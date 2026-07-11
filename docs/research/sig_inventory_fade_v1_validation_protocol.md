<!--
  File:   docs/research/sig_inventory_fade_v1_validation_protocol.md
  Status: PRE-REGISTERED — FROZEN (Task 8-F, 2026-07-11). Written
          BEFORE any implementation and BEFORE any data contact.
          Pre-freeze reconciliation and Lei's rulings recorded in §11:
          census σ₁₂₀ thresholds corrected to the strict §4.2 anchor
          (29–39 bps; the §15(ii) 4.0-AS substitution NOT approved for
          the census floor); five judgment calls approved as ruled;
          sensitivity pass set = 27-vertex neighborhood + inv12-stress
          point. From the 8-F commit, changes go ONLY in an appended
          AMENDMENTS section with timestamp and justification. No
          forward return, IC, or outcome statistic was computed in
          producing this file.
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8, Phase B.

  Provenance (FQ-3 template):
    git_sha: "f2c71f187aeec5311a91f79575d99f490b93c686"
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "0 set in session; the only scripted run in this
      task is the amendment-E dependency check (step-0 verification,
      tests/bootstrap/test_horizon_feature_factories.py — 2 passed)"
    normative_inputs:
      sig_inventory_fade_v1_formal_spec.md (§1–§16 incl. the §15
        ruling — floors, κ freeze, power gate — and §16 deviations),
      prompt_pack_03c_universe_and_cache.md (closed 80-cell grid §5.1,
        L1–L4 verbatim, realized tick buckets §7, median bids §3.1),
      prompt_pack_00b_edge_units_convention.md (one-way convention,
        9.75 bps disclosure floor arithmetic, hop table),
      prompt_pack_00c_eval_canon.md (pinned realism profile at commit
        825a7bc3bda48d3a819fed0a498dbf9d65e711c4; zero-latency ban),
      prompt_pack_03b_print_eligibility.md (§3.3 Class table, §4.4
        correction netting — via the spec's §1.5 instantiation),
      prompt_pack_04_hypothesis_slate.md (trial ledger, N = 10,
        FQ-6B-R registration rule),
      docs/research/gas_01_integrated_ofi.md / gas_02 (ENG-3
        sign-golden + IC-gate precedent),
      .cursor/skills/microstructure-alpha/research-protocol.md
        (Phase 3 stratification procedure, ~100-obs per-stratum rule,
        Phase 5 IC(t) decay fit),
      src/feelies/research/{cpcv.py, dsr.py, forward_ic.py},
      src/feelies/alpha/promotion_evidence.py (GateThresholds),
      src/feelies/forensics/cost_survival.py (verdict vocabulary),
      scripts/{sensor_feature_ic.py, regime_diagnostics.py},
      src/feelies/harness/backtest_cli.py (--inv12-stress)
      (all read this session; citations inline).
-->

# `sig_inventory_fade_v1` — pre-registered validation protocol (Task 8)

This protocol fixes, numerically and in execution order, every test the
candidate must pass — **before** any implementation exists and before
any outcome statistic is computed. It binds Task 8 (measurement),
Task 9 (implementation), and the Task-12-gated execution overlay.

**Freeze rule.** From the Task 8-F freeze commit this file is
immutable except for an appended `AMENDMENTS` section (timestamp +
justification per entry).
Converting any FAIL below by tuning is prohibited: **any post-hoc
parameter change is a new trial — N increments and the change is
logged in the ledger (§10) before the re-run.** Simulator-knob
perturbations inside the pre-registered §8 grid do not increment N
(the grid's pass criterion is conjunctive — it can only reject);
any change to alpha-side parameters (`pressure_threshold`,
`edge_scale_bps` outside the §3 calibration procedure, `edge_cap_bps`,
gate thresholds, exit ages, session constants) does.

**Two validity axes, never conflated (session constraint 5).** Steps
1–6 establish *statistical* validity on pre-cost / disclosure-
arithmetic quantities; steps 7–8 establish *execution* validity on the
Task-12-parity-cleared machinery. No number from steps 1–6 is ever
presented as an economic result, and no number produced before the
Task-12 router timing-parity check is presented as a result at all.

**Evidence set (Amendment B).** The 03c §5.1 frozen 80-cell inventory
is the CLOSED evidence set: symbols `APP, RMBS, OLN, ENSG, DIOD, PCTY,
MLI, CROX` × dates `2025-11-25, 2025-12-04` (elevated episode A),
`2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27` (calm),
`2026-04-01, 2026-04-10, 2026-04-22` (elevated episode B). No
addition or substitution without a protocol amendment. **OLN is in the
evidence set solely for the §2.4 tick-artifact tests; it is excluded
from deployable economics, CPCV, DSR, and the execution overlay
(spec Amendment G).**

The 03c known limitations are carried **verbatim** into every stratum
definition and every downstream artifact (Amendment B; L1 attaches
unconditionally to every calm-stratum conclusion):

- "L1: calm stratum = ONE episode; calm-regime conclusions are evidence
  about calm-as-realized Dec-2025/Feb-2026, not calm-in-general"
- "L2: calm dates 2026-01-26/01-27 are adjacent (deterministic redraw
  artifact of a contaminated late-Jan/early-Feb tail); effective calm
  diversity ~4 distinct weeks; benign for intraday horizons across the
  overnight boundary"
- "L3: shared-calendar + any-symbol screen over-represents jointly-quiet
  days; RMBS (highest trip rate, incl. during SPY's calmest stretch) is
  the most heavily conditioned subsample — per-symbol diagnostics must
  flag RMBS; its tick-bucket prior is provisional"
- "L4: elevated stratum spans two episodes ~4 months apart (mild
  Nov-Dec band vs severe April band incl. span rv20 max) — treat
  within-stratum heterogeneity as a feature, report per-window where
  sample permits"

**Units (00b, THE CONVENTION).** Every edge and cost figure below is
**one-way, per-fill, in bps of fill notional** unless explicitly
marked round-trip-derived.

---

## 0. PRECONDITIONS (verified before step 1 executes)

| # | precondition | status at protocol write |
|---|---|---|
| P0-1 | h=120 wiring pre-step committed and green (task Amendment E) | **VERIFIED 2026-07-11**: commit `6a3ac12` ("bootstrap: wire inventory_pressure passthrough at h=120") on `main`; commit message records full gate battery green (ruff, ruff format, mypy strict, `pytest -m "not functional and not slow"` 3981 passed/9 skipped, `tests/determinism/` 126 passed/4 skipped, PYTHONHASHSEED=0, no baseline moved); worktree clean at this task's start; `tests/bootstrap/test_horizon_feature_factories.py` re-run this session: **2 passed** |
| P0-2 | Grid inputs CLEARED | 03c FQ-6A-R re-check table: CLEARED 2026-07-11 |
| P0-3 | Realism profile pinned | 00c profile at commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`; configs with `backtest_fill_latency_ns == 0` are invalid for evidence (00c decision A, adopted verbatim per its Task-8 amendment) |
| P0-4 | Determinism discipline | every scripted run: `PYTHONHASHSEED=0`, direct `DiskEventCache` read (`~/.feelies/cache`), replay through the real pipeline; provenance (git SHA, command line) recorded per run |
| P0-5 | Step-1 census executes only after this file is committed | the protocol freezes BEFORE the census runs (task Amendment A) |

Execution order is **locked**: 1 → 2 → 3 → 4 → 5 → 6 → (7 → 8) with
steps 7–8 additionally gated on the Task-12 router timing-parity
precondition. A step does not begin until the prior step's outputs are
committed. A park/reject at any step halts the sequence.

---

## 1. STEP 1 — PARK-RULE CENSUS (Amendment A; spec §15 governs)

Offline deterministic scan of the frozen 80-cell grid. **NO forward
returns are computed anywhere in this step** — the only return-like
quantity permitted is the *unconditional* session volatility σ₁₂₀
(std of non-overlapping 120 s mid log-returns over RTH, in bps),
which conditions on nothing signal-related.

### 1.1 Frozen viable-region definition (numeric, before execution)

κ = **0.16, FROZEN** (spec §15(i); one-way ratchet — revisable down on
evidence, never up; superseded entirely by the measured conditional
edge once the census has run). Per-symbol σ₁₂₀ viability thresholds =
**§4.2 stressed floors ÷ κ**, hop-by-hop per the 00b one-way
convention (Task 8-F reconciliation, §11 — every quantity below is
one-way, per-fill, bps of fill notional; no ×2 appears anywhere):

1. adverse selection (passive/LEVEL, 00c pin): **2.0 bps**;
2. fee_s = min-commission floor `max(0.0035×80, $0.35)` = $0.35 on
   the 80-share reference fill ÷ notional at the 03c §3.1 median RTH
   bid, in bps;
3. C_ow = 0 (maker half-spread) + 2.0 + fee_s;
4. Inv-12 cost stress (cost side only; the edge is never touched,
   00b hop 4): C_ow,stressed = 1.5 × C_ow;
5. strict anchor (pre-registered): **e_ow ≥ 1.5 × C_ow,stressed =
   2.25 × (2.0 + fee_s)** — the spec §4.2 stressed floor;
6. σ₁₂₀ min = floor ÷ κ = floor / 0.16.

| symbol | median bid ($) | fee (bps) | C_ow | C_ow,stressed | floor (bps) | σ₁₂₀ min (bps) |
|---|---|---|---|---|---|---|
| APP  | 615.05 | 0.07 | 2.07 | 3.11 | 4.66 | ≈ 29.1 |
| ENSG | 182.94 | 0.24 | 2.24 | 3.36 | 5.04 | ≈ 31.5 |
| PCTY | 140.80 | 0.31 | 2.31 | 3.47 | 5.20 | ≈ 32.5 |
| MLI  | 130.62 | 0.33 | 2.33 | 3.50 | 5.25 | ≈ 32.8 |
| RMBS | 105.36 | 0.42 | 2.42 | 3.63 | 5.43 | ≈ 33.9 |
| CROX | 83.28  | 0.53 | 2.53 | 3.80 | 5.68 | ≈ 35.5 |
| DIOD | 57.50  | 0.76 | 2.76 | 4.14 | 6.21 | ≈ 38.8 |
| OLN  | — | — | — | — | excluded (Amendment G) | — |

A (symbol, session) cell is **in the viable region** iff its realized
session σ₁₂₀ ≥ the symbol's σ₁₂₀ min. Adverse-selection-axis
robustness ({2.0, 3.0, 4.0}) is tested where it belongs — the step-8
sensitivity grid, binding within the §8 neighborhood, on **measured**
execution economics — never inside the pre-data census floor (§11
reconciliation; supersedes spec §15(ii)'s floor substitution for
census purposes).

### 1.2 Boundary-eligible episode definition (numeric)

An **eligible boundary** is an h=120 `HorizonFeatureSnapshot` boundary
satisfying ALL of:

1. `|inventory_pressure| ≥ 0.5` (the spec's fixed gate arm; the
   free-range `pressure_threshold` can only tighten later);
2. `spread_z_30d ≤ 1.0`;
3. HMM `P(normal) > 0.6` (boundary-time posterior,
   `hmm_3state_fractional`, reference calibration);
4. every id in `{inventory_pressure, spread_z_30d,
   realized_vol_30s_zscore}` warm and not stale at the boundary
   (spec §1.3 required-warm set);
5. boundary time inside the session-discipline window: ≥ 09:35:00 ET
   (`no_entry_first_seconds: 300`) and ≤ 15:50:00 ET
   (`session_flatten_seconds_before_close: 600`).

One eligible boundary = one episode. (At h=120 the trailing 60 s
sensor windows of consecutive boundaries are disjoint, so no
double-counting correction is needed; the count is of independent
conditioning windows.)

### 1.3 Census outputs (all reported per symbol × session × daily stratum)

- eligible-episode counts (total, and split fade-long `p ≥ +0.5` /
  fade-short `p ≤ −0.5`);
- sensor warm coverage: fraction of RTH boundaries with each of the
  three entry-warm ids warm (spec §1.1 flags; ENSG/DIOD
  `inventory_pressure` marginality and ENSG/DIOD/MLI/PCTY
  `spread_z_30d` late-warm risk are the declared watch items);
- §1.5 contamination flags: fraction of eligible boundaries whose
  trailing 60 s window contains any Class-B print (03b §3.3 exclusion
  set) or any `correction ∈ {10,11,12}` record — reported, and flagged
  boundaries excluded from the primary counts (both counts reported);
- realized session σ₁₂₀ (bps) and the cell's viable/non-viable label;
- **benign-on-elevated counts per Amendment H**: eligible episodes on
  elevated-stratum days, reported separately for episode A (Nov–Dec)
  and episode B (April), per symbol (L4);
- the 2×2 of (intraday gate state × daily stratum) boundary counts
  (spec §9(i)).

### 1.4 Park conditions (numeric; either parks the card)

- **Edge-region emptiness:** for every grid symbol, the viable region
  (cells with σ₁₂₀ ≥ σ_min) contains zero eligible episodes after
  contamination exclusion → **PARK** (the pre-registered deployable
  claim has no support).
- **Power floor (spec §15(iii)):** a symbol is *deployable-candidate*
  only if its viable-region eligible-episode count (contamination-
  excluded) is **≥ 100**. If **no** grid symbol clears 100, the card
  **PARKS on power** before a single IC number exists. Cells/strata
  below the floor are reported INSUFFICIENT, never pooled away.

The census fixes the **deployable candidate set** D = {symbols with
≥ 100 viable-region eligible episodes}. All subsequent deployable-
economics statements are restricted to D. OLN is never in D.

---

## 2. STEP 2 — SIGN-GOLDEN + IC GATE (ENG-3 precedent, gas_01/gas_02)

Per the repo's own promotion policy (engine-readiness ENG-3, as
exercised in `docs/research/gas_01_integrated_ofi.md`): **no promotion
of the feature without BOTH (a) and (b).**

### 2.1 (a) Sign-golden through the REAL pipeline

Synthetic tape with known ground truth pushed through the real
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (the
gas-01 pattern, `tests/research/test_gas_ofi_integrated.py`); new test
module `tests/research/test_gas_inventory_fade_sign.py` (Task 9
implements; assertions fixed here):

1. **Sell-pressure golden:** ≥ 20 tick-rule-classifiable sell-aggressor
   prints (trades at the bid on a downtick grid) within a 60 s window
   before an h=120 boundary ⇒ the snapshot carries key
   `inventory_pressure` at h=120 with value **> 0** (MM absorbed net
   selling; sensor convention `Σ(−aggressor·size)/Σsize`,
   `sensors/impl/inventory_pressure.py:25-31`), and the §5.2 draft
   `evaluate` (once implemented) emits direction **LONG** — fade the
   flow, expect upward reversion.
2. **Buy-pressure mirror:** same tape mirrored ⇒ value < 0 ⇒ SHORT.
3. **Warm-gate golden:** 19 trades in the window ⇒ sensor not warm ⇒
   no entry (warm rule `min_trades=20` binding).
4. **h=120 key presence:** the snapshot at h=120 carries the key at
   all (regression lock on commit `6a3ac12`'s wiring).

Any assertion failure ⇒ **REJECTED (sign/wiring defect)** — fix is an
implementation correction, not a tuning event (N unchanged), but the
gate must re-run from scratch.

### 2.2 (b) RankIC evidence — thresholds and sessions fixed now

**Harness:** `scripts/sensor_feature_ic.py` extended (Task 9) with an
`inventory_fade` row: sensor `inventory_pressure` (1.0.0, reference
params `window_seconds=60, min_trades=20`), passthrough feature at
h ∈ {30, 120}, paired at each warm boundary with the forward mid
log-return over the snapshot horizon; statistics via
`research/forward_ic.py` (`spearman_ic`, `bucketed_forward_return`,
`long_short_edge_bps`). The harness extension is measurement plumbing
for the pre-registered primary trial, not a new trial.

**Sessions (named now, the closed set):** all 80 cells of the 03c grid
(8 symbols × the 10 dates listed in the preamble). Primary evidence =
pooled over the census deployable set D restricted to viable-region
sessions; the full grid is reported for context. Contamination-flagged
boundaries excluded from the primary (reported both ways, §1.3).

**Numeric gate (ALL required, at h = 120, fade convention: mechanism
predicts RankIC(inventory_pressure, forward mid log-return) > 0):**

| criterion | threshold |
|---|---|
| pooled RankIC sign | > 0 (positive = fade-correct) |
| pooled \|RankIC\| | ≥ 0.03 |
| pooled significance | Fisher-z two-sided p ≤ 0.01 |
| pooled sample minimum | n ≥ 1,000 warm boundaries (else INSUFFICIENT — the gate cannot pass or fail; report and stop for Lei) |
| per-symbol (each symbol in D) | RankIC > 0 with n ≥ 100 in the viable region; a symbol failing sign or n drops out of D (n < 100 ⇒ INSUFFICIENT ⇒ out of D per §1.4 power rule) |
| bucket monotonicity | `bucketed_forward_return` (5 equal-count buckets): top-bucket minus bottom-bucket forward-return spread (`long_short_edge_bps`) positive in the fade direction |
| conditional tail (F1 anchor) | mean fade-signed 120 s forward return on eligible boundaries (\|p\| ≥ 0.5) > 0 with t ≥ 2 pooled over D |

The gas-01 lesson binds: single-tape results are indicative only; the
gate is evaluated **pooled** and per-symbol as above, never on one
(symbol, date).

The criteria are **deliberately conjunctive** (Task 8-F ruling): the
p ≤ 0.01 bar binds at moderate n, and the |RankIC| ≥ 0.03 floor
rejects effects that are trivial-in-magnitude yet significant at huge
n. Neither alone is sufficient.

### 2.3 Measured-edge anchor (the §4.3/§15 acceptance test)

The measured conditional edge (mean fade-signed 120 s forward return
on eligible boundaries, bps one-way, per symbol in D, viable region,
contamination-excluded) must be **≥ the per-symbol §4.2 stressed floor**
(APP 4.66, ENSG 5.04, PCTY 5.20, MLI 5.25, RMBS 5.43, CROX 5.68,
DIOD 6.21 bps) for the symbol to remain in D. This measured value
supersedes all κ arithmetic from this point (§15(i)) and becomes the
G12 disclosure input (`edge_estimate_bps` = the D-set minimum measured
edge, conservative, per spec §5.5). If D empties here, the card parks
exactly as H1 did.

### 2.4 Tick-constraint artifact tests (spec §7, pre-registered design)

Run alongside the IC gate (evidence set including OLN):

1. spread-in-ticks distribution **at eligible boundaries** (not
   pooled) per symbol;
2. **≥ 4-tick-stratum re-derivation**: conditional edge re-estimated on
   boundaries with prevailing spread ≥ 4 ticks; pass = sign-consistent
   with the full-sample estimate; collapse ⇒ pooled effect was grid
   artifact ⇒ restate economics on the surviving stratum (definition
   kill on the affected stratum per spec §10);
3. **OLN quantum test**: conditional 120 s mid-move mass vs the
   ±1 half-tick quantum (≈ ±2.1 bps); reversion mass entirely at one
   quantum with no continuous tail ⇒ OLN's effect is grid bounce
   (evidence finding only — OLN is never deployable);
4. sign difference across buckets after quantum correction ⇒
   **definition-level kill**.

---

## 3. STEP 3 — CPCV (`research/cpcv.py`)

### 3.1 Configuration (numeric, with derivation)

Run **per symbol in D**, on that symbol's 10 grid sessions.

- **Bar** = one h=120 boundary; RTH 09:30–16:00 = 23,400 s ⇒ **195
  bars/session**, `n_bars ≈ 1,950` per symbol (exact count = emitted
  boundaries; sessions never concatenate state — sensors and regime
  engine re-warm per session replay, so cross-session leakage through
  sensor state is zero by construction).
- **Groups:** `n_groups = 10` — one contiguous group per grid session
  in calendar order (group boundaries coincide with session
  boundaries).
- **k:** `k_test_groups = 2` ⇒ φ = C(10,2) = **45 combinations**,
  paths = C(9,1) = **9 reconstructed paths ≥ 8** (`cpcv_min_folds` ✓).
- **Purge:** `label_horizon_bars = 1`. Derivation: the label is the
  120 s forward mid return ⇒ label span = 120 s = 1 bar exactly.
- **Embargo:** `embargo_bars = 2`. Derivation (task item 2: horizon +
  longest sensor window, arithmetic shown): required forward
  exclusion = horizon 120 s (label overlap, covered by the 1-bar
  purge) + longest *time-bounded* entry-path sensor window = 60 s
  (`inventory_pressure`; `realized_vol_30s` 30 s and the offline-only
  `quote_replenish_asymmetry` 5 s are shorter) ⇒ residual 60 s ⇒
  ⌈60/120⌉ = 1 bar minimum. Adopted **2 bars = 240 s** — the extra bar
  conservatively covers the two entry-path components with **no fixed
  time constant**: `spread_z_30d`'s 6000-quote count window (≈ 47 min
  at APP quote rates, longer on thin names — bounded structurally by
  the session-aligned groups and per-session sensor reset, so only
  within-session adjacency leaks) and the quote-clocked HMM posterior
  (spec §3 tick-dwell caveat). Total forward exclusion = 1 + 2 =
  3 bars = 360 s per test region. `embargo_bars = 2 ≥
  cpcv_min_embargo_bars = 1` ✓; the block-bootstrap block length is
  `max(1, embargo_bars) = 2` bars (the declared serial-correlation
  length), per `build_cpcv_evidence`.

### 3.2 Return series and per-split training (the CPCV contract)

Per-bar return series per symbol: at each boundary, the **fade-signed
120 s forward mid log-return minus the round-trip-derived cost
2 × C_ow,stressed(symbol)** (C_ow,stressed = 1.5 × (2.0 + fee_s), the
§4.2 stressed one-way cost) **if the boundary is entry-eligible under
the full frozen rule** (§1.2 conditions + the `evaluate` EV gate with
the split's trained `edge_scale_bps`), else **0.0**. This is a
*statistical-validity* series — a disclosure-arithmetic cost proxy,
not an execution result (fill realism enters only at steps 7–8).

Per-split training (the CPCV caveat honored — the caller retrains per
combination): on each of the 45 splits, `edge_scale_bps` is
re-estimated on the split's purged+embargoed **train** bars (OLS of
fade-signed forward return on normalised exceedance
`(|p| − 0.5)/0.5`, through the origin, clipped to the declared range
[4.0, 16.0]) and applied to the **test** bars through the frozen
`evaluate` rule. All other parameters are frozen at spec defaults
(`pressure_threshold = 0.5`, `edge_cap_bps = 12.0`, `_MIN_EDGE_BPS =
5.0`, gate thresholds §5.3). This in-protocol calibration is part of
the single pre-registered primary trial; it does not increment N.

**Dual reporting (Task 8-F ruling):** the **PRE-COST path
distribution** (same series without the 2 × C_ow,stressed deduction)
is computed and reported **alongside the cost-adjusted one at every
step** that quotes CPCV output — the pass/fail **criterion stays on
the cost-adjusted series**. The pre-cost distribution is diagnostic
context (separating "no reversion exists" from "reversion exists but
below the cost proxy"), never a result.

### 3.3 Annualization and thresholds

`annualization_factor = sqrt(195 × 252) = sqrt(49,140) ≈ 221.68`
(bars/session × trading days/year — the sqrt(252)-commensurate scaling
for 120 s bars), passed to `build_cpcv_evidence` so emitted Sharpes
are annualised and directly comparable to the `GateThresholds`
defaults. Bootstrap: `n_bootstrap = 10,000`, `seed = 0` (Inv-5
bit-identical).

**Thresholds: the `GateThresholds` defaults, NO per-alpha override**
(none is needed; none is pre-registered):

| gate | value | this run |
|---|---|---|
| `cpcv_min_folds` | ≥ 8 reconstructed paths | 9 by construction |
| `cpcv_min_mean_sharpe` | ≥ 1.0 (annualised) | must clear on **every** symbol in D |
| `cpcv_max_p_value` | ≤ 0.05 (block bootstrap) | every symbol in D |
| `cpcv_min_embargo_bars` | ≥ 1 | 2 by construction |

Fail on any symbol ⇒ that symbol leaves D; D emptying ⇒ status per §9.

---

## 4. STEP 4 — REGIME STRATIFICATION (manual per R6 / research-protocol Phase 3.3 — no shipped harness)

### 4.1 Strata (cutpoints fixed now)

Partition **warm h=120 boundaries** (per symbol, full grid) on two
axes:

- **Vol axis** — HMM dominant state (`RegimeState.dominant_name`,
  `HMM3StateFractional`): `compression_clustering` / `normal` /
  `vol_breakout` (3 strata);
- **Spread axis** — boundary-time `spread_z_30d` at **fixed
  cutpoints**: z ≤ 0 (tight) / 0 < z ≤ 1 (normal) / z > 1 (wide)
  (3 strata; chosen to bracket the gate's `≤ 1.0` arm — the z > 1
  stratum is outside the entry gate and serves as the adverse
  control).

The daily calm/elevated-A/elevated-B stratum is a **third, reporting
axis** (Amendment H: intraday gate ≠ daily stratum; every statistic is
also reported in the gate-state × daily-stratum 2×2). The spec's F3
kill clause is additionally evaluated in its own frozen form —
`spread_z_30d` **terciles within the benign stratum** — exactly as
worded in spec §12 (the fixed cutpoints above are the reporting
harness; the tercile clause is the kill test, carried verbatim).

### 4.2 Procedure and per-stratum minimum

Within each (vol × spread) stratum: repeat the §2.2 IC test
(`spearman_ic` on stratum boundaries) and, where the stratum holds
enough bars to form the §3 groups, repeat CPCV (same config; where a
stratum cannot form 10 groups of ≥ 1 bar per session it reports
CPCV-INFEASIBLE, not a fail). **Minimum per-stratum sample = 100
boundary observations** (research-protocol Phase 3.3 rule 4); below
it the stratum reports **INSUFFICIENT** — never pooled away, never
counted for or against the acceptance rule.

### 4.3 Acceptance rule (numeric)

**PASS** iff, on the pooled-D evidence: the conditional edge is
**sign-stable (fade-positive) AND RankIC ≥ +0.02 with Fisher-z
p ≤ 0.05** in at least **2 vol strata × 2 spread strata** (i.e. ≥ 2
cells on each axis among cells with n ≥ 100). Single-stratum
concentration is a fragility flag reported to Lei (not an automatic
kill) **unless** the sign reverses across spread terciles within the
benign stratum — that is F3, a **definition-level kill** (spec §10,
Spread axis).

### 4.4 Invariance checks (spec §6, slotted here; numeric criteria)

- **I-1 (zero-integrated-edge conservation, mandatory):** funding pool
  (a) = Σ_episodes D̂ × Q_episode × measured temporary share; strategy
  integrated pre-cost conditional edge (b) at declared participation
  (≤ 80 sh/episode). **Pass:** (b) / (participation share × (a)) ≤ 1.5
  (point estimate; the 0.5 headroom is the pre-registered estimation-
  error allowance). In the viable (high-σ) stratum the pool is priced
  at the **stressed** adverse-selection charge for that stratum
  (§15(ii), never calm assumptions). Companion: unconditional forward
  returns over matched boundaries integrate to ≈ 0 —
  |mean| ≤ 2 × SE. Fail ⇒ **misattribution ⇒ hypothesis-revise** (the
  card is wrong even if profitable).
- **I-2 (side symmetry):** fade-long vs fade-short conditional edges
  in the benign stratum agree within sampling error — two-sample
  z ≤ 2. Fail ⇒ investigate before any deployment claim
  (hypothesis-revise); SHORT side carries the §5.2 SSR/HTB optimism
  caveat in all reporting.
- **I-3 (episode-volume invariance):** conditional edge by
  episode-volume tercile within the benign stratum. Red flag (report,
  investigate — not automatic kill): any tercile with sign opposite
  the pooled estimate, or > 80 % of the pooled edge concentrated in a
  single extreme tercile.

Phase-5 decay-shape check (spec §3): IC(t) measured at t ∈ {30, 60,
120, 300} s on eligible boundaries; exponential fit half-life must lie
in **[20, 80] s** (the declared 40 s ± a factor of 2). Outside ⇒ the
process model is mis-specified ⇒ hypothesis-revise (a half-life
change is a parameter-level revision per §10 only if sign and shape
survive; a non-decaying IC(t) is F1-adjacent death).

---

## 5. STEP 5 — DSR (`research/dsr.py`)

Computed on the pooled-D per-bar cost-adjusted return series (§3.2
definition, all D symbols' sessions, bars in (symbol, session, time)
order; n_obs = total bar count):

- `build_dsr_evidence_from_returns(returns=…, trials_count=N,
  annualization_factor=sqrt(49,140))` with **N = the then-current
  living-ledger count at computation time** — N = 10 at protocol
  freeze (Amendment D); every evaluation event between freeze and the
  DSR computation increments it first (FQ-6B-R rule: any data contact
  increments; drafting does not). The six REGISTERED-UNEVALUATED slate
  rows and the spec §13 drafted-not-evaluated variants count **only if
  actually evaluated** by then.
- `trial_sharpe_variance`: **None** (iid-Gaussian null floor
  `1/(n_obs−1)`), because the parked/unevaluated trials have no
  measured Sharpes to pool an empirical variance from. This is the
  weakest honest deflation (module warning) and is disclosed verbatim
  in the evidence artifact.
- **Report `expected_max_sharpe(n_trials=N, trial_sharpe_variance=
  1/(n_obs−1))` — annualised — as the noise ceiling alongside the
  observed Sharpe** in every artifact quoting the DSR.

**Thresholds (defaults, no override):** `dsr` (deflated Sharpe excess,
annualised) ≥ **`dsr_min` = 1.0** AND `dsr_p_value` ≤
**`dsr_max_p_value` = 0.05**. An observed Sharpe below the reported
noise ceiling fails regardless of nominal significance (F1's honest-N
clause). Fail ⇒ **REJECTED** (statistically indistinguishable from
the best of N noise trials).

---

## 6. STEP 6 — DRIFT DIAGNOSTICS

**What re-estimates, on what window:** at runtime, **nothing** — all
sensor params, gate thresholds, and session constants are fixed
constants (spec §1.4/§5). The only estimated quantity in the whole
candidate is `edge_scale_bps` (Task-8 calibration, §3.2). Drift
diagnostics therefore test the *stability of the fixed-parameter
machinery and the single calibrated parameter* across the grid's
sessions; pre-stated bounds below are disqualifying.

### 6.1 Regime-engine behavior (`scripts/regime_diagnostics.py` as anchor)

Run per (symbol ∈ D ∪ {APP}, session) over the grid with the Task-9
config, `--horizon 120`:

| diagnostic | pre-stated stability bound (per session unless noted) |
|---|---|
| min pairwise emission separation d | ≥ 0.5; a session below it ⇒ gate treated as non-discriminative that session (H8/M6 fail-safe: OFF), and that session's boundaries leave the benign stratum |
| argmax occupancy | no single state > 0.98 of RTH quotes (else same treatment as above) |
| benign-gate ON fraction (`P(normal)>0.6 ∧ spread_z ≤ 1.0`) | within [0.05, 0.95] — an always-on or always-off gate is non-informative; > 3 deployable-symbol sessions outside ⇒ drift-disqualifying for the gate design (hypothesis-revise) |
| median gate-ON dwell (seconds, per symbol pooled) | ≥ 120 s (one horizon) — spec §3's tick-dwell caveat made numeric; below ⇒ the gate cannot support boundary-scale entries ⇒ hypothesis-revise |

### 6.2 Sensor / conditioning stability

| diagnostic | pre-stated bound |
|---|---|
| per-session eligible-episode rate (per deployable symbol, within a daily stratum) | max/min ratio across that stratum's sessions ≤ 5; above ⇒ conditioning unstable ⇒ hypothesis-revise |
| `spread_z_30d` warm coverage (per deployable symbol, per session) | ≥ 50 % of RTH boundaries warm; a symbol failing on > 2 sessions leaves D (coverage/power, not tuning — the §13 `window=2000` variant remains drafted-not-evaluated) |
| `inventory_pressure` warm coverage | reported (mandatory per spec §1.1); no numeric kill — entry suppression when cold is the correct fail-safe; feeds the §1.4 power gate through episode counts |
| L6 sign-stability diagnostic (spec §8 row L6) | tick-rule vs quote-position-of-print agreement per stratum, offline; agreement < 80 % in the benign stratum ⇒ the conditioning variable is materially diluted ⇒ report and carry as an edge-dilution haircut in §2.3 (measured, not assumed) |

### 6.3 Calibration stability

Leave-one-session-out re-estimates of `edge_scale_bps` (pooled-D
procedure of §3.2) must all lie within **[0.5×, 2.0×]** of the
full-sample estimate. Outside ⇒ the single calibrated parameter is
session-unstable ⇒ **drift-disqualifying (hypothesis-revise)** — not
tunable within this trial.

Structural boundaries (spec §10 footer / F5) stand: Rule 612 half-penny
(Nov 2027), MDI round-lot reassignments, the 2026-04-27 vendor
admissibility split — never pool across; the grid is entirely
pre-2026-04-27 by construction.

---

## 7. STEP 7 — EXECUTION OVERLAY (order-locked after steps 1–6; runs ONLY after the Task-12 router timing-parity precondition passes)

**Hard gate (spec §11(c) / session constraint 5):** no number from
this step exists as a result until the Task-12 router timing-parity
check has passed. If Task 12 has not run, this protocol halts here
with steps 1–6 outcomes reported as statistical-axis-only.

### 7.1 Configuration

`configs/bt_sig_inventory_fade_v1.yaml` (Task 9 deliverable),
instantiated from the pinned 00c profile (checksum guard; commit
`825a7bc3bda48d3a819fed0a498dbf9d65e711c4`):
`execution_mode: passive_limit`; realism knobs ON exactly as pinned
(`passive_fill_delay_ticks 3`, `passive_queue_position_shares 200`,
`passive_fill_hazard_max 0.5`, `passive_through_fill_size_cap_enabled
true`, `passive_require_trade_for_level_fill true`,
`cost_within_l1_impact_factor 0.3`, `cost_stop_depth_depletion_factor
2.0`, `cost_max_impact_half_spreads 4.0`);
`backtest_fill_latency_ns 50_000_000`, `market_data_latency_ns
20_000_000` (zero latency invalid for evidence);
`signal_min_edge_cost_ratio: 1.5` (deployment convention);
`no_entry_first_seconds: 300`, `session_flatten_enabled: true`,
`session_flatten_seconds_before_close: 600`; symbols = D only.

### 7.2 Runs and required outcomes (numeric)

Per symbol in D over its 10 grid sessions: `feelies backtest
--config configs/bt_sig_inventory_fade_v1.yaml --symbol <S> --date
<D>` — the **baseline** pass — then the **identical** run set under
`--inv12-stress` (1.5× `cost_stress_multiplier`, 2× both latency
legs; the edge side is never touched, 00b hop 4). Required outcomes,
ALL of:

1. **Per-Alpha Cost Survival verdict = `SURVIVES`** (pooled per
   symbol over its sessions, `min_margin 1.5×`, `min_fills 20`) on
   the **baseline** run — `MARGINAL`, `BLEED` fail outright; `LOW_N`
   (< 20 fills) is a **power failure ⇒ PARKED (execution power)**,
   not a pass.
2. **`SURVIVES` again under `--inv12-stress`** — Inv-12: if the alpha
   vanishes under stress it wasn't real.
3. **Post-cost economics consistent with the disclosed
   `cost_arithmetic` (±5 % reconciliation spirit, made numeric):**
   (i) realized `mean_cost_bps` ≤ 1.25 × disclosed `cost_total_bps`
   (the modeled quote-dependent round trip may exceed disclosure
   arithmetic — 00b qualification 1 — but a 25 % breach means the
   disclosure is wrong: re-derive and re-disclose, which is +1 N);
   (ii) calibration factor `realized mean_edge_bps / disclosed
   edge_estimate_bps` ≥ 0.75 (below ⇒ the disclosed edge is
   optimistic ⇒ re-disclosure, +1 N); (iii) the G12 block's declared
   `margin_ratio` reconciles with components within ±0.05 absolute
   (load-gate arithmetic, checked at Task-9 load).
4. **Fill-quality diagnostics (spec §11(a)), numeric:**
   through-fill share of entry fills ≤ 50 % (a through-dominated mix
   is the θ₂ signature at the execution layer ⇒ execution-invalid);
   filled-minus-unfilled 120 s markout gap ≤ the 2.0 bps charged
   adverse selection — if exceeded, F4 arithmetic is **re-run with
   the measured figure** (pre-registered recomputation, not a new
   trial) and outcomes 1–2 re-judged on it. `EXPIRED` (timeout-
   cancel) rate and time-to-fill distribution reported against the
   3-tick-delay + hazard model.

---

## 8. STEP 8 — SENSITIVITY GRID (Amendment C; spec §11(b) extended)

Axes (mandatorily including the three Amendment-C knobs), full cross
= **3 × 3 × 3 × 3 = 81 vertices**, every vertex a deterministic
re-run of the §7.2 baseline set:

| knob | pinned | grid |
|---|---|---|
| `passive_fill_hazard_max` | 0.5 | {0.25, 0.5, 0.75} |
| `passive_queue_position_shares` | 200 | {100, 200, 400} |
| adverse-selection pair (`cost_passive_adverse_selection_bps`, `cost_through_fill_adverse_selection_bps`) — coupled at the pinned 2.5× ratio, one axis | (2.0, 5.0) | {(2.0, 5.0), (3.0, 7.5), (4.0, 10.0)} |
| `backtest_fill_latency_ns` | 50 ms | {25 ms, 50 ms, 100 ms} |

(`market_data_latency_ns` stays pinned at 20 ms; the 100 ms vertex
equals the Inv-12 2× fill-latency leg.)

**Robustness criterion (Task 8-F sensitivity amendment, approved):**
the **binding pass set** is the **27 vertices in the ±1-step
neighborhood of the pinned profile** — the spec §11(b) cube
`passive_fill_hazard_max × passive_queue_position_shares ×
adverse-selection pair` (3 × 3 × 3) at the pinned 50 ms fill latency
— **plus the `--inv12-stress` point** (§7.2 run 2: 1.5× costs, 2×
latency legs). **PASS** = the F4 clearance verdict — measured net
edge ≥ the per-symbol §4.2 stressed floor AND cost-survival
`SURVIVES` — holds at all 27 neighborhood vertices and the
inv12-stress point, for every symbol in D. A verdict that flips
inside the binding set is simulator-dependence: the candidate is
**not execution-valid regardless of the pinned-profile number**
(spec §11(b)).

The **full 81-vertex cube is still run and reported**; failures
outside the binding neighborhood (i.e. at the 25 ms / 100 ms latency
vertices) are **logged fragility findings** — recorded in the
evidence artifact and carried into deployment review — **not kills**.
Grid vertices are pre-registered perturbations of the simulator, not
candidate variants — they do not increment N; the pass rule is
conjunctive and can only reject.

---

## 9. PASS/FAIL MATRIX AND STATUS CONSEQUENCES

One numeric criterion per step; the status each failure mode assigns.
**Trap-quadrant** is reserved for statistically-valid-but-execution-
invalid (spec §11(d) verbatim: "F4 (execution validity): pre-cost
reversion exists but ≤ 1.5 × C_ow under the passive realism model →
trap-quadrant").

| step | binding numeric criterion | on FAIL → status |
|---|---|---|
| 1 census | viable region non-empty AND ≥ 100 eligible episodes for ≥ 1 symbol | **PARKED** (emptiness or power; the H1 path — before any IC exists) |
| 2a sign-golden | all four assertions | **REJECTED** (sign/wiring defect; re-run after fix, N unchanged) |
| 2b IC gate | RankIC > 0, \|RankIC\| ≥ 0.03, p ≤ 0.01, n ≥ 1,000; bucket spread positive; tail t ≥ 2 | **REJECTED** (F1 dead — no conditional edge) |
| 2.3 edge anchor | measured conditional edge ≥ per-symbol §4.2 stressed floor on ≥ 1 symbol | **PARKED** (economics below floor everywhere — H1-style) |
| 2.4 tick tests | ≥ 4-tick stratum sign-consistent | **REJECTED on affected stratum** (grid artifact; economics restated on survivors; if D empties → PARKED) |
| 3 CPCV | 9 paths, mean annualised path Sharpe ≥ 1.0, block-bootstrap p ≤ 0.05, embargo 2, per D symbol | **REJECTED** (does not survive purged OOS reconstruction) |
| 4 stratification | sign-stable + RankIC ≥ 0.02 (p ≤ 0.05) in ≥ 2 vol × ≥ 2 spread strata (n ≥ 100 each) | **HYPOTHESIS-REVISE** (regime-fragile — a narrower re-registered card is a new trial); F3 tercile sign reversal ⇒ **REJECTED** (definition kill) |
| 4.4 invariance | I-1 ratio ≤ 1.5; I-2 z ≤ 2; IC(t) half-life ∈ [20, 80] s | **HYPOTHESIS-REVISE** (misattribution / contamination — mechanism story wrong in a named way) |
| 5 DSR | dsr ≥ 1.0, p ≤ 0.05, observed > noise ceiling at honest N | **REJECTED** (indistinguishable from max-of-N noise) |
| 6 drift | all §6.1–§6.3 bounds | **HYPOTHESIS-REVISE** (machinery unstable across sessions; any bound-motivated change = new trial) |
| 7 execution | SURVIVES baseline + stressed; reconciliation (§7.2.3); fill-mix bounds | **TRAP-QUADRANT** if steps 1–6 passed (statistically valid, execution-invalid); `LOW_N` ⇒ **PARKED (execution power)** |
| 8 grid | F4 clearance at all 27 neighborhood vertices + the inv12-stress point, every D symbol (full 81-cube reported; non-neighborhood failures = logged fragility findings, not kills) | **TRAP-QUADRANT** (simulator-dependent economics) |

**Tuning prohibition (binding, repeated):** converting any FAIL by
changing a parameter, threshold, window, stratum definition, or knob
is prohibited within this trial. Any such change is a **new trial**:
increment N in the living ledger, log the variant with its
justification, and re-enter this protocol from step 1 for the new
variant. The one-way κ ratchet (§15(i)) additionally forbids upward
re-estimation of any §4.1 factor after data contact.

---

## 10. TRIAL LEDGER STATE AT PROTOCOL FREEZE (Amendment D)

**N = 10 at freeze** (prompt_pack_04 ledger; unchanged through Task 7
and this protocol — no data contact has occurred for this candidate).
The primary object of this protocol is slate **N-row 3** (H2 primary:
`inventory_pressure` 60 s fade, H = 120 s, hl = 40 s, passive entry).
Rows that increment **only on evaluation** (FQ-6B-R binding rule: any
data contact — including exploratory — increments; drafting does
not):

- the six REGISTERED-UNEVALUATED slate rows (H1 sweep-volume floor;
  H1 SFI normalization; 03b id-12 DW weight; H2 condition-filtered
  `inventory_pressure` NEW sensor; H4 MOC-conversion; H4 15:50
  cutoff);
- the spec §13 drafted-not-evaluated variants (percentile gate form;
  `hard_exit_age_seconds = 120`; runtime σ-scaled edge; `spread_z_30d
  window=2000`; session-constant variations; the condition-filtered
  sensor, duplicated above).

Every criterion in this protocol carries its numeric threshold above;
no threshold is left to be chosen after data contact. The DSR of §5
uses the then-current N, never the frozen 10 if evaluations have
occurred in between.

---

## 11. PRE-FREEZE RECONCILIATION AND RULINGS (Task 8-F, Lei, 2026-07-11)

### 11.1 BLOCKING RECONCILIATION — census viable-region arithmetic

The protocol's first draft stated per-symbol σ₁₂₀ thresholds of
≈ 57–67 bps, sourced from the spec **§15(ii)** table
(`floor_s = 2.25 × (4.0 + fee_s)`). Hop-by-hop audit against the 00b
units convention and spec §4.2:

| hop | quantity | draft (§15(ii) source) | §4.2 strict anchor | units verdict |
|---|---|---|---|---|
| 1 | adverse selection (passive/LEVEL, one-way) | **4.0 bps** (top of the §11(b) grid axis) | **2.0 bps** (00c pin) | both one-way — no round-trip doubling anywhere |
| 2 | fee_s (one-way, 80-sh fill, median bid) | identical | identical | ✓ |
| 3 | C_ow = 0 + AS + fee | 4.0 + fee | 2.0 + fee | commensurate one-way sums |
| 4 | Inv-12 stress ×1.5 (cost side only) | applied | applied | ✓ |
| 5 | anchor ×1.5 | applied | applied | e_ow ≥ 1.5 × C_ow,stressed ✓ |
| 6 | ÷ κ = 0.16 | ≈ 57–67 bps | ≈ 29–39 bps | — |

**Finding: no one-way/round-trip units slip exists** — every hop in
both columns is one-way per 00b. The 2× inflation of the σ thresholds
came entirely from hop 1: the spec §15(ii) ruling substituted the
**top of the sensitivity-grid adverse-selection axis (4.0 bps)** for
the pinned charge (2.0 bps) *inside* the census floor — stacking the
grid's stress vertex on top of the Inv-12 1.5× cost stress (effective
AS 4.0 × 1.5 = 6.0 bps vs the pinned 2.0), i.e. **deliberate extra
margin, not a units error**.

**Ruling applied: the extra margin is NOT approved — the frozen
anchor stands and the bar moves in neither direction.** The census
floor is the pre-registered strict anchor
`e_ow ≥ 1.5 × C_ow,stressed = 2.25 × (2.0 + fee_s)` — the spec §4.2
floors (4.66–6.21 bps) — giving σ₁₂₀ thresholds ≈ **29.1–38.8 bps**
(§1.1 table, corrected). Adverse-selection-axis robustness
({2.0, 3.0, 4.0}) is tested at step 8 on measured execution
economics, where it is binding within the §8 neighborhood; it does
not double-stress the pre-data census floor. For census purposes this
ruling **supersedes the spec §15(ii) floor substitution**; everything
else in §15 (κ = 0.16 frozen, one-way ratchet, ≥ 100-episode power
gate, measured-edge supersession) stands unchanged.

### 11.2 JUDGMENT CALLS — all five approved as ruled

1. **IC thresholds (0.03 / p ≤ 0.01 / n ≥ 1,000):** approved;
   recorded in §2.2 — the criteria are deliberately conjunctive (the
   p-bar binds at moderate n; the 0.03 floor rejects
   trivial-at-huge-n effects).
2. **Embargo 2 bars** (above the 1-bar arithmetic minimum): approved.
3. **CPCV cost-adjusted return series with per-split `edge_scale_bps`
   training:** approved, with the rider (recorded in §3.2) that the
   **pre-cost path distribution is reported alongside the
   cost-adjusted one at every step; the criterion stays on
   cost-adjusted**.
4. **Reconciliation numerics (realized cost ≤ 1.25× disclosed;
   calibration factor ≥ 0.75; breach = re-disclosure, +1 N):**
   approved (§7.2.3).
5. **Latency grid axis {25, 50, 100 ms}:** approved, as amended by
   §11.3.

### 11.3 SENSITIVITY AMENDMENT (approved)

Pass = all **27 vertices in the ±1-step neighborhood of the pinned
profile** (the spec §11(b) 3×3×3 cube at pinned 50 ms latency) **plus
the inv12-stress point**; the full 81-vertex cube is reported;
non-neighborhood failures are logged fragility findings, not kills.
Recorded in §8 and the §9 matrix.

---

## 12. FREEZE DECLARATION

Steps are order-locked (§0); the census (step 1) executes only after
this file is committed; steps 7–8 execute only after Task-12 parity.
This document is **PRE-REGISTERED — FROZEN as of the Task 8-F commit
(2026-07-11)**. From this commit, all changes go in an `AMENDMENTS`
section appended below this line, each entry carrying a timestamp and
justification.

*Protocol frozen — Task 9 (implementation) may begin.*
