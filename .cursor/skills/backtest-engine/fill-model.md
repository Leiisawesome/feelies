# Fill Model — Calibration & Assumptions

> **NOT YET IMPLEMENTED** — The fill model is a design target. The
> implementation hook is the `OrderRouter` protocol (`execution/backend.py`).
> A backtest-mode `OrderRouter` receives `Order` events and returns
> `OrderAck` events with typed `OrderAckStatus` (ACKNOWLEDGED,
> PARTIALLY_FILLED, FILLED, REJECTED). Fill model logic lives inside
> the `OrderRouter` implementation, keeping it decoupled from the
> core pipeline.

## Model Hierarchy

Three tiers of fill realism. Default to Tier 2 unless explicitly choosing otherwise.

| Tier | Description | Use Case |
|------|------------|----------|
| 1 — Naive | Immediate fill at NBBO | Rapid prototyping only; never for final results |
| 2 — Realistic | Queue model + slippage + adverse selection | Default for all research |
| 3 — Conservative | Tier 2 + pessimistic queue + increased impact | Deployment readiness check |

Strategies that are profitable only under Tier 1 are rejected.
Strategies deployed only if profitable under Tier 3.

---

## Market Order Fill Model

### Slippage Function

```
slippage(size, displayed_size, sigma) =
    base_spread_fraction
    + size_impact(size / displayed_size)
    + volatility_impact(sigma)
```

#### Size Impact

```
size_impact(participation) =
    0                                if participation <= 0.1
    alpha * (participation - 0.1)    if 0.1 < participation <= 1.0
    alpha * 0.9 + beta * sqrt(participation - 1.0)   if participation > 1.0
```

- `alpha`: linear impact coefficient (calibrate from historical fills)
- `beta`: square-root impact for sweeping beyond displayed size
- `participation = order_size / displayed_size_at_level`

#### Volatility Impact

```
volatility_impact(sigma) = gamma * sigma_1min
```

- `sigma_1min`: rolling 1-minute realized volatility
- `gamma`: volatility sensitivity coefficient (~0.3–0.5)

Higher volatility → quotes are staler → more adverse movement during execution.

### Calibration Procedure

1. Collect historical trades with known aggressor side
2. Compute effective spread: `2 * |trade_price - mid_at_trade_time|`
3. Regress effective spread on `participation_rate`, `sigma_1min`, `spread_level`
4. Estimate `alpha`, `beta`, `gamma` coefficients
5. Validate on held-out period (minimum 3 months)
6. Re-calibrate quarterly; monitor for drift monthly

---

## Passive Limit Order Fill Model

### Queue Position Model

Queue position is unobservable from L1. Model probabilistically:

```
queue_position ~ Uniform(0, estimated_total_queue)

estimated_total_queue = displayed_size * queue_depth_multiplier
```

- `queue_depth_multiplier`: accounts for hidden/iceberg orders (typical: 1.5–3.0x)
- Calibrate by comparing L1 displayed size to actual volume at level

### Fill Probability

```
P(fill | queue_pos, time, flow) =
    P(price_touch) * P(fill_at_touch | queue_pos, volume_at_touch)
```

#### Price Touch Probability

```
P(price_touch | spread, volatility, horizon) =
    1 - exp(-lambda_touch * horizon)

lambda_touch = f(volatility / spread)
```

Higher vol-to-spread ratio → more frequent price touches.

#### Fill-at-Touch Probability

```
P(fill_at_touch | queue_pos, volume) =
    max(0, (volume - queue_pos) / volume)   [deterministic]
    or
    Beta(a, b) where a = volume - queue_pos, b = queue_pos  [stochastic]
```

Use the stochastic version for Monte Carlo sensitivity analysis.

### Time-in-Queue Dynamics

Queue position improves over time as orders ahead are filled or canceled:

```
queue_pos(t) = queue_pos(0) * exp(-mu_cancel * t) - fills_ahead(t)
```

- `mu_cancel`: cancellation rate of orders ahead (calibrate from quote update frequency)
- `fills_ahead(t)`: volume traded at the level since order placement

### Adverse Selection Adjustment

Fills on passive limit orders are adversely selected:

```
P(adverse_move | filled) > P(adverse_move | not_filled)
```

Model this as a conditional return penalty:

```
expected_return_given_fill =
    unconditional_expected_return - adverse_selection_penalty

adverse_selection_penalty = delta * P(informed_flow)
```

- `delta`: price impact of informed flow (calibrate from trade-direction persistence)
- `P(informed_flow)`: proxy via VPIN or trade clustering intensity

Fills that occur during high-flow-toxicity periods carry larger adverse selection.

---

## Partial Fill Model

### Market Orders

When `order_size > displayed_size`:

```
fill_1 = min(order_size, displayed_size)  at NBBO
fill_2 = remaining_size                    at next level (NBBO + tick)
...
```

Sweep model: fill sequentially through price levels until order is complete.
Each level adds incremental slippage. Total cost is volume-weighted average.

With L1-only data, the next level is unobservable. Model conservatively:

```
next_level_size ~ Geometric(p) * displayed_size
next_level_price = current_level + tick_size * level_index
```

### Limit Orders

Partial fills occur when volume at the level is insufficient:

```
fill_fraction ~ Beta(alpha_fill, beta_fill)

where:
  alpha_fill = max(1, volume_at_level - queue_position)
  beta_fill = max(1, queue_position)
```

Fill fraction is bounded: `filled_quantity = order_size * fill_fraction`

---

## Assumptions Register

Explicitly document every assumption. Review quarterly.

| Assumption | Basis | Risk if Wrong | Monitoring |
|-----------|-------|---------------|------------|
| Queue depth = 1.5–3x displayed | Academic literature + estimation | Underestimate queue → overstate fills | Compare backtest fill rate to paper trade |
| LogNormal latency distribution | Empirical fit to Polygon data | Tail events underestimated | QQ plot monthly |
| Linear temporary impact | Almgren-Chriss framework | Understates impact for large orders | Track slippage vs predicted |
| Adverse selection ~ VPIN | Easley et al. | Misclassification of informed flow | Monitor fill-conditional returns |
| Iceberg order prevalence | Exchange-dependent; estimated | Hidden liquidity distorts queue model | Track fills > displayed size |
| Cancellation rate stationary | Short-horizon assumption | Queue position estimate drifts | Rolling mu_cancel estimate |

---

## Model Selection Guide

| Scenario | Recommended Tier | Rationale |
|---------|-----------------|-----------|
| Initial signal exploration | Tier 1 | Speed; reject clearly unprofitable signals |
| Research validation | Tier 2 | Realistic costs; defensible results |
| Pre-deployment check | Tier 3 | Conservative; ensures live viability |
| Sensitivity analysis | All three | Bracket the range of outcomes |
| Publication / reporting | Tier 2 + Tier 3 | Show both realistic and conservative |
