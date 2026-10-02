"""Reminder service — scheduling, triggering, and lifecycle.

Reminders are dispatched through the notification abstraction; no provider is
hardcoded into business logic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.integrations.notifications import NotificationMessage, get_notification_backend
from app.models.claim import Reminder
from app.models.enums import ReminderStatus, ReminderType
from app.models.user import User
from app.schemas.claim import ReminderCreate, ReminderUpdate

VALID_OFFSETS = {30, 14, 7, 1}


async def get_reminder(
    db: AsyncSession, family_id: str, reminder_id: str
) -> Reminder:
    reminder = await db.get(Reminder, reminder_id)
    if reminder is None or reminder.family_id != family_id:
        raise NotFoundError("Reminder not found.")
    return reminder


def _validate_offsets(offsets: list[int]) -> list[int]:
    cleaned = sorted({int(o) for o in offsets if int(o) > 0})
    if not cleaned:
        raise ValidationError("At least one positive reminder offset is required.")
    if any(o > 365 for o in cleaned):
        raise ValidationError("Reminder offsets cannot exceed 365 days.")
    return cleaned


async def create_reminder(
    db: AsyncSession, payload: ReminderCreate, actor: User
) -> Reminder:
    reminder = Reminder(
        family_id=payload.family_id,
        policy_id=payload.policy_id,
        claim_id=payload.claim_id,
        created_by_user_id=actor.id,
        reminder_type=payload.reminder_type.value
        if isinstance(payload.reminder_type, ReminderType)
        else payload.reminder_type,
        title=payload.title.strip(),
        due_date=payload.due_date,
        offsets=_validate_offsets(payload.offsets),
        status=ReminderStatus.SCHEDULED.value,
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def update_reminder(
    db: AsyncSession,
    family_id: str,
    reminder_id: str,
    payload: ReminderUpdate,
    actor: User,
) -> Reminder:
    reminder = await get_reminder(db, family_id, reminder_id)
    data = payload.model_dump(exclude_unset=True)
    if "offsets" in data and data["offsets"] is not None:
        data["offsets"] = _validate_offsets(data["offsets"])
    if "status" in data and data["status"] is not None and hasattr(data["status"], "value"):
        data["status"] = data["status"].value
    for field, value in data.items():
        setattr(reminder, field, value)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def delete_reminder(
    db: AsyncSession, family_id: str, reminder_id: str, actor: User
) -> None:
    reminder = await get_reminder(db, family_id, reminder_id)
    await db.delete(reminder)
    await db.commit()


async def list_reminders(
    db: AsyncSession,
    family_id: str,
    *,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Reminder], int]:
    stmt = select(Reminder).where(Reminder.family_id == family_id)
    count_stmt = select(func.count(Reminder.id)).where(
        Reminder.family_id == family_id
    )
    if status:
        stmt = stmt.where(Reminder.status == status)
        count_stmt = count_stmt.where(Reminder.status == status)
    stmt = stmt.order_by(Reminder.due_date.asc()).offset(offset).limit(limit)
    items = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return items, total


async def acknowledge(
    db: AsyncSession, family_id: str, reminder_id: str, actor: User
) -> Reminder:
    reminder = await get_reminder(db, family_id, reminder_id)
    reminder.status = ReminderStatus.ACKNOWLEDGED.value
    reminder.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def complete(
    db: AsyncSession, family_id: str, reminder_id: str, actor: User
) -> Reminder:
    reminder = await get_reminder(db, family_id, reminder_id)
    reminder.status = ReminderStatus.COMPLETED.value
    reminder.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def run_due_reminders(db: AsyncSession) -> int:
    """Mark reminders triggered/sent when within their offset window.

    Intended to be invoked by a scheduler. Returns the number dispatched.
    """
    today = date.today()
    backend = get_notification_backend()
    rows = await db.execute(
        select(Reminder).where(
            Reminder.status.in_(
                [ReminderStatus.SCHEDULED.value, ReminderStatus.TRIGGERED.value]
            ),
            Reminder.due_date >= today,
            Reminder.due_date <= today + timedelta(days=30),
        )
    )
    dispatched = 0
    for reminder in rows.scalars().all():
        days_until = (reminder.due_date - today).days
        if days_until not in (reminder.offsets or []):
            continue
        sent = await backend.send(
            NotificationMessage(
                recipient=reminder.family_id,
                subject=reminder.title,
                body=f"Reminder: {reminder.title} due {reminder.due_date.isoformat()} "
                f"({days_until} day(s)).",
            )
        )
        reminder.last_triggered_at = datetime.now(timezone.utc)
        reminder.status = (
            ReminderStatus.SENT.value if sent else ReminderStatus.TRIGGERED.value
        )
        dispatched += 1
    await db.commit()
    return dispatched
