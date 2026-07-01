<!--
  File:   docs/research/gas_03_dynamic_horizon.md
  Status: GAS DECISION #3 — LAB TEST, offline only. No engine, alpha, or
          scheduler change. Pre-registered; awaiting operator harness run.
  Owner:  feature-engine / microstructure-alpha.
-->

# Gas decision #3 — "dynamic horizon": is a fixed calendar horizon hiding regime-conditional edge?

Opened from a stress-test of gas #1 and #2's methodology, not from a new
sensor idea. Both prior decisions measured RankIC / `edgeBps` **pooled**
across an entire session at each fixed calendar horizon
(30/120/300/900/1800 s). This decision asks whether that pooling itself is
hiding a real, tradeable, regime-conditional edge.

## Explicit scope: lab test only

This is a **measurement-only stratification of data the harness already
produces** — it does not propose changing `HorizonScheduler`, any alpha's
`horizon_seconds`, the `regime_gate` DSL, or any live wiring. Nothing here is
reachable from `bootstrap.py`, a `platform.yaml`, or an alpha spec. It is
fully additive to `scripts/sensor_feature_ic.py` (a new opt-in
`--regime-stratify` flag; the default invocation used for gas #1/#2 is
byte-for-byte unaffected) and is trivially reversible — delete this doc, the
new harness functions, and the new tests, and nothing else in the platform
changes. **Only if this lab test shows a robust, multi-day, cost-gate-clearing
result does it become a real proposal** (see "If this passes" below), and
even then the first real step is routing among *already-registered* horizons
(zero scheduler changes) — never a new scheduling primitive.

## Hypothesis

A fixed calendar window spans a variable "information dose" depending on the
prevailing regime. Three literatures converge on this:

- **Kyle (1985)** itself doesn't use calendar time — the model's "auction
  time" is normalized by cumulative order flow, not the clock.
- **Volume-clock literature** (Ané & Geman 2000; Easley/López de
  Prado/O'Hara 2012) shows subordinating returns to a volume/trade-count
  clock restores near-iid behavior that calendar sampling destroys, because
  information arrives in bursts, not uniformly.
- **AFML's triple-barrier method** is functionally "dynamic horizon" for
  labeling — barriers scale with realized volatility.

Applied here: `ofi_integrated` over 30 s of a `vol_breakout` regime and 30 s
of `compression_clustering` are not the same measurement. Pooling both under
one `RankIC(ofi_integrated, 30s)` mixes two different data-generating
processes.

**Falsifiable link to prior evidence:**
- Gas #1's KYLE-horizon instability (≈0 at 300 s, wrong-signed −0.409 at
  1800 s, n=16–88) may be partly a regime-pooling artifact, not pure small-n
  noise — a long window spans a variable regime mix session to session.
- Gas #2's cost-gate failure (pooled `edgeBps` +0.85 at 30 s, vs a ~5 bp
  hurdle) may be averaging a real, cost-clearing edge concentrated in burst
  windows against near-zero edge in quiet windows.

## What already exists (no new engine surface needed for this lab test)

- `RegimeEngine` / `HMM3StateFractional` — causal, deterministic, per-symbol
  posterior over `{compression_clustering, normal, vol_breakout}`, calibrated
  from a **causal prefix** of quotes (mirrors
  `Orchestrator._calibrate_regime_engine`; production uses e.g.
  `regime_calibration_max_quotes: 100000` in `configs/paper_run.yaml`). The
  harness instantiates a fresh, throwaway instance of this exact class —
  nothing shared with a live run.
- `forward_ic.long_short_edge_bps` / `spearman_ic` — the same cost-gate and
  IC primitives used for gas #1/#2, applied per stratum instead of pooled.

## Study design

`scripts/sensor_feature_ic.py --regime-stratify` adds, per `(symbol, date)`:

1. Build a fresh `HMM3StateFractional`, calibrate on a causal prefix of that
   tape's quotes (`_REGIME_CALIBRATION_MAX_QUOTES = 20_000`, or the whole
   tape if shorter — same pattern as `scripts/regime_diagnostics.py`).
2. Latch the dominant regime state at each `HorizonFeatureSnapshot`
   boundary (causal — the most recent quote's posterior at-or-before the
   boundary timestamp; `None`/dropped if no posterior has latched yet).
3. Re-cut the existing `ofi_kyle_input` (`ofi_integrated` /
   `ofi_ewma_zscore`) pairs by `(variant, horizon, regime)` instead of
   `(variant, horizon)`, and report `RankIC`, `IC`, `t`, and `edgeBps` per
   cell using the same primitives as gas #1/#2.
4. Multi-day pooling (`_aggregate_across_days`) now pools **within** each
   regime bucket, so a `(vol_breakout, 30s, ofi_integrated)` cell across 10
   days becomes one headline row.

## Run it (operator, on the disk cache; pool many days — cell n will be small)

```bash
PYTHONHASHSEED=0 uv run python scripts/sensor_feature_ic.py \
    --cache-dir ~/.feelies/cache \
    --symbol APP --date 2026-03-26 --symbol APP --date 2026-03-27 ... \
    --horizons 30,300,1800 --regime-stratify --csv gas3.csv
```

Read the pooled `ofi_kyle_input` rows grouped by `regime`. Expect small `n`
per cell — regime splits a already-thin sample three ways — so this
**requires more days pooled** than gas #1/#2 needed before any cell is
trustworthy.

## Decision criteria — this remains a lab test unless ALL hold (pooled, multi-day)

1. At least one `(variant, horizon, regime)` cell shows `RankIC` significant
   (|t| > 2) **and** correctly signed, with adequate pooled `n` (materially
   more than the single-day n that made gas #1's long horizons untrustworthy).
2. That cell's `edgeBps` clears **that regime's own round-trip cost** — not
   the blended cost gas #2 used. Spread (and therefore cost) is itself
   regime-dependent (wider in `vol_breakout`), so a regime-conditional edge
   must be checked against a regime-conditional cost, not a pooled one.
3. The result survives `research/cpcv` (purged, embargoed) and
   `research/dsr` (deflated Sharpe) scrutiny before being treated as
   anything other than exploratory — regime-stratifying is itself a
   multi-way hyperparameter search (3 regimes × N horizons × 2 variants),
   and naive in-sample cell-picking will find noise that looks like edge.

Any one of these failing keeps this filed as a negative/inconclusive lab
result, same as gas #1's long-horizon finding.

## If this passes — still not an engine change

A pass justifies **only**: a composition-layer rule that routes to an
*already-registered* horizon's signal based on current regime state (e.g.
"if `dominant == vol_breakout`, act on the 30 s signal; else the 1800 s
signal"). This requires zero changes to `HorizonScheduler`'s boundary math,
G7 (horizon must be platform-registered), or G3 (cross-alpha horizon
isolation) — every horizon it could route to already runs today. The only
real new surface is bookkeeping: `forensics/multi_horizon_attribution.py`
would need a per-decision "which horizon was live" tag. A continuous or
volume-clock horizon (a genuine `HorizonScheduler` change) is explicitly
**out of scope** unless the discrete routing case is proven first and shown
to be insufficient — see the "engine vs gas" discussion this decision was
opened from.

## Result

*(pending — operator harness run on cached data)*

## Status

**OPEN — pre-registered, lab test only.** Harness plumbing (`--regime-stratify`,
`_build_regime_lookup`, `_ofi_integrated_by_regime`) and unit tests
(`tests/research/test_gas_dynamic_horizon.py`) are in place. No alpha, no
engine primitive, no scheduler change. Reversible by deleting this doc, the
new harness functions, and the new tests — nothing else in the platform
depends on them.
