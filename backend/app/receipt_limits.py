"""Bitta yangi mahsulot kirimi uchun kilogramm chegarasi."""
from decimal import Decimal
from fastapi import HTTPException


MAX_RECEIPT_KG = Decimal('200.000')


def require_receipt_limit(kg, status_code=422):
    if kg > MAX_RECEIPT_KG:
        raise HTTPException(status_code,
                            'Bir kirimda ko‘pi bilan 200 kg kiriting. Ko‘proq mahsulotni 200 kg gacha bo‘laklarda alohida kiriting.')
