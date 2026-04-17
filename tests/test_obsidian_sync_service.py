import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from app.api.deps import get_obsidian_export_service
from app.config import Settings
from app.schemas import TaskCommentCreate, TaskCreate
from app.services.obsidian_sync_service import ObsidianExportService, ObsidianFileWriteResult
from app.services.task_service import TaskService
from main import app

pytestmark = pytest.mark.asyncio


@dataclass
class FakeObsidianClient:
    calls: list

    async def put_file(self, *, vault_id: str, path: str, content: bytes, base_version: int | None, idempotency_key: str):
        self.calls.append({
            "vault_id": vault_id,
            "path": path,
            "content": content.decode("utf-8"),
            "base_version": base_version,
            "idempotency_key": idempotency_key,
        })
        return ObsidianFileWriteResult(
            file_id="obs-file-1",
            path=path,
            version=1 if base_version is None else base_version + 1,
            content_hash="sha256:" + "a" * 64,
            checkpoint="cp_1",
            changeset_id="changeset-1",
            op="create" if base_version is None else "update",
        )


def build_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key="test-key",
        obsidian_sync_vault_id="vault-1",
        obsidian_sync_base_url="http://obsidian.test/api/v1",
    )


async def test_export_task_renders_markdown_and_persists_binding(db_session):
    task_service = TaskService(session=db_session, embedding_service=None, is_postgres=False)
    task = await task_service.upsert_task(
        data=TaskCreate(
            title="同步到 Obsidian",
            description="把任务导出为 Markdown",
            priority=2,
            tags=["obsidian", "sync"],
        )
    )
    await task_service.add_comment(task.id, data=TaskCommentCreate(type="progress", content="准备导出"))

    fake_client = FakeObsidianClient(calls=[])
    svc = ObsidianExportService(session=db_session, settings=build_settings(), client=fake_client)
    result = await svc.export_task(task.id)

    assert result["path"].startswith("AI-Todo/待办任务/")
    assert result["path"].endswith(".md")
    assert result["file_id"] == "obs-file-1"
    assert result["version"] == 1
    assert fake_client.calls
    content = fake_client.calls[0]["content"]
    assert "source: ai-todo" in content
    assert f"aitodo_id: {task.id}" in content
    assert "# 同步到 Obsidian" in content
    assert "把任务导出为 Markdown" in content

    bindings = await svc.list_bindings(entity_type="task")
    assert len(bindings) == 1
    assert bindings[0].entity_id == str(task.id)
    assert bindings[0].content_hash == "sha256:" + "a" * 64


async def test_export_task_reuses_binding_version_on_update(db_session):
    task_service = TaskService(session=db_session, embedding_service=None, is_postgres=False)
    task = await task_service.upsert_task(data=TaskCreate(title="重复导出"))
    fake_client = FakeObsidianClient(calls=[])
    svc = ObsidianExportService(session=db_session, settings=build_settings(), client=fake_client)

    first = await svc.export_task(task.id)
    second = await svc.export_task(task.id)

    assert first["version"] == 1
    assert second["version"] == 2
    assert fake_client.calls[1]["base_version"] == 1


async def test_export_task_api_uses_export_service_override(client: AsyncClient):
    task_resp = await client.post("/api/v1/tasks", json={"title": "API export"})
    task_id = task_resp.json()["id"]

    class FakeExportService:
        async def export_task(self, task_id_arg: uuid.UUID):
            return {
                "entity_type": "task",
                "entity_id": str(task_id_arg),
                "vault_id": "vault-1",
                "path": f"AI-Todo/待办任务/2026-04-15 00-00-00-000.md",
                "file_id": "obs-file-1",
                "version": 1,
                "content_hash": "sha256:" + "b" * 64,
                "checkpoint": "cp_1",
                "op": "create",
                "exported_at": None,
            }

        async def export_all_tasks(self, limit: int = 100):
            return {"exported_count": 0, "items": []}

        async def list_bindings(self, entity_type: str | None = None):
            return []

    async def override_export_service():
        return FakeExportService()

    app.dependency_overrides[get_obsidian_export_service] = override_export_service
    try:
        resp = await client.post(f"/api/v1/obsidian-sync/tasks/{task_id}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == task_id
        assert data["path"].startswith("AI-Todo/待办任务/")
    finally:
        app.dependency_overrides.pop(get_obsidian_export_service, None)
