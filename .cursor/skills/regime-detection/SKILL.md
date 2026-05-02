---
name: regime-detection
description: >
  Platform-level regime detection + hazard-spike service for the
  feelies platform. Owns the `RegimeEngine` protocol, the
  `RegimeState` event, the state taxonomy, the
  `RegimeHazardDetector` (and the `RegimeHazardSpike` event consumed
  by `HazardExitController`), and the writer/reader contract. Use
  when designing regime-aware components, integrating regime
  posteriors into risk or sizing, extending the state taxonomy,
  swapping HMM implementations, or reasoning about hazard-detection
  semantics, idempotency, or consumer contracts.
---

# Regime Detection — Platform Service

The regime engine is a shared, platform-level service that classifies
market microstructure state per symbol on every tick. It produces a
posterior probability vector over a discrete set of regime states,
consumed read-only by risk, sizing, the `RegimeGate` DSL bindings on
SIGNAL alphas, and the hazard detector.

The orchestrator is the **sole writer** to the engine. All other
consumers are read-only.

The Phase 3.1 amendment adds `RegimeHazardDetector`
(`services/regime_hazard_detector.py`), a pure function over two
consecutive `RegimeState` events that emits `RegimeHazardSpike`
events when a regime flip is imminent. The spike is consumed by
`HazardExitController` (risk-engine skill) for hazard-driven
position exits.

## Core Invariants

Inherits Inv-5 (deterministic replay), Inv-7 (event-driven typed
schemas), Inv-10 (clock abstraction), Inv-11 (fail-safe default).
Additionally:

1. **Single-writer** — only the orchestrator calls `posterior()`,
   once per tick at micro-state M2 (STATE_UPDATE). No other component
   may call `posterior()`.

2. **Idempotency** — `posterior()` caches per `(symbol,
   timestamp_ns)`. If called multiple times for the same symbol and
   timestamp, the Bayesian update is applied only once; subsequent
   calls return the cached result. Prevents double-update corruption.

3. **Read-only consumers** — risk engine, position sizer, regime-gate
   DSL bindings, and forensic consumers access regime state via
   `current_state()` only. Alpha namespaces receive
   `regime_posteriors` (bound to `current_state`) and
   `regime_state_names` — never the engine itself.

4. **Fail-safe default** — when no regime data is available (engine
   absent, symbol never updated, or empty posteriors), all consumers
   default to neutral scaling (`1.0×`). Regime state never amplifies
   exposure beyond baseline (Inv-11).

5. **Determinism** — same quote sequence produces identical posterior
   sequences. No randomness, no external I/O in `posterior()`.

6. **Hazard purity** — `RegimeHazardDetector.detect(prev, curr)` is
   a pure function of two consecutive `RegimeState` events; it
   introduces no new state and no new clock dependency, so replay is
   bit-identical (Inv-5; verifiable via the Level-5 hazard-parity
   hash).

---

## `RegimeEngine` Protocol

`services/regime_engine.py`:

```python
class RegimeEngine(Protocol):
    @property
    def state_names(self) -> Sequence[str]: ...
    @property
    def n_states(self) -> int: ...

    def posterior(self, quote: NBBOQuote) -> list[float]: ...
    def current_state(self, symbol: str) -> list[float] | None: ...
    def reset(self, symbol: str) -> None: ...
```

| Method | Mutates state | Caller |
|--------|--------------|--------|
| `posterior(quote)` | Yes (Bayesian update) | Orchestrator only (M2) |
| `current_state(symbol)` | No (read cache) | Risk engine, position sizer, regime-gate, forensics |
| `reset(symbol)` | Yes (clear cache) | Orchestrator (recovery), tests |
| `state_names` | No | Any |
| `n_states` | No | Any |

---

## Default State Taxonomy

`HMM3StateFractional` (`services/regime_engine.py`) defines three
canonical states:

| Index | Name | Interpretation | Typical risk response |
|-------|------|----------------|----------------------|
| 0 | `compression_clustering` | Low vol, tight spreads | Reduced edge; size down |
| 1 | `normal` | Typical conditions | Baseline sizing |
| 2 | `vol_breakout` | High vol, wide spreads | Elevated risk; halve size |

State names are **not hardcoded** in consumers. Risk engine and
position sizer look up names from `state_names` and apply
configurable scaling factors per name. Consumers handle unknown
names by defaulting to `1.0×`.

### Extensibility

New state taxonomies are added by:

1. Implementing `RegimeEngine` with the desired states
2. Registering via `register_engine(name, engine_cls)`
3. Selecting in `PlatformConfig.regime_engine` by name
4. Updating consumer scaling-factor maps (risk config, sizer config)

The platform does not require exactly 3 states. Any `n_states ≥ 2`
is valid.

---

## Writer / Reader Contract

```
Tick pipeline:
  M0 → M1 (quote logged + bus published)
       → M2: orchestrator calls regime_engine.posterior(quote)
              → publishes RegimeState event on the bus
       → SENSOR_UPDATE: sensors run; regime read-only available
       → HORIZON_AGGREGATE: snapshot built
       → SIGNAL_GATE: HorizonSignal.evaluate sees RegimeState (read-only)
                      regime_gate DSL evaluates against regime posteriors
       → CROSS_SECTIONAL: composition reads regime via depends_on edges
       → M5: risk engine calls current_state(symbol) in check_signal /
              check_sized_intent
              position sizer calls current_state(symbol)
       → M6: risk engine calls current_state(symbol) in check_order
```

The single-writer guarantee means `current_state()` at any downstream
sub-state always returns the posteriors computed at M2 for the
current tick.

---

## `RegimeState` Event

`core/events.py`:

```python
@dataclass(frozen=True, kw_only=True)
class RegimeState(Event):
    symbol: str
    engine_name: str
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_state: int
    dominant_name: str
```

Published by the orchestrator at M2 after `posterior()` returns.

Consumers:

- Risk engine — `current_state(symbol)` → scaling factor
- Position sizer — `current_state(symbol)` → capital scalar
- Regime-gate DSL — bindings `P(<state_name>)`, `dominant`
- `RegimeHazardDetector` — pairs of consecutive `RegimeState` events
- Post-trade forensics — regime-stability audit

---

## Hazard Detection (Phase 3.1)

`services/regime_hazard_detector.py` produces `RegimeHazardSpike`
events from pairs of consecutive `RegimeState` events.

### `RegimeHazardSpike` Event

```python
@dataclass(frozen=True, kw_only=True)
class RegimeHazardSpike(Event):
    symbol: str
    engine_name: str
    departing_state: str
    incoming_state: str | None        # may be None if not yet dominant
    posterior_drop: float             # signed drop in P(departing_state)
    boundary_ts_ns: int
```

### Detection Logic

`RegimeHazardDetector.detect(prev, curr)` flags a spike when:

- Both `RegimeState` events agree on `engine_name` and `symbol`
- The dominant state in `prev` shows a significant posterior drop in
  `curr` (a "departure episode")
- A regime flip is therefore imminent

Suppression is per `(symbol, engine_name, departing_state)`: at most
one spike per departure episode; re-arms only when a different state
becomes dominant or the departing posterior recovers above the
`1.0 − hysteresis_threshold` floor.

### Pure-Function Property

`detect()` is a pure function of two `RegimeState` events. No new
state is introduced beyond the suppression key cache (which is itself
deterministic given the input sequence). Replay is bit-identical
(Inv-5; locked by L5 hazard-parity test
`tests/determinism/test_hazard_parity.py`).

### Wiring

`HazardExitController` (risk-engine skill) consumes
`RegimeHazardSpike` events and emits `OrderRequest.reason ∈
{"HAZARD_SPIKE", "HARD_EXIT_AGE"}` to flatten open positions when:

- Posterior drop exceeds the per-alpha `hazard_score_threshold`
- The position has been open at least `min_age_seconds`

Wired behind alpha-level `hazard_exit.enabled: true` (default off,
v0.2-compatible).

Hazard-driven exits are **exit-only**: entries on a stale regime are
forbidden by Inv-11. The spike never closes a position by itself —
it surfaces a microstructure signal that the controller may act on.

---

## Consumer Contract

### Risk Engine

Reads `current_state(symbol)` in `_regime_scaling()`. Maps the
dominant state name to a position-limit multiplier. Unknown states
default to `1.0×`.

### Position Sizer

`BudgetBasedSizer._get_regime_factor()` applies a regime-dependent
capital scaling factor. Missing data defaults to `1.0×`.

### Regime-Gate DSL

`signals/regime_gate.py` parses the alpha YAML's `regime_gate:`
block into a safe AST-evaluated boolean DSL. Bindings drawn from
`RegimeState`:

- `P(<state_name>)` — posterior probability of the named state
- `dominant` — name of the dominant state

Plus from the live sensor cache:

- `<sensor_id>` — raw value
- `<sensor_id>_zscore` — z-score
- `<sensor_id>_percentile` — percentile

The gate is the purity boundary: never reads untyped state, never
imports, never mutates the snapshot.

### Forensic Consumers

Post-trade-forensics reads `RegimeState` events from the audit log
to compute the `RegimeBucket` axis of `MultiHorizonAttributor` and
to audit regime classification accuracy over time.

---

## Event Interface

| Event | Direction | Notes |
|-------|-----------|-------|
| `NBBOQuote` | In (from ingestion) | Consumed by `posterior()` |
| `RegimeState` | Out (to bus) | Published after each `posterior()` call |
| `RegimeHazardSpike` | Out (to bus) | Published from pairs of consecutive `RegimeState` events |

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Engine not configured | `regime_engine is None` | All consumers default to `1.0×` (Inv-11) |
| Symbol never updated | `current_state()` returns `None` | Consumers default to `1.0×` |
| Empty posteriors list | `len(posteriors) == 0` | Treat as `None` |
| NaN in posteriors | Bayesian update divergence | `reset(symbol)` and re-initialize |
| Engine raises in `posterior()` | Caught by orchestrator at M2 | Tick degrades; cached state preserved |
| Hazard detector receives mismatched engine_name | `_validate_pair` raises `HazardDetectorContractError` | Tick degrades to DEGRADED; investigate engine swap |

---

## Integration Points

| Dependency | Interface | Direction |
|------------|-----------|-----------|
| Orchestrator | `posterior()` at M2 | Provides |
| Risk engine | `current_state()` | Provides |
| Position sizer | `current_state()` | Provides |
| Regime-gate DSL | `current_state`, `state_names` | Provides |
| `HazardExitController` | `RegimeHazardSpike` | Provides (via the hazard detector) |
| Event bus | `RegimeState`, `RegimeHazardSpike` published | Emits |
| Platform config | `regime_engine: str` selects implementation | Consumes |
| Engine registry | `register_engine`, `get_regime_engine` | Provides |
| Post-trade forensics | `RegimeState` for `RegimeBucket` attribution | Consumed by forensics |
| Testing & Validation | L5 hazard-parity hash; idempotency property tests | Provides |
