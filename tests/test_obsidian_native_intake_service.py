from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from app.api.deps import get_obsidian_native_intake_service
from app.config import Settings, get_settings
from app.schemas import ParseTaskResponse, TaskDraft
from app.services.obsidian_native_intake_service import ObsidianNativeTaskIntakeService
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
            file_id="obs-file-1",
            path=path,
            version=1,
            content_hash="sha256:" + "7" * 64,
            checkpoint="cp_1",
            changeset_id="changeset-1",
            op="create",
        )

    async def list_files(self, *, vault_id: str, prefix: str, limit: int = 200, cursor: str | None = None):
        return ObsidianFileListResult(checkpoint="cp_0", items=[], next_cursor=None)

    async def download_object(self, *, vault_id: str, content_hash: str) -> bytes:
        return b""


class FakeParsingService:
    def __init__(self, confidence: float = 0.9):
        self.confidence = confidence

    async def parse_text(self, text: str):
        draft = TaskDraft(
            title="解析任务",
            description=text,
            priority=2,
            tags=["native"],
            meta_data={"parsed_by": "fake"},
        )
        return ParseTaskResponse(
            draft=draft,
            candidates=[draft],
            selected_index=0,
            confidence=self.confidence,
            source="fake",
            raw_text=text,
        )


def native_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        api_key="test-key",
        app_version="1.1.0-test",
        obsidian_sync_vault_id="vault-1",
        obsidian_sync_base_url="http://obsidian.test/api/v1",
        aitodo_storage_mode="obsidian_native",
    )


async def test_native_parse_and_create_writes_markdown(db_session):
    fake_client = FakeWriteClient(calls=[])
    write_service = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake_client)
    svc = ObsidianNativeTaskIntakeService(write_service=write_service, parsing_service=FakeParsingService())

    result = await svc.parse_and_create(text="明天写 Obsidian native 测试", force_create=True)

    assert result.created is True
    assert result.task is not None
    assert result.task.title == "解析任务"
    assert result.task.meta_data["parse_source"] == "fake"
    assert fake_client.calls
    assert "# 解析任务" in fake_client.calls[0]["content"]
    assert "parse_source" in result.task.meta_data


async def test_native_parse_and_create_respects_confidence_gate(db_session):
    fake_client = FakeWriteClient(calls=[])
    write_service = ObsidianNativeTaskWriteService(session=db_session, settings=native_settings(), client=fake_client)
    svc = ObsidianNativeTaskIntakeService(write_service=write_service, parsing_service=FakeParsingService(confidence=0.1))

    result = await svc.parse_and_create(text="低置信度", min_confidence=0.8, force_create=False)

    assert result.created is False
    assert result.task is None
    assert fake_client.calls == []


async def test_native_parse_and_create_route_uses_native_service(client: AsyncClient):
    class FakeNativeIntakeService:
        async def parse_and_create(self, **kwargs):
            return {
                "created": True,
                "parse_result": {
                    "draft": {"title": "route native", "description": None, "status": "todo", "priority": 3, "due_at": None, "tags": [], "meta_data": {}},
                    "candidates": [],
                    "selected_index": 0,
                    "confidence": 0.9,
                    "source": "fake",
                    "raw_text": kwargs["text"],
                },
                "task": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "title": "route native",
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
                "reason": None,
            }

    async def override_settings():
        return native_settings()

    async def override_intake():
        return FakeNativeIntakeService()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_obsidian_native_intake_service] = override_intake
    try:
        resp = await client.post("/api/v1/tasks/parse-and-create", json={"text": "创建 native", "force_create": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["task"]["meta_data"]["source"] == "obsidian_native_index"
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_obsidian_native_intake_service, None)
