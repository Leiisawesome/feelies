<!--
  File:   docs/audits/engine_readiness_checklist_2026-06-19.md
  Status: ENGINE-READINESS CHECKLIST (read-only assessment of the current tree).
  Scope:  The alpha-neutral hot path
          NBBOQuote/Trade → SensorRegistry → SensorReading → HorizonScheduler →
          HorizonTick → HorizonAggregator → HorizonFeatureSnapshot →
          HorizonSignalEngine → Signal(layer="SIGNAL").
  Goal:   Define "engine done" = the measurement apparatus is trustworthy enough
          that gas (sensor/feature) quality can be selected on evidence it
          produces.  This is the EXIT GATE from the engine phase to the gas phase.
-->

# Engine-Readiness Checklist — 2026-06-19

The "engine" is the alpha-neutral pipeline; the "gas" is the sensors/features.
The engine is the **measurement apparatus** — until it is trustworthy, every IC
/ RankIC / backtest number computed on the gas is measured with a bent ruler.
This checklist is the exit gate from *engine* work to *gas* work.

Legend: ✅ done · 🟡 partial (scoped issue below) · ⬜ open (scoped issue below).
"Engine done" = every row ✅ **or** consciously accepted with its effect documented.

| # | Criterion | Status | Evidence (current tree) |
|---|-----------|:------:|--------------------------|
| 1 | Deterministic, bit-identical replay | ✅ | `tests/determinism/parity_manifest.py` (44 locked constants); Level-1/2/3 replay tests `test_sensor_reading_replay` / `test_signal_replay` / `test_horizon_feature_snapshot_replay`. Transcendental sensors locked intra-process (`test_transcendental_determinism.py`); cross-libm caveat documented in `parity_manifest.py`. |
| 2 | Causality — no lookahead; contemporaneous regime | ✅ | Bus-driven depth-first order in `kernel/orchestrator.py:2297` (publish quote → sensors → `aggregator.observe`) → `:2361` (`_update_regime`) → `:2370` (`_dispatch_sensor_layer` → scheduler tick → `finalize` → snapshot → gate). The crossing quote is folded **before** `finalize`; regime is published **before** the snapshot chain. No path sees data after `snapshot.timestamp_ns`. |
| 3 | Honest boundary timestamps | ✅ | **ENG-1 done:** `HorizonTick` / `HorizonFeatureSnapshot` now carry `boundary_ts_ns` (the exact nominal grid boundary) alongside `timestamp_ns` (the trigger). Set in `horizon_scheduler._make_tick`, carried in `aggregator._build_snapshot`. Additive (default 0) — no golden rebaseline (both replay hashes use explicit field lists). Tests: `tests/sensors/test_boundary_ts.py`. |
| 4 | Fail-safe containment — non-finite | ✅ | Registry suppresses NaN/Inf (scalar + tuple): `sensors/registry.py:_is_finite_value`, `_on_event` (suppress + WARN + `feelies.sensor.nonfinite.count`); aggregator demotes a non-finite feature to cold (`features/aggregator.py:_build_snapshot`). Tests: `test_robustness_3p.py`. |
| 5 | Fail-safe containment — bad market data | ✅ | All 11 price-consuming sensors reject `bid<=0`, `ask<=0`, **and** crossed `bid>ask` (mid-carriers reset carry-forward mid). Sizes-only `book_imbalance` and price-agnostic `quote_hazard_rate` intentionally exempt. |
| 6 | Fail-safe gate — errors never strand a position | ✅ | Every gate-eval exception path forces the latch OFF and unwinds if previously ON (`signals/horizon_engine.py:389-468`); `entry_blocked` is separated from gate eval (`:356, 470-480`) so ON→OFF exits fire even when a required feature is cold/stale. Warm/stale gates **entry only** (exits permitted). |
| 7 | Gating semantics — gate only on consumed features | ✅ | `required_warm` is consume-driven: bootstrap statically parses the `signal:` body for the `snapshot.values` keys it reads (`bootstrap.py:_consumed_value_keys_from_signal_source` @1390, used @1480), with a conservative fall-back when keys can't be resolved. Tests: `tests/bootstrap/test_required_warm_consume_driven.py`. |
| 8 | Throttle dispatch contract locked | ✅ | `SensorSpec` warns on `throttled_ms` without `stateful=True` (`sensors/spec.py`); registry dispatch golden in `tests/sensors/test_throttle_dispatch.py` (stateful → update every event, emit sparsely; stateless → skip update in window). |
| 9 | Observability — engine behaviour is visible | ✅ | Sensor/aggregator metered: `feelies.sensor.reading.count`, `feelies.sensor.nonfinite.count`, `feelies.horizon.tick.emitted`, `feelies.feature.snapshot.stale_fraction`. **ENG-2 done:** the signal engine now emits `feelies.signal.gate.transition` (to=ON\|OFF), `feelies.signal.entry.suppressed` (reason=not_warm\|stale), `feelies.signal.gate.failsafe_unwind` (reason), `feelies.signal.emitted` (direction) on a dedicated metrics sequence (off the locked Signal stream). `signals/horizon_engine.py:_emit_metric`; tests `tests/signals/test_horizon_engine_metrics.py`. |
| 10 | Known-answer measurement harness | ✅ | **ENG-3 done.** Stats core + bucketing already shipped (`feelies.research.forward_ic`: `spearman_ic` w/ p-value, `bucketed_forward_return`; certified by `tests/research/test_forward_ic.py`). This change adds the **end-to-end apparatus certification** (`tests/research/test_ic_apparatus_certification.py`): a deterministic tape replayed through the *real* `SensorRegistry→HorizonScheduler→HorizonAggregator`, asserting the boundary value is causal + exact, the final boundary's forward pair is dropped (no look-ahead), and a co-/anti-monotone reference measures RankIC = +1.0 / −1.0 — i.e. the apparatus introduces *zero* pairing error. |

**Verdict:** **10 of 10 ✅ — ENGINE DONE (2026-06-19).** The measurement
apparatus is certified: deterministic, causal, fail-safe-contained, correctly
gated, observable, and proven to pair feature values with forward returns with
zero error. This is the green light to start the **gas phase** — selecting
premium sensors/features on IC evidence the certified engine produces.

---

## Open issues

### ENG-1 — Explicit boundary-timestamp semantics ✅ DONE (2026-06-19)

**Delivered.** `HorizonTick` and `HorizonFeatureSnapshot` now carry
`boundary_ts_ns` (the exact nominal grid boundary `session_open_ns + k·h·1e9`)
alongside `timestamp_ns` (the trigger). The scheduler sets it from the value it
already computes for the correlation id (`horizon_scheduler._make_tick`); the
aggregator carries it through (`aggregator._build_snapshot`). The change is
**additive** (default 0 = unset) and required **no golden rebaseline** — both
replay hashes (`hash_horizon_tick_stream`, `_hash_snapshot_stream`) and the
JSONL emitter use explicit field lists that don't include the new field. Tests:
`tests/sensors/test_boundary_ts.py`.

**Refinement vs the original framing.** *Single-symbol IC is honest* (window and
forward return share the `t_cross` anchor), and **cross-sectional sync was
already correct** — `UniverseSynchronizer` keys the barrier on `boundary_index`
(the nominal boundary identifier), not on wall time, so symbols were already
aligned by nominal boundary. The real value of `boundary_ts_ns` is therefore
**label / forensic honesty**: consumers (the IC harness, attribution) can now
anchor to a regular grid and *measure* the nominal-vs-trigger jitter instead of
inheriting it silently. No composition-layer rewire was needed; the field is now
available if a future consumer wants to pair on the nominal grid.

---

### ENG-2 — Meter the signal engine ✅ DONE (2026-06-19)

**Delivered.** The `HorizonSignalEngine` now emits four counters via
`_emit_metric` on a dedicated metrics sequence (collector, not bus — zero effect
on the locked Signal stream; `None` collector is a no-op):
- `feelies.signal.gate.transition` (`alpha_id`, `to=ON|OFF`) — normal ON↔OFF,
- `feelies.signal.entry.suppressed` (`alpha_id`, `reason=not_warm|stale`),
- `feelies.signal.gate.failsafe_unwind` (`alpha_id`, `reason`) — error-forced OFFs,
- `feelies.signal.emitted` (`alpha_id`, `direction`).
Wired through `bootstrap._create_signal_layer` → `HorizonSignalEngine`. Tests in
`tests/signals/test_horizon_engine_metrics.py`; signal parity goldens unchanged.

---

### ENG-3 — Known-answer measurement harness ✅ DONE (2026-06-19)

**Delivered (across the merge + this change).**

1. **Stats core + stratification — already shipped** in the merged
   `feelies.research.forward_ic`: `spearman_ic` (rank IC with a Fisher-z
   p-value), `bucketed_forward_return` (equal-count conditional-forward-return
   profile), and `forward_return_at` (causal, no-look-ahead pairing). Certified
   by `tests/research/test_forward_ic.py` (rho = ±1, monotone-nonlinear, ties,
   NaN drops, constant→0).
2. **End-to-end apparatus certification — added here**
   (`tests/research/test_ic_apparatus_certification.py`): a deterministic tape is
   replayed through the **real production** path
   `SensorRegistry → HorizonScheduler → HorizonAggregator`, and the warm boundary
   values are paired with forward returns via the same `forward_return_at` the
   harness uses. Asserts (a) the boundary value is **causal + exact** (reflects
   exactly the quotes ≤ the snapshot time, never a later one), (b) the final
   boundary's forward pair is **dropped** (no look-ahead off the tape end), and
   (c) a co-/anti-monotone reference measures RankIC = **+1.0 / −1.0** — proving
   the apparatus introduces *zero* pairing error and preserves sign. **This is
   the certification that lets IC numbers be trusted.**

**Promotion gate (policy).** No gas (sensor/feature) is promoted to an alpha
input without: a **sign golden** (`tests/sensors/test_sensor_sign_goldens.py`
pattern) **and** an IC pass through this certified harness — RankIC of the
right sign, ideally with a monotone `bucketed_forward_return` profile, and
(when the question is regime-conditional) stratified by the relevant condition.

**Follow-up (non-blocking).** The driver script `scripts/sensor_feature_ic.py`
still presets only 4 families; extending it to inventory / Hawkes / stress /
scheduled-flow is mechanical (the `forward_ic` core already measures any
feature). Regime/cost stratification is a bucketer plugged into
`bucketed_forward_return`. Neither gates "engine done."

---

## Sequencing recommendation

1. ~~**ENG-2**~~ ✅ **done (2026-06-19)** — the engine is now instrumented, so you
   can *watch* the next two changes land.
2. ~~**ENG-1**~~ ✅ **done (2026-06-19)** — boundary-timestamp semantics are now
   explicit; the IC harness can anchor to the nominal grid.
3. ~~**ENG-3**~~ ✅ **done (2026-06-19)** — the measurement apparatus is certified
   (zero pairing error, sign-preserving). **Engine done — start the gas phase.**

All ten rows are ✅. "Engine first" is complete: the ruler is calibrated and
certified. Gas selection (premium sensors/features, mechanism-matched reducers,
the sig_benign improvements: integrated OFI, dwell-weighted imbalance, an
orthogonal trade-side confirmation) can now proceed on IC evidence the engine
produces — not on intuition.
