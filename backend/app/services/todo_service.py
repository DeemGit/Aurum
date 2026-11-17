"""CRUD and progress helpers for planned todo checklist items."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TodoKind
from app.models.todo import TodoItem
from app.schemas.todo import TodoCreate, TodoRead, TodoUpdate


def _as_read(row: TodoItem) -> TodoRead:
    return TodoRead.model_validate(row)


async def list_todos(session: AsyncSession, *, include_deleted: bool = False) -> list[TodoRead]:
    stmt = select(TodoItem).order_by(TodoItem.due_date.asc(), TodoItem.id.asc())
    if not include_deleted:
        stmt = stmt.where(TodoItem.deleted_at.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    return [_as_read(row) for row in rows]


async def create_todo(session: AsyncSession, payload: TodoCreate) -> TodoRead:
    row = TodoItem(**payload.model_dump())
    if row.progress_percent >= 100:
        row.progress_percent = 100
        row.completed_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _as_read(row)


async def _get_active(session: AsyncSession, todo_id: int) -> TodoItem:
    row = await session.get(TodoItem, todo_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return row


async def update_todo(session: AsyncSession, todo_id: int, payload: TodoUpdate) -> TodoRead:
    row = await _get_active(session, todo_id)
    data = payload.model_dump(exclude_unset=True)
    # Explicit null for amount / step_count clears the field.
    for key, value in data.items():
        setattr(row, key, value)
    if "progress_percent" in data:
        if row.progress_percent >= 100:
            row.progress_percent = 100
            row.completed_at = row.completed_at or datetime.now(timezone.utc)
        elif row.progress_percent < 100:
            row.completed_at = None
    await session.commit()
    await session.refresh(row)
    return _as_read(row)


async def soft_delete_todo(session: AsyncSession, todo_id: int) -> None:
    row = await _get_active(session, todo_id)
    row.deleted_at = datetime.now(timezone.utc)
    await session.commit()


async def complete_todo(session: AsyncSession, todo_id: int) -> TodoRead:
    row = await _get_active(session, todo_id)
    row.progress_percent = 100
    row.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _as_read(row)


async def step_todo(session: AsyncSession, todo_id: int) -> TodoRead:
    row = await _get_active(session, todo_id)
    if row.step_count is None or row.step_count < 1:
        raise HTTPException(status_code=400, detail="Todo has no step_count")
    step = (Decimal(100) / Decimal(row.step_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Keep percent as int 0–100; accumulate via Decimal then round.
    current = Decimal(row.progress_percent)
    nxt = min(Decimal(100), current + step)
    row.progress_percent = int(nxt.to_integral_value(rounding=ROUND_HALF_UP))
    if row.progress_percent >= 100:
        row.progress_percent = 100
        row.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _as_read(row)


async def sum_planned_amounts(
    session: AsyncSession,
    *,
    kind: TodoKind,
    year: int,
    month: int,
    today: date | None = None,
) -> Decimal:
    """Future incomplete todos in the month that count toward the dashboard."""
    today = today or date.today()
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    # due_date in [start, end) and >= today
    effective_start = max(start, today)
    if effective_start >= end:
        return Decimal("0")

    stmt = select(func.coalesce(func.sum(TodoItem.amount), 0)).where(
        TodoItem.kind == kind,
        TodoItem.deleted_at.is_(None),
        TodoItem.completed_at.is_(None),
        TodoItem.count_in_dashboard.is_(True),
        TodoItem.amount.is_not(None),
        TodoItem.due_date >= effective_start,
        TodoItem.due_date < end,
    )
    return (await session.execute(stmt)).scalar_one()
