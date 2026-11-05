"""How a transaction changes account balances and spending attribution.

Kept in one place so account_service, net_worth, insights, and reports cannot
drift on transfer fees / dual amounts / refunds.
"""
from collections import defaultdict
from datetime import date as date_
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import TransactionType
from app.models.transaction import Transaction


def apply_balance_delta(
    balances: dict[int, Decimal],
    *,
    tx_type: TransactionType,
    amount: Decimal,
    transfer_amount: Decimal | None,
    fee_amount: Decimal | None,
    account_id: int,
    transfer_account_id: int | None,
) -> None:
    fee = fee_amount or Decimal("0")
    if tx_type == TransactionType.INCOME:
        balances[account_id] += amount
    elif tx_type == TransactionType.EXPENSE:
        balances[account_id] -= amount
    elif tx_type == TransactionType.REFUND:
        balances[account_id] += amount
    elif tx_type == TransactionType.TRANSFER:
        balances[account_id] -= amount + fee
        if transfer_account_id is not None:
            balances[transfer_account_id] += transfer_amount if transfer_amount is not None else amount


def cash_delta_for_accounts(
    *,
    tx_type: TransactionType,
    amount: Decimal,
    transfer_amount: Decimal | None,
    fee_amount: Decimal | None,
    account_id: int,
    transfer_account_id: int | None,
    cash_account_ids: set[int],
) -> Decimal:
    """Net change to the cash slice of net worth for one transaction."""
    fee = fee_amount or Decimal("0")
    delta = Decimal("0")
    if tx_type == TransactionType.INCOME and account_id in cash_account_ids:
        delta += amount
    elif tx_type == TransactionType.EXPENSE and account_id in cash_account_ids:
        delta -= amount
    elif tx_type == TransactionType.REFUND and account_id in cash_account_ids:
        delta += amount
    elif tx_type == TransactionType.TRANSFER:
        if account_id in cash_account_ids:
            delta -= amount + fee
        if transfer_account_id in cash_account_ids:
            delta += transfer_amount if transfer_amount is not None else amount
    return delta


async def refund_amounts_by_original_expense_date(
    session: AsyncSession,
) -> dict[int, list[tuple[date_, Decimal]]]:
    """expense_id -> list of (expense.date, refund.amount) for attribution.

    Spending reports attribute refunds to the *purchase* month; cash flow also
    needs the refund's own date separately (loaded by callers).
    """
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.refund_of))
        .where(Transaction.type == TransactionType.REFUND, Transaction.refund_of_transaction_id.is_not(None))
    )
    rows = list((await session.execute(stmt)).scalars().all())
    by_expense: dict[int, list[tuple[date_, Decimal]]] = defaultdict(list)
    for refund in rows:
        original = refund.refund_of
        if original is None:
            continue
        by_expense[original.id].append((original.date, refund.amount))
    return by_expense


async def refund_total_for_expense_ids(
    session: AsyncSession, expense_ids: set[int]
) -> dict[int, Decimal]:
    if not expense_ids:
        return {}
    stmt = select(Transaction.refund_of_transaction_id, Transaction.amount).where(
        Transaction.type == TransactionType.REFUND,
        Transaction.refund_of_transaction_id.in_(expense_ids),
    )
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for expense_id, amount in (await session.execute(stmt)).all():
        if expense_id is not None:
            totals[expense_id] += amount
    return totals
