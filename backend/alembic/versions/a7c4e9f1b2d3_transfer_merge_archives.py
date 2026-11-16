"""transfer_merge_archives for undoable merge-transfer

Revision ID: a7c4e9f1b2d3
Revises: f1a2b3c4d5e6
Create Date: 2026-11-16 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7c4e9f1b2d3"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transfer_merge_archives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transfer_id", sa.Integer(), nullable=False),
        sa.Column("expense_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("income_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transactions.id"],
            name="fk_transfer_merge_archives_transfer_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_id", name="uq_transfer_merge_archives_transfer_id"),
    )


def downgrade() -> None:
    op.drop_table("transfer_merge_archives")
