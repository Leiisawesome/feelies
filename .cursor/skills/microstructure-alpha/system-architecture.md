# System Architecture — Layer-2 Reference

> **Authoritative pipeline:** [system-architect skill](../system-architect/SKILL.md)
> (layer topology, micro-states M0–M10, typed events, `ExecutionBackend`).
> This file records **microstructure-alpha-specific** context only.

## Where Layer 2 sits

```
HorizonFeatureSnapshot + RegimeState
  → SIGNAL_GATE: regime_gate (AST DSL) → HorizonSignal.evaluate()
  → Signal (direction, strength, edge_estimate_bps,
             trend_mechanism, expected_half_life_seconds)
  → M4 drain → PositionSizer → IntentTranslator → M5 risk
```

PORTFOLIO construction is downstream — see [composition-layer skill](../composition-layer/SKILL.md).

D.2 retired the per-tick `FeatureVector` path; canonical Layer-2 input is
`HorizonFeatureSnapshot` only (see platform-invariants glossary).

---

## Mechanism-aware sensors (G16 fingerprint map)

Layer-1 sensors that anchor SIGNAL alpha `depends_on_sensors` /
`l1_signature_sensors`. Full catalog (registered vs dormant): [feature-engine skill](../feature-engine/SKILL.md).

| Family | Primary fingerprints (rule 5) | Other family-related |
|--------|------------------------------|----------------------|
| KYLE_INFO | `kyle_lambda_60s`, `micro_price` | `ofi_ewma` |
| INVENTORY | `quote_replenish_asymmetry` | `inventory_pressure` |
| HAWKES_SELF_EXCITE | `hawkes_intensity` | `trade_through_rate` |
| LIQUIDITY_STRESS | `vpin_50bucket`, `realized_vol_30s` | `liquidity_stress_score`, `spread_z_30d`, `quote_hazard_rate`, `quote_flicker_rate` |
| SCHEDULED_FLOW | `scheduled_flow_window` | — |

---

## Horizon snapshot quality (Layer-2 gate)

From [feature-engine skill](../feature-engine/SKILL.md); common authoring mistakes:

- `warm` / `stale` are **per-`feature_id` dicts** — never `if snapshot.warm:`
- `values` contains warm features only; cold keys are absent (use `.get()`)
- Entry suppressed when any `required_warm_feature_ids` is not warm or is stale; exits permitted when stale

---

## Signal contract summary

```python
class HorizonSignal(Protocol):
    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState,
        params: Mapping[str, Any],
    ) -> Signal | None: ...
```

- Pure function — no sizing, routing, or risk (Inv-5 parity hash scope)
- Single `horizon_seconds` per alpha (G3/G16)
- `cost_arithmetic:` margin_ratio ≥ 1.5, reconciles ±5% (G12)
- `trend_mechanism:` required under default strict mode (G16)
- `hazard_exit.enabled: true` → `HazardExitController` (see [regime-detection](../regime-detection/SKILL.md) + [risk-engine](../risk-engine/SKILL.md))

---

## Research vs production parity

Shared tick pipeline; mode swap is only `ExecutionBackend`:

| Mode | Clock | Orders |
|------|-------|--------|
| RESEARCH | `SimulatedClock` | None (`run_research`) |
| BACKTEST | `SimulatedClock` | Simulated router |
| PAPER | `WallClock` | IB Gateway |

Before LIVE: all eleven parity hashes (L1–L6) + F-2 promotion gates —
see [testing-validation](../testing-validation/SKILL.md) and
[alpha-lifecycle](../alpha-lifecycle/SKILL.md).

---

## Further reading

| Topic | Skill |
|-------|-------|
| Full pipeline diagram | system-architect |
| Sensor + aggregator detail | feature-engine |
| Regime gate DSL bindings | regime-detection |
| Fill / execution backends | backtest-engine, live-execution |
| Research methodology | [research-protocol.md](research-protocol.md) |
