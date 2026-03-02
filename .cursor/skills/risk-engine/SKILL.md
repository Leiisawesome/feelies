---
name: risk-engine
description: >
  Risk control layer and portfolio governor for real-time position limits, exposure
  management, drawdown enforcement, regime detection, and PnL attribution. Use when
  designing risk constraints, implementing drawdown gates, building volatility-adjusted
  sizing, detecting regime shifts or concentration risk, defining hedge overlays,
  emergency de-leveraging, or reasoning about fail-safe guarantees, PnL decomposition,
  or risk budget allocation.
---

# Risk Engine & Portfolio Governor

The risk engine is the sole gatekeeper between signal and execution. Every order
intent passes through it — no module bypasses risk checks. The system defaults to
safe: unknown states, missing data, and unhandled conditions all resolve to
position reduction or trading halt, never to increased exposure.

## Core Invariants

Inherits platform invariants 5 (deterministic replay), 11 (fail-safe default + monotonic safety).
Additionally:

1. **No bypass** — every order intent transits the risk engine; no direct signal-to-execution path exists
2. **Pre-trade and post-trade** — constraints enforced before order submission and validated after fill
3. **Independent authority** — risk engine can halt trading unilaterally; no other layer can override

---

## Real-Time Risk Constraints

### Position Limits

| Constraint | Scope | Default | Enforcement |
|------------|-------|---------|-------------|
| Max shares per symbol | Per-symbol | Configurable per ticker | Reject order if post-fill position exceeds limit |
| Max notional per symbol | Per-symbol | % of NAV (configurable) | Reject based on mark-to-market notional |
| Max symbols held | Portfolio | Configurable | Reject new-name orders when at capacity |
| Max position as % of ADV | Per-symbol | 1% of 20-day ADV | Prevent outsized participation |

### Exposure Limits

| Constraint | Definition | Default | Action on Breach |
|------------|-----------|---------|------------------|
| Max gross exposure | Sum of |long| + |short| notional / NAV | Configurable | Block new orders; begin unwinding if sustained |
| Max net exposure | (long - short) notional / NAV | Configurable | Block directional orders that increase |
| Max sector exposure | Gross notional in any single sector / NAV | Configurable | Block same-sector orders |
| Max single-name concentration | Single position notional / gross notional | 20% | Reject orders increasing concentration |

### Drawdown Gates

| Level | Trigger | Response |
|-------|---------|----------|
| Warning | Intraday PnL < -0.5% NAV | Log alert; tighten position sizing to 50% |
| Throttle | Intraday PnL < -1.0% NAV | Cancel open orders; reduce position sizing to 25%; no new positions |
| Circuit breaker | Intraday PnL < -1.5% NAV | Cancel all orders; no new trades; existing positions monitored with stops |
| Kill switch | Intraday PnL < -2.0% NAV | Flatten all positions; halt trading for the day |

Drawdown levels are configurable. PnL measured mark-to-market using last NBBO mid.
Thresholds checked on every quote update and every fill event.

**Ownership boundary**: Drawdown gates define the policy (thresholds and
responses). The live-execution skill owns the safety mechanisms (kill switch,
circuit breaker, capital throttle) that enforce these policies at the order
routing level.

### Volatility-Adjusted Sizing

```
target_risk_per_trade = risk_budget_bps * NAV
position_size = target_risk_per_trade / (realized_vol * vol_scalar)
position_size = min(position_size, max_position_limit, adv_limit)
```

| Parameter | Source | Update Frequency |
|-----------|--------|-----------------|
| Realized volatility | Rolling intraday (configurable window) | Every quote update |
| Vol scalar | Regime-dependent multiplier (see Regime Detection) | On regime transition |
| Risk budget | Per-strategy allocation from portfolio governor | Daily or on rebalance |

Position size scales inversely with volatility. In elevated-vol regimes, sizes
shrink automatically without manual intervention.

---

## Regime Detection

The risk engine maintains regime classifiers that feed into sizing, exposure
limits, and safety controls.

**Ownership boundary**: The microstructure-alpha skill defines the regime
taxonomy (what regimes exist and their structural meaning). This skill owns
real-time detection and the risk response to regime transitions. The
post-trade-forensics skill audits whether regime classification remains
accurate and whether strategy performance is stable across regimes. When
forensic and risk-engine regime labels diverge, use the more conservative
classification and alert.

### Volatility Regime

| Regime | Detection | Risk Response |
|--------|-----------|---------------|
| Low | Realized vol < 20th percentile of lookback | Normal sizing; full allocation |
| Normal | 20th–80th percentile | Normal sizing |
| Elevated | 80th–95th percentile | Reduce sizing to 50%; widen stops |
| Crisis | > 95th percentile or vol spike > 3x rolling mean | Reduce sizing to 25%; activate circuit breaker evaluation |

Detection via exponentially weighted realized volatility with regime persistence
filter (minimum dwell time before transition, configurable).

### Correlation Clustering

Monitor rolling pairwise correlations across held positions:

| Condition | Detection | Response |
|-----------|-----------|----------|
| Correlation spike | Mean pairwise corr > threshold (e.g., 0.7) | Reduce gross exposure; alert |
| Directional clustering | > 80% of positions same-sign beta | Flag concentration; enforce net exposure limit |
| Correlation breakdown | Historical stable correlations diverge | Re-evaluate hedges; alert for manual review |

Correlation estimated from intraday returns (5-min windows, rolling).
Not raw price correlation — use returns to avoid spurious level effects.

### Concentration Risk

| Metric | Threshold | Action |
|--------|-----------|--------|
| Herfindahl index (notional) | > 0.25 | Alert; block further concentration |
| Top-3 position weight | > 60% of gross | Reduce or block |
| Sector Herfindahl | > 0.35 | Alert; enforce sector caps |

---

## Risk-Neutral Overlays

### Beta Hedge Logic

Maintain portfolio beta within target band:

```
portfolio_beta = sum(position_i * beta_i) / NAV
hedge_needed   = (portfolio_beta - target_beta) * NAV
hedge_instrument = configurable (index ETF, futures proxy)
```

| Parameter | Default | Notes |
|-----------|---------|-------|
| Target beta | 0.0 (market-neutral) | Configurable per strategy |
| Rebalance trigger | |portfolio_beta - target| > tolerance | Tolerance configurable |
| Hedge instrument | SPY / sector ETFs | Configurable; must be liquid |
| Beta estimation | Rolling OLS, intraday 5-min returns | Window configurable |

Hedge orders route through the same risk engine — they are not exempt from
position limits or exposure checks.

### Dynamic Exposure Scaling

Total exposure scales based on regime and system health:

```
effective_allocation = base_allocation * regime_scalar * health_scalar * drawdown_scalar

regime_scalar   = f(volatility_regime)     # 1.0 normal, 0.5 elevated, 0.25 crisis
health_scalar   = f(execution_quality)     # from live-execution monitoring
drawdown_scalar = f(intraday_pnl_vs_limit) # linear ramp from 1.0 to 0.0
```

Scalars multiply — compounding reduces exposure aggressively when multiple
risk signals fire simultaneously.

### Emergency De-Leveraging Protocol

Triggered when multiple risk signals fire concurrently or a single critical
breach occurs.

| Phase | Trigger | Action | Duration |
|-------|---------|--------|----------|
| 1 — Reduce | 2+ warning-level signals | Cut new order sizes by 50% | Until signals clear |
| 2 — Defensive | Any throttle-level + elevated vol | Cancel all open orders; reduce positions to 50% | Until regime normalizes |
| 3 — Flatten | Kill switch trigger or 3+ throttle signals | Market-order flatten all positions | Immediate; irreversible without manual restart |

Flattening order:
1. Cancel all open orders (wait for confirmations)
2. Submit market orders to close each position
3. Verify flat via broker reconciliation
4. Enter halted state — no automated re-entry

---

## Real-Time PnL Decomposition

### PnL Components

Track continuously, updated on every fill and quote:

| Component | Definition |
|-----------|-----------|
| Gross PnL | Mark-to-market change in portfolio value |
| Realized PnL | Closed-trade profit/loss |
| Unrealized PnL | Open-position mark-to-market |
| Transaction costs | Commissions + fees (realized) |
| Slippage cost | Fill price vs reference price at signal time |
| Net PnL | Gross - transaction costs - slippage |

### Attribution

Decompose returns into sources:

| Attribution | Calculation | Purpose |
|-------------|------------|---------|
| Alpha | Residual return after removing beta exposure | Measure signal quality |
| Beta | Portfolio beta * market return | Measure market exposure contribution |
| Slippage | Realized fill vs backtest-expected fill | Measure execution quality |
| Spread cost | Half-spread paid on entry + exit | Measure liquidity cost |
| Timing | Return from signal time to fill time | Measure latency cost |

```
total_return = alpha + beta_return + slippage + spread_cost + timing_cost + fees
```

Attribution computed per-trade and aggregated at strategy and portfolio level.
Rolling windows (1hr, session, daily) maintained for monitoring dashboards.

### Reconciliation

| Check | Frequency | Action on Failure |
|-------|-----------|-------------------|
| PnL vs position * price change | Every quote update | Alert; re-derive from fills |
| Sum of attributed components = total PnL | Every trade | Alert; flag attribution model |
| Internal PnL vs broker statement | End of day | Investigate discrepancy; broker is authoritative |

---

## Risk Budget Allocation

### Per-Strategy Budgets

Each strategy receives an independent risk allocation:

| Parameter | Scope | Purpose |
|-----------|-------|---------|
| Max drawdown | Per-strategy | Independent kill switch per strategy |
| Capital allocation | Per-strategy | Fraction of NAV available |
| Position limit | Per-strategy per-symbol | Prevent single strategy from monopolizing a name |
| Correlation budget | Cross-strategy | Limit aggregate correlated exposure |

### Portfolio-Level Governor

The portfolio governor enforces aggregate constraints that no single strategy
can evaluate alone:

- Total gross exposure across all strategies
- Total drawdown across all strategies (diversified)
- Net beta exposure across all strategies
- Aggregate concentration across all strategies holding the same name

If aggregate constraints bind, the governor reduces the most recently submitted
order first (LIFO priority for risk reduction).

---

## Event Interface

All risk decisions emit typed events onto the event bus:

| Event | Payload |
|-------|---------|
| `RISK_CHECK_PASSED` | order_id, checks_performed, margins_remaining |
| `RISK_CHECK_REJECTED` | order_id, violated_constraint, current_value, limit_value |
| `REGIME_TRANSITION` | old_regime, new_regime, detection_method, timestamp |
| `DRAWDOWN_ALERT` | level, current_pnl, threshold, response_taken |
| `EXPOSURE_BREACH` | metric, current_value, limit, action_taken |
| `DELEVERAGE_INITIATED` | phase, trigger_reasons, target_exposure |
| `PNL_SNAPSHOT` | gross, net, alpha, beta, slippage, by_strategy |
| `HEDGE_REBALANCE` | current_beta, target_beta, hedge_size, instrument |

Every event carries a timestamp from the injectable clock (never raw `datetime.now()`).

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Stale NBBO (no update > threshold) | Heartbeat monitor on quote stream | Use last-known price; flag stale; block new orders if sustained |
| Risk engine crash | Watchdog process; heartbeat | Kill switch activates; no orders can route without risk engine |
| PnL calculation error | Reconciliation check fails | Halt new orders; re-derive PnL from fill log |
| Regime model divergence | Backtest vs live regime disagreement | Alert; use more conservative regime classification |
| Clock desync | Clock drift detection | Use more conservative (earlier) timestamp; alert |

The risk engine is a **hard dependency** for order flow. If it is unavailable,
the system cannot trade. This is by design.

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| System Architect (system-architect skill) | Clock abstraction, event bus, layer boundaries |
| Live Execution (live-execution skill) | Order routing gate; safety controls coordination; execution quality health signal |
| Backtest Engine (backtest-engine skill) | Shared risk check logic; deterministic replay of risk decisions |
| Microstructure Alpha (microstructure-alpha skill) | Signal regime awareness; entry/exit conditions; volatility features |
| Data Engineering (data-engineering skill) | Real-time NBBO feed for mark-to-market, vol estimation, regime detection |

The risk engine sits between signal and execution in both backtest and live modes.
Same risk logic, same constraints, same fail-safe behavior. Mode-specific
differences (e.g., broker reconciliation in live vs simulated reconciliation in
backtest) are behind the `ExecutionBackend` interface.
