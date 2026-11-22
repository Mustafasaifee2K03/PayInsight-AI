"""One-click deterministic demo scenarios (A–G)."""
from __future__ import annotations

from ..core.security import User
from ..database.app_store import get_setting, set_setting
from ..database.manager import get_db
from .query_executor import cache

SCENARIOS = [
    {
        "id": "A", "key": "normal", "title": "Normal performance", "profile": "baseline",
        "description": "Stable payments business. Basic counts, success rate and TPV over the full 60-day window.",
        "suggested_role": "ANALYST", "page": "workspace",
        "questions": ["How many transactions occurred?", "What is the overall success rate?", "What is our total transaction value?", "Show daily transaction trends"],
    },
    {
        "id": "B", "key": "bank_decline", "title": "Bank performance decline", "profile": "bank_decline",
        "description": "Deccan Commercial Bank's success rate is deliberately degraded by ~22 pp in the last 7 days (mostly BANK_TIMEOUT).",
        "suggested_role": "ANALYST", "page": "workspace",
        "questions": ["Why did payment success rate decline?", "Which banks contributed most to the decline?", "Compare bank-level performance across periods"],
    },
    {
        "id": "C", "key": "method_comparison", "title": "Payment method comparison", "profile": "baseline",
        "description": "Segment-level performance across UPI, cards and net banking.",
        "suggested_role": "ANALYST", "page": "workspace",
        "questions": ["Which payment methods have the highest failure rates?", "Compare payment success rates by payment method", "Which payment method performs best?"],
    },
    {
        "id": "D", "key": "mix_shift", "title": "Transaction mix shift", "profile": "mix_shift",
        "description": "Per-method success rates are unchanged, but the last 7 days shift share from UPI to Net Banking. The blended rate falls purely from mix.",
        "suggested_role": "ANALYST", "page": "workspace",
        "questions": ["Is the decline caused by payment-method mix?", "Why did payment success rate decline?", "Did transaction composition change?"],
    },
    {
        "id": "E", "key": "data_quality", "title": "Data quality failure", "profile": "data_quality",
        "description": "Injected duplicate versions, missing and orphan dimension keys, invalid statuses, amounts and timestamps.",
        "suggested_role": "ADMIN", "page": "quality",
        "questions": ["What is the overall success rate?", "Compare payment success rates by bank"],
    },
    {
        "id": "F", "key": "access_control", "title": "Access control failure", "profile": "baseline",
        "description": "Sign in as viewer@payinsight.demo and request a bank-level breakdown; the backend rejects it with HTTP 403.",
        "suggested_role": "VIEWER", "page": "workspace",
        "questions": ["Compare payment success rates by bank", "Compare payment success rates by payment method"],
    },
    {
        "id": "G", "key": "source_discrepancy", "title": "Source discrepancy", "profile": "source_discrepancy",
        "description": "Ganga Valley Bank's daily MIS over-reports successes on three days and one Bharat Union Bank report is missing.",
        "suggested_role": "ADMIN", "page": "quality",
        "questions": ["Compare bank-level performance across periods"],
    },
]
_BY_ID = {s["id"]: s for s in SCENARIOS}


def active_scenario_id() -> str:
    return get_setting("active_scenario", "A") or "A"


def list_scenarios() -> dict:
    return {"active": active_scenario_id(), "data_profile": get_db().profile, "scenarios": SCENARIOS}


def activate(scenario_id: str, user: User, *, reseed: bool = False) -> dict:
    user.require("scenarios:activate")
    sc = _BY_ID.get(scenario_id.upper())
    if sc is None:
        from ..core.errors import NotFoundError
        raise NotFoundError(f"Unknown scenario '{scenario_id}'.")
    gen = get_db().activate(sc["profile"], rebuild=reseed)
    cache.clear()
    set_setting("active_scenario", sc["id"])
    return {
        "active": sc["id"], "scenario": sc, "data_profile": sc["profile"], "regenerated": gen is not None,
        "generation_seconds": round(gen.seconds, 2) if gen else None, "cache_cleared": True,
    }


def restore_active() -> None:
    sc = _BY_ID.get(active_scenario_id(), _BY_ID["A"])
    get_db().activate(sc["profile"])
