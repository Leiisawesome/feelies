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
| 3 | Honest boundary timestamps | 🟡 | `HorizonTick.timestamp_ns = ts_ns` (the trigger event), not the nominal integer boundary; the boundary time lives only in the correlation id (`sensors/horizon_scheduler.py:304, 314`). No `boundary_ts_ns` field on `HorizonTick` / `HorizonFeatureSnapshot` (`core/events.py`). → **ENG-1**. |
| 4 | Fail-safe containment — non-finite | ✅ | Registry suppresses NaN/Inf (scalar + tuple): `sensors/registry.py:_is_finite_value`, `_on_event` (suppress + WARN + `feelies.sensor.nonfinite.count`); aggregator demotes a non-finite feature to cold (`features/aggregator.py:_build_snapshot`). Tests: `test_robustness_3p.py`. |
| 5 | Fail-safe containment — bad market data | ✅ | All 11 price-consuming sensors reject `bid<=0`, `ask<=0`, **and** crossed `bid>ask` (mid-carriers reset carry-forward mid). Sizes-only `book_imbalance` and price-agnostic `quote_hazard_rate` intentionally exempt. |
| 6 | Fail-safe gate — errors never strand a position | ✅ | Every gate-eval exception path forces the latch OFF and unwinds if previously ON (`signals/horizon_engine.py:389-468`); `entry_blocked` is separated from gate eval (`:356, 470-480`) so ON→OFF exits fire even when a required feature is cold/stale. Warm/stale gates **entry only** (exits permitted). |
| 7 | Gating semantics — gate only on consumed features | ✅ | `required_warm` is consume-driven: bootstrap statically parses the `signal:` body for the `snapshot.values` keys it reads (`bootstrap.py:_consumed_value_keys_from_signal_source` @1390, used @1480), with a conservative fall-back when keys can't be resolved. Tests: `tests/bootstrap/test_required_warm_consume_driven.py`. |
| 8 | Throttle dispatch contract locked | ✅ | `SensorSpec` warns on `throttled_ms` without `stateful=True` (`sensors/spec.py`); registry dispatch golden in `tests/sensors/test_throttle_dispatch.py` (stateful → update every event, emit sparsely; stateless → skip update in window). |
| 9 | Observability — engine behaviour is visible | 🟡 | Sensor/aggregator metered: `feelies.sensor.reading.count`, `feelies.sensor.nonfinite.count`, `feelies.horizon.tick.emitted`, `feelies.feature.snapshot.stale_fraction`. **Signal engine emits no metrics** — gate ON/OFF transitions, entry suppression (`entry_blocked`), and fail-safe unwinds (`_publish_gate_close`) are log-only. → **ENG-2**. |
| 10 | Known-answer measurement harness | 🟡 | `scripts/sensor_feature_ic.py` replays through the real registry→scheduler→aggregator and pairs warm snapshots with forward mid-returns (causal, no-lookahead drop) — but covers only 4 families (ofi/micro/realized-vol/kyle), no regime/cost stratification, and there is **no reference-sensor golden** that asserts the snapshot↔forward-return pairing is *exact*. → **ENG-3**. |

**Verdict:** 7 of 10 ✅. The engine is ~80 % done. Three scoped issues remain;
none is a from-scratch effort. ENG-3 is the true bridge to the gas phase.

---

## Open issues

### ENG-1 — Make boundary-timestamp semantics explicit (causality clarity / cross-sectional alignment)

**Problem.** A snapshot is stamped at the *triggering event* time `t_cross`
(the first quote at/after the nominal boundary `T_k`), not at `T_k`
(`horizon_scheduler.py:314`). On sparse mid-cap tapes `t_cross` can be well past
`T_k`.

**Severity: P1, not P0.** It is causal, and *single-symbol* IC is honest: the
feature window `[t_cross−h, t_cross]` and the forward return `[t_cross, t_cross+h]`
are anchored to the same `t_cross`, so the pairing is internally consistent. The
real exposures are:
- **Cross-sectional alignment** — two symbols' "same boundary `k`" snapshots are
  at *different* wall times, so any Layer-3 universe synchronization or
  cross-sectional z at a boundary compares slightly non-contemporaneous states.
- **Decision cadence** — the effective decision interval drifts from `h` on
  sparse names.
- **Forensics** — the nominal-vs-actual divergence is not surfaced, so the
  jitter is invisible to attribution.

**Acceptance criteria.**
- Add `boundary_ts_ns: int` (the exact `T_k = session_open_ns + k·h·1e9`) to
  `HorizonTick` and carry it onto `HorizonFeatureSnapshot`, leaving
  `timestamp_ns` as the trigger time. Consumers (IC pairing, cross-sectional
  sync, staleness) choose explicitly.
- A sparse-tape test: a tape with a multi-minute gap asserts
  `snapshot.boundary_ts_ns == T_k` while `timestamp_ns == t_cross > T_k`.
- Decide and document the cross-sectional sync policy (nominal boundary vs
  trigger) in the composition layer.

**Scope: S–M.** Additive event field + plumbing + one replay rebaseline (the
field changes the hashed snapshot stream). No behavioural change to gating.

**Evidence:** `sensors/horizon_scheduler.py:304, 314`; `core/events.py`
(`HorizonTick` / `HorizonFeatureSnapshot`).

---

### ENG-2 — Meter the signal engine (see the gate working)

**Problem.** The sensor and aggregator layers emit metrics, but the
`HorizonSignalEngine` is log-only. You cannot answer, from telemetry, "how often
is the gate ON?", "how many entries were suppressed for warm/stale?", "how many
fail-safe unwinds fired?" — exactly the signals you need to trust the engine in
production and to debug a silent alpha.

**Acceptance criteria.** Emit counters (dedicated metrics sequence, off the
locked Signal stream — mirror the registry pattern):
- `feelies.signal.gate.transition` (tags: `alpha_id`, `to=ON|OFF`),
- `feelies.signal.entry.suppressed` (tags: `alpha_id`, `reason=not_warm|stale`),
- `feelies.signal.gate.failsafe_unwind` (tags: `alpha_id`, `reason`),
- `feelies.signal.emitted` (tags: `alpha_id`, `direction`).
One test asserts the suppression counter increments when a required feature is
cold.

**Scope: S.** Pure additive instrumentation in `signals/horizon_engine.py`
(`_dispatch_one`, `_publish_gate_close`). No effect on the Signal stream or
parity hashes (separate sequence generator).

**Evidence:** `signals/horizon_engine.py:356-380, 470-480, 517-551`; no
`MetricEvent` in that module today.

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

1. **ENG-2** first (S, zero risk) — instrument the engine so you can *watch* the
   next two changes land.
2. **ENG-1** (S–M) — close the last causality-clarity gap and unblock honest
   cross-sectional work; rebaseline the snapshot parity hash in the same commit.
3. **ENG-3** (M) — build and certify the measurement harness. **This row going
   green is the signal to start the gas phase.**

Everything else (rows 1, 2, 4–8) is already ✅ from the three-pass sensor audit
plus the merged platform work — "engine first" here is *finishing*, not
*building*.
