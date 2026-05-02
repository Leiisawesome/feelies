---
name: feature-engine
description: >
  Layer-1 sensor framework + horizon-aggregation contract for the feelies
  platform. Owns per-symbol sensor state, the `SensorRegistry`, the
  `HorizonScheduler` / `HorizonAggregator` pipeline, and the
  `HorizonFeatureSnapshot` event consumed by Layer-2 alphas. Use when
  designing or extending Layer-1 sensors, debugging warm-up / staleness,
  reasoning about sensor-DAG topology, horizon bucketing, snapshot
  emission, or the boundary between Layer-1 (event-time) and Layer-2
  (horizon-anchored) computation.
---

# Sensor Layer & Horizon Aggregation

The Layer-1 sensor framework is the only stateful layer in the data
pipeline. Every other layer is either stateless (signal evaluation,
risk checks) or manages a different state domain (orders, positions,
data integrity).

Sensors transform raw L1 NBBO events into typed `SensorReading`
estimates. `HorizonAggregator` then bucket-aggregates those readings
into `HorizonFeatureSnapshot` events on `HorizonTick` boundary
crossings. This is the **only** Layer-2 input contract — the historical
per-tick `FeatureVector` path was retired in Workstream D.2 (D.2
PR-2b-iv deleted `FeatureVector`, `FeatureEngine.update`,
`SignalEngine.evaluate`, `CompositeFeatureEngine`, `CompositeSignalEngine`,
and `AlphaModule.evaluate`).

## Core Invariants

Inherits Inv-5 (deterministic replay), Inv-6 (causality enforced),
Inv-13 (versioned provenance). Additionally:

1. **Incremental by default** — sensors update incrementally on each
   event; full recomputation only at cold start or recovery.
2. **Per-symbol isolation** — sensor state is per-symbol; no
   cross-symbol leakage inside the sensor layer.
3. **Bounded** — per-sensor memory footprint is bounded and
   configurable; no unbounded accumulation.
4. **Horizon anchoring** — `HorizonFeatureSnapshot` emission is
   anchored to integer-math boundary crossings against
   `session_open_ns`; no wall-clock drift.

## Sensor Protocol (Layer 1)

The `SensorProtocol` (`sensors/protocol.py`) defines the per-symbol
incremental computation contract:

```python
class SensorProtocol(Protocol):
    @property
    def sensor_id(self) -> str: ...
    @property
    def sensor_version(self) -> str: ...
    def update(self, event: NBBOQuote | Trade) -> SensorReading | None: ...
    def is_warm(self, symbol: str) -> bool: ...
    def reset(self, symbol: str) -> None: ...
```

`update()` processes a single L1 event and returns a `SensorReading`
event (with `SensorProvenance`) or `None` if the sensor abstains. The
orchestrator dispatches this fan-out at the `SENSOR_UPDATE` micro-state
(between M2 and M3).

A sensor is **stateless-by-instance** — multiple symbols share the
class but per-symbol state is keyed inside the implementation. This
keeps memory bounded and replay deterministic.

### `SensorRegistry` (`sensors/registry.py`)

Sensors are registered declaratively via `SensorSpec` so the registry
can pre-bake provenance, enforce throttling, and validate dependency
topology before any tick runs.

```python
@dataclass(frozen=True, kw_only=True)
class SensorSpec:
    sensor_id: str
    sensor_version: str
    factory: Callable[..., SensorProtocol]
    depends_on: tuple[str, ...]      # upstream sensor_ids
    warm_up: WarmUpSpec
    throttle_ns: int = 0             # per-symbol min inter-emission interval
```

The registry resolves the dependency DAG, computes a topological order,
and rejects cycles. Layer gate **G6** enforces sensor-DAG validity at
alpha-load time — a SIGNAL alpha cannot declare a `depends_on_sensors`
edge that would create a cycle or reference an unregistered sensor.

### Implemented Sensors (v0.3, 13 total)

Implementations live under `feelies.sensors.impl`. The v0.3 catalog
is anchored to the trend-mechanism taxonomy (see
microstructure-alpha):

- `kyle_lambda_60s`, `kyle_lambda_300s` — KYLE_INFO fingerprint
- `inventory_pressure`, `quote_replenishment_asym` — INVENTORY fingerprint
- `hawkes_intensity`, `trade_clustering` — HAWKES_SELF_EXCITE fingerprint
- `liquidity_stress_score`, `spread_z_30d`, `quote_flicker_rate` — LIQUIDITY_STRESS fingerprint
- `scheduled_flow_window` — SCHEDULED_FLOW fingerprint
- `ofi_ewma`, `micro_price_drift`, `effective_spread` — composite

Per-sensor implementations expose `is_warm(symbol)` and emit
`SensorReading.provenance.warm` so downstream consumers (the horizon
aggregator) can track readiness on a per-(symbol, sensor) basis.

## Horizon Pipeline (Layer 1.5)

The bridge between event-time sensors and horizon-anchored Layer-2
alphas.

### `HorizonScheduler` (`sensors/horizon_scheduler.py`)

A pure-integer-math scheduler that detects horizon boundary crossings
against `session_open_ns`. For each configured horizon (canonical
Phase-2 set: `{30, 120, 300, 900, 1800}` seconds), it emits a
`HorizonTick(horizon_seconds, boundary_index, boundary_ts_ns)` event
when the current event timestamp crosses an integer multiple of the
horizon since session open.

Bit-identical replay across runs is contractual: the scheduler has no
clock dependency beyond the event timestamp it receives.

### `HorizonAggregator` (`features/aggregator.py`)

On each `HorizonTick`, fans in the most recent `SensorReading` per
(symbol, sensor_id) within the horizon window and emits a
`HorizonFeatureSnapshot`:

```python
@dataclass(frozen=True, kw_only=True)
class HorizonFeatureSnapshot(Event):
    symbol: str
    horizon_seconds: int
    boundary_index: int
    values: dict[str, float]          # {sensor_id: value}
    z_scores: dict[str, float]        # {sensor_id: z_score}
    percentiles: dict[str, float]     # {sensor_id: percentile}
    warm: bool
    stale: bool
```

The snapshot is the **canonical Layer-2 input**. It carries warm/stale
quality gates per sensor and z-score / percentile views (used by
`RegimeGate` DSL bindings — see microstructure-alpha skill).

### Snapshot Quality Gates

| Field | Source | Layer-2 contract |
|-------|--------|------------------|
| `warm: bool` | All consumed sensors past their `warm_up` requirement | SIGNAL alphas suppress entry signals when `warm == False` |
| `stale: bool` | No NBBO arrival for the symbol within the staleness threshold (default 5s) | Entry signals suppressed; exits permitted (conservative) |
| `boundary_index` | `HorizonScheduler` integer math | Used as the deterministic sequence key for parity hashing |

## Computation Patterns

### Rolling Windows

| Pattern | Implementation | Memory |
|---------|---------------|--------|
| Time-windowed (e.g., 5s VWAP) | Ring buffer keyed by timestamp; evict expired | O(window) |
| Count-windowed (last N trades) | Circular buffer; overwrite oldest | O(N) |
| Exponentially weighted (EWMA vol) | Single accumulator; no buffer | O(1) |
| Decaying sum (OFI EWMA) | Accumulator with decay factor per tick | O(1) |

### Cross-Event Sensors

Sensors that combine information from quotes and trades (e.g.,
`hawkes_intensity` consuming aggressor side from `Trade` and quote
update rate from `NBBOQuote`) subscribe to multiple event types but
maintain a single coherent state per symbol. Within-tick ordering
follows the data-engineering skill's micro-batch rules: quotes
processed before trades within the same exchange timestamp.

### Derived Sensors

Sensors computed from other sensors declare their `depends_on:` edges
and update only after all upstreams have updated for the current
event. The `SensorRegistry` topological sort enforces this; cycles
are rejected at construction.

## State Lifecycle (per Symbol)

| Phase | Trigger | Behavior |
|-------|---------|----------|
| Init | First event for symbol | Allocate state; cold-start mode |
| Warm-up | Events received but insufficient history | `is_warm == False`; `SensorReading.provenance.warm = False` |
| Active | Warm-up complete | Normal operation; readings flow into the aggregator |
| Stale | No event received for > staleness threshold | `HorizonFeatureSnapshot.stale = True` |
| Reset | Explicit command or corruption detected | Clear state; re-enter Init |

### Warm-Up

Each sensor declares its minimum warm-up requirement via
`WarmUpSpec(min_events: int, min_duration_ns: int)`. Layer gate **G8**
enforces that every alpha's `depends_on_sensors` declares a warm-up
budget consistent with its sensors.

The aggregator emits `warm=True` only when **every** consumed sensor
reports warm. SIGNAL alphas must not act on `warm=False` snapshots
for entry; exits are permitted (conservative).

### Staleness

If no NBBO event arrives for a symbol within a configurable threshold
(default 5 s during market hours), the snapshot is marked stale. Stale
snapshots:

- Continue to hold last-known sensor values (no decay to zero)
- Carry `HorizonFeatureSnapshot.stale = True`
- Trigger an `Alert` if sustained beyond a second threshold

## Snapshot/Sensor Versioning

| Change type | Version bump | Action |
|-------------|--------------|--------|
| Bug fix (same semantics) | Patch | Recompute affected backtests |
| Parameter change | Minor | New `sensor_id` recommended; old version retained |
| Semantic change | Major | New `sensor_id` required; old version deprecated |
| New sensor added | N/A | Additive; no version bump on existing sensors |

`SensorReading.sensor_version` is captured on every emission. Backtest
parity hashes are only valid for the `(sensor_id, sensor_version)`
tuples they were computed with.

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| NaN / Inf in sensor value | Post-update value check | Suppress emission; emit `Alert`; flag `provenance.valid = False` |
| State corruption | Per-update invariant check | `reset(symbol)`; re-warm from recent events |
| Memory budget exceeded | Per-symbol allocation tracking | Evict oldest ring-buffer entries; alert if persistent |
| Dependency cycle | Registry construction | Fail bootstrap (`SensorRegistry` raises) |
| Clock-derived staleness flagged but quote arriving | Race between staleness sweep and event ingestion | Accept the new event; clear stale flag on next snapshot |

## Performance Constraints

Sensor + aggregator wall time is on the per-tick critical path. Budget
from the performance-engineering skill (per tick, all sensors, one
symbol):

| Operation | Budget | Hard ceiling |
|-----------|--------|--------------|
| Single sensor `update()` | 50 μs | 200 μs |
| Full sensor fan-out at SENSOR_UPDATE | 500 μs | 2 ms |
| `HorizonAggregator` snapshot emission | 200 μs | 1 ms |
| Per-symbol memory footprint | < 1 MB | configurable |

The Phase-4 perf gate is `≤ 12 %` end-to-end throughput regression vs
the v0.2 baseline; the Phase-4.1 gate is `≤ 5 %` decay-weighting
overhead. Per-host pinned baselines live in
`tests/perf/baselines/v02_baseline.json` (opt-in via `PERF_HOST_LABEL`).

## Reproducibility

Same `(sensor_id, sensor_version)` set + same event log → bit-identical
`SensorReading` and `HorizonFeatureSnapshot` streams. Locked by the
Level-1 sensor parity test (`tests/determinism/test_sensor_replay.py`).

### Snapshot Persistence

This skill owns the optional `SensorStateStore` checkpoint protocol for
warm-start. Snapshots are keyed by `(symbol, sensor_id,
sensor_version)`. Version mismatch on restore falls back to cold start
— never silently degrade to a different version's state.

## Cross-Sectional Aggregation

The sensor layer is **strictly per-symbol**. Cross-sectional
aggregation (sector-relative spread, market-wide vol rank) belongs to
Layer 3 (`composition` package). The aggregator never compares across
symbols; per-symbol horizon snapshots are the unit of cross-symbol
fan-in for `UniverseSynchronizer` in the composition layer.

## Event Interface

| Event | Direction | Notes |
|-------|-----------|-------|
| `NBBOQuote` | Inbound | Consumed by `update()` |
| `Trade` | Inbound | Consumed by trade-driven sensors |
| `SensorReading` | Outbound | Per-event emission with provenance |
| `HorizonTick` | Internal | Scheduler → aggregator |
| `HorizonFeatureSnapshot` | Outbound | Layer-1.5 → Layer-2 contract |

All carry timestamps from the injectable `Clock` (Inv-10).

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Data Engineering | `NBBOQuote` / `Trade` events from `MarketDataSource` |
| System Architect | `Clock`, `EventBus`, micro-state pipeline (M2 → SENSOR_UPDATE → HORIZON_AGGREGATE) |
| Microstructure Alpha | Defines what sensors to compute; consumes `HorizonFeatureSnapshot` |
| Composition Layer | Per-symbol snapshots feed `UniverseSynchronizer` for cross-sectional context |
| Backtest Engine | Replays events through the sensor + aggregator pipeline |
| Performance Engineering | Per-tick sensor compute budget |
| Testing & Validation | Sensor parity hash + warm-up + staleness property tests |

The sensor layer is the deterministic, incremental, bounded,
version-controlled foundation on which every alpha depends.
