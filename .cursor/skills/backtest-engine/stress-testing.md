# Stress Testing & Sensitivity Analysis

## Data Perturbation Protocol

Inject controlled anomalies into the replay stream to validate engine robustness.
Every perturbation has a known ground truth so you can verify correct handling.

### Timestamp Jitter

Simulate clock uncertainty between exchange, SIP, and Polygon receipt.

```
perturbed_timestamp = original_timestamp + jitter

jitter ~ Uniform(-max_jitter, +max_jitter)
```

| Test Level | Max Jitter | Purpose |
|-----------|-----------|---------|
| Mild | ±1ms | Normal SIP variation |
| Moderate | ±5ms | Polygon websocket delay variance |
| Severe | ±50ms | Network congestion / reconnection |
| Adversarial | ±500ms | Simulated feed failure recovery |

**Validation**: results should degrade gracefully, not catastrophically.
Plot PnL vs jitter level — a sharp cliff indicates fragile timestamp dependencies.

### Duplicate Events

Inject exact duplicates at configurable rate to verify dedup logic.

| Parameter | Default | Range |
|-----------|---------|-------|
| Duplicate rate | 0.1% | 0.01% – 1.0% |
| Duplicate delay | 0–10ms | 0–100ms |
| Burst duplicates | 3 consecutive | 1–10 |

**Validation**: PnL must be identical with and without duplicates (after dedup).
If PnL differs, the dedup layer has a gap.

### Dropped Events

Remove events randomly to simulate feed gaps.

| Parameter | Default | Range |
|-----------|---------|-------|
| Drop rate | 0.05% | 0.01% – 0.5% |
| Burst drops | 5 consecutive | 1–50 |
| Gap duration | 100ms | 10ms – 5s |

**Validation**:
- Engine must detect gaps (sequence break or timestamp discontinuity)
- Features must handle missing data (interpolate, hold, or invalidate)
- Orders in flight during gap must be flagged as uncertain
- PnL should degrade proportionally, not diverge

### Stale Quotes

Freeze the NBBO for a configurable duration to simulate stale data.

```
if random() < stale_probability:
    suppress quote updates for stale_duration
```

| Parameter | Default | Range |
|-----------|---------|-------|
| Stale probability | 0.1% per second | 0.01% – 1% |
| Stale duration | 500ms | 100ms – 5s |

**Validation**: staleness detector must fire within detection_threshold.
No orders should be placed against quotes older than max_quote_age.

### Price Spikes

Inject outlier prices to test filtering and circuit-breaker logic.

```
if random() < spike_probability:
    quote.bid *= (1 + spike_direction * spike_magnitude)
    quote.ask *= (1 + spike_direction * spike_magnitude)
```

| Parameter | Default | Range |
|-----------|---------|-------|
| Spike probability | 0.01% | 0.001% – 0.1% |
| Spike magnitude | ±5% | ±1% – ±20% |

**Validation**: spikes filtered before reaching feature engine.
No trades executed at spike prices.

---

## Sensitivity Analysis Protocol

### Single-Parameter Sweeps

For each parameter, hold all others at baseline and sweep:

| Parameter | Baseline | Sweep Range | Steps |
|-----------|----------|-------------|-------|
| Total latency | 30ms | 0–200ms | 20 |
| Fill probability multiplier | 1.0x | 0.1–1.0 | 10 |
| Slippage multiplier | 1.0x | 0.5–3.0 | 10 |
| Queue position assumption | 50th percentile | 10th–90th | 9 |
| Adverse selection penalty | baseline | 0–2x baseline | 10 |
| Transaction cost multiplier | 1.0x | 0.5–2.0 | 10 |

**Output**: for each parameter, report:
- PnL curve as function of parameter value
- Sharpe ratio as function of parameter value
- Breakeven point (parameter value where PnL = 0)
- Gradient at baseline (local sensitivity)

### Multi-Parameter Scenarios

Combine parameters into named scenarios:

| Scenario | Latency | Fill Rate | Slippage | Costs | Purpose |
|---------|---------|-----------|----------|-------|---------|
| Optimistic | 15ms | 1.0x | 0.5x | 0.8x | Upper bound on performance |
| Baseline | 30ms | 1.0x | 1.0x | 1.0x | Default simulation |
| Realistic | 50ms | 0.7x | 1.5x | 1.2x | Expected live conditions |
| Pessimistic | 100ms | 0.4x | 2.5x | 1.5x | Stress case |
| Adversarial | 200ms | 0.2x | 3.0x | 2.0x | Viability threshold |

A strategy is deployment-ready only if profitable under **Realistic**.
A strategy is robust if still positive under **Pessimistic**.

### Monte Carlo Sensitivity

For stochastic parameters, run N simulations with parameter draws:

```
for seed in range(N):
    latency_profile = draw_latency_samples(seed)
    fill_model = draw_fill_parameters(seed)
    slippage_model = draw_slippage_parameters(seed)
    result = run_backtest(events, latency_profile, fill_model, slippage_model)
    results.append(result)

report:
    PnL distribution (mean, median, 5th/95th percentile)
    Sharpe distribution
    Max drawdown distribution
    Fill rate distribution
```

Minimum N = 100 for screening; N = 1000 for deployment decisions.

---

## Regime-Stratified Stress Testing

Run all stress tests separately for each regime:

| Regime | Definition | Why Separate |
|--------|-----------|-------------|
| Tight spread | Spread < 20th percentile | Different queue dynamics |
| Wide spread | Spread > 80th percentile | Fill model behaves differently |
| Low volatility | RV < 20th percentile | Signals may not fire |
| High volatility | RV > 80th percentile | Slippage dominates |
| Opening auction | 09:30–09:45 ET | Extreme microstructure noise |
| Closing auction | 15:45–16:00 ET | Concentrated flow |
| FOMC / macro event | Event calendar flagged | Regime breaks possible |

A strategy that works only in one regime is fragile.
Report per-regime PnL contribution and flag regime concentration.

---

## Validation Checklist

Run before accepting any backtest result:

```
INTEGRITY
- [ ] Determinism: two runs produce identical output
- [ ] Causality: no feature uses future data
- [ ] Fill timing: no fill before order acknowledgment
- [ ] PnL reconciliation: positions × prices = reported PnL
- [ ] Clock monotonicity: simulated time never decreases

REALISM
- [ ] Fill rate: within 20% of historical realized rate
- [ ] Slippage distribution: KS test vs production (p > 0.05)
- [ ] Latency distribution: matches configured profile
- [ ] Cost model: total costs within 10% of expected

ROBUSTNESS
- [ ] Jitter test: PnL degrades < 20% at ±5ms
- [ ] Drop test: PnL degrades < 30% at 0.05% drop rate
- [ ] Duplicate test: PnL identical after dedup
- [ ] Stale quote test: no trades against stale quotes
- [ ] Spike test: no fills at spike prices

SENSITIVITY
- [ ] Breakeven latency identified
- [ ] Breakeven fill rate identified
- [ ] PnL compression ratio: 0.6–0.8 (backtest vs live estimate)
- [ ] Profitable under Realistic scenario
- [ ] Positive under Pessimistic scenario
```

---

## Reporting Template

Every stress test report includes:

```
STRATEGY: [name]
RUN DATE: [date]
DATA PERIOD: [start] – [end]
CONFIG: [latency profile, fill tier, cost model]

BASELINE PERFORMANCE
  Gross PnL: [bps]
  Net PnL: [bps]
  Sharpe: [annualized]
  Max Drawdown: [bps]
  Fill Rate: [%]
  Avg Slippage: [bps]

SENSITIVITY SUMMARY
  Breakeven latency: [ms]
  Breakeven fill rate: [x]
  Breakeven slippage: [x]
  PnL compression ratio: [live estimate / backtest]

REGIME BREAKDOWN
  [Per-regime PnL table]

STRESS TEST RESULTS
  Jitter: [pass/fail, degradation %]
  Drops: [pass/fail, degradation %]
  Duplicates: [pass/fail]
  Stale quotes: [pass/fail]
  Spikes: [pass/fail]

MONTE CARLO (N=[count])
  PnL: [mean] ([5th] – [95th])
  Sharpe: [mean] ([5th] – [95th])
  Max DD: [mean] ([5th] – [95th])

DEPLOYMENT RECOMMENDATION
  [Ready / Conditional / Not ready]
  [If conditional: what must improve]
```
