from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

import pytest
from httpx import AsyncClient

from app.api.deps import get_obsidian_native_planning_service
from app.config import Settings, get_settings
from app.models import ObsidianTaskIndex
from app.services.obsidian_native_planning_service import ObsidianNativeTaskPlanningService
from app.services.obsidian_native_query_service import ObsidianNativeTaskQueryService
from app.services.obsidian_native_write_service import ObsidianNativeTaskWriteService
from app.services.obsidian_sync_service import ObsidianFileListResult, ObsidianFileWriteResult
from main import app

pytestmark = pytest.mark.asyncio


@dataclass
class FakeWriteClient:
    calls: list

    async def put_file(self, *, vault_id: str, path: str, content: bytes, base_version: int | None, idempotency_key: str):
        self.calls.append({"path": path, "content": content.decode("utf-8"), "base_version": base_version})
        return ObsidianFileWriteResult(
            file_id=f"file-{len(self.calls)}",
            path=path,
            version=1 if base_version is None else base_version + 1,
            content_hash="sha256:" + str(len(self.calls)) * 64,
            checkpoint=f"cp_{len(self.calls)}",
            changeset_id=f"changeset-{len(self.calls)}",
            op="create" if base_version is None else "update",
        )

    async def list_files(self, *, vault_id: str, prefix: str, limit: int = 200, cursor: str | None = None):
        return ObsidianFileListResult(checkpoint="cp_0", items=[], next_cursor=None)

    async def download_object(self, *, vault_id: str, content_hash: str) -> bytes:
        return b""


def native_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key="test-key",
        obsidian_sync_vault_id="vault-1",
        obsidian_sync_base_url="http://obsidian.test/api/v1",
        aitodo_storage_mode="obsidian_native",
    )


async def seed_parent(db_session, title="准备发布版本") -> uuid.UUID:
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db_session.add(ObsidianTaskIndex(
        task_id=task_id,
        vault_id="vault-1",
        path=f"AI-Todo/tasks/{task_id}.md",
        file_id="parent-file",
        version=1,
        content_hash="sha256:" + "a" * 64,
        title=title,
        description="deployment task",
        status="todo",
        priority=1,
        due_at=None,
        tags=["release"],
        parent_id=None,
        depends_on=[],
        source_updated_at=now,
        parsed_at=now,
        meta_data={"schema_version": 1},
    ))
    await db_session.commit()
    return uuid.UUID(task_id)


async def test_native_plan_and_apply_creates_markdown_subtasks(db_session):
    parent_id = await seed_parent(db_session)
    fake = FakeWriteClient(calls=[])
    query = ObsidianNativeTaskQueryService(session=db_session)
    write = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake)
    svc = ObsidianNativeTaskPlanningService(query_service=query, write_service=write)

    plan = await svc.generate_plan(parent_id)
    assert plan.goal == "准备发布版本"
    assert len(plan.suggestions) == 3
    assert plan.suggestions[1].depends_on_indices == [0]

    result = await svc.apply_plan(parent_id, indices=[0, 1])
    assert result.parent_task.id == parent_id
    assert len(result.sub_tasks) == 2
    assert result.sub_tasks[0].parent_id == parent_id
    assert result.sub_tasks[1].parent_id == parent_id
    # two creates + one dependency rewrite
    assert len(fake.calls) == 3
    assert str(result.sub_tasks[0].id) in fake.calls[-1]["content"]


async def test_native_plan_routes_use_native_service(client: AsyncClient):
    class FakeNativePlanningService:
        async def generate_plan(self, task_id: uuid.UUID):
            return {
                "task_id": task_id,
                "goal": "native plan",
                "suggestions": [],
                "risks": [],
                "assumptions": [],
            }

        async def apply_plan(self, task_id: uuid.UUID, indices=None):
            return {
                "parent_task": {
                    "id": task_id,
                    "title": "native plan",
                    "description": None,
                    "status": "todo",
                    "priority": 3,
                    "due_at": None,
                    "parent_id": None,
                    "tags": [],
                    "meta_data": {"source": "obsidian_native_index"},
                    "created_at": "2026-04-15T00:00:00+00:00",
                    "updated_at": "2026-04-15T00:00:00+00:00",
                    "children": [],
                },
                "sub_tasks": [],
            }

        async def suggest_decomposition(self, task_id: uuid.UUID):
            return {"task_id": task_id, "suggestions": []}

    async def override_settings():
        return native_settings()

    async def override_planning():
        return FakeNativePlanningService()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_planning_service] = override_planning
    try:
        task_id = uuid.uuid4()
        plan_resp = await client.post(f"/api/v1/tasks/{task_id}/plan")
        assert plan_resp.status_code == 200
        assert plan_resp.json()["goal"] == "native plan"

        apply_resp = await client.post(f"/api/v1/tasks/{task_id}/apply-plan", json={"indices": []})
        assert apply_resp.status_code == 200
        assert apply_resp.json()["parent_task"]["id"] == str(task_id)
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_planning_service, None)
