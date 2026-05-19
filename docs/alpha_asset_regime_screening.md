# Alpha-to-Asset-to-Regime Screening

## Overview

Each signal alpha encodes a specific microstructure mechanism with an implicit
asset fit. Deploying an alpha on an unsuitable asset degrades signal-to-noise,
increases adverse selection cost, and produces spurious backtest results. This
document describes the pre-screening pipeline that makes the fit criteria
*explicit and empirically validated* before full deterministic backtesting in
Feelies.

---

## Why This Is Necessary

The five signal alphas in this repository each target a distinct footprint:

| Alpha | Mechanism | Implicit Asset Fit |
|---|---|---|
| `sig_benign_midcap_v1` | Kyle-style OFI + micro-price L1 footprint | Mid/large-cap with institutional VWAP/TWAP sponsorship |
| `sig_hawkes_burst_v1` | Self-exciting trade arrival bursts | Episodic informed-flow names (biotech, index candidates) |
| `sig_kyle_drift_v1` | Persistent Kyle lambda drift | Large-cap with measurable information asymmetry |
| `sig_moc_imbalance_v1` | MOC/LOC auction imbalance pressure | S&P 500 constituents with large ETF rebalance flows |
| `sig_inventory_revert_v1` | Dealer inventory exhaustion + reversion | Mid-cap with wide intraday range and active dealer books |

Running full deterministic backtests across all (alpha, asset) combinations is
expensive — O(alphas × liquid equities × dates). The screening pipeline narrows
this to O(alphas × 5–10 high-fit candidates per alpha) before the replay begins.

---

## Why Grok REPL

### The Infrastructure Problem

Running this pipeline locally requires Polygon.io API credentials, a configured
Python environment, and sufficient bandwidth to stream 1-second NBBO quote data
for hundreds of symbols across multiple weeks. For a universe of 300 symbols ×
10 days × ~50,000 quotes/symbol/day that is **150 million quote records** —
non-trivial outside dedicated data infrastructure.

### What Grok Provides

| Capability | Relevance |
|---|---|
| Pre-authenticated Polygon.io access | No API key management, no rate-limit negotiation |
| Persistent REPL session | Multi-step computation (universe → screen → synthesise) runs in one stateful session; intermediate DataFrames survive between cells |
| Server-side data proximity | Co-located with Polygon infrastructure; high-volume L1 quote fetches are orders of magnitude faster than a residential connection |
| Pre-installed dependencies | `numpy`, `pandas`, `scipy`, `statsmodels`, `polygon-api-client` all available |
| Extended context window | Full 6-prompt pipeline with all mathematical definitions fits in a single thread |

### Practical Comparison

```
Local approach:
  pip install  →  obtain API key  →  write fetch loop  →  handle pagination
  →  store to parquet  →  analyse
  Time to first result: hours to days

Grok REPL approach:
  Paste Prompt 0  →  universe_df ready in minutes
  Paste Prompts 1–5 sequentially  →  all five screens complete
  Paste Prompt 6  →  YAML mapping ready to inject into platform.yaml
  Time to first result: 30–60 minutes for the full pipeline
```

### Real-Time Data Advantage

The screening prompts use recent dates. Grok's Polygon.io access covers the
current and recent historical tape, so asset fit scores reflect *current*
microstructure behaviour — not a stale calibration from a different liquidity
regime. Spread regimes, institutional flow patterns, and Kyle lambda values
shift over quarters; a mapping derived from older data may not reflect today's
market structure.

### What Grok Does Not Replace

Grok REPL is a *screening tool*, not a backtesting engine. It cannot:

- Run Feelies' deterministic replay pipeline or produce parity-locked results
- Apply the platform's exact sensor implementations (EWMA parameters, snapshot timing)
- Enforce regime gate logic with the HMM calibration used in production

The handoff is deliberate: Grok identifies *candidate* (alpha, asset) pairs from
first-principles microstructure analysis; Feelies' deterministic backtest then
validates them with production-exact execution, cost, and regime modelling.

---

## Architecture: Three-Layer Filter

```
Layer 1 (Static)    Asset eligibility from observable characteristics
      ↓                  → market cap tier, ADTV, spread regime, sector
Layer 2 (Dynamic)   Microstructure signal quality from L1 NBBO replay
      ↓                  → IC, hit rate, edge magnitude, mechanism metrics
Layer 3 (Regime)    Regime compatibility from HMM state distribution
                         → preferred_regime annotation per (alpha, asset) pair
```

### Layer 1 — Static Eligibility

Observable asset characteristics are checked before any L1 data is fetched.
These criteria are derived from the alpha hypothesis, not from backtest P&L,
which is the key anti-overfitting safeguard:

- **Market cap tier**: VWAP/TWAP flow is measurable on mid/large-cap; MOC
  imbalance is only material on index constituents.
- **ADTV**: Sets a liquidity floor ensuring execution costs are within the
  alpha's declared cost arithmetic.
- **Spread regime**: The Roll (1984) spread estimate screens out names where
  the entry cost exceeds the alpha's declared `edge_cap_bps`.
- **Sector**: Some mechanisms are structurally absent in certain sectors
  (e.g. Hawkes burst intensity is low in slow-moving utilities).

### Layer 2 — Dynamic Signal Quality

The screening prompts compute the same sensor outputs the alpha uses in
production — using the same mathematical definitions as the platform's sensor
layer — and measure forward returns at the alpha's declared `horizon_seconds`.

Key metrics per alpha:

| Alpha | Primary Quality Metric | Threshold |
|---|---|---|
| `sig_benign_midcap_v1` | Spearman IC(OFI z-score, 120s return) | IC > 0.04, p < 0.10 |
| `sig_hawkes_burst_v1` | Directional consistency of burst episodes | > 0.60 |
| `sig_kyle_drift_v1` | Autocorrelation of info signal at lags 1–3 min | > 0.08 |
| `sig_moc_imbalance_v1` | Imbalance proxy IC vs auction return | IC > 0.10 |
| `sig_inventory_revert_v1` | Net reversion bps at 30s after episode end | > 1.0 bps net |

### Layer 3 — Regime Annotation

Regime compatibility is assigned from the alpha hypothesis, not derived from
data, to prevent circular reasoning. This annotation directly populates the
`regime_gate` in the alpha YAML.

| Alpha | Preferred HMM Regime |
|---|---|
| `sig_benign_midcap_v1` | `normal` |
| `sig_hawkes_burst_v1` | `vol_breakout` |
| `sig_kyle_drift_v1` | `normal` |
| `sig_moc_imbalance_v1` | any (calendar-driven) |
| `sig_inventory_revert_v1` | `compression_clustering` |

---

## Execution Flow

```
Prompt 0  →  universe_df  (shared input to all 5 screens)
     ↓
Prompts 1–5  →  per-alpha ranked tables (results_benign, results_hawkes, …)
     ↓
Prompt 6  →  cross-join, eligibility matrix, regime annotations
     ↓
YAML output  →  inject into platform.yaml alpha_specs[] + symbols[]
     ↓
Feelies deterministic backtest sweep  →  parity-locked validation
     ↓
Promote to asset_eligibility: block in alpha YAML
```

---

## Prompt Set

The following prompts are designed for Claude Opus with Polygon.io REPL access.
Paste them sequentially into a single conversation. Each prompt is self-contained
with all mathematical definitions; no external state is required except
`universe_df` produced by Prompt 0.

---

### SYSTEM CONTEXT (prepend to every prompt)

```
You are a quantitative microstructure research assistant with access to Polygon.io
via its Python REST client (already authenticated). Execute all code in REPL cells.
Python environment has: numpy, pandas, scipy, statsmodels, polygon-api-client.

Polygon.io client initialisation:
  from polygon import RESTClient
  client = RESTClient()   # API key injected via environment

Time zone convention: all timestamps converted to US/Eastern.
Trading hours filter: 09:30:00–15:59:59 ET only (exclude auction prints).
Date range for all screens unless overridden: 2026-04-01 to 2026-04-25 (18 trading days).

Data quality rules (apply before any computation):
  - Drop quotes where bid <= 0 or ask <= 0 or bid >= ask
  - Drop quotes where spread_bps > 200 (clearly erroneous)
  - Drop trades with condition codes in {37,38,41,54,64} (odd-lot / out-of-sequence)
  - Drop any symbol-day where total quotes < 50,000 (insufficient L1 data)
  - Winsorise all z-scores to [-6, +6] before correlation analysis
```

---

### Prompt 0 — Universe Construction

```
## Task
Build a filtered US equity universe suitable for intraday signal screening.
This universe feeds all five subsequent alpha-screening prompts.

## Step 1 — Reference Universe
Fetch all active US common equity tickers:
  tickers = client.list_tickers(market="stocks", type="CS", active=True, locale="us")

## Step 2 — 30-Day Daily Aggregates
For each ticker, fetch daily aggregate bars for 2026-03-24 to 2026-04-25 (23 days):
  client.get_aggs(ticker, 1, "day", "2026-03-24", "2026-04-25", adjusted=True)

Compute per ticker:
  adtv_usd  = median(volume_i * vwap_i) across available days
  adtv_n    = count of days with valid bars (require >= 15)
  price_med = median(vwap_i)

## Step 3 — Filters
Retain tickers satisfying ALL of:
  (a) adtv_usd >= 50_000_000   (liquidity floor: $50M ADTV)
  (b) price_med >= 5.00        (price floor)
  (c) adtv_n >= 15             (data continuity)
  (d) type="CS"                (common stock only; no ETFs, ADRs, preferreds)

## Step 4 — Market-Cap Tier Classification
  client.get_ticker_details(ticker)  →  market_cap field

  tier = "mega"  if market_cap >= 50e9
  tier = "large" if 10e9 <= market_cap < 50e9
  tier = "mid"   if 2e9  <= market_cap < 10e9
  tier = "small" if market_cap < 2e9

## Step 5 — Spread Proxy (Roll 1984 Estimator)
For a 3-day sample (2026-04-23, 2026-04-24, 2026-04-25), fetch 1-min bars.
  roll_spread_bps = 2 * 10000 * sqrt(max(0, -cov(delta_log_mid_t, delta_log_mid_{t+1})))
Take the median across 3 sample days.

## Output
DataFrame `universe_df`:
  [ticker, adtv_usd, price_med, market_cap, tier, sector, roll_spread_bps_est, adtv_n]

Print: shape, count per tier, top-30 by adtv_usd,
       percentile distribution of roll_spread_bps_est (p10, p25, p50, p75, p90).
```

---

### Prompt 1 — sig_benign_midcap_v1

```
## Alpha Hypothesis
Kyle-style informed-flow footprint on L1. Institutional VWAP/TWAP parent orders
imprint a persistent same-sign OFI and micro-price tilt relative to mid.
Signal condition: |ofi_ewma_zscore| > 0.8 with aligned micro_price_zscore,
spread_z < 1.5, horizon 120 seconds.

## Target Asset Profile
  tier in {"mid", "large"}
  roll_spread_bps_est < 8.0
  adtv_usd in [500M, 10B]
  Preferred sectors: Industrials, Healthcare, Financials, Tech

## Data
Input: universe_df filtered to above profile.
Fetch per symbol per day (5 days: 2026-04-21 to 2026-04-25):
  - 1-second NBBO quotes: client.list_quotes(ticker, ...)
  - 1-second trades:      client.list_trades(ticker, ...)

## Computation

### Raw Features (1-second bins)
mid_t         = (bid_t + ask_t) / 2
spread_bps_t  = (ask_t - bid_t) / mid_t * 10000
micro_price_t = (bid_t * ask_size_t + ask_t * bid_size_t) / (bid_size_t + ask_size_t)
micro_dev_bps = (micro_price_t - mid_t) / mid_t * 10000

OFI_t = Δbid_size_t * I(bid_t >= bid_{t-1}) - Δask_size_t * I(ask_t <= ask_{t-1})
  [Cont-Kukanov-Weber 2014 Level-1 OFI]

### EWMA Aggregation (30-second bins)
ofi_ewma_t   = EWMA(OFI_t,         halflife='180s')
spread_ewma_t = EWMA(spread_bps_t, halflife='180s')

### Rolling Z-Score (30-minute window, 30-second step)
ofi_zscore_t    = (ofi_ewma_t - rolling_mean) / rolling_std
micro_price_z_t = (micro_dev_bps - rolling_mean) / rolling_std
spread_z_t      = (spread_ewma_t - rolling_30d_median) / rolling_30d_std
vol_zscore_t    = z-score of 30s realised vol over 60-min rolling window

### Signal Gate
qualifying = (
  abs(ofi_zscore_t) > 0.8
  AND sign(ofi_zscore_t) == sign(micro_price_z_t)
  AND spread_z_t < 1.5
  AND vol_zscore_t < 4.5
)
direction_t = sign(ofi_zscore_t)

### Forward Return (120-second horizon, sign-adjusted)
forward_return_bps = (mid_{t+120s} - mid_t) / mid_t * 10000 * direction_t
Exclude bins within 600s of open (09:30–09:40) and 600s of close (14:50–15:00).

### Per-Symbol Metrics
signal_count_per_day = len(qualifying) / n_days
IC_spearman  = spearmanr(|ofi_zscore| values, forward_return_bps).statistic
p_value_IC   = two-sided t-test on IC (df = n - 2)
mean_edge_bps = mean(forward_return_bps)
hit_rate      = mean(forward_return_bps > 0)
sharpe_120s   = mean / std * sqrt(252 * 26)

## Scoring
composite_score = (
  IC_spearman * (1 - p_value_IC)
  * log1p(signal_count_per_day)
  * (mean_edge_bps / 5.0).clip(0, 2)
)
Gate: n_qualifying >= 15 AND p_value_IC < 0.10

## Output DataFrame `results_benign`
[ticker, tier, roll_spread_bps_est, signal_count_per_day, n_qualifying,
 IC_spearman, p_value_IC, mean_edge_bps, hit_rate, sharpe_120s, composite_score]
Top-20 by composite_score. Count satisfying IC > 0.06 AND p < 0.10 AND edge > 2bps.
```

---

### Prompt 2 — sig_hawkes_burst_v1

```
## Alpha Hypothesis
Self-exciting Hawkes process on trade arrivals. Branching ratio η = α/β captures
persistence of informed urgency. Exploitable regime: η ∈ (0.35, 0.80).
Below: noise-only. Above: illiquid / near-explosive.

## Target Asset Profile
  tier in {"mid", "large", "mega"}
  adtv_usd >= 100M
  Preferred sectors: Healthcare/Biotech, Tech, Energy, high short-interest names

## Data
Fetch per symbol per day (10 days: 2026-04-14 to 2026-04-25):
  All trades: client.list_trades(ticker, ...) → sip_timestamp, price, size, conditions

## Computation

### Hawkes MLE (univariate exponential kernel)
Model: λ(t) = μ + Σ_{t_i < t} α * exp(-β * (t - t_i))

Log-likelihood = -μT - (α/β)N + Σ_i log(μ + α * R_i)
  R_i = (R_{i-1} + 1) * exp(-β * Δt_i)   [recursive computation]
  T = 23400s, N = trade count

Optimise (μ, α, β) via scipy.optimize.minimize L-BFGS-B.
Bounds: μ ∈ (0.001, 100), α ∈ (0, 50), β ∈ (0.01, 500).
Reject if η = α/β >= 1.0 (supercritical) or se(η)/η > 0.30.

### Burst Episode Detection
background_intensity = μ / (1 - η)
burst_threshold = background_intensity * 3.0
Episode: λ(t) > burst_threshold sustained >= 10s.
Merge episodes within 10s; require 30s gap between distinct episodes.

### Per-Episode Metrics
Lee-Ready sign per trade: +1 if price > prevailing_mid, -1 if below, tick rule fallback.
signed_volume = Σ sign_i * size_i
price_impact_bps = (mid_{t_end} - mid_{t_start}) / mid_{t_start} * 10000
directionally_consistent = (sign(signed_volume) == sign(price_impact_bps))

### Per-Symbol Metrics
burst_frequency_per_day, mean_burst_duration_s, mean_price_impact_bps,
directional_consistency, η_mean, η_cv = std(η)/mean(η) across days.

## Scoring
Gate: η_mean ∈ [0.35, 0.80] AND η_cv < 0.30 AND burst_frequency > 3/day
composite_score = (
  directional_consistency
  * log1p(burst_frequency_per_day)
  * (mean_price_impact_bps / 5.0).clip(0, 3)
  * (1 - η_cv).clip(0, 1)
)

## Output DataFrame `results_hawkes`
[ticker, η_mean, η_cv, se_eta_ratio, burst_frequency_per_day,
 mean_burst_duration_s, mean_price_impact_bps, directional_consistency, composite_score]
Top-20 by composite_score. Histogram of η_mean across all tickers.
```

---

### Prompt 3 — sig_kyle_drift_v1

```
## Alpha Hypothesis
Persistent Kyle lambda drift: informed traders' order flow exerts sustained
signed price pressure proportional to private information value. Persistence
(positive autocorrelation of λ*signed_vol at lags 1–3 min) distinguishes
informed drift from noise-driven reversion.

## Target Asset Profile
  tier in {"large", "mega"}
  adtv_usd >= 500M
  Active options market: total_options_oi > 100,000 contracts
  λ_median ∈ (5e-7, 5e-5) bps per share

## Data
Fetch per symbol per day (all 18 days):
  1-minute bars: client.get_aggs(ticker, 1, "minute", ...)
  1-second trades for Lee-Ready sign

## Computation

### Per 1-Minute Bar
bar_return_bps = (mid_close - mid_open) / mid_open * 10000
signed_volume  = Σ (tick_rule_sign_i * size_i) for trades in bar

### Rolling Kyle Lambda (20-bar OLS window)
OLS: bar_return_bps ~ α + λ * signed_volume
Reject λ_b if |t_stat| < 1.5 or λ_b < 0.

### Drift Persistence
info_signal_b = λ_b * signed_volume_b
AC_k = autocorr(info_signal, lag=k) for k in {1,2,3,5,10}
persistence_score = mean(AC_1, AC_2, AC_3)
drift_vs_revert_ratio = mean(AC_1..3) / abs(mean(AC_5, AC_10))

### Lambda Stability
λ_iqr = (p75(λ_b) - p25(λ_b)) / median(λ_b)   [want < 1.5]

### Information Ratio
forward_return_bps_b = bar_return_bps_{b+1}
IR = mean(forward * sign(info_signal)) / std(forward * sign(info_signal)) * sqrt(252*390)

### Per-Symbol Aggregation (18 days)
λ_mean, λ_day_cv, persistence_mean, IR, drift_ratio_mean

## Scoring
Gate: λ_mean ∈ (5e-7, 5e-5) AND persistence_mean > 0.08 AND IR > 0.05
composite_score = (
  persistence_mean * 3.0 + IR.clip(0,1) - λ_day_cv * 0.5
) * (drift_ratio_mean > 1.0)   [hard zero if reversion-dominated]

## Output DataFrame `results_kyle`
[ticker, tier, λ_mean, λ_day_cv, persistence_mean, drift_ratio_mean, IR, composite_score]
Top-20 by composite_score. Scatter: λ_mean vs persistence_mean coloured by tier.
Note any ticker in top-10 of both results_benign and results_kyle.
```

---

### Prompt 4 — sig_moc_imbalance_v1

```
## Alpha Hypothesis
Exchange MOC/LOC imbalance (or its proxy) reveals excess directional demand
that must be satisfied at the closing auction. Pre-close drift in 15:50–16:00 ET
is the exploitable window. Best on S&P 500 constituents with large ETF rebalance flows.

## Target Asset Profile
  tier in {"mega", "large"}
  is_sp500 = True
  adtv_usd * moc_volume_pct > $5M estimated daily MOC volume

## Data
Fetch per symbol per day (all 18 days):
  1-minute bars: client.get_aggs(ticker, 1, "minute", ...)
  1-second bars for 15:45–16:05: client.get_aggs(ticker, 1, "second", ...)
  Closing auction print: trades with condition code 6 or 38

## Computation

### Reference Prices
mid_15h50, mid_15h55, mid_15h59 from quote stream.
close_px = closing auction print (condition 6/38).

### MOC Imbalance Proxy (Polygon has no direct imbalance feed for equities)
(i)  vol_accel = volume[15:50–16:00] / volume[15:40–15:50]
(ii) depth_imbalance = (bid_size_15h55 - ask_size_15h55) / (bid_size + ask_size)
(iii)drift_acceleration = drift[15:50–15:59] - drift[15:40–15:50]

imbalance_proxy = 0.4*depth_imbalance + 0.4*sign(drift_accel)*min(|drift_accel|/5,1)
                + 0.2*(vol_accel > 2.0) - 0.5

### Signal Measurement (sign-adjusted)
alpha_return_bps = (close_px - mid_15h50) / mid_15h50 * 10000 * sign(imbalance_proxy)
net_alpha_bps    = alpha_return_bps - (roll_spread/2 + 1.0)
overnight_reversion_bps = (next_open - close_px) / close_px * 10000

### Per-Symbol Metrics (18 days)
mean_alpha_return_bps, hit_rate, imbalance_proxy_IC (spearmanr),
mean_vol_accel, overnight_reversion_fraction

## Scoring
Gate: hit_rate > 0.50 AND imbalance_proxy_IC > 0.10 AND mean_alpha_return > 1.5bps
composite_score = (
  imbalance_proxy_IC * 2 + hit_rate * 2 - overnight_reversion_fraction * 1.5
  + (mean_vol_accel > 2.5) * 0.5
) * is_sp500   [hard zero for non-SP500]

## Output DataFrame `results_moc`
[ticker, tier, sector, mean_alpha_return_bps, hit_rate, imbalance_proxy_IC,
 mean_vol_accel, overnight_reversion_fraction, is_sp500, composite_score]
Top-20 by composite_score. Sector breakdown of top-20.
```

---

### Prompt 5 — sig_inventory_revert_v1

```
## Alpha Hypothesis
Dealer inventory accumulation under one-sided order flow causes temporary price
dislocation (Ho-Stoll 1981, Amihud-Mendelson 1980). Reversion occurs when the
dealer reloads or contra-side flow arrives. Signal fires on detectable inventory
depletion (quote skew + spread widening) and targets 30–120s mean reversion.

## Target Asset Profile
  tier in {"mid", "large"}
  roll_spread_bps_est in [3, 20]
  adtv_usd in [100M, 3B]
  Exclude names with quote-to-trade ratio > 500:1 (HFT-dominated)

## Data
Fetch per symbol per day (10 days: 2026-04-14 to 2026-04-25):
  1-second NBBO quotes and 1-second trades.

## Computation

### Quote Microstructure Features (1-second bins)
mid_t         = (bid_t + ask_t) / 2
spread_bps_t  = (ask_t - bid_t) / mid_t * 10000
quote_skew_t  = (ask_size_t - bid_size_t) / (ask_size_t + bid_size_t + 1e-9)
vwap_mid_t    = rolling 60s VWAP of trade prices
mid_tilt_bps  = (mid_t - vwap_mid_t) / vwap_mid_t * 10000
spread_z_t    = (spread_bps_t - rolling_60min_mean) / rolling_60min_std

### Depletion Episode Detection
Episode criteria (all conditions sustained >= 20 consecutive seconds):
  |quote_skew_t| > 0.60   (one-sided book)
  spread_z_t > 1.0         (spread widened)
  |mid_tilt_bps| > 0.5     (mid tilted from VWAP)
Merge episodes within 10s; require 30s gap between distinct episodes.
depletion_direction = sign(quote_skew_t)   [+1 = ask-heavy = buy pressure]

### Reversion Measurement
entry_mid = mid at episode end
For h in {15, 30, 60, 120} seconds:
  reversion_h_bps = -(mid_{t_end+h} - entry_mid) / entry_mid * 10000 * depletion_direction
cost_bps = spread_bps_{t_end} / 2 + 0.5
net_reversion_30s = reversion_30s_bps - cost_bps

spread_normalisation_speed_s:
  first t > t_end where spread_bps_t < rolling_mean + 0.5 * rolling_std

### Per-Symbol Metrics (10 days)
episode_frequency_per_day, mean_net_reversion_30s_bps,
reversion_hit_rate_30s, reversion_hit_rate_120s, spread_norm_speed_s,
decay_shape_score = (reversion_30s > reversion_15s) AND (reversion_60s > reversion_30s)

## Scoring
Gate: frequency > 3/day AND net_reversion_30s > 1.0bps AND hit_rate_30s > 0.55
      AND spread_norm_speed < 90s
composite_score = (
  mean_net_reversion_30s_bps * 2
  * reversion_hit_rate_30s
  * log1p(episode_frequency_per_day)
  * (90 / (spread_norm_speed_s + 1))
) * decay_shape_score   [hard zero without correct reversion profile]

## Output DataFrame `results_inventory`
[ticker, tier, roll_spread_bps_est, episode_frequency_per_day,
 mean_net_reversion_30s_bps, reversion_hit_rate_30s, reversion_hit_rate_120s,
 spread_norm_speed_s, decay_shape_score, composite_score]
Top-20 by composite_score. Reversion decay profile (mean per horizon) for top-5.
```

---

### Prompt 6 — Cross-Alpha Mapping Synthesis

```
## Task
Synthesise the five per-alpha screening results into a deployable
alpha-to-asset mapping with regime annotations.

## Step 1 — Merge All Results
Outer-join results_benign, results_hawkes, results_kyle, results_moc,
results_inventory on ticker. Fill NaN composite_scores with 0.

## Step 2 — Eligibility Matrix
For each ticker:
  eligible_benign    = (composite_score > p50) AND IC_spearman > 0.04
  eligible_hawkes    = (composite_score > p50) AND η_mean ∈ [0.35, 0.80]
  eligible_kyle      = (composite_score > p50) AND drift_ratio_mean > 1.0
  eligible_moc       = (composite_score > p50) AND is_sp500
  eligible_inventory = (composite_score > p50) AND decay_shape_score
  n_alphas_eligible  = sum of above 5 binary flags

## Step 3 — Regime Compatibility Annotation
  sig_benign_midcap_v1    → preferred_regime: normal
  sig_hawkes_burst_v1     → preferred_regime: vol_breakout
  sig_kyle_drift_v1       → preferred_regime: normal
  sig_moc_imbalance_v1    → preferred_regime: any
  sig_inventory_revert_v1 → preferred_regime: compression_clustering

## Step 4 — Priority Ranking
Sort by: n_alphas_eligible DESC, then sum of normalised composite scores DESC.

## Output
1. Top-30 tickers:
   [ticker, tier, sector, n_alphas_eligible, eligible_alphas (list),
    preferred_regimes (dict), all five composite scores]

2. Heatmap-ready matrix: tickers (rows) × 5 alphas (columns), value = composite_score.

3. "Starter deployment shortlist":
   n_alphas_eligible >= 2 AND at least one score in top quartile.

4. YAML-formatted per-alpha top-5:
   alpha_asset_mapping:
     sig_benign_midcap_v1:    [TICKER1, TICKER2, ...]
     sig_hawkes_burst_v1:     [...]
     sig_kyle_drift_v1:       [...]
     sig_moc_imbalance_v1:    [...]
     sig_inventory_revert_v1: [...]
```

---

## Output → Deployment Path

The YAML block from Prompt 6 Step 4 is injected directly into `platform.yaml`:

```yaml
# Symbols eligible per alpha (from Grok screening, <date>)
symbols:
  - TICKER1
  - TICKER2
  ...

alpha_specs:
  - alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml
  ...
```

Each (alpha, asset) pair is then run as a separate deterministic backtest in
Feelies. Parity hashes lock in results. Pairs that pass the full backtest
acceptance criteria graduate to an `asset_eligibility:` block in the alpha YAML,
becoming a permanent pre-flight filter for production deployment.

---

## Key Design Principles

**Anti-overfitting**: Eligibility criteria are derived from *ex-ante* asset
characteristics and microstructure theory, not from backtest P&L rankings. The
screening identifies assets where the mechanism *should* work; the backtest
verifies that it *does* work.

**Same math as production**: Screening prompts compute OFI, Kyle lambda, spread_z,
and other sensors using the same mathematical definitions as the platform's sensor
layer. This ensures the signal being screened is the signal that will be backtested.

**Regime annotation from theory**: Regime compatibility is assigned from the alpha
hypothesis, not from data correlation, to prevent circular reasoning.

**Multi-alpha overlap as priority signal**: Assets appearing in multiple eligible
sets have the highest platform coverage value and are prioritised for the backtest
sweep first.
