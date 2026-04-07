from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import ReminderScanResponse
from app.services.task_service import TaskService


class ReminderService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service

    async def scan(self, top_n: int = 20) -> ReminderScanResponse:
        alerts = await self.task_service.list_alerts(top_n=top_n)
        return ReminderScanResponse(
            scanned_at=datetime.now(timezone.utc),
            alerts=alerts.alerts,
            total=alerts.total,
        )
