"""Shared fixtures. Tests run against an isolated temporary data directory.

Each progressive iteration test records (scenario, input, expected, actual) via the
``record`` fixture; at session end the results (with real pass/fail and timings from
pytest) are written to docs/generated/progressive_results.json and rendered into
docs/BENCHMARK_REPORT.md between the PROGRESSIVE markers.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="payinsight_test_")
os.environ["PAYINSIGHT_DATA_DIR"] = _TMP
os.environ["PAYINSIGHT_LOG_LEVEL"] = "WARNING"
# Tests log in many times from one "IP"; the limiter itself is unit-tested in test_auth.py.
os.environ["PAYINSIGHT_AUTH_RATE_LIMIT_PER_MINUTE"] = "10000"
# Lower hashing cost keeps the suite fast; production default (600k) is asserted in test_auth.py.
os.environ["PAYINSIGHT_PASSWORD_HASH_ITERATIONS"] = "20000"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = "PayInsight@2026"
PROJECT = Path(__file__).resolve().parents[2]
_RECORDS: dict[str, dict] = {}
_OUTCOMES: dict[str, dict] = {}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _token(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _token(client, "admin@payinsight.demo")


@pytest.fixture(scope="session")
def analyst(client):
    return _token(client, "analyst@payinsight.demo")


@pytest.fixture(scope="session")
def viewer(client):
    return _token(client, "viewer@payinsight.demo")


@pytest.fixture
def scenario(client, admin):
    def activate(sid: str):
        r = client.post("/api/scenarios/activate", json={"scenario_id": sid}, headers=admin)
        assert r.status_code == 200, r.text
        return r.json()
    yield activate
    client.post("/api/scenarios/activate", json={"scenario_id": "A"}, headers=admin)


@pytest.fixture
def db_conn():
    """Independent read-only connection to the *active* payments DB (for cross-checks)."""
    from app.database.manager import get_db

    conns = []

    def open_():
        c = sqlite3.connect(f"file:{get_db().path.as_posix()}?mode=ro", uri=True)
        conns.append(c)
        return c
    yield open_
    for c in conns:
        c.close()


@pytest.fixture
def record(request):
    def _record(iteration: int, scenario: str, input: str, expected: str, actual: str):
        _RECORDS[request.node.nodeid] = {"iteration": iteration, "scenario": scenario, "input": input,
                                         "expected": expected, "actual": actual}
    return _record


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _OUTCOMES[report.nodeid] = {
            "outcome": report.outcome,
            "duration_s": round(report.duration, 3),
            "failure": (str(report.longrepr).splitlines()[-1][:300] if report.failed and report.longrepr else ""),
        }


def pytest_sessionfinish(session, exitstatus):
    rows = []
    for nodeid, rec in _RECORDS.items():
        out = _OUTCOMES.get(nodeid, {"outcome": "unknown", "duration_s": None, "failure": ""})
        rows.append({**rec, **out, "test": nodeid})
    if not rows:
        return
    rows.sort(key=lambda r: (r["iteration"], r["test"]))
    gen = PROJECT / "docs" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (gen / "progressive_results.json").write_text(json.dumps({"run_at": stamp, "results": rows}, indent=2), encoding="utf-8")

    def esc(s):
        return str(s).replace("|", "\\|").replace("\n", " ")
    lines = [f"_Generated automatically by `pytest` on {stamp} — {sum(r['outcome'] == 'passed' for r in rows)}/{len(rows)} iteration checks passed._", "",
             "| # | Scenario | Input | Expected | Actual (recorded during the run) | Result | Time (s) | Failure cause |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['iteration']} | {esc(r['scenario'])} | {esc(r['input'])} | {esc(r['expected'])} | {esc(r['actual'])} | "
                     f"{'PASS' if r['outcome'] == 'passed' else r['outcome'].upper()} | {r['duration_s']} | {esc(r['failure']) or '—'} |")
    report = PROJECT / "docs" / "BENCHMARK_REPORT.md"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        block = "<!-- PROGRESSIVE:START -->\n" + "\n".join(lines) + "\n<!-- PROGRESSIVE:END -->"
        text = re.sub(r"<!-- PROGRESSIVE:START -->.*?<!-- PROGRESSIVE:END -->", lambda _: block, text, flags=re.S)
        report.write_text(text, encoding="utf-8")
