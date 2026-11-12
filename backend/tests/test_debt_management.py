"""Only disposable databases: receipt, schedule and correction safety regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import os
from threading import Barrier
import unittest
from unittest.mock import patch
import uuid

from openpyxl import load_workbook
from sqlalchemy import event, func, inspect, select

import test_branch_archive as fixture
import test_operation_cancel as cancellation_fixture
from app.accounting import balances, supplier_debt
from app.common import row
from app.db import Base
from app.models import (Audit, BranchExpense, Debtor, Debt, DebtInstallment, DebtPayment,
                        DebtRevision, OpeningDebt, OpeningDebtPayment, Sale,
                        SaleItem, Stock)
from app.routes_debts import today
from app.routes_sync import InboxEvent, SyncDevice
from app.sync_projection import remember


class DebtManagementTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    cancellation_payload = cancellation_fixture.OperationCancelTest.payload

    def debtor(self, branch=1, **changes):
        result = self.owner.post('/api/debtors', json={'branch_id': branch,
            'first_name': 'Debt', 'last_name': 'Fixture', 'phone1': '+998900000001',
            'phone2': '+998900000002', 'address': 'Fixture address', **changes})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def create(self, origin='opening', amount='1000', branch=1, due=None):
        debtor = self.debtor(branch)
        due = due or (today() + timedelta(days=20)).isoformat()
        if origin == 'opening':
            result = self.owner.post('/api/opening-debts', json=dict(
                request_id=str(uuid.uuid4()), branch_id=branch, debtor_id=debtor['id'],
                amount=amount, due_date=due, note='Original fixture'))
        else:
            result = self.owner.post('/api/sales', json={**self.sale(), 'branch_id': branch,
                'cash': str(Decimal('10000') - Decimal(amount)),
                'debtor_id': debtor['id'], 'due_date': due})
        self.assertEqual(result.status_code, 201, result.text)
        debt = result.json() if origin == 'opening' else result.json()['debt']
        return self.current(origin, debt['id'])

    def current(self, origin, debt_id):
        response = self.owner.get('/api/debts?status=all')
        self.assertEqual(response.status_code, 200, response.text)
        return next(d for d in response.json()['items'] if d['origin'] == origin and d['id'] == debt_id)

    def path(self, debt, action):
        resource = 'opening-debts' if debt['origin'] == 'opening' else 'debts'
        return f"/api/{resource}/{debt['id']}/{action}"

    def pay(self, debt, cash='0', card='0', client=None, expected=201, **changes):
        body = dict(request_id=str(uuid.uuid4()), cash=cash, card=card, **changes)
        response = (client or self.owner).post(self.path(debt, 'pay'), json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response, body

    def revise(self, debt, client=None, expected=200, **changes):
        body = dict(request_id=str(uuid.uuid4()), reason='Fixture correction',
                    expected_fingerprint=debt['management']['expected_fingerprint'], **changes)
        response = (client or self.owner).post(self.path(debt, 'revise'), json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response, body

    def cancel_receipt(self, payment, client=None, expected=200, body=None):
        body = body or dict(request_id=str(uuid.uuid4()), reason='Incorrect receipt fixture',
                            expected_fingerprint=payment['operation']['expected_fingerprint'])
        response = (client or self.owner).post(f"/api/debt-installments/{payment['id']}/cancel", json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response, body

    def amounts(self, debt, principal, paid, remaining):
        for name, value in (('amount', principal), ('paid_amount', paid), ('remaining_amount', remaining)):
            self.assertEqual(Decimal(debt[name]), Decimal(str(value)), name)

    def ledger(self, debt, cash, card, stock='10', donation='0'):
        with self.sessions() as db:
            values = balances(db, 1)
            self.assertEqual(values['customer_debt'], Decimal(str(debt)))
            self.assertEqual(values['cash'], Decimal(str(cash)))
            self.assertEqual(values['card'], Decimal(str(card)))
            self.assertEqual(values['donation_received'], Decimal(str(donation)))
            self.assertEqual(db.get(Stock, 1).kg, Decimal(str(stock)))

    def test_search_filters_both_origins_before_pagination_and_totals(self):
        debts = [self.create(amount='100'), self.create(origin='sale', amount='200'),
                 self.create(amount='300', branch=2)]
        with self.sessions() as db:
            for index, debt in enumerate(debts):
                person = db.get(Debtor, debt['debtor_id'])
                person.first_name = 'Dilshod' if index != 1 else 'Akmal'
                person.last_name = 'Karimov'
                person.phone1 = '+998 (90) 123-45-67' if index == 0 else '+998901111111'
                person.phone2 = '+998 93 765 43 21' if index == 1 else ''
            db.commit()
        result = self.owner.get('/api/debts', params={'q': 'KARIMOV', 'limit': 1, 'offset': 1}).json()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['count'], 3)
        self.assertEqual(Decimal(result['amount']), Decimal('600'))
        result = self.owner.get('/api/debts', params={'q': 'Karimov Dilshod', 'branch_id': 1}).json()
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['items'][0]['id'], debts[0]['id'])
        for phone, origin in (('+998901234567', 'opening'), ('93 765-43-21', 'sale')):
            result = self.owner.get('/api/debts', params={'q': phone}).json()
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['items'][0]['origin'], origin)
        result = self.owner.get('/api/debts', params={'q': '%'}).json()
        self.assertEqual(result['items'], [])
        self.assertEqual(result['count'], 0)
        self.assertEqual(Decimal(result['amount']), 0)

    def test_custom_page_size_preserves_totals_and_page_boundaries(self):
        for amount in ('100', '200', '300'):
            self.create(amount=amount, due=today().isoformat())
        first = self.owner.get('/api/debts?limit=2').json()
        second = self.owner.get('/api/debts?limit=2&offset=2').json()
        self.assertEqual(len(first['items']), 2)
        self.assertEqual(len(second['items']), 1)
        self.assertEqual(first['count'], 3)
        self.assertEqual(second['count'], 3)
        self.assertEqual(Decimal(first['amount']), Decimal('600'))
        self.assertEqual(first['amount'], second['amount'])
        first_ids = {(d['origin'], d['id']) for d in first['items']}
        second_ids = {(d['origin'], d['id']) for d in second['items']}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(len(self.owner.get('/api/notifications/debts').json()['items']), 3)
        for limit in (0, 101):
            self.assertEqual(self.owner.get(f'/api/debts?limit={limit}').status_code, 422)

    def test_early_partial_and_overdue_partial_update_only_actual_receipts(self):
        early = self.create(amount='1000')
        late = self.create(amount='2000', due=(today() - timedelta(days=5)).isoformat())
        self.pay(early, cash='200', card='100', client=self.client('cashier'))
        self.pay(late, cash='250', card='50')
        self.amounts(self.current('opening', early['id']), 1000, 300, 700)
        current = self.current('opening', late['id'])
        self.amounts(current, 2000, 300, 1700)
        self.assertTrue(current['overdue'])
        notifications = self.client('cashier').get('/api/notifications/debts').json()
        self.assertEqual(notifications['count'], 1)
        self.assertEqual(Decimal(notifications['amount']), 1700)
        self.ledger(2400, 450, 150)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 0)
            self.assertEqual(supplier_debt(db, 1, 1)['earned'], 0)

    def test_partial_with_new_date_is_atomic_and_closure_cannot_overpay(self):
        debt = self.create(due=(today() - timedelta(days=2)).isoformat())
        new_day = (today() + timedelta(days=30)).isoformat()
        self.pay(debt, cash='300', next_due_date=new_day)
        current = self.current('opening', debt['id'])
        self.amounts(current, 1000, 300, 700)
        self.assertEqual(current['due_date'], new_day)
        self.assertFalse(current['overdue'])
        self.assertEqual(len(current['revisions']), 1)
        self.pay(current, cash='701', expected=422)
        self.pay(current, cash='700', next_due_date=new_day, expected=422)
        self.ledger(700, 300, 0)
        self.pay(current, cash='500', card='200')
        closed = self.current('opening', debt['id'])
        self.amounts(closed, 1000, 1000, 0)
        self.assertEqual(closed['status'], 'paid')
        self.assertEqual(len(closed['payments']), 2)
        self.pay(closed, cash='1', expected=409)
        self.ledger(0, 800, 200)
        self.assertEqual(self.owner.get('/api/debts?status=open').json()['count'], 0)

    def test_reschedule_without_payment_preserves_all_financial_rows_and_old_date(self):
        debt = self.create(due=(today() - timedelta(days=1)).isoformat())
        with self.sessions() as db:
            before = (balances(db, 1), row(db.get(OpeningDebt, debt['id'])))
        new_day = (today() + timedelta(days=11)).isoformat()
        response, body = self.revise(debt, due_date=new_day)
        current = response.json()
        self.amounts(current, 1000, 0, 1000)
        self.assertEqual(current['revisions'][0]['before']['due_date'], debt['due_date'])
        self.assertEqual(current['revisions'][0]['after']['due_date'], new_day)
        retry = self.owner.post(self.path(debt, 'revise'), json=body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(len(retry.json()['revisions']), 1)
        self.revise(debt, due_date=(today() + timedelta(days=12)).isoformat(), expected=409)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1), before[0])
            source = row(db.get(OpeningDebt, debt['id']))
            self.assertEqual({k:v for k,v in source.items() if k != 'due_date'},
                             {k:v for k,v in before[1].items() if k != 'due_date'})
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtInstallment)), 0)

    def test_principal_customer_note_corrections_cannot_go_below_already_collected(self):
        debt = self.create()
        self.pay(debt, cash='300')
        current = self.current('opening', debt['id'])
        self.revise(current, amount='299.99', expected=422)
        other = self.debtor(first_name='Correct')
        response, _ = self.revise(current, amount='900', debtor_id=other['id'], note='Corrected original')
        changed = response.json()
        self.amounts(changed, 900, 300, 600)
        self.assertEqual(changed['debtor_id'], other['id'])
        self.assertEqual(changed['note'], 'Corrected original')
        self.assertEqual(len(changed['payments']), 1)
        self.ledger(600, 300, 0)
        self.revise(changed, amount='300')
        self.assertEqual(self.current('opening', debt['id'])['status'], 'paid')
        self.ledger(0, 300, 0)

    def test_legacy_full_payment_is_preserved_and_increased_principal_counts_both_sources(self):
        debt = self.create(amount='1000')
        self.pay(debt, cash='600', card='400')
        paid = self.current('opening', debt['id'])
        with self.sessions() as db:
            original = row(db.get(OpeningDebtPayment, paid['payment']['id']))
        increased, _ = self.revise(paid, amount='1500')
        self.amounts(increased.json(), 1500, 1000, 500)
        self.pay(increased.json(), cash='500.01', expected=422)
        self.pay(increased.json(), cash='250', card='250')
        closed = self.current('opening', debt['id'])
        self.amounts(closed, 1500, 1500, 0)
        self.assertEqual(len(closed['payments']), 2)
        with self.sessions() as db:
            self.assertEqual(row(db.get(OpeningDebtPayment, original['id'])), original)
        self.ledger(0, 850, 650)

    def test_cancel_receipt_reopens_debt_preserves_data_and_rejects_cancelled_retry(self):
        debt = self.create()
        _, first_body = self.pay(debt, cash='300')
        self.pay(debt, cash='700')
        closed = self.current('opening', debt['id'])
        first = next(p for p in closed['payments'] if p['request_id'] == first_body['request_id'])
        _, cancellation = self.cancel_receipt(first)
        reopened = self.current('opening', debt['id'])
        self.amounts(reopened, 1000, 700, 300)
        self.assertEqual(len(reopened['payments']), 2)
        self.assertTrue(next(p for p in reopened['payments'] if p['id'] == first['id'])['cancelled'])
        self.cancel_receipt(first, body=cancellation)
        response = self.owner.post(self.path(debt, 'pay'), json=first_body)
        self.assertEqual(response.status_code, 409, response.text)
        self.cancel_receipt(first, body=dict(cancellation, reason='Changed'), expected=409)
        self.ledger(300, 700, 0)
        audit = self.owner.get('/api/audit?branch_id=1').json()
        linked = [a for a in audit if (a.get('operation') or {}).get('kind') == 'debt_installment'
                  and a['operation']['id'] == first['id']]
        self.assertEqual(len(linked), 2)
        self.assertTrue(all(a['operation']['cancelled'] for a in linked))

    def test_payment_retry_cannot_change_date_amount_actor_or_origin(self):
        opening = self.create()
        sale = self.create('sale', amount='1000')
        due = (today() + timedelta(days=30)).isoformat()
        _, body = self.pay(opening, cash='100', card='200', next_due_date=due)
        with patch('app.debt_management.today', return_value=today() + timedelta(days=45)):
            retry = self.owner.post(self.path(opening, 'pay'), json=body)
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual(retry.json()['due_date'], due)
        for changed in (dict(body, cash='101'), dict(body, next_due_date=None),
                        dict(body, next_due_date=(today()+timedelta(days=40)).isoformat())):
            self.assertEqual(self.owner.post(self.path(opening, 'pay'), json=changed).status_code, 409)
        self.assertEqual(self.client('admin').post(self.path(opening, 'pay'), json=body).status_code, 409)
        self.assertEqual(self.owner.post(self.path(sale, 'pay'), json=body).status_code, 409)
        self.ledger(1700, 9100, 200, stock=9)

    def test_scope_archived_branch_and_roles_guard_date_and_cancellation(self):
        debt = self.create()
        other = self.create(branch=2)
        cashier = self.client('cashier')
        self.pay(other, cash='100', client=cashier, expected=403)
        self.revise(debt, due_date=(today()+timedelta(days=30)).isoformat(), client=cashier, expected=403)
        self.pay(debt, cash='100', next_due_date=(today()+timedelta(days=30)).isoformat(), client=cashier, expected=403)
        self.pay(debt, cash='100', client=cashier)
        payment = self.current('opening', debt['id'])['payments'][0]
        self.cancel_receipt(payment, client=cashier, expected=403)
        archived = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(archived.status_code, 200, archived.text)
        current = self.current('opening', debt['id'])
        self.assertFalse(current['management']['can_revise'])
        self.assertFalse(current['payments'][0]['operation']['can_cancel'])
        self.pay(debt, cash='100', expected=409)
        self.revise(current, due_date=(today()+timedelta(days=30)).isoformat(), expected=409)
        self.cancel_receipt(payment, expected=409)
        self.ledger(900, 100, 0)

    def test_bad_dates_zero_or_fractional_payments_leave_no_receipts_or_revisions(self):
        debt = self.create()
        for fields in (dict(cash='0'), dict(cash='-1'), dict(cash='NaN'), dict(cash='1.001'),
                       dict(cash='50', next_due_date='2026-02-30'),
                       dict(cash='50', next_due_date=(today()-timedelta(days=1)).isoformat())):
            self.pay(debt, expected=422, **fields)
        self.revise(debt, due_date=(today()-timedelta(days=1)).isoformat(), expected=422)
        self.revise(debt, expected=422)
        self.ledger(1000, 0, 0)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtInstallment)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtRevision)), 0)

    def test_cancellation_refuses_to_remove_money_already_spent_and_rolls_back(self):
        sold = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(sold.status_code, 201, sold.text)
        debt = self.create()
        self.pay(debt, card='300')
        expense = self.owner.post('/api/expenses', json=dict(request_id=str(uuid.uuid4()), branch_id=1,
            supplier_id=1, amount='300', method='card', reason='Fixture card spend'))
        self.assertEqual(expense.status_code, 201, expense.text)
        self.cancel_receipt(self.current('opening', debt['id'])['payments'][0], expected=409)
        current = self.current('opening', debt['id'])
        self.amounts(current, 1000, 300, 700)
        self.assertFalse(current['payments'][0]['cancelled'])
        self.ledger(700, 10000, 0, stock=9)

    def test_sale_receipts_do_not_change_stock_donation_goods_or_supplier_earned(self):
        ordinary = self.owner.post('/api/sales', json={**self.sale(), 'cash': '11000'})
        self.assertEqual(ordinary.status_code, 201, ordinary.text)
        debt = self.create('sale', amount='8000')
        with self.sessions() as db:
            before = row(db.get(Sale, debt['sale_id']))
            earned = supplier_debt(db, 1, 1)['earned']
        self.pay(debt, cash='1000', card='2000')
        self.pay(debt, cash='2500', card='2500')
        self.amounts(self.current('sale', debt['id']), 8000, 8000, 0)
        self.ledger(0, 16500, 4500, stock=8, donation=1000)
        with self.sessions() as db:
            self.assertEqual(row(db.get(Sale, debt['sale_id'])), before)
            self.assertEqual(supplier_debt(db, 1, 1)['earned'], earned)

    def test_active_receipt_blocks_sale_edit_cancel_until_payment_cancelled(self):
        debt = self.create('sale', amount='8000')
        stale_cancel = self.cancellation_payload('sale', debt['sale_id'])
        self.pay(debt, cash='2000')
        with self.sessions() as db:
            item = db.scalar(select(SaleItem).where(SaleItem.sale_id == debt['sale_id']))
            item_id = item.id
        edit = dict(request_id=str(uuid.uuid4()), version=0, reason='Fixture sale correction',
            customer='Corrected customer', cash='2000', card='0', items=[dict(item_id=item_id,
                product_id=1, kg='0.9', price='10000', discount='0')])
        self.assertEqual(self.owner.post(f"/api/sales/{debt['sale_id']}/edit", json=edit).status_code, 409)
        self.assertEqual(self.owner.post(f"/api/operations/sale/{debt['sale_id']}/cancel", json=stale_cancel).status_code, 409)
        current_cancel = self.cancellation_payload('sale', debt['sale_id'])
        self.assertEqual(self.owner.post(f"/api/operations/sale/{debt['sale_id']}/cancel", json=current_cancel).status_code, 409)
        self.ledger(6000, 4000, 0, stock=9)
        self.cancel_receipt(self.current('sale', debt['id'])['payments'][0])
        fixed = self.owner.post(f"/api/sales/{debt['sale_id']}/edit", json=edit)
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.amounts(self.current('sale', debt['id']), 7000, 0, 7000)
        self.ledger(7000, 2000, 0, stock='9.1')

    def test_cancelled_history_cannot_attach_to_reused_legacy_debt_id(self):
        debt = self.create('sale', amount='8000')
        self.pay(debt, cash='1000', next_due_date=(today()+timedelta(days=35)).isoformat())
        current = self.current('sale', debt['id'])
        receipt = current['payments'][0]
        self.cancel_receipt(receipt)
        result = self.owner.post(f"/api/operations/sale/{debt['sale_id']}/cancel",
            json=self.cancellation_payload('sale', debt['sale_id']))
        self.assertEqual(result.status_code, 200, result.text)
        new = self.create('sale', amount='5000')
        if not getattr(self, 'postgres', False):
            self.assertEqual(new['id'], debt['id'], 'Exercise legacy SQLite ID reuse')
        self.amounts(new, 5000, 0, 5000)
        self.assertEqual(new['payments'], [])
        self.assertEqual(new['revisions'], [])
        with self.sessions() as db:
            self.assertIsNotNone(db.get(DebtInstallment, receipt['id']))
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtRevision)), 1)
        self.ledger(5000, 5000, 0, stock=9)

    def test_analytics_and_excel_count_multiple_receipts_once_with_correct_dates(self):
        debt = self.create('sale', amount='8000')
        self.pay(debt, cash='1000', card='1000')
        self.pay(debt, cash='1000')
        opening = self.create(amount='500')
        self.pay(opening, card='100')
        day = today().isoformat()
        query = f'?branch_id=1&start={day}&end={day}'
        data = self.owner.get('/api/sales/analytics'+query).json()
        summary = data['summary']
        self.assertEqual(summary['sales_count'], 1)
        for key, value in dict(goods_total=10000, debt_created=8000, debt_outstanding=5000,
                               debt_collected=3100, period_inflow=5100, kg=1).items():
            self.assertEqual(Decimal(summary[key]), value, key)
        workbook = load_workbook(BytesIO(self.owner.get('/api/sales/export.xlsx'+query).content))
        self.assertEqual(workbook['Savdolar']['I2'].value, 3000)
        self.assertEqual(workbook['Savdolar']['L2'].value, 5000)
        self.assertEqual(workbook['Savdolar']['N2'].value, 8000)
        self.assertEqual(workbook['Qarz to‘lovlari'].max_row, 3)
        self.cancel_receipt(self.current('sale', debt['id'])['payments'][0])
        changed = self.owner.get('/api/sales/analytics'+query).json()['summary']
        self.assertEqual(Decimal(changed['debt_collected']), 1100)
        self.assertEqual(Decimal(changed['debt_outstanding']), 7000)
        workbook = load_workbook(BytesIO(self.owner.get('/api/sales/export.xlsx'+query).content))
        self.assertEqual(workbook['Qarz to‘lovlari'].max_row, 3)
        self.assertEqual(workbook['Qarz to‘lovlari']['J2'].value, 'Bekor qilingan')

    def test_parallel_partial_payments_cannot_exceed_remaining_debt(self):
        debt = self.create()
        clients = self.client('cashier'), self.client('cashier')
        bodies = [dict(request_id=str(uuid.uuid4()), cash='600', card='0') for _ in clients]
        start = Barrier(2)
        def submit(args):
            start.wait(timeout=15)
            return args[0].post(self.path(debt, 'pay'), json=args[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, zip(clients, bodies)))
        self.assertEqual(sorted(r.status_code for r in responses), [201, 422])
        self.amounts(self.current('opening', debt['id']), 1000, 600, 400)
        self.ledger(400, 600, 0)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtInstallment)), 1)

    def test_parallel_same_partial_request_returns_one_receipt_and_one_audit(self):
        debt = self.create()
        clients = self.client('cashier'), self.client('cashier')
        body = dict(request_id=str(uuid.uuid4()), cash='300', card='100')
        start = Barrier(2)
        def submit(client):
            start.wait(timeout=15)
            return client.post(self.path(debt, 'pay'), json=body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, clients))
        self.assertEqual([r.status_code for r in responses], [201, 201])
        self.amounts(self.current('opening', debt['id']), 1000, 400, 600)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtInstallment)), 1)
            audits = [a for a in db.scalars(select(Audit)) if a.detail.get('request_id') == body['request_id']]
            self.assertEqual(len(audits), 1)
        self.ledger(600, 300, 100)

    def test_installment_collection_uses_receipt_day_even_when_sale_is_outside_period(self):
        debt = self.create('sale', amount='8000')
        opening = self.create(amount='1000')
        self.pay(debt, cash='1000')
        self.pay(debt, cash='1000')
        self.pay(opening, card='100')
        payment_day = today() + timedelta(days=2)
        with self.sessions() as db:
            payments = list(db.scalars(select(DebtInstallment).order_by(DebtInstallment.id)))
            payments[0].created_at = datetime.combine(payment_day, datetime.min.time(), timezone.utc)
            payments[1].created_at = datetime.combine(payment_day + timedelta(days=1), datetime.min.time(), timezone.utc)
            payments[2].created_at = datetime.combine(payment_day, datetime.min.time(), timezone.utc)
            db.commit()
        response = self.owner.get(f'/api/sales/analytics?start={payment_day}&end={payment_day}&branch_id=1')
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()['summary']
        self.assertEqual(summary['sales_count'], 0)
        self.assertEqual(Decimal(summary['goods_total']), 0)
        self.assertEqual(Decimal(summary['debt_collected']), 1100)
        self.assertEqual(Decimal(summary['period_inflow']), 1100)

    def test_additive_schema_creation_preserves_existing_principal_receipts_and_unique_keys(self):
        opening = self.create()
        self.pay(opening, cash='1000')
        sale = self.create('sale', amount='8000')
        self.pay(sale, cash='8000')
        watched = (Sale, SaleItem, Debt, DebtPayment, OpeningDebt, OpeningDebtPayment)
        def snapshot():
            with self.sessions() as db:
                return {model.__tablename__: [row(v) for v in db.scalars(select(model).order_by(model.id))]
                        for model in watched}
        before = snapshot()
        old_constraints = {model.__tablename__: inspect(self.engine).get_unique_constraints(model.__tablename__)
                           for model in watched}
        # This fixture owns a fresh disposable DB/schema, never production.
        DebtRevision.__table__.drop(self.engine)
        DebtInstallment.__table__.drop(self.engine)
        statements = []
        def observe(connection, cursor, statement, *args):
            statements.append(statement.strip().upper())
        event.listen(self.engine, 'before_cursor_execute', observe)
        try:
            Base.metadata.create_all(self.engine)
        finally:
            event.remove(self.engine, 'before_cursor_execute', observe)
        self.assertEqual(snapshot(), before)
        for model in watched:
            self.assertEqual(inspect(self.engine).get_unique_constraints(model.__tablename__),
                             old_constraints[model.__tablename__])
        self.assertFalse(any(s.startswith(('ALTER ', 'DROP ', 'DELETE ', 'UPDATE ')) for s in statements))
        self.ledger(0, 11000, 0, stock=9)

    def test_stale_payment_after_schedule_change_is_rejected_but_exact_ack_retry_survives(self):
        cashier = self.client('cashier')
        for origin in ('opening', 'sale'):
            with self.subTest(origin=origin):
                debt = self.create(origin)
                stale = debt['management']['expected_fingerprint']
                revised, _ = self.revise(debt, due_date=(today()+timedelta(days=25)).isoformat())
                self.pay(debt, cash='100', client=cashier, expected_fingerprint=stale, expected=409)
                current = revised.json()
                self.amounts(current, 1000, 0, 1000)
                _, body = self.pay(current, cash='100', client=cashier,
                                   expected_fingerprint=current['management']['expected_fingerprint'])
                after_payment = self.current(origin, debt['id'])
                self.revise(after_payment, due_date=(today()+timedelta(days=30)).isoformat())
                retry = cashier.post(self.path(debt, 'pay'), json=body)
                self.assertEqual(retry.status_code, 201, retry.text)
                self.amounts(self.current(origin, debt['id']), 1000, 100, 900)
                wrong = cashier.post(self.path(debt, 'pay'), json=dict(body, expected_fingerprint='0'*64))
                self.assertEqual(wrong.status_code, 409, wrong.text)

    def test_stale_full_payment_after_principal_change_preserves_cash_and_exact_retry(self):
        debt = self.create()
        revised, _ = self.revise(debt, amount='1500')
        self.pay(debt, cash='1000', expected_fingerprint=debt['management']['expected_fingerprint'], expected=409)
        self.ledger(1500, 0, 0)
        current = revised.json()
        paid, body = self.pay(current, cash='1500',
                              expected_fingerprint=current['management']['expected_fingerprint'])
        self.assertIsNotNone(paid.json()['payment'])
        self.assertEqual(self.owner.post(self.path(debt, 'pay'), json=body).status_code, 201)
        self.assertEqual(self.owner.post(self.path(debt, 'pay'), json=dict(body, expected_fingerprint=None)).status_code, 409)
        self.ledger(0, 1500, 0)

    def test_stale_customer_details_payment_is_rejected_without_receipt(self):
        debt = self.create()
        debtor = debt['debtor']
        body = {key: debtor[key] for key in ('branch_id','first_name','last_name','phone1','phone2','address')}
        result = self.owner.put(f"/api/debtors/{debtor['id']}", json=dict(body, first_name='Corrected name'))
        self.assertEqual(result.status_code, 200, result.text)
        self.pay(debt, cash='100', expected_fingerprint=debt['management']['expected_fingerprint'], expected=409)
        self.amounts(self.current('opening', debt['id']), 1000, 0, 1000)
        self.ledger(1000, 0, 0)

    def test_legacy_queue_refuses_central_partial_and_consumed_cancelled_request(self):
        debt = self.create('sale', amount='8000')
        self.pay(debt, cash='1000')
        cancelled_debt = self.create('sale', amount='8000')
        _, cancelled_body = self.pay(cancelled_debt, cash='1000')
        self.cancel_receipt(self.current('sale', cancelled_debt['id'])['payments'][0])
        # Financial data can predate the old-device registration. Registration
        # then freezes normal API writes until that device's queue is resolved.
        registered = self.owner.post('/api/sync/devices', json={'branch_id': 1, 'name': 'Legacy fixture PC'})
        self.assertEqual(registered.status_code, 201, registered.text)
        device = registered.json()
        local_debt_id = 333
        with self.sessions() as db:
            remember(db, device['device_id'], 'debts', local_debt_id, debt['id'])
            remember(db, device['device_id'], 'debts', local_debt_id+1, cancelled_debt['id'])
            db.commit()
        def queued(request_id, local_debt=local_debt_id):
            return {'branch_id': 1, 'events': [{'event_id': str(uuid.uuid4()), 'sequence': 1,
                'payload': {'version': 3, 'changes': [{'table': 'debt_payments', 'operation': 'insert',
                    'row': {'id': 222, 'request_id': request_id, 'debt_id': local_debt,
                            'branch_id': 1, 'user_id': 3, 'cash': '8000', 'card': '0',
                            'created_at': datetime.now(timezone.utc).isoformat()}}]}}]}
        def push(payload):
            return self.server.post('/api/sync/push', json=payload,
                                    headers={'Authorization': 'Bearer '+device['token']})
        old_full_queue = queued(str(uuid.uuid4()))
        result = push(old_full_queue)
        self.assertEqual(result.status_code, 409, result.text)
        self.ledger(15000, 5000, 0, stock=8)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(InboxEvent)), 0)
            self.assertEqual(db.get(SyncDevice, device['device_id']).received_sequence, 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtPayment)), 0)
        # A canceled modern UUID must never become a fresh legacy full receipt.
        replay = push(queued(cancelled_body['request_id'], local_debt_id+1))
        self.assertEqual(replay.status_code, 409, replay.text)
        self.ledger(15000, 5000, 0, stock=8)
        correct_full_queue = queued(str(uuid.uuid4()), local_debt_id+1)
        accepted = push(correct_full_queue)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(push(correct_full_queue).status_code, 200)
        self.ledger(7000, 13000, 0, stock=8)
        self.amounts(self.current('sale', debt['id']), 8000, 1000, 7000)
        self.amounts(self.current('sale', cancelled_debt['id']), 8000, 8000, 0)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(DebtPayment)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(InboxEvent)), 1)

    def test_original_checkout_retry_survives_rescheduling_without_new_sale_or_stock_change(self):
        for action in ('revise', 'partial'):
            with self.subTest(action=action):
                debtor = self.debtor()
                original_day = (today()+timedelta(days=7)).isoformat()
                new_day = (today()+timedelta(days=30)).isoformat()
                body = {**self.sale(), 'cash': '2000', 'debtor_id': debtor['id'], 'due_date': original_day}
                sold = self.owner.post('/api/sales', json=body)
                self.assertEqual(sold.status_code, 201, sold.text)
                debt = self.current('sale', sold.json()['debt']['id'])
                if action == 'revise':
                    self.revise(debt, due_date=new_day)
                else:
                    self.pay(debt, cash='2000', next_due_date=new_day)
                with self.sessions() as db:
                    before = (balances(db, 1), row(db.get(Stock, 1)),
                              db.scalar(select(func.count()).select_from(Sale)))
                retry = self.owner.post('/api/sales', json=body)
                self.assertEqual(retry.status_code, 201, retry.text)
                self.assertEqual(retry.json()['id'], sold.json()['id'])
                self.assertEqual(retry.json()['debt']['due_date'], new_day)
                changed = self.owner.post('/api/sales', json=dict(body, due_date=new_day))
                self.assertEqual(changed.status_code, 409, changed.text)
                with self.sessions() as db:
                    self.assertEqual((balances(db, 1), row(db.get(Stock, 1)),
                                      db.scalar(select(func.count()).select_from(Sale))), before)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class DebtManagementPostgresTest(DebtManagementTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
