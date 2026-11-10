"""In-process reminder scheduler.

This is intentionally small: one asyncio task that periodically dispatches due
reminders. It is appropriate for a single-instance deployment. When running
multiple workers, disable it (``REMINDER_SCHEDULER_ENABLED=false``) and call
``POST /api/v1/system/run-reminders`` from an external cron instead, so the
same reminder is not dispatched by every worker.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import reminder_service

logger = logging.getLogger("koverly.scheduler")

_task: asyncio.Task | None = None


async def _run_forever() -> None:
    interval = max(60, settings.REMINDER_CHECK_INTERVAL_MINUTES * 60)
    while True:
        try:
            async with SessionLocal() as db:
                dispatched = await reminder_service.run_due_reminders(db)
            if dispatched:
                logger.info("reminders_dispatched", extra={
                    "extra_fields": {"count": dispatched}
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reminder_scheduler_failed")
        await asyncio.sleep(interval)


def start_scheduler() -> None:
    global _task
    if not settings.REMINDER_SCHEDULER_ENABLED or _task is not None:
        return
    _task = asyncio.create_task(_run_forever(), name="koverly-reminder-scheduler")
    logger.info(
        "reminder_scheduler_started",
        extra={
            "extra_fields": {
                "interval_minutes": settings.REMINDER_CHECK_INTERVAL_MINUTES
            }
        },
    )


async def stop_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("reminder_scheduler_stopped")
