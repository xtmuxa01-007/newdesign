"""Arxiv savdo hisoblarini o'zgartirmaydi, parallel yozuv va vakolatlar tekshiriladi."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import unittest
import uuid
import os
from sqlalchemy import select, func, inspect
import test_branch_archive as branch_fixture
from app.models import Product, ProductArchive, Stock, Sale, Audit
from app.online_transition import prepare_online


class ProductArchiveTest(unittest.TestCase):
    setUp = branch_fixture.BranchArchiveTest.setUp
    tearDown = branch_fixture.BranchArchiveTest.tearDown
    client = branch_fixture.BranchArchiveTest.client
    provision = branch_fixture.BranchArchiveTest.provision
    sale = branch_fixture.BranchArchiveTest.sale

    def archive(self, client=None, sku='TEST-1'):
        return (client or self.owner).post('/api/products/1/archive', json={'confirmation': sku})

    def restore(self, client=None):
        return (client or self.owner).post('/api/products/1/restore', json={'confirmation': 'TEST-1'})

    def test_permission_confirmation_schema_and_csrf(self):
        self.assertTrue(self.owner_data['can_archive_products'])
        for role in ('boss', 'admin', 'cashier'):
            client = self.client(role)
            self.assertFalse(client.get('/api/auth/me').json()['can_archive_products'])
            self.assertEqual(self.archive(client).status_code, 403)
            self.assertEqual(self.restore(client).status_code, 403)
        self.assertEqual(self.archive(sku='wrong').status_code, 422)
        self.assertEqual(self.owner.post('/api/products/999/archive', json={'confirmation':'TEST'}).status_code, 404)
        self.assertEqual(self.owner.post('/api/products/1/archive', json={'confirmation':'TEST-1','force':True}).status_code, 422)
        self.assertEqual(self.owner.post('/api/products/1/archive', json={'confirmation':'TEST-1'}, headers={'Origin':'https://untrusted.invalid'}).status_code, 403)
        self.assertNotIn('archived', {c['name'] for c in inspect(self.engine).get_columns('products')})

    def test_history_stock_balances_and_all_branches_are_preserved(self):
        cashier = self.client('cashier')
        sold = cashier.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        receipt = {'request_id':str(uuid.uuid4()),'branch_id':1,'product_id':1,'kg':'2','price':'10000'}
        self.assertEqual(self.owner.post('/api/receipts', json=receipt).status_code, 201)
        dashboard = self.owner.get('/api/dashboard').json()
        with self.sessions() as db:
            before = {t.name: db.scalar(select(func.count()).select_from(t))
                      for t in Product.metadata.sorted_tables if t.name not in ('product_archives','audit_logs')}
        self.assertEqual(self.archive().status_code, 200)
        self.assertEqual(self.archive().status_code, 200)
        self.assertEqual(dashboard, self.owner.get('/api/dashboard').json())
        self.assertEqual(self.owner.get('/api/sales?branch_id=1').json()['items'][0]['id'], sold.json()['id'])
        self.assertEqual(len(self.owner.get('/api/receipts?branch_id=1').json()), 1)
        for branch in (1, 2):
            self.assertEqual(self.owner.get(f'/api/products?branch_id={branch}').json(), [])
            archived = self.owner.get(f'/api/products?branch_id={branch}&include_archived=true').json()[0]
            self.assertTrue(archived['archived'])
            self.assertFalse(archived['active'])
            self.assertEqual(Decimal(archived['kg']), Decimal(11 if branch == 1 else 10))
        self.assertEqual(cashier.get('/api/products?branch_id=1&include_archived=true').json(), [])
        with self.sessions() as db:
            self.assertEqual(before, {t.name: db.scalar(select(func.count()).select_from(t))
                                    for t in Product.metadata.sorted_tables if t.name in before})
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'Mahsulot arxivlandi')), 1)
        self.assertEqual(self.restore().status_code, 200)
        self.assertEqual(self.restore().status_code, 200)
        self.assertEqual(cashier.post('/api/sales', json=self.sale()).status_code, 201)
        self.assertEqual(len(self.owner.get('/api/products?branch_id=2').json()), 1)

    def test_stale_carts_new_writes_and_sale_edits_are_blocked(self):
        cashier = self.client('cashier')
        cart_body = {'branch_id':1,'label':'Saved','items':[{'product_id':1,'kg':'1'}]}
        cart = cashier.post('/api/carts', json=cart_body).json()
        sale = self.owner.post('/api/sales', json=self.sale()).json()
        edit = {'request_id':str(uuid.uuid4()),'version':0,'reason':'Fixture correction','customer':'Test',
                'cash':'10000','card':'0','items':[{'item_id':sale['items'][0]['id'],'product_id':1,'kg':'1','price':'10000','discount':'0'}]}
        self.assertEqual(self.archive().status_code, 200)
        for response in (
            cashier.post('/api/sales', json=self.sale(saved_cart_id=cart['id'], saved_cart_version=cart['version'])),
            cashier.post('/api/carts', json=cart_body),
            cashier.put(f"/api/carts/{cart['id']}", json=dict(cart_body, version=cart['version'])),
            self.owner.post('/api/receipts', json={'request_id':str(uuid.uuid4()),'branch_id':2,'product_id':1,'kg':'1','price':'10000'}),
            self.owner.patch('/api/stocks/1/discount', json={'discount':'2'}),
            self.owner.post('/api/products/1/image', files={'file':('image.png', b'not image', 'image/png')}),
            self.owner.post(f"/api/sales/{sale['id']}/edit", json=edit),
        ):
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(cashier.get('/api/carts?branch_id=1').json()), 1)
        self.assertEqual(cashier.delete(f"/api/carts/{cart['id']}?version={cart['version']}").status_code, 200)
        self.assertEqual(self.restore().status_code, 200)
        self.assertEqual(self.owner.post(f"/api/sales/{sale['id']}/edit", json=edit).status_code, 200)

    def test_lost_financial_acknowledgement_can_replay_after_archive(self):
        body = self.sale()
        sale = self.owner.post('/api/sales', json=body).json()
        receipt = {'request_id':str(uuid.uuid4()),'branch_id':1,'product_id':1,'kg':'1','price':'10000'}
        received = self.owner.post('/api/receipts', json=receipt).json()
        self.archive()
        self.assertEqual(self.owner.post('/api/sales', json=body).json()['id'], sale['id'])
        self.assertEqual(self.owner.post('/api/receipts', json=receipt).json()['id'], received['id'])

    def test_legacy_transition_before_global_archive_and_no_old_registration(self):
        folder, config = self.provision()
        self.assertEqual(self.archive().status_code, 409)
        prepare_online(folder, self.wire)
        self.assertEqual(self.archive().status_code, 200)
        self.assertEqual(self.owner.post('/api/sync/devices', json={'branch_id':2,'name':'Old EXE'}).status_code, 409)

    def test_parallel_archive_sale_and_receipt_keep_consistent_stock(self):
        cashier = self.client('cashier')
        manager = self.client('admin')
        receipt = {'request_id':str(uuid.uuid4()),'branch_id':1,'product_id':1,'kg':'2','price':'10000'}
        with ThreadPoolExecutor(max_workers=3) as pool:
            archived = pool.submit(self.archive)
            sold = pool.submit(cashier.post, '/api/sales', json=self.sale())
            received = pool.submit(manager.post, '/api/receipts', json=receipt)
            self.assertEqual(archived.result().status_code, 200)
            sale_status, receipt_status = sold.result().status_code, received.result().status_code
        self.assertIn(sale_status, (201,409))
        self.assertIn(receipt_status, (201,409))
        with self.sessions() as db:
            self.assertIsNotNone(db.get(ProductArchive, 1))
            self.assertEqual(db.get(Stock, 1).kg, 10 - (sale_status == 201) + 2 * (receipt_status == 201))
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), int(sale_status == 201))


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class ProductArchivePostgresTest(ProductArchiveTest):
    postgres = True
