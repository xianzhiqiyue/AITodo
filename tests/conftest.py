import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.database import Base, get_async_session
from app.models import NotificationDelivery, Task, TaskComment, TaskDependency  # noqa: F401
from app.services.task_parsing_service import TaskParsingService
from app.services.task_service import TaskService
from main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def build_test_settings(parsing_timezone: str = "UTC") -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        api_key="test-key",
        app_version="1.1.0-test",
        embedding_api_key="",
        embedding_base_url="https://api.openai.com/v1",
        parsing_api_key="",
        parsing_base_url="https://api.openai.com/v1",
        parsing_model="gpt-4o-mini",
        parsing_timezone=parsing_timezone,
        notification_webhook_url="",
        notification_repeat_window_hours=6,
        slow_request_threshold_ms=1,
        log_level="WARNING",
    )


def get_test_settings() -> Settings:
    return build_test_settings()


test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def task_service(db_session: AsyncSession) -> TaskService:
    return TaskService(
        session=db_session,
        embedding_service=None,
        is_postgres=False,
        timezone_name="UTC",
    )


@pytest_asyncio.fixture
async def shanghai_task_service(db_session: AsyncSession) -> TaskService:
    return TaskService(
        session=db_session,
        embedding_service=None,
        is_postgres=False,
        timezone_name="Asia/Shanghai",
    )


@pytest.fixture
def task_parsing_service() -> TaskParsingService:
    return TaskParsingService(get_test_settings())


async def _override_get_async_session():
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_settings] = get_test_settings
    app.dependency_overrides[get_async_session] = _override_get_async_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c

    app.dependency_overrides.clear()


def get_shanghai_test_settings() -> Settings:
    return build_test_settings(parsing_timezone="Asia/Shanghai")


@pytest_asyncio.fixture
async def shanghai_client() -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_settings] = get_shanghai_test_settings
    app.dependency_overrides[get_async_session] = _override_get_async_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c

    app.dependency_overrides.clear()
