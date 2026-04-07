from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_async_session
from app.errors import AppError, ErrorCode
from app.services.embedding_service import EmbeddingService
from app.services.notification_service import AlertDeliveryService, WebhookNotificationProvider
from app.services.reminder_service import ReminderService
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
    provider = (
        WebhookNotificationProvider(settings.notification_webhook_url)
        if settings.notification_webhook_url
        else None
    )
    return AlertDeliveryService(
        task_service=task_service,
        provider=provider,
        repeat_window_hours=settings.notification_repeat_window_hours,
    )
