"""MCP Server entry point for AI Task Scheduling Center.

Run via stdio: python mcp_server.py
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.database import async_session_factory
from app.services.embedding_service import EmbeddingService
from app.services.task_service import TaskService
from app.schemas import SubTaskInput, TaskCreate, TaskUpdate

mcp = FastMCP("ai-todo")

settings = get_settings()
_embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None


async def _get_service() -> TaskService:
    session = async_session_factory()
    return TaskService(session=session, embedding_service=_embedding_svc)


def _serialize(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=2)


@mcp.tool()
async def upsert_task(
    title: str = "",
    id: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int = 3,
    due_at: str | None = None,
    parent_id: str | None = None,
    tags: list[str] | None = None,
    meta_data: dict | None = None,
    thinking_process: str | None = None,
) -> str:
    """当用户提到新的任务、修改任务或改变进度时调用。不提供 id 时为新建，提供 id 时为更新已有任务。"""
    svc = await _get_service()
    try:
        parsed_due = datetime.fromisoformat(due_at) if due_at else None
        parsed_parent = uuid.UUID(parent_id) if parent_id else None

        if id:
            result = await svc.upsert_task(
                update_data=TaskUpdate(
                    title=title or None,
                    description=description,
                    status=status,
                    priority=priority,
                    due_at=parsed_due,
                    parent_id=parsed_parent,
                    tags=tags,
                    meta_data=meta_data,
                    thinking_process=thinking_process,
                ),
                task_id=uuid.UUID(id),
            )
        else:
            if not title:
                return _serialize({"error": "title is required when creating a new task"})
            result = await svc.upsert_task(
                data=TaskCreate(
                    title=title,
                    description=description,
                    status=status,
                    priority=priority,
                    due_at=parsed_due,
                    parent_id=parsed_parent,
                    tags=tags or [],
                    meta_data=meta_data,
                    thinking_process=thinking_process,
                ),
            )
        return _serialize(result.model_dump())
    finally:
        await svc.session.close()


@mcp.tool()
async def get_task_context(
    status_filter: str = "open",
    top_n: int = 20,
    offset: int = 0,
    tags: list[str] | None = None,
    query: str | None = None,
    parent_id: str | None = None,
) -> str:
    """获取当前相关的所有待办项，用于辅助 AI 决策。支持按状态、标签、语义进行过滤。"""
    svc = await _get_service()
    try:
        result = await svc.get_task_context(
            status_filter=status_filter,
            top_n=top_n,
            offset=offset,
            tags=tags,
            query=query,
            parent_id=uuid.UUID(parent_id) if parent_id else None,
        )
        return _serialize(result.model_dump())
    finally:
        await svc.session.close()


@mcp.tool()
async def delete_task(task_id: str, cascade: bool = False) -> str:
    """删除指定任务。默认存在子任务时拒绝删除，设置 cascade=true 可级联删除所有子任务。"""
    svc = await _get_service()
    try:
        result = await svc.delete_task(uuid.UUID(task_id), cascade=cascade)
        return _serialize(result.model_dump())
    finally:
        await svc.session.close()


@mcp.tool()
async def decompose_task(task_id: str, sub_tasks: list[dict]) -> str:
    """将一个任务拆解为多个子任务。每个子任务需包含 title(必填), description(可选), priority(可选), due_at(可选)。"""
    svc = await _get_service()
    try:
        parsed_subs = []
        for s in sub_tasks:
            parsed_subs.append(SubTaskInput(
                title=s["title"],
                description=s.get("description"),
                priority=s.get("priority", 3),
                due_at=datetime.fromisoformat(s["due_at"]) if s.get("due_at") else None,
            ))
        result = await svc.decompose_task(uuid.UUID(task_id), parsed_subs)
        return _serialize(result.model_dump())
    finally:
        await svc.session.close()


if __name__ == "__main__":
    mcp.run()
