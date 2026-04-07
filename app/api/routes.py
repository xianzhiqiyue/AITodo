import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_alert_delivery_service,
    get_blocked_recovery_service,
    get_execution_suggestion_service,
    get_reminder_service,
    get_review_summary_service,
    get_task_intake_service,
    get_task_parsing_service,
    get_task_planning_service,
    get_task_service,
    get_workspace_service,
    verify_api_key,
)
from app.config import Settings, get_settings
from app.database import get_async_session
from app.schemas import (
    AlertListResponse,
    ApplyPlanRequest,
    ApplySuggestionRequest,
    BlockedRecoveryResponse,
    DispatchAlertsRequest,
    DispatchAlertsResponse,
    DecomposeRequest,
    DecomposeResponse,
    DecomposeSuggestionResponse,
    DeleteResponse,
    HealthResponse,
    NotificationTestRequest,
    NotificationTestResponse,
    ParseAndCreateTaskRequest,
    ParseAndCreateTaskResponse,
    ParseTaskRequest,
    ParseTaskResponse,
    ReadyTaskListResponse,
    ReviewSummaryResponse,
    ReminderScanResponse,
    SuggestedTaskListResponse,
    TaskCommentCreate,
    TaskCommentListResponse,
    TaskCommentResponse,
    TaskDependencyCreate,
    TaskDependencyListResponse,
    TaskDependencyResponse,
    TaskCreate,
    TaskListResponse,
    TaskPlanResponse,
    TaskResponse,
    TaskUpdate,
    WorkspaceDashboardResponse,
)
from app.services.blocked_recovery_service import BlockedRecoveryService
from app.services.execution_suggestion_service import ExecutionSuggestionService
from app.services.notification_service import AlertDeliveryService
from app.services.task_intake_service import TaskIntakeService
from app.services.task_parsing_service import TaskParsingService
from app.services.reminder_service import ReminderService
from app.services.review_summary_service import ReviewSummaryService
from app.services.task_planning_service import TaskPlanningService
from app.services.task_service import TaskService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.upsert_task(data=data)


@router.put("/tasks/{task_id}", response_model=TaskResponse)
@router.patch("/tasks/{task_id}", response_model=TaskResponse)
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


@router.get("/tasks/{task_id}/decompose/suggestions", response_model=DecomposeSuggestionResponse)
async def suggest_task_decomposition(
    task_id: uuid.UUID,
    svc: TaskPlanningService = Depends(get_task_planning_service),
):
    return await svc.suggest_decomposition(task_id)


@router.post("/tasks/{task_id}/decompose/apply-suggestions", response_model=DecomposeResponse)
async def apply_task_suggestions(
    task_id: uuid.UUID,
    data: ApplySuggestionRequest,
    svc: TaskPlanningService = Depends(get_task_planning_service),
):
    return await svc.apply_suggestions(task_id, data.indices)


@router.post("/tasks/{task_id}/plan", response_model=TaskPlanResponse)
async def generate_task_plan(
    task_id: uuid.UUID,
    svc: TaskPlanningService = Depends(get_task_planning_service),
):
    return await svc.generate_plan(task_id)


@router.post("/tasks/{task_id}/apply-plan", response_model=DecomposeResponse)
async def apply_task_plan(
    task_id: uuid.UUID,
    data: ApplyPlanRequest,
    svc: TaskPlanningService = Depends(get_task_planning_service),
):
    return await svc.apply_plan(task_id, data.indices)


@router.post("/tasks/{task_id}/dependencies", response_model=TaskDependencyResponse, status_code=201)
async def add_task_dependency(
    task_id: uuid.UUID,
    data: TaskDependencyCreate,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.add_dependency(task_id, data.depends_on_task_id)


@router.get("/tasks/{task_id}/dependencies", response_model=TaskDependencyListResponse)
async def list_task_dependencies(
    task_id: uuid.UUID,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_dependencies(task_id)


@router.delete("/tasks/{task_id}/dependencies/{dependency_id}", response_model=DeleteResponse)
async def delete_task_dependency(
    task_id: uuid.UUID,
    dependency_id: uuid.UUID,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.remove_dependency(task_id, dependency_id)


@router.post("/tasks/{task_id}/comments", response_model=TaskCommentResponse, status_code=201)
async def add_task_comment(
    task_id: uuid.UUID,
    data: TaskCommentCreate,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.add_comment(task_id, data)


@router.get("/tasks/{task_id}/timeline", response_model=TaskCommentListResponse)
async def list_task_timeline(
    task_id: uuid.UUID,
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_comments(task_id)


@router.post("/tasks/parse", response_model=ParseTaskResponse)
async def parse_task(
    data: ParseTaskRequest,
    svc: TaskParsingService = Depends(get_task_parsing_service),
):
    return await svc.parse_text(data.text)


@router.post("/tasks/parse-and-create", response_model=ParseAndCreateTaskResponse)
async def parse_and_create_task(
    data: ParseAndCreateTaskRequest,
    svc: TaskIntakeService = Depends(get_task_intake_service),
):
    return await svc.parse_and_create(
        text=data.text,
        parent_id=data.parent_id,
        min_confidence=data.min_confidence,
        force_create=data.force_create,
        selected_draft_index=data.selected_draft_index,
        override=data.override,
    )


@router.get("/workspace/ready-to-start", response_model=ReadyTaskListResponse)
async def list_ready_to_start_tasks(
    top_n: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tags: list[str] | None = Query(None),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_ready_tasks(top_n=top_n, offset=offset, tags=tags)


@router.get("/workspace/today", response_model=TaskListResponse)
async def list_today_tasks(
    top_n: int = Query(20, ge=1, le=100),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_today_tasks(top_n=top_n)


@router.get("/workspace/overdue", response_model=TaskListResponse)
async def list_overdue_tasks(
    top_n: int = Query(20, ge=1, le=100),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_overdue_tasks(top_n=top_n)


@router.get("/workspace/blocked", response_model=TaskListResponse)
async def list_blocked_tasks(
    top_n: int = Query(20, ge=1, le=100),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_blocked_tasks(top_n=top_n)


@router.get("/workspace/recently-updated", response_model=TaskListResponse)
async def list_recently_updated_tasks(
    top_n: int = Query(20, ge=1, le=100),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_recently_updated_tasks(top_n=top_n)


@router.get("/workspace/alerts", response_model=AlertListResponse)
async def list_workspace_alerts(
    top_n: int = Query(20, ge=1, le=100),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_alerts(top_n=top_n)


@router.get("/workspace/dashboard", response_model=WorkspaceDashboardResponse)
async def get_workspace_dashboard(
    top_n: int = Query(10, ge=1, le=100),
    svc: WorkspaceService = Depends(get_workspace_service),
):
    return await svc.get_dashboard(top_n=top_n)


@router.get("/workspace/suggested-today", response_model=SuggestedTaskListResponse)
async def get_suggested_today(
    top_n: int = Query(10, ge=1, le=100),
    tags: list[str] | None = Query(None),
    svc: ExecutionSuggestionService = Depends(get_execution_suggestion_service),
):
    return await svc.get_suggested_today(top_n=top_n, tags=tags)


@router.get("/workspace/stale", response_model=TaskListResponse)
async def get_stale_tasks(
    top_n: int = Query(20, ge=1, le=100),
    svc: ExecutionSuggestionService = Depends(get_execution_suggestion_service),
):
    result = await svc.get_stale_tasks(top_n=top_n)
    return TaskListResponse(tasks=result.tasks, total=result.total, offset=0)


@router.post("/reminders/scan", response_model=ReminderScanResponse)
async def scan_reminders(
    top_n: int = Query(20, ge=1, le=100),
    svc: ReminderService = Depends(get_reminder_service),
):
    return await svc.scan(top_n=top_n)


@router.post("/notifications/dispatch-alerts", response_model=DispatchAlertsResponse)
async def dispatch_alerts(
    data: DispatchAlertsRequest,
    svc: AlertDeliveryService = Depends(get_alert_delivery_service),
):
    return await svc.dispatch_alerts(top_n=data.top_n, force=data.force, channel=data.channel)


@router.post("/notifications/test", response_model=NotificationTestResponse)
async def test_notification_channel(
    data: NotificationTestRequest,
    svc: AlertDeliveryService = Depends(get_alert_delivery_service),
):
    return await svc.test_channel(message=data.message, channel=data.channel)


@router.get("/tasks/{task_id}/recovery-suggestions", response_model=BlockedRecoveryResponse)
async def get_task_recovery_suggestions(
    task_id: uuid.UUID,
    svc: BlockedRecoveryService = Depends(get_blocked_recovery_service),
):
    return await svc.get_recovery_suggestions(task_id)


@router.get("/reviews/summary", response_model=ReviewSummaryResponse)
async def get_review_summary(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    tags: list[str] | None = Query(None),
    svc: ReviewSummaryService = Depends(get_review_summary_service),
):
    return await svc.summarize(from_date=from_date, to_date=to_date, tags=tags)


health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse)
async def health_check(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
):
    db_status = "connected"
    migration_status = "unknown"
    try:
        await session.execute(text("SELECT 1"))
        try:
            revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
            migration_status = revision or "missing"
        except Exception:
            migration_status = "missing"
    except Exception:
        db_status = "disconnected"
        migration_status = "unknown"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        database=db_status,
        migration=migration_status,
        parsing_service="configured" if settings.parsing_api_key else "heuristic_only",
        embedding_service="configured" if settings.embedding_api_key else "disabled",
        version=settings.app_version,
    )
