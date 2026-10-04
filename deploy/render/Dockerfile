# Koverly combined production image (Render / single-container hosts).
#
# Stage 1 builds the React SPA; stage 2 runs FastAPI + nginx in one container.
# nginx serves the SPA and proxies /api to the API on the same origin, so
# relative document signed URLs resolve correctly. Frontend is built with an
# empty VITE_API_BASE_URL on purpose (same-origin).
#
# Build context is the repository root.

# ---------- Stage 1: build the frontend ----------
FROM node:24-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# nginx + gettext-base (envsubst) + curl (healthcheck).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        gettext-base \
        curl \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Backend runtime dependencies.
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

# Backend application code.
COPY backend/app ./app

# Frontend build output + nginx config template + entrypoint.
COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY deploy/render/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY deploy/render/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as non-root: nginx's master process keeps the privileges it needs to bind
# the port and write its pid file, while the app runs under the koverly user.
RUN useradd --create-home --uid 10001 koverly \
    && mkdir -p /app/storage \
    && chown -R koverly:koverly /app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8080}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
