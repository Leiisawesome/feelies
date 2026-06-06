# Regime Stack — Deferred Empirical Validations (V-1 … V-5)

This directory holds the five data-dependent validations the
**services / regime-stack audit** (PR #96, retro
`docs/audits/regime_stack_audit_2026-06-04.md` §3) deferred to
post-merge work.  Each validation answers a specific design question
the audit couldn't settle from code alone and informs at least one
deferred or follow-up decision (E-2, E-3, E-4, or threshold
re-calibration).

## Convention

For each validation `V-N` ship **three** artifacts at the same
commit:

* `V-N_<slug>.py` — analysis script written in [Jupyter percent
  format](https://jupytext.readthedocs.io/en/latest/formats.html#the-percent-format)
  so it's diffable in git but opens directly in VS Code Jupyter or
  Jupytext as a notebook.  Every script must declare its
  **decision rule frozen in the header**, before the analysis
  itself, so post-hoc rationalisation is structurally impossible.
* `V-N_<slug>.md` — one-page memo: header (date, author, data
  window, decision rule), result summary table, conclusion,
  decision.  The memo is the durable artifact — six months from
  now you read this, not the script.
* `V-N_<slug>_data.csv` — the summary table the memo's numbers
  come from, so the result can be audited without re-running the
  script.

When all five are done, append a row to the retro's §3 table with
result + decision + commit SHA, and link the memo.

## Ground rules (from the retro)

1. **Use real engine code, not reimplementations.**
   `from feelies.services.regime_engine import HMM3StateFractional`
   and feed it real `NBBOQuote` events.  Reproducing the math in
   pandas validates the notebook, not the engine.
2. **Pin the data window in the script header.**  Don't auto-grab
   "latest 30 days" — results need to be re-runnable in six
   months.
3. **One script per question.**  Don't combine.
4. **Memo > script.**  The script produces the chart; the memo
   records the decision.
5. **Set the decision rule before looking.**  The header has a
   `# DECISION RULE:` block — write it before running, do not
   amend after.

## Suggested execution order

| # | Validation | Decides | Effort | Why this order |
|---|---|---|---|---|
| **V-1** | Emission separation `d` + state occupancy | Default-enable `enforce_min_pairwise_emission_separation` (E-4) | half day | Smallest; if emissions don't separate, V-3 and V-4 become more important |
| **V-5** | Hazard precision at threshold 0.30 | Canonical hazard-score threshold valid? | half day | Validates the most recent audit value change |
| **V-2** | Intraday quote-rate distribution per cohort | Flip `transition_time_scaling_enabled` (E-2) + `dt_reference` | quarter day | Quick distribution work; sets up V-3 |
| **V-3** | Posterior-bucketed forward returns | Does "normal" carry edge? (E-3 scope) | one day | Depends on V-1 (engine usefully calibrated) |
| **V-4** | Gate ON/OFF conditional Sharpe | Gate selects better microstructure? | one to one-and-a-half days | Most plumbing; co-runnable with V-3 |

## Data

The repo's NBBO path goes through the `massive` extra (formerly
Polygon).  A V-N run needs:

* a `data/cache/` (or operator-chosen) directory of NBBO snapshots
  per symbol per session, in the platform's canonical format
  (parquet preferred; the loader hint is in
  `src/feelies/ingestion/cache.py`);
* the universe pinned in the script header.

If the cache layout differs in your environment, update
`DATA_PATH` at the top of the script — the rest of the analysis is
written against the platform's `NBBOQuote` event type, not the
on-disk layout.
