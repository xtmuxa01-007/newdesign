"""Faqat vaqtinchalik DBlar: bir filial, web/EXE seanslari va offline o'tish."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['COOKIE_SECURE'] = 'false'
os.environ.pop('CRM_BRANCH_ID', None)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func, URL, text
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db
from app.models import Branch, User, Supplier, Product, Stock, Sale, Audit, DebtPayment
from app.security import password_hash
from app.shared_mode import SharedBranch
from app.routes_sync import SyncDevice
from app.center_profile import SERVER
from app.provision_local import provision_device
from app.online_transition import prepare_online
from app.offline_queue import install_capture, uninstall_capture, OutboxEvent
from app.connection import ConnectionProblem
from app import routes_auth, routes_sales
from test_center_profile import branch_environment


class SharedOnlineTest(unittest.TestCase):
    def setUp(self):
        # These fixtures exercise the explicitly re-enabled legacy protocol.
        # Production defaults remain paused; pause tests override these flags.
        desktop_mode = patch.dict(os.environ, {
            'CRM_DESKTOP_ENABLED': '1', 'CRM_LEGACY_SYNC_ENABLED': '1'})
        desktop_mode.start()
        self.addCleanup(desktop_mode.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='tin-shared-')
        self.root = Path(self.temp.name).resolve()
        if getattr(self, 'postgres', False):
            # Faqat CI disposable DB; production nomi bilan bu fixture ishlamaydi.
            if os.getenv('DB_NAME') != 'marva_ci':
                raise RuntimeError('PostgreSQL sinovi faqat marva_ci bazasida mumkin.')
            self.pg_schema = 'test_' + uuid.uuid4().hex
            self.engine = create_engine(URL.create('postgresql+psycopg',
                username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                host=os.environ['DB_HOST'], database='marva_ci'),
                connect_args={'options':'-csearch_path='+self.pg_schema})
            with self.engine.begin() as connection:
                connection.execute(text('CREATE SCHEMA '+self.pg_schema))
        else:
            self.engine = create_engine('sqlite:///' + (self.root / 'central.db').as_posix(),
                                    connect_args={'check_same_thread': False, 'timeout': 15})
            @event.listens_for(self.engine, 'connect')
            def configure(connection, _):
                connection.isolation_level = None
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA journal_mode=WAL')
            @event.listens_for(self.engine, 'begin')
            def begin(connection):
                connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        def central_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = central_db
        self.clients = []
        self.server = self.client()
        self.secret = uuid.uuid4().hex
        with self.sessions() as db:
            db.add_all([Branch(id=1, name='Shared'), Branch(id=2, name='Other'), Supplier(id=1, name='Supplier')])
            db.flush()
            for number, role in enumerate(('boss', 'admin', 'cashier'), 1):
                db.add(User(id=number, username='test_' + role, name=role, role=role,
                            branch_id=None if role == 'boss' else 1, password_hash=password_hash(self.secret)))
            db.add(Product(id=1, name='Product', sku='TEST-1', supplier_id=1))
            db.flush()
            db.add_all([Stock(id=1, branch_id=1, product_id=1, kg=10, price=10000),
                        Stock(id=2, branch_id=2, product_id=1, kg=10, price=10000)])
            db.commit()
        self.online = True
        self.lose_push = False
        self.lose_activation = False
        self.requests = []
        def transport(request):
            if not self.online:
                raise httpx.ConnectError('fixture offline', request=request)
            self.requests.append(request.url.path)
            with branch_environment():
                response = self.server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            flag = ('lose_push' if request.url.path == '/api/sync/push' else
                    'lose_activation' if request.url.path == '/api/sync/activate-shared' else None)
            if flag and getattr(self, flag):
                setattr(self, flag, False)
                raise httpx.ReadTimeout('fixture lost acknowledgement', request=request)
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)
        self.wire = httpx.MockTransport(transport)
        self.credentials = {'server': SERVER, 'username': 'test_boss', 'password': self.secret,
                            'branch_id': 1, 'name': 'Legacy fixture'}

    def client(self, role=None):
        client = TestClient(app, base_url=SERVER)
        self.clients.append(client)
        if role:
            response = client.post('/api/auth/login', json={'username': 'test_' + role, 'password': self.secret})
            self.assertEqual(response.status_code, 200, response.text)
        return client

    def tearDown(self):
        for client in self.clients:
            client.close()
        app.dependency_overrides.pop(get_db, None)
        if getattr(self, 'pg_schema', None):
            with self.engine.begin() as connection:
                connection.execute(text('DROP SCHEMA '+self.pg_schema+' CASCADE'))
        self.engine.dispose()
        self.temp.cleanup()

    def sale(self, kg='1', **extra):
        return dict(request_id=str(uuid.uuid4()), branch_id=1, customer='Test',
                    items=[{'product_id': 1, 'kg': kg}], expected_total=str(Decimal(kg) * 10000),
                    cash=str(Decimal(kg) * 10000), card='0', **extra)

    def provision(self, folder=None, branch=1):
        folder = folder or self.root / 'pc'
        config = provision_device(folder, dict(self.credentials, branch_id=branch), self.wire)
        return folder, config

    def offline_sale(self, folder, config):
        engine = create_engine('sqlite:///' + (folder / 'branch.db').as_posix())
        sessions = sessionmaker(engine, expire_on_commit=False)
        listener = install_capture(sessions, config['device_id'], 1)
        local_app = FastAPI()
        local_app.include_router(routes_auth.router)
        local_app.include_router(routes_sales.router)
        def local_db():
            with sessions() as db:
                yield db
        local_app.dependency_overrides[get_db] = local_db
        try:
            with TestClient(local_app) as local, branch_environment(1):
                response = local.post('/api/auth/login', json={'username': 'test_boss', 'password': self.secret})
                self.assertEqual(response.status_code, 200, response.text)
                response = local.post('/api/sales', json=self.sale())
                self.assertEqual(response.status_code, 201, response.text)
        finally:
            uninstall_capture(sessions, listener)
            engine.dispose()

    def test_lost_sync_and_transition_ack_preserve_sales_and_unlock_all_clients(self):
        folder, config = self.provision()
        self.offline_sale(folder, config)
        web = self.client('boss')
        self.assertEqual(web.post('/api/sales', json=self.sale()).status_code, 409)
        self.online = False
        with self.assertRaises(httpx.ConnectError):
            prepare_online(folder, self.wire)
        self.online, self.lose_push = True, True
        with self.assertRaises(ConnectionProblem):
            prepare_online(folder, self.wire)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)
            self.assertIsNone(db.get(SharedBranch, 1))
        self.lose_activation = True
        with self.assertRaises(httpx.ReadTimeout):
            prepare_online(folder, self.wire)
        self.assertFalse(json.loads((folder / 'shared-transition.json').read_text())['completed'])
        prepare_online(folder, self.wire)
        self.assertTrue(json.loads((folder / 'shared-transition.json').read_text())['completed'])
        self.assertTrue(list((folder / 'backups').glob('*.zip')))
        # O'tish / restart markazga ikkinchi savdo yubormaydi.
        prepare_online(folder, self.wire)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)
        for role in ('boss', 'admin', 'cashier'):
            response = self.client(role).post('/api/sales', json=self.sale())
            self.assertEqual(response.status_code, 201, response.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, Decimal(6))
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 4)
        response = self.server.post('/api/sync/push', headers={'Authorization': 'Bearer ' + config['token']},
            json={'branch_id': 1, 'events': [{'event_id': str(uuid.uuid4()), 'sequence': 999, 'payload': {}}]})
        self.assertEqual(response.status_code, 409)
        with closing(sqlite3.connect(folder / 'branch.db')) as local:
            self.assertEqual(local.execute('SELECT count(*) FROM sales').fetchone()[0], 1)

    def test_new_pcs_do_not_register_or_claim_branch(self):
        for name in ('pc-a', 'pc-b', 'pc-c'):
            result = prepare_online(self.root / name, self.wire)
            self.assertEqual(result['mode'], 'online')
            self.assertEqual(result['migrated_branches'], [])
        self.assertNotIn('/api/sync/devices', self.requests)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SyncDevice)), 0)

    def test_parallel_sales_do_not_oversell_and_replay_does_not_charge_twice(self):
        folder, _ = self.provision()
        prepare_online(folder, self.wire)
        pc1, pc2 = self.client('cashier'), self.client('cashier')
        requests = [self.sale('6'), self.sale('6')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: pair[0].post('/api/sales', json=pair[1]), zip((pc1, pc2), requests)))
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        winner = next(i for i, r in enumerate(results) if r.status_code == 201)
        replay = pc1.post('/api/sales', json=requests[winner])
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()['id'], results[winner].json()['id'])
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, Decimal(4))
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 1)

    def test_multiple_clients_keep_roles_branch_scope_and_edit_versions(self):
        folder, _ = self.provision()
        prepare_online(folder, self.wire)
        pc, web, cashier = self.client('admin'), self.client('boss'), self.client('cashier')
        sale = pc.post('/api/sales', json=self.sale()).json()
        item = sale['items'][0]
        edit = {'request_id': str(uuid.uuid4()), 'version': 0, 'reason': 'Test change',
                'customer': '', 'cash': '5000', 'card': '0',
                'items': [{'item_id': item['id'], 'product_id': 1, 'kg': '0.5', 'price': '10000', 'discount': '0'}]}
        self.assertEqual(cashier.post(f"/api/sales/{sale['id']}/edit", json=edit).status_code, 403)
        result = web.post(f"/api/sales/{sale['id']}/edit", json=edit)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(pc.post(f"/api/sales/{sale['id']}/edit", json=dict(edit, request_id=str(uuid.uuid4()))).status_code, 409)
        bad = self.sale(); bad['branch_id'] = 2
        self.assertEqual(pc.post('/api/sales', json=bad).status_code, 403)
        receipt = {'request_id': str(uuid.uuid4()), 'branch_id': 1, 'product_id': 1, 'kg': '2', 'price': '10000'}
        self.assertEqual(pc.post('/api/receipts', json=receipt).status_code, 201)
        self.assertEqual(cashier.post('/api/receipts', json=dict(receipt, request_id=str(uuid.uuid4()))).status_code, 403)
        self.assertEqual(web.post('/api/branches', json={'name': 'From EXE or web'}).status_code, 201)
        self.assertEqual(web.post('/api/products', json={'name': 'New product', 'sku': 'NEW', 'supplier_id': 1}).status_code, 201)

    def test_saved_cart_stale_version_cannot_checkout_or_overwrite(self):
        folder, _ = self.provision()
        prepare_online(folder, self.wire)
        pc1, pc2 = self.client('cashier'), self.client('cashier')
        payload = {'branch_id': 1, 'label': 'Cart', 'items': [{'product_id': 1, 'kg': '1'}]}
        cart = pc1.post('/api/carts', json=payload).json()
        updated = pc2.put(f"/api/carts/{cart['id']}", json=dict(payload, version=cart['version']))
        self.assertEqual(updated.status_code, 200, updated.text)
        stale = pc1.post('/api/sales', json=self.sale(saved_cart_id=cart['id'], saved_cart_version=cart['version']))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(pc1.delete(f"/api/carts/{cart['id']}?version={cart['version']}").status_code, 409)
        result = pc1.post('/api/sales', json=self.sale(saved_cart_id=cart['id'], saved_cart_version=updated.json()['version']))
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(pc2.get('/api/carts?branch_id=1').json(), [])

    def test_bad_journal_or_failed_backup_cannot_activate_shared_branch(self):
        folder, config = self.provision()
        headers = {'Authorization': 'Bearer ' + config['token']}
        response = self.server.post('/api/sync/activate-shared', headers=headers,
                                    json={'received_sequence': 7, 'last_digest': 'a' * 64})
        self.assertEqual(response.status_code, 409)
        with patch('app.online_transition.create_backup', side_effect=OSError('fixture backup failure')):
            with self.assertRaises(OSError):
                prepare_online(folder, self.wire)
        with self.sessions() as db:
            self.assertIsNone(db.get(SharedBranch, 1))
        self.assertTrue((folder / 'branch.db').is_file())
        self.assertFalse((folder / 'shared-transition.json').exists())

    def test_all_saved_profiles_transition_and_a_server_rollback_is_detected(self):
        folder, _ = self.provision()
        self.provision(folder / 'branches' / '2', branch=2)
        result = prepare_online(folder, self.wire)
        self.assertEqual(result['migrated_branches'], [1, 2])
        with self.sessions() as db:
            db.delete(db.get(SharedBranch, 1)); db.commit()
        with self.assertRaises(ConnectionProblem):
            prepare_online(folder, self.wire)


if __name__ == '__main__':
    unittest.main()
