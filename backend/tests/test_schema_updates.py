"""Only disposable SQLite or explicit marva_ci PostgreSQL schemas are used."""
import os
import unittest
import uuid

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from sqlalchemy import URL, create_engine, inspect, select, text
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Branch, OperationCancellation, User
from app import schema_updates as updates


class SchemaUpdatesTest(unittest.TestCase):
    def test_fresh_sqlite_metadata_has_new_kind_and_requires_no_rebuild(self):
        engine = create_engine('sqlite:///:memory:')
        try:
            Base.metadata.create_all(engine)
            before = inspect(engine).get_check_constraints('operation_cancellations')
            self.assertTrue(any('other_payment' in item['sqltext'] for item in before))
            self.assertFalse(updates.ensure_other_payment_kind(engine))
            self.assertEqual(inspect(engine).get_check_constraints('operation_cancellations'), before)
        finally:
            engine.dispose()

    def test_known_postgres_and_metadata_enum_expressions_are_recognized(self):
        old = "kind IN ('sale','receipt','supplier_payment','donation_payment','expense','debt_payment','stock_adjustment')"
        postgres = "((kind)::text = ANY ((ARRAY['sale'::character varying, 'receipt'::character varying, 'supplier_payment'::character varying, 'donation_payment'::character varying, 'expense'::character varying, 'debt_payment'::character varying, 'stock_adjustment'::character varying])::text[]))"
        self.assertEqual(updates._kind_values(old), updates._OLD_KINDS)
        self.assertEqual(updates._kind_values(postgres), updates._OLD_KINDS)
        self.assertEqual(updates._kind_values(updates._CHECK), updates._NEW_KINDS)
        for unsupported in (old + ' OR operation_id > 0', "kind <> 'unknown'",
                            old.replace("'sale'", "'unknown'"), None):
            with self.assertRaises(RuntimeError):
                updates._kind_values(unsupported)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class SchemaUpdatesPostgresTest(unittest.TestCase):
    def setUp(self):
        if os.getenv('DB_NAME') != 'marva_ci':
            raise RuntimeError('Sxema sinovi faqat marva_ci bazasida mumkin.')
        self.schema = 'test_' + uuid.uuid4().hex
        self.engine = create_engine(URL.create('postgresql+psycopg',
            username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
            host=os.environ['DB_HOST'], database='marva_ci'),
            connect_args={'options': '-csearch_path=' + self.schema})
        with self.engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA ' + self.schema))
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add(Branch(id=1, name='Migration fixture'))
            db.add(User(id=1, username='fixture', name='Fixture', role='boss', password_hash='not-a-password'))
            db.flush()
            db.add(self.marker('supplier_payment', 'initial-source'))
            db.commit()

    def tearDown(self):
        with self.engine.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + self.schema + ' CASCADE'))
        self.engine.dispose()

    @staticmethod
    def marker(kind, original):
        return OperationCancellation(kind=kind, operation_id=1, original_request_id=original,
            request_id=str(uuid.uuid4()), branch_id=1, user_id=1, actor='Fixture',
            reason='Migration fixture', snapshot={'record': {'amount': '100.00'}})

    def state(self):
        with self.engine.connect() as connection:
            return list(connection.execute(select(OperationCancellation.__table__)))

    def set_legacy_check(self, expression=None):
        with self.engine.begin() as connection:
            checks = updates._kind_checks(connection)
            self.assertEqual(len(checks), 1)
            quote = connection.dialect.identifier_preparer.quote_identifier
            connection.execute(text('ALTER TABLE operation_cancellations DROP CONSTRAINT ' + quote(checks[0][0])))
            old = "kind IN ('sale','receipt','supplier_payment','donation_payment','expense','debt_payment','stock_adjustment')"
            connection.execute(text('ALTER TABLE operation_cancellations ADD CONSTRAINT ' +
                quote('legacy kind check') + ' CHECK (' + (expression or old) + ')'))

    def test_existing_legacy_constraint_rows_and_other_checks_are_preserved(self):
        self.set_legacy_check()
        before_rows = self.state()
        before_checks = {item['name']: item['sqltext'] for item in
                         inspect(self.engine).get_check_constraints('operation_cancellations')
                         if item['name'] != 'legacy kind check'}
        self.assertTrue(updates.ensure_other_payment_kind(self.engine))
        self.assertEqual(self.state(), before_rows)
        after = inspect(self.engine).get_check_constraints('operation_cancellations')
        self.assertTrue(any(item['name'] == 'legacy kind check' and 'other_payment' in item['sqltext'] for item in after))
        self.assertEqual({item['name']: item['sqltext'] for item in after
                          if item['name'] != 'legacy kind check'}, before_checks)
        self.assertFalse(updates.ensure_other_payment_kind(self.engine))
        with Session(self.engine) as db:
            db.add(self.marker('other_payment', 'new-source'))
            db.commit()
        self.assertEqual(len(self.state()), 2)

    def test_fresh_postgres_is_idempotent_without_altering_data(self):
        before = self.state()
        self.assertFalse(updates.ensure_other_payment_kind(self.engine))
        self.assertFalse(updates.ensure_other_payment_kind(self.engine))
        self.assertEqual(self.state(), before)

    def test_unexpected_kind_check_fails_closed_without_changing_rows_or_constraints(self):
        self.set_legacy_check("kind <> 'unknown'")
        before_rows = self.state()
        before_checks = inspect(self.engine).get_check_constraints('operation_cancellations')
        with self.assertRaises(RuntimeError):
            updates.ensure_other_payment_kind(self.engine)
        self.assertEqual(self.state(), before_rows)
        self.assertEqual(inspect(self.engine).get_check_constraints('operation_cancellations'), before_checks)


if __name__ == '__main__':
    unittest.main()
