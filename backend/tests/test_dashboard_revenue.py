"""Birinchi ekrandagi tushum savdo, qarz va Toshkent davrlariga mos bo‘lsin."""
from datetime import datetime, timedelta
from decimal import Decimal
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select, func
import test_branch_archive as fixture
import test_sales_analytics as analytics_fixture
import test_operation_cancel as cancellation_fixture
from app.models import Sale, Debt, OpeningDebt, OpeningDebtPayment, DebtInstallment, Audit
from app.routes_finance import TZ


class DashboardRevenueTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    moment = analytics_fixture.SalesAnalyticsTest.moment
    seed_sale = analytics_fixture.SalesAnalyticsTest.seed_sale
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel

    def dashboard(self, today='2026-10-02', client=None, branch=None):
        fixed = datetime.fromisoformat(today).replace(hour=12, tzinfo=TZ)
        path = '/api/dashboard' + (f'?branch_id={branch}' if branch is not None else '')
        with patch('app.routes_finance.datetime', wraps=datetime) as clock:
            clock.now.return_value = fixed
            response = (client or self.owner).get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_day_month_receipts_match_analytics_and_do_not_count_unpaid_goods(self):
        self.seed_sale(self.moment('2026-10-02'), total='20000', cash='3000', card='2000', debt='15000')
        self.seed_sale(self.moment('2026-09-29'), total='8000', cash='2000', debt='6000',
                       payment=(self.moment('2026-10-02'), '4000', '2000'))
        self.seed_sale(self.moment('2026-10-01'), total='10000')
        self.seed_sale(self.moment('2026-10-02'), branch=2, total='7000')
        self.seed_sale(self.moment('2026-10-03'), total='9999')
        result = self.dashboard()
        branches = {b['id']: b for b in result['branches']}
        self.assertEqual(result['revenue_date'], '2026-10-02')
        self.assertEqual(Decimal(branches[1]['today_inflow']), 11000)
        self.assertEqual(Decimal(branches[1]['month_inflow']), 21000)
        self.assertEqual(Decimal(branches[1]['today']), 20000)
        self.assertEqual(Decimal(result['today_inflow']), 18000)
        self.assertEqual(Decimal(result['month_inflow']), 28000)
        for start, field in (('2026-10-02', 'today_inflow'), ('2026-10-01', 'month_inflow')):
            analysis = self.owner.get(f'/api/sales/analytics?start={start}&end=2026-10-02').json()
            self.assertEqual(result[field], analysis['summary']['period_inflow'])
            for row in analysis['branches']:
                self.assertEqual(branches[row['id']][field], row['period_inflow'])

    def test_opening_receipts_active_installments_and_cancelled_receipts_are_separate(self):
        self.seed_sale(self.moment('2026-09-25'), total='10000', cash='0', debt='10000')
        moment = self.moment('2026-10-02')
        with self.sessions() as db:
            debt = db.scalar(select(Debt))
            opening = OpeningDebt(request_id=str(uuid.uuid4()), branch_id=1,
                debtor_id=debt.debtor_id, user_id=1, amount=5000,
                due_date=moment.date() + timedelta(days=5), created_at=self.moment('2026-09-25'))
            db.add(opening)
            db.flush()
            db.add(OpeningDebtPayment(request_id=str(uuid.uuid4()), debt_id=opening.id,
                branch_id=1, user_id=1, cash=3000, card=2000, created_at=moment))
            for cash, cancelled in ((2000, False), (500, True)):
                db.add(DebtInstallment(origin='sale', debt_id=debt.id,
                    debt_created_at=debt.created_at, request_id=str(uuid.uuid4()),
                    branch_id=1, user_id=1, cash=cash, card=0, created_at=moment,
                    **({'cancelled_at': moment, 'cancel_request_id': str(uuid.uuid4()),
                        'cancel_user_id': 1, 'cancel_reason': 'Fixture cancellation',
                        'cancel_fingerprint': 'fixture'} if cancelled else {})))
            db.commit()
        result = self.dashboard()
        self.assertEqual(Decimal(result['today_inflow']), 7000)
        self.assertEqual(Decimal(result['month_inflow']), 7000)
        self.assertEqual(Decimal(result['today']), 0)

    def test_tashkent_midnight_and_role_branch_scope(self):
        self.seed_sale(self.moment('2026-10-01', 23), total='1000')
        self.seed_sale(self.moment('2026-10-02', 0), total='2000')
        self.seed_sale(self.moment('2026-10-02', 23), total='3000')
        self.seed_sale(self.moment('2026-10-03', 0), total='4000')
        self.seed_sale(self.moment('2026-10-02', 12), branch=2, total='5000')
        admin = self.client('admin')
        result = self.dashboard(client=admin)
        self.assertEqual([b['id'] for b in result['branches']], [1])
        self.assertEqual(Decimal(result['today_inflow']), 5000)
        self.assertEqual(Decimal(result['month_inflow']), 6000)
        self.assertEqual(admin.get('/api/dashboard?branch_id=2').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/dashboard').status_code, 403)

    def test_empty_results_read_only_and_cancelled_sales_disappear(self):
        with self.sessions() as db:
            audits = db.scalar(select(func.count()).select_from(Audit))
        result = self.dashboard()
        self.assertEqual(result['today_inflow'], '0.00')
        self.assertEqual(result['month_inflow'], '0.00')
        self.assertTrue(all(b['today_inflow'] == '0.00' for b in result['branches']))
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), audits)
        response = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(response.status_code, 201, response.text)
        sale = response.json()
        day = datetime.fromisoformat(sale['created_at']).astimezone(TZ).date().isoformat()
        self.assertEqual(Decimal(self.dashboard(day)['today_inflow']), 10000)
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 200)
        self.assertEqual(Decimal(self.dashboard(day)['today_inflow']), 0)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class DashboardRevenuePostgresTest(DashboardRevenueTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
