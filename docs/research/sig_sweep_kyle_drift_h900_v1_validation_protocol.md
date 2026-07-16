<!--
  File:   docs/research/sig_sweep_kyle_drift_h900_v1_validation_protocol.md
  Status: REJECTED (H10 rejection close-out, Lei, 2026-07-16).
          PRE-REGISTERED — FROZEN (Task 8-F-H10). STEP 1 PROCEED
          (n=152, D={APP,RMBS}). STEP 2: 2a PASS 7/7; 2b FAIL →
          REJECTED per frozen §9 row "2b IC gate", ratified (S.8).
          Steps 2.3 / JC-5 / 3–8 NOT computed. N = 12 confirmed.
          Closure: sig_sweep_kyle_drift_h900_v1_result.md.
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8 / Task 11-A / H10 close-out.

  Provenance (FQ-3 — Task 8-C-H10 census execution; step-2 block
  appended under STATISTICAL RESULTS):
    git_sha: "1e2cf24bfe566c223088fd3d914d3639be4bfe0c"
      (instrument-pin golden commit; HEAD at census start)
    worktree_clean: "yes for tracked tree; formal_spec.md remains
      untracked sibling (freeze-provenance allowance)"
    pythonhashseed: "0"
    host: "CHENGLEI-L-3 / Windows-11-10.0.26200-SP0 /
      Python 3.14.2 (MSC v.1944 64 bit AMD64)"
    artifact_sha256:
      "a2f49e6bb7e32e68c5b776a106b4b27d9aa1218a9e1ed5af5f8a3dffe5eb7829"
      (docs/research/artifacts/sweep_kyle_drift_census_2026-07-16.json;
       bit-identical re-run matched)
    normative_inputs: frozen protocol §1 (this file) + Phase-A
      instruments (faeafaa / 19adcfd / 8b8932f / 1e2cf24) + 03c grid.
-->

# `sig_sweep_kyle_drift_h900_v1` — pre-registered validation protocol (Task 8)

This protocol fixes, numerically and in execution order, every test the
candidate must pass — **before** any implementation exists and before
any outcome statistic is computed. It binds Task 8 (measurement),
Task 9 / Phase B (implementation), and the Task-12-gated execution
overlay. The frozen H2 and H8 protocols are the **structural template**
(task Amendment A): locked order, single-stress anchor, conjunctive-IC
rationale, CPCV dual reporting, 27-vertex+stress sensitivity pass set,
±5 % reconciliation numericization, and the latency axis are reused
verbatim. **Only what H = 900 and the pooled {APP ∪ RMBS} structure
change is re-derived** (embargo arithmetic §3.1, annualization §3.3,
CPCV group/path counts §3.1, GateThresholds implication §3.3, census
power axis §1, step-2 pooling §2.2) — arithmetic shown inline.

**Freeze rule.** This file is **PRE-REGISTERED — FROZEN** as of the
Task 8-F-H10 commit (2026-07-15). It is immutable except for an
appended `AMENDMENTS` section (timestamp + justification per entry).
Converting any FAIL below by tuning is prohibited: **any post-hoc
parameter change is a new trial — N increments and the change is
logged in the ledger (§10) before the re-run.** Simulator-knob
perturbations inside the pre-registered §8 grid do not increment N
(the grid's pass criterion is conjunctive — it can only reject); any
change to alpha-side parameters (`sfi_percentile_min`,
`edge_scale_bps` outside the §3 calibration procedure, `edge_cap_bps`,
gate thresholds, exit ages, session constants, ISO-warm prior used as
a tuned occupancy) does.

**Two validity axes, never conflated (session constraint 5).** Steps
1–6 establish *statistical* validity on pre-cost / disclosure-
arithmetic quantities; steps 7–8 establish *execution* validity on the
Task-12-parity-cleared machinery. No number from steps 1–6 is ever
presented as an economic result, and no number produced before the
Task-12 router timing-parity check is presented as a result at all.

**Evidence set (closed; DISPOSITIONS 4).** Symbols **{APP, RMBS}** ×
the **20-session** 03c grid (10 preamble + 10 Lei-ratified expansion
dates per 03c AMENDMENT 1):

- preamble elevated A: `2025-11-25, 2025-12-04`
- preamble calm: `2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26,
  2026-01-27`
- preamble elevated B: `2026-04-01, 2026-04-10, 2026-04-22`
- expansion elevated A: `2025-12-01, 2025-12-02`
- expansion calm: `2025-12-26, 2025-12-30, 2026-01-12, 2026-01-20,
  2026-01-22` (2025-12-26 / 2025-12-30 tagged HOLIDAY-THIN; tags
  never exclude)
- expansion elevated B: `2026-04-02, 2026-04-07, 2026-04-16`

**Tranche-1B cells ({OLN, DIOD, PCTY, CROX} × expansion dates) carry
NO role** in H10 evidence (DISPOSITIONS 4). **OLN × the 10 preamble
dates** is added evidence-only for the §2.4 tick-artifact tests; it is
excluded from deployable economics, CPCV, DSR, and the execution
overlay. The 03c limitations L1–L5 attach verbatim to every calm /
elevated-A / elevated-B conclusion.

**Units (00b, THE CONVENTION).** Every edge and cost figure below is
**one-way, per-fill, in bps of fill notional** unless explicitly
marked round-trip-derived.

**N = 11** at protocol write (task Amendment H; slate-C ledger; no
outcome contact). First outcome contact on the H10 primary → **N ≥ 12**.

---

## 0. PRECONDITIONS (verified before step 1 executes)

| # | precondition | status at protocol write |
|---|---|---|
| P0-1 | Phase-A deliverables landed (Amendment G) | **REQUIRED BEFORE step 1 or step 2 executes**: (i) `sweep_flow_imbalance` sensor v1.0.0 registered; (ii) census instrument committed; (iii) harness IC row landed on the census-pinned predicate. Until then steps 1–2 are blocked. See §1 / §2.1 / §2.2 Phase-A assignment rows. |
| P0-2 | Grid inputs CLEARED | 03c FQ-6A-R re-check table: CLEARED 2026-07-11; expansion AMENDMENT 1 ratified; Tranche-1B out of scope for this card |
| P0-3 | Realism profile pinned | 00c profile at commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`; configs with `backtest_fill_latency_ns == 0` are invalid for evidence |
| P0-4 | Determinism discipline | every scripted run: `PYTHONHASHSEED=0`, direct `DiskEventCache` read (`~/.feelies/cache`), replay through the real pipeline; provenance (git SHA, command line, artifact SHA-256) recorded per run; bit-identical re-run required for the census artifact (H2 C.7 / H8 C.8 precedent) |
| P0-5 | Step-1 census executes only after this file is FROZEN (post-§11 rulings) and committed | **FROZEN 2026-07-15** (Task 8-F-H10); census still waits on P0-1 |
| P0-6 | Task-12 router timing-parity (steps 7–8 gate) | **AXIS-1 VERIFIED 2026-07-12** (`prompt_pack_12p_router_fill_timing_parity.md`; regression guards committed). Re-verified green at step-7 execution time; any AXIS-1 regression re-opens the gate. |

Execution order is **locked**: 1 → 2 → 3 → 4 → 5 → 6 → (7 → 8) with
steps 7–8 additionally gated on P0-6. A step does not begin until the
prior step's outputs are committed. A park/reject at any step halts
the sequence.

---

## 1. STEP 1 — PARK-RULE CENSUS (spec §4.2–§4.4 / Amendment C–E)

Offline deterministic scan of the closed **40-cell** {APP, RMBS} ×
20-date grid (OLN × 10 preamble added evidence-only for §2.4 inputs).
**NO forward returns are computed anywhere in this step** — the only
return-like quantity permitted is the *unconditional* session
volatility σ₉₀₀ (std of non-overlapping 900 s mid log-returns over
RTH, in bps), which conditions on nothing signal-related.

### 1.0 Phase-A assignment (Amendment G)

| deliverable | owner section | status at protocol write |
|---|---|---|
| **Census instrument** (deterministic offline pass; PYTHONHASHSEED=0) | this §1 — script target `scripts/research/sweep_kyle_drift_census.py` (Task-9-adjacent / Phase-A) | **not yet implemented** — protocol freezes the predicate and park bars before the instrument exists |
| SFI sensor v1.0.0 | §2.1 (sign-golden requires it) + spec §1.1.1 | Phase-A; blocked until landed |
| Harness IC row | §2.2 | Phase-A; blocked until landed |

### 1.1 Episode definition — the entry predicate EXACTLY (Amendment D)

An **eligible boundary (= one episode)** is an h=900
`HorizonFeatureSnapshot` boundary satisfying ALL of the following
(spec §1.4 / §5.3 / card conditional-distribution statement — **no
threshold freedom**):

1. session window: boundary inside the **09:35–15:50 ET** in-window
   (spec §1.4: `no_entry_first_seconds: 300`,
   `session_flatten_seconds_before_close: 600`) on the nominal
   `boundary_ts_ns` — **25 boundaries / session** by construction
   (pack-08 / 09a §2 actuals bit-exact);
2. required entry-warm ids warm and not stale:
   `{sweep_flow_imbalance, sweep_flow_imbalance_percentile,
   realized_vol_30s_zscore}` (spec §1.3 consume-driven set);
3. **SFI decile arm:** `sweep_flow_imbalance_percentile ≥ 0.90`
   (LONG candidate) OR `≤ 0.10` (SHORT candidate);
4. **breakout gate:** `P(vol_breakout) < 0.7` on the latched
   `hmm_3state_fractional` posterior (reference defaults; per-session
   causal-prefix calibration on the first ≤ 100,000 RTH quotes;
   advanced once per quote before the boundary is read);
5. **vol-z backstop:** `realized_vol_30s_zscore ≤ 3.0`;
6. sign agreement (spec §5.2): LONG candidates require
   `sweep_flow_imbalance > 0`; SHORT candidates require
   `sweep_flow_imbalance < 0`.

Pipeline pins: RTH filter 09:30 ≤ t < 16:00 ET on
`exchange_timestamp_ns`; events sorted by `(timestamp_ns, sequence)`;
reference `platform.yaml` sensor params for existing sensors;
SFI params per spec §1.1.1 (`window_seconds=900`,
`min_eligible_prints=20`, `max_gap_seconds=60`, Class-A ∩ id-14,
`drop_correction_records={10,11,12}`); h=900 features from the
production factories once Phase-A wiring lands; fresh sensor/regime
state per session.

**ISO-warm measurement (Amendment D — replaces ASSERTED 0.95).** The
census **measures** the eligible-print warm fraction
(`sweep_flow_imbalance.warm` share of in-window boundaries per
symbol × session) and the joint conditioning occupancy at the frozen
thresholds above. The ASSERTED 0.95 design prior is **resolved by
measurement** — never tuned. If measured warm drives the pooled
contamination-excluded episode count below the §1.5 park floor →
**PARK on power** (no threshold / prior tuning). **SFI warm-coverage
drop rule (coverage-not-tuning):** warm fraction < 0.5 on > 2
sessions ⇒ that symbol drops from D.

### 1.2 Frozen viable-region definition (numeric, before execution)

κ = **0.158, FROZEN** (spec §4.1; one-way ratchet — revisable down on
evidence, never up; superseded entirely by the measured conditional
edge once step 2 has run). Per-symbol single-stress floors (spec
§4.2, 8-F §11.1 anchor, one-way, per-fill, bps of fill notional):

| symbol | floor = 2.25 × (2.0 + fee) (bps) | σ₉₀₀ min = floor/κ (bps) | short rider-incl. floor (bps) |
|---|---|---|---|
| APP  | **4.68** | **29.62** | **5.82** |
| RMBS | **5.51** | **34.87** | **6.60** |

A (symbol, session) cell is **in the viable region** iff its realized
session σ₉₀₀ ≥ the symbol's σ₉₀₀ min. σ₉₀₀ estimator (recorded, not
tuned; H2/H8 C.2 convention at H = 900): Bessel-corrected sample std
of non-overlapping 900 s mid log-returns on the 09:30-anchored grid
(last-mid-at-or-before sampling, ~26 raw RTH returns/session before
session-discipline trim), in bps. SELL-leg viability uses the
rider-inclusive short floor column (spec §4.2).

### 1.3 Contamination handling (Amendment E; JC-1 APPROVED 2026-07-15)

Because the NEW sensor **already filters** Class-A ∩ id-14 +
correction drop at construction, **entry episodes are Class-A ∩ id-14
filter-clean by construction** (spec §1.5; contamination-excluded
multiplier = **1.0 at design**).

**Census EXCLUDES (binding primary count):** nothing beyond the
sensor's own filter — the primary episode count IS the §1.1 predicate
count. No post-hoc intensity or binary exclusion is applied to the
primary power number.

**No-double-exclusion rationale (vs H8 JC-1):** H8 required intensity
exclusion because its conditioning variable (`kyle_lambda_60s`)
ingested unfiltered trade prints and the H2 binary any-flag
convention saturated (≈ 98.8 % of APP conditioning boundaries). H10's
entry conditioner is constructed under Class-A ∩ id-14 + correction
drop — applying a second exclusion layer on top of the sensor filter
would double-count the same hygiene and deflate power without a
contamination mechanism the filter has not already removed. H8's
intensity instrument remains a REPORT diagnostic only (§ below).

**Census REPORTS (diagnostic only, never binding on park):**

- residual non-A / non-id-14 co-travel in the trailing 900 s window
  at eligible boundaries (prints that failed the filter — should be
  near-zero by construction);
- **numeric flag (JC-1 ruled):** residual non-A / non-id-14
  co-travel share **> 1 %** at eligible boundaries ⇒ **sensor-bug
  investigation trigger** — never a park, never a power deflator;
- Class-B flag intensity in the same window (H8 JC-1 intensity
  instrument at 2.0× count-basis — precedent, not primary; reported
  for Lei adjudication of mixture θ₂/θ₃);
- both-ways counts only if a drafted unfiltered SFI variant is ever
  evaluated (+1 N).

### 1.4 Census outputs (all per symbol × session × daily stratum)

- eligible-episode counts (§1.1), split LONG / SHORT — SHORT feeds
  the long-only restatement rule (§1.6);
- measured ISO / SFI warm coverage per session (ASSERTED→measured
  resolution); coverage drop rule applied;
- residual non-A co-travel diagnostics (§1.3 REPORTS);
- realized session σ₉₀₀ (bps) and viable/non-viable labels (long floor
  and short rider-inclusive separately);
- (intraday gate state × daily stratum) 2×2 boundary table;
- spread-in-ticks distribution at eligible boundaries AND at all warm
  in-window boundaries, per symbol incl. OLN (§2.4 / §4 inputs);
- per-stratum episode counts for elevated-A / elevated-B / calm (L4:
  A and B reported separately, never pooled).

### 1.5 Park conditions (Amendment C — card→protocol deviation logged)

**Card→protocol deviation (Amendment C; logged, never silent):**

| # | card / design | this protocol | why |
|---|---|---|---|
| D-C1 | pooled ≥ **130** contamination-excluded episodes (30 % design margin over ≥ 100) | census park floor = pooled ≥ **100** contamination-excluded episodes across {APP, RMBS} | Lei Amendment C: ≥ 130 is the **design margin**, not the census bar; ≥ 100 is the census floor (H8 park precedent). The card's 146.2 design-central projection vs ≥ 130 remains the *design* headline only. |

Park conditions — **either parks the card** before any IC outcome is
treated as a PROCEED:

1. **Edge-region emptiness:** for every deployable symbol, the viable
   region contains zero primary eligible episodes → **PARK**.
2. **Power floor (pooled):** pooled contamination-excluded primary
   episodes across {APP ∪ RMBS} (viable-region restricted) **< 100**
   — including after ISO-warm measurement replaces ASSERTED 0.95 →
   **PARK on power**. No threshold / prior tuning.

**Axis split (Amendment C; card block-3 sketch):** a **single-symbol
shortfall** inside the pool parks **nothing** by itself, **unless**
that symbol also fails **deployability park arithmetic** (edge-region
emptiness on that symbol, the §1.6 rider / coverage drop, or — on a
primary 2b PASS only — the §1.6 / §2.2.1 SIGN-CONSISTENCY
D-membership condition), in which case it drops from D and the
**pool is re-checked** against ≥ 100 on the remaining symbols.
Undefined intersection = freeze-blocking defect (§9 precedence).

**n-class labels (Amendment B / 3-M):** park condition 1
(edge-region emptiness after measured σ) is **n-variant** (more
sessions can cure) → PARK evidence-infrastructure when empty on all
symbols. Park condition 2 (pooled < 100) is **n-variant** → PARK
on power. Neither is a magnitude REJECTED.

### 1.6 Deployable-set restatement rules (pre-registered; JC-5 sign-consistency added)

The census fixes **D** and the pool:

- **D = {symbols that clear deployability}**: edge-region non-empty
  under long floor (and short rider if two-sided claim retained);
  warm-coverage drop rule not fired.
- **RMBS long-only restatement:** if RMBS fails the SELL-leg axis
  (κ·σ₉₀₀ or measured short edge vs rider-inclusive floor 6.60 bps),
  RMBS restates **long-only** and its contribution to the pooled
  power count is the continuation-long episode count alone; D
  membership re-checks.
- **SIGN-CONSISTENCY D-membership (JC-5 ruled, deployability class;
  fires only on a primary §2b PASS):** each symbol then in D must
  show own-boundary extreme-SFI RankIC **sign matching the claim**
  (continuation-positive). Fail ⇒ that symbol **leaves D**; pooled
  power axis-split recheck vs ≥ 100 on remaining D. **No magnitude
  bar, no p bar;** cannot loosen a primary fail, cannot park the
  card, cannot REJECT — acts only on a pass (conflict with §9 row
  2b impossible by construction). See §2.2.1 / §9.1.
- **Symbol fails deployability ⇒ drops from D**; pool re-checks
  ≥ 100 on remaining D. Pool failing after drop → PARK.
- **Both symbols fail deployability ⇒ PARK** regardless of raw
  counts.
- OLN is never in D.

### 1.7 Post-park path

**No occupancy re-threshold variant is pre-authorized for H10.** The
decile split (0.90 / 0.10) IS the mechanism claim (urgency at
extremes), not a tuning axis; the ISO-warm prior is measured, not
re-fit. A park on power or emptiness stops for Lei review. Any
subsequent variant requires Lei's explicit approval with reasons and
is a new ledger row (N-neutral until outcome contact; first IC
contact +1 N). Iterative occupancy fishing is prohibited.

---

## 2. STEP 2 — SIGN-GOLDEN + IC GATE (ENG-3 precedent, gas_01/gas_02)

Per the repo's own promotion policy (engine-readiness ENG-3, as
exercised in `docs/research/gas_01_integrated_ofi.md`): **no promotion
of the signature without BOTH (a) and (b).**

### 2.1 (a) Sign-golden through the REAL pipeline

**Phase-A assignment (Amendment G):** requires `sweep_flow_imbalance`
sensor v1.0.0 + h=900 feature wiring. New test module
`tests/research/test_gas_sweep_kyle_drift_sign.py` (Phase A / Task 9
implements; assertions fixed here).

Synthetic tape with known ground truth pushed through the real
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (the
gas-01 pattern):

1. **Informed-continuation golden (LONG):** a synthetic tape whose
   trailing 900 s window is dominated by Class-A ∩ id-14 buy-side
   ISO prints (tick-rule +1; enough eligible prints for SFI warm ≥
   20) so that at the h=900 boundary
   `sweep_flow_imbalance > 0` and
   `sweep_flow_imbalance_percentile ≥ 0.90` ⇒ the §5.2 draft
   `evaluate` (once implemented) emits direction **LONG** — trade
   WITH the sweep imbalance.
2. **Mirror golden (SHORT):** the same tape mirrored ⇒
   `sweep_flow_imbalance < 0`, percentile ≤ 0.10 ⇒ SHORT.
3. **Interior-null golden (THE card-defining assertion):** the same
   absolute SFI magnitude but percentile interior to (0.10, 0.90) ⇒
   `evaluate` returns **None** — no signal without the extreme-decile
   arm. This is the mechanism gate in golden form.
4. **Filter-exclusion golden:** identical tape with sale condition
   stripped of id-14 (or Class-A failed) ⇒ SFI window does not
   accumulate those prints ⇒ extreme percentile not produced by
   non-eligible flow ⇒ entry suppressed / SFI not driven by junk.
5. **Warm-gate golden:** < 20 eligible ISO prints in the trailing
   900 s ⇒ `sweep_flow_imbalance` not warm ⇒ entry suppressed
   (required-warm set, spec §1.3).
6. **Sign-disagreement golden:** percentile ≥ 0.90 but
   `sweep_flow_imbalance ≤ 0` (or mirror) ⇒ `evaluate` returns
   **None** (spec §5.2 sign agreement).
7. **h=900 key-presence golden:** the snapshot at h=900 carries the
   consumed entry ids (factory wiring regression lock, P0-1).

Any assertion failure ⇒ **REJECTED (sign/wiring defect)** — fix is an
implementation correction, not a tuning event (N unchanged), but the
gate must re-run from scratch. Census-consistency smoke (Phase B
mismatch after YAML lands): implementation-correction re-run, N
unchanged (spec §15).

### 2.2 (b) RankIC evidence — thresholds and sessions fixed now

**Phase-A assignment (Amendment G):** harness IC row on the
census-pinned predicate — `scripts/sensor_feature_ic.py` extended
with an H10 row (Phase A implements; measurement plumbing for the
pre-registered primary trial, not a new trial). Sensors:
`sweep_flow_imbalance` (1.0.0), `kyle_lambda_60s` (2.0.0 causal; F2
diagnostic), `realized_vol_30s` (1.3.0) at reference params; features
= consumed ids at h = 900; each warm boundary paired with the forward
mid log-return over the snapshot horizon; statistics via
`research/forward_ic.py` (`spearman_ic`, `bucketed_forward_return`,
`long_short_edge_bps`).

**IC variable (fixed now — conditional-extreme hypothesis):** the
primary IC pair is `x = sweep_flow_imbalance` (signed) vs `y` =
signed forward 900 s mid log-return, computed **within the extreme-
SFI stratum** (`sweep_flow_imbalance_percentile ≥ 0.90` OR `≤ 0.10`,
with continuation sign matching SFI sign). The interior stratum
(percentile ∈ (0.10, 0.90)) is the pre-registered contrast (F2/I-1
companion: continuation there too ⇒ unregistered momentum).

**Sessions (named now, the closed set):** the 40 cells {APP, RMBS} ×
the 20 dates above. **Primary evidence = pooled {APP ∪ RMBS}** over
viable-region sessions (Amendment F / card block 3). Contamination
handling per §1.3 (primary = filter-clean; REPORTS alongside).

**Numeric gate (ALL required, at h = 900) — conjunctive-IC rationale
carried verbatim from 8-F:**

| criterion | threshold | n-class |
|---|---|---|
| extreme-SFI pooled RankIC sign | > 0 (continuation-correct) | **n-invariant** (sign) |
| extreme-SFI pooled \|RankIC\| | ≥ **0.03** | **n-invariant** (magnitude) |
| extreme-SFI pooled significance | Fisher-z two-sided p ≤ **0.01** | n-variant (p) |
| pooled sample minimum | n ≥ **100** warm boundaries in the extreme-SFI stratum pooled over {APP ∪ RMBS} viable-region (else INSUFFICIENT). Feasibility: at 25 bars/session the full 40-cell grid holds ≤ 1,000 warm in-window boundaries; extreme decile ≤ ~200 before HT/gate — H8's n ≥ 1,000 is **unreachable by construction** at H = 900. Floor aligned to research-protocol ~100 and the §1.5 census floor. **JC-3 APPROVED 2026-07-15:** n-variant label; expectation note — at pooled n ≈ 200 the p ≤ 0.01 conjunct binds at realized RankIC ≈ 0.16, commensurate with frozen κ 0.158; the gate tests the claimed strength. Unreachable ⇒ PARK evidence-infrastructure, never magnitude rescaling. | **n-variant** (power) → PARK evidence-infrastructure if unreachable after measurement, never magnitude rescaling |
| interior contrast (F2/I-1) | extreme-stratum RankIC minus interior-stratum RankIC > 0, AND interior conditional continuation edge ≤ 0 within 2 SE (not significantly positive) | **n-invariant** on sign of contrast |
| F2 λ / volume co-travel (spec §12 F2) | among primary eligible episodes, `kyle_lambda_60s_percentile` elevated vs baseline OR same-direction print-volume elevation vs baseline — at least one contrast > 0 with material separation (reported; binding: both absent ⇒ F2 fail) | mechanism |
| per-symbol diagnostics | RankIC \|RankIC\|, n, p reported per symbol — magnitude/p **NON-GOVERNING**; sign feeds §2.2.1 SIGN-CONSISTENCY D-membership on a primary 2b PASS only | magnitude/p diagnostic; sign → D on pass |
| bucket monotonicity | `bucketed_forward_return` (5 equal-count buckets of x, extreme stratum): top-minus-bottom forward-return spread positive in the continuation direction | **n-invariant** (sign) |
| conditional tail (F1 anchor) | mean continuation-signed 900 s forward return on primary eligible episodes > 0 with t ≥ 2 pooled over {APP ∪ RMBS} | **n-invariant** on sign; t is n-variant |

The criteria are **deliberately conjunctive** (8-F ruling, carried
verbatim): the p ≤ 0.01 bar binds at moderate n, and the
|RankIC| ≥ 0.03 floor rejects effects that are trivial-in-magnitude
yet significant at huge n. Neither alone is sufficient.

#### 2.2.1 Per-symbol step-2 posture (JC-5 RULED 2026-07-15)

**No binding per-symbol magnitude/significance step-2 safeguard**
(proposal accepted). Pooled §2.2 criteria alone govern the primary
2b PASS/FAIL. Per-symbol RankIC magnitude and p are diagnostics only.

**PLUS — SIGN-CONSISTENCY D-membership condition (deployability
class, §1.6 family; ruled modified):** on a **primary 2b PASS**, each
symbol then in D must show own-boundary extreme-SFI RankIC **sign
matching the claim** (continuation-positive). Fail ⇒ that symbol
**leaves D** ⇒ pooled-power axis-split recheck (§1.5 / §9.0.2) vs
≥ 100 on remaining D. **No magnitude bar, no p bar.** Precedence
(§9.1): acts **only on a pass** — cannot loosen a primary 2b FAIL,
cannot park the card, cannot REJECT. Conflict with §9 row 2b
impossible by construction (S.8 / Amendment F satisfied).

Rationale (recorded): H10's evidence structure is pooled-primary by
card design; the free-rider hole (pooled pass driven by one symbol
while the other carries the opposite sign) is closed by
sign-consistency D-membership without reintroducing an A-2.1-class
magnitude/p conjunct that could conflict with the primary gate.

### 2.3 Measured-edge anchor (spec §4.1 / §5.5 acceptance test)

The measured conditional edge (mean continuation-signed 900 s forward
return on primary eligible episodes, bps one-way, per symbol in D,
viable region) must be **≥ the per-symbol single-stress floor**
(APP 4.68, RMBS 5.51 bps) for the symbol to remain in D; SELL-leg
edges are additionally tested against the rider-inclusive short
floors (APP 5.82, RMBS 6.60). This measured value supersedes all κ
arithmetic from this point (spec §4.1 one-way ratchet) and becomes
the G12 disclosure input (`edge_estimate_bps` = the D-set minimum
measured edge, conservative). If D empties here, the card parks.

### 2.4 Tick-constraint artifact tests (spec §8 / §10 tick axis)

Run alongside the IC gate (evidence set including OLN × 10 preamble):

1. spread-in-ticks distribution **at eligible boundaries** per symbol;
2. **≥ 4-tick-stratum re-derivation:** conditional continuation edge
   on boundaries with prevailing spread ≥ 4 ticks; pass = sign-
   consistent with the pooled estimate; collapse ⇒ definition kill
   on the affected stratum;
3. **OLN quantum test:** conditional 900 s move mass vs the
   ±1 half-tick quantum; genuine persistence must show mass beyond
   one quantum. Evidence finding only — OLN is never deployable;
4. sign difference across buckets after quantum correction ⇒
   **definition-level kill**.

---

## 3. STEP 3 — CPCV (`research/cpcv.py`)

### 3.1 Configuration (numeric, with the H=900 re-derivation — Amendment A)

Run **per symbol in D**, on that symbol's 20 grid sessions (pooled
structure does not merge symbols inside a CPCV path — serial
dependence is within-symbol).

- **Bar** = one h=900 in-window boundary; session discipline ⇒
  **25 bars/session**, `n_bars ≈ 500` per symbol on the 20-session
  grid (exact count = emitted in-window boundaries; sessions never
  concatenate state — sensors and regime engine re-warm per session
  replay).
- **Groups:** `n_groups = 20` — one contiguous group per grid session
  in calendar order (Amendment A: carried; group boundaries coincide
  with session boundaries).
- **k:** `k_test_groups = 2` ⇒ φ = C(20,2) = **190 combinations**,
  paths = C(19,1) = **19 reconstructed paths ≥ 8** (`cpcv_min_folds`
  ✓) — Amendment A carry.
- **Purge:** `label_horizon_bars = 1`. Derivation: the label is the
  900 s forward mid return ⇒ label span = 900 s = 1 bar exactly.
- **Embargo:** `embargo_bars = 3`. Derivation (Amendment A; bars
  shown):

  | component | seconds | note |
  |---|---|---|
  | label horizon (purge) | 900 | 1 bar — covered by `label_horizon_bars = 1` |
  | SFI event-time window | 900 | `HorizonWindowedFeature` / sensor `window_seconds=900` |
  | `kyle_lambda_60s` OLS window | 60 | F2 fingerprint lookback nested under SFI |
  | deepest feature lookback | **960** | 900 + 60 |
  | residual after 1-bar purge | 960 | ⌈960 / 900⌉ = **2 bars minimum** |
  | no-fixed-constant components | +1 bar | `realized_vol_30s_zscore` 2000-reading count window (`RollingZscoreFeature` default — quote-rate-dependent) + quote-clocked HMM posterior (spec §3 tick-dwell caveat); mirrors approved H2/H8 +1 pattern |
  | **adopted `embargo_bars`** | **3** | 2 + 1 |

  Total forward exclusion = 1 + 3 = **4 bars = 3,600 s** per test
  region. `embargo_bars = 3 ≥ cpcv_min_embargo_bars = 1` ✓; the
  block-bootstrap block length is `max(1, embargo_bars) = 3` bars
  (the declared serial-correlation length), per `build_cpcv_evidence`.

### 3.2 Return series and per-split training (the CPCV contract)

Per-bar return series per symbol: at each boundary, the
**continuation-signed 900 s forward mid log-return minus the
round-trip-derived cost 2 × C_ow,stressed(symbol)** — C_ow,stressed =
1.5 × (2.0 + fee) so the deduction is APP ≈ 6.24 / RMBS ≈ 7.29 bps
one-way round-trip-derived — **if the boundary is entry-eligible
under the full frozen rule** (§1.1 + the `evaluate` EV gate with the
split's trained `edge_scale_bps`), else **0.0**. This is a
*statistical-validity* series — a disclosure-arithmetic cost proxy,
not an execution result (fill realism enters only at steps 7–8).

Per-split training: on each of the 190 splits, `edge_scale_bps` is
re-estimated on the split's purged+embargoed **train** bars (OLS of
continuation-signed forward return on the spec §5.2 normalised
exceedance `excess`, through the origin, clipped to the declared
range [6.0, 16.0]) and applied to the **test** bars through the
frozen `evaluate` rule. All other parameters are frozen at spec
defaults (`sfi_percentile_min = 0.90`, `edge_cap_bps = 12.0`, the
per-symbol floor constants, gate thresholds §5.3). This in-protocol
calibration is part of the single pre-registered primary trial; it
does not increment N. **JC-8 APPROVED 2026-07-15** (regressor as
proposed).

**Dual reporting (8-F ruling, carried verbatim):** the **PRE-COST
path distribution** (same series without the 2 × C_ow,stressed
deduction) is computed and reported **alongside the cost-adjusted one
at every step** that quotes CPCV output — the pass/fail **criterion
stays on the cost-adjusted series**. The pre-cost distribution is
diagnostic context (separating "no continuation exists" from
"continuation exists but below the cost proxy"), never a result.

### 3.3 Annualization and thresholds (H=900 re-derivation; GateThresholds implication: NONE)

```
annualization_factor = sqrt(25 × 252) = sqrt(6,300) ≈ 79.3725
```

(bars/session × trading days/year — the sqrt(252)-commensurate
scaling for 900 s in-window bars), passed to `build_cpcv_evidence` so
emitted Sharpes are annualised and directly comparable to the
`GateThresholds` defaults. Bootstrap: `n_bootstrap = 10,000`,
`seed = 0` (Inv-5 bit-identical).

**Thresholds: the `GateThresholds` defaults, NO per-alpha
`gate_thresholds:` override — none is needed and none is
pre-registered** (Amendment A: H = 900 changes the annualization
factor and path count, not the annualised bars themselves — 19 paths
≥ 8, embargo 3 ≥ 1, and the annualised Sharpe / p-value bars are
horizon-independent once the annualization factor is commensurate):

| gate | value | this run |
|---|---|---|
| `cpcv_min_folds` | ≥ 8 reconstructed paths | **19** by construction |
| `cpcv_min_mean_sharpe` | ≥ 1.0 (annualised) | must clear on **every** symbol in D |
| `cpcv_max_p_value` | ≤ 0.05 (block bootstrap) | every symbol in D |
| `cpcv_min_embargo_bars` | ≥ 1 | **3** by construction |

Fail on any symbol ⇒ that symbol leaves D; pool / D emptying ⇒ status
per §9. **n-class:** mean-Sharpe / p-value fails after honest
annualization are treated as **n-invariant REJECTED** (does not
survive purged OOS reconstruction); inability to form 20 groups is
**n-variant PARK** (evidence-infrastructure).

---

## 4. STEP 4 — REGIME STRATIFICATION (manual per R6 / research-protocol Phase 3.3 — no shipped harness)

### 4.1 Strata (cutpoints fixed now; spread axis = spread-in-ticks — JC-4)

Partition **warm h=900 boundaries** (per symbol, full 20-session grid)
on two axes:

- **Vol axis** — HMM dominant state (`RegimeState.dominant_name`,
  `hmm_3state_fractional`): `compression_clustering` / `normal` /
  `vol_breakout` (3 strata);
- **Spread axis** — boundary-time prevailing **spread-in-ticks** at
  **per-symbol terciles of the UNCONDITIONAL grid spread
  distribution** — all warm in-window boundaries, never
  eligible-only — **frozen at census time and disclosed per symbol**
  (H8 JC-4 carried: spec bans `spread_z_30d` on this card — census
  warm 0.03–0.16 on thin names; F3 is worded on spread-in-ticks;
  APP vs RMBS medians live in different buckets). Cutpoints computed
  once from the census output before any forward return exists.

The daily calm/elevated-A/elevated-B stratum is a **third, reporting
axis** (every statistic also reported in the gate-state × daily-
stratum 2×2). F3 kill clause: conditional continuation sign across
**spread-in-ticks terciles within the benign stratum** (benign =
`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0`).

### 4.2 Procedure and per-stratum minimum

Within each (vol × spread) stratum: repeat the §2.2 IC test
(extreme-SFI `spearman_ic` on stratum boundaries, plus the interior
contrast) and, where the stratum holds enough bars to form the §3
groups, repeat CPCV (same config; a stratum that cannot form 20
groups reports CPCV-INFEASIBLE, not a fail). **Minimum per-stratum
sample = 100 boundary observations** (research-protocol Phase 3.3
rule 4); below it the stratum reports **INSUFFICIENT** — never
pooled away, never counted for or against the acceptance rule.

### 4.3 Acceptance rule (numeric)

**PASS** iff, on the pooled {APP ∪ RMBS} evidence: the extreme-SFI
conditional continuation is **sign-stable (continuation-positive) AND
extreme-SFI RankIC ≥ +0.02 with Fisher-z p ≤ 0.05** in at least
**2 vol strata × 2 spread strata** (i.e. ≥ 2 cells on each axis among
cells with n ≥ 100). Single-stratum concentration is a fragility flag
reported to Lei (not an automatic kill) **unless** the conditional
continuation sign reverses across spread-in-ticks terciles within the
benign stratum — that is F3, a **definition-level kill**.

**n-class:** sign reversal across strata = **n-invariant REJECTED**
(definition); failure to clear ≥ 2 × 2 with adequate n =
**n-variant** → HYPOTHESIS-REVISE (regime-fragile; a narrower card is
a new trial).

### 4.4 Invariance checks (spec §6, slotted here; numeric criteria)

- **I-1 (zero-integrated-edge conservation, mandatory):** funding
  pool (a) = Σ_episodes (measured continuation move × contra-side
  fading volume inside the episode window — resting LPs'
  mark-to-horizon loss); strategy integrated pre-cost conditional
  edge (b) at declared participation (≤ top-of-book scale).
  **Pass:** (b) / (participation share × (a)) ≤ 1.5. Companions:
  (i) unconditional forward returns over all matched in-window
  boundaries integrate to ≈ 0 — |mean| ≤ 2 × SE; (ii) the **interior
  SFI stratum** shows reversion or zero — continuation-signed mean
  ≤ 0 within 2 SE. Fail ⇒ **misattribution ⇒ hypothesis-revise**.
- **I-2 (side symmetry):** continuation-long vs continuation-short
  conditional edges in the benign stratum agree within sampling
  error — two-sample z ≤ 2. Fail ⇒ hypothesis-revise; SHORT carries
  the SSR/HTB optimism caveat; §1.6 RMBS long-only is an *economic*
  asymmetry — I-2 tests pre-cost mechanism symmetry only.
- **I-3 (SFI dose-response; JC-9):** conditional continuation-signed
  forward return in SFI-percentile bands
  {[0.90, 0.95), [0.95, 0.98), [0.98, 1.0]} (and symmetric lower
  tail) plus the interior contrast band. **Numeric reading:** the
  top extreme band must exceed the interior band by ≥ 1 SE, and the
  three extreme-band means must not be strictly decreasing in band
  order. Flat ⇒ the decile split is a coin flip ⇒ hypothesis-revise;
  inverted-U at the extreme top ⇒ θ₃ ignition signature — red flag,
  not an automatic kill.
- **IC(t) decay (research-protocol Phase 5; JC-7):** compute RankIC
  at forward horizons t ∈ {120, 300, 900, 1800} s on the extreme-SFI
  stratum; fit `IC(t) = IC_0 · exp(−λ t)`; fitted half-life must lie
  in **[225, 900] s** (declared hl = 450 ± a factor of 2). Outside ⇒
  hypothesis-revise; non-decaying IC(t) is F1-adjacent death.

---

## 5. STEP 5 — DSR (`research/dsr.py`)

Computed on the pooled-D per-bar cost-adjusted return series (§3.2
definition, all D symbols' sessions, bars in (symbol, session, time)
order; n_obs = total bar count — ≈ 500 × |D|):

- `build_dsr_evidence_from_returns(returns=…, trials_count=N,
  annualization_factor=sqrt(6,300) ≈ 79.37)` with **N = the
  then-current living-ledger count at computation time** — **N = 11
  at protocol write** (Amendment H); every evaluation event between
  freeze and the DSR computation increments it first (FQ-6B-R).
  Spec §13 drafted-not-evaluated variants count **only if actually
  evaluated** by then.
- `trial_sharpe_variance`: **None** (iid-Gaussian null floor
  `1/(n_obs−1)`), because unevaluated trials have no measured Sharpes
  to pool an empirical variance from. Weakest honest deflation
  (module `UserWarning`); disclosed verbatim in the evidence artifact.
- **Report `expected_max_sharpe(n_trials=N, trial_sharpe_variance=
  1/(n_obs−1))` — annualised — as the noise ceiling alongside the
  observed Sharpe** in every artifact quoting the DSR.

**Thresholds (defaults, no override):** `dsr` (deflated Sharpe excess,
annualised) ≥ **`dsr_min` = 1.0** AND `dsr_p_value` ≤
**`dsr_max_p_value` = 0.05**. An observed Sharpe below the reported
noise ceiling fails regardless of nominal significance (F1's honest-N
clause). Fail ⇒ **REJECTED** (**n-invariant** at fixed N — more data
does not raise the noise ceiling's deflation of the same trial count;
acquiring more trials without a better Sharpe worsens DSR).

---

## 6. STEP 6 — DRIFT DIAGNOSTICS

**What re-estimates, on what window:** at runtime, **nothing** — all
sensor params, gate thresholds, and session constants are fixed (spec
§1.4 / §5.1). The only estimated quantity in the whole candidate is
`edge_scale_bps` (Task-8 calibration, §3.2). Drift diagnostics
therefore test the *stability of the fixed-parameter machinery and
the single calibrated parameter* across the grid's sessions;
pre-stated bounds below are disqualifying.

### 6.1 Regime-engine behavior (`scripts/regime_diagnostics.py` as anchor)

Run per (symbol ∈ D, session) over the grid with the Task-9 config,
`--horizon 900`. The H10 regime arm is an **exclusion screen**
(`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0`), not a
positive benign selector — bounds adapted from H8 JC-5 (JC-6 here):

| diagnostic | pre-stated stability bound (per session unless noted) |
|---|---|
| min pairwise emission separation d | ≥ 0.5; below ⇒ posterior non-discriminative that session ⇒ boundaries leave the benign stratum (fail-safe) |
| argmax occupancy | no single state > 0.98 of RTH quotes (else same treatment) |
| exclusion-screen OFF fraction (`P(vol_breakout) ≥ 0.7 ∨ rvz > 3.0` over in-window boundaries) | ≤ 0.95 per session; > 3 deployable-symbol sessions above ⇒ drift-disqualifying (hypothesis-revise). Always-ON screen (OFF ≈ 0) is expected calm-tape behavior — reported, not bounded. |
| median screen-ON dwell (seconds, per symbol pooled) | ≥ **900 s** (one horizon — tick-dwell caveat made numeric); below ⇒ hypothesis-revise |
| full-gate ON fraction (conditioning fraction) | reported per session against the census; no numeric kill here — power adjudicated at §1.5 |

### 6.2 Sensor / conditioning stability

| diagnostic | pre-stated bound |
|---|---|
| per-session eligible-episode rate (per deployable symbol, within a daily stratum) | max/min ratio across that stratum's sessions ≤ 5; above ⇒ hypothesis-revise |
| `sweep_flow_imbalance` warm coverage | spec §1.1 coverage rule: warm < 0.5 on > 2 sessions ⇒ symbol leaves D (coverage/power, not tuning) |
| `kyle_lambda_60s` warm coverage (F2 only) | reported; RMBS marginality disclosed — never entry-path; does not drop D by itself |
| `realized_vol_30s_zscore` warm coverage | reported per session (mandatory) |
| L6 sign-stability diagnostic (spec §2 / §9 L6) | tick-rule vs quote-position-of-print agreement on **eligible ISO prints inside conditioned windows**; agreement < 80 % in the benign stratum ⇒ material dilution ⇒ report and carry as edge-dilution haircut in §2.3; systematic one-sided disagreement in the extreme decile ⇒ red flag feeding F1/F2 adjudication |

### 6.3 Calibration stability

Leave-one-session-out re-estimates of `edge_scale_bps` (pooled-D
procedure of §3.2) must all lie within **[0.5×, 2.0×]** of the
full-sample estimate. Outside ⇒ **drift-disqualifying
(hypothesis-revise)** — not tunable within this trial.

---

## 7. STEP 7 — EXECUTION OVERLAY (order-locked after steps 1–6; runs ONLY after P0-6 holds)

**Hard gate:** no number from this step exists as a result until the
Task-12 router timing-parity check has passed (P0-6). If the parity
state has regressed, this protocol halts here with steps 1–6 outcomes
reported as statistical-axis-only.

### 7.1 Configuration

`configs/bt_sig_sweep_kyle_drift_h900_v1.yaml` (Phase B / Task 9
deliverable), instantiated from the pinned 00c profile (checksum
guard; commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`):
`execution_mode: passive_limit`; realism knobs ON exactly as pinned
(`passive_fill_delay_ticks 3`, `passive_queue_position_shares 200`,
`passive_fill_hazard_max 0.5`, `passive_through_fill_size_cap_enabled
true`, `passive_require_trade_for_level_fill true`,
`cost_within_l1_impact_factor 0.3`, `cost_stop_depth_depletion_factor
2.0`, `cost_max_impact_half_spreads 4.0`);
`backtest_fill_latency_ns 50_000_000`, `market_data_latency_ns
20_000_000` (zero latency invalid for evidence);
`signal_min_edge_cost_ratio: 1.5`;
`no_entry_first_seconds: 300`, `session_flatten_enabled: true`,
`session_flatten_seconds_before_close: 600`; symbols = D only.

### 7.2 Runs and required outcomes (numeric)

Per symbol in D over its 20 grid sessions: `feelies backtest
--config configs/bt_sig_sweep_kyle_drift_h900_v1.yaml --symbol <S>
--date <D>` — the **baseline** pass — then the **identical** run set
under `--inv12-stress` (1.5× `cost_stress_multiplier`, 2× both
latency legs; the edge side is never touched, 00b hop 4). Required
outcomes, ALL of:

1. **Per-Alpha Cost Survival verdict = `SURVIVES`** (pooled per
   symbol over its sessions, `min_margin 1.5×`, `min_fills 20`) on
   the **baseline** run — `MARGINAL`, `BLEED` fail outright; `LOW_N`
   (< 20 fills) is a **power failure ⇒ PARKED (execution power)**,
   not a pass.
2. **`SURVIVES` again under `--inv12-stress`** — Inv-12: if the alpha
   vanishes under stress it wasn't real.
3. **Post-cost economics consistent with the disclosed
   `cost_arithmetic` (±5 % reconciliation spirit, numericized per the
   8-F ruling, carried verbatim):** (i) realized `mean_cost_bps` ≤
   1.25 × disclosed `cost_total_bps` (25 % breach ⇒ disclosure wrong:
   re-derive and re-disclose, +1 N); (ii) calibration factor
   `realized mean_edge_bps / disclosed edge_estimate_bps` ≥ 0.75
   (below ⇒ disclosed edge optimistic ⇒ re-disclosure, +1 N);
   (iii) the G12 block's declared `margin_ratio` reconciles with
   components within ±0.05 absolute (load-gate arithmetic, checked
   at Task-9 load).
4. **Fill-quality diagnostics (spec §11(a)), numeric (JC-7):**
   through-fill share of entry fills ≤ 50 % — for this card's
   passive-entry-into-continuation geometry a through fill means
   price crossed back through the resting level (deep retrace), the
   execution-layer θ₂/θ₃ signature; filled-minus-unfilled **900 s**
   markout gap ≤ the 2.0 bps charged adverse selection (450 s
   markouts reported alongside) — if exceeded, F4 arithmetic is
   **re-run with the measured figure** (pre-registered recomputation,
   not a new trial) and outcomes 1–2 re-judged on it. `EXPIRED`
   (timeout-cancel) rate and time-to-fill distribution reported
   against the 3-tick-delay + hazard model.

---

## 8. STEP 8 — SENSITIVITY GRID (spec §11(b) extended; 8-F sensitivity amendment carried verbatim)

Axes, full cross = **3 × 3 × 3 × 3 = 81 vertices**, every vertex a
deterministic re-run of the §7.2 baseline set:

| knob | pinned | grid |
|---|---|---|
| `passive_fill_hazard_max` | 0.5 | {0.25, 0.5, 0.75} |
| `passive_queue_position_shares` | 200 | {100, 200, 400} |
| adverse-selection pair (`cost_passive_adverse_selection_bps`, `cost_through_fill_adverse_selection_bps`) — coupled at the pinned 2.5× ratio, one axis | (2.0, 5.0) | {(2.0, 5.0), (3.0, 7.5), (4.0, 10.0)} |
| `backtest_fill_latency_ns` | 50 ms | {25 ms, 50 ms, 100 ms} |

(`market_data_latency_ns` stays pinned at 20 ms; the 100 ms vertex
equals the Inv-12 2× fill-latency leg.)

**Robustness criterion (8-F ruling, carried verbatim):** the
**binding pass set** is the **27 vertices in the ±1-step neighborhood
of the pinned profile** — the 3 × 3 × 3 cube
`passive_fill_hazard_max × passive_queue_position_shares ×
adverse-selection pair` at the pinned 50 ms fill latency — **plus the
`--inv12-stress` point** (§7.2 run 2: 1.5× costs, 2× latency legs).
**PASS** = the F4 clearance verdict — measured net edge ≥ the
per-symbol §1.2 single-stress floor AND cost-survival `SURVIVES` —
holds at all 27 neighborhood vertices and the inv12-stress point, for
every symbol in D. The AS axis here is a robustness sweep, never a
second stress folded into the floor (no stacking). A verdict that
flips inside the binding set is simulator-dependence: the candidate
is **not execution-valid regardless of the pinned-profile number**.

The **full 81-vertex cube is still run and reported**; failures
outside the binding neighborhood (i.e. at the 25 ms / 100 ms latency
vertices) are **logged fragility findings** — recorded in the
evidence artifact and carried into deployment review — **not kills**.
Grid vertices are pre-registered perturbations of the simulator, not
candidate variants — they do not increment N; the pass rule is
conjunctive and can only reject.

---

## 9. PASS/FAIL MATRIX AND STATUS CONSEQUENCES

### 9.0 Consequence-precedence (FROZEN VERBATIM — Amendment B / spec §4.3)

The following four-point block enters this protocol as **frozen
text** (backlog-13 binding; any undefined intersection is a
freeze-blocking defect):

1. Primary §9 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK; a single-symbol
   shortfall inside the pool does **not** park the card if the pool
   clears ≥ 100 contamination-excluded — unless that symbol also
   fails deployability park arithmetic, in which case it drops from
   D and the pool is re-checked (A-2.1-class axis split, stated now).
   *(Numeric floor in this protocol = 100 per Amendment C; the card's
   sketch said ≥ 130 — deviation D-C1 logged in §1.5.)*
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

### 9.1 Instrument-pair precedence walk (Amendment B — completeness check)

Every intersection that can fire in the same step is declared. An
absent row would be a freeze-blocking defect.

| instruments that can co-fire | which governs | subordinate effect |
|---|---|---|
| §1.5 power (pooled < 100) ∩ §1.5 edge-emptiness | **both PARK** (either parks); report both | — |
| §1.5 pooled power PASS ∩ single-symbol episode shortfall | **pooled governs PROCEED** (§9.0.2); symbol stays unless deployability fails | diagnostic only |
| §1.5 pooled power PASS ∩ symbol deployability fail (edge / rider / warm drop / sign-consistency) | symbol **drops from D**; **pool re-checked** vs ≥ 100 | if pool then fails → PARK |
| §1.5 PARK ∩ any later step | **first-FAIL stop** — later steps do not run | — |
| §2a sign-golden FAIL ∩ §2b | **2a REJECTED** governs; 2b not computed | implementation fix, N unchanged, re-run from 2a |
| §2b magnitude (|RankIC| < 0.03 or sign ≤ 0) ∩ §2b p > 0.01 | **magnitude n-invariant REJECTED** governs (§9.0.3); p is reported | — |
| §2b magnitude FAIL ∩ §2b n < 100 (INSUFFICIENT) | **magnitude REJECTED** outranks sample-floor PARK when magnitude is computable at n ≥ 3; if n below computability, **INSUFFICIENT → PARK (power)** only | never rescale \|RankIC\| floor |
| §2b primary FAIL ∩ per-symbol diagnostic fail | **primary §9 row 2b REJECTED governs**; diagnostics cannot loosen | no magnitude/p safeguard (§2.2.1) — intersection closed |
| §2b primary PASS ∩ per-symbol SIGN-CONSISTENCY fail (JC-5) | **primary 2b PASS stands**; failing symbol **leaves D** (deployability class); pool re-checked vs ≥ 100 | cannot loosen / park / REJECT; acts only on a pass |
| §2b PASS ∩ §2.3 edge anchor fail on all D symbols | **§2.3 PARK** (economics below floor) | D empty |
| §2b PASS ∩ §2.4 tick stratum kill | **REJECTED on affected stratum**; if D empties → PARK | survivors continue |
| §2b F2 fail (no λ / volume co-travel) ∩ §2b RankIC PASS | **REJECTED (F2)** — mechanism attribution dead despite pooled drift | — |
| §3 CPCV fail on one D symbol ∩ other D symbols pass | failing symbol **leaves D**; remaining D continues if non-empty | D empty → REJECTED |
| §4 F3 sign reversal ∩ §4 ≥2×2 miss | **F3 REJECTED (definition)** outranks hypothesis-revise | — |
| §5 DSR fail ∩ §3 CPCV pass | **REJECTED (honest-N)** — CPCV does not override DSR | — |
| §6 drift fail ∩ steps 1–5 pass | **HYPOTHESIS-REVISE** | new trial if parameters change |
| §7 SURVIVES fail ∩ steps 1–6 pass | **TRAP-QUADRANT** (stat valid, exec invalid) | — |
| §7 LOW_N ∩ steps 1–6 pass | **PARKED (execution power)** — n-variant | — |
| §8 neighborhood fail ∩ §7 pinned SURVIVES | **TRAP-QUADRANT** (simulator-dependent) | pinned number is not a result |
| §8 non-neighborhood (25/100 ms) fail ∩ neighborhood PASS | **logged fragility** — not a kill | deployment review only |

### 9.2 Pass/fail matrix

One numeric criterion per step; the status each failure mode assigns.
**Trap-quadrant** is reserved for statistically-valid-but-execution-
invalid (spec §11(d) verbatim: "F4 (execution validity): pre-cost
continuation exists but ≤ 1.5 × C_ow under the passive realism model
→ trap-quadrant").

| step | binding numeric criterion | on FAIL → status | n-class |
|---|---|---|---|
| 1 census | viable region non-empty on ≥ 1 symbol AND pooled contamination-excluded episodes ≥ **100** across {APP ∪ RMBS} (after measured ISO-warm) | **PARKED** (emptiness or power) | n-variant |
| 2a sign-golden | all seven assertions | **REJECTED** (sign/wiring defect; re-run after fix, N unchanged) | n-invariant (wiring) |
| 2b IC gate | extreme-SFI RankIC > 0, \|RankIC\| ≥ 0.03, p ≤ 0.01, n ≥ 100; interior contrast; F2 co-travel; bucket spread positive; tail t ≥ 2 — **pooled primary** | **REJECTED** (F1/F2 dead) | magnitude/sign **n-invariant**; p/n **n-variant** |
| 2b sample floor | n ≥ 100 reachable on the pooled viable-region extreme stratum | **PARKED (evidence-infrastructure)** if unreachable — never threshold rescaling | n-variant |
| 2b→D sign-consistency (JC-5) | on 2b PASS: each D symbol own-boundary RankIC sign matches claim | failing symbol **leaves D**; pool recheck — **not** a park/reject of the card | deployability; acts only on pass |
| 2.3 edge anchor | measured conditional edge ≥ per-symbol single-stress floor on ≥ 1 symbol (SELL: rider-inclusive) | **PARKED** (economics below floor everywhere) | n-variant |
| 2.4 tick tests | ≥ 4-tick stratum sign-consistent | **REJECTED on affected stratum** (grid artifact); if D empties → PARKED | n-invariant (sign) |
| 3 CPCV | 19 paths, mean annualised path Sharpe ≥ 1.0, block-bootstrap p ≤ 0.05, embargo 3, per D symbol, cost-adjusted series | **REJECTED** (does not survive purged OOS reconstruction) | n-invariant (at commensurate annualization) |
| 4 stratification | sign-stable + extreme-SFI RankIC ≥ 0.02 (p ≤ 0.05) in ≥ 2 vol × ≥ 2 spread strata (n ≥ 100 each) | **HYPOTHESIS-REVISE** (regime-fragile); F3 spread-tercile sign reversal in benign stratum ⇒ **REJECTED** | F3 n-invariant; 2×2 miss n-variant |
| 4.4 invariance | I-1 ratio ≤ 1.5 + companions; I-2 z ≤ 2; I-3 gradient exists, no inversion; IC(t) half-life ∈ [225, 900] s | **HYPOTHESIS-REVISE** | mixed; I-1 fail ≈ n-invariant misattribution |
| 5 DSR | dsr ≥ 1.0, p ≤ 0.05, observed > noise ceiling at honest N | **REJECTED** (indistinguishable from max-of-N noise) | n-invariant at fixed N |
| 6 drift | all §6.1–§6.3 bounds | **HYPOTHESIS-REVISE** | n-variant |
| 7 execution | SURVIVES baseline + stressed; reconciliation (§7.2.3); fill-mix bounds | **TRAP-QUADRANT** if steps 1–6 passed; `LOW_N` ⇒ **PARKED (execution power)** | LOW_N n-variant; otherwise exec-axis |
| 8 grid | F4 clearance at all 27 neighborhood vertices + the inv12-stress point, every D symbol (full 81-cube reported; non-neighborhood failures = logged fragility) | **TRAP-QUADRANT** (simulator-dependent economics) | exec-axis |

**Tuning prohibition (binding, repeated):** converting any FAIL by
changing a parameter, threshold, window, stratum definition, or knob
is prohibited within this trial. Any such change is a **new trial**:
increment N in the living ledger, log the variant with its
justification, and re-enter this protocol from step 1 for the new
variant. The one-way κ ratchet (spec §4.1) additionally forbids
upward re-estimation of any κ factor after data contact. No
post-park occupancy re-threshold is pre-authorized (§1.7).

---

## 10. TRIAL LEDGER STATE AT PROTOCOL WRITE (Amendment H)

**N = 11** (slate-C / pack-09 §(3); H8 close-out left N = 11; no
outcome contact in Task 7 or this Task 8 write). The primary object of
this protocol is the slate-C ledger row "H10 primary:
sweep_flow_imbalance(900 s) decile continuation, H=900, hl=450,
passive, pooled {APP,RMBS}" — this protocol is its measurement plan,
not a new trial. Rows that increment **only on evaluation**
(FQ-6B-R):

- the spec §13 drafted-not-evaluated variants (min sweep-volume floor;
  Class-A-filtered NEW λ fallback; session-relative SFI percentile;
  `hard_exit_age_seconds = 1350`; session-constant variations;
  re-thresholded conditioning);
- H9 primary / alt (CONTINGENT SECOND CARD — not authorized for census
  yet; revivable iff H10 passes step 2).

Census-class evaluation (step 1) is N-neutral until first IC /
forward-return contact. **First outcome contact on the H10 primary
→ N ≥ 12.** The DSR of §5 uses the then-current N, never the written
11 if evaluations have occurred in between.

---

## 11. JUDGMENT CALLS AND RULINGS (Amendment H — 8-F pattern; RULED 2026-07-15, Task 8-F-H10, Lei)

Every residual numeric or instrument freedom, with the adopted
proposal and its alternative. **All ten JCs are RULED (2026-07-15);
the per-JC ruling is recorded at the end of each entry and the ruled
text is applied in the named sections. This section is the freeze
record.**

**JC-1 — Contamination EXCLUDES vs REPORTS (§1.3; Amendment E).**
Proposed: primary count = filter-clean §1.1 predicate (multiplier
1.0); REPORT residual non-A co-travel + H8-style intensity as
diagnostics only. Alternative: adopt H8 JC-1 intensity exclusion
(2.0× count-basis) as primary despite Class-A ∩ id-14 construction.
**RULING: APPROVED as proposed, with numeric flag added — residual
non-A / non-id-14 co-travel share > 1 % at eligible boundaries =
sensor-bug investigation trigger, never a park. No-double-exclusion
rationale vs H8 JC-1 recorded in §1.3 (H8 needed intensity because
unfiltered λ saturated binary; H10's sensor filter already removes
the same class — a second exclusion would double-count). Applied in
§1.3.**

**JC-2 — Embargo 3 bars (§3.1).** Arithmetic minimum 2 bars
(900 + 60 = 960 s residual after purge); +1 covers no-fixed-constant
components (rv-z count window + HMM). Alternative: bare 2-bar
minimum. **RULING: APPROVED (3 bars). Confirmed reading recorded:
the 900 in the lookback sum (900 + 60 = 960) is the SFI
feature-lookback window; the label horizon is separately purged at
`label_horizon_bars = 1`. Applied in §3.1.**

**JC-3 — IC-gate pooled sample floor n ≥ 100 (§2.2).** H8's n ≥ 1,000
is unreachable at H = 900 (≤ ~200 extreme-decile boundaries on the
full 40-cell grid). Proposed: n ≥ 100 (research-protocol / census-
floor aligned); unreachable ⇒ PARK evidence-infrastructure, never
magnitude rescaling. Alternative A: carry 1,000 verbatim ⇒
auto-PARK by construction (honest but vacuous). Alternative B:
scale 1,000 × 25/78 ≈ 321 — flagged as the rescaling 8-F prohibited.
**RULING: APPROVED — pooled n ≥ 100, n-variant label. Expectation
note recorded: at pooled n ≈ 200 the p ≤ 0.01 conjunct binds at
realized RankIC ≈ 0.16, commensurate with frozen κ 0.158; the gate
tests the claimed strength. Applied in §2.2.**

**JC-4 — Stratification spread axis = spread-in-ticks per-symbol
terciles (§4.1).** Carries H8 JC-4 (spec bans `spread_z_30d`; F3
worded on ticks). Alternative: fixed cross-symbol cutpoints
(degenerate given APP vs RMBS). **RULING: APPROVED as proposed.
Applied in §4.1.**

**JC-5 — Per-symbol step-2 posture (§2.2.1; Amendment F).** Proposed:
**NONE** — diagnostics only; makes §9-vs-A-2.1 conflict impossible.
Alternative: A-2.1-class conjunct (each D symbol must clear
\|RankIC\| ≥ 0.03 at p ≤ 0.05 on its own n) with explicit
subordination to primary §9 row 2b.
**RULING: RULED MODIFIED — (i) NO step-2 magnitude/significance
safeguard (proposal accepted); (ii) PLUS a per-symbol
SIGN-CONSISTENCY D-membership condition (deployability class, §1.6
family): on a primary 2b PASS, each D symbol's own-boundary RankIC
sign must match the claim; fail ⇒ leaves D ⇒ pooled-power axis-split
recheck. No magnitude/p bar; cannot loosen, park, or reject; acts
only on a pass — conflict impossible by construction. Precedence
declared in §9.1. Applied in §1.5 / §1.6 / §2.2.1 / §9.1 / §9.2.**

**JC-6 — Drift bounds for exclusion screen (§6.1).** Carry H8 JC-5
adapted at H = 900 (screen-OFF ≤ 0.95; median ON dwell ≥ 900 s;
always-ON not a failure). Alternative: H2 two-sided gate-ON band
(inappropriate for extreme-exclusion). **RULING: APPROVED as
proposed. Applied in §6.1.**

**JC-7 — Fill-mix / markout horizon (§7.2.4).** Through-share ≤ 50 %;
filled-minus-unfilled markout gap ≤ 2.0 bps at **900 s** (450 s
alongside). Alternative: bespoke drain-then-non-resumption bound —
rejected as non-numericizable beyond the markout gap. **RULING:
APPROVED as proposed. Applied in §7.2.4.**

**JC-8 — CPCV per-split calibration regressor (§3.2).**
`edge_scale_bps` ~ OLS of continuation-signed forward return on spec
§5.2 `excess`, through origin, clipped [6.0, 16.0]. Alternative:
calibrate on raw SFI level alone (discards the percentile-exceedance
the evaluate rule uses). **RULING: APPROVED as proposed. Applied in
§3.2.**

**JC-9 — I-3 dose-response numericization (§4.4).** Top extreme band
minus interior ≥ 1 SE AND no strict decrease across three extreme
bands; inverted-U = red flag, not kill. **RULING: APPROVED as
proposed. Applied in §4.4.**

**JC-10 — ISO-warm measurement definition (§1.1 / Amendment D).**
Proposed: per (symbol, session) warm fraction = share of in-window
h=900 boundaries with `sweep_flow_imbalance.warm == True`; pooled
episode count re-scored after measurement; warm < 0.5 on > 2 sessions
drops that symbol. Alternative: warm = share of RTH seconds with
eligible-print rate ≥ 20/900 — different estimand. **RULING:
APPROVED as proposed. Applied in §1.1.**

**Pre-ruled by Lei (Amendment C — recorded, not a JC; STANDS):**
census park floor = pooled ≥ **100**; card ≥ 130 = design margin only
(deviation D-C1). Single-symbol shortfall parks nothing unless
deployability also fails.

---

## 12. FREEZE DECLARATION

Steps are order-locked (§0); the census (step 1) executes only after
this freeze commit **and** P0-1 Phase-A deliverables are green; steps
7–8 execute only under P0-6. The §11 rulings landed 2026-07-15
(Task 8-F-H10, Lei) and are applied in §1.3, §1.5, §1.6, §2.2,
§2.2.1, §3.1, §4.1, §4.4, §6.1, §7.2.4, and §9. This document is
**PRE-REGISTERED — FROZEN as of the Task 8-F-H10 commit
(2026-07-15)**. From this commit, all changes go in an `AMENDMENTS`
section appended below this line, each entry carrying a timestamp
and justification.

*Protocol frozen — Phase A / Task 9 (implementation) may begin under
P0-1.*

---

# AMENDMENTS

## A-1 — Phase-A IMPLEMENTATION RECORD (Task 9-A-H10, 2026-07-15)

**Scope.** Phase A only (Ordering B): sensor + census instrument +
harness IC row. **No census execution, no IC numbers, no outcome
contact.** Phase B explicitly out of scope. **N = 11 survives
unchanged** (living ledger; first outcome contact still reserved for
step-2 IC on the H10 primary → N ≥ 12).

### Commit ledger

| # | sha | delivered |
|---|---|---|
| 1 | `faeafaa` | `sweep_flow_imbalance` sensor v1.0.0 (`src/feelies/sensors/impl/sweep_flow_imbalance.py`) + unit tests (hand goldens, warm/gap, filter-boundary per excluded class, incremental-vs-recompute, Hypothesis truncation causality, no retroactive-stamp conditioning) + `__init__.py` catalog row. Coverage map: `sensors/` wholly owned by `audit_sensor` — no `_FILE_OWNERS` edit required. |
| 2 | `19adcfd` | Census instrument `scripts/research/sweep_kyle_drift_census.py` (frozen §1.1 predicate exact; JC-10 ISO-warm; warm-drop; JC-1 REPORTS incl. >1% residual flag; integrity pin vs prior census `n_events`/`n_quotes`/`n_trades`) + helper unit tests (no cache) + `docs/prompts/README.md` research_validation scripts-row ownership. |
| 3 | `8b8932f` | Harness IC row in `scripts/sensor_feature_ic.py` — H10 SFI-stratified extreme / interior / `sfi_contrast` at h=900; OLN §2.4 evidence-only hooks; additive only; synthetic smoke tests in `tests/scripts/test_sensor_feature_ic.py`. |

### Gate battery (each commit independently green; PYTHONHASHSEED=0)

| gate | commit 1 | commit 2 | commit 3 |
|---|---|---|---|
| `pytest -m "not functional and not slow"` | 4076 passed, 9 skipped | 4081 passed, 9 skipped | 4083 passed, 9 skipped |
| `mypy src/feelies` (strict) | clean (194 files) | clean (194 files) | clean (194 files) |
| `ruff check src/ tests/` (+ scripts touched) | clean | clean | clean |
| coverage on new sensor module | **98%** (≥ 80% bar) | n/a (script) | n/a (script) |
| `tests/docs/test_prompt_coverage_map.py` | green | green (scripts row) | green |

### Coverage-map ownership rows

| artifact | owner |
|---|---|
| `src/feelies/sensors/impl/sweep_flow_imbalance.py` | `audit_sensor` (package-wholly-owned; no `_FILE_OWNERS` entry required) |
| `scripts/research/sweep_kyle_drift_census.py` | `research_validation` (`docs/prompts/README.md` scripts row) |
| `scripts/sensor_feature_ic.py` (H10 row additive) | `sensor` (pre-existing scripts-row owner; unchanged) |

### Explicit non-actions (binding)

- Census **not executed** against the 40-cell grid (instrument pinned only).
- No forward return / RankIC / CPCV / DSR / outcome statistic computed
  on cached L1.
- No Phase-B alpha YAML, bootstrap SFI factory wiring, or platform.yaml
  registration.
- Locked parity baselines / promotion ledger / core event schemas
  untouched.
- **N = 11** at close of Phase A (unchanged).

### P0-1 status after this amendment

| deliverable | status |
|---|---|
| (i) `sweep_flow_imbalance` v1.0.0 | **landed** (`faeafaa`) |
| (ii) census instrument | **committed** (`19adcfd`) — not run |
| (iii) harness IC row | **landed** (`8b8932f`) — not run on cache |

**Stop for Lei review before any census execution (step 1).**

*(Record appended 2026-07-15. Justification: Task 9-A-H10 Phase-A
close-out; instruments built and pinned; no freeze-body edit.)*

---

# CENSUS RESULTS — STEP 1 EXECUTED (Task 8-C-H10, 2026-07-16)

Execution record of the frozen §1 census. **Not an amendment** — no
test definition, threshold, or parameter above the freeze line
changed; the only header edit is the Status / FQ-3 provenance block
recording this execution. **No forward return, IC, or signal
evaluation was computed** — the only return-like quantity touched is
the unconditional session σ₉₀₀, per the frozen §1 authorization.
**N = 11** (census N-neutral).

## C.0 Instrument pin (task step 0; before grid contact)

Synthetic-fixture golden absent from Phase-A helper tests → added and
committed as `1e2cf24` **before** any cache contact:
`tests/scripts/test_sweep_kyle_drift_census.py` exercises
`run_cell_from_events` on a hand-computable RTH tape (n_in_window = 1
by session-window construction; n_iso = 45 ⇒ ≥ 20 warm SFI readings
after the sensor's own warm gate ⇒ exactly **1 LONG** episode;
n_iso = 5 / Class-B `(8,)` / `correction=10` ⇒ **0** episodes). Pin
green before grid.

## C.1 Preconditions at execution (§0 re-verified)

| # | check | result |
|---|---|---|
| P0-1 | Phase-A deliverables | green: sensor `faeafaa`, instrument `19adcfd`+pin `1e2cf24`, harness IC row `8b8932f` |
| P0-4 | determinism | `PYTHONHASHSEED=0`; direct `DiskEventCache` (`~/.feelies/cache`); real `SensorRegistry → HorizonScheduler → HorizonAggregator` stack; full-grid re-run **bit-identical** (SHA-256 match below) |
| P0-5 | protocol frozen before census | freeze `ec7eb5c` + A-1 `4e0db1a` + pin `1e2cf24` precede execution |
| integrity pin | vs H8 expanded census | overlapping (symbol, date) `n_events` / `n_quotes` / `n_trades` **match** (`integrity_pin.ok = true`) |

**FQ-3 provenance:** host `CHENGLEI-L-3` / `Windows-11-10.0.26200-SP0` /
Python 3.14.2; git SHA `1e2cf24`; worktree clean for tracked files
(`formal_spec.md` untracked sibling, freeze-allowed); artifact
`docs/research/artifacts/sweep_kyle_drift_census_2026-07-16.json`
SHA-256 `a2f49e6bb7e32e68c5b776a106b4b27d9aa1218a9e1ed5af5f8a3dffe5eb7829`
(primary run = re-run).

## C.2 Method

`scripts/research/sweep_kyle_drift_census.py` — frozen §1.1 predicate
exact (arms 1–6); JC-10 ISO-warm = SFI-warm share of in-window
boundaries; warm-drop < 0.5 on > 2 sessions; primary count =
filter-clean §1.1 (JC-1 no-double-exclusion, multiplier 1.0); σ₉₀₀ =
Bessel-corrected std of non-overlapping 900 s mid log-returns on the
09:30-anchored grid (bps); floors APP 4.68 / 29.62 and RMBS 5.51 /
34.87 (κ = 0.158); short rider APP 5.82 / 36.84, RMBS 6.60 / 41.77.
OLN × 10 preamble evidence-only (zero episodes by construction).

## C.3 JC-1 REPORTS — residual flag investigation (BEFORE verdict)

**Trigger fired:** `any_residual_bug_flag = true` on **40/40**
{APP, RMBS} cells with episodes (residual mean share ≈ **0.62–0.80**).

**Investigation (closed — not a sensor bug):** the instrument's
`residual_non_a_share` is the share of *all* trailing-900 s tape prints
that fail Class-A ∩ id-14 + correction drop — i.e. ≈ 1 − ISO-eligible
share on a mixed tape. That quantity is large by construction on real
L1 (ISO is a minority). The sensor **does not ingest** those prints
(filter goldens + pin confirm exclusion); co-travel on the tape is
expected hygiene context, not ingestion leakage. The protocol's
"near-zero by construction" reading matches *state* leakage, which
this estimand does not measure. Per §1.3 / JC-1: diagnostic only —
**never a park, never a power deflator**. No sensor-code change;
estimand clarification deferred to Lei if a tighter leakage probe is
wanted later (would be a new diagnostic, not a freeze edit).

**Class-B intensity (2.0× count-basis, non-binding):** APP **4** /
RMBS **4** eligible boundaries flagged; reported for mixture
θ₂/θ₃ adjudication only.

## C.4 ISO-warm (JC-10) — ASSERTED 0.95 vs measured

| symbol | ASSERTED prior | measured mean [min–max] | sessions with warm < 0.5 | warm-drop fired? |
|---|---|---|---|---|
| APP | 0.95 | **1.000** [1.000–1.000] | 0 / 20 | no |
| RMBS | 0.95 | **1.000** [1.000–1.000] | 0 / 20 | no |

Measured warm **replaces** the ASSERTED 0.95 for power scoring; both
recorded. Coverage drop rule did not fire.

## C.5 Per-symbol roll-up (κ = 0.158; primary = §1.1)

| symbol | σ₉₀₀ min L/S (bps) | viable_long cells | viable_short cells | episodes (all) | viable-region episodes (L/S split of all) | elev-A / elev-B / calm (all cells) | ≥ 100 viable? |
|---|---|---|---|---|---|---|---|
| APP | 29.62 / 36.84 | **18 / 20** | 17 / 20 | 107 (58 L / 49 S) | **94** | 24 / 29 / 54 | YES (94) alone under pool rule |
| RMBS | 34.87 / 41.77 | **16 / 20** | 15 / 20 | 72 (39 L / 33 S) | **58** | 11 / 23 / 38 | no alone; pool carries |
| OLN | — | — | — | 0 (evidence-only) | — | — | never in D |

Pooled viable-region primary episodes across D: **152 ≥ 100**.

**HOLIDAY-THIN (2025-12-26, 2025-12-30; never excluded):** APP HT
episodes = 13 (both HT cells are the only APP non-viable-σ sessions:
σ = 21.50 / 26.42); RMBS HT = 8 (2025-12-26 non-viable; 2025-12-30
viable). Tags reported; counts include them.

**Benign / gate occupancy (predicate = gate ON):** in-window
boundaries = 25 × 20 = 500 per symbol. APP gate_on = 107 (occupancy
0.214), gate_off = 393; RMBS gate_on = 72 (0.144), gate_off = 428.
Elevated strata denser than calm on a per-cell basis; A and B reported
separately (L4), never pooled for conclusions.

**SELL-leg / long-only:** RMBS clears short σ min on 15/20 sessions;
short episodes remain in the two-sided claim at census — **no** §1.6
long-only restatement forced by σ arithmetic alone (measured short
edge awaits step 2).

## C.6 Park-condition scoring (§1.5 / §1.6 / §9; no discretion)

1. **Edge-region emptiness: FALSE.** Both APP and RMBS have
   non-empty viable-region primary episodes (94 / 58).
2. **Power floor (pooled ≥ 100 contamination-excluded): PASS.**
   Pooled = **152**. Axis-split not required (neither symbol failed
   deployability).
3. **Warm-drop: FALSE** for both symbols.
4. **D = {APP, RMBS}.** OLN never in D.

**VERDICT: PROCEED — D = {APP, RMBS}.**

(Census instrument string `PROCEED_CENSUS`; mapped to the frozen §9
verdict line above.)

## C.7 Per-cell table (grid symbols; full JSON in artifact)

Columns: σ₉₀₀ (bps); viaL/viaS; eps / L / S; SFI warm; residual mean;
Class-B intensity excl.; gate ON/OFF; in-window (always 25).

| sym | date | stratum | σ₉₀₀ | viaL | viaS | eps | L | S | warm | resid | B-int | gON | gOFF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APP | 2025-11-25 | elev-A | 41.30 | Y | Y | 5 | 4 | 1 | 1.00 | 0.756 | 1 | 5 | 20 |
| APP | 2025-12-04 | elev-A | 63.10 | Y | Y | 5 | 4 | 1 | 1.00 | 0.702 | 1 | 5 | 20 |
| APP | 2025-12-01 | elev-A | 58.87 | Y | Y | 9 | 5 | 4 | 1.00 | 0.735 | 0 | 9 | 16 |
| APP | 2025-12-02 | elev-A | 58.33 | Y | Y | 5 | 3 | 2 | 1.00 | 0.696 | 0 | 5 | 20 |
| APP | 2025-12-22 | calm | 32.87 | Y | n | 5 | 1 | 4 | 1.00 | 0.763 | 0 | 5 | 20 |
| APP | 2026-01-05 | calm | 40.70 | Y | Y | 8 | 3 | 5 | 1.00 | 0.726 | 0 | 8 | 17 |
| APP | 2026-01-15 | calm | 46.45 | Y | Y | 2 | 1 | 1 | 1.00 | 0.701 | 2 | 2 | 23 |
| APP | 2026-01-26 | calm | 50.57 | Y | Y | 6 | 2 | 4 | 1.00 | 0.726 | 0 | 6 | 19 |
| APP | 2026-01-27 | calm | 59.03 | Y | Y | 2 | 1 | 1 | 1.00 | 0.786 | 0 | 2 | 23 |
| APP | 2025-12-26 | calm HT | 21.50 | n | n | 6 | 4 | 2 | 1.00 | 0.708 | 0 | 6 | 19 |
| APP | 2025-12-30 | calm HT | 26.42 | n | n | 7 | 6 | 1 | 1.00 | 0.682 | 0 | 7 | 18 |
| APP | 2026-01-12 | calm | 69.76 | Y | Y | 7 | 4 | 3 | 1.00 | 0.700 | 0 | 7 | 18 |
| APP | 2026-01-20 | calm | 73.04 | Y | Y | 5 | 3 | 2 | 1.00 | 0.728 | 0 | 5 | 20 |
| APP | 2026-01-22 | calm | 45.61 | Y | Y | 6 | 2 | 4 | 1.00 | 0.755 | 0 | 6 | 19 |
| APP | 2026-04-01 | elev-B | 40.72 | Y | Y | 6 | 4 | 2 | 1.00 | 0.721 | 0 | 6 | 19 |
| APP | 2026-04-10 | elev-B | 43.67 | Y | Y | 6 | 3 | 3 | 1.00 | 0.724 | 0 | 6 | 19 |
| APP | 2026-04-22 | elev-B | 41.01 | Y | Y | 4 | 2 | 2 | 1.00 | 0.803 | 0 | 4 | 21 |
| APP | 2026-04-02 | elev-B | 77.53 | Y | Y | 4 | 2 | 2 | 1.00 | 0.777 | 0 | 4 | 21 |
| APP | 2026-04-07 | elev-B | 55.54 | Y | Y | 6 | 3 | 3 | 1.00 | 0.753 | 0 | 6 | 19 |
| APP | 2026-04-16 | elev-B | 49.00 | Y | Y | 3 | 1 | 2 | 1.00 | 0.724 | 0 | 3 | 22 |
| RMBS | 2025-11-25 | elev-A | 51.11 | Y | Y | 4 | 2 | 2 | 1.00 | 0.746 | 0 | 4 | 21 |
| RMBS | 2025-12-04 | elev-A | 49.71 | Y | Y | 2 | 2 | 0 | 1.00 | 0.722 | 0 | 2 | 23 |
| RMBS | 2025-12-01 | elev-A | 41.01 | Y | n | 2 | 2 | 0 | 1.00 | 0.699 | 0 | 2 | 23 |
| RMBS | 2025-12-02 | elev-A | 43.76 | Y | Y | 3 | 3 | 0 | 1.00 | 0.713 | 0 | 3 | 22 |
| RMBS | 2025-12-22 | calm | 31.05 | n | n | 4 | 0 | 4 | 1.00 | 0.801 | 0 | 4 | 21 |
| RMBS | 2026-01-05 | calm | 53.36 | Y | Y | 4 | 3 | 1 | 1.00 | 0.675 | 0 | 4 | 21 |
| RMBS | 2026-01-15 | calm | 67.33 | Y | Y | 5 | 2 | 3 | 1.00 | 0.704 | 0 | 5 | 20 |
| RMBS | 2026-01-26 | calm | 43.96 | Y | Y | 2 | 1 | 1 | 1.00 | 0.726 | 0 | 2 | 23 |
| RMBS | 2026-01-27 | calm | 43.74 | Y | Y | 3 | 0 | 3 | 1.00 | 0.735 | 0 | 3 | 22 |
| RMBS | 2025-12-26 | calm HT | 19.58 | n | n | 2 | 0 | 2 | 1.00 | 0.736 | 1 | 2 | 23 |
| RMBS | 2025-12-30 | calm HT | 46.13 | Y | Y | 6 | 5 | 1 | 1.00 | 0.722 | 0 | 6 | 19 |
| RMBS | 2026-01-12 | calm | 32.87 | n | n | 6 | 3 | 3 | 1.00 | 0.788 | 0 | 6 | 19 |
| RMBS | 2026-01-20 | calm | 75.90 | Y | Y | 3 | 1 | 2 | 1.00 | 0.666 | 0 | 3 | 22 |
| RMBS | 2026-01-22 | calm | 49.45 | Y | Y | 3 | 3 | 0 | 1.00 | 0.723 | 1 | 3 | 22 |
| RMBS | 2026-04-01 | elev-B | 46.93 | Y | Y | 6 | 2 | 4 | 1.00 | 0.750 | 0 | 6 | 19 |
| RMBS | 2026-04-10 | elev-B | 47.65 | Y | Y | 1 | 1 | 0 | 1.00 | 0.711 | 0 | 1 | 24 |
| RMBS | 2026-04-22 | elev-B | 61.29 | Y | Y | 5 | 3 | 2 | 1.00 | 0.651 | 1 | 5 | 20 |
| RMBS | 2026-04-02 | elev-B | 81.94 | Y | Y | 3 | 1 | 2 | 1.00 | 0.729 | 0 | 3 | 22 |
| RMBS | 2026-04-07 | elev-B | 56.04 | Y | Y | 6 | 4 | 2 | 1.00 | 0.728 | 1 | 6 | 19 |
| RMBS | 2026-04-16 | elev-B | 33.82 | n | n | 2 | 1 | 1 | 1.00 | 0.623 | 0 | 2 | 23 |

Every grid cell emitted 26 RTH h=900 boundaries, **25** in the
09:35–15:50 window. OLN × 10 preamble: episodes = 0 by construction.

## C.8 Stop

§0 order lock: **stop for Lei review** before Phase B or any step-2
action. No IC / forward return / YAML / bootstrap factory work in this
task. **N = 11** unchanged.

*(Record appended 2026-07-16. Justification: Task 8-C-H10 step-1
execution; frozen bars scored without discretion.)*

---

## A-2 — JC-1 REPORTS estimand clarification (Task 11-A-H10 housekeeping, 2026-07-16)

**Scope.** Append-only clarification of the §1.3 / JC-1 REPORTS
definition. **No threshold, park bar, predicate, or freeze-body text
changed.** Recorded **before any step-2 statistic** (task step 0).

**Census finding that forced the clarification (C.3):** the instrument
flagged `residual_non_a_share > 1 %` on 40/40 {APP, RMBS} cells with
episodes (mean share ≈ 0.62–0.80). Investigation closed: not a sensor
bug — the measured quantity is tape co-travel, not state leakage.

**Two estimands (distinguished; never conflated):**

| estimand | definition | expected on real L1 | JC-1 >1 % investigation trigger |
|---|---|---|---|
| **Sensor-state leakage** | share of prints that *enter* SFI sensor state despite failing Class-A ∩ id-14 + correction drop | **0 by construction** (filter goldens + census synthetic pin); golden-pinned | **YES — attaches here only** |
| **Tape co-travel share** | share of *all* trailing-900 s tape prints that fail the same filter (ISO is a minority on mixed L1) | **natural, large** (census observed ≈ 62–80 %) | **NO** — composition diagnostic only; never a park, never a power deflator |

**Resolution recorded:** the census investigation resolved the
conflation correctly. The Phase-A instrument's `residual_non_a_share`
field measures the **tape co-travel** estimand; the protocol's
"near-zero by construction" / >1 % investigation wording in §1.3 /
JC-1 attaches to the **leakage** estimand only. No sensor-code
change; no freeze-body edit; no new diagnostic required for step 2.

*(Amendment appended 2026-07-16 before step-2 outcome contact.
Justification: Task 11-A-H10 housekeeping item 0.)*

---

# STATISTICAL RESULTS — STEPS 2a/2b EXECUTED, FIRST FAIL AT 2b (Task 11-A-H10, 2026-07-16)

Execution record of protocol step 2 under Ordering B (slate-C
SEQUENCING RULING: harness extraction path; Phase B YAML gated on
PASS). Locked order; each criterion scored against its pre-registered
number; STOP at first failing stage with the §9 consequence. **The
run stopped inside step 2b.** Steps 2.3, JC-5, 2.4, and 3–8 were
**NOT COMPUTED**. A-2 (JC-1 REPORTS estimand clarification) was
recorded before any statistic.

**N = 12** — first outcome contact on the H10 primary (11 → 12).

## S.1 Preconditions

| # | check | result |
|---|---|---|
| worktree | clean tracked tree at start | yes at `2c45b6f` (census PROCEED); `formal_spec.md` untracked sibling (freeze-allowed) |
| seed | `PYTHONHASHSEED=0` | set for every scripted run and pytest |
| A-2 housekeeping | JC-1 REPORTS estimand split | appended before any statistic |
| P0-1 | Phase-A instruments | green (sensor / census / harness IC row) |
| P0-4 | determinism | extract re-run bit-identical; stats re-run bit-identical |
| stage 0 | census pin | **50/50 cells exact**; viable-region episodes APP 94 / RMBS 58 / pooled **152** |

## S.2 Instruments (Ordering B)

| artifact | role |
|---|---|
| `tests/research/test_gas_sweep_kyle_drift_sign.py` | §2.1 harness sign-goldens (extraction / census-pinned predicate; no YAML `evaluate`) |
| `scripts/research/sweep_kyle_drift_validation_extract.py` | boundary extract; imports census for all constants / predicate; +`kyle_lambda_60s` F2 diagnostic |
| `scripts/research/sweep_kyle_drift_validation_stats.py` | stage 0 → 2b → (2.3 / JC-5 on PASS only); first-FAIL stop |

Binding conventions: IC pair x = `sweep_flow_imbalance`, y = signed
forward 900 s mid log-return; evidence set = census §1.1 eligible
episodes on `viable_long` sessions, pooled {APP ∪ RMBS}; zero-move
fwd = 0.0 (valid pair); end-of-session pairs without a realised 900 s
endpoint dropped from the IC sample (disclosed: episode n = 152,
IC-pair n = 144 — both ≥ 100).

## S.3 Step 2a — harness sign-golden — **PASS**

```
PYTHONHASHSEED=0 uv run pytest tests/research/test_gas_sweep_kyle_drift_sign.py
→ 7 passed
```

| # | assertion (Ordering-B harness equivalent of §2.1) | result |
|---|---|---|
| 1 | Informed-continuation LONG (buy ISO ⇒ SFI>0, pctl≥0.90 ⇒ LONG arm) | PASS |
| 2 | Mirror SHORT | PASS |
| 3 | Interior-null (alternating ISO ⇒ interior pctl ⇒ no entry) | PASS |
| 4 | Filter-exclusion (Class-B / non-id-14 ⇒ no SFI warm / no entry) | PASS |
| 5 | Warm-gate (<20 eligible ISO ⇒ suppressed) | PASS |
| 6 | Sign-disagreement predicate reject | PASS |
| 7 | h=900 key-presence (ENTRY_WARM_IDS) | PASS |

**Step 2a: PASS.** (Full loader-compiled `evaluate` goldens remain a
Phase-B proof obligation — not reached; Phase B gated on step-2 PASS.)

## S.4 Step 2b — RankIC gate (census boundary set n = 152) — **FAIL**

Pooled {APP ∪ RMBS}, viable-region primary eligible episodes, h = 900:

| quantity | value |
|---|---|
| episode n (census pin) | **152** (APP 94 / RMBS 58) |
| IC-pair n (fwd realised) | **144** (8 end-session drops) |
| extreme-SFI RankIC | **+0.0893** |
| Fisher-z two-sided p | **0.288** |
| interior RankIC (n=517) | +0.0306 (p 0.487) |
| extreme − interior contrast | **+0.0586** |
| interior continuation-signed mean | +0.53 bps (SE 2.43, t 0.22 — not sig positive) |
| F2 kyle_lambda_60s_pctl contrast (elev − base) | **−0.014** (not material) |
| F2 print-volume contrast | **−19,407** (not material; both F2 arms absent) |
| bucket top−bottom edge | **+10.52 bps** |
| conditional tail mean / t | **+2.86 bps / t = 0.82** |

**Per-criterion scoring (§2.2; each vs pre-registered bar):**

| criterion | bar | observed | n-class | verdict |
|---|---|---|---|---|
| extreme-SFI pooled RankIC sign | > 0 | +0.0893 | n-invariant | **PASS** |
| extreme-SFI pooled \|RankIC\| | ≥ 0.03 | 0.0893 | n-invariant | **PASS** |
| extreme-SFI pooled Fisher-z p | ≤ 0.01 | 0.288 | n-variant | **FAIL** |
| pooled sample minimum | n ≥ 100 | 152 (IC-pair 144) | n-variant | **PASS** |
| interior contrast | contrast > 0 AND interior not sig-positive | +0.0586; interior t 0.22 | n-invariant | **PASS** |
| F2 λ / volume co-travel | ≥ 1 material positive contrast | both absent / negative | mechanism | **FAIL** |
| per-symbol diagnostics | reported (non-governing) | APP +0.083 (n=89, p=0.44); RMBS +0.226 (n=55, p=0.097) | diagnostic | **PASS** (reported) |
| bucket monotonicity | top−bottom > 0 | +10.52 bps | n-invariant | **PASS** |
| conditional tail | mean > 0 with t ≥ 2 | +2.86 bps, **t 0.82** | sign n-inv; t n-var | **FAIL** |

**Verdict: step 2b FAILS.** Three conjuncts fire: Fisher-z p, F2
co-travel, conditional-tail t. Magnitude and sign of RankIC clear
their bars; the claimed strength / attribution / tail do not.

**Honest characterization (no re-litigation):** a weak positive
continuation RankIC exists in-sample (+0.089) with a favourable
interior contrast and bucket spread, but it is indistinguishable from
zero at the pre-registered p ≤ 0.01 bar, the F2 informed-flow
fingerprint (λ / volume elevation at extremes) is **absent**
(contrasts negative), and the conditional-tail t-stat (0.82) misses
t ≥ 2. The conjunctive gate rejects exactly this configuration.

## S.5 Status consequence (§9) — STOP

**§9 row "2b IC gate" → REJECTED (F1/F2 dead).** Precedence:

- F2 fail ∩ RankIC magnitude/sign PASS → **REJECTED (F2)** (§9.1) —
  mechanism attribution dead despite pooled drift sign.
- Fisher-z p FAIL and tail-t FAIL reinforce the same §9 row 2b
  REJECTED (conjunctive). Magnitude-class bars themselves PASSED;
  the rejection is not a \|RankIC\| < 0.03 kill.
- JC-5 **not applied** (acts only on a primary 2b PASS). Per-symbol
  signs were both continuation-positive (diagnostic only here).
- Steps 2.3 / 2.4 / 3–8 **not executed** (first-FAIL stop).

No tuning. No variant evaluation. Phase B remains gated — **not
authorized**.

Doc Status: **FAILED STEP 2b — REJECTED (§9 row "2b IC gate") —
AWAITING LEI REVIEW** (slate-C sequencing: Phase B does not open).

## S.6 Trial ledger

**N = 12.** N = 11 at census close; this step-2 execution is the H10
primary's **first outcome contact** → +1. Zero exploratory variants
evaluated (one extract, one scoring pass, frozen thresholds). Spec
§13 drafted-not-evaluated rows remain N-impact 0 unless Lei
authorizes (+1 N each). Living ledger updated in
`prompt_pack_09_hypothesis_slate_c.md` §(3) appendix below.

## S.7 Provenance (FQ-3)

    git_sha: "2c45b6ff0fdbc02639ac74af093270f739ee56bd"
      (HEAD at evidence start = census PROCEED commit; instruments
      and this record committed with the Task 11-A-H10 close-out)
    worktree_clean: "tracked tree clean at start; formal_spec.md
      untracked sibling (freeze-allowed)"
    pythonhashseed: "0"
    host_fingerprint:
      os: "Windows-11-10.0.26200-SP0"
      host: "CHENGLEI-L-3"
      python_build: "3.14.2 (MSC v.1944 64 bit AMD64)"
    commands:
      2a: "PYTHONHASHSEED=0 uv run pytest
        tests/research/test_gas_sweep_kyle_drift_sign.py → 7 passed"
      extract: "PYTHONHASHSEED=0 uv run python
        scripts/research/sweep_kyle_drift_validation_extract.py
        --json docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/
        boundaries_extract_2026-07-16.json"
      stats: "PYTHONHASHSEED=0 uv run python
        scripts/research/sweep_kyle_drift_validation_stats.py
        --extract <above>
        --census docs/research/artifacts/sweep_kyle_drift_census_2026-07-16.json
        --json docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/
        validation_stats_2026-07-16.json"
    artifacts (docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/):
      boundaries_extract_2026-07-16.json
        sha256=522e0ff14c1986a6099ba7a9523f9a4b488b9730ab3d1ba09d4458da6d8f0c25
        (re-run bit-identical)
      validation_stats_2026-07-16.json
        sha256=4735b20a937ba7382f4108b29138d365892616f10824ce856bce18e7ff9cd9ea
        (re-run bit-identical)
    census_pin: "sweep_kyle_drift_census_2026-07-16.json
      sha256=a2f49e6bb7e32e68c5b776a106b4b27d9aa1218a9e1ed5af5f8a3dffe5eb7829
      — stage 0 50/50 exact; pooled viable episodes 152"
    ownership:
      scripts/research/sweep_kyle_drift_validation_extract.py
        → research_validation (docs/prompts/README.md scripts row)
      scripts/research/sweep_kyle_drift_validation_stats.py
        → research_validation (same)
      tests/research/test_gas_sweep_kyle_drift_sign.py
        → research_validation / microstructure-alpha (gas convention)

*Task 11-A-H10 stops here per the first-FAIL rule. Phase B is not
authorized. Lei reviews the REJECTED verdict and whether any
spec §13 variant (+1 N each) is authorized before anything else runs.*

## S.8 ADJUDICATION (Lei, 2026-07-16) — REJECTED per frozen §9 row 2b, ratified

**Ruling: REJECTED** under frozen §9 row **"2b IC gate"**. The
Task 11-A-H10 S.5 first-FAIL stop stands; this adjudication ratifies
it and records the failure decomposition precisely. Phase B remains
**not authorized**. No post-outcome threshold, pool, or parameter
change is permitted within this trial.

### Failure decomposition (binding for all downstream citations)

| axis | frozen bar | observed | class | verdict |
|---|---|---|---|---|
| **Magnitude** | \|RankIC\| ≥ 0.03 (sign > 0) | **+0.0893** (≥ 0.03; ~**5×** H8's H=300 primary realization 0.0186) | n-invariant | **PASSED** |
| **Significance** | Fisher-z two-sided p ≤ 0.01 | **p = 0.288** (IC-pair n = 144) | n-variant | **FAILED** |
| **F2 mechanism tie** | λ-percentile elevation OR same-direction print-volume elevation among primary eligible episodes (at least one material positive contrast) | λ pctl contrast **−0.014**; volume contrast **−19,407** — both absent / wrong-signed | mechanism | **FAILED** |

**Significance — no legal rescue.** At the realized RankIC ≈ +0.089,
Fisher-z p ≤ 0.01 requires **n ≈ 680** IC pairs versus the **144**
realized on the frozen evidence pool. The evidence set was closed
pre-outcome ({APP, RMBS} × 20-session 03c grid; DISPOSITIONS 4 /
protocol §0). **Post-outcome widening of the pool is prohibited.**
An n-variant miss that cannot be cured inside the frozen program is
not convertible into a park by acquiring unauthorized sessions.

**F2 — governing substance of the rejection.** Sweep-conditioned
windows show **no** `kyle_lambda_60s` elevation and **no**
same-direction volume co-travel versus baseline. The KYLE
attribution (informed-flow via the impact / aggression fingerprint
at the extreme-SFI stratum) is **refuted in-sample**. Magnitude
clearing its floor without the mechanism tie is exactly the
configuration §9.1 F2∩RankIC-PASS maps to **REJECTED (F2)** —
mechanism attribution dead despite pooled drift sign. Conditional-
tail t = 0.82 < 2 (also failed in S.4) reinforces the same §9 row
2b REJECTED and does not alter the decomposition above.

**What is rejected (scope precision).** The extreme-SFI
continuation claim at **H = 900, passive, pooled {APP, RMBS}**,
under the certified-ISO conditioner, with KYLE attribution via F2
— on this frozen evidence set. The RankIC magnitude bar itself did
**not** kill the card; significance and F2 did. No claim that
"|RankIC| failed" may cite this record. No claim that more grid
sessions inside an unfrozen expansion would have rescued the trial
is admissible without a **new** trial (+1 N) and its own protocol
from step 1.

**Consequences.** Doc Status: **REJECTED** (close-out record:
`sig_sweep_kyle_drift_h900_v1_result.md`; slate-C DISPOSITIONS
appended). Steps 2.3, JC-5, 2.4, and 3–8 were never executed — no
measured-edge, CPCV, stratification, DSR, drift, execution, or
sensitivity statistic exists for this candidate, and none may be
quoted. Trial ledger **N = 12 confirmed** (S.6 accounting adopted).
No spec §13 variant is authorized by this ruling — any future
evaluation of one is a new trial (+1 N) requiring its own protocol
from step 1. Per-symbol RMBS RankIC +0.226 and the H=300→H=900
magnitude comparison are recorded as post-hoc, outcome-contaminated
observations in the result doc only — zero evidential weight.
