# Demo Script (about 6 minutes)

**Goal:** show business value, analytical correctness and engineering reliability. Do not walk through installation.

> **Every answer quoted below is copied verbatim from the app's real output** (captured on 2026-11-22 against the live data files, which match the fixed seed). If what you see differs, check the **active scenario** in the header dropdown first. Each step says which scenario must be active, and the table at the end shows what each question returns in the *wrong* scenario.

## Before recording (2 minutes, off camera)

1. Run `scripts\start.ps1`, open **http://localhost:5173**, and zoom the browser to 90 %.
2. Sign in as **admin@payinsight.demo** / `PayInsight@2026`.
3. Header dropdown → **A — Normal performance**. In **Demo Scenarios**, optionally click *Reset / reseed active scenario* to clear the cache.
4. Keep a private window (Ctrl+Shift+N) open on http://localhost:5173 for the signup part. Each window has its own session.
5. Rehearse once: each scenario switch takes 1–2 seconds and shows a confirmation banner. **Always switch first, then ask.**

---

## 0:00 – 0:30 · The problem

> "Payments teams constantly ask *why* success rates moved. Is it a bank? A merchant? Or just a change in transaction mix? Today an analyst spends hours finding tables, writing SQL and building charts. **PayInsight AI** turns that question into an evidence-backed answer in under a second. It runs entirely locally with a **deterministic analysis engine and no external AI API**. Every number you'll see comes from SQL that actually ran."

Point at the sidebar label: *Local deterministic analysis engine — No external AI API.*

## 0:30 – 1:05 · Dashboard · active scenario **A**

The KPI cards compare the last 30 days (2025-10-01 → 10-30) with the previous 30:

| Card | Value | Change |
|---|---|---|
| Total payment attempts | **15,430** | +860 (+5.9 %) |
| Payment success rate | **91.79 %** (`13,956 / 15,205`) | **+0.06 pp** (+0.06 % relative) |
| Failed transactions | **1,249** | +62 (+5.2 %) |
| TPV (INR) | **₹5.07 Cr** | +6.3 % |

- Point at `13,956 / 15,205` under the success rate, and at the **pp** change shown separately from the relative %.
- Daily success-rate chart: hover the tooltip. Attempts are in a separate panel underneath, with no dual axis.
- Failure rate by payment method: **Net Banking is clearly worst (≈ 19.9 % failure vs UPI ≈ 5.3 %)**. Top failure codes: **INCORRECT_PIN_OTP (260), INSUFFICIENT_FUNDS (249), BANK_TIMEOUT (240)**.

> "Success rate here is SUCCESS over SUCCESS plus FAILED. Pending transactions are excluded, and every card shows its numerator and denominator."

## 1:05 – 1:45 · A basic question and its SQL · active scenario **A**

Go to **Analytics Workspace** and ask **"What is the overall success rate?"**

The app answers:
> **"Payment success rate was 91.76% (27,122 of 29,558 eligible attempts) for 2025-09-01 to 2025-10-30 (60 days)."**

- Amber **Assumptions** line: *"No period given; using the full available data window (2025-09-01 to 2025-10-30)."* Point out that the app states its defaults instead of hiding them.
- Observed facts: *"Status split: 27,122 SUCCESS, 2,436 FAILED, 442 PENDING out of 30,000 canonical attempts."* and *"442 non-terminal or invalid-status attempts are excluded from the rate denominator."*
- Explainability panels to open:
  - **1. Question interpretation**: recognised terms, and confidence 0.83.
  - **6. Generated SQL**: bound parameters, nothing interpolated.
  - **7. Execution metadata**: milliseconds per query and cache hit or miss.
  - **9. Evidence**: the raw result rows.

Also good in Scenario A, if you have time:

| Ask | Answer |
|---|---|
| "How many transactions occurred?" | "Total payment attempts was 30,000 …" |
| "What is our total transaction value?" | "Total payment value (TPV, INR) was ₹9.84 Cr …" |
| "Show daily transaction trends" | "… daily total payment attempts ranged from 424 (2025-09-03) to 599 (2025-09-28) …" |

> "The planner turned English into a validated JSON plan, and the compiler turned the plan into parameterised SQL. That SQL went through a SQLGlot validator, a SQLite authorizer and a read-only connection before it ran."

## 1:45 – 2:50 · "Why did it decline?" · switch to **B — Bank performance decline**

Header dropdown → **B — Bank performance decline**, wait for the banner, then ask **"Why did payment success rate decline?"**

The app answers:
> **"Payment success rate declined by -3.00 pp (91.09% → 88.08%). The largest contributor is bank Deccan Commercial Bank: -3.40 pp (113% of the change), with its success rate moving 89.57% → 71.08% on 17.9% of eligible volume. Mix effects are small (-0.06 pp by merchant category)."**

- **Verdict chip:** *"Verdict: Performance deterioration within a segment (mix ≈ 2% of change)"*.
- **Assumptions:** *"No period given; comparing the last 7 days of data (2025-10-24 to 2025-10-30) with the previous 7 days."*
- **Observed facts** to read out:
  - "… -3.00 pp absolute, -3.3% relative. The change is statistically significant (two-proportion z = -4.1)."
  - "Within Deccan Commercial Bank, BANK_TIMEOUT failures changed 13 → 142 — the largest increase of any failure code."
  - "Decomposition identity verified for every dimension: within + mix = direct change (max residual 9.3e-15 pp)."
- **Charts:**
  - Daily success rate across both weeks.
  - *Failure codes for Deccan Commercial Bank: previous vs current* (BANK_TIMEOUT 13 → 142).
  - *Contribution to success-rate change by bank*.
- **Three columns:**
  - **Observed facts**: numbers only.
  - **Hypotheses**: *"…consistent with a segment-specific operational issue … but the data alone does not prove the cause."* The footnote reads *"Hypotheses are correlational; they are not proven causes."*
  - **Recommended actions**:
    1. *Investigate BANK_TIMEOUT failures for Deccan Commercial Bank*
    2. *Escalate to the Deccan Commercial Bank relationship / integration team*
    3. *Evaluate temporary routing or retry mitigations*
- **Decomposition scan across dimensions** table: in the **Bank** row, within-effect ≈ −3.01 pp and mix ≈ 0.00 pp. Deccan is the top segment at 113 % of the change.

> "It didn't just rank banks by failure rate. It decomposed the aggregate change, found where the drop is concentrated, and drilled into failure codes. 113 % is possible because other banks slightly improved."

**Optional proof that it isn't pattern-matching (15 s), still in B:** ask **"Is the decline caused by payment-method mix?"**
> **"Success rate declined by -3.00 pp. By payment method, mix explains -0.03 pp (1%) and within-segment performance -2.98 pp (99%). Verdict: Within-segment performance change (not mix)."**

## 2:50 – 3:40 · Mix decomposition · switch to **D — Transaction mix shift**

Header dropdown → **D — Transaction mix shift**, then ask **"Is the decline caused by payment-method mix?"**

The app answers:
> **"Success rate declined by -3.17 pp. By payment method, mix explains -3.88 pp (122%) and within-segment performance +0.71 pp (-22%). Verdict: Transaction mix shift."**

- **Verdict chip:** *"Verdict: Transaction mix shift (mix ≈ 122% of change)"*.
- **Observed facts:**
  - *"Net Banking: share 12.1% → 39.3% (+27.2 pp); success rate 77.00% → 80.08% (+3.09 pp)."*
  - *"UPI: share 54.2% → 27.4% (-26.8 pp); success rate 94.96% → 94.36% (-0.59 pp)."*
  - *"… within-segment effect +0.71 pp + mix effect -3.88 pp = -3.17 pp; direct aggregate change -3.17 pp (residual 4.00e-15 pp — identity verified)."*
- **Charts:** *Share of eligible attempts by payment method* (the share swap) and *Success rate by payment method* (rates did not fall).
- **Recommended action:** *"Do not escalate to banks solely on the blended decline."*

> "Same kind of headline drop as Scenario B, completely different cause. In B the same question said 'not mix'; here mix explains more than the whole decline. A naive dashboard would send you chasing banks."

(Also in D: **"Why did payment success rate decline?"** gives *"…explained mainly by a shift in payment method mix: mix effect -3.88 pp (122% of the change) vs within-segment performance +0.71 pp. Individual payment method success rates were broadly stable."*)

## 3:40 – 4:25 · Data quality and sources · scenarios **E** then **G**

Switch to **E — Data quality failure** and open **Data Quality & Sources**. The *Data quality* tab shows status **FAIL**:

| Check | Affected | Severity |
|---|---|---|
| Duplicate transaction IDs (raw 30,300 → canonical 30,000) | 300 | high |
| Duplicates with conflicting status | 196 | medium |
| Missing merchant / bank / payment-method IDs | 120 / 80 / 40 | medium |
| Orphan dimension references | 30 | high |
| Invalid statuses | 15 | high |
| Invalid amounts | 20 | medium |
| Invalid or out-of-window timestamps | 10 | high |
| FAILED transactions without failure code | 25 | low |
| Non-INR transactions (informational) | 102 | info |

Each row shows its impact and the **treatment** applied. Nothing is silently dropped.

Optional, still in E: ask **"What is the overall success rate?"**
> **"Payment success rate was 91.68% (27,077 of 29,534 eligible attempts) …"**

It also adds a recommendation, *"Resolve upstream data-quality defects"*, listing the open issues. The analysis knows the data is dirty.

Switch to **G — Source discrepancy** and open the **Source reconciliation** tab. Status FAIL, 4 flagged rows out of 480 compared:
- **Ganga Valley Bank**, 25–27 Oct: the MIS over-reports successes by **≈ 8.5–8.7 %** (for example 69 derived vs 75 reported on 25 Oct), status **CRITICAL**.
- **Bharat Union Bank**, 20 Oct: the report is **MISSING**.

> "We never merge conflicting sources. Transaction data drives the analytics, and discrepancies are flagged for investigation."

**Optional (20 s): SQL safety sandbox tab**

| Run | Result |
|---|---|
| `DROP TABLE transactions_raw` | **HTTP 422**: *"Only SELECT queries are allowed (received DROP)."* |
| `SELECT COUNT(*) FROM transactions_canonical a, transactions_canonical b, transactions_canonical c` | **HTTP 408**: *"Query exceeded the 3000 ms execution limit and was cancelled."* |
| `SELECT printf('%.*c', 400000000, 'x') FROM transactions_canonical` | **HTTP 422**: *"Function 'printf' width/precision must be a literal of at most 1000."* This one was found by the hardening pass; it used to allocate 400 MB. |

## 4:25 – 5:30 · Accounts, sessions and access control · switch to **F — Access control failure** (or stay on A)

1. In the private window, click **Create account**. Type a weak password and point at the live checklist: the button stays disabled. Use a strong one (for example `Settle-Up#2026`) and sign up.
2. You land as **VIEWER** (header chip). The dashboard shows ***"Bank performance is restricted"***.
3. Ask **"Compare payment success rates by bank"**:
   > **Access denied — HTTP 403 (ROLE_RESTRICTED_DIMENSION):** *"Access denied: your role (VIEWER) is not permitted to run bank-level analysis. Bank and merchant drill-downs require the ANALYST or ADMIN role."*

   Point at the **Reference** ID under the error. It matches the server log line.
4. Show that the viewer *can* ask **"Compare payment success rates by payment method"**:
   > *"Across 4 payment method segment(s), UPI has the highest payment success rate (94.60%) and Net Banking the lowest (80.61%); overall 91.76% …"*
5. Admin window → **Users & Audit**. Change the new user's role to **ANALYST**. Point at the audit log row **USER_UPDATED** (VIEWER → ANALYST, by admin@payinsight.demo).
6. Back in the private window, ask the bank question again **without signing in again**:
   > **"Across 8 bank segment(s), Aurora National Bank has the highest payment success rate (92.96%) and Frontier Co-operative Bank the lowest (88.41%); overall 91.76% for 2025-09-01 to 2025-10-30 (60 days)."**
7. Open **Account & Security**: the session list shows *This device*, the IP and the token-rotation count.
8. Optional (10 s): in the admin window click **Disable** on that user. In the private window click anything: it goes back to the login page with *"Your session ended"*, and signing in shows *"This account has been disabled by an administrator."*

> "Authentication is a 15-minute JWT plus a rotating refresh token in an httpOnly cookie, backed by a sessions table. That's why a role change or disabling an account takes effect instantly, and why a replayed refresh token kills the session. Five wrong passwords lock the account, and every one of these events is in the audit log."

**Optional (10 s), the planner refusing to guess:** ask **"success rate same period last year"**:
> *"'same period last year' comparisons are not supported (the dataset covers 2025-09-01 to 2025-10-30). Try 'compare the last 7 days with the previous 7 days'."*

## 5:30 – 6:00 · Close

> "So: natural-language questions, validated plans, safe SQL, period comparisons, a mathematically verified mix decomposition, explicit facts versus hypotheses, data-quality and reconciliation checks, and real authentication with server-side sessions and backend-enforced access control. It's covered by 153 backend tests, including 18 progressive acceptance iterations checked against independent SQL, 25 authentication tests and 47 regression tests from a 10-round adversarial hardening pass, plus 12 browser journeys. A full root-cause analysis on 100,000 transactions takes about half a second, with zero paid dependencies. That's PayInsight AI."

---

## Same question, different scenario: what you should see

If an answer doesn't match the script, compare it with this table. These are actual outputs.

| Question | A / G (normal data) | B (bank decline) | D (mix shift) | E (data quality) |
|---|---|---|---|---|
| "Why did payment success rate decline?" | "…did not materially decline: it increased by +0.69 pp (91.09% → 91.78%), z = 1.0. No segment-level root cause is warranted." | −3.00 pp, Deccan Commercial Bank −3.40 pp (113 %) | −3.17 pp, explained by payment-method mix (−3.88 pp) | "…did not materially decline: it increased by +0.73 pp (91.02% → 91.75%)…" |
| "Is the decline caused by payment-method mix?" | "Success rate did not change materially (+0.69 pp, z = 1.0)…" | **Not mix**: mix −0.03 pp, within −2.98 pp | **Mix**: mix −3.88 pp, within +0.71 pp | "did not change materially (+0.73 pp, z = 1.1)…" |
| "Compare payment success rates by bank" (admin/analyst) | Aurora 92.96 % highest, Frontier 88.41 % lowest; overall 91.76 % | Same ranking over 60 days; overall **91.31 %** (Deccan's drop is only the last 7 days) | Aurora 92.62 %, Frontier 88.35 %; overall 91.28 % | 9 segments, including **"Unknown / unmapped"** (rows with missing bank IDs are kept, not dropped); overall 91.68 % |

Saying "in Scenario A it correctly says there's nothing to explain" is itself a good demo line. The engine refuses to invent a root cause.

### Fallbacks
- **Answer differs from the script:** check the header dropdown for the active scenario, then see the table above.
- **Numbers still differ:** Demo Scenarios → *Reset / reseed active scenario* regenerates the data from the fixed seed.
- **Backend unreachable:** the UI shows "Cannot reach the PayInsight backend". Restart with `scripts\start.ps1`.
- **Account locked after typos:** sign in as admin → *Users & Audit* → **Unlock**.
- **Quick checks:** `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`.
