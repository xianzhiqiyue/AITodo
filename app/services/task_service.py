from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, exists, or_, func, select, text
from sqlalchemy.orm import Load, aliased, selectinload

from app.errors import AppError, ErrorCode
from app.models import Task, TaskComment, TaskDependency
from app.schemas import (
    AlertItem,
    AlertListResponse,
    DecomposeResponse,
    DeleteResponse,
    ReadyTaskListResponse,
    SubTaskInput,
    TaskCommentCreate,
    TaskCommentListResponse,
    TaskCommentResponse,
    TaskDependencyListResponse,
    TaskDependencyResponse,
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
VALID_COMMENT_TYPES = {"comment", "progress", "failure"}
MAX_DEPTH = 5
ALLOWED_TRANSITIONS = {
    "todo": {"in_progress", "blocked"},
    "in_progress": {"done", "blocked"},
    "done": {"blocked"},
    "blocked": {"todo", "in_progress"},
}


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService | None = None,
        is_postgres: bool = True,
        timezone_name: str = "UTC",
    ):
        self.session = session
        self.embedding_service = embedding_service
        self.is_postgres = is_postgres
        self.timezone = ZoneInfo(timezone_name)

    def _task_tree_load_options(self) -> list[Load]:
        options: list[Load] = []
        current = selectinload(Task.children)
        options.append(current)
        for _ in range(MAX_DEPTH - 1):
            current = current.selectinload(Task.children)
            options.append(current)
        return options

    async def _get_dependency_or_raise(self, dependency_id: uuid.UUID) -> TaskDependency:
        result = await self.session.execute(
            select(TaskDependency).where(TaskDependency.id == dependency_id)
        )
        dependency = result.scalar_one_or_none()
        if dependency is None:
            raise AppError(
                ErrorCode.TASK_DEPENDENCY_NOT_FOUND,
                f"Task dependency '{dependency_id}' does not exist.",
            )
        return dependency

    async def _log_task_event(
        self,
        task_id: uuid.UUID,
        content: str,
        meta_data: dict | None = None,
    ) -> None:
        self.session.add(
            TaskComment(
                task_id=task_id,
                type="event",
                content=content,
                meta_data=meta_data or {},
            )
        )

    async def _get_task_or_raise(self, task_id: uuid.UUID) -> Task:
        result = await self.session.execute(
            select(Task).where(Task.id == task_id).options(*self._task_tree_load_options())
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

        if new_status != task.status and new_status not in ALLOWED_TRANSITIONS[task.status]:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid status transition from '{task.status}' to '{new_status}'.",
            )

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

            dependency_result = await self.session.execute(
                select(func.count()).select_from(TaskDependency).join(
                    Task,
                    Task.id == TaskDependency.depends_on_task_id,
                ).where(
                    TaskDependency.task_id == task.id,
                    Task.status != "done",
                )
            )
            blocked_dependencies = dependency_result.scalar_one()
            if blocked_dependencies > 0:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Cannot mark task as done: {blocked_dependencies} dependency task(s) are not yet done.",
                )

    async def _generate_embedding(self, title: str, description: str | None) -> list[float] | None:
        if self.embedding_service is None:
            return None
        text_content = title
        if description:
            text_content = f"{title}\n{description}"
        return await self.embedding_service.generate_embedding(text_content)

    async def _validate_parent_assignment(
        self,
        *,
        task_id: uuid.UUID | None,
        parent_id: uuid.UUID | None,
    ) -> None:
        if parent_id is None:
            return

        if task_id is not None and task_id == parent_id:
            raise AppError(
                ErrorCode.TASK_CYCLE_DETECTED,
                "Task cannot be its own parent.",
            )

        parent_depth = await self._get_depth(parent_id)
        if parent_depth + 1 > MAX_DEPTH:
            raise AppError(ErrorCode.MAX_DEPTH_EXCEEDED, f"Maximum nesting depth of {MAX_DEPTH} exceeded.")

        if task_id is None:
            return

        current_id = parent_id
        while current_id is not None:
            if current_id == task_id:
                raise AppError(
                    ErrorCode.TASK_CYCLE_DETECTED,
                    "Task parent assignment would create a cycle.",
                )
            result = await self.session.execute(
                select(Task.parent_id).where(Task.id == current_id)
            )
            row = result.first()
            if row is None:
                raise AppError(ErrorCode.TASK_NOT_FOUND, f"Parent task '{current_id}' does not exist.")
            current_id = row[0]

    async def _validate_dependency_assignment(
        self,
        *,
        task_id: uuid.UUID,
        depends_on_task_id: uuid.UUID,
    ) -> None:
        if task_id == depends_on_task_id:
            raise AppError(
                ErrorCode.TASK_DEPENDENCY_CYCLE,
                "Task cannot depend on itself.",
            )

        await self._get_task_or_raise(task_id)
        await self._get_task_or_raise(depends_on_task_id)

        result = await self.session.execute(
            select(TaskDependency.id).where(
                TaskDependency.task_id == task_id,
                TaskDependency.depends_on_task_id == depends_on_task_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Task dependency already exists.",
            )

        current_ids = [depends_on_task_id]
        visited: set[uuid.UUID] = set()
        while current_ids:
            result = await self.session.execute(
                select(TaskDependency.depends_on_task_id).where(
                    TaskDependency.task_id.in_(current_ids)
                )
            )
            next_ids: list[uuid.UUID] = []
            for dep_id in result.scalars():
                if dep_id == task_id:
                    raise AppError(
                        ErrorCode.TASK_DEPENDENCY_CYCLE,
                        "Task dependency would create a cycle.",
                    )
                if dep_id not in visited:
                    visited.add(dep_id)
                    next_ids.append(dep_id)
            current_ids = next_ids

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

        await self._validate_parent_assignment(task_id=None, parent_id=data.parent_id)

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
        result = await self.session.execute(
            select(Task).where(Task.id == task.id).options(*self._task_tree_load_options())
        )
        task = result.scalar_one()
        await self._log_task_event(task.id, "Task created.", {"title": task.title})
        await self.session.commit()
        logger.info("task_created", task_id=str(task.id), title=task.title)
        return TaskResponse.model_validate(task)

    async def _update_task(self, task_id: uuid.UUID, data: TaskUpdate) -> TaskResponse:
        task = await self._get_task_or_raise(task_id)
        provided_fields = data.model_fields_set

        if "status" in provided_fields and data.status is not None:
            previous_status = task.status
            await self._validate_status_transition(task, data.status)
            task.status = data.status
            if previous_status != data.status:
                await self._log_task_event(
                    task.id,
                    f"Status changed from {previous_status} to {data.status}.",
                    {"from": previous_status, "to": data.status},
                )

        if "title" in provided_fields and data.title is not None:
            task.title = data.title
        if "description" in provided_fields:
            task.description = data.description
        if "priority" in provided_fields and data.priority is not None:
            task.priority = data.priority
        if "due_at" in provided_fields:
            task.due_at = data.due_at
        if "tags" in provided_fields and data.tags is not None:
            task.tags = data.tags

        if "parent_id" in provided_fields:
            await self._validate_parent_assignment(task_id=task.id, parent_id=data.parent_id)
            task.parent_id = data.parent_id

        if "meta_data" in provided_fields and data.meta_data is not None:
            task.meta_data = {**task.meta_data, **data.meta_data}
        if "thinking_process" in provided_fields and data.thinking_process is not None:
            task.meta_data = {**task.meta_data, "thinking": data.thinking_process}

        needs_reembed = "title" in provided_fields or "description" in provided_fields
        if needs_reembed:
            embedding = await self._generate_embedding(task.title, task.description)
            if embedding is not None:
                task.embedding = embedding

        await self.session.flush()
        await self.session.commit()
        result = await self.session.execute(
            select(Task).where(Task.id == task.id).options(*self._task_tree_load_options())
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

    async def add_dependency(
        self,
        task_id: uuid.UUID,
        depends_on_task_id: uuid.UUID,
    ) -> TaskDependencyResponse:
        await self._validate_dependency_assignment(
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
        )

        dependency = TaskDependency(
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
        )
        self.session.add(dependency)
        await self.session.flush()
        await self._log_task_event(
            task_id,
            "Task dependency added.",
            {"depends_on_task_id": str(depends_on_task_id)},
        )
        await self.session.commit()
        logger.info(
            "task_dependency_created",
            dependency_id=str(dependency.id),
            task_id=str(task_id),
            depends_on_task_id=str(depends_on_task_id),
        )
        return TaskDependencyResponse.model_validate(dependency)

    async def list_dependencies(self, task_id: uuid.UUID) -> TaskDependencyListResponse:
        await self._get_task_or_raise(task_id)
        result = await self.session.execute(
            select(TaskDependency)
            .where(TaskDependency.task_id == task_id)
            .order_by(TaskDependency.created_at.asc())
        )
        dependencies = result.scalars().all()
        return TaskDependencyListResponse(
            dependencies=[TaskDependencyResponse.model_validate(dep) for dep in dependencies]
        )

    async def remove_dependency(
        self,
        task_id: uuid.UUID,
        dependency_id: uuid.UUID,
    ) -> DeleteResponse:
        dependency = await self._get_dependency_or_raise(dependency_id)
        if dependency.task_id != task_id:
            raise AppError(
                ErrorCode.TASK_DEPENDENCY_NOT_FOUND,
                f"Task dependency '{dependency_id}' does not belong to task '{task_id}'.",
            )

        await self.session.delete(dependency)
        await self._log_task_event(
            task_id,
            "Task dependency removed.",
            {"dependency_id": str(dependency_id)},
        )
        await self.session.commit()
        logger.info(
            "task_dependency_deleted",
            dependency_id=str(dependency_id),
            task_id=str(task_id),
        )
        return DeleteResponse(deleted_count=1)

    async def list_ready_tasks(
        self,
        top_n: int = 20,
        offset: int = 0,
        tags: list[str] | None = None,
    ) -> ReadyTaskListResponse:
        top_n = min(max(top_n, 1), 100)
        dependency_task = aliased(Task)
        dependency_block_exists = exists(
            select(1)
            .select_from(TaskDependency)
            .join(dependency_task, dependency_task.id == TaskDependency.depends_on_task_id)
            .where(
                and_(
                    TaskDependency.task_id == Task.id,
                    dependency_task.status != "done",
                )
            )
        )

        stmt = (
            select(Task)
            .where(Task.status.in_(["todo", "in_progress"]))
            .where(~dependency_block_exists)
        )
        count_stmt = (
            select(func.count()).select_from(Task)
            .where(Task.status.in_(["todo", "in_progress"]))
            .where(~dependency_block_exists)
        )

        if tags:
            if self.is_postgres:
                tag_cond = Task.tags.overlap(tags)
            else:
                tag_cond = or_(*[Task.tags.like(f"%{t}%") for t in tags])
            stmt = stmt.where(tag_cond)
            count_stmt = count_stmt.where(tag_cond)

        stmt = stmt.options(*self._task_tree_load_options())
        stmt = stmt.order_by(Task.priority.asc(), Task.due_at.asc().nullslast(), Task.created_at.desc())
        stmt = stmt.offset(offset).limit(top_n)

        total = (await self.session.execute(count_stmt)).scalar_one()
        tasks = (await self.session.execute(stmt)).scalars().all()
        return ReadyTaskListResponse(
            tasks=[TaskResponse.model_validate(t) for t in tasks],
            total=total,
        )

    async def add_comment(
        self,
        task_id: uuid.UUID,
        data: TaskCommentCreate,
    ) -> TaskCommentResponse:
        await self._get_task_or_raise(task_id)
        if data.type not in VALID_COMMENT_TYPES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid comment type '{data.type}'.",
            )
        comment = TaskComment(
            task_id=task_id,
            type=data.type,
            content=data.content,
            meta_data=data.meta_data or {},
        )
        self.session.add(comment)
        await self.session.flush()
        await self.session.commit()
        logger.info("task_comment_created", task_id=str(task_id), comment_id=str(comment.id), type=data.type)
        return TaskCommentResponse.model_validate(comment)

    async def list_comments(self, task_id: uuid.UUID) -> TaskCommentListResponse:
        await self._get_task_or_raise(task_id)
        result = await self.session.execute(
            select(TaskComment)
            .where(TaskComment.task_id == task_id)
            .order_by(TaskComment.created_at.asc())
        )
        comments = result.scalars().all()
        return TaskCommentListResponse(
            comments=[TaskCommentResponse.model_validate(comment) for comment in comments]
        )

    async def list_today_tasks(self, top_n: int = 20) -> TaskListResponse:
        now = datetime.now(self.timezone)
        tasks = (
            await self.session.execute(
                select(Task)
                .where(Task.due_at.isnot(None))
                .where(Task.status != "done")
                .options(*self._task_tree_load_options())
                .order_by(Task.priority.asc(), Task.due_at.asc())
            )
        ).scalars().all()
        tasks = [
            task for task in tasks
            if task.due_at and task.due_at.astimezone(self.timezone).date() == now.date()
        ][:top_n]
        return TaskListResponse(
            tasks=[TaskResponse.model_validate(task) for task in tasks],
            total=len(tasks),
            offset=0,
        )

    async def list_overdue_tasks(self, top_n: int = 20) -> TaskListResponse:
        now = datetime.now(self.timezone)
        tasks = (
            await self.session.execute(
                select(Task)
                .where(Task.due_at.isnot(None))
                .where(Task.status != "done")
                .options(*self._task_tree_load_options())
                .order_by(Task.due_at.asc(), Task.priority.asc())
            )
        ).scalars().all()
        tasks = [
            task for task in tasks
            if task.due_at and task.due_at.astimezone(self.timezone) < now
        ][:top_n]
        return TaskListResponse(
            tasks=[TaskResponse.model_validate(task) for task in tasks],
            total=len(tasks),
            offset=0,
        )

    async def list_blocked_tasks(self, top_n: int = 20) -> TaskListResponse:
        stmt = (
            select(Task)
            .where(Task.status == "blocked")
            .options(*self._task_tree_load_options())
            .order_by(Task.priority.asc(), Task.updated_at.desc())
            .limit(top_n)
        )
        tasks = (await self.session.execute(stmt)).scalars().all()
        return TaskListResponse(
            tasks=[TaskResponse.model_validate(task) for task in tasks],
            total=len(tasks),
            offset=0,
        )

    async def list_recently_updated_tasks(self, top_n: int = 20) -> TaskListResponse:
        stmt = (
            select(Task)
            .options(*self._task_tree_load_options())
            .order_by(Task.updated_at.desc())
            .limit(top_n)
        )
        tasks = (await self.session.execute(stmt)).scalars().all()
        return TaskListResponse(
            tasks=[TaskResponse.model_validate(task) for task in tasks],
            total=len(tasks),
            offset=0,
        )

    async def list_alerts(self, top_n: int = 20) -> AlertListResponse:
        now = datetime.now(self.timezone)
        soon = now + timedelta(days=1)
        alerts: list[AlertItem] = []

        overdue_result = await self.session.execute(
            select(Task)
            .where(Task.due_at.isnot(None))
            .where(Task.status != "done")
            .options(*self._task_tree_load_options())
            .order_by(Task.due_at.asc(), Task.priority.asc())
        )
        for task in overdue_result.scalars():
            if task.due_at and task.due_at.astimezone(self.timezone) < now and len(alerts) < top_n:
                alerts.append(AlertItem(task=TaskResponse.model_validate(task), reason="overdue"))

        if len(alerts) < top_n:
            soon_result = await self.session.execute(
                select(Task)
                .where(Task.due_at.isnot(None))
                .where(Task.status != "done")
                .options(*self._task_tree_load_options())
                .order_by(Task.due_at.asc(), Task.priority.asc())
            )
            existing_ids = {item.task.id for item in alerts}
            for task in soon_result.scalars():
                due_at = task.due_at.astimezone(self.timezone) if task.due_at else None
                if task.id not in existing_ids and due_at is not None and now <= due_at <= soon and len(alerts) < top_n:
                    alerts.append(AlertItem(task=TaskResponse.model_validate(task), reason="due_soon"))

        if len(alerts) < top_n:
            blocked_result = await self.session.execute(
                select(Task)
                .where(Task.status == "blocked")
                .options(*self._task_tree_load_options())
                .order_by(Task.updated_at.asc(), Task.priority.asc())
                .limit(top_n)
            )
            existing_ids = {item.task.id for item in alerts}
            for task in blocked_result.scalars():
                if task.id not in existing_ids and len(alerts) < top_n:
                    alerts.append(AlertItem(task=TaskResponse.model_validate(task), reason="blocked"))

        return AlertListResponse(alerts=alerts, total=len(alerts))

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
            keyword_cond = or_(
                Task.title.ilike(like_pattern),
                Task.description.ilike(like_pattern),
            )
            stmt = stmt.where(keyword_cond)
            count_stmt = count_stmt.where(keyword_cond)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.options(*self._task_tree_load_options())
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
        stmt = stmt.options(*self._task_tree_load_options())
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

        await self._log_task_event(
            task_id,
            "Task deleted.",
            {"cascade": cascade, "deleted_count": 1 + (child_count if cascade else 0)},
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
            await self._log_task_event(child.id, "Task created by decomposition.", {"parent_id": str(task_id)})

        await self._log_task_event(
            task_id,
            f"Task decomposed into {len(child_ids)} sub-task(s).",
            {"sub_task_count": len(child_ids)},
        )
        await self.session.commit()

        created: list[TaskResponse] = []
        for cid in child_ids:
            result = await self.session.execute(
                select(Task).where(Task.id == cid).options(*self._task_tree_load_options())
            )
            created.append(TaskResponse.model_validate(result.scalar_one()))

        parent_result = await self.session.execute(
            select(Task).where(Task.id == task_id).options(*self._task_tree_load_options())
        )
        parent = parent_result.scalar_one()
        logger.info("task_decomposed", task_id=str(task_id), sub_task_count=len(created))
        return DecomposeResponse(
            parent_task=TaskResponse.model_validate(parent),
            sub_tasks=created,
        )
