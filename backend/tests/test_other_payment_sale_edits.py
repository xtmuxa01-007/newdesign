"""Existing cash deficits from handovers cannot block unrelated sale corrections."""
from decimal import Decimal
import os
import unittest
import uuid

import test_other_payments as fixture
from app.accounting import balances
from app.models import Sale


class OtherPaymentSaleEditsTest(unittest.TestCase):
    setUp = fixture.OtherPaymentsTest.setUp
    tearDown = fixture.OtherPaymentsTest.tearDown
    client = fixture.OtherPaymentsTest.client
    sale = fixture.OtherPaymentsTest.sale
    payload = fixture.OtherPaymentsTest.payload
    payout = fixture.OtherPaymentsTest.payout

    def edit(self, sale, price='10000', customer='Tuzatilgan ism', **values):
        body = {'request_id': str(uuid.uuid4()), 'version': sale['edit_version'],
                'reason': 'Fixture tuzatish', 'customer': customer, 'cash': price, 'card': '0',
                'items': [{'item_id': sale['items'][0]['id'], 'product_id': 1,
                           'kg': '1', 'price': price, 'discount': '0'}], **values}
        return self.owner.post(f"/api/sales/{sale['id']}/edit", json=body)

    def test_unchanged_or_improving_cash_deficit_edits_work_but_worsening_is_rejected(self):
        response = self.owner.post('/api/sales', json=self.sale())
        self.assertEqual(response.status_code, 201, response.text)
        sale = response.json()
        self.payout(amount='15000')
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], -5000)
        changed = self.edit(sale)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['customer'], 'Tuzatilgan ism')
        improved = self.edit(changed.json(), price='12000')
        self.assertEqual(improved.status_code, 200, improved.text)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], -3000)
        rejected = self.edit(improved.json(), price='11000')
        self.assertEqual(rejected.status_code, 409, rejected.text)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], -3000)
            self.assertEqual(db.get(Sale, sale['id']).total, Decimal('12000'))

    def test_edit_may_not_move_cash_to_card_and_create_new_deficit(self):
        sale = self.owner.post('/api/sales', json=self.sale()).json()
        self.payout(amount='5000')
        rejected = self.edit(sale, cash='0', card='10000')
        self.assertEqual(rejected.status_code, 409, rejected.text)
        with self.sessions() as db:
            self.assertEqual(balances(db, 1)['cash'], 5000)
            self.assertEqual(balances(db, 1)['card'], 0)


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class OtherPaymentSaleEditsPostgresTest(OtherPaymentSaleEditsTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
