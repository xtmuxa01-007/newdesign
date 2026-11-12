"""Create synthetic transactions only in the fixed local demo database.

This script never clears a database. A populated demo is left intact on rerun.
All amounts are Decimal values and stock changes retain historical versions.
"""
from local_environment import DATABASE, LOCAL, PASSWORD, USERNAME, configure_local

configure_local()

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D
import json
import random
from unittest.mock import patch
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from app.main import app  # Register all application models, without starting workers.
from app.db import Base, SessionLocal, engine
from app.models import (Audit, Branch, BranchExpense, Debt, DebtInstallment, Debtor,
                        DebtPayment, DonationPayment, OpeningDebt, OtherPayment,
                        Product, Receipt, Sale, SaleItem, Stock, Supplier,
                        SupplierPayment, User)
from app.branch_lifecycle import initialize_owner
from app.security import password_hash
from app.stock_valuation_history import initialize_history

START = date(2026, 8, 6)
END = date(2026, 11, 5)
TZ = ZoneInfo('Asia/Tashkent')
rng = random.Random(20261105)


def moment(day, hour=10, minute=0):
    return datetime.combine(day, time(hour, minute), TZ).astimezone(timezone.utc)


def summary(db):
    return {
        'database': str(DATABASE), 'synthetic': True,
        'start': START.isoformat(), 'end': END.isoformat(),
        'branches': db.scalar(select(func.count(Branch.id))),
        'products': db.scalar(select(func.count(Product.id))),
        'sales': db.scalar(select(func.count(Sale.id))),
        'sale_items': db.scalar(select(func.count(SaleItem.id))),
        'sale_total': str(db.scalar(select(func.sum(Sale.total))) or 0),
        'accounts': db.scalar(select(func.count(User.id))),
        'sale_debts': db.scalar(select(func.count(Debt.id))),
        'first_sale': str(db.scalar(select(func.min(Sale.created_at)))),
        'last_sale': str(db.scalar(select(func.max(Sale.created_at)))),
    }


def seed():
    assert engine.dialect.name == 'sqlite'
    assert engine.url.database == DATABASE.as_posix()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Branch.id).limit(1)) or db.scalar(select(Sale.id).limit(1)):
            result = summary(db)
            print(json.dumps({'preserved_existing_data': True, **result}, ensure_ascii=False))
            return
        with db.begin_nested():
            owner = db.scalar(select(User).where(User.username == USERNAME))
            if owner is None:
                owner = User(username=USERNAME, name='Lokal dasturchi', role='boss',
                             password_hash=password_hash(PASSWORD))
                db.add(owner)
                db.flush()
            initialize_owner(db)
            owner.name = 'Lokal dasturchi'
            branches = [Branch(name=name) for name in
                        ('Andijon · Sinov', 'Shahrixon · Sinov', 'Asaka · Sinov',
                         'Namangan · Sinov', 'Farg‘ona · Sinov')]
            suppliers = [Supplier(name=name, phone='', note='Sun’iy lokal sinov ma’lumoti')
                         for name in ('Atlas Textile', 'Silk House', 'Cotton Line', 'Premium Fabric', 'Eco Weave')]
            db.add_all(branches + suppliers)
            db.flush()
            names = ('Atlas', 'Adras', 'Baxmal', 'Shoyi', 'Poplin', 'Satin', 'Paxta', 'Trikotaj',
                     'Jakkard', 'Shifon', 'Gabardin', 'Krep', 'Organza', 'Flanel', 'Lyon',
                     'Viskoza', 'Velur', 'Denim', 'Kashmir', 'Interlok')
            products = [Product(name=name, sku=f'DEMO-{index+1:03}',
                                supplier_id=suppliers[index % 5].id)
                        for index, name in enumerate(names)]
            db.add_all(products)
            db.flush()
            cashiers = {}
            debtors = {}
            local_hash = password_hash(PASSWORD)
            for index, branch in enumerate(branches, 1):
                admin = User(username=f'admin{index}', name=f'{branch.name.split(" · ")[0]} admin',
                             role='admin', branch_id=branch.id, password_hash=local_hash)
                cashier = User(username=f'kassir{index}', name=f'{branch.name.split(" · ")[0]} kassir',
                               role='cashier', branch_id=branch.id, password_hash=local_hash)
                db.add_all([admin, cashier])
                db.flush()
                cashiers[branch.id] = cashier
                debtors[branch.id] = [Debtor(branch_id=branch.id, first_name=f'Sinov mijoz {n+1}',
                    last_name=str(index), phone1='', phone2='', address='Sun’iy lokal sinov manzili',
                    created_at=moment(START, 8)) for n in range(5)]
                db.add_all(debtors[branch.id])
            db.flush()
            initial_time = moment(START, 8)
            with patch('app.stock_valuation_history.utc_now', return_value=initial_time):
                initialize_history(db)
                stocks = {}
                for branch in branches:
                    for index, product in enumerate(products):
                        price = D(12000 + index * 1500)
                        stock = Stock(branch_id=branch.id, product_id=product.id,
                                      kg=D('1000.000'), price=price, discount=D(0))
                        stocks[(branch.id, product.id)] = stock
                        db.add(stock)
                        db.add(Receipt(request_id=f'demo-receipt-{branch.id}-{product.id}',
                            branch_id=branch.id, product_id=product.id, user_id=owner.id,
                            kg=D('1000.000'), price=price, created_at=initial_time,
                            note='Sinov uchun boshlang‘ich kirim'))
                db.flush()
            day = START
            serial = 0
            while day <= END:
                day_index = (day - START).days
                for branch in branches:
                    for slot in range(5):
                        serial += 1
                        created = moment(day, 9, slot * 10 + branch.id)
                        entries = []
                        for product in rng.sample(products, rng.randint(2, 4)):
                            stock = stocks[(branch.id, product.id)]
                            kg = D(rng.randint(3, 36)) / 10
                            total = (kg * stock.price).quantize(D('.01'))
                            entries.append((product, stock, kg, total))
                        total = sum((e[3] for e in entries), D(0))
                        debt_amount = (total * D('.4')).quantize(D('.01')) if serial % 9 == 0 else D(0)
                        donation = D(1000) if slot == 0 and not debt_amount else D(0)
                        received = total - debt_amount + donation
                        method = serial % 3
                        cash = received if method == 0 else (D(0) if method == 1 else (received / 2).quantize(D('.01')))
                        sale = Sale(request_id=f'demo-sale-{serial}', branch_id=branch.id,
                            user_id=cashiers[branch.id].id, customer=f'Sinov xaridor {serial:04}',
                            total=total, cash=cash, card=received-cash, donation=donation, created_at=created)
                        with patch('app.stock_valuation_history.utc_now', return_value=created):
                            db.add(sale)
                            db.flush()
                            for product, stock, kg, amount in entries:
                                stock.kg -= kg
                                assert stock.kg >= 0
                                db.add(SaleItem(sale_id=sale.id, product_id=product.id,
                                    supplier_id=product.supplier_id, name=product.name, sku=product.sku,
                                    kg=kg, price=stock.price, discount=D(0), total=amount))
                            db.flush()
                        if debt_amount:
                            debt = Debt(branch_id=branch.id, sale_id=sale.id,
                                debtor_id=debtors[branch.id][serial % 5].id, amount=debt_amount,
                                due_date=day+timedelta(days=14), created_at=created)
                            db.add(debt)
                            db.flush()
                            if day+timedelta(days=12) <= END and serial % 27 == 0:
                                db.add(DebtPayment(request_id=f'demo-debt-paid-{serial}',
                                    debt_id=debt.id, branch_id=branch.id, user_id=owner.id,
                                    cash=debt_amount, card=D(0), created_at=moment(day+timedelta(days=12), 11)))
                            elif day+timedelta(days=7) <= END and serial % 27 == 9:
                                db.add(DebtInstallment(origin='sale', debt_id=debt.id,
                                    debt_created_at=created, request_id=f'demo-partial-{serial}',
                                    branch_id=branch.id, user_id=owner.id,
                                    cash=(debt_amount/2).quantize(D('.01')), card=D(0),
                                    next_due_date=day+timedelta(days=21), created_at=moment(day+timedelta(days=7), 11)))
                    if day_index > 0 and day_index % 7 == 0:
                        timestamp = moment(day, 12)
                        for supplier in suppliers:
                            db.add(SupplierPayment(request_id=f'demo-supplier-{branch.id}-{supplier.id}-{day_index}',
                                branch_id=branch.id, supplier_id=supplier.id, user_id=owner.id,
                                amount=D(30000), method='cash', recipient=supplier.name,
                                note='Haftalik sinov to‘lovi', created_at=timestamp))
                        db.add(BranchExpense(request_id=f'demo-expense-{branch.id}-{day_index}',
                            branch_id=branch.id, supplier_id=suppliers[day_index % 5].id, user_id=owner.id,
                            amount=D(25000), method='cash', reason=('Ijara' if day_index % 2 else 'Yetkazib berish'),
                            created_at=timestamp))
                        db.add(DonationPayment(request_id=f'demo-donation-{branch.id}-{day_index}',
                            branch_id=branch.id, user_id=owner.id, amount=D(3000), method='cash',
                            recipient='Sinov yordam jamg‘armasi', note='Sun’iy sinov to‘lovi', created_at=timestamp))
                        db.add(OtherPayment(request_id=f'demo-other-{branch.id}-{day_index}',
                            branch_id=branch.id, user_id=owner.id, amount=D(15000), method='card',
                            recipient='Sinov rahbari', note='Sinov pul topshirish amali', created_at=timestamp))
                db.flush()
                day += timedelta(days=1)
            for branch in branches:
                db.add(OpeningDebt(request_id=f'demo-opening-{branch.id}', branch_id=branch.id,
                    debtor_id=debtors[branch.id][0].id, user_id=owner.id, amount=D(150000),
                    due_date=END+timedelta(days=7), note='Sinov uchun oldingi qarz',
                    command={}, created_at=moment(START, 8)))
            db.add(Audit(user_id=owner.id, actor=owner.name, action='Lokal sinov bazasi yaratildi',
                detail={'synthetic':True,'period':[START.isoformat(),END.isoformat()], 'branches':5},
                created_at=moment(END, 12)))
            db.flush()
        db.commit()
        result = summary(db)
        LOCAL.joinpath('demo-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    seed()
