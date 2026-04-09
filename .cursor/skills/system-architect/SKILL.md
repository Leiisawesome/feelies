---
name: system-architect
description: >
  Foundational system architecture for a unified intraday trading platform.
  Enforces layer separation, determinism, event-driven design, and dual-mode
  (research/live) behavioral equivalence under L1 NBBO constraints (Massive
  Advanced, formerly Polygon.io). Use when designing system components, defining layer boundaries,
  making architectural decisions, or reasoning about cross-layer interactions,
  failure modes, or deterministic replay.
---

# System Architect — Foundation

Design all components for a unified intraday trading platform where research
backtesting and live trading share core logic, behavioral equivalence is
enforced, and determinism is guaranteed in replay mode.

## System Boundaries

All code must belong to exactly one of these layers:

| Layer | Responsibility |
|-------|---------------|
| Market Data Ingestion | Normalize Massive L1 NBBO into canonical events |
| Event Bus | Route typed events with deterministic ordering |
| Feature Engine | Stateful feature computation from event streams (see feature-engine skill) |
| Signal Engine | Pure functions: features → signals (no side effects) |
| Intent & Sizing | Position-aware intent translation and risk-budget position sizing |
| Risk Engine | Position limits, exposure checks, drawdown gates |
| Execution Engine | Order routing, fill simulation (backtest) / broker API (live) |
| Alpha Module System | Discovery, registration, and lifecycle of strategy modules |
| Portfolio Layer | Position tracking, PnL, capital allocation |
| Storage Layer | Event log, feature snapshots, trade journal |
| Monitoring | Latency histograms, throughput, health checks, kill-switch |

## Kernel & Orchestration

The Kernel layer is the coordination center. The `Orchestrator`
(`kernel/orchestrator.py`) owns all five state machines and drives
layers through the deterministic micro-state pipeline. It contains
**no business logic** — only coordination, state management, and
fail-safe enforcement.

### State Machines

Five state machines govern all system behavior. Each uses the generic
`StateMachine[S]` framework (`core/state_machine.py`) with a frozen
transition table validated for enum completeness at construction.

| Machine | Enum | File | States | Scope |
|---------|------|------|--------|-------|
| Global Stack | `MacroState` | `kernel/macro.py` | 10 | System-wide lifecycle (INIT through SHUTDOWN) |
| Tick Pipeline | `MicroState` | `kernel/micro.py` | 11 | Per-tick processing sequence (M0 through M10) |
| Order Lifecycle | `OrderState` | `execution/order_state.py` | 9 | Per-order (CREATED through terminal) |
| Risk Escalation | `RiskLevel` | `risk/escalation.py` | 5 | Monotonic safety tightening (NORMAL through LOCKED) |
| Data Integrity | `DataHealth` | `ingestion/data_integrity.py` | 4 | Per-symbol stream health |

Every transition emits a `StateTransition` event on the bus via
`TransitionRecord` callbacks — no silent transitions (invariant 13).
Illegal transitions raise `IllegalTransition`.

### ExecutionBackend (Invariant 9)

This skill owns the `ExecutionBackend` abstraction and its two composed
protocols (`execution/backend.py`):

- `MarketDataSource` — historical replay (backtest) or live feed
- `OrderRouter` — simulated fills (backtest) or broker API (live)

`ExecutionBackend` is the **sole** mode-specific abstraction.

The orchestrator never inspects `backend.mode`. The micro-state pipeline
is identical across BACKTEST_MODE, PAPER_TRADING_MODE, and
LIVE_TRADING_MODE. Any logic that branches on mode outside
`ExecutionBackend` implementations is a defect.

#### Composition by Mode

Mode selection determines which concrete implementations are composed
into `ExecutionBackend` at startup. The orchestrator receives a fully
composed backend and never inspects `backend.mode`.

| Mode | `MarketDataSource` | `OrderRouter` | `Clock` |
|------|-------------------|---------------|---------|
| `BACKTEST_MODE` (`execution_mode: market`) | `ReplayFeed(EventLog)` | `BacktestOrderRouter` (mid-price fills) | `SimulatedClock` |
| `BACKTEST_MODE` (`execution_mode: passive_limit`) | `ReplayFeed(EventLog)` | `PassiveLimitOrderRouter` (queue-position fills) | `SimulatedClock` |
| `PAPER_TRADING_MODE` | `MassiveLiveFeed` | Paper router (NOT YET IMPLEMENTED) | `WallClock` |
| `LIVE_TRADING_MODE` | `MassiveLiveFeed` | Broker router (NOT YET IMPLEMENTED) | `WallClock` |

Historical backfill (`MassiveHistoricalIngestor`) is a batch process
that populates `EventLog` — it runs outside the orchestrator lifecycle
and is not an operating mode. See the data-engineering skill for
backfill details (REST API, checkpointing, resumability).

Composition happens at startup via `bootstrap.build_platform(config)`,
which selects concrete implementations for the desired mode:
`build_backtest_backend()` composes `ReplayFeed` + `BacktestOrderRouter`
(mid-price fills) and `build_passive_limit_backend()` composes
`ReplayFeed` + `PassiveLimitOrderRouter` (queue-position fills).
The `execution_mode` config field (`"market"` or `"passive_limit"`)
selects which factory is called. Both wire `NBBOQuote` bus subscriptions
so the router tracks last-seen quotes for fill pricing. The orchestrator
receives a fully composed backend and never inspects `backend.mode`.

### Fail-Safe Cascade (Invariant 11)

When any tick-processing step throws an exception:

1. Micro SM resets to M0 (`_handle_tick_failure`)
2. Macro transitions to DEGRADED
3. The original exception type is captured in the trigger for provenance

When risk escalation fires (`_escalate_risk`):

1. Risk SM walks R0 → R1 → R2 → R3 → R4 (monotonic, forward-only)
2. Kill switch activates (irreversible without human intervention)
3. Macro transitions to RISK_LOCKDOWN
4. Recovery requires `unlock_from_lockdown(audit_token)` with zero exposure

### Exhaustiveness Guards

At every enum-driven decision point, an explicit guard raises `ValueError`
for unhandled enum members. This pattern prevents new enum additions from
silently falling through to unsafe paths. Applied at:

- `RiskAction` gate (M5 and M6)
- `TradingIntent` in `_side_from_intent`
- `OrderAckStatus` in `_apply_ack_to_order`

## Hard Rules

Inherits platform invariants 5 (deterministic replay), 7 (event-driven typed schemas),
8 (layer separation), 10 (clock abstraction). Additionally:

1. **Explicit latency modeling** — annotate every path with expected latency; measure actual vs expected in production.
2. **Canonical message formats** — define typed schemas for every event crossing a layer boundary.

## Typed Event Catalog

All inter-layer communication uses frozen dataclasses from `core/events.py`.
Every event inherits from `Event` which carries `timestamp_ns`,
`correlation_id`, and `sequence` for provenance.

| Event | Layer Boundary | Key Fields |
|-------|---------------|------------|
| `NBBOQuote` | Ingestion → Feature/Signal | symbol, bid, ask, bid_size, ask_size |
| `Trade` | Ingestion → Feature/Storage | symbol, price, size |
| `FeatureVector` | Feature → Signal | symbol, feature_version, values, warm, stale |
| `Signal` | Signal → Risk | symbol, direction (`SignalDirection`), strength, edge_estimate_bps |
| `RiskVerdict` | Risk → Kernel | action (`RiskAction`), reason, scaling_factor |
| `OrderRequest` | Kernel → Execution | order_id, symbol, side, order_type, quantity |
| `OrderAck` | Execution → Kernel | order_id, status (`OrderAckStatus`), fill_price, filled_quantity |
| `PositionUpdate` | Kernel → Portfolio | symbol, quantity, avg_price, realized_pnl |
| `StateTransition` | Any SM → Bus | machine_name, from_state, to_state, trigger |
| `MetricEvent` | Any → Monitoring | layer, name, value, metric_type (`MetricType`) |
| `Alert` | Any → Monitoring | severity (`AlertSeverity`), alert_name, message |
| `KillSwitchActivation` | Kernel → All | reason, activated_by |

## Intent & Sizing Layer

Between signal evaluation (M4) and risk check (M5), the orchestrator
runs two injectable components that bridge the stateless signal to a
position-aware trading action:

### PositionSizer (`risk/position_sizer.py`)

```python
class PositionSizer(Protocol):
    def compute_target_quantity(
        self, signal: Signal, risk_budget: AlphaRiskBudget,
        symbol_price: Decimal, account_equity: Decimal,
    ) -> int: ...
```

Computes unsigned target share count from the alpha's declared risk
budget, account equity, mid-price, signal strength, and regime state.
The default `BudgetBasedSizer` applies regime-dependent scaling factors
(e.g., `vol_breakout` → 0.5×).

### IntentTranslator (`execution/intent.py`)

```python
class IntentTranslator(Protocol):
    def translate(
        self, signal: Signal, position: Position,
        target_quantity: int | None = None,
    ) -> OrderIntent: ...
```

Maps `(signal direction × current position)` to a `TradingIntent` enum:
`ENTRY_LONG`, `ENTRY_SHORT`, `EXIT`, `REVERSE_LONG_TO_SHORT`,
`REVERSE_SHORT_TO_LONG`, `SCALE_UP`, or `NO_ACTION`. The default
`SignalPositionTranslator` encodes the full signal×position matrix.

`NO_ACTION` causes the micro-state pipeline to skip M5–M9 entirely,
transitioning directly from M4 to M10 (LOG_AND_METRICS). This is the
path taken when the signal agrees with the current position and no
scaling is needed, or when a `FLAT` signal has no position to exit.

### Pipeline Position

```
M4: signal = signal_engine.evaluate(features)
    → target_qty = position_sizer.compute_target_quantity(signal, ...)
    → intent = intent_translator.translate(signal, position, target_qty)
    → if intent.intent == NO_ACTION → M10 (skip risk + order path)
M5: verdict = risk_engine.check_signal(signal, positions)
M6: order = _build_order_from_intent(intent, verdict, cid)
```

---

## Alpha Module System

The alpha module system provides multi-strategy support behind the
single-engine protocol interfaces. It is composed at startup via
`bootstrap.build_platform()`.

### Components

| Component | File | Responsibility |
|-----------|------|---------------|
| `AlphaModule` | `alpha/module.py` | Bundled strategy unit: manifest, feature defs, signal evaluator, risk budget |
| `AlphaRegistry` | `alpha/registry.py` | Tracks registered modules with lifecycle (active/suspended/quarantined) |
| `AlphaLoader` | `alpha/loader.py` | Discovers and loads `.alpha.yaml` spec files into `AlphaModule` instances |
| `CompositeFeatureEngine` | `alpha/composite.py` | Aggregates feature definitions from all registered alphas; computes in topological order |
| `CompositeSignalEngine` | `alpha/composite.py` | Fans out `evaluate()` to each active alpha; applies signal arbitration |
| `SignalArbitrator` | `alpha/arbitration.py` | Resolves conflicts when multiple alphas emit signals for the same symbol |
| `load_and_register()` | `alpha/discovery.py` | Discovers `.alpha.yaml` files in a directory and registers them |

### Composition Flow

```
PlatformConfig.alpha_spec_dir / alpha_specs
  → AlphaLoader.load(spec_path) → AlphaModule
    → AlphaRegistry.register(module)
      → CompositeFeatureEngine(registry)  # implements FeatureEngine protocol
      → CompositeSignalEngine(registry)   # implements SignalEngine protocol
```

The orchestrator receives `CompositeFeatureEngine` and
`CompositeSignalEngine` as its `FeatureEngine` and `SignalEngine`
dependencies — it never knows about the multi-alpha structure.

---

## Tradeoff Documentation

When making architectural decisions, explicitly state the tradeoff:

- Simplicity vs performance
- Memory vs CPU
- Latency vs abstraction
- Flexibility vs type safety

## Failure & Degradation

- Every component defines its failure mode (crash, degrade, retry).
- Stale data must be detected and surfaced, never silently consumed.
- Kill-switch conditions defined per-strategy and globally.
- Throughput bottlenecks and latency-critical paths identified and documented.

## Observability & Monitoring

The Monitoring layer listed in System Boundaries is a cross-cutting concern.
Every other layer emits telemetry into it; no layer implements its own
alerting or dashboarding in isolation.

### Pillars

| Pillar | What | How |
|--------|------|-----|
| Logging | Structured, machine-parseable event logs | JSON lines; one log stream per layer; no unstructured prints |
| Metrics | Numeric time-series (latency, throughput, PnL, fill rate) | Counters, gauges, histograms; emitted via event bus |
| Tracing | End-to-end request/event correlation | Correlation ID assigned at ingestion; propagated through every layer |
| Alerting | Threshold- and anomaly-based notifications | Defined per layer; routed through a central alert manager |

### Correlation ID

Every inbound market data event receives a unique `correlation_id` at
ingestion via `make_correlation_id()` (`core/identifiers.py`). This ID
propagates through feature computation, signal generation, risk check,
and order submission. A single correlation ID links a quote update to
the trade it ultimately caused — enabling end-to-end latency measurement
and root-cause investigation.

```
correlation_id = f"{symbol}:{exchange_timestamp_ns}:{sequence}"
```

Sequence numbers are produced by `SequenceGenerator` (`core/identifiers.py`),
a thread-safe monotonic counter.

### Metric Collection

Each layer emits metrics onto the event bus as typed `MetricEvent` events
(`core/events.py`). The orchestrator forwards these to the `MetricCollector`
protocol (`monitoring/telemetry.py`) via bus subscription.

| Layer | Key Metrics |
|-------|------------|
| Ingestion | Events/sec, parse errors, feed latency, gap count |
| Feature Engine | Compute time per tick, warm-up status, stale symbol count |
| Signal Engine | Signals emitted/sec, signal-to-noise ratio, evaluation time |
| Risk Engine | Checks/sec, rejection rate, regime state, drawdown level |
| Execution Engine | Orders/sec, fill rate, slippage, latency histograms |
| Storage | Write throughput, disk usage, checkpoint lag |

Metrics are collected at p50, p95, p99, p99.9 where applicable.

### Alert Routing

Alerts are typed `Alert` events carrying `AlertSeverity` (`core/events.py`),
routed to the `AlertManager` protocol (`monitoring/alerting.py`) via bus
subscription. Kill switch activations emit `KillSwitchActivation` events.

| Severity (`AlertSeverity`) | Response Time | Channel | Examples |
|----------|--------------|---------|----------|
| INFO | Async review | Log only | Feature warm-up complete, regime transition |
| WARNING | < 15 min | Log + dashboard highlight | Elevated slippage, latency approaching ceiling |
| CRITICAL | < 1 min | Log + push notification | Kill switch fired, position reconciliation failure |
| EMERGENCY | Immediate (automated) | Automated safety response + notification | Unrecoverable state, broker disconnect |

Critical and emergency alerts activate safety controls autonomously.
Human review follows but does not gate the safety response.

### Dashboard Requirements

Operational dashboards must surface at minimum:
- Real-time PnL curve (gross, net, by strategy)
- Tick-to-trade latency histogram (updating)
- Per-symbol feature staleness map
- Risk constraint utilization (how close to limits)
- Safety control state (kill switch, circuit breaker, throttle)
- Feed health (events/sec, gap count, reconnect count)

Dashboards read from the metric stream. They never query production
databases or add load to the critical path.

### Monitoring Protocol Ownership

This skill owns the `MetricCollector` and `AlertManager` protocols.

#### MetricCollector (`monitoring/telemetry.py`)

```python
class MetricCollector(Protocol):
    def record(self, metric: MetricEvent) -> None: ...
    def flush(self) -> None: ...
```

`record()` accepts typed `MetricEvent` from all layers via bus subscription.
`flush()` writes buffered metrics to persistent storage — called at end of
each tick (M10) and on graceful shutdown.

#### AlertManager (`monitoring/alerting.py`)

```python
class AlertManager(Protocol):
    def emit(self, alert: Alert) -> None: ...
    def active_alerts(self) -> list[Alert]: ...
    def acknowledge(self, alert_name: str, *, operator: str) -> None: ...
```

`emit()` routes alerts by `AlertSeverity`. CRITICAL and EMERGENCY trigger
safety controls synchronously before returning (invariant 11).
`acknowledge()` records human acknowledgment but does not deactivate
safety controls — those require explicit re-authorization (e.g.,
`KillSwitch.reset`, `Orchestrator.unlock_from_lockdown`).

Failure mode: crash. If AlertManager is unavailable, the system cannot
guarantee safety responses — it is a hard dependency.

### Ownership Boundaries

Observability infrastructure (log aggregation, metric storage, alert
routing, dashboards) is owned by this layer. Individual layers define
*what* they emit; this layer defines *how* it is collected, stored,
correlated, and surfaced. Skill-specific monitoring details:
- Execution quality metrics: live-execution skill
- Latency budgets and profiling: performance-engineering skill
- Forensic health reports: post-trade-forensics skill
- Risk snapshots and PnL attribution: risk-engine skill

---

## Portfolio Layer Ownership

The Portfolio Layer (position tracking, PnL, capital allocation) is not a
separate skill. Its responsibilities are distributed:

| Responsibility | Owning Skill |
|---------------|-------------|
| Position tracking and reconciliation | live-execution (live) / backtest-engine (replay) |
| PnL decomposition and attribution | risk-engine |
| Capital allocation and risk budgets | risk-engine (portfolio governor) |
| Position state interface | system-architect (`PositionStore` protocol, injected independently) |

All three skills share the `PositionStore` protocol (`portfolio/position_store.py`),
injected as a separate dependency into the orchestrator (not composed into
`ExecutionBackend`). Mode-specific `PositionStore` implementations (broker-backed
live, simulated backtest) are selected at composition time alongside `ExecutionBackend`.

### PositionStore Protocol

```python
@dataclass
class Position:
    symbol: str
    quantity: int              # signed: +long, -short
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal

class PositionStore(Protocol):
    def get(self, symbol: str) -> Position: ...
    def update(self, symbol: str, quantity_delta: int, fill_price: Decimal) -> Position: ...
    def all_positions(self) -> dict[str, Position]: ...
    def total_exposure(self) -> Decimal: ...
```

- `get()` — returns current position for a symbol (zero-position `Position` if none)
- `update()` — atomically applies a fill delta and returns updated position with recalculated `realized_pnl`; called in `_reconcile_fills()` at M9
- `all_positions()` — snapshot for risk checks, PnL attribution, and reconciliation
- `total_exposure()` — aggregate absolute exposure; used by risk engine for limit checks and by `unlock_from_lockdown()` zero-exposure guard

---

## Design Targets

- **Auditability**: every decision traceable to an event
- **Determinism**: replay produces identical output
- **Scalability**: horizontal scaling at ingestion and feature layers
- **Testability**: every layer testable in isolation with mock events
