"""Progressive acceptance iterations 1–18 (see docs/TEST_PLAN.md).

Every check compares the application's answer with an *independent* computation
(direct SQL on the database, or a Python loop over raw rows) — never with itself.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from app.config import get_settings
from app.database.generator import QUALITY_INJECTION, build_database
from app.database.manager import get_db
from app.services.decomposition import decompose
from app.services.query_executor import cache

S = get_settings()
START, END = S.data_start_date.isoformat(), S.data_end_date.isoformat()


def ask(client, headers, q):
    r = client.post("/api/analytics/analyze", json={"question": q}, headers=headers)
    return r


def window_where(start, end_inclusive):
    from datetime import date, timedelta
    e = (date.fromisoformat(end_inclusive) + timedelta(days=1)).isoformat()
    return f"transaction_timestamp >= '{start} 00:00:00' AND transaction_timestamp < '{e} 00:00:00'"


# ------------------------------------------------------------------ 1
def test_iter01_health_and_startup(client, admin, record):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "No external AI API" in r.json()["planner"]
    assert r.json().get("database") is None  # public probe no longer discloses internals (hardening iteration 8)
    r = client.get("/api/system/status", headers=admin)
    body = r.json()
    assert r.status_code == 200 and body["database"]["canonical_rows"] == 30_000
    record(1, "Application health and backend startup", "GET /health + GET /api/system/status (admin)",
           "HTTP 200, status ok, local planner, 30,000 canonical rows",
           f"HTTP {r.status_code}, status={body['status']}, rows={body['database']['canonical_rows']}, planner='{body['planner']}'")


# ------------------------------------------------------------------ 2
def test_iter02_database_init_relationships_counts(client, db_conn, record):
    c = db_conn()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    required = {"transactions_raw", "merchants", "banks", "payment_methods", "settlements", "bank_daily_reports",
                "v_transactions_canonical", "transactions_canonical"}
    assert required <= tables
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("transactions_raw", "merchants", "banks", "payment_methods", "settlements", "bank_daily_reports")}
    assert counts["transactions_raw"] == 30_000 and counts["merchants"] == 24 and counts["banks"] == 8 and counts["payment_methods"] == 4
    assert counts["settlements"] > 0 and counts["bank_daily_reports"] == 8 * 60
    fks = c.execute("SELECT COUNT(*) FROM pragma_foreign_key_list('transactions_raw')").fetchone()[0]
    assert fks == 4
    violations = c.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []
    view_n = c.execute("SELECT COUNT(*) FROM v_transactions_canonical").fetchone()[0]
    assert view_n == c.execute("SELECT COUNT(*) FROM transactions_canonical").fetchone()[0]
    idx = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions_raw'")}
    assert {"idx_raw_ts", "idx_raw_txn", "idx_raw_merchant", "idx_raw_bank", "idx_raw_method", "idx_raw_status"} <= idx
    record(2, "Database initialisation, relationships and seed counts", "sqlite_master, pragma_foreign_key_list, COUNT(*)",
           "All 6 tables + canonical view; 30,000 txns, 24 merchants, 8 banks, 4 methods; 4 FKs; 0 FK violations",
           f"{counts}; FKs on transactions_raw={fks}; FK violations={len(violations)}; view rows={view_n}")


# ------------------------------------------------------------------ 3
def test_iter03_transaction_count_vs_direct_sql(client, analyst, db_conn, record):
    r = ask(client, analyst, "How many transactions occurred?")
    j = r.json()
    app_val = j["kpis"][0]["value"]
    direct = db_conn().execute(f"SELECT COUNT(*) FROM transactions_canonical WHERE {window_where(START, END)}").fetchone()[0]
    raw_distinct = db_conn().execute("SELECT COUNT(DISTINCT transaction_id) FROM transactions_raw").fetchone()[0]
    assert j["interpretation"]["metric"] == "transaction_count"
    assert app_val == direct == raw_distinct == 30_000
    record(3, "Overall transaction count vs direct SQL", "How many transactions occurred?",
           "App count == independent COUNT(*) == COUNT(DISTINCT transaction_id)",
           f"app={app_val:,.0f}, direct SQL={direct:,}, distinct raw ids={raw_distinct:,}")


# ------------------------------------------------------------------ 4
def test_iter04_success_rate_independent(client, analyst, db_conn, record):
    j = ask(client, analyst, "What is the overall success rate?").json()
    k = j["kpis"][0]
    statuses = [s for (s,) in db_conn().execute(f"SELECT status FROM transactions_canonical WHERE {window_where(START, END)}")]
    succ = sum(1 for s in statuses if s == "SUCCESS")
    elig = sum(1 for s in statuses if s in ("SUCCESS", "FAILED"))
    independent = 100 * succ / elig
    assert k["numerator"] == succ and k["denominator"] == elig
    assert abs(k["value"] - independent) < 1e-9
    assert any(m["name"] == "success_rate" and "PENDING" in " ".join(m["notes"]) for m in j["metric_definitions"])
    record(4, "Overall success rate vs independent Python calculation", "What is the overall success rate?",
           "SUCCESS/(SUCCESS+FAILED)x100 matches independent loop; numerator/denominator exposed; PENDING excluded",
           f"app={k['value']:.4f}% ({k['numerator']}/{k['denominator']}); independent={independent:.4f}% ({succ}/{elig}); pending excluded={sum(1 for s in statuses if s == 'PENDING')}")


# ------------------------------------------------------------------ 5
def test_iter05_daily_trend_date_filtering(client, analyst, db_conn, record):
    j = ask(client, analyst, "Show daily transaction trends for the last 14 days").json()
    tr = j["interpretation"]["time_range"]
    rows = j["tables"][0]["rows"]
    assert tr["start"] == "2025-10-17" and tr["end"] == END and tr["days"] == 14
    assert len(rows) == 14 and rows[0]["day"] == "2025-10-17" and rows[-1]["day"] == END
    direct = dict(db_conn().execute(
        f"SELECT date(transaction_timestamp), COUNT(*) FROM transactions_canonical WHERE {window_where('2025-10-17', END)} GROUP BY 1").fetchall())
    assert all(direct[r["day"]] == r["attempts"] for r in rows)
    assert "2025-10-16" not in {r["day"] for r in rows}
    record(5, "Daily trend with correct date filtering", "Show daily transaction trends for the last 14 days",
           "14 rows 2025-10-17..2025-10-30 (anchored to data end), each day == direct SQL count, no day outside window",
           f"range={tr['start']}..{tr['end']} ({tr['days']}d), rows={len(rows)}, first={rows[0]['day']}:{rows[0]['attempts']}, last={rows[-1]['day']}:{rows[-1]['attempts']}, all days match direct SQL")


# ------------------------------------------------------------------ 6
def test_iter06_payment_method_breakdown(client, analyst, db_conn, record):
    j = ask(client, analyst, "Compare payment success rates by payment method").json()
    rows = {r["payment_method"]: r for r in j["tables"][0]["rows"]}
    direct = db_conn().execute(f"""SELECT pm.method_name, SUM(status='SUCCESS'), SUM(status IN ('SUCCESS','FAILED'))
        FROM transactions_canonical t JOIN payment_methods pm USING(payment_method_id) WHERE {window_where(START, END)} GROUP BY 1""").fetchall()
    assert len(rows) == 4
    for name, s, e in direct:
        assert abs(rows[name]["metric_value"] - 100 * s / e) < 1e-9
    assert abs(sum(r["share_pct"] for r in rows.values()) - 100) < 1e-6
    record(6, "Payment-method breakdown", "Compare payment success rates by payment method",
           "4 methods; each success rate equals direct SQL; shares sum to 100%",
           "; ".join(f"{n} {rows[n]['metric_value']:.2f}% (direct {100 * s / e:.2f}%)" for n, s, e in direct))


# ------------------------------------------------------------------ 7
def test_iter07_bank_breakdown_analyst(client, analyst, db_conn, record):
    r = ask(client, analyst, "Compare payment success rates by bank")
    j = r.json()
    rows = {x["bank"]: x["metric_value"] for x in j["tables"][0]["rows"]}
    direct = {n: 100 * s / e for n, s, e in db_conn().execute(f"""SELECT b.bank_name, SUM(status='SUCCESS'), SUM(status IN ('SUCCESS','FAILED'))
        FROM transactions_canonical t JOIN banks b USING(bank_id) WHERE {window_where(START, END)} GROUP BY 1""")}
    assert r.status_code == 200 and len(rows) == 8
    assert all(abs(rows[k] - v) < 1e-9 for k, v in direct.items())
    record(7, "Bank-level breakdown for an authorised analyst", "ANALYST: Compare payment success rates by bank",
           "HTTP 200; 8 banks; every rate equals direct SQL",
           f"HTTP {r.status_code}; {len(rows)} banks; max |diff| = {max(abs(rows[k] - v) for k, v in direct.items()):.1e}")


# ------------------------------------------------------------------ 8
def test_iter08_top_failed_merchants(client, analyst, db_conn, record):
    j = ask(client, analyst, "Which merchants have the highest failed transaction volumes?").json()
    rows = j["tables"][0]["rows"]
    direct = db_conn().execute(f"""SELECT m.merchant_name, SUM(status='FAILED') f FROM transactions_canonical t JOIN merchants m USING(merchant_id)
        WHERE {window_where(START, END)} GROUP BY 1 ORDER BY f DESC LIMIT 10""").fetchall()
    assert j["interpretation"]["intent"] == "ranking" and j["interpretation"]["metric"] == "failed_transactions"
    assert [(r["merchant"], r["failed"]) for r in rows] == [(n, f) for n, f in direct]
    record(8, "Top failed merchants", "Which merchants have the highest failed transaction volumes?",
           "Ranking intent, failed_transactions metric, top-10 order identical to direct SQL",
           f"top 3 app={[(r['merchant'], r['failed']) for r in rows[:3]]}; direct={direct[:3]}")


# ------------------------------------------------------------------ 9
def test_iter09_equal_length_period_comparison(client, analyst, db_conn, record):
    j = ask(client, analyst, "Compare the last 7 days with the previous 7 days").json()
    it = j["interpretation"]
    cur, prev = it["time_range"], it["comparison_range"]
    assert cur["days"] == prev["days"] == 7 and prev["end"] == "2025-10-23" and cur["start"] == "2025-10-24"
    sr = next(k for k in j["kpis"] if k["metric"] == "success_rate")
    q = "SELECT SUM(status='SUCCESS')*1.0/SUM(status IN ('SUCCESS','FAILED'))*100 FROM transactions_canonical WHERE "
    v1 = db_conn().execute(q + window_where(cur["start"], cur["end"])).fetchone()[0]
    v0 = db_conn().execute(q + window_where(prev["start"], prev["end"])).fetchone()[0]
    assert abs(sr["value"] - v1) < 1e-9 and abs(sr["previous"] - v0) < 1e-9
    assert abs(sr["change_abs"] - (v1 - v0)) < 1e-9                       # percentage points
    assert abs(sr["change_pct"] - (v1 - v0) / v0 * 100) < 1e-9            # relative %
    record(9, "Equal-length previous-period comparison", "Compare the last 7 days with the previous 7 days",
           "Two 7-day periods (10-17..10-23 vs 10-24..10-30); pp change and relative % reported separately and correct",
           f"prev={v0:.3f}%, curr={v1:.3f}%, change={sr['change_abs']:+.3f} pp, relative={sr['change_pct']:+.3f}%")


# ------------------------------------------------------------------ 10
def test_iter10_failure_code_distribution(client, analyst, db_conn, record):
    j = ask(client, analyst, "What are the main failure codes?").json()
    rows = j["tables"][0]["rows"]
    total_failed = db_conn().execute(f"SELECT SUM(status='FAILED') FROM transactions_canonical WHERE {window_where(START, END)}").fetchone()[0]
    direct = dict(db_conn().execute(f"SELECT failure_code, COUNT(*) FROM transactions_canonical WHERE status='FAILED' AND {window_where(START, END)} GROUP BY 1"))
    assert sum(r["failed"] for r in rows) == total_failed
    assert {r["failure_code"]: r["failed"] for r in rows} == direct
    assert abs(sum(r["share_pct"] for r in rows) - 100) < 1e-6
    record(10, "Failure-code distribution", "What are the main failure codes?",
           "Counts per code equal direct SQL; sum equals total failed; shares sum to 100%",
           f"{len(rows)} codes, sum={sum(r['failed'] for r in rows)} vs failed={total_failed}; top={rows[0]['failure_code']} {rows[0]['failed']}")


# ------------------------------------------------------------------ 11
def test_iter11_mix_decomposition_math(client, analyst, scenario, record):
    # (a) hand-verifiable example incl. a segment absent in the current period
    segs = [{"segment": "A", "b_elig": 600, "b_succ": 570, "c_elig": 300, "c_succ": 285},
            {"segment": "B", "b_elig": 400, "b_succ": 320, "c_elig": 650, "c_succ": 520},
            {"segment": "C", "b_elig": 50, "b_succ": 40, "c_elig": 0, "c_succ": 0}]
    d = decompose(segs)
    direct = 100 * (805 / 950 - 930 / 1050)
    assert abs(d["direct_change_pp"] - direct) < 1e-12 and d["identity_holds"]
    # (b) scenario D through the API
    scenario("D")
    j = ask(client, analyst, "Is the decline caused by payment-method mix?").json()
    dec = j["decomposition"]
    assert abs(dec["within_effect_pp"] + dec["mix_effect_pp"] - dec["direct_change_pp"]) < 1e-9
    assert j["verdict"]["type"] == "mix_shift" and dec["mix_effect_pp"] / dec["direct_change_pp"] > 0.6
    record(11, "Mix-shift decomposition verified mathematically", "Scenario D: Is the decline caused by payment-method mix?",
           "within + mix == direct change (|residual| < 1e-9); mix > 60% of change; verdict mix_shift; hand example incl. zero-volume segment exact",
           f"direct={dec['direct_change_pp']:+.4f} pp = within {dec['within_effect_pp']:+.4f} + mix {dec['mix_effect_pp']:+.4f} (residual {dec['residual_pp']:.1e}); verdict={j['verdict']['label']}; hand example residual={d['residual_pp']:.1e}")


# ------------------------------------------------------------------ 12
def test_iter12_bank_decline_scenario(client, analyst, scenario, record):
    scenario("B")
    j = ask(client, analyst, "Why did payment success rate decline?").json()
    v = j["verdict"]
    assert v["type"] == "performance" and v["dimension"] == "bank" and v["segment"] == "Deccan Commercial Bank"
    sr = next(k for k in j["kpis"] if k["metric"] == "success_rate")
    assert sr["change_abs"] < -2.0
    shift = next(t for t in j["tables"] if t["id"] == "failure_shift")["rows"][0]
    assert shift["code"] == "BANK_TIMEOUT"
    assert j["hypotheses"] and j["recommendations"]
    c = ask(client, analyst, "Which banks contributed most to the decline?").json()
    top = c["tables"][0]["rows"][0]
    assert top["segment"] == "Deccan Commercial Bank" and top["share_of_change_pct"] > 80
    record(12, "Bank-specific performance decline scenario", "Scenario B: Why did payment success rate decline? / Which banks contributed most?",
           "Verdict = deterioration in bank Deccan Commercial Bank; BANK_TIMEOUT is the largest failure-code increase; >80% of change attributed",
           f"SR change {sr['change_abs']:+.2f} pp; verdict={v['label']} ({v['segment']}); Deccan contribution {top['contribution_pp']:+.2f} pp ({top['share_of_change_pct']:.0f}% of change); BANK_TIMEOUT {shift['baseline']}→{shift['current']}")


# ------------------------------------------------------------------ 13
def test_iter13_duplicate_and_missing_data_detection(client, admin, analyst, scenario, record):
    scenario("E")
    q = client.get("/api/quality", headers=admin).json()
    got = {c["id"]: c["affected"] for c in q["checks"]}
    assert q["raw_rows"] == 30_300 and q["canonical_rows"] == 30_000
    assert got["duplicate_transaction_ids"] == QUALITY_INJECTION["duplicate_versions"]
    assert got["missing_merchant_id"] == QUALITY_INJECTION["missing_merchant_id"]
    assert got["missing_bank_id"] == QUALITY_INJECTION["missing_bank_id"]
    assert got["missing_payment_method_id"] == QUALITY_INJECTION["missing_payment_method_id"]
    assert got["orphan_references"] == QUALITY_INJECTION["orphan_merchant_id"]
    assert got["invalid_status"] == QUALITY_INJECTION["invalid_status"]
    assert got["invalid_amount"] == QUALITY_INJECTION["invalid_amount"]
    assert got["invalid_timestamp"] == QUALITY_INJECTION["invalid_timestamp"]
    assert got["failed_without_failure_code"] >= QUALITY_INJECTION["failed_without_failure_code"]
    assert q["status"] == "fail"
    detected = {k: v for k, v in got.items() if v}
    j = ask(client, analyst, "What is the overall success rate?").json()
    assert j["data_quality"]["status"] == "fail" and len(j["data_quality"]["warnings"]) >= 9
    record(13, "Duplicate and missing-data injection and detection", "Scenario E: GET /api/quality + analysis",
           "Every injected defect detected with the exact injected count; raw 30,300 vs canonical 30,000; warnings attached to analyses",
           f"raw={q['raw_rows']}, canonical={q['canonical_rows']}, detected={detected}")


# ------------------------------------------------------------------ 14
def test_iter14_viewer_access_control(client, viewer, analyst, record):
    r = ask(client, viewer, "Compare payment success rates by bank")
    body = r.json()
    assert r.status_code == 403 and body["error"]["code"] == "ROLE_RESTRICTED_DIMENSION"
    r2 = ask(client, viewer, "Which merchants have the highest failed transaction volumes?")
    assert r2.status_code == 403
    assert client.get("/api/quality", headers=viewer).status_code == 403
    assert client.get("/api/reconciliation", headers=viewer).status_code == 403
    assert client.post("/api/scenarios/activate", json={"scenario_id": "B"}, headers=analyst).status_code == 403
    assert client.post("/api/sql/execute", json={"sql": "SELECT 1 FROM banks"}, headers=analyst).status_code == 403
    assert client.get("/api/dashboard/overview").status_code == 401
    ok = ask(client, viewer, "Compare payment success rates by payment method")
    assert ok.status_code == 200
    dash = client.get("/api/dashboard/overview", headers=viewer).json()
    assert dash["banks"] is None
    record(14, "Viewer access-control rejection", "VIEWER: Compare payment success rates by bank (+ merchant, quality, reconciliation; ANALYST activate/sandbox; no token)",
           "403 ROLE_RESTRICTED_DIMENSION for bank & merchant; 403 for admin endpoints; 401 without token; method breakdown allowed; dashboard omits banks",
           f"bank={r.status_code} {body['error']['code']}; merchant={r2.status_code}; method={ok.status_code}; no-token=401; dashboard banks={dash['banks']}")


# ------------------------------------------------------------------ 15
@pytest.mark.parametrize("sql", [
    "SELECT * FROM banks; DROP TABLE banks",
    "DROP TABLE transactions_raw",
    "DELETE FROM banks",
    "INSERT INTO banks VALUES ('X','x','x','x','ACTIVE')",
    "UPDATE merchants SET risk_tier = 'LOW'",
    "ALTER TABLE banks ADD COLUMN x TEXT",
    "ATTACH DATABASE 'evil.db' AS evil",
    "PRAGMA writable_schema = 1",
    "SELECT * FROM sqlite_master",
    "SELECT load_extension('evil')",
    "SELECT * FROM banks -- WHERE 1=0",
    "SELECT * FROM main.banks",
])
def test_iter15_unsafe_sql_rejected(client, admin, sql, record):
    r = client.post("/api/sql/execute", json={"sql": sql}, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "SQL_REJECTED"
    record(15, "SQL injection / unsafe query rejected", sql, "HTTP 422 SQL_REJECTED with readable reason",
           f"HTTP {r.status_code}: {r.json()['error']['details']['reasons'][0]}")


def test_iter15_injection_via_question_and_expensive_query(client, admin, analyst, db_conn, record):
    r = ask(client, analyst, "Show success rate for bank '; DROP TABLE banks; --")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r2 = ask(client, analyst, "What is the success rate for Deccan Commercial Bank' OR '1'='1")
    j2 = r2.json()
    assert j2["status"] == "completed"
    assert all("OR '1'='1" not in q["sql"] for q in j2["queries"])  # values are bound parameters, never interpolated
    assert db_conn().execute("SELECT COUNT(*) FROM banks").fetchone()[0] == 8
    old = S.query_timeout_ms
    S.query_timeout_ms = 500
    try:
        t0 = time.perf_counter()
        r3 = client.post("/api/sql/execute", json={"sql": "SELECT COUNT(*) FROM transactions_canonical a, transactions_canonical b"}, headers=admin)
        elapsed = time.perf_counter() - t0
    finally:
        S.query_timeout_ms = old
    assert r3.status_code == 408 and r3.json()["error"]["code"] == "QUERY_TIMEOUT" and elapsed < 3
    # defence in depth: the authorizer blocks writes even if the validator were bypassed
    from app.services.query_executor import _authorizer
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t(x)")
    conn.set_authorizer(_authorizer)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("INSERT INTO t VALUES (1)")
    record(15, "Injection via question, expensive query, authorizer", "NL injection strings; 900M-row cross join with 500 ms limit; INSERT under authorizer",
           "Write-intent question rejected; quote payload never reaches SQL; cross join cancelled (HTTP 408); authorizer denies INSERT; banks table intact",
           f"q1={r.json()['status']}; q2 completed with bound params; cross join HTTP {r3.status_code} after {elapsed:.2f}s; authorizer raised DatabaseError; banks=8")


# ------------------------------------------------------------------ 16
def test_iter16_ambiguous_questions(client, analyst, record):
    a = ask(client, analyst, "How are we doing?").json()
    b = ask(client, analyst, "Which bank is best?").json()
    c = ask(client, analyst, "Compare the last 45 days with the previous 45 days").json()
    d = ask(client, analyst, "What was the success rate in March 2024?").json()
    assert a["status"] == "needs_clarification" and a["suggestions"]
    assert b["status"] == "completed" and any("success rate" in s.lower() for s in b["interpretation"]["assumptions"])
    assert any("full available data window" in s for s in b["interpretation"]["assumptions"])
    assert c["status"] == "needs_clarification" and "equal-length" in c["message"]
    assert d["status"] == "needs_clarification" and "Data is available" in d["message"]
    record(16, "Ambiguous question handling", "'How are we doing?' / 'Which bank is best?' / 45d vs 45d / March 2024",
           "Clarify when no metric; explicit assumptions for metric/date defaults; refuse unequal comparison; refuse out-of-window dates",
           f"a={a['status']}; b assumptions={b['interpretation']['assumptions']}; c={c['status']}; d={d['status']}")


# ------------------------------------------------------------------ 17
def test_iter17_cache_hit_and_invalidation(client, analyst, admin, record):
    q = "Compare bank-level performance across periods"
    first = ask(client, analyst, q).json()["execution"]
    second = ask(client, analyst, q).json()["execution"]
    assert second["cache_hits"] == second["query_count"] and second["query_count"] > 0
    gen_before = get_db().generation
    client.post("/api/scenarios/activate", json={"scenario_id": "C"}, headers=admin)
    assert cache.stats()["entries"] == 0 and get_db().generation > gen_before
    third = ask(client, analyst, q).json()["execution"]
    assert third["cache_hits"] == 0
    client.post("/api/scenarios/activate", json={"scenario_id": "A"}, headers=admin)
    record(17, "Cache hit and invalidation", f"'{q}' x2, then activate scenario, then again",
           "2nd run: all queries cached; activation clears cache and bumps generation; 3rd run: 0 hits",
           f"1st: {first['cache_hits']}/{first['query_count']} hits {first['sql_ms']} ms SQL; 2nd: {second['cache_hits']}/{second['query_count']} hits {second['sql_ms']} ms; after activation: {third['cache_hits']} hits")


# ------------------------------------------------------------------ 18
def test_iter18_performance_100k(client, analyst, record, tmp_path):
    db = get_db()
    path = tmp_path / "perf_100k.db"
    t0 = time.perf_counter()
    gen = build_database(path, "bank_decline", 100_000, S.random_seed, S.data_start_date, S.data_days)
    gen_s = time.perf_counter() - t0
    db.use_path(path)
    cache.clear()
    timings = {}
    try:
        for q in ["What is the overall success rate?", "Show daily transaction trends", "Compare payment success rates by bank",
                  "Compare the last 7 days with the previous 7 days", "Why did payment success rate decline?"]:
            t1 = time.perf_counter()
            r = ask(client, analyst, q)
            timings[q] = time.perf_counter() - t1
            assert r.status_code == 200 and r.json()["status"] == "completed"
        why = r.json()
        assert why["verdict"]["segment"] == "Deccan Commercial Bank"
    finally:
        db.activate("baseline")
        cache.clear()
    assert gen.canonical_rows == 100_000
    assert max(timings.values()) < 3.0
    record(18, "Performance with 100,000 transactions", "100k-row bank_decline DB; 5 representative questions (cold cache, end-to-end HTTP)",
           "Batched generation; every analysis < 3 s end-to-end; root cause still identified",
           f"generation {gen_s:.1f}s; " + "; ".join(f"'{k}' {v * 1000:.0f} ms" for k, v in timings.items()))
