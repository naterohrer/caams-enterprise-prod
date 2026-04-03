#!/bin/sh
# CAAMS Enterprise container entrypoint.
# Runs Alembic migrations then starts the application server.
set -e

echo "CAAMS: running database migrations..."
alembic upgrade head

echo "CAAMS: starting application..."
exec uvicorn app.main:app \
    --host "${CAAMS_HOST:-0.0.0.0}" \
    --port "${CAAMS_PORT:-8000}" \
    --workers "${CAAMS_WORKERS:-2}"
