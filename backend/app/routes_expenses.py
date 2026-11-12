"""Uchala rol xarajat kiritadi; filial va mablag‘ chegarasi serverda tekshiriladi."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from .db import get_db
from .models import BranchExpense, Supplier, User
from .schemas import NewExpense
from .security import current_user, manager, branch_scope, branch_write
from .routes_debts import web_only
from .accounting import balances, supplier_debt
from .common import row, clean, audit
from .operation_history import reject_cancelled_request

router = APIRouter(prefix='/api/expenses', dependencies=[Depends(web_only)])


@router.get('/options')
def options(branch_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id, required=True)
    ledger = balances(db, branch_id)
    return clean({'branch_id': branch_id, 'cash': ledger['cash'], 'card': ledger['card'],
                  'suppliers': [{'id': s.id, 'name': s.name, 'debt': supplier_debt(db, s.id, branch_id)['debt']}
                                for s in db.scalars(select(Supplier).order_by(Supplier.name))]})


@router.get('')
def expenses(branch_id: int | None = None, offset: int = Query(0, ge=0),
             limit: int = Query(100, ge=1, le=100), user=Depends(manager), db=Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    q = select(BranchExpense, Supplier.name, User.name).join(Supplier, Supplier.id == BranchExpense.supplier_id).join(User, User.id == BranchExpense.user_id)
    if branch_id is not None:
        q = q.where(BranchExpense.branch_id == branch_id)
    filtered = q.subquery()
    count, amount = db.execute(select(func.count(), func.coalesce(func.sum(filtered.c.amount), 0)).select_from(filtered)).one()
    return clean({'count': count, 'amount': amount, 'items': [dict(row(e), supplier=s, actor=u)
                  for e, s, u in db.execute(q.order_by(BranchExpense.id.desc()).offset(offset).limit(limit))]})


@router.post('', status_code=201)
def create_expense(data: NewExpense, user=Depends(current_user), db=Depends(get_db)):
    branch_id = branch_scope(db, user, data.branch_id, required=True)
    # Shu qulf savdo, ta’minotchi to‘lovi va ehson chiqimi bilan ham umumiy.
    branch_write(db, branch_id)
    reject_cancelled_request(db, 'expense', data.request_id)
    values = dict(data.model_dump(), branch_id=branch_id, user_id=user.id)
    existing = db.scalar(select(BranchExpense).where(BranchExpense.request_id == data.request_id))
    if existing:
        if any(getattr(existing, key) != value for key, value in values.items()):
            raise HTTPException(409, 'Bu identifikator boshqa xarajatga tegishli. Oldingi amalni tekshiring.')
        return row(existing)
    if not db.get(Supplier, data.supplier_id):
        raise HTTPException(404, 'Ta’minotchi topilmadi.')
    if data.amount > balances(db, branch_id)[data.method]:
        raise HTTPException(422, 'Tanlangan naqd yoki karta hisobida yetarli pul yo‘q.')
    if data.amount > supplier_debt(db, data.supplier_id, branch_id)['debt']:
        raise HTTPException(422, 'Xarajat ta’minotchining shu filialdagi qolgan haqidan oshmasin.')
    expense = BranchExpense(**values)
    db.add(expense)
    db.flush()
    audit(db, user, 'Filial xarajati qilindi', branch_id, expense=row(expense))
    db.commit()
    return row(expense)
