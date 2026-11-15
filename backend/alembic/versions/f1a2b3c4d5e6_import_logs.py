"""import_logs + transactions.import_log_id

Revision ID: f1a2b3c4d5e6
Revises: e5a1b7c3d240
Create Date: 2026-11-15 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5a1b7c3d240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "transactions",
        sa.Column("import_log_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_import_log_id",
        "transactions",
        "import_logs",
        ["import_log_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_transactions_import_log_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "import_log_id")
    op.drop_table("import_logs")
