"""Narx, ombor, savdo va pul xabarlari; boshliqlar mustaqil o'qiydi."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, and_, cast, exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased

from .common import clean
from .db import get_db
from .models import Audit, Branch, OperationCancellation, OtherPayment, Product, StockAdjustment, User
from .security import boss, branch_scope, manager
from .stock_adjustments import STOCK_ADJUSTMENT_ACTION
from .stock_prices import PRICE_CHANGE_ACTION


router = APIRouter(prefix='/api', tags=['changes'])
READ_ACTION = 'O‘zgarish xabari o‘qildi'
TZ = ZoneInfo('Asia/Tashkent')
OTHER_PAYMENT_ACTION = 'Boshqa pul berildi'


class ReadChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1, max_length=100)


def _event_condition():
    stock_adjustment = or_(
        exists(select(StockAdjustment.id).where(
            cast(StockAdjustment.id, String) == cast(Audit.detail['adjustment_id'].as_string(), String),
            StockAdjustment.request_id == Audit.detail['request_id'].as_string(),
            StockAdjustment.branch_id == Audit.branch_id,
            StockAdjustment.user_id == Audit.user_id)),
        exists(select(OperationCancellation.id).where(
            OperationCancellation.kind == 'stock_adjustment',
            cast(OperationCancellation.operation_id, String) == cast(Audit.detail['adjustment_id'].as_string(), String),
            OperationCancellation.original_request_id == Audit.detail['request_id'].as_string(),
            OperationCancellation.branch_id == Audit.branch_id,
            cast(OperationCancellation.snapshot['record']['user_id'].as_string(), String) == cast(Audit.user_id, String))))
    cancellation = exists(select(OperationCancellation.id).where(
        cast(OperationCancellation.id, String) == cast(Audit.detail['cancellation_id'].as_string(), String),
        OperationCancellation.kind == 'sale',
        OperationCancellation.branch_id == Audit.branch_id,
        cast(OperationCancellation.operation_id, String) == cast(Audit.detail['operation_id'].as_string(), String)))
    other_cancellation = exists(select(OperationCancellation.id).where(
        cast(OperationCancellation.id, String) == cast(Audit.detail['cancellation_id'].as_string(), String),
        OperationCancellation.kind == 'other_payment',
        OperationCancellation.branch_id == Audit.branch_id,
        cast(OperationCancellation.operation_id, String) == cast(Audit.detail['operation_id'].as_string(), String)))
    other_payment = or_(
        exists(select(OtherPayment.id).where(
            cast(OtherPayment.id, String) == cast(Audit.detail['payment_id'].as_string(), String),
            OtherPayment.request_id == Audit.detail['request_id'].as_string(),
            OtherPayment.branch_id == Audit.branch_id)),
        exists(select(OperationCancellation.id).where(
            OperationCancellation.kind == 'other_payment',
            cast(OperationCancellation.operation_id, String) == cast(Audit.detail['payment_id'].as_string(), String),
            OperationCancellation.original_request_id == Audit.detail['request_id'].as_string(),
            OperationCancellation.branch_id == Audit.branch_id)))
    # Ushbu amallar faqat markazda bajariladi. Eski sync qurilmasi yuborgan
    # xuddi shunday matnli audit haqiqiy narx/bekor qilish hodisasi emas.
    return and_(Audit.detail['_sync_source'].as_string().is_(None),
                or_(Audit.action == PRICE_CHANGE_ACTION,
                    and_(Audit.action == STOCK_ADJUSTMENT_ACTION, stock_adjustment),
                    and_(Audit.action == OTHER_PAYMENT_ACTION, other_payment),
                    and_(Audit.action == 'Amal bekor qilindi',
                         Audit.detail['kind'].as_string() == 'other_payment', other_cancellation),
                    and_(Audit.action == 'Amal bekor qilindi',
                         Audit.detail['kind'].as_string() == 'sale', cancellation)))


def _unread_condition(user_id):
    receipt = aliased(Audit)
    # Sync audit JSONi ishonchsiz: noto'g'ri ID PostgreSQL integer castini
    # yiqitmasin. Server tasdig'idagi raqamning matni aynan mos kelishi kerak.
    event_id = cast(receipt.detail['event_id'].as_string(), String)
    return cast(Audit.id, String).not_in(select(event_id).where(receipt.action == READ_ACTION,
        receipt.user_id == user_id, receipt.branch_id.is_(None),
        receipt.detail['_sync_source'].as_string().is_(None), event_id.is_not(None)))


def _snapshot(db, read):
    if db.get_bind().dialect.name == 'postgresql':
        with db.get_bind().connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with Session(bind=connection) as snapshot:
                snapshot.execute(text('SET TRANSACTION READ ONLY'))
                return read(snapshot)
    return read(db)


def _dates(start, end):
    if start and end and start > end:
        raise HTTPException(422, 'Boshlanish sanasi tugash sanasidan katta bo‘lmasin.')
    conditions = []
    try:
        if start:
            conditions.append(Audit.created_at >= datetime.combine(start, datetime.min.time(), TZ).astimezone(timezone.utc))
        if end:
            conditions.append(Audit.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc))
    except (OverflowError, ValueError):
        raise HTTPException(422, 'Sana oralig‘i vaqt zonasida hisoblash uchun yaroqsiz.')
    return conditions


def _amount(value=0, places=2):
    return format(Decimal(str(value or 0)), f'.{places}f')


def _sale_summary(db, marker, detailed):
    snapshot = marker.snapshot
    record = snapshot.get('record', {})
    cashier = db.scalar(select(Audit.actor).where(
        Audit.id.in_(snapshot.get('audit_ids', [])),
        Audit.action.in_(('Savdo yakunlandi', 'Qarzga savdo qilindi'))).order_by(Audit.id).limit(1))
    if not cashier:
        seller = db.get(User, record.get('user_id')) if record.get('user_id') else None
        cashier = seller.name if seller else '—'
    payments = snapshot.get('debt_payments', []) + [payment for payment in
        snapshot.get('debt_installments', []) if not payment.get('cancelled_at')]
    result = {'id': marker.operation_id, 'created_at': record.get('created_at'),
              'cashier': cashier, 'customer': record.get('customer', ''),
              **{key: _amount(record.get(key)) for key in ('total', 'cash', 'card', 'donation')},
              'mini_discount': _amount(sum(Decimal(str(row['amount'])) for row in snapshot.get('mini_discounts', []))),
              'debt': _amount(sum(Decimal(str(row['amount'])) for row in snapshot.get('debts', []))),
              'debt_cash': _amount(sum(Decimal(str(row['cash'])) for row in payments)),
              'debt_card': _amount(sum(Decimal(str(row['card'])) for row in payments))}
    if detailed:
        shares = {row['sale_item_id']: row['amount'] for row in snapshot.get('mini_discount_shares', [])}
        result['items'] = [{'id': row['id'], 'name': row['name'], 'sku': row['sku'],
            'kg': _amount(row['kg'], 3), 'price': _amount(row['price']),
            'discount': _amount(row['discount']), 'mini_discount': _amount(shares.get(row['id'])),
            'total': _amount(row['total'])} for row in snapshot.get('sale_items', [])]
    return result


def _stock_summary(db, entry):
    """Kg qiymatlari haqiqiy tuzatishdan; yorliqlar auditdagi snapshotdan olinadi."""
    detail = entry.detail
    adjustment = db.scalar(select(StockAdjustment).where(
        StockAdjustment.request_id == detail.get('request_id'),
        StockAdjustment.branch_id == entry.branch_id,
        StockAdjustment.user_id == entry.user_id))
    marker = None if adjustment else db.scalar(select(OperationCancellation).where(
        OperationCancellation.kind == 'stock_adjustment',
        OperationCancellation.original_request_id == detail.get('request_id'),
        OperationCancellation.branch_id == entry.branch_id))
    record = marker.snapshot['record'] if marker else {
        'stock_id': adjustment.stock_id, 'product_id': adjustment.product_id,
        'before_kg': adjustment.before_kg, 'kg': adjustment.kg}
    product = db.get(Product, record['product_id'])
    before, after = Decimal(str(record['before_kg'])), Decimal(str(record['kg']))
    return {'stock_id': record['stock_id'], 'product_id': record['product_id'],
            'name': detail.get('product_name') or (product.name if product else 'Mahsulot'),
            'sku': detail.get('sku') or (product.sku if product else ''),
            'labels_source': 'snapshot' if detail.get('product_name') and 'sku' in detail else 'current_product',
            'before': _amount(before, 3), 'after': _amount(after, 3),
            'difference': _amount(after - before, 3), 'cancelled': bool(marker)}


def _items(db, entries, user, detailed=False):
    if not entries:
        return []
    ids = [entry.id for entry in entries]
    unread = (set(db.scalars(select(Audit.id).where(Audit.id.in_(ids), _unread_condition(user.id))))
              if user.role == 'boss' else set())
    result = []
    for entry in entries:
        detail = entry.detail
        branch = db.get(Branch, entry.branch_id) if entry.branch_id else None
        price_change = entry.action == PRICE_CHANGE_ACTION
        stock_adjustment = entry.action == STOCK_ADJUSTMENT_ACTION
        other_payment = entry.action == OTHER_PAYMENT_ACTION
        other_cancelled = not price_change and not stock_adjustment and not other_payment and detail.get('kind') == 'other_payment'
        kind = ('price_change' if price_change else 'stock_adjustment' if stock_adjustment else 'other_payment' if other_payment else
                'other_payment_cancelled' if other_cancelled else 'sale_cancelled')
        title = {'price_change': 'Mahsulot narxi o‘zgardi', 'sale_cancelled': 'Savdo bekor qilindi',
                 'stock_adjustment': 'Ombor qoldig‘i tuzatildi',
                 'other_payment': 'Boshqa pul topshirildi',
                 'other_payment_cancelled': 'Boshqa pul topshirig‘i bekor qilindi'}[kind]
        item = {'id': entry.id, 'event_id': entry.id,
                'kind': kind, 'title': title,
                'created_at': entry.created_at, 'actor': entry.actor, 'user_id': entry.user_id,
                'branch_id': entry.branch_id, 'branch_name': branch.name if branch else 'Umumiy',
                'reason': detail.get('note', '') if other_payment else detail.get('reason', ''),
                'unread': entry.id in unread}
        if price_change:
            product_id = detail.get('product_id')
            product = db.get(Product, product_id) if product_id else None
            item['price'] = {'stock_id': detail.get('stock_id'), 'product_id': product_id,
                'name': detail.get('product_name') or (product.name if product else 'Mahsulot'),
                'sku': detail.get('sku') or (product.sku if product else ''),
                'labels_source': 'snapshot' if detail.get('product_name') and 'sku' in detail else 'current_product',
                'before': _amount(detail.get('before')), 'after': _amount(detail.get('after'))}
        elif stock_adjustment:
            item['stock'] = _stock_summary(db, entry)
        elif other_payment or other_cancelled:
            marker = (db.get(OperationCancellation, detail['cancellation_id']) if other_cancelled else
                      db.scalar(select(OperationCancellation).where(
                          OperationCancellation.kind == 'other_payment',
                          OperationCancellation.branch_id == entry.branch_id,
                          OperationCancellation.original_request_id == detail.get('request_id'))))
            record = marker.snapshot['record'] if marker else detail
            item['payment'] = {'id': marker.operation_id if marker else detail.get('payment_id'),
                'amount': _amount(record.get('amount')), 'method': record.get('method'),
                'recipient': record.get('recipient', ''), 'note': record.get('note', ''),
                'cancelled': bool(marker)}
            if other_payment:
                item['payment'].update({key: _amount(detail.get(key)) for key in
                                        ('balance_before', 'balance_after', 'unrecorded_amount')})
        else:
            marker = db.get(OperationCancellation, detail['cancellation_id'])
            item['sale'] = _sale_summary(db, marker, detailed)
        result.append(clean(item))
    return result


def _notifications(db, user, limit):
    conditions = (_event_condition(), _unread_condition(user.id))
    count = db.scalar(select(func.count()).select_from(Audit).where(*conditions))
    entries = list(db.scalars(select(Audit).where(*conditions).order_by(Audit.id.desc()).limit(limit)))
    return {'unread_count': count, 'items': _items(db, entries, user)}


def _central_notifications():
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'O‘zgarish xabarlarini web yoki umumiy bazaga ulangan yangi EXE orqali oching.')


@router.get('/changes')
def changes(branch_id: int | None = None, start: date | None = None, end: date | None = None,
            kind: Literal['price_change', 'stock_adjustment', 'sale_cancelled', 'other_payment', 'other_payment_cancelled'] | None = None,
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
            user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    conditions = [_event_condition(), *_dates(start, end)]
    if kind is not None:
        if kind in ('price_change', 'stock_adjustment', 'other_payment'):
            conditions.append(Audit.action == {'price_change': PRICE_CHANGE_ACTION,
                'stock_adjustment': STOCK_ADJUSTMENT_ACTION, 'other_payment': OTHER_PAYMENT_ACTION}[kind])
        else:
            conditions.extend((Audit.action == 'Amal bekor qilindi',
                               Audit.detail['kind'].as_string() == ('sale' if kind == 'sale_cancelled' else 'other_payment')))
    if branch_id is not None:
        conditions.append(Audit.branch_id == branch_id)

    def read(snapshot):
        total = snapshot.scalar(select(func.count()).select_from(Audit).where(*conditions))
        entries = list(snapshot.scalars(select(Audit).where(*conditions).order_by(Audit.id.desc())
                                       .offset(offset).limit(limit)))
        return {'items': _items(snapshot, entries, user), 'offset': offset, 'limit': limit,
                'total': total, 'has_more': offset + len(entries) < total}

    return _snapshot(db, read)


@router.get('/changes/{event_id}')
def change_detail(event_id: int, user=Depends(manager), db: Session = Depends(get_db)):
    def read(snapshot):
        entry = snapshot.scalar(select(Audit).where(Audit.id == event_id, _event_condition()))
        if entry is None:
            raise HTTPException(404, 'O‘zgarish topilmadi.')
        branch_scope(snapshot, user, entry.branch_id, required=True)
        return _items(snapshot, [entry], user, detailed=True)[0]

    return _snapshot(db, read)


@router.get('/notifications/changes')
def notifications(limit: int = Query(20, ge=1, le=50), user=Depends(boss), db: Session = Depends(get_db)):
    _central_notifications()
    return _snapshot(db, lambda snapshot: _notifications(snapshot, user, limit))


@router.post('/notifications/changes/read')
def read_notifications(data: ReadChanges, user=Depends(boss), db: Session = Depends(get_db)):
    _central_notifications()
    try:
        locked = db.scalar(select(User).where(User.id == user.id).with_for_update()
                           .execution_options(populate_existing=True))
        if not locked or not locked.active or locked.role != 'boss':
            raise HTTPException(403, 'Xabarlarni faqat boshliq o‘qilgan deb belgilaydi.')
        ids = list(dict.fromkeys(data.event_ids))
        entries = list(db.scalars(select(Audit).where(Audit.id.in_(ids), _event_condition())))
        if len(entries) != len(ids):
            raise HTTPException(404, 'O‘zgarish xabari topilmadi. Ro‘yxatni yangilang.')
        unread = set(db.scalars(select(Audit.id).where(Audit.id.in_(ids), _unread_condition(user.id))))
        for entry in entries:
            if entry.id in unread:
                db.add(Audit(user_id=user.id, actor=locked.name, branch_id=None, action=READ_ACTION,
                             detail={'event_id': entry.id}))
        db.flush()
        count = db.scalar(select(func.count()).select_from(Audit).where(
            _event_condition(), _unread_condition(user.id)))
        result = {'ok': True, 'acknowledged': ids, 'unread_count': count}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
