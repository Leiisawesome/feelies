# Research Protocol — Detailed Methodology

## Codebase Alignment

Research features defined below feed into the Layer-1 sensor framework
(`feelies.sensors`) — implementations of `SensorProtocol`
(`sensors/protocol.py`) emitting `SensorReading` events
(`core/events.py`). `HorizonAggregator` (`features/aggregator.py`)
fans them into `HorizonFeatureSnapshot` events on `HorizonTick`
boundary crossings. Signal logic feeds into the `HorizonSignal`
contract (`signals/horizon_protocol.py`) declared inline in a
schema-1.1 SIGNAL alpha YAML — `evaluate(snapshot, regime, params)
-> Signal | None`.

The historical per-tick `FeatureVector` / `FeatureEngine.update` /
`SignalEngine.evaluate` contracts were retired in Workstream D.2 and
are unsupported.

The formalization path from research prototype to engine component is
governed by the research-workflow skill. Sensors must implement
incremental `update(NBBOQuote | Trade) -> SensorReading | None`
semantics; batch pandas/numpy prototypes must be re-implemented
incrementally before backtesting via `Orchestrator.run_backtest()`.

Schema-1.1 SIGNAL alphas additionally declare:

- `depends_on_sensors:` (G6 sensor-DAG validity)
- `horizon_seconds:` (single-horizon binding)
- `trend_mechanism:` (G16 — required since Workstream E)
- `regime_gate:` (AST-DSL purity boundary)
- `cost_arithmetic:` (G12 — margin_ratio ≥ 1.5, reconciles ±5%)

---

## Hypothesis-Driven Research Framework

### Phase 1: Hypothesis Formation

Every research initiative begins with a structural hypothesis:

```
HYPOTHESIS TEMPLATE:
- Observable: [What L1 phenomenon do we observe?]
- Mechanism: [What latent process generates this observation?]
- Prediction: [What forward return distribution does this imply?]
- Counterfactual: [What would we observe if the hypothesis is false?]
- Decay model: [How does this edge degrade under exploitation?]
```

Reject hypotheses that:
- Cannot specify the mechanism
- Have no testable counterfactual
- Require data you don't have (L2, direct feed timestamps)
- Assume stable parameters across regimes

### Phase 2: Feature Engineering from L1

#### Spread-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Spread level | ask - bid | Liquidity cost proxy |
| Spread z-score | (spread - rolling_mean) / rolling_std | Regime detection |
| Spread velocity | d(spread)/dt | Liquidity withdrawal speed |
| Spread acceleration | d²(spread)/dt² | Second-order liquidity shock |
| Spread percentile | Rolling rank of current spread | Non-parametric regime |

#### Quote-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Quote update intensity | Updates per unit time | Information arrival proxy |
| Bid/ask update asymmetry | (ask_updates - bid_updates) / total | Directional pressure |
| Quote duration | Time between updates per side | Liquidity stability |
| Quote flicker rate | Rapid cancel-replace sequences | Spoofing / uncertainty proxy |
| Size imbalance | (bid_size - ask_size) / (bid_size + ask_size) | Micro-price adjustment |

#### Trade-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Trade aggressor | Classify via Lee-Ready or similar | Flow direction |
| VPIN proxy | Volume-bucketed aggressor imbalance | Toxicity measure |
| Trade clustering | Hawkes process intensity estimate | Self-exciting flow |
| Trade-to-quote ratio | Trades / quote updates in window | Information vs noise |
| Effective spread | 2 * |trade_price - mid| | Execution cost realization |

#### Micro-Price Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Weighted mid-price | bid + spread * (ask_size / (bid_size + ask_size)) | Fair value proxy |
| Micro-price momentum | Rolling change in weighted mid | Short-horizon trend |
| Micro-price mean reversion | Deviation from EWMA of weighted mid | Reversion signal |

### Phase 3: Statistical Validation

#### Test Hierarchy

1. **Univariate predictive regressions**
   - Regress forward returns on each feature
   - Use Newey-West standard errors (account for serial correlation)
   - Report t-stats, R², information coefficient

2. **Cross-validation protocol**
   - Walk-forward with expanding or rolling window
   - Never look ahead — strictly causal feature construction
   - Minimum 3 non-overlapping out-of-sample periods

3. **Regime stratification**
   - Test separately in low-vol, medium-vol, high-vol regimes
   - Test separately in tight-spread vs wide-spread regimes
   - Report if alpha concentrates in one regime (fragility signal)

4. **Transaction cost hurdle**
   - Compute realistic round-trip cost: spread + slippage + market impact
   - Alpha must exceed cost by a margin (minimum Sharpe contribution > 0.5 after costs)
   - Model fill probability for limit orders at various queue positions

5. **Multiple testing correction**
   - Track number of features tested
   - Apply Bonferroni or Benjamini-Hochberg correction
   - Report both raw and adjusted significance

#### Backtest Standards

```
BACKTEST REQUIREMENTS:
- Entry point: `Orchestrator.run_backtest()` with `SimulatedClock` (core/clock.py)
- Latency model: minimum 10ms processing + network delay (injected via SimulatedClock)
- Fill model: no immediate fills at NBBO; model queue position (OrderRouter protocol)
- Slippage model: function of size relative to displayed liquidity
- Market impact: even for small orders, model temporary impact
- Cost model: explicit commission + SEC/FINRA fees
- Timestamp alignment: use exchange timestamps via NBBOQuote.exchange_timestamp_ns
- Determinism: SHA-256 order IDs from correlation_id:sequence (core/identifiers.py)
```

### Phase 4: Robustness Checks

| Test | Purpose | Red Flag |
|------|---------|----------|
| Parameter perturbation | Vary lookback windows ±20% | Sharp performance cliff |
| Subsample stability | Test on first/second half separately | Sign reversal |
| Ticker rotation | Test on in-sample and out-of-sample tickers | Only works on trained tickers |
| Calendar effects | Test across days-of-week, month-end, FOMC | Alpha clusters on events only |
| Regime conditioning | Stratify by VIX level | Works only in one regime |
| Data vintage | Test on different data periods | Recent-only alpha (overfitting) |

### Phase 5: Alpha Decay Modeling

Model the half-life of the signal:
- Measure information coefficient as a function of horizon
- Estimate decay curve: IC(t) = IC_0 * exp(-lambda * t)
- If half-life < execution latency, the signal is not tradeable
- Monitor decay in production: compare realized IC vs expected IC

---

## L1 Data Limitations — What You Cannot See

Explicitly acknowledge these blind spots:

| Hidden Information | Impact | Mitigation |
|-------------------|--------|------------|
| Full order book depth | Cannot measure true liquidity beyond top | Infer from spread dynamics + trade sizes |
| Hidden/dark orders | Underestimate true liquidity | Track trade-to-displayed-size ratios |
| Cancel-to-trade ratio | Cannot directly observe full cancellation flow | Proxy via quote flicker rate |
| Queue position | Cannot know where your order sits | Model probabilistically |
| Cross-venue dynamics | Massive aggregates; you lose venue granularity | Accept as systematic noise |
| True latency | Variable websocket delay | Model as stochastic latency; add buffer |

Every model must include a section: "What breaks if the L2 reality diverges
from our L1 inference?" — and specify monitoring for this divergence.

---

## Mathematical Toolkit Reference

### Point Processes for Order Arrivals

Model trade/quote arrivals as a Hawkes process:

```
lambda(t) = mu + sum_i alpha * exp(-beta * (t - t_i))
```

- mu: baseline intensity
- alpha: self-excitation (clustering)
- beta: decay rate
- Estimate via MLE on trade timestamps
- Use to detect regime shifts in flow intensity

### Micro-Price Dynamics

Weighted mid-price as Bayesian fair value:

```
p_micro = p_bid + spread * (V_ask / (V_bid + V_ask))
```

Under the assumption that displayed size reflects informational content.
Caveat: this breaks when displayed sizes are strategic (iceberg orders).

### Spread Process

Model spread as a mean-reverting jump-diffusion:

```
dS = kappa * (theta - S) * dt + sigma_S * dW + J * dN
```

- kappa: mean reversion speed
- theta: long-run spread level (regime-dependent)
- J: jump size distribution (spread dislocation events)
- N: Poisson process for liquidity shocks

### Order Flow Imbalance

Aggregate signed trade flow in volume buckets (not time buckets):

```
OFI_n = sum_{trades in bucket n} sign_i * volume_i
```

Use volume time to normalize for intraday seasonality.
Test predictive power of OFI on next-bucket return.

---

## Implementation Mapping

| Research concept | Codebase type | Location |
|------------------|---------------|----------|
| Sensor prototype (Layer 1) | `SensorProtocol` + `SensorSpec` | `sensors/protocol.py`, `sensors/spec.py`, `sensors/registry.py` |
| Sensor output | `SensorReading` (with `SensorProvenance`) | `core/events.py` |
| Layer-2 input | `HorizonFeatureSnapshot` (warm/stale flags, z-scores, percentiles) | `core/events.py` |
| SIGNAL alpha contract | `HorizonSignal.evaluate(snapshot, regime, params)` | `signals/horizon_protocol.py` |
| Signal output | `Signal` (with `SignalDirection`, `edge_estimate_bps`, `trend_mechanism`, `expected_half_life_seconds`) | `core/events.py` |
| Regime gate DSL | `RegimeGate` (AST-evaluated boolean DSL) | `signals/regime_gate.py` |
| Cost arithmetic | `CostArithmetic` (G12 enforcement at load time) | `alpha/cost_arithmetic.py` |
| Trend mechanism (G16) | `TrendMechanism` enum + family envelopes | `core/events.py`, `alpha/layer_validator.py` |
| Cross-sectional construction | `PortfolioAlpha` + `CompositionEngine` | `composition/protocol.py`, `composition/engine.py` |
| L1 quote / trade input | `NBBOQuote` / `Trade` | `core/events.py` |
| Backtest execution | `Orchestrator.run_backtest()` | `kernel/orchestrator.py` |
| Research execution | `Orchestrator.run_research(job)` | `kernel/orchestrator.py` |
| Deterministic time | `SimulatedClock` | `core/clock.py` |
| Config provenance | `Configuration.snapshot()` | `core/config.py` |
| Promotion lifecycle | `AlphaLifecycle` + F-2 gate matrix + F-1 ledger | `alpha/lifecycle.py`, `alpha/promotion_evidence.py`, `alpha/promotion_ledger.py` |
| Operator forensic CLI | `feelies promote ...` | `cli/promote.py` |
