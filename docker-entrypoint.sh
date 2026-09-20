#!/bin/sh
# docker-entrypoint.sh — RegIntel AI backend startup script
#
# Runs database migrations before starting the application server.
# Exits non-zero immediately if any step fails.

set -e

echo "[entrypoint] Starting RegIntel AI backend..."

# ── SQLite mode: no database server, no migrations ──────────────────────────
# When DATABASE_URL points at SQLite (zero-database deploys), there is
# nothing to wait for and Alembic must NOT run (migrations are
# PostgreSQL-only DDL). The app creates all tables itself at startup.
if [ "${DATABASE_URL:-}" != "${DATABASE_URL##sqlite*}" ]; then
    echo "[entrypoint] SQLite mode detected ($DATABASE_URL) — skipping database wait and migrations."
    echo "[entrypoint] Starting uvicorn..."
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${PORT:-8000}" \
        --workers "${WORKERS:-2}" \
        --log-level "${LOG_LEVEL:-info}"
fi

# ── Fail fast when no database is configured at all ─────────────────────────
# Without this, a missing DATABASE_URL burns 30s printing a misleading
# "Database not ready" loop (the classic Render Docker-deploy failure).
if [ -z "${DATABASE_URL_SYNC:-}" ] && [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] ERROR: neither DATABASE_URL_SYNC nor DATABASE_URL is set."
    echo "[entrypoint] Fix: attach a Postgres instance to this service and set"
    echo "[entrypoint] DATABASE_URL to its connection string (internal URL if"
    echo "[entrypoint] the database is on the same platform)."
    echo "[entrypoint] Easiest path: deploy via the render.yaml Blueprint in"
    echo "[entrypoint] the repo root, which provisions Postgres and wires the"
    echo "[entrypoint] URL automatically (no Docker entrypoint involved)."
    exit 1
fi

# ── Wait for the database to be reachable ────────────────────────────────────
# Retry up to 30 seconds so Docker Compose's "depends_on: db" healthcheck
# condition has time to succeed even on slower machines.
DB_RETRIES=30
DB_WAIT=1

echo "[entrypoint] Waiting for database..."
until python -c "
import os
url = os.environ.get('DATABASE_URL_SYNC') or os.environ['DATABASE_URL']
# Normalise managed-provider schemes (postgres://, postgresql://) to the
# sync psycopg2 driver URL, mirroring app/core/config.py.
for prefix in ('postgres://', 'postgresql://'):
    if url.startswith(prefix):
        url = 'postgresql+psycopg2://' + url[len(prefix):]
        break
import sqlalchemy
sqlalchemy.create_engine(url).connect().close()
" > /dev/null 2>&1; do
    DB_RETRIES=$((DB_RETRIES - 1))
    if [ $DB_RETRIES -le 0 ]; then
        echo "[entrypoint] ERROR: Could not reach the database after retrying. Exiting."
        exit 1
    fi
    echo "[entrypoint] Database not ready — retrying in ${DB_WAIT}s ($DB_RETRIES retries left)..."
    sleep $DB_WAIT
done

echo "[entrypoint] Database reachable."

# ── Run Alembic migrations ───────────────────────────────────────────────────
echo "[entrypoint] Running database migrations..."
alembic upgrade head
echo "[entrypoint] Migrations complete."

# ── Start the application server ─────────────────────────────────────────────
echo "[entrypoint] Starting uvicorn..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-2}" \
    --log-level "${LOG_LEVEL:-info}"
