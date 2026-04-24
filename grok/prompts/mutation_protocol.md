<!--
  File:     grok/prompts/mutation_protocol.md
  Purpose:  Disciplined alpha-mutation protocol for Grok REPL.
            Extracted from grok/prompts/hypothesis_reasoning.md §5 and
            §11; augmented with parity-preservation rules and a
            pre-emit safety checklist.
  Consumer: Grok (LLM) when MODE = MUTATION (per §2 of
            hypothesis_reasoning.md).
  Status:   Normative.  Parameter sweeps without mechanism hypotheses
            are how overfitting enters the platform — refuse them.
-->

# Mutation Protocol — feelies / Grok REPL

> Mutation applies when an existing alpha shows decay, crowding, or
> regime-dependent failure. The temptation is to tweak parameters.
> **Resist.** Parameter sweeps without mechanism hypotheses are how
> overfitting enters the platform.

---

## 1. When to Mutate

Trigger conditions (any one is sufficient):

- **Realized IC decay**: live IC < 50 % of in-sample for ≥ 30 trading
  days.
- **Per-regime IC heterogeneity**: forensics show IC strong in a
  measurable sub-regime, weak outside.
- **Cost arithmetic drift**: realized round-trip cost > 1.2 × the
  declared `cost_arithmetic.round_trip_cost_bps`.
- **Half-life drift**: post-trade attribution shows realized half-life
  outside the alpha's `trend_mechanism.expected_half_life_seconds`
  envelope (Phase-3.1 G16 rule 2).
- **Mechanism crowding**: `mechanism_breakdown` on PORTFOLIO intents
  exceeds the alpha's per-family `max_share_of_gross` cap on
  > 10 consecutive boundaries.
- **Structural-break alarm**: `structural_break_score > 0.95` for
  > 7 consecutive sessions on a fingerprint sensor.

If none of the above is supplied by the operator, request forensics
(do not guess).

---

## 2. The Five Legitimate Axes

Every mutation operates on **exactly one** of these axes. State which
axis you are using before producing the mutated YAML.

### Axis 1 — Regime refinement

The hypothesis works, but only in a sub-regime of its current gate.
Trigger: forensics show IC strong in a subset, weak outside.

Action: tighten the `regime_gate.on_condition` to isolate the working
sub-regime. Re-run cost arithmetic — tighter regime usually means fewer
trades, higher per-trade edge, same `margin_ratio`.

### Axis 2 — Sensor substitution

Replace a sensor with a stronger proxy for the same latent variable.
Trigger: sensor shows lower signal-to-noise than an alternative from
the catalog.

Action: substitute in `depends_on_sensors`. If the substitution uses a
sensor not yet in `grok/prompts/sensor_catalog.md`, write the SENSOR
hypothesis first.

**Forbidden**: substituting a sensor that measures a *different* latent
variable. That is a new hypothesis, not a mutation.

### Axis 3 — Horizon adjustment

The mechanism expresses at a different horizon than originally chosen.
Trigger: IC profile by horizon peaks elsewhere than the current
`horizon_seconds`.

Action: update `horizon_seconds`. Re-run Step 5 cost arithmetic
(see `hypothesis_reasoning.md`) — shorter horizons have lower expected
edge and must still clear the hurdle. The new
`horizon_seconds / expected_half_life_seconds` ratio MUST stay in
`[0.5, 4.0]` (G16 rule 3); if not, the mutation actually requires a
matching `trend_mechanism.expected_half_life_seconds` adjustment, which
demands a new mechanism story (Axis 5).

### Axis 4 — Universe refinement

The mechanism applies differently across the universe. Trigger: IC
heterogeneous across market cap, sector, liquidity tier, or spread
regime.

Action: tighten `symbols` (or PORTFOLIO `universe`) to the sub-universe
where the structural actor is dominant. Document the **selection
criterion**, not just the list — a static list without criterion is a
look-ahead-shaped mutation.

### Axis 5 — Layer promotion

A SIGNAL with decaying single-name IC may still work as a PORTFOLIO
cross-sectional rank. Trigger: single-name IC below hurdle but
cross-sectional `IC × √N` still delivers IR > 0.5.

Action: write a **new** PORTFOLIO hypothesis consuming the SIGNAL via
`depends_on_signals`. The original SIGNAL is **not deleted** — it
becomes a dependency.

---

## 3. Forbidden Mutations

Refuse to emit any of the following. Each is an overfitting vector
masquerading as iteration:

- Parameter sweeps without a per-parameter mechanism hypothesis.
- Adding features without specifying which latent variable they
  measure.
- Combining two decaying signals "because they might help each other"
  (without a cross-sectional construction mechanism — that would be
  Axis 5).
- Changing `falsification_criteria` to be **easier** to satisfy.
- Loosening the `regime_gate` to trade more.
- Reducing `cost_arithmetic.hurdle_bps` (or `margin_ratio`) without a
  corresponding documented change in cost assumptions and a fresh
  citation.
- Bumping `cost_arithmetic.edge_estimate_bps` without a fresh prior or
  reference.
- Renaming a `trend_mechanism.family` to evade G16 rule 2 (half-life
  envelope) or rule 3 (horizon ratio).

When refusing, name the specific gate or rule the mutation would
violate.

---

## 4. Parity-Preservation Rules (Inv-5)

Mutation produces a **new alpha file** at a new version
(`<alpha_id>_v<N+1>.alpha.yaml`). Mutation **never** edits an existing
alpha file in-place — replay determinism (Inv-5) requires the
predecessor's parity hash to remain reproducible from its on-disk YAML
forever.

Concretely:

1. **Predecessor preserved.** The old YAML is moved to
   `alphas/_deprecated/<alpha_id>_v<predecessor_version>.yaml` (not
   deleted). Any historical replay must continue to load it byte-for-
   byte.
2. **Successor in a fresh directory.**
   `alphas/<new_alpha_id>/<new_alpha_id>.alpha.yaml`. The
   `alpha_id` either bumps the trailing `_vN` index (mutation within
   the same hypothesis lineage) or is a wholly new id (Axis 5
   promotion).
3. **Version bump rules.**
   - Axis 1, 2, 4 within the same family: minor bump (`1.0.0` →
     `1.1.0`).
   - Axis 3 (horizon change) or Axis 5 (layer promotion): major bump
     (`1.0.0` → `2.0.0`) AND new `alpha_id` (mechanism story or layer
     contract has changed).
4. **Decision-basis hashes diverge.** Expect `decision_basis_hash`
   (the per-boundary hash on `Signal` and `SizedPositionIntent`) to
   change after mutation; the per-level parity hashes
   (`tests/determinism/test_signal_replay.py`,
   `tests/determinism/test_sized_intent_replay.py`, ...) are baselined per `alpha_id` so
   they continue to lock the *predecessor* — the mutation gets its own
   baseline once it lands.

---

## 5. Pre-Emit Safety Checklist

Before writing the mutated YAML, walk this list. Refuse on any **No**.

```
[M1] One axis (1, 2, 3, 4, or 5) is named in the Reasoning section.
[M2] The trigger condition above (§1) is supplied with forensics.
[M3] No forbidden mutation (§3) is in play.
[M4] Predecessor file path is preserved; successor path is fresh.
[M5] schema_version / layer of the successor matches the predecessor
     (Axis 5 excepted — that promotes layer).
[M6] If trend_mechanism is declared, family is unchanged (Axis 1–4)
     OR the mutation explicitly justifies a family change in Axis 5.
[M7] If horizon changed, horizon / expected_half_life ∈ [0.5, 4.0]
     (G16 rule 3) — re-verify.
[M8] cost_arithmetic re-computed for the new (regime, universe, horizon)
     and margin_ratio still ≥ 1.5 (Inv-12).
[M9] All hard gates G1–G16 from hypothesis_reasoning.md §6 still pass.
[M10] Falsification criteria are still mechanism-tied (not P&L-tied)
      and are NOT easier to satisfy than the predecessor's.
```

If any of M1–M10 fails, write to `alphas/_drafts/` with a
`# FAILED_MUTATION_GATES: [...]` header instead of the live tree.

---

## 6. REPL Output Contract for Mutation

```
MODE: MUTATION  parent=<alpha_id>  version=<predecessor_version>

## Reasoning
Trigger: <trigger condition + forensics summary>
Axis: <1 | 2 | 3 | 4 | 5>
<axis-specific narrative — what changes and why>

## Cost Arithmetic Recheck
<recomputed half_spread / impact / fee / hurdle / margin_ratio>

## Gate Audit
[G1]..[G16]: <✓ or ✗ with reason>
[M1]..[M10]: <✓ or ✗ with reason>

## Decision
EMIT:
  alphas/<new_alpha_id>/<new_alpha_id>.alpha.yaml
  alphas/_deprecated/<old_alpha_id>_<predecessor_version>.yaml  (move predecessor)

## YAML
<full successor YAML inline for operator review>
```

Do not deviate from this structure. The operator's tooling parses it.

End of mutation protocol.
