"""One-off backfill: align transfer ``date`` with Europe/Moscow wall-clock of
``occurred_at``.

Merge used to set ``date`` from the UTC calendar day of ``min(occurred_at)``.
Alfa synthetic midnight ``08.11 00:00+03`` stores as ``07.11 21:00 UTC``, so
merged transfers landed on the previous day. This script sets

    date = occurred_at.astimezone(Europe/Moscow).date()

for every transfer where they disagree.

Does **not** restore a later bank timestamp (e.g. GPB 21:11) — merge deleted
the legs and kept the earlier ``occurred_at``. Only the calendar ``date`` is
fixed.

Run against a running stack:

    docker compose exec backend python -m scripts.fix_transfer_dates_from_moscow_wall

Safe to re-run — already-aligned rows are left untouched.
"""
from __future__ import annotations

import asyncio
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import TransactionType
from app.models.transaction import Transaction

MOSCOW = ZoneInfo("Europe/Moscow")


def _as_aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction).where(Transaction.type == TransactionType.TRANSFER)
        )
        updated = 0
        for row in result.scalars().all():
            wall_date = _as_aware(row.occurred_at).astimezone(MOSCOW).date()
            if row.date == wall_date:
                continue
            print(f"id={row.id}: date {row.date} -> {wall_date} (occurred_at={row.occurred_at})")
            row.date = wall_date
            updated += 1
        await session.commit()
        print(f"Transfers updated: {updated}")


if __name__ == "__main__":
    asyncio.run(main())
