"""Koverly FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestTimer, configure_logging, log_event
from app.core.scheduler import start_scheduler, stop_scheduler
from app.db.session import db_connection_hint, engine, init_models

logger = logging.getLogger("koverly")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    try:
        await init_models()
    except Exception:
        # Hosts like Render restart the container on startup failure, and
        # the raw SQLAlchemy/asyncpg traceback buries the actual cause.
        # Surface the database target (password redacted) in one line: an
        # unresolvable host almost always means DATABASE_URL points at a
        # database that no longer exists (free-tier instances expire).
        url = engine.url.render_as_string(hide_password=True)
        logger.critical(
            "Startup failed: database unreachable. DATABASE_URL is %s.%s",
            url,
            db_connection_hint(url),
        )
        raise
    log_event(
        logger,
        "app_started",
        env=settings.ENV,
        ai_provider=settings.AI_PROVIDER,
        storage_backend=settings.STORAGE_BACKEND,
    )
    start_scheduler()
    yield
    await stop_scheduler()
    log_event(logger, "app_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Koverly API",
        description="Insurance Operating System for individuals and families.",
        version="1.0.0",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def _logging_middleware(request: Request, call_next):
        timer = RequestTimer()
        try:
            response = await call_next(request)
        except Exception:
            log_event(
                logger,
                "request_error",
                method=request.method,
                path=request.url.path,
                duration_ms=timer.elapsed_ms,
            )
            raise
        response.headers["X-Process-Time-Ms"] = str(timer.elapsed_ms)
        # Security headers.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        log_event(
            logger,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=timer.elapsed_ms,
        )
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "app": settings.APP_NAME}

    return app


app = create_app()
