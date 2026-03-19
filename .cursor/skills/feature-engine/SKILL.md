---
name: feature-engine
description: >
  Incremental feature computation engine for stateful, per-symbol feature
  extraction from L1 NBBO event streams. Defines computation patterns, state
  lifecycle, versioning, feature–signal contracts, and reproducibility
  guarantees. Use when designing feature pipelines, implementing incremental
  updates, managing per-symbol state, defining feature schemas, versioning
  feature definitions, or reasoning about feature reproducibility, staleness
  detection, or the boundary between features and signals.
---

# Feature Engine — Stateful Computation Layer

The feature engine transforms raw L1 NBBO events into stateful, per-symbol
feature vectors consumed by the signal layer. It sits between data ingestion
and signal generation — receiving canonical events from the event bus and
emitting typed feature snapshots.

The feature engine is the only layer that maintains mutable per-symbol state
across ticks. Every other layer is either stateless (signal engine) or
manages different state domains (risk engine: portfolio state; execution
engine: order state).

## Core Invariants

Inherits platform invariants 5 (deterministic replay), 6 (causality), 13 (versioned provenance).
Additionally:

1. **Incremental by default** — features update incrementally on each event; full recomputation only on state reset or recovery
2. **Isolated per symbol** — per-symbol feature state is independent; no cross-symbol leakage within the feature engine
3. **Bounded** — per-symbol memory footprint is bounded and configurable; no unbounded accumulation

---

## Computation Patterns

### Incremental Update

Every feature engine must implement the `FeatureEngine` protocol
(`features/engine.py`):

```python
class FeatureEngine(Protocol):
    def update(self, quote: NBBOQuote) -> FeatureVector: ...
    def process_trade(self, trade: Trade) -> FeatureVector | None: ...
    def is_warm(self, symbol: str) -> bool: ...
    def reset(self, symbol: str) -> None: ...
    @property
    def version(self) -> str: ...
    def checkpoint(self, symbol: str) -> tuple[bytes, int]: ...
    def restore(self, symbol: str, state: bytes) -> None: ...
```

`update()` processes a single `NBBOQuote` event and returns the updated
`FeatureVector` — advancing internal state exactly once per event.
The orchestrator calls this at micro-state M3 (FEATURE_COMPUTE) and
publishes the result on the bus.

`process_trade()` updates feature state from a `Trade` event (e.g.,
volume clustering, trade arrival rate). Returns a `FeatureVector` if
any feature consumed the trade, `None` otherwise. Trade-triggered
updates modify state but do not drive signal evaluation — the updated
values feed into the next quote-driven `FeatureVector`. Called by
`_process_trade()` in the orchestrator outside the micro-state pipeline.

Full recomputation from raw events is used only for:
- Cold start (no prior state)
- Recovery from corruption
- Validation (compare incremental vs full-recompute output)

### Rolling Window Features

Fixed-size windows over time or event counts. Implemented via ring buffers
to guarantee O(1) update and bounded memory.

| Pattern | Implementation | Memory |
|---------|---------------|--------|
| Time-windowed (e.g., 5s VWAP) | Ring buffer keyed by timestamp; evict expired | O(window_size) |
| Count-windowed (e.g., last 100 trades) | Circular buffer; overwrite oldest | O(N) fixed |
| Exponentially weighted (e.g., EWMA vol) | Single accumulator; no buffer needed | O(1) |
| Decaying sum (e.g., order flow imbalance) | Accumulator with decay factor per tick | O(1) |

### Cross-Event Features

Features that combine information from quotes and trades (e.g., trade
arrival rate relative to quote update rate). These subscribe to multiple
event types but maintain a single coherent state per symbol.

Ordering within a tick follows the backtest engine's micro-batch rules:
quotes processed before trades within the same timestamp.

### Derived Features

Features computed from other features (e.g., z-score of spread relative
to rolling mean spread). Derived features declare their dependencies
explicitly and update only after all upstream features have updated for the
current event.

```
DerivedFeature:
  depends_on: list[FeatureId]
  compute(upstream_values: dict[FeatureId, value]) -> value
```

Circular dependencies are forbidden and detected at registration time.

---

## State Lifecycle

### Per-Symbol State

Each symbol maintains an independent feature state container:

| Phase | Trigger | Behavior |
|-------|---------|----------|
| Init | First event for symbol or explicit start | Allocate state; all features in cold-start mode |
| Warm-up | Events received but insufficient history | Features emit values marked `warming_up=True`; signal engine may ignore |
| Active | Warm-up period complete | Normal operation; all features valid |
| Stale | No event received for > staleness threshold | Features marked stale; signal engine suppresses |
| Reset | Explicit command or corruption detected | Clear all state; re-enter Init |
| Shutdown | End of session or symbol removal | Persist state snapshot if configured; deallocate |

### Warm-Up Protocol

Each feature declares its minimum warm-up requirement:

| Feature Type | Warm-Up Requirement |
|-------------|---------------------|
| EWMA (span N) | N events (or configurable multiplier) |
| Rolling window (W seconds) | W seconds of data received |
| Count-based window (N events) | N events |
| Point-in-time (e.g., current spread) | 1 event |

The feature engine tracks warm-up status per feature per symbol. A
`FEATURES_READY` event is emitted when all features for a symbol exit
warm-up. The signal engine must not act on features that are still warming.

### Staleness Detection

If no event arrives for a symbol within a configurable threshold (default:
5 seconds during market hours), the feature state for that symbol is marked
stale. Stale features:
- Continue to hold their last value (no decay to zero)
- Are flagged in the feature snapshot (`stale=True`)
- Trigger an alert if sustained beyond a second threshold

The signal engine must not generate entry signals from stale features.
Exit signals from stale features are allowed (conservative: exit is safer
than hold when data is missing).

---

## Feature–Signal Contract

The boundary between feature engine and signal engine is a strict typed
contract. Features produce; signals consume. No negotiation.

### Feature Snapshot Schema

The `FeatureVector` event (`core/events.py`) is the output type:

```python
@dataclass(frozen=True, kw_only=True)
class FeatureVector(Event):
    symbol: str
    feature_version: str
    values: dict[str, float]
    warm: bool = True
    stale: bool = False
    event_count: int = 0
```

It inherits `timestamp_ns`, `correlation_id`, and `sequence` from `Event`.
Feature vectors are frozen dataclasses — immutable after creation, safe to
share without copying.

### Contract Rules

1. The signal engine receives `FeatureVector` objects — never raw events
2. Feature IDs are stable across versions; renamed features get new IDs
3. Adding a feature is non-breaking; removing or changing semantics requires a version bump
4. The signal engine must not modify feature state or call feature internals
5. Feature snapshots are immutable after emission — safe to share without copying

---

## Feature Registry

All features are registered in a central registry that enforces uniqueness,
tracks versions, and resolves dependencies.

### Registration

```
FeatureRegistry:
  register(feature: FeatureDefinition) -> None
  resolve_dependencies() -> DependencyGraph
  validate() -> list[ValidationError]
  get_computation_order() -> list[FeatureId]  # topological sort
```

### Feature Definition

```
FeatureDefinition:
  id: FeatureId (unique, stable)
  version: str (semantic version)
  description: str
  event_types: list[EventType] (subscribed events)
  depends_on: list[FeatureId] (upstream features, if derived)
  warm_up: WarmUpSpec
  memory_budget: int (bytes, per symbol)
  compute: Callable (the update function)
```

### Versioning Rules

| Change Type | Version Bump | Action |
|-------------|-------------|--------|
| Bug fix (same semantics) | Patch | Recompute affected backtests |
| Parameter change (e.g., window length) | Minor | New feature ID recommended; old version retained |
| Semantic change (different meaning) | Major | New feature ID required; old version deprecated |
| New feature added | N/A | Additive; no version bump to existing features |

Feature version is embedded in every feature snapshot and in backtest
reproducibility logs. A backtest result is only valid for the feature
versions it was computed with.

---

## Cross-Sectional Features

While per-symbol state is isolated within the feature engine, some signals
require cross-sectional context (e.g., sector-relative spread, market-wide
volatility rank). These are handled at the boundary:

| Approach | When |
|----------|------|
| Market-level features | Computed as a special "symbol" (e.g., `_MARKET`, `_SPY`) with its own state |
| Cross-sectional aggregation | Performed in the signal engine, not the feature engine |
| Sector/index features | Computed per-index symbol; consumed by signal engine alongside per-stock features |

The feature engine never compares across symbols internally. Cross-sectional
logic belongs to the signal engine, which receives snapshots from multiple
symbols and can reason across them.

---

## Reproducibility

### Replay Guarantee

Given the same event sequence and feature definitions (version-pinned),
the feature engine must produce bit-identical feature snapshots. This is
tested via the replay reproducibility tests in the testing-validation skill.

### Snapshot Persistence

This skill owns the `FeatureSnapshotStore` protocol and `FeatureSnapshotMeta`
dataclass (`storage/feature_snapshot.py`) for checkpoint persistence:

- `checkpoint(symbol) -> (bytes, event_count)` serializes engine state
- `restore(symbol, state: bytes)` deserializes and validates
- `FeatureSnapshotMeta` carries `symbol`, `feature_version`, `event_count`,
  `last_sequence`, `last_timestamp_ns`, `checksum` (SHA-256 of state blob)

The orchestrator manages the warm-start lifecycle:
- `_restore_feature_snapshots()` at boot: loads snapshots per symbol,
  falls back to cold-start on version mismatch or corruption
- `_checkpoint_feature_snapshots()` at shutdown: persists state for all
  configured symbols (best-effort, does not block shutdown)

Snapshots are keyed by `(symbol, feature_version)` and stored in the
storage layer.

### Validation: Incremental vs Full Recompute

Periodically (configurable, default: daily), run a full recompute from
raw events for a sample of symbols and compare against the incremental
output. Any divergence is a bug — the incremental path must exactly match
the full-recompute path.

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| NaN / Inf in feature value | Post-update value check | Suppress feature; emit with `valid=False`; alert |
| State corruption (inconsistent internals) | Invariant checks after update | Reset symbol state; re-warm from recent events |
| Memory budget exceeded | Per-symbol allocation tracking | Evict oldest rolling window entries; alert if persistent |
| Dependency cycle detected | Registry validation at startup | Fail startup; do not proceed with circular dependencies |
| Feature computation exceeds latency budget | Scoped timer per update | Log; alert if sustained; profile for optimization |
| Event ordering violation | Timestamp monotonicity check | Log; use last-known ordering; alert for investigation |

---

## Multi-Alpha Composition

In multi-strategy deployments, the `CompositeFeatureEngine`
(`alpha/composite.py`) aggregates feature definitions from all
registered alpha modules (`AlphaRegistry`). It implements the
`FeatureEngine` protocol so the orchestrator is unaware of the
multi-alpha structure.

- Features are computed in topological dependency order (stable
  tie-breaking by `feature_id` for determinism)
- Per-symbol state is maintained per feature definition
- The composite `version` is a SHA-256 hash of all constituent
  feature versions
- `checkpoint()` / `restore()` serialize/deserialize the full
  multi-alpha state

Individual alpha modules declare their feature definitions via
`AlphaModule.feature_definitions` and are loaded from `.alpha.yaml`
specs by the `AlphaLoader`. See the system-architect skill for the
full alpha module system.

---

## Performance Constraints

Feature computation is on the critical path (tick-to-trade pipeline).
Budget from the performance-engineering skill:

| Operation | Budget | Hard Ceiling |
|-----------|--------|-------------|
| Per-tick incremental update (all features, 1 symbol) | 1 ms | 5 ms |
| Feature snapshot emission | 50 μs | 200 μs |
| Per-symbol memory footprint | < 1 MB | Configurable |

Optimization hierarchy: incremental updates > vectorized batch >
pre-allocated buffers. Never sacrifice determinism or correctness for speed.

---

## Event Interface

| Event | Direction | Type (`core/events.py`) |
|-------|-----------|---------|
| Quote update | Inbound | `NBBOQuote` — symbol, bid, ask, bid_size, ask_size, exchange_timestamp_ns |
| Trade print | Inbound | `Trade` — symbol, price, size, exchange_timestamp_ns |
| Feature output | Outbound | `FeatureVector` — symbol, feature_version, values, warm, stale, event_count |

The following signals are NOT YET IMPLEMENTED as typed events but should
extend `Event` when built:

| Future Event | Purpose |
|-------|---------|
| `FEATURES_READY` | All features for a symbol past warm-up |
| `FEATURE_STALE` | No event for symbol beyond staleness threshold |
| `FEATURE_ERROR` | NaN/Inf or state corruption detected |

All events carry timestamps from the injectable `Clock` protocol.

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Data Engineering (data-engineering skill) | `NBBOQuote` / `Trade` events from `MarketDataSource` |
| System Architect (system-architect skill) | `Clock`, `EventBus`, micro-state M3 (FEATURE_COMPUTE) |
| Microstructure Alpha (microstructure-alpha skill) | Signal taxonomy defines what features to compute |
| Signal Engine | Consumes `FeatureVector`; calls `SignalEngine.evaluate(features)` at M4 |
| Backtest Engine (backtest-engine skill) | Replays events through feature engine; snapshot comparison for determinism |
| Storage Layer | `FeatureSnapshotStore` for checkpoint persistence |
| Performance Engineering (performance-engineering skill) | M3 feature compute latency budget (1ms target, 5ms ceiling) |
| Testing & Validation (testing-validation skill) | Incremental vs full-recompute validation; property-based invariant tests |

The feature engine is the stateful core of the data pipeline. It is
deterministic, incremental, bounded, and version-controlled — the foundation
on which signal quality depends.
