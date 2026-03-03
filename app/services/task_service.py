from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import or_, func, select, text
from sqlalchemy.orm import selectinload

from app.errors import AppError, ErrorCode
from app.models import Task
from app.schemas import (
    DecomposeResponse,
    DeleteResponse,
    SubTaskInput,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.embedding_service import EmbeddingService

logger = structlog.get_logger()

VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}
MAX_DEPTH = 5


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService | None = None,
        is_postgres: bool = True,
    ):
        self.session = session
        self.embedding_service = embedding_service
        self.is_postgres = is_postgres

    async def _get_task_or_raise(self, task_id: uuid.UUID) -> Task:
        result = await self.session.execute(
            select(Task).where(Task.id == task_id).options(selectinload(Task.children))
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND, f"Task with id '{task_id}' does not exist.")
        return task

    async def _get_depth(self, parent_id: uuid.UUID | None) -> int:
        """Calculate current depth of a parent chain (root = 1)."""
        if parent_id is None:
            return 0
        depth = 0
        current_id = parent_id
        while current_id is not None:
            depth += 1
            if depth > MAX_DEPTH:
                return depth
            result = await self.session.execute(
                select(Task.parent_id).where(Task.id == current_id)
            )
            row = result.first()
            if row is None:
                raise AppError(ErrorCode.TASK_NOT_FOUND, f"Parent task '{current_id}' does not exist.")
            current_id = row[0]
        return depth

    async def _validate_status_transition(self, task: Task, new_status: str) -> None:
        if new_status not in VALID_STATUSES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}")

        if new_status == "done":
            result = await self.session.execute(
                select(func.count()).select_from(Task).where(
                    Task.parent_id == task.id,
                    Task.status != "done",
                )
            )
            undone_count = result.scalar_one()
            if undone_count > 0:
                raise AppError(
                    ErrorCode.PARENT_NOT_DONE,
                    f"Cannot mark task as done: {undone_count} child task(s) are not yet done.",
                )

    async def _generate_embedding(self, title: str, description: str | None) -> list[float] | None:
        if self.embedding_service is None:
            return None
        text_content = title
        if description:
            text_content = f"{title}\n{description}"
        return await self.embedding_service.generate_embedding(text_content)

    async def upsert_task(
        self,
        data: TaskCreate | None = None,
        update_data: TaskUpdate | None = None,
        task_id: uuid.UUID | None = None,
    ) -> TaskResponse:
        if task_id is not None:
            return await self._update_task(task_id, update_data or TaskUpdate())
        if data is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Task data is required for creation.")
        return await self._create_task(data)

    async def _create_task(self, data: TaskCreate) -> TaskResponse:
        if data.status and data.status not in VALID_STATUSES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid status '{data.status}'.")

        if data.parent_id is not None:
            parent_depth = await self._get_depth(data.parent_id)
            if parent_depth + 1 > MAX_DEPTH:
                raise AppError(ErrorCode.MAX_DEPTH_EXCEEDED, f"Maximum nesting depth of {MAX_DEPTH} exceeded.")

        meta = data.meta_data or {}
        if data.thinking_process:
            meta["thinking"] = data.thinking_process

        embedding = await self._generate_embedding(data.title, data.description)

        task = Task(
            title=data.title,
            description=data.description,
            status=data.status or "todo",
            priority=data.priority,
            due_at=data.due_at,
            parent_id=data.parent_id,
            tags=data.tags,
            meta_data=meta,
            embedding=embedding,
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task, attribute_names=["children"])
        await self.session.commit()
        logger.info("task_created", task_id=str(task.id), title=task.title)
        return TaskResponse.model_validate(task)

    async def _update_task(self, task_id: uuid.UUID, data: TaskUpdate) -> TaskResponse:
        task = await self._get_task_or_raise(task_id)

        if data.status is not None:
            await self._validate_status_transition(task, data.status)
            task.status = data.status

        if data.title is not None:
            task.title = data.title
        if data.description is not None:
            task.description = data.description
        if data.priority is not None:
            task.priority = data.priority
        if data.due_at is not None:
            task.due_at = data.due_at
        if data.tags is not None:
            task.tags = data.tags

        if data.parent_id is not None:
            depth = await self._get_depth(data.parent_id)
            if depth + 1 > MAX_DEPTH:
                raise AppError(ErrorCode.MAX_DEPTH_EXCEEDED, f"Maximum nesting depth of {MAX_DEPTH} exceeded.")
            task.parent_id = data.parent_id

        if data.meta_data is not None:
            task.meta_data = {**task.meta_data, **data.meta_data}
        if data.thinking_process is not None:
            task.meta_data = {**task.meta_data, "thinking": data.thinking_process}

        needs_reembed = data.title is not None or data.description is not None
        if needs_reembed:
            embedding = await self._generate_embedding(task.title, task.description)
            if embedding is not None:
                task.embedding = embedding

        await self.session.flush()
        await self.session.commit()
        result = await self.session.execute(
            select(Task).where(Task.id == task.id).options(selectinload(Task.children))
        )
        task = result.scalar_one()
        logger.info("task_updated", task_id=str(task.id))
        return TaskResponse.model_validate(task)

    async def get_task(self, task_id: uuid.UUID) -> TaskResponse:
        task = await self._get_task_or_raise(task_id)
        return TaskResponse.model_validate(task)

    async def get_task_context(
        self,
        status_filter: str = "open",
        top_n: int = 20,
        offset: int = 0,
        tags: list[str] | None = None,
        query: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> TaskListResponse:
        top_n = min(max(top_n, 1), 100)

        if query and self.embedding_service:
            return await self._semantic_search(
                query=query,
                status_filter=status_filter,
                top_n=top_n,
                offset=offset,
                tags=tags,
                parent_id=parent_id,
            )

        return await self._keyword_search(
            query=query,
            status_filter=status_filter,
            top_n=top_n,
            offset=offset,
            tags=tags,
            parent_id=parent_id,
        )

    async def _keyword_search(
        self,
        query: str | None = None,
        status_filter: str = "open",
        top_n: int = 20,
        offset: int = 0,
        tags: list[str] | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> TaskListResponse:
        stmt = select(Task)
        count_stmt = select(func.count()).select_from(Task)

        conditions = self._build_filter_conditions(status_filter, tags, parent_id)
        for cond in conditions:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        if query:
            like_pattern = f"%{query}%"
            keyword_cond = Task.title.ilike(like_pattern)
            stmt = stmt.where(keyword_cond)
            count_stmt = count_stmt.where(keyword_cond)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.options(selectinload(Task.children))
        stmt = stmt.order_by(Task.priority.asc(), Task.created_at.desc())
        stmt = stmt.offset(offset).limit(top_n)

        result = await self.session.execute(stmt)
        tasks = result.scalars().all()

        return TaskListResponse(
            tasks=[TaskResponse.model_validate(t) for t in tasks],
            total=total,
            offset=offset,
        )

    async def _semantic_search(
        self,
        query: str,
        status_filter: str,
        top_n: int,
        offset: int,
        tags: list[str] | None,
        parent_id: uuid.UUID | None,
    ) -> TaskListResponse:
        assert self.embedding_service is not None
        query_embedding = await self.embedding_service.generate_embedding(query)

        if query_embedding is None:
            return await self._keyword_search(
                query=query,
                status_filter=status_filter,
                top_n=top_n,
                offset=offset,
                tags=tags,
                parent_id=parent_id,
            )

        stmt = select(Task)
        count_stmt = select(func.count()).select_from(Task)
        conditions = self._build_filter_conditions(status_filter, tags, parent_id)
        conditions.append(Task.embedding.isnot(None))
        for cond in conditions:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        stmt = stmt.options(selectinload(Task.children))
        stmt = stmt.order_by(
            Task.embedding.cosine_distance(text(f"'{embedding_str}'::vector"))
        )
        stmt = stmt.offset(offset).limit(top_n)

        result = await self.session.execute(stmt)
        tasks = result.scalars().all()

        return TaskListResponse(
            tasks=[TaskResponse.model_validate(t) for t in tasks],
            total=total,
            offset=offset,
        )

    def _build_filter_conditions(
        self,
        status_filter: str,
        tags: list[str] | None,
        parent_id: uuid.UUID | None,
    ) -> list:
        conditions = []

        if status_filter == "open":
            conditions.append(Task.status.in_(["todo", "in_progress"]))
        elif status_filter != "all" and status_filter in VALID_STATUSES:
            conditions.append(Task.status == status_filter)

        if tags:
            if self.is_postgres:
                conditions.append(Task.tags.overlap(tags))
            else:
                tag_conditions = [Task.tags.like(f"%{t}%") for t in tags]
                conditions.append(or_(*tag_conditions))

        if parent_id is not None:
            conditions.append(Task.parent_id == parent_id)

        return conditions

    async def delete_task(self, task_id: uuid.UUID, cascade: bool = False) -> DeleteResponse:
        task = await self._get_task_or_raise(task_id)

        child_count = await self._count_descendants(task_id)

        if child_count > 0 and not cascade:
            raise AppError(
                ErrorCode.HAS_CHILDREN,
                f"Task '{task_id}' has {child_count} child task(s). Use cascade=true to delete them.",
            )

        await self.session.delete(task)
        await self.session.commit()
        deleted_count = 1 + (child_count if cascade else 0)
        logger.info("task_deleted", task_id=str(task_id), cascade=cascade, deleted_count=deleted_count)
        return DeleteResponse(deleted_count=deleted_count)

    async def _count_descendants(self, task_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Task).where(Task.parent_id == task_id)
        )
        direct_children = result.scalar_one()
        if direct_children == 0:
            return 0

        total = direct_children
        child_result = await self.session.execute(
            select(Task.id).where(Task.parent_id == task_id)
        )
        for row in child_result.all():
            total += await self._count_descendants(row[0])
        return total

    async def decompose_task(
        self, task_id: uuid.UUID, sub_tasks: list[SubTaskInput]
    ) -> DecomposeResponse:
        parent = await self._get_task_or_raise(task_id)

        parent_depth = await self._get_depth(task_id)
        if parent_depth + 1 > MAX_DEPTH:
            raise AppError(
                ErrorCode.MAX_DEPTH_EXCEEDED,
                f"Cannot decompose: maximum nesting depth of {MAX_DEPTH} would be exceeded.",
            )

        child_ids: list[uuid.UUID] = []
        for sub in sub_tasks:
            embedding = await self._generate_embedding(sub.title, sub.description)
            child = Task(
                title=sub.title,
                description=sub.description,
                priority=sub.priority,
                due_at=sub.due_at,
                parent_id=task_id,
                status="todo",
                embedding=embedding,
            )
            self.session.add(child)
            await self.session.flush()
            child_ids.append(child.id)

        await self.session.commit()

        created: list[TaskResponse] = []
        for cid in child_ids:
            result = await self.session.execute(
                select(Task).where(Task.id == cid).options(selectinload(Task.children))
            )
            created.append(TaskResponse.model_validate(result.scalar_one()))

        parent_result = await self.session.execute(
            select(Task).where(Task.id == task_id).options(selectinload(Task.children))
        )
        parent = parent_result.scalar_one()
        logger.info("task_decomposed", task_id=str(task_id), sub_task_count=len(created))
        return DecomposeResponse(
            parent_task=TaskResponse.model_validate(parent),
            sub_tasks=created,
        )
