#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"

echo "Starting V4.5 Desktop API on http://127.0.0.1:8765"
cd V4.5_Desktop/backend
uvicorn app:app --host 127.0.0.1 --port 8765 --reload
