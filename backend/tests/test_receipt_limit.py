"""Kirim chegarasi, atomarlik va oldin yozilgan amallarning xavfsiz retrylari."""
from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select, func
import test_branch_archive as fixture
from app.models import Receipt, Product, Stock, Audit
from app.routes_sync import SyncDevice, InboxEvent
from app.sync_projection import SyncIdentity


class ReceiptLimitTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision

    def receipt(self, kg='200', **changes):
        return dict({'request_id': str(uuid.uuid4()), 'branch_id': 1,
                     'product_id': 1, 'kg': kg, 'price': '12000', 'note': ''}, **changes)

    def count(self, db, model):
        return db.scalar(select(func.count()).select_from(model))

    def assert_stock(self, kg=10, price=10000, receipts=0):
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, Decimal(kg))
            self.assertEqual(db.get(Stock, 1).price, Decimal(price))
            self.assertEqual(self.count(db, Receipt), receipts)
            self.assertEqual(db.get(Stock, 2).kg, 10)

    def test_boundary_replay_and_separate_receipts_can_exceed_200_in_total(self):
        first = self.receipt()
        accepted = self.owner.post('/api/receipts', json=first)
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertEqual(Decimal(accepted.json()['kg']), 200)
        self.assertEqual(self.owner.post('/api/receipts', json=first).json()['id'], accepted.json()['id'])
        second = self.owner.post('/api/receipts', json=self.receipt('200.000'))
        self.assertEqual(second.status_code, 201, second.text)
        self.assert_stock(kg=410, price=12000, receipts=2)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Omborga kirim')), 2)

    def test_over_limit_rolls_back_stock_price_and_history(self):
        for quantity in ('200.001', '201', '10000'):
            with self.subTest(quantity=quantity):
                response = self.client('admin').post('/api/receipts', json=self.receipt(quantity))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('200 kg', response.json()['detail'])
                self.assert_stock()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Omborga kirim')), 0)

    def test_over_limit_does_not_create_first_stock_row(self):
        with self.sessions() as db:
            db.add(Product(id=2, name='New product', sku='NEW', supplier_id=1))
            db.commit()
        result = self.owner.post('/api/receipts', json=self.receipt('200.001', product_id=2))
        self.assertEqual(result.status_code, 422, result.text)
        with self.sessions() as db:
            self.assertIsNone(db.scalar(select(Stock).where(Stock.product_id == 2)))
        self.assert_stock()

    def test_already_committed_legacy_receipt_replay_remains_idempotent(self):
        body = self.receipt('250')
        # A real record created before the new cap, without invoking today's route.
        with self.sessions() as db:
            original = Receipt(**{**body, 'kg': Decimal('250'), 'price': Decimal('12000')}, user_id=4)
            db.add(original)
            db.get(Stock, 1).kg = 260
            db.get(Stock, 1).price = 12000
            db.commit()
            receipt_id = original.id
        replay = self.owner.post('/api/receipts', json=body)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()['id'], receipt_id)
        changed = self.owner.post('/api/receipts', json={**body, 'kg': '251'})
        self.assertEqual(changed.status_code, 409, changed.text)
        new = self.owner.post('/api/receipts', json={**body, 'request_id': str(uuid.uuid4())})
        self.assertEqual(new.status_code, 422, new.text)
        self.assert_stock(kg=260, price=12000, receipts=1)

    def test_stock_adjustments_and_sales_are_not_receipt_limited(self):
        result = self.owner.post('/api/stocks/1/adjustments', json={
            'request_id': str(uuid.uuid4()), 'expected_kg': '10',
            'kg': '500', 'reason': 'Old aggregate inventory correction'})
        self.assertEqual(result.status_code, 200, result.text)
        sold = self.owner.post('/api/sales', json=self.sale('250'))
        self.assertEqual(sold.status_code, 201, sold.text)
        sale = sold.json()
        edited = self.owner.post(f"/api/sales/{sale['id']}/edit", json={
            'request_id': str(uuid.uuid4()), 'version': 0, 'reason': 'Sale quantity correction',
            'customer': sale['customer'], 'cash': '2510000', 'card': '0',
            'items': [{'item_id': sale['items'][0]['id'], 'product_id': 1,
                       'kg': '251', 'price': '10000', 'discount': '0'}]})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assert_stock(kg=249)

    def push(self, config, changes, event_id=None, sequence=1):
        return self.server.post('/api/sync/push',
            headers={'Authorization': 'Bearer ' + config['token']},
            json={'branch_id': 1, 'events': [{'event_id': event_id or str(uuid.uuid4()),
                'sequence': sequence, 'payload': {'version': 4, 'changes': changes}}]})

    def sync_receipt(self, kg='200'):
        # Send stock first to ensure a later rejected receipt rolls back flushed rows.
        return [
            {'table': 'stocks', 'operation': 'update', 'row': {
                'id': 1, 'branch_id': 1, 'product_id': 1,
                'kg': str(Decimal('10') + Decimal(kg)), 'price': '12000', 'discount': '0'}},
            {'table': 'receipts', 'operation': 'insert', 'row': {
                'id': 301, 'request_id': str(uuid.uuid4()), 'branch_id': 1, 'user_id': 1,
                'product_id': 1, 'kg': kg, 'price': '12000', 'note': '',
                'created_at': datetime.now(timezone.utc).isoformat()}},
        ]

    def test_new_legacy_import_over_limit_rolls_back_inbox_and_identity(self):
        _, config = self.provision()
        with self.sessions() as db:
            identity_count = self.count(db, SyncIdentity)
        result = self.push(config, self.sync_receipt('200.001'))
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn('200 kg', result.json()['detail'])
        self.assert_stock()
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 0)
            self.assertEqual(self.count(db, SyncIdentity), identity_count)
            self.assertEqual(db.get(SyncDevice, config['device_id']).received_sequence, 0)

    def test_legacy_import_boundary_and_exact_ack_retry(self):
        _, config = self.provision()
        changes = self.sync_receipt('200.000')
        event_id = str(uuid.uuid4())
        accepted = self.push(config, changes, event_id)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(self.push(config, changes, event_id).status_code, 200)
        self.assert_stock(kg=210, price=12000, receipts=1)
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 1)
            self.assertEqual(db.get(SyncDevice, config['device_id']).received_sequence, 1)

    def test_already_applied_over_limit_legacy_event_is_acknowledged(self):
        _, config = self.provision()
        changes = self.sync_receipt('250')
        event_id = str(uuid.uuid4())
        # Seed an event applied by the old server; today's exact transport retry
        # should acknowledge it without re-applying stock or rejecting the new cap.
        with patch('app.sync_projection.require_receipt_limit'):
            accepted = self.push(config, changes, event_id)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        replay = self.push(config, changes, event_id)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assert_stock(kg=260, price=12000, receipts=1)
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 1)
            self.assertEqual(db.get(SyncDevice, config['device_id']).received_sequence, 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class ReceiptLimitPostgresTest(ReceiptLimitTest):
    postgres = True
