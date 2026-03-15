---
name: regime-detection
description: >
  Platform-level regime detection service for classifying market microstructure
  states via online Bayesian inference. Owns the RegimeEngine protocol,
  RegimeState event, state taxonomy, and writer/reader contract. Use when
  designing regime-aware components, integrating regime state into risk or
  sizing, extending the state taxonomy, swapping HMM implementations, or
  reasoning about regime detection semantics, idempotency, or consumer contracts.
---

# Regime Detection — Platform Service

The regime engine is a shared, platform-level service that classifies
market microstructure state per symbol on every tick. It produces a
posterior probability vector over a discrete set of regime states,
consumed read-only by risk, sizing, and alpha feature layers.

The orchestrator is the sole writer. All other consumers are readers.

## Core Invariants

Inherits platform invariants 5 (deterministic replay), 7 (event-driven
typed schemas), 10 (clock abstraction), 11 (fail-safe default).
Additionally:

1. **Single-writer** — only the orchestrator calls `posterior()`, once
   per tick at micro-state M2 (STATE_UPDATE). No other component may
   call `posterior()`.

2. **Idempotency** — `posterior()` must cache per `(symbol, timestamp_ns)`.
   If called multiple times for the same symbol and timestamp, the
   Bayesian update is applied only once; subsequent calls return the
   cached result. This prevents double-update corruption.

3. **Read-only consumers** — risk engine, position sizer, and alpha
   features access regime state via `current_state()` only. Alpha
   feature namespaces receive `regime_posteriors` (bound to
   `current_state`) and `regime_state_names` — never the engine
   itself.

4. **Fail-safe default** — when no regime data is available (engine
   absent, symbol never updated, or empty posteriors), all consumers
   default to neutral scaling (`1.0x`). Regime state never amplifies
   exposure beyond baseline.

5. **Determinism** — same quote sequence produces identical posterior
   sequences. No randomness, no external I/O in `posterior()`.

## Protocol Ownership

**File:** `services/regime_engine.py`

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

| Method | Mutates State | Who Calls |
|--------|--------------|-----------|
| `posterior(quote)` | Yes (Bayesian update) | Orchestrator only (M2) |
| `current_state(symbol)` | No (read cache) | Risk engine, position sizer, alpha features |
| `reset(symbol)` | Yes (clear cache) | Orchestrator (recovery), tests |
| `state_names` | No | Any (read-only property) |
| `n_states` | No | Any (read-only property) |

## State Taxonomy

The default implementation (`HMM3StateFractional`) defines three states:

| Index | Name | Interpretation | Typical Behavior |
|-------|------|---------------|------------------|
| 0 | `compression_clustering` | Low volatility, tight spreads | Reduced edge; size down |
| 1 | `normal` | Typical trading conditions | Baseline sizing |
| 2 | `vol_breakout` | High volatility, wide spreads | Elevated risk; halve size |

State names are not hardcoded in consumers. Risk engine and position
sizer look up names from `state_names` and apply configurable scaling
factors per name.

### Extensibility

New state taxonomies are added by:

1. Implementing the `RegimeEngine` protocol with the desired states
2. Registering via `register_engine(name, engine_cls)`
3. Configuring in `PlatformConfig.regime_engine` by name
4. Updating consumer scaling factor maps (risk config, sizer config)

The platform does not require exactly 3 states. Any `n_states >= 2`
is valid. Consumers handle unknown state names by defaulting to `1.0x`.

## Writer/Reader Contract

```
Tick pipeline:
  M0 → M1 (quote logged)
       → M2: orchestrator calls regime_engine.posterior(quote)
              → publishes RegimeState event on bus
       → M3: feature engine calls update(quote)
              → alpha features may read regime_posteriors(symbol)
       → M4: signal engine evaluates
       → M5: risk engine calls current_state(symbol) in check_signal()
              position sizer calls current_state(symbol)
       → M6: risk engine calls current_state(symbol) in check_order()
```

The single-writer guarantee means `current_state()` at M3/M5/M6
always returns the posteriors computed at M2 for the current tick.

## Consumer Contract

### Risk Engine

Reads `current_state(symbol)` in `_regime_scaling()`. Maps the
dominant state name to a position limit multiplier. Unknown states
default to `1.0x`.

### Position Sizer

Reads `current_state(symbol)` in `_get_regime_factor()`. Applies
a regime-dependent capital scaling factor. Missing data defaults
to `1.0x`.

### Alpha Features

Alpha feature namespaces receive:
- `regime_posteriors(symbol) -> list[float] | None` — bound to
  `current_state()`
- `regime_state_names -> Sequence[str]` — the state name tuple

Alpha features must not call `posterior()`. The loader enforces
this structurally by not injecting the engine object.

## RegimeState Event

**File:** `core/events.py`

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

Published by the orchestrator at M2, after `posterior()` returns.
Fire-and-forget observability — current consumers (risk, sizer)
read from the engine directly, not from this event.

Expected future subscribers:
- Dashboards (monitoring skill) — regime state visualization
- Post-trade forensics — regime classification accuracy audit
- Research notebooks — regime transition analysis

## Event Interface

| Event | Direction | Key Fields |
|-------|-----------|------------|
| `NBBOQuote` | In (from ingestion) | Consumed by `posterior()` |
| `RegimeState` | Out (to bus) | Published after each `posterior()` call |

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Engine not configured | `regime_engine is None` | All consumers use `1.0x` (Inv-4) |
| Symbol never updated | `current_state()` returns `None` | Consumers use `1.0x` |
| Empty posteriors list | `len(posteriors) == 0` | Treat as `None` |
| NaN in posteriors | Bayesian update divergence | `reset(symbol)` and re-initialize |
| Engine raises in `posterior()` | Caught by orchestrator at M2 | Tick degrades; cached state preserved |

## Integration Points

| Dependency | Interface | Direction |
|------------|-----------|-----------|
| Orchestrator | `posterior()` at M2 | This skill provides |
| Risk engine | `current_state()` | This skill provides |
| Position sizer | `current_state()` | This skill provides |
| Alpha loader | `current_state`, `state_names` injected | This skill provides |
| Event bus | `RegimeState` published | This skill emits |
| Platform config | `regime_engine: str` selects impl | Consumed by bootstrap |
| Engine registry | `register_engine()`, `get_regime_engine()` | This skill provides |
