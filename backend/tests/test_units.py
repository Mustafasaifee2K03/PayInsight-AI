"""Unit tests: planner, SQL validator, decomposition maths, metric helpers."""
from __future__ import annotations

from datetime import date

import pytest

from app.services.decomposition import daily_anomalies, decompose, two_proportion_z
from app.services.metrics import change
from app.services.planner import CatalogEntry, PlannerContext, normalise, plan_question
from app.services.sql_validator import validate_sql

CTX = PlannerContext(
    data_start=date(2025, 9, 1), data_end=date(2025, 10, 30),
    catalog=[
        CatalogEntry("bank", "B03", "Deccan Commercial Bank", ["deccan", "deccan bank"]),
        CatalogEntry("bank", "B04", "Eastern Coastal Bank", ["eastern"]),
        CatalogEntry("payment_method", "PM01", "UPI", ["upi"]),
        CatalogEntry("payment_method", "PM04", "Net Banking", ["netbanking", "net banking"]),
        CatalogEntry("payment_method", "PM03", "Credit Card", ["credit cards", "credit"]),
        CatalogEntry("region", "East", "East", ["eastern region"]),
        CatalogEntry("failure_code", "BANK_TIMEOUT", "BANK_TIMEOUT", ["bank timeout"]),
    ],
)


def plan(q):
    out = plan_question(q, CTX)
    return out


@pytest.mark.parametrize("q,intent,metric,dims", [
    ("How many transactions occurred?", "kpi", "transaction_count", []),
    ("What is the overall success rate?", "kpi", "success_rate", []),
    ("What is our total transaction value?", "kpi", "tpv", []),
    ("What's the average ticket size?", "kpi", "avg_transaction_value", []),
    ("Show daily transaction trends", "trend", "transaction_count", []),
    ("Compare payment success rates by bank", "breakdown", "success_rate", ["bank"]),
    ("Which payment methods have the highest failure rates?", "ranking", "failure_rate", ["payment_method"]),
    ("Which merchants have the highest failed transaction volumes?", "ranking", "failed_transactions", ["merchant"]),
    ("What are the main failure codes?", "breakdown", "failed_transactions", ["failure_code"]),
    ("Compare the last seven days with the previous seven days.", "period_comparison", "success_rate", []),
    ("Why did payment success rate decline?", "diagnose", "success_rate", []),
    ("Which banks contributed most to the decline?", "contribution", "success_rate", ["bank"]),
    ("Is the decline caused by payment-method mix?", "mix_decomposition", "success_rate", ["payment_method"]),
    ("Which merchants have unusual failure rates?", "segment_outliers", "failure_rate", ["merchant"]),
    ("Compare bank-level performance across periods", "period_comparison", "success_rate", ["bank"]),
    ("Did transaction composition change?", "mix_decomposition", "success_rate", ["payment_method"]),
    ("Any anomalies in daily success rate?", "anomaly_daily", "success_rate", []),
    ("approval rate split by region", "breakdown", "success_rate", ["region"]),
    ("GMV by merchant category", "breakdown", "tpv", ["merchant_category"]),
    ("UPI vs net banking success rate", "breakdown", "success_rate", ["payment_method"]),
])
def test_planner_question_catalogue(q, intent, metric, dims):
    out = plan(q)
    assert out.status == "planned", out.message
    assert out.plan.intent == intent
    assert out.plan.metric == metric
    assert out.plan.dimensions == dims


def test_planner_spec_example_output():
    p = plan("Compare payment success rates by bank over the last seven days.").plan
    d = p.summary_dict()
    assert d["metric"] == "success_rate" and d["visualization"] == "kpi_comparison"
    assert d["dimensions"] == ["bank"] and d["time_range"]["days"] == 7 and d["comparison"] == "previous_period"
    assert p.comparison_range.days == 7 and p.comparison_range.end == date(2025, 10, 23)


def test_planner_entity_filters_and_time():
    p = plan("Show daily success rate for Deccan Commercial Bank in October").plan
    assert p.intent == "trend" and p.filters[0].values == ["B03"]
    assert p.time_range.start == date(2025, 10, 1) and p.time_range.end == date(2025, 10, 30)
    p2 = plan("success rate for BANK_TIMEOUT on UPI last 14 days").plan
    assert {f.dimension for f in p2.filters} == {"failure_code", "payment_method"}
    assert p2.time_range.days == 14


def test_planner_explicit_dates_and_clipping():
    p = plan("success rate between 2025-08-20 and 2025-09-10").plan
    assert p.time_range.start == date(2025, 9, 1) and p.time_range.end == date(2025, 9, 10)
    assert any("clipped" in a for a in p.assumptions)


def test_planner_defaults_are_explicit():
    p = plan("Which bank is best?").plan
    assert p.intent == "ranking" and p.sort == "desc"
    assert len(p.assumptions) == 2


def test_planner_worst_sorts_ascending_for_success_rate():
    assert plan("Which bank has the worst success rate?").plan.sort == "asc"
    assert plan("Which bank has the worst failure rate?").plan.sort == "desc"
    assert plan("top 3 merchants by failed transactions").plan.limit == 3


@pytest.mark.parametrize("q,status", [
    ("", "needs_clarification"),
    ("How are we doing?", "needs_clarification"),
    ("Why?", "needs_clarification"),
    ("Compare the last 60 days with the previous 60 days", "needs_clarification"),
    ("success rate in March 2024", "needs_clarification"),
    ("success rate on 2025-02-30", "needs_clarification"),
    ("delete all failed transactions", "rejected"),
    ("drop table banks", "rejected"),
    ("x" * 600, "rejected"),
])
def test_planner_ambiguous_or_unsafe(q, status):
    assert plan(q).status == status


def test_normalise_word_numbers_and_hyphens():
    assert normalise("Bank-level, last SEVEN days!") == "bank level last 7 days"


@pytest.mark.parametrize("sql,ok", [
    ("SELECT COUNT(*) FROM transactions_canonical", True),
    ("WITH x AS (SELECT bank_id FROM banks) SELECT * FROM x", True),
    ("SELECT bank_id FROM banks WHERE bank_name = 'a;b'", True),  # ';' inside a string literal is not a separator
    ("SELECT * FROM banks UNION SELECT * FROM banks", True),
    ("SELECT * FROM banks; SELECT 1", False),
    ("DELETE FROM banks", False),
    ("SELECT * FROM users", False),
    ("SELECT * FROM pragma_table_info('banks')", False),
    ("CREATE TABLE x AS SELECT * FROM banks", False),
    ("SELECT randomblob(1000000000) FROM banks", False),
    ("SELECT * FROM banks /* hi */", False),
])
def test_validator(sql, ok):
    v = validate_sql(sql, max_rows=100)
    assert v.valid is ok, v.reasons


def test_validator_enforces_row_limit():
    v = validate_sql("SELECT * FROM banks LIMIT 100000", max_rows=50)
    assert v.valid and v.limit_applied == 50 and v.sql.endswith("LIMIT 50")
    v2 = validate_sql("SELECT * FROM banks LIMIT 10", max_rows=50)
    assert v2.limit_applied is None


def test_decomposition_identity_random():
    import random
    rnd = random.Random(7)
    for _ in range(200):
        segs = []
        for i in range(rnd.randint(1, 8)):
            be, ce = rnd.choice([0, rnd.randint(1, 500)]), rnd.choice([0, rnd.randint(1, 500)])
            segs.append({"segment": str(i), "b_elig": be, "b_succ": rnd.randint(0, be), "c_elig": ce, "c_succ": rnd.randint(0, ce)})
        if sum(s["b_elig"] for s in segs) == 0 or sum(s["c_elig"] for s in segs) == 0:
            continue
        d = decompose(segs)
        assert abs(d["residual_pp"]) < 1e-9


def test_decomposition_pure_mix_and_pure_within():
    mix = decompose([{"segment": "hi", "b_elig": 800, "b_succ": 760, "c_elig": 400, "c_succ": 380},
                     {"segment": "lo", "b_elig": 200, "b_succ": 160, "c_elig": 600, "c_succ": 480}])
    assert abs(mix["within_effect_pp"]) < 1e-9 and mix["mix_effect_pp"] < 0
    within = decompose([{"segment": "a", "b_elig": 500, "b_succ": 450, "c_elig": 500, "c_succ": 400},
                        {"segment": "b", "b_elig": 500, "b_succ": 450, "c_elig": 500, "c_succ": 450}])
    assert abs(within["mix_effect_pp"]) < 1e-9 and abs(within["within_effect_pp"] + 5.0) < 1e-9


def test_change_pp_vs_relative():
    ch = change(88.0, 92.0, "percent")
    assert ch["absolute"] == pytest.approx(-4.0) and ch["absolute_unit"] == "pp"
    assert ch["relative_pct"] == pytest.approx(-4.3478, rel=1e-4)
    assert change(None, 1.0, "count")["absolute"] is None


def test_two_proportion_z_and_anomaly_rule():
    assert two_proportion_z(900, 1000, 800, 1000) < -5
    assert two_proportion_z(0, 0, 1, 1) is None
    daily = [{"day": f"2025-10-{d:02d}", "v": 92.0 + (0.3 if d % 2 else -0.3)} for d in range(1, 21)]
    daily[-1]["v"] = 80.0
    flagged = [a["day"] for a in daily_anomalies(daily, "v", "2025-10-15") if a["flagged"]]
    assert flagged == ["2025-10-20"]
