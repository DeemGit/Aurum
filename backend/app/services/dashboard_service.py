"""Aggregation logic behind the Overview dashboard."""
import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TransactionType
from app.models.tag import Tag
from app.models.transaction import Transaction
from app.schemas.dashboard import CategoryBreakdownChildItem, CategoryBreakdownItem, DashboardSummary
from app.services.category_rollup import rollup_spending_by_top_level_category
from app.services.settings_service import list_dashboard_excluded_tag_ids

# Categorical slots are capped at 8 (dataviz skill: a 9th series folds into "Other",
# never a generated hue) — this is also the exact size of the default category set.
MAX_CHART_SLICES = 8
OTHER_SLICE_COLOR = "#898781"  # muted ink, reserved for the non-categorical rollup


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _without_excluded_tags(excluded_tag_ids: list[int]):
    """SQLAlchemy clause: transaction has none of the excluded tags."""
    return ~Transaction.tags.any(Tag.id.in_(excluded_tag_ids))


async def get_dashboard_summary(session: AsyncSession, year: int, month: int) -> DashboardSummary:
    start, end = _month_bounds(year, month)
    excluded_tag_ids = await list_dashboard_excluded_tag_ids(session)

    totals_stmt = (
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.date >= start, Transaction.date <= end)
        .group_by(Transaction.type)
    )
    if excluded_tag_ids:
        totals_stmt = totals_stmt.where(_without_excluded_tags(excluded_tag_ids))
    totals_result = await session.execute(totals_stmt)
    totals: dict[TransactionType, Decimal] = {row[0]: row[1] for row in totals_result.all()}

    real_income = totals.get(TransactionType.INCOME, Decimal("0"))
    raw_spent = totals.get(TransactionType.EXPENSE, Decimal("0"))
    transferred_out = totals.get(TransactionType.TRANSFER, Decimal("0"))

    # Refunds attribute back to the purchase month: reduce spent by refunds
    # whose original expense falls in this month (not by refund.date).
    # Only non-excluded expenses and non-excluded refunds participate — a
    # tagged refund must not shrink spent for an expense already omitted.
    expense_ids_stmt = select(Transaction.id).where(
        Transaction.type == TransactionType.EXPENSE,
        Transaction.date >= start,
        Transaction.date <= end,
    )
    if excluded_tag_ids:
        expense_ids_stmt = expense_ids_stmt.where(_without_excluded_tags(excluded_tag_ids))
    refund_attr_stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.type == TransactionType.REFUND,
        Transaction.refund_of_transaction_id.in_(expense_ids_stmt),
    )
    if excluded_tag_ids:
        refund_attr_stmt = refund_attr_stmt.where(_without_excluded_tags(excluded_tag_ids))
    attributed_refunds = (await session.execute(refund_attr_stmt)).scalar_one()
    spent = raw_spent - attributed_refunds
    if spent < 0:
        spent = Decimal("0")

    # A subcategory's spending rolls up into its parent's slice, and a split
    # transaction's category_id=NULL means its category lives on its split
    # lines instead — rollup_spending_by_top_level_category handles both
    # the same way a plain transaction's category already was.
    rows = await rollup_spending_by_top_level_category(
        session,
        transaction_type=TransactionType.EXPENSE,
        start_date=start,
        end_date=end,
        exclude_tag_ids=excluded_tag_ids,
    )

    top_rows, rest_rows = rows[:MAX_CHART_SLICES], rows[MAX_CHART_SLICES:]

    def _percent(amount: Decimal) -> float:
        return float(amount / spent * 100) if spent else 0.0

    spending_by_category = [
        CategoryBreakdownItem(
            category_id=row.category_id, name=row.name, color=row.color, icon=row.icon,
            amount=row.amount, percent=_percent(row.amount),
            children=[
                CategoryBreakdownChildItem(
                    category_id=child.category_id, name=child.name, color=child.color, icon=child.icon,
                    amount=child.amount,
                )
                for child in row.children
            ],
        )
        for row in top_rows
    ]

    if rest_rows:
        other_amount = sum((row.amount for row in rest_rows), Decimal("0"))
        spending_by_category.append(
            CategoryBreakdownItem(
                category_id=None, name="Other", color=OTHER_SLICE_COLOR, icon="more-horizontal",
                amount=other_amount, percent=_percent(other_amount),
            )
        )

    return DashboardSummary(
        year=year,
        month=month,
        real_income=real_income,
        spent=spent,
        net=real_income - spent,
        transferred_out=transferred_out,
        spending_by_category=spending_by_category,
    )
