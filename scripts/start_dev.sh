#!/usr/bin/env bash
# Start local stack: Redis + API + Celery worker/beat + H5 + Web + Admin
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/common.sh"

WITH_FRONTENDS=1
API_PORT=8000
H5_PORT=5173
ADMIN_PORT=5174
WEB_PORT=5175

usage() {
  cat <<'EOF'
Usage: ./scripts/start_dev.sh [options]

Starts Redis, API, Celery worker/beat, H5 (5173), Web (5175), and Admin (5174).

Options:
  --api-only       Only Redis + API + Celery worker/beat
  -h, --help       Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-only) WITH_FRONTENDS=0; shift ;;
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

start_frontend() {
  local name="$1"
  local port="$2"
  local dir="$3"
  if is_port_listening "$port"; then
    echo "OK  $name port $port already in use"
  elif [[ -d "$dir/node_modules" ]]; then
    start_bg "$name" bash -lc "cd \"$dir\" && npm run dev -- --host 0.0.0.0 --port $port"
  else
    echo "WARN $dir/node_modules missing, skip $name (run: cd $dir && npm install)"
  fi
}

if [[ "$WITH_FRONTENDS" -eq 1 ]]; then
  start_frontend h5 "$H5_PORT" "$ROOT/frontend-h5"
  start_frontend web "$WEB_PORT" "$ROOT/frontend-web"
  start_frontend admin "$ADMIN_PORT" "$ROOT/frontend-admin"
fi

cat <<EOF

=== Services ===
API:     http://127.0.0.1:${API_PORT}/health
Ready:   http://127.0.0.1:${API_PORT}/ready
Docs:    http://127.0.0.1:${API_PORT}/docs
H5:      http://127.0.0.1:${H5_PORT}/
Web:     http://127.0.0.1:${WEB_PORT}/
Admin:   http://127.0.0.1:${ADMIN_PORT}/
Celery:  worker + beat started (see logs)

Logs:    $LOG_DIR/
PIDs:    $PID_DIR/
Stop:    ./scripts/stop_dev.sh

EOF
