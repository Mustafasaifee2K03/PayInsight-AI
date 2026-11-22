"""Dashboard overview: KPI cards and charts, all computed by validated SQL."""
from __future__ import annotations

from datetime import timedelta

from ..config import get_settings
from ..core.security import User
from ..database.manager import get_db
from ..database.schema import RELATIONSHIPS, TABLE_DESCRIPTIONS
from ..schemas.plan import AnalysisPlan, TimeRange
from .metrics import METRICS
from .query_executor import execute
from .sql_compiler import CompiledQuery, compile_aggregate, compile_period_segments


def _plan(metric: str, tr: TimeRange, comparison: TimeRange | None = None, sort: str = "desc") -> AnalysisPlan:
    return AnalysisPlan(intent="kpi", metric=metric, time_range=tr, comparison="previous_period" if comparison else None,
                        comparison_range=comparison, sort=sort)


def overview(user: User, window_days: int = 30) -> dict:
    s = get_settings()
    window_days = max(1, min(window_days, s.data_days))
    end = s.data_end_date
    cur = TimeRange(start=end - timedelta(days=window_days - 1), end=end, label=f"last {window_days} days")
    prev_start = cur.start - timedelta(days=window_days)
    prev = TimeRange(start=prev_start, end=cur.start - timedelta(days=1), label=f"previous {window_days} days") if prev_start >= s.data_start_date else None
    full = TimeRange(start=s.data_start_date, end=end, label="full window")
    queries = []

    def run(q):
        r = execute(q)
        queries.append(r.meta())
        return r.rows

    kpi_rows = {}
    if prev:
        for r in run(compile_period_segments(_plan("success_rate", cur, prev), None, purpose="KPI cards: current vs previous window")):
            kpi_rows[r["period"]] = r
    else:
        kpi_rows["current"] = run(compile_aggregate(_plan("success_rate", cur), dimensions=[], purpose="KPI cards"))[0]
    cards = []
    for name in ("transaction_count", "success_rate", "failed_transactions", "tpv"):
        m = METRICS[name]
        c_val = m.compute(kpi_rows["current"])
        card = {"metric": name, "label": m.label, "unit": m.unit, "value": c_val, "higher_is_better": m.higher_is_better,
                "numerator": kpi_rows["current"].get(m.numerator), "denominator": kpi_rows["current"].get(m.denominator) if m.denominator else None}
        if "baseline" in kpi_rows:
            p_val = m.compute(kpi_rows["baseline"])
            card["previous"] = p_val
            if c_val is not None and p_val is not None:
                card["change_abs"] = c_val - p_val
                card["change_pct"] = (c_val - p_val) / p_val * 100 if p_val else None
        cards.append(card)

    daily = run(compile_aggregate(_plan("success_rate", full), dimensions=["day"], purpose="Daily trend (full window)", order="day ASC"))
    trend = [{"day": r["day"], "attempts": r["attempts"], "failed": r["failed"], "success_rate": METRICS["success_rate"].compute(r),
              "tpv_minor": r["tpv_minor"]} for r in daily if r["day"]]

    def seg(dim: str, metric: str = "success_rate", order: str = "attempts DESC"):
        rows = run(compile_aggregate(_plan(metric, cur), dimensions=[dim], purpose=f"{dim} breakdown ({cur.label})", order=order))
        total = sum(r["attempts"] for r in rows) or 1
        return [{"segment": r[dim], "attempts": r["attempts"], "share_pct": 100 * r["attempts"] / total, "failed": r["failed"],
                 "success_rate": METRICS["success_rate"].compute(r), "tpv_minor": r["tpv_minor"]} for r in rows]

    restricted = []
    methods = seg("payment_method")
    banks = seg("bank") if "bank" in user.allowed_dimensions else None
    if banks is None:
        restricted.append("Bank performance (requires ANALYST or ADMIN)")
    fc_rows = run(compile_aggregate(_plan("failed_transactions", cur), dimensions=["failure_code"], purpose=f"Failure codes ({cur.label})"))
    tf = sum(r["failed"] for r in fc_rows) or 1
    failure_codes = [{"segment": r["failure_code"], "failed": r["failed"], "share_pct": 100 * r["failed"] / tf} for r in fc_rows]
    categories = seg("merchant_category")
    return {
        "window": cur.as_dict(), "previous_window": prev.as_dict() if prev else None, "data_profile": get_db().profile,
        "kpis": cards, "daily_trend": trend, "payment_methods": methods, "banks": banks, "failure_codes": failure_codes,
        "categories": categories, "restricted": restricted, "queries": queries,
    }


def datasets() -> dict:
    tables = []
    for name in ("transactions_raw", "transactions_canonical", "merchants", "banks", "payment_methods", "settlements", "bank_daily_reports"):
        cols = execute(CompiledQuery(f"Columns of {name}", f"SELECT * FROM {name} LIMIT 1")).columns
        cnt = execute(CompiledQuery(f"Row count of {name}", f"SELECT COUNT(*) AS n FROM {name}")).rows[0]["n"]
        tables.append({"name": name, "description": TABLE_DESCRIPTIONS[name], "row_count": cnt, "columns": cols})
    meta = {r["key"]: r["value"] for r in execute(CompiledQuery("Dataset metadata", "SELECT key, value FROM dataset_metadata")).rows}
    return {"tables": tables, "relationships": [{"from": a, "to": b} for a, b in RELATIONSHIPS], "metadata": meta,
            "view": {"name": "v_transactions_canonical", "description": TABLE_DESCRIPTIONS["v_transactions_canonical"]}}
