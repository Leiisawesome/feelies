# Migration Cookbook — Alpha Schema 1.0 → 1.1

> **Workstream D.1 — schema 1.0 hard-removal.** `schema_version: "1.0"`
> is **no longer accepted** by the loader; it is rejected outright
> with a pointer back to this cookbook.  All existing alphas must
> declare `schema_version: "1.1"`.

> **Workstream D.2 — LEGACY_SIGNAL retirement (current release).**
> `layer: LEGACY_SIGNAL` is also **no longer accepted** by the loader;
> the per-tick legacy execution path was retired.  The §1 five-line
> upgrade documented below is preserved for historical reference, but
> the only viable migration target post-D.2 is the SIGNAL layer
> (§3) or the PORTFOLIO layer (§8).  Authors with a private
> ``layer: LEGACY_SIGNAL`` alpha must promote it to SIGNAL or pin a
> private fork of the platform that retains the legacy code-path.

> **Audience:** alpha authors with one or more existing
> `schema_version: "1.0"` YAML files in `alphas/`.
>
> **Goal:** mechanical, opt-in upgrade path to schema 1.1 with **zero
> behavioural change** by default, plus a clear runway for opting into
> the Phase-3 horizon engine, the Phase-3.1 mechanism contract, the
> Phase-4 PORTFOLIO layer, and the Phase-4.1 decay/hazard extensions
> when the operator is ready.
>
> **Deprecation timeline:** see §11.

---

## Table of Contents

1. The five-line upgrade (LEGACY_SIGNAL)
2. Field-by-field cheat sheet (1.0 → 1.1)
3. Promoting LEGACY_SIGNAL → SIGNAL (Phase 3)
4. The `cost_arithmetic` block (gate G12)
5. The `regime_gate` DSL (gate G4)
6. The `depends_on_sensors` block (gate G6 / sensor catalog)
7. Horizon binding (`horizon_seconds`; gate G7)
8. Authoring a PORTFOLIO alpha (Phase 4)
9. Hazard exits (Phase 4.1)
10. v0.3 opt-in cookbook — `trend_mechanism` + `enforce_trend_mechanism`
11. Deprecation timeline & sunset

---

## 1. The five-line upgrade (LEGACY_SIGNAL) — historical reference only

> **Status: rejected by the loader as of Workstream D.2.**  This
> section is retained as a historical "before" example so the
> §3 promotion path (`LEGACY_SIGNAL → SIGNAL`) reads end-to-end.
> Do **not** apply the upgrade below to a new alpha — it will fail
> to load.

For an existing schema-1.0 alpha that you are not ready to promote to
the horizon engine yet, the historical (D.1-only, pre-D.2) shape was:

```yaml
schema_version: "1.1"
layer: LEGACY_SIGNAL
```

Post-D.2 the loader rejects every `layer: LEGACY_SIGNAL` spec with an
`AlphaLoadError` pointing back at this cookbook.  The viable migration
targets are:

- `layer: SIGNAL` — see §3 below.
- `layer: PORTFOLIO` — see §8 below.

**Workstream-D update —** the in-repo `LEGACY_SIGNAL` reference alpha
(`alphas/trade_cluster_drift/`) and its anchoring parity test
(`tests/determinism/test_legacy_alpha_parity.py`) were retired in D.2.
Both the per-tick legacy execution path and the loader-side
`LEGACY_SIGNAL` dispatch were removed in the same workstream; the
in-repo regression suite no longer carries a LEGACY-anchored Level-1
hash.

**Why a five-line upgrade is no longer enough?** Two reasons:

- The bare `schema_version: "1.0"` form is **rejected** at load time
  (workstream D.1).
- The historical bridge value `layer: LEGACY_SIGNAL` is also
  **rejected** at load time (workstream D.2); declaring it does not
  preserve the per-tick contract any more.

---

## 2. Field-by-field cheat sheet (1.0 → 1.1)

| 1.0 field | 1.1 status | Notes |
|---|---|---|
| `schema_version` | required | bump to `"1.1"` |
| `alpha_id` | unchanged | still `^[a-z][a-z0-9_]*$` |
| `version` | unchanged | semver |
| `description` | unchanged | |
| `hypothesis` | unchanged | |
| `falsification_criteria` | unchanged | |
| `symbols` | unchanged | optional restriction list |
| `parameters` | unchanged | ≤ 3 with free range (G12) |
| `risk_budget` | unchanged | |
| `features` | LEGACY_SIGNAL only | SIGNAL alphas drop this |
| `signal` | unchanged for LEGACY_SIGNAL; signature changes for SIGNAL | see §3 |
| `layer` | **NEW (mandatory in 1.1)** | `LEGACY_SIGNAL` \| `SIGNAL` \| `PORTFOLIO` |
| `horizon_seconds` | NEW (SIGNAL/PORTFOLIO) | gate G7 |
| `depends_on_sensors` | NEW (SIGNAL) | gate G6 |
| `regime_gate` | NEW (SIGNAL) | gate G4 |
| `cost_arithmetic` | NEW (SIGNAL/PORTFOLIO) | gate G12 |
| `universe` | NEW (PORTFOLIO) | gate G10 |
| `depends_on_signals` | NEW (PORTFOLIO) | gate G3 |
| `factor_neutralization` | NEW (PORTFOLIO) | gate G11 |
| `trend_mechanism` | NEW (SIGNAL/PORTFOLIO; opt-in v0.3) | gate G16, see §10 |
| `hazard_exit` | NEW (SIGNAL/PORTFOLIO; opt-in v0.3) | see §9 |

A schema-1.0 spec containing a `layer:` field is **rejected** — `layer`
requires `schema_version: "1.1"`. A schema-1.1 spec **without**
`layer:` is also rejected — there is no implicit upgrade path.

---

## 3. Promoting LEGACY_SIGNAL → SIGNAL (Phase 3)

The Phase-3 SIGNAL contract is fundamentally different:

- Per-tick `features:` blocks are dropped — features come from the
  **sensor layer** (`depends_on_sensors:`) and the horizon aggregator
  (`HorizonFeatureSnapshot`).
- `evaluate(features, params)` becomes
  `evaluate(snapshot, regime, params)`.
- The signal fires only at horizon boundaries and only when the
  `regime_gate` resolves to ON.

Minimal SIGNAL spec (mandatory blocks only):

```yaml
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_signal_alpha
version: "1.0.0"
description: "One paragraph on the structural edge."
hypothesis: |
  [actor] does [action] because [incentive], leaking into L1 as
  [observable signature].
falsification_criteria:
  - "Mechanism-tied criterion 1."
  - "OOS DSR < 1.0 across any single calendar quarter after LIVE."

depends_on_sensors:
  - kyle_lambda_60s
  - ofi_ewma
  - spread_z_30d

horizon_seconds: 300

regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(normal) > 0.6 and spread_z_30d <= 1.0
  off_condition: |
    P(normal) < 0.4 or spread_z_30d > 2.0
  hysteresis:
    posterior_margin: 0.20
    percentile_margin: 0.30

cost_arithmetic:
  edge_estimate_bps: 11.7
  half_spread_bps: 2.5
  impact_bps: 3.0
  fee_bps: 1.0
  margin_ratio: 1.8

signal: |
  def evaluate(snapshot, regime, params):
      z = snapshot.values.get("kyle_lambda_60s_zscore")
      ofi = snapshot.values.get("ofi_ewma")
      if z is None or ofi is None:
          return None
      if abs(z) < 2.0:
          return None
      direction = LONG if ofi > 0.0 else SHORT
      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="my_signal_alpha",
          direction=direction,
          strength=min(abs(z) / 4.0, 1.0),
          edge_estimate_bps=min(abs(z) * 4.0, 20.0),
      )
```

Mechanical mapping from a typical 1.0 signal:

- Replace `features.values.get("foo", 0.0)` with
  `snapshot.values.get("foo", 0.0)`. The `.values` dict is populated
  by `HorizonAggregator` from `depends_on_sensors` and exposes
  `<sensor_id>`, `<sensor_id>_zscore`, `<sensor_id>_percentile`
  bindings (and tuple-component bindings for tuple-valued sensors —
  see `grok/prompts/sensor_catalog.md` §1.1).
- Replace `features.timestamp_ns` / `correlation_id` / `sequence` /
  `symbol` with the same fields on `snapshot`. The Signal constructor
  signature is unchanged.
- Drop the `features:` block entirely. If the legacy alpha computed a
  feature that does not exist as a sensor, you must:
  - either find a sensor in `grok/prompts/sensor_catalog.md` that
    measures the same latent variable, or
  - author a SENSOR hypothesis first and add it to the registry, then
    reference it from `depends_on_sensors`.
- Add a `regime_gate:` block. The DSL is documented in §5.

The reference SIGNAL alpha is
[`alphas/pofi_kyle_drift_v1`](../../alphas/pofi_kyle_drift_v1/) — copy
its structure verbatim and edit the mechanism story.

---

## 4. The `cost_arithmetic` block (gate G12)

Required on every SIGNAL and PORTFOLIO alpha. Validated at load time
by `feelies.alpha.cost_arithmetic.CostArithmetic`:

```yaml
cost_arithmetic:
  edge_estimate_bps: 11.7   # claimed expected per-trade edge
  half_spread_bps: 2.5      # estimated half-spread cost (one side)
  impact_bps: 3.0           # estimated permanent impact (Almgren-Chriss)
  fee_bps: 1.0              # taker fees + reg fees
  margin_ratio: 1.8         # = edge / (half_spread + impact + fee); ≥ 1.5
```

Two enforcement rules:

1. `margin_ratio ≥ 1.5` (Inv-12). Below this hurdle the platform
   refuses to load the alpha.
2. The disclosed `margin_ratio` must reconcile with its components
   within ±5%. Otherwise the load rejects with a "lied about costs"
   error.

There is **no runtime sizing effect** — the block is structural
metadata recorded in the alpha manifest for promotion gating, post-
trade reconciliation, and decay detection.

`edge_estimate_bps` MUST be backed by a citation in your `rationale.md`
or commit message — empirical (prior backtest, paper reference) or
theoretical (mechanism derivation). Guesses will be caught at the
first promotion review and bounce the alpha back to DRAFT.

---

## 5. The `regime_gate` DSL (gate G4)

A Phase-3 SIGNAL alpha is regime-conditional by construction.
Unconditional alphas do not survive OOS validation.

```yaml
regime_gate:
  regime_engine: hmm_3state_fractional   # platform regime engine identifier
  on_condition: |
    P(normal) > 0.6 and spread_z_30d <= 1.0
  off_condition: |
    P(normal) < 0.4 or spread_z_30d > 2.0
  hysteresis:
    posterior_margin: 0.20               # ≥ 0.15 (G9)
    percentile_margin: 0.30
```

Bindings available in the DSL:

- `P(<state_name>)` — posterior over the regime state (e.g.
  `P(normal)`, `P(stressed)`, `P(toxic)`).
- `dominant` — string id of the dominant state.
- `<sensor_id>` — latest scalar value of any sensor in
  `depends_on_sensors` (or its `__<component>` for tuple-valued
  sensors).
- `<sensor_id>_zscore`, `<sensor_id>_percentile` — derived rolling
  bindings published by the aggregator.

Whitelisted operators: arithmetic, comparison, boolean, function calls
on the bound names. **Forbidden** at compile time:
attribute access, subscripting, lambdas, comprehensions, imports,
free-form `Call` on unbound names — these all raise
`UnsafeExpressionError` and the alpha refuses to load.

Hysteresis margin (gate G9) requires the on/off thresholds to differ
by ≥ 0.15 for posterior conditions and ≥ 20 percentile points for
percentile conditions, preventing chattering.

---

## 6. The `depends_on_sensors` block (gate G6 / sensor catalog)

```yaml
depends_on_sensors:
  - kyle_lambda_60s
  - ofi_ewma
  - micro_price
  - spread_z_30d
```

Every entry must resolve to a registered sensor in
`feelies.sensors.registry.SensorRegistry`. Unknown ids raise
`SensorNotRegisteredError` at load time. Cycles in cross-sensor
dependencies (declared on `SensorSpec.input_sensor_ids`) raise
`SensorTopologyError`.

The canonical catalog ships in
[`grok/prompts/sensor_catalog.md`](../../grok/prompts/sensor_catalog.md).
Adding a sensor is a deliberate platform-level change — a new
implementation under `src/feelies/sensors/impl/`, a registry entry
(`SensorSpec`), a catalog row, and a SENSOR hypothesis YAML.

---

## 7. Horizon binding (`horizon_seconds`; gate G7)

```yaml
horizon_seconds: 300
```

Must be a member of `PlatformConfig.horizons_seconds` (the canonical
Phase-2 set is `{30, 120, 300, 900, 1800}`). Setting a value below 30
on a SIGNAL alpha is rejected — the platform's L1 NBBO sampling rate
cannot carry a sub-30s horizon snapshot.

The `HorizonScheduler` emits `HorizonTick` events at deterministic
event-time boundaries (`session_open_ns + k * horizon_seconds * 1e9`)
for every registered horizon; the alpha's `evaluate` is invoked once
per boundary per symbol after the regime gate resolves to ON.

PORTFOLIO alphas additionally constrain
`horizon_seconds ≥ 300` and `horizon_seconds ≥ max(upstream SIGNAL
horizons)` (gate G3 / cross-alpha isolation).

---

## 8. Authoring a PORTFOLIO alpha (Phase 4)

Minimal PORTFOLIO spec (mandatory blocks only):

```yaml
schema_version: "1.1"
layer: PORTFOLIO

alpha_id: my_portfolio_alpha
version: "1.0.0"
description: "Cross-sectional alpha consuming the listed SIGNAL outputs."

hypothesis: |
  Cross-sectional dispersion of horizon-anchored microstructure signals
  carries a residual factor-orthogonal alpha at 5-minute decision
  horizons after fee + impact deductions.

falsification_criteria:
  - sharpe_post_cost_below_1.0_60d

horizon_seconds: 300

universe:
  - AAPL
  - MSFT
  - GOOG
  - AMZN
  - META

depends_on_signals:
  - my_signal_alpha

factor_neutralization: true

cost_arithmetic:
  edge_estimate_bps: 12.0
  half_spread_bps: 1.5
  impact_bps: 1.5
  fee_bps: 0.5
  margin_ratio: 3.43

risk_budget:
  max_position_per_symbol: 5000
  max_gross_exposure_pct: 50.0
  max_drawdown_pct: 5.0
  capital_allocation_pct: 100.0
```

The PORTFOLIO alpha never bypasses the risk engine. Its
`SizedPositionIntent` is decomposed into per-leg `OrderRequest`s by
`RiskEngine.check_sized_intent`; per-leg veto (Inv-11) drops only the
failing leg, not the whole intent.

The default composition pipeline
(`CrossSectionalRanker → FactorNeutralizer → SectorMatcher →
TurnoverOptimizer`) is wired automatically — no inline `construct:`
block is needed unless you have an explicit reason to override the
ordering, and any override requires a `rationale.md` justification.

---

## 9. Hazard exits (Phase 4.1)

Opt in by adding a `hazard_exit:` block to a PORTFOLIO alpha:

```yaml
hazard_exit:
  enabled: true
  hazard_score_threshold: 0.7    # spike posterior departure floor
  min_age_seconds: 60            # don't exit positions younger than this
  hard_exit_age_seconds: 1800    # hard cap; fires regardless of regime
  hard_exit_suppression_seconds: 300
```

Two exit paths:

- On `RegimeHazardSpike`: spike score ≥ threshold AND position age ≥
  `min_age_seconds` ⇒ emit `OrderRequest(reason="HAZARD_SPIKE")`.
- On `Trade` reconciliation: position age ≥ `hard_exit_age_seconds` ⇒
  emit `OrderRequest(reason="HARD_EXIT_AGE")`.

Suppression is per `(symbol, alpha_id, departing_state)` — at most one
hazard-spike exit per departure episode. The hard-exit branch is
suppressed for `hard_exit_suppression_seconds` after firing.

Both paths are bit-identical across replays — verified by
`tests/determinism/test_hazard_exit_replay.py`.

---

## 10. v0.3 opt-in cookbook — `trend_mechanism` + `enforce_trend_mechanism`

The v0.3 mechanism contract (gate G16, Phase 3.1) is **opt-in via
field presence** by default. A SIGNAL alpha without a
`trend_mechanism:` block continues to load and run unchanged.

### 10.1 Adding a `trend_mechanism:` block (SIGNAL)

```yaml
trend_mechanism:
  family: KYLE_INFO                 # closed enum (see §10.3)
  expected_half_life_seconds: 600   # within family envelope (§10.4)
  l1_signature_sensors:             # at least one MUST be a primary fingerprint
    - kyle_lambda_60s
    - ofi_ewma
  failure_signature:                # at least one — mechanism-specific invalidator
    - "spread_z_30d > 2.0"
    - "kyle_lambda_60s_zscore < -1.5"
```

Validation at load time (G16):

1. `family` ∈ `{KYLE_INFO, INVENTORY, HAWKES_SELF_EXCITE, LIQUIDITY_STRESS, SCHEDULED_FLOW}`.
2. `expected_half_life_seconds` within per-family envelope (§10.4).
3. `horizon_seconds / expected_half_life_seconds ∈ [0.5, 4.0]`.
4. Every `l1_signature_sensors` entry is a registered sensor.
5. The family's primary fingerprint sensor (per
   `grok/prompts/sensor_catalog.md` §2) appears in
   `l1_signature_sensors`.
6. `failure_signature` is a non-empty list of strings.
7. **`LIQUIDITY_STRESS` is exit-only** — the `signal:` body is
   AST-scanned and any code path that can return a `LONG`/`SHORT`
   `Signal` rejects. Stress alphas may only emit `FLAT` (close-
   position) signals.

### 10.2 Adding a `trend_mechanism:` block (PORTFOLIO)

```yaml
trend_mechanism:
  consumes:
    - {family: KYLE_INFO,  max_share_of_gross: 0.6}
    - {family: INVENTORY,  max_share_of_gross: 0.5}
  max_share_of_gross: 0.6           # global cap across all families
```

Additional G16 PORTFOLIO rules:

- 8. The sum of declared per-family `max_share_of_gross` is bounded
  (no over-allocation). The `CrossSectionalRanker` enforces the cap at
  emission time and reports per-family share on every
  `SizedPositionIntent.mechanism_breakdown`.
- 9. Every `depends_on_signals` entry must declare a
  `trend_mechanism.family` that appears in `consumes:` (whitelist).

### 10.3 Closed family taxonomy

| family | Typical horizon | Primary fingerprint sensor(s) |
|---|---|---|
| `KYLE_INFO` | 60 – 1800 s | `kyle_lambda_60s`, `micro_price` |
| `INVENTORY` | 10 – 120 s | `quote_replenish_asymmetry` |
| `HAWKES_SELF_EXCITE` | 5 – 120 s | `hawkes_intensity` |
| `LIQUIDITY_STRESS` | 30 – 600 s (exit-only) | `vpin_50bucket`, `realized_vol_30s` |
| `SCHEDULED_FLOW` | 60 – 3600 s | `scheduled_flow_window` |

Adding a family is a deliberate platform-level change — modify
`feelies.core.events.TrendMechanism` and
`feelies.alpha.loader._TREND_MECHANISM_FAMILIES` together, then update
this section, the sensor catalog, and the layer validator envelope
table.

### 10.4 Half-life envelopes (G16 rule 2)

| family | envelope (seconds) |
|---|---|
| `KYLE_INFO` | `[60, 1800]` |
| `INVENTORY` | `[10, 120]` |
| `HAWKES_SELF_EXCITE` | `[5, 120]` |
| `LIQUIDITY_STRESS` | `[30, 600]` |
| `SCHEDULED_FLOW` | `[60, 3600]` |

### 10.5 Strict mode

```yaml
# platform.yaml
enforce_trend_mechanism: true     # default false
```

When set, schema-1.1 SIGNAL/PORTFOLIO specs **missing** a
`trend_mechanism:` block are also rejected at load time. Recommended
once an operator has committed to the v0.3 mechanism contract — it
catches "drift back to v0.2" at load time rather than at promotion
review.

---

## 11. Deprecation timeline & sunset

| Phase | `schema_version: "1.0"` | `layer: LEGACY_SIGNAL` |
|---|---|---|
| Pre-D | accepted, **once-per-process WARNING** at load | accepted, **once-per-process WARNING** at load |
| **D.1** | **rejected at load** — `AlphaLoadError` pointing at this cookbook | accepted, **once-per-process WARNING** at load |
| **D.2 PR-1** | rejected (unchanged from D.1) | **rejected at load** — operators must promote LEGACY_SIGNAL alphas to `layer: SIGNAL` (or retire them) |
| **D.2 PR-2a** | rejected (unchanged) | rejected (unchanged); the leaf surfaces orphaned by PR-1's rejection — `LoadedAlphaModule`, `LegacyFeatureShim`, the loader's dead `_compile_signal` 2-arg compiler, and the `LayerValidator` G6/G8/G13 inline-features branches — are deleted from the codebase |
| **D.2 PR-2b-i** | rejected (unchanged) | rejected (unchanged); the orchestrator's `feature_engine` / `signal_engine` constructor parameters become **optional** (typed `... | None`) and bootstrap stops constructing the per-tick engines, leaving the legacy single-alpha pipeline reachable only when an engine is explicitly injected by a caller (tests). Production deployments boot with `feature_engine=None`, `signal_engine=None`, `multi_alpha_evaluator=None` and the M3/M4 micro-state transitions visit empty bodies |
| **D.2 PR-2b-ii** | rejected (unchanged) | rejected (unchanged); the per-tick engine classes themselves are deleted: `CompositeFeatureEngine`, `CompositeSignalEngine`, `MultiAlphaEvaluator`, the `FeatureEngine` and `SignalEngine` protocols, and their dedicated test files are removed. The orchestrator's `multi_alpha_evaluator` constructor parameter and its 348-line `_process_tick_multi_alpha` method body are dropped. `Signal.layer` is narrowed from `Literal["SIGNAL", "LEGACY_SIGNAL"]` to `Literal["SIGNAL", "PORTFOLIO"]` with default `"SIGNAL"`. `FeatureVector`, `AlphaModule.evaluate`, and the orchestrator's `feature_engine` / `signal_engine` constructor parameters survive only as test scaffolding (typed `Any | None`) |
| **D.2 PR-2b-iii (current)** | rejected (unchanged) | rejected (unchanged); the orchestrator gains a **bus-driven `Signal` subscriber** (`_on_bus_signal`) that buffers `Signal(layer="SIGNAL")` events per tick and translates them through the existing risk → order → fill pipeline at the M4 `SIGNAL_EVALUATE` drain.  This is the **first production-reachable Signal → Order path** — pre-PR-2b-iii nothing converted bus Signals into `OrderRequest` events because the only translator was the legacy `signal_engine`-gated branch which production never reached.  The subscriber filters out `__stop_exit__` synthetic signals and any `strategy_id` listed in some PORTFOLIO alpha's `depends_on_signals` (those route through `CompositionEngine` and emerge as `SizedPositionIntent`, to avoid double-trading per Inv-11).  The micro SM only allows one `RISK_CHECK → … → LOG_AND_METRICS` walk per tick, so when ≥2 standalone SIGNAL alphas fire on the same tick the orchestrator picks the first arrival deterministically and logs a once-per-process WARNING hinting that the operator should aggregate via a PORTFOLIO alpha.  `LoadedPortfolioLayerModule` now stores and exposes `depends_on_signals` (was parsed but discarded prior to this PR).  When both the legacy `signal_engine` stub and the bus buffer are wired the legacy stub takes precedence so existing kernel tests stay bit-identical (the bus buffer is still drained and discarded so it cannot leak into the next tick).  `tests/integration/test_phase4_e2e.py` adds a regression-guard assertion that locks the standalone-SIGNAL → `OrderRequest` invariant |
| **D.2 PR-2b-iv (current)** | rejected (unchanged) | rejected (unchanged); the orchestrator gains a second bus-driven subscriber, `_on_bus_sized_intent`, which receives `SizedPositionIntent` events emitted by `CompositionEngine`, calls `RiskEngine.check_sized_intent` (Inv-11 per-leg veto), hashes a deterministic `order_id` (Inv-5), and submits per-leg `OrderRequest` events through the existing backend.  Translation happens **outside** the per-tick micro state-machine walk so a single tick never processes two `RISK_CHECK → … → LOG_AND_METRICS` walks (mirrors the existing `_execute_reverse` pattern).  This closes the **second production-reachable Signal/Intent → Order path**: PORTFOLIO alphas now submit orders end-to-end.  With both production paths in place, PR-2b-iv then **deletes the surviving test scaffolding**: the `feature_engine` / `signal_engine` constructor parameters and their attribute assignments, the M3 `FEATURE_COMPUTE` body, the M4 legacy `signal_engine` branch (so M4 now drains exclusively from `_signal_buffer`), the `process_trade_fn` block, the orphan `_build_net_order` / `_compute_contributions` methods (only called by the deleted `MultiAlphaEvaluator`), and the `feature_engine` paths in `_restore/_checkpoint_feature_snapshots`.  The `FeatureVector` event class is deleted from `src/feelies/core/events.py`.  The `AlphaModule.evaluate` protocol method and its no-op overrides on `LoadedSignalLayerModule` / `LoadedPortfolioLayerModule` are deleted, along with `AlphaRegistry._smoke_test`.  All 29 stub-driven kernel tests in `tests/kernel/test_orchestrator.py` are migrated to publish `Signal` events on the bus through a `_publish_signal_on_quote` helper (`_StubFeatureEngine` / `_StubSignalEngine` / `_RaisingSignalEngine` deleted; the `_RaisingRiskEngine` newly added covers the post-PR-2b-iv "tick raises → DEGRADED" path).  `TestMultiAlphaB4Gate`, which called `_build_net_order` directly, is deleted — the B4 gate is still covered through the per-tick walk in `TestEdgeCostGate`.  Workstream D.2 is **COMPLETE** |

Recommended migration order for a portfolio of legacy alphas
(post-D.2):

1. **Promote, don't bridge.** The historical D.1-only step ("bump
   every `schema_version` to `"1.1"` and add `layer: LEGACY_SIGNAL`")
   no longer loads — the loader rejects `LEGACY_SIGNAL` outright.
2. **Per-alpha promotion**: for each legacy alpha where you can name a
   structural actor and compute cost arithmetic, follow §3 to promote
   it to a `layer: SIGNAL` spec. Author a sibling
   `<alpha_id>_v2.alpha.yaml`; preserve the v1 file under
   `alphas/_deprecated/` (mutation parity rules,
   `grok/prompts/mutation_protocol.md` §4).
3. **Cross-sectional**: once two or more SIGNAL alphas exist that you
   want to compose, author a PORTFOLIO alpha per §8.
4. **v0.3 opt-in**: add `trend_mechanism:` blocks per §10 once you can
   name the family, half-life, and L1 fingerprint sensors.
5. **Strict mode flip**: set
   `platform.yaml: enforce_trend_mechanism: true` once every
   active SIGNAL/PORTFOLIO alpha carries a `trend_mechanism:` block.

End of cookbook.
