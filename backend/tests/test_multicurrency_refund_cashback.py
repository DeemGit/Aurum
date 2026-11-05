"""Multicurrency transfers, refunds, import_hash dedupe, cashback, matching."""
from decimal import Decimal

from httpx import AsyncClient

from tests.helpers import money, txn_payload as _txn


async def test_account_currency_immutable(client: AsyncClient):
    created = await client.post("/accounts", json={"name": "EUR Card", "type": "debit_card", "currency": "EUR"})
    assert created.status_code == 201
    assert created.json()["currency"] == "EUR"
    account_id = created.json()["id"]

    patched = await client.patch(f"/accounts/{account_id}", json={"currency": "USD"})
    # currency is not on AccountUpdate — ignored / rejected at schema level
    assert patched.status_code in (200, 422)
    if patched.status_code == 200:
        assert patched.json()["currency"] == "EUR"


async def test_cross_currency_transfer_balance(client: AsyncClient):
    usd = (await client.post("/accounts", json={"name": "USD", "type": "checking", "currency": "USD"})).json()
    eur = (await client.post("/accounts", json={"name": "EUR", "type": "checking", "currency": "EUR"})).json()

    resp = await client.post(
        "/transactions",
        json={
            "account_id": usd["id"],
            "transfer_account_id": eur["id"],
            "type": "transfer",
            "amount": "100.00",
            "transfer_amount": "90.00",
            "exchange_rate": "0.9",
            "fee_amount": "1.00",
            "description": "usd to eur",
            "date": "2026-03-01",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert money(body["transfer_amount"]) == Decimal("90.00")
    assert body["occurred_at"].startswith("2026-03-01")

    accounts = {a["id"]: a for a in (await client.get("/accounts")).json()}
    assert money(accounts[usd["id"]]["balance"]) == Decimal("-101.00")
    assert money(accounts[eur["id"]]["balance"]) == Decimal("90.00")


async def test_refund_reduces_purchase_month_spend(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    expense = await client.post(
        "/transactions",
        json=_txn(account_id, category_id=groceries, amount="100.00", date="2026-01-10", description="order"),
    )
    assert expense.status_code == 201
    expense_id = expense.json()["id"]

    refund = await client.post(
        "/transactions",
        json={
            "account_id": account_id,
            "type": "refund",
            "amount": "30.00",
            "description": "partial return",
            "date": "2026-02-05",
            "refund_of_transaction_id": expense_id,
            "cashback_amount": "-1.50",
        },
    )
    assert refund.status_code == 201
    assert money(refund.json()["cashback_amount"]) == Decimal("-1.50")

    jan = (await client.get("/dashboard/summary", params={"year": 2026, "month": 1})).json()
    assert money(jan["spent"]) == Decimal("70.00")

    feb_cash = (await client.get("/cash-flow", params={"start_date": "2026-02-01", "end_date": "2026-02-28"})).json()
    feb_point = next(p for p in feb_cash["points"] if p["month"] == 2)
    assert money(feb_point["refunds_received"]) == Decimal("30.00")

    accounts = {a["id"]: a for a in (await client.get("/accounts")).json()}
    # -100 expense +30 refund
    assert money(accounts[account_id]["balance"]) == Decimal("-70.00")


async def test_bulk_skips_duplicate_import_hash(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    digest = "a" * 64
    first = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                _txn(
                    account_id,
                    category_id=groceries,
                    description="csv row",
                    date="2026-04-01",
                    import_hash=digest,
                )
            ]
        },
    )
    assert first.status_code == 201
    assert first.json()["created"] == 1

    second = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                _txn(
                    account_id,
                    category_id=groceries,
                    description="csv row again",
                    date="2026-04-01",
                    import_hash=digest,
                )
            ]
        },
    )
    assert second.status_code == 201
    assert second.json()["created"] == 0
    assert second.json()["skipped_duplicates"] == 1


async def test_merge_transfer_clears_cashback(client: AsyncClient, categories):
    a = (await client.post("/accounts", json={"name": "A", "type": "checking", "currency": "USD"})).json()
    b = (await client.post("/accounts", json={"name": "B", "type": "checking", "currency": "USD"})).json()
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]

    cb = await client.post("/cashback-categories", json={"name": "Travel", "color": "#112233"})
    assert cb.status_code == 201
    cb_id = cb.json()["id"]

    expense = await client.post(
        "/transactions",
        json=_txn(
            a["id"],
            category_id=groceries,
            amount="50.00",
            date="2026-05-01",
            description="move out",
            cashback_category_id=cb_id,
        ),
    )
    income = await client.post(
        "/transactions",
        json=_txn(
            b["id"],
            type="income",
            category_id=salary,
            amount="50.00",
            date="2026-05-01",
            description="move in",
        ),
    )
    assert expense.status_code == 201
    assert income.status_code == 201

    matches = await client.get(f"/transactions/{expense.json()['id']}/transfer-matches")
    assert matches.status_code == 200
    assert len(matches.json()["candidates"]) >= 1

    merged = await client.post(
        "/transactions/merge-transfer",
        json={
            "source_transaction_id": expense.json()["id"],
            "destination_transaction_id": income.json()["id"],
        },
    )
    assert merged.status_code == 201
    body = merged.json()
    assert body["type"] == "transfer"
    assert body["cashback_category_id"] is None
    assert body["cashback_amount"] is None

    listed = await client.get("/transactions", params={"year": 2026, "month": 5})
    assert listed.json()["total"] == 1


async def test_cashback_rates_rejected_for_cash_account(client: AsyncClient):
    cash = (await client.post("/accounts", json={"name": "Cash", "type": "cash", "currency": "USD"})).json()
    cat = (await client.post("/cashback-categories", json={"name": "Food"})).json()
    resp = await client.put(
        f"/accounts/{cash['id']}/cashback-rates",
        json={"year": 2026, "month": 6, "rates": [{"cashback_category_id": cat["id"], "percent": "5"}]},
    )
    assert resp.status_code == 400


async def test_filter_transactions_by_account(client: AsyncClient, account_id, categories):
    other = (await client.post("/accounts", json={"name": "Other", "type": "checking", "currency": "USD"})).json()
    groceries = categories["Groceries"]["id"]
    await client.post("/transactions", json=_txn(account_id, category_id=groceries, description="mine"))
    await client.post("/transactions", json=_txn(other["id"], category_id=groceries, description="theirs"))

    filtered = await client.get("/transactions", params={"account_id": account_id})
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["description"] == "Mine"
