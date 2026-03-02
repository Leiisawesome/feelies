---
name: live-execution
description: >
  Live execution architecture for transforming signals into safe, latency-aware
  trades with order routing, state machine lifecycle, idempotency, and safety
  controls. Use when designing live order execution, implementing broker
  integration, building kill switches or circuit breakers, reasoning about
  backtest/live parity, or monitoring execution quality drift.
---

# Live Execution Architect

Transform signals into safe, latency-aware live trades. Every component must
enforce behavioral equivalence with the backtest engine — structural drift
between simulated and live execution is a system failure.

## Core Invariants

Inherits platform invariants 9 (backtest/live parity), 11 (fail-safe default).
Additionally:

1. **Idempotent order submission** — duplicate signals never produce duplicate orders
2. **Explicit state transitions** — every order follows a defined state machine; no implicit states
3. **Reconciliation as ground truth** — broker position is authoritative; internal state reconciles to it

---

## Order Routing Interface

### Broker Abstraction

All broker interaction behind a single interface:

```
BrokerGateway:
  submit_order(order: Order) -> OrderAck | OrderReject
  cancel_order(order_id: str) -> CancelAck | CancelReject
  modify_order(order_id: str, changes: Modification) -> ModifyAck | ModifyReject
  query_position(symbol: str) -> Position
  query_order_status(order_id: str) -> OrderStatus
  subscribe_executions() -> Stream[ExecutionReport]
```

The gateway emits typed events onto the event bus. Strategy and risk logic
never call broker methods directly — they emit order-intent events.

### Routing Rules

| Condition | Action |
|-----------|--------|
| Risk engine approves | Route to broker gateway |
| Risk engine rejects | Log rejection reason; notify monitoring |
| Gateway timeout | Enter retry loop with backoff |
| Gateway reject | Classify reject reason; retry if transient, abort if permanent |
| Duplicate order_id detected | Drop silently; log idempotency catch |

---

## Retry, Timeout & Idempotency

### Retry Logic

| Failure Class | Strategy | Max Attempts | Backoff |
|---------------|----------|--------------|---------|
| Transient (network, 5xx) | Retry with exponential backoff | 3 | 100ms, 500ms, 2s |
| Rate limit (429) | Retry after `Retry-After` header | 5 | Server-specified |
| Permanent (4xx, invalid order) | Abort immediately | 0 | — |
| Unknown | Treat as transient for 1 retry, then abort | 1 | 500ms |

### Timeout Logic

| Operation | Timeout | On Expiry |
|-----------|---------|-----------|
| Order submission | 5s | Cancel attempt + reconcile |
| Cancel request | 3s | Re-query status; escalate if still open |
| Position query | 2s | Use last-known position; flag stale |
| Execution stream heartbeat | 10s | Reconnect; reconcile all open orders |

### Idempotency

Every order carries a client-generated idempotency key:

```
idempotency_key = hash(signal_id, symbol, side, size, timestamp_bucket)
```

- The gateway deduplicates on this key within a configurable window (default: 60s)
- If a submission times out and is retried, the same key prevents double-fill
- Idempotency keys are persisted in the order journal for audit

---

## Order State Machine

Every order follows an explicit finite state machine. No order exists outside
these states. See [order-lifecycle.md](order-lifecycle.md) for transition
diagrams, edge cases, and timeout escalation paths.

### States

| State | Description |
|-------|-------------|
| `CREATED` | Order constructed, pending risk check |
| `RISK_APPROVED` | Passed risk engine; queued for submission |
| `RISK_REJECTED` | Rejected by risk engine; terminal |
| `SUBMITTED` | Sent to broker; awaiting acknowledgment |
| `ACKNOWLEDGED` | Broker accepted; order is live |
| `PARTIALLY_FILLED` | One or more fills received; order still open |
| `FILLED` | Fully filled; terminal |
| `CANCEL_PENDING` | Cancel request sent; awaiting confirmation |
| `CANCELLED` | Confirmed cancelled; terminal |
| `REJECTED` | Broker rejected; terminal |
| `EXPIRED` | TTL exceeded without fill; terminal |
| `ERROR` | Unrecoverable error; requires manual review |

### Transition Rules

- Only forward transitions allowed (no `FILLED` -> `SUBMITTED`)
- `SUBMITTED` without `ACKNOWLEDGED` within timeout -> `CANCEL_PENDING`
- `CANCEL_PENDING` without `CANCELLED` within timeout -> `ERROR` + reconcile
- Every transition emits an event on the bus with timestamp and reason
- `ERROR` state triggers monitoring alert and position reconciliation

### Acknowledgment Handling

- **Ack received**: transition `SUBMITTED` -> `ACKNOWLEDGED`, record broker order ID
- **Ack not received within timeout**: assume submission may have succeeded; query order status before retrying
- **Late ack** (after timeout-triggered cancel): reconcile — if order is live, re-enter cancel flow
- **Duplicate ack**: idempotent; log but do not re-process

---

## Position Reconciliation

### Reconciliation Protocol

| Trigger | Action |
|---------|--------|
| Every fill event | Reconcile internal position vs running fill tally |
| Every 30s (configurable) | Query broker positions; diff against internal state |
| On reconnect | Full position snapshot from broker; hard-reconcile |
| On `ERROR` state entry | Immediate position query and reconciliation |
| Pre-market open | Zero-position assertion (for intraday-only strategies) |

### Discrepancy Handling

| Discrepancy Type | Severity | Response |
|------------------|----------|----------|
| Internal > broker (phantom position) | Critical | Reduce internal to broker; investigate |
| Broker > internal (missed fill) | Critical | Adopt broker position; replay execution reports |
| Sign mismatch (long vs short) | Emergency | Halt trading; manual review |
| Size within tolerance (< 1 share) | Warning | Log; auto-correct on next reconciliation |

Broker position is always authoritative. Internal state is a performance
optimization — it must never override broker ground truth.

---

## Execution Quality Monitoring

Real-time monitoring of execution quality. Drift from expectations triggers
alerts and can activate safety controls.

**Ownership boundary**: This skill monitors slippage, latency, and fill rate
in real-time over short windows (20 trades, 30 min) and triggers immediate
safety responses. The post-trade-forensics skill consumes the same metrics
over longer windows (50–200 trades, multi-day) to detect structural edge
decay, crowding, and alpha erosion — forensic conclusions, not operational
alerts.

### Slippage Monitoring

```
realized_slippage = fill_price - reference_price_at_signal_time
expected_slippage = backtest_slippage_model(size, spread, volatility)
slippage_drift    = realized_slippage - expected_slippage
```

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Mean slippage drift (rolling 20 trades) | > 2 bps | Warning; log |
| Mean slippage drift (rolling 20 trades) | > 5 bps | Reduce position sizes 50% |
| Single-trade slippage | > 10 bps | Flag for review |
| Systematic slippage bias (one direction) | p < 0.05 | Investigate adverse selection |

### Latency Monitoring

| Metric | Expected | Alert |
|--------|----------|-------|
| Signal-to-submission | < 5ms | > 20ms |
| Submission-to-ack | < 50ms | > 200ms |
| Ack-to-fill (market orders) | < 100ms | > 500ms |
| End-to-end (signal-to-fill) | < 150ms | > 500ms |

Latency distributions logged as histograms (p50, p95, p99).
Regime shifts in latency distribution trigger review.

### Fill Rate Monitoring

```
expected_fill_rate = backtest_fill_model.predicted_rate(order_type, spread_regime)
realized_fill_rate = fills / submissions  (rolling window)
fill_rate_drift    = realized - expected
```

| Condition | Action |
|-----------|--------|
| Fill rate drift > 10% for 1 hour | Warning |
| Fill rate drift > 20% for 1 hour | Reduce passive order usage |
| Fill rate < 50% of expected for 30 min | Activate circuit breaker |

---

## Safety Controls

Three independent safety mechanisms. Any one can halt trading independently.
See [safety-controls.md](safety-controls.md) for implementation details,
configuration, and recovery procedures.

**Ownership boundary**: This skill owns the mechanisms (kill switch, circuit
breaker, capital throttle). The risk-engine skill defines the policies
(drawdown thresholds, exposure limits) that trigger these mechanisms. The
risk engine emits events; this layer enforces them.

### Kill Switch

Immediate cessation of all trading activity.

| Trigger | Response |
|---------|----------|
| Manual activation | Cancel all open orders; flatten positions |
| Unrecoverable system error | Cancel all open orders; freeze state |
| Position reconciliation emergency | Cancel all open orders; freeze for manual review |
| External signal (ops team) | Cancel all open orders; await manual re-enable |

Kill switch activation is **irreversible without manual intervention**.
The system cannot self-recover from a kill switch.

### Circuit Breaker

Temporary trading halt with automatic evaluation for resumption.

| Trigger | Cooldown | Resume Condition |
|---------|----------|------------------|
| Drawdown > daily limit | End of day | Next trading day; manual review |
| Drawdown > intraday threshold | 15 min | Drawdown recovers; volatility normalizes |
| Fill rate collapse | 10 min | Fill rate returns to expected range |
| Latency spike (sustained) | 5 min | Latency returns to p95 baseline |
| Rapid loss sequence (3+ consecutive) | 5 min | Cool-off period expires |

Circuit breaker cancels all open orders but does **not** flatten positions
(unlike kill switch). Existing positions are monitored via stop-losses.

### Capital Throttle

Dynamic position sizing based on system health.

| Health Signal | Throttle Level | Max Position Size |
|---------------|---------------|-------------------|
| All nominal | 100% | Full allocation |
| Elevated slippage | 75% | 75% of normal |
| Elevated latency | 50% | 50% of normal |
| Degraded fill rate | 50% | 50% of normal |
| Multiple degraded signals | 25% | 25% of normal |
| Any critical alert | 0% | No new positions |

Throttle level is the minimum across all health signals.
Throttle changes emit events on the bus for strategy-layer awareness.

---

## Backtest/Live Parity Enforcement

Structural drift between backtest assumptions and live behavior is a
first-class failure mode.

### Parity Metrics

| Metric | Backtest Source | Live Source | Drift Threshold |
|--------|---------------|-------------|-----------------|
| Fill rate | Fill model prediction | Realized fills | > 15% relative |
| Slippage | Slippage model | Realized slippage | > 3 bps mean |
| Latency profile | Injected latency dist | Measured latency dist | KS test p < 0.05 |
| PnL compression | Backtest PnL | Live PnL (same period) | Ratio < 0.5 |
| Order rejection rate | Simulated (near 0) | Broker rejections | > 5% of submissions |

### Drift Response Protocol

1. **Detect** — continuous comparison of live metrics vs backtest assumptions
2. **Alert** — surface drift metric, magnitude, and affected strategy
3. **Diagnose** — determine if drift is from fill model, latency model, cost model, or market regime
4. **Adapt** — if regime change: update backtest parameters. If model error: fix model.
5. **Halt** — if drift is unexplained or large: activate circuit breaker until resolved

### Shared Logic Enforcement

| Component | Shared Between Modes | Mode-Specific |
|-----------|---------------------|---------------|
| Signal generation | Yes | — |
| Feature computation | Yes | — |
| Risk checks | Yes | — |
| Order construction | Yes | — |
| Order routing | — | Backtest: fill simulator / Live: broker gateway |
| Clock | — | Backtest: simulated / Live: wall clock |
| Position tracking | Yes (interface) | State source differs |

Code that diverges between modes must be behind the `ExecutionBackend`
interface and nowhere else. Any logic duplication is a bug.

---

## Output Specification

Live execution produces a continuous stream of:

```
{
  "order_journal": [ { order_id, idempotency_key, state_transitions[], fills[], timestamps } ],
  "position_snapshots": [ { timestamp, symbol, quantity, avg_price, broker_confirmed } ],
  "execution_quality": {
    "slippage": { mean, p50, p95, drift_from_backtest },
    "latency": { signal_to_fill: { p50, p95, p99 } },
    "fill_rate": { by_order_type, drift_from_backtest }
  },
  "safety_state": { kill_switch, circuit_breaker, throttle_level, active_alerts[] },
  "parity_report": { metric: { backtest_value, live_value, drift, alert_level } }
}
```

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Backtest Engine (backtest-engine skill) | Shared order construction, fill model assumptions, cost framework |
| System Architect (system-architect skill) | Clock abstraction, event bus, layer boundaries, `ExecutionBackend` interface |
| Microstructure Alpha (microstructure-alpha skill) | Signal definitions, entry/exit logic, regime awareness |
| Data Engineering (data-engineering skill) | Real-time NBBO feed for reference pricing and spread regime detection |

The live execution engine is the execution layer in live mode.
It swaps in for the backtest fill simulator with no changes to signal,
feature, or risk logic.
