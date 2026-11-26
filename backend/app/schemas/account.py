from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AccountType, CashbackRounding


def _credit_cycle_fields_ok(
    *,
    type: AccountType,
    statement_day: int | None,
    payment_day: int | None,
    grace_period_days: int | None,
) -> str | None:
    """Credit cards need a full cycle; other types must not carry cycle fields."""
    if type == AccountType.CREDIT_CARD:
        if statement_day is None or payment_day is None or grace_period_days is None:
            return "statement_day, payment_day, and grace_period_days are required for credit_card"
        return None
    if statement_day is not None or payment_day is not None or grace_period_days is not None:
        return "statement_day, payment_day, and grace_period_days are only valid for credit_card"
    return None


class AccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType = AccountType.CHECKING
    currency: str = Field(default="USD", min_length=3, max_length=3)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    cashback_rounding: CashbackRounding = CashbackRounding.PERCENT_FLOOR
    statement_day: int | None = Field(default=None, ge=1, le=28)
    payment_day: int | None = Field(default=None, ge=1, le=28)
    grace_period_days: int | None = Field(default=None, ge=1, le=120)


class AccountCreate(AccountBase):
    @model_validator(mode="after")
    def _validate_credit_cycle(self) -> "AccountCreate":
        problem = _credit_cycle_fields_ok(
            type=self.type,
            statement_day=self.statement_day,
            payment_day=self.payment_day,
            grace_period_days=self.grace_period_days,
        )
        if problem:
            raise ValueError(problem)
        return self


class AccountUpdate(BaseModel):
    # currency is immutable after create — intentionally omitted (see account_service.update_account).
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: AccountType | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    is_archived: bool | None = None
    cashback_rounding: CashbackRounding | None = None
    statement_day: int | None = Field(default=None, ge=1, le=28)
    payment_day: int | None = Field(default=None, ge=1, le=28)
    grace_period_days: int | None = Field(default=None, ge=1, le=120)


class AccountRead(AccountBase):
    """Used wherever an account is embedded in another response (e.g.
    TransactionRead.account) — deliberately balance-less so adding a field
    here can never break an unrelated endpoint's serialization."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_archived: bool


class AccountWithBalance(AccountRead):
    """The Accounts page's shape — adds the live balance (see
    services/account_service.py), summed from Transaction rows rather than
    stored, the same "derive it" approach net_worth_service.py uses for
    Cash. Used only by /api/accounts' own endpoints, never nested."""

    balance: Decimal
    # Unpaid amount due by credit_due_date (null when not a configured credit card).
    credit_due_amount: Decimal | None = None
    credit_due_date: date_ | None = None
