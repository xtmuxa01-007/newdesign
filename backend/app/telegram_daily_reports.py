"""Yesterday's branch accounting and personalized Telegram message formatting."""
from datetime import date, datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .accounting import ZERO
from .models import Branch, BranchArchive, Sale, SaleItem
from .routes_analytics import time_conditions
from .stock_valuation_history import closing_balances
from .telegram_report_recipients import read_report_settings

TZ = ZoneInfo('Asia/Tashkent')
MONTHS = ('yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul',
          'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr')


def money_text(value):
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError('Hisobot summasi noto‘g‘ri.')
    return format(number, ',.2f').replace(',', ' ').replace('.', ',').removesuffix(',00')


def day_text(day):
    return f'{day.day}-{MONTHS[day.month - 1]} {day.year}'


def quantity_text(value):
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError('Hisobot kilogrammi noto‘g‘ri.')
    return format(number, ',.3f').rstrip('0').rstrip('.').replace(',', ' ').replace('.', ',')


def build_report(db, report_day: date, generated_at: datetime, recipient_name='Muhammadjon Ahmedov'):
    if generated_at.tzinfo is None:
        raise ValueError('Hisobot vaqti uchun vaqt zonasi kerak.')
    if report_day >= generated_at.astimezone(TZ).date():
        raise ValueError('Faqat yakunlangan kunning hisoboti tayyorlanadi.')
    if not isinstance(recipient_name, str) or not 1 <= len(recipient_name.strip()) <= 120:
        raise ValueError('Qabul qiluvchining ismi noto‘g‘ri.')
    inventory = closing_balances(db, report_day)
    conditions = time_conditions(Sale, None, report_day, report_day)
    # Keep money on Sale and kilograms on SaleItem in separate grouped queries:
    # a sale containing multiple products must contribute its total only once.
    sales = dict(db.execute(select(Sale.branch_id, func.sum(Sale.total))
        .where(*conditions)
        .group_by(Sale.branch_id)).all())
    sales_kg = dict(db.execute(select(Sale.branch_id, func.sum(SaleItem.kg))
        .select_from(SaleItem).join(Sale, Sale.id == SaleItem.sale_id)
        .where(*conditions).group_by(Sale.branch_id)).all())
    archived = set(db.scalars(select(BranchArchive.branch_id)))
    branches = [{'id': branch.id, 'name': branch.name, 'archived': branch.id in archived,
                 'sales': str(sales.get(branch.id, ZERO)),
                 'sales_kg': str(sales_kg.get(branch.id, Decimal('0.000'))),
                 'inventory': str(inventory.get(branch.id, {}).get('inventory', ZERO)),
                 'inventory_kg': str(inventory.get(branch.id, {}).get('kg', Decimal('0.000')))}
                for branch in db.scalars(select(Branch).order_by(Branch.id))]
    heading = f'{day_text(report_day)} kungi savdo hisoboti'
    messages = [{'key': 'greeting', 'text':
        f'Assalomu alaykum, {escape(recipient_name.strip())}!\n\n'
        f'📊 <b>{heading}</b>\n\n'
        f'Har bir filial bo‘yicha savdo va kun yakunidagi ombor qoldig‘i quyida.'}]
    for branch in branches:
        label = escape(branch['name']) + (' (arxiv)' if branch['archived'] else '')
        messages.append({'key': f"branch:{branch['id']}", 'text':
            f'🏬 <b>{label}</b>\n'
            f'{day_text(report_day)}\n\n'
            f'💰 Savdo: <b>{money_text(branch["sales"])} so‘m</b>\n'
            f'⚖️ Sotilgan tovar: <b>{quantity_text(branch["sales_kg"])} kg</b>\n\n'
            f'📦 Kun yakunidagi tovar:\n<b>{money_text(branch["inventory"])} so‘m</b>\n'
            f'⚖️ Qolgan tovar: <b>{quantity_text(branch["inventory_kg"])} kg</b>'})
    if not branches:
        messages[0]['text'] += '\n\nFiliallar mavjud emas.'
    return {'date': report_day.isoformat(), 'timezone': 'Asia/Tashkent',
            'generated_at': generated_at.isoformat(), 'branches': branches, 'messages': messages}

