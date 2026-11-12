"""Excel exports retain report scope, dates, exact amounts and safe text."""
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
import os
import unittest
import uuid
from unittest.mock import patch

from openpyxl import load_workbook
from sqlalchemy import select
import test_branch_archive as fixture
from app.excel_reports import XLSX_TYPE, number, sales_workbook
from app.models import Audit, Debt, DebtPayment, Debtor, Sale, SaleItem
from app import routes_exports


class ExcelExportsTest(unittest.TestCase):
    setUp = fixture.BranchArchiveTest.setUp
    tearDown = fixture.BranchArchiveTest.tearDown
    client = fixture.BranchArchiveTest.client

    def seed_sale(self, db, sale_id, moment, branch_id=1, total='100', cash='100', card='0', donation='0'):
        sale = Sale(id=sale_id, request_id=str(uuid.uuid4()), branch_id=branch_id, user_id=3,
                    customer='=1+1', total=Decimal(total), cash=Decimal(cash), card=Decimal(card),
                    donation=Decimal(donation), created_at=moment)
        db.add(sale)
        db.flush()
        db.add(SaleItem(sale_id=sale.id, product_id=1, supplier_id=1, name='=SUM(A1:A2)',
                        sku='@SKU-1', kg=Decimal('1.250'), price=Decimal(total) / Decimal('1.250'),
                        discount=0, total=Decimal(total)))
        return sale

    def workbook(self, response):
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else '')
        self.assertTrue(response.headers['content-type'].startswith(XLSX_TYPE))
        self.assertIn('.xlsx', response.headers['content-disposition'])
        self.assertTrue(response.content.startswith(b'PK'))
        return load_workbook(BytesIO(response.content))

    def test_history_export_full_tashkent_day_branch_amounts_and_safe_text(self):
        with self.sessions() as db:
            self.seed_sale(db, 10, datetime(2026, 9, 30, 18, 59, 59, 999999, tzinfo=timezone.utc))
            self.seed_sale(db, 11, datetime(2026, 9, 30, 19, tzinfo=timezone.utc), cash='110', donation='10')
            self.seed_sale(db, 12, datetime(2026, 10, 1, 18, 59, 59, 999999, tzinfo=timezone.utc), total='200', cash='0', card='150')
            self.seed_sale(db, 13, datetime(2026, 10, 1, 19, tzinfo=timezone.utc))
            self.seed_sale(db, 14, datetime(2026, 10, 1, 10, tzinfo=timezone.utc), branch_id=2)
            db.add(Debtor(id=1, branch_id=1, first_name='Fake', last_name='Customer',
                          phone1='0000000', phone2='1111111', address='Fixture'))
            db.flush()
            db.add(Debt(id=1, branch_id=1, sale_id=12, debtor_id=1, amount=50,
                        due_date=date(2026, 10, 10)))
            db.flush()
            db.add(DebtPayment(request_id=str(uuid.uuid4()), debt_id=1, branch_id=1, user_id=2,
                               cash=20, card=30, created_at=datetime(2026, 10, 2, 10, tzinfo=timezone.utc)))
            db.commit()
        response = self.owner.get('/api/sales/export.xlsx?branch_id=1&start=2026-10-01&end=2026-10-01')
        workbook = self.workbook(response)
        self.assertEqual(workbook.sheetnames, ['Hisobot', 'Savdolar', 'Mahsulotlar', 'Qarz to‘lovlari'])
        sales = workbook['Savdolar']
        self.assertEqual([sales.cell(row, 1).value for row in (2, 3)], [11, 12])
        self.assertEqual(sales['B2'].value, datetime(2026, 10, 1))
        self.assertEqual(sales['B3'].value.date(), date(2026, 10, 1))
        self.assertEqual((sales['F2'].value, sales['J2'].value, sales['K2'].value), (100, 110, 10))
        self.assertEqual((sales['I3'].value, sales['J3'].value, sales['L3'].value), (50, 200, 0))
        self.assertEqual((workbook['Hisobot']['B9'].value, workbook['Hisobot']['B10'].value), (300, 310))
        self.assertEqual((sales['E2'].value, sales['E2'].data_type), ('=1+1', 's'))
        items = workbook['Mahsulotlar']
        self.assertEqual((items['C2'].value, items['C2'].data_type), ('=SUM(A1:A2)', 's'))
        self.assertEqual(items['E2'].value, 1.25)
        self.assertEqual(items['E2'].number_format, '#,##0.000;[Red](#,##0.000);0.000')
        self.assertEqual(sales.freeze_panes, 'A2')
        self.assertEqual(sales.auto_filter.ref, 'A1:O3')
        with self.sessions() as db:
            audit = db.scalar(select(Audit).where(Audit.action == 'Savdolar Excel yuklandi'))
            self.assertEqual((audit.branch_id, audit.detail['count']), (1, 2))

    def test_export_all_records_beyond_history_page_and_admin_scope(self):
        moment = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
        with self.sessions() as db:
            for sale_id in range(100, 201):
                self.seed_sale(db, sale_id, moment)
            self.seed_sale(db, 201, moment, branch_id=2)
            db.commit()
        admin = self.client('admin')
        workbook = self.workbook(admin.get('/api/sales/export.xlsx?start=2026-10-05&end=2026-10-05'))
        self.assertEqual(workbook['Savdolar'].max_row, 102)
        self.assertEqual(workbook['Hisobot']['B8'].value, 101)
        self.assertEqual(admin.get('/api/sales/export.xlsx?branch_id=2').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/sales/export.xlsx').status_code, 403)
        self.assertEqual(self.client().get('/api/sales/export.xlsx').status_code, 401)
        all_branches = self.workbook(self.owner.get('/api/sales/export.xlsx?start=2026-10-05&end=2026-10-05'))
        self.assertEqual(all_branches['Savdolar'].max_row, 103)

    def test_empty_range_and_invalid_dates(self):
        workbook = self.workbook(self.owner.get('/api/sales/export.xlsx?branch_id=1&start=2026-10-01&end=2026-10-31'))
        self.assertEqual(workbook['Hisobot']['B8'].value, 0)
        self.assertEqual(workbook['Savdolar'].max_row, 1)
        for query in ('start=2026-10-31&end=2026-10-01', 'start=not-a-date', 'branch_id=999'):
            response = self.owner.get('/api/sales/export.xlsx?' + query)
            self.assertIn(response.status_code, (404, 422))
        for endpoint in ('/api/sales', '/api/sales/export', '/api/sales/export.xlsx'):
            for query in ('end=9999-12-31', 'start=0001-01-01'):
                with self.subTest(endpoint=endpoint, query=query):
                    response = self.owner.get(endpoint + '?' + query)
                    self.assertEqual(response.status_code, 422, response.text)

    def test_analytics_workbook_matches_same_date_scope_and_embeds_charts(self):
        with self.sessions() as db:
            self.seed_sale(db, 21, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), total='123.45', cash='130', donation='6.55')
            self.seed_sale(db, 22, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), branch_id=2)
            db.commit()
        query = '?branch_id=1&start=2026-10-01&end=2026-10-31'
        data = self.owner.get('/api/sales/analytics' + query).json()
        workbook = self.workbook(self.owner.get('/api/sales/analytics/export.xlsx' + query))
        self.assertEqual(workbook.sheetnames, ['Hisobot', 'Kunlar', 'Oylar', 'Filiallar', 'Mahsulotlar'])
        self.assertEqual(Decimal(str(workbook['Hisobot']['B8'].value)), Decimal(data['summary']['goods_total']))
        self.assertEqual(Decimal(str(workbook['Hisobot']['B9'].value)), Decimal(data['summary']['period_inflow']))
        self.assertEqual(workbook['Hisobot']['B10'].value, data['summary']['sales_count'])
        self.assertEqual(len(workbook['Hisobot']._charts), 2)
        self.assertEqual(workbook['Kunlar'].max_row, len(data['daily']) + 1)
        self.assertEqual(workbook['Filiallar'].max_row, 2)
        admin = self.client('admin')
        self.assertEqual(admin.get('/api/sales/analytics/export.xlsx?branch_id=2').status_code, 403)
        self.assertEqual(self.client('cashier').get('/api/sales/analytics/export.xlsx').status_code, 403)

    def test_large_exact_values_and_xml_controls_are_safe_in_excel(self):
        self.assertEqual(number('999999999999999.99'), '999999999999999.99')
        self.assertEqual(number('10000.50'), Decimal('10000.50'))
        data = [{'id': 1, 'created_at': '2026-10-01T10:00:00+00:00', 'branch_id': 1,
                 'cashier': '\x01=2+2', 'customer': '=1+1', 'total': '999999999999999.99',
                 'cash': '999999999999999.99', 'card': '0', 'donation': '0', 'debt': None, 'items': []}]
        workbook = load_workbook(BytesIO(sales_workbook(data, [{'id': 1, 'name': '=Branch'}], None, None, 1)))
        self.assertEqual(workbook['Savdolar']['F2'].value, '999999999999999.99')
        self.assertEqual(workbook['Savdolar']['F2'].data_type, 's')
        self.assertEqual(workbook['Savdolar']['D2'].value, '=2+2')
        for sheet in workbook:
            self.assertFalse(any(cell.data_type == 'f' for row in sheet for cell in row))


@unittest.skipUnless(os.getenv('CRM_TEST_POSTGRES') == '1', 'Disposable CI PostgreSQL kerak')
class ExcelExportsPostgresTest(ExcelExportsTest):
    postgres = True

    def test_concurrent_edit_retains_consistent_old_header_and_items_snapshot(self):
        with self.sessions() as db:
            self.seed_sale(db, 31, datetime(2026, 10, 1, 10, tzinfo=timezone.utc))
            db.commit()
        original = routes_exports.sale_data
        changed = False

        def edit_after_header(snapshot, sale):
            nonlocal changed
            if not changed:
                # A second PC commits after the export selected its sale header
                # but before sale_data queries the associated rows.
                with self.sessions() as writer:
                    current = writer.get(Sale, sale.id)
                    current.total, current.cash = Decimal('200'), Decimal('200')
                    item = writer.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
                    item.kg, item.total = Decimal('2.500'), Decimal('200')
                    writer.commit()
                changed = True
            return original(snapshot, sale)

        with patch('app.routes_exports.sale_data', side_effect=edit_after_header):
            workbook = self.workbook(self.owner.get(
                '/api/sales/export.xlsx?branch_id=1&start=2026-10-01&end=2026-10-01'))
        self.assertTrue(changed)
        self.assertEqual((workbook['Savdolar']['F2'].value, workbook['Savdolar']['J2'].value), (100, 100))
        self.assertEqual((workbook['Mahsulotlar']['E2'].value, workbook['Mahsulotlar']['I2'].value), (1.25, 100))
        with self.sessions() as db:
            self.assertEqual(db.get(Sale, 31).total, Decimal('200'))
            self.assertEqual(db.scalar(select(SaleItem).where(SaleItem.sale_id == 31)).total, Decimal('200'))
