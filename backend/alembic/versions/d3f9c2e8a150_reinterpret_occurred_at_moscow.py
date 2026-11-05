"""Reinterpret occurred_at wall-clock as Europe/Moscow

Previously CSV/form tagged bank local times as +00:00. Values already
stored have the correct digits but the wrong zone; reinterpret them as
Moscow wall time (T-Bank / RU, no DST).

Revision ID: d3f9c2e8a150
Revises: c2e5a8b1d940
Create Date: 2026-11-06 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d3f9c2e8a150"
down_revision: Union[str, None] = "c2e5a8b1d940"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Digits on the clock were Moscow local time, wrongly stored as UTC.
    op.execute(
        """
        UPDATE transactions
        SET occurred_at = ((occurred_at AT TIME ZONE 'UTC')::timestamp AT TIME ZONE 'Europe/Moscow')
        """
    )


def downgrade() -> None:
    # Reverse: treat stored absolute as Moscow wall, re-tag as UTC.
    op.execute(
        """
        UPDATE transactions
        SET occurred_at = ((occurred_at AT TIME ZONE 'Europe/Moscow')::timestamp AT TIME ZONE 'UTC')
        """
    )
