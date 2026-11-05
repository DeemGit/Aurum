"""Bank cashback gradations and per-account monthly rates — separate from
expense/income Category rows, because a bank's "Active leisure" bucket is
not the same taxonomy the user uses for spending reports.
"""
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CashbackCategory(Base):
    __tablename__ = "cashback_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    rates: Mapped[list["AccountCashbackRate"]] = relationship(back_populates="cashback_category")


class AccountCashbackRate(Base):
    """Percent cashback for one bank category on one account for one calendar month."""

    __tablename__ = "account_cashback_rates"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "year",
            "month",
            "cashback_category_id",
            name="uq_account_cashback_rate_month",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    cashback_category_id: Mapped[int] = mapped_column(
        ForeignKey("cashback_categories.id", ondelete="CASCADE"), nullable=False
    )
    percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)

    account: Mapped["Account"] = relationship()
    cashback_category: Mapped["CashbackCategory"] = relationship(back_populates="rates")
