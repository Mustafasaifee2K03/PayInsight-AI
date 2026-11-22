# Benchmark & Test Report

This report is **generated from real runs**:
- The progressive-iteration table is written by `pytest` (`backend/tests/conftest.py`) from what each test recorded during the run, together with pytest's own pass/fail outcome and duration.
- The performance table is written by `backend/scripts/benchmark.py`.
- Raw data: `docs/generated/progressive_results.json` and `docs/generated/benchmark_results*.json`.

Nothing in the generated sections was typed by hand. To regenerate, run `scripts\run_tests.ps1 -Benchmark`.

## 1. Summary of the latest run

| Check | Result |
|---|---|
| Backend pytest (unit + auth + hardening + progressive) | **153 / 153 passed** (51 unit, 25 auth/session/RBAC, 47 hardening regressions, 30 progressive cases covering iterations 1–18) |
| Frontend `tsc --noEmit` (strict) | clean |
| Frontend Vitest | **8 / 8 passed** |
| Frontend production build | succeeds (Recharts chunk 538 kB / 154 kB gzip) |
| Browser journeys (Playwright + Edge) | **12 / 12 passed** (J9–J12 cover session restore, signup, live role change, disable) |
| Fresh-checkout reproduction | Copied the repo **without** venv, node_modules, databases or .env, then ran `setup.ps1` and `run_tests.ps1`: setup exit 0, all checks passed |

## 2. Progressive test iterations (1–18)

Each row records the test number, scenario, input, expected output, actual output captured during the run, pass/fail, and execution time. Failures found **during development**, with their cause, fix and retest result, are listed in section 4.

<!-- PROGRESSIVE:START -->
_Generated automatically by `pytest` on 2026-11-21 13:58 UTC — 30/30 iteration checks passed._

| # | Scenario | Input | Expected | Actual (recorded during the run) | Result | Time (s) | Failure cause |
|---|---|---|---|---|---|---|---|
| 1 | Application health and backend startup | GET /health + GET /api/system/status (admin) | HTTP 200, status ok, local planner, 30,000 canonical rows | HTTP 200, status=ok, rows=30000, planner='Local deterministic analysis engine — No external AI API' | PASS | 0.009 | — |
| 2 | Database initialisation, relationships and seed counts | sqlite_master, pragma_foreign_key_list, COUNT(*) | All 6 tables + canonical view; 30,000 txns, 24 merchants, 8 banks, 4 methods; 4 FKs; 0 FK violations | {'transactions_raw': 30000, 'merchants': 24, 'banks': 8, 'payment_methods': 4, 'settlements': 1440, 'bank_daily_reports': 480}; FKs on transactions_raw=4; FK violations=0; view rows=30000 | PASS | 0.151 | — |
| 3 | Overall transaction count vs direct SQL | How many transactions occurred? | App count == independent COUNT(*) == COUNT(DISTINCT transaction_id) | app=30,000, direct SQL=30,000, distinct raw ids=30,000 | PASS | 0.082 | — |
| 4 | Overall success rate vs independent Python calculation | What is the overall success rate? | SUCCESS/(SUCCESS+FAILED)x100 matches independent loop; numerator/denominator exposed; PENDING excluded | app=91.7586% (27122/29558); independent=91.7586% (27122/29558); pending excluded=442 | PASS | 0.037 | — |
| 5 | Daily trend with correct date filtering | Show daily transaction trends for the last 14 days | 14 rows 2025-10-17..2025-10-30 (anchored to data end), each day == direct SQL count, no day outside window | range=2025-10-17..2025-10-30 (14d), rows=14, first=2025-10-17:525, last=2025-10-30:476, all days match direct SQL | PASS | 0.031 | — |
| 6 | Payment-method breakdown | Compare payment success rates by payment method | 4 methods; each success rate equals direct SQL; shares sum to 100% | Credit Card 91.73% (direct 91.73%); Debit Card 90.45% (direct 90.45%); Net Banking 80.61% (direct 80.61%); UPI 94.60% (direct 94.60%) | PASS | 0.081 | — |
| 7 | Bank-level breakdown for an authorised analyst | ANALYST: Compare payment success rates by bank | HTTP 200; 8 banks; every rate equals direct SQL | HTTP 200; 8 banks; max \|diff\| = 0.0e+00 | PASS | 0.043 | — |
| 8 | Top failed merchants | Which merchants have the highest failed transaction volumes? | Ranking intent, failed_transactions metric, top-10 order identical to direct SQL | top 3 app=[('ShopSphere Online', 243), ('LuxeDeals Flash Sales', 206), ('QuickBite Foods', 199)]; direct=[('ShopSphere Online', 243), ('LuxeDeals Flash Sales', 206), ('QuickBite Foods', 199)] | PASS | 0.113 | — |
| 9 | Equal-length previous-period comparison | Compare the last 7 days with the previous 7 days | Two 7-day periods (10-17..10-23 vs 10-24..10-30); pp change and relative % reported separately and correct | prev=91.085%, curr=91.779%, change=+0.694 pp, relative=+0.762% | PASS | 0.023 | — |
| 10 | Failure-code distribution | What are the main failure codes? | Counts per code equal direct SQL; sum equals total failed; shares sum to 100% | 7 codes, sum=2436 vs failed=2436; top=INSUFFICIENT_FUNDS 494 | PASS | 0.047 | — |
| 11 | Mix-shift decomposition verified mathematically | Scenario D: Is the decline caused by payment-method mix? | within + mix == direct change (\|residual\| < 1e-9); mix > 60% of change; verdict mix_shift; hand example incl. zero-volume segment exact | direct=-3.1679 pp = within +0.7099 + mix -3.8778 (residual 4.0e-15); verdict=Transaction mix shift; hand example residual=-8.4e-15 | PASS | 1.253 | — |
| 12 | Bank-specific performance decline scenario | Scenario B: Why did payment success rate decline? / Which banks contributed most? | Verdict = deterioration in bank Deccan Commercial Bank; BANK_TIMEOUT is the largest failure-code increase; >80% of change attributed | SR change -3.00 pp; verdict=Performance deterioration within a segment (Deccan Commercial Bank); Deccan contribution -3.40 pp (113% of change); BANK_TIMEOUT 13→142 | PASS | 1.283 | — |
| 13 | Duplicate and missing-data injection and detection | Scenario E: GET /api/quality + analysis | Every injected defect detected with the exact injected count; raw 30,300 vs canonical 30,000; warnings attached to analyses | raw=30300, canonical=30000, detected={'duplicate_transaction_ids': 300, 'conflicting_duplicates': 196, 'missing_merchant_id': 120, 'missing_bank_id': 80, 'missing_payment_method_id': 40, 'orphan_references': 30, 'invalid_status': 15, 'invalid_amount': 20, 'invalid_timestamp': 10, 'failed_without_failure_code': 25, 'non_inr_transactions': 102} | PASS | 2.357 | — |
| 14 | Viewer access-control rejection | VIEWER: Compare payment success rates by bank (+ merchant, quality, reconciliation; ANALYST activate/sandbox; no token) | 403 ROLE_RESTRICTED_DIMENSION for bank & merchant; 403 for admin endpoints; 401 without token; method breakdown allowed; dashboard omits banks | bank=403 ROLE_RESTRICTED_DIMENSION; merchant=403; method=200; no-token=401; dashboard banks=None | PASS | 0.312 | — |
| 15 | Injection via question, expensive query, authorizer | NL injection strings; 900M-row cross join with 500 ms limit; INSERT under authorizer | Write-intent question rejected; quote payload never reaches SQL; cross join cancelled (HTTP 408); authorizer denies INSERT; banks table intact | q1=rejected; q2 completed with bound params; cross join HTTP 408 after 0.51s; authorizer raised DatabaseError; banks=8 | PASS | 0.576 | — |
| 15 | SQL injection / unsafe query rejected | ALTER TABLE banks ADD COLUMN x TEXT | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Only SELECT queries are allowed (received ALTER). | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | ATTACH DATABASE 'evil.db' AS evil | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: ATTACH statements are not allowed. | PASS | 0.005 | — |
| 15 | SQL injection / unsafe query rejected | DELETE FROM banks | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Only SELECT queries are allowed (received DELETE). | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | DROP TABLE transactions_raw | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Only SELECT queries are allowed (received DROP). | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | INSERT INTO banks VALUES ('X','x','x','x','ACTIVE') | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Only SELECT queries are allowed (received INSERT). | PASS | 0.005 | — |
| 15 | SQL injection / unsafe query rejected | PRAGMA writable_schema = 1 | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: PRAGMA statements are not allowed. | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | SELECT * FROM banks -- WHERE 1=0 | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: SQL comments are not allowed in executed queries. | PASS | 0.005 | — |
| 15 | SQL injection / unsafe query rejected | SELECT * FROM banks; DROP TABLE banks | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Multiple statements are not allowed (found ';' separating statements). | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | SELECT * FROM main.banks | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Schema-qualified table references are not allowed (main.banks). | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | SELECT * FROM sqlite_master | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Table(s) not in the approved allowlist: sqlite_master. | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | SELECT load_extension('evil') | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: LOAD_EXTENSION statements are not allowed. | PASS | 0.006 | — |
| 15 | SQL injection / unsafe query rejected | UPDATE merchants SET risk_tier = 'LOW' | HTTP 422 SQL_REJECTED with readable reason | HTTP 422: Only SELECT queries are allowed (received UPDATE). | PASS | 0.006 | — |
| 16 | Ambiguous question handling | 'How are we doing?' / 'Which bank is best?' / 45d vs 45d / March 2024 | Clarify when no metric; explicit assumptions for metric/date defaults; refuse unequal comparison; refuse out-of-window dates | a=needs_clarification; b assumptions=["Using payment success rate as the metric because 'performance' (success rate is the primary payments health metric).", 'No period given; using the full available data window (2025-09-01 to 2025-10-30).']; c=needs_clarification; d=needs_clarification | PASS | 0.122 | — |
| 17 | Cache hit and invalidation | 'Compare bank-level performance across periods' x2, then activate scenario, then again | 2nd run: all queries cached; activation clears cache and bumps generation; 3rd run: 0 hits | 1st: 0/3 hits 27.0 ms SQL; 2nd: 3/3 hits 0.1 ms; after activation: 0 hits | PASS | 0.211 | — |
| 18 | Performance with 100,000 transactions | 100k-row bank_decline DB; 5 representative questions (cold cache, end-to-end HTTP) | Batched generation; every analysis < 3 s end-to-end; root cause still identified | generation 3.6s; 'What is the overall success rate?' 427 ms; 'Show daily transaction trends' 137 ms; 'Compare payment success rates by bank' 153 ms; 'Compare the last 7 days with the previous 7 days' 65 ms; 'Why did payment success rate decline?' 294 ms | PASS | 4.675 | — |
<!-- PROGRESSIVE:END -->

## 3. Performance benchmarks

Measured on the development machine: Windows 11 Home, 8 GB RAM, Python 3.10.5, SQLite 3.37.2. The 30k and 100k datasets are generated with the `bank_decline` profile.
- **SQL-layer cases** time compile + validate + execute with the cache cleared before every run.
- **E2E cases** time the whole `run_analysis` call: planning, every query, reasoning, and the data-quality summary attached to every result.

<!-- BENCH:START -->
_Generated by `scripts/benchmark.py` on 2026-11-21 06:00 UTC — Windows 10, Python 3.10.5, AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD; median of 7 runs (E2E: median of 3)._

Dataset generation (batched inserts, incl. indexes and canonical snapshot): **30k rows 1.0 s (13.6 MB)**, **100k rows 3.29 s (45.7 MB)**.

| Benchmark | 30k median (ms) | 30k min–max | 100k median (ms) | 100k min–max |
|---|---|---|---|---|
| Overall success rate (full window) | 15.9 | 15.52–21.57 | 49.94 | 47.91–51.25 |
| Daily transaction aggregation (60 days) | 28.96 | 27.74–43.01 | 102.06 | 98.75–103.18 |
| Bank-level breakdown | 48.01 | 41.07–186.91 | 125.96 | 125.55–127.82 |
| Previous-period comparison (7d vs 7d) | 6.06 | 5.85–10.67 | 19.03 | 18.43–19.98 |
| Multi-dimensional (bank x payment method) | 55.53 | 54.71–63.95 | 181.53 | 179.68–183.87 |
| Period comparison by bank (segmented) | 10.29 | 10.09–15.5 | 39.43 | 38.54–39.68 |
| Repeated bank breakdown (cache hit) | 0.02 | 0.02–0.08 | 0.02 | 0.02–0.08 |
| E2E: 'What is the overall success rate?' (cold cache) | 116.05 | 113.87–116.09 | 371.13 | 365.96–379.68 |
| E2E: 'Compare payment success rates by bank' (cold cache) | 125.02 | 123.16–128.75 | 415.98 | 412.58–422.24 |
| E2E: 'Why did payment success rate decline?' (cold cache) | 137.69 | 136.16–162.9 | 470.25 | 467.9–475.83 |
| E2E: 'Why did payment success rate decline?' (warm cache) | 7.74 | 7.39–8.51 | 7.74 | 7.32–8.17 |
<!-- BENCH:END -->

### 3.1 Optimisation history (measured, medians)

Two inefficiencies were found by benchmarking and profiling, then fixed and re-measured. Columns (0)–(2) are three successive real benchmark runs.

| Benchmark | Rows | (0) Baseline ms | (1) + memoised validation, single-scan DQ ms | (2) + index-backed snapshot check ms | Overall speed-up |
|---|---|---|---|---|---|
| Repeated bank breakdown (cache hit) | 30k | 4.74 | 0.02 | 0.02 | 237.0× |
| Repeated bank breakdown (cache hit) | 100k | 4.63 | 0.04 | 0.02 | 231.5× |
| E2E: 'What is the overall success rate?' (cold cache) | 30k | 228.66 | 201.31 | 116.05 | 2.0× |
| E2E: 'What is the overall success rate?' (cold cache) | 100k | 692.75 | 736.3 | 371.13 | 1.9× |
| E2E: 'Compare payment success rates by bank' (cold cache) | 30k | 241.56 | 211.92 | 125.02 | 1.9× |
| E2E: 'Compare payment success rates by bank' (cold cache) | 100k | 732.44 | 833.94 | 415.98 | 1.8× |
| E2E: 'Why did payment success rate decline?' (cold cache) | 30k | 278.49 | 230.7 | 137.69 | 2.0× |
| E2E: 'Why did payment success rate decline?' (cold cache) | 100k | 820.58 | 912.95 | 470.25 | 1.7× |
| E2E: 'Why did payment success rate decline?' (warm cache) | 30k | 52.27 | 7.5 | 7.74 | 6.8× |
| E2E: 'Why did payment success rate decline?' (warm cache) | 100k | 52.06 | 10.81 | 7.74 | 6.7× |

What changed:
1. **Memoised SQL validation.** Before, every cache hit still re-parsed its SQL with SQLGlot (≈4.7 ms). `validate_sql` is a pure function, so its results are now memoised (LRU of 1,024 entries; copies are returned). Cache hits dropped from 4.7 ms to 0.02 ms.
2. **Single-scan data-quality profile.** Ten row-level checks now run in one pass over `transactions_canonical` instead of separate queries. This helped at 30k (229 → 201 ms) but **regressed at 100k (693 → 736 ms)**, so the work was profiled rather than assumed.
3. **Profiling at 100k** showed *Canonical snapshot consistency* took **313 ms**, because it evaluated the window-function view over every row. The view yields exactly one row per distinct `transaction_id`, so the check now compares against the index-backed `COUNT(DISTINCT transaction_id)`, which is exactly equivalent. Iteration 2 still compares against the view itself. Result: cold root-cause analysis at 100k went from 820 ms to 470 ms.

Memory: the backend never loads the transaction table into Pandas. Every aggregation runs in SQLite, and Pandas only handles daily series of at most 60 rows (rolling statistics for the anomaly rule). Data generation is vectorised with NumPy and inserted in batches of 5,000 rows.

## 4. Failures found during development, with cause, fix and retest

| # | Where | Symptom (actual) | Cause | Fix | Retest |
|---|---|---|---|---|---|
| F1 | Data generator | Scenario profiles had different baselines (7-day success rate 91.67 % in baseline vs 92.94 % in source_discrepancy) | Each profile used its own seed, so the RNG streams diverged | One shared RNG stream; profile-specific draws are made for every profile and applied conditionally | All profiles identical except the seeded effect (baseline prev/curr 91.09 / 91.78 in every profile). PASS |
| F2 | Scenario D design | Mix effect only −2.0 pp, too close to noise | Share shift too small | UPI 55 → 28 %, Net Banking 12 → 39 % | −3.17 pp, z = −4.4, mix 122 %. PASS (iteration 11) |
| F3 | Smoke test harness | `UnicodeEncodeError: 'charmap' codec can't encode '₹'` | Windows console cp1252 | Run Python with `PYTHONIOENCODING=utf-8` (environment, not app code) | PASS |
| F4 | Ranking narrative | "…ShopSphere has the highest… PowerGrid the **lowest** (99)" for a top-10 list | Breakdown sentence reused for top-N rankings | Ranking-specific summary ("ranked by highest … top 10 shown: …") | PASS (iteration 8) |
| F5 | Planner | "Why?" alone was routed to a root-cause analysis | `why` rule accepted a missing metric | Require change words or a rate metric, otherwise ask for clarification | PASS (unit test `Why?` → needs_clarification) |
| F6 | Dashboard charts | Zero-based success-rate bars (88–93 %) hid real bank differences | Wrong measure for zero-based bars | Chart failure rate (7–12 %) instead | Visual check + J2. PASS |
| F7 | E2E journey | Frontend unreachable at 127.0.0.1:5173 (HTTP 000) | Vite binds `localhost` (IPv6 ::1) | Journeys use `http://localhost:5173` | PASS |
| F8 | E2E J4/J5 | `Locator expected to be visible` | `get_by_text("Transaction mix shift").first` matched the hidden `<option>` in the scenario dropdown; `"FAIL"` matched "Failed…" case-insensitively | Specific locators (`"Verdict: Transaction mix shift"`, `exact=True`). Screenshots confirmed the app output was correct. | J4: strict-mode violation (2 matches), fixed with `.first`, then 8/8 PASS |
| F9 | DQ refactor | `SyntaxError` after a scripted edit (literal newlines, doubled commas) | Tooling error during refactor | Corrected the source; full suite re-run | 81/81 PASS |
| F10 | Performance | 100k cold E2E regressed 693 → 736 ms after the single-scan refactor | View evaluation in the consistency check (313 ms) | Index-backed equivalent check (section 3.1) | 371 ms. PASS |
| F11 | Auth: refresh error path | Dead refresh cookie not cleared on a 401 | FastAPI discards the injected `Response` when an exception propagates | Return an explicit `JSONResponse` with the cookie deletion (kept for the benign multi-tab race) | New assertion in `test_refresh_requires_csrf_header_and_cookie`. PASS |
| F12 | E2E J10 | `strict mode violation: get_by_label("Password") resolved to 2 elements` | The checklist's `aria-label="Password requirements"` also matched; J11/J12 failed as a knock-on | `get_by_label("Password", exact=True)` | 12/12 PASS |

No test was deleted or weakened to make it pass. F8 changed the *locators* only after screenshots showed the expected content was on screen.
