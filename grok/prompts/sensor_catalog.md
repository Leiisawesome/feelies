<!--
  File:     grok/prompts/sensor_catalog.md
  Purpose:  Authoritative Layer-1 sensor vocabulary for Grok REPL.
            Sourced from src/feelies/sensors/impl/*.py (canonical) and
            design_docs/three_layer_architecture.md §20.4 (specification).
  Consumer: Grok (LLM) in REPL — referenced from
            grok/prompts/hypothesis_reasoning.md §3 and §8.
  Status:   Normative.  When a new sensor lands in
            src/feelies/sensors/impl/, this catalog MUST be updated in
            the same PR.
-->

# Sensor Catalog — Layer-1 Vocabulary

> **Use only ``sensor_id`` values listed below.** New sensors require a
> companion SENSOR hypothesis (`design_docs/three_layer_architecture.md`
> §10) and a registry entry in `src/feelies/sensors/impl/`. Inventing a
> sensor in YAML without registering it is a hard validation failure
> (G14, sensor-DAG validity).

Sensors emit `SensorReading` events on the bus. SIGNAL-layer features
consume these via the horizon aggregator (`HorizonAggregator`).
Cross-sensor dependencies are declared via `input_sensor_ids` for
topological-order enforcement only — the registry hot path routes raw
market events.

---

## 1. Canonical Catalog (v0.3)

| sensor_id | Output shape | Latent variable | Family role |
|---|---|---|---|
| `ofi_ewma` | float (Cont-Kukanov-Stoikov OFI, τ-EWMA) | Net signed liquidity pressure | KYLE_INFO confirming; HAWKES confirming |
| `micro_price` | float (size-weighted mid) | Latent fair price | KYLE_INFO primary |
| `vpin_50bucket` | float ∈ [0,1] (volume-clock, V̄ = ADV/50) | Informed-flow probability | LIQUIDITY_STRESS primary |
| `kyle_lambda_60s` | float (cov(Δp, signed_vol) / var, 60 s) | Permanent price impact | KYLE_INFO primary |
| `spread_z_30d` | float (z-score vs 30-day median) | Liquidity stress | INVENTORY/STRESS confirming |
| `realized_vol_30s` | float (Parkinson, 30 s) | Instantaneous vol regime | LIQUIDITY_STRESS primary |
| `quote_hazard_rate` | float (exponential hazard on quote life) | Flickering / spoofing intensity | INVENTORY/STRESS confirming |
| `trade_through_rate` | float ∈ [0,1] (% prints outside NBBO, 60 s) | Hidden-liquidity / dark-pool activity | HAWKES confirming |
| `quote_replenish_asymmetry` | float (re-quote bid / re-quote ask post-trade) | Latent depth asymmetry (L2 proxy) | INVENTORY primary |
| `hawkes_intensity` | tuple(λ_buy, λ_sell, ratio, branching) | Self-exciting trade clustering | HAWKES_SELF_EXCITE primary (v0.3) |
| `scheduled_flow_window` | tuple(active, sec_to_close, window_hash, dir_prior) | Time-of-day scheduled flow | SCHEDULED_FLOW primary (v0.3) |
| `snr_drift_diffusion` | tuple(snr_at_h for h in horizons) | Per-horizon signal-to-noise | Cross-cutting exploitability gate (v0.3) |
| `structural_break_score` | float ∈ [0,1] (page-Hinkley) | Non-stationarity in generating process | Cross-cutting alpha-decay diagnostic (v0.3) |

All sensor implementations live under `src/feelies/sensors/impl/`. The
`sensor_version` is read off each class (`<Sensor>.sensor_version`) and
forms part of the alpha's reproducibility manifest.

### 1.1 Sensor binding in alpha YAML

SIGNAL alphas list sensor_ids in `depends_on_sensors:`. The Phase-3
horizon aggregator exposes derived bindings on each
`HorizonFeatureSnapshot`:

```
snapshot.values["<sensor_id>"]                # latest value (or tuple element[0])
snapshot.values["<sensor_id>_zscore"]         # rolling z-score
snapshot.values["<sensor_id>_percentile"]     # rolling percentile rank
```

Tuple-valued sensors (`hawkes_intensity`, `scheduled_flow_window`,
`snr_drift_diffusion`) expose individual elements as
`<sensor_id>__<element_name>` (see the implementation docstring for the
element ordering). The regime-gate DSL accepts the same names.

---

## 2. Per-Mechanism Fingerprint Matrix (G16 rule 5)

Every Phase-3.1 SIGNAL alpha that declares a `trend_mechanism:` block
MUST list **at least one primary fingerprint sensor** for its declared
family in `l1_signature_sensors:` (gate G16 rule 5;
`MissingFingerprintSensorError`). Confirming sensors are
*recommended* but not enforced.

| family | Primary fingerprint sensor(s) | Confirming sensors |
|---|---|---|
| `KYLE_INFO` | `kyle_lambda_60s`, `micro_price` | `ofi_ewma`, `spread_z_30d` |
| `INVENTORY` | `quote_replenish_asymmetry` | `spread_z_30d`, `quote_hazard_rate` |
| `HAWKES_SELF_EXCITE` | `hawkes_intensity` *(v0.3)* | `trade_through_rate`, `ofi_ewma` |
| `LIQUIDITY_STRESS` | `vpin_50bucket`, `realized_vol_30s` | `spread_z_30d`, `quote_hazard_rate` |
| `SCHEDULED_FLOW` | `scheduled_flow_window` *(v0.3)* | `ofi_ewma` |
| *(cross-cutting SNR floor)* | `snr_drift_diffusion` *(v0.3)* | — |
| *(cross-cutting stationarity)* | `structural_break_score` *(v0.3)* | — |

The cross-cutting sensors are not fingerprints for any one family but
are reusable across all five — `snr_drift_diffusion` typically appears
in the regime-gate `on_condition` (exploitability floor), and
`structural_break_score` appears in the `off_condition` or as a
forensics input only.

---

## 3. Half-life Envelopes (G16 rule 2)

Every `trend_mechanism.expected_half_life_seconds` MUST lie inside the
per-family envelope below. Out-of-envelope rejects with
`HalfLifeOutOfEnvelopeError`. The horizon ratio
`horizon_seconds / expected_half_life_seconds` MUST also lie in
`[0.5, 4.0]` (G16 rule 3).

| family | half-life envelope (seconds) |
|---|---|
| `KYLE_INFO` | `[60, 1800]` |
| `INVENTORY` | `[10, 120]` |
| `HAWKES_SELF_EXCITE` | `[5, 120]` |
| `LIQUIDITY_STRESS` | `[30, 600]` |
| `SCHEDULED_FLOW` | `[60, 3600]` |

---

## 4. Sensor Topology Rules

1. Sensors are **per-symbol stateful** but **stateless across symbols**
   (no cross-symbol leakage; replay determinism is per-symbol).
2. A sensor MUST NOT depend on a feature, a signal, or a sized intent
   (downstream-only ban — Inv-6, Inv-8).
3. Sensors that consume other sensors declare it via
   `input_sensor_ids` on `SensorSpec`. The registry enforces a
   topological order at construction; cycles raise
   `SensorTopologyError`.
4. Sensors emit on every relevant raw market event by default.
   Throttled emission (`SensorSpec.emission_rate=throttled_ms:N`) is
   permitted for compute-heavy sensors and does not break replay
   determinism (the throttle clock is event-time, not wall-clock).

---

## 5. When to Propose a New SENSOR

Refuse to invent a sensor inline in a SIGNAL hypothesis. Instead, when
the L1 signature your mechanism requires is not in this catalog:

1. State the **latent variable** the new sensor measures (e.g.
   "queue-position-decay rate", "PFOF flow ratio").
2. Confirm the variable is computable from L1 NBBO + trades + reference
   data only. If it requires L2 / hidden liquidity / colocated tape, it
   is out of scope — abandon the SIGNAL hypothesis.
3. Author a SENSOR hypothesis YAML per
   `grok/prompts/hypothesis_reasoning.md` §7.2.
4. Wait for the SENSOR PR to land before opening the SIGNAL PR. The
   SIGNAL alpha cannot validate without its declared sensors existing
   in the registry.

End of catalog.
