"""CRUD and progress helpers for planned todo checklist items."""
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TodoKind
from app.models.todo import TodoItem
from app.schemas.todo import TodoCreate, TodoRead, TodoUpdate


def _as_read(row: TodoItem) -> TodoRead:
    return TodoRead.model_validate(row)


def percent_for_steps(steps_done: int, step_count: int) -> int:
    """Integer percent for k of N steps: (100 * k) // N; full → 100."""
    if step_count < 1:
        return 0
    if steps_done >= step_count:
        return 100
    if steps_done <= 0:
        return 0
    return (100 * steps_done) // step_count


def steps_from_percent(progress_percent: int, step_count: int) -> int:
    """Largest k such that percent_for_steps(k, N) <= progress_percent."""
    if step_count < 1:
        return 0
    if progress_percent >= 100:
        return step_count
    if progress_percent <= 0:
        return 0
    k = 0
    for i in range(1, step_count + 1):
        if percent_for_steps(i, step_count) <= progress_percent:
            k = i
        else:
            break
    return k


def _apply_progress_kind_rules(row: TodoItem) -> None:
    """Progress notes never feed the dashboard planned_* totals."""
    if row.kind == TodoKind.PROGRESS:
        row.count_in_dashboard = False


async def list_todos(session: AsyncSession, *, include_deleted: bool = False) -> list[TodoRead]:
    stmt = select(TodoItem).order_by(TodoItem.due_date.asc(), TodoItem.id.asc())
    if not include_deleted:
        stmt = stmt.where(TodoItem.deleted_at.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    return [_as_read(row) for row in rows]


async def create_todo(session: AsyncSession, payload: TodoCreate) -> TodoRead:
    row = TodoItem(**payload.model_dump())
    _apply_progress_kind_rules(row)
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
    _apply_progress_kind_rules(row)
    if "progress_percent" in data:
        if row.progress_percent >= 100:
            row.progress_percent = 100
            row.completed_at = row.completed_at or datetime.now(timezone.utc)
        elif row.progress_percent < 100:
            row.completed_at = None
    await session.commit()
    await session.refresh(row)
    return _as_read(row)


async def delete_todo(session: AsyncSession, todo_id: int) -> None:
    """Soft-delete an active row; permanently purge an already soft-deleted one."""
    row = await session.get(TodoItem, todo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if row.deleted_at is None:
        row.deleted_at = datetime.now(timezone.utc)
    else:
        await session.delete(row)
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
    n = row.step_count
    k = min(n, steps_from_percent(row.progress_percent, n) + 1)
    row.progress_percent = percent_for_steps(k, n)
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
