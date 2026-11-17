"""Checklist items for planned expenses/income (not real transactions)."""
from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TodoKind
from app.models.mixins import TimestampMixin


class TodoItem(Base, TimestampMixin):
    """A dated reminder with optional amount — feeds dashboard planned_* when active."""

    __tablename__ = "todo_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    due_date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    kind: Mapped[TodoKind] = mapped_column(
        Enum(TodoKind, name="todo_kind", native_enum=False, length=10), nullable=False
    )
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When set, UI offers «+step» that adds 100/step_count percent.
    step_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    count_in_dashboard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
