# `fix(regime): institutional-grade hardening + audit follow-throughs`

Closes the services / regime-stack audit recorded in
`docs/audits/regime_stack_audit_2026-06-04.md`.

## TL;DR — what was broken

**Headline:** `sig_hawkes_burst_v1` declared `hazard_exit.enabled: true`
but the hazard exit it requested was silently non-functional.  The
detector was wired registry-wide, so spikes were emitted on the bus —
to **zero subscribers**, because `HazardExitController` was built
only from PORTFOLIO modules and the alpha is `layer: SIGNAL`.  Even
if it had been wired, the author's `posterior_drop_threshold: 0.30`
field was silently dropped (no loader validation) and the controller
defaulted to `0.85`.

This PR repairs the wiring at both layers and adds eight more
fixes the audit identified along the way.

## What changed

### P0 (correctness / safety)

* **H-1** Hazard wiring covers SIGNAL opt-ins.  Lifted
  `_create_hazard_exit_controller` out of composition layer; scans
  `registry.active_alphas()`; SIGNAL modules fall back to platform
  `symbols` for universe.
* **#1** Fix `posterior()` atomicity — watermark commit moved after
  the Bayesian update, so a mid-update exception no longer poisons
  the cache.
* **#13** Implement `Orchestrator._reset_regime_session_state()` and
  wire it into `run_backtest` / `run_paper` / `run_live`.  The
  orchestrator's comment promised session-boundary clearing that
  didn't exist; spike-prev pair was leaking across sessions.

### P1 (economic soundness / contract drift)

* **H-2** Strict `hazard_exit:` schema in the loader.  Unknown keys
  raise `AlphaLoadError`; legacy `posterior_drop_threshold` is
  translated to canonical `hazard_score_threshold` with a `WARN`;
  values type-coerced + range-checked.
* **G-1** Gate `ZeroDivisionError` / `TypeError` now route through
  Inv-11 fail-safe.  `_dispatch_one` catches arithmetic / type
  errors → reset latch + unwind any open position.
* **R-1** EV regime factor clamped to `min(EV, 1.0)` in both
  `BudgetBasedSizer._get_regime_factor` and
  `BasicRiskEngine._regime_scaling`.  Inv-11 is enforced at the
  value level rather than via config discipline.
* **E-1** Checkpoint schema v2 carries `flags_fingerprint` of the
  constructor-frozen state (state names + transition matrix + all
  `*_enabled` flags); `restore` rejects mismatched configurations.
  Legacy v1 blobs still load with a one-shot warning.
* **HM-1** `hard_exit_age_seconds` defaults to
  `2 × expected_half_life_seconds` when omitted — for SIGNAL and
  PORTFOLIO modules (follow-up `6c6a420`).
* **GC-1** `RegimeGate.from_spec` warns when a declared `hysteresis`
  block names margins that no condition references.
* **C-1** Skills + arch doc reconciled to actual behavior:
  `(symbol, sequence)` idempotency, EV-over-posteriors with clamp,
  `RegimeHazardSpike` actual fields, detector vs controller
  suppression keys, canonical `compression_clustering`.
* **#3** `_EPS_DENOMINATOR` docstring corrected to match the
  bounded-score behavior (the code never short-circuited on near-
  zero `p_prev`, only floored the divisor).
* **#8** Decision pipeline deduped — stateful `RegimeHazardDetector`
  delegates to the pure `detect()` function; `_SuppressionKey`
  dataclass removed.
* **#10** `_validate_pair` enforces `dominant_state ↔ dominant_name`
  consistency + index bounds + `len(posteriors) == len(state_names)`.
* **#12** L5 hazard-replay `EXPECTED_LEVEL5_HAZARD_HASH` is now a
  frozen literal (the prior "locked baseline" recomputed expected
  via the same code path — tautological).

### P2 (research / cleanup)

* **E-4** Calibration soft-fails when the pairwise-separation gate
  rejects emissions (WARN + retain defaults).  Default still off
  to preserve replay parity.
* **GC-2** Dead `hysteresis` block removed from
  `sig_moc_imbalance_v1.alpha.yaml`.

### Deferred

* **E-2** `transition_time_scaling_enabled` default flip — needs
  empirical tick-rate distribution data (see retro §3, V-2).
* **E-3** Additional observation channel (vol / trade intensity) —
  research-scope, needs design doc.

## Tests

**273 / 273 regime-stack tests green.**  L5 hazard-replay parity
hash bit-identical through every fix.

New / modified:

* `tests/services/test_regime_engine.py` — atomicity, uncalibrated
  warning, flags-fingerprint round-trip (4 cases), schema-version bump
* `tests/services/test_regime_engine_improvements.py` — schema v2
* `tests/services/test_regime_hazard_detector.py` — dominance
  consistency (3 cases)
* `tests/services/test_hazard_exit_controller_wiring.py` — **new** —
  focused unit suite for the new helper (6 cases)
* `tests/services/test_regime_hazard_engine_wiring.py` —
  session-boundary reset (4 cases)
* `tests/signals/test_regime_gate_dsl.py` — GC-1 dead-config
  warning (2 cases)
* `tests/signals/test_horizon_signal_engine.py` — G-1 fail-safe
  (2 cases)
* `tests/risk/test_position_sizer.py` — R-1 clamp
* `tests/alpha/test_loader_v03_blocks.py` — H-2 strict schema
  (5 cases)
* `tests/bootstrap/test_composition_wiring.py` — SIGNAL hazard
  wiring (2 cases)
* `tests/determinism/test_regime_hazard_replay.py` — frozen hash
* `tests/integration/test_hazard_exit_e2e.py` — **new** end-to-end
  (6 cases)
* `tests/_fixtures/sensor_specs.py` — **new** shared G16 fingerprint
  sensor catalogs

## Out of scope

* Empirical data validations (V-1 through V-5 in the retro §3) —
  notebook work, no code changes.
* Periodic re-calibration / drift detection — flagged in retro §4.
* Renaming `hazard_score` to make the per-tick-relative-decay
  semantics explicit (L5 parity cost) — flagged in retro §4.

## How to review

1. **Start at the retro:**
   `docs/audits/regime_stack_audit_2026-06-04.md`.  Severity table
   + headline finding is the fastest way to understand what was
   broken.
2. **Read the new helper** `_create_hazard_exit_controller` and
   verify it scans `registry.active_alphas()`, not just PORTFOLIO.
3. **Read the new e2e test** `test_hazard_exit_e2e.py` — six
   behaviours it locks correspond 1-1 to the audit's headline
   claims.
4. **Check the locked baseline** — `EXPECTED_LEVEL5_HAZARD_HASH`
   should be unchanged across all three commits.

## Refs

* Audit transcript: `session_01NvSiYeP5NX3wfSWYBJcxsB`
* Retro: `docs/audits/regime_stack_audit_2026-06-04.md`
