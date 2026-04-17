from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ErrorCode
from app.models import ObsidianTaskIndex
from app.services.obsidian_markdown_parser import ObsidianMarkdownParser, ParsedObsidianTask
from app.services.obsidian_sync_service import ObsidianFileClient, ObsidianFileMetadata, ObsidianSyncHttpClient


class ObsidianIndexService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        client: ObsidianFileClient | None = None,
        parser: ObsidianMarkdownParser | None = None,
    ):
        self.session = session
        self.settings = settings
        self.client = client or ObsidianSyncHttpClient(settings)
        self.parser = parser or ObsidianMarkdownParser()

    async def rebuild_index(self, *, prefix: str = "AI-Todo/tasks/", limit: int = 500) -> dict:
        vault_id = self._resolve_vault_id()
        cursor: str | None = None
        scanned = 0
        indexed = 0
        skipped = 0
        errors: list[dict[str, str]] = []
        checkpoint = "cp_0"

        while True:
            page = await self.client.list_files(vault_id=vault_id, prefix=prefix, limit=min(limit, 1000), cursor=cursor)
            checkpoint = page.checkpoint
            for metadata in page.items:
                scanned += 1
                try:
                    changed = await self._index_file(vault_id=vault_id, metadata=metadata)
                    if changed:
                        indexed += 1
                    else:
                        skipped += 1
                except Exception as exc:  # keep rebuild best-effort
                    errors.append({"path": metadata.path, "error": str(exc)})
            if not page.next_cursor or scanned >= limit:
                break
            cursor = page.next_cursor

        await self.session.commit()
        return {
            "vault_id": vault_id,
            "checkpoint": checkpoint,
            "scanned": scanned,
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
        }

    async def list_indexed_tasks(self, *, status: str | None = None, limit: int = 100) -> list[ObsidianTaskIndex]:
        statement = select(ObsidianTaskIndex).order_by(ObsidianTaskIndex.updated_at.desc()).limit(limit)
        if status:
            statement = statement.where(ObsidianTaskIndex.status == status)
        return list((await self.session.execute(statement)).scalars().all())

    async def _index_file(self, *, vault_id: str, metadata: ObsidianFileMetadata) -> bool:
        existing = await self._get_by_file(vault_id=vault_id, file_id=metadata.file_id)
        if existing and existing.content_hash == metadata.content_hash:
            return False
        content = await self.client.download_object(vault_id=vault_id, content_hash=metadata.content_hash)
        parsed = self.parser.parse_task(content.decode("utf-8"))
        if parsed is None:
            return False
        await self._upsert_index(vault_id=vault_id, metadata=metadata, parsed=parsed, existing=existing)
        return True

    async def _get_by_file(self, *, vault_id: str, file_id: str) -> ObsidianTaskIndex | None:
        result = await self.session.execute(
            select(ObsidianTaskIndex).where(
                ObsidianTaskIndex.vault_id == vault_id,
                ObsidianTaskIndex.file_id == file_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_by_task(self, *, vault_id: str, task_id: str) -> ObsidianTaskIndex | None:
        result = await self.session.execute(
            select(ObsidianTaskIndex).where(
                ObsidianTaskIndex.vault_id == vault_id,
                ObsidianTaskIndex.task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_index(
        self,
        *,
        vault_id: str,
        metadata: ObsidianFileMetadata,
        parsed: ParsedObsidianTask,
        existing: ObsidianTaskIndex | None,
    ) -> ObsidianTaskIndex:
        target = existing or await self._get_by_task(vault_id=vault_id, task_id=parsed.task_id)
        now = datetime.now(timezone.utc)
        if target is None:
            target = ObsidianTaskIndex(
                task_id=parsed.task_id,
                vault_id=vault_id,
                path=metadata.path,
                file_id=metadata.file_id,
                version=metadata.version,
                content_hash=metadata.content_hash,
                title=parsed.title,
                description=parsed.description,
                status=parsed.status,
                priority=parsed.priority,
                due_at=parsed.due_at,
                tags=parsed.tags,
                parent_id=parsed.parent_id,
                depends_on=parsed.depends_on,
                source_updated_at=parsed.source_updated_at,
                parsed_at=now,
                meta_data={"schema_version": parsed.schema_version},
            )
            self.session.add(target)
            return target
        target.path = metadata.path
        target.file_id = metadata.file_id
        target.version = metadata.version
        target.content_hash = metadata.content_hash
        target.title = parsed.title
        target.description = parsed.description
        target.status = parsed.status
        target.priority = parsed.priority
        target.due_at = parsed.due_at
        target.tags = parsed.tags
        target.parent_id = parsed.parent_id
        target.depends_on = parsed.depends_on
        target.source_updated_at = parsed.source_updated_at
        target.parsed_at = now
        target.updated_at = now
        target.meta_data = {"schema_version": parsed.schema_version}
        return target

    def _resolve_vault_id(self) -> str:
        if self.settings.obsidian_sync_vault_id:
            return self.settings.obsidian_sync_vault_id
        raise AppError(ErrorCode.VALIDATION_ERROR, "Obsidian Sync vault is not configured.")
