"""Tiyin aniqligida mutanosib taqsimlash; hech bir tiyin yo‘qolmaydi."""
from decimal import Decimal
from sqlalchemy import select
from .models import MiniDiscountShare, Supplier
from .common import row


def allocate(amount, totals):
    weights = [int(value * 100) for value in totals]
    cents = int(amount * 100)
    denominator = sum(weights)
    if cents < 0 or cents > denominator or denominator <= 0:
        raise ValueError('Chegirma qatorlar summasidan oshmasin.')
    shares = [cents * weight // denominator for weight in weights]
    # Eng katta kasr qoldig‘iga bir tiyindan beriladi; tenglikda qator tartibi.
    order = sorted(range(len(weights)), key=lambda i: (-(cents * weights[i] % denominator), i))
    for index in order[:cents - sum(shares)]:
        shares[index] += 1
    return [Decimal(value) / 100 for value in shares]


def mini_data(db, mini):
    q = select(MiniDiscountShare, Supplier.name).join(Supplier, Supplier.id == MiniDiscountShare.supplier_id).where(MiniDiscountShare.mini_discount_id == mini.id).order_by(MiniDiscountShare.id)
    return dict(row(mini), shares=[dict(row(s), supplier=name) for s, name in db.execute(q)])
