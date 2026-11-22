# PayInsight AI
### Enterprise AI-Powered Payments Business Analyst

PayInsight AI lets business users ask payments questions in plain English, such as *"Why did payment success rate decline?"*, and get **evidence-backed answers**. Each question becomes a validated analysis plan. The plan is compiled into safe SQL and executed against a relational payments database. The results are then decomposed into the drivers of the change. Every number on screen comes from a query that actually ran, and the app shows that query.

> **Local deterministic analysis engine — No external AI API.**
> There are no paid APIs, no LLM and no cloud services. The planner is a rule-based natural-language parser and all numerical reasoning is deterministic Python/SQL. It runs on an 8 GB Windows laptop.

## Quick start for evaluators (about 5 minutes)

**No API keys, accounts or paid services are needed.** You need **Python 3.10+**, **Node.js 18+** with npm, and **Git**. All data is synthetic and generated locally from a fixed seed, so you will see exactly the numbers quoted in these docs.

```bash
git clone <this-repository-url> PayInsight-AI
cd PayInsight-AI
```

| Step | Windows (PowerShell) | macOS / Linux / Git Bash |
|---|---|---|
| 1. Install and generate data (one time, about 2–4 min) | `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` | `bash scripts/setup.sh` |
| 2. Start the app | `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` | `bash scripts/start.sh` |
| 3. Run all automated checks | `powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1` | `bash scripts/run_tests.sh` |

Then open **http://localhost:5173** and sign in with `admin@payinsight.demo` / `PayInsight@2026`. Other demo accounts are [listed below](#demo-accounts).

**What you should see:**
- **Step 3:** `153 passed` (pytest), a clean typecheck, `8 passed` (Vitest), a successful build, and *All checks passed*.
- **Analytics Workspace, scenario A:** asking *"What is the overall success rate?"* returns **91.76 % (27,122 of 29,558 eligible attempts)**.
- **Scenario B** (header dropdown): asking *"Why did payment success rate decline?"* returns **−3.00 pp (91.09 % → 88.08 %)**, with **Deccan Commercial Bank** as the main contributor (−3.40 pp).

Each question depends on the active scenario. [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) lists the exact expected answer for every demo question, including what each one returns in the other scenarios.

<details><summary>Troubleshooting</summary>

- **`python` not found / wrong version:** on Windows use `py -3.10 -m venv backend\.venv`, then re-run setup.
- **Port 8000 or 5173 already in use:** stop the other process, or start the backend with another `--port` and update the proxy target in `frontend/vite.config.ts`.
- **"Cannot reach the PayInsight backend" in the UI:** the backend window is not running. Run step 2 again.
- **Numbers differ from the docs:** switch to the scenario named in the docs, or use *Demo Scenarios → Reset / reseed active scenario*. The data is regenerated from the fixed seed.
- **Account locked after 5 wrong passwords:** wait 15 minutes, or sign in as admin → *Users & Audit* → *Unlock*.
- **Optional browser journeys** (`run_tests.ps1 -E2E` / `run_tests.sh --e2e`): need `pip install -r backend/requirements-dev.txt`, Microsoft Edge installed, and the app running.
</details>

**Configuration is optional.** Setup copies [.env.example](.env.example) to `.env`, which is git-ignored. No secrets are committed. A JWT signing key is generated locally on first run into `data/.jwt_secret`, which is also git-ignored. For a real deployment, set `PAYINSIGHT_JWT_SECRET` and `PAYINSIGHT_REFRESH_COOKIE_SECURE=true`.

---

## The business problem

Payment teams regularly need answers to questions like these:

- Why did success rates fall?
- Which bank drove the fall?
- Is it a real deterioration, or just a change in transaction mix?

Today an analyst has to find the tables, write SQL, compare periods, build charts and write up an explanation, which takes hours. PayInsight AI automates that workflow and keeps every step inspectable:

```
question → interpretation → datasets → metric → analysis plan → SQL → validation → execution
        → segmentation → decomposition → charts → facts / hypotheses / recommendations → caveats
```

## Key features

| Area | What is implemented |
|---|---|
| **NL planner** | A deterministic parser that recognises metric, dimension, entity, date-range, comparison and ranking language, including synonyms, word numbers and named banks/merchants/methods. It outputs a Pydantic-validated `AnalysisPlan`. Defaults are always shown as explicit assumptions. If a question has no metric or intent, the planner asks for clarification instead of guessing. |
| **SQL engine** | Plans are compiled into parameterised SQLite `SELECT` statements. There are three defence layers: a SQLGlot AST validator (allowlists, SELECT-only, one statement, no comments, PRAGMA or ATTACH), a SQLite authorizer (SELECT/READ only), and a read-only connection (`mode=ro` + `query_only`). Queries also have a timeout and a row cap. |
| **Business reasoning** | Equal-length period comparison, with **pp change reported separately from relative %** and a two-proportion z-test. Segment contribution analysis. **Mix vs. within-segment decomposition** whose identity is verified to within 1e-9. A multi-dimension root-cause scan with a verdict (deterioration, mix shift, both, or no material change). Failure-code drill-down. Statistical anomaly and outlier rules, clearly labelled as heuristics. |
| **Explainability** | Nine panels: interpretation, datasets, metric definitions, plan JSON, date range and filters, every executed SQL statement with its bound parameters, execution metadata, data-quality warnings, and raw evidence. Facts, hypotheses and recommendations are shown in separate columns. |
| **Data quality** | 13 checks (duplicates, conflicting duplicates, missing or orphan keys, invalid status, amount or timestamp, missing attributes, currency) with counts, severity, impact and the treatment applied. Bank-reported counts are reconciled against transaction-derived counts. |
| **RBAC** | ADMIN, ANALYST and VIEWER roles, enforced in the backend: a viewer asking for a bank breakdown gets an HTTP 403 before any SQL is generated. Passwords use PBKDF2 hashing. Session tokens are random and stored only as hashes. |
| **Demo scenarios** | Seven one-click deterministic scenarios (A–G) that can be switched and reseeded from the UI. |
| **Reliability** | Indexed SQLite, batched seeding, an LRU+TTL result cache invalidated on reseed, memoised SQL validation, structured JSON logs, and a consistent error envelope. |
| **Authentication** | Signup and login, 15-minute JWT access tokens, rotating refresh tokens in an httpOnly cookie backed by a sessions table (reuse detection, revocation, sign out everywhere), account lockout, rate limiting, user administration and a security audit log. |
| **Testing** | 153 pytest tests (including 25 auth tests, 47 hardening regression tests and 18 progressive acceptance iterations whose results are written into the report automatically), 8 Vitest unit tests and 12 Playwright browser journeys. |

## Architecture

```mermaid
flowchart LR
  subgraph FE[React + TypeScript + Vite]
    UI[Login · Dashboard · Analytics Workspace<br/>Explainability · Data Quality · Scenarios]
  end
  subgraph BE[FastAPI backend]
    AUTH[Auth & RBAC<br/>JWT + DB sessions, PBKDF2]
    PL[Deterministic planner<br/>→ AnalysisPlan (Pydantic)]
    AN[Analysis orchestrator<br/>comparison · contribution · decomposition · anomalies]
    SC[SQL compiler<br/>allowlisted identifiers, bound params]
    VA[SQLGlot validator]
    EX[Executor<br/>authorizer · read-only · timeout · row cap · cache]
    DQ[Data quality & reconciliation]
    RC[Recommendations<br/>rule-based]
  end
  subgraph DB[SQLite]
    PAY[(payments_&lt;profile&gt;.db<br/>raw → canonical view/snapshot<br/>dimensions · settlements · bank reports)]
    APP[(app.db<br/>users · sessions · history)]
  end
  UI -- REST/JSON + Bearer token --> AUTH
  AUTH --> PL --> AN --> SC --> VA --> EX --> PAY
  AN --> RC
  AN --> DQ --> EX
  AUTH --> APP
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module responsibilities and request flow.

## Technology stack

- **Frontend:** React 18, TypeScript 5, Vite 5, Tailwind CSS 3, Recharts 2, Lucide icons. Components are hand-built with Tailwind; shadcn/ui was not needed.
- **Backend:** Python 3.10, FastAPI, Pydantic v2, SQLite 3.37, Pandas, NumPy, SQLGlot.
- **Testing:** Pytest + FastAPI TestClient, Vitest, Playwright (driving the locally installed Microsoft Edge, so no browser download is needed).
- All versions are pinned (`backend/requirements.txt`, `frontend/package.json`). The core app needs no Docker, Redis or cloud service.

## Database schema

| Table | Purpose |
|---|---|
| `transactions_raw` | The landing table exactly as received. It may contain duplicates and incomplete rows. FKs reference merchants, banks, payment_methods and settlements. |
| `v_transactions_canonical` | A **view** that defines the duplicate rule: one row per `transaction_id`, the latest `updated_at` wins, and ties go to the highest `row_id`. |
| `transactions_canonical` | An indexed snapshot of that view, rebuilt on every seed. All metrics read from it. |
| `merchants`, `banks`, `payment_methods` | Dimension tables (24 merchants, 8 banks, 4 methods). All names are fictional. |
| `settlements` | T+1 merchant settlement batches for successful INR transactions. |
| `bank_daily_reports` | Bank-reported daily totals, used as the second source for reconciliation. |

Money is stored as **integer minor units** (paise). The data uses a fixed window, **2025-09-01 → 2025-10-30**, with seed `20250901`. Full column-level detail is in [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Metric definitions

| Metric | Definition |
|---|---|
| Payment success rate | `SUCCESS / (SUCCESS + FAILED) × 100`. PENDING and invalid statuses are **excluded** from the denominator. |
| Payment failure rate | `FAILED / (SUCCESS + FAILED) × 100` |
| Total attempts | All canonical transactions in the window (every status) |
| TPV (INR) | `SUM(amount_minor)` for SUCCESS, `currency = 'INR'`, `amount_minor > 0`. Other currencies are never summed with INR. |
| Average transaction value | TPV / number of successful positive INR transactions |
| Period-over-period change | Absolute change in **percentage points** for rates, plus **relative %**, always as two separate numbers |

Every result exposes its numerator, denominator, formula, filters and time window. Date boundaries are `start 00:00:00` inclusive and `end + 1 day 00:00:00` exclusive. Relative phrases such as "last 7 days" are anchored to the **last day of data**, never the machine clock. See [docs/METRIC_DEFINITIONS.md](docs/METRIC_DEFINITIONS.md).

## SQL safety approach

1. **The compiler never interpolates user input.** Identifiers come from allowlists, and dates and filter IDs are bound parameters. Entity names are matched against the live catalogue, so the free text of a question never reaches the SQL.
2. **SQLGlot validator.** It enforces exactly one statement, and the root must be SELECT or a set operation. It rejects DDL/DML, PRAGMA, ATTACH, comments, schema-qualified names, non-allowlisted tables and dangerous functions. It adds or clamps the `LIMIT`.
3. **SQLite authorizer.** Only `SELECT`, `READ` and `FUNCTION` actions are allowed; `load_extension` and similar functions are denied.
4. **Read-only connection.** The database is opened with `mode=ro` and `PRAGMA query_only=ON`.
5. **Execution limits.** A progress-handler timeout (default 3 s) returns HTTP 408, and results are capped at 5,000 rows (500 in the sandbox).

The ADMIN-only **SQL safety sandbox** in the UI lets you try to break these layers yourself. Resource abuse is bounded as well: nesting depth, `printf` widths, table-valued functions, a 512 MB SQLite heap ceiling and a 10 KB cell cap. Details are in [docs/SECURITY.md](docs/SECURITY.md).

### Hardening

A 10-iteration adversarial pass found and fixed 16 defects: sandbox memory/crash vectors, refresh-token and lockout races, a reuse-detection bypass, stale RBAC on stored results, rate limiting behind proxies, information exposure on `/health`, silent planner misreadings and hot-path scans. Each has a regression test and was mutation-checked; before/after measurements and the scale-out design are in **[docs/HARDENING_REPORT.md](docs/HARDENING_REPORT.md)**.

## Data-quality checks

The 13 checks are: duplicate transaction IDs, conflicting-status duplicates, missing merchant/bank/method IDs, orphan dimension references, invalid statuses, invalid amounts, invalid or out-of-window timestamps, FAILED rows without a failure code, missing currency, non-INR transactions (informational), and canonical-snapshot consistency. Each check reports the number of affected records, severity, explanation, impact and the treatment applied. **No row is silently dropped**: rows with missing keys are kept in totals and grouped as `Unknown / unmapped`.

## Roles

| Role | Can do | Cannot do |
|---|---|---|
| **ADMIN** | All analytics and dimensions, the data-quality report, reconciliation, scenario activation and reseed, the SQL sandbox, user management (roles, enable/disable, unlock) and the audit log | Change their own role or disable themselves |
| **ANALYST** | All analysis dimensions, including bank and merchant drill-down; SQL validation | Admin operations: quality report, reconciliation, scenario switching, sandbox execution |
| **VIEWER** | Aggregate summaries by payment method, category, region, failure code and day | Bank or merchant drill-down (HTTP 403), admin pages. Root-cause scans automatically omit restricted dimensions and say so. |

New self-registered accounts start as **VIEWER**; an admin promotes them on the *Users & Audit* page, and the change applies on the user's next request without signing in again.

### Authentication

- **Sign up / sign in** on the login page (*Create account* tab), with a live password-policy checklist.
- **Access token:** a 15-minute JWT (HS256, pinned algorithm, issuer/audience checked) held in memory only.
- **Refresh token:** an httpOnly, SameSite=Strict cookie, rotated on every use; replaying an old one revokes the session. Reloading the page restores the session from the cookie.
- **Server-side sessions** in `app.db`: every request checks the session is still active, so logout, *sign out everywhere*, admin disable and password change take effect immediately.
- **Lockout** after 5 failed sign-ins (15 min), per-IP rate limiting, PBKDF2-SHA256 at 600k iterations, and an audit log of every auth event.

Full details, endpoints and the threat model are in [docs/SECURITY.md](docs/SECURITY.md#2-authentication-and-session-management). SSO, MFA and email-based password reset are out of scope.

## Setup and run (Windows)

Prerequisites: **Python 3.10+**, **Node.js 18+** (tested on 22.9) and npm. From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # venv + pip + seed all scenario DBs + npm install
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # opens backend (:8000) and frontend (:5173) windows
```

Then open **http://localhost:5173**. The API docs are at http://127.0.0.1:8000/docs.

<details><summary>Manual commands (any OS)</summary>

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip
.venv\Scripts\python scripts\seed.py                  # deterministic demo databases (~6 s)
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

cd ../frontend
npm install
npm run dev                                           # http://localhost:5173
```
macOS/Linux/Git Bash: `scripts/setup.sh` then `scripts/start.sh`.
</details>

To rebuild every scenario database from scratch, run `backend\.venv\Scripts\python backend\scripts\seed.py --reset`, or use **Demo Scenarios → Reset / reseed** in the UI.

## Demo accounts

| Email | Role | Password |
|---|---|---|
| `admin@payinsight.demo` | ADMIN | `PayInsight@2026` |
| `analyst@payinsight.demo` | ANALYST | `PayInsight@2026` |
| `viewer@payinsight.demo` | VIEWER | `PayInsight@2026` |

The shared demo password can be changed with `PAYINSIGHT_DEMO_PASSWORD` in `.env`. Stored hashes are refreshed automatically at startup.

## Example questions

- **Basic:** *How many transactions occurred?* · *What is the overall success rate?* · *What is our total transaction value?* · *Show daily transaction trends*
- **Intermediate:** *Compare payment success rates by bank* · *Which payment methods have the highest failure rates?* · *Which merchants have the highest failed transaction volumes?* · *What are the main failure codes?* · *Compare the last 7 days with the previous 7 days*
- **Advanced:** *Why did payment success rate decline?* · *Which banks contributed most to the decline?* · *Is the decline caused by payment-method mix?* · *Which merchants have unusual failure rates?* · *Compare bank-level performance across periods*
- **Filters and dates:** *Show daily success rate for Deccan Commercial Bank in October* · *UPI vs net banking success rate* · *success rate between 2025-10-01 and 2025-10-15*

## Demo scenarios

| | Scenario | What it demonstrates |
|---|---|---|
| A | Normal performance | Stable baseline. "Why did it decline?" correctly answers **no material change** (z ≈ 1.0). |
| B | Bank performance decline | Deccan Commercial Bank loses about 22 pp in the last 7 days. The root-cause scan attributes about −3.4 pp of a −3.0 pp drop to it, with BANK_TIMEOUT up from 13 to 142. |
| C | Payment method comparison | Segment-level method performance |
| D | Transaction mix shift | Method success rates are unchanged, but share moves from UPI to Net Banking. **Mix explains −3.88 pp of the −3.17 pp change.** |
| E | Data-quality failure | 300 duplicate versions, plus missing or orphan keys, invalid statuses, amounts and timestamps, each detected with its exact count |
| F | Access-control failure | A viewer's bank breakdown request is rejected with HTTP 403 |
| G | Source discrepancy | Ganga Valley Bank over-reports successes on 3 days (CRITICAL) and one Bharat Union Bank report is MISSING |

## Testing

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1             # pytest + tsc + vitest + vite build
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 -E2E        # + Playwright journeys (app must be running)
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 -Benchmark  # + 30k/100k performance benchmark
```

On macOS/Linux: `bash scripts/run_tests.sh [--e2e] [--benchmark]`. Adversarial probes and the scale test: `backend/scripts/hardening_probe.py` and `hardening_scale.py` (see [docs/HARDENING_REPORT.md](docs/HARDENING_REPORT.md#8-reproducing)). Continuous integration runs pytest, the typecheck, Vitest and the build on every push (`.github/workflows/ci.yml`).

Results from the latest run:
- **Backend:** 153/153 pytest tests pass: 51 unit, 25 authentication/session/RBAC, 47 hardening regressions ([docs/HARDENING_REPORT.md](docs/HARDENING_REPORT.md)), and 30 progressive cases covering 18 iterations, each checked against an independent SQL or Python computation; the iteration table is auto-written to [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md).
- **Frontend:** strict typecheck clean, 8/8 Vitest tests, production build succeeds.
- **Browser:** 12/12 Playwright journeys pass (login, dashboard, root cause, mix shift, data quality, reconciliation, viewer 403, clarification, session restore on reload, signup, admin role change applied live, admin disable ending an open session). The E2E run needs `pip install -r backend/requirements-dev.txt` and Microsoft Edge.

## Benchmark summary

Medians from `scripts/benchmark.py` on the development laptop (Windows 11, 8 GB RAM, Python 3.10). The full table is in [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md).

| Measurement | 30k rows | 100k rows |
|---|---|---|
| Dataset generation (batched) | 1.0 s | 3.3 s |
| Overall success rate (SQL) | 15.9 ms | 49.9 ms |
| Bank-level breakdown (SQL) | 48.0 ms | 126.0 ms |
| 7d vs 7d comparison (SQL) | 6.1 ms | 19.0 ms |
| Repeated query (cache hit) | 0.02 ms | 0.02 ms |
| End-to-end "Why did success rate decline?", cold cache | 138 ms | 470 ms |
| End-to-end "Why did success rate decline?", warm cache | 7.7 ms | 7.7 ms |

## Known limitations

- The planner is rule-based. It covers the documented question families and close paraphrases, not arbitrary language. Unrecognised questions get a clarification request rather than a guess.
- The anomaly and outlier detectors are simple statistical rules (trailing mean ± 3σ, binomial z-score), not predictive models. Weekly seasonality is not modelled, so the baseline occasionally flags a borderline day (|z| ≈ 3.1).
- Root-cause output shows *where* a change is concentrated, which is correlation. Hypotheses are labelled as such and are not proven causes.
- The data is synthetic, with a single region-level hierarchy (merchant region). The app is single-node SQLite with an in-process cache (the scale-out seams are described in the hardening report), and has no SSO/MFA.

The full list is in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Future improvements

- An **optional local LLM provider** (for example via Ollama) behind the planner interface to paraphrase questions into the same validated `AnalysisPlan`. The deterministic compiler, validator and reasoning would remain the source of truth.
- PostgreSQL/DuckDB backends, server-side pagination, and persisting the cache across restarts.
- Seasonality-aware anomaly baselines, plus confidence intervals on segment rates.
- SSO/OIDC, row-level security, and audit logging of every executed query.
- Scheduled monitoring, so analyses run on a cadence and send alerts on verdict changes.

## Repository layout

```
backend/   FastAPI app (app/api, core, database, schemas, services, utils), scripts/, tests/
frontend/  React + TS app (components, pages, services, lib, types)
docs/      architecture, data dictionary, metrics, security, test plan, benchmark report, hardening report, demo script, limitations
scripts/   setup / start / test helpers (PowerShell + bash)
.github/   CI workflow (pytest, typecheck, Vitest, build)
data/      generated SQLite databases (git-ignored; recreated by seed.py)
```

Demo walkthrough: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) · Build log: [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) · Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## License

[MIT](LICENSE) © 2026 Mustafa Saifee
