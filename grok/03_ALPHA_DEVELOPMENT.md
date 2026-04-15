# PROMPT 3 — ALPHA DEVELOPMENT: SCHEMA, FEATURES & HYPOTHESES

> **Paste this entire file as one block. Wait for `Alpha Development module: ACTIVE` before pasting Prompt 4.**

## ACTIVATION DIRECTIVE

The Alpha Development module is now active. This module defines:

1. The `.alpha.yaml` schema as enforced by `AlphaLoader` from repo source
2. The feature computation and signal evaluation protocols
3. A library of reusable feature modules
4. A mechanism catalog and hypothesis workflow
5. Validation using the repo's actual `AlphaLoader`

**Prerequisite: Prompts 1 and 2 must have been executed successfully.**

---

## CELL 1 — Alpha development utilities (uses AlphaLoader from repo source)

```python
import yaml, os, pathlib, datetime
from feelies.alpha.loader import AlphaLoader
from feelies.services.regime_engine import get_regime_engine

# -------------------------------------------------------------------
# Workspace for alpha specs during development
# -------------------------------------------------------------------
ALPHA_DEV_DIR = "/home/user/alphas"
os.makedirs(ALPHA_DEV_DIR, exist_ok=True)

# -------------------------------------------------------------------
# Alpha validation: uses the repo's actual AlphaLoader — not reimplemented rules
# -------------------------------------------------------------------
def validate_alpha(spec: dict | str, regime_engine_name: str | None = "hmm_3state_fractional") -> bool:
    """
    Validate a .alpha.yaml spec using the repo's AlphaLoader.

    Args:
        spec:  dict (parsed YAML) or str (YAML text)
        regime_engine_name: name of regime engine to inject, or None

    Returns:
        True if valid. Prints AlphaLoader errors on failure.

    Note: For specs using computation_module (external .py files), call save_alpha()
    first so the .py files are on disk, then pass the file path to loader.load() instead.
    This function is best suited for inline-computation specs.
    """
    if isinstance(spec, str):
        spec = yaml.safe_load(spec)

    regime = get_regime_engine(regime_engine_name) if regime_engine_name else None
    loader = AlphaLoader(regime_engine=regime)

    try:
        module = loader.load_from_dict(spec)
        print(f"VALIDATION PASSED: alpha_id={module.manifest.alpha_id}  "
              f"features={len(module.features)}  "
              f"version={module.manifest.version}")
        return True
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}")
        return False


def save_alpha(spec: dict | str, alpha_id: str | None = None) -> str:
    """
    Save a .alpha.yaml spec to /home/user/alphas/{alpha_id}/ and return the path.
    Also saves any feature modules found in the spec's features list.
    """
    if isinstance(spec, str):
        spec_dict = yaml.safe_load(spec)
        spec_yaml = spec
    else:
        spec_dict = spec
        spec_yaml = yaml.dump(spec_dict, default_flow_style=False, sort_keys=False)

    alpha_id = alpha_id or spec_dict.get("alpha_id", "unknown")
    alpha_dir = os.path.join(ALPHA_DEV_DIR, alpha_id)
    os.makedirs(alpha_dir, exist_ok=True)

    out_path = os.path.join(alpha_dir, f"{alpha_id}.alpha.yaml")
    with open(out_path, "w") as f:
        f.write(spec_yaml)
    print(f"Saved: {out_path}")
    return out_path


def assemble_alpha(
    alpha_id: str,
    hypothesis: str,
    falsification_criteria: list[str],
    parameters: dict,
    features: list[dict],
    signal_code: str,
    risk_budget: dict | None = None,
    symbols: list[str] | None = None,
    description: str | None = None,
) -> dict:
    """
    Assemble a complete .alpha.yaml spec dict.

    Args:
        alpha_id:               Must match ^[a-z][a-z0-9_]*$
        hypothesis:             Named causal mechanism (required)
        falsification_criteria: List of falsifiable statements
        parameters:             Dict of {name: {type, default, range, description}}
                                NOTE: use 'range' not 'min'/'max' — AlphaLoader reads 'range' only
        features:               List of feature dicts (see schema below)
        signal_code:            String containing evaluate(features, params) function
        risk_budget:            Optional dict; defaults are conservative
        symbols:                Optional list of tickers
        description:            Optional short description (defaults to first 200 chars of hypothesis)

    Returns:
        dict representing the .alpha.yaml spec
    """
    spec = {
        "schema_version": "1.0",
        "alpha_id":   alpha_id,
        "version":    "1.0.0",
        "description": (description or hypothesis)[:200],
        "hypothesis": hypothesis,
        "falsification_criteria": falsification_criteria,
    }
    if symbols:
        spec["symbols"] = symbols
    spec["parameters"] = parameters
    spec["risk_budget"] = risk_budget or {
        "max_position_per_symbol": 100,
        "max_gross_exposure_pct":  5.0,
        "max_drawdown_pct":        1.0,
        "capital_allocation_pct":  10.0,
    }
    spec["features"] = features
    spec["signal"]   = signal_code
    return spec

print("Alpha development utilities: ACTIVE")
print("validate_alpha(), save_alpha(), assemble_alpha() available")
```

---

## CELL 2 — Feature library (6 reusable modules as inline computation strings)

```python
# These feature definitions use the platform's update(quote, state, params) protocol.
# They are self-contained strings suitable for the 'computation' field in .alpha.yaml.
# quote.bid / quote.ask are Decimal; quote.bid_size / quote.ask_size are int.
# No import statements allowed. math module is pre-injected.

FEATURE_LIBRARY = {

    "spread_bps": {
        "description": "Current bid-ask spread in basis points of mid-price.",
        "warm_up": 1,
        "code": """\
def initial_state():
    return {}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 9999.0
    return (ask - bid) / mid * 10000.0
""",
    },

    "microprice": {
        "description": "Size-weighted mid-price (microprice).",
        "warm_up": 1,
        "code": """\
def initial_state():
    return {}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bsz = float(quote.bid_size)
    asz = float(quote.ask_size)
    total = bsz + asz
    if total > 0:
        return (bid * asz + ask * bsz) / total
    return (bid + ask) / 2.0
""",
    },

    "order_imbalance": {
        "description": "Signed order imbalance in [-1, +1]. Positive = bid-heavy.",
        "warm_up": 1,
        "code": """\
def initial_state():
    return {}

def update(quote, state, params):
    total = float(quote.bid_size + quote.ask_size)
    if total <= 0:
        return 0.0
    return float(quote.bid_size - quote.ask_size) / total
""",
    },

    "imbalance_ema": {
        "description": "Exponential moving average of order imbalance.",
        "warm_up": 50,
        "code": """\
def initial_state():
    return {"ema": 0.0, "n": 0}

def update(quote, state, params):
    total = float(quote.bid_size + quote.ask_size)
    if total <= 0:
        return state["ema"]
    raw = float(quote.bid_size - quote.ask_size) / total
    alpha = params.get("imbalance_ema_alpha", 0.98)
    if state["n"] == 0:
        state["ema"] = raw
    else:
        state["ema"] = alpha * state["ema"] + (1.0 - alpha) * raw
    state["n"] += 1
    return float(state["ema"])
""",
    },

    "mid_zscore": {
        "description": "Z-score of mid-price relative to its EWMA (mean-reversion signal).",
        "warm_up": 50,
        "code": """\
def initial_state():
    return {"ewma": None, "ema_var": 0.0, "n": 0}

def update(quote, state, params):
    mid = float((quote.bid + quote.ask) / 2)
    span = params.get("ewma_span", 50)
    alpha = 2.0 / (span + 1)
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
""",
    },

    "mu_ema": {
        "description": "Volatility-normalised EWMA of microprice drift (SDE drift proxy).",
        "warm_up": 100,
        "code": """\
def initial_state():
    return {"prev_mp": None, "prev_spread": None, "ema_var": 0.0, "mu_ema": 0.0}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bsz = float(quote.bid_size)
    asz = float(quote.ask_size)
    spread = ask - bid
    total  = bsz + asz
    mp = (bid * asz + ask * bsz) / total if total > 0 else (bid + ask) / 2.0

    if state["prev_mp"] is None:
        state["prev_mp"]     = mp
        state["prev_spread"] = spread
        return 0.0

    spread_vel = spread - state["prev_spread"]
    micro_vel  = mp - state["prev_mp"]
    raw_mu     = spread_vel * micro_vel

    vol_alpha = params.get("ewma_vol_alpha", 0.94)
    state["ema_var"] = vol_alpha * state["ema_var"] + (1.0 - vol_alpha) * (micro_vel ** 2)
    local_vol  = max(state["ema_var"] ** 0.5, 1e-12)
    mu_norm    = raw_mu / local_vol

    ema_alpha = params.get("mu_ema_alpha", 0.99)
    state["mu_ema"] = ema_alpha * state["mu_ema"] + (1.0 - ema_alpha) * mu_norm

    state["prev_mp"]     = mp
    state["prev_spread"] = spread
    return float(state["mu_ema"])
""",
    },
}

def feature_entry(feature_id: str, depends_on: list[str] | None = None,
                  param_overrides: dict | None = None) -> dict:
    """Build a feature dict for use in assemble_alpha(features=[...])."""
    lib = FEATURE_LIBRARY[feature_id]
    entry = {
        "feature_id":  feature_id,
        "version":     "1.0.0",
        "description": lib["description"],
        "depends_on":  depends_on or [],
        "warm_up":     {"min_events": lib["warm_up"]},
        "computation": lib["code"],
    }
    return entry

print("Feature library: 6 modules (spread_bps, microprice, order_imbalance,")
print("                              imbalance_ema, mid_zscore, mu_ema)")
print("feature_entry(feature_id) builds a feature dict for assemble_alpha()")
```

---

## CELL 3 — Mechanism catalog and hypothesis workflow

```python
# -------------------------------------------------------------------
# Mechanism catalog — 10 known microstructure phenomena
# Every TEST must reference one of these (or extend the catalog with a new entry)
# -------------------------------------------------------------------
MECHANISM_CATALOG = {
    "M001": {
        "name":      "Order imbalance pressure",
        "mechanism": "Excess buy-side (sell-side) queue pressure at the BBO predicts "
                     "short-term microprice direction due to inventory clearing.",
        "observable": "order_imbalance → microprice_velocity",
        "holding_s":  (1, 30),
        "features":   ["order_imbalance", "imbalance_ema"],
    },
    "M002": {
        "name":      "Spread compression anticipation",
        "mechanism": "Narrowing spread combined with directional imbalance signals "
                     "impending informed order flow arriving at the NBBO.",
        "observable": "spread_velocity < 0 AND directional_imbalance",
        "holding_s":  (5, 60),
        "features":   ["spread_bps", "order_imbalance"],
    },
    "M003": {
        "name":      "Trade clustering momentum",
        "mechanism": "Bursts of same-side trades indicate institutional order slicing; "
                     "subsequent ticks continue in the same direction.",
        "observable": "trade_aggressiveness + trade_intensity",
        "holding_s":  (5, 120),
        "features":   ["order_imbalance"],   # extend with trade-side features
    },
    "M004": {
        "name":      "Quote flickering detection",
        "mechanism": "High quote update frequency with low trade intensity indicates "
                     "market makers refreshing; the direction of refreshes predicts "
                     "short-term fair value.",
        "observable": "quote_freq > threshold AND trade_intensity < threshold",
        "holding_s":  (10, 60),
        "features":   ["spread_bps"],
    },
    "M005": {
        "name":      "Queue depletion cascade",
        "mechanism": "Rapid depletion of one side of the BBO triggers adverse selection "
                     "pressure and spread widening in the next N ticks.",
        "observable": "queue_depletion → spread_widening",
        "holding_s":  (2, 30),
        "features":   ["order_imbalance", "spread_bps"],
    },
    "M006": {
        "name":      "Microprice mean reversion",
        "mechanism": "Microprice deviates from mid due to transient size imbalance; "
                     "reverts as liquidity replenishes.",
        "observable": "microprice_deviation_from_mid",
        "holding_s":  (5, 60),
        "features":   ["microprice", "mid_zscore"],
    },
    "M007": {
        "name":      "VPIN toxicity proxy",
        "mechanism": "Volume-synchronised probability of informed trading (VPIN proxy) "
                     "predicts volatility increase and spread widening.",
        "observable": "vpin_proxy → realized_variance",
        "holding_s":  (30, 300),
        "features":   ["order_imbalance"],   # volume bucketed variant
    },
    "M008": {
        "name":      "SDE drift persistence",
        "mechanism": "Smoothed microprice drift (mu_ema) captures persistent directional "
                     "pressure from informed flow; confirmation from order imbalance.",
        "observable": "mu_ema + imbalance_ema alignment",
        "holding_s":  (500, 2000),   # tick-based
        "features":   ["mu_ema", "imbalance_ema"],
    },
    "M009": {
        "name":      "Spread regime transition",
        "mechanism": "HMM regime shift from compression_clustering to normal (or normal "
                     "to vol_breakout) combined with directional imbalance predicts "
                     "short-term price dislocation.",
        "observable": "regime_posterior shift + order_imbalance",
        "holding_s":  (30, 300),
        "features":   ["order_imbalance", "spread_bps"],
    },
    "M010": {
        "name":      "Trade size anomaly",
        "mechanism": "Unusually large individual trades indicate institutional activity "
                     "that temporarily moves fair value in the trade direction.",
        "observable": "trade_size_zscore → price_impact",
        "holding_s":  (5, 60),
        "features":   [],   # requires trade-event features (update_trade)
    },
}

def PRIORITIZE(mechanism_id: str) -> None:
    """Direct the factory to focus on a specific mechanism."""
    m = MECHANISM_CATALOG.get(mechanism_id)
    if not m:
        print(f"Unknown mechanism {mechanism_id}. Available: {list(MECHANISM_CATALOG)}")
        return
    print(f"\nMechanism {mechanism_id}: {m['name']}")
    print(f"  Causal claim: {m['mechanism']}")
    print(f"  Observable:   {m['observable']}")
    print(f"  Holding:      {m['holding_s'][0]}–{m['holding_s'][1]}s")
    print(f"  Suggested features: {m['features']}")
    print(f"\nFormalize a hypothesis, then call TEST(hypothesis_dict).")

print("Mechanism catalog: 10 entries (M001–M010)")
print("PRIORITIZE('M001') to direct the factory")
```

---

## 1. `.alpha.yaml` SCHEMA

The schema is enforced by `AlphaLoader` from repo source (`feelies.alpha.loader`).
Use `validate_alpha(spec)` to check any spec before backtesting.

```yaml
schema_version: "1.0"          # Supported: "1.0". Omit → default "1.0" with warning.
alpha_id: my_alpha              # Required. Pattern: ^[a-z][a-z0-9_]*$
version: "1.0.0"                # Required. Semver: \d+\.\d+\.\d+
description: "Short text."
hypothesis: |                   # Required. Must name a causal force.
  State the microstructure mechanism being exploited.
  No mechanism = not a valid hypothesis.
falsification_criteria:         # Required. List of falsifiable statements.
  - "OOS Sharpe < 0.80 net of all fees"
  - "Bootstrap p-value > 0.05"
  - "Edge vanishes outside target regime"

symbols:                        # Optional. Restrict to specific tickers.
  - AAPL

parameters:
  lookback:
    type: int
    default: 50
    range: [5, 500]             # Use 'range' — AlphaLoader reads ONLY 'range', not 'min'/'max'
    description: "Lookback ticks for feature computation."
  threshold:
    type: float
    default: 1.5
    range: [0.1, 10.0]
    description: "Z-score entry threshold."

risk_budget:
  max_position_per_symbol: 100  # Max shares for this alpha (> 0)
  max_gross_exposure_pct:  5.0  # Max exposure as % of allocated capital (0, 100]
  max_drawdown_pct:        1.0  # Per-alpha drawdown halt (0, 100]
  capital_allocation_pct: 10.0  # % of account equity for this alpha (0, 100]

features:
  - feature_id: my_feature      # Must be unique within the spec
    version: "1.0.0"
    description: "What this computes."
    depends_on: []              # Other feature_ids this depends on
    warm_up:
      min_events: 50            # Ticks before feature is considered warm
      # min_duration_ns: 60000000000  # Optional: 60s minimum
    computation: |              # Inline code (no imports; math is pre-injected)
      def initial_state():
          return {"values": []}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          state["values"].append(mid)
          if len(state["values"]) > params["lookback"]:
              state["values"].pop(0)
          mu = sum(state["values"]) / len(state["values"])
          return float(mid - mu)
      # Optional: def update_trade(trade, state, params): return float or None
    # Alternative to inline: computation_module: my_feature.py
    # The .py file MUST be in the same directory as the .alpha.yaml.

signal: |                       # Required. evaluate(features, params) → Signal | None
  def evaluate(features, params):
      # Namespace available (injected by AlphaLoader):
      #   Signal, SignalDirection, LONG, SHORT, FLAT
      #   alpha_id (str)
      #   math (module: math.log, math.exp, math.sqrt, etc.)
      #   abs, min, max, round, len, range, sum, float, int, bool, str
      #   list, dict, tuple, True, False, None
      #
      # When regimes.engine is declared:
      #   regime_posteriors(symbol) → list[float] | None  (3 values: compression, normal, vol_breakout)
      #   regime_state_names → tuple[str, ...]            ("compression_clustering", "normal", "vol_breakout")
      #
      # features.values:        dict[str, float]
      # features.warm:          bool
      # features.stale:         bool
      # features.timestamp_ns:  int
      # features.symbol:        str
      # features.correlation_id: str
      # features.sequence:      int
      if not features.warm or features.stale:
          return None
      val = features.values.get("my_feature", 0.0)
      if val > params["threshold"]:
          return Signal(
              timestamp_ns    = features.timestamp_ns,
              correlation_id  = features.correlation_id,
              sequence        = features.sequence,
              symbol          = features.symbol,
              strategy_id     = alpha_id,
              direction       = LONG,
              strength        = min(abs(val) / params["threshold"], 1.0),
              edge_estimate_bps = abs(val) * 10.0,
          )
      elif val < -params["threshold"]:
          return Signal(
              timestamp_ns    = features.timestamp_ns,
              correlation_id  = features.correlation_id,
              sequence        = features.sequence,
              symbol          = features.symbol,
              strategy_id     = alpha_id,
              direction       = SHORT,
              strength        = min(abs(val) / params["threshold"], 1.0),
              edge_estimate_bps = abs(val) * 10.0,
          )
      return None
```

---

## 2. FEATURE PROTOCOL

Every feature module must define exactly these functions:

```python
def initial_state() -> dict:
    """Return initial state. No arguments. State must be JSON-safe:
    only float, int, str, bool, None, list, dict — no Decimal, no tuple, no set."""
    return {}

def update(quote, state: dict, params: dict) -> float:
    """Compute feature value from one NBBOQuote.
    quote.bid, quote.ask: Decimal
    quote.bid_size, quote.ask_size: int
    state: mutable dict persisting across ticks
    params: alpha parameter dict
    Returns: float (the feature value for this tick)"""
    ...

# Optional:
def update_trade(trade, state: dict, params: dict) -> float | None:
    """Update from a Trade event. trade.price: Decimal; trade.size: int.
    Return float to update feature value, or None to keep previous value."""
    ...
```

Validation rules (enforced by `AlphaLoader`):
- `initial_state()` takes 0 arguments, returns dict
- `update()` takes exactly 3 arguments: `(quote, state, params)`
- `evaluate()` takes exactly 2 arguments: `(features, params)`
- No `import` in inline code (sandbox)
- No `eval`, `exec`, `open`, `__import__`

---

## 3. HYPOTHESIS FORMALIZATION TEMPLATE

```python
def formalize_hypothesis(
    mechanism_id: str,
    statement: str,
    causal_chain: str,
    expected_sign: str,          # "+1" or "-1"
    expected_magnitude_bps: tuple,   # (min_bps, max_bps)
    holding_period_s: tuple,     # (min_s, max_s)
    falsification_criteria: list[str],
    regime_dependency: str,
) -> dict:
    return {
        "mechanism_id":   mechanism_id,
        "statement":      statement,
        "causal_chain":   causal_chain,
        "expected_sign":  expected_sign,
        "expected_magnitude_bps": expected_magnitude_bps,
        "holding_period_s": holding_period_s,
        "falsification_criteria": falsification_criteria,
        "regime_dependency": regime_dependency,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

# Example:
H_EXAMPLE = formalize_hypothesis(
    mechanism_id   = "M001",
    statement      = "Bid-heavy order imbalance (imbalance_ema > 0.3) predicts "
                     "positive microprice returns over the next 10–30 ticks.",
    causal_chain   = "Excess buy demand at BBO → market makers reprice ask upward "
                     "→ microprice rises → observed in subsequent NBBOQuote stream",
    expected_sign  = "+1",
    expected_magnitude_bps = (0.5, 3.0),
    holding_period_s       = (5, 60),
    falsification_criteria = [
        "OOS Sharpe < 0.80 net of all fees",
        "Bootstrap p-value > 0.05 on trade returns",
        "Effect disappears when imbalance_ema lagged by 5 ticks (no persistence)",
        "Signal reverses sign in vol_breakout regime",
    ],
    regime_dependency = "Expected: works in compression_clustering and normal. "
                        "Likely fails in vol_breakout (adverse selection dominates).",
)
print("Hypothesis formalized:", H_EXAMPLE["statement"][:80])
```

---

## ALPHA DEVELOPMENT STATUS

```
Alpha Development Module: ACTIVE
AlphaLoader:       From repo source (feelies.alpha.loader)
Validation:        validate_alpha(spec) → uses AlphaLoader directly
Feature library:   6 modules (spread_bps, microprice, order_imbalance,
                               imbalance_ema, mid_zscore, mu_ema)
Mechanism catalog: 10 entries (M001–M010)
Schema version:    1.0 (enforced by AlphaLoader)
Parameter format:  range: [lo, hi]  (NOT min/max — AlphaLoader reads only 'range')

Awaiting Backtest Execution activation (Prompt 4).
```
