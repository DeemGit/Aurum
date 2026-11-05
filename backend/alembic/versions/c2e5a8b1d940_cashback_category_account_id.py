"""cashback_categories.account_id — categories scoped per account

Revision ID: c2e5a8b1d940
Revises: b1d4f7a2c830
Create Date: 2026-11-06 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2e5a8b1d940"
down_revision: Union[str, None] = "b1d4f7a2c830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cashback_categories", sa.Column("account_id", sa.Integer(), nullable=True))
    # Prefer an account that already has a rate for this category.
    op.execute(
        """
        UPDATE cashback_categories AS c
        SET account_id = sub.account_id
        FROM (
            SELECT DISTINCT ON (cashback_category_id) cashback_category_id, account_id
            FROM account_cashback_rates
            ORDER BY cashback_category_id, id
        ) AS sub
        WHERE c.id = sub.cashback_category_id AND c.account_id IS NULL
        """
    )
    # Orphans with no rates: attach to the first non-cash account if any.
    op.execute(
        """
        UPDATE cashback_categories
        SET account_id = (
            SELECT id FROM accounts
            WHERE type <> 'cash'
            ORDER BY id
            LIMIT 1
        )
        WHERE account_id IS NULL
        """
    )
    # Still NULL (no accounts at all) — drop orphan categories.
    op.execute("DELETE FROM cashback_categories WHERE account_id IS NULL")
    op.alter_column("cashback_categories", "account_id", nullable=False)
    op.create_foreign_key(
        "fk_cashback_categories_account_id",
        "cashback_categories",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_cashback_categories_account_name",
        "cashback_categories",
        ["account_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_cashback_categories_account_name", "cashback_categories", type_="unique")
    op.drop_constraint("fk_cashback_categories_account_id", "cashback_categories", type_="foreignkey")
    op.drop_column("cashback_categories", "account_id")
