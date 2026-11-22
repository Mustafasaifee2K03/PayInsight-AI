"""Rule-based hypotheses and recommended investigations.

These rules turn *observed* numbers into *candidate* explanations and next
steps. They never assert causality: hypotheses are phrased as possibilities
that the recommended actions would confirm or rule out.
"""
from __future__ import annotations

from ..utils.formatting import pct, pp

FAILURE_CODE_HYPOTHESES = {
    "BANK_TIMEOUT": "issuer/bank-side latency or downtime, or gateway-to-bank connectivity problems",
    "NETWORK_ERROR": "network or switch connectivity issues between the gateway and the bank/NPCI",
    "ISSUER_DECLINED": "issuer policy changes or tighter issuer risk controls",
    "INSUFFICIENT_FUNDS": "customer-side balance issues (usually not actionable by the gateway)",
    "INCORRECT_PIN_OTP": "authentication friction (OTP delivery delays, PIN-entry UX)",
    "RISK_DECLINED": "merchant or gateway fraud-rule thresholds being triggered",
    "LIMIT_EXCEEDED": "per-transaction or daily limits (e.g. UPI limits, card limits)",
    "NOT_RECORDED": "incomplete upstream data (failure reason missing)",
}

FAILURE_CODE_ACTIONS = {
    "BANK_TIMEOUT": "Check gateway→bank latency and timeout dashboards; open an incident with the bank's technical team and request their uptime report for the affected days.",
    "NETWORK_ERROR": "Review network/switch error logs for the affected window and verify failover routing.",
    "ISSUER_DECLINED": "Request decline-reason detail from the issuer and check for recent policy or BIN-level rule changes.",
    "INSUFFICIENT_FUNDS": "Consider retry-with-alternate-method prompts at checkout; this cause is largely customer-driven.",
    "INCORRECT_PIN_OTP": "Audit OTP delivery latency and PIN/OTP entry UX on the checkout flow.",
    "RISK_DECLINED": "Review fraud-rule hit rates and false-positive rate for the affected merchant(s) with the risk team.",
    "LIMIT_EXCEEDED": "Check whether ticket sizes changed or limits were lowered; suggest alternate methods for high-value payments.",
    "NOT_RECORDED": "Fix upstream feed so failure_code is always populated for FAILED transactions.",
}


def rec(action: str, rationale: str, priority: str = "medium") -> dict:
    return {"action": action, "rationale": rationale, "priority": priority}


def for_deterioration(dim_label: str, segment: str, seg: dict, top_code: dict | None) -> tuple[list[str], list[dict]]:
    hyps, recs = [], []
    hyps.append(
        f"The decline is concentrated in {dim_label.lower()} '{segment}' (success rate {pct(seg.get('baseline_rate_pct'))} → "
        f"{pct(seg.get('current_rate_pct'))}). This pattern is consistent with a segment-specific operational issue rather than a market-wide change, "
        "but the data alone does not prove the cause."
    )
    if top_code:
        code = top_code["code"]
        hyps.append(
            f"{code} failures for '{segment}' rose from {top_code['baseline']:,} to {top_code['current']:,}; this may point to "
            f"{FAILURE_CODE_HYPOTHESES.get(code, 'an operational issue')}."
        )
        recs.append(rec(f"Investigate {code} failures for {segment}", FAILURE_CODE_ACTIONS.get(code, "Review failure logs for the affected window."), "high"))
    recs.append(rec(
        f"Escalate to the {segment} relationship / integration team",
        f"Share the daily success-rate series and failure-code shift as evidence; ask for incident reports covering the affected days.", "high"))
    recs.append(rec(
        "Evaluate temporary routing or retry mitigations",
        f"If the issue persists, assess smart-retry or alternate routing for traffic affected by {segment}, and monitor the impact.", "medium"))
    return hyps, recs


def for_mix(dim_label: str, top_mix: list[dict], mix_pp: float, within_pp: float) -> tuple[list[str], list[dict]]:
    hyps, recs = [], []
    movers = ", ".join(f"{s['segment']} ({pp(s['share_change_pp'], 1)} share)" for s in top_mix[:3])
    hyps.append(
        f"Transaction mix shifted across {dim_label.lower()} segments ({movers}). Segments with structurally lower success rates gained share, "
        f"which lowers the blended rate even though per-segment performance was broadly stable (within-segment effect {pp(within_pp)})."
    )
    hyps.append("Possible drivers of the shift include checkout/UI changes, a promotion on a specific method, or an outage of a preferred method — these need confirmation.")
    recs.append(rec(f"Identify what moved traffic between {dim_label.lower()}s",
                    "Review recent checkout releases, campaigns and method availability around the start of the current period.", "high"))
    recs.append(rec("Report success rate on a mix-adjusted basis",
                    f"Mix explains {pp(mix_pp)} of the change; track per-segment rates alongside the blended rate to avoid misreading mix as deterioration.", "medium"))
    recs.append(rec("Do not escalate to banks solely on the blended decline",
                    "Per-segment success rates did not materially deteriorate, so an issuer escalation is not supported by this evidence.", "medium"))
    return hyps, recs


def for_outliers(dim_label: str, flagged: list[dict], top_codes: list[dict]) -> tuple[list[str], list[dict]]:
    hyps, recs = [], []
    for f in flagged[:3]:
        code_txt = ""
        if top_codes and f is flagged[0]:
            code_txt = f" Its leading failure code is {top_codes[0]['code']} ({top_codes[0]['share_pct']:.0f}% of its failures), which may indicate {FAILURE_CODE_HYPOTHESES.get(top_codes[0]['code'], 'an operational issue')}."
        hyps.append(f"{dim_label} '{f['segment']}' fails at {pct(f['failure_rate_pct'])} vs {pct(f['overall_failure_rate_pct'])} overall (z = {f['z']:.1f}).{code_txt}")
    if flagged:
        top = flagged[0]
        code = top_codes[0]["code"] if top_codes else None
        recs.append(rec(f"Review {top['segment']} with the risk and integration teams",
                        FAILURE_CODE_ACTIONS.get(code, "Compare its failure-code mix and configuration with peer segments."), "high"))
        recs.append(rec("Add a monitoring alert for segment failure-rate outliers",
                        "Alert when a segment's failure rate exceeds the overall rate by 3 standard errors on ≥ 50 eligible attempts.", "medium"))
    return hyps, recs


def for_quality(warnings: list[dict]) -> list[dict]:
    serious = [w for w in warnings if w["severity"] in ("high", "medium")]
    if not serious:
        return []
    names = ", ".join(f"{w['check']} ({w['affected']:,})" for w in serious[:4])
    return [rec("Resolve upstream data-quality defects", f"Open issues affect this analysis: {names}. See the Data Quality page for treatment details.", "medium")]
