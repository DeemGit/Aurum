"""credit card statement/payment/grace fields

Revision ID: c9e6a1b3d4f5
Revises: b8d5f0a2c3e4
Create Date: 2026-11-26 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e6a1b3d4f5"
down_revision: Union[str, None] = "b8d5f0a2c3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("statement_day", sa.Integer(), nullable=True))
    op.add_column("accounts", sa.Column("payment_day", sa.Integer(), nullable=True))
    op.add_column("accounts", sa.Column("grace_period_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "grace_period_days")
    op.drop_column("accounts", "payment_day")
    op.drop_column("accounts", "statement_day")
