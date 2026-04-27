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
> **Deprecation timeline:** see §12.

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
11. Per-alpha promotion overrides — `promotion.gate_thresholds:` (Workstream F-5)
11.bis. Capital-tier escalation — `LIVE @ SMALL_CAPITAL → LIVE @ SCALED` (Workstream F-6)
12. Deprecation timeline & sunset

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

## 11. Per-alpha promotion overrides — `promotion.gate_thresholds:` (Workstream F-5)

Workstream **F-5** introduces the optional `promotion:` block in
alpha YAML so per-alpha thresholds can override the platform default
`GateThresholds` consumed by `validate_gate(...)` at promotion time.
The block is **opt-in via field presence** — absent or empty
`promotion:` blocks preserve every prior behaviour bit-identically.

### 11.1 Layering precedence

Effective `GateThresholds` for an alpha at promotion time are the
result of three left-to-right merges (lowest → highest):

1. **Skill-pinned defaults.** `GateThresholds()` with the values
   pinned in
   [`src/feelies/alpha/promotion_evidence.py`](../../src/feelies/alpha/promotion_evidence.py)
   (mirroring the testing-validation and post-trade-forensics skill
   thresholds, e.g. `paper_min_trading_days=5`,
   `cpcv_min_folds=8`, `dsr_min=1.0`).
2. **`platform.yaml: gate_thresholds:`** — operator-wide overrides
   parsed by `PlatformConfig.from_yaml` and applied at bootstrap by
   `_build_platform_gate_thresholds(config)`. The result is passed
   to `AlphaRegistry.__init__(gate_thresholds=...)`.
3. **`promotion.gate_thresholds:`** in the alpha YAML — per-alpha
   overrides parsed by `AlphaLoader._parse_promotion_block`, stored
   on `AlphaManifest.gate_thresholds_overrides`, and applied on top
   of (2) inside `AlphaRegistry._resolve_gate_thresholds` when the
   alpha's `AlphaLifecycle` is constructed.

The merge is non-mutating: each layer's overrides materialise a new
`GateThresholds` instance via `dataclasses.replace`, so the
upstream layers remain available for inspection.

### 11.2 YAML grammar

```yaml
promotion:
  gate_thresholds:
    paper_min_trading_days: 7         # default 5  — longer paper window
    dsr_min: 1.2                      # default 1.0 — stricter DSR floor
    cpcv_min_mean_sharpe: 1.2         # default 1.0 — stricter CPCV bar
    revalidation_min_oos_sharpe: 1.5  # default 1.0 — re-promotion harder
```

Validation rules at load time (raise `AlphaLoadError` with the alpha
spec path and a structural message):

1. `promotion:` must be a mapping (not a scalar or list).
2. The only supported sub-key is `gate_thresholds:`. Other keys
   (e.g. `promotion.notes:`) raise `AlphaLoadError` listing the
   offending keys.
3. `gate_thresholds:` must be a mapping; an empty mapping is
   treated as "no overrides" and yields
   `manifest.gate_thresholds_overrides=None`.
4. Every key must name a real `GateThresholds` field.  Unknown
   keys raise `AlphaLoadError` listing the valid field names.
5. Every value must match the field's declared type
   (`int` / `float` / `bool`).  Booleans are *not* coerced to
   `int`; strings are *not* parsed as numbers.

### 11.3 Platform-wide overrides

The same field/type/coercion validation is applied to a top-level
`gate_thresholds:` block in `platform.yaml`:

```yaml
# platform.yaml
gate_thresholds:
  paper_min_trading_days: 5     # accept the platform default explicitly
  dsr_min: 1.1                  # tighten DSR floor for every alpha
```

Empty / absent block ⇒ `PlatformConfig.gate_thresholds_overrides`
is `{}` and `_build_platform_gate_thresholds(config)` returns
`None`, so the registry's base is the skill defaults.

### 11.4 Cross-field invariants

The override layer performs only **structural** validation
(field-name existence + scalar type).  Cross-field invariants
(e.g. `paper_min_pnl_compression_ratio ≤ paper_max_pnl_compression_ratio`,
or family-specific consistency rules) are deferred to the
F-2 validators inside
[`src/feelies/alpha/promotion_evidence.py`](../../src/feelies/alpha/promotion_evidence.py).
That keeps the loader simple and keeps the override surface
identical regardless of where the keys are sourced from
(`platform.yaml` vs. per-alpha YAML).

### 11.5 Worked example — research-grade alpha with stricter DSR

```yaml
# alphas/my_research_alpha.alpha.yaml
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_research_alpha
# … rest of the SIGNAL spec …

promotion:
  gate_thresholds:
    # research-grade alpha — require a stronger DSR before paper
    dsr_min: 1.5
    # require CPCV mean Sharpe ≥ 1.2 (vs platform default 1.0)
    cpcv_min_mean_sharpe: 1.2
    # require 10-day PAPER window (vs default 5)
    paper_min_trading_days: 10
```

At promotion time, the lifecycle dispatches to
`validate_gate(GateId.PAPER_TO_LIVE, evs, gate_thresholds)` with the
**merged** `GateThresholds` carrying the platform defaults overlaid
by these three keys.  All other thresholds remain at the platform
value (or skill default if no platform override applies).

### 11.6 Forensic-only writer contract preserved

Workstream F-5 adds **no** new code paths that read the merged
thresholds at runtime — `AlphaLifecycle.promote_*` already consumed
`GateThresholds` from F-4.  The only change is in *how* the
lifecycle's `GateThresholds` instance is constructed (now via the
three-layer merge instead of the one-layer registry pin).  Replay
determinism (audit A-DET-02) is unaffected because the merge runs
once at registration time and the resulting `GateThresholds` is
immutable for the alpha's lifetime.

---

## 11.bis. Capital-tier escalation — `LIVE @ SMALL_CAPITAL → LIVE @ SCALED` (Workstream F-6)

Workstream **F-6** closes the strategy-promotion pipeline by wiring
the LIVE @ SMALL_CAPITAL → LIVE @ SCALED capital-tier escalation as
a **state-machine self-loop** on `AlphaLifecycle`.  The lifecycle
state stays LIVE; only the alpha's capital-stage tier flips.  The
escalation is recorded as a `LIVE -> LIVE` entry on the F-1
promotion ledger whose `trigger == "promote_capital_tier"`
distinguishes it from the LIVE -> QUARANTINED demotion (both share
`from_state == "LIVE"`).  The 5-state lifecycle machine is unchanged
— Inv-13 (provenance) is satisfied without inflating it to 6 states.

### 11.bis.1 The new method

```python
from feelies.alpha.promotion_evidence import (
    CapitalStageEvidence,
    CapitalStageTier,
)

evidence = CapitalStageEvidence(
    tier=CapitalStageTier.SMALL_CAPITAL,   # the *outgoing* tier
    allocation_fraction=0.01,              # 1 % of target during window
    deployment_days=12,                    # ≥ small_min_deployment_days
    pnl_compression_ratio_realised=0.85,   # within [0.5, 1.0] band
    slippage_residual_bps=1.0,             # ≤ 2.5 bps default ceiling
    hit_rate_residual_pp=-2.0,             # ≥ -5 pp default floor
    fill_rate_drift_pct=3.0,               # within ±10 % default band
)

errors = registry.promote_capital_tier(
    "kyle_info_v2",
    evidence,
    correlation_id="cap-2026-01-15",
)
assert errors == []   # gate passed; tier flipped to SCALED
```

`AlphaLifecycle.promote_capital_tier(evidence, *, correlation_id="")`
and `AlphaRegistry.promote_capital_tier(alpha_id, evidence, *,
correlation_id="")` are the two entry points.  Both dispatch
`validate_gate(GateId.LIVE_PROMOTE_CAPITAL_TIER, [evidence],
gate_thresholds)` against the per-alpha resolved `GateThresholds`
(the §11 three-layer merge), so an alpha with stricter or looser
SCALED criteria can override them in its `promotion: {
gate_thresholds: ... }` block without affecting any other alpha.

### 11.bis.2 Pre/post-conditions

| Condition | Behaviour |
|---|---|
| Lifecycle state must be `LIVE` | Otherwise returns `["…requires state=LIVE; current state is …"]`; no ledger entry. |
| Current tier must be `SMALL_CAPITAL` | A second call after a prior SCALED escalation returns `["…tier=SCALED; no further escalation defined"]`; no ledger entry. |
| `evidence.tier` field must be `SMALL_CAPITAL` | The validator reads the *outgoing* tier; passing `SCALED` is a configuration error. |
| Validator failures | Returned as `list[str]` like the other promotion methods; no ledger entry, no state change. |
| Validator success | One `LIVE -> LIVE` ledger entry, `trigger == "promote_capital_tier"`, metadata = `evidence_to_metadata(evidence)`; tier flips to `SCALED`. |
| Quarantine after SCALED | The next `LIVE -> QUARANTINED` entry uses the existing demotion path; tier returns to `None`.  Quarantine + revalidate + re-promote starts a **new** LIVE epoch that resets to `SMALL_CAPITAL` (the prior epoch's SCALED escalation does not bleed forward — operators must re-justify). |

### 11.bis.3 New `current_capital_tier` property

`AlphaLifecycle.current_capital_tier: CapitalStageTier | None`
returns `None` for non-LIVE states, `SCALED` if the current LIVE
epoch contains a `promote_capital_tier` self-loop, and
`SMALL_CAPITAL` otherwise.  The property scans `history` backwards
from the most recent record to the most recent transition *into*
LIVE so it agrees with the F-1 ledger contents byte-for-byte (the
operator CLI uses the same algorithm to render the tier on
`feelies promote inspect / list`, see §11.bis.4).

### 11.bis.4 Operator CLI surfaces

The F-3 `feelies promote` CLI was extended in three places:

* `feelies promote inspect <alpha_id>` renders a `tier=SCALED` /
  `tier=SMALL_CAPITAL` suffix in the per-alpha header and formats
  the self-loop arrow as `LIVE @ SMALL_CAPITAL -> LIVE @ SCALED` so
  operators don't have to read the metadata blob.  JSON output
  carries a top-level `current_capital_tier` field.
* `feelies promote list` renders the state column as `LIVE @ <tier>`
  for live alphas (text + JSON `current_capital_tier` field).
* `feelies promote replay-evidence <alpha_id>` infers
  `GateId.LIVE_PROMOTE_CAPITAL_TIER` for `("LIVE", "LIVE")`
  transitions with trigger `promote_capital_tier` and validates the
  round-tripped `CapitalStageEvidence` against today's thresholds.
  Failed replays surface as exit code 3 (`EXIT_VALIDATION_FAILED`)
  exactly like the other gates.

### 11.bis.5 Wire-format symbol location

The trigger string `PROMOTE_CAPITAL_TIER_TRIGGER = "promote_capital_tier"`
lives in
[`src/feelies/alpha/promotion_evidence.py`](../../src/feelies/alpha/promotion_evidence.py)
(re-exported from `feelies.alpha`) rather than in
`feelies.alpha.lifecycle` so the wire-format symbol is shared
between writer (lifecycle) and readers (CLI / forensics) without
re-introducing a layering edge — the CLI must not import
`feelies.alpha.lifecycle` (forensic-only consumer contract).

### 11.bis.6 Backwards compatibility

Alphas that never call `promote_capital_tier` continue to pass
through the existing 5-state machine without writing self-loop
entries — the `LIVE` state's transition set now contains both
`LIVE` and `QUARANTINED`, but no caller is forced to produce a
self-loop.  Existing legacy `PromotionEvidence` consumers
(`promote_to_paper` / `promote_to_live` / `revalidate_to_paper`)
are entirely untouched, and the F-3 CLI continues to handle
ledgers that contain no self-loop entries (the helpers fall back
to `current_capital_tier=None` cleanly when no LIVE entry has been
recorded).

---

## 12. Deprecation timeline & sunset

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
