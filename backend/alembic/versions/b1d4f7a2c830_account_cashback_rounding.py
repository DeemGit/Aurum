"""account cashback_rounding mode

Revision ID: b1d4f7a2c830
Revises: a8c3e1f4b920
Create Date: 2026-11-06 00:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1d4f7a2c830"
down_revision: Union[str, None] = "a8c3e1f4b920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "cashback_rounding",
            sa.String(length=20),
            nullable=False,
            server_default="percent_floor",
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "cashback_rounding")
