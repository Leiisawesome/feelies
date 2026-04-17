# Prompt 6 — EVOLUTION MODULE (autonomous mutation, exploration, evolution)

> Paste this *after* Prompt 5 (Export & Lifecycle).
>
> This module is what makes the Grok REPL a *system* rather than a manual research notebook.
> It closes the autonomy loop required by design goal 3:
>
>     hypothesis → alpha → backtest → mutation → next-generation alpha
>
> Every mutation is **typed** (named operator), **provenance-tagged** (parent_id + mutation_type),
> **MHT-corrected** (Holm over the family), and **promotion-gated** (TEST verdict + selfcheck).
>
> The module relies on:
>   • assemble_alpha / FEATURE_LIBRARY / MECHANISM_CATALOG / formalize_hypothesis  (Prompt 3)
>   • TEST / SELFCHECK / falsification_battery / holm_correction / compute_ic     (Prompt 4)
>   • EXPORT / _registry_upsert                                                    (Prompt 5)
>
> No new dependency. No invented features. Only operators that compose existing repo primitives.

---

## CELL 1 — Mutation operators (typed, deterministic, schema-preserving)

```python
import copy, random, hashlib, datetime
from typing import Callable

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
#   4. Preserve the .alpha.yaml schema (assemble_alpha output shape).
#   5. Return None if the mutation is structurally impossible (e.g. parameter
#      perturbation on an alpha with no parameters). EXPLORE skips Nones.
#
# Operators MUST NOT:
#   - Touch SESSION, registry, filesystem.
#   - Read wall-clock state. (Determinism: same parent + seed → same child.)
#   - Mutate features that don't exist in FEATURE_LIBRARY (use known-good only).
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
    lo, hi = (spec.get("range") or [None, None])
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


# ---- OP 2: threshold flip / sign reversal -------------------------
def op_flip_sign(parent_spec: dict, rng: random.Random) -> dict | None:
    """
    Reverse the sign convention inside the signal: replace `LONG` with
    `SHORT` and vice-versa. Tests the symmetric hypothesis (the mechanism
    points the opposite way). Only mutates spec["signal"] textually.
    """
    sig = parent_spec.get("signal", "")
    if "LONG" not in sig or "SHORT" not in sig:
        return None
    seed = rng.randrange(1 << 30)
    child = _new_child(parent_spec, "flip_sign", seed)
    sentinel = "____TMP_DIR_SWAP____"
    child["signal"] = (sig.replace("LONG", sentinel)
                          .replace("SHORT", "LONG")
                          .replace(sentinel, "SHORT"))
    child["hypothesis"] = "[SIGN-FLIPPED] " + parent_spec.get("hypothesis", "")
    return child


# ---- OP 3: feature swap (within-family) ---------------------------
def op_swap_feature(parent_spec: dict, rng: random.Random,
                    candidates: list[str] | None = None) -> dict | None:
    """
    Replace one feature in the spec with a sibling feature from
    FEATURE_LIBRARY that has the same input dependency profile. The signal
    code is left untouched — if it references the removed feature by name
    the AlphaLoader will reject it, and EXPLORE will mark this child invalid.
    The point is to falsify the hypothesis "this specific feature carries
    the edge"; if the sibling also works, the edge is broader than claimed.
    """
    feats = parent_spec.get("features") or []
    if not feats:
        return None
    candidates = candidates or list(FEATURE_LIBRARY.keys())  # Prompt 3 global
    seed = rng.randrange(1 << 30)
    idx = rng.randrange(len(feats))
    old_id = feats[idx].get("feature_id")
    pool = [c for c in candidates if c != old_id]
    if not pool:
        return None
    new_id = rng.choice(pool)

    child = _new_child(parent_spec, "swap_feature", seed,
                       {"index": idx, "old": old_id, "new": new_id})
    child["features"][idx] = feature_entry(new_id)   # Prompt 3 helper
    return child


# ---- OP 4: holding-window scaling ---------------------------------
def op_scale_holding(parent_spec: dict, rng: random.Random,
                     factor_choices: tuple = (0.5, 2.0)) -> dict | None:
    """
    Scale the alpha's holding-time / cooldown parameter (any param whose
    name contains 'hold' or 'cooldown' or 'window'). Rotates through factor_choices.
    Tests the persistence-window dimension of the edge — if doubling the
    horizon kills it, the mechanism decays fast (information-driven).
    """
    params = parent_spec.get("parameters") or {}
    candidates = [k for k in params
                  if any(t in k.lower() for t in ("hold", "cooldown", "window"))
                  and isinstance(params[k].get("default"), (int, float))]
    if not candidates:
        return None
    seed = rng.randrange(1 << 30)
    name = rng.choice(candidates)
    factor = rng.choice(factor_choices)
    child = _new_child(parent_spec, "scale_holding", seed,
                       {"parameter": name, "factor": factor})
    spec = child["parameters"][name]
    new_val = spec["default"] * factor
    lo, hi = (spec.get("range") or [None, None])
    if lo is not None: new_val = max(new_val, lo)
    if hi is not None: new_val = min(new_val, hi)
    if spec.get("type") == "int":
        new_val = int(round(new_val))
    spec["default"] = new_val
    return child


# ---- OP 5: regime-condition the signal ----------------------------
def op_regime_filter(parent_spec: dict, rng: random.Random,
                     regimes: tuple = ("trending", "compression_clustering",
                                       "vol_breakout")) -> dict | None:
    """
    Wrap the signal's evaluate() body in a regime gate that suppresses
    entries outside a chosen regime. Requires the regime engine to be
    active during backtest (TEST passes regime_engine through).
    Tests the hypothesis that the edge is regime-conditional, which is the
    most common reason a backtest looks great but live PnL collapses.
    """
    sig = parent_spec.get("signal", "")
    if "def evaluate" not in sig:
        return None
    seed = rng.randrange(1 << 30)
    regime = rng.choice(regimes)
    child = _new_child(parent_spec, "regime_filter", seed, {"regime": regime})

    # Inject a lightweight gate at the top of evaluate(). The features dict
    # is expected to expose 'regime' (provided by feelies.regime adapter when
    # regime_engine is wired into the build_platform() pipeline).
    gate = (
        f"    # regime gate injected by op_regime_filter\n"
        f"    if features.get('regime') != {regime!r}:\n"
        f"        return None\n"
    )
    lines = sig.split("\n")
    out = []
    injected = False
    for ln in lines:
        out.append(ln)
        if not injected and ln.strip().startswith("def evaluate"):
            out.append(gate.rstrip())
            injected = True
    child["signal"] = "\n".join(out)
    return child


# Operator registry — EXPLORE / EVOLVE pull from here.
# Order is irrelevant; EXPLORE samples uniformly with the seeded RNG.
MUTATION_OPERATORS: dict[str, Callable] = {
    "perturb_param":   op_perturb_parameter,
    "flip_sign":       op_flip_sign,
    "swap_feature":    op_swap_feature,
    "scale_holding":   op_scale_holding,
    "regime_filter":   op_regime_filter,
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
# parents and produces one child whose feature set is the union of both
# parents' features and whose signal logic is one parent's. This tests
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
    Splice features from parent_b into parent_a; keep parent_a's signal
    code (or parent_b's if signal_from='b').

    Both parents must validate. The child's feature list is the union by
    feature_id (parent_a wins on ID collision so its computation_module
    is preserved). The signal text is taken verbatim from the chosen parent;
    if the chosen parent's signal references a feature that the union does
    NOT contain, AlphaLoader will reject the child and EXPLORE will skip it.
    """
    assert signal_from in ("a", "b"), "signal_from must be 'a' or 'b'"
    if parent_a.get("alpha_id") == parent_b.get("alpha_id"):
        return None   # splicing with self is a no-op

    a_feats = parent_a.get("features") or []
    b_feats = parent_b.get("features") or []
    if not a_feats or not b_feats:
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

    # Union features by feature_id; base wins on collision.
    have = {f.get("feature_id") for f in child["features"]}
    added = []
    for f in (parent_a["features"] if signal_from == "b" else parent_b["features"]):
        fid = f.get("feature_id")
        if fid and fid not in have:
            child["features"].append(copy.deepcopy(f))
            have.add(fid)
            added.append(fid)

    # Union parameters by name; base wins on collision (same rule as features).
    other_params = other.get("parameters") or {}
    for pname, pdef in other_params.items():
        child.setdefault("parameters", {}).setdefault(pname, copy.deepcopy(pdef))

    child["lineage"] = {
        # parent_id is the "primary" parent for genealogy; co_parent_id
        # captures the other side. LINEAGE prints both.
        "parent_id":      base["alpha_id"],
        "co_parent_id":   other["alpha_id"],
        "parent_version": base.get("version", "1.0.0"),
        "mutation_type":  op_name,
        "operator_kwargs": {
            "signal_from":    signal_from,
            "spliced_features": added,
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
            f"Splice not applicable: same alpha_id, missing features, "
            f"or invalid signal_from='{signal_from}'."
        )
    if not validate_alpha(child):
        raise ValueError(
            f"Spliced child '{child['alpha_id']}' failed AlphaLoader validation. "
            f"Most common cause: signal_from='{signal_from}' references a feature "
            f"not present in the union. Try signal_from='{'b' if signal_from=='a' else 'a'}' "
            f"or adjust the unioned features manually."
        )
    print(f"RECOMBINE: {parent_a_spec['alpha_id']}  x  {parent_b_spec['alpha_id']}  "
          f"--[{child['lineage']['mutation_type']}]-->  {child['alpha_id']}")
    return child


print("Recombination operator registered: op_splice (binary, via RECOMBINE)")
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
print("Evolution module: ACTIVE")
```

---

## EVOLUTION MODULE STATUS

```
Unary operators:       perturb_param, flip_sign, swap_feature, scale_holding, regime_filter
Binary operator:       op_splice (via RECOMBINE — feature/parameter union, signal from chosen parent)
Determinism:           SELFCHECK_MUTATION asserts seeded reproducibility (Inv-5 in mutation layer)
MHT correction:        Holm-Bonferroni over each EXPLORE family (alpha=0.05 default)
DSR n_trials:          EXPLORE passes len(children) → falsification_battery deflates by trial count
Provenance:            child.lineage → report.lineage → registry.parent_id + co_parent_id + mutation_type
Promotion:             EVOLVE picks champions in research; user calls EXPORT to deploy
Post-promotion:        AUDIT(signal_id) re-runs CPCV+IC on a fresh window, stamps audit_status
                       (HEALTHY / DEGRADED / DEAD) into the registry
Lineage view:          LINEAGE(signal_id) prints the chain root→leaf with IC stability summary
Persistence:           every EXPLORE → family_summary.json; every EVOLVE → evolution_run.json

Ready: EXPLORE(parent_spec, n=8)                     — Holm-corrected family of mutated siblings
       EVOLVE(seed_spec, n_generations=3)            — full hypothesis → mutation → selection loop
       RECOMBINE(parent_a, parent_b)                 — cross-mechanism splice
       AUDIT(signal_id)                              — post-promotion edge-decay monitor
       LINEAGE(signal_id)                            — ancestry walk with IC stability classification
```
