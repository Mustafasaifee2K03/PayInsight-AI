"""SQLite schema for the payments analytics database.

Design notes
------------
* ``transactions_raw`` is the landing table. It may contain duplicates and
  incomplete records exactly as received from upstream feeds.
* ``v_transactions_canonical`` is the *canonical view*. It documents the
  duplicate-resolution rule: for each ``transaction_id`` keep the version with
  the latest ``updated_at``; ties are broken by the highest ``row_id``
  (i.e. the most recently ingested row).
* ``transactions_canonical`` is a materialised, indexed snapshot of that view,
  refreshed every time the database is (re)seeded. The data is static between
  seeds, so the snapshot is always identical to the view (verified by tests);
  it exists purely so analytical queries do not pay for a window function on
  every request.
* All money is stored as INTEGER minor units (paise for INR, cents for USD).
"""

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE dataset_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE merchants (
    merchant_id       TEXT PRIMARY KEY,
    merchant_name     TEXT NOT NULL,
    merchant_category TEXT NOT NULL,
    region            TEXT NOT NULL,
    risk_tier         TEXT NOT NULL CHECK (risk_tier IN ('LOW','MEDIUM','HIGH')),
    merchant_status   TEXT NOT NULL CHECK (merchant_status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE banks (
    bank_id     TEXT PRIMARY KEY,
    bank_name   TEXT NOT NULL,
    bank_type   TEXT NOT NULL,
    region      TEXT NOT NULL,
    bank_status TEXT NOT NULL CHECK (bank_status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE payment_methods (
    payment_method_id  TEXT PRIMARY KEY,
    method_name        TEXT NOT NULL,
    method_category    TEXT NOT NULL,
    payment_instrument TEXT NOT NULL
);

CREATE TABLE settlements (
    settlement_id           TEXT PRIMARY KEY,
    merchant_id             TEXT NOT NULL REFERENCES merchants(merchant_id),
    bank_id                 TEXT NOT NULL REFERENCES banks(bank_id),
    settlement_date         TEXT NOT NULL,
    settlement_amount_minor INTEGER NOT NULL CHECK (settlement_amount_minor >= 0),
    settlement_status       TEXT NOT NULL CHECK (settlement_status IN ('SETTLED','PENDING'))
);

CREATE TABLE transactions_raw (
    row_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id        TEXT NOT NULL,
    merchant_id           TEXT REFERENCES merchants(merchant_id),
    bank_id               TEXT REFERENCES banks(bank_id),
    payment_method_id     TEXT REFERENCES payment_methods(payment_method_id),
    transaction_timestamp TEXT,
    amount_minor          INTEGER,
    currency              TEXT,
    status                TEXT,
    failure_code          TEXT,
    settlement_id         TEXT REFERENCES settlements(settlement_id),
    updated_at            TEXT
);

CREATE TABLE bank_daily_reports (
    report_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id             TEXT NOT NULL REFERENCES banks(bank_id),
    report_date         TEXT NOT NULL,
    reported_total      INTEGER NOT NULL,
    reported_successful INTEGER NOT NULL,
    reported_failed     INTEGER NOT NULL,
    source_name         TEXT NOT NULL,
    UNIQUE (bank_id, report_date)
);
"""

POST_LOAD_DDL = """
CREATE INDEX idx_raw_ts       ON transactions_raw(transaction_timestamp);
CREATE INDEX idx_raw_txn      ON transactions_raw(transaction_id);
CREATE INDEX idx_raw_merchant ON transactions_raw(merchant_id);
CREATE INDEX idx_raw_bank     ON transactions_raw(bank_id);
CREATE INDEX idx_raw_method   ON transactions_raw(payment_method_id);
CREATE INDEX idx_raw_status   ON transactions_raw(status);
CREATE INDEX idx_settle_merchant ON settlements(merchant_id);
CREATE INDEX idx_reports_date ON bank_daily_reports(report_date);

CREATE VIEW v_transactions_canonical AS
SELECT row_id, transaction_id, merchant_id, bank_id, payment_method_id,
       transaction_timestamp, amount_minor, currency, status, failure_code,
       settlement_id, updated_at, version_count
FROM (
    SELECT r.*,
           ROW_NUMBER() OVER (PARTITION BY r.transaction_id
                              ORDER BY r.updated_at DESC, r.row_id DESC) AS rn,
           COUNT(*)     OVER (PARTITION BY r.transaction_id)             AS version_count
    FROM transactions_raw r
)
WHERE rn = 1;

CREATE TABLE transactions_canonical AS SELECT * FROM v_transactions_canonical;

CREATE UNIQUE INDEX idx_can_txn ON transactions_canonical(transaction_id);
CREATE INDEX idx_can_ts       ON transactions_canonical(transaction_timestamp);
CREATE INDEX idx_can_merchant ON transactions_canonical(merchant_id);
CREATE INDEX idx_can_bank     ON transactions_canonical(bank_id);
CREATE INDEX idx_can_method   ON transactions_canonical(payment_method_id);
CREATE INDEX idx_can_status   ON transactions_canonical(status);
CREATE INDEX idx_can_ts_status ON transactions_canonical(transaction_timestamp, status);
"""

# Tables the analytical SQL layer is allowed to read.
ANALYTICS_TABLES = frozenset(
    {
        "transactions_canonical",
        "v_transactions_canonical",
        "transactions_raw",
        "merchants",
        "banks",
        "payment_methods",
        "settlements",
        "bank_daily_reports",
        "dataset_metadata",
    }
)

TABLE_DESCRIPTIONS = {
    "transactions_raw": "Landing table of payment attempts exactly as received (may contain duplicates and incomplete rows).",
    "transactions_canonical": "Deduplicated transactions (one row per transaction_id, latest updated_at wins). Used for all metrics.",
    "v_transactions_canonical": "View that defines the duplicate-resolution rule over transactions_raw.",
    "merchants": "Merchant master data: category, region, risk tier, status.",
    "banks": "Issuing / remitter bank master data.",
    "payment_methods": "Payment method catalogue (UPI, cards, net banking).",
    "settlements": "Daily merchant settlement batches (T+1) for successful INR transactions.",
    "bank_daily_reports": "Daily counts reported independently by each bank (second source for reconciliation).",
    "dataset_metadata": "Generation metadata: profile, seed, row counts, date window.",
}

RELATIONSHIPS = [
    ("transactions_raw.merchant_id", "merchants.merchant_id"),
    ("transactions_raw.bank_id", "banks.bank_id"),
    ("transactions_raw.payment_method_id", "payment_methods.payment_method_id"),
    ("transactions_raw.settlement_id", "settlements.settlement_id"),
    ("settlements.merchant_id", "merchants.merchant_id"),
    ("settlements.bank_id", "banks.bank_id"),
    ("bank_daily_reports.bank_id", "banks.bank_id"),
]
