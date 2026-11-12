"""Filial tranzaksiyasini markaziy hisobot jadvallariga atomar qo‘llash.

Mahsulot va foydalanuvchi IDlari markazdan keladi. Filial yaratgan savdo,
kirim va tarix IDlari esa qurilma kesimida markaziy IDga xaritalanadi.
"""
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import String, Integer, DateTime, Date, Numeric, JSON, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import (Stock, Receipt, Sale, SaleItem, SupplierPayment, DonationPayment,
                     SavedCart, Audit, Product, Supplier, User, Debtor, Debt, DebtPayment,
                     MiniDiscount, MiniDiscountShare, BranchExpense, SaleEdit, DebtInstallment)
from .accounting import line_total, balances, supplier_debt
from .donation_limits import require_donation_limit
from .receipt_limits import require_receipt_limit
from .operation_history import OPERATION_MODELS, reject_cancelled_request

MODELS = {m.__tablename__: m for m in
          (Stock, Receipt, Sale, SaleItem, SupplierPayment, DonationPayment, SavedCart, Audit,
           Debtor, Debt, DebtPayment, MiniDiscount, MiniDiscountShare, BranchExpense, SaleEdit)}
LOCAL_REFS = {'sale_id': Sale, 'sale_item_id': SaleItem, 'debtor_id': Debtor,
              'debt_id': Debt, 'mini_discount_id': MiniDiscount}
REFERENCES = {"product_id": Product, "supplier_id": Supplier, "user_id": User}
SOURCE_KINDS = {model: kind for kind, model in OPERATION_MODELS.items()}


class SyncIdentity(Base):
    __tablename__ = "sync_identity"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36))
    table_name: Mapped[str] = mapped_column(String(40))
    local_id: Mapped[int] = mapped_column(Integer)
    central_id: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("device_id", "table_name", "local_id"),)


def fail(message):
    raise HTTPException(409, "Sinxronlash: " + message)


def identity(db, device_id, table, local_id):
    return db.scalar(select(SyncIdentity).where(SyncIdentity.device_id == device_id,
                     SyncIdentity.table_name == table, SyncIdentity.local_id == local_id))


def remember(db, device_id, table, local_id, central_id):
    old = identity(db, device_id, table, local_id)
    if old:
        if old.central_id != central_id:
            fail("ID mosligi o‘zgargan.")
    else:
        db.add(SyncIdentity(device_id=device_id, table_name=table,
                            local_id=local_id, central_id=central_id))
        db.flush()


def typed_row(model, raw):
    columns = {c.name: c for c in model.__table__.columns}
    if set(raw) != set(columns):
        fail("Yozuv maydonlari server sxemasiga mos emas.")
    values = {}
    for key, value in raw.items():
        col = columns[key]
        if value is None:
            if not col.nullable:
                fail(f"{key} bo‘sh bo‘lmasin.")
        elif isinstance(col.type, Integer):
            if type(value) is not int or value <= 0:
                fail(f"{key} musbat butun son bo‘lsin.")
        elif isinstance(col.type, Numeric):
            try:
                number = Decimal(str(value))
                if (not number.is_finite() or number < 0 or
                        number != number.quantize(Decimal(10) ** -col.type.scale) or
                        number >= Decimal(10) ** (col.type.precision - col.type.scale)):
                    fail(f"{key} son formati noto‘g‘ri.")
                value = number
            except (InvalidOperation, ValueError):
                fail(f"{key} son emas.")
        elif isinstance(col.type, DateTime):
            try:
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    fail("Vaqt zonasi kerak.")
            except (ValueError, TypeError):
                fail("Vaqt formati noto‘g‘ri.")
        elif isinstance(col.type, Date):
            try:
                value = date.fromisoformat(value)
            except (ValueError, TypeError):
                fail('Sana formati noto‘g‘ri.')
        elif isinstance(col.type, String):
            if not isinstance(value, str) or len(value) > col.type.length:
                fail(f"{key} matn uzunligi noto‘g‘ri.")
        elif isinstance(col.type, JSON):
            if not isinstance(value, (dict, list)):
                fail(f"{key} JSON obyekt bo‘lsin.")
        values[key] = value
    return values


def apply_bundle(db, device, payload):
    """Commit qilmaydi: inbox, ID mapping va hisoblar birgalikda commit bo‘ladi."""
    if set(payload) != {"version", "changes"} or payload["version"] not in (2, 3, 4):
        fail("Protokol versiyasi qo‘llab-quvvatlanmaydi.")
    changes = payload["changes"]
    if not isinstance(changes, list) or not 1 <= len(changes) <= 1000:
        fail("Tranzaksiyadagi o‘zgarishlar soni noto‘g‘ri.")
    if any(isinstance(c, dict) and c.get('table') == 'sale_edits' for c in changes):
        if payload['version'] != 4:
            fail('Savdo tuzatishi uchun yangi protokol kerak.')
        from .sync_sale_edits import apply_edit_bundle
        return apply_edit_bundle(db, device, changes)
    expected_delta, actual_delta = defaultdict(Decimal), defaultdict(Decimal)
    new_sales, new_items = {}, defaultdict(list)
    new_minis = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"table", "operation", "row"}:
            fail("O‘zgarish shakli noto‘g‘ri.")
        model = MODELS.get(change["table"])
        operation = change["operation"]
        if model is None or operation not in ("insert", "update", "delete"):
            fail("Jadval yoki amal ruxsat etilmagan.")
        if operation != "insert" and model not in (Stock, SavedCart, Debtor):
            fail("Moliyaviy tarix o‘zgartirilmaydi.")
        if operation == "delete" and model is not SavedCart:
            fail("Faqat saqlangan savat o‘chirilishi mumkin.")
        if not isinstance(change["row"], dict):
            fail("Yozuv obyekt bo‘lsin.")
        values = typed_row(model, change["row"])
        if operation == 'insert' and model in SOURCE_KINDS:
            reject_cancelled_request(db, SOURCE_KINDS[model], values['request_id'])
        if model is Sale:
            require_donation_limit(values['donation'], status_code=409)
        elif model is DonationPayment:
            require_donation_limit(values['amount'], status_code=409)
        local_id = values.pop("id")
        for key, ref in LOCAL_REFS.items():
            if key not in values or model is SaleItem:
                continue
            linked = identity(db, device.id, ref.__tablename__, values[key])
            target = db.get(ref, linked.central_id) if linked else None
            if target is None:
                fail(f'Bog‘langan {key} uchun lokal ID mosligi topilmadi.')
            if hasattr(target, 'branch_id') and target.branch_id != device.branch_id:
                fail('Bog‘langan yozuv boshqa filialga tegishli.')
            values[key] = target.id
        if "branch_id" in values:
            if model is Audit and values["branch_id"] is None:
                values["branch_id"] = device.branch_id
            if values["branch_id"] != device.branch_id:
                fail("Boshqa filialga tegishli yozuv.")
        for key, ref in REFERENCES.items():
            if key in values and values[key] is not None:
                found = db.get(ref, values[key])
                if found is None:
                    fail(f"Bog‘langan {key} topilmadi.")
                if ref is User and found.role != "boss" and found.branch_id != device.branch_id:
                    fail("Xodim boshqa filialga tegishli.")
                if ref is User and model in (Receipt, SupplierPayment, DonationPayment) and found.role == "cashier":
                    fail("Kassir bu amalni bajara olmaydi.")
        mapping = identity(db, device.id, model.__tablename__, local_id)
        obj = db.get(model, mapping.central_id) if mapping else None
        if operation == "insert" and obj is not None:
            fail("Mahalliy ID allaqachon mavjud.")
        if operation != "insert" and obj is None:
            fail("Yangilanadigan yozuv uchun boshlang‘ich nusxa yo‘q.")
        if model is SaleItem:
            sale_mapping = identity(db, device.id, "sales", values["sale_id"])
            if not sale_mapping or sale_mapping.central_id not in new_sales:
                fail("Savdo tarkibi o‘z savdosi bilan bitta tranzaksiyada kelsin.")
            values["sale_id"] = sale_mapping.central_id
            product = db.get(Product, values["product_id"])
            if product.supplier_id != values["supplier_id"]:
                fail("Mahsulot ta’minotchisi mos emas.")
            if values["kg"] <= 0 or values["discount"] > 100 or values["total"] > line_total(values["kg"], values["price"], values["discount"]):
                fail("Savdo qatori hisobi mos emas.")
            expected_delta[values["product_id"]] -= values["kg"]
            new_items[values["sale_id"]].append(values)
        if model is Receipt:
            if values["kg"] <= 0:
                fail("Kirim kilogrammi musbat bo‘lsin.")
            require_receipt_limit(values["kg"], status_code=409)
            expected_delta[values["product_id"]] += values["kg"]
        if model is Stock:
            if values["discount"] > 100:
                fail("Chegirma 100 dan oshmasin.")
            if obj and obj.product_id != values["product_id"]:
                fail("Qoldiq mahsuloti almashtirilmaydi.")
            actual_delta[values["product_id"]] += values["kg"] - (obj.kg if obj else Decimal(0))
        if model is Audit:
            if not isinstance(values['detail'], dict):
                fail('Tarix tafsilotlari JSON obyekt bo‘lsin.')
            # Markazdagi ID boshqacha bo‘lishi mumkin; asl qurilma izi yo‘qolmaydi.
            values['detail'] = {**values['detail'], '_sync_source': {
                'device_id': device.id, 'local_audit_id': local_id,
                'branch_id': device.branch_id}}
        if model in (Debt, MiniDiscount) and values['sale_id'] not in new_sales:
            fail('Qarz va mini chegirma yangi savdo bilan bitta tranzaksiyada kelsin.')
        if model is DebtPayment:
            debt = db.get(Debt, values['debt_id'])
            # An old offline queue only knows the original full principal. It
            # must not collect it again after a real central partial receipt.
            # Canceled installment UUIDs also stay consumed forever.
            if db.scalar(select(DebtInstallment.id).where(
                    DebtInstallment.request_id == values['request_id']).limit(1)):
                fail('Bu qarz to‘lovi so‘rovi markazda ishlatilgan yoki bekor qilingan.')
            from .debt_management import paid_amount
            if paid_amount(db, 'sale', debt) > 0:
                fail('Qarzning to‘lovi markazda o‘zgargan. Eski navbatni avtomatik aralashtirib bo‘lmaydi.')
            if values['cash'] + values['card'] != debt.amount:
                fail('Qarz to‘lovi qarz summasiga teng emas.')
        if model is MiniDiscountShare and values['mini_discount_id'] not in new_minis:
            fail('Chegirma ulushi yangi chegirma bilan kelsin.')
        if model is BranchExpense and (not values['reason'].strip() or values['amount'] <= 0):
            fail('Xarajat summasi va sababi kerak.')
        if operation == "delete":
            db.delete(obj)
        elif operation == "update":
            if model is SavedCart and (obj.user_id != values["user_id"] or obj.branch_id != values["branch_id"]):
                fail("Savat egasi almashtirilmaydi.")
            for key, value in values.items():
                setattr(obj, key, value)
        else:
            obj = model(**values)
            db.add(obj)
        db.flush()
        if operation == "insert":
            remember(db, device.id, model.__tablename__, local_id, obj.id)
        if model is Sale:
            new_sales[obj.id] = obj
        if model is MiniDiscount:
            new_minis.add(obj.id)
    if any(expected_delta[k] != actual_delta[k] for k in set(expected_delta) | set(actual_delta)):
        fail("Ombor o‘zgarishi savdo/kirim kilogrammlariga teng emas.")
    for sale_id, sale in new_sales.items():
        items = new_items[sale_id]
        debt = db.scalar(select(Debt).where(Debt.sale_id == sale_id))
        mini = db.scalar(select(MiniDiscount).where(MiniDiscount.sale_id == sale_id))
        gross = sum(line_total(i['kg'], i['price'], i['discount']) for i in items)
        if not items or sum(i["total"] for i in items) != sale.total or sale.cash + sale.card + (debt.amount if debt else 0) != sale.total + sale.donation:
            fail("Savdo jami, to‘lov yoki ehson hisobi mos emas.")
        if debt and (sale.donation or mini):
            fail('Qarz bilan ehson yoki mini chegirma birga bo‘lmasin.')
        if mini:
            if (mini.original_total != gross or gross - sale.total != mini.amount or
                    sale.total % 1000 or sale.donation or mini.user_id != sale.user_id):
                fail('Mini chegirma summasi yoki minglik yaxlitlash noto‘g‘ri.')
            from .mini_discounts import allocate
            rows = list(db.scalars(select(SaleItem).where(SaleItem.sale_id == sale_id).order_by(SaleItem.id)))
            shares = {s.sale_item_id: s for s in db.scalars(select(MiniDiscountShare).where(MiniDiscountShare.mini_discount_id == mini.id))}
            expected = allocate(mini.amount, [line_total(i.kg, i.price, i.discount) for i in rows])
            for item, amount in zip(rows, expected):
                share = shares.pop(item.id, None)
                if (line_total(item.kg, item.price, item.discount) - item.total != amount or
                        (amount > 0 and (not share or share.amount != amount or share.supplier_id != item.supplier_id)) or
                        (amount == 0 and share)):
                    fail('Mini chegirma ta’minotchi ulushlari mos emas.')
            if shares:
                fail('Ortiqcha mini chegirma ulushi.')
        elif gross != sale.total:
            fail('Savdo qatori chegirmasiga izoh yo‘q.')
    ledger = balances(db, device.branch_id)
    if min(ledger["cash"], ledger["card"], ledger["donation_balance"], ledger['customer_debt']) < 0:
        fail("Kassa, ehson yoki qarz qoldig‘i manfiy bo‘ldi.")
    for supplier in db.scalars(select(Supplier.id)):
        if supplier_debt(db, supplier, device.branch_id)["debt"] < 0:
            fail("Ta’minotchiga haqidan ortiq to‘lov yozilgan.")
