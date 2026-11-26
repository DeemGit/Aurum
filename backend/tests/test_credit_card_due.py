"""Credit-card statement periods and FIFO repayment allocation."""
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from types import SimpleNamespace

from app.models.enums import TransactionType
from app.services.credit_card_service import (
    allocate_credit_due,
    collect_card_charges_and_payments,
    due_date_for_period_end,
    statement_period_containing,
)
from tests.helpers import money, txn_payload


def test_statement_period_sep25_to_oct24():
    start, end = statement_period_containing(date(2025, 10, 1), statement_day=25)
    assert start == date(2025, 9, 25)
    assert end == date(2025, 10, 24)
    assert due_date_for_period_end(end, payment_day=18) == date(2025, 11, 18)


def test_allocate_due_for_closed_period_before_payment_day():
    amount, due = allocate_credit_due(
        statement_day=25,
        payment_day=18,
        charges_by_date=[
            (date(2025, 9, 26), Decimal("1000.00")),
            (date(2025, 10, 20), Decimal("500.00")),
        ],
        payments=[],
        today=date(2025, 11, 10),
    )
    assert due == date(2025, 11, 18)
    assert money(amount) == money("1500.00")


def test_allocate_fifo_payment_reduces_oldest_period():
    amount, due = allocate_credit_due(
        statement_day=25,
        payment_day=18,
        charges_by_date=[
            (date(2025, 9, 26), Decimal("1000.00")),
            (date(2025, 10, 26), Decimal("400.00")),
        ],
        payments=[(date(2025, 11, 5), Decimal("1000.00"))],
        today=date(2025, 11, 10),
    )
    # Sep25–Oct24 fully paid; Oct25+ is due Dec 18, not yet in Nov 18 anchor.
    assert amount is None
    assert due is None

    amount2, due2 = allocate_credit_due(
        statement_day=25,
        payment_day=18,
        charges_by_date=[
            (date(2025, 9, 26), Decimal("1000.00")),
            (date(2025, 10, 26), Decimal("400.00")),
        ],
        payments=[(date(2025, 11, 5), Decimal("1000.00"))],
        today=date(2025, 11, 20),
    )
    assert due2 == date(2025, 12, 18)
    assert money(amount2) == money("400.00")


def test_refund_reduces_period_charges():
    amount, due = allocate_credit_due(
        statement_day=25,
        payment_day=18,
        charges_by_date=[
            (date(2025, 9, 26), Decimal("1000.00")),
            (date(2025, 10, 1), Decimal("-200.00")),
        ],
        payments=[],
        today=date(2025, 11, 10),
    )
    assert due == date(2025, 11, 18)
    assert money(amount) == money("800.00")


def test_outbound_transfer_from_card_counts_as_charge():
    """Cash moved off the card is statement debt (amount + fee), not income elsewhere."""
    card_id = 10
    rows = [
        SimpleNamespace(
            account_id=card_id,
            transfer_account_id=20,
            type=TransactionType.TRANSFER,
            date=date(2025, 9, 26),
            amount=Decimal("250.00"),
            transfer_amount=Decimal("250.00"),
            fee_amount=Decimal("50.00"),
        ),
        SimpleNamespace(
            account_id=30,
            transfer_account_id=card_id,
            type=TransactionType.TRANSFER,
            date=date(2025, 11, 1),
            amount=Decimal("100.00"),
            transfer_amount=Decimal("100.00"),
            fee_amount=Decimal("0"),
        ),
    ]
    charges, payments = collect_card_charges_and_payments(card_id, rows)
    assert charges == [(date(2025, 9, 26), Decimal("300.00"))]
    assert payments == [(date(2025, 11, 1), Decimal("100.00"))]

    amount, due = allocate_credit_due(
        statement_day=25,
        payment_day=18,
        charges_by_date=charges,
        payments=payments,
        today=date(2025, 11, 10),
    )
    assert due == date(2025, 11, 18)
    assert money(amount) == money("200.00")


async def test_credit_card_account_api_due_amount(client: AsyncClient, categories):
    created = await client.post(
        "/accounts",
        json={
            "name": "CC",
            "type": "credit_card",
            "currency": "RUB",
            "statement_day": 25,
            "payment_day": 18,
            "grace_period_days": 55,
        },
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["statement_day"] == 25
    assert card["payment_day"] == 18

    checking = (
        await client.post("/accounts", json={"name": "Bank", "type": "checking", "currency": "RUB"})
    ).json()

    # Spend in Oct25–Nov24 2026 period → due 18 Dec 2026 (still upcoming in late Nov).
    expense_category = categories.get("Groceries") or next(iter(categories.values()))
    expense = await client.post(
        "/transactions",
        json=txn_payload(
            card["id"],
            type="expense",
            amount="1500.00",
            category_id=expense_category["id"],
            description="shop",
            date="2026-10-26",
        ),
    )
    assert expense.status_code == 201, expense.text

    transfer = await client.post(
        "/transactions",
        json=txn_payload(
            checking["id"],
            type="transfer",
            amount="500.00",
            transfer_account_id=card["id"],
            transfer_amount="500.00",
            description="cc payment",
            date="2026-11-20",
            category_id=None,
        ),
    )
    assert transfer.status_code == 201, transfer.text

    listing = await client.get("/accounts")
    assert listing.status_code == 200
    row = next(item for item in listing.json() if item["id"] == card["id"])
    assert row["credit_due_date"] == "2026-12-18"
    assert money(row["credit_due_amount"]) == money("1000.00")


async def test_credit_card_requires_cycle_fields(client: AsyncClient):
    response = await client.post(
        "/accounts",
        json={"name": "Bad CC", "type": "credit_card", "currency": "RUB"},
    )
    assert response.status_code == 422
