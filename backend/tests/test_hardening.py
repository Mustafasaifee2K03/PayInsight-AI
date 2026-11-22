"""Regression tests for the 10-iteration hardening pass (docs/HARDENING_REPORT.md).

Each test is named ``test_hNN_*`` after the iteration that found the flaw; each one failed (or the
probe demonstrating the flaw failed) before the corresponding fix and passes after it.
"""
from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import get_settings

CSRF = {"X-Requested-With": "PayInsight"}


def _signup(client, email, password="Correct-Horse#91", name="Hardening Test"):
    r = client.post("/api/auth/signup", json={"email": email, "full_name": name, "password": password})
    assert r.status_code == 201, r.text
    return r


# ============================================================ iteration 1: SQL sandbox resource abuse
@pytest.mark.parametrize("sql,code", [
    ("SELECT " + "(" * 3000 + "1" + ")" * 3000 + " AS x FROM transactions_canonical", "SQL_REJECTED"),        # parser RecursionError -> 500
    ("SELECT length(printf('%.*c', 400000000, 'x')) FROM transactions_canonical", "SQL_REJECTED"),            # 400 MB in one call
    ("SELECT format('%5000000d', 1) FROM transactions_canonical", "SQL_REJECTED"),
    ("SELECT printf(status, 1) FROM transactions_canonical", "SQL_REJECTED"),                                # dynamic format string
    ("SELECT * FROM transactions_canonical, pragma_table_info('transactions_canonical')", "SQL_REJECTED"),   # was 500
    ("SELECT j.value FROM transactions_canonical, json_each('[1,2]') j", "SQL_REJECTED"),                   # was 500
])
def test_h01_sandbox_rejects_resource_abuse_cleanly(client, admin, sql, code):
    r = client.post("/api/sql/execute", json={"sql": sql}, headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


def test_h01_depth_guard_and_recursion_handler_each_work_alone(monkeypatch):
    """Two independent layers: the cheap depth pre-check, and the parser RecursionError handler behind it."""
    from app.services import sql_validator as v
    nested = "SELECT " + "(" * 100 + "1" + ")" * 100 + " AS x FROM transactions_canonical"
    r = v.validate_sql(nested, max_rows=10)                       # depth 100: parseable, rejected by the guard alone
    assert not r.valid and "nesting deeper" in r.reasons[0]
    monkeypatch.setattr(v, "MAX_NESTING_DEPTH", 10**9)           # guard off -> the RecursionError handler must still hold
    v._validate_cached.cache_clear()
    deep = "SELECT " + "(" * 5000 + "1" + ")" * 5000 + " AS x FROM transactions_canonical"
    r = v.validate_sql(deep, max_rows=10)
    assert not r.valid and "too deeply nested" in r.reasons[0]
    v._validate_cached.cache_clear()


def test_h01_heap_limit_contains_amplification(client, admin):
    """A 19 KB literal x 30k rows = 570 MB: not catchable syntactically, so SQLite's hard heap limit stops it."""
    sql = "SELECT length(group_concat('" + "z" * 19_000 + "')) AS n FROM transactions_canonical"
    r = client.post("/api/sql/execute", json={"sql": sql}, headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "QUERY_RESOURCE_LIMIT"
    # the process is healthy afterwards
    assert client.post("/api/sql/execute", json={"sql": "SELECT COUNT(*) AS n FROM transactions_canonical"}, headers=admin).status_code == 200


def test_h01_blob_and_long_cells_are_json_safe(client, admin):
    sql = "SELECT x'00ff' AS b, printf('%.900c', 'q') AS s FROM transactions_canonical LIMIT 1"
    r = client.post("/api/sql/execute", json={"sql": sql}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0]["b"] == "x'00ff'"


def test_h01_legitimate_printf_still_allowed(client, admin):
    r = client.post("/api/sql/execute", json={"sql": "SELECT printf('%.2f', 1.234) AS v FROM transactions_canonical LIMIT 1"}, headers=admin)
    assert r.status_code == 200 and r.json()["rows"][0]["v"] == "1.23"


# ============================================================ iteration 2: refresh-token rotation race
def test_h02_concurrent_refresh_with_one_token_has_single_winner(client):
    _signup(client, "h02.race@example.com")
    r = client.post("/api/auth/login", json={"email": "h02.race@example.com", "password": "Correct-Horse#91"})
    tok = r.cookies.get("payinsight_refresh")
    barrier, codes = threading.Barrier(8), []

    def go(_):
        barrier.wait()
        codes.append(client.post("/api/auth/refresh", headers=CSRF, cookies={"payinsight_refresh": tok}).status_code)
    for _ in range(3):  # the race was intermittent (1/8 .. 7/8 winners), so repeat
        codes.clear()
        tok = client.post("/api/auth/login", json={"email": "h02.race@example.com", "password": "Correct-Horse#91"}).cookies.get("payinsight_refresh")
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(go, range(8)))
        assert codes.count(200) == 1, codes


# ============================================================ iteration 3: reuse detection measured from rotation time
def test_h03_replay_after_api_use_is_detected_as_theft(client):
    from datetime import datetime, timedelta, timezone
    _signup(client, "h03.reuse@example.com")
    t0 = client.post("/api/auth/login", json={"email": "h03.reuse@example.com", "password": "Correct-Horse#91"}).cookies.get("payinsight_refresh")
    r = client.post("/api/auth/refresh", headers=CSRF, cookies={"payinsight_refresh": t0})
    sid, acc = r.json()["user"]["session_id"], r.json()["access_token"]
    ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with sqlite3.connect(get_settings().app_db_path) as db:  # rotation happened 10 minutes ago
        db.execute("UPDATE auth_sessions SET last_used_at = ?, rotated_at = ? WHERE session_id = ?", (ten_min_ago, ten_min_ago, sid))
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {acc}"}).status_code == 200  # bumps last_used_at
    replay = client.post("/api/auth/refresh", headers=CSRF, cookies={"payinsight_refresh": t0})
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {acc}"}).json()["error"]["code"] == "SESSION_REVOKED"


# ============================================================ iteration 4: lockout race
def test_h04_parallel_guesses_cannot_exceed_attempt_budget(client):
    _signup(client, "h04.lock@example.com")
    barrier, codes = threading.Barrier(20), []

    def go(_):
        barrier.wait()
        codes.append(client.post("/api/auth/login", json={"email": "h04.lock@example.com", "password": "wrong-Password#1"}).status_code)
    with ThreadPoolExecutor(20) as ex:
        list(ex.map(go, range(20)))
    assert codes.count(401) <= get_settings().max_failed_logins - 1, codes  # the slot-exhausting guess returns 429
    assert codes.count(429) >= 20 - get_settings().max_failed_logins
    ok = client.post("/api/auth/login", json={"email": "h04.lock@example.com", "password": "Correct-Horse#91"})
    assert ok.status_code == 429 and ok.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_h04_exhausted_slots_become_an_expiring_lock(client):
    """If an attempt dies after reserving the last slot, the account must not stay unusable forever."""
    r = _signup(client, "h04.stuck@example.com")
    uid = r.json()["user"]["user_id"]
    with sqlite3.connect(get_settings().app_db_path) as db:
        db.execute("UPDATE users SET failed_logins = ?, locked_until = NULL WHERE user_id = ?", (get_settings().max_failed_logins, uid))
    assert client.post("/api/auth/login", json={"email": "h04.stuck@example.com", "password": "Correct-Horse#91"}).status_code == 429
    with sqlite3.connect(get_settings().app_db_path) as db:
        locked_until, = db.execute("SELECT locked_until FROM users WHERE user_id = ?", (uid,)).fetchone()
    assert locked_until is not None  # a real lock with an expiry now exists


# ============================================================ iteration 5: change-password as a password oracle
def test_h05_change_password_guessing_locks_account_and_kills_sessions(client):
    r = _signup(client, "h05.cp@example.com")
    hb = {"Authorization": f"Bearer {r.json()['access_token']}"}
    codes = [client.post("/api/auth/change-password", json={"current_password": f"guess-{i}", "new_password": "Another-Pass#77"},
                         headers=hb).status_code for i in range(10)]
    assert codes[: get_settings().max_failed_logins - 1] == [401] * (get_settings().max_failed_logins - 1)
    assert codes[get_settings().max_failed_logins - 1] == 429          # budget exhausted -> locked
    assert client.get("/api/auth/me", headers=hb).json()["error"]["code"] == "SESSION_REVOKED"  # stolen token is dead
    login = client.post("/api/auth/login", json={"email": "h05.cp@example.com", "password": "Correct-Horse#91"})
    assert login.json()["error"]["code"] == "ACCOUNT_LOCKED"


# ============================================================ iteration 6: stored results re-authorised on read
def test_h06_demoted_user_cannot_reopen_restricted_history(client, admin):
    r = _signup(client, "h06.demote@example.com")
    uid, hb = r.json()["user"]["user_id"], {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.patch(f"/api/admin/users/{uid}", json={"role": "ANALYST"}, headers=admin).status_code == 200
    res = client.post("/api/analytics/analyze", json={"question": "Compare payment success rates by bank"}, headers=hb).json()
    assert res["access"]["dimensions"] == ["bank"]
    assert client.get(f"/api/analytics/result/{res['id']}", headers=hb).status_code == 200
    assert client.patch(f"/api/admin/users/{uid}", json={"role": "VIEWER"}, headers=admin).status_code == 200
    again = client.get(f"/api/analytics/result/{res['id']}", headers=hb)
    assert again.status_code == 403 and again.json()["error"]["details"]["restricted_dimensions"] == ["bank"]


def test_h06_viewer_can_reopen_permitted_results(client, viewer):
    res = client.post("/api/analytics/analyze", json={"question": "Why did payment success rate decline?"}, headers=viewer).json()
    assert res["status"] == "completed"
    assert not {"bank", "merchant"} & set(res["access"]["dimensions"])  # root-cause scan skipped restricted dimensions
    assert client.get(f"/api/analytics/result/{res['id']}", headers=viewer).status_code == 200


def test_h06_legacy_results_without_access_metadata_fail_closed(client, viewer):
    from app.core.errors import AuthorizationError
    from app.core.security import Role, User
    from app.services.analysis import authorize_stored_result
    legacy = {"status": "completed"}  # stored before access metadata existed
    with pytest.raises(AuthorizationError):
        authorize_stored_result(legacy, User(1, "v@x", "V", Role.VIEWER))
    authorize_stored_result(legacy, User(1, "a@x", "A", Role.ANALYST))


# ============================================================ iteration 7: bounded, pluggable rate limiting + proxy-aware client IP
def test_h07_limiter_memory_is_bounded():
    import time
    from app.core.ratelimit import MemoryRateLimitBackend, RateLimiter
    rl = RateLimiter(MemoryRateLimitBackend(max_keys=500, sweep_every=1000))
    for i in range(5_000):
        rl.check("login", f"10.0.{i // 256}.{i % 256}", 30, window_s=60)
    assert rl.backend.size() == 500                      # hard cap: least recently active keys evicted
    rl2 = RateLimiter(MemoryRateLimitBackend(sweep_every=1000))
    for i in range(10_000):
        rl2.check("login", f"ip{i}", 30, window_s=0.001)
    time.sleep(0.01)
    for i in range(1000):                                # triggers a sweep of expired keys
        rl2.check("login", "same", 10_000, window_s=0.001)
    assert rl2.backend.size() < 50                       # was: every IP ever seen retained forever


def test_h07_backend_is_pluggable():
    from app.core import ratelimit

    class DenyAll:
        def hit(self, key, limit, window_s): return 7.0
        def reset(self): pass
        def size(self): return 0
    ratelimit.register_backend("deny-all", DenyAll)
    rl = ratelimit.RateLimiter(ratelimit.create_backend("deny-all"))
    from app.core.errors import RateLimitError
    with pytest.raises(RateLimitError) as e:
        rl.check("login", "1.2.3.4", 5)
    assert e.value.headers["Retry-After"] == "8"
    with pytest.raises(ValueError):
        ratelimit.create_backend("nope")


@pytest.mark.parametrize("peer,xff,expected", [
    ("127.0.0.1", "203.0.113.9", "203.0.113.9"),                   # trusted dev proxy forwards the browser address
    ("127.0.0.1", "198.51.100.7, 203.0.113.9", "203.0.113.9"),     # right-most untrusted hop wins (client-supplied left part ignored)
    ("198.51.100.7", "1.2.3.4", "198.51.100.7"),                   # untrusted peer cannot spoof via the header
    ("127.0.0.1", None, "127.0.0.1"),
    ("testclient", "1.2.3.4", "testclient"),                       # non-IP peer is never trusted
    ("10.0.0.5", "203.0.113.9, 10.0.0.9", "203.0.113.9"),          # chain of trusted proxies (CIDR)
])
def test_h07_client_ip_resolution(peer, xff, expected):
    from app.api.deps import resolve_client_ip
    assert resolve_client_ip(peer, xff, "127.0.0.1,::1,10.0.0.0/8") == expected


# ============================================================ iteration 8: observability and attack surface
def test_h08_public_health_is_minimal_and_admin_status_is_protected(client, admin, analyst):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body.get("database") is None and body.get("cache") is None
    assert client.get("/api/system/status").status_code == 401
    assert client.get("/api/system/status", headers=analyst).status_code == 403
    st = client.get("/api/system/status", headers=admin).json()
    assert st["database"]["canonical_rows"] > 0 and st["rate_limiter"]["backend"] == "memory"


def test_h08_errors_carry_request_id_matching_header(client, viewer):
    r = client.post("/api/analytics/analyze", json={"question": "Compare payment success rates by bank"}, headers=viewer)
    assert r.status_code == 403
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]
    r = client.get("/api/auth/me", headers={"X-Request-ID": "gateway-abc-12345"})   # upstream id is propagated
    assert r.headers["x-request-id"] == "gateway-abc-12345" and r.json()["error"]["request_id"] == "gateway-abc-12345"
    r = client.get("/api/auth/me", headers={"X-Request-ID": "bad id\r\nx"})          # malformed ids are replaced
    assert r.headers["x-request-id"] != "bad id\r\nx"


def test_h08_force_signout_unknown_user_404_and_actor_audited(client, admin):
    assert client.post("/api/admin/users/999999/revoke-sessions", headers=admin).status_code == 404
    uid = _signup(client, "h08.force@example.com").json()["user"]["user_id"]
    assert client.post(f"/api/admin/users/{uid}/revoke-sessions", headers=admin).json()["sessions_revoked"] == 1
    ev = client.get("/api/admin/audit?event_type=SESSIONS_REVOKED", headers=admin).json()
    mine = [e for e in ev if e["user_id"] == uid]
    assert mine and mine[0]["detail"]["by"] == "admin@payinsight.demo"


# ============================================================ iteration 9: planner must not silently misread time language
def _ask(client, headers, q):
    r = client.post("/api/analytics/analyze", json={"question": q}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("q", ["What is the success rate in 1999?", "success rate same period last year",
                               "success rate year to date", "success rate since monday", "top 0 banks by success rate"])
def test_h09_unsupported_or_empty_periods_ask_for_clarification(client, analyst, q):
    """Before: these ran on the full window with the false assumption 'No period given'."""
    assert _ask(client, analyst, q)["status"] == "needs_clarification"


@pytest.mark.parametrize("q,start,end", [
    ("success rate in 2025", "2025-09-01", "2025-10-30"),
    ("success rate q3 2025", "2025-09-01", "2025-09-30"),
    ("success rate in the third quarter of 2025", "2025-09-01", "2025-09-30"),
    ("success rate q4", "2025-10-01", "2025-10-30"),
    ("success rate last 2 years", "2025-09-01", "2025-10-30"),
    ("success rate last 999999999 days", "2025-09-01", "2025-10-30"),
])
def test_h09_years_quarters_and_huge_ranges_are_parsed_and_clipped_explicitly(client, analyst, q, start, end):
    res = _ask(client, analyst, q)
    tr = res["interpretation"]["time_range"]
    assert (tr["start"], tr["end"]) == (start, end)
    assert not any(a.startswith("No period given") for a in res["interpretation"]["assumptions"])
    assert any("clipped" in a for a in res["interpretation"]["assumptions"])


def test_h09_rank_limit_and_currency_assumptions_are_explicit(client, analyst):
    res = _ask(client, analyst, "top 5000 merchants by tpv")
    assert res["plan"]["limit"] == 100 and any("Requested top 5,000" in a for a in res["interpretation"]["assumptions"])
    res = _ask(client, analyst, "What is TPV in USD?")
    assert any("INR only" in a for a in res["interpretation"]["assumptions"])


# ============================================================ iteration 10: scale (indexes, housekeeping, single-flight, fair writes)
def test_h10_hot_queries_use_indexes(client):
    from app.database.app_store import app_conn
    with app_conn() as c:
        plan = lambda q: " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + q))  # noqa: E731
        assert "idx_auth_sessions_expires" in plan("DELETE FROM auth_sessions WHERE expires_at < 'x'")
        assert "idx_audit_type" in plan("SELECT event_id FROM auth_audit_log WHERE event_type = 'LOGIN' ORDER BY event_id DESC LIMIT 100")
        assert "COVERING INDEX idx_auth_sessions_active" in plan(
            "SELECT COUNT(*) FROM auth_sessions WHERE user_id = 1 AND revoked_at IS NULL AND expires_at > 'x'")


def test_h10_housekeeping_is_throttled_and_enforces_retention(client):
    from app.database.app_store import app_conn
    from app.services import auth
    with app_conn() as c:
        c.execute("INSERT INTO auth_audit_log(occurred_at, event_type, outcome) VALUES ('2000-01-01T00:00:00+00:00', 'LOGIN', 'SUCCESS')")
        c.execute("INSERT INTO auth_sessions(session_id, user_id, refresh_token_hash, created_at, last_used_at, expires_at) "
                  "VALUES ('h10-old', 1, 'h10-hash', '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00', '2000-01-08T00:00:00+00:00')")
    with app_conn() as c:
        assert auth.housekeeping(c, auth.utcnow(), force=True) is True
        assert auth.housekeeping(c, auth.utcnow()) is False          # throttled: not on every login any more
        assert c.execute("SELECT COUNT(*) FROM auth_audit_log WHERE occurred_at < '2001'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auth_sessions WHERE session_id = 'h10-old'").fetchone()[0] == 0


def test_h10_single_flight_runs_identical_concurrent_query_once(client, monkeypatch):
    from app.services import query_executor
    from app.services.sql_compiler import CompiledQuery
    query_executor.cache.clear()
    executions = []
    real = query_executor._run_uncached
    monkeypatch.setattr(query_executor, "_run_uncached", lambda *a, **k: executions.append(1) or real(*a, **k))
    q = CompiledQuery("single-flight probe", "SELECT status, COUNT(*) AS n FROM transactions_canonical WHERE amount_minor > 17 GROUP BY status")
    barrier = threading.Barrier(12)

    def go(_):
        barrier.wait()
        return query_executor.execute(q).rows
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(go, range(12)))
    assert len(results) == 12 and all(r == results[0] for r in results)   # every caller got the same rows
    assert len(executions) < 12, executions                                 # but the database was not hit 12 times
    assert query_executor.cache.stats()["in_flight"] == 0


def test_h10_fair_write_gate_is_fifo_and_reentrant():
    import time
    from app.database.app_store import FairWriteGate
    gate, order = FairWriteGate(), []
    gate.acquire(); gate.acquire(); gate.release()                    # re-entrant
    threads = []
    for i in range(5):
        t = threading.Thread(target=lambda i=i: (gate.acquire(), order.append(i), gate.release()))
        t.start(); threads.append(t); time.sleep(0.02)                # arrive in a known order
    gate.release()
    for t in threads:
        t.join(2)
    assert order == [0, 1, 2, 3, 4]


def test_h10_gated_connection_releases_on_error_and_rollback(client):
    from app.database.app_store import app_conn, write_gate
    with pytest.raises(sqlite3.IntegrityError):
        with app_conn() as c:
            c.execute("INSERT INTO users(email, full_name, role, password_hash) VALUES ('x@y.z', 'X', 'NOT_A_ROLE', 'h')")
    with app_conn() as c:                                              # gate was released: this would deadlock otherwise
        c.execute("UPDATE settings SET value = value WHERE key = 'none'")
        c.rollback()
    assert write_gate._owner is None and not write_gate._queue


def test_h10_concurrent_mixed_load_has_no_server_errors(client, analyst):
    qs = ["What is the overall success rate?", "Compare payment success rates by bank", "Why did payment success rate decline?"]

    def work(i):
        if i % 4 == 0:
            return client.post("/api/auth/login", json={"email": "viewer@payinsight.demo", "password": "PayInsight@2026"}).status_code
        return client.post("/api/analytics/analyze", json={"question": qs[i % 3]}, headers=analyst).status_code
    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(work, range(64)))
    assert all(c == 200 for c in codes), codes
