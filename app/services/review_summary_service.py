from __future__ import annotations

from datetime import datetime

from app.schemas import ReviewSummaryResponse
from app.services.task_service import TaskService


class ReviewSummaryService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service
        self.timezone = task_service.timezone

    async def summarize(
        self,
        from_date: datetime,
        to_date: datetime,
        tags: list[str] | None = None,
    ) -> ReviewSummaryResponse:
        context = await self.task_service.get_task_context(
            status_filter="all",
            top_n=500,
            offset=0,
            tags=tags,
        )

        created_count = 0
        completed_count = 0
        overdue_count = 0
        blocked_count = 0
        recent_progress: list[str] = []

        now = datetime.now(self.timezone)

        for task in context.tasks:
            created_at = task.created_at.astimezone(self.timezone)
            updated_at = task.updated_at.astimezone(self.timezone)
            if from_date <= created_at <= to_date:
                created_count += 1
            if task.status == "done" and from_date <= updated_at <= to_date:
                completed_count += 1
            if task.status == "blocked":
                blocked_count += 1
            if task.due_at is not None and task.status != "done" and task.due_at.astimezone(self.timezone) < now:
                overdue_count += 1
            if from_date <= updated_at <= to_date and len(recent_progress) < 5:
                recent_progress.append(f"{task.title}: {task.status}")

        return ReviewSummaryResponse(
            from_date=from_date,
            to_date=to_date,
            created_count=created_count,
            completed_count=completed_count,
            overdue_count=overdue_count,
            blocked_count=blocked_count,
            recent_progress=recent_progress,
        )
