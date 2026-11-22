"""Compile validated analysis plans into parameterised SQLite SELECT statements.

Identifiers (tables, columns, expressions) come exclusively from the allowlists
below. User-derived values (dates, filter IDs) are always bound parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ..schemas.plan import AnalysisPlan, Filter, TimeRange
from .metrics import BASE_AGGREGATES, METRICS

UNKNOWN = "Unknown / unmapped"


@dataclass(frozen=True)
class DimensionSpec:
    name: str
    label: str
    select_expr: str
    join: str | None  # alias of required join
    filter_column: str


JOINS = {
    "b": "LEFT JOIN banks b ON b.bank_id = t.bank_id",
    "m": "LEFT JOIN merchants m ON m.merchant_id = t.merchant_id",
    "pm": "LEFT JOIN payment_methods pm ON pm.payment_method_id = t.payment_method_id",
}

DIMENSIONS: dict[str, DimensionSpec] = {
    "bank": DimensionSpec("bank", "Bank", f"COALESCE(b.bank_name, '{UNKNOWN}')", "b", "t.bank_id"),
    "merchant": DimensionSpec("merchant", "Merchant", f"COALESCE(m.merchant_name, '{UNKNOWN}')", "m", "t.merchant_id"),
    "merchant_category": DimensionSpec("merchant_category", "Merchant category", f"COALESCE(m.merchant_category, '{UNKNOWN}')", "m", "m.merchant_category"),
    "region": DimensionSpec("region", "Region (merchant)", f"COALESCE(m.region, '{UNKNOWN}')", "m", "m.region"),
    "payment_method": DimensionSpec("payment_method", "Payment method", f"COALESCE(pm.method_name, '{UNKNOWN}')", "pm", "t.payment_method_id"),
    "failure_code": DimensionSpec("failure_code", "Failure code", "COALESCE(t.failure_code, 'NOT_RECORDED')", None, "t.failure_code"),
    "day": DimensionSpec("day", "Day", "date(t.transaction_timestamp)", None, "date(t.transaction_timestamp)"),
}


@dataclass
class CompiledQuery:
    purpose: str
    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    # Business dimensions this query groups or filters by. Used to authorise later re-reads of stored
    # results against the reader's *current* role (hardening iteration 6).
    dimensions: frozenset[str] = frozenset()


class _Builder:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self.joins: list[str] = []
        self.where: list[str] = []
        self.dims: set[str] = set()

    def need(self, alias: str | None) -> None:
        if alias and JOINS[alias] not in self.joins:
            self.joins.append(JOINS[alias])

    def bind(self, name: str, value: Any) -> str:
        self.params[name] = value
        return f":{name}"

    def time(self, start_name: str, end_name: str, tr_start, tr_end_inclusive) -> None:
        s = self.bind(start_name, f"{tr_start.isoformat()} 00:00:00")
        e = self.bind(end_name, f"{(tr_end_inclusive + timedelta(days=1)).isoformat()} 00:00:00")
        self.where.append(f"t.transaction_timestamp >= {s} AND t.transaction_timestamp < {e}")

    def filters(self, filters: list[Filter]) -> None:
        for i, f in enumerate(filters):
            self.dims.add(f.dimension)
            spec = DIMENSIONS[f.dimension]
            self.need(spec.join)
            names = [self.bind(f"f{i}_{j}", v) for j, v in enumerate(f.values)]
            self.where.append(f"{spec.filter_column} IN ({', '.join(names)})")

    def render(self, select: list[str], group_by: list[str] | None = None, order_by: str | None = None, limit: int = 1000) -> str:
        lines = ["SELECT " + ",\n       ".join(select), "FROM transactions_canonical t"]
        lines += self.joins
        if self.where:
            lines.append("WHERE " + "\n  AND ".join(self.where))
        if group_by:
            lines.append("GROUP BY " + ", ".join(group_by))
        if order_by:
            lines.append("ORDER BY " + order_by)
        lines.append(f"LIMIT {int(limit)}")
        return "\n".join(lines)


def _aggregates() -> list[str]:
    return [f"{expr} AS {name}" for name, expr in BASE_AGGREGATES]


def compile_aggregate(plan: AnalysisPlan, *, dimensions: list[str] | None = None, time_range: TimeRange | None = None,
                      purpose: str = "Aggregate metric", limit: int | None = None, extra_filters: list[Filter] | None = None,
                      order: str | None = None) -> CompiledQuery:
    """Base aggregates (optionally grouped) for the plan's filters and a time range."""
    dims = plan.dimensions if dimensions is None else dimensions
    tr = time_range or plan.time_range
    b = _Builder()
    b.time("start_ts", "end_ts", tr.start, tr.end)
    b.filters(plan.filters + (extra_filters or []))
    select, group = [], []
    for d in dims:
        spec = DIMENSIONS[d]
        b.need(spec.join)
        b.dims.add(d)
        select.append(f"{spec.select_expr} AS {d}")
        group.append(d)
        if d != "day":
            select.append(f"{spec.filter_column} AS {d}_key")
            group.append(f"{d}_key")
    if "failure_code" in dims:
        b.where.append("t.status = 'FAILED'")
    metric = METRICS[plan.metric]
    select += _aggregates() + [f"{metric.sql_expression} AS metric_value"]
    if order is None:
        if "day" in dims:
            order = "day ASC"
        elif dims:
            order = f"metric_value {plan.sort.upper()}, attempts DESC"
    return CompiledQuery(purpose, b.render(select, group or None, order, limit or 1000), b.params, frozenset(b.dims - {"day"}))


def compile_period_segments(plan: AnalysisPlan, dimension: str | None, *, purpose: str, extra_filters: list[Filter] | None = None) -> CompiledQuery:
    """Base aggregates for baseline and current periods (equal length), optionally per segment."""
    assert plan.comparison_range is not None
    cur, base = plan.time_range, plan.comparison_range
    b = _Builder()
    b.time("base_start_ts", "cur_end_ts", base.start, cur.end)
    cur_start = b.bind("cur_start_ts", f"{cur.start.isoformat()} 00:00:00")
    b.filters(plan.filters + (extra_filters or []))
    select = [f"CASE WHEN t.transaction_timestamp >= {cur_start} THEN 'current' ELSE 'baseline' END AS period"]
    group = ["period"]
    if dimension:
        spec = DIMENSIONS[dimension]
        b.need(spec.join)
        b.dims.add(dimension)
        select.append(f"{spec.select_expr} AS segment")
        select.append(f"{spec.filter_column} AS segment_key")
        group += ["segment", "segment_key"]
        if dimension == "failure_code":
            b.where.append("t.status = 'FAILED'")
    select += _aggregates()
    return CompiledQuery(purpose, b.render(select, group, ", ".join(group), 2000), b.params, frozenset(b.dims))


def compile_daily(plan: AnalysisPlan, time_range: TimeRange, *, purpose: str) -> CompiledQuery:
    return compile_aggregate(plan, dimensions=["day"], time_range=time_range, purpose=purpose, limit=1000, order="day ASC")
