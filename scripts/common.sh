#!/usr/bin/env bash
# Shared helpers for local dev scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
LOG_DIR="$BACKEND_DIR/logs"
PID_DIR="$ROOT/.dev-pids"
ENV_FILE="$BACKEND_DIR/.env"

mkdir -p "$LOG_DIR" "$PID_DIR"

activate_python() {
  if [[ -f "$BACKEND_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$BACKEND_DIR/.venv/bin/activate"
  elif [[ -f /tmp/rpv-venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source /tmp/rpv-venv/bin/activate
  else
    echo "ERROR: Python venv not found. Run: cd backend && python3 -m venv .venv && pip install -r requirements.txt"
    exit 1
  fi
  export PYTHONPATH="$BACKEND_DIR"
  cd "$BACKEND_DIR"
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "WARN $ENV_FILE not found; copy from backend/.env.example"
    return 0
  fi
  set -a
  # shellcheck disable=SC1090
  if ! source "$ENV_FILE"; then
    echo "ERROR: failed to load $ENV_FILE"
    echo "       Quote values that contain spaces or special characters, e.g.:"
    echo '       APP_NAME="Reach Part Vision"'
    set +a
    exit 1
  fi
  set +a
}

require_mysql_env() {
  load_env
  if [[ -z "${MYSQL_HOST:-}" ]]; then
    echo "ERROR: MYSQL_HOST is missing in $ENV_FILE"
    echo "       Copy backend/.env.example to backend/.env and set MYSQL_* variables."
    exit 1
  fi
  if [[ "${MYSQL_HOST}" == "127.0.0.1" && "${MYSQL_USER:-root}" == "root" && -z "${MYSQL_PASSWORD:-}" ]]; then
    echo "WARN MYSQL looks like unset defaults (127.0.0.1/root/no password)."
    echo "     Check $ENV_FILE if you expect a remote database."
  fi
  echo "OK  MySQL target: ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT:-3306}/${MYSQL_DATABASE:-reach_part_vision4dsv}"
}

is_port_listening() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

wait_http() {
  local url="$1"
  local name="$2"
  local retries="${3:-30}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "OK  $name is ready: $url"
      return 0
    fi
    sleep 1
  done
  echo "WARN $name not ready yet: $url"
  return 1
}

ensure_redis() {
  load_env
  local host="127.0.0.1"
  local port="6379"
  if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli -h "$host" -p "$port" ping 2>/dev/null | grep -q PONG; then
      echo "OK  Redis already running at ${host}:${port}"
      return 0
    fi
  fi

  echo "Redis not reachable at ${host}:${port}, trying to start..."
  if command -v brew >/dev/null 2>&1 && brew list redis >/dev/null 2>&1; then
    brew services start redis >/dev/null 2>&1 || true
    sleep 1
  elif command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes --port "$port" >/dev/null 2>&1 || true
    sleep 1
  fi

  if command -v redis-cli >/dev/null 2>&1 && redis-cli -h "$host" -p "$port" ping 2>/dev/null | grep -q PONG; then
    echo "OK  Redis started at ${host}:${port}"
    return 0
  fi

  echo "ERROR: Local Redis is required for Celery. Install/start Redis first:"
  echo "  brew install redis && brew services start redis"
  exit 1
}

nohup_cmd() {
  # Detach from controlling terminal so Cursor/shell exit won't kill services.
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null
  else
    nohup "$@" </dev/null
  fi
}

start_bg() {
  local name="$1"
  shift
  local pid_file="$PID_DIR/${name}.pid"
  local log_file="$LOG_DIR/${name}.log"

  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "OK  $name already running (pid=$old_pid)"
      return 0
    fi
    echo "CLEAN stale $name pid file (pid=${old_pid:-unknown})"
    rm -f "$pid_file"
  fi

  case "$name" in
    celery) pkill -f "celery -A app.tasks.celery_app.celery_app worker" 2>/dev/null || true ;;
    beat) pkill -f "celery -A app.tasks.celery_app.celery_app beat" 2>/dev/null || true ;;
    api) pkill -f "uvicorn app.main:app" 2>/dev/null || true ;;
  esac
  sleep 0.5

  nohup_cmd "$@" >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" >"$pid_file"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "ERROR $name exited immediately. See log: $log_file"
    tail -n 40 "$log_file" || true
    rm -f "$pid_file"
    return 1
  fi
  echo "START $name (pid=$pid) log=$log_file"
}

stop_bg() {
  local name="$1"
  local pid_file="$PID_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "SKIP $name (no pid file)"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    # Kill process group children for uvicorn --reload / celery
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    pkill -P "$pid" 2>/dev/null || true
    echo "STOP $name (pid=$pid)"
  else
    echo "SKIP $name (pid=$pid not running)"
  fi
  rm -f "$pid_file"
}
