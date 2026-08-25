#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created backend/.env — please fill secrets before running services."
fi
python -m app.scripts.init_db || true
python -m app.scripts.init_minio || true
echo "Bootstrap finished."
