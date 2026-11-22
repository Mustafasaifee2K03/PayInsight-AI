#!/usr/bin/env bash
# PayInsight AI - start backend (:8000) and frontend (:5173). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=backend/.venv/bin/python; [ -x "$PY" ] || PY=backend/.venv/Scripts/python
(cd backend && "../$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
cd frontend && npm run dev
