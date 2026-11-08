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


async def test_refund_may_use_different_account(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    other = (
        await client.post("/accounts", json={"name": "Other card", "type": "debit_card", "currency": "USD"})
    ).json()

    expense = await client.post(
        "/transactions",
        json=_txn(account_id, category_id=groceries, amount="40.00", date="2026-06-01", description="buy"),
    )
    assert expense.status_code == 201

    refund = await client.post(
        "/transactions",
        json={
            "account_id": other["id"],
            "type": "refund",
            "amount": "40.00",
            "description": "return to other card",
            "date": "2026-06-10",
            "refund_of_transaction_id": expense.json()["id"],
        },
    )
    assert refund.status_code == 201

    accounts = {a["id"]: a for a in (await client.get("/accounts")).json()}
    assert money(accounts[account_id]["balance"]) == Decimal("-40.00")
    assert money(accounts[other["id"]]["balance"]) == Decimal("40.00")


async def test_bulk_backfills_import_hash_on_existing_row(client: AsyncClient, account_id, categories):
    groceries = categories["Groceries"]["id"]
    created = await client.post(
        "/transactions",
        json=_txn(account_id, category_id=groceries, amount="42.00", date="2026-07-01", description="legacy row"),
    )
    assert created.status_code == 201
    tx_id = created.json()["id"]
    assert created.json()["import_hash"] is None

    digest = "b" * 64
    bulk = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                {
                    "account_id": account_id,
                    "type": "expense",
                    "amount": "42.00",
                    "description": "Legacy Row",
                    "date": "2026-07-01",
                    "import_hash": digest,
                }
            ]
        },
    )
    assert bulk.status_code == 201
    body = bulk.json()
    assert body["created"] == 0
    assert body["hashes_backfilled"] == 1

    listed = await client.get("/transactions", params={"account_id": account_id, "page_size": 50})
    row = next(item for item in listed.json()["items"] if item["id"] == tx_id)
    assert row["import_hash"] == digest

    again = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                {
                    "account_id": account_id,
                    "type": "expense",
                    "amount": "42.00",
                    "description": "legacy row",
                    "date": "2026-07-01",
                    "import_hash": digest,
                }
            ]
        },
    )
    assert again.status_code == 201
    assert again.json()["created"] == 0
    assert again.json()["skipped_duplicates"] == 1
    assert again.json()["hashes_backfilled"] == 0


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

    cb = await client.post(
        "/cashback-categories", json={"account_id": a["id"], "name": "Travel", "color": "#112233"}
    )
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
    assert body["transfer_account"] is not None
    assert body["transfer_account"]["id"] == b["id"]
    assert body["account"]["id"] == a["id"]

    listed = await client.get("/transactions", params={"year": 2026, "month": 5})
    assert listed.json()["total"] == 1


async def test_merge_transfer_keeps_both_import_hashes(client: AsyncClient, categories):
    """Merge of two imported legs must succeed and block re-import of either hash."""
    a = (await client.post("/accounts", json={"name": "Src", "type": "checking", "currency": "USD"})).json()
    b = (await client.post("/accounts", json={"name": "Dst", "type": "checking", "currency": "USD"})).json()
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]
    hash_a = "1" * 64
    hash_b = "2" * 64

    expense = await client.post(
        "/transactions",
        json=_txn(
            a["id"],
            category_id=groceries,
            amount="28.00",
            date="2026-06-01",
            description="bank out",
            import_hash=hash_a,
        ),
    )
    income = await client.post(
        "/transactions",
        json=_txn(
            b["id"],
            type="income",
            category_id=salary,
            amount="28.00",
            date="2026-06-01",
            description="bank in",
            import_hash=hash_b,
        ),
    )
    assert expense.status_code == 201, expense.text
    assert income.status_code == 201, income.text

    merged = await client.post(
        "/transactions/merge-transfer",
        json={
            "source_transaction_id": expense.json()["id"],
            "destination_transaction_id": income.json()["id"],
        },
    )
    assert merged.status_code == 201, merged.text
    body = merged.json()
    assert body["type"] == "transfer"
    assert body["import_hash"] == hash_a
    assert body["transfer_account"]["id"] == b["id"]
    digests = {(row["account_id"], row["import_hash"]) for row in body["import_hashes"]}
    assert digests == {(a["id"], hash_a), (b["id"], hash_b)}

    reimport = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                _txn(
                    a["id"],
                    category_id=groceries,
                    amount="28.00",
                    date="2026-06-01",
                    description="bank out again",
                    import_hash=hash_a,
                ),
                _txn(
                    b["id"],
                    type="income",
                    category_id=salary,
                    amount="28.00",
                    date="2026-06-01",
                    description="bank in again",
                    import_hash=hash_b,
                ),
            ]
        },
    )
    assert reimport.status_code == 201, reimport.text
    assert reimport.json()["created"] == 0
    assert reimport.json()["skipped_duplicates"] == 2


async def test_attach_import_hash_to_transfer(client: AsyncClient, categories):
    a = (await client.post("/accounts", json={"name": "SrcAttach", "type": "checking", "currency": "USD"})).json()
    b = (await client.post("/accounts", json={"name": "DstAttach", "type": "checking", "currency": "USD"})).json()
    transfer = await client.post(
        "/transactions",
        json={
            "account_id": a["id"],
            "transfer_account_id": b["id"],
            "type": "transfer",
            "amount": "75.00",
            "description": "manual transfer",
            "date": "2026-08-01",
        },
    )
    assert transfer.status_code == 201, transfer.text
    tx_id = transfer.json()["id"]
    digest_src = "c" * 64
    digest_dst = "d" * 64

    attached = await client.post(
        f"/transactions/{tx_id}/import-hashes",
        json={"account_id": a["id"], "import_hash": digest_src},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["import_hash"] == digest_src
    assert any(h["import_hash"] == digest_src for h in attached.json()["import_hashes"])

    attached_dst = await client.post(
        f"/transactions/{tx_id}/import-hashes",
        json={"account_id": b["id"], "import_hash": digest_dst},
    )
    assert attached_dst.status_code == 200, attached_dst.text
    digests = {h["import_hash"] for h in attached_dst.json()["import_hashes"]}
    assert digests == {digest_src, digest_dst}

    # Idempotent re-attach.
    again = await client.post(
        f"/transactions/{tx_id}/import-hashes",
        json={"account_id": a["id"], "import_hash": digest_src},
    )
    assert again.status_code == 200

    # Wrong account for this transfer.
    bad_account = await client.post(
        "/accounts", json={"name": "OtherAttach", "type": "checking", "currency": "USD"}
    )
    wrong = await client.post(
        f"/transactions/{tx_id}/import-hashes",
        json={"account_id": bad_account.json()["id"], "import_hash": "e" * 64},
    )
    assert wrong.status_code == 400

    # Same digest already owned by another transaction on the account.
    other = await client.post(
        "/transactions",
        json=_txn(
            a["id"],
            category_id=categories["Groceries"]["id"],
            amount="1.00",
            date="2026-08-02",
            description="other row",
            import_hash="f" * 64,
        ),
    )
    assert other.status_code == 201
    conflict = await client.post(
        f"/transactions/{tx_id}/import-hashes",
        json={"account_id": a["id"], "import_hash": "f" * 64},
    )
    assert conflict.status_code == 409


async def test_import_link_candidates_and_bulk_dest_soft_match(client: AsyncClient, categories):
    a = (await client.post("/accounts", json={"name": "SrcCand", "type": "checking", "currency": "USD"})).json()
    b = (await client.post("/accounts", json={"name": "DstCand", "type": "checking", "currency": "USD"})).json()
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]

    expense = await client.post(
        "/transactions",
        json=_txn(
            a["id"],
            category_id=groceries,
            amount="33.00",
            date="2026-09-10",
            description="same desc both sides",
        ),
    )
    income = await client.post(
        "/transactions",
        json=_txn(
            b["id"],
            type="income",
            category_id=salary,
            amount="33.00",
            date="2026-09-10",
            description="same desc both sides",
        ),
    )
    merged = await client.post(
        "/transactions/merge-transfer",
        json={
            "source_transaction_id": expense.json()["id"],
            "destination_transaction_id": income.json()["id"],
        },
    )
    assert merged.status_code == 201, merged.text
    transfer_id = merged.json()["id"]

    candidates = await client.get(
        "/transactions/import-link-candidates",
        params={"account_id": b["id"], "amount": "33.00", "date": "2026-09-10"},
    )
    assert candidates.status_code == 200, candidates.text
    ids = [row["id"] for row in candidates.json()]
    assert transfer_id in ids
    assert candidates.json()[0]["type"] == "transfer"

    digest = "9" * 64
    bulk = await client.post(
        "/transactions/bulk",
        json={
            "items": [
                _txn(
                    b["id"],
                    type="income",
                    category_id=salary,
                    amount="33.00",
                    date="2026-09-10",
                    description="Same Desc Both Sides",
                    import_hash=digest,
                )
            ]
        },
    )
    assert bulk.status_code == 201, bulk.text
    assert bulk.json()["created"] == 0
    assert bulk.json()["hashes_backfilled"] == 1

    refreshed = await client.get(f"/transactions", params={"account_id": b["id"], "page_size": 50})
    transfer_row = next(item for item in refreshed.json()["items"] if item["id"] == transfer_id)
    assert any(h["import_hash"] == digest and h["account_id"] == b["id"] for h in transfer_row["import_hashes"])


async def test_cashback_rates_rejected_for_cash_account(client: AsyncClient):
    cash = (await client.post("/accounts", json={"name": "Cash", "type": "cash", "currency": "USD"})).json()
    card = (await client.post("/accounts", json={"name": "Card", "type": "debit_card", "currency": "USD"})).json()
    missing_account = await client.post("/cashback-categories", json={"name": "Food"})
    assert missing_account.status_code == 422
    cat = (await client.post("/cashback-categories", json={"account_id": card["id"], "name": "Food"})).json()
    resp = await client.put(
        f"/accounts/{cash['id']}/cashback-rates",
        json={"year": 2026, "month": 6, "rates": [{"cashback_category_id": cat["id"], "percent": "5"}]},
    )
    assert resp.status_code == 400


async def test_cashback_category_scoped_to_account(client: AsyncClient, categories):
    a = (await client.post("/accounts", json={"name": "A", "type": "debit_card", "currency": "USD"})).json()
    b = (await client.post("/accounts", json={"name": "B", "type": "debit_card", "currency": "USD"})).json()
    cat_a = (
        await client.post("/cashback-categories", json={"account_id": a["id"], "name": "Travel"})
    ).json()
    listed = await client.get("/cashback-categories", params={"account_id": a["id"]})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["account_id"] == a["id"]

    other = await client.get("/cashback-categories", params={"account_id": b["id"]})
    assert other.json() == []

    groceries = categories["Groceries"]["id"]
    wrong = await client.post(
        "/transactions",
        json=_txn(
            b["id"],
            category_id=groceries,
            amount="10.00",
            date="2026-07-01",
            description="wrong account cat",
            cashback_category_id=cat_a["id"],
        ),
    )
    assert wrong.status_code == 400


async def test_expense_cashback_auto_and_override(client: AsyncClient, categories):
    from decimal import Decimal

    from app.models.enums import CashbackRounding
    from app.services.cashback_service import compute_cashback_amount

    assert compute_cashback_amount(Decimal("950"), Decimal("5"), CashbackRounding.PERCENT_FLOOR) == Decimal("47")
    assert compute_cashback_amount(Decimal("950"), Decimal("6"), CashbackRounding.BASE_100) == Decimal("54")

    account = (
        await client.post("/accounts", json={"name": "Card", "type": "debit_card", "currency": "RUB"})
    ).json()
    assert account["cashback_rounding"] == "percent_floor"
    patched = await client.patch(f"/accounts/{account['id']}", json={"cashback_rounding": "percent_floor"})
    assert patched.status_code == 200

    cat = (
        await client.post("/cashback-categories", json={"account_id": account["id"], "name": "Travel"})
    ).json()
    rates = await client.put(
        f"/accounts/{account['id']}/cashback-rates",
        json={"year": 2026, "month": 7, "rates": [{"cashback_category_id": cat["id"], "percent": "5"}]},
    )
    assert rates.status_code == 200

    groceries = categories["Groceries"]["id"]
    auto = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="950.00",
            date="2026-07-10",
            description="auto cb",
            cashback_category_id=cat["id"],
        ),
    )
    assert auto.status_code == 201, auto.text
    assert money(auto.json()["cashback_amount"]) == Decimal("47")

    override = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="950.00",
            date="2026-07-11",
            description="manual cb",
            cashback_category_id=cat["id"],
            cashback_amount="12.34",
        ),
    )
    assert override.status_code == 201, override.text
    assert money(override.json()["cashback_amount"]) == Decimal("12.34")

    report = (
        await client.get("/reports/cashback", params={"year": 2026, "month": 7, "account_id": account["id"]})
    ).json()
    assert money(report["expected_total"]) == Decimal("59.34")

    await client.patch(f"/accounts/{account['id']}", json={"cashback_rounding": "base_100"})
    await client.put(
        f"/accounts/{account['id']}/cashback-rates",
        json={"year": 2026, "month": 8, "rates": [{"cashback_category_id": cat["id"], "percent": "6"}]},
    )
    base = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="950.00",
            date="2026-08-01",
            description="base100",
            cashback_category_id=cat["id"],
        ),
    )
    assert base.status_code == 201, base.text
    assert money(base.json()["cashback_amount"]) == Decimal("54")


async def test_expense_to_refund_clears_cashback_unless_sent(client: AsyncClient, categories):
    """Flipping expense→refund must not keep the purchase cashback on the refund row."""
    account = (
        await client.post("/accounts", json={"name": "CB Card", "type": "debit_card", "currency": "RUB"})
    ).json()
    cat = (
        await client.post("/cashback-categories", json={"account_id": account["id"], "name": "Shop"})
    ).json()
    await client.put(
        f"/accounts/{account['id']}/cashback-rates",
        json={"year": 2026, "month": 9, "rates": [{"cashback_category_id": cat["id"], "percent": "5"}]},
    )
    groceries = categories["Groceries"]["id"]

    purchase = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="200.00",
            date="2026-09-01",
            description="keep",
        ),
    )
    assert purchase.status_code == 201
    purchase_id = purchase.json()["id"]

    mistaken = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="50.00",
            date="2026-09-02",
            description="was expense",
            cashback_category_id=cat["id"],
        ),
    )
    assert mistaken.status_code == 201, mistaken.text
    assert money(mistaken.json()["cashback_amount"]) == Decimal("2")
    mistaken_id = mistaken.json()["id"]

    # Partial PATCH: type flip only — cashback from the expense must not stick.
    cleared = await client.patch(
        f"/transactions/{mistaken_id}",
        json={
            "type": "refund",
            "category_id": None,
            "refund_of_transaction_id": purchase_id,
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cashback_amount"] is None
    assert cleared.json()["cashback_category_id"] is None

    # Explicit clawback on the same kind of flip is preserved.
    again = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="80.00",
            date="2026-09-03",
            description="expense again",
            cashback_category_id=cat["id"],
        ),
    )
    assert again.status_code == 201, again.text
    clawback = await client.patch(
        f"/transactions/{again.json()['id']}",
        json={
            "type": "refund",
            "category_id": None,
            "refund_of_transaction_id": purchase_id,
            "cashback_amount": "-2.00",
            "cashback_category_id": cat["id"],
        },
    )
    assert clawback.status_code == 200, clawback.text
    assert money(clawback.json()["cashback_amount"]) == Decimal("-2.00")


async def test_income_to_refund_clears_is_cashback(client: AsyncClient, categories):
    """Flipping income→refund must clear is_cashback and not invent cashback_amount."""
    account = (
        await client.post("/accounts", json={"name": "Income CB", "type": "debit_card", "currency": "RUB"})
    ).json()
    groceries = categories["Groceries"]["id"]
    salary = categories["Salary"]["id"]

    purchase = await client.post(
        "/transactions",
        json=_txn(
            account["id"],
            category_id=groceries,
            amount="200.00",
            date="2026-10-01",
            description="purchase for refund",
        ),
    )
    assert purchase.status_code == 201
    purchase_id = purchase.json()["id"]

    income = await client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": salary,
            "type": "income",
            "amount": "50.00",
            "description": "bank cashback income",
            "date": "2026-10-02",
            "is_cashback": True,
        },
    )
    assert income.status_code == 201, income.text
    assert income.json()["is_cashback"] is True
    income_id = income.json()["id"]

    converted = await client.patch(
        f"/transactions/{income_id}",
        json={
            "type": "refund",
            "category_id": None,
            "refund_of_transaction_id": purchase_id,
        },
    )
    assert converted.status_code == 200, converted.text
    body = converted.json()
    assert body["type"] == "refund"
    assert body["is_cashback"] is False
    assert body["cashback_amount"] is None
    assert body["cashback_category_id"] is None


async def test_filter_transactions_by_account(client: AsyncClient, account_id, categories):
    other = (await client.post("/accounts", json={"name": "Other", "type": "checking", "currency": "USD"})).json()
    groceries = categories["Groceries"]["id"]
    await client.post("/transactions", json=_txn(account_id, category_id=groceries, description="mine"))
    await client.post("/transactions", json=_txn(other["id"], category_id=groceries, description="theirs"))

    filtered = await client.get("/transactions", params={"account_id": account_id})
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["description"] == "Mine"
