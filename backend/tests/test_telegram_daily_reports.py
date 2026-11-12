"""All accounting data and recipients here are disposable synthetic fixtures."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Branch, BranchArchive, Product, Sale, SaleItem, Stock, Supplier, User
from app import stock_valuation_history as history
from app import telegram_daily_reports as reports


class DailyReportAccountingTest(unittest.TestCase):
    def moment(self, day, hour=12):
        return datetime.combine(date.fromisoformat(day), datetime.min.time(), reports.TZ).replace(hour=hour)

    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.day = date(2026, 11, 2)
        with self.sessions() as db:
            db.add_all([Branch(id=1, name='Shahrixon <&>'), Branch(id=2, name='Andijon'),
                        Branch(id=3, name='Toshkent'), Supplier(id=1, name='Fixture')])
            db.flush()
            db.add_all([User(id=1, name='Fixture', username='fixture', role='boss', password_hash='fixture'),
                        Product(id=1, name='Fixture A', sku='A', supplier_id=1),
                        Product(id=2, name='Fixture B', sku='B', supplier_id=1)])
            db.flush()
            with patch.object(history, 'utc_now', return_value=self.moment('2026-11-01').astimezone(timezone.utc)):
                history.initialize_history(db)
                db.add_all([Stock(id=1, branch_id=1, product_id=1, kg=Decimal('2.123'), price=Decimal('10000.05'), discount=Decimal('5')),
                            Stock(id=2, branch_id=1, product_id=2, kg=Decimal('0.001'), price=Decimal('15'), discount=0),
                            Stock(id=3, branch_id=2, product_id=1, kg=10, price=80000, discount=0)])
                db.commit()
            db.add(BranchArchive(branch_id=2, user_id=1))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def add_sale(self, moment, branch=1, total='100', items=False):
        with self.sessions() as db:
            sale = Sale(request_id=str(moment) + str(branch), branch_id=branch, user_id=1,
                        total=Decimal(total), cash=0, card=0, donation=0, created_at=moment.astimezone(timezone.utc))
            db.add(sale)
            db.flush()
            if items:
                for product in (1, 2):
                    db.add(SaleItem(sale_id=sale.id, product_id=product, supplier_id=1, name='Fixture',
                                    sku=str(product), kg=1, price=50, discount=0, total=50))
            db.commit()
            return sale.id

    def report(self):
        with self.sessions() as db:
            return reports.build_report(db, self.day, self.moment('2026-11-03', 8))

    def test_yesterday_timezone_bounds_multi_item_debt_sale_zero_and_archived_branches(self):
        self.add_sale(self.moment('2026-11-02', 0), total='100.25', items=True)
        self.add_sale(self.moment('2026-11-02', 23), branch=2, total='200.50')
        self.add_sale(self.moment('2026-11-01', 23), total='999')
        self.add_sale(self.moment('2026-11-03', 0), total='888')
        result = self.report()
        self.assertEqual([Decimal(b['sales']) for b in result['branches']], [Decimal('100.25'), Decimal('200.50'), 0])
        self.assertEqual(len(result['messages']), 4)
        self.assertEqual([m['key'] for m in result['messages']], ['greeting', 'branch:1', 'branch:2', 'branch:3'])
        self.assertIn('Assalomu alaykum, Muhammadjon Ahmedov!', result['messages'][0]['text'])
        self.assertIn('2-noyabr 2026 kungi savdo hisoboti', result['messages'][0]['text'])
        self.assertIn('Shahrixon &lt;&amp;&gt;', result['messages'][1]['text'])
        self.assertIn('(arxiv)', result['messages'][2]['text'])

    def test_closing_inventory_is_not_changed_by_morning_stock_price_or_discount(self):
        before = self.report()
        with self.sessions() as db, patch.object(history, 'utc_now', return_value=self.moment('2026-11-03', 7).astimezone(timezone.utc)):
            stock = db.get(Stock, 1)
            stock.kg, stock.price, stock.discount = Decimal('500'), Decimal('90000'), Decimal('0')
            db.commit()
        after = self.report()
        self.assertEqual(before['branches'], after['branches'])
        self.assertEqual(Decimal(after['branches'][0]['inventory']), Decimal('20168.62'))

    def test_queries_do_not_modify_business_records_and_live_edits_or_deletes_are_reflected(self):
        sale_id = self.add_sale(self.moment('2026-11-02'), total='100')
        with self.sessions() as db:
            db.get(Sale, sale_id).total = Decimal('40')
            db.commit()
            counts = (db.scalar(select(func.count()).select_from(Sale)), db.scalar(select(func.count()).select_from(Stock)))
            self.assertEqual(Decimal(reports.build_report(db, self.day, self.moment('2026-11-03', 8))['branches'][0]['sales']), 40)
            self.assertEqual(counts, (db.scalar(select(func.count()).select_from(Sale)), db.scalar(select(func.count()).select_from(Stock))))
            db.delete(db.get(Sale, sale_id))
            db.commit()
        self.assertEqual(Decimal(self.report()['branches'][0]['sales']), 0)

    def test_unfinished_days_and_unavailable_history_fail_closed(self):
        with self.sessions() as db:
            with self.assertRaises(ValueError):
                reports.build_report(db, date(2026, 11, 3), self.moment('2026-11-03', 8))
            with self.assertRaises(ValueError):
                reports.build_report(db, date(2026, 10, 31), self.moment('2026-11-03', 8))
            with self.assertRaises(ValueError):
                reports.build_report(db, self.day, datetime(2026, 11, 3, 8))

    def test_api_lifespan_initializes_history_but_default_worker_sends_nothing(self):
        from fastapi.testclient import TestClient
        from app import main as application
        from app.telegram_daily_worker import DailyReportWorker
        Base.metadata.create_all(self.engine)
        with tempfile.TemporaryDirectory(prefix='crm-report-lifespan-') as directory:
            with patch.object(application, 'engine', self.engine), \
                    patch.object(application, 'SessionLocal', self.sessions), \
                    patch.object(application, 'UPLOADS', Path(directory)), \
                    patch.dict(os.environ, {'CRM_TELEGRAM_DAILY_REPORT_ENABLED': '0'}), \
                    patch.object(DailyReportWorker, '_send') as send:
                with TestClient(application.app) as client:
                    self.assertEqual(client.get('/api/health').json()['status'], 'ok')
                send.assert_not_called()
        with self.sessions() as db:
            self.assertIsNotNone(db.get(history.StockValuationState, 1))


if __name__ == '__main__':
    unittest.main()
