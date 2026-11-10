"""System/ops endpoints.

These are not part of the user-facing product. They exist so an external cron
can drive scheduled work in multi-worker deployments, where an in-process
scheduler would otherwise run once per worker.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header

from app.api.deps import DbSession
from app.core.config import settings
from app.core.errors import AuthenticationError, NotFoundError
from app.services import reminder_service

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/run-reminders")
async def run_reminders(
    db: DbSession,
    x_scheduler_token: Annotated[str | None, Header(alias="X-Scheduler-Token")] = None,
) -> dict[str, int]:
    """Dispatch due reminders. Requires the configured scheduler token."""
    if not settings.SCHEDULER_TOKEN:
        raise NotFoundError("Scheduler endpoint is not enabled.")
    if not x_scheduler_token or not hmac.compare_digest(
        x_scheduler_token, settings.SCHEDULER_TOKEN
    ):
        raise AuthenticationError("Invalid scheduler token.")
    dispatched = await reminder_service.run_due_reminders(db)
    return {"dispatched": dispatched}
