---
name: feature-engine
description: >
  Layer-1 sensors and `HorizonFeatureSnapshot` aggregation. Use for sensor DAG, warm/stale, horizon bucketing.
---

# Sensor Layer & Horizon Aggregation

The Layer-1 sensor framework is the only stateful layer in the data
pipeline. Every other layer is either stateless (signal evaluation,
risk checks) or manages a different state domain (orders, positions,
data integrity).

Sensors transform raw L1 NBBO events into typed `SensorReading`
estimates. `HorizonAggregator` then bucket-aggregates those readings
into `HorizonFeatureSnapshot` events on `HorizonTick` boundary
crossings. Layer-2 input is `HorizonFeatureSnapshot` only; D.2 retired `FeatureVector` / `LEGACY_SIGNAL`.

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

The `Sensor` Protocol (`sensors/protocol.py`) defines the per-symbol
incremental computation contract. State is **owned by the registry**
and threaded through `update()` — sensor implementations hold no
mutable per-symbol state themselves:

```python
@runtime_checkable
class Sensor(Protocol):
    sensor_id: str
    sensor_version: str

    def initial_state(self) -> dict[str, Any]: ...
    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None: ...
```

`update()` processes a single L1 event, mutates `state` in place exactly
once, and returns a `SensorReading` event (with `SensorProvenance`) or
`None` if the sensor abstains. The orchestrator dispatches this fan-out
at the `SENSOR_UPDATE` micro-state (between M2 and M3). Warmness is set
directly on the returned `SensorReading.warm` flag — there is **no**
`is_warm()` method (per `sensors/protocol.py` docstring). The
`SensorProvenance` attached to each emission is **pre-baked** by the
registry from the sensor's `SensorSpec`; sensors must attach the
provided instance verbatim and not allocate fresh provenance per call.

A sensor is **stateless-by-instance** — module-level singletons hold
only immutable parameters; per-symbol state lives in the registry-owned
`state` dict and is keyed by `(sensor_id, symbol)`. This keeps memory
bounded and replay deterministic.

### `SensorRegistry` (`sensors/registry.py`)

Sensors are registered declaratively via `SensorSpec`
(`src/feelies/sensors/spec.py`) so the registry can pre-bake
provenance, enforce throttling, and validate dependency topology
before any tick runs.

```python
@dataclass(frozen=True, kw_only=True)
class SensorSpec:
    sensor_id: str
    sensor_version: str
    cls: type[Any]                         # implements the Sensor Protocol
    params: Mapping[str, Any] = ...        # forwarded to cls(**params) + each update()
    subscribes_to: tuple[type[Event], ...] = (NBBOQuote,)
    input_sensor_ids: tuple[str, ...] = () # upstream sensors (cross-sensor deps)
    min_history: int = 0                   # warm-up minimum (consulted via params)
    throttled_ms: int | None = None        # per-(sensor, symbol) min inter-emission ms
    stateful: bool = False                 # accumulator (EWMA/Hawkes/Kyle): bypass-skip throttle
```

Field semantics worth highlighting:

- `subscribes_to` must be a subset of `(NBBOQuote, Trade)` in Phase 2;
  the registry uses it to populate `SensorProvenance.input_event_kinds`.
- `input_sensor_ids` declares upstream sensors whose `SensorReading`
  this sensor consumes. The registry enforces topological registration
  order and rejects cycles. Note: no shipped sensor currently declares
  a cross-sensor edge — the design intent was `structural_break_score`
  over `hawkes_intensity`, but the v0.3 implementation subscribes to
  `NBBOQuote` only (mid-price log-returns) with an empty
  `input_sensor_ids` by design; true cross-sensor wiring is deferred
  (`sensors/impl/structural_break_score.py`).
- `min_history` is the warm-up minimum; sensors consult it via
  `params` — the registry does **not** gate on it, since warmth is a
  sensor-level concern.
- `throttled_ms` is enforced at the registry level. Operators MUST set
  `stateful=True` for any accumulator paired with a non-null
  `throttled_ms`; otherwise skipped events bias the estimator (per H4/M4
  audit). When `stateful=True`, `update()` is called on every event but
  the resulting `SensorReading` is only *emitted* outside the throttle
  window — separating "state advance" from "emission rate-limiting".

Layer gate **G6** enforces sensor-DAG validity at alpha-load time — a
SIGNAL alpha cannot declare a `depends_on_sensors` edge that would
create a cycle or reference an unregistered sensor.

### Implemented Sensors (v0.3, 18 total)

Implementations live under `feelies.sensors.impl`. 18 modules ship
today (one per `sensor_id`); keep this list in sync with
`feelies/sensors/impl/*.py`. Anchored to the trend-mechanism taxonomy
(see microstructure-alpha):

**Registered in the reference `platform.yaml` (15):**

1. `kyle_lambda_60s` — KYLE_INFO fingerprint
2. `inventory_pressure` — INVENTORY fingerprint (trade-side MM-inventory proxy)
3. `quote_replenish_asymmetry` — INVENTORY fingerprint (quote-side)
4. `hawkes_intensity` — HAWKES_SELF_EXCITE fingerprint
5. `liquidity_stress_score` — LIQUIDITY_STRESS fingerprint (spread×depth composite)
6. `quote_flicker_rate` — LIQUIDITY_STRESS fingerprint (best-price reversal fraction)
7. `spread_z_30d` — LIQUIDITY_STRESS (single-axis)
8. `quote_hazard_rate` — LIQUIDITY_STRESS (single-axis)
9. `trade_through_rate` — NBBO-aggression / HAWKES precursor
10. `scheduled_flow_window` — SCHEDULED_FLOW fingerprint
11. `ofi_ewma` — composite
12. `micro_price` — composite
13. `realized_vol_30s` — composite
14. `book_imbalance` — KYLE_INFO fingerprint (level-invariant top-of-book size
    imbalance; algebraically the micro-price-deviation transform — added to
    `_FAMILY_FINGERPRINT_SENSORS["KYLE_INFO"]` by sensor_audit_2026-07-02 P1)
15. `ofi_raw` — KYLE_INFO composite (per-event, unsmoothed OFI; feeds the
    `ofi_integrated` windowed-sum feature — no shipped alpha reads it yet)

**Implemented and tested but dormant in the reference `platform.yaml` (3):**

16. `vpin_50bucket` (flow toxicity)
17. `snr_drift_diffusion`
18. `structural_break_score`

> `inventory_pressure`, `liquidity_stress_score`, and
> `quote_flicker_rate` were specified-but-missing in earlier drafts and
> shipped in the audit P2-3 pass; every G16 family now has a dedicated
> implemented fingerprint. Research use of these sensors carries a
> mirage-risk rank per observable family (quote-flow/cancellation is
> HIGH) — see the microstructure-alpha skill's
> [research-protocol.md](../microstructure-alpha/research-protocol.md),
> "Mirage risk by observable family". Sensor ids that were **never** implemented
> (`kyle_lambda_300s`, `trade_clustering`, `micro_price_drift`,
> `effective_spread`) must not appear in `l1_signature_sensors` /
> `depends_on_sensors`, or G6 resolution fails at load.

Per-sensor implementations set the `warm` flag on each emitted
`SensorReading` (there is no `is_warm()` method on the `Sensor`
protocol — `sensors/protocol.py`) so downstream consumers (the horizon
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
    values: dict[str, float]            # {feature_id: value}; warm only
    warm: dict[str, bool]               # {feature_id: warm}; ALL features
    stale: dict[str, bool]              # {feature_id: stale}; ALL features
    source_sensors: dict[str, tuple[str, ...]]   # {feature_id: input_sensor_ids}
    feature_versions: dict[str, str]    # {feature_id: feature_version}
```

The snapshot is the **canonical Layer-2 input**. Note the actual
contract (`core/events.py`):

- Keys are **`feature_id`**, not `sensor_id`. A passthrough feature
  reuses the `sensor_id` as its `feature_id`; z-score / percentile
  *views are themselves features* exposed under
  `"<sensor_id>_zscore"` / `"<sensor_id>_percentile"` keys inside
  **`values`** — there are **no** separate `z_scores` / `percentiles`
  dicts on the event.
- `warm` and `stale` are **per-feature dicts**, not scalars. `values`
  contains only *warm* features (cold features are absent, not `0.0`),
  while `warm` / `stale` include **every** registered feature so the
  engine can detect active-mode snapshots even when all are cold.
  A SIGNAL alpha must therefore check the specific `feature_id` keys
  it consumes (the `HorizonSignalEngine` does this via each alpha's
  `required_warm_feature_ids`), not truthiness of `snapshot.warm`.

### Snapshot Quality Gates

| Field | Source | Layer-2 contract |
|-------|--------|------------------|
| `warm: dict[str, bool]` | Per `feature_id`: the feature is past its warm-up requirement | The engine suppresses entry when **any required** `feature_id` is `warm=False` |
| `stale: dict[str, bool]` | Per `feature_id`: the feature's input sensor has not fired a *warm* reading within the feature's `horizon_seconds` window (`HorizonAggregator._build_snapshot`) | Entry suppressed when any required feature is stale; exits permitted (conservative) |
| `boundary_index` | `HorizonScheduler` integer math | Used as the deterministic sequence key for parity hashing |

Staleness is enforced by the aggregator's per-`(symbol, sensor_id)`
warm-reading freshness clock, **not** a fixed 5 s wall-clock window:
a feature is stale when `tick.timestamp_ns - last_warm_reading_ns >
horizon_seconds * 1e9`. `spread_z_30d` was historically the cache-only
example, but audit P1-6 wired `SensorPassthroughFeature("spread_z_30d",
h)` in `bootstrap._HORIZON_FEATURE_FACTORIES`, so it now appears in
`HorizonFeatureSnapshot.values` and `required_warm_feature_ids` with
per-feature horizon-window staleness. Sensors that wire **no** Layer-2
feature still reach the gate only via the engine's event-time
`_sensor_cache` (the fallback path) — those are **not** covered by
horizon staleness and are invalidated only when the sensor emits a
*cold* reading.

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

Sensors computed from other sensors declare their upstream edges via
`SensorSpec.input_sensor_ids` (`sensors/spec.py`) and update only
after all upstreams have updated for the current event. The
`SensorRegistry` topological sort enforces this; cycles are rejected
at construction.

## State Lifecycle (per Symbol)

| Phase | Trigger | Behavior |
|-------|---------|----------|
| Init | First event for symbol | Allocate state; cold-start mode |
| Warm-up | Events received but insufficient history | `SensorReading.warm = False` on each emission |
| Active | Warm-up complete | Normal operation; readings flow into the aggregator |
| Stale | No warm reading within the feature's horizon window | `HorizonFeatureSnapshot.stale[feature_id] = True` (per-feature dict, `core/events.py`) |
| Reset | Explicit command or corruption detected | Clear state; re-enter Init |

### Warm-Up

Each sensor declares its minimum warm-up requirement via
`SensorSpec.min_history` (`sensors/spec.py`), consulted by the sensor
through `params`. Layer gate **G8** is the AST no-implicit-lookahead
scan on inline `signal:` code; layer gate **G13** is the warm-up
documentation gate, currently a no-op for the surviving SIGNAL /
PORTFOLIO layers post-D.2 (`alpha/layer_validator.py`) — neither gate
checks warm-up budgets against sensors.

The aggregator sets `warm` / `stale` **per `feature_id`** via each
feature's `finalize()` (`features/aggregator.py`); there is no global
all-sensors-warm flag. `HorizonSignalEngine` suppresses entry when any
of the alpha's `required_warm_feature_ids` is not warm; exits are
permitted (conservative).

### Staleness

Snapshot staleness is **per feature**: a feature is marked stale when
its input sensor has produced no *warm* reading within the feature's
own `horizon_seconds` window — there is no fixed wall-clock default
(no 5 s threshold exists in the aggregator path). Stale features:

- Continue to hold last-known sensor values (no decay to zero)
- Carry `HorizonFeatureSnapshot.stale[feature_id] = True`
- Suppress entry for any alpha consuming them; exits permitted

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

The Paper-RTH `≤ 12 %` end-to-end throughput-regression threshold and
the Phase-4.1 `≤ 5 %` decay-weighting-overhead threshold are **policy
targets** — no shipped test enforces them as regression gates.
What ships today: `tests/perf/test_paper_rth_no_regression.py` asserts
only that the pinned baseline blob exists (host-label gated), and
`tests/acceptance/test_perf_baseline_plumbing.py` smoke-checks the
`tests/perf/_pinned_baseline.py` plumbing. Per-host pinned baselines
live in `tests/perf/baselines/v02_baseline.json` (opt-in via
`PERF_HOST_LABEL`).

## Reproducibility

Same `(sensor_id, sensor_version)` set + same event log → bit-identical
`SensorReading` and `HorizonFeatureSnapshot` streams. Locked by L1/L3
parity tests — full registry in [testing-validation skill](../testing-validation/SKILL.md)
(`test_sensor_reading_replay.py`, `test_v03_sensor_replay.py`,
`test_horizon_feature_snapshot_replay.py`).

### Snapshot Persistence

**Shipped (partial):** `FeatureSnapshotStore` /
`InMemoryFeatureSnapshotStore` persist feature/regime snapshots used by
the orchestrator (e.g. regime checkpoint restore). This is **not** a
per-sensor warm-start protocol.

**Not shipped:** sensor-keyed warm-start checkpoint store keyed by
`(symbol, sensor_id, sensor_version)`. Sensors still cold-start from the
event stream; the planned design falls back to cold start on version
mismatch — never silently degrade to a different version's state.

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

See [skill index](../README.md). **Non-obvious edges:** feeds `HorizonFeatureSnapshot` to Layer-2; micro-state chain M2 → SENSOR_UPDATE → HORIZON_AGGREGATE.