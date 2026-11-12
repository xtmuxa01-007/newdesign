"""Login tahriri hisob IDsi, tarix va Programmist vakolatini saqlaydi."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest
import uuid

from sqlalchemy import select
import test_branch_archive as fixture
from app.branch_lifecycle import initialize_owner
from app.models import AuthSession, Audit, Sale, SystemOwner, User
from app.security import verify_password


class AccountUsernameTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale

    def user_state(self, user_id):
        with self.sessions() as db:
            target = db.get(User, user_id)
            return {key: getattr(target, key) for key in (
                'id', 'username', 'name', 'role', 'branch_id', 'active', 'password_hash')}

    def session_state(self):
        with self.sessions() as db:
            result = {}
            for session in db.scalars(select(AuthSession)):
                result.setdefault(session.user_id, set()).add(session.id)
            return result

    def changed_audits(self):
        with self.sessions() as db:
            return [entry.detail for entry in db.scalars(select(Audit).where(
                Audit.action == 'Foydalanuvchi yangilandi').order_by(Audit.id))]

    def login(self, username, password=None):
        client = self.client()
        response = client.post('/api/auth/login', json={
            'username': username, 'password': password or self.secret})
        self.assertEqual(response.status_code, 200, response.text)
        return client, response.json()

    def test_boss_renames_account_keeps_password_history_and_revokes_only_target_sessions(self):
        boss = self.client('boss')
        admin = self.client('admin')
        cashier_a, cashier_b = self.client('cashier'), self.client('cashier')
        sold = cashier_a.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        sale_id = sold.json()['id']
        before = self.user_state(3)
        sessions = self.session_state()
        changed = boss.patch('/api/users/3', json={'username': '  CASHIER_NEW.01  '})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['username'], 'cashier_new.01')
        self.assertNotIn('password_hash', changed.json())
        self.assertEqual(self.user_state(3), {**before, 'username': 'cashier_new.01'})
        self.assertEqual(self.session_state(), {key: value for key, value in sessions.items() if key != 3})
        for old in (cashier_a, cashier_b):
            self.assertEqual(old.get('/api/auth/me').status_code, 401)
        for unchanged in (boss, admin, self.owner):
            self.assertEqual(unchanged.get('/api/auth/me').status_code, 200)
        old_login = self.client().post('/api/auth/login', json={
            'username': 'test_cashier', 'password': self.secret})
        self.assertEqual(old_login.status_code, 401)
        _, renamed = self.login('cashier_new.01')
        self.assertEqual((renamed['id'], renamed['role'], renamed['branch_id']), (3, 'cashier', 1))
        self.assertFalse(renamed['can_edit_inventory'])
        with self.sessions() as db:
            sale = db.get(Sale, sale_id)
            self.assertEqual((sale.user_id, sale.branch_id, sale.total, sale.cash), (3, 1, 10000, 10000))
        audit = self.changed_audits()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]['target_id'], 3)
        self.assertEqual(audit[0]['username'], 'cashier_new.01')
        self.assertEqual(audit[0]['previous_username'], 'test_cashier')
        self.assertFalse(audit[0]['password_changed'])
        self.assertNotIn(before['password_hash'], str(audit))
        self.assertNotIn(self.secret, str(audit))

    def test_case_only_or_missing_username_keeps_existing_sessions_and_password(self):
        cashier = self.client('cashier')
        before, sessions = self.user_state(3), self.session_state()
        for payload in ({'username': ' TEST_CASHIER '}, {'username': None}, {'active': True}):
            changed = self.owner.patch('/api/users/3', json=payload)
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(self.user_state(3), before)
            self.assertEqual(self.session_state(), sessions)
            self.assertEqual(cashier.get('/api/auth/me').status_code, 200)

    def test_username_validation_and_permissions_do_not_change_account(self):
        before, sessions = self.user_state(3), self.session_state()
        for username in ('', ' ', 'ab', 'a' * 61, 'first last', 'a@b', 'o‘quvchi'):
            with self.subTest(username=username):
                response = self.owner.patch('/api/users/3', json={'username': username})
                self.assertEqual(response.status_code, 422, response.text)
        for role in ('admin', 'cashier'):
            client = self.client(role)
            response = client.patch('/api/users/3', json={'username': 'unauthorized_new'})
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client().patch('/api/users/3', json={'username': 'anonymous_new'}).status_code, 401)
        self.assertEqual(self.owner.patch('/api/users/3', json={
            'username': 'renamed', 'role': 'boss'}).status_code, 422)
        self.assertEqual(self.user_state(3), before)
        # Additional clients added their own sessions; the original sessions remain.
        current = self.session_state()
        for user_id, ids in sessions.items():
            self.assertTrue(ids <= current[user_id])
        self.assertEqual(self.changed_audits(), [])

    def test_duplicate_username_rolls_back_other_fields_and_preserves_sessions(self):
        self.client('cashier')
        before, sessions = self.user_state(3), self.session_state()
        response = self.owner.patch('/api/users/3', json={
            'username': ' TEST_ADMIN ', 'active': False, 'password': uuid.uuid4().hex})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.user_state(3), before)
        self.assertEqual(self.session_state(), sessions)
        self.assertEqual(self.changed_audits(), [])

    def test_owner_rename_keeps_owner_id_and_reserved_login_cannot_transfer(self):
        before = self.user_state(4)
        changed = self.owner.patch('/api/users/4', json={'username': '  Programmer_2026  '})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()['can_archive_branches'])
        self.assertTrue(changed.json()['can_edit_inventory'])
        self.assertEqual(changed.json()['role_label'], 'Programmist')
        self.assertEqual(self.owner.get('/api/auth/me').status_code, 401)
        owner, info = self.login('programmer_2026')
        self.assertEqual(info['id'], 4)
        self.assertTrue(info['is_programmer'])
        self.assertEqual(self.user_state(4), {**before, 'username': 'programmer_2026'})
        with self.sessions() as db:
            initialize_owner(db)
            db.commit()
            self.assertEqual(db.get(SystemOwner, 1).user_id, 4)
        other_boss = self.client('boss')
        self.assertEqual(other_boss.patch('/api/users/4', json={'username': 'owner_stolen'}).status_code, 403)
        self.assertEqual(other_boss.patch('/api/users/3', json={'username': ' Abduqodir '}).status_code, 403)
        self.assertEqual(owner.patch('/api/users/2', json={'username': 'abduqodir'}).status_code, 403)
        self.assertEqual(owner.post('/api/users', json={
            'username': 'ABDUQODIR', 'name': 'New boss', 'password': uuid.uuid4().hex,
            'role': 'boss'}).status_code, 403)
        self.assertEqual(self.user_state(3)['username'], 'test_cashier')
        self.assertEqual(self.user_state(2)['username'], 'test_admin')
        self.assertEqual(owner.get('/api/auth/me').status_code, 200)
        restored = owner.patch('/api/users/4', json={'username': 'abduqodir'})
        self.assertEqual(restored.status_code, 200, restored.text)
        _, restored_info = self.login('abduqodir')
        self.assertEqual(restored_info['id'], 4)
        self.assertTrue(restored_info['can_archive_products'])

    def test_username_and_password_change_requires_new_credentials(self):
        cashier = self.client('cashier')
        new_password = uuid.uuid4().hex
        response = self.owner.patch('/api/users/3', json={
            'username': 'cashier_both', 'password': new_password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(cashier.get('/api/auth/me').status_code, 401)
        for username, password in (('test_cashier', self.secret), ('cashier_both', self.secret)):
            response = self.client().post('/api/auth/login', json={'username': username, 'password': password})
            self.assertEqual(response.status_code, 401, response.text)
        _, changed = self.login('cashier_both', new_password)
        self.assertEqual(changed['id'], 3)
        with self.sessions() as db:
            self.assertTrue(verify_password(new_password, db.get(User, 3).password_hash))
        audit = self.changed_audits()
        self.assertEqual(len(audit), 1)
        self.assertTrue(audit[0]['password_changed'])
        self.assertNotIn(new_password, str(audit))

    def test_missing_account_and_untrusted_origin_preserve_data(self):
        before, sessions = self.user_state(3), self.session_state()
        missing = self.owner.patch('/api/users/999', json={'username': 'does_not_exist'})
        self.assertEqual(missing.status_code, 404, missing.text)
        untrusted = self.owner.patch('/api/users/3', json={'username': 'untrusted_new'},
                                    headers={'Origin': 'https://untrusted.invalid'})
        self.assertEqual(untrusted.status_code, 403, untrusted.text)
        self.assertEqual(self.user_state(3), before)
        self.assertEqual(self.session_state(), sessions)
        self.assertEqual(self.changed_audits(), [])

    def test_self_disable_with_username_does_not_partially_rename_account(self):
        before, sessions = self.user_state(4), self.session_state()
        response = self.owner.patch('/api/users/4', json={'username': 'owner_disabled', 'active': False})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.user_state(4), before)
        self.assertEqual(self.session_state(), sessions)
        self.assertEqual(self.changed_audits(), [])

    def test_parallel_same_username_creates_only_one_account_change(self):
        self.client('admin')
        self.client('cashier')
        before = {user_id: self.user_state(user_id) for user_id in (2, 3)}
        sessions = self.session_state()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda user_id: self.owner.patch(f'/api/users/{user_id}', json={'username': 'same_login'}),
                (2, 3)))
        self.assertEqual(sorted(response.status_code for response in results), [200, 409])
        winner = (2, 3)[next(index for index, response in enumerate(results) if response.status_code == 200)]
        loser = 3 if winner == 2 else 2
        self.assertEqual(self.user_state(winner), {**before[winner], 'username': 'same_login'})
        self.assertEqual(self.user_state(loser), before[loser])
        self.assertEqual(self.session_state(), {key: value for key, value in sessions.items() if key != winner})
        self.assertEqual(len(self.changed_audits()), 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class AccountUsernamePostgresTest(AccountUsernameTest):
    postgres = True
