"""Reset faqat vaqtinchalik fixture bazasida sinovdan o'tadi."""
from datetime import date, timedelta
import os
import unittest
import uuid
from sqlalchemy import select, func, text
import test_branch_archive as fixture
from app.database_reset import reset_plan, reset_database
from app.models import User, SystemOwner, Branch, Product, Audit
from app.security import verify_password


class DatabaseResetTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    provision = fixture.BranchArchiveTest.provision
    sale = fixture.BranchArchiveTest.sale

    def seed_history(self):
        debtor = self.owner.post('/api/debtors', json={'branch_id':1,'first_name':'Reset','last_name':'Fixture',
            'phone1':'+998900000001','phone2':'+998900000002','address':'Test only'}).json()
        sold = self.owner.post('/api/sales', json=dict(self.sale(),cash='5000',debtor_id=debtor['id'],
            due_date=(date.today()+timedelta(days=1)).isoformat()))
        self.assertEqual(sold.status_code, 201, sold.text)
        self.assertEqual(self.owner.post('/api/carts', json={'branch_id':1,'label':'Draft','items':[{'product_id':1,'kg':'1'}]}).status_code,201)
        self.assertEqual(self.owner.post('/api/products/1/archive',json={'confirmation':'TEST-1'}).status_code,200)
        self.assertEqual(self.owner.post('/api/branches/1/archive',json={'confirmation':'Shared'}).status_code,200)

    def test_only_owner_password_and_reset_audit_remain(self):
        self.seed_history()
        with self.sessions() as db:
            user = db.get(User,4)
            user.branch_id = 1
            original = user.password_hash
            db.commit()
            plan = reset_plan(db,'abduqodir')
            result = reset_database(db,'abduqodir',plan['confirmation'],'reset-fixture-1234')
            db.commit()
            db.expire_all()
            self.assertEqual(db.get(User,4).password_hash,original)
            self.assertTrue(verify_password(self.secret,original))
            self.assertIsNone(db.get(User,4).branch_id)
            self.assertEqual(db.get(SystemOwner,1).user_id,4)
            self.assertEqual(result['rows_after']['users'],1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Branch)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Product)),0)
            self.assertEqual(db.scalar(select(Audit)).detail['backup_id'],'reset-fixture-1234')
        self.assertEqual(self.owner.get('/api/auth/me').status_code,401)
        login = self.owner.post('/api/auth/login',json={'username':'abduqodir','password':self.secret})
        self.assertEqual(login.status_code,200)
        self.assertTrue(login.json()['can_archive_products'])
        self.assertEqual(self.client().post('/api/auth/login',json={'username':'test_boss','password':self.secret}).status_code,401)
        created = self.owner.post('/api/branches',json={'name':'New start'})
        self.assertEqual(created.status_code,201,created.text)

    def test_invalid_owner_confirmation_or_schema_never_deletes(self):
        with self.sessions() as db:
            plan = reset_plan(db,'abduqodir')
            with self.assertRaises(ValueError):
                reset_plan(db,'test_boss')
            with self.assertRaises(ValueError):
                reset_database(db,'abduqodir','wrong','reset-fixture-1234')
            db.rollback()
            self.assertEqual(reset_plan(db,'abduqodir'),plan)
            db.add(Branch(id=3, name='Changed after preview'))
            db.commit()
            with self.assertRaises(ValueError):
                reset_database(db,'abduqodir',plan['confirmation'],'reset-fixture-1234')
            db.rollback()
            self.assertEqual(db.scalar(select(func.count()).select_from(User)),4)
            db.execute(text('CREATE TABLE unexpected_fixture (id INTEGER PRIMARY KEY)'))
            db.commit()
            try:
                with self.assertRaises(ValueError):
                    reset_plan(db,'abduqodir')
            finally:
                db.execute(text('DROP TABLE unexpected_fixture'))
                db.commit()

    def test_transaction_rollback_restores_every_row(self):
        self.seed_history()
        with self.sessions() as db:
            before = reset_plan(db,'abduqodir')
            reset_database(db,'abduqodir',before['confirmation'],'reset-fixture-1234')
            db.rollback()  # Masalan disk/yakuniy tekshiruv xatosi.
            self.assertEqual(reset_plan(db,'abduqodir'),before)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class DatabaseResetPostgresTest(DatabaseResetTest):
    postgres = True
