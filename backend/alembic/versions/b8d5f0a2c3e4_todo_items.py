"""todo_items for planned expenses/income checklist

Revision ID: b8d5f0a2c3e4
Revises: a7c4e9f1b2d3
Create Date: 2026-11-17 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d5f0a2c3e4"
down_revision: Union[str, None] = "a7c4e9f1b2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "todo_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step_count", sa.Integer(), nullable=True),
        sa.Column("count_in_dashboard", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_todo_items_due_date", "todo_items", ["due_date"])


def downgrade() -> None:
    op.drop_index("ix_todo_items_due_date", table_name="todo_items")
    op.drop_table("todo_items")
