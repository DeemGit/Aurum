from datetime import date as date_
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_session
from app.core.audit import log_destructive
from app.models.cashback import CashbackCategory
from app.models.category import Category
from app.models.enums import CategoryKind, TransactionType
from app.models.tag import Tag
from app.models.transaction import Transaction, TransactionImportHash, TransactionSplit
from app.schemas.transaction import (
    AlfaHtmlConvertRequest,
    AlfaHtmlConvertResult,
    GpbHtmlConvertRequest,
    GpbHtmlConvertResult,
    TransactionBulkCreate,
    TransactionBulkCreateResult,
    TransactionCreate,
    TransactionPage,
    TransactionRead,
    TransactionSplitInput,
    TransactionUpdate,
    TransferMatchResponse,
    TransferMatchCandidate,
    TransferMergeRequest,
    cashback_rule_violation,
    normalize_occurred_at,
    refund_rule_violation,
    split_rule_violation,
    transfer_rule_violation,
)
from app.services.alfa_html_statement import convert_alfa_html_to_csv
from app.services.gpb_html_statement import convert_gpb_html_to_csv
from app.services.cashback_service import (
    ensure_cashback_category_for_account,
    resolve_expense_cashback_amount,
)
from app.services.transaction_domain import (
    attach_import_hash,
    backfill_import_hash,
    ensure_refund_target,
    find_transfer_match_candidates,
    merge_into_transfer,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

_EAGER = (
    selectinload(Transaction.account),
    selectinload(Transaction.transfer_account),
    selectinload(Transaction.category),
    selectinload(Transaction.tags),
    selectinload(Transaction.cashback_category).selectinload(CashbackCategory.account),
    selectinload(Transaction.splits).selectinload(TransactionSplit.category),
)


async def _resolve_tags(session: AsyncSession, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    result = await session.execute(select(Tag).where(Tag.id.in_(tag_ids)))
    tags = list(result.scalars().all())
    missing = set(tag_ids) - {tag.id for tag in tags}
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown tag id(s): {sorted(missing)}")
    return tags

_TYPE_TO_CATEGORY_KIND = {
    TransactionType.INCOME: CategoryKind.INCOME,
    TransactionType.EXPENSE: CategoryKind.EXPENSE,
}


async def _ensure_category_matches_type(
    session: AsyncSession, category_id: int | None, transaction_type: TransactionType
) -> Category | None:
    """A category picked for an income transaction must itself be an income
    category (and likewise for expense) — otherwise the dashboard's spending
    breakdown, which only joins EXPENSE-typed rows, would silently misclassify
    the entry. Returns the fetched category (or None for category_id=None) so
    callers that also need the row itself — _build_splits, below — don't have
    to fetch it a second time."""
    if category_id is None:
        return None
    expected_kind = _TYPE_TO_CATEGORY_KIND.get(transaction_type)
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=400, detail="Category not found")
    if expected_kind is not None and category.kind != expected_kind:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category.name}' is a {category.kind.value} category and cannot be used for a {transaction_type.value} transaction",
        )
    return category


async def _build_splits(
    session: AsyncSession, splits: list[TransactionSplitInput], transaction_type: TransactionType
) -> list[TransactionSplit]:
    """A split's whole point is dividing one purchase's total across the
    *subcategories of one parent* (a hypermarket receipt: part groceries ->
    Sweets, part -> Alcohol) — not across unrelated top-level categories, or
    the numbers would roll up into two different parents and the "spent X on
    Groceries, split between Sweets/Alcohol" picture the feature exists for
    falls apart. Each split may point at that parent category itself (an
    unspecified-subcategory line) or at any one of its direct children —
    enforced by requiring every split's own top-level ancestor
    (parent_id, or its own id if it has none) to agree.
    """
    top_level_ids: set[int] = set()
    for split in splits:
        category = await _ensure_category_matches_type(session, split.category_id, transaction_type)
        assert category is not None  # split.category_id is required (not Optional) on the schema
        top_level_ids.add(category.parent_id if category.parent_id is not None else category.id)
    if len(top_level_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail="All split categories must be the same parent category or its direct subcategories",
        )
    return [TransactionSplit(category_id=s.category_id, amount=s.amount, note=s.note) for s in splits]


async def _load_transaction(session: AsyncSession, transaction_id: int) -> Transaction:
    refreshed = await session.execute(
        select(Transaction).options(*_EAGER).where(Transaction.id == transaction_id)
    )
    transaction = refreshed.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@router.get("", response_model=TransactionPage)
async def list_transactions(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    start_date: date_ | None = Query(default=None),
    end_date: date_ | None = Query(default=None),
    account_id: int | None = None,
    category_id: int | None = None,
    tag_id: int | None = None,
    type: TransactionType | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=255),
    sort: Literal["date_desc", "amount_desc", "amount_asc"] = Query(default="date_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> TransactionPage:
    stmt = select(Transaction).options(*_EAGER)
    count_stmt = select(func.count()).select_from(Transaction)

    if year is not None:
        stmt = stmt.where(func.extract("year", Transaction.date) == year)
        count_stmt = count_stmt.where(func.extract("year", Transaction.date) == year)
    if month is not None:
        stmt = stmt.where(func.extract("month", Transaction.date) == month)
        count_stmt = count_stmt.where(func.extract("month", Transaction.date) == month)
    if start_date is not None:
        stmt = stmt.where(Transaction.date >= start_date)
        count_stmt = count_stmt.where(Transaction.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.date <= end_date)
        count_stmt = count_stmt.where(Transaction.date <= end_date)
    if account_id is not None:
        # Include transfers that touch the account on either leg.
        account_filter = or_(
            Transaction.account_id == account_id,
            Transaction.transfer_account_id == account_id,
        )
        stmt = stmt.where(account_filter)
        count_stmt = count_stmt.where(account_filter)
    if category_id is not None:
        # A split transaction has category_id=NULL on the row itself — the
        # category lives on its split lines instead, so filtering by exact
        # column match alone would silently drop it from a category filter
        # it genuinely belongs to.
        category_filter = or_(
            Transaction.category_id == category_id, Transaction.splits.any(TransactionSplit.category_id == category_id)
        )
        stmt = stmt.where(category_filter)
        count_stmt = count_stmt.where(category_filter)
    if tag_id is not None:
        stmt = stmt.where(Transaction.tags.any(Tag.id == tag_id))
        count_stmt = count_stmt.where(Transaction.tags.any(Tag.id == tag_id))
    if type is not None:
        stmt = stmt.where(Transaction.type == type)
        count_stmt = count_stmt.where(Transaction.type == type)
    if search is not None:
        # Lets the user find a transaction from any period by keyword (e.g. an
        # item bought months ago) without knowing which month to look in first —
        # matches description, merchant, and notes so any of those fields can surface it.
        pattern = f"%{search.strip()}%"
        search_clause = or_(
            Transaction.description.ilike(pattern),
            Transaction.merchant.ilike(pattern),
            Transaction.notes.ilike(pattern),
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = (await session.execute(count_stmt)).scalar_one()

    # id as a tiebreaker keeps pagination stable when many rows share a date/amount.
    if sort == "amount_desc":
        stmt = stmt.order_by(Transaction.amount.desc(), Transaction.id.desc())
    elif sort == "amount_asc":
        stmt = stmt.order_by(Transaction.amount.asc(), Transaction.id.desc())
    else:
        stmt = stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    items = list(result.scalars().all())

    return TransactionPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/years", response_model=list[int])
async def list_transaction_years(session: AsyncSession = Depends(get_session)) -> list[int]:
    """Full range of years to offer in the year picker — from the earliest
    transaction through the current year, so a gap year with no activity
    still shows up (as zero) instead of silently disappearing from the UI."""
    bounds = await session.execute(select(func.min(Transaction.date), func.max(Transaction.date)))
    min_date, max_date = bounds.one()
    current_year = date_.today().year
    if min_date is None:
        return [current_year]
    return list(range(min_date.year, max(max_date.year, current_year) + 1))


@router.get("/{transaction_id}/transfer-matches", response_model=TransferMatchResponse)
async def list_transfer_matches(
    transaction_id: int, session: AsyncSession = Depends(get_session)
) -> TransferMatchResponse:
    transaction = await _load_transaction(session, transaction_id)
    ranked = await find_transfer_match_candidates(session, transaction, eager_options=_EAGER)
    return TransferMatchResponse(
        candidates=[
            TransferMatchCandidate(transaction=candidate, delta_seconds=delta)
            for candidate, delta in ranked
        ]
    )


@router.post("/merge-transfer", response_model=TransactionRead, status_code=201)
async def merge_transfer(
    payload: TransferMergeRequest, session: AsyncSession = Depends(get_session)
) -> Transaction:
    source = await session.get(Transaction, payload.source_transaction_id)
    destination = await session.get(Transaction, payload.destination_transaction_id)
    if source is None or destination is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    transfer = await merge_into_transfer(
        session,
        source=source,
        destination=destination,
        transfer_amount=payload.transfer_amount,
        exchange_rate=payload.exchange_rate,
        fee_amount=payload.fee_amount,
    )
    return await _load_transaction(session, transfer.id)


@router.post("", response_model=TransactionRead, status_code=201)
async def create_transaction(payload: TransactionCreate, session: AsyncSession = Depends(get_session)) -> Transaction:
    await _ensure_category_matches_type(session, payload.category_id, payload.type)
    if payload.type == TransactionType.REFUND:
        await ensure_refund_target(
            session,
            refund_of_transaction_id=payload.refund_of_transaction_id,  # type: ignore[arg-type]
            amount=payload.amount,
        )
    if payload.type in (TransactionType.EXPENSE, TransactionType.REFUND):
        await ensure_cashback_category_for_account(
            session,
            cashback_category_id=payload.cashback_category_id,
            account_id=payload.account_id,
        )
    fields = payload.model_dump(exclude={"tag_ids", "splits"})
    digest = fields.pop("import_hash", None)
    if payload.type == TransactionType.EXPENSE:
        fields["cashback_amount"] = await resolve_expense_cashback_amount(
            session,
            account_id=payload.account_id,
            cashback_category_id=payload.cashback_category_id,
            amount=payload.amount,
            tx_date=fields["date"],
            explicit_amount=payload.cashback_amount,
            amount_provided=payload.cashback_amount is not None,
        )
    transaction = Transaction(**fields)
    attach_import_hash(transaction, payload.account_id, digest)
    transaction.tags = await _resolve_tags(session, payload.tag_ids)
    if payload.splits:
        transaction.splits = await _build_splits(session, payload.splits, payload.type)
    session.add(transaction)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Unique (account_id, import_hash) — treat as a client-visible conflict.
        detail = str(exc)
        if payload.import_hash and (
            "uq_transactions_account_import_hash" in detail
            or "uq_transaction_import_hashes_account_hash" in detail
        ):
            raise HTTPException(status_code=409, detail="Duplicate import_hash for this account") from exc
        raise
    return await _load_transaction(session, transaction.id)


@router.post("/import/gpb-html", response_model=GpbHtmlConvertResult)
async def convert_gpb_html_statement(payload: GpbHtmlConvertRequest) -> GpbHtmlConvertResult:
    """Turn a pasted Gazprombank history HTML fragment into a CSV the existing
    import wizard (tbank-compatible headers) can consume. No DB writes."""
    today = payload.today or date_.today()
    csv_text, row_count = convert_gpb_html_to_csv(payload.html, today=today)
    if row_count == 0:
        raise HTTPException(status_code=400, detail="No operations found in HTML")
    return GpbHtmlConvertResult(csv=csv_text, row_count=row_count)


@router.post("/import/alfa-html", response_model=AlfaHtmlConvertResult)
async def convert_alfa_html_statement(payload: AlfaHtmlConvertRequest) -> AlfaHtmlConvertResult:
    """Turn a pasted Alfa-Bank history HTML fragment into Alfa CSV the import
    wizard (alfabank preset) can consume. No DB writes."""
    today = payload.today or date_.today()
    csv_text, row_count = convert_alfa_html_to_csv(payload.html, today=today)
    if row_count == 0:
        raise HTTPException(status_code=400, detail="No operations found in HTML")
    return AlfaHtmlConvertResult(csv=csv_text, row_count=row_count)


@router.post("/bulk", response_model=TransactionBulkCreateResult, status_code=201)
async def bulk_create_transactions(
    payload: TransactionBulkCreate, session: AsyncSession = Depends(get_session)
) -> TransactionBulkCreateResult:
    """CSV import lands here — see schemas.TransactionBulkCreate. Bad rows
    still 400 the whole request; rows whose import_hash already exists on
    the account are skipped instead of aborting. Rows that match an older
    transaction by date/amount/description (any type) without that hash yet
    get the fingerprint backfilled instead of a duplicate insert."""
    for item in payload.items:
        await _ensure_category_matches_type(session, item.category_id, item.type)
        if item.type == TransactionType.REFUND:
            await ensure_refund_target(
                session,
                refund_of_transaction_id=item.refund_of_transaction_id,  # type: ignore[arg-type]
                amount=item.amount,
            )
        if item.type in (TransactionType.EXPENSE, TransactionType.REFUND):
            await ensure_cashback_category_for_account(
                session,
                cashback_category_id=item.cashback_category_id,
                account_id=item.account_id,
            )

    hashes_by_account: dict[int, set[str]] = {}
    for item in payload.items:
        if item.import_hash:
            hashes_by_account.setdefault(item.account_id, set()).add(item.import_hash)

    # Dedupe against both legs stored after merge-transfer (and migrated legacy hashes).
    existing_hashes: set[tuple[int, str]] = set()
    for account_id, hashes in hashes_by_account.items():
        rows = await session.execute(
            select(TransactionImportHash.account_id, TransactionImportHash.import_hash).where(
                TransactionImportHash.account_id == account_id,
                TransactionImportHash.import_hash.in_(hashes),
            )
        )
        existing_hashes.update((row[0], row[1]) for row in rows.all())

    transactions = []
    skipped = 0
    hashes_backfilled = 0
    seen_in_batch: set[tuple[int, str]] = set()
    for item in payload.items:
        if item.import_hash:
            key = (item.account_id, item.import_hash)
            if key in existing_hashes or key in seen_in_batch:
                skipped += 1
                continue
            seen_in_batch.add(key)

            # Older rows (incl. expense→transfer) may lack this fingerprint —
            # attach it instead of inserting a second expense.
            match = (
                await session.execute(
                    select(Transaction)
                    .options(selectinload(Transaction.import_hashes))
                    .where(
                        Transaction.account_id == item.account_id,
                        Transaction.date == item.date,
                        Transaction.amount == item.amount,
                        func.lower(func.trim(Transaction.description)) == item.description.strip().lower(),
                    )
                    .order_by(Transaction.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if match is not None and backfill_import_hash(match, item.account_id, item.import_hash):
                hashes_backfilled += 1
                existing_hashes.add(key)
                continue
            if match is not None:
                # Same identity already has this digest via another path — treat as skip.
                skipped += 1
                continue

        fields = item.model_dump(exclude={"tag_ids", "splits"})
        digest = fields.pop("import_hash", None)
        if item.type == TransactionType.EXPENSE:
            fields["cashback_amount"] = await resolve_expense_cashback_amount(
                session,
                account_id=item.account_id,
                cashback_category_id=item.cashback_category_id,
                amount=item.amount,
                tx_date=fields["date"],
                explicit_amount=item.cashback_amount,
                amount_provided=item.cashback_amount is not None,
            )
        transaction = Transaction(**fields)
        attach_import_hash(transaction, item.account_id, digest)
        transaction.tags = await _resolve_tags(session, item.tag_ids)
        if item.splits:
            transaction.splits = await _build_splits(session, item.splits, item.type)
        transactions.append(transaction)

    if transactions or hashes_backfilled:
        if transactions:
            session.add_all(transactions)
        await session.commit()
        log_destructive(
            "transactions.bulk_created",
            count=len(transactions),
            skipped_duplicates=skipped,
            hashes_backfilled=hashes_backfilled,
        )
    return TransactionBulkCreateResult(
        created=len(transactions),
        skipped_duplicates=skipped,
        hashes_backfilled=hashes_backfilled,
    )


@router.patch("/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int, payload: TransactionUpdate, session: AsyncSession = Depends(get_session)
) -> Transaction:
    # Eager-loads tags and splits — assigning transaction.tags/splits below
    # would otherwise lazy-load the current collection first to diff
    # against, which async SQLAlchemy can't do outside an explicit await
    # (MissingGreenlet).
    transaction = await session.get(
        Transaction,
        transaction_id,
        options=[selectinload(Transaction.tags), selectinload(Transaction.splits)],
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    updates = payload.model_dump(exclude_unset=True, exclude={"tag_ids", "splits"})
    # Checks run against the row as it would look after the patch, not just
    # the fields sent: switching type alone can invalidate fields left
    # untouched.
    effective_type = updates.get("type", transaction.type)
    effective_category_id = updates.get("category_id", transaction.category_id)
    effective_account_id = updates.get("account_id", transaction.account_id)
    effective_transfer_account_id = updates.get("transfer_account_id", transaction.transfer_account_id)
    effective_refund_of = updates.get("refund_of_transaction_id", transaction.refund_of_transaction_id)
    effective_amount = updates.get("amount", transaction.amount)
    effective_cashback_category_id = updates.get("cashback_category_id", transaction.cashback_category_id)
    effective_cashback_amount = updates.get("cashback_amount", transaction.cashback_amount)
    effective_is_cashback = updates.get("is_cashback", transaction.is_cashback)

    if "occurred_at" in updates or "date" in updates:
        date_value, occurred_at = normalize_occurred_at(
            date=updates.get("date", transaction.date if "occurred_at" not in updates else None),
            occurred_at=updates.get("occurred_at", transaction.occurred_at if "date" not in updates else None),
        )
        updates["date"] = date_value
        updates["occurred_at"] = occurred_at

    await _ensure_category_matches_type(session, effective_category_id, effective_type)
    if effective_type in (TransactionType.EXPENSE, TransactionType.REFUND):
        await ensure_cashback_category_for_account(
            session,
            cashback_category_id=effective_cashback_category_id,
            account_id=effective_account_id,
        )
    violation = transfer_rule_violation(
        type=effective_type,
        account_id=effective_account_id,
        transfer_account_id=effective_transfer_account_id,
        category_id=effective_category_id,
    )
    if violation:
        raise HTTPException(status_code=400, detail=violation)
    refund_violation = refund_rule_violation(
        type=effective_type,
        refund_of_transaction_id=effective_refund_of,
        category_id=effective_category_id,
        transfer_account_id=effective_transfer_account_id,
    )
    if refund_violation:
        raise HTTPException(status_code=400, detail=refund_violation)

    if effective_type == TransactionType.TRANSFER:
        # Becoming a transfer always clears cashback (merge path does the same).
        updates["cashback_category_id"] = None
        updates["cashback_amount"] = None
        updates["is_cashback"] = False
        effective_cashback_category_id = None
        effective_cashback_amount = None
        effective_is_cashback = False
        if updates.get("transfer_amount", transaction.transfer_amount) is None and "transfer_amount" not in updates:
            updates["transfer_amount"] = effective_amount
    elif (
        "type" in updates
        and effective_type == TransactionType.REFUND
        and transaction.type != TransactionType.REFUND
    ):
        # Becoming a refund (from income, expense, …) must not keep purchase
        # cashback or is_cashback. UI clears fields on type change; partial
        # PATCH may omit them; a full form save used to re-send a positive
        # amount — drop that carry-over. Explicit clawback (negative) is kept.
        updates["is_cashback"] = False
        effective_is_cashback = False
        amount_in_patch = "cashback_amount" in updates
        explicit_amount = updates.get("cashback_amount") if amount_in_patch else None
        keep_clawback = (
            amount_in_patch
            and explicit_amount is not None
            and explicit_amount < 0
        )
        if not keep_clawback:
            updates["cashback_amount"] = None
            updates["cashback_category_id"] = None
            effective_cashback_amount = None
            effective_cashback_category_id = None
    elif effective_type == TransactionType.EXPENSE:
        amount_provided = "cashback_amount" in updates
        should_recompute = not amount_provided and (
            "cashback_category_id" in updates
            or "amount" in updates
            or "account_id" in updates
            or "date" in updates
            or "occurred_at" in updates
        )
        if amount_provided or should_recompute or (
            effective_cashback_category_id is not None and transaction.cashback_amount is None
        ):
            tx_date = updates.get("date", transaction.date)
            resolved = await resolve_expense_cashback_amount(
                session,
                account_id=effective_account_id,
                cashback_category_id=effective_cashback_category_id,
                amount=effective_amount,
                tx_date=tx_date,
                explicit_amount=updates.get("cashback_amount") if amount_provided else None,
                amount_provided=amount_provided,
            )
            updates["cashback_amount"] = resolved
            effective_cashback_amount = resolved

    cashback_violation = cashback_rule_violation(
        type=effective_type,
        cashback_category_id=effective_cashback_category_id,
        cashback_amount=effective_cashback_amount,
        is_cashback=bool(effective_is_cashback),
    )
    if cashback_violation:
        raise HTTPException(status_code=400, detail=cashback_violation)

    if effective_type == TransactionType.REFUND:
        await ensure_refund_target(
            session,
            refund_of_transaction_id=effective_refund_of,  # type: ignore[arg-type]
            amount=effective_amount,
            exclude_refund_id=transaction_id,
        )

    if payload.splits is not None:
        split_count = len(payload.splits)
        split_total = sum((s.amount for s in payload.splits), Decimal("0")) if payload.splits else None
    else:
        # Splits weren't touched by this patch — check the existing rows as
        # they stand. Reading straight off the ORM objects here (not
        # rebuilding TransactionSplitInput) on purpose: an existing split's
        # category_id can be None if that category was since deleted, and
        # the sum check below needs none of that — only tags/category
        # values that were actually just fetched from the caller could ever
        # need to be re-validated, and those go through payload.splits above.
        split_count = len(transaction.splits)
        split_total = sum((s.amount for s in transaction.splits), Decimal("0")) if transaction.splits else None
    split_violation = split_rule_violation(
        type=effective_type,
        amount=effective_amount,
        category_id=effective_category_id,
        split_count=split_count,
        split_total=split_total,
    )
    if split_violation:
        raise HTTPException(status_code=400, detail=split_violation)

    for field, value in updates.items():
        setattr(transaction, field, value)
    if payload.tag_ids is not None:
        transaction.tags = await _resolve_tags(session, payload.tag_ids)
    if payload.splits is not None:
        transaction.splits = await _build_splits(session, payload.splits, effective_type)
    await session.commit()
    return await _load_transaction(session, transaction_id)


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(transaction_id: int, session: AsyncSession = Depends(get_session)) -> None:
    transaction = await session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await session.delete(transaction)
    await session.commit()
