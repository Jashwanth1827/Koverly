"""DATABASE_URL normalization for hosted Postgres (Supabase, Render, Neon).

The asyncpg dialect forwards every URL query parameter to ``asyncpg.connect``,
so libpq/ORM-only params must be stripped, and transaction-pooler endpoints
need the prepared-statement caches disabled. These tests pin that behaviour
without touching a real database.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import build_engine_config

_SUPABASE_SESSION = (
    "postgresql://postgres.abcd:pw@aws-0-us-west-1.pooler.supabase.com:5432/postgres"
)
_SUPABASE_TRANSACTION = (
    "postgresql://postgres.abcd:pw@aws-0-us-west-1.pooler.supabase.com:6543/postgres"
)


def test_plain_postgres_scheme_is_upgraded() -> None:
    url, kwargs = build_engine_config("postgresql://u:p@host:5432/db")
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert kwargs == {}


def test_short_postgres_scheme_is_upgraded() -> None:
    url, kwargs = build_engine_config("  postgres://u:p@host:5432/db  ")
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert kwargs == {}


def test_asyncpg_scheme_is_untouched() -> None:
    original = "postgresql+asyncpg://u:p@host:5432/db"
    assert build_engine_config(original) == (original, {})


def test_libpq_and_orm_only_params_are_removed() -> None:
    url, kwargs = build_engine_config(
        "postgresql://u:p@host:5432/db"
        "?sslmode=require&pgbouncer=false&connection_limit=1"
    )
    # sslmode/pgbouncer/connection_limit are not asyncpg.connect() arguments;
    # asyncpg negotiates TLS by default ("prefer") instead.
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert kwargs == {}


def test_supabase_session_pooler_keeps_prepared_statement_cache() -> None:
    url, kwargs = build_engine_config(_SUPABASE_SESSION)
    assert url == (
        "postgresql+asyncpg://postgres.abcd:pw"
        "@aws-0-us-west-1.pooler.supabase.com:5432/postgres"
    )
    assert kwargs == {}


def test_supabase_transaction_pooler_disables_both_caches() -> None:
    url, kwargs = build_engine_config(_SUPABASE_TRANSACTION)
    assert "prepared_statement_cache_size=0" in url
    # asyncpg's own cache must also be off: Supavisor transaction mode shares
    # one backend connection across clients.
    assert kwargs == {"connect_args": {"statement_cache_size": 0}}


def test_pgbouncer_flag_also_disables_caches() -> None:
    url, kwargs = build_engine_config("postgresql://u:p@host:5432/db?pgbouncer=true")
    assert "prepared_statement_cache_size=0" in url
    assert kwargs["connect_args"] == {"statement_cache_size": 0}


def test_percent_encoded_password_is_preserved() -> None:
    url, _ = build_engine_config("postgresql://u:p%40ss%3Aword@host:5432/db")
    assert url == "postgresql+asyncpg://u:p%40ss%3Aword@host:5432/db"


def test_sqlite_is_returned_unchanged() -> None:
    original = "sqlite+aiosqlite:///./koverly.db"
    assert build_engine_config(original) == (original, {})


def test_transaction_pooler_config_builds_an_engine() -> None:
    # Validates that the generated kwargs are real SQLAlchemy arguments; no
    # connection is attempted.
    url, kwargs = build_engine_config(_SUPABASE_TRANSACTION)
    engine = create_async_engine(url, **kwargs)
    assert engine.url.query["prepared_statement_cache_size"] == "0"
    assert engine.dialect.name == "postgresql"
