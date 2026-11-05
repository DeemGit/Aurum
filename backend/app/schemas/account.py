from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountType, CashbackRounding


class AccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType = AccountType.CHECKING
    currency: str = Field(default="USD", min_length=3, max_length=3)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    cashback_rounding: CashbackRounding = CashbackRounding.PERCENT_FLOOR


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    # currency is immutable after create — intentionally omitted (see account_service.update_account).
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: AccountType | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    is_archived: bool | None = None
    cashback_rounding: CashbackRounding | None = None


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
