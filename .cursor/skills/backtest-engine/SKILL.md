---
name: backtest-engine
description: >
  High-fidelity backtest engine architecture for event-driven replay of L1 NBBO
  data with realistic fill simulation, latency injection, and integrity enforcement.
  Use when designing backtest infrastructure, implementing fill models, building
  replay engines, modeling transaction costs, testing for lookahead bias, or
  reasoning about simulation realism, queue uncertainty, or execution feasibility.
---

# Backtest Engine — High-Fidelity Simulation

Event-driven replay engine that approximates live trading behavior as closely
as possible given L1-only data. Optimize for realism over speed — but quantify both.

## Core Invariants

Inherits platform invariants 5 (deterministic replay), 6 (causality), 9 (backtest/live parity),
12 (transaction cost realism). Causality is enforced in three specific forms:

1. **No future leakage** — event processing sees only past and present
2. **No lookahead bias** — features computed causally; no peeking at future quotes/trades
3. **No synchronous feature cheating** — features from event at time T not available until T + processing_latency

---

## Backtest Lifecycle

Backtest execution is driven by `Orchestrator.run_backtest()`:

1. Assert macro state is READY
2. Reset micro SM to M0 (`session_start:backtest`)
3. Transition macro: READY → BACKTEST_MODE (`CMD_BACKTEST`)
4. Run `_run_pipeline()` — iterates `backend.market_data.events()`
5. On success: BACKTEST_MODE → READY (`BACKTEST_COMPLETE`)
6. On exception: BACKTEST_MODE → DEGRADED (`BACKTEST_INTEGRITY_FAIL`)

The pipeline dispatches by event type: `NBBOQuote` drives the full
signal pipeline via `_process_tick()`; `Trade` events are logged and
published via `_process_trade()`.

Order IDs are deterministic — derived from
`hashlib.sha256(f"{correlation_id}:{seq}")`. This ensures two runs
with the same event log and parameters produce bit-identical signals,
orders, and PnL (invariant 5).

---

## Event Replay Engine

### Deterministic Ordering

All events merged into a single stream ordered by exchange timestamp.
Ties broken deterministically:

| Priority | Event Type | Rationale |
|----------|-----------|-----------|
| 1 | NBBO quote updates | Quotes establish available liquidity before trades print |
| 2 | Trades | Trades consume liquidity established by quotes |
| 3 | Internal events (signals, orders) | Reactions to market data, never ahead of it |

### Micro-Batching Rules

Events within the same exchange-timestamp nanosecond form a **micro-batch**:
- All events in a batch are visible simultaneously
- No internal ordering within a batch (treat as atomic)
- Feature updates triggered once per batch, not per event
- Configurable batch window (default: 0ns — strict timestamp ordering)

### Clock & Latency Injection

Backtest mode uses `SimulatedClock` (`core/clock.py`) — a deterministic clock
whose time only advances via explicit `set_time(ns)` calls. The clock
enforces monotonicity: `set_time(ns)` raises `ValueError` if `ns` is less
than the current time, preventing accidental backward movement.

```python
simulated_clock = exchange_timestamp + injected_latency
```

Latency injection is achieved by calling `set_time()` with the exchange
timestamp plus modeled delays between events — not by inserting explicit
sleeps into the pipeline.

```
injected_latency = data_feed_delay + processing_delay + broker_delay

data_feed_delay  ~ LogNormal(mu=3.0, sigma=0.5) [ms]
processing_delay ~ Deterministic(measured_compute_time)
broker_delay     ~ LogNormal(mu=2.0, sigma=0.8) [ms]
```

Configurable latency profiles:

| Profile | Use Case | Total Latency |
|---------|----------|---------------|
| Zero | Debugging, unit tests | 0ms |
| Optimistic | Best-case realistic | ~15ms |
| Realistic | Default simulation | ~30ms |
| Pessimistic | Stress testing | ~100ms+ |
| Stochastic | Monte Carlo runs | Sampled per-event |

Raw `datetime.now()` is forbidden in simulation code. All timestamps
flow through the `Clock` protocol (invariant 10).

---

## Order Types & Execution Logic

### Supported Order Types

| Order Type | Behavior |
|-----------|----------|
| Market buy | Fill at current ask + slippage |
| Market sell | Fill at current bid - slippage |
| Passive limit buy | Place at bid; fill via queue model |
| Passive limit sell | Place at ask; fill via queue model |
| Spread-crossing limit | Aggresses through NBBO; immediate fill with market-order slippage |
| Cancel | Remove pending limit order; subject to cancel latency |

### Order Lifecycle

Orders follow the same 9-state `OrderState` SM (`execution/order_state.py`)
as live trading. The orchestrator's `_process_tick()` is identical in
backtest and live modes — fill responses arrive as `OrderAck` events with
typed `OrderAckStatus` enum members.

```
Signal evaluated (M4)
  → Risk check (M5: check_signal → RiskVerdict)
    → Order constructed (M6: _build_order → OrderRequest)
      → Second risk check (M6: check_order → RiskVerdict)
        → Order submitted (M7: OrderRouter.submit())
          → Ack polled (M8: OrderRouter.poll_acks() → OrderAck[])
            → Position updated (M9: _reconcile_fills())
```

The backtest fill simulator is a concrete `OrderRouter` implementation
(NOT YET IMPLEMENTED). It must return `OrderAck` events with
`OrderAckStatus.FILLED`/`PARTIALLY_FILLED`/`REJECTED` plus `fill_price`
and `filled_quantity`. The orchestrator's `_apply_ack_to_order()` handles
the order SM transitions and `_reconcile_fills()` produces `PositionUpdate`
events and `TradeRecord` entries.

Between signal and acknowledgment, the NBBO may have moved.
The fill model uses the NBBO at acknowledgment time, not signal time.

### Spread Crossing Logic

When a limit order price crosses the opposite side of NBBO at submission:
- Treat as a marketable limit order
- Fill at the NBBO (not the limit price) plus slippage
- Remaining size (if any) rests as a passive limit at the limit price

---

## Fill Model

**NOT YET IMPLEMENTED** — the `OrderRouter` protocol (`execution/backend.py`)
is the implementation hook. A backtest fill simulator must implement
`OrderRouter.submit()` and `poll_acks()`, returning `OrderAck` events
with typed `OrderAckStatus` members.

Three-tier model with increasing realism. See [fill-model.md](fill-model.md) for
calibration methodology, parameter estimation, and adverse selection adjustment.

### Market Orders

```
fill_price = reference_price + direction * slippage(size, displayed_size, volatility)
```

Where `reference_price` is ask (buy) or bid (sell) at acknowledgment time.

### Passive Limit Orders

```
fill_probability = f(queue_position, time_in_queue, flow_direction, spread_regime)
```

Key assumptions:
- Queue position is **unobservable** from L1 — modeled probabilistically
- Fills are biased toward adverse outcomes (adverse selection)
- Fill probability decreases as spread widens (less aggressive flow reaches your level)

### Partial Fills

- Market orders: partial fill when `order_size > displayed_size_at_level`
- Limit orders: fill fraction drawn from Beta distribution calibrated to displayed size
- Remaining quantity either rests (limit) or sweeps next level (market)

---

## Transaction Cost Framework

| Component | Model |
|-----------|-------|
| Spread cost | Half-spread at fill time (realized, not quoted) |
| Slippage | f(order_size / displayed_size, volatility, spread_regime) |
| Market impact | Temporary: linear in participation rate; permanent: sqrt model |
| Commission | Explicit per-share fee schedule |
| Regulatory fees | SEC fee + FINRA TAF (per-trade) |
| Financing | Intraday carry cost for leveraged positions |

### Cost Aggregation

```
total_cost_bps = spread_cost + slippage + impact + commission + fees
round_trip_cost = entry_cost + exit_cost
```

Alpha must exceed round-trip cost by a margin. Minimum threshold:
`expected_edge_bps > 1.5 * round_trip_cost_bps`

---

## Integrity Enforcement

### Structural Safeguards (Built Into Architecture)

Several integrity properties are enforced structurally rather than via
post-hoc validation:

| Property | Enforcement Mechanism |
|----------|----------------------|
| Timestamp monotonicity | `SimulatedClock.set_time()` raises `ValueError` on backward movement |
| No illegal state transitions | `StateMachine` frozen transition table + `IllegalTransition` exception |
| Deterministic order IDs | SHA-256 from `correlation_id:sequence` (no uuid4) |
| No silent transitions | Every SM change emits `StateTransition` via `TransitionRecord` callback |
| Enum completeness | `StateMachine.__init__` validates every enum member has a transition entry |

### Anti-Leakage Checks

| Check | Enforcement |
|-------|------------|
| Causal ordering | Feature at time T uses only events with timestamp ≤ T (invariant 6) |
| Processing delay | Features not available until T + compute_time |
| No future NBBO | Order decisions use last-known NBBO, not next |
| No batch peeking | Within micro-batch, no cross-event dependencies |
| Timestamp monotonicity | `SimulatedClock` backward-movement guard |

### Automated Validation

Run these checks on every backtest:
1. **Timestamp audit** — verify no feature depends on future timestamps
2. **Fill audit** — verify no fill occurs before order acknowledgment time
3. **PnL reconciliation** — verify position changes match fill records exactly
4. **Determinism check** — two runs with same seed produce identical output (SHA-256 IDs guarantee this structurally)
5. **Latency budget check** — log if any event processing exceeds pipeline budget

---

## Stress Testing & Sensitivity

See [stress-testing.md](stress-testing.md) for full protocols.

### Data Perturbation

| Perturbation | Purpose | Default Level |
|-------------|---------|---------------|
| Timestamp jitter | Model clock uncertainty | ±5ms uniform |
| Duplicate events | Test dedup robustness | 0.1% of events |
| Dropped events | Test gap handling | 0.05% of events |
| Stale quotes | Test staleness detection | Hold NBBO frozen 500ms |
| Price spikes | Test outlier filtering | ±5% instantaneous |

### Parameter Sensitivity

Vary each parameter independently and report PnL impact:
- Latency: 0ms → 200ms in 10ms steps
- Fill probability: 0.1 → 1.0
- Slippage multiplier: 0.5x → 3.0x
- Queue position assumption: front → back of queue

### Realism Metrics

Quantify simulation fidelity:

| Metric | Definition |
|--------|-----------|
| Fill rate realism | Backtest fill rate vs historical realized fill rate |
| Slippage realism | Backtest slippage distribution vs production slippage |
| Latency realism | Injected latency distribution vs measured production latency |
| PnL compression ratio | Live PnL / backtest PnL (target: 0.6–0.8) |

If PnL compression ratio < 0.5, the backtest is unrealistically optimistic.
Diagnose whether fill model, latency model, or cost model is the source.

---

## Performance Budget

Realism over speed — but measure both.

| Operation | Target | Acceptable |
|-----------|--------|------------|
| Single event replay | < 10 μs | < 100 μs |
| Full day replay (1 ticker) | < 30s | < 120s |
| Full day replay (100 tickers) | < 10min | < 30min |
| Monte Carlo (100 latency seeds, 1 day) | < 1hr | < 4hr |

If performance targets are not met, profile before optimizing.
Never sacrifice fill model fidelity for replay speed.

---

## Output Specification

Backtest output flows through the existing event and storage types:

| Output | Type | Source |
|--------|------|--------|
| Trade lifecycle records | `TradeRecord` (`storage/trade_journal.py`) | `_reconcile_fills()` writes to `TradeJournal` |
| Position changes | `PositionUpdate` (`core/events.py`) | Published on bus at M9 |
| State machine audit trail | `StateTransition` (`core/events.py`) | Every SM transition emitted via bus |
| Tick latency | `MetricEvent` (`core/events.py`) | `tick_to_decision_latency_ns` histogram per tick |
| Alerts | `Alert` (`core/events.py`) | Safety events, fill anomalies |

Aggregated run summaries (PnL curve, integrity checks, realism metrics)
are NOT YET IMPLEMENTED as a structured output format. When built, they
should aggregate from the typed events above:

```
{
  "run_id": str (deterministic hash of config + data),
  "config": { latency_profile, fill_model, cost_model, ... },
  "trades": [ TradeRecord... ],
  "positions": [ PositionUpdate... ],
  "state_transitions": [ StateTransition... ],
  "integrity_checks": { causal_ok, determinism_ok, reconciliation_ok },
  "realism_metrics": { fill_rate, slippage_dist, pnl_compression }
}
```

---

## Integration Points

| Upstream Dependency | Interface |
|--------------------|-----------|
| Data Engineering (data-engineering skill) | `NBBOQuote` / `Trade` events from `MarketDataSource.events()` |
| System Architect (system-architect skill) | `SimulatedClock`, `EventBus`, `ExecutionBackend`, micro-state pipeline |
| Feature Engine (feature-engine skill) | `FeatureEngine.update(quote) -> FeatureVector`; snapshot persistence via `FeatureSnapshotStore` |
| Risk Engine (risk-engine skill) | `RiskEngine.check_signal()` / `check_order()` returning `RiskVerdict` |
| Microstructure Alpha (microstructure-alpha skill) | `Signal` events with `SignalDirection`; research protocol |

The backtest engine is a concrete `MarketDataSource` + `OrderRouter`
implementation composed into `ExecutionBackend`. It swaps in for the
live execution layer with no changes to signal, feature, or risk logic
— the orchestrator's `_process_tick()` is identical in all modes.
