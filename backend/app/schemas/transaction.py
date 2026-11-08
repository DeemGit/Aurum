from datetime import date as date_
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.text import capitalize_first_letter
from app.models.enums import TransactionType
from app.schemas.account import AccountRead
from app.schemas.category import CategoryRead
from app.schemas.tag import TagRead


def transfer_rule_violation(
    *,
    type: TransactionType,
    account_id: int,
    transfer_account_id: int | None,
    category_id: int | None,
) -> str | None:
    """The transfer invariants in one place, returning the problem as text or
    None if the combination is valid.

    Both halves of the write path go through this: the create schema below
    (as a pydantic validator) and the PATCH route (see
    routes/transactions.py). Enforcing it on create only used to let an edit
    produce a row that create would have rejected — most damagingly a
    transfer with no transfer_account_id, which TransactionRead itself can't
    serialize, so the row broke every later read of the transactions list.
    """
    if type == TransactionType.TRANSFER:
        if not transfer_account_id:
            return "transfer_account_id is required for transfer transactions"
        if transfer_account_id == account_id:
            return "transfer_account_id must differ from account_id"
        if category_id:
            return "category_id is not valid for transfer transactions"
    elif transfer_account_id:
        return "transfer_account_id is only valid for transfer transactions"
    return None


def refund_rule_violation(
    *,
    type: TransactionType,
    refund_of_transaction_id: int | None,
    category_id: int | None,
    transfer_account_id: int | None,
) -> str | None:
    if type == TransactionType.REFUND:
        if not refund_of_transaction_id:
            return "refund_of_transaction_id is required for refund transactions"
        if category_id:
            return "category_id is not valid for refund transactions"
        if transfer_account_id:
            return "transfer_account_id is not valid for refund transactions"
    elif refund_of_transaction_id:
        return "refund_of_transaction_id is only valid for refund transactions"
    return None


def cashback_rule_violation(
    *,
    type: TransactionType,
    cashback_category_id: int | None,
    cashback_amount: Decimal | None,
    is_cashback: bool,
) -> str | None:
    if type == TransactionType.TRANSFER:
        if cashback_category_id is not None or cashback_amount is not None:
            return "cashback fields are not valid for transfer transactions"
        if is_cashback:
            return "is_cashback is not valid for transfer transactions"
    if type == TransactionType.REFUND:
        if is_cashback:
            return "is_cashback is not valid for refund transactions"
    if is_cashback and type != TransactionType.INCOME:
        return "is_cashback is only valid for income transactions"
    if type not in (TransactionType.EXPENSE, TransactionType.REFUND) and cashback_category_id is not None:
        if type != TransactionType.INCOME:
            return "cashback_category_id is only valid for expense or refund transactions"
    if type == TransactionType.INCOME and cashback_category_id is not None:
        return "cashback_category_id is not valid for income transactions"
    if type not in (TransactionType.REFUND, TransactionType.EXPENSE) and cashback_amount is not None:
        if type != TransactionType.INCOME:
            return "cashback_amount is only valid for expense or refund transactions"
    if type == TransactionType.INCOME and cashback_amount is not None:
        return "cashback_amount is not valid for income — use is_cashback"
    return None


def split_rule_violation(
    *,
    type: TransactionType,
    amount: Decimal,
    category_id: int | None,
    split_count: int,
    split_total: Decimal | None,
) -> str | None:
    """The split invariants in one place, same shape as transfer_rule_violation
    above — checked on create, and against the row *as it would look after
    a patch* on update (see routes/transactions.py), so an edit can't leave
    a transaction whose splits no longer add up to its own amount.

    Takes counts/totals rather than the split objects themselves: the
    update path's "splits weren't touched by this patch" case has to check
    the existing ORM rows, whose category_id can be None (the category was
    since deleted) — nothing here needs a live category to check the sum.
    """
    if split_count == 0:
        return None
    if type in (TransactionType.TRANSFER, TransactionType.REFUND):
        return f"splits are not valid for {type.value} transactions"
    if category_id is not None:
        return "category_id must be omitted when splitting a transaction across categories"
    if split_count < 2:
        return "splitting a transaction needs at least 2 categories"
    if split_total != amount:
        return f"split amounts ({split_total}) must add up to the transaction amount ({amount})"
    return None


def normalize_occurred_at(*, date: date_ | None, occurred_at: datetime | None) -> tuple[date_, datetime]:
    """Derive the (date, occurred_at) pair from whichever side the client sent.

    ``occurred_at`` is stored as UTC, but the calendar ``date`` must stay the
    bank/wall-clock day — converting first and taking ``.date()`` would turn
    ``2026-11-01T02:23+03:00`` into ``2026-10-31``.
    """
    if occurred_at is not None:
        # Wall-clock calendar day before converting the absolute moment to UTC.
        wall_date = occurred_at.date()
        if occurred_at.tzinfo is None:
            occurred_utc = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_utc = occurred_at.astimezone(timezone.utc)
        return (date if date is not None else wall_date), occurred_utc
    if date is None:
        raise ValueError("date or occurred_at is required")
    return date, datetime(date.year, date.month, date.day, tzinfo=timezone.utc)


class TransactionFields(BaseModel):
    """A transaction's shape, without the rules that only make sense while
    writing one. Reading goes through this: rows already in the database can
    stop satisfying a write-time rule through no fault of their own — the
    transfer_account_id FK is ON DELETE SET NULL, so deleting an account
    leaves the transfers that pointed at it with no destination — and
    refusing to serialize such a row would take the whole transactions list
    down with it, leaving no way in the UI to find and delete the row."""

    account_id: int
    category_id: int | None = None
    transfer_account_id: int | None = None
    refund_of_transaction_id: int | None = None
    type: TransactionType
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    transfer_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    description: str = Field(min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)
    date: date_
    occurred_at: datetime
    import_hash: str | None = Field(default=None, min_length=64, max_length=64)
    cashback_category_id: int | None = None
    cashback_amount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    is_cashback: bool = False

    # Auto-capitalizes "траты на продукты" -> "Траты на продукты" so mixed
    # casing from quick manual entry doesn't need fixing by hand later.
    @field_validator("description")
    @classmethod
    def _capitalize_description(cls, value: str) -> str:
        return capitalize_first_letter(value)

    @field_validator("import_hash")
    @classmethod
    def _normalize_import_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("import_hash must be a 64-character lowercase hex SHA-256 digest")
        return normalized


class TransactionBase(BaseModel):
    """The write-side shape: the fields plus the invariants a new or edited
    row has to satisfy. date/occurred_at are optional individually — at least
    one must be present and the pair is normalized in the validator."""

    account_id: int
    category_id: int | None = None
    transfer_account_id: int | None = None
    refund_of_transaction_id: int | None = None
    type: TransactionType
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    transfer_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    description: str = Field(min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)
    date: date_ | None = None
    occurred_at: datetime | None = None
    import_hash: str | None = Field(default=None, min_length=64, max_length=64)
    cashback_category_id: int | None = None
    cashback_amount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    is_cashback: bool = False

    @field_validator("description")
    @classmethod
    def _capitalize_description(cls, value: str) -> str:
        return capitalize_first_letter(value)

    @field_validator("import_hash")
    @classmethod
    def _normalize_import_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("import_hash must be a 64-character lowercase hex SHA-256 digest")
        return normalized

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "TransactionBase":
        date_value, occurred_at = normalize_occurred_at(date=self.date, occurred_at=self.occurred_at)
        self.date = date_value
        self.occurred_at = occurred_at

        violation = transfer_rule_violation(
            type=self.type,
            account_id=self.account_id,
            transfer_account_id=self.transfer_account_id,
            category_id=self.category_id,
        )
        if violation:
            raise ValueError(violation)
        refund_violation = refund_rule_violation(
            type=self.type,
            refund_of_transaction_id=self.refund_of_transaction_id,
            category_id=self.category_id,
            transfer_account_id=self.transfer_account_id,
        )
        if refund_violation:
            raise ValueError(refund_violation)
        cashback_violation = cashback_rule_violation(
            type=self.type,
            cashback_category_id=self.cashback_category_id,
            cashback_amount=self.cashback_amount,
            is_cashback=self.is_cashback,
        )
        if cashback_violation:
            raise ValueError(cashback_violation)

        if self.type == TransactionType.TRANSFER:
            # Cashback is never kept on a transfer (merge path clears it too).
            self.cashback_category_id = None
            self.cashback_amount = None
            self.is_cashback = False
            if self.transfer_amount is None:
                self.transfer_amount = self.amount
        else:
            if self.transfer_amount is not None or self.exchange_rate is not None:
                raise ValueError("transfer_amount/exchange_rate are only valid for transfer transactions")
            if self.fee_amount and self.fee_amount != 0:
                raise ValueError("fee_amount is only valid for transfer transactions")
            self.transfer_amount = None
            self.exchange_rate = None
            self.fee_amount = Decimal("0")
        return self


class TransactionSplitInput(BaseModel):
    category_id: int
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    note: str | None = Field(default=None, max_length=200)


class TransactionCreate(TransactionBase):
    tag_ids: list[int] = Field(default_factory=list)
    # None/omitted -> a normal single-category transaction, unchanged from
    # before. 2+ entries -> the amount is divided across categories instead
    # of using category_id (which must then be omitted — see
    # split_rule_violation). A single entry isn't accepted: that's just
    # category_id with extra steps.
    splits: list[TransactionSplitInput] | None = None

    @model_validator(mode="after")
    def _validate_splits(self) -> "TransactionCreate":
        splits = self.splits or []
        violation = split_rule_violation(
            type=self.type,
            amount=self.amount,
            category_id=self.category_id,
            split_count=len(splits),
            split_total=sum((s.amount for s in splits), Decimal("0")) if splits else None,
        )
        if violation:
            raise ValueError(violation)
        return self


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    category_id: int | None = None
    transfer_account_id: int | None = None
    refund_of_transaction_id: int | None = None
    type: TransactionType | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    transfer_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    fee_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)
    date: date_ | None = None
    occurred_at: datetime | None = None
    import_hash: str | None = Field(default=None, min_length=64, max_length=64)
    cashback_category_id: int | None = None
    cashback_amount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    is_cashback: bool | None = None
    # Omitted -> tags untouched; sent (even as []) -> replaces the full tag set.
    tag_ids: list[int] | None = None
    # Omitted -> splits untouched; sent (even as []) -> replaces the full
    # split set (send [] together with a category_id to turn a split
    # transaction back into a normal single-category one).
    splits: list[TransactionSplitInput] | None = None

    @field_validator("description")
    @classmethod
    def _capitalize_description(cls, value: str | None) -> str | None:
        return capitalize_first_letter(value) if value is not None else None

    @field_validator("import_hash")
    @classmethod
    def _normalize_import_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("import_hash must be a 64-character lowercase hex SHA-256 digest")
        return normalized


class CashbackCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str | None = None
    name: str
    color: str | None = None


class TransactionSplitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int | None
    category: CategoryRead | None = None
    amount: Decimal
    note: str | None


class ImportHashRead(BaseModel):
    """One statement fingerprint attached to a transaction (per account)."""

    model_config = ConfigDict(from_attributes=True)

    account_id: int
    import_hash: str


class TransactionRead(TransactionFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account: AccountRead
    # Present for transfers so the list UI can show "Source → Dest" without a second lookup.
    transfer_account: AccountRead | None = None
    category: CategoryRead | None = None
    cashback_category: CashbackCategoryRead | None = None
    tags: list[TagRead] = Field(default_factory=list)
    splits: list[TransactionSplitRead] = Field(default_factory=list)
    # Both legs after merge-transfer; CSV preview uses these for hash dedupe.
    import_hashes: list[ImportHashRead] = Field(default_factory=list)


class ImportHashAttach(BaseModel):
    """Force-link a statement fingerprint to an existing transaction."""

    account_id: int
    import_hash: str = Field(min_length=64, max_length=64)

    @field_validator("import_hash")
    @classmethod
    def _normalize_import_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("import_hash must be a 64-character lowercase hex SHA-256 digest")
        return normalized


class TransactionPage(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int


class TransactionBulkCreate(BaseModel):
    """CSV import (see routes/transactions.py's /bulk): the frontend parses
    the file and maps its columns client-side, then sends already-shaped
    rows here. Validation still fails the whole request on a bad row, but
    rows whose import_hash already exists on the account are skipped rather
    than aborting the batch."""

    items: list[TransactionCreate] = Field(min_length=1, max_length=5000)


class TransactionBulkCreateResult(BaseModel):
    created: int
    skipped_duplicates: int = 0
    # Rows matched to an existing tx that had no fingerprint yet — hash attached, no insert.
    hashes_backfilled: int = 0


class TransferMatchCandidate(BaseModel):
    transaction: TransactionRead
    delta_seconds: int


class TransferMatchResponse(BaseModel):
    candidates: list[TransferMatchCandidate]


class TransferMergeRequest(BaseModel):
    source_transaction_id: int
    destination_transaction_id: int
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    transfer_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)


class GpbHtmlConvertRequest(BaseModel):
    """HTML paste from Gazprombank operation history → CSV for the import wizard."""

    html: str = Field(min_length=1)
    # Calendar day that labels like «Сегодня» / «Вчера» resolve against.
    today: date_ | None = None


class GpbHtmlConvertResult(BaseModel):
    csv: str
    row_count: int


class AlfaHtmlConvertRequest(BaseModel):
    """HTML paste from Alfa-Bank operation history → Alfa CSV for the wizard."""

    html: str = Field(min_length=1)
    # Used only when data-date is missing («сегодня» / «вчера» labels).
    today: date_ | None = None


class AlfaHtmlConvertResult(BaseModel):
    csv: str
    row_count: int
