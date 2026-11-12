"""Markaziy qarz qoldig'i, qisman to'lov va tarixli tuzatishlar.

Eski bir martalik to'lov jadvallari o'zgarishsiz qoladi. Yangi tushumlar
alohida yoziladi; bekor qilish tushumni o'chirmasdan hisobdan chiqaradi.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from .common import audit, clean, row
from .db import get_db
from .models import (Debt, DebtPayment, OpeningDebt, OpeningDebtPayment,
                     Debtor, User, DebtInstallment, DebtRevision, OperationCancellation,
                     OpeningDebtCancellation, Audit, now)
from .schemas import CancelOperation, ReviseDebt
from .security import branch_scope, branch_write, manager


router = APIRouter(prefix='/api')
MODELS = {'sale': (Debt, DebtPayment), 'opening': (OpeningDebt, OpeningDebtPayment)}
ZERO = Decimal('0.00')


def today():
    return datetime.now(ZoneInfo('Asia/Tashkent')).date()


def central_only():
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Qisman to‘lov va qarz tuzatishini umumiy bazaga ulangan EXE yoki webda bajaring.')


def installment_total_expression(origin, debt_id_column, debt_created_at_column=None):
    """Bir qarzga bog'langan faol tushumlarning SQL summasi."""
    query = select(func.coalesce(func.sum(DebtInstallment.cash + DebtInstallment.card), 0)).where(
        DebtInstallment.origin == origin, DebtInstallment.debt_id == debt_id_column,
        DebtInstallment.cancelled_at.is_(None))
    if debt_created_at_column is None:
        debt_created_at_column = MODELS[origin][0].created_at
    return query.where(DebtInstallment.debt_created_at == debt_created_at_column).correlate_except(
        DebtInstallment).scalar_subquery()


def remaining_expression(model, legacy_model, origin):
    legacy = select(func.coalesce(func.sum(legacy_model.cash + legacy_model.card), 0)).where(
        legacy_model.debt_id == model.id).correlate_except(legacy_model).scalar_subquery()
    if os.getenv('CRM_BRANCH_ID'):
        return model.amount - legacy
    return model.amount - legacy - installment_total_expression(origin, model.id, model.created_at)


def active_installment_total(db, origin, debt_id, debt_created_at=None):
    if os.getenv('CRM_BRANCH_ID'):
        return ZERO
    if debt_created_at is None:
        debt = db.get(MODELS[origin][0], debt_id)
        if debt is None:
            return ZERO
        debt_created_at = debt.created_at
    return Decimal(db.scalar(select(func.coalesce(func.sum(DebtInstallment.cash + DebtInstallment.card), 0))
        .where(DebtInstallment.origin == origin, DebtInstallment.debt_id == debt_id,
               DebtInstallment.debt_created_at == debt_created_at,
               DebtInstallment.cancelled_at.is_(None))) or ZERO)


def legacy_payment(db, origin, debt_id):
    model = MODELS[origin][1]
    return db.scalar(select(model).where(model.debt_id == debt_id)
                     .execution_options(populate_existing=True))


def paid_amount(db, origin, debt):
    payment = legacy_payment(db, origin, debt.id)
    return (payment.cash + payment.card if payment else ZERO) + active_installment_total(
        db, origin, debt.id, debt.created_at)


def installments(db, origin, debt_id, debt_created_at=None):
    if os.getenv('CRM_BRANCH_ID'):
        return []
    if debt_created_at is None:
        debt = db.get(MODELS[origin][0], debt_id)
        if debt is None:
            return []
        debt_created_at = debt.created_at
    return list(db.scalars(select(DebtInstallment).where(
        DebtInstallment.origin == origin, DebtInstallment.debt_id == debt_id)
        .where(DebtInstallment.debt_created_at == debt_created_at)
        .order_by(DebtInstallment.created_at, DebtInstallment.id)
        .execution_options(populate_existing=True)))


def revisions(db, origin, debt_id, debt_created_at=None):
    if os.getenv('CRM_BRANCH_ID'):
        return []
    if debt_created_at is None:
        debt = db.get(MODELS[origin][0], debt_id)
        if debt is None:
            return []
        debt_created_at = debt.created_at
    return list(db.scalars(select(DebtRevision).where(
        DebtRevision.origin == origin, DebtRevision.debt_id == debt_id,
        DebtRevision.debt_created_at == debt_created_at).order_by(DebtRevision.id)))


def _hash(payload):
    encoded = json.dumps(clean(payload), sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def debt_fingerprint(db, origin, debt):
    payment = legacy_payment(db, origin, debt.id)
    debtor = db.get(Debtor, debt.debtor_id)
    return _hash({'origin': origin, 'debt': row(debt),
                  'debtor': row(debtor) if debtor else None,
                  'legacy_payment': row(payment) if payment else None,
                  'installments': [row(item) for item in installments(db, origin, debt.id, debt.created_at)],
                  'revisions': [row(item) for item in revisions(db, origin, debt.id, debt.created_at)]})


def _can_manage(db, branch_id, user):
    from .branch_lifecycle import is_archived
    return bool(user and user.active and user.role in ('boss', 'admin') and
                (user.role == 'boss' or user.branch_id == branch_id) and
                not os.getenv('CRM_BRANCH_ID') and not is_archived(db, branch_id))


def management_data(db, origin, debt, user):
    return {'can_revise': _can_manage(db, debt.branch_id, user),
            'expected_fingerprint': debt_fingerprint(db, origin, debt)}


def installment_fingerprint(db, payment):
    debt = db.get(MODELS[payment.origin][0], payment.debt_id)
    if debt and _utc(debt.created_at) != _utc(payment.debt_created_at):
        debt = None
    return _hash({'installment': row(payment),
                  'debt_fingerprint': debt_fingerprint(db, payment.origin, debt) if debt else None})


def installment_operation(db, payment, user):
    debt = db.get(MODELS[payment.origin][0], payment.debt_id)
    if debt and _utc(debt.created_at) != _utc(payment.debt_created_at):
        debt = None
    cancelled = payment.cancelled_at is not None
    return clean({'kind': 'debt_installment', 'id': payment.id,
                  'origin': payment.origin, 'cancelled': cancelled,
                  'can_cancel': bool(debt and not cancelled and _can_manage(db, payment.branch_id, user)),
                  'expected_fingerprint': installment_fingerprint(db, payment),
                  'reason': payment.cancel_reason, 'cancelled_at': payment.cancelled_at,
                  'summary': {'cash': payment.cash, 'card': payment.card,
                              'amount': payment.cash + payment.card, 'debt_id': payment.debt_id}})


def payment_rows(db, origin, debt, user=None):
    result = []
    payment = legacy_payment(db, origin, debt.id)
    if payment:
        actor = db.get(User, payment.user_id)
        if origin == 'opening':
            from .opening_debts import operation_data
            operation = operation_data(db, 'opening_debt_payment', payment, user)
        else:
            from .operation_history import source_fingerprint
            operation = {'kind': 'debt_payment', 'id': payment.id, 'cancelled': False,
                         'can_cancel': _can_manage(db, debt.branch_id, user),
                         'expected_fingerprint': source_fingerprint(db, 'debt_payment', payment)}
        result.append(dict(row(payment), actor=actor.name if actor else None,
                           kind='legacy', cancelled=False, operation=operation))
    for payment in installments(db, origin, debt.id):
        actor = db.get(User, payment.user_id)
        result.append(dict(row(payment), actor=actor.name if actor else None,
                           kind='installment', cancelled=payment.cancelled_at is not None,
                           operation=installment_operation(db, payment, user)))
    if not os.getenv('CRM_BRANCH_ID'):
        model = OpeningDebtCancellation if origin == 'opening' else OperationCancellation
        stored_kind = 'payment' if origin == 'opening' else 'debt_payment'
        operation_kind = 'opening_debt_payment' if origin == 'opening' else 'debt_payment'
        for marker in db.scalars(select(model).where(model.branch_id == debt.branch_id, model.kind == stored_kind)):
            snapshot = marker.snapshot if isinstance(marker.snapshot, dict) else {}
            record = snapshot.get('record', {})
            if not isinstance(record, dict) or record.get('debt_id') != debt.id:
                continue
            try:
                receipt_time = _utc(datetime.fromisoformat(record['created_at']))
                parent = snapshot.get('debt')
                if isinstance(parent, dict) and (parent.get('id') != debt.id or
                        _utc(datetime.fromisoformat(parent['created_at'])) != _utc(debt.created_at)):
                    continue
                # Avvalgi bekor qilish snapshotlarida parent yo'q: vaqt eski IDni ajratadi.
                if receipt_time < _utc(debt.created_at):
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            actor = db.get(User, record.get('user_id')) if record.get('user_id') else None
            operation = {'kind': operation_kind, 'id': marker.operation_id, 'cancelled': True,
                         'can_cancel': False, 'reason': marker.reason,
                         'cancelled_at': clean(marker.cancelled_at)}
            result.append(dict(record, actor=actor.name if actor else None, kind='legacy',
                               cancelled=True, cancel_reason=marker.reason,
                               cancelled_at=clean(marker.cancelled_at), operation=operation))
    return sorted(result, key=lambda item: (item['created_at'], item['kind'], item['id']))


def revision_rows(db, origin, debt_id):
    result = []
    for revision in revisions(db, origin, debt_id):
        actor = db.get(User, revision.user_id)
        result.append(dict(row(revision, omit=('command',)), actor=actor.name if actor else None))
    return result


def installment_operation_for_audit(db, entry, user):
    detail = entry.detail if isinstance(entry.detail, dict) else {}
    if entry.action not in ('Qarz qisman to‘landi', 'Qarz qisman to‘lovi bekor qilindi'):
        return None
    ident = detail.get('installment_id')
    if type(ident) is not int or ident <= 0:
        return None
    payment = db.get(DebtInstallment, ident)
    if (not payment or payment.branch_id != entry.branch_id or
            payment.request_id != detail.get('request_id')):
        return None
    return installment_operation(db, payment, user)


def _state(db, origin, debt):
    paid = paid_amount(db, origin, debt)
    result = {'amount': debt.amount, 'due_date': debt.due_date, 'debtor_id': debt.debtor_id,
              'paid_amount': paid, 'remaining_amount': debt.amount - paid}
    if origin == 'opening':
        result['note'] = debt.note
    return clean(result)


def _debt_data(db, origin, debt, user):
    if origin == 'opening':
        from .opening_debts import debt_data
    else:
        from .routes_debts import debt_data
    return debt_data(db, debt, user)


def _reject_legacy_cancelled(db, origin, request_id):
    if origin == 'opening':
        from .opening_debts import reject_cancelled_request
        reject_cancelled_request(db, 'payment', request_id)
    else:
        from .operation_history import reject_cancelled_request
        reject_cancelled_request(db, 'debt_payment', request_id)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _existing_payment(db, origin, debt_id, data, user):
    _reject_legacy_cancelled(db, origin, data.request_id)
    installment = None if os.getenv('CRM_BRANCH_ID') else db.scalar(select(DebtInstallment).where(
        DebtInstallment.request_id == data.request_id).execution_options(populate_existing=True))
    if installment:
        if installment.cancelled_at:
            raise HTTPException(409, 'Bu to‘lov bekor qilingan. Yangi to‘lov uchun yangi so‘rov yarating.')
        current = db.get(MODELS[origin][0], debt_id)
        if (not current or _utc(current.created_at) != _utc(installment.debt_created_at) or
                installment.origin != origin or installment.debt_id != debt_id or
                installment.user_id != user.id or installment.cash != data.cash or
                installment.card != data.card or installment.next_due_date != data.next_due_date or
                installment.expected_fingerprint != data.expected_fingerprint):
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa to‘lovga tegishli.')
        return installment
    payment_model = MODELS[origin][1]
    previous = db.scalar(select(payment_model).where(payment_model.request_id == data.request_id))
    if previous:
        action = 'Oldingi qarz to‘landi' if origin == 'opening' else 'Qarz to‘landi'
        entry = db.scalar(select(Audit).where(
            Audit.action == action, Audit.branch_id == previous.branch_id,
            Audit.user_id == previous.user_id,
            Audit.detail['payment']['id'].as_integer() == previous.id,
            Audit.detail['payment']['request_id'].as_string() == previous.request_id
        ).order_by(Audit.id).limit(1))
        original_fingerprint = entry.detail.get('request_fingerprint') if entry else None
        if (previous.debt_id != debt_id or previous.user_id != user.id or
                previous.cash != data.cash or previous.card != data.card or data.next_due_date is not None or
                original_fingerprint != data.expected_fingerprint):
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa to‘lovga tegishli.')
        return previous
    return None


def apply_payment(db, origin, debt_id, data, user):
    """Commit tashqarida; to'lov va qoldiq sanasi bitta tranzaksiyada yoziladi."""
    model, payment_model = MODELS[origin]
    debt = db.get(model, debt_id)
    if debt is None:
        raise HTTPException(404, 'Qarz topilmadi.')
    original_branch = debt.branch_id
    branch_scope(db, user, debt.branch_id, required=True)
    branch_write(db, debt.branch_id)
    debt = db.scalar(select(model).where(model.id == debt_id).with_for_update()
                     .execution_options(populate_existing=True))
    if debt is None:
        raise HTTPException(409, 'Qarz bekor qilingan. Ro‘yxatni yangilang.')
    if debt.branch_id != original_branch:
        raise HTTPException(409, 'Qarz filiali o‘zgargan. Ro‘yxatni yangilang.')
    if _existing_payment(db, origin, debt_id, data, user):
        return debt
    branch_scope(db, user, debt.branch_id, required=True)
    if data.expected_fingerprint is not None and debt_fingerprint(db, origin, debt) != data.expected_fingerprint:
        raise HTTPException(409, 'Qarz ma’lumotlari yoki qoldig‘i o‘zgargan. Ro‘yxatni yangilab to‘lovni qayta tekshiring.')
    amount = data.cash + data.card
    paid = paid_amount(db, origin, debt)
    remaining = debt.amount - paid
    if remaining <= ZERO:
        raise HTTPException(409, 'Bu qarz allaqachon to‘langan. Ro‘yxatni yangilang.')
    if amount <= ZERO:
        raise HTTPException(422, 'To‘lov summasi noldan katta bo‘lsin.')
    if amount > remaining:
        raise HTTPException(422, 'To‘lov qarz qoldig‘idan oshmasin.')
    if data.next_due_date is not None:
        central_only()
        if not _can_manage(db, debt.branch_id, user):
            raise HTTPException(403, 'Qarz muddatini faqat boshliq yoki admin o‘zgartiradi.')
        if amount == remaining:
            raise HTTPException(422, 'To‘liq to‘lovdan keyin qarz qoldig‘i yo‘q. Yangi sana kerak emas.')
        if data.next_due_date < today():
            raise HTTPException(422, 'Yangi to‘lov sanasi bugundan oldin bo‘lmasin.')
    history = installments(db, origin, debt_id)
    if amount == debt.amount and paid == ZERO and not history and data.next_due_date is None:
        # Eski sync/test shartnomasi: birinchi to'liq to'lov avvalgi jadvalga yoziladi.
        payment = payment_model(request_id=data.request_id, cash=data.cash, card=data.card,
                                debt_id=debt_id, branch_id=debt.branch_id, user_id=user.id)
        db.add(payment)
        db.flush()
        action = 'Oldingi qarz to‘landi' if origin == 'opening' else 'Qarz to‘landi'
        detail = {'debtor_id': debt.debtor_id, 'amount': amount, 'payment': row(payment),
                  'request_fingerprint': data.expected_fingerprint}
        detail.update({'opening_debt_id': debt.id} if origin == 'opening' else
                      {'debt_id': debt.id, 'sale_id': debt.sale_id})
        audit(db, user, action, debt.branch_id, **detail)
        return debt
    central_only()
    before = _state(db, origin, debt)
    payment = DebtInstallment(origin=origin, debt_id=debt_id, debt_created_at=debt.created_at,
        request_id=data.request_id,
        branch_id=debt.branch_id, user_id=user.id, cash=data.cash, card=data.card,
        next_due_date=data.next_due_date, expected_fingerprint=data.expected_fingerprint)
    db.add(payment)
    db.flush()
    if data.next_due_date is not None and data.next_due_date != debt.due_date:
        debt.due_date = data.next_due_date
        db.add(DebtRevision(origin=origin, debt_id=debt_id, debt_created_at=debt.created_at,
            request_id=data.request_id,
            branch_id=debt.branch_id, user_id=user.id,
            reason='Qisman to‘lovdan keyin qoldiq uchun yangi sana belgilandi.',
            command=clean({'payment_request_id': data.request_id, 'due_date': data.next_due_date}),
            before=before, after=_state(db, origin, debt)))
    audit(db, user, 'Qarz qisman to‘landi', debt.branch_id, installment_id=payment.id,
          request_id=payment.request_id, origin=origin, debt_id=debt.id,
          debtor_id=debt.debtor_id, amount=amount, payment=row(payment), before=before,
          after=_state(db, origin, debt))
    db.flush()
    return debt


def pay(db, origin, debt_id, data, user):
    try:
        debt = apply_payment(db, origin, debt_id, data, user)
        db.commit()
        return _debt_data(db, origin, debt, user)
    except IntegrityError:
        db.rollback()
        if _existing_payment(db, origin, debt_id, data, user):
            debt = db.get(MODELS[origin][0], debt_id)
            if debt:
                branch_scope(db, user, debt.branch_id, required=True)
                return _debt_data(db, origin, debt, user)
        raise HTTPException(409, 'Bu so‘rov identifikatori boshqa to‘lovga tegishli.') from None


def _revision_command(data):
    payload = data.model_dump(exclude_unset=True)
    # Pulning decimal yozilish farqi bir xil so'rovni boshqa payload qilmasin.
    if payload.get('amount') is not None:
        payload['amount'] = format(payload['amount'].quantize(Decimal('0.01')), 'f')
    return clean(payload)


def _matching_revision(previous, origin, debt_id, data, user):
    if (previous.origin != origin or previous.debt_id != debt_id or previous.user_id != user.id or
            previous.command != _revision_command(data)):
        raise HTTPException(409, 'Bu so‘rov identifikatori boshqa qarz tuzatishiga tegishli.')


def revise(db, origin, debt_id, data, user):
    central_only()
    model = MODELS[origin][0]
    debt = db.get(model, debt_id)
    if debt is None:
        raise HTTPException(404, 'Qarz topilmadi.')
    branch_scope(db, user, debt.branch_id, required=True)
    branch_write(db, debt.branch_id)
    debt = db.scalar(select(model).where(model.id == debt_id).with_for_update()
                     .execution_options(populate_existing=True))
    if debt is None:
        raise HTTPException(409, 'Qarz bekor qilingan. Ro‘yxatni yangilang.')
    if not _can_manage(db, debt.branch_id, user):
        raise HTTPException(403, 'Qarz ma’lumotlarini faqat boshliq yoki admin tuzatadi.')
    previous = db.scalar(select(DebtRevision).where(DebtRevision.request_id == data.request_id))
    if previous:
        _matching_revision(previous, origin, debt_id, data, user)
        if _utc(previous.debt_created_at) != _utc(debt.created_at):
            raise HTTPException(409, 'Bu so‘rov oldingi qarzga tegishli. Yangi so‘rov yarating.')
        return _debt_data(db, origin, debt, user)
    fields = data.model_fields_set & {'amount', 'due_date', 'note', 'debtor_id'}
    if not fields or any(getattr(data, key) is None for key in fields):
        raise HTTPException(422, 'Tuzatiladigan ma’lumotni kiriting.')
    if origin == 'sale' and fields - {'due_date'}:
        raise HTTPException(422, 'Savdo qarzining summasini savdoni tuzatish orqali o‘zgartiring.')
    if debt_fingerprint(db, origin, debt) != data.expected_fingerprint:
        raise HTTPException(409, 'Qarz holati o‘zgargan. Ro‘yxatni yangilab qayta tekshiring.')
    paid = paid_amount(db, origin, debt)
    target_amount = data.amount if 'amount' in fields else debt.amount
    if target_amount < paid:
        raise HTTPException(422, 'Qarz summasi undirilgan to‘lovlardan kam bo‘lmasin. Avval noto‘g‘ri to‘lovni bekor qiling.')
    if 'due_date' in fields and data.due_date != debt.due_date:
        if data.due_date < today():
            raise HTTPException(422, 'Yangi to‘lov sanasi bugundan oldin bo‘lmasin.')
        if target_amount == paid:
            raise HTTPException(422, 'To‘langan qarzga yangi to‘lov sanasini belgilab bo‘lmaydi.')
    if 'debtor_id' in fields:
        debtor = db.get(Debtor, data.debtor_id)
        if not debtor or debtor.branch_id != debt.branch_id:
            raise HTTPException(422, 'Qarzdor shu filialga tegishli bo‘lsin.')
    if all(getattr(debt, key) == getattr(data, key) for key in fields):
        raise HTTPException(422, 'Qarz ma’lumotlari o‘zgarmagan.')
    before = _state(db, origin, debt)
    for key in fields:
        setattr(debt, key, getattr(data, key))
    revision = DebtRevision(origin=origin, debt_id=debt_id, debt_created_at=debt.created_at,
        request_id=data.request_id,
        branch_id=debt.branch_id, user_id=user.id, reason=data.reason,
        command=_revision_command(data), before=before, after=_state(db, origin, debt))
    db.add(revision)
    try:
        db.flush()
        audit(db, user, 'Qarz ma’lumotlari tuzatildi', debt.branch_id,
              revision_id=revision.id, request_id=revision.request_id, origin=origin,
              debt_id=debt.id, reason=data.reason, before=revision.before, after=revision.after)
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(DebtRevision).where(DebtRevision.request_id == data.request_id))
        if not previous:
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa tuzatishga tegishli.') from None
        _matching_revision(previous, origin, debt_id, data, user)
        debt = db.get(model, debt_id)
        if debt is None:
            raise HTTPException(409, 'Qarz bekor qilingan. Ro‘yxatni yangilang.')
        if _utc(previous.debt_created_at) != _utc(debt.created_at):
            raise HTTPException(409, 'Bu so‘rov oldingi qarzga tegishli. Yangi so‘rov yarating.')
    # Numeric ustun DBda ikki kasr xonaga normalizatsiya qilinadi. Javobdagi
    # fingerprint keyingi oynaning yangi SELECTidagi qiymat bilan aynan mos bo'lsin.
    db.refresh(debt)
    return _debt_data(db, origin, debt, user)


@router.post('/debts/{debt_id}/revise')
def revise_sale(debt_id: int, data: ReviseDebt, user=Depends(manager), db=Depends(get_db)):
    return revise(db, 'sale', debt_id, data, user)


@router.post('/opening-debts/{debt_id}/revise')
def revise_opening(debt_id: int, data: ReviseDebt, user=Depends(manager), db=Depends(get_db)):
    return revise(db, 'opening', debt_id, data, user)


def cancel_installment(db, installment_id, data, user):
    central_only()
    from .operation_history import require_cancellation_user
    previous = db.scalar(select(DebtInstallment).where(DebtInstallment.cancel_request_id == data.request_id))
    if previous:
        require_cancellation_user(user, previous.branch_id)
        branch_scope(db, user, previous.branch_id, required=True)
        if (previous.id != installment_id or previous.cancel_user_id != user.id or
                previous.cancel_reason != data.reason or previous.cancel_fingerprint != data.expected_fingerprint):
            raise HTTPException(409, 'Bu so‘rov boshqa bekor qilishga tegishli.')
        return previous
    payment = db.get(DebtInstallment, installment_id)
    if not payment:
        raise HTTPException(404, 'Qisman to‘lov topilmadi.')
    require_cancellation_user(user, payment.branch_id)
    branch_scope(db, user, payment.branch_id, required=True)
    branch_write(db, payment.branch_id)
    payment = db.scalar(select(DebtInstallment).where(DebtInstallment.id == installment_id)
                        .with_for_update().execution_options(populate_existing=True))
    if payment.cancelled_at:
        if payment.cancel_request_id == data.request_id:
            return cancel_installment(db, installment_id, data, user)
        raise HTTPException(409, 'To‘lov allaqachon bekor qilingan. Tarixni yangilang.')
    debt = db.scalar(select(MODELS[payment.origin][0]).where(
        MODELS[payment.origin][0].id == payment.debt_id).with_for_update()
        .execution_options(populate_existing=True))
    if debt is None or _utc(debt.created_at) != _utc(payment.debt_created_at):
        raise HTTPException(409, 'To‘lovga tegishli qarz topilmadi.')
    if installment_fingerprint(db, payment) != data.expected_fingerprint:
        raise HTTPException(409, 'Qarz yoki to‘lov holati o‘zgargan. Tarixni yangilab qayta tekshiring.')
    from .routes_operations import financial_state, require_safe_balances
    before_balance = financial_state(db, payment.branch_id, set())
    before = _state(db, payment.origin, debt)
    payment.cancel_request_id = data.request_id
    payment.cancel_user_id = user.id
    payment.cancel_reason = data.reason
    payment.cancel_fingerprint = data.expected_fingerprint
    payment.cancelled_at = now()
    db.flush()
    require_safe_balances(db, payment.branch_id, set(), before_balance)
    audit(db, user, 'Qarz qisman to‘lovi bekor qilindi', payment.branch_id,
          installment_id=payment.id, request_id=payment.request_id,
          cancellation_request_id=data.request_id, origin=payment.origin,
          debt_id=payment.debt_id, reason=data.reason, before=before,
          after=_state(db, payment.origin, debt))
    db.flush()
    return payment


@router.post('/debt-installments/{installment_id}/cancel')
def cancel(installment_id: int, data: CancelOperation, user=Depends(manager), db=Depends(get_db)):
    try:
        payment = cancel_installment(db, installment_id, data, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.scalar(select(DebtInstallment.id).where(DebtInstallment.cancel_request_id == data.request_id)):
            raise HTTPException(409, 'Bu so‘rov boshqa bekor qilishga tegishli.') from None
        payment = cancel_installment(db, installment_id, data, user)
    return {'ok': True, 'cancellation': row(payment)}
