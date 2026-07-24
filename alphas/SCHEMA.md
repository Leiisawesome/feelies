# Alpha Spec Schema Reference

> **Acceptance status.** Schema-level invariants enforced by this
> document (`margin_ratio` floors, `trend_mechanism` G16 binding
> rules, factor-exposure tolerances, `enforce_trend_mechanism`
> strict-mode behaviour) are asserted in `tests/acceptance/`.

> **Workstream D.1 (schema 1.0 hard-removal).** `schema_version: "1.0"`
> is no longer accepted by the loader; the only supported value is
> `"1.1"`, and `schema_version:` is now mandatory.
>
> **Workstream D.2 (LEGACY_SIGNAL retirement).** `layer: LEGACY_SIGNAL`
> is no longer accepted by the loader. The per-tick legacy execution
> path was retired; alphas must declare `layer: SIGNAL`
> (horizon-anchored, regime-gated, cost-aware) or `layer: PORTFOLIO`
> (cross-sectional construction).

## Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | **Yes** | Schema version.  Only `"1.1"` is accepted (workstream D.1).  Legacy `"1.0"` specs and missing-version specs are rejected outright. |
| `alpha_id` | string | Yes | Unique identifier. Must match `^[a-z][a-z0-9_]*$`. |
| `version` | string | Yes | Semver string (e.g. `"1.0.0"`). Must match `^\d+\.\d+\.\d+$`. |
| `description` | string | Yes | Human-readable description of the alpha. |
| `hypothesis` | string | Yes | Structural mechanism exploited (Inv-1). |
| `falsification_criteria` | list[string] | Yes | What would disprove the hypothesis (Inv-2). |
| `symbols` | list[string] | No | Restrict to specific symbols. Omit for all. |
| `parameters` | dict | No | Parameter definitions (see below). |
| `risk_budget` | dict | No | Per-alpha risk limits (see below). |
| `features` | dict or list | Yes | Feature definitions (see below). |
| `signal` | string | Yes | Python code defining `evaluate(features, params)`. |

## Parameters

Each parameter is a dict keyed by name:

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | Yes | `int`, `float`, `str`, `bool` |
| `default` | any | Yes | Default value. |
| `min` | number | No | Minimum bound (numeric types). |
| `max` | number | No | Maximum bound (numeric types). |
| `description` | string | No | Human-readable description. |

## Risk Budget

| Field | Type | Default | Constraints |
|---|---|---|---|
| `max_position_per_symbol` | int | 100 | Must be > 0 |
| `max_gross_exposure_pct` | float | 5.0 | Must be in (0, 100] |
| `max_drawdown_pct` | float | 1.0 | Must be in (0, 100] |
| `capital_allocation_pct` | float | 10.0 | Must be in (0, 100] |

## Features

Features can be specified as a dict (keyed by feature_id) or a list of dicts with `feature_id` field.

| Field | Type | Required | Description |
|---|---|---|---|
| `feature_id` | string | Yes (list form) | Unique feature identifier. |
| `computation` | string | Yes* | Inline Python defining `initial_state()` and `update(quote, state, params)`. |
| `computation_module` | string | Yes* | Path to external `.py` file (relative to alpha directory). |
| `warm_up.min_events` | int | No | Minimum events before feature is warm. |
| `warm_up.min_duration_ns` | int | No | Minimum elapsed nanoseconds. |
| `depends_on` | list[string] | No | Upstream feature_ids (for dependency ordering). |
| `version` | string | No | Feature version (default `"1.0.0"`). |
| `return_type` | string | No | `"float"` (default) or `"list[N]"` for compound features. |

*One of `computation` or `computation_module` is required.

### Computation Functions

The `computation` code (or module) must define:

- `initial_state() -> dict` — returns initial mutable state (0 required args)
- `update(quote, state, params) -> float` — returns feature value (3 required args)
- `update_trade(trade, state, params) -> float | None` — optional trade handler (3 required args)

## Signal

The `signal` code must define:

- `evaluate(features, params) -> Signal | None` — returns a Signal or None (2 required args)

Available in signal namespace: `Signal`, `SignalDirection`, `LONG`, `SHORT`, `FLAT`, `alpha_id`.

## Directory Layout

Alphas can be placed in either layout:

- **Flat:** `alphas/my_alpha.alpha.yaml`
- **Nested:** `alphas/my_alpha/my_alpha.alpha.yaml` (supports `computation_module` references)

---

## Schema 1.1 (Three-Layer)

> **Status: `SIGNAL` + `PORTFOLIO` accepted (Phase 3-α + Phase 3.1 + Phase 4 + Phase 4.1). `LEGACY_SIGNAL` retired (Workstream D.2). `SENSOR` reserved (Phase 5).**
>
> As of Workstream D.2, `schema_version: "1.1"` accepts:
>
> - `layer: SIGNAL` — horizon-anchored, regime-gated, optional v0.3 `trend_mechanism:` block enforced by G16 (Phase 3-α + Phase 3.1).
> - `layer: PORTFOLIO` — cross-sectional alpha consuming
>   `CrossSectionalContext` and emitting `SizedPositionIntent`. Must
>   declare `universe`, `depends_on_signals`, `factor_neutralization`,
>   and `cost_arithmetic`. Risk decomposition (per-leg veto) is
>   handled by `RiskEngine.check_sized_intent`. Optional
>   `decay_weighting_enabled: true` parameter enables
>   inverse-staleness reweighting (Phase 4.1). Optional `hazard_exit:
>   {enabled: true, ...}` block wires `HazardExitController` for
>   hazard-spike-driven exits and a hard-exit age cap (Phase 4.1).
> - `layer: LEGACY_SIGNAL` is rejected with a workstream-D.2 retirement
>   error pointing at the migration cookbook.
> - `layer: SENSOR` is still rejected with a "Phase 5 not yet
>   implemented" error.
>
> As of Phase 3.1, the v0.3 `trend_mechanism:` block is **enforced by
> gate G16** for any `SIGNAL`/`PORTFOLIO` alpha that declares one (see
> [`docs/three_layer_architecture.md`](../docs/three_layer_architecture.md)
> §20.6). **Strict mode is the platform default since Workstream E**
> (acceptance row 84): schema-1.1 `SIGNAL`/`PORTFOLIO` specs *missing*
> a `trend_mechanism:` block are rejected at load time unless the
> operator explicitly pins `enforce_trend_mechanism: false` in
> `platform.yaml` (the documented v0.2 escape hatch). Four reference
> alphas covering the non-stress families ship in this slice
> (`sig_hawkes_burst_v1`, `sig_kyle_drift_v1`,
> `sig_inventory_revert_v1`, `sig_moc_imbalance_v1`); the
> `LIQUIDITY_STRESS` family is enforced **exit-only** — a stress-family
> alpha may not emit an entry-direction `Signal`. See §20.10 (v0.3
> Phased Delivery) for the full timeline.

### Top-level fields added in 1.1

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | Yes | Set to `"1.1"`. Schema 1.0 was hard-removed in Workstream D.1. |
| `layer` | string | Yes | Dispatch key. One of `SIGNAL`, `PORTFOLIO`, `SENSOR`. The historical value `LEGACY_SIGNAL` is rejected with a workstream-D.2 retirement error; `SENSOR` is reserved for Phase 5. |
| `horizon_seconds` | int | No (Phase 3) | Decision-horizon for `SIGNAL` and `PORTFOLIO` alphas. Must be a registered horizon (Phase 3). |
| `cost_arithmetic` | string | No (Phase 3) | Declares whether edge / cost are quoted in `bps` or `usd`. Phase-3 gate G12 will require this on all non-legacy alphas. |
| `regime_gate` | string | No (Phase 3) | DSL expression over regime posteriors (e.g. `dominant == "compression" and P("vol_breakout") < 0.2`). Evaluated at the horizon boundary. |
| `depends_on_sensors` | list[string] | No (Phase 2/3) | Sensor IDs (with version pin) consumed by this alpha. |
| `depends_on_signals` | list[string] | No (Phase 4) | Upstream `SIGNAL` alphas consumed by a `PORTFOLIO` alpha. |
| `structural_actor` | string | No (Phase 3) | Free-text description of the actor whose behavior the alpha trades against. |
| `mechanism` | string | No (Phase 3) | Free-text mechanism summary; complementary to the v0.3 `trend_mechanism` block below. |
| `trend_mechanism` | dict | No (Phase 1.1 parsed, Phase 3.1 enforced) | v0.3 mechanism descriptor, see below. |
| `hazard_exit` | dict | No (Phase 1.1 parsed, Phase 4.1 enforced) | v0.3 hazard-rate exit policy, see below. |
| `promotion` | dict | No (Workstream F-5) | Per-alpha override of the platform `GateThresholds` used by `validate_gate(...)` at promotion time, see below. |
| `lifecycle_state` | string | No (BT-13) | Only `"RESEARCH"` is accepted. Caps the alpha at RESEARCH — blocks PAPER/LIVE promotion — while it still loads for backtest/integration use, see below. |

### `trend_mechanism:` block (v0.3, §20.5)

Optional mechanism descriptor for `SIGNAL`-layer alphas. **Opt-in via
field presence** — absent block ⇒ no enforcement. When present in
Phase 1.1, the loader checks only that `family:` belongs to the closed
taxonomy:

| `family:` value | Description |
|---|---|
| `KYLE_INFO` | Informed-trader price-impact (Kyle 1985). |
| `INVENTORY` | Market-maker inventory drift. |
| `HAWKES_SELF_EXCITE` | Self-exciting order-flow cluster. |
| `LIQUIDITY_STRESS` | Depth withdrawal / spread blow-out. |
| `SCHEDULED_FLOW` | Known time-of-day flow window. |

Adding a new family is a deliberate platform-level change (modify
`feelies.core.events.TrendMechanism` and
`feelies.alpha.loader._TREND_MECHANISM_FAMILIES` together). Per-family
parameter constraints (decay curves, regime predicates, feature
whitelists) are documented in §20.6 of the design doc and will be
enforced by gate G16 (raised as
`feelies.alpha.layer_validator.TrendMechanismValidationError`) in
Phase 3.1.

### `hazard_exit:` block (v0.3, §20.5)

Optional hazard-rate-driven exit policy for `SIGNAL`- or
`PORTFOLIO`-layer alphas. **Opt-in via field presence**. Phase 1.1
only checks that the block is a mapping; field-level enforcement is
deferred to Phase 4.1 when the composition layer activates
hazard-rate exits via `RegimeHazardSpike` events.

### `safety_exit_policy:` block (Stage-0 dual-permission actuation, design rev 5)

Optional, `SIGNAL`-layer only. **Opt-in via field presence** — an absent
block is the default `gate_close_flat` behaviour: the SIGNAL engine flattens
an open book *immediately* on the clean regime-gate ON→OFF transition, exactly
as today (bit-identical).

The block decouples *"no new exposure"* (the gate's safety meaning, which
still blocks entries autonomously) from *"flatten this open book now"* (an
actuation policy). Under `decouple_caps_only`, the clean gate-OFF FLAT becomes
a **bounded deferral**: the open book may be held, but only until the earliest
of the declared ceilings, after which a risk-layer author forces the exit.

```yaml
safety_exit_policy:
  mode: gate_close_flat | decouple_caps_only   # default: gate_close_flat
  max_hold_after_safe_off: <positive_seconds>  # REQUIRED when mode = decouple_caps_only
  hard_exit_age_seconds: <positive_seconds>    # REQUIRED when mode = decouple_caps_only
```

| Field | Type | Rule |
|---|---|---|
| `mode` | string | `gate_close_flat` (default) or `decouple_caps_only`. |
| `max_hold_after_safe_off` | int seconds > 0 | The deferral ceiling, measured from the episode's **first** `safe→OFF` (monotonic — a gate flicker never re-anchors it). Mandatory under `decouple_caps_only`; turns "no immediate flatten" into a *bounded delay*, never a removal. |
| `hard_exit_age_seconds` | int seconds > 0 | The monotonic position-age backstop, measured from open. Mandatory under `decouple_caps_only`; holds even if the first-safe-OFF anchor is mis-derived. |

Parsing (structural) lives in `AlphaLoader._parse_safety_exit_policy_block`
([`src/feelies/alpha/loader.py`](../src/feelies/alpha/loader.py)); it rejects
an unknown `mode`, a non-positive ceiling, and — under `decouple_caps_only` — a
**missing** `max_hold_after_safe_off` or `hard_exit_age_seconds` (design §3.6:
"Stage 0 without either ceiling → reject load"). The normalized block is stored
verbatim on `AlphaManifest.safety_exit_policy`; a `decouple_caps_only` module
also carries `LoadedSignalLayerModule.decouple_gate_close = True`.

The cross-block and cross-alpha invariants are gate **G17** (below).

An optional Stage-1 `story_permission:` block (a positive hold-desire map) is
**deferred** — do not author it yet — but the load-time coupling is already
enforced: `story_permission` present ⇒ `mode` must be `decouple_caps_only`
(a story map while the gate still auto-flattens is contradictory, §3.4).

### Architectural gates

| Gate | Status | Description |
|---|---|---|
| G1 | **Active** (Phase 4) | Layer independence — `SIGNAL` may not import PORTFOLIO modules; `PORTFOLIO` may not bypass `RiskEngine`. Downgradable to a warning via `PlatformConfig.enforce_layer_gates: false` (research escape hatch); always blocks in strict mode. |
| G2 | **Active** (Phase 3-α) | Event typing — `signal:` code must be a string, no inline objects, no module-level side effects. |
| G3 | **Active** (Phase 4) | Strict cross-alpha isolation — a PORTFOLIO alpha's `depends_on_signals` may not reference signals at a different `horizon_seconds`. Downgradable to a warning via `PlatformConfig.enforce_layer_gates: false`; always blocks in strict mode. |
| G4 | **Active** (Phase 3-α) | Regime-gate purity — `regime_gate.on/off_condition` must parse as a whitelisted DSL expression (`RegimeGate.compile`). |
| G5 | **Active** (Phase 3-α) | Signal purity — `signal:` evaluate must not import, mutate globals, call `open`/network/clock, or read state outside `(snapshot, regime, params)`. |
| G6 | **Active** (Phase 3-α) | Feature/sensor dependency DAG — every entry in `depends_on_sensors` must resolve to a registered sensor; no unknown ids; no cycles. |
| G7 | **Active** (Phase 3-α) | Horizon registration — `horizon_seconds` must be one of the platform-registered horizons. |
| G8 | **Active** (Phase 3-α) | No implicit lookahead — AST-scan rejects access to future-bucketed names. |
| G9 | **Active** (Phase 4) | Cross-symbol staleness checks — `CrossSectionalContext.completeness` must clear the per-platform `composition_completeness_threshold` (default `0.7`) for the boundary to produce a `SizedPositionIntent`. Always blocks (data-integrity gate; not affected by `enforce_layer_gates`). |
| G10 | **Active** (Phase 4) | PORTFOLIO `universe:` presence + scale cap — every PORTFOLIO alpha must declare a non-empty `universe:` list and the universe size must be ≤ `composition_max_universe_size` (v0.2 cap = 50 symbols). Always blocks. |
| G11 | **Active** (Phase 4) | PORTFOLIO `factor_neutralization:` disclosure — every PORTFOLIO alpha must declare `factor_neutralization: true` (or list explicit excluded factor IDs). Reference factor loadings under `src/feelies/storage/reference/factor_loadings/` (or the path set in `PlatformConfig.factor_loadings_dir`) must exist and not exceed `factor_loadings_max_age_seconds`; missing or stale loadings raise `StaleFactorLoadingsError` at bootstrap. Always blocks. |
| G12 | **Active** (Phase 3-α) | Cost-arithmetic disclosure — `cost_arithmetic` block required, `margin_ratio >= 1.5`, components reconcile within ±0.05 absolute on the ratio (`src/feelies/alpha/cost_arithmetic.py`). |
| G13 | **Active** (Phase 3-α) | Warm-up documentation — `SIGNAL` inherits warm-up from sensor warm-up by construction; the inline-features warm-up branch is unreachable post-D.2 (the loader rejects `LEGACY_SIGNAL` before validation). |
| G14 | **Active** (Phase 1) | Alpha must declare no data dependency outside L1 NBBO + trades + reference data + session calendar. |
| G15 | **Active** (Phase 1) | Declared `fill_model.router` must name a platform-supported router (`PassiveLimitOrderRouter` or `BacktestOrderRouter`). |
| G16 | **Active** (Phase 3.1) | Mechanism-horizon binding — when a `schema_version: "1.1"` SIGNAL/PORTFOLIO alpha declares a `trend_mechanism:` block, validates: (1) `family` ∈ closed taxonomy; (2) `expected_half_life_seconds` ∈ per-family envelope; (3) `horizon_seconds / expected_half_life_seconds` ∈ `[0.5, 4.0]`; (4) every entry in `l1_signature_sensors` is a registered sensor; (5) the family's primary fingerprint sensor is among them; (6) `failure_signature` declared; (7) `LIQUIDITY_STRESS` mechanisms emit no entry-direction `Signal` (AST-checked); (8) PORTFOLIO `trend_mechanism.consumes.max_share_of_gross` summation; (9) PORTFOLIO `depends_on_signals` family whitelist. **Strict mode is the platform default since Workstream E** (`platform.yaml: enforce_trend_mechanism: true`, default `true`) — schema-1.1 SIGNAL/PORTFOLIO specs *missing* a `trend_mechanism:` block are rejected at load time unless the operator explicitly pins `enforce_trend_mechanism: false`. |
| G17 | **Active** (Phase 4) | Stage-0 dual-permission actuation (`safety_exit_policy:` / `story_permission:`) — always blocking (safety-critical, Inv-11; not `enforce_layer_gates`-downgradable). Cross-block, single-spec: (1) both blocks are `SIGNAL`-layer only; (2) `story_permission` present ⇒ `mode = decouple_caps_only`; (3) `decouple_caps_only` requires a `trend_mechanism:` with a known `family` and positive `expected_half_life_seconds` (the deferral ceiling is bounded by the family envelope); (4) `max_hold_after_safe_off ≤` per-family multiple × `expected_half_life_seconds` (`_FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE`: KYLE_INFO 3×, INVENTORY 1×, HAWKES_SELF_EXCITE 1×, LIQUIDITY_STRESS 2×, SCHEDULED_FLOW 2×; §2.8). The structural checks (`mode` enum, both ceilings present + positive under decouple) are the loader's (`_parse_safety_exit_policy_block`). A **cross-alpha** companion, `validate_decouple_symbol_scope` (called at load from `bootstrap._enforce_decouple_symbol_scope`), rejects a `decouple_caps_only` alpha that shares a symbol with another strategy **when the decoupling backstop is symbol-net** (single-strategy-per-symbol otherwise); this platform's backstop is strategy-slice-scoped, so a shared symbol is safe. |

### Phase-2 status (Sensor layer + Horizon scheduler shipped)

As of Phase 2 + Phase 2.1, the platform exposes a complete L1 sensor
catalog and horizon-aware feature scaffolding, but alpha specs are
**not yet required** to consume any of it:

- `depends_on_sensors:` is now meaningfully populated from
  `feelies.sensors.registry.SensorRegistry`. The 13 catalog sensors
  shipped in v0.3 are:
  - **P2-β simple** (4): `ofi_ewma`, `micro_price`, `spread_z_30d`,
    `realized_vol_30s`.
  - **P2-γ complex** (5): `vpin_50bucket`, `kyle_lambda_60s`,
    `quote_hazard_rate`, `quote_replenish_asymmetry`,
    `trade_through_rate`.
  - **P2.1 v0.3 mechanism fingerprints** (4): `hawkes_intensity`,
    `scheduled_flow_window`, `snr_drift_diffusion`,
    `structural_break_score`.
- `HorizonScheduler` emits `HorizonTick` events at deterministic
  event-time boundaries (`session_open_ns + k * horizon_seconds * 1e9`)
  for every horizon configured under `platform.horizons_seconds`.
  Schedulers and the registry use *isolated* sequence generators so
  Phase-2 wiring cannot perturb the locked Level-1 fill sequence
  (Inv-A / C1).
- `HorizonAggregator` runs in **passive emitter** mode in Phase 2:
  it publishes `HorizonFeatureSnapshot` events with empty
  ``values``/``warm``/``stale`` dicts so downstream consumers can be
  built and tested against a stable contract before Phase 3 wires
  concrete `HorizonFeature` implementations.
- The `scheduled_flow_window` sensor reads
  ``src/feelies/storage/reference/event_calendar/<date>.yaml`` (or any path passed via `PlatformConfig.event_calendar_path`); the calendar's
  `EventCalendar.hash()` is folded into the bootstrap provenance
  bundle (Inv-13).

Phase-2 wiring is purely additive — enabling sensors, horizons, or
the aggregator does not affect any existing event sequence (Inv-A).
The historical `LEGACY_SIGNAL` parity hash this clause originally
guarded was retired with the per-tick legacy path in Workstream D.2;
the same isolation guarantees now apply to the SIGNAL-only fast-path.
Mechanism-binding enforcement (Gate G16) and active aggregation of
`HorizonFeature` implementations land in Phase 3.

### Phase-3-α status (SIGNAL layer live)

As of Phase 3-α, the `SIGNAL` layer is fully live and is the canonical
Layer-2 contract:

- `layer: SIGNAL` alphas are loaded by `AlphaLoader._load_signal_layer`
  and registered as `LoadedSignalLayerModule`. Their `evaluate` does
  not participate in `CompositeSignalEngine`; they are driven by the
  new `HorizonSignalEngine` instead.
- `HorizonSignalEngine` subscribes to `HorizonFeatureSnapshot`,
  `RegimeState`, and `SensorReading`, applies the alpha's compiled
  `regime_gate`, and emits `Signal(layer="SIGNAL", regime_gate_state,
  horizon_seconds, consumed_features, ...)` via a dedicated
  `_signal_seq` `SequenceGenerator` (Inv-A / C1 isolation).
- Every `SIGNAL`-layer alpha must declare `horizon_seconds`,
  `depends_on_sensors`, `regime_gate.on_condition` /
  `off_condition`, `cost_arithmetic`, and a `signal: |` block whose
  `evaluate(snapshot, regime, params)` is parsed and validated by
  gates G2–G13 at load time.
- The reference alpha
  [`alphas/sig_benign_midcap_v1`](sig_benign_midcap_v1/) ships as
  the canonical Phase-3 example. Its Level-2 SIGNAL parity hash is
  locked in `tests/determinism/test_signal_replay.py`. Drift in
  ordering, scope, or sequence allocation surfaces as a baseline
  failure on the next CI run.
- `scripts/run_backtest.py --emit-signals-jsonl` dumps every emitted
  `Signal` to stdout under prefix `SIGNAL_JSONL`; post-D.2 every row
  carries `layer="SIGNAL"`.
- Gates G2, G4–G8, G12, G13 are **active** — see the Architectural
  gates table above. Gate G16 (mechanism-horizon binding) remains
  scaffolded; it flips active in Phase 3.1 alongside the v0.3
  reference alphas.

### Phase-3.1 status (mechanism-horizon binding ACTIVE)

As of Phase 3.1, the v0.3 mechanism-horizon contract is enforced and
four reference alphas exercise the four non-stress families:

- **Gate G16 is ACTIVE** for any `schema_version: "1.1"`
  `SIGNAL`/`PORTFOLIO` spec that declares a `trend_mechanism:` block.
  See the Architectural gates table for the nine binding rules. v0.2
  `SIGNAL` specs without a `trend_mechanism:` block continue to load
  (G16 is opt-in via field presence, unless strict mode is enabled).
  The historical `LEGACY_SIGNAL`-exempt branch is moot post-D.2: the
  loader rejects `LEGACY_SIGNAL` before any gate runs.
- **Strict mode (`platform.yaml: enforce_trend_mechanism: true`,
  default `true` since Workstream E, acceptance row 84)** rejects
  any schema-1.1 `SIGNAL`/`PORTFOLIO` spec *missing* a
  `trend_mechanism:` block at load time. Operators staying on a v0.2
  baseline alpha (e.g. `sig_benign_midcap_v1`) must pin
  `enforce_trend_mechanism: false` explicitly. This is the
  recommended setting once an operator has committed to the
  v0.3 mechanism contract; it catches "drift back to v0.2" at load
  time rather than at promotion review.
- **Reference alphas (one per non-stress family):**
  - [`alphas/sig_hawkes_burst_v1`](sig_hawkes_burst_v1/) —
    `HAWKES_SELF_EXCITE`, 30 s horizon, hazard-exit enabled.
  - [`alphas/sig_kyle_drift_v1`](sig_kyle_drift_v1/) — `KYLE_INFO`,
    300 s horizon, slow drift on informed-trader price impact.
  - [`alphas/sig_inventory_revert_v1`](sig_inventory_revert_v1/) —
    `INVENTORY`, 30 s horizon, contrarian on quote-replenish
    asymmetry (`abs(zscore) > 2.0`).
  - [`alphas/sig_moc_imbalance_v1`](sig_moc_imbalance_v1/) —
    `SCHEDULED_FLOW`, 120 s horizon, MOC-window flow tracking via the
    tuple-valued `scheduled_flow_window` sensor (component-expanded
    by `HorizonSignalEngine`).
- **`LIQUIDITY_STRESS` is enforced exit-only.** Gate G16 rule 7
  AST-scans every stress-family alpha's `signal:` body and rejects
  any code path that can return a `LONG`/`SHORT` `Signal`. Stress
  alphas may only emit `FLAT` (close-position) signals.
- **`Signal` event metadata is propagated end-to-end.** Every
  `Signal` emitted by `HorizonSignalEngine` carries
  `Signal.trend_mechanism: TrendMechanism | None` and
  `Signal.expected_half_life_seconds: int` so post-trade forensics,
  regime-overlay attribution, and crowding diagnostics can group
  realized PnL by mechanism family without re-parsing alpha YAML at
  attribution time.
- **`RegimeHazardSpike` events** are emitted by
  `RegimeHazardDetector` (wired behind the alpha-level
  `hazard_exit.enabled: true` flag, default off) when a regime
  posterior shows a significant departure episode. Suppression is
  per `(symbol, engine_name, departing_state)` transition — at most
  one spike per departure; re-arms only when a different state
  becomes dominant or the departing posterior recovers above the
  `1.0 − hysteresis_threshold` floor.
- **Tuple-valued sensors** (currently `scheduled_flow_window`) are
  fanned out into per-component scalar entries in the
  `HorizonSignalEngine` sensor cache via an explicit static mapping
  (`_TUPLE_SENSOR_COMPONENTS`), so the scalar-only `RegimeGate` DSL
  can reference `scheduled_flow_window_active`,
  `seconds_to_window_close`, etc. directly.
- `scripts/run_backtest.py --emit-hazard-spikes-jsonl` dumps every
  emitted `RegimeHazardSpike` to stdout under prefix `HAZARD_JSONL`,
  composable with the prior `--emit-{sensor-readings,horizon-ticks,
  snapshots,signals}-jsonl` flags. The Level-5 hazard parity hash
  baseline lives in `tests/determinism/test_regime_hazard_replay.py`.

### Phase-4 status (PORTFOLIO layer live)

As of Phase 4, the `PORTFOLIO` layer is fully live and runs
side-by-side with `SIGNAL` alphas on the same universe:

- `layer: PORTFOLIO` alphas are loaded by
  `AlphaLoader._load_portfolio_layer` and registered as
  `LoadedPortfolioLayerModule`. Their `evaluate(context, params) →
  SizedPositionIntent` is driven by `CompositionEngine`, never by
  `CompositeSignalEngine` or `HorizonSignalEngine`.
- `UniverseSynchronizer` subscribes to `Signal` events emitted by
  the upstream `depends_on_signals` alphas, fans them in per
  `(alpha_id, horizon_seconds, boundary_index)`, and emits a
  `CrossSectionalContext` event once the boundary closes (or once
  the per-platform fan-in deadline elapses, whichever comes first).
  The context carries `completeness` (the fraction of the alpha's
  declared `universe` that supplied a non-stale signal); contexts
  below `composition_completeness_threshold` (default `0.7` in
  `platform.yaml`) are dropped silently — see G9 in the
  Architectural gates table.
- `CompositionEngine` consumes the context, runs the alpha's
  `evaluate`, and routes the result through `FactorNeutralizer →
  SectorMatcher → CrossSectionalRanker → TurnoverOptimizer` (in
  that fixed order) before emitting the `SizedPositionIntent`.
  Every component is deterministic by construction and contributes
  to the intent's `decision_basis_hash`. The Level-3 SIZED-INTENT
  parity hash is locked in
  `tests/determinism/test_sized_intent_replay.py`; drift in
  ordering, scope, weights, or sequence allocation surfaces as a
  baseline failure on the next CI run.
- The risk engine consumes `SizedPositionIntent` via
  `RiskEngine.check_sized_intent`, which decomposes the desired
  book delta against `PositionStore` (current quantity + most
  recent mark price) and emits per-leg `OrderRequest`s sorted
  lexicographically by symbol. **Per-leg veto** (Inv-11) is
  enforced: a single leg failing risk checks drops only that leg,
  never the entire intent. Each emitted `OrderRequest.reason =
  "PORTFOLIO"` for lineage tracking. The Level-4 PORTFOLIO
  ORDER-REQUEST parity hash is locked in
  `tests/determinism/test_portfolio_order_replay.py`.
- Every PORTFOLIO alpha must declare `universe`,
  `depends_on_signals`, `factor_neutralization`, and
  `cost_arithmetic`. Risk-budget keys (`max_position_per_symbol`,
  `max_gross_exposure_pct`, `capital_allocation_pct`) are
  inherited by per-leg `OrderRequest`s through the standard risk
  pipeline. Reference factor loadings live under
  `src/feelies/storage/reference/factor_loadings/<universe_hash>/loadings.json`
  (with optional `loadings.parquet`) and a sector map under
  `src/feelies/storage/reference/sector_map/sector_map.json`; both are produced
  by `scripts/build_reference_factor_loadings.py` and folded into
  the bootstrap provenance bundle (Inv-13).
- Bootstrap is gated on `AlphaRegistry.has_portfolio_alphas()` —
  if no PORTFOLIO alpha is registered, no composition components
  are constructed and the orchestrator runs a strict superset of
  the Phase-3-α pipeline. When PORTFOLIO alphas *are* registered,
  bootstrap also instantiates `CrossSectionalTracker` (per-strategy
  gross/net/factor/mechanism aggregation), `HorizonMetricsCollector`
  (12 composition + hazard metrics), and (if any alpha enables
  `hazard_exit.enabled: true`) `HazardExitController`.
- The reference alpha
  [`alphas/pro_xsect_v1`](pro_xsect_v1/) ships as the canonical
  Phase-4 example, with a sibling `pro_xsect_v1.with_decay.alpha.yaml`
  exercising the Phase-4.1 decay-weighting branch and
  [`alphas/pro_xsect_mixed_mechanism_v1`](pro_xsect_mixed_mechanism_v1/)
  exercising the multi-mechanism cap.
- `scripts/run_backtest.py` exposes three new emission flags
  composable with the Phase-3 ones:
  - `--emit-cross-sectional-jsonl` (prefix `XSECT_JSONL`),
  - `--emit-sized-intents-jsonl` (prefix `SIZED_JSONL`),
  - `--emit-hazard-exits-jsonl` (prefix `HAZARD_EXIT_JSONL`).
- Gates G1, G3, G9, G10, G11 are **active** — see the
  Architectural gates table above. G1 / G3 are downgradable to
  warnings via `PlatformConfig.enforce_layer_gates: false` for
  research workflows; G9 / G10 / G11 always block.

### Phase-4.1 status (decay weighting + hazard exit ACTIVE)

As of Phase 4.1, two opt-in extensions to the Phase-4 baseline are
live:

- **Decay weighting (`CrossSectionalRanker`).** A PORTFOLIO alpha
  with `parameters.decay_weighting_enabled.default: true`
  multiplies each per-symbol raw alpha score by `exp(-Δt / hl)`
  before standardization, where `Δt = boundary_ts_ns -
  signal.timestamp_ns` and `hl = signal.expected_half_life_seconds
  * 1e9` (per-mechanism half-life from G16). Clamped below by
  `decay_floor` (default `1e-6`). Decay weighting is *additive* —
  the structural ranking semantics are unchanged — and produces a
  different `decision_basis_hash` than the decay-OFF baseline,
  verified by the cross-check in
  `tests/determinism/test_sized_intent_with_decay_replay.py`. The
  performance budget is **≤5% wall-clock end-to-end regression**
  vs the same alpha with decay OFF.
- **Hazard exit (`HazardExitController`).** A PORTFOLIO alpha
  with `hazard_exit.enabled: true` participates in two exit paths:
  - On `RegimeHazardSpike`: if the spike's hazard score exceeds
    `hazard_score_threshold` (per-alpha) AND the position has
    been open at least `min_age_seconds`, emit an `OrderRequest`
    with `reason = "HAZARD_SPIKE"` flattening the position.
    Suppression is per `(symbol, alpha_id, departing_state)`.
  - On `Trade` reconciliation: if the position has been open
    longer than `hard_exit_age_seconds`, emit an `OrderRequest`
    with `reason = "HARD_EXIT_AGE"` (hard cap, fired regardless
    of regime). Suppressed for `hard_exit_suppression_seconds`
    after firing.
  Both paths are bit-identical across replays (Inv-5) — verified
  by `tests/determinism/test_hazard_exit_replay.py`.
- **Mechanism breakdown + cap (`CrossSectionalRanker`).** Every
  `SizedPositionIntent` carries a `mechanism_breakdown:
  dict[TrendMechanism, float]` reporting the gross-exposure share
  per upstream mechanism family. The PORTFOLIO alpha's
  `trend_mechanism.consumes:` list declares per-family
  `max_share_of_gross` caps; the ranker scales any over-budget
  family down proportionally before re-normalizing the gross.
  G16 PORTFOLIO rule 8 enforces the cap summation at load time;
  the ranker enforces it at emission time. Verified by
  `tests/integration/test_mixed_mechanism_universe.py`.

### `promotion:` block (v0.3, Workstream F-5)

Optional per-alpha override of the platform `GateThresholds` consumed
by `validate_gate(...)` in
[`src/feelies/alpha/promotion_evidence.py`](../src/feelies/alpha/promotion_evidence.py).
The block is **opt-in via field presence** — absent or empty block
⇒ no per-alpha override and the alpha promotes against the platform
defaults.  When supplied, the loader stores the validated overrides
on `AlphaManifest.gate_thresholds_overrides`; the registry then
applies them on top of the platform `GateThresholds` when
constructing the alpha's `AlphaLifecycle`.

```yaml
promotion:
  gate_thresholds:
    paper_min_trading_days: 7         # default 5
    dsr_min: 1.2                      # default 1.0
    cpcv_min_mean_sharpe: 1.2         # default 1.0
    revalidation_min_oos_sharpe: 1.5  # default 1.0
```

Layering precedence (lowest → highest):

1. **Skill-pinned defaults** — `GateThresholds()` with the values
   pinned in `promotion_evidence.py` (mirroring the
   testing-validation and post-trade-forensics skill thresholds).
2. **`platform.yaml: gate_thresholds:`** — operator-wide overrides
   (Workstream F-5 platform-level surface; see
   `PlatformConfig.gate_thresholds_overrides`).  Applied on top of
   the skill defaults at bootstrap to produce the registry's base
   `GateThresholds`.
3. **`promotion.gate_thresholds:`** in this YAML — per-alpha
   overrides applied on top of (2) at registration time.

**Operator floors (per-alpha may only tighten operator policy).** A
per-alpha override may tighten any gate and may loosen a threshold the
operator left at its skill default, but it may **not loosen below a
threshold the operator explicitly pinned in `platform.yaml:
gate_thresholds:`**. `AlphaRegistry` refuses such an alpha at
registration (`AlphaRegistryError` wrapping `GateThresholdFloorError`)
in every mode. Direction is per-field: `*_min_*` / floor thresholds may
only be raised, `*_max_*` ceilings only lowered (note
`small_max_hit_rate_residual_pp` is a *floor* despite its name); the
consistency-only `quarantine_*` fields are unconstrained. Fields the
operator did not pin remain freely loosenable per-alpha.

Validation at load time:

| Rule | Behaviour |
|---|---|
| Block must be a mapping | `AlphaLoadError` if scalar/list. |
| Only `gate_thresholds:` sub-block is supported | Other keys (e.g. `promotion.notes:`) raise `AlphaLoadError` listing the offending keys. |
| `gate_thresholds:` must be a mapping | `AlphaLoadError` otherwise. |
| Every key must name a `GateThresholds` field | Unknown keys raise `AlphaLoadError` listing the valid field names. |
| Every value must match the field's declared type | Booleans are not auto-cast to ints; strings are not auto-parsed as numbers — operator must supply real numbers/booleans in YAML. |
| Empty `gate_thresholds: {}` | Treated as "no overrides"; manifest carries `gate_thresholds_overrides=None`. |

The loader does **not** perform cross-field invariant checks (e.g.
`small_min_pnl_compression_ratio < small_max_pnl_compression_ratio`)
— those are deferred to the consumer (the F-2 validators).  The
override surface is purely structural.  See
`alphas/SCHEMA.md` § "Per-alpha promotion overrides" for the operator
cookbook and
[`tests/alpha/test_loader_promotion_block.py`](../tests/alpha/test_loader_promotion_block.py)
for the asserting tests.

The same `gate_thresholds` block also governs the **Workstream F-6**
LIVE @ SMALL_CAPITAL → LIVE @ SCALED capital-tier escalation (gate
`LIVE_PROMOTE_CAPITAL_TIER`).  The thresholds the F-6 gate reads —
`small_min_deployment_days`, `small_min_pnl_compression_ratio`,
`small_max_pnl_compression_ratio`, `small_max_slippage_residual_bps`,
`small_max_hit_rate_residual_pp`, `small_max_fill_rate_drift_pct` —
are part of the same `GateThresholds` dataclass, so an alpha that
needs a stricter or looser SCALED bar can override them in this
block without touching the platform defaults or any other alpha.
The escalation itself is invoked through
`AlphaLifecycle.promote_capital_tier(evidence)` (or
`AlphaRegistry.promote_capital_tier(alpha_id, evidence)`); on success
it records a `LIVE -> LIVE` self-loop entry on the F-1 promotion
ledger with `trigger == "promote_capital_tier"` so the operator CLI
(`feelies promote inspect <alpha_id>`) can render the escalation
without the lifecycle state name changing.

### `lifecycle_state:` field (BT-13)

Top-level, optional, `string`. The only accepted value is `"RESEARCH"`
(`AlphaLoader._parse_lifecycle_state`,
[`src/feelies/alpha/loader.py`](../src/feelies/alpha/loader.py)); anything
else raises `AlphaLoadError` at load time. When present, the loader carries
it onto `AlphaManifest.lifecycle_cap`, and `AlphaRegistry.register()` wires
it into the alpha's constructed `AlphaLifecycle`
(`lifecycle_cap=manifest.lifecycle_cap`). `AlphaLifecycle._lifecycle_promotion_errors`
then unconditionally blocks `promote_to_paper()` / `promote_to_live()` while
still allowing the spec to load for backtest and integration use — see
`alpha-lifecycle` skill and
[`tests/alpha/test_sig_inventory_revert_v1.py`](../tests/alpha/test_sig_inventory_revert_v1.py)
(`test_research_lifecycle_cap_blocks_paper_promotion`) for the enforced,
tested example.

**PR-review checklist item (audit `signal_alpha_audit_2026-07-02.md` §8):**
the cap is a pure function of this one YAML line — it carries no link back
to *why* the alpha was capped. Removing or changing `lifecycle_state:
RESEARCH` on an alpha that was capped because of a specific negative
forward-IC / decay-evidence finding (e.g. `sig_inventory_revert_v1`'s
recorded quarantine, see that spec's `notes:` block) lifts the promotion
block immediately, with **no automatic check that new evidence justifies
it**. Reviewers must treat a diff that removes or weakens
`lifecycle_state: RESEARCH` on a previously-capped alpha as requiring the
same evidence bar as a fresh RESEARCH→PAPER promotion request — never
approve it as a routine YAML edit.

### Backward compatibility

- Schema 1.0 specs are rejected (Workstream D.1 hard-removal).
- Schema-1.1 specs declaring `layer: LEGACY_SIGNAL` are rejected
  (Workstream D.2 retirement); the rejection error includes a
  pointer to the backward-compatibility notes above.
- A schema-1.1 spec without `layer:` is rejected — there is no
  implicit upgrade path (§8.7).
- A schema-1.1 spec **without** a `promotion:` block continues to
  load unchanged (Workstream F-5 is opt-in via field presence).
  The alpha promotes against the platform `GateThresholds` produced
  by `bootstrap._build_platform_gate_thresholds` from
  `platform.yaml` (or against the skill-pinned defaults if no
  platform overrides exist either).

### Migration

After Workstream D.2 the only accepted layer values are `SIGNAL` and
`PORTFOLIO`; the previously documented mechanical
``layer: LEGACY_SIGNAL`` upgrade is no longer accepted by the loader.
Authors must promote per-tick alphas to the SIGNAL layer (declaring
`horizon_seconds`, `depends_on_sensors`, `regime_gate`,
`cost_arithmetic`, and a 3-arg `evaluate(snapshot, regime, params)`
signal block).

**Workstream-D notes —** the in-repo LEGACY parity test
(`tests/determinism/test_legacy_alpha_parity.py`) and its anchoring
reference alpha (`alphas/trade_cluster_drift/`) were retired in D.2.
Both the per-tick legacy execution path and the loader-side
`LEGACY_SIGNAL` dispatch were removed in the same workstream; the
Level-1 LEGACY-fill parity hash is no longer maintained in this repo.

### Phase-5 status (documentation + LEGACY_SIGNAL retirement complete)

As of Phase 5 + Workstream D.2, the platform's externally facing
documentation is synchronised with the three-layer architecture and
the LEGACY_SIGNAL retirement is complete:

- **Migration complete** — covers the schema 1.0 → 1.1 upgrade, the
  per-tick → SIGNAL promotion path, the `regime_gate` DSL, the
  `cost_arithmetic` block, authoring a PORTFOLIO alpha, hazard exits,
  and the v0.3 `trend_mechanism` opt-in.
- **Layer-specific templates** ship under
  [`alphas/_template/`](_template/): `template_signal.alpha.yaml` and
  `template_portfolio.alpha.yaml`.  The original
  `template.alpha.yaml` (schema 1.0) was deleted in workstream D.1
  and `template_legacy_signal.alpha.yaml` was deleted in D.2 with
  the loader-side retirement.  No in-repo per-tick LEGACY template
  will be re-introduced.
- **Authoring guidance** — SIGNAL hypothesis discipline and mechanism
  taxonomy: [`.cursor/skills/microstructure-alpha/SKILL.md`](../.cursor/skills/microstructure-alpha/SKILL.md).
  Sensor / horizon-feature layer: [`.cursor/skills/feature-engine/SKILL.md`](../.cursor/skills/feature-engine/SKILL.md).
  Research workflow and experiment hygiene:
  [`.cursor/skills/research-workflow/SKILL.md`](../.cursor/skills/research-workflow/SKILL.md).
- **`LEGACY_SIGNAL` is hard-rejected.** The loader's once-per-process
  sunset banner has been removed; any spec carrying
  `layer: LEGACY_SIGNAL` raises an `AlphaLoadError` at parse time
  with a stable pointer to the backward-compatibility notes in SCHEMA.md.

### Stage-0 dual-permission actuation status (`safety_exit_policy`, Phase 4)

The Stage-0 decoupling schema surface and its guards are live
(`dual_permission_actuation_design` rev 5, staged Phases 1–4):

- **Config surface** — the `safety_exit_policy:` block parses and round-trips
  onto `AlphaManifest.safety_exit_policy`; `mode: decouple_caps_only` marks the
  loaded module `decouple_gate_close = True`. An absent block (or the default
  `gate_close_flat`) is **bit-identical to pre-decoupling behaviour** (Inv-5).
- **Load-time invariants (Phase 4)** — gate **G17** and the cross-alpha
  `validate_decouple_symbol_scope` enforce, at load: both ceilings mandatory
  under decouple; `story_permission ⇒ decouple`; the per-family
  `max_hold_after_safe_off` half-life ceiling; and the symbol-scope rule
  (single-strategy-per-symbol unless the backstop is strategy-slice-scoped —
  which this platform's is).
- **Revocation symmetry (Phase 4, §2.5 / §3.6)** — the mechanism that flattens
  an open deferred book **immediately** on a decoupled alpha's Stage-0
  authorization removal, not at the old ceiling. A lifecycle demotion
  (`quarantine` / `decommission`) fires `AlphaLifecycle`'s revocation hook;
  `AlphaRegistry.set_lifecycle_revocation_hook` propagates one hook to every
  lifecycle; and the risk-layer `ExitComposer.revoke_and_flatten` emits a
  strategy-slice-scoped `DECOUPLING_REVOKED` flatten through the same
  non-vetoable forced-exit bridge as the fail-closed unwind (Inv-11). A config
  revert to `gate_close_flat` calls the same composer entry point. The demotion
  always commits even if the immediate flatten fails (the deferral cap / session
  flatten remain as backstops).
- **Runtime activation deferred to the parity phase** — Phase 4 delivers the
  *load-time* surface + guards and the revocation *mechanism*. Flipping
  `decouple_gate_close` into the live `HorizonSignalEngine`, wiring the
  `DeferralCapController` beside the composer, and connecting the registry's
  revocation hook to that composer at bootstrap are the runtime go-live steps —
  they change a decoupled alpha's **event-stream shape** (SIGNAL-stream
  gate-close FLAT → RISK-stream flatten at a new sequence), so they land with the
  determinism / regenerated-golden phase. Until then the default `gate_close_flat`
  path is untouched (bit-identical, Inv-5) and no shipped alpha declares
  `decouple_caps_only`.
- **Not yet promotable** — the promotion gates that let an alpha *adopt*
  `decouple_caps_only` in production (conditional-CVaR under purged CPCV,
  turnover bound, Inv-12 stress fills) are the Stage-0 validation harness and
  land in a later phase.
