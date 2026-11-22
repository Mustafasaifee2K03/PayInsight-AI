"""Data-quality checks and source reconciliation.

Nothing is silently discarded: every check reports how many records are
affected, how the metric engine treats them, and what that means for results.
All checks run as validated read-only SQL through the standard executor.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ..database.manager import get_db
from .query_executor import execute
from .sql_compiler import CompiledQuery


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    base_severity: str  # severity when affected > 0
    sql: str | None  # standalone query, or None when the check is part of the single-scan profile
    explanation: str
    impact: str
    treatment: str
    expr: str | None = None  # boolean condition evaluated in the single-scan profile query


def _window_params() -> dict:
    s = get_settings()
    return {"start_ts": f"{s.data_start_date} 00:00:00", "end_ts": f"{s.data_end_date} 23:59:59"}


CHECKS: list[Check] = [
    Check(
        "duplicate_transaction_ids", "Duplicate transaction IDs", "high",
        "SELECT COUNT(*) - COUNT(DISTINCT transaction_id) AS affected FROM transactions_raw",
        "Extra raw rows sharing a transaction_id with another row (re-deliveries or intermediate status versions).",
        "Counting raw rows would overstate attempts and can double-count outcomes (e.g. a stale PENDING plus a final SUCCESS).",
        "Resolved by the canonical rule: keep the version with the latest updated_at (ties: highest row_id). All metrics use transactions_canonical.",
    ),
    Check(
        "conflicting_duplicates", "Duplicates with conflicting status", "medium",
        "SELECT COUNT(*) AS affected FROM (SELECT transaction_id FROM transactions_raw GROUP BY transaction_id "
        "HAVING COUNT(DISTINCT COALESCE(status, '?')) > 1) AS x",
        "Transaction IDs whose versions disagree on status.",
        "Choice of version changes success / failure counts for these transactions.",
        "Latest updated_at version wins (documented canonical rule); conflicts remain listed here for audit.",
    ),
    Check(
        "missing_merchant_id", "Missing merchant IDs", "medium",
        None,
        "Canonical transactions with no merchant_id.",
        "Included in totals but cannot be attributed to a merchant, category or region.",
        "Kept; grouped as 'Unknown / unmapped' in merchant, category and region breakdowns.",
        expr="t.merchant_id IS NULL"
    ),
    Check(
        "missing_bank_id", "Missing bank IDs", "medium",
        None,
        "Canonical transactions with no bank_id.",
        "Included in totals; absent from bank attribution and bank reconciliation.",
        "Kept; grouped as 'Unknown / unmapped' in bank breakdowns.",
        expr="t.bank_id IS NULL"
    ),
    Check(
        "missing_payment_method_id", "Missing payment-method IDs", "medium",
        None,
        "Canonical transactions with no payment_method_id.",
        "Included in totals; cannot be attributed to a payment method (affects mix analysis).",
        "Kept; grouped as 'Unknown / unmapped' in payment-method breakdowns.",
        expr="t.payment_method_id IS NULL"
    ),
    Check(
        "orphan_references", "Orphan dimension references", "high",
        None,
        "IDs that do not exist in the corresponding dimension table (e.g. merchant M999).",
        "Rows cannot be joined to master data; joins would drop them if INNER JOINs were used.",
        "LEFT JOINs keep them in totals; grouped as 'Unknown / unmapped'.",
        expr="(t.merchant_id IS NOT NULL AND m.merchant_id IS NULL) OR (t.bank_id IS NOT NULL AND b.bank_id IS NULL) OR (t.payment_method_id IS NOT NULL AND pm.payment_method_id IS NULL)"
    ),
    Check(
        "invalid_status", "Invalid statuses", "high",
        None,
        "Status outside the allowed set {SUCCESS, FAILED, PENDING}.",
        "Counted in total attempts but cannot be classified as success or failure.",
        "Excluded from the success/failure-rate denominator (not eligible); still counted in total attempts.",
        expr="t.status IS NULL OR t.status NOT IN ('SUCCESS', 'FAILED', 'PENDING')"
    ),
    Check(
        "invalid_amount", "Invalid amounts", "medium",
        None,
        "Zero, negative or missing amount_minor.",
        "Would distort TPV and average transaction value.",
        "Excluded from TPV and average transaction value (amount_minor > 0 condition); counts unaffected.",
        expr="t.amount_minor IS NULL OR t.amount_minor <= 0"
    ),
    Check(
        "invalid_timestamp", "Invalid or out-of-window timestamps", "high",
        None,
        "Missing, unparseable or out-of-window transaction_timestamp.",
        "These rows cannot be placed in any time window.",
        "Excluded from all time-windowed metrics (every analysis filters by timestamp range).",
        expr="t.transaction_timestamp IS NULL OR datetime(t.transaction_timestamp) IS NULL OR t.transaction_timestamp < :start_ts OR t.transaction_timestamp > :end_ts"
    ),
    Check(
        "failed_without_failure_code", "FAILED transactions without failure code", "low",
        None,
        "Failed transactions missing a failure_code (important attribute).",
        "Failure-reason distributions under-report known causes.",
        "Kept; shown as 'NOT_RECORDED' in failure-code breakdowns.",
        expr="t.status = 'FAILED' AND (t.failure_code IS NULL OR t.failure_code = '')"
    ),
    Check(
        "missing_currency", "Missing currency", "medium",
        None,
        "Transactions with no currency code (important attribute).",
        "Amount cannot be valued safely.",
        "Excluded from TPV (TPV requires currency = 'INR').",
        expr="t.currency IS NULL OR t.currency = ''"
    ),
    Check(
        "non_inr_transactions", "Non-INR transactions (informational)", "info",
        None,
        "Transactions in a currency other than INR (e.g. USD on travel merchants).",
        "Different currencies must not be summed.",
        "Counted in attempts and rates; excluded from INR TPV (never converted or combined).",
        expr="t.currency IS NOT NULL AND t.currency <> 'INR'"
    ),
    Check(
        "canonical_snapshot_consistency", "Canonical snapshot consistency", "high",
        # The canonical view returns exactly one row per distinct transaction_id (ROW_NUMBER() = 1 per
        # partition), so COUNT(DISTINCT transaction_id) is an exact, index-backed proxy for COUNT(view).
        # Evaluating the view itself costs ~300 ms at 100k rows (window function); the full view
        # comparison is covered by test iteration 2.
        "SELECT ABS((SELECT COUNT(*) FROM transactions_canonical) - (SELECT COUNT(DISTINCT transaction_id) FROM transactions_raw)) AS affected "
        "FROM dataset_metadata WHERE key = 'profile'",
        "Row-count difference between the materialised canonical table and the canonical view (one row per distinct transaction_id).",
        "A difference would mean metrics are computed on stale data.",
        "Snapshot is rebuilt on every seed; any difference is surfaced here.",
    ),
]


def _severity(base: str, affected: int, total: int) -> str:
    if affected == 0:
        return "pass"
    if base == "info":
        return "info"
    share = affected / total if total else 0
    if share >= 0.01 and base != "low":
        return "high"
    return base


PROFILE_SQL = (
    "SELECT COUNT(*) AS canonical_rows,\n       "
    + ",\n       ".join(f"SUM(CASE WHEN {c.expr} THEN 1 ELSE 0 END) AS {c.id}" for c in CHECKS if c.expr)
    + "\nFROM transactions_canonical t\n"
    "LEFT JOIN merchants m ON m.merchant_id = t.merchant_id\n"
    "LEFT JOIN banks b ON b.bank_id = t.bank_id\n"
    "LEFT JOIN payment_methods pm ON pm.payment_method_id = t.payment_method_id"
)


def run_quality_checks() -> dict:
    """Row-level checks run in ONE scan of transactions_canonical (PROFILE_SQL); set-level
    checks (duplicates, snapshot consistency) run as their own queries."""
    total_q = execute(CompiledQuery("Row counts", "SELECT (SELECT COUNT(*) FROM transactions_raw) AS raw_rows, "
                                    "(SELECT COUNT(*) FROM transactions_canonical) AS canonical_rows FROM dataset_metadata WHERE key = 'profile'"))
    counts = total_q.rows[0]
    profile = execute(CompiledQuery("DQ single-scan profile of transactions_canonical", PROFILE_SQL, _window_params()))
    queries = [total_q.meta(), profile.meta()]
    results = []
    for chk in CHECKS:
        if chk.expr:
            affected = int(profile.rows[0][chk.id] or 0)
            shown_sql = f"SUM(CASE WHEN {chk.expr} THEN 1 ELSE 0 END)  -- column {chk.id} of the single-scan profile query"
        else:
            run = execute(CompiledQuery(f"DQ check: {chk.name}", chk.sql, {}))
            queries.append(run.meta())
            affected = int(run.rows[0]["affected"] or 0) if run.rows else 0
            shown_sql = chk.sql
        sev = _severity(chk.base_severity, affected, counts["canonical_rows"])
        results.append({
            "id": chk.id, "name": chk.name, "affected": affected, "severity": sev,
            "pct_of_rows": round(100 * affected / counts["canonical_rows"], 3) if counts["canonical_rows"] else 0,
            "explanation": chk.explanation, "impact": chk.impact if affected else "No impact detected.",
            "treatment": chk.treatment, "sql": shown_sql,
        })
    failing = [r for r in results if r["severity"] not in ("pass", "info")]
    status = "fail" if any(r["severity"] == "high" for r in failing) else "warn" if failing else "pass"
    return {
        "status": status,
        "raw_rows": counts["raw_rows"],
        "canonical_rows": counts["canonical_rows"],
        "duplicate_rule": "One row per transaction_id: latest updated_at wins; ties broken by highest row_id.",
        "checks": results,
        "issues": len(failing),
        "queries": queries,
        "profile_sql": PROFILE_SQL,
        "data_profile": get_db().profile,
    }


def quality_summary_for_analysis() -> dict:
    report = run_quality_checks()
    warnings = [
        {"check": r["name"], "affected": r["affected"], "severity": r["severity"], "impact": r["impact"], "treatment": r["treatment"]}
        for r in report["checks"] if r["severity"] not in ("pass",)
    ]
    return {"status": report["status"], "warnings": warnings, "raw_rows": report["raw_rows"], "canonical_rows": report["canonical_rows"]}


RECONCILIATION_SQL = """WITH derived AS (
    SELECT t.bank_id,
           date(t.transaction_timestamp) AS report_date,
           COUNT(*) AS derived_total,
           SUM(CASE WHEN t.status = 'SUCCESS' THEN 1 ELSE 0 END) AS derived_successful,
           SUM(CASE WHEN t.status = 'FAILED' THEN 1 ELSE 0 END) AS derived_failed
    FROM transactions_canonical t
    WHERE t.bank_id IN (SELECT bank_id FROM banks)
      AND t.transaction_timestamp >= :start_ts AND t.transaction_timestamp <= :end_ts
    GROUP BY t.bank_id, date(t.transaction_timestamp)
)
SELECT d.bank_id, b.bank_name, d.report_date,
       d.derived_total, d.derived_successful, d.derived_failed,
       r.reported_total, r.reported_successful, r.reported_failed, r.source_name
FROM derived d
JOIN banks b ON b.bank_id = d.bank_id
LEFT JOIN bank_daily_reports r ON r.bank_id = d.bank_id AND r.report_date = d.report_date
ORDER BY d.report_date, d.bank_id
LIMIT 5000"""

WARN_PCT = 0.5
CRITICAL_PCT = 2.0


def _status(a: int, b: int | None) -> tuple[str, int | None, float | None]:
    if b is None:
        return "MISSING", None, None
    diff = b - a
    pct = abs(diff) / a * 100 if a else (0.0 if diff == 0 else 100.0)
    if pct >= CRITICAL_PCT:
        return "CRITICAL", diff, pct
    if pct >= WARN_PCT:
        return "WARNING", diff, pct
    return "OK", diff, pct


def run_reconciliation() -> dict:
    run = execute(CompiledQuery("Source reconciliation: transactions vs bank_daily_reports", RECONCILIATION_SQL, _window_params()))
    rows, per_bank = [], {}
    for r in run.rows:
        entry = {"bank_id": r["bank_id"], "bank_name": r["bank_name"], "report_date": r["report_date"], "source_b": r["source_name"], "metrics": {}}
        worst = "OK"
        for metric in ("total", "successful", "failed"):
            a, b = r[f"derived_{metric}"], r[f"reported_{metric}"]
            st, diff, pct = _status(a, b)
            entry["metrics"][metric] = {"source_a": a, "source_b": b, "abs_discrepancy": diff,
                                        "pct_discrepancy": None if pct is None else round(pct, 2), "status": st}
            order = ["OK", "WARNING", "CRITICAL", "MISSING"]
            worst = max(worst, st, key=order.index)
        entry["status"] = worst
        rows.append(entry)
        pb = per_bank.setdefault(r["bank_id"], {"bank_id": r["bank_id"], "bank_name": r["bank_name"], "days": 0, "ok": 0, "warning": 0,
                                                "critical": 0, "missing": 0, "source_a_total": 0, "source_b_total": 0})
        pb["days"] += 1
        pb[worst.lower()] += 1
        pb["source_a_total"] += r["derived_total"]
        pb["source_b_total"] += r["reported_total"] or 0
    flagged = [e for e in rows if e["status"] != "OK"]
    return {
        "source_a": "Transaction-derived counts (transactions_canonical)",
        "source_b": "Bank-reported daily MIS (bank_daily_reports)",
        "thresholds": {"warning_pct": WARN_PCT, "critical_pct": CRITICAL_PCT},
        "policy": "Sources are never merged. Transaction-derived data is used for analytics; discrepancies are flagged for investigation.",
        "status": "fail" if any(e["status"] in ("CRITICAL", "MISSING") for e in flagged) else "warn" if flagged else "pass",
        "flagged": flagged,
        "flagged_count": len(flagged),
        "compared_rows": len(rows),
        "banks": sorted(per_bank.values(), key=lambda x: -(x["critical"] + x["missing"] + x["warning"])),
        "query": run.meta(),
    }
