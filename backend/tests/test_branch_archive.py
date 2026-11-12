"""Arxiv haqiqiy moliyaviy yozuvlarni saqlaydi; faqat bog'langan hisob boshqaradi."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import date, timedelta
import unittest
import uuid

from sqlalchemy import select, func, inspect
import test_shared_online as shared_fixture
from app.models import User, Branch, BranchArchive, SystemOwner, Stock, Sale, Audit, SavedCart
from app.security import password_hash, verify_password
from app.branch_lifecycle import initialize_owner
from app.online_transition import prepare_online


class BranchArchiveTest(unittest.TestCase):
    client = shared_fixture.SharedOnlineTest.client
    sale = shared_fixture.SharedOnlineTest.sale
    provision = shared_fixture.SharedOnlineTest.provision
    tearDown = shared_fixture.SharedOnlineTest.tearDown

    def setUp(self):
        shared_fixture.SharedOnlineTest.setUp(self)
        with self.sessions() as db:
            db.add(User(id=4, username='abduqodir', name='Boshliq', role='boss',
                        password_hash=password_hash(self.secret)))
            db.flush()
            initialize_owner(db)
            db.commit()
        self.owner = self.client()
        response = self.owner.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(response.status_code, 200, response.text)
        self.owner_data = response.json()

    def archive(self, client=None, name='Shared'):
        return (client or self.owner).post('/api/branches/1/archive', json={'confirmation': name})

    def restore(self, client=None):
        return (client or self.owner).post('/api/branches/1/restore', json={'confirmation': 'Shared'})

    def test_owner_binding_label_password_and_other_boss_protection(self):
        self.assertEqual(self.owner_data['name'], 'Programmist')
        self.assertEqual(self.owner_data['role_label'], 'Programmist')
        self.assertTrue(self.owner_data['can_archive_branches'])
        self.assertNotIn('password_hash', self.owner_data)
        with self.sessions() as db:
            original = db.get(User, 4).password_hash
            initialize_owner(db)
            db.commit()
            self.assertEqual(db.get(SystemOwner, 1).user_id, 4)
            self.assertEqual(db.get(User, 4).password_hash, original)
            self.assertTrue(verify_password(self.secret, original))
        for role in ('boss', 'admin', 'cashier'):
            other = self.client(role)
            self.assertFalse(other.get('/api/auth/me').json()['can_archive_branches'])
            self.assertEqual(self.archive(other).status_code, 403)
            self.assertEqual(self.restore(other).status_code, 403)
        boss = self.client('boss')
        for body in ({'active': False}, {'password': uuid.uuid4().hex}):
            self.assertEqual(boss.patch('/api/users/4', json=body).status_code, 403)
        # Hatto DBdan nofaol qilingan egasining hisobini boshqa boshliq egallay olmaydi.
        with self.sessions() as db:
            db.get(User, 4).active = False
            db.commit()
        self.assertEqual(boss.patch('/api/users/4', json={'active': True}).status_code, 403)
        self.assertEqual(self.archive().status_code, 401)

    def test_history_preserved_writes_blocked_sessions_revoked_and_restore(self):
        cashier = self.client('cashier')
        debtor = self.owner.post('/api/debtors', json={'branch_id':1,'first_name':'Test','last_name':'Debtor',
            'phone1':'+998900000001','phone2':'+998900000002','address':'Test address'}).json()
        sold = cashier.post('/api/sales', json=dict(self.sale(), cash='5000', debtor_id=debtor['id'],
                            due_date=(date.today() + timedelta(days=2)).isoformat()))
        self.assertEqual(sold.status_code, 201, sold.text)
        sale_id = sold.json()['id']
        debt = self.owner.get('/api/debts?branch_id=1').json()['items'][0]
        cart_body = {'branch_id':1,'label':'Saved history','items':[{'product_id':1,'kg':'1'}]}
        cart = self.owner.post('/api/carts', json=cart_body).json()
        expense = {'request_id':str(uuid.uuid4()),'branch_id':1,'supplier_id':1,'amount':'100','method':'cash','reason':'Test expense'}
        self.assertEqual(self.owner.post('/api/expenses', json=expense).status_code, 201)
        dashboard = self.owner.get('/api/dashboard?branch_id=1').json()
        with self.sessions() as db:
            before = {table.name: db.scalar(select(func.count()).select_from(table))
                      for table in Branch.metadata.sorted_tables
                      if table.name not in ('branch_archives', 'auth_sessions', 'audit_logs', 'login_attempts')}
        self.assertEqual(self.archive(name='wrong').status_code, 422)
        self.assertEqual(self.archive().status_code, 200)
        self.assertEqual(self.archive().status_code, 200)  # Javobi yo'qolsa qayta yuborish.
        with self.sessions() as db:
            after = {table.name: db.scalar(select(func.count()).select_from(table))
                     for table in Branch.metadata.sorted_tables if table.name in before}
            self.assertEqual(before, after)
            self.assertEqual(db.get(Stock, 1).kg, Decimal(9))
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'Filial arxivlandi')), 1)
        self.assertEqual([b['id'] for b in self.owner.get('/api/branches').json()], [2])
        all_branches = self.owner.get('/api/branches?include_archived=true').json()
        self.assertTrue(all_branches[0]['archived'])
        self.assertEqual(self.owner.get('/api/sales?branch_id=1').json()['items'][0]['id'], sale_id)
        archived_debt = self.owner.get('/api/debts?branch_id=1').json()['items'][0]
        self.assertEqual(archived_debt, dict(debt, management=dict(debt['management'], can_revise=False)))
        self.assertEqual(self.owner.get('/api/carts?branch_id=1').json()[0]['id'], cart['id'])
        self.assertEqual(self.owner.post(f"/api/debts/{debt['id']}/pay", json={'request_id':str(uuid.uuid4()),'cash':'5000','card':'0'}).status_code, 409)
        self.assertEqual(self.owner.post('/api/expenses', json=dict(expense, request_id=str(uuid.uuid4()))).status_code, 409)
        self.assertEqual(self.owner.delete(f"/api/carts/{cart['id']}?version={cart['version']}").status_code, 409)
        after_dashboard = self.owner.get('/api/dashboard?branch_id=1').json()
        for key in ('today', 'cash', 'card', 'inventory_kg', 'inventory_value', 'supplier_debt'):
            self.assertEqual(dashboard[key], after_dashboard[key])
        self.assertTrue(after_dashboard['branches'][0]['archived'])
        self.assertEqual(cashier.get('/api/auth/me').status_code, 401)
        self.assertEqual(cashier.post('/api/auth/login', json={'username':'test_cashier','password':self.secret}).status_code, 403)
        self.assertEqual(self.owner.post('/api/sales', json=self.sale()).status_code, 409)
        receipt = {'request_id':str(uuid.uuid4()),'branch_id':1,'product_id':1,'kg':'1','price':'10000'}
        self.assertEqual(self.owner.post('/api/receipts', json=receipt).status_code, 409)
        self.assertEqual(self.owner.patch('/api/stocks/1/discount', json={'discount':'1'}).status_code, 409)
        self.assertEqual(self.owner.post('/api/carts', json={'branch_id':1,'label':'Cart','items':[{'product_id':1,'kg':'1'}]}).status_code, 409)
        self.assertEqual(self.owner.post('/api/users', json={'username':'new_cashier','name':'New','password':self.secret,'role':'cashier','branch_id':1}).status_code, 409)
        self.assertEqual(self.restore().status_code, 200)
        self.assertEqual(self.restore().status_code, 200)
        self.assertEqual(self.owner.get('/api/debts?branch_id=1').json()['items'][0], debt)
        cashier = self.client('cashier')
        self.assertEqual(cashier.post('/api/sales', json=self.sale()).status_code, 201)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, Decimal(8))
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 2)
            self.assertIsNone(db.get(BranchArchive, 1))

    def test_reserved_login_cannot_transfer_owner_rights(self):
        response = self.owner.post('/api/auth/settings', json={'username':'renamed_owner','current_password':self.secret})
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            initialize_owner(db)
            self.assertEqual(db.get(SystemOwner, 1).user_id, 4)
        other = self.client('boss')
        self.assertEqual(other.post('/api/auth/settings', json={'username':'abduqodir','current_password':self.secret}).status_code, 403)
        body = {'username':'abduqodir','name':'Impersonation','password':self.secret,'role':'boss'}
        self.assertEqual(other.post('/api/users', json=body).status_code, 403)
        self.assertEqual(self.archive(other).status_code, 403)
        response = self.owner.post('/api/auth/login', json={'username':'renamed_owner','password':self.secret})
        self.assertTrue(response.json()['can_archive_branches'])
        self.assertEqual(self.archive().status_code, 200)

    def test_legacy_branch_requires_transition_before_archive(self):
        folder, config = self.provision()
        self.assertEqual(self.archive().status_code, 409)
        prepare_online(folder, self.wire)
        self.assertEqual(self.archive().status_code, 200)
        self.assertEqual(self.owner.get('/api/sync/branches').json()[0]['id'], 2)
        self.assertEqual(self.owner.post('/api/sync/devices', json={'branch_id':1,'name':'late PC'}).status_code, 409)
        response = self.server.post('/api/sync/push', headers={'Authorization':'Bearer '+config['token']},
            json={'branch_id':1,'events':[{'event_id':str(uuid.uuid4()),'sequence':1,'payload':{}}]})
        self.assertEqual(response.status_code, 409)
        # O'tilgan PCdagi online yordamchi arxivlangan profil sabab boshqa filiallarni bloklamaydi.
        prepare_online(folder, self.wire)

    def test_archive_and_sale_are_atomic_with_parallel_clients(self):
        cashier = self.client('cashier')
        with ThreadPoolExecutor(max_workers=2) as pool:
            archived = pool.submit(self.archive)
            sold = pool.submit(cashier.post, '/api/sales', json=self.sale())
            self.assertEqual(archived.result().status_code, 200)
            result = sold.result()
        self.assertIn(result.status_code, (201, 401, 409))
        with self.sessions() as db:
            count = db.scalar(select(func.count()).select_from(Sale))
            self.assertEqual(count, 1 if result.status_code == 201 else 0)
            self.assertEqual(db.get(Stock, 1).kg, Decimal(10 - count))
            self.assertIsNotNone(db.get(BranchArchive, 1))
        self.assertEqual(self.owner.post('/api/sales', json=self.sale()).status_code, 409)

    def test_archive_is_additive_and_no_public_owner_grant(self):
        columns = {c['name'] for c in inspect(self.engine).get_columns('branches')}
        self.assertEqual(columns, {'id', 'name'})
        response = self.owner.post('/api/branches/999/archive', json={'confirmation':'Missing'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.owner.post('/api/branches/1/archive', json={'confirmation':'Shared','user_id':4}).status_code, 422)
        self.assertEqual(self.owner.post('/api/branches/1/archive', json={'confirmation':'Shared'},
            headers={'Origin':'https://untrusted.invalid','sec-fetch-site':'cross-site'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
