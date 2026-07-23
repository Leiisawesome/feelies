<!--
  File:   docs/research/sig_dislocation_lambda_drift_v1_impl_plan.md
  Status: APPROVED — EXECUTING (Lei, 2026-07-14). Task 9 implementation
          plan approved with four rulings recorded in §7 (flag 1 upheld
          — single APP-only config + config-scope guard added to §2.6;
          flag 2 approved as read; flag 3 approved with the pre-stated
          risk_budget bound; docstring requirement added to §2.5).
          Implementation proceeds per §5 sequencing. NO implementation
          code exists at approval time; NO outcome statistic was
          computed in producing this plan (zero data contact — document
          authoring only).
  Owner:  microstructure-alpha (alpha artifacts) / testing-validation
          (test plan); prompt-pack Task 9, Phase B.

  Provenance (FQ-3 template):
    git_sha: "487c351e2ec1818f01981c297ceb8a6852af27ef"
    worktree_clean: "yes (git status --porcelain empty at task start;
      this file is the only artifact produced)"
    pythonhashseed: "n/a — no scripted analysis run in this task"
    normative_inputs (read this session):
      sig_dislocation_lambda_drift_v1_formal_spec.md (frozen spec incl.
        §16 deviations + the §6.2 clamped strength form),
      sig_dislocation_lambda_drift_v1_result.md (closure record; the
        step-0–8 validation protocol and census JSON artifacts were
        removed from the repo),
      prompt_pack_00_architecture_verification.md (guard inventory §(d),
        PARITY-GAP register §(e)),
      prompt_pack_03_data_contract.md (§7 L2 loss ledger, sensor
        vocabulary §5),
      prompt_pack_03c_universe_and_cache.md as amended (AMENDMENT 1 —
        the 20-session grid; {APP, RMBS} × 20 = 40 ingested cells for
        this candidate),
      prompt_pack_00b_edge_units_convention.md (one-way convention),
      prompt_pack_00c_eval_canon.md (pinned profile @ 825a7bc3…; Task-9
        config-guard amendment; zero-latency ban),
      prompt_pack_00e_strength_rider_and_thread.md (Track A rider —
        NORMATIVE for Task 9),
      prompt_pack_12p_router_fill_timing_parity.md (AXIS-1 VERIFIED
        2026-07-12 — Task 12 cites 8c69d49-era guards + overlay; not
        re-derived here),
      repo conventions read this session: alphas/SCHEMA.md,
        alphas/sig_kyle_drift_v1/ + tests/alpha/test_sig_kyle_drift_v1.py,
        alphas/sig_hawkes_burst_v1 (hazard_exit block),
        configs/bt_sig_kyle_drift.yaml, docs/alphas/* convention,
        docs/prompts/README.md coverage map +
        tests/docs/test_prompt_coverage_map.py,
        tests/research/test_gas_ofi_integrated.py (sign-golden model),
        tests/causality/test_anti_lookahead.py,
        tests/harness/test_backtest_parity_no_cache.py,
        tests/alpha/test_shipped_alpha_specs_load.py (pinned discovery
        list), tests/acceptance/test_backtest_app_baseline.py,
        src/feelies/alpha/loader.py (hazard_exit normalization
        :1027-1160), src/feelies/risk/hazard_exit.py (:43-44, 124-125).
-->

# `sig_dislocation_lambda_drift_v1` — Task 9 implementation plan

Plan only; no implementation code ships with this document. Scope facts
baked in per the approved amendments (A–E): **YAML-only card — zero new
sensors, zero bootstrap/wiring changes** (spec §1.2/§15 item 3, verified
against `_HORIZON_FEATURE_FACTORIES` in the spec session and
runtime-asserted on all census cells); deployable set **D = {APP}**
(protocol E.4/A-2); RMBS **evidence-only, step 2 only** (A-2.1 scope
limit); OLN evidence-only for the tick-artifact tests, never in any
config's symbol list; Task 12 parity is **cited** (12p AXIS-1 VERIFIED,
regression guards at `tests/execution/test_router_fill_timing_parity.py`
plus the kernel halt case), not rediscovered.

Standing at plan time: protocol step 1 complete (PROCEED — D = {APP});
steps 2–8 not executed; **no IC, forward return, or outcome statistic
exists for this candidate**. Step 2 may begin once Task 9's deliverables
exist; step 3 remains blocked until A-2.3 RF-1/RF-2 clear Lei veto.
N = 10 (living ledger), unchanged by this plan.

---

## 1. ARTIFACT PLAN (schema-1.1 path; legacy inline-features route retired — not used anywhere below)

### 1.0 NEW-SENSOR modules — NONE (explicit)

The spec requires no new sensor. All three `depends_on_sensors` entries
are existing, registered, reference-config sensors at their shipped
versions (`kyle_lambda_60s` 2.0.0 causal, `micro_price` 1.1.0,
`realized_vol_30s` 1.3.0 — spec §1.1), and all four consumed feature ids
(`micro_price_drift`, `micro_price`, `kyle_lambda_60s_percentile`,
`realized_vol_30s_zscore`) are factory-wired at h=300 (spec §1.2; census
P0-1 runtime assertion, all cells). Consequences:

- no `src/feelies/sensors/impl/` file, no `SensorSpec` registration
  entry, no `sensor_specs` block in the new config beyond what
  `extends: ../platform.yaml` already provides;
- `tests/sensors/test_<sensor_id>.py` (hand-computed values, warm/stale,
  gap-flush, incremental-vs-full agreement) is **N/A for this card** —
  those behaviors are already locked by the existing sensor suites; the
  causality and sign-golden items below still exercise the real sensor →
  feature → snapshot stack end-to-end;
- the 03b-filtered NEW `kyle_lambda` variant stays
  **drafted-not-evaluated** (spec §14) — no code for it in Task 9.

### 1.1 `alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml`

Schema 1.1, `layer: SIGNAL`, `version: "1.0.0"`. Content is the spec
made literal — every number below is frozen (spec §§1.2, 5.2, 6, 11, 13;
varying any is +1 N per the protocol freeze rule):

| block | content (source) |
|---|---|
| `description` / `hypothesis` | Real content carried verbatim from the spec preamble hypothesis (Kyle dynamic informed-trader incorporation; the λ-elevated stratum continues, the baseline-λ stratum reverts — that contrast IS the falsifier). Not placeholder text. |
| `falsification_criteria` | The consolidated §13 F1–F5 list, each as prose (F1 rolling-20-session sign-agreement clause; F2 λ-contrast indistinguishability; F3 spread-strata sign reversal / benign-stratum flip; F4 §12(d) trap-quadrant clause verbatim; F5 the three structural boundaries). |
| `depends_on_sensors` | `[kyle_lambda_60s, micro_price, realized_vol_30s]` (§1.3). No `ofi_ewma` (§16 row 5), no `spread_z_30d` (§1.1 ban). |
| `parameters` (≤ 3 free-range, §6.1) | `lambda_percentile_min` (float, default 0.5, range 0.5–0.7); `edge_scale_bps` (default 10.0, range 6.0–16.0, description flags "provisional pending Task-8 §3.2 calibration"); `edge_cap_bps` (default 12.0, range 8.0–20.0). Fixed constants (disloc_min dict, floor dict, session knobs, gate thresholds) are literals, not parameters. |
| `horizon_seconds` | 300 |
| `risk_budget` | Top-of-book scale per §6.5 sizing note: `max_position_per_symbol: 80` (APP p50 displayed depth; `platform_min_order_shares: 50` respected), conservative gross/drawdown/allocation values in line with the shipped sig_* conventions — exact numbers proposed at the commit-1 diff review. **Pre-stated bound (Lei ruling 3, 2026-07-14):** the numbers must respect the census capacity reality (APP top-of-book scale, Sharpe-max declaration — size beyond displayed-depth scale forfeits the passive economics) and be provably inert to steps 2–8 evidence statistics (steps 1–6 are boundary/return statistics that never read risk_budget; steps 7–8 fills are sized at the 80-share reference scale the budget merely caps — the diff review states this inertness argument explicitly). |
| `regime_gate` | §6.3 **verbatim**: engine `hmm_3state_fractional`; `on_condition` = `P(vol_breakout) < 0.7 and abs(micro_price_drift) >= 0.00237165 * micro_price and kyle_lambda_60s_percentile >= 0.5 and realized_vol_30s_zscore <= 3.0`; `off_condition` = `P(vol_breakout) > 0.7 + posterior_margin or realized_vol_30s_zscore > 3.0 or kyle_lambda_60s_percentile < 0.5 - percentile_margin`; `hysteresis: {posterior_margin: 0.15, percentile_margin: 0.15}` — **both margins referenced** in the off-condition (§16 row 3; the strict loader rejects declared-but-unused margins). Gate arms on the weaker (RMBS) constant; `evaluate()` enforces exact per-symbol constants. |
| `cost_arithmetic` (G12) | §6.5 verbatim: `edge_estimate_bps: 6.4`, `half_spread_bps: 0.0`, `impact_bps: 2.0`, `fee_bps: 0.08`, `margin_ratio: 3.08`, `cost_basis` one_way (default). Reconciliation check: 6.4 / (0.0 + 2.0 + 0.08) = 3.0769; |3.08 − 3.0769| ≈ 0.003 ≤ 0.05 absolute ✓; 3.08 ≥ 1.5 ✓. Comment records that the Task-8 §2.3 measured D-set-minimum edge supersedes 6.4 on measurement (one-way ratchet) — re-disclosure then is its own reviewed edit. |
| `trend_mechanism` (G16) | `family: KYLE_INFO`; `expected_half_life_seconds: 150` (envelope 60–1800 ✓; horizon/hl = 300/150 = 2.0 ∈ [0.5, 4.0] ✓); `l1_signature_sensors: [kyle_lambda_60s, micro_price]` (both G16 rule-5 KYLE_INFO fingerprints, both load-bearing); `failure_signature`: the five §11 clauses verbatim (spread-strata sign reversal; rolling-20-session sign agreement ≤ 0.50; λ-contrast indistinguishability; ≥4-tick-stratum sign inconsistency; session-interior vs event-adjacent concentration). |
| `hazard_exit` | §6.4: `enabled: true`, `hazard_score_threshold: 0.85`, `min_age_seconds: 30`, `hard_exit_age_seconds: null` → bootstrap derives 2 × 150 = 300 s (`bootstrap.py:2126-2190`; loader accepts explicit null, `alpha/loader.py:1144-1160`). |
| `signal:` | The §6.2 normative draft, implemented as written: G5-pure (no imports/I/O/state); reads exactly the three literal snapshot keys; per-symbol `disloc_min` {APP 2.53563e-3, RMBS 2.37165e-3} and `floor_bps` {APP 4.6809, RMBS 5.4645} literal dicts; `mag = drift if drift >= 0.0 else -drift` (no `abs()` call — purity linting); combined normalised exceedance `excess = 0.5·(d_x + l_x)` with d_x saturating at 1; EV gate `edge_bps < floor_bps → None` (never a bare threshold); direction = sign-matched continuation; **strength = `min(max(0.0, excess), 1.0)`** — the 00e Track-A clamped form, bounded by construction with explicit belt-and-suspenders clamps. |

Consume-driven `required_warm_feature_ids` (statically parsed
`snapshot.values` reads ∪ gate identifiers) resolves to exactly the four
ids of spec §1.3 — asserted in the load test (§2.4 below).

### 1.2 `configs/bt_sig_dislocation_lambda_drift_v1.yaml`

Follows the `bt_sig_*` convention (`extends: ../platform.yaml`, cf.
`configs/bt_sig_kyle_drift.yaml`), instantiated from the **00c pinned
profile** (commit `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`):

- `symbols: [APP]` — **deployable set D only** (amendment B; protocol
  §7.1). RMBS and OLN never appear in any config symbol list.
- `alpha_specs: [alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml]`.
- `signal_min_edge_cost_ratio: 1.5` (deployment convention, 00c
  amendment; the reference profile's 1.0 is documented-permissive).
- Session-time constants **verbatim from spec §1.4** (amendment C):
  `no_entry_first_seconds: 300`, `session_flatten_enabled: true`,
  `session_flatten_seconds_before_close: 600` (all three are real
  `PlatformConfig` fields folded into the snapshot,
  `platform_config.py:171, 346-347, 1062, 1123-1124`).
- **No `sensor_specs` additions** — the three sensors ride in from the
  reference profile at reference params (§1.1); config-scoped
  registration is unnecessary because nothing new is registered. **No
  reference-config change is needed**: `platform.yaml` is not edited
  (its `alpha_specs`/sensor blocks are untouched), so acceptance and
  determinism fixtures that read it see zero drift. Flag discharged:
  no unavoidable reference-config change exists for this card.
- Header comments record: the 00c pin commit, the instantiation-time
  realism-knob snapshot checksum (captured under PYTHONHASHSEED=0 when
  the config is created — 00c O-1: no pre-recorded value exists to
  copy), the evidence grid = the **named 20 sessions** (03c AMENDMENT 1
  list, verbatim in the comment for operator convenience), and the
  inv12-stress invocation used by protocol §7.2.
- Realism knobs are **inherited, not restated** (restating them would
  create a second place for drift); the checksum guard test (§2.6) is
  what pins them.

**Evidence-scoping interpretation (flagged for Lei at approval, not
silently decided).** Amendment C says "evidence configs cover
{APP, RMBS} per A-2 step-2 scoping". A-2's step-2 evidence set is
consumed by the §2.2 IC harness (`scripts/sensor_feature_ic.py`
extension), which reads the `DiskEventCache` directly per (symbol,
session) — it takes no backtest config, so {APP ∪ RMBS} coverage is an
invocation-grid property of the harness runs, documented in the config
header and the architecture note. Steps 3–8 are D-scoped = APP, which is
exactly what the single config provides. **Default plan: one config,
symbols [APP]; no second "evidence" config.** If Lei intended a literal
`bt_..._evidence.yaml` with `symbols: [APP, RMBS]`, that is a one-file
addition — but note it would create a config in which the platform can
route RMBS orders, which contradicts the A-2.1 scope limit (RMBS never
enters the execution overlay); the plan therefore recommends against it.

### 1.3 `scripts/sensor_feature_ic.py` — H8 row extension (protocol §2.2 assigns this to Task 9)

Measurement plumbing for the pre-registered primary trial (not a new
trial; N-impact 0 until an IC run executes under Task 8 step 2):

- an H8 variant row pairing `x = micro_price_drift / micro_price`
  (signed dislocation fraction) at h=300 warm boundaries with the
  signed forward 300 s mid log-return, **stratified by the λ median
  split** (`kyle_lambda_60s_percentile ≥ 0.5` vs `< 0.5`), reporting
  RankIC per stratum plus the λ-contrast, `bucketed_forward_return`
  (5 buckets) and `long_short_edge_bps` in the elevated stratum —
  statistics via the existing `research/forward_ic.py` primitives;
- contamination handling hooks per protocol §1.3 (intensity-primary,
  all three ways reported) reusing the flag-set logic already
  transplanted into the removed census instrument (historical note only);
- OLN cells accepted as evidence-only inputs for the §2.4 tick-artifact
  reporting (spread-in-ticks at eligible boundaries; quantum-mass
  reporting hooks), never contributing to any pooled IC statistic
  (protocol preamble; OLN never in D).
- The gas-01 pattern applies: a synthetic-tape smoke test proves the
  extension runs end-to-end and reports a row per (variant, stratum)
  (§2.3 below); **no cached-data IC run executes in Task 9** — first
  outcome contact belongs to Task 8 step 2 and increments nothing until
  it happens (it is the primary trial's own contact).

The script already has a coverage-map owner (`docs/prompts/README.md`
scripts row → sensor audit); no map change for this edit.

### 1.4 `docs/alphas/sig_dislocation_lambda_drift_v1_architecture.md`

Per-alpha architecture note following the five existing
`docs/alphas/sig_*_architecture.md`: mechanism summary (KYLE_INFO,
hl 150, H 300), the sensor → feature → gate → evaluate dataflow with the
four consumed ids, the frozen constants table (disloc_min, floors,
session knobs, gate thresholds with hysteresis), the EV-gate/B4
interaction (one-way disclosure, B4 doubles onto round-trip basis at
ratio 1.5), hazard-exit derivation (300 s hard age = 2 × hl), the
deployable-set statement (D = {APP}; RMBS evidence-only step 2; OLN
tick-artifact only), the two-axis validity statement (no number before
Task-12-parity-cleared overlay is a result; steps 1–6 statistical-axis
only), and pointers to the spec/protocol/census artifacts. All cited
repo paths kept real (internal-links hygiene).

---

## 2. TEST PLAN (mirrors `tests/` structure)

No new `src/feelies/` module exists, so the ≥ 80 %-coverage-on-new-code
gate has no new production surface to measure; the YAML-embedded
`evaluate` and the gate DSL are exercised behaviorally by the tests
below (loader-compiled, engine-driven). All new tests run under the
default marker set (no `functional` dependence) except the two
cache-gated items marked below.

### 2.1 Sensors — N/A (no new sensor; §1.0). Existing suites stand untouched.

### 2.2 Causality — `tests/causality/test_dislocation_lambda_no_lookahead.py`

`tests/causality/test_anti_lookahead.py` style, targeting this card's
exact consumed-feature set through the **real**
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack (gas-01
replay helper pattern):

- **truncation property (Hypothesis):** for generated quote/trade tapes,
  the h=300 snapshot emitted at boundary T is bit-identical between (a)
  the tape truncated at T and (b) the full tape — i.e. every reading and
  every one of the four feature values at T is a function only of events
  with `timestamp_ns ≤ T`;
- **out-of-order future reading:** a post-T reading fed before the
  boundary tick must not enter the snapshot at T (the
  `TestHorizonAggregationAntiLookahead` perturbation, instantiated on
  `kyle_lambda_60s_percentile` / `micro_price_drift` instead of the
  synthetic feature).

### 2.3 Sign-golden — `tests/research/test_gas_dislocation_lambda_sign.py`

Gas convention (`test_gas_ofi_integrated.py` as the model: real pipeline,
synthetic tape with known ground truth). The **five protocol §2.1
assertions, fixed there, implemented exactly**:

1. informed-continuation golden (LONG): upward dislocation ≥
   `disloc_min(APP)` built from high-impact prints (≥ 30 causal (Δp, Δq)
   pairs in the trailing 60 s; λ ramped above its window median; raw
   `kyle_lambda_60s` > 0) ⇒ `evaluate` emits LONG;
2. mirror golden (SHORT): the same tape mirrored ⇒ SHORT;
3. **λ-contrast golden (card-defining):** same dislocation magnitude,
   low impact (large Δq, small Δp; boundary percentile < 0.5) ⇒ `None`;
4. warm-gate golden: < 30 pairs in the trailing 60 s ⇒ λ not warm ⇒
   percentile id not warm ⇒ entry suppressed via the required-warm set;
5. h=300 key-presence golden: the snapshot carries all four consumed ids
   (factory-wiring regression lock, P0-1).

Plus the sensor_feature_ic H8-row smoke (§1.3): the extension runs
end-to-end on a synthetic tape and reports both λ strata (the gas-01
`_ofi_integrated_ab` test pattern). Any assertion failure at Task-8
execution time is an implementation-correction re-run (N unchanged),
per protocol §2.1.

### 2.4 Alpha load/gate — `tests/alpha/test_sig_dislocation_lambda_drift_v1.py`

Modeled on `test_sig_kyle_drift_v1.py`, extended per amendment D:

- loads under both `AlphaLoader()` and
  `AlphaLoader(enforce_trend_mechanism=True)` (strict) — clears the
  loader and `LayerValidator` (G2–G16);
- **G16 arithmetic at the frozen numbers:** family KYLE_INFO;
  `expected_half_life_seconds == 150` inside [60, 1800];
  horizon/hl ratio == 2.0 inside [0.5, 4.0]; both KYLE_INFO fingerprint
  sensors present in `l1_signature_sensors` AND `depends_on_sensors`;
  five failure-signature clauses present;
- **G12 arithmetic at the frozen numbers:** declared margin 3.08
  reconciles with 6.4/(0+2.0+0.08) within ±0.05 absolute; ≥ 1.5;
  one-way basis;
- gate DSL compiles with **both hysteresis margins referenced**
  (loading is itself the dead-config check; additionally assert the
  gate object's engine name and that ON/OFF evaluation flips on a
  `P(vol_breakout)` sweep across 0.70/0.85 and a λ-percentile sweep
  across 0.50/0.35 — the latch semantics of §6.3);
- engine-driven behavior via `HorizonSignalEngine` (the
  `_engine_with_alpha` pattern): LONG on the golden snapshot, SHORT on
  the mirror, `None` below `disloc_min`, `None` below the λ split,
  `None` when the EV gate fails (edge < per-symbol floor), no emission
  when gate OFF, no emission for a symbol outside {APP, RMBS}, edge
  capped at `edge_cap_bps`;
- **00e Track-A strength tests (amendment D):** (i) unit test asserting
  emitted `strength ∈ [0, 1]` across the full declared parameter ranges
  (min and max of every `parameters:` entry, not just defaults);
  (ii) Hypothesis property test driving snapshot values adversarially
  (NaN, ±inf, extremes, missing keys, zero/negative `micro_price`)
  asserting `evaluate` returns `None` or an in-range strength with
  non-negative finite `edge_estimate_bps`;
- discovery-pin update: add the new basename to the expected list in
  `tests/alpha/test_shipped_alpha_specs_load.py`
  (`test_all_shipped_alpha_specs_discovered` pins the exact basename
  set and otherwise fails on discovery of the new spec).
  `tests/alpha/test_discovered_alpha_specs_load.py` pins no list — it
  loads whatever discovery finds under both strict modes, which the new
  YAML must simply pass (covered by the load tests above).

### 2.5 Census-consistency smoke — removed with validation protocol artifacts

Amendment D item, cache-gated (`@pytest.mark.functional`, skip on cache
miss with the populate command — the `test_backtest_app_baseline.py`
pattern): replay **one known cell** (proposed: APP 2026-01-15 — densest
original cell, census incl = 13) through the production stack and assert
the alpha's **entry predicate** reproduces the census episode count for
that cell.

Stated precisely, because the census predicate and `evaluate()` are not
identical: the frozen §1.1 episode predicate is arms 1–6 (session
window, warm, λ ≥ 0.5, dislocation ≥ disloc_min, posterior < 0.7,
vol-z ≤ 3.0) and does **not** include the §6.2 EV gate
(`edge_bps ≥ floor_bps`), which strictly subsets it. The smoke therefore
asserts two things: (a) the predicate arms as expressed by the alpha's
gate + threshold logic (evaluated at the same boundaries with the same
constants) count exactly the census including-flagged number for the
cell (13); (b) every boundary where the loaded `evaluate` actually emits
is a subset of those 13. No forward return, IC, or outcome statistic is
computed — boundary counting only (census-class, N-neutral per the 8-F
C.6 rule).

**Docstring requirement (Lei ruling 4, 2026-07-14):** the test module's
docstring must state explicitly why the assertion is emissions ⊆
predicate set rather than equality — the frozen §1.1 census predicate is
arms 1–6 only, while `evaluate()` additionally applies the §6.2 EV gate
(`edge_bps ≥ floor_bps(symbol)`), so emission is a strict subset of
census eligibility by construction; asserting equality would be wrong
and asserting subset without saying why would hide the EV-gate
difference from future readers.

### 2.6 Config guard — `tests/acceptance/test_bt_dislocation_lambda_config_guard.py`

The 00c Task-9 amendment adopted verbatim (data-free, no cache):

- loading `configs/bt_sig_dislocation_lambda_drift_v1.yaml` asserts
  `backtest_fill_latency_ns > 0` and `market_data_latency_ns > 0`
  (FQ-2 amendment; zero-latency ban — amendment C's "fill latency > 0
  guard test");
- the realism-knob subset of `PlatformConfig.snapshot()` (the 00c §1
  table fields) serialises to sorted JSON whose SHA-256 equals the
  checksum pinned at config instantiation (any knob drift — including
  drift inherited through `extends: ../platform.yaml` — fails here);
  per-knob equality asserts alongside for readable failures;
- `signal_min_edge_cost_ratio == 1.5`;
  `no_entry_first_seconds == 300`; `session_flatten_enabled` is true;
  `session_flatten_seconds_before_close == 600`;
- **config-scope guard (Lei ruling 1, 2026-07-14):** a dedicated
  assertion that the run config's `symbols == ["APP"]` **exactly** —
  deployment scope cannot widen (RMBS, OLN, or anything else) without
  this test tripping; RMBS step-2 coverage is harness-level only and
  never enters a run config.

### 2.7 Determinism — `tests/harness/test_dislocation_lambda_parity.py`

Two identical runs → identical parity hash **via the harness**
(`compute_parity_hash` / `compute_combined_parity_hash`,
`harness/backtest_report.py`), modeled on
`tests/harness/test_backtest_parity_no_cache.py`: build the real
bootstrap twice over the same synthetic tape (the §2.3 golden tape,
extended so at least one entry clears the EV gate and B4 and produces
fills) with the new alpha registered, assert
`compute_parity_hash(orch1) == compute_parity_hash(orch2)` and that the
trade journal is non-empty (a trivially-equal empty hash proves
nothing). If fills prove unreachable on a compact synthetic tape, the
fallback assertion is bit-equality of the emitted `Signal` stream
fingerprints across the two runs — disclosed in the test docstring,
not silently substituted.

**Locked baselines are untouched:** no `EXPECTED_*_HASH` constant is
added anywhere (so the `tests/determinism/` unregistered-hash sweep and
the manifest fingerprint are not triggered);
`tests/determinism/parity_manifest.py` is not opened. No new locked
baseline is proposed — if one is ever warranted for this alpha, that is
a separately-approved architectural step, out of scope here.

---

## 3. GOVERNANCE OBLIGATIONS

| obligation | discharge |
|---|---|
| Coverage map (`tests/docs/test_prompt_coverage_map.py`) | **No new `src/feelies/` module ⇒ the enforced guard cannot fire.** The README scripts row is still updated per amendment E: add `scripts/research/h8_contamination_read.py` and `scripts/research/dislocation_lambda_census.py` to the `research_validation` entry in `docs/prompts/README.md` §Coverage map (they exist on disk but are absent from the map; `inventory_fade_census.py` / `horizon_feasibility_map.py` are the precedent). `scripts/sensor_feature_ic.py` already maps to the sensor audit — unchanged. |
| Internal links (`tests/docs/test_internal_links.py`) | The README edit adds only real paths. New docs (`docs/alphas/…`, this plan) are not in `_DOC_FILES`, but all paths cited in them are kept real anyway. No `docs/prompts/*.md` structural edits ⇒ `test_audit_prompt_structure.py` unaffected. |
| DTZ (ruff, wall-clock ban) | New tests and the `sensor_feature_ic.py` extension use explicit `ts_ns` construction and injected `SimulatedClock` only; no `datetime.now()`/`time.time()`; no new per-file-ignore is requested. |
| N-ledger discipline (amendment E) | Task 9 computes **zero outcome statistics**. Synthetic-tape goldens are not data contact; the census-consistency smoke is census-class boundary counting (N-neutral, 8-F C.6). Every implementation-detail choice below (e.g. risk_budget numbers, tape construction) is engineering, not a strategy variant; anything that would change a frozen constant is refused and escalated instead. Implementation variants remain drafted-not-evaluated until run. N = 10 stands. |
| Two-axes honesty | No number produced by Task-9 tests is a result; the architecture note and config comments state that steps 7–8 evidence exists only under the P0-6 (Task 12-P AXIS-1) precondition, re-verified green at execution time, with AXIS-2 residuals reported alongside per the parity-gap register. |

## 4. DO-NOT-TOUCH LIST (verified against every step below)

- `tests/determinism/parity_manifest.py` locked baselines + manifest
  fingerprint (no edit, no re-pin, no new `EXPECTED_*` constant);
- the promotion ledger (append-only; nothing here transitions any
  lifecycle);
- core event schemas (`core/events.py` untouched);
- router public semantics (`execution/*` untouched);
- existing alphas and their configs (`alphas/sig_*`, `alphas/research/`,
  `configs/bt_*` existing files, `platform.yaml` — all untouched;
  the only edits to existing files are: the discovery-pin list in
  `tests/alpha/test_shipped_alpha_specs_load.py` (a test, not an alpha),
  `scripts/sensor_feature_ic.py` (additive row), and the
  `docs/prompts/README.md` scripts row);
- frozen research artifacts (spec, protocol, census JSONs) — read-only
  inputs.

## 5. SEQUENCING (one module per commit; message convention `alpha/sig_dislocation_lambda_drift_v1: <artifact> — <summary>`)

Gate battery **per step** (a step is not done while any gate fails):
`PYTHONHASHSEED=0 uv run pytest -m "not functional and not slow"` ·
`uv run pytest tests/determinism/` · `uv run mypy src/feelies` (strict;
expected no-op since src is untouched, run anyway) ·
`uv run ruff check src/ tests/` · `uv run ruff format --check` on
changed files. Cache-gated tests additionally run locally once
(`uv run pytest -m functional -k dislocation`) before their commit.

| # | commit (artifact) | contents | est. diff |
|---|---|---|---|
| 1 | `alpha YAML — schema-1.1 SIGNAL card at the frozen spec numbers` | `alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml` + `tests/alpha/test_sig_dislocation_lambda_drift_v1.py` (load/gate/G12/G16/strength/property tests, §2.4) + the discovery-pin list update (same commit, else the suite is red between commits) | ~250 yaml + ~300 test + ~5 |
| 2 | `run config — 00c pinned profile instantiation + guard` | `configs/bt_sig_dislocation_lambda_drift_v1.yaml` + `tests/acceptance/test_bt_dislocation_lambda_config_guard.py` (checksum captured under PYTHONHASHSEED=0 at instantiation) | ~60 yaml + ~120 test |
| 3 | `sign-golden — protocol §2.1 five assertions through the real pipeline` | `tests/research/test_gas_dislocation_lambda_sign.py` | ~350 test |
| 4 | `causality — no-lookahead property tests for the consumed feature set` | `tests/causality/test_dislocation_lambda_no_lookahead.py` | ~200 test |
| 5 | `IC harness — H8 λ-stratified row in sensor_feature_ic` | `scripts/sensor_feature_ic.py` (additive) + harness smoke test in the §2.3 module | ~150 script + ~60 test |
| 6 | `census-consistency smoke — one-cell predicate reproduction (functional)` | `tests/research/test_dislocation_lambda_census_consistency.py` | ~150 test |
| 7 | `determinism — run-twice parity-hash guard (no locked baseline)` | `tests/harness/test_dislocation_lambda_parity.py` | ~120 test |
| 8 | `docs — architecture note + coverage-map scripts row` | `docs/alphas/sig_dislocation_lambda_drift_v1_architecture.md` + `docs/prompts/README.md` (one row edit) | ~150 doc + 1 line |

Order rationale: the YAML must exist before anything evaluates it
(commits 3–7 depend on 1; 6–7 depend on 2); docs last so they describe
what shipped. Each commit is independently green.

## 6. RISKS

| risk | mechanism | guard |
|---|---|---|
| Strict-loader rejection of the gate block | dead-config hysteresis rule; unknown hazard_exit keys; legacy spellings | Both margins referenced in `off_condition` (spec §16 row 3); hazard_exit uses only canonical keys (`enabled`, `hazard_score_threshold`, `min_age_seconds`, `hard_exit_age_seconds` — loader `_HAZARD_EXIT_KNOWN_KEYS`, null accepted); commit-1 strict-load test fails fast |
| Discovery-pin breakage | `test_shipped_alpha_specs_load.py` pins the exact basename list; a new alphas/ dir fails it | list update in the same commit as the YAML (commit 1) |
| G12 arithmetic drift | ±0.05 absolute reconciliation on `margin_ratio` at load | numbers frozen from spec §6.5; commit-1 test asserts the exact arithmetic before any suite run |
| G16 rule-5 fingerprint failure | KYLE_INFO requires both fingerprint sensors in `l1_signature_sensors` | both present and load-bearing (spec §1.3); asserted in commit 1 |
| Reference-config coupling | `extends: ../platform.yaml` inherits future platform.yaml drift into the evidence config; acceptance/determinism fixtures couple to platform.yaml | platform.yaml is **never edited** by this task; the §2.6 checksum guard converts silent inherited drift into a loud test failure; 00c pin commit recorded in the config header |
| Coverage-map guard | new src module without owner fails `test_prompt_coverage_map.py` | no new src module exists; README scripts row updated anyway (amendment E); guard run in every step's battery |
| Locked-parity exposure | any change to reference-config-driven streams or a new `EXPECTED_*` constant | no src, platform.yaml, or manifest edit; determinism test uses run-twice equality, no literal hash; `tests/determinism/` in every step's battery |
| EV-gate/census predicate conflation | the smoke test could wrongly assert evaluate-emission == census count (it is a strict subset) | §2.5 splits the assertion: predicate arms reproduce the count; emissions ⊆ predicate set |
| Synthetic-tape infeasibility for fills (commit 7) | EV gate + B4 + passive fill model may leave a compact tape fill-less | pre-registered fallback: Signal-stream fingerprint equality, disclosed in the docstring |
| Hypothesis flakiness in property tests | adversarial generation timing out on slow CI | fixed seeds/deadline settings per existing `tests/alpha/test_gate_g16_props.py` conventions |

## 7. APPROVAL RULINGS (Lei, 2026-07-14)

Plan APPROVED. The three flags raised at plan submission were ruled as
follows; rulings 1 and 4 amended the test plan in place (§2.5, §2.6).

1. **Flag 1 UPHELD — evidence-config reading (§1.2):** single APP-only
   run config stands; RMBS step-2 coverage is harness-level only and
   never enters a run config. **Amendment applied:** a config-scope
   guard added to §2.6 asserting the run config's `symbols == ["APP"]`
   exactly, so deployment scope cannot widen without a test tripping.
2. **Flag 2 APPROVED as read — "OLN/§6 artifact tests" (amendment B):**
   OLN = IC-harness tick-artifact support (spec §8 / protocol §2.4)
   plus spec-§6 decision-rule artifacts (strength rider tests, gate-DSL
   latch test, EV-floor tests); never in a run config.
3. **Flag 3 APPROVED for commit-1 diff review — `risk_budget`
   numerics:** with the pre-stated bound (recorded in §1.1) that the
   numbers must respect the census capacity reality (APP top-of-book
   scale, Sharpe-max declaration) and be provably inert to steps 2–8
   evidence statistics.
4. **Additional ruling — census-consistency smoke docstring:** the
   module docstring must state why emissions ⊆ predicate set (EV floor)
   rather than equality is asserted. Requirement recorded in §2.5.

*Plan approved 2026-07-14; implementation proceeds per §5 sequencing.*

### 7.1 Commit-1 pause rulings record (Lei, 2026-07-14)

**(a) risk_budget APPROVED CONDITIONAL — binding arithmetic re-show.**

Grid-maximum APP price: $729.51 = the maximum per-session median RTH
bid over the 20-session evidence grid, taken on 2025-12-22. Source:
pack-05 artifact (`docs/research/artifacts/horizon_feasibility_map_2026-07-11.json`,
APP cells); confirmed as the 20-session maximum by recomputing the
per-session median RTH bid for the 10 AMENDMENT-1 expansion sessions
with the identical pack-05 method (RTH two-sided quotes, median of
bids — price metadata only, no outcome statistic touched; N-neutral;
max over the expansion sessions is $718.26 on 2025-12-26 < $729.51).
Anchor notional: **80 sh × $729.51 = $58,360.80**.

As-submitted numbers FAILED the ruling's test at the inherited
capital base (`platform.yaml` `account_equity: 50000.0`):

| limit | USD | binds at (grid-max price) |
|---|---|---|
| gross 3.0% (Lei form: base × pct) | $1,500 | 2 sh ≤ 80 — BINDS |
| allocation 5.0% (base × pct; also the `BudgetBasedSizer` allocated capital) | $2,500 | 3 sh ≤ 80 — BINDS |
| compounded per-alpha exposure cap (`risk_wrapper.py`: base × alloc% × gross%) | $75 | 0 sh — BINDS |

Raising percentages alone cannot satisfy the bound at the $50k base:
the loader validates both percentages into (0, 100]
(`alpha/loader.py::_validate_risk_budget`), so the maximum reachable
USD limit is $50,000 < $58,360.80 — still binding at 68 sh on
2025-12-22 (and below 80 sh on 7 of 20 grid sessions). **Resolution
(the only lever that is not the 80-share anchor):** the evidence run
config overrides the capital base to `account_equity: 100000.0` — the
top of the BT-15 deployed-capital bracket ($25k–$100k,
`core/platform_config.py:173-174`), using the placeholder's own
documented override point ("locked placeholder $50k; override for
your book", `platform.yaml:94`); `account_equity` is not a 00c
realism knob (not in the 00c §1 table), so the §2.6 checksum guard is
unaffected. Re-shown at base $100,000 with the raised percentages
(gross 3.0 → 80.0, allocation 5.0 → 80.0; the 80-share anchor
untouched):

| limit | USD | binds at (grid-max price) |
|---|---|---|
| allocation 80.0% (Lei form; = sizer allocated capital) | $80,000 | 109 sh > 80 ✓ |
| gross 80.0% (Lei form: base × pct) | $80,000 | 109 sh > 80 ✓ |
| compounded per-alpha exposure cap (base × 80% × 80%) | $64,000 | 87 sh > 80 ✓ |

Neither percentage limit binds at ≤ 80 shares under either the
ruling's simple form or the shipped compounding semantics; the
80-share mechanism anchor is the binding constraint on every grid
session. `platform_min_order_shares ≥ 50` note: the platform floor
(50) is below the anchor (80), so the H1 min-order clamp
(`orchestrator.py:3977-3983`) keeps order sizes in [50, 80] and never
inflates past the anchor; at the old numbers the sizer's 3-share
targets would have been clamped to 50-share orders whose economics
sit off the 80-share fee anchor — the raised numbers remove that
distortion too. `max_drawdown_pct: 0.75` is unchanged (not a
share-binding limit; conservative shipped convention). The
inertness argument is unchanged: steps 1–6 never read risk_budget;
steps 7–8 fills are sized at the 80-share reference scale, which
`max_position_per_symbol` merely caps.

**(b) D-1 APPROVED AS DISCLOSED — conditions discharged:**
(i) spec §16 row 8 appended (append-only amendment, dated; the YAML
comment stays, the spec is the record); (ii) one deterministic NaN
golden per guarded input (micro_price_drift, micro_price,
kyle_lambda_60s_percentile — Lei's list named micro_price and the λ
percentile; drift is the third D-1-guarded input) plus a gate-level
NaN golden for the realized-vol input (consumed by the §6.3 gate,
never by `evaluate()`), alongside the Hypothesis property —
`tests/alpha/test_sig_dislocation_lambda_drift_v1.py`; (iii) the
census-alignment statement is recorded in the §16 row 8 entry, with
a precision note that the census instrument codes the predicate in
negated-exclusion form (not the De Morgan dual of the conjunctive
form on NaN) — the normative conjunctive predicate is all-False on
NaN, so NaN boundaries were never census-countable, and D-1 sides
the alpha with that form.

**N-ledger impact of this record: zero evaluations.** The grid-max
price read is boundary/price metadata (census-class); no outcome
statistic was computed; no parameter or construction variant was
evaluated against returns.

---

## 8. IMPLEMENTATION RECORD (appended on completion, 2026-07-14)

Execution of this plan under Task 10 (amendments A–C) is **complete**.
Eight commits, in the §5 order, each independently green; one pause
(after commit 1) as mandated, discharged by the §7.1 rulings record.

### 8.1 Commit ledger

| # | sha | delivered |
|---|---|---|
| 1 | `8cf091b` | alpha YAML at the frozen spec numbers + load/gate/G12/G16/strength tests + discovery-pin update. **PAUSED** for risk_budget sign-off; D-1 disclosed at the pause. |
| 1.5 | `8dfe366` | commit-1 rulings discharge: risk_budget re-show (§7.1a — 80/80 at the $100k base, 80-share anchor binding), spec §16 row 8 (D-1), four deterministic NaN goldens. |
| 2 | `9ed87ee` | `configs/bt_sig_dislocation_lambda_drift_v1.yaml` (00c pinned profile, `account_equity: 100000.0` per ruling a) + `tests/acceptance/test_bt_dislocation_lambda_config_guard.py` (zero-latency ban, per-knob pin, checksum, session constants, capital base, config-scope guard `symbols == ["APP"]`). |
| 3 | `ddc9be1` | `tests/research/test_gas_dislocation_lambda_sign.py` — the five protocol §2.1 assertions through the real pipeline (LONG golden, SHORT mirror, λ-contrast, warm-gate, key-presence). |
| 4 | `41c9f0e` | `tests/causality/test_dislocation_lambda_no_lookahead.py` — Hypothesis truncation property (h=300 snapshots at ≤ T bit-identical between truncated and full tapes, all four consumed ids) + out-of-order future-reading perturbation on the real reducers. |
| 5 | `477ce55` | `scripts/sensor_feature_ic.py` H8 row (§1.3): λ-stratified RankIC/Fisher-z p via `forward_ic` primitives, contamination three ways (intensity-primary, census flag-set transplanted), λ-contrast row, elevated-stratum buckets + `long_short_edge_bps`, OLN §2.4 evidence-only hooks; smoke tests in the §2.3 module. |
| 6 | `3cd8974` | `tests/research/test_dislocation_lambda_census_consistency.py` (functional) — APP 2026-01-15 predicate count == census incl **13** reproduced through the alpha's own gate machinery; engine emissions ⊆ predicate set; ruling-4 docstring. |
| 7 | `2a2458c` | `tests/harness/test_dislocation_lambda_parity.py` — run-twice `compute_parity_hash` equality over the extended golden tape with the run **actually trading** (2 journal records/run; the pre-registered Signal-fingerprint fallback was NOT needed). No locked baseline added. |
| 8 | `8d1d85c` | `docs/alphas/sig_dislocation_lambda_drift_v1_architecture.md` + `docs/prompts/README.md` scripts-row edit (amendment E). |

### 8.2 Final gate battery (at commit `8d1d85c`, PYTHONHASHSEED=0)

- full suite: **4064 passed, 33 skipped** (the skips are the gated
  `functional`/`paper_rth`/per-host perf tests; the two functional
  items exercised by this task — the census-consistency smoke and the
  APP baseline — ran **green** against the local disk cache);
- `uv run mypy src/feelies`: clean (193 files, strict);
- `uv run ruff check src/ tests/ scripts/`: clean; new files
  format-clean (the only `ruff format` diffs in touched files are
  pre-existing hunks in `scripts/sensor_feature_ic.py`, untouched);
- docs guards (`tests/docs/`): 101 passed (coverage map + internal
  links, including the new note's citations);
- `tests/determinism/`: 126 passed, no locked baseline added or
  re-pinned; `parity_manifest.py` untouched (do-not-touch list §4
  verified against the final diff).

### 8.3 Implementation-time disclosures (none change a frozen number)

1. **Commit 4, perturbation placement:** the out-of-order
   future-reading test stamps the injected readings at 305 s (not
   310 s): `HorizonWindowedFeature.observe` evicts at
   ``reading.ts − window``, so a future reading deeper than
   ``oldest_in_window_ts + window`` narrows the window and shifts the
   percentile denominator — that class is undefendable at the
   aggregator (the pre-existing model-level test says exactly this)
   and is covered upstream by `CausalityViolation` on non-monotonic
   feeds. The docstring discloses the defense boundary instead of
   hiding it by construction; the in-envelope perturbation exercises
   `finalize`'s live-subset defense on the real reducers.
2. **Commit 5, reporting plumbing:** `_Row` gains a `p_value` field
   (Fisher-z, from `spearman_ic`) with table/CSV columns — additive;
   existing rows carry `None`. The pooled table keeps the harness's
   existing sample-weighted convention; the protocol §2.2 pooled gate
   statistics are computed at Task-8 execution from per-cell pairs
   (pairs retained on rows carrying `edge_bps`), not from the pooled
   display row.
3. **Commit 7, config notes (documented in the test docstring):**
   `regime_calibration_max_quotes=300` is required (uncalibrated
   posteriors fail the `P(vol_breakout)` gate safe to OFF — audit
   P0-1), and `risk_max_gross_exposure_pct=200.0` (the reference
   `platform.yaml` value the evidence config inherits) is required —
   the 20 % class default vetoes the 80-share entry at APP notional
   ($43.8k vs $20k) and would leave the parity hash trivially empty.
4. **Commit 6, empirical outcome of the smoke:** predicate count
   reproduced the census **13/13** and the emission set was a strict
   subset on the cell — the EV-gate/census conflation risk (§6 row)
   did not materialise.

### 8.4 Trial-ledger record (amendment B discipline)

**Task 9/10 evaluations: ZERO. N = 10 stands.**

- No forward return, IC, Sharpe, or any outcome statistic was computed
  against cached data at any commit. The census-consistency smoke is
  census-class boundary counting (8-F C.6, N-neutral); the §7.1
  grid-max price read is boundary/price metadata (census-class,
  N-neutral); all other tests run on synthetic tapes (not data
  contact).
- No parameter or construction variant was evaluated against returns;
  every frozen constant ships verbatim from the spec. Draft
  alternatives considered during implementation (tape shapes, test
  scaffolding) are engineering choices, N-neutral by amendment B.
- First outcome contact remains Task 8 step 2 (the pre-registered
  primary trial's own contact).

*(Record appended 2026-07-14. Implementation stops here for Lei's
review before Task 11.)*
