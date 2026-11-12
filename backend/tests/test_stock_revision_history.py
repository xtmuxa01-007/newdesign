"""Admin revision preserves historical sales, finances and past day closings."""
from datetime import date, datetime, timezone
from decimal import Decimal
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select
import test_branch_archive as fixture
from app import stock_valuation_history as history
from app.models import Receipt, Sale, Stock
from app.telegram_daily_reports import build_report


class StockRevisionHistoryTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale

    @staticmethod
    def instant(day, hour=0):
        return datetime.fromisoformat(day).replace(hour=hour, tzinfo=history.TZ).astimezone(timezone.utc)

    def snapshot(self, except_tables=()):
        excluded = {'auth_sessions', 'login_attempts', *except_tables}
        with self.sessions() as db:
            return {table.name: sorted(list(db.execute(select(table))), key=repr)
                    for table in Sale.metadata.sorted_tables if table.name not in excluded}

    def analysis(self):
        response = self.owner.get('/api/products/1/analytics?branch_id=1&start=2026-11-03&end=2026-11-03')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_revision_updates_current_stock_without_rewriting_yesterday_or_business_records(self):
        receipt = self.owner.post('/api/receipts', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1, 'product_id': 1,
            'kg': '1', 'price': '10000', 'note': 'Original receipt'})
        self.assertEqual(receipt.status_code, 201, receipt.text)
        sale = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sale.status_code, 201, sale.text)
        with self.sessions() as db:
            db.get(Receipt, receipt.json()['id']).created_at = self.instant('2026-11-03', 12)
            db.get(Sale, sale.json()['id']).created_at = self.instant('2026-11-03', 13)
            with patch.object(history, 'utc_now', return_value=self.instant('2026-11-03', 23)):
                history.initialize_history(db)
                db.commit()
        admin = self.client('admin')
        before_analysis = self.analysis()
        before_business = self.snapshot({'stocks', 'stock_adjustments', 'audit_logs', 'stock_valuation_versions'})
        with self.sessions() as db:
            original_versions = list(db.execute(select(history.StockValuationVersion.__table__)))
            other_stock = (db.get(Stock, 2).kg, db.get(Stock, 2).price, db.get(Stock, 2).discount)
        payload = {'request_id': str(uuid.uuid4()), 'expected_kg': '10',
                   'kg': '7.125', 'reason': 'Reviziyada haqiqiy qoldiq tekshirildi'}
        with patch.object(history, 'utc_now', return_value=self.instant('2026-11-04', 10)):
            response = admin.post('/api/stocks/1/adjustments', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot({'stocks', 'stock_adjustments', 'audit_logs', 'stock_valuation_versions'}), before_business)
        after_analysis = self.analysis()
        for field in ('summary', 'daily', 'recent_sales', 'recent_receipts', 'price_history'):
            self.assertEqual(after_analysis[field], before_analysis[field], field)
        self.assertEqual(Decimal(after_analysis['current_stock']['kg']), Decimal('7.125'))
        self.assertEqual(Decimal(after_analysis['current_stock']['retail_value']), Decimal('71250'))
        with self.sessions() as db, patch.object(history, 'utc_now', return_value=self.instant('2026-11-05', 8)):
            self.assertEqual(list(db.execute(select(history.StockValuationVersion.__table__).where(
                history.StockValuationVersion.id.in_([row.id for row in original_versions])))), original_versions)
            self.assertEqual((db.get(Stock, 2).kg, db.get(Stock, 2).price, db.get(Stock, 2).discount), other_stock)
            self.assertEqual((db.get(Stock, 1).price, db.get(Stock, 1).discount), (Decimal('10000'), Decimal('0')))
            yesterday = build_report(db, date(2026, 11, 3), self.instant('2026-11-05', 8))['branches'][0]
            revised_day = build_report(db, date(2026, 11, 4), self.instant('2026-11-05', 8))['branches'][0]
            for field, value in {'inventory_kg': '10', 'inventory': '100000', 'sales_kg': '1', 'sales': '10000'}.items():
                self.assertEqual(Decimal(yesterday[field]), Decimal(value), field)
            self.assertEqual(Decimal(revised_day['inventory_kg']), Decimal('7.125'))
            self.assertEqual(Decimal(revised_day['inventory']), Decimal('71250'))
            self.assertEqual(Decimal(revised_day['sales_kg']), Decimal('0'))
            self.assertEqual(Decimal(revised_day['sales']), Decimal('0'))

    def test_stale_revision_creates_no_adjustment_audit_or_valuation_version(self):
        admin = self.client('admin')
        with self.sessions() as db, patch.object(history, 'utc_now', return_value=self.instant('2026-11-03', 23)):
            history.initialize_history(db)
            db.commit()
        before = self.snapshot()
        with patch.object(history, 'utc_now', return_value=self.instant('2026-11-04', 10)):
            response = admin.post('/api/stocks/1/adjustments', json={
                'request_id': str(uuid.uuid4()), 'expected_kg': '9', 'kg': '7.125', 'reason': 'Eskirgan reviziya oynasi'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.snapshot(), before)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class StockRevisionHistoryPostgresTest(StockRevisionHistoryTest):
    postgres = True
