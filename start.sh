#!/bin/bash
# ─── Dulo.tv Stream API v3.1 — VPS Start Script (4-Core Gunicorn) ───────────
#
# Usage:
#   bash start.sh              # foreground (gunicorn, 4 workers)
#   bash start.sh bg           # background daemon
#   bash start.sh stop         # stop background server
#   bash start.sh status       # check if running
#   bash start.sh restart      # restart background server
#
# Environment:
#   PROXY_URL   — rotating proxy URL (default: built-in)
#   PORT        — listen port (default: 8000)
#   WORKERS     — gunicorn worker processes (default: 4 → uses 4 cores)
#   THREADS     — threads per worker (default: 2)
#   FETCH_MODE  — "requests" (default) or "curl"
#   SSE_TIMEOUT — timeout for SSE fetch in seconds (default: 60)
#   LOG_LEVEL   — DEBUG / INFO / WARNING / ERROR (default: INFO)
#   TIMEOUT     — gunicorn worker timeout in seconds (default: 300)

set -e

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-4}"
THREADS="${THREADS:-2}"
TIMEOUT="${TIMEOUT:-300}"
LOGFILE="server.log"
PIDFILE="server.pid"

# Export env vars
export FETCH_MODE="${FETCH_MODE:-requests}"
export SSE_TIMEOUT="${SSE_TIMEOUT:-60}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export WORKERS="${WORKERS}"
export THREADS="${THREADS}"
export TIMEOUT="${TIMEOUT}"

# ── Install dependencies if needed ──────────────────────────────────────────
if ! python3 -c "import flask, flask_cors, requests, gunicorn" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt 2>&1 || pip install -r requirements.txt 2>&1
  echo "✓ Dependencies installed"
fi

case "${1:-run}" in
  bg)
    echo "Starting Dulo.tv Stream API on 0.0.0.0:${PORT} (${WORKERS} workers × ${THREADS} threads = ${WORKERS} cores)..."
    nohup python3 run.py > "${LOGFILE}" 2>&1 &
    echo $! > "${PIDFILE}"
    sleep 2
    if kill -0 "$(cat ${PIDFILE})" 2>/dev/null; then
      echo "✓ Server started (PID $(cat ${PIDFILE}))"
      echo "  API:     http://localhost:${PORT}/"
      echo "  Log:     ${LOGFILE}"
      echo "  Mode:    ${FETCH_MODE}"
      echo "  Workers: ${WORKERS} (using ${WORKERS} CPU cores)"
    else
      echo "✗ Server failed to start. Check ${LOGFILE}"
      rm -f "${PIDFILE}"
      exit 1
    fi
    ;;

  stop)
    if [ -f "${PIDFILE}" ]; then
      PID=$(cat "${PIDFILE}")
      if kill -0 "${PID}" 2>/dev/null; then
        kill "${PID}"
        echo "Stopped server (PID ${PID})"
      else
        echo "Server not running (stale PID file)"
      fi
      rm -f "${PIDFILE}"
    else
      echo "No PID file found. Server not running."
    fi
    ;;

  restart)
    bash start.sh stop
    sleep 1
    bash start.sh bg
    ;;

  status)
    if [ -f "${PIDFILE}" ] && kill -0 "$(cat ${PIDFILE})" 2>/dev/null; then
      echo "Server running (PID $(cat ${PIDFILE}), port ${PORT}, ${WORKERS} workers, FETCH_MODE=${FETCH_MODE})"
    else
      echo "Server not running"
      rm -f "${PIDFILE}" 2>/dev/null
    fi
    ;;

  run|*)
    echo "Starting Dulo.tv Stream API on 0.0.0.0:${PORT} (${WORKERS} workers × ${THREADS} threads = ${WORKERS} cores)..."
    exec python3 run.py
    ;;
esac
