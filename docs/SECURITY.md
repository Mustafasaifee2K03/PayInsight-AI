# Security

> All controls below are implemented and covered by automated tests. *Out of scope* at the end lists what a regulated production deployment would still add.

## 1. SQL safety: three independent layers

Every SQL statement, whether compiled from a plan or typed into the admin sandbox, goes through the same path in `services/query_executor.py`:

| Layer | Implementation | What it stops |
|---|---|---|
| **1. AST validator** | `services/sql_validator.py` (SQLGlot, SQLite dialect) | Multiple statements (`;` outside string literals); comments (`--`, `/* */`); PRAGMA, ATTACH, DETACH, VACUUM, REINDEX, load_extension (keyword pre-check); any root other than SELECT/UNION/INTERSECT/EXCEPT; forbidden AST nodes anywhere (Insert, Update, Delete, Drop, Alter, Create, Command, Pragma, Transaction, Merge, Into, Set…); tables outside the allowlist (CTE names excluded); schema-qualified names (`main.banks`); dangerous functions (`load_extension`, `readfile`, `writefile`, `randomblob`, `zeroblob`…); missing or excessive `LIMIT` (wrapped in `SELECT * FROM (…) LIMIT n`) |
| **2. SQLite authorizer** | `conn.set_authorizer` allows only `SQLITE_SELECT`, `SQLITE_READ`, `SQLITE_FUNCTION`, `SQLITE_RECURSIVE`; also denies `load_extension`, `readfile` and similar | Any write, DDL, PRAGMA or ATTACH, even if layer 1 had a bug (tested directly in iteration 15) |
| **3. Read-only connection** | `sqlite3.connect("file:…?mode=ro", uri=True)` + `PRAGMA query_only = ON` | Writes at the storage-engine level |

**Execution limits:**
- **Timeout:** a progress handler checks a deadline every 2,000 VM steps and interrupts the query. The default is 3,000 ms (`PAYINSIGHT_QUERY_TIMEOUT_MS`); the response is HTTP 408 `QUERY_TIMEOUT`.
- **Row cap:** `fetchmany(limit + 1)` with truncation detection. The default is 5,000 rows, and 500 in the sandbox.
- **Structured errors:** `SQL_REJECTED` (422) returns readable reasons, `QUERY_TIMEOUT` (408), `QUERY_FAILED` (500).

**Allowlisted tables:** `transactions_canonical`, `v_transactions_canonical`, `transactions_raw`, `merchants`, `banks`, `payment_methods`, `settlements`, `bank_daily_reports`, `dataset_metadata`. The `app.db` tables (users, auth sessions, audit log) live in a **different file**, which analytical connections never open.

### Natural language never becomes SQL text

- The compiler builds SQL from allowlisted identifier templates (`DIMENSIONS`, `JOINS`, `BASE_AGGREGATES`).
- Dates and filter values are **bound parameters** (`:start_ts`, `:f0_0`…).
- Filter values are catalogue IDs (`B03`), never the user's text. Entities are recognised by matching the question against the live dimension catalogue, so `Deccan Commercial Bank' OR '1'='1` becomes the parameter `B03` and the payload is discarded. This is verified by test iteration 15.
- Questions containing write intents (*delete*, *drop*, *truncate*, *update the*…) are refused by the planner before any processing.

The frontend has no endpoint that executes arbitrary SQL except `/api/sql/execute`. That endpoint is ADMIN-only, and it uses exactly the same three layers.

## 2. Authentication and session management

Implemented in `app/core/security.py` (primitives), `app/services/auth.py` (logic) and `app/api/auth_routes.py` (HTTP). Covered by `backend/tests/test_auth.py` (25 tests) and browser journeys J9–J12.

### Token model

```
login / signup -> { access_token (JWT, 15 min), user }  + Set-Cookie: payinsight_refresh (httpOnly, SameSite=Strict, Path=/api/auth, 7 days)
API call       -> Authorization: Bearer <JWT>  -> verify signature + claims -> look up session (sid) -> load user and role from DB
JWT expired    -> POST /api/auth/refresh (cookie + X-Requested-With) -> refresh token ROTATED, new JWT
logout         -> session row revoked -> JWT and refresh token both stop working immediately
```

| Element | Implementation |
|---|---|
| **Access token** | HS256 JWT (PyJWT) with `iss`, `aud`, `sub`, `sid`, `role`, `typ=access`, `jti`, `iat`, `nbf`, `exp`. Lifetime 15 min (`PAYINSIGHT_ACCESS_TOKEN_TTL_MINUTES`). The algorithm is **pinned** on decode, so `alg=none` and algorithm-confusion tokens are rejected; `exp/iat/nbf/sub/sid/iss/aud` are required. |
| **Signing secret** | `PAYINSIGHT_JWT_SECRET` (at least 32 characters, checked at startup). If unset, a random 256-bit secret is generated once and persisted to `data/.jwt_secret` (git-ignored), so tokens survive restarts. |
| **Refresh token** | 384-bit random value, delivered only as an **httpOnly** cookie (never in a JSON body, never readable by JavaScript). Only its SHA-256 is stored, in `auth_sessions`. |
| **Rotation** | Every refresh issues a new refresh token and keeps the previous hash. **Reuse detection:** presenting an already-rotated token revokes the whole session (`REFRESH_TOKEN_REUSED`) and is audited. A 5-second grace window treats two tabs refreshing at the same moment as benign (`REFRESH_SUPERSEDED`; the client retries). |
| **Stateful validation** | A valid signature is not enough. Each request also checks that the session (`sid`) exists and is neither revoked nor expired, and that the account is active. The **role is read from the database**, not from the token, so revocation, deactivation and role changes apply on the next request. A forged but validly signed `role: ADMIN` claim gains nothing (tested). |
| **Browser storage** | The access token is held **in memory only** (not localStorage or sessionStorage). On reload, the app restores the session by calling `/api/auth/refresh` with the cookie. Journey J9 asserts no token is visible to page JavaScript. |
| **CSRF** | Only `/refresh` and `/logout` are authenticated by cookie. They require the `X-Requested-With: PayInsight` header, which forces a CORS preflight that foreign origins fail. The cookie is also `SameSite=Strict` and path-scoped to `/api/auth`. All other endpoints use the bearer header, which browsers never attach automatically. |
| **Cookie `Secure` flag** | Off by default because the dev servers are plain HTTP; set `PAYINSIGHT_REFRESH_COOKIE_SECURE=true` behind HTTPS. |

### Accounts and passwords

- **Signup** (`POST /api/auth/signup`) validates the email format and normalises case, so duplicates are rejected case-insensitively (`409 EMAIL_TAKEN`). It enforces the password policy. New accounts get **VIEWER**, the least-privileged role. Self-registration can be turned off with `PAYINSIGHT_ALLOW_SIGNUP=false`.
- **Password policy** (enforced by the backend; the UI shows a live checklist): 10–128 characters, at least 3 of lowercase/uppercase/digit/symbol, not a common password, and not containing the email name.
- **Hashing:** PBKDF2-HMAC-SHA256 at **600,000 iterations** (OWASP 2023 guidance) with a per-user 16-byte salt, stored as `pbkdf2_sha256$iter$salt$hash` and compared with `hmac.compare_digest`. Older hashes are **upgraded on the next successful login**. The cost is deliberate: a login takes about 0.6 s on the development laptop. The test suite lowers the iteration count for speed, and a test asserts the production default.
- **Change password** requires the current password, applies the policy, and **revokes every other session**.

### Brute-force and enumeration defences

- **Account lockout:** 5 consecutive failures lock the account for 15 minutes (`429 ACCOUNT_LOCKED` with `Retry-After`). The correct password is refused while the account is locked. Admins can unlock it from the Users page. Each attempt **reserves a slot atomically before the hash is checked**, so parallel guesses cannot exceed the budget. The current-password check in *change password* shares the same budget; exhausting it there also revokes every session.
- **Rate limiting:** a per-IP sliding window on login, signup and refresh (default 30 per minute, `429 RATE_LIMITED`). The backend is pluggable (`app/core/ratelimit.py`); the default in-memory backend has bounded memory and applies per server instance. The client IP is taken from `X-Forwarded-For` only when the direct peer is listed in `PAYINSIGHT_TRUSTED_PROXIES` (default loopback, which covers the Vite proxy).
- **No user enumeration on login:** an unknown email and a wrong password return the same code and message, and unknown emails still pay the hashing cost so the timing does not differ. Signup necessarily reports an existing email; this is the usual trade-off, and it is rate-limited.

### Session management

Refresh rotation is a compare-and-swap, so concurrent refreshes with one token have exactly one winner, and the reuse grace window is measured from `rotated_at`. Stored analyses are re-authorised against the reader's current role when opened from history. Public `/health` is minimal; operational detail is at the admin-only `/api/system/status`. Every error body carries a `request_id` that matches the log line. See [HARDENING_REPORT.md](HARDENING_REPORT.md).

Each sign-in is a row in `auth_sessions`: device user agent, IP, created, last used, expiry, rotation count and revocation reason. From *Account & Security*, users can list their sessions, revoke any other device, or **sign out everywhere**. Admins can disable an account, which revokes all of its sessions instantly, or force a user to sign out.

### Audit trail

`auth_audit_log` records SIGNUP, LOGIN (success, and failure with its reason), ACCOUNT_LOCKED, TOKEN_REFRESH, REFRESH_TOKEN_REUSE, LOGOUT, SESSION_REVOKED, SESSIONS_REVOKED, PASSWORD_CHANGE and USER_UPDATED (who changed which role), with time, user, IP and session. Passwords and tokens are never written to it (tested). Admins view and filter it on the *Users & Audit* page.

### Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/auth/signup`, `POST /api/auth/login` | none (rate-limited) | Create an account or sign in; returns a JWT and sets the refresh cookie |
| `POST /api/auth/refresh` | refresh cookie + CSRF header | Rotate the refresh token and issue a new JWT |
| `POST /api/auth/logout` | JWT or refresh cookie, + CSRF header | Revoke the current session |
| `POST /api/auth/logout-all` | JWT | Revoke all of the user's sessions |
| `GET /api/auth/me`, `GET /api/auth/sessions`, `DELETE /api/auth/sessions/{id}` | JWT | Profile; list and revoke own sessions |
| `POST /api/auth/change-password` | JWT | Change password and revoke other sessions |
| `GET /api/admin/users`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/revoke-sessions` | JWT + `users:manage` | Change role, enable/disable, unlock, force sign-out |
| `GET /api/admin/audit` | JWT + `audit:read` | Security audit log |

Admins cannot change their own role or disable themselves (`409 SELF_MODIFICATION`), and the last active admin cannot be demoted (`409 LAST_ADMIN`).

**Demo accounts:** `admin@`, `analyst@` and `viewer@payinsight.demo`, all with password `PayInsight@2026`. Override the password with `PAYINSIGHT_DEMO_PASSWORD`; the hashes are refreshed at startup if it changes.

### Schema migrations

`app.db` is migrated with versioned, idempotent steps tracked in `PRAGMA user_version` (`app/database/app_store.py`). Migration 1 adds the account-state columns, replaces the old opaque-token `sessions` table with `auth_sessions`, and creates `auth_audit_log`. A database from the earlier version is upgraded in place on startup (tested from a legacy schema).

## 3. Authorization (backend-enforced RBAC)

`core/security.py` defines `ROLE_PERMISSIONS` (endpoint capabilities) and `ROLE_DIMENSIONS` (analysis dimensions):

| Permission / dimension | ADMIN | ANALYST | VIEWER |
|---|---|---|---|
| analytics, dashboard, history | ✓ | ✓ | ✓ |
| bank, merchant dimensions and filters | ✓ | ✓ | ✗ (403) |
| payment_method, merchant_category, region, failure_code, day | ✓ | ✓ | ✓ |
| quality report, reconciliation | ✓ | ✗ | ✗ |
| scenario activation / reseed | ✓ | ✗ | ✗ |
| SQL validate | ✓ | ✓ | ✗ |
| SQL sandbox execute | ✓ | ✗ | ✗ |
| user management (roles, enable/disable, unlock), audit log | ✓ | ✗ | ✗ |
| own account: sessions, sign out everywhere, change password | ✓ | ✓ | ✓ |

The rules are enforced at these points:
- **Analytics:** `analysis.enforce_rbac(plan, user)` runs after planning and **before any SQL is compiled**. A restricted dimension gets HTTP 403 `ROLE_RESTRICTED_DIMENSION` with the restricted and allowed lists.
- **Root-cause scans:** dimensions the role cannot see are skipped, and the response says so in `restricted_notes`. Restricted data is never computed and then hidden.
- **Dashboard:** the bank chart is omitted server-side for viewers (`banks: null`, plus a `restricted` note).
- **History:** `/api/analytics/result/{id}` returns only the caller's own analyses, unless the caller is ADMIN.
- **Routes:** admin and account endpoints use a `require("permission")` dependency, so the check cannot be forgotten inside a handler.
- **Frontend:** hiding controls in the UI is for convenience only. Every rule is enforced in the backend and covered by test iteration 14 and `test_auth.py`.

## 4. Other controls

- **CORS:** restricted to the configured dev origins (credentials allowed only for them), methods GET/POST/PATCH/DELETE, and headers Authorization/Content-Type/X-Requested-With.
- **Security headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; auth responses are `Cache-Control: no-store`.
- **Input validation:** Pydantic models validate request bodies. Questions are capped at 500 characters and SQL at 20,000.
- **Error responses:** a consistent envelope. Unhandled exceptions return a generic message, and details go only to the structured log.
- **Logging:** JSON-lines records with a request id, path, status and latency for each request. Rejected SQL is logged with its reasons. Passwords and tokens are never logged.
- **Data:** all data is synthetic and fictional, with no PII. The databases are git-ignored and regenerated deterministically.
- **Dependencies:** versions are pinned, and there are no network calls at runtime. Google Fonts is the only external resource and the UI falls back to system fonts without it.

## 5. Out of scope (what production would add)

- SSO/OIDC and MFA; email verification and self-service password reset (both need an email service).
- TLS termination (the dev servers are HTTP; enable `PAYINSIGHT_REFRESH_COOKIE_SECURE` behind HTTPS), a secrets manager and key rotation for the JWT secret.
- A shared rate-limit store (the limiter is per process) and shipping the audit log to a SIEM.
- Row-level security inside a dimension. RBAC works at the level of whole dimensions.
- The SQL sandbox is meant for demonstrating the safety layers; in production it would usually be disabled or audited.
