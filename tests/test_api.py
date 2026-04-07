from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.api.deps import get_alert_delivery_service
from app.services.notification_service import AlertDeliveryService
from app.services.task_service import TaskService

import app.services.task_service as task_service_module
from main import app

pytestmark = pytest.mark.asyncio


class FrozenDateTime(datetime):
    current: datetime = datetime(2026, 4, 5, 18, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["migration"] in {"missing", "unknown"}
    assert data["parsing_service"] == "heuristic_only"
    assert data["embedding_service"] == "disabled"
    assert data["version"] == "1.1.0-test"
    assert resp.headers["X-Request-ID"]


async def test_create_task_via_api(client: AsyncClient):
    resp = await client.post("/api/v1/tasks", json={
        "title": "API task",
        "priority": 1,
        "tags": ["test"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "API task"
    assert data["status"] == "todo"
    assert data["id"]


async def test_get_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "Get me"})
    task_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get me"


async def test_update_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "To update"})
    task_id = create_resp.json()["id"]

    resp = await client.put(f"/api/v1/tasks/{task_id}", json={
        "title": "Updated",
        "status": "in_progress",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"
    assert resp.json()["status"] == "in_progress"


async def test_patch_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={
        "title": "Patch me",
        "description": "remove later",
    })
    task_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/tasks/{task_id}", json={
        "description": None,
    })
    assert resp.status_code == 200
    assert resp.json()["description"] is None


async def test_list_tasks_via_api(client: AsyncClient):
    await client.post("/api/v1/tasks", json={"title": "List item 1"})
    await client.post("/api/v1/tasks", json={"title": "List item 2"})

    resp = await client.get("/api/v1/tasks", params={"status_filter": "all"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    assert len(data["tasks"]) >= 2


async def test_delete_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "To delete"})
    task_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 1


async def test_decompose_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "Big task"})
    task_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/tasks/{task_id}/decompose", json={
        "sub_tasks": [
            {"title": "Sub A"},
            {"title": "Sub B", "priority": 2},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sub_tasks"]) == 2


async def test_parse_task_via_api(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse", json={
        "text": "明天补后端测试并提交报告",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "heuristic"
    assert data["raw_text"] == "明天补后端测试并提交报告"
    assert data["draft"]["priority"] == 1
    assert "backend" in data["draft"]["tags"]
    assert "testing" in data["draft"]["tags"]
    assert len(data["candidates"]) >= 1


async def test_parse_task_via_api_handles_weekday_phrase(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse", json={
        "text": "本周五下午给客户发报告",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["draft"]["due_at"] is not None
    assert "due_at" in data["draft"]["meta_data"]["confidence_signals"]
    assert data["confidence"] > 0.5


async def test_parse_task_via_api_handles_relative_day_and_time(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse", json={
        "text": "3天后上午10点给客户发文档",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["draft"]["due_at"] is not None
    assert "time_expression" in data["draft"]["meta_data"]["confidence_signals"]


async def test_parse_and_create_task_rejects_low_confidence_by_default(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse-and-create", json={
        "text": "整理一下 backlog",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is False
    assert data["task"] is None
    assert "below the required threshold" in data["reason"]


async def test_parse_and_create_task_can_force_create(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse-and-create", json={
        "text": "整理一下 backlog",
        "force_create": True,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is True
    assert data["task"]["title"]
    assert data["task"]["meta_data"]["parse_source"] == "heuristic"
    assert data["task"]["meta_data"]["parse_raw_text"] == "整理一下 backlog"


async def test_parse_and_create_task_supports_override_and_candidate_selection(client: AsyncClient):
    resp = await client.post("/api/v1/tasks/parse-and-create", json={
        "text": "明天补后端测试并提交报告，给团队同步",
        "force_create": True,
        "selected_draft_index": 1,
        "override": {
            "title": "同步测试结果",
            "priority": 2,
            "tags": ["backend", "sync"],
        },
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is True
    assert data["task"]["title"] == "同步测试结果"
    assert data["task"]["priority"] == 2
    assert data["task"]["tags"] == ["backend", "sync"]
    assert data["task"]["meta_data"]["selected_draft_index"] == 1


async def test_add_dependency_and_list_ready_tasks_via_api(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "Task A"})
    dependency_resp = await client.post("/api/v1/tasks", json={"title": "Task B"})
    task_id = task_resp.json()["id"]
    dependency_id = dependency_resp.json()["id"]

    create_dep_resp = await client.post(
        f"/api/v1/tasks/{task_id}/dependencies",
        json={"depends_on_task_id": dependency_id},
    )
    assert create_dep_resp.status_code == 201

    ready_resp = await client.get("/api/v1/workspace/ready-to-start")
    assert ready_resp.status_code == 200
    ready_ids = {task["id"] for task in ready_resp.json()["tasks"]}
    assert dependency_id in ready_ids
    assert task_id not in ready_ids


async def test_delete_dependency_via_api(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "Task A"})
    dependency_resp = await client.post("/api/v1/tasks", json={"title": "Task B"})
    task_id = task_resp.json()["id"]
    dependency_id = dependency_resp.json()["id"]

    create_dep_resp = await client.post(
        f"/api/v1/tasks/{task_id}/dependencies",
        json={"depends_on_task_id": dependency_id},
    )
    dependency_link_id = create_dep_resp.json()["id"]

    delete_resp = await client.delete(
        f"/api/v1/tasks/{task_id}/dependencies/{dependency_link_id}"
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_count"] == 1


async def test_add_comment_and_get_timeline_via_api(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "Task A"})
    task_id = task_resp.json()["id"]

    comment_resp = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"type": "progress", "content": "Started working"},
    )
    assert comment_resp.status_code == 201

    timeline_resp = await client.get(f"/api/v1/tasks/{task_id}/timeline")
    assert timeline_resp.status_code == 200
    contents = [item["content"] for item in timeline_resp.json()["comments"]]
    assert "Started working" in contents


async def test_add_comment_with_event_type_is_rejected(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "Task A"})
    task_id = task_resp.json()["id"]

    comment_resp = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"type": "event", "content": "Forged event"},
    )
    assert comment_resp.status_code == 400
    assert comment_resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_workspace_views_via_api(client: AsyncClient):
    now = datetime.now(timezone.utc)
    today_due = now.replace(hour=12, minute=0, second=0, microsecond=0)
    overdue_due = today_due - timedelta(days=1)
    await client.post(
        "/api/v1/tasks",
        json={"title": "Today", "due_at": today_due.isoformat()},
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Overdue", "due_at": overdue_due.isoformat()},
    )
    await client.post("/api/v1/tasks", json={"title": "Blocked", "status": "blocked"})

    today_resp = await client.get("/api/v1/workspace/today")
    overdue_resp = await client.get("/api/v1/workspace/overdue")
    blocked_resp = await client.get("/api/v1/workspace/blocked")
    alerts_resp = await client.get("/api/v1/workspace/alerts")

    assert today_resp.status_code == 200
    assert overdue_resp.status_code == 200
    assert blocked_resp.status_code == 200
    assert alerts_resp.status_code == 200
    assert any(task["title"] == "Today" for task in today_resp.json()["tasks"])
    assert any(task["title"] == "Overdue" for task in overdue_resp.json()["tasks"])
    assert any(task["title"] == "Blocked" for task in blocked_resp.json()["tasks"])
    assert alerts_resp.json()["total"] >= 2


async def test_workspace_dashboard_via_api(client: AsyncClient):
    await client.post("/api/v1/tasks", json={"title": "Ready"})
    await client.post("/api/v1/tasks", json={"title": "Blocked", "status": "blocked"})

    resp = await client.get("/api/v1/workspace/dashboard")

    assert resp.status_code == 200
    data = resp.json()
    assert "today" in data
    assert "blocked" in data
    assert "ready_to_start" in data
    assert "alerts" in data
    assert "suggested_today" in data
    assert "stale_tasks" in data


async def test_suggested_today_and_stale_via_api(client: AsyncClient):
    overdue_due = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await client.post("/api/v1/tasks", json={"title": "Urgent", "priority": 1, "due_at": overdue_due})

    suggested_resp = await client.get("/api/v1/workspace/suggested-today")
    stale_resp = await client.get("/api/v1/workspace/stale")

    assert suggested_resp.status_code == 200
    assert stale_resp.status_code == 200
    assert suggested_resp.json()["total"] >= 1


class FakeNotificationProvider:
    def __init__(self, channel: str = "webhook"):
        self.channel = channel
        self.messages: list[tuple[str, dict]] = []

    async def send(self, message: str, payload: dict) -> None:
        self.messages.append((message, payload))


async def test_workspace_today_uses_configured_timezone_via_api(
    shanghai_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(task_service_module, "datetime", FrozenDateTime)
    await shanghai_client.post(
        "/api/v1/tasks",
        json={
            "title": "Shanghai today",
            "due_at": datetime(2026, 4, 6, 0, 30, tzinfo=timezone.utc).isoformat(),
        },
    )

    today_resp = await shanghai_client.get("/api/v1/workspace/today")

    assert today_resp.status_code == 200
    assert any(task["title"] == "Shanghai today" for task in today_resp.json()["tasks"])


async def test_decompose_suggestions_and_apply_via_api(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "发布项目版本"})
    task_id = task_resp.json()["id"]

    suggest_resp = await client.get(f"/api/v1/tasks/{task_id}/decompose/suggestions")
    assert suggest_resp.status_code == 200
    suggestions = suggest_resp.json()["suggestions"]
    assert len(suggestions) >= 3
    assert suggestions[1]["depends_on_indices"] == [0]
    assert suggestions[2]["depends_on_indices"] == [1]

    apply_resp = await client.post(
        f"/api/v1/tasks/{task_id}/decompose/apply-suggestions",
        json={"indices": [0, 1]},
    )
    assert apply_resp.status_code == 200
    sub_tasks = apply_resp.json()["sub_tasks"]
    assert len(sub_tasks) == 2

    dependencies_resp = await client.get(
        f"/api/v1/tasks/{sub_tasks[1]['id']}/dependencies"
    )
    assert dependencies_resp.status_code == 200
    dependency_ids = {
        item["depends_on_task_id"] for item in dependencies_resp.json()["dependencies"]
    }
    assert sub_tasks[0]["id"] in dependency_ids


async def test_generate_and_apply_plan_via_api(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "写项目报告"})
    task_id = task_resp.json()["id"]

    plan_resp = await client.post(f"/api/v1/tasks/{task_id}/plan")
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    assert plan["goal"] == "写项目报告"
    assert len(plan["suggestions"]) >= 3

    apply_resp = await client.post(
        f"/api/v1/tasks/{task_id}/apply-plan",
        json={"indices": [0, 1]},
    )
    assert apply_resp.status_code == 200
    assert len(apply_resp.json()["sub_tasks"]) == 2


async def test_apply_suggestions_with_invalid_index_returns_validation_error(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "发布项目版本"})
    task_id = task_resp.json()["id"]

    apply_resp = await client.post(
        f"/api/v1/tasks/{task_id}/decompose/apply-suggestions",
        json={"indices": [99]},
    )
    assert apply_resp.status_code == 400
    assert apply_resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_scan_reminders_via_api(client: AsyncClient):
    now = datetime.now(timezone.utc)
    await client.post(
        "/api/v1/tasks",
        json={"title": "Overdue", "due_at": (now - timedelta(days=1)).isoformat()},
    )

    scan_resp = await client.post("/api/v1/reminders/scan")
    assert scan_resp.status_code == 200
    assert scan_resp.json()["total"] >= 1
    assert scan_resp.json()["alerts"][0]["reason"] in {"overdue", "due_soon", "blocked"}


async def test_dispatch_alerts_via_api(client: AsyncClient, db_session):
    now = datetime.now(timezone.utc)
    await client.post(
        "/api/v1/tasks",
        json={"title": "Overdue", "due_at": (now - timedelta(days=1)).isoformat()},
    )

    fake_provider = FakeNotificationProvider()

    async def _override_alert_delivery_service():
        task_service = TaskService(
            session=db_session,
            embedding_service=None,
            is_postgres=False,
            timezone_name="UTC",
        )
        return AlertDeliveryService(
            task_service=task_service,
            providers={"webhook": fake_provider},
            repeat_window_hours=6,
        )

    app.dependency_overrides[get_alert_delivery_service] = _override_alert_delivery_service
    try:
        resp = await client.post("/api/v1/notifications/dispatch-alerts", json={"top_n": 10})
    finally:
        app.dependency_overrides.pop(get_alert_delivery_service, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sent_count"] >= 1
    assert len(fake_provider.messages) == data["sent_count"]


async def test_notification_test_via_api(client: AsyncClient, db_session):
    fake_provider = FakeNotificationProvider(channel="dingtalk")

    async def _override_alert_delivery_service():
        task_service = TaskService(
            session=db_session,
            embedding_service=None,
            is_postgres=False,
            timezone_name="UTC",
        )
        return AlertDeliveryService(
            task_service=task_service,
            providers={"dingtalk": fake_provider},
            repeat_window_hours=6,
        )

    app.dependency_overrides[get_alert_delivery_service] = _override_alert_delivery_service
    try:
        resp = await client.post(
            "/api/v1/notifications/test",
            json={"channel": "dingtalk", "message": "hello"},
        )
    finally:
        app.dependency_overrides.pop(get_alert_delivery_service, None)

    assert resp.status_code == 200
    assert resp.json()["channel"] == "dingtalk"
    assert fake_provider.messages[0][0] == "hello"


async def test_recovery_suggestions_and_review_summary_via_api(client: AsyncClient):
    blocked_resp = await client.post("/api/v1/tasks", json={"title": "Blocked", "status": "blocked"})
    task_id = blocked_resp.json()["id"]

    recovery_resp = await client.get(f"/api/v1/tasks/{task_id}/recovery-suggestions")
    assert recovery_resp.status_code == 200
    assert recovery_resp.json()["summary"]

    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(days=1)
    review_resp = await client.get(
        "/api/v1/reviews/summary",
        params={
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        },
    )
    assert review_resp.status_code == 200
    assert "created_count" in review_resp.json()


async def test_unauthorized(client: AsyncClient):
    async_client = client
    resp = await async_client.get(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


async def test_missing_auth(client: AsyncClient):
    resp = await client.get(
        "/api/v1/tasks",
        headers={"Authorization": ""},
    )
    assert resp.status_code == 401


async def test_task_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"
