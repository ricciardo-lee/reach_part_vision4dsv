#!/usr/bin/env bash
# Stop processes started by start_dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/common.sh"

echo "=== Stopping local services ==="
stop_bg admin || true
stop_bg h5 || true
stop_bg beat || true
stop_bg celery || true
stop_bg api || true

# Extra cleanup for reload children / leftover workers
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "celery -A app.tasks.celery_app.celery_app worker" 2>/dev/null || true
pkill -f "celery -A app.tasks.celery_app.celery_app beat" 2>/dev/null || true

echo "Done."
