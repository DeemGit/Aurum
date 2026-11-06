"""Calendar date must not shift when occurred_at is converted to UTC."""
from datetime import date, datetime, timedelta, timezone

from app.schemas.transaction import normalize_occurred_at


def test_keeps_client_date_when_utc_crosses_midnight():
    # 01.11.2026 02:23 MSK → 31.10.2026 23:23 UTC — date must stay 1 Nov.
    msk = timezone(timedelta(hours=3))
    occurred = datetime(2026, 11, 1, 2, 23, 0, tzinfo=msk)
    date_value, stored = normalize_occurred_at(date=date(2026, 11, 1), occurred_at=occurred)
    assert date_value == date(2026, 11, 1)
    assert stored == datetime(2026, 10, 31, 23, 23, 0, tzinfo=timezone.utc)


def test_wall_clock_date_when_only_occurred_at_sent():
    msk = timezone(timedelta(hours=3))
    occurred = datetime(2026, 11, 1, 2, 23, 0, tzinfo=msk)
    date_value, stored = normalize_occurred_at(date=None, occurred_at=occurred)
    assert date_value == date(2026, 11, 1)
    assert stored.tzinfo == timezone.utc
    assert stored == datetime(2026, 10, 31, 23, 23, 0, tzinfo=timezone.utc)


def test_date_only_still_midnight_utc():
    date_value, stored = normalize_occurred_at(date=date(2026, 11, 1), occurred_at=None)
    assert date_value == date(2026, 11, 1)
    assert stored == datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
