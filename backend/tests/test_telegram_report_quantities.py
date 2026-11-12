"""Synthetic local records only: sold and closing kilograms stay independent."""
from datetime import timedelta, timezone
from decimal import Decimal
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import select

import test_telegram_daily_reports as fixture
from app.models import Sale, SaleItem, Stock, User
from app.sale_edits import apply_edit
from app.schemas import EditSale
from app import stock_valuation_history as history
from app import telegram_daily_reports as reports


class TelegramReportQuantitiesTest(unittest.TestCase):
    setUp = fixture.DailyReportAccountingTest.setUp
    tearDown = fixture.DailyReportAccountingTest.tearDown
    moment = fixture.DailyReportAccountingTest.moment
    report = fixture.DailyReportAccountingTest.report

    def sale(self, moment=None, branch=1, lines=((1, '0.100', '1000'), (2, '0.200', '4000'))):
        with self.sessions() as db:
            total = sum((Decimal(line[2]) for line in lines), Decimal(0))
            sale = Sale(request_id=str(uuid.uuid4()), branch_id=branch, user_id=1,
                        total=total, cash=total, card=0, donation=0,
                        created_at=(moment or self.moment('2026-11-02')).astimezone(timezone.utc))
            db.add(sale)
            db.flush()
            for product_id, kg, amount in lines:
                db.add(SaleItem(sale_id=sale.id, product_id=product_id, supplier_id=1,
                                name='Synthetic', sku=str(product_id), kg=Decimal(kg),
                                price=Decimal(amount) / Decimal(kg), discount=0, total=Decimal(amount)))
            db.commit()
            return sale.id

    def test_multiple_items_sum_sale_money_once_and_kg_at_tashkent_day_bounds(self):
        beginning = self.moment('2026-11-02', 0)
        ending = self.moment('2026-11-03', 0)
        self.sale(beginning - timedelta(microseconds=1), lines=((1, '99', '9900'),))
        self.sale(beginning)
        self.sale(ending - timedelta(microseconds=1), lines=((1, '1.234', '12340'),))
        self.sale(ending, lines=((1, '88', '8800'),))
        self.sale(self.moment('2026-11-02', 15), branch=2, lines=((1, '2.500', '25000'),))
        branches = self.report()['branches']
        self.assertEqual([Decimal(row['sales']) for row in branches], [Decimal('17340'), Decimal('25000'), 0])
        self.assertEqual([Decimal(row['sales_kg']) for row in branches], [Decimal('1.534'), Decimal('2.5'), 0])
        self.assertTrue(branches[1]['archived'])
        self.assertIn('Sotilgan tovar: <b>1,534 kg</b>', self.report()['messages'][1]['text'])

    def test_closing_kg_and_money_both_ignore_midnight_and_morning_state(self):
        cutoff = self.moment('2026-11-03', 0).astimezone(timezone.utc)
        with self.sessions() as db:
            stock = db.get(Stock, 1)
            with patch.object(history, 'utc_now', return_value=cutoff - timedelta(microseconds=1)):
                stock.kg, stock.price, stock.discount = Decimal('3.456'), Decimal('100'), Decimal('10')
                db.commit()
            with patch.object(history, 'utc_now', return_value=cutoff):
                stock.kg, stock.price = Decimal('900'), Decimal('9999')
                db.commit()
            with patch.object(history, 'utc_now', return_value=cutoff + timedelta(hours=7)):
                stock.kg, stock.discount = Decimal('500'), Decimal('0')
                db.commit()
            closing = history.closing_balances(db, self.day)
            self.assertEqual(closing[1]['kg'], Decimal('3.457'))
            self.assertEqual(closing[1]['inventory'], Decimal('311.06'))
            self.assertEqual(history.closing_values(db, self.day)[1], closing[1]['inventory'])
        branch = self.report()['branches'][0]
        self.assertEqual(Decimal(branch['inventory_kg']), Decimal('3.457'))
        self.assertEqual(Decimal(branch['inventory']), Decimal('311.06'))
        self.assertIn('Qolgan tovar: <b>3,457 kg</b>', self.report()['messages'][1]['text'])

    def test_real_partial_return_removes_returned_line_from_reported_sales_kg(self):
        sale_id = self.sale()
        before = self.report()['branches'][0]
        self.assertEqual(Decimal(before['sales']), Decimal('5000'))
        self.assertEqual(Decimal(before['sales_kg']), Decimal('0.300'))
        with self.sessions() as db:
            first = db.scalar(select(SaleItem).where(SaleItem.sale_id == sale_id).order_by(SaleItem.id))
            data = EditSale(request_id=str(uuid.uuid4()), version=0, reason='Synthetic second item return',
                            customer='', cash=Decimal('1000'), card=Decimal('0'),
                            items=[{'item_id': first.id, 'product_id': first.product_id,
                                    'kg': first.kg, 'price': first.price, 'discount': first.discount}])
            moment = self.moment('2026-11-02', 20).astimezone(timezone.utc)
            with patch.object(history, 'utc_now', return_value=moment):
                apply_edit(db, sale_id, data, db.get(User, 1), edited_at=moment)
                db.commit()
            self.assertEqual(len(list(db.scalars(select(SaleItem).where(SaleItem.sale_id == sale_id)))), 1)
        after = self.report()['branches'][0]
        self.assertEqual(Decimal(after['sales']), Decimal('1000'))
        self.assertEqual(Decimal(after['sales_kg']), Decimal('0.100'))
        self.assertEqual(Decimal(after['inventory_kg']), Decimal(before['inventory_kg']) + Decimal('0.200'))

    def test_deleted_sale_and_lines_disappear_from_both_sales_fields(self):
        sale_id = self.sale()
        with self.sessions() as db:
            for item in db.scalars(select(SaleItem).where(SaleItem.sale_id == sale_id)):
                db.delete(item)
            db.delete(db.get(Sale, sale_id))
            db.commit()
        branch = self.report()['branches'][0]
        self.assertEqual(Decimal(branch['sales']), 0)
        self.assertEqual(Decimal(branch['sales_kg']), 0)
        self.assertEqual(Decimal(branch['inventory_kg']), Decimal('2.124'))

    def test_personalized_name_html_escaping_quantity_format_and_removed_note(self):
        with self.sessions() as db:
            report = reports.build_report(db, self.day, self.moment('2026-11-03', 8), recipient_name='  Muhammad <&>  ')
            self.assertIn('Assalomu alaykum, Muhammad &lt;&amp;&gt;!', report['messages'][0]['text'])
            for name in ('', ' ', 'a' * 121, None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    reports.build_report(db, self.day, self.moment('2026-11-03', 8), recipient_name=name)
        for value, expected in (('0.000', '0'), ('12.000', '12'), ('12.300', '12,3'),
                                ('12.345', '12,345'), ('1234567.890', '1 234 567,89')):
            self.assertEqual(reports.quantity_text(value), expected)
        self.assertTrue(all('Sotuv narxida' not in message['text'] for message in report['messages']))
        self.assertTrue(all('<i>' not in message['text'] for message in report['messages']))


if __name__ == '__main__':
    unittest.main()
