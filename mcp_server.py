"""MCP Server entry point for AI Task Scheduling Center.

Run via stdio: python mcp_server.py
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.database import async_session_factory
from app.errors import AppError
from app.services.blocked_recovery_service import BlockedRecoveryService
from app.services.embedding_service import EmbeddingService
from app.services.execution_suggestion_service import ExecutionSuggestionService
from app.services.obsidian_index_service import ObsidianIndexService
from app.services.obsidian_sync_service import ObsidianExportService
from app.services.notification_service import (
    AlertDeliveryService,
    DingTalkNotificationProvider,
    WebhookNotificationProvider,
)
from app.services.reminder_service import ReminderService
from app.services.review_summary_service import ReviewSummaryService
from app.services.task_intake_service import TaskIntakeService
from app.services.task_parsing_service import TaskParsingService
from app.services.task_planning_service import TaskPlanningService
from app.services.task_service import TaskService
from app.services.workspace_service import WorkspaceService
from app.schemas import SubTaskInput, TaskCommentCreate, TaskCreate, TaskDraftOverride, TaskUpdate

mcp = FastMCP("ai-todo")

settings = get_settings()
_embedding_svc = EmbeddingService(settings) if settings.embedding_api_key else None
_task_parsing_svc = TaskParsingService(settings)


async def _get_service() -> TaskService:
    session = async_session_factory()
    return TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )


async def _get_intake_service() -> TaskIntakeService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return TaskIntakeService(task_service=task_service, parsing_service=_task_parsing_svc)


async def _get_planning_service() -> TaskPlanningService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return TaskPlanningService(task_service=task_service)


async def _get_reminder_service() -> ReminderService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return ReminderService(task_service=task_service)


async def _get_workspace_service() -> WorkspaceService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return WorkspaceService(task_service=task_service)


async def _get_alert_delivery_service() -> AlertDeliveryService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    providers = {}
    if settings.notification_webhook_url:
        providers["webhook"] = WebhookNotificationProvider(settings.notification_webhook_url)
    if settings.notification_dingtalk_webhook_url:
        providers["dingtalk"] = DingTalkNotificationProvider(settings.notification_dingtalk_webhook_url)
    return AlertDeliveryService(
        task_service=task_service,
        providers=providers,
        repeat_window_hours=settings.notification_repeat_window_hours,
    )


async def _get_execution_suggestion_service() -> ExecutionSuggestionService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return ExecutionSuggestionService(task_service=task_service)


async def _get_blocked_recovery_service() -> BlockedRecoveryService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return BlockedRecoveryService(task_service=task_service)


async def _get_review_summary_service() -> ReviewSummaryService:
    session = async_session_factory()
    task_service = TaskService(
        session=session,
        embedding_service=_embedding_svc,
        timezone_name=settings.parsing_timezone,
    )
    return ReviewSummaryService(task_service=task_service)


def _serialize(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=2)


@mcp.tool()
async def upsert_task(
    title: str = "",
    id: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int | None = None,
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
                    priority=priority or 3,
                    due_at=parsed_due,
                    parent_id=parsed_parent,
                    tags=tags or [],
                    meta_data=meta_data,
                    thinking_process=thinking_process,
                ),
            )
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
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
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def delete_task(task_id: str, cascade: bool = False) -> str:
    """删除指定任务。默认存在子任务时拒绝删除，设置 cascade=true 可级联删除所有子任务。"""
    svc = await _get_service()
    try:
        result = await svc.delete_task(uuid.UUID(task_id), cascade=cascade)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
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
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def add_task_dependency(task_id: str, depends_on_task_id: str) -> str:
    """为任务添加依赖关系，表示 task_id 必须等待 depends_on_task_id 完成后才能执行。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_write_service()
        try:
            result = await svc.add_dependency(uuid.UUID(task_id), uuid.UUID(depends_on_task_id))
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.session.close()
    svc = await _get_service()
    try:
        result = await svc.add_dependency(uuid.UUID(task_id), uuid.UUID(depends_on_task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def list_task_dependencies(task_id: str) -> str:
    """列出指定任务的依赖关系。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_write_service()
        try:
            result = await svc.list_dependencies(uuid.UUID(task_id))
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.session.close()
    svc = await _get_service()
    try:
        result = await svc.list_dependencies(uuid.UUID(task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def remove_task_dependency(task_id: str, dependency_id: str) -> str:
    """删除指定任务的一条依赖关系。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_write_service()
        try:
            result = await svc.remove_dependency(uuid.UUID(task_id), uuid.UUID(dependency_id))
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.session.close()
    svc = await _get_service()
    try:
        result = await svc.remove_dependency(uuid.UUID(task_id), uuid.UUID(dependency_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_ready_to_start_tasks(
    top_n: int = 20,
    offset: int = 0,
    tags: list[str] | None = None,
) -> str:
    """获取当前没有未完成依赖、可以直接启动的任务列表。"""
    svc = await _get_service()
    try:
        result = await svc.list_ready_tasks(top_n=top_n, offset=offset, tags=tags)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def add_task_comment(
    task_id: str,
    content: str,
    type: str = "comment",
    meta_data: dict | None = None,
) -> str:
    """为任务添加评论、进展、失败记录或系统备注。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_write_service()
        try:
            result = await svc.add_comment(
                uuid.UUID(task_id),
                TaskCommentCreate(type=type, content=content, meta_data=meta_data),
            )
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.session.close()
    svc = await _get_service()
    try:
        result = await svc.add_comment(
            uuid.UUID(task_id),
            TaskCommentCreate(type=type, content=content, meta_data=meta_data),
        )
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_task_timeline(task_id: str) -> str:
    """获取任务评论与系统事件时间线。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_write_service()
        try:
            result = await svc.list_comments(uuid.UUID(task_id))
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.session.close()
    svc = await _get_service()
    try:
        result = await svc.list_comments(uuid.UUID(task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_today(top_n: int = 20) -> str:
    """获取今天到期的任务。"""
    svc = await _get_service()
    try:
        result = await svc.list_today_tasks(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_overdue(top_n: int = 20) -> str:
    """获取已逾期且未完成的任务。"""
    svc = await _get_service()
    try:
        result = await svc.list_overdue_tasks(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_blocked(top_n: int = 20) -> str:
    """获取当前处于 blocked 状态的任务。"""
    svc = await _get_service()
    try:
        result = await svc.list_blocked_tasks(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_recently_updated(top_n: int = 20) -> str:
    """获取最近更新的任务。"""
    svc = await _get_service()
    try:
        result = await svc.list_recently_updated_tasks(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_alerts(top_n: int = 20) -> str:
    """获取逾期、即将到期和长期阻塞任务告警。"""
    svc = await _get_service()
    try:
        result = await svc.list_alerts(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def get_workspace_dashboard(top_n: int = 10) -> str:
    """获取工作台总览，包括 today、overdue、blocked、ready-to-start、recently-updated 和 alerts。"""
    svc = await _get_workspace_service()
    try:
        result = await svc.get_dashboard(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def suggest_task_decomposition(task_id: str) -> str:
    """为一个任务生成建议的拆解子任务。"""
    svc = await _get_planning_service()
    try:
        result = await svc.suggest_decomposition(uuid.UUID(task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def apply_task_suggestions(task_id: str, indices: list[int]) -> str:
    """选择建议拆解项并创建为子任务。"""
    svc = await _get_planning_service()
    try:
        result = await svc.apply_suggestions(uuid.UUID(task_id), indices)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def plan_task_execution(task_id: str) -> str:
    """为一个任务生成结构化执行计划。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_planning_service()
        try:
            result = await svc.generate_plan(uuid.UUID(task_id))
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.query_service.session.close()
    svc = await _get_planning_service()
    try:
        result = await svc.generate_plan(uuid.UUID(task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def apply_task_plan(task_id: str, indices: list[int] | None = None) -> str:
    """将任务计划中的建议批量应用为子任务和依赖。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_planning_service()
        try:
            result = await svc.apply_plan(uuid.UUID(task_id), indices)
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.query_service.session.close()
    svc = await _get_planning_service()
    try:
        result = await svc.apply_plan(uuid.UUID(task_id), indices)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def scan_reminders(top_n: int = 20) -> str:
    """执行一次提醒扫描，返回当前告警快照。"""
    svc = await _get_reminder_service()
    try:
        result = await svc.scan(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def dispatch_alert_notifications(top_n: int = 20, force: bool = False) -> str:
    """将当前 alerts 主动发送到已配置的 webhook 渠道。"""
    svc = await _get_alert_delivery_service()
    try:
        result = await svc.dispatch_alerts(top_n=top_n, force=force)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def test_notification_channel(channel: str | None = None, message: str = "AITodo notification channel test") -> str:
    """测试当前配置的通知渠道是否可用。"""
    svc = await _get_alert_delivery_service()
    try:
        result = await svc.test_channel(message=message, channel=channel)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def get_suggested_today_tasks(top_n: int = 10, tags: list[str] | None = None) -> str:
    """获取今天建议优先处理的任务列表。"""
    svc = await _get_execution_suggestion_service()
    try:
        result = await svc.get_suggested_today(top_n=top_n, tags=tags)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def get_stale_tasks(top_n: int = 20) -> str:
    """获取长时间未推进的开放任务。"""
    svc = await _get_execution_suggestion_service()
    try:
        result = await svc.get_stale_tasks(top_n=top_n)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def get_task_recovery_suggestions(task_id: str) -> str:
    """获取 blocked 任务的恢复建议。"""
    svc = await _get_blocked_recovery_service()
    try:
        result = await svc.get_recovery_suggestions(uuid.UUID(task_id))
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def get_review_summary(
    days: int = 7,
    tags: list[str] | None = None,
) -> str:
    """获取最近一段时间的任务回顾摘要。"""
    svc = await _get_review_summary_service()
    try:
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=days)
        result = await svc.summarize(from_date=from_date, to_date=to_date, tags=tags)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


@mcp.tool()
async def parse_task_input(text: str) -> str:
    """将自然语言任务描述解析为结构化任务草稿，供 AI 在正式入库前预览和确认。"""
    try:
        result = await _task_parsing_svc.parse_text(text)
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})


@mcp.tool()
async def parse_and_create_task(
    text: str,
    parent_id: str | None = None,
    min_confidence: float = 0.6,
    force_create: bool = False,
    selected_draft_index: int = 0,
    override: dict | None = None,
) -> str:
    """先将自然语言解析为任务草稿，再按置信度阈值决定是否正式入库。"""
    if settings.aitodo_storage_mode == "obsidian_native":
        svc = await _get_obsidian_native_intake_service()
        try:
            result = await svc.parse_and_create(
                text=text,
                parent_id=uuid.UUID(parent_id) if parent_id else None,
                min_confidence=min_confidence,
                force_create=force_create,
                selected_draft_index=selected_draft_index,
                override=TaskDraftOverride(**override) if override else None,
            )
            return _serialize(result.model_dump())
        except AppError as exc:
            return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
        finally:
            await svc.write_service.session.close()
    svc = await _get_intake_service()
    try:
        result = await svc.parse_and_create(
            text=text,
            parent_id=uuid.UUID(parent_id) if parent_id else None,
            min_confidence=min_confidence,
            force_create=force_create,
            selected_draft_index=selected_draft_index,
            override=TaskDraftOverride(**override) if override else None,
        )
        return _serialize(result.model_dump())
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.task_service.session.close()


async def _get_obsidian_export_service() -> ObsidianExportService:
    session = async_session_factory()
    return ObsidianExportService(session=session, settings=settings)


@mcp.tool()
async def export_task_to_obsidian(task_id: str) -> str:
    """将指定 AITodo 任务导出为 Obsidian Vault 中的 AI-Todo/tasks/<task_id>.md 文件。"""
    svc = await _get_obsidian_export_service()
    try:
        result = await svc.export_task(uuid.UUID(task_id))
        return _serialize(result)
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def export_all_tasks_to_obsidian(limit: int = 100) -> str:
    """批量导出 AITodo 任务到 Obsidian Vault 的 AI-Todo/ 前缀下。"""
    svc = await _get_obsidian_export_service()
    try:
        result = await svc.export_all_tasks(limit=limit)
        return _serialize(result)
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()



async def _get_obsidian_native_planning_service() -> ObsidianNativeTaskPlanningService:
    session = async_session_factory()
    query_service = ObsidianNativeTaskQueryService(session=session, timezone_name=settings.parsing_timezone)
    write_service = ObsidianNativeTaskWriteService(session=session, settings=settings)
    return ObsidianNativeTaskPlanningService(query_service=query_service, write_service=write_service)


async def _get_obsidian_native_intake_service() -> ObsidianNativeTaskIntakeService:
    write_service = await _get_obsidian_native_write_service()
    return ObsidianNativeTaskIntakeService(write_service=write_service, parsing_service=_task_parsing_svc)


async def _get_obsidian_native_write_service() -> ObsidianNativeTaskWriteService:
    session = async_session_factory()
    return ObsidianNativeTaskWriteService(session=session, settings=settings)


async def _get_obsidian_index_service() -> ObsidianIndexService:
    session = async_session_factory()
    return ObsidianIndexService(session=session, settings=settings)


@mcp.tool()
async def rebuild_obsidian_task_index(prefix: str = "AI-Todo/tasks/", limit: int = 500) -> str:
    """从 Obsidian Sync 远端文件快照下载并解析 AI-Todo Markdown，重建 AITodo 可查询索引。"""
    svc = await _get_obsidian_index_service()
    try:
        result = await svc.rebuild_index(prefix=prefix, limit=limit)
        return _serialize(result)
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()


@mcp.tool()
async def list_obsidian_indexed_tasks(status: str | None = None, limit: int = 100) -> str:
    """列出从 Obsidian Markdown 重建出的任务索引。"""
    svc = await _get_obsidian_index_service()
    try:
        items = await svc.list_indexed_tasks(status=status, limit=limit)
        return _serialize({
            "items": [
                {
                    "task_id": item.task_id,
                    "title": item.title,
                    "status": item.status,
                    "priority": item.priority,
                    "path": item.path,
                    "version": item.version,
                    "content_hash": item.content_hash,
                }
                for item in items
            ],
            "total": len(items),
        })
    except AppError as exc:
        return _serialize({"error": {"code": exc.code.value, "message": exc.message}})
    finally:
        await svc.session.close()

if __name__ == "__main__":
    mcp.run()
