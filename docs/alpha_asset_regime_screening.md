# Alpha-to-Asset-to-Regime Screening

## Document Purpose and How to Use This File

**This document is a briefing for Claude Opus.** Its job is to give Claude the
exact information needed to generate a set of self-contained Python prompts that
an operator can copy-paste — sequentially and without modification — into a Grok
REPL session (Grok with Polygon.io access) and receive a ranked, YAML-ready
alpha-to-asset mapping as output.

The chain is:

```
[This doc, read by Claude Opus]
       ↓  Claude understands production sensor math, gate logic,
          and why each metric corresponds to a platform behavior
       ↓
[Claude generates Grok prompt set (Prompts 0–6)]
       ↓  Operator pastes prompts sequentially into Grok REPL
       ↓
[Grok fetches Polygon.io L1 data, runs screens, outputs YAML]
       ↓
[YAML → platform.yaml → Feelies deterministic backtest sweep]
```

The quality of the Grok prompts depends entirely on how precisely the screening
computation mirrors the platform's production sensor implementations. A generic
microstructure screen selects assets where a mechanism *exists*. A
production-grounded screen selects assets where the platform's specific sensor
parameterisation will produce valid, warm, above-threshold signals at sufficient
frequency to justify deterministic backtest cost.

Reading guide for Claude: §1 explains why screening must precede backtesting.
§2 explains why Grok is the right execution environment and what the deliverable
is. §3 describes the three-layer screening filter architecture. §4 is the
central section — it establishes the quality principle that binds every
subsequent prompt. §5 is a production-exact analysis of all five alphas: read
this section before drafting or modifying any screening prompt. §6 is the
prompt set itself, designed for direct Grok use. §7 is the deployment path from
Grok output to production alpha YAML. §8 summarises the key design principles.

**If you are tasked with revising a prompt:** §4 and §5 are the immutable
anchors. Any revision must preserve the three correspondences in §4.1 (same
formula, same threshold, same horizon). The production sensor formulas, exact
parameter values, and `evaluate()` gate conditions documented in §5 are the
ground truth — they must not be approximated or substituted. What is tunable:
scoring weights, composite score formula, output DataFrame column names, print
statements, and supplementary diagnostic metrics that do not affect eligibility
gates.

---

## 1. Why Screening Is Non-Negotiable

Each signal alpha encodes a specific microstructure mechanism with an implicit
asset fit. Deploying an alpha on an unsuitable asset degrades signal-to-noise,
increases adverse selection cost, and produces spurious backtest results. This
section explains *why* screening must precede backtesting, not accompany it.

---

### 1.1 The Five Alphas and Their Structural Asset Requirements

| Alpha | Mechanism Family | Horizon | Asset Fit |
|---|---|---|---|
| `sig_benign_midcap_v1` | `KYLE_INFO` | 120 s | Mid/large-cap; institutional VWAP/TWAP sponsorship |
| `sig_hawkes_burst_v1` | `HAWKES_SELF_EXCITE` | 30 s | Names with episodic informed-flow clustering |
| `sig_kyle_drift_v1` | `KYLE_INFO` | 300 s | Large/mega-cap; measurable persistent λ drift |
| `sig_moc_imbalance_v1` | `SCHEDULED_FLOW` | 120 s | S&P 500 constituents; large ETF rebalance flows |
| `sig_inventory_revert_v1` | `INVENTORY` | 30 s | Mid-cap; wide intraday range; active dealer books |

### 1.2 Why the Backtest Cannot Self-Select Assets

**The combinatorial cost.** Running full deterministic backtests across all
(alpha, asset) combinations is O(alphas × liquid equities × dates). At
5 alphas × 300 symbols × 60 trading days each, that is 90,000 alpha-day replay
runs before a single result can be evaluated. The screening pipeline narrows
this to O(alphas × 5–10 high-fit candidates per alpha) before the replay begins.

**The circular reasoning trap.** If asset selection is based on backtest P&L
ranking, you are *conditioning on outcomes* rather than *conditioning on
mechanism*. The signal produces large P&L on stock A in the historical backtest
— but is that because the mechanism genuinely fits A, or because A happened to
trend during the calibration window? Screening from mechanism-first criteria
(does OFI z-score predict 120s returns *in normal regime* on this asset?) is
the only anti-overfitting safeguard that transfers out of sample.

**The cold-start problem.** Each sensor requires a warm-up period. For
`kyle_lambda_60s` that is 30 trades in a 60-second window. For
`hawkes_intensity` it is 20 trades per side in a 60-second window. On an
illiquid asset the sensor never warms, the regime gate never arms, and the
backtest produces zero signals — not useful information. Screening for minimum
liquidity floors ensures every symbol in the backtest sweep will produce a
meaningful number of signal events.

---

## 2. Why Grok REPL: The Deliverable Is the Prompt Set

### 2.1 The Goal

The explicit goal of this document is **to produce Prompts 0–6 (§6), which an
operator pastes sequentially into a Grok REPL session and receives a YAML
alpha-to-asset mapping as output.** Everything else in this document exists to
ensure those prompts are correct, grounded in production sensor math, and
unlikely to screen in assets where the platform would produce zero signals.

### 2.2 Why Grok Specifically

| Infrastructure Need | Grok Solution |
|---|---|
| Polygon.io L1 quotes, 1-second resolution | Pre-authenticated; no API key, no pagination boilerplate |
| Persistent stateful session | `universe_df` from Prompt 0 survives unchanged through Prompts 1–5 |
| Co-located compute | 150 million quote records (300 symbols × 10 days × 50,000 q/s/d) in ~30 min vs hours locally |
| Python environment | `numpy`, `pandas`, `scipy`, `statsmodels`, `polygon-api-client` available out of the box |

### 2.3 Time Advantage

```
Local approach:
  pip install  →  obtain API key  →  write pagination loop  →  store to parquet
  →  debug data quality  →  analyse
  Time to first result: hours to days

Grok REPL approach:
  Paste Prompt 0  →  universe_df ready in minutes
  Paste Prompts 1–5 sequentially  →  all five screens complete
  Paste Prompt 6  →  YAML mapping ready to inject into platform.yaml
  Time to first result: 30–60 minutes for the full pipeline
```

### 2.4 What Grok Does Not Replace

Grok REPL is a *screening tool*, not a backtesting engine. It cannot:

- Run Feelies' deterministic replay pipeline or produce parity-locked results
- Apply the platform's exact sensor warm-up sequences, snapshot timing, or HMM calibration
- Enforce regime gate logic with the fractional HMM posteriors used in production

The handoff is deliberate: Grok identifies *candidate* (alpha, asset) pairs from
first-principles microstructure analysis computed with production-equivalent
math; Feelies' deterministic backtest then validates them with production-exact
execution, cost, and regime modelling.

---

## 3. Architecture: Three-Layer Filter

```
Layer 1 (Static)    Asset eligibility from observable characteristics
      ↓                  → market cap tier, ADTV, spread regime, sector
Layer 2 (Dynamic)   Signal-grounded quality from L1 NBBO replay
      ↓                  → production-equivalent sensor outputs, IC, hit rate, edge
Layer 3 (Regime)    Regime compatibility from mechanism hypothesis
                         → preferred_regime annotation per (alpha, asset) pair
```

### Layer 1 — Static Eligibility

Observable asset characteristics checked before any L1 data is fetched. Each
criterion maps directly to a constraint that determines whether the platform's
sensors will warm and whether the alpha's cost arithmetic will hold:

- **Market cap tier**: VWAP/TWAP flow is measurable on mid/large-cap; MOC
  imbalance is only material on index constituents; Kyle λ needs sustained
  informed trading, present mainly in large/mega-cap.
- **ADTV**: Sets a liquidity floor. The `kyle_lambda_60s` sensor requires
  30 trades in a 60s window (`min_samples=30`); the `hawkes_intensity` sensor
  requires 20 trades per side in 60s (`warm_trades_per_side=20`). Below the
  ADTV floor these sensors will rarely warm.
- **Spread regime**: The Roll (1984) spread estimate screens out names where
  the entry cost exceeds the alpha's declared `edge_cap_bps`. Each alpha
  declares its half-spread assumption in `cost_arithmetic`.
- **Quote-to-trade ratio**: HFT-dominated names (>500:1) produce pathological
  readings in `ofi_ewma` because each order-book resting quote is tiny and
  cancels before matching; inventory depletion episodes are indistinguishable
  from noise.

### Layer 2 — Dynamic Signal Quality

Each screening prompt computes the sensor output using the **same mathematical
formula** as the platform's production sensor implementation. This is the
central quality principle — see §4 for the detailed derivation and §5 for the
per-alpha specifics.

Primary quality metric per alpha:

| Alpha | Primary Metric | Screening Threshold |
|---|---|---|
| `sig_benign_midcap_v1` | Spearman IC(ofi_ewma_zscore, 120s return) | IC > 0.04, p < 0.10 |
| `sig_hawkes_burst_v1` | Directional consistency of intensity z > 2 bursts | > 0.60 |
| `sig_kyle_drift_v1` | Autocorrelation of λ̂ × sign(OFI) at lags 1–3 min | > 0.08 |
| `sig_moc_imbalance_v1` | IC(imbalance_proxy, 15:50–16:00 drift) | IC > 0.10 |
| `sig_inventory_revert_v1` | Net reversion bps at 30s after asymmetry episode | > 1.0 bps net |

### Layer 3 — Regime Annotation

Regime compatibility is assigned from the alpha hypothesis, not from data
correlation, to prevent circular reasoning. This annotation populates the
`regime_gate` in the alpha YAML. The two `KYLE_INFO` alphas gate on `P(normal)`;
the `HAWKES_SELF_EXCITE` alpha also gates on `P(normal)` but requires tighter
spread; the `INVENTORY` alpha requires orderly conditions (`P(normal) > 0.5`);
the `SCHEDULED_FLOW` alpha is calendar-driven and does not use HMM posteriors.

| Alpha | `regime_engine` | Operative `on_condition` |
|---|---|---|
| `sig_benign_midcap_v1` | `hmm_3state_fractional` | `P(normal) > 0.5 and spread_z_30d < 1.5` |
| `sig_hawkes_burst_v1` | `hmm_3state_fractional` | `P(normal) > 0.6 and spread_z_30d < 1.0` |
| `sig_kyle_drift_v1` | `hmm_3state_fractional` | `P(normal) > 0.6 and spread_z_30d <= 1.0` |
| `sig_moc_imbalance_v1` | `hmm_3state_fractional` | `scheduled_flow_window_active == 1.0 and seconds_to_window_close > 60` |
| `sig_inventory_revert_v1` | `hmm_3state_fractional` | `abs(quote_replenish_asymmetry_zscore) > 2.0 and P(normal) > 0.5` |

---

## 4. The Quality Principle: Screen What You Trade

**This section is the most important part of this document for generating
correct Grok prompts.** The prompts in §6 are only useful if they compute
features that are predictive of *platform signal events* — not generic
microstructure predictability.

### 4.1 The Correspondence Requirement

For each alpha, a screening metric is *valid* if and only if:

1. It uses the same mathematical formula as the platform sensor that feeds the
   alpha's `evaluate()` function.
2. It applies the same thresholds as the alpha's `evaluate()` and `regime_gate`.
3. It measures predictability at the alpha's declared `horizon_seconds`.

If any of these three correspondences are broken, the screen may select assets
where the mechanism exists in some general form but the platform sensor will
never cross its threshold — producing zero signals in the deterministic backtest.

### 4.2 Why "Same Formula" Is Not Obvious

Consider `ofi_ewma`. A generic OFI screen might compute order imbalance as
`(buy_volume - sell_volume) / total_volume`. That is *not* what the platform
computes. The platform's `OFIEwmaSensor` (in
`src/feelies/sensors/impl/ofi_ewma.py`) uses the Cont-Kukanov-Weber (2014)
*top-of-book change* formula:

```
OFI_t =
  + bid_size_t              if bid_t > bid_{t-1}   (bid price improved: buy pressure)
  - bid_size_{t-1}          if bid_t < bid_{t-1}   (bid price retreated: supply)
  + (bid_size_t - bid_size_{t-1}) if bid_t == bid_{t-1}  (depth change at same price)
  + (-ask_size_t)              if ask_t < ask_{t-1}   (ask price improved: sell pressure)
  + ask_size_{t-1}             if ask_t > ask_{t-1}   (ask price retreated: demand)
  + -(ask_size_t - ask_size_{t-1}) if ask_t == ask_{t-1}
```

Then EWMA-smoothed with `alpha = 0.1` (platform default):
```
ofi_ewma_t = 0.1 * OFI_t + 0.9 * ofi_ewma_{t-1}
```

The screening prompt must use this formula, not a volume-ratio proxy. A
volume-ratio proxy might find assets where volume imbalance is predictive —
which is a different (and weaker) signal than the top-of-book footprint the
platform is actually measuring.

### 4.3 Why "Same Threshold" Is Not Obvious

The `sig_benign_midcap_v1` signal fires when `|ofi_ewma_zscore| > 0.8` **and**
`sign(ofi_zscore) == sign(micro_price_zscore)`. The screening should count
*qualifying signal events* — 30-second bins that would pass both conditions —
and measure the forward IC only on those qualifying bins, not on all bins where
`|ofi_zscore| > 0.8`. The dual-sign confirmation is load-bearing: it is the
mechanism's L1 footprint test and rejects approximately 40% of high-OFI bins.

### 4.4 Why "Same Horizon" Is Not Obvious

The five alphas use three distinct horizons: 30 s, 120 s, and 300 s. The
`sig_hawkes_burst_v1` and `sig_inventory_revert_v1` both use 30 s. Measuring
the Hawkes burst IC at 120 s would find assets where the burst drifts for 2
minutes — which is *not* what the platform is trying to capture. The platform's
`HorizonSignalEngine` gates evaluation to the exact `horizon_seconds` from the
YAML. The screening must measure forward returns at that exact horizon.

### 4.5 The Warm-Up Implication for Asset Selection

Each sensor has a warm-up requirement. Assets that warm slowly produce fewer
valid signal events per day, which raises the signal frequency threshold. The
screening's `signal_count_per_day` metric is therefore both a quality metric
and a proxy for the sensor warm-up regime on that asset:

| Sensor | Warm condition | Typical warm-up time on liquid names |
|---|---|---|
| `ofi_ewma` | 50 quotes in 300s window | < 10 s |
| `hawkes_intensity` | 20 trades per side in 60s | 30–120 s at open |
| `kyle_lambda_60s` | 30 trades in 60s window | 60–120 s at open |
| `quote_replenish_asymmetry` | 20 quotes, ≥1 add per side | < 30 s |
| `quote_hazard_rate` | platform default; ~4 events/s floor | < 5 s on liquid names |
| `scheduled_flow_window` | calendar-driven; active window is a prerequisite | only arms during MOC window |

---

## 5. Alpha-by-Alpha Production Analysis

This section documents what each alpha's production code *actually computes*,
so that Claude can translate these exact specifications into screening prompt
code. Each subsection has four parts: sensor pipeline, `evaluate()` logic,
regime gate, and screening implication.

---

### 5.1 `sig_benign_midcap_v1` — Kyle OFI + Micro-Price (120 s)

**Sensor pipeline:**

- `ofi_ewma` → `OFIEwmaSensor(alpha=0.1)`. Uses CKW (2014) top-of-book OFI,
  EWMA-smoothed. At the 120 s horizon boundary, `HorizonAggregator` provides
  `ofi_ewma` (level, passthrough) and `ofi_ewma_zscore` (rolling z over a 30-min
  window of 120 s snapshots).
- `micro_price` → micro-price vs mid deviation, EWMA-smoothed. Provides
  `micro_price_zscore` at the 120 s boundary.
- `spread_z_30d` → historical spread z-score (read from sensor cache, not
  snapshot; no horizon feature row for this sensor).
- `realized_vol_30s` → 30-second realised volatility; `realized_vol_30s_zscore`
  at boundary.

**`evaluate()` logic:** Requires `ofi_ewma_zscore` and `micro_price_zscore`.
Signal fires when:
```python
abs(z) >= 0.8                            # |ofi_ewma_zscore| threshold
and sign(z) == sign(z_mp) and z_mp != 0  # micro-price must align (same-sign, non-zero)
```
Direction = sign of `ofi_ewma_zscore`. Strength is superlinear above `|z|=1.6`.
Edge = `min(|z| * 4.0, 20.0)` bps.

**Regime gate:** `P(normal) > 0.5 and spread_z_30d < 1.5` to arm;
`P(normal) < 0.35 or spread_z_30d > 3.0 or realized_vol_30s_zscore > 4.5` to disarm.

**Screening implication:** The screen must compute the CKW OFI formula exactly,
EWMA at `alpha=0.1`, then z-score over a rolling window. Qualifying bins must
pass **both** the OFI magnitude test **and** the micro-price sign-alignment test.
Only IC computed on qualifying-bin forward returns at **120 s** is valid.
Expected signal frequency: ~5–15 qualifying bins/hour on well-fit mid-cap names.
An IC of 0.04 at p < 0.10 corresponds to approximately 50 qualifying events
over 5 days — achievable on names with ADTV above $500M.

---

### 5.2 `sig_hawkes_burst_v1` — Hawkes Self-Exciting Burst (30 s)

**Sensor pipeline:**

- `hawkes_intensity` → `HawkesIntensitySensor(alpha=0.4, beta=0.05, baseline_mu=0.0)`.
  Two-sided (buy and sell) exponentially-decaying intensity:
  ```
  Between trades:        λ(t) = μ + (λ(t_last) - μ) · exp(-β · Δt_s)
  On same-side trade:    λ(t_i) = λ(t_i⁻) + α
  ```
  where `Δt_s` is elapsed seconds since last trade (derived from nanosecond
  timestamps). Outputs a length-4 tuple: `(intensity_buy, intensity_sell,
  intensity_ratio, branching_ratio_param)`. The platform uses
  `tuple_sum_component_indices=(0, 1)` — summing `intensity_buy + intensity_sell`
  — then z-scores that scalar over 30 s snapshots to produce `hawkes_intensity_zscore`.
  Note: the `branching_ratio_param` field is the *configured* `α/β = 0.4/0.05 = 8.0`,
  not a runtime MLE estimate. The platform uses fixed parameters, not fitted η.
- `trade_through_rate` → fraction of marketable prints walking the book.
  Passthrough feature `trade_through_rate` at 30 s boundary.
- `ofi_ewma` → same as §5.1. Level `ofi_ewma` used for direction only.
- `spread_z_30d` → gate-only via sensor cache.
- `realized_vol_30s` → `realized_vol_30s_zscore` at 30 s boundary.

**`evaluate()` logic:** Requires `hawkes_intensity_zscore`, `trade_through_rate`,
`ofi_ewma`. Signal fires when:
```python
z >= 2.0          # intensity_zscore_floor
and ttr >= 0.6    # trade_through_floor (fraction of prints walking book)
and abs(ofi) > 1e-9  # OFI non-zero (direction suppression guard)
```
Direction = sign of `ofi_ewma` level. Strength = `min(z / 4.0, 1.0)`.

**Regime gate:** `P(normal) > 0.6 and spread_z_30d < 1.0` to arm;
`P(normal) < 0.4 or spread_z_30d > 2.5 or realized_vol_30s_zscore > 3.5` to disarm.

**Screening implication — critical difference from original prompt:** The
platform does NOT fit a Hawkes MLE per symbol per day. It uses *fixed* parameters
(`α=0.4`, `β=0.05`). The screening should compute the platform's intensity
formula directly and measure whether `hawkes_intensity_zscore ≥ 2.0` events
(combined with `trade_through_rate ≥ 0.6` and OFI agreement) are directionally
predictive at **30 s**. The MLE-based `η ∈ (0.35, 0.80)` filter is a *separate*
validity check: it confirms the asset's true Hawkes dynamics are in the
exploitable range (not noise-only and not explosive). Both checks are needed:
MLE `η` is the mechanism existence test; platform-formula z-score > 2.0 IC is
the implementation validity test. An asset may have `η ∈ (0.35, 0.80)` in MLE
but still produce z-scores that are not predictive when computed with fixed
`α=0.4, β=0.05` if the asset's inter-trade timescales are mismatched to those
parameters. A useful additional metric: mean inter-trade interval vs `1/β = 20s`.
Assets where trades arrive every 1–20 s are well-matched to `β=0.05`.

---

### 5.3 `sig_kyle_drift_v1` — Kyle λ Drift (300 s)

**Sensor pipeline:**

- `kyle_lambda_60s` → `KyleLambda60sSensor(window_seconds=60, min_samples=30)`.
  OLS regression over a rolling 60-second event-time window of trades:
  ```
  Δp_t = λ · Δq_t + ε_t
  λ = (n·Σ(ΔpΔq) - ΣΔp·ΣΔq) / (n·Σ(Δq²) - (ΣΔq)²)
  ```
  where `Δp_t` is trade-to-trade mid-price change, `Δq_t` is tick-rule-signed
  trade size. Provides `kyle_lambda_60s_percentile` and `kyle_lambda_60s_zscore`
  at the 300 s boundary via rolling percentile and z-score features.
- `ofi_ewma` → `ofi_ewma` level and `ofi_ewma_zscore` at 300 s boundary.
- `micro_price` → declared in `depends_on_sensors` (G16 fingerprint requirement)
  but **not read in `evaluate()`**. Still contributes warm-up requirements.
- `spread_z_30d` → gate-only via sensor cache.
- `realized_vol_30s` → `realized_vol_30s_zscore` at 300 s boundary.

**`evaluate()` logic:** Requires `kyle_lambda_60s_percentile` and `ofi_ewma`.
Signal fires when:
```python
lam_pct >= 0.7    # lambda_percentile_floor: λ̂ in top 30% of its rolling distribution
and abs(ofi) >= 0.5  # ofi_threshold: non-trivial signed flow present
```
Direction = sign of `ofi_ewma`. Magnitude uses `kyle_lambda_60s_zscore` when
available, else `(lam_pct - 0.5) * 4.0`. Edge = `min(max(magnitude, 0) * 6.0, 25.0)`.

**Regime gate:** `P(normal) > 0.6 and spread_z_30d <= 1.0` to arm;
`P(normal) < 0.4 or spread_z_30d > 2.0 or realized_vol_30s_zscore > 3.5` to disarm.
The `trend_mechanism.failure_signature` also includes `kyle_lambda_60s_zscore < -1.5`
(λ has collapsed — mechanism absent).

**Screening implication:** The screen must compute Kyle λ using the exact OLS
formula above, over a rolling 60s trade window, and compute its rolling percentile
rank. Signal events occur when the *percentile* exceeds 0.7 (not when λ exceeds
a fixed threshold — the gate is rank-based). The predictability test measures
IC at **300 s** (five-minute forward return). The persistence check (positive
autocorrelation of `λ × sign(OFI)` at 1–3 min lags) confirms that the
information content is durable enough for the 5-minute horizon. Assets where
λ is transiently high but mean-reverts quickly will fail this check. Assets
requiring `λ_median ∈ (5e-7, 5e-5)` bps/share ensure the impact coefficient
is in an economically meaningful range (not so small as to be noise, not so
large as to indicate a structural anomaly).

---

### 5.4 `sig_moc_imbalance_v1` — Scheduled MOC Flow (120 s)

**Sensor pipeline:**

- `scheduled_flow_window` → calendar-driven sensor. In production, it is
  initialised with `event_calendar_path` from `platform.yaml`, which provides
  the MOC window schedule. It outputs a tuple:
  `(active_flag: 0.0/1.0, seconds_to_window_close, flow_direction_prior: -1/0/+1)`.
  The `flow_direction_prior` encodes the published exchange imbalance direction
  (+1 = buy-side imbalance, -1 = sell-side). Platform fans this into snapshot
  keys `scheduled_flow_window_active`, `seconds_to_window_close`,
  `scheduled_flow_window_direction_prior`.
- `ofi_ewma` → `ofi_ewma` level at 120 s boundary. Used as confirmation gate.
- `realized_vol_30s` → `realized_vol_30s_zscore` at 120 s boundary (off-switch only).

**`evaluate()` logic:** Requires all four sensor outputs. Signal fires when:
```python
active >= 0.5                              # window open
and remaining >= 60.0                      # min_seconds_to_close: at least 60s left
and abs(ofi) >= 0.1                        # ofi_agreement_threshold
and (prior > 0.5 and ofi > 0)             # signed agreement: buy
     or (prior < -0.5 and ofi < 0)         # or sell
```
Edge scales with remaining minutes: `min(remaining_min * 1.5, 18.0)`.

**Regime gate:** Unique — does NOT use `P(normal)`. Gate arms on
`scheduled_flow_window_active == 1.0 and seconds_to_window_close > 60` and
disarms on `scheduled_flow_window_active == 0.0 or seconds_to_window_close < 30
or realized_vol_30s_zscore > 3.5`. The HMM engine (`hmm_3state_fractional`) is
still registered but its posteriors are unused in the gate DSL strings.

**Screening implication:** This alpha is unique in that regime does not gate
on microstructure state — it gates on calendar schedule. The screening cannot
replicate the `scheduled_flow_window` sensor (which needs the platform's event
calendar), but it CAN proxy the MOC window period (15:50–16:00 ET) directly.
The key screening tests are:
  (a) Does a pre-close directional signal (depth imbalance + drift acceleration)
      predict the final close price vs 15:50 mid?
  (b) Is the signal sign-consistent across days (not random)?
  (c) Is there a volume acceleration in the 15:50–16:00 window consistent with
      institutional MOC execution?
S&P 500 membership is a **hard gate** — the `scheduled_flow_window` sensor's
`flow_direction_prior` is populated from exchange imbalance data which is most
reliable and structurally large for index constituents.

---

### 5.5 `sig_inventory_revert_v1` — Quote Replenishment Asymmetry (30 s)

**Sensor pipeline:**

- `quote_replenish_asymmetry` → `QuoteReplenishAsymmetrySensor(window_seconds=5,
  min_observations=20)`. On every quote, computes `Δbid_size` and `Δask_size`.
  **Only same-price-level changes** count as replenishment (a new best-bid price
  is a price step, not a depth addition — this is the guard that separates
  replenishment from price improvement). Maintains trailing 5-second sums of
  bid-side and ask-side additions:
  ```
  asymmetry = (bid_adds - ask_adds) / max(bid_adds + ask_adds, ε)
  ```
  Bounded in `[-1, +1]`: positive = bid side replenishes faster (buy pressure
  was absorbed; ask side was depleted). Provides `quote_replenish_asymmetry`
  (scalar) and `quote_replenish_asymmetry_zscore` (rolling z at 30 s boundary).
- `spread_z_30d` → gate-only via sensor cache.
- `quote_hazard_rate` → quote arrival rate in events/second. Gate hard-floor:
  `quote_hazard_rate < 4.0` disarms (sensor units are events/s; 4.0 events/s is
  the minimum for the replenishment signal to be meaningful). Note the gate uses
  the raw `quote_hazard_rate` scalar, not a z-score.
- `realized_vol_30s` → `realized_vol_30s_zscore` at 30 s boundary.

**`evaluate()` logic:** Requires `quote_replenish_asymmetry_zscore` and
`quote_hazard_rate`. Signal fires when:
```python
abs(asym_z) >= 2.0    # asymmetry_z_threshold
hazard >= 4.0         # hazard_floor (events/s)
```
Direction = **FADE** the asymmetry: `LONG` when `asym_z > 0` (bid replenishes
faster → buy pressure absorbed → expect ask-side catch-up = price lift) and
`SHORT` when `asym_z < 0`. Edge incorporates `hazard_weight`, `vol_weight`,
and a `realized_capture_ratio=0.646` discount (analytically derived: at 30s
horizon and 20s half-life, `1 - 0.5^1.5 ≈ 65%` of peak edge is captured).
The `cost_floor_bps = 5.5` gate rejects signals where edge ≤ cost.

**Regime gate:** Requires `abs(quote_replenish_asymmetry_zscore) > 2.0 AND
P(normal) > 0.5`. Also gates off on `spread_z_30d > 2.0`,
`realized_vol_30s_zscore > 3.5`, and `quote_hazard_rate < 4.0`.

**Screening implication:** The replenishment asymmetry formula is very specific
— only *same-price-level* depth changes count. Generic quote imbalance
(ask_size vs bid_size) is a different and less informative measure. The
screening must implement the price-level guard. Episode detection should also
require `spread_z > 1.0` (platform-equivalent: `off_condition spread_z_30d > 2.0`
maps to a softer on-condition). The 30 s reversion must be measured as a
contrarian fade, not a momentum trade. Assets where `quote_hazard_rate` is below
4 events/s on average are structurally unsuitable and will produce no signals.
Expected episode frequency: 3–10 episodes/day on well-fit mid-cap names with
spread 3–20 bps.

---

## 6. Prompt Set

**How to use this section:** The prompts below are designed for direct sequential
paste into a Grok REPL session with Polygon.io access. Paste the SYSTEM CONTEXT
first (or prepend it to Prompt 0). Then paste Prompts 0–6 in order. Each prompt
is self-contained: Prompts 1–5 require only `universe_df` from Prompt 0. Prompt 6
requires `results_benign`, `results_hawkes`, `results_kyle`, `results_moc`, and
`results_inventory` from Prompts 1–5.

Each prompt's computation section is written to match the production sensor
formula from §5. Do not substitute approximations (e.g. volume-ratio OFI,
Lee-Ready trade sign alone for replenishment asymmetry).

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
## Alpha
sig_benign_midcap_v1 | Mechanism: KYLE_INFO | Horizon: 120 s

## Production Signal Logic (from alpha YAML evaluate() block)
Signal fires at each 120-second horizon boundary when:
  abs(ofi_ewma_zscore) >= 0.8                     [entry_threshold_z]
  AND sign(ofi_ewma_zscore) == sign(micro_price_zscore)
  AND micro_price_zscore != 0.0                    [L1 footprint confirmation]
Direction = sign(ofi_ewma_zscore).

Regime gate arms when: P(normal) > 0.5 AND spread_z_30d < 1.5
Regime gate disarms when: P(normal) < 0.35 OR spread_z_30d > 3.0 OR realized_vol_30s_zscore > 4.5

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

### Step 1 — Production OFI Formula (Cont-Kukanov-Weber 2014, top-of-book)
For consecutive quote pairs (q_{t-1}, q_t):
  bid_change = bid_t - bid_{t-1}
  ask_change = ask_t - ask_{t-1}

  ofi_bid =  bid_size_t              if bid_change > 0    (bid improved)
             -bid_size_{t-1}         if bid_change < 0    (bid retreated)
             (bid_size_t - bid_size_{t-1})  if bid_change == 0  (depth changed)

  ofi_ask = -ask_size_t              if ask_change < 0    (ask improved)
             ask_size_{t-1}          if ask_change > 0    (ask retreated)
             -(ask_size_t - ask_size_{t-1}) if ask_change == 0

  OFI_t = ofi_bid + ofi_ask

### Step 2 — EWMA Smoothing (platform default alpha=0.1)
  ofi_ewma_t = 0.1 * OFI_t + 0.9 * ofi_ewma_{t-1}
  (initialise ofi_ewma_0 = OFI_0)

### Step 3 — Micro-Price Deviation
  micro_price_t = (bid_t * ask_size_t + ask_t * bid_size_t) / (bid_size_t + ask_size_t)
  micro_dev_bps_t = (micro_price_t - mid_t) / mid_t * 10000
  Smooth: micro_dev_ewma_t = 0.1 * micro_dev_bps_t + 0.9 * micro_dev_ewma_{t-1}

### Step 4 — 30-Second Horizon Bins
  Resample ofi_ewma and micro_dev_ewma to 30-second bins (last value per bin).

### Step 5 — Rolling Z-Score (30-minute window, 30-second step = 60 bins)
  ofi_zscore_t       = (ofi_ewma_t - rolling60_mean(ofi_ewma)) / rolling60_std(ofi_ewma)
  micro_price_z_t    = (micro_dev_ewma_t - rolling60_mean) / rolling60_std
  spread_z_t         = (spread_bps_t - rolling_30d_median) / rolling_30d_std
  vol_zscore_t       = z-score of 30s realised vol over 60-min rolling window

### Step 6 — Qualifying Signal Bins (production threshold + confirmation)
  qualifying = (
    abs(ofi_zscore_t) >= 0.8
    AND sign(ofi_zscore_t) == sign(micro_price_z_t)
    AND micro_price_z_t != 0.0
    AND spread_z_t < 1.5
    AND vol_zscore_t < 4.5
  )
  direction_t = sign(ofi_zscore_t)

  Exclude bins within 600s of open (09:30–09:40) and 600s of close (14:50–15:00).

### Step 7 — Forward Return at 120-Second Horizon (sign-adjusted)
  forward_return_bps = (mid_{t+120s} - mid_t) / mid_t * 10000 * direction_t
  Compute only for qualifying bins with a valid 120s lookahead.

### Step 8 — Per-Symbol Metrics
  n_qualifying        = count of qualifying bins across n_days
  signal_count_per_day = n_qualifying / n_days
  IC_spearman         = spearmanr(abs(ofi_zscore)[qualifying], forward_return_bps).statistic
  p_value_IC          = two-sided p-value (df = n_qualifying - 2)
  mean_edge_bps       = mean(forward_return_bps)
  hit_rate            = mean(forward_return_bps > 0)
  sharpe_120s         = mean_edge_bps / std(forward_return_bps) * sqrt(252 * 26)

## Scoring
  Gate: n_qualifying >= 15 AND p_value_IC < 0.10

  composite_score = (
    IC_spearman * (1 - p_value_IC)
    * log1p(signal_count_per_day)
    * clip(mean_edge_bps / 5.0, 0, 2)
  )

## Output DataFrame `results_benign`
  [ticker, tier, roll_spread_bps_est, signal_count_per_day, n_qualifying,
   IC_spearman, p_value_IC, mean_edge_bps, hit_rate, sharpe_120s, composite_score]

Print: top-20 by composite_score; count satisfying IC > 0.06 AND p < 0.10 AND edge > 2bps.
Note: signal_count_per_day < 2 suggests the asset's OFI rarely reaches |z|=0.8;
      signal_count_per_day > 30 suggests noisy conditions or spread_z not filtering.
```

---

### Prompt 2 — sig_hawkes_burst_v1

```
## Alpha
sig_hawkes_burst_v1 | Mechanism: HAWKES_SELF_EXCITE | Horizon: 30 s

## Production Signal Logic (from alpha YAML evaluate() block)
Signal fires at each 30-second horizon boundary when:
  hawkes_intensity_zscore >= 2.0           [intensity_zscore_floor]
  AND trade_through_rate >= 0.6            [trade_through_floor]
  AND abs(ofi_ewma) > 1e-9                 [direction guard: OFI non-zero]
Direction = sign(ofi_ewma) level (not z-score).

Regime gate arms when: P(normal) > 0.6 AND spread_z_30d < 1.0
Regime gate disarms when: P(normal) < 0.4 OR spread_z_30d > 2.5 OR realized_vol_30s_zscore > 3.5

## Target Asset Profile
  tier in {"mid", "large", "mega"}
  adtv_usd >= 100M
  Preferred: mean inter-trade interval 1–20 s (matched to 1/beta=20s kernel decay)
  Preferred sectors: Healthcare/Biotech, Tech, Energy, high short-interest names

## Data
Fetch per symbol per day (10 days: 2026-04-14 to 2026-04-25):
  All trades: client.list_trades(ticker, ...) → sip_timestamp, price, size, conditions
  1-second NBBO quotes: client.list_quotes(ticker, ...) for OFI computation

## Computation: Part A — Mechanism Validity Check (Hawkes MLE)
Purpose: confirm the asset's true trade dynamics have exploitable self-excitation
(η ∈ [0.35, 0.80]). This validates mechanism existence independently of the
platform's fixed-parameter implementation.

  Model: λ(t) = μ + Σ_{t_i < t} α_mle * exp(-β_mle * (t - t_i))

  Log-likelihood = -μT - (α_mle/β_mle)*N + Σ_i log(μ + α_mle * R_i)
    R_i = (R_{i-1} + 1) * exp(-β_mle * Δt_i)
    T = 23400s, N = trade count per day

  Optimise (μ, α_mle, β_mle) via scipy.optimize.minimize L-BFGS-B.
  Bounds: μ ∈ (0.001, 100), α_mle ∈ (0, 50), β_mle ∈ (0.01, 500).
  η_day = α_mle / β_mle per day. Reject day if η >= 1.0 or se(η)/η > 0.30.
  η_mean = mean(η) across valid days. η_cv = std(η)/mean(η).

  Gate: η_mean ∈ [0.35, 0.80] AND η_cv < 0.30.
  Also compute: mean_inter_trade_interval_s = T / N (should be in [1, 20] s for
  good match with platform's β=0.05 decay constant, where 1/β = 20 s).

## Computation: Part B — Platform-Formula Intensity (production match)
Purpose: verify the platform's fixed-parameter sensor (α=0.4, β=0.05) produces
z-scores ≥ 2.0 that are directionally predictive at 30 s on this asset.

  Using the same fixed parameters as HawkesIntensitySensor:
    alpha_fixed = 0.4    # platform default
    beta_fixed  = 0.05   # platform default (1/beta = 20s decay)
    mu_fixed    = 0.0    # platform default baseline

  ### Two-sided intensity (buy and sell separately, tick rule for side classification)
  For each trade at time t_i, classify side via tick rule:
    side = +1 (buy)  if price_i > price_{i-1}
    side = -1 (sell) if price_i < price_{i-1}
    side = prior_side if price_i == price_{i-1}  (default +1 on first trade)

  Between trades (apply decay to both sides):
    lambda_buy(t)  = mu_fixed + (lambda_buy(t_last) - mu_fixed) * exp(-beta_fixed * delta_t_s)
    lambda_sell(t) = mu_fixed + (lambda_sell(t_last) - mu_fixed) * exp(-beta_fixed * delta_t_s)

  On a buy trade:  lambda_buy(t_i) = lambda_buy(t_i⁻) + alpha_fixed
  On a sell trade: lambda_sell(t_i) = lambda_sell(t_i⁻) + alpha_fixed

  Scalar intensity per trade: lambda_scalar = lambda_buy + lambda_sell

  ### 30-Second Bins
  Resample lambda_scalar to 30-second bins (last value per bin).

  ### Rolling Z-Score (30-minute window = 60 bins)
  hawkes_intensity_zscore_t = (lambda_scalar_t - rolling60_mean) / rolling60_std

  ### OFI for direction (same formula as §Prompt 1 Step 1-2)
  Compute ofi_ewma using CKW formula with alpha=0.1.

  ### Trade-Through Rate (30-second bins)
  Per 30s bin: trade_through_rate = fraction of trades where price moved
  beyond the prevailing best bid (buy-side) or best ask (sell-side).
  Proxy: fraction of trades classified as aggressive (price > mid for buy,
  price < mid for sell) among all trades in the bin.

  ### Platform-Qualifying Signal Events
  platform_qualifying = (
    hawkes_intensity_zscore_t >= 2.0
    AND trade_through_rate_t >= 0.6
    AND abs(ofi_ewma_t) > 1e-9
  )
  direction_t = sign(ofi_ewma_t)

  ### Forward Return at 30-Second Horizon
  forward_return_bps = (mid_{t+30s} - mid_t) / mid_t * 10000 * direction_t
  Compute for qualifying bins only.

  ### Per-Symbol Metrics (Part B)
  platform_n_qualifying    = count of platform_qualifying bins across 10 days
  platform_freq_per_day    = platform_n_qualifying / 10
  directional_consistency  = mean(forward_return_bps > 0) on qualifying bins
  mean_edge_30s_bps        = mean(forward_return_bps) on qualifying bins
  IC_spearman_platform     = spearmanr(hawkes_intensity_zscore[qualifying], forward_return_bps)

## Scoring
  Gate: η_mean ∈ [0.35, 0.80] AND η_cv < 0.30    (Part A mechanism check)
        AND platform_freq_per_day >= 3              (Part B: signals will fire)
        AND directional_consistency > 0.60          (Part B: directional edge)

  composite_score = (
    directional_consistency
    * log1p(platform_freq_per_day)
    * clip(mean_edge_30s_bps / 3.0, 0, 3)
    * (1 - η_cv)
    * (IC_spearman_platform > 0.04)   [hard zero if platform formula shows no IC]
  )

## Output DataFrame `results_hawkes`
  [ticker, η_mean, η_cv, mean_inter_trade_interval_s, platform_freq_per_day,
   platform_n_qualifying, directional_consistency, mean_edge_30s_bps,
   IC_spearman_platform, composite_score]

Print: top-20 by composite_score; histogram of η_mean across all tickers;
       flag tickers where mean_inter_trade_interval_s > 20 (poorly matched to beta=0.05).
```

---

### Prompt 3 — sig_kyle_drift_v1

```
## Alpha
sig_kyle_drift_v1 | Mechanism: KYLE_INFO | Horizon: 300 s (5 min)

## Production Signal Logic (from alpha YAML evaluate() block)
Signal fires at each 300-second horizon boundary when:
  kyle_lambda_60s_percentile >= 0.7        [lambda_percentile_floor]
  AND abs(ofi_ewma) >= 0.5                 [ofi_threshold: normalised OFI level]
Direction = sign(ofi_ewma) level.
Edge magnitude uses kyle_lambda_60s_zscore when available.

Regime gate arms when: P(normal) > 0.6 AND spread_z_30d <= 1.0
Regime gate disarms when: P(normal) < 0.4 OR spread_z_30d > 2.0 OR realized_vol_30s_zscore > 3.5
Additional failure signature: kyle_lambda_60s_zscore < -1.5 (mechanism collapsed)

## Target Asset Profile
  tier in {"large", "mega"}
  adtv_usd >= 500M
  Active options market: indicative total open interest > 100,000 contracts
  λ_median ∈ (5e-7, 5e-5) bps/share (economically meaningful range)

## Data
Fetch per symbol per day (all 18 days):
  1-second trades: client.list_trades(ticker, ...) → for Kyle λ OLS
  1-second NBBO quotes: for OFI and spread
  1-minute aggregate bars: client.get_aggs(ticker, 1, "minute", ...) for bar-level checks

## Computation

### Step 1 — Production Kyle λ Formula (KyleLambda60sSensor exact OLS)
For each trade at time t_i, maintain a deque of samples older than 60 seconds evicted.
On each trade:
  delta_p_t = mid_price_t - mid_price_{t-1}   (trade-to-trade mid-price change)
  delta_q_t = signed_size_t                    (tick-rule sign * size)
  Tick rule: +1 if price_i > price_{i-1}, -1 if below, inherit prior if equal; default +1.

Running OLS sums in 60s window (Welford-style eviction of expired samples):
  n, Sdp, Sdq, Sdpdq, Sdq2 = count and running sums
  On add: n++, Sdp += dp, Sdq += dq, Sdpdq += dp*dq, Sdq2 += dq^2
  On evict: n--, subtract evicted values

  Denominator D = n * Sdq2 - Sdq^2
  λ_t = (n * Sdpdq - Sdp * Sdq) / D   if D != 0 AND n >= 30 (min_samples)
       = NaN otherwise

### Step 2 — 5-Minute Horizon Bins
Resample λ_t (last valid value per 5-min bin) and ofi_ewma_t (from CKW formula,
alpha=0.1, then 5-min resample) to 300-second bins.

### Step 3 — Rolling Percentile and Z-Score of Kyle λ
Over a rolling 18-day x 6.5h x 12bins/hr = ~1430 bins window:
  kyle_lambda_60s_percentile_t = percentile_rank(λ_t, trailing_window)
  kyle_lambda_60s_zscore_t     = (λ_t - rolling_mean) / rolling_std

### Step 4 — Platform-Qualifying Signal Events
  platform_qualifying = (
    kyle_lambda_60s_percentile_t >= 0.7
    AND abs(ofi_ewma_t) >= 0.5
    AND lambda_t > 0    (OLS positive constraint)
  )
  direction_t = sign(ofi_ewma_t)

### Step 5 — Forward Return at 300-Second Horizon
  forward_return_bps = (mid_{t+300s} - mid_t) / mid_t * 10000 * direction_t
  Compute for qualifying bins only.

### Step 6 — Drift Persistence (mechanism durability check)
  info_signal_b = lambda_t * signed_volume_in_5min_bin   (proxy for λ×OFI contribution)
  AC_k = autocorr(info_signal, lag=k) for k in {1, 2, 3, 5, 10}
  persistence_score = mean(AC_1, AC_2, AC_3)
  drift_vs_revert_ratio = mean(AC_1..3) / max(abs(mean(AC_5, AC_10)), 1e-9)

### Step 7 — Per-Symbol Metrics
  λ_median, λ_day_cv (CV of daily median λ across 18 days)
  platform_n_qualifying, platform_freq_per_day
  mean_edge_300s_bps = mean(forward_return_bps) on qualifying bins
  IC_spearman_300s   = spearmanr(kyle_lambda_60s_percentile[qualifying], forward_return_bps)
  persistence_score, drift_vs_revert_ratio

## Scoring
  Gate: λ_median ∈ (5e-7, 5e-5)
        AND persistence_score > 0.08
        AND platform_freq_per_day >= 1  (≥ 1 qualifying event/day on average)

  composite_score = (
    persistence_score * 3.0
    + clip(IC_spearman_300s, 0, 1)
    - λ_day_cv * 0.5
  ) * (drift_vs_revert_ratio > 1.0)   [hard zero if reversion-dominated]

## Output DataFrame `results_kyle`
  [ticker, tier, λ_median, λ_day_cv, persistence_score, drift_vs_revert_ratio,
   IC_spearman_300s, platform_freq_per_day, mean_edge_300s_bps, composite_score]

Print: top-20 by composite_score; scatter λ_median vs persistence_score coloured by tier;
       flag any ticker appearing in top-10 of both results_benign and results_kyle
       (KYLE_INFO overlap is structurally interesting: both alphas may co-activate).
```

---

### Prompt 4 — sig_moc_imbalance_v1

```
## Alpha
sig_moc_imbalance_v1 | Mechanism: SCHEDULED_FLOW | Horizon: 120 s

## Production Signal Logic (from alpha YAML evaluate() block)
Signal fires at 120-second horizon boundaries during the active MOC window when:
  scheduled_flow_window_active >= 0.5      (window open)
  AND seconds_to_window_close >= 60        [min_seconds_to_close]
  AND abs(ofi_ewma) >= 0.1                 [ofi_agreement_threshold]
  AND ((prior > 0.5 AND ofi > 0) OR (prior < -0.5 AND ofi < 0))  [sign agreement]
Direction = sign(prior * ofi).
Edge = min(remaining_minutes * 1.5, 18.0) bps.

IMPORTANT: The regime gate for this alpha is calendar-driven, NOT HMM-based.
  on_condition:  scheduled_flow_window_active == 1.0 AND seconds_to_window_close > 60
  off_condition: window inactive OR remaining < 30s OR realized_vol_30s_zscore > 3.5
The HMM engine is registered but posteriors are NOT used in gate expressions.
S&P 500 membership is a HARD REQUIREMENT — the flow_direction_prior from exchange
imbalance data is structurally meaningful only for index constituents.

## Target Asset Profile
  tier in {"mega", "large"}
  is_sp500 = True   [HARD GATE: score = 0 for non-S&P 500 names]
  adtv_usd >= 1B    (large absolute MOC volume needed for exploitable drift)

## Data
Fetch per symbol per day (all 18 trading days):
  1-minute bars: client.get_aggs(ticker, 1, "minute", ...)
  1-second bars for 15:45–16:05: client.get_aggs(ticker, 1, "second", ...)
  1-second NBBO quotes for 15:45–16:05: client.list_quotes(ticker, ...)
  Closing auction print: trades with condition code 6 or 38 (or nearest trade to 16:00)

## Computation

### Step 1 — Reference Prices (from 1-second data)
  mid_1550 = mid at 15:50:00 ET (last quote before 15:50:01)
  mid_1555 = mid at 15:55:00 ET
  mid_1559 = mid at 15:59:00 ET
  close_px = closing auction print (condition 6/38); fallback: last trade at/after 15:59:55

### Step 2 — MOC Imbalance Proxy
(Polygon does not publish MOC imbalance feeds; use three complementary proxies.)

  (i)  vol_accel = volume[15:50–16:00] / volume[15:40–15:50]
       (> 2.0 indicates institutional MOC acceleration)

  (ii) depth_imbalance_1555 = (bid_size_1555 - ask_size_1555) / (bid_size_1555 + ask_size_1555)
       (positive = buy-side demand pressure at 15:55)

  (iii) drift_1550_1600 = (mid_1559 - mid_1550) / mid_1550 * 10000  (bps)
        drift_1540_1550 = (mid_1550 - mid at 15:40) / mid_at_1540 * 10000
        drift_accel = drift_1550_1600 - drift_1540_1550

  imbalance_proxy = (
    0.4 * depth_imbalance_1555
    + 0.4 * sign(drift_accel) * min(abs(drift_accel) / 5.0, 1.0)
    + 0.2 * (vol_accel > 2.0)
    - 0.5
  )
  signal_direction = sign(imbalance_proxy)

### Step 3 — OFI Confirmation (production requirement)
  Compute ofi_ewma in the 15:50–16:00 window using CKW formula, alpha=0.1.
  ofi_confirmation = (sign(ofi_ewma_mean_1550_1600) == sign(imbalance_proxy))
  (This mirrors the production require: flow_direction_prior and OFI must agree in sign.)

### Step 4 — Signal Measurement (sign-adjusted)
  alpha_return_bps = (close_px - mid_1550) / mid_1550 * 10000 * signal_direction
  net_alpha_bps    = alpha_return_bps - (roll_spread_bps_est / 2 + 1.0)
  overnight_reversion_bps = (next_open - close_px) / close_px * 10000

### Step 5 — Per-Symbol Metrics (18 days)
  mean_alpha_return_bps
  net_alpha_bps_mean
  hit_rate           = mean(net_alpha_bps > 0)
  imbalance_IC       = spearmanr(imbalance_proxy, alpha_return_bps).statistic
  ofi_confirm_rate   = fraction of days where ofi_confirmation == True
  mean_vol_accel
  overnight_reversion_fraction = mean(sign(overnight_reversion_bps) != signal_direction)

## Scoring
  Gate: hit_rate > 0.50
        AND imbalance_IC > 0.10
        AND mean_alpha_return_bps > 1.5
        AND is_sp500 = True

  composite_score = (
    imbalance_IC * 2
    + hit_rate * 2
    - overnight_reversion_fraction * 1.5
    + (mean_vol_accel > 2.5) * 0.5
    + ofi_confirm_rate * 1.0
  ) * is_sp500   [hard zero for non-S&P 500]

## Output DataFrame `results_moc`
  [ticker, tier, sector, is_sp500, mean_alpha_return_bps, net_alpha_bps_mean,
   hit_rate, imbalance_IC, ofi_confirm_rate, mean_vol_accel,
   overnight_reversion_fraction, composite_score]

Print: top-20 by composite_score; sector breakdown of top-20;
       flag names where ofi_confirm_rate < 0.5 (OFI and imbalance proxy disagreeing
       — these will fail the production signal's sign-agreement gate on many days).
```

---

### Prompt 5 — sig_inventory_revert_v1

```
## Alpha
sig_inventory_revert_v1 | Mechanism: INVENTORY | Horizon: 30 s

## Production Signal Logic (from alpha YAML evaluate() block)
Signal fires at 30-second horizon boundaries when:
  abs(quote_replenish_asymmetry_zscore) >= 2.0    [asymmetry_z_threshold]
  AND quote_hazard_rate >= 4.0                     [hazard_floor in events/s]
Direction = FADE the asymmetry:
  asym_z > 0 (bid replenishes faster → buy pressure absorbed) → LONG
  asym_z < 0 (ask replenishes faster → sell pressure absorbed) → SHORT
Edge is further discounted by hazard_weight, vol_taper, AND realized_capture_ratio=0.646
(analytically: 1 - 0.5^(30/20) ≈ 65% of peak edge captured at 30s with 20s half-life).
A hard cost_floor_bps=5.5 rejects signals where edge <= total cost.

Regime gate arms when: abs(asymmetry_zscore) > 2.0 AND P(normal) > 0.5
Regime gate disarms when: P(normal) < 0.3 OR asymmetry_z < 1.7 OR spread_z_30d > 2.0
                          OR realized_vol_30s_zscore > 3.5 OR quote_hazard_rate < 4.0

## Target Asset Profile
  tier in {"mid", "large"}
  roll_spread_bps_est in [3, 20]
  adtv_usd in [100M, 3B]
  Exclude: quote_to_trade_ratio > 500 (HFT-dominated; replenishment signal is noise)

## Data
Fetch per symbol per day (10 days: 2026-04-14 to 2026-04-25):
  1-second NBBO quotes and 1-second trades.

## Computation

### Step 1 — Production Quote Replenishment Asymmetry Formula
(QuoteReplenishAsymmetrySensor, window_seconds=5, min_observations=20)

For consecutive quote pairs (q_{t-1}, q_t), applying the same-price-level guard:
  bid_add_t = max(bid_size_t - bid_size_{t-1}, 0)   IF bid_t == bid_{t-1} ELSE 0
  ask_add_t = max(ask_size_t - ask_size_{t-1}, 0)   IF ask_t == ask_{t-1} ELSE 0
  [CRITICAL: only depth additions at the SAME price level count as replenishment.
   A new best-bid price is a price improvement, not replenishment of the old level.]

Maintain rolling 5-second sums:
  bid_adds_5s = sum(bid_add_t) over trailing 5 seconds of event time
  ask_adds_5s = sum(ask_add_t) over trailing 5 seconds of event time

  asymmetry_t = (bid_adds_5s - ask_adds_5s) / max(bid_adds_5s + ask_adds_5s, 1e-12)
  Bounded in [-1, +1].
  Warm: True once >= 20 quotes seen AND >= 1 add recorded on each side.

### Step 2 — Quote Hazard Rate
  quote_hazard_rate_t = rolling count of NBBO events per second over 5s window
  (events/s; platform gate threshold: 4.0 events/s)

### Step 3 — 30-Second Horizon Bins
  Resample asymmetry_t and quote_hazard_rate_t to 30-second bins (last value per bin).

### Step 4 — Rolling Z-Score of Replenishment Asymmetry (60-min window = 120 bins)
  asymmetry_zscore_t = (asymmetry_t - rolling120_mean) / rolling120_std

### Step 5 — Spread Z-Score (30d reference, per platform spread_z_30d sensor)
  spread_bps_t = (ask_t - bid_t) / mid_t * 10000
  spread_z_t   = (spread_bps_t - daily_median) / daily_std  (proxy for 30d)

### Step 6 — Platform-Qualifying Signal Events
  platform_qualifying = (
    abs(asymmetry_zscore_t) >= 2.0
    AND quote_hazard_rate_t >= 4.0
    AND spread_z_t <= 2.0
  )
  direction_t = sign(asymmetry_zscore_t)   [FADE the asymmetry]

### Step 7 — Reversion Measurement at Exact 30-Second Horizon
  entry_mid = mid at qualifying bin close
  For h in {15, 30, 60, 120} seconds:
    reversion_h_bps = -(mid_{t+h} - entry_mid) / entry_mid * 10000 * direction_t
  cost_bps = spread_bps_t_entry / 2 + 0.5
  net_reversion_30s = reversion_30s_bps - cost_bps

  spread_norm_speed_s: first t > entry where spread_bps < rolling_mean + 0.5*rolling_std

### Step 8 — Per-Symbol Metrics (10 days)
  episode_freq_per_day      = platform_n_qualifying / 10
  mean_net_reversion_30s    = mean(net_reversion_30s) on qualifying bins
  hit_rate_30s              = mean(net_reversion_30s > 0)
  hit_rate_120s             = mean(reversion_120s_bps > 0)
  spread_norm_speed_s       = mean(spread_norm_speed_s)
  decay_shape_score         = mean(reversion_30s_bps > reversion_15s_bps
                                    AND reversion_60s_bps > reversion_30s_bps)
  mean_quote_hazard_rate    = mean(quote_hazard_rate across all 30s bins)

## Scoring
  Gate: episode_freq_per_day >= 3
        AND mean_net_reversion_30s >= 1.0
        AND hit_rate_30s >= 0.55
        AND spread_norm_speed_s < 90

  composite_score = (
    mean_net_reversion_30s * 2
    * hit_rate_30s
    * log1p(episode_freq_per_day)
    * (90 / max(spread_norm_speed_s + 1, 1))
  ) * decay_shape_score   [hard zero without monotone reversion profile]

## Output DataFrame `results_inventory`
  [ticker, tier, roll_spread_bps_est, mean_quote_hazard_rate, episode_freq_per_day,
   mean_net_reversion_30s, hit_rate_30s, hit_rate_120s, spread_norm_speed_s,
   decay_shape_score, composite_score]

Print: top-20 by composite_score; reversion decay profile (mean per horizon h={15,30,60,120})
       for top-5 names; flag tickers where mean_quote_hazard_rate < 6 events/s
       (marginal for the hazard_rate >= 4 gate — will frequently disarm in production).
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
For each ticker apply the production-grounded gates:
  eligible_benign    = (composite_score_benign > p50) AND IC_spearman > 0.04
  eligible_hawkes    = (composite_score_hawkes > p50) AND η_mean ∈ [0.35, 0.80]
                       AND IC_spearman_platform > 0.04   [platform formula IC check]
  eligible_kyle      = (composite_score_kyle > p50) AND drift_vs_revert_ratio > 1.0
  eligible_moc       = (composite_score_moc > p50) AND is_sp500 AND ofi_confirm_rate >= 0.5
  eligible_inventory = (composite_score_inventory > p50) AND decay_shape_score > 0.5
  n_alphas_eligible  = sum of above 5 binary flags

## Step 3 — Regime Compatibility Annotation
Derived from alpha hypothesis and regime_gate on_condition in YAML:
  sig_benign_midcap_v1    → preferred_regime: "normal"    (P(normal) > 0.5 gate)
  sig_hawkes_burst_v1     → preferred_regime: "normal"    (P(normal) > 0.6 gate, tight spread)
  sig_kyle_drift_v1       → preferred_regime: "normal"    (P(normal) > 0.6 gate)
  sig_moc_imbalance_v1    → preferred_regime: "any"       (calendar-driven gate; HMM unused)
  sig_inventory_revert_v1 → preferred_regime: "normal"    (P(normal) > 0.5 gate)
Note: sig_hawkes_burst_v1 requires TIGHTER spread and HIGHER P(normal) than the
benign and kyle alphas; it is the most restrictive on orderly market conditions.

## Step 4 — Priority Ranking
Sort by: n_alphas_eligible DESC, then sum of normalised composite scores DESC.

## Output
1. Top-30 tickers:
   [ticker, tier, sector, n_alphas_eligible, eligible_alphas (list),
    preferred_regimes (dict), all five composite scores]

2. Heatmap-ready matrix: tickers (rows) × 5 alphas (columns), value = composite_score.

3. "Starter deployment shortlist":
   n_alphas_eligible >= 2 AND at least one composite score in top quartile.
   Note overlap between benign + kyle (both KYLE_INFO, both prefer P(normal) > 0.6):
   these two alphas on the same asset provide correlated L1 footprint reads at
   different horizons (120s vs 300s) — useful for multi-horizon validation.

4. YAML-formatted per-alpha top-5:
   alpha_asset_mapping:
     sig_benign_midcap_v1:    [TICKER1, TICKER2, ...]
     sig_hawkes_burst_v1:     [...]
     sig_kyle_drift_v1:       [...]
     sig_moc_imbalance_v1:    [...]
     sig_inventory_revert_v1: [...]
```

---

## 7. Output → Deployment Path

```
Prompt 6 YAML output
       ↓
Inject into platform.yaml:
  symbols: [TICKER1, TICKER2, ...]
  alpha_specs:
    - alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml
    - ...
       ↓
uv run pytest tests/integration/test_phase4_e2e.py   (smoke check: does it boot?)
       ↓
uv run python scripts/smoke_pipeline.py               (does it produce signals?)
       ↓
Feelies deterministic backtest sweep per (alpha, asset) pair
  → parity hashes lock results
  → pairs passing acceptance criteria graduate to alpha YAML:
       ↓
asset_eligibility: block in each alpha's .alpha.yaml
  (permanent pre-flight filter for production deployment)
```

Each (alpha, asset) pair is run as a **separate** deterministic backtest. Parity
hashes lock in results from the first valid run; subsequent runs must match
exactly (determinism invariant). Pairs that fail cost arithmetic (`margin_ratio`
not achieved) or produce DSR < 1.0 are dropped without graduating.

---

## 8. Key Design Principles

### 8.1 Platform Design Principles

**Anti-overfitting.** Eligibility criteria derive from mechanism hypothesis and
static asset characteristics — not from backtest P&L. The screen identifies
assets where the mechanism *should* work; the deterministic backtest verifies it
*does* work with exact platform sensors, HMM calibration, and cost arithmetic.

**Production-exact sensor math.** The screening prompts compute OFI with the
Cont-Kukanov-Weber top-of-book formula, Kyle λ with OLS over a 60-second rolling
trade window, Hawkes intensity with the platform's fixed `α=0.4, β=0.05`
parameters, and quote replenishment asymmetry with the same-price-level depth-add
guard. Approximating any of these with simpler formulas risks selecting assets
where the production sensor will never warm or never cross its threshold.

**Threshold correspondence.** Qualifying events in screening use the same numeric
thresholds as the production `evaluate()` function: `|ofi_z| ≥ 0.8`,
`λ_pct ≥ 0.70`, `hawkes_z ≥ 2.0`, `|asym_z| ≥ 2.0`. IC measured over all bins
is not meaningful; IC measured over qualifying bins is.

**Regime annotation from theory.** All five alphas gate on `P(normal) > threshold`
in their `on_condition` (with `sig_moc_imbalance_v1` additionally requiring a
calendar window). Preferred regime is annotated as `"normal"` for all four
HMM-gated alphas. `sig_moc_imbalance_v1` is `"any"` because it arms on a
calendar schedule, not on microstructure state.

**Multi-alpha overlap as priority signal.** Assets eligible for both
`sig_benign_midcap_v1` and `sig_kyle_drift_v1` share the `KYLE_INFO` mechanism
family across two horizons — structurally the richest validation possible. Assets
eligible for `sig_hawkes_burst_v1` in addition have episodic burst dynamics
layered on top of persistent informed flow; these are the highest-conviction
names for the backtest sweep.

---

### 8.2 Grok Behavior Constraints

These rules govern how Grok must execute the prompts in §6. They are not
optional guidance — they are quality assurance requirements. Any violation
invalidates the screening result; the resulting YAML must not be injected into
`platform.yaml`.

**No formula improvisation.** Grok must execute the exact formula specified in
each prompt. It must not substitute, simplify, or "improve" any sensor
computation: not the CKW OFI casework, not the EWMA `α=0.1`, not the Hawkes
fixed `α=0.4 / β=0.05`, not the Kyle OLS 60-second window, not the same-price-
level replenishment guard. If Grok believes an alternative formula is superior,
it must execute the specified formula as written and append a clearly labelled
comment noting the concern — it must never silently substitute.

**No data hallucination.** If an API call returns empty data or fewer records
than the quality floor (< 50,000 quotes for a symbol-day), Grok must drop that
symbol-day, log the drop explicitly (`DROPPED: {ticker} {date} — reason`), and
continue. It must never invent data, interpolate absent records, or populate
a metric with a "reasonable" assumed value. A fabricated row is categorically
worse than a missing row.

**No silent NaN imputation.** If a sensor value is undefined — insufficient
trades for Kyle λ OLS, zero denominator in asymmetry, no qualifying bins for IC
— that value must be `NaN` in the output DataFrame and excluded from all
aggregate metrics. Filling with `0`, mean, or any imputed value is prohibited.

**No threshold adjustment.** Grok must use the exact numeric thresholds from
the prompt: `|ofi_z| ≥ 0.8`, `λ_pct ≥ 0.70`, `hawkes_z ≥ 2.0`,
`|asym_z| ≥ 2.0`, `hazard ≥ 4.0`. It must not relax or tighten a threshold
because the observed distribution makes it appear "too strict" or "too loose"
for a particular asset. Threshold changes break the production correspondence
that is the entire point of the screening.

**No name bias.** Grok must not use training-time knowledge of specific tickers
(sector reputation, well-known volatility, analyst coverage, market prominence)
to influence rankings. Rankings are determined solely by the computed metrics.
If a result is surprising — a prominent name ranks low, an obscure name ranks
high — Grok may note the observation in a print statement but must not adjust
any score or gate.

**No scope leakage between prompts.** Each prompt computes only what it
declares, using only the inputs it specifies. Prompt 1 must not incorporate
results from Prompt 2. Prompt 6 must use only `results_benign`, `results_hawkes`,
`results_kyle`, `results_moc`, `results_inventory` from Prompts 1–5 — no
additional data fetches, no enrichment from Grok's training knowledge about
individual tickers.

**Mandatory audit trail.** Before any computation, each prompt must print the
count of raw records fetched per symbol (quotes, trades) and the count after
data quality filtering. This exposes silent data-quality failures before they
corrupt downstream metrics.

**Failure isolation.** If processing fails for one ticker (API error, numerical
error, insufficient data), Grok must catch the exception, log it with the
reason, and continue with the remaining tickers. A single failure must not abort
the prompt.

**Output column fidelity.** Output DataFrame column names must exactly match
those specified in each prompt's Output section. Grok must not rename, merge, or
add columns. The YAML block in Prompt 6 must use exactly the keys shown
(`alpha_asset_mapping`, `sig_benign_midcap_v1`, etc.) — these map directly into
`platform.yaml` and any key mismatch causes a Feelies parse error.

**Deterministic execution.** Any operation using random sampling (e.g.,
bootstrap confidence intervals) must fix a seed (`random_state=42`). Results
must be bit-reproducible on a second run over the same data.
