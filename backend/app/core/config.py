"""Application configuration.

All secrets and environment-specific values are read from environment
variables (see ``.env.example``). Nothing sensitive is hardcoded here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Core -------------------------------------------------------------
    APP_NAME: str = "Koverly"
    ENV: str = "development"  # development | test | production
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Security ---------------------------------------------------------
    # MUST be provided in production. A random ephemeral value is generated
    # for local development so the app never runs with a hardcoded secret.
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    ALGORITHM: str = "HS256"

    # --- Auth security ----------------------------------------------------
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_ROTATE: bool = True
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 1
    # Account lockout: lock after N failed logins for M minutes.
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    # Track failed logins per IP as well.
    LOGIN_MAX_ATTEMPTS_IP: int = 20
    # Set AUTH_COOKIE_SECURE=true behind HTTPS.
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"  # strict | lax | none
    AUTH_COOKIE_DOMAIN: str = ""

    # --- Database ---------------------------------------------------------
    # SQLite+aiosqlite by default for zero-dependency local runs.
    # Production should set e.g. postgresql+asyncpg://user:pass@host/db
    DATABASE_URL: str = "sqlite+aiosqlite:///./koverly.db"

    # --- Storage ----------------------------------------------------------
    STORAGE_BACKEND: str = "local"  # local | s3
    STORAGE_LOCAL_ROOT: str = "./storage"
    STORAGE_S3_BUCKET: str = ""
    STORAGE_S3_REGION: str = ""
    SIGNED_URL_TTL_SECONDS: int = 300

    # --- Uploads ----------------------------------------------------------
    # The user never selects a type; every reasonable document format is
    # accepted and the real type is detected from the file's content.
    MAX_UPLOAD_BYTES: int = 15 * 1024 * 1024  # 15 MB
    ALLOWED_UPLOAD_TYPES: str = (
        "application/pdf,"
        "image/jpeg,image/png,image/webp,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/msword,"
        "application/rtf,text/rtf,text/csv,text/markdown,text/plain"
    )

    # --- OCR --------------------------------------------------------------
    # Self-hosted Tesseract. When enabled, pages/images without a text layer
    # are rendered and OCR'd so scanned policy copies can be read. If the
    # engine or its system dependencies are missing, OCR degrades gracefully:
    # the document fails with an explicit reason instead of inventing text.
    OCR_ENABLED: bool = True
    OCR_LANGUAGES: str = "eng"
    OCR_DPI: int = 200
    OCR_MAX_PAGES: int = 10
    OCR_PAGE_TIMEOUT_SECONDS: int = 60
    # A PDF page with fewer than this many characters is treated as scanned
    # (cover pages, signatures and image-only schedules).
    OCR_MIN_TEXT_CHARS: int = 80
    # Absolute path to the tesseract binary; empty means "find on PATH".
    TESSERACT_CMD: str = ""

    # --- AI ---------------------------------------------------------------
    # Provider abstraction: "null" (deterministic local, no external calls),
    # "openai", "anthropic". "null" keeps the product fully functional
    # offline and never fabricates data.
    AI_PROVIDER: str = "null"
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""
    AI_MODEL: str = ""
    AI_EMBEDDING_MODEL: str = ""
    AI_TIMEOUT_SECONDS: int = 60

    # --- Notifications ----------------------------------------------------
    NOTIFICATION_BACKEND: str = "noop"  # noop | smtp | webhook
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # Sender address. Falls back to SMTP_USER when empty.
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 15
    NOTIFICATION_WEBHOOK_URL: str = ""

    # --- Reminder scheduler ------------------------------------------------
    # In-process scheduler for single-instance deployments. For multiple
    # workers, disable this and call POST /api/v1/system/run-reminders from an
    # external cron using SCHEDULER_TOKEN.
    REMINDER_SCHEDULER_ENABLED: bool = True
    REMINDER_CHECK_INTERVAL_MINUTES: int = 15
    SCHEDULER_TOKEN: str = ""

    # --- CORS -------------------------------------------------------------
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Rate limiting ----------------------------------------------------
    RATE_LIMIT_PER_MINUTE: int = 120

    @property
    def allowed_upload_types(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_UPLOAD_TYPES.split(",") if t.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.SECRET_KEY:
        if settings.is_production:
            raise RuntimeError(
                "SECRET_KEY must be set in production. Refusing to start with "
                "an insecure default."
            )
        # Ephemeral dev secret — regenerated per process, never persisted.
        import secrets

        settings.SECRET_KEY = secrets.token_urlsafe(48)
    return settings


settings = get_settings()
