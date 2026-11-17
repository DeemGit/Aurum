"""Todo checklist: CRUD, soft-delete, step/complete, dashboard planned_*."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from tests.helpers import money


def _future_in_month(offset_days: int = 1) -> str:
    """A date >= today that still falls in the current calendar month."""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = date(today.year, today.month, last_day)
    candidate = today + timedelta(days=offset_days)
    if candidate > month_end:
        candidate = month_end
    if candidate < today:
        candidate = today
    return candidate.isoformat()


def _past(days: int = 7) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _todo_payload(**overrides) -> dict:
    body = {
        "title": "Pay rent",
        "due_date": _future_in_month(1),
        "amount": "1500.00",
        "kind": "expense",
        "step_count": 4,
        "count_in_dashboard": True,
    }
    body.update(overrides)
    return body


async def test_create_list_update_soft_delete(client: AsyncClient):
    created = (await client.post("/todos", json=_todo_payload())).json()
    assert created["title"] == "Pay rent"
    assert created["progress_percent"] == 0
    assert created["deleted_at"] is None
    assert created["completed_at"] is None

    listed = (await client.get("/todos")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    updated = (
        await client.patch(f"/todos/{created['id']}", json={"title": "Pay utilities", "amount": None})
    ).json()
    assert updated["title"] == "Pay utilities"
    assert updated["amount"] is None

    delete_resp = await client.delete(f"/todos/{created['id']}")
    assert delete_resp.status_code == 204

    assert (await client.get("/todos")).json() == []
    with_deleted = (await client.get("/todos", params={"include_deleted": True})).json()
    assert len(with_deleted) == 1
    assert with_deleted[0]["deleted_at"] is not None

    # Second delete of a soft-deleted row purges it permanently.
    purge_resp = await client.delete(f"/todos/{created['id']}")
    assert purge_resp.status_code == 204
    assert (await client.get("/todos", params={"include_deleted": True})).json() == []


async def test_step_and_complete(client: AsyncClient):
    created = (await client.post("/todos", json=_todo_payload(step_count=4))).json()

    stepped = (await client.post(f"/todos/{created['id']}/step")).json()
    assert stepped["progress_percent"] == 25
    assert stepped["completed_at"] is None

    await client.post(f"/todos/{created['id']}/step")
    await client.post(f"/todos/{created['id']}/step")
    done = (await client.post(f"/todos/{created['id']}/step")).json()
    assert done["progress_percent"] == 100
    assert done["completed_at"] is not None

    other = (await client.post("/todos", json=_todo_payload(title="Bonus", kind="income", step_count=None))).json()
    completed = (await client.post(f"/todos/{other['id']}/complete")).json()
    assert completed["progress_percent"] == 100
    assert completed["completed_at"] is not None

    no_steps = await client.post(f"/todos/{other['id']}/step")
    # Soft-active but already complete — step still runs if step_count missing → 400
    assert no_steps.status_code == 400


async def test_dashboard_planned_only_future_incomplete_with_flag(client: AsyncClient):
    today = date.today()
    # In-month future expense counted.
    await client.post(
        "/todos",
        json=_todo_payload(
            title="Future rent",
            due_date=_future_in_month(0),
            amount="1000.00",
            kind="expense",
        ),
    )
    # Future income counted.
    await client.post(
        "/todos",
        json=_todo_payload(
            title="Future bonus",
            due_date=_future_in_month(0),
            amount="200.00",
            kind="income",
            step_count=None,
        ),
    )
    # Flag off — not counted.
    await client.post(
        "/todos",
        json=_todo_payload(
            title="Ignored",
            due_date=_future_in_month(0),
            amount="999.00",
            kind="expense",
            count_in_dashboard=False,
        ),
    )
    # Past due — not counted.
    await client.post(
        "/todos",
        json=_todo_payload(
            title="Overdue",
            due_date=_past(2),
            amount="50.00",
            kind="expense",
        ),
    )
    # Completed — not counted.
    completed = (
        await client.post(
            "/todos",
            json=_todo_payload(
                title="Done",
                due_date=_future_in_month(0),
                amount="75.00",
                kind="expense",
            ),
        )
    ).json()
    await client.post(f"/todos/{completed['id']}/complete")

    # No amount — not counted.
    await client.post(
        "/todos",
        json=_todo_payload(
            title="Promo",
            due_date=_future_in_month(0),
            amount=None,
            kind="expense",
            step_count=None,
        ),
    )

    resp = await client.get(
        "/dashboard/summary",
        params={"year": today.year, "month": today.month},
    )
    body = resp.json()
    assert money(body["planned_expenses"]) == Decimal("1000.00")
    assert money(body["planned_income"]) == Decimal("200.00")
