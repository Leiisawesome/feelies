# Safety Controls — Implementation Detail

Three independent safety mechanisms that operate at different severity levels.
Any mechanism can halt trading independently. They compose but never override
each other — the most restrictive state wins.

## Kill Switch

### Activation Triggers

| Trigger | Source | Auto/Manual |
|---------|--------|-------------|
| Manual button / API call | Ops team | Manual |
| Position reconciliation sign mismatch | Reconciliation engine | Auto |
| Unrecoverable gateway error | Broker gateway | Auto |
| Multiple orders in ERROR state (>= 3 within 1 min) | Order state machine | Auto |
| External halt signal | Upstream monitoring | Auto |

### Activation Sequence

```
1. Set global kill_switch_active = true (atomic)
2. Reject all new order-intent events at the bus
3. Cancel all open orders (best-effort, parallel)
4. Log all cancel results (success / failed / unknown)
5. If flatten_on_kill = true:
   a. Query broker positions
   b. Submit market orders to flatten all positions
   c. Wait for fill confirmation
6. Emit KILL_SWITCH_ACTIVATED event with full state snapshot
7. Persist kill switch state to durable storage
8. Block all further trading until manual re-enable
```

### Recovery

1. Ops team reviews cause of activation
2. Full position reconciliation performed
3. Order journal audited for consistency
4. Kill switch manually deactivated via authenticated API call
5. System enters `RECOVERING` mode:
   - Capital throttle set to 25%
   - Circuit breaker thresholds tightened 2x
   - Elevated monitoring for 30 minutes
6. Gradual return to normal operation

Kill switch state survives process restart. On startup, the system checks
for persisted kill switch state before accepting any orders.

---

## Circuit Breaker

### Trigger Conditions

| Metric | Threshold | Window | Cooldown |
|--------|-----------|--------|----------|
| Daily drawdown | > configured limit (e.g., 2% of capital) | Session | End of day |
| Intraday drawdown | > configured limit (e.g., 0.5% of capital) | Rolling 30 min | 15 min |
| Consecutive losses | >= 3 losing trades in a row | Sequential | 5 min |
| Fill rate collapse | < 50% of expected fill rate | Rolling 30 min | 10 min |
| Sustained latency spike | p95 > 2x baseline for 2+ minutes | Rolling 5 min | 5 min |
| Slippage blowout | Mean slippage > 5 bps (rolling 20 trades) | Rolling | 10 min |

### Activation Sequence

```
1. Set circuit_breaker_active = true
2. Record trigger reason, metrics, and timestamp
3. Cancel all open orders
4. DO NOT flatten existing positions (unlike kill switch)
5. Existing positions monitored via trailing stop-losses
6. Emit CIRCUIT_BREAKER_TRIPPED event
7. Start cooldown timer
```

### Cooldown & Resumption

```
During cooldown:
  - No new orders accepted
  - Position monitoring continues
  - Stop-losses remain active
  - Execution quality metrics continue streaming

On cooldown expiry:
  1. Re-evaluate trigger condition
  2. If condition resolved:
     a. Set circuit_breaker_active = false
     b. Capital throttle set to 50% for ramp-up period (5 min)
     c. Emit CIRCUIT_BREAKER_RESET event
     d. Resume normal trading with elevated monitoring
  3. If condition persists:
     a. Extend cooldown by 2x (exponential backoff)
     b. If extended 3 times, escalate to kill switch
```

### Per-Strategy vs Global

Circuit breakers exist at two levels:

| Level | Scope | Triggers | Effect |
|-------|-------|----------|--------|
| Strategy | Single strategy | Strategy-specific drawdown, fill rate | Halts that strategy only |
| Global | All strategies | Aggregate drawdown, system-wide latency | Halts all trading |

Global circuit breaker overrides all strategy-level breakers.

---

## Capital Throttle

### Health Signal Inputs

| Signal | Source | Update Frequency |
|--------|--------|-----------------|
| Slippage drift | Execution quality monitor | Per-fill |
| Latency health | Latency monitor | Per-order |
| Fill rate health | Fill rate monitor | Rolling window |
| Drawdown proximity | PnL tracker | Per-fill |
| Broker health | Gateway heartbeat | Every 5s |
| Data feed health | Market data ingestion | Every 5s |

### Throttle Computation

```
throttle_level = min(
  slippage_throttle(slippage_drift),
  latency_throttle(latency_p95),
  fill_rate_throttle(fill_rate_drift),
  drawdown_throttle(drawdown_proximity),
  broker_throttle(broker_health),
  feed_throttle(feed_health)
)
```

Each component function maps its input to [0.0, 1.0]:

| Function | Input Range -> Output |
|----------|----------------------|
| slippage_throttle | drift < 2bps -> 1.0; 2-5bps -> 0.75; 5-10bps -> 0.5; >10bps -> 0.0 |
| latency_throttle | p95 < 100ms -> 1.0; 100-300ms -> 0.75; 300-500ms -> 0.5; >500ms -> 0.0 |
| fill_rate_throttle | drift < 5% -> 1.0; 5-15% -> 0.75; 15-25% -> 0.5; >25% -> 0.0 |
| drawdown_throttle | < 50% of limit -> 1.0; 50-75% -> 0.75; 75-90% -> 0.5; >90% -> 0.0 |
| broker_throttle | healthy -> 1.0; degraded -> 0.5; unreachable -> 0.0 |
| feed_throttle | fresh -> 1.0; stale (>1s) -> 0.5; dead (>5s) -> 0.0 |

### Throttle Application

```
max_position_size = base_position_size * throttle_level
max_order_rate    = base_order_rate * throttle_level
max_notional      = base_notional * throttle_level
```

Throttle changes are:
- Applied immediately (no delay)
- Emitted as events on the bus
- Logged with all contributing health signals
- Never auto-increase faster than 25% per 5-minute window (ramp-up governor)

### Interaction with Circuit Breaker

- If throttle_level drops to 0.0, this is equivalent to a circuit breaker
- If circuit breaker is active, throttle is forced to 0.0
- On circuit breaker reset, throttle starts at 0.5 and ramps up

---

## Composition Rules

The three mechanisms compose via precedence:

```
if kill_switch_active:
  -> No trading. Flatten if configured. Manual recovery required.
elif circuit_breaker_active:
  -> No new orders. Existing positions monitored. Automatic recovery.
else:
  -> Trading allowed at throttle_level capacity.
```

State transitions between mechanisms:

| From | To | Trigger |
|------|-----|---------|
| Normal | Throttled | Any health signal degrades |
| Throttled | Circuit breaker | Throttle at 0% or explicit trigger |
| Circuit breaker | Kill switch | 3x cooldown extensions or explicit trigger |
| Kill switch | Recovering | Manual re-enable |
| Recovering | Normal | 30 min stable operation |

All safety state is persisted to durable storage and survives restarts.
On startup, the system resumes from persisted safety state — it never
assumes a clean start.
