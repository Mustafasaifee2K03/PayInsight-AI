"""Deterministic statistics: mix/within decomposition, significance tests, anomaly rules.

Mix decomposition (shift-share)
-------------------------------
For each segment s with baseline share p0, current share p1, baseline success
rate r0 and current success rate r1 (shares are of *eligible* attempts):

    within_s = p0 * (r1 - r0)
    mix_s    = (p1 - p0) * r1
    sum_s(within_s + mix_s) = sum(p1*r1) - sum(p0*r0) = R1 - R0   (exact identity)

Zero-volume handling: a segment absent in the baseline (p0 = 0) has an undefined
r0; we set r0 := r1 so its within effect is 0 and its entire impact is mix. A
segment absent in the current period (p1 = 0) has an undefined r1; we set
r1 := r0 so its disappearance is attributed to mix (-p0*r0). In both cases the
identity still holds exactly because the undefined term is multiplied by zero
in R0 or R1.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def two_proportion_z(s0: int, n0: int, s1: int, n1: int) -> float | None:
    if n0 == 0 or n1 == 0:
        return None
    p_pool = (s0 + s1) / (n0 + n1)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n0 + 1 / n1))
    if se == 0:
        return None
    return (s1 / n1 - s0 / n0) / se


def decompose(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """segments: [{segment, key, b_elig, b_succ, c_elig, c_succ, b_attempts, c_attempts}]"""
    B = sum(s["b_elig"] for s in segments)
    C = sum(s["c_elig"] for s in segments)
    if B == 0 or C == 0:
        return {"valid": False, "reason": "No eligible attempts in one of the periods.", "segments": []}
    R0 = sum(s["b_succ"] for s in segments) / B
    R1 = sum(s["c_succ"] for s in segments) / C
    out = []
    for s in segments:
        p0, p1 = s["b_elig"] / B, s["c_elig"] / C
        r0 = s["b_succ"] / s["b_elig"] if s["b_elig"] else None
        r1 = s["c_succ"] / s["c_elig"] if s["c_elig"] else None
        note = None
        if r0 is None and r1 is None:
            continue
        if r0 is None:
            r0_eff, r1_eff, note = r1, r1, "New in current period (no baseline volume): impact attributed to mix."
        elif r1 is None:
            r0_eff, r1_eff, note = r0, r0, "Absent in current period: impact attributed to mix."
        else:
            r0_eff, r1_eff = r0, r1
        within = p0 * (r1_eff - r0_eff)
        mix = (p1 - p0) * r1_eff
        out.append({
            "segment": s["segment"], "key": s.get("key"),
            "baseline_attempts": s.get("b_attempts", s["b_elig"]), "current_attempts": s.get("c_attempts", s["c_elig"]),
            "baseline_eligible": s["b_elig"], "current_eligible": s["c_elig"],
            "baseline_share_pct": 100 * p0, "current_share_pct": 100 * p1, "share_change_pp": 100 * (p1 - p0),
            "baseline_rate_pct": None if r0 is None else 100 * r0, "current_rate_pct": None if r1 is None else 100 * r1,
            "rate_change_pp": None if (r0 is None or r1 is None) else 100 * (r1 - r0),
            "within_effect_pp": 100 * within, "mix_effect_pp": 100 * mix, "contribution_pp": 100 * (within + mix),
            "low_sample": min(s["b_elig"], s["c_elig"]) < 30, "note": note,
        })
    within_total = sum(x["within_effect_pp"] for x in out)
    mix_total = sum(x["mix_effect_pp"] for x in out)
    direct = 100 * (R1 - R0)
    for x in out:
        x["share_of_change_pct"] = (100 * x["contribution_pp"] / direct) if abs(direct) > 1e-9 else None
    out.sort(key=lambda x: x["contribution_pp"] if direct < 0 else -x["contribution_pp"])
    return {
        "valid": True,
        "baseline_rate_pct": 100 * R0, "current_rate_pct": 100 * R1, "direct_change_pp": direct,
        "within_effect_pp": within_total, "mix_effect_pp": mix_total,
        "residual_pp": direct - (within_total + mix_total),
        "identity_holds": abs(direct - (within_total + mix_total)) < 1e-9,
        "segments": out,
    }


def segments_from_period_rows(rows: list[dict]) -> list[dict]:
    """Pivot rows of compile_period_segments (period, segment, segment_key, aggregates) into decompose() input."""
    seg: dict[tuple, dict] = {}
    for r in rows:
        k = (r.get("segment"), r.get("segment_key"))
        d = seg.setdefault(k, {"segment": r.get("segment"), "key": r.get("segment_key"), "b_elig": 0, "b_succ": 0, "c_elig": 0, "c_succ": 0,
                               "b_attempts": 0, "c_attempts": 0, "b_failed": 0, "c_failed": 0})
        p = "b" if r["period"] == "baseline" else "c"
        d[f"{p}_elig"] += r["eligible"] or 0
        d[f"{p}_succ"] += r["successful"] or 0
        d[f"{p}_attempts"] += r["attempts"] or 0
        d[f"{p}_failed"] += r["failed"] or 0
    return list(seg.values())


def daily_anomalies(daily: list[dict], value_key: str, scan_start: str, window: int = 14, threshold: float = 3.0,
                    min_points: int = 7) -> list[dict]:
    """Trailing-baseline z-score rule (heuristic, not a predictive model).

    For each day d >= scan_start: baseline = previous `window` days (excluding d);
    z = (x_d - mean) / std; flagged if |z| >= threshold.
    """
    if not daily:
        return []
    df = pd.DataFrame(daily).sort_values("day").reset_index(drop=True)
    x = df[value_key].astype(float)
    df["baseline_mean"] = x.shift(1).rolling(window, min_periods=min_points).mean()
    df["baseline_std"] = x.shift(1).rolling(window, min_periods=min_points).std(ddof=1)
    df["z"] = (x - df["baseline_mean"]) / df["baseline_std"].replace(0, float("nan"))
    df["flagged"] = df["z"].abs() >= threshold
    df = df[df["day"] >= scan_start]
    out = []
    for r in df.to_dict("records"):
        out.append({
            "day": r["day"], "value": r[value_key],
            "baseline_mean": None if pd.isna(r["baseline_mean"]) else float(r["baseline_mean"]),
            "baseline_std": None if pd.isna(r["baseline_std"]) else float(r["baseline_std"]),
            "z": None if pd.isna(r["z"]) else float(r["z"]),
            "flagged": bool(r["flagged"]) if not pd.isna(r["z"]) else False,
            "attempts": r.get("attempts"),
        })
    return out
