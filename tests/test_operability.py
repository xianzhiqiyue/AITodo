from datetime import datetime, timedelta, timezone

import pytest

from app.schemas import TaskCreate
from app.services.notification_service import AlertDeliveryService
from app.services.task_service import TaskService
from app.services.workspace_service import WorkspaceService


pytestmark = pytest.mark.asyncio


class FakeNotificationProvider:
    channel = "webhook"

    def __init__(self):
        self.messages: list[tuple[str, dict]] = []

    async def send(self, message: str, payload: dict) -> None:
        self.messages.append((message, payload))


async def test_workspace_dashboard_aggregates_sections(task_service: TaskService):
    now = datetime.now(timezone.utc)
    await task_service.upsert_task(
        data=TaskCreate(title="Today", due_at=now.replace(hour=12, minute=0, second=0, microsecond=0))
    )
    await task_service.upsert_task(
        data=TaskCreate(title="Blocked", status="blocked")
    )
    ready = await task_service.upsert_task(
        data=TaskCreate(title="Ready")
    )

    dashboard = await WorkspaceService(task_service).get_dashboard(top_n=5)

    assert any(task.title == "Today" for task in dashboard.today.tasks)
    assert any(task.title == "Blocked" for task in dashboard.blocked.tasks)
    assert any(task.id == ready.id for task in dashboard.ready_to_start.tasks)
    assert dashboard.recently_updated.total >= 1


async def test_alert_delivery_dispatches_and_deduplicates(task_service: TaskService):
    overdue = await task_service.upsert_task(
        data=TaskCreate(
            title="Overdue",
            due_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    provider = FakeNotificationProvider()
    service = AlertDeliveryService(task_service=task_service, provider=provider, repeat_window_hours=6)

    first = await service.dispatch_alerts(top_n=10)
    second = await service.dispatch_alerts(top_n=10)

    assert first.sent_count >= 1
    assert any(delivery.task_id == overdue.id for delivery in first.deliveries)
    assert second.skipped_count >= 1
    assert len(provider.messages) == first.sent_count
