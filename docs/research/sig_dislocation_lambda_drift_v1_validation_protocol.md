<!--
  File:   docs/research/sig_dislocation_lambda_drift_v1_validation_protocol.md
  Status: PRE-REGISTERED — FROZEN AT TASK 9 START (Task 8-F-H8
          rulings, Lei, 2026-07-12: JC-1 approved count-basis-primary;
          JC-2/4/5/6/7/8/9 approved as proposed/amended; JC-3 approved
          with the §9 PARK consequence mapping; JC-10 approved
          conditional — the §1.7 mechanical κ-adjustment rule is
          pinned. Rulings recorded per-JC in §11.) Written BEFORE any
          implementation exists and BEFORE any outcome statistic was
          computed for this candidate. From this freeze commit,
          changes go ONLY in an appended AMENDMENTS section with
          timestamp and justification. No forward return, IC, or
          outcome statistic was computed in producing this file.
  Owner:  research-workflow (protocol + ledger) / microstructure-alpha
          (candidate); prompt-pack Task 8, Phase B.

  Provenance (FQ-3 template):
    git_sha: "8c69d49f4c45ff0652440a42ed786026b35471fb"
    worktree_clean: "yes at task start except the prior task's three
      untracked artifacts (sig_dislocation_lambda_drift_v1_formal_spec.md,
      scripts/research/h8_contamination_read.py,
      docs/research/h8_contamination_read_results.json) and this file"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (protocol authoring only; zero data contact)"
    normative_inputs:
      sig_dislocation_lambda_drift_v1_formal_spec.md (H8 spec §1–§16
        incl. §2 Amendment-C read, §5 κ freeze + floors, §14 ledger,
        Appendix A per-cell instrument),
      sig_inventory_fade_v1_validation_protocol.md (H2 frozen protocol
        — STRUCTURAL TEMPLATE per task Amendment A; §11 8-F rulings
        carried verbatim; CENSUS RESULTS C.2 method conventions),
      scripts/research/h8_contamination_read.py +
        docs/research/h8_contamination_read_results.json (the
        Appendix-A census instrument, pinned by task Amendment B),
      prompt_pack_03c_universe_and_cache.md (closed grid §5.1, L1–L4
        verbatim, realized tick buckets §7, median bids),
      prompt_pack_00b_edge_units_convention.md (one-way convention),
      prompt_pack_00c_eval_canon.md (pinned realism profile at commit
        825a7bc3bda48d3a819fed0a498dbf9d65e711c4; zero-latency ban),
      prompt_pack_03b_print_eligibility.md (§3.3 Class table, §4.4
        correction netting — via spec §1.5),
      prompt_pack_06_hypothesis_slate_b.md (H8 card, trial ledger),
      prompt_pack_05_horizon_feasibility_map.md (σ₃₀₀ medians, floors),
      prompt_pack_12p_router_fill_timing_parity.md (Task 12-P AXIS-1
        VERIFIED 2026-07-12 — the step-7/8 precondition record),
      docs/research/gas_01_integrated_ofi.md / gas_02 (ENG-3
        sign-golden + IC-gate precedent),
      .cursor/skills/microstructure-alpha/research-protocol.md
        (Phase 3 stratification, ~100-obs rule, Phase 5 IC(t) fit),
      src/feelies/research/{cpcv.py, dsr.py, forward_ic.py},
      src/feelies/alpha/promotion_evidence.py (GateThresholds),
      src/feelies/forensics/cost_survival.py (verdict vocabulary),
      src/feelies/bootstrap.py (_HORIZON_FEATURE_FACTORIES h=300
        wiring), src/feelies/features/impl/{horizon_windowed.py,
        rolling_stats.py} (window semantics for the embargo
        arithmetic), scripts/{sensor_feature_ic.py,
        regime_diagnostics.py}, src/feelies/harness/backtest_cli.py
        (--inv12-stress) (all read this session; citations inline).
-->

# `sig_dislocation_lambda_drift_v1` — pre-registered validation protocol (Task 8)

This protocol fixes, numerically and in execution order, every test the
candidate must pass — **before** any implementation exists and before
any outcome statistic is computed. It binds Task 8 (measurement),
Task 9 (implementation), and the Task-12-gated execution overlay. The
frozen H2 protocol is the structural template (task Amendment A): its
locked order, machinery grounding, and 8-F rulings are reused verbatim;
only what H = 300 changes is re-derived (embargo arithmetic §3.1,
annualization §3.3, and the GateThresholds implication — none, §3.3).

**Freeze rule.** From the freeze commit this file is immutable except
for an appended `AMENDMENTS` section (timestamp + justification per
entry). Converting any FAIL below by tuning is prohibited: **any
post-hoc parameter change is a new trial — N increments and the change
is logged in the ledger (§10) before the re-run.** Simulator-knob
perturbations inside the pre-registered §8 grid do not increment N
(the grid's pass criterion is conjunctive — it can only reject); any
change to alpha-side parameters (`lambda_percentile_min`,
`edge_scale_bps` outside the §3 calibration procedure, `edge_cap_bps`,
the dislocation constants, gate thresholds, exit ages, session
constants) does.

**Two validity axes, never conflated (session constraint 5).** Steps
1–6 establish *statistical* validity on pre-cost / disclosure-
arithmetic quantities; steps 7–8 establish *execution* validity on the
Task-12-parity-cleared machinery. No number from steps 1–6 is ever
presented as an economic result, and no number produced before the
Task-12 router timing-parity check is presented as a result at all.

**Evidence set (closed).** Symbols **{APP, RMBS}** (the spec §5
deployable candidates; APP primary, RMBS secondary park-armed) ×
the 10 frozen 03c dates: `2025-11-25, 2025-12-04` (elevated episode A),
`2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27` (calm),
`2026-04-01, 2026-04-10, 2026-04-22` (elevated episode B). **OLN × the
same 10 dates is added evidence-only for the §2.4 tick-artifact tests
(spec §8); it is excluded from deployable economics, CPCV, DSR, and
the execution overlay — never in D.** No addition or substitution
without a protocol amendment.

The 03c known limitations are carried **verbatim** into every stratum
definition and every downstream artifact (L1 attaches unconditionally
to every calm-stratum conclusion; L3 lands directly on RMBS, this
card's secondary symbol — spec §10):

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

**Single-stress anchor (8-F §11.1 ruling, carried verbatim — NO
stacking, ever).** The stressed floor applies the Inv-12 1.5× stress
**once** to the one-way passive cost stack:
`floor = 1.5 × 1.5 × (2.0 + fee) = 2.25 × (2.0 + fee)`. It is never
combined with a simultaneously stressed adverse-selection vertex or
any other stressed axis; the adverse-selection axis is tested where it
belongs — the §8 sensitivity grid, on measured execution economics,
binding within the neighborhood — never inside a pre-data floor.

---

## 0. PRECONDITIONS (verified before step 1 executes)

| # | precondition | status at protocol write |
|---|---|---|
| P0-1 | Feature wiring | **NO wiring pre-step exists for H8** (contrast H2's h=120 commit): all four consumed features (`micro_price_drift`, `micro_price`, `kyle_lambda_60s_percentile`, `realized_vol_30s_zscore`) are factory-wired at every horizon incl. h=300 (`bootstrap.py` `_HORIZON_FEATURE_FACTORIES`, verified this session; the Appendix-A read runtime-asserted it on all 20 cells). The census re-asserts it at runtime (the read's assertion, carried). |
| P0-2 | Grid inputs CLEARED | 03c FQ-6A-R re-check table: CLEARED 2026-07-11 |
| P0-3 | Realism profile pinned | 00c profile at commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`; configs with `backtest_fill_latency_ns == 0` are invalid for evidence (00c decision A) |
| P0-4 | Determinism discipline | every scripted run: `PYTHONHASHSEED=0`, direct `DiskEventCache` read (`~/.feelies/cache`), replay through the real pipeline; provenance (git SHA, command line, artifact SHA-256) recorded per run; bit-identical re-run required for the census artifact (H2 C.7 precedent) |
| P0-5 | Step-1 census executes only after this file is FROZEN (post-§11 rulings) and committed | the protocol freezes BEFORE the census runs |
| P0-6 | Task-12 router timing-parity (steps 7–8 gate) | **AXIS-1 VERIFIED 2026-07-12** (`prompt_pack_12p_router_fill_timing_parity.md`; regression guards committed). Re-verified green at step-7 execution time; any AXIS-1 regression re-opens the gate. |

Execution order is **locked**: 1 → 2 → 3 → 4 → 5 → 6 → (7 → 8) with
steps 7–8 additionally gated on P0-6. A step does not begin until the
prior step's outputs are committed. A park/reject at any step halts
the sequence.

---

## 1. STEP 1 — PARK-RULE CENSUS (spec §5 / NEXT ACTION governs; episode instrument PINNED per task Amendment B)

Offline deterministic scan of the 20-cell {APP, RMBS} × 10-date grid
(OLN × 10 added evidence-only for §2.4 inputs). **NO forward returns
are computed anywhere in this step** — the only return-like quantity
permitted is the *unconditional* session volatility σ₃₀₀ (std of
non-overlapping 300 s mid log-returns over RTH, in bps), which
conditions on nothing signal-related.

### 1.1 Episode definition — the Appendix-A instrument, EXACTLY (integrity pin)

An **eligible boundary (= one episode)** is an h=300
`HorizonFeatureSnapshot` boundary satisfying ALL of the following,
**as instantiated in `scripts/research/h8_contamination_read.py` at
git 8c69d49 — same gate arms, same thresholds, same warm handling,
same regime machinery** (task Amendment B):

1. session window: boundary offset ≥ 300 s from the 09:30 ET session
   open (`rth_open_ns` anchor) on the **nominal** `boundary_ts_ns`,
   AND boundary ET clock ≤ 15:50:00 (boundaries at exactly 15:50
   included, per the read);
2. all four ids `{kyle_lambda_60s_percentile, micro_price_drift,
   micro_price, realized_vol_30s_zscore}` **warm and not stale** at
   the boundary;
3. `kyle_lambda_60s_percentile ≥ 0.5` (the median split; frozen);
4. `|micro_price_drift| / micro_price ≥ disloc_min(symbol)` with the
   frozen constants `disloc_min(APP) = 25.3563e-4`,
   `disloc_min(RMBS) = 23.7165e-4` (0.75 × pack-05 median σ₃₀₀,
   as fractions of the micro-price level);
5. `P(vol_breakout) < 0.7` on the latched `hmm_3state_fractional`
   posterior (reference defaults; per-session causal-prefix
   calibration on the first ≤ 100,000 RTH quotes; advanced once per
   quote before the boundary is read);
6. `realized_vol_30s_zscore ≤ 3.0`.

Pipeline pins carried from the read verbatim: RTH filter
09:30 ≤ t < 16:00 ET on `exchange_timestamp_ns`; events sorted by
`(timestamp_ns, sequence)`; reference `platform.yaml` sensor params
(`kyle_lambda_60s` 2.0.0 `min_samples=30, alignment="causal"`;
`micro_price` 1.1.0 `warm_after=1, warm_window_seconds=60`;
`realized_vol_30s` 1.3.0 `window_seconds=30, warm_after=16`);
h=300 features from the production `_HORIZON_FEATURE_FACTORIES`;
fresh sensor/regime state per session. Consecutive boundaries' 60 s
λ windows are disjoint (300 ≫ 60): one boundary = one independent
conditioning window; no double-counting correction.

**Deviations from the Appendix-A instrument (task Amendment B: each
listed with count-direction; NONE is permissive — nothing here can
inflate the counts above the read's 81/77):**

| # | deviation | count-direction | justification |
|---|---|---|---|
| 1 | primary counts apply the contamination exclusion of §1.3 (the read counted conditioning boundaries WITHOUT exclusion — 81/77 are including-flagged) | **deflating** | Amendment C(ii) demands a contamination-excluded power count; instrument choice is JC-1 (§11) because the H2 binary convention saturates on H8 — see §1.3. Cannot affect the park verdict (§1.5). |
| 2 | additive outputs only: long/short split, realized σ₃₀₀, viability labels, gate×stratum 2×2, spread-in-ticks distribution, per-id warm coverage | **neutral** | reporting extensions; the episode predicate is untouched |
| 3 | the census script is committed (`scripts/research/dislocation_lambda_census.py`, Task-9-adjacent deliverable) vs the read's one-off uncommitted script; logic transplanted verbatim | **neutral** | provenance/reproducibility (P0-4); a runtime assertion pins the entry predicate to the constants above |
| 4 | OLN cells replayed alongside (evidence-only, §2.4 inputs; OLN uses no `disloc_min` gate — full boundary/spread reporting only, never episode counts toward D) | **neutral** | spec §8 test bed; OLN never deployable |

Any further deviation discovered at implementation time halts the
census for a protocol amendment — it is not patched silently.

### 1.2 Frozen viable-region definition (numeric, before execution)

κ = **0.190, FROZEN** (spec §5.1; one-way ratchet — revisable down on
evidence, never up; superseded entirely by the measured conditional
edge once step 2 has run). Per-symbol single-stress floors (spec
§5.2, 8-F §11.1 anchor, one-way, per-fill, bps of fill notional; fees
at the 80-share reference fill against pack-05 median RTH bids APP
$544.075, RMBS $102.06):

| symbol | fee (bps) | C_ow = 2.0 + fee | floor = 2.25 × C_ow (bps) | σ₃₀₀ min = floor/κ (bps) | short rider-incl. floor (bps) |
|---|---|---|---|---|---|
| APP  | 0.0804 | 2.0804 | **4.6809** | **24.64** | 5.82 |
| RMBS | 0.4287 | 2.4287 | **5.4645** | **28.76** | 6.60 |

A (symbol, session) cell is **in the viable region** iff its realized
session σ₃₀₀ ≥ the symbol's σ₃₀₀ min. σ₃₀₀ estimator (recorded, not
tuned; the H2 C.2 convention at H = 300): Bessel-corrected sample std
of non-overlapping 300 s mid log-returns on the 09:30-anchored grid
(last-mid-at-or-before sampling, ~77 returns/session), in bps.
SELL-leg viability uses the rider-inclusive short floor column (spec
§5.2 short-side rider: +0.5 bps regulatory + TAF).

### 1.3 Contamination handling (per spec §1.5; instrument RULED — JC-1 APPROVED, 8-F-H8)

Every eligible boundary's trailing 60 s window is scored against the
03b §3.3 Class-B exclusion set {2, 7, 8, 9, 10, 13, 15, 16, 17, 22,
29, 32, 35, 52, 53} ∪ `correction ∈ {10, 11, 12}` (the read's flag
set, verbatim). **Three counts are always reported per cell:**

- **(a) including-flagged** — the Appendix-A instrument's own count
  (reproduces 81/77 pooled by construction);
- **(b) intensity-excluded (PRIMARY — ruled)** — excludes a boundary
  iff its own trailing-60 s window flagged-print share is ≥ **2.0 ×**
  the session tape base rate on the **count basis** (the frozen §2
  materiality criterion applied at boundary granularity; the
  volume-basis share and its exclusion count are **reported**
  alongside, never binding);
- **(c) binary-excluded (the H2 convention)** — excludes on any
  flagged print in the window. Disclosed for continuity; on H8 it
  saturates (read: APP 98.8 % / RMBS 79.2 % of conditioning
  boundaries carry ≥ 1 flag — the saturation the §2 intensity
  criterion was pre-registered to avoid; at APP print rates a 60 s
  window holds O(300) prints, so P(any flag) ≈ 1 at a 3 % base rate
  and the binary measures window length, not λ-input contamination).

The **power floor and all primary downstream statistics bind on (b)**;
(a) and (c) are reported alongside at every step (the spec §1.5
both-ways rule). The binary→intensity instrument change relative to
the H2 template is **logged as a template deviation** (ruled 8-F-H8;
justification = the saturation finding above; count-directions per
the §1.1 deviation table row 1). **The identical instrument — 2.0×,
count-basis-binding, volume-reported — governs any re-census under
§1.7**; it is not re-chosen per variant. Statistics on the
03b-filtered NEW λ fallback variant are NOT computed here (it stays
drafted-not-evaluated, spec §14).

### 1.4 Census outputs (all per symbol × session × daily stratum)

- eligible-episode counts per §1.3 (all three counts), split
  continuation-long (`micro_price_drift > 0`) / continuation-short
  (`< 0`) — the SHORT split feeds the RMBS long-only restatement rule
  (§1.6);
- sensor warm coverage per entry-warm id (spec §1.1; the RMBS
  coverage rule applied: λ warm < 0.5 on > 2 sessions drops the
  symbol — coverage/power, not tuning);
- realized session σ₃₀₀ (bps) and the cell's viable/non-viable label
  (long floor and short rider-inclusive floor separately);
- the (intraday gate state × daily stratum) 2×2 boundary table (spec
  §10(i)); gate ON = the full §1.1 predicate arms 3–6 on warm
  boundaries;
- spread-in-ticks distribution at eligible boundaries AND at all
  warm in-window boundaries, per symbol incl. OLN (spec §8 test 1;
  feeds §2.4 and the §4 strata);
- per-stratum episode counts for elevated-A / elevated-B / calm
  (L4: episodes A and B reported separately, never pooled).

### 1.5 Park conditions (numeric; either parks the card) — and the pre-determined outcome, disclosed

- **Edge-region emptiness (Amendment C(i)):** for every grid symbol,
  the viable region (cells with σ₃₀₀ ≥ σ₃₀₀ min at frozen κ = 0.190)
  contains zero primary eligible episodes → **PARK**.
- **Power floor (Amendment C(ii) / spec §5.3):** a symbol is
  *deployable-candidate* only if its viable-region primary episode
  count is **≥ 100**. If no grid symbol clears 100, the card **PARKS
  on power** before a single IC number exists. Cells/strata below the
  floor report INSUFFICIENT, never pooled away.

**Honesty disclosure (integrity-critical, stated before execution):
the power outcome is already arithmetically determined.** The census
instrument is pinned to the Appendix-A read (§1.1) on the same frozen
20 cells, so the including-flagged conditioning counts will reproduce
**APP 81, RMBS 77 — both < 100 even before viability restriction or
contamination exclusion, which only deflate**. Barring an instrument
defect discovered at execution, step 1 therefore **parks the card on
power deterministically**, exactly as the spec §2 incidental density
observation foreshadowed (realized joint conditioning fraction
≈ 0.10–0.11 vs the card's assumed 0.226). The census still executes
in full: it is the pre-registered adjudicating instrument (the
incidental read is not), and its σ₃₀₀-viability axis, long/short
split, warm coverage, 2×2 table, and spread-in-ticks outputs are the
required inputs to the Amendment-D post-park decision and to any
future variant's design (census-legal, no returns). No threshold may
be re-tuned in response to any census output within this trial.

### 1.6 Deployable-set restatement rules (Amendment C(iii), pre-registered)

The census fixes the deployable candidate set
**D = {symbols with ≥ 100 viable-region primary episodes}**, with:

- **RMBS long-only restatement:** if RMBS fails the SELL-leg axis —
  κ·σ₃₀₀ against the rider-inclusive short floor 6.60 bps (already
  closed at the pack-05 median: κ·31.622 = 6.01 < 6.60; the census
  applies per-session realized σ₃₀₀) — RMBS restates **long-only**
  and its power floor re-checks on the continuation-long episode
  count alone (spec projection ≈ 55 < 100 ⇒ RMBS expected to drop).
- **RMBS fails either axis (edge viability or power) ⇒ the card
  restates as APP-only**; all downstream steps run on D = {APP}.
- **APP fails power ⇒ the card PARKS** regardless of RMBS (APP is
  the primary; an RMBS-only deployable claim was never registered).
- OLN is never in D.

### 1.7 Post-park path (task Amendment D, pre-registered now)

If (as pre-determined, §1.5) the census parks on power: **exactly ONE
occupancy-based re-threshold variant may be registered** and
re-censused under this protocol from step 1. Binding rules:

- **Mechanism-derived, occupancy-only derivation, disclosed in the
  ledger row before the re-census:** the λ split stays at the median
  (p₀ = 0.5 — the split IS the mechanism claim, not a tuning axis);
  only the dislocation multiple m (frozen 0.75 in the primary) may
  re-derive, from **census-legal occupancy identities alone** — the
  realized boundary-level distribution of `|micro_price_drift| /
  micro_price` on warm in-window boundaries (no forward returns, no
  IC, no outcome contact) — targeting the card block-2 design
  occupancy (joint conditioning fraction ≈ 0.226) that the frozen
  thresholds failed to realize. The derivation arithmetic is
  disclosed verbatim in the ledger row and in the re-census record.
- **Mechanical κ adjustment (JC-10 condition, pinned now; ruled
  8-F-H8):** the variant's park arithmetic uses
  **κ_variant = min(0.190, κ_frozen × c_D(m_v) / c_D(0.75))** where
  m_v is the re-derived dislocation multiple and
  **c_D(m) = φ(m) / (1 − Φ(m))** — the standard-normal inverse Mills
  ratio, i.e. E[|z| : |z| ≥ m] under the SAME near-Gaussian identity
  the card's frozen c_D used (check: c_D(0.75) = 0.3011/0.2266 =
  1.329 ≈ the card's 1.33 ⇒ the ratio form is exact at m = 0.75 and
  independent of the 1.3 rounding). All other κ factors (f_perm,
  r_rem, f_H, f_pass) are untouched. Because c_D(m) is increasing in
  m, any occupancy-raising m_v < 0.75 mechanically LOWERS κ_variant —
  the adjustment can only tighten the variant's σ₃₀₀ viability floors
  (floor / κ_variant ≥ floor / 0.190); the explicit
  κ_variant ≤ 0.190 cap makes the one-way ratchet structural. The
  variant's per-symbol σ₃₀₀ min and viable region re-derive from
  κ_variant with the §1.2 floors unchanged. No non-mechanical input
  enters; if the derivation ever needs a quantity outside these
  identities plus the census occupancy read, it **stops for Lei
  review** instead of proceeding.
- The variant is **one ledger row, N-neutral until outcome contact**
  (census-class evaluation of the variant is N-neutral per the 8-F
  C.6 rule; its first IC/forward-return contact is +1 N).
- **Iterative occupancy fishing is prohibited:** a second re-threshold
  requires Lei's explicit approval with reasons, and any
  outcome-informed threshold choice is data-contact tuning (+1 N,
  logged, and presumptively rejected).
- The re-censused variant must clear the SAME park conditions (§1.5)
  and then re-enter this protocol at step 2 unchanged; all §5.2
  floors, κ ratchet, and units conventions carry.

---

## 2. STEP 2 — SIGN-GOLDEN + IC GATE (ENG-3 precedent, gas_01/gas_02)

Per the repo's own promotion policy (engine-readiness ENG-3, as
exercised in `docs/research/gas_01_integrated_ofi.md`): **no promotion
of the signature without BOTH (a) and (b).**

### 2.1 (a) Sign-golden through the REAL pipeline

Synthetic tape with known ground truth pushed through the real
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (the
gas-01 pattern); new test module
`tests/research/test_gas_dislocation_lambda_sign.py` (Task 9
implements; assertions fixed here):

1. **Informed-continuation golden (LONG):** a synthetic tape whose
   final 300 s window carries an upward micro-price dislocation
   ≥ `disloc_min(APP)` produced by trades with high price impact
   (signed flow and Δmid positively aligned; ≥ 30 causal (Δp, Δq)
   pairs in the trailing 60 s so λ is warm), with the trailing-300 s
   λ series ramped so the boundary λ sits above its window median ⇒
   the h=300 snapshot carries `micro_price_drift > 0`,
   `kyle_lambda_60s_percentile ≥ 0.5`, **and the raw
   `kyle_lambda_60s` reading is > 0** (the causal estimator's sign
   convention, P1-5 precedent) ⇒ the §6.2 draft `evaluate` (once
   implemented) emits direction **LONG** — trade WITH the
   dislocation.
2. **Mirror golden (SHORT):** the same tape mirrored ⇒
   `micro_price_drift < 0` ⇒ SHORT.
3. **λ-contrast golden (THE card-defining assertion):** the same
   dislocation magnitude produced with LOW impact (large Δq, small
   Δp; trailing λ series ramped down so the boundary percentile
   < 0.5) ⇒ `evaluate` returns **None** — no signal without the
   impact fingerprint. This is F2 in golden form.
4. **Warm-gate golden:** < 30 (Δp, Δq) samples in the trailing 60 s
   ⇒ `kyle_lambda_60s` not warm ⇒ the percentile id not warm ⇒ entry
   suppressed (required-warm set, spec §1.3).
5. **h=300 key-presence golden:** the snapshot at h=300 carries all
   four consumed ids (factory wiring regression lock, P0-1).

Any assertion failure ⇒ **REJECTED (sign/wiring defect)** — fix is an
implementation correction, not a tuning event (N unchanged), but the
gate must re-run from scratch.

### 2.2 (b) RankIC evidence — thresholds and sessions fixed now

**Harness:** `scripts/sensor_feature_ic.py` extended (Task 9) with an
H8 row: sensors `kyle_lambda_60s` (2.0.0 causal), `micro_price`
(1.1.0), `realized_vol_30s` (1.3.0) at reference params; features =
the four consumed ids at h = 300; each warm boundary paired with the
forward mid log-return over the snapshot horizon; statistics via
`research/forward_ic.py` (`spearman_ic`, `bucketed_forward_return`,
`long_short_edge_bps`). The harness extension is measurement plumbing
for the pre-registered primary trial, not a new trial.

**IC variable (fixed now — the card is a conditional-contrast
hypothesis, not a monotone-sensor hypothesis; JC-3):** the primary
IC pair is `x = micro_price_drift / micro_price` (signed dislocation
fraction) vs `y` = signed forward 300 s mid log-return, computed
**within λ strata**: the λ-elevated stratum
(`kyle_lambda_60s_percentile ≥ 0.5`) carries the mechanism prediction
RankIC(x, y) > 0 (continuation); the λ-baseline stratum (< 0.5) is
the pre-registered contrast (reversion or zero — a positive IC there
too means the λ arm does no work; F2/I-1 companion).

**Sessions (named now, the closed set):** the 20 cells {APP, RMBS} ×
the 10 preamble dates. Primary evidence = pooled over the census
deployable set D restricted to viable-region sessions; the full
20-cell set is reported for context. Contamination-excluded per §1.3
primary; reported all three ways.

**Numeric gate (ALL required, at h = 300):**

| criterion | threshold |
|---|---|
| λ-elevated pooled RankIC sign | > 0 (continuation-correct) |
| λ-elevated pooled \|RankIC\| | ≥ 0.03 |
| λ-elevated pooled significance | Fisher-z two-sided p ≤ 0.01 |
| pooled sample minimum | n ≥ 1,000 warm boundaries in the λ-elevated stratum pooled over D (else INSUFFICIENT — the gate cannot pass or fail). Feasibility disclosure (JC-3): at 78 bars/session the full two-symbol grid holds ≈ 745 λ-elevated warm boundaries — the bar is reachable only on a two-symbol D with high warm coverage; on D = {APP} alone (≈ 380) the gate is INSUFFICIENT by construction. **Ruled consequence (8-F-H8): D = {APP} with no legal path to n ≥ 1,000 ⇒ PARK — evidence-infrastructure class (H4 precedent), not hypothesis-revise, never threshold rescaling** (§9). |
| λ-contrast (F2 anchor) | λ-elevated-stratum RankIC minus λ-baseline-stratum RankIC > 0, AND the λ-baseline conditional continuation edge on matched dislocations is ≤ 0 within 2 SE (not significantly positive) |
| per-symbol (each symbol in D) | λ-elevated RankIC > 0 with n ≥ 100 in the viable region; a symbol failing sign or n drops out of D (n < 100 ⇒ INSUFFICIENT ⇒ out of D per §1.5 power rule) |
| bucket monotonicity | `bucketed_forward_return` (5 equal-count buckets of x, λ-elevated stratum): top-minus-bottom forward-return spread (`long_short_edge_bps`) positive in the continuation direction |
| conditional tail (F1 anchor) | mean continuation-signed 300 s forward return on primary eligible episodes > 0 with t ≥ 2 pooled over D |

The gas-01 lesson binds: single-tape results are indicative only; the
gate is evaluated **pooled** and per-symbol as above, never on one
(symbol, date).

The criteria are **deliberately conjunctive** (8-F ruling, carried
verbatim): the p ≤ 0.01 bar binds at moderate n, and the
|RankIC| ≥ 0.03 floor rejects effects that are trivial-in-magnitude
yet significant at huge n. Neither alone is sufficient.

### 2.3 Measured-edge anchor (spec §5.2/§6.5 acceptance test)

The measured conditional edge (mean continuation-signed 300 s forward
return on primary eligible episodes, bps one-way, per symbol in D,
viable region) must be **≥ the per-symbol single-stress floor**
(APP 4.6809, RMBS 5.4645 bps) for the symbol to remain in D; SELL-leg
edges are additionally tested against the rider-inclusive short
floors (APP 5.82, RMBS 6.60 bps — the RMBS long-only restatement rule
re-applies here on measured evidence). This measured value supersedes
all κ arithmetic from this point (spec §5.1 one-way ratchet) and
becomes the G12 disclosure input (`edge_estimate_bps` = the D-set
minimum measured edge, conservative, per spec §6.5). If D empties
here, the card parks.

### 2.4 Tick-constraint artifact tests (spec §8, pre-registered design)

Run alongside the IC gate (evidence set including OLN):

1. spread-in-ticks distribution **at eligible boundaries** (not
   pooled) per symbol — λ-elevation conditioning may select grid
   states the pooled medians hide (thin books widen spreads AND
   inflate λ; θ₂'s grid twin);
2. **≥ 4-tick-stratum re-derivation:** conditional continuation edge
   re-estimated on boundaries with prevailing spread ≥ 4 ticks
   (APP/RMBS qualify structurally: pooled medians 61/22 ticks); pass
   = sign-consistent with the full-sample estimate; collapse ⇒
   pooled effect was grid artifact ⇒ restate economics on the
   surviving stratum (definition kill on the affected stratum, spec
   §11 tick axis);
3. **OLN quantum test:** conditional 300 s move mass vs the
   ±1 half-tick quantum (≈ ±2.1 bps at OLN levels); continuation
   mass sitting at exactly the quantum with no continuous tail ⇒
   grid bounce, not incorporation; genuine persistence must show
   mass beyond one quantum and σ-normalised agreement with the
   wide-bucket estimate. Additionally report OLN's λ-percentile vs
   spread-in-ticks correlation (is the λ arm a grid detector on a
   constrained grid?). Evidence finding only — OLN is never
   deployable;
4. sign difference across buckets after quantum correction ⇒
   **definition-level kill**.

---

## 3. STEP 3 — CPCV (`research/cpcv.py`)

### 3.1 Configuration (numeric, with the H=300 re-derivation — task Amendment A)

Run **per symbol in D**, on that symbol's 10 grid sessions.

- **Bar** = one h=300 boundary; RTH 09:30–16:00 = 23,400 s ⇒ **78
  bars/session** (confirmed: the Appendix-A read emitted exactly 78
  RTH h=300 boundaries per cell), `n_bars ≈ 780` per symbol (exact
  count = emitted boundaries; sessions never concatenate state —
  sensors and regime engine re-warm per session replay, so
  cross-session leakage through sensor state is zero by
  construction).
- **Groups:** `n_groups = 10` — one contiguous group per grid session
  in calendar order (group boundaries coincide with session
  boundaries).
- **k:** `k_test_groups = 2` ⇒ φ = C(10,2) = **45 combinations**,
  paths = C(9,1) = **9 reconstructed paths ≥ 8** (`cpcv_min_folds` ✓).
- **Purge:** `label_horizon_bars = 1`. Derivation: the label is the
  300 s forward mid return ⇒ label span = 300 s = 1 bar exactly.
- **Embargo:** `embargo_bars = 3`. Derivation (bars shown, per
  Amendment A): a post-test training bar's entry features look back
  through **two nested time-bounded windows** — the h=300
  event-time reducer window (`micro_price_drift` delta and the
  `kyle_lambda_60s_percentile` rank both aggregate over the trailing
  **300 s**, `HorizonWindowedFeature` semantics) whose λ inputs are
  each an OLS over the trailing **60 s** trade window ⇒ deepest
  time-bounded lookback = 300 + 60 = **360 s**. Required forward
  exclusion after a test region = label span 300 s (covered by the
  1-bar purge) + 360 s feature lookback ⇒ residual 360 s ⇒
  ⌈360/300⌉ = **2 bars minimum**. Adopted **3 bars = 900 s** — the
  extra bar conservatively covers the two entry-path components with
  **no fixed time constant**: `realized_vol_30s_zscore`'s
  2000-reading count window (`RollingZscoreFeature` default —
  quote-rate-dependent, minutes on APP, longer on thin RMBS
  stretches; bounded structurally by the session-aligned groups and
  per-session sensor reset, so only within-session adjacency leaks)
  and the quote-clocked HMM posterior (spec §4 tick-dwell caveat).
  Total forward exclusion = 1 + 3 = **4 bars = 1,200 s** per test
  region. `embargo_bars = 3 ≥ cpcv_min_embargo_bars = 1` ✓; the
  block-bootstrap block length is `max(1, embargo_bars) = 3` bars
  (the declared serial-correlation length), per `build_cpcv_evidence`.

### 3.2 Return series and per-split training (the CPCV contract)

Per-bar return series per symbol: at each boundary, the
**continuation-signed 300 s forward mid log-return minus the
round-trip-derived cost 2 × C_ow,stressed(symbol)** — C_ow,stressed =
1.5 × (2.0 + fee) = APP 3.1206 / RMBS 3.6431 bps one-way, so the
deduction is APP 6.2412 / RMBS 7.2861 bps — **if the boundary is
entry-eligible under the full frozen rule** (§1.1 conditions + the
`evaluate` EV gate with the split's trained `edge_scale_bps`), else
**0.0**. This is a *statistical-validity* series — a
disclosure-arithmetic cost proxy, not an execution result (fill
realism enters only at steps 7–8).

Per-split training (the CPCV caveat honored — the caller retrains per
combination): on each of the 45 splits, `edge_scale_bps` is
re-estimated on the split's purged+embargoed **train** bars (OLS of
continuation-signed forward return on the spec §6.2 normalised
exceedance `excess = 0.5 × (d_x + l_x)`, through the origin, clipped
to the declared range [6.0, 16.0]) and applied to the **test** bars
through the frozen `evaluate` rule. All other parameters are frozen
at spec defaults (`lambda_percentile_min = 0.5`,
`edge_cap_bps = 12.0`, the per-symbol `disloc_min` and floor
constants, gate thresholds §6.3). This in-protocol calibration is
part of the single pre-registered primary trial; it does not
increment N.

**Dual reporting (8-F ruling, carried verbatim):** the **PRE-COST
path distribution** (same series without the 2 × C_ow,stressed
deduction) is computed and reported **alongside the cost-adjusted one
at every step** that quotes CPCV output — the pass/fail **criterion
stays on the cost-adjusted series**. The pre-cost distribution is
diagnostic context (separating "no continuation exists" from
"continuation exists but below the cost proxy"), never a result.

### 3.3 Annualization and thresholds (H=300 re-derivation; GateThresholds implication: NONE)

`annualization_factor = sqrt(78 × 252) = sqrt(19,656) ≈ 140.20`
(bars/session × trading days/year — the sqrt(252)-commensurate
scaling for 300 s bars), passed to `build_cpcv_evidence` so emitted
Sharpes are annualised and directly comparable to the
`GateThresholds` defaults. Bootstrap: `n_bootstrap = 10,000`,
`seed = 0` (Inv-5 bit-identical).

**Thresholds: the `GateThresholds` defaults, NO per-alpha
`gate_thresholds:` override — none is needed and none is
pre-registered** (stated explicitly per Amendment A: H = 300 changes
nothing here — 9 paths ≥ 8, embargo 3 ≥ 1, and the annualised Sharpe
and p-value bars are horizon-independent once the annualization
factor is commensurate):

| gate | value | this run |
|---|---|---|
| `cpcv_min_folds` | ≥ 8 reconstructed paths | 9 by construction |
| `cpcv_min_mean_sharpe` | ≥ 1.0 (annualised) | must clear on **every** symbol in D |
| `cpcv_max_p_value` | ≤ 0.05 (block bootstrap) | every symbol in D |
| `cpcv_min_embargo_bars` | ≥ 1 | 3 by construction |

Fail on any symbol ⇒ that symbol leaves D; D emptying ⇒ status per §9.

---

## 4. STEP 4 — REGIME STRATIFICATION (manual per R6 / research-protocol Phase 3.3 — no shipped harness)

### 4.1 Strata (cutpoints fixed now; spread axis re-derived for H8 — JC-4)

Partition **warm h=300 boundaries** (per symbol, full grid) on two
axes:

- **Vol axis** — HMM dominant state (`RegimeState.dominant_name`,
  `hmm_3state_fractional`): `compression_clustering` / `normal` /
  `vol_breakout` (3 strata);
- **Spread axis** — boundary-time prevailing **spread-in-ticks** at
  **per-symbol terciles of the UNCONDITIONAL grid spread
  distribution** — all warm in-window boundaries, never
  eligible-only — **frozen at census time and disclosed per symbol**
  (ruled 8-F-H8). H8 substitutes spread-in-ticks
  for H2's `spread_z_30d` because (i) the H8 spec bans `spread_z_30d`
  from this card entirely (§1.1: census C.5 warm 0.03–0.16 on thin
  names; slate convention §0.1), (ii) the spec's own F3 kill clause
  is worded on **spread-in-ticks strata** (§11 Spread axis), and
  (iii) the tick-artifact machinery (§2.4) already measures it at
  every boundary. Per-symbol terciles rather than fixed cutpoints
  because the deployable symbols live in different buckets (APP
  median 61 ticks, RMBS 22 — any fixed cross-symbol cutpoint
  degenerates on one of them). The tercile boundaries are computed
  once from the census output (§1.4 spread distribution) before any
  forward return exists, then frozen for all of step 4.

The daily calm/elevated-A/elevated-B stratum is a **third, reporting
axis** (spec §10: intraday gate ≠ daily stratum; every statistic is
also reported in the gate-state × daily-stratum 2×2). The spec's F3
kill clause is evaluated in its own frozen form — conditional
continuation sign across **spread-in-ticks terciles within the benign
stratum** (benign = `P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore
≤ 3.0` at the boundary).

### 4.2 Procedure and per-stratum minimum

Within each (vol × spread) stratum: repeat the §2.2 IC test
(λ-elevated-stratum `spearman_ic` on stratum boundaries, plus the
λ-contrast) and, where the stratum holds enough bars to form the §3
groups, repeat CPCV (same config; a stratum that cannot form 10
groups of ≥ 1 bar per session reports CPCV-INFEASIBLE, not a fail).
**Minimum per-stratum sample = 100 boundary observations**
(research-protocol Phase 3.3 rule 4); below it the stratum reports
**INSUFFICIENT** — never pooled away, never counted for or against
the acceptance rule. (Power disclosure: conditioning *episodes* are
far too few to stratify — ~81 per symbol; the stratified object is
the boundary-level λ-elevated IC, exactly as H2 stratified the
boundary-level sensor IC.)

### 4.3 Acceptance rule (numeric)

**PASS** iff, on the pooled-D evidence: the λ-elevated conditional
continuation is **sign-stable (continuation-positive) AND λ-elevated
RankIC ≥ +0.02 with Fisher-z p ≤ 0.05** in at least **2 vol strata ×
2 spread strata** (i.e. ≥ 2 cells on each axis among cells with
n ≥ 100). Single-stratum concentration is a fragility flag reported
to Lei (not an automatic kill) **unless** the conditional
continuation sign reverses across spread-in-ticks terciles within the
benign stratum — that is F3, a **definition-level kill** (spec §11,
Spread axis).

### 4.4 Invariance checks (spec §7, slotted here; numeric criteria)

- **I-1 (zero-integrated-edge conservation, mandatory):** funding
  pool (a) = Σ_episodes (measured continuation move × contra-side
  fading volume inside the episode window — the faders'
  mark-to-horizon loss); strategy integrated pre-cost conditional
  edge (b) at declared participation (≤ 80 sh/episode against
  episode volumes O(10³–10⁴) sh — participation share O(1–10 %)).
  **Pass:** (b) / (participation share × (a)) ≤ 1.5 (point estimate;
  the 0.5 headroom is the pre-registered estimation-error
  allowance). Companions: (i) unconditional forward returns over all
  matched in-window boundaries integrate to ≈ 0 over the
  regime-balanced sample — |mean| ≤ 2 × SE (no ambient-momentum
  subsidy); (ii) the **baseline-λ stratum** (same dislocation gate,
  `kyle_lambda_60s_percentile < 0.5`) shows reversion or zero —
  continuation-signed mean ≤ 0 within 2 SE (not significantly
  positive). Fail ⇒ **misattribution ⇒ hypothesis-revise** (if
  everything continues regardless of λ, the card is an unregistered
  momentum hypothesis — dead by its own terms, F2).
- **I-2 (side symmetry):** continuation-long vs continuation-short
  conditional edges in the benign stratum agree within sampling
  error — two-sample z ≤ 2. Fail ⇒ investigate before any deployment
  claim (hypothesis-revise); the SHORT side carries the §6.2 SSR/HTB
  optimism caveat in all reporting, and the §1.6 RMBS long-only rule
  is an *economic* (floor) asymmetry pre-stated at design — I-2
  tests the pre-cost mechanism symmetry only.
- **I-3 (λ dose-response):** conditional continuation-signed forward
  return in λ-percentile bands {[0.5, 0.65), [0.65, 0.8), [0.8, 1.0]}
  plus the below-median contrast band. **Numeric reading (JC-9):**
  the top elevated band must exceed the below-median band by ≥ 1 SE
  (gradient exists), and the three elevated-band means must not be
  strictly decreasing in band order (no inversion). Flat across
  bands ⇒ the median split is a coin flip ⇒ mechanism attribution
  fails even if the pooled number is positive (hypothesis-revise);
  an inverted-U concentrated at the extreme top ⇒ θ₃ ignition
  signature — red flag feeding the hazard-exit calibration and Lei
  review, not an automatic kill.

Phase-5 decay-shape check (spec §4): IC(t) measured at t ∈ {60, 120,
300, 600} s on eligible boundaries; exponential fit half-life must
lie in **[75, 300] s** (the declared 150 s ± a factor of 2; JC-7).
Outside ⇒ the process model is mis-specified ⇒ hypothesis-revise; a
non-decaying IC(t) is F1-adjacent death.

---

## 5. STEP 5 — DSR (`research/dsr.py`)

Computed on the pooled-D per-bar cost-adjusted return series (§3.2
definition, all D symbols' sessions, bars in (symbol, session, time)
order; n_obs = total bar count — 780 × |D|):

- `build_dsr_evidence_from_returns(returns=…, trials_count=N,
  annualization_factor=sqrt(19,656) ≈ 140.20)` with **N = the
  then-current living-ledger count at computation time** — N = 10 at
  protocol freeze (task Amendment E; the Appendix-A read was
  census-class, no outcome contact, N-neutral per the 8-F C.6 rule);
  every evaluation event between freeze and the DSR computation
  increments it first (FQ-6B-R rule: any data contact increments;
  drafting does not). The spec §14 drafted-not-evaluated variants
  count **only if actually evaluated** by then.
- `trial_sharpe_variance`: **None** (iid-Gaussian null floor
  `1/(n_obs−1)`), because the parked/unevaluated trials have no
  measured Sharpes to pool an empirical variance from. This is the
  weakest honest deflation (module `UserWarning`) and is disclosed
  verbatim in the evidence artifact.
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
sensor params, gate thresholds, dislocation constants, and session
constants are fixed (spec §1.4/§6.1). The only estimated quantity in
the whole candidate is `edge_scale_bps` (Task-8 calibration, §3.2).
Drift diagnostics therefore test the *stability of the
fixed-parameter machinery and the single calibrated parameter* across
the grid's sessions; pre-stated bounds below are disqualifying.

### 6.1 Regime-engine behavior (`scripts/regime_diagnostics.py` as anchor)

Run per (symbol ∈ D, session) over the grid with the Task-9 config,
`--horizon 300`. The H8 regime arm is an **exclusion screen**
(`P(vol_breakout) < 0.7 ∧ realized_vol_30s_zscore ≤ 3.0`), not H2's
positive benign selector — the bounds are adapted accordingly (JC-5):

| diagnostic | pre-stated stability bound (per session unless noted) |
|---|---|
| min pairwise emission separation d | ≥ 0.5; a session below it ⇒ the posterior is non-discriminative that session ⇒ its boundaries leave the benign stratum (fail-safe; gate arms conservatively) |
| argmax occupancy | no single state > 0.98 of RTH quotes (else same treatment as above) |
| exclusion-screen OFF fraction (`P(vol_breakout) ≥ 0.7 ∨ rvz > 3.0` over in-window boundaries) | ≤ 0.95 per session — a screen that excludes essentially everything leaves no entry surface; > 3 deployable-symbol sessions above ⇒ drift-disqualifying for the gate design (hypothesis-revise). An always-ON screen (OFF ≈ 0) is the *expected* calm-tape behavior of an extreme-exclusion backstop and is NOT a failure — reported, not bounded. |
| median screen-ON dwell (seconds, per symbol pooled) | ≥ 300 s (one horizon — spec §4's tick-dwell caveat made numeric); below ⇒ the screen cannot support boundary-scale holds ⇒ hypothesis-revise |
| full-gate ON fraction (the §1.1 arms 3–6, i.e. the conditioning fraction) | reported per session against the census (consistency check); no numeric kill here — power is adjudicated at §1.5, not re-litigated |

### 6.2 Sensor / conditioning stability

| diagnostic | pre-stated bound |
|---|---|
| per-session eligible-episode rate (per deployable symbol, within a daily stratum) | max/min ratio across that stratum's sessions ≤ 5; above ⇒ conditioning unstable ⇒ hypothesis-revise |
| `kyle_lambda_60s` warm coverage (per deployable symbol, per session) | the spec §1.1 coverage rule: warm fraction < 0.5 on > 2 sessions ⇒ the symbol leaves D (coverage/power, not tuning). Read baseline, disclosed: APP 1.000; RMBS 0.959 with worst cell 0.763 — all 20 cells currently clear. |
| `micro_price` / `realized_vol_30s_zscore` warm coverage | reported per session (mandatory); entry suppression when cold is the correct fail-safe; feeds power through episode counts |
| L6 sign-stability diagnostic (spec §9 row L6) | tick-rule vs quote-position-of-print agreement per λ-percentile band, offline; agreement < 80 % in the benign stratum ⇒ the conditioning variable is materially diluted ⇒ report and carry as an edge-dilution haircut in §2.3 (measured, not assumed) |
| L5 micro-vs-mid drift divergence (spec §9 row L5) | \|micro-price drift − mid drift\| at eligible boundaries reported per symbol; median divergence > half the conditioning threshold ⇒ the L5 shading margin claim (4.5×/2.2×) is void ⇒ hypothesis-revise (the mid-based NEW drift sensor variant stays drafted, spec §14) |
| `ofi_ewma` flow-agreement diagnostic (spec §1.1 — offline only) | share of eligible episodes where OFI sign agrees with dislocation direction, reported per stratum; no numeric kill (diagnostic for the θ₂/θ₃ mixture; feeds Lei review) |

### 6.3 Calibration stability

Leave-one-session-out re-estimates of `edge_scale_bps` (pooled-D
procedure of §3.2) must all lie within **[0.5×, 2.0×]** of the
full-sample estimate. Outside ⇒ the single calibrated parameter is
session-unstable ⇒ **drift-disqualifying (hypothesis-revise)** — not
tunable within this trial.

Structural boundaries (spec §11 footer / F5) stand: Rule 612
half-penny (Nov 2027), MDI round-lot reassignments, the 2026-04-27
vendor admissibility split — never pool across; the grid is entirely
pre-2026-04-27 by construction.

---

## 7. STEP 7 — EXECUTION OVERLAY (order-locked after steps 1–6; runs ONLY after the P0-6 Task-12 parity precondition holds)

**Hard gate (spec §12(c) / session constraint 5):** no number from
this step exists as a result until the Task-12 router timing-parity
check has passed (P0-6: AXIS-1 VERIFIED 2026-07-12; re-verified green
at execution time). If the parity state has regressed, this protocol
halts here with steps 1–6 outcomes reported as
statistical-axis-only.

### 7.1 Configuration

`configs/bt_sig_dislocation_lambda_drift_v1.yaml` (Task 9
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
`signal_min_edge_cost_ratio: 1.5` (deployment convention);
`no_entry_first_seconds: 300`, `session_flatten_enabled: true`,
`session_flatten_seconds_before_close: 600`; symbols = D only.

### 7.2 Runs and required outcomes (numeric)

Per symbol in D over its 10 grid sessions: `feelies backtest
--config configs/bt_sig_dislocation_lambda_drift_v1.yaml --symbol <S>
--date <D>` — the **baseline** pass — then the **identical** run set
under `--inv12-stress` (1.5× `cost_stress_multiplier`, 2× both
latency legs; the edge side is never touched, 00b hop 4). Required
outcomes, ALL of:

1. **Per-Alpha Cost Survival verdict = `SURVIVES`** (pooled per
   symbol over its sessions, `min_margin 1.5×`, `min_fills 20`) on
   the **baseline** run — `MARGINAL`, `BLEED` fail outright; `LOW_N`
   (< 20 fills) is a **power failure ⇒ PARKED (execution power)**,
   not a pass. (Power disclosure, stated now: at ~81 conditioning
   episodes per symbol and passive fill ratios < 1, the 20-fill bar
   is not automatically cleared — `LOW_N` is a live outcome.)
2. **`SURVIVES` again under `--inv12-stress`** — Inv-12: if the alpha
   vanishes under stress it wasn't real.
3. **Post-cost economics consistent with the disclosed
   `cost_arithmetic` (±5 % reconciliation spirit, numericized per the
   8-F ruling, carried verbatim):** (i) realized `mean_cost_bps` ≤
   1.25 × disclosed `cost_total_bps` (the modeled quote-dependent
   round trip may exceed disclosure arithmetic — 00b qualification 1
   — but a 25 % breach means the disclosure is wrong: re-derive and
   re-disclose, which is +1 N); (ii) calibration factor
   `realized mean_edge_bps / disclosed edge_estimate_bps` ≥ 0.75
   (below ⇒ the disclosed edge is optimistic ⇒ re-disclosure, +1 N);
   (iii) the G12 block's declared `margin_ratio` reconciles with
   components within ±0.05 absolute (load-gate arithmetic, checked
   at Task-9 load).
4. **Fill-quality diagnostics (spec §12(a)), numeric:**
   through-fill share of entry fills ≤ 50 % — for this card's
   passive-entry-into-continuation geometry a through fill means
   price crossed back through the resting level (deep retrace), the
   execution-layer θ₂/θ₃ signature; the trap otherwise reads
   *inverted* relative to a fade (fills acquired exactly when the
   continuation premise has failed), which is quantified by:
   filled-minus-unfilled **300 s** markout gap ≤ the 2.0 bps charged
   adverse selection (150 s markouts reported alongside) — if
   exceeded, F4 arithmetic is **re-run with the measured figure**
   (pre-registered recomputation, not a new trial) and outcomes 1–2
   re-judged on it. `EXPIRED` (timeout-cancel) rate and time-to-fill
   distribution reported against the 3-tick-delay + hazard model.

---

## 8. STEP 8 — SENSITIVITY GRID (spec §12(b) extended; 8-F sensitivity amendment carried verbatim)

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
second stress folded into the floor (§11.1 anchor — no stacking). A
verdict that flips inside the binding set is simulator-dependence:
the candidate is **not execution-valid regardless of the
pinned-profile number**.

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
invalid (spec §12(d) verbatim: "F4 (execution validity): pre-cost
continuation exists but ≤ 1.5 × C_ow under the passive realism model
→ trap-quadrant").

| step | binding numeric criterion | on FAIL → status |
|---|---|---|
| 1 census | viable region non-empty AND ≥ 100 primary episodes for APP (and RMBS per §1.6) | **PARKED** (emptiness or power — pre-determined on the power axis, §1.5; the Amendment-D path is the sole continuation) |
| 2a sign-golden | all five assertions | **REJECTED** (sign/wiring defect; re-run after fix, N unchanged) |
| 2b IC gate | λ-elevated RankIC > 0, \|RankIC\| ≥ 0.03, p ≤ 0.01, n ≥ 1,000; λ-contrast positive with baseline not significantly positive; bucket spread positive; tail t ≥ 2 | **REJECTED** (F1/F2 dead — no conditional continuation edge, or the λ arm does no work) |
| 2b sample floor (JC-3 ruling) | n ≥ 1,000 reachable on the realized D | **PARKED (evidence-infrastructure class, H4 precedent)** when D = {APP} with no legal path to n ≥ 1,000 — not hypothesis-revise; threshold rescaling prohibited |
| 2.3 edge anchor | measured conditional edge ≥ per-symbol single-stress floor on ≥ 1 symbol (SELL legs: rider-inclusive) | **PARKED** (economics below floor everywhere) |
| 2.4 tick tests | ≥ 4-tick stratum sign-consistent | **REJECTED on affected stratum** (grid artifact; economics restated on survivors; if D empties → PARKED) |
| 3 CPCV | 9 paths, mean annualised path Sharpe ≥ 1.0, block-bootstrap p ≤ 0.05, embargo 3, per D symbol, cost-adjusted series | **REJECTED** (does not survive purged OOS reconstruction) |
| 4 stratification | sign-stable + λ-elevated RankIC ≥ 0.02 (p ≤ 0.05) in ≥ 2 vol × ≥ 2 spread strata (n ≥ 100 each) | **HYPOTHESIS-REVISE** (regime-fragile — a narrower re-registered card is a new trial); F3 spread-tercile sign reversal in the benign stratum ⇒ **REJECTED** (definition kill) |
| 4.4 invariance | I-1 ratio ≤ 1.5 + companions; I-2 z ≤ 2; I-3 gradient exists, no inversion; IC(t) half-life ∈ [75, 300] s | **HYPOTHESIS-REVISE** (misattribution / contamination — mechanism story wrong in a named way) |
| 5 DSR | dsr ≥ 1.0, p ≤ 0.05, observed > noise ceiling at honest N | **REJECTED** (indistinguishable from max-of-N noise) |
| 6 drift | all §6.1–§6.3 bounds | **HYPOTHESIS-REVISE** (machinery unstable across sessions; any bound-motivated change = new trial) |
| 7 execution | SURVIVES baseline + stressed; reconciliation (§7.2.3); fill-mix bounds | **TRAP-QUADRANT** if steps 1–6 passed (statistically valid, execution-invalid); `LOW_N` ⇒ **PARKED (execution power)** |
| 8 grid | F4 clearance at all 27 neighborhood vertices + the inv12-stress point, every D symbol (full 81-cube reported; non-neighborhood failures = logged fragility findings, not kills) | **TRAP-QUADRANT** (simulator-dependent economics) |

**Tuning prohibition (binding, repeated):** converting any FAIL by
changing a parameter, threshold, window, stratum definition, or knob
is prohibited within this trial. Any such change is a **new trial**:
increment N in the living ledger, log the variant with its
justification, and re-enter this protocol from step 1 for the new
variant. The one-way κ ratchet (spec §5.1) additionally forbids
upward re-estimation of any κ factor after data contact. The sole
pre-authorized post-park action is the single Amendment-D
occupancy-based re-threshold (§1.7) under its own binding rules.

---

## 10. TRIAL LEDGER STATE AT PROTOCOL FREEZE (task Amendment E)

**N = 10 at freeze** (prompt_pack_04 ledger through slate B and
Task 7; the Appendix-A contamination read was census-class with no
outcome contact — N-neutral per the 8-F C.6 rule). The primary object
of this protocol is the slate-B ledger row "H8 primary:
dislocation(≥0.75σ) × λ(≥p50) continuation, H=300, hl=150, passive,
{APP, RMBS}" — this protocol is its measurement plan, not a new
trial. Rows that increment **only on evaluation** (FQ-6B-R binding
rule: any data contact — including exploratory — increments; drafting
does not); all drafted rows carry N-impact 0 until evaluated:

- the spec §14 drafted-not-evaluated variants (OFI entry arm;
  mid-based drift NEW sensor; 03b-filtered NEW `kyle_lambda`
  fallback; session-relative λ percentile; session-relative σ₃₀₀
  threshold; `hard_exit_age_seconds = 450`; session-constant
  variations; re-thresholded conditioning);
- the §1.7 occupancy-based re-threshold variant (registered
  post-park with its disclosed derivation; census-class re-census
  N-neutral; first outcome contact +1 N).

Every criterion in this protocol carries its numeric threshold above;
no threshold is left to be chosen after data contact (the two
census-derived constants — the §4.1 spread terciles and the §1.7
occupancy derivation — are computed from census-legal,
return-free quantities under pre-registered procedures). The DSR of
§5 uses the then-current N, never the frozen 10 if evaluations have
occurred in between.

---

## 11. JUDGMENT CALLS AND RULINGS (task Amendment F — 8-F pattern; RULED 2026-07-12, Task 8-F-H8, Lei)

Every numeric or instrument choice the task left free, with the
adopted proposal and its alternative. **All ten JCs are RULED
(2026-07-12); the per-JC ruling is recorded at the end of each entry
and the ruled text is applied in the named sections. This section is
the freeze record.**

**JC-1 — Contamination-exclusion instrument for the primary census
count (§1.3; integrity-critical, Amendment B interaction).**
Proposed: per-boundary **intensity** exclusion (flagged share ≥ 2.0 ×
session tape base rate, count OR volume basis — the frozen §2
materiality criterion at boundary granularity). Alternative 1: the H2
**binary** any-flag convention — on H8 it saturates (98.8 % of APP
conditioning boundaries flagged; the §2 read pre-registered exactly
this objection) and would measure window length, not λ-input
contamination. Alternative 2: no exclusion (the read's own count) —
more permissive than Amendment C(ii)'s "contamination-excluded"
wording allows. Count-directions: proposal is deflating vs the read's
81/77 and inflating vs binary. **Materiality bound, disclosed: the
choice cannot affect the §1.5 park verdict (all three candidate
counts are < 100 for both symbols), so it is not power-tuning; it
binds only on downstream conditional statistics.** Because the
instrument was frozen after seeing 81/77, Amendment B required
explicit approval.
**RULING: APPROVED as amended — intensity exclusion at the frozen
2.0× bar with the COUNT basis binding (volume basis reported, never
binding); all three counts always reported; the H2→H8 instrument
change logged as a template deviation; the identical instrument
governs any §1.7 re-census. Applied in §1.3.**

**JC-2 — Embargo 3 bars (§3.1).** The arithmetic minimum is 2 bars
(300 s reducer window + 60 s λ window = 360 s residual); the +1
conservative bar mirrors the approved H2 pattern (covers the rv-z
2000-count window and the quote-clocked HMM posterior — the
no-fixed-constant components). Alternative: the bare 2-bar minimum.
**RULING: APPROVED as proposed.**

**JC-3 — IC-gate primary variable and the n ≥ 1,000 bar (§2.2).**
Proposed variable: signed dislocation fraction vs signed forward
return, stratified by the λ median split, with the λ-contrast as a
binding conjunct (the card is a conditional-contrast hypothesis; a
single pooled monotone IC would test a momentum claim the card does
not make). The 0.03 / p ≤ 0.01 / n ≥ 1,000 thresholds are carried
verbatim per Amendment A (conjunctive-IC rationale). Feasibility
disclosure: at 78 bars/session the λ-elevated stratum holds ≈ 745
pooled warm boundaries on the full two-symbol grid and ≈ 380 on
APP-only D — **if D = {APP}, the gate reports INSUFFICIENT and stops
for you** rather than silently rescaling the bar. Alternative:
pre-scale the minimum by the bars-per-session ratio (1,000 × 78/195 =
400) — flagged, not adopted, because the 8-F ruling is carried
verbatim.
**RULING: APPROVED with consequence mapping added to §9 — D = {APP}
only with no legal path to n ≥ 1,000 ⇒ PARK (evidence-infrastructure
class, H4 precedent), not hypothesis-revise, never threshold
rescaling. Applied in §2.2 and §9.**

**JC-4 — Stratification spread axis = spread-in-ticks per-symbol
terciles (§4.1).** Replaces H2's `spread_z_30d` fixed cutpoints for
the three reasons stated in §4.1 (spec bans the sensor on this card;
F3 is worded on spread-in-ticks; the tick machinery already measures
it). Terciles are frozen from the census spread distribution
(return-free) before any forward return exists. Alternative: fixed
cross-symbol cutpoints (degenerate given APP 61 vs RMBS 22 median
ticks) or offline `spread_z_30d` (contradicts the spec's own
convention).
**RULING: APPROVED — tercile cutpoints from the UNCONDITIONAL grid
spread distributions, frozen at census time, disclosed per symbol.
Applied in §4.1.**

**JC-5 — Drift bounds adapted for an exclusion screen (§6.1).** H2's
"gate-ON fraction ∈ [0.05, 0.95]" assumed a positive benign selector;
H8's regime arm is an extreme-exclusion backstop that legitimately
sits near always-ON on calm tape. Proposed: bound only the
screen-OFF fraction (≤ 0.95 per session, > 3 sessions above ⇒
hypothesis-revise) and the screen-ON dwell (≥ 300 s); report the
full-gate conditioning fraction against the census with no separate
kill. Alternative: carry H2's two-sided band verbatim (would fail on
ordinary calm sessions for reasons unrelated to the design).
**RULING: APPROVED as proposed.**

**JC-6 — Fill-mix criterion carried verbatim with inverted-geometry
reading (§7.2.4).** Through-share ≤ 50 % and the
filled-minus-unfilled markout gap ≤ 2.0 bps both carry from H2; the
markout horizon moves to 300 s (150 s reported alongside). For this
card a through fill = deep retrace against the continuation premise,
so the bound reads as the θ₂/θ₃ execution signature just as
naturally as it did for the fade. Alternative: a bespoke
"drain-fill-then-non-resumption" bound — rejected as
non-numericizable beyond what the markout gap already measures.
**RULING: APPROVED as proposed.**

**JC-7 — IC(t) grid and half-life window (§4.4).** t ∈ {60, 120, 300,
600} s with fitted half-life ∈ [75, 300] s — the H2 pattern (declared
hl ± factor of 2) re-derived at hl = 150 s. Alternative: none
natural.
**RULING: APPROVED as proposed.**

**JC-8 — CPCV per-split calibration regressor (§3.2).**
`edge_scale_bps` trained by OLS of continuation-signed forward return
on the spec §6.2 `excess` (through origin), clipped to the declared
[6.0, 16.0] range — the exact analog of the approved H2 procedure
with the spec's own exceedance as regressor. Alternative: calibrate
on dislocation exceedance alone (discards the λ term the spec's edge
attribution uses).
**RULING: APPROVED as proposed.**

**JC-9 — I-3 dose-response numericization (§4.4).** Top elevated band
minus below-median band ≥ 1 SE AND no strict decrease across the
three elevated bands; inverted-U = reported red flag, not a kill.
Alternative: rank-correlation-of-bands form (equivalent in spirit,
less transparent at 3 bands).
**RULING: APPROVED as proposed.**

**JC-10 — Occupancy re-threshold derivation template (§1.7,
Amendment D).** λ split pinned at the median (mechanism claim, not
tunable); only the dislocation multiple re-derives, from the realized
boundary-level dislocation distribution targeting the card block-2
design occupancy (≈ 0.226 joint conditioning fraction), disclosed
arithmetic, one variant, census-class N-neutral. Alternative: also
freeing p₀ — rejected (the median split is the falsifiable mechanism
statement; moving it is a different hypothesis).
**RULING: APPROVED CONDITIONAL — condition satisfied: the mechanical
κ-adjustment rule is pinned in §1.7 before freeze
(κ_variant = min(0.190, 0.190 × c_D(m_v)/c_D(0.75)), inverse-Mills
c_D from the card's own near-Gaussian identity; κ_variant ≤ 0.190
always; the variant's park arithmetic uses κ_variant; any
non-mechanical input stops the derivation for Lei review).**

---

## 12. FREEZE DECLARATION

Steps are order-locked (§0); the census (step 1) executes only after
this freeze commit; steps 7–8 execute only under P0-6. The §11
rulings landed 2026-07-12 (Task 8-F-H8, Lei) and are applied in
§1.3, §1.7, §2.2, §4.1, and §9. This document is **PRE-REGISTERED —
FROZEN AT TASK 9 START as of the Task 8-F-H8 commit (2026-07-12)**.
From this commit, all changes go in an `AMENDMENTS` section appended
below this line, each entry carrying a timestamp and justification.

*Protocol frozen — Task 9 (implementation) may begin.*
