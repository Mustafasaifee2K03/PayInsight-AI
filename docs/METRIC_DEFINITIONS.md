# Metric Definitions

All metrics are defined once in `backend/app/services/metrics.py`. Every analytical query selects the same **base aggregates** over `transactions_canonical t`, and each metric is a documented function of them. As a result, every reported value can show its numerator and denominator.

| Base aggregate | SQL |
|---|---|
| attempts | `COUNT(*)` |
| successful | `SUM(CASE WHEN t.status = 'SUCCESS' THEN 1 ELSE 0 END)` |
| failed | `SUM(CASE WHEN t.status = 'FAILED' THEN 1 ELSE 0 END)` |
| pending | `SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END)` |
| eligible | `SUM(CASE WHEN t.status IN ('SUCCESS','FAILED') THEN 1 ELSE 0 END)` |
| tpv_minor | `SUM(CASE WHEN status='SUCCESS' AND currency='INR' AND amount_minor > 0 THEN amount_minor ELSE 0 END)` |
| tpv_txn_count | count of the rows included in `tpv_minor` |

## Metrics

| # | Metric | Formula | Unit |
|---|---|---|---|
| 1 | Total payment attempts | `attempts` (every status, one row per transaction_id) | count |
| 2 | Successful transactions | `successful` | count |
| 3 | Failed transactions | `failed` | count |
| 4 | Pending transactions | `pending` | count |
| 5 | **Payment success rate** | `successful / eligible × 100` | % |
| 6 | Payment failure rate | `failed / eligible × 100` (= 100 − success rate) | % |
| 7 | Transaction volume | Same as attempts. "Volume" in a question maps to count. | count |
| 8 | Total payment value (TPV, INR) | `tpv_minor` (paise; displayed as ₹ with L/Cr) | INR minor |
| 9 | Average transaction value | `tpv_minor / tpv_txn_count` | INR minor |
| 10 | Daily transaction trend | Any metric grouped by `date(transaction_timestamp)` | — |
| 11–13 | Bank / merchant / payment-method success rate | Metric 5 grouped by the dimension, LEFT JOIN to its master table | % |
| 14 | Failure-code distribution | `failed` grouped by `failure_code` (FAILED rows only); share = code failures / all failures | count, % |
| 15 | Period-over-period change | See below | pp and % |

### Eligibility rule (success and failure rate)

**Eligible attempts are terminal outcomes only: SUCCESS + FAILED.**
- PENDING is excluded because its outcome is unknown. Counting it as a failure would understate success, and counting it as a success would overstate it.
- Invalid statuses (Scenario E) are excluded from the denominator too, and are reported by the data-quality check.
- Every KPI card shows `numerator / denominator`, and the facts list states how many attempts were excluded.

### Currency rule

TPV sums **only INR**. USD transactions on travel merchants are counted in attempts and rates but are never converted or added to INR TPV. The data-quality page shows the number of non-INR transactions (informational).

### Date boundaries

- A range `[start, end]` is inclusive of whole days and is implemented as `transaction_timestamp >= 'start 00:00:00' AND transaction_timestamp < 'end+1 00:00:00'`.
- Relative ranges such as "last 7 days" end on the **last day of available data** (2025-10-30), not on today's date. This makes results reproducible.
- When no range is given, the planner uses the full window (or the last 7 days for comparisons) and **states this as an assumption**.

### Period-over-period change (never confused)

For current value `v1` and previous value `v0`:
- **Absolute change** = `v1 − v0`. For rates this is in **percentage points (pp)**.
- **Relative change** = `(v1 − v0) / v0 × 100` %.

Example (Scenario B): the success rate moves from 91.09 % to 88.08 %. That is **−3.00 pp** absolute and **−3.3 %** relative.

Comparison periods are always **equal length and adjacent**: the previous N days end the day before the current period starts. This is enforced by the `AnalysisPlan` validator. If there is not enough history, the planner asks for a shorter period instead of comparing unequal windows.

### Statistical significance

For success-rate changes, a two-proportion z-test is reported: `z = (r1 − r0) / sqrt(p(1−p)(1/n0 + 1/n1))` with the pooled `p`. A change counts as *material* only if |Δ| ≥ 0.3 pp **and** |z| ≥ 2.

## Mix vs. within-segment decomposition (shift-share)

For segments `s`, using shares of **eligible** attempts:

| Symbol | Meaning |
|---|---|
| p0, p1 | baseline and current share |
| r0, r1 | baseline and current success rate |

```
within_s = p0 × (r1 − r0)        # performance change at constant mix
mix_s    = (p1 − p0) × r1        # share shift valued at current rates
Σ within_s + Σ mix_s = Σ p1·r1 − Σ p0·r0 = R1 − R0        (exact identity)
```

- The **contribution** of a segment is `within_s + mix_s`, and its *% of change* is `contribution_s / (R1 − R0)`.
- Contributions are ranked by their effect on the aggregate, **not** by the segment's current failure rate.
- A segment can exceed 100 % when other segments moved in the opposite direction. For example, Deccan contributes 113 % in Scenario B.

**Zero-volume segments.**
- A segment that is absent in the baseline has undefined `r0`. It is set to `r1`, so the within effect is 0 and the whole impact is mix.
- A segment that is absent in the current period has undefined `r1`. It is set to `r0`, so its disappearance is attributed to mix (−p0·r0).
- The identity holds exactly in both cases, because the undefined term is multiplied by zero in R0 or R1.

**Verification.** Each decomposition reports `residual = direct − (within + mix)`. The tests require |residual| < 1e-9 on real scenarios and on 200 randomised cases that include zero-volume segments.

## Heuristic detectors (clearly labelled in the UI)

| Detector | Rule |
|---|---|
| Daily anomaly | For each day, take the mean and sample standard deviation of the previous 14 days (7 inside root-cause scans) and flag the day if |z| ≥ 3. Weekly seasonality is not modelled. |
| Segment outlier | Binomial z-score of the segment failure rate against the overall rate, `z = (fr − FR) / sqrt(FR(1−FR)/n)`. Flagged when z ≥ 3 and n ≥ 50 eligible attempts. |

Neither detector is a predictive or machine-learning model.
