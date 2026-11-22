"""Deterministic natural-language analysis planner (no LLM, no external API).

Pipeline: normalise text -> reject write intents -> extract entity filters
(bank / merchant / method / category / region / failure code values from the
live dimension catalogue) -> detect metric, dimensions, time range, comparison,
ranking direction -> choose intent -> build and validate an ``AnalysisPlan``.

Every default the planner applies is recorded as an explicit assumption that is
shown to the user. When the question has no recognisable metric or analytical
intent, the planner asks for clarification instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from pydantic import ValidationError

from ..schemas.plan import AnalysisPlan, Filter, MatchedTerm, PlannerOutcome, TimeRange
from .metrics import METRICS

ENGINE_NAME = "Local deterministic analysis engine — No external AI API"
ENGINE_VERSION = "1.0"

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20,
    "twenty one": 21, "twenty eight": 28, "thirty": 30, "forty five": 45, "sixty": 60,
}
# Three-letter month keys; 'may' is only matched when followed by a year (see _parse_time).
MAX_RANK_LIMIT = 100
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
MAX_RELATIVE_UNITS = 36_500
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
# Time language the parser does not support. Without this check such questions silently ran on the
# full window with the false assumption "No period given" (hardening iteration 9).
UNPARSED_TIME = re.compile(r"(?<!top )(?<!bottom )\b(?:19|20)\d{2}\b|\bquarters?\b|\bytd\b|\byear to date\b|\bfiscal\b|\bfy\s?\d{2,4}\b|"
                           r"\bsame (?:period|time|day|week|month)\b|\bweek of\b|\bsince\b|\bh[12]\b|\bhalf year\b")
UNSUPPORTED_TIME = re.compile(r"\bsame (?:period|time|day|week|month|quarter)(?: (?:of |as )?last year)?\b|\byear over year\b|\byoy\b|"
                              r"\byear to date\b|\bytd\b")
FOREIGN_CURRENCY = re.compile(r"\b(usd|dollars?|eur|euros?|gbp|pounds?|aed|dirhams?|sgd|jpy|yen)\b")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

SUGGESTIONS = [
    "What is the overall success rate?",
    "Compare payment success rates by bank over the last 7 days",
    "Why did payment success rate decline?",
    "Which payment methods have the highest failure rates?",
    "Show daily transaction trends",
    "What are the main failure codes?",
]

WRITE_PATTERN = re.compile(
    r"\b(delete|drop|insert|truncate|alter|update the|update all|remove all|overwrite|create table|grant|revoke|attach|pragma)\b"
)

# (metric, pattern) in priority order — first match wins.
METRIC_PATTERNS: list[tuple[str, str]] = [
    ("avg_transaction_value", r"average (transaction|ticket|order|payment) (value|size|amount)|avg\.? (ticket|transaction)( value| size)?|\bats\b|\baov\b|average ticket"),
    ("tpv", r"\btpv\b|\bgmv\b|total (payment |transaction )?value|payment value|transaction value|processed value|\brevenue\b|amount processed|how much (money|value)|total amount|value of (payments|transactions)|money (processed|collected)"),
    ("failure_rate", r"failure rates?|fail(ure)? ratio|\bfail rates?|decline rates?|error rates?|rejection rates?|failure percentage|failure %"),
    ("success_rate", r"success rates?|success ratio|approval rates?|authori[sz]ation rates?|conversion( rates?)?|success percentage|success %|\bsr\b|payment success"),
    ("failed_transactions", r"failed (transactions?|payments?|transaction volumes?|volumes?|counts?|txns?|attempts?)|number of failed|how many failed|\bfailures\b|declined (transactions|payments)|failed volume"),
    ("successful_transactions", r"successful (transactions?|payments?)|number of successful|how many successful|succeeded"),
    ("pending_transactions", r"\bpending\b"),
    ("transaction_count", r"how many|number of (transactions|payments)|transaction (counts?|volumes?|trends?)|payment (attempts|volumes?|counts?)|\battempts\b|\bvolumes?\b|count of transactions|transactions (occurred|happened|processed)|total transactions|daily transactions|transactions per day"),
]
PERFORMANCE_PATTERN = r"\bperform\w*|\bbest\b|\bworst\b|\bhealth\w*|\bdoing\b|\bstrongest\b|\bweakest\b"

DIMENSION_PATTERNS: list[tuple[str, str]] = [
    ("failure_code", r"failure (codes?|reasons?)|decline (codes?|reasons?)|error codes?|reasons? (for|of|behind) (the )?(failures?|declines?)|response codes?|why (are |do )?(payments|transactions) fail"),
    ("merchant_category", r"merchant categor(y|ies)|\bcategor(y|ies)\b|\bverticals?\b|\bindustr(y|ies)\b|\bmcc\b|business types?"),
    ("payment_method", r"payment methods?|\bmethods?\b|payment modes?|modes? of payment|\binstruments?\b|payment (types?|options?)|\bchannels?\b|\bupi vs\b|\bcards? vs\b"),
    ("merchant", r"\bmerchants?\b|\bsellers?\b|\bstores?\b"),
    ("bank", r"\bbanks?\b|\bissuers?\b|issuing bank|\bremitters?\b"),
    ("region", r"\bregions?\b|\bregional\b|\bgeograph(y|ies|ic)\b|\bzones?\b|\blocations?\b"),
]

CHANGE_DOWN = r"declin\w*|\bdrop\w*|\bfall\w*|\bfell\b|decreas\w*|deteriorat\w*|worsen\w*|went down|\bdip\w*|\breduc\w*|\bslump\w*"
CHANGE_UP = r"increas\w*|improv\w*|\brise\b|\brose\b|went up|\bjump\w*|\bspike?d?\b|\bgrew\b|\bgrowth\b"
CHANGE_ANY = r"\bchang\w*|\bshift\w*|\bmov\w*"
COMPARISON = (r"\bcompar\w*.*\b(previous|prior|preceding|last|earlier)\b.*\b(period|week|weeks|days|month)\b"
              r"|\bvs\.? (the )?(previous|prior|last)|\bversus\b|week over week|\bwow\b|period over period"
              r"|(previous|prior|preceding) (period|week|\d+ days)|across periods|over periods|than (the )?(previous|prior|last)"
              r"|with the (previous|prior|preceding)|period comparison|\bpop\b")
TREND = r"\btrends?\b|\bdaily\b|per day|by day|each day|day by day|over time|time series|\btimeline\b|day wise|daywise"
RANKING = r"\btop\b|\bhighest\b|\blowest\b|\bbest\b|\bworst\b|\bmost\b|\bleast\b|\bwhich\b|\brank\w*|\bleading\b|\bbottom\b|\blargest\b|\bbiggest\b|\bsmallest\b|\bweakest\b|\bstrongest\b"
BREAKDOWN = r"\bby\b|\bbreak ?down\b|\bsplit\b|\bdistribution\b|\bper\b|\bacross\b|\beach\b|\bwise\b|\bsegment\w*|\bcompar\w*|\blevel\b"
ANOMALY = r"\bunusual\b|anomal\w*|\boutliers?\b|\babnormal\w*|\bsuspicious\b|\bunexpected\b|\bodd\b|\birregular\b"
MIX = r"\bmix\b|\bcomposition\b|share (shift|change)|shift in (share|traffic)|traffic shift|\bshares?\b of (traffic|volume|transactions)"
CONTRIBUTION = r"contribut\w*|\bdrivers?\b|\bdrove\b|\bdriving\b|responsible|account(ed)? for|\bexplain\w*|\bculprit\w*"
WHY = r"\bwhy\b|root cause|what caused|\bcause[sd]?\b|reason (for|behind) the|what happened|\bdiagnos\w*|\binvestigat\w*"
LOWER_WORDS = r"\blowest\b|\bleast\b|\bbottom\b|\bsmallest\b|\bfewest\b"
HIGHER_WORDS = r"\bhighest\b|\bmost\b|\btop\b|\blargest\b|\bbiggest\b|\bmaximum\b"


@dataclass
class CatalogEntry:
    dimension: str
    value_id: str
    label: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class PlannerContext:
    data_start: date
    data_end: date
    catalog: list[CatalogEntry]


def normalise(question: str) -> str:
    q = question.lower().strip()
    q = re.sub(r"[‘’`]", "'", q)
    q = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", q)  # bank-level -> bank level
    q = re.sub(r"[^a-z0-9%\-\s'./]", " ", q)
    for words, n in sorted(WORD_NUMBERS.items(), key=lambda kv: -len(kv[0])):
        q = re.sub(rf"\b{words}\b", str(n), q)
    return re.sub(r"\s+", " ", q).strip()


def _search(pattern: str, text: str) -> re.Match | None:
    return re.search(pattern, text)


def _blank(text: str, span: tuple[int, int]) -> str:
    return text[: span[0]] + " " * (span[1] - span[0]) + text[span[1]:]


def _extract_entities(q: str, catalog: list[CatalogEntry]) -> tuple[dict[str, list[CatalogEntry]], str, list[MatchedTerm]]:
    found: dict[str, list[CatalogEntry]] = {}
    terms: list[MatchedTerm] = []
    candidates: list[tuple[str, CatalogEntry]] = []
    for e in catalog:
        for alias in {normalise(e.label), *[normalise(a) for a in e.aliases]}:
            candidates.append((alias, e))
    candidates.sort(key=lambda c: -len(c[0]))  # longest match first
    for alias, e in candidates:
        m = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q)
        if m:
            bucket = found.setdefault(e.dimension, [])
            if all(x.value_id != e.value_id for x in bucket):
                bucket.append(e)
                terms.append(MatchedTerm(term=m.group(0), meaning=f"{e.dimension} = {e.label}"))
            q = _blank(q, m.span())
    return found, q, terms


def _clip(start: date, end: date, ctx: PlannerContext, label: str, assumptions: list[str], explicit: bool = True) -> TimeRange | None:
    if end < ctx.data_start or start > ctx.data_end:
        return None
    s, e = max(start, ctx.data_start), min(end, ctx.data_end)
    if (s, e) != (start, end):
        assumptions.append(f"Requested period {start} to {end} was clipped to the available data ({s} to {e}).")
    return TimeRange(start=s, end=e, label=label, explicit=explicit)


def _parse_time(q: str, ctx: PlannerContext, assumptions: list[str], terms: list[MatchedTerm]) -> tuple[TimeRange | None, bool, str | None]:
    """Return (time_range, found_any, error_message). Relative phrases are anchored to the
    last day of available data (ctx.data_end), never to the machine clock."""
    anchor = ctx.data_end
    unsupported = UNSUPPORTED_TIME.search(q)
    if unsupported:  # checked first: "same period last year" must not be read as "last year"
        return None, True, (f"'{unsupported.group(0)}' comparisons are not supported (the dataset covers {ctx.data_start} to "
                            f"{ctx.data_end}). Try 'compare the last 7 days with the previous 7 days'.")

    def rel_days(n: int, label: str, term: str):
        terms.append(MatchedTerm(term=term, meaning=f"time range = {label} (anchored to {anchor})"))
        return _clip(anchor - timedelta(days=n - 1), anchor, ctx, label, assumptions)

    dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", q)
    if dates:
        try:
            ds = sorted(date.fromisoformat(d) for d in dates[:2])
        except ValueError:
            return None, True, "One of the dates in the question is not a valid calendar date (use YYYY-MM-DD)."
        start, end = ds[0], ds[-1]
        terms.append(MatchedTerm(term=" / ".join(dates[:2]), meaning=f"time range = {start} to {end}"))
        tr = _clip(start, end, ctx, f"{start} to {end}", assumptions)
        return tr, True, None if tr else f"No data in that period. Data is available from {ctx.data_start} to {ctx.data_end}."

    m = re.search(r"\b(last|past|previous|recent|trailing|latest)\s+(\d+)\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b", q)
    if m:
        n = min(int(m.group(2)[:7]), MAX_RELATIVE_UNITS)  # bounded: "last 999999999 days" overflowed nothing but was ignored
        unit = m.group(3)
        days = n * UNIT_DAYS[unit.rstrip("s")]
        if days < 1:
            return None, True, "The time range must be at least one day."
        return rel_days(days, f"last {days} days", m.group(0)), True, None
    m = re.search(r"\b(last|past|previous|this)\s+(quarter|year)\b", q)
    if m:
        days = UNIT_DAYS[m.group(2)]
        return rel_days(days, f"last {days} days", m.group(0)), True, None
    m = re.search(r"\b(last|past|this|previous|recent)\s+(week|fortnight|month)\b", q)
    if m:
        days = {"week": 7, "fortnight": 14, "month": 30}[m.group(2)]
        return rel_days(days, f"last {days} days", m.group(0)), True, None
    if re.search(r"\byesterday\b", q):
        d = anchor - timedelta(days=1)
        terms.append(MatchedTerm(term="yesterday", meaning=f"time range = {d} (day before last data day)"))
        return TimeRange(start=d, end=d, label=f"{d}"), True, None
    if re.search(r"\btoday\b", q):
        terms.append(MatchedTerm(term="today", meaning=f"time range = {anchor} (last data day)"))
        return TimeRange(start=anchor, end=anchor, label=f"{anchor}"), True, None
    m = re.search(r"\b(january|february|march|april|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|may(?=\s+\d{4}))\b(\s+(\d{4}))?", q)
    if m:
        month = MONTHS[m.group(1)[:3]]
        year = int(m.group(3)) if m.group(3) else (ctx.data_end.year if month <= ctx.data_end.month else ctx.data_end.year - 1)
        start = date(year, month, 1)
        end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        terms.append(MatchedTerm(term=m.group(0).strip(), meaning=f"time range = {start:%B %Y}"))
        tr = _clip(start, end, ctx, f"{start:%B %Y}", assumptions)
        return tr, True, None if tr else f"No data for {start:%B %Y}. Data is available from {ctx.data_start} to {ctx.data_end}."
    m = re.search(r"\bq([1-4])(?:\s+(?:of\s+)?(\d{4}))?\b|\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+(?:of\s+)?(\d{4}))?\b", q)
    if m:
        qn = int(m.group(1)) if m.group(1) else QUARTER_WORDS[m.group(3)]
        year_txt = m.group(2) or m.group(4)
        year = int(year_txt) if year_txt else ctx.data_end.year
        start = date(year, 3 * qn - 2, 1)
        end = date(year + (qn == 4), (3 * qn) % 12 + 1, 1) - timedelta(days=1)
        label = f"Q{qn} {year}"
        terms.append(MatchedTerm(term=m.group(0), meaning=f"time range = {label} ({start} to {end})"))
        if not year_txt:
            assumptions.append(f"No year given for Q{qn}; assumed {year} (the year of the latest data).")
        tr = _clip(start, end, ctx, label, assumptions)
        return tr, True, None if tr else f"No data for {label}. Data is available from {ctx.data_start} to {ctx.data_end}."
    m = re.search(r"\b(?:in|during|for|of|year)\s+((?:19|20)\d{2})\b", q)
    if m:
        year = int(m.group(1))
        terms.append(MatchedTerm(term=m.group(0), meaning=f"time range = calendar year {year}"))
        tr = _clip(date(year, 1, 1), date(year, 12, 31), ctx, f"{year}", assumptions)
        return tr, True, None if tr else f"No data for {year}. Data is available from {ctx.data_start} to {ctx.data_end}."
    if re.search(r"\ball time\b|\boverall period\b|\bentire\b|\bwhole period\b|\bfull period\b|\ball data\b|\bso far\b", q):
        terms.append(MatchedTerm(term="all time", meaning="time range = full available window"))
        return TimeRange(start=ctx.data_start, end=ctx.data_end, label="full available window"), True, None
    leftover = UNPARSED_TIME.search(q)
    if leftover:
        return None, True, (f"I could not interpret the time period '{leftover.group(0).strip()}'. Supported forms: 'last N days/weeks/"
                            "months/quarters', 'Q3 2025', a month name, 'in 2025', or explicit dates (YYYY-MM-DD).")
    return None, False, None


def _detect_metric(q: str, terms: list[MatchedTerm]) -> str | None:
    for metric, pattern in METRIC_PATTERNS:
        m = _search(pattern, q)
        if m:
            terms.append(MatchedTerm(term=m.group(0), meaning=f"metric = {METRICS[metric].label}"))
            return metric
    return None


def _detect_dimensions(q: str, terms: list[MatchedTerm]) -> list[str]:
    dims: list[tuple[int, str]] = []
    text = q
    for dim, pattern in DIMENSION_PATTERNS:
        m = _search(pattern, text)
        if m:
            dims.append((m.start(), dim))
            terms.append(MatchedTerm(term=m.group(0), meaning=f"dimension = {dim}"))
            text = _blank(text, m.span())
    return [d for _, d in sorted(dims)][:2]


def plan_question(question: str, ctx: PlannerContext) -> PlannerOutcome:
    raw = (question or "").strip()
    if len(raw) < 3:
        return PlannerOutcome(status="needs_clarification", message="Please type a question about payments performance.", suggestions=SUGGESTIONS)
    if len(raw) > 500:
        return PlannerOutcome(status="rejected", message="Questions are limited to 500 characters.")
    q = normalise(raw)
    if WRITE_PATTERN.search(q):
        return PlannerOutcome(
            status="rejected",
            message="PayInsight AI is a read-only analytics assistant. Requests to modify, delete or administer data are not supported.",
            suggestions=SUGGESTIONS[:3],
        )

    terms: list[MatchedTerm] = []
    assumptions: list[str] = []
    entities, q_rest, ent_terms = _extract_entities(q, ctx.catalog)
    terms.extend(ent_terms)

    time_range, time_found, time_error = _parse_time(q_rest, ctx, assumptions, terms)
    if time_error:
        return PlannerOutcome(status="needs_clarification", message=time_error, suggestions=SUGGESTIONS[:3], matched_terms=terms)

    metric = _detect_metric(q_rest, terms)
    dims = _detect_dimensions(q_rest, terms)

    has = lambda p: bool(_search(p, q_rest))  # noqa: E731
    is_down, is_up, is_change = has(CHANGE_DOWN), has(CHANGE_UP), has(CHANGE_ANY)
    is_comparison = has(COMPARISON)
    is_why = has(WHY)

    # Multiple named values of one dimension ("UPI vs credit card") imply a breakdown by it.
    for dim, vals in entities.items():
        if len(vals) > 1 and dim not in dims and len(dims) < 2:
            dims.append(dim)

    # --- intent selection (ordered rules) ---------------------------------
    if has(ANOMALY):
        intent = "segment_outliers" if any(d in dims for d in ("merchant", "bank", "payment_method", "merchant_category", "region")) else "anomaly_daily"
    elif has(MIX) and (is_down or is_up or is_change or is_why or has(r"\bmix\b|composition")):
        intent = "mix_decomposition"
    elif has(CONTRIBUTION) and (is_down or is_up or is_change or has(r"\bdecline|\bdrop")):
        intent = "contribution" if dims else "diagnose"
    elif is_why and (is_down or is_up or is_change or metric in ("success_rate", "failure_rate", "failed_transactions")):
        intent = "diagnose"
    elif is_comparison or ((is_down or is_up or is_change) and not has(TREND)):
        intent = "period_comparison"
    elif has(TREND):
        intent = "trend"
    elif dims and has(RANKING):
        intent = "ranking"
    elif dims and (has(BREAKDOWN) or "failure_code" in dims or metric is None):
        intent = "breakdown"
    elif dims:
        intent = "breakdown"
    elif metric:
        intent = "kpi"
    elif has(PERFORMANCE_PATTERN) and entities:
        intent = "kpi"
    else:
        return PlannerOutcome(
            status="needs_clarification",
            message=("I could not identify a metric or analysis in that question. Try asking about success rate, "
                     "failure rate, transaction count, TPV, failure codes or trends — optionally by bank, merchant, "
                     "payment method, category or region."),
            suggestions=SUGGESTIONS,
            matched_terms=terms,
        )

    # --- metric defaults (always explicit) ---------------------------------
    if "failure_code" in dims:
        if metric not in (None, "failed_transactions"):
            assumptions.append("Failure codes only exist on FAILED transactions, so the breakdown counts failed transactions.")
        metric = "failed_transactions"
    if metric is None:
        if intent == "trend" and has(r"\btransactions?\b|\bpayments?\b|\bvolume"):
            metric = "transaction_count"
            assumptions.append("No metric named; 'transaction trends' interpreted as daily transaction count.")
        else:
            metric = "success_rate"
            reason = "'performance'" if has(PERFORMANCE_PATTERN) else "no metric was named"
            assumptions.append(f"Using payment success rate as the metric because {reason} (success rate is the primary payments health metric).")
    if intent in ("contribution", "mix_decomposition", "diagnose") and metric not in ("success_rate", "failure_rate"):
        assumptions.append(f"{INTENT_TEXT[intent]} is performed on payment success rate (requested metric '{METRICS[metric].label}' is shown as context).")
        metric = "success_rate"

    if intent == "mix_decomposition" and not dims:
        dims = ["payment_method"]
        assumptions.append("No segment dimension named for the mix analysis; using payment method.")
    if intent == "segment_outliers":
        dims = [next(d for d in dims if d != "failure_code")]
    if intent in ("contribution", "mix_decomposition", "period_comparison", "segment_outliers", "ranking") and len(dims) > 1:
        dims = dims[:1]

    # --- time range defaults ------------------------------------------------
    needs_comparison = intent in ("period_comparison", "contribution", "mix_decomposition", "diagnose")
    if time_range is None:
        if needs_comparison:
            time_range = TimeRange(start=ctx.data_end - timedelta(days=6), end=ctx.data_end, label="last 7 days", explicit=False)
            assumptions.append(f"No period given; comparing the last 7 days of data ({time_range.start} to {time_range.end}) with the previous 7 days.")
        elif intent == "anomaly_daily":
            time_range = TimeRange(start=ctx.data_end - timedelta(days=13), end=ctx.data_end, label="last 14 days", explicit=False)
            assumptions.append(f"No period given; scanning the last 14 days ({time_range.start} to {time_range.end}) against a trailing 14-day baseline.")
        else:
            time_range = TimeRange(start=ctx.data_start, end=ctx.data_end, label="full available window", explicit=False)
            assumptions.append(f"No period given; using the full available data window ({ctx.data_start} to {ctx.data_end}).")

    comparison_range = None
    if needs_comparison:
        n = time_range.days
        cend = time_range.start - timedelta(days=1)
        cstart = cend - timedelta(days=n - 1)
        if cstart < ctx.data_start:
            return PlannerOutcome(
                status="needs_clarification",
                message=(f"An equal-length comparison needs {n} days of history before {time_range.start}, but data starts on "
                         f"{ctx.data_start}. Please choose a shorter or later period (e.g. 'last 7 days')."),
                suggestions=["Compare the last 7 days with the previous 7 days", "Compare the last 14 days with the previous 14 days"],
                matched_terms=terms,
            )
        comparison_range = TimeRange(start=cstart, end=cend, label=f"previous {n} days", explicit=time_range.explicit)

    # --- filters --------------------------------------------------------------
    filters = [Filter(dimension=d, values=[e.value_id for e in vals], labels=[e.label for e in vals]) for d, vals in entities.items()]

    # --- ranking direction / limit -----------------------------------------------
    m_def = METRICS[metric]
    sort = "desc"
    if has(LOWER_WORDS):
        sort = "asc"
    elif has(r"\bworst\b|\bweakest\b"):
        sort = "asc" if m_def.higher_is_better else "desc"
    elif has(r"\bbest\b|\bstrongest\b"):
        sort = "desc" if m_def.higher_is_better else "asc"
    limit_m = re.search(r"\btop\s+(\d+)\b|\bbottom\s+(\d+)\b", q_rest)
    limit = int(next(g for g in limit_m.groups() if g)) if limit_m else (10 if intent == "ranking" else 50)
    if limit > MAX_RANK_LIMIT:
        assumptions.append(f"Requested top {limit:,}; showing at most {MAX_RANK_LIMIT} segments.")
        limit = MAX_RANK_LIMIT
    if limit < 1:
        return PlannerOutcome(status="needs_clarification", message="The number of segments to show must be at least 1.",
                              suggestions=SUGGESTIONS[:3], matched_terms=terms)
    if metric in ("tpv", "avg_transaction_value") and FOREIGN_CURRENCY.search(q_rest):
        assumptions.append("Amounts are reported in INR only. Non-INR transactions are excluded from value metrics and never converted (there is no FX table).")

    visualization = {
        "kpi": "kpi", "trend": "line_chart", "breakdown": "bar_chart", "ranking": "bar_chart",
        "period_comparison": "kpi_comparison", "contribution": "decomposition", "mix_decomposition": "decomposition",
        "diagnose": "decomposition", "anomaly_daily": "line_chart", "segment_outliers": "bar_chart",
    }[intent]

    confidence = max(0.35, 0.95 - 0.12 * len(assumptions))
    try:
        plan = AnalysisPlan(
            intent=intent, metric=metric, dimensions=dims, filters=filters, time_range=time_range,
            comparison="previous_period" if needs_comparison else None, comparison_range=comparison_range,
            visualization=visualization, sort=sort, limit=limit, assumptions=assumptions,
            matched_terms=terms, confidence=round(confidence, 2),
        )
    except ValidationError as exc:  # defensive: planner bug or impossible combination
        return PlannerOutcome(status="needs_clarification", message=f"Could not build a valid analysis plan: {exc.errors()[0]['msg']}",
                              suggestions=SUGGESTIONS, matched_terms=terms)
    return PlannerOutcome(status="planned", plan=plan, matched_terms=terms)


INTENT_TEXT = {
    "contribution": "Contribution analysis",
    "mix_decomposition": "Mix decomposition",
    "diagnose": "Root-cause investigation",
}
