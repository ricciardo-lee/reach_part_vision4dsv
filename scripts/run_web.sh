#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend-web"
npm run dev -- --host 0.0.0.0 --port 5175
