"""Oldingi qarzlar savdo yaratmaydi; undirish va bekor qilish umumiy hisobga kiradi."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from threading import Barrier, Lock
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import select, func, event
import test_branch_archive as fixture
from app.accounting import balances, supplier_debt
from app.models import (
    Audit, BranchExpense, Debt, DebtPayment, Debtor, OpeningDebt,
    OpeningDebtCancellation, OpeningDebtPayment, Receipt, Sale, SaleItem, Stock,
)
from app.opening_debts import source_fingerprint
from app.routes_debts import today


class OpeningDebtsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale

    def count(self, db, model):
        return db.scalar(select(func.count()).select_from(model))

    def debtor(self, branch=1, **changes):
        result = self.owner.post('/api/debtors', json={
            'branch_id': branch, 'first_name': 'Oldingi', 'last_name': 'Qarzdor',
            'phone1': '+998900000001', 'phone2': '+998900000002',
            'address': 'Fixture manzil', **changes})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def create(self, amount='12345.67', branch=1, client=None, debtor=None, **changes):
        debtor = debtor or self.debtor(branch)
        body = {'request_id': str(uuid.uuid4()), 'branch_id': branch,
                'debtor_id': debtor['id'], 'amount': amount, **changes}
        result = (client or self.owner).post('/api/opening-debts', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json(), body

    def pay(self, debt, cash=None, card='0', client=None, **changes):
        body = {'request_id': str(uuid.uuid4()),
                'cash': str(cash if cash is not None else debt['amount']),
                'card': card, **changes}
        result = (client or self.owner).post(f"/api/opening-debts/{debt['id']}/pay", json=body)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json(), body

    def cancel_body(self, kind, operation_id):
        model = OpeningDebt if kind == 'opening_debt' else OpeningDebtPayment
        with self.sessions() as db:
            source = db.get(model, operation_id)
            self.assertIsNotNone(source)
            fingerprint = source_fingerprint(db, kind, source)
        return {'request_id': str(uuid.uuid4()), 'reason': 'Fixture xato yozuv',
                'expected_fingerprint': fingerprint}

    def cancel(self, kind, operation_id, body=None, client=None):
        segment = '' if kind == 'opening_debt' else 'payments/'
        return (client or self.owner).post(
            f'/api/opening-debts/{segment}{operation_id}/cancel',
            json=body or self.cancel_body(kind, operation_id))

    def assert_no_goods_changes(self, expected_debt=0, cash=0, card=0):
        with self.sessions() as db:
            for model in (Sale, SaleItem, Receipt, Debt, DebtPayment):
                self.assertEqual(self.count(db, model), 0, model.__tablename__)
            self.assertEqual(db.get(Stock, 1).kg, 10)
            self.assertEqual(db.get(Stock, 1).price, 10000)
            self.assertEqual(db.get(Stock, 2).kg, 10)
            ledger = balances(db, 1)
            self.assertEqual(ledger['cash'], Decimal(str(cash)))
            self.assertEqual(ledger['card'], Decimal(str(card)))
            self.assertEqual(ledger['customer_debt'], Decimal(str(expected_debt)))
            self.assertEqual(ledger['donation_received'], 0)
            self.assertEqual(supplier_debt(db, 1, 1)['earned'], 0)

    def test_create_principal_without_sale_product_stock_or_cash_movement(self):
        debt, _ = self.create(note='  Oldindan qolgan summa  ')
        self.assertEqual(debt['origin'], 'opening')
        self.assertIsNone(debt['sale_id'])
        self.assertEqual(debt['note'], 'Oldindan qolgan summa')
        self.assertEqual(debt['user_id'], 4)
        self.assertEqual(debt['created_by'], 'Programmist')
        self.assertEqual(debt['status'], 'open')
        self.assertIsNone(debt['payment'])
        self.assertEqual(debt['due_date'], today().isoformat())
        self.assert_no_goods_changes(expected_debt='12345.67')
        dashboard = self.owner.get('/api/dashboard?branch_id=1')
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        data = dashboard.json()
        for key in ('today', 'month', 'year', 'cash', 'card', 'supplier_debt'):
            self.assertEqual(Decimal(data[key]), 0, key)
        self.assertEqual(Decimal(data['customer_debt']), Decimal('12345.67'))
        self.assertEqual(data['recent_sales'], [])

    def test_roles_branch_and_debtor_membership_are_checked_before_creation(self):
        debtor = self.debtor()
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1,
                'debtor_id': debtor['id'], 'amount': '200'}
        self.assertEqual(self.server.post('/api/opening-debts', json=body).status_code, 401)
        self.assertEqual(self.client('cashier').post('/api/opening-debts', json=body).status_code, 403)
        admin = self.client('admin')
        result = admin.post('/api/opening-debts', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        other_debtor = self.debtor(2)
        for change, status in (
            ({'branch_id': 2, 'debtor_id': other_debtor['id']}, 403),
            ({'debtor_id': 99999}, 404),
            ({'debtor_id': other_debtor['id']}, 403),
        ):
            result = admin.post('/api/opening-debts', json=dict(body,
                request_id=str(uuid.uuid4()), **change))
            self.assertEqual(result.status_code, status, result.text)
        self.assertEqual(self.owner.post('/api/opening-debts', json=dict(body,
            request_id=str(uuid.uuid4()), branch_id=99999)).status_code, 404)
        self.assertEqual(self.owner.post('/api/opening-debts', json=dict(body,
            request_id=str(uuid.uuid4())), headers={
                'Origin': 'https://untrusted.invalid', 'sec-fetch-site': 'cross-site'}).status_code, 403)
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1', 'CRM_OFFLINE_V3': '1'}):
            self.assertEqual(self.owner.post('/api/opening-debts',
                json=dict(body, request_id=str(uuid.uuid4()))).status_code, 409)
        self.assert_no_goods_changes(expected_debt=200)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 1)

    def test_invalid_amount_date_extra_fields_are_atomic_and_blank_note_allowed(self):
        debtor = self.debtor()
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1,
                'debtor_id': debtor['id'], 'amount': '200'}
        for changes in (
            {'amount': '0'}, {'amount': '-1'}, {'amount': '1.001'},
            {'amount': 'NaN'}, {'amount': 'Infinity'}, {'amount': '1000000000000'},
            {'amount': '1 000'}, {'request_id': 'short'}, {'debtor_id': 0},
            {'due_date': '2026-02-30'}, {'note': 'x' * 501}, {'sale_id': 1},
            {'user_id': 1}, {'items': [{'product_id': 1, 'kg': '1'}]},
        ):
            with self.subTest(changes=changes):
                result = self.owner.post('/api/opening-debts', json=dict(body, **changes))
                self.assertEqual(result.status_code, 422, result.text)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 0)
        debt, _ = self.create(amount=' 1000.50 ', debtor=debtor, note='   ', due_date='2000-01-01')
        self.assertEqual(debt['note'], '')
        self.assertTrue(debt['overdue'])
        self.assertEqual(Decimal(debt['amount']), Decimal('1000.50'))
        self.assert_no_goods_changes(expected_debt='1000.50')

    def test_create_retry_preserves_omitted_due_date_and_rejects_changed_actor_payload(self):
        original_day = date(2026, 10, 2)
        with patch('app.routes_debts.today', return_value=original_day):
            debt, body = self.create(amount='300.00', due_date=None, note='  Oldingi qarz  ')
        later = original_day + timedelta(days=10)
        with patch('app.routes_debts.today', return_value=later):
            retry = self.owner.post('/api/opening-debts', json=dict(body, amount='300', note='Oldingi qarz'))
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual(retry.json()['id'], debt['id'])
        self.assertEqual(retry.json()['due_date'], original_day.isoformat())
        for changes in ({'amount': '301'}, {'due_date': later.isoformat()}, {'note': 'Other note'}):
            result = self.owner.post('/api/opening-debts', json=dict(body, **changes))
            self.assertEqual(result.status_code, 409, result.text)
        result = self.client('boss').post('/api/opening-debts', json=body)
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 1)
        self.assert_no_goods_changes(expected_debt=300)

    def test_parallel_create_same_request_commits_one_principal_and_audit(self):
        debtor = self.debtor()
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1,
                'debtor_id': debtor['id'], 'amount': '200'}
        second_pc = self.client()
        login = second_pc.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pc: pc.post('/api/opening-debts', json=body),
                                    (self.owner, second_pc)))
        self.assertEqual([r.status_code for r in results], [201, 201])
        self.assertEqual(results[0].json()['id'], results[1].json()['id'])
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 1)
            matching = [a for a in db.scalars(select(Audit))
                        if a.detail.get('request_id') == body['request_id']]
            self.assertEqual(len(matching), 1)
        self.assert_no_goods_changes(expected_debt=200)

    def test_combined_listing_pagination_keeps_origin_and_totals_on_id_collision(self):
        debtor = self.debtor()
        sale = self.owner.post('/api/sales', json=dict(self.sale(), cash='0',
            debtor_id=debtor['id'], due_date=(today() + timedelta(days=1)).isoformat()))
        self.assertEqual(sale.status_code, 201, sale.text)
        with self.sessions() as db:
            for _ in range(101):
                db.add(OpeningDebt(request_id=str(uuid.uuid4()), branch_id=1,
                    debtor_id=debtor['id'], user_id=4, amount=Decimal('10'),
                    due_date=today() + timedelta(days=1)))
            db.commit()
        first = self.owner.get('/api/debts?branch_id=1&status=all').json()
        second = self.owner.get('/api/debts?branch_id=1&status=all&offset=100').json()
        self.assertEqual(first['count'], 102)
        self.assertEqual(second['count'], 102)
        self.assertEqual(Decimal(first['amount']), 11010)
        self.assertEqual(first['amount'], second['amount'])
        self.assertEqual(len(first['items']), 100)
        self.assertEqual(len(second['items']), 2)
        all_rows = first['items'] + second['items']
        self.assertEqual(len({(d['origin'], d['id']) for d in all_rows}), 102)
        collision = [d for d in all_rows if d['id'] == sale.json()['debt']['id']]
        self.assertEqual({d['origin'] for d in collision}, {'opening', 'sale'})
        self.assertEqual(self.client('admin').get('/api/debts?status=all').json()['count'], 102)
        self.assertEqual(self.client('admin').get('/api/debts?branch_id=2').status_code, 403)
        self.assertEqual(self.owner.get('/api/debts?status=wrong').status_code, 422)
        self.assertEqual(self.owner.get('/api/debts?offset=-1').status_code, 422)

    def test_due_notifications_include_old_debts_exclude_paid_future_and_other_branch(self):
        overdue, _ = self.create(amount='100', due_date=(today() - timedelta(days=30)).isoformat())
        due, _ = self.create(amount='200', due_date=today().isoformat())
        self.create(amount='300', due_date=(today() + timedelta(days=1)).isoformat())
        paid, _ = self.create(amount='400', due_date=today().isoformat())
        self.pay(paid)
        self.create(amount='500', branch=2, due_date=today().isoformat())
        result = self.client('cashier').get('/api/notifications/debts')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data['count'], 2)
        self.assertEqual(Decimal(data['amount']), 300)
        self.assertEqual({d['id'] for d in data['items']}, {overdue['id'], due['id']})
        self.assertTrue(all(d['overdue'] and d['origin'] == 'opening' for d in data['items']))
        self.assertEqual(self.owner.get('/api/debts?branch_id=1&status=paid').json()['count'], 1)
        self.assertEqual(self.owner.get('/api/debts?branch_id=1&status=open').json()['count'], 3)

    def test_full_payment_money_actor_idempotence_and_independent_sale_debt_route(self):
        debt, _ = self.create(amount='300')
        payer = self.client('cashier')
        path = f"/api/opening-debts/{debt['id']}/pay"
        for cash, card in (('0', '0'), ('301', '0'), ('-1', '301'), ('1.001', '298.999')):
            result = payer.post(path, json={'request_id': str(uuid.uuid4()), 'cash': cash, 'card': card})
            self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.owner.post(f"/api/debts/{debt['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '300', 'card': '0'}).status_code, 404)
        self.assert_no_goods_changes(expected_debt=300)
        paid, body = self.pay(debt, cash='100', card='200', client=payer)
        self.assertEqual(paid['status'], 'paid')
        self.assertFalse(paid['overdue'])
        self.assertEqual(paid['payment']['actor'], 'cashier')
        self.assertEqual(payer.post(path, json=body).status_code, 201)
        self.assertEqual(self.owner.post(path, json=body).status_code, 409)
        self.assertEqual(payer.post(path, json=dict(body, cash='200', card='100')).status_code, 409)
        self.assertEqual(payer.post(path, json=dict(body, request_id=str(uuid.uuid4()))).status_code, 409)
        other, _ = self.create(amount='300', branch=2)
        self.assertEqual(payer.post(f"/api/opening-debts/{other['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '300', 'card': '0'}).status_code, 403)
        self.assert_no_goods_changes(expected_debt=0, cash=100, card=200)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebtPayment), 1)

    def test_two_cashier_pcs_cannot_collect_same_debt_twice(self):
        debt, _ = self.create(amount='300')
        pc1, pc2 = self.client('cashier'), self.client('cashier')
        requests = [{'request_id': str(uuid.uuid4()), 'cash': '300', 'card': '0'} for _ in range(2)]
        path = f"/api/opening-debts/{debt['id']}/pay"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: pair[0].post(path, json=pair[1]),
                                    zip((pc1, pc2), requests)))
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        winner = next(i for i, result in enumerate(results) if result.status_code == 201)
        replay = pc1.post(path, json=requests[winner])
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()['payment']['id'], results[winner].json()['payment']['id'])
        self.assert_no_goods_changes(expected_debt=0, cash=300)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebtPayment), 1)

    def test_cancel_unpaid_principal_keeps_snapshot_and_blocks_old_retry(self):
        debt, original = self.create(amount='123.45', note='Eski daftar')
        body = self.cancel_body('opening_debt', debt['id'])
        self.assertEqual(self.cancel('opening_debt', debt['id'], body, self.client('cashier')).status_code, 403)
        result = self.cancel('opening_debt', debt['id'], body, self.client('admin'))
        self.assertEqual(result.status_code, 200, result.text)
        marker = result.json()['cancellation']
        self.assertEqual(Decimal(marker['snapshot']['record']['amount']), Decimal('123.45'))
        self.assertEqual(marker['snapshot']['record']['note'], 'Eski daftar')
        # Takrorlash actor bilan bog'langan: shu admin aynan shu so'rovni takrorlaydi.
        admin = self.client('admin')
        retry = self.cancel('opening_debt', debt['id'], body, admin)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()['cancellation']['id'], marker['id'])
        self.assertEqual(self.cancel('opening_debt', debt['id'], dict(body, reason='Other reason'), admin).status_code, 409)
        self.assertEqual(self.owner.post('/api/opening-debts', json=original).status_code, 409)
        self.assertEqual(self.owner.get('/api/debts?status=all').json()['count'], 0)
        self.assert_no_goods_changes()
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 0)
            self.assertEqual(self.count(db, OpeningDebtCancellation), 1)
            self.assertIsNotNone(db.get(Debtor, debt['debtor_id']))
        audit = self.owner.get('/api/audit?branch_id=1').json()
        linked = [a for a in audit if a.get('operation') and
                  a['operation']['kind'] == 'opening_debt' and a['operation']['id'] == debt['id']]
        self.assertTrue(linked)
        self.assertTrue(all(a['operation']['cancelled'] and not a['operation']['can_cancel'] for a in linked))

    def test_paid_debt_requires_payment_unwind_stale_fingerprints_and_exact_repay(self):
        debt, original = self.create(amount='300')
        stale = self.cancel_body('opening_debt', debt['id'])
        paid, payment_body = self.pay(debt, cash='100', card='200')
        self.assertEqual(self.cancel('opening_debt', debt['id'], stale).status_code, 409)
        current = self.cancel_body('opening_debt', debt['id'])
        self.assertEqual(self.cancel('opening_debt', debt['id'], current).status_code, 409)
        payment_id = paid['payment']['id']
        cancel_body = self.cancel_body('opening_debt_payment', payment_id)
        result = self.cancel('opening_debt_payment', payment_id, cancel_body)
        self.assertEqual(result.status_code, 200, result.text)
        marker = result.json()['cancellation']
        snapshot = marker['snapshot']
        self.assertEqual(Decimal(snapshot['record']['cash']), 100)
        self.assertEqual(Decimal(snapshot['record']['card']), 200)
        self.assert_no_goods_changes(expected_debt=300)
        replay = self.cancel('opening_debt_payment', payment_id, cancel_body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()['cancellation']['id'], marker['id'])
        self.assertEqual(self.owner.post(f"/api/opening-debts/{debt['id']}/pay", json=payment_body).status_code, 409)
        paid_again, _ = self.pay(debt)
        self.assertGreater(paid_again['payment']['id'], payment_id)
        self.assertEqual(self.cancel('opening_debt_payment', paid_again['payment']['id']).status_code, 200)
        result = self.cancel('opening_debt', debt['id'])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.owner.post('/api/opening-debts', json=original).status_code, 409)
        self.assert_no_goods_changes()
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebtCancellation), 3)

    def test_cancel_validation_scope_and_spent_cash_do_not_lose_principal_or_payment(self):
        debt, _ = self.create(amount='300')
        paid, _ = self.pay(debt)
        payment_id = paid['payment']['id']
        body = self.cancel_body('opening_debt_payment', payment_id)
        for changes in ({'reason': '  '}, {'request_id': 'short'},
                        {'expected_fingerprint': 'bad'}, {'user_id': 4}):
            result = self.cancel('opening_debt_payment', payment_id, dict(body, **changes))
            self.assertEqual(result.status_code, 422, result.text)
        result = self.cancel('opening_debt_payment', payment_id,
            dict(body, expected_fingerprint='0' * 64))
        self.assertEqual(result.status_code, 409, result.text)
        other, _ = self.create(amount='100', branch=2)
        self.assertEqual(self.cancel('opening_debt', other['id'], client=self.client('admin')).status_code, 403)
        with self.sessions() as db:
            db.add(BranchExpense(request_id=str(uuid.uuid4()), branch_id=1,
                user_id=4, supplier_id=1, amount=100, method='cash', reason='Spent collection fixture'))
            db.commit()
        result = self.cancel('opening_debt_payment', payment_id, body)
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(OpeningDebt, debt['id']))
            self.assertIsNotNone(db.get(OpeningDebtPayment, payment_id))
            self.assertEqual(self.count(db, OpeningDebtCancellation), 0)
            self.assertEqual(balances(db, 1)['cash'], 200)
            self.assertEqual(balances(db, 1)['customer_debt'], 0)
            self.assertEqual(self.count(db, BranchExpense), 1)

    def test_cancel_opening_id_collision_preserves_real_sale_debt_and_inventory(self):
        debtor = self.debtor()
        sale_body = dict(self.sale(), cash='2000', debtor_id=debtor['id'],
                         due_date=(today() + timedelta(days=1)).isoformat())
        result = self.owner.post('/api/sales', json=sale_body)
        self.assertEqual(result.status_code, 201, result.text)
        sale = result.json()
        old_debt, _ = self.create(amount='300', debtor=debtor)
        self.assertEqual(old_debt['id'], sale['debt']['id'])
        paid, _ = self.pay(old_debt, cash='100', card='200')
        result = self.cancel('opening_debt_payment', paid['payment']['id'])
        self.assertEqual(result.status_code, 200, result.text)
        result = self.cancel('opening_debt', old_debt['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(Sale, sale['id']))
            self.assertIsNotNone(db.get(Debt, sale['debt']['id']))
            self.assertEqual(self.count(db, Sale), 1)
            self.assertEqual(self.count(db, SaleItem), 1)
            self.assertEqual(db.get(Stock, 1).kg, 9)
            ledger = balances(db, 1)
            self.assertEqual(ledger['customer_debt'], 8000)
            self.assertEqual(ledger['cash'], 2000)
            self.assertEqual(ledger['card'], 0)
            self.assertEqual(supplier_debt(db, 1, 1)['earned'], 10000)
        current = self.owner.get('/api/debts?branch_id=1&status=all').json()
        self.assertEqual(current['count'], 1)
        self.assertEqual(current['items'][0]['origin'], 'sale')
        self.assertEqual(current['items'][0]['id'], sale['debt']['id'])
        retry = self.owner.post('/api/sales', json=sale_body)
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual(retry.json()['id'], sale['id'])

    def test_archive_retains_history_and_blocks_create_pay_cancel(self):
        debt, original = self.create(amount='300')
        cancel_body = self.cancel_body('opening_debt', debt['id'])
        result = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.owner.get('/api/debts?branch_id=1').json()['items'][0]['id'], debt['id'])
        self.assertEqual(self.owner.post('/api/opening-debts',
            json=dict(original, request_id=str(uuid.uuid4()))).status_code, 409)
        self.assertEqual(self.owner.post(f"/api/opening-debts/{debt['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '300', 'card': '0'}).status_code, 409)
        self.assertEqual(self.cancel('opening_debt', debt['id'], cancel_body).status_code, 409)
        self.assert_no_goods_changes(expected_debt=300)

    def test_analytics_counts_only_collection_period_and_never_old_principal_as_sale(self):
        debt, _ = self.create(amount='300')
        self.create(amount='700', branch=2)
        paid, _ = self.pay(debt, cash='100', card='200')
        with self.sessions() as db:
            db.get(OpeningDebt, debt['id']).created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
            db.get(OpeningDebtPayment, paid['payment']['id']).created_at = datetime(
                2026, 9, 30, 19, 0, tzinfo=timezone.utc)  # Toshkent 1-oktabr 00:00.
            db.commit()
        result = self.owner.get('/api/sales/analytics?branch_id=1&start=2026-10-01&end=2026-10-01')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        summary = data['summary']
        self.assertEqual(summary['sales_count'], 0)
        for key in ('goods_total', 'received_at_sale', 'cash', 'card', 'kg', 'donation', 'debt_created'):
            self.assertEqual(Decimal(summary[key]), 0, key)
        self.assertEqual(Decimal(summary['debt_collected']), 300)
        self.assertEqual(Decimal(summary['period_inflow']), 300)
        self.assertEqual(data['products'], [])
        self.assertEqual(Decimal(data['daily'][0]['period_inflow']), 300)
        self.assertEqual(Decimal(data['monthly'][0]['period_inflow']), 300)
        self.assertEqual(Decimal(data['branches'][0]['period_inflow']), 300)
        previous = self.owner.get('/api/sales/analytics?branch_id=1&start=2026-09-01&end=2026-09-30')
        self.assertEqual(previous.status_code, 200, previous.text)
        self.assertEqual(Decimal(previous.json()['summary']['period_inflow']), 0)
        self.assertEqual(self.client('admin').get(
            '/api/sales/analytics?branch_id=2&start=2026-10-01&end=2026-10-01').status_code, 403)
        self.assertEqual(self.cancel('opening_debt_payment', paid['payment']['id']).status_code, 200)
        cancelled = self.owner.get('/api/sales/analytics?branch_id=1&start=2026-10-01&end=2026-10-01')
        self.assertEqual(Decimal(cancelled.json()['summary']['period_inflow']), 0)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class OpeningDebtsPostgresTest(OpeningDebtsTest):
    postgres = True

    def concurrent_requests_after_empty_lookup(self, table, request_id, requests,
                                               id_projection_only=False):
        """Ikkala mustaqil filial global UUIDni bo'sh deb ko'rgach yozishni boshlaydi."""
        barrier, guard = Barrier(2), Lock()
        seen = []

        def after_lookup(connection, cursor, statement, parameters, context, executemany):
            normalized = ' '.join(statement.lower().split())
            if f'from {table} where {table}.request_id =' not in normalized:
                return
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if request_id not in values:
                return
            if id_projection_only and not normalized.startswith(f'select {table}.id from '):
                return
            with guard:
                if len(seen) >= 2:
                    return
                seen.append(True)
            barrier.wait(timeout=15)

        event.listen(self.engine, 'after_cursor_execute', after_lookup)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(pc.post, path, json=body) for pc, path, body in requests]
                results = [future.result(timeout=25) for future in futures]
        finally:
            event.remove(self.engine, 'after_cursor_execute', after_lookup)
        self.assertEqual(seen, [True, True], 'Both requests must reach the empty UUID lookup.')
        return results

    def test_global_creation_uuid_collision_across_branches_has_one_real_principal(self):
        debtors = [self.debtor(1), self.debtor(2)]
        shared_id = str(uuid.uuid4())
        requests = [(pc, '/api/opening-debts', {
            'request_id': shared_id, 'branch_id': branch, 'debtor_id': debtor['id'], 'amount': '200'})
            for pc, branch, debtor in zip((self.owner, self.client('boss')), (1, 2), debtors)]
        results = self.concurrent_requests_after_empty_lookup('opening_debts', shared_id, requests)
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        winner = next(r.json() for r in results if r.status_code == 201)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 1)
            self.assertEqual(self.count(db, OpeningDebtPayment), 0)
            self.assertEqual(balances(db)['customer_debt'], 200)
            self.assertEqual(balances(db)['cash'], 0)
            self.assertEqual(balances(db)['card'], 0)
            for branch in (1, 2):
                self.assertEqual(balances(db, branch)['customer_debt'],
                                 200 if branch == winner['branch_id'] else 0)
                self.assertEqual(db.get(Stock, branch).kg, 10)
            audit = [a for a in db.scalars(select(Audit)) if a.detail.get('request_id') == shared_id]
            self.assertEqual(len(audit), 1)
            self.assertEqual(self.count(db, Sale), 0)

    def test_global_payment_uuid_collision_across_branches_collects_only_one_debt(self):
        first, _ = self.create(amount='100', branch=1)
        second, _ = self.create(amount='200', branch=2)
        shared_id = str(uuid.uuid4())
        requests = [(pc, f"/api/opening-debts/{debt['id']}/pay", {
            'request_id': shared_id, 'cash': debt['amount'], 'card': '0'})
            for pc, debt in zip((self.owner, self.client('boss')), (first, second))]
        results = self.concurrent_requests_after_empty_lookup('opening_debt_payments', shared_id, requests)
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        winner = next(r.json() for r in results if r.status_code == 201)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebt), 2)
            self.assertEqual(self.count(db, OpeningDebtPayment), 1)
            ledger = balances(db)
            self.assertEqual(ledger['cash'], Decimal(winner['amount']))
            self.assertEqual(ledger['card'], 0)
            self.assertEqual(ledger['customer_debt'] + ledger['cash'], 300)
            self.assertEqual(self.count(db, Sale), 0)
            self.assertEqual(self.count(db, SaleItem), 0)
            self.assertEqual(supplier_debt(db, 1)['earned'], 0)
            audit = [a for a in db.scalars(select(Audit))
                     if a.detail.get('payment', {}).get('request_id') == shared_id]
            self.assertEqual(len(audit), 1)
        debts = self.owner.get('/api/debts?status=all').json()['items']
        self.assertEqual(sorted(d['status'] for d in debts), ['open', 'paid'])

    def test_global_cancellation_uuid_collision_across_branches_unwinds_only_one_principal(self):
        first, _ = self.create(amount='100', branch=1)
        second, _ = self.create(amount='200', branch=2)
        shared_id = str(uuid.uuid4())
        bodies = [dict(self.cancel_body('opening_debt', debt['id']), request_id=shared_id)
                  for debt in (first, second)]
        requests = [(pc, f"/api/opening-debts/{debt['id']}/cancel", body)
            for pc, debt, body in zip((self.owner, self.client('boss')), (first, second), bodies)]
        results = self.concurrent_requests_after_empty_lookup('opening_debt_cancellations',
            shared_id, requests, id_projection_only=True)
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        marker = next(r.json()['cancellation'] for r in results if r.status_code == 200)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OpeningDebtCancellation), 1)
            self.assertEqual(self.count(db, OpeningDebt), 1)
            survivor = db.scalar(select(OpeningDebt))
            self.assertNotEqual(survivor.id, marker['operation_id'])
            self.assertEqual(balances(db)['customer_debt'], survivor.amount)
            self.assertEqual(balances(db)['cash'], 0)
            self.assertEqual(balances(db)['card'], 0)
            self.assertEqual(self.count(db, Sale), 0)
            self.assertEqual(self.count(db, SaleItem), 0)
            self.assertEqual(self.count(db, Debtor), 2)
            audit = [a for a in db.scalars(select(Audit))
                     if a.detail.get('opening_cancellation_id') == marker['id']]
            self.assertEqual(len(audit), 1)
            for branch in (1, 2):
                self.assertEqual(db.get(Stock, branch).kg, 10)

    def test_list_snapshot_survives_cancellation_or_payment_after_page_selection(self):
        other_operator = self.client('admin')
        for transition in ('cancel', 'pay'):
            with self.subTest(transition=transition):
                debt, _ = self.create(amount='300')
                cancellation_body = self.cancel_body('opening_debt', debt['id'])
                triggered = []

                def after_page(connection, cursor, statement, parameters, context, executemany):
                    normalized = ' '.join(statement.lower().split())
                    if triggered or 'union all' not in normalized or ' limit ' not in normalized:
                        return
                    # PostgreSQLdagi boshqa operator sahifa IDlari tanlangandan
                    # keyin amalni o'zgartiradi. Yangi ulanish darhol commit qiladi.
                    triggered.append(True)
                    if transition == 'cancel':
                        result = self.cancel('opening_debt', debt['id'],
                                             cancellation_body, other_operator)
                        self.assertEqual(result.status_code, 200, result.text)
                    else:
                        self.pay(debt, client=other_operator)

                event.listen(self.engine, 'after_cursor_execute', after_page)
                try:
                    response = self.owner.get('/api/debts?branch_id=1&status=open')
                finally:
                    event.remove(self.engine, 'after_cursor_execute', after_page)
                self.assertEqual(triggered, [True], 'Merged page query was not exercised.')
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertEqual(data['count'], 1)
                self.assertEqual(Decimal(data['amount']), 300)
                self.assertEqual(len(data['items']), 1)
                self.assertEqual(data['items'][0]['id'], debt['id'])
                self.assertEqual(data['items'][0]['status'], 'open')
                self.assertIsNone(data['items'][0]['payment'])
                fresh = self.owner.get('/api/debts?branch_id=1&status=open')
                self.assertEqual(fresh.status_code, 200, fresh.text)
                self.assertEqual(fresh.json()['count'], 0)
                self.assertEqual(fresh.json()['items'], [])


if __name__ == '__main__':
    unittest.main()
