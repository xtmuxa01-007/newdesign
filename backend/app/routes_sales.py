from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import Branch, Product, Stock, Sale, SaleItem, SavedCart, Debt, Debtor, MiniDiscount, MiniDiscountShare, User
from .mini_discounts import allocate, mini_data
from .routes_debts import debt_data, web_only, today
from .schemas import Checkout, SaveCart, EditSale
from .security import current_user, manager, branch_scope, branch_write
from .common import row, audit, clean
from .accounting import line_total, money
from .donation_limits import require_donation_limit
from .operation_history import reject_cancelled_request, operation_for_source
from .product_lifecycle import product_write

router = APIRouter(prefix="/api")

def sale_data(db, sale):
    from .sale_edits import revision, utc
    from datetime import timedelta
    debt = db.scalar(select(Debt).where(Debt.sale_id == sale.id))
    mini = db.scalar(select(MiniDiscount).where(MiniDiscount.sale_id == sale.id))
    info = mini_data(db, mini) if mini else None
    shares = {s['sale_item_id']: Decimal(s['amount']) for s in info['shares']} if info else {}
    return dict(row(sale), edit_version=revision(db, sale.id), editable_until=(utc(sale.created_at) + timedelta(days=3)).isoformat(),
                debt=debt_data(db, debt) if debt else None, mini_discount=info,
                items=[dict(row(i), mini_discount=format(shares.get(i.id, Decimal(0)), 'f')) for i in db.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.id))])

def owned_cart(db, user, cart_id, lock=False):
    query = select(SavedCart).where(SavedCart.id == cart_id, SavedCart.user_id == user.id)
    cart = db.scalar(query)
    if not cart:
        raise HTTPException(404, "Saqlangan savdo topilmadi yoki boshqa kassirga tegishli.")
    branch_scope(db, user, cart.branch_id, required=True)
    if lock:
        # Checkout ham avval filial, keyin savatni qulflaydi. Ikki PCdagi
        # tahrir va checkout teskari tartibda qulflanib qolmasin.
        branch_write(db, cart.branch_id)
        cart = db.scalar(query.with_for_update().execution_options(populate_existing=True))
        if not cart:
            raise HTTPException(409, "Saqlangan savdo boshqa oynada yakunlangan. Ro‘yxatni yangilang.")
    return cart


@router.get('/sales/{sale_id}/cancellation')
def sale_cancellation_context(sale_id: int, user=Depends(manager), db: Session = Depends(get_db)):
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(404, 'Savdo topilmadi.')
    branch_scope(db, user, sale.branch_id, required=True)
    original_branch = sale.branch_id
    # Yozuvchi amallar shu filialni FOR UPDATE bilan qulflaydi. FOR SHARE
    # joriy xulosa va fingerprint orasida yangi qarz to'lovi tushmasin.
    if not db.scalar(select(Branch).where(Branch.id == original_branch).with_for_update(read=True)):
        raise HTTPException(404, 'Filial topilmadi.')
    sale = db.scalar(select(Sale).where(Sale.id == sale_id)
                     .execution_options(populate_existing=True))
    if not sale:
        raise HTTPException(404, 'Savdo topilmadi.')
    if sale.branch_id != original_branch:
        raise HTTPException(409, 'Savdo filiali o‘zgargan. Tarixni yangilang.')
    branch_scope(db, user, sale.branch_id, required=True)
    seller = db.get(User, sale.user_id)
    return clean({'action': 'Savdo', 'actor': seller.name if seller else '—',
                  'created_at': sale.created_at, 'branch_id': sale.branch_id,
                  'operation': operation_for_source(db, 'sale', sale, user)})


@router.get('/sales/{sale_id}/edit')
def edit_sale_detail(sale_id: int, user=Depends(manager), db: Session = Depends(get_db)):
    from .models import SaleEdit
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(404, 'Savdo topilmadi.')
    branch_scope(db, user, sale.branch_id, required=True)
    return dict(sale_data(db, sale), edits=[row(e) for e in db.scalars(select(SaleEdit).where(SaleEdit.sale_id == sale_id).order_by(SaleEdit.version))])


@router.post('/sales/{sale_id}/edit')
def edit_sale(sale_id: int, data: EditSale, user=Depends(manager), db: Session = Depends(get_db)):
    from .sale_edits import apply_edit
    sale = db.get(Sale, sale_id)
    if not sale:
        raise HTTPException(404, 'Savdo topilmadi.')
    branch_scope(db, user, sale.branch_id, required=True)
    branch_write(db, sale.branch_id)
    apply_edit(db, sale_id, data, user)
    db.commit()
    return sale_data(db, sale)

@router.get("/carts")
def carts(branch_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    branch_id = branch_scope(db, user, branch_id, required=True)
    return [row(c) for c in db.scalars(select(SavedCart).where(SavedCart.branch_id == branch_id, SavedCart.user_id == user.id).order_by(SavedCart.id.desc()))]

def validate_cart(db, items):
    ids = {i.product_id for i in items}
    actual = set(db.scalars(select(Product.id).where(Product.id.in_(ids))))
    if ids != actual:
        raise HTTPException(422, "Savatda mavjud bo‘lmagan mahsulot bor.")
    for product_id in sorted(ids):
        product_write(db, product_id)

@router.post("/carts", status_code=201)
def save_cart(data: SaveCart, user=Depends(current_user), db: Session = Depends(get_db)):
    branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, data.branch_id)
    validate_cart(db, data.items)
    cart = SavedCart(branch_id=data.branch_id, user_id=user.id, label=data.label, items=[i.model_dump(mode="json") for i in data.items])
    db.add(cart)
    db.flush()
    audit(db, user, "Savdo xotiraga saqlandi", cart.branch_id, cart_id=cart.id, label=cart.label, items=cart.items)
    db.commit()
    return row(cart)

@router.put("/carts/{cart_id}")
def update_cart(cart_id: int, data: SaveCart, user=Depends(current_user), db: Session = Depends(get_db)):
    cart = owned_cart(db, user, cart_id, lock=True)
    branch_write(db, cart.branch_id)
    if cart.version != data.version or cart.branch_id != data.branch_id:
        raise HTTPException(409, "Savat boshqa oynada o‘zgargan. Xotiradan qayta oching.")
    validate_cart(db, data.items)
    cart.label = data.label
    cart.items = [i.model_dump(mode="json") for i in data.items]
    cart.version += 1
    audit(db, user, "Xotiradagi savdo yangilandi", cart.branch_id, cart_id=cart.id, items=cart.items, version=cart.version)
    db.commit()
    return row(cart)

@router.delete("/carts/{cart_id}")
def delete_cart(cart_id: int, version: int, user=Depends(current_user), db: Session = Depends(get_db)):
    cart = owned_cart(db, user, cart_id, lock=True)
    branch_write(db, cart.branch_id)
    if cart.version != version:
        raise HTTPException(409, "Savat o‘zgargan. Ro‘yxatni yangilang.")
    audit(db, user, "Xotiradagi savdo o‘chirildi", cart.branch_id, cart_id=cart.id, label=cart.label, items=cart.items)
    db.delete(cart)
    db.commit()
    return {"ok": True}

@router.post("/sales", status_code=201)
def checkout(data: Checkout, user=Depends(current_user), db: Session = Depends(get_db)):
    if data.debtor_id is not None or data.due_date is not None or data.mini_discount:
        web_only()
    if data.mini_discount and data.debtor_id is not None:
        raise HTTPException(422, 'Qarz va mini chegirma birga qo‘llanmaydi.')
    if (data.debtor_id is None) != (data.due_date is None):
        raise HTTPException(422, 'Qarz uchun qarzdor va qaytarish sanasini birga tanlang.')
    branch_id = branch_scope(db, user, data.branch_id, required=True)
    branch_write(db, branch_id)
    # Barcha filial moliyaviy yozuvlari shu qulfdan o‘tadi: parallel savdo va to‘lov xavfsiz.
    db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update())
    reject_cancelled_request(db, 'sale', data.request_id)
    existing = db.scalar(select(Sale).where(Sale.request_id == data.request_id))
    if existing:
        old_mini = db.scalar(select(MiniDiscount).where(MiniDiscount.sale_id == existing.id))
        old_discount = old_mini.amount if old_mini else Decimal(0)
        if existing.user_id != user.id or existing.branch_id != branch_id:
            raise HTTPException(409, "Savdo so‘rovi identifikatori band.")
        old_items = {i.product_id: i.kg for i in db.scalars(select(SaleItem).where(SaleItem.sale_id == existing.id))}
        new_items = defaultdict(Decimal)
        for item in data.items:
            new_items[item.product_id] += item.kg
        if (old_items != dict(new_items) or existing.total + old_discount != data.expected_total or old_discount != data.mini_discount or
                existing.cash != data.cash or existing.card != data.card or existing.customer != data.customer):
            raise HTTPException(409, "Shu identifikator bilan boshqa savdo yuborilgan. Oldingi savdoni tekshiring.")
        old_debt = db.scalar(select(Debt).where(Debt.sale_id == existing.id))
        original_due_date = old_debt.due_date if old_debt else None
        if old_debt:
            from datetime import date
            from .debt_management import revisions
            history = revisions(db, 'sale', old_debt.id, old_debt.created_at)
            if history:
                original_due_date = date.fromisoformat(history[0].before['due_date'])
        if ((old_debt.debtor_id if old_debt else None) != data.debtor_id or
                original_due_date != data.due_date):
            raise HTTPException(409, 'Shu identifikator bilan boshqa qarz yuborilgan.')
        return sale_data(db, existing)
    if data.debtor_id is not None:
        debtor = db.get(Debtor, data.debtor_id)
        if not debtor or debtor.branch_id != branch_id:
            raise HTTPException(422, 'Shu filialdagi qarzdorni tanlang.')
        if data.due_date < today():
            raise HTTPException(422, 'Qaytarish sanasi bugundan oldin bo‘lmasin.')
    cart = None
    if data.saved_cart_id:
        cart = owned_cart(db, user, data.saved_cart_id, lock=True)
        if cart.branch_id != branch_id or cart.version != data.saved_cart_version:
            raise HTTPException(409, "Xotiradagi savdo o‘zgargan. Qayta oching.")
    quantities = defaultdict(Decimal)
    for item in data.items:
        quantities[item.product_id] += item.kg
    items = []
    total = Decimal(0)
    for product_id, kg in sorted(quantities.items()):
        product = product_write(db, product_id)
        stock = db.scalar(select(Stock).where(Stock.branch_id == branch_id, Stock.product_id == product_id).with_for_update())
        if not product or not stock or kg > stock.kg:
            raise HTTPException(409, f"{product.name if product else 'Mahsulot'} uchun omborda yetarli kilogramm yo‘q.")
        amount = line_total(kg, stock.price, stock.discount)
        items.append(SaleItem(product_id=product_id, supplier_id=product.supplier_id, name=product.name, sku=product.sku, kg=kg, price=stock.price, discount=stock.discount, total=amount))
        total += amount
        stock.kg -= kg
    if total != data.expected_total:
        raise HTTPException(409, "Narx yoki chegirma o‘zgargan. Mahsulotlarni yangilab, jami summani qayta tekshiring.")
    paid = data.cash + data.card
    original_total = total
    shares = [Decimal(0)] * len(items)
    if data.mini_discount:
        if total - paid != data.mini_discount:
            raise HTTPException(422, 'Mini chegirma jami va kiritilgan to‘lov orasidagi farqqa teng bo‘lsin.')
        if paid % Decimal('1000') != 0:
            raise HTTPException(422, 'Mini chegirmadan keyingi jami to‘lov minglik bo‘lsin. Masalan, 13 800 uchun 13 000 kiriting.')
        shares = allocate(data.mini_discount, [i.total for i in items])
        for item, share in zip(items, shares):
            item.total -= share
        total -= data.mini_discount
    if paid < total and data.debtor_id is None:
        raise HTTPException(422, "Kiritilgan naqd va karta summasi jami narxdan kam.")
    if data.debtor_id is not None and paid >= total:
        raise HTTPException(422, 'Qarz uchun to‘lanmagan qoldiq bo‘lishi kerak.')
    donation = money(max(paid - total, Decimal(0)))
    require_donation_limit(donation)
    sale = Sale(request_id=data.request_id, branch_id=branch_id, user_id=user.id, customer=data.customer,
                total=total, cash=data.cash, card=data.card, donation=donation)
    db.add(sale)
    db.flush()
    if data.debtor_id is not None:
        debt = Debt(branch_id=branch_id, sale_id=sale.id, debtor_id=data.debtor_id,
                    amount=money(total - paid), due_date=data.due_date)
        db.add(debt)
        db.flush()
        audit(db, user, 'Qarzga savdo qilindi', branch_id, debt_id=debt.id, sale_id=sale.id,
              request_id=data.request_id, debtor_id=debt.debtor_id, amount=debt.amount, due_date=debt.due_date)
    for item in items:
        item.sale_id = sale.id
        db.add(item)
    if data.mini_discount:
        mini = MiniDiscount(sale_id=sale.id, branch_id=branch_id, user_id=user.id,
                            original_total=original_total, amount=data.mini_discount)
        db.add(mini)
        db.flush()
        for item, share in zip(items, shares):
            if share:
                db.add(MiniDiscountShare(mini_discount_id=mini.id, sale_item_id=item.id,
                                         supplier_id=item.supplier_id, amount=share))
        audit(db, user, 'Mini chegirma berildi', branch_id, sale_id=sale.id,
              request_id=data.request_id, original_total=original_total, amount=data.mini_discount, total=total,
              shares=[{'product_id': i.product_id, 'supplier_id': i.supplier_id, 'amount': s} for i, s in zip(items, shares) if s])
    if cart:
        db.delete(cart)
    audit(db, user, "Savdo yakunlandi", branch_id, sale_id=sale.id, total=total, cash=data.cash, card=data.card, donation=sale.donation,
          request_id=data.request_id,
          items=[{"product_id": i.product_id, "name": i.name, "kg": i.kg, "price": i.price, "discount": i.discount, "total": i.total} for i in items])
    db.commit()
    return sale_data(db, sale)
