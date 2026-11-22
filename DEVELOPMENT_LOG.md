# Development Log

This is a chronological record of the build. Every measurement here was observed in the session it describes. Failures F1–F10 are cross-referenced in [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md#4-failures-found-during-development-with-cause-fix-and-retest).

## Session 1 — 2026-11-21

### Phase 1: inspection and setup
- The repository was empty. Toolchain: Python 3.10.5, Node 22.9.0, npm 10.9.0, git 2.40, Windows 11 (8 GB RAM).
- Created the backend venv and installed pinned dependencies: fastapi 0.115.6, pydantic 2.10.4, pandas 2.2.3, numpy 1.26.4, sqlglot 26.0.1, pytest 8.3.4. The bundled SQLite is 3.37.2, which supports window functions.

### Phase 2: schema and data
- Wrote the DDL with FKs and indexes, the canonical view (latest `updated_at`, then highest `row_id`), and a materialised snapshot.
- Built a vectorised generator with fictional merchants and banks, weekday/hour seasonality, lognormal amounts by category, and ~3 % USD on travel merchants.
- First smoke run: all five profiles generated in about 1 s each, with 0 FK violations.
- **F1:** the profiles' baselines differed because each used its own seed. Fixed by moving to one RNG stream.
- **F2:** the mix shift (−2.0 pp) was too weak and was strengthened. Re-check: baseline 91.09 → 91.78, bank_decline 91.09 → 88.08, mix_shift 91.09 → 87.92.

### Phases 3–6: backend
- Built config, the error envelope, JSON logging, `app.db`, and PBKDF2 auth with hashed session tokens.
- Built the planner, compiler, validator, executor and cache; the metric registry; the analysis handlers; and decomposition, z-test and anomaly rules.
- The first end-to-end smoke test ran 22 questions × scenarios A, B, D and E through TestClient:
  - A: correctly "no material change" (+0.69 pp, z = 1.0).
  - B: Deccan −3.40 pp, 113 % of the change, BANK_TIMEOUT 13 → 142.
  - D: mix −3.88 pp out of −3.17 pp.
  - E: total attempts 29,990, because 10 invalid timestamps are excluded from time windows.
- **F3:** a console encoding error, fixed in the harness only.
- **F4:** a misleading "lowest" in ranking summaries; fixed.
- Quality, reconciliation and RBAC smoke tests: E detected every injected defect; G flagged 3 CRITICAL days and 1 MISSING report; viewer bank request returned 403; analyst quality and activate returned 403; no token returned 401. All 10 malicious SQL strings were rejected, and a cross join was cancelled at 3 s with HTTP 408.

### Phase 8: frontend
- Built Vite + React + TS + Tailwind + Recharts. The chart design follows a validated categorical palette, never uses dual axes (separate metric and volume panels), and adds hover tooltips and legends for multi-series charts.
- `tsc` strict was clean, Vitest 5/5, and the build succeeded. Recharts was split into its own chunk (538 kB) and the warning limit raised.

### Phase 9: browser verification
- Installed `playwright==1.49.1` (dev only) and drove the **installed Microsoft Edge**, so no browser download was needed.
- **F7:** Vite listens on IPv6 `localhost`; the journeys were switched to `localhost`.
- First run: 6/8. **F8:** two locator bugs. The screenshots proved the app was right: the root-cause page showed the correct verdict and Deccan details. After fixing the locators: 8/8.
- **F6** came from visually reviewing the dashboard screenshot: zero-based success-rate bars hid differences, so the charts now show failure rate.

### Phase 10: automated tests
- conftest isolates data in a temp directory, and the `record` fixture plus a session hook auto-writes the iteration table.
- First full run: **81 passed** (12.9–14.1 s). Iteration 18 generated 100k rows in 3.4 s; every analysis took under 1 s end to end.

### Phase 11: performance
- Baseline benchmark (7 repeats): a cache hit still cost 4.7 ms, and cold root cause took 278 ms at 30k and 821 ms at 100k.
- Memoised validation: cache hit 0.02 ms; warm root cause 52 → 7.5 ms.
- Single-scan data quality: faster at 30k but **slower at 100k (F10)**. Profiling showed the snapshot-consistency check evaluating the view took 313 ms. Replacing it with an index-backed equivalent brought cold root cause at 100k to **470 ms** (1.7×) and at 30k to **138 ms** (2.0×).
- **F9:** a scripted refactor left syntax errors. They were fixed and the suite re-run: 81/81.

### Phase 12: documentation and reproduction
- Wrote the README, the eight docs files, setup/start/test scripts (PowerShell + bash), `.env.example` and `.gitignore`.
- Fresh-checkout reproduction: copied the repo without ignored files into a scratch directory, ran `setup.ps1` (exit 0; 5 profiles seeded, 205 npm packages), then `run_tests.ps1` (81/81, tsc clean, 5/5 Vitest, build OK).
- README.md was found to contain the original build brief pasted into its third line during the session. With the user's confirmation, exactly that inserted block was removed.

## Decisions worth noting
- **Relative dates anchor to the last data day (2025-10-30)**, not today. This keeps the demo reproducible indefinitely.
- **The materiality rule** (|Δ| ≥ 0.3 pp and |z| ≥ 2) means the app says "did not materially decline" instead of inventing a root cause from noise.
- **Contribution can exceed 100 %** (Deccan, 113 %) when other segments move the other way. The app shows this rather than normalising it away.
- **The viewer root-cause scan** omits bank and merchant dimensions with a visible note, instead of returning a 403, because the user did not explicitly request a restricted dimension.

## Session 2 — 2026-11-21: authentication upgrade

Goal: replace the demo opaque-token login with proper authentication: signup, JWT, DB-backed session management and RBAC administration.

- **Design:** short-lived JWT access tokens (15 min, in memory in the browser) plus rotating refresh tokens in an httpOnly SameSite=Strict cookie, each bound to a row in a new `auth_sessions` table. Every request also checks the session and loads the role from the database, so revocation and role changes are immediate. Added `PyJWT==2.9.0` (the only new dependency; free, pure Python).
- **Migrations:** `app.db` now has versioned migrations (`PRAGMA user_version`). Migration 1 added account-state columns, `auth_sessions` and `auth_audit_log`, and dropped the old `sessions` table. The existing dev database upgraded in place on restart, and the demo hashes were re-hashed at 600k iterations.
- **Features:** signup (new users are VIEWER), password policy, lockout after 5 failures, per-IP rate limit, refresh-token reuse detection, session list/revoke, sign out everywhere, change password (revokes other sessions), admin user management (role, enable/disable, unlock, force sign-out) with self-lockout guards, and an audit log. The frontend gained a Create account tab, an Account & Security page and a Users & Audit page.
- **Tests:** `test_auth.py`, 25 tests, all passed on the first run. Because a first-run pass can mean weak tests, a **mutation check** was run: disabling the session-revocation check and the token-type check made 6 tests fail; restoring the code brought them back to 25/25.
- **F11:** the refresh endpoint tried to clear a dead cookie inside an `except … raise` block. FastAPI discards the injected `Response` when an exception propagates, so the cookie was never cleared. Fixed by returning an explicit `JSONResponse` with the deletion, except for the benign multi-tab race. Covered by a new assertion.
- **F12:** E2E J10 failed with a strict-mode violation. `get_by_label("Password")` also matched the checklist's `aria-label="Password requirements"`. J11 and J12 failed as a knock-on effect. Fixed with `exact=True`; then 12/12 passed.
- **Housekeeping:** `data/.jwt_secret` and SQLite WAL files were added to `.gitignore`; the browser run deletes the accounts it creates; audit rows now show the email for every user-linked event.
- **Measured:** login is about 0.6 s through the Vite proxy (600k PBKDF2 iterations, intentional). The pytest suite takes about 31 s (106 tests).
- **Final run** (`run_tests.ps1 -E2E`): pytest 106/106, tsc clean, Vitest 8/8, build OK, Playwright 12/12.

## Session 3 — 2026-11-21: 10-iteration hardening pass

Goal: test the system adversarially against the problem statement, fixing every confirmed flaw with a regression test, in a way that extends to scale. Full write-up: [docs/HARDENING_REPORT.md](docs/HARDENING_REPORT.md).

- **Method:** a 15-probe adversarial harness (`scripts/hardening_probe.py`), run in an isolated data directory, started at 10 flaws out of 15. Re-runs also exposed an intermittent refresh race (up to 7 of 8 concurrent refreshes succeeded) and a parser crash.
- **Fixes, one iteration each:**
  1. SQL sandbox resource limits (depth guard, `printf` widths, table-valued functions, SQLite `hard_heap_limit`, JSON-safe cells).
  2. Refresh compare-and-swap.
  3. `rotated_at` for reuse detection (migration 2).
  4. Atomic attempt reservation for lockout.
  5. Change-password attempt budget.
  6. Re-authorisation of stored results.
  7. Bounded, pluggable rate limiter with trusted-proxy client IP.
  8. Minimal `/health`, admin `/api/system/status`, request IDs, force sign-out 404 and actor audit.
  9. Planner years/quarters plus clarification for unsupported time language.
  10. Indexes (migration 3), throttled housekeeping with audit retention, single-flight cache, FIFO write gate.
- **Measured (scale harness, 200k sessions / 500k audit rows):** login p50 50.5 → 15.9 ms; 32-worker mixed-load p99 5.8 s → 1.1 s; throughput 69 → 92 req/s; no 5xx. The write gate raises the median under heavy concurrent writes in exchange for 2–3× lower tails. This was A/B-tested and is configurable.
- **Honesty notes:** two existing tests were changed: the migration version assert, and progressive iteration 1, which now checks that `/health` hides internals. Two harness mistakes were found and fixed: a stale probe simulation, and tests missing an app fixture. The first mutation run missed one fix because a second layer masked it, so a per-layer test was added. Final mutation run: 13/13 caught.
- **Final run** (`run_tests.ps1 -E2E`): pytest 153/153, tsc clean, Vitest 8/8, build OK, Playwright 12/12.
