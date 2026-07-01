<!--
  File:   docs/research/gas_03_dynamic_horizon.md
  Status: GAS DECISION #3 — LAB TEST, offline only. No engine, alpha, or
          scheduler change. 12-day pooled run: criteria not met (no cell
          clears |t|>2 + regime-conditional cost + CPCV/DSR); INCONCLUSIVE,
          not a flat kill. One lead (300s/compression_clustering/
          ofi_integrated, t=1.65) worth further pooling.
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

## Result — pooled 12 days, sample-weighted (`ofi_kyle_input`)

| horizon | variant | regime | n | RankIC | t | edgeBps |
|--:|---|---|--:|--:|--:|--:|
| 30s | `ofi_ewma_zscore` | all | 7,799 | +0.028 | +2.47 | +1.23 |
| 30s | `ofi_ewma_zscore` | normal | 2,532 | +0.025 | +1.26 | +1.89 |
| 30s | `ofi_ewma_zscore` | vol_breakout | 996 | +0.060 | **+1.90** | +2.20 |
| 30s | `ofi_integrated` | all | 9,177 | +0.035 | +3.36 | +1.03 |
| 300s | `ofi_ewma_zscore` | all | 964 | +0.021 | +0.65 | −0.06 |
| 300s | `ofi_integrated` | compression_clustering | 526 | +0.072 | **+1.65** | +8.35 |
| 1800s | `ofi_ewma_zscore` | normal | 46 | +0.266 | **+1.83** | +3.61 |
| 1800s | `ofi_integrated` | vol_breakout | 35 | +0.171 | **+1.00** | +105.15 |

(t computed with the same `_tstat` the harness reports, `t = ic·√((n−2)/(1−ic²))`.)

**No regime-cut cell clears the pre-registered `|t| > 2` bar.** The single
largest-looking number (`+105.15 bps`, 1800s `ofi_integrated`/`vol_breakout`)
has the *weakest* statistical support of the table (t≈1.00, n=35) — the exact
small-sample-long-horizon failure mode gas #1 already flagged (its −0.409 at
1800s, n=17). It is noise, not a finding, and must not anchor the read.

Qualitative support for the hypothesis, short of significance:
- At 30s, edge scales with regime in the predicted direction:
  `ofi_ewma_zscore` edge is 1.23 (all) → 1.89 (normal) → 2.20 (vol_breakout)
  bps — a real, ~1.8× lift from calm to bursty. But even the best bucket
  stays well under the ~5 bp Inv-12 hurdle; regime conditioning does not
  rescue the 30 s cost-gate failure gas #2 found.
- The one cell worth further pooling: **300s / `ofi_integrated` /
  `compression_clustering`** — a real sample (n=526, not a fluke size),
  edge +8.35 bps clears cost by a wide margin, t=1.65 short of significance.
  It also has a coherent mechanism (quiet/tight-spread regimes may carry
  less noise-diluted order-flow signal than chaotic ones), unlike the 1800 s
  numbers, which have no such support.
- Sanity check: the pooled "all" rows match gas #2's single-day read almost
  exactly (30 s `ofi_integrated`: RankIC +0.035 both times; n grew from
  ~810 to 9,177) — the harness is behaving consistently as more days pool in.

**Multiple-comparison caution.** This run cut ~24 cells (2 variants × 3
horizons × 3–4 regime buckets incl. "all"). Seeing one or two cells near
t≈1.7–1.9 is unsurprising under pure noise at that count — exactly why
criterion 3 (CPCV/DSR) exists before any single cell is treated as real.

## Decision

**Criteria not met — stays a lab-test negative/inconclusive result.** No
cell clears all three pre-registered criteria (significant RankIC,
regime-conditional cost clearance, CPCV/DSR robustness) simultaneously.
Regime stratification does not rescue gas #1 or gas #2's failures on this
evidence. It is not, however, a flat kill the way gas #1/#2 were: the
300 s/`compression_clustering`/`ofi_integrated` cell is a plausible,
adequately-sized (n=526) lead that fell just short of significance
(t=1.65) — worth targeted further pooling (more compression-regime days at
300 s specifically) before being written off, but not worth building
anything on yet.

## Status

**OPEN — inconclusive.** Harness plumbing (`--regime-stratify`,
`_build_regime_lookup`, `_ofi_integrated_by_regime`) and unit tests
(`tests/research/test_gas_dynamic_horizon.py`) are in place and have
produced one 12-day pooled result. No alpha, no engine primitive, no
scheduler change — reversible by deleting this doc, the new harness
functions, and the new tests. Re-run with more days pooled, targeting the
300 s/`compression_clustering` cell, before revisiting this decision.
