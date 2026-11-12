"""Day-closing valuation: SQLite and opt-in marva_ci schemas, never Telegram."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from sqlalchemy import URL, create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Branch, BranchArchive, Product, ProductArchive, Stock, Supplier, User
from app import stock_valuation_history as history


class StockValuationHistoryTest(unittest.TestCase):
    def setUp(self):
        if getattr(self, 'postgres', False):
            # Only the explicitly enabled disposable CI database is allowed.
            if os.getenv('CRM_TEST_POSTGRES') != '1' or os.getenv('DB_NAME') != 'marva_ci':
                raise RuntimeError('PostgreSQL sinovi faqat yoqilgan marva_ci bazasida mumkin.')
            self.pg_schema = 'test_' + uuid.uuid4().hex
            self.engine = create_engine(URL.create('postgresql+psycopg',
                username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                host=os.environ['DB_HOST'], database='marva_ci'),
                connect_args={'options': '-csearch_path=' + self.pg_schema})
            with self.engine.begin() as connection:
                connection.execute(text('CREATE SCHEMA ' + self.pg_schema))
        else:
            self.engine = create_engine('sqlite:///:memory:')
            @event.listens_for(self.engine, 'connect')
            def foreign_keys(connection, record):
                connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.clock = patch.object(history, 'utc_now', return_value=self.moment('2026-11-03', 8))
        self.now = self.clock.start()
        self.db.add_all([Branch(id=1, name='First'), Branch(id=2, name='Second'), Branch(id=3, name='Empty'),
                         Supplier(id=1, name='Supplier'),
                         User(id=1, username='fixture', name='Fixture', role='boss', password_hash='not-a-real-password')])
        self.db.flush()
        self.db.add_all([Product(id=1, name='One', sku='ONE', supplier_id=1),
                         Product(id=2, name='Two', sku='TWO', supplier_id=1)])
        self.db.flush()
        self.db.add_all([Stock(id=1, branch_id=1, product_id=1, kg=Decimal('2'), price=Decimal('100'), discount=0),
                         Stock(id=2, branch_id=1, product_id=2, kg=Decimal('3'), price=Decimal('50'), discount=10),
                         Stock(id=3, branch_id=2, product_id=1, kg=Decimal('1'), price=Decimal('20'), discount=0)])
        self.db.commit()

        if getattr(self, 'postgres', False):
            # Explicit fixture IDs do not advance PostgreSQL's serial sequence.
            # Later inserts must behave like normally generated application IDs.
            self.db.execute(text("SELECT setval(pg_get_serial_sequence('stocks', 'id'), (SELECT max(id) FROM stocks))"))
            self.db.commit()

    def tearDown(self):
        self.db.close()
        self.clock.stop()
        if getattr(self, 'postgres', False):
            with self.engine.begin() as connection:
                connection.execute(text('DROP SCHEMA ' + self.pg_schema + ' CASCADE'))
        self.engine.dispose()

    @staticmethod
    def moment(day, hour=0):
        return datetime.fromisoformat(day).replace(hour=hour, tzinfo=history.TZ).astimezone(timezone.utc)

    def baseline(self, day='2026-11-01', hour=8):
        self.now.return_value = self.moment(day, hour)
        started = history.initialize_history(self.db)
        self.db.commit()
        self.now.return_value = self.moment('2026-11-03', 8)
        return started

    def change(self, stock_id, instant, **values):
        self.now.return_value = instant
        stock = self.db.get(Stock, stock_id)
        for key, value in values.items():
            setattr(stock, key, Decimal(value))
        self.db.commit()
        self.now.return_value = self.moment('2026-11-03', 8)

    def version_count(self):
        return self.db.scalar(select(func.count()).select_from(history.StockValuationVersion))

    def test_baseline_copies_existing_rows_once_and_does_not_commit(self):
        self.assertEqual(self.version_count(), 0)
        self.now.return_value = self.moment('2026-11-01', 8)
        started = history.initialize_history(self.db)
        self.assertEqual(self.version_count(), 3)
        self.db.rollback()
        self.assertEqual(self.version_count(), 0)
        self.assertIsNone(self.db.get(history.StockValuationState, 1))
        self.assertEqual(self.baseline(), started)
        self.assertEqual(history.initialize_history(self.db), started)
        self.assertEqual(self.version_count(), 3)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1)), {1: Decimal('335.00'), 2: Decimal('20.00')})

    def test_midnight_boundary_quantity_price_discount_and_next_day_changes(self):
        self.baseline()
        cutoff = self.moment('2026-11-02')
        self.change(1, cutoff - timedelta(microseconds=2), kg='3.125')
        self.change(1, cutoff - timedelta(microseconds=1), price='200.01', discount='12.5')
        expected = history.line_total(Decimal('3.125'), Decimal('200.01'), Decimal('12.5')) + Decimal('135')
        self.change(1, cutoff, kg='1', price='999', discount='0')
        self.change(2, cutoff + timedelta(seconds=1), kg='0')
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1)), {1: expected, 2: Decimal('20.00')})
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 2)), {1: Decimal('999.00'), 2: Decimal('20.00')})

    def test_rolled_back_update_has_no_history_or_stock_effect(self):
        self.baseline()
        self.now.return_value = self.moment('2026-11-01', 16)
        stock = self.db.get(Stock, 1)
        stock.kg = Decimal('8')
        self.db.flush()
        self.assertEqual(self.version_count(), 4)
        self.db.rollback()
        self.assertEqual(self.version_count(), 3)
        self.assertEqual(self.db.get(Stock, 1).kg, Decimal('2'))
        self.now.return_value = self.moment('2026-11-03', 8)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1))[1], Decimal('335.00'))

    def test_insert_delete_tombstone_and_reinsert_same_pair(self):
        self.baseline()
        self.now.return_value = self.moment('2026-11-01', 20)
        stock = Stock(branch_id=2, product_id=2, kg=Decimal('5'), price=Decimal('7.77'), discount=Decimal('2.5'))
        self.db.add(stock)
        self.db.commit()
        expected = Decimal('20') + history.line_total(Decimal('5'), Decimal('7.77'), Decimal('2.5'))
        self.now.return_value = self.moment('2026-11-02', 10)
        self.db.delete(stock)
        self.db.commit()
        self.now.return_value = self.moment('2026-11-03', 8)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1))[2], expected)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 2))[2], Decimal('20.00'))
        self.now.return_value = self.moment('2026-11-02', 15)
        self.db.add(Stock(branch_id=2, product_id=2, kg=2, price=9, discount=0))
        self.db.commit()
        self.now.return_value = self.moment('2026-11-03', 8)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 2))[2], Decimal('38.00'))

    def test_last_version_id_resolves_equal_timestamps(self):
        self.baseline()
        instant = self.moment('2026-11-01', 22)
        self.change(1, instant, kg='4')
        self.change(1, instant, kg='5')
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1))[1], Decimal('635.00'))

    def test_archived_products_and_branches_keep_value_and_reads_do_not_write(self):
        self.baseline()
        self.db.add_all([BranchArchive(branch_id=1, user_id=1), ProductArchive(product_id=1, user_id=1)])
        self.db.commit()
        before = self.version_count()
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1)), {1: Decimal('335.00'), 2: Decimal('20.00')})
        self.assertEqual(self.version_count(), before)

    def test_missing_late_equal_midnight_and_future_history_are_unavailable(self):
        with self.assertRaises(history.StockHistoryUnavailable):
            history.closing_values(self.db, date(2026, 11, 1))
        self.baseline(day='2026-11-02', hour=0)
        with self.assertRaises(history.StockHistoryUnavailable):
            history.closing_values(self.db, date(2026, 11, 1))
        with self.assertRaises(history.StockHistoryUnavailable):
            history.closing_values(self.db, date(2026, 10, 31))
        with self.assertRaises(history.StockHistoryUnavailable):
            history.closing_values(self.db, date(2026, 11, 3))
        with self.assertRaises(ValueError):
            history.closing_values(self.db, datetime(2026, 11, 1))

    def test_empty_baseline_has_known_zero_and_new_stock_starts_later(self):
        for stock in self.db.scalars(select(Stock)):
            self.db.delete(stock)
        self.db.commit()
        self.baseline()
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1)), {})
        self.now.return_value = self.moment('2026-11-02', 9)
        self.db.add(Stock(branch_id=1, product_id=1, kg=3, price=10, discount=0))
        self.db.commit()
        self.now.return_value = self.moment('2026-11-03', 8)
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 1)), {})
        self.assertEqual(history.closing_values(self.db, date(2026, 11, 2)), {1: Decimal('30.00')})

    def test_stock_pair_cannot_move_and_leave_false_old_value(self):
        self.baseline()
        self.db.get(Stock, 1).branch_id = 3
        with self.assertRaises(ValueError):
            self.db.flush()
        self.db.rollback()
        self.assertEqual(self.db.get(Stock, 1).branch_id, 1)
        self.assertEqual(self.version_count(), 3)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class StockValuationHistoryPostgresTest(StockValuationHistoryTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
