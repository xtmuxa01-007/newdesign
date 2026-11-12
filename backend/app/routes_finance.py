from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func, case, union_all
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import json
import os
from .db import get_db
from .models import Branch, User, Stock, Sale, SaleItem, Supplier, SupplierPayment, DonationPayment, OtherPayment, Audit, now, MiniDiscount, DebtPayment, OpeningDebtPayment, DebtInstallment
from .security import manager, branch_scope, branch_write
from .schemas import Payment, OtherPayment as NewOtherPayment
from .common import row, clean, audit
from .accounting import balances, supplier_debt, sum_column, line_total, ZERO
from .donation_limits import require_donation_limit
from .operation_history import reject_cancelled_request, operation_for_audit, operation_for_source
from .routes_sales import sale_data
from .mini_discounts import mini_data
from .branch_lifecycle import is_archived
from .routes_analytics import time_conditions

router = APIRouter(prefix="/api")
TZ = ZoneInfo("Asia/Tashkent")


@router.get('/mini-discounts')
def mini_discounts(branch_id: int | None = None, offset: int = Query(0, ge=0),
                   limit: int = Query(100, ge=1, le=100),
                   user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    q = select(MiniDiscount, User.name, Sale.cash, Sale.card).join(User, User.id == MiniDiscount.user_id).join(Sale, Sale.id == MiniDiscount.sale_id)
    if branch_id is not None:
        q = q.where(MiniDiscount.branch_id == branch_id)
    filtered = q.subquery()
    count = db.scalar(select(func.count()).select_from(filtered))
    return clean({'items': [dict(mini_data(db, d), actor=name, cash=cash, card=card) for d, name, cash, card in db.execute(q.order_by(MiniDiscount.id.desc()).offset(offset).limit(limit))],
                  'count': count, 'amount': sum_column(db, MiniDiscount, MiniDiscount.amount, branch_id)})

def period(start, end):
    if start and end and start > end:
        raise HTTPException(422, "Boshlanish sanasi tugash sanasidan katta bo‘lmasin.")
    result = []
    try:
        if start:
            result.append(Sale.created_at >= datetime.combine(start, datetime.min.time(), TZ).astimezone(timezone.utc))
        if end:
            result.append(Sale.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc))
    except OverflowError:
        raise HTTPException(422, 'Sana oralig‘i vaqt zonasida hisoblash uchun yaroqsiz.')
    return result

def dashboard_inflows(db, branch_id, today):
    """Real receipts in the Tashkent day/month, grouped without sale-item joins."""
    streams = []
    for model in (Sale, DebtPayment, OpeningDebtPayment, DebtInstallment):
        amount = model.cash + model.card
        conditions = time_conditions(model, branch_id, today.replace(day=1), today)
        day_conditions = time_conditions(model, branch_id, today, today)
        if model is DebtInstallment:
            conditions.append(model.cancelled_at.is_(None))
        streams.append(select(model.branch_id.label('branch_id'),
            func.sum(case((day_conditions[0], amount), else_=0)).label('today_inflow'),
            func.sum(amount).label('month_inflow'))
            .where(*conditions).group_by(model.branch_id))
    receipts = union_all(*streams).subquery()
    return {entry.branch_id: {'today_inflow': entry.today_inflow,
                              'month_inflow': entry.month_inflow}
            for entry in db.execute(select(receipts.c.branch_id,
                func.sum(receipts.c.today_inflow).label('today_inflow'),
                func.sum(receipts.c.month_inflow).label('month_inflow'))
                .group_by(receipts.c.branch_id))}


@router.get("/dashboard")
def dashboard(branch_id: int | None = None, user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    today = datetime.now(TZ).date()
    inflows = dashboard_inflows(db, branch_id, today)
    totals = {}
    for key, start in (("today", today), ("month", today.replace(day=1)), ("year", today.replace(month=1, day=1))):
        totals[key] = sum_column(db, Sale, Sale.total, branch_id, period(start, today))
    query = select(Stock)
    if branch_id is not None:
        query = query.where(Stock.branch_id == branch_id)
    stocks = list(db.scalars(query))
    ledger = balances(db, branch_id)
    total_debt = sum(supplier_debt(db, s, branch_id)["debt"] for s in db.scalars(select(Supplier.id)))
    branches = []
    bq = select(Branch).order_by(Branch.id)
    if branch_id is not None:
        bq = bq.where(Branch.id == branch_id)
    for b in db.scalars(bq):
        from .routes_sync import SyncDevice
        device = db.scalar(select(SyncDevice).where(SyncDevice.branch_id == b.id))
        bs = [s for s in stocks if s.branch_id == b.id]
        branches.append(dict(row(b), archived=is_archived(db, b.id), kg=sum(s.kg for s in bs), inventory=sum(line_total(s.kg, s.price, s.discount) for s in bs),
                             device_linked=bool(device), last_received_at=device.last_received_at if device else None,
                             today=sum_column(db, Sale, Sale.total, b.id, period(today, today)),
                             **inflows.get(b.id, {'today_inflow': ZERO, 'month_inflow': ZERO}), **balances(db, b.id)))
    recent = select(Sale, User.name).join(User, User.id == Sale.user_id).order_by(Sale.id.desc()).limit(6)
    if branch_id is not None:
        recent = recent.where(Sale.branch_id == branch_id)
    return clean(dict(totals, **ledger, today_inflow=sum((v['today_inflow'] for v in inflows.values()), ZERO),
                      month_inflow=sum((v['month_inflow'] for v in inflows.values()), ZERO), revenue_date=today.isoformat(),
                      supplier_debt=total_debt, inventory_kg=sum(s.kg for s in stocks),
                      inventory_value=sum(line_total(s.kg, s.price, s.discount) for s in stocks),
                      active_products=sum(1 for s in stocks if s.kg > 0), branches=branches,
                      recent_sales=[dict(sale_data(db, s), cashier=name) for s, name in db.execute(recent)]))

def make_payment(db, user, data, supplier_id=None):
    branch_id = branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, branch_id)
    db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update())
    model = SupplierPayment if supplier_id is not None else DonationPayment
    reject_cancelled_request(db, 'supplier_payment' if supplier_id is not None else 'donation_payment', data.request_id)
    existing = db.scalar(select(model).where(model.request_id == data.request_id))
    if existing:
        if existing.branch_id != branch_id or existing.user_id != user.id or (supplier_id is not None and existing.supplier_id != supplier_id):
            raise HTTPException(409, "To‘lov identifikatori band.")
        if any(getattr(existing, key) != value for key, value in data.model_dump().items()):
            raise HTTPException(409, "Shu identifikator bilan boshqa to‘lov yuborilgan. Oldingi to‘lovni tekshiring.")
        return row(existing)
    if supplier_id is None:
        require_donation_limit(data.amount)
    ledger = balances(db, branch_id)
    if data.amount > ledger[data.method]:
        raise HTTPException(422, "Tanlangan naqd yoki karta hisobida yetarli mablag‘ yo‘q.")
    values = dict(data.model_dump(), user_id=user.id)
    if supplier_id is not None:
        if not db.get(Supplier, supplier_id):
            raise HTTPException(404, "Ta’minotchi topilmadi.")
        if data.amount > supplier_debt(db, supplier_id, branch_id)["debt"]:
            raise HTTPException(422, "To‘lov ta’minotchining qolgan haqidan oshmasin.")
        payment = SupplierPayment(**values, supplier_id=supplier_id)
        action = "Ta’minotchiga pul berildi"
    else:
        if data.amount > ledger["donation_balance"]:
            raise HTTPException(422, "Ehson hisobida yetarli mablag‘ yo‘q.")
        payment = DonationPayment(**values)
        action = "Ehson puli berildi"
    db.add(payment)
    db.flush()
    audit(db, user, action, branch_id, payment_id=payment.id, request_id=data.request_id,
          supplier_id=supplier_id, amount=data.amount, method=data.method, recipient=data.recipient, note=data.note)
    db.commit()
    return row(payment)

@router.post("/suppliers/{supplier_id}/payments", status_code=201)
def supplier_payment(supplier_id: int, data: Payment, user=Depends(manager), db: Session = Depends(get_db)):
    return make_payment(db, user, data, supplier_id)

@router.post("/donations/payments", status_code=201)
def donation_payment(data: Payment, user=Depends(manager), db: Session = Depends(get_db)):
    return make_payment(db, user, data)


def _other_payment_response(db, payment, user):
    return dict(row(payment), operation=operation_for_source(db, 'other_payment', payment, user))


def _matching_other_payment(db, payment, data, user):
    if (payment.user_id != user.id or
            any(getattr(payment, key) != value for key, value in data.model_dump().items())):
        raise HTTPException(409, 'Bu so‘rov identifikatori boshqa pul topshirig‘iga tegishli.')
    return _other_payment_response(db, payment, user)


@router.post('/other-payments', status_code=201)
def other_payment(data: NewOtherPayment, user=Depends(manager), db: Session = Depends(get_db)):
    # The legacy offline protocol does not transmit this new central-only table.
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Boshqa pullarni web yoki umumiy bazaga ulangan EXE orqali topshiring.')
    branch_id = branch_scope(db, user, data.branch_id, required=True)
    # branch_write takes the shared Branch FOR UPDATE lock and validates archive
    # and legacy-device state before reading a balance or replaying a request.
    branch_write(db, branch_id)
    reject_cancelled_request(db, 'other_payment', data.request_id)
    existing = db.scalar(select(OtherPayment).where(OtherPayment.request_id == data.request_id))
    if existing:
        return _matching_other_payment(db, existing, data, user)
    ledger = balances(db, branch_id)
    # This cashout records the physical handover even if earlier cash income
    # was never entered. Do not fabricate an income to hide the discrepancy.
    balance_before = ledger[data.method]
    balance_after = balance_before - data.amount
    unrecorded_amount = max(data.amount - max(balance_before, ZERO), ZERO)
    payment = OtherPayment(**data.model_dump(), user_id=user.id)
    db.add(payment)
    try:
        db.flush()
        audit(db, user, 'Boshqa pul berildi', branch_id,
              payment_id=payment.id, request_id=payment.request_id, amount=payment.amount,
              method=payment.method, recipient=payment.recipient, note=payment.note,
              balance_before=balance_before, balance_after=balance_after,
              unrecorded_amount=unrecorded_amount)
        db.commit()
    except IntegrityError:
        # A different branch can submit the same globally unique request ID
        # while holding its own branch lock. Roll back any attempted cashout.
        db.rollback()
        reject_cancelled_request(db, 'other_payment', data.request_id)
        existing = db.scalar(select(OtherPayment).where(OtherPayment.request_id == data.request_id))
        if existing:
            return _matching_other_payment(db, existing, data, user)
        raise HTTPException(409, 'Pul topshirig‘ini saqlashda ziddiyat yuz berdi. Tarixni tekshiring.') from None
    # Normalize Numeric scale before exposing the cancellation fingerprint.
    db.refresh(payment)
    return _other_payment_response(db, payment, user)


@router.get("/payments")
def payments(branch_id: int | None = None, offset: int = Query(0, ge=0),
             others_offset: int = Query(0, ge=0), suppliers_limit: int = Query(100, ge=1, le=100),
             donations_limit: int = Query(100, ge=1, le=100),
             others_limit: int = Query(100, ge=1, le=100),
             user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    result = {}
    for key, model in (("suppliers", SupplierPayment), ("donations", DonationPayment)):
        q = select(model, User.name).join(User, User.id == model.user_id).order_by(model.id.desc()).offset(offset).limit(suppliers_limit if key == 'suppliers' else donations_limit)
        if branch_id is not None:
            q = q.where(model.branch_id == branch_id)
        result[key] = [dict(row(p), actor=name) for p, name in db.execute(q)]
    supplier_conditions = (SupplierPayment.branch_id == branch_id,) if branch_id is not None else ()
    result['suppliers_count'] = db.scalar(select(func.count()).select_from(SupplierPayment).where(*supplier_conditions))
    donation_conditions = (DonationPayment.branch_id == branch_id,) if branch_id is not None else ()
    result['donations_count'] = db.scalar(select(func.count()).select_from(DonationPayment).where(*donation_conditions))
    result.update(others=[], other_paid=ZERO, others_count=0)
    if not os.getenv('CRM_BRANCH_ID'):
        conditions = (OtherPayment.branch_id == branch_id,) if branch_id is not None else ()
        query = (select(OtherPayment, User.name).join(User, User.id == OtherPayment.user_id)
                 .where(*conditions).order_by(OtherPayment.id.desc()).offset(others_offset).limit(others_limit))
        result['others'] = [dict(_other_payment_response(db, payment, user), actor=name)
                            for payment, name in db.execute(query)]
        result['other_paid'] = sum_column(db, OtherPayment, OtherPayment.amount, branch_id)
        result['others_count'] = db.scalar(select(func.count()).select_from(OtherPayment).where(*conditions))
    return clean(result)

@router.get("/sales")
def sales(branch_id: int | None = None, start: date | None = None, end: date | None = None,
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
          user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    conditions = period(start, end)
    query = select(Sale, User.name).join(User, Sale.user_id == User.id).where(*conditions).order_by(Sale.id.desc()).offset(offset).limit(limit)
    if branch_id is not None:
        query = query.where(Sale.branch_id == branch_id)
    return clean({"items": [dict(sale_data(db, s), cashier=name) for s, name in db.execute(query)],
                  "total": sum_column(db, Sale, Sale.total, branch_id, conditions),
                  "donation": sum_column(db, Sale, Sale.donation, branch_id, conditions)})

@router.get("/sales/export")
def export_sales(branch_id: int | None = None, start: date | None = None, end: date | None = None,
                 user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    query = select(Sale).where(*period(start, end)).order_by(Sale.id)
    if branch_id is not None:
        query = query.where(Sale.branch_id == branch_id)
    # Bir tranzaksiyadagi nusxa; pul satr ko‘rinishida, float aniqligi yo‘qolmaydi.
    entries = [sale_data(db, s) for s in db.scalars(query)]
    branch_q = select(Branch)
    user_q = select(User)
    if branch_id is not None:
        branch_q = branch_q.where(Branch.id == branch_id)
        seller_ids = {s["user_id"] for s in entries}
        user_q = user_q.where(User.id.in_(seller_ids))
    supplier_ids = {i["supplier_id"] for s in entries for i in s["items"]}
    payload = {"schema_version": 1, "exported_at": now().isoformat(), "timezone": "Asia/Tashkent", "currency": "UZS", "weight_unit": "kg",
               "filter": {"branch_id": branch_id, "start": str(start) if start else None, "end": str(end) if end else None},
               "branches": [row(b) for b in db.scalars(branch_q)],
               "sellers": [{"id": u.id, "name": u.name} for u in db.scalars(user_q)],
               "suppliers": [row(s) for s in db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids)))], "sales": entries}
    audit(db, user, "Savdolar JSON yuklandi", branch_id, count=len(entries), start=start, end=end)
    db.commit()
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="marwa-sales.json"'})

@router.get("/audit")
def history(branch_id: int | None = None, offset: int = Query(0, ge=0), q: str = Query("", max_length=120),
            limit: int = Query(100, ge=1, le=100), user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    query = select(Audit).order_by(Audit.id.desc()).offset(offset).limit(limit)
    if branch_id is not None:
        query = query.where(Audit.branch_id == branch_id)
    if q:
        query = query.where(Audit.action.icontains(q, autoescape=True) | Audit.actor.icontains(q, autoescape=True))
    return [dict(row(a), operation=operation_for_audit(db, a, user)) for a in db.scalars(query)]
