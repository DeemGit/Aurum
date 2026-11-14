from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSettings, DashboardExcludedTag
from app.models.tag import Tag
from app.schemas.settings import AppSettingsRead
from app.schemas.tag import TagRead


async def get_or_create_app_settings(session: AsyncSession) -> AppSettings:
    """Singleton row (id=1) — get-or-create so callers never hit a missing
    row even if app startup's seeding hasn't run yet (e.g. a fresh test DB)."""
    settings = await session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


async def list_dashboard_excluded_tag_ids(session: AsyncSession) -> list[int]:
    rows = (await session.execute(select(DashboardExcludedTag.tag_id))).scalars().all()
    return list(rows)


async def list_dashboard_excluded_tags(session: AsyncSession) -> list[Tag]:
    result = await session.execute(
        select(Tag)
        .join(DashboardExcludedTag, DashboardExcludedTag.tag_id == Tag.id)
        .order_by(Tag.name)
    )
    return list(result.scalars().all())


async def replace_dashboard_excluded_tags(session: AsyncSession, tag_ids: list[int]) -> None:
    unique_ids = sorted(set(tag_ids))
    if unique_ids:
        found = set(
            (await session.execute(select(Tag.id).where(Tag.id.in_(unique_ids)))).scalars().all()
        )
        missing = set(unique_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tag id(s): {sorted(missing)}")
    await session.execute(delete(DashboardExcludedTag))
    for tag_id in unique_ids:
        session.add(DashboardExcludedTag(tag_id=tag_id))


async def read_app_settings(session: AsyncSession) -> AppSettingsRead:
    settings = await get_or_create_app_settings(session)
    tags = await list_dashboard_excluded_tags(session)
    return AppSettingsRead(
        currency=settings.currency,
        negative_cash_flow_threshold_months=settings.negative_cash_flow_threshold_months,
        net_worth_decline_threshold_months=settings.net_worth_decline_threshold_months,
        risky_allocation_threshold_percent=settings.risky_allocation_threshold_percent,
        idle_cash_threshold_amount=settings.idle_cash_threshold_amount,
        idle_cash_threshold_days=settings.idle_cash_threshold_days,
        dashboard_excluded_tags=[TagRead.model_validate(tag) for tag in tags],
    )
