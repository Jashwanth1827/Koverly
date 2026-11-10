"""Notification abstraction.

Business logic depends only on the ``NotificationBackend`` interface. Email,
WhatsApp, and push providers can be added later without touching reminder
scheduling. The default ``noop`` backend records dispatches without sending,
so no channel is faked as working.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage

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


class SmtpNotificationBackend(NotificationBackend):
    """SMTP delivery using the standard library.

    The blocking ``smtplib`` call runs in a worker thread so the reminder loop
    and API requests are never blocked by a slow mail server.
    """

    name = "smtp"

    def __init__(self) -> None:
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.from_addr = settings.SMTP_FROM or settings.SMTP_USER
        self.use_tls = settings.SMTP_USE_TLS
        self.use_ssl = settings.SMTP_USE_SSL
        self.timeout = settings.SMTP_TIMEOUT_SECONDS

    async def send(self, message: NotificationMessage) -> bool:
        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: NotificationMessage) -> bool:
        if not self.host or not self.from_addr:
            logger.error("notification_smtp_not_configured")
            return False
        mime = MimeMessage()
        mime["From"] = self.from_addr
        mime["To"] = message.recipient
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        try:
            if self.use_ssl:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout
                )
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                if self.use_tls and not self.use_ssl:
                    client.starttls()
                if self.username:
                    client.login(self.username, self.password)
                client.send_message(mime)
            return True
        except Exception:
            logger.exception("notification_smtp_failed")
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
        except Exception:
            logger.exception("notification_webhook_failed")
            return False


_backend: NotificationBackend | None = None


def get_notification_backend() -> NotificationBackend:
    global _backend
    if _backend is None:
        backend = settings.NOTIFICATION_BACKEND.strip().lower()
        if backend == "smtp" and settings.SMTP_HOST:
            _backend = SmtpNotificationBackend()
        elif backend == "webhook" and settings.NOTIFICATION_WEBHOOK_URL:
            _backend = WebhookNotificationBackend(settings.NOTIFICATION_WEBHOOK_URL)
        else:
            if backend in {"smtp", "webhook"}:
                logger.warning("notification_backend_misconfigured", extra={
                    "extra_fields": {"backend": backend}
                })
            _backend = NoopNotificationBackend()
    return _backend
