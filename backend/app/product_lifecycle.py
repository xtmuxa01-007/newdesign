"""Mahsulot qulfi sotuv/kirim bilan arxivlashni bir vaqtda bajarilishdan saqlaydi."""
from fastapi import HTTPException
from sqlalchemy import select
from .models import Product, ProductArchive


def require_active_product(db, product):
    if db.scalar(select(ProductArchive.product_id).where(ProductArchive.product_id == product.id)) is not None:
        raise HTTPException(409, f'{product.name} arxivlangan. Davom etish uchun mahsulotni qayta tiklang yoki savatdan olib tashlang.')


def product_write(db, product_id):
    # Tartib: filial -> mahsulot IDlari o'sish tartibida -> stock.
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None:
        raise HTTPException(404, 'Mahsulot topilmadi.')
    require_active_product(db, product)
    return product


def require_shared_catalog(db):
    from .shared_mode import has_legacy_writer
    if has_legacy_writer(db):
        raise HTTPException(409, 'Avval barcha eski offline filial EXElarini 0.5.0 yoki yangiroq versiyaga o‘tkazing. Yuborilmagan savdolar tugagach katalogni tahrirlash mumkin.')


def require_legacy_catalog(db):
    # Eski EXE arxiv holatini tushunmaydi. Arxivlash ham shu product qulfini oladi.
    list(db.scalars(select(Product.id).order_by(Product.id).with_for_update()))
    if db.scalar(select(ProductArchive.product_id).limit(1)) is not None:
        raise HTTPException(409, 'Katalogda arxivlangan mahsulot bor. EXE 0.5.0 yoki yangiroq versiyada o‘z hisobingiz bilan kiring.')
