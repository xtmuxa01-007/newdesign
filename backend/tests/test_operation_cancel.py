"""Bekor qilish joriy hisobni qaytaradi, asl dalil va takroriy so'rov himoyasi qoladi."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import os
from threading import Event
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import select, func, event
import test_branch_archive as fixture
from app.accounting import balances, supplier_debt
from app.models import (Sale, SaleItem, SaleEdit, Receipt, Stock, StockAdjustment,
                        Debt, DebtPayment, MiniDiscount, MiniDiscountShare,
                        BranchExpense, SupplierPayment, DonationPayment, Audit,
                        OperationCancellation)
from app.operation_history import operation_model, source_fingerprint
from app.routes_debts import today


class OperationCancelTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    sale = fixture.BranchArchiveTest.sale
    provision = fixture.BranchArchiveTest.provision

    def count(self, db, model):
        return db.scalar(select(func.count()).select_from(model))

    def create_sale(self, **changes):
        body = dict(self.sale(), **changes)
        response = self.owner.post('/api/sales', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), body

    def create_debt_sale(self):
        result = self.owner.post('/api/debtors', json={
            'branch_id': 1, 'first_name': 'Test', 'last_name': 'Debtor',
            'phone1': '+998900000001', 'phone2': '+998900000002',
            'address': 'Fixture address'})
        self.assertEqual(result.status_code, 201, result.text)
        return self.create_sale(cash='2000', debtor_id=result.json()['id'],
            due_date=(today() + timedelta(days=2)).isoformat())

    def edit_sale(self, sale, kg='0.5', cash='5000', **changes):
        body = {'request_id': str(uuid.uuid4()), 'version': sale['edit_version'],
            'reason': 'Fixture savdo tuzatishi', 'customer': 'Correct customer',
            'cash': cash, 'card': '0', 'items': [{'item_id': sale['items'][0]['id'],
                'product_id': 1, 'kg': kg, 'price': '10000', 'discount': '0'}],
            **changes}
        result = self.owner.post(f"/api/sales/{sale['id']}/edit", json=body)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def payload(self, kind, operation_id):
        with self.sessions() as db:
            source = db.get(operation_model(kind), operation_id)
            self.assertIsNotNone(source)
            fingerprint = source_fingerprint(db, kind, source)
        return {'request_id': str(uuid.uuid4()), 'reason': 'Xato amal fixture',
                'expected_fingerprint': fingerprint}

    def cancel(self, kind, operation_id, body=None, client=None):
        return (client or self.owner).post(f'/api/operations/{kind}/{operation_id}/cancel',
            json=body or self.payload(kind, operation_id))

    def receipt(self, kg='1', price='12000'):
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1, 'product_id': 1,
                'kg': kg, 'price': price, 'note': 'Fixture kirim'}
        response = self.owner.post('/api/receipts', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), body

    def adjustment(self, kg, expected):
        body = {'request_id': str(uuid.uuid4()), 'kg': str(kg), 'expected_kg': str(expected),
                'reason': 'Fixture qoldiq tuzatishi'}
        response = self.owner.post('/api/stocks/1/adjustments', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), body

    def payment(self, path, amount='1000', method='cash'):
        body = {'request_id': str(uuid.uuid4()), 'branch_id': 1, 'amount': amount,
                'method': method, 'recipient': 'Fixture recipient', 'note': ''}
        result = self.owner.post(path, json=body)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json(), body

    def assert_empty_sales(self, kg='10'):
        with self.sessions() as db:
            for model in (Sale, SaleItem, SaleEdit, Debt, DebtPayment,
                          MiniDiscount, MiniDiscountShare):
                self.assertEqual(self.count(db, model), 0, model.__tablename__)
            self.assertEqual(db.get(Stock, 1).kg, Decimal(kg))
            ledger = balances(db, 1)
            for name in ('cash', 'card', 'customer_debt', 'donation_balance'):
                self.assertEqual(ledger[name], 0, name)
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 0)

    def test_sale_cancellation_context_is_read_only_and_matches_current_audit(self):
        sale, _ = self.create_sale(mini_discount='1000', cash='9000')
        sale = self.edit_sale(sale, cash='4000')
        admin = self.client('admin')

        def database_state():
            with self.sessions() as db:
                return {table.name: sorted(list(db.execute(select(table))), key=repr)
                        for table in Sale.metadata.sorted_tables}

        before = database_state()
        path = f"/api/sales/{sale['id']}/cancellation"
        response = self.owner.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        context = response.json()
        self.assertEqual(context['action'], 'Savdo')
        self.assertEqual(context['actor'], self.owner_data['name'])
        self.assertEqual(context['created_at'], sale['created_at'])
        self.assertEqual(context['branch_id'], sale['branch_id'])
        operation = context['operation']
        self.assertEqual((operation['kind'], operation['id']), ('sale', sale['id']))
        self.assertTrue(operation['can_cancel'])
        self.assertFalse(operation['cancelled'])
        self.assertEqual(Decimal(operation['summary']['total']), 4000)
        self.assertEqual(Decimal(operation['summary']['items'][0]['kg']), Decimal('0.5'))
        self.assertRegex(operation['expected_fingerprint'], r'^[0-9a-f]{64}$')
        self.assertEqual(admin.get(path).json()['operation'], operation)
        history = self.owner.get('/api/audit?branch_id=1').json()
        linked = [entry['operation'] for entry in history if entry.get('operation') and
                  entry['operation']['kind'] == 'sale' and entry['operation']['id'] == sale['id']]
        self.assertTrue(linked)
        self.assertTrue(all(entry == operation for entry in linked))
        self.assertEqual(database_state(), before)

    def test_sale_cancellation_context_checks_role_branch_and_missing_sale(self):
        sale, _ = self.create_sale()
        other, _ = self.create_sale(branch_id=2)
        own_path = f"/api/sales/{sale['id']}/cancellation"
        other_path = f"/api/sales/{other['id']}/cancellation"
        self.assertEqual(self.client().get(own_path).status_code, 401)
        self.assertEqual(self.client('cashier').get(own_path).status_code, 403)
        admin = self.client('admin')
        self.assertEqual(admin.get(own_path).status_code, 200)
        self.assertEqual(admin.get(other_path).status_code, 403)
        self.assertTrue(self.client('boss').get(other_path).json()['operation']['can_cancel'])
        self.assertEqual(self.owner.get('/api/sales/999999/cancellation').status_code, 404)

    def test_old_sale_context_fingerprint_uses_existing_audited_cancellation(self):
        sale, _ = self.create_sale()
        with self.sessions() as db:
            source = db.get(Sale, sale['id'])
            source.created_at -= timedelta(days=4)
            db.commit()
        path = f"/api/sales/{sale['id']}/cancellation"
        context = self.owner.get(path).json()
        self.assertTrue(context['operation']['can_cancel'])
        body = {'request_id': str(uuid.uuid4()), 'reason': 'Old sale fixture correction',
                'expected_fingerprint': context['operation']['expected_fingerprint']}
        result = self.cancel('sale', sale['id'], body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assert_empty_sales()
        self.assertEqual(self.owner.get(path).status_code, 404)
        history = self.owner.get('/api/audit?branch_id=1').json()
        self.assertTrue(any(entry['action'] == 'Amal bekor qilindi' and
                            entry['operation']['cancelled'] for entry in history))

    def test_archived_sale_cancellation_context_explains_block(self):
        sale, _ = self.create_sale()
        archived = self.owner.post('/api/branches/1/archive', json={'confirmation': 'Shared'})
        self.assertEqual(archived.status_code, 200, archived.text)
        response = self.owner.get(f"/api/sales/{sale['id']}/cancellation")
        self.assertEqual(response.status_code, 200, response.text)
        operation = response.json()['operation']
        self.assertFalse(operation['can_cancel'])
        self.assertIn('arxivlangan', operation['reason'])
        self.assertEqual(Decimal(operation['summary']['total']), 10000)

    def test_local_and_legacy_sale_cancellation_contexts_explain_transition(self):
        sale, _ = self.create_sale()
        path = f"/api/sales/{sale['id']}/cancellation"
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            response = self.owner.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['operation']['can_cancel'])
        self.assertIn('umumiy bazaga', response.json()['operation']['reason'])
        self.provision()
        response = self.owner.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['operation']['can_cancel'])
        self.assertIn('offline', response.json()['operation']['reason'])

    def test_active_installment_blocks_sale_context_until_receipt_is_cancelled(self):
        sale, _ = self.create_debt_sale()
        path = f"/api/sales/{sale['id']}/cancellation"
        before = self.owner.get(path).json()['operation']
        payment = self.owner.post(f"/api/debts/{sale['debt']['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '1000', 'card': '0'})
        self.assertEqual(payment.status_code, 201, payment.text)
        operation = self.owner.get(path).json()['operation']
        self.assertFalse(operation['can_cancel'])
        self.assertIn('qarz to‘lovi', operation['reason'])
        self.assertEqual(Decimal(operation['summary']['debt_cash']), 1000)
        self.assertNotEqual(operation['expected_fingerprint'], before['expected_fingerprint'])
        receipt = payment.json()['payments'][0]
        cancelled = self.owner.post(f"/api/debt-installments/{receipt['id']}/cancel", json={
            'request_id': str(uuid.uuid4()), 'reason': 'Incorrect receipt fixture',
            'expected_fingerprint': receipt['operation']['expected_fingerprint']})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        restored = self.owner.get(path).json()['operation']
        self.assertTrue(restored['can_cancel'])
        self.assertEqual(Decimal(restored['summary']['debt_cash']), 0)

    def test_edited_mini_sale_reversal_archives_dependencies_and_is_idempotent(self):
        sale, original = self.create_sale(mini_discount='1000', cash='9000')
        sale = self.edit_sale(sale, cash='4000')
        before_audit = self.owner.get('/api/audit?branch_id=1').json()
        linked = [a for a in before_audit if a.get('operation') and
                  a['operation']['kind'] == 'sale' and a['operation']['id'] == sale['id']]
        self.assertEqual(len(linked), 3)  # Savdo, mini chegirma, tuzatish.
        self.assertTrue(all(a['operation']['can_cancel'] for a in linked))
        # Eski auditdagi to'lov emas, tuzatilgan joriy savdo tasdiqlanadi.
        for entry in linked:
            summary = entry['operation']['summary']
            self.assertEqual(Decimal(summary['cash']), 4000)
            self.assertEqual(Decimal(summary['total']), 4000)
            self.assertEqual(Decimal(summary['items'][0]['kg']), Decimal('0.5'))
        body = self.payload('sale', sale['id'])
        result = self.cancel('sale', sale['id'], body)
        self.assertEqual(result.status_code, 200, result.text)
        marker = result.json()['cancellation']
        snapshot = marker['snapshot']
        self.assertEqual(Decimal(snapshot['record']['total']), 4000)
        self.assertEqual(Decimal(snapshot['sale_items'][0]['kg']), Decimal('0.5'))
        self.assertEqual(len(snapshot['sale_edits']), 1)
        self.assertEqual(len(snapshot['mini_discounts']), 1)
        self.assertEqual(len(snapshot['mini_discount_shares']), 1)
        self.assertEqual(set(snapshot['audit_ids']), {a['id'] for a in linked})
        self.assert_empty_sales()
        replay = self.cancel('sale', sale['id'], body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()['cancellation']['id'], marker['id'])
        mismatch = self.cancel('sale', sale['id'], dict(body, reason='Different reason'))
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        self.assertEqual(self.owner.post('/api/sales', json=original).status_code, 409)
        after_audit = self.owner.get('/api/audit?branch_id=1').json()
        self.assertEqual(len(after_audit), len(before_audit) + 1)
        cancelled = [a for a in after_audit if a['id'] in snapshot['audit_ids']]
        self.assertTrue(all(a['operation']['cancelled'] and not a['operation']['can_cancel']
                            for a in cancelled))
        fresh_sale, _ = self.create_sale()
        self.assertGreater(fresh_sale['id'], sale['id'])
        # Eski tarix yangi savdoni bir xil raqam bilan tutmasin.
        after_audit = self.owner.get('/api/audit?branch_id=1').json()
        old = next(a for a in after_audit if a['id'] == linked[0]['id'])
        self.assertTrue(old['operation']['cancelled'])
        with self.sessions() as db:
            self.assertEqual(self.count(db, OperationCancellation), 1)

    def test_paid_debt_sale_reversal_archives_child_payment_and_stock(self):
        sale, _ = self.create_debt_sale()
        debt_id = sale['debt']['id']
        pay_body = {'request_id': str(uuid.uuid4()), 'cash': '5000', 'card': '3000'}
        paid = self.owner.post(f'/api/debts/{debt_id}/pay', json=pay_body)
        self.assertEqual(paid.status_code, 201, paid.text)
        payment_id = paid.json()['payment']['id']
        # Joriy tuzatilgan qiymatlar ham, avvalgi nusxa ham arxivlanadi.
        sale = self.edit_sale(sale, kg='0.8', cash='2000', debt_cash='4000', debt_card='2000')
        result = self.cancel('sale', sale['id'])
        self.assertEqual(result.status_code, 200, result.text)
        parent = result.json()['cancellation']
        snapshot = parent['snapshot']
        self.assertEqual(len(snapshot['debts']), 1)
        self.assertEqual(len(snapshot['debt_payments']), 1)
        self.assertEqual(Decimal(snapshot['debt_payments'][0]['cash']), 4000)
        self.assertEqual(len(snapshot['sale_edits']), 1)
        self.assert_empty_sales()
        with self.sessions() as db:
            self.assertEqual(self.count(db, OperationCancellation), 2)
            child = db.scalar(select(OperationCancellation).where(
                OperationCancellation.kind == 'debt_payment'))
            self.assertEqual(child.operation_id, payment_id)
            self.assertEqual(child.original_request_id, pay_body['request_id'])
            self.assertEqual(child.snapshot['parent_cancellation_id'], parent['id'])
        audit = self.owner.get('/api/audit?branch_id=1').json()
        entry = next(a for a in audit if a['action'] == 'Qarz to‘landi')
        self.assertTrue(entry['operation']['cancelled'])

    def test_debt_payment_can_be_cancelled_and_paid_again_without_replay(self):
        sale, _ = self.create_debt_sale()
        debt_id = sale['debt']['id']
        body = {'request_id': str(uuid.uuid4()), 'cash': '5000', 'card': '3000'}
        paid = self.owner.post(f'/api/debts/{debt_id}/pay', json=body)
        self.assertEqual(paid.status_code, 201, paid.text)
        result = self.cancel('debt_payment', paid.json()['payment']['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(Debt, debt_id))
            self.assertEqual(self.count(db, DebtPayment), 0)
            self.assertEqual(balances(db, 1)['cash'], 2000)
            self.assertEqual(balances(db, 1)['card'], 0)
            self.assertEqual(balances(db, 1)['customer_debt'], 8000)
        self.assertEqual(self.owner.post(f'/api/debts/{debt_id}/pay', json=body).status_code, 409)
        result = self.owner.post(f'/api/debts/{debt_id}/pay', json=dict(body, request_id=str(uuid.uuid4())))
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['status'], 'paid')

    def test_permissions_stale_fingerprint_and_input_validation_preserve_operation(self):
        sale, _ = self.create_sale()
        body = self.payload('sale', sale['id'])
        self.assertEqual(self.cancel('sale', sale['id'], body, self.client('cashier')).status_code, 403)
        other_sale, _ = self.create_sale(branch_id=2)
        self.assertEqual(self.cancel('sale', other_sale['id'], client=self.client('admin')).status_code, 403)
        # Tugallanmagan dialog paytida savdo tuzatildi.
        sale = self.edit_sale(sale)
        stale = self.cancel('sale', sale['id'], body)
        self.assertEqual(stale.status_code, 409, stale.text)
        for change in ({'reason': '  '}, {'expected_fingerprint': 'bad'},
                       {'request_id': 'not-a-uuid'}, {'user_id': 4}):
            response = self.cancel('sale', sale['id'], dict(self.payload('sale', sale['id']), **change))
            self.assertEqual(response.status_code, 422, response.text)
        unknown = self.owner.post('/api/operations/audit/1/cancel', json=body)
        self.assertEqual(unknown.status_code, 422, unknown.text)
        with self.sessions() as db:
            self.assertEqual(self.count(db, OperationCancellation), 0)
            self.assertEqual(self.count(db, Sale), 2)
        # Oddiy admin o'z filialidagi joriy savdoni bekor qila oladi.
        result = self.cancel('sale', sale['id'], client=self.client('admin'))
        self.assertEqual(result.status_code, 200, result.text)

    def test_new_debt_payment_invalidates_sale_confirmation(self):
        sale, _ = self.create_debt_sale()
        body = self.payload('sale', sale['id'])
        result = self.owner.post(f"/api/debts/{sale['debt']['id']}/pay", json={
            'request_id': str(uuid.uuid4()), 'cash': '8000', 'card': '0'})
        self.assertEqual(result.status_code, 201, result.text)
        result = self.cancel('sale', sale['id'], body)
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(self.count(db, Sale), 1)
            self.assertEqual(self.count(db, DebtPayment), 1)
            self.assertEqual(self.count(db, OperationCancellation), 0)
            self.assertEqual(db.get(Stock, 1).kg, 9)

    def test_outgoing_payments_and_expense_reversal_restore_accounts(self):
        self.create_sale(cash='15000')  # 10 000 savdo, 5 000 ehson.
        rows = []
        for kind, path, model in (
            ('supplier_payment', '/api/suppliers/1/payments', SupplierPayment),
            ('donation_payment', '/api/donations/payments', DonationPayment)):
            payment, body = self.payment(path)
            rows.append((kind, path, model, payment, body))
        expense_body = {'request_id': str(uuid.uuid4()), 'branch_id': 1,
                        'supplier_id': 1, 'amount': '1000', 'method': 'cash',
                        'reason': 'Fixture branch expense'}
        result = self.client('cashier').post('/api/expenses', json=expense_body)
        self.assertEqual(result.status_code, 201, result.text)
        rows.append(('expense', '/api/expenses', BranchExpense, result.json(), expense_body))
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], 12000)
            self.assertEqual(balances(db, 1)['donation_balance'], 4000)
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 8000)
        for kind, path, model, source, body in rows:
            with self.subTest(kind=kind):
                result = self.cancel(kind, source['id'])
                self.assertEqual(result.status_code, 200, result.text)
                replay = self.owner.post(path, json=body)
                self.assertEqual(replay.status_code, 409, replay.text)
                with self.sessions() as db:
                    self.assertIsNone(db.get(model, source['id']))
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], 15000)
            self.assertEqual(balances(db, 1)['donation_balance'], 5000)
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 10000)
            self.assertEqual(self.count(db, OperationCancellation), 3)

    def test_receipt_reversal_restores_price_but_preserves_later_discount(self):
        receipt, body = self.receipt()
        changed = self.owner.patch('/api/stocks/1/discount', json={'discount': '5'})
        self.assertEqual(changed.status_code, 200, changed.text)
        result = self.cancel('receipt', receipt['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            stock = db.get(Stock, 1)
            self.assertEqual(stock.kg, 10)
            self.assertEqual(stock.price, 10000)
            self.assertEqual(stock.discount, 5)
            self.assertEqual(self.count(db, Receipt), 0)
        self.assertEqual(self.owner.post('/api/receipts', json=body).status_code, 409)

    def test_receipts_cancelled_out_of_order_restore_active_price_then_baseline(self):
        first, _ = self.receipt(price='11000')
        second, _ = self.receipt(price='12000')
        third, _ = self.receipt(price='13000')
        self.assertEqual(self.cancel('receipt', second['id']).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).price, 13000)
            self.assertEqual(db.get(Stock, 1).kg, 12)
        result = self.cancel('receipt', third['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).price, 11000)
            self.assertEqual(db.get(Stock, 1).kg, 11)
        result = self.cancel('receipt', first['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).price, 10000)
            self.assertEqual(db.get(Stock, 1).kg, 10)
            self.assertEqual(self.count(db, Receipt), 0)
            self.assertEqual(self.count(db, OperationCancellation), 3)

    def test_receipt_underflow_rolls_back_everything(self):
        receipt, _ = self.receipt(price='10000')
        self.create_sale(items=[{'product_id': 1, 'kg': '11'}],
                         expected_total='110000', cash='110000')
        result = self.cancel('receipt', receipt['id'])
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 0)
            self.assertIsNotNone(db.get(Receipt, receipt['id']))
            self.assertEqual(self.count(db, OperationCancellation), 0)

    def test_latest_receipt_uses_baseline_of_cancelled_earliest_receipt(self):
        first, _ = self.receipt(price='11000')
        second, _ = self.receipt(price='12000')
        result = self.cancel('receipt', first['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).price, 12000)
        result = self.cancel('receipt', second['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 10)
            self.assertEqual(db.get(Stock, 1).price, 10000)

    def test_later_stock_adjustment_blocks_old_movement_and_owner_can_reverse_it(self):
        sale, _ = self.create_sale()
        receipt, _ = self.receipt(price='10000')
        adjustment, original = self.adjustment(20, 10)
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 409)
        self.assertEqual(self.cancel('receipt', receipt['id']).status_code, 409)
        self.assertEqual(self.cancel('stock_adjustment', adjustment['id'],
                                     client=self.client('boss')).status_code, 403)
        history = self.client('boss').get('/api/audit?branch_id=1').json()
        row = next(a for a in history if a['action'] == 'Ombor qoldig‘i tuzatildi')
        self.assertFalse(row['operation']['can_cancel'])
        result = self.cancel('stock_adjustment', adjustment['id'])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 10)
            self.assertEqual(self.count(db, StockAdjustment), 0)
        self.assertEqual(self.owner.post('/api/stocks/1/adjustments', json=original).status_code, 409)
        self.assertEqual(self.cancel('sale', sale['id']).status_code, 200)
        self.assertEqual(self.cancel('receipt', receipt['id']).status_code, 200)
        self.assert_empty_sales()

    def test_stock_adjustment_with_later_sale_cannot_be_removed(self):
        adjustment, _ = self.adjustment(20, 10)
        self.create_sale()
        result = self.cancel('stock_adjustment', adjustment['id'])
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 19)
            self.assertIsNotNone(db.get(StockAdjustment, adjustment['id']))
            self.assertEqual(self.count(db, OperationCancellation), 0)

    def test_spent_sale_cash_cannot_be_removed_and_transaction_is_intact(self):
        sale, _ = self.create_sale()
        expense = {'request_id': str(uuid.uuid4()), 'branch_id': 1,
            'supplier_id': 1, 'amount': '5000', 'method': 'cash', 'reason': 'Spent cash'}
        result = self.owner.post('/api/expenses', json=expense)
        self.assertEqual(result.status_code, 201, result.text)
        with self.sessions() as db:
            before = balances(db, 1)
            before_count = self.count(db, Audit)
        result = self.cancel('sale', sale['id'])
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1), before)
            self.assertEqual(db.get(Stock, 1).kg, 9)
            self.assertIsNotNone(db.get(Sale, sale['id']))
            self.assertEqual(self.count(db, OperationCancellation), 0)
            self.assertEqual(self.count(db, Audit), before_count)

    def test_spent_donation_blocks_sale_even_when_cash_would_remain_positive(self):
        sale, _ = self.create_sale(cash='15000')
        self.create_sale()
        self.payment('/api/donations/payments', '5000')
        result = self.cancel('sale', sale['id'])
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], 20000)
            self.assertEqual(balances(db, 1)['donation_balance'], 0)
            self.assertEqual(self.count(db, Sale), 2)
            self.assertEqual(db.get(Stock, 1).kg, 8)
            self.assertEqual(self.count(db, OperationCancellation), 0)

    def test_concurrent_identical_cancellation_is_applied_once(self):
        sale, _ = self.create_sale()
        body = self.payload('sale', sale['id'])
        other = self.client()
        login = other.post('/api/auth/login', json={'username': 'abduqodir', 'password': self.secret})
        self.assertEqual(login.status_code, 200, login.text)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.cancel, 'sale', sale['id'], body, self.owner)
            second = pool.submit(self.cancel, 'sale', sale['id'], body, other)
            results = (first.result(), second.result())
        for result in results:
            self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(results[0].json()['cancellation']['id'],
                         results[1].json()['cancellation']['id'])
        self.assert_empty_sales()
        with self.sessions() as db:
            self.assertEqual(self.count(db, OperationCancellation), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(
                Audit.action == 'Amal bekor qilindi')), 1)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class OperationCancelPostgresTest(OperationCancelTest):
    postgres = True

    def test_context_waits_for_payment_commit_before_reading_summary_and_fingerprint(self):
        from app.debt_management import apply_payment
        from app.models import Branch, User
        from app.schemas import SettleDebt
        sale, _ = self.create_debt_sale()
        requester = self.client('boss')
        reading_branch = Event()

        def observe_branch_read(connection, cursor, statement, parameters, context, many):
            if 'FOR SHARE' in statement:
                reading_branch.set()

        event.listen(self.engine, 'before_cursor_execute', observe_branch_read)
        try:
            with self.sessions() as writer:
                writer.scalar(select(Branch).where(Branch.id == 1).with_for_update())
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(requester.get, f"/api/sales/{sale['id']}/cancellation")
                    try:
                        self.assertTrue(reading_branch.wait(5), 'Context must acquire a shared branch lock')
                        self.assertFalse(pending.done())
                        apply_payment(writer, 'sale', sale['debt']['id'], SettleDebt(
                            request_id=str(uuid.uuid4()), cash='8000', card='0'), writer.get(User, 4))
                        writer.commit()
                        response = pending.result(timeout=10)
                    finally:
                        writer.rollback()
            self.assertEqual(response.status_code, 200, response.text)
            operation = response.json()['operation']
            self.assertTrue(operation['can_cancel'])
            self.assertEqual(Decimal(operation['summary']['debt_cash']), 8000)
            self.assertEqual(operation['expected_fingerprint'],
                             self.payload('sale', sale['id'])['expected_fingerprint'])
        finally:
            event.remove(self.engine, 'before_cursor_execute', observe_branch_read)

    def test_parallel_sale_edit_and_cancellation_have_one_coherent_result(self):
        sale, _ = self.create_sale()
        cancel_body = self.payload('sale', sale['id'])
        edit_body = {'request_id': str(uuid.uuid4()), 'version': 0,
            'reason': 'Parallel edit fixture', 'customer': 'Changed customer',
            'cash': '5000', 'card': '0', 'items': [{'item_id': sale['items'][0]['id'],
                'product_id': 1, 'kg': '0.5', 'price': '10000', 'discount': '0'}]}
        editor = self.client('boss')
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation = pool.submit(self.cancel, 'sale', sale['id'], cancel_body)
            edit = pool.submit(editor.post, f"/api/sales/{sale['id']}/edit", json=edit_body)
            cancelled, edited = cancellation.result(), edit.result()
        self.assertIn(cancelled.status_code, (200, 409), cancelled.text)
        self.assertIn(edited.status_code, (200, 404, 409), edited.text)
        with self.sessions() as db:
            if cancelled.status_code == 200:
                self.assertIn(edited.status_code, (404, 409), edited.text)
                self.assertIsNone(db.get(Sale, sale['id']))
                self.assertEqual(db.get(Stock, 1).kg, 10)
                self.assertEqual(balances(db, 1)['cash'], 0)
                self.assertEqual(self.count(db, OperationCancellation), 1)
                self.assertEqual(self.count(db, SaleEdit), 0)
            else:
                self.assertEqual(edited.status_code, 200, edited.text)
                self.assertEqual(db.get(Sale, sale['id']).cash, 5000)
                self.assertEqual(db.get(Stock, 1).kg, Decimal('9.5'))
                self.assertEqual(balances(db, 1)['cash'], 5000)
                self.assertEqual(self.count(db, OperationCancellation), 0)
                self.assertEqual(self.count(db, SaleEdit), 1)

    def test_parallel_debt_payment_and_sale_cancellation_have_one_coherent_result(self):
        sale, _ = self.create_debt_sale()
        cancel_body = self.payload('sale', sale['id'])
        debt_id = sale['debt']['id']
        payment_body = {'request_id': str(uuid.uuid4()), 'cash': '8000', 'card': '0'}
        payer = self.client('cashier')
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation = pool.submit(self.cancel, 'sale', sale['id'], cancel_body)
            payment = pool.submit(payer.post, f'/api/debts/{debt_id}/pay', json=payment_body)
            cancelled, paid = cancellation.result(), payment.result()
        self.assertIn(cancelled.status_code, (200, 409), cancelled.text)
        self.assertIn(paid.status_code, (201, 404, 409), paid.text)
        with self.sessions() as db:
            if cancelled.status_code == 200:
                self.assertIn(paid.status_code, (404, 409), paid.text)
                self.assertIsNone(db.get(Sale, sale['id']))
                self.assertIsNone(db.get(Debt, debt_id))
                self.assertEqual(db.get(Stock, 1).kg, 10)
                self.assertEqual(balances(db, 1)['cash'], 0)
                self.assertEqual(self.count(db, OperationCancellation), 1)
                self.assertEqual(self.count(db, DebtPayment), 0)
            else:
                self.assertEqual(paid.status_code, 201, paid.text)
                self.assertIsNotNone(db.get(Sale, sale['id']))
                self.assertEqual(db.get(Stock, 1).kg, 9)
                self.assertEqual(balances(db, 1)['cash'], 10000)
                self.assertEqual(balances(db, 1)['customer_debt'], 0)
                self.assertEqual(self.count(db, OperationCancellation), 0)
                self.assertEqual(self.count(db, DebtPayment), 1)


if __name__ == '__main__':
    unittest.main()
