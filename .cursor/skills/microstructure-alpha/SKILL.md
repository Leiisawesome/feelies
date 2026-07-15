---
name: microstructure-alpha
description: >
  Layer-2 SIGNAL alpha authoring: `HorizonSignal`, regime gates, G16, cost arithmetic. Use when writing or reviewing SIGNAL YAML.
---

# Microstructure Alpha — Layer-2 (SIGNAL) Authoring

Scope: Layer-2 (SIGNAL) alpha on L1 NBBO only — no L2 depth or
microsecond-direct-feed edge.

This skill owns the Layer-2 contract: every `layer: SIGNAL` alpha is a
**pure, stateless, horizon-anchored, regime-gated, cost-disclosed,
mechanism-tagged** function from `(HorizonFeatureSnapshot, RegimeState,
params) → Signal | None`. Layer-2 input is `HorizonFeatureSnapshot` only; D.2 retired `FeatureVector` / `LEGACY_SIGNAL`.

## Operating Constraints

- **Data**: L1 NBBO quotes + trades only. No L2 order book.
- **Latency**: Massive WebSocket (~10-50 ms). Not competing on speed.
- **Scale**: Personal / small-fund infrastructure. Not Renaissance.
- **Edge source**: Structural microstructure phenomena, not speed.

Treat L1 as a projection of a latent microstructural state. Explicitly
model what information is lost by not observing L2, and infer it
probabilistically.

---

## L1 Signal Taxonomy

Extract signal from these observable phenomena:

| Category | Observables |
|----------|------------|
| Spread dynamics | Spread level, compression / expansion, regime transitions |
| Quote behavior | Update rate, cancellations, flickers, replenishment asymmetry |
| Trade prints | Aggressor side, size, clustering, prints relative to bid/ask |
| Micro-price | Imbalance proxies from bid/ask sizes, weighted mid |
| Volatility | Short-horizon clustering, realized vs implied divergence |
| Order flow | Inferred from L1 transitions: aggressive trade sequences, quote depletion |

### Inductive (bottom-up)

Observe L1 patterns → hypothesize latent liquidity behavior → test via
forward-return distribution.

- Aggressive trade clustering at ask → short-term buy pressure
- Spread compression + rising micro-price → liquidity-taking phase
- Quote replenishment asymmetry → hidden liquidity inference
- Flickering quotes → spoofing-probability estimation

### Deductive (top-down)

Given rational liquidity-provider behavior under inventory constraints
→ what L1 signature must appear? Derive testable predictions. Price is
an emergent phenomenon of liquidity competition, not a chart line.

For detailed methodology see [`research-protocol.md`](research-protocol.md)
— including the Reformalization Gate (Phase 0), the archetype &
structural-counterparty rider, mirage-risk ranking, the
zero-integrated-edge conservation check, validation-protocol freeze
discipline (magnitude-vs-power labeling, consequence-precedence,
occupancy pre-read, grid-amendment constants), and the tick-grid
artifact test. Proposals instantiate
[`proposal-template.md`](proposal-template.md).

---

## Trend Mechanism Taxonomy (G16)

Every schema-1.1 SIGNAL alpha must declare one of the closed
`TrendMechanism` family in `core/events.py` (Phase 3.1 strict-mode is
the platform default since Workstream E). PORTFOLIO alphas do **not**
declare a single family — instead they declare a `trend_mechanism.consumes:`
list (one entry per upstream family) with a `max_share_of_gross` cap per
family (G16 PORTFOLIO rule 8; see composition-layer skill).

Sensors below are the **implemented** `sensor_id`s only
(see feature-engine skill's catalog). Declaring an unimplemented id in
`l1_signature_sensors` / `depends_on_sensors` fails G6 at load. The
"G16 primary fingerprint" column lists the rule-5 set
(`_FAMILY_FINGERPRINT_SENSORS`, `alpha/layer_validator.py`):
`l1_signature_sensors` must include **at least one** of these;
"other family-related sensors" do not satisfy rule 5 on their own.

| Family | Half-life envelope | G16 primary fingerprint (rule 5) | Other family-related sensors | Cost-arithmetic guidance |
|--------|-------------------|-----------------------|-----------------------|------------------------|
| `KYLE_INFO` | 60 – 1800 s | `kyle_lambda_60s`, `micro_price` | `ofi_ewma` | Edge ~ permanent impact; survive 1.5× spread |
| `INVENTORY` | 5 – 60 s | `quote_replenish_asymmetry` | `inventory_pressure` | Mean-reverting; tight horizon, low cost margin |
| `HAWKES_SELF_EXCITE` | 5 – 60 s | `hawkes_intensity` | `trade_through_rate` | Short half-life; latency-sensitive |
| `LIQUIDITY_STRESS` | 30 – 600 s | `vpin_50bucket`, `realized_vol_30s` | `liquidity_stress_score`, `spread_z_30d`, `quote_hazard_rate`, `quote_flicker_rate` | **Exit-only** — entries forbidden by G16 |
| `SCHEDULED_FLOW` | 60 – 1800 s | `scheduled_flow_window` | — | MOC / open / close imbalance windows |

> Coverage note: every family above now has at least one **dedicated,
> implemented** fingerprint sensor — the previously-missing
> `inventory_pressure` (trade-side MM-inventory proxy),
> `liquidity_stress_score` (composite spread-widening + depth-thinning
> alarm), and `quote_flicker_rate` (best-price reversal fraction) shipped
> in the audit P2-3 pass. `vpin_50bucket` (flow toxicity) and
> `snr_drift_diffusion` ship but remain dormant (not in the reference
> `platform.yaml`).

The alpha's `horizon_seconds / expected_half_life_seconds` ratio must
lie in `[0.5, 4.0]` (G16 mechanism-horizon binding) — neither too
short to harvest nor too long to outlive decay. The fingerprint
sensor for the family must appear in `depends_on_sensors`.

Stress-family alphas are **exit-only**: G16 rejects any entry-direction
`Signal` originating from a `LIQUIDITY_STRESS` alpha. The PORTFOLIO
layer enforces a per-family gross-share cap, declared in the alpha
YAML as `trend_mechanism.consumes[*].max_share_of_gross` and enforced
at runtime via the `CrossSectionalRanker` parameter
`mechanism_max_share_of_gross` (`composition/cross_sectional.py`; see
the composition-layer skill).

The families encode **mechanisms, not archetypes**: every candidate
must additionally state its archetype (liquidity provision /
informed-flow-following / argued third case) and its structural
counterparty — see the archetype rider in
[`research-protocol.md`](research-protocol.md) Phase 1.

The mechanism is propagated end-to-end on `Signal.trend_mechanism` and
`Signal.expected_half_life_seconds`, surfaced in
`SizedPositionIntent.mechanism_breakdown`, and consumed by
`MultiHorizonAttributor` for per-mechanism PnL decomposition (see
post-trade-forensics).

---

## SIGNAL Alpha Contract

A schema-1.1 SIGNAL alpha YAML declares (canonical reference:
`alphas/SCHEMA.md`):

```yaml
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_signal_alpha
version: "1.0.0"
hypothesis: "[actor] does [action] because [incentive]; L1 signature: [observable]"
falsification_criteria:
  - "Mechanism-tied criterion (Inv-2)."

depends_on_sensors: [kyle_lambda_60s, ofi_ewma, spread_z_30d]
horizon_seconds: 300

trend_mechanism:                        # G16 — required since Workstream E
  family: KYLE_INFO
  expected_half_life_seconds: 240
  l1_signature_sensors: [kyle_lambda_60s]
  failure_signature:                    # G16 rule 6 — non-empty LIST of invalidator clauses
    - "kyle_lambda decays below 30d percentile-20 …"

regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "P(normal) > 0.6 and spread_z_30d <= 1.0"
  off_condition: "P(normal) < 0.4 or spread_z_30d > 2.0"
  hysteresis: {posterior_margin: 0.20, percentile_margin: 0.30}

cost_arithmetic:                        # G12 — Inv-12 enforcement
  edge_estimate_bps: 11.7
  half_spread_bps: 2.5
  impact_bps: 3.0
  fee_bps: 1.0
  margin_ratio: 1.8                    # ≥ 1.5; reconciles ±0.05 absolute (alpha/cost_arithmetic.py)

signal: |
  def evaluate(snapshot, regime, params):
      ...
```

### `HorizonSignal` Protocol

Implementations live in the loaded module body and conform to
`signals/horizon_protocol.py`:

```python
class HorizonSignal(Protocol):
    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState,
        params: Mapping[str, Any],
    ) -> Signal | None: ...
```

`evaluate()` is a **pure function**: deterministic, no side effects,
no state mutation, no I/O (Inv-5). Given identical
`HorizonFeatureSnapshot`, `RegimeState`, and parameters, it must
produce identical outputs.

Returns `Signal` when a tradeable condition is detected, `None`
otherwise. The signal carries `direction (LONG | SHORT | FLAT)`,
`strength ∈ [0,1]`, `edge_estimate_bps`, `trend_mechanism`,
`expected_half_life_seconds`, and inherits `correlation_id`,
`timestamp_ns`, `sequence` from `Event` for provenance.

### Single-Horizon Binding

Each SIGNAL alpha is anchored to **one** `horizon_seconds` from the
configured set (`platform.yaml: horizons_seconds`, canonical Phase-2
set `{30, 120, 300, 900, 1800}`). `HorizonSignalEngine` invokes
`evaluate()` once per `(alpha_id, symbol, boundary_index)` triple
after the alpha's `regime_gate` resolves to ON. At most one `Signal`
per triple; bit-identical replay is contractual (locked by the
Level-2 SIGNAL parity test, `tests/determinism/test_signal_replay.py`).

### `RegimeGate` (Purity Boundary)

The `regime_gate:` block is parsed into a safe AST-evaluated boolean
DSL by `signals/regime_gate.py`. Two expressions:

- `on_condition` — transition OFF→ON
- `off_condition` — transition ON→OFF

Bindings drawn from `RegimeState` posteriors (`P(<state_name>)`,
`dominant`) and the live sensor cache (`<sensor_id>`,
`<sensor_id>_zscore`, `<sensor_id>_percentile`). Hysteresis state is
per `(alpha_id, symbol)`.

Only whitelisted AST nodes survive parse — `Attribute`, free-form
`Call`, `Lambda`, `Subscript`, `ListComp`, etc. raise
`UnsafeExpressionError` at compile time. The gate is the purity
boundary: never reads untyped state, never imports, never mutates the
snapshot. Inv-6 (causality) and Inv-7 (typed events) follow by
construction.

### Feature Quality Gates

`evaluate()` receives a `HorizonFeatureSnapshot` carrying:

- `warm: dict[str, bool]` — per `feature_id`; a key is `False` during
  that feature's warm-up. The `HorizonSignalEngine` suppresses entry
  when any of the alpha's `required_warm_feature_ids` is not warm —
  the alpha body does **not** see the snapshot unless those are warm.
- `stale: dict[str, bool]` — per `feature_id`; `True` when the feature's
  input sensor produced no warm reading within the feature's horizon
  window. Entry suppressed, exits permitted (conservative).
- `values: dict[str, float]` — per `feature_id`, **warm features only**
  (cold features are absent — use `.get(...)` and handle `None`). The
  reference alpha reads e.g. `values.get("ofi_ewma_zscore")`.
- `boundary_index: int` — deterministic ordering key

Note: `warm` / `stale` are **dicts keyed by `feature_id`**, not
booleans. Never gate on `if snapshot.warm:` (a non-empty dict is always
truthy); gate on the specific keys you consume.

### Cost Arithmetic (G12)

The `cost_arithmetic:` block discloses `edge_estimate_bps`,
`half_spread_bps`, `impact_bps`, `fee_bps`, and the resulting
`margin_ratio = edge / (half_spread + impact + fee)`. Validated by
`alpha/cost_arithmetic.py` at load time:

- `margin_ratio ≥ 1.5` enforces Inv-12 (transaction cost realism)
- The disclosed `margin_ratio` must reconcile with the components
  within ±0.05 **absolute on the ratio** — not ±5% relative
  (`alpha/cost_arithmetic.py`); otherwise the alpha author has lied
  about costs and the load is rejected

The block is structural metadata — it does not alter runtime sizing —
but it is recorded in the alpha manifest for promotion gating,
post-trade reconciliation, and decay detection.

**Units-convention rider (FQ-1, NORMATIVE —
`docs/research/prompt_pack_00b_edge_units_convention.md`):**

- `edge_estimate_bps` and all three cost components
  (`half_spread_bps`, `impact_bps`, `fee_bps`) are **one-way
  (per-fill) quantities in bps of fill notional**. Declaring
  round-trip figures is a disclosure error that systematically
  loosens the B4 runtime gate, which doubles the disclosed edge onto
  the round-trip basis (`signal_edge_cost_basis: "round_trip"`
  default) before comparing against `min_ratio ×` the modeled
  entry+taker-exit round-trip cost at `signal_min_edge_cost_ratio`
  default 1.0 (`execution/position_manager.py`,
  `entry_edge_clears_cost`).
- The optional `cost_basis` YAML field (default `one_way`,
  `alpha/cost_arithmetic.py`) records the basis; `round_trip` is
  accepted but reserved — no shipped alpha uses it and new
  candidates must not.
- `margin_ratio ≥ 1.5` is a **one-way** figure (≈ 0.75× on the
  round-trip basis); the reconciliation tolerance is ±0.05 absolute
  on the ratio, per above.
- Realized-edge comparisons (forensics TCA, the SURVIVES verdict,
  the calibration haircut — `forensics/decay_detector.py`,
  `forensics/cost_survival.py`, `forensics/edge_calibration.py`) are
  per-fill quantities directly commensurate with the one-way
  disclosure under balanced entry/exit fill counts.

#### Units convention (FQ-1, NORMATIVE — `docs/research/prompt_pack_00b_edge_units_convention.md`)

- `edge_estimate_bps` and all three cost components
  (`half_spread_bps`, `impact_bps`, `fee_bps`) are **one-way
  (per-fill) quantities in bps of fill notional**. Declaring
  round-trip figures is a disclosure error that systematically
  loosens the B4 runtime gate, which doubles the disclosed edge onto
  the round-trip basis (`signal_edge_cost_basis: "round_trip"`
  default) before comparing against `min_ratio ×` the modeled
  entry+taker-exit round-trip cost at `signal_min_edge_cost_ratio`
  default 1.0 (`execution/position_manager.py`,
  `core/platform_config.py`).
- The optional `cost_basis` YAML field (default `one_way`,
  `alpha/cost_arithmetic.py`) records the basis; `round_trip` is
  accepted but **reserved** — no shipped alpha uses it and new
  candidates must not.
- `margin_ratio ≥ 1.5` is a **one-way** figure (≈ 0.75× on the
  round-trip basis); the reconciliation tolerance is ±0.05 absolute
  on the ratio, not ±5% relative (`alpha/cost_arithmetic.py`).
- Realized-edge comparisons (forensics TCA, the SURVIVES verdict,
  the calibration haircut — `forensics/decay_detector.py`,
  `forensics/cost_survival.py`, `forensics/edge_calibration.py`) are
  per-fill quantities directly commensurate with the one-way
  disclosure under balanced entry/exit fill counts.

---

## Entry / Exit Design

### Entry Conditions

Enter only when:
- Every consumed `feature_id` is warm and not stale (`warm` / `stale`
  are per-`feature_id` dicts; the engine gates on the alpha's
  `required_warm_feature_ids` — see Feature Quality Gates above)
- The alpha's `regime_gate` has resolved to ON
- The mechanism family's expected half-life justifies the configured
  horizon (G16)
- `edge_estimate_bps > 1.5 × round_trip_cost_bps` (Inv-12, structurally
  enforced via `cost_arithmetic`)
- A **structural force** is identified (Inv-1) — not a threshold trigger
- The causal chain is specified: e.g., imbalance → spread shift →
  micro-price drift

Every entry must answer:
1. What structural force am I exploiting?
2. What event invalidates this force?
3. What regime shift kills this edge?

### Exit Conditions

Exit based on:
- Regime gate transitioning OFF
- Hazard rate of reversal exceeds threshold (`RegimeHazardSpike`
  consumed by `HazardExitController` — see regime-detection skill)
- Structural invalidation (the causal premise breaks)
- Time decay (alpha half-life exceeded — `expected_half_life_seconds`)

Exits are permitted even when consumed features are stale
(`snapshot.stale[feature_id] == True` — conservative: exit is safer
than hold when data is missing).

### Hazard-Driven Exit

When `hazard_exit.enabled: true` is declared on the alpha manifest
(SIGNAL **or** PORTFOLIO layer — both are now wired; audit P0 H-1),
`HazardExitController` consumes `RegimeHazardSpike` events and emits
`OrderRequest.reason = "HAZARD_SPIKE"` to flatten open positions when
the per-alpha `hazard_score_threshold` is exceeded (and the position
has been open at least `min_age_seconds`). A separate `HARD_EXIT_AGE`
branch fires when a position has been open longer than
`hard_exit_age_seconds`; when this field is omitted it is **derived
from `2 × expected_half_life_seconds`** (audit P1 HM-1) so short-
half-life mechanisms aren't silently age-uncapped.

Schema (audit P1 H-2 — strict; unknown keys raise `AlphaLoadError`):

```yaml
hazard_exit:
  enabled: true                  # bool — literal True opts in
  hazard_score_threshold: 0.85   # float in (0, 1]; controller default 0.85
  min_age_seconds: 30            # int ≥ 0; controller default 30
  hard_exit_age_seconds: 1800    # int > 0; null → 2 × expected_half_life_seconds
```

`posterior_drop_threshold` is accepted as a legacy spelling of
`hazard_score_threshold` (the detector's `hazard_score` IS a
normalized posterior drop) and rewritten with a WARN at load time;
use the canonical name in new specs.

Suppression at the **controller** layer is per
`(strategy_id, symbol, reason)`, cleared when the position returns
to flat.  This is distinct from the **detector** suppression key
`(symbol, engine_name, departing_state)` held inside
`RegimeHazardDetector`.  Bit-identical replay is locked by the
Level-5 hazard-replay parity test
(`tests/determinism/test_regime_hazard_replay.py`).

---

## Pre-Trade Capacity & Crowding Envelope

Declare the envelope at **proposal time**, before any backtest — it
belongs in the proposal's CAPACITY & CROWDING section
([proposal-template.md](proposal-template.md)) and in the PORTFOLIO
VIEW of any recommendation:

- **ADV-based ceiling** — state the maximum position as a fraction of
  the midcap universe's ADV at which the disclosed `impact_bps` still
  holds. This is a research-stage claim, distinct from the risk
  engine's runtime ADV participation limit (policy-only today — see
  risk-engine skill, "Policy only — not yet implemented").
- **Sharpe-max vs profit-max size** — the Sharpe-maximizing size is
  smaller than the profit-maximizing size once impact is concave in
  participation; state which one the candidate targets and why.
- **Correlated-unwind reasoning** — who else exits when this
  mechanism's trigger fires (same-family alphas, same-archetype
  competitors), and what that does to realized exit cost relative to
  the disclosed `impact_bps`.

Caveat (OQ-3, accepted risk): G16 PORTFOLIO rule-8 mechanism-share
caps are validated at load time only — runtime enforcement is not
active (bootstrap wires `CrossSectionalRanker` with
`mechanism_max_share_of_gross=1.0`; see composition-layer skill). No
capacity or deployment claim may rely on runtime mechanism-share
enforcement.

Post-trade crowding **symptoms** (alpha decay with stable signal
quality, adverse-selection increase, quote anticipation) are owned by
the post-trade-forensics skill — the envelope here is the pre-trade
counterpart, not a duplicate of that table.

---

## Uncertainty Quantification

Markets are stochastic, non-stationary, partially observed systems.

### Mandatory Practices

- **No point estimates** — model distributions
- **Hazard-rate thinking** — not certainties
- **Confidence intervals** on alpha decay timescales
- **Stability tests** across volatility / spread regimes
- **Rolling-window diagnostics** for parameter drift
- **Sensitivity analysis** on latency, slippage, fill probability

### Assumptions

- Edge decays when exploited (Inv-4)
- Parameter drift is the rule, not the exception
- Correlations are regime-dependent, not stable

### Mathematical Framework

Reason with appropriate formalism: stochastic calculus for diffusion
approximations, point processes (Hawkes) for order arrivals,
Markov / semi-Markov for regime switching, Bayesian inference for
uncertainty quantification, causal inference (intervention vs
correlation distinction). Define state variables. Specify conservation
constraints. Distinguish signal from noise via hypothesis testing.
Separate structural invariants from regime-dependent parameters.

---

## Pipeline Position

```
NBBOQuote / Trade
  → M1: bus publish + event log append
    → M2: RegimeEngine.posterior → RegimeState
      → SENSOR_UPDATE: SensorRegistry fan-out → SensorReading[]
        → HORIZON_CHECK: HorizonScheduler boundary detection
          → HORIZON_AGGREGATE: HorizonAggregator → HorizonFeatureSnapshot
            → SIGNAL_GATE: HorizonSignalEngine
                ├─ regime_gate OFF → no emission
                └─ regime_gate ON → HorizonSignal.evaluate(snapshot, regime, params)
                    └─ → Signal | None published on the bus
                        → M4 SIGNAL_EVALUATE: orchestrator drains buffered Signal
                          → PositionSizer.compute_target_quantity
                            → IntentTranslator → OrderIntent
                              ├─ NO_ACTION → M10
                              └─ actionable → M5 RiskEngine.check_signal
                                → M6 _build_order_from_intent → OrderRequest
                                  → M7 OrderRouter.submit
                                    → M8 poll_acks → OrderAck
                                      → M9 _reconcile_fills → PositionUpdate
```

The PORTFOLIO layer (`composition` package) is downstream of SIGNAL —
it consumes contemporaneous `Signal` events through
`UniverseSynchronizer` and emits `SizedPositionIntent`. See the
composition-layer skill.

---

## Critical Separations

| Separate | From |
|----------|------|
| Research environment | Production |
| Backtest logic | Live execution logic |
| Signal generation | Position sizing |
| Mechanism declaration (`trend_mechanism:`) | Runtime predicate (`regime_gate:`) — both are required |

`HorizonSignal.evaluate` does not size, route, or risk-check — those are
downstream layers. Maintaining strict purity here keeps the Level-2
parity hash bit-identical and the alpha's economic claims auditable.

---

## Behavioral Constraints

### You Must

- Challenge weak assumptions explicitly
- State model limitations before presenting results
- Distinguish structural insight (edge) from curve fit (alpha)
- Refuse strategies relying on unrealistic fill assumptions
- Label unvalidated theories as hypotheses; specify falsification criteria

### You Must Not

- Use vague technical-analysis language — folk claims are inadmissible
  until they pass the Reformalization Gate
  ([research-protocol.md](research-protocol.md) Phase 0: state variable
  with units + conditional-distribution claim + falsifier)
- Conflate correlation with causation
- Propose alphas that vanish after realistic transaction costs
- Rely on patterns without causal mechanisms
- Hand-wave over execution feasibility
- Skip the `trend_mechanism:` block (rejected by G16 strict mode)

---

## Output Format

Structure all substantive responses as:

```
MICROSTRUCTURE VIEW
-> Edge mechanism (TrendMechanism family + half-life)
-> State transition identified
-> Trigger conditions
-> Immediate invalidation criteria

PORTFOLIO VIEW
-> Loss geometry
-> Tail exposure assessment
-> Cross-sectional construction objectives
-> Mechanism-cap implications
-> Capacity & crowding envelope (pre-trade section above)

CTO VIEW
-> Execution feasibility
-> Sensor / data requirements
-> Failure modes
-> Monitoring metrics
-> Kill-switch rules

SYNTHESIS
-> Deployable under what constraints?
-> If not: where does it break?
```

Omit sections only when genuinely irrelevant.

---

## Tri-Altitude Convergence Rule

**Applies only to final strategy recommendations** (not routine code
changes). Before recommending deployment, validate across microstructure,
portfolio-risk, and CTO layers. If convergence is impossible, declare
non-viable.

---

## Integration Points

See [skill index](../README.md). **Non-obvious edges:** consumes `HorizonFeatureSnapshot`, emits `Signal`; see [`research-protocol.md`](research-protocol.md) and [`system-architecture.md`](system-architecture.md).