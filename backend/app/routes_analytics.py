"""Savdo, qarz to‘lovi va xarajatlarning Toshkent sanalari bo‘yicha tahlili."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import BigInteger, Integer, Numeric, String, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from .db import get_db
from .models import Branch, BranchArchive, BranchExpense, Debt, DebtPayment, Product, Sale, SaleItem, OpeningDebtPayment, DebtInstallment
from .security import branch_scope, manager


router = APIRouter(prefix='/api/sales')
TZ = ZoneInfo('Asia/Tashkent')
METRICS = ('sales_count', 'goods_total', 'cash', 'card', 'donation', 'debt_created',
           'debt_outstanding', 'kg', 'expenses', 'debt_collected')


def analysis_dates(start=None, end=None):
    today = datetime.now(TZ).date()
    start, end = start or today.replace(day=1), end or today
    if start > end:
        raise HTTPException(422, 'Boshlanish sanasi tugash sanasidan katta bo‘lmasin.')
    if end == date.max:
        raise HTTPException(422, 'Tugash sanasi 9999-12-31 dan oldin bo‘lsin.')
    return start, end


def time_conditions(model, branch_id, start, end):
    try:
        beginning = datetime.combine(start, datetime.min.time(), TZ).astimezone(timezone.utc)
        ending = datetime.combine(end + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc)
    except OverflowError:
        raise HTTPException(422, 'Sana oralig‘i vaqt zonasida hisoblash uchun yaroqsiz.')
    conditions = [model.created_at >= beginning, model.created_at < ending]
    if branch_id is not None:
        conditions.append(model.branch_id == branch_id)
    return conditions


def local_day(db, column):
    if db.get_bind().dialect.name == 'sqlite':
        # SQLite has no timezone database; use the same ZoneInfo as UTC bounds,
        # including historical dates rather than assuming a fixed +05 offset.
        def tashkent_day(value):
            moment = datetime.fromisoformat(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.astimezone(TZ).date().isoformat()
        db.connection().connection.driver_connection.create_function(
            'crm_tashkent_day', 1, tashkent_day, deterministic=True)
        return cast(func.crm_tashkent_day(column), String)
    return func.to_char(func.timezone('Asia/Tashkent', column), 'YYYY-MM-DD')


def metric_columns(values):
    return [cast(values.get(key, literal(0)),
                 BigInteger if key == 'sales_count' else Numeric(30, 3 if key == 'kg' else 2)).label(key)
            for key in METRICS]


def empty_metrics():
    return {key: 0 if key == 'sales_count' else Decimal(0) for key in METRICS}


def merge_metrics(target, values):
    for key in METRICS:
        target[key] += values[key]


def result_metrics(values):
    result = {'sales_count': int(values['sales_count'])}
    for key in METRICS:
        if key != 'sales_count':
            quantum = Decimal('0.001' if key == 'kg' else '0.01')
            result[key] = format(Decimal(values[key]).quantize(quantum, rounding=ROUND_HALF_UP), 'f')
    received = values['cash'] + values['card']
    average = values['goods_total'] / values['sales_count'] if values['sales_count'] else Decimal(0)
    for key, value in (('received_at_sale', received),
                       ('period_inflow', received + values['debt_collected']), ('average_sale', average)):
        result[key] = format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')
    return result


def build_sales_analytics(db, branch_id, start, end):
    """One statement produces metrics, products and branch labels from one snapshot.

    Item kilograms are aggregated per sale before joining its money. Debt and
    DebtPayment have unique sale_id/debt_id; installments are aggregated before
    joining so multiple receipts never multiply sales. Period debt collections
    remain a separate inflow stream.
    """
    start, end = analysis_dates(start, end)
    conditions = time_conditions(Sale, branch_id, start, end)
    sale_day = local_day(db, Sale.created_at)
    item_kg = (select(SaleItem.sale_id, func.sum(SaleItem.kg).label('kg'))
               .join(Sale, Sale.id == SaleItem.sale_id).where(*conditions)
               .group_by(SaleItem.sale_id).subquery())
    installments = (select(DebtInstallment.debt_id, DebtInstallment.debt_created_at,
        func.sum(DebtInstallment.cash + DebtInstallment.card).label('paid'))
        .where(DebtInstallment.origin == 'sale', DebtInstallment.cancelled_at.is_(None))
        .group_by(DebtInstallment.debt_id, DebtInstallment.debt_created_at).subquery())
    remaining_debt = (Debt.amount - func.coalesce(DebtPayment.cash + DebtPayment.card, 0)
                      - func.coalesce(installments.c.paid, 0))
    sale_metrics = (select(Sale.branch_id, sale_day.label('day'), *metric_columns({
        'sales_count': func.count(Sale.id), 'goods_total': func.sum(Sale.total),
        'cash': func.sum(Sale.cash), 'card': func.sum(Sale.card), 'donation': func.sum(Sale.donation),
        'debt_created': func.sum(func.coalesce(Debt.amount, 0)),
        'debt_outstanding': func.sum(case((remaining_debt > 0, remaining_debt), else_=0)),
        'kg': func.sum(func.coalesce(item_kg.c.kg, 0)),
    })).select_from(Sale).outerjoin(item_kg, item_kg.c.sale_id == Sale.id)
        .outerjoin(Debt, Debt.sale_id == Sale.id).outerjoin(DebtPayment, DebtPayment.debt_id == Debt.id)
        .outerjoin(installments, (installments.c.debt_id == Debt.id) &
                   (installments.c.debt_created_at == Debt.created_at))
        .where(*conditions).group_by(Sale.branch_id, sale_day))
    expense_day = local_day(db, BranchExpense.created_at)
    expense_metrics = (select(BranchExpense.branch_id, expense_day.label('day'),
                              *metric_columns({'expenses': func.sum(BranchExpense.amount)}))
                       .where(*time_conditions(BranchExpense, branch_id, start, end))
                       .group_by(BranchExpense.branch_id, expense_day))
    payment_day = local_day(db, DebtPayment.created_at)
    payment_metrics = (select(DebtPayment.branch_id, payment_day.label('day'),
                              *metric_columns({'debt_collected': func.sum(DebtPayment.cash + DebtPayment.card)}))
                       .where(*time_conditions(DebtPayment, branch_id, start, end))
                       .group_by(DebtPayment.branch_id, payment_day))
    opening_payment_day = local_day(db, OpeningDebtPayment.created_at)
    opening_payment_metrics = (select(OpeningDebtPayment.branch_id, opening_payment_day.label('day'),
        *metric_columns({'debt_collected': func.sum(OpeningDebtPayment.cash + OpeningDebtPayment.card)}))
        .where(*time_conditions(OpeningDebtPayment, branch_id, start, end))
        .group_by(OpeningDebtPayment.branch_id, opening_payment_day))
    # Imported principal is not a new sale or cash receipt. Only real repayments
    # contribute to the period's collected debt, alongside sale debt repayments.
    installment_day = local_day(db, DebtInstallment.created_at)
    installment_metrics = (select(DebtInstallment.branch_id, installment_day.label('day'),
        *metric_columns({'debt_collected': func.sum(DebtInstallment.cash + DebtInstallment.card)}))
        .where(DebtInstallment.cancelled_at.is_(None),
               *time_conditions(DebtInstallment, branch_id, start, end))
        .group_by(DebtInstallment.branch_id, installment_day))
    streams = union_all(sale_metrics, expense_metrics, payment_metrics,
                        opening_payment_metrics, installment_metrics).subquery()
    combined = (select(literal('metric').label('kind'), streams.c.day,
                       streams.c.branch_id, literal(0).label('identifier'),
                       literal('').label('name'), literal('').label('sku'), literal(False).label('archived'),
                       *metric_columns({key: func.sum(streams.c[key]) for key in METRICS}))
                .group_by(streams.c.day, streams.c.branch_id))
    product_metrics = (select(literal('product'), cast(literal(None), String),
                              cast(literal(None), Integer), Product.id, Product.name, Product.sku, literal(False),
                              *metric_columns({'kg': func.sum(SaleItem.kg), 'goods_total': func.sum(SaleItem.total)}))
                       .select_from(SaleItem).join(Sale, Sale.id == SaleItem.sale_id)
                       .join(Product, Product.id == SaleItem.product_id).where(*conditions)
                       .group_by(Product.id, Product.name, Product.sku))
    branch_metrics = (select(literal('branch'), cast(literal(None), String),
                             Branch.id, Branch.id, Branch.name, literal(''), BranchArchive.branch_id.is_not(None),
                             *metric_columns({}))
                      .outerjoin(BranchArchive, BranchArchive.branch_id == Branch.id))
    if branch_id is not None:
        branch_metrics = branch_metrics.where(Branch.id == branch_id)
    records = db.execute(union_all(combined, product_metrics, branch_metrics)).mappings().all()
    summary = empty_metrics()
    daily, monthly, branches, products = {}, {}, {}, []
    for record in records:
        if record['kind'] == 'branch':
            branches[record['branch_id']] = {
                'id': record['branch_id'], 'name': record['name'], 'archived': bool(record['archived']),
                **empty_metrics()}
        elif record['kind'] == 'product':
            products.append({'product_id': record['identifier'], 'name': record['name'],
                             'sku': record['sku'], 'kg': format(record['kg'], '.3f'),
                             'total': format(record['goods_total'], '.2f')})
    for record in records:
        if record['kind'] != 'metric':
            continue
        day = record['day']
        merge_metrics(summary, record)
        merge_metrics(branches[record['branch_id']], record)
        merge_metrics(daily.setdefault(day, empty_metrics()), record)
        merge_metrics(monthly.setdefault(day[:7], empty_metrics()), record)
    # Dates remain unrestricted. Long ranges use sparse series to avoid millions
    # of zero rows; ordinary month/year charts include every empty bucket.
    daily_complete = (end - start).days < 3660
    monthly_complete = (end.year - start.year) * 12 + end.month - start.month < 1200
    if daily_complete:
        day = start
        while day <= end:
            daily.setdefault(day.isoformat(), empty_metrics())
            day += timedelta(days=1)
    if monthly_complete:
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            monthly.setdefault(f'{year:04d}-{month:02d}', empty_metrics())
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        'filter': {'branch_id': branch_id, 'start': start.isoformat(), 'end': end.isoformat()},
        'summary': result_metrics(summary),
        'daily': [{'date': key, **result_metrics(value)} for key, value in sorted(daily.items())],
        'monthly': [{'month': key, **result_metrics(value)} for key, value in sorted(monthly.items())],
        'branches': [{'id': row['id'], 'name': row['name'], 'archived': row['archived'], **result_metrics(row)}
                     for _, row in sorted(branches.items())],
        'products': sorted(products, key=lambda row: (-Decimal(row['total']), row['name'], row['product_id'])),
        'series': {'daily_complete': daily_complete, 'monthly_complete': monthly_complete},
    }


@router.get('/analytics')
def sales_analytics(branch_id: int | None = None, start: date | None = None, end: date | None = None,
                    user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    start, end = analysis_dates(start, end)
    return build_sales_analytics(db, branch_id, start, end)
