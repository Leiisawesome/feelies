<!--
  File:   docs/research/sig_sweep_kyle_drift_h900_v1_validation_protocol.md
  Status: PRE-REGISTERED — FROZEN (Task 8-F-H10 rulings, Lei,
          2026-07-15: JC-1/2/3/4/6/7/8/9/10 APPROVED as proposed or
          amended; JC-5 RULED modified — no step-2 magnitude
          safeguard PLUS per-symbol SIGN-CONSISTENCY D-membership
          condition; Amendment-C pre-ruling stands). Written BEFORE
          any implementation exists and BEFORE any outcome statistic
          was computed for this candidate. From this freeze commit,
          changes go ONLY in an appended AMENDMENTS section with
          timestamp and justification. No forward return, IC, or
          outcome statistic was computed in producing this file.
          N = 11 (unchanged; no outcome contact).
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8, Phase B (H10).

  Provenance (FQ-3 template):
    git_sha: "decd9170b82e9832800583b97517808a125add31" (HEAD at
      Task-8 authoring; freeze commit supersedes)
    worktree_clean: "research outputs: formal_spec may remain
      untracked sibling; this file is the freeze write"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (protocol authoring / freeze only; zero data contact)"
    normative_inputs (Amendment A — structural template):
      sig_inventory_fade_v1_validation_protocol.md (H2 frozen —
        STRUCTURAL TEMPLATE; §11 8-F rulings carried),
      sig_dislocation_lambda_drift_v1_validation_protocol.md (H8
        frozen incl. all 8-F and A-1/A-2 rulings — STRUCTURAL
        TEMPLATE; locked order, single-stress anchor, conjunctive-IC
        rationale, CPCV dual reporting, 27-vertex+stress sensitivity
        pass set, ±5% numericization, latency axis),
      sig_sweep_kyle_drift_h900_v1_formal_spec.md (H10 Task-7 spec
        §1–§16; consequence-precedence sketch §4.3; Phase-A map §15;
        Amendments A–F on the spec),
      prompt_pack_09_hypothesis_slate_c.md (H10 card VERBATIM +
        DISPOSITIONS; trial ledger N = 11),
      prompt_pack_09a_slate_c_review.md (DECISION RECORD),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2;
        20-session {APP,RMBS} grid; L1–L5; HOLIDAY-THIN),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.3/§4.4),
      prompt_pack_00b_edge_units_convention.md,
      prompt_pack_00c_eval_canon.md (pinned realism profile at commit
        825a7bc3bda48d3a819fed0a498dbf9d65e711c4),
      prompt_pack_12p_router_fill_timing_parity.md (Task 12-P AXIS-1
        VERIFIED — hard gate cited, not re-run),
      docs/research/gas_01_integrated_ofi.md / gas_02 (ENG-3
        sign-golden + IC-gate precedent),
      .cursor/skills/microstructure-alpha/research-protocol.md
        (Phase 3 stratification, ~100-obs rule, Phase 5 IC(t) fit),
      src/feelies/research/{cpcv.py, dsr.py, forward_ic.py},
      src/feelies/alpha/promotion_evidence.py (GateThresholds),
      src/feelies/forensics/cost_survival.py (verdict vocabulary),
      scripts/{sensor_feature_ic.py, regime_diagnostics.py},
      src/feelies/harness/backtest_cli.py (--inv12-stress)
      (all read this session; citations inline).
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

*(none yet — section reserved for post-freeze entries only)*
