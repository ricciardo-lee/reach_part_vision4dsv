#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/common.sh"
activate_python
load_env
ensure_redis
exec celery -A app.tasks.celery_app.celery_app worker -l info --concurrency=2 \
  --without-heartbeat --without-mingle --without-gossip
