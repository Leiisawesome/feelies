# System Architecture — Engineering Reference

> **Cross-reference**: this document provides microstructure-specific
> architecture context. For the authoritative layer structure, state
> machines, and protocol definitions, see the system-architect skill.
> The actual tick-processing pipeline is the `MicroState` SM (M0-M10)
> in `kernel/micro.py`, driven by `Orchestrator._process_tick()`.

## Architecture Overview

The diagram below shows the conceptual flow. In the implemented codebase,
the Kernel layer (`Orchestrator`) coordinates all transitions, and
mode-specific behavior is confined to `ExecutionBackend`
(`execution/backend.py`) which composes `MarketDataSource` + `OrderRouter`.

```
┌─────────────────────────────────────────────────────────┐
│                    DATA LAYER                           │
│  Polygon.io WebSocket ──> MarketDataNormalizer          │
│  Polygon.io REST API ──> MarketDataSource (replay)      │
│  Output: NBBOQuote, Trade (core/events.py)              │
└──────────────────────┬──────────────────────────────────┘
                       │ M0→M1→M2
┌──────────────────────▼──────────────────────────────────┐
│                 FEATURE ENGINE                          │
│  FeatureEngine.update(NBBOQuote) → FeatureVector        │
│  Spread calculator  │  Quote dynamics  │  Trade flow    │
│  Micro-price        │  Volatility      │  Regime state  │
└──────────────────────┬──────────────────────────────────┘
                       │ M2→M3→M4
┌──────────────────────▼──────────────────────────────────┐
│                  SIGNAL LAYER                           │
│  SignalEngine.evaluate(FeatureVector) → Signal | None    │
│  Signal: direction(LONG/SHORT/FLAT), strength,          │
│          edge_estimate_bps, strategy_id                  │
└──────────────────────┬──────────────────────────────────┘
                       │ M4→M5
┌──────────────────────▼──────────────────────────────────┐
│                  RISK ENGINE                            │
│  RiskEngine.check_signal() → RiskVerdict(RiskAction)    │
│  RiskEngine.check_order()  → RiskVerdict(RiskAction)    │
│  Position limits  │  Drawdown monitor  │  RiskLevel SM  │
└──────────────────────┬──────────────────────────────────┘
                       │ M5→M6→M7
┌──────────────────────▼──────────────────────────────────┐
│              EXECUTION LAYER                            │
│  OrderRouter.submit(OrderRequest)                       │
│  OrderRouter.poll_acks() → OrderAck[OrderAckStatus]     │
│  Backtest: fill simulator │ Live: broker API            │
└──────────────────────┬──────────────────────────────────┘
                       │ M7→M8→M9
┌──────────────────────▼──────────────────────────────────┐
│             PORTFOLIO / POSITION                        │
│  PositionStore.update() → PositionUpdate event          │
│  TradeJournal.record() → TradeRecord                    │
└──────────────────────┬──────────────────────────────────┘
                       │ M9→M10→M0
┌──────────────────────▼──────────────────────────────────┐
│              MONITORING & LOGGING                       │
│  MetricEvent (tick_to_decision_latency_ns)              │
│  Alert / AlertSeverity │  StateTransition events        │
│  KillSwitch │  MetricCollector │  AlertManager           │
└─────────────────────────────────────────────────────────┘
```

---

## Data Layer

### Polygon.io Integration

**Real-time feeds (WebSocket):**
- `T.*` — Trade messages
- `Q.*` — NBBO quote messages
- `AM.*` — Per-minute aggregates (secondary)

**Historical data (REST):**
- `/v3/quotes/{ticker}` — Historical NBBO quotes (nanosecond)
- `/v3/trades/{ticker}` — Historical trades
- `/v2/aggs/ticker/{ticker}/range/...` — Aggregated bars

**Subscription tier**: Advanced Stock ($229/mo equivalent)
- Real-time trades + quotes
- Full historical access
- 5 concurrent websocket connections

### Data Normalization Requirements

| Field | Normalization |
|-------|--------------|
| Timestamps | Convert to exchange time; track Polygon receipt delay |
| Prices | Adjust for splits (use Polygon adjustment factors) |
| Sizes | Normalize to shares (not lots) |
| Conditions | Parse trade condition codes; filter irregular trades |
| Exchanges | Map exchange codes; flag SIP consolidated vs direct |

### Canonical Event Types

Raw Polygon data is normalized into typed events (`core/events.py`):

- `NBBOQuote`: bid/ask price+size, exchange timestamp, SIP timestamp
- `Trade`: price, size, conditions, aggressor side

These flow through `MarketDataNormalizer` protocol (`ingestion/normalizer.py`).
Per-symbol data health is tracked by the `DataHealth` SM
(`ingestion/data_integrity.py`): `HEALTHY → STALE → GAP_DETECTED → CORRUPT`.

### Replay Engine

For backtesting, replay historical data through `MarketDataSource`
(the same protocol as live, behind `ExecutionBackend`):
- Same feature computation code path (`FeatureEngine.update()`)
- `SimulatedClock` (`core/clock.py`) provides injectable time
- No future data leakage — enforced by `SimulatedClock.set_time()`
  monotonicity guard and causal ordering via `MicroState` pipeline
- Support variable-speed replay by controlling `SimulatedClock.set_time()` calls

---

## Feature Engine

> Implemented as the `FeatureEngine` protocol (`features/engine.py`).
> The orchestrator calls `FeatureEngine.update(NBBOQuote) -> FeatureVector`
> at micro-state M3 (FEATURE_COMPUTE). In multi-alpha deployments, the
> concrete implementation is `CompositeFeatureEngine` (`alpha/composite.py`).

### Design Principles

- **Incremental updates**: `update()` processes one quote at a time; no window recomputation
- **Warm-up tracking**: `FeatureVector.warm` flag; signals ignore cold vectors
- **Staleness detection**: `FeatureVector.stale` flag when quote age exceeds threshold
- **Determinism**: Same `NBBOQuote` sequence → identical `FeatureVector` stream (invariant 5)
- **Clock choice**: Support both wall-clock time and volume-clock (trade-count buckets)

### Feature Categories

```
LEVEL 0 — Raw observables
  bid, ask, bid_size, ask_size, last_trade, trade_size, trade_side

LEVEL 1 — Derived quantities
  spread, mid, micro_price, trade_aggressor, effective_spread

LEVEL 2 — Windowed statistics
  spread_ewma, quote_intensity, trade_imbalance, volatility_estimate

LEVEL 3 — Regime indicators
  spread_regime, vol_regime, flow_regime, composite_state
```

### Feature Compute Latency Budget

| Component | Target | Hard Limit |
|-----------|--------|------------|
| Feature update on new message | < 100 us | < 1 ms |
| Signal evaluation | < 1 ms | < 5 ms |
| Full pipeline (message -> order decision) | < 5 ms | < 20 ms |

These targets reflect Polygon.io websocket latency (~10-50ms) — no point
optimizing compute below the data delivery latency floor.

---

## Signal Layer

### Model Types

| Model | Use Case | Complexity |
|-------|----------|------------|
| Linear regression | Baseline alpha, interpretability | Low |
| Logistic / probit | Direction prediction with calibrated probability | Low |
| Ridge / Lasso | Feature selection + regularization | Medium |
| Gradient boosted trees | Non-linear interactions, regime capture | Medium |
| Online learning | Adaptive parameter updates | Medium-High |
| Hidden Markov Model | Regime detection and transition probabilities | High |

### Signal Output Specification

Signals are typed `Signal` events (`core/events.py`), produced by
`SignalEngine.evaluate(FeatureVector) -> Signal | None`:

```python
@dataclass(frozen=True)
class Signal(Event):
    symbol: str
    direction: SignalDirection    # LONG, SHORT, or FLAT
    strength: float              # 0.0–1.0 confidence
    strategy_id: str
    edge_estimate_bps: float     # expected edge after costs
    feature_snapshot: dict[str, float]
```

- `direction` is a typed enum (`SignalDirection`), not a float.
  `FLAT` signals exit the pipeline at M5 (no order constructed).
- `edge_estimate_bps` must exceed `1.5 × round_trip_cost` (invariant 12).
- `feature_snapshot` captures the `FeatureVector` values at signal time
  for provenance (invariant 13).
- `Signal` inherits `correlation_id`, `timestamp_ns`, `sequence` from
  `Event` base class, enabling end-to-end tracing.

### Model Governance

- Re-estimate parameters on a fixed schedule (e.g., weekly)
- Log all parameter updates with before/after comparison
- Monitor information coefficient daily; alert on sustained degradation
- Maintain a model registry with version history

---

## Execution Layer

> Implemented behind `ExecutionBackend` (`execution/backend.py`), which
> composes `MarketDataSource` + `OrderRouter`. Backtest and live modes
> provide different `OrderRouter` implementations; the core pipeline
> (MicroState M0–M10) is shared.

### Order Lifecycle

Orders flow through the 9-state `OrderState` SM (`execution/order_state.py`):
`CREATED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED/FILLED/CANCELLED/EXPIRED/REJECTED`.
See the live-execution skill `order-lifecycle.md` for full transition reference.

Fill events arrive as `OrderAck` events with typed `OrderAckStatus`
(ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED).

### Fill Model for Backtesting

> **v1 implemented** — `BacktestOrderRouter` fills at mid-price with
> configurable latency. The full 3-tier fill model (slippage, queue,
> adverse selection) is future work — see `fill-model.md`
> (backtest-engine skill).

**Market orders:**
```
fill_price = ask + slippage(size, displayed_ask_size, volatility)
```

**Limit orders:**
```
fill_probability = f(queue_position, time_in_queue, flow_direction)
```

### Latency Model

```
total_latency = polygon_delay + network_jitter + compute_time + broker_delay

polygon_delay ~ LogNormal(mu=3.0, sigma=0.5) [ms]
network_jitter ~ Uniform(1, 5) [ms]
compute_time ~ deterministic (measured via MetricEvent.tick_to_decision_latency_ns)
broker_delay ~ LogNormal(mu=2.0, sigma=0.8) [ms]
```

Add stochastic latency in backtest; do not use fixed latency assumptions.
`SimulatedClock` provides the time base; latency injection advances
simulated time without violating monotonicity.

---

## Risk Engine

> Implemented as the `RiskEngine` protocol with two-phase check:
> `check_signal()` at M5 (RISK_CHECK) and `check_order()` at M6
> (ORDER_DECISION). Both return `RiskVerdict` containing a `RiskAction`
> (ALLOW, REJECT, SCALE_DOWN, FORCE_FLATTEN). Exhaustiveness guards
> in the orchestrator ensure no unhandled action values.

### Position-Level Controls

| Control | Specification |
|---------|--------------|
| Max position size | Function of ADV and displayed liquidity |
| Max holding period | Kill stale positions (alpha half-life * 2) |
| Per-trade loss limit | Max 0.5% of daily capital per trade |
| Stop-loss | Structural invalidation, not fixed dollar amount |

### Portfolio-Level Controls

| Control | Specification |
|---------|--------------|
| Gross exposure limit | Configurable; default 2x capital |
| Net exposure limit | Configurable; default 0.3x capital |
| Sector concentration | Max 30% gross in any single sector |
| Correlation cluster limit | Max 3 positions with pairwise rho > 0.6 |
| Daily drawdown limit | -2% triggers position reduction; -3% triggers full flatten |
| Weekly drawdown limit | -5% triggers strategy pause for review |

### Kill Switches & Risk Escalation

The `RiskLevel` SM (`risk/escalation.py`) provides 5 monotonic states:
`NORMAL → WARNING → BREACH_DETECTED → FORCED_FLATTEN → LOCKED`.
`_escalate_risk()` in the orchestrator walks all intermediate transitions
and emits a `KillSwitchActivation` event.

Automatic shutdown triggers:
1. Daily PnL exceeds drawdown kill-switch threshold (configurable; see risk-engine skill)
2. Latency exceeds 200ms for > 30 seconds
3. Data feed gap > 5 seconds during market hours
4. Execution errors > 3 in any 10-minute window
5. Position reconciliation mismatch detected
6. Manual override via `KillSwitch.activate()`

See `safety-controls.md` (live-execution skill) for detailed implementation.

---

## Portfolio Construction

### Position Sizing

Volatility-scaled sizing:

```
position_size = (target_risk / realized_vol) * confidence * capital
```

Where:
- target_risk: annualized vol target per position (e.g., 10bps/day)
- realized_vol: rolling estimate of ticker's intraday volatility
- confidence: signal confidence (0 to 1)
- capital: allocated capital for this strategy

### Factor Exposure Management

Monitor and constrain:
- **Market beta**: Net beta < 0.1 (near market-neutral)
- **Sector**: No sector > 30% of gross
- **Size factor**: Balance across market cap
- **Momentum factor**: Avoid systematic momentum loading
- **Volatility factor**: Monitor vol-of-vol exposure

---

## Monitoring & Logging

> Metrics are emitted as `MetricEvent` events via `MetricCollector`
> protocol. Alerts are emitted as `Alert` events (with `AlertSeverity`:
> INFO, WARNING, CRITICAL, EMERGENCY) via `AlertManager` protocol.
> Both flow through the event bus.

### Real-Time Metrics

| Metric | Frequency | Alert Threshold |
|--------|-----------|----------------|
| PnL (realized + unrealized) | Per-second | Daily loss limit |
| `tick_to_decision_latency_ns` | Per-tick (MetricEvent) | > 100ms sustained |
| Fill rate vs expected | Per-trade | < 50% of expected |
| Information coefficient | Hourly | < 0 for 2+ consecutive hours |
| Spread regime | Per-tick | Regime shift detected |
| `DataHealth` state per symbol | Per-tick | `GAP_DETECTED` or `CORRUPT` |

### Research vs Production Separation

Both share the same core pipeline (`MicroState` M0–M10), differing only
in `ExecutionBackend`:

```
RESEARCH ENVIRONMENT (MacroState.RESEARCH_MODE):
- run_research() on Orchestrator
- SimulatedClock for injectable time
- Full historical data via MarketDataSource (replay)
- No OrderRouter — signals evaluated but no orders placed
- Feature experimentation via FeatureEngine protocol

PRODUCTION ENVIRONMENT (MacroState.LIVE_TRADING):
- run_live() on Orchestrator (requires RiskLevel == NORMAL)
- WallClock for real time
- Live data via MarketDataSource (WebSocket)
- Live OrderRouter (broker API)
- Frozen model parameters (until scheduled update)
- Full audit logging via EventLog, TradeJournal
```

Shared logic guarantees backtest/live parity (invariant 9).
Never deploy research code directly. Production code must be:
- Reviewed for correctness
- Tested with simulated data
- Validated against backtest results (paper trade period)
- Monitored for divergence from expected behavior
