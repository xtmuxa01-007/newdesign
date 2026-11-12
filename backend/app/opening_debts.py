"""Oldingi qarzlar: alohida manba, to'liq to'lov va o'zgarmas bekor qilish izi."""
import hashlib
import json
import os
from datetime import timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from .common import audit, clean, row
from .models import OpeningDebt, OpeningDebtPayment, OpeningDebtCancellation, Debtor, User, Audit
from .security import branch_scope, branch_write
from .operation_history import require_cancellation_user
from . import debt_management as management


KINDS = {'opening_debt': ('debt', OpeningDebt),
         'opening_debt_payment': ('payment', OpeningDebtPayment)}


def central_only():
    # Eski offline protokoli bu jadvallarni markazga o'tkazmaydi.
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Oldingi qarzni web yoki umumiy bazaga ulangan EXE orqali kiriting.')


def command(data):
    result = clean(data.model_dump())
    result['amount'] = format(data.amount.quantize(Decimal('0.01')), 'f')
    return result


def reject_cancelled_request(db, kind, request_id):
    if db.scalar(select(OpeningDebtCancellation.id).where(
            OpeningDebtCancellation.kind == kind,
            OpeningDebtCancellation.original_request_id == request_id)):
        raise HTTPException(409, 'Bu amal bekor qilingan. Yangi amal uchun yangi so‘rov yarating.')


def payment_for(db, debt_id):
    return db.scalar(select(OpeningDebtPayment).where(OpeningDebtPayment.debt_id == debt_id)
                     .execution_options(populate_existing=True))


def source_fingerprint(db, kind, source):
    if kind not in KINDS or not isinstance(source, KINDS[kind][1]):
        raise HTTPException(422, 'Oldingi qarz amalining turi mos emas.')
    payload = {'source': row(source)}
    if kind == 'opening_debt':
        payment = payment_for(db, source.id)
        payload['payment'] = row(payment) if payment else None
        payload['installments'] = [row(item) for item in management.installments(db, 'opening', source.id)]
        payload['revisions'] = [row(item) for item in management.revisions(db, 'opening', source.id)]
    else:
        debt = db.get(OpeningDebt, source.debt_id)
        payload['debt'] = row(debt) if debt else None
        if debt:
            payload['installments'] = [row(item) for item in management.installments(db, 'opening', debt.id)]
            payload['revisions'] = [row(item) for item in management.revisions(db, 'opening', debt.id)]
    encoded = json.dumps(clean(payload), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def operation_data(db, kind, source, user):
    from .branch_lifecycle import is_archived
    can_cancel = bool(user and user.active and user.role in ('boss', 'admin') and
                      (user.role == 'boss' or user.branch_id == source.branch_id) and
                      not os.getenv('CRM_BRANCH_ID') and not is_archived(db, source.branch_id))
    debt = source if kind == 'opening_debt' else db.get(OpeningDebt, source.debt_id)
    payment = payment_for(db, debt.id) if debt else None
    if kind == 'opening_debt' and (payment or (debt and management.active_installment_total(db, 'opening', debt.id) > 0)):
        can_cancel = False
    summary = {'amount': debt.amount, 'due_date': debt.due_date, 'note': debt.note,
               'debtor': row(db.get(Debtor, debt.debtor_id))} if debt else {}
    if kind == 'opening_debt_payment':
        summary.update(cash=source.cash, card=source.card)
    return clean({'kind': kind, 'id': source.id, 'cancelled': False,
                  'can_cancel': can_cancel, 'summary': summary,
                  'expected_fingerprint': source_fingerprint(db, kind, source)})


def debt_data(db, debt, user=None):
    from .routes_debts import today
    payment = payment_for(db, debt.id)
    creator = db.get(User, debt.user_id)
    paid = management.paid_amount(db, 'opening', debt)
    remaining = debt.amount - paid
    payments = management.payment_rows(db, 'opening', debt, user)
    result = dict(row(debt, omit=('command',)), origin='opening', sale_id=None,
                  debtor=row(db.get(Debtor, debt.debtor_id)),
                  created_by=creator.name if creator else None,
                  paid_amount=clean(paid), remaining_amount=clean(remaining),
                  status='paid' if remaining <= 0 else 'partial' if paid > 0 else 'open',
                  overdue=remaining > 0 and debt.due_date <= today(),
                  payments=payments, revisions=management.revision_rows(db, 'opening', debt.id),
                  has_active_installments=any(p['kind'] == 'installment' and not p['cancelled'] for p in payments),
                  management=management.management_data(db, 'opening', debt, user),
                  operation=operation_data(db, 'opening_debt', debt, user), payment=None)
    if payment:
        actor = db.get(User, payment.user_id)
        result['payment'] = dict(row(payment), actor=actor.name if actor else None,
                                 operation=operation_data(db, 'opening_debt_payment', payment, user))
    return result


def audit_reference(entry):
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    if entry.action == 'Oldingi qarz kiritildi':
        return 'opening_debt', detail.get('opening_debt_id'), detail.get('request_id')
    if entry.action == 'Oldingi qarz to‘landi':
        payment = detail.get('payment', {})
        if isinstance(payment, dict):
            return 'opening_debt_payment', payment.get('id'), payment.get('request_id')
    return None


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _marker_data(marker):
    kind = 'opening_debt' if marker.kind == 'debt' else 'opening_debt_payment'
    return clean({'kind': kind, 'id': marker.operation_id, 'cancelled': True,
                  'can_cancel': False, 'reason': marker.reason,
                  'cancelled_at': marker.cancelled_at})


def opening_operation_for_audit(db, entry, user):
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    marker_id = detail.get('opening_cancellation_id')
    if type(marker_id) is int and marker_id > 0:
        marker = db.get(OpeningDebtCancellation, marker_id)
        if marker and marker.branch_id == entry.branch_id:
            return _marker_data(marker)
    reference = audit_reference(entry)
    if not reference:
        return None
    kind, operation_id, request_hint = reference
    if type(operation_id) is not int or operation_id <= 0 or not isinstance(request_hint, str):
        return None
    marker = db.scalar(select(OpeningDebtCancellation).where(
        OpeningDebtCancellation.kind == KINDS[kind][0],
        OpeningDebtCancellation.original_request_id == request_hint,
        OpeningDebtCancellation.branch_id == entry.branch_id))
    if marker:
        return _marker_data(marker)
    source = db.get(KINDS[kind][1], operation_id)
    if (source is None or source.branch_id != entry.branch_id or
            source.request_id != request_hint or _utc(source.created_at) > _utc(entry.created_at)):
        return {'kind': kind, 'id': operation_id, 'cancelled': False,
                'can_cancel': False, 'reason': 'Asl qarz yoki to‘lov topilmadi.'}
    return operation_data(db, kind, source, user)


def linked_audits(db, kind, source):
    return [entry.id for entry in db.scalars(select(Audit).where(
        Audit.branch_id == source.branch_id).order_by(Audit.id))
        if audit_reference(entry) == (kind, source.id, source.request_id)]


def cancel_operation(db, kind, operation_id, data, user):
    """Commit tashqarida. Filial qulfi to'lov va bekor qilishni ketma-ket bajaradi."""
    central_only()
    if kind not in KINDS:
        raise HTTPException(422, 'Oldingi qarz amalining turi mos emas.')
    stored_kind, model = KINDS[kind]
    previous = db.scalar(select(OpeningDebtCancellation).where(
        OpeningDebtCancellation.request_id == data.request_id))
    if previous:
        require_cancellation_user(user, previous.branch_id)
        if (previous.kind != stored_kind or previous.operation_id != operation_id or
                previous.user_id != user.id or previous.reason != data.reason or
                previous.snapshot.get('fingerprint') != data.expected_fingerprint):
            raise HTTPException(409, 'Bu so‘rov boshqa bekor qilishga tegishli.')
        return previous
    source = db.get(model, operation_id)
    if source is None:
        if db.scalar(select(OpeningDebtCancellation.id).where(
                OpeningDebtCancellation.request_id == data.request_id)):
            return cancel_operation(db, kind, operation_id, data, user)
        raise HTTPException(404, 'Asl qarz yoki to‘lov topilmadi. Tarixni yangilang.')
    require_cancellation_user(user, source.branch_id)
    branch_scope(db, user, source.branch_id, required=True)
    branch_write(db, source.branch_id)
    source = db.scalar(select(model).where(model.id == operation_id).with_for_update()
                       .execution_options(populate_existing=True))
    if db.scalar(select(OpeningDebtCancellation.id).where(
            OpeningDebtCancellation.request_id == data.request_id)):
        return cancel_operation(db, kind, operation_id, data, user)
    if source is None:
        raise HTTPException(409, 'Amal boshqa operator tomonidan bekor qilindi. Tarixni yangilang.')
    fingerprint = source_fingerprint(db, kind, source)
    if fingerprint != data.expected_fingerprint:
        raise HTTPException(409, 'Amal holati o‘zgargan. Tarixni yangilab qayta tekshiring.')
    if kind == 'opening_debt' and (payment_for(db, source.id) or
            management.active_installment_total(db, 'opening', source.id) > 0):
        raise HTTPException(409, 'Avval bu qarzning to‘lovini bekor qiling.')
    from .routes_operations import financial_state, require_safe_balances
    before = financial_state(db, source.branch_id, set())
    snapshot = {'record': row(source), 'fingerprint': fingerprint,
                'audit_ids': linked_audits(db, kind, source)}
    if kind == 'opening_debt':
        snapshot['installments'] = [row(item) for item in management.installments(db, 'opening', source.id)]
        snapshot['revisions'] = [row(item) for item in management.revisions(db, 'opening', source.id)]
    if kind == 'opening_debt_payment':
        debt = db.get(OpeningDebt, source.debt_id)
        snapshot['debt'] = row(debt) if debt else None
    marker = OpeningDebtCancellation(kind=stored_kind, operation_id=operation_id,
        request_id=data.request_id, original_request_id=source.request_id,
        branch_id=source.branch_id, user_id=user.id, actor=user.name,
        reason=data.reason, snapshot=clean(snapshot))
    db.add(marker)
    db.flush()
    db.delete(source)
    db.flush()
    require_safe_balances(db, marker.branch_id, set(), before)
    audit(db, user, 'Oldingi qarz amali bekor qilindi', marker.branch_id,
          opening_cancellation_id=marker.id, kind=kind, operation_id=operation_id,
          reason=data.reason, before=snapshot['record'])
    db.flush()
    return marker
