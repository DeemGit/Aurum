"""multicurrency transfer fields, refund, cashback, import_hash, occurred_at

Revision ID: e4b8c2a91f70
Revises: d1a6f4c8b729
Create Date: 2026-11-05 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b8c2a91f70"
down_revision: Union[str, None] = "d1a6f4c8b729"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cashback_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
    )
    op.create_table(
        "account_cashback_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column(
            "cashback_category_id",
            sa.Integer(),
            sa.ForeignKey("cashback_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("percent", sa.Numeric(6, 3), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "year",
            "month",
            "cashback_category_id",
            name="uq_account_cashback_rate_month",
        ),
    )

    op.add_column("transactions", sa.Column("transfer_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("transactions", sa.Column("exchange_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("fee_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "refund_of_transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("transactions", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transactions", sa.Column("import_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "transactions",
        sa.Column(
            "cashback_category_id",
            sa.Integer(),
            sa.ForeignKey("cashback_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("transactions", sa.Column("cashback_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("is_cashback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Fill occurred_at from calendar date at midnight UTC — schema completeness only.
    op.execute(
        sa.text(
            "UPDATE transactions SET occurred_at = (date::timestamp AT TIME ZONE 'UTC') "
            "WHERE occurred_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE transactions SET transfer_amount = amount "
            "WHERE type = 'transfer' AND transfer_amount IS NULL"
        )
    )
    op.alter_column("transactions", "occurred_at", nullable=False)
    op.alter_column("transactions", "fee_amount", server_default=None)
    op.alter_column("transactions", "is_cashback", server_default=None)

    op.create_index(
        "uq_transactions_account_import_hash",
        "transactions",
        ["account_id", "import_hash"],
        unique=True,
        postgresql_where=sa.text("import_hash IS NOT NULL"),
    )

    op.add_column("recurring_transactions", sa.Column("transfer_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("recurring_transactions", sa.Column("exchange_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column(
        "recurring_transactions",
        sa.Column("fee_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.alter_column("recurring_transactions", "fee_amount", server_default=None)


def downgrade() -> None:
    op.drop_column("recurring_transactions", "fee_amount")
    op.drop_column("recurring_transactions", "exchange_rate")
    op.drop_column("recurring_transactions", "transfer_amount")

    op.drop_index("uq_transactions_account_import_hash", table_name="transactions")
    op.drop_column("transactions", "is_cashback")
    op.drop_column("transactions", "cashback_amount")
    op.drop_column("transactions", "cashback_category_id")
    op.drop_column("transactions", "import_hash")
    op.drop_column("transactions", "occurred_at")
    op.drop_column("transactions", "refund_of_transaction_id")
    op.drop_column("transactions", "fee_amount")
    op.drop_column("transactions", "exchange_rate")
    op.drop_column("transactions", "transfer_amount")

    op.drop_table("account_cashback_rates")
    op.drop_table("cashback_categories")
