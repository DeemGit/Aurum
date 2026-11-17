from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TodoKind


class TodoFields(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    due_date: date_
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    kind: TodoKind
    progress_percent: int = Field(default=0, ge=0, le=100)
    step_count: int | None = Field(default=None, ge=1, le=365)
    count_in_dashboard: bool = True

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be empty")
        return cleaned


class TodoCreate(TodoFields):
    pass


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    due_date: date_ | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    kind: TodoKind | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    step_count: int | None = Field(default=None, ge=1, le=365)
    count_in_dashboard: bool | None = None

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be empty")
        return cleaned


class TodoRead(TodoFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    completed_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
