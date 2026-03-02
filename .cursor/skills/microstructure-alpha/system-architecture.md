# System Architecture — Engineering Reference

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    DATA LAYER                           │
│  Polygon.io WebSocket ──> Raw Buffer ──> Normalizer     │
│  Polygon.io REST API ──> Historical Replay Engine       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 FEATURE ENGINE                          │
│  Spread calculator  │  Quote dynamics  │  Trade flow    │
│  Micro-price        │  Volatility      │  Regime state  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  SIGNAL LAYER                           │
│  Alpha models  │  Regime classifier  │  Confidence est. │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              EXECUTION LAYER                            │
│  Order manager  │  Fill simulator  │  Latency model     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  RISK ENGINE                            │
│  Position limits  │  Drawdown monitor  │  Kill switches  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│             PORTFOLIO ALLOCATOR                         │
│  Sizing  │  Factor exposure  │  Correlation control     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              MONITORING & LOGGING                       │
│  PnL tracking  │  Alpha decay  │  Latency  │  Alerts    │
└─────────────────────────────────────────────────────────┘
```

---

## Data Layer

### Polygon.io Integration

**Real-time feeds (WebSocket):**
- `T.*` — Trade messages
- `Q.*` — NBBO quote messages
- `AM.*` — Per-minute aggregates (secondary)

**Historical data (REST):**
- `/v3/quotes/{ticker}` — Historical NBBO quotes (nanosecond)
- `/v3/trades/{ticker}` — Historical trades
- `/v2/aggs/ticker/{ticker}/range/...` — Aggregated bars

**Subscription tier**: Advanced Stock ($229/mo equivalent)
- Real-time trades + quotes
- Full historical access
- 5 concurrent websocket connections

### Data Normalization Requirements

| Field | Normalization |
|-------|--------------|
| Timestamps | Convert to exchange time; track Polygon receipt delay |
| Prices | Adjust for splits (use Polygon adjustment factors) |
| Sizes | Normalize to shares (not lots) |
| Conditions | Parse trade condition codes; filter irregular trades |
| Exchanges | Map exchange codes; flag SIP consolidated vs direct |

### Replay Engine

For backtesting, replay historical data through the same pipeline as live:
- Same feature computation code path
- Inject synthetic latency matching production
- No future data leakage — enforce causal ordering
- Support variable-speed replay for development

---

## Feature Engine

### Design Principles

- **Stateless computation**: Each feature is a pure function of a sliding window
- **Incremental updates**: Update on each new quote/trade, don't recompute full window
- **Clock choice**: Support both wall-clock time and volume-clock (trade-count buckets)
- **Determinism**: Same input sequence produces same output regardless of wall time

### Feature Categories

```
LEVEL 0 — Raw observables
  bid, ask, bid_size, ask_size, last_trade, trade_size, trade_side

LEVEL 1 — Derived quantities
  spread, mid, micro_price, trade_aggressor, effective_spread

LEVEL 2 — Windowed statistics
  spread_ewma, quote_intensity, trade_imbalance, volatility_estimate

LEVEL 3 — Regime indicators
  spread_regime, vol_regime, flow_regime, composite_state
```

### Feature Compute Latency Budget

| Component | Target | Hard Limit |
|-----------|--------|------------|
| Feature update on new message | < 100 us | < 1 ms |
| Signal evaluation | < 1 ms | < 5 ms |
| Full pipeline (message -> order decision) | < 5 ms | < 20 ms |

These targets reflect Polygon.io websocket latency (~10-50ms) — no point
optimizing compute below the data delivery latency floor.

---

## Signal Layer

### Model Types

| Model | Use Case | Complexity |
|-------|----------|------------|
| Linear regression | Baseline alpha, interpretability | Low |
| Logistic / probit | Direction prediction with calibrated probability | Low |
| Ridge / Lasso | Feature selection + regularization | Medium |
| Gradient boosted trees | Non-linear interactions, regime capture | Medium |
| Online learning | Adaptive parameter updates | Medium-High |
| Hidden Markov Model | Regime detection and transition probabilities | High |

### Signal Output Specification

Every signal must produce:
```
{
  "ticker": str,
  "timestamp": int (ns),
  "direction": float (-1.0 to 1.0),
  "confidence": float (0.0 to 1.0),
  "regime": str,
  "expected_edge_bps": float,
  "expected_half_life_seconds": float,
  "features_snapshot": dict
}
```

### Model Governance

- Re-estimate parameters on a fixed schedule (e.g., weekly)
- Log all parameter updates with before/after comparison
- Monitor information coefficient daily; alert on sustained degradation
- Maintain a model registry with version history

---

## Execution Layer

### Fill Model for Backtesting

**Market orders:**
```
fill_price = ask + slippage(size, displayed_ask_size, volatility)
```

**Limit orders:**
```
fill_probability = f(queue_position, time_in_queue, flow_direction)
```

Calibrate fill model from historical data:
- Track limit orders placed at NBBO vs actual fill rates
- Model queue position as a function of time-since-placement
- Account for adverse selection: fills that execute are biased toward losers

### Latency Model

```
total_latency = polygon_delay + network_jitter + compute_time + broker_delay

polygon_delay ~ LogNormal(mu=3.0, sigma=0.5) [ms]
network_jitter ~ Uniform(1, 5) [ms]
compute_time ~ deterministic (measured)
broker_delay ~ LogNormal(mu=2.0, sigma=0.8) [ms]
```

Add stochastic latency in backtest; do not use fixed latency assumptions.

---

## Risk Engine

### Position-Level Controls

| Control | Specification |
|---------|--------------|
| Max position size | Function of ADV and displayed liquidity |
| Max holding period | Kill stale positions (alpha half-life * 2) |
| Per-trade loss limit | Max 0.5% of daily capital per trade |
| Stop-loss | Structural invalidation, not fixed dollar amount |

### Portfolio-Level Controls

| Control | Specification |
|---------|--------------|
| Gross exposure limit | Configurable; default 2x capital |
| Net exposure limit | Configurable; default 0.3x capital |
| Sector concentration | Max 30% gross in any single sector |
| Correlation cluster limit | Max 3 positions with pairwise rho > 0.6 |
| Daily drawdown limit | -2% triggers position reduction; -3% triggers full flatten |
| Weekly drawdown limit | -5% triggers strategy pause for review |

### Kill Switches

Automatic shutdown triggers:
1. Daily PnL < -3% of capital
2. Latency exceeds 200ms for > 30 seconds
3. Data feed gap > 5 seconds during market hours
4. Execution errors > 3 in any 10-minute window
5. Position reconciliation mismatch detected
6. Manual override via monitoring dashboard

---

## Portfolio Construction

### Position Sizing

Volatility-scaled sizing:

```
position_size = (target_risk / realized_vol) * confidence * capital
```

Where:
- target_risk: annualized vol target per position (e.g., 10bps/day)
- realized_vol: rolling estimate of ticker's intraday volatility
- confidence: signal confidence (0 to 1)
- capital: allocated capital for this strategy

### Factor Exposure Management

Monitor and constrain:
- **Market beta**: Net beta < 0.1 (near market-neutral)
- **Sector**: No sector > 30% of gross
- **Size factor**: Balance across market cap
- **Momentum factor**: Avoid systematic momentum loading
- **Volatility factor**: Monitor vol-of-vol exposure

---

## Monitoring & Logging

### Real-Time Metrics

| Metric | Frequency | Alert Threshold |
|--------|-----------|----------------|
| PnL (realized + unrealized) | Per-second | Daily loss limit |
| Latency (end-to-end) | Per-message | > 100ms sustained |
| Fill rate vs expected | Per-trade | < 50% of expected |
| Information coefficient | Hourly | < 0 for 2+ consecutive hours |
| Spread regime | Per-tick | Regime shift detected |
| Data feed health | Per-second | Gap > 2 seconds |

### Research vs Production Separation

```
RESEARCH ENVIRONMENT:
- Jupyter / Python scripts
- Full historical data access
- No connection to broker
- Relaxed latency constraints
- Feature experimentation

PRODUCTION ENVIRONMENT:
- Compiled / optimized code paths
- Real-time data only
- Live broker connection
- Hard latency budgets
- Frozen model parameters (until scheduled update)
- Full audit logging
```

Never deploy research code directly. Production code must be:
- Reviewed for correctness
- Tested with simulated data
- Validated against backtest results (paper trade period)
- Monitored for divergence from expected behavior
