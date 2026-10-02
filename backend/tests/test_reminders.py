"""Reminder scheduling/lifecycle and calendar tests."""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import auth_headers, create_family, create_policy, register


def _setup(client):
    user = register(client, "rem_user@example.com", "Rem User")
    family = create_family(client, user["access_token"])
    policy = create_policy(client, user["access_token"], family["id"])
    return user, family, policy


def test_create_reminder_with_offsets(client):
    user, family, policy = _setup(client)
    due = (date.today() + timedelta(days=45)).isoformat()
    resp = client.post(
        f"/api/v1/families/{family['id']}/reminders",
        json={
            "family_id": family["id"],
            "policy_id": policy["id"],
            "reminder_type": "renewal",
            "title": "Health policy renewal",
            "due_date": due,
            "offsets": [30, 14, 7, 1],
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["offsets"] == [1, 7, 14, 30]  # normalized/sorted
    assert body["status"] == "scheduled"


def test_reminder_offsets_validated(client):
    user, family, policy = _setup(client)
    resp = client.post(
        f"/api/v1/families/{family['id']}/reminders",
        json={
            "family_id": family["id"],
            "title": "Bad",
            "due_date": date.today().isoformat(),
            "offsets": [0, -5],
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_reminder_lifecycle(client):
    user, family, policy = _setup(client)
    due = (date.today() + timedelta(days=10)).isoformat()
    reminder = client.post(
        f"/api/v1/families/{family['id']}/reminders",
        json={
            "family_id": family["id"],
            "title": "Premium due",
            "due_date": due,
            "offsets": [7, 1],
        },
        headers=auth_headers(user["access_token"]),
    ).json()

    ack = client.post(
        f"/api/v1/families/{family['id']}/reminders/{reminder['id']}/acknowledge",
        headers=auth_headers(user["access_token"]),
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    done = client.post(
        f"/api/v1/families/{family['id']}/reminders/{reminder['id']}/complete",
        headers=auth_headers(user["access_token"]),
    )
    assert done.status_code == 200
    assert done.json()["status"] == "completed"


def test_calendar_aggregates_events(client):
    user, family, policy = _setup(client)
    soon = (date.today() + timedelta(days=20)).isoformat()
    # Policy with renewal date.
    client.patch(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        json={"renewal_date": soon, "expiry_date": soon},
        headers=auth_headers(user["access_token"]),
    )
    client.post(
        f"/api/v1/families/{family['id']}/reminders",
        json={
            "family_id": family["id"],
            "title": "Premium",
            "due_date": soon,
            "offsets": [7],
        },
        headers=auth_headers(user["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/calendar",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    kinds = {e["kind"] for e in resp.json()}
    assert "renewal" in kinds
    assert "policy" in kinds


def test_reminder_calculation_offsets_due(client):
    """A reminder whose due date is within its offset window is triggered."""
    import asyncio

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.claim import Reminder
    from app.models.enums import ReminderStatus
    from app.services import reminder_service

    user, family, policy = _setup(client)
    due = (date.today() + timedelta(days=7)).isoformat()
    reminder = client.post(
        f"/api/v1/families/{family['id']}/reminders",
        json={
            "family_id": family["id"],
            "title": "Trigger me",
            "due_date": due,
            "offsets": [7],
        },
        headers=auth_headers(user["access_token"]),
    ).json()

    async def _run():
        async with SessionLocal() as db:
            count = await reminder_service.run_due_reminders(db)
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(Reminder).where(Reminder.id == reminder["id"])
                )
            ).scalar_one()
            return count, row.status

    count, status = asyncio.run(_run())
    assert count >= 1
    # Noop backend does not deliver, so status is "triggered" (not "sent").
    assert status == ReminderStatus.TRIGGERED.value
