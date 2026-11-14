"""Dashboard exclusion by tag: settings list, summary aggregates, list filter."""
from decimal import Decimal

from httpx import AsyncClient

from tests.helpers import money, txn_payload as _txn


async def test_excluded_tag_expense_and_income_leave_summary(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]
    tag_id = (await client.post("/tags", json={"name": "Hidden"})).json()["id"]

    await client.post(
        "/transactions",
        json=_txn(
            account_id,
            type="income",
            amount="500.00",
            category_id=salary,
            date="2026-08-01",
            tag_ids=[tag_id],
        ),
    )
    await client.post(
        "/transactions",
        json=_txn(account_id, amount="80.00", category_id=groceries, date="2026-08-02", tag_ids=[tag_id]),
    )
    await client.post(
        "/transactions",
        json=_txn(account_id, amount="20.00", category_id=groceries, date="2026-08-03"),
    )
    await client.post(
        "/transactions",
        json=_txn(account_id, type="income", amount="100.00", category_id=salary, date="2026-08-04"),
    )

    before = (await client.get("/dashboard/summary", params={"year": 2026, "month": 8})).json()
    assert money(before["real_income"]) == Decimal("600.00")
    assert money(before["spent"]) == Decimal("100.00")

    patch = await client.patch("/settings", json={"dashboard_excluded_tag_ids": [tag_id]})
    assert patch.status_code == 200
    assert [tag["id"] for tag in patch.json()["dashboard_excluded_tags"]] == [tag_id]

    after = (await client.get("/dashboard/summary", params={"year": 2026, "month": 8})).json()
    assert money(after["real_income"]) == Decimal("100.00")
    assert money(after["spent"]) == Decimal("20.00")
    breakdown = {row["name"]: row for row in after["spending_by_category"]}
    assert money(breakdown["Groceries"]["amount"]) == Decimal("20.00")


async def test_excluded_tag_on_refund_does_not_reduce_spent(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    tag_id = (await client.post("/tags", json={"name": "SkipRefund"})).json()["id"]
    await client.patch("/settings", json={"dashboard_excluded_tag_ids": [tag_id]})

    expense = await client.post(
        "/transactions",
        json=_txn(account_id, amount="100.00", category_id=groceries, date="2026-08-10"),
    )
    expense_id = expense.json()["id"]
    refund = await client.post(
        "/transactions",
        json={
            "account_id": account_id,
            "type": "refund",
            "amount": "40.00",
            "description": "return",
            "date": "2026-08-15",
            "refund_of_transaction_id": expense_id,
            "tag_ids": [tag_id],
        },
    )
    assert refund.status_code == 201

    # Expense has no excluded tag so it stays in spent; tagged refund is ignored.
    body = (await client.get("/dashboard/summary", params={"year": 2026, "month": 8})).json()
    assert money(body["spent"]) == Decimal("100.00")


async def test_list_exclude_tag_ids_omits_tagged_transactions(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    tag_id = (await client.post("/tags", json={"name": "Out"})).json()["id"]
    kept = await client.post(
        "/transactions",
        json=_txn(account_id, amount="10.00", category_id=groceries, date="2026-08-01", description="kept"),
    )
    hidden = await client.post(
        "/transactions",
        json=_txn(
            account_id,
            amount="10.00",
            category_id=groceries,
            date="2026-08-02",
            description="hidden",
            tag_ids=[tag_id],
        ),
    )
    assert kept.status_code == 201 and hidden.status_code == 201

    listed = await client.get(
        "/transactions",
        params={"year": 2026, "month": 8, "exclude_tag_ids": [tag_id]},
    )
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert kept.json()["id"] in ids
    assert hidden.json()["id"] not in ids
