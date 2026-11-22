#!/usr/bin/env bash
# PayInsight AI - one-time setup (macOS / Linux / Git Bash). Run from the repository root.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
cd backend
[ -d .venv ] || python -m venv .venv
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r requirements.txt
"$PY" scripts/seed.py
cd ../frontend && npm install --no-fund --no-audit
echo "Setup complete. Start with: scripts/start.sh"
