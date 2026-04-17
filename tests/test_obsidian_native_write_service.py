from dataclasses import dataclass
import uuid

import pytest
from httpx import AsyncClient

from app.api.deps import get_obsidian_native_write_service
from app.config import Settings, get_settings
from app.schemas import TaskCommentCreate, TaskCreate, TaskUpdate
from app.services.obsidian_native_write_service import ObsidianNativeTaskWriteService
from app.services.obsidian_sync_service import ObsidianFileListResult, ObsidianFileWriteResult
from main import app

pytestmark = pytest.mark.asyncio


@dataclass
class FakeWriteClient:
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
            content_hash="sha256:" + "e" * 64,
            checkpoint="cp_1",
            changeset_id="changeset-1",
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
        app_version="1.1.0-test",
        obsidian_sync_vault_id="vault-1",
        obsidian_sync_base_url="http://obsidian.test/api/v1",
        aitodo_storage_mode="obsidian_native",
    )


async def test_native_write_service_creates_and_updates_markdown_task(db_session):
    fake = FakeWriteClient(calls=[])
    svc = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake)

    created = await svc.create_task(TaskCreate(title="Native create", description="写入 Obsidian", priority=2, tags=["native"]))
    assert created.title == "Native create"
    assert created.meta_data["source"] == "obsidian_native_index"
    assert created.meta_data["version"] == 1
    assert fake.calls[0]["base_version"] is None
    assert fake.calls[0]["path"].startswith("AI-Todo/待办任务/")
    assert fake.calls[0]["path"].endswith(".md")
    assert "# Native create" in fake.calls[0]["content"]
    assert "source: ai-todo" in fake.calls[0]["content"]

    updated = await svc.update_task(created.id, TaskUpdate(title="Native updated", status="in_progress"))
    assert updated.title == "Native updated"
    assert updated.status == "in_progress"
    assert updated.meta_data["version"] == 2
    assert fake.calls[1]["base_version"] == 1
    assert "status: in_progress" in fake.calls[1]["content"]


async def test_native_mode_routes_create_and_update_via_native_write_service(client: AsyncClient):
    class FakeNativeWriteService:
        def __init__(self):
            self.task_id = uuid.uuid4()

        async def create_task(self, data: TaskCreate):
            return {
                "id": self.task_id,
                "title": data.title,
                "description": data.description,
                "status": data.status or "todo",
                "priority": data.priority,
                "due_at": data.due_at,
                "parent_id": data.parent_id,
                "tags": data.tags,
                "meta_data": {"source": "obsidian_native_index"},
                "created_at": "2026-04-15T00:00:00+00:00",
                "updated_at": "2026-04-15T00:00:00+00:00",
                "children": [],
            }

        async def update_task(self, task_id: uuid.UUID, data: TaskUpdate):
            return {
                "id": task_id,
                "title": data.title or "updated",
                "description": data.description,
                "status": data.status or "todo",
                "priority": data.priority or 3,
                "due_at": data.due_at,
                "parent_id": data.parent_id,
                "tags": data.tags or [],
                "meta_data": {"source": "obsidian_native_index"},
                "created_at": "2026-04-15T00:00:00+00:00",
                "updated_at": "2026-04-15T00:00:00+00:00",
                "children": [],
            }

    fake_service = FakeNativeWriteService()

    async def override_settings():
        return native_settings()

    async def override_write_service():
        return fake_service

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_write_service] = override_write_service
    try:
        create_resp = await client.post("/api/v1/tasks", json={"title": "Create native"})
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["meta_data"]["source"] == "obsidian_native_index"

        update_resp = await client.patch(f"/api/v1/tasks/{created['id']}", json={"title": "Updated native", "status": "in_progress"})
        assert update_resp.status_code == 200
        assert update_resp.json()["title"] == "Updated native"
        assert update_resp.json()["status"] == "in_progress"
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_write_service, None)


async def test_native_delete_archives_task_without_remote_delete(db_session):
    fake = FakeWriteClient(calls=[])
    svc = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake)
    created = await svc.create_task(TaskCreate(title="Archive me"))

    deleted_count = await svc.archive_task(created.id)

    assert deleted_count == 1
    assert len(fake.calls) == 2
    assert fake.calls[1]["base_version"] == 1
    assert "status: archived" in fake.calls[1]["content"]
    assert "archived_at:" in fake.calls[1]["content"]


async def test_native_mode_delete_route_archives(client: AsyncClient):
    class FakeNativeWriteService:
        async def create_task(self, data: TaskCreate):
            raise AssertionError("not used")

        async def update_task(self, task_id: uuid.UUID, data: TaskUpdate):
            raise AssertionError("not used")

        async def archive_task(self, task_id: uuid.UUID):
            return 1

    async def override_settings():
        return native_settings()

    async def override_write_service():
        return FakeNativeWriteService()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_write_service] = override_write_service
    try:
        resp = await client.delete(f"/api/v1/tasks/{uuid.uuid4()}")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 1
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_write_service, None)


async def test_native_dependencies_update_markdown_and_index(db_session):
    fake = FakeWriteClient(calls=[])
    svc = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake)
    dependency = await svc.create_task(TaskCreate(title="Dependency"))
    task = await svc.create_task(TaskCreate(title="Dependent"))

    created = await svc.add_dependency(task.id, dependency.id)
    assert created.task_id == task.id
    assert created.depends_on_task_id == dependency.id
    assert fake.calls[-1]["base_version"] == 1
    assert str(dependency.id) in fake.calls[-1]["content"]

    listed = await svc.list_dependencies(task.id)
    assert len(listed.dependencies) == 1
    assert listed.dependencies[0].depends_on_task_id == dependency.id

    removed = await svc.remove_dependency(task.id, created.id)
    assert removed.deleted_count == 1
    assert str(dependency.id) not in fake.calls[-1]["content"]
    listed_after = await svc.list_dependencies(task.id)
    assert listed_after.dependencies == []


async def test_native_mode_dependency_routes(client: AsyncClient):
    dep_id = uuid.uuid4()

    class FakeNativeWriteService:
        async def create_task(self, data: TaskCreate):
            raise AssertionError("not used")

        async def update_task(self, task_id: uuid.UUID, data: TaskUpdate):
            raise AssertionError("not used")

        async def archive_task(self, task_id: uuid.UUID):
            raise AssertionError("not used")

        async def add_dependency(self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID):
            return {
                "id": dep_id,
                "task_id": task_id,
                "depends_on_task_id": depends_on_task_id,
                "created_at": "2026-04-15T00:00:00+00:00",
            }

        async def list_dependencies(self, task_id: uuid.UUID):
            return {
                "dependencies": [
                    {
                        "id": dep_id,
                        "task_id": task_id,
                        "depends_on_task_id": uuid.uuid4(),
                        "created_at": "2026-04-15T00:00:00+00:00",
                    }
                ]
            }

        async def remove_dependency(self, task_id: uuid.UUID, dependency_id: uuid.UUID):
            return {"deleted_count": 1}

    async def override_settings():
        return native_settings()

    async def override_write_service():
        return FakeNativeWriteService()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_write_service] = override_write_service
    try:
        task_id = uuid.uuid4()
        add_resp = await client.post(
            f"/api/v1/tasks/{task_id}/dependencies",
            json={"depends_on_task_id": str(uuid.uuid4())},
        )
        assert add_resp.status_code == 201
        assert add_resp.json()["id"] == str(dep_id)

        list_resp = await client.get(f"/api/v1/tasks/{task_id}/dependencies")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["dependencies"]) == 1

        delete_resp = await client.delete(f"/api/v1/tasks/{task_id}/dependencies/{dep_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted_count"] == 1
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_write_service, None)


async def test_native_comments_update_timeline(db_session):
    fake = FakeWriteClient(calls=[])
    svc = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake)
    task = await svc.create_task(TaskCreate(title="Commented"))

    comment = await svc.add_comment(task.id, TaskCommentCreate(type="progress", content="已推进", meta_data={"step": 1}))

    assert comment.task_id == task.id
    assert comment.type == "progress"
    assert comment.content == "已推进"
    assert fake.calls[-1]["base_version"] == 1
    assert "## 时间线" in fake.calls[-1]["content"]
    assert "[progress] 已推进" in fake.calls[-1]["content"]

    timeline = await svc.list_comments(task.id)
    assert len(timeline.comments) == 1
    assert timeline.comments[0].id == comment.id
    assert timeline.comments[0].meta_data == {"step": 1}


async def test_native_mode_comment_routes(client: AsyncClient):
    comment_id = uuid.uuid4()

    class FakeNativeWriteService:
        async def create_task(self, data: TaskCreate):
            raise AssertionError("not used")

        async def update_task(self, task_id: uuid.UUID, data: TaskUpdate):
            raise AssertionError("not used")

        async def archive_task(self, task_id: uuid.UUID):
            raise AssertionError("not used")

        async def add_dependency(self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID):
            raise AssertionError("not used")

        async def list_dependencies(self, task_id: uuid.UUID):
            raise AssertionError("not used")

        async def remove_dependency(self, task_id: uuid.UUID, dependency_id: uuid.UUID):
            raise AssertionError("not used")

        async def add_comment(self, task_id: uuid.UUID, data: TaskCommentCreate):
            return {
                "id": comment_id,
                "task_id": task_id,
                "type": data.type,
                "content": data.content,
                "meta_data": data.meta_data or {},
                "created_at": "2026-04-15T00:00:00+00:00",
            }

        async def list_comments(self, task_id: uuid.UUID):
            return {
                "comments": [
                    {
                        "id": comment_id,
                        "task_id": task_id,
                        "type": "comment",
                        "content": "hello",
                        "meta_data": {},
                        "created_at": "2026-04-15T00:00:00+00:00",
                    }
                ]
            }

    async def override_settings():
        return native_settings()

    async def override_write_service():
        return FakeNativeWriteService()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_write_service] = override_write_service
    try:
        task_id = uuid.uuid4()
        add_resp = await client.post(
            f"/api/v1/tasks/{task_id}/comments",
            json={"type": "comment", "content": "hello"},
        )
        assert add_resp.status_code == 201
        assert add_resp.json()["id"] == str(comment_id)

        list_resp = await client.get(f"/api/v1/tasks/{task_id}/timeline")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["comments"]) == 1
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_write_service, None)
