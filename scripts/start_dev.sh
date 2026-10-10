#!/usr/bin/env bash
# Start local stack: Redis + API + Celery worker + Celery beat (+ optional H5/Web/Admin)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/common.sh"

WITH_H5=1
WITH_ADMIN=0
WITH_WEB=0
API_PORT=8000
H5_PORT=5173
ADMIN_PORT=5174
WEB_PORT=5175

usage() {
  cat <<'EOF'
Usage: ./scripts/start_dev.sh [options]

Options:
  --api-only       Only Redis + API + Celery worker/beat
  --with-admin     Also start admin frontend (5174)
  --with-web       Also start desktop web frontend (5175)
  --no-h5          Do not start H5 frontend
  -h, --help       Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-only) WITH_H5=0; WITH_ADMIN=0; WITH_WEB=0; shift ;;
    --with-admin) WITH_ADMIN=1; shift ;;
    --with-web) WITH_WEB=1; shift ;;
    --no-h5) WITH_H5=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

echo "=== Reach Part Vision local start ==="
echo "Root: $ROOT"

ensure_redis
activate_python
require_mysql_env
load_env

# Prefer Celery async in local start
export CELERY_ENABLED="${CELERY_ENABLED:-true}"
export PYTHONPATH="$BACKEND_DIR"

# API（后台模式不加 --reload，避免父进程退出后子进程被带走）
if is_port_listening "$API_PORT"; then
  echo "OK  API port $API_PORT already in use"
else
  start_bg api uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT"
fi

# Celery worker（必须成功，否则识别会 503；默认 concurrency=1 避免重复加载 DINOv2）
WORKER_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-1}"
if ! start_bg celery celery -A app.tasks.celery_app.celery_app worker -l info --concurrency="$WORKER_CONCURRENCY" \
  --without-heartbeat --without-mingle --without-gossip; then
  echo "ERROR: Celery worker failed to start. Recognition will return 503."
  exit 1
fi

# Celery beat（定时清图）
if ! start_bg beat celery -A app.tasks.celery_app.celery_app beat -l info \
  --schedule="$LOG_DIR/celerybeat-schedule"; then
  echo "WARN: Celery beat failed to start. Daily image cleanup will not run."
fi

wait_http "http://127.0.0.1:${API_PORT}/health" "API" 40 || true

# Probe readiness (redis + celery)
READY_JSON="$(curl -sf "http://127.0.0.1:${API_PORT}/ready" 2>/dev/null || true)"
if [[ -n "$READY_JSON" ]]; then
  echo "READY $READY_JSON"
  if echo "$READY_JSON" | grep -q '"celery":"down"'; then
    echo "WARN Celery worker not responding to ping yet; check $LOG_DIR/celery.log" >&2
  fi
  if echo "$READY_JSON" | grep -q '"redis":"down"'; then
    echo "WARN Redis not reachable from API" >&2
  fi
else
  echo "WARN /ready endpoint not reachable yet" >&2
fi

# H5 / Web / Admin need frontend cwd
if [[ "$WITH_H5" -eq 1 ]]; then
  if is_port_listening "$H5_PORT"; then
    echo "OK  H5 port $H5_PORT already in use"
  elif [[ -d "$ROOT/frontend-h5/node_modules" ]]; then
    start_bg h5 bash -lc "cd \"$ROOT/frontend-h5\" && npm run dev -- --host 0.0.0.0 --port $H5_PORT"
  else
    echo "WARN frontend-h5/node_modules missing, skip H5 (run: cd frontend-h5 && npm install)"
  fi
fi

if [[ "$WITH_ADMIN" -eq 1 ]]; then
  if is_port_listening "$ADMIN_PORT"; then
    echo "OK  Admin port $ADMIN_PORT already in use"
  elif [[ -d "$ROOT/frontend-admin/node_modules" ]]; then
    start_bg admin bash -lc "cd \"$ROOT/frontend-admin\" && npm run dev -- --host 0.0.0.0 --port $ADMIN_PORT"
  else
    echo "WARN frontend-admin/node_modules missing, skip Admin (run: cd frontend-admin && npm install)"
  fi
fi

if [[ "$WITH_WEB" -eq 1 ]]; then
  if is_port_listening "$WEB_PORT"; then
    echo "OK  Web port $WEB_PORT already in use"
  elif [[ -d "$ROOT/frontend-web/node_modules" ]]; then
    start_bg web bash -lc "cd \"$ROOT/frontend-web\" && npm run dev -- --host 0.0.0.0 --port $WEB_PORT"
  else
    echo "WARN frontend-web/node_modules missing, skip Web (run: cd frontend-web && npm install)"
  fi
fi

cat <<EOF

=== Services ===
API:     http://127.0.0.1:${API_PORT}/health
Ready:   http://127.0.0.1:${API_PORT}/ready
Docs:    http://127.0.0.1:${API_PORT}/docs
H5:      http://127.0.0.1:${H5_PORT}/
Web:     http://127.0.0.1:${WEB_PORT}/   (if --with-web)
Admin:   http://127.0.0.1:${ADMIN_PORT}/   (if --with-admin)
Celery:  worker + beat started (see logs)

Logs:    $LOG_DIR/
PIDs:    $PID_DIR/
Stop:    ./scripts/stop_dev.sh

EOF
