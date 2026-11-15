"""Dashboard summary: the arithmetic and month-scoping behind the Overview
page's four stat cards and the spending-by-category donut.
"""
from decimal import Decimal

from httpx import AsyncClient

from tests.helpers import money, txn_payload as _txn


async def test_summary_is_zero_for_a_month_with_no_transactions(client: AsyncClient):
    resp = await client.get("/dashboard/summary", params={"year": 2030, "month": 1})
    body = resp.json()
    assert money(body["real_income"]) == 0
    assert money(body["spent"]) == 0
    assert money(body["net"]) == 0
    assert body["spending_by_category"] == []


async def test_income_expense_and_net_only_count_the_selected_month(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]

    # In scope: August 2026.
    await client.post(
        "/transactions", json=_txn(account_id, type="income", amount="3000.00", category_id=salary, date="2026-08-01")
    )
    await client.post(
        "/transactions", json=_txn(account_id, type="expense", amount="1200.00", category_id=groceries, date="2026-08-20")
    )
    # Out of scope: same categories, different month — must not leak in.
    await client.post(
        "/transactions", json=_txn(account_id, type="income", amount="9999.00", category_id=salary, date="2026-07-31")
    )
    await client.post(
        "/transactions", json=_txn(account_id, type="expense", amount="9999.00", category_id=groceries, date="2026-09-01")
    )

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    body = resp.json()
    assert money(body["real_income"]) == Decimal("3000.00")
    assert money(body["spent"]) == Decimal("1200.00")
    assert money(body["net"]) == Decimal("1800.00")


async def test_transfers_are_excluded_from_income_and_spent(client: AsyncClient, account_id, categories):
    other = await client.post("/accounts", json={"name": "Savings", "type": "savings", "currency": "USD"})
    other_id = other.json()["id"]
    await client.post(
        "/transactions",
        json=_txn(account_id, type="transfer", amount="500.00", transfer_account_id=other_id, date="2026-08-05"),
    )
    await client.post(
        "/transactions",
        json=_txn(account_id, type="income", amount="100.00", category_id=categories["Salary"]["id"], date="2026-08-05"),
    )

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    body = resp.json()
    assert money(body["real_income"]) == Decimal("100.00")
    assert money(body["spent"]) == 0
    assert money(body["transferred_out"]) == Decimal("500.00")


async def test_spending_by_category_amounts_and_percent(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    dining = categories["Dining Out"]["id"]
    await client.post(
        "/transactions", json=_txn(account_id, amount="75.00", category_id=groceries, date="2026-08-01")
    )
    await client.post(
        "/transactions", json=_txn(account_id, amount="25.00", category_id=dining, date="2026-08-02")
    )

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    breakdown = {row["name"]: row for row in resp.json()["spending_by_category"]}

    assert money(breakdown["Groceries"]["amount"]) == Decimal("75.00")
    assert breakdown["Groceries"]["percent"] == 75.0
    assert money(breakdown["Dining Out"]["amount"]) == Decimal("25.00")
    assert breakdown["Dining Out"]["percent"] == 25.0


async def test_subcategory_spending_rolls_up_into_its_parent(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    alcohol = await client.post(
        "/categories", json={"name": "Alcohol", "kind": "expense", "color": "#e34948", "parent_id": groceries}
    )
    alcohol_id = alcohol.json()["id"]

    await client.post("/transactions", json=_txn(account_id, amount="60.00", category_id=groceries, date="2026-08-01"))
    await client.post("/transactions", json=_txn(account_id, amount="15.00", category_id=alcohol_id, date="2026-08-02"))

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    breakdown = {row["name"]: row for row in resp.json()["spending_by_category"]}

    assert "Alcohol" not in breakdown
    assert money(breakdown["Groceries"]["amount"]) == Decimal("75.00")


async def test_more_than_eight_expense_categories_roll_up_into_other(client: AsyncClient, account_id, categories):
    expense_categories = [c for c in categories.values() if c["kind"] == "expense"]
    # The default seed only ships 8 expense categories (see app/db/seed.py) —
    # add a 9th ourselves rather than depending on that number ever changing.
    extra = await client.post(
        "/categories", json={"name": "Extra Expense", "kind": "expense", "color": "#123456", "sort_order": 99}
    )
    expense_categories.append(extra.json())
    assert len(expense_categories) == 9

    # Distinct amounts so we can tell which ones survive as their own slice.
    for index, category in enumerate(expense_categories[:9]):
        await client.post(
            "/transactions",
            json=_txn(account_id, amount=f"{(9 - index) * 10}.00", category_id=category["id"], date="2026-08-01"),
        )

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    breakdown = resp.json()["spending_by_category"]

    assert len(breakdown) == 9  # 8 explicit categories + one "Other" rollup
    other = [row for row in breakdown if row["category_id"] is None]
    assert len(other) == 1
    assert other[0]["name"] == "Other"
    # The 9th (smallest, index 8) category's 10.00 must be folded into Other,
    # not silently dropped from the total.
    assert money(other[0]["amount"]) == Decimal("10.00")


async def test_split_transaction_rolls_up_into_one_slice_with_a_children_breakdown(
    client: AsyncClient, account_id, categories
):
    """A hypermarket receipt split between Groceries and one of its own
    subcategories (Sweets) must show up as a single Groceries slice on the
    donut with the full 100.00 total — a split's categories always share one
    parent (see routes/transactions.py's _build_splits), so it never
    fragments into separate top-level slices — but the slice must expose a
    children breakdown so the Groceries/Sweets split is still visible."""
    groceries = categories["Groceries"]["id"]
    sweets_resp = await client.post(
        "/categories", json={"name": "Sweets", "kind": "expense", "color": "#7a869a", "parent_id": groceries}
    )
    sweets = sweets_resp.json()["id"]
    await client.post(
        "/transactions",
        json=_txn(
            account_id,
            amount="100.00",
            category_id=None,
            date="2026-08-01",
            splits=[
                {"category_id": groceries, "amount": "70.00"},
                {"category_id": sweets, "amount": "30.00"},
            ],
        ),
    )

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    body = resp.json()
    breakdown = {row["name"]: row for row in body["spending_by_category"]}

    assert money(body["spent"]) == Decimal("100.00")
    assert "Sweets" not in breakdown
    assert money(breakdown["Groceries"]["amount"]) == Decimal("100.00")

    children = {child["name"]: child for child in breakdown["Groceries"]["children"]}
    # The 70.00 line was filed directly on Groceries itself (no
    # subcategory), so it shows up as a child entry with Groceries' own id
    # and name too — same as any genuine subcategory would.
    assert money(children["Groceries"]["amount"]) == Decimal("70.00")
    assert money(children["Sweets"]["amount"]) == Decimal("30.00")


async def test_a_single_category_slice_has_no_children_breakdown(client: AsyncClient, account_id, categories):
    """A category funded by exactly one source (the common case — no
    splitting, no subcategories involved) shouldn't show a redundant
    one-item breakdown of itself."""
    groceries = categories["Groceries"]["id"]
    await client.post("/transactions", json=_txn(account_id, amount="50.00", category_id=groceries, date="2026-08-01"))

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    breakdown = {row["name"]: row for row in resp.json()["spending_by_category"]}

    assert breakdown["Groceries"]["children"] == []


async def test_uncategorized_expense_lands_in_other_slice(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    await client.post(
        "/transactions", json=_txn(account_id, amount="40.00", category_id=groceries, date="2026-08-01")
    )
    uncategorized = await client.post(
        "/transactions",
        json=_txn(account_id, amount="15.00", category_id=None, date="2026-08-02", description="no cat"),
    )
    assert uncategorized.status_code == 201

    resp = await client.get("/dashboard/summary", params={"year": 2026, "month": 8})
    body = resp.json()
    assert money(body["spent"]) == Decimal("55.00")
    other = next(row for row in body["spending_by_category"] if row["category_id"] is None)
    assert other["name"] == "Other"
    assert money(other["amount"]) == Decimal("15.00")


async def test_list_dashboard_other_excludes_top_categories_includes_uncategorized(
    client: AsyncClient, account_id, categories
):
    groceries = categories["Groceries"]["id"]
    dining = categories["Dining Out"]["id"]
    in_top = await client.post(
        "/transactions", json=_txn(account_id, amount="20.00", category_id=groceries, date="2026-08-01")
    )
    outside = await client.post(
        "/transactions", json=_txn(account_id, amount="30.00", category_id=dining, date="2026-08-02")
    )
    bare = await client.post(
        "/transactions",
        json=_txn(account_id, amount="10.00", category_id=None, date="2026-08-03", description="bare"),
    )
    assert in_top.status_code == 201 and outside.status_code == 201 and bare.status_code == 201

    listed = await client.get(
        "/transactions",
        params={
            "year": 2026,
            "month": 8,
            "type": "expense",
            "dashboard_other": True,
            "exclude_category_ids": [groceries],
        },
    )
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert in_top.json()["id"] not in ids
    assert outside.json()["id"] in ids
    assert bare.json()["id"] in ids
