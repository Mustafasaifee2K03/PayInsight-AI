"""Deterministic synthetic payments data generator.

Every database is fully determined by (profile, row_count, seed). The date
window is fixed in configuration and never derived from the machine clock.

Profiles
--------
baseline            Stable performance (scenarios A, C, F).
bank_decline        Deccan Commercial Bank (B03) loses ~22 pp of success
                    probability in the last 7 days, mostly BANK_TIMEOUT (B).
mix_shift           Per-method success probabilities are unchanged but the
                    last 7 days shift share from UPI to Net Banking (D).
data_quality        Baseline plus injected duplicates, missing / orphan
                    dimension keys, invalid statuses, amounts, timestamps (E).
source_discrepancy  Baseline plus bank-reported daily counts that disagree with
                    transaction-derived counts for one bank, and one missing
                    report (G).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from . import reference_data as ref
from .schema import DDL, POST_LOAD_DDL

log = logging.getLogger("payinsight.generator")

PROFILES = ("baseline", "bank_decline", "mix_shift", "data_quality", "source_discrepancy")
BATCH_SIZE = 5_000

# Scenario E injected defects (counts are of distinct transactions affected).
QUALITY_INJECTION = {
    "duplicate_versions": 300,
    "missing_merchant_id": 120,
    "missing_bank_id": 80,
    "missing_payment_method_id": 40,
    "orphan_merchant_id": 30,
    "invalid_status": 15,
    "invalid_amount": 20,
    "invalid_timestamp": 10,
    "failed_without_failure_code": 25,
}


@dataclass(frozen=True)
class GenerationResult:
    profile: str
    path: str
    raw_rows: int
    canonical_rows: int
    seconds: float


def _daily_weights(rng: np.random.Generator, start: date, days: int) -> np.ndarray:
    w = np.empty(days)
    for i in range(days):
        d = start + timedelta(days=i)
        weekend = 1.15 if d.weekday() >= 5 else 1.0
        trend = 1.0 + 0.002 * i
        month_start = 1.10 if d.day <= 3 else 1.0  # salary-day / bill-payment bump
        w[i] = weekend * trend * month_start
    w *= rng.normal(1.0, 0.04, size=days).clip(0.85, 1.15)
    return w / w.sum()


def _generate_transactions(profile: str, n: int, start: date, days: int, rng: np.random.Generator):
    """Return column arrays for ``n`` canonical transactions, sorted by timestamp."""
    merchants = ref.MERCHANTS
    banks = ref.BANKS
    methods = ref.PAYMENT_METHODS

    day_idx = rng.choice(days, size=n, p=_daily_weights(rng, start, days))
    hours = rng.choice(24, size=n, p=np.array(ref.HOURLY_WEIGHTS) / sum(ref.HOURLY_WEIGHTS))
    secs = hours * 3600 + rng.integers(0, 3600, size=n)
    order = np.lexsort((secs, day_idx))
    day_idx, secs = day_idx[order], secs[order]

    m_w = np.array([m[7] for m in merchants]); m_w = m_w / m_w.sum()
    merchant_idx = rng.choice(len(merchants), size=n, p=m_w)
    b_w = np.array([b[5] for b in banks]); b_w = b_w / b_w.sum()
    bank_idx = rng.choice(len(banks), size=n, p=b_w)

    base_shares = np.array([m[4] for m in methods])
    method_idx = rng.choice(len(methods), size=n, p=base_shares / base_shares.sum())
    in_last_week = day_idx >= days - ref.DECLINE_DAYS
    # Draw the shifted mix for every profile so all profiles share one RNG stream
    # and differ only by their seeded effect.
    shift = np.array([ref.MIX_SHIFT_SHARES[m[0]] for m in methods])
    shifted_methods = rng.choice(len(methods), size=n, p=shift / shift.sum())
    if profile == "mix_shift":
        method_idx = np.where(in_last_week, shifted_methods, method_idx)

    p_success = (
        np.array([m[5] for m in methods])[method_idx]
        + np.array([b[6] for b in banks])[bank_idx]
        + np.array([m[8] for m in merchants])[merchant_idx]
    )
    decline_mask = np.zeros(n, dtype=bool)
    if profile == "bank_decline":
        decline_bank = [b[0] for b in banks].index(ref.DECLINE_BANK_ID)
        decline_mask = in_last_week & (bank_idx == decline_bank)
        p_success = np.where(decline_mask, p_success - ref.DECLINE_SUCCESS_DROP, p_success)
    p_success = p_success.clip(0.05, 0.995)

    u = rng.random(n)
    pending = rng.random(n) < 0.015
    success = (~pending) & (u < p_success)
    failed = (~pending) & (~success)
    status = np.where(pending, "PENDING", np.where(success, "SUCCESS", "FAILED"))

    # Failure codes per method; seeded decline failures are dominated by BANK_TIMEOUT.
    failure_code = np.full(n, None, dtype=object)
    codes = np.array(ref.FAILURE_CODES, dtype=object)
    for mi, m in enumerate(methods):
        sel = failed & (method_idx == mi)
        w = np.array(ref.FAILURE_CODE_WEIGHTS[m[0]]); w = w / w.sum()
        failure_code[sel] = rng.choice(codes, size=int(sel.sum()), p=w)
    risky = failed & (np.array([m[4] for m in merchants])[merchant_idx] == "HIGH")
    flip = risky & (rng.random(n) < 0.45)
    failure_code[flip] = "RISK_DECLINED"
    timeout_draw = rng.random(n)
    if profile == "bank_decline":
        extra = failed & decline_mask & (timeout_draw < 0.70)
        failure_code[extra] = "BANK_TIMEOUT"

    # Amounts in minor units by merchant category (lognormal).
    cat_of_merchant = np.array([m[2] for m in merchants], dtype=object)[merchant_idx]
    amount_minor = np.zeros(n, dtype=np.int64)
    for cat, (median, sigma) in ref.MERCHANT_CATEGORIES.items():
        sel = cat_of_merchant == cat
        vals = rng.lognormal(np.log(median), sigma, size=int(sel.sum()))
        amount_minor[sel] = np.maximum(np.round(vals * 100), 1000)
    currency = np.full(n, "INR", dtype=object)
    usd = (cat_of_merchant == "Travel") & (rng.random(n) < 0.03)
    currency[usd] = "USD"
    amount_minor[usd] = np.maximum(np.round(amount_minor[usd] / 84.0), 500)

    update_lag = np.where(pending, 0, rng.integers(1, 120, size=n))
    return {
        "day_idx": day_idx,
        "secs": secs,
        "merchant_idx": merchant_idx,
        "bank_idx": bank_idx,
        "method_idx": method_idx,
        "status": status,
        "failure_code": failure_code,
        "amount_minor": amount_minor,
        "currency": currency,
        "update_lag": update_lag,
    }


def _fmt_ts(start: date, day: int, secs: int) -> str:
    dt = datetime(start.year, start.month, start.day) + timedelta(days=int(day), seconds=int(secs))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_database(path: Path | str, profile: str, row_count: int, seed: int, start: date, days: int) -> GenerationResult:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}")
    t0 = time.perf_counter()
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    rng = np.random.default_rng(seed)
    cols = _generate_transactions(profile, row_count, start, days, rng)
    end_date = start + timedelta(days=days - 1)

    merchants, banks, methods = ref.MERCHANTS, ref.BANKS, ref.PAYMENT_METHODS
    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript(DDL)
        conn.executemany("INSERT INTO merchants VALUES (?,?,?,?,?,?)", [m[:6] for m in merchants])
        conn.executemany("INSERT INTO banks VALUES (?,?,?,?,?)", [b[:5] for b in banks])
        conn.executemany("INSERT INTO payment_methods VALUES (?,?,?,?)", [m[:4] for m in methods])

        # Settlements: one batch per merchant per transaction day for successful INR txns (T+1).
        settle_key = {}
        settle_amount: dict[str, int] = {}
        n = row_count
        for i in range(n):
            if cols["status"][i] == "SUCCESS" and cols["currency"][i] == "INR":
                m = merchants[cols["merchant_idx"][i]]
                sdate = start + timedelta(days=int(cols["day_idx"][i]) + 1)
                sid = f"S{m[0]}{sdate:%Y%m%d}"
                settle_key[i] = sid
                settle_amount[sid] = settle_amount.get(sid, 0) + int(cols["amount_minor"][i])
        settlement_rows = []
        for sid, amt in sorted(settle_amount.items()):
            mid = sid[1:5]
            sdate = datetime.strptime(sid[5:], "%Y%m%d").date()
            sbank = next(m[6] for m in merchants if m[0] == mid)
            status = "PENDING" if sdate > end_date else "SETTLED"
            settlement_rows.append((sid, mid, sbank, sdate.isoformat(), amt, status))
        conn.executemany("INSERT INTO settlements VALUES (?,?,?,?,?,?)", settlement_rows)

        rows = []
        for i in range(n):
            ts = _fmt_ts(start, cols["day_idx"][i], cols["secs"][i])
            upd = _fmt_ts(start, cols["day_idx"][i], int(cols["secs"][i]) + int(cols["update_lag"][i]))
            rows.append(
                (
                    f"TXN{i + 1:08d}",
                    merchants[cols["merchant_idx"][i]][0],
                    banks[cols["bank_idx"][i]][0],
                    methods[cols["method_idx"][i]][0],
                    ts,
                    int(cols["amount_minor"][i]),
                    cols["currency"][i],
                    cols["status"][i],
                    cols["failure_code"][i],
                    settle_key.get(i),
                    upd,
                )
            )
        insert_sql = (
            "INSERT INTO transactions_raw (transaction_id, merchant_id, bank_id, payment_method_id, "
            "transaction_timestamp, amount_minor, currency, status, failure_code, settlement_id, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        )
        for b in range(0, len(rows), BATCH_SIZE):
            conn.executemany(insert_sql, rows[b : b + BATCH_SIZE])
        conn.commit()

        if profile == "data_quality":
            _inject_quality_issues(conn, rows, rng)

        conn.executescript(POST_LOAD_DDL)
        _build_bank_reports(conn, profile, start, days)
        canonical = conn.execute("SELECT COUNT(*) FROM transactions_canonical").fetchone()[0]
        raw = conn.execute("SELECT COUNT(*) FROM transactions_raw").fetchone()[0]
        meta = {
            "profile": profile,
            "seed": str(seed),
            "requested_rows": str(row_count),
            "raw_rows": str(raw),
            "canonical_rows": str(canonical),
            "data_start_date": start.isoformat(),
            "data_end_date": end_date.isoformat(),
            "timezone": "IST (naive local timestamps)",
            "generator_version": "1.0",
        }
        conn.executemany("INSERT INTO dataset_metadata VALUES (?,?)", list(meta.items()))
        conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)
    secs = time.perf_counter() - t0
    log.info("database_generated", extra={"profile": profile, "rows": raw, "seconds": round(secs, 2)})
    return GenerationResult(profile, str(path), raw, canonical, secs)


def _inject_quality_issues(conn: sqlite3.Connection, rows: list[tuple], rng: np.random.Generator) -> None:
    """Scenario E: simulate a defective upstream batch (FK enforcement disabled for this feed)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    n = len(rows)
    perm = rng.permutation(n)
    sizes = list(QUALITY_INJECTION.values())
    offsets = np.cumsum([0] + sizes)
    groups = [perm[offsets[k] : offsets[k + 1]] for k in range(len(sizes))]
    dup_idx, miss_m, miss_b, miss_pm, orphan, bad_status, bad_amt, bad_ts, no_code = groups

    insert_sql = (
        "INSERT INTO transactions_raw (transaction_id, merchant_id, bank_id, payment_method_id, "
        "transaction_timestamp, amount_minor, currency, status, failure_code, settlement_id, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )
    dups = []
    for k, i in enumerate(dup_idx):
        r = list(rows[int(i)])
        if k % 3 == 0:
            dups.append(tuple(r))  # exact re-delivery of the same record
        else:
            # stale intermediate version: PENDING, recorded *before* the final state
            r[7], r[8], r[9], r[10] = "PENDING", None, None, r[4]
            dups.append(tuple(r))
    conn.executemany(insert_sql, dups)

    def ids(idx):
        return [(f"TXN{int(i) + 1:08d}",) for i in idx]

    conn.executemany("UPDATE transactions_raw SET merchant_id = NULL WHERE transaction_id = ?", ids(miss_m))
    conn.executemany("UPDATE transactions_raw SET bank_id = NULL WHERE transaction_id = ?", ids(miss_b))
    conn.executemany("UPDATE transactions_raw SET payment_method_id = NULL WHERE transaction_id = ?", ids(miss_pm))
    conn.executemany("UPDATE transactions_raw SET merchant_id = 'M999' WHERE transaction_id = ?", ids(orphan))
    conn.executemany("UPDATE transactions_raw SET status = 'UNKNOWN' WHERE transaction_id = ?", ids(bad_status))
    conn.executemany(
        "UPDATE transactions_raw SET amount_minor = CASE WHEN row_id % 2 = 0 THEN 0 ELSE -50000 END WHERE transaction_id = ?",
        ids(bad_amt),
    )
    conn.executemany(
        "UPDATE transactions_raw SET transaction_timestamp = CASE WHEN row_id % 2 = 0 THEN NULL ELSE '2025-02-30 25:61:00' END "
        "WHERE transaction_id = ?",
        ids(bad_ts),
    )
    conn.executemany(
        "UPDATE transactions_raw SET status = 'FAILED', failure_code = NULL, settlement_id = NULL WHERE transaction_id = ?",
        ids(no_code),
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _build_bank_reports(conn: sqlite3.Connection, profile: str, start: date, days: int) -> None:
    """Second source: daily counts as reported by each bank. Normally equal to canonical counts."""
    derived = conn.execute(
        """
        SELECT bank_id, date(transaction_timestamp) AS d, COUNT(*),
               SUM(status = 'SUCCESS'), SUM(status = 'FAILED')
        FROM transactions_canonical
        WHERE bank_id IS NOT NULL AND date(transaction_timestamp) IS NOT NULL
          AND bank_id IN (SELECT bank_id FROM banks)
        GROUP BY bank_id, d
        """
    ).fetchall()
    end = start + timedelta(days=days - 1)
    disc_days = {(end - timedelta(days=k)).isoformat() for k in (5, 4, 3)}
    missing_day = (end - timedelta(days=10)).isoformat()
    reports = []
    for bank_id, d, total, succ, fail in derived:
        if d is None or not (start.isoformat() <= d <= end.isoformat()):
            continue
        if profile == "source_discrepancy":
            if bank_id == ref.MISSING_REPORT_BANK_ID and d == missing_day:
                continue
            if bank_id == ref.DISCREPANCY_BANK_ID and d in disc_days:
                succ_r = int(round(succ * 1.08))
                fail_r = int(round(fail * 0.55))
                total = total + (succ_r - succ) + (fail_r - fail)
                succ, fail = succ_r, fail_r
        reports.append((bank_id, d, total, succ, fail, f"{bank_id}_DAILY_MIS"))
    conn.executemany(
        "INSERT INTO bank_daily_reports (bank_id, report_date, reported_total, reported_successful, reported_failed, source_name) "
        "VALUES (?,?,?,?,?,?)",
        reports,
    )
    conn.commit()
