<!--
  File:    docs/audits/sensor_audit_2026-06-11.md
  Status:  AUDIT — §1-8 first pass (read-only); §9 remediation (code merged);
           §10 second-pass review + remediation (merged); §11 third-pass
           robustness / logic-soundness review (read-only, 2026-06-13).
  Scope:   Layer-1 sensors → Layer-1.5 horizon aggregation → HorizonFeatureSnapshot.
  Method:  Static read of src + YAML + tests; full suite 3311 pass / 43 skip
           (4 pre-existing env failures) after the §9 remediation.
  Owner:   feature-engine (sensors + aggregator); touchpoints into bootstrap,
           microstructure-alpha, data-ingestion noted but not owned here.
-->

# Sensor & Horizon-Aggregation Audit — 2026-06-11

**Mandate.** Evidence-based, read-only audit of the L1 sensor framework and its
path into `HorizonFeatureSnapshot`. Find where the math is rigorous vs heuristic,
where aggregation dilutes signal, and what changes yield stronger Layer-2 inputs
without breaking platform invariants. **No fixes implemented in this pass.**

**Verification run (read-only).**
`tests/sensors/` → 170 passed, 1 skipped.
`tests/determinism/{test_sensor_reading_replay,test_horizon_feature_snapshot_replay,test_v03_sensor_replay,test_horizon_tick_replay}` + `tests/features/` → 122 passed.
No production source was modified.

Severity legend: **P0** correctness (math/lookahead/determinism/sign) · **P1**
feature strength (aggregation, redundancy, normalization) · **P2** research.
Each finding tags *implementation bug* / *modeling choice* / *L1 identifiability
limit* per the quality bar.

---

## 1. Executive summary (top risks & opportunities)

1. **`micro_price_zscore` is effectively a momentum proxy, not a microstructure
   signal — the single highest-impact finding (P1, modeling).** `micro − mid =
   (spread/2)·imbalance` (algebra of `micro_price.py:94`), i.e. **sub-cent**,
   while the micro-price *level* z-scored in `bootstrap.py:1178-1183` is ~$100
   with cents of variance driven almost entirely by price drift. The reference
   alpha gates on `micro_price_zscore` as "L1 footprint confirmation"
   (`sig_benign_midcap_v1.alpha.yaml:143-159`) but is really confirming
   *price momentum*, not bid/ask imbalance. The imbalance content the Stoikov
   micro-price is meant to carry is ≲0.01 % of the feature variance.
2. **No sensor exposes the size-imbalance / `micro−mid` quantity at all (P1, L1
   identifiability + gap).** The legacy `BidAskImbalanceComputation`
   (`features/library.py:43-60`) is never wired as a sensor. The one structural
   L1 edge the platform repeatedly *names* (queue imbalance) is unobservable
   downstream.
3. **`kyle_lambda_60s` default class version ships the wrong-sign estimator
   (P0-adjacent, modeling).** Class default is `1.2.0` / `alignment="legacy"`
   (`kyle_lambda_60s.py:49,74`), which the repo's own cached IC shows carries
   the **wrong sign** at KYLE horizons (`platform.yaml:260-267`: legacy RankIC
   −0.22…−0.19 vs causal +0.15). Reference config correctly pins `2.0.0`/causal,
   but any code path that constructs the sensor without explicit params (tests,
   ad-hoc harnesses) silently gets the inverted estimator.
4. **OFI EWMA decays in *event* time, not calendar time (P1, modeling /
   time-basis).** `α=0.1` per quote (`ofi_ewma.py:142`, `platform.yaml:233-238`)
   ⇒ half-life ≈ 6.6 *quotes* ≈ 0.07–0.7 s wall-clock — two to four orders of
   magnitude shorter than the KYLE_INFO 60–1800 s envelope it serves. The
   boundary value is near-instantaneous flow; the horizon z-score re-aggregates
   noise. **Integrated OFI** (`reducer="sum"`) is the literature-correct Kyle
   input and is already supported by `HorizonWindowedFeature` but unused.
5. **`exp`/`log` sensors put bit-identical cross-platform replay (Inv-5) at
   risk (P1, determinism).** `math.exp` (hawkes, liquidity_stress) and
   `math.log` (realized_vol, snr, structural_break) are not guaranteed
   correctly-rounded across libm versions; parity hashes are only valid within
   one libm. The skill claims "bit-identical across runs" — true per-host, not
   cross-host.
6. **Registry does not enforce the `throttled_ms` ⇒ `stateful=True` rule it
   documents (P1, latent correctness).** `spec.py:75-97` calls the unflagged
   combination "undefined behaviour"; `__post_init__` (`spec.py:99-126`) never
   checks it. All reference sensors are accumulators with `throttled_ms: null`,
   so it is dormant — but a single future throttle config silently biases the
   estimator.
7. **Snapshot timestamp is the *triggering event* time, not the boundary time
   (modeling, document — not a bug).** `aggregator.py:520` stamps the snapshot
   at `tick.timestamp_ns` = the real crossing event (`horizon_scheduler.py:313`);
   the theoretical boundary time lives only in the correlation_id
   (`horizon_scheduler.py:304`). On sparse names a "30 s" snapshot can be
   emitted well after the nominal boundary → first/last-of-day buckets are
   ragged. Causal (no lookahead), but introduces horizon jitter for thin symbols.
8. **Scheduler emits `boundary_index = 0` (None-sentinel), contradicting the
   design-doc pseudocode and an in-tree comment (P2, doc/impl drift).**
   `horizon_scheduler.py:242-243` emits the first observed boundary even when it
   is 0; design §7.4 inits `_last_boundary=0` (never emits 0); `aggregator.py:260-266`
   asserts "scheduler currently emits boundary_index ≥ 1". Harmless (empty
   window) but the three sources disagree — a determinism-relevant ambiguity.
9. **Sensor families are not sign-reconciled inside a snapshot (P1, modeling).**
   `inventory_pressure` is mean-reverting (positive ⇒ expect *up*,
   `inventory_pressure.py:124-143`) while `ofi_ewma` is momentum (positive ⇒
   continuation). Both land in one snapshot with no orthogonalization; an alpha
   consuming both must hand-resolve the contradiction.
10. **`hawkes_intensity` λ outputs are unnormalized impulse units, not
    events/second (P2, modeling).** The docstring says "per second"
    (`hawkes_intensity.py:18-30`) but λ is an additive-impulse EWMA
    (`:181-188`); only β's half-life `ln2/β` is dimensionally meaningful. The
    `α/β` "impulse-decay ratio" is *not* a branching ratio.
11. **`calibrate_hawkes.py` fits a different model than the sensor implements
    (P2, modeling mismatch).** The script MLE-fits a *true* self-exciting Hawkes
    (`calibrate_hawkes.py:4-12`, branching ratio α/β<1) but the sensor is an
    EWMA-impulse tracker whose α has no branching-ratio meaning — only β/half-life
    transfers cleanly.
12. **No sign / monotonicity test exists for any sensor's economic claim (P1,
    test gap).** `inventory_pressure` tests only assert the `[-1,1]` bound
    (`test_inventory_pressure.py:97`); kyle/ofi/hawkes have no "positive flow ⇒
    positive value" golden. Sign regressions (the costliest microstructure bug)
    are untested.
13. **`realized_vol_30s` correctly kept on a *count* window after an IC
    regression (good); but the decision is undocumented outside a code comment
    (P2).** `bootstrap.py:1197-1207` records count-window RankIC 0.523 vs
    horizon-window 0.191 at 1800 s — strong evidence, but only in a comment, not
    a tracked experiment.
14. **`vpin_50bucket`, `snr_drift_diffusion`, `structural_break_score` ship but
    are dormant (not in `platform.yaml`); `structural_break_score` also does not
    implement its design intent (cross-sensor PH over `hawkes_intensity`)** —
    it runs PH over mid-returns with empty `input_sensor_ids`
    (`structural_break_score.py:16-27`). The advertised G16 coverage is
    nominal, not wired.
15. **Opportunity: most normalization gaps are *aggregation-policy* changes, not
    new sensors.** Integrated-OFI for Kyle, a `micro−mid` reducer, last-of-horizon
    for fast inventory, and cross-sectional standardization at the boundary (L3)
    are all reachable inside the existing `HorizonFeature` surface.

---

## 2. Sensor inventory

Source: `platform.yaml:193-361` (specs) + `sensors/impl/*.py` (defaults).
"Reg?" = present in reference `platform.yaml`. "Clock" = time basis driving the
window/decay. Warm = warm-up criterion.

| # | sensor_id | ver (cfg) | inputs | key params | deps | throttle | warm criterion | clock | reg? |
|---|-----------|-----------|--------|------------|------|----------|----------------|-------|------|
| 1 | `ofi_ewma` | 1.1.0 | NBBOQuote | α=0.1, warm_after=50, warm_window=300 s | — | null | ≥50 quotes in 300 s window | **event-paced EWMA** | ✓ |
| 2 | `micro_price` | 1.1.0 | NBBOQuote | warm_after=1, warm_window=60 s | — | null | ≥1 valid quote in 60 s | event-time | ✓ |
| 3 | `kyle_lambda_60s` | 2.0.0 | NBBOQuote, Trade | window=60 s, min_samples=30, alignment=causal | — | null | ≥30 trades in window | event-time (60 s) | ✓ |
| 4 | `spread_z_30d` | 1.1.0 | NBBOQuote | window=6000, min_std=1e-9 | — | null | deque full (6000); **cannot un-warm** | **count** (6000 quotes) | ✓ |
| 5 | `realized_vol_30s` | 1.3.0 | NBBOQuote | window=30 s, warm_after=16 | — | null | ≥16 returns in 30 s | event-time (30 s) | ✓ |
| 6 | `quote_replenish_asymmetry` | 1.1.0 | NBBOQuote | window=5 s, min_obs=20 | — | null | ≥20 quotes **and** ≥1 add/side | event-time (5 s) | ✓ |
| 7 | `quote_hazard_rate` | 1.0.0 | NBBOQuote | window=5 s, min_samples=20 | — | null | ≥20 quotes in window | event-time (5 s) | ✓ |
| 8 | `trade_through_rate` | 1.1.0 | NBBOQuote, Trade | window=30 s, min_trades=5 | — | null | ≥5 trades in window | event-time (30 s) | ✓ |
| 9 | `hawkes_intensity` | 1.2.0 | Trade | α=0.4, β=0.05, warm_window=60 s, warm/side=10 | — | null | ≥10 trades/side in 60 s | **calendar** (exp decay) | ✓ |
| 10 | `scheduled_flow_window` | 1.2.0 | NBBOQuote | calendar (injected) | — | null | calendar has symbol-eligible window | wall (calendar) | ✓ |
| 11 | `inventory_pressure` | 1.0.0 | Trade | window=60 s, min_trades=20 | — | null | ≥20 trades in window | event-time (60 s) | ✓ |
| 12 | `liquidity_stress_score` | 1.0.0 | NBBOQuote | window=6000, sensitivity=2.0 | — | null | deque full (6000) | count (6000) | ✓ |
| 13 | `quote_flicker_rate` | 1.0.0 | NBBOQuote | window=5 s, min_quotes=20 | — | null | ≥20 quotes in window | event-time (5 s) | ✓ |
| 14 | `vpin_50bucket` | 1.1.0 | Trade | bucket=5000, window=50, min=10 | — | n/a | ≥10 filled buckets | **volume** | ✗ dormant |
| 15 | `snr_drift_diffusion` | 1.3.0 | NBBOQuote | horizons, n_eff=16, warm/h=4, anchor=0 | — | n/a | ≥4 returns every horizon | grid (per-h) | ✗ dormant |
| 16 | `structural_break_score` | 1.2.0 | NBBOQuote | window=3600 s, λ=0.05, warm=100 | **()** (intent: hawkes) | n/a | ≥100 samples ∧ span ≥ window | event-time (3600 s) | ✗ dormant |

**DAG note.** No shipped sensor declares a cross-sensor edge
(`input_sensor_ids=()` everywhere); the DAG is a flat fan-out. The only intended
edge (`structural_break_score`→`hawkes_intensity`) is deferred
(`structural_break_score.py:21-27`). The registry's topological-order enforcement
(`registry.py:166-172`) is therefore currently exercised only negatively. **No
implicit upstream-future lookahead is possible** because there are no edges.

---

## 3. Per-sensor audit

Conventions: estimator stated in math; literature cited author-year; "L1 caveat"
flags identifiability / discretization loss; "tests" maps coverage.

### 3.1 `ofi_ewma` — composite (KYLE_INFO support)

- **Estimator.** Cont–Kukanov–Stoikov order-flow imbalance:
  `e_t = bid_contrib + ask_contrib` with the canonical level/size rules, then
  `ewma_t = α·e_t + (1−α)·ewma_{t−1}`. **The sign convention matches CKS exactly**
  (`ofi_ewma.py:127-139`): bid up ⇒ `+q^b`, bid down ⇒ `−q^b_{prev}`, equal ⇒
  `Δq^b`; ask symmetric. Verified line-by-line — *rigorous*. **Cite:** Cont,
  Kukanov & Stoikov (2014), "The Price Impact of Order Book Events," *J. Financial
  Econometrics* 12(1).
- **L1 caveat.** OFI at L1 sees only top-of-book; depth replenishment behind the
  best is invisible (modeling-acknowledged limit, not a bug).
- **Numerics.** First-quote bootstrap skips the EWMA fold to avoid re-seeding a
  restored state toward 0 (`:116-125`) — correct. Degenerate-book guard
  `bid≤0 ∨ ask≤0` (`:106-107`). No div-by-zero.
- **Time basis (P1).** α is per *event*, so decay half-life is ~6.6 quotes; in
  calendar time this is sub-second and rate-dependent (bursts decay faster). The
  KYLE envelope (60–1800 s) is served only after the horizon window re-aggregates.
  → see backlog **P1-A** (integrate, don't z-score).
- **Warm-up.** Sliding-window (`:149-165`) correctly un-warms after gaps (S3). Good.
- **Tests.** `test_ofi_ewma.py` (7): determinism, warm transition, bootstrap.
  **No sign golden** ("net bid lift ⇒ positive EWMA").

### 3.2 `micro_price` — composite (KYLE_INFO support)

- **Estimator.** Stoikov size-weighted price
  `micro = (ask·bid_sz + bid·ask_sz)/(bid_sz+ask_sz)` (`micro_price.py:94`),
  mid fallback when depth = 0 with `warm=False`. **Cite:** Stoikov (2018), "The
  Micro-Price," *Quantitative Finance* 18(12).
- **Critical caveat (P1, the headline).** The *informative* part is
  `micro − mid = (spread/2)·imbalance` — at most half a spread (sub-cent for
  liquid names). The sensor emits the **level** (~$100), and the wired feature
  z-scores the level (`bootstrap.py:1178-1183`). Variance of the level is
  dominated by price drift; the imbalance signal is ≲0.01 %. **The Stoikov edge
  is destroyed at the feature layer.** A `micro − mid` (or `(micro−mid)/spread`)
  reducer/sensor is required to recover it. The `micro_price_drift` (delta)
  feature (`bootstrap.py:1188-1193`) is `≈ Δmid` — also momentum, not imbalance.
- **Tests.** `test_micro_price.py` (6): formula, degenerate book. No
  imbalance-recovery assertion (because the quantity is not exposed).

### 3.3 `kyle_lambda_60s` — KYLE_INFO fingerprint

- **Estimator.** OLS slope of `Δp = λ·Δq` over a 60 s rolling window via
  maintained sums (`kyle_lambda_60s.py:194-211`). **Cite:** Kyle (1985),
  "Continuous Auctions and Insider Trading," *Econometrica* 53(6). Tick-rule
  signing of `Δq` (`:150-156`).
- **Sign/alignment (P0-adjacent, modeling).** Class default `1.2.0`/`legacy`
  pairs `Δp` over `[t−1,t)` with the *current* trade's flow — a
  flow-autocorrelation, not contemporaneous impact, and the repo's own cached IC
  shows it **carries the wrong sign** (`platform.yaml:260-267`). Causal `2.0.0`
  pairs `Δp` with `Δq_{t−1}` (`:162-166`) — correct and still causal (Inv-6 holds;
  both quantities known at trade *t*). **Reference config pins causal** — but the
  *class default* is the inverted one. Any construction without explicit
  `alignment` (a real risk in new tests / harnesses) gets the wrong sign.
- **Numerics.** Relative degeneracy guard `denom ≤ 1e-12·n·sum_dq2`
  (`:204-205`) with associativity explicitly pinned to the golden vector — sound;
  prevents OLS blow-up under near-constant `Δq`.
- **L1 caveat.** `Δp` uses NBBO mid carried to the trade timestamp; a stale NBBO
  between trades biases λ. The `last_nbbo_mid=None` invalidation on bad quotes
  (`:122-125`) is correct.
- **Tests.** `test_kyle_lambda_60s.py` (11): both alignments, window eviction,
  degeneracy. Good coverage; still no positive-control sign golden tying a known
  impact to a positive λ.

### 3.4 `spread_z_30d` — LIQUIDITY_STRESS (single-axis)

- **Estimator.** Welford sliding-window z of spread `z = (s−μ)/σ`
  (`spread_z_30d.py:96-138`), **population** variance `M2/n` (`:130-133`,
  documented divergence from Bessel). **Cite:** Pébay (2008) for the stable
  sliding update; the z-score itself is standard.
- **Caveat (modeling).** "30d" is a misnomer — window is 6000 *quotes* (count,
  not days). Documented. **Cannot un-warm** once the deque fills (`:148-152`):
  unlike event-time sensors there is no S3 reversion, so after a long halt the
  z-score is computed against a pre-halt distribution until 6000 fresh quotes
  flush. → backlog **P1-E**.
- **Tests.** `test_spread_z_30d.py` (6): Welford correctness, min_std floor.

### 3.5 `realized_vol_30s` — composite (LIQUIDITY_STRESS support)

- **Estimator.** Bessel-corrected sample std of mid log-returns over a 30 s
  event-time window via reverse-Welford (`realized_vol_30s.py:108-137`). Sound.
- **Caveat.** Bad-quote `last_mid=None` invalidation (`:96-101`) correctly avoids
  a log-return spanning the gap (which would inflate vol). Unannualized
  (documented).
- **Aggregation note (good).** The wired feature is a **count-window** z
  (`RollingZscoreFeature`, `bootstrap.py:1203-1207`), kept deliberately after an
  IC regression vs horizon-window — recorded only in a code comment.
- **Tests.** `test_realized_vol_30s.py` (6): gap reset, Welford.

### 3.6 `quote_replenish_asymmetry` — INVENTORY fingerprint

- **Estimator.** `(bid_adds − ask_adds)/max(bid_adds+ask_adds, ε)` over 5 s,
  counting size growth **only when the best price is unchanged**
  (`quote_replenish_asymmetry.py:118-127`) — a genuinely careful guard against
  miscounting a price step as replenishment. Bounded `[−1,1]`. **Cite (mechanism):**
  Ho & Stoll (1981) inventory paradigm.
- **L1 caveat (identifiability).** True replenishment *speed* needs hidden/iceberg
  detection; at L1 only displayed-size deltas are visible. The sensor proxies
  asymmetry of *displayed* additions — a weak proxy for the inventory mechanism
  it fingerprints. No documented directional return claim.
- **Tests.** `test_quote_replenish_asymmetry.py` (8): price-step guard, eviction.

### 3.7 `quote_hazard_rate` — LIQUIDITY_STRESS (single-axis)

- **Estimator.** `hazard = N_window / window_seconds` (events/s) over 5 s
  (`quote_hazard_rate.py:86-87`). A rate, not a fitted point-process hazard.
- **Caveat (modeling).** This is a quote-arrival *count rate*, not a conditional
  hazard λ(t|history); the "hazard" name overstates it. Unbounded above; not
  normalized cross-symbol (a fast name always reads high). For gating it needs a
  per-symbol baseline (none applied; the passthrough exposes the raw rate,
  `bootstrap.py:1101-1103`).
- **Tests.** `test_quote_hazard_rate.py` (7): window count, warm.

### 3.8 `trade_through_rate` — HAWKES precursor / aggression

- **Estimator.** Rolling fraction of prints with `price ≥ ask ∨ price ≤ bid`
  over 30 s (`trade_through_rate.py:111`). **Honestly documented** as
  *NBBO-aggression* (touch-or-cross), **not** Reg-NMS trade-through (strictly
  outside) — `:6-12`. Good naming discipline.
- **L1 caveat.** Uses last-quote NBBO at trade time; a stale quote misclassifies.
  Bad-quote guard preserves prior NBBO (`:95-98`). `min_trades=5`
  (`platform.yaml:291`) is thin — a 5-print window gives a fraction on a
  {0,…,5}/5 lattice; high variance.
- **Tests.** `test_trade_through_rate.py` (9): touch vs cross, NBBO staleness.

### 3.9 `hawkes_intensity` — HAWKES_SELF_EXCITE fingerprint

- **Estimator.** Two one-sided EWMA-impulse intensities:
  decay `λ ← μ + (λ−μ)e^{−βΔt}` (`hawkes_intensity.py:147-152`, **true calendar
  decay** — good), impulse `λ ← λ + α` on a same-side trade (`:181-188`).
  Emits `(λ_buy, λ_sell, ratio, α/β)`. **Cite:** Hawkes (1971); Bacry, Mastromatteo
  & Muzy (2015) survey.
- **Caveat (P2, modeling).** This is **not** a fitted Hawkes — the impulse never
  feeds back into arrival generation (docstring is admirably explicit,
  `:27-30`). Hence: (a) λ is in arbitrary impulse units, not events/s despite the
  "per second" label (`:18`); (b) `α/β` is an impulse-decay ratio, **not** a
  branching ratio — the `<1` stability reading does not apply. Only `ln2/β` is
  dimensionally meaningful.
- **Calibration mismatch (P2).** `scripts/calibrate_hawkes.py` MLE-fits a *true*
  self-exciting Hawkes (`calibrate_hawkes.py:4-12`); its α is not transferable to
  this EWMA-impulse sensor (only β/half-life is). Calibrating the sensor from
  that script's α would be a category error.
- **Tests.** `test_hawkes_intensity.py` (8): decay, impulse, two-sided warm,
  ratio neutral state.

### 3.10 `scheduled_flow_window` — SCHEDULED_FLOW fingerprint

- **Estimator.** Time-of-day window membership from an injected `EventCalendar`;
  emits `(active, secs_to_close, id_hash, direction_prior)`
  (`scheduled_flow_window.py:162-170`). Deterministic salt-free SHA-256 id hash
  (`:55-58`) — correctly avoids `PYTHONHASHSEED` non-determinism.
- **Caveat.** US-only in v0.3 (design §20). Warm gate is scope-aware (`:171-176`)
  — good (catches EARNINGS_DRIFT-for-AAPL consumed by MSFT). The
  `direction_prior` is a *config input*, not a measured edge — tradability rests
  entirely on calendar curation.
- **Tests.** `test_scheduled_flow_window.py` (7) + `test_calendar_adapter.py` (10).

### 3.11 `inventory_pressure` — INVENTORY fingerprint (trade-side)

- **Estimator.** `Σ(−aggressor·size)/Σ size` over 60 s, bounded `[−1,1]`
  (`inventory_pressure.py:124-143`); positive ⇒ MM net long ⇒ expects up-revert.
  **Cite:** Ho & Stoll (1981); Madhavan & Smidt (1991).
- **Caveat (L1 identifiability).** MM inventory is unobservable; the sensor
  *infers* sign from tick-rule aggressor. The mean-reversion sign is the
  **opposite** of `ofi_ewma`'s momentum sign by construction — a fusion hazard
  (see §4.4). Reasonable proxy, but the inferential leap (aggressor ⇒ MM
  inventory ⇒ reversion) is two modeling assumptions deep.
- **Tests.** `test_inventory_pressure.py` (9): **bound only** (`:97`), eviction,
  warm. **No sign golden** — the economic claim is untested.

### 3.12 `liquidity_stress_score` — LIQUIDITY_STRESS fingerprint (composite)

- **Estimator.** `score = 1 − exp(−(max(0,z_spread)+max(0,z_thin))/k)` ∈ [0,1]
  (`liquidity_stress_score.py:167-174`), one-sided z on spread-widening and
  depth-thinning via the same Welford scheme as `spread_z_30d`. Genuinely a
  two-axis alarm; unsigned, exit-only (correct per G16).
- **Caveat.** Scores the incoming sample against the *prior* baseline before
  folding it in (`:163-171`) — correct (no self-contamination). `exp` →
  cross-platform determinism caveat. Count-window (cannot un-warm) like
  `spread_z_30d`.
- **Tests.** `test_liquidity_stress_score.py` (9): two-axis, one-sidedness.

### 3.13 `quote_flicker_rate` — LIQUIDITY_STRESS fingerprint

- **Estimator.** Trailing-window fraction of quotes on which either best price
  *reverses* its last non-zero direction (`quote_flicker_rate.py:113-124`),
  ∈ [0,1]. Reasonable spoofing/instability proxy.
- **Caveat.** "Reversal" counts any up-then-down at the best — captures normal
  two-sided quoting as well as manipulation; high baseline on actively two-sided
  names. Not normalized cross-symbol.
- **Tests.** `test_quote_flicker_rate.py` (8): reversal detection, fraction.

### 3.14 `vpin_50bucket` — flow toxicity (dormant)

- **Estimator.** Mean absolute bucket imbalance over 50 volume buckets, tick-rule
  signed, exact volume conservation via spill (`vpin_50bucket.py:117-141`).
  **Cite:** Easley, López de Prado & O'Hara (2012), *RFS* 25(5). Faithful.
- **Caveat (well-known).** VPIN's predictive validity is contested (Andersen &
  Bondarenko 2014). Tick-rule signing on L1 trades (no Lee-Ready). Dormant — not
  in `platform.yaml`.
- **Tests.** `test_vpin_50bucket.py` (8): bucket fill, spill conservation.

### 3.15 `snr_drift_diffusion` — exploitability gate (dormant)

- **Estimator.** Per-horizon `SNR(h)=|μ_h|/(σ_h/√h)` on an integer-ns grid with
  closed-form multi-bar EWMA catch-up (`snr_drift_diffusion.py:140-180`) — the
  gap-handling (split `r/N`, decay `(1−λ)^N`) is mathematically careful and
  correctly avoids O(N) variance inflation.
- **Caveat.** `grid_anchor_ns=0` (epoch) default (`:152-153`) means the bar grid
  is not session-aligned unless an anchor is passed; first bar per symbol is
  ragged. Dormant. `log` determinism caveat.
- **Tests.** `test_snr_drift_diffusion.py` (7): grid snap, multi-bar collapse.

### 3.16 `structural_break_score` — diagnostic (dormant, intent unmet)

- **Estimator.** One-sided Page-Hinkley on |mid log-return| with rolling
  reference mean, Kahan-compensated sum (`structural_break_score.py:182-203`).
  Numerically careful. **Cite:** Page (1954) CUSUM/Page-Hinkley.
- **Caveat (modeling, intent unmet).** Design §20.4.4 intends PH over an
  *upstream sensor* (`hawkes_intensity`); the implementation runs PH over
  raw mid-returns with `input_sensor_ids=()` (`:16-27`). Honest provenance, but
  the advertised cross-sensor "alpha is dying" diagnostic does not exist yet. A
  *rolling* reference baseline also self-tracks slow drifts (documented `:50-59`),
  reducing sensitivity to exactly the gradual decay it targets.
- **Tests.** `test_structural_break_score.py` (7): PH cumulant, alarm threshold.

---

## 4. Horizon aggregation audit (deep dive — `HorizonAggregator`)

### 4.1 Mechanics & determinism (sound)

- **Pull, not push** (`aggregator.py:5-13`): one bus subscription each for
  `SensorReading`/`HorizonTick`; features never subscribe. O(1) handler count.
- **Iteration determinism** (Inv-C): features pre-sorted by
  `(feature_id, horizon, version)` (`:152-157`) and pre-bucketed by horizon
  (`:178-183`); symbols sorted (`:185`). No per-tick re-sort. **Sound.**
- **Sequence isolation** (Inv-A): dedicated `_snapshot_seq` (`:34-39`). Adding the
  aggregator cannot perturb pre-existing sequences. **Sound.**
- **Symmetric SYMBOL/UNIVERSE dedup** (`:405-435`): both scopes consult
  `_last_snapshot_boundary` so `(symbol,horizon,boundary)` is unique regardless of
  tick-scope arrival order. **Sound** (previously UNIVERSE-only; now fixed).
- **Warm-only monotonic freshness clock** (`:352-356`): `_last_reading_ns`
  advances only on *warm* readings and only forward — out-of-order late arrivals
  cannot regress freshness, cold readings don't refresh. **Sound.**

### 4.2 What aggregation policy is actually applied (per feature)

The aggregation is **entirely determined by the `HorizonFeature` wired in
`bootstrap.py:1050-1209`**, not by a per-horizon policy table. Catalogue:

| Sensor | Wired feature(s) | Reducer / policy | Window basis |
|--------|------------------|------------------|--------------|
| `spread_z_30d` | passthrough | **last warm** | n/a (last) |
| `ofi_ewma` | passthrough + `_zscore` | last; **z over event-time window h** | event-time `h` |
| `kyle_lambda_60s` | `_zscore`, `_percentile` | z + Hazen percentile, window `h` | event-time `h` |
| `quote_replenish_asymmetry` | `_zscore` | z, window `h` | event-time `h` |
| `quote_hazard_rate` | passthrough | last warm | n/a |
| `inventory_pressure` | passthrough + `_zscore` | **last** + z | event-time `h` |
| `liquidity_stress_score` | passthrough | last | n/a |
| `quote_flicker_rate` | passthrough + `_zscore` | last + z | event-time `h` |
| `hawkes_intensity` | `_zscore`(Σλ) + `_imbalance` | z of burst magnitude + signed imbalance | event-time `h` |
| `trade_through_rate` | passthrough | last | n/a |
| `scheduled_flow_window` | 3× tuple component | last (active/secs/dir) | n/a |
| `micro_price` | passthrough + `_zscore` + `_drift` | last + **z of level** + delta | event-time `h` |
| `realized_vol_30s` | passthrough + `_zscore` | last + **count-window z** | **count** (2000) |

**Key observations:**

1. **No `sum`/integrated reducer is used anywhere**, although
   `HorizonWindowedFeature` supports it (`horizon_windowed.py:61,280-281`). For
   **Kyle/OFI the integrated (cumulative) flow over the horizon is the
   literature-correct input** (price impact ∝ Σ signed flow); z-scoring an
   event-paced EWMA instead is strictly weaker. → **P1-A**.
2. **`micro_price_zscore` z-scores a level** — momentum, not imbalance (§1.1). The
   horizon-windowing (P1-1 work) actually *amplifies* the problem at long
   horizons: a wider window = more price drift = even more momentum-dominated.
3. **`realized_vol_30s` is the lone count-window survivor** — kept after a
   documented IC regression (`bootstrap.py:1197-1207`). This is the *right* call
   and the right kind of evidence; it should be promoted from comment to a tracked
   experiment artifact.
4. **Ratio horizon/half-life (G16 `[0.5,4.0]`).** The *feature* window equals the
   alpha horizon (30…1800 s), but several *sensors* have internal half-lives far
   from it: `ofi_ewma` (~0.1–0.7 s), `hawkes` (`ln2/0.05≈13.9 s`), `kyle`
   (60 s window). At horizon 1800 s the ofi-EWMA/horizon ratio is ~10⁴ — the
   sensor is reset-fast relative to the decision horizon, so the boundary value
   is essentially a single fast sample re-standardized. The G16 binding governs
   *alpha* half-life vs horizon, but does **not** constrain *sensor* internal
   timescale vs horizon — a real gap.

### 4.3 Boundary alignment & partial buckets

- **Snapshot timestamp = crossing-event time** (`aggregator.py:520`;
  `horizon_scheduler.py:313` stamps `ts_ns=ts`, boundary time only in
  correlation_id at `:304`). Causal and deterministic, but on sparse names the
  realized window `[tick.ts − h, tick.ts]` ends *after* the nominal boundary →
  horizon jitter. For the first snapshot of the session the window reaches back
  before the session anchor (empty → cold). **First/last-of-day snapshots are
  structurally raggeder than mid-session.** Document + consider gating entries in
  the first `h` seconds.
- **`boundary_index=0` emission** (`horizon_scheduler.py:242-243`) vs design §7.4
  (`_last_boundary=0`, never emits 0) vs aggregator comment "emits ≥1"
  (`aggregator.py:260-266`). Three-way disagreement; behaviorally harmless
  (empty window) but should be reconciled and pinned by a test (it is a
  determinism-surface ambiguity).

### 4.4 Multi-sensor fusion & sign conflicts (P1, modeling)

The snapshot is a flat `dict[feature_id→value]`; **the aggregator performs no
orthogonalization or sign reconciliation** (`aggregator.py:450-511`). Concretely,
`ofi_ewma_zscore` (momentum: +flow ⇒ continuation) and `inventory_pressure`
(reversion: +absorbed-selling ⇒ up-revert) can carry **opposite implications for
the same forward return** and coexist in one snapshot. Today only
`sig_benign_midcap_v1` is wired (OFI + micro-price), so no live conflict — but the
moment an alpha consumes both INVENTORY and KYLE fingerprints it must resolve the
contradiction by hand, with no platform support. **Collinearity** is the dual
risk: `micro_price_zscore`, `ofi_ewma_zscore`, and `micro_price_drift` are all
mostly **price-momentum** (per §1.1), so an alpha "confirming" OFI with
micro-price is largely confirming a signal with itself.

### 4.5 Staleness & warm propagation (sound, with one caveat)

- Per-feature `warm`/`stale` populated for **every** registered feature; `values`
  holds **warm only** (`aggregator.py:498-506`). Correct — consumers distinguish
  "not warm" from "computed zero".
- Stale override (`:491-497`): a feature is stale if any input sensor produced no
  *warm* reading within `h`. Correct fail-safe (suppresses entry, permits exit).
- **Caveat.** Throttled stateful sensors emit only outside the throttle window, so
  `_last_reading_ns` could lag by the throttle interval and spuriously mark a
  feature stale. Moot in the reference config (no throttles) but couples to the
  unenforced `stateful` rule (§1.6).

---

## 5. Mechanism × horizon × aggregation matrix (G16)

Half-life envelopes from microstructure-alpha SKILL §G16. "Ratio" = horizon /
expected half-life; G16 requires ∈ [0.5, 4.0].

| Family | Half-life env. | Fingerprint sensor (wired feature) | Current aggregation | Recommended aggregation | Rationale |
|--------|----------------|-------------------------------------|---------------------|--------------------------|-----------|
| KYLE_INFO | 60–1800 s | `kyle_lambda_60s` (`_zscore`,`_percentile`); `micro_price`(`_zscore`); `ofi_ewma`(`_zscore`) | z of event-paced/level quantities | **integrated OFI (`sum`)**, `(micro−mid)/spread`, λ-percentile | impact ∝ Σ signed flow; level-z is momentum |
| INVENTORY | 5–60 s | `quote_replenish_asymmetry`(`_zscore`); `inventory_pressure`(last+z) | last + z over `h` | **last-of-horizon** at h=30 only | fast/mean-reverting; long-h z smears the reversion |
| HAWKES_SELF_EXCITE | 5–60 s | `hawkes_intensity`(`_zscore`Σλ, `_imbalance`) | z of burst + signed imbalance | keep, but **h=30** binding; calibrate β | half-life ~14 s ⇒ only h=30/120 in [0.5,4] |
| LIQUIDITY_STRESS | 30–600 s | `vpin`(dormant),`realized_vol`(z); `liquidity_stress_score`,`spread_z_30d`,`quote_hazard_rate`,`quote_flicker_rate` (last/z) | last / count-z | last-of-horizon (alarms already [0,1]) | exit-only; magnitude not direction — last is fine |
| SCHEDULED_FLOW | 60–1800 s | `scheduled_flow_window` (3× component) | last (active/secs/dir) | **last** (correct) | clock state, not an aggregate |

**Orthogonality verdict.** Each family has ≥1 dedicated implemented fingerprint
(coverage is nominally complete). **But** within KYLE the three observables are
not orthogonal (all momentum-loaded), and the INVENTORY pair
(`quote_replenish_asymmetry` quote-side, `inventory_pressure` trade-side) are
genuinely complementary — the better diversification is *inside* INVENTORY, not
KYLE.

---

## 6. Test gap matrix

Coverage from `tests/sensors/` (counts in §2 inventory). ✓ = asserted, ✗ = gap.

| Sensor | determinism | warm transition | gap/un-warm recovery | bounds | **sign / economic** | numeric edge |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|
| ofi_ewma | ✓ | ✓ | ✓ (S3) | n/a | **✗** | ✓ bootstrap |
| micro_price | ✓ | ✓ | ✓ | ✓ | **✗** (imbalance not exposed) | ✓ depth=0 |
| kyle_lambda_60s | ✓ (golden 1.2.0) | ✓ | ✓ evict | n/a | **✗** (positive-control) | ✓ denom |
| spread_z_30d | ✓ | ✓ | **✗ cannot un-warm** | n/a | n/a | ✓ Welford |
| realized_vol_30s | ✓ | ✓ | ✓ gap reset | ≥0 ✓ | n/a | ✓ Bessel |
| quote_replenish_asymmetry | ✓ | ✓ | ✓ | ✓ [−1,1] | **✗** | ✓ step-guard |
| quote_hazard_rate | ✓ | ✓ | ✓ | ≥0 | n/a | ✓ |
| trade_through_rate | ✓ | ✓ | ✓ | [0,1] ✓ | partial (touch/cross) | ✓ |
| hawkes_intensity | ✓ | ✓ | ✓ window | ratio∈[.5,1] ✓ | **✗** | ✓ decay |
| scheduled_flow_window | ✓ | ✓ (scope) | n/a | n/a | n/a (config) | ✓ hash |
| inventory_pressure | ✓ | ✓ | ✓ | ✓ [−1,1] | **✗** (only bound) | ✓ |
| liquidity_stress_score | ✓ | ✓ | n/a | [0,1] ✓ | n/a (unsigned) | ✓ one-sided |
| quote_flicker_rate | ✓ | ✓ | ✓ | [0,1] ✓ | n/a | ✓ |
| vpin_50bucket | ✓ | ✓ | n/a | [0,1] ✓ | **✗** | ✓ spill |
| snr_drift_diffusion | ✓ | ✓ | ✓ multibar | ≥0 | n/a | ✓ collapse |
| structural_break_score | ✓ | ✓ | ✓ | [0,1] ✓ | n/a | ✓ Kahan |

**Aggregator-level gaps (no test asserts):** (a) sign-conflict fusion of two
families in one snapshot; (b) `boundary_index=0` behaviour pinned; (c)
cross-platform `exp`/`log` parity (only single-host parity is locked).

**Proposed minimal new tests (specs only — not implemented this pass):**

- **TG-1 (property, per signed sensor).** Construct a synthetic stream with
  monotone one-sided pressure (e.g. all aggressive buys); assert
  `ofi_ewma>0`, `kyle λ>0` (causal), `inventory_pressure<0`, hawkes
  `λ_buy>λ_sell`. Locks the economic sign — the single most valuable missing test.
- **TG-2 (golden).** `micro_price` with `bid_sz≫ask_sz` ⇒ `micro>mid` by exactly
  `(spread/2)·imbalance`; assert the magnitude to pin that the imbalance content
  is sub-cent (documents the §1.1 finding as an executable invariant).
- **TG-3 (replay).** Pin `boundary_index` of the first emitted snapshot for a
  session whose first event lands exactly on the anchor (resolve §4.3 ambiguity).
- **TG-4 (un-warm).** `spread_z_30d` / `liquidity_stress_score`: after a
  `>window` event-time gap, assert the z is computed against post-gap data (will
  currently fail → confirms P1-E).
- **TG-5 (determinism, cross-impl).** Recompute one `exp`/`log` sensor under a
  reference rational approximation and assert agreement to N ulps, bounding the
  cross-libm replay risk.

**Offline validation harness (methodology, extends `scripts/sensor_feature_ic.py`):**

- Per `(feature_id, horizon, variant)` compute Spearman RankIC and Pearson IC of
  the warm boundary value vs **forward mid log-return over the same horizon**
  (already implemented, `sensor_feature_ic.py:305-324`; no-lookahead drop at
  `:238-246`). **Extend** with: (i) an `ofi_integrated` variant
  (`reducer="sum"`) vs `ofi_ewma_zscore`; (ii) a `micro_minus_mid` synthetic
  feature vs `micro_price_zscore` to quantify the §1.1 loss; (iii) regime-conditional
  IC (split by HMM `normal`/`vol_breakout`) since the reference alpha's edge is
  conditional. Run on cached AAPL + a second name (e.g. a thinner mid-cap) across
  ≥20 sessions; report sample-weighted pooled RankIC with t-stats
  (`_aggregate_across_days`, `:507-544`).

---

## 7. Prioritized backlog

Effort: **S** ≤0.5 d · **M** 0.5–2 d · **L** >2 d. Each item: target ·
file:line · one-sentence fix · expected SNR/alpha impact.

### P0 — correctness (math / lookahead / determinism / sign)

| ID | Target | file:line | Fix | Impact |
|----|--------|-----------|-----|--------|
| P0-1 | `kyle_lambda_60s` default | `kyle_lambda_60s.py:49,74` | Flip the class default to `alignment="causal"`/`2.0.0` (or make `alignment` required) so no construction path silently yields the wrong-sign estimator; keep `1.2.0` reachable only by explicit opt-in for the golden vector. **(modeling)** | Removes a latent sign-inversion for any non-config consumer; protects KYLE alphas. **S** |
| P0-2 | sign goldens (all signed sensors) | `tests/sensors/*` | Add TG-1 positive-control tests. **(test)** | Makes the costliest class of bug (sign) regression-visible. **M** |
| P0-3 | cross-platform replay | hawkes/realized_vol/snr/structural/liquidity | Document Inv-5 as **per-libm**, add TG-5 ulp-bound test, and pin the libm/host in parity-hash provenance. **(determinism)** | Converts a silent replay risk into a known, bounded one. **M** |

### P1 — feature strength (aggregation / redundancy / normalization)

| ID | Target | file:line | Fix | Impact |
|----|--------|-----------|-----|--------|
| P1-A | OFI for KYLE | `bootstrap.py:1067-1075` | Add an `ofi_ewma` **`reducer="sum"`** (integrated signed flow over `h`) feature; prefer it over the level-EWMA z for KYLE alphas. **(modeling)** | Aligns the feature with Kyle's `Δp∝Σq`; expected RankIC lift at 300–1800 s (validate via §6 harness). **S** |
| P1-B | micro-price imbalance | `micro_price.py:94`, `bootstrap.py:1176-1193` | Expose `(micro−mid)` or `(micro−mid)/spread` (new reducer/sensor); deprecate `micro_price_zscore` as a "footprint" input. **(L1 identifiability + impl)** | Recovers the Stoikov imbalance edge currently lost (~0.01 % of variance today). **M** |
| P1-C | size-imbalance sensor | `features/library.py:43-60` (unused) | Wire a top-of-book size-imbalance sensor `(bid_sz−ask_sz)/(bid_sz+ask_sz)` with a no-liquidity sentinel. **(gap)** | Adds the one structural L1 observable the docs keep naming but never expose. **M** |
| P1-D | throttle/stateful guard | `spec.py:99-126` | Reject (or loudly warn) `throttled_ms` set on a sensor with `stateful=False`. **(impl)** | Closes the documented "undefined behaviour" landmine before any throttle ships. **S** |
| P1-E | count-window un-warm | `spread_z_30d.py:148-152`, `liquidity_stress_score.py:176` | Add an event-time staleness/reset path so a long halt flushes the pre-halt distribution. **(modeling)** | Prevents post-halt z-scores against stale baselines (TG-4). **M** |
| P1-F | INVENTORY aggregation | `bootstrap.py:1108-1116` | Restrict `inventory_pressure` features to last-of-horizon at h=30 (drop long-h z that smears a 5–60 s mean-reversion). **(modeling)** | Matches G16 half-life; reduces dilution. **S** |
| P1-G | hazard/flicker normalization | `bootstrap.py:1101-1103,1123-1131` | Pass `quote_hazard_rate`/`quote_flicker_rate` through a per-symbol z (regime-relative) rather than raw last. **(modeling)** | Makes thresholds comparable across symbols. **S** |
| P1-H | fusion/orthogonality doc + guard | `aggregator.py:450-511` | Document that snapshot fusion is caller-resolved; add a research note flagging KYLE collinearity and INVENTORY↔KYLE sign conflict. **(modeling)** | Prevents alphas from self-confirming or sign-fighting. **S** |

### P2 — research / literature-aligned rewrites

| ID | Target | file:line | Fix | Impact |
|----|--------|-----------|-----|--------|
| P2-1 | true Hawkes vs EWMA | `hawkes_intensity.py:18-30`, `calibrate_hawkes.py:4-12` | Either (a) relabel sensor outputs as impulse-EWMA (drop "per second"/branching) — cheap; or (b) implement a true exp-kernel Hawkes so the calibrator's α/β transfer. **(modeling)** | Removes model/calibration mismatch; honest units. **S(a)/L(b)** |
| P2-2 | structural_break cross-sensor | `structural_break_score.py:16-27` | Implement the §20.4.4 intent (PH over `hawkes_intensity` via `input_sensor_ids`), requires registry SensorReading routing. **(impl)** | Delivers the advertised "alpha is dying" diagnostic. **L** |
| P2-3 | cross-sectional standardization | composition layer (out of L1 scope) | Standardize fingerprint features cross-sectionally at the boundary (z within universe) in Layer 3. **(consumer impact — not L1)** | `IR=IC·√N` breadth; explicitly L3 per invariants, noted for downstream. **L** |
| P2-4 | data-driven sensor timescales | `ofi_ewma.py:142`, `hawkes` β | Calibrate α/β/half-lives from cached data per symbol-class instead of hand-set defaults. **(modeling)** | Aligns sensor internal timescale with the served horizon (§4.2.4 gap). **M** |
| P2-5 | promote IC evidence | `bootstrap.py:1197-1207` | Move the realized-vol count-vs-window IC decision from a comment into a tracked experiment artifact under `docs/`/research. **(process)** | Makes aggregation choices auditable & revisitable. **S** |

---

## 8. Appendix — open questions needing data runs

Each needs a cached-NBBO replay (methodology in §6). Symbols: AAPL (liquid) + one
thinner mid-cap to expose sparsity effects; ≥20 RTH sessions.

1. **Integrated vs z-scored OFI (P1-A).** RankIC of `ofi_ewma` `reducer="sum"`
   vs `_zscore` by horizon {30,120,300,900,1800}. Hypothesis: `sum` wins ≥300 s.
2. **Micro-price imbalance recovery (P1-B).** RankIC of synthetic
   `(micro−mid)/spread` vs `micro_price_zscore`; and decompose `micro_price_zscore`
   variance into price-drift vs imbalance components to quantify the §1.1 loss.
3. **Kyle alignment confirmation.** Re-run `_kyle_alignment_ab`
   (`sensor_feature_ic.py:423-486`) on the wider panel to confirm the
   `platform.yaml:260-267` sign-flip generalizes beyond the original cache.
4. **Regime-conditional IC.** Split RankIC by HMM `normal` vs `vol_breakout`;
   does the reference alpha's claimed conditional edge survive only in `normal`?
5. **Sensor-internal-timescale vs horizon.** Sweep `ofi_ewma` α and `hawkes` β;
   find the (α,β) maximizing pooled RankIC at each served horizon — tests the
   §4.2.4 "sensor reset-fast relative to decision horizon" hypothesis.
6. **Sparse-name horizon jitter (§4.3).** On the thin mid-cap, measure the
   distribution of `snapshot.timestamp_ns − nominal_boundary_ns` and the
   first/last-of-day bucket bias; decide whether to gate entries in the first `h`.
7. **Throughput.** Confirm any added `sum`/`micro−mid` reducers keep the
   aggregator within the 200 µs/snapshot budget (perf-engineering skill) before
   wiring to production.

---

## 9. Remediation status (2026-06-11 follow-up pass)

The backlog above was subsequently implemented. Status of every item:

### P0 — done

- **P0-1 (done).** `KyleLambda60sSensor` class default flipped to
  `alignment="causal"` / version `2.0.0` (`sensors/impl/kyle_lambda_60s.py`);
  the wrong-sign `legacy`/`1.2.0` estimator is now opt-in only. Test fixtures
  that relied on the old default updated (`tests/_fixtures/sensor_specs.py`,
  `tests/integration/test_phase4_e2e.py`, `tests/sensors/fixtures/_generate.py`
  pins the locked legacy vector explicitly).
- **P0-2 (done).** Sign positive-control goldens added
  (`tests/sensors/test_sensor_sign_goldens.py`) for ofi, kyle (causal),
  inventory_pressure, hawkes, book_imbalance.
- **P0-3 (partial / documented).** Per-libm caveat documented in
  `tests/determinism/parity_manifest.py`; intra-process reproducibility of the
  `exp`/`log` sensors locked by
  `tests/determinism/test_transcendental_determinism.py`. **Deferred:** pinning
  the libm/host fingerprint into parity-hash *provenance* (cross-cutting
  plumbing owned by the data-ingestion / determinism harness) and the full
  cross-host ulp bound.

### P1 — done

- **P1-A (done).** `ofi_ewma_integrated` (`reducer="sum"`) feature wired
  (`bootstrap.py`).
- **P1-B / P1-C (done).** New `book_imbalance` sensor
  (`sensors/impl/book_imbalance.py`, registered in `platform.yaml`) — the
  signed top-of-book size imbalance that *is* the Stoikov footprint
  (`(micro−mid)/spread = book_imbalance/2`). The reference alpha
  `sig_benign_midcap_v1` now confirms with `book_imbalance` instead of the
  momentum-laden `micro_price_zscore`.
- **P1-D (done).** `SensorSpec.__post_init__` now warns on the
  `throttled_ms`-without-`stateful` footgun
  (`tests/sensors/test_spec_throttle_guard.py`).
- **P1-E (done).** Opt-in `max_gap_seconds` event-time reset added to
  `spread_z_30d` and `liquidity_stress_score`; enabled at 300 s in
  `platform.yaml`. Default `None` preserves the locked golden vectors.
- **P1-F (done).** `inventory_pressure` restricted to last-of-horizon at h=30.
- **P1-G (done).** `quote_hazard_rate` gained a regime-relative windowed z.
- **P1-H (done).** No-cross-feature-fusion / collinearity contract documented in
  the `HorizonAggregator` module docstring.

### P2 — mixed

- **P2-1 (done, option a).** Hawkes λ outputs relabeled as impulse-EWMA units
  (dropped the misleading "per second").
- **P2-5 (done).** Realized-vol aggregation IC evidence promoted to
  `docs/research/realized_vol_aggregation_ic.md`.
- **P2-2 (deferred).** Cross-sensor Page-Hinkley over `hawkes_intensity`
  requires the registry to route `SensorReading` to downstream sensors — a
  v0.4 hot-path change with its own determinism surface; out of scope for this
  pass. `structural_break_score` remains dormant.
- **P2-3 (deferred — out of L1 scope).** Cross-sectional standardization is a
  Layer-3 (composition) concern by platform invariant; not implemented here.
- **P2-4 (deferred — data-dependent).** Data-driven α/β/half-life calibration
  needs cached-data IC runs (no dataset in this environment); tracked in §8.

### Known follow-up requiring the APP dataset

Re-pointing `sig_benign_midcap_v1` to `book_imbalance` changes its signals on
the APP tape, so the **data-gated** baselines in
`tests/acceptance/test_backtest_app_baseline.py` (`_BASELINE_NET_PNL`,
`_BASELINE_FILL_COUNT`, and the combined parity hash) must be re-baked on a host
with the APP dataset. The **dataset-free** config-contract hash in that file was
re-baked in this pass; the PnL/fill baselines were not (no dataset available).

### Verification

`tests/sensors/`, `tests/features/`, `tests/determinism/`, `tests/alpha/`,
`tests/bootstrap/test_composition_wiring.py`,
`tests/integration/test_phase4_e2e.py`, and the active-aggregator acceptance
test pass. Pre-existing environment failures unrelated to this work
(`tests/ingestion/test_massive_ingestor.py` mocked-REST cases,
`tests/acceptance/test_mypy_strict_scope.py`) are unchanged.

---

## 10. Second-pass review (2026-06-12)

This pass audits the §9 remediation itself — including code I added — for new
issues, overstated fixes, and regressions. Findings are numbered `2P-*`. Three
of them (`2P-1`, `2P-2`, `2P-3`) are partly *self-inflicted*: the remediation
introduced or amplified them. Nothing here is a hard test failure; they are
correctness-of-semantics and feature-strength issues. No code was changed in
this second pass — these are documented for a follow-up.

### 2P-1 (P1, **amplified by this remediation**) — `required_warm` gates alphas on features they never read

`_feature_ids_for_sensor_at_horizon` (`bootstrap.py:1280-1291`) adds **every**
feature whose `input_sensor_ids` contains a depended sensor to the alpha's
`required_warm_feature_ids` — *regardless of whether the alpha's `evaluate()`
reads it*. The `HorizonSignalEngine` suppresses entry until all of them are
warm. So adding an auxiliary feature to a sensor silently raises the entry bar
for every alpha that depends on that sensor.

**Concrete regression I introduced:** `sig_inventory_revert_v1` consumes the
*raw* `quote_hazard_rate` in both its gate (`quote_hazard_rate < 4.0`) and
`evaluate()` (`hazard = snapshot.values.get("quote_hazard_rate")`,
`sig_inventory_revert_v1.alpha.yaml:199-203`) — it never reads a z-score. P1-G
added `quote_hazard_rate_zscore` (`bootstrap.py`), which now enters this alpha's
`required_warm` set and must reach its `min_samples=20` warm-up before the alpha
may enter, even though the alpha ignores it. Same shape for P1-A
(`ofi_ewma_integrated` now required-warm for `sig_benign`, which reads only
`ofi_ewma_zscore`) and P1-B (`book_imbalance_zscore` required-warm for
`sig_benign`, which reads only the `book_imbalance` passthrough).

- **Falsifiable:** on a thin name where `quote_hazard_rate` warms but fires
  < 20 times within a 30 s window, `sig_inventory_revert_v1` is now suppressed
  where it previously would have entered. (On liquid names the 20-sample
  warm-up is sub-second, so the practical impact is small — but the *semantics*
  are wrong: the alpha is gated on data it does not use.)
- **Pre-existing, but worse:** the pattern predates the remediation
  (`micro_price_drift` was already required-but-unused for `sig_benign`), but
  P1-A/P1-G/P1-B each added another required-but-unused feature.
- **Fix (P1):** derive `required_warm` from the features the alpha *actually
  consumes* — parse the `signal:` body for `values.get("…")` keys (or honour a
  declared `consumed_features` whitelist) — instead of the union over all
  depended sensors' features. Decouples G16 fingerprint declaration from
  runtime gating. **Effort: M.** Touches `bootstrap._required_warm_feature_ids_for_signal_alpha`
  and may shift `signal_replay` / acceptance gating → rebaseline.

### 2P-2 (P1, **overstated fix**) — `ofi_ewma_integrated` is not a flow integral

P1-A wired `HorizonWindowedFeature("ofi_ewma", h, reducer="sum")` and called it
"integrated OFI." Two problems make the label overstate it:

1. **It sums the EWMA, not raw flow.** The sensor emits the *EWMA* of OFI, so
   the `sum` reducer sums an already-low-passed series. Each raw OFI event is
   smeared across the EWMA's decay tail and thus counted many times with
   geometric weights — this is a decaying-weighted cumulative, **not** Kyle's
   `Σ signed flow`.
2. **It scales with quote count.** The `sum` reducer returns `mean * n`
   (`horizon_windowed.py:281`), where `n` is the number of in-window readings.
   `n` tracks the *quote rate*, not the flow, so `ofi_ewma_integrated` at a busy
   moment is mechanically larger than at a quiet one for identical net flow —
   and it is not comparable across symbols or time. A z-score or threshold on it
   inherits the quote-rate contamination.

- **Falsifiable:** hold net signed flow fixed and double the quote rate ⇒
  `ofi_ewma_integrated` roughly doubles.
- **Fix (P1):** to get a true Kyle input, have the OFI sensor emit *cumulative
  raw OFI* (reset per horizon or as a running sum the feature differences), or
  add a count/time-normalised integral reducer. Until then, prefer
  `ofi_ewma_zscore` over `ofi_ewma_integrated` and treat the latter as
  experimental. **Effort: M** (sensor change).

### 2P-3 (P2, **L1 limit + aggregation choice on new sensor**) — `book_imbalance` is noisy at L1 and sampled last-of-horizon

The P1-B/C `book_imbalance` sensor recovers the right *quantity*
(`(micro−mid)/spread`), but two caveats temper the win:

1. **Displayed-size imbalance is a weak L1 proxy.** SIP NBBO sizes are
   round-lot-quantised, exclude hidden/iceberg depth, and are trivially gameable
   (post-and-pull). The imbalance computed from displayed sizes is therefore
   noisy and partially adversarial — the same critique the first pass made of
   `quote_flicker_rate`. This is an L1 identifiability limit, not a bug.
2. **Last-of-horizon sampling is high-variance.** The wired confirmation is
   `SensorPassthroughFeature("book_imbalance", h)` — the *single* most-recent
   warm reading at the boundary (`bootstrap.py`). One instantaneous quote's
   imbalance is a high-variance snapshot; a short-window mean/EWMA would be a
   steadier confirmation.

- **Fix (P2):** confirm `sig_benign` with a `reducer="mean"` (or a short EWMA)
  of `book_imbalance` over the horizon rather than the raw last reading; keep
  the passthrough for gate identifiers. **Effort: S.**

### 2P-4 (P2) — `micro_price` is now a dead dependency held only for G16

After P1-B, `sig_benign_midcap_v1` no longer reads any `micro_price` feature,
yet still declares `micro_price` in `depends_on_sensors` and
`l1_signature_sensors`. It cannot simply be dropped: G16 rule 5 requires a
*primary* KYLE fingerprint (`kyle_lambda_60s` **or** `micro_price`) to appear in
`depends_on_sensors`, and the alpha does not depend on `kyle_lambda_60s`. So
`micro_price` is retained purely to satisfy G16, while contributing three
required-but-unused features (compounding `2P-1`). This exposes a structural
tension: **G16 fingerprint declaration and `required_warm` gating are coupled
through `depends_on_sensors`.** Resolving `2P-1` (consume-driven `required_warm`)
also resolves the gating half of this; the declaration half is by-design.
**Effort: subsumed by 2P-1.**

### 2P-5 (P2, doc accuracy) — snapshot-replay golden no longer mirrors bootstrap

`tests/determinism/test_horizon_feature_snapshot_replay.py` wires
`ofi_ewma` → passthrough + `HorizonWindowedFeature(zscore)` and comments that it
"mirrors `_horizon_features_for()` in bootstrap." After P1-A, bootstrap also
emits `ofi_ewma_integrated`, so the golden's feature slice is now a strict
*subset* of production, and the "mirrors" comment is stale. Not a correctness
bug (the golden is a deterministic slice), but either add the integrated feature
and rebaseline `EXPECTED_LEVEL3_SNAPSHOT_HASH`, or downgrade the comment to
"a slice of bootstrap." **Effort: S.**

### 2P-6 (P2, residual from P2-1) — Hawkes μ/α/λ units still inconsistent

P2-1 relabelled `λ_buy`/`λ_sell` as "arbitrary impulse units," but the class
docstring still documents `baseline_mu` as "events/second"
(`hawkes_intensity.py`). If λ is in arbitrary impulse units then μ (the level λ
decays toward) and α (the impulse) must share those units; "events/second" for
μ is inconsistent with "arbitrary" for λ. Either fully commit to dimensionless
impulse units across μ/α/λ, or normalise the impulse so λ really is events/s.
**Effort: S** (doc) **/ L** (true normalisation).

### 2P-7 (informational) — `book_imbalance` is a better but not orthogonal confirmation

`book_imbalance` is a genuine improvement over `micro_price_zscore` for the
`sig_benign` footprint check: it is level-invariant and carries queue-state
rather than price-momentum, so it is far less collinear with `ofi_ewma_zscore`
than the old confirmation was. But it is not *independent* of OFI — both read
top-of-book queue dynamics (OFI from size *changes*, `book_imbalance` from size
*levels*), so they share information when the book builds directionally. A truly
orthogonal confirmation would come from a different observable channel (e.g.
trade-side aggression). This is a refinement, not a defect; recorded so the
"independent L1 confirmation" claim is not overread.

### Second-pass backlog

| ID | Sev | One-line fix | Effort |
|----|-----|--------------|--------|
| 2P-1 | P1 | Derive `required_warm` from consumed `values.get(...)` keys, not all depended-sensor features | M |
| 2P-2 | P1 | Emit cumulative raw OFI (or a rate-normalised integral) instead of `sum` over the EWMA | M |
| 2P-3 | P2 | Confirm with a short-window mean/EWMA of `book_imbalance`, not last-of-horizon | S |
| 2P-5 | P2 | Reconcile the snapshot-replay golden with bootstrap (add integrated + rebaseline, or fix comment) | S |
| 2P-6 | P2 | Make Hawkes μ/α/λ units consistent (doc, or normalise to events/s) | S/L |

### Second-pass remediation status (2026-06-13)

- **2P-1 (done).** `required_warm` is now *consume-driven*: bootstrap statically
  parses the `signal:` body (`_consumed_value_keys_from_signal_source`,
  `bootstrap.py`) for the `snapshot.values` keys the alpha actually reads and
  gates only on those, with a conservative fall-back to the old all-features set
  when the keys cannot be resolved (dynamic key, aliased `.values`, missing
  source). The source is threaded through `LoadedSignalLayerModule.signal_source`.
  `sig_inventory_revert_v1` no longer requires the unread `quote_hazard_rate_zscore`;
  `sig_benign` no longer requires the unread `micro_price*` views — which also
  resolves the gating half of **2P-4**. Tests:
  `tests/bootstrap/test_required_warm_consume_driven.py`.
- **2P-2 (done).** New `ofi_raw` sensor (`sensors/impl/ofi_raw.py`, registered in
  `platform.yaml`) emits the per-event signed OFI, so the `sum` reducer now
  yields the genuine integrated flow `Σ ofi_t` (`ofi_integrated`, each event
  counted once). The misleading sum-over-EWMA `ofi_ewma_integrated` was removed.
  Tests: `tests/sensors/test_ofi_raw.py`.
- **2P-3 (done).** Added `book_imbalance_mean` (horizon-window mean) and
  re-pointed `sig_benign_midcap_v1`'s confirmation to it instead of the noisy
  last-of-horizon `book_imbalance` passthrough.
- **2P-5 (resolved by 2P-2).** With `ofi_ewma_integrated` removed, the
  `ofi_ewma` factory is back to passthrough + z-score, so the snapshot-replay
  golden's "mirrors bootstrap" comment is accurate again (the golden hash was
  never affected — it wires its own slice).
- **2P-6 (done).** Hawkes `baseline_mu` doc corrected — μ/α/λ are documented as a
  single arbitrary impulse-unit system; only β carries physical (1/s) units.
- **2P-7** — informational; no action (recorded so the "independent confirmation"
  claim is not overread).

Re-baked the dataset-free config-contract hash. The data-gated APP PnL/fill
baselines still require re-baking on a host with the dataset (the reference
alpha's signals changed). Full suite green apart from the same pre-existing
environment failures (`massive` / `dotenv` / `yaml`-stub absence).

*End of audit (second-pass remediation appended 2026-06-13).*

---

## 11. Third-pass review — algorithm robustness & logic soundness (2026-06-13)

This pass applies an institutional-grade robustness lens: numerical stability,
data-quality failure modes, fail-safe containment, and logic soundness across
the whole path (sensors → aggregator → snapshot → gate/signal), **including the
code added in passes 1–2**. The bar is "what breaks in production on a bad tick,
a crossed quote, or a million-event session" — not "does the unit test pass."
Findings are `3P-*`. This pass is read-only; no code was changed. Two findings
are P0/P1-class and one (`3P-3`) is a logic regression introduced in `2P-3`.

### 3P-1 (P0, institutional) — no NaN/Inf containment anywhere on the path

The feature-engine SKILL "Failure Modes" table promises a safeguard:
*"NaN / Inf in sensor value → post-update value check → suppress emission; emit
`Alert`; flag `provenance.valid = False`"* (`feature-engine/SKILL.md:327`). **No
such check exists anywhere.** The registry publishes the sensor's value verbatim
(`registry.py:282` `raw = sensor.update(...)` → `:303` `self._bus.publish(reading)`
→ `_stamp` `:358` `value=reading.value`, no finiteness test); the aggregator
stores it with a bare `float(value)` (`aggregator.py:521`); and `signals/` /
`risk/` contain no `isfinite`/`isnan` guard either (grep: empty). So a single
non-finite sensor value propagates **unbounded** with three compounding harms:

1. **Permanent accumulator poisoning.** A NaN folded into a
   `HorizonWindowedFeature` reverse-Welford (`horizon_windowed.py:169-189`)
   sets `mean`/`M2` to NaN forever — every subsequent z-score/mean/sum for that
   `(feature, symbol, horizon)` is NaN for the rest of the session, and the
   `M2 < 0 → 0` clamp does not catch NaN (`NaN < 0` is `False`).
2. **Silent gate corruption.** A NaN in `snapshot.values` makes every gate
   comparison evaluate `False` (`NaN < 1.5` is `False`), so the ON/OFF latch
   silently takes the wrong branch instead of failing safe.
3. **NaN sizing.** A NaN reaches `Signal.edge_estimate_bps`, then position
   sizing — a non-finite target quantity is the textbook institutional
   incident.

- **Falsifiable:** inject one `float('nan')` `SensorReading` for a windowed
  feature; every later snapshot value for that feature is NaN and entries are
  no longer gated by the real condition.
- **Fix (P0):** implement the documented contract at the registry emission
  boundary — reject non-finite `value` (and each tuple component), suppress the
  emission, emit `Alert`, set `provenance.valid = False`; add a defensive
  finiteness guard at `aggregator.py:521` so a feature bug cannot poison the
  snapshot. **Effort: M.** This is the single most important institutional gap
  in the layer.

### 3P-2 (P1, institutional / data-quality) — no crossed/locked-market guard

Every price-consuming sensor guards only `bid <= 0 or ask <= 0`
(e.g. `spread_z_30d.py:93`, `liquidity_stress_score.py:157`, `micro_price.py:84`)
— **none reject a crossed (`bid > ask`) or locked (`bid == ask`) NBBO**, which
occur routinely in fast markets, around halts, and from SIP consolidation
latency. The consequences are silent and sometimes sign-inverted:

- `spread_z_30d` folds a **negative** spread into its rolling mean/variance,
  distorting the entire spread distribution and every subsequent z-score.
- `liquidity_stress_score` is **inverted** on a cross: `z_spread` goes strongly
  negative, and `excess = max(0, z_spread) + max(0, z_thin)`
  (`liquidity_stress_score.py:195,173`) drops the spread axis to **0** — so a
  crossed book (an acute stress / dislocation event) reads as *zero stress*,
  exactly backwards for an exit-only alarm.
- `micro_price` can return a value **outside `[bid, ask]`** when the book is
  crossed (`micro_price.py:94`), feeding a nonsensical "fair price."

- **Fix (P1):** add a shared crossed/locked guard to the price-consuming
  sensors (reject `bid >= ask`, or treat crossed as a degenerate book like the
  `bid<=0` path and reset carry-forward mids), or filter crossed/locked NBBO at
  the normalizer so the whole sensor layer sees only valid books. **Effort: M.**

### 3P-3 (P1, logic soundness — regression introduced in 2P-3) — dead `imb == 0.0` guard

The reference alpha's neutral-rejection guard `if imb == 0.0: return None`
(`sig_benign_midcap_v1.alpha.yaml:166`) was sound when `imb` was the
last-of-horizon `book_imbalance` passthrough (exactly `0.0` when
`bid_size == ask_size`). After `2P-3` re-pointed it to `book_imbalance_mean` — a
float **mean** over many in-window readings — exact `0.0` essentially never
occurs, so the guard is **dead code**: a near-zero mean (no real queue
confirmation) now passes the footprint check and can fire a signal on noise.

- **Falsifiable:** feed a `book_imbalance_mean` of `1e-9` with `z` above
  threshold ⇒ a signal fires, where the intent was to require a *meaningful*
  same-side imbalance.
- **Fix (P1):** replace exact equality with an epsilon band, e.g.
  `if abs(imb) < params["imbalance_floor"]: return None`. **Effort: S.**
  **Note:** this re-touches the reference alpha, so it will re-trigger the
  data-gated APP PnL/fill re-bake that was just completed — batch it with any
  other reference-alpha change rather than shipping it alone.

### 3P-4 (P2, numerical) — drift-prone reverse-Welford vs exact recompute

The two feature families use *different* numerical schemes for the same
statistic. `HorizonWindowedFeature` maintains `mean`/`M2` incrementally with a
reverse-Welford remove on every eviction (`horizon_windowed.py:169-189,196,249`)
— over a 1800 s window at high quote rate this is millions of add/remove pairs
per session, accumulating float error, and the `M2 < 0 → 0` clamp
(`:186-188`) *masks* the error rather than bounding it. `RollingZscoreFeature`
instead recomputes `sum`/`var` from the deque on each `finalize`
(`rolling_stats.py:193-195`) — O(n) but numerically exact, no drift. For
institutional grade the incremental reverse-Welford over a long high-frequency
window is the riskier choice for the *more*-used feature family.

- **Fix (P2):** periodically recompute `mean`/`M2` from the live deque (e.g.
  every K finalizes, or whenever the M2 clamp fires) to bound drift, or document
  and test a precision budget. **Effort: M.**

### 3P-5 (P2, consistency) — gap-handling differs across the mid-return sensors

The log-return sensors disagree on what a bad tick does to carry-forward state:
`realized_vol_30s` (`realized_vol_30s.py:96-101`) and `structural_break_score`
(`structural_break_score.py:160-165`) reset `last_mid = None` so the next return
cannot span the gap; `snr_drift_diffusion` (`snr_drift_diffusion.py:192-193`)
returns `None` **without** resetting, so its per-horizon return spans the
bad-data gap (then splits it into `N` equal bars, understating a halt jump);
`kyle_lambda_60s` resets a *different* field (`last_nbbo_mid`). Harmonize the
gap-reset contract across all mid-derived sensors so behaviour around halts is
uniform and auditable. (`snr` is dormant, so low urgency — but the inconsistency
is a latent surprise.) **Effort: S.**

### 3P-6 (P2, robustness) — `ofi_integrated` is unbounded and unnormalised

The `2P-2` integral (`sum` reducer over `ofi_raw`, `horizon_windowed.py:281`
`mean * n`) is the correct *quantity*, but its magnitude scales with both quote
count and book depth, so a single fat-finger size or a quote-rate burst can
dominate the window, and the value is not comparable across symbols or regimes.
Any future alpha thresholding `ofi_integrated` directly is brittle.

- **Fix (P2):** normalise the integral (per-window traded volume, or `√n`), or
  require it be z-scored before use; document that a raw threshold is
  unsupported. **Effort: S.**

### 3P-7 (P2, robustness) — single-quote saturation in `book_imbalance`

`book_imbalance = (bid_size − ask_size)/(bid_size + ask_size)`
(`book_imbalance.py`) saturates to ±1 on a single lopsided resting order; the
`2P-3` horizon mean dampens transient spikes but a persistent fat-finger /
spoof quote holds the mean near ±1. Consider winsorising displayed sizes or
capping the per-quote contribution before averaging. **Effort: S.**

### Third-pass backlog

| ID | Sev | One-line fix | Effort |
|----|-----|--------------|--------|
| 3P-1 | **P0** | Reject non-finite sensor values at registry emission (Alert + provenance.valid=False); finiteness guard in aggregator | M |
| 3P-2 | P1 | Reject crossed/locked NBBO in price-consuming sensors (or filter at the normalizer) | M |
| 3P-3 | P1 | Replace `imb == 0.0` with an epsilon band (batch with the APP re-bake) | S |
| 3P-4 | P2 | Bound reverse-Welford drift (periodic recompute) or document a precision budget | M |
| 3P-5 | P2 | Harmonise the bad-tick gap-reset contract across mid-return sensors | S |
| 3P-6 | P2 | Normalise / mandate z-scoring of `ofi_integrated` | S |
| 3P-7 | P2 | Winsorise `book_imbalance` displayed sizes | S |

**Priority guidance:** `3P-1` (NaN/Inf containment) is the institutional P0 —
it is a fail-safe the platform *documents but does not have*, and its blast
radius (permanent accumulator poison → NaN sizing) is severe. `3P-2` and `3P-3`
are next. `3P-4`–`3P-7` are hardening.

### Third-pass remediation status (2026-06-13)

- **3P-1 (done).** Non-finite containment now exists at both boundaries: the
  registry refuses to publish a NaN/Inf sensor value (scalar or any tuple
  component) — suppress + WARN + `feelies.sensor.nonfinite.count` metric, with
  the throttle clock intentionally not advanced (`registry.py:_is_finite_value`,
  `_on_event`, `_emit_nonfinite_metric`); the aggregator demotes a non-finite
  *feature* value to cold and omits it from `values`
  (`aggregator.py:_build_snapshot`). Tests:
  `tests/sensors/test_robustness_3p.py`, `tests/features/test_robustness_3p.py`.
- **3P-2 (done).** All spread/mid-consuming sensors now reject a crossed book
  (`bid > ask`) via the existing degenerate-book path (the mid-carrying sensors
  reset their carry-forward mid). Applied to `spread_z_30d`, `micro_price`,
  `liquidity_stress_score`, `quote_flicker_rate`, `realized_vol_30s`,
  `structural_break_score`, `snr_drift_diffusion`, `kyle_lambda_60s`,
  `ofi_ewma`, `ofi_raw`, `trade_through_rate`. `book_imbalance` (sizes-only) and
  `quote_hazard_rate` (price-agnostic) are intentionally untouched. Locked
  markets (`bid == ask`) are still accepted (harmless, sometimes legitimate).
  Golden-safe: fixtures contain zero crossed quotes (verified).
- **3P-4 (done).** `HorizonWindowedFeature` now flags catastrophic cancellation
  (the `M2 < 0` indicator) and recomputes `mean`/`M2` exactly from the live
  window on the next eviction sweep, so reverse-Welford drift is *bounded*, not
  merely clamped (`horizon_windowed._recompute_from_window`). Golden-safe (the
  recompute fires only when the indicator trips, which clean fixtures do not).
- **3P-5 (done).** `snr_drift_diffusion` now resets its carry-forward mid and
  per-horizon grid on a bad/crossed quote, harmonising bad-tick gap handling
  with `realized_vol_30s` / `structural_break_score`.
- **3P-6 (addressed by documentation).** The `ofi_integrated` wiring comment
  already directs consumers to z-score it; a normalised (per-volume / √n)
  variant is left as future work since no alpha consumes it yet.
- **3P-3 (done).** The reference alpha's dead `imb == 0.0` check is replaced by
  an epsilon band `abs(imb) < params["imbalance_floor"]` (new parameter,
  default 0.05), so a near-zero `book_imbalance_mean` no longer passes as a
  confirmation. Test: `test_no_emission_when_imbalance_below_floor`.
- **3P-7 (done).** `book_imbalance` gained an opt-in `imbalance_cap` (default
  1.0 = no-op, so the 1.0.0 estimator is byte-preserved without a version bump;
  `platform.yaml` opts into 0.95). A lone fat-finger / spoof quote is winsorised
  before it enters the horizon mean. Tests in `test_robustness_3p.py`.

3P-1/3P-2/3P-4/3P-5 are code-only (no config change). 3P-3/3P-7 change the
reference alpha + a platform sensor param, so the **data-free config-contract
hash was re-baked**; the **data-gated APP PnL/fill baselines must be re-baked on
a host with the APP disk cache** (the reference alpha's confirmation logic
changed), as must any host where the APP tape contains crossed quotes (3P-2).

*End of audit (third-pass remediation appended 2026-06-13).*
