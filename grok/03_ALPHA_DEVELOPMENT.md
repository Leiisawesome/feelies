# MODULE 3 - ALPHA DEVELOPMENT: SCHEMA, SENSORS & HYPOTHESES

## ACTIVATION DIRECTIVE

The Alpha Development module activates with this block. This module defines:

1. The schema-1.1 `.alpha.yaml` contract as enforced by `AlphaLoader`
2. Reference-alpha and sensor-catalog helpers sourced from the repo
3. Layer-aware builders for deployable SIGNAL alphas
4. Hypothesis helpers that stay aligned with the current three-layer platform
5. Validation using the repo's actual `AlphaLoader`

Default path: start from a shipped reference alpha, mutate the declarative
fields, validate with `AlphaLoader`, then backtest via Prompt 4.

---

## CELL 1 - Alpha development utilities (uses AlphaLoader from repo source)

```python
import copy, datetime, os, pathlib, re, yaml
from feelies.alpha.loader import AlphaLoader
from feelies.services.regime_engine import get_regime_engine

# -------------------------------------------------------------------
# Workspace for alpha specs during development
# -------------------------------------------------------------------
ALPHA_DEV_DIR = "/home/user/alphas"
REFERENCE_ALPHA_DIR = os.path.join(FEELIES_REPO, "alphas")
os.makedirs(ALPHA_DEV_DIR, exist_ok=True)

_REGIME_ALIASES = {
    "benign": "normal",
    "neutral": "normal",
    "normal": "normal",
    "compression": "compression_clustering",
    "compressed": "compression_clustering",
    "compression_clustering": "compression_clustering",
    "toxic": "vol_breakout",
    "breakout": "vol_breakout",
    "vol_breakout": "vol_breakout",
    # Human-facing shorthand is lossy; emitted YAML should prefer canonical names.
    "stressed": "vol_breakout",
}


def _alpha_yaml_path(alpha_id: str, root: str = REFERENCE_ALPHA_DIR) -> str:
    return os.path.join(root, alpha_id, f"{alpha_id}.alpha.yaml")


def list_reference_alphas() -> list[str]:
    """Return sorted shipped alpha ids under FEELIES_REPO/alphas."""
    alpha_ids: list[str] = []
    if not os.path.isdir(REFERENCE_ALPHA_DIR):
        return alpha_ids
    for entry in sorted(os.listdir(REFERENCE_ALPHA_DIR)):
        path = _alpha_yaml_path(entry)
        if os.path.exists(path):
            alpha_ids.append(entry)
    return alpha_ids


def load_reference_alpha(alpha_id: str) -> dict:
    """Load a shipped .alpha.yaml from FEELIES_REPO/alphas."""
    path = _alpha_yaml_path(alpha_id)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Reference alpha not found: {path}. "
            f"Available: {list_reference_alphas()}"
        )
    with open(path, "r") as f:
        return yaml.safe_load(f)


def clone_reference_alpha(
    alpha_id: str,
    *,
    new_alpha_id: str | None = None,
    version: str | None = None,
) -> dict:
    """Deep-copy a shipped alpha and optionally retag its id/version."""
    spec = copy.deepcopy(load_reference_alpha(alpha_id))
    if new_alpha_id is not None:
        spec["alpha_id"] = new_alpha_id
    if version is not None:
        spec["version"] = version
    return spec


def _translate_regime_aliases(expr: str) -> str:
    """Translate human-facing regime aliases into engine canonical names."""
    out = expr
    for alias, canonical in _REGIME_ALIASES.items():
        out = re.sub(rf"\b{re.escape(alias)}\b", canonical, out, flags=re.IGNORECASE)
    return out


def regime_gate_block(
    on_condition: str,
    off_condition: str,
    *,
    regime_engine: str = "hmm_3state_fractional",
    posterior_margin: float = 0.20,
    percentile_margin: float = 0.30,
) -> dict:
    """Build a schema-1.1 regime_gate block using canonical state names."""
    return {
        "regime_engine": regime_engine,
        "on_condition": _translate_regime_aliases(on_condition),
        "off_condition": _translate_regime_aliases(off_condition),
        "hysteresis": {
            "posterior_margin": posterior_margin,
            "percentile_margin": percentile_margin,
        },
    }


def cost_arithmetic_block(
    *,
    edge_estimate_bps: float,
    half_spread_bps: float,
    impact_bps: float,
    fee_bps: float,
) -> dict:
    """Build a cost_arithmetic block with a derived margin_ratio.

    margin_ratio = expected_edge / (1.5 * round_trip_cost), where:
        round_trip_cost = 2 * (half_spread + impact + fee)
    """
    one_way_cost_bps = float(half_spread_bps + impact_bps + fee_bps)
    round_trip_cost_bps = 2.0 * one_way_cost_bps
    hurdle_bps = 1.5 * round_trip_cost_bps
    margin_ratio = 0.0 if hurdle_bps <= 0 else float(edge_estimate_bps) / hurdle_bps
    return {
        "edge_estimate_bps": float(edge_estimate_bps),
        "half_spread_bps": float(half_spread_bps),
        "impact_bps": float(impact_bps),
        "fee_bps": float(fee_bps),
        "margin_ratio": round(margin_ratio, 4),
    }


def trend_mechanism_block(
    family: str,
    expected_half_life_seconds: int,
    l1_signature_sensors: list[str],
    failure_signature: list[str] | None = None,
) -> dict:
    """Build a trend_mechanism block compatible with current main."""
    return {
        "family": family,
        "expected_half_life_seconds": int(expected_half_life_seconds),
        "l1_signature_sensors": list(l1_signature_sensors),
        "failure_signature": list(failure_signature or []),
    }


def validate_alpha(
    spec: dict | str,
    regime_engine_name: str | None = "hmm_3state_fractional",
) -> bool:
    """Validate a .alpha.yaml spec using the repo's actual AlphaLoader."""
    if isinstance(spec, str):
        spec = yaml.safe_load(spec)

    regime = get_regime_engine(regime_engine_name) if regime_engine_name else None
    loader = AlphaLoader(regime_engine=regime)

    try:
        module = loader.load_from_dict(spec)
        manifest = getattr(module, "manifest", None)
        alpha_id = getattr(manifest, "alpha_id", spec.get("alpha_id", "?"))
        version = getattr(manifest, "version", spec.get("version", "?"))
        layer = getattr(manifest, "layer", spec.get("layer", "?"))
        print(
            f"VALIDATION PASSED: alpha_id={alpha_id}  "
            f"layer={layer}  version={version}"
        )
        return True
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}")
        return False


def save_alpha(spec: dict | str, alpha_id: str | None = None) -> str:
    """Save a .alpha.yaml spec to /home/user/alphas/{alpha_id}/ and return the path."""
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


def assemble_signal_alpha(
    *,
    alpha_id: str,
    hypothesis: str,
    falsification_criteria: list[str],
    parameters: dict,
    depends_on_sensors: list[str],
    horizon_seconds: int,
    regime_gate: dict,
    cost_arithmetic: dict,
    signal_code: str,
    description: str | None = None,
    version: str = "1.0.0",
    risk_budget: dict | None = None,
    trend_mechanism: dict | None = None,
    hazard_exit: dict | None = None,
    symbols: list[str] | None = None,
) -> dict:
    """Assemble a schema-1.1 SIGNAL alpha compatible with current main."""
    if int(horizon_seconds) < 30:
        raise ValueError("SIGNAL alphas require horizon_seconds >= 30 on current main")

    spec = {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": alpha_id,
        "version": version,
        "description": (description or hypothesis)[:200],
        "hypothesis": hypothesis,
        "falsification_criteria": list(falsification_criteria),
        "parameters": parameters,
        "depends_on_sensors": sorted(dict.fromkeys(depends_on_sensors)),
        "horizon_seconds": int(horizon_seconds),
        "risk_budget": risk_budget or {
            "max_position_per_symbol": 100,
            "max_gross_exposure_pct": 5.0,
            "max_drawdown_pct": 1.0,
            "capital_allocation_pct": 10.0,
        },
        "regime_gate": regime_gate,
        "cost_arithmetic": cost_arithmetic,
        "signal": signal_code,
    }
    if symbols:
        spec["symbols"] = list(symbols)
    if trend_mechanism is not None:
        spec["trend_mechanism"] = trend_mechanism
    if hazard_exit is not None:
        spec["hazard_exit"] = hazard_exit
    return spec


print(f"Reference alphas: {list_reference_alphas()}")
print("Alpha development utilities: ACTIVE")
print(
    "validate_alpha(), save_alpha(), list_reference_alphas(), load_reference_alpha(), "
    "clone_reference_alpha(), assemble_signal_alpha() available"
)
```

---

## CELL 2 - Sensor catalog and reference-alpha templates

```python
# -------------------------------------------------------------------
# Shipped Layer-1 sensor vocabulary. Prefer these ids directly.
# Derived fields on HorizonFeatureSnapshot follow current-main conventions:
#   <sensor_id>
#   <sensor_id>_zscore
#   <sensor_id>_percentile
# -------------------------------------------------------------------
SENSOR_CATALOG = {
    "ofi_ewma": {
        "role": "KYLE_INFO confirming; HAWKES confirming",
        "description": "Net signed liquidity pressure",
    },
    "micro_price": {
        "role": "KYLE_INFO primary",
        "description": "Size-weighted latent fair price",
    },
    "vpin_50bucket": {
        "role": "LIQUIDITY_STRESS primary",
        "description": "Informed-flow probability proxy",
    },
    "kyle_lambda_60s": {
        "role": "KYLE_INFO primary",
        "description": "Rolling permanent-impact estimate",
    },
    "spread_z_30d": {
        "role": "INVENTORY/STRESS confirming",
        "description": "Spread z-score versus 30-day median",
    },
    "realized_vol_30s": {
        "role": "LIQUIDITY_STRESS primary",
        "description": "Instantaneous realized-vol regime proxy",
    },
    "quote_hazard_rate": {
        "role": "INVENTORY/STRESS confirming",
        "description": "Flickering or spoofing intensity proxy",
    },
    "trade_through_rate": {
        "role": "HAWKES confirming",
        "description": "Fraction of prints outside NBBO",
    },
    "quote_replenish_asymmetry": {
        "role": "INVENTORY primary",
        "description": "Asymmetric quote replenishment after trades",
    },
    "hawkes_intensity": {
        "role": "HAWKES_SELF_EXCITE primary",
        "description": "Self-exciting trade-clustering tuple sensor",
    },
    "scheduled_flow_window": {
        "role": "SCHEDULED_FLOW primary",
        "description": "Scheduled-flow activity window tuple sensor",
    },
    "snr_drift_diffusion": {
        "role": "Cross-cutting exploitability gate",
        "description": "Per-horizon signal-to-noise envelope",
    },
    "structural_break_score": {
        "role": "Cross-cutting decay diagnostic",
        "description": "Non-stationarity score for the generating process",
    },
}

SENSOR_BINDING_RULES = [
    "SIGNAL alphas declare shipped sensor ids under depends_on_sensors.",
    "The horizon snapshot exposes <sensor_id>, <sensor_id>_zscore, and <sensor_id>_percentile bindings.",
    "Tuple sensors may also expose named scalar elements using <sensor_id>__<element_name> bindings.",
    "Do not invent a sensor inline in YAML; propose a SENSOR first if the required latent variable is missing.",
]

SENSOR_TOPOLOGY_RULES = [
    "Sensors are per-symbol stateful and must stay stateless across symbols.",
    "Sensors must not depend on signals, portfolio logic, or sized intents.",
    "Cross-sensor dependencies belong in the registry topology, not in ad hoc YAML wiring.",
    "Only L1 NBBO + trades + reference data are in scope for shipped sensors.",
]

FAMILY_PRIMARY_FINGERPRINTS = {
    "KYLE_INFO": ["kyle_lambda_60s", "micro_price"],
    "INVENTORY": ["quote_replenish_asymmetry"],
    "HAWKES_SELF_EXCITE": ["hawkes_intensity"],
    "LIQUIDITY_STRESS": ["vpin_50bucket", "realized_vol_30s"],
    "SCHEDULED_FLOW": ["scheduled_flow_window"],
}

FAMILY_CONFIRMING_SENSORS = {
    "KYLE_INFO": ["ofi_ewma", "spread_z_30d"],
    "INVENTORY": ["spread_z_30d", "quote_hazard_rate"],
    "HAWKES_SELF_EXCITE": ["trade_through_rate", "ofi_ewma"],
    "LIQUIDITY_STRESS": ["spread_z_30d", "quote_hazard_rate"],
    "SCHEDULED_FLOW": ["ofi_ewma"],
}

HALF_LIFE_ENVELOPES = {
    "KYLE_INFO": (60, 1800),
    "INVENTORY": (10, 120),
    "HAWKES_SELF_EXCITE": (5, 120),
    "LIQUIDITY_STRESS": (30, 600),
    "SCHEDULED_FLOW": (60, 3600),
}


REFERENCE_ALPHA_CATALOG = {
    "pofi_benign_midcap_v1": {
        "family": "baseline / parent-order flow",
        "horizon_seconds": 120,
        "layer": "SIGNAL",
    },
    "pofi_kyle_drift_v1": {
        "family": "KYLE_INFO",
        "horizon_seconds": 300,
        "layer": "SIGNAL",
    },
    "pofi_inventory_revert_v1": {
        "family": "INVENTORY",
        "horizon_seconds": 30,
        "layer": "SIGNAL",
    },
    "pofi_hawkes_burst_v1": {
        "family": "HAWKES_SELF_EXCITE",
        "horizon_seconds": 120,
        "layer": "SIGNAL",
    },
    "pofi_moc_imbalance_v1": {
        "family": "SCHEDULED_FLOW",
        "horizon_seconds": 300,
        "layer": "SIGNAL",
    },
    "pofi_xsect_v1": {
        "family": "PORTFOLIO cross-sectional",
        "horizon_seconds": 300,
        "layer": "PORTFOLIO",
    },
    "pofi_xsect_mixed_mechanism_v1": {
        "family": "PORTFOLIO mixed-mechanism",
        "horizon_seconds": 300,
        "layer": "PORTFOLIO",
    },
}


def LIST_SENSORS() -> None:
    """Display the shipped Layer-1 sensor ids and their roles."""
    print("\nShipped sensors")
    print("-" * 90)
    for sensor_id, meta in SENSOR_CATALOG.items():
        print(f"{sensor_id:28s} {meta['role']:35s} {meta['description']}")
    print("-" * 90)


def DESCRIBE_SENSOR_RULES() -> None:
    """Print the embedded sensor-binding, fingerprint, and topology rules."""
    print("\nSensor rules")
    print("-" * 90)
    print("Bindings")
    for line in SENSOR_BINDING_RULES:
        print(f"  - {line}")
    print("\nTopology")
    for line in SENSOR_TOPOLOGY_RULES:
        print(f"  - {line}")
    print("\nFingerprints")
    for family, primary in FAMILY_PRIMARY_FINGERPRINTS.items():
        confirming = FAMILY_CONFIRMING_SENSORS.get(family, [])
        envelope = HALF_LIFE_ENVELOPES.get(family)
        print(
            f"  {family:20s} primary={primary}  confirming={confirming}  "
            f"half_life={envelope}"
        )
    print("-" * 90)


def LIST_REFERENCE_ALPHAS() -> None:
    """Display the shipped reference alphas Grok should copy before mutating."""
    print("\nReference alphas")
    print("-" * 90)
    for alpha_id in list_reference_alphas():
        meta = REFERENCE_ALPHA_CATALOG.get(alpha_id, {})
        family = meta.get("family", "unknown")
        horizon = meta.get("horizon_seconds", "?")
        layer = meta.get("layer", "?")
        print(f"{alpha_id:32s} layer={layer:9s} horizon={str(horizon):>4s}s  family={family}")
    print("-" * 90)


print(f"Sensor catalog: {len(SENSOR_CATALOG)} shipped sensors")
print("LIST_SENSORS(), DESCRIBE_SENSOR_RULES(), and LIST_REFERENCE_ALPHAS() available")
```

---

## CELL 3 - Mechanism-family catalog and hypothesis workflow

```python
MECHANISM_FAMILY_CATALOG = {
    "KYLE_INFO": {
        "structural_actor": "informed parent-order executors",
        "observable": "kyle_lambda_60s with same-sign OFI and stable spreads",
        "typical_horizon_seconds": (120, 900),
        "half_life_envelope_seconds": HALF_LIFE_ENVELOPES["KYLE_INFO"],
        "template_alpha": "pofi_kyle_drift_v1",
        "signature_sensors": ["kyle_lambda_60s", "ofi_ewma", "micro_price", "spread_z_30d"],
        "primary_fingerprint_sensors": FAMILY_PRIMARY_FINGERPRINTS["KYLE_INFO"],
        "confirming_sensors": FAMILY_CONFIRMING_SENSORS["KYLE_INFO"],
    },
    "INVENTORY": {
        "structural_actor": "market makers managing short-lived inventory imbalances",
        "observable": "quote_replenish_asymmetry with replenishment hazard",
        "typical_horizon_seconds": (30, 120),
        "half_life_envelope_seconds": HALF_LIFE_ENVELOPES["INVENTORY"],
        "template_alpha": "pofi_inventory_revert_v1",
        "signature_sensors": ["quote_replenish_asymmetry", "quote_hazard_rate", "spread_z_30d"],
        "primary_fingerprint_sensors": FAMILY_PRIMARY_FINGERPRINTS["INVENTORY"],
        "confirming_sensors": FAMILY_CONFIRMING_SENSORS["INVENTORY"],
    },
    "HAWKES_SELF_EXCITE": {
        "structural_actor": "self-exciting order-flow bursts",
        "observable": "hawkes_intensity with confirming trade-through or OFI pressure",
        "typical_horizon_seconds": (30, 300),
        "half_life_envelope_seconds": HALF_LIFE_ENVELOPES["HAWKES_SELF_EXCITE"],
        "template_alpha": "pofi_hawkes_burst_v1",
        "signature_sensors": ["hawkes_intensity", "trade_through_rate", "ofi_ewma"],
        "primary_fingerprint_sensors": FAMILY_PRIMARY_FINGERPRINTS["HAWKES_SELF_EXCITE"],
        "confirming_sensors": FAMILY_CONFIRMING_SENSORS["HAWKES_SELF_EXCITE"],
    },
    "SCHEDULED_FLOW": {
        "structural_actor": "scheduled execution programs and close-window hedgers",
        "observable": "scheduled_flow_window with same-sign OFI confirmation",
        "typical_horizon_seconds": (120, 900),
        "half_life_envelope_seconds": HALF_LIFE_ENVELOPES["SCHEDULED_FLOW"],
        "template_alpha": "pofi_moc_imbalance_v1",
        "signature_sensors": ["scheduled_flow_window", "ofi_ewma"],
        "primary_fingerprint_sensors": FAMILY_PRIMARY_FINGERPRINTS["SCHEDULED_FLOW"],
        "confirming_sensors": FAMILY_CONFIRMING_SENSORS["SCHEDULED_FLOW"],
    },
    "PORTFOLIO_XSECT": {
        "structural_actor": "cross-sectional allocator combining multiple validated signals",
        "observable": "ranked signal stack across a synchronized universe",
        "typical_horizon_seconds": (300, 1800),
        "template_alpha": "pofi_xsect_v1",
        "signature_sensors": [],
    },
}


def PRIORITIZE(mechanism_family: str) -> None:
    """Direct the factory to a current-main mechanism family or template alpha."""
    family = mechanism_family.upper()
    if family in MECHANISM_FAMILY_CATALOG:
        meta = MECHANISM_FAMILY_CATALOG[family]
        print(f"\nMechanism family: {family}")
        print(f"  Structural actor: {meta['structural_actor']}")
        print(f"  Observable:       {meta['observable']}")
        lo, hi = meta['typical_horizon_seconds']
        print(f"  Horizon:          {lo}-{hi}s")
        if meta.get("half_life_envelope_seconds"):
            hlo, hhi = meta["half_life_envelope_seconds"]
            print(f"  Half-life:        {hlo}-{hhi}s")
        print(f"  Template alpha:   {meta['template_alpha']}")
        print(f"  Signature sensors:{meta['signature_sensors']}")
        if meta.get("primary_fingerprint_sensors"):
            print(f"  Primary sensors:  {meta['primary_fingerprint_sensors']}")
        if meta.get("confirming_sensors"):
            print(f"  Confirming:       {meta['confirming_sensors']}")
        return
    if mechanism_family in list_reference_alphas():
        spec = load_reference_alpha(mechanism_family)
        print(f"\nTemplate alpha: {mechanism_family}")
        print(f"  layer:            {spec.get('layer')}")
        print(f"  horizon_seconds:  {spec.get('horizon_seconds')}")
        print(f"  depends_on_sensors: {spec.get('depends_on_sensors', [])}")
        return
    print(
        f"Unknown family/template {mechanism_family}. Available families: "
        f"{list(MECHANISM_FAMILY_CATALOG)}. Templates: {list_reference_alphas()}"
    )


def formalize_hypothesis(
    *,
    mechanism_family: str,
    structural_actor: str,
    mechanism: str,
    l1_signature: str,
    expected_edge_bps: tuple[float, float],
    horizon_seconds: int,
    falsification_criteria: list[str],
    regime_dependency: str,
    rationale: str = "",
) -> dict:
    return {
        "statement": mechanism,
        "mechanism_family": mechanism_family,
        "structural_actor": structural_actor,
        "mechanism": mechanism,
        "l1_signature": l1_signature,
        "expected_edge_bps": expected_edge_bps,
        "horizon_seconds": horizon_seconds,
        "falsification_criteria": falsification_criteria,
        "regime_dependency": regime_dependency,
        "rationale": rationale,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }


H_EXAMPLE = formalize_hypothesis(
    mechanism_family="KYLE_INFO",
    structural_actor="informed parent-order executors",
    mechanism=(
        "When rolling Kyle lambda rises alongside same-sign OFI in the normal regime, "
        "residual drift over the next 300 seconds remains directionally biased."
    ),
    l1_signature="kyle_lambda_60s + ofi_ewma + spread_z_30d",
    expected_edge_bps=(8.0, 15.0),
    horizon_seconds=300,
    falsification_criteria=[
        "Spearman correlation between lambda x sign(OFI) and forward return drops below 0.05 for >= 4 weeks",
        "Realized half-life drifts outside the KYLE_INFO envelope",
        "OOS DSR < 1.0 after promotion to LIVE",
    ],
    regime_dependency="Expected: normal regime only; toxic breakout disables the gate.",
    rationale="Start from pofi_kyle_drift_v1 and retune only if the mechanism story stays intact.",
)

print("Mechanism-family catalog: ACTIVE")
print("PRIORITIZE('KYLE_INFO') or PRIORITIZE('pofi_kyle_drift_v1') to anchor development")
print("Hypothesis formalized:", H_EXAMPLE["mechanism"][:90])
print("Alpha Development module: ACTIVE")
```

---

## 1. `.alpha.yaml` SCHEMA

The schema is enforced by `AlphaLoader` from repo source (`feelies.alpha.loader`).
Use `validate_alpha(spec)` before backtesting any alpha.

Default Grok path: emit a schema-1.1 `layer: SIGNAL` alpha.

```yaml
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_signal_alpha
version: "1.0.0"
description: "Short text."
hypothesis: |
  Name the structural actor, the incentive, and the L1 signature.
falsification_criteria:
  - "Mechanism-level criterion, not just Sharpe decay"
  - "Realized half-life drifts outside the family's normative envelope"

depends_on_sensors:
  - ofi_ewma
  - spread_z_30d

parameters:
  threshold:
    type: float
    default: 2.0
    min: 1.0
    max: 4.0
    description: "Entry threshold in normalized sensor units."

horizon_seconds: 120

risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 10.0

regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(normal) > 0.7 and spread_z_30d < 0.5
  off_condition: |
    P(normal) < 0.5 or spread_z_30d > 1.5
  hysteresis:
    posterior_margin: 0.20
    percentile_margin: 0.30

cost_arithmetic:
  edge_estimate_bps: 9.0
  half_spread_bps: 2.0
  impact_bps: 2.0
  fee_bps: 1.0
  margin_ratio: 1.8

trend_mechanism:
  family: KYLE_INFO
  expected_half_life_seconds: 600
  l1_signature_sensors:
    - kyle_lambda_60s
    - ofi_ewma
  failure_signature:
    - "spread_z_30d > 2.0"

# Optional when the alpha explicitly opts into hazard exits.
# hazard_exit:
#   enabled: true
#   trigger_score: 0.90

signal: |
  def evaluate(snapshot, regime, params):
      z = snapshot.values.get("ofi_ewma_zscore")
      if z is None or abs(z) < params["threshold"]:
          return None

      direction = LONG if z > 0 else SHORT
      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="my_signal_alpha",
          direction=direction,
          strength=min(abs(z) / (params["threshold"] * 2.0), 1.0),
          edge_estimate_bps=min(abs(z) * 4.0, 20.0),
      )
```

Hard current-main reminders:

- `schema_version` must be `"1.1"`
- `layer: SIGNAL` requires `horizon_seconds >= 30`
- `depends_on_sensors`, `regime_gate`, and `cost_arithmetic` are first-class
  required fields
- emitted YAML should use canonical regime state names even if the human-facing
  reasoning used aliases

---

## 2. SENSOR BINDING & SIGNAL PROTOCOL

Shipped sensor ids flow into the Phase-3 horizon aggregator. SIGNAL alphas consume
the resulting `HorizonFeatureSnapshot` rather than per-tick feature updates.

Embedded sensor rules for paste-only use:

- Use only the shipped `sensor_id` values printed by `LIST_SENSORS()`.
- The snapshot surface exposes `<sensor_id>`, `<sensor_id>_zscore`, and `<sensor_id>_percentile`.
- Tuple-valued sensors may expose named scalar elements as `<sensor_id>__<element_name>`.
- `trend_mechanism.family` should name a family from `MECHANISM_FAMILY_CATALOG`, and its
    `l1_signature_sensors` should include at least one primary fingerprint sensor for that family.
- `trend_mechanism.expected_half_life_seconds` should stay within the family's half-life envelope
    and keep `horizon_seconds / expected_half_life_seconds` inside `[0.5, 4.0]`.
- If the required latent variable is not in `SENSOR_CATALOG`, the correct next step is a new
    SENSOR proposal rather than inventing a YAML-only sensor.
- Sensor dependencies stay downstream of raw market data only; do not wire signals or portfolio
    state back into sensor definitions.

Signal evaluation contract:

```python
def evaluate(snapshot, regime, params):
    # Namespace injected by AlphaLoader:
    #   Signal, LONG, SHORT, FLAT, alpha_id, math
    #
    # snapshot.values exposes:
    #   <sensor_id>
    #   <sensor_id>_zscore
    #   <sensor_id>_percentile
    #
    # For tuple sensors, current main may expose named scalar bindings.
    # See the reference alpha templates and sensor docs before relying on them.
    #
    # snapshot.timestamp_ns
    # snapshot.correlation_id
    # snapshot.sequence
    # snapshot.symbol
    ...
```

Practical rules for Grok:

- Prefer `load_reference_alpha()` then mutate a small number of fields.
- Treat `depends_on_sensors` as the canonical feature vocabulary.
- Avoid inventing new sensors in alpha YAML. If the sensor is not in
  `SENSOR_CATALOG`, the hypothesis is not yet executable.
- Prefer canonical regime names in emitted YAML: `compression_clustering`,
  `normal`, `vol_breakout`.

---

## 3. HYPOTHESIS FORMALIZATION TEMPLATE

Use the hypothesis helper to keep reasoning aligned with current-main contracts.

```python
H = formalize_hypothesis(
    mechanism_family="INVENTORY",
    structural_actor="market makers managing short-lived inventory imbalance",
    mechanism=(
        "A one-sided quote depletion that fails to replenish symmetrically is "
        "dominantly inventory-driven and mean-reverts as the ladder rebuilds."
    ),
    l1_signature="quote_replenish_asymmetry + quote_hazard_rate + spread_z_30d",
    expected_edge_bps=(5.0, 10.0),
    horizon_seconds=30,
    falsification_criteria=[
        "Realized half-life falls outside the INVENTORY envelope for >= 2 weeks",
        "Contrarian hit rate falls below 50% for >= 4 trading weeks",
        "OOS DSR < 1.0 in any quarter after promotion",
    ],
    regime_dependency="Expected: normal regime only; toxic breakout disables the gate.",
    rationale="Start from pofi_inventory_revert_v1 and only retune thresholds or gate width.",
)

spec = clone_reference_alpha("pofi_inventory_revert_v1", new_alpha_id="inventory_probe_v1")
spec["hypothesis"] = H["mechanism"]
spec["falsification_criteria"] = H["falsification_criteria"]
spec["regime_gate"] = regime_gate_block(
    on_condition="abs(quote_replenish_asymmetry_zscore) > 2.2 and P(benign) > 0.6",
    off_condition="P(toxic) > 0.4 or spread_z_30d > 2.0",
)

validate_alpha(spec)
```

Default development loop:

1. `LIST_REFERENCE_ALPHAS()`
2. `clone_reference_alpha(...)`
3. mutate hypothesis / parameters / gate / cost / trend-mechanism fields
4. `validate_alpha(spec)`
5. `save_alpha(spec)`
6. backtest via Prompt 4

---

## ALPHA DEVELOPMENT STATUS

```
Alpha Development Module: ACTIVE
Contract: schema-1.1 SIGNAL alphas on current main
Primary builders: assemble_signal_alpha(), clone_reference_alpha()
Primary catalogs: SENSOR_CATALOG, REFERENCE_ALPHA_CATALOG, MECHANISM_FAMILY_CATALOG
Primary validator: validate_alpha(spec)
```
