"""Validated structured analysis plan produced by the deterministic planner."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Intent = Literal[
    "kpi",
    "breakdown",
    "ranking",
    "trend",
    "period_comparison",
    "contribution",
    "mix_decomposition",
    "diagnose",
    "anomaly_daily",
    "segment_outliers",
]
MetricName = Literal[
    "transaction_count",
    "successful_transactions",
    "failed_transactions",
    "pending_transactions",
    "success_rate",
    "failure_rate",
    "tpv",
    "avg_transaction_value",
]
Dimension = Literal["bank", "merchant", "merchant_category", "region", "payment_method", "failure_code", "day"]
Visualization = Literal["kpi", "bar_chart", "line_chart", "kpi_comparison", "decomposition", "table"]

INTENT_LABELS = {
    "kpi": "Single KPI",
    "breakdown": "Segment breakdown",
    "ranking": "Ranked segments",
    "trend": "Daily trend",
    "period_comparison": "Period-over-period comparison",
    "contribution": "Contribution to change",
    "mix_decomposition": "Mix vs. performance decomposition",
    "diagnose": "Root-cause investigation",
    "anomaly_daily": "Daily anomaly scan (statistical heuristic)",
    "segment_outliers": "Segment outlier scan (statistical heuristic)",
}


class TimeRange(BaseModel):
    start: date
    end: date  # inclusive
    label: str
    explicit: bool = True

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @model_validator(mode="after")
    def _check(self) -> "TimeRange":
        if self.end < self.start:
            raise ValueError("time range end precedes start")
        return self

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days,
                "label": self.label, "explicit": self.explicit}


class Filter(BaseModel):
    dimension: Dimension
    values: list[str] = Field(min_length=1, max_length=20)
    labels: list[str] = Field(default_factory=list)


class MatchedTerm(BaseModel):
    term: str
    meaning: str


class AnalysisPlan(BaseModel):
    intent: Intent
    metric: MetricName
    dimensions: list[Dimension] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list)
    time_range: TimeRange
    comparison: Literal["previous_period"] | None = None
    comparison_range: TimeRange | None = None
    visualization: Visualization = "table"
    sort: Literal["desc", "asc"] = "desc"
    limit: int = Field(default=10, ge=1, le=100)
    assumptions: list[str] = Field(default_factory=list)
    matched_terms: list[MatchedTerm] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0, le=1)

    @field_validator("dimensions")
    @classmethod
    def _unique_dims(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate dimensions")
        return v

    @model_validator(mode="after")
    def _check_comparison(self) -> "AnalysisPlan":
        if self.comparison == "previous_period":
            if self.comparison_range is None:
                raise ValueError("comparison_range required for previous_period comparison")
            if self.comparison_range.days != self.time_range.days:
                raise ValueError("comparison periods must have equal length")
            if self.comparison_range.end >= self.time_range.start:
                raise ValueError("comparison period must precede the current period")
        return self

    def summary_dict(self) -> dict:
        """Compact JSON form matching the documented planner output."""
        d = {
            "intent": self.intent,
            "metric": self.metric,
            "dimensions": self.dimensions,
            "filters": [f.model_dump() for f in self.filters],
            "time_range": self.time_range.as_dict(),
            "comparison": self.comparison,
            "visualization": self.visualization,
            "sort": self.sort,
            "limit": self.limit,
        }
        if self.comparison_range:
            d["comparison_range"] = self.comparison_range.as_dict()
        return d


class PlannerOutcome(BaseModel):
    status: Literal["planned", "needs_clarification", "rejected"]
    plan: AnalysisPlan | None = None
    message: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    matched_terms: list[MatchedTerm] = Field(default_factory=list)
