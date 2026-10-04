"""Structured error handling.

Every API error is returned in a consistent envelope::

    {"error": {"code": "...", "message": "...", "details": {...}}}

Internal details (stack traces, DB errors) are logged server-side and never
returned to clients.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("koverly.errors")

# Starlette renamed this constant; support both without eagerly touching the
# deprecated attribute (which would emit a warning on every import).
HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None)
if HTTP_422 is None:  # pragma: no cover - older Starlette only
    HTTP_422 = status.HTTP_422_UNPROCESSABLE_ENTITY


class AppError(Exception):
    """Base class for expected, client-safe application errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or "Request could not be processed."
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationError(AppError):
    status_code = HTTP_422
    code = "VALIDATION_ERROR"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


def _envelope(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def _label(field: str) -> str:
    label = field.replace("_", " ").strip()
    return (label[:1].upper() + label[1:]) if label else "Value"


def _friendly_validation_message(errors: list[dict[str, Any]]) -> str:
    """Turn pydantic validation errors into a message naming the bad field.

    A bare "Invalid request." gives the user nothing to act on. This surfaces
    the offending field and the reason without leaking internal details.
    """
    parts: list[str] = []
    for err in errors:
        loc = [str(p) for p in err.get("loc", []) if str(p) not in {"body", "query", "path"}]
        label = _label(loc[-1]) if loc else "Request"
        typ = str(err.get("type", ""))
        ctx = err.get("ctx") or {}
        if typ == "missing":
            parts.append(f"{label} is required.")
        elif typ == "string_too_long":
            limit = ctx.get("max_length")
            parts.append(
                f"{label} must be at most {limit} characters."
                if limit is not None
                else f"{label} is too long."
            )
        elif typ == "string_too_short":
            limit = ctx.get("min_length")
            parts.append(
                f"{label} must be at least {limit} characters."
                if limit is not None
                else f"{label} is too short."
            )
        elif typ.startswith("date") or typ.startswith("datetime"):
            parts.append(f"{label} must be a valid date.")
        elif typ == "enum":
            parts.append(f"{label} is not a valid option.")
        elif typ in {"email", "value_error.email"} or (
            typ == "value_error" and "email" in label.lower()
        ):
            parts.append(f"{label} must be a valid email address.")
        elif typ == "value_error":
            # Surface the validator's own message (strip pydantic's prefix).
            msg = str(err.get("msg", "")).replace("Value error, ", "").strip()
            parts.append(msg or f"{label} is invalid.")
        elif typ in {"int_parsing", "int_type", "decimal_parsing", "float_parsing"}:
            parts.append(f"{label} must be a number.")
        elif typ in {"greater_than_equal", "less_than_equal"}:
            parts.append(f"{label} is out of the allowed range.")
        else:
            parts.append(f"{label} is invalid.")
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return " ".join(unique) or "Invalid request."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Sanitize pydantic errors (drop non-serializable context values).
        details = []
        for err in exc.errors():
            details.append(
                {
                    "loc": [str(p) for p in err.get("loc", [])],
                    "msg": err.get("msg", ""),
                    "type": err.get("type", ""),
                }
            )
        return JSONResponse(
            status_code=HTTP_422,
            content=_envelope(
                "VALIDATION_ERROR",
                _friendly_validation_message(details),
                {"fields": details},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "INTERNAL_ERROR", "Something went wrong. Please try again."
            ),
        )
