from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.schemas.todo import TodoCreate, TodoRead, TodoUpdate
from app.services import todo_service

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("", response_model=list[TodoRead])
async def read_todos(
    include_deleted: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> list[TodoRead]:
    return await todo_service.list_todos(session, include_deleted=include_deleted)


@router.post("", response_model=TodoRead, status_code=201)
async def create_todo_route(
    payload: TodoCreate, session: AsyncSession = Depends(get_session)
) -> TodoRead:
    return await todo_service.create_todo(session, payload)


@router.patch("/{todo_id}", response_model=TodoRead)
async def update_todo_route(
    todo_id: int, payload: TodoUpdate, session: AsyncSession = Depends(get_session)
) -> TodoRead:
    return await todo_service.update_todo(session, todo_id, payload)


@router.delete("/{todo_id}", status_code=204)
async def delete_todo_route(todo_id: int, session: AsyncSession = Depends(get_session)) -> None:
    await todo_service.delete_todo(session, todo_id)


@router.post("/{todo_id}/complete", response_model=TodoRead)
async def complete_todo_route(
    todo_id: int, session: AsyncSession = Depends(get_session)
) -> TodoRead:
    return await todo_service.complete_todo(session, todo_id)


@router.post("/{todo_id}/step", response_model=TodoRead)
async def step_todo_route(
    todo_id: int, session: AsyncSession = Depends(get_session)
) -> TodoRead:
    return await todo_service.step_todo(session, todo_id)
