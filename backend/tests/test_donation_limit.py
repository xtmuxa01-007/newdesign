"""Ehson chegarasi savdo, tuzatish va eski EXE importida ham bajariladi."""
from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
import uuid

from sqlalchemy import select, func
import test_branch_archive as fixture
from app.models import (Sale, SaleItem, SaleEdit, Stock, DonationPayment,
                        SupplierPayment, Audit, OperationCancellation)
from app.routes_sync import SyncDevice, InboxEvent


class DonationLimitTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision

    def count(self, db, model):
        return db.scalar(select(func.count()).select_from(model))

    def create_sale(self, donation='0'):
        body = self.sale()
        body['cash'] = str(Decimal('10000') + Decimal(donation))
        result = self.owner.post('/api/sales', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json(), body

    def edit(self, sale, donation='0'):
        return {'request_id': str(uuid.uuid4()), 'version': sale['edit_version'],
                'reason': 'Ehson summasini tekshirish', 'customer': sale['customer'],
                'cash': str(Decimal('10000') + Decimal(donation)), 'card': '0',
                'items': [{'item_id': sale['items'][0]['id'], 'product_id': 1,
                           'kg': '1', 'price': '10000', 'discount': '0'}]}

    def assert_unchanged(self, sales=0, kg=10, edits=0, payments=0):
        with self.sessions() as db:
            self.assertEqual(self.count(db, Sale), sales)
            self.assertEqual(self.count(db, SaleEdit), edits)
            self.assertEqual(self.count(db, DonationPayment), payments)
            self.assertEqual(db.get(Stock, 1).kg, kg)

    def test_checkout_combined_cash_card_and_exact_limit_replay(self):
        body = self.sale()
        body.update(cash='15000', card='10000.01')
        bad = self.owner.post('/api/sales', json=body)
        self.assertEqual(bad.status_code, 422, bad.text)
        self.assertIn('15 000', bad.json()['detail'])
        self.assert_unchanged()
        body['card'] = '10000'
        accepted = self.owner.post('/api/sales', json=body)
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertEqual(Decimal(accepted.json()['donation']), 15000)
        self.assertEqual(self.owner.post('/api/sales', json=body).json()['id'], accepted.json()['id'])
        self.assert_unchanged(sales=1, kg=9)

    def test_huge_typo_does_not_create_sale_or_reduce_stock(self):
        body = self.sale()
        body['cash'] = '400010000'
        response = self.client('cashier').post('/api/sales', json=body)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_unchanged()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Savdo yakunlandi')), 0)

    def test_sale_edit_rejects_excess_preserves_history_and_accepts_boundary(self):
        sale, _ = self.create_sale()
        body = self.edit(sale, '15000.01')
        result = self.owner.post(f"/api/sales/{sale['id']}/edit", json=body)
        self.assertEqual(result.status_code, 422, result.text)
        self.assert_unchanged(sales=1, kg=9)
        with self.sessions() as db:
            self.assertEqual(db.get(Sale, sale['id']).donation, 0)
            self.assertEqual(db.get(Sale, sale['id']).cash, 10000)
        body['cash'] = '25000'
        result = self.owner.post(f"/api/sales/{sale['id']}/edit", json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(Decimal(result.json()['donation']), 15000)
        self.assertEqual(self.owner.post(f"/api/sales/{sale['id']}/edit", json=body).json()['edit_version'], 1)
        self.assert_unchanged(sales=1, kg=9, edits=1)

    def test_legacy_wrong_donation_can_be_corrected_down(self):
        sale, _ = self.create_sale()
        with self.sessions() as db:
            old = db.get(Sale, sale['id'])
            old.cash, old.donation = Decimal('400010000'), Decimal('400000000')
            db.commit()
        result = self.owner.post(f"/api/sales/{sale['id']}/edit", json=self.edit(sale))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(Decimal(result.json()['donation']), 0)
        with self.sessions() as db:
            self.assertEqual(Decimal(db.scalar(select(SaleEdit)).before['donation']), 400000000)

    def test_donation_payment_cap_does_not_limit_supplier_payments(self):
        self.create_sale('15000')
        self.create_sale('15000')
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1, 'amount': '15000.01',
                'method': 'cash', 'recipient': 'Test recipient', 'note': 'Ehson testi'}
        result = self.owner.post('/api/donations/payments', json=body)
        self.assertEqual(result.status_code, 422, result.text)
        self.assert_unchanged(sales=2, kg=8)
        body['amount'] = '15000'
        result = self.owner.post('/api/donations/payments', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(self.owner.post('/api/donations/payments', json=body).json()['id'], result.json()['id'])
        self.assert_unchanged(sales=2, kg=8, payments=1)
        supplier = self.owner.post('/api/suppliers/1/payments', json={**body,
            'request_id': str(uuid.uuid4()), 'amount': '20000'})
        self.assertEqual(supplier.status_code, 201, supplier.text)
        with self.sessions() as db:
            self.assertEqual(self.count(db, SupplierPayment), 1)

    def push(self, config, changes, event_id=None, sequence=1):
        return self.server.post('/api/sync/push',
            headers={'Authorization': 'Bearer ' + config['token']},
            json={'branch_id': 1, 'events': [{'event_id': event_id or str(uuid.uuid4()),
                'sequence': sequence, 'payload': {'version': 4, 'changes': changes}}]})

    def sync_sale(self, donation):
        moment = datetime.now(timezone.utc).isoformat()
        return [
            {'table': 'sales', 'operation': 'insert', 'row': {
                'id': 101, 'request_id': str(uuid.uuid4()), 'branch_id': 1, 'user_id': 1,
                'customer': 'Sync fixture', 'total': '10000',
                'cash': str(Decimal('10000') + Decimal(donation)), 'card': '0',
                'donation': donation, 'created_at': moment}},
            {'table': 'sale_items', 'operation': 'insert', 'row': {
                'id': 201, 'sale_id': 101, 'product_id': 1, 'supplier_id': 1,
                'name': 'Product', 'sku': 'TEST-1', 'kg': '1', 'price': '10000',
                'discount': '0', 'total': '10000'}},
            {'table': 'stocks', 'operation': 'update', 'row': {
                'id': 1, 'branch_id': 1, 'product_id': 1, 'kg': '9',
                'price': '10000', 'discount': '0'}},
        ]

    def test_sync_sale_rejects_excess_and_boundary_can_replay(self):
        _, config = self.provision()
        changes = self.sync_sale('15000.01')
        result = self.push(config, changes)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn('15 000', result.json()['detail'])
        self.assert_unchanged()
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 0)
            self.assertEqual(db.get(SyncDevice, config['device_id']).received_sequence, 0)
        changes = self.sync_sale('15000')
        event_id = str(uuid.uuid4())
        result = self.push(config, changes, event_id)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.push(config, changes, event_id).status_code, 200)
        self.assert_unchanged(sales=1, kg=9)

    def test_sync_donation_payment_rejects_excess_and_accepts_boundary(self):
        self.create_sale('15000')
        self.create_sale('15000')
        _, config = self.provision()
        changes = [{'table': 'donation_payments', 'operation': 'insert', 'row': {
            'id': 301, 'request_id': str(uuid.uuid4()), 'branch_id': 1, 'user_id': 1,
            'amount': '15000.01', 'method': 'cash', 'recipient': 'Sync recipient',
            'note': '', 'created_at': datetime.now(timezone.utc).isoformat()}}]
        result = self.push(config, changes)
        self.assertEqual(result.status_code, 409, result.text)
        self.assert_unchanged(sales=2, kg=8)
        changes[0]['row']['amount'] = '15000'
        result = self.push(config, changes)
        self.assertEqual(result.status_code, 200, result.text)
        self.assert_unchanged(sales=2, kg=8, payments=1)

    def test_cancelled_sync_request_cannot_be_reinserted_but_applied_ack_remains(self):
        _, config = self.provision()
        changes = self.sync_sale('15000')
        event_id = str(uuid.uuid4())
        result = self.push(config, changes, event_id)
        self.assertEqual(result.status_code, 200, result.text)
        # Simulate a centrally cancelled source: immutable tombstone and
        # original applied inbox remain, while current financial rows are gone.
        with self.sessions() as db:
            source = db.scalar(select(Sale))
            db.add(OperationCancellation(kind='sale', operation_id=source.id,
                original_request_id=source.request_id, request_id=str(uuid.uuid4()),
                branch_id=1, user_id=4, actor='Programmist', reason='Sync replay fixture',
                snapshot={'record': {'donation': '15000'}}))
            for item in db.scalars(select(SaleItem).where(SaleItem.sale_id == source.id)):
                db.delete(item)
            db.flush()
            db.delete(source)
            db.get(Stock, 1).kg = Decimal('10')
            db.commit()
        # The exact already-applied transport retry is only acknowledged.
        result = self.push(config, changes, event_id)
        self.assertEqual(result.status_code, 200, result.text)
        self.assert_unchanged()
        # A fresh inbox event cannot turn the same cancelled source request
        # into a new sale, even when the old central sale no longer exists.
        result = self.push(config, changes, sequence=2)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn('bekor qilingan', result.json()['detail'])
        self.assert_unchanged()
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 1)
            self.assertEqual(db.get(SyncDevice, config['device_id']).received_sequence, 1)

    def test_sync_sale_edit_cannot_bypass_cap_with_command(self):
        sale, _ = self.create_sale()
        _, config = self.provision()
        changes = [{'table': 'sale_edits', 'operation': 'insert', 'row': {
            'id': 301, 'request_id': str(uuid.uuid4()), 'sale_id': sale['id'],
            'branch_id': 1, 'user_id': 1, 'version': 1, 'reason': 'Sync correction',
            'command': self.edit(sale, '15000.01'), 'before': {}, 'after': {},
            'created_at': datetime.now(timezone.utc).isoformat()}}]
        result = self.push(config, changes)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('15 000', result.json()['detail'])
        self.assert_unchanged(sales=1, kg=9)
        with self.sessions() as db:
            self.assertEqual(self.count(db, InboxEvent), 0)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class DonationLimitPostgresTest(DonationLimitTest):
    postgres = True
