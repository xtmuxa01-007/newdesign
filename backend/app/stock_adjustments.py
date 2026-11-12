"""Read-only revision permissions; quantity changes use the existing audit trail."""
import os

from .branch_lifecycle import is_archived
from .models import ProductArchive
from .shared_mode import LEGACY_WRITER_REASON, has_legacy_writer


STOCK_ADJUSTMENT_ACTION = 'Ombor qoldig‘i tuzatildi'


def stock_adjustment_access(db, user, product, stock, branch_id):
    reason = None
    if not user or not user.active or user.role not in ('boss', 'admin'):
        reason = 'Qoldiqni faqat boshliq yoki admin tuzatadi.'
    elif user.role == 'admin' and user.branch_id != branch_id:
        reason = 'Boshqa filial qoldig‘ini tuzatib bo‘lmaydi.'
    elif os.getenv('CRM_BRANCH_ID'):
        reason = 'Qoldiqni web yoki umumiy bazaga ulangan yangi EXE orqali tuzating.'
    elif is_archived(db, branch_id):
        reason = 'Filial arxivlangan. Avval Programmist filialni tiklashi kerak.'
    elif product is None:
        reason = 'Mahsulot topilmadi.'
    elif db.get(ProductArchive, product.id) is not None:
        reason = 'Mahsulot arxivlangan. Qoldiqni tuzatish uchun mahsulotni tiklang.'
    elif stock is None:
        reason = 'Bu filialda mahsulot qoldig‘i yozuvi yo‘q. Avval kirim qo‘shing.'
    elif stock.branch_id != branch_id or stock.product_id != product.id:
        reason = 'Mahsulot qoldig‘i tanlangan filialga mos emas.'
    elif has_legacy_writer(db, branch_id):
        reason = LEGACY_WRITER_REASON
    return {'can_adjust_stock': reason is None, 'adjustment_disabled_reason': reason}
