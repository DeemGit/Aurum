from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel


class CashFlowPoint(BaseModel):
    year: int
    month: int
    income: Decimal
    expense: Decimal
    # Cash returned via refunds dated in this month — not classified as income.
    refunds_received: Decimal = Decimal("0")
    net: Decimal


class CashFlowResponse(BaseModel):
    start_date: date_ | None
    end_date: date_ | None
    points: list[CashFlowPoint]
    total_income: Decimal
    total_expense: Decimal
    total_refunds_received: Decimal = Decimal("0")
    total_net: Decimal
