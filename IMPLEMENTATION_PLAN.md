# Implementation Plan

This is the plan the build followed, annotated with its final status. The design rationale is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Guiding decisions

| Decision | Why |
|---|---|
| Deterministic rule-based planner instead of an LLM | Zero-cost and offline requirement. It is also reproducible and auditable, and it cannot hallucinate numbers. An LLM could later sit *in front of* the same validated `AnalysisPlan`. |
| SQLite, one file per scenario profile | No server process, which suits 8 GB RAM. Switching scenarios is a pointer swap, and reseeding is an atomic file replace. |
| Canonical view + materialised snapshot | The view documents the duplicate rule. The snapshot avoids running a window function on every query. Equality between them is tested. |
| Shared base aggregates for all metrics | Every number can expose its numerator and denominator, and metric definitions live in one place. |
| Three-layer SQL defence | The AST validator can have bugs, so the authorizer and read-only connection still stop writes. |
| RBAC on the plan, before SQL | Restricted data is never computed and then hidden. |
| Separate `app.db` | Analytical connections stay strictly read-only, and users and history survive reseeds. |
| Tests compare against independent SQL/Python | Prevents the app from validating itself. |

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository inspection (empty), toolchain check (Python 3.10.5, Node 22.9, SQLite 3.37.2), skeleton, pinned dependencies | ✅ |
| 2 | Schema, FKs, indexes, canonical view/snapshot; vectorised deterministic generator; 5 profiles; batched inserts | ✅ ~1 s per 30k rows |
| 3 | FastAPI app, config, error envelope, JSON logging, app store, auth | ✅ |
| 4 | Deterministic planner: normalisation, entities, time, metric, dimension, intent rules, explicit assumptions, clarification | ✅ |
| 5 | Compiler (allowlists, bound params), SQLGlot validator, executor (authorizer, timeout, row cap, cache) | ✅ |
| 6 | Metric engine; KPI/breakdown/trend/comparison/contribution/mix/diagnose/anomaly/outlier handlers; decomposition with identity check | ✅ |
| 7 | 13 data-quality checks, reconciliation, RBAC, scenarios A–G with reseed | ✅ |
| 8 | React UI: login, dashboard, workspace, explainability (9 panels), data quality & sources (+ SQL sandbox), scenarios, history, CSV export | ✅ |
| 9 | End-to-end smoke across all scenarios; Playwright journeys with the system Edge | ✅ 12/12 |
| 10 | Pytest: 51 unit + 30 progressive cases (iterations 1–18), auto-generated report | ✅ 81/81 |
| 11 | Benchmarks at 30k/100k; profiling-driven optimisations | ✅ cold root cause at 100k: 820 → 470 ms |
| 12 | Documentation, setup/start/test scripts, fresh-checkout reproduction | ✅ |
| 13 | Authentication upgrade: signup, JWT access tokens, rotating DB-backed refresh sessions with reuse detection, lockout, rate limiting, user admin, audit log, versioned app.db migrations | ✅ 25 new tests, J9–J12 |

## Explicitly out of scope

The following were deliberately left out to honour the project constraints (zero cost, offline, 8 GB laptop): Docker, Redis, Kafka, Elasticsearch, any LLM or Ollama install, ML models, cloud deployment, and production identity. These are listed as future work in the README.
