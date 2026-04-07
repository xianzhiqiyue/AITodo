from datetime import datetime, timedelta, timezone

import pytest

from app.schemas import TaskCreate, TaskUpdate
from app.services.notification_service import AlertDeliveryService
from app.services.execution_suggestion_service import ExecutionSuggestionService
from app.services.blocked_recovery_service import BlockedRecoveryService
from app.services.review_summary_service import ReviewSummaryService
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
    service = AlertDeliveryService(task_service=task_service, providers={"webhook": provider}, repeat_window_hours=6)

    first = await service.dispatch_alerts(top_n=10)
    second = await service.dispatch_alerts(top_n=10)

    assert first.sent_count >= 1
    assert any(delivery.task_id == overdue.id for delivery in first.deliveries)
    assert second.skipped_count >= 1
    assert len(provider.messages) == first.sent_count


async def test_execution_suggestions_and_stale_tasks(task_service: TaskService):
    now = datetime.now(timezone.utc)
    due_today = now + timedelta(hours=1)
    task = await task_service.upsert_task(
        data=TaskCreate(title="Urgent", priority=1, due_at=due_today)
    )

    suggestion_service = ExecutionSuggestionService(task_service)
    suggestions = await suggestion_service.get_suggested_today(top_n=5)

    assert suggestions.total >= 1
    assert suggestions.tasks[0].task.id == task.id
    assert any(reason in {"due_today", "due_soon", "overdue"} for reason in suggestions.tasks[0].reasons)


async def test_blocked_recovery_service(task_service: TaskService):
    task = await task_service.upsert_task(
        data=TaskCreate(title="Blocked task", status="blocked")
    )
    recovery = await BlockedRecoveryService(task_service).get_recovery_suggestions(task.id)

    assert recovery.task_id == task.id
    assert recovery.summary
    assert len(recovery.suggestions) >= 1


async def test_review_summary_service(task_service: TaskService):
    await task_service.upsert_task(data=TaskCreate(title="Created task"))
    done = await task_service.upsert_task(data=TaskCreate(title="Done task"))
    await task_service.upsert_task(
        update_data=TaskUpdate(status="in_progress"),
        task_id=done.id,
    )
    await task_service.upsert_task(
        update_data=TaskUpdate(status="done"),
        task_id=done.id,
    )

    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(days=1)
    summary = await ReviewSummaryService(task_service).summarize(from_date=from_date, to_date=to_date)

    assert summary.created_count >= 2
    assert summary.completed_count >= 1
