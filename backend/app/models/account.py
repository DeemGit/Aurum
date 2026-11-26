"""An account is any place money lives: bank account, card, cash, wallet."""
from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AccountType, CashbackRounding
from app.models.mixins import TimestampMixin


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type", native_enum=False, length=20),
        nullable=False,
        default=AccountType.CHECKING,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    # Hex color used for account-scoped UI accents (e.g. transaction list avatars).
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # How auto cashback on expenses is rounded for this account's bank rules.
    # values_callable: persist/read .value ("percent_floor"), not .name — matches
    # the migration server_default and the API/frontend wire format.
    cashback_rounding: Mapped[CashbackRounding] = mapped_column(
        Enum(
            CashbackRounding,
            name="cashback_rounding",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=CashbackRounding.PERCENT_FLOOR,
    )
    # Credit-card billing cycle (nullable for other account types).
    # statement_day: first day of the reporting period (e.g. 25).
    # payment_day: calendar day the closed period must be repaid (e.g. 18).
    # grace_period_days: bank-stated max grace (display); due date uses payment_day.
    statement_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account",
        foreign_keys="Transaction.account_id",
        cascade="all, delete-orphan",
    )
