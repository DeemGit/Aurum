from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.schemas.cashback import (
    AccountCashbackRateRead,
    AccountCashbackRatesCopy,
    AccountCashbackRatesUpsert,
    CashbackCategoryCreate,
    CashbackCategoryRead,
    CashbackCategoryUpdate,
    CashbackReport,
)
from app.services import cashback_service

router = APIRouter(tags=["cashback"])


@router.get("/cashback-categories", response_model=list[CashbackCategoryRead])
async def list_categories(session: AsyncSession = Depends(get_session)) -> list[CashbackCategoryRead]:
    return await cashback_service.list_cashback_categories(session)


@router.post("/cashback-categories", response_model=CashbackCategoryRead, status_code=201)
async def create_category(
    payload: CashbackCategoryCreate, session: AsyncSession = Depends(get_session)
) -> CashbackCategoryRead:
    return await cashback_service.create_cashback_category(session, payload)


@router.patch("/cashback-categories/{category_id}", response_model=CashbackCategoryRead)
async def update_category(
    category_id: int, payload: CashbackCategoryUpdate, session: AsyncSession = Depends(get_session)
) -> CashbackCategoryRead:
    return await cashback_service.update_cashback_category(session, category_id, payload)


@router.delete("/cashback-categories/{category_id}", status_code=204)
async def delete_category(category_id: int, session: AsyncSession = Depends(get_session)) -> None:
    await cashback_service.delete_cashback_category(session, category_id)


@router.get("/accounts/{account_id}/cashback-rates", response_model=list[AccountCashbackRateRead])
async def list_rates(
    account_id: int,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    session: AsyncSession = Depends(get_session),
) -> list[AccountCashbackRateRead]:
    return await cashback_service.list_account_rates(session, account_id, year, month)


@router.put("/accounts/{account_id}/cashback-rates", response_model=list[AccountCashbackRateRead])
async def upsert_rates(
    account_id: int,
    payload: AccountCashbackRatesUpsert,
    session: AsyncSession = Depends(get_session),
) -> list[AccountCashbackRateRead]:
    return await cashback_service.upsert_account_rates(session, account_id, payload)


@router.post("/accounts/{account_id}/cashback-rates/copy", response_model=list[AccountCashbackRateRead])
async def copy_rates(
    account_id: int,
    payload: AccountCashbackRatesCopy,
    session: AsyncSession = Depends(get_session),
) -> list[AccountCashbackRateRead]:
    return await cashback_service.copy_account_rates(session, account_id, payload)


@router.get("/reports/cashback", response_model=CashbackReport)
async def cashback_report(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> CashbackReport:
    return await cashback_service.get_cashback_report(session, year=year, month=month, account_id=account_id)
