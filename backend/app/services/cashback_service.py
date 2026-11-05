"""Cashback category catalogue, per-account monthly rates, and the expected
vs actual cashback report.
"""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_FLOOR

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.cashback import AccountCashbackRate, CashbackCategory
from app.models.enums import AccountType, CashbackRounding, TransactionType
from app.models.transaction import Transaction
from app.schemas.cashback import (
    AccountCashbackRatesCopy,
    AccountCashbackRatesUpsert,
    CashbackCategoryCreate,
    CashbackCategoryUpdate,
    CashbackReport,
    CashbackReportLine,
)


def _reject_cash_account(account: Account) -> None:
    if account.type == AccountType.CASH:
        raise HTTPException(status_code=400, detail="Cash accounts do not support cashback rates")


def compute_cashback_amount(
    amount: Decimal, percent: Decimal, rounding: CashbackRounding
) -> Decimal:
    """Auto cashback is always a whole number; callers may later override to cents."""
    if percent <= 0 or amount <= 0:
        return Decimal("0")
    if rounding == CashbackRounding.BASE_100:
        hundreds = (amount / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR)
        raw = hundreds * percent
    else:
        # percent_floor (default): floor(amount * percent / 100)
        raw = amount * percent / Decimal("100")
    return raw.to_integral_value(rounding=ROUND_FLOOR)


async def resolve_expense_cashback_amount(
    session: AsyncSession,
    *,
    account_id: int,
    cashback_category_id: int | None,
    amount: Decimal,
    tx_date: date,
    explicit_amount: Decimal | None,
    amount_provided: bool,
) -> Decimal | None:
    """If the client sent cashback_amount, keep it. Otherwise derive from rates."""
    if amount_provided:
        return explicit_amount
    if cashback_category_id is None:
        return None
    account = await session.get(Account, account_id)
    if account is None or account.type == AccountType.CASH:
        return Decimal("0")
    rate = (
        await session.execute(
            select(AccountCashbackRate.percent).where(
                AccountCashbackRate.account_id == account_id,
                AccountCashbackRate.year == tx_date.year,
                AccountCashbackRate.month == tx_date.month,
                AccountCashbackRate.cashback_category_id == cashback_category_id,
            )
        )
    ).scalar_one_or_none()
    if rate is None:
        return Decimal("0")
    return compute_cashback_amount(amount, rate, account.cashback_rounding)


async def list_cashback_categories(session: AsyncSession) -> list[CashbackCategory]:
    result = await session.execute(select(CashbackCategory).order_by(CashbackCategory.name))
    return list(result.scalars().all())


async def create_cashback_category(session: AsyncSession, payload: CashbackCategoryCreate) -> CashbackCategory:
    category = CashbackCategory(**payload.model_dump())
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def update_cashback_category(
    session: AsyncSession, category_id: int, payload: CashbackCategoryUpdate
) -> CashbackCategory:
    category = await session.get(CashbackCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Cashback category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await session.commit()
    await session.refresh(category)
    return category


async def delete_cashback_category(session: AsyncSession, category_id: int) -> None:
    category = await session.get(CashbackCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Cashback category not found")
    await session.delete(category)
    await session.commit()


async def list_account_rates(
    session: AsyncSession, account_id: int, year: int, month: int
) -> list[AccountCashbackRate]:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    _reject_cash_account(account)
    result = await session.execute(
        select(AccountCashbackRate)
        .options(selectinload(AccountCashbackRate.cashback_category))
        .where(
            AccountCashbackRate.account_id == account_id,
            AccountCashbackRate.year == year,
            AccountCashbackRate.month == month,
        )
        .order_by(AccountCashbackRate.id)
    )
    return list(result.scalars().all())


async def upsert_account_rates(
    session: AsyncSession, account_id: int, payload: AccountCashbackRatesUpsert
) -> list[AccountCashbackRate]:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    _reject_cash_account(account)

    category_ids = {item.cashback_category_id for item in payload.rates}
    if category_ids:
        found = set(
            (
                await session.execute(select(CashbackCategory.id).where(CashbackCategory.id.in_(category_ids)))
            )
            .scalars()
            .all()
        )
        missing = category_ids - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown cashback category id(s): {sorted(missing)}")

    await session.execute(
        delete(AccountCashbackRate).where(
            AccountCashbackRate.account_id == account_id,
            AccountCashbackRate.year == payload.year,
            AccountCashbackRate.month == payload.month,
        )
    )
    for item in payload.rates:
        session.add(
            AccountCashbackRate(
                account_id=account_id,
                year=payload.year,
                month=payload.month,
                cashback_category_id=item.cashback_category_id,
                percent=item.percent,
            )
        )
    await session.commit()
    return await list_account_rates(session, account_id, payload.year, payload.month)


async def copy_account_rates(
    session: AsyncSession, account_id: int, payload: AccountCashbackRatesCopy
) -> list[AccountCashbackRate]:
    source = await list_account_rates(session, account_id, payload.from_year, payload.from_month)
    from app.schemas.cashback import AccountCashbackRateItem

    return await upsert_account_rates(
        session,
        account_id,
        AccountCashbackRatesUpsert(
            year=payload.to_year,
            month=payload.to_month,
            rates=[
                AccountCashbackRateItem(cashback_category_id=r.cashback_category_id, percent=r.percent)
                for r in source
            ],
        ),
    )


async def get_cashback_report(
    session: AsyncSession, *, year: int, month: int, account_id: int | None
) -> CashbackReport:
    start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    expenses_stmt = select(Transaction).where(
        Transaction.type == TransactionType.EXPENSE,
        Transaction.cashback_category_id.is_not(None),
        Transaction.date >= start,
        Transaction.date <= end,
    )
    if account_id is not None:
        expenses_stmt = expenses_stmt.where(Transaction.account_id == account_id)
    expenses = list((await session.execute(expenses_stmt)).scalars().all())

    # Expected uses the stored per-expense cashback_amount (auto or manual),
    # not a live recompute — so hand edits show up in the report.
    expected_by_cat: dict[int | None, Decimal] = defaultdict(Decimal)
    for expense in expenses:
        expected_by_cat[expense.cashback_category_id] += expense.cashback_amount or Decimal("0")

    income_stmt = select(Transaction).where(
        Transaction.type == TransactionType.INCOME,
        Transaction.is_cashback.is_(True),
        Transaction.date >= start,
        Transaction.date <= end,
    )
    refund_stmt = select(Transaction).where(
        Transaction.type == TransactionType.REFUND,
        Transaction.cashback_amount.is_not(None),
        Transaction.date >= start,
        Transaction.date <= end,
    )
    if account_id is not None:
        income_stmt = income_stmt.where(Transaction.account_id == account_id)
        refund_stmt = refund_stmt.where(Transaction.account_id == account_id)

    actual_by_cat: dict[int | None, Decimal] = defaultdict(Decimal)
    refund_adj_by_cat: dict[int | None, Decimal] = defaultdict(Decimal)

    for income in (await session.execute(income_stmt)).scalars().all():
        actual_by_cat[None] += income.amount
    for refund in (await session.execute(refund_stmt)).scalars().all():
        amount = refund.cashback_amount or Decimal("0")
        refund_adj_by_cat[refund.cashback_category_id] += amount
        actual_by_cat[refund.cashback_category_id] += amount

    categories = {
        c.id: c for c in (await session.execute(select(CashbackCategory))).scalars().all()
    }
    cat_ids = set(expected_by_cat) | set(actual_by_cat) | set(refund_adj_by_cat)
    lines: list[CashbackReportLine] = []
    for cat_id in sorted(cat_ids, key=lambda value: (value is None, value or 0)):
        cat = categories.get(cat_id) if cat_id is not None else None
        lines.append(
            CashbackReportLine(
                cashback_category_id=cat_id,
                cashback_category_name=cat.name if cat else None,
                expected_amount=expected_by_cat.get(cat_id, Decimal("0")),
                actual_amount=actual_by_cat.get(cat_id, Decimal("0")),
                refund_adjustment=refund_adj_by_cat.get(cat_id, Decimal("0")),
            )
        )

    return CashbackReport(
        account_id=account_id,
        year=year,
        month=month,
        expected_total=sum((line.expected_amount for line in lines), Decimal("0")),
        actual_total=sum((line.actual_amount for line in lines), Decimal("0")),
        refund_adjustment_total=sum((line.refund_adjustment for line in lines), Decimal("0")),
        lines=lines,
    )
