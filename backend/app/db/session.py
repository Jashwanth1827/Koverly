"""Database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Query parameters that hosted-Postgres dashboards and ORM quick-start guides
# put in the URL but the asyncpg driver does not accept as connect arguments.
# The asyncpg dialect forwards *every* URL query parameter to
# ``asyncpg.connect()`` (``opts.update(url.query)``), so leaving these in place
# fails with ``TypeError: connect() got an unexpected keyword argument``.
_DROP_QUERY_PARAMS = frozenset({"sslmode", "pgbouncer", "connection_limit"})


def _url_port(parts: Any) -> int | None:
    """Return the URL port, or None when it is malformed (driver reports it)."""
    try:
        return parts.port
    except ValueError:
        return None


def build_engine_config(raw_url: str) -> tuple[str, dict[str, Any]]:
    """Normalize a hosted-Postgres URL for the asyncpg driver.

    Returns ``(url, engine_kwargs)`` ready for :func:`create_async_engine`.

    Handles the URL shapes people paste from provider dashboards (Supabase,
    Render, Neon, Railway):

    * ``postgres://`` / ``postgresql://`` are upgraded to
      ``postgresql+asyncpg://``. The Render entrypoint rewrites these too;
      doing it here keeps local runs, docker-compose and CI consistent.
    * ``sslmode`` / ``pgbouncer`` / ``connection_limit`` are removed. asyncpg
      already negotiates TLS by default (its ``prefer`` mode, so encrypted
      when the server offers it) and rejects the others as unexpected
      connect arguments.
    * Transaction-pooler endpoints (Supabase port 6543, or ``pgbouncer=true``)
      multiplex many client sessions over one backend connection, which
      breaks prepared-statement caching. For those the cache is disabled on
      both sides: SQLAlchemy's (``prepared_statement_cache_size=0``) and
      asyncpg's (``statement_cache_size=0``). Session-pooler (5432) and
      direct connections keep the cache.

    Non-Postgres URLs (SQLite in development and tests) are returned
    unchanged.
    """
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    if not url.startswith("postgresql+asyncpg://"):
        return url, {}

    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    transaction_pooler = _url_port(parts) == 6543 or any(
        key == "pgbouncer" and value.strip().lower() in {"1", "true", "yes", "on"}
        for key, value in params
    )
    remaining = [(key, value) for key, value in params if key not in _DROP_QUERY_PARAMS]

    engine_kwargs: dict[str, Any] = {}
    if transaction_pooler:
        remaining.append(("prepared_statement_cache_size", "0"))
        engine_kwargs["connect_args"] = {"statement_cache_size": 0}

    normalized = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(remaining), parts.fragment)
    )
    return normalized, engine_kwargs


_DATABASE_URL, _ENGINE_KWARGS = build_engine_config(settings.DATABASE_URL)

engine = create_async_engine(
    _DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    **_ENGINE_KWARGS,
)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enforce foreign keys on SQLite (off by default).

    Several models rely on ``ON DELETE CASCADE`` — notably deleting a family,
    which must remove its policies, members, documents, and claims. Without
    this pragma SQLite silently ignores those clauses.
    """
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Create tables for local/dev/test usage.

    Production deployments should use Alembic migrations instead; this helper
    exists so the app boots without a migration toolchain in development.
    """
    import app.models  # noqa: F401  (register all models on the metadata)
    from app.db import base

    async with engine.begin() as conn:
        await conn.run_sync(base.Base.metadata.create_all)
