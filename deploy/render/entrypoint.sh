#!/usr/bin/env bash
# Combined production entrypoint (Render / any single-container host).
#
# Runs the FastAPI app (internal port 8000) and nginx (public, bound to the
# platform-provided $PORT) in one container. nginx serves the built SPA and
# proxies /api to the API, so the frontend and API share one origin — required
# because document signed URLs are returned as relative paths.
set -euo pipefail

# Render (and most PaaS) inject $PORT. Default to 8080 for local use.
export PORT="${PORT:-8080}"

# Render Postgres exposes a bare postgres:// or postgresql:// URL; the app
# uses the asyncpg driver, which needs the +asyncpg scheme.
if [ -n "${DATABASE_URL:-}" ]; then
  case "$DATABASE_URL" in
    postgres://*) DATABASE_URL="postgresql+asyncpg://${DATABASE_URL#postgres://}" ;;
    postgresql://*) DATABASE_URL="postgresql+asyncpg://${DATABASE_URL#postgresql://}" ;;
  esac
  export DATABASE_URL
fi

# Render provides RENDER_EXTERNAL_URL (e.g. https://koverly.onrender.com).
# Use it as the allowed CORS origin unless CORS_ORIGINS is set explicitly.
if [ -z "${CORS_ORIGINS:-}" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  export CORS_ORIGINS="$RENDER_EXTERNAL_URL"
fi

# nginx cannot read $PORT from the environment in a static config file; render
# it from the template. Only that one placeholder is substituted so nginx's own
# $host/$remote_addr variables are left untouched.
envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Private local storage directory (a persistent disk can be mounted here).
mkdir -p "${STORAGE_LOCAL_ROOT:-/app/storage}"

# Run the API as the unprivileged user when possible; nginx's master process
# keeps the privileges it needs to bind the port and write its pid file.
APP_HOME=/home/koverly
RUN_AS=()
if command -v setpriv >/dev/null 2>&1 && id koverly >/dev/null 2>&1; then
  RUN_AS=(setpriv --reuid=koverly --regid=koverly --init-groups)
  mkdir -p "$APP_HOME" 2>/dev/null || true
  chown -R koverly:koverly "$APP_HOME" 2>/dev/null || true
fi

# HOME must point at a directory the app user can read: asyncpg probes
# ~/.postgresql for client certificates and raises a permission error when HOME
# is inherited as /root after privileges are dropped.
"${RUN_AS[@]}" env HOME="$APP_HOME" uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

nginx -g 'daemon off;' &
NGINX_PID=$!

# Exit as soon as either process dies so the platform can restart the container.
wait -n "$API_PID" "$NGINX_PID"
