from __future__ import annotations

from datetime import datetime

from app.schemas import SuggestedTask, SuggestedTaskListResponse, StaleTaskListResponse, TaskListResponse, TaskResponse
from app.services.task_service import TaskService


class ExecutionSuggestionService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service
        self.timezone = task_service.timezone

    def _score_task(self, task: TaskResponse, now: datetime) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        score += max(0, 6 - task.priority) * 10
        reasons.append(f"priority_{task.priority}")

        if task.due_at is not None:
            due_at = task.due_at.astimezone(self.timezone)
            if due_at < now:
                score += 50
                reasons.append("overdue")
            elif due_at.date() == now.date():
                score += 30
                reasons.append("due_today")
            elif (due_at - now).days <= 2:
                score += 15
                reasons.append("due_soon")

        age_hours = max((now - task.updated_at.astimezone(self.timezone)).total_seconds() / 3600, 0)
        if age_hours >= 24:
            score += min(age_hours / 4, 20)
            reasons.append("stale")

        if task.parent_id is not None:
            score += 5
            reasons.append("part_of_larger_goal")

        return score, reasons

    async def get_suggested_today(
        self,
        top_n: int = 10,
        tags: list[str] | None = None,
    ) -> SuggestedTaskListResponse:
        now = datetime.now(self.timezone)
        ready = await self.task_service.list_ready_tasks(top_n=100, offset=0, tags=tags)
        overdue = await self.task_service.list_overdue_tasks(top_n=100)
        overdue_ids = {item.id for item in overdue.tasks}

        suggestions: list[SuggestedTask] = []
        for task in ready.tasks:
            score, reasons = self._score_task(task, now)
            if task.id in overdue_ids and "overdue" not in reasons:
                reasons.append("overdue")
                score += 50
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

    async def get_stale_tasks(self, top_n: int = 20) -> StaleTaskListResponse:
        now = datetime.now(self.timezone)
        recent = await self.task_service.get_task_context(status_filter="open", top_n=100, offset=0)
        stale_tasks = [
            task
            for task in recent.tasks
            if (now - task.updated_at.astimezone(self.timezone)).total_seconds() >= 48 * 3600
        ][:top_n]
        return StaleTaskListResponse(tasks=stale_tasks, total=len(stale_tasks))
