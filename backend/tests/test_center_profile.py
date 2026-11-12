"""Alohida vaqtinchalik bazalar: eski navbat, qayta urinish va offline savdo.

Ishchi bazaga yoki haqiqiy serverga ulanmaydi. unittest bilan bajariladi.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['COOKIE_SECURE'] = 'false'
os.environ.pop('CRM_BRANCH_ID', None)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db
from app.models import Branch, User, Supplier, Product, Stock, Sale
from app.security import password_hash
from app.center_profile import prepare_center, SERVER, NAMESPACE
from app.local_backup import verify_backup
from app.provision_local import provision_device, discover_branches, atomic_json
from app.sync_worker import SyncWorker
from app.routes_sync import SyncDevice
from app.offline_queue import OutboxEvent, enqueue, pending, install_capture, uninstall_capture
from app import routes_auth, routes_sales
from app.desktop_profiles import select_profile, discover_profiles, active_folder, profile_status, backup_active
from app.connection import ConnectionProblem


@contextmanager
def branch_environment(branch=None):
    keys = ('CRM_BRANCH_ID', 'CRM_OFFLINE_V3')
    previous = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    if branch is not None:
        os.environ.update(CRM_BRANCH_ID=str(branch), CRM_OFFLINE_V3='1')
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class CentralProfileTest(unittest.TestCase):
    def test_server_snapshot_then_offline_sale_without_legacy_replay(self):
        with tempfile.TemporaryDirectory(prefix='tin-profile-') as temporary:
            root = Path(temporary).resolve()
            central_engine = create_engine('sqlite:///' + (root / 'central.db').as_posix())
            Base.metadata.create_all(central_engine)
            central_sessions = sessionmaker(central_engine, expire_on_commit=False)
            def central_db():
                with central_sessions() as db:
                    yield db
            app.dependency_overrides[get_db] = central_db
            server_client = TestClient(app, base_url=SERVER)
            local_engine = None
            listener = None
            try:
                secret = uuid.uuid4().hex
                with central_sessions() as db:
                    db.add_all([Branch(id=1, name='Joriy filial'), Branch(id=2, name='Ikkinchi filial')])
                    db.add(User(id=1, username='fixture_boss', name='Test boss', role='boss', password_hash=password_hash(secret)))
                    db.add(Supplier(id=1, name='Joriy taminotchi'))
                    db.flush()
                    db.add(Product(id=1, name='Joriy sochiq', sku='NEW-1', supplier_id=1))
                    db.flush()
                    db.add_all([Stock(id=1, branch_id=1, product_id=1, kg=10, price=10000),
                                Stock(id=2, branch_id=2, product_id=1, kg=20, price=10000)])
                    db.commit()

                legacy = root / 'old-pc'
                legacy.mkdir()
                old_engine = create_engine('sqlite:///' + (legacy / 'branch.db').as_posix())
                Base.metadata.create_all(old_engine)
                old_config = {'server': 'http://192.168.1.7:8784', 'branch_id': 1,
                              'device_id': str(uuid.uuid4()), 'token': uuid.uuid4().hex * 2}
                atomic_json(legacy / 'device.json', old_config)
                with sessionmaker(old_engine)() as db:
                    enqueue(db, device_id=old_config['device_id'], branch_id=1,
                            payload={'legacy_only': 'NEVER SEND THIS'})
                    db.commit()
                old_engine.dispose()
                old_bytes = (legacy / 'branch.db').read_bytes()
                info = prepare_center(legacy)
                self.assertTrue(info['legacy_preserved'])
                target = legacy / 'centers' / NAMESPACE
                marker = (target / 'center-profile.json').read_bytes()
                saved = json.loads(marker)
                verify_backup(saved['legacy_backup'])
                self.assertEqual((legacy / 'branch.db').read_bytes(), old_bytes)
                self.assertFalse((target / 'branch.db').exists())

                network = {'online': True, 'lose_bootstrap': True, 'lose_ack': False}
                sent_ids = []
                def transport(request):
                    if not network['online']:
                        raise httpx.ConnectError('simulated offline', request=request)
                    with branch_environment():
                        response = server_client.request(request.method, str(request.url),
                            headers=dict(request.headers), content=request.content)
                    if request.url.path == '/api/sync/push':
                        for event in json.loads(request.content)['events']:
                            sent_ids.append(event['event_id'])
                            self.assertNotIn('legacy_only', event['payload'])
                    key = ('lose_bootstrap' if request.url.path == '/api/sync/bootstrap' else
                           'lose_ack' if request.url.path == '/api/sync/push' else None)
                    if key and network[key]:
                        network[key] = False
                        raise httpx.ReadTimeout('simulated lost response after commit', request=request)
                    return httpx.Response(response.status_code, headers=response.headers, content=response.content)
                wire = httpx.MockTransport(transport)
                credentials = {'server': SERVER, 'username': 'fixture_boss', 'password': secret,
                               'branch_id': 1, 'name': 'Test kassa'}
                with self.assertRaises(httpx.HTTPStatusError):
                    discover_branches(target, {**credentials, 'password': 'wrong'}, wire)
                self.assertFalse((target / 'branch.db').exists())
                choices = discover_branches(target, credentials, wire)
                self.assertTrue(all(b['available'] for b in choices['branches']))
                with self.assertRaises(httpx.ReadTimeout):
                    provision_device(target, credentials, wire)
                self.assertFalse((target / 'device.json').exists())
                choices = discover_branches(target, credentials, wire)
                self.assertTrue(next(b for b in choices['branches'] if b['id'] == 1)['available'])
                config = provision_device(target, credentials, wire)
                self.assertNotEqual(config['device_id'], old_config['device_id'])
                self.assertEqual(config['server'], SERVER)
                local_engine = create_engine('sqlite:///' + (target / 'branch.db').as_posix())
                local_sessions = sessionmaker(local_engine, expire_on_commit=False)
                with local_sessions() as db:
                    self.assertEqual(db.get(Product, 1).sku, 'NEW-1')
                    self.assertEqual(db.get(Stock, 1).kg, Decimal('10'))
                    self.assertIsNone(db.get(Stock, 2))
                    self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent)), 0)

                local_app = FastAPI()
                local_app.include_router(routes_auth.router)
                local_app.include_router(routes_sales.router)
                def local_db():
                    with local_sessions() as db:
                        yield db
                local_app.dependency_overrides[get_db] = local_db
                local_client = TestClient(local_app)
                listener = install_capture(local_sessions, config['device_id'], 1)
                worker = SyncWorker(local_sessions, config, target / 'uploads', transport=wire, backup_folder=target)
                network['online'] = False
                with branch_environment(1):
                    login = local_client.post('/api/auth/login', json={'username': 'fixture_boss', 'password': secret})
                    self.assertEqual(login.status_code, 200, login.text)
                    sale = local_client.post('/api/sales', json={
                        'request_id': str(uuid.uuid4()), 'branch_id': 1, 'items': [{'product_id': 1, 'kg': '1.000'}],
                        'expected_total': '10000.00', 'cash': '10000.00', 'card': '0.00', 'customer': 'Offline test',
                    })
                    self.assertEqual(sale.status_code, 201, sale.text)
                    worker.once()
                with local_sessions() as db:
                    self.assertGreater(len(pending(db, config['device_id'])), 0)
                    self.assertEqual(db.get(Stock, 1).kg, Decimal('9'))
                with central_sessions() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 0)
                # Qayta ochish ham, yangilanish ham yuborilmagan navbatni almashtirmaydi.
                prepare_center(legacy)
                self.assertEqual((target / 'center-profile.json').read_bytes(), marker)
                self.assertEqual(json.loads((target / 'device.json').read_text())['device_id'], config['device_id'])
                network.update(online=True, lose_ack=True)
                worker.once()
                with central_sessions() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)
                with local_sessions() as db:
                    self.assertGreater(len(pending(db, config['device_id'])), 0)
                worker.once()
                with local_sessions() as db:
                    self.assertEqual(len(pending(db, config['device_id'])), 0)
                with central_sessions() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)
                    self.assertEqual(db.get(Stock, 1).kg, Decimal('9'))
                    db.get(Product, 1).name = 'Serverdan yangi nom'
                    db.commit()
                worker.once()
                with local_sessions() as db:
                    self.assertEqual(db.get(Product, 1).name, 'Serverdan yangi nom')
                self.assertGreater(len(sent_ids), len(set(sent_ids)))
                self.assertEqual((legacy / 'branch.db').read_bytes(), old_bytes)

                second = root / 'second-pc'
                prepare_center(second)
                second_target = second / 'centers' / NAMESPACE
                choices = discover_branches(second_target, credentials, wire)
                self.assertFalse(next(b for b in choices['branches'] if b['id'] == 1)['available'])
                with self.assertRaises(httpx.HTTPStatusError):
                    provision_device(second_target, credentials, wire)
                config2 = provision_device(second_target, {**credentials, 'branch_id': 2}, wire)
                self.assertEqual(config2['branch_id'], 2)
                with central_sessions() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(SyncDevice)), 2)
                    db.add(Branch(id=3, name='Almashtiriladigan filial'))
                    db.add(Stock(id=3, branch_id=3, product_id=1, kg=30, price=10000))
                    db.commit()
                # Joriy profil o'chmaydi; boshqa filial alohida nusxadan boshlanadi.
                changed = select_profile(target, {**credentials, 'branch_id': 3}, wire)
                self.assertEqual(changed['branch_id'], 3)
                self.assertEqual(active_folder(target), target / 'branches' / '3')
                choices = discover_profiles(target, credentials, wire)
                self.assertTrue(next(b for b in choices['branches'] if b['id'] == 1)['on_this_pc'])
                self.assertFalse(next(b for b in choices['branches'] if b['id'] == 2)['available'])
                with self.assertRaises(httpx.HTTPStatusError):
                    select_profile(target, {**credentials, 'password': 'wrong'}, wire)
                self.assertEqual(profile_status(target)['branch_id'], 3)
                restored = select_profile(target, credentials, wire)
                self.assertEqual(restored['directory'], str(target))
                self.assertEqual(json.loads((target / 'device.json').read_text())['device_id'], config['device_id'])
                with local_sessions() as db:
                    self.assertEqual(db.get(Stock, 1).kg, Decimal('9'))
                    self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)
                    enqueue(db, device_id=config['device_id'], branch_id=1, payload={'pending_test': True})
                    db.commit()
                with self.assertRaises(ConnectionProblem):
                    select_profile(target, {**credentials, 'branch_id': 3}, wire)
                self.assertEqual(profile_status(target)['branch_id'], 1)
                self.assertEqual(backup_active(target)['pending'], 1)
                self.assertEqual(profile_status(target)['pending'], 1)
                print('PASS: switch, return with same device/database, boss required, other PC protected, pending blocks switch, backup preserves pending')
                print('PASS: backup, legacy isolation, failed/retried setup, branch scope, offline login/sale, lost ACK, deduplication, catalog pull, restart, second PC')
            finally:
                if listener:
                    uninstall_capture(local_sessions, listener)
                if local_engine:
                    local_engine.dispose()
                server_client.close()
                app.dependency_overrides.pop(get_db, None)
                central_engine.dispose()


if __name__ == '__main__':
    unittest.main()
