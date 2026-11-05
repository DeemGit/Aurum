"""transaction_import_hashes for dual-leg transfer dedupe

Revision ID: a8c3e1f4b920
Revises: e4b8c2a91f70
Create Date: 2026-11-06 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c3e1f4b920"
down_revision: Union[str, None] = "e4b8c2a91f70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_import_hashes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("import_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "import_hash",
            name="uq_transaction_import_hashes_account_hash",
        ),
    )
    # Copy legacy single-column hashes so bulk dedupe can use the new table only.
    op.execute(
        """
        INSERT INTO transaction_import_hashes (transaction_id, account_id, import_hash)
        SELECT id, account_id, import_hash
        FROM transactions
        WHERE import_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("transaction_import_hashes")
