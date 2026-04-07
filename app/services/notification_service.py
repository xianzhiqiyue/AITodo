from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
import structlog
from sqlalchemy import select

from app.errors import AppError, ErrorCode
from app.models import NotificationDelivery
from app.schemas import (
    AlertItem,
    DispatchAlertsResponse,
    NotificationDeliveryResponse,
    NotificationTestResponse,
)
from app.services.task_service import TaskService

logger = structlog.get_logger()


class NotificationProvider(Protocol):
    channel: str

    async def send(self, message: str, payload: dict) -> None:
        ...


class WebhookNotificationProvider:
    channel = "webhook"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, message: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.webhook_url,
                json={"message": message, "payload": payload},
            )
            response.raise_for_status()


class DingTalkNotificationProvider:
    channel = "dingtalk"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, message: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.webhook_url,
                json={
                    "msgtype": "text",
                    "text": {"content": f"{message}\n{payload}"},
                },
            )
            response.raise_for_status()


class AlertDeliveryService:
    def __init__(
        self,
        task_service: TaskService,
        providers: dict[str, NotificationProvider],
        repeat_window_hours: int = 6,
    ):
        self.task_service = task_service
        self.session = task_service.session
        self.providers = providers
        self.repeat_window_hours = repeat_window_hours

    def _get_provider(self, channel: str | None = None) -> NotificationProvider:
        if channel:
            provider = self.providers.get(channel)
            if provider is None:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Notification channel '{channel}' is not configured.")
            return provider
        if "dingtalk" in self.providers:
            return self.providers["dingtalk"]
        if "webhook" in self.providers:
            return self.providers["webhook"]
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "No notification channel is configured.",
        )

    async def _has_recent_delivery(self, task_id, reason: str, channel: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.repeat_window_hours)
        result = await self.session.execute(
            select(NotificationDelivery.id).where(
                NotificationDelivery.task_id == task_id,
                NotificationDelivery.reason == reason,
                NotificationDelivery.channel == channel,
                NotificationDelivery.status == "sent",
                NotificationDelivery.sent_at >= cutoff,
            )
        )
        return result.scalar_one_or_none() is not None

    def _build_message(self, alert: AlertItem) -> str:
        return f"[{alert.reason}] {alert.task.title}"

    def _build_payload(self, alert: AlertItem) -> dict:
        return {
            "task": alert.task.model_dump(mode="json"),
            "reason": alert.reason,
        }

    async def dispatch_alerts(
        self,
        top_n: int = 20,
        force: bool = False,
        channel: str | None = None,
    ) -> DispatchAlertsResponse:
        provider = self._get_provider(channel)

        alerts = await self.task_service.list_alerts(top_n=top_n)
        deliveries: list[NotificationDeliveryResponse] = []
        sent_count = 0
        skipped_count = 0
        failed_count = 0

        for alert in alerts.alerts:
            if not force and await self._has_recent_delivery(alert.task.id, alert.reason, provider.channel):
                skipped_count += 1
                continue

            payload = self._build_payload(alert)
            delivery = NotificationDelivery(
                task_id=alert.task.id,
                reason=alert.reason,
                channel=provider.channel,
                status="sent",
                meta_data=payload,
                sent_at=datetime.now(timezone.utc),
            )

            try:
                await provider.send(self._build_message(alert), payload)
                sent_count += 1
            except Exception as exc:
                delivery.status = "failed"
                delivery.error_message = str(exc)
                failed_count += 1
                logger.exception(
                    "notification_delivery_failed",
                    task_id=str(alert.task.id),
                    reason=alert.reason,
                    channel=provider.channel,
                )

            self.session.add(delivery)
            await self.session.flush()
            deliveries.append(NotificationDeliveryResponse.model_validate(delivery))

        await self.session.commit()

        return DispatchAlertsResponse(
            total_candidates=alerts.total,
            sent_count=sent_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            deliveries=deliveries,
        )

    async def test_channel(self, message: str, channel: str | None = None) -> NotificationTestResponse:
        provider = self._get_provider(channel)
        payload = {"type": "notification_test", "sent_at": datetime.now(timezone.utc).isoformat()}
        await provider.send(message, payload)
        return NotificationTestResponse(
            channel=provider.channel,
            success=True,
            detail="Notification test sent successfully.",
        )
