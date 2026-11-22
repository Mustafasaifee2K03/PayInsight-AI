"""Human-readable formatting helpers used in narratives."""
from __future__ import annotations


def inr_from_minor(minor: float | int | None) -> str:
    if minor is None:
        return "n/a"
    rupees = minor / 100.0
    if abs(rupees) >= 1e7:
        return f"₹{rupees / 1e7:,.2f} Cr"
    if abs(rupees) >= 1e5:
        return f"₹{rupees / 1e5:,.2f} L"
    return f"₹{rupees:,.0f}"


def pct(v: float | None, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}%"


def pp(v: float | None, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f} pp"


def rel(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def num(v: float | int | None) -> str:
    return "n/a" if v is None else f"{int(round(v)):,}"


def fmt_metric(value: float | None, unit: str) -> str:
    if unit == "percent":
        return pct(value)
    if unit == "currency_minor":
        return inr_from_minor(value)
    return num(value)
