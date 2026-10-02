"""Audit logging service.

Records sensitive actions with actor/action/resource/timestamp. Never stores
raw document contents or credentials in metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.claim import AuditLog

logger = logging.getLogger("koverly.audit")

_SENSITIVE_KEYS = {"password", "token", "secret", "content", "extracted_text"}


def _sanitize(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        k: ("<redacted>" if k.lower() in _SENSITIVE_KEYS else v)
        for k, v in metadata.items()
    }


async def record(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    actor_user_id: str | None = None,
    family_id: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        family_id=family_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=_sanitize(metadata),
    )
    db.add(entry)
    await db.flush()
    logger.info(
        "audit",
        extra={
            "extra_fields": {
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "actor_user_id": actor_user_id,
                "family_id": family_id,
            }
        },
    )
    return entry
