"""Notification delivery, reminder recipients, and scheduler endpoint tests."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from tests.conftest import auth_headers, create_family, create_policy, register


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, message) -> bool:
        self.sent.append((message.recipient, message.subject))
        return True


def _setup(client, email: str = "notify_user@example.com"):
    user = register(client, email, "Notify User")
    family = create_family(client, user["access_token"])
    policy = create_policy(client, user["access_token"], family["id"])
    return user, family, policy


def _create_reminder(client, token: str, family_id: str, due_in_days: int) -> dict:
    resp = client.post(
        f"/api/v1/families/{family_id}/reminders",
        json={
            "family_id": family_id,
            "title": "Premium due",
            "due_date": (date.today() + timedelta(days=due_in_days)).isoformat(),
            "offsets": [due_in_days],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_reminder_sends_to_creator_and_member_and_only_once(client, monkeypatch):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.claim import Reminder
    from app.models.enums import ReminderStatus
    from app.services import reminder_service

    user, family, _ = _setup(client)
    member = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={
            "name": "Spouse",
            "relationship": "spouse",
            "email": "spouse@example.com",
        },
        headers=auth_headers(user["access_token"]),
    )
    assert member.status_code == 201, member.text

    reminder = _create_reminder(client, user["access_token"], family["id"], 7)
    backend = RecordingBackend()
    monkeypatch.setattr(
        reminder_service, "get_notification_backend", lambda: backend
    )

    async def _run() -> tuple[int, int, str]:
        async with SessionLocal() as db:
            first = await reminder_service.run_due_reminders(db)
        async with SessionLocal() as db:
            second = await reminder_service.run_due_reminders(db)
        async with SessionLocal() as db:
            row = (
                await db.execute(select(Reminder).where(Reminder.id == reminder["id"]))
            ).scalar_one()
            return first, second, row.status

    first, second, status = asyncio.run(_run())
    assert first == 1
    assert second == 0  # no duplicate dispatch on the same day
    assert status == ReminderStatus.SENT.value
    recipients = {r for r, _ in backend.sent}
    assert recipients == {"notify_user@example.com", "spouse@example.com"}


def test_smtp_backend_builds_and_sends_message(monkeypatch):
    from app.core.config import settings
    from app.integrations import notifications
    from app.integrations.notifications import (
        NotificationMessage,
        SmtpNotificationBackend,
    )

    sent: list = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.started_tls = False
            self.logged_in = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            self.started_tls = True

        def login(self, username, password):
            self.logged_in = True

        def send_message(self, message):
            sent.append((self, message))

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", "mailer@example.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(settings, "SMTP_FROM", "no-reply@koverly.app")
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USE_SSL", False)

    backend = SmtpNotificationBackend()
    ok = asyncio.run(
        backend.send(
            NotificationMessage(
                recipient="user@example.com",
                subject="Renewal",
                body="Your policy renews soon.",
            )
        )
    )
    assert ok is True
    assert len(sent) == 1
    smtp, message = sent[0]
    assert smtp.started_tls is True
    assert smtp.logged_in is True
    assert message["To"] == "user@example.com"
    assert message["From"] == "no-reply@koverly.app"
    assert message["Subject"] == "Renewal"


def test_scheduler_endpoint_requires_token(client):
    assert client.post("/api/v1/system/run-reminders").status_code == 401
    assert (
        client.post(
            "/api/v1/system/run-reminders",
            headers={"X-Scheduler-Token": "wrong"},
        ).status_code
        == 401
    )
    ok = client.post(
        "/api/v1/system/run-reminders",
        headers={"X-Scheduler-Token": "test-scheduler-token"},
    )
    assert ok.status_code == 200, ok.text
    assert "dispatched" in ok.json()
