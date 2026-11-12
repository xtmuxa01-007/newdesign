"""Transactional stock versions for exact future Tashkent day-closing values.

The first baseline is the start of coverage, never a reconstruction of older
inventory. Stock mapper writes append in the same transaction as the business
operation, so a rollback also removes its valuation version. Core/bulk SQL
against ``stocks`` bypasses mapper events and must not be used by stock writers.
The maintenance-only database reset intentionally clears both history tables.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, event, func, inspect, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .accounting import ZERO, line_total
from .db import Base
from .models import Stock


TZ = ZoneInfo('Asia/Tashkent')


def utc_now():
    """A single patchable clock; values persisted in UTC."""
    return datetime.now(timezone.utc)


def _utc(value):
    # SQLite drops tzinfo on DateTime values; those stored instants are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class StockHistoryUnavailable(ValueError):
    """The requested closing predates trustworthy coverage or has not occurred."""


class StockValuationState(Base):
    __tablename__ = 'stock_valuation_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('id = 1'),)


class StockValuationVersion(Base):
    __tablename__ = 'stock_valuation_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'))
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    price: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint('kg >= 0 AND price >= 0 AND discount >= 0 AND discount <= 100'),
        Index('ix_stock_valuation_pair_time', 'branch_id', 'product_id', 'recorded_at', 'id'),
        {'sqlite_autoincrement': True},
    )


def initialize_history(db):
    """Take one baseline in the caller's transaction; the caller commits it.

    Startup runs before request handling. The PostgreSQL lock also serializes
    parallel workers and stops a concurrent stock write entering the baseline.
    Existing branches/products with no Stock row have a known zero balance.
    """
    db.flush()
    connection = db.connection()
    if connection.dialect.name == 'postgresql':
        connection.execute(text('LOCK TABLE stocks IN SHARE ROW EXCLUSIVE MODE'))
        connection.execute(text('LOCK TABLE stock_valuation_state IN EXCLUSIVE MODE'))
    existing = connection.scalar(select(StockValuationState.started_at).where(StockValuationState.id == 1))
    if existing is not None:
        return _utc(existing)
    started_at = _utc(utc_now())
    records = connection.execute(select(Stock.branch_id, Stock.product_id, Stock.kg, Stock.price, Stock.discount)).mappings()
    values = [dict(record, recorded_at=started_at) for record in records]
    if values:
        connection.execute(StockValuationVersion.__table__.insert(), values)
    connection.execute(StockValuationState.__table__.insert().values(id=1, started_at=started_at))
    return started_at


def _enabled(connection):
    # No implicit baseline from a transaction: the full stock set must be known.
    return connection.scalar(select(StockValuationState.id).where(StockValuationState.id == 1)) is not None


def _append(connection, target, *, deleted=False):
    if not _enabled(connection):
        return
    connection.execute(StockValuationVersion.__table__.insert().values(
        branch_id=target.branch_id, product_id=target.product_id,
        kg=ZERO if deleted else target.kg, price=target.price, discount=target.discount,
        recorded_at=_utc(utc_now()),
    ))


@event.listens_for(Stock, 'after_insert')
def _inserted(mapper, connection, target):
    _append(connection, target)


@event.listens_for(Stock, 'after_update')
def _updated(mapper, connection, target):
    # Stock writers identify a permanent branch/product pair. Moving that row
    # would otherwise leave its old pair's last version looking still active.
    state = inspect(target)
    if any(state.attrs[key].history.has_changes() for key in ('branch_id', 'product_id')):
        raise ValueError('Ombor qatorining filial va mahsulot bog‘lanishi o‘zgartirilmaydi.')
    _append(connection, target)


@event.listens_for(Stock, 'after_delete')
def _deleted(mapper, connection, target):
    # A tombstone prevents an earlier nonzero version surviving a deleted row.
    _append(connection, target, deleted=True)


def closing_balances(db, report_day):
    """Value and weigh the latest versions before the following local midnight.

    All archived products/branches remain included. Values use the exact same
    per-stock money rounding as the ordinary dashboard. Missing history raises;
    current Stock values are never substituted for a past closing.
    """
    if type(report_day) is not date:
        raise ValueError('Hisobot kuni sana bo‘lishi kerak.')
    try:
        cutoff = datetime.combine(report_day + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc)
    except OverflowError:
        raise ValueError('Hisobot sanasi yaroqsiz.') from None
    started_at = db.scalar(select(StockValuationState.started_at).where(StockValuationState.id == 1))
    if started_at is None or _utc(started_at) >= cutoff:
        raise StockHistoryUnavailable('Bu kun oxiridagi ombor tarixi hali yig‘ilmagan. Joriy qoldiq eski kun o‘rniga qo‘yilmaydi.')
    if cutoff > _utc(utc_now()):
        raise StockHistoryUnavailable('Bu kun hali yakunlanmagan; kun oxiridagi ombor qiymati tayyor emas.')
    version = StockValuationVersion
    ranked = select(
        version.branch_id, version.kg, version.price, version.discount,
        func.row_number().over(
            partition_by=(version.branch_id, version.product_id),
            order_by=(version.recorded_at.desc(), version.id.desc()),
        ).label('position'),
    ).where(version.recorded_at < cutoff).subquery()
    result = {}
    for row in db.execute(select(ranked).where(ranked.c.position == 1)):
        balance = result.setdefault(row.branch_id, {'inventory': ZERO, 'kg': Decimal('0.000')})
        balance['inventory'] += line_total(row.kg, row.price, row.discount)
        balance['kg'] += row.kg
    return result


def closing_values(db, report_day):
    """Compatibility wrapper for callers that only need closing money values."""
    return {branch_id: balance['inventory'] for branch_id, balance in closing_balances(db, report_day).items()}
