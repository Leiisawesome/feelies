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

All broker interaction is behind the `OrderRouter` protocol
(`execution/backend.py`), composed into `ExecutionBackend`:

```python
class OrderRouter(Protocol):
    def submit(self, request: OrderRequest) -> None: ...
    def poll_acks(self) -> list[OrderAck]: ...
```

Orders are submitted as `OrderRequest` events (`core/events.py`) with
deterministic `order_id` derived from `hashlib.sha256(correlation_id:sequence)`.
Fill responses arrive as `OrderAck` events carrying typed `OrderAckStatus`
(ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED).

Cancellation is initiated via `Orchestrator.cancel_order(order_id, reason=...)`
which transitions the order SM: ACKNOWLEDGED → CANCEL_REQUESTED.

Strategy and risk logic never call broker methods directly. Signals are
translated into `OrderIntent` via the `IntentTranslator` (see below),
then constructed into `OrderRequest` via `_build_order_from_intent()`.
The orchestrator mediates all order routing.

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

Every order carries a deterministic `order_id` derived via SHA-256:

```python
order_id = hashlib.sha256(f"{correlation_id}:{seq}".encode()).hexdigest()[:16]
```

This ensures replay of identical events produces identical order IDs
(invariant 5). The `SequenceGenerator` (`core/identifiers.py`) provides
the monotonic `seq`. uuid4 is forbidden in order ID generation.

- The deterministic ID serves as the idempotency key
- Duplicate submissions with the same order_id are detectable at the router level
- Order IDs are recorded in `TradeRecord` for audit

---

## Order State Machine

Every order follows the `OrderState` SM (`execution/order_state.py`).
No order exists outside these states. Each order gets its own
`StateMachine[OrderState]` instance tracked in the orchestrator's
`_active_orders` dict.

### States (9-state)

| State | Description | Terminal? |
|-------|-------------|-----------|
| `CREATED` | Order constructed, pending submission | No |
| `SUBMITTED` | Sent to broker via `OrderRouter.submit()` | No |
| `ACKNOWLEDGED` | Broker accepted; order is live | No |
| `PARTIALLY_FILLED` | One or more fills received; order still open | No |
| `FILLED` | Fully filled | Yes |
| `CANCEL_REQUESTED` | Cancel request via `Orchestrator.cancel_order()` | No |
| `CANCELLED` | Confirmed cancelled | Yes |
| `REJECTED` | Broker rejected | Yes |
| `EXPIRED` | TTL exceeded without fill | Yes |

Risk approval/rejection happens **before** order construction (at M5
`check_signal` and M6 `check_order`), not as order states. This keeps
the order SM focused on the broker lifecycle.

### Transition Table (`_ORDER_TRANSITIONS`)

```
CREATED         → {SUBMITTED}
SUBMITTED       → {ACKNOWLEDGED, REJECTED}
ACKNOWLEDGED    → {PARTIALLY_FILLED, FILLED, CANCEL_REQUESTED, EXPIRED}
PARTIALLY_FILLED → {PARTIALLY_FILLED, FILLED}
CANCEL_REQUESTED → {CANCELLED, FILLED}
FILLED / CANCELLED / REJECTED / EXPIRED → {} (terminal)
```

### Acknowledgment Handling

`_apply_ack_to_order()` maps typed `OrderAckStatus` enum members to
order SM transitions with exhaustive matching:

- **ACKNOWLEDGED**: SUBMITTED → ACKNOWLEDGED
- **REJECTED**: any → REJECTED (direct terminal)
- **FILLED**: ACKNOWLEDGED → FILLED (auto-acks SUBMITTED first if needed)
- **PARTIALLY_FILLED**: ACKNOWLEDGED → PARTIALLY_FILLED (emits alert if inapplicable)
- **CANCELLED**: CANCEL_REQUESTED → CANCELLED (emits alert if inapplicable)
- **EXPIRED**: ACKNOWLEDGED → EXPIRED (emits alert if inapplicable)
- **Unknown status**: raises `ValueError` (exhaustiveness guard)

Acks for unknown `order_id`s emit `ack_for_unknown_order` alert.
Fills for untracked orders are rejected with `fill_for_unknown_order` alert
(invariant 11: fail-safe prevents exposure increase from unknown orders).

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

The `KillSwitch` protocol (`monitoring/kill_switch.py`) provides:

```python
class KillSwitch(Protocol):
    @property
    def is_active(self) -> bool: ...
    def activate(self, reason: str, *, activated_by: str = "automated") -> None: ...
    def reset(self, *, operator: str, audit_token: str) -> None: ...
```

`reset()` re-enables trading after kill switch activation. Requires human
authorization; audit token is logged for provenance (invariant 13). Called
via `Orchestrator.unlock_from_lockdown(audit_token=...)` which additionally
enforces the zero-exposure guard before allowing `reset()`.

When activated:

1. `KillSwitchActivation` event is published on the bus
2. The orchestrator's tick-processing gate checks `is_active` at the
   top of every tick — if active, macro transitions to DEGRADED and
   the tick is skipped
3. The `_escalate_risk()` cascade activates the kill switch as part
   of the R0→R4 escalation sequence

Kill switch activation is **irreversible without manual intervention**.
Recovery requires `Orchestrator.unlock_from_lockdown(audit_token=...)`
with a zero-exposure guard.

| Trigger | Response |
|---------|----------|
| `_escalate_risk()` cascade (FORCE_FLATTEN) | R0→R4 escalation + kill switch + macro RISK_LOCKDOWN |
| Manual activation | Cancel all open orders; flatten positions |
| Unrecoverable system error | Cancel all open orders; freeze state |
| External signal (ops team) | Cancel all open orders; await manual re-enable |

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

### Intent Translation Layer

Between signal evaluation (M4) and risk check (M5), the orchestrator
runs two injectable components:

1. **`PositionSizer`** (`risk/position_sizer.py`) — computes target
   quantity from the alpha's risk budget, account equity, mid-price,
   signal strength, and regime state.
2. **`IntentTranslator`** (`execution/intent.py`) — maps
   `(signal direction × current position × target_quantity)` to a
   `TradingIntent` enum (`ENTRY_LONG`, `ENTRY_SHORT`, `EXIT`,
   `REVERSE_*`, `SCALE_UP`, `NO_ACTION`).

`NO_ACTION` causes the pipeline to skip from M4 directly to M10
(LOG_AND_METRICS) — before the risk check at M5. This is the path
taken for `FLAT` signals with no position, or when the signal agrees
with the current position and no scaling is needed.

Orders are constructed via `_build_order_from_intent(intent, verdict, cid)`
which derives `Side` from the `TradingIntent` enum, applies the risk
verdict's `scaling_factor`, and generates a deterministic `order_id`
via SHA-256.

### Shared Logic Enforcement

The micro-state pipeline (`MicroState` M0-M10 in `kernel/micro.py`) is
identical across all trading modes. The orchestrator's `_process_tick()`
method is the single code path — it never inspects `backend.mode`.

| Component | Shared Between Modes | Mode-Specific |
|-----------|---------------------|---------------|
| Signal generation | Yes | — |
| Feature computation | Yes | — |
| Intent translation + position sizing | Yes | — |
| Risk checks (`check_signal`, `check_order`) | Yes | — |
| Order construction (`_build_order_from_intent`) | Yes | — |
| Order routing | — | `OrderRouter`: fill simulator (backtest) / broker API (live) |
| Market data | — | `MarketDataSource`: replay (backtest) / live feed |
| Clock | — | `SimulatedClock` (backtest) / `WallClock` (live) |
| Position tracking | Yes (`PositionStore` protocol) | Implementation differs |

Code that diverges between modes must be behind `ExecutionBackend`
(`execution/backend.py`) and nowhere else. Any logic duplication is a bug.

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
| Backtest Engine (backtest-engine skill) | Shared `OrderRouter` protocol; fill model behind same interface |
| System Architect (system-architect skill) | `Clock`, `EventBus`, `ExecutionBackend`, `PositionStore` protocols |
| Risk Engine (risk-engine skill) | `RiskVerdict` with `RiskAction`; `_escalate_risk()` cascade |
| Microstructure Alpha (microstructure-alpha skill) | `Signal` events with `SignalDirection`; entry/exit logic |
| Data Engineering (data-engineering skill) | `NBBOQuote` / `Trade` events for reference pricing |

The live execution engine is a concrete `OrderRouter` implementation
(broker API adapter). It swaps in for the backtest fill simulator with
no changes to signal, feature, or risk logic — the orchestrator's
`_process_tick()` is identical in all modes.
