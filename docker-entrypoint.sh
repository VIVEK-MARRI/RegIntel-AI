#!/bin/sh
# docker-entrypoint.sh — RegIntel AI backend startup script
#
# Runs database migrations before starting the application server.
# Exits non-zero immediately if any step fails.

set -e

echo "[entrypoint] Starting RegIntel AI backend..."

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
