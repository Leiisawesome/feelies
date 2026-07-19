# Migration: schema 1.0 / LEGACY_SIGNAL → schema 1.1 SIGNAL or PORTFOLIO

Workstream D.1 removed `schema_version: "1.0"`. Workstream D.2 retired
`layer: LEGACY_SIGNAL` and the per-tick execution path (`FeatureVector`,
`features/legacy_shim.py`, `CompositeSignalEngine`). The loader
hard-rejects both; there is no deprecation warning or shim.

**Canonical field reference:** [`alphas/SCHEMA.md`](../../alphas/SCHEMA.md).  
**Authoring depth:** [`.cursor/skills/microstructure-alpha/SKILL.md`](../../.cursor/skills/microstructure-alpha/SKILL.md).  
**PORTFOLIO alphas:** [`.cursor/skills/composition-layer/SKILL.md`](../../.cursor/skills/composition-layer/SKILL.md).  
**Starter YAML:** [`alphas/_template/template_signal.alpha.yaml`](../../alphas/_template/template_signal.alpha.yaml).

## What the loader accepts today

| Field | Accepted values |
|---|---|
| `schema_version` | `"1.1"` only (mandatory) |
| `layer` | `SIGNAL` or `PORTFOLIO` |

Anything else (missing version, `"1.0"`, `LEGACY_SIGNAL`, unknown layer)
raises `AlphaLoadError` with a pointer to this document.

## SIGNAL migration checklist

1. Set `schema_version: "1.1"` and `layer: SIGNAL`.
2. Replace per-tick feature YAML with `depends_on_sensors:` (sensor id +
   version + `min_history_seconds`) and a horizon-anchored `signal:`
   block that reads a `HorizonFeatureSnapshot`.
3. Declare `horizon_seconds` from the canonical set
   `{30, 120, 300, 900, 1800}`.
4. Add a required `regime_gate:` block (`on_condition` / `off_condition`,
   AST-safe DSL).
5. Add a required `cost_arithmetic:` block with `margin_ratio ≥ 1.5`
   (Inv-12; metadata only — does not size at runtime).
6. Add a G16 `trend_mechanism:` block (closed enum +
   `expected_half_life_seconds` envelope).
7. Delete any reliance on per-tick `FeatureVector` / `evaluate(features,
   params)` LEGACY_SIGNAL surface — Layer-2 input is
   `HorizonFeatureSnapshot` only.

## PORTFOLIO migration checklist

1. Set `schema_version: "1.1"` and `layer: PORTFOLIO`.
2. Declare `universe`, `depends_on_signals`, `horizon_seconds`, and
   `cost_arithmetic`.
3. Follow composition-layer skill for neutralization, mechanism caps, and
   turnover constraints.

## Verification

```bash
# Loader reject path (legacy layer / schema)
uv run pytest tests/alpha/test_schema_1_1_loading.py -q

# Full schema / gate surface
uv run pytest tests/alpha/test_layer_validator_g2_g13.py -q
```

If an alpha still fails to load, the error message names the missing or
retired field — fix that field, then re-run the tests above.
