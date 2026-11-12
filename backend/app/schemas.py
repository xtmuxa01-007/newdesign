"""Kirimlar qat’iy tekshiriladi: kilogramm 3, pul 2 kasr xonagacha."""
from decimal import Decimal
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Kg = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
RequestId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9-]{16,64}$")]

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Login(Input):
    username: Name
    password: str = Field(min_length=1, max_length=200)

class NewUser(Input):
    username: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{3,60}$")]
    name: Name
    password: str = Field(min_length=10, max_length=200)
    role: Literal["boss", "admin", "cashier"]
    branch_id: int | None = None

class EditUser(Input):
    username: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{3,60}$")] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)

class AccountSettings(Input):
    current_password: str = Field(min_length=1, max_length=200)
    username: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{3,60}$")]
    new_password: str | None = Field(default=None, min_length=10, max_length=200)

class NewBranch(Input):
    name: Name

class BranchConfirmation(Input):
    confirmation: Name

class ProductConfirmation(Input):
    confirmation: Annotated[str, StringConstraints(min_length=1, max_length=60)]

class NewSupplier(Input):
    name: Name
    phone: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=500)

class NewProduct(Input):
    name: Name
    sku: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    supplier_id: int

class NewReceipt(Input):
    request_id: RequestId
    branch_id: int
    product_id: int
    kg: Kg
    price: PositiveMoney
    note: str = Field(default="", max_length=500)

class EditSku(Input):
    expected_sku: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    sku: Annotated[str, StringConstraints(min_length=1, max_length=60, to_upper=True)]

class AdjustStock(Input):
    request_id: RequestId
    expected_kg: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    kg: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=3, max_length=500)

class CancelOperation(Input):
    request_id: RequestId
    reason: str = Field(min_length=3, max_length=500)
    expected_fingerprint: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]

class Discount(Input):
    discount: Decimal = Field(ge=0, le=100, decimal_places=2)

class EditStockPrice(Input):
    request_id: RequestId
    expected_price: Money
    price: PositiveMoney
    reason: str = Field(min_length=3, max_length=500)

class CartItem(Input):
    product_id: int
    kg: Kg

class EditSaleItem(Input):
    item_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    kg: Kg
    price: PositiveMoney
    discount: Decimal = Field(default=0, ge=0, le=100, max_digits=5, decimal_places=2)

class EditSale(Input):
    request_id: RequestId
    version: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    customer: str = Field(default='', max_length=120)
    items: list[EditSaleItem] = Field(min_length=1, max_length=200)
    cash: Money
    card: Money
    debt_cash: Money = Decimal('0')
    debt_card: Money = Decimal('0')

class SaveCart(Input):
    branch_id: int
    label: Name
    items: list[CartItem] = Field(min_length=1, max_length=200)
    version: int | None = None

class Checkout(Input):
    branch_id: int
    request_id: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9-]{16,64}$")]
    customer: str = Field(default="", max_length=120)
    items: list[CartItem] = Field(min_length=1, max_length=200)
    cash: Money
    card: Money
    expected_total: Money
    saved_cart_id: int | None = None
    saved_cart_version: int | None = None
    debtor_id: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    mini_discount: Decimal = Field(default=Decimal('0'), ge=0, le=5000, max_digits=14, decimal_places=2)


class DebtorInput(Input):
    branch_id: int
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    phone1: Annotated[str, StringConstraints(pattern=r"^\+?[0-9][0-9 ()-]{5,28}[0-9]$")]
    phone2: Annotated[str, StringConstraints(pattern=r"^\+?[0-9][0-9 ()-]{5,28}[0-9]$")]
    address: str = Field(min_length=1, max_length=500)


class SettleDebt(Input):
    request_id: RequestId
    cash: Money
    card: Money
    next_due_date: date | None = None
    expected_fingerprint: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')] | None = None


class ReviseDebt(Input):
    request_id: RequestId
    reason: str = Field(min_length=3, max_length=500)
    expected_fingerprint: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    due_date: date | None = None
    amount: PositiveMoney | None = None
    debtor_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)


class NewOpeningDebt(Input):
    request_id: RequestId
    branch_id: int = Field(gt=0)
    debtor_id: int = Field(gt=0)
    amount: PositiveMoney
    due_date: date | None = None
    note: str = Field(default='', max_length=500)

class Payment(Input):
    request_id: RequestId
    branch_id: int
    amount: PositiveMoney
    method: Literal["cash", "card"]
    recipient: Name
    note: str = Field(default="", max_length=500)


class OtherPayment(Payment):
    # Unrecorded physical cash can be handed over too; the explanation is
    # mandatory so a negative recorded balance remains traceable.
    note: str = Field(min_length=3, max_length=500)


class NewExpense(Input):
    request_id: RequestId
    branch_id: int | None = None
    supplier_id: int = Field(gt=0)
    amount: PositiveMoney
    method: Literal['cash', 'card'] = 'cash'
    reason: str = Field(min_length=1, max_length=500)
