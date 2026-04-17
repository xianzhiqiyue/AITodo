from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ErrorCode
from app.models import ObsidianTaskIndex
from app.schemas import AlertItem, AlertListResponse, ReadyTaskListResponse, SuggestedTask, SuggestedTaskListResponse, TaskListResponse, TaskResponse, WorkspaceDashboardResponse

OPEN_STATUSES = {"todo", "in_progress"}


class ObsidianNativeTaskQueryService:
    def __init__(self, *, session: AsyncSession, timezone_name: str = "UTC"):
        self.session = session
        self.timezone = ZoneInfo(timezone_name)

    async def get_task(self, task_id: uuid.UUID) -> TaskResponse:
        item = await self._get_index_item(task_id)
        return self._to_task_response(item)

    async def get_task_context(
        self,
        *,
        status_filter: str = "open",
        top_n: int = 20,
        offset: int = 0,
        tags: list[str] | None = None,
        query: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> TaskListResponse:
        items = await self._list_all()
        filtered = self._filter_items(
            items,
            status_filter=status_filter,
            tags=tags,
            query=query,
            parent_id=str(parent_id) if parent_id else None,
        )
        filtered.sort(key=lambda item: (item.priority, item.created_at), reverse=False)
        paged = filtered[offset: offset + top_n]
        return TaskListResponse(
            tasks=[self._to_task_response(item) for item in paged],
            total=len(filtered),
            offset=offset,
        )

    async def list_ready_tasks(
        self,
        *,
        top_n: int = 20,
        offset: int = 0,
        tags: list[str] | None = None,
    ) -> ReadyTaskListResponse:
        items = await self._list_all()
        by_id = {item.task_id: item for item in items}
        ready = []
        for item in items:
            if item.status not in OPEN_STATUSES:
                continue
            if tags and not set(tags).intersection(set(item.tags)):
                continue
            dependencies_done = True
            for dep_id in item.depends_on:
                dep = by_id.get(dep_id)
                if dep is not None and dep.status != "done":
                    dependencies_done = False
                    break
            if dependencies_done:
                ready.append(item)
        ready.sort(key=lambda item: (item.priority, item.due_at or datetime.max.replace(tzinfo=self.timezone), item.created_at))
        paged = ready[offset: offset + top_n]
        return ReadyTaskListResponse(tasks=[self._to_task_response(item) for item in paged], total=len(ready))

    async def get_suggested_today(self, *, top_n: int = 10, tags: list[str] | None = None) -> SuggestedTaskListResponse:
        now = datetime.now(self.timezone)
        ready = await self.list_ready_tasks(top_n=100, offset=0, tags=tags)
        suggestions: list[SuggestedTask] = []
        for task in ready.tasks:
            score, reasons = self._score_task(task, now)
            suggestions.append(SuggestedTask(task=task, score=round(score, 2), reasons=reasons))
        suggestions.sort(
            key=lambda item: (
                -item.score,
                item.task.priority,
                item.task.due_at or datetime.max.replace(tzinfo=self.timezone),
            )
        )
        suggestions = suggestions[:top_n]
        return SuggestedTaskListResponse(tasks=suggestions, total=len(suggestions))


    async def list_today_tasks(self, *, top_n: int = 20) -> TaskListResponse:
        now = datetime.now(self.timezone)
        items = [
            item for item in await self._list_all()
            if item.status != "done"
            and item.status != "archived"
            and item.due_at is not None
            and self._as_timezone(item.due_at).date() == now.date()
        ]
        items.sort(key=lambda item: (item.priority, item.due_at or datetime.max.replace(tzinfo=self.timezone)))
        items = items[:top_n]
        return TaskListResponse(tasks=[self._to_task_response(item) for item in items], total=len(items), offset=0)

    async def list_overdue_tasks(self, *, top_n: int = 20) -> TaskListResponse:
        now = datetime.now(self.timezone)
        items = [
            item for item in await self._list_all()
            if item.status != "done"
            and item.status != "archived"
            and item.due_at is not None
            and self._as_timezone(item.due_at) < now
        ]
        items.sort(key=lambda item: (item.due_at or datetime.max.replace(tzinfo=self.timezone), item.priority))
        items = items[:top_n]
        return TaskListResponse(tasks=[self._to_task_response(item) for item in items], total=len(items), offset=0)

    async def list_blocked_tasks(self, *, top_n: int = 20) -> TaskListResponse:
        items = [item for item in await self._list_all() if item.status == "blocked"]
        items.sort(key=lambda item: (item.priority, item.updated_at), reverse=False)
        items = items[:top_n]
        return TaskListResponse(tasks=[self._to_task_response(item) for item in items], total=len(items), offset=0)

    async def list_recently_updated_tasks(self, *, top_n: int = 20) -> TaskListResponse:
        items = await self._list_all()
        items.sort(key=lambda item: item.source_updated_at or item.updated_at, reverse=True)
        items = items[:top_n]
        return TaskListResponse(tasks=[self._to_task_response(item) for item in items], total=len(items), offset=0)

    async def get_stale_tasks(self, *, top_n: int = 20) -> TaskListResponse:
        now = datetime.now(self.timezone)
        items = [
            item for item in await self._list_all()
            if item.status in OPEN_STATUSES
            and (now - self._as_timezone(item.source_updated_at or item.updated_at)).total_seconds() >= 48 * 3600
        ]
        items.sort(key=lambda item: item.source_updated_at or item.updated_at)
        items = items[:top_n]
        return TaskListResponse(tasks=[self._to_task_response(item) for item in items], total=len(items), offset=0)

    async def list_alerts(self, *, top_n: int = 20) -> AlertListResponse:
        alerts: list[AlertItem] = []
        seen: set[uuid.UUID] = set()
        for task in (await self.list_overdue_tasks(top_n=top_n)).tasks:
            alerts.append(AlertItem(task=task, reason="overdue"))
            seen.add(task.id)
        if len(alerts) < top_n:
            for task in (await self.list_today_tasks(top_n=top_n)).tasks:
                if task.id not in seen and len(alerts) < top_n:
                    alerts.append(AlertItem(task=task, reason="due_today"))
                    seen.add(task.id)
        if len(alerts) < top_n:
            for task in (await self.list_blocked_tasks(top_n=top_n)).tasks:
                if task.id not in seen and len(alerts) < top_n:
                    alerts.append(AlertItem(task=task, reason="blocked"))
                    seen.add(task.id)
        return AlertListResponse(alerts=alerts, total=len(alerts))

    async def get_dashboard(self, *, top_n: int = 10) -> WorkspaceDashboardResponse:
        today = await self.list_today_tasks(top_n=top_n)
        overdue = await self.list_overdue_tasks(top_n=top_n)
        blocked = await self.list_blocked_tasks(top_n=top_n)
        ready_to_start = await self.list_ready_tasks(top_n=top_n)
        recently_updated = await self.list_recently_updated_tasks(top_n=top_n)
        alerts = await self.list_alerts(top_n=top_n)
        suggested_today = await self.get_suggested_today(top_n=top_n)
        stale_tasks = await self.get_stale_tasks(top_n=top_n)
        return WorkspaceDashboardResponse(
            today=today,
            overdue=overdue,
            blocked=blocked,
            ready_to_start=ready_to_start,
            recently_updated=recently_updated,
            alerts=alerts,
            suggested_today=suggested_today,
            stale_tasks=stale_tasks,
        )

    async def _get_index_item(self, task_id: uuid.UUID) -> ObsidianTaskIndex:
        result = await self.session.execute(
            select(ObsidianTaskIndex).where(ObsidianTaskIndex.task_id == str(task_id))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND, f"Task with id '{task_id}' does not exist in Obsidian index.")
        return item

    async def _list_all(self) -> list[ObsidianTaskIndex]:
        result = await self.session.execute(select(ObsidianTaskIndex))
        return list(result.scalars().all())

    def _filter_items(
        self,
        items: list[ObsidianTaskIndex],
        *,
        status_filter: str,
        tags: list[str] | None,
        query: str | None,
        parent_id: str | None,
    ) -> list[ObsidianTaskIndex]:
        filtered = []
        query_lower = query.lower() if query else None
        for item in items:
            if status_filter == "open" and item.status not in OPEN_STATUSES:
                continue
            if status_filter not in {"open", "all"} and item.status != status_filter:
                continue
            if tags and not set(tags).intersection(set(item.tags)):
                continue
            if parent_id and item.parent_id != parent_id:
                continue
            if query_lower:
                haystack = f"{item.title}\n{item.description or ''}".lower()
                if query_lower not in haystack:
                    continue
            filtered.append(item)
        return filtered

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


    def _as_timezone(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self.timezone)
        return value.astimezone(self.timezone)

    def _score_task(self, task: TaskResponse, now: datetime) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        score += max(0, 6 - task.priority) * 10
        reasons.append(f"priority_{task.priority}")
        if task.due_at is not None:
            due_at = self._as_timezone(task.due_at)
            if due_at < now:
                score += 50
                reasons.append("overdue")
            elif due_at.date() == now.date():
                score += 30
                reasons.append("due_today")
            elif (due_at - now).days <= 2:
                score += 15
                reasons.append("due_soon")
        age_hours = max((now - self._as_timezone(task.updated_at)).total_seconds() / 3600, 0)
        if age_hours >= 24:
            score += min(age_hours / 4, 20)
            reasons.append("stale")
        if task.parent_id is not None:
            score += 5
            reasons.append("part_of_larger_goal")
        return score, reasons


# keep helper attached after class definition for mypy-free runtime usage
