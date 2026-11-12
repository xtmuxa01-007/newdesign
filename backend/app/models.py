"""Hisoblar o‘chirilmaydi: barcha moliyaviy amallarning tarixi saqlanadi."""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, Numeric, Date, DateTime, ForeignKey, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now():
    return datetime.now(timezone.utc)

class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (CheckConstraint("role IN ('boss','admin','cashier')"),)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SystemOwner(Base):
    """Vakolat login matniga emas, bir marta bog'langan hisob IDiga tegishli."""
    __tablename__ = 'system_owner'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True)
    __table_args__ = (CheckConstraint('id = 1'),)


class BranchArchive(Base):
    """Filial va moliyaviy yozuvlar saqlanadi; bu faqat joriy arxiv belgisi."""
    __tablename__ = 'branch_archives'
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(60), default="")
    note: Mapped[str] = mapped_column(String(500), default="")

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    sku: Mapped[str] = mapped_column(String(60), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    image: Mapped[str | None] = mapped_column(String(160))

class ProductArchive(Base):
    """Umumiy katalogdan yashiradi; mahsulot va barcha hisoblar saqlanadi."""
    __tablename__ = 'product_archives'
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    discount: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    __table_args__ = (UniqueConstraint("branch_id", "product_id"), CheckConstraint("kg >= 0"),
                     CheckConstraint("price >= 0"), CheckConstraint("discount >= 0 AND discount <= 100"))

class StockAdjustment(Base):
    """Inventarizatsiya: qoldiq tuzatishi savdo yoki yangi kirim hisoblanmaydi."""
    __tablename__ = 'stock_adjustments'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey('stocks.id'))
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    before_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint('before_kg >= 0 AND kg >= 0'), {'sqlite_autoincrement': True})

class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    price: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = {'sqlite_autoincrement': True}

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    customer: Mapped[str] = mapped_column(String(120), default="")
    total: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    cash: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    card: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    donation: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint("cash >= 0 AND card >= 0 AND total >= 0 AND donation >= 0"), {'sqlite_autoincrement': True})

class SaleEdit(Base):
    """Savdoning har bir tuzatishi: asl vaqt o'zgarmaydi, oldingi holat yo'qolmaydi."""
    __tablename__ = 'sale_edits'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey('sales.id'), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    command: Mapped[dict] = mapped_column(JSON)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('sale_id', 'version'),)

class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    sku: Mapped[str] = mapped_column(String(60))
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    price: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(16, 2))

class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    method: Mapped[str] = mapped_column(String(10))
    recipient: Mapped[str] = mapped_column(String(150))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("amount > 0"), CheckConstraint("method IN ('cash','card')"), {'sqlite_autoincrement': True})

class DonationPayment(Base):
    __tablename__ = "donation_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    method: Mapped[str] = mapped_column(String(10))
    recipient: Mapped[str] = mapped_column(String(150))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("amount > 0"), CheckConstraint("method IN ('cash','card')"), {'sqlite_autoincrement': True})

class OtherPayment(Base):
    """Kassadan topshirilgan boshqa pul; ta'minotchi haqini o'zgartirmaydi."""
    __tablename__ = 'other_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    method: Mapped[str] = mapped_column(String(10))
    recipient: Mapped[str] = mapped_column(String(150))
    note: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint('amount > 0'), CheckConstraint("method IN ('cash','card')"), {'sqlite_autoincrement': True})

class SavedCart(Base):
    __tablename__ = "saved_carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(120))
    items: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# Qarz alohida jadvallarda: eski savdolar tuzilishi va summalari o‘zgarmaydi.
class Debtor(Base):
    __tablename__ = "debtors"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    phone1: Mapped[str] = mapped_column(String(30))
    phone2: Mapped[str] = mapped_column(String(30))
    address: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Debt(Base):
    __tablename__ = "debts"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), unique=True)
    debtor_id: Mapped[int] = mapped_column(ForeignKey("debtors.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("amount > 0"),)


class DebtPayment(Base):
    __tablename__ = "debt_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id"), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cash: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    card: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("cash >= 0 AND card >= 0 AND cash + card > 0"), {'sqlite_autoincrement': True})


class OpeningDebt(Base):
    """Oldin berilgan qarz: savdo, mahsulot va ombor yozuvi yaratilmaydi."""
    __tablename__ = 'opening_debts'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    debtor_id: Mapped[int] = mapped_column(ForeignKey('debtors.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    # Muddatsiz so'rov ertasi kuni takrorlansa ham aynan oldingi qarz qaytadi.
    command: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint('amount > 0'), {'sqlite_autoincrement': True})


class OpeningDebtPayment(Base):
    """Oldingi qarz undirilgandagina kassa kirimi hisoblanadi."""
    __tablename__ = 'opening_debt_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey('opening_debts.id'), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    cash: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    card: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint('cash >= 0 AND card >= 0 AND cash + card > 0'),
                     {'sqlite_autoincrement': True})


class OpeningDebtCancellation(Base):
    """Asl qarz/to'lov nusxasi saqlanadi; bekor qilingan so'rov qayta yozilmaydi."""
    __tablename__ = 'opening_debt_cancellations'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    operation_id: Mapped[int] = mapped_column(Integer, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    original_request_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSON)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('kind', 'original_request_id'),
                     CheckConstraint("kind IN ('debt','payment')"),
                     CheckConstraint('operation_id > 0'), {'sqlite_autoincrement': True})


class DebtInstallment(Base):
    """Qisman tushumlar alohida saqlanadi; bekor qilingani ham o'chirilmaydi."""
    __tablename__ = 'debt_installments'
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(10), index=True)
    debt_id: Mapped[int] = mapped_column(Integer, index=True)
    debt_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    cash: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    card: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    next_due_date: Mapped[date | None] = mapped_column(Date)
    expected_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    cancel_request_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    cancel_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    cancel_fingerprint: Mapped[str | None] = mapped_column(String(64))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        CheckConstraint("origin IN ('sale','opening')"), CheckConstraint('debt_id > 0'),
        CheckConstraint('cash >= 0 AND card >= 0 AND cash + card > 0'),
        CheckConstraint("(cancelled_at IS NULL AND cancel_request_id IS NULL AND cancel_user_id IS NULL "
                        "AND cancel_reason IS NULL AND cancel_fingerprint IS NULL) OR "
                        "(cancelled_at IS NOT NULL AND cancel_request_id IS NOT NULL AND cancel_user_id IS NOT NULL "
                        "AND cancel_reason IS NOT NULL AND cancel_fingerprint IS NOT NULL)"),
        {'sqlite_autoincrement': True},
    )


class DebtRevision(Base):
    """Qarzning tuzatishlari va muddat ko'chirishlari oldingi holati bilan saqlanadi."""
    __tablename__ = 'debt_revisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(10), index=True)
    debt_id: Mapped[int] = mapped_column(Integer, index=True)
    debt_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reason: Mapped[str] = mapped_column(String(500))
    command: Mapped[dict] = mapped_column(JSON)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint("origin IN ('sale','opening')"),
                     CheckConstraint('debt_id > 0'), {'sqlite_autoincrement': True})


class MiniDiscount(Base):
    """Kassir bergan kichik chegirma savdo bilan birga va faqat bir marta yoziladi."""
    __tablename__ = "mini_discounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    original_total: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("amount > 0 AND amount <= 5000"),
                     CheckConstraint("original_total >= amount"))


class MiniDiscountShare(Base):
    """Ta’minotchidan ayrilgan ulush: sotuv qatori va chegirma bilan bog‘langan."""
    __tablename__ = "mini_discount_shares"
    id: Mapped[int] = mapped_column(primary_key=True)
    mini_discount_id: Mapped[int] = mapped_column(ForeignKey('mini_discounts.id'), index=True)
    sale_item_id: Mapped[int] = mapped_column(ForeignKey('sale_items.id'), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey('suppliers.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    __table_args__ = (CheckConstraint('amount > 0'),)


class BranchExpense(Base):
    """Filial uchun sarflangan pul: kassadan va tanlangan ta’minotchi haqidan ayriladi."""
    __tablename__ = 'branch_expenses'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey('suppliers.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    method: Mapped[str] = mapped_column(String(10), default='cash')
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint('amount > 0'), CheckConstraint("method IN ('cash','card')"), {'sqlite_autoincrement': True})


class OperationCancellation(Base):
    """Bekor qilingan amal va barcha bog'lanishlarning o'zgarmas zaxira izi.

    Joriy hisobdan chiqarilgan asl yozuv snapshot ichida saqlanadi. So'rov
    identifikatori eski oynadan takror yuborilganda amal qayta yaratilmaydi.
    """
    __tablename__ = 'operation_cancellations'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    operation_id: Mapped[int] = mapped_column(Integer, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    original_request_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSON)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint('kind', 'original_request_id'),
        CheckConstraint('operation_id > 0'),
        CheckConstraint("kind IN ('sale','receipt','supplier_payment','donation_payment','other_payment','expense','debt_payment','stock_adjustment')"),
        {'sqlite_autoincrement': True},
    )
