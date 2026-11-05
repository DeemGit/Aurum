from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CashbackCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class CashbackCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class CashbackCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str | None = None


class AccountCashbackRateItem(BaseModel):
    cashback_category_id: int
    percent: Decimal = Field(ge=0, max_digits=6, decimal_places=3)


class AccountCashbackRatesUpsert(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    rates: list[AccountCashbackRateItem] = Field(default_factory=list)


class AccountCashbackRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    year: int
    month: int
    cashback_category_id: int
    cashback_category: CashbackCategoryRead | None = None
    percent: Decimal


class AccountCashbackRatesCopy(BaseModel):
    from_year: int = Field(ge=2000, le=2100)
    from_month: int = Field(ge=1, le=12)
    to_year: int = Field(ge=2000, le=2100)
    to_month: int = Field(ge=1, le=12)

    @field_validator("to_month", "from_month")
    @classmethod
    def _month_ok(cls, value: int) -> int:
        if not 1 <= value <= 12:
            raise ValueError("month must be 1..12")
        return value


class CashbackReportLine(BaseModel):
    cashback_category_id: int | None
    cashback_category_name: str | None
    expected_amount: Decimal
    actual_amount: Decimal
    refund_adjustment: Decimal


class CashbackReport(BaseModel):
    account_id: int | None
    year: int
    month: int
    expected_total: Decimal
    actual_total: Decimal
    refund_adjustment_total: Decimal
    lines: list[CashbackReportLine]
