"""SKU Programmistga, qoldiq tuzatishi managerga; tarix va parallel savdo himoyasi."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from decimal import Decimal
from sqlalchemy import select, func
import test_branch_archive as fixture
from app.models import Product, Stock, StockAdjustment, SaleItem, Audit


class InventoryEditTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision

    def adjustment(self, **changes):
        return dict({'request_id': str(uuid.uuid4()), 'expected_kg': '10',
                     'kg': '7.125', 'reason': 'Inventarizatsiya'}, **changes)

    def sku(self, **changes):
        return dict({'expected_sku': 'TEST-1', 'sku': 'new-001'}, **changes)

    def test_only_owner_can_edit_sku_and_quantity_validation(self):
        self.assertTrue(self.owner_data['can_edit_inventory'])
        for role in ('boss', 'admin', 'cashier'):
            client = self.client(role)
            self.assertFalse(client.get('/api/auth/me').json()['can_edit_inventory'])
            self.assertEqual(client.patch('/api/products/1/sku', json=self.sku()).status_code, 403)
            if role == 'cashier':
                self.assertEqual(client.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 403)
        for quantity in ('-1', '0.0001', 'NaN', 'Infinity', '100000000000'):
            self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment(kg=quantity)).status_code, 422)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment(reason=' ')).status_code, 422)
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku(sku=' ')).status_code, 422)
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment(),
                         headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)

    def test_sku_uniqueness_stale_edit_search_and_sale_history(self):
        sale = self.owner.post('/api/sales', json=self.sale()).json()
        with self.sessions() as db:
            db.add(Product(id=2, name='Other', sku='TAKEN', supplier_id=1))
            db.commit()
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku(sku='taken')).status_code, 409)
        result = self.owner.patch('/api/products/1/sku', json=self.sku())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['sku'], 'NEW-001')
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku()).status_code, 200)
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku(sku='STALE')).status_code, 409)
        for branch in (1, 2):
            self.assertEqual(self.owner.get(f'/api/products?branch_id={branch}&q=new-001').json()[0]['id'], 1)
        edit = {'request_id':str(uuid.uuid4()), 'version':0, 'reason':'Customer correction',
                'customer':'Corrected', 'cash':'10000', 'card':'0',
                'items':[{'item_id':sale['items'][0]['id'], 'product_id':1,
                          'kg':'1', 'price':'10000', 'discount':'0'}]}
        self.assertEqual(self.owner.post(f"/api/sales/{sale['id']}/edit", json=edit).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(SaleItem)).sku, 'TEST-1')
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Mahsulot SKU kodi o‘zgartirildi')), 1)

    def test_adjustment_history_replay_and_no_financial_change(self):
        dashboard = self.owner.get('/api/dashboard').json()
        suppliers = self.owner.get('/api/suppliers?branch_id=1').json()
        body = self.adjustment(kg='0')
        result = self.owner.post('/api/stocks/1/adjustments', json=body)
        self.assertEqual(result.status_code, 200, result.text)
        # Boshqa kirim bo'lgach ham retry yangi qoldiqni ortga qaytarmaydi.
        self.assertEqual(self.owner.post('/api/receipts', json={'request_id':str(uuid.uuid4()),
            'branch_id':1, 'product_id':1, 'kg':'3', 'price':'10000'}).status_code, 201)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=body).json()['id'], result.json()['id'])
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=dict(body, kg='2')).status_code, 409)
        after = self.owner.get('/api/dashboard').json()
        inventory_fields = {'inventory_kg', 'inventory_value', 'active_products', 'branches'}
        self.assertEqual({k:v for k,v in dashboard.items() if k not in inventory_fields},
                         {k:v for k,v in after.items() if k not in inventory_fields})
        self.assertEqual(Decimal(after['inventory_kg']), 13)
        self.assertEqual(suppliers, self.owner.get('/api/suppliers?branch_id=1').json())
        history = self.owner.get('/api/stock-adjustments?branch_id=1').json()
        self.assertEqual(len(history), 1)
        self.assertEqual(Decimal(history[0]['difference']), -10)
        self.assertEqual(history[0]['reason'], body['reason'])
        self.assertEqual(self.owner.get('/api/stock-adjustments?branch_id=2').json(), [])
        self.assertEqual(self.client('admin').get('/api/stock-adjustments?branch_id=2').status_code, 403)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 3)
            self.assertEqual(db.get(Stock, 2).kg, 10)
            self.assertEqual(db.get(Stock, 1).price, 10000)

    def test_archives_and_legacy_guard(self):
        self.owner.post('/api/products/1/archive', json={'confirmation':'TEST-1'})
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku()).status_code, 409)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)
        self.owner.post('/api/products/1/restore', json={'confirmation':'TEST-1'})
        self.owner.post('/api/branches/1/archive', json={'confirmation':'Shared'})
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)
        self.owner.post('/api/branches/1/restore', json={'confirmation':'Shared'})
        self.provision()
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=self.sku()).status_code, 409)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)

    def test_parallel_sale_and_stale_adjustments(self):
        cashier = self.client('cashier')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self.owner.post, '/api/stocks/1/adjustments', json=self.adjustment(kg='5'))
            s = pool.submit(cashier.post, '/api/sales', json=self.sale())
            self.assertEqual(s.result().status_code, 201)
            status = a.result().status_code
        self.assertIn(status, (200, 409))
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 4 if status == 200 else 9)
            self.assertEqual(db.scalar(select(func.count()).select_from(StockAdjustment)), int(status == 200))
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class InventoryEditPostgresTest(InventoryEditTest):
    postgres = True
