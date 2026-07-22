#!/bin/bash
# ─── Entrypoint for Dulo.tv Stream API (4-core gunicorn) ─────────────────────
# Reads all config from environment variables (set in Coolify UI)

set -e

WORKERS="${WORKERS:-4}"
THREADS="${THREADS:-2}"
TIMEOUT="${TIMEOUT:-300}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo "[entrypoint] Starting gunicorn: ${WORKERS} workers × ${THREADS} threads on 0.0.0.0:${PORT}"

exec gunicorn \
  --bind 0.0.0.0:${PORT} \
  --workers ${WORKERS} \
  --threads ${THREADS} \
  --timeout ${TIMEOUT} \
  --graceful-timeout ${TIMEOUT} \
  --preload \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --access-logfile - \
  --log-level ${LOG_LEVEL} \
  api.index:app
