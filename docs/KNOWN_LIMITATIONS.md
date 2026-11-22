# Known Limitations

This page lists what the system does **not** do, or does only in a simplified way.

## Natural-language understanding
- **Rule-based planner, not an LLM.** It covers the documented question families (KPI, breakdown, ranking, trend, comparison, contribution, mix, root cause, anomalies, outliers) plus synonyms and close paraphrases. Unusual phrasings, complex sentences ("…excluding X but only for Y after Z"), negation and multi-part questions are not understood. These usually lead to a clarification request or to the closest supported plan, with assumptions shown.
- **At most two dimensions per plan.** Filters support equality and IN on catalogue values only. There are no numeric filters such as "amount > ₹5,000".
- **Simple relative dates.** "Last N days/weeks/months/quarters/years", month names, quarters ("Q3 2025"), calendar years ("in 2025"), ISO dates and "yesterday"/"today" are supported, all anchored to the last data day and clipped to the data window with an explicit assumption. Year-to-date, "same period last year" and fiscal calendars are not supported and get a clarification request rather than a guess. Quarters, "same period last year" and custom fiscal calendars are not.
- **Heuristic confidence score.** It is derived from the number of assumptions and is not a calibrated probability.

## Analytics
- **Correlation, not causation.** Contribution and decomposition show *where* a change is concentrated. Hypotheses are template-based and labelled as unproven.
- **Single-level decomposition.** The decomposition works on one dimension at a time. The root-cause scan compares five dimensions but does not decompose nested hierarchies such as bank × method jointly.
- **Simple heuristic detectors.**
  - The daily anomaly rule uses a trailing mean ± 3σ and ignores weekly seasonality. On the stable baseline it flags one borderline day (2025-10-17, z = −3.1), which is a genuine false positive of the rule.
  - The outlier rule uses a binomial z-score without multiple-comparison correction.
- **Fixed significance thresholds.** The materiality threshold (0.3 pp, |z| ≥ 2) is fixed rather than configurable per metric.
- **One region attribute.** The region dimension is the *merchant's* region. Bank region exists in the data but is not exposed as a separate dimension.
- **Currency.** Non-INR transactions are excluded from TPV and never converted; there is no FX table.

## Data
- **Synthetic, simplified data.** For example, settlements are one batch per merchant per day, and refunds, chargebacks and partial captures are not modelled.
- **Fixed window and size.** The demo dataset covers 60 days with 30,000 transactions per scenario. The 100k dataset is used only for benchmarks and tests.
- **Data-quality scenario.** Scenario E injects a fixed, known set of defects; real feeds would need more check types (schema drift, late-arriving data).

## Platform
- **Single process.** One SQLite file per scenario, an in-process result cache (not shared between workers, lost on restart), and synchronous request handling in a thread pool.
- **Server-side scenario switching.** Activating a scenario changes the active dataset for **all** users of the running instance. This is intended for single-presenter demos.
- **Authentication scope.** JWT + DB-backed sessions, lockout, rate limiting and audit are implemented, but there is no SSO/MFA, email verification or password reset (no email service), and no TLS on the dev servers. The rate limiter is in-process by default (bounded memory, pluggable backend), so it is per server instance until a shared backend is registered. Lockout can be triggered by anyone who knows an email (admins can unlock). See HARDENING_REPORT.md §5–6 for the scale-out path. See SECURITY.md §5.
- **Light theme only.** Charts use the validated light-mode palette, and no dark mode is provided.
- **Bundle size.** The frontend's Recharts chunk is about 540 kB minified (154 kB gzip). The chunk warning limit was raised instead of replacing the chart library.
- **E2E browser requirement.** The browser journeys need Microsoft Edge (they use Playwright's `msedge` channel to avoid downloading browsers). The core app and the pytest suite do not need it.
