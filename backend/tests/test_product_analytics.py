"""Faqat disposable fixture bazalarda mahsulot tahlili va tarixiy narxlar."""
from datetime import datetime, timedelta
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import select
import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
import test_sales_analytics as analytics_fixture
from app.models import Audit, Product, ProductArchive, Receipt, Sale, Stock
from app.routes_analytics import TZ


class ProductAnalyticsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel
    create_sale = cancellation_fixture.OperationCancelTest.create_sale
    edit_sale = cancellation_fixture.OperationCancelTest.edit_sale
    receipt = cancellation_fixture.OperationCancelTest.receipt
    seed_sale = analytics_fixture.SalesAnalyticsTest.seed_sale
    moment = analytics_fixture.SalesAnalyticsTest.moment

    def data(self, product_id=1, branch=1, start=None, end=None, client=None):
        path = f'/api/products/{product_id}/analytics?branch_id={branch}'
        if start:
            path += '&start=' + start
        if end:
            path += '&end=' + end
        response = (client or self.owner).get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def day(self, value):
        return datetime.fromisoformat(value).astimezone(TZ).date().isoformat()

    def state(self):
        with self.sessions() as db:
            return {table.name: sorted(list(db.execute(select(table))), key=repr)
                    for table in Sale.metadata.sorted_tables}

    def assert_amounts(self, record, **values):
        for key, value in values.items():
            self.assertIsInstance(record[key], str, key)
            self.assertEqual(Decimal(record[key]), Decimal(str(value)), key)

    def test_default_current_tashkent_month_empty_and_full_database_unchanged(self):
        fixed = datetime(2026, 10, 2, 23, 30, tzinfo=TZ)
        before = self.state()
        with patch('app.routes_analytics.datetime', wraps=datetime) as clock:
            clock.now.return_value = fixed
            result = self.data()
        self.assertEqual(result['filter'], {'branch_id': 1, 'start': '2026-10-01', 'end': '2026-10-02'})
        self.assertEqual(result['product']['name'], 'Product')
        self.assertEqual(result['product']['supplier'], 'Supplier')
        self.assertFalse(result['product']['archived'])
        self.assertEqual(result['summary']['sales_count'], 0)
        self.assertEqual(result['summary']['receipt_count'], 0)
        self.assert_amounts(result['summary'], sold_kg=0, sales_total=0, mini_discount=0,
                            average_price_per_kg=0, received_kg=0)
        self.assert_amounts(result['current_stock'], kg=10, price=10000, discount=0,
                            effective_price=10000, retail_value=100000)
        self.assertTrue(result['permissions']['can_edit_price'])
        self.assertEqual([row['date'] for row in result['daily']], ['2026-10-01', '2026-10-02'])
        self.assertEqual(result['recent_sales'], [])
        self.assertEqual(result['recent_receipts'], [])
        self.assertEqual(result['price_history'], [])
        self.assertEqual(self.state(), before)

    def test_role_branch_product_and_date_validation(self):
        path = '/api/products/1/analytics?branch_id=1'
        self.assertEqual(self.client().get(path).status_code, 401)
        self.assertEqual(self.client('cashier').get(path).status_code, 403)
        admin = self.client('admin')
        self.assertEqual(self.data(client=admin)['filter']['branch_id'], 1)
        self.assertEqual(admin.get('/api/products/1/analytics?branch_id=2').status_code, 403)
        self.assertEqual(self.data(branch=2)['filter']['branch_id'], 2)
        self.assertEqual(self.owner.get('/api/products/1/analytics').status_code, 422)
        self.assertEqual(self.owner.get('/api/products/1/analytics?branch_id=999').status_code, 404)
        self.assertEqual(self.owner.get('/api/products/999/analytics?branch_id=1').status_code, 404)
        for suffix in ('&start=bad', '&start=2026-10-02&end=2026-10-01',
                       '&start=2026-01-01&end=9999-12-31', '&start=0001-01-01&end=2026-01-01'):
            self.assertEqual(self.owner.get(path + suffix).status_code, 422, suffix)

    def test_missing_stock_and_archived_product_remain_readable_without_price_edit(self):
        with self.sessions() as db:
            db.add(Product(id=2, name='No stock', sku='NONE', supplier_id=1))
            db.add(ProductArchive(product_id=1, user_id=4))
            db.commit()
        before = self.state()
        empty = self.data(product_id=2)
        self.assertIsNone(empty['current_stock']['stock_id'])
        self.assert_amounts(empty['current_stock'], kg=0, price=0, discount=0,
                            effective_price=0, retail_value=0)
        self.assertFalse(empty['permissions']['can_edit_price'])
        self.assertTrue(empty['permissions']['price_edit_reason'])
        archived = self.data()
        self.assertTrue(archived['product']['archived'])
        self.assertFalse(archived['permissions']['can_edit_price'])
        self.assertEqual(self.state(), before)

    def test_archived_branch_history_is_readable_and_price_edit_is_disabled(self):
        sold, _ = self.create_sale()
        response = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(response.status_code, 200, response.text)
        result = self.data(start=self.day(sold['created_at']), end=self.day(sold['created_at']))
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assert_amounts(result['summary'], sold_kg=1, sales_total=10000)
        self.assertFalse(result['permissions']['can_edit_price'])
        self.assertIn('arxiv', result['permissions']['price_edit_reason'].lower())

    def test_product_net_totals_mini_discount_and_receipts_do_not_multiply_each_other(self):
        with self.sessions() as db:
            db.add(Product(id=2, name='Second', sku='SECOND', supplier_id=1))
            db.flush()
            db.add(Stock(id=3, branch_id=1, product_id=2, kg=10, price=20000, discount=0))
            db.commit()
        sold, _ = self.create_sale(items=[{'product_id': 1, 'kg': '1'}, {'product_id': 2, 'kg': '1'}],
                                   expected_total='30000', mini_discount='1000', cash='29000')
        self.create_sale(items=[{'product_id': 1, 'kg': '0.5'}], expected_total='5000', cash='6000')
        self.create_sale(branch_id=2)
        first, _ = self.receipt(kg='1', price='11000')
        second, _ = self.receipt(kg='2', price='12000')
        today = self.day(sold['created_at'])
        before = self.state()
        result = self.data(start=today, end=today)
        self.assertEqual(result['summary']['sales_count'], 2)
        self.assertEqual(result['summary']['receipt_count'], 2)
        self.assert_amounts(result['summary'], sold_kg='1.500', sales_total='14666.67',
                            mini_discount='333.33', average_price_per_kg='9777.78', received_kg=3)
        self.assert_amounts(result['daily'][0], kg='1.500', total='14666.67')
        self.assertEqual(result['daily'][0]['sales_count'], 2)
        self.assert_amounts(result['current_stock'], kg='11.500', price=12000, retail_value=138000)
        self.assertEqual(len(result['recent_sales']), 2)
        self.assertTrue(all(Decimal(row['price']) == 10000 for row in result['recent_sales']))
        self.assertEqual([row['id'] for row in result['recent_receipts']], [second['id'], first['id']])
        self.assertEqual(self.state(), before)
        self.assert_amounts(self.data(product_id=2, start=today, end=today)['summary'],
                            sold_kg=1, sales_total='19333.33', mini_discount='666.67', received_kg=0)

    def test_tashkent_midnight_and_inclusive_end_apply_to_sales_and_receipts(self):
        beginning = self.moment('2026-03-01', hour=0)
        ending = self.moment('2026-04-01', hour=0)
        for stamp, kg in ((beginning - timedelta(microseconds=1), '4'), (beginning, '1'),
                          (ending - timedelta(microseconds=1), '2'), (ending, '8')):
            self.seed_sale(stamp, total=str(Decimal(kg) * 10000), kg=kg)
            with self.sessions() as db:
                db.add(Receipt(request_id=str(uuid.uuid4()), branch_id=1, product_id=1,
                               user_id=4, kg=Decimal(kg), price=Decimal(10000),
                               created_at=stamp, note='Boundary fixture'))
                db.commit()
        result = self.data(start='2026-03-01', end='2026-03-31')
        self.assertEqual(result['summary']['sales_count'], 2)
        self.assertEqual(result['summary']['receipt_count'], 2)
        self.assert_amounts(result['summary'], sold_kg=3, sales_total=30000, received_kg=3)
        self.assertEqual(len(result['daily']), 31)
        self.assert_amounts(result['daily'][0], kg=1, total=10000)
        self.assert_amounts(result['daily'][-1], kg=2, total=20000)
        # The selected period never turns today's stock into an old closing balance.
        self.assert_amounts(result['current_stock'], kg=10, price=10000)

    def test_legacy_duplicate_product_lines_count_one_sale_and_keep_decimal_totals(self):
        self.seed_sale(self.moment('2026-09-15'), total='30.03',
                       items=[(1, '0.100', '10.01'), (1, '0.200', '20.02')])
        result = self.data(start='2026-09-15', end='2026-09-15')
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assertEqual(result['daily'][0]['sales_count'], 1)
        self.assert_amounts(result['summary'], sold_kg='0.300', sales_total='30.03',
                            average_price_per_kg='100.10')
        self.assertEqual(len(result['recent_sales']), 2)
        self.assertNotEqual(result['recent_sales'][0]['id'], result['recent_sales'][1]['id'])

    def test_sale_edit_is_reported_at_original_date_instead_of_edit_date(self):
        sold, _ = self.create_sale()
        original_time = datetime.fromisoformat(sold['created_at']) - timedelta(days=1)
        with self.sessions() as db:
            db.get(Sale, sold['id']).created_at = original_time
            db.commit()
        edited = self.edit_sale(sold)
        original_day = original_time.astimezone(TZ).date().isoformat()
        edit_day = self.day(sold['created_at'])
        result = self.data(start=original_day, end=original_day)
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assert_amounts(result['summary'], sold_kg='0.500', sales_total=5000)
        self.assertEqual(result['recent_sales'][0]['created_at'], edited['created_at'])
        self.assertEqual(self.data(start=edit_day, end=edit_day)['summary']['sales_count'], 0)

    def test_edited_current_lines_use_original_sale_date_and_cancelled_sources_are_excluded(self):
        first, _ = self.create_sale()
        day = self.day(first['created_at'])
        self.edit_sale(first)
        second, _ = self.create_sale()
        receipt, _ = self.receipt(kg='2', price='12000')
        self.assertEqual(self.cancel('sale', second['id']).status_code, 200)
        self.assertEqual(self.cancel('receipt', receipt['id']).status_code, 200)
        result = self.data(start=day, end=day)
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assertEqual(result['summary']['receipt_count'], 0)
        self.assert_amounts(result['summary'], sold_kg='0.500', sales_total=5000, received_kg=0)
        self.assertEqual([row['sale_id'] for row in result['recent_sales']], [first['id']])
        self.assertEqual(result['recent_receipts'], [])
        with self.sessions() as db:
            self.assertGreaterEqual(len(list(db.scalars(select(Audit).where(
                Audit.action == 'Amal bekor qilindi')))), 2)

    def test_all_time_price_history_is_scoped_and_recent_lists_are_bounded(self):
        start = self.moment('2020-01-01')
        with self.sessions() as db:
            for index in range(25):
                db.add(Audit(user_id=4, actor='Fixture admin', branch_id=1,
                    action='Mahsulot narxi o‘zgartirildi', created_at=start + timedelta(days=index),
                    detail={'product_id': 1, 'stock_id': 1, 'before': str(10000 + index),
                            'after': str(10001 + index), 'reason': f'Price fixture {index}'}))
            for product_id, branch in ((2, 1), (1, 2)):
                db.add(Audit(user_id=4, actor='Different scope', branch_id=branch,
                    action='Mahsulot narxi o‘zgartirildi',
                    detail={'product_id': product_id, 'before': '1', 'after': '2', 'reason': 'Other'}))
            db.commit()
        for index in range(23):
            self.seed_sale(self.moment('2026-09-15') + timedelta(minutes=index))
            with self.sessions() as db:
                db.add(Receipt(request_id=str(uuid.uuid4()), branch_id=1, product_id=1,
                               user_id=4, kg=1, price=10000, note='Limit fixture',
                               created_at=self.moment('2026-09-15') + timedelta(minutes=index)))
                db.commit()
        result = self.data(start='2026-09-01', end='2026-09-30')
        self.assertEqual(len(result['recent_sales']), 20)
        self.assertEqual(len(result['recent_receipts']), 20)
        self.assertEqual(len(result['price_history']), 20)
        self.assertEqual(result['price_history'][0]['reason'], 'Price fixture 24')
        self.assertEqual(result['price_history'][-1]['reason'], 'Price fixture 5')
        self.assertTrue(all(row['created_at'].startswith('2020-') for row in result['price_history']))
        self.assertEqual(result['summary']['sales_count'], 23)
        self.assertEqual(result['summary']['receipt_count'], 23)
        enormous = self.data(start='0002-01-01', end='9999-12-30')
        self.assertFalse(enormous['series']['daily_complete'])
        self.assertEqual(len(enormous['daily']), 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class ProductAnalyticsPostgresTest(ProductAnalyticsTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
