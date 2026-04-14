# PROMPT 4 — SELF-EVOLVING ALPHA FACTORY

## ACTIVATION DIRECTIVE

Autonomous signal discovery mode is now active. The laboratory continuously searches for microstructure alpha using evolutionary exploration.

**Critical constraint:** Every signal this factory produces must be a valid `.alpha.yaml` file (Prompt 1, Section 3). The factory does not produce ad-hoc Python — it produces platform-deployable alpha specifications.

This module explores search space, not truth. Truth is established by Prompt 5.

---

## GENERATION LOOP

Each generation performs:

```
1. Hypothesis generation → mechanism catalog or mutation
2. Signal construction → .alpha.yaml spec with feature modules
3. Event-level backtest → parity config (spread-crossing, latency, TC)
4. Statistical falsification → bootstrap, permutation, DSR
5. Regime validation → per-state performance (3-state HMM)
6. Survivor selection → rank by OOS DSR, reject failures
7. Mutation & recombination → evolve survivors
8. Artifact storage → /home/user/experiments/generation_XXX/
```

---

## 1. FEATURE CONSTRUCTION PROTOCOL

Features are the building blocks. Every feature must be a valid computation module that follows the platform protocol.

### Template: Feature Module

Every feature the factory generates must follow this exact template:

```python
# File: {feature_id}.py
# Feature: {description}
# Version: 1.0.0

def initial_state():
    return {
        # Only JSON-safe types: float, int, str, bool, None, list, dict
        # NO Decimal, tuple, set, or custom objects
    }

def update(quote, state, params):
    """
    Args:
        quote: has .bid (Decimal), .ask (Decimal), .bid_size (int), .ask_size (int)
        state: mutable dict (persists across ticks)
        params: dict from alpha spec parameters section
    Returns:
        float
    """
    # Compute feature value using ONLY data available at this tick
    return float(result)

# Optional: trade event handler
# def update_trade(trade, state, params):
#     """trade has .price (Decimal), .size (int)"""
#     return float(result) or None
```

### Feature Library: Reusable Modules

The factory maintains a library of validated feature modules:

```python
FEATURE_LIBRARY = {
    # ── Spread features ──
    "spread_bps": {
        "code": '''
def initial_state():
    return {}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 9999.0
    return (ask - bid) / mid * 10000.0
''',
        "warm_up": 1,
        "description": "Current spread in basis points of mid-price.",
    },

    # ── Microprice ──
    "microprice": {
        "code": '''
def initial_state():
    return {}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    if total > 0:
        return (bid * ask_sz + ask * bid_sz) / total
    return (bid + ask) / 2.0
''',
        "warm_up": 1,
    },

    # ── Order imbalance ──
    "order_imbalance": {
        "code": '''
def initial_state():
    return {}

def update(quote, state, params):
    total = float(quote.bid_size + quote.ask_size)
    if total <= 0:
        return 0.0
    return float(quote.bid_size - quote.ask_size) / total
''',
        "warm_up": 1,
    },

    # ── EWMA of imbalance ──
    "imbalance_ema": {
        "code": '''
def initial_state():
    return {"ema": 0.0}

def update(quote, state, params):
    total = float(quote.bid_size + quote.ask_size)
    if total <= 0:
        return state["ema"]
    raw = float(quote.bid_size - quote.ask_size) / total
    alpha = params.get("imbalance_ema_alpha", 0.98)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * raw
    return float(state["ema"])
''',
        "warm_up": 50,
    },

    # ── EWMA of vol-normalized drift ──
    "mu_ema": {
        "code": '''
def initial_state():
    return {"prev_microprice": None, "prev_spread": None,
            "ewma_var": 0.0, "mu_ema": 0.0}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    spread = ask - bid
    total = bid_sz + ask_sz
    mp = (bid * ask_sz + ask * bid_sz) / total if total > 0 else (bid + ask) / 2.0

    if state["prev_microprice"] is None:
        state["prev_microprice"] = mp
        state["prev_spread"] = spread
        return 0.0

    spread_vel = spread - state["prev_spread"]
    micro_vel = mp - state["prev_microprice"]
    raw_mu = spread_vel * micro_vel

    vol_alpha = params.get("ewma_vol_alpha", 0.94)
    state["ewma_var"] = vol_alpha * state["ewma_var"] + (1.0 - vol_alpha) * (micro_vel ** 2)
    local_vol = state["ewma_var"] ** 0.5 + 1e-12
    mu_norm = raw_mu / local_vol

    ema_alpha = params.get("mu_ema_alpha", 0.99)
    state["mu_ema"] = ema_alpha * state["mu_ema"] + (1.0 - ema_alpha) * mu_norm

    state["prev_microprice"] = mp
    state["prev_spread"] = spread
    return float(state["mu_ema"])
''',
        "warm_up": 100,
    },

    # ── Mid-price z-score ──
    "mid_zscore": {
        "code": '''
def initial_state():
    return {"ewma": None, "ema_var": 0.0, "n": 0}

def update(quote, state, params):
    mid = float((quote.bid + quote.ask) / 2)
    alpha = 2.0 / (params.get("ewma_span", 50) + 1)
    if state["ewma"] is None:
        state["ewma"] = mid
        state["n"] = 1
        return 0.0
    diff = mid - state["ewma"]
    state["ema_var"] = alpha * (diff * diff) + (1.0 - alpha) * state["ema_var"]
    state["ewma"] = alpha * mid + (1.0 - alpha) * state["ewma"]
    state["n"] += 1
    std = max(state["ema_var"] ** 0.5, 1e-12)
    return (mid - state["ewma"]) / std
''',
        "warm_up": 50,
    },
}
```

---

## 2. ALPHA SPEC ASSEMBLY

When the factory constructs a signal, it assembles a complete `.alpha.yaml`:

```python
def assemble_alpha_spec(
    alpha_id,
    hypothesis,
    falsification_criteria,
    parameters,
    features,       # list of {feature_id, code, warm_up, depends_on}
    signal_code,    # evaluate(features, params) function
    risk_budget=None,
    symbols=None,
):
    """
    Assemble a complete .alpha.yaml string.
    
    Every field must satisfy the AlphaLoader validation rules:
    - alpha_id: ^[a-z][a-z0-9_]*$
    - version: semver
    - features: each with initial_state() + update(quote, state, params)
    - signal: evaluate(features, params) returning Signal | None
    """
    spec = {
        "schema_version": "1.0",
        "alpha_id": alpha_id,
        "version": "1.0.0",
        "description": hypothesis[:200],
        "hypothesis": hypothesis,
        "falsification_criteria": falsification_criteria,
    }

    if symbols:
        spec["symbols"] = symbols

    spec["parameters"] = parameters
    # NOTE: parameters must use range: [min, max] format, NOT separate min/max fields.
    # The AlphaLoader reads only the 'range' key. Separate 'min'/'max' are silently ignored.

    spec["risk_budget"] = risk_budget or {
        "max_position_per_symbol": 100,
        "max_gross_exposure_pct": 5.0,
        "max_drawdown_pct": 1.0,
        "capital_allocation_pct": 10.0,
    }

    spec["features"] = []
    for f in features:
        entry = {
            "feature_id": f["feature_id"],
            "version": "1.0.0",
            "description": f.get("description", ""),
            "depends_on": f.get("depends_on", []),
            "warm_up": {"min_events": f.get("warm_up", 1)},
        }
        if f.get("module_file"):
            entry["computation_module"] = f["module_file"]
        else:
            entry["computation"] = f["code"]
        spec["features"].append(entry)

    spec["signal"] = signal_code

    return yaml.dump(spec, default_flow_style=False, sort_keys=False)
```

---

## 3. MECHANISM CATALOG

The factory draws hypotheses from known microstructure mechanisms:

| ID | Mechanism | Observable | Holding |
|----|-----------|-----------|---------|
| M001 | Order imbalance pressure | `order_imbalance` → `microprice_vel` | 1-30s |
| M002 | Spread compression anticipation | `spread_velocity` < 0 + directional imbalance | 5-60s |
| M003 | Trade clustering momentum | `trade_aggressiveness` + `trade_intensity` | 5-120s |
| M004 | Quote flickering detection | High `quote_freq` + low `trade_intensity` | 10-60s |
| M005 | Queue depletion cascade | `queue_depletion` → spread widening | 2-30s |
| M006 | Microprice mean reversion | Microprice deviation from midprice | 5-60s |
| M007 | VPIN toxicity signal | `vpin_proxy` → volatility increase | 30-300s |
| M008 | SDE drift persistence | Smoothed `mu_ema` with LP confirmation | 500-2000 ticks |
| M009 | Spread regime transition | Spread regime shift + imbalance direction | 30-300s |
| M010 | Trade size anomaly | Trade size z-score → price impact | 5-60s |

---

## 4. EVOLUTION OPERATORS

### Mutation Types

```python
MUTATIONS = [
    "swap_feature",       # Replace one feature with another from library
    "add_feature",        # Add a new feature to the spec
    "change_parameter",   # Modify a parameter value within its range
    "add_nonlinearity",   # Wrap a feature value in tanh/sigmoid/sign
    "modify_threshold",   # Adjust entry/exit thresholds
    "change_holding",     # Modify holding period parameters
    "swap_regime_gate",   # Change which regimes are allowed
]
```

### Recombination

Combine features from two surviving alphas into a new spec:
- Take signal structure from parent A
- Add feature from parent B
- Generate new `alpha_id` with lineage recorded

### Diversity Pressure

Reject mutations that produce >80% feature overlap with existing survivors.

---

## 5. BACKTEST ENGINE (PARITY MODE)

All backtests use the canonical parity configuration (Prompt 1, Section 6).

**Notation note:** The feature library (§1) uses `quote.bid` / `quote.ask` because
features are written for the platform's `NBBOQuote` objects. The backtest engine below
uses `quote["ask_price"]` / `quote["bid_price"]` because Grok REPL operates on raw
Polygon API dicts. When testing features in Grok, wrap raw data in a simple object:
`class Q: pass; q = Q(); q.bid = Decimal(str(row["bid_price"])); q.ask = ...`

```python
class ParityBacktester:
    def __init__(self):
        self.latency_ns = 100_000_000      # 100ms
        self.fill_probability = 0.7
        self.rng = random.Random(42)
        self.quantity = 100

    def fill_price(self, quote, direction):
        """CANONICAL: buy at ask, sell at bid."""
        if direction > 0:
            return float(quote["ask_price"])
        return float(quote["bid_price"])

    def attempt_fill(self):
        return self.rng.random() <= self.fill_probability

    def compute_tc(self, price, quantity, spread):
        """Additional costs beyond spread (spread is in fill price)."""
        notional = price * quantity
        exchange = 0.003 * quantity
        sec = 0.0000278 * notional
        finra = 0.000119 * quantity
        sigma = spread / max(price, 1e-12)
        impact = sigma * math.sqrt(quantity / 50_000_000) * 0.1 * notional
        return exchange + sec + finra + impact
```

---

## 6. STATISTICAL FALSIFICATION

Every candidate must survive:

```python
def falsification_battery(trade_returns, regime_labels, n_boot=1000, n_perm=1000):
    results = {}

    # Bootstrap: is mean return significantly > 0?
    boot_means = [np.mean(np.random.choice(trade_returns, len(trade_returns), replace=True))
                  for _ in range(n_boot)]
    results["bootstrap_pvalue"] = np.mean(np.array(boot_means) <= 0)

    # Permutation: is signal better than random?
    obs_sharpe = np.mean(trade_returns) / max(np.std(trade_returns), 1e-10)
    perm_sharpes = [np.mean(np.random.permutation(trade_returns)) /
                    max(np.std(trade_returns), 1e-10) for _ in range(n_perm)]
    results["permutation_pvalue"] = np.mean(np.array(perm_sharpes) >= obs_sharpe)

    # DSR: deflated sharpe ratio
    T = len(trade_returns)
    skew = scipy.stats.skew(trade_returns)
    kurt = scipy.stats.kurtosis(trade_returns, fisher=True)
    sr = obs_sharpe
    dsr = sr * math.sqrt(T) / math.sqrt(1 - skew * sr + (kurt / 4) * sr**2)
    results["dsr"] = dsr

    # Regime stability
    regime_sharpes = {}
    for r in np.unique(regime_labels):
        mask = regime_labels == r
        rr = trade_returns[mask]
        if len(rr) > 5:
            regime_sharpes[r] = np.mean(rr) / max(np.std(rr), 1e-10)
    results["regime_all_positive"] = all(s > 0 for s in regime_sharpes.values())
    results["regime_cv"] = np.std(list(regime_sharpes.values())) / max(np.mean(list(regime_sharpes.values())), 1e-10)

    # Verdict
    results["pass"] = (
        results["bootstrap_pvalue"] < 0.05 and
        results["permutation_pvalue"] < 0.05 and
        results["dsr"] > 1.0 and
        results["regime_all_positive"]
    )
    return results
```

---

## 7. ARTIFACT STORAGE

Each generation stored under:

```
/home/user/experiments/generation_XXX/
├── hypothesis.json
├── {alpha_id}.alpha.yaml          # Feelies-loadable spec
├── *.py                            # Feature computation modules
├── metrics.csv
├── trades.csv
├── lineage.json
├── regime_analysis.json
├── falsification_report.json
├── config.json
└── parity_fingerprint.json
```

Registry updated with every generation.

---

## ALPHA FACTORY STATUS

```
Alpha Factory: ACTIVE
Output format: .alpha.yaml (feelies-compatible)
Feature protocol: initial_state() + update(quote, state, params)
Signal protocol: evaluate(features, params) → Signal | None
Mechanism catalog: 10 entries
Backtest mode: PARITY (spread-crossing, 70% fill, 100ms latency)
```

Awaiting Hypothesis Testing Pipeline activation (Prompt 5).
