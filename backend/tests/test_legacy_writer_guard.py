"""Retired devices cannot block central edits or replay old queued business data.

Every database is a disposable fixture; opt-in PostgreSQL runs only in marva_ci.
"""
import hashlib
from datetime import datetime, timezone
import json
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select
import test_branch_archive as fixture
from app.models import Sale, Stock
from app.routes_sync import InboxEvent, SyncDevice
from app.security import token_hash
from app.shared_mode import LEGACY_WRITER_REASON, SharedBranch, has_legacy_writer


class LegacyWriterGuardTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale

    def device(self, branch=1, active=False, pending_inbox=False):
        device_id, token = str(uuid.uuid4()), uuid.uuid4().hex + uuid.uuid4().hex
        payload = {'version': 3, 'tables': {}}
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        event = {'event_id': str(uuid.uuid4()), 'sequence': 1, 'payload': payload}
        with self.sessions() as db:
            db.add(SyncDevice(id=device_id, branch_id=branch, name='Retired fixture',
                              token_digest=token_hash(token), active=active,
                              received_sequence=1 if pending_inbox else 0))
            db.flush()
            if pending_inbox:
                db.add(InboxEvent(device_id=device_id, event_id=event['event_id'], sequence=1,
                                  payload=payload, payload_digest=digest,
                                  received_at=datetime.now(timezone.utc), applied_at=None))
            db.commit()
        return device_id, {'Authorization': 'Bearer ' + token}, event, token

    def snapshot(self, except_tables=()):
        with self.sessions() as db:
            return {table.name: sorted(list(db.execute(select(table))), key=repr)
                    for table in Sale.metadata.sorted_tables if table.name not in except_tables}

    def permissions(self, client):
        response = client.get('/api/products/1/analytics?branch_id=1')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['permissions']

    def adjustment(self):
        return {'request_id': str(uuid.uuid4()), 'expected_kg': '10', 'kg': '8.125',
                'reason': 'Reviziyada haqiqiy qoldiq tekshirildi'}

    def price_change(self):
        return {'request_id': str(uuid.uuid4()), 'expected_price': '10000', 'price': '12000',
                'reason': 'Joriy narx qayta tekshirildi'}

    def assert_edit_permissions(self, permission, enabled):
        self.assertEqual(permission['can_adjust_stock'], enabled)
        self.assertEqual(permission['can_edit_price'], enabled)
        if enabled:
            self.assertIsNone(permission['adjustment_disabled_reason'])
            self.assertIsNone(permission['price_edit_reason'])
        else:
            self.assertEqual(permission['adjustment_disabled_reason'], LEGACY_WRITER_REASON)
            self.assertEqual(permission['price_edit_reason'], LEGACY_WRITER_REASON)

    def test_retired_registration_allows_admin_edits_without_changing_legacy_records(self):
        self.device(pending_inbox=True)
        admin = self.client('admin')
        before_read = self.snapshot()
        self.assert_edit_permissions(self.permissions(admin), True)
        self.assertEqual(self.snapshot(), before_read)
        preserved = self.snapshot({'stocks', 'stock_adjustments', 'audit_logs'})
        response = admin.post('/api/stocks/1/adjustments', json=self.adjustment())
        self.assertEqual(response.status_code, 200, response.text)
        response = admin.post('/api/stocks/1/price', json=self.price_change())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot({'stocks', 'stock_adjustments', 'audit_logs'}), preserved)
        with self.sessions() as db:
            self.assertEqual(str(db.get(Stock, 1).kg), '8.125')
            self.assertEqual(str(db.get(Stock, 1).price), '12000.00')
            self.assertEqual(str(db.get(Stock, 2).kg), '10.000')
            self.assertIsNone(db.get(SharedBranch, 1))
        events = self.owner.get('/api/notifications/changes').json()['items']
        revision = next(entry for entry in events if entry['kind'] == 'stock_adjustment')
        self.assertEqual(revision['actor'], 'admin')
        self.assertEqual(revision['stock']['before'], '10.000')
        self.assertEqual(revision['stock']['after'], '8.125')
        self.assertEqual(revision['stock']['difference'], '-1.875')
        self.assertEqual(revision['reason'], 'Reviziyada haqiqiy qoldiq tekshirildi')

    def test_active_untransitioned_device_still_blocks_ui_and_all_writes(self):
        self.device(active=True)
        admin = self.client('admin')
        before = self.snapshot()
        self.assert_edit_permissions(self.permissions(admin), False)
        for path, body in (('/api/stocks/1/adjustments', self.adjustment()),
                           ('/api/stocks/1/price', self.price_change()),
                           ('/api/sales', self.sale())):
            response = admin.post(path, json=body)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['detail'], LEGACY_WRITER_REASON)
        self.assertEqual(self.snapshot(), before)

    def test_shared_active_device_allows_central_edits_but_rejects_legacy_push(self):
        device_id, headers, event, _ = self.device(active=True)
        with self.sessions() as db:
            db.add(SharedBranch(branch_id=1, device_id=device_id, received_sequence=0, last_digest=None))
            db.commit()
        admin = self.client('admin')
        self.assert_edit_permissions(self.permissions(admin), True)
        response = admin.post('/api/stocks/1/adjustments', json=self.adjustment())
        self.assertEqual(response.status_code, 200, response.text)
        before_push = self.snapshot()
        with patch('app.routes_sync.apply_bundle', side_effect=AssertionError('Legacy push must not apply')) as apply:
            response = self.server.post('/api/sync/push', headers=headers,
                                        json={'branch_id': 1, 'events': [event]})
        self.assertEqual(response.status_code, 409, response.text)
        apply.assert_not_called()
        self.assertEqual(self.snapshot(), before_push)

    def test_inactive_token_cannot_apply_unapplied_inbox_or_activate_shared(self):
        _, headers, event, _ = self.device(pending_inbox=True)
        admin = self.client('admin')
        self.assertEqual(admin.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 200)
        before = self.snapshot()
        with patch('app.routes_sync.apply_bundle', side_effect=AssertionError('Revoked token must not apply')) as apply:
            response = self.server.post('/api/sync/push', headers=headers,
                                        json={'branch_id': 1, 'events': [event]})
        self.assertEqual(response.status_code, 401, response.text)
        apply.assert_not_called()
        self.assertEqual(self.server.get('/api/sync/device', headers=headers).status_code, 401)
        self.assertEqual(self.server.get('/api/sync/bootstrap', headers=headers).status_code, 401)
        self.assertEqual(self.server.post('/api/sync/activate-shared', headers=headers,
                                         json={'received_sequence': 1, 'last_digest': None}).status_code, 401)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_registration_cannot_be_reenabled_or_replaced(self):
        device_id, _, _, token = self.device()
        before = self.snapshot()
        for data in ({'branch_id': 1, 'name': 'Retry old device', 'device_id': device_id, 'token': token},
                     {'branch_id': 1, 'name': 'Replacement device', 'device_id': str(uuid.uuid4()),
                      'token': uuid.uuid4().hex + uuid.uuid4().hex}):
            response = self.owner.post('/api/sync/devices', json=data)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_branch_and_global_catalog_guards_only_consider_active_unshared_devices(self):
        self.device(branch=1, active=False)
        active_id, _, _, _ = self.device(branch=2, active=True)
        with self.sessions() as db:
            self.assertFalse(has_legacy_writer(db, 1))
            self.assertTrue(has_legacy_writer(db, 2))
            self.assertTrue(has_legacy_writer(db))
        admin = self.client('admin')
        self.assert_edit_permissions(self.permissions(admin), True)
        change_sku = {'expected_sku': 'TEST-1', 'sku': 'RETIRED-SAFE'}
        before = self.snapshot()
        self.assertEqual(self.owner.patch('/api/products/1/sku', json=change_sku).status_code, 409)
        self.assertEqual(self.snapshot(), before)
        with self.sessions() as db:
            db.get(SyncDevice, active_id).active = False
            db.commit()
            self.assertFalse(has_legacy_writer(db))
        response = self.owner.patch('/api/products/1/sku', json=change_sku)
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertIsNone(db.get(SharedBranch, 1))
            self.assertIsNone(db.get(SharedBranch, 2))
            self.assertFalse(db.get(SyncDevice, active_id).active)

    def test_device_reactivated_after_form_opens_blocks_stale_submit_atomically(self):
        device_id, _, _, _ = self.device()
        admin = self.client('admin')
        self.assert_edit_permissions(self.permissions(admin), True)
        # Simulate an explicit administrative credential restore outside the API.
        with self.sessions() as db:
            db.get(SyncDevice, device_id).active = True
            db.commit()
        before = self.snapshot()
        self.assertEqual(admin.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)
        self.assertEqual(admin.post('/api/stocks/1/price', json=self.price_change()).status_code, 409)
        self.assert_edit_permissions(self.permissions(admin), False)
        self.assertEqual(self.snapshot(), before)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class LegacyWriterGuardPostgresTest(LegacyWriterGuardTest):
    postgres = True
