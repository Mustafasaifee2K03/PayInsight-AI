#!/usr/bin/env bash
# PayInsight AI - run all automated checks (macOS / Linux / Git Bash). Run from the repository root:
#   scripts/run_tests.sh [--e2e] [--benchmark]
# --e2e needs the app running (scripts/start.sh), `pip install -r backend/requirements-dev.txt` and Microsoft Edge.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PY=backend/.venv/bin/python; [ -x "$PY" ] || PY=backend/.venv/Scripts/python
PY="$ROOT/$PY"
failed=0
run() { echo "== $1"; shift; "$@" || failed=$((failed + 1)); }

cd "$ROOT/backend"
run "Backend: pytest (unit + auth + hardening + progressive)" "$PY" -m pytest tests -q -p no:cacheprovider
cd "$ROOT/frontend"
run "Frontend: typecheck" npx tsc --noEmit -p .
run "Frontend: vitest" npx vitest run
run "Frontend: production build" npx vite build
cd "$ROOT/backend"
for arg in "$@"; do
  case "$arg" in
    --e2e) run "Browser journeys (Playwright + Microsoft Edge)" "$PY" tests/e2e/browser_journey.py ;;
    --benchmark) run "Performance benchmark (30k and 100k rows)" "$PY" scripts/benchmark.py ;;
  esac
done
cd "$ROOT"
if [ "$failed" -gt 0 ]; then echo; echo "$failed check group(s) FAILED"; exit 1; fi
echo; echo "All checks passed"
