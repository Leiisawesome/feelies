# MODULE 7 - HYPOTHESIS REASONING: EMBEDDED PROTOCOL & GATE AUDIT

## ACTIVATION DIRECTIVE

This module embeds the reasoning contract required for paste-only Grok REPL
usage. It does not assume the user also pasted or mounted any companion docs.

Prompt 7 owns the embedded reasoning protocol, hard-gate checklist, mutation-axis
map, and anti-pattern refusals needed at proposal time. Prompt 3 carries the
sensor and schema execution surface. Prompt 6 carries the mutation execution
surface.

Default path:

1. use `pre_propose_audit()` to catch weak or forbidden requests early
2. use `SHOW_PROTOCOL_OVERVIEW()` if the operator needs the embedded contract
3. use `PROPOSE()` to clone a shipped reference alpha and apply bounded edits
4. run `audit_gates()` and `print_gate_audit()`
5. run `validate_alpha()`
6. derive a Prompt-4-ready hypothesis via `HYPOTHESIS_FROM_SPEC(spec)`
7. backtest via Prompt 4

---

## CELL 1 - Embedded protocol and helper surface

```python
import datetime, os, random, re, yaml

EMBEDDED_REASONING_PROTOCOL = {
    "mode_detection": [
        "If the operator names an existing alpha_id and asks to improve, rescue, or mutate it: MODE=MUTATION.",
        "If the operator asks for a new idea, new alpha, or new mechanism with no parent alpha_id: MODE=GENERATION.",
        "If the request is ambiguous, ask one precise clarifying question instead of guessing.",
    ],
    "generation_steps": [
        "Name the structural actor.",
        "State the mechanism in actor-action-incentive-observable form.",
        "Identify the L1 signature using shipped sensors only.",
        "Assign a horizon that is long enough to clear costs.",
        "Compute cost arithmetic and require margin_ratio >= 1.5.",
        "Specify regime on-condition, off-condition, and hysteresis.",
        "Write falsification criteria tied to the mechanism, not just PnL.",
    ],
    "output_contract": [
        "MODE line first.",
        "Reasoning block naming actor, mechanism, signature, horizon, regime, and falsification.",
        "Gate-audit block listing hard gates with PASS/FAIL/SKIP.",
        "Decision block that either EMITs, DRAFTs, or REFUSEs.",
        "Full YAML only after the reasoning and gate audit are complete.",
    ],
}

EMBEDDED_HARD_GATES = {
    "G1": "Layer classified as SENSOR, SIGNAL, or PORTFOLIO.",
    "G2": "Structural actor named specifically.",
    "G3": "Mechanism sentence parses in actor-action-incentive-observable form.",
    "G4": "Every referenced sensor exists in the shipped catalog or a companion SENSOR proposal exists.",
    "G5": "SIGNAL horizon_seconds >= 30.",
    "G6": "cost_arithmetic is fully populated and cites its basis.",
    "G7": "margin_ratio >= 1.5.",
    "G8": "regime_gate.on_condition and off_condition are both specified.",
    "G9": "Hysteresis margins are meaningfully separated.",
    "G10": "falsification_criteria are mechanism-tied, not pure PnL thresholds.",
    "G11": "Structural and regime-shift invalidators are named.",
    "G12": "At most 3 parameters have free search ranges.",
    "G13": "No look-ahead in feature definitions or signal bindings.",
    "G14": "No data dependency beyond L1 NBBO + trades + reference data.",
    "G15": "Fill assumptions remain consistent with platform routers.",
    "G16": "If trend_mechanism exists, family, fingerprint, half-life envelope, ratio, and failure-signature rules must all pass.",
}

EMBEDDED_MUTATION_PROTOCOL = {
    "triggers": [
        "Realized IC decay versus in-sample.",
        "Per-regime IC heterogeneity.",
        "Cost arithmetic drift.",
        "Half-life drift.",
        "Mechanism crowding.",
        "Structural-break alarm on a fingerprint sensor.",
    ],
    "axes": {
        1: "Regime refinement.",
        2: "Sensor substitution for the same latent variable.",
        3: "Horizon adjustment with cost recheck.",
        4: "Universe refinement with an explicit selection criterion.",
        5: "Layer promotion from SIGNAL to PORTFOLIO.",
    },
    "forbidden": [
        "Parameter sweeps without a mechanism hypothesis.",
        "Adding new measurements without naming the latent variable.",
        "Making falsification criteria easier to satisfy.",
        "Loosening the regime gate just to trade more.",
        "Lowering hurdle_bps or inflating edge_estimate_bps without a fresh rationale.",
        "Renaming trend families just to evade G16.",
    ],
}

PROMPT7_PROPOSAL_CONTEXT: dict[str, dict] = {}


def REGISTER_PROPOSAL_CONTEXT(alpha_id: str, **context) -> dict:
    stored = dict(PROMPT7_PROPOSAL_CONTEXT.get(alpha_id, {}))
    for key, value in context.items():
        if value is not None:
            stored[key] = value
    PROMPT7_PROPOSAL_CONTEXT[alpha_id] = stored
    return stored


def _proposal_context_for(spec: dict, context: dict | None = None) -> dict:
    alpha_id = spec.get("alpha_id", "")
    merged = dict(PROMPT7_PROPOSAL_CONTEXT.get(alpha_id, {}))
    if context:
        for key, value in context.items():
            if value is not None:
                merged[key] = value
    return merged


def _text_blob(*parts) -> str:
    return "\n".join(str(part) for part in parts if part)


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _infer_signal_family(signal_id: str) -> str | None:
    family = REFERENCE_ALPHA_CATALOG.get(signal_id, {}).get("family")
    if family in MECHANISM_FAMILY_CATALOG:
        return family
    try:
        spec = load_reference_alpha(signal_id)
    except Exception:
        return None
    trend = spec.get("trend_mechanism") or {}
    family = trend.get("family")
    return family if family in MECHANISM_FAMILY_CATALOG else None


def _infer_parent_family(spec: dict) -> str | None:
    family = ((spec.get("trend_mechanism") or {}).get("family"))
    if family in MECHANISM_FAMILY_CATALOG and family != "PORTFOLIO_XSECT":
        return family
    family = REFERENCE_ALPHA_CATALOG.get(spec.get("alpha_id", ""), {}).get("family")
    return family if family in MECHANISM_FAMILY_CATALOG and family != "PORTFOLIO_XSECT" else None


def SHOW_PROTOCOL_OVERVIEW() -> None:
    print("\nEmbedded reasoning protocol")
    print("-" * 90)
    print("Mode detection")
    for line in EMBEDDED_REASONING_PROTOCOL["mode_detection"]:
        print(f"  - {line}")
    print("\nGeneration steps")
    for idx, line in enumerate(EMBEDDED_REASONING_PROTOCOL["generation_steps"], 1):
        print(f"  {idx}. {line}")
    print("\nOutput contract")
    for line in EMBEDDED_REASONING_PROTOCOL["output_contract"]:
        print(f"  - {line}")
    print("-" * 90)


def SHOW_HARD_GATES() -> None:
    print("\nEmbedded hard gates")
    print("-" * 90)
    for gate, description in EMBEDDED_HARD_GATES.items():
        print(f"{gate:4s} {description}")
    print("-" * 90)


def SHOW_MUTATION_AXES() -> None:
    print("\nEmbedded mutation protocol")
    print("-" * 90)
    print("Triggers")
    for line in EMBEDDED_MUTATION_PROTOCOL["triggers"]:
        print(f"  - {line}")
    print("\nAxes")
    for axis, label in EMBEDDED_MUTATION_PROTOCOL["axes"].items():
        print(f"  {axis}. {label}")
    print("\nForbidden")
    for line in EMBEDDED_MUTATION_PROTOCOL["forbidden"]:
        print(f"  - {line}")
    print("-" * 90)


def SHOW_OUTPUT_CONTRACT_EXAMPLES() -> None:
    print("\nEmbedded output contract examples")
    print("-" * 90)
    print(FORMAT_GENERATION_OUTPUT_TEMPLATE())
    print("-" * 90)
    print(FORMAT_MUTATION_OUTPUT_TEMPLATE())
    print("-" * 90)

print("Embedded protocol helpers: ACTIVE")
print("SHOW_PROTOCOL_OVERVIEW(), SHOW_HARD_GATES(), SHOW_MUTATION_AXES(), SHOW_OUTPUT_CONTRACT_EXAMPLES() available")
```

---

## CELL 2 - Gate audit helpers

```python
def audit_gates(spec: dict) -> dict:
    """Schema-aware embedded audit before calling AlphaLoader.

    This is a local screen for the paste-only Prompt-7 workflow. AlphaLoader
    remains the executable source of truth, but Prompt 7 now carries the gate
    descriptions and the subset of checks that can be evaluated directly from a
    schema-1.1 spec.
    """
    checks: dict[str, dict] = {}
    context = _proposal_context_for(spec)
    hypothesis_text = str(spec.get("hypothesis", "") or "")
    description_text = str(spec.get("description", "") or "")
    signal_text = str(spec.get("signal", "") or "")
    rationale_text = str(context.get("rationale", "") or "")
    analysis_text = _text_blob(hypothesis_text, description_text, signal_text, rationale_text)

    def _record(gate: str, status: str, message: str) -> None:
        checks[gate] = {"status": status, "pass": status != "FAIL", "message": message}

    layer = spec.get("layer")
    if layer in {"SENSOR", "SIGNAL", "PORTFOLIO"}:
        _record("G1", "PASS", f"layer={layer}")
    else:
        _record("G1", "FAIL", "layer must be SENSOR, SIGNAL, or PORTFOLIO")

    structural_actor = str(context.get("structural_actor", "") or "").strip()
    if len(structural_actor.split()) >= 2 and not _contains_any(structural_actor, ["someone", "some actor", "market participants", "traders"]):
        _record("G2", "PASS", f"structural_actor={structural_actor}")
    else:
        _record("G2", "FAIL", "structural_actor must be named explicitly in proposal context")

    mechanism_sentence = str(context.get("mechanism_sentence") or hypothesis_text).strip()
    mechanism_ok = (
        len(mechanism_sentence) >= 40
        and " because " in mechanism_sentence.lower()
        and re.search(r"(leak|show|surface|manifest|appear|observable|visible)", mechanism_sentence, flags=re.IGNORECASE)
    )
    if mechanism_ok:
        _record("G3", "PASS", "mechanism sentence includes incentive and observable signature")
    else:
        _record("G3", "FAIL", "mechanism sentence must include actor-action-incentive-observable structure")

    if spec.get("schema_version") == "1.1":
        _record("G_schema_1_1", "PASS", "schema_version is 1.1")
    else:
        _record("G_schema_1_1", "FAIL", "schema_version must be 1.1")

    horizon = spec.get("horizon_seconds")
    if layer == "SIGNAL":
        if horizon is not None and int(horizon) >= 30:
            _record("G5", "PASS", f"SIGNAL horizon_seconds={int(horizon)}")
        else:
            _record("G5", "FAIL", "SIGNAL horizon_seconds must be >= 30")
    elif layer == "PORTFOLIO":
        if horizon is not None and int(horizon) >= 300:
            _record("G5", "PASS", f"PORTFOLIO horizon_seconds={int(horizon)}")
        else:
            _record("G5", "FAIL", "PORTFOLIO horizon_seconds must be >= 300")
    elif horizon is not None:
        _record("G5", "PASS", f"non-SIGNAL horizon_seconds={int(horizon)}")
    else:
        _record("G5", "FAIL", "horizon_seconds missing; required for SIGNAL and PORTFOLIO")

    sensors = spec.get("depends_on_sensors") or []
    missing_sensors = [sensor_id for sensor_id in sensors if sensor_id not in SENSOR_CATALOG]
    if missing_sensors:
        _record("G4", "FAIL", f"unknown sensors: {missing_sensors}")
    else:
        _record("G4", "PASS", f"all depends_on_sensors entries are shipped sensors ({len(sensors)})")

    regime_gate = spec.get("regime_gate")
    if isinstance(regime_gate, dict):
        on_cond = regime_gate.get("on_condition")
        off_cond = regime_gate.get("off_condition")
        if on_cond and off_cond:
            _record("G8", "PASS", "regime_gate has on_condition and off_condition")
        else:
            _record("G8", "FAIL", "regime_gate needs both on_condition and off_condition")
        hysteresis = regime_gate.get("hysteresis") or {}
        posterior_margin = float(hysteresis.get("posterior_margin", 0.0) or 0.0)
        percentile_margin = float(hysteresis.get("percentile_margin", 0.0) or 0.0)
        if posterior_margin >= 0.15 or percentile_margin >= 0.15:
            _record("G9", "PASS", f"posterior_margin={posterior_margin}, percentile_margin={percentile_margin}")
        else:
            _record("G9", "FAIL", "hysteresis margins are too small")
    else:
        _record("G8", "FAIL", "regime_gate must be present and must be a mapping")
        _record("G9", "FAIL", "hysteresis cannot be checked without regime_gate")

    cost = spec.get("cost_arithmetic")
    if isinstance(cost, dict):
        required_cost_keys = {"edge_estimate_bps", "half_spread_bps", "impact_bps", "fee_bps", "margin_ratio"}
        missing_cost_keys = sorted(key for key in required_cost_keys if key not in cost)
        cost_basis = context.get("cost_basis") or cost.get("basis") or cost.get("edge_source")
        if missing_cost_keys:
            _record("G6", "FAIL", f"cost_arithmetic missing keys: {missing_cost_keys}")
        elif not cost_basis:
            _record("G6", "FAIL", "cost_arithmetic requires a basis or edge_source citation")
        else:
            _record("G6", "PASS", f"cost_arithmetic basis={cost_basis}")
    else:
        _record("G6", "FAIL", "cost_arithmetic must be present and must be a mapping")

    margin_ratio = ((cost or {}).get("margin_ratio"))
    if margin_ratio is not None and float(margin_ratio) >= 1.5:
        _record("G7", "PASS", f"margin_ratio={float(margin_ratio):.4f}")
    else:
        _record("G7", "FAIL", "cost_arithmetic.margin_ratio must be >= 1.5")

    free_range_params = 0
    for pdef in (spec.get("parameters") or {}).values():
        if isinstance(pdef, dict) and ("range" in pdef or ("min" in pdef and "max" in pdef)):
            free_range_params += 1
    if free_range_params <= 3:
        _record("G12", "PASS", f"free-range parameters={free_range_params}")
    else:
        _record("G12", "FAIL", f"free-range parameters={free_range_params}; max is 3")

    falsification_criteria = [str(item) for item in (spec.get("falsification_criteria") or [])]
    falsification_text = " ".join(falsification_criteria).lower()
    performance_only_terms = ["sharpe", "pnl", "drawdown", "hit rate", "hit_rate", "dsr", "oos"]
    mechanism_terms = [
        *[sensor.lower() for sensor in sensors],
        str((spec.get("trend_mechanism") or {}).get("family", "")).lower(),
        "regime", "spread", "lambda", "ofi", "vpin", "correlation", "half-life", "half_life",
        "inventory", "hawkes", "scheduled", "micro_price", "replenish",
    ]
    has_mechanism_anchor = any(term and term in falsification_text for term in mechanism_terms)
    performance_only = falsification_criteria and all(any(term in criterion.lower() for term in performance_only_terms) for criterion in falsification_criteria)
    if falsification_criteria and has_mechanism_anchor and not performance_only:
        _record("G10", "PASS", "falsification_criteria reference mechanism-linked terms")
    else:
        _record("G10", "FAIL", "falsification_criteria must reference mechanism-linked sensors, regime, or horizon terms")

    structural_invalidators = [str(item) for item in (context.get("structural_invalidators") or []) if str(item).strip()]
    regime_shift_invalidators = [str(item) for item in (context.get("regime_shift_invalidators") or []) if str(item).strip()]
    if structural_invalidators and regime_shift_invalidators:
        _record("G11", "PASS", f"structural_invalidators={len(structural_invalidators)}, regime_shift_invalidators={len(regime_shift_invalidators)}")
    else:
        _record("G11", "FAIL", "proposal context must include both structural_invalidators and regime_shift_invalidators")

    lookahead_terms = ["future", "next_bar", "next tick", "tomorrow", "lead(", "lead_", "shift(-", "t+1", "forward_return", "future_return"]
    if _contains_any(signal_text, lookahead_terms):
        _record("G13", "FAIL", "signal code contains look-ahead-shaped terms")
    else:
        _record("G13", "PASS", "no obvious look-ahead terms detected in signal code")

    out_of_scope_terms = ["level 2", "order book depth", "dark pool", "hidden liquidity", "colocation", "news", "sentiment", "options chain", "fundamental", "social media"]
    if _contains_any(analysis_text, out_of_scope_terms):
        _record("G14", "FAIL", "proposal references data beyond L1 NBBO + trades + reference data")
    else:
        _record("G14", "PASS", "no out-of-scope data dependencies detected")

    fill_model_assumption = str(context.get("fill_model_assumption") or "platform_default_router")
    fill_model_terms = ["fill probability", "queue position", "hidden queue", "latency arb", "colocation advantage", "guaranteed fill"]
    if _contains_any(analysis_text, fill_model_terms):
        _record("G15", "FAIL", "proposal references fill assumptions inconsistent with platform routers")
    elif fill_model_assumption not in {"platform_default_router", "BacktestOrderRouter", "PassiveLimitOrderRouter", "platform_default"}:
        _record("G15", "FAIL", f"unsupported fill_model_assumption={fill_model_assumption}")
    else:
        _record("G15", "PASS", f"fill_model_assumption={fill_model_assumption}")

    family = ((spec.get("trend_mechanism") or {}).get("family"))
    trend = spec.get("trend_mechanism") or {}
    if family is None:
        _record("G16", "PASS", "trend_mechanism omitted; local platform.yaml may opt out of strict enforcement")
    else:
        if family not in MECHANISM_FAMILY_CATALOG:
            _record("G16", "FAIL", f"unknown trend_mechanism.family={family}")
        else:
            tm_messages = [f"family={family}"]
            l1_signature_sensors = set(trend.get("l1_signature_sensors") or [])
            expected_half_life = trend.get("expected_half_life_seconds")
            failure_signature = trend.get("failure_signature") or []
            failures: list[str] = []

            if not l1_signature_sensors:
                failures.append("l1_signature_sensors is empty")
            elif not l1_signature_sensors.issubset(SENSOR_CATALOG):
                bad = sorted(sensor for sensor in l1_signature_sensors if sensor not in SENSOR_CATALOG)
                failures.append(f"unknown signature sensors: {bad}")

            required_primary = set(FAMILY_PRIMARY_FINGERPRINTS.get(family, []))
            if required_primary and l1_signature_sensors.isdisjoint(required_primary):
                failures.append(f"missing primary fingerprint sensor for {family}: need one of {sorted(required_primary)}")

            if expected_half_life is None:
                failures.append("expected_half_life_seconds missing")
            else:
                lo, hi = HALF_LIFE_ENVELOPES[family]
                half_life_value = int(expected_half_life)
                if not lo <= half_life_value <= hi:
                    failures.append(f"expected_half_life_seconds={half_life_value} outside [{lo}, {hi}]")
                elif horizon is not None:
                    ratio = float(horizon) / float(half_life_value)
                    if not 0.5 <= ratio <= 4.0:
                        failures.append(f"horizon/half_life ratio={ratio:.3f} outside [0.5, 4.0]")
                    else:
                        tm_messages.append(f"ratio={ratio:.3f}")

            if not failure_signature:
                failures.append("failure_signature must be non-empty")

            if family == "LIQUIDITY_STRESS":
                if re.search(r"\b(LONG|SHORT)\b", signal_text):
                    _record("G16.7", "FAIL", "LIQUIDITY_STRESS is exit-only; signal code still emits LONG/SHORT")
                else:
                    _record("G16.7", "PASS", "LIQUIDITY_STRESS signal does not emit LONG/SHORT tokens")

            if layer == "PORTFOLIO":
                consumes = trend.get("consumes") or []
                overall_cap = trend.get("max_share_of_gross")
                consume_families = []
                if not isinstance(consumes, list) or not consumes:
                    _record("G16.8", "FAIL", "PORTFOLIO trend_mechanism.consumes must be a non-empty list")
                elif overall_cap is None:
                    _record("G16.8", "FAIL", "PORTFOLIO trend_mechanism.max_share_of_gross is required")
                else:
                    bad_caps = []
                    for item in consumes:
                        item_family = item.get("family") if isinstance(item, dict) else None
                        item_cap = item.get("max_share_of_gross") if isinstance(item, dict) else None
                        if item_family not in MECHANISM_FAMILY_CATALOG or item_family == "PORTFOLIO_XSECT":
                            bad_caps.append(f"bad family={item_family}")
                            continue
                        if item_cap is None or float(item_cap) <= 0:
                            bad_caps.append(f"missing cap for family={item_family}")
                            continue
                        consume_families.append(item_family)
                    if bad_caps:
                        _record("G16.8", "FAIL", "; ".join(bad_caps))
                    else:
                        _record("G16.8", "PASS", f"consumes={consume_families}, max_share_of_gross={overall_cap}")

                depends_on_signals = spec.get("depends_on_signals") or []
                context_signal_families = context.get("depends_on_signal_families") or {}
                inferred_families = []
                unknown_families = []
                for signal_id in depends_on_signals:
                    signal_family = context_signal_families.get(signal_id) or _infer_signal_family(signal_id)
                    if signal_family is None:
                        unknown_families.append(signal_id)
                    else:
                        inferred_families.append(signal_family)
                if unknown_families:
                    _record("G16.9", "FAIL", f"could not infer families for depends_on_signals={unknown_families}")
                elif set(inferred_families).issubset(set(consume_families)):
                    _record("G16.9", "PASS", f"depends_on_signals families={sorted(set(inferred_families))}")
                else:
                    _record("G16.9", "FAIL", f"depends_on_signals families {sorted(set(inferred_families))} not subset of consumes {sorted(set(consume_families))}")
            else:
                _record("G16.8", "SKIP", "not a PORTFOLIO alpha")
                _record("G16.9", "SKIP", "not a PORTFOLIO alpha")

            if failures:
                _record("G16", "FAIL", "; ".join(failures))
            else:
                _record("G16", "PASS", ", ".join(tm_messages))

    return checks


def print_gate_audit(audit: dict) -> None:
    print("\nGate audit")
    print("-" * 90)
    for gate, result in audit.items():
        status = result.get("status") or ("PASS" if result.get("pass") else "FAIL")
        print(f"{gate:24s} {status:4s}  {result.get('message', '')}")
    print("-" * 90)


print("audit_gates(spec) and print_gate_audit(audit): ACTIVE")
```

---

## CELL 3 - Proposal and mutation-by-axis helpers

```python
def FAILED_GATES(audit: dict) -> list[str]:
    return [gate for gate, result in audit.items() if result.get("status") == "FAIL"]


def PROPOSAL_DECISION(spec: dict, audit: dict | None = None) -> tuple[str, list[str]]:
    audit = audit or audit_gates(spec)
    failed = FAILED_GATES(audit)
    if failed:
        return "DRAFT", failed
    return "EMIT", []


def WRITE_DRAFT_SPEC(spec: dict, audit: dict | None = None, *, reason: str | None = None) -> str:
    """Persist a failed proposal under ALPHA_DEV_DIR/_drafts with a FAILED_GATES header."""
    audit = audit or audit_gates(spec)
    failed = FAILED_GATES(audit)
    draft_dir = os.path.join(ALPHA_DEV_DIR, "_drafts")
    os.makedirs(draft_dir, exist_ok=True)
    alpha_id = spec.get("alpha_id", "draft")
    out_path = os.path.join(draft_dir, f"{alpha_id}.alpha.yaml")
    payload = yaml.dump(spec, default_flow_style=False, sort_keys=False)
    header = f"# FAILED_GATES: {failed}\n"
    if reason:
        header += f"# REASON: {reason}\n"
    with open(out_path, "w") as f:
        f.write(header)
        f.write(payload)
    return out_path


def FORMAT_GENERATION_OUTPUT_TEMPLATE() -> str:
    return """MODE: GENERATION\n\n## Reasoning\nActor: <named structural actor>\nMechanism: <actor-action-incentive-observable sentence>\nSignature: <shipped sensors only>\nHorizon: <seconds>\nRegime: <on_condition / off_condition / hysteresis>\nFalsification: <mechanism-tied criteria + invalidators>\n\n## Gate Audit\n[G1]..[G16]: <PASS | FAIL | SKIP with reason>\n\n## Decision\nEMIT | DRAFT | REFUSE\n\n## YAML\n<full schema-1.1 alpha yaml>"""


def FORMAT_MUTATION_OUTPUT_TEMPLATE() -> str:
    return """MODE: MUTATION  parent=<alpha_id>  version=<predecessor_version>\n\n## Reasoning\nTrigger: <forensics summary>\nAxis: <1 | 2 | 3 | 4 | 5>\nMutation story: <what changes and why>\n\n## Cost Arithmetic Recheck\n<updated hurdle / edge / margin ratio>\n\n## Gate Audit\n[G1]..[G16]: <PASS | FAIL | SKIP with reason>\n\n## Decision\nEMIT | DRAFT | REFUSE\n\n## YAML\n<full successor yaml>"""


def SELFTEST_PROMPT7() -> dict:
    """Exercise representative good/bad proposal audits for Prompt 7 heuristics."""
    good_spec = PROPOSE(
        template_alpha_id="pofi_kyle_drift_v1",
        new_alpha_id="prompt7_selfcheck_good",
        hypothesis=(
            "Informed parent-order executors keep leaning on same-sign OFI because residual impact remains "
            "observable in kyle_lambda_60s, micro_price, and stable spreads before the signature decays."
        ),
        falsification_criteria=[
            "kyle_lambda_60s percentile signal decouples from OFI for 4 consecutive weeks",
            "spread_z_30d remains above 2.0 long enough that the normal-regime gate stays structurally OFF",
        ],
        structural_actor="informed parent-order executors",
        mechanism_sentence=(
            "Informed parent-order executors keep leaning on same-sign OFI because residual impact remains "
            "observable in kyle_lambda_60s, micro_price, and stable spreads before the signature decays."
        ),
        structural_invalidators=["Kyle impact estimate stops co-moving with same-sign OFI for 4 consecutive weeks"],
        regime_shift_invalidators=["spread_z_30d remains above 2.0 for 30 trading days"],
        rationale="Reference-template inheritance with explicit actor, observable, and invalidator language.",
        cost_basis="template_inherited:pofi_kyle_drift_v1",
        fill_model_assumption="platform_default_router",
    )
    good_audit = audit_gates(good_spec)
    good_failed = FAILED_GATES(good_audit)
    if good_failed:
        raise AssertionError(f"Prompt 7 self-check good case failed gates: {good_failed}")

    bad_spec = PROPOSE(
        template_alpha_id="pofi_kyle_drift_v1",
        new_alpha_id="prompt7_selfcheck_bad",
        hypothesis="Traders make money.",
        falsification_criteria=["Sharpe below 1.0 for a month"],
        structural_actor="traders",
        mechanism_sentence="Traders trade.",
        structural_invalidators=[],
        regime_shift_invalidators=[],
        rationale="Uses future returns and unsupported fill assumptions.",
        fill_model_assumption="guaranteed_fill_router",
        signal_code=(
            "def evaluate(snapshot, regime, params):\n"
            "    future = snapshot.values.get(\"future_return\")\n"
            "    if future is None:\n"
            "        return None\n"
            "    return future\n"
        ),
    )
    bad_audit = audit_gates(bad_spec)
    bad_failed = set(FAILED_GATES(bad_audit))
    expected_bad = {"G2", "G3", "G10", "G11", "G13", "G15"}
    missing = sorted(expected_bad.difference(bad_failed))
    if missing:
        raise AssertionError(f"Prompt 7 self-check bad case missed expected failures: {missing}")

    summary = {
        "good_case": "PASS",
        "bad_case_expected_failures": sorted(expected_bad),
        "bad_case_observed_failures": sorted(bad_failed),
    }
    print("SELFTEST_PROMPT7: PASS", summary)
    return summary


def PROPOSE(
    *,
    template_alpha_id: str,
    new_alpha_id: str,
    hypothesis: str,
    falsification_criteria: list[str],
    description: str | None = None,
    structural_actor: str | None = None,
    mechanism_sentence: str | None = None,
    structural_invalidators: list[str] | None = None,
    regime_shift_invalidators: list[str] | None = None,
    rationale: str | None = None,
    cost_basis: str | None = None,
    fill_model_assumption: str = "platform_default_router",
    parameter_overrides: dict | None = None,
    regime_gate: dict | None = None,
    cost_arithmetic: dict | None = None,
    trend_mechanism: dict | None = None,
    signal_code: str | None = None,
) -> dict:
    """Clone a shipped template alpha and apply bounded edits.

    This helper intentionally stays narrow. It avoids synthesizing a spec from
    scratch when a current-main reference alpha already exists for the same
    mechanism family.
    """
    spec = clone_reference_alpha(template_alpha_id, new_alpha_id=new_alpha_id)
    spec["hypothesis"] = hypothesis
    spec["falsification_criteria"] = list(falsification_criteria)
    if description is not None:
        spec["description"] = description
    if parameter_overrides:
        for name, patch in parameter_overrides.items():
            spec.setdefault("parameters", {}).setdefault(name, {})
            spec["parameters"][name].update(patch)
    if regime_gate is not None:
        spec["regime_gate"] = regime_gate
    if cost_arithmetic is not None:
        spec["cost_arithmetic"] = cost_arithmetic
    if trend_mechanism is not None:
        spec["trend_mechanism"] = trend_mechanism
    if signal_code is not None:
        spec["signal"] = signal_code
    family = ((spec.get("trend_mechanism") or {}).get("family"))
    inferred_actor = structural_actor
    if not inferred_actor and family in MECHANISM_FAMILY_CATALOG:
        inferred_actor = MECHANISM_FAMILY_CATALOG[family].get("structural_actor")
    REGISTER_PROPOSAL_CONTEXT(
        new_alpha_id,
        structural_actor=inferred_actor,
        mechanism_sentence=mechanism_sentence or hypothesis,
        structural_invalidators=list(structural_invalidators or []),
        regime_shift_invalidators=list(regime_shift_invalidators or []),
        rationale=rationale,
        cost_basis=cost_basis or ("template_inherited:" + template_alpha_id if cost_arithmetic is None else None),
        fill_model_assumption=fill_model_assumption,
    )
    return spec


def HYPOTHESIS_FROM_SPEC(spec: dict) -> dict:
    """Project a proposal spec into Prompt 4's hypothesis dict shape."""
    mechanism = spec.get("hypothesis", "")
    trend = spec.get("trend_mechanism") or {}
    return {
        "statement": mechanism,
        "mechanism": mechanism,
        "mechanism_family": trend.get("family", ""),
        "horizon_seconds": spec.get("horizon_seconds"),
        "falsification_criteria": list(spec.get("falsification_criteria") or []),
    }


def MUTATE_BY_AXIS(parent_spec: dict, axis: int, seed: int = 0, **kwargs) -> dict:
    """Map the embedded five-axis mutation protocol onto Prompt 6 operators."""
    if axis == 1:
        return MUTATE(parent_spec, "refine_regime", seed=seed, **kwargs)
    if axis == 2:
        return MUTATE(parent_spec, "substitute_sensor", seed=seed, **kwargs)
    if axis == 3:
        return MUTATE(parent_spec, "adjust_horizon", seed=seed, **kwargs)
    if axis == 4:
        return MUTATE(parent_spec, "refine_universe", seed=seed, **kwargs)
    if axis == 5:
        child = op_promote_to_portfolio(parent_spec, random.Random(seed), **kwargs)
        if child is None:
            raise ValueError(
                "Axis 5 promotion requires a SIGNAL parent with an inferable mechanism family."
            )
        if not validate_alpha(child):
            raise ValueError(
                f"Promoted PORTFOLIO child '{child['alpha_id']}' failed AlphaLoader validation."
            )
        parent_family = _infer_parent_family(parent_spec)
        ADOPTION_DEPENDENCY_BUNDLES[child["alpha_id"]] = {
            parent_spec["alpha_id"]: copy.deepcopy(parent_spec),
        }
        REGISTER_PROPOSAL_CONTEXT(
            child["alpha_id"],
            structural_actor=MECHANISM_FAMILY_CATALOG["PORTFOLIO_XSECT"].get("structural_actor"),
            mechanism_sentence=child.get("hypothesis"),
            depends_on_signal_families={parent_spec["alpha_id"]: parent_family} if parent_family else None,
            cost_basis="template_inherited:pofi_xsect_v1",
        )
        ADOPT(child, source="MUTATE:promote_portfolio")
        return child
    raise ValueError("axis must be one of 1, 2, 3, 4, 5")


print("PROPOSE(...), REGISTER_PROPOSAL_CONTEXT(...), HYPOTHESIS_FROM_SPEC(spec), MUTATE_BY_AXIS(...), PROPOSAL_DECISION(spec), WRITE_DRAFT_SPEC(spec, audit), and SELFTEST_PROMPT7() available")
```

---

## CELL 4 - Anti-pattern guardrails

```python
FORBIDDEN_PATTERNS = {
    "ta_crossover": ["moving average crossover", "ema crossover", "rsi", "macd"],
    "parameter_sweep": ["grid search", "parameter sweep", "sweep every", "optimize thresholds blindly"],
    "out_of_scope_data": ["level 2", "order book depth", "dark pool", "hidden liquidity", "colocation"],
    "model_slop": ["neural network", "deep learning", "xgboost everything", "find patterns automatically"],
}


def pre_propose_audit(request_text: str) -> list[str]:
    """Return refusal reasons for requests that violate the reasoning protocol."""
    lowered = request_text.lower()
    hits: list[str] = []
    for label, patterns in FORBIDDEN_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            hits.append(label)
    return hits


def assert_request_clean(request_text: str) -> None:
    hits = pre_propose_audit(request_text)
    if hits:
        raise ValueError(
            "Prompt 7 refusal: request matches forbidden pattern(s): "
            + ", ".join(hits)
        )


print("pre_propose_audit(text) and assert_request_clean(text): ACTIVE")
print("Hypothesis Reasoning Module: ACTIVE")
```

---

## EMBEDDED REASONING CONTRACT

### Mode Detection

- If the operator names an existing `alpha_id` and asks to improve, fix, rescue, or mutate it, treat the request as `MODE: MUTATION`.
- If the operator asks for a new alpha, new mechanism, or new hypothesis with no parent alpha, treat the request as `MODE: GENERATION`.
- If the request is ambiguous, ask one precise clarifying question and stop.

### Generation Protocol

1. Name the structural actor.
2. State the mechanism in actor-action-incentive-observable form.
3. Identify the L1 signature using shipped sensors only.
4. Assign a horizon long enough to clear costs.
5. Compute cost arithmetic and require `margin_ratio >= 1.5`.
6. Specify regime `on_condition`, `off_condition`, and hysteresis.
7. Write falsification criteria tied to the mechanism and name structural and regime invalidators.

### Hard Gates

- `G1`: classify the layer.
- `G2`: name a specific structural actor.
- `G3`: express a valid mechanism sentence.
- `G4`: use only shipped sensors unless a new SENSOR proposal exists first.
- `G5`: keep SIGNAL horizon at or above 30 seconds.
- `G6`: fully specify cost arithmetic and its basis.
- `G7`: require `margin_ratio >= 1.5`.
- `G8`: require both regime gate conditions.
- `G9`: require meaningful hysteresis separation.
- `G10`: keep falsification criteria mechanism-tied.
- `G11`: name structural and regime invalidators.
- `G12`: limit free search ranges to three parameters.
- `G13`: forbid look-ahead.
- `G14`: stay within L1 NBBO + trades + reference data.
- `G15`: keep fills consistent with platform routers.
- `G16`: if `trend_mechanism` exists, enforce known family, fingerprint, half-life envelope, ratio, and failure-signature rules.

### Decision Contract

- `EMIT`: all required gates pass and the spec is ready for validation/backtest.
- `DRAFT`: the idea is plausible but failed proposal gates that need rewrite rather than outright refusal.
- `REFUSE`: the request violates scope, needs non-L1 data, or fails hard economic validity.

### Mutation Contract

- Legitimate axes are regime refinement, sensor substitution, horizon adjustment, universe refinement, and layer promotion.
- Forbidden moves include parameter sweeps without a mechanism story, easier falsification criteria, looser regime gates just to trade more, and evading trend-family constraints by renaming the family.
- Every mutation must preserve deterministic lineage and should be treated as a new emitted child rather than an in-place overwrite.

## HYPOTHESIS REASONING STATUS

```
Hypothesis Reasoning Module: ACTIVE
Embedded protocol:    mode detection, generation steps, hard gates, mutation axes
Mechanical helpers:   PROPOSE(), MUTATE_BY_AXIS(), audit_gates()
Primary validator:    validate_alpha(spec)
Primary development:  clone_reference_alpha() -> bounded edits -> audit -> HYPOTHESIS_FROM_SPEC() -> backtest
```