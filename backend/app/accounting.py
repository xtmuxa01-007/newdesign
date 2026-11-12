"""Bir xil pul qoidalari savdo, hisobot va sinovlarda ishlatiladi."""
from decimal import Decimal, ROUND_HALF_UP
import os
from sqlalchemy import select, func
from .models import Sale, SaleItem, SupplierPayment, DonationPayment, OtherPayment, Debt, DebtPayment, MiniDiscount, MiniDiscountShare, BranchExpense, OpeningDebt, OpeningDebtPayment, DebtInstallment

ZERO = Decimal("0.00")

def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def line_total(kg, price, discount):
    # Har bir qator bir marta yaxlitlanadi, jami shu qatorlardan yig‘iladi.
    return money(kg * price * (Decimal(100) - discount) / Decimal(100))

def sum_column(db, model, column, branch_id=None, conditions=()):
    query = select(func.coalesce(func.sum(column), 0)).select_from(model)
    if branch_id is not None:
        query = query.where(model.branch_id == branch_id)
    return Decimal(db.scalar(query.where(*conditions)) or 0)

def supplier_debt(db, supplier_id, branch_id=None):
    query = select(func.coalesce(func.sum(SaleItem.total), 0)).join(Sale, Sale.id == SaleItem.sale_id).where(SaleItem.supplier_id == supplier_id)
    if branch_id is not None:
        query = query.where(Sale.branch_id == branch_id)
    earned = Decimal(db.scalar(query) or 0)
    paid = sum_column(db, SupplierPayment, SupplierPayment.amount, branch_id, (SupplierPayment.supplier_id == supplier_id,))
    discounts = select(func.coalesce(func.sum(MiniDiscountShare.amount), 0)).join(MiniDiscount, MiniDiscount.id == MiniDiscountShare.mini_discount_id).where(MiniDiscountShare.supplier_id == supplier_id)
    if branch_id is not None:
        discounts = discounts.where(MiniDiscount.branch_id == branch_id)
    expenses = sum_column(db, BranchExpense, BranchExpense.amount, branch_id, (BranchExpense.supplier_id == supplier_id,))
    return {"earned": earned, "paid": paid, "expenses": expenses, "debt": earned - paid - expenses, 'mini_discount': Decimal(db.scalar(discounts) or 0)}

def balances(db, branch_id=None):
    result = {}
    for method in ("cash", "card"):
        incoming = sum_column(db, Sale, getattr(Sale, method), branch_id)
        incoming += sum_column(db, DebtPayment, getattr(DebtPayment, method), branch_id)
        incoming += sum_column(db, OpeningDebtPayment, getattr(OpeningDebtPayment, method), branch_id)
        if not os.getenv('CRM_BRANCH_ID'):
            incoming += sum_column(db, DebtInstallment, getattr(DebtInstallment, method), branch_id,
                                   (DebtInstallment.cancelled_at.is_(None),))
        outgoing = sum(sum_column(db, model, model.amount, branch_id, (model.method == method,)) for model in (SupplierPayment, DonationPayment, BranchExpense))
        # New cashouts are central-only; old offline SQLite schemas do not carry
        # this table and must never silently create an unsynchronised payment.
        if not os.getenv('CRM_BRANCH_ID'):
            outgoing += sum_column(db, OtherPayment, OtherPayment.amount, branch_id,
                                   (OtherPayment.method == method,))
        result[method] = incoming - outgoing
    result["donation_received"] = sum_column(db, Sale, Sale.donation, branch_id)
    result["donation_paid"] = sum_column(db, DonationPayment, DonationPayment.amount, branch_id)
    result["donation_balance"] = result["donation_received"] - result["donation_paid"]
    # Savdo va oldingi qarzlar pul undirilmaguncha kassa kirimi hisoblanmaydi.
    received = sum_column(db, DebtPayment, DebtPayment.cash, branch_id) + sum_column(db, DebtPayment, DebtPayment.card, branch_id)
    received += sum_column(db, OpeningDebtPayment, OpeningDebtPayment.cash, branch_id) + sum_column(db, OpeningDebtPayment, OpeningDebtPayment.card, branch_id)
    if not os.getenv('CRM_BRANCH_ID'):
        received += sum_column(db, DebtInstallment, DebtInstallment.cash + DebtInstallment.card, branch_id,
                               (DebtInstallment.cancelled_at.is_(None),))
    result['customer_debt'] = sum_column(db, Debt, Debt.amount, branch_id) + sum_column(db, OpeningDebt, OpeningDebt.amount, branch_id) - received
    result['branch_expenses'] = sum_column(db, BranchExpense, BranchExpense.amount, branch_id)
    result['other_paid'] = (sum_column(db, OtherPayment, OtherPayment.amount, branch_id)
                            if not os.getenv('CRM_BRANCH_ID') else ZERO)
    return result
