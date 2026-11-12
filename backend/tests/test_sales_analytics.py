"""Tahlil vaqt zonasi, pul oqimlari, filial huquqi va joriy tarixni tekshiradi."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select, func
import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
from app.models import BranchExpense, Debt, DebtPayment, Debtor, Product, Sale, SaleItem, Audit
from app.routes_analytics import TZ


class SalesAnalyticsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel

    def moment(self, day, hour=12):
        return datetime.combine(date.fromisoformat(day), datetime.min.time(), TZ).replace(hour=hour).astimezone(timezone.utc)

    def seed_sale(self, created_at, branch=1, total='10000', cash=None, card='0', donation='0',
                  kg='1', debt=None, payment=None, items=None):
        with self.sessions() as db:
            sale = Sale(request_id=str(uuid.uuid4()), branch_id=branch, user_id=1,
                        customer='Analytics fixture', total=Decimal(total),
                        cash=Decimal(cash if cash is not None else total), card=Decimal(card),
                        donation=Decimal(donation), created_at=created_at)
            db.add(sale)
            db.flush()
            for product_id, item_kg, item_total in items or [(1, kg, total)]:
                product = db.get(Product, product_id)
                db.add(SaleItem(sale_id=sale.id, product_id=product_id, supplier_id=product.supplier_id,
                                name=product.name, sku=product.sku, kg=Decimal(item_kg),
                                price=Decimal(item_total) / Decimal(item_kg), discount=0,
                                total=Decimal(item_total)))
            if debt:
                debtor = Debtor(branch_id=branch, first_name='Test', last_name='Debtor',
                                phone1='+998900000001', phone2='+998900000002', address='Fixture')
                db.add(debtor)
                db.flush()
                owed = Debt(branch_id=branch, sale_id=sale.id, debtor_id=debtor.id, amount=Decimal(debt),
                            due_date=created_at.astimezone(TZ).date() + timedelta(days=7), created_at=created_at)
                db.add(owed)
                db.flush()
                if payment:
                    payment_at, payment_cash, payment_card = payment
                    db.add(DebtPayment(request_id=str(uuid.uuid4()), debt_id=owed.id, branch_id=branch,
                                       user_id=1, cash=Decimal(payment_cash), card=Decimal(payment_card),
                                       created_at=payment_at))
            db.commit()
            return sale.id

    def seed_expense(self, created_at, amount='300', branch=1):
        with self.sessions() as db:
            expense = BranchExpense(request_id=str(uuid.uuid4()), branch_id=branch, supplier_id=1,
                                    user_id=1, amount=Decimal(amount), method='cash',
                                    reason='Analytics fixture', created_at=created_at)
            db.add(expense)
            db.commit()
            return expense.id

    def analytics(self, start='2026-09-01', end='2026-09-30', branch=None, client=None):
        path = f'/api/sales/analytics?start={start}&end={end}'
        if branch is not None:
            path += f'&branch_id={branch}'
        response = (client or self.owner).get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_amounts(self, record, **values):
        for key, value in values.items():
            self.assertEqual(Decimal(record[key]), Decimal(str(value)), key)
            self.assertIsInstance(record[key], str, key)

    def test_default_empty_month_has_zero_days_branches_and_no_writes(self):
        with self.sessions() as db:
            before = db.scalar(select(func.count()).select_from(Audit))
        fixed = datetime(2026, 10, 2, 23, 30, tzinfo=TZ)
        with patch('app.routes_analytics.datetime', wraps=datetime) as clock:
            clock.now.return_value = fixed
            response = self.owner.get('/api/sales/analytics')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['filter'], {'branch_id': None, 'start': '2026-10-01', 'end': '2026-10-02'})
        self.assertEqual([day['date'] for day in result['daily']], ['2026-10-01', '2026-10-02'])
        self.assertEqual([month['month'] for month in result['monthly']], ['2026-10'])
        self.assertEqual([branch['id'] for branch in result['branches']], [1, 2])
        self.assertEqual(result['products'], [])
        self.assertEqual(result['summary']['sales_count'], 0)
        for key, value in result['summary'].items():
            if key != 'sales_count':
                self.assertIsInstance(value, str)
                self.assertEqual(Decimal(value), 0)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), before)

    def test_branch_scope_archived_labels_and_manager_permissions(self):
        self.seed_sale(self.moment('2026-09-10'), branch=1)
        self.seed_sale(self.moment('2026-09-10'), branch=2, total='20000', kg='2')
        archived = self.owner.post('/api/branches/2/archive', json={'confirmation': 'Other'})
        self.assertEqual(archived.status_code, 200, archived.text)
        result = self.analytics()
        self.assert_amounts(result['summary'], goods_total=30000, kg=3)
        self.assertTrue(result['branches'][1]['archived'])
        self.assert_amounts(self.analytics(branch=2)['summary'], goods_total=20000)
        own = self.analytics(client=self.client('admin'))
        self.assertEqual(own['filter']['branch_id'], 1)
        self.assertEqual([branch['id'] for branch in own['branches']], [1])
        self.assert_amounts(own['summary'], goods_total=10000)
        self.assertEqual(self.client('admin').get('/api/sales/analytics?branch_id=2').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/sales/analytics').status_code, 403)
        self.assertEqual(self.client().get('/api/sales/analytics').status_code, 401)
        self.assertEqual(self.owner.get('/api/sales/analytics?branch_id=999').status_code, 404)

    def test_tashkent_start_and_inclusive_end_boundaries_exclude_next_day(self):
        beginning = self.moment('2026-03-01', hour=0)
        ending = self.moment('2026-04-01', hour=0)
        self.seed_sale(beginning - timedelta(microseconds=1), total='40000', kg='4')
        self.seed_sale(beginning)
        self.seed_sale(ending - timedelta(microseconds=1), total='20000', kg='2')
        self.seed_sale(ending, total='80000', kg='8')
        self.seed_expense(beginning - timedelta(microseconds=1), amount='1000')
        self.seed_expense(beginning, amount='100')
        self.seed_expense(ending - timedelta(microseconds=1), amount='200')
        self.seed_expense(ending, amount='2000')
        result = self.analytics(start='2026-03-01', end='2026-03-31')
        self.assertEqual(result['summary']['sales_count'], 2)
        self.assert_amounts(result['summary'], goods_total=30000, cash=30000, expenses=300, kg=3)
        self.assertEqual(len(result['daily']), 31)
        self.assert_amounts(result['daily'][0], goods_total=10000, expenses=100)
        self.assert_amounts(result['daily'][-1], goods_total=20000, expenses=200)
        self.assert_amounts(result['daily'][1], goods_total=0, expenses=0)

    def test_multiple_items_do_not_multiply_sale_money_and_months_stay_separate(self):
        with self.sessions() as db:
            db.add(Product(id=2, name='Second product', sku='SKU-2', supplier_id=1))
            db.commit()
        self.seed_sale(self.moment('2026-09-30', hour=23), total='17500', cash='12000', card='5500',
                       items=[(1, '0.250', '2500'), (2, '0.750', '15000')])
        self.seed_sale(self.moment('2026-10-01', hour=0), total='25000', kg='2.5', cash='20000', card='5000')
        result = self.analytics(start='2026-09-30', end='2026-10-01')
        self.assertEqual(result['summary']['sales_count'], 2)
        self.assert_amounts(result['summary'], goods_total=42500, cash=32000, card=10500,
                            received_at_sale=42500, average_sale=21250, kg='3.500')
        self.assertEqual([month['month'] for month in result['monthly']], ['2026-09', '2026-10'])
        self.assert_amounts(result['monthly'][0], goods_total=17500, cash=12000, kg=1)
        self.assert_amounts(result['monthly'][1], goods_total=25000, cash=20000, kg='2.500')
        products = {row['product_id']: row for row in result['products']}
        self.assert_amounts(products[1], kg='2.750', total=27500)
        self.assert_amounts(products[2], kg='0.750', total=15000)
        self.assert_amounts(result['branches'][1], goods_total=0, period_inflow=0)

    def debt_fixture(self):
        self.seed_sale(self.moment('2026-09-21'), cash='9000', card='2000', donation='1000')
        self.seed_sale(self.moment('2026-09-22'), total='20000', kg='2', cash='3000', card='2000',
                       debt='15000', payment=(self.moment('2026-09-30'), '10000', '5000'))
        self.seed_sale(self.moment('2026-09-22'), total='5000', kg='0.5', cash='1000', card='1000', debt='3000')
        self.seed_sale(self.moment('2026-09-10'), total='8000', kg='0.8', cash='2000', debt='6000',
                       payment=(self.moment('2026-09-22'), '4000', '2000'))
        self.seed_expense(self.moment('2026-09-22'))

    def test_payment_period_is_separate_and_outstanding_uses_current_debt_state(self):
        self.debt_fixture()
        result = self.analytics(start='2026-09-21', end='2026-09-22')
        self.assertEqual(result['summary']['sales_count'], 3)
        self.assert_amounts(result['summary'], goods_total=35000, cash=13000, card=5000,
                            received_at_sale=18000, donation=1000, debt_created=18000,
                            debt_outstanding=3000, debt_collected=6000, period_inflow=24000,
                            average_sale='11666.67', expenses=300, kg='3.500')
        self.assert_amounts(result['daily'][0], received_at_sale=11000, debt_collected=0, period_inflow=11000)
        self.assert_amounts(result['daily'][1], received_at_sale=7000, debt_collected=6000, period_inflow=13000)
        self.assert_amounts(result['products'][0], total=35000, kg='3.500')
        self.assertEqual(result['summary'], {key: value for key, value in result['monthly'][0].items() if key != 'month'})

    def test_debt_collection_is_reported_even_without_sales_in_period(self):
        self.debt_fixture()
        result = self.analytics(start='2026-09-30', end='2026-09-30')
        self.assertEqual(result['summary']['sales_count'], 0)
        self.assert_amounts(result['summary'], goods_total=0, received_at_sale=0, donation=0,
                            debt_created=0, debt_outstanding=0, debt_collected=15000,
                            period_inflow=15000, average_sale=0, kg=0)
        self.assertEqual(result['products'], [])

    def test_cancelled_sales_and_expenses_are_excluded_but_audit_is_preserved(self):
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        sale = sold.json()
        day = datetime.fromisoformat(sale['created_at']).astimezone(TZ).date().isoformat()
        expense = self.owner.post('/api/expenses', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1, 'supplier_id': 1,
            'amount': '1000', 'method': 'cash', 'reason': 'Analytics cancellation fixture'})
        self.assertEqual(expense.status_code, 201, expense.text)
        before = self.analytics(start=day, end=day)
        self.assert_amounts(before['summary'], goods_total=10000, expenses=1000)
        cancelled = self.cancel('expense', expense.json()['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assert_amounts(self.analytics(start=day, end=day)['summary'], goods_total=10000, expenses=0)
        cancelled = self.cancel('sale', sale['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        after = self.analytics(start=day, end=day)
        self.assertEqual(after['summary']['sales_count'], 0)
        self.assert_amounts(after['summary'], goods_total=0, period_inflow=0, expenses=0, kg=0)
        self.assertEqual(after['products'], [])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Amal bekor qilindi')), 2)

    def test_sale_correction_uses_current_values_with_original_sale_date(self):
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        sale = sold.json()
        day = datetime.fromisoformat(sale['created_at']).astimezone(TZ).date().isoformat()
        edited = self.owner.post(f"/api/sales/{sale['id']}/edit", json={
            'request_id': str(uuid.uuid4()), 'version': 0, 'reason': 'Analytics correction fixture',
            'customer': sale['customer'], 'cash': '5500', 'card': '0',
            'items': [{'item_id': sale['items'][0]['id'], 'product_id': 1,
                       'kg': '0.5', 'price': '10000', 'discount': '0'}]})
        self.assertEqual(edited.status_code, 200, edited.text)
        result = self.analytics(start=day, end=day)
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assert_amounts(result['summary'], goods_total=5000, received_at_sale=5500,
                            donation=500, average_sale=5000, kg='0.500')
        self.assert_amounts(result['products'][0], total=5000, kg='0.500')

    def test_cancelled_debt_payment_reopens_outstanding_without_changing_goods_sale(self):
        debtor = self.owner.post('/api/debtors', json={
            'branch_id': 1, 'first_name': 'Test', 'last_name': 'Debtor',
            'phone1': '+998900000001', 'phone2': '+998900000002', 'address': 'Fixture'})
        self.assertEqual(debtor.status_code, 201, debtor.text)
        sold = self.owner.post('/api/sales', json={
            **self.sale(), 'cash': '2000', 'debtor_id': debtor.json()['id'],
            'due_date': (datetime.now(TZ).date() + timedelta(days=2)).isoformat()})
        self.assertEqual(sold.status_code, 201, sold.text)
        sale = sold.json()
        day = datetime.fromisoformat(sale['created_at']).astimezone(TZ).date().isoformat()
        paid = self.owner.post(f"/api/debts/{sale['debt']['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '5000', 'card': '3000'})
        self.assertEqual(paid.status_code, 201, paid.text)
        before = self.analytics(start=day, end=day)
        self.assert_amounts(before['summary'], goods_total=10000, received_at_sale=2000,
                            debt_created=8000, debt_outstanding=0, debt_collected=8000, period_inflow=10000)
        cancelled = self.cancel('debt_payment', paid.json()['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        after = self.analytics(start=day, end=day)
        self.assertEqual(after['summary']['sales_count'], 1)
        self.assert_amounts(after['summary'], goods_total=10000, received_at_sale=2000,
                            debt_created=8000, debt_outstanding=8000, debt_collected=0, period_inflow=2000)

    def test_dates_are_validated_and_long_ranges_are_not_business_limited(self):
        self.seed_sale(self.moment('2026-09-10'))
        for query in ('start=2026-09-02&end=2026-09-01', 'start=not-a-date',
                      'start=2026-01-01&end=9999-12-31', 'start=0001-01-01&end=2026-09-30'):
            response = self.owner.get('/api/sales/analytics?' + query)
            self.assertEqual(response.status_code, 422, response.text)
        long = self.analytics(start='1990-01-01', end='2050-01-01')
        self.assertEqual(long['summary']['sales_count'], 1)
        self.assertFalse(long['series']['daily_complete'])
        self.assertEqual(len(long['daily']), 1)
        self.assertTrue(long['series']['monthly_complete'])
        enormous = self.analytics(start='0002-01-01', end='9999-12-30')
        self.assertEqual(enormous['summary']['sales_count'], 1)
        self.assertFalse(enormous['series']['monthly_complete'])
        self.assertEqual(len(enormous['monthly']), 1)

    def test_historical_tashkent_timezone_agrees_with_utc_boundaries(self):
        beginning = self.moment('1900-03-01', hour=0)
        self.seed_sale(beginning)
        self.seed_sale(beginning - timedelta(microseconds=1), total='20000', kg='2')
        result = self.analytics(start='1900-03-01', end='1900-03-01')
        self.assertEqual(result['summary']['sales_count'], 1)
        self.assertEqual(result['daily'][0]['date'], '1900-03-01')
        self.assert_amounts(result['summary'], goods_total=10000)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class SalesAnalyticsPostgresTest(SalesAnalyticsTest):
    postgres = True
