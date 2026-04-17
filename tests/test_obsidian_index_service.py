import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from app.api.deps import get_obsidian_index_service
from app.config import Settings
from app.services.obsidian_index_service import ObsidianIndexService
from app.services.obsidian_markdown_parser import ObsidianMarkdownParser
from app.services.obsidian_sync_service import ObsidianFileListResult, ObsidianFileMetadata, ObsidianFileWriteResult
from main import app

pytestmark = pytest.mark.asyncio


def markdown(task_id: str, dependency_id: str | None = None) -> str:
    dep_block = f"depends_on:\n  - {dependency_id}" if dependency_id else "depends_on: []"
    dep_body = f"- [[AI-Todo/tasks/{dependency_id}.md]]" if dependency_id else "- 无"
    return f"""---
source: ai-todo
schema_version: 1
aitodo_id: {task_id}
status: in_progress
priority: 2
due_at: 2026-04-20T10:00:00+00:00
parent_id:
tags:
  - obsidian
  - sync
{dep_block}
updated_at: 2026-04-15T08:00:00+00:00
---

# 索引任务

这是从 Obsidian Markdown 解析出的任务。

## 依赖

{dep_body}
"""


@dataclass
class FakeIndexClient:
    files: list[ObsidianFileMetadata]
    objects: dict[str, bytes]

    async def list_files(self, *, vault_id: str, prefix: str, limit: int = 200, cursor: str | None = None):
        return ObsidianFileListResult(checkpoint="cp_7", items=self.files, next_cursor=None)

    async def download_object(self, *, vault_id: str, content_hash: str) -> bytes:
        return self.objects[content_hash]

    async def put_file(self, *, vault_id: str, path: str, content: bytes, base_version: int | None, idempotency_key: str):
        return ObsidianFileWriteResult(
            file_id="unused",
            path=path,
            version=1,
            content_hash="sha256:" + "c" * 64,
            checkpoint="cp_1",
            changeset_id="unused",
            op="create",
        )


def build_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key="test-key",
        obsidian_sync_vault_id="vault-1",
        obsidian_sync_base_url="http://obsidian.test/api/v1",
    )


async def test_markdown_parser_extracts_task_fields():
    task_id = str(uuid.uuid4())
    dep_id = str(uuid.uuid4())
    parsed = ObsidianMarkdownParser().parse_task(markdown(task_id, dep_id))

    assert parsed is not None
    assert parsed.task_id == task_id
    assert parsed.title == "索引任务"
    assert parsed.description == "这是从 Obsidian Markdown 解析出的任务。"
    assert parsed.status == "in_progress"
    assert parsed.priority == 2
    assert parsed.tags == ["obsidian", "sync"]
    assert parsed.depends_on == [dep_id]
    assert parsed.due_at is not None


async def test_index_service_rebuilds_index_from_remote_markdown(db_session):
    task_id = str(uuid.uuid4())
    content_hash = "sha256:" + "d" * 64
    fake_client = FakeIndexClient(
        files=[
            ObsidianFileMetadata(
                file_id="obs-file-1",
                path=f"AI-Todo/tasks/{task_id}.md",
                version=4,
                content_hash=content_hash,
                deleted=False,
            )
        ],
        objects={content_hash: markdown(task_id).encode("utf-8")},
    )
    svc = ObsidianIndexService(session=db_session, settings=build_settings(), client=fake_client)

    result = await svc.rebuild_index()

    assert result["checkpoint"] == "cp_7"
    assert result["scanned"] == 1
    assert result["indexed"] == 1
    indexed = await svc.list_indexed_tasks()
    assert len(indexed) == 1
    assert indexed[0].task_id == task_id
    assert indexed[0].title == "索引任务"
    assert indexed[0].version == 4


async def test_index_rebuild_api_uses_service_override(client: AsyncClient):
    class FakeIndexService:
        async def rebuild_index(self, *, prefix: str = "AI-Todo/tasks/", limit: int = 500):
            return {
                "vault_id": "vault-1",
                "checkpoint": "cp_1",
                "scanned": 1,
                "indexed": 1,
                "skipped": 0,
                "errors": [],
            }

        async def list_indexed_tasks(self, *, status: str | None = None, limit: int = 100):
            return []

    async def override_index_service():
        return FakeIndexService()

    app.dependency_overrides[get_obsidian_index_service] = override_index_service
    try:
        resp = await client.post("/api/v1/obsidian-sync/index/rebuild", json={"limit": 10})
        assert resp.status_code == 200
        assert resp.json()["indexed"] == 1
    finally:
        app.dependency_overrides.pop(get_obsidian_index_service, None)
