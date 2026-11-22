"""Adversarial probe harness for docs/HARDENING_REPORT.md: each probe prints FLAW or OK with evidence.

Run from backend/:  .venv/Scripts/python scripts/hardening_probe.py [probe_name ...]
Uses an isolated temporary data directory; the demo databases are never touched.
"""
import os, sys, tempfile, time, json, sqlite3, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

os.environ["PAYINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="pi_probe_")
os.environ["PAYINSIGHT_LOG_LEVEL"] = "ERROR"
os.environ["PAYINSIGHT_PASSWORD_HASH_ITERATIONS"] = "20000"
os.environ["PAYINSIGHT_AUTH_RATE_LIMIT_PER_MINUTE"] = "100000"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings

PW = "PayInsight@2026"
H = {"X-Requested-With": "PayInsight"}
only = set(sys.argv[1:])
results = []


def report(name, flaw, evidence):
    results.append((name, flaw, evidence))
    print(f"[{'FLAW' if flaw else 'OK  '}] {name}: {evidence}", flush=True)


def login(c, email, pw=PW):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    return r


def bearer(c, email):
    return {"Authorization": "Bearer " + login(c, email).json()["access_token"]}


def probe(fn):
    if not only or fn.__name__ in only:
        try:
            fn()
        except Exception as e:  # a crash in the probe itself is also a finding
            report(fn.__name__, True, f"probe crashed: {type(e).__name__}: {e}")
    return fn


with TestClient(app, raise_server_exceptions=False) as c:
    A = bearer(c, "admin@payinsight.demo")
    AN = bearer(c, "analyst@payinsight.demo")
    V = bearer(c, "viewer@payinsight.demo")

    @probe
    def p01_planner_fuzz():
        qs = ["", " ", "?", "🙂🙂", "'; DROP TABLE users; --", "success rate last 999999999 days", "success rate last 0 days",
              "success rate between 2025-10-30 and 2025-09-01", "success rate on 2025-02-30", "success rate in 1999",
              "success rate for bank \"><script>alert(1)</script>", "x" * 500, "success rate " * 40,
              "compare success rate by bank by method by region by merchant", "top -5 banks by success rate",
              "top 100000000000000000000 merchants by tpv", "success rate from 2025-13-01 to 2025-14-01",
              "success rate last 3 quarters", "tpv in USD", "\x00\x01 success rate", "SUCCESS RATE YESTERDAY",
              "success rate on 2026-11-21", "why did tpv decline between 2025-09-01 and 2025-09-01"]
        bad = []
        for q in qs:
            r = c.post("/api/analytics/analyze", json={"question": q}, headers=AN)
            if r.status_code >= 500 or r.status_code not in (200, 403, 422):
                bad.append((q[:40], r.status_code, r.text[:160]))
        report("p01_planner_fuzz", bool(bad), bad or f"{len(qs)} hostile questions, no 5xx")

    @probe
    def p02_sql_sandbox_attacks():
        attacks = {
            "huge_printf": "SELECT length(printf('%.*c', 400000000, 'x')) AS n FROM transactions_canonical LIMIT 1",
            "pragma_tvf": "SELECT * FROM transactions_canonical, pragma_table_info('transactions_canonical') LIMIT 3",
            "json_each": "SELECT j.value FROM transactions_canonical, json_each('[1,2]') j LIMIT 2",
            "deep_nesting": "SELECT " + "(" * 3000 + "1" + ")" * 3000 + " FROM transactions_canonical LIMIT 1",
            "sqlite_master_quoted": 'SELECT * FROM "sqlite_master"',
            "recursive_cte": "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) SELECT max(n) FROM r, transactions_canonical",
            "group_concat_amplifier": "SELECT length(group_concat('" + "z" * 19000 + "')) AS n FROM transactions_canonical",
            "huge_replace": "SELECT length(replace(hex(zeroblob(1)), '0', printf('%.*c', 200000000, 'y'))) FROM transactions_canonical LIMIT 1",
        }
        out = {}
        for k, sql in attacks.items():
            t = time.perf_counter()
            r = c.post("/api/sql/execute", json={"sql": sql}, headers=A)
            dt = time.perf_counter() - t
            body = r.json()
            ok = r.status_code in (408, 422) or (r.status_code == 200 and k == "json_each")
            out[k] = (r.status_code, round(dt, 2), ok, (body.get("error") or {}).get("code") if isinstance(body, dict) else None,
                      str(body.get("rows", ""))[:80] if r.status_code == 200 else "")
        r = c.post("/api/sql/execute", json={"sql": "SELECT x'00ff' AS b, printf('%.900c','q') || printf('%.900c','q') AS s FROM transactions_canonical LIMIT 1"}, headers=A)
        out["blob_cell"] = (r.status_code, 0, r.status_code == 200, None, r.text[:60])
        bad = {k: v for k, v in out.items() if not v[2]}
        report("p02_sql_sandbox_attacks", bool(bad), bad or out)

    @probe
    def p03_concurrency():
        errs = []
        def work(i):
            if i % 3 == 0:
                r = login(c, "analyst@payinsight.demo")
            else:
                r = c.post("/api/analytics/analyze", json={"question": ["What is the overall success rate?", "Compare success rate by payment method"][i % 2]}, headers=AN)
            if r.status_code >= 500:
                errs.append((i, r.status_code, r.text[:120]))
        t = time.perf_counter()
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(work, range(96)))
        report("p03_concurrency", bool(errs), errs[:3] or f"96 mixed requests on 16 threads in {time.perf_counter()-t:.1f}s, no 5xx")

    @probe
    def p04_refresh_race():
        r = login(c, "analyst@payinsight.demo")
        tok = r.cookies.get("payinsight_refresh")
        codes = []
        barrier = threading.Barrier(8)
        def go(_):
            barrier.wait()
            rr = c.post("/api/auth/refresh", headers=H, cookies={"payinsight_refresh": tok})
            codes.append(rr.status_code)
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(go, range(8)))
        n200 = codes.count(200)
        report("p04_refresh_race", n200 > 1, f"{n200} of 8 concurrent refreshes with the SAME token succeeded (expected exactly 1); codes={sorted(codes)}")

    @probe
    def p05_lockout_race():
        email = "lockrace@example.com"
        c.post("/api/auth/signup", json={"email": email, "full_name": "Lock Race", "password": "Correct-Horse#91"})
        barrier = threading.Barrier(20)
        codes = []
        def go(_):
            barrier.wait()
            codes.append(login(c, email, "wrong-password-X1!").status_code)
        with ThreadPoolExecutor(20) as ex:
            list(ex.map(go, range(20)))
        guesses = codes.count(401)
        report("p05_lockout_race", guesses > get_settings().max_failed_logins,
               f"{guesses} password guesses were evaluated before lockout (policy allows {get_settings().max_failed_logins}); codes={sorted(codes)}")

    @probe
    def p06_reuse_grace_bypass():
        r = login(c, "analyst@payinsight.demo")
        t0 = r.cookies.get("payinsight_refresh")
        r2 = c.post("/api/auth/refresh", headers=H, cookies={"payinsight_refresh": t0})
        acc = r2.json()["access_token"]
        sid = r2.json()["user"]["session_id"]
        # simulate: rotation happened 10 minutes ago (outside grace window)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        with sqlite3.connect(get_settings().app_db_path) as db:
            db.execute("UPDATE auth_sessions SET last_used_at=? WHERE session_id=?", (old, sid))
            if "rotated_at" in [r[1] for r in db.execute("PRAGMA table_info(auth_sessions)")]:
                db.execute("UPDATE auth_sessions SET rotated_at=? WHERE session_id=?", (old, sid))
        c.get("/api/auth/me", headers={"Authorization": "Bearer " + acc})  # ordinary API use bumps last_used_at
        r3 = c.post("/api/auth/refresh", headers=H, cookies={"payinsight_refresh": t0})  # attacker replays stolen OLD token
        code = r3.json()["error"]["code"]
        report("p06_reuse_grace_bypass", code != "REFRESH_TOKEN_REUSED",
               f"stolen token replayed 10 min after rotation -> {code} (expected REFRESH_TOKEN_REUSED + session revoked)")

    @probe
    def p07_stale_history_after_demotion():
        email = "demote@example.com"
        r = c.post("/api/auth/signup", json={"email": email, "full_name": "Demote Me", "password": "Correct-Horse#92"})
        uid = r.json()["user"]["user_id"]
        hb = {"Authorization": "Bearer " + r.json()["access_token"]}
        c.patch(f"/api/admin/users/{uid}", json={"role": "ANALYST"}, headers=A)
        res = c.post("/api/analytics/analyze", json={"question": "Compare payment success rates by bank"}, headers=hb).json()
        c.patch(f"/api/admin/users/{uid}", json={"role": "VIEWER"}, headers=A)
        live = c.post("/api/analytics/analyze", json={"question": "Compare payment success rates by bank"}, headers=hb).status_code
        old = c.get(f"/api/analytics/result/{res['id']}", headers=hb)
        leaked = old.status_code == 200 and "bank" in json.dumps(old.json()).lower()
        report("p07_stale_history_after_demotion", leaked, f"live bank query -> {live}; stored bank result re-read after demotion -> {old.status_code}")

    @probe
    def p08_change_password_bruteforce():
        email = "cpbrute@example.com"
        r = c.post("/api/auth/signup", json={"email": email, "full_name": "CP Brute", "password": "Correct-Horse#93"})
        hb = {"Authorization": "Bearer " + r.json()["access_token"]}
        codes = [c.post("/api/auth/change-password", json={"current_password": f"guess-{i}", "new_password": "Another-Pass#77"}, headers=hb).status_code
                 for i in range(15)]
        report("p08_change_password_bruteforce", 429 not in codes and codes.count(401) == 15,
               f"15 wrong current-password guesses with a stolen access token: {codes} (flaw = all 401, i.e. never throttled or locked)")

    @probe
    def p09_rate_limiter_memory():
        from app.services.auth import RateLimiter
        rl = RateLimiter()
        for i in range(50_000):
            rl.check("login", f"10.{i//65536}.{(i//256)%256}.{i%256}", 30, window_s=0.0001)
        time.sleep(0.01)
        rl.check("login", "1.1.1.1", 30, window_s=0.0001)
        n = rl.backend.size() if hasattr(rl, "backend") else len(rl._hits)
        report("p09_rate_limiter_memory", n > 1000, f"{n} keys retained after 50k one-off IPs whose windows all expired")

    @probe
    def p10_proxy_ip():
        # Dev setup: Vite proxy forwards every browser to the API from 127.0.0.1 -> one shared bucket.
        from app.api.deps import client_info
        from starlette.requests import Request
        req = Request({"type": "http", "client": ("127.0.0.1", 5000), "headers": [(b"x-forwarded-for", b"203.0.113.9")]})
        ip = client_info(req).ip
        report("p10_proxy_ip", ip == "127.0.0.1", f"request via trusted local proxy for client 203.0.113.9 is keyed as {ip}")

    @probe
    def p11_health_disclosure():
        r = c.get("/health")
        report("p11_health_disclosure", bool(r.json().get("database") or r.json().get("cache")),
               f"unauthenticated /health body: {r.json()}")

    @probe
    def p12_admin_revoke_unknown_and_audit():
        r = c.post("/api/admin/users/99999/revoke-sessions", headers=A)
        report("p12_admin_revoke_unknown", r.status_code == 200, f"force sign-out of non-existent user -> {r.status_code} {r.text[:80]}")

    @probe
    def p13_history_growth():
        with sqlite3.connect(get_settings().app_db_path) as db:
            n = db.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(result_json)),0) FROM analysis_history").fetchone()
        report("p13_history_size", n[0] and n[1] / max(n[0], 1) > 50_000, f"{n[0]} stored analyses, avg {n[1]/max(n[0],1)/1024:.1f} KB each")

    @probe
    def p14_error_request_id():
        r = c.post("/api/analytics/analyze", json={"question": "Compare payment success rates by bank"}, headers=V)
        body = r.json()
        rid = (body.get("error") or {}).get("request_id")
        report("p14_error_correlation", rid is None or rid != r.headers.get("x-request-id"), f"403 body request_id={rid}, header X-Request-ID={r.headers.get('x-request-id')}")

    @probe
    def p15_signup_email_edge():
        cases = {"  MiXeD@Example.COM ": 201, "a@b": 422, "x" * 190 + "@e.com": 201, "evil@example.com\n": 201, "a@@b.com": 422, "<s>@x.io": 422}
        bad = []
        for e, exp in cases.items():
            r = c.post("/api/auth/signup", json={"email": e, "full_name": "Edge Case", "password": "Correct-Horse#95"})
            if r.status_code >= 500 or (exp == 422 and r.status_code == 201):
                bad.append((e[:30], r.status_code, r.text[:100]))
        report("p15_signup_email_edge", bool(bad), bad or "ok")

print("\nSUMMARY:", sum(f for _, f, _ in results), "flaw(s) of", len(results))
