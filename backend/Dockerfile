FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "sqlalchemy[asyncio]>=2.0.30" \
    "aiosqlite>=0.20.0" \
    "asyncpg>=0.29.0" \
    "pydantic>=2.8.0" \
    "email-validator>=2.1.0" \
    "pydantic-settings>=2.4.0" \
    "PyJWT>=2.9.0" \
    "argon2-cffi>=23.1.0" \
    "python-multipart>=0.0.9" \
    "httpx>=0.27.0" \
    "aiofiles>=24.1.0" \
    "pypdf>=4.3.0" \
    "numpy>=1.26.0" \
    "pytesseract>=0.3.10" \
    "pdf2image>=1.17.0" \
    "Pillow>=10.0.0"

COPY app ./app

# Run as a non-root user.
RUN useradd --create-home --uid 10001 koverly \
    && mkdir -p /app/storage \
    && chown -R koverly:koverly /app
USER koverly

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
