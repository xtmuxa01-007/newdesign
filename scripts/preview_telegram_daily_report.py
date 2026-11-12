"""Render the real report formatter against synthetic, isolated in-memory data.

This command never loads .env, integration credentials, or the company's database,
and never contacts Telegram. Open the generated HTML to review message contents.
"""
import argparse
import base64
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo('Asia/Tashkent')
RECIPIENTS = {
    'muhammad': {'username': 'MUHAMMAD_AHMED0V', 'name': 'Muhammadjon Ahmedov'},
    'abduqodir': {'username': 'abduqodir_1', 'name': 'Abduqodir Abdumalikov'},
}


class TelegramText(HTMLParser):
    """Keep Telegram's basic formatting, with no active content or links."""
    allowed = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.allowed:
            self.parts.append('<' + tag + '>')

    def handle_endtag(self, tag):
        if tag in self.allowed:
            self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        self.parts.append(escape(data))


def telegram_html(value):
    parser = TelegramText()
    parser.feed(value)
    parser.close()
    return ''.join(parser.parts)


def sample_report(report_day, recipient_name='Abduqodir Abdumalikov'):
    # Override connection selection before importing *any* application module.
    # Do not use the shared production engine even if DATABASE_URL was inherited.
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    sys.path.insert(0, str(ROOT / 'backend'))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.db import Base
    from app.models import Branch, Product, Sale, SaleItem, Stock, Supplier, User
    from app.accounting import line_total
    from app import stock_valuation_history as history
    from app.telegram_daily_reports import build_report

    target = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(target)
    opening = datetime.combine(report_day, time(7), TZ).astimezone(timezone.utc)
    closing = datetime.combine(report_day, time(22, 30), TZ).astimezone(timezone.utc)
    generated_at = datetime.combine(report_day + timedelta(days=1), time(8), TZ)
    today_change = generated_at.replace(hour=7).astimezone(timezone.utc)
    names = ('Marwa Shahrixon', 'Marwa Andijon', 'Marwa Toshkent')
    closing_kg = (Decimal('3474.454'), Decimal('2971.566'), Decimal('1.000'))
    desired_values = (Decimal('273616930.64'), Decimal('228167008.30'), Decimal('80000.00'))
    prices = tuple((amount / kg).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                   for amount, kg in zip(desired_values, closing_kg))
    closing_values = tuple(line_total(kg, price, Decimal(0)) for kg, price in zip(closing_kg, prices))
    # Product, kg and sale price are actual SaleItem fixtures, not display-only
    # numbers. A two-product sale proves its money is not doubled by item joins.
    sales = ((1, ((1, Decimal('8.750'), Decimal('80000')), (2, Decimal('3.750'), Decimal('80000')))),
             (1, ((1, Decimal('6.155'), Decimal('80000')),)),
             (2, ((2, Decimal('26.125'), Decimal('80000')), (3, Decimal('21.061'), Decimal('80000')))))
    expected_sales = [Decimal(0), Decimal(0), Decimal(0)]
    expected_sales_kg = [Decimal(0), Decimal(0), Decimal(0)]
    for branch_id, lines in sales:
        expected_sales[branch_id - 1] += sum((line_total(kg, price, Decimal(0)) for _, kg, price in lines), Decimal(0))
        expected_sales_kg[branch_id - 1] += sum((kg for _, kg, _ in lines), Decimal(0))

    try:
        with Session(target) as db:
            with patch.object(history, 'utc_now', return_value=opening):
                history.initialize_history(db)
                db.add_all([Branch(id=i, name=name) for i, name in enumerate(names, 1)])
                db.add(Supplier(id=1, name='Sinov ta’minotchisi'))
                db.flush()
                db.add(User(id=1, username='preview_only', name='Lokal sinov',
                            role='boss', password_hash='preview-not-a-login'))
                for i in range(1, 4):
                    db.add(Product(id=i, name='Sinov mahsuloti ' + str(i),
                                   sku='PREVIEW-' + str(i), supplier_id=1))
                db.flush()
                for i, (kg, price) in enumerate(zip(closing_kg, prices), 1):
                    main_sold_kg = sum((quantity for branch_id, lines in sales if branch_id == i
                                        for product_id, quantity, _ in lines if product_id == i), Decimal(0))
                    db.add(Stock(id=i, branch_id=i, product_id=i, kg=kg + main_sold_kg,
                                 price=price, discount=Decimal('0.00')))
                db.add_all([Stock(id=4, branch_id=1, product_id=2, kg=Decimal('3.750'), price=80000, discount=0),
                            Stock(id=5, branch_id=2, product_id=3, kg=Decimal('21.061'), price=80000, discount=0)])
                db.commit()

            # Yesterday's final stock version; this is the report's valuation.
            with patch.object(history, 'utc_now', return_value=closing):
                for i in range(1, 4):
                    db.get(Stock, i).kg = closing_kg[i - 1]
                db.get(Stock, 4).kg = Decimal('0')
                db.get(Stock, 5).kg = Decimal('0')
                for i, (branch_id, lines) in enumerate(sales, 1):
                    amount = sum((line_total(kg, price, Decimal(0)) for _, kg, price in lines), Decimal(0))
                    sale = Sale(request_id='preview-sale-' + str(i), branch_id=branch_id,
                                user_id=1, customer='SINOV MA’LUMOTI', total=amount,
                                cash=amount, card=Decimal('0'), donation=Decimal('0'),
                                created_at=closing - timedelta(minutes=i))
                    db.add(sale)
                    db.flush()
                    for product_id, kg, price in lines:
                        db.add(SaleItem(sale_id=sale.id, product_id=product_id, supplier_id=1,
                                        name='Sinov mahsuloti ' + str(product_id), sku='PREVIEW-' + str(product_id),
                                        kg=kg, price=price, discount=0, total=line_total(kg, price, Decimal(0))))
                db.commit()

            # Today's stock and sale are intentionally different. Neither belongs
            # in yesterday's totals or yesterday's closing inventory valuation.
            with patch.object(history, 'utc_now', return_value=today_change):
                db.get(Stock, 1).kg = closing_kg[0] + Decimal('100.000')
                db.get(Stock, 2).price = Decimal('999.00')
                today_sale = Sale(request_id='preview-today-excluded', branch_id=1, user_id=1,
                            customer='BUGUNGI SINOV', total=Decimal('500000.00'),
                            cash=Decimal('500000.00'), card=Decimal('0'), donation=Decimal('0'),
                            created_at=today_change)
                db.add(today_sale)
                db.flush()
                db.add(SaleItem(sale_id=today_sale.id, product_id=1, supplier_id=1,
                                name='Bugungi sinov mahsuloti', sku='PREVIEW-1', kg=Decimal('5.000'),
                                price=Decimal('100000'), discount=0, total=Decimal('500000')))
                db.commit()

            with patch.object(history, 'utc_now', return_value=generated_at.astimezone(timezone.utc)):
                report = build_report(db, report_day, generated_at, recipient_name=recipient_name)
            observed = {item['id']: item for item in report['branches']}
            for i, (sales, inventory) in enumerate(zip(expected_sales, closing_values), 1):
                if (Decimal(observed[i]['sales']) != sales or
                        Decimal(observed[i]['inventory']) != inventory or
                        Decimal(observed[i]['sales_kg']) != expected_sales_kg[i - 1] or
                        Decimal(observed[i]['inventory_kg']) != closing_kg[i - 1]):
                    raise ValueError('Sinov hisoboti kechagi savdo, kilogramm yoki kun yakunidagi qoldiqqa mos emas.')
            return report
    finally:
        target.dispose()


def render(report, report_day, recipient=None):
    recipient = recipient or RECIPIENTS['abduqodir']
    bubbles = []
    for message in report['messages']:
        bubbles.append('<article class="bubble"><div class="message">' +
                       telegram_html(message['text']) +
                       '</div><div class="message-time">08:00</div></article>')
    report_date = report_day.strftime('%d.%m.%Y')
    logo = ROOT / 'desktop' / 'assets' / 'tin-logo.png'
    avatar = ('<img src="data:image/png;base64,' + base64.b64encode(logo.read_bytes()).decode('ascii') +
              '" alt="TIN kompaniya logotipi">') if logo.is_file() else '<span aria-hidden="true">M</span>'
    return '''<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>Marwa — kundalik Telegram hisoboti · lokal namuna</title>
<style>
*{box-sizing:border-box}html{color-scheme:light}body{margin:0;background:#edf1ed;color:#143f37;font:15px/1.55 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
.layout{width:min(1100px,100%);margin:0 auto;padding:42px 30px;display:grid;grid-template-columns:minmax(0,1fr) 430px;gap:66px;align-items:start}
.intro{position:sticky;top:42px;padding-top:35px}.eyebrow{font-size:11px;letter-spacing:1.45px;font-weight:750;color:#486c60;margin-bottom:19px}
h1{font-size:38px;line-height:1.19;letter-spacing:-1.1px;margin:0 0 19px;max-width:440px}.description{color:#5b6d65;max-width:390px;margin:0 0 29px;font-size:16px;line-height:1.75}
.facts{display:grid;gap:17px;padding:24px 0;border-top:1px solid #d0dcd2;border-bottom:1px solid #d0dcd2}.fact{display:flex;justify-content:space-between;gap:18px}.fact span{color:#62746a}.fact strong{font-size:14px;font-weight:650;text-align:right}
.notice{font-size:13px;line-height:1.7;color:#67776e;margin:21px 0 0;max-width:390px}.notice strong{color:#335c4d}.device{overflow:hidden;border-radius:24px;background:#dfe9df;box-shadow:0 22px 65px #173f3020;border:1px solid #cedacf}
.chat-header{background:#1c493e;color:#fff;display:flex;align-items:center;gap:13px;padding:20px 20px 18px}.avatar{height:43px;width:43px;flex-shrink:0;display:grid;place-items:center;border-radius:50%;overflow:hidden;background:#ddca90;color:#214639;font-weight:800;font-size:21px}.avatar img{display:block;width:100%;height:100%;object-fit:contain;background:#fff}.chat-name{font-size:17px;font-weight:700;line-height:1.3}.bot-status{font-size:12px;color:#bdd0c7;margin-top:2px}.chat-header .menu{margin-left:auto;font-size:22px;color:#bdd0c7;line-height:1;letter-spacing:1px}
.chat{padding:16px 14px 20px;min-height:540px}.day-label{display:table;margin:0 auto 17px;padding:4px 12px;background:#638477;color:#fff;font-size:11px;line-height:1.5;border-radius:20px}.bubble{width:96%;padding:13px 15px 6px;margin:0 0 10px;background:#fffdf7;border-radius:14px 14px 14px 4px;box-shadow:0 1px 2px #15362712;color:#243b32}.bubble:first-of-type{border-top-left-radius:5px}.message{white-space:pre-wrap;font-size:14px;line-height:1.6;overflow-wrap:anywhere}.message b,.message strong{font-weight:720;color:#194c3b}.message code{font:inherit;font-variant-numeric:tabular-nums}.message-time{font-size:10px;line-height:1.5;text-align:right;color:#7a8b80;margin-top:3px}.chat-bottom{font-size:11px;color:#5f786a;text-align:center;padding:5px 12px 17px}.status-dot{display:inline-block;height:6px;width:6px;background:#a9bcb0;border-radius:50%;vertical-align:1px;margin-right:5px}
@media(max-width:850px){.layout{grid-template-columns:1fr;max-width:490px;padding:24px 20px;gap:24px}.intro{position:static;padding:0}.eyebrow{margin-bottom:12px}h1{font-size:27px;letter-spacing:-.6px;margin-bottom:12px}.description{font-size:14px;margin-bottom:16px}.facts{gap:9px;padding:14px 0}.fact{font-size:13px}.fact strong{font-size:13px}.notice{font-size:12px;margin-top:14px}.device{border-radius:20px}.chat{min-height:0}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style></head><body><main class="layout">
<section class="intro"><div class="eyebrow">LOKAL NAMUNA · SINOV MA’LUMOTLARI</div>
<h1>Har tong — kechagi kunning savdo hisoboti.</h1>
<p class="description">Telegram bot har bir filialning savdo summasi va sotilgan kilogrammini, kun yakunidagi tovar qiymati va qolgan kilogrammini alohida xabarda ko‘rsatadi.</p>
<div class="facts"><div class="fact"><span>Qabul qiluvchi</span><strong>@''' + escape(recipient['username']) + '''</strong></div>
<div class="fact"><span>Salomlashuv</span><strong>''' + escape(recipient['name']) + '''</strong></div>
<div class="fact"><span>Yuborish vaqti</span><strong>Har kuni 08:00 · Toshkent</strong></div>
<div class="fact"><span>Hisobot sanasi</span><strong>''' + escape(report_date) + '''</strong></div>
<div class="fact"><span>Ombor qiymati</span><strong>Kecha kun yakuni · sotuv narxida</strong></div></div>
<p class="notice"><strong>Bu raqamlar faqat namuna.</strong> Xabarlar tayyor hisobot kodidan olindi. Telegramga hech narsa yuborilmadi; serverdagi avtomatik yuborish yoqilmadi.</p>
</section><section class="device" aria-label="Telegram xabarlari namunasi">
<header class="chat-header"><div class="avatar">''' + avatar + '''</div><div><div class="chat-name">Marwa</div><div class="bot-status">bot · @marwacrmbot</div></div><div class="menu" aria-hidden="true">⋮</div></header>
<div class="chat"><div class="day-label">''' + escape((report_day + timedelta(days=1)).strftime('%d.%m.%Y')) + ''' · 08:00</div>
''' + '\n'.join(bubbles) + '''</div><div class="chat-bottom"><span class="status-dot"></span>Lokal ko‘rinish · avtomatik yuborish o‘chirilgan</div>
</section></main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description='Izolyatsiyalangan Telegram hisobot namunasi; hech qanday xabar yubormaydi.')
    parser.add_argument('--date', type=date.fromisoformat,
                        default=datetime.now(TZ).date() - timedelta(days=1), help='Hisobot kuni, YYYY-MM-DD')
    parser.add_argument('--recipient', choices=tuple(RECIPIENTS), default='abduqodir', help='Namuna uchun qabul qiluvchi')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    recipient = RECIPIENTS[args.recipient]
    if args.output is None:
        args.output = ROOT / '.runtime' / 'telegram-daily-preview' / (args.recipient + '.html')
    report = sample_report(args.date, recipient_name=recipient['name'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(report, args.date, recipient), encoding='utf-8')
    args.output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'preview': str(args.output.resolve()), 'messages': len(report['messages']),
                      'report_date': args.date.isoformat(), 'recipient': recipient['username'], 'sample_data_only': True,
                      'telegram_messages_sent': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
