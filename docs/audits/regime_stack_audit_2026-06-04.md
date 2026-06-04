# Services / Regime-Stack Audit — feelies

**Date:** 2026-06-04
**Scope:** `src/feelies/services/regime_engine.py`,
`src/feelies/services/regime_hazard_detector.py`,
`src/feelies/signals/regime_gate.py`,
`src/feelies/signals/horizon_engine.py` (gate integration),
`src/feelies/kernel/orchestrator.py` (M2 writer + session reset),
`src/feelies/bootstrap.py` (engine selection + hazard wiring),
`src/feelies/risk/{basic_risk,position_sizer,hazard_exit}.py`,
`src/feelies/core/events.py` (`RegimeState`, `RegimeHazardSpike`),
all `alphas/*/*.alpha.yaml` `regime_gate:` and `hazard_exit:` blocks,
existing tests for the above, and the four primary doc sources
(`.cursor/skills/regime-detection/SKILL.md`,
`.cursor/skills/microstructure-alpha/SKILL.md`,
`.cursor/skills/risk-engine/SKILL.md`, `docs/three_layer_architecture.md`).
**Mode:** Read-only, evidence-based, then implementation.
**Merged via:** PR #96 + follow-up `6c6a420`.

> Severity legend: **P0** correctness / safety control silently dead,
> **P1** economic soundness / contract drift, **P2** research / cleanup.
> Effort S/M/L.

## 0. Remediation status

Landed every actionable P0/P1/P2 item plus a follow-up the merge
review surfaced (HM-1 derivation for PORTFOLIO modules). End state:
**273 / 273** tests across the regime stack green, Level-5
hazard-replay parity hash bit-identical, no replay-determinism
regressions elsewhere.

### Headline finding

The audit's top finding was a **silently dead safety control**:
`sig_hawkes_burst_v1.alpha.yaml` declared `hazard_exit.enabled: true`
with `posterior_drop_threshold: 0.30`, but

1. `_create_hazard_detector` scanned the **whole registry** and built
   a detector that emitted `RegimeHazardSpike` events on the bus, while
2. `HazardExitController` was constructed **only from PORTFOLIO
   modules** in `_create_composition_layer` — and the alpha was
   `layer: SIGNAL`.

So spikes were emitted to a bus with zero subscribers. On top of that,
the field name `posterior_drop_threshold` was silently dropped by the
loader (no validation) and the controller defaulted to `0.85` even when
it ran — so the author's 0.30 intent would have been ignored even in
the PORTFOLIO path.

The fix repaired both layers: hazard wiring scans `registry.active_alphas()`,
the loader rejects unknown `hazard_exit:` keys, and the legacy field
name is translated with a `WARN`.

| Item | Tier | Status | Notes |
|---|---|---|---|
| **H-1** SIGNAL-layer `hazard_exit.enabled` got no controller — spikes emitted to a dead bus | P0 | ✅ | Lifted `_create_hazard_exit_controller` out of composition; scans full registry; SIGNAL modules fall back to platform `symbols` for universe; PORTFOLIO modules keep their per-alpha universe |
| **H-2** Loader accepted any keys under `hazard_exit:` — author's `posterior_drop_threshold: 0.30` silently dropped | P1 | ✅ | Strict schema in `_parse_hazard_exit_block`; unknown keys raise `AlphaLoadError`; legacy spelling translated with `WARN`; values type-coerced + range-checked |
| **G-1** Gate `ZeroDivisionError`/`TypeError` escaped fail-safe path (DSL whitelists `/ % //`) | P1 | ✅ | `HorizonSignalEngine._dispatch_one` catches `(ZeroDivisionError, ArithmeticError, TypeError, ValueError)`; resets latch + unwinds open position (Inv-11 fail-safe) |
| **R-1** EV regime factor un-clamped — operator could amplify exposure above 1.0 baseline | P1 | ✅ | `min(EV, 1.0)` clamp in both `BudgetBasedSizer._get_regime_factor` and `BasicRiskEngine._regime_scaling` — Inv-11 enforced at the value level, not via config discipline |
| **E-1** Checkpoints portable across differently-configured engines → silent replay divergence | P1 | ✅ | Schema bumped 1 → 2; carries `flags_fingerprint` (canonical hash of `state_names`, transition matrix, `*_enabled` flags); `restore` rejects mismatch; legacy v1 blobs load with one-shot WARN |
| **HM-1** `hard_exit_age_seconds` null → no hard-age exit (short-half-life mechanisms uncapped) | P1 | ✅ | Derive `2 × expected_half_life_seconds` from manifest when omitted; explicit values honored verbatim; covers SIGNAL **and** PORTFOLIO modules (follow-up `6c6a420`) |
| **GC-1** `posterior_margin` / `percentile_margin` declared but never referenced — dead config in 5/7 gates | P1 | ✅ | `RegimeGate.from_spec` walks both ASTs and `WARN`s on unreferenced margin keys at load time |
| **C-1** Doc / impl drift on idempotency key, EV semantics, spike schema, suppression-key layering, state-name canonical form | P1 | ✅ | Skills + arch doc reconciled: `(symbol, sequence)` idempotency, EV-over-posteriors with clamp (not dominant-name), `RegimeHazardSpike` actual fields, detector vs controller suppression keys, `compression_clustering` canonical |
| **#1** `posterior()` watermark set before successful update → cache poisoning on mid-update exception | P0 | ✅ | (Landed in `3424b3f`) Watermark commit moved after `_posteriors[symbol] = updated` |
| **#3** `_EPS_DENOMINATOR` doc said "no spike below floor"; code only floored divisor and still emitted | P1 | ✅ | (Landed in `3424b3f`) Doc corrected to match the bounded-score behavior |
| **#8** Decision pipeline duplicated in stateful detector vs pure `detect()` — drift risk | P1 | ✅ | (Landed in `3424b3f`) Stateful detector now delegates; `_SuppressionKey` dataclass removed; locked L5 hash unchanged |
| **#10** `dominant_state` (int) and `dominant_name` (str) on `RegimeState` never cross-checked | P1 | ✅ | (Landed in `3424b3f`) `_validate_pair` enforces `state_names[dominant_state] == dominant_name` + bounds + `len(posteriors)==len(state_names)` |
| **#12** L5 hazard-replay "locked baseline" test was tautological (recomputed expected via same code path) | P1 | ✅ | (Landed in `3424b3f`) Replaced with frozen literal `EXPECTED_LEVEL5_HAZARD_HASH` |
| **#13** Orchestrator comment promised session-boundary clear that didn't exist; spike-prev pair leaked across sessions | P0 | ✅ | (Landed in `3424b3f`) `_reset_regime_session_state()` clears `_last_regime_state` + calls `_regime_hazard_detector.reset()`; wired into `run_backtest` / `run_paper` / `run_live` |
| **E-4** Pairwise-separation gate rejection left engine uncalibrated forever (returned False, no fallback) | P2 | ✅ | Soft-fail: WARN + retain constructor-default emissions; default still off (replay-parity preservation) |
| **GC-2** `sig_moc_imbalance_v1` was schedule-gated; `regime_engine` + `hysteresis` were dead config | P2 | ✅ | Dead `hysteresis` block removed from YAML; `regime_engine` retained as attach hint |
| **E-2** `transition_time_scaling_enabled` default off; per-tick dwell mismatches 10–100× intraday quote-rate variation | P2 | 🟡 deferred | Flip would break replay parity for existing deployments; needs data run (see §3) |
| **E-3** Spread-only taxonomy misses vol-without-spread, inventory, info asymmetry | P2 | 🟡 deferred | Research-scope; needs design doc, separate PR |

### Tests added / modified

* `tests/services/test_regime_engine.py` — atomicity (`TestUpdateAtomicity`), uncalibrated warning, checkpoint flags fingerprint (4 cases), schema-version bump
* `tests/services/test_regime_engine_improvements.py` — schema v2 expectation
* `tests/services/test_regime_hazard_detector.py` — dominance-consistency contract (3 new contract checks)
* `tests/services/test_hazard_exit_controller_wiring.py` — **new** focused unit suite for `_create_hazard_exit_controller` (6 tests; SIGNAL opt-in, PORTFOLIO opt-in, HM-1 default, explicit override, zero-half-life null, disabled-block skip)
* `tests/services/test_regime_hazard_engine_wiring.py` — session-boundary reset (4 cases)
* `tests/signals/test_regime_gate_dsl.py` — GC-1 hysteresis-dead-config warning (2 cases)
* `tests/signals/test_horizon_signal_engine.py` — G-1 fail-safe on `ZeroDivisionError` and `TypeError` (2 cases)
* `tests/risk/test_position_sizer.py` — R-1 clamp on amplifier factor
* `tests/alpha/test_loader_v03_blocks.py` — H-2 strict schema (5 new cases: known keys, unknown rejection, legacy translation + WARN, dual-spelling rejection, range checks)
* `tests/bootstrap/test_composition_wiring.py` — SIGNAL-layer hazard wiring (2 cases) + shared fingerprint sensor catalog
* `tests/determinism/test_regime_hazard_replay.py` — frozen `EXPECTED_LEVEL5_HAZARD_HASH`
* `tests/integration/test_hazard_exit_e2e.py` — **new** end-to-end coverage (6 cases): long-spike-closes, short-spike-closes, threshold-gate-suppression, min-age-blocks-unseasoned, Inv-11 exit-only on flat, per-policy universe filter
* `tests/_fixtures/sensor_specs.py` — **new** shared G16 fingerprint-sensor catalogs (per-family + union)

### Cached-data validation status

This audit's fixes are **structural / contract correctness** —
the empirical questions live in §3 below and are not blocked by
this PR.  Recommend running them upstream of any future regime
default-flip (E-2) or taxonomy extension (E-3).

## 1. Engine math (HMM3StateFractional)

The class is a fixed-structure online forward filter — Markov
prediction + diagonal Gaussian emissions on `o = log(spread/mid)` —
**not** a full Baum–Welch / EM HMM fit
(Hamilton 1989, *Econometrica* 57:357; Kim 1994, *J. Econometrics*
60:1).  Calibration fits emission moments per tercile; the
transition matrix is author-controlled.  Document this distinction
explicitly in the class docstring so reviewers don't grade the
filter against EM conventions.

Idempotency keyed on `(symbol, sequence)` — **not** `(symbol,
timestamp_ns)` as an earlier doc draft said.  Sequence is the
right key because two distinct quotes can share a ns timestamp
but never a sequence; replay determinism is preserved.

Tick-time semantics: `p_stay = 0.99` per quote → mean dwell
~100 ticks.  At 10 / 50 / 100 quotes·s⁻¹ that's 10 / 2 / 1 s —
far shorter than the 120–600 s alpha horizons.  Doc updated to
make this explicit; `transition_time_scaling_enabled` exists but
is off by default (replay-parity blocker — see §3 E-2).

## 2. Gate / hazard / consumer coherence

* **Gate DSL** parse-time safety passes: whitelist + AST validator
  block `Attribute`, `Subscript`, `Lambda`, comprehensions, and
  any `Call` outside `{abs, min, max, P}`.  I could not construct
  a scope-escape with the allowed set.
* **Causality (Inv-6):** `_build_bindings` reads only the
  boundary snapshot's `values` + `sensor_cache` (latest ≤ T,
  single ordered bus loop) + cached `RegimeState` selected by
  `engine_name` (deterministic; multi-engine fallback picks
  max-timestamp + WARN).
* **Cross-layer semantics:** gate uses hard `P(state) > τ` and
  sometimes `dominant`; risk + sizer use EV-over-posteriors with
  `min(EV, 1.0)` clamp; hazard reads `dominant_state` index.
  Three views — direction-consistent, all clamped to ≤ 1×
  exposure, in series (sizer proposes, risk caps).  No
  double-scaling.
* **Hazard detector** is pure, single-source (post #8 dedupe),
  session-resettable (post #13), with the dominance-consistency
  contract from #10.  L5 replay-parity hash unchanged through
  every fix in this PR.

## 3. Open empirical validations (recommended before any default flip)

The audit deferred five data-dependent questions to the
"need real microstructure" appendix.  They block any future
decision on **E-2** (transition-time scaling default) and
**E-3** (taxonomy expansion) — recommend running them as
notebooks under `audits/notebooks/` upstream of further code
changes.

| # | Question | Decides | Data |
|---|---|---|---|
| V-1 | Emission separation `d` per pair after calibration on real NBBO | Whether to default-enable `enforce_min_pairwise_emission_separation` | AAPL + SPY 30-day NBBO cache |
| V-2 | Intraday quote-rate distribution per cohort | Whether to flip `transition_time_scaling_enabled` default + value of `transition_dt_reference_seconds` | universe-wide quote rate sample |
| V-3 | Posterior-bucketed forward returns by `P(normal)` decile | Whether "normal" carries edge or is just a spread label (informs E-3 scope) | AAPL + universe sample with horizon-bucketed forward mids |
| V-4 | Gate ON/OFF conditional Sharpe / hit rate / cost for the three KYLE alphas | Whether the gate selects economically better microstructure | sig_kyle_drift_v1, sig_benign_midcap_v1 replay |
| V-5 | Hazard precision: P(actual flip in next 5 ticks ⏐ `hazard_score ≥ 0.30`) | Validates the now-canonical 0.30 threshold on sig_hawkes_burst_v1 | regime-flip-rich session replay |

## 4. Open structural items the audit flagged but did not fix

* **Universe-symbol consistency for SIGNAL hazard policies.**
  SIGNAL modules don't carry a per-alpha universe, so the
  controller falls back to platform-wide `symbols`.  This is
  correct today (the only SIGNAL opt-in trades a subset of
  platform symbols), but if SIGNAL alphas ever need a narrower
  universe than the platform, surface it on the loaded module.
* **Calibration is one-shot at boot.**  Live deployments
  spanning many sessions would benefit from periodic re-fit on
  rolling-window quotes; currently the engine is calibrated
  once during `_calibrate_regime_engine` and runs forever on
  that emission triple.  Drift detection is not implemented.
* **Hazard-score is a per-tick relative decay, not a
  time-normalized hazard rate.**  Two slow-decay sequences over
  different quote gaps produce identical `hazard_score` values.
  Not a bug — but the naming overpromises vs. survival-analysis
  λ(t) = f(t) / S(t).  Either rename the field (replay-parity
  cost) or document the semantic distinction.

## 5. References

* PR #96 — audit fixes + e2e coverage
* Audit transcript: `session_01NvSiYeP5NX3wfSWYBJcxsB`
* L5 hazard-replay parity:
  `tests/determinism/test_regime_hazard_replay.py:EXPECTED_LEVEL5_HAZARD_HASH`
