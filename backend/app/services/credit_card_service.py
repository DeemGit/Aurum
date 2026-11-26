"""Credit-card statement cycles and amount due for repayment.

Billing period runs from statement_day inclusive to the day before the next
statement_day (e.g. 25 Sep – 24 Oct). That period is due on payment_day in the
month after the period closes (24 Oct → 18 Nov). Transfers onto the card
(transfer_account_id = card) pay down periods FIFO by due date.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date as date_
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.enums import AccountType, TransactionType
from app.models.transaction import Transaction


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _clamp_day(year: int, month: int, day: int) -> date_:
    return date_(year, month, min(day, monthrange(year, month)[1]))


def statement_period_containing(day: date_, statement_day: int) -> tuple[date_, date_]:
    """Inclusive [start, end] for the statement cycle that contains `day`."""
    if day.day >= statement_day:
        start = _clamp_day(day.year, day.month, statement_day)
    else:
        y, m = _add_months(day.year, day.month, -1)
        start = _clamp_day(y, m, statement_day)
    y2, m2 = _add_months(start.year, start.month, 1)
    next_start = _clamp_day(y2, m2, statement_day)
    end = next_start - timedelta(days=1)
    return start, end


def due_date_for_period_end(period_end: date_, payment_day: int) -> date_:
    """Payment falls on payment_day in the month after the period closes."""
    y, m = _add_months(period_end.year, period_end.month, 1)
    return _clamp_day(y, m, payment_day)


def next_payment_date(today: date_, payment_day: int) -> date_:
    """Soonest payment_day on or after today."""
    candidate = _clamp_day(today.year, today.month, payment_day)
    if candidate >= today:
        return candidate
    y, m = _add_months(today.year, today.month, 1)
    return _clamp_day(y, m, payment_day)


@dataclass
class StatementPeriod:
    start: date_
    end: date_
    due_date: date_
    charges: Decimal
    remaining: Decimal


def _iter_period_starts(first: date_, last: date_, statement_day: int) -> list[date_]:
    start, _ = statement_period_containing(first, statement_day)
    end_start, _ = statement_period_containing(last, statement_day)
    out: list[date_] = []
    cur = start
    while cur <= end_start:
        out.append(cur)
        y, m = _add_months(cur.year, cur.month, 1)
        cur = _clamp_day(y, m, statement_day)
    return out


def allocate_credit_due(
    *,
    statement_day: int,
    payment_day: int,
    charges_by_date: list[tuple[date_, Decimal]],
    payments: list[tuple[date_, Decimal]],
    today: date_,
) -> tuple[Decimal | None, date_ | None]:
    """FIFO payments against statement periods → (due_amount, due_date).

    Returns (None, None) when there is nothing due. due_amount can be 0 with a
    due_date when the next anchor has no unpaid remainder (callers may still
    prefer null — we return null when amount is 0).
    """
    if not charges_by_date and not payments:
        return None, None

    dates = [d for d, _ in charges_by_date] + [d for d, _ in payments] + [today]
    first = min(dates)
    last = max(dates)

    periods: list[StatementPeriod] = []
    for start in _iter_period_starts(first, last, statement_day):
        _, end = statement_period_containing(start, statement_day)
        due = due_date_for_period_end(end, payment_day)
        periods.append(
            StatementPeriod(start=start, end=end, due_date=due, charges=Decimal("0"), remaining=Decimal("0"))
        )

    for tx_date, amount in charges_by_date:
        for period in periods:
            if period.start <= tx_date <= period.end:
                period.charges += amount
                break

    for period in periods:
        period.remaining = max(period.charges, Decimal("0"))

    # Payments in chronological order against oldest due first.
    ordered_payments = sorted(payments, key=lambda item: item[0])
    for _pay_date, pay_amount in ordered_payments:
        left = pay_amount
        for period in sorted(periods, key=lambda p: p.due_date):
            if left <= 0:
                break
            if period.remaining <= 0:
                continue
            applied = min(period.remaining, left)
            period.remaining -= applied
            left -= applied

    unpaid = [p for p in periods if p.remaining > 0]
    if not unpaid:
        return None, None

    overdue = [p for p in unpaid if p.due_date < today]
    if overdue:
        due_date = min(p.due_date for p in overdue)
        amount = sum((p.remaining for p in overdue), Decimal("0"))
        return amount, due_date

    anchor = next_payment_date(today, payment_day)
    due_slices = [p for p in unpaid if p.due_date <= anchor]
    if not due_slices:
        # Unpaid only on later cycles (e.g. next statement) — nothing due yet.
        return None, None

    amount = sum((p.remaining for p in due_slices), Decimal("0"))
    due_date = max(p.due_date for p in due_slices)
    return amount, due_date


async def credit_due_for_account(
    session: AsyncSession,
    account: Account,
    *,
    today: date_ | None = None,
) -> tuple[Decimal | None, date_ | None]:
    if (
        account.type != AccountType.CREDIT_CARD
        or account.statement_day is None
        or account.payment_day is None
    ):
        return None, None

    today = today or date_.today()
    stmt = select(Transaction).where(
        or_(
            Transaction.account_id == account.id,
            Transaction.transfer_account_id == account.id,
        )
    )
    rows = (await session.execute(stmt)).scalars().all()

    charges: list[tuple[date_, Decimal]] = []
    payments: list[tuple[date_, Decimal]] = []
    for tx in rows:
        if tx.account_id == account.id and tx.type == TransactionType.EXPENSE:
            charges.append((tx.date, tx.amount))
        elif tx.account_id == account.id and tx.type == TransactionType.REFUND:
            charges.append((tx.date, -tx.amount))
        elif tx.type == TransactionType.TRANSFER and tx.transfer_account_id == account.id:
            credited = tx.transfer_amount if tx.transfer_amount is not None else tx.amount
            payments.append((tx.date, credited))

    return allocate_credit_due(
        statement_day=account.statement_day,
        payment_day=account.payment_day,
        charges_by_date=charges,
        payments=payments,
        today=today,
    )
