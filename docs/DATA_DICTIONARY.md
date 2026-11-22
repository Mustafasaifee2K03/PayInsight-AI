# Data Dictionary

All data is **synthetic and fictional**. It contains no real customers, cardholders, merchants or bank data. It is generated deterministically by `backend/app/database/generator.py`.

| Parameter | Value |
|---|---|
| Window | 2025-09-01 to 2025-10-30 (60 days, fixed) |
| Rows per profile | 30,000 canonical transactions (the 100,000-row variant is used for performance tests) |
| Seed | `20250901` |
| Timestamps | IST, stored as naive `YYYY-MM-DD HH:MM:SS` text |
| Money | Integer minor units (paise for INR, cents for USD) |

## transactions_raw: landing table (may contain defects)

| Column | Type | Description |
|---|---|---|
| row_id | INTEGER PK AUTOINCREMENT | Ingestion order; tie-breaker for duplicates |
| transaction_id | TEXT NOT NULL (indexed, **not unique**) | Business key `TXN########`; duplicates possible |
| merchant_id | TEXT FK → merchants | May be NULL or an orphan in Scenario E |
| bank_id | TEXT FK → banks | Issuing / remitter bank |
| payment_method_id | TEXT FK → payment_methods | |
| transaction_timestamp | TEXT (indexed) | Attempt time (IST) |
| amount_minor | INTEGER | Lognormal by merchant category; minimum ₹10 |
| currency | TEXT | `INR` (about 99.7 %), `USD` (about 3 % of Travel merchant transactions) |
| status | TEXT (indexed) | `SUCCESS`, `FAILED`, `PENDING` (about 1.5 %); invalid values appear only in Scenario E |
| failure_code | TEXT | Set when FAILED (see codes below) |
| settlement_id | TEXT FK → settlements | Set for successful INR transactions |
| updated_at | TEXT | Last status update; used by the duplicate rule |

Indexes: `transaction_timestamp`, `transaction_id`, `merchant_id`, `bank_id`, `payment_method_id`, `status`.

## v_transactions_canonical (view) and transactions_canonical (snapshot)

The view applies the duplicate-resolution rule with `ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY updated_at DESC, row_id DESC) = 1`, and adds `version_count` (the number of raw versions). `transactions_canonical` is a materialised copy built at seed time, with a unique index on `transaction_id` and indexes matching the raw table plus `(transaction_timestamp, status)`. Equality with the view is verified by test iteration 2 and by a data-quality check.

## merchants (24 rows)

| Column | Description |
|---|---|
| merchant_id | `M001`–`M024` |
| merchant_name | Fictional names (e.g. *ShopSphere Online*, *LuxeDeals Flash Sales*) |
| merchant_category | E-commerce, Food Delivery, Travel, Electronics, Grocery, Utilities, Education, Healthcare |
| region | North, South, East, West (this is the `region` dimension) |
| risk_tier | LOW, MEDIUM, HIGH |
| merchant_status | ACTIVE, INACTIVE |

*LuxeDeals Flash Sales* (M017, HIGH risk) is a seeded statistical outlier with elevated RISK_DECLINED failures in every profile.

## banks (8 rows)

| bank_id | bank_name | bank_type | region |
|---|---|---|---|
| B01 | Aurora National Bank | PUBLIC | North |
| B02 | Bharat Union Bank | PUBLIC | West |
| B03 | Deccan Commercial Bank | PRIVATE | South |
| B04 | Eastern Coastal Bank | PRIVATE | East |
| B05 | Frontier Co-operative Bank | COOPERATIVE | West |
| B06 | Ganga Valley Bank | PUBLIC | East |
| B07 | Horizon Payments Bank | PAYMENTS_BANK | South |
| B08 | Indus Private Bank | PRIVATE | North |

All banks are fictional. `bank_status` is ACTIVE for every bank.

## payment_methods (4 rows)

| id | method_name | method_category | payment_instrument | Baseline share | Base success probability |
|---|---|---|---|---|---|
| PM01 | UPI | UPI | VPA | 55 % | 94.5 % |
| PM02 | Debit Card | CARD | DEBIT_CARD | 17 % | 90.5 % |
| PM03 | Credit Card | CARD | CREDIT_CARD | 16 % | 92.5 % |
| PM04 | Net Banking | NETBANKING | BANK_ACCOUNT | 12 % | 80.0 % |

The realised success probability equals the method base plus a bank adjustment plus a merchant adjustment.

## settlements

| Column | Description |
|---|---|
| settlement_id | `S<merchant_id><yyyymmdd>`: one batch per merchant per settlement day |
| merchant_id / bank_id | Merchant and its settlement bank |
| settlement_date | Transaction day + 1 (T+1) |
| settlement_amount_minor | Sum of successful INR transaction amounts |
| settlement_status | SETTLED, or PENDING when the date is beyond the data window |

## bank_daily_reports (second source)

There is one row per bank per day (`UNIQUE(bank_id, report_date)`), with columns `reported_total`, `reported_successful`, `reported_failed` and `source_name` (`<bank>_DAILY_MIS`). Normally these equal the counts derived from transactions. In Scenario G:
- **B06** reports +8 % successes and −45 % failures on 2025-10-25, 10-26 and 10-27.
- **B02** has no report for 2025-10-20.

## Failure codes

`INSUFFICIENT_FUNDS`, `INCORRECT_PIN_OTP`, `BANK_TIMEOUT`, `ISSUER_DECLINED`, `RISK_DECLINED`, `NETWORK_ERROR`, `LIMIT_EXCEEDED`. Each method has its own weights. `NOT_RECORDED` is a display label for FAILED rows missing a code.

## Time distribution

The hour-of-day profile peaks at 12:00–14:00 and 19:00–21:00 IST. Weekends carry +15 % volume and days 1–3 of each month +10 %. There is a mild upward trend of +0.2 % per day plus ±4 % daily noise.

## Scenario profiles

| Profile | Scenarios | Seeded effect (all other data identical to baseline) |
|---|---|---|
| baseline | A, C, F | none |
| bank_decline | B | B03 success probability −22 pp for the last 7 days; 70 % of its failures re-coded to BANK_TIMEOUT |
| mix_shift | D | Last 7 days method shares become UPI 28 % / Debit 17 % / Credit 16 % / Net Banking 39 %; per-method probabilities are unchanged |
| data_quality | E | 300 duplicate versions (⅓ exact re-deliveries, ⅔ stale PENDING versions), 120 missing merchant, 80 missing bank, 40 missing method, 30 orphan merchant `M999`, 15 `UNKNOWN` status, 20 zero or negative amounts, 10 NULL or unparseable timestamps, 25 FAILED without a code |
| source_discrepancy | G | Bank-report discrepancies described above |

## app.db (application state, separate file)

| Table | Contents |
|---|---|
| `users` | email (unique, lower-case), name, role, `pbkdf2_sha256$600000$salt$hash`, is_active, created_at, last_login_at, failed_logins, locked_until, password_changed_at |
| `auth_sessions` | session_id (the JWT `sid`), user, SHA-256 of the current and previous refresh token, rotation_count, created/last_used/expires, revoked_at + reason, user agent, IP |
| `auth_audit_log` | time, event type, SUCCESS/FAILURE, user, email, session, IP, JSON detail |
| `analysis_history` | Full result JSON per analysis (most recent 200 per user) |
| `settings` | Active scenario, demo-password fingerprint |

`app.db` schema changes are versioned migrations tracked in `PRAGMA user_version`.
