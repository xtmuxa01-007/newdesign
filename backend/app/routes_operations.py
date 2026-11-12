"""Xato moliyaviy amalni joriy hisobdan chiqarish; asl nusxa va audit saqlanadi."""
from collections import defaultdict
from decimal import Decimal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .db import get_db
from .models import (Sale, SaleItem, SaleEdit, Receipt, Stock, Product, Audit, Debt,
                     DebtPayment, MiniDiscount, MiniDiscountShare, StockAdjustment,
                     SupplierPayment, BranchExpense, OperationCancellation)
from .models import DebtInstallment, DebtRevision
from .schemas import CancelOperation
from .security import manager, branch_scope, branch_write
from .branch_lifecycle import is_owner
from .accounting import balances, supplier_debt
from .common import row, clean, audit
from .operation_history import (operation_model, source_fingerprint,
                                require_cancellation_user, audit_operation_reference,
                                _central_id, _utc)

router = APIRouter(prefix='/api/operations', tags=['operations'])


def linked_audits(db, kind, source):
    ids = []
    for entry in db.scalars(select(Audit).where(Audit.branch_id == source.branch_id).order_by(Audit.id)):
        reference = audit_operation_reference(entry)
        if not reference or reference[0] != kind or not reference[1]:
            continue
        if (reference[2] and reference[2] != source.request_id) or _utc(entry.created_at) < _utc(source.created_at):
            continue
        if _central_id(db, entry, kind, reference[1]) == source.id:
            ids.append(entry.id)
    return ids


def receipt_history(db, audit_ids):
    for audit_id in audit_ids:
        entry = db.get(Audit, audit_id)
        if entry and entry.action == 'Omborga kirim' and isinstance(entry.detail, dict):
            if 'price' in entry.detail.get('before', {}):
                return entry.detail
    return {}


def restore_receipt_terms(db, source, stock, snapshot):
    """Eng oxirgi kirim bekor bo'lganda bekor qilingan oldingi narx qaytmasin."""
    entries = list(db.scalars(select(Receipt).where(Receipt.branch_id == source.branch_id,
        Receipt.product_id == source.product_id).order_by(Receipt.created_at, Receipt.id)))
    if entries[-1].id != source.id:
        return
    histories = [(r.created_at, r.id, receipt_history(db, linked_audits(db, 'receipt', r)))
                 for r in entries]
    for marker in db.scalars(select(OperationCancellation).where(
            OperationCancellation.branch_id == source.branch_id,
            OperationCancellation.kind == 'receipt')):
        record = marker.snapshot.get('record', {})
        if record.get('product_id') == source.product_id:
            from datetime import datetime
            histories.append((datetime.fromisoformat(record['created_at']), record['id'],
                              {'before': marker.snapshot.get('receipt_before', {})}))
    histories.sort(key=lambda h: (_utc(h[0]), h[1]))
    baseline = histories[0][2].get('before', {})
    remaining = [r for r in entries if r.id != source.id]
    if remaining:
        prior_receipt = remaining[-1]
        stock.price = prior_receipt.price
        prior = receipt_history(db, linked_audits(db, 'receipt', prior_receipt)).get('after', {})
        discount_since = prior_receipt.created_at
    else:
        if 'price' not in baseline:
            raise HTTPException(409, 'Kirimdan oldingi narx tarixi topilmadi. Qoldiqni alohida tuzating.')
        stock.price = Decimal(str(baseline['price']))
        prior = baseline
        discount_since = histories[0][0]
    # Kirimlar orasida yoki oxirgi kirimdan keyin qo'lda belgilangan narx
    # keyingi kirim bekor qilinganda yo'qolmasin. Yangi faol kirim uni bosadi.
    from .stock_prices import PRICE_CHANGE_ACTION
    explicit_price = db.scalar(select(Audit).where(Audit.branch_id == source.branch_id,
        Audit.action == PRICE_CHANGE_ACTION, Audit.created_at >= discount_since,
        Audit.detail['product_id'].as_integer() == source.product_id
    ).order_by(Audit.created_at.desc(), Audit.id.desc()).limit(1))
    if explicit_price:
        stock.price = Decimal(str(explicit_price.detail['after']))
    explicit = db.scalar(select(Audit).where(Audit.branch_id == source.branch_id,
        Audit.action == 'Chegirma o‘zgartirildi', Audit.created_at >= discount_since,
        Audit.detail['product_id'].as_integer() == source.product_id
    ).order_by(Audit.created_at.desc(), Audit.id.desc()).limit(1))
    if explicit:
        stock.discount = Decimal(str(explicit.detail['after']))
    elif 'discount' in prior:
        stock.discount = Decimal(str(prior['discount']))
    else:
        raise HTTPException(409, 'Kirimdan oldingi chegirma tarixi topilmadi. Qoldiqni alohida tuzating.')


def sale_dependents(db, sale):
    records = {
        'sale_items': list(db.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.id))),
        'sale_edits': list(db.scalars(select(SaleEdit).where(SaleEdit.sale_id == sale.id).order_by(SaleEdit.id))),
        'debts': list(db.scalars(select(Debt).where(Debt.sale_id == sale.id).order_by(Debt.id))),
        'mini_discounts': list(db.scalars(select(MiniDiscount).where(MiniDiscount.sale_id == sale.id).order_by(MiniDiscount.id))),
    }
    records['debt_payments'] = list(db.scalars(select(DebtPayment).where(DebtPayment.debt_id.in_([d.id for d in records['debts']])).order_by(DebtPayment.id)))
    for name, model in (('debt_installments', DebtInstallment), ('debt_revisions', DebtRevision)):
        records[name] = list(db.scalars(select(model).join(Debt,
            (model.debt_id == Debt.id) & (model.debt_created_at == Debt.created_at)).where(
            model.origin == 'sale', Debt.sale_id == sale.id).order_by(model.id)))
    records['mini_discount_shares'] = list(db.scalars(select(MiniDiscountShare).where(MiniDiscountShare.mini_discount_id.in_([m.id for m in records['mini_discounts']])).order_by(MiniDiscountShare.id)))
    return records


def lock_stocks(db, branch_id, product_ids):
    db.scalars(select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()).all()
    stocks = {s.product_id: s for s in db.scalars(select(Stock).where(
        Stock.branch_id == branch_id, Stock.product_id.in_(product_ids)
    ).order_by(Stock.product_id).with_for_update().execution_options(populate_existing=True))}
    if set(stocks) != set(product_ids):
        raise HTTPException(409, 'Amalga tegishli ombor yozuvi topilmadi.')
    return stocks


def require_no_later_adjustment(db, source, product_ids):
    if db.scalar(select(StockAdjustment.id).where(
            StockAdjustment.branch_id == source.branch_id,
            StockAdjustment.product_id.in_(product_ids),
            StockAdjustment.created_at > source.created_at).limit(1)):
        raise HTTPException(409, 'Bu amaldan keyin qoldiq tuzatilgan. Avval keyingi qoldiq tuzatishini tekshiring.')


def financial_state(db, branch_id, suppliers):
    return {(scope, supplier): supplier_debt(db, supplier, scope)['debt']
            for scope in (None, branch_id) for supplier in suppliers}, {
        scope: balances(db, scope) for scope in (None, branch_id)}


def require_safe_balances(db, branch_id, suppliers, before):
    old_suppliers, old_balances = before
    debts, ledgers = financial_state(db, branch_id, suppliers)
    for key, value in debts.items():
        if value < 0 and value < old_suppliers[key]:
            raise HTTPException(409, 'Bekor qilish ta’minotchi hisobini manfiy qiladi. Avval bog‘liq to‘lov yoki xarajatni tekshiring.')
    for scope, values in ledgers.items():
        for name in ('cash', 'card', 'donation_balance', 'customer_debt'):
            if values[name] < 0 and values[name] < old_balances[scope][name]:
                raise HTTPException(409, 'Bekor qilish pul yoki qarz hisobini manfiy qiladi. Avval keyingi bog‘liq amallarni tekshiring.')


def cancel_operation(db, kind, operation_id, data, user):
    """Commit tashqarida; HTTP endpoint va texnik tuzatish bir xil tranzaksiyani ishlatadi."""
    model = operation_model(kind)
    previous = db.scalar(select(OperationCancellation).where(OperationCancellation.request_id == data.request_id))
    if previous:
        require_cancellation_user(user, previous.branch_id)
        if (previous.kind != kind or previous.operation_id != operation_id or
                previous.user_id != user.id or previous.reason != data.reason or
                previous.snapshot.get('fingerprint') != data.expected_fingerprint):
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa bekor qilishga tegishli.')
        return previous
    source = db.get(model, operation_id)
    if source is None:
        # READ COMMITTEDda oldingi marker SELECTidan keyin ayni so'rov commit
        # bo'lishi mumkin; yo'qolgan javobni tekshirish 404ga aylanmasin.
        if db.scalar(select(OperationCancellation.id).where(
                OperationCancellation.request_id == data.request_id)):
            return cancel_operation(db, kind, operation_id, data, user)
        raise HTTPException(404, 'Asl amal topilmadi yoki allaqachon bekor qilingan. Tarixni yangilang.')
    require_cancellation_user(user, source.branch_id)
    branch_scope(db, user, source.branch_id, required=True)
    branch_write(db, source.branch_id)
    source = db.scalar(select(model).where(model.id == operation_id).with_for_update().execution_options(populate_existing=True))
    # Qulf kutilayotganda boshqa operator shu amalni bekor qilgan bo'lishi mumkin.
    previous = db.scalar(select(OperationCancellation).where(OperationCancellation.request_id == data.request_id))
    if previous:
        return cancel_operation(db, kind, operation_id, data, user)
    if source is None:
        raise HTTPException(409, 'Amal boshqa operator tomonidan bekor qilindi. Tarixni yangilang.')
    if kind == 'stock_adjustment' and not is_owner(db, user):
        raise HTTPException(403, 'Qoldiq tuzatishini faqat Programmist bekor qiladi.')
    fingerprint = source_fingerprint(db, kind, source)
    if fingerprint != data.expected_fingerprint:
        raise HTTPException(409, 'Amal holati o‘zgargan. Tarixni yangilab, joriy ma’lumotni tekshiring.')
    snapshot = {'record': row(source), 'audit_ids': linked_audits(db, kind, source), 'fingerprint': fingerprint}
    if kind == 'debt_payment':
        debt = db.get(Debt, source.debt_id)
        snapshot['debt'] = row(debt) if debt else None
    dependents = sale_dependents(db, source) if kind == 'sale' else {}
    if kind == 'sale' and any(p.cancelled_at is None for p in dependents['debt_installments']):
        raise HTTPException(409, 'Savdoda qisman qarz to‘lovi bor. Avval qarz to‘lovlarini tekshirib bekor qiling.')
    snapshot.update({name: [row(v) for v in values] for name, values in dependents.items()})
    supplier_ids = {i.supplier_id for i in dependents.get('sale_items', [])}
    if kind in ('supplier_payment', 'expense'):
        supplier_ids.add(source.supplier_id)
    before = financial_state(db, source.branch_id, supplier_ids)
    stocks = {}
    if kind == 'sale':
        products = sorted({i.product_id for i in dependents['sale_items']})
        require_no_later_adjustment(db, source, products)
        stocks = lock_stocks(db, source.branch_id, products)
        snapshot['stock_before'] = [row(s) for s in stocks.values()]
        quantities = defaultdict(Decimal)
        for item in dependents['sale_items']:
            quantities[item.product_id] += item.kg
        for product_id, kg in quantities.items():
            stocks[product_id].kg += kg
    elif kind in ('receipt', 'stock_adjustment'):
        stocks = lock_stocks(db, source.branch_id, [source.product_id])
        stock = stocks[source.product_id]
        snapshot['stock_before'] = [row(stock)]
        if kind == 'receipt':
            receipt_detail = receipt_history(db, snapshot['audit_ids'])
            snapshot['receipt_before'] = receipt_detail.get('before', {})
            require_no_later_adjustment(db, source, [source.product_id])
            if stock.kg < source.kg:
                raise HTTPException(409, 'Kirimdagi mahsulot sotilgan: bekor qilish qoldiqni manfiy qiladi.')
            stock.kg -= source.kg
            restore_receipt_terms(db, source, stock, snapshot)
        else:
            require_no_later_adjustment(db, source, [source.product_id])
            later_receipt = db.scalar(select(Receipt.id).where(Receipt.branch_id == source.branch_id,
                Receipt.product_id == source.product_id, Receipt.created_at > source.created_at).limit(1))
            later_sale = db.scalar(select(Sale.id).join(SaleItem).where(Sale.branch_id == source.branch_id,
                SaleItem.product_id == source.product_id, Sale.created_at > source.created_at).limit(1))
            if later_receipt or later_sale or stock.kg != source.kg:
                raise HTTPException(409, 'Qoldiq tuzatishidan keyin boshqa ombor amali bor. Avval keyingi amallarni tekshiring.')
            stock.kg = source.before_kg
    snapshot['stock_after'] = [row(s) for s in stocks.values()]
    marker = OperationCancellation(kind=kind, operation_id=operation_id,
        original_request_id=source.request_id, request_id=data.request_id,
        branch_id=source.branch_id, user_id=user.id, actor=user.name,
        reason=data.reason, snapshot=clean(snapshot))
    db.add(marker)
    db.flush()
    if kind == 'sale':
        for payment in dependents['debt_payments']:
            db.add(OperationCancellation(kind='debt_payment', operation_id=payment.id,
                original_request_id=payment.request_id, request_id=str(uuid.uuid4()),
                branch_id=payment.branch_id, user_id=user.id, actor=user.name,
                reason=data.reason, snapshot=clean({'record': row(payment),
                    'debt': row(db.get(Debt, payment.debt_id)),
                    'audit_ids': linked_audits(db, 'debt_payment', payment),
                    'parent_cancellation_id': marker.id,
                    'fingerprint': source_fingerprint(db, 'debt_payment', payment)})))
        for name in ('mini_discount_shares', 'mini_discounts', 'sale_edits', 'debt_payments', 'debts', 'sale_items'):
            for value in dependents[name]:
                db.delete(value)
            db.flush()
    db.delete(source)
    db.flush()
    require_safe_balances(db, marker.branch_id, supplier_ids, before)
    audit(db, user, 'Amal bekor qilindi', marker.branch_id, cancellation_id=marker.id,
          kind=kind, operation_id=operation_id, reason=data.reason, before=snapshot['record'])
    db.flush()
    return marker


@router.post('/{kind}/{operation_id}/cancel')
def cancel(kind: str, operation_id: int, data: CancelOperation,
           user=Depends(manager), db=Depends(get_db)):
    try:
        result = cancel_operation(db, kind, operation_id, data, user)
        response = {'ok': True, 'cancellation': row(result)}
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
