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
| 10 | Known-answer measurement harness | 🟡 | `scripts/sensor_feature_ic.py` replays through the real registry→scheduler→aggregator and pairs warm snapshots with forward mid-returns (causal, no-lookahead drop) — but covers only 4 families (ofi/micro/realized-vol/kyle), no regime/cost stratification, and there is **no reference-sensor golden** that asserts the snapshot↔forward-return pairing is *exact*. → **ENG-3**. |

**Verdict:** 9 of 10 ✅ (ENG-1 + ENG-2 landed 2026-06-19). One scoped issue
remains — **ENG-3**, the true bridge to the gas phase.

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

### ENG-3 — Known-answer measurement harness (the bridge to the gas phase)

**Problem.** This is the decisive missing piece. Before gas can be selected on
evidence, the *ruler* must be certified: a reference sensor whose output is a
known deterministic function so the snapshot↔forward-return pairing can be
asserted **exactly**, plus an IC harness that covers every live mechanism and
stratifies by the conditions that actually move edge (regime, cost, spread).
Today `scripts/sensor_feature_ic.py` is causal and real but covers 4 families
and reports one unconditional RankIC.

**Acceptance criteria.**
1. **Known-answer golden** (`tests/`): a deterministic reference sensor (e.g.
   emits a linear ramp / a unit step) replayed through the real
   registry→scheduler→aggregator; assert the boundary value and the paired
   forward return equal the closed-form expected values to the bit. This
   certifies that the apparatus introduces *zero* pairing error — the
   precondition for trusting any IC number.
2. **Coverage** (`scripts/sensor_feature_ic.py`): add inventory, Hawkes, stress,
   and scheduled-flow specs so every live mechanism is measurable.
3. **Stratification**: output RankIC by horizon **and** by HMM regime posterior,
   spread-z bucket, hazard bucket, and round-trip-cost bucket — so "edge" is
   never a single pooled number that hides where it lives (or doesn't).
4. **Make it the canonical gate**: no gas is promoted to an alpha input without a
   sign golden + a stratified IC pass through this harness.

**Scope: M.** Mostly harness extension (the replay plumbing already exists) plus
one new golden test. No production-code change required.

**Evidence:** `scripts/sensor_feature_ic.py:79-114` (4 specs), `:163-246`,
`:305-324` (replay + pairing); `tests/scripts/test_sensor_feature_ic.py`,
`tests/research/test_forward_ic.py`.

---

## Sequencing recommendation

1. ~~**ENG-2**~~ ✅ **done (2026-06-19)** — the engine is now instrumented, so you
   can *watch* the next two changes land.
2. ~~**ENG-1**~~ ✅ **done (2026-06-19)** — boundary-timestamp semantics are now
   explicit; the IC harness can anchor to the nominal grid.
3. **ENG-3** (M) — build and certify the measurement harness. **This row going
   green is the signal to start the gas phase.** *(last remaining)*

Everything else (rows 1–9 except ENG-1/ENG-3) is ✅ from the three-pass sensor
audit plus the merged platform work — "engine first" here is *finishing*, not
*building*.
