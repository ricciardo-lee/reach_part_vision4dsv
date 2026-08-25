#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/common.sh"
activate_python
load_env
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
