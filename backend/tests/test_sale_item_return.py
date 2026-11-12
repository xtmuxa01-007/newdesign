"""Qisman qaytarish faqat vaqtinchalik bazada: ombor, pul, chegirma va tarix."""
from datetime import timedelta
from decimal import Decimal
import os
import unittest
import uuid

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
import test_branch_archive as fixture
from app.accounting import balances, supplier_debt
from app.models import Product, Stock, Sale, SaleItem, SaleEdit, MiniDiscountShare, Debt, User
from app.offline_queue import install_capture, uninstall_capture, OutboxEvent
from app.sale_edits import apply_edit
from app.schemas import EditSale
from app.routes_debts import today
from test_center_profile import branch_environment


class SaleItemReturnTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client
    provision = fixture.BranchArchiveTest.provision

    def create_sale(self, **changes):
        with self.sessions() as db:
            db.add(Product(id=2, name='Second product', sku='TEST-2', supplier_id=1))
            db.flush()
            db.add(Stock(id=3, branch_id=1, product_id=2, kg=10, price=20000))
            db.commit()
        response = self.owner.post('/api/sales', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1, 'customer': 'Return fixture',
            'items': [{'product_id': 1, 'kg': '1'}, {'product_id': 2, 'kg': '2'}],
            'expected_total': '50000', 'cash': '50000', 'card': '0', **changes})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def payload(self, sale, **changes):
        item = sale['items'][0]
        return {'request_id': str(uuid.uuid4()), 'version': sale['edit_version'],
            'reason': 'Ikkinchi mahsulot qaytarildi', 'customer': sale['customer'],
            'cash': '10000', 'card': '0', 'items': [{
                'item_id': item['id'], 'product_id': item['product_id'],
                'kg': item['kg'], 'price': item['price'], 'discount': item['discount']}],
            **changes}

    def edit(self, sale, body):
        return self.owner.post(f"/api/sales/{sale['id']}/edit", json=body)

    def test_return_restores_only_removed_stock_keeps_history_and_retries_once(self):
        sale = self.create_sale()
        body = self.payload(sale)
        for _ in range(2):
            result = self.edit(sale, body)
            self.assertEqual(result.status_code, 200, result.text)
            edited = result.json()
            self.assertEqual(len(edited['items']), 1)
            self.assertEqual(Decimal(edited['total']), 10000)
            self.assertEqual(edited['created_at'], sale['created_at'])
            self.assertEqual(edited['edit_version'], 1)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 9)
            self.assertEqual(db.get(Stock, 3).kg, 10)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 1)
            history = db.scalar(select(SaleEdit))
            self.assertEqual(len(history.before['items']), 2)
            self.assertEqual(len(history.after['items']), 1)
            self.assertEqual(Decimal(history.before['total']), 50000)
            self.assertEqual(Decimal(history.after['total']), 10000)
            self.assertEqual(balances(db, 1)['cash'], 10000)
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 10000)
        self.assertEqual(self.edit(sale, self.payload(sale)).status_code, 409)

    def test_return_reallocates_mini_discount_and_deletes_removed_share(self):
        sale = self.create_sale(cash='49000', mini_discount='1000')
        removed_id = sale['items'][1]['id']
        result = self.edit(sale, self.payload(sale, cash='9000'))
        self.assertEqual(result.status_code, 200, result.text)
        edited = result.json()
        self.assertEqual(Decimal(edited['total']), 9000)
        self.assertEqual(Decimal(edited['mini_discount']['amount']), 1000)
        self.assertEqual(Decimal(edited['mini_discount']['original_total']), 10000)
        self.assertEqual(len(edited['mini_discount']['shares']), 1)
        self.assertEqual(Decimal(edited['items'][0]['mini_discount']), 1000)
        with self.sessions() as db:
            self.assertIsNone(db.get(SaleItem, removed_id))
            self.assertIsNone(db.scalar(select(MiniDiscountShare).where(
                MiniDiscountShare.sale_item_id == removed_id)))
            self.assertEqual(supplier_debt(db, 1, 1)['debt'], 9000)

    def test_return_first_item_preserves_second_item_identity_and_discount(self):
        sale = self.create_sale(cash='49000', mini_discount='1000')
        item = sale['items'][1]
        body = self.payload(sale, cash='39000', items=[{
            'item_id': item['id'], 'product_id': item['product_id'],
            'kg': item['kg'], 'price': item['price'], 'discount': item['discount']}])
        result = self.edit(sale, body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['items'][0]['id'], item['id'])
        self.assertEqual(Decimal(result.json()['total']), 39000)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 10)
            self.assertEqual(db.get(Stock, 3).kg, 8)
            shares = list(db.scalars(select(MiniDiscountShare)))
            self.assertEqual(len(shares), 1)
            self.assertEqual(shares[0].sale_item_id, item['id'])
            self.assertEqual(shares[0].amount, 1000)

    def test_empty_foreign_and_duplicate_lines_cannot_change_sale_or_stock(self):
        sale = self.create_sale()
        base = self.payload(sale)
        for lines in ([], [dict(base['items'][0], item_id=9999)], base['items'] * 2):
            result = self.edit(sale, self.payload(sale, items=lines))
            self.assertEqual(result.status_code, 422, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 1).kg, 9)
            self.assertEqual(db.get(Stock, 3).kg, 8)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleEdit)), 0)

    def test_return_recalculates_outstanding_debt(self):
        debtor = self.owner.post('/api/debtors', json={
            'branch_id': 1, 'first_name': 'Test', 'last_name': 'Debtor',
            'phone1': '+998900000001', 'phone2': '+998900000002',
            'address': 'Fixture address'}).json()
        sale = self.create_sale(cash='2000', debtor_id=debtor['id'],
            due_date=(today() + timedelta(days=2)).isoformat())
        result = self.edit(sale, self.payload(sale, cash='2000'))
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(Debt)).amount, 8000)
            self.assertEqual(balances(db, 1)['customer_debt'], 8000)
            self.assertEqual(db.get(Stock, 3).kg, 10)

    def test_failed_payment_validation_rolls_back_stock_items_and_discount_shares(self):
        sale = self.create_sale(cash='49000', mini_discount='1000')
        result = self.edit(sale, self.payload(sale, cash='8000'))
        self.assertEqual(result.status_code, 422, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 3).kg, 8)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(MiniDiscountShare)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleEdit)), 0)

    def test_return_cannot_reduce_supplier_balance_below_money_already_paid(self):
        sale = self.create_sale()
        payment = self.owner.post('/api/suppliers/1/payments', json={
            'request_id': str(uuid.uuid4()), 'branch_id': 1,
            'amount': '45000', 'method': 'cash', 'recipient': 'Supplier', 'note': ''})
        self.assertEqual(payment.status_code, 201, payment.text)
        result = self.edit(sale, self.payload(sale))
        self.assertEqual(result.status_code, 409, result.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Stock, 3).kg, 8)
            self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 2)

    def test_legacy_sync_recalculates_return_with_deleted_item_and_discount_share(self):
        sale = self.create_sale(cash='49000', mini_discount='1000')
        folder, config = self.provision()
        engine = create_engine('sqlite:///' + (folder / 'branch.db').as_posix())
        sessions = sessionmaker(engine, expire_on_commit=False)
        listener = install_capture(sessions, config['device_id'], 1)
        try:
            with branch_environment(1), sessions() as db:
                local_sale = db.scalar(select(Sale))
                item = db.scalar(select(SaleItem).where(SaleItem.sale_id == local_sale.id)
                                 .order_by(SaleItem.id))
                body = self.payload(sale, cash='9000', items=[{
                    'item_id': item.id, 'product_id': item.product_id,
                    'kg': str(item.kg), 'price': str(item.price), 'discount': str(item.discount)}])
                apply_edit(db, local_sale.id, EditSale.model_validate(body), db.get(User, 1))
                db.commit()
                event = db.scalar(select(OutboxEvent))
                envelope = {'event_id': event.event_id, 'sequence': event.sequence,
                            'payload': event.payload}
            response = self.server.post('/api/sync/push',
                headers={'Authorization': 'Bearer ' + config['token']},
                json={'branch_id': 1, 'events': [envelope]})
            self.assertEqual(response.status_code, 200, response.text)
            with self.sessions() as db:
                self.assertEqual(db.get(Stock, 3).kg, 10)
                self.assertEqual(db.get(Sale, sale['id']).total, 9000)
                self.assertEqual(db.scalar(select(func.count()).select_from(SaleItem)), 1)
                self.assertEqual(db.scalar(select(func.count()).select_from(MiniDiscountShare)), 1)
                self.assertEqual(db.scalar(select(func.count()).select_from(SaleEdit)), 1)
        finally:
            uninstall_capture(sessions, listener)
            engine.dispose()


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class SaleItemReturnPostgresTest(SaleItemReturnTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
