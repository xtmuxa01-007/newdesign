"""Bitta ehson kirimi yoki chiqimi uchun umumiy chegara."""
from decimal import Decimal
from fastapi import HTTPException


MAX_DONATION = Decimal('15000.00')


def require_donation_limit(amount, status_code=422):
    if amount > MAX_DONATION:
        raise HTTPException(status_code,
                            'Bir amaldagi ehson summasi 15 000 so‘mdan oshmasin. Naqd va karta summalarini tekshiring.')
