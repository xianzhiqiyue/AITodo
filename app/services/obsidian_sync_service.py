from __future__ import annotations

import base64
import re
import uuid
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.models import ObsidianFileBinding, ObsidianSyncConnection, Task, TaskComment, TaskDependency


@dataclass
class ObsidianFileWriteResult:
    file_id: str
    path: str
    version: int
    content_hash: str
    checkpoint: str
    changeset_id: str
    op: str




@dataclass
class ObsidianFileMetadata:
    file_id: str
    path: str
    version: int
    content_hash: str
    deleted: bool
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ObsidianFileListResult:
    checkpoint: str
    items: list[ObsidianFileMetadata]
    next_cursor: str | None


class ObsidianFileClient(Protocol):
    async def put_file(
        self,
        *,
        vault_id: str,
        path: str,
        content: bytes,
        base_version: int | None,
        idempotency_key: str,
    ) -> ObsidianFileWriteResult:
        ...

    async def list_files(
        self,
        *,
        vault_id: str,
        prefix: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> ObsidianFileListResult:
        ...

    async def download_object(self, *, vault_id: str, content_hash: str) -> bytes:
        ...


class ObsidianSyncHttpClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.obsidian_sync_base_url.rstrip("/")
        self.access_token = settings.obsidian_sync_access_token

    async def _ensure_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not self.settings.obsidian_sync_email or not self.settings.obsidian_sync_password:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Obsidian Sync credentials are not configured.")
        async with httpx.AsyncClient(timeout=self.settings.obsidian_sync_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": self.settings.obsidian_sync_email,
                    "password": self.settings.obsidian_sync_password,
                    "deviceName": self.settings.obsidian_sync_device_name,
                    "platform": "linux",
                    "pluginVersion": f"aitodo-{self.settings.app_version}",
                },
            )
            self._raise_for_obsidian_error(response)
            payload = response.json()
            self.access_token = payload["accessToken"]
            return self.access_token

    async def put_file(
        self,
        *,
        vault_id: str,
        path: str,
        content: bytes,
        base_version: int | None,
        idempotency_key: str,
    ) -> ObsidianFileWriteResult:
        token = await self._ensure_access_token()
        body: dict[str, object] = {
            "contentBase64": base64.b64encode(content).decode("ascii"),
            "idempotencyKey": idempotency_key,
            "conflictStrategy": "fail",
        }
        if base_version is not None:
            body["baseVersion"] = base_version
        async with httpx.AsyncClient(timeout=self.settings.obsidian_sync_timeout_seconds) as client:
            response = await client.put(
                f"{self.base_url}/vaults/{vault_id}/files/by-path/{quote(path, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            self._raise_for_obsidian_error(response)
            payload = response.json()
            return ObsidianFileWriteResult(
                file_id=payload["fileId"],
                path=payload["path"],
                version=payload["version"],
                content_hash=payload["contentHash"],
                checkpoint=payload["checkpoint"],
                changeset_id=payload["changesetId"],
                op=payload["op"],
            )


    async def list_files(
        self,
        *,
        vault_id: str,
        prefix: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> ObsidianFileListResult:
        token = await self._ensure_access_token()
        params: dict[str, object] = {"prefix": prefix, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=self.settings.obsidian_sync_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/vaults/{vault_id}/files",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            self._raise_for_obsidian_error(response)
            payload = response.json()
            return ObsidianFileListResult(
                checkpoint=payload["checkpoint"],
                items=[
                    ObsidianFileMetadata(
                        file_id=item["fileId"],
                        path=item["path"],
                        version=item["version"],
                        content_hash=item["contentHash"],
                        deleted=item.get("deleted", False),
                        created_at=item.get("createdAt"),
                        updated_at=item.get("updatedAt"),
                    )
                    for item in payload.get("items", [])
                ],
                next_cursor=payload.get("nextCursor"),
            )

    async def download_object(self, *, vault_id: str, content_hash: str) -> bytes:
        token = await self._ensure_access_token()
        async with httpx.AsyncClient(timeout=self.settings.obsidian_sync_timeout_seconds) as client:
            url_response = await client.post(
                f"{self.base_url}/vaults/{vault_id}/objects/download-urls",
                headers={"Authorization": f"Bearer {token}"},
                json={"contentHashes": [content_hash]},
            )
            self._raise_for_obsidian_error(url_response)
            items = url_response.json().get("items", [])
            if not items:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"No download URL for {content_hash}.")
            download_response = await client.get(items[0]["downloadUrl"])
            self._raise_for_obsidian_error(download_response)
            return download_response.content

    @staticmethod
    def _raise_for_obsidian_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        code = payload.get("code", "OBSIDIAN_SYNC_ERROR")
        message = payload.get("message", f"Obsidian Sync request failed with status {response.status_code}")
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{code}: {message}")


def _sanitize_path_segment(value: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", value).strip().strip(".")
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or "其他事项"


def _record_type(title: str, tags: list[str], meta_data: dict | None) -> str:
    meta_data = meta_data or {}
    explicit = meta_data.get("record_type") or meta_data.get("obsidian_record_type")
    if explicit:
        return _sanitize_path_segment(str(explicit))
    tag_set = {str(tag).lower() for tag in tags}
    if {"daily-log", "worklog", "工作日记", "日报", "日记"}.intersection(tag_set):
        return "工作日记"
    if {"learning", "study", "学习", "学习感悟", "感悟"}.intersection(tag_set):
        return "学习感悟"
    if {"other", "misc", "其他", "其他事项"}.intersection(tag_set):
        return "其他事项"
    if "本日工作" in title or "工作记录" in title:
        return "工作日记"
    return "待办任务"


def _timestamp_filename(value: datetime, timezone_name: str = "Asia/Shanghai") -> str:
    tz = ZoneInfo(timezone_name)
    local = value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%Y-%m-%d %H-%M-%S-%f")[:-3] + ".md"


def build_task_path(
    task_id: uuid.UUID,
    title: str,
    tags: list[str] | None = None,
    meta_data: dict | None = None,
    created_at: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    del task_id  # Stable ID remains in front matter; path is human-oriented.
    record_type = _record_type(title, tags or [], meta_data)
    return f"AI-Todo/{record_type}/{_timestamp_filename(created_at or datetime.now(timezone.utc), timezone_name)}"

class ObsidianExportRenderer:
    def render_task(
        self,
        *,
        task: Task,
        comments: list[TaskComment],
        dependencies: list[TaskDependency],
        exported_at: datetime,
    ) -> str:
        tags_yaml = "\n".join(f"  - {tag}" for tag in task.tags) if task.tags else " []"
        due_at = task.due_at.isoformat() if task.due_at else ""
        parent_id = str(task.parent_id) if task.parent_id else ""
        description = task.description or ""
        dependency_lines = []
        for dep in dependencies:
            dependency_lines.append(f"- [[AI-Todo/tasks/{dep.depends_on_task_id}.md]]")
        timeline_lines = []
        for comment in comments:
            timeline_lines.append(f"- {comment.created_at.isoformat()} [{comment.type}] {comment.content}")
        if not dependency_lines:
            dependency_lines.append("- 无")
        if not timeline_lines:
            timeline_lines.append("- 暂无")
        return "\n".join(
            [
                "---",
                "source: ai-todo",
                f"aitodo_id: {task.id}",
                f"status: {task.status}",
                f"priority: {task.priority}",
                f"due_at: {due_at}",
                f"parent_id: {parent_id}",
                "tags:" + (f"\n{tags_yaml}" if task.tags else tags_yaml),
                f"updated_at: {task.updated_at.isoformat()}",
                f"exported_at: {exported_at.isoformat()}",
                "---",
                "",
                f"# {task.title}",
                "",
                description,
                "",
                "## 元信息",
                "",
                f"- 状态：{task.status}",
                f"- 优先级：{task.priority}",
                f"- 截止时间：{due_at or '未设置'}",
                "",
                "## 依赖",
                "",
                *dependency_lines,
                "",
                "## 时间线",
                "",
                *timeline_lines,
                "",
            ]
        )


class ObsidianExportService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        client: ObsidianFileClient | None = None,
        renderer: ObsidianExportRenderer | None = None,
    ):
        self.session = session
        self.settings = settings
        self.client = client or ObsidianSyncHttpClient(settings)
        self.renderer = renderer or ObsidianExportRenderer()

    async def export_task(self, task_id: uuid.UUID) -> dict:
        vault_id = await self._resolve_vault_id()
        result = await self.session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.children))
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND, f"Task with id '{task_id}' does not exist.")

        comments = (await self.session.execute(
            select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at.asc())
        )).scalars().all()
        dependencies = (await self.session.execute(
            select(TaskDependency).where(TaskDependency.task_id == task_id).order_by(TaskDependency.created_at.asc())
        )).scalars().all()
        binding = await self._get_binding(entity_type="task", entity_id=str(task_id), vault_id=vault_id)
        path = binding.path if binding else build_task_path(task_id, task.title, task.tags, task.meta_data, task.created_at)
        exported_at = datetime.now(timezone.utc)
        markdown = self.renderer.render_task(
            task=task,
            comments=list(comments),
            dependencies=list(dependencies),
            exported_at=exported_at,
        )
        idempotency_key = str(uuid.uuid4())
        write_result = await self.client.put_file(
            vault_id=vault_id,
            path=path,
            content=markdown.encode("utf-8"),
            base_version=binding.version if binding else None,
            idempotency_key=idempotency_key,
        )
        binding = await self._upsert_binding(
            binding=binding,
            entity_type="task",
            entity_id=str(task_id),
            vault_id=vault_id,
            result=write_result,
            exported_at=exported_at,
        )
        await self.session.commit()
        return {
            "entity_type": binding.entity_type,
            "entity_id": binding.entity_id,
            "vault_id": binding.vault_id,
            "path": binding.path,
            "file_id": binding.file_id,
            "version": binding.version,
            "content_hash": binding.content_hash,
            "checkpoint": write_result.checkpoint,
            "op": write_result.op,
            "exported_at": binding.last_exported_at,
        }

    async def export_all_tasks(self, limit: int = 100) -> dict:
        result = await self.session.execute(select(Task.id).order_by(Task.updated_at.desc()).limit(limit))
        task_ids = list(result.scalars())
        items = []
        for task_id in task_ids:
            items.append(await self.export_task(task_id))
        return {"exported_count": len(items), "items": items}

    async def list_bindings(self, entity_type: str | None = None) -> list[ObsidianFileBinding]:
        statement = select(ObsidianFileBinding).order_by(ObsidianFileBinding.updated_at.desc())
        if entity_type:
            statement = statement.where(ObsidianFileBinding.entity_type == entity_type)
        return list((await self.session.execute(statement)).scalars().all())

    async def _resolve_vault_id(self) -> str:
        if self.settings.obsidian_sync_vault_id:
            return self.settings.obsidian_sync_vault_id
        result = await self.session.execute(
            select(ObsidianSyncConnection).where(ObsidianSyncConnection.status == "active").order_by(ObsidianSyncConnection.updated_at.desc())
        )
        connection = result.scalar_one_or_none()
        if connection:
            return connection.vault_id
        raise AppError(ErrorCode.VALIDATION_ERROR, "Obsidian Sync vault is not configured.")

    async def _get_binding(self, *, entity_type: str, entity_id: str, vault_id: str) -> ObsidianFileBinding | None:
        result = await self.session.execute(
            select(ObsidianFileBinding).where(
                ObsidianFileBinding.entity_type == entity_type,
                ObsidianFileBinding.entity_id == entity_id,
                ObsidianFileBinding.vault_id == vault_id,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_binding(
        self,
        *,
        binding: ObsidianFileBinding | None,
        entity_type: str,
        entity_id: str,
        vault_id: str,
        result: ObsidianFileWriteResult,
        exported_at: datetime,
    ) -> ObsidianFileBinding:
        if binding is None:
            binding = ObsidianFileBinding(
                entity_type=entity_type,
                entity_id=entity_id,
                vault_id=vault_id,
                path=result.path,
                file_id=result.file_id,
                version=result.version,
                content_hash=result.content_hash,
                last_exported_at=exported_at,
                meta_data={},
            )
            self.session.add(binding)
            return binding
        binding.path = result.path
        binding.file_id = result.file_id
        binding.version = result.version
        binding.content_hash = result.content_hash
        binding.last_exported_at = exported_at
        binding.updated_at = datetime.now(timezone.utc)
        return binding
