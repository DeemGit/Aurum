"""Shared write-path helpers for transfers, refunds, import dedupe and merge."""
from __future__ import annotations

from datetime import date as date_
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import TransactionType
from app.models.tag import Tag
from app.models.transaction import (
    Transaction,
    TransactionImportHash,
    TransactionSplit,
    TransferMergeArchive,
)
from app.schemas.transaction import normalize_occurred_at


TRANSFER_MATCH_WINDOW = timedelta(days=2)

_LEG_LOAD = (
    selectinload(Transaction.tags),
    selectinload(Transaction.splits),
    selectinload(Transaction.import_hashes),
)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def attach_import_hash(transaction: Transaction, account_id: int, digest: str | None) -> None:
    """Record a statement fingerprint on the transaction (and mirror on the legacy column)."""
    if not digest:
        return
    transaction.import_hash = digest
    transaction.import_hashes.append(
        TransactionImportHash(account_id=account_id, import_hash=digest)
    )


def backfill_import_hash(transaction: Transaction, account_id: int, digest: str) -> bool:
    """Attach a fingerprint to an older row that lacked one.

    Never overwrites a different legacy ``import_hash`` already stored on the
    row; only fills the column when empty, and always appends a
    ``transaction_import_hashes`` row when this digest is new for the account.
    Returns True when a new hash row was added.
    """
    existing = {row.import_hash for row in transaction.import_hashes}
    if digest in existing:
        return False
    if transaction.import_hash is None:
        transaction.import_hash = digest
    transaction.import_hashes.append(
        TransactionImportHash(account_id=account_id, import_hash=digest)
    )
    return True


async def ensure_refund_target(
    session: AsyncSession,
    *,
    refund_of_transaction_id: int,
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
    # Refund may land on a different account than the original expense
    # (e.g. returned to another card / cash).

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
    occurred = _as_aware_utc(transaction.occurred_at)
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
        other_at = _as_aware_utc(other.occurred_at)
        return int(abs((other_at - occurred).total_seconds()))

    ranked = sorted(((row, delta_seconds(row)) for row in rows), key=lambda item: (item[1], item[0].id))
    return ranked


def _serialize_leg(tx: Transaction) -> dict:
    """JSON-serializable snapshot of a leg for transfer_merge_archives."""
    return {
        "id": tx.id,
        "account_id": tx.account_id,
        "category_id": tx.category_id,
        "transfer_account_id": tx.transfer_account_id,
        "refund_of_transaction_id": tx.refund_of_transaction_id,
        "type": tx.type.value if isinstance(tx.type, TransactionType) else tx.type,
        "amount": str(tx.amount),
        "transfer_amount": str(tx.transfer_amount) if tx.transfer_amount is not None else None,
        "exchange_rate": str(tx.exchange_rate) if tx.exchange_rate is not None else None,
        "fee_amount": str(tx.fee_amount or Decimal("0")),
        "description": tx.description,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "date": tx.date.isoformat(),
        "occurred_at": tx.occurred_at.isoformat(),
        "import_hash": tx.import_hash,
        "import_log_id": tx.import_log_id,
        "cashback_category_id": tx.cashback_category_id,
        "cashback_amount": str(tx.cashback_amount) if tx.cashback_amount is not None else None,
        "is_cashback": bool(tx.is_cashback),
        "tag_ids": [tag.id for tag in tx.tags],
        "splits": [
            {
                "id": split.id,
                "category_id": split.category_id,
                "amount": str(split.amount),
                "note": split.note,
            }
            for split in tx.splits
        ],
        "import_hashes": [
            {"account_id": row.account_id, "import_hash": row.import_hash} for row in tx.import_hashes
        ],
        "created_at": tx.created_at.isoformat() if tx.created_at is not None else None,
        "updated_at": tx.updated_at.isoformat() if tx.updated_at is not None else None,
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _restore_leg_from_payload(session: AsyncSession, payload: dict, tags_by_id: dict[int, Tag]) -> Transaction:
    """Re-insert a snapshotted leg with its original id and related rows."""
    leg_id = int(payload["id"])
    tag_ids = [int(x) for x in payload.get("tag_ids") or []]
    missing = [tid for tid in tag_ids if tid not in tags_by_id]
    if missing:
        raise HTTPException(status_code=400, detail=f"Cannot restore merge leg: unknown tag id(s) {missing}")

    occurred_at = _parse_datetime(payload["occurred_at"])
    assert occurred_at is not None
    created_at = _parse_datetime(payload.get("created_at"))
    updated_at = _parse_datetime(payload.get("updated_at"))

    transfer_amount = payload.get("transfer_amount")
    exchange_rate = payload.get("exchange_rate")
    cashback_amount = payload.get("cashback_amount")
    fee_raw = payload.get("fee_amount") or "0"

    transaction = Transaction(
        id=leg_id,
        account_id=int(payload["account_id"]),
        category_id=payload.get("category_id"),
        transfer_account_id=payload.get("transfer_account_id"),
        refund_of_transaction_id=payload.get("refund_of_transaction_id"),
        type=TransactionType(payload["type"]),
        amount=Decimal(str(payload["amount"])),
        transfer_amount=Decimal(str(transfer_amount)) if transfer_amount is not None else None,
        exchange_rate=Decimal(str(exchange_rate)) if exchange_rate is not None else None,
        fee_amount=Decimal(str(fee_raw)),
        description=payload["description"],
        merchant=payload.get("merchant"),
        notes=payload.get("notes"),
        date=date_.fromisoformat(payload["date"]),
        occurred_at=occurred_at,
        import_hash=payload.get("import_hash"),
        import_log_id=payload.get("import_log_id"),
        cashback_category_id=payload.get("cashback_category_id"),
        cashback_amount=Decimal(str(cashback_amount)) if cashback_amount is not None else None,
        is_cashback=bool(payload.get("is_cashback", False)),
        tags=[],
    )
    if created_at is not None:
        transaction.created_at = created_at
    if updated_at is not None:
        transaction.updated_at = updated_at

    for split in payload.get("splits") or []:
        split_kwargs: dict = {
            "category_id": split.get("category_id"),
            "amount": Decimal(str(split["amount"])),
            "note": split.get("note"),
        }
        if split.get("id") is not None:
            split_kwargs["id"] = int(split["id"])
        transaction.splits.append(TransactionSplit(**split_kwargs))
    for row in payload.get("import_hashes") or []:
        transaction.import_hashes.append(
            TransactionImportHash(account_id=int(row["account_id"]), import_hash=row["import_hash"])
        )
    # If hashes list empty but legacy column set, rebuild the single row.
    if not transaction.import_hashes and transaction.import_hash:
        transaction.import_hashes.append(
            TransactionImportHash(account_id=transaction.account_id, import_hash=transaction.import_hash)
        )

    transaction.tags = [tags_by_id[tid] for tid in tag_ids]
    session.add(transaction)
    return transaction


async def _reset_transactions_sequence(session: AsyncSession) -> None:
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('transactions', 'id'), "
            "COALESCE((SELECT MAX(id) FROM transactions), 1))"
        )
    )
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('transaction_splits', 'id'), "
            "COALESCE((SELECT MAX(id) FROM transaction_splits), 1))"
        )
    )


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

    # Reload with children so the archive snapshot is complete.
    expense = (
        await session.execute(select(Transaction).options(*_LEG_LOAD).where(Transaction.id == expense.id))
    ).scalar_one()
    income = (
        await session.execute(select(Transaction).options(*_LEG_LOAD).where(Transaction.id == income.id))
    ).scalar_one()

    refunds_on_expense = (
        await session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.refund_of_transaction_id == expense.id)
        )
    ).scalar_one()
    if refunds_on_expense:
        raise HTTPException(
            status_code=400,
            detail="cannot merge an expense that has refunds; remove refunds first",
        )

    expense_payload = _serialize_leg(expense)
    income_payload = _serialize_leg(income)

    expense_hash = expense.import_hash
    income_hash = income.import_hash
    expense_account_id = expense.account_id
    income_account_id = income.account_id
    expense_amount = expense.amount
    income_amount = income.amount
    description = expense.description or income.description
    merchant = expense.merchant or income.merchant
    # Legs already store wall-clock calendar days; never derive date from a UTC
    # instant — Alfa midnight +03 becomes previous-day UTC and used to win min().
    date_value = max(expense.date, income.date)
    # Prefer the later absolute moment so a real bank timestamp beats synthetic 00:00.
    occurred = max(_as_aware_utc(expense.occurred_at), _as_aware_utc(income.occurred_at))

    # Delete first and flush so unique (account_id, import_hash) is free before INSERT.
    await session.delete(expense)
    await session.delete(income)
    await session.flush()

    transfer = Transaction(
        account_id=expense_account_id,
        transfer_account_id=income_account_id,
        type=TransactionType.TRANSFER,
        amount=expense_amount,
        transfer_amount=transfer_amount if transfer_amount is not None else income_amount,
        exchange_rate=exchange_rate,
        fee_amount=fee_amount or Decimal("0"),
        description=description,
        merchant=merchant,
        notes=None,
        date=date_value,
        occurred_at=occurred,
        # Legacy column mirrors the source leg; both digests live in import_hashes.
        import_hash=expense_hash,
        cashback_category_id=None,
        cashback_amount=None,
        is_cashback=False,
        category_id=None,
        refund_of_transaction_id=None,
    )
    if expense_hash:
        transfer.import_hashes.append(
            TransactionImportHash(account_id=expense_account_id, import_hash=expense_hash)
        )
    if income_hash:
        # Same digest on two accounts is still two unique (account_id, hash) pairs.
        transfer.import_hashes.append(
            TransactionImportHash(account_id=income_account_id, import_hash=income_hash)
        )

    session.add(transfer)
    await session.flush()

    session.add(
        TransferMergeArchive(
            transfer_id=transfer.id,
            expense_payload=expense_payload,
            income_payload=income_payload,
        )
    )
    await session.commit()
    return transfer


async def delete_transaction_with_merge_restore(session: AsyncSession, transaction: Transaction) -> None:
    """Delete a transaction; if it is a merged transfer, restore archived legs first."""
    archive: TransferMergeArchive | None = None
    if transaction.type == TransactionType.TRANSFER:
        archive = (
            await session.execute(
                select(TransferMergeArchive).where(TransferMergeArchive.transfer_id == transaction.id)
            )
        ).scalar_one_or_none()

    if archive is None:
        await session.delete(transaction)
        await session.commit()
        return

    expense_payload = dict(archive.expense_payload)
    income_payload = dict(archive.income_payload)
    tag_ids = set(expense_payload.get("tag_ids") or []) | set(income_payload.get("tag_ids") or [])
    tags_by_id: dict[int, Tag] = {}
    if tag_ids:
        rows = (await session.execute(select(Tag).where(Tag.id.in_(tag_ids)))).scalars().all()
        tags_by_id = {tag.id: tag for tag in rows}

    # Drop archive then transfer so RESTRICT FK and unique hashes are free.
    await session.delete(archive)
    await session.delete(transaction)
    await session.flush()

    await _restore_leg_from_payload(session, expense_payload, tags_by_id)
    await _restore_leg_from_payload(session, income_payload, tags_by_id)
    await session.flush()
    await _reset_transactions_sequence(session)
    await session.commit()
