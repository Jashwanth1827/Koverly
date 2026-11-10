"""Readiness and liveness endpoints for load balancers/containers."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.logging import log_event
from app.db.session import engine
from app.integrations.storage import get_storage
from app.utils.ocr import is_ocr_available

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness check - process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict:
    """Readiness check - dependencies are reachable."""
    checks: dict[str, str] = {"api": "ok"}
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        # Local storage: root exists (created on init). S3: client init succeeded.
        get_storage()
        checks["storage"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["storage"] = f"error: {exc.__class__.__name__}"
    checks["ocr"] = "ok" if is_ocr_available() else "disabled"
    checks["ai_provider"] = settings.AI_PROVIDER
    status = "ok" if all(v == "ok" or v == "disabled" or v == settings.AI_PROVIDER for v in checks.values()) else "degraded"
    # Treat storage/db/api failures as not ready.
    if checks.get("database") != "ok" or checks.get("storage") != "ok":
        status = "not_ready"
    log_event(__import__("logging").getLogger("koverly.health"), "readiness_check", **checks)
    return {"status": status, "checks": checks}
