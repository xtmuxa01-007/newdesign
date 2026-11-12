"""Desktop suspension isolates active old writers without changing business data.

All sessions use disposable SQLite fixtures or the explicitly enabled CI database.
No installed EXE, AppData directory, real Telegram account or production DB is used.
"""
import base64
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import sqlite3
import unittest
import uuid
from contextlib import closing
from unittest.mock import Mock, patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import test_branch_archive as fixture
import test_shared_online as shared_fixture
from app.db import get_db
from app.main import app
from app.models import Stock
from app.offline_queue import enqueue
from app.online_transition import prepare_online
from app.routes_sync import InboxEvent, SyncDevice
from app.security import token_hash
from app.shared_mode import SharedBranch, has_legacy_writer
from app.sync_worker import SyncWorker


class DesktopPauseTest(unittest.TestCase):
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision
    offline_sale = shared_fixture.SharedOnlineTest.offline_sale

    def setUp(self):
        fixture.BranchArchiveTest.setUp(self)
        # Existing legacy fixtures opt in to enabled mode. Each new case explicitly
        # exercises the production-default suspension after its initial login.
        self._pause_fixture = patch.dict(os.environ, {
            'CRM_DESKTOP_ENABLED': '0', 'CRM_LEGACY_SYNC_ENABLED': '0'})
        self._pause_fixture.start()
        self.addCleanup(self._pause_fixture.stop)

    def snapshot(self, except_tables=()):
        with self.sessions() as db:
            return {table.name: sorted(list(db.execute(select(table))), key=repr)
                    for table in Stock.metadata.sorted_tables if table.name not in except_tables}

    def seed_active_device(self, pending=True):
        device_id, token = str(uuid.uuid4()), uuid.uuid4().hex + uuid.uuid4().hex
        payload = {'version': 3, 'changes': []}
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        with self.sessions() as db:
            db.add(SyncDevice(id=device_id, branch_id=1, name='Asosiy kassa fixture',
                              token_digest=token_hash(token), active=True,
                              received_sequence=4,
                              last_received_at=datetime(2026, 11, 3, 15, 56, tzinfo=timezone.utc)))
            db.flush()
            if pending:
                db.add(InboxEvent(device_id=device_id, event_id=str(uuid.uuid4()), sequence=4,
                                  payload=payload, payload_digest=hashlib.sha256(encoded).hexdigest(),
                                  received_at=datetime.now(timezone.utc), applied_at=None))
            db.commit()
        return device_id, {'Authorization': 'Bearer ' + token}

    def adjustment(self, expected='10'):
        return {'request_id': str(uuid.uuid4()), 'expected_kg': expected, 'kg': '8.125',
                'reason': 'Reviziyada haqiqiy qoldiq tekshirildi'}

    def assert_paused(self, response):
        # Already-open older EXE frontends clear pending operations on 4xx.
        # A retryable pause preserves those operations until a deliberate resume.
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['code'], 'desktop_paused')
        self.assertIn('EXE', response.json()['detail'])

    def test_default_and_invalid_settings_remain_suspended_without_database_access(self):
        from app.desktop_access import desktop_enabled, legacy_sync_enabled
        with patch.dict(os.environ):
            os.environ.pop('CRM_DESKTOP_ENABLED', None)
            os.environ.pop('CRM_LEGACY_SYNC_ENABLED', None)
            self.assertFalse(desktop_enabled())
            self.assertFalse(legacy_sync_enabled())
            os.environ['CRM_LEGACY_SYNC_ENABLED'] = '1'
            for value in ('', '0', 'false', 'False', 'true', 'TRUE', 'yes', 'enabled', '1 ', ' 1'):
                os.environ['CRM_DESKTOP_ENABLED'] = value
                self.assertFalse(desktop_enabled(), value)
                self.assertFalse(legacy_sync_enabled(), value)
            os.environ['CRM_DESKTOP_ENABLED'] = '1'
            self.assertTrue(desktop_enabled())
            for value in ('', '0', 'false', 'true', 'yes', '1 ', ' 1'):
                os.environ['CRM_LEGACY_SYNC_ENABLED'] = value
                self.assertFalse(legacy_sync_enabled(), value)
            os.environ['CRM_LEGACY_SYNC_ENABLED'] = '1'
            self.assertTrue(legacy_sync_enabled())
        before = self.snapshot()
        # A paused guard must not query or alter even a historical device record.
        self.assertFalse(has_legacy_writer(object(), 1))
        self.assertFalse(has_legacy_writer(object()))
        response = self.server.get('/api/desktop/status')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enabled'], False)
        self.assertEqual(response.json()['paused'], True)
        self.assertEqual(response.json()['legacy_sync_enabled'], False)
        self.assertEqual(response.json()['code'], 'desktop_paused')
        self.assertEqual(self.server.head('/api/desktop/status').status_code, 200)
        self.assert_paused(self.server.get('/api/desktop/status', headers={'User-Agent': 'Electron/35.0.0'}))
        self.assert_paused(self.server.post('/api/desktop/status', headers={'User-Agent': 'Electron/35.0.0'}, json={}))
        # Ordinary service health checks remain usable, while known suspended
        # clients cannot use even an operational endpoint as an exception.
        self.assertEqual(self.server.get('/api/health').status_code, 200)
        self.assert_paused(self.server.get('/api/health', headers={'User-Agent': 'Electron/35.0.0'}))
        self.assertEqual(self.snapshot(), before)

    def test_active_old_device_no_longer_blocks_web_revision_and_all_legacy_data_survives(self):
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        receipt = self.owner.post('/api/receipts', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1, 'product_id': 1,
            'kg': '2', 'price': '11000', 'note': 'Original business receipt'})
        self.assertEqual(receipt.status_code, 201, receipt.text)
        device_id, headers = self.seed_active_device()
        admin = self.client('admin')
        before_read = self.snapshot()
        response = admin.get('/api/products/1/analytics?branch_id=1')
        self.assertEqual(response.status_code, 200, response.text)
        permissions = response.json()['permissions']
        self.assertTrue(permissions['can_adjust_stock'])
        self.assertTrue(permissions['can_edit_price'])
        self.assertIsNone(permissions['adjustment_disabled_reason'])
        self.assertIsNone(permissions['price_edit_reason'])
        self.assertEqual(self.snapshot(), before_read)
        preserved = self.snapshot({'stocks', 'stock_adjustments', 'audit_logs'})
        command = self.adjustment('11')
        changed = admin.post('/api/stocks/1/adjustments', json=command)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(admin.post('/api/stocks/1/adjustments', json=command).json(), changed.json())
        self.assertEqual(self.snapshot({'stocks', 'stock_adjustments', 'audit_logs'}), preserved)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, Decimal('8.125'))
            self.assertEqual(db.get(Stock, 1).price, Decimal('11000'))
            self.assertEqual(db.get(Stock, 2).kg, Decimal('10'))
            self.assertTrue(db.get(SyncDevice, device_id).active)
            self.assertEqual(db.get(SyncDevice, device_id).received_sequence, 4)
            self.assertIsNone(db.get(SharedBranch, 1))
        events = self.owner.get('/api/notifications/changes').json()['items']
        revision = next(entry for entry in events if entry['kind'] == 'stock_adjustment')
        self.assertEqual(revision['actor'], 'admin')
        self.assertEqual(revision['stock']['before'], '11.000')
        self.assertEqual(revision['stock']['after'], '8.125')
        self.assertEqual(revision['reason'], command['reason'])
        after_edit = self.snapshot()
        self.assert_paused(self.server.get('/api/sync/device', headers=headers))
        self.assertEqual(self.snapshot(), after_edit)

    def test_every_legacy_sync_local_and_download_entry_is_denied_before_dependencies(self):
        _, headers = self.seed_active_device()
        before = self.snapshot()
        original_dependency = app.dependency_overrides[get_db]

        def forbidden_database():
            raise AssertionError('Suspended desktop request reached the database dependency')

        paths = (
            ('GET', '/api/sync/capabilities'), ('GET', '/api/sync/branches'),
            ('POST', '/api/sync/devices'), ('GET', '/api/sync/device'),
            ('POST', '/api/sync/push'), ('GET', '/api/sync/bootstrap'),
            ('GET', '/api/sync/catalog'), ('GET', '/api/sync/images/' + 'a' * 32 + '.jpg'),
            ('GET', '/api/sync/recovery-events?after=0'), ('POST', '/api/sync/activate-shared'),
            ('GET', '/api/sync/status'), ('POST', '/api/sync/now'),
            ('POST', '/api/local/backups'), ('POST', '/api/local/server'),
            ('GET', '/api/local/backups/missing.zip'),
            ('GET', '/api/desktop/updates/latest.yml'),
            ('GET', '/api/desktop/updates/files/v0.5.3/TIN-CRM-Setup-0.5.3.exe'),
        )
        app.dependency_overrides[get_db] = forbidden_database
        try:
            for authorization in ({}, headers):
                for method, path in paths:
                    with self.subTest(method=method, path=path, authenticated=bool(authorization)):
                        # Even spoofing a web/Telegram marker cannot bypass a blocked protocol.
                        response = self.server.request(method, path,
                            headers={**authorization, 'x-crm-client': 'telegram-web'},
                            json={} if method == 'POST' else None)
                        self.assert_paused(response)
        finally:
            app.dependency_overrides[get_db] = original_dependency
        self.assertEqual(self.snapshot(), before)

    def test_existing_exe_session_and_desktop_login_are_rejected_without_side_effects(self):
        admin = self.client('admin')
        before = self.snapshot()
        desktop_headers = (
            {'User-Agent': 'Mozilla/5.0 TIN-CRM/0.5.3 Chrome/132.0 Electron/35.0.0 Safari/537.36'},
            {'User-Agent': 'Mozilla/5.0 electron/35.0.0', 'x-crm-client': 'telegram-web'},
            {'User-Agent': 'TINCRM/0.5.3', 'x-crm-client': 'web'},
            {'User-Agent': 'Marva-CRM/0.4.8'},
            {'User-Agent': 'Mozilla/5.0 Chrome/132.0', 'x-crm-client': 'desktop'},
            {'User-Agent': 'Mozilla/5.0 Chrome/132.0', 'x-crm-client': 'exe'},
            {'User-Agent': 'python-httpx/0.28.1', 'x-crm-client': 'web'},
        )
        for headers in desktop_headers:
            with self.subTest(headers=headers):
                self.assert_paused(admin.get('/api/auth/me?telegram=1', headers=headers))
                self.assert_paused(admin.post('/api/stocks/1/adjustments', headers=headers, json=self.adjustment()))
                self.assert_paused(admin.post('/api/auth/login', headers=headers,
                    json={'username': 'test_admin', 'password': self.secret}))
        self.assertEqual(self.snapshot(), before)

    def test_paused_local_instance_cannot_accept_browser_writes_without_sync_capture(self):
        admin = self.client('admin')
        before = self.snapshot()
        original_dependency = app.dependency_overrides[get_db]

        def forbidden_database():
            raise AssertionError('Suspended local API reached a database dependency')

        app.dependency_overrides[get_db] = forbidden_database
        try:
            for modern, legacy in (('0', '0'), ('1', '0'), ('0', '1')):
                with self.subTest(modern=modern, legacy=legacy), patch.dict(os.environ, {
                        'CRM_BRANCH_ID': '1', 'CRM_DESKTOP_ENABLED': modern, 'CRM_LEGACY_SYNC_ENABLED': legacy}):
                    for headers in ({}, {'User-Agent': 'Mozilla/5.0 Windows NT 10.0 Chrome/132.0'}):
                        self.assert_paused(admin.get('/api/auth/me', headers=headers))
                        self.assert_paused(admin.post('/api/stocks/1/adjustments', headers=headers,
                                                      json=self.adjustment()))
                        self.assert_paused(admin.post('/api/sales', headers=headers, json=self.sale()))
                    # Read-only operational status does not grant local CRM access.
                    self.assertEqual(admin.get('/api/desktop/status').status_code, 200)
        finally:
            app.dependency_overrides[get_db] = original_dependency
        self.assertEqual(self.snapshot(), before)

    def test_ordinary_web_and_telegram_clients_keep_their_sessions_and_permissions(self):
        self.seed_active_device()
        admin = self.client('admin')
        before = self.snapshot()
        for headers in (
            {'User-Agent': 'Mozilla/5.0 Windows NT 10.0 Chrome/132.0 Safari/537.36'},
            {'User-Agent': 'TelegramDesktop/5.8.0 (Windows)', 'x-crm-client': 'telegram-web'},
            {'User-Agent': 'Mozilla/5.0 iPhone AppleWebKit/605.1.15 Telegram-iOS/11.0'},
            {'User-Agent': 'Mozilla/5.0 Android WebView Chrome/132.0'},
        ):
            with self.subTest(headers=headers):
                response = admin.get('/api/auth/me', headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['role'], 'admin')
                response = admin.get('/api/products/1/analytics?branch_id=1', headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()['permissions']['can_adjust_stock'])
        self.assertEqual(self.snapshot(), before)

    def test_explicit_resume_restores_the_legacy_guard_without_auto_applying_any_queue(self):
        device_id, headers = self.seed_active_device()
        admin = self.client('admin')
        before = self.snapshot()
        with patch.dict(os.environ, {'CRM_DESKTOP_ENABLED': '1', 'CRM_LEGACY_SYNC_ENABLED': '1'}):
            status = self.server.get('/api/desktop/status')
            self.assertEqual(status.status_code, 200, status.text)
            self.assertTrue(status.json()['enabled'])
            self.assertFalse(status.json()['paused'])
            self.assertTrue(status.json()['legacy_sync_enabled'])
            self.assertEqual(status.json()['code'], 'desktop_enabled')
            response = admin.get('/api/products/1/analytics?branch_id=1')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()['permissions']['can_adjust_stock'])
            self.assertFalse(response.json()['permissions']['can_edit_price'])
            self.assertEqual(admin.post('/api/stocks/1/adjustments', json=self.adjustment()).status_code, 409)
            identity = self.server.get('/api/sync/device', headers=headers)
            self.assertEqual(identity.status_code, 200, identity.text)
            self.assertEqual(identity.json()['device_id'], device_id)
            self.assertEqual(identity.json()['received_sequence'], 4)
        self.assert_paused(self.server.get('/api/sync/device', headers=headers))
        self.assertEqual(self.snapshot(), before)

    def test_resuming_modern_exe_does_not_silently_resume_old_database_or_its_blockers(self):
        _, headers = self.seed_active_device()
        admin = self.client('admin')
        before = self.snapshot()
        with patch.dict(os.environ, {'CRM_DESKTOP_ENABLED': '1', 'CRM_LEGACY_SYNC_ENABLED': '0'}):
            status = self.server.get('/api/desktop/status').json()
            self.assertTrue(status['enabled'])
            self.assertFalse(status['legacy_sync_enabled'])
            response = admin.get('/api/auth/me', headers={'User-Agent': 'Electron/35.0.0'})
            self.assertEqual(response.status_code, 200, response.text)
            response = admin.get('/api/products/1/analytics?branch_id=1')
            self.assertTrue(response.json()['permissions']['can_adjust_stock'])
            self.assert_paused(self.server.get('/api/sync/device', headers=headers))
            self.assert_paused(admin.get('/api/auth/me', headers={'User-Agent': 'python-httpx/0.28.1'}))
        # A legacy-only flag must not open an old writer while desktop remains
        # suspended; resuming either channel always requires deliberate choices.
        with patch.dict(os.environ, {'CRM_DESKTOP_ENABLED': '0', 'CRM_LEGACY_SYNC_ENABLED': '1'}):
            self.assertFalse(self.server.get('/api/desktop/status').json()['legacy_sync_enabled'])
            self.assert_paused(self.server.get('/api/sync/device', headers=headers))
            self.assert_paused(admin.get('/api/auth/me', headers={'User-Agent': 'Electron/35.0.0'}))
        self.assertEqual(self.snapshot(), before)

    def test_release_publisher_authentication_remains_separate_from_exe_downloads(self):
        # Invalid OIDC must reach its publisher check and remain forbidden,
        # rather than make a legitimate release workflow an EXE-client bypass.
        payload = {'version': '0.5.3', 'filename': 'TIN-CRM-Setup-0.5.3.exe', 'size': 1,
                   'sha512': base64.b64encode(b'x' * 64).decode(),
                   'url': 'https://release-assets.githubusercontent.com/fixture'}
        before = self.snapshot()
        with patch('app.routes_desktop.require_publisher', side_effect=AssertionError('Unexpected publisher call')):
            self.assert_paused(self.server.post('/api/desktop/updates/publish', json=payload,
                headers={'User-Agent': 'Electron/35.0.0'}))
        response = self.server.post('/api/desktop/updates/publish', json=payload,
                                    headers={'Authorization': 'Bearer fixture-invalid-oidc'})
        self.assertEqual(response.status_code, 403, response.text)
        response = self.server.post('/api/desktop/updates/publish', json=payload,
            headers={'Authorization': 'Bearer fixture-invalid-oidc', 'User-Agent': 'python-httpx/0.28.1'})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_paused_server_preserves_the_old_local_database_and_unacknowledged_queue(self):
        with patch.dict(os.environ, {'CRM_DESKTOP_ENABLED': '1', 'CRM_LEGACY_SYNC_ENABLED': '1'}):
            folder, config = self.provision()
            self.offline_sale(folder, config)
        database = folder / 'branch.db'

        def local_business():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                        for table in ('stocks', 'sales', 'sale_items', 'offline_outbox')}

        before_local = local_business()
        self.assertGreater(len(before_local['offline_outbox']), 0)
        before_server = self.snapshot()
        config_bytes = (folder / 'device.json').read_bytes()
        with self.assertRaises(httpx.HTTPStatusError) as rejected:
            prepare_online(folder, self.wire)
        self.assertEqual(rejected.exception.response.status_code, 503)
        local_engine = create_engine('sqlite:///' + database.as_posix())
        local_sessions = sessionmaker(local_engine, expire_on_commit=False)
        try:
            worker = SyncWorker(local_sessions, config, folder / 'uploads', transport=self.wire)
            worker.once()
            self.assertGreater(worker.status()['pending'], 0)
            self.assertIn('503', worker.status()['error'])
        finally:
            local_engine.dispose()
        self.assertTrue(database.is_file())
        self.assertEqual((folder / 'device.json').read_bytes(), config_bytes)
        self.assertEqual(local_business(), before_local)
        self.assertEqual(self.snapshot(), before_server)

    def test_paused_startup_never_starts_an_old_sync_worker_but_keeps_telegram_reports(self):
        import app.main as main
        device_id, _ = self.seed_active_device()
        with self.sessions() as db:
            enqueue(db, device_id=device_id, branch_id=1,
                    payload={'version': 3, 'changes': [{'saved': 'unacknowledged fixture'}]})
            db.commit()
        before = self.snapshot({'stock_valuation_state', 'stock_valuation_versions'})
        worker = Mock()
        worker.config = {'device_id': device_id, 'branch_id': 1}
        original_config = dict(worker.config)
        sentinel = object()
        previous_worker = getattr(app.state, 'sync_worker', sentinel)
        previous_telegram = getattr(app.state, 'telegram_report_worker', sentinel)
        app.state.sync_worker = worker

        async def startup():
            async with main.lifespan(app):
                worker.start.assert_not_called()
                worker.wake_event.set.assert_not_called()

        try:
            for modern, legacy in (('0', '0'), ('1', '0'), ('0', '1')):
                with self.subTest(modern=modern, legacy=legacy), \
                        patch.dict(os.environ, {'CRM_DESKTOP_ENABLED': modern, 'CRM_LEGACY_SYNC_ENABLED': legacy}), \
                        patch.object(main, 'engine', self.engine), \
                        patch.object(main, 'SessionLocal', self.sessions), \
                        patch.object(main, 'UPLOADS', self.root / 'startup-uploads'), \
                        patch.object(main.offline_queue, 'install_capture') as capture, \
                        patch.object(main.offline_queue, 'uninstall_capture') as remove_capture, \
                        patch.object(main, 'DailyReportWorker') as report_worker:
                    asyncio.run(startup())
                    capture.assert_not_called()
                    remove_capture.assert_not_called()
                    worker.start.assert_not_called()
                    worker.stop.assert_not_called()
                    worker.wake_event.set.assert_not_called()
                    report_worker.assert_called_once_with(self.sessions)
                    report_worker.return_value.start.assert_called_once_with()
                    report_worker.return_value.stop.assert_called_once_with()
            self.assertEqual(worker.config, original_config)
            self.assertEqual(self.snapshot({'stock_valuation_state', 'stock_valuation_versions'}), before)
        finally:
            for key, previous in (('sync_worker', previous_worker), ('telegram_report_worker', previous_telegram)):
                if previous is sentinel:
                    if hasattr(app.state, key):
                        delattr(app.state, key)
                else:
                    setattr(app.state, key, previous)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class DesktopPausePostgresTest(DesktopPauseTest):
    postgres = True
