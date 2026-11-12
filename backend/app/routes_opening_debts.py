"""Savdo tafsilotisiz oldingi qarz va uni haqiqiy pul bilan yopish."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import get_db
from .models import Debtor, OpeningDebt, OpeningDebtCancellation
from .schemas import NewOpeningDebt, SettleDebt, CancelOperation
from .security import current_user, manager, branch_scope, branch_write
from .common import audit, row
from . import opening_debts as ledger
from . import debt_management

router = APIRouter(prefix='/api/opening-debts', dependencies=[Depends(ledger.central_only)])


@router.post('', status_code=201)
def create(data: NewOpeningDebt, user=Depends(manager), db=Depends(get_db)):
    branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, data.branch_id)
    ledger.reject_cancelled_request(db, 'debt', data.request_id)
    existing = db.scalar(select(OpeningDebt).where(OpeningDebt.request_id == data.request_id))
    if existing:
        if existing.user_id != user.id or existing.command != ledger.command(data):
            raise HTTPException(409, 'Bu so‘rov identifikatori boshqa qarzga tegishli.')
        return ledger.debt_data(db, existing, user)
    debtor = db.scalar(select(Debtor).where(Debtor.id == data.debtor_id).with_for_update())
    if debtor is None:
        raise HTTPException(404, 'Qarzdor topilmadi.')
    if debtor.branch_id != data.branch_id:
        raise HTTPException(403, 'Qarzdor boshqa filialga tegishli.')
    from .routes_debts import today
    debt = OpeningDebt(request_id=data.request_id, branch_id=data.branch_id,
        debtor_id=data.debtor_id, user_id=user.id, amount=data.amount,
        due_date=data.due_date or today(), note=data.note, command=ledger.command(data))
    db.add(debt)
    try:
        db.flush()
        audit(db, user, 'Oldingi qarz kiritildi', debt.branch_id, opening_debt_id=debt.id,
              request_id=debt.request_id, debtor_id=debt.debtor_id,
              amount=debt.amount, due_date=debt.due_date, note=debt.note)
        db.commit()
    except IntegrityError:
        # Filiallar alohida qulflanadi, request_id esa butun jadvalda yagona.
        # Ikkinchi filial bir xil UUID yuborsa muvaffaqiyatsiz tranzaksiya
        # to'liq qaytariladi; faqat aynan shu actor/payload uchun ACK qaytadi.
        db.rollback()
        ledger.reject_cancelled_request(db, 'debt', data.request_id)
        existing = db.scalar(select(OpeningDebt).where(OpeningDebt.request_id == data.request_id))
        if existing and existing.user_id == user.id and existing.command == ledger.command(data):
            return ledger.debt_data(db, existing, user)
        raise HTTPException(409, 'Bu so‘rov identifikatori boshqa qarzga tegishli.') from None
    db.refresh(debt)
    return ledger.debt_data(db, debt, user)


@router.post('/{debt_id}/pay', status_code=201)
def pay(debt_id: int, data: SettleDebt, user=Depends(current_user), db=Depends(get_db)):
    return debt_management.pay(db, 'opening', debt_id, data, user)


def _cancel(db, kind, target_id, data, user):
    try:
        marker = ledger.cancel_operation(db, kind, target_id, data, user)
        response = {'ok': True, 'cancellation': row(marker)}
        db.commit()
        return response
    except IntegrityError:
        db.rollback()
        if db.scalar(select(OpeningDebtCancellation.id).where(
                OpeningDebtCancellation.request_id == data.request_id)):
            # Immutable marker mavjud bo'lsa helper actor, sabab, target va
            # fingerprintni yana tekshiradi. Yangi bekor qilish bajarilmaydi.
            marker = ledger.cancel_operation(db, kind, target_id, data, user)
            return {'ok': True, 'cancellation': row(marker)}
        raise HTTPException(409, 'Bekor qilish identifikatori boshqa amalga tegishli.') from None
    except Exception:
        db.rollback()
        raise


@router.post('/{debt_id}/cancel')
def cancel_debt(debt_id: int, data: CancelOperation, user=Depends(manager), db=Depends(get_db)):
    return _cancel(db, 'opening_debt', debt_id, data, user)


@router.post('/payments/{payment_id}/cancel')
def cancel_payment(payment_id: int, data: CancelOperation, user=Depends(manager), db=Depends(get_db)):
    return _cancel(db, 'opening_debt_payment', payment_id, data, user)
