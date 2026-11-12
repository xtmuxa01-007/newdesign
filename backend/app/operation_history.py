"""Tarix yozuvini asl amalga bog'lash va bekor qilingan so'rovni to'xtatish.

Audit jurnali hamda bekor qilish snapshotlari o'chirilmaydi. Identifikatorlar
eski SQLite bazalarda qayta ishlatilishi mumkin: tarix faqat raqamga qarab
boshqa yangi amalni bekor qilishga ruxsat bermaydi.
"""
import os
import hashlib
import json
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy import select

from .models import (
    Sale, Receipt, SupplierPayment, DonationPayment, OtherPayment, BranchExpense,
    DebtPayment, StockAdjustment, OperationCancellation,
    SaleItem, SaleEdit, Debt, MiniDiscount, MiniDiscountShare,
    DebtInstallment, DebtRevision,
)
from .common import clean, row


OPERATION_MODELS = {
    'sale': Sale,
    'receipt': Receipt,
    'supplier_payment': SupplierPayment,
    'donation_payment': DonationPayment,
    'other_payment': OtherPayment,
    'expense': BranchExpense,
    'debt_payment': DebtPayment,
    'stock_adjustment': StockAdjustment,
}


def operation_model(kind):
    model = OPERATION_MODELS.get(kind)
    if model is None:
        raise HTTPException(422, 'Bu turdagi tarix amalini bekor qilib bo‘lmaydi.')
    return model


def cancellation_for_request(db, kind, request_id):
    """Bitta amalning eski so'rovi yangi moliyaviy yozuvga aylanmasin."""
    operation_model(kind)
    return db.scalar(select(OperationCancellation).where(
        OperationCancellation.kind == kind,
        OperationCancellation.original_request_id == request_id,
    ))


def reject_cancelled_request(db, kind, request_id):
    # Bekor qilish faqat markazda bajariladi. Eski lokal bazalarda bu yangi
    # jadval bo'lmasligi mumkin; saqlangan amallar markazda yana tekshiriladi.
    if os.getenv('CRM_BRANCH_ID'):
        return
    if cancellation_for_request(db, kind, request_id) is not None:
        raise HTTPException(409, 'Bu amal bekor qilingan. To‘g‘ri yangi amal uchun yangi so‘rov yarating.')


def require_cancellation_user(user, branch_id):
    """Bekor qilish faqat umumiy bazada, adminning o'z filialida bajariladi."""
    if user is None or not user.active or user.role not in ('boss', 'admin'):
        raise HTTPException(403, 'Amalni faqat boshliq yoki admin bekor qiladi.')
    if user.role == 'admin' and user.branch_id != branch_id:
        raise HTTPException(403, 'Boshqa filial amalini bekor qilib bo‘lmaydi.')
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Amalni web yoki umumiy bazaga ulangan yangi EXE orqali bekor qiling.')


def source_fingerprint(db, kind, source):
    """Tasdiqlash oynasi ochilgach o'zgargan amal yashirin bekor qilinmasin.

    Savdo qatorlari, tuzatishlari, qarzi va to'lovi ham bitta holatga kiradi.
    Tartib ORM qaytargan tasodifiy qator tartibiga bog'liq emas.
    """
    model = operation_model(kind)
    if not isinstance(source, model):
        raise HTTPException(422, 'Amal turi va moliyaviy yozuv mos emas.')
    payload = {'source': row(source)}
    if kind == 'sale':
        for key, dependent in (('sale_items', SaleItem), ('sale_edits', SaleEdit),
                               ('debts', Debt), ('mini_discounts', MiniDiscount)):
            payload[key] = [row(item) for item in db.scalars(
                select(dependent).where(dependent.sale_id == source.id).order_by(dependent.id))]
        debt_ids = [item['id'] for item in payload['debts']]
        mini_ids = [item['id'] for item in payload['mini_discounts']]
        payload['debt_payments'] = [row(item) for item in db.scalars(
            select(DebtPayment).where(DebtPayment.debt_id.in_(debt_ids)).order_by(DebtPayment.id))]
        dependents = () if os.getenv('CRM_BRANCH_ID') else (
            ('debt_installments', DebtInstallment), ('debt_revisions', DebtRevision))
        for key, dependent in dependents:
            payload[key] = [row(item) for item in db.scalars(select(dependent).join(Debt,
                (dependent.debt_id == Debt.id) & (dependent.debt_created_at == Debt.created_at)).where(
                dependent.origin == 'sale', Debt.sale_id == source.id).order_by(dependent.id))]
        payload['mini_discount_shares'] = [row(item) for item in db.scalars(
            select(MiniDiscountShare).where(MiniDiscountShare.mini_discount_id.in_(mini_ids))
            .order_by(MiniDiscountShare.id))]
    elif kind == 'debt_payment':
        debt = db.get(Debt, source.debt_id)
        payload['debt'] = row(debt) if debt else None
        if debt and not os.getenv('CRM_BRANCH_ID'):
            from .debt_management import installments, revisions
            payload['installments'] = [row(v) for v in installments(db, 'sale', debt.id)]
            payload['revisions'] = [row(v) for v in revisions(db, 'sale', debt.id)]
    encoded = json.dumps(clean(payload), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _positive_id(value):
    # JSONdagi bool son sifatida qabul qilinmasin.
    return value if type(value) is int and value > 0 else None


def audit_operation_reference(entry):
    """Ma'lum moliyaviy auditlardan (kind, id, request_id) olinadi."""
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    action = entry.action
    if action in ('Savdo yakunlandi', 'Qarzga savdo qilindi',
                  'Mini chegirma berildi', 'Savdo tuzatildi'):
        return 'sale', _positive_id(detail.get('sale_id')), detail.get('request_id')
    if action == 'Omborga kirim':
        return 'receipt', _positive_id(detail.get('receipt_id')), detail.get('request_id')
    if action == 'Ta’minotchiga pul berildi':
        return 'supplier_payment', _positive_id(detail.get('payment_id')), detail.get('request_id')
    if action == 'Ehson puli berildi':
        return 'donation_payment', _positive_id(detail.get('payment_id')), detail.get('request_id')
    if action == 'Boshqa pul berildi':
        return 'other_payment', _positive_id(detail.get('payment_id')), detail.get('request_id')
    if action == 'Filial xarajati qilindi':
        source = detail.get('expense', {})
        if isinstance(source, dict):
            return 'expense', _positive_id(source.get('id')), source.get('request_id')
    if action == 'Qarz to‘landi':
        source = detail.get('payment', {})
        if isinstance(source, dict):
            return 'debt_payment', _positive_id(source.get('id')), source.get('request_id')
    if action == 'Ombor qoldig‘i tuzatildi':
        return 'stock_adjustment', _positive_id(detail.get('adjustment_id')), detail.get('request_id')
    return None


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _cancelled_data(marker):
    return clean({'kind': marker.kind, 'id': marker.operation_id,
                  'cancelled': True, 'can_cancel': False,
                  'reason': marker.reason, 'cancelled_at': marker.cancelled_at})


def _central_id(db, entry, kind, operation_id):
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    source = detail.get('_sync_source')
    if not isinstance(source, dict):
        return operation_id
    device_id = source.get('device_id')
    if not isinstance(device_id, str):
        return None
    from .sync_projection import identity
    mapping = identity(db, device_id, operation_model(kind).__tablename__, operation_id)
    return mapping.central_id if mapping else None


def operation_for_source(db, kind, source, user):
    """Joriy amalning faqat o'qiladigan bekor qilish konteksti."""
    if not isinstance(source, operation_model(kind)):
        raise HTTPException(422, 'Amal turi va moliyaviy yozuv mos emas.')
    reason = None
    try:
        require_cancellation_user(user, source.branch_id)
    except HTTPException as failure:
        reason = failure.detail
    if reason is None and kind == 'stock_adjustment':
        from .branch_lifecycle import is_owner
        if not is_owner(db, user):
            reason = 'Qoldiq tuzatishini faqat Programmist bekor qiladi.'
    if reason is None:
        from .branch_lifecycle import is_archived
        if is_archived(db, source.branch_id):
            reason = 'Filial arxivlangan. Avval Programmist filialni tiklashi kerak.'
    if reason is None:
        from .shared_mode import LEGACY_WRITER_REASON, has_legacy_writer
        if has_legacy_writer(db, source.branch_id):
            reason = LEGACY_WRITER_REASON
    if kind == 'sale':
        from .sale_edits import snapshot
        summary = snapshot(db, source)
        active = db.scalar(select(DebtInstallment.id).join(Debt,
            (DebtInstallment.debt_id == Debt.id) &
            (DebtInstallment.debt_created_at == Debt.created_at)).where(
            DebtInstallment.origin == 'sale', Debt.sale_id == source.id,
            DebtInstallment.cancelled_at.is_(None)).limit(1)) if not os.getenv('CRM_BRANCH_ID') else None
        if active and reason is None:
            reason = 'Savdoda qisman qarz to‘lovi bor. Avval qarz to‘lovlarini tekshirib bekor qiling.'
    else:
        fields = ('amount', 'cash', 'card', 'kg', 'price', 'before_kg', 'method',
                  'recipient', 'note', 'reason')
        summary = clean({name: getattr(source, name) for name in fields if hasattr(source, name)})
    result = {'kind': kind, 'id': source.id, 'cancelled': False, 'can_cancel': reason is None,
              'summary': summary, 'expected_fingerprint': source_fingerprint(db, kind, source)}
    if reason is not None:
        result['reason'] = reason
    return result


def operation_for_audit(db, entry, user):
    """UI: operation {kind,id,cancelled,can_cancel,reason?,cancelled_at?}."""
    from .debt_management import installment_operation_for_audit
    installment_operation = installment_operation_for_audit(db, entry, user)
    if installment_operation is not None:
        return installment_operation
    from .opening_debts import opening_operation_for_audit
    opening_operation = opening_operation_for_audit(db, entry, user)
    if opening_operation is not None:
        return opening_operation
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    cancellation_id = _positive_id(detail.get('cancellation_id'))
    if cancellation_id:
        marker = db.get(OperationCancellation, cancellation_id)
        if marker and marker.branch_id == entry.branch_id:
            return _cancelled_data(marker)
    reference = audit_operation_reference(entry)
    if reference is None:
        return None
    kind, operation_id, request_hint = reference
    if operation_id is None:
        return None
    operation_id = _central_id(db, entry, kind, operation_id)
    if operation_id is None:
        return {'kind': kind, 'id': reference[1], 'cancelled': False,
                'can_cancel': False, 'reason': 'Asl amalning markaziy identifikatori topilmadi.'}
    markers = list(db.scalars(select(OperationCancellation).where(
        OperationCancellation.kind == kind,
        OperationCancellation.operation_id == operation_id,
        OperationCancellation.branch_id == entry.branch_id,
    ).order_by(OperationCancellation.id.desc())))
    for marker in markers:
        snapshot = marker.snapshot if isinstance(marker.snapshot, dict) else {}
        audit_ids = snapshot.get('audit_ids', [])
        if (isinstance(audit_ids, list) and entry.id in audit_ids) or (
                isinstance(request_hint, str) and request_hint == marker.original_request_id):
            return _cancelled_data(marker)
    source = db.get(operation_model(kind), operation_id)
    # Yangi qayta ishlatilgan ID eski tarixning nusxasi deb qabul qilinmaydi.
    if source is not None and (source.branch_id != entry.branch_id or
            _utc(source.created_at) > _utc(entry.created_at) or
            (request_hint and source.request_id != request_hint)):
        source = None
    if source is None:
        # Eski yozuvlarda request_id auditda yo'q. Bekor qilish vaqti yangi
        # yaratilgan amal auditi bilan eski amal auditini ajratib turadi.
        for marker in markers:
            if _utc(entry.created_at) <= _utc(marker.cancelled_at):
                return _cancelled_data(marker)
        return {'kind': kind, 'id': operation_id, 'cancelled': False,
                'can_cancel': False, 'reason': 'Asl moliyaviy yozuv topilmadi.'}
    return operation_for_source(db, kind, source, user)
