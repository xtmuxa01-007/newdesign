import io
import os
import uuid
from pathlib import Path
from decimal import Decimal
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .models import Branch, Product, ProductArchive, Stock, StockAdjustment, Supplier, Receipt, User
from .schemas import NewProduct, NewSupplier, NewReceipt, Discount, ProductConfirmation, EditSku, AdjustStock, EditStockPrice
from .security import current_user, manager, programmer, branch_scope, branch_write
from .product_lifecycle import product_write, require_shared_catalog
from .common import row, clean, audit
from .accounting import supplier_debt
from .operation_history import reject_cancelled_request
from .receipt_limits import require_receipt_limit
from .stock_prices import apply_price_change
from .stock_adjustments import STOCK_ADJUSTMENT_ACTION

router = APIRouter(prefix="/api")
UPLOADS = Path(os.getenv("CRM_UPLOADS", "uploads"))

@router.get("/suppliers")
def suppliers(branch_id: int | None = None, user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    return [dict(row(s), **clean(supplier_debt(db, s.id, branch_id))) for s in db.scalars(select(Supplier).order_by(Supplier.name))]

@router.post("/suppliers", status_code=201)
def add_supplier(data: NewSupplier, user=Depends(manager), db: Session = Depends(get_db)):
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    db.flush()
    audit(db, user, "Ta’minotchi yaratildi", user.branch_id, supplier_id=supplier.id, name=supplier.name)
    db.commit()
    return row(supplier)

@router.get("/products")
def products(branch_id: int | None = None, q: str = Query("", max_length=150), include_archived: bool = False, user=Depends(current_user), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id, required=True)
    query = (select(Product, Supplier, Stock, ProductArchive.archived_at)
             .join(Supplier, Product.supplier_id == Supplier.id)
             .outerjoin(Stock, (Stock.product_id == Product.id) & (Stock.branch_id == branch_id))
             .outerjoin(ProductArchive, ProductArchive.product_id == Product.id).order_by(Product.name))
    if not include_archived or user.role not in ('boss', 'admin'):
        query = query.where(ProductArchive.product_id.is_(None))
    # Qidiruv literal matn bo‘yicha: foydalanuvchining % va _ belgilari wildcard emas.
    if q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Product.name.ilike(f"%{term}%", escape="\\") | Product.sku.ilike(f"%{term}%", escape="\\"))
    result = []
    for p, s, stock, archived_at in db.execute(query):
        result.append(dict(row(p), supplier=s.name, stock_id=stock.id if stock else None,
                           kg=str(stock.kg) if stock else "0", price=str(stock.price) if stock else "0",
                           discount=str(stock.discount) if stock else "0", active=bool(stock and stock.kg > 0 and archived_at is None),
                           archived=archived_at is not None, archived_at=clean(archived_at)))
    return result


def change_product_archive(db, user, product_id, data, archived):
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product:
        raise HTTPException(404, 'Mahsulot topilmadi.')
    if data.confirmation != product.sku:
        raise HTTPException(422, 'Tasdiqlash uchun mahsulot SKU kodini aynan yozing.')
    marker = db.get(ProductArchive, product_id)
    if archived and marker is None:
        require_shared_catalog(db)
        db.add(ProductArchive(product_id=product_id, user_id=user.id))
        audit(db, user, 'Mahsulot arxivlandi', product_id=product_id, name=product.name, sku=product.sku)
    elif not archived and marker is not None:
        db.delete(marker)
        audit(db, user, 'Mahsulot tiklandi', product_id=product_id, name=product.name, sku=product.sku)
    db.commit()
    return dict(id=product.id, name=product.name, archived=archived)


@router.post('/products/{product_id}/archive')
def archive_product(product_id: int, data: ProductConfirmation, user=Depends(programmer), db: Session = Depends(get_db)):
    return change_product_archive(db, user, product_id, data, True)


@router.post('/products/{product_id}/restore')
def restore_product(product_id: int, data: ProductConfirmation, user=Depends(programmer), db: Session = Depends(get_db)):
    return change_product_archive(db, user, product_id, data, False)

@router.post("/products", status_code=201)
def add_product(data: NewProduct, user=Depends(manager), db: Session = Depends(get_db)):
    if not db.get(Supplier, data.supplier_id):
        raise HTTPException(404, "Ta’minotchi topilmadi.")
    product = Product(name=data.name, sku=data.sku.upper(), supplier_id=data.supplier_id)
    db.add(product)
    db.flush()
    audit(db, user, "Mahsulot yaratildi", user.branch_id, product_id=product.id, name=product.name, sku=product.sku, supplier_id=product.supplier_id)
    db.commit()
    return row(product)

@router.post("/products/{product_id}/image")
async def upload_image(product_id: int, file: UploadFile = File(...), user=Depends(manager), db: Session = Depends(get_db)):
    product = product_write(db, product_id)
    if product.image:
        raise HTTPException(409, "Mahsulot rasmi allaqachon mavjud. Qayta kirim uchun shu rasm ishlatiladi.")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Rasm 5 MB dan oshmasin.")
    try:
        image = Image.open(io.BytesIO(content))
        if image.width * image.height > 20_000_000 or image.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError()
        image.load()
        image = image.convert("RGB")
        image.thumbnail((1200, 1200))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "To‘g‘ri JPG, PNG yoki WebP rasm tanlang.")
    UPLOADS.mkdir(exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    image.save(UPLOADS / filename, "JPEG", quality=85)
    product.image = f"/api/images/{filename}"
    audit(db, user, "Mahsulot rasmi qo‘shildi", user.branch_id, product_id=product.id)
    try:
        db.commit()
    except Exception:
        (UPLOADS / filename).unlink(missing_ok=True)
        raise
    return row(product)


@router.patch('/products/{product_id}/sku')
def edit_sku(product_id: int, data: EditSku, user=Depends(programmer), db: Session = Depends(get_db)):
    product = product_write(db, product_id)
    require_shared_catalog(db)
    if len(data.sku) > 60:
        raise HTTPException(422, 'SKU 60 belgidan oshmasin.')
    # Javobi yo'qolgan bir xil tahrir xavfsiz qaytariladi.
    if product.sku == data.sku:
        return row(product)
    if product.sku != data.expected_sku:
        raise HTTPException(409, 'SKU boshqa oynada o‘zgargan. Ro‘yxatni yangilab qayta oching.')
    if db.scalar(select(Product.id).where(Product.sku == data.sku, Product.id != product_id)):
        raise HTTPException(409, 'Bu SKU boshqa mahsulotda bor. Boshqa kod kiriting.')
    before = product.sku
    product.sku = data.sku
    audit(db, user, 'Mahsulot SKU kodi o‘zgartirildi', product_id=product.id,
          name=product.name, before=before, after=product.sku)
    db.commit()
    return row(product)


@router.post('/stocks/{stock_id}/adjustments')
def adjust_stock(stock_id: int, data: AdjustStock, user=Depends(manager), db: Session = Depends(get_db)):
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(409, 'Qoldiqni web yoki umumiy bazaga ulangan yangi EXE orqali tuzating.')
    stock = db.get(Stock, stock_id)
    if not stock:
        raise HTTPException(404, 'Mahsulot qoldig‘i topilmadi. Avval yangi kirim qo‘shing.')
    branch_scope(db, user, stock.branch_id, required=True)
    # Barcha qoldiq yozuvlari bilan bir xil tartib: filial -> mahsulot -> qoldiq.
    db.scalar(select(Branch).where(Branch.id == stock.branch_id).with_for_update())
    reject_cancelled_request(db, 'stock_adjustment', data.request_id)
    previous = db.scalar(select(StockAdjustment).where(StockAdjustment.request_id == data.request_id))
    if previous:
        if (previous.stock_id, previous.user_id, previous.before_kg, previous.kg, previous.reason) != (
                stock_id, user.id, data.expected_kg, data.kg, data.reason):
            raise HTTPException(409, 'Shu identifikator bilan boshqa tuzatish yuborilgan.')
        return row(previous)
    branch_write(db, stock.branch_id)
    product = product_write(db, stock.product_id)
    stock = db.scalar(select(Stock).where(Stock.id == stock_id).with_for_update()
                      .execution_options(populate_existing=True))
    if stock.kg != data.expected_kg:
        raise HTTPException(409, 'Qoldiq o‘zgargan: savdo, kirim yoki boshqa tuzatish bor. Ro‘yxatni yangilab qayta oching.')
    if stock.kg == data.kg:
        raise HTTPException(422, 'Yangi qoldiq hozirgi qoldiqdan farq qilsin.')
    adjustment = StockAdjustment(request_id=data.request_id, stock_id=stock.id,
        branch_id=stock.branch_id, product_id=stock.product_id, user_id=user.id,
        before_kg=stock.kg, kg=data.kg, reason=data.reason)
    try:
        db.add(adjustment)
        stock.kg = data.kg
        db.flush()
        audit(db, user, STOCK_ADJUSTMENT_ACTION, stock.branch_id, adjustment_id=adjustment.id,
              stock_id=stock.id, request_id=data.request_id, product_id=stock.product_id,
              product_name=product.name, sku=product.sku,
              before=format(adjustment.before_kg.quantize(Decimal('0.001')), 'f'),
              after=format(data.kg.quantize(Decimal('0.001')), 'f'),
              difference=format((data.kg-adjustment.before_kg).quantize(Decimal('0.001')), 'f'),
              reason=data.reason)
        db.commit()
    except IntegrityError:
        # Request IDs are globally unique; another branch has a different lock.
        # A concurrent collision must roll back its stock change as well.
        db.rollback()
        previous = db.scalar(select(StockAdjustment).where(StockAdjustment.request_id == data.request_id))
        if previous is None:
            raise
        if (previous.stock_id, previous.user_id, previous.before_kg, previous.kg, previous.reason) != (
                stock_id, user.id, data.expected_kg, data.kg, data.reason):
            raise HTTPException(409, 'Shu identifikator bilan boshqa tuzatish yuborilgan.')
        return row(previous)
    db.refresh(adjustment)
    return row(adjustment)


@router.get('/stock-adjustments')
def stock_adjustments(branch_id: int | None = None, offset: int = Query(0, ge=0),
                      user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id, required=True)
    query = (select(StockAdjustment, Product.name, User.name)
             .join(Product, Product.id == StockAdjustment.product_id)
             .join(User, User.id == StockAdjustment.user_id)
             .where(StockAdjustment.branch_id == branch_id)
             .order_by(StockAdjustment.id.desc()).offset(offset).limit(100))
    return [dict(row(a), product_name=name, actor=actor, difference=str(a.kg-a.before_kg))
            for a, name, actor in db.execute(query)]

@router.post("/receipts", status_code=201)
def add_receipt(data: NewReceipt, user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, branch_id)
    # Filial qulfi yangi stock qatori bir vaqtda ikki marta yaratilishini to‘xtatadi.
    db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update())
    reject_cancelled_request(db, 'receipt', data.request_id)
    existing = db.scalar(select(Receipt).where(Receipt.request_id == data.request_id))
    if existing:
        if existing.branch_id != branch_id or existing.user_id != user.id:
            raise HTTPException(409, "Kirim identifikatori band.")
        if any(getattr(existing, key) != value for key, value in data.model_dump().items()):
            raise HTTPException(409, "Shu identifikator bilan boshqa kirim yuborilgan. Oldingi kirimni tekshiring.")
        return row(existing)
    # Eski, allaqachon yozilgan katta kirimning aynan retry javobi saqlanadi.
    require_receipt_limit(data.kg)
    product_write(db, data.product_id)
    stock = db.scalar(select(Stock).where(Stock.branch_id == branch_id, Stock.product_id == data.product_id).with_for_update())
    if not stock:
        stock = Stock(branch_id=branch_id, product_id=data.product_id, kg=Decimal(0), price=data.price, discount=Decimal(0))
        db.add(stock)
    before = {"kg": stock.kg, "price": stock.price, "discount": stock.discount}
    # Bitta joriy narx: yangi kirim narxi filialdagi qolgan kilogrammga ham qo‘llanadi.
    # Qoldiq tugagan bo‘lsa eski vaqtinchalik chegirma yangi yukga o‘tmaydi.
    if stock.kg == 0:
        stock.discount = Decimal(0)
    stock.kg += data.kg
    stock.price = data.price
    receipt = Receipt(**data.model_dump(), user_id=user.id)
    db.add(receipt)
    db.flush()
    audit(db, user, "Omborga kirim", branch_id, receipt_id=receipt.id, request_id=data.request_id,
          product_id=data.product_id, kg=data.kg, price=data.price, before=before,
          after={"kg": stock.kg, "price": stock.price, "discount": stock.discount}, note=data.note)
    db.commit()
    return row(receipt)

@router.get("/receipts")
def receipts(branch_id: int | None = None, offset: int = Query(0, ge=0), user=Depends(manager), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id)
    query = select(Receipt, Product.name).join(Product, Product.id == Receipt.product_id).order_by(Receipt.id.desc()).offset(offset).limit(100)
    if branch_id is not None:
        query = query.where(Receipt.branch_id == branch_id)
    return [dict(row(r), product_name=name) for r, name in db.execute(query)]

@router.post('/stocks/{stock_id}/price')
def edit_stock_price(stock_id: int, data: EditStockPrice, user=Depends(manager), db: Session = Depends(get_db)):
    try:
        result = apply_price_change(db, stock_id, data, user)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.patch("/stocks/{stock_id}/discount")
def discount(stock_id: int, data: Discount, user=Depends(manager), db: Session = Depends(get_db)):
    stock = db.get(Stock, stock_id)
    if not stock:
        raise HTTPException(404, "Mahsulot qoldig‘i topilmadi.")
    branch_scope(db, user, stock.branch_id, required=True)
    branch_write(db, stock.branch_id)
    product_write(db, stock.product_id)
    stock = db.scalar(select(Stock).where(Stock.id == stock_id).with_for_update().execution_options(populate_existing=True))
    before = stock.discount
    stock.discount = data.discount
    audit(db, user, "Chegirma o‘zgartirildi", stock.branch_id, product_id=stock.product_id, before=before, after=data.discount)
    db.commit()
    return row(stock)
