"""Web uchun qarzdorlar, qarz qoldig'i, muddati va haqiqiy to'lovlar.

To‘landi belgisi moliyaviy yozuvdan olinadi: oddiy statusni almashtirish yo‘q.
"""
import os
import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, literal, union_all, text, or_
from sqlalchemy.orm import Session
from .db import get_db
from .models import Debtor, Debt, DebtPayment, OpeningDebt, OpeningDebtPayment, User
from .schemas import DebtorInput, SettleDebt
from .security import current_user, manager, branch_scope, branch_write
from .common import row, clean, audit
from . import debt_management as ledger


def web_only():
    # Eski runtime yangi moliyaviy yozuvni navbatsiz yaratmasin.
    if os.getenv('CRM_BRANCH_ID') and os.getenv('CRM_OFFLINE_V3') != '1':
        raise HTTPException(403, 'Ushbu funksiya uchun yangi EXE versiyasini o‘rnating.')


router = APIRouter(prefix='/api', dependencies=[Depends(web_only)])


def today():
    return datetime.now(ZoneInfo('Asia/Tashkent')).date()


def debt_data(db, debt, user=None):
    payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id))
    actor = db.get(User, payment.user_id).name if payment else None
    paid = ledger.paid_amount(db, 'sale', debt)
    remaining = debt.amount - paid
    payments = ledger.payment_rows(db, 'sale', debt, user)
    return dict(row(debt), origin='sale', debtor=row(db.get(Debtor, debt.debtor_id)),
                paid_amount=clean(paid), remaining_amount=clean(remaining),
                status='paid' if remaining <= 0 else 'partial' if paid > 0 else 'open',
                overdue=remaining > 0 and debt.due_date <= today(),
                payment=dict(row(payment), actor=actor) if payment else None,
                payments=payments, revisions=ledger.revision_rows(db, 'sale', debt.id),
                has_active_installments=any(p['kind'] == 'installment' and not p['cancelled'] for p in payments),
                management=ledger.management_data(db, 'sale', debt, user))


@router.get('/debtors')
def debtors(branch_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    q = select(Debtor).order_by(Debtor.last_name, Debtor.first_name, Debtor.id)
    if branch_id is not None:
        q = q.where(Debtor.branch_id == branch_id)
    return [row(d) for d in db.scalars(q)]


@router.post('/debtors', status_code=201)
def create_debtor(data: DebtorInput, user=Depends(manager), db: Session = Depends(get_db)):
    branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, data.branch_id)
    debtor = Debtor(**data.model_dump())
    db.add(debtor)
    db.flush()
    audit(db, user, 'Qarzdor qo‘shildi', data.branch_id, debtor=row(debtor))
    db.commit()
    return row(debtor)


@router.put('/debtors/{debtor_id}')
def edit_debtor(debtor_id: int, data: DebtorInput, user=Depends(manager), db: Session = Depends(get_db)):
    branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, data.branch_id)
    debtor = db.scalar(select(Debtor).where(Debtor.id == debtor_id).with_for_update())
    if not debtor:
        raise HTTPException(404, 'Qarzdor topilmadi.')
    branch_scope(db, user, debtor.branch_id, required=True)
    if debtor.branch_id != data.branch_id:
        raise HTTPException(422, 'Qarzdorni boshqa filialga o‘tkazib bo‘lmaydi.')
    before = row(debtor)
    for key, value in data.model_dump().items():
        setattr(debtor, key, value)
    audit(db, user, 'Qarzdor ma’lumotlari yangilandi', data.branch_id, before=before, after=row(debtor))
    db.commit()
    return row(debtor)


def debt_list(db, branch_id, status, offset, user, limit=100, q=''):
    """Jami, sahifa va to'lov holati bitta o'qish snapshotidan olinadi."""
    report_today = today()
    def scoped(model, payment, origin):
        remaining = ledger.remaining_expression(model, payment, origin)
        query = select(literal(origin).label('origin'), model.id.label('id'),
                       (model.amount if status == 'paid' else remaining).label('amount'),
                       model.due_date.label('due_date'))
        if branch_id is not None:
            query = query.where(model.branch_id == branch_id)
        if q.strip():
            query = query.join(Debtor, model.debtor_id == Debtor.id)
            if re.fullmatch(r'[\d\s+().-]+', q.strip()):
                digits = re.sub(r'\D', '', q)
                phones = [Debtor.phone1, Debtor.phone2]
                for char in (' ', '+', '(', ')', '-', '.'):
                    phones = [func.replace(phone, char, '') for phone in phones]
                query = query.where(or_(*(phone.contains(digits, autoescape=True) for phone in phones)))
            else:
                for token in q.lower().split():
                    query = query.where(or_(*(func.lower(column).contains(token, autoescape=True)
                        for column in (Debtor.first_name, Debtor.last_name, Debtor.phone1, Debtor.phone2))))
        if status in ('open', 'due', 'partial'):
            query = query.where(remaining > 0)
        elif status == 'paid':
            query = query.where(remaining <= 0)
        if status == 'partial':
            query = query.where(remaining < model.amount)
        if status == 'due':
            query = query.where(model.due_date <= report_today)
        return query
    queries = [scoped(Debt, DebtPayment, 'sale')]
    # Eski offline bazada bu yangi markaziy jadvallar bo'lmasligi mumkin.
    if not os.getenv('CRM_BRANCH_ID'):
        queries.append(scoped(OpeningDebt, OpeningDebtPayment, 'opening'))
    filtered = union_all(*queries).subquery()
    count, amount = db.execute(select(func.count(), func.coalesce(func.sum(filtered.c.amount), 0))
                               .select_from(filtered)).one()
    page = db.execute(select(filtered.c.origin, filtered.c.id).order_by(
        filtered.c.due_date, filtered.c.origin, filtered.c.id).offset(offset).limit(limit)).all()
    sales = {d.id: d for d in db.scalars(select(Debt).where(
        Debt.id.in_([id for origin, id in page if origin == 'sale'])))}
    openings = {d.id: d for d in db.scalars(select(OpeningDebt).where(
        OpeningDebt.id.in_([id for origin, id in page if origin == 'opening'])))} if len(queries) > 1 else {}
    from .opening_debts import debt_data as opening_debt_data
    items = [debt_data(db, sales[id], user) if origin == 'sale' else opening_debt_data(db, openings[id], user)
             for origin, id in page]
    return clean({'items': items, 'count': count, 'amount': amount, 'today': report_today})


@router.get('/debts')
def debts(branch_id: int | None = None, status: Literal['all', 'open', 'paid', 'due', 'partial'] = 'open',
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
          q: str = Query('', max_length=120),
          user=Depends(current_user), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    if db.get_bind().dialect.name == 'postgresql':
        # current_user allaqachon asl tranzaksiyadan o'qilgan. Yangi read-only
        # snapshot boshqa PC qarzni/to'lovni bekor qilayotganida jami, sahifa
        # IDlari va to'liq qatorlar bir xil holatda qolishini ta'minlaydi.
        with db.get_bind().connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with Session(bind=connection) as snapshot:
                snapshot.execute(text('SET TRANSACTION READ ONLY'))
                return debt_list(snapshot, branch_id, status, offset, user, limit, q)
    # SQLite uchun ikkinchi BEGIN IMMEDIATE qulfini ochmaymiz.
    return debt_list(db, branch_id, status, offset, user, limit, q)


@router.get('/notifications/debts')
def notifications(branch_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    return debts(branch_id=branch_id, status='due', offset=0, limit=100, q='', user=user, db=db)


@router.post('/debts/{debt_id}/pay', status_code=201)
def pay_debt(debt_id: int, data: SettleDebt, user=Depends(current_user), db: Session = Depends(get_db)):
    return ledger.pay(db, 'sale', debt_id, data, user)
