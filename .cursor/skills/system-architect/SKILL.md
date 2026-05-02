---
name: system-architect
description: >
  Foundational architecture for the feelies intraday platform: three alpha
  layers (SENSOR / SIGNAL / PORTFOLIO) anchored to horizon-bucketed snapshots,
  five state machines, single-`ExecutionBackend` mode swap, and end-to-end
  determinism. Use when designing components, defining layer boundaries,
  reasoning about cross-layer interactions, micro-state ordering, replay
  determinism, or fail-safe enforcement on L1 NBBO data from Massive
  (formerly Polygon.io).
---

# System Architect — Platform Foundation

The feelies platform is a deterministic, event-driven, three-layer alpha
stack on L1 NBBO data. Research backtests and live trading share the
same core; mode-specific code lives only behind `ExecutionBackend`.
Every architectural decision is gated by the 13 invariants in
`.cursor/rules/platform-invariants.mdc`.

This skill owns the system-wide contract: layer topology, state
machines, the `ExecutionBackend` abstraction, the typed event catalog,
the kernel/orchestrator, and the observability layer. Layer-internal
contracts are owned by their respective skills.

## Three Alpha Layers

Every alpha targets exactly one of these layers; cross-layer leakage is
a load-time failure (gate G1).

| Layer | Package | Horizon | Output Event | Owner skill |
|-------|---------|---------|--------------|-------------|
| **SENSOR** (Layer 1) | `feelies.sensors` | event-time (≤ 1 s) | `SensorReading` | feature-engine |
| **SIGNAL** (Layer 2) | `feelies.signals` | 30 s – 30 min | `Signal` | microstructure-alpha |
| **PORTFOLIO** (Layer 3) | `feelies.composition` | 5 – 30 min | `SizedPositionIntent` | composition-layer |

`LEGACY_SIGNAL` was a fourth (per-tick) layer retired in Workstream D.2;
the loader rejects `layer: LEGACY_SIGNAL` outright. The legacy
per-tick `FeatureVector` event, `FeatureEngine.update`, `SignalEngine.evaluate`,
`CompositeFeatureEngine`, `CompositeSignalEngine`, and
`AlphaModule.evaluate` were all deleted in D.2 PR-2b-iv — any
documentation or skill referring to them is stale.

The canonical Layer-2 input is **`HorizonFeatureSnapshot`** (emitted by
`HorizonAggregator` on `HorizonTick` boundary crossings). The canonical
Layer-2 output is **`Signal`** (emitted by `HorizonSignalEngine` after
the alpha's `regime_gate` resolves to ON). The canonical Layer-3 output
is **`SizedPositionIntent`** (emitted by `CompositionEngine` per
`CrossSectionalContext`).

## Kernel & Orchestrator

The kernel layer (`feelies.kernel.orchestrator.Orchestrator`) coordinates
all five state machines and drives the per-tick micro-state pipeline.
It contains **no business logic** — only state management, bus
dispatch, and fail-safe enforcement.

### Five State Machines

Each uses the generic `StateMachine[S]` framework
(`core/state_machine.py`) with a frozen transition table validated for
enum completeness at construction. Every transition emits a typed
`StateTransition` event on the bus via `TransitionRecord` callbacks —
no silent transitions (Inv-13).

| Machine | Enum | File | States | Scope |
|---------|------|------|--------|-------|
| Macro lifecycle | `MacroState` | `kernel/macro.py` | INIT → DATA_SYNC → READY → {RESEARCH, BACKTEST, PAPER_TRADING, LIVE_TRADING}_MODE → DEGRADED → RISK_LOCKDOWN → SHUTDOWN | System-wide |
| Micro pipeline | `MicroState` | `kernel/micro.py` | M0 ‥ M10 backbone + Phase-2/3/4 sub-states (see below) | Per-tick |
| Order lifecycle | `OrderState` | `execution/order_state.py` | CREATED → SUBMITTED → ACKNOWLEDGED → {PARTIALLY_FILLED, FILLED, CANCEL_REQUESTED, REJECTED, EXPIRED, CANCELLED} | Per-order |
| Risk escalation | `RiskLevel` | `risk/escalation.py` | NORMAL → WARNING → BREACH_DETECTED → FORCED_FLATTEN → LOCKED | Monotonic safety |
| Data integrity | `DataHealth` | `ingestion/data_integrity.py` | HEALTHY → GAP_DETECTED → CORRUPTED → RECOVERING | Per-symbol stream |

Illegal transitions raise `IllegalTransition`. Construction-time enum
completeness check guarantees every enum member has a transition entry
— a contributor adding a new state without wiring it triggers a hard
failure at `StateMachine.__init__`.

### Micro-State Pipeline (Per Tick)

The `MicroState` enum (`kernel/micro.py`) defines the M0 → M10
backbone with Phase-2/3/4 sub-states inserted between M2 and M3.
The orchestrator's `_process_tick_inner()` is the **single code path**
across all trading modes — it never inspects `backend.mode`.

```
M0  WAITING_FOR_MARKET_EVENT
M1  MARKET_EVENT_RECEIVED          (event log append + bus publish)
M2  STATE_UPDATE                   (RegimeEngine.posterior → RegimeState)
    SENSOR_UPDATE                  (Layer-1 fan-out via SensorRegistry)
    HORIZON_CHECK                  (HorizonScheduler boundary check)
    HORIZON_AGGREGATE              (HorizonAggregator → HorizonFeatureSnapshot)
    SIGNAL_GATE                    (HorizonSignalEngine → Signal)
    CROSS_SECTIONAL                (UniverseSynchronizer → CrossSectionalContext;
                                    CompositionEngine → SizedPositionIntent)
M3  FEATURE_COMPUTE                (body now empty — legacy hook preserved
                                    so the SM stays on its legal path)
M4  SIGNAL_EVALUATE                (drain bus-buffered Signal → OrderRequest)
    ORDER_AGGREGATION              (multi-leg intent fan-out)
M5  RISK_CHECK                     (RiskEngine.check_signal | check_sized_intent)
M6  ORDER_DECISION                 (build OrderRequest from intent + verdict)
M7  ORDER_SUBMIT                   (OrderRouter.submit)
M8  ORDER_ACK                      (OrderRouter.poll_acks → OrderAck)
M9  POSITION_UPDATE                (_reconcile_fills → PositionUpdate)
M10 LOG_AND_METRICS                (tick_to_decision_latency_ns, cleanup)
```

Sub-states between M2 and M3 are the Phase-2/3/4 wiring; the M0–M10
backbone is preserved so the SM transition table remains stable. The
SIGNAL → Order path runs through M4; the PORTFOLIO `SizedPositionIntent`
path is dispatched on the bus at `CROSS_SECTIONAL` and consumed by
`RiskEngine.check_sized_intent` at M5 (with per-leg veto semantics).
M3's body is empty for Phase-3 alphas — kept as a structural hook so
the legal-path walk stays bit-identical (Inv-5).

### `ExecutionBackend` (Inv-9)

The single mode-specific abstraction (`execution/backend.py`):

- `MarketDataSource` — historical replay (backtest) or live feed
- `OrderRouter` — simulated fills (backtest) or broker API (live)

The orchestrator never inspects `backend.mode`. Composition happens at
startup via `bootstrap.build_platform(config)`:

| Mode | `MarketDataSource` | `OrderRouter` | `Clock` |
|------|-------------------|---------------|---------|
| `BACKTEST_MODE` (`execution_mode: market`) | `ReplayFeed(EventLog)` | `BacktestOrderRouter` (mid-price fills) | `SimulatedClock` |
| `BACKTEST_MODE` (`execution_mode: passive_limit`) | `ReplayFeed(EventLog)` | `PassiveLimitOrderRouter` (queue-position fills) | `SimulatedClock` |
| `PAPER_TRADING_MODE` | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |
| `LIVE_TRADING_MODE` | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |

`MassiveHistoricalIngestor` is a batch ETL that populates `EventLog`
outside the orchestrator lifecycle — it is not an operating mode (see
the data-engineering skill).

### Fail-Safe Cascade (Inv-11)

When any tick-processing step throws:

1. Micro SM resets to M0 via `_handle_tick_failure()`
2. Macro transitions to DEGRADED
3. The original exception type is captured in the trigger for provenance

When risk escalation fires (`_escalate_risk`):

1. Risk SM walks R0 → R1 → R2 → R3 → R4 (monotonic, forward-only)
2. `KillSwitch.activate()` — irreversible without human authorization
3. Macro transitions to RISK_LOCKDOWN
4. Recovery requires `Orchestrator.unlock_from_lockdown(audit_token)` with
   a zero-exposure guard (`PositionStore.total_exposure() == Decimal("0")`)

Intermediate stranding (callback exception during escalation) is
recovered via `reset_risk_escalation(audit_token)` from {WARNING,
BREACH_DETECTED, FORCED_FLATTEN}; LOCKED is exit-only via
`unlock_from_lockdown`.

### Exhaustiveness Guards

Every enum-driven decision point has an explicit guard that raises
`ValueError` for unhandled members. New enum additions cannot silently
fall through to unsafe paths. Applied at:

- `RiskAction` gate at M5 and M6
- `TradingIntent` in `_side_from_intent`
- `OrderAckStatus` in `_apply_ack_to_order`
- `SignalDirection` in the SIGNAL → Order translation
- `TrendMechanism` in attribution and capacity-cap enforcement

## Typed Event Catalog

All inter-layer communication is via frozen dataclasses from
`core/events.py`. Every event inherits from `Event` carrying
`timestamp_ns` (clock-derived), `correlation_id`, and `sequence` for
end-to-end provenance.

| Event | Boundary | Key fields |
|-------|----------|-----------|
| `NBBOQuote` | Ingestion → Layer 1 | symbol, bid/ask, sizes |
| `Trade` | Ingestion → Layer 1 / storage | symbol, price, size, conditions |
| `RegimeState` | Service → Layer 2 / risk | engine_name, posteriors, dominant_state |
| `RegimeHazardSpike` | Service → Risk / portfolio | engine_name, departing_state, posterior_drop |
| `SensorReading` | Layer 1 → Layer 2 | sensor_id, value, provenance |
| `HorizonTick` | Scheduler → aggregator | horizon_seconds, boundary_index, boundary_ts_ns |
| `HorizonFeatureSnapshot` | Layer 1.5 → Layer 2 | symbol, horizon_seconds, values, warm, stale |
| `Signal` | Layer 2 → Layer 3 / risk | direction, strength, edge_estimate_bps, trend_mechanism, expected_half_life_seconds |
| `CrossSectionalContext` | Layer 3 → portfolio alpha | alpha_id, horizon_seconds, signals, completeness |
| `SizedPositionIntent` | Layer 3 → risk | target_positions, mechanism_breakdown, decision_basis_hash |
| `RiskVerdict` | Risk → kernel | action (`RiskAction`), reason, scaling_factor |
| `OrderRequest` | Kernel → execution | order_id, symbol, side, qty, reason |
| `OrderAck` | Execution → kernel | status (`OrderAckStatus`), fill_price, filled_qty |
| `PositionUpdate` | Kernel → portfolio | symbol, signed qty, avg_entry, realized_pnl |
| `StateTransition` | Any SM → bus | machine_name, from/to, trigger |
| `MetricEvent` | Any → monitoring | layer, name, value, metric_type |
| `Alert` | Any → monitoring | severity (`AlertSeverity`), name, context |
| `KillSwitchActivation` | Kernel → all | reason, activated_by |

`SensorProvenance` and `TargetPosition` are value objects (not events).
`TrendMechanism` is a closed enum (`KYLE_INFO, INVENTORY,
HAWKES_SELF_EXCITE, LIQUIDITY_STRESS, SCHEDULED_FLOW`) carried on every
`Signal` and aggregated on `SizedPositionIntent.mechanism_breakdown`.

## Alpha Module System

`feelies.alpha` provides multi-strategy support behind the layer
protocols. Composition happens at startup via
`bootstrap.build_platform()`.

| Component | File | Responsibility |
|-----------|------|----------------|
| `AlphaManifest` | `alpha/module.py` | Schema-1.1 manifest (validated by `AlphaLoader`) |
| `LoadedSignalLayerModule` | `alpha/signal_layer_module.py` | Schema-1.1 SIGNAL alpha runtime |
| `LoadedPortfolioLayerModule` | `alpha/portfolio_layer_module.py` | Schema-1.1 PORTFOLIO alpha runtime |
| `AlphaLoader` | `alpha/loader.py` | Discovers and loads `*.alpha.yaml`; rejects `LEGACY_SIGNAL` |
| `LayerValidator` | `alpha/layer_validator.py` | Enforces gates G1–G16 at load time |
| `AlphaRegistry` | `alpha/registry.py` | Tracks active modules + per-alpha lifecycle (F-5 threshold merge) |
| `AlphaLifecycle` | `alpha/lifecycle.py` | 5-state machine (RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED) + LIVE @ SCALED self-loop (F-6) |
| `PromotionLedger` | `alpha/promotion_ledger.py` | Append-only JSONL audit trail (F-1) |
| `validate_gate` + `GATE_EVIDENCE_REQUIREMENTS` | `alpha/promotion_evidence.py` | F-2 declarative gate matrix |
| `feelies promote` | `cli/promote.py` | F-3 read-only operator CLI |

Per-alpha `GateThresholds` overrides merge over `platform.yaml`
defaults, themselves merged over skill-pinned defaults (F-5
three-layer merge). The merge is non-mutating and runs once at
registration time so an alpha's effective thresholds are immutable for
its lifetime — replay determinism is preserved.

See the alpha-lifecycle skill for the full evidence schema, gate
matrix, capital-tier escalation, and operator-CLI contract.

## Layer Gates G1–G16

Enforced by `LayerValidator` against every alpha YAML before
instantiation. Each gate raises a distinct `LayerValidationError`
subclass.

| Gate | Concern | Enforcement |
|------|---------|-------------|
| G1 | Layer independence | SIGNAL alphas cannot import PORTFOLIO modules and vice versa |
| G2–G8, G13 | Phase-3-α: event-typing, regime-gate purity, signal purity, sensor-DAG validity, horizon registration, no implicit lookahead, cost-arithmetic disclosure, warm-up documentation | Always blocks |
| G9 | Cross-symbol staleness | Always blocks |
| G10 | PORTFOLIO universe presence | Always blocks |
| G11 | PORTFOLIO factor-neutralization disclosure | Always blocks |
| G12 | Cost-arithmetic margin_ratio ≥ 1.5 (Inv-12) | Always blocks |
| G14 | Data dependency declaration | Always blocks |
| G15 | Router whitelist | Always blocks |
| G16 | Mechanism-horizon binding (taxonomy + half-life envelope + horizon ratio + fingerprint sensors + stress-family exit-only + family caps) | Always blocks |

`PlatformConfig.enforce_layer_gates` (default `true`) toggles G1 and G3
(architectural gates) between hard-blocking and WARNING-only. The
data-integrity / economic / provenance gates (G9–G16) **always block**
regardless of the flag.

`PlatformConfig.enforce_trend_mechanism` (default `true` since
Workstream E) additionally rejects schema-1.1 SIGNAL/PORTFOLIO alphas
that omit a `trend_mechanism:` block. Operators on a v0.2 baseline
must pin to `false` explicitly.

## Intent & Sizing

The Layer-2 (SIGNAL) path runs through these injectable components
between the bus-buffered `Signal` and the M5 risk check:

- **`PositionSizer`** (`risk/position_sizer.py`) — computes target
  share count from the alpha's risk budget, account equity, mid price,
  signal strength, and regime state. Default `BudgetBasedSizer`
  applies regime-dependent scaling (e.g., `vol_breakout` → 0.5×).
- **`IntentTranslator`** (`execution/intent.py`) — maps `(SignalDirection
  × current Position × target_quantity)` to a `TradingIntent` enum
  (`ENTRY_LONG, ENTRY_SHORT, EXIT, REVERSE_*, SCALE_UP, NO_ACTION`).
  `NO_ACTION` short-circuits the pipeline directly to M10.

The Layer-3 (PORTFOLIO) path bypasses the per-symbol translator: the
`SizedPositionIntent` is consumed by `RiskEngine.check_sized_intent`
which (a) resolves desired delta against `PositionStore`, (b) emits per-leg
`OrderRequest`s sorted lexicographically by symbol, (c) applies per-leg
risk checks with **per-leg veto semantics** — a single failed leg drops
only that leg, not the whole intent (Inv-11). Each emitted
`OrderRequest.reason = "PORTFOLIO"` for forensic lineage.

Hazard-driven exits run through `HazardExitController`
(`risk/hazard_exit.py`) which emits `OrderRequest.reason ∈
{"HAZARD_SPIKE", "HARD_EXIT_AGE"}`. See the regime-detection and
risk-engine skills.

## Observability

The monitoring layer is a cross-cutting concern. Every layer emits
typed events into it; no layer implements its own alerting in
isolation.

| Pillar | What | How |
|--------|------|-----|
| Logging | Structured JSON event stream | One stream per layer; `StateTransition` audit trail |
| Metrics | Time-series (latency, throughput, fill rate, parity) | `MetricEvent` with `MetricType ∈ {COUNTER, GAUGE, HISTOGRAM}` via `MetricCollector` |
| Tracing | End-to-end correlation | `correlation_id = make_correlation_id(symbol, exchange_ts_ns, sequence)` propagated across every layer |
| Alerting | Threshold + anomaly notifications | `Alert` with `AlertSeverity ∈ {INFO, WARNING, CRITICAL, EMERGENCY}` via `AlertManager` |

`MetricCollector.record(metric)` accepts `MetricEvent` from all layers
via bus subscription. `flush()` is called at M10 each tick and on
graceful shutdown. `AlertManager.emit(alert)` routes by severity;
CRITICAL and EMERGENCY trigger safety controls synchronously before
returning. `AlertManager.acknowledge(name, operator)` records human
acknowledgment but does not deactivate safety — re-authorization is
explicit (`KillSwitch.reset`, `Orchestrator.unlock_from_lockdown`).

Per-layer telemetry ownership:
- Execution-quality metrics → live-execution skill
- Latency budgets and profiling → performance-engineering skill
- Forensic health reports → post-trade-forensics skill
- Risk snapshots and PnL attribution → risk-engine skill
- Sensor-layer health → feature-engine skill

## Portfolio Layer Ownership

The portfolio layer (position tracking, PnL, capital allocation) is
distributed:

| Responsibility | Owning skill |
|---------------|--------------|
| Position tracking and reconciliation | live-execution (live) / backtest-engine (replay) |
| PnL decomposition and real-time attribution | risk-engine |
| Capital allocation and risk budgets | risk-engine (portfolio governor) |
| Multi-horizon attribution (per-mechanism, per-regime) | post-trade-forensics |
| Position-state interface (`PositionStore`) | this skill |

```python
class PositionStore(Protocol):
    def get(self, symbol: str) -> Position: ...
    def update(self, symbol: str, quantity_delta: int, fill_price: Decimal) -> Position: ...
    def all_positions(self) -> dict[str, Position]: ...
    def total_exposure(self) -> Decimal: ...
```

`PositionStore` is injected as a separate dependency into the
orchestrator (not composed into `ExecutionBackend`). Mode-specific
implementations (broker-backed live, simulated backtest) are selected
at composition time alongside `ExecutionBackend`. `total_exposure()`
gates `unlock_from_lockdown()`.

## Determinism (Inv-5)

Five locked **parity hashes** guard end-to-end determinism. Each is a
SHA-256 over the ordered event stream at one layer, asserted by a
subprocess-isolated test under `tests/determinism/`:

| Level | Stream | Test |
|-------|--------|------|
| L1 | `SensorReading` | `test_sensor_replay.py` |
| L2 | `Signal` (SIGNAL layer) | `test_signal_replay.py` |
| L3 | `SizedPositionIntent` | `test_sized_intent_replay.py` |
| L3-orders | per-leg `OrderRequest` from PORTFOLIO | `test_portfolio_order_replay.py` |
| L4 | hazard-exit `OrderRequest` | `test_hazard_exit_replay.py` |
| L5 | `RegimeHazardSpike` | `test_hazard_parity.py` |

Determinism is structurally supported by:
- `SimulatedClock.set_time()` rejecting backward movement
- SHA-256 order IDs (`hashlib.sha256(f"{correlation_id}:{seq}")`) — never `uuid4`
- `SequenceGenerator` (`core/identifiers.py`) thread-safe monotonic counter
- Frozen `StateMachine` transition tables
- `TransitionRecord` audit trail on every SM change
- `ruff DTZ` rules banning raw `datetime.now()` outside the `Clock` protocol (Inv-10)
- Strict `mypy` (no per-module `ignore_errors` overrides) — locked by
  `tests/acceptance/test_mypy_strict_scope.py`

## Hard Rules (this skill)

Inherits Inv-5, 7, 8, 9, 10, 11. Additionally:

1. **Explicit latency modeling** — every path is annotated with expected
   latency; live measures against expected via `MetricEvent`.
2. **Canonical message formats** — every event crossing a layer
   boundary is a frozen dataclass under `core/events.py`.
3. **Single tick code path** — `_process_tick_inner` is the only
   per-tick driver; mode branching outside `ExecutionBackend` is a
   defect.
4. **No silent transitions** — every SM change emits `StateTransition`
   on the bus.
5. **Exhaustiveness over flexibility** — explicit guard at every
   enum-driven decision point.

## Tradeoff Documentation

When making architectural decisions, state the tradeoff explicitly:
simplicity vs performance, memory vs CPU, latency vs abstraction,
flexibility vs type safety, generality vs determinism. Determinism
always wins when in tension.

## Design Targets

- **Auditability** — every decision traceable to a typed event with
  correlation ID
- **Determinism** — five locked parity hashes; bit-identical replay
- **Testability** — every layer testable in isolation with mock events
- **Strictness** — mypy strict on every module under `src/feelies/`;
  ruff DTZ on every `datetime` call; no `ignore_errors` overrides
