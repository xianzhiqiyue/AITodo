from __future__ import annotations

from app.schemas import TaskListResponse, WorkspaceDashboardResponse
from app.services.execution_suggestion_service import ExecutionSuggestionService
from app.services.task_service import TaskService


class WorkspaceService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service

    async def get_dashboard(self, top_n: int = 10) -> WorkspaceDashboardResponse:
        execution_service = ExecutionSuggestionService(self.task_service)
        today = await self.task_service.list_today_tasks(top_n=top_n)
        overdue = await self.task_service.list_overdue_tasks(top_n=top_n)
        blocked = await self.task_service.list_blocked_tasks(top_n=top_n)
        ready_to_start = await self.task_service.list_ready_tasks(top_n=top_n)
        recently_updated = await self.task_service.list_recently_updated_tasks(top_n=top_n)
        alerts = await self.task_service.list_alerts(top_n=top_n)
        suggested_today = await execution_service.get_suggested_today(top_n=top_n)
        stale_tasks = await execution_service.get_stale_tasks(top_n=top_n)

        return WorkspaceDashboardResponse(
            today=today,
            overdue=overdue,
            blocked=blocked,
            ready_to_start=ready_to_start,
            recently_updated=recently_updated,
            alerts=alerts,
            suggested_today=suggested_today,
            stale_tasks=TaskListResponse(tasks=stale_tasks.tasks, total=stale_tasks.total, offset=0),
        )
