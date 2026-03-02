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

Inherits platform invariants 5 (deterministic replay), 6 (causality), 9 (backtest/live parity).
Causality is enforced in three specific forms:

1. **No future leakage** — event processing sees only past and present
2. **No lookahead bias** — features computed causally; no peeking at future quotes/trades
3. **No synchronous feature cheating** — features from event at time T not available until T + processing_latency

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

```
simulated_clock = exchange_timestamp + injected_latency

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

All latency injection uses the injectable clock from the system-architect layer.
Raw `datetime.now()` is forbidden in simulation code.

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

```
Signal emitted (T)
  → Order created (T + processing_delay)
    → Order submitted (T + processing_delay + broker_delay)
      → Order acknowledged (T + total_latency)
        → Fill / partial fill / timeout / cancel
```

Between signal and acknowledgment, the NBBO may have moved.
The fill model uses the NBBO at acknowledgment time, not signal time.

### Spread Crossing Logic

When a limit order price crosses the opposite side of NBBO at submission:
- Treat as a marketable limit order
- Fill at the NBBO (not the limit price) plus slippage
- Remaining size (if any) rests as a passive limit at the limit price

---

## Fill Model

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

### Anti-Leakage Checks

| Check | Enforcement |
|-------|------------|
| Causal ordering | Feature at time T uses only events with timestamp ≤ T |
| Processing delay | Features not available until T + compute_time |
| No future NBBO | Order decisions use last-known NBBO, not next |
| No batch peeking | Within micro-batch, no cross-event dependencies |
| Timestamp monotonicity | Simulated clock never moves backward |

### Automated Validation

Run these checks on every backtest:
1. **Timestamp audit** — verify no feature depends on future timestamps
2. **Fill audit** — verify no fill occurs before order acknowledgment time
3. **PnL reconciliation** — verify position changes match fill records exactly
4. **Determinism check** — two runs with same seed produce identical output
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

Every backtest run produces:

```
{
  "run_id": str (deterministic hash of config + data),
  "config": { latency_profile, fill_model, cost_model, ... },
  "trades": [ { timestamp, ticker, side, size, fill_price, slippage, fees, latency } ],
  "positions": [ { timestamp, ticker, quantity, avg_price, unrealized_pnl } ],
  "pnl_curve": [ { timestamp, realized, unrealized, gross, net } ],
  "integrity_checks": { causal_ok, determinism_ok, reconciliation_ok },
  "realism_metrics": { fill_rate, slippage_dist, pnl_compression },
  "sensitivity": { param: impact_bps for each varied parameter }
}
```

---

## Integration Points

| Upstream Dependency | Interface |
|--------------------|-----------|
| Data Engineering (data-engineering skill) | Normalized event stream, partitioned Parquet |
| System Architect (system-architect skill) | Clock abstraction, event bus, layer boundaries |
| Feature Engine (feature-engine skill) | Stateful feature computation; deterministic replay of feature snapshots |
| Microstructure Alpha (microstructure-alpha skill) | Signal definitions, research protocol |

The backtest engine is the execution layer in backtest mode.
It must be swappable with the live execution layer with no changes to
signal, feature, or risk logic.
