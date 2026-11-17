from decimal import Decimal

from pydantic import BaseModel, Field


class CategoryBreakdownChildItem(BaseModel):
    """One subcategory's (or the parent's own direct, un-subcategorized)
    share of a CategoryBreakdownItem's total — see
    services/category_rollup.py's CategoryRollupChildItem."""

    category_id: int
    name: str
    color: str
    icon: str | None
    amount: Decimal


class CategoryBreakdownItem(BaseModel):
    category_id: int | None
    name: str
    color: str
    icon: str | None
    amount: Decimal
    percent: float
    # Populated only when this slice's spend came from more than one
    # distinct category (subcategories, or a mix of the parent itself and
    # its children) — e.g. a receipt split across "Groceries" subcategories.
    children: list[CategoryBreakdownChildItem] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    year: int
    month: int
    real_income: Decimal
    spent: Decimal
    net: Decimal
    transferred_out: Decimal
    # Future incomplete todos in this month with amount + count_in_dashboard.
    planned_expenses: Decimal = Decimal("0")
    planned_income: Decimal = Decimal("0")
    spending_by_category: list[CategoryBreakdownItem]
