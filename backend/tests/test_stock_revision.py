"""Inventory revision only changes the chosen current stock and appends evidence.

All requests use isolated fixture databases; PostgreSQL is the CI marva_ci DB.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import func, select
import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
from app.accounting import balances, supplier_debt
from app.common import row
from app.models import Audit, Product, Stock, StockAdjustment, User
from app.stock_adjustments import STOCK_ADJUSTMENT_ACTION, stock_adjustment_access


class StockRevisionTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel
    receipt = cancellation_fixture.OperationCancelTest.receipt

    def command(self, expected='10', kg='8.125', **changes):
        return dict(request_id=str(uuid.uuid4()), expected_kg=expected, kg=kg,
                    reason='Reviziya: haqiqiy qoldiq qayta tortildi', **changes)

    def change(self, body=None, stock_id=1, client=None):
        return (client or self.owner).post(f'/api/stocks/{stock_id}/adjustments',
                                           json=body or self.command())

    def stock(self, stock_id=1):
        with self.sessions() as db:
            return row(db.get(Stock, stock_id))

    def adjustments(self):
        with self.sessions() as db:
            return [row(a) for a in db.scalars(select(StockAdjustment).order_by(StockAdjustment.id))]

    def permission(self, user_id=4, product_id=1, stock_id=1, branch_id=1):
        with self.sessions() as db:
            return stock_adjustment_access(db, db.get(User, user_id), db.get(Product, product_id),
                                           db.get(Stock, stock_id), branch_id)

    def test_manager_roles_branch_scope_and_sku_stays_programmer_only(self):
        self.assertEqual(self.change(client=self.client()).status_code, 401)
        self.assertEqual(self.change(client=self.client('cashier')).status_code, 403)
        admin = self.client('admin')
        self.assertEqual(self.change(stock_id=2, client=admin).status_code, 403)
        self.assertEqual(self.change(stock_id=99999, client=admin).status_code, 404)
        self.assertEqual(admin.patch('/api/products/1/sku', json={
            'expected_sku': 'TEST-1', 'sku': 'REVISED'}).status_code, 403)
        self.assertEqual(self.change(client=admin).status_code, 200)
        self.assertEqual(self.change(stock_id=2, client=self.client('boss')).status_code, 200)
        self.assertEqual(Decimal(self.stock()['kg']), Decimal('8.125'))
        self.assertEqual(Decimal(self.stock(2)['kg']), Decimal('8.125'))
        self.assertEqual([entry['user_id'] for entry in self.adjustments()], [2, 1])

    def test_current_quantity_only_changes_and_append_only_audit(self):
        admin = self.client('admin')
        self.receipt(kg='2', price='11000')
        sold = self.owner.post('/api/sales', json={**self.sale(), 'expected_total': '11000',
                                                 'cash': '11000'})
        self.assertEqual(sold.status_code, 201, sold.text)
        self.assertEqual(admin.patch('/api/stocks/1/discount', json={'discount': '5'}).status_code, 200)
        excluded = {'stocks', 'stock_adjustments', 'audit_logs', 'stock_valuation_versions'}

        def preserved():
            with self.sessions() as db:
                return ({table.name: sorted(list(db.execute(select(table))), key=repr)
                         for table in Product.metadata.sorted_tables if table.name not in excluded},
                        balances(db, 1), supplier_debt(db, 1, 1))

        before, old_stock, other_stock = preserved(), self.stock(), self.stock(2)
        body = self.command(expected='11', kg='13.001')
        result = self.change(body, client=admin)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(preserved(), before)
        self.assertEqual(self.stock(), dict(old_stock, kg='13.001'))
        self.assertEqual(self.stock(2), other_stock)
        entry = result.json()
        self.assertEqual((entry['before_kg'], entry['kg'], entry['user_id']), ('11.000', '13.001', 2))
        with self.sessions() as db:
            evidence = db.scalar(select(Audit).where(Audit.action == STOCK_ADJUSTMENT_ACTION))
            self.assertEqual((evidence.branch_id, evidence.user_id, evidence.actor), (1, 2, 'admin'))
            self.assertEqual(evidence.detail, {
                'adjustment_id': entry['id'], 'stock_id': 1, 'request_id': body['request_id'],
                'product_id': 1, 'product_name': 'Product', 'sku': 'TEST-1',
                'before': '11.000', 'after': '13.001', 'difference': '2.001', 'reason': body['reason']})

    def test_validation_stale_and_noop_leave_all_state_unchanged(self):
        with self.sessions() as db:
            before = {table.name: sorted(list(db.execute(select(table))), key=repr)
                      for table in Product.metadata.sorted_tables}
        base = self.command()
        for changes in ({'kg': '-1'}, {'kg': '0.0001'}, {'kg': 'NaN'}, {'kg': 'Infinity'},
                        {'kg': '100000000000'}, {'expected_kg': '-1'}, {'reason': '  '},
                        {'reason': 'ab'}, {'reason': 'x' * 501}, {'request_id': 'bad'}, {'force': True}):
            with self.subTest(changes=changes):
                response = self.change(dict(base, **changes))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.change(self.command(kg='10')).status_code, 422)
        self.assertEqual(self.change(self.command(expected='9')).status_code, 409)
        with self.sessions() as db:
            after = {table.name: sorted(list(db.execute(select(table))), key=repr)
                     for table in Product.metadata.sorted_tables}
        self.assertEqual(after, before)

    def test_zero_increase_and_exact_replay_preserve_newer_stock(self):
        body = self.command(kg='0')
        first = self.change(body)
        self.assertEqual(first.status_code, 200, first.text)
        self.receipt(kg='3', price='12000')
        retry = self.change(dict(body, expected_kg='10.000', kg='0.000'))
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.stock()['kg'], '3.000')
        raised = self.change(self.command(expected='3', kg='99999999999.999'))
        self.assertEqual(raised.status_code, 200, raised.text)
        self.assertEqual(self.stock()['kg'], '99999999999.999')
        self.assertEqual(len(self.adjustments()), 2)

    def test_request_payload_actor_stock_conflicts_and_canceled_replay(self):
        body = self.command()
        first = self.change(body)
        self.assertEqual(first.status_code, 200, first.text)
        for changes in ({'kg': '7'}, {'expected_kg': '9'}, {'reason': 'Boshqa sabab'}):
            self.assertEqual(self.change(dict(body, **changes)).status_code, 409)
        self.assertEqual(self.change(body, client=self.client('admin')).status_code, 409)
        self.assertEqual(self.change(body, stock_id=2).status_code, 409)
        self.assertEqual(self.cancel('stock_adjustment', first.json()['id'],
                                    client=self.client('admin')).status_code, 403)
        cancelled = self.cancel('stock_adjustment', first.json()['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.change(body).status_code, 409)
        self.assertEqual(self.stock()['kg'], '10.000')

    def test_read_only_permissions_match_write_guards(self):
        self.assertTrue(self.permission(2)['can_adjust_stock'])
        self.assertTrue(self.permission(1, stock_id=2, branch_id=2)['can_adjust_stock'])
        self.assertFalse(self.permission(2, stock_id=2, branch_id=2)['can_adjust_stock'])
        self.assertFalse(self.permission(3)['can_adjust_stock'])
        result = self.client('admin').get('/api/products/1/analytics?branch_id=1').json()
        self.assertTrue(result['permissions']['can_adjust_stock'])
        self.assertIsNone(result['permissions']['adjustment_disabled_reason'])
        with self.sessions() as db:
            db.add(Product(id=2, name='Empty', sku='EMPTY-2', supplier_id=1))
            db.commit()
            before = {table.name: sorted(list(db.execute(select(table))), key=repr)
                      for table in Product.metadata.sorted_tables}
            permission = stock_adjustment_access(db, db.get(User, 2), db.get(Product, 2), None, 1)
            after = {table.name: sorted(list(db.execute(select(table))), key=repr)
                     for table in Product.metadata.sorted_tables}
        self.assertFalse(permission['can_adjust_stock'])
        self.assertIn('kirim', permission['adjustment_disabled_reason'])
        self.assertEqual(after, before)
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertFalse(self.permission(2)['can_adjust_stock'])
            self.assertEqual(self.change(client=self.client('admin')).status_code, 409)
        self.owner.post('/api/products/1/archive', json={'confirmation': 'TEST-1'})
        self.assertFalse(self.permission(2)['can_adjust_stock'])
        self.assertEqual(self.change(client=self.client('admin')).status_code, 409)
        self.owner.post('/api/products/1/restore', json={'confirmation': 'TEST-1'})
        self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertFalse(self.permission()['can_adjust_stock'])
        self.assertEqual(self.change().status_code, 409)
        self.owner.post('/api/branches/1/restore', json={'confirmation': 'Shared'})
        self.provision()
        self.assertFalse(self.permission(2)['can_adjust_stock'])
        self.assertEqual(self.change(client=self.client('admin')).status_code, 409)

    def test_parallel_identical_requests_apply_once(self):
        other = self.client('boss')
        body = self.command()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.change(body, client=other), range(2)))
        self.assertEqual([result.status_code for result in results], [200, 200])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(len(self.adjustments()), 1)

    def test_parallel_competing_requests_reject_stale_revision(self):
        admin = self.client('admin')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.change, self.command(kg='8'), client=self.owner)
            second = pool.submit(self.change, self.command(kg='7'), client=admin)
            results = (first.result(), second.result())
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        self.assertEqual(len(self.adjustments()), 1)

    def test_parallel_request_id_collision_across_branches_rolls_back_loser(self):
        body = self.command()
        other = self.client('boss')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.change, body, stock_id=1, client=self.owner)
            second = pool.submit(self.change, body, stock_id=2, client=other)
            results = (first.result(), second.result())
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        self.assertEqual(len(self.adjustments()), 1)
        for index, result in enumerate(results, 1):
            self.assertEqual(self.stock(index)['kg'], '8.125' if result.status_code == 200 else '10.000')


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class StockRevisionPostgresTest(StockRevisionTest):
    postgres = True
