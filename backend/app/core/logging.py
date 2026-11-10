"""Structured JSON logging.

Never log raw documents, passwords, or tokens. Request logging records only
method/path/status/duration and the authenticated user id (if any).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from app.core.config import settings

_REDACT_KEYS = {
    "password",
    "token",
    "access_token",
    "authorization",
    "api_key",
    "secret",
    "secret_key",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key.lower() in _REDACT_KEYS:
                    value = "<redacted>"
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(logging.INFO if not settings.DEBUG else logging.DEBUG)
    # pypdf emits per-object warnings for malformed-but-readable PDFs; keep them
    # out of production logs while still surfacing real errors.
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    """Emit a structured log record with sanitized extra fields."""
    logger.info(message, extra={"extra_fields": fields})


class RequestTimer:
    """Context helper to measure request duration in ms."""

    def __init__(self) -> None:
        self.start = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.start) * 1000, 2)
