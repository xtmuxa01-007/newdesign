"""Other cash handovers use only disposable fixture databases, never production."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import func, select

import test_branch_archive as fixture
import test_opening_debts as opening_fixture
from app.accounting import balances, supplier_debt
from app.models import (Audit, BranchExpense, DonationPayment, MiniDiscount, OpeningDebtPayment, OtherPayment,
                        Sale, SaleItem, Stock, SupplierPayment)
from app.operation_history import source_fingerprint
from app.routes_sync import SyncDevice
from app.shared_mode import SharedBranch


class OtherPaymentsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    debtor = opening_fixture.OpeningDebtsTest.debtor
    opening = opening_fixture.OpeningDebtsTest.create
    collect = opening_fixture.OpeningDebtsTest.pay

    def count(self, db, model):
        return db.scalar(select(func.count()).select_from(model))

    def funds(self, cash='1000', card='0', branch=1):
        debt, _ = self.opening(amount=str(Decimal(cash) + Decimal(card)), branch=branch)
        paid, _ = self.collect(debt, cash=cash, card=card)
        return paid

    def payload(self, amount='100', method='cash', branch=1, **changes):
        return {'request_id': str(uuid.uuid4()), 'branch_id': branch,
                'amount': amount, 'method': method, 'recipient': 'Marwa',
                'note': 'Oldingi qarzlardan undirilgan pul topshirildi.', **changes}

    def payout(self, body=None, client=None, expected=201, **changes):
        body = body or self.payload(**changes)
        result = (client or self.owner).post('/api/other-payments', json=body)
        self.assertEqual(result.status_code, expected, result.text)
        return result, body

    def cancel_payout(self, payment, body=None, expected=200, client=None):
        with self.sessions() as db:
            source = db.get(OtherPayment, payment['id'])
            if body is None:
                body = {'request_id': str(uuid.uuid4()), 'reason': 'Noto‘g‘ri topshirish fixture',
                        'expected_fingerprint': source_fingerprint(db, 'other_payment', source)}
        result = (client or self.owner).post(f"/api/operations/other_payment/{payment['id']}/cancel", json=body)
        self.assertEqual(result.status_code, expected, result.text)
        return result, body

    def listing(self, branch=1, **params):
        result = self.owner.get('/api/payments', params={'branch_id': branch, **params})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_expenses_twenty_row_pages_keep_branch_totals(self):
        with self.sessions() as db:
            for index in range(22):
                db.add(BranchExpense(request_id=str(uuid.uuid4()), branch_id=1 if index < 21 else 2,
                    supplier_id=1, user_id=4, amount=Decimal('10'), method='cash', reason='Pagination fixture'))
            db.commit()
        first = self.owner.get('/api/expenses?branch_id=1&limit=20').json()
        second = self.owner.get('/api/expenses?branch_id=1&limit=20&offset=20').json()
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 1)
        self.assertEqual(first['count'], 21)
        self.assertEqual(second['count'], 21)
        self.assertEqual(Decimal(first['amount']), Decimal('210'))
        self.assertEqual(first['amount'], second['amount'])
        self.assertFalse({p['id'] for p in first['items']} & {p['id'] for p in second['items']})
        self.assertEqual(self.owner.get('/api/expenses?branch_id=2&limit=20').json()['count'], 1)
        for limit in (0, 101):
            self.assertEqual(self.owner.get(f'/api/expenses?limit={limit}').status_code, 422)

    def test_sales_and_audit_support_small_pages_without_changing_totals(self):
        with self.sessions() as db:
            for index in range(21):
                db.add(Sale(request_id=str(uuid.uuid4()), branch_id=1, user_id=4,
                            total=Decimal('10'), cash=Decimal('10'), card=0, donation=0))
                db.add(Audit(branch_id=1, user_id=4, actor='Fixture', action='Pagination fixture', detail={}))
            db.commit()
        first = self.owner.get('/api/sales?branch_id=1&limit=20').json()
        second = self.owner.get('/api/sales?branch_id=1&limit=20&offset=20').json()
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 1)
        self.assertEqual(Decimal(first['total']), Decimal('210'))
        self.assertEqual(first['total'], second['total'])
        self.assertFalse({p['id'] for p in first['items']} & {p['id'] for p in second['items']})
        first = self.owner.get('/api/audit?branch_id=1&q=Pagination&limit=20').json()
        second = self.owner.get('/api/audit?branch_id=1&q=Pagination&limit=20&offset=20').json()
        self.assertEqual(len(first), 20)
        self.assertEqual(len(second), 1)
        self.assertFalse({p['id'] for p in first} & {p['id'] for p in second})
        for endpoint in ('sales', 'audit'):
            for limit in (0, 101):
                self.assertEqual(self.owner.get(f'/api/{endpoint}?limit={limit}').status_code, 422)

    def test_donation_and_mini_pages_have_independent_twenty_row_limits(self):
        with self.sessions() as db:
            for index in range(22):
                branch = 1 if index < 21 else 2
                sale = Sale(request_id=str(uuid.uuid4()), branch_id=branch, user_id=4,
                            total=Decimal('99'), cash=Decimal('99'), card=0, donation=0)
                db.add(sale)
                db.flush()
                db.add(MiniDiscount(sale_id=sale.id, branch_id=branch, user_id=4,
                                    original_total=Decimal('100'), amount=Decimal('1')))
                db.add(DonationPayment(request_id=str(uuid.uuid4()), branch_id=branch,
                    user_id=4, amount=Decimal('1'), method='cash', recipient='Fixture'))
            db.commit()
        first = self.listing(donations_limit=20)
        second = self.listing(donations_limit=20, offset=20)
        self.assertEqual(len(first['donations']), 20)
        self.assertEqual(len(second['donations']), 1)
        self.assertEqual(first['donations_count'], 21)
        self.assertEqual(second['donations_count'], 21)
        self.assertFalse({p['id'] for p in first['donations']} & {p['id'] for p in second['donations']})
        self.assertEqual(len(self.listing()['donations']), 21)
        self.assertEqual(self.listing(branch=2)['donations_count'], 1)
        first = self.owner.get('/api/mini-discounts?branch_id=1&limit=20').json()
        second = self.owner.get('/api/mini-discounts?branch_id=1&limit=20&offset=20').json()
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 1)
        self.assertEqual(first['count'], 21)
        self.assertEqual(second['count'], 21)
        self.assertEqual(Decimal(first['amount']), Decimal('21'))
        self.assertEqual(first['amount'], second['amount'])
        self.assertFalse({p['id'] for p in first['items']} & {p['id'] for p in second['items']})
        self.assertEqual(self.owner.get('/api/mini-discounts?branch_id=2&limit=20').json()['count'], 1)
        for limit in (0, 101):
            self.assertEqual(self.owner.get(f'/api/payments?donations_limit={limit}').status_code, 422)
            self.assertEqual(self.owner.get(f'/api/mini-discounts?limit={limit}').status_code, 422)

    def test_supplier_payment_pages_are_twenty_rows_with_scoped_totals(self):
        with self.sessions() as db:
            db.add_all([SupplierPayment(request_id=str(uuid.uuid4()), branch_id=1,
                supplier_id=1, user_id=4, amount=Decimal('1'), method='cash', recipient='Fixture')
                for _ in range(21)])
            db.add(SupplierPayment(request_id=str(uuid.uuid4()), branch_id=2,
                supplier_id=1, user_id=4, amount=Decimal('2'), method='cash', recipient='Fixture'))
            db.commit()
        first = self.listing(suppliers_limit=20)
        second = self.listing(suppliers_limit=20, offset=20)
        self.assertEqual(len(first['suppliers']), 20)
        self.assertEqual(len(second['suppliers']), 1)
        self.assertEqual(first['suppliers_count'], 21)
        self.assertEqual(second['suppliers_count'], 21)
        self.assertFalse({p['id'] for p in first['suppliers']} & {p['id'] for p in second['suppliers']})
        self.assertEqual(len(self.listing()['suppliers']), 21)
        self.assertEqual(self.listing(branch=2, suppliers_limit=20)['suppliers_count'], 1)
        for limit in (0, 101):
            self.assertEqual(self.owner.get(f'/api/payments?suppliers_limit={limit}').status_code, 422)

    def test_opening_debt_collections_can_be_handed_over_without_supplier_or_donation_limit(self):
        self.funds(cash='20000.75', card='15000.25')
        with self.sessions() as db:
            supplier_before = supplier_debt(db, 1, 1)
        first, _ = self.payout(amount='20000.75')
        second, _ = self.payout(amount='15000.25', method='card')
        self.assertTrue(first.json()['operation']['can_cancel'])
        self.assertEqual(second.json()['recipient'], 'Marwa')
        with self.sessions() as db:
            ledger = balances(db, 1)
            self.assertEqual(ledger['cash'], 0)
            self.assertEqual(ledger['card'], 0)
            self.assertEqual(ledger['customer_debt'], 0)
            self.assertEqual(ledger['donation_balance'], 0)
            self.assertEqual(supplier_debt(db, 1, 1), supplier_before)
            self.assertEqual(self.count(db, OtherPayment), 2)
            for model in (Sale, SaleItem, SupplierPayment, DonationPayment):
                self.assertEqual(self.count(db, model), 0)
            self.assertEqual(db.get(Stock, 1).kg, 10)
        data = self.listing()
        self.assertEqual(Decimal(data['other_paid']), Decimal('35001.00'))
        self.assertEqual(data['others_count'], 2)
        self.assertEqual(data['suppliers'], [])
        self.assertEqual(data['donations'], [])

    def test_existing_supplier_payable_is_unchanged_by_other_cash_handover(self):
        self.funds(cash='30000')
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        with self.sessions() as db:
            before = supplier_debt(db, 1, 1)
            self.assertEqual(before['debt'], 10000)
        supplier_capped = self.owner.post('/api/suppliers/1/payments', json=self.payload(amount='20000'))
        self.assertEqual(supplier_capped.status_code, 422, supplier_capped.text)
        donation_capped = self.owner.post('/api/donations/payments', json=self.payload(amount='15000.01'))
        self.assertEqual(donation_capped.status_code, 422, donation_capped.text)
        # This exceeds both the supplier's payable and the separate donation cap.
        self.payout(amount='30000')
        with self.sessions() as db:
            self.assertEqual(supplier_debt(db, 1, 1), before)
            self.assertEqual(balances(db, 1)['cash'], 10000)

    def test_invalid_amount_recipient_and_required_note_are_atomic(self):
        self.funds(cash='500.50', card='200.25')
        omitted_note = self.payload()
        del omitted_note['note']
        for body in (omitted_note, self.payload(amount='0'), self.payload(amount='-1'), self.payload(amount='1.001'),
                     self.payload(amount='NaN'), self.payload(amount='Infinity'),
                     self.payload(amount='1 000'), self.payload(amount='1000000000000'),
                     self.payload(recipient=' '), self.payload(method='other'), self.payload(supplier_id=1),
                     self.payload(note=''), self.payload(note='ab'), self.payload(note='   '),
                     self.payload(note='x' * 501)):
            with self.subTest(body=body):
                self.payout(body, expected=422)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OtherPayment), 0)
            self.assertEqual(balances(db, 1)['cash'], Decimal('500.50'))
            self.assertEqual(balances(db, 1)['card'], Decimal('200.25'))
        self.payout(amount='500.50')
        self.payout(amount='200.25', method='card')

    def test_other_money_can_exceed_recorded_cash_or_card_and_records_the_full_difference(self):
        self.funds(cash='500.50', card='200.25')
        first, first_body = self.payout(amount='1000')
        second, second_body = self.payout(amount='700', method='card')
        third, third_body = self.payout(amount='10')
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], Decimal('-509.50'))
            self.assertEqual(balances(db, 1)['card'], Decimal('-499.75'))
            self.assertEqual(balances(db, 1)['customer_debt'], 0)
            self.assertEqual(supplier_debt(db, 1, 1)['paid'], 0)
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 0)
            for body, before, after, unrecorded in (
                    (first_body, '500.50', '-499.50', '499.50'),
                    (second_body, '200.25', '-499.75', '499.75'),
                    (third_body, '-499.50', '-509.50', '10.00')):
                entry = next(row for row in db.scalars(select(Audit))
                             if row.detail.get('request_id') == body['request_id'])
                self.assertEqual(Decimal(entry.detail['balance_before']), Decimal(before))
                self.assertEqual(Decimal(entry.detail['balance_after']), Decimal(after))
                self.assertEqual(Decimal(entry.detail['unrecorded_amount']), Decimal(unrecorded))
        self.assertEqual(Decimal(self.listing()['other_paid']), 1710)

    def test_supplier_is_paid_first_then_other_cash_is_recorded_without_fake_income(self):
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        supplier = self.owner.post('/api/suppliers/1/payments', json=self.payload(amount='10000'))
        self.assertEqual(supplier.status_code, 201, supplier.text)
        self.payout(amount='10000')
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], -10000)
            supplier_values = supplier_debt(db, 1, 1)
            self.assertEqual(supplier_values['earned'], 10000)
            self.assertEqual(supplier_values['paid'], 10000)
            self.assertEqual(supplier_values['debt'], 0)
            self.assertEqual(self.count(db, Sale), 1)
            self.assertEqual(self.count(db, OpeningDebtPayment), 0)
            self.assertEqual(self.count(db, OtherPayment), 1)

    def test_roles_branch_and_archived_branch_scope(self):
        self.funds(branch=1)
        self.funds(branch=2)
        body = self.payload()
        self.payout(body, client=self.server, expected=401)
        self.payout(body, client=self.client('cashier'), expected=403)
        admin = self.client('admin')
        self.payout(self.payload(branch=2), client=admin, expected=403)
        self.payout(self.payload(branch=9999), expected=404)
        self.payout(self.payload(), client=admin)
        self.assertEqual(admin.get('/api/payments?branch_id=2').status_code, 403)
        archived = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(archived.status_code, 200, archived.text)
        self.payout(self.payload(), expected=409)
        self.assertEqual(self.listing()['others_count'], 1)

    def test_replay_normalizes_decimals_and_rejects_changed_payload_actor_or_branch(self):
        self.funds(cash='1000')
        self.funds(cash='1000', branch=2)
        body = self.payload(amount='123.40', recipient='  Marwa  ', note='  Topshirildi  ')
        first, _ = self.payout(body)
        retry, _ = self.payout({**body, 'amount': '123.4', 'recipient': 'Marwa', 'note': 'Topshirildi'})
        self.assertEqual(first.json()['id'], retry.json()['id'])
        for changes in ({'amount': '123.41'}, {'recipient': 'Other'}, {'note': 'Other'},
                        {'method': 'card'}, {'branch_id': 2}):
            self.payout({**body, **changes}, expected=409)
        self.payout(body, client=self.client('boss'), expected=409)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OtherPayment), 1)
            self.assertEqual(balances(db, 1)['cash'], Decimal('876.60'))
            self.assertEqual(balances(db, 2)['cash'], 1000)
            entries = [row for row in db.scalars(select(Audit)) if row.detail.get('request_id') == body['request_id']]
            self.assertEqual(len(entries), 1)

    def test_cancellation_restores_money_once_and_keeps_immutable_audit_and_retry_guard(self):
        self.funds(cash='800.25')
        payment, body = self.payout(amount='500.15')
        payment = payment.json()
        self.cancel_payout(payment, expected=403, client=self.client('cashier'))
        result, cancellation = self.cancel_payout(payment)
        duplicate, _ = self.cancel_payout(payment, body=cancellation)
        self.assertEqual(result.json()['cancellation']['id'], duplicate.json()['cancellation']['id'])
        self.payout(body, expected=409)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], Decimal('800.25'))
            self.assertEqual(self.count(db, OtherPayment), 0)
        data = self.listing()
        self.assertEqual(data['others_count'], 0)
        self.assertEqual(Decimal(data['other_paid']), 0)
        history = self.owner.get('/api/audit?branch_id=1').json()
        linked = [item['operation'] for item in history if item.get('operation') and
                  item['operation']['kind'] == 'other_payment' and item['operation']['id'] == payment['id']]
        self.assertTrue(linked)
        self.assertTrue(all(item['cancelled'] and not item['can_cancel'] for item in linked))

    def test_handed_over_opening_debt_receipt_cannot_be_cancelled_until_cash_is_restored(self):
        debt = self.funds(cash='1000')
        payment = debt['payment']
        handed_over, _ = self.payout(amount='1500')
        body = opening_fixture.OpeningDebtsTest.cancel_body(self, 'opening_debt_payment', payment['id'])
        path = f"/api/opening-debts/payments/{payment['id']}/cancel"
        blocked = self.owner.post(path, json=body)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(OpeningDebtPayment, payment['id']))
            self.assertEqual(balances(db, 1)['cash'], -500)
        self.cancel_payout(handed_over.json())
        cancelled = self.owner.post(path, json=body)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        with self.sessions() as db:
            self.assertIsNone(db.get(OpeningDebtPayment, payment['id']))
            self.assertEqual(balances(db, 1)['cash'], 0)
            self.assertEqual(balances(db, 1)['customer_debt'], 1000)

    def test_history_totals_and_others_pagination_are_branch_scoped_and_independent(self):
        self.funds(cash='200')
        self.funds(cash='50', branch=2)
        with self.sessions() as db:
            db.add_all([OtherPayment(request_id=str(uuid.uuid4()), branch_id=1,
                user_id=4, amount=Decimal('1.25'), method='cash', recipient='Marwa', note='Fixture page')
                for _ in range(101)])
            db.add(OtherPayment(request_id=str(uuid.uuid4()), branch_id=2,
                user_id=4, amount=Decimal('7.50'), method='cash', recipient='Other branch', note='Fixture'))
            db.commit()
        first = self.listing(offset=100, others_offset=0)
        second = self.listing(offset=0, others_offset=100)
        self.assertEqual(len(first['others']), 100)
        self.assertEqual(len(second['others']), 1)
        self.assertEqual(first['others_count'], 101)
        self.assertEqual(second['others_count'], 101)
        self.assertEqual(Decimal(first['other_paid']), Decimal('126.25'))
        self.assertEqual(first['other_paid'], second['other_paid'])
        self.assertTrue(first['others'][0]['operation']['can_cancel'])
        self.assertEqual(first['others'][0]['actor'], 'Programmist')
        self.assertEqual(self.listing(branch=2)['others_count'], 1)
        self.assertEqual(Decimal(self.listing(branch=2)['other_paid']), Decimal('7.50'))
        self.assertEqual(self.owner.get('/api/payments?others_offset=-1').status_code, 422)
        small_first = self.listing(others_limit=20)
        small_second = self.listing(others_limit=20, others_offset=20)
        small_last = self.listing(others_limit=20, others_offset=100)
        self.assertEqual(len(small_first['others']), 20)
        self.assertEqual(len(small_second['others']), 20)
        self.assertEqual(len(small_last['others']), 1)
        self.assertEqual(small_first['others_count'], 101)
        self.assertEqual(small_first['other_paid'], first['other_paid'])
        self.assertFalse({p['id'] for p in small_first['others']} & {p['id'] for p in small_second['others']})
        for limit in (0, 101):
            self.assertEqual(self.owner.get(f'/api/payments?others_limit={limit}').status_code, 422)

    def test_legacy_local_and_untransitioned_offline_branch_are_rejected(self):
        self.funds()
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1', 'CRM_OFFLINE_V3': '1'}):
            self.payout(expected=409)
        device_id = str(uuid.uuid4())
        with self.sessions() as db:
            db.add(SyncDevice(id=device_id, branch_id=1, name='Legacy fixture',
                              token_digest='a' * 64, active=True))
            db.commit()
        self.payout(expected=409)
        with self.sessions() as db:
            db.add(SharedBranch(branch_id=1, device_id=device_id, received_sequence=0, last_digest=None))
            db.commit()
        self.payout()

    def test_parallel_distinct_handovers_both_record_full_outflow_even_beyond_cash(self):
        self.funds(cash='1000')
        second = self.client()
        login = second.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        bodies = [self.payload(amount='700'), self.payload(amount='700')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: pair[0].post('/api/other-payments', json=pair[1]),
                                    zip((self.owner, second), bodies)))
        self.assertEqual([result.status_code for result in results], [201, 201])
        with self.sessions() as db:
            self.assertEqual(self.count(db, OtherPayment), 2)
            self.assertEqual(balances(db, 1)['cash'], -400)

    def test_parallel_same_request_is_recorded_only_once(self):
        self.funds(cash='1000')
        second = self.client()
        login = second.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        body = self.payload(amount='700')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: client.post('/api/other-payments', json=body), (self.owner, second)))
        self.assertEqual([result.status_code for result in results], [201, 201])
        self.assertEqual(results[0].json()['id'], results[1].json()['id'])
        with self.sessions() as db:
            self.assertEqual(self.count(db, OtherPayment), 1)
            self.assertEqual(balances(db, 1)['cash'], 300)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class OtherPaymentsPostgresTest(OtherPaymentsTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
