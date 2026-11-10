"""Reminder service — scheduling, triggering, and lifecycle.

Reminders are dispatched through the notification abstraction; no provider is
hardcoded into business logic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.integrations.notifications import NotificationMessage, get_notification_backend
from app.models.claim import Reminder
from app.models.enums import ReminderStatus, ReminderType
from app.models.family import FamilyMember
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
    reminder.acknowledged_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def complete(
    db: AsyncSession, family_id: str, reminder_id: str, actor: User
) -> Reminder:
    reminder = await get_reminder(db, family_id, reminder_id)
    reminder.status = ReminderStatus.COMPLETED.value
    reminder.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def _reminder_recipients(db: AsyncSession, reminder: Reminder) -> list[str]:
    """Resolve real email addresses for a reminder.

    The member who created the reminder is always included, followed by any
    family members with an email on file. Falls back to the family id so the
    noop backend still records a dispatch target when no address exists.
    """
    emails: list[str] = []

    creator = await db.get(User, reminder.created_by_user_id)
    if creator and creator.email:
        emails.append(creator.email)

    rows = await db.execute(
        select(FamilyMember.email).where(
            FamilyMember.family_id == reminder.family_id,
            FamilyMember.email.is_not(None),
        )
    )
    for (email,) in rows.all():
        if email:
            emails.append(email)

    deduped: list[str] = []
    seen: set[str] = set()
    for email in emails:
        normalized = email.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(email.strip())
    return deduped or [reminder.family_id]


async def run_due_reminders(db: AsyncSession) -> int:
    """Send reminders whose due date falls in one of their offset windows.

    Intended to be invoked by the in-process scheduler or an external cron
    job. Returns the number of reminders dispatched. Each reminder fires at
    most once per day.
    """
    today = date.today()
    backend = get_notification_backend()
    max_offset = 365
    rows = await db.execute(
        select(Reminder).where(
            Reminder.status.in_(
                [ReminderStatus.SCHEDULED.value, ReminderStatus.TRIGGERED.value]
            ),
            Reminder.due_date >= today,
            Reminder.due_date <= today + timedelta(days=max_offset),
        )
    )
    dispatched = 0
    for reminder in rows.scalars().all():
        days_until = (reminder.due_date - today).days
        if days_until not in (reminder.offsets or []):
            continue
        # Do not send the same reminder again on the same day, even if the
        # scheduler runs more frequently than daily.
        last = reminder.last_triggered_at
        if last is not None:
            last_date = last.date() if last.tzinfo is None else last.astimezone(
                UTC
            ).date()
            if last_date == today:
                continue

        recipients = await _reminder_recipients(db, reminder)
        body = (
            f"Reminder: {reminder.title} due {reminder.due_date.isoformat()} "
            f"({days_until} day(s))."
        )
        results = [
            await backend.send(
                NotificationMessage(
                    recipient=recipient,
                    subject=reminder.title,
                    body=body,
                )
            )
            for recipient in recipients
        ]
        delivered = bool(results) and all(results)
        reminder.last_triggered_at = datetime.now(UTC)
        reminder.status = (
            ReminderStatus.SENT.value if delivered else ReminderStatus.TRIGGERED.value
        )
        dispatched += 1
    await db.commit()
    return dispatched
