"""Read-only Excel snapshots of sales and analytics, with safe text cells."""
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from math import ceil
import re

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.utils import get_column_letter
from .routes_finance import TZ

XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MONEY_FORMAT = '#,##0.00;[Red](#,##0.00);0.00'
KG_FORMAT = '#,##0.000;[Red](#,##0.000);0.000'
HEADER_FILL = PatternFill('solid', fgColor='195C53')
BODY_FONT = Font(name='Arial', size=11, color='183F37')
MUTED_FONT = Font(name='Arial', size=11, color='5D706A')
GOLD = 'D9C58F'
RULE = Side(style='hair', color='DDE6E0')
BODY_BORDER = Border(bottom=RULE)
WHITE_RULE = Side(style='thin', color='FFFFFF')
ROW_FILL = PatternFill('solid', fgColor='F1F5F0')
FORBIDDEN_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def number(value, places=2):
    """Keep oversized values exact as text beyond Excel's 15-digit precision."""
    value = Decimal(str(value or '0')).quantize(Decimal(1).scaleb(-places))
    text = format(value, 'f')
    digits = text.lstrip('-').replace('.', '').lstrip('0')
    return text if len(digits) > 15 else value


def local_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    # Excel rounds sub-millisecond times; avoid moving 23:59:59.999999 to tomorrow.
    # The column label specifies Tashkent because Excel has no timezone dates.
    return value.astimezone(TZ).replace(tzinfo=None, microsecond=0)


def cell_value(cell, value, number_format=None):
    if isinstance(value, str):
        value = FORBIDDEN_XML.sub('', value)
    cell.value = value
    if isinstance(value, str):
        # Customer, SKU and branch names must never become Excel formulas.
        cell.data_type = 's'
    if number_format:
        cell.number_format = number_format
    cell.font = BODY_FONT
    cell.alignment = Alignment(horizontal='right' if number_format or isinstance(value, (int, Decimal)) else 'left',
                               vertical='center', wrap_text=isinstance(value, str) and not number_format, indent=1)


def print_settings(sheet, title):
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_margins = PageMargins(left=0.3, right=0.3, top=0.5, bottom=0.5, header=0.2, footer=0.2)
    sheet.oddHeader.left.text = 'TIN / Marwa Company'
    sheet.oddHeader.right.text = title
    sheet.oddFooter.left.text = 'Toshkent vaqti / so‘m'
    sheet.oddFooter.right.text = 'Sahifa &P / &N'
    for part in (sheet.oddHeader.left, sheet.oddHeader.right, sheet.oddFooter.left, sheet.oddFooter.right):
        part.font, part.size, part.color = 'Arial', 9, '5D706A'


def wrapped_height(text, width, minimum=26):
    # Reserve normal line height rather than relying on Excel to autofit on open.
    lines = sum(max(1, ceil(len(line) / max(8, width - 3))) for line in str(text).split('\n'))
    return min(240, max(minimum, lines * 15 + 8))


def table(workbook, title, headers, rows, formats=None, widths=None):
    sheet = workbook.create_sheet(title)
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 90
    sheet.sheet_properties.tabColor = 'D9C58F'
    sheet.freeze_panes = 'A2'
    print_settings(sheet, title)
    sheet.print_title_rows = '1:1'
    header_height = 44
    for column, header in enumerate(headers, 1):
        cell = sheet.cell(1, column)
        cell_value(cell, header)
        cell.font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = Border(right=WHITE_RULE, bottom=Side(style='medium', color=GOLD))
        width = (widths or {}).get(column, 24 if (formats or {}).get(column) else 22)
        if header in ('Savdo №', 'To‘lov №'):
            width = 13
        elif header == 'Holat':
            width = 27
        elif header == 'SKU':
            width = 20
        sheet.column_dimensions[get_column_letter(column)].width = width
        header_height = max(header_height, wrapped_height(header, width))
    sheet.row_dimensions[1].height = header_height
    last = 1
    for last, row in enumerate(rows, 2):
        if last > 1048576:
            raise HTTPException(422, 'Excel jadvali qator chegarasidan oshdi. Sana oralig‘ini qisqartiring.')
        height = 28
        for column, value in enumerate(row, 1):
            cell = sheet.cell(last, column)
            fmt = (formats or {}).get(column)
            cell_value(cell, value, fmt)
            cell.border = BODY_BORDER
            if isinstance(value, str) and not fmt:
                height = max(height, wrapped_height(value, sheet.column_dimensions[get_column_letter(column)].width))
            if last % 2 == 0:
                cell.fill = ROW_FILL
        sheet.row_dimensions[last].height = height
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{last}'
    sheet.print_area = sheet.auto_filter.ref
    return sheet


def report_book(title, start, end, branch_name, summary):
    workbook = Workbook()
    report = workbook.active
    report.title = 'Hisobot'
    report.sheet_view.showGridLines = False
    report.sheet_view.zoomScale = 90
    report.sheet_properties.tabColor = '195C53'
    report.column_dimensions['A'].width = 48
    report.column_dimensions['B'].width = 34
    report.column_dimensions['C'].width = 5
    print_settings(report, title)
    report.merge_cells('A1:B1')
    cell_value(report['A1'], title)
    report['A1'].font = Font(name='Arial', size=16, bold=True, color='195C53')
    report.row_dimensions[1].height = 40
    report.merge_cells('A2:B2')
    cell_value(report['A2'], 'TIN / Marwa Company')
    report['A2'].font = Font(name='Arial', size=11, color='5D706A')
    report['A2'].border = Border(bottom=Side(style='medium', color=GOLD))
    report['B2'].border = Border(bottom=Side(style='medium', color=GOLD))
    report.row_dimensions[2].height = 28
    cell_value(report['A3'], 'Filial')
    cell_value(report['B3'], branch_name)
    cell_value(report['A4'], 'Davr (ikkala kun ham kiradi)')
    cell_value(report['B4'], f'{start or "Boshidan"} — {end or "Hozirgacha"}')
    cell_value(report['A5'], 'Vaqt zonasi / pul birligi')
    cell_value(report['B5'], 'Asia/Tashkent / so‘m')
    cell_value(report['A6'], 'Tayyorlangan vaqt (Toshkent)')
    cell_value(report['B6'], local_time(datetime.now(timezone.utc)), 'dd.mm.yyyy hh:mm')
    for row in range(3, 7):
        report.cell(row, 1).font = MUTED_FONT
        report.cell(row, 2).alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        report.row_dimensions[row].height = max(26, wrapped_height(report.cell(row, 2).value, 34))
    report.row_dimensions[7].height = 12
    for index, (label, value, fmt) in enumerate(summary, 8):
        cell_value(report.cell(index, 1), label)
        cell_value(report.cell(index, 2), value, fmt)
        report.row_dimensions[index].height = 32
        for column in (1, 2):
            cell = report.cell(index, column)
            cell.fill = PatternFill('solid', fgColor='E8F0E8' if index == 8 else 'F5F6EF' if index % 2 == 0 else 'FFFFFF')
            cell.border = BODY_BORDER
        report.cell(index, 1).font = Font(name='Arial', size=11, bold=True, color='195C53')
        report.cell(index, 2).font = Font(name='Arial', size=12, bold=True, color='195C53')
    workbook.calculation.fullCalcOnLoad = True
    return workbook


def serialize(workbook):
    result = BytesIO()
    workbook.save(result)
    return result.getvalue()


def report_note(sheet, start, end, text):
    cell_value(sheet.cell(start, 1), text)
    sheet.merge_cells(start_row=start, start_column=1, end_row=end, end_column=2)
    cell = sheet.cell(start, 1)
    cell.font = Font(name='Arial', size=11, italic=True, color='5D706A')
    cell.alignment = Alignment(vertical='center', wrap_text=True, indent=1)
    cell.fill = PatternFill('solid', fgColor='F7F3E6')
    cell.border = Border(left=Side(style='medium', color=GOLD))
    for row in range(start, end + 1):
        sheet.row_dimensions[row].height = 22


def sales_workbook(sales, branches, start, end, branch_id):
    branch_names = {branch['id']: branch['name'] for branch in branches}
    values = dict(goods=Decimal(0), cash=Decimal(0), card=Decimal(0),
                  donation=Decimal(0), debt_paid=Decimal(0), debt_open=Decimal(0), kg=Decimal(0))
    rows, items, payments = [], [], []
    for sale in sales:
        cash, card = Decimal(sale['cash']), Decimal(sale['card'])
        debt = sale.get('debt')
        payment = debt.get('payment') if debt else None
        legacy_paid = Decimal(payment['cash']) + Decimal(payment['card']) if payment else Decimal(0)
        paid = Decimal(debt.get('paid_amount', legacy_paid)) if debt else Decimal(0)
        outstanding = Decimal(debt.get('remaining_amount', Decimal(debt['amount']) - paid)) if debt else Decimal(0)
        received = cash + card + paid
        for key, amount in (('goods', sale['total']), ('cash', cash), ('card', card),
                            ('donation', sale['donation']), ('debt_paid', paid), ('debt_open', outstanding)):
            values[key] += Decimal(amount)
        name = branch_names.get(sale['branch_id'], str(sale['branch_id']))
        rows.append([sale['id'], local_time(sale['created_at']), name, sale.get('cashier', ''),
                     sale.get('customer') or 'Oddiy savdo', number(sale['total']), number(cash),
                     number(card), number(paid), number(received), number(sale['donation']),
                     number(outstanding), 'To‘langan qarz' if debt and outstanding == 0 else
                     'Qisman to‘langan qarz' if debt and paid else 'Ochiq qarz' if debt else 'Oddiy savdo',
                     number(debt['amount']) if debt else number(0), debt.get('due_date') if debt else ''])
        for receipt in debt.get('payments', [payment] if payment else []) if debt else []:
            cancelled = bool(receipt.get('cancelled_at') or (receipt.get('operation') or {}).get('cancelled'))
            payments.append([sale['id'], name, sale.get('customer') or '', receipt['id'],
                local_time(receipt['created_at']), receipt.get('actor') or '',
                number(receipt['cash']), number(receipt['card']),
                number(Decimal(receipt['cash']) + Decimal(receipt['card'])),
                'Bekor qilingan' if cancelled else 'Hisobga olindi',
                local_time(receipt['cancelled_at']) if receipt.get('cancelled_at') else '',
                receipt.get('cancel_reason') or ''])
        for item in sale['items']:
            values['kg'] += Decimal(item['kg'])
            items.append([sale['id'], name, item['name'], item['sku'], number(item['kg'], 3),
                          number(item['price']), number(item['discount']),
                          number(item.get('mini_discount', '0')), number(item['total'])])
    received = values['cash'] + values['card'] + values['debt_paid']
    workbook = report_book('Savdolar tarixi', start, end,
        branch_names.get(branch_id, 'Barcha filiallar'), [
            ('Savdolar soni', len(sales), '0'), ('Sotilgan mahsulot qiymati', number(values['goods']), MONEY_FORMAT),
            ('Jami olingan (qarz to‘lovi bilan)', number(received), MONEY_FORMAT),
            ('Savdoda naqd olingan', number(values['cash']), MONEY_FORMAT),
            ('Savdoda karta olingan', number(values['card']), MONEY_FORMAT),
            ('Shu savdolardan keyin to‘langan qarz', number(values['debt_paid']), MONEY_FORMAT),
            ('Shu savdolarning joriy ochiq qarzi', number(values['debt_open']), MONEY_FORMAT),
            ('Savdoda yig‘ilgan ehson', number(values['donation']), MONEY_FORMAT),
            ('Sotilgan kilogramm', number(values['kg'], 3), KG_FORMAT)])
    report_note(workbook['Hisobot'], 19, 20,
        'Qarz to‘lovi savdo sanasidan keyin kelgan bo‘lishi mumkin; bu savdolarning joriy holati.')
    workbook['Hisobot'].print_area = 'A1:B20'
    table(workbook, 'Savdolar', ['Savdo №', 'Sana va vaqt (Toshkent)', 'Filial', 'Kassir', 'Mijoz',
        'Mahsulot qiymati (so‘m)', 'Naqd (so‘m)', 'Karta (so‘m)', 'Keyin to‘langan qarz (so‘m)',
        'Jami olingan (so‘m)', 'Ehson (so‘m)', 'Joriy ochiq qarz (so‘m)', 'Holat',
        'Qarzning jami summasi (so‘m)', 'Qaytarish sanasi'], rows,
        formats={**{column: MONEY_FORMAT for column in range(6, 13)}, 14: MONEY_FORMAT, 2: 'dd.mm.yyyy hh:mm'},
        widths={2: 25, 3: 25, 4: 25, 5: 25})
    table(workbook, 'Mahsulotlar', ['Savdo №', 'Filial', 'Mahsulot', 'SKU', 'Kg', 'Narx/kg (so‘m)',
        'Chegirma (%)', 'Mini chegirma (so‘m)', 'Qator qiymati (so‘m)'], items,
        formats={5: KG_FORMAT, **{column: MONEY_FORMAT for column in range(6, 10)}},
        widths={2: 25, 3: 35})
    table(workbook, 'Qarz to‘lovlari', ['Savdo №', 'Filial', 'Mijoz', 'To‘lov №',
        'To‘lov vaqti (Toshkent)', 'Qabul qilgan', 'Naqd (so‘m)', 'Karta (so‘m)',
        'Jami (so‘m)', 'Holat', 'Bekor qilish vaqti (Toshkent)', 'Bekor qilish sababi'], payments,
        formats={**{column: MONEY_FORMAT for column in range(7, 10)},
                 5: 'dd.mm.yyyy hh:mm', 11: 'dd.mm.yyyy hh:mm'}, widths={2: 25, 3: 25, 5: 25, 12: 35})
    return serialize(workbook)


METRICS = [('goods_total', 'Mahsulot savdosi (so‘m)', MONEY_FORMAT),
    ('period_inflow', 'Davrda jami tushum (so‘m)', MONEY_FORMAT), ('sales_count', 'Savdolar soni', '0'),
    ('kg', 'Sotilgan kg', KG_FORMAT), ('average_sale', 'O‘rtacha savdo (so‘m)', MONEY_FORMAT),
    ('cash', 'Savdoda naqd (so‘m)', MONEY_FORMAT), ('card', 'Savdoda karta (so‘m)', MONEY_FORMAT),
    ('debt_collected', 'Davrda undirilgan qarz (so‘m)', MONEY_FORMAT),
    ('debt_created', 'Savdoda berilgan qarz (so‘m)', MONEY_FORMAT),
    ('debt_outstanding', 'Shu savdolarning joriy qarzi (so‘m)', MONEY_FORMAT),
    ('donation', 'Savdoda ehson (so‘m)', MONEY_FORMAT), ('expenses', 'Davr xarajati (so‘m)', MONEY_FORMAT)]


def metric_values(row):
    return [int(row.get(key, 0)) if key == 'sales_count' else number(row.get(key, '0'), 3 if key == 'kg' else 2)
            for key, _, _ in METRICS]


def analytics_workbook(data):
    scope = data['filter']
    names = {branch['id']: branch['name'] for branch in data['branches']}
    values = metric_values(data['summary'])
    workbook = report_book('Savdolar analizi', scope['start'], scope['end'],
        names.get(scope['branch_id'], 'Barcha filiallar'),
        [(label, value, fmt) for (_, label, fmt), value in zip(METRICS, values)])
    note = ('Savdo qiymati va savdoda olingan pul savdo sanasi bo‘yicha. Undirilgan qarz va xarajatlar '
            'o‘z to‘lov sanasi bo‘yicha. Jami tushum = savdoda naqd + karta + davrda undirilgan qarz. '
            'Joriy qarz tanlangan davr savdolaridan hozir to‘lanmagan qoldiq; foyda hisoblanmagan.')
    report_note(workbook['Hisobot'], 22, 25, note)
    headers = [label for _, label, _ in METRICS]
    formats = {column: fmt for column, (_, _, fmt) in enumerate(METRICS, 2)}
    daily = table(workbook, 'Kunlar', ['Sana'] + headers,
                  ([row['date']] + metric_values(row) for row in data['daily']), formats=formats)
    monthly = table(workbook, 'Oylar', ['Oy'] + headers,
                    ([row['month']] + metric_values(row) for row in data['monthly']), formats=formats)
    branch_sheet = table(workbook, 'Filiallar', ['Filial', 'Holat'] + headers,
        ([row['name'], 'Arxiv' if row['archived'] else 'Faol'] + metric_values(row) for row in data['branches']),
        formats={column + 1: fmt for column, fmt in formats.items()}, widths={1: 30})
    table(workbook, 'Mahsulotlar', ['Mahsulot', 'SKU', 'Sotilgan kg', 'Qator qiymati (so‘m)'],
        ([row['name'], row['sku'], number(row['kg'], 3), number(row['total'])] for row in data['products']),
        formats={3: KG_FORMAT, 4: MONEY_FORMAT}, widths={1: 35})
    if monthly.max_row > 1:
        chart = LineChart()
        chart.title = 'Oylik mahsulot savdosi'
        chart.y_axis.title = 'So‘m'
        chart.add_data(Reference(monthly, min_col=2, max_col=2, min_row=1, max_row=monthly.max_row), titles_from_data=True)
        chart.set_categories(Reference(monthly, min_col=1, min_row=2, max_row=monthly.max_row))
        chart.width, chart.height = 23, 9.2
        chart.legend = None
        chart.y_axis.numFmt = '#,##0'
        chart.series[0].graphicalProperties.line.solidFill = '195C53'
        chart.series[0].graphicalProperties.line.width = 25000
        chart.smooth = False
        workbook['Hisobot'].add_chart(chart, 'D3')
    if branch_sheet.max_row > 1:
        chart = BarChart()
        chart.title = 'Filiallar savdosi'
        chart.y_axis.title = 'So‘m'
        chart.add_data(Reference(branch_sheet, min_col=3, max_col=3, min_row=1, max_row=branch_sheet.max_row), titles_from_data=True)
        chart.set_categories(Reference(branch_sheet, min_col=1, min_row=2, max_row=branch_sheet.max_row))
        chart.width, chart.height = 23, 9.2
        chart.legend = None
        chart.y_axis.numFmt = '#,##0'
        chart.series[0].graphicalProperties.solidFill = '195C53'
        chart.series[0].graphicalProperties.line.noFill = True
        workbook['Hisobot'].add_chart(chart, 'D16')
    workbook['Hisobot'].print_area = 'A1:R35'
    return serialize(workbook)
