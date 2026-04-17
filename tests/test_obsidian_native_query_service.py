from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import AsyncClient

from app.config import Settings, get_settings
from app.models import ObsidianTaskIndex
from main import app

pytestmark = pytest.mark.asyncio


def native_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key="test-key",
        app_version="1.1.0-test",
        parsing_timezone="UTC",
        aitodo_storage_mode="obsidian_native",
    )


async def seed_index(db_session):
    now = datetime.now(timezone.utc)
    done_id = str(uuid.uuid4())
    ready_id = str(uuid.uuid4())
    blocked_id = str(uuid.uuid4())
    overdue_id = str(uuid.uuid4())
    explicit_blocked_id = str(uuid.uuid4())
    stale_id = str(uuid.uuid4())
    db_session.add_all([
        ObsidianTaskIndex(
            task_id=done_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{done_id}.md",
            file_id="file-done",
            version=1,
            content_hash="sha256:" + "1" * 64,
            title="已完成依赖",
            description="done dependency",
            status="done",
            priority=5,
            due_at=None,
            tags=["obsidian"],
            parent_id=None,
            depends_on=[],
            source_updated_at=now - timedelta(days=1),
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),
        ObsidianTaskIndex(
            task_id=ready_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{ready_id}.md",
            file_id="file-ready",
            version=2,
            content_hash="sha256:" + "2" * 64,
            title="Native ready task",
            description="from markdown index",
            status="todo",
            priority=1,
            due_at=now,
            tags=["obsidian", "sync"],
            parent_id=None,
            depends_on=[done_id],
            source_updated_at=now - timedelta(hours=3),
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),

        ObsidianTaskIndex(
            task_id=overdue_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{overdue_id}.md",
            file_id="file-overdue",
            version=1,
            content_hash="sha256:" + "4" * 64,
            title="Overdue native",
            description="late",
            status="todo",
            priority=1,
            due_at=now - timedelta(days=1),
            tags=["obsidian"],
            parent_id=None,
            depends_on=[],
            source_updated_at=now - timedelta(days=2),
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),
        ObsidianTaskIndex(
            task_id=explicit_blocked_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{explicit_blocked_id}.md",
            file_id="file-explicit-blocked",
            version=1,
            content_hash="sha256:" + "5" * 64,
            title="Explicit blocked",
            description="blocked",
            status="blocked",
            priority=2,
            due_at=None,
            tags=["obsidian"],
            parent_id=None,
            depends_on=[],
            source_updated_at=now - timedelta(hours=5),
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),
        ObsidianTaskIndex(
            task_id=stale_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{stale_id}.md",
            file_id="file-stale",
            version=1,
            content_hash="sha256:" + "6" * 64,
            title="Stale native",
            description="stale",
            status="in_progress",
            priority=3,
            due_at=None,
            tags=["obsidian"],
            parent_id=None,
            depends_on=[],
            source_updated_at=now - timedelta(days=3),
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),
        ObsidianTaskIndex(
            task_id=blocked_id,
            vault_id="vault-1",
            path=f"AI-Todo/tasks/{blocked_id}.md",
            file_id="file-blocked",
            version=1,
            content_hash="sha256:" + "3" * 64,
            title="Blocked by ready",
            description="not ready yet",
            status="todo",
            priority=2,
            due_at=None,
            tags=["obsidian"],
            parent_id=None,
            depends_on=[ready_id],
            source_updated_at=now,
            parsed_at=now,
            meta_data={"schema_version": 1},
        ),
    ])
    await db_session.commit()
    return {"done_id": done_id, "ready_id": ready_id, "blocked_id": blocked_id, "overdue_id": overdue_id, "explicit_blocked_id": explicit_blocked_id, "stale_id": stale_id}


async def test_tasks_read_from_obsidian_native_index(client: AsyncClient, db_session):
    ids = await seed_index(db_session)
    app.dependency_overrides[get_settings] = native_settings
    try:
        list_resp = await client.get("/api/v1/tasks", params={"status_filter": "open", "tags": ["sync"]})
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] == 1
        assert list_data["tasks"][0]["id"] == ids["ready_id"]
        assert list_data["tasks"][0]["meta_data"]["source"] == "obsidian_native_index"

        get_resp = await client.get(f"/api/v1/tasks/{ids['ready_id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Native ready task"
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_ready_and_suggested_today_use_obsidian_native_index(client: AsyncClient, db_session):
    ids = await seed_index(db_session)
    app.dependency_overrides[get_settings] = native_settings
    try:
        ready_resp = await client.get("/api/v1/workspace/ready-to-start")
        assert ready_resp.status_code == 200
        ready_ids = {item["id"] for item in ready_resp.json()["tasks"]}
        assert ids["ready_id"] in ready_ids
        assert ids["blocked_id"] not in ready_ids

        suggested_resp = await client.get("/api/v1/workspace/suggested-today")
        assert suggested_resp.status_code == 200
        suggested = suggested_resp.json()["tasks"]
        assert suggested
        suggested_ids = {item["task"]["id"] for item in suggested}
        assert ids["ready_id"] in suggested_ids
        assert any("priority_1" in item["reasons"] for item in suggested)
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_workspace_native_endpoints(client: AsyncClient, db_session):
    ids = await seed_index(db_session)
    app.dependency_overrides[get_settings] = native_settings
    try:
        today_resp = await client.get("/api/v1/workspace/today")
        assert today_resp.status_code == 200
        today_ids = {item["id"] for item in today_resp.json()["tasks"]}
        assert ids["ready_id"] in today_ids

        overdue_resp = await client.get("/api/v1/workspace/overdue")
        assert overdue_resp.status_code == 200
        overdue_ids = {item["id"] for item in overdue_resp.json()["tasks"]}
        assert ids["overdue_id"] in overdue_ids

        blocked_resp = await client.get("/api/v1/workspace/blocked")
        assert blocked_resp.status_code == 200
        blocked_ids = {item["id"] for item in blocked_resp.json()["tasks"]}
        assert ids["explicit_blocked_id"] in blocked_ids

        stale_resp = await client.get("/api/v1/workspace/stale")
        assert stale_resp.status_code == 200
        stale_ids = {item["id"] for item in stale_resp.json()["tasks"]}
        assert ids["stale_id"] in stale_ids

        recent_resp = await client.get("/api/v1/workspace/recently-updated")
        assert recent_resp.status_code == 200
        assert recent_resp.json()["tasks"]

        alerts_resp = await client.get("/api/v1/workspace/alerts")
        assert alerts_resp.status_code == 200
        alert_reasons = {item["reason"] for item in alerts_resp.json()["alerts"]}
        assert "overdue" in alert_reasons
        assert "blocked" in alert_reasons

        dashboard_resp = await client.get("/api/v1/workspace/dashboard")
        assert dashboard_resp.status_code == 200
        dashboard = dashboard_resp.json()
        assert dashboard["today"]["tasks"]
        assert dashboard["overdue"]["tasks"]
        assert dashboard["ready_to_start"]["tasks"]
        assert dashboard["suggested_today"]["tasks"]
        assert dashboard["stale_tasks"]["tasks"]
    finally:
        app.dependency_overrides.pop(get_settings, None)
