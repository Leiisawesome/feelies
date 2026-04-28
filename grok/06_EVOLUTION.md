# MODULE 6 — EVOLUTION (autonomous mutation, exploration, evolution)

## ACTIVATION DIRECTIVE

The Evolution module activates with this block. It closes the autonomy loop:

    hypothesis → alpha → backtest → mutation → next-generation alpha

Every mutation is **typed** (named operator), **provenance-tagged**
(`parent_id` + `mutation_type`), **MHT-corrected** (Holm over the family),
and **promotion-gated** (TEST verdict + selfcheck).

This module composes symbols defined in earlier modules:

- `assemble_signal_alpha` / `clone_reference_alpha` / `SENSOR_CATALOG` /
    `MECHANISM_FAMILY_CATALOG` / `formalize_hypothesis`  (Module 3)
- `TEST` / `SELFCHECK` / `falsification_battery` / `holm_correction` / `compute_ic`  (Module 4)
- `EXPORT` / `_registry_upsert`  (Module 5)
- `ALPHA_ACTIVE_DIR` / `SESSION["active_alpha_id"]`  (Module 1)

**Adoption loop.** Every validated child (MUTATE, RECOMBINE, EVOLVE
champion) is automatically `ADOPT`ed: the spec is written to
`ALPHA_ACTIVE_DIR/<alpha_id>/<alpha_id>.alpha.yaml` and
`SESSION["active_alpha_id"]` is flipped. The next `RUN_ACTIVE()` (or any
backtest with `use_active_dir=True`) discovers the freshly generated alpha
through the production `alpha_spec_dir` code path — the same path
`scripts/run_backtest.py` uses when `platform.yaml` points at `alphas/<id>/`.
A generated alpha becomes "what the platform sees" without manual file
copying.

No new dependency. No invented sensors. Only operators that compose
existing repo primitives and preserve the schema-1.1 contract.

---

## CELL 1 — Mutation operators (typed, deterministic, schema-preserving)

```python
import copy, random, hashlib, datetime
from typing import Callable

MUTATION_TRIGGER_RULES = [
    "Realized IC decay versus in-sample.",
    "Per-regime IC heterogeneity.",
    "Cost arithmetic drift.",
    "Half-life drift outside the declared family envelope.",
    "Mechanism crowding.",
    "Structural-break alarm on a fingerprint sensor.",
]

MUTATION_AXIS_RULES = {
    1: "Regime refinement: tighten the regime gate to isolate the working sub-regime.",
    2: "Sensor substitution: replace a sensor only with another sensor measuring the same latent variable.",
    3: "Horizon adjustment: move horizon_seconds and recheck cost arithmetic and half-life ratio.",
    4: "Universe refinement: tighten the universe and document the selection criterion.",
    5: "Layer promotion: promote a SIGNAL to a PORTFOLIO hypothesis instead of deleting the parent signal.",
}

FORBIDDEN_MUTATIONS = [
    "Parameter sweeps without a mechanism hypothesis.",
    "Adding measurements without naming the latent variable they capture.",
    "Combining decaying signals without a cross-sectional construction mechanism.",
    "Making falsification criteria easier to satisfy.",
    "Loosening the regime gate just to trade more often.",
    "Reducing hurdle_bps or inflating edge_estimate_bps without a fresh rationale.",
    "Renaming trend families just to evade G16.",
]

MUTATION_PREEMIT_CHECKLIST = [
    "Name exactly one mutation axis.",
    "State the trigger condition and supporting forensics.",
    "Keep schema_version and layer unchanged unless doing explicit layer promotion.",
    "Recompute cost arithmetic when horizon, regime, or universe changed.",
    "Recheck horizon / expected_half_life_seconds when trend_mechanism exists.",
    "Preserve predecessor lineage rather than overwriting history in place.",
    "Keep falsification criteria mechanism-tied and not easier than the parent.",
]


def SHOW_MUTATION_PROTOCOL() -> None:
    """Print the embedded mutation protocol for paste-only sessions."""
    print("\nMutation protocol")
    print("-" * 90)
    print("Triggers")
    for line in MUTATION_TRIGGER_RULES:
        print(f"  - {line}")
    print("\nAxes")
    for axis, line in MUTATION_AXIS_RULES.items():
        print(f"  {axis}. {line}")
    print("\nForbidden")
    for line in FORBIDDEN_MUTATIONS:
        print(f"  - {line}")
    print("\nPre-emit checklist")
    for idx, line in enumerate(MUTATION_PREEMIT_CHECKLIST, 1):
        print(f"  {idx}. {line}")
    print("-" * 90)

# -------------------------------------------------------------------
# Operator contract.
#
# An operator is a pure function:
#     operator(parent_spec: dict, rng: random.Random, **kwargs) -> dict | None
#
# It MUST:
#   1. Return a NEW dict (deepcopy parent first; never mutate parent in place).
#   2. Set child["alpha_id"]  = unique id derived from parent + operator + seed.
#   3. Set child["lineage"]   = {parent_id, mutation_type, operator_kwargs, seed}.
#   4. Preserve the current-main .alpha.yaml schema (Prompt 3 SIGNAL path).
#   5. Return None if the mutation is structurally impossible (e.g. parameter
#      perturbation on an alpha with no parameters). EXPLORE skips Nones.
#
# Operators MUST NOT:
#   - Touch SESSION, registry, filesystem.
#   - Read wall-clock state. (Determinism: same parent + seed → same child.)
#   - Invent sensors, layers, or regime state names that current main does not load.
# -------------------------------------------------------------------

def _child_id(parent_spec: dict, op_name: str, seed: int) -> str:
    """Deterministic child id: parent_alphaid + op + seed → 8-char hash suffix."""
    base = f"{parent_spec['alpha_id']}|{op_name}|{seed}".encode()
    suffix = hashlib.sha1(base).hexdigest()[:8]
    return f"{parent_spec['alpha_id']}_{op_name}_{suffix}"


def _new_child(parent_spec: dict, op_name: str, seed: int,
               operator_kwargs: dict | None = None) -> dict:
    child = copy.deepcopy(parent_spec)
    child["alpha_id"] = _child_id(parent_spec, op_name, seed)
    # Bump version: 1.0.0 → 1.0.1 → 1.0.2 …
    parent_ver = parent_spec.get("version", "1.0.0").split(".")
    try:
        parent_ver[-1] = str(int(parent_ver[-1]) + 1)
    except ValueError:
        parent_ver = ["1", "0", "1"]
    child["version"] = ".".join(parent_ver)
    child["lineage"] = {
        "parent_id":       parent_spec["alpha_id"],
        "parent_version":  parent_spec.get("version", "1.0.0"),
        "mutation_type":   op_name,
        "operator_kwargs": operator_kwargs or {},
        "seed":            seed,
        "created_at":      datetime.datetime.utcnow().isoformat(),
    }
    return child


def _numeric_bounds(spec: dict) -> tuple[float | None, float | None]:
    if "range" in spec and isinstance(spec.get("range"), (list, tuple)) and len(spec["range"]) == 2:
        return spec["range"][0], spec["range"][1]
    return spec.get("min"), spec.get("max")


_SENSOR_LATENT_GROUPS = {
    "price_impact_proxy": ("kyle_lambda_60s", "micro_price"),
    "order_flow_pressure": ("ofi_ewma", "trade_through_rate"),
    "inventory_replenishment": ("quote_replenish_asymmetry", "quote_hazard_rate"),
    "stress_pressure": ("vpin_50bucket", "realized_vol_30s"),
}


def _same_latent_variable(left_sensor: str, right_sensor: str) -> bool:
    if left_sensor == right_sensor:
        return True
    for members in _SENSOR_LATENT_GROUPS.values():
        if left_sensor in members and right_sensor in members:
            return True

    left_role = str((SENSOR_CATALOG.get(left_sensor) or {}).get("role", ""))
    right_role = str((SENSOR_CATALOG.get(right_sensor) or {}).get("role", ""))
    left_head = left_role.split(" primary")[0].split(" confirming")[0]
    right_head = right_role.split(" primary")[0].split(" confirming")[0]
    return bool(left_head) and left_head == right_head


def _replace_sensor_text(value, old_sensor: str, new_sensor: str):
    if isinstance(value, str):
        return value.replace(old_sensor, new_sensor)
    if isinstance(value, list):
        return [item.replace(old_sensor, new_sensor) if isinstance(item, str) else item for item in value]
    return value


def _dedupe_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _infer_parent_family(parent_spec: dict) -> str | None:
    family = ((parent_spec.get("trend_mechanism") or {}).get("family"))
    if family in MECHANISM_FAMILY_CATALOG and family != "PORTFOLIO_XSECT":
        return family

    family = REFERENCE_ALPHA_CATALOG.get(parent_spec.get("alpha_id", ""), {}).get("family")
    if family in MECHANISM_FAMILY_CATALOG and family != "PORTFOLIO_XSECT":
        return family
    return None


# ---- OP 1: parameter perturbation ---------------------------------
def op_perturb_parameter(parent_spec: dict, rng: random.Random,
                         scale: float = 0.25) -> dict | None:
    """
    Pick one numeric parameter at random and shift its default by a
    multiplicative factor in [1-scale, 1+scale], clipped to its declared range.
    This is the gentlest mutation — same mechanism, same features, only
    operating-point shift. Use to map the parameter sensitivity surface.
    """
    params = parent_spec.get("parameters") or {}
    numeric = [k for k, v in params.items()
               if isinstance(v.get("default"), (int, float))
               and v.get("type") in ("float", "int")]
    if not numeric:
        return None
    seed = rng.randrange(1 << 30)
    child = _new_child(parent_spec, "perturb_param", seed, {"scale": scale})
    name  = rng.choice(numeric)
    spec  = child["parameters"][name]
    lo, hi = _numeric_bounds(spec)
    factor = 1.0 + rng.uniform(-scale, scale)
    new_val = spec["default"] * factor
    if lo is not None: new_val = max(new_val, lo)
    if hi is not None: new_val = min(new_val, hi)
    if spec.get("type") == "int":
        new_val = int(round(new_val))
    spec["default"] = new_val
    child["lineage"]["operator_kwargs"].update({"parameter": name,
                                                "old": parent_spec["parameters"][name]["default"],
                                                "new": new_val})
    return child


# ---- OP 1b: sensor substitution (Axis 2) --------------------------
def op_substitute_sensor(parent_spec: dict, rng: random.Random,
                         old_sensor: str | None = None,
                         new_sensor: str | None = None) -> dict | None:
    """
    Replace one declared sensor with a same-latent-variable proxy and rewrite
    the inline signal and related text fields consistently.

    This stays intentionally narrow: it only touches schema fields that commonly
    embed sensor bindings and refuses substitutions across unrelated latent
    variables.
    """
    if parent_spec.get("layer") != "SIGNAL":
        return None

    sensors = list(parent_spec.get("depends_on_sensors") or [])
    if not sensors:
        return None

    if old_sensor is None:
        for candidate in sensors:
            compatible = [
                sensor_id for sensor_id in SENSOR_CATALOG
                if sensor_id != candidate and _same_latent_variable(candidate, sensor_id)
            ]
            if compatible:
                old_sensor = candidate
                new_sensor = compatible[0] if new_sensor is None else new_sensor
                break

    if old_sensor is None or old_sensor not in sensors:
        return None
    if new_sensor is None or new_sensor not in SENSOR_CATALOG:
        return None
    if not _same_latent_variable(old_sensor, new_sensor):
        return None

    seed = rng.randrange(1 << 30)
    child = _new_child(parent_spec, "substitute_sensor", seed,
                       {"old_sensor": old_sensor, "new_sensor": new_sensor})
    child["depends_on_sensors"] = _dedupe_in_order([
        new_sensor if sensor_id == old_sensor else sensor_id
        for sensor_id in sensors
    ])

    rewrite_hits = 0
    for field in ("signal", "hypothesis", "description"):
        original = child.get(field)
        rewritten = _replace_sensor_text(original, old_sensor, new_sensor)
        if rewritten != original:
            rewrite_hits += 1
            child[field] = rewritten

    falsification = child.get("falsification_criteria") or []
    rewritten_falsification = _replace_sensor_text(falsification, old_sensor, new_sensor)
    if rewritten_falsification != falsification:
        rewrite_hits += 1
        child["falsification_criteria"] = rewritten_falsification

    regime_gate = child.get("regime_gate") or {}
    for gate_key in ("on_condition", "off_condition"):
        original = regime_gate.get(gate_key)
        rewritten = _replace_sensor_text(original, old_sensor, new_sensor)
        if rewritten != original:
            rewrite_hits += 1
            regime_gate[gate_key] = rewritten
    if regime_gate:
        child["regime_gate"] = regime_gate

    trend = child.get("trend_mechanism") or {}
    signature = trend.get("l1_signature_sensors") or []
    rewritten_signature = [new_sensor if sensor_id == old_sensor else sensor_id for sensor_id in signature]
    rewritten_signature = _dedupe_in_order(rewritten_signature)
    if rewritten_signature != signature:
        rewrite_hits += 1
        trend["l1_signature_sensors"] = rewritten_signature
    failure_signature = trend.get("failure_signature") or []
    rewritten_failure_signature = _replace_sensor_text(failure_signature, old_sensor, new_sensor)
    if rewritten_failure_signature != failure_signature:
        rewrite_hits += 1
        trend["failure_signature"] = rewritten_failure_signature
    if trend:
        child["trend_mechanism"] = trend

    child["lineage"]["operator_kwargs"].update({
        "rewritten_fields": rewrite_hits,
        "compatible_latent_group": next(
            (name for name, members in _SENSOR_LATENT_GROUPS.items() if old_sensor in members and new_sensor in members),
            None,
        ),
    })
    return child


# ---- OP 2: horizon adjustment (Axis 3) ----------------------------
def op_adjust_horizon(parent_spec: dict, rng: random.Random,
                      allowed: tuple = (30, 120, 300, 900, 1800)) -> dict | None:
    """
    Move the alpha to a neighboring allowed horizon while preserving G16's
    horizon / half-life ratio when a trend_mechanism block is present.
    """
    current = parent_spec.get("horizon_seconds")
    if current is None:
        return None

    half_life = ((parent_spec.get("trend_mechanism") or {})
                 .get("expected_half_life_seconds"))
    candidates = []
    for horizon in allowed:
        if horizon == current:
            continue
        if half_life is not None:
            ratio = float(horizon) / float(half_life)
            if not 0.5 <= ratio <= 4.0:
                continue
        candidates.append(horizon)
    if not candidates:
        return None

    seed = rng.randrange(1 << 30)
    new_horizon = rng.choice(candidates)
    child = _new_child(parent_spec, "adjust_horizon", seed,
                       {"old_horizon": current, "new_horizon": new_horizon})
    child["horizon_seconds"] = int(new_horizon)
    return child


# ---- OP 3: regime refinement (Axis 1) -----------------------------
def op_refine_regime_gate(parent_spec: dict, rng: random.Random,
                          posterior_step: float = 0.05,
                          percentile_step: float = 0.05) -> dict | None:
    """
    Tighten the declared regime gate by increasing hysteresis margins. This is
    a conservative sub-regime refinement that preserves the gate DSL while
    reducing chattering and loosening risk of over-trading marginal states.
    """
    gate = parent_spec.get("regime_gate") or {}
    hysteresis = gate.get("hysteresis") or {}
    if not gate:
        return None

    seed = rng.randrange(1 << 30)
    child = _new_child(parent_spec, "refine_regime", seed,
                       {"posterior_step": posterior_step,
                        "percentile_step": percentile_step})
    child_gate = child.setdefault("regime_gate", {})
    child_hysteresis = child_gate.setdefault("hysteresis", {})
    old_post = float(hysteresis.get("posterior_margin", 0.20))
    old_pct = float(hysteresis.get("percentile_margin", 0.30))
    child_hysteresis["posterior_margin"] = round(min(old_post + posterior_step, 0.50), 3)
    child_hysteresis["percentile_margin"] = round(min(old_pct + percentile_step, 0.60), 3)
    child["lineage"]["operator_kwargs"].update({
        "old_posterior_margin": old_post,
        "new_posterior_margin": child_hysteresis["posterior_margin"],
        "old_percentile_margin": old_pct,
        "new_percentile_margin": child_hysteresis["percentile_margin"],
    })
    return child


# ---- OP 4: universe refinement (Axis 4) ---------------------------
def op_refine_universe(parent_spec: dict, rng: random.Random,
                       keep_fraction: float = 0.5) -> dict | None:
    """
    Restrict a symbol list or universe list to a deterministic sub-universe.
    This is only applicable when the parent spec already declares an explicit
    list; config-driven universes remain untouched.
    """
    key = None
    values = None
    if isinstance(parent_spec.get("symbols"), list) and len(parent_spec["symbols"]) > 1:
        key = "symbols"
        values = parent_spec["symbols"]
    elif isinstance(parent_spec.get("universe"), list) and len(parent_spec["universe"]) > 1:
        key = "universe"
        values = parent_spec["universe"]
    if key is None or values is None:
        return None

    seed = rng.randrange(1 << 30)
    child = _new_child(parent_spec, "refine_universe", seed,
                       {"key": key, "keep_fraction": keep_fraction})
    count = max(1, int(round(len(values) * keep_fraction)))
    chosen = sorted(rng.sample(list(values), count))
    child[key] = chosen
    child["lineage"]["operator_kwargs"].update({"old_size": len(values), "new_size": len(chosen)})
    return child


# ---- OP 5: layer promotion (Axis 5) -------------------------------
def op_promote_to_portfolio(parent_spec: dict, rng: random.Random,
                            template_alpha_id: str = "pofi_xsect_v1",
                            horizon_seconds: int | None = None,
                            universe: list[str] | None = None) -> dict | None:
    """
    Promote a SIGNAL alpha into a PORTFOLIO draft that consumes the parent via
    depends_on_signals and inherits the shipped cross-sectional template.

    This helper returns a new child spec but intentionally does not assume the
    parent signal is already materialized in the active alpha directory.
    """
    if parent_spec.get("layer") != "SIGNAL":
        return None

    family = _infer_parent_family(parent_spec)
    if family is None:
        return None

    seed = rng.randrange(1 << 30)
    child_alpha_id = _child_id(parent_spec, "promote_portfolio", seed)
    child = clone_reference_alpha(template_alpha_id, new_alpha_id=child_alpha_id)

    parent_ver = parent_spec.get("version", "1.0.0").split(".")
    try:
        parent_ver[-1] = str(int(parent_ver[-1]) + 1)
    except ValueError:
        parent_ver = ["1", "0", "1"]
    child["version"] = ".".join(parent_ver)

    promoted_horizon = max(
        300,
        int(child.get("horizon_seconds", 300) or 300),
        int(horizon_seconds or parent_spec.get("horizon_seconds") or 300),
    )
    child["horizon_seconds"] = promoted_horizon
    child["depends_on_signals"] = [parent_spec["alpha_id"]]

    if universe is not None:
        child["universe"] = list(universe)
    elif isinstance(parent_spec.get("symbols"), list) and len(parent_spec["symbols"]) > 1:
        child["universe"] = list(parent_spec["symbols"])

    parent_actor = MECHANISM_FAMILY_CATALOG.get(family, {}).get("structural_actor", "the parent mechanism")
    child["description"] = (
        f"Prompt-7 layer promotion of {parent_spec['alpha_id']} into a PORTFOLIO allocator. "
        f"Consumes the parent SIGNAL across the template universe via the platform's default composition pipeline."
    )
    child["hypothesis"] = (
        f"Cross-sectional ranking of {parent_spec['alpha_id']} preserves the {family} mechanism driven by "
        f"{parent_actor} because dispersion in the parent signal remains observable across a synchronized universe "
        f"at {promoted_horizon}-second decision intervals."
    )
    child["falsification_criteria"] = [
        f"cross_sectional_ir_below_0_5_60d_on_{parent_spec['alpha_id']}",
        f"mechanism_breakdown_{family.lower()}_exceeds_cap_for_3_consecutive_barriers",
        f"parent_signal_{parent_spec['alpha_id']}_loses_family_alignment_or_turnover_exceeds_budget",
    ]
    child["trend_mechanism"] = {
        "consumes": [{"family": family, "max_share_of_gross": 1.0}],
        "max_share_of_gross": 1.0,
    }
    child["lineage"] = {
        "parent_id": parent_spec["alpha_id"],
        "parent_version": parent_spec.get("version", "1.0.0"),
        "mutation_type": "promote_portfolio",
        "operator_kwargs": {
            "template_alpha_id": template_alpha_id,
            "family": family,
            "horizon_seconds": promoted_horizon,
            "depends_on_signals": list(child["depends_on_signals"]),
        },
        "seed": seed,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    return child


# Operator registry — EXPLORE / EVOLVE pull from here.
# Order is irrelevant; EXPLORE samples uniformly with the seeded RNG.
MUTATION_OPERATORS: dict[str, Callable] = {
    "perturb_param":   op_perturb_parameter,
    "substitute_sensor": op_substitute_sensor,
    "adjust_horizon":  op_adjust_horizon,
    "refine_regime":   op_refine_regime_gate,
    "refine_universe": op_refine_universe,
}

print(f"Mutation operators registered: {list(MUTATION_OPERATORS)}")
```

---

## CELL 1b — Cross-mechanism splice (binary recombination)

```python
# -------------------------------------------------------------------
# Splice (recombination) operator.
#
# Unlike the unary operators in MUTATION_OPERATORS, splice takes TWO
# parents and produces one child whose sensor dependency set is the union
# of both parents and whose signal logic is one parent's. This tests
# whether two independent mechanisms compose into a stronger combined
# edge — a classic genetic-algorithm crossover, scoped to our schema.
#
# Determinism: same (parent_a, parent_b, seed, signal_from) → same child.
#
# Why it lives outside MUTATION_OPERATORS:
#   The unary operator contract is `(spec, rng, **kw) -> spec | None`.
#   Splice needs two specs, so forcing it into that signature would
#   require globals or a wrapper that hides intent. Better to expose
#   it as its own RECOMBINE() command.
# -------------------------------------------------------------------
def op_splice(
    parent_a: dict,
    parent_b: dict,
    rng: random.Random,
    signal_from: str = "a",
) -> dict | None:
    """
    Splice sensor dependencies from parent_b into parent_a; keep parent_a's signal
    code (or parent_b's if signal_from='b').

    Both parents must validate. The child's `depends_on_sensors` list is the
    union of both parents. Parameters are also unioned, with the base parent
    winning on name collision. The signal text is taken verbatim from the
    chosen parent; if the chosen parent's signal expects bindings not exposed
    by the unioned sensors, AlphaLoader may still load the child but the
    strategy can become inactive at runtime, so use splice sparingly.
    """
    assert signal_from in ("a", "b"), "signal_from must be 'a' or 'b'"
    if parent_a.get("alpha_id") == parent_b.get("alpha_id"):
        return None   # splicing with self is a no-op

    a_sensors = parent_a.get("depends_on_sensors") or []
    b_sensors = parent_b.get("depends_on_sensors") or []
    if not a_sensors and not b_sensors:
        return None

    seed = rng.randrange(1 << 30)
    base = parent_a if signal_from == "a" else parent_b
    other = parent_b if signal_from == "a" else parent_a

    # Synthesize a child id that records BOTH parents.
    op_name = f"splice_{signal_from}"
    base_handle = base["alpha_id"]
    other_handle = other["alpha_id"]
    child_alpha_id = (
        f"{base_handle[:24]}__x__{other_handle[:24]}"
        f"_{hashlib.sha1(f'{base_handle}|{other_handle}|{seed}'.encode()).hexdigest()[:8]}"
    )

    child = copy.deepcopy(base)
    child["alpha_id"] = child_alpha_id
    parent_ver = base.get("version", "1.0.0").split(".")
    try:
        parent_ver[-1] = str(int(parent_ver[-1]) + 1)
    except ValueError:
        parent_ver = ["1", "0", "1"]
    child["version"] = ".".join(parent_ver)

    # Union sensor dependencies; base wins on collision only in the sense
    # that order is preserved from the chosen parent first.
    base_sensors = list(base.get("depends_on_sensors") or [])
    other_sensors = list(other.get("depends_on_sensors") or [])
    have = set(base_sensors)
    added = []
    for sensor_id in other_sensors:
        if sensor_id not in have:
            base_sensors.append(sensor_id)
            have.add(sensor_id)
            added.append(sensor_id)
    child["depends_on_sensors"] = base_sensors

    # Union parameters by name; base wins on collision.
    other_params = other.get("parameters") or {}
    for pname, pdef in other_params.items():
        child.setdefault("parameters", {}).setdefault(pname, copy.deepcopy(pdef))

    # Widen the trend-mechanism signature sensor list if both parents declare one.
    child_tm = child.get("trend_mechanism") or {}
    other_tm = other.get("trend_mechanism") or {}
    if child_tm and other_tm:
        tm_sensors = list(child_tm.get("l1_signature_sensors") or [])
        tm_have = set(tm_sensors)
        for sensor_id in other_tm.get("l1_signature_sensors") or []:
            if sensor_id not in tm_have:
                tm_sensors.append(sensor_id)
                tm_have.add(sensor_id)
        child_tm["l1_signature_sensors"] = tm_sensors
        child["trend_mechanism"] = child_tm

    child["lineage"] = {
        # parent_id is the "primary" parent for genealogy; co_parent_id
        # captures the other side. LINEAGE prints both.
        "parent_id":      base["alpha_id"],
        "co_parent_id":   other["alpha_id"],
        "parent_version": base.get("version", "1.0.0"),
        "mutation_type":  op_name,
        "operator_kwargs": {
            "signal_from":    signal_from,
            "spliced_sensors": added,
        },
        "seed":           seed,
        "created_at":     datetime.datetime.utcnow().isoformat(),
    }
    child["hypothesis"] = (
        f"[SPLICED] {base.get('hypothesis','')}  ⊕  {other.get('hypothesis','')}"
    )[:1000]
    return child


def RECOMBINE(
    parent_a_spec: dict,
    parent_b_spec: dict,
    seed: int = 0,
    signal_from: str = "a",
) -> dict:
    """
    Splice two parent alphas into one child and validate.

    See op_splice docstring for semantics. This is the only command that
    crosses mechanism families — use it when EXPLORE within one parent has
    plateaued and you want to test whether a second mechanism's features
    rescue or amplify the edge.
    """
    rng = random.Random(seed)
    child = op_splice(parent_a_spec, parent_b_spec, rng, signal_from=signal_from)
    if child is None:
        raise ValueError(
            f"Splice not applicable: same alpha_id, missing sensor dependencies, "
            f"or invalid signal_from='{signal_from}'."
        )
    if not validate_alpha(child):
        raise ValueError(
            f"Spliced child '{child['alpha_id']}' failed AlphaLoader validation. "
            f"Most common cause: signal_from='{signal_from}' expects a schema field "
            f"the base parent provided but the splice mutated incompatibly. Try "
            f"signal_from='{'b' if signal_from=='a' else 'a'}' or inspect the unioned sensors manually."
        )
    print(f"RECOMBINE: {parent_a_spec['alpha_id']}  x  {parent_b_spec['alpha_id']}  "
          f"--[{child['lineage']['mutation_type']}]-->  {child['alpha_id']}")

    # Auto-adopt validated splice children (same contract as MUTATE).
    try:
        ADOPT(child, source=f"RECOMBINE:{signal_from}")
    except Exception as e:
        print(f"  WARN: ADOPT failed for spliced child '{child['alpha_id']}': {e}")

    return child


print("Recombination operator registered: op_splice (binary, via RECOMBINE)")
```

---

## CELL 1c — `ADOPT` / `LIST_ACTIVE` (production-discovery handoff)

```python
import shutil, yaml as _yaml

ADOPTION_DEPENDENCY_BUNDLES: dict[str, dict[str, dict]] = {}


def _archive_prior_active() -> str | None:
    """Preserve the current active spec in ALPHA_DEV_DIR/_deprecated before swap."""
    prior_alpha_id = SESSION.get("active_alpha_id")
    if not prior_alpha_id:
        return None

    prior_yaml = os.path.join(ALPHA_ACTIVE_DIR, prior_alpha_id, f"{prior_alpha_id}.alpha.yaml")
    if not os.path.exists(prior_yaml):
        return None

    with open(prior_yaml, "r") as f:
        prior_spec = _yaml.safe_load(f)

    prior_version = str((prior_spec or {}).get("version", "unknown")).replace("/", "_")
    deprecated_dir = WORKSPACE.get("alpha_deprecated") or os.path.join(ALPHA_DEV_DIR, "_deprecated")
    os.makedirs(deprecated_dir, exist_ok=True)

    archive_name = f"{prior_alpha_id}_v{prior_version}.alpha.yaml"
    archive_path = os.path.join(deprecated_dir, archive_name)
    if os.path.exists(archive_path):
        archive_name = (
            f"{prior_alpha_id}_v{prior_version}_"
            f"{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.alpha.yaml"
        )
        archive_path = os.path.join(deprecated_dir, archive_name)

    shutil.copy2(prior_yaml, archive_path)
    return archive_path


def _resolve_adopt_dependency(alpha_id: str, owner_alpha_id: str | None = None) -> dict | None:
    """Resolve a dependency spec for adoption-time staging.

    Resolution order prefers session-local generated specs over shipped
    references so a promoted PORTFOLIO can consume a freshly mutated SIGNAL.
    """
    bundle = ADOPTION_DEPENDENCY_BUNDLES.get(owner_alpha_id or "", {})
    bundled = bundle.get(alpha_id)
    if bundled is not None:
        return copy.deepcopy(bundled)

    current_active = SESSION.get("active_alpha_id")
    candidates = [
        os.path.join(ALPHA_DEV_DIR, alpha_id, f"{alpha_id}.alpha.yaml"),
        os.path.join(ALPHA_ACTIVE_DIR, alpha_id, f"{alpha_id}.alpha.yaml"),
    ]
    if current_active:
        candidates.append(os.path.join(ALPHA_ACTIVE_DIR, current_active, alpha_id, f"{alpha_id}.alpha.yaml"))
    candidates.append(os.path.join(REFERENCE_ALPHA_DIR, alpha_id, f"{alpha_id}.alpha.yaml"))

    for path in candidates:
        if os.path.exists(path):
            with open(path, "r") as f:
                return _yaml.safe_load(f)
    return None


def _copy_computation_modules(spec: dict, alpha_id: str, target_dir: str) -> list[str]:
    """Stage external computation modules beside the adopted spec when needed."""
    missing_modules = []
    for feat in spec.get("features") or []:
        mod = feat.get("computation_module")
        if not mod:
            continue
        candidates = [
            os.path.join(ALPHA_DEV_DIR, alpha_id, os.path.basename(mod)),
            os.path.join(ALPHA_DEV_DIR, spec.get("lineage", {}).get("parent_id", ""),
                         os.path.basename(mod)),
            mod if os.path.isabs(mod) else None,
        ]
        src = next((c for c in candidates if c and os.path.exists(c)), None)
        if src is None:
            missing_modules.append(mod)
            continue
        shutil.copy2(src, os.path.join(target_dir, os.path.basename(mod)))
    return missing_modules


def _write_adopted_spec_bundle(target_dir: str, spec: dict, alpha_id: str) -> tuple[str, list[str]]:
    os.makedirs(target_dir, exist_ok=True)
    target_yaml = os.path.join(target_dir, f"{alpha_id}.alpha.yaml")
    with open(target_yaml, "w") as f:
        _yaml.dump(spec, f, default_flow_style=False, sort_keys=False)
    missing_modules = _copy_computation_modules(spec, alpha_id, target_dir)
    return target_yaml, missing_modules


def _collect_portfolio_dependencies(spec: dict, owner_alpha_id: str) -> tuple[dict[str, dict], list[str]]:
    resolved: dict[str, dict] = {}
    missing: list[str] = []
    for dependency_id in spec.get("depends_on_signals") or []:
        dependency_spec = _resolve_adopt_dependency(dependency_id, owner_alpha_id=owner_alpha_id)
        if dependency_spec is None:
            missing.append(dependency_id)
            continue
        resolved[dependency_id] = dependency_spec
    return resolved, missing


def _stage_portfolio_dependencies(resolved_dependencies: dict[str, dict], target_dir: str) -> list[str]:
    staged: list[str] = []
    for dependency_id, dependency_spec in resolved_dependencies.items():
        dep_dir = os.path.join(target_dir, dependency_id)
        _write_adopted_spec_bundle(dep_dir, dependency_spec, dependency_id)
        staged.append(dependency_id)
    return staged

# -------------------------------------------------------------------
# ADOPT — flip the platform's "currently live" alpha.
#
# The local platform discovers alphas by scanning `platform.yaml`'s
# `alpha_spec_dir`. Grok mirrors that contract by writing the freshly
# generated/mutated spec into ALPHA_ACTIVE_DIR/<alpha_id>/<alpha_id>.alpha.yaml
# and flipping SESSION["active_alpha_id"]. The next RUN_ACTIVE() (or any
# backtest with use_active_dir=True) loads through bootstrap._load_alphas
# exactly as scripts/run_backtest.py would.
#
# Active bundle (atomic swap):
#   ALPHA_ACTIVE_DIR is wiped on every ADOPT before writing the new active
#   subtree. The adopted alpha remains the single live root at
#   ALPHA_ACTIVE_DIR/<alpha_id>/, but PORTFOLIO alphas may stage one-level
#   nested SIGNAL dependencies under that subtree so bootstrap's discovery
#   path can load the full bundle from alpha_spec_dir.
#
# Validation gate:
#   ADOPT calls validate_alpha (Prompt 3) before writing. An invalid spec
#   never reaches the active dir, so RUN_ACTIVE() can never run a malformed
#   alpha. This matches EXPORT()'s gate.
#
# computation_module handling:
#   Current-main SIGNAL prompts usually keep logic inline in `signal:` and do
#   not ship external feature modules. If a spec does reference legacy
#   computation_module files, we resolve them relative to
#   ALPHA_DEV_DIR/<alpha_id>/ first (the save_alpha home), then warn if any
#   file is missing — at which point the user must save_alpha() the spec
#   before adopting.
# -------------------------------------------------------------------
def ADOPT(
    spec: dict,
    alpha_id: str | None = None,
    source: str = "manual",
) -> str:
    """
    Promote `spec` to the active alpha directory the platform will scan.

    Returns the path of the written .alpha.yaml. After ADOPT:
      SESSION["active_alpha_id"]  == alpha_id
      RUN_ACTIVE()                runs this alpha via the production
                                  discovery path (alpha_spec_dir).

    Args:
        spec:     .alpha.yaml dict (output of assemble_signal_alpha / MUTATE / RECOMBINE)
        alpha_id: defaults to spec["alpha_id"]; explicit value lets you alias
                  e.g. for a quick "active" handle independent of the lineage id.
        source:   free-form provenance tag stored in adoption_history. Suggested
                  values: "manual", "MUTATE", "RECOMBINE", "EVOLVE", "EXPORT".

    Raises:
        ValueError if validate_alpha rejects the spec.
    """
    assert isinstance(spec, dict), f"ADOPT expects a spec dict, got {type(spec).__name__}"
    alpha_id = alpha_id or spec.get("alpha_id")
    assert alpha_id, "spec is missing 'alpha_id' and no override provided"

    if not validate_alpha(spec):
        raise ValueError(
            f"ADOPT BLOCKED: spec '{alpha_id}' failed AlphaLoader validation. "
            f"Fix the spec before adopting — RUN_ACTIVE() must never run a "
            f"malformed alpha."
        )

    dependency_ids = list(spec.get("depends_on_signals") or []) if spec.get("layer") == "PORTFOLIO" else []
    resolved_dependencies: dict[str, dict] = {}
    missing_dependencies: list[str] = []
    if dependency_ids:
        resolved_dependencies, missing_dependencies = _collect_portfolio_dependencies(spec, owner_alpha_id=alpha_id)
        if missing_dependencies:
            raise ValueError(
                f"ADOPT BLOCKED: PORTFOLIO '{alpha_id}' is missing dependency spec(s) "
                f"for depends_on_signals={missing_dependencies}. Save or stage the parent SIGNAL first."
            )

    archived_prior = _archive_prior_active()

    # ---- Atomic swap: wipe then write ----
    for entry in os.listdir(ALPHA_ACTIVE_DIR):
        path = os.path.join(ALPHA_ACTIVE_DIR, entry)
        (shutil.rmtree if os.path.isdir(path) else os.remove)(path)

    target_dir = os.path.join(ALPHA_ACTIVE_DIR, alpha_id)
    target_yaml, missing_modules = _write_adopted_spec_bundle(target_dir, spec, alpha_id)
    staged_dependencies: list[str] = []
    if dependency_ids:
        staged_dependencies = _stage_portfolio_dependencies(resolved_dependencies, target_dir)

    if missing_modules:
        print(f"  WARN: ADOPT could not resolve {len(missing_modules)} "
              f"computation_module file(s): {missing_modules}. "
              f"RUN_ACTIVE() will fail at AlphaLoader time. "
              f"Run save_alpha(spec) with the .py files in the same dir first.")
    # ---- Update session state ----
    SESSION["active_alpha_id"] = alpha_id
    SESSION["active_dependency_alpha_ids"] = list(staged_dependencies)
    SESSION.setdefault("adoption_history", []).append({
        "alpha_id":   alpha_id,
        "source":     source,
        "ts":         datetime.datetime.utcnow().isoformat(),
        "lineage":    spec.get("lineage", {}),
        "archived_prior": archived_prior,
        "dependency_alpha_ids": list(staged_dependencies),
    })

    print(f"ADOPT: '{alpha_id}' is now the active alpha "
          f"(source={source}, dir={target_dir})")
    if archived_prior:
        print(f"  Archived prior active spec: {archived_prior}")
    if staged_dependencies:
        print(f"  Staged dependency SIGNALs: {staged_dependencies}")
    return target_yaml


def LIST_ACTIVE() -> dict:
    """
    Show the currently adopted alpha and the recent adoption history.

    Returns the dict for programmatic use; also prints a human-readable view.
    The platform's discovery path (build_platform with use_active_dir=True)
    will load whatever is reported under 'active_alpha_id'.
    """
    aid = SESSION.get("active_alpha_id")
    history = SESSION.get("adoption_history") or []

    print(f"\n{'='*60}")
    print(f"ACTIVE ALPHA")
    print(f"{'='*60}")
    if not aid:
        print("  (none — call ADOPT(spec) or any MUTATE/RECOMBINE/EVOLVE)")
        print(f"{'='*60}\n")
        return {"active_alpha_id": None, "history": []}

    target_yaml = os.path.join(ALPHA_ACTIVE_DIR, aid, f"{aid}.alpha.yaml")
    on_disk = os.path.exists(target_yaml)
    dependency_ids = SESSION.get("active_dependency_alpha_ids") or []
    print(f"  active_alpha_id : {aid}")
    print(f"  spec path       : {target_yaml}")
    print(f"  on disk         : {'YES' if on_disk else 'MISSING — re-ADOPT'}")
    if dependency_ids:
        print(f"  staged deps     : {dependency_ids}")
    print(f"\n  Recent adoptions ({len(history)} total, last 5 shown):")
    for h in history[-5:]:
        archived = h.get("archived_prior")
        deps = h.get("dependency_alpha_ids") or []
        suffix = f"  archived={archived}" if archived else ""
        if deps:
            suffix += f"  deps={deps}"
        print(f"    {h['ts']}  {h['source']:10s}  {h['alpha_id']}{suffix}")
    print(f"{'='*60}\n")

    return {
        "active_alpha_id": aid,
        "spec_path":       target_yaml,
        "on_disk":         on_disk,
        "dependency_alpha_ids": dependency_ids,
        "history":         history,
    }


print("ADOPT(spec) / LIST_ACTIVE(): ACTIVE — production discovery handoff online.")
```

---

## CELL 2 — `MUTATE`: single deterministic mutation

```python
def MUTATE(
    parent_spec: dict,
    operator: str,
    seed: int = 0,
    **operator_kwargs,
) -> dict:
    """
    Apply a single named mutation operator to `parent_spec` and return the child.

    Determinism contract: same (parent_spec, operator, seed, kwargs) → bit-identical
    child spec. This is verified by SELFCHECK_MUTATION() below.

    The child carries a `lineage` block that downstream TEST/EXPORT use to
    populate parent_id and mutation_type in the registry.
    """
    if operator not in MUTATION_OPERATORS:
        raise ValueError(f"Unknown operator '{operator}'. "
                         f"Available: {list(MUTATION_OPERATORS)}")
    rng = random.Random(seed)
    child = MUTATION_OPERATORS[operator](parent_spec, rng, **operator_kwargs)
    if child is None:
        raise ValueError(
            f"Operator '{operator}' is not applicable to parent "
            f"'{parent_spec.get('alpha_id')}' (returned None — see operator docstring)."
        )

    # Validate immediately so the user discovers schema breakage now,
    # not three commands downstream.
    if not validate_alpha(child):
        raise ValueError(
            f"Mutated child '{child['alpha_id']}' failed AlphaLoader validation. "
            f"Operator '{operator}' produced an invalid spec — fix the operator, "
            f"or this parent is not mutable along this axis."
        )

    print(f"MUTATE: {parent_spec['alpha_id']} --[{operator}]--> {child['alpha_id']}")

    # Adopt every validated child — closes the autonomy loop. The next
    # RUN_ACTIVE() will discover this spec via alpha_spec_dir, exactly as
    # scripts/run_backtest.py would. Per architecture decision: every
    # validated MUTATE/RECOMBINE child + every EVOLVE strict-improvement
    # winner flips the live spec.
    try:
        ADOPT(child, source=f"MUTATE:{operator}")
    except Exception as e:
        print(f"  WARN: ADOPT failed for child '{child['alpha_id']}': {e}. "
              f"Spec is valid but not promoted; RUN_ACTIVE() will use prior active.")

    return child


def SELFCHECK_MUTATION(parent_spec: dict, operator: str, seed: int = 0) -> bool:
    """
    Determinism check for the mutation layer itself: applying the same
    operator with the same seed twice must yield identical specs.
    Mirrors SELFCHECK() (Prompt 4) but for the autonomy layer.
    """
    a = MUTATE(parent_spec, operator, seed=seed)
    b = MUTATE(parent_spec, operator, seed=seed)
    a2 = json.dumps(a, sort_keys=True, default=str)
    b2 = json.dumps(b, sort_keys=True, default=str)
    ok = (a2 == b2)
    print(f"SELFCHECK_MUTATION({operator}, seed={seed}): "
          f"{'PASS' if ok else 'FAIL — Inv-5 violated in mutation layer'}")
    assert ok, "Mutation operator is non-deterministic"
    return ok
```

---

## CELL 3 — `EXPLORE`: parallel siblings + Holm-corrected ranking

```python
def EXPLORE(
    parent_spec: dict,
    n: int = 8,
    operators: list[str] | None = None,
    symbols: list[str] | None = None,
    train_dates: list[str] | None = None,
    oos_dates:   list[str] | None = None,
    regime_engine: str | None = "hmm_3state_fractional",
    seed: int = 42,
    alpha: float = 0.05,
) -> dict:
    """
    Generate `n` mutated siblings of `parent_spec`, run TEST() on each, then
    apply Holm-Bonferroni correction over the family of bootstrap p-values.

    Why Holm over the family:
      Without MHT correction, running 8 candidates and reporting the best
      one inflates the false-discovery rate roughly 8×. Holm gives a
      uniformly more powerful FWER-controlled adjustment than Bonferroni
      while requiring no independence assumption.

    Returns:
      dict with:
        family_id      — sha1(parent_id + seed)
        n_candidates   — actual children generated (may be < n if some operators returned None)
        results        — list of {child_id, operator, report, q_value, survives}
        n_survivors    — children with q_value < alpha AND TEST verdict in {DEPLOY, VALIDATE}
        ranked         — children sorted by oos_sharpe (descending), survivors first

    Side effects:
      - Each child's TEST report is written under WORKSPACE["experiments"].
      - Each surviving child is auto-registered (no auto-EXPORT — the user
        chooses which survivor to promote).
    """
    operators = operators or list(MUTATION_OPERATORS.keys())
    symbols    = symbols    or SESSION.get("symbols")
    train_dates = train_dates or SESSION.get("train_dates")
    oos_dates   = oos_dates   or SESSION.get("oos_dates")
    assert symbols and train_dates and oos_dates, (
        "EXPLORE requires symbols/train_dates/oos_dates either as args or in SESSION"
    )

    family_seed = hashlib.sha1(f"{parent_spec['alpha_id']}|{seed}".encode()).hexdigest()[:12]
    print(f"\n{'='*60}")
    print(f"EXPLORE: parent={parent_spec['alpha_id']}  family={family_seed}")
    print(f"  n={n}  operators={operators}")
    print(f"{'='*60}\n")

    rng = random.Random(seed)
    children: list[dict] = []
    attempts = 0
    while len(children) < n and attempts < n * 5:
        attempts += 1
        op = rng.choice(operators)
        try:
            child = MUTATE(parent_spec, op, seed=rng.randrange(1 << 30))
            children.append({"spec": child, "operator": op})
        except ValueError as e:
            # Operator inapplicable — try another. Logged but not fatal.
            print(f"  skip {op}: {e}")

    if not children:
        return {"error": "no applicable operators produced a valid child",
                "family_id": family_seed}

    # Run TEST on each child. n_trials = len(children) so DSR penalizes
    # selection bias correctly inside each child's own falsification.
    results = []
    parent_hyp = {"statement": parent_spec.get("hypothesis", ""),
                  "mechanism_id": "evolved_from_" + parent_spec["alpha_id"]}
    for i, c in enumerate(children, 1):
        print(f"\n--- Child {i}/{len(children)}: {c['spec']['alpha_id']} "
              f"({c['operator']}) ---")
        try:
            report = TEST(
                hypothesis = parent_hyp,
                spec       = c["spec"],
                symbols    = symbols,
                train_dates = train_dates,
                oos_dates   = oos_dates,
                regime_engine = regime_engine,
                n_trials   = len(children),
            )
            # Inject lineage into the report so registry stamps it correctly.
            report["lineage"] = c["spec"].get("lineage", {})
            p_val = report.get("steps", {}).get("falsification", {}).get("bootstrap_pvalue", 1.0)
            results.append({
                "child_id":  c["spec"]["alpha_id"],
                "operator":  c["operator"],
                "spec":      c["spec"],
                "report":    report,
                "p_value":   p_val,
            })
        except Exception as e:
            print(f"  child failed: {e}")
            results.append({
                "child_id":  c["spec"]["alpha_id"],
                "operator":  c["operator"],
                "spec":      c["spec"],
                "report":    {"error": str(e), "verdict": "ERROR"},
                "p_value":   1.0,
            })

    # ---- Holm-Bonferroni correction over the family ----
    p_values = [r["p_value"] for r in results]
    holm = holm_correction(p_values, alpha=alpha)   # Prompt 4 helper
    for r, q, rejected in zip(results, holm["q_values"], holm["rejected"]):
        verdict = r["report"].get("verdict", "ERROR")
        r["q_value"]   = q
        r["survives"]  = bool(rejected) and verdict in ("DEPLOY", "VALIDATE")
        # Stamp the family-corrected q-value into the report so it flows
        # through to the registry via _registry_upsert.
        r["report"]["holm_qvalue"] = q

    # ---- Persist the family summary ----
    n_survivors = sum(r["survives"] for r in results)
    family_dir = os.path.join(WORKSPACE["experiments"],
                              f"family_{family_seed}_{parent_spec['alpha_id']}")
    os.makedirs(family_dir, exist_ok=True)
    with open(os.path.join(family_dir, "family_summary.json"), "w") as f:
        json.dump({
            "family_id":   family_seed,
            "parent_id":   parent_spec["alpha_id"],
            "seed":        seed,
            "alpha":       alpha,
            "method":      holm["method"],
            "n_candidates": len(results),
            "n_survivors": n_survivors,
            "results": [{
                "child_id":  r["child_id"],
                "operator":  r["operator"],
                "p_value":   r["p_value"],
                "q_value":   r["q_value"],
                "survives":  r["survives"],
                "verdict":   r["report"].get("verdict"),
                "oos_sharpe": r["report"].get("steps", {}).get("oos", {}).get("sharpe"),
                "lineage":   r["spec"].get("lineage"),
            } for r in results],
        }, f, indent=2, default=str)

    # ---- Auto-register every survivor (no auto-EXPORT) ----
    for r in results:
        if r["survives"]:
            # Use a synthetic fingerprint from TEST output. EXPORT will
            # rebuild the full fingerprint when the user promotes the child.
            oos = r["report"].get("steps", {}).get("oos", {})
            fp = {
                "n_trades":    oos.get("n"),
                "total_pnl":   oos.get("mean_pnl"),
                "pnl_hash":    r["report"].get("oos_pnl_hash"),
                "config_hash": r["report"].get("oos_config_hash"),
                "parity_hash": r["report"].get("oos_parity_hash"),
            }
            _registry_upsert(r["child_id"], r["spec"]["alpha_id"], r["report"], fp)

    # ---- Rank survivors first, then by OOS Sharpe ----
    def _key(r):
        s = r["report"].get("steps", {}).get("oos", {}).get("sharpe") or -1e9
        return (not r["survives"], -s)
    ranked = sorted(results, key=_key)

    print(f"\n{'='*60}")
    print(f"EXPLORE complete: {n_survivors}/{len(results)} survivors after Holm @ alpha={alpha}")
    print(f"  family dir: {family_dir}")
    print(f"  Top 3:")
    for r in ranked[:3]:
        s = r["report"].get("steps", {}).get("oos", {}).get("sharpe") or 0
        print(f"    {r['child_id']:60s} sharpe={s:+.3f}  q={r['q_value']:.4f}  "
              f"surv={r['survives']}  op={r['operator']}")
    print(f"{'='*60}\n")

    return {
        "family_id":    family_seed,
        "n_candidates": len(results),
        "n_survivors":  n_survivors,
        "results":      results,
        "ranked":       ranked,
        "family_dir":   family_dir,
    }
```

---

## CELL 4 — `EVOLVE`: multi-generation evolutionary loop

```python
def EVOLVE(
    seed_spec: dict,
    n_generations: int = 3,
    children_per_gen: int = 6,
    operators: list[str] | None = None,
    promotion_min_sharpe: float = 0.8,
    seed: int = 7,
    **explore_kwargs,
) -> dict:
    """
    Multi-generation autonomous evolution.

    For each generation:
      1. EXPLORE the current champion (parent of the next generation).
      2. The next generation's parent is the highest-Sharpe Holm-survivor
         that strictly improves OOS Sharpe over the current champion.
      3. If no survivor improves, the loop halts (local maximum reached).

    All intermediate families are persisted; the full lineage chain is
    written to evolution_run.json. Returns the chain so the user can
    inspect generation-by-generation drift in mechanism / parameters.

    Halting conditions:
      - No survivor improves the champion's OOS Sharpe (early stop)
      - n_generations reached
      - All operators inapplicable (degenerate parent)

    The user, NOT this function, decides what to deploy. EVOLVE is for
    research; promotion still goes through EXPORT + VERIFY.
    """
    rng = random.Random(seed)
    operators = operators or list(MUTATION_OPERATORS.keys())

    champion = copy.deepcopy(seed_spec)
    chain = [{
        "generation": 0,
        "alpha_id":   champion["alpha_id"],
        "lineage":    champion.get("lineage", {"parent_id": None,
                                               "mutation_type": "seed"}),
        "oos_sharpe": None,   # baseline measured below
    }]

    # Establish the baseline by running a single TEST on the seed.
    print(f"\n[EVOLVE] Baseline TEST on seed alpha {champion['alpha_id']}")
    base_report = TEST(
        hypothesis  = {"statement": champion.get("hypothesis", ""),
                       "mechanism_id": champion["alpha_id"]},
        spec        = champion,
        symbols     = explore_kwargs.get("symbols")    or SESSION.get("symbols"),
        train_dates = explore_kwargs.get("train_dates") or SESSION.get("train_dates"),
        oos_dates   = explore_kwargs.get("oos_dates")   or SESSION.get("oos_dates"),
        regime_engine = explore_kwargs.get("regime_engine", "hmm_3state_fractional"),
        n_trials    = 1,
    )
    chain[0]["oos_sharpe"] = (base_report.get("steps", {})
                                          .get("oos", {})
                                          .get("sharpe") or 0)
    chain[0]["verdict"] = base_report.get("verdict")

    for gen in range(1, n_generations + 1):
        print(f"\n{'#'*60}")
        print(f"# GENERATION {gen}/{n_generations} — champion {champion['alpha_id']} "
              f"(sharpe={chain[-1]['oos_sharpe']:+.3f})")
        print(f"{'#'*60}")

        family = EXPLORE(
            parent_spec = champion,
            n           = children_per_gen,
            operators   = operators,
            seed        = rng.randrange(1 << 30),
            **explore_kwargs,
        )

        survivors = [r for r in family["ranked"] if r["survives"]]
        if not survivors:
            print(f"[EVOLVE] Generation {gen}: no Holm-survivors. Halting.")
            chain.append({"generation": gen, "halt_reason": "no_holm_survivors"})
            break

        # Pick the survivor with the best OOS sharpe that ALSO improves on the champion.
        best = survivors[0]
        best_sr = best["report"].get("steps", {}).get("oos", {}).get("sharpe") or -1e9
        if best_sr <= chain[-1]["oos_sharpe"]:
            print(f"[EVOLVE] Generation {gen}: best survivor sharpe={best_sr:+.3f} "
                  f"≤ champion {chain[-1]['oos_sharpe']:+.3f}. Local max — halting.")
            chain.append({"generation": gen, "halt_reason": "no_improvement",
                          "best_candidate_sharpe": best_sr})
            break

        # Promote inside the loop (research-only — does NOT call EXPORT).
        champion = best["spec"]
        chain.append({
            "generation": gen,
            "alpha_id":   champion["alpha_id"],
            "lineage":    champion.get("lineage"),
            "oos_sharpe": best_sr,
            "verdict":    best["report"].get("verdict"),
            "q_value":    best["q_value"],
            "operator":   best["operator"],
        })
        print(f"[EVOLVE] Generation {gen}: new champion {champion['alpha_id']} "
              f"sharpe={best_sr:+.3f} (Δ={best_sr - chain[-2]['oos_sharpe']:+.3f}) "
              f"via {best['operator']}")

        # Re-adopt the champion at the END of the generation. EXPLORE's
        # MUTATE calls auto-adopted each child as it was generated, so the
        # active alpha at this point is whichever child happened to be
        # MUTATEd LAST — not necessarily the survivor we just promoted.
        # Re-adopt explicitly so RUN_ACTIVE() reflects EVOLVE's verdict,
        # not EXPLORE's last sample.
        try:
            ADOPT(champion, source=f"EVOLVE:gen{gen}")
        except Exception as e:
            print(f"  WARN: EVOLVE could not adopt champion '{champion['alpha_id']}': {e}")

    # ---- Persist full chain ----
    run_id = hashlib.sha1(f"{seed_spec['alpha_id']}|{seed}".encode()).hexdigest()[:8]
    out_dir = os.path.join(WORKSPACE["experiments"], f"evolution_{run_id}")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "evolution_run.json")
    with open(out_path, "w") as f:
        json.dump({
            "run_id":             run_id,
            "seed_alpha":         seed_spec["alpha_id"],
            "seed":               seed,
            "n_generations":      n_generations,
            "children_per_gen":   children_per_gen,
            "promotion_min_sharpe": promotion_min_sharpe,
            "chain":              chain,
            "final_champion":     champion["alpha_id"],
        }, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"EVOLVE complete: {len(chain)-1} generations explored, "
          f"final champion {champion['alpha_id']}")
    print(f"  Run dir: {out_dir}")
    print(f"  To deploy: EXPORT('{champion['alpha_id']}', report, spec)  "
          f"after rerunning TEST + SELFCHECK against the champion's spec.")
    print(f"{'='*60}\n")

    return {
        "run_id":         run_id,
        "chain":          chain,
        "final_champion": champion,
        "out_dir":        out_dir,
    }
```

---

## CELL 5 — `AUDIT`: post-promotion CPCV decay monitor

```python
def AUDIT(
    signal_id: str,
    symbols: list[str] | None = None,
    audit_dates: list[str] | None = None,
    cpcv_groups: int = 6,
    cpcv_k_test: int = 2,
    embargo_days: int = 1,
    decay_threshold_pct: float = 30.0,
    ic_decay_threshold: float = 0.5,
    regime_engine: str | None = "hmm_3state_fractional",
) -> dict:
    """
    Post-promotion edge-decay audit.

    Re-runs CPCV + IC on a FRESH window (`audit_dates`, default = SESSION
    last LOAD window) and compares against the original OOS hashes / metrics
    captured at EXPORT time. Writes the verdict back into the registry's
    `audit_*` columns so the PI can see decay at a glance via REGISTRY().

    Why this exists (Inv-4: decay is the default):
      Promotion was gated on the OOS window that produced the artifact.
      Once live capital is at risk, the only honest way to detect erosion
      is to keep replaying the strategy on new data and watch the metrics
      drift. This command does NOT change the artifact — it only stamps
      the registry with current health, so the PI's quarantine decision is
      evidence-based.

    Verdicts (written to row['audit_status']):
      HEALTHY      — sharpe decay <= threshold AND |IC| >= threshold * baseline
      DEGRADED     — sharpe decay > threshold OR  IC magnitude collapsed
      DEAD         — current sharpe <= 0 OR fraction_positive < 50%
      MISSING_DATA — audit window load failed; nothing changed in the registry

    Decay calculations:
      sharpe_decay_pct = (oos_sharpe_at_export - audit_sharpe) / |oos_sharpe_at_export|
                        positive number means the edge weakened.
      ic_decay         = audit_ic / oos_ic_at_export
                        ratio < ic_decay_threshold means the predictive signal collapsed.

    The original artifact's `parity_pnl_hash` is read for traceability but
    is NOT compared (the audit window is, by design, different data).
    """
    assert os.path.exists(REGISTRY_PATH), "Registry not initialized"
    with open(REGISTRY_PATH, "r") as f:
        rows = list(csv.DictReader(f))
    row = next((r for r in rows if r.get("signal_id") == signal_id), None)
    assert row is not None, f"signal_id '{signal_id}' not in registry"

    alpha_id = row.get("alpha_id") or signal_id
    spec_path = Path(WORKSPACE["alphas"]) / f"{alpha_id}.alpha.yaml"
    if not spec_path.exists():
        # Fall back to the experiments tree (EXPORT writes there too).
        candidates = list(Path(WORKSPACE["experiments"]).rglob(f"{alpha_id}.alpha.yaml"))
        if candidates:
            spec_path = candidates[-1]
        else:
            return {"audit_status": "MISSING_SPEC",
                    "error": f"No .alpha.yaml found for alpha_id={alpha_id}",
                    "signal_id": signal_id}

    symbols = symbols or SESSION.get("loaded_symbols") or SESSION.get("symbols")
    audit_dates = audit_dates or SESSION.get("loaded_dates") or SESSION.get("oos_dates")
    if not (symbols and audit_dates and len(audit_dates) >= cpcv_groups * 2):
        return {"audit_status": "MISSING_DATA",
                "error": (f"Need symbols + >= {cpcv_groups*2} audit_dates. "
                          f"Got symbols={symbols}, n_dates={len(audit_dates) if audit_dates else 0}"),
                "signal_id": signal_id}

    print(f"\n{'='*60}")
    print(f"AUDIT: {signal_id} (alpha {alpha_id})")
    print(f"  audit window: {audit_dates[0]} … {audit_dates[-1]}  ({len(audit_dates)} days)")
    print(f"  cpcv: groups={cpcv_groups} k_test={cpcv_k_test} embargo={embargo_days}d")
    print(f"{'='*60}")

    # ---- Re-run CPCV on the audit window ----
    cpcv_result = cpcv_backtest(
        spec_path, symbols, audit_dates,
        n_groups=cpcv_groups, k_test=cpcv_k_test, embargo_days=embargo_days,
        regime_engine=regime_engine,
    )

    # ---- Re-run IC on the audit window (last day for tractability) ----
    audit_log = LOAD(symbols, audit_dates[0], audit_dates[-1])
    if audit_log is None:
        return {"audit_status": "MISSING_DATA",
                "error": "LOAD failed for audit window", "signal_id": signal_id}
    try:
        ic_result = compute_ic(spec_path, audit_log, regime_engine=regime_engine)
    except Exception as e:
        ic_result = {"ic_mean": 0.0, "ic_tstat": 0.0, "error": str(e)}

    # ---- Decay computation against the EXPORT-time baseline ----
    def _flt(v: str | None) -> float | None:
        try:    return float(v) if v not in (None, "") else None
        except ValueError: return None

    base_sharpe = _flt(row.get("oos_sharpe"))
    base_ic     = _flt(row.get("ic_mean"))
    cur_sharpe  = cpcv_result.get("sharpe_mean")
    cur_ic      = ic_result.get("ic_mean")

    sharpe_decay_pct = None
    if base_sharpe is not None and abs(base_sharpe) > 1e-9 and cur_sharpe is not None:
        sharpe_decay_pct = (base_sharpe - cur_sharpe) / abs(base_sharpe) * 100.0

    ic_decay = None
    if base_ic is not None and abs(base_ic) > 1e-9 and cur_ic is not None:
        ic_decay = cur_ic / base_ic   # ratio: 1.0 = no decay, 0 = total collapse

    # ---- Verdict ----
    frac_pos = cpcv_result.get("fraction_positive") or 0
    if cur_sharpe is not None and (cur_sharpe <= 0 or frac_pos < 0.5):
        verdict = "DEAD"
    elif (
        (sharpe_decay_pct is not None and sharpe_decay_pct > decay_threshold_pct)
        or (ic_decay is not None and abs(ic_decay) < ic_decay_threshold)
    ):
        verdict = "DEGRADED"
    else:
        verdict = "HEALTHY"

    print(f"  baseline  sharpe={base_sharpe}  ic={base_ic}")
    print(f"  audit     sharpe={cur_sharpe}    ic={cur_ic}    frac_pos={frac_pos:.1%}")
    if sharpe_decay_pct is not None:
        print(f"  decay     sharpe={sharpe_decay_pct:+.1f}%   ic_ratio={ic_decay if ic_decay is not None else 'n/a'}")
    print(f"  verdict   {verdict}")
    print(f"{'='*60}")

    # ---- Write audit fields back to the registry row ----
    row["audit_status"]            = verdict
    row["audit_last_run"]          = datetime.datetime.utcnow().isoformat()
    row["audit_sharpe_decay_pct"]  = (round(sharpe_decay_pct, 2)
                                      if sharpe_decay_pct is not None else "")
    row["audit_ic_decay"]          = (round(ic_decay, 4)
                                      if ic_decay is not None else "")
    row["updated_at"]              = row["audit_last_run"]
    if verdict == "DEAD":
        row["status"] = "quarantined"

    with open(REGISTRY_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_COLS)
        w.writeheader()
        w.writerows(rows)

    return {
        "signal_id":            signal_id,
        "alpha_id":             alpha_id,
        "audit_status":         verdict,
        "baseline_sharpe":      base_sharpe,
        "audit_sharpe":         cur_sharpe,
        "sharpe_decay_pct":     sharpe_decay_pct,
        "baseline_ic":          base_ic,
        "audit_ic":             cur_ic,
        "ic_decay":             ic_decay,
        "cpcv_fraction_positive": frac_pos,
        "audit_window":         (audit_dates[0], audit_dates[-1]),
    }


print("AUDIT(signal_id) ACTIVE — post-promotion decay monitor.")
```

---

## CELL 6 — `LINEAGE`: human-readable ancestry walk

```python
def LINEAGE(signal_id: str, depth: int = 10) -> list[dict]:
    """
    Walk the registry up to `depth` generations and print the ancestry of `signal_id`.

    Reads parent_id, co_parent_id, mutation_type, and IC fields from REGISTRY_PATH (Prompt 5).
    Surfaces IC stability across the chain so the user can see whether the
    edge persists across mutations or whether successive children rely on
    increasingly fragile predictive signals.
    """
    if not os.path.exists(REGISTRY_PATH):
        print("Registry is empty.")
        return []
    with open(REGISTRY_PATH, "r") as f:
        rows = list(csv.DictReader(f))
    by_id = {r["signal_id"]: r for r in rows}

    chain = []
    cur = signal_id
    for _ in range(depth):
        row = by_id.get(cur)
        if not row:
            break
        chain.append(row)
        parent = row.get("parent_id") or ""
        if not parent or parent == cur:
            break
        cur = parent

    # Helper: parse a numeric registry cell, returning None on blank/garbage.
    def _f(v):
        try:    return float(v) if v not in (None, "") else None
        except ValueError: return None

    # Walk the chain root → leaf for printing (chain was built leaf → root).
    walk = list(reversed(chain))

    print(f"\nLineage of {signal_id} ({len(chain)} ancestors shown, root → leaf):")
    print(f"{'─'*120}")
    print(f"  {'gen':>3}  {'signal_id':40s}  {'op':15s}  "
          f"{'sharpe':>7}  {'IC':>8}  {'IC_t':>6}  {'ΔIC':>7}  "
          f"{'q':>7}  {'audit':10s}")
    print(f"{'─'*120}")

    prev_ic = None
    for i, r in enumerate(walk):
        is_leaf = (i == len(walk) - 1)
        marker  = "└─" if is_leaf else "├─"
        ic      = _f(r.get("ic_mean"))
        delta_ic = ""
        if ic is not None and prev_ic is not None:
            delta_ic = f"{ic - prev_ic:+.4f}"
        elif i == 0:
            delta_ic = "—"

        co_parent = r.get("co_parent_id") or ""
        op_label = (r.get("mutation_type") or "seed") or "seed"
        if co_parent:
            op_label = f"{op_label}*"   # asterisk flags binary recombination

        print(f"  {marker}{r.get('generation','?'):>3}  "
              f"{r.get('signal_id','?'):40s}  "
              f"{op_label:15s}  "
              f"{(r.get('oos_sharpe','') or ''):>7}  "
              f"{(r.get('ic_mean','') or ''):>8}  "
              f"{(r.get('ic_tstat','') or ''):>6}  "
              f"{delta_ic:>7}  "
              f"{(r.get('holm_qvalue','') or ''):>7}  "
              f"{(r.get('audit_status','') or '-'):10s}")
        if co_parent:
            print(f"     │  co_parent: {co_parent}")
        if ic is not None:
            prev_ic = ic
    print(f"{'─'*120}")
    print("  * = binary splice (RECOMBINE); ΔIC computed root→leaf where both ICs present.")

    # Stability summary across the chain.
    ic_vals = [v for v in (_f(r.get("ic_mean")) for r in walk) if v is not None]
    if len(ic_vals) >= 2:
        import statistics as _stats
        mean_ic   = _stats.mean(ic_vals)
        stdev_ic  = _stats.pstdev(ic_vals)
        # Classify chain health: low CV with strictly positive IC = stable mechanism.
        cv = stdev_ic / max(abs(mean_ic), 1e-9)
        all_pos = all(v > 0 for v in ic_vals)
        all_neg = all(v < 0 for v in ic_vals)
        sign_consistent = all_pos or all_neg
        if cv < 0.5 and sign_consistent:
            health = "STABLE  — sign-consistent IC, low dispersion (mechanism preserved across mutations)"
        elif sign_consistent:
            health = "DRIFTING — sign-consistent IC but high dispersion (operating-point sensitive)"
        else:
            health = "UNSTABLE — IC sign flips across mutations (no preserved edge)"
        print(f"  IC chain summary: n={len(ic_vals)}  mean={mean_ic:+.4f}  "
              f"stdev={stdev_ic:.4f}  CV={cv:.2f}  →  {health}")
        print(f"{'─'*120}")
    return chain


print("EVOLVE / EXPLORE / MUTATE / RECOMBINE / SELFCHECK_MUTATION / AUDIT / LINEAGE: ACTIVE")
print("ADOPT / LIST_ACTIVE: ACTIVE — production discovery handoff online")
print("SHOW_MUTATION_PROTOCOL(): ACTIVE")
print("Evolution module: ACTIVE")
```

---

## EMBEDDED MUTATION CONTRACT

### Triggers

- Mutate only when there is decay, regime heterogeneity, cost drift, half-life drift, crowding, or a structural-break alarm.
- If the operator supplies none of those, ask for forensics instead of guessing.

### Axes

1. Regime refinement.
2. Sensor substitution for the same latent variable.
3. Horizon adjustment with cost and half-life recheck.
4. Universe refinement with an explicit selection criterion.
5. Layer promotion from SIGNAL to PORTFOLIO.

### Forbidden Moves

- Parameter sweeps without a mechanism hypothesis.
- Easier falsification criteria.
- Looser regime gates just to trade more.
- Cost or edge edits without a fresh rationale.
- Family renames used only to evade trend-mechanism constraints.

### Pre-Emit Checklist

- Name one axis.
- State the trigger and forensics.
- Keep schema and layer stable unless the mutation is an explicit promotion.
- Recompute cost arithmetic whenever horizon, regime, or universe changed.
- Recheck `horizon_seconds / expected_half_life_seconds` when `trend_mechanism` exists.
- Preserve predecessor lineage rather than overwriting history in place.
- Keep falsification criteria mechanism-tied.

### Current Prompt-6 Scope

- Axis 1, 2, 3, and 4 are automated here through the seeded unary operator surface.
- Axis 5 is now available as deterministic template-based PORTFOLIO promotion via `op_promote_to_portfolio()`.
- `ADOPT()` performs live active-dir handoff; long-lived archival and deprecated-tree policy remain an operator concern outside this prompt surface.

## EVOLUTION MODULE STATUS

```
Unary operators:       perturb_param, substitute_sensor, adjust_horizon, refine_regime, refine_universe
Promotion helper:      op_promote_to_portfolio (template-based SIGNAL -> PORTFOLIO draft)
Binary operator:       op_splice (via RECOMBINE — sensor/parameter union, signal from chosen parent)
Determinism:           SELFCHECK_MUTATION asserts seeded reproducibility (Inv-5 in mutation layer)
MHT correction:        Holm-Bonferroni over each EXPLORE family (alpha=0.05 default)
DSR n_trials:          EXPLORE passes len(children) → falsification_battery deflates by trial count
Provenance:            child.lineage → report.lineage → registry.parent_id + co_parent_id + mutation_type
Adoption loop:         every validated MUTATE/RECOMBINE child + every EVOLVE strict-improvement
                       winner is ADOPTed → ALPHA_ACTIVE_DIR/<alpha_id>/<alpha_id>.alpha.yaml.
                       SESSION["active_alpha_id"] flips, RUN_ACTIVE() picks it up via the same
                       alpha_spec_dir discovery code path scripts/run_backtest.py uses.
Promotion:             EVOLVE picks champions in research; user calls EXPORT to deploy
                       (EXPORT also re-ADOPTs the exported alpha as the live spec).
Post-promotion:        AUDIT(signal_id) re-runs CPCV+IC on a fresh window, stamps audit_status
                       (HEALTHY / DEGRADED / DEAD) into the registry
Lineage view:          LINEAGE(signal_id) prints the chain root→leaf with IC stability summary
Persistence:           every EXPLORE → family_summary.json; every EVOLVE → evolution_run.json;
                       ALPHA_ACTIVE_DIR is ephemeral (one live bundle at a time) — lineage lives in
                       WORKSPACE["alphas"] + the registry, never here

Ready: EXPLORE(parent_spec, n=8)                     — Holm-corrected family of mutated siblings
       EVOLVE(seed_spec, n_generations=3)            — full hypothesis → mutation → selection loop
       RECOMBINE(parent_a, parent_b)                 — cross-mechanism splice
       ADOPT(spec, source='manual')                  — promote any spec to the live alpha dir
       LIST_ACTIVE()                                 — show currently adopted alpha + history
       AUDIT(signal_id)                              — post-promotion edge-decay monitor
       LINEAGE(signal_id)                            — ancestry walk with IC stability classification
```
