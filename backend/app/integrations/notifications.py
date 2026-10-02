"""Notification abstraction.

Business logic depends only on the ``NotificationBackend`` interface. Email,
WhatsApp, and push providers can be added later without touching reminder
scheduling. The default ``noop`` backend records dispatches without sending,
so no channel is faked as working.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("koverly.notifications")


@dataclass
class NotificationMessage:
    recipient: str
    subject: str
    body: str
    channel: str = "email"


class NotificationBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    async def send(self, message: NotificationMessage) -> bool: ...


class NoopNotificationBackend(NotificationBackend):
    name = "noop"

    async def send(self, message: NotificationMessage) -> bool:
        # Intentionally does not deliver. Recorded for observability only.
        logger.info(
            "notification_skipped",
            extra={
                "extra_fields": {
                    "channel": message.channel,
                    "backend": self.name,
                }
            },
        )
        return False


class WebhookNotificationBackend(NotificationBackend):
    name = "webhook"

    def __init__(self, url: str) -> None:
        self.url = url

    async def send(self, message: NotificationMessage) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.url,
                    json={
                        "recipient": message.recipient,
                        "subject": message.subject,
                        "body": message.body,
                        "channel": message.channel,
                    },
                )
                return resp.status_code < 400
        except Exception:  # noqa: BLE001 - never crash reminder flow
            logger.exception("notification_webhook_failed")
            return False


_backend: NotificationBackend | None = None


def get_notification_backend() -> NotificationBackend:
    global _backend
    if _backend is None:
        if settings.NOTIFICATION_BACKEND == "webhook" and settings.NOTIFICATION_WEBHOOK_URL:
            _backend = WebhookNotificationBackend(settings.NOTIFICATION_WEBHOOK_URL)
        else:
            _backend = NoopNotificationBackend()
    return _backend
