from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.models import ObsidianTaskIndex
from app.schemas import DeleteResponse, TaskCommentCreate, TaskCommentListResponse, TaskCommentResponse, TaskCreate, TaskDependencyListResponse, TaskDependencyResponse, TaskResponse, TaskUpdate
from app.services.task_service import VALID_COMMENT_TYPES, VALID_STATUSES
from app.services.obsidian_sync_service import ObsidianFileClient, ObsidianFileWriteResult, ObsidianSyncHttpClient


class ObsidianNativeTaskWriteService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        client: ObsidianFileClient | None = None,
    ):
        self.session = session
        self.settings = settings
        self.client = client or ObsidianSyncHttpClient(settings)

    def _record_type(self, *, title: str, tags: list[str], meta_data: dict | None) -> str:
        meta_data = meta_data or {}
        explicit = meta_data.get("record_type") or meta_data.get("obsidian_record_type")
        if explicit:
            return self._sanitize_path_segment(str(explicit))
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

    def _sanitize_path_segment(self, value: str) -> str:
        sanitized = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", value).strip().strip(".")
        sanitized = re.sub(r"\s+", " ", sanitized)
        return sanitized or "其他事项"

    def _timestamp_filename(self, value: datetime) -> str:
        tz = ZoneInfo(self.settings.parsing_timezone)
        local = value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=timezone.utc).astimezone(tz)
        return local.strftime("%Y-%m-%d %H-%M-%S-%f")[:-3] + ".md"

    def _task_path(self, *, title: str, tags: list[str], meta_data: dict | None, created_at: datetime) -> str:
        record_type = self._record_type(title=title, tags=tags, meta_data=meta_data)
        return f"AI-Todo/{record_type}/{self._timestamp_filename(created_at)}"

    async def create_task(self, data: TaskCreate) -> TaskResponse:
        if data.status and data.status not in VALID_STATUSES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid status '{data.status}'.")
        vault_id = self._resolve_vault_id()
        task_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        item = ObsidianTaskIndex(
            task_id=str(task_id),
            vault_id=vault_id,
            path=self._task_path(title=data.title, tags=data.tags, meta_data=data.meta_data, created_at=now),
            file_id="pending",
            version=0,
            content_hash="pending",
            title=data.title,
            description=data.description,
            status=data.status or "todo",
            priority=data.priority,
            due_at=data.due_at,
            tags=data.tags,
            parent_id=str(data.parent_id) if data.parent_id else None,
            depends_on=[],
            source_updated_at=now,
            parsed_at=now,
            meta_data={"schema_version": 1, **(data.meta_data or {})},
        )
        markdown = self._render_markdown(item)
        write_result = await self.client.put_file(
            vault_id=vault_id,
            path=item.path,
            content=markdown.encode("utf-8"),
            base_version=None,
            idempotency_key=str(uuid.uuid4()),
        )
        self._apply_write_result(item, write_result, now)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return self._to_task_response(item)

    async def update_task(self, task_id: uuid.UUID, data: TaskUpdate) -> TaskResponse:
        item = await self._get_index_item(task_id)
        provided = data.model_fields_set
        if "status" in provided and data.status is not None:
            if data.status not in VALID_STATUSES:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid status '{data.status}'.")
            item.status = data.status
        if "title" in provided and data.title is not None:
            item.title = data.title
        if "description" in provided:
            item.description = data.description
        if "priority" in provided and data.priority is not None:
            item.priority = data.priority
        if "due_at" in provided:
            item.due_at = data.due_at
        if "parent_id" in provided:
            item.parent_id = str(data.parent_id) if data.parent_id else None
        if "tags" in provided and data.tags is not None:
            item.tags = data.tags
        if "meta_data" in provided and data.meta_data is not None:
            item.meta_data = {**(item.meta_data or {}), **data.meta_data}
        if "thinking_process" in provided and data.thinking_process is not None:
            item.meta_data = {**(item.meta_data or {}), "thinking": data.thinking_process}
        now = datetime.now(timezone.utc)
        item.source_updated_at = now
        item.parsed_at = now
        markdown = self._render_markdown(item)
        write_result = await self.client.put_file(
            vault_id=item.vault_id,
            path=item.path,
            content=markdown.encode("utf-8"),
            base_version=item.version,
            idempotency_key=str(uuid.uuid4()),
        )
        self._apply_write_result(item, write_result, now)
        await self.session.commit()
        await self.session.refresh(item)
        return self._to_task_response(item)

    def _comment_id(self, task_id: uuid.UUID, created_at: str, content: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"aitodo-obsidian-comment:{task_id}:{created_at}:{content}")

    async def add_comment(self, task_id: uuid.UUID, data: TaskCommentCreate) -> TaskCommentResponse:
        if data.type not in VALID_COMMENT_TYPES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid comment type '{data.type}'.")
        item = await self._get_index_item(task_id)
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        entry = {
            "id": str(self._comment_id(task_id, created_at, data.content)),
            "type": data.type.value if hasattr(data.type, "value") else str(data.type),
            "content": data.content,
            "meta_data": data.meta_data or {},
            "created_at": created_at,
        }
        timeline = list((item.meta_data or {}).get("timeline", []))
        timeline.append(entry)
        item.meta_data = {**(item.meta_data or {}), "timeline": timeline}
        await self._rewrite_existing_item(item)
        return self._comment_response(task_id, entry)

    async def list_comments(self, task_id: uuid.UUID) -> TaskCommentListResponse:
        item = await self._get_index_item(task_id)
        timeline = list((item.meta_data or {}).get("timeline", []))
        return TaskCommentListResponse(comments=[self._comment_response(task_id, entry) for entry in timeline])

    def _comment_response(self, task_id: uuid.UUID, entry: dict) -> TaskCommentResponse:
        return TaskCommentResponse(
            id=uuid.UUID(entry["id"]),
            task_id=task_id,
            type=entry.get("type", "comment"),
            content=entry.get("content", ""),
            meta_data=entry.get("meta_data", {}),
            created_at=datetime.fromisoformat(entry["created_at"]),
        )

    def _dependency_id(self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"aitodo-obsidian-dependency:{task_id}:{depends_on_task_id}")

    async def add_dependency(self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID) -> TaskDependencyResponse:
        if task_id == depends_on_task_id:
            raise AppError(ErrorCode.TASK_DEPENDENCY_CYCLE, "Task cannot depend on itself.")
        item = await self._get_index_item(task_id)
        await self._get_index_item(depends_on_task_id)
        depends_on_text = str(depends_on_task_id)
        if depends_on_text not in item.depends_on:
            item.depends_on = [*item.depends_on, depends_on_text]
            await self._rewrite_existing_item(item)
        return self._dependency_response(task_id, depends_on_task_id, item.source_updated_at or item.updated_at)

    async def list_dependencies(self, task_id: uuid.UUID) -> TaskDependencyListResponse:
        item = await self._get_index_item(task_id)
        return TaskDependencyListResponse(
            dependencies=[
                self._dependency_response(task_id, uuid.UUID(depends_on), item.source_updated_at or item.updated_at)
                for depends_on in item.depends_on
            ]
        )

    async def remove_dependency(self, task_id: uuid.UUID, dependency_id: uuid.UUID) -> DeleteResponse:
        item = await self._get_index_item(task_id)
        removed = False
        next_depends_on = []
        for depends_on in item.depends_on:
            depends_uuid = uuid.UUID(depends_on)
            if dependency_id in {depends_uuid, self._dependency_id(task_id, depends_uuid)}:
                removed = True
                continue
            next_depends_on.append(depends_on)
        if not removed:
            raise AppError(ErrorCode.TASK_DEPENDENCY_NOT_FOUND, f"Task dependency '{dependency_id}' does not exist.")
        item.depends_on = next_depends_on
        await self._rewrite_existing_item(item)
        return DeleteResponse(deleted_count=1)

    async def _rewrite_existing_item(self, item: ObsidianTaskIndex) -> None:
        now = datetime.now(timezone.utc)
        item.source_updated_at = now
        item.parsed_at = now
        markdown = self._render_markdown(item)
        write_result = await self.client.put_file(
            vault_id=item.vault_id,
            path=item.path,
            content=markdown.encode("utf-8"),
            base_version=item.version,
            idempotency_key=str(uuid.uuid4()),
        )
        self._apply_write_result(item, write_result, now)
        await self.session.commit()

    def _dependency_response(
        self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID, created_at: datetime
    ) -> TaskDependencyResponse:
        return TaskDependencyResponse(
            id=self._dependency_id(task_id, depends_on_task_id),
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            created_at=created_at,
        )

    async def archive_task(self, task_id: uuid.UUID) -> int:
        item = await self._get_index_item(task_id)
        if item.status == "archived":
            return 1
        now = datetime.now(timezone.utc)
        item.status = "archived"
        item.source_updated_at = now
        item.parsed_at = now
        item.meta_data = {**(item.meta_data or {}), "archived_at": now.isoformat()}
        markdown = self._render_markdown(item)
        write_result = await self.client.put_file(
            vault_id=item.vault_id,
            path=item.path,
            content=markdown.encode("utf-8"),
            base_version=item.version,
            idempotency_key=str(uuid.uuid4()),
        )
        self._apply_write_result(item, write_result, now)
        item.meta_data = {**(item.meta_data or {}), "archived_at": now.isoformat()}
        await self.session.commit()
        return 1

    async def _get_index_item(self, task_id: uuid.UUID) -> ObsidianTaskIndex:
        result = await self.session.execute(select(ObsidianTaskIndex).where(ObsidianTaskIndex.task_id == str(task_id)))
        item = result.scalar_one_or_none()
        if item is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND, f"Task with id '{task_id}' does not exist in Obsidian index.")
        return item

    def _resolve_vault_id(self) -> str:
        if self.settings.obsidian_sync_vault_id:
            return self.settings.obsidian_sync_vault_id
        raise AppError(ErrorCode.VALIDATION_ERROR, "Obsidian Sync vault is not configured.")

    def _apply_write_result(self, item: ObsidianTaskIndex, result: ObsidianFileWriteResult, now: datetime) -> None:
        item.path = result.path
        item.file_id = result.file_id
        item.version = result.version
        item.content_hash = result.content_hash
        item.source_updated_at = now
        item.parsed_at = now
        item.updated_at = now
        item.meta_data = {**(item.meta_data or {}), "last_checkpoint": result.checkpoint, "last_op": result.op}

    def _render_markdown(self, item: ObsidianTaskIndex) -> str:
        tags = "\n".join(f"  - {tag}" for tag in item.tags) if item.tags else " []"
        depends_on = "\n".join(f"  - {dep}" for dep in item.depends_on) if item.depends_on else " []"
        due_at = item.due_at.isoformat() if item.due_at else ""
        parent_id = item.parent_id or ""
        updated_at = (item.source_updated_at or datetime.now(timezone.utc)).isoformat()
        archived_at = (item.meta_data or {}).get("archived_at", "")
        dependency_links = [f"- [[AI-Todo/tasks/{dep}.md]]" for dep in item.depends_on] or ["- 无"]
        timeline = list((item.meta_data or {}).get("timeline", []))
        timeline_lines = [f"- {entry.get('created_at')} [{entry.get('type', 'comment')}] {entry.get('content', '')}" for entry in timeline] or ["- 暂无"]
        return "\n".join([
            "---",
            "source: ai-todo",
            "schema_version: 1",
            f"aitodo_id: {item.task_id}",
            f"status: {item.status}",
            f"priority: {item.priority}",
            f"due_at: {due_at}",
            f"parent_id: {parent_id}",
            "tags:" + (f"\n{tags}" if item.tags else tags),
            "depends_on:" + (f"\n{depends_on}" if item.depends_on else depends_on),
            f"updated_at: {updated_at}",
            f"archived_at: {archived_at}",
            "---",
            "",
            f"# {item.title}",
            "",
            item.description or "",
            "",
            "## 依赖",
            "",
            *dependency_links,
            "",
            "## 时间线",
            "",
            *timeline_lines,
            "",
        ])

    def _to_task_response(self, item: ObsidianTaskIndex) -> TaskResponse:
        return TaskResponse(
            id=uuid.UUID(item.task_id),
            title=item.title,
            description=item.description,
            status=item.status,
            priority=item.priority,
            due_at=item.due_at,
            parent_id=uuid.UUID(item.parent_id) if item.parent_id else None,
            tags=item.tags,
            meta_data={
                **(item.meta_data or {}),
                "source": "obsidian_native_index",
                "vault_id": item.vault_id,
                "path": item.path,
                "file_id": item.file_id,
                "version": item.version,
                "content_hash": item.content_hash,
            },
            created_at=item.source_updated_at or item.created_at,
            updated_at=item.source_updated_at or item.updated_at,
            children=[],
        )
