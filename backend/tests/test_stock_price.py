"""Only disposable fixture databases: current prices never rewrite sales or receipts."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import select, func
import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
from app.accounting import balances, supplier_debt
from app.common import row
from app.models import Audit, Product, Receipt, Sale, SaleItem, Stock, User
from app.stock_prices import PRICE_CHANGE_ACTION, price_edit_access


class StockPriceTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision
    create_sale = cancellation_fixture.OperationCancelTest.create_sale
    receipt = cancellation_fixture.OperationCancelTest.receipt
    payload = cancellation_fixture.OperationCancelTest.payload
    cancel = cancellation_fixture.OperationCancelTest.cancel

    def command(self, expected='10000', price='12000', **changes):
        return dict(request_id=str(uuid.uuid4()), expected_price=expected, price=price,
                    reason='Fixture assigned price correction', **changes)

    def change(self, body=None, stock_id=1, client=None):
        return (client or self.owner).post(f'/api/stocks/{stock_id}/price',
                                           json=body or self.command())

    def stock(self, stock_id=1):
        with self.sessions() as db:
            return row(db.get(Stock, stock_id))

    def price_audits(self):
        with self.sessions() as db:
            return [row(entry) for entry in db.scalars(select(Audit).where(
                Audit.action == PRICE_CHANGE_ACTION).order_by(Audit.id))]

    def access(self, stock_id=1, product_id=1):
        with self.sessions() as db:
            return price_edit_access(db, db.get(User, 4), db.get(Product, product_id),
                                     db.get(Stock, stock_id), 1)

    def test_only_current_price_and_immutable_audit_change(self):
        self.receipt(price='10000')
        sold, _ = self.create_sale(mini_discount='1000', cash='9000')
        self.assertEqual(self.owner.patch('/api/stocks/1/discount', json={'discount': '5'}).status_code, 200)

        def preserved_state():
            with self.sessions() as db:
                return ({table.name: sorted(list(db.execute(select(table))), key=repr)
                         for table in Sale.metadata.sorted_tables
                         if table.name not in (Stock.__tablename__, Audit.__tablename__)},
                        balances(db, 1), supplier_debt(db, 1, 1))

        before = preserved_state()
        stock_before = self.stock()
        with self.sessions() as db:
            audit_count = db.scalar(select(func.count()).select_from(Audit))
        body = self.command()
        result = self.change(body)
        self.assertEqual(result.status_code, 200, result.text)
        stock_after = self.stock()
        self.assertEqual(stock_after, dict(stock_before, price='12000.00'))
        self.assertEqual(preserved_state(), before)
        self.assertEqual(result.json(), {'ok': True, 'stock': stock_after, 'request_id': body['request_id']})
        entries = self.price_audits()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual((entry['branch_id'], entry['user_id']), (1, 4))
        self.assertEqual(entry['detail'], {
            'stock_id': 1, 'product_id': 1, 'product_name': 'Product', 'sku': 'TEST-1',
            'request_id': body['request_id'],
            'before': '10000.00', 'after': '12000.00', 'reason': body['reason'],
            'command': {'stock_id': 1, 'expected_price': '10000.00', 'price': '12000.00',
                        'reason': body['reason']}, 'result': result.json()})
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), audit_count + 1)
            old_item = db.scalar(select(SaleItem).where(SaleItem.sale_id == sold['id']))
            self.assertEqual((old_item.price, old_item.total), (Decimal('10000'), Decimal('9000')))

    def test_roles_branch_scope_and_missing_stock(self):
        body = self.command()
        self.assertEqual(self.change(body, client=self.client()).status_code, 401)
        self.assertEqual(self.change(body, client=self.client('cashier')).status_code, 403)
        admin = self.client('admin')
        self.assertEqual(self.change(body, stock_id=2, client=admin).status_code, 403)
        self.assertEqual(self.change(body, stock_id=99999).status_code, 404)
        self.assertEqual(self.change(body, client=admin).status_code, 200)
        self.assertEqual(self.change(self.command(), stock_id=2).status_code, 200)
        self.assertEqual(len(self.price_audits()), 2)

    def test_validation_noop_and_stale_price_preserve_everything(self):
        self.assertEqual(self.change(self.command(price='10000')).status_code, 422)
        self.assertEqual(self.change(self.command(expected='9999')).status_code, 409)
        base = self.command()
        for change in ({'price': '0'}, {'price': '-1'}, {'price': '1.234'}, {'price': 'NaN'},
                       {'price': 'Infinity'}, {'price': '1000000000000.00'},
                       {'expected_price': '-1'}, {'reason': '  '}, {'reason': 'xx'},
                       {'request_id': 'short'}, {'kg': '10'}):
            with self.subTest(change=change):
                response = self.change(dict(base, **change))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.stock()['price'], '10000.00')
        self.assertEqual(self.price_audits(), [])

    def test_exact_retry_returns_saved_result_without_reverting_newer_price(self):
        body = self.command()
        first = self.change(body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.change(self.command(expected='12000', price='13000'))
        self.assertEqual(second.status_code, 200, second.text)
        retry = self.change(dict(body, expected_price='10000.0', price='12000.00'))
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.stock()['price'], '13000.00')
        for changes in ({'price': '14000'}, {'expected_price': '13000'}, {'reason': 'Different reason'}):
            self.assertEqual(self.change(dict(body, **changes)).status_code, 409)
        self.assertEqual(self.change(body, client=self.client('admin')).status_code, 409)
        with self.sessions() as db:
            db.add(Product(id=2, name='Second', sku='TEST-2', supplier_id=1))
            db.flush()
            db.add(Stock(id=3, branch_id=1, product_id=2, kg=1, price=10000, discount=0))
            db.commit()
        self.assertEqual(self.change(body, stock_id=3).status_code, 409)
        self.assertEqual(len(self.price_audits()), 2)
        # Request IDs are explicitly scoped to a branch; another branch is independent.
        self.assertEqual(self.change(body, stock_id=2).status_code, 200)
        self.assertEqual(self.stock(2)['price'], '12000.00')

    def test_local_and_legacy_guards_with_read_only_access_reasons(self):
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            response = self.change()
            permission = self.access()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(permission['can_edit_price'])
        self.assertIn('umumiy bazaga', permission['price_edit_reason'])
        self.provision()
        self.assertEqual(self.change().status_code, 409)
        permission = self.access()
        self.assertFalse(permission['can_edit_price'])
        self.assertIn('offline', permission['price_edit_reason'])
        self.assertEqual(self.stock()['price'], '10000.00')
        self.assertEqual(self.price_audits(), [])

    def test_archived_branch_and_product_guards(self):
        archived = self.owner.post('/api/products/1/archive', json={'confirmation': 'TEST-1'})
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.change().status_code, 409)
        self.assertFalse(self.access()['can_edit_price'])
        restored = self.owner.post('/api/products/1/restore', json={'confirmation': 'TEST-1'})
        self.assertEqual(restored.status_code, 200, restored.text)
        archived = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.change().status_code, 409)
        self.assertIn('arxivlangan', self.access()['price_edit_reason'])
        self.assertEqual(self.stock()['price'], '10000.00')
        self.assertEqual(self.price_audits(), [])

    def test_missing_stock_access_is_read_only(self):
        with self.sessions() as db:
            db.add(Product(id=2, name='Unstocked', sku='EMPTY-2', supplier_id=1))
            db.commit()
            before = {table.name: sorted(list(db.execute(select(table))), key=repr)
                      for table in Sale.metadata.sorted_tables}
            permission = price_edit_access(db, db.get(User, 4), db.get(Product, 2), None, 1)
            after = {table.name: sorted(list(db.execute(select(table))), key=repr)
                     for table in Sale.metadata.sorted_tables}
        self.assertFalse(permission['can_edit_price'])
        self.assertIn('kirim', permission['price_edit_reason'])
        self.assertEqual(before, after)

    def test_pos_uses_new_price_and_rejects_stale_total_without_rewriting_sale(self):
        old_sale, _ = self.create_sale()
        self.assertEqual(self.change().status_code, 200)
        products = self.owner.get('/api/products?branch_id=1').json()
        self.assertEqual(Decimal(products[0]['price']), 12000)
        stale = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(stale.status_code, 409, stale.text)
        sold = self.owner.post('/api/sales', json={**self.sale(), 'expected_total': '12000', 'cash': '12000'})
        self.assertEqual(sold.status_code, 201, sold.text)
        with self.sessions() as db:
            original = db.scalar(select(SaleItem).where(SaleItem.sale_id == old_sale['id']))
            current = db.scalar(select(SaleItem).where(SaleItem.sale_id == sold.json()['id']))
            self.assertEqual((original.price, original.total), (10000, 10000))
            self.assertEqual((current.price, current.total), (12000, 12000))
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 2)

    def test_identical_parallel_price_requests_apply_once(self):
        body = self.command()
        other = self.client()
        login = other.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: self.change(body, client=client), (self.owner, other)))
        self.assertTrue(all(result.status_code == 200 for result in results))
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(self.stock()['price'], '12000.00')
        self.assertEqual(len(self.price_audits()), 1)

    def test_competing_parallel_price_requests_reject_stale_writer(self):
        admin = self.client('admin')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.change, self.command(price='11000'), client=self.owner)
            second = pool.submit(self.change, self.command(price='12000'), client=admin)
            results = (first.result(), second.result())
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        self.assertIn(self.stock()['price'], ('11000.00', '12000.00'))
        self.assertEqual(len(self.price_audits()), 1)

    def test_receipt_cancellation_preserves_later_explicit_price_and_discount(self):
        receipt, _ = self.receipt(price='11000')
        self.assertEqual(self.owner.patch('/api/stocks/1/discount', json={'discount': '5'}).status_code, 200)
        self.assertEqual(self.change(self.command(expected='11000', price='15000')).status_code, 200)
        cancelled = self.cancel('receipt', receipt['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual((self.stock()['price'], self.stock()['discount'], self.stock()['kg']),
                         ('15000.00', '5.00', '10.000'))

    def test_price_between_receipts_returns_when_later_receipt_is_cancelled(self):
        first, _ = self.receipt(price='11000')
        self.assertEqual(self.change(self.command(expected='11000', price='15000')).status_code, 200)
        second, _ = self.receipt(price='12000')
        self.assertEqual(self.cancel('receipt', second['id']).status_code, 200)
        self.assertEqual(self.stock()['price'], '15000.00')
        self.assertEqual(self.cancel('receipt', first['id']).status_code, 200)
        self.assertEqual(self.stock()['price'], '15000.00')

    def test_newer_surviving_receipt_overrides_old_edit_and_out_of_order_cancel_is_safe(self):
        first, _ = self.receipt(price='11000')
        self.assertEqual(self.change(self.command(expected='11000', price='15000')).status_code, 200)
        second, _ = self.receipt(price='12000')
        third, _ = self.receipt(price='13000')
        self.assertEqual(self.cancel('receipt', third['id']).status_code, 200)
        self.assertEqual(self.stock()['price'], '12000.00')
        self.assertEqual(self.cancel('receipt', first['id']).status_code, 200)
        self.assertEqual(self.stock()['price'], '12000.00')
        self.assertEqual(self.cancel('receipt', second['id']).status_code, 200)
        self.assertEqual(self.stock()['price'], '15000.00')

    def test_rejected_receipt_cancel_keeps_explicit_price_and_all_history(self):
        receipt, _ = self.receipt(price='11000')
        sold = self.owner.post('/api/sales', json={**self.sale(kg='10.5'),
                              'expected_total': '115500', 'cash': '115500'})
        self.assertEqual(sold.status_code, 201, sold.text)
        self.assertEqual(self.change(self.command(expected='11000', price='15000')).status_code, 200)
        before = self.stock(), self.price_audits()
        cancelled = self.cancel('receipt', receipt['id'])
        self.assertEqual(cancelled.status_code, 409, cancelled.text)
        self.assertEqual((self.stock(), self.price_audits()), before)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(Receipt, receipt['id']))


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class StockPricePostgresTest(StockPriceTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
