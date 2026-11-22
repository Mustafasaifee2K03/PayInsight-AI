"""Scale probe for docs/HARDENING_REPORT.md.

Seeds app.db to production-like volume (env SC_SESS sessions / SC_AUDIT audit rows, default 200k / 500k),
measures hot auth paths, then runs a 32-worker mixed load.
Run from backend/:  .venv/Scripts/python scripts/hardening_scale.py
"""
import os, sys, tempfile, time, statistics, sqlite3, uuid, json
from concurrent.futures import ThreadPoolExecutor

os.environ["PAYINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="pi_scale_")
os.environ["PAYINSIGHT_LOG_LEVEL"] = "ERROR"
os.environ["PAYINSIGHT_PASSWORD_HASH_ITERATIONS"] = "20000"
os.environ["PAYINSIGHT_AUTH_RATE_LIMIT_PER_MINUTE"] = "1000000"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings

SESSIONS, AUDIT = int(os.environ.get('SC_SESS', 200_000)), int(os.environ.get('SC_AUDIT', 500_000))


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


with TestClient(app, raise_server_exceptions=False) as c:
    # ---- seed volume
    t = time.perf_counter()
    db = sqlite3.connect(get_settings().app_db_path)
    db.executemany("INSERT INTO auth_sessions(session_id,user_id,refresh_token_hash,created_at,last_used_at,expires_at) VALUES (?,?,?,?,?,?)",
                   ((uuid.uuid4().hex, 1 + i % 3, uuid.uuid4().hex + str(i), "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00",
                     "2026-12-30T00:00:00+00:00") for i in range(SESSIONS)))
    ev = ["LOGIN", "TOKEN_REFRESH", "LOGOUT", "SIGNUP"]
    db.executemany("INSERT INTO auth_audit_log(occurred_at,event_type,outcome,user_id,ip_address) VALUES (?,?,?,?,?)",
                   (("2026-11-01T00:00:00+00:00", ev[i % 4] if i % 1000 else "ACCOUNT_LOCKED", "SUCCESS", 1 + i % 3, "10.0.0.1") for i in range(AUDIT)))
    db.commit(); db.close()
    print(f"seeded {SESSIONS:,} sessions + {AUDIT:,} audit rows in {time.perf_counter()-t:.1f}s")

    A = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@payinsight.demo", "password": "PayInsight@2026"}).json()["access_token"]}

    def timeit(fn, n):
        xs = []
        for _ in range(n):
            t = time.perf_counter(); r = fn(); xs.append((time.perf_counter() - t) * 1000)
            assert r.status_code < 500, r.text[:200]
        return round(statistics.median(xs), 1), round(pct(xs, 95), 1)

    print("login (p50, p95 ms):", timeit(lambda: c.post("/api/auth/login", json={"email": "analyst@payinsight.demo", "password": "PayInsight@2026"}), 30))
    print("audit filter ACCOUNT_LOCKED (p50, p95 ms):", timeit(lambda: c.get("/api/admin/audit?event_type=ACCOUNT_LOCKED&limit=100", headers=A), 30))
    print("audit latest page (p50, p95 ms):", timeit(lambda: c.get("/api/admin/audit?limit=100", headers=A), 30))
    print("admin users (p50, p95 ms):", timeit(lambda: c.get("/api/admin/users", headers=A), 30))

    # ---- concurrent mixed load (32 workers)
    AN = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "analyst@payinsight.demo", "password": "PayInsight@2026"}).json()["access_token"]}
    qs = ["What is the overall success rate?", "Compare payment success rates by bank", "Why did payment success rate decline?",
          "Show daily transaction trends", "Which payment methods have the highest failure rates?", "Is the decline caused by payment-method mix?"]
    lat, codes, kinds = [], [], {}

    def work(i):
        t = time.perf_counter()
        k = i % 10
        if k < 6:
            r = c.post("/api/analytics/analyze", json={"question": qs[i % len(qs)] + (" last 14 days" if i % 2 else "")}, headers=AN)
        elif k < 9:
            r = c.get("/api/auth/me", headers=AN)
        else:
            r = c.post("/api/auth/login", json={"email": "viewer@payinsight.demo", "password": "PayInsight@2026"})
        lat.append((time.perf_counter() - t) * 1000); codes.append(r.status_code)
        kinds.setdefault('analyze' if k < 6 else 'me' if k < 9 else 'login', []).append(lat[-1])
    t = time.perf_counter()
    with ThreadPoolExecutor(32) as ex:
        list(ex.map(work, range(640)))
    wall = time.perf_counter() - t
    errs = [x for x in codes if x >= 500]
    print(json.dumps({"requests": len(codes), "workers": 32, "wall_s": round(wall, 1), "throughput_rps": round(len(codes) / wall, 1),
                      "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1), "p99_ms": round(pct(lat, 99), 1),
                      "5xx": len(errs), "by_kind_p50_p95_max": {k: (round(pct(v, 50)), round(pct(v, 95)), round(max(v))) for k, v in kinds.items()}, "status_counts": {str(k): codes.count(k) for k in sorted(set(codes))}}))
