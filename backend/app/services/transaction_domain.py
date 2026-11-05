"""Shared write-path helpers for transfers, refunds, import dedupe and merge."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import TransactionType
from app.models.transaction import Transaction, TransactionSplit
from app.schemas.transaction import normalize_occurred_at


TRANSFER_MATCH_WINDOW = timedelta(days=2)


async def ensure_refund_target(
    session: AsyncSession,
    *,
    refund_of_transaction_id: int,
    account_id: int,
    amount: Decimal,
    exclude_refund_id: int | None = None,
) -> Transaction:
    original = await session.get(
        Transaction,
        refund_of_transaction_id,
        options=[selectinload(Transaction.splits)],
    )
    if original is None:
        raise HTTPException(status_code=400, detail="refund_of_transaction_id not found")
    if original.type != TransactionType.EXPENSE:
        raise HTTPException(status_code=400, detail="refund_of_transaction_id must reference an expense")
    if original.account_id != account_id:
        raise HTTPException(status_code=400, detail="refund must use the same account as the original expense")

    refunded_stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.type == TransactionType.REFUND,
        Transaction.refund_of_transaction_id == refund_of_transaction_id,
    )
    if exclude_refund_id is not None:
        refunded_stmt = refunded_stmt.where(Transaction.id != exclude_refund_id)
    already = (await session.execute(refunded_stmt)).scalar_one()
    remaining = original.amount - already
    if amount > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"refund amount ({amount}) exceeds remaining refundable ({remaining})",
        )
    return original


def apply_occurred_fields(fields: dict) -> dict:
    """Normalize date/occurred_at on a dumped create/update dict in place."""
    date_value, occurred_at = normalize_occurred_at(
        date=fields.get("date"),
        occurred_at=fields.get("occurred_at"),
    )
    fields["date"] = date_value
    fields["occurred_at"] = occurred_at
    return fields


async def find_transfer_match_candidates(
    session: AsyncSession,
    transaction: Transaction,
    *,
    eager_options: tuple,
) -> list[tuple[Transaction, int]]:
    if transaction.type not in (TransactionType.INCOME, TransactionType.EXPENSE):
        return []
    opposite = TransactionType.INCOME if transaction.type == TransactionType.EXPENSE else TransactionType.EXPENSE
    occurred = transaction.occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    window_start = occurred - TRANSFER_MATCH_WINDOW
    window_end = occurred + TRANSFER_MATCH_WINDOW

    stmt = (
        select(Transaction)
        .options(*eager_options)
        .where(
            Transaction.id != transaction.id,
            Transaction.account_id != transaction.account_id,
            Transaction.type == opposite,
            Transaction.amount == transaction.amount,
            Transaction.occurred_at >= window_start,
            Transaction.occurred_at <= window_end,
        )
    )
    rows = list((await session.execute(stmt)).scalars().all())

    def delta_seconds(other: Transaction) -> int:
        other_at = other.occurred_at
        if other_at.tzinfo is None:
            other_at = other_at.replace(tzinfo=timezone.utc)
        return int(abs((other_at - occurred).total_seconds()))

    ranked = sorted(((row, delta_seconds(row)) for row in rows), key=lambda item: (item[1], item[0].id))
    return ranked


async def merge_into_transfer(
    session: AsyncSession,
    *,
    source: Transaction,
    destination: Transaction,
    transfer_amount: Decimal | None,
    exchange_rate: Decimal | None,
    fee_amount: Decimal,
) -> Transaction:
    if {source.type, destination.type} != {TransactionType.EXPENSE, TransactionType.INCOME}:
        raise HTTPException(status_code=400, detail="merge requires one expense and one income")
    if source.account_id == destination.account_id:
        raise HTTPException(status_code=400, detail="merge requires two different accounts")
    if source.amount != destination.amount:
        raise HTTPException(status_code=400, detail="merge requires equal amounts")

    expense = source if source.type == TransactionType.EXPENSE else destination
    income = destination if source.type == TransactionType.EXPENSE else source

    occurred = min(expense.occurred_at, income.occurred_at)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)

    transfer = Transaction(
        account_id=expense.account_id,
        transfer_account_id=income.account_id,
        type=TransactionType.TRANSFER,
        amount=expense.amount,
        transfer_amount=transfer_amount if transfer_amount is not None else income.amount,
        exchange_rate=exchange_rate,
        fee_amount=fee_amount or Decimal("0"),
        description=expense.description or income.description,
        merchant=expense.merchant or income.merchant,
        notes=None,
        date=occurred.date(),
        occurred_at=occurred,
        import_hash=expense.import_hash,
        cashback_category_id=None,
        cashback_amount=None,
        is_cashback=False,
        category_id=None,
        refund_of_transaction_id=None,
    )
    session.add(transfer)
    await session.delete(expense)
    await session.delete(income)
    await session.commit()
    return transfer
