"""Central business-metric definitions.

All analytical SQL selects the same set of *base aggregates*; each metric is a
documented function of those aggregates. Rates are computed from integer
numerators/denominators, so every reported value can expose both.

Eligibility rule (default success-rate metric)
---------------------------------------------
Eligible attempts = canonical transactions with terminal status SUCCESS or FAILED.
PENDING (non-terminal) and any invalid statuses are excluded from the denominator.

TPV rule
--------
TPV = sum of amount_minor for SUCCESS transactions in INR with amount_minor > 0.
Other currencies are never summed with INR; they are reported separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Unit = Literal["count", "percent", "currency_minor"]

BASE_AGGREGATES: list[tuple[str, str]] = [
    ("attempts", "COUNT(*)"),
    ("successful", "SUM(CASE WHEN t.status = 'SUCCESS' THEN 1 ELSE 0 END)"),
    ("failed", "SUM(CASE WHEN t.status = 'FAILED' THEN 1 ELSE 0 END)"),
    ("pending", "SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END)"),
    ("eligible", "SUM(CASE WHEN t.status IN ('SUCCESS', 'FAILED') THEN 1 ELSE 0 END)"),
    ("tpv_minor", "SUM(CASE WHEN t.status = 'SUCCESS' AND t.currency = 'INR' AND t.amount_minor > 0 THEN t.amount_minor ELSE 0 END)"),
    ("tpv_txn_count", "SUM(CASE WHEN t.status = 'SUCCESS' AND t.currency = 'INR' AND t.amount_minor > 0 THEN 1 ELSE 0 END)"),
]
_AGG = dict(BASE_AGGREGATES)


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    label: str
    unit: Unit
    formula: str
    numerator: str
    denominator: str | None
    sql_expression: str
    higher_is_better: bool
    notes: list[str] = field(default_factory=list)

    def compute(self, row: dict) -> float | None:
        num = row.get(self.numerator) or 0
        if self.denominator is None:
            return float(num)
        den = row.get(self.denominator) or 0
        if den == 0:
            return None
        scale = 100.0 if self.unit == "percent" else 1.0
        return scale * num / den

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "unit": self.unit,
            "formula": self.formula,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "sql_expression": self.sql_expression,
            "higher_is_better": self.higher_is_better,
            "notes": self.notes,
        }


ELIGIBILITY_NOTE = "Eligible attempts = SUCCESS + FAILED. PENDING and invalid statuses are excluded from the denominator."

METRICS: dict[str, MetricDefinition] = {
    m.name: m
    for m in [
        MetricDefinition(
            "transaction_count", "Total payment attempts", "count",
            "COUNT(canonical transactions in window)", "attempts", None, _AGG["attempts"], True,
            ["Includes SUCCESS, FAILED, PENDING and any invalid statuses (one row per transaction_id)."],
        ),
        MetricDefinition(
            "successful_transactions", "Successful transactions", "count",
            "COUNT(status = SUCCESS)", "successful", None, _AGG["successful"], True,
        ),
        MetricDefinition(
            "failed_transactions", "Failed transactions", "count",
            "COUNT(status = FAILED)", "failed", None, _AGG["failed"], False,
        ),
        MetricDefinition(
            "pending_transactions", "Pending transactions", "count",
            "COUNT(status = PENDING)", "pending", None, _AGG["pending"], False,
            ["Pending = non-terminal; excluded from success-rate denominator."],
        ),
        MetricDefinition(
            "success_rate", "Payment success rate", "percent",
            "Successful eligible attempts / Total eligible attempts x 100", "successful", "eligible",
            f"100.0 * {_AGG['successful']} / NULLIF({_AGG['eligible']}, 0)", True, [ELIGIBILITY_NOTE],
        ),
        MetricDefinition(
            "failure_rate", "Payment failure rate", "percent",
            "Failed eligible attempts / Total eligible attempts x 100", "failed", "eligible",
            f"100.0 * {_AGG['failed']} / NULLIF({_AGG['eligible']}, 0)", False, [ELIGIBILITY_NOTE],
        ),
        MetricDefinition(
            "tpv", "Total payment value (TPV, INR)", "currency_minor",
            "SUM(amount_minor) where status = SUCCESS, currency = INR, amount_minor > 0", "tpv_minor", None,
            _AGG["tpv_minor"], True,
            ["Stored in paise (integer minor units). Non-INR transactions are excluded, never converted or summed."],
        ),
        MetricDefinition(
            "avg_transaction_value", "Average transaction value (INR)", "currency_minor",
            "TPV / COUNT(successful INR transactions with positive amount)", "tpv_minor", "tpv_txn_count",
            f"1.0 * {_AGG['tpv_minor']} / NULLIF({_AGG['tpv_txn_count']}, 0)", True,
            ["Average of successful INR transactions only."],
        ),
    ]
}

PERIOD_KPI_METRICS = ["transaction_count", "successful_transactions", "failed_transactions", "success_rate", "failure_rate", "tpv"]


def get_metric(name: str) -> MetricDefinition:
    return METRICS[name]


def metric_values(row: dict) -> dict[str, float | None]:
    return {name: m.compute(row) for name, m in METRICS.items()}


def change(current: float | None, previous: float | None, unit: Unit) -> dict:
    """Period-over-period change. For percentage metrics, the absolute change is in
    percentage points (pp) and is reported separately from the relative % change."""
    if current is None or previous is None:
        return {"absolute": None, "absolute_unit": "pp" if unit == "percent" else unit, "relative_pct": None}
    absolute = current - previous
    relative = (absolute / previous * 100.0) if previous else None
    return {"absolute": absolute, "absolute_unit": "pp" if unit == "percent" else unit, "relative_pct": relative}
