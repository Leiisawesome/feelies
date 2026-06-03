# Layer-1 Sensor & Horizon-Aggregation Audit — feelies

**Date:** 2026-06-02
**Scope:** `src/feelies/sensors/**`, `src/feelies/features/**`,
`src/feelies/signals/horizon_engine.py` (consumer, read-only), `platform.yaml`
`sensor_specs:`, reference alphas under `alphas/`.
**Mode:** Read-only, evidence-based. No production code modified.
**Test state at audit:** `tests/sensors/` → 139 passed, 1 skipped;
`tests/features/` + the three determinism replay suites → 102 passed. Green.

> Severity legend: **P0** correctness (math/sign/lookahead/non-determinism),
> **P1** feature strength / contract drift, **P2** research. Effort S/M/L.

## 0. Remediation status (this PR)

Landed the P0 doc fixes, the parity-safe P1-2 / P1-3 fixes, **and the
P1-1 horizon-windowed aggregator** (with a deliberate, documented
re-baseline of the single Level-3 snapshot parity hash via
`scripts/rebaseline_parity_hashes.py`). Full suite: no new failures
(9 pre-existing failures in `bootstrap/test_paper_branch.py`,
`test_execution_backend_wiring.py`, `test_mypy_strict_scope.py` —
a `_create_backend(... cost_model)` signature drift — are unrelated to
this work and reproduce on a clean checkout).

| Item | Status | Notes |
|---|---|---|
| **P0-1** G16 fingerprint table cites unimplemented sensors | ✅ fixed | feature-engine + microstructure-alpha skills now list only implemented ids + flag the coverage gap |
| **P0-2** snapshot contract docstrings wrong (`warm: bool`, fake `z_scores`) | ✅ fixed | both skills corrected to `warm/stale: dict`, `feature_id` keys, real staleness semantics |
| **P1-2** `stateful` unreachable from YAML (silent estimator bias) | ✅ fixed | `platform_config.py` loader plumbs + serializes `stateful`; warns when `throttled_ms` set without it; new round-trip test |
| **P1-3** Hawkes direction discarded | ✅ fixed | new `TupleSignedImbalanceFeature` → additive `hawkes_intensity_imbalance` feature; new unit tests |
| **P1-1** horizon-windowed aggregation | ✅ fixed | new `HorizonWindowedFeature` (Welford event-time window keyed on `horizon_seconds`); production `ofi_ewma_zscore` / `micro_price_zscore` / `realized_vol_30s_zscore` now horizon-windowed so the G16 ratio has real effect. Level-3 snapshot parity hash **rebaselined** (count unchanged at 14); rationale in `test_horizon_feature_snapshot_replay.py` + commit |
| **P1-7** z-window inconsistent / horizon-blind (also exec-summary #11) | ✅ fixed | all remaining rolling features (`kyle_lambda_60s` z+percentile, `quote_replenish_asymmetry` z, `hawkes_intensity` z) converted to `HorizonWindowedFeature`; added a `percentile` reducer; every rolling feature now uses a consistent event-time window of width `h` |
| **P1-6** spread_z staleness / gate time-base (#8) | ✅ fixed | additive `spread_z_30d` passthrough feature → aggregator horizon-staleness override now covers it and the gate binding resolves from the boundary value (unifies gate/snapshot time-base); parity-safe |
| **P1-9** micro_price level → drift | ✅ fixed | added a level-invariant `delta` reducer to `HorizonWindowedFeature` and wired `micro_price_drift` (signed micro-price change over the horizon) as an additive feature; migrating the reference alpha to consume it instead of the level z is a follow-up pending the IC run |
| **P1-8** session-open anchor | ⏸ deferred | needs config policy (which RTH open) + APP backtest re-baseline |
| **P1-4** Hawkes α/β=8.0 default | ⏸ deferred | parameter change → new `sensor_version` + data-driven β (no guessed values) |
| **P1-5** Kyle dp/dq alignment | ⏸ deferred | semantic change to a locked-vector sensor; needs sign-off + IC validation |
| **P2-1..5** | ⏸ deferred | research / new-sensor scope |

Deferred items are held pending explicit approval to rebaseline the
locked determinism hashes (`scripts/rebaseline_parity_hashes.py`), since
that is an Inv-5-governed action.

---

## 1. Executive summary

1. **The horizon is a *clock*, not a *window*.** Every rolling Layer-2 feature
   (`RollingZscoreFeature`, `RollingPercentileFeature`) accumulates one sample
   **per sensor event** into a *count-bounded* deque (`max_samples`), and
   `horizon_seconds` only decides *when* `finalize()` fires
   (`rolling_stats.py:142-217`, `aggregator.py:478-489`). The 30 s and 1800 s
   snapshots of the same sensor see near-identical deques. The G16
   `horizon/half_life ∈ [0.5,4]` binding is therefore **decorative** for these
   features — there is no horizon-windowed integration. *(P1, central finding.)*

2. **OFI is never integrated over the horizon.** `ofi_ewma` emits an EWMA
   (α=0.1, O(1)) sampled at the boundary and then z-scored over the last **200
   raw quotes** (`bootstrap.py:1002`). Cont-Kukanov-Stoikov OFI predicts return
   via *integrated* signed flow over a fixed interval; the platform delivers
   last-EWMA-vs-2-to-20-seconds-of-history. For a KYLE_INFO/120 s alpha this is
   a baseline mismatch of ~10–60×. *(P1.)*

3. **`stateful` is unreachable from config.** `SensorSpec.stateful` governs
   whether a throttled accumulator keeps advancing inside the throttle window
   (`spec.py:75-97`, `registry.py:266-303`), but the YAML loader never reads it
   (`platform_config.py:1679-1687`). Any operator who sets `throttled_ms` on
   `ofi_ewma`/`kyle_lambda_60s`/`hawkes_intensity` gets a **silently biased
   estimator** with no way to opt into the documented fix. *(P1 latent footgun.)*

4. **Documented fingerprint sensors do not exist.** The microstructure-alpha
   G16 table cites `inventory_pressure`, `trade_clustering`,
   `liquidity_stress_score`, `quote_flicker_rate`, `kyle_lambda_300s`,
   `micro_price_drift`, `effective_spread` — **none** are implemented under
   `sensors/impl/`. An alpha declaring `l1_signature_sensors:
   [inventory_pressure]` cannot resolve at G6. INVENTORY and LIQUIDITY_STRESS
   families have **zero** real L1 observables. *(P0 doc-vs-impl contract gap.)*

5. **Snapshot contract docstrings are wrong.** Both skills describe
   `HorizonFeatureSnapshot.warm: bool` / `stale: bool` and `z_scores` /
   `percentiles` dicts. The real event has `warm: dict[str,bool]`,
   `stale: dict[str,bool]`, **no** z_score/percentile fields
   (`core/events.py:604-613`); z-scores/percentiles are themselves `feature_id`s
   inside `values`. An alpha following the skill (`if snapshot.warm == True`)
   would mis-gate. *(P1.)*

6. **Kyle-λ regression is mis-aligned in time.** `dp` is the mid change over
   `[prev_trade, this_trade)` while `dq` is *this* trade's signed size
   (`kyle_lambda_60s.py:135-136`). The current trade's price impact lands in the
   *next* sample's `dp`, so the OLS slope regresses *past* drift on *current*
   flow — closer to a flow-autocorrelation/momentum statistic than Kyle's
   contemporaneous price-impact λ. *(P1 modeling, falsifiable.)*

7. **Hawkes branching ratio is advertised unstable and the directional
   information is discarded.** Defaults α=0.4, β=0.05 ⇒ α/β=8.0, emitted
   verbatim as the 4th tuple component while the docstring requires α/β<1 for
   stability (`hawkes_intensity.py:61-63,111`). The only wired feature sums
   λ_buy+λ_sell (`bootstrap.py:1015-1019`) → an **undirected burst magnitude**;
   the signed imbalance (λ_buy−λ_sell)/(λ_buy+λ_sell) is never exposed, and the
   `intensity_ratio` component collapses to max/total ∈ [0.5,1] (sign-free).
   With `warm_trades_per_side=3` (platform.yaml:280) the intensity is statistically
   thin. *(P1.)*

8. **Two time-bases reach the gate vs. the signal.** The regime gate reads
   `_sensor_cache` (latest *event-time* value) while the alpha body reads
   `snapshot.values` (*horizon-boundary* aggregate) — `horizon_engine.py:376,
   591-595`. The same sensor can read differently in the gate and the alpha at
   the same boundary. *(P1 consistency.)*

9. **`spread_z_30d` cannot un-warm across gaps.** Its warm gate is a count
   window (`len(spreads) >= warm_after`), with an explicit "cannot un-warm"
   note (`spread_z_30d.py:148-152`). It has **no** Layer-2 feature, so it only
   reaches alphas through `_sensor_cache`, which is invalidated *only* on a cold
   reading (`horizon_engine.py:307-319`). After a multi-hour gap the gate
   predicate `spread_z_30d < 1.5` can fire on a pre-gap distribution. *(P1
   staleness asymmetry — note this is exactly the fail-safe the other
   event-time sensors implement via S3.)*

10. **VPIN, SNR-drift-diffusion, structural-break are dormant.** Implemented and
    tested (`vpin_50bucket.py`, `snr_drift_diffusion.py`,
    `structural_break_score.py`) but absent from `platform.yaml sensor_specs:`
    and from `_HORIZON_FEATURE_FACTORIES` (`bootstrap.py:997-1045`) → they never
    enter any snapshot. The essay's §4.2 SNR exploitability gate is wired
    nowhere. *(P1/P2.)*

11. **z-normalization windows are inconsistent and horizon-blind.** `ofi_ewma`
    uses `max_samples=200`; every other rolling feature uses the default 2000
    (`bootstrap.py:1002` vs `rolling_stats.py:96`). Cross-sensor z-scores are
    not comparable, and none scale with the alpha horizon. *(P1.)*

12. **No cross-sectional normalization at the boundary.** The aggregator is
    strictly per-symbol by design (correct per the skill), but with a
    single-symbol universe (`platform.yaml:9-10` AAPL) every percentile/z is
    purely self-referential; there is no universe rank available to Layer-2.
    *(P2 — by design, flagged for research.)*

13. **OFI sensor math is correct** (rare positive): the bid/ask contribution
    signs in `ofi_ewma.py:129-141` match Cont, Kukanov & Stoikov (2014) exactly,
    including the ask-up ⇒ +qᵃ_{n-1} convention. No change needed.

14. **Determinism is sound** across the audited path: dedicated sequence
    generators isolate metric/sensor/snapshot streams (`registry.py:146-148`,
    `aggregator.py:313-316`, `horizon_scheduler.py:133-135`), integer boundary
    math (`horizon_scheduler.py:198`), fixed iteration order, replay suites
    green. The "associative over float64" claim in `rolling_stats.py:34-36` is
    technically false but harmless (insertion order is fixed). *(No action.)*

15. **Biggest opportunity:** introduce genuinely horizon-windowed aggregators
    (integrated OFI, realized variance, last-of-window inventory) keyed on
    `horizon_seconds`, plus a signed Hawkes imbalance and a longer/horizon-scaled
    z baseline. These are additive feature_ids — no sensor rewrite, no invariant
    break — and directly raise feature SNR for the shipped KYLE_INFO alpha.

---

## 2. Sensor inventory

Registered in `platform.yaml sensor_specs:` (the live set) plus dormant impls.

| sensor_id | ver | inputs | key params (platform.yaml) | impl default warm | wired Layer-2 feature(s) | registered? |
|---|---|---|---|---|---|---|
| `spread_z_30d` | 1.1.0 | NBBOQuote | window=6000, min_std=1e-9 | warm_after=window (count, **no un-warm**) | none → `_sensor_cache` only | ✅ |
| `quote_replenish_asymmetry` | 1.1.0 | NBBOQuote | window_seconds=5, min_obs=20 | count≥20 ∧ adds on both sides | `_zscore` | ✅ |
| `quote_hazard_rate` | 1.0.0 | NBBOQuote | window_seconds=5, min_samples=20 | n≥20 in window | passthrough | ✅ |
| `ofi_ewma` | 1.1.0 | NBBOQuote | alpha=0.1, warm_after=50, warm_window=300 | sliding 300 s (S3) | passthrough + `_zscore` (max_samples=**200**) | ✅ |
| `micro_price` | 1.1.0 | NBBOQuote | warm_after=1, warm_window=60 | sliding 60 s | passthrough + `_zscore` | ✅ |
| `kyle_lambda_60s` | 1.2.0 | NBBOQuote, Trade | min_samples=30 (window_seconds=60 default) | n≥30 in 60 s | `_zscore` + `_percentile` | ✅ |
| `trade_through_rate` | 1.1.0 | NBBOQuote, Trade | min_trades=5 (window_seconds=30 default) | n≥5 in window | passthrough | ✅ |
| `hawkes_intensity` | 1.2.0 | Trade | warm_trades_per_side=3 (α=0.4,β=0.05,μ=0 defaults) | ≥3/side in 60 s | `_zscore` of λ_buy+λ_sell | ✅ |
| `scheduled_flow_window` | 1.2.0 | NBBOQuote | calendar-injected | has-windows ∧ symbol-eligible | TupleComponent[0,1,3] | ✅ |
| `realized_vol_30s` | 1.3.0 | NBBOQuote | window_seconds=30, warm_after=16 | 16 returns in 30 s | passthrough + `_zscore` | ✅ |
| `vpin_50bucket` | 1.1.0 | Trade | bucket=5000, win=50, min=10 | ≥10 buckets | — | ❌ dormant |
| `snr_drift_diffusion` | 1.3.0 | NBBOQuote | horizons, n_eff=16, warm=4 | 4 returns/horizon | — | ❌ dormant |
| `structural_break_score` | 1.2.0 | NBBOQuote | window=3600 s, λ=0.05, warm=100 | 100 samples ∧ full window | — | ❌ dormant |

All registered specs: `throttled_ms: null`, `input_sensor_ids: []`,
`stateful` unset (not plumbed). DAG is therefore **flat** — no cross-sensor
edges exist in practice (see §4).

---

## 3. Per-sensor audit

### 3.1 `ofi_ewma` (1.1.0) — composite / KYLE_INFO proxy
- **Math.** Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book
  Events" order-flow imbalance, EWMA-smoothed: `e_n` from bid/ask price-and-size
  transitions, `ewma_t = α·e_n + (1-α)·ewma_{t-1}`. **Sign convention verified
  correct** against CKS (`ofi_ewma.py:129-141`), including ask-up ⇒ `+qᵃ_{n-1}`.
- **L1 caveats.** Top-of-book only; depth replenishment beyond L1 invisible.
  Bid/ask size *changes* are read as flow with no trade confirmation — quote
  flicker inflates |OFI|. Degenerate books dropped (`:108`), first quote skips
  EWMA seed (`:118-127`, good for checkpoint restore).
- **Numerics/time.** O(1) accumulator; α=0.1 ⇒ EWMA half-life ≈ 6.6 *events*
  (event-time, **not** calendar) — so its effective memory is quote-rate
  dependent and not aligned to any horizon. Warm = sliding 300 s window (S3,
  un-warms after gap — correct fail-safe).
- **Tests.** `test_ofi_ewma.py` present (sign, warm, determinism). **Gap:** no
  test that OFI EWMA half-life is invariant to quote rate; no integrated-OFI
  reference vector.

### 3.2 `micro_price` (1.1.0) — composite
- **Math.** Stoikov (2018) micro-price `(ask·qᵇ + bid·qᵃ)/(qᵇ+qᵃ)`
  (`micro_price.py:96`). Correct.
- **L1 caveats.** A *level* estimator, not a *drift* — the wired
  `micro_price_zscore` z-scores the level vs its recent mean, which is the
  drift-ish object the reference alpha actually wants, but the raw value scale is
  the price itself (~$100s), so the z-score subtracts a moving mean of prices.
  Over 2000 samples the mean lags the level → z tracks short-term price
  momentum, not bid/ask imbalance. The microstructure intent ("imbalance proxy")
  is **not** what the z delivers. *(Maps to P1 #2/#11.)*
- **Warm.** `warm_after=1` — instant; the `_zscore` feature still needs 30.
- **Tests.** `test_micro_price.py`. **Gap:** no assertion the z reflects
  imbalance rather than price level.

### 3.3 `spread_z_30d` (1.1.0) — LIQUIDITY_STRESS proxy
- **Math.** Welford sliding-window (Pébay 2008) z of the spread; **population**
  variance M2/n, documented deviation from Bessel (`spread_z_30d.py:128-138`).
- **L1 caveats / staleness.** Count-window warm with explicit no-un-warm
  (`:148-152`); the *only* sensor of the registered set that violates the S3
  fail-safe. Combined with `_sensor_cache`-only delivery (no Layer-2 feature,
  no horizon-staleness override), the gate can act on a stale spread
  distribution after a gap. **P1.**
- **Tests.** `test_spread_z_30d.py`. **Gap:** no gap-recovery / un-warm test
  (correctly, because the behavior is by-design wrong); no staleness test of the
  `_sensor_cache` path.

### 3.4 `kyle_lambda_60s` (1.2.0) — KYLE_INFO fingerprint
- **Math.** Kyle (1985) λ via rolling OLS slope of `Δp = λ·Δq`
  (`kyle_lambda_60s.py:160-178`), tick-rule side classification, decremental
  running sums, Cauchy-Schwarz degeneracy guard (`:171-172`). Numerically
  careful and replay-pinned.
- **Modeling bug (P1).** `dp = mid_now − mid_at_prev_trade` pairs the
  *pre-trade* mid change with the *current* trade's `dq` (`:135-136,158`). The
  current trade's impact appears only in the next `dp`. Falsifiable: lag `dq`
  by one trade and λ changes sign/scale on trending tapes. As written it
  measures "does current signed flow correlate with the drift that just
  happened" ≈ flow autocorrelation, not contemporaneous impact.
- **L1 caveats.** Mid sampled from last NBBO before the trade (`:103`); no
  trade-price-vs-quote reconciliation. `min_samples=30` (raised from 5 — see
  platform.yaml:256-260 comment, good).
- **Tests.** `test_kyle_lambda_60s.py`. **Gap:** no test pinning the dp/dq time
  alignment; no IC-style sign test vs forward return.

### 3.5 `realized_vol_30s` (1.3.0) — composite / vol
- **Math.** Bessel-corrected sample std of mid log-returns, Welford
  forward+reverse over 30 s event window (`realized_vol_30s.py:110-139`).
  Rigorous; bad-quote invalidates carry-forward mid (`:98-104`, prevents
  gap-spanning return inflation).
- **L1 caveats.** Quote-driven (not trade) realized vol — captures quote
  jitter as well as true price vol. Unannualized (documented).
- **Tests.** `test_realized_vol_30s.py`. **Gap:** none material.

### 3.6 `hawkes_intensity` (1.2.0) — HAWKES_SELF_EXCITE fingerprint
- **Math.** Two-sided EWMA self-exciting kernel: decay
  `λ←μ+(λ−μ)e^{−βΔt}`, same-side impulse `λ+=α` (`:140-179`). This is a
  *kernel-shaped intensity tracker*, not a fitted Hawkes process (branching
  ratio is a constant param, not estimated — honestly documented).
- **Problems.** (a) α/β=8.0 contradicts the docstring's <1 stability note and is
  emitted as a value (`:111,209`). (b) Only λ_buy+λ_sell is consumed → undirected
  burst magnitude; the directional signal (signed imbalance) is discarded
  (`bootstrap.py:1015-1019`). (c) `intensity_ratio = max/total ∈ [0.5,1]` is
  sign-free (`:196`). (d) `warm_trades_per_side=3` (platform.yaml:280) → thin.
- **Tests.** `test_hawkes_intensity.py`. **Gap:** no test that the consumed
  feature carries direction; no branching-ratio stability assertion.

### 3.7 `quote_replenish_asymmetry` (1.1.0) — INVENTORY-ish proxy
- **Math.** `(bid_adds − ask_adds)/(bid_adds+ask_adds)` over 5 s, counting size
  growth only at unchanged price (`:122-131`) — a thoughtful guard against
  price-step miscounting. Bounded [−1,1].
- **L1 caveats.** Replenishment ≠ hidden liquidity without trade context; pure
  quote-size deltas. Short 5 s window. This is the closest thing to the
  (missing) `inventory_pressure` fingerprint but is *not* the documented sensor.
- **Tests.** `test_quote_replenish_asymmetry.py`. **Gap:** no sign test vs
  one-sided sweep fixture.

### 3.8 `quote_hazard_rate` (1.0.0) — LIQUIDITY_STRESS-ish
- **Math.** `count_in_window / window_seconds` (events/s) over 5 s
  (`:90-91`). A rate, not a hazard in the survival-analysis sense (no
  inter-arrival conditioning). Naming overclaims.
- **Tests.** `test_quote_hazard_rate.py`. **Gap:** none material; consider
  renaming to `quote_arrival_rate`.

### 3.9 `trade_through_rate` (1.1.0) — HAWKES precursor
- **Math.** Rolling fraction of prints at-or-beyond NBBO; **broader than
  Reg-NMS trade-through** (includes the touch) — explicitly documented
  (`:1-12`). `min_trades=5` (platform.yaml:269) is low for a fraction.
- **L1 caveats.** Uses last NBBO before the trade; no fill-vs-quote latency
  model. Honest naming caveat.
- **Tests.** `test_trade_through_rate.py`. **Gap:** none material.

### 3.10 `scheduled_flow_window` (1.2.0) — SCHEDULED_FLOW fingerprint
- **Math.** Calendar membership → 4-tuple (active, secs-to-close, id-hash,
  direction-prior); deterministic salt-free hash (`:55-58`); earliest-`end_ns`
  tie-break (`:114-134`). Clean.
- **L1 caveats.** Not an estimator — a regime clock. `warm` correctly encodes
  symbol-eligibility (`:171-176`).
- **Tests.** `test_scheduled_flow_window.py` + `test_calendar_adapter.py`.
  **Gap:** none material.

### 3.11 Dormant: `vpin_50bucket`, `snr_drift_diffusion`, `structural_break_score`
- `vpin_50bucket`: Easley, López de Prado & O'Hara (2012) VPIN, exact
  volume-conserving buckets, tick-rule (`vpin_50bucket.py`). Solid — **should be
  registered** for a toxicity gate. *(P2.)*
- `snr_drift_diffusion`: per-horizon `|μ|/(σ/√h)` on a shared integer grid with
  correct multi-bar gap collapse (`:170-183`). This is the *only* genuinely
  horizon-windowed estimator in the codebase and is **unused** — wiring it would
  directly implement the §4.2 exploitability gate. *(P1/P2.)*
- `structural_break_score`: Page-Hinkley on |log-return| (not over an upstream
  sensor, as §20.4.4 intends — honestly documented `:10-27`). Kahan-stable.
  *(P2.)*

---

## 4. Sensor DAG & composition

- **Topology.** Every registered spec has `input_sensor_ids: []`
  (platform.yaml). The DAG is a flat fan-out; the registry's topological/cycle
  machinery (`registry.py:166-172`) is exercised only by tests. No implicit
  upstream-future-state lookahead is possible. ✔
- **Acyclicity / isolation.** Per-symbol state keyed `(sensor_id, version,
  symbol)` (`registry.py:213-216`); no cross-symbol leakage. ✔ Inv-5/Inv-6
  hold on this path.
- **Redundancy.** `ofi_ewma`, `micro_price` (via its z), and `kyle_lambda_60s`
  are three correlated reads of the *same* latent (signed informed flow). For
  KYLE_INFO a single sufficient statistic (integrated signed OFI, or λ·Δq
  exposure) would likely dominate the three collinear z-scores the reference
  alpha juggles. *(P2.)*
- **G16 orthogonality gap.** Families map to L1 observables **unevenly**:
  KYLE_INFO has 3 proxies; INVENTORY and LIQUIDITY_STRESS have **named-but-
  unimplemented** fingerprints (#4). SCHEDULED_FLOW and HAWKES each have one.
  This is the most actionable correctness gap for alpha authors.

---

## 5. Horizon aggregation audit (`HorizonAggregator`) — deep dive

**Pipeline.** `_on_sensor_reading` folds each warm reading into every consuming
feature's per-`(feature_id, horizon, symbol)` state (`aggregator.py:345-409`);
`_on_horizon_tick` finalizes the horizon-bucketed feature set and builds one
snapshot (`:411-546`). Buffers (`_buffers`) are forensic only — features keep
their own state (`:223-237` docstring).

### 5.1 Actual aggregation policy per feature type
| Feature | Policy | Window basis | Horizon-sensitive? |
|---|---|---|---|
| `SensorPassthroughFeature` | **last warm value** | none (single slot) | No — pure last-of-stream (`sensor_passthrough.py:81-89`) |
| `RollingZscoreFeature` | z of last value vs deque | **count** (`max_samples`) | **No** (`rolling_stats.py:183-217`) |
| `RollingPercentileFeature` | Hazen pct of last vs deque | **count** (`max_samples`) | **No** (`rolling_stats.py:316-329`) |
| `TupleComponentFeature` | last warm component | none | No |

**Consequence.** There is *no* horizon-windowed mean/sum/EWMA/RV/last-of-bucket
keyed on `horizon_seconds`. The {30,120,300,900,1800}s set multiplies feature
*instances* and snapshot cadence but not the data window. The G16 ratio
constraint, validated upstream, has no effect on the numbers Layer-2 sees. This
is the single highest-leverage finding for "stronger, more tradable inputs."

### 5.2 Boundary alignment
- Integer math `elapsed // (h·1e9)` (`horizon_scheduler.py:198`); `session_open`
  lazily bound to first event (`:174-183`) — deterministic but means the first
  partial bucket of the day is anchored to first-event, not RTH open, unless
  `session_open_ns` is configured (it is `null` in platform.yaml:184). **First
  snapshot of the session is computed on a truncated, first-event-anchored
  bucket** → first-bar bias. *(P1.)*
- Symmetric SYMBOL/UNIVERSE dedup via `_last_snapshot_boundary`
  (`aggregator.py:433-456`) — correct, order-independent. ✔
- Snapshot timestamp = triggering event ts ≥ boundary; uses only readings up to
  that event → **no lookahead** (`:526-545`). ✔

### 5.3 Multi-sensor fusion & quality flags
- Each `feature_id` carries its own `warm`/`stale` (`:511-524`); the snapshot
  never combines conflicting signs — that is left to the alpha body. ✔
- **Staleness override is the real gate** (`:504-510`): finalize always returns
  `stale=False`, and `_last_reading_ns` (warm-only, monotonic — `:358-362`)
  marks a feature stale if its sensor hasn't fired warm within `horizon_ns`.
  Robust for sensors that go silent. ✔
- **But** `spread_z_30d` has no feature, so this override never protects it
  (#9); its freshness lives only in `_sensor_cache`. *(P1.)*
- Passthrough/rolling `warm` latches True forever once seen (cold readings are
  ignored in `observe`); only the staleness override re-suppresses. Acceptable
  given the override, but means `warm` alone is not a freshness signal.

### 5.4 Signal-to-noise for the reference alpha (`sig_benign_midcap_v1`)
- Consumes `ofi_ewma_zscore` and `micro_price_zscore` at horizon 120 s; gate
  uses `spread_z_30d`, `realized_vol_30s_zscore` (`alphas/.../*.alpha.yaml`).
- Hypothesized edge: persistent same-sign OFI ⇒ positive 120 s forward mid
  drift in normal regime (Kyle footprint). **Aggregation smears it**: (a) the z
  baseline is 200 raw quotes (~seconds), so a 120 s-persistent imbalance is
  *normalized away* the moment it persists (it becomes "the mean"); the alpha
  fires on **deviations from the last few seconds**, not on 120 s drift. (b)
  `micro_price_zscore` z-scores a price *level*, leaking momentum.
- **Recommended aggregators** (additive feature_ids, §7): integrated/summed OFI
  over `horizon_seconds` for KYLE_INFO; last-of-horizon for INVENTORY; realized
  variance over the horizon for vol; signed Hawkes imbalance for
  HAWKES_SELF_EXCITE. Each preserves the edge the current count-window z erases.

---

## 6. Mechanism × horizon matrix (G16)

| Family | Half-life env. | Documented fingerprint | Implemented? | Current aggregation | Horizon-appropriate? |
|---|---|---|---|---|---|
| KYLE_INFO | 60–1800 s | kyle_lambda_60s/300s, OFI | partial (no 300s) | last-EWMA z (200-quote baseline) | **No** — wants integrated OFI over h |
| INVENTORY | 10–120 s | `inventory_pressure`, `quote_replenishment_asym` | **neither id exists**; `quote_replenish_asymmetry` is closest | z over 2000-sample count window | **No** — wants last-of-short-horizon |
| HAWKES_SELF_EXCITE | 5–120 s | `hawkes_intensity`, `trade_clustering` | hawkes only; `trade_clustering` missing | z of undirected λ-sum | **No** — wants signed λ imbalance, short h |
| LIQUIDITY_STRESS | 30–600 s | `liquidity_stress_score`, spread_z_30d, `quote_flicker_rate` | **2 of 3 missing**; spread_z exists but no feature | sensor_cache last value (no un-warm) | exit-only; staleness unsafe (#9) |
| SCHEDULED_FLOW | 60–3600 s | scheduled_flow_window | yes | last-value tuple components | acceptable (regime clock) |

Cells in **bold** are the correctness/feature gaps with the largest alpha impact.

---

## 7. Test gap matrix

| Sensor / module | Has tests | Untested invariant (proposed minimal test) |
|---|---|---|
| ofi_ewma | ✔ | EWMA half-life invariance to quote rate; integrated-OFI golden vector |
| kyle_lambda_60s | ✔ | dp/dq time-alignment (lag-shift sign test); sign vs forward-return fixture |
| hawkes_intensity | ✔ | consumed feature carries **direction**; α/β stability warn; warm thinness |
| micro_price | ✔ | z reflects imbalance, not price level (constant-imbalance/rising-price fixture) |
| spread_z_30d | ✔ | gap → un-warm (currently absent because behavior is wrong); `_sensor_cache` staleness |
| RollingZscore/Percentile | ✔ (`test_rolling_*`) | property: window is **count**-bounded ⇒ horizon-independence is explicit & intended? add xfail spec |
| aggregator | ✔ (`test_aggregator`) | first-bar bias at session open (session_open_ns null); horizon-windowed value test |
| dormant trio | ✔ | promotion test: registering them does not break replay hashes |
| **cross-cutting** | — | **golden offline IC/RankIC harness** (see §9) — none exists |

Property-based / golden-replay specs to add (no impl this pass):
1. `test_horizon_window_is_count_not_time` — assert (and decide whether to fix)
   that `RollingZscore` at h=30 and h=1800 produce identical deques given one
   reading stream.
2. `test_session_open_first_bar` — with `session_open_ns=None`, first snapshot
   bucket length < horizon ⇒ flag/skip or document.
3. `test_stateful_throttle_unreachable` — assert YAML cannot set `stateful`
   (guards the footgun until fixed).

---

## 8. Prioritized backlog

### P0 — correctness (do first)
| # | Module | file:line | One-line fix | Impact |
|---|---|---|---|---|
| P0-1 | docs/skills | microstructure-alpha SKILL §G16 table | Replace `inventory_pressure`/`trade_clustering`/`liquidity_stress_score`/`quote_flicker_rate`/`kyle_lambda_300s`/`micro_price_drift`/`effective_spread` with the **implemented** ids, or implement the named sensors | Alpha authors can declare resolvable fingerprints; G6 stops failing on documented ids | M |
| P0-2 | docs/skills | feature-engine SKILL:133-143; microstructure-alpha:202-209 | Correct `HorizonFeatureSnapshot` to `warm: dict`, `stale: dict`, no `z_scores`/`percentiles` | Alphas stop mis-gating on a scalar that is a dict | S |

### P1 — feature strength
| # | Module | file:line | One-line fix | Impact (SNR/usability) |
|---|---|---|---|---|
| P1-1 | features/aggregator + new feature impls | `rolling_stats.py:142-217` | Add horizon-**time-windowed** aggregators (integrated OFI, realized variance, last-of-horizon) keyed on `horizon_seconds` | Makes G16 ratio meaningful; restores 120 s OFI drift edge | L |
| P1-2 | config | `platform_config.py:1679-1687` | Read & plumb `stateful` into `SensorSpec` | Removes silent estimator bias when throttling is enabled | S |
| P1-3 | bootstrap | `bootstrap.py:1015-1019` | Expose **signed** Hawkes imbalance `(λ_buy−λ_sell)/Σ` as a feature | Directional HAWKES signal instead of undirected magnitude | S |
| P1-4 | sensors | `hawkes_intensity.py:81-83` defaults; platform.yaml:280 | Reconcile α/β<1 (or relabel the emitted ratio); raise warm/side | Stable, calibrated intensity | S |
| P1-5 | sensors/kyle | `kyle_lambda_60s.py:135-136,158` | Align `dp` to the interval the trade impacts (or document as flow-autocorr) | λ measures impact, not lagged drift | M |
| P1-6 | engine/sensor | `spread_z_30d.py:148-152`; `horizon_engine.py:307-319` | Give spread_z an S3 event-time un-warm OR a horizon-staleness path | Gate stops firing on stale spread after gaps | M |
| P1-7 | bootstrap | `bootstrap.py:1002` vs `rolling_stats.py:96` | Make z-baseline window horizon-scaled and consistent across sensors | Comparable, horizon-appropriate z-scores | S |
| P1-8 | aggregator | `horizon_scheduler.py:174-183`; platform.yaml:184 | Set `session_open_ns` from RTH open; flag partial first bucket | Removes first-bar-of-day bias | S |
| P1-9 | micro_price feature | `bootstrap.py:1037-1040` | z-score an imbalance/drift object, not the raw price level | Removes momentum leakage in the reference alpha | M |

### P2 — research
| # | Item | Rationale |
|---|---|---|
| P2-1 | Register `vpin_50bucket` + a toxicity gate | Easley-LdP-O'Hara VPIN is a tested, idle toxicity proxy |
| P2-2 | Wire `snr_drift_diffusion` to the §4.2 exploitability gate | Only true horizon-windowed estimator; currently dead |
| P2-3 | Implement the missing INVENTORY/LIQUIDITY_STRESS fingerprints | Gives those families orthogonal L1 observables |
| P2-4 | Collapse OFI/micro/kyle collinearity into one sufficient statistic for KYLE_INFO | Less redundant, lower-variance feature |
| P2-5 | Parameter calibration (α, half-lives, max_samples) from cached NBBO | Replace hand-set constants with data-driven values |

---

## 9. Appendix — open questions needing data runs

Methodology only (no L2 book, per platform constraint):

1. **IC/RankIC by horizon (the decisive test for P1-1).** On cached AAPL NBBO
   (and AAPL/APP if available), compute per-sensor Spearman IC of the *current*
   feature vs forward mid log-return at each h∈{30,120,300,900,1800}s. Compare
   the shipped count-window z against a prototype **integrated-OFI-over-h**. If
   the latter's |IC| rises monotonically toward the G16 envelope while the
   former is flat in h, P1-1 is confirmed quantitatively.
   *(Symbol: AAPL; date: a normal-regime RTH session; metric: RankIC ± SE.)*
2. **Kyle alignment.** Re-estimate λ with `dq` lagged 0 vs 1 trade; report sign
   stability and IC vs forward return. Confirms/[refutes] P1-5.
3. **z-baseline length sweep.** RankIC of `ofi_ewma_zscore` for
   max_samples ∈ {200, 1000, 2000, horizon-scaled}. Picks the P1-7 default.
4. **spread_z staleness.** Inject a synthetic 1 h gap into a replay; measure how
   long `spread_z_30d` retains its pre-gap binding in `_sensor_cache`. Sizes the
   P1-6 risk window.
5. **Hawkes direction.** IC of undirected λ-sum z vs signed λ-imbalance against
   forward return on high-`trade_through_rate` windows. Justifies P1-3.

---

*Prepared read-only. No production code, sensor math, or replay-pinned vectors
were modified. All citations point at the audited revision on branch
`claude/beautiful-tesla-Mrz6f`.*
