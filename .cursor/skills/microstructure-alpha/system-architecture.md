# System Architecture — Engineering Reference

> **Cross-reference**: this document provides microstructure-specific
> architecture context. For the authoritative layer structure, state
> machines, and protocol definitions, see the system-architect skill.
> The actual tick-processing pipeline is the `MicroState` SM (M0–M10
> backbone with Phase-2/3/4 sub-states) in `kernel/micro.py`, driven
> by `Orchestrator._process_tick_inner()`.

## Architecture Overview

The diagram below shows the conceptual flow. In the implemented codebase,
the Kernel layer (`Orchestrator`) coordinates all transitions, and
mode-specific behavior is confined to `ExecutionBackend`
(`execution/backend.py`) which composes `MarketDataSource` + `OrderRouter`.

```
┌────────────────────────────────────────────────────────────┐
│                      DATA LAYER                            │
│  Massive WebSocket  ─→ MarketDataNormalizer (live)         │
│  Massive REST API   ─→ EventLog → ReplayFeed (backtest)    │
│  Output: NBBOQuote, Trade (core/events.py)                 │
└──────────────────────┬─────────────────────────────────────┘
                       │ M0 → M1 → M2  (RegimeEngine.posterior → RegimeState)
┌──────────────────────▼─────────────────────────────────────┐
│             SENSOR LAYER (Layer 1)                         │
│  SensorRegistry fan-out (13 sensors in v0.3)               │
│  SENSOR_UPDATE: SensorProtocol.update → SensorReading      │
│  Mechanism fingerprints: kyle_lambda, inventory_pressure,  │
│  hawkes_intensity, liquidity_stress_score, scheduled_flow  │
└──────────────────────┬─────────────────────────────────────┘
                       │ HORIZON_CHECK / HORIZON_AGGREGATE
┌──────────────────────▼─────────────────────────────────────┐
│           HORIZON AGGREGATION (Layer 1.5)                  │
│  HorizonScheduler boundary detection (integer math)        │
│  HorizonAggregator → HorizonFeatureSnapshot                │
│  warm/stale flags, z-scores, percentiles                   │
└──────────────────────┬─────────────────────────────────────┘
                       │ SIGNAL_GATE
┌──────────────────────▼─────────────────────────────────────┐
│              SIGNAL LAYER (Layer 2)                        │
│  HorizonSignalEngine: regime_gate eval                     │
│    HorizonSignal.evaluate(snapshot, regime, params)        │
│  Signal: direction, strength, edge_estimate_bps,           │
│           trend_mechanism, expected_half_life_seconds      │
└──────────────────────┬─────────────────────────────────────┘
                       │ CROSS_SECTIONAL (PORTFOLIO only)
┌──────────────────────▼─────────────────────────────────────┐
│            COMPOSITION LAYER (Layer 3)                     │
│  UniverseSynchronizer → CrossSectionalContext              │
│  CompositionEngine:                                         │
│    PortfolioAlpha.compute_weights                          │
│      → CrossSectionalRanker (decay-weighted, capped)       │
│      → FactorNeutralizer (factor exposures)                │
│      → SectorMatcher (long/short pairing)                  │
│      → TurnoverOptimizer (cvxpy QP, optional)              │
│  Output: SizedPositionIntent + mechanism_breakdown         │
└──────────────────────┬─────────────────────────────────────┘
                       │ M5: RISK_CHECK
┌──────────────────────▼─────────────────────────────────────┐
│                  RISK ENGINE                               │
│  check_signal()      → RiskVerdict (per-symbol path)       │
│  check_order()       → RiskVerdict (post-construction)     │
│  check_sized_intent()→ per-leg veto on PORTFOLIO intent    │
│  Position limits │ drawdown │ RiskLevel SM (R0→R4)         │
│  HazardExitController consumes RegimeHazardSpike           │
└──────────────────────┬─────────────────────────────────────┘
                       │ M6 → M7 → M8 → M9
┌──────────────────────▼─────────────────────────────────────┐
│              EXECUTION LAYER                               │
│  OrderRouter.submit(OrderRequest)                          │
│  OrderRouter.poll_acks() → OrderAck[OrderAckStatus]        │
│  Backtest: BacktestOrderRouter / PassiveLimitOrderRouter   │
│  Live:     broker API (not yet implemented)                │
└──────────────────────┬─────────────────────────────────────┘
                       │ M9 → M10
┌──────────────────────▼─────────────────────────────────────┐
│             PORTFOLIO / POSITION                           │
│  PositionStore.update() → PositionUpdate event             │
│  TradeJournal.record() → TradeRecord                       │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│              MONITORING & LOGGING                          │
│  MetricEvent (tick_to_decision_latency_ns)                 │
│  Alert / AlertSeverity │ StateTransition events            │
│  KillSwitch │ MetricCollector │ AlertManager               │
└────────────────────────────────────────────────────────────┘
```

The historical per-tick `FeatureVector` / `FeatureEngine.update` /
`SignalEngine.evaluate` / `CompositeFeatureEngine` /
`CompositeSignalEngine` / `AlphaModule.evaluate` contracts were
retired in Workstream D.2.

---

## Data Layer

### Massive API Integration

**Real-time feeds (WebSocket):**
- `T.*` — Trade messages
- `Q.*` — NBBO quote messages
- `AM.*` — Per-minute aggregates (secondary)

**Historical data (REST):**
- `/v3/quotes/{ticker}` — Historical NBBO quotes (nanosecond)
- `/v3/trades/{ticker}` — Historical trades
- `/v2/aggs/ticker/{ticker}/range/...` — Aggregated bars

**Subscription tier**: Advanced Stock — real-time trades + quotes,
full historical access, 5 concurrent WebSocket connections.

### Data Normalization

| Field | Normalization |
|-------|--------------|
| Timestamps | Convert to exchange time; track Massive receipt delay |
| Prices | Adjust for splits (Massive adjustment factors) |
| Sizes | Normalize to shares (not lots) |
| Conditions | Parse trade-condition codes; filter irregular |
| Exchanges | Map exchange codes; flag SIP consolidated vs direct |

### Canonical Event Types

Raw Massive data is normalized into typed events (`core/events.py`):

- `NBBOQuote` — bid/ask price+size, exchange timestamp
- `Trade` — price, size, conditions, aggressor side

These flow through the `MarketDataNormalizer` protocol
(`ingestion/normalizer.py`). Per-symbol data health is tracked by the
`DataHealth` SM (`ingestion/data_integrity.py`):
`HEALTHY → GAP_DETECTED → CORRUPTED → RECOVERING`.

### Replay Engine

For backtesting, replay historical data through `MarketDataSource`
(the same protocol as live, behind `ExecutionBackend`):

- Same downstream code path (sensor → aggregator → signal → composition)
- `SimulatedClock` (`core/clock.py`) provides injectable time
- No future-data leakage — enforced by `SimulatedClock.set_time()`
  monotonicity guard and causal ordering via `MicroState` pipeline
- Variable-speed replay by controlling `SimulatedClock.set_time()` calls

---

## Sensor Layer (Layer 1)

> Implemented as the `SensorProtocol` + `SensorRegistry` framework
> (`feelies.sensors`). Sensors fan out at the `SENSOR_UPDATE`
> sub-state between M2 and M3. See the feature-engine skill for the
> full sensor + horizon-aggregator contract.

### Design Principles

- **Incremental updates**: `SensorProtocol.update()` processes one
  event at a time; no window recomputation
- **Per-symbol isolation**: state is per-symbol; no cross-symbol
  leakage inside a sensor
- **Bounded memory**: per-sensor footprint configurable
- **Determinism**: same `(NBBOQuote | Trade)` sequence → identical
  `SensorReading` stream (Inv-5)

### Mechanism-Aware Sensor Catalog (v0.3)

Per the trend-mechanism taxonomy (G16):

| Family | Sensors |
|--------|---------|
| KYLE_INFO | `kyle_lambda_60s`, `kyle_lambda_300s`, OFI proxies |
| INVENTORY | `inventory_pressure`, `quote_replenishment_asym` |
| HAWKES_SELF_EXCITE | `hawkes_intensity`, `trade_clustering` |
| LIQUIDITY_STRESS | `liquidity_stress_score`, `spread_z_30d`, `quote_flicker_rate` |
| SCHEDULED_FLOW | `scheduled_flow_window` |
| Composite | `ofi_ewma`, `micro_price_drift`, `effective_spread` |

---

## Horizon Aggregation (Layer 1.5)

### `HorizonScheduler` + `HorizonAggregator`

`HorizonScheduler` detects boundary crossings via pure integer math
against `session_open_ns` for each configured horizon
(`{30, 120, 300, 900, 1800}` seconds canonical Phase-2 set). On each
`HorizonTick`, `HorizonAggregator` fans in the most recent
`SensorReading` per (symbol, sensor_id) and emits a
`HorizonFeatureSnapshot` carrying values, z-scores, percentiles, and
warm/stale quality flags.

### Quality Gates

- `warm: bool` — every consumed sensor past its `warm_up`; SIGNAL
  alphas suppress entry when False
- `stale: bool` — no NBBO arrival within staleness threshold; entry
  suppressed, exit allowed (conservative)
- `boundary_index: int` — deterministic ordering key for parity hashes

---

## Signal Layer (Layer 2)

### `HorizonSignal` Contract

```python
class HorizonSignal(Protocol):
    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState,
        params: Mapping[str, Any],
    ) -> Signal | None: ...
```

`evaluate()` is a **pure function**. `HorizonSignalEngine` invokes it
once per `(alpha_id, symbol, boundary_index)` after the alpha's
`regime_gate` resolves to ON.

### Signal Output

```python
@dataclass(frozen=True, kw_only=True)
class Signal(Event):
    symbol: str
    strategy_id: str
    direction: SignalDirection                  # LONG, SHORT, FLAT
    strength: float                              # [0, 1]
    edge_estimate_bps: float                     # > 1.5 × round_trip_cost (Inv-12)
    trend_mechanism: TrendMechanism | None       # G16 — populated for schema-1.1
    expected_half_life_seconds: int              # G16 — 0 means unspecified
    metadata: dict[str, Any]
```

`FLAT` signals are handled by the `IntentTranslator`: when there is
no position to exit, the translator returns `NO_ACTION`, causing the
pipeline to skip from M4 directly to M10 — before the risk check at
M5.

### Regime Gate Purity (G3)

`signals/regime_gate.py` parses the alpha's `regime_gate:` block into
a safe AST-evaluated boolean DSL. Bindings drawn from `RegimeState`
posteriors and the live sensor cache. Hysteresis state is per
`(alpha_id, symbol)`. Whitelisted AST nodes only — `Attribute`,
free-form `Call`, `Lambda`, `Subscript`, `ListComp`, etc. raise
`UnsafeExpressionError` at compile time.

### Cost Arithmetic (G12)

The `cost_arithmetic:` block discloses `edge_estimate_bps`,
`half_spread_bps`, `impact_bps`, `fee_bps`, and `margin_ratio`.
Validated by `alpha/cost_arithmetic.py`:

- `margin_ratio ≥ 1.5` (Inv-12)
- Disclosed margin reconciles with components within ±5%

The platform refuses to load any alpha with `margin_ratio < 1.5`.

---

## Composition Layer (Layer 3)

> See the composition-layer skill for the full contract. Summary:
> `PortfolioAlpha` declares a `universe`, `depends_on_signals`,
> `factor_neutralization`, and emits cross-sectional weights via
> `compute_weights`. `CompositionEngine` runs the rank → neutralize
> → sector → optimize → cap pipeline and emits
> `SizedPositionIntent` with `mechanism_breakdown`. `RiskEngine.check_sized_intent`
> decomposes it into per-leg `OrderRequest`s with per-leg veto
> semantics.

---

## Execution Layer

> Implemented behind `ExecutionBackend` (`execution/backend.py`),
> which composes `MarketDataSource` + `OrderRouter`. Backtest and
> live modes provide different `OrderRouter` implementations; the
> core pipeline is shared.

### Order Lifecycle

Orders flow through the 9-state `OrderState` SM
(`execution/order_state.py`):
`CREATED → SUBMITTED → ACKNOWLEDGED → {PARTIALLY_FILLED, FILLED,
CANCEL_REQUESTED, REJECTED, EXPIRED, CANCELLED}`.
See `order-lifecycle.md` (live-execution skill) for the full reference.

Fill events arrive as `OrderAck` events with typed `OrderAckStatus`
(ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED).

### Backtest Routers

Two backtest routers are available, selected via `execution_mode`:

- `BacktestOrderRouter` (`execution_mode: market`) — immediate
  mid-price fills with configurable latency
- `PassiveLimitOrderRouter` (`execution_mode: passive_limit`) —
  deterministic queue-position fill model with through-fill,
  level-fill, timeout cancellation; passive fills charge zero spread
  cost and apply a maker rebate

The stochastic 3-tier fill model (slippage, adverse selection)
remains a design target — see `fill-model.md` (backtest-engine skill).

### Latency Model

```
total = massive_delay + network_jitter + compute_time + broker_delay

massive_delay  ~ LogNormal(mu=3.0, sigma=0.5) [ms]
network_jitter ~ Uniform(1, 5) [ms]
compute_time   ~ deterministic (measured via tick_to_decision_latency_ns)
broker_delay   ~ LogNormal(mu=2.0, sigma=0.8) [ms]
```

Add stochastic latency in backtest; do not use fixed latency
assumptions. `SimulatedClock` provides the time base; latency
injection advances simulated time without violating monotonicity.

---

## Risk Engine

> Implemented as the `RiskEngine` protocol with three entry points:
> `check_signal()` at M5 (per-symbol SIGNAL path),
> `check_order()` at M6 (post-construction final gate), and
> `check_sized_intent()` at the CROSS_SECTIONAL sub-state (per-leg
> veto on PORTFOLIO intent). All return `RiskVerdict` containing a
> `RiskAction` (ALLOW, REJECT, SCALE_DOWN, FORCE_FLATTEN).
> Exhaustiveness guards in the orchestrator ensure no unhandled
> action values.

### Risk Escalation

The `RiskLevel` SM (`risk/escalation.py`) provides 5 monotonic states:
`NORMAL → WARNING → BREACH_DETECTED → FORCED_FLATTEN → LOCKED`.
`_escalate_risk()` walks all intermediate transitions and emits a
`KillSwitchActivation` event.

### Hazard Exit

`HazardExitController` (`risk/hazard_exit.py`) consumes
`RegimeHazardSpike` events from `RegimeHazardDetector` and emits
`OrderRequest.reason ∈ {"HAZARD_SPIKE", "HARD_EXIT_AGE"}` to flatten
open positions when departure exceeds the per-alpha
`hazard_score_threshold`. Wired behind alpha-level
`hazard_exit.enabled: true` (default off).

### Automatic Shutdown Triggers

1. Daily PnL exceeds drawdown kill-switch threshold (configurable)
2. Latency exceeds 200 ms for > 30 seconds
3. Data-feed gap > 5 seconds during market hours
4. Execution errors > 3 in any 10-minute window
5. Position-reconciliation mismatch detected
6. Manual override via `KillSwitch.activate()`

See `safety-controls.md` (live-execution skill) for detailed
implementation.

---

## Portfolio Construction

### Position Sizing

Volatility-scaled (`risk/position_sizer.py`):

```
position_size = (target_risk / realized_vol) × confidence × capital
```

The default `BudgetBasedSizer` reads `RegimeEngine.current_state` and
applies regime-dependent scaling.

### Factor Exposure Management

Cross-sectional construction is enforced at Layer 3 by the
composition pipeline:

- Market beta: net beta < 0.1 (near market-neutral)
- Sector: enforced via `SectorMatcher`
- Size / value / momentum: enforced via `FactorNeutralizer` against
  the parquet-loaded `FactorLoadings` artifact (`factor_loadings_max_age_seconds`
  guard at bootstrap)
- Mechanism concentration: per-family `max_share_of_gross` cap (G16)

---

## Monitoring & Logging

> Metrics are emitted as `MetricEvent` events via `MetricCollector`
> protocol. Alerts as `Alert` events (with `AlertSeverity`: INFO,
> WARNING, CRITICAL, EMERGENCY) via `AlertManager`. Both flow through
> the event bus.

### Real-Time Metrics

| Metric | Frequency | Alert |
|--------|-----------|-------|
| PnL (realized + unrealized) | Per-second | Daily loss limit |
| `tick_to_decision_latency_ns` | Per-tick (HISTOGRAM) | > 100 ms sustained |
| Fill rate vs expected | Per-trade | < 50% of expected |
| Signal IC | Hourly | < 0 for 2+ consecutive hours |
| Regime state per symbol | Per-tick | Regime shift detected |
| `DataHealth` per symbol | Per-tick | `GAP_DETECTED` or `CORRUPTED` |

### Research vs Production

Both share the same core pipeline (M0–M10 backbone with Phase-2/3/4
sub-states), differing only in `ExecutionBackend`:

```
RESEARCH (MacroState.RESEARCH_MODE):
- run_research(job) on Orchestrator
- SimulatedClock for injectable time
- Full historical data via MarketDataSource (replay)
- No OrderRouter — orders never submitted

PRODUCTION (MacroState.LIVE_TRADING_MODE):
- run_live() on Orchestrator (requires RiskLevel == NORMAL)
- WallClock for real time
- Live data via MarketDataSource (WebSocket)
- Live OrderRouter (broker API)
- Frozen alpha YAML (until scheduled update)
- Full audit logging via EventLog, TradeJournal, PromotionLedger
```

Shared logic guarantees backtest/live parity (Inv-9). Never deploy
research code directly. Production code must be:

- Reviewed for correctness
- Tested against the five locked parity hashes
- Validated against backtest results (paper-window evidence in F-2)
- Promoted via the `AlphaLifecycle` SM (RESEARCH → PAPER → LIVE @
  SMALL_CAPITAL → LIVE @ SCALED) with structured evidence
- Monitored for divergence from expected behavior
