"""dashboard_excluded_tags for dashboard income/spend filters

Revision ID: e5a1b7c3d240
Revises: d3f9c2e8a150
Create Date: 2026-11-14 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5a1b7c3d240"
down_revision: Union[str, None] = "d3f9c2e8a150"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboard_excluded_tags",
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tag_id"),
    )


def downgrade() -> None:
    op.drop_table("dashboard_excluded_tags")
