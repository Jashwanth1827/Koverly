"""Database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enforce foreign keys on SQLite (off by default).

    Several models rely on ``ON DELETE CASCADE`` — notably deleting a family,
    which must remove its policies, members, documents, and claims. Without
    this pragma SQLite silently ignores those clauses.
    """
    if settings.DATABASE_URL.startswith("sqlite"):
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
