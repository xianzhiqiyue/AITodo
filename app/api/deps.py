from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_async_session
from app.errors import AppError, ErrorCode
from app.services.embedding_service import EmbeddingService
from app.services.task_service import TaskService


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
    return TaskService(session=session, embedding_service=embedding_svc, is_postgres=is_pg)
