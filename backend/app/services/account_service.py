"""Account CRUD, plus each account's live balance — summed from its
Transaction rows (income adds, expense subtracts, a transfer moves
amount+fee from the source and transfer_amount onto the destination, a
refund credits the account) rather than stored, the same "derive it, don't
duplicate it" approach net_worth_service.py uses for Cash.
"""
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.enums import AccountType
from app.models.transaction import Transaction
from app.schemas.account import AccountCreate, AccountUpdate, AccountWithBalance, _credit_cycle_fields_ok
from app.services.credit_card_service import credit_due_for_account
from app.services.money_effects import apply_balance_delta


async def _account_balances(session: AsyncSession) -> dict[int, Decimal]:
    result = await session.execute(
        select(
            Transaction.type,
            Transaction.amount,
            Transaction.transfer_amount,
            Transaction.fee_amount,
            Transaction.account_id,
            Transaction.transfer_account_id,
        )
    )
    balances: dict[int, Decimal] = defaultdict(Decimal)
    for tx_type, amount, transfer_amount, fee_amount, account_id, transfer_account_id in result.all():
        apply_balance_delta(
            balances,
            tx_type=tx_type,
            amount=amount,
            transfer_amount=transfer_amount,
            fee_amount=fee_amount,
            account_id=account_id,
            transfer_account_id=transfer_account_id,
        )
    return balances


async def _to_read(session: AsyncSession, account: Account, balance: Decimal) -> AccountWithBalance:
    due_amount, due_date = await credit_due_for_account(session, account)
    return AccountWithBalance(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        color=account.color,
        is_archived=account.is_archived,
        cashback_rounding=account.cashback_rounding,
        statement_day=account.statement_day,
        payment_day=account.payment_day,
        grace_period_days=account.grace_period_days,
        balance=balance,
        credit_due_amount=due_amount,
        credit_due_date=due_date,
    )


async def list_accounts(session: AsyncSession, include_archived: bool) -> list[AccountWithBalance]:
    stmt = select(Account).order_by(Account.name)
    if not include_archived:
        stmt = stmt.where(Account.is_archived.is_(False))
    accounts = (await session.execute(stmt)).scalars().all()
    balances = await _account_balances(session)
    return [
        await _to_read(session, account, balances.get(account.id, Decimal("0"))) for account in accounts
    ]


async def create_account(session: AsyncSession, payload: AccountCreate) -> AccountWithBalance:
    account = Account(**payload.model_dump())
    session.add(account)
    await session.commit()
    await session.refresh(account)
    # A brand-new account has no transactions yet — no need to query.
    return await _to_read(session, account, Decimal("0"))


async def update_account(session: AsyncSession, account_id: int, payload: AccountUpdate) -> AccountWithBalance:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    updates = payload.model_dump(exclude_unset=True)

    effective_type = updates.get("type", account.type)
    # When leaving credit_card, clear cycle fields even if the client omitted them.
    if effective_type != AccountType.CREDIT_CARD:
        updates["statement_day"] = None
        updates["payment_day"] = None
        updates["grace_period_days"] = None
    else:
        statement_day = updates.get("statement_day", account.statement_day)
        payment_day = updates.get("payment_day", account.payment_day)
        grace_period_days = updates.get("grace_period_days", account.grace_period_days)
        problem = _credit_cycle_fields_ok(
            type=effective_type,
            statement_day=statement_day,
            payment_day=payment_day,
            grace_period_days=grace_period_days,
        )
        if problem:
            raise HTTPException(status_code=422, detail=problem)

    for field, value in updates.items():
        setattr(account, field, value)
    await session.commit()
    await session.refresh(account)
    balances = await _account_balances(session)
    return await _to_read(session, account, balances.get(account.id, Decimal("0")))


async def delete_account(session: AsyncSession, account_id: int) -> None:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await session.delete(account)
    await session.commit()


async def account_has_transactions(session: AsyncSession, account_id: int) -> bool:
    count = (
        await session.execute(select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id))
    ).scalar_one()
    return count > 0
