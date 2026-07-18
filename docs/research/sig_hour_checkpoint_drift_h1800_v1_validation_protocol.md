<!--
  File:   docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md
  Status: PRE-REGISTERED — FROZEN (Task 8-F-H13, Lei, 2026-07-17).
          Amendments-only below the freeze line. Double expectation
          frozen: in-window ≈96 / F2 arm ≈96 — expected PARK (power)
          and expected F2-INSUFFICIENT; census runs as measurement.
          CPCV session-count defect fixed at freeze (D-C2).
          N = 12; zero outcome contact. H13 = final card (stop-rule).
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8 / Task 8-F-H13 (H13).

  Provenance (FQ-3 — freeze commit; no instruments run):
    git_sha: "Task 8-F-H13 freeze commit (this file)"
    worktree_clean: "yes for tracked tree at freeze"
    pythonhashseed: "0 — arithmetic from committed artifacts /
      frozen specs; no cache contact; no IC"
    normative_inputs:
      sig_hour_checkpoint_drift_h1800_v1_formal_spec.md
        (Amendments A–H + Appendix P RULING Lei 2026-07-17),
      four frozen protocols (inventory_fade, dislocation_lambda,
        sweep_kyle_h900, halfhour_clock_h900) — structural template,
      prompt_pack_03_data_contract.md,
      prompt_pack_03c_universe_and_cache.md (through A2 / Tranche-1B),
      prompt_pack_00c_eval_canon.md (realism profile pin),
      prompt_pack_12p_router_fill_timing_parity.md (AXIS-1 VERIFIED),
      research/cpcv.py, research/dsr.py, promotion_evidence.GateThresholds,
      gas_01_integrated_ofi.md (ENG-3 sign-golden + RankIC precedent),
      Task 8-F-H13 rulings (Lei, 2026-07-17) — all twelve JCs + CPCV
        session-count freeze correction (D-C2).
-->

# `sig_hour_checkpoint_drift_h1800_v1` — pre-registered validation protocol (Task 8)

This protocol fixes, numerically and in execution order, every test the
candidate must pass — **before** any implementation exists and before
any outcome statistic is computed. It binds Task 8 (measurement),
Task 9 / Phase B (implementation), and the Task-12-gated execution
overlay. The four frozen protocols (inventory_fade, dislocation_lambda,
sweep_kyle_h900, halfhour_clock_h900 — incl. all rulings) are the
**structural template** (task Amendment A): locked order, single-stress
anchor, conjunctive-IC rationale, CPCV dual reporting, 27-vertex+stress
sensitivity pass set, ±5 % reconciliation numericization, latency axis,
n-invariant/n-variant labels on every criterion, and a precedence walk
with zero undefined intersections. **Only what H13 changes is
re-derived** (embargo / annualization / CPCV bar arithmetic at h=1800
§3; eight-symbol evidence-pool census §1; F2 hour-vs-:30 two-arm
machinery §2; hour-subset calendar derivation) — arithmetic shown
inline.

**Freeze rule.** This file is **PRE-REGISTERED — FROZEN** as of the
Task 8-F-H13 commit (2026-07-17). It is immutable except for an
appended `AMENDMENTS` section (timestamp + justification per entry).
Converting any FAIL below by tuning is prohibited: **any post-hoc
parameter change is a new trial — N increments and the change is
logged in the ledger (§10) before the re-run.** Simulator-knob
perturbations inside the pre-registered §8 grid do not increment N
(the grid's pass criterion is conjunctive — it can only reject); any
change to alpha-side parameters (`ofi_percentile_min`,
`edge_scale_bps` outside the §3 calibration procedure, `edge_cap_bps`,
gate thresholds, exit ages, session constants, calendar lead/ε /
hour-subset rule, quintile split, `w_hr` used as a tuned occupancy)
does.

**Two validity axes, never conflated (session constraint 5).** Steps
1–6 establish *statistical* validity on pre-cost / disclosure-
arithmetic quantities; steps 7–8 establish *execution* validity on the
Task-12-parity-cleared machinery. No number from steps 1–6 is ever
presented as an economic result, and no number produced before the
Task-12 router timing-parity check is presented as a result at all.

**Stop-rule accounting (§0 / pack-11 DISPOSITIONS 8 — binding).** H13
is the **final card** on this universe/grid. Death at **any** gate
(census power, form/calendar, step-2b magnitude / significance / F2,
or later) **closes the program**. A step-2b PASS (primary ∧ F2-BINDING)
is the sole remaining path that satisfies the cycle-3 stop-rule.

**Evidence set — POOL CONFIGURATION (B) FROZEN (Appendix P §P.4 /
task Amendment B).**

| role | symbols | sessions | cells |
|---|---|---|---|
| **Deployable (D)** | {APP, RMBS, OLN, DIOD, PCTY, CROX} | 20 each (03c preamble + expansion) | **120** |
| **Evidence-only** | {ENSG, MLI} | **10** cached originals each (expansion DRAWN-NOT-INGESTED) | **20** |
| **Step-2 evidence pool** | D ∪ {ENSG, MLI} | as above | **140** ingested admissible |

**CPCV session-count (D-C2 — freeze correction, §3):** `n_groups` =
that symbol's CPCV session count (one group per session) — APP/RMBS
**20**; {OLN, DIOD, PCTY, CROX} **10** (preamble grid for CPCV
paths). Pre-freeze draft incorrectly assumed uniform 20/2 for every D
symbol. Census / RankIC / F2 evidence-pool cells remain Appendix P
(×20 for all six D).

**Never-promotable rule (§9 / §P.4):** ENSG/MLI remain evidence-only
under Lei's 0.16-class D-membership screen and the §P.1 κ geometry;
**never promotable post-hoc into D** (ENSG's ~1.8 % headroom at
κ_frozen is inside estimation noise). Configuration **(C) REJECTED**
— zero ingestion. Per-symbol episode counts are **always reported** so
the six-symbol D-only sub-answer is extractable from every census /
IC artifact without re-running.

**Sessions (named now, the closed set).**

- preamble elevated A: `2025-11-25, 2025-12-04`
- preamble calm: `2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26,
  2026-01-27`
- preamble elevated B: `2026-04-01, 2026-04-10, 2026-04-22`
- expansion elevated A: `2025-12-01, 2025-12-02`
- expansion calm: `2025-12-26, 2025-12-30, 2026-01-12, 2026-01-20,
  2026-01-22` (2025-12-26 / 2025-12-30 tagged HOLIDAY-THIN; tags
  never exclude)
- expansion elevated B: `2026-04-02, 2026-04-07, 2026-04-16`

D symbols use all 20 for census / RankIC / F2. ENSG/MLI use the **10
preamble dates only** (config (B); expansion cells stay
DRAWN-NOT-INGESTED). CPCV for {OLN, DIOD, PCTY, CROX} uses the
**preamble 10** only (D-C2 / §3). The 03c limitations L1–L5 attach
verbatim to every calm / elevated-A / elevated-B conclusion.

**Units (00b, THE CONVENTION).** Every edge and cost figure below is
**one-way, per-fill, in bps of fill notional** unless explicitly
marked round-trip-derived. **Single-stress anchor** (8-F §11.1 /
pack-08 — carried verbatim, NO stacking): Inv-12 1.5× applied once
into `floor = 2.25 × (2.0 + fee)`; never stacked with a simultaneously
stressed adverse-selection vertex.

**N = 12** at protocol write (pack-11 / spec §14; slate-D ledger; no
outcome contact). First outcome contact on the H13 primary →
**N ≥ 13**.

**Frozen double expectation (task Amendment C / §P.4(3) / Task
8-F-H13 — recorded in §1; binding disclosure, not a skip).**
Backlog-19-compliant κ-viable central under (B), geometry-symmetric
across arms:

| arm | κ-viable central | vs ≥ 100 | stated prior |
|---|---|---|---|
| in-window (primary / census power) | ≈ **96** | FAIL | **expected PARK (power)** |
| F2 :30 out-window | ≈ **96** | FAIL | **expected F2-INSUFFICIENT** |

The census **runs as measurement**. Projections **never rescue** a
measured miss and **never condemn** a measured clear — measured
counts govern both directions. A pass must surprise these priors; a
park on either arm closes the program cleanly (final card).

---

## 0. PRECONDITIONS (verified before step 1 executes)

| # | precondition | status at protocol write |
|---|---|---|
| P0-1 | Phase-A deliverables landed (Amendment H / spec §16) | **REQUIRED BEFORE step 1 or step 2 executes**: (i) hour-only calendar derivation from committed `ALGO_CLOCK` YAMLs for every operative D date (spec §1.5.2 — `:00` subset; `:30` excluded from injection view); (ii) `ofi_integrated_percentile` at h=1800 consumed (factory already multi-h — verify no silent h=900 substitution); (iii) census instrument committed (both arms; eight-symbol evidence pool); (iv) harness IC row landed on the census-pinned predicate (both F2 arms). Until then steps 1–2 are blocked. |
| P0-2 | Grid inputs CLEARED | 03c FQ-6A-R re-check; expansion AMENDMENT 1 ratified; Tranche-1B in D; ENSG/MLI ×10 cached; expansion DRAWN-NOT-INGESTED; (C) rejected |
| P0-3 | Realism profile pinned | 00c profile at commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`; configs with `backtest_fill_latency_ns == 0` are invalid for evidence |
| P0-4 | Determinism discipline | every scripted run: `PYTHONHASHSEED=0`, direct `DiskEventCache` read (`~/.feelies/cache`), replay through the real pipeline; provenance (git SHA, command line, artifact SHA-256) recorded per run; bit-identical re-run required for the census artifact; **hour-subset derivation determinism** verified as a census precondition (identical derived views / hashes on rerun — §1.1 / JC-10) |
| P0-5 | Step-1 census executes only after this file is FROZEN (post-§11 8-F rulings) and committed | **FROZEN 2026-07-17** (Task 8-F-H13); census still waits on P0-1 |
| P0-6 | Task-12 router timing-parity (steps 7–8 gate) | **AXIS-1 VERIFIED 2026-07-12** (`prompt_pack_12p_router_fill_timing_parity.md`; regression guards committed). Re-verified green at step-7 execution time; any AXIS-1 regression re-opens the gate. |

Execution order is **locked**: 1 → 2 → 3 → 4 → 5 → 6 → (7 → 8) with
steps 7–8 additionally gated on P0-6. A step does not begin until the
prior step's outputs are committed. A park/reject at any step halts
the sequence — and under the stop-rule **closes the program**.

---

## 1. STEP 1 — PARK-RULE CENSUS (spec §4.2–§4.5 / Appendix P / Amendments B–D)

Offline deterministic scan of the closed **140-cell** evidence-pool
grid (120 D + 20 ENSG/MLI). **NO forward returns are computed
anywhere in this step** — the only return-like quantity permitted is
the *unconditional* session volatility σ₁₈₀₀ (std of non-overlapping
1800 s mid log-returns over RTH, in bps), which conditions on nothing
signal-related.

### 1.0 Phase-A assignment (Amendment H — H12 §-assignment pattern)

| deliverable | owner section | status at protocol write |
|---|---|---|
| **Hour-only calendar derivation** (deterministic `:00` subset of committed half-hour `ALGO_CLOCK` YAMLs; exchange-schedule authoring only) | §1.1 / spec §1.5.2 | **not yet implemented** — protocol freezes the derivation rule and warm-iff-calendar semantics before artifacts exist |
| **`ofi_integrated_percentile` at h=1800** (consume existing multi-h factory; no silent h=900 sub) | §2.1 + spec §1.2 | Phase A; verify wiring |
| **Census instrument** (deterministic offline pass; PYTHONHASHSEED=0; **both arms**; eight-symbol pool) | this §1 — script target `scripts/research/hour_checkpoint_drift_census.py` (Task-9-adjacent / Phase-A) | **not yet implemented** |
| **Harness IC row** (in-hour primary + :30 matched-OFI arm) | §2.2 | Phase A; blocked until landed |

### 1.1 Episode definition — the entry predicate EXACTLY

An **eligible in-hour boundary (= one primary episode)** is an
h=1800 `HorizonFeatureSnapshot` boundary satisfying ALL of the
following (spec §1.4 / §5.2–§5.3 / card conditional-distribution
statement — **no threshold freedom**):

1. session window: boundary inside the **09:35–15:50 ET** in-window
   (spec §1.4: `no_entry_first_seconds: 300`,
   `session_flatten_seconds_before_close: 600`) on the nominal
   `boundary_ts_ns` — **12 boundaries / session** by construction
   (pack-08 / 11a §1 actuals bit-exact);
2. required entry-warm ids warm and not stale:
   `{scheduled_flow_window_active, ofi_integrated_percentile,
   ofi_integrated, realized_vol_30s_zscore}` (spec §1.3
   consume-driven set);
3. **clock predicate:** `scheduled_flow_window_active ≥ 0.5`
   (`W_hr = 1` — boundary inside a registered hour-only `ALGO_CLOCK`
   window — injection view excludes `:30`);
4. **OFI quintile arm:** `ofi_integrated_percentile ≥ 0.80`
   (LONG candidate) OR `≤ 0.20` (SHORT candidate);
5. **breakout gate:** `P(vol_breakout) < 0.7` on the latched
   `hmm_3state_fractional` posterior (reference defaults; per-session
   causal-prefix calibration on the first ≤ 100,000 RTH quotes;
   advanced once per quote before the boundary is read);
6. **vol-z backstop:** `realized_vol_30s_zscore ≤ 3.0`;
7. sign agreement (spec §5.2): LONG candidates require
   `ofi_integrated > 0`; SHORT candidates require
   `ofi_integrated < 0`.

**Matched :30 contrast episode (F2 arm — census counts only;
no forward return):** same arms 1–2 and 4–7 with arm 3 inverted:
`scheduled_flow_window_active < 0.5` (`W_hr = 0` — `:30` marks on
the same H = 1800 grid; 6/session by geometry identity). Symmetric
to in-hour under hour-only injection.

Pipeline pins: RTH filter 09:30 ≤ t < 16:00 ET on
`exchange_timestamp_ns`; events sorted by `(timestamp_ns, sequence)`;
reference `platform.yaml` sensor params for existing sensors;
`scheduled_flow_window` calendar injected at construction with the
**hour-only derived view**; h=1800 features from the production
factories; fresh sensor/regime state per session.

**Calendar-warm measurement (JC-10 carried / Amendment D — replaces
ASSERTED values).** The census **measures**, per (symbol, session):

- `calendar_warm_fraction` = share of in-window h=1800 boundaries with
  `scheduled_flow_window.warm == True` under the hour-only derived view;
- `calendar_missing_rate` = share of in-window boundaries with
  `warm=False` due to missing/empty derived view;
- joint conditioning occupancy at the frozen thresholds above
  (in-hour and :30 arms separately);
- measured `w_hr` realization vs geometry identity 0.50;
- measured gate/sign/vol-z residual (do **not** silently import H12's
  `f_resid = 0.3935` as an H13 measured fact — characterization prior
  only).

ASSERTED design priors and Appendix-P projections are **resolved by
measurement** — never tuned. If measured warm drives the pooled
contamination-excluded viable-region episode count below the §1.5
park floor → **PARK on power** (no threshold / prior tuning; program
closes). **Warm-coverage drop rule (coverage-not-tuning):** warm
fraction < 0.5 on > 2 sessions ⇒ that symbol drops from D (evidence-
only symbols report the same metric but cannot enter D).
`calendar_missing_rate > 0` after derivation lands → **infrastructure
FAIL** (not an edge fail; P0-1 defect).

**Hour-subset derivation determinism (census precondition — JC-10):**
re-running the `:00`-filter transform under `PYTHONHASHSEED=0` on the
same committed calendars must produce bit-identical derived-view
content / content-addressed hash per date. Mismatch ⇒ infrastructure
FAIL; census does not proceed. Verifying that `:30` marks are
**excluded** from the injection view (so `W_hr` is non-tautological
at H = 1800) is part of the same precondition.

### 1.2 Frozen viable-region definition (numeric, before execution)

κ = **0.172, FROZEN** (spec §4.1; one-way ratchet — revisable down on
evidence, never up; superseded entirely by the measured conditional
edge once step 2 has run).

**κ minimum-rule (Amendment B / E / spec §4.1 — recorded; bug logged):**
on any discrepancy between the stated freeze and the factor product,
take `κ = min(stated, product)` and log the gap.

    Factor product = 1.20 × 0.55 × 0.55 × 0.80 × 0.65 = 0.18876 ≈ 0.189
    Card freeze (stated) = 0.172
    κ_frozen = min(0.172, 0.189) = **0.172**

The 0.017 gap is an auditable card arithmetic bug (11a DECISION
RECORD 1) — factors are **not** rewritten to erase it.

Per-symbol single-stress floors (spec §4.2, 8-F §11.1 anchor, one-way,
per-fill, bps of fill notional):

| symbol | floor = 2.25 × (2.0 + fee) (bps) | σ₁₈₀₀ min = floor/κ (bps) | short rider-incl. floor (bps) | role |
|---|---|---|---|---|
| APP  | **4.68** | **27.21** | **5.82** | D |
| RMBS | **5.51** | **32.03** | **≈6.61** | D |
| OLN  | **8.69** | **50.52** | **≈9.83** | D (thin; min-commission trap) |
| DIOD | **6.23** | **36.22** | — | D |
| PCTY | **5.19** | **30.17** | **≈6.33** | D (thin short rider) |
| CROX | **5.66** | **32.91** | — | D |
| ENSG | **5.04** | **29.30** | — | evidence-only; never-promotable |
| MLI  | **5.32** | **30.93** | — | evidence-only; never-promotable |

A (symbol, session) cell is **in the viable region** iff its realized
session σ₁₈₀₀ ≥ the symbol's σ₁₈₀₀ min. σ₁₈₀₀ estimator (recorded, not
tuned; H12 C.2 convention scaled to H = 1800): Bessel-corrected sample
std of non-overlapping 1800 s mid log-returns on the 09:30-anchored
grid (last-mid-at-or-before sampling, ~13 raw RTH returns/session
before session-discipline trim), in bps. Soft-σ caveat: 12
returns/session (pack-08 §1) — disclosed, never a post-hoc κ rescue.
SELL-leg viability uses the rider-inclusive short floor column where
stated (spec §4.2).

**Tranche-1B κ caveat:** if a census-legal σ refresh on the operative
20 raises median κ_req above 0.172 for {OLN, DIOD, PCTY, CROX}, that
symbol **drops from D** and the pool is re-checked — no κ inflation.

### 1.3 Contamination handling (JC-1 estimand split carried)

Entry conditioner is **quote-fed** (`ofi_integrated`) × **hour-only
calendar membership** (spec §1.7). Class-B prints never enter
`ofi_raw`. No NEW trade-fed extreme. Contamination-excluded
multiplier = **1.0 at design**.

**Census EXCLUDES (binding primary count):** nothing beyond the
predicate of §1.1 — the primary in-hour episode count IS the §1.1
predicate count. No post-hoc intensity or binary exclusion is applied
to the primary power number.

**Estimand split (H10 JC-1 / H12 carry — Amendment B):**

| estimand | definition | binding? |
|---|---|---|
| **leakage** | share of primary eligible boundaries whose trailing-1800 s OFI integrand path includes quote events that the production `ofi_raw` path would have dropped as degenerate/crossed (should be ≈ 0 by construction) | **REPORT only**; share **> 1 %** ⇒ **sensor-bug investigation trigger** — never a park, never a power deflator |
| **co-travel** | `halfhour_not_hour_cotravel_rate` = share of quintile-OFI H=1800 boundaries that are `:30` (F2 geometry; design ≈ 0.50) | **REPORT only** — **not leakage**; never a park |
| **tranche1b_kappa_drift** | census-measured median κ_req − design κ_req on {OLN, DIOD, PCTY, CROX} | diagnostic; drop-from-D if measured κ_req > κ_frozen |

**No-double-exclusion rationale:** quote-fed × calendar conditioner —
applying a trade-flag exclusion would invent a contamination mechanism
the conditioner does not ingest (H12 carry).

### 1.4 Census outputs (all per symbol × session × daily stratum)

- eligible in-hour episode counts (§1.1), split LONG / SHORT —
  SHORT feeds the long-only restatement rule (§1.6);
- matched :30 contrast episode counts (F2 arm);
- measured calendar-warm coverage per session; coverage drop rule;
  `calendar_missing_rate`; hour-subset derivation hash per date;
- leakage / co-travel / tranche1b_kappa_drift REPORTS (§1.3);
- realized session σ₁₈₀₀ (bps) and viable/non-viable labels (long floor
  and short rider-inclusive separately);
- (intraday gate state × daily stratum) 2×2 boundary table;
- spread-in-ticks distribution at eligible in-hour boundaries AND
  at all warm in-window boundaries, per symbol incl. ENSG/MLI (§2.4 /
  §4 inputs);
- per-stratum episode counts for elevated-A / elevated-B / calm (L4:
  A and B reported separately, never pooled);
- **per-symbol counts always** (six-symbol D sub-total extractable;
  ENSG/MLI contribution separately disclosed).

### 1.5 Park conditions (Amendment B — D-C1 + Appendix-P A-2.1)

**Card→protocol deviations (logged, never silent):**

| # | card / design | this protocol | why |
|---|---|---|---|
| D-C1 | pooled ≥ **130** contamination-excluded episodes (design margin); rebuilt all-cell (B) **120.9** / κ-viable central **≈96** | census park floor = pooled ≥ **100** contamination-excluded viable-region in-hour episodes across the **eight-symbol evidence pool** (D ∪ {ENSG, MLI}) | Lei Amendment B / Appendix P §P.4 A-2.1: ≥ 130 is design margin; ≥ 100 is the census floor (H8/H10/H12 park precedent); evidence-pool counting RULED |
| D-C2 | pre-freeze draft: CPCV `n_groups = 20` / k=2 / 190 / 19 **uniformly** for every D symbol | per-symbol `n_groups` = that symbol's CPCV session count: APP/RMBS **20/2 → 190/19**; {OLN, DIOD, PCTY, CROX} **10/2 → 45/9** (≥ `cpcv_min_folds` 8 ✓). Training-fraction geometry ≈ **87%** (20-sess) vs ≈ **73%** (10-sess). Park line: inability to form **that symbol's session-count groups** (not a hard-coded 20) | Task 8-F-H13 Lei — protocol deviation caught **pre-freeze**; principle: one group per session |

**Frozen double expectation (Amendment C / 8-F-H13 — binding disclosure, not a skip):**

| estimand | projection | vs ≥ 100 | status |
|---|---|---|---|
| (B) uniform H12-haircut viable (either arm) | ≈ **104.9** | PASS (hair) | not load-bearing for expectation |
| (B) κ-viable honesty — **in-window** | ≈ **96** | **FAIL** | **expected PARK (power)** |
| (B) κ-viable honesty — **F2 :30 arm** | ≈ **96** | **FAIL** | **expected F2-INSUFFICIENT** |
| D-only viable (extractable sub-answer) | ≈ **88.5** | FAIL | nested audit baseline |

Census runs as measurement. Projections never rescue and never
condemn — measured governs both directions. A pass must surprise
these priors. A park on either arm closes the program cleanly.

Park conditions — **either parks the card** before any IC outcome is
treated as a PROCEED (and closes the program):

1. **Edge-region emptiness:** for every deployable symbol, the viable
   region contains zero primary in-hour eligible episodes → **PARK**.
2. **Power floor (evidence-pool):** pooled contamination-excluded
   primary in-hour episodes across D ∪ {ENSG, MLI} (viable-region
   restricted) **< 100** — including after calendar-warm measurement
   replaces ASSERTED priors → **PARK on power**. No threshold / prior
   tuning. ENSG/MLI count toward this floor only; they never enter D.
3. **Infrastructure:** `calendar_missing_rate > 0` after Phase-A
   derivation lands, OR hour-subset derivation determinism fail →
   **infrastructure FAIL** (halt; not an edge park; fix and re-run,
   N unchanged). Program-close stop-rule does **not** fire on infra
   FAIL alone (wiring defect, not hypothesis death).

**Axis split / pool-collapse verdict mapping (Amendment B; every
partial-pool outcome — eight-symbol structure):**

| measured pooled viable-region in-hour (evidence pool) | \|D\| after drops | verdict |
|---|---|---|
| ≥ 100 and edge non-empty on remaining D | any | **PROCEED** to step 2 (power clears); F2 arm separately scored for adjudicability; report D-only sub-total |
| < 100 | any | **PARK (power)** — **program closes** (H13 final card) |
| ≥ 100 on geometry fantasy / uniform haircut but < 100 measured | — | measured governs; projections never rescue |
| edge-region empty on every remaining D symbol | any | **PARK (edge emptiness)** before power — program closes; evidence-only n **cannot** rescue an economically empty D (A-2.1 safeguard) |
| symbol deployability fail (κ / warm / rider) | drops from D; evidence-only stay; **re-check evidence-pool ≥ 100** | if then < 100 → PARK (power) → program closes |
| drop cascade → D ≤ 5 under κ/warm/rider **before** census instruments | — | Lei re-auth required (spec §4.5); rebuilt D-only table says ≤ 5 fails census floor even as projection |
| ENSG/MLI post-hoc promotion into D | — | **FORBIDDEN** (never-promotable); would be a new trial + screen override, not this protocol |

**n-class labels:** park condition 1 (edge-region emptiness) is
**n-variant** → PARK evidence-infrastructure. Park condition 2
(pooled < 100) is **n-variant** → PARK on power. Neither is a
magnitude REJECTED. Infrastructure FAIL is **n-invariant** wiring.

### 1.6 Deployable-set restatement rules (pre-registered; JC-5 carried)

The census fixes **D** and the evidence pool:

- **D = {symbols that clear deployability}**: edge-region non-empty
  under long floor (and short rider if two-sided claim retained);
  warm-coverage drop rule not fired; hour-only derived calendars
  present; κ_req ≤ κ_frozen after census σ refresh.
- **Long-only restatement (pre-stated):** if OLN or PCTY (or any D
  symbol) fails the SELL-leg axis (κ·σ₁₈₀₀ or measured short edge vs
  rider-inclusive floor), that symbol restates **long-only** and its
  contribution to the pooled power count is the continuation-long
  episode count alone; D membership re-checks.
- **SIGN-CONSISTENCY D-membership (JC-5 carried, deployability class;
  fires only on a primary §2b PASS):** each symbol then in D must
  show own-boundary in-hour extreme-OFI RankIC **sign matching the
  claim** (continuation-positive). Fail ⇒ that symbol **leaves D**;
  evidence-pool power axis-split recheck vs ≥ 100. **No magnitude
  bar, no p bar;** cannot loosen a primary fail, cannot park the
  card, cannot REJECT — acts only on a pass. **ENSG/MLI never enter
  this check as D members.**
- **Symbol fails deployability ⇒ drops from D**; pool re-checks
  ≥ 100 on remaining evidence pool. Pool failing after drop → PARK
  → program closes.
- **All D symbols fail deployability ⇒ PARK** regardless of
  evidence-only counts (A-2.1 safeguard).
- ENSG/MLI are never in D.

### 1.7 Post-park path

**No occupancy re-threshold variant is pre-authorized.** The quintile
split (0.80 / 0.20) and hour `W_hr` membership ARE the mechanism
claim, not tuning axes; calendar-warm is measured, not re-fit; hour-
subset rule is frozen. A park on power or emptiness **closes the
program**. Any subsequent variant requires Lei's explicit approval
with reasons and is a new ledger row (N-neutral until outcome
contact; first IC contact +1 N). Iterative occupancy fishing is
prohibited.

### 1.8 Post-park path after PROCEED

On census PROCEED: D, the evidence pool, and the measured warm /
occupancy / arm counts are pinned; step 2 begins only under P0-1
green and this file frozen (post-8-F).

---

## 2. STEP 2 — SIGN-GOLDEN + IC GATE (ENG-3 precedent, gas_01/gas_02)

Per the repo's own promotion policy (engine-readiness ENG-3, as
exercised in `docs/research/gas_01_integrated_ofi.md`): **no promotion
of the signature without BOTH (a) and (b).**

**H13 two-arm design (Amendment D — FROZEN COMPLETELY):** step 2b is
(i) **in-hour primary gate** (pooled RankIC / p / n bars at the frozen
numbers below) **AND** (ii) the **window-binding contrast** (:30
matched-OFI arm) with its own numeric criterion and §9 consequence.
Every intersection of primary × binding outcomes is declared in §9.1.
Both arms' adjudicability floors: out-window (and in-window sample)
n ≥ **100** (JC-9 precedent).

### 2.1 (a) Sign-golden through the REAL pipeline

**Phase-A assignment:** requires hour-only derived calendars +
`ofi_integrated_percentile` at h=1800 + `scheduled_flow_window`
injection. New test module
`tests/research/test_gas_hour_checkpoint_drift_sign.py` (Phase A /
Task 9 implements; assertions fixed here).

Synthetic tape with known ground truth pushed through the real
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (the
gas-01 pattern):

1. **In-hour continuation golden (LONG):** a synthetic tape whose
   trailing 1800 s window is dominated by buy-side quote-flow so that
   at an h=1800 on-the-hour mark boundary `ofi_integrated > 0`,
   `ofi_integrated_percentile ≥ 0.80`, and
   `scheduled_flow_window_active ≥ 0.5` ⇒ the §5.2 draft `evaluate`
   (once implemented) emits direction **LONG** — trade WITH the
   hour-bound OFI extreme.
2. **Mirror golden (SHORT):** the same tape mirrored ⇒
   `ofi_integrated < 0`, percentile ≤ 0.20, `W_hr = 1` ⇒ SHORT.
3. **Clock-null golden (THE card-defining assertion):** the same
   absolute OFI extremity but `scheduled_flow_window_active < 0.5`
   (`:30` / off-hour mark under hour-only injection) ⇒ `evaluate`
   returns **None** — no signal without the hour predicate. This is
   F2 in golden form.
4. **Interior-null golden:** `W_hr = 1` but percentile interior to
   (0.20, 0.80) ⇒ `evaluate` returns **None**.
5. **Calendar-cold golden:** empty/missing hour-only derived view ⇒
   `scheduled_flow_window` not warm ⇒ entry suppressed
   (warm-iff-calendar, spec §1.3).
6. **Sign-disagreement golden:** percentile ≥ 0.80 but
   `ofi_integrated ≤ 0` (or mirror) ⇒ `evaluate` returns **None**
   (spec §5.2 sign agreement).
7. **h=1800 key-presence golden:** the snapshot at h=1800 carries the
   consumed entry ids including `ofi_integrated_percentile` and
   `scheduled_flow_window_active` (factory / calendar wiring
   regression lock, P0-1 — no silent h=900 percentile).

Any assertion failure ⇒ **REJECTED (sign/wiring defect)** — fix is an
implementation correction, not a tuning event (N unchanged), but the
gate must re-run from scratch. Census-consistency smoke (Phase B
mismatch after YAML lands): implementation-correction re-run, N
unchanged (spec §16).

### 2.2 (b) RankIC evidence — two arms; thresholds and sessions fixed now

**Phase-A assignment:** harness IC row on the census-pinned predicate
— `scripts/sensor_feature_ic.py` extended with an H13 row (Phase A
implements; measurement plumbing for the pre-registered primary trial,
not a new trial). Sensors: `scheduled_flow_window` (hour-only
calendar-injected), `ofi_raw` (1.0.0), `realized_vol_30s` (1.3.0) at
reference params; features = consumed ids at h = 1800; each warm
boundary paired with the forward mid log-return over the snapshot
horizon; statistics via `research/forward_ic.py` (`spearman_ic`,
`bucketed_forward_return`, `long_short_edge_bps`).

**IC variable (fixed now — conditional hour×OFI hypothesis):** the
primary IC pair is `x = ofi_integrated` (signed) vs `y` = signed
forward 1800 s mid log-return, computed **within the in-hour
extreme-OFI stratum** (`W_hr = 1` AND percentile ≥ 0.80 OR ≤ 0.20,
with continuation sign matching OFI sign).

**Sessions (named now):** the closed evidence-pool set of §0.
**Primary evidence = pooled over the eight-symbol evidence pool**
(viable-region sessions) for the conjunctive IC / sample floor —
**JC-12 APPROVED** (P.3 coupling: park floor counts the evidence pool
because step 2 adjudicates on it); per-symbol and D-only sub-totals
always reported; JC-5 / §2.3 remain D-scoped. Contamination handling
per §1.3.

#### 2.2.0 In-hour primary gate (ALL required, at h = 1800) —
conjunctive-IC rationale carried verbatim from 8-F / H10 / H12

| criterion | threshold | n-class |
|---|---|---|
| in-hour extreme-OFI pooled RankIC sign | > 0 (continuation-correct) | **n-invariant** (sign) |
| in-hour extreme-OFI pooled \|RankIC\| | ≥ **0.03** | **n-invariant** (magnitude) |
| in-hour extreme-OFI pooled significance | Fisher-z two-sided p ≤ **0.01** | n-variant (p) |
| pooled sample minimum | n ≥ **100** warm boundaries in the in-hour extreme-OFI stratum pooled over the **eight-symbol evidence pool** viable-region (else INSUFFICIENT). Feasibility: κ-viable central ≈ **96** (expected miss); uniform-haircut ≈ **104.9**. Unreachable ⇒ PARK evidence-infrastructure, never magnitude rescaling. D-only sub-total always reported (nested ≈ 88.5). | **n-variant** (power) → PARK evidence-infrastructure if unreachable after measurement; **program closes** |
| bucket monotonicity | `bucketed_forward_return` (5 equal-count buckets of x, in-hour extreme stratum): top-minus-bottom forward-return spread positive in the continuation direction | **n-invariant** (sign) |
| conditional tail (F1 anchor) | mean continuation-signed 1800 s forward return on primary in-hour eligible episodes > 0 with t ≥ 2 pooled over the evidence pool | **n-invariant** on sign; t is n-variant |
| per-symbol diagnostics | RankIC \|RankIC\|, n, p reported per symbol — magnitude/p **NON-GOVERNING**; sign feeds §2.2.2 SIGN-CONSISTENCY D-membership on a primary 2b PASS only (**D members only**) | magnitude/p diagnostic; sign → D on pass |

The criteria are **deliberately conjunctive** (8-F ruling, carried
verbatim): the p ≤ 0.01 bar binds at moderate n, and the
|RankIC| ≥ 0.03 floor rejects effects that are trivial-in-magnitude
yet significant at huge n. Neither alone is sufficient.

**Primary 2b PASS** ⇔ all rows of §2.2.0 clear. **Primary 2b FAIL** ⇔
any magnitude/sign/tail/bucket row fails (n-invariant REJECTED path)
or p fails after n ≥ 100 (reported; magnitude outranks when both
fail — §9.1). n < 100 with magnitude uncomputable ⇒ INSUFFICIENT →
PARK (power) → **program closes**, never REJECTED on magnitude.

#### 2.2.1 Window-binding contrast — :30 matched-OFI arm
(Amendment D — FROZEN; F2 load-bearing)

**Population (fixed now):** matched OFI-quintile episodes with
`W_hr = 0` (`:30` marks) on the same closed evidence-pool grid,
viable-region restricted, same gate/vol-z/sign-agreement arms as
§1.1 with clock inverted. Geometry-symmetric to in-hour.

**Eight-symbol out-window projection (shown now):**

| estimand | projection | vs ≥ 100 adjudicability |
|---|---|---|
| :30 all-cell (B uniform) | **120.9** | design-margin FAIL vs 130; vs 100 PASS (hair) |
| :30 viable-region (B uniform) | **≈ 104.9** | PASS (hair) |
| :30 viable κ-viable honesty | **≈ 96** | **FAIL — expected F2-INSUFFICIENT** |
| :30 D-only viable (extractable) | **≈ 88.5** | FAIL |

Adjudication requires measured out-window n ≥ **100** (else
**F2-INSUFFICIENT** → PARK evidence-infrastructure on the binding
arm — **JC-9**: no primary-only PROCEED; never auto-REJECT on
mechanism, never magnitude rescaling; **program closes**).

**IC / edge variable (fixed now):** same `x = ofi_integrated` vs
forward 1800 s mid log-return, computed **within the :30
extreme-OFI stratum**.

**Numeric F2 criteria (ALL required for F2-BINDING PASS — H12
rulings carried):**

| # | form | criterion | n-class |
|---|---|---|---|
| F2-S | Substance | :30 continuation-signed mean 1800 s forward return ≤ 0 within 2 SE (not significantly positive) | **n-invariant** on the "not same-class continuation" claim |
| F2-D | Differential | (in-hour continuation-signed mean − :30 continuation-signed mean) > 0 AND the difference ≥ 1 SE of the difference | **mixed** — sign of (in−:30) is **n-invariant**; the ≥ 1 SE magnitude conjunct is **n-variant** (JC-2) |
| F2-R | RankIC companion (reported; binding with F2-D) | in-hour extreme-OFI RankIC − :30 extreme-OFI RankIC > 0 | **n-invariant** on sign of contrast |

**F2 outcome vocabulary (closed — used by §9.1; JC-2 / JC-3 carried):**

| outcome | definition |
|---|---|
| **F2-BINDING PASS** | **F2-S ∧ F2-D ∧ F2-R** all hold at n ≥ 100 (conjunction pinned) |
| **F2-BINDING NEGATIVE** | :30 continuation-signed mean > 0 with t ≥ 2 (affirmative same-class continuation — **contaminated shelf**; JC-3) |
| **F2-BINDING FAIL** | residual — not PASS and not NEGATIVE (e.g. flat / under-separated differential without significant :30 continuation; or F2-R fails while F2-S holds) |
| **F2-INSUFFICIENT** | measured :30 n < 100 → **PARK evidence-infrastructure** (JC-9); no primary-only PROCEED; **program closes** |

**Firewall status of the :30 arm (binding — spec §12.2):** if the arm
is **F2-BINDING NEGATIVE** (shows continuation), that arm is a
**contaminated diagnostic about a dead claim** — **never reusable as
confirmation evidence for H9 or any future unclocked-OFI / half-hour /
KYLE card** without Lei extraordinary review. H13 evidence never
cites toward H9 revival regardless of F2 outcome. Recorded again in
§9.3.

#### 2.2.2 Per-symbol step-2 posture (JC-5 carried — D members only)

**No binding per-symbol magnitude/significance step-2 safeguard.**
Pooled §2.2.0 criteria alone govern the primary 2b PASS/FAIL.
Per-symbol RankIC magnitude and p are diagnostics only.

**PLUS — SIGN-CONSISTENCY D-membership condition (deployability
class, §1.6 family; JC-5 carried):** on a **primary 2b PASS**, each
symbol then in D must show own-boundary in-hour extreme-OFI RankIC
**sign matching the claim** (continuation-positive). Fail ⇒ that
symbol **leaves D** ⇒ evidence-pool power axis-split recheck
(§1.5 / §9.0.2) vs ≥ 100. **No magnitude bar, no p bar.** Precedence
(§9.1): acts **only on a pass** — cannot loosen a primary 2b FAIL,
cannot park the card, cannot REJECT. ENSG/MLI excluded from D-
membership by construction.

### 2.3 Measured-edge anchor (spec §4.1 / §5.5 acceptance test)

The measured conditional edge (mean continuation-signed 1800 s forward
return on primary **in-hour** eligible episodes, bps one-way, per
symbol in D, viable region) must be **≥ the per-symbol single-stress
floor** (§1.2) for the symbol to remain in D; SELL-leg edges are
additionally tested against the rider-inclusive short floors. This
measured value supersedes all κ arithmetic from this point (spec §4.1
one-way ratchet) and becomes the G12 disclosure input
(`edge_estimate_bps` = the D-set minimum measured edge,
conservative). If D empties here, the card parks → **program closes**.
Evidence-only symbols report the same statistic diagnostically —
**never** as deployable economics.

### 2.4 Tick-constraint artifact tests (spec §7 / §8 tick axis)

Run alongside the IC gate (evidence set including ENSG/MLI × 10 and
OLN as in-D discreteness case):

1. spread-in-ticks distribution **at eligible in-hour boundaries**
   per symbol;
2. **≥ 4-tick-stratum re-derivation:** conditional continuation edge
   on in-hour boundaries with prevailing spread ≥ 4 ticks; pass =
   sign-consistent with the pooled estimate; collapse ⇒ definition
   kill on the affected stratum;
3. **OLN quantum test:** conditional 1800 s move mass vs counter the
   ±1 half-tick quantum (~2.1 bps at OLN); genuine persistence must
   show mass beyond one quantum. OLN remains in D unless §1.6 /
   §2.3 drops it;
4. sign difference across buckets after quantum correction ⇒
   **definition-level kill**.

---

## 3. STEP 3 — CPCV (`research/cpcv.py`)

### 3.1 Configuration (numeric, with the H=1800 embargo re-derivation — Amendment A; D-C2 session-count freeze)

Run **per symbol in D**, on that symbol's CPCV session series (pooled
structure does not merge symbols inside a CPCV path — serial
dependence is within-symbol). ENSG/MLI are **never** CPCV subjects
(A-2.1 orthogonality: steps 3–8 D-scoped).

**Principle (Task 8-F-H13 — D-C2):** `n_groups` = that symbol's CPCV
session count — **one contiguous group per session**.

| symbol set | CPCV sessions | n_bars ≈ | n_groups | k | φ = C(N,k) | paths = C(N−1,k−1) | train frac (interior non-adj.) |
|---|---|---|---|---|---|---|---|
| {APP, RMBS} | **20** (full operative grid) | **240** | **20** | **2** | **190** | **19** ≥ 8 ✓ | ≈ **87%** (208/240) |
| {OLN, DIOD, PCTY, CROX} | **10** (preamble grid) | **120** | **10** | **2** | **45** | **9** ≥ 8 ✓ | ≈ **73%** (88/120) |

- **Bar** = one h=1800 in-window boundary; session discipline ⇒
  **12 bars/session** (exact count = emitted in-window boundaries;
  sessions never concatenate state — sensors and regime engine
  re-warm per session replay).
- **Groups:** `n_groups` = session count above; group boundaries
  coincide with session boundaries in calendar order.
- **k:** `k_test_groups = 2` for every D symbol (paths as in the
  table — both clear `cpcv_min_folds` ≥ 8).
- **Purge:** `label_horizon_bars = 1`. Derivation: the label is the
  1800 s forward mid return ⇒ label span = 1800 s = 1 bar exactly.
- **Embargo:** `embargo_bars = 2` (**JC-1 APPROVED — Task 8-F-H13**).
  Derivation (Amendment A; bars shown; H12 lineage rule — **verified
  from the H13 spec, not assumed**):

  | component | seconds | note |
  |---|---|---|
  | label horizon (purge) | 1800 | 1 bar — covered by `label_horizon_bars = 1` |
  | `ofi_integrated` / `ofi_integrated_percentile` event-time window | **1800** | `HorizonWindowedFeature` on `ofi_raw` path — **deepest lookback** |
  | `scheduled_flow_window` lookback | **0** | **stateless** calendar membership — no feature lookback |
  | `ofi_raw` `warm_window_seconds` | 300 | nested under the 1800 s integrate path; does **not** extend deepest lookback beyond 1800 |
  | deepest feature lookback | **1800** | OFI window only (no nested OLS / λ window) |
  | residual after 1-bar purge | 1800 | ⌈1800 / 1800⌉ = **1 bar minimum** |
  | no-fixed-constant components | +1 bar | `realized_vol_30s_zscore` 2000-reading count window (`RollingZscoreFeature` default — quote-rate-dependent) **and** quote-clocked HMM posterior — **both sit on the entry/gate path** (spec §5.3 `on_condition`: `P(vol_breakout) < 0.7` and `realized_vol_30s_zscore <= 3.0`) → **NFC +1 applies** |
  | **adopted `embargo_bars`** | **2** | 1 + 1 |

  **Lineage rule (H12 JC-1, carried generally):** embargo =
  arithmetic minimum from deepest feature lookback after purge
  (⌈lookback_s / bar_s⌉), **+1 NFC when gate consumers warrant**
  (rv-z count window and/or quote-clocked HMM on the entry/gate
  path). H12: deepest 900 → 1 + NFC 1 = 2. H13: deepest 1800 → 1 +
  NFC 1 = **2** (same bar count; longer wall-clock exclusion).

  Total forward exclusion = 1 + 2 = **3 bars = 5,400 s** per test
  region. `embargo_bars = 2 ≥ cpcv_min_embargo_bars = 1` ✓; the
  block-bootstrap block length is `max(1, embargo_bars) = 2` bars
  (the declared serial-correlation length), per `build_cpcv_evidence`.

### 3.2 Return series and per-split training (the CPCV contract)

Per-bar return series per symbol: at each boundary, the
**continuation-signed 1800 s forward mid log-return minus the
round-trip-derived cost 2 × C_ow,stressed(symbol)** — C_ow,stressed =
1.5 × (2.0 + fee) so the deduction is the per-symbol stressed
one-way floor/1.5 basis (APP ≈ 6.24 / RMBS ≈ 7.29 / OLN ≈ 11.59 bps
round-trip-derived) — **if the boundary is entry-eligible under the
full frozen rule** (§1.1 + the `evaluate` EV gate with the split's
trained `edge_scale_bps`), else **0.0**. This is a
*statistical-validity* series — a disclosure-arithmetic cost proxy,
not an execution result (fill realism enters only at steps 7–8).

Per-split training: on each of the φ splits (190 for APP/RMBS; 45 for
{OLN, DIOD, PCTY, CROX}), `edge_scale_bps` is re-estimated on the
split's purged+embargoed **train** bars (OLS of continuation-signed
forward return on the spec §5.2 normalised exceedance `excess`,
through the origin, clipped to **[6.0, 18.0]** — **JC-8 APPROVED**;
clip coincides with the free-range — coincidence rule recorded, not
an independent knob) and applied to the **test** bars through the
frozen `evaluate` rule. All other parameters are frozen at spec
defaults (`ofi_percentile_min = 0.80`, `edge_cap_bps = 16.0`, the
per-symbol floor constants, gate thresholds §5.3). This in-protocol
calibration is part of the single pre-registered primary trial; it
does not increment N.

**Dual reporting (8-F ruling, carried verbatim):** the **PRE-COST
path distribution** (same series without the 2 × C_ow,stressed
deduction) is computed and reported **alongside the cost-adjusted one
at every step** that quotes CPCV output — the pass/fail **criterion
stays on the cost-adjusted series**. The pre-cost distribution is
diagnostic context (separating "no continuation exists" from
"continuation exists but below the cost proxy"), never a result.

### 3.3 Annualization and thresholds (Amendment A; GateThresholds implication: NONE)

```
annualization_factor = sqrt(12 × 252) = sqrt(3,024) ≈ 54.9909 ≈ 55.0
```

(bars/session × trading days/year — the sqrt(252)-commensurate
scaling for 1800 s in-window bars; Amendment A **re-derived**),
passed to `build_cpcv_evidence` so emitted Sharpes are annualised and
directly comparable to the `GateThresholds` defaults. Bootstrap:
`n_bootstrap = 10,000`, `seed = 0` (Inv-5 bit-identical).

**GateThresholds implication (stated):** H = 1800 changes the
annualization factor (√(12×252) ≈ 55.0 vs H12's √(25×252) ≈ 79.37)
and the wall-clock embargo span (5,400 s vs 2,700 s), **not** the
annualised acceptance bars themselves. Path counts 19 (APP/RMBS) and
9 ({OLN, DIOD, PCTY, CROX}) both ≥ 8, embargo 2 ≥ 1, and the
annualised Sharpe / p-value bars are horizon-independent once the
annualization factor is commensurate. **Thresholds: the
`GateThresholds` defaults, NO per-alpha `gate_thresholds:` override
— none is needed and none is pre-registered:**

| gate | value | this run |
|---|---|---|
| `cpcv_min_folds` | ≥ 8 reconstructed paths | **19** (APP/RMBS) / **9** ({OLN, DIOD, PCTY, CROX}) by construction |
| `cpcv_min_mean_sharpe` | ≥ 1.0 (annualised) | must clear on **every** symbol in D |
| `cpcv_max_p_value` | ≤ 0.05 (block bootstrap) | every symbol in D |
| `cpcv_min_embargo_bars` | ≥ 1 | **2** by construction (JC-1 APPROVED) |

Fail on any symbol ⇒ that symbol leaves D; pool / D emptying ⇒ status
per §9 (**program closes** if D empty after a magnitude-class fail,
or PARK/REJECTED per the step). **n-class:** mean-Sharpe / p-value
fails after honest annualization are treated as **n-invariant
REJECTED** (does not survive purged OOS reconstruction); inability to
form that symbol's **session-count groups** is **n-variant PARK**
(evidence-infrastructure) — D-C2 corrected the pre-freeze hard-coded
"20 groups" line.

---

## 4. STEP 4 — REGIME STRATIFICATION (manual per R6 / research-protocol Phase 3.3 — no shipped harness)

### 4.1 Strata (cutpoints fixed now; spread axis = spread-in-ticks —
JC-4 APPROVED; task "spread_z_30d" prose overridden by spec ban)

Partition **warm h=1800 boundaries** (per symbol, full evidence-pool
grid for reporting; acceptance scored on D ∪ evidence-pool pooled
cells with n ≥ 100) on two axes:

- **Vol axis** — HMM dominant state (`RegimeState.dominant_name`,
  `hmm_3state_fractional`): `compression_clustering` / `normal` /
  `vol_breakout` (3 strata);
- **Spread axis** — boundary-time prevailing **spread-in-ticks** at
  **per-symbol terciles of the UNCONDITIONAL grid spread
  distribution** — all warm in-window boundaries, never
  eligible-only — **frozen at census time and disclosed per symbol**
  (H8/H10/H12 JC-4 carried: H13 spec bans `spread_z_30d` —
  census warm starvation on thin names; F3 is worded on
  spread-in-ticks; APP vs OLN medians live in different buckets).
  Cutpoints computed once from the census output before any forward
  return exists.

The daily calm/elevated-A/elevated-B stratum is a **third, reporting
axis** (every statistic also reported in the gate-state × daily-
stratum 2×2). F3 kill clause: conditional continuation sign across
**spread-in-ticks terciles within the benign stratum** (benign =
`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0 ∧ W_hr = 1`).

### 4.2 Procedure and per-stratum minimum

Within each (vol × spread) stratum: repeat the §2.2.0 IC test
(in-hour extreme-OFI `spearman_ic` on stratum boundaries, plus the
§2.2.1 F2 contrast where the stratum holds matched :30 bars)
and, where the stratum holds enough bars to form the §3 groups,
repeat CPCV (same config; a stratum that cannot form 20 groups
reports CPCV-INFEASIBLE, not a fail). **Minimum per-stratum sample =
100 boundary observations** (research-protocol Phase 3.3 rule 4);
below it the stratum reports **INSUFFICIENT** — never pooled away,
never counted for or against the acceptance rule.

### 4.3 Acceptance rule (numeric)

**PASS** iff, on the pooled evidence-pool (D ∪ {ENSG, MLI}) sample:
the in-hour extreme-OFI conditional continuation is **sign-stable
(continuation-positive) AND in-hour extreme-OFI RankIC ≥ +0.02 with
Fisher-z p ≤ 0.05** in at least **2 vol strata × 2 spread strata**
(i.e. ≥ 2 cells on each axis among cells with n ≥ 100).
Single-stratum concentration is a fragility flag reported to Lei (not
an automatic kill) **unless** the conditional continuation sign
reverses across spread-in-ticks terciles within the benign stratum —
that is F3, a **definition-level kill**.

**n-class:** sign reversal across strata = **n-invariant REJECTED**
(definition); failure to clear ≥ 2 × 2 with adequate n =
**n-variant** → HYPOTHESIS-REVISE (regime-fragile; a narrower card is
a new trial — and under the stop-rule, Lei decides whether
hypothesis-revise still closes the program or opens an extraordinary
path; default = **program closes** on any death).

### 4.4 Invariance checks (spec §6, slotted here; numeric criteria)

- **I-1 (zero-integrated-edge conservation, mandatory):** funding
  pool (a) = Σ_episodes (measured continuation move × contra-side
  fading volume inside the episode window — resting LPs'
  mark-to-horizon loss); strategy integrated pre-cost conditional
  edge (b) at declared participation (≤ top-of-book scale).
  **Pass:** (b) / (participation share × (a)) ≤ 1.5. Companions:
  (i) unconditional forward returns over all matched in-hour
  boundaries integrate to ≈ 0 — |mean| ≤ 2 × SE; (ii) the
  **:30 matched-OFI stratum** is exactly F2 (§2.2.1) — if it
  continues at the same sign/magnitude class, the hour does no work.
  Fail ⇒ **misattribution ⇒ hypothesis-revise** (or REJECTED if F2
  NEGATIVE per §9).
- **I-2 (side symmetry):** continuation-long vs continuation-short
  conditional edges in the benign in-hour stratum agree within
  sampling error — two-sample z ≤ 2. Fail ⇒ hypothesis-revise; SHORT
  carries the SSR/HTB optimism caveat; §1.6 OLN/PCTY long-only is an
  *economic* asymmetry — I-2 tests pre-cost mechanism symmetry only.
- **I-3 (hour / flow co-travel; mechanism attribution):** identical
  to F2-D / F2-R — in-hour continuation must exceed matched :30; no
  differential ⇒ θ₂ (hour decoration). Numeric reading = §2.2.1.
- **IC(t) decay (research-protocol Phase 5):** compute RankIC at
  forward horizons t ∈ {300, 900, 1800, 3600} s on the in-hour
  extreme-OFI stratum; fit `IC(t) = IC_0 · exp(−λ t)`; fitted
  half-life must lie in **[450, 1800] s** (declared hl = 900 ± a
  factor of 2 — **JC-11 APPROVED**). Outside ⇒ hypothesis-revise;
  non-decaying IC(t) is F1-adjacent death.

---

## 5. STEP 5 — DSR (`research/dsr.py`)

Computed on the pooled-D per-bar cost-adjusted return series (§3.2
definition, all D symbols' sessions, bars in (symbol, session, time)
order; n_obs = total bar count — ≈ 240 × |D|):

- `build_dsr_evidence_from_returns(returns=…, trials_count=N,
  annualization_factor=sqrt(3,024) ≈ 55.0)` with **N = the
  then-current living-ledger count at computation time** — **N = 12
  at protocol write** (Amendment F / pack-11); every evaluation event
  between freeze and the DSR computation increments it first
  (FQ-6B-R). Spec §14 drafted-not-evaluated variants count **only if
  actually evaluated** by then.
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
acquiring more trials without a better Sharpe worsens DSR) →
**program closes**.

---

## 6. STEP 6 — DRIFT DIAGNOSTICS

**What re-estimates, on what window:** at runtime, **nothing** — all
sensor params, gate thresholds, session constants, and calendar
lead/ε / hour-subset rule are fixed (spec §1.4 / §1.5 / §5.1). The
only estimated quantity in the whole candidate is `edge_scale_bps`
(Task-8 calibration, §3.2). Drift diagnostics therefore test the
*stability of the fixed-parameter machinery and the single calibrated
parameter* across the grid's sessions; pre-stated bounds below are
disqualifying.

### 6.1 Regime-engine behavior (`scripts/regime_diagnostics.py` as anchor)

Run per (symbol ∈ D, session) over the grid with the Task-9 config,
`--horizon 1800`. The H13 regime arm is an **exclusion screen**
(`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0`), not a
positive benign selector — bounds adapted from H8/H10/H12 JC-6
(**JC-6 APPROVED — dwell ≥ 1800 s**):

| diagnostic | pre-stated stability bound (per session unless noted) |
|---|---|
| min pairwise emission separation d | ≥ 0.5; below ⇒ posterior non-discriminative that session ⇒ boundaries leave the benign stratum (fail-safe) |
| argmax occupancy | no single state > 0.98 of RTH quotes (else same treatment) |
| exclusion-screen OFF fraction (`P(vol_breakout) ≥ 0.7 ∨ rvz > 3.0` over in-window boundaries) | ≤ 0.95 per session; > 3 deployable-symbol sessions above ⇒ drift-disqualifying (hypothesis-revise). Always-ON screen (OFF ≈ 0) is expected calm-tape behavior — reported, not bounded. |
| median screen-ON dwell (seconds, per symbol pooled) | ≥ **1800 s** (one horizon — JC-6 APPROVED); below ⇒ hypothesis-revise |
| full-gate ON fraction (conditioning fraction) | reported per session against the census; no numeric kill here — power adjudicated at §1.5 |

### 6.2 Sensor / conditioning stability

| diagnostic | pre-stated bound |
|---|---|
| per-session eligible in-hour episode rate (per deployable symbol, within a daily stratum) | max/min ratio across that stratum's sessions ≤ 5; above ⇒ hypothesis-revise |
| `scheduled_flow_window` calendar-warm coverage | spec §1.3 / §1.5.3: warm < 0.5 on > 2 sessions ⇒ symbol leaves D; `calendar_missing_rate > 0` ⇒ infrastructure FAIL |
| hour-subset derivation hash stability | bit-identical across re-runs (JC-10); drift ⇒ infrastructure FAIL |
| `ofi_integrated` / percentile warm coverage | reported per session; quote-warm starvation that collapses the pooled count below §1.5 is PARK on power (already scored) |
| `realized_vol_30s_zscore` warm coverage | reported per session (mandatory) |
| in-hour vs :30 occupancy ratio | reported against geometry identity 6:6; material deviation unexplained by HT/gate ⇒ calendar-authorship / subset-derivation investigation (infrastructure), not edge tuning |

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

`configs/bt_sig_hour_checkpoint_drift_h1800_v1.yaml` (Phase B / Task 9
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
`session_flatten_seconds_before_close: 600`; symbols = D only;
hour-only calendar injection.

### 7.2 Runs and required outcomes (numeric)

Per symbol in D over its 20 grid sessions: `feelies backtest
--config configs/bt_sig_hour_checkpoint_drift_h1800_v1.yaml --symbol <S>
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
4. **Fill-quality diagnostics (spec §11; JC-7 APPROVED):** through-
   fill share of entry fills ≤ 50 % — for this card's passive-entry-
   into-continuation geometry a through fill means price crossed
   back through the resting level (deep retrace), the execution-
   layer θ₂/θ₃ signature; filled-minus-unfilled **1800 s** markout
   gap ≤ the 2.0 bps charged adverse selection (900 s markouts
   reported alongside) — if exceeded, F4
   arithmetic is **re-run with the measured figure** (pre-registered
   recomputation, not a new trial) and outcomes 1–2 re-judged on it.
   `EXPIRED` (timeout-cancel) rate and time-to-fill distribution
   reported against the 3-tick-delay + hazard model.

Fail on outcomes 1–3 after steps 1–6 passed ⇒ **TRAP-QUADRANT**
(statistically valid, execution-invalid) → under stop-rule, **program
closes** (no extraordinary revival without Lei).

---

## 8. STEP 8 — SENSITIVITY GRID (8-F sensitivity amendment carried verbatim)

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
**PASS** = the F4 clearance verdict — measured net execution edge ≥
the per-symbol §1.2 single-stress floor AND cost-survival `SURVIVES`
— holds at all 27 neighborhood vertices and the inv12-stress point,
for every symbol in D. The AS axis here is a robustness sweep, never
a second stress folded into the floor (no stacking). A verdict that
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

### 9.0 Consequence-precedence (FROZEN VERBATIM — Amendment B / spec §4.3 / Appendix P)

1. Primary §9 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Evidence-pool power bar governs census PROCEED/PARK; a
   single-symbol shortfall inside the pool does **not** park the card
   if the pool clears ≥ 100 contamination-excluded — unless that
   symbol also fails deployability park arithmetic, in which case it
   drops from D and the **evidence pool** is re-checked (A-2.1-class
   axis split). Evidence-only n cannot rescue an economically empty D.
   *(Numeric floor = 100 per D-C1 / §P.4; design margin ≥ 130;
   honest expectation ≈ 96.)*
3. Magnitude-class IC bars are `n-invariant` → REJECTED-terminal;
   power-class census misses → PARK evidence-infrastructure →
   **program closes**.
4. **F2 window-binding** (mechanism): F2-BINDING FAIL or NEGATIVE →
   REJECTED (substance) when it co-fires with a primary posture that
   would otherwise continue — see §9.1; n-invariant for the binding
   claim.
5. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.
6. **Stop-rule:** any death (PARK / REJECTED / TRAP-QUADRANT after
   statistical pass) **closes the program**. HYPOTHESIS-REVISE and
   infrastructure FAIL are the only non-closing statuses (infra =
   fix-and-rerun; hypothesis-revise = Lei extraordinary path only).

### 9.1 Instrument-pair precedence walk (completeness check)

Every intersection that can fire in the same step is declared. An
absent row would be a freeze-blocking defect.

| instruments that can co-fire | which governs | subordinate effect / stop-rule |
|---|---|---|
| §1.5 power (pooled < 100) ∩ §1.5 edge-emptiness | **both PARK** (either parks); report both | **program closes** |
| §1.5 infrastructure FAIL ∩ any park | **infrastructure FAIL** governs (halt; N unchanged) | program-close does **not** auto-fire; fix wiring |
| §1.5 pooled power PASS ∩ single-symbol episode shortfall | **pooled governs PROCEED** (§9.0.2); symbol stays unless deployability fails | diagnostic; report D-only sub-total |
| §1.5 pooled power PASS ∩ symbol deployability fail (edge / rider / warm drop / sign-consistency) | symbol **drops from D**; **evidence pool re-checked** vs ≥ 100 | if pool then fails → PARK → **program closes** |
| §1.5 PARK ∩ any later step | **first-FAIL stop** — later steps do not run | **program closes** |
| ENSG/MLI "promote to D" proposal ∩ any | **FORBIDDEN** — never-promotable; not a protocol path | would be new trial + screen override |
| §2a sign-golden FAIL ∩ §2b | **2a REJECTED** governs; 2b not computed | implementation fix, N unchanged, re-run from 2a |
| §2b primary magnitude (\|RankIC\| < 0.03 or sign ≤ 0) ∩ §2b p > 0.01 | **magnitude n-invariant REJECTED** governs (§9.0.3); p is reported | **program closes** |
| §2b primary magnitude FAIL ∩ §2b n < 100 (INSUFFICIENT) | **magnitude REJECTED** outranks sample-floor PARK when magnitude is computable at n ≥ 3; if n below computability, **INSUFFICIENT → PARK (power)** only | never rescale \|RankIC\| floor; **program closes** |
| **§2b primary PASS ∩ F2-BINDING PASS** | **continue to §2.3 / step 3** | sole remaining stop-rule survival path |
| **§2b primary PASS ∩ F2-BINDING FAIL** | **REJECTED (F2)** — mechanism attribution dead despite pooled in-hour drift (§9.0.4) | **program closes** |
| **§2b primary PASS ∩ F2-BINDING NEGATIVE** | **REJECTED (F2 NEGATIVE)** — hour decoration; :30 arm = **contaminated shelf** (§9.3) | **program closes**; shelf never cites to H9 |
| **§2b primary FAIL ∩ F2-BINDING PASS** | **REJECTED (F1 / primary 2b)** — magnitude/significance/tail kill; clock-binding substance held | **program closes** |
| **§2b primary FAIL ∩ F2-BINDING NEGATIVE** | **REJECTED (F1+F2)** — both arms kill | **program closes**; contaminated shelf |
| **§2b primary FAIL ∩ F2-BINDING FAIL** | **REJECTED (F1)** governs; F2 FAIL reported as non-NEGATIVE non-PASS | **program closes** |
| §2b ∩ F2-INSUFFICIENT (:30 n < 100) | **PARKED (evidence-infrastructure)** on the binding arm — primary 2b numbers reported but not treated as PROCEED | never rescale F2 n floor; **program closes** |
| §2b primary FAIL ∩ per-symbol diagnostic fail | **primary §9 row 2b REJECTED governs**; diagnostics cannot loosen | no magnitude/p safeguard (§2.2.2) |
| §2b primary PASS ∩ per-symbol SIGN-CONSISTENCY fail (JC-5, D only) | **primary 2b PASS stands**; failing symbol **leaves D**; pool re-checked vs ≥ 100 | cannot loosen / park / REJECT; acts only on a pass; if pool then fails → PARK → **program closes** |
| §2b PASS ∩ F2 PASS ∩ §2.3 edge anchor fail on all D symbols | **§2.3 PARK** (economics below floor) | D empty → **program closes** |
| §2b PASS ∩ §2.4 tick stratum kill | **REJECTED on affected stratum**; if D empties → PARK | survivors continue; D empty → **program closes** |
| §3 CPCV fail on one D symbol ∩ other D symbols pass | failing symbol **leaves D**; remaining D continues if non-empty | D empty → REJECTED → **program closes** |
| §4 F3 sign reversal ∩ §4 ≥2×2 miss | **F3 REJECTED (definition)** outranks hypothesis-revise | **program closes** |
| §5 DSR fail ∩ §3 CPCV pass | **REJECTED (honest-N)** — CPCV does not override DSR | **program closes** |
| §6 drift fail ∩ steps 1–5 pass | **HYPOTHESIS-REVISE** | Lei extraordinary path only; default program posture = closed pending ruling |
| §7 SURVIVES fail ∩ steps 1–6 pass | **TRAP-QUADRANT** (stat valid, exec invalid) | **program closes** |
| §7 LOW_N ∩ steps 1–6 pass | **PARKED (execution power)** — n-variant | **program closes** |
| §8 neighborhood fail ∩ §7 pinned SURVIVES | **TRAP-QUADRANT** (simulator-dependent) | pinned number is not a result; **program closes** |
| §8 non-neighborhood (25/100 ms) fail ∩ neighborhood PASS | **logged fragility** — not a kill | deployment review only |

### 9.2 Pass/fail matrix

One numeric criterion per step; the status each failure mode assigns.
**Trap-quadrant** is reserved for statistically-valid-but-execution-
invalid (spec §11(d) / research-workflow vocabulary).

| step | binding numeric criterion | on FAIL → status | n-class |
|---|---|---|---|
| 1 census | viable region non-empty on ≥ 1 D symbol AND pooled contamination-excluded in-hour episodes ≥ **100** across evidence pool D ∪ {ENSG, MLI} (after measured calendar-warm); `calendar_missing_rate = 0`; hour-subset derivation deterministic | **PARKED** (emptiness or power) → **program closes**; infra FAIL if calendars/derivation broken | n-variant (power/emptiness); infra n-invariant |
| 2a sign-golden | all seven assertions | **REJECTED** (sign/wiring defect; re-run after fix, N unchanged) | n-invariant (wiring) |
| 2b primary IC gate | in-hour extreme-OFI RankIC > 0, \|RankIC\| ≥ 0.03, p ≤ 0.01, n ≥ 100; bucket spread positive; tail t ≥ 2 — **pooled evidence pool** | **REJECTED** (F1 dead) → **program closes** | magnitude/sign **n-invariant**; p/n **n-variant** |
| 2b F2 binding | F2-S ∧ F2-D@1SE ∧ F2-R at :30 n ≥ 100 | **REJECTED (F2)** if FAIL/NEGATIVE co-fires with primary PASS → **program closes** | F2-S / F2-R / F2-D sign **n-invariant**; F2-D ≥1 SE **n-variant** |
| 2b sample floor | n ≥ 100 reachable on pooled in-hour extreme stratum; :30 n ≥ 100 for F2 adjudication | **PARKED (evidence-infrastructure)** if unreachable (JC-9: no primary-only PROCEED) → **program closes** — never threshold rescaling | n-variant |
| 2b→D sign-consistency (JC-5) | on 2b PASS: each D symbol own-boundary RankIC sign matches claim | failing symbol **leaves D**; pool recheck — **not** a park/reject of the card | deployability; acts only on pass; D members only |
| 2.3 edge anchor | measured conditional edge ≥ per-symbol single-stress floor on ≥ 1 D symbol (SELL: rider-inclusive) | **PARKED** (economics below floor everywhere) → **program closes** | n-variant |
| 2.4 tick tests | ≥ 4-tick stratum sign-consistent | **REJECTED on affected stratum** (grid artifact); if D empties → PARKED → **program closes** | n-invariant (sign) |
| 3 CPCV | paths **19** (APP/RMBS) / **9** ({OLN, DIOD, PCTY, CROX}); mean annualised path Sharpe ≥ 1.0; block-bootstrap p ≤ 0.05; embargo **2** (JC-1); per D symbol; cost-adjusted series; annualization √(12×252)≈55.0 | **REJECTED** (does not survive purged OOS reconstruction) → **program closes**; inability to form session-count groups → PARK (D-C2) | n-invariant (at commensurate annualization); group-form n-variant |
| 4 stratification | sign-stable + in-hour extreme-OFI RankIC ≥ 0.02 (p ≤ 0.05) in ≥ 2 vol × ≥ 2 spread strata (n ≥ 100 each) | **HYPOTHESIS-REVISE** (regime-fragile); F3 spread-tercile sign reversal in benign stratum ⇒ **REJECTED** → **program closes** | F3 n-invariant; 2×2 miss n-variant |
| 4.4 invariance | I-1 ratio ≤ 1.5 + companions; I-2 z ≤ 2; I-3 = F2 differential; IC(t) half-life ∈ [450, 1800] s | **HYPOTHESIS-REVISE** | mixed; I-1 fail ≈ n-invariant misattribution |
| 5 DSR | dsr ≥ 1.0, p ≤ 0.05, observed > noise ceiling at honest N | **REJECTED** (indistinguishable from max-of-N noise) → **program closes** | n-invariant at fixed N |
| 6 drift | all §6.1–§6.3 bounds | **HYPOTHESIS-REVISE** | n-variant |
| 7 execution | SURVIVES baseline + stressed; reconciliation (§7.2.3); fill-mix bounds | **TRAP-QUADRANT** if steps 1–6 passed → **program closes**; `LOW_N` ⇒ **PARKED (execution power)** → **program closes** | LOW_N n-variant; otherwise exec-axis |
| 8 grid | F4 clearance at all 27 neighborhood vertices + the inv12-stress point, every D symbol (full 81-cube reported; non-neighborhood failures = logged fragility) | **TRAP-QUADRANT** (simulator-dependent economics) → **program closes** | exec-axis |

**Tuning prohibition (binding, repeated):** converting any FAIL by
changing a parameter, threshold, window, stratum definition, calendar
lead/ε, hour-subset rule, or knob is prohibited within this trial. Any
such change is a **new trial**: increment N in the living ledger, log
the variant with its justification, and re-enter this protocol from
step 1 for the new variant. The one-way κ ratchet (spec §4.1)
additionally forbids upward re-estimation of any κ factor after data
contact. No post-park occupancy re-threshold is pre-authorized
(§1.7). Under the stop-rule, a parked/rejected primary **closes the
program** — a new trial is not an automatic continuation path.

### 9.3 F2 :30 firewall + never-promotable (spec §12.2 / Appendix P)

| direction | rule |
|---|---|
| **H13 → H9** | H13 evidence **never cites toward H9 revival**. An H13 **F2-BINDING PASS** strengthens H9's presumptive death. An H13 **F2-BINDING NEGATIVE** :30 arm is a **contaminated shelf** — diagnostic about a dead claim; not extraordinary justification for H9; not a KYLE attribution restore; **not reusable as confirmation evidence** for H9 or any future unclocked-OFI / half-hour card without Lei extraordinary review. |
| **H12 → H13** | H12's **power park** is trigger (a) activation only — not a magnitude prior, not an F2 result, not a κ/bar input. H12 F2 was **F2-INSUFFICIENT** (n = 89), not F2-NEGATIVE. No architecture prejudice transfers. |
| **H9 → H13** | H9 history **never prejudices H13 scoring**. |
| **ENSG/MLI → D** | **Never-promotable post-hoc** (§P.4 / §1.5). Evidence-only forever under this protocol. |

---

## 10. TRIAL LEDGER STATE AT PROTOCOL WRITE (Amendment F)

**N = 12** (pack-11 §(3) / spec §14; H12 park close-out left N = 12; no
outcome contact in Task 7 or this Task 8 write). The primary object of
this protocol is the slate-D ledger row "H13 primary:
ofi_integrated(1800 s) quintile × hour `ALGO_CLOCK` continuation,
H=1800, hl=900, passive, pooled six-symbol D (evidence pool +ENSG/MLI
for power)" — this protocol is its measurement plan, not a new trial.
Rows that increment **only on evaluation** (FQ-6B-R):

- the spec §14 drafted-not-evaluated variants (drop-OLN alt;
  session-relative OFI percentile; `hard_exit_age_seconds = 2700`;
  session-constant variations; re-thresholded conditioning);
- any post-hoc parameter change after a FAIL (forbidden within trial;
  if authorized by Lei as a new card, +1 N and re-enter from step 1 —
  stop-rule default = program closed).

Census-class evaluation (step 1) is N-neutral until first IC /
forward-return contact. **First outcome contact on the H13 primary
→ N ≥ 13.** The DSR of §5 uses the then-current N, never the written
12 if evaluations have occurred in between.

---

## 11. JUDGMENT CALLS AND RULINGS (Amendment F — 8-F pattern; RULED 2026-07-17, Task 8-F-H13, Lei)

Every residual numeric or instrument freedom, with the adopted
proposal and its alternative. **All twelve JCs are RULED
(2026-07-17); the per-JC ruling is recorded at the end of each entry
and the ruled text is applied in the named sections. This section is
the freeze record.**

**Pre-ruled by Lei (recorded, not a JC; STANDS):**

- Appendix P config **(B) FROZEN**; **(C) REJECTED**; zero ingestion.
- P.3 A-2.1 evidence-pool census floor ≥ **100** over
  D ∪ {ENSG, MLI}; CPCV/DSR/steps 3–8 D-scoped.
- ENSG/MLI evidence-only; **never-promotable** post-hoc.
- Frozen double expectation: in-window ≈ **96** / F2 arm ≈ **96** —
  expected PARK (power) and expected F2-INSUFFICIENT; census runs as
  measurement; projections never rescue and never condemn.
- D-C1: census floor = 100; design ≥ 130 = margin only.
- D-C2: CPCV session-count freeze (APP/RMBS 20/2/190/19; four 10/2/45/9).
- κ minimum-rule: freeze **0.172** (product 0.189; bug logged).
- Single-stress anchor; conjunctive IC (0.03 / p≤0.01 / n≥100
  pooled); F2-S ∧ F2-D@1SE ∧ F2-R; NEGATIVE requires affirmative t ≥ 2;
  stop-rule final card.
- N = **12**.

---

**JC-1 — Embargo bars (§3.1; Amendment A verify-not-assume).**
Proposed: `embargo_bars = 2` — arithmetic minimum 1 bar residual
(deepest lookback 1800 s OFI = label span; `scheduled_flow_window`
stateless) +1 NFC (rv-z count window + HMM on entry/gate path —
verified from spec §5.3). Alternative: carry **3** bars as
conservatism without nested-λ arithmetic (no nested λ on this card).
**RULING: APPROVED — 2 bars (lineage rule: ⌈lookback/bar⌉ + NFC when
gate consumers warrant). Applied in §3.1 / §3.3 / §9.2.**

**JC-2 — F2 differential margin numericization (§2.2.1 F2-D).**
Proposed: carry H12 — (in − :30) > 0 AND ≥ **1 SE** of the
difference, plus F2-R RankIC contrast > 0, plus F2-S (:30 ≤ 0 within
2 SE). Alternative A: ≥ 2 SE differential. Alternative B: RankIC
contrast alone.
**RULING: APPROVED as carried — mixed n-class labels kept (sign
n-invariant; ≥1 SE n-variant). Conjunction pinned: F2-BINDING PASS =
F2-S ∧ F2-D ∧ F2-R. Applied in §2.2.1 / §9.2.**

**JC-3 — F2-BINDING FAIL vs NEGATIVE split (§2.2.1 / §9.1).**
Proposed: carry H12 — NEGATIVE = :30 continuation-signed mean > 0
with t ≥ 2; FAIL = residual non-PASS non-NEGATIVE.
**RULING: APPROVED. Applied in §2.2.1 / §9.1.**

**JC-4 — Stratification spread axis (§4.1).**
Proposed: carry H8/H10/H12 JC-4 — **spread-in-ticks** per-symbol
terciles (task prose said `spread_z_30d`; H13 spec bans that sensor).
Alternative: fixed cross-symbol cutpoints (degenerate across D).
**RULING: APPROVED — spread-in-ticks; task prose overridden by the
spec ban, recorded. Applied in §4.1.**

**JC-5 — Per-symbol step-2 posture (§2.2.2).**
Proposed: carry H12 — no magnitude/p safeguard; PLUS sign-consistency
D-membership on primary PASS only (**D members only**; ENSG/MLI
excluded). Alternative: reintroduce A-2.1-class per-symbol
magnitude/p conjunct.
**RULING: APPROVED (D members only). Applied in §1.6 / §2.2.2 /
§9.1 / §9.2.**

**JC-6 — Drift bounds for exclusion screen (§6.1).**
Proposed: carry H12 adapted — screen-OFF ≤ 0.95; median ON dwell ≥
**1800 s** (one H=1800 horizon); always-ON not a failure.
Alternative: keep H12's 900 s dwell bound despite longer horizon.
**RULING: APPROVED (dwell ≥ 1800 s). Applied in §6.1.**

**JC-7 — Fill-mix / markout horizon (§7.2.4).**
Proposed: through-share ≤ 50 %; filled-minus-unfilled markout gap ≤
2.0 bps at **1800 s** (900 s alongside). Alternative: keep 900 s as
the binding markout gap despite H=1800.
**RULING: APPROVED (1800 s binding, 900 alongside). Applied in
§7.2.4.**

**JC-8 — CPCV per-split calibration regressor (§3.2).**
Proposed: `edge_scale_bps` ~ OLS of continuation-signed forward
return on spec §5.2 `excess`, through origin, clipped **[6.0, 18.0]**
(match free-range). Alternative: carry H12 clip [5.0, 14.0]
(tighter than free-range max 18).
**RULING: APPROVED — [6.0, 18.0] = free-range coincidence rule
recorded (clip is not an independent knob beyond the declared
free-range). Applied in §3.2.**

**JC-9 — F2-INSUFFICIENT consequence (§2.2.1 / §9.1).**
Proposed: carry H12 — :30 n < 100 ⇒ PARK evidence-infrastructure
(binding arm unadjudicable); primary 2b numbers reported but not
PROCEED; **program closes**. Alternative: allow primary-only PROCEED
with F2 reported as INCONCLUSIVE (weakens load-bearing F2; conflicts
with stop-rule spirit).
**RULING: APPROVED — F2-INSUFFICIENT → PARK; program closes. Applied
in §2.2.1 / §9.1 / §9.2.**

**JC-10 — Calendar-warm + hour-subset derivation determinism
(§1.1).**
Proposed: per (symbol, session) warm fraction = share of in-window
h=1800 boundaries with `scheduled_flow_window.warm == True` under the
hour-only derived view; pooled episode count re-scored after
measurement; warm < 0.5 on > 2 sessions drops that symbol from D;
`calendar_missing_rate > 0` ⇒ infrastructure FAIL; **hour-subset
derivation bit-identity** is a census precondition (identical
derived-view hashes on rerun; `:30` excluded from injection).
Alternative: warm = share of RTH seconds inside authored windows.
**RULING: APPROVED — boundary-based estimand + hour-subset
derivation determinism as census precondition. Applied in §1.1 /
P0-4.**

**JC-11 — IC(t) half-life window (§4.4).**
Proposed: t ∈ {300, 900, 1800, 3600} s; fitted half-life ∈
**[450, 1800] s** (declared hl = 900 ± factor of 2). Alternative:
t ∈ {120, 300, 900, 1800} with band [450, 1800] (shorter probe grid).
**RULING: APPROVED — t ∈ {300, 900, 1800, 3600}; band [450, 1800].
Applied in §4.4 / §9.2.**

**JC-12 — Primary RankIC pool scope (§2.2.0).**
Proposed: conjunctive IC n / RankIC / p / tail scored on the
**eight-symbol evidence pool** (aligned with A-2.1 census floor);
D-only sub-totals always reported; JC-5 sign-consistency and §2.3
edge anchor remain D-scoped. Alternative: primary RankIC D-only
(stricter; expected n ≈ 88.5 under honesty rider ⇒ near-certain
INSUFFICIENT even if evidence pool clears).
**RULING: APPROVED — evidence-pool primary; D-only sub-totals
reported; JC-5 / §2.3 D-scoped. Rationale recorded: P.3 couples the
park floor to the evidence pool *because* step 2 adjudicates on it —
the primary RankIC sample floor is the same estimand. Applied in
§2.2.0.**

---

## 12. FREEZE DECLARATION

Steps are order-locked (§0); the census (step 1) executes only after
this freeze commit **and** P0-1 Phase-A deliverables are green; steps
7–8 execute only under P0-6. The §11 rulings landed 2026-07-17
(Task 8-F-H13, Lei) and are applied in §1 (double expectation; D-C1 /
D-C2), §1.1, §2.2.0, §2.2.1, §2.2.2, §3.1, §3.2, §3.3, §4.1, §4.4,
§6.1, §7.2.4, §9.1, and §9.2. The §9.1 matrix is freeze-clean under
backlog-13 (zero undefined intersections). This document is
**PRE-REGISTERED — FROZEN as of the Task 8-F-H13 commit
(2026-07-17)**. From this commit, all changes go in an `AMENDMENTS`
section appended below this line, each entry carrying a timestamp
and justification.

*Protocol frozen — Phase A / Task 9 (implementation) may begin under
P0-1.*

---

# AMENDMENTS

## A-1 — Phase-A IMPLEMENTATION RECORD (Task 9-A-H13, 2026-07-18)

**Scope.** Phase A only (Ordering B): hour-only calendar derivation +
`ofi_integrated_percentile` h=1800 pin + census instrument + harness IC
row. **No census execution, no IC numbers, no outcome contact.** Phase B
explicitly out of scope. **N = 12 survives unchanged** (living ledger;
first outcome contact still reserved for step-2 IC on the H13 primary
→ N ≥ 13).

### Commit ledger

| # | sha | delivered |
|---|---|---|
| 1 | `989ab39` | Hour-only derived calendar view — deterministic `:00` SUBSET of committed `ALGO_CLOCK` YAMLs (`scripts/research/derive_hour_only_algo_clock_calendars.py`); `:30` excluded from injection; bit-identity census precondition in `tests/sensors/test_hour_only_algo_clock_derivation.py`. Committed calendars untouched. Coverage map: derive script → `research_validation`. |
| 2 | `4aff50f` | `ofi_integrated_percentile` at h=1800 pinned (factory already multi-h; H13 consumption lock + bootstrap comment). Determinism suite green — **no locked parity baseline moved**. |
| 3 | `6bef718` | Census instrument `scripts/research/hour_checkpoint_drift_census.py` (frozen §1.1 predicate **both arms**; eight-symbol evidence pool; JC-10 calendar-warm under hour-only view; JC-1 leakage / co-travel / tranche1b_kappa_drift REPORTS; σ₁₈₀₀ vs floors) + synthetic-fixture golden pinning both arms at build time incl. ENSG/MLI evidence-only cells (`tests/scripts/test_hour_checkpoint_drift_census.py`). Coverage map: census → `research_validation`. |
| 4 | (this commit) | Harness IC row in `scripts/sensor_feature_ic.py` — H13 hour-stratified `in_hour_extreme` / `halfhour_extreme` / `hour_contrast` at h=1800 under hour-only injection; ENSG/MLI included (JC-12 evidence-pool primary); additive only; synthetic smoke tests in `tests/scripts/test_sensor_feature_ic.py`. This IMPLEMENTATION RECORD. |

### Gate battery (each commit independently green; PYTHONHASHSEED=0)

| gate | commit 1 | commit 2 | commit 3 | commit 4 |
|---|---|---|---|---|
| `pytest -m "not functional and not slow"` | 4127 passed, 9 skipped | 4128 passed, 9 skipped | 4138 passed, 9 skipped | 4140 passed, 9 skipped |
| `mypy src/feelies` (strict) | clean (194 files) | clean | clean | clean |
| `ruff check src/ tests/` (+ scripts touched) | clean | clean | clean | clean |
| `tests/docs/test_prompt_coverage_map.py` | green (scripts row) | green | green (scripts row) | green |
| determinism / locked baselines | n/a (no src factory change) | **no baseline moved** | n/a | n/a |

### Coverage-map ownership rows

| artifact | owner |
|---|---|
| `scripts/research/derive_hour_only_algo_clock_calendars.py` | `research_validation` (`docs/prompts/README.md` scripts row) |
| `src/feelies/bootstrap.py` (`ofi_integrated_percentile` comment only) | `audit_kernel` (pre-existing root-module owner; unchanged) |
| `scripts/research/hour_checkpoint_drift_census.py` | `research_validation` |
| `scripts/sensor_feature_ic.py` (H13 row additive) | `sensor` (pre-existing scripts-row owner; unchanged) |

### Explicit non-actions (binding)

- Census **not executed** against the 140-cell evidence-pool grid
  (instrument + golden pin only).
- No forward return / RankIC / CPCV / DSR / outcome statistic computed
  on cached L1.
- No Phase-B alpha YAML, `configs/bt_sig_hour_checkpoint_drift_h1800_v1.yaml`,
  or sign-golden evaluate module.
- Locked parity baselines / promotion ledger / core event schemas
  untouched.
- **N = 12** at close of Phase A (unchanged).

### P0-1 status after this amendment

| deliverable | status |
|---|---|
| (i) hour-only calendar derivation (`:00` subset; `:30` excluded) | **landed** (`989ab39`) |
| (ii) `ofi_integrated_percentile` at h=1800 | **landed** (`4aff50f`) |
| (iii) census instrument (both arms; eight-symbol pool) | **committed** (`6bef718`) — not run on cache |
| (iv) harness IC row (both F2 arms) | **landed** (this commit) — not run on cache |

**Stop for Lei review before any census execution (step 1).**

*(Record appended 2026-07-18. Justification: Task 9-A-H13 Phase-A
close-out; instruments built and pinned; no freeze-body edit.)*
