import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_task_service, verify_api_key
from app.database import get_async_session
from app.schemas import (
    DecomposeRequest,
    DecomposeResponse,
    DeleteResponse,
    HealthResponse,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.upsert_task(data=data)


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.upsert_task(update_data=data, task_id=task_id)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status_filter: str = Query("open"),
    top_n: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tags: list[str] | None = Query(None),
    query: str | None = Query(None),
    parent_id: uuid.UUID | None = Query(None),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.get_task_context(
        status_filter=status_filter,
        top_n=top_n,
        offset=offset,
        tags=tags,
        query=query,
        parent_id=parent_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.get_task(task_id)


@router.delete("/tasks/{task_id}", response_model=DeleteResponse)
async def delete_task(
    task_id: uuid.UUID,
    cascade: bool = Query(False),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.delete_task(task_id, cascade=cascade)


@router.post("/tasks/{task_id}/decompose", response_model=DecomposeResponse)
async def decompose_task(
    task_id: uuid.UUID,
    data: DecomposeRequest,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.decompose_task(task_id, data.sub_tasks)


health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse)
async def health_check(session: AsyncSession = Depends(get_async_session)):
    db_status = "connected"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return HealthResponse(status="healthy", database=db_status, version="1.0.0")
