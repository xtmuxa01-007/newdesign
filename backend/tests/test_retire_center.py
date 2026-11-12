"""Resetdan keyin eski qurilma 401: pending saqlanadi, markazga qayta yuborilmaydi."""
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import select, func
import test_shared_online as fixture
from app.center_profile import prepare_center, NAMESPACE
from app.connection import ConnectionProblem, LegacyDeviceUnavailable
from app.local_backup import verify_backup
from app.models import Sale
from app.online_transition import prepare_online, journal_state
from app.retire_center import retire_center
from app.routes_sync import SyncDevice


class RetireCenterTest(unittest.TestCase):
    client = fixture.SharedOnlineTest.client
    sale = fixture.SharedOnlineTest.sale
    provision = fixture.SharedOnlineTest.provision
    offline_sale = fixture.SharedOnlineTest.offline_sale
    tearDown = fixture.SharedOnlineTest.tearDown

    def setUp(self):
        fixture.SharedOnlineTest.setUp(self)
        self.legacy = self.root / 'legacy'
        prepare_center(self.legacy)
        self.center = self.legacy / 'centers' / NAMESPACE
        _, self.config = self.provision(self.center)
        self.offline_sale(self.center, self.config)
        self.initial_pending = self.pending(self.center)
        self.assertGreater(self.initial_pending, 0)

    def revoke(self):
        with self.sessions() as db:
            db.get(SyncDevice, self.config['device_id']).active = False
            db.commit()

    def pending(self, folder):
        with closing(sqlite3.connect(folder / 'branch.db')) as connection:
            return journal_state(connection)[0]

    def test_retired_profile_pending_backup_and_fresh_online_connection(self):
        self.revoke()
        with self.assertRaises(LegacyDeviceUnavailable):
            prepare_online(self.center, self.wire)
        self.requests.clear()
        result = retire_center(self.center, self.wire)
        retired = Path(result['archive_directory'])
        self.assertFalse(self.center.exists())
        self.assertEqual(retired.parent, self.center.parent)
        self.assertEqual(result['pending_preserved'], self.initial_pending)
        self.assertEqual(self.pending(retired), self.initial_pending)
        manifest = json.loads((retired / 'retired-profile.json').read_text())
        verify_backup(retired / manifest['profiles'][0]['backup'])
        prepare_center(self.legacy)
        self.assertEqual(prepare_online(self.center, self.wire)['mode'], 'online')
        self.assertEqual(sorted(p.name for p in self.center.iterdir()), ['center-profile.json'])
        self.assertNotIn('/api/sync/push', self.requests)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 0)

    def test_backup_failure_keeps_profile_and_retry_can_finish(self):
        self.revoke()
        with patch('app.retire_center.verify_backup', side_effect=ValueError('fixture corrupt backup')):
            with self.assertRaises(ValueError):
                retire_center(self.center, self.wire)
        self.assertTrue((self.center / 'device.json').exists())
        self.assertEqual(self.pending(self.center), self.initial_pending)
        self.assertFalse(list(self.center.parent.glob('retired-*')))
        self.assertEqual(retire_center(self.center, self.wire)['pending_preserved'], self.initial_pending)

    def test_network_server_error_and_live_device_never_retire(self):
        with self.assertRaises(ConnectionProblem):
            retire_center(self.center, self.wire)
        self.online = False
        with self.assertRaises(httpx.TransportError):
            retire_center(self.center, self.wire)
        with self.assertRaises(httpx.TransportError):
            prepare_online(self.center, self.wire)
        self.assertTrue(self.center.is_dir())
        self.assertEqual(self.pending(self.center), self.initial_pending)
        self.assertFalse(list(self.center.parent.glob('retired-*')))

    def test_wrong_root_and_mixed_active_profiles_preserve_all(self):
        self.provision(self.center / 'branches' / '2', branch=2)
        self.revoke()
        with self.assertRaises(ConnectionProblem):
            retire_center(self.center, self.wire)
        with self.assertRaises(ConnectionProblem):
            retire_center(self.legacy, self.wire)
        self.assertTrue((self.center / 'branches' / '2' / 'branch.db').exists())
        self.assertEqual(self.pending(self.center), self.initial_pending)
