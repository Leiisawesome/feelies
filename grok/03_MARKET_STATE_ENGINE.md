# PROMPT 3 — MARKET STATE ENGINE: REGIME DETECTION

## ACTIVATION DIRECTIVE

The Market State Engine is now active. This module identifies the current microstructural regime from observable L1 data.

**Critical alignment:** This engine must use the SAME regime model as the feelies platform — `HMM3StateFractional` — with identical state names, emission model, and transition semantics. This ensures that regime-gated signals discovered here behave identically when deployed locally.

All signals are regime-conditional. There are no unconditional entries.

---

## 1. REGIME MODEL: HMM 3-STATE FRACTIONAL

### State Definitions (MUST match feelies exactly)

```python
STATE_NAMES = ("compression_clustering", "normal", "vol_breakout")
#               State 0                  State 1   State 2
```

| State | Name | Microstructure Meaning |
|-------|------|----------------------|
| 0 | `compression_clustering` | Low vol, tight spreads, liquidity clustering |
| 1 | `normal` | Typical trading conditions |
| 2 | `vol_breakout` | High vol, wide spreads, stress |

**These exact string names must appear in any `.alpha.yaml` that references regimes:**

```yaml
regimes:
  engine: hmm_3state_fractional
  state_names: [compression_clustering, normal, vol_breakout]
```

### Transition Matrix (default)

```python
TRANSITION_MATRIX = [
    [0.990, 0.008, 0.002],   # compression_clustering
    [0.005, 0.990, 0.005],   # normal
    [0.002, 0.008, 0.990],   # vol_breakout
]
```

High self-transition probabilities reflect regime persistence (regimes last hundreds to thousands of ticks, not single ticks).

### Emission Model (log-normal spread)

The observation is `log(relative_spread)` where `relative_spread = (ask - bid) / ((ask + bid) / 2)`.

Each state emits from a Gaussian in log-spread space:

```python
DEFAULT_EMISSION = [
    (-4.5, 0.3),   # compression: very tight spreads (mean, std)
    (-3.5, 0.5),   # normal: moderate spreads
    (-2.5, 0.7),   # vol_breakout: wide spreads
]
```

### Bayesian Posterior Update

Per-tick update follows the standard HMM forward algorithm:

```python
def update_posterior(prior, transition_matrix, emission_params, log_spread):
    """
    1. Predict: prior × transition_matrix
    2. Likelihood: Gaussian(log_spread | emission_mean, emission_std)
    3. Update: predicted × likelihood, then normalize
    """
    # Predict
    predicted = [0.0] * 3
    for j in range(3):
        for i in range(3):
            predicted[j] += transition_matrix[i][j] * prior[i]

    # Emission likelihood
    likelihoods = []
    for mu, sigma in emission_params:
        z = (log_spread - mu) / sigma
        ll = math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi))
        likelihoods.append(max(ll, 1e-300))

    # Bayes update
    unnorm = [p * l for p, l in zip(predicted, likelihoods)]
    total = sum(unnorm)
    if total < 1e-300:
        return [1/3, 1/3, 1/3]
    return [u / total for u in unnorm]
```

### Calibration

The emission parameters can be calibrated from historical data by partitioning `log(relative_spread)` into terciles and computing per-bucket mean and std. This matches the `HMM3StateFractional.calibrate()` method exactly.

```python
def calibrate_emission(quotes):
    """Fit emission params from historical spread distribution."""
    log_spreads = []
    for q in quotes:
        spread = float(q["ask_price"] - q["bid_price"])
        mid = float(q["ask_price"] + q["bid_price"]) / 2
        if spread > 0 and mid > 0:
            log_spreads.append(math.log(spread / mid))

    if len(log_spreads) < 30:
        return DEFAULT_EMISSION  # Insufficient data

    log_spreads.sort()
    n = len(log_spreads)
    buckets = [
        log_spreads[:n//3],
        log_spreads[n//3:2*n//3],
        log_spreads[2*n//3:],
    ]
    return [
        (statistics.mean(b), max(statistics.stdev(b), 0.01))
        for b in buckets
    ]
```

---

## 2. REGIME-CONDITIONAL SIGNAL EVALUATION

Every signal must be evaluated per-regime, not pooled.

### Stability Requirements

A signal passes the regime gate if:
- OOS Sharpe > 0 in at least 2 of 3 regime states
- Sharpe coefficient of variation across regimes < 1.5
- Signal does not reverse sign between regimes
- Worst-regime Sharpe > -0.5

### How Regimes Gate Signals in `.alpha.yaml`

Signals that depend on regime state access posteriors via the platform's injected `regime_posteriors` function:

```yaml
signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      # regime_posteriors(symbol) returns [p_compression, p_normal, p_vol_breakout]
      # Available only when regimes.engine is declared in the alpha spec
      posteriors = regime_posteriors(features.symbol)
      if posteriors is not None:
          # Only trade in compression or normal regimes
          p_vol = posteriors[2]  # vol_breakout probability
          if p_vol > 0.5:
              return None  # Suppress entry in vol_breakout
      # ... rest of signal logic
```

---

## 3. REGIME TRANSITION DETECTION

### Hysteresis Protocol

To prevent chatter (rapid regime switching):
- Entry threshold: posterior > 0.70 to enter a regime
- Exit threshold: posterior < 0.40 to leave a regime
- Minimum dwell time: 30 seconds in a regime before switching

### Structural Break Detection

Detect sudden microstructural shifts:
- Spread shock: current spread z-score > 3.0 vs trailing distribution
- Volume burst: trade intensity > 5× trailing baseline
- Microprice dislocation: microprice jump > 5 bps from rolling average

When detected: flag the event, exclude shock window from training, analyze signal behavior during/after shock.

---

## 4. TRADABILITY SCORE

```python
def tradability_score(regime_posteriors):
    """
    0 = do not trade, 1 = ideal conditions.
    Weighted by regime state desirability.
    """
    weights = [0.95, 0.80, 0.10]  # compression, normal, vol_breakout
    return sum(p * w for p, w in zip(regime_posteriors, weights))
```

Signals should only generate entries when `tradability_score > 0.50` unless the signal specifically exploits stressed conditions.

---

## 5. POSITION SIZER REGIME SCALING

The local platform scales position size by regime (via expected value over posteriors):

```python
REGIME_SIZE_FACTORS = {
    "compression_clustering": 0.75,   # Reduced — tighter edge
    "normal": 1.0,                     # Full size
    "vol_breakout": 0.5,              # Halved — high risk
}

# Position scale = sum(posterior_i × factor_i)
```

Alphas tested in Grok must account for this scaling when estimating capacity.

---

## MARKET STATE ENGINE STATUS

```
Market State Engine: ACTIVE
Model: HMM3StateFractional (3 states)
States: compression_clustering, normal, vol_breakout
Emission: log-spread Gaussian (calibratable)
Update: online Bayesian posterior
Alignment: MATCHED with feelies platform
```

Awaiting Alpha Factory activation (Prompt 4).
