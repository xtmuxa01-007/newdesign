"""72 soatlik savdo tuzatishi. Ombor va hisoblar bitta tranzaksiyada yangilanadi."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from fastapi import HTTPException
from sqlalchemy import select, func
from .models import (Branch, Sale, SaleItem, SaleEdit, Stock, Product, Debt, DebtPayment,
                     MiniDiscount, MiniDiscountShare, DebtInstallment)
from .accounting import balances, supplier_debt, line_total, money
from .donation_limits import require_donation_limit
from .common import clean, audit
from .mini_discounts import allocate
from .product_lifecycle import product_write


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def revision(db, sale_id):
    return db.scalar(select(func.count()).select_from(SaleEdit).where(SaleEdit.sale_id == sale_id))


def snapshot(db, sale):
    items = list(db.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.id)))
    debt = db.scalar(select(Debt).where(Debt.sale_id == sale.id))
    payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id)) if debt else None
    installments = list(db.scalars(select(DebtInstallment).where(
        DebtInstallment.origin == 'sale', DebtInstallment.debt_id == debt.id,
        DebtInstallment.debt_created_at == debt.created_at,
        DebtInstallment.cancelled_at.is_(None)).order_by(DebtInstallment.id))) if debt and not os.getenv('CRM_BRANCH_ID') else []
    mini = db.scalar(select(MiniDiscount).where(MiniDiscount.sale_id == sale.id))
    return clean(dict(customer=sale.customer, total=sale.total, cash=sale.cash, card=sale.card,
                     donation=sale.donation, mini_discount=mini.amount if mini else Decimal(0),
                     debt=debt.amount if debt else Decimal(0),
                     debt_cash=(payment.cash if payment else Decimal(0)) + sum((p.cash for p in installments), Decimal(0)),
                     debt_card=(payment.card if payment else Decimal(0)) + sum((p.card for p in installments), Decimal(0)),
                     items=[{k: getattr(i, k) for k in ('product_id','supplier_id','name','sku','kg','price','discount','total')} for i in items]))


def apply_edit(db, sale_id, data, user, edited_at=None):
    """Commit tashqarida. Lokal va markaz bir xil qoidani bajaradi."""
    if user is None or not user.active or user.role not in ('boss', 'admin'):
        raise HTTPException(403, 'Savdoni faqat boshliq yoki admin tuzatadi.')
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(404, 'Savdo topilmadi.')
    if user.role == 'admin' and user.branch_id != sale.branch_id:
        raise HTTPException(403, 'Boshqa filial savdosini o‘zgartirib bo‘lmaydi.')
    db.scalar(select(Branch).where(Branch.id == sale.branch_id).with_for_update())
    sale = db.scalar(select(Sale).where(Sale.id == sale_id).with_for_update()
                     .execution_options(populate_existing=True))
    if sale is None:
        raise HTTPException(409, 'Savdo boshqa oynada bekor qilingan. Tarixni yangilang.')
    old = db.scalar(select(SaleEdit).where(SaleEdit.request_id == data.request_id))
    command = data.model_dump(mode='json')
    if old:
        if old.sale_id != sale_id or old.user_id != user.id or old.command != command:
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa tuzatishga tegishli.')
        return old
    moment = utc(edited_at or datetime.now(timezone.utc))
    created = utc(sale.created_at)
    if moment < created or moment >= created + timedelta(days=3):
        raise HTTPException(409, 'Savdodan 72 soat o‘tgan. Tahrirlash muddati tugagan.')
    if moment > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(409, 'Tuzatish vaqti kelajakda bo‘lishi mumkin emas.')
    version = revision(db, sale_id)
    if version != data.version:
        raise HTTPException(409, 'Savdo boshqa oynada o‘zgartirilgan. Qayta oching.')
    if not data.reason.strip():
        raise HTTPException(422, 'Tuzatish sababini yozing.')
    active_receipt = db.scalar(select(DebtInstallment.id).join(Debt,
        (DebtInstallment.debt_id == Debt.id) &
        (DebtInstallment.debt_created_at == Debt.created_at)).where(
        DebtInstallment.origin == 'sale', Debt.sale_id == sale_id,
        DebtInstallment.cancelled_at.is_(None)).limit(1)) if not os.getenv('CRM_BRANCH_ID') else None
    if active_receipt:
        raise HTTPException(409, 'Savdoda qisman qarz to‘lovi bor. Savdoni tuzatishdan avval qarz to‘lovlarini tekshirib bekor qiling.')
    items = list(db.scalars(select(SaleItem).where(SaleItem.sale_id == sale_id).order_by(SaleItem.id)))
    proposed = {i.item_id: i for i in data.items}
    if len(proposed) != len(data.items) or not set(proposed).issubset({i.id for i in items}):
        raise HTTPException(422, 'Faqat shu savdoga tegishli qatorlarni bir martadan yuboring.')
    if len({i.product_id for i in data.items}) != len(data.items):
        raise HTTPException(422, 'Bir mahsulotni ikki qatorga tanlamang.')
    before = snapshot(db, sale)
    before_account = balances(db, sale.branch_id)
    suppliers = {i.supplier_id for i in items}
    delta = defaultdict(Decimal)
    for item in items:
        delta[item.product_id] += item.kg
    for line in data.items:
        delta[line.product_id] -= line.kg
    for product_id, kg in sorted(delta.items()):
        product_write(db, product_id)
        stock = db.scalar(select(Stock).where(Stock.branch_id == sale.branch_id, Stock.product_id == product_id).with_for_update())
        if stock is None or stock.kg + kg < 0:
            raise HTTPException(409, 'Tanlangan mahsulot omborda yetarli emas.')
        stock.kg += kg
    kept_items = []
    removed_items = []
    for item in items:
        if item.id not in proposed:
            removed_items.append(item)
            continue
        line = proposed[item.id]
        product = db.get(Product, line.product_id)
        if product is None:
            raise HTTPException(422, 'Mahsulot topilmadi.')
        if item.product_id != product.id:
            item.name, item.sku = product.name, product.sku
        item.product_id, item.supplier_id = product.id, product.supplier_id
        item.kg, item.price, item.discount = line.kg, line.price, line.discount
        item.total = line_total(item.kg, item.price, item.discount)
        suppliers.add(item.supplier_id)
        kept_items.append(item)
    items = kept_items
    gross = sum((i.total for i in items), Decimal(0))
    mini = db.scalar(select(MiniDiscount).where(MiniDiscount.sale_id == sale_id))
    # Avval berilgan mini chegirma saqlanadi, yangi summaga ulushlari qayta ajratiladi.
    if mini:
        if gross <= mini.amount or (data.cash + data.card) % 1000:
            raise HTTPException(422, 'Mini chegirmali savdoda yakuniy to‘lov minglik bo‘lsin va jami chegirmadan katta bo‘lsin.')
        shares = allocate(mini.amount, [i.total for i in items])
        existing = {s.sale_item_id: s for s in db.scalars(select(MiniDiscountShare).where(MiniDiscountShare.mini_discount_id == mini.id))}
        # O'chirilgan yuqori IDni SQLite qayta ishlatmasligi uchun ID oldindan olinadi.
        next_id = (db.scalar(select(func.max(MiniDiscountShare.id))) or 0) + 1
        for item, amount in zip(items, shares):
            share = existing.get(item.id)
            if amount:
                if share is None:
                    share = MiniDiscountShare(mini_discount_id=mini.id, sale_item_id=item.id)
                    if db.bind.dialect.name == 'sqlite':
                        share.id = next_id
                    next_id += 1
                    db.add(share)
                share.amount, share.supplier_id = amount, item.supplier_id
            elif share:
                db.delete(share)
            item.total -= amount
        for item in removed_items:
            if item.id in existing:
                db.delete(existing[item.id])
        # Ulushlar tashqi kalit bilan savdo qatoriga bog'langan.
        db.flush()
        mini.original_total = gross
    for item in removed_items:
        db.delete(item)
    total = sum((i.total for i in items), Decimal(0))
    paid = data.cash + data.card
    debt = db.scalar(select(Debt).where(Debt.sale_id == sale_id))
    payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id)) if debt else None
    if debt:
        if paid >= total:
            raise HTTPException(422, 'Qarz savdosida dastlabki to‘lov jamidan kam bo‘lsin; qarz to‘lovini alohida kiriting.')
        debt.amount = money(total - paid)
        if payment:
            if data.debt_cash + data.debt_card != debt.amount:
                raise HTTPException(422, 'Yopilgan qarzning tuzatilgan naqd/karta to‘lovi yangi qarz summasiga teng bo‘lsin.')
            payment.cash, payment.card = data.debt_cash, data.debt_card
        elif data.debt_cash or data.debt_card:
            raise HTTPException(422, 'Bu qarz hali yopilmagan; uni Qarzlar bo‘limida to‘lang.')
    elif paid < total or data.debt_cash or data.debt_card:
        raise HTTPException(422, 'Naqd va karta jami savdoni qoplashi kerak.')
    if mini and paid != total:
        raise HTTPException(422, 'Mini chegirmali savdoda to‘lov tuzatilgan jamiga teng bo‘lsin.')
    donation = money(max(paid - total, Decimal(0)))
    require_donation_limit(donation)
    sale.customer, sale.total = data.customer, total
    sale.cash, sale.card = data.cash, data.card
    sale.donation = donation
    db.flush()
    account = balances(db, sale.branch_id)
    # A physical handover can legitimately leave the recorded cash/card ledger
    # negative. Unrelated or improving edits remain possible; an edit must not
    # create a new deficit or worsen one already recorded.
    if (any(account[k] < min(before_account[k], Decimal(0)) for k in ('cash', 'card')) or
            any(account[k] < 0 for k in ('donation_balance', 'customer_debt'))):
        raise HTTPException(409, 'Tuzatish kassani yoki ehson hisobini manfiy qiladi. Avval oldingi chiqimlarni tekshiring.')
    if any(supplier_debt(db, s, sale.branch_id)['debt'] < 0 for s in suppliers):
        raise HTTPException(409, 'Ta’minotchiga avval berilgan yoki ishlatilgan puldan kam savdo qoldirib bo‘lmaydi.')
    after = snapshot(db, sale)
    edit = SaleEdit(request_id=data.request_id, sale_id=sale.id, branch_id=sale.branch_id,
                    user_id=user.id, version=version + 1, reason=data.reason.strip(),
                    command=command, before=before, after=after, created_at=moment)
    db.add(edit)
    audit(db, user, 'Savdo tuzatildi', sale.branch_id, sale_id=sale.id,
          reason=edit.reason, version=edit.version, before=before, after=after)
    db.flush()
    return edit
