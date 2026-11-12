"""Filialning joriy sotuv narxi; savdo va kirim snapshotlari o'zgarmaydi."""
import os

from fastapi import HTTPException
from sqlalchemy import select

from .accounting import money
from .branch_lifecycle import is_archived
from .common import row, audit
from .models import Audit, Branch, ProductArchive, Stock
from .product_lifecycle import product_write
from .security import branch_scope, branch_write
from .shared_mode import LEGACY_WRITER_REASON, has_legacy_writer


PRICE_CHANGE_ACTION = 'Mahsulot narxi o‘zgartirildi'


def price_edit_access(db, user, product, stock, branch_id):
    """Analiz uchun faqat o'qish: ruxsat yoki tahrirni to'xtatish sababi."""
    reason = None
    if not user or not user.active or user.role not in ('boss', 'admin'):
        reason = 'Narxni faqat boshliq yoki admin o‘zgartiradi.'
    elif user.role == 'admin' and user.branch_id != branch_id:
        reason = 'Boshqa filial narxini o‘zgartirib bo‘lmaydi.'
    elif os.getenv('CRM_BRANCH_ID'):
        reason = 'Narxni web yoki umumiy bazaga ulangan yangi EXE orqali o‘zgartiring.'
    elif is_archived(db, branch_id):
        reason = 'Filial arxivlangan. Avval Programmist filialni tiklashi kerak.'
    elif product is None:
        reason = 'Mahsulot topilmadi.'
    elif db.get(ProductArchive, product.id) is not None:
        reason = 'Mahsulot arxivlangan. Narxni o‘zgartirish uchun mahsulotni tiklang.'
    elif stock is None:
        reason = 'Bu filialda mahsulot qoldig‘i yozuvi yo‘q. Avval kirim qo‘shing.'
    elif stock.branch_id != branch_id or stock.product_id != product.id:
        reason = 'Mahsulot qoldig‘i tanlangan filialga mos emas.'
    elif has_legacy_writer(db, branch_id):
        reason = LEGACY_WRITER_REASON
    return {'can_edit_price': reason is None, 'price_edit_reason': reason}


def apply_price_change(db, stock_id, data, user):
    """Audit request_idsi filial doirasida yagona; filial qulfi retrylarni ketma-ket bajaradi."""
    if not user or not user.active or user.role not in ('boss', 'admin'):
        raise HTTPException(403, 'Narxni faqat boshliq yoki admin o‘zgartiradi.')
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Narxni web yoki umumiy bazaga ulangan yangi EXE orqali o‘zgartiring.')
    stock = db.get(Stock, stock_id)
    if stock is None:
        raise HTTPException(404, 'Mahsulot qoldig‘i topilmadi. Avval kirim qo‘shing.')
    branch_scope(db, user, stock.branch_id, required=True)
    branch_id, product_id = stock.branch_id, stock.product_id
    # Umumiy tartib: filial -> mahsulot -> stock. Retry ham filial qulfini oladi.
    if not db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update()):
        raise HTTPException(404, 'Filial topilmadi.')
    command = {'stock_id': stock_id, 'expected_price': format(money(data.expected_price), 'f'),
               'price': format(money(data.price), 'f'), 'reason': data.reason}
    previous = db.scalar(select(Audit).where(Audit.branch_id == branch_id,
        Audit.action == PRICE_CHANGE_ACTION,
        Audit.detail['request_id'].as_string() == data.request_id).order_by(Audit.id).limit(1))
    if previous is not None:
        if previous.user_id != user.id or previous.detail.get('command') != command:
            raise HTTPException(409, 'Shu identifikator bilan boshqa narx o‘zgarishi yuborilgan.')
        return previous.detail['result']
    branch_write(db, branch_id)
    product = product_write(db, product_id)
    stock = db.scalar(select(Stock).where(Stock.id == stock_id).with_for_update()
                      .execution_options(populate_existing=True))
    if stock is None or stock.branch_id != branch_id or stock.product_id != product_id:
        raise HTTPException(409, 'Mahsulot qoldig‘i o‘zgargan. Ro‘yxatni yangilang.')
    if stock.price != data.expected_price:
        raise HTTPException(409, 'Narx boshqa oynada yoki kirimda o‘zgargan. Analizni yangilab qayta oching.')
    if stock.price == data.price:
        raise HTTPException(422, 'Yangi narx hozirgi narxdan farq qilsin.')
    before = format(money(stock.price), 'f')
    stock.price = money(data.price)
    result = {'ok': True, 'stock': row(stock), 'request_id': data.request_id}
    audit(db, user, PRICE_CHANGE_ACTION, branch_id, stock_id=stock_id, product_id=product_id,
          product_name=product.name, sku=product.sku,
          request_id=data.request_id, before=before, after=format(stock.price, 'f'),
          reason=data.reason, command=command, result=result)
    db.flush()
    return result
