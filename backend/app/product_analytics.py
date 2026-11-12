"""Mahsulotning joriy qoldig'i va tanlangan davrdagi o'qiladigan savdo tarixi."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .accounting import line_total, money
from .common import clean
from .db import get_db
from .models import (Audit, MiniDiscountShare, Product, ProductArchive, Receipt,
                     Sale, SaleItem, Stock, Supplier, User)
from .routes_analytics import analysis_dates, local_day, time_conditions
from .security import branch_scope, manager


router = APIRouter(prefix='/api/products', tags=['product analytics'])
ZERO = Decimal(0)


def quantity(value):
    return format(Decimal(value or 0).quantize(Decimal('0.001')), 'f')


def amount(value):
    return format(money(value or 0), 'f')


def product_snapshot(db, product_id, branch_id, start, end, user):
    """Money comes from recorded item totals, never today's stock price."""
    from .stock_prices import price_edit_access
    from .stock_adjustments import stock_adjustment_access

    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, 'Mahsulot topilmadi.')
    supplier = db.get(Supplier, product.supplier_id)
    archived = db.get(ProductArchive, product.id) is not None
    stock = db.scalar(select(Stock).where(Stock.product_id == product.id,
                                         Stock.branch_id == branch_id))
    price, discount, kg = (stock.price, stock.discount, stock.kg) if stock else (ZERO, ZERO, ZERO)
    conditions = [SaleItem.product_id == product.id, *time_conditions(Sale, branch_id, start, end)]
    # A single product can occur in multiple legacy rows of the same sale.
    sales_count, sold_kg, sales_total, mini_discount = db.execute(
        select(func.count(func.distinct(Sale.id)), func.coalesce(func.sum(SaleItem.kg), 0),
               func.coalesce(func.sum(SaleItem.total), 0),
               func.coalesce(func.sum(MiniDiscountShare.amount), 0))
        .select_from(SaleItem).join(Sale, Sale.id == SaleItem.sale_id)
        .outerjoin(MiniDiscountShare, MiniDiscountShare.sale_item_id == SaleItem.id)
        .where(*conditions)).one()
    receipt_conditions = [Receipt.product_id == product.id,
                          *time_conditions(Receipt, branch_id, start, end)]
    receipt_count, received_kg = db.execute(
        select(func.count(Receipt.id), func.coalesce(func.sum(Receipt.kg), 0))
        .where(*receipt_conditions)).one()
    day = local_day(db, Sale.created_at)
    daily_rows = db.execute(
        select(day.label('day'), func.sum(SaleItem.kg), func.sum(SaleItem.total),
               func.count(func.distinct(Sale.id)))
        .select_from(SaleItem).join(Sale, Sale.id == SaleItem.sale_id)
        .where(*conditions).group_by(day).order_by(day)).all()
    daily = {row[0]: {'date': row[0], 'kg': quantity(row[1]), 'total': amount(row[2]),
                      'sales_count': row[3]} for row in daily_rows}
    daily_complete = (end - start).days < 3660
    if daily_complete:
        current = start
        while current <= end:
            key = current.isoformat()
            daily.setdefault(key, {'date': key, 'kg': '0.000', 'total': '0.00', 'sales_count': 0})
            current += timedelta(days=1)
    recent_sales = [
        {'id': item.id, 'sale_id': sale.id, 'created_at': sale.created_at,
         'cashier': cashier or '—', 'customer': sale.customer, 'kg': quantity(item.kg),
         'price': amount(item.price), 'discount': amount(item.discount), 'total': amount(item.total)}
        for item, sale, cashier in db.execute(
            select(SaleItem, Sale, User.name).join(Sale, Sale.id == SaleItem.sale_id)
            .outerjoin(User, User.id == Sale.user_id).where(*conditions)
            .order_by(Sale.created_at.desc(), Sale.id.desc(), SaleItem.id.desc()).limit(20))]
    recent_receipts = [
        {'id': receipt.id, 'created_at': receipt.created_at, 'actor': actor or '—',
         'kg': quantity(receipt.kg), 'price': amount(receipt.price), 'note': receipt.note}
        for receipt, actor in db.execute(
            select(Receipt, User.name).outerjoin(User, User.id == Receipt.user_id)
            .where(*receipt_conditions).order_by(Receipt.created_at.desc(), Receipt.id.desc()).limit(20))]
    # Price changes belong to current stock history, regardless of the sales date filter.
    price_history = []
    for entry in db.scalars(select(Audit).where(
            Audit.action == 'Mahsulot narxi o‘zgartirildi', Audit.branch_id == branch_id,
            Audit.detail['product_id'].as_integer() == product.id)
            .order_by(Audit.created_at.desc(), Audit.id.desc()).limit(20)):
        detail = entry.detail if isinstance(entry.detail, dict) else {}
        price_history.append({'id': entry.id, 'created_at': entry.created_at, 'actor': entry.actor,
                              'before': detail.get('before'), 'after': detail.get('after'),
                              'reason': detail.get('reason', '')})
    return clean({
        'filter': {'branch_id': branch_id, 'start': start.isoformat(), 'end': end.isoformat()},
        'product': {'id': product.id, 'name': product.name, 'sku': product.sku,
                    'supplier': supplier.name if supplier else '—', 'image': product.image,
                    'archived': archived},
        'current_stock': {'stock_id': stock.id if stock else None, 'kg': quantity(kg),
                          'price': amount(price), 'discount': amount(discount),
                          'effective_price': amount(line_total(Decimal(1), price, discount)),
                          'retail_value': amount(line_total(kg, price, discount))},
        'permissions': {**price_edit_access(db, user, product, stock, branch_id),
                        **stock_adjustment_access(db, user, product, stock, branch_id)},
        'summary': {'sales_count': sales_count, 'sold_kg': quantity(sold_kg),
                    'sales_total': amount(sales_total), 'mini_discount': amount(mini_discount),
                    'average_price_per_kg': amount(Decimal(sales_total) / Decimal(sold_kg) if sold_kg else ZERO),
                    'receipt_count': receipt_count, 'received_kg': quantity(received_kg)},
        'daily': [daily[key] for key in sorted(daily)], 'series': {'daily_complete': daily_complete},
        'recent_sales': recent_sales, 'recent_receipts': recent_receipts, 'price_history': price_history,
    })


@router.get('/{product_id}/analytics')
def product_analytics(product_id: int, branch_id: int | None = None,
                      start: date | None = None, end: date | None = None,
                      user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id, required=True)
    start, end = analysis_dates(start, end)
    # Authentication already used the original transaction. Match the established
    # export snapshot so product, stock, counts and history cannot mix versions.
    if db.get_bind().dialect.name == 'postgresql':
        with db.get_bind().connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with Session(bind=connection) as snapshot:
                snapshot.execute(text('SET TRANSACTION READ ONLY'))
                return product_snapshot(snapshot, product_id, branch_id, start, end, user)
    return product_snapshot(db, product_id, branch_id, start, end, user)
