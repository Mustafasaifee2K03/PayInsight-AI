# Test Plan

## Test layers

| Layer | Location | Tooling | Count | How to run |
|---|---|---|---|---|
| Progressive acceptance iterations 1–18 | `backend/tests/test_progressive.py` | pytest + FastAPI TestClient | 30 test cases (iteration 15 has 13) | `pytest tests` |
| Backend unit tests | `backend/tests/test_units.py` | pytest | 51 cases (planner ×35, validator ×12, decomposition, metrics, statistics) | `pytest tests` |
| Auth, sessions, RBAC admin | `backend/tests/test_auth.py` | pytest, one TestClient per simulated browser | 25 | `pytest tests` |
| Hardening regressions (10 iterations) | `backend/tests/test_hardening.py` | pytest, threads for races and load | 47 | `pytest tests` |
| Adversarial probes / scale | `backend/scripts/hardening_probe.py`, `hardening_scale.py` | TestClient, isolated temp data | 15 probes / volume + 32-worker load | `python scripts\hardening_probe.py` |
| Frontend unit tests | `frontend/src/lib/format.test.ts`, `src/services/api.test.ts` | Vitest | 8 | `npm test` |
| Frontend static checks | — | `tsc --noEmit` (strict), `vite build` | — | `npx tsc --noEmit -p .` |
| Browser journeys | `backend/tests/e2e/browser_journey.py` | Playwright → installed Microsoft Edge | 12 | app running, then `python tests\e2e\browser_journey.py` |
| Performance | `backend/scripts/benchmark.py` | perf_counter, medians | 11 benchmarks × 2 datasets | `python scripts\benchmark.py` |

`scripts\run_tests.ps1` runs pytest, tsc, Vitest and the build. Add `-E2E` and `-Benchmark` for the remaining layers.

### Isolation and independence

- `tests/conftest.py` sets `PAYINSIGHT_DATA_DIR` to a fresh temporary directory **before** importing the app. Tests generate their own databases and never touch the development data.
- Correctness checks compare the API's answer with an **independent** computation: direct SQL through a separate read-only connection, or a Python loop over raw rows. The app's own output is never used as its own oracle.
- The `record` fixture captures scenario, input, expected and actual output during the run. A session hook combines them with pytest's real outcome and duration, then writes `docs/generated/progressive_results.json` and the results table in `BENCHMARK_REPORT.md`. Results therefore cannot drift from what was actually executed.

## Authentication tests (`test_auth.py`)

| Area | What is asserted |
|---|---|
| Hashing and policy | 600k production default; salted PBKDF2 format; the policy rejects short, low-variety, common and email-derived passwords |
| Migration | A legacy `app.db` (old `sessions` table) upgrades to schema v1 in place, idempotently |
| Signup | 201 and role VIEWER; the refresh cookie is httpOnly, SameSite=Strict and path-scoped; the refresh token is never in JSON; the password and refresh token are stored only as hashes; duplicate email (case-insensitive) 409; weak password 422; invalid email 422; signup can be disabled |
| JWT | Claims and the 15-minute lifetime; tampered, `alg=none`, wrong-secret, wrong-audience, wrong-type, unknown-session and expired tokens all get 401; a validly signed token claiming ADMIN for a viewer session is still refused on admin endpoints |
| Refresh | Rotation issues a new cookie; a replay inside the grace window keeps the session; a replay after it revokes the session (`REFRESH_TOKEN_REUSED`); a missing CSRF header gets 403; a missing or unknown cookie gets 401 and a dead cookie is cleared |
| Sessions | Logout kills both access and refresh; logout works with only the cookie; the multi-device list has exactly one "current"; revoking another device works; another user's session cannot be revoked; sign out everywhere |
| Brute force | `attempts_remaining` counts 4→1, the 5th failure locks (429 + Retry-After), the correct password is refused while locked, admin unlock works; an unknown email is indistinguishable from a wrong password; the per-IP limiter works over HTTP |
| RBAC admin | Analyst and viewer get 403 and anonymous gets 401 on admin endpoints; a role change applies to an existing token; disabling kills sessions and blocks login; an admin cannot demote or disable themselves |
| Password change | Wrong current password 401, weak 422, same password 422; success keeps the current device and revokes the others; the old password stops working |
| Audit and headers | The expected event types are recorded, the filter works, no passwords appear in the log; security headers are present |

**Mutation check:** deliberately disabling the revocation check and the token-type check made 6 of these tests fail. Restoring the code made all 25 pass again.

## Progressive iterations

| # | Scenario | Key assertions |
|---|---|---|
| 1 | Health and startup | `/health` 200 with no internals exposed, local planner name; admin `/api/system/status` reports 30,000 canonical rows |
| 2 | DB initialisation | All tables and the view exist; seed counts (30,000/24/8/4/480 reports); 4 FKs on raw; `PRAGMA foreign_key_check` empty; view == snapshot; indexes present |
| 3 | Transaction count | App == `COUNT(*)` == `COUNT(DISTINCT transaction_id)` |
| 4 | Success rate | Numerator and denominator equal an independent Python loop; PENDING excluded |
| 5 | Daily trend filtering | "last 14 days" → 2025-10-17..10-30 (anchored to data end); each day equals direct SQL; no day outside the window |
| 6 | Payment-method breakdown | 4 methods match direct SQL; shares sum to 100 % |
| 7 | Bank breakdown (analyst) | 200, 8 banks, every rate equals direct SQL |
| 8 | Top failed merchants | Ranking intent; top-10 order identical to direct SQL |
| 9 | Period comparison | Equal 7-day periods; pp change and relative % both correct and separate |
| 10 | Failure codes | Per-code counts equal direct SQL; sum equals total failed |
| 11 | Mix decomposition | Hand example with a zero-volume segment exact; Scenario D: within + mix = direct (<1e-9), mix > 60 %, verdict mix_shift |
| 12 | Bank decline | Scenario B: verdict deterioration in Deccan Commercial Bank; BANK_TIMEOUT is the top failure increase; > 80 % of change attributed |
| 13 | DQ injection | Scenario E: every injected defect detected with the **exact** injected count; raw 30,300 vs canonical 30,000; warnings attached to analyses |
| 14 | Access control | Viewer bank/merchant → 403; admin endpoints → 403 for viewer and analyst; no token → 401; method breakdown allowed; dashboard omits banks |
| 15 | SQL safety | 12 unsafe statements → 422 with reasons; NL injection payload never reaches SQL; cross join cancelled with 408 under a 500 ms limit; authorizer blocks INSERT directly; tables intact |
| 16 | Ambiguity | No metric → clarification; defaults → explicit assumptions; unequal history → clarification; out-of-window → clarification |
| 17 | Cache | 2nd identical run: 100 % cache hits; activation clears the cache and bumps the generation; next run 0 hits |
| 18 | 100k performance | 100k-row database generated; 5 representative analyses each < 3 s end to end; root cause still identified |

## Browser journeys (Playwright)

| # | Journey |
|---|---|
| J1 | Login page shows demo accounts |
| J2 | Admin login, dashboard KPIs and charts render |
| J3 | Switch to Scenario B in the UI, ask "Why did payment success rate decline?", see Deccan, verdict and facts |
| J4 | Switch to Scenario D and see "Verdict: Transaction mix shift" |
| J5 | Switch to Scenario E; the data-quality page shows duplicates and FAIL |
| J6 | Switch to Scenario G; reconciliation shows Ganga Valley Bank CRITICAL |
| J7 | Viewer sees the restricted bank card; the bank question shows "Access denied — HTTP 403" |
| J8 | An ambiguous question shows "Clarification needed" |
| J9 | Reloading the page keeps the user signed in (refresh cookie), and no token is readable by page JavaScript |
| J10 | Sign up a new account; it is a VIEWER and its session appears in Account & Security as "This device" |
| J11 | Admin promotes that user to ANALYST in Users & Audit; the user's open session can immediately run a bank breakdown |
| J12 | Admin disables the user; the user's next action returns them to login with "Your session ended", and signing in is refused |

The browser run deletes the accounts it created (`@e2e.payinsight.test`) from the dev database at the end; audit rows are kept.

Screenshots are written to `backend/tests/e2e/screenshots/` (git-ignored). Failing steps also save `FAILED_<step>.png`.

## Pass criteria

Hardening tests are described iteration by iteration, with the mutation check, in [HARDENING_REPORT.md](HARDENING_REPORT.md).

All pytest, Vitest, tsc and build checks must be green, and all 12 browser journeys must pass. The results of the latest run, including failures found during development and their fixes, are in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).
