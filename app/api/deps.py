from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_async_session
from app.errors import AppError, ErrorCode
from app.services.blocked_recovery_service import BlockedRecoveryService
from app.services.embedding_service import EmbeddingService
from app.services.execution_suggestion_service import ExecutionSuggestionService
from app.services.obsidian_index_service import ObsidianIndexService
from app.services.obsidian_native_intake_service import ObsidianNativeTaskIntakeService
from app.services.obsidian_native_planning_service import ObsidianNativeTaskPlanningService
from app.services.obsidian_native_query_service import ObsidianNativeTaskQueryService
from app.services.obsidian_native_write_service import ObsidianNativeTaskWriteService
from app.services.obsidian_sync_service import ObsidianExportService
from app.services.notification_service import (
    AlertDeliveryService,
    DingTalkNotificationProvider,
    WebhookNotificationProvider,
)
from app.services.reminder_service import ReminderService
from app.services.review_summary_service import ReviewSummaryService
from app.services.task_intake_service import TaskIntakeService
from app.services.task_parsing_service import TaskParsingService
from app.services.task_planning_service import TaskPlanningService
from app.services.task_service import TaskService
from app.services.workspace_service import WorkspaceService


async def verify_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    if request.url.path == "/health":
        return ""

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AppError(ErrorCode.UNAUTHORIZED, "Missing or invalid Authorization header.")

    token = auth_header[7:]
    if token != settings.api_key:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid API key.")

    return token


async def get_task_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> TaskService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    is_pg = "postgresql" in settings.database_url
    return TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres=is_pg,
        timezone_name=settings.parsing_timezone,
    )


def get_task_parsing_service(
    settings: Settings = Depends(get_settings),
) -> TaskParsingService:
    return TaskParsingService(settings)


async def get_task_intake_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> TaskIntakeService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    parsing_service = TaskParsingService(settings)
    return TaskIntakeService(task_service=task_service, parsing_service=parsing_service)


async def get_task_planning_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> TaskPlanningService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return TaskPlanningService(task_service=task_service)


async def get_reminder_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ReminderService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return ReminderService(task_service=task_service)


async def get_workspace_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> WorkspaceService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return WorkspaceService(task_service=task_service)


async def get_alert_delivery_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> AlertDeliveryService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    providers = {}
    if settings.notification_webhook_url:
        providers["webhook"] = WebhookNotificationProvider(settings.notification_webhook_url)
    if settings.notification_dingtalk_webhook_url:
        providers["dingtalk"] = DingTalkNotificationProvider(settings.notification_dingtalk_webhook_url)
    return AlertDeliveryService(
        task_service=task_service,
        providers=providers,
        repeat_window_hours=settings.notification_repeat_window_hours,
    )


async def get_execution_suggestion_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ExecutionSuggestionService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return ExecutionSuggestionService(task_service=task_service)


async def get_blocked_recovery_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> BlockedRecoveryService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return BlockedRecoveryService(task_service=task_service)


async def get_review_summary_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ReviewSummaryService:
    embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
    task_service = TaskService(
        session=session,
        embedding_service=embedding_svc,
        is_postgres="postgresql" in settings.database_url,
        timezone_name=settings.parsing_timezone,
    )
    return ReviewSummaryService(task_service=task_service)


async def get_obsidian_export_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianExportService:
    return ObsidianExportService(session=session, settings=settings)


async def get_obsidian_index_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianIndexService:
    return ObsidianIndexService(session=session, settings=settings)


async def get_obsidian_native_query_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianNativeTaskQueryService:
    return ObsidianNativeTaskQueryService(session=session, timezone_name=settings.parsing_timezone)


async def get_obsidian_native_write_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianNativeTaskWriteService:
    return ObsidianNativeTaskWriteService(session=session, settings=settings)


async def get_obsidian_native_intake_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianNativeTaskIntakeService:
    write_service = ObsidianNativeTaskWriteService(session=session, settings=settings)
    parsing_service = TaskParsingService(settings)
    return ObsidianNativeTaskIntakeService(write_service=write_service, parsing_service=parsing_service)


async def get_obsidian_native_planning_service(
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings),
) -> ObsidianNativeTaskPlanningService:
    query_service = ObsidianNativeTaskQueryService(session=session, timezone_name=settings.parsing_timezone)
    write_service = ObsidianNativeTaskWriteService(session=session, settings=settings)
    return ObsidianNativeTaskPlanningService(query_service=query_service, write_service=write_service)
