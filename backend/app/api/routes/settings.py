from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate
from app.services.settings_service import (
    get_or_create_app_settings,
    read_app_settings,
    replace_dashboard_excluded_tags,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsRead)
async def read_settings(session: AsyncSession = Depends(get_session)) -> AppSettingsRead:
    return await read_app_settings(session)


@router.patch("", response_model=AppSettingsRead)
async def update_settings(
    payload: AppSettingsUpdate, session: AsyncSession = Depends(get_session)
) -> AppSettingsRead:
    settings = await get_or_create_app_settings(session)
    data = payload.model_dump(exclude_unset=True)
    tag_ids = data.pop("dashboard_excluded_tag_ids", None)
    for field, value in data.items():
        setattr(settings, field, value)
    if tag_ids is not None:
        await replace_dashboard_excluded_tags(session, tag_ids)
    await session.commit()
    return await read_app_settings(session)
