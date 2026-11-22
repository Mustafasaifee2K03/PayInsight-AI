# Hardening Report — 10 iterations of adversarial testing

This report covers a systematic attempt to break PayInsight AI. Each iteration tried to break one area, confirmed every flaw with a reproducible probe, fixed the cause, and added a regression test that fails without the fix. Every number below was measured on the development laptop (Windows 11, Python 3.10.5, SQLite 3.37.2, 8 GB RAM). Nothing is estimated.

**Outcome.** 16 confirmed defects in 10 areas were fixed. 6 of them were security-relevant, 3 were correctness issues and the rest affected availability or scale. The adversarial probe harness went from **10 flaws out of 15 probes** (plus an intermittent race and a server crash found on re-runs) to **0 flaws out of 15**.

| | Before | After |
|---|---|---|
| Backend tests | 106 | **153** (+47 hardening regressions) |
| Mutation check | — | **13 of 13** reverted fixes caught |
| Browser journeys | 12/12 | **12/12** |
| Frontend | Vitest 8/8 | Vitest 8/8, `tsc` clean, build OK |
| Server errors (5xx) under a 32-worker mixed load | 0 | 0 |
| p99 latency under that load | 5.8 s | **1.1 s** |

---

## 1. Method

```
for iteration in 1..10:
    probe   – targeted adversarial input against an isolated copy of the app (temp data dir)
    confirm – reproduce; record evidence (status codes, sizes, timings)
    fix     – change the root cause, not the symptom
    test    – add test_hNN_* regression test(s); full suite must stay green
    re-probe– the probe must now report OK; re-run racy probes several times
```

- **Probe harness:** `backend/scripts/hardening_probe.py` has 15 probes and prints `FLAW` or `OK` with evidence for each.
- **Scale harness:** `backend/scripts/hardening_scale.py` seeds `app.db` with 200,000 sessions and 500,000 audit rows, times the hot auth paths, then runs a 32-worker mixed load.
- **Regression tests:** `backend/tests/test_hardening.py` holds 47 tests. Each is named after the iteration that found its flaw.
- **Mutation check:** after all fixes, each fix was reverted in turn and its tests had to fail. See §4.

The iterations were driven by the problem statement's own requirements:
- SQL must be safe.
- RBAC must be enforced in the backend.
- Defaults must be shown as explicit assumptions, and the system must never guess silently.
- Authentication must be real.
- The system must run reliably on an 8 GB laptop.

---

## 2. Findings at a glance

| # | Area | Defect (as found) | Severity | Fix | Regression tests |
|---|---|---|---|---|---|
| 1a | SQL sandbox | 3,000-level nested parentheses crashed the parser (`RecursionError` → HTTP 500) | High (availability) | Nesting-depth pre-check (64) + `RecursionError` handler | `test_h01_sandbox_*`, `test_h01_depth_guard_*` |
| 1b | SQL sandbox | `printf('%.*c', 400000000, 'x')` allocated 400 MB in one call; a 1e9 width allocates 1 GB | High (availability) | `printf`/`format` need a literal format string with width/precision ≤ 1,000 | `test_h01_sandbox_*` |
| 1c | SQL sandbox | `group_concat` of a 19 KB literal over 30k rows allocated **570 MB**. There is no syntactic tell. | High (availability) | SQLite process-wide `PRAGMA hard_heap_limit` (512 MB) → `422 QUERY_RESOURCE_LIMIT` | `test_h01_heap_limit_*` |
| 1d | SQL sandbox | Table-valued functions (`pragma_table_info`, `json_each`) passed the validator and failed as HTTP 500 | Medium | Rejected by the validator (`422`). Authorizer denials map to `422` too. | `test_h01_sandbox_*` |
| 1e | SQL sandbox | A BLOB result cell (`x'00ff'`) crashed JSON encoding (HTTP 500); very long text cells were sent verbatim | Medium | BLOBs rendered as hex literals, cells capped at 10,000 characters | `test_h01_blob_*` |
| 2 | Refresh tokens | Concurrent refreshes with **one** token: up to **7 of 8 succeeded**, minting 7 live refresh tokens | High | Compare-and-swap rotation (`WHERE refresh_token_hash = ?`, rowcount must be 1) | `test_h02_*` |
| 3 | Refresh tokens | Reuse detection measured its 5 s grace window from `last_used_at`, which every API call updates. A stolen token replayed soon after any API call was treated as a benign race, not theft. | High | New `rotated_at` column (migration 2); grace is measured from rotation | `test_h03_*` |
| 4 | Lockout | 20 parallel wrong guesses: **all 20 were evaluated** (all 401) despite a 5-attempt policy | High | Atomic attempt reservation *before* the hash check (`UPDATE … RETURNING`) | `test_h04_*` (×2) |
| 5 | Change password | With a stolen access token, the current-password check was an **unlimited password oracle** | High | Shares the login attempt budget; exhausting it locks the account and revokes every session | `test_h05_*` |
| 6 | RBAC | An analyst demoted to VIEWER could still **re-open stored bank-level analyses** from history | High (data exposure) | Results record the dimensions they touched and are re-authorised on every read. Legacy results fail closed. | `test_h06_*` (×3) |
| 7a | Rate limiting | Limiter memory was unbounded: 50,000 one-off IPs left **50,001 keys** in memory forever | Medium | Periodic sweep + hard key cap; pluggable backend interface | `test_h07_limiter_*`, `test_h07_backend_*` |
| 7b | Rate limiting | Behind a proxy (including the Vite dev proxy) every user shared **one bucket and one audit IP** | Medium | `X-Forwarded-For` honoured only from configured trusted proxies, read right to left | `test_h07_client_ip_*` (×6) |
| 8a | Attack surface | Unauthenticated `/health` exposed the DB file name, data generation, transaction volume and cache stats | Low–Medium | Minimal public `/health`; admin-only `/api/system/status` | `test_h08_public_*` |
| 8b | Operability | Error bodies had no request ID, so a user's error couldn't be matched to a log line | Low | `request_id` in every error envelope and log line; a well-formed upstream `X-Request-ID` is propagated | `test_h08_errors_*` |
| 8c | Admin | Force sign-out of a nonexistent user returned 200, and the acting admin was not audited | Low | 404 + actor recorded in `SESSIONS_REVOKED` | `test_h08_force_*` |
| 9 | Planner correctness | "in 1999", "last 3 quarters", "last 2 years", "year to date", "same period last year" silently ran on the **full window** with the false assumption "No period given" | Medium (wrong answers) | Years and quarters parsed and clipped explicitly; unsupported time language → clarification; top-N and currency assumptions made explicit | `test_h09_*` (×12) |
| 10 | Scale | Full table scans on hot paths; write-lock starvation (p95 1.6 s, max 3.3 s for logins); cache stampede; audit log grew without bound | Medium | Indexes (migration 3), FIFO write gate, single-flight cache, throttled housekeeping with retention | `test_h10_*` (×6) |

---

## 3. Iteration details

### Iteration 1 — SQL sandbox resource abuse

The ADMIN SQL sandbox already had three defence layers: AST validation, a SQLite authorizer and a read-only connection. They block *writes*, but nothing bounded *resources*.

**Evidence (before):**

| Attack | Result |
|---|---|
| `SELECT ((((…3000…))))` | **500** INTERNAL_ERROR (`RecursionError` in SQLGlot) |
| `printf('%.*c', 400000000, 'x')` | **200** after allocating a 400,000,000-character string (1.6 s) |
| `group_concat('<19 KB literal>')` over 30k rows | **200**, `n = 570,029,999` characters allocated |
| `… , pragma_table_info('…')` | **500** QUERY_FAILED (authorizer denial mapped to 500) |
| `… , json_each('[1,2]')` | **500** QUERY_FAILED |
| `SELECT x'00ff'` | **500** (`UnicodeDecodeError` while encoding JSON) |

**Root cause:** the validator checked *what* a query touches, not *how much* it can allocate. On Python 3.10, `sqlite3.Connection.setlimit` does not exist, so `SQLITE_LIMIT_LENGTH` cannot be lowered per connection.

**Fix:**
1. A parenthesis-depth pre-check (64), with a `RecursionError` handler behind it as a second layer.
2. `printf`/`format` require a literal format string, and widths/precisions must be literals ≤ 1,000.
3. `exp.Table` nodes that are not plain identifiers (table-valued functions) are rejected.
4. **`PRAGMA hard_heap_limit`**: a process-wide ceiling on SQLite's heap (`PAYINSIGHT_SQLITE_HEAP_LIMIT_MB`, default 512). Over-allocation raises `MemoryError`, which is mapped to `422 QUERY_RESOURCE_LIMIT`. This catches the amplification attacks that have no syntactic signature.
5. Authorizer messages map to `422 SQL_REJECTED`.
6. Result cells are made JSON-safe: BLOB → `x'…'`, text capped at 10,000 characters.

**After:** all nine attacks get `422` (or `408` for the infinite recursive CTE), and the process remains healthy. Disabling the heap limit brings the 570 MB allocation straight back, so it is a real layer, not decoration. The 30k- and 100k-row database generation and all analyses run unchanged under the limit.

### Iteration 2 — Refresh-token rotation race

**Evidence:** eight concurrent `POST /api/auth/refresh` calls with the same cookie. On the first run 1 of 8 succeeded; on a re-run **7 of 8** succeeded. The race is intermittent, which is why the probe and the test repeat it.

**Root cause:** read-then-write. Every request read the session row, saw its hash as current, and rotated it.

**Fix:** the rotation `UPDATE` now carries `AND refresh_token_hash = :presented AND revoked_at IS NULL`. Only a request that changes exactly one row wins. Losers get `REFRESH_SUPERSEDED`, which the client already retries once.

**After:** exactly 1 winner in every run (3 probe runs, plus 3 repetitions inside the test).

### Iteration 3 — Reuse-detection bypass

**Evidence:** a token rotated 10 minutes earlier and replayed after an ordinary API call returned `REFRESH_SUPERSEDED` (benign) instead of `REFRESH_TOKEN_REUSED` (revoke the session).

**Root cause:** the grace window was computed from `last_used_at`, which `authenticate()` updates once a minute on normal requests.

**Fix:** migration 2 adds `auth_sessions.rotated_at`, set only by rotation. The grace window uses it. Legacy rows with `NULL` have no grace at all (fail closed).

**After:** the replay revokes the session, and the attacker's and the victim's access tokens both stop working.

### Iteration 4 — Lockout race

**Evidence:** 20 parallel wrong passwords against one account → 20 × 401, so **all 20 guesses were checked** against a 5-attempt policy.

**Root cause:** the lock check happened before a slow hash (600k PBKDF2 iterations, ~0.6 s). The failure counter was written afterwards, so every parallel request passed the "not locked" read.

**Fix:** *attempt reservation*. A single conditional statement claims a slot before hashing and is committed at once:

```sql
UPDATE users SET failed_logins = failed_logins + 1, …
 WHERE user_id = ? AND (locked_until IS NULL OR locked_until <= :now) AND failed_logins < :max
RETURNING failed_logins
```

No row returned means the account is locked (429). The attempt that takes the last slot sets the lock if it fails; a success resets the counter.

There is a liveness edge case. If a request dies after taking the last slot, the account could be stuck with no slots left and no expiry. That state is converted into a normal, expiring lock.

**After:** at most 5 guesses are ever evaluated: 4 × 401, then 1 locking 429, then 15 × 429. The correct password is refused while the account is locked.

### Iteration 5 — Change password as a password oracle

**Evidence:** with a valid access token (for example a stolen one), 15 wrong `current_password` guesses got 15 × 401, with no throttle and no lock.

**Fix:** the check uses the same attempt budget as login. When the budget runs out, the account is locked and **every session is revoked**, audited as `ACCOUNT_LOCKED` with `via: change-password`. The stolen token dies immediately.

### Iteration 6 — Stale authorisation on stored results

**Evidence:** an analyst ran a bank breakdown, was demoted to VIEWER, and could still `GET /api/analytics/result/{id}` (200) even though a live bank query now returned 403.

**Root cause:** RBAC was enforced when a question was *planned*, but history re-reads returned the stored JSON unchecked.

**Fix:**
1. `CompiledQuery` now carries the business dimensions it groups or filters by. The compiler fills this in, so it cannot drift from the SQL.
2. The analysis context accumulates them, and results store `access.dimensions`.
3. `authorize_stored_result()` re-checks them against the reader's *current* role on every read.
4. Results saved before this metadata existed fail closed: only roles with every dimension can open them.

**After:** 403 with `restricted_dimensions: ["bank"]`. A viewer's own root-cause scan, which already skips restricted dimensions, still re-opens normally.

### Iteration 7 — Rate limiting that scales

**Evidence (memory):** 50,000 single-use client IPs left 50,001 keys in the limiter's dictionary.

**Evidence (identity):** through the Vite proxy every request appeared to come from `127.0.0.1`. One busy user could rate-limit everyone, and the audit log recorded the proxy's address.

**Fix:**
- The limiter moved to `app/core/ratelimit.py` behind a `RateLimitBackend` protocol (`hit / reset / size`), with a registry (`register_backend`) and a setting (`PAYINSIGHT_RATE_LIMIT_BACKEND`).
- The in-memory backend sweeps idle keys every 1,000 calls and enforces a hard cap of 100,000 keys, evicting the least recently active.
- A side finding: `time.monotonic()` ticks only every ~15.6 ms on Windows, so it was replaced with `perf_counter()`.
- `resolve_client_ip()` honours `X-Forwarded-For` only when the direct peer is in `PAYINSIGHT_TRUSTED_PROXIES` (default loopback, which covers the Vite proxy). It walks the header right to left past trusted hops, so a client cannot spoof its address by sending the header itself. The Vite proxy now sends `xfwd`.

**After:**
- 72 residual keys after 50,000 one-off IPs.
- A hard cap of 500 holds exactly at 500 in the test.
- A forwarded client is keyed by its real address.
- An untrusted peer's spoofed header is ignored.

### Iteration 8 — Attack surface and operability

1. **Public `/health`** returned `{profile, path, canonical_rows, generation}` plus cache statistics to anonymous callers. Transaction volume is business-sensitive for a payments company. `/health` now returns only status, app name and planner. The detail moved to **`GET /api/system/status`** (ADMIN), which also reports the rate-limiter backend and key count.
2. **Request IDs:**
   - Every request gets an ID, held in a `ContextVar`.
   - The ID appears in the error envelope (`error.request_id`), in every JSON log line, and in the `X-Request-ID` header.
   - A well-formed upstream ID from a gateway is propagated, so one ID follows a request across tiers; malformed values are replaced.
   - The frontend shows it as "Reference: …" in error boxes.
3. **Force sign-out:**
   - An unknown user ID now returns 404.
   - The audit entry records which admin did it (`detail.by`).
   - Disabling an account records the actor as well.

### Iteration 9 — The planner must not guess silently

The problem statement requires that defaults are always shown as explicit assumptions. The fuzz run found the opposite for time language the parser didn't recognise.

| Question | Before | After |
|---|---|---|
| "success rate in 1999" | Full window, "No period given" | Clarification: *No data for 1999* |
| "success rate in 2025" | Full window, "No period given" | 2025 clipped to data window, *clipped* assumption shown |
| "success rate q3 2025" / "third quarter of 2025" | Full window, "No period given" | Q3 2025 → clipped to 2025-09-01…09-30 |
| "success rate q4" | Full window | Q4 2025, with "No year given; assumed 2025" |
| "success rate last 3 quarters" / "last 2 years" | Full window, "No period given" | Parsed (90 / 365-day units) and clipped, with the assumption shown |
| "success rate last 999999999 days" | Full window, "No period given" | Parsed, bounded, clipped, with the assumption shown |
| "year to date", "same period last year", "since monday" | Full window ("same period last year" was even read as "last year") | Clarification explaining what is supported |
| "top 100000000000000000000 merchants" | Silently top 10 | Top 100, with "Requested top 100,000,000,000,000,000,000; showing at most 100" |
| "top 0 banks" | Default limit | Clarification |
| "TPV in USD" | INR TPV, no caveat | Assumption: *INR only; non-INR excluded, never converted* |

The guard is intentionally generic: any year, quarter, fiscal, YTD, "since" or "same period" phrase left unparsed is a clarification, never a silent default. Numbers after "top"/"bottom" are excluded, so "top 2000 merchants" is not read as a year. All 30 existing progressive acceptance cases still pass unchanged.

### Iteration 10 — Behaviour at scale

**Query plans.** `EXPLAIN QUERY PLAN` on every hot `app.db` statement found:
- a full scan of `auth_sessions` in the expired-session purge that ran inside **every** login and signup;
- a full scan of `auth_audit_log` when filtering by event type.

Migration 3 adds `idx_auth_sessions_expires`, `idx_audit_type (event_type, event_id)` and a covering `idx_auth_sessions_active (user_id, revoked_at, expires_at)`.

**Housekeeping.** The purge now runs at most every 10 minutes per process (and at startup) instead of on every login. It also enforces **audit-log retention** (`PAYINSIGHT_AUDIT_RETENTION_DAYS`, default 365). Before this, the audit log grew forever.

**Write-lock starvation.** With 32 concurrent sign-ins, SQLite's busy handler (sleep-and-retry, no queue) let unlucky writers starve: p50 32 ms but p95 1.6 s and max 3.3 s.

`app_conn()` now uses a `GatedConnection`:
- Its write transactions take a **FIFO write gate**: a re-entrant ticket lock that wakes exactly one waiter.
- The gate is taken at the first DML and released on commit, rollback or close.
- Reads are never gated, since the database runs in WAL mode.
- The attempt-reset commit was moved so that a password hash never runs while the write lock is held.

**Cache stampede.** With a cold cache, identical analyses from many users ran the same SQL concurrently. The result cache is now **single-flight**: the first caller computes, and concurrent callers wait for its result. `coalesced` and `in_flight` counters were added to the stats.

**Measured at volume (200,000 sessions, 500,000 audit rows), sequential:**

| Path | Before p50 / p95 | After p50 / p95 |
|---|---|---|
| Login | 50.5 / 54.5 ms | **15.9 / 16.9 ms** |
| Audit log filtered by event type | 18.3 / 24.8 ms | **8.1 / 9.2 ms** |
| Admin users list | 123.7 / 126.1 ms | **22.9 / 24.5 ms** |

*(Test hashing cost of 20k iterations. Production uses 600k, which adds about 0.6 s of deliberate hashing per login.)*

**32-worker mixed load (640 requests: 60% analyses, 30% `/me`, 10% logins):**

| | Before | After |
|---|---|---|
| Throughput | 68.8 req/s | **91.6 req/s** |
| p50 | 58.5 ms | 364.8 ms |
| p95 | 2,330 ms | **1,005 ms** |
| p99 | 5,768 ms | **1,114 ms** |
| 5xx | 0 | 0 |

**Trade-off.** The p50 rise is the expected cost of fairness, not a slowdown. In a closed-loop test with 32 workers, mean latency is fixed by throughput (Little's law). Before the fix, a few requests jumped the queue and others starved; afterwards, latency converges on the mean.

An A/B comparison with the gate switched off (`PAYINSIGHT_APP_DB_WRITE_GATE=false`) was run twice per setting:

| 32 concurrent workers | Gate off | Gate on |
|---|---|---|
| Login wall time | 3.2–3.3 s | 1.5–1.7 s |
| Login p95 | 1.6 s | 0.18–0.2 s |
| Warm analyze wall time | 1.7–2.2 s | ~2.0 s |
| Warm analyze p95 | 1.4–1.6 s | 0.75 s |
| Warm analyze p50 | 150–240 ms | 585 ms |

The gate is on by default and can be switched off.

**GIL ceiling.** Warm analyses spend about 20 ms of Python CPU each. With 32 threads in one process they queue on the GIL, so beyond this point throughput comes from more processes, not from more threads (see §5).

---

## 4. Verification

**Final pipeline (`scripts\run_tests.ps1 -E2E`):**
- pytest **153 passed**: 51 unit, 25 auth, 30 progressive, 47 hardening.
- `tsc` clean, Vitest **8/8**, production build OK.
- Playwright **J1–J12 all PASS** against the live servers, after the real `data/app.db` was migrated to schema version 3.

**Mutation check.** Each fix was reverted in turn, the relevant tests were run, and the code was restored. The suite was green again (153/153) afterwards.

| Reverted fix | Caught by |
|---|---|
| Nesting-depth guard | `test_h01_depth_guard_and_recursion_handler_each_work_alone` |
| `RecursionError` handler | same test (guard disabled inside the test) |
| SQLite heap limit | `test_h01_heap_limit_contains_amplification` |
| Refresh compare-and-swap | `test_h02_*` |
| `rotated_at` grace window | `test_h03_*` |
| Attempt reservation | `test_h04_*` |
| Change-password budget | `test_h05_*` |
| Stored-result authorisation | `test_h06_demoted_*` |
| Limiter sweep | `test_h07_limiter_memory_is_bounded` |
| Trusted-proxy check | `test_h07_client_ip_resolution` (2 cases) |
| Minimal `/health` | `test_h08_public_*` |
| Unparsed-time guard | `test_h09_unsupported_*` |
| Single-flight cache | `test_h10_single_flight_*` |

The first mutation run **missed** the depth guard. With the guard removed, the `RecursionError` handler still produced a 422, so no test could tell the guard was gone. That is defence in depth working, but it meant one layer was untested on its own. A test now exercises each layer independently, and the re-run caught **13 of 13**.

**Changes to existing tests (disclosed rather than silently edited):**
- `test_auth.py::test_app_db_migration_from_legacy_schema` asserted schema version `== 1`. It now asserts *the latest migration*, since migrations 2 and 3 were added. It still checks the legacy upgrade path and idempotency.
- `test_progressive.py::test_iter01_health_and_startup` read the row count from public `/health`. It now asserts that `/health` exposes **no** internals and reads the row count from the admin `/api/system/status`.

**Bugs in my own harness, also disclosed:**
- The first reuse-bypass probe gave a false positive after the fix, because it didn't backdate the new `rotated_at` column. The probe was corrected, not the code.
- Two new tests failed when run in isolation because they did not request the app fixture. Every hardening test was then run alone to confirm isolation.

---

## 5. Designed to scale: extension points

The fixes were written so that growth means *configuration or a new adapter*, not rewrites. Today's deployment is a single process on one machine. Every component that holds state has a defined seam:

| Concern | Today (single node, zero cost) | Seam | Scale-out replacement |
|---|---|---|---|
| Rate limiting | `MemoryRateLimitBackend`: bounded sliding window | `RateLimitBackend` protocol + `register_backend()` + `PAYINSIGHT_RATE_LIMIT_BACKEND` | Shared store (for example a Redis sorted set per key, or a SQL table). One class implementing `hit / reset / size`; no call sites change. |
| Client identity behind proxies | `X-Forwarded-For` from loopback | `PAYINSIGHT_TRUSTED_PROXIES` (IPs/CIDRs) | Add the load balancer's subnet |
| Sessions, users, audit | SQLite `app.db` (WAL) + in-process FIFO write gate | Every access goes through `app_conn()`; schema via versioned `MIGRATIONS` | Server database (PostgreSQL) when several API hosts share state. The SQL is portable apart from `RETURNING`/`ON CONFLICT`, which PostgreSQL supports. |
| Token validation | Stateful: JWT + session-row lookup (indexed point query) | `auth.authenticate()` | Read replica or short-TTL session cache, keeping revocation latency bounded |
| Analytical result cache | In-process LRU + TTL, single-flight | `ResultCache` (`get / put / lead / done / clear / stats`), keyed by DB generation | Shared cache when several workers serve the same dataset; generation keys keep invalidation correct |
| Analytical queries | SQLite read-only snapshot per profile | `DatabaseManager.readonly()` + validated SQL | Columnar or warehouse engine behind the same compiler/validator. Queries are allowlisted, parameterised `SELECT`s. |
| Resource limits | 3 s timeout, 5,000-row cap, 512 MB SQLite heap, 10 KB cells | Settings | Tune per host; per-tenant quotas later |
| Retention | Sessions purged 30 days after expiry; audit 365 days | `housekeeping()` + settings | Move to a scheduled job when multiple workers exist |
| Correlation | `X-Request-ID` in, out, in error bodies and in logs | `request_id_var` (`ContextVar`) | Feed the same ID into a tracing system (OpenTelemetry) |
| Health | Public liveness `/health`; admin `/api/system/status` | Two endpoints | Load-balancer probe on `/health`; dashboards on status |

**Stages of growth:**
1. **One host, one process (today).** All defaults apply. Measured at 92 req/s for the mixed load above, with p99 about 1.1 s at 32 concurrent workers.
2. **One host, N worker processes** (`uvicorn --workers N`), to get past the GIL ceiling measured in iteration 10. SQLite WAL handles cross-process writes. The per-process limiter and cache need a shared backend to stay exact, which is one adapter each.
3. **Several hosts behind a load balancer.** Move `app.db` to a server database, register a shared rate-limit backend, and list the balancer in `PAYINSIGHT_TRUSTED_PROXIES`. Request IDs already propagate across tiers.

None of the stage-2 or stage-3 adapters ship here, because the project constraints exclude Redis, paid databases and cloud services. The interfaces they plug into do ship, and are tested.

---

## 6. Residual risks and trade-offs

- **Lockout as denial of service.** Anyone who knows an email can lock that account for 15 minutes. This is the usual trade-off against brute force. Admins can unlock it, and the per-IP rate limit slows mass locking. Tracking failures per (account, IP) pair would soften it.
- **The heap limit is process-wide.** It also bounds legitimate SQLite work. 512 MB is far above what the 100k-row analyses need, but it should be revisited if the datasets grow.
- **FIFO write gate.** It raises median latency under heavy concurrent writing in exchange for much lower tails and equal or better throughput. It only coordinates threads within one process.
- **Planner coverage.** Unsupported time language now produces a clarification instead of a wrong answer. That is safer but stricter; fiscal calendars and year-over-year comparisons remain unsupported.
- **Rate-limit and cache state** are per process until a shared backend is registered (§5).

---

## 7. New configuration

| Variable | Default | Purpose |
|---|---|---|
| `PAYINSIGHT_SQLITE_HEAP_LIMIT_MB` | `512` | SQLite hard heap ceiling (0 disables it) |
| `PAYINSIGHT_RATE_LIMIT_BACKEND` | `memory` | Rate-limit backend name (see `app/core/ratelimit.py`) |
| `PAYINSIGHT_TRUSTED_PROXIES` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-For` is trusted |
| `PAYINSIGHT_APP_DB_WRITE_GATE` | `true` | FIFO in-process writer queue for `app.db` |
| `PAYINSIGHT_AUDIT_RETENTION_DAYS` | `365` | Audit-log retention |
| `PAYINSIGHT_HOUSEKEEPING_INTERVAL_SECONDS` | `600` | Purge cadence per process |

**Schema:** migration 2 adds `auth_sessions.rotated_at`; migration 3 adds the indexes. Both are applied automatically and idempotently at startup.

## 8. Reproducing

From `backend/`:

```powershell
.venv\Scripts\python scripts\hardening_probe.py          # 15 adversarial probes (expect: 0 flaw(s) of 15)
.venv\Scripts\python scripts\hardening_scale.py          # volume + 32-worker load (SC_SESS / SC_AUDIT to resize)
.venv\Scripts\python -m pytest tests\test_hardening.py   # 47 regression tests
powershell -ExecutionPolicy Bypass -File ..\scripts\run_tests.ps1 -E2E   # everything, including browser journeys
```

Timings vary from run to run on a laptop. The before/after comparisons above were taken back to back on the same machine.
