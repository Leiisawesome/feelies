<!--
  File:   docs/research/sig_halfhour_clock_drift_h900_v1_validation_protocol.md
  Status: PRE-REGISTERED — FROZEN (Task 8-F-H12, Lei, 2026-07-17).
          STEP 1 PARK — power (pooled viable-region in-window
          episodes = 59 < 100); F2-arm F2-INSUFFICIENT (out-window
          viable-region n = 89 < 100) reported per JC-9. N = 12
          (census N-neutral; no outcome contact).
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8 / Task 8-C-H12 (H12).

  Provenance (FQ-3 — Task 8-C-H12 census execution):
    git_sha: "8708c3c39155cc203982412d0ffb7539a5c76cbc"
      (HEAD at census start; Phase-A commit-4 pin)
    worktree_clean: "yes for tracked tree; formal_spec.md remains
      untracked sibling (freeze-provenance allowance)"
    pythonhashseed: "0"
    host: "CHENGLEI-L-3 / Windows-11-10.0.26200-SP0 /
      Python 3.14.2 (MSC v.1944 64 bit AMD64)"
    artifact_sha256:
      "3d0783bf60afb4ca94c857690c0237dc7c742daba8494af89938714722bbf5a3"
      (docs/research/artifacts/halfhour_clock_drift_census_2026-07-17.json;
       LF-canonical; bit-identical re-run matched)
    normative_inputs: frozen protocol §1 (this file) + Phase-A
      instruments (2f3d930 / aea0578 / ec78718 / 3cf4413 / 8708c3c)
      + 03c grid.
-->

# `sig_halfhour_clock_drift_h900_v1` — pre-registered validation protocol (Task 8)

This protocol fixes, numerically and in execution order, every test the
candidate must pass — **before** any implementation exists and before
any outcome statistic is computed. It binds Task 8 (measurement),
Task 9 / Phase B (implementation), and the Task-12-gated execution
overlay. The frozen H2, H8, and H10 protocols (incl. all rulings) are
the **structural template** (task Amendment A): locked order,
single-stress anchor, conjunctive-IC rationale, CPCV dual reporting,
27-vertex+stress sensitivity pass set, ±5 % reconciliation
numericization, latency axis, n-invariant/n-variant labels on every
criterion, and a precedence walk with zero undefined intersections.
**Only what H12 changes is re-derived** (embargo arithmetic §3.1 —
verified not assumed against H10's 3-bar prior; census / F2 two-arm
machinery §1–§2; Phase-A calendar deliverables) — arithmetic shown
inline. Annualization √(25×252) ≈ 79.37 and CPCV 20/2/190/19 are
**carried** per-symbol in D (Amendment A).

**Freeze rule.** This file is **PRE-REGISTERED — FROZEN** as of the
Task 8-F-H12 commit (2026-07-17). It is immutable except for an
appended `AMENDMENTS` section (timestamp + justification per entry).
Converting any FAIL below by tuning is prohibited: **any post-hoc
parameter change is a new trial — N increments and the change is
logged in the ledger (§10) before the re-run.** Simulator-knob
perturbations inside the pre-registered §8 grid do not increment N
(the grid's pass criterion is conjunctive — it can only reject); any
change to alpha-side parameters (`ofi_percentile_min`,
`edge_scale_bps` outside the §3 calibration procedure, `edge_cap_bps`,
gate thresholds, exit ages, session constants, calendar lead/ε,
quintile split, `w_hh` used as a tuned occupancy) does.

**Two validity axes, never conflated (session constraint 5).** Steps
1–6 establish *statistical* validity on pre-cost / disclosure-
arithmetic quantities; steps 7–8 establish *execution* validity on the
Task-12-parity-cleared machinery. No number from steps 1–6 is ever
presented as an economic result, and no number produced before the
Task-12 router timing-parity check is presented as a result at all.

**Evidence set (closed; pack-11 DISPOSITIONS 4 / spec §4.3).** Symbols
**{APP, RMBS}** × the **20-session** 03c grid (10 preamble + 10
Lei-ratified expansion dates per 03c AMENDMENT 1):

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
NO role** in H12 evidence. **OLN × the 10 preamble dates** is added
evidence-only for the §2.4 tick-artifact tests; it is excluded from
deployable economics, CPCV, DSR, and the execution overlay. The 03c
limitations L1–L5 attach verbatim to every calm / elevated-A /
elevated-B conclusion.

**Units (00b, THE CONVENTION).** Every edge and cost figure below is
**one-way, per-fill, in bps of fill notional** unless explicitly
marked round-trip-derived.

**N = 12** at protocol write (pack-11 / spec §14; slate-D ledger; no
outcome contact). First outcome contact on the H12 primary →
**N ≥ 13**.

---

## 0. PRECONDITIONS (verified before step 1 executes)

| # | precondition | status at protocol write |
|---|---|---|
| P0-1 | Phase-A deliverables landed (Amendment E / spec §16) | **REQUIRED BEFORE step 1 or step 2 executes**: (i) `WindowKind.ALGO_CLOCK` taxonomy + per-session half-hour calendar YAMLs for every operative {APP, RMBS} date; (ii) `ofi_integrated_percentile` factory wiring at h=900; (iii) census instrument committed (both arms); (iv) harness IC row landed on the census-pinned predicate (both F2 arms). Until then steps 1–2 are blocked. See §1.0 / §2.1 / §2.2 Phase-A assignment rows. |
| P0-2 | Grid inputs CLEARED | 03c FQ-6A-R re-check table: CLEARED 2026-07-11; expansion AMENDMENT 1 ratified; Tranche-1B out of scope for this card |
| P0-3 | Realism profile pinned | 00c profile at commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`; configs with `backtest_fill_latency_ns == 0` are invalid for evidence |
| P0-4 | Determinism discipline | every scripted run: `PYTHONHASHSEED=0`, direct `DiskEventCache` read (`~/.feelies/cache`), replay through the real pipeline; provenance (git SHA, command line, artifact SHA-256) recorded per run; bit-identical re-run required for the census artifact (H2 C.7 / H8 C.8 / H10 C.7 precedent); **window-authoring determinism** verified as a census precondition (identical calendars on rerun — §1.1) |
| P0-5 | Step-1 census executes only after this file is FROZEN (post-§11 rulings) and committed | **FROZEN 2026-07-17** (Task 8-F-H12); census still waits on P0-1 |
| P0-6 | Task-12 router timing-parity (steps 7–8 gate) | **AXIS-1 VERIFIED 2026-07-12** (`prompt_pack_12p_router_fill_timing_parity.md`; regression guards committed). Re-verified green at step-7 execution time; any AXIS-1 regression re-opens the gate. |

Execution order is **locked**: 1 → 2 → 3 → 4 → 5 → 6 → (7 → 8) with
steps 7–8 additionally gated on P0-6. A step does not begin until the
prior step's outputs are committed. A park/reject at any step halts
the sequence.

---

## 1. STEP 1 — PARK-RULE CENSUS (spec §4.2–§4.4 / Amendments B–D)

Offline deterministic scan of the closed **40-cell** {APP, RMBS} ×
20-date grid (OLN × 10 preamble added evidence-only for §2.4 inputs).
**NO forward returns are computed anywhere in this step** — the only
return-like quantity permitted is the *unconditional* session
volatility σ₉₀₀ (std of non-overlapping 900 s mid log-returns over
RTH, in bps), which conditions on nothing signal-related.

### 1.0 Phase-A assignment (Amendment E — H10 §-assignment pattern)

| deliverable | owner section | status at protocol write |
|---|---|---|
| **`WindowKind.ALGO_CLOCK` + per-session calendars** (twelve half-hour `[M, M+1s)` windows; exchange-schedule authoring only) | §1.1 / spec §1.5 — artifact target `src/feelies/storage/reference/event_calendar/<YYYY-MM-DD>.yaml` | **not yet implemented** — protocol freezes the authoring rule and warm-iff-calendar semantics before artifacts exist |
| **`ofi_integrated_percentile` factory wiring** at h=900 | §2.1 (sign-golden requires it) + spec §1.2 | Phase A; blocked until landed |
| **Census instrument** (deterministic offline pass; PYTHONHASHSEED=0; **both arms**) | this §1 — script target `scripts/research/halfhour_clock_drift_census.py` (Task-9-adjacent / Phase-A) | **not yet implemented** — protocol freezes the predicate and park bars before the instrument exists |
| **Harness IC row** (in-window primary + out-window matched-OFI arm) | §2.2 | Phase A; blocked until landed |

### 1.1 Episode definition — the entry predicate EXACTLY (Amendment D)

An **eligible in-window boundary (= one primary episode)** is an
h=900 `HorizonFeatureSnapshot` boundary satisfying ALL of the
following (spec §1.4 / §5.2–§5.3 / card conditional-distribution
statement — **no threshold freedom**):

1. session window: boundary inside the **09:35–15:50 ET** in-window
   (spec §1.4: `no_entry_first_seconds: 300`,
   `session_flatten_seconds_before_close: 600`) on the nominal
   `boundary_ts_ns` — **25 boundaries / session** by construction
   (pack-08 / 11a §1 actuals bit-exact);
2. required entry-warm ids warm and not stale:
   `{scheduled_flow_window_active, ofi_integrated_percentile,
   ofi_integrated, realized_vol_30s_zscore}` (spec §1.3
   consume-driven set);
3. **clock predicate:** `scheduled_flow_window_active ≥ 0.5`
   (`W_hh = 1` — boundary inside a registered `ALGO_CLOCK`
   half-hour window);
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

**Matched out-window contrast episode (F2 arm — census counts only;
no forward return):** same arms 1–2 and 4–7 with arm 3 inverted:
`scheduled_flow_window_active < 0.5` (`W_hh = 0` — off-clock
15-minute marks on the same H = 900 grid). Design-central population
≈ **160.1** (13 × 20 × 2 × HT × quintile × gw; spec §1.6).

Pipeline pins: RTH filter 09:30 ≤ t < 16:00 ET on
`exchange_timestamp_ns`; events sorted by `(timestamp_ns, sequence)`;
reference `platform.yaml` sensor params for existing sensors;
`scheduled_flow_window` calendar injected at construction
(`EventCalendar`); h=900 features from the production factories once
Phase-A wiring lands; fresh sensor/regime state per session.

**Calendar-warm measurement (Amendment D — replaces ASSERTED values).**
The census **measures**, per (symbol, session):

- `calendar_warm_fraction` = share of in-window h=900 boundaries with
  `scheduled_flow_window.warm == True`;
- `calendar_missing_rate` = share of in-window boundaries with
  `warm=False` due to missing/empty calendar;
- joint conditioning occupancy at the frozen thresholds above
  (in-window and out-window arms separately).

ASSERTED design priors (gate×warm 0.90 × 0.95; design-central 147.7 /
160.1) are **resolved by measurement** — never tuned. If measured warm
drives the pooled contamination-excluded in-window episode count
below the §1.5 park floor → **PARK on power** (no threshold / prior
tuning). **Warm-coverage drop rule (coverage-not-tuning):** warm
fraction < 0.5 on > 2 sessions ⇒ that symbol drops from D.
`calendar_missing_rate > 0` after artifacts land → **infrastructure
FAIL** (not an edge fail; P0-1 defect).

**Window-authoring determinism (census precondition):** re-running
calendar authoring under `PYTHONHASHSEED=0` on the same exchange
schedule must produce bit-identical YAML content / `EventCalendar.hash`
per date. Mismatch ⇒ infrastructure FAIL; census does not proceed.

### 1.2 Frozen viable-region definition (numeric, before execution)

κ = **0.146, FROZEN** (spec §4.1; one-way ratchet — revisable down on
evidence, never up; superseded entirely by the measured conditional
edge once step 2 has run).

**κ minimum-rule (Amendment B / spec §4.1 — recorded):** on any
discrepancy between the stated freeze and the factor product, take
`κ = min(stated, product)` and log the gap. H12 product =
1.15 × 0.52 × 0.50 × 0.75 × 0.65 = **0.1458375 ≈ 0.146** — **no
discrepancy**; freeze stands at **0.146**.

Per-symbol single-stress floors (spec §4.2, 8-F §11.1 anchor, one-way,
per-fill, bps of fill notional):

| symbol | floor = 2.25 × (2.0 + fee) (bps) | σ₉₀₀ min = floor/κ (bps) | short rider-incl. floor (bps) |
|---|---|---|---|
| APP  | **4.68** | **32.05** | **5.82** |
| RMBS | **5.51** | **37.74** | **6.60** |

A (symbol, session) cell is **in the viable region** iff its realized
session σ₉₀₀ ≥ the symbol's σ₉₀₀ min. σ₉₀₀ estimator (recorded, not
tuned; H2/H8/H10 C.2 convention at H = 900): Bessel-corrected sample
std of non-overlapping 900 s mid log-returns on the 09:30-anchored
grid (last-mid-at-or-before sampling, ~26 raw RTH returns/session
before session-discipline trim), in bps. SELL-leg viability uses the
rider-inclusive short floor column (spec §4.2).

### 1.3 Contamination handling (Amendment B; H10/H8 JC-1 estimand split carried)

Entry conditioner is **quote-fed** (`ofi_integrated`) × **calendar
membership** (spec §1.7). Class-B prints never enter `ofi_raw`. No NEW
trade-fed extreme. Contamination-excluded multiplier = **1.0 at
design**.

**Census EXCLUDES (binding primary count):** nothing beyond the
predicate of §1.1 — the primary in-window episode count IS the §1.1
predicate count. No post-hoc intensity or binary exclusion is applied
to the primary power number.

**Estimand split (H10 JC-1 / H8 precedent carried — Amendment B):**

| estimand | definition | binding? |
|---|---|---|
| **leakage** | share of primary eligible boundaries whose trailing-900 s OFI integrand path includes quote events that the production `ofi_raw` path would have dropped as degenerate/crossed (should be ≈ 0 by construction) | **REPORT only**; share **> 1 %** ⇒ **sensor-bug investigation trigger** — never a park, never a power deflator |
| **co-travel** | `off_clock_cotravel_rate` = share of quintile-OFI in-window-eligible-class boundaries that are off-clock (geometry diagnostic; design ≈ 0.52 by §1.6) | **REPORT only** — **not leakage**; never a park |

**No-double-exclusion rationale:** H8 required intensity exclusion
because `kyle_lambda_60s` ingested unfiltered trade prints. H12's
entry conditioner is quote-fed × calendar — applying a trade-flag
exclusion would invent a contamination mechanism the conditioner does
not ingest.

**Census REPORTS (diagnostic only, never binding on park):**

- leakage share + > 1 % flag (above);
- `off_clock_cotravel_rate` (geometry, not leakage);
- `calendar_missing_rate` (infrastructure);
- measured in-window / out-window episode counts vs design-central
  147.7 / 160.1.

### 1.4 Census outputs (all per symbol × session × daily stratum)

- eligible in-window episode counts (§1.1), split LONG / SHORT —
  SHORT feeds the long-only restatement rule (§1.6);
- matched out-window contrast episode counts (F2 arm);
- measured calendar-warm coverage per session (ASSERTED→measured
  resolution); coverage drop rule applied; `calendar_missing_rate`;
- leakage / co-travel REPORTS (§1.3);
- realized session σ₉₀₀ (bps) and viable/non-viable labels (long floor
  and short rider-inclusive separately);
- (intraday gate state × daily stratum) 2×2 boundary table;
- spread-in-ticks distribution at eligible in-window boundaries AND
  at all warm in-window boundaries, per symbol incl. OLN (§2.4 / §4
  inputs);
- per-stratum episode counts for elevated-A / elevated-B / calm (L4:
  A and B reported separately, never pooled);
- calendar-authoring determinism hash per date (precondition).

### 1.5 Park conditions (Amendment B — D-C1 carried)

**Card→protocol deviation (D-C1; logged, never silent):**

| # | card / design | this protocol | why |
|---|---|---|---|
| D-C1 | pooled ≥ **130** contamination-excluded episodes (30 % design margin over ≥ 100); design-central **147.7** | census park floor = pooled ≥ **100** contamination-excluded in-window episodes across {APP, RMBS} | Lei Amendment B / H10 D-C1: ≥ 130 / 147.7 are the **design margin / design-central projection**, not the census bar; ≥ 100 is the census floor (H8/H10 park precedent). |

Park conditions — **either parks the card** before any IC outcome is
treated as a PROCEED:

1. **Edge-region emptiness:** for every deployable symbol, the viable
   region contains zero primary in-window eligible episodes → **PARK**.
2. **Power floor (pooled):** pooled contamination-excluded primary
   in-window episodes across {APP ∪ RMBS} (viable-region restricted)
   **< 100** — including after calendar-warm measurement replaces
   ASSERTED priors → **PARK on power**. No threshold / prior tuning.
3. **Infrastructure:** `calendar_missing_rate > 0` after Phase-A
   artifacts land, OR window-authoring determinism fail →
   **infrastructure FAIL** (halt; not an edge park; fix and re-run,
   N unchanged).

**Axis split (Amendment B; card block-3 / H10 carry):** a
**single-symbol shortfall** inside the pool parks **nothing** by
itself, **unless** that symbol also fails **deployability park
arithmetic** (edge-region emptiness on that symbol, the §1.6 rider /
coverage drop, or — on a primary 2b PASS only — the §1.6 / §2.2.1
SIGN-CONSISTENCY D-membership condition), in which case it drops from
D and the **pool is re-checked** against ≥ 100 on the remaining
symbols. Undefined intersection = freeze-blocking defect (§9
precedence).

**n-class labels (Amendment A / 3-M):** park condition 1
(edge-region emptiness after measured σ) is **n-variant** → PARK
evidence-infrastructure when empty on all symbols. Park condition 2
(pooled < 100) is **n-variant** → PARK on power. Neither is a
magnitude REJECTED. Infrastructure FAIL is **n-invariant** wiring.

### 1.6 Deployable-set restatement rules (pre-registered; JC-5 carried)

The census fixes **D** and the pool:

- **D = {symbols that clear deployability}**: edge-region non-empty
  under long floor (and short rider if two-sided claim retained);
  warm-coverage drop rule not fired; calendars present.
- **RMBS long-only restatement:** if RMBS fails the SELL-leg axis
  (κ·σ₉₀₀ or measured short edge vs rider-inclusive floor 6.60 bps),
  RMBS restates **long-only** and its contribution to the pooled
  power count is the continuation-long episode count alone; D
  membership re-checks.
- **SIGN-CONSISTENCY D-membership (JC-5 carried, deployability class;
  fires only on a primary §2b PASS):** each symbol then in D must
  show own-boundary in-window extreme-OFI RankIC **sign matching the
  claim** (continuation-positive). Fail ⇒ that symbol **leaves D**;
  pooled power axis-split recheck vs ≥ 100 on remaining D. **No
  magnitude bar, no p bar;** cannot loosen a primary fail, cannot
  park the card, cannot REJECT — acts only on a pass (conflict with
  §9 row 2b impossible by construction). See §2.2.1 / §9.1.
- **Symbol fails deployability ⇒ drops from D**; pool re-checks
  ≥ 100 on remaining D. Pool failing after drop → PARK.
- **Both symbols fail deployability ⇒ PARK** regardless of raw
  counts.
- OLN is never in D.

### 1.7 Post-park path

**No occupancy re-threshold variant is pre-authorized for H12.** The
quintile split (0.80 / 0.20) and half-hour `W_hh` membership ARE the
mechanism claim, not tuning axes; calendar-warm is measured, not
re-fit; decile alt is drafted-not-authorized (spec §14). A park on
power or emptiness stops for Lei review. Any subsequent variant
requires Lei's explicit approval with reasons and is a new ledger row
(N-neutral until outcome contact; first IC contact +1 N). Iterative
occupancy fishing is prohibited.

**H13 contingent (pack-11 DISPOSITIONS 2 — recorded, not authorized):**
census / design death → trigger **(a)** ACTIVATES H13 under its own
protocol (κ frozen 0.172 minimum-rule; pool-collapse floors must be
frozen before any H13 census). This H12 protocol does not authorize
H13 instruments.

### 1.8 Post-park path after PROCEED

On census PROCEED: D and the measured warm / occupancy / arm counts
are pinned; step 2 begins only under P0-1 green and this file frozen.

---

## 2. STEP 2 — SIGN-GOLDEN + IC GATE (ENG-3 precedent, gas_01/gas_02)

Per the repo's own promotion policy (engine-readiness ENG-3, as
exercised in `docs/research/gas_01_integrated_ofi.md`): **no promotion
of the signature without BOTH (a) and (b).**

**H12 novel machinery (Amendment C — FROZEN COMPLETELY):** step 2b is
a **two-arm design** — (i) **in-window primary gate** (pooled
RankIC / p / n bars at the frozen numbers below) **AND** (ii) the
**window-binding contrast** (out-window matched-OFI arm at design
~160 boundaries) with its own numeric criterion and §9 consequence.
Every intersection of primary × binding outcomes is declared in §9.1
so trigger-(b)/(c) are *implied by the frozen rows*, not adjudicated
later. The out-window arm's firewall status (contaminated for any
future H9-class use if it shows continuation) is recorded in §2.2.2 /
§9.3.

### 2.1 (a) Sign-golden through the REAL pipeline

**Phase-A assignment (Amendment E):** requires `ALGO_CLOCK` calendars +
`ofi_integrated_percentile` wiring + `scheduled_flow_window` calendar
injection. New test module
`tests/research/test_gas_halfhour_clock_drift_sign.py` (Phase A /
Task 9 implements; assertions fixed here).

Synthetic tape with known ground truth pushed through the real
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (the
gas-01 pattern):

1. **In-window continuation golden (LONG):** a synthetic tape whose
   trailing 900 s window is dominated by buy-side quote-flow so that
   at an h=900 half-hour mark boundary `ofi_integrated > 0`,
   `ofi_integrated_percentile ≥ 0.80`, and
   `scheduled_flow_window_active ≥ 0.5` ⇒ the §5.2 draft `evaluate`
   (once implemented) emits direction **LONG** — trade WITH the
   clock-bound OFI extreme.
2. **Mirror golden (SHORT):** the same tape mirrored ⇒
   `ofi_integrated < 0`, percentile ≤ 0.20, `W_hh = 1` ⇒ SHORT.
3. **Clock-null golden (THE card-defining assertion):** the same
   absolute OFI extremity but `scheduled_flow_window_active < 0.5`
   (off-clock mark) ⇒ `evaluate` returns **None** — no signal without
   the clock predicate. This is F2 in golden form.
4. **Interior-null golden:** `W_hh = 1` but percentile interior to
   (0.20, 0.80) ⇒ `evaluate` returns **None**.
5. **Calendar-cold golden:** empty/missing calendar ⇒
   `scheduled_flow_window` not warm ⇒ entry suppressed
   (warm-iff-calendar, spec §1.3).
6. **Sign-disagreement golden:** percentile ≥ 0.80 but
   `ofi_integrated ≤ 0` (or mirror) ⇒ `evaluate` returns **None**
   (spec §5.2 sign agreement).
7. **h=900 key-presence golden:** the snapshot at h=900 carries the
   consumed entry ids including `ofi_integrated_percentile` and
   `scheduled_flow_window_active` (factory / calendar wiring
   regression lock, P0-1).

Any assertion failure ⇒ **REJECTED (sign/wiring defect)** — fix is an
implementation correction, not a tuning event (N unchanged), but the
gate must re-run from scratch. Census-consistency smoke (Phase B
mismatch after YAML lands): implementation-correction re-run, N
unchanged (spec §16).

### 2.2 (b) RankIC evidence — two arms; thresholds and sessions fixed now

**Phase-A assignment (Amendment E):** harness IC row on the
census-pinned predicate — `scripts/sensor_feature_ic.py` extended
with an H12 row (Phase A implements; measurement plumbing for the
pre-registered primary trial, not a new trial). Sensors:
`scheduled_flow_window` (calendar-injected), `ofi_raw` (1.0.0),
`realized_vol_30s` (1.3.0) at reference params; features = consumed
ids at h = 900; each warm boundary paired with the forward mid
log-return over the snapshot horizon; statistics via
`research/forward_ic.py` (`spearman_ic`, `bucketed_forward_return`,
`long_short_edge_bps`).

**IC variable (fixed now — conditional clock×OFI hypothesis):** the
primary IC pair is `x = ofi_integrated` (signed) vs `y` = signed
forward 900 s mid log-return, computed **within the in-window
extreme-OFI stratum** (`W_hh = 1` AND percentile ≥ 0.80 OR ≤ 0.20,
with continuation sign matching OFI sign).

**Sessions (named now, the closed set):** the 40 cells {APP, RMBS} ×
the 20 dates above. **Primary evidence = pooled {APP ∪ RMBS}** over
viable-region sessions. Contamination handling per §1.3 (primary =
predicate-clean; REPORTS alongside).

#### 2.2.0 In-window primary gate (ALL required, at h = 900) —
conjunctive-IC rationale carried verbatim from 8-F / H10

| criterion | threshold | n-class |
|---|---|---|
| in-window extreme-OFI pooled RankIC sign | > 0 (continuation-correct) | **n-invariant** (sign) |
| in-window extreme-OFI pooled \|RankIC\| | ≥ **0.03** | **n-invariant** (magnitude) |
| in-window extreme-OFI pooled significance | Fisher-z two-sided p ≤ **0.01** | n-variant (p) |
| pooled sample minimum | n ≥ **100** warm boundaries in the in-window extreme-OFI stratum pooled over {APP ∪ RMBS} viable-region (else INSUFFICIENT). Feasibility: design-central ≈ **147.7** (spec §1.6); H8's n ≥ 1,000 is **unreachable by construction** at H = 900. Floor aligned to research-protocol ~100 and the §1.5 census floor. Unreachable ⇒ PARK evidence-infrastructure, never magnitude rescaling. | **n-variant** (power) → PARK evidence-infrastructure if unreachable after measurement, never magnitude rescaling |
| bucket monotonicity | `bucketed_forward_return` (5 equal-count buckets of x, in-window extreme stratum): top-minus-bottom forward-return spread positive in the continuation direction | **n-invariant** (sign) |
| conditional tail (F1 anchor) | mean continuation-signed 900 s forward return on primary in-window eligible episodes > 0 with t ≥ 2 pooled over {APP ∪ RMBS} | **n-invariant** on sign; t is n-variant |
| per-symbol diagnostics | RankIC \|RankIC\|, n, p reported per symbol — magnitude/p **NON-GOVERNING**; sign feeds §2.2.1 SIGN-CONSISTENCY D-membership on a primary 2b PASS only | magnitude/p diagnostic; sign → D on pass |

The criteria are **deliberately conjunctive** (8-F ruling, carried
verbatim): the p ≤ 0.01 bar binds at moderate n, and the
|RankIC| ≥ 0.03 floor rejects effects that are trivial-in-magnitude
yet significant at huge n. Neither alone is sufficient.

**Primary 2b PASS** ⇔ all rows of §2.2.0 clear. **Primary 2b FAIL** ⇔
any magnitude/sign/tail/bucket row fails (n-invariant REJECTED path)
or p fails after n ≥ 100 (reported; magnitude outranks when both
fail — §9.1). n < 100 with magnitude uncomputable ⇒ INSUFFICIENT →
PARK (power), never REJECTED on magnitude.

#### 2.2.1 Window-binding contrast — out-window matched-OFI arm
(Amendment C — FROZEN; F2 load-bearing)

**Population (fixed now):** matched OFI-quintile episodes with
`W_hh = 0` on the same closed 40-cell grid, viable-region restricted,
same gate/vol-z/sign-agreement arms as §1.1 with clock inverted.
Design-central ≈ **160.1**; adjudication requires measured
out-window n ≥ **100** (else **F2-INSUFFICIENT** → PARK
evidence-infrastructure on the binding arm — **JC-9 APPROVED**: no
primary-only PROCEED; never auto-REJECT on mechanism, never
magnitude rescaling).

**IC / edge variable (fixed now):** same `x = ofi_integrated` vs
forward 900 s mid log-return, computed **within the out-window
extreme-OFI stratum**.

**Numeric F2 criteria (ALL required for F2-BINDING PASS):**

| # | form | criterion | n-class |
|---|---|---|---|
| F2-S | Substance | out-window continuation-signed mean 900 s forward return ≤ 0 within 2 SE (not significantly positive) | **n-invariant** on the "not same-class continuation" claim |
| F2-D | Differential | (in-window continuation-signed mean − out-window continuation-signed mean) > 0 AND the difference ≥ 1 SE of the difference | **mixed** — sign of (in−out) is **n-invariant**; the ≥ 1 SE magnitude conjunct is **n-variant** (JC-2 RULED 2026-07-17) |
| F2-R | RankIC companion (reported; binding with F2-D) | in-window extreme-OFI RankIC − out-window extreme-OFI RankIC > 0 | **n-invariant** on sign of contrast |

**F2 outcome vocabulary (closed — used by §9.1 / trigger map; JC-2 /
JC-3 RULED 2026-07-17):**

| outcome | definition |
|---|---|
| **F2-BINDING PASS** | **F2-S ∧ F2-D ∧ F2-R** all hold at n ≥ 100 (conjunction pinned) |
| **F2-BINDING NEGATIVE** | out-window continuation-signed mean > 0 with t ≥ 2 (affirmative same-class continuation — **contaminated shelf**, pack-11 DISPOSITIONS 3; JC-3) |
| **F2-BINDING FAIL** | residual — not PASS and not NEGATIVE (e.g. flat / under-separated differential without significant out-window continuation; or F2-R fails while F2-S holds) |
| **F2-INSUFFICIENT** | measured out-window n < 100 → **PARK evidence-infrastructure** (JC-9); no primary-only PROCEED |

**Firewall status of the out-window arm (binding — Amendment C / spec
§12.2):** if the arm is **F2-BINDING NEGATIVE** (shows continuation),
that arm is a **contaminated diagnostic about a dead claim** — **never
reusable as confirmation evidence for H9 or any future unclocked-OFI
/ KYLE card** without Lei extraordinary review. H12 evidence never
cites toward H9 revival regardless of F2 outcome. Recorded again in
§9.3.

#### 2.2.2 Per-symbol step-2 posture (JC-5 carried)

**No binding per-symbol magnitude/significance step-2 safeguard.**
Pooled §2.2.0 criteria alone govern the primary 2b PASS/FAIL.
Per-symbol RankIC magnitude and p are diagnostics only.

**PLUS — SIGN-CONSISTENCY D-membership condition (deployability
class, §1.6 family; JC-5 carried):** on a **primary 2b PASS**, each
symbol then in D must show own-boundary in-window extreme-OFI RankIC
**sign matching the claim** (continuation-positive). Fail ⇒ that
symbol **leaves D** ⇒ pooled-power axis-split recheck (§1.5 / §9.0.2)
vs ≥ 100 on remaining D. **No magnitude bar, no p bar.** Precedence
(§9.1): acts **only on a pass** — cannot loosen a primary 2b FAIL,
cannot park the card, cannot REJECT.

### 2.3 Measured-edge anchor (spec §4.1 / §5.5 acceptance test)

The measured conditional edge (mean continuation-signed 900 s forward
return on primary **in-window** eligible episodes, bps one-way, per
symbol in D, viable region) must be **≥ the per-symbol single-stress
floor** (APP 4.68, RMBS 5.51 bps) for the symbol to remain in D;
SELL-leg edges are additionally tested against the rider-inclusive
short floors (APP 5.82, RMBS 6.60). This measured value supersedes all
κ arithmetic from this point (spec §4.1 one-way ratchet) and becomes
the G12 disclosure input (`edge_estimate_bps` = the D-set minimum
measured edge, conservative). If D empties here, the card parks.

### 2.4 Tick-constraint artifact tests (spec §7 / §8 tick axis)

Run alongside the IC gate (evidence set including OLN × 10 preamble):

1. spread-in-ticks distribution **at eligible in-window boundaries**
   per symbol;
2. **≥ 4-tick-stratum re-derivation:** conditional continuation edge
   on in-window boundaries with prevailing spread ≥ 4 ticks; pass =
   sign-consistent with the pooled estimate; collapse ⇒ definition
   kill on the affected stratum;
3. **OLN quantum test:** conditional 900 s move mass vs counter the
   ±1 half-tick quantum; genuine persistence must show mass beyond
   one quantum. Evidence finding only — OLN is never deployable;
4. sign difference across buckets after quantum correction ⇒
   **definition-level kill**.

---

## 3. STEP 3 — CPCV (`research/cpcv.py`)

### 3.1 Configuration (numeric, with the H=900 embargo re-derivation — Amendment A)

Run **per symbol in D**, on that symbol's 20 grid sessions (pooled
structure does not merge symbols inside a CPCV path — serial
dependence is within-symbol).

- **Bar** = one h=900 in-window boundary; session discipline ⇒
  **25 bars/session**, `n_bars ≈ 500` per symbol on the 20-session
  grid (exact count = emitted in-window boundaries; sessions never
  concatenate state — sensors and regime engine re-warm per session
  replay).
- **Groups:** `n_groups = 20` — one contiguous group per grid session
  in calendar order (Amendment A: **carried**; group boundaries
  coincide with session boundaries).
- **k:** `k_test_groups = 2` ⇒ φ = C(20,2) = **190 combinations**,
  paths = C(19,1) = **19 reconstructed paths ≥ 8** (`cpcv_min_folds`
  ✓) — Amendment A **carry**.
- **Purge:** `label_horizon_bars = 1`. Derivation: the label is the
  900 s forward mid return ⇒ label span = 900 s = 1 bar exactly.
- **Embargo:** `embargo_bars = 2` (**JC-1 APPROVED 2026-07-17**).
  Derivation (Amendment A; bars shown; H10's 3-bar result was the
  prior — **verified, not assumed**):

  | component | seconds | note |
  |---|---|---|
  | label horizon (purge) | 900 | 1 bar — covered by `label_horizon_bars = 1` |
  | `ofi_integrated` / `ofi_integrated_percentile` event-time window | 900 | `HorizonWindowedFeature` on `ofi_raw` path |
  | `scheduled_flow_window` lookback | **0** | **stateless** calendar membership — no feature lookback |
  | `ofi_raw` `warm_window_seconds` | 300 | nested under the 900 s integrate path; does **not** extend deepest lookback beyond 900 |
  | deepest feature lookback | **900** | OFI window only (no nested OLS / λ window — contrast H10's 900+60) |
  | residual after 1-bar purge | 900 | ⌈900 / 900⌉ = **1 bar minimum** |
  | no-fixed-constant components | +1 bar | `realized_vol_30s_zscore` 2000-reading count window (`RollingZscoreFeature` default — quote-rate-dependent) + quote-clocked HMM posterior (both on the entry/gate path — spec §5.3 `on_condition`) |
  | **adopted `embargo_bars`** | **2** | 1 + 1 |

  **Lineage rule (now stated generally — JC-1):** embargo =
  arithmetic minimum from deepest feature lookback after purge
  (⌈lookback_s / bar_s⌉), **+1 NFC when gate consumers warrant**
  (rv-z count window and/or quote-clocked HMM on the entry/gate path).
  H2/H8/H10 each instantiated this rule; H10's 3 bars = ⌈960/900⌉=2
  (SFI 900 + nested λ 60) +1 NFC. H12 has no nested λ → 1+1=2.

  Total forward exclusion = 1 + 2 = **3 bars = 2,700 s** per test
  region. `embargo_bars = 2 ≥ cpcv_min_embargo_bars = 1` ✓; the
  block-bootstrap block length is `max(1, embargo_bars) = 2` bars
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
range [5.0, 14.0]) and applied to the **test** bars through the
frozen `evaluate` rule. All other parameters are frozen at spec
defaults (`ofi_percentile_min = 0.80`, `edge_cap_bps = 12.0`, the
per-symbol floor constants, gate thresholds §5.3). This in-protocol
calibration is part of the single pre-registered primary trial; it
does not increment N. (**JC-8 APPROVED 2026-07-17** — regressor on
`excess`, clip [5.0, 14.0].)

**Dual reporting (8-F ruling, carried verbatim):** the **PRE-COST
path distribution** (same series without the 2 × C_ow,stressed
deduction) is computed and reported **alongside the cost-adjusted one
at every step** that quotes CPCV output — the pass/fail **criterion
stays on the cost-adjusted series**. The pre-cost distribution is
diagnostic context (separating "no continuation exists" from
"continuation exists but below the cost proxy"), never a result.

### 3.3 Annualization and thresholds (H=900 carry; GateThresholds implication: NONE)

```
annualization_factor = sqrt(25 × 252) = sqrt(6,300) ≈ 79.3725
```

(bars/session × trading days/year — the sqrt(252)-commensurate
scaling for 900 s in-window bars; Amendment A **carried**), passed to
`build_cpcv_evidence` so emitted Sharpes are annualised and directly
comparable to the `GateThresholds` defaults. Bootstrap:
`n_bootstrap = 10,000`, `seed = 0` (Inv-5 bit-identical).

**Thresholds: the `GateThresholds` defaults, NO per-alpha
`gate_thresholds:` override — none is needed and none is
pre-registered** (Amendment A: H = 900 changes the annualization
factor and path count, not the annualised bars themselves — 19 paths
≥ 8, embargo ≥ 1, and the annualised Sharpe / p-value bars are
horizon-independent once the annualization factor is commensurate):

| gate | value | this run |
|---|---|---|
| `cpcv_min_folds` | ≥ 8 reconstructed paths | **19** by construction |
| `cpcv_min_mean_sharpe` | ≥ 1.0 (annualised) | must clear on **every** symbol in D |
| `cpcv_max_p_value` | ≤ 0.05 (block bootstrap) | every symbol in D |
| `cpcv_min_embargo_bars` | ≥ 1 | **2** by construction (JC-1 APPROVED) |

Fail on any symbol ⇒ that symbol leaves D; pool / D emptying ⇒ status
per §9. **n-class:** mean-Sharpe / p-value fails after honest
annualization are treated as **n-invariant REJECTED** (does not
survive purged OOS reconstruction); inability to form 20 groups is
**n-variant PARK** (evidence-infrastructure).

---

## 4. STEP 4 — REGIME STRATIFICATION (manual per R6 / research-protocol Phase 3.3 — no shipped harness)

### 4.1 Strata (cutpoints fixed now; spread axis = spread-in-ticks — H8/H10 JC-4 carried)

Partition **warm h=900 boundaries** (per symbol, full 20-session grid)
on two axes:

- **Vol axis** — HMM dominant state (`RegimeState.dominant_name`,
  `hmm_3state_fractional`): `compression_clustering` / `normal` /
  `vol_breakout` (3 strata);
- **Spread axis** — boundary-time prevailing **spread-in-ticks** at
  **per-symbol terciles of the UNCONDITIONAL grid spread
  distribution** — all warm in-window boundaries, never
  eligible-only — **frozen at census time and disclosed per symbol**
  (H8/H10 JC-4 carried: spec bans `spread_z_30d` on this card —
  census warm starvation on thin names; F3 is worded on
  spread-in-ticks; APP vs RMBS medians live in different buckets).
  Cutpoints computed once from the census output before any forward
  return exists.

The daily calm/elevated-A/elevated-B stratum is a **third, reporting
axis** (every statistic also reported in the gate-state × daily-
stratum 2×2). F3 kill clause: conditional continuation sign across
**spread-in-ticks terciles within the benign stratum** (benign =
`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0 ∧ W_hh = 1`).

### 4.2 Procedure and per-stratum minimum

Within each (vol × spread) stratum: repeat the §2.2.0 IC test
(in-window extreme-OFI `spearman_ic` on stratum boundaries, plus the
§2.2.1 F2 contrast where the stratum holds matched out-window bars)
and, where the stratum holds enough bars to form the §3 groups,
repeat CPCV (same config; a stratum that cannot form 20 groups
reports CPCV-INFEASIBLE, not a fail). **Minimum per-stratum sample =
100 boundary observations** (research-protocol Phase 3.3 rule 4);
below it the stratum reports **INSUFFICIENT** — never pooled away,
never counted for or against the acceptance rule.

### 4.3 Acceptance rule (numeric)

**PASS** iff, on the pooled {APP ∪ RMBS} evidence: the in-window
extreme-OFI conditional continuation is **sign-stable
(continuation-positive) AND in-window extreme-OFI RankIC ≥ +0.02 with
Fisher-z p ≤ 0.05** in at least **2 vol strata × 2 spread strata**
(i.e. ≥ 2 cells on each axis among cells with n ≥ 100).
Single-stratum concentration is a fragility flag reported to Lei (not
an automatic kill) **unless** the conditional continuation sign
reverses across spread-in-ticks terciles within the benign stratum —
that is F3, a **definition-level kill**.

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
  boundaries integrate to ≈ 0 — |mean| ≤ 2 × SE; (ii) the
  **out-window matched-OFI stratum** is exactly F2 (§2.2.1) — if it
  continues at the same sign/magnitude class, the clock does no work.
  Fail ⇒ **misattribution ⇒ hypothesis-revise** (or REJECTED if F2
  NEGATIVE per §9).
- **I-2 (side symmetry):** continuation-long vs continuation-short
  conditional edges in the benign in-window stratum agree within
  sampling error — two-sample z ≤ 2. Fail ⇒ hypothesis-revise; SHORT
  carries the SSR/HTB optimism caveat; §1.6 RMBS long-only is an
  *economic* asymmetry — I-2 tests pre-cost mechanism symmetry only.
- **I-3 (clock / flow co-travel; mechanism attribution):** identical
  to F2-D / F2-R — in-window continuation must exceed matched
  out-window; no differential ⇒ θ₂ (clock decoration). Numeric
  reading = §2.2.1.
- **IC(t) decay (research-protocol Phase 5):** compute RankIC at
  forward horizons t ∈ {120, 300, 900, 1800} s on the in-window
  extreme-OFI stratum; fit `IC(t) = IC_0 · exp(−λ t)`; fitted
  half-life must lie in **[225, 900] s** (declared hl = 450 ± a
  factor of 2). Outside ⇒ hypothesis-revise; non-decaying IC(t) is
  F1-adjacent death.

---

## 5. STEP 5 — DSR (`research/dsr.py`)

Computed on the pooled-D per-bar cost-adjusted return series (§3.2
definition, all D symbols' sessions, bars in (symbol, session, time)
order; n_obs = total bar count — ≈ 500 × |D|):

- `build_dsr_evidence_from_returns(returns=…, trials_count=N,
  annualization_factor=sqrt(6,300) ≈ 79.37)` with **N = the
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
acquiring more trials without a better Sharpe worsens DSR).

---

## 6. STEP 6 — DRIFT DIAGNOSTICS

**What re-estimates, on what window:** at runtime, **nothing** — all
sensor params, gate thresholds, session constants, and calendar
lead/ε are fixed (spec §1.4 / §1.5 / §5.1). The only estimated
quantity in the whole candidate is `edge_scale_bps` (Task-8
calibration, §3.2). Drift diagnostics therefore test the *stability
of the fixed-parameter machinery and the single calibrated parameter*
across the grid's sessions; pre-stated bounds below are
disqualifying.

### 6.1 Regime-engine behavior (`scripts/regime_diagnostics.py` as anchor)

Run per (symbol ∈ D, session) over the grid with the Task-9 config,
`--horizon 900`. The H12 regime arm is an **exclusion screen**
(`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0`), not a
positive benign selector — bounds adapted from H8/H10 JC-6:

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
| per-session eligible in-window episode rate (per deployable symbol, within a daily stratum) | max/min ratio across that stratum's sessions ≤ 5; above ⇒ hypothesis-revise |
| `scheduled_flow_window` calendar-warm coverage | spec §1.3 / §1.5.3: warm < 0.5 on > 2 sessions ⇒ symbol leaves D; `calendar_missing_rate > 0` ⇒ infrastructure FAIL |
| `ofi_integrated` / percentile warm coverage | reported per session; quote-warm starvation that collapses the pooled count below §1.5 is PARK on power (already scored) |
| `realized_vol_30s_zscore` warm coverage | reported per session (mandatory) |
| in-window vs out-window occupancy ratio | reported against geometry identity 12:13; material deviation unexplained by HT/gate ⇒ calendar-authorship investigation (infrastructure), not edge tuning |

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

`configs/bt_sig_halfhour_clock_drift_h900_v1.yaml` (Phase B / Task 9
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
--config configs/bt_sig_halfhour_clock_drift_h900_v1.yaml --symbol <S>
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
4. **Fill-quality diagnostics (spec §11; H10 JC-7 carried):**
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

The following five-point block enters this protocol as **frozen
text** (backlog-13 binding; any undefined intersection is a
freeze-blocking defect):

1. Primary §9 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK; a single-symbol
   shortfall inside the pool does **not** park the card if the pool
   clears ≥ 100 contamination-excluded — unless that symbol also
   fails deployability park arithmetic, in which case it drops from
   D and the pool is re-checked (A-2.1-class axis split, stated now).
   *(Numeric floor in this protocol = 100 per D-C1; design margin /
   design-central = 130 / 147.7 — deviation logged in §1.5.)*
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. **F2 window-binding** (mechanism): F2-BINDING FAIL or NEGATIVE →
   REJECTED (substance) when it co-fires with a primary posture that
   would otherwise continue — see §9.1 for every intersection;
   n-invariant for the binding claim.
5. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

### 9.1 Instrument-pair precedence walk (Amendment C — completeness
check; trigger-(b)/(c) implied)

Every intersection that can fire in the same step is declared. An
absent row would be a freeze-blocking defect. **Freeze record
(Task 8-F-H12, Lei, 2026-07-17; backlog-13):** this matrix is
**freeze-clean** — zero undefined intersections; triggers (a)/(b)/(c)
are **self-executing** from the frozen rows (no post-outcome
adjudication).

| instruments that can co-fire | which governs | subordinate effect / H13 map |
|---|---|---|
| §1.5 power (pooled < 100) ∩ §1.5 edge-emptiness | **both PARK** (either parks); report both | H13 trigger **(a)** ACTIVATES on design/census death |
| §1.5 infrastructure FAIL ∩ any park | **infrastructure FAIL** governs (halt; N unchanged) | H13 not authorized from infra fail |
| §1.5 pooled power PASS ∩ single-symbol episode shortfall | **pooled governs PROCEED** (§9.0.2); symbol stays unless deployability fails | diagnostic only |
| §1.5 pooled power PASS ∩ symbol deployability fail (edge / rider / warm drop / sign-consistency) | symbol **drops from D**; **pool re-checked** vs ≥ 100 | if pool then fails → PARK → trigger **(a)** |
| §1.5 PARK ∩ any later step | **first-FAIL stop** — later steps do not run | — |
| §2a sign-golden FAIL ∩ §2b | **2a REJECTED** governs; 2b not computed | implementation fix, N unchanged, re-run from 2a |
| §2b primary magnitude (\|RankIC\| < 0.03 or sign ≤ 0) ∩ §2b p > 0.01 | **magnitude n-invariant REJECTED** governs (§9.0.3); p is reported | — |
| §2b primary magnitude FAIL ∩ §2b n < 100 (INSUFFICIENT) | **magnitude REJECTED** outranks sample-floor PARK when magnitude is computable at n ≥ 3; if n below computability, **INSUFFICIENT → PARK (power)** only | never rescale \|RankIC\| floor; PARK → trigger **(a)** adjacency |
| **§2b primary PASS ∩ F2-BINDING PASS** | **continue to §2.3 / step 3** | — |
| **§2b primary PASS ∩ F2-BINDING FAIL** | **REJECTED (F2)** — mechanism attribution dead despite pooled in-window drift (§9.0.4) | H13: F2 fail ⇒ presumptive death for cards sharing the same `ALGO_CLOCK` binding architecture (pack-11 H12·3); **not** trigger (b)/(c) |
| **§2b primary PASS ∩ F2-BINDING NEGATIVE** | **REJECTED (F2 NEGATIVE)** — clock decoration; out-window arm = **contaminated shelf** (§9.3) | same H13 posture as F2 FAIL for architecture; shelf **never** cites to H9 |
| **§2b primary FAIL ∩ F2-BINDING PASS** | **REJECTED (F1 / primary 2b)** — magnitude/significance/tail kill; clock-binding substance held | **H13 trigger (b) ACTIVATES** (pack-11 DISPOSITIONS 2) — implied by this row |
| **§2b primary FAIL ∩ F2-BINDING NEGATIVE** | **REJECTED (F1+F2)** — both arms kill | **H13 trigger (c)** — activation **only after Lei reviews** F2 by window type (outcome-contaminated; extraordinary bar) — implied by this row |
| **§2b primary FAIL ∩ F2-BINDING FAIL** | **REJECTED (F1)** governs; F2 FAIL reported as non-NEGATIVE non-PASS | **H13 trigger (c) adjacency** — treat as requiring Lei review (not automatic (b)); disclosed |
| §2b ∩ F2-INSUFFICIENT (out-window n < 100) | **PARKED (evidence-infrastructure)** on the binding arm — primary 2b numbers reported but not treated as PROCEED | never rescale F2 n floor; not trigger (b) |
| §2b primary FAIL ∩ per-symbol diagnostic fail | **primary §9 row 2b REJECTED governs**; diagnostics cannot loosen | no magnitude/p safeguard (§2.2.2) |
| §2b primary PASS ∩ per-symbol SIGN-CONSISTENCY fail (JC-5) | **primary 2b PASS stands**; failing symbol **leaves D**; pool re-checked vs ≥ 100 | cannot loosen / park / REJECT; acts only on a pass; if pool then fails → PARK |
| §2b PASS ∩ F2 PASS ∩ §2.3 edge anchor fail on all D symbols | **§2.3 PARK** (economics below floor) | D empty → trigger **(a)** adjacency |
| §2b PASS ∩ §2.4 tick stratum kill | **REJECTED on affected stratum**; if D empties → PARK | survivors continue |
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
invalid (spec §11(d) / research-workflow vocabulary).

| step | binding numeric criterion | on FAIL → status | n-class |
|---|---|---|---|
| 1 census | viable region non-empty on ≥ 1 symbol AND pooled contamination-excluded in-window episodes ≥ **100** across {APP ∪ RMBS} (after measured calendar-warm); `calendar_missing_rate = 0` | **PARKED** (emptiness or power); infra FAIL if calendars missing | n-variant (power/emptiness); infra n-invariant |
| 2a sign-golden | all seven assertions | **REJECTED** (sign/wiring defect; re-run after fix, N unchanged) | n-invariant (wiring) |
| 2b primary IC gate | in-window extreme-OFI RankIC > 0, \|RankIC\| ≥ 0.03, p ≤ 0.01, n ≥ 100; bucket spread positive; tail t ≥ 2 — **pooled primary** | **REJECTED** (F1 dead) — then see §9.1 for F2 intersection → trigger (b)/(c) | magnitude/sign **n-invariant**; p/n **n-variant** |
| 2b F2 binding | F2-S ∧ F2-D ∧ F2-R at out-window n ≥ 100 (JC-2 conjunction) | **REJECTED (F2)** if FAIL/NEGATIVE co-fires with primary PASS; see §9.1 | F2-S / F2-R / F2-D sign **n-invariant**; F2-D ≥1 SE **n-variant** (JC-2) |
| 2b sample floor | n ≥ 100 reachable on pooled in-window extreme stratum; out-window n ≥ 100 for F2 adjudication | **PARKED (evidence-infrastructure)** if unreachable (JC-9: no primary-only PROCEED) — never threshold rescaling | n-variant |
| 2b→D sign-consistency (JC-5) | on 2b PASS: each D symbol own-boundary RankIC sign matches claim | failing symbol **leaves D**; pool recheck — **not** a park/reject of the card | deployability; acts only on pass |
| 2.3 edge anchor | measured conditional edge ≥ per-symbol single-stress floor on ≥ 1 symbol (SELL: rider-inclusive) | **PARKED** (economics below floor everywhere) | n-variant |
| 2.4 tick tests | ≥ 4-tick stratum sign-consistent | **REJECTED on affected stratum** (grid artifact); if D empties → PARKED | n-invariant (sign) |
| 3 CPCV | 19 paths, mean annualised path Sharpe ≥ 1.0, block-bootstrap p ≤ 0.05, embargo **2** (JC-1), per D symbol, cost-adjusted series | **REJECTED** (does not survive purged OOS reconstruction) | n-invariant (at commensurate annualization) |
| 4 stratification | sign-stable + in-window extreme-OFI RankIC ≥ 0.02 (p ≤ 0.05) in ≥ 2 vol × ≥ 2 spread strata (n ≥ 100 each) | **HYPOTHESIS-REVISE** (regime-fragile); F3 spread-tercile sign reversal in benign stratum ⇒ **REJECTED** | F3 n-invariant; 2×2 miss n-variant |
| 4.4 invariance | I-1 ratio ≤ 1.5 + companions; I-2 z ≤ 2; I-3 = F2 differential; IC(t) half-life ∈ [225, 900] s | **HYPOTHESIS-REVISE** | mixed; I-1 fail ≈ n-invariant misattribution |
| 5 DSR | dsr ≥ 1.0, p ≤ 0.05, observed > noise ceiling at honest N | **REJECTED** (indistinguishable from max-of-N noise) | n-invariant at fixed N |
| 6 drift | all §6.1–§6.3 bounds | **HYPOTHESIS-REVISE** | n-variant |
| 7 execution | SURVIVES baseline + stressed; reconciliation (§7.2.3); fill-mix bounds | **TRAP-QUADRANT** if steps 1–6 passed; `LOW_N` ⇒ **PARKED (execution power)** | LOW_N n-variant; otherwise exec-axis |
| 8 grid | F4 clearance at all 27 neighborhood vertices + the inv12-stress point, every D symbol (full 81-cube reported; non-neighborhood failures = logged fragility) | **TRAP-QUADRANT** (simulator-dependent economics) | exec-axis |

**Tuning prohibition (binding, repeated):** converting any FAIL by
changing a parameter, threshold, window, stratum definition, calendar
lead/ε, or knob is prohibited within this trial. Any such change is a
**new trial**: increment N in the living ledger, log the variant with
its justification, and re-enter this protocol from step 1 for the new
variant. The one-way κ ratchet (spec §4.1) additionally forbids
upward re-estimation of any κ factor after data contact. No
post-park occupancy re-threshold is pre-authorized (§1.7).

### 9.3 F2 out-window firewall (pack-11 DISPOSITIONS 3 — binding)

| direction | rule |
|---|---|
| **H12 → H9** | H12 evidence **never cites toward H9 revival**. An H12 **F2-BINDING PASS** strengthens H9's presumptive death. An H12 **F2-BINDING NEGATIVE** out-window arm is a **contaminated shelf** — diagnostic about a dead claim; not extraordinary justification for H9; not a KYLE attribution restore; **not reusable as confirmation evidence** for H9 or any future unclocked-OFI card without Lei extraordinary review. |
| **H9 → H12** | H9 history **never prejudices H12 scoring** — κ, RankIC bars, census floors, F1/F2 adjudication, or stop-rule accounting. H12 is evaluated fresh against its own gates (session constraint 6). |

---

## 10. TRIAL LEDGER STATE AT PROTOCOL WRITE (Amendment F)

**N = 12** (pack-11 §(3) / spec §14; H10 close-out left N = 12; no
outcome contact in Task 7 or this Task 8 write). The primary object of
this protocol is the slate-D ledger row "H12 primary:
ofi_integrated(900 s) quintile × half-hour `ALGO_CLOCK` continuation,
H=900, hl=450, passive, pooled {APP,RMBS}" — this protocol is its
measurement plan, not a new trial. Rows that increment **only on
evaluation** (FQ-6B-R):

- the spec §14 drafted-not-evaluated variants (decile alt — not
  authorized; session-relative OFI percentile; `seconds_to_window_close`
  band; `hard_exit_age_seconds = 1350`; session-constant variations;
  re-thresholded conditioning);
- H13 primary (CONTINGENT SECOND CARD — not authorized for census
  yet; activates only under pack-11 DISPOSITIONS 2 triggers (a)/(b)/(c)
  as implied by §9.1).

Census-class evaluation (step 1) is N-neutral until first IC /
forward-return contact. **First outcome contact on the H12 primary
→ N ≥ 13.** The DSR of §5 uses the then-current N, never the written
12 if evaluations have occurred in between.

---

## 11. JUDGMENT CALLS AND RULINGS (Amendment F — 8-F pattern; RULED 2026-07-17, Task 8-F-H12, Lei)

Every residual numeric or instrument freedom, with the adopted
proposal and its alternative. **All ten JCs are RULED (2026-07-17);
the per-JC ruling is recorded at the end of each entry and the ruled
text is applied in the named sections. This section is the freeze
record.**

**Pre-ruled by Lei (Amendment B — recorded, not a JC; STANDS):**

- census park floor = pooled ≥ **100**; design ≥ 130 and
  design-central **147.7** = design margin / projection only (D-C1).
- JC-5 precedent carried: per-symbol sign-consistency D-membership
  condition on a 2b PASS; deployability class; precedence declared
  (§1.6 / §2.2.2 / §9.1).
- H10/H8 JC-1 estimand split carried: leakage vs co-travel; **> 1 %
  trigger on leakage only** (§1.3).
- κ minimum-rule recorded (§1.2 / spec §4.1): H12 no discrepancy;
  freeze **0.146**.
- N = **12**.
- §9.1 matrix freeze-clean under backlog-13 — zero undefined
  intersections; triggers (a)/(b)/(c) self-executing (Task 8-F-H12
  item 5).

---

**JC-1 — Embargo bars (§3.1; Amendment A verify-not-assume).**
Proposed: `embargo_bars = 2` — arithmetic minimum 1 bar residual
(deepest lookback 900 s OFI = label span; `scheduled_flow_window`
stateless) +1 NFC (rv-z count window + HMM on entry/gate path).
Alternative: carry H10's **3** bars despite absence of nested 60 s λ
lookback (conservatism without arithmetic).
**RULING: APPROVED — 2 bars (minimum 1 + NFC 1; derivation as §3.1).
Lineage rule now stated generally: arithmetic minimum from deepest
feature lookback, +1 NFC when gate consumers warrant. Applied in
§3.1 / §3.3 / §9.2.**

**JC-2 — F2 differential margin numericization (§2.2.1 F2-D).**
Proposed: (in − out) > 0 AND ≥ **1 SE** of the difference, plus
F2-R RankIC contrast > 0, plus F2-S (out ≤ 0 within 2 SE).
Alternative A: ≥ 2 SE differential (stricter; may starve power at
n ≈ 160). Alternative B: RankIC contrast alone without mean
differential.
**RULING: APPROVED at 1 SE with label precision — F2-D is mixed
n-class (sign n-invariant; ≥1 SE n-variant). Conjunction pinned:
F2-BINDING PASS = F2-S ∧ F2-D ∧ F2-R; NEGATIVE per JC-3; FAIL =
residual. Applied in §2.2.1 / §9.2.**

**JC-3 — F2-BINDING FAIL vs NEGATIVE split for trigger-(c) (§2.2.1 /
§9.1).** Proposed: NEGATIVE = out-window continuation-signed mean > 0
with t ≥ 2; FAIL = residual non-PASS non-NEGATIVE; primary FAIL ∩
F2 FAIL maps to trigger-(c) *adjacency* (Lei review, not automatic
(b)). Alternative: collapse FAIL into NEGATIVE for trigger purposes
(more H13-restrictive).
**RULING: APPROVED as proposed — NEGATIVE requires affirmative t ≥ 2
out-window continuation; primary-FAIL ∩ F2-FAIL = trigger-(c)
adjacency (Lei review). Applied in §2.2.1 / §9.1.**

**JC-4 — Stratification spread axis = spread-in-ticks per-symbol
terciles (§4.1).** Carry H8/H10 JC-4 (spec bans `spread_z_30d`).
Alternative: fixed cross-symbol cutpoints (degenerate given APP vs
RMBS).
**RULING: CONFIRMED as carried. Applied in §4.1.**

**JC-5 — Per-symbol step-2 posture (§2.2.2).** Carry H10 JC-5 ruled
modified (no magnitude/p safeguard; PLUS sign-consistency
D-membership on primary PASS only). Alternative: reintroduce
A-2.1-class per-symbol magnitude/p conjunct.
**RULING: CONFIRMED as carried. Applied in §1.6 / §2.2.2 / §9.1 /
§9.2.**

**JC-6 — Drift bounds for exclusion screen (§6.1).** Carry H10 JC-6
adapted (screen-OFF ≤ 0.95; median ON dwell ≥ 900 s; always-ON not a
failure). Alternative: H2 two-sided gate-ON band.
**RULING: CONFIRMED as carried. Applied in §6.1.**

**JC-7 — Fill-mix / markout horizon (§7.2.4).** Through-share ≤ 50 %;
filled-minus-unfilled markout gap ≤ 2.0 bps at **900 s** (450 s
alongside). Alternative: bespoke bound beyond the markout gap.
**RULING: CONFIRMED as carried. Applied in §7.2.4.**

**JC-8 — CPCV per-split calibration regressor (§3.2).**
`edge_scale_bps` ~ OLS of continuation-signed forward return on spec
§5.2 `excess`, through origin, clipped [5.0, 14.0]. Alternative:
calibrate on raw `ofi_integrated` level alone (discards the
percentile-exceedance the evaluate rule uses).
**RULING: APPROVED (clip [5.0, 14.0]). Applied in §3.2.**

**JC-9 — F2-INSUFFICIENT consequence (§2.2.1 / §9.1).** Proposed:
out-window n < 100 ⇒ PARK evidence-infrastructure (binding arm
unadjudicable); primary 2b numbers reported but not PROCEED.
Alternative: allow primary-only PROCEED with F2 reported as
INCONCLUSIVE (weakens load-bearing F2).
**RULING: APPROVED — F2-INSUFFICIENT → PARK; no primary-only
PROCEED. Applied in §2.2.1 / §9.1 / §9.2.**

**JC-10 — Calendar-warm measurement definition (§1.1 / Amendment D).**
Proposed: per (symbol, session) warm fraction = share of in-window
h=900 boundaries with `scheduled_flow_window.warm == True`; pooled
episode count re-scored after measurement; warm < 0.5 on > 2 sessions
drops that symbol; `calendar_missing_rate > 0` ⇒ infrastructure FAIL.
Alternative: warm = share of RTH seconds inside authored windows —
different estimand.
**RULING: APPROVED — boundary-based estimand; missing-rate =
infrastructure FAIL. Applied in §1.1.**

---

## 12. FREEZE DECLARATION

Steps are order-locked (§0); the census (step 1) executes only after
this freeze commit **and** P0-1 Phase-A deliverables are green; steps
7–8 execute only under P0-6. The §11 rulings landed 2026-07-17
(Task 8-F-H12, Lei) and are applied in §1.1, §2.2.1, §3.1, §3.2,
§3.3, §4.1, §6.1, §7.2.4, §9.1, and §9.2. The §9.1 matrix is
freeze-clean under backlog-13 (zero undefined intersections;
triggers (a)/(b)/(c) self-executing). This document is
**PRE-REGISTERED — FROZEN as of the Task 8-F-H12 commit
(2026-07-17)**. From this commit, all changes go in an `AMENDMENTS`
section appended below this line, each entry carrying a timestamp
and justification.

*Protocol frozen — Phase A / Task 9 (implementation) may begin under
P0-1.*

---

# AMENDMENTS

## A-1 — Phase-A IMPLEMENTATION RECORD (Task 9-A-H12, 2026-07-17)

**Scope.** Phase A only (Ordering B): calendar artifacts +
`ofi_integrated_percentile` factory + census instrument + harness IC
row. **No census execution, no IC numbers, no outcome contact.** Phase B
explicitly out of scope. **N = 12 survives unchanged** (living ledger;
first outcome contact still reserved for step-2 IC on the H12 primary
→ N ≥ 13).

### Commit ledger

| # | sha | delivered |
|---|---|---|
| 1 | `2f3d930` | `WindowKind.ALGO_CLOCK` + deterministic authoring script (`scripts/research/author_algo_clock_calendars.py`) + per-session half-hour calendars for the 20-grid dates (`[M, M+1s)`); `scheduled_flow_window` warms for {APP, RMBS}; window-authoring bit-identity guard in `tests/sensors/test_algo_clock_calendars.py`. Fixture `2026-03-24` hash baseline untouched. Coverage map: `author_algo_clock_calendars.py` → `research_validation`. |
| 2 | `aea0578` | `ofi_integrated_percentile` factory sibling on `ofi_raw` at all canonical horizons (H8 `kyle_lambda_60s` percentile precedent) + bootstrap factory tests. Determinism suite green — **no locked parity baseline moved**. |
| 3 | `ec78718` | Census instrument `scripts/research/halfhour_clock_drift_census.py` (frozen §1.1 predicate **both arms**; JC-10 calendar-warm; JC-1 leakage / co-travel REPORTS; σ₉₀₀ vs floors) + synthetic-fixture golden pinning both arms at build time (`tests/scripts/test_halfhour_clock_drift_census.py` — 8-C-H10 lesson). Coverage map: census → `research_validation`. |
| 4 | `3cf4413` | Harness IC row in `scripts/sensor_feature_ic.py` — H12 clock-stratified `in_window_extreme` / `out_window_extreme` / `clock_contrast` at h=900; OLN evidence-only empty; additive only; synthetic smoke tests in `tests/scripts/test_sensor_feature_ic.py`. |

### Gate battery (each commit independently green; PYTHONHASHSEED=0)

| gate | commit 1 | commit 2 | commit 3 | commit 4 |
|---|---|---|---|---|
| `pytest -m "not functional and not slow"` | 4110 passed, 9 skipped | 4112 passed, 9 skipped | 4119 passed, 9 skipped | 4121 passed, 9 skipped |
| `mypy src/feelies` (strict) | clean (194 files) | clean | clean | clean |
| `ruff check src/ tests/` (+ scripts touched) | clean | clean | clean | clean |
| `tests/docs/test_prompt_coverage_map.py` | green (scripts row) | green | green (scripts row) | green |
| determinism / locked baselines | fixture hash held | **no baseline moved** | n/a | n/a |

### Coverage-map ownership rows

| artifact | owner |
|---|---|
| `src/feelies/storage/reference/event_calendar/` (ALGO_CLOCK + YAMLs) | `audit_data_ingestion` (package-wholly-owned; no `_FILE_OWNERS` entry required) |
| `scripts/research/author_algo_clock_calendars.py` | `research_validation` (`docs/prompts/README.md` scripts row) |
| `src/feelies/bootstrap.py` (`ofi_integrated_percentile` additive) | `audit_kernel` (pre-existing root-module owner; unchanged) |
| `scripts/research/halfhour_clock_drift_census.py` | `research_validation` |
| `scripts/sensor_feature_ic.py` (H12 row additive) | `sensor` (pre-existing scripts-row owner; unchanged) |

### Explicit non-actions (binding)

- Census **not executed** against the 40-cell grid (instrument + golden pin only).
- No forward return / RankIC / CPCV / DSR / outcome statistic computed on cached L1.
- No Phase-B alpha YAML, `configs/bt_sig_halfhour_clock_drift_h900_v1.yaml`, or sign-golden evaluate module.
- Locked parity baselines / promotion ledger / core event schemas untouched.
- **N = 12** at close of Phase A (unchanged).

### P0-1 status after this amendment

| deliverable | status |
|---|---|
| (i) `WindowKind.ALGO_CLOCK` + per-session calendars | **landed** (`2f3d930`) |
| (ii) `ofi_integrated_percentile` at h=900 | **landed** (`aea0578`) |
| (iii) census instrument (both arms) | **committed** (`ec78718`) — not run on cache |
| (iv) harness IC row (both F2 arms) | **landed** (this commit) — not run on cache |

**Stop for Lei review before any census execution (step 1).**

*(Record appended 2026-07-17. Justification: Task 9-A-H12 Phase-A
close-out; instruments built and pinned; no freeze-body edit.)*

---

# CENSUS RESULTS — STEP 1 EXECUTED (Task 8-C-H12, 2026-07-17)

Execution record of the frozen §1 census. **Not an amendment** — no
test definition, threshold, or parameter above the freeze line
changed; the only header edit is the Status / FQ-3 provenance block
recording this execution. **No forward return, IC, or signal
evaluation was computed** — the only return-like quantity touched is
the unconditional session σ₉₀₀, per the frozen §1 authorization. The
out-window (`W_hh = 0`) arm was **COUNTED, never scored**. **N = 12**
(census N-neutral).

## C.0 Preconditions at execution (§0 re-verified, in order)

| # | check | result |
|---|---|---|
| (i) window-authoring determinism | `PYTHONHASHSEED=0 uv run pytest tests/sensors/test_algo_clock_calendars.py` → **8/8**; committed calendar YAML / `EventCalendar.hash` bit-identical on re-author — **PASS**; mismatch would be infrastructure FAIL |
| (ii) both-arm synthetic golden | `PYTHONHASHSEED=0 uv run pytest tests/scripts/test_halfhour_clock_drift_census.py` → **7/7** at census time (in-window + out-window arms pinned) — **PASS** |
| (iii) `calendar_missing_rate` (JC-10) | armed; measured **0.0 on all 40** {APP, RMBS} cells — **PASS** (any > 0 = infrastructure FAIL / P0-1 defect) |
| P0-1 | Phase-A deliverables | green: calendars `2f3d930`, percentile factory `aea0578`, instrument `ec78718`, harness IC row `3cf4413` / pin `8708c3c` |
| P0-4 | determinism | `PYTHONHASHSEED=0`; direct `DiskEventCache` (`~/.feelies/cache`); real `SensorRegistry → HorizonScheduler → HorizonAggregator` stack; full-grid re-run **bit-identical** (SHA-256 match below) |
| P0-5 | protocol frozen before census | freeze + A-1 Phase-A record precede execution |

**FQ-3 provenance:** host `CHENGLEI-L-3` / `Windows-11-10.0.26200-SP0` /
Python 3.14.2; git SHA `8708c3c`; worktree clean for tracked files
(`formal_spec.md` untracked sibling, freeze-allowed); artifact
`docs/research/artifacts/halfhour_clock_drift_census_2026-07-17.json`
SHA-256 `51913fe947745f9ea99c165d7b44232f4ac9d36678f451e0f1a772b7eb349ec1`
(primary run = re-run).

## C.1 Method

`scripts/research/halfhour_clock_drift_census.py` — frozen §1.1
predicate exact (arms 1–7) on **both** arms; JC-10 calendar-warm =
share of in-window h=900 boundaries with `scheduled_flow_window`
warm; warm-drop < 0.5 on > 2 sessions; primary count = §1.1
predicate count (contamination-excluded multiplier 1.0; no
post-hoc intensity exclusion); σ₉₀₀ = Bessel-corrected std of
non-overlapping 900 s mid log-returns on the 09:30-anchored grid
(bps); floors APP 4.68 / **32.05** and RMBS 5.51 / **37.74**
(κ = **0.146**); short rider APP 5.82 / 39.86, RMBS 6.60 / 45.21
(σ min = floor/κ). OLN × 10 preamble evidence-only.

## C.2 Calendar-warm (JC-10) — ASSERTED 0.90×0.95 vs measured

Design priors (gate × warm): **0.90 × 0.95** → design-central
in-window **147.7** / out-window **160.1**. Measured warm **replaces**
the ASSERTED 0.95 for power scoring; both recorded.

| symbol | ASSERTED warm prior | measured mean [min–max] | sessions with warm < 0.5 | warm-drop fired? |
|---|---|---|---|---|
| APP | 0.95 (in 0.90×0.95 product) | **1.000** [1.000–1.000] | 0 / 20 | no |
| RMBS | 0.95 (in 0.90×0.95 product) | **1.000** [1.000–1.000] | 0 / 20 | no |

`calendar_missing_rate = 0` on every grid cell. Coverage drop rule
did not fire. Measured warm does **not** rescue power — occupancy
after the frozen quintile × clock × gate × vol-z × sign arms is
below the park floor (C.5).

## C.3 JC-1 REPORTS — leakage vs co-travel

| estimand | result | > 1 % trigger? |
|---|---|---|
| **leakage** (share of primary in-window eligible boundaries whose trailing-900 s OFI path includes quotes `ofi_raw` would drop as degenerate/crossed) | mean ≈ **9.7×10⁻⁵**; max cell mean ≈ **0.0013**; `any_leakage_bug_flag = false` (0 / 40 cells) | **NO** |
| **co-travel** (`off_clock_cotravel_rate` among quintile-OFI eligible-class boundaries ignoring clock) | mean ≈ **0.615** (design ≈ 0.52) | **N/A** — REPORT only; never a park |

Leakage trigger did not fire. Co-travel is geometry diagnostic only.

## C.4 Per-symbol roll-up (κ = 0.146; primary = §1.1)

| symbol | σ₉₀₀ min L/S (bps) | viable_long cells | viable_short cells | in-window eps (all) | viable-region in-window | out-window eps (all) | viable-region out-window | elev-A / elev-B / calm (in-window all) | ≥ 100 viable in? |
|---|---|---|---|---|---|---|---|---|---|
| APP | 32.05 / 39.86 | **18 / 20** | 17 / 20 | 43 (31 L / 12 S) | **40** | 38 (25 L / 13 S) | **36** | 7 / 13 / 23 | no alone |
| RMBS | 37.74 / 45.21 | **16 / 20** | 12 / 20 | 25 (24 L / 1 S) | **19** | 67 (61 L / 6 S) | **53** | 2 / 9 / 14 | no alone |
| OLN | — | — | — | 0 (evidence-only) | — | 0 | — | — | never in D |

Pooled viable-region **in-window** episodes across D: **59 < 100**.
Pooled viable-region **out-window** (F2 arm, counts only): **89 < 100**.
Pooled all-cell (σ-unrestricted) in / out: **68 / 105** vs
design-central **147.7 / 160.1**.

**HOLIDAY-THIN (2025-12-26, 2025-12-30; never excluded):** APP HT
in-window = 3 (both HT cells non-viable-σ: σ = 21.50 / 26.42);
RMBS HT in-window = 2 (2025-12-26 non-viable; 2025-12-30 viable with
2 in / 2 out). HT contribution to pooled all-cell in / out = 5 / 8.
Tags reported; counts include them.

**Gate-arm occupancy (predicate arms 4–7 on, clock either side):**
in-window boundaries = 25 × 20 = 500 per symbol. APP gate_on = 81
(occupancy 0.162), gate_off = 419; RMBS gate_on = 92 (0.184),
gate_off = 408. Elevated strata denser than calm on a per-cell basis
for APP in-window; RMBS in-window sparse in elev-A (2). A and B
reported separately (L4), never pooled for conclusions.

**SELL-leg / long-only:** RMBS clears short σ min on 12/20 sessions
but has only **1** SHORT in-window episode on the full grid — σ
arithmetic alone does **not** force §1.6 long-only restatement at
census (measured short edge awaits step 2; park on power halts
before that).

## C.5 Park-condition scoring (§1.5 / §1.6 / §9.1; no discretion)

1. **Edge-region emptiness: FALSE.** Both APP and RMBS have
   non-empty viable-region primary in-window episodes (40 / 19).
2. **Power floor (pooled ≥ 100 contamination-excluded in-window):
   FAIL.** Pooled = **59**. Axis-split not required for the park
   itself (neither symbol failed deployability; re-check would still
   be 59 on D = {APP, RMBS}).
3. **Warm-drop: FALSE** for both symbols.
4. **Infrastructure (`calendar_missing_rate` / authoring): PASS.**
5. **Deployable-set arithmetic before power park:** D would be
   **{APP, RMBS}** (edge non-empty; warm-drop clear; calendars
   present). OLN never in D. Power park governs — card does not
   PROCEED.

**F2-arm adjudicability (reported now; JC-9):** out-window
viable-region n = **89 < 100** ⇒ **F2-INSUFFICIENT**. Per JC-9 an
out-window shortfall parks the binding arm at step 2 (no
primary-only PROCEED). Reported here even though step-1's park floor
is the **in-window** population — the in-window power FAIL already
halts the sequence.

**VERDICT: PARK — power (pooled viable-region in-window episodes =
59 < 100).**

**F2-arm adjudicability: F2-INSUFFICIENT (out-window viable-region n =
89 < 100).**

(Census instrument string `PARKED_POWER`; mapped to the frozen §9
verdict line above. H13 trigger **(a)** adjacency on census/design
death — activation requires Lei review under pack-11 DISPOSITIONS 2;
this task does not authorize H13 instruments.)

## C.6 Per-cell table (grid symbols; full JSON in artifact)

Columns: σ₉₀₀ (bps); viaL/viaS; in-eps / L / S; out-eps / L / S;
calendar warm; leakage mean; co-travel; gate ON/OFF; in-window
boundaries always 25.

| sym | date | stratum | σ₉₀₀ | viaL | viaS | in | L | S | out | oL | oS | warm | leak | cot | gON | gOFF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APP | 2025-11-25 | elev-A | 41.30 | Y | Y | 1 | 1 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 0.750 | 4 | 21 |
| APP | 2025-12-04 | elev-A | 63.10 | Y | Y | 2 | 2 | 0 | 0 | 0 | 0 | 1.00 | 0.0000 | 0.000 | 2 | 23 |
| APP | 2025-12-01 | elev-A | 58.87 | Y | Y | 3 | 3 | 0 | 4 | 3 | 1 | 1.00 | 0.0000 | 0.571 | 7 | 18 |
| APP | 2025-12-02 | elev-A | 58.33 | Y | Y | 1 | 0 | 1 | 2 | 2 | 0 | 1.00 | 0.0000 | 0.667 | 3 | 22 |
| APP | 2025-12-22 | calm | 32.87 | Y | n | 2 | 2 | 0 | 1 | 0 | 1 | 1.00 | 0.0000 | 0.333 | 3 | 22 |
| APP | 2026-01-05 | calm | 40.70 | Y | Y | 2 | 2 | 0 | 4 | 4 | 0 | 1.00 | 0.0000 | 0.667 | 6 | 19 |
| APP | 2026-01-15 | calm | 46.45 | Y | Y | 0 | 0 | 0 | 2 | 0 | 2 | 1.00 | 0.0000 | 1.000 | 2 | 23 |
| APP | 2026-01-26 | calm | 50.57 | Y | Y | 2 | 0 | 2 | 1 | 0 | 1 | 1.00 | 0.0000 | 0.333 | 3 | 22 |
| APP | 2026-01-27 | calm | 59.03 | Y | Y | 3 | 1 | 2 | 3 | 1 | 2 | 1.00 | 0.0013 | 0.500 | 6 | 19 |
| APP | 2025-12-26 | calm HT | 21.50 | n | n | 1 | 1 | 0 | 0 | 0 | 0 | 1.00 | 0.0000 | 0.000 | 1 | 24 |
| APP | 2025-12-30 | calm HT | 26.42 | n | n | 2 | 1 | 1 | 2 | 2 | 0 | 1.00 | 0.0000 | 0.500 | 4 | 21 |
| APP | 2026-01-12 | calm | 69.76 | Y | Y | 3 | 2 | 1 | 0 | 0 | 0 | 1.00 | 0.0000 | 0.000 | 3 | 22 |
| APP | 2026-01-20 | calm | 73.04 | Y | Y | 6 | 5 | 1 | 2 | 2 | 0 | 1.00 | 0.0002 | 0.250 | 8 | 17 |
| APP | 2026-01-22 | calm | 45.61 | Y | Y | 2 | 2 | 0 | 1 | 1 | 0 | 1.00 | 0.0002 | 0.333 | 3 | 22 |
| APP | 2026-04-01 | elev-B | 40.72 | Y | Y | 1 | 1 | 0 | 2 | 0 | 2 | 1.00 | 0.0000 | 0.667 | 3 | 22 |
| APP | 2026-04-10 | elev-B | 43.67 | Y | Y | 3 | 3 | 0 | 1 | 1 | 0 | 1.00 | 0.0000 | 0.250 | 4 | 21 |
| APP | 2026-04-22 | elev-B | 41.01 | Y | Y | 6 | 4 | 2 | 2 | 2 | 0 | 1.00 | 0.0002 | 0.250 | 8 | 17 |
| APP | 2026-04-02 | elev-B | 77.53 | Y | Y | 1 | 0 | 1 | 3 | 1 | 2 | 1.00 | 0.0000 | 0.750 | 4 | 21 |
| APP | 2026-04-07 | elev-B | 55.54 | Y | Y | 2 | 1 | 1 | 2 | 2 | 0 | 1.00 | 0.0003 | 0.500 | 4 | 21 |
| APP | 2026-04-16 | elev-B | 49.00 | Y | Y | 0 | 0 | 0 | 3 | 1 | 2 | 1.00 | 0.0000 | 1.000 | 3 | 22 |
| RMBS | 2025-11-25 | elev-A | 51.11 | Y | Y | 1 | 0 | 1 | 3 | 1 | 2 | 1.00 | 0.0000 | 0.750 | 4 | 21 |
| RMBS | 2025-12-04 | elev-A | 49.71 | Y | Y | 0 | 0 | 0 | 2 | 2 | 0 | 1.00 | 0.0000 | 1.000 | 2 | 23 |
| RMBS | 2025-12-01 | elev-A | 41.01 | Y | n | 0 | 0 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 1.000 | 3 | 22 |
| RMBS | 2025-12-02 | elev-A | 43.76 | Y | n | 1 | 1 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 0.750 | 4 | 21 |
| RMBS | 2025-12-22 | calm | 31.05 | n | n | 0 | 0 | 0 | 1 | 1 | 0 | 1.00 | 0.0000 | 1.000 | 1 | 24 |
| RMBS | 2026-01-05 | calm | 53.36 | Y | Y | 2 | 2 | 0 | 3 | 2 | 1 | 1.00 | 0.0000 | 0.600 | 5 | 20 |
| RMBS | 2026-01-15 | calm | 67.33 | Y | Y | 1 | 1 | 0 | 2 | 1 | 1 | 1.00 | 0.0000 | 0.667 | 3 | 22 |
| RMBS | 2026-01-26 | calm | 43.96 | Y | n | 1 | 1 | 0 | 4 | 3 | 1 | 1.00 | 0.0000 | 0.800 | 5 | 20 |
| RMBS | 2026-01-27 | calm | 43.74 | Y | n | 2 | 2 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 0.600 | 5 | 20 |
| RMBS | 2025-12-26 | calm HT | 19.58 | n | n | 0 | 0 | 0 | 4 | 4 | 0 | 1.00 | 0.0000 | 1.000 | 4 | 21 |
| RMBS | 2025-12-30 | calm HT | 46.13 | Y | Y | 2 | 2 | 0 | 2 | 2 | 0 | 1.00 | 0.0000 | 0.500 | 4 | 21 |
| RMBS | 2026-01-12 | calm | 32.87 | n | n | 3 | 3 | 0 | 5 | 5 | 0 | 1.00 | 0.0000 | 0.625 | 8 | 17 |
| RMBS | 2026-01-20 | calm | 75.90 | Y | Y | 3 | 3 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 0.500 | 6 | 19 |
| RMBS | 2026-01-22 | calm | 49.45 | Y | Y | 0 | 0 | 0 | 2 | 2 | 0 | 1.00 | 0.0000 | 1.000 | 2 | 23 |
| RMBS | 2026-04-01 | elev-B | 46.93 | Y | Y | 1 | 1 | 0 | 5 | 5 | 0 | 1.00 | 0.0000 | 0.833 | 6 | 19 |
| RMBS | 2026-04-10 | elev-B | 47.65 | Y | Y | 2 | 2 | 0 | 3 | 3 | 0 | 1.00 | 0.0000 | 0.600 | 5 | 20 |
| RMBS | 2026-04-22 | elev-B | 61.29 | Y | Y | 0 | 0 | 0 | 7 | 7 | 0 | 1.00 | 0.0000 | 1.000 | 7 | 18 |
| RMBS | 2026-04-02 | elev-B | 81.94 | Y | Y | 2 | 2 | 0 | 4 | 4 | 0 | 1.00 | 0.0000 | 0.667 | 6 | 19 |
| RMBS | 2026-04-07 | elev-B | 56.04 | Y | Y | 1 | 1 | 0 | 4 | 3 | 1 | 1.00 | 0.0000 | 0.800 | 5 | 20 |
| RMBS | 2026-04-16 | elev-B | 33.82 | n | n | 3 | 3 | 0 | 4 | 4 | 0 | 1.00 | 0.0008 | 0.571 | 7 | 18 |

Every grid cell emitted 26 RTH h=900 boundaries, **25** in the
09:35–15:50 window. OLN × 10 preamble: episodes = 0 by construction.

## C.7 Stop

§0 order lock: **stop for Lei review** before step 2 or any IC /
forward-return contact. No Phase-B YAML, sign-golden `evaluate`, or
outcome statistic in this task. **N = 12** unchanged.

*(Record appended 2026-07-17. Justification: Task 8-C-H12 step-1
execution; frozen bars scored without discretion.)*

---
