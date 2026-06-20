# Feelies SIGNAL Alpha Audit - 2026-06-20

Scope: read-only audit of the SIGNAL layer, current alpha YAML specs, loader and validation contracts, engine dispatch, cost disclosure, multi-alpha composition, and focused tests. No production fixes were made.

Assumptions:

- "Reference SIGNAL alphas" means discovered non-template SIGNAL specs plus the intentionally underscored paper smoke spec where it is loaded by config.
- "Cost survival" is evaluated from disclosed YAML arithmetic and code contracts, not from a new market-data backtest.
- A pass on static G16/G12 validation is not evidence of live alpha; it only means the spec satisfies the repository's declared structural contracts.
- Severity follows the requested P0/P1/P2 framing: P0 correctness/safety, P1 economic soundness, P2 research/product hardening.

## 1. Executive Summary

- No P0 production-code correctness defect was found in the current SIGNAL engine path.
- The engine mostly enforces the intended purity and causality contract: alpha `evaluate(snapshot, regime, params)` is wrapped as a stateless adapter, and inline code is compiled into a restricted namespace (`src/feelies/alpha/signal_layer_module.py:222`, `src/feelies/alpha/loader.py:769`).
- Warm/stale handling is now correct for the key safety case: stale or cold required features suppress new entries, while gate-close exits can still publish FLAT (`src/feelies/signals/horizon_engine.py:476`, `tests/signals/test_horizon_signal_engine.py:353`).
- G16 validation is strong for families, half-life ranges, horizon/half-life ratio, fingerprint sensors, failure signatures, and signature-sensor coverage (`src/feelies/alpha/layer_validator.py:843`).
- Residual G16 risk remains for dynamic LIQUIDITY_STRESS entry logic because the static AST checker cannot resolve every dynamic direction expression (`src/feelies/alpha/layer_validator.py:1154`).
- All production-style SIGNAL specs reconcile their disclosed one-way cost arithmetic and meet the G12 `>=1.5` one-way margin rule.
- None of the reference SIGNAL specs have disclosed raw edge `>=1.5x` disclosed round-trip cost; their raw round-trip margins are 0.8 to 1.0 before stress. This is a disclosed economic/modeling risk, not a G12 implementation bug.
- Runtime B4 cost gating is therefore essential. The code has that gate, and the config comments explicitly distinguish one-way disclosure from round-trip execution cost (`src/feelies/core/platform_config.py:289`, `src/feelies/execution/position_manager.py:550`).
- Every production-style alpha self-suppresses below a `cost_floor_bps`, but that floor is still a tunable bounded parameter and can be lowered by config unless a caller is constrained elsewhere.
- `sig_inventory_revert_v1` is correctly quarantined as RESEARCH by its own forward-return evidence and should not be promoted without a new by-leg data run (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:7`).
- `sig_moc_imbalance_v1` is honest about its edge source: the directional prior is exogenous scheduled-flow data, not L1 microstructure (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:15`).
- The current standalone multi-signal path is deterministic and conservative, but it selects one winning entry rather than stacking same-direction standalone alpha evidence (`src/feelies/alpha/arbitration.py:34`, `src/feelies/kernel/orchestrator.py:2388`).
- The test suite is good at contract enforcement and replay determinism, but it does not yet prove per-alpha forward-return IC, post-cost profitability, or Inv-12 survival under stressed spread, fees, impact, and latency.
- Highest-value next work is data-facing: per-alpha OOS IC/bucket-return reports, per-alpha stressed B4 survival, and stricter promotion gates around quarantined or exogenous-prior alphas.

## 2. SIGNAL Alpha Inventory

| Alpha | Layer | Lifecycle | Horizon | Mechanism | Half-life | Ratio h/hl | Main sensors | Cost basis | Edge bps | One-way cost bps | G12 margin | Raw RT margin | Strict G16 |
| --- | --- | --- | ---: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| `paper_smoke_v1` | SIGNAL | not declared | 30s | none | n/a | n/a | `micro_price`, `realized_vol_30s` | one_way | 10.0 | 2.5 | 4.00 | 2.00 | intentionally off in smoke config |
| `sig_benign_midcap_v1` | SIGNAL | RESEARCH | 120s | KYLE_INFO | 120s | 1.00 | `ofi_ewma`, `micro_price`, `book_imbalance`, `spread_z_30d`, `realized_vol_30s` | one_way | 9.0 | 5.0 | 1.80 | 0.90 | pass |
| `sig_hawkes_burst_v1` | SIGNAL | RESEARCH | 30s | HAWKES_SELF_EXCITE | 30s | 1.00 | `hawkes_intensity`, `trade_through_rate`, `ofi_ewma`, `spread_z_30d`, `realized_vol_30s` | one_way | 8.0 | 5.0 | 1.60 | 0.80 | pass |
| `sig_inventory_revert_v1` | SIGNAL | RESEARCH, quarantined | 30s | INVENTORY | 20s | 1.50 | `quote_replenish_asymmetry`, `spread_z_30d`, `realized_vol_30s`, `quote_hazard_rate` | one_way | 8.8 | 5.5 | 1.60 | 0.80 | pass |
| `sig_kyle_drift_v1` | SIGNAL | RESEARCH | 300s | KYLE_INFO | 600s | 0.50 | `kyle_lambda_60s`, `ofi_ewma`, `micro_price`, `spread_z_30d`, `realized_vol_30s` | one_way | 11.7 | 6.5 | 1.80 | 0.90 | pass |
| `sig_moc_imbalance_v1` | SIGNAL | RESEARCH | 120s | SCHEDULED_FLOW | 240s | 0.50 | `scheduled_flow_window`, `ofi_ewma`, `realized_vol_30s` | one_way | 12.0 | 6.0 | 2.00 | 1.00 | pass |

Notes:

- `paper_smoke_v1` is excluded from discovered active alpha tests because underscore path segments are filtered (`tests/alpha/test_discovered_alpha_specs_load.py:1`). It is explicitly loaded only by the paper smoke config with strict trend enforcement disabled (`configs/paper_smoke_rth.yaml:14`, `tests/paper/test_smoke_config.py:18`).
- "Raw RT margin" above is `edge / (2 * disclosed_one_way_cost)` using disclosed YAML values. It is not the runtime cost model result.
- All production-style SIGNAL alphas pass the G16 horizon/half-life ratio band `[0.5, 4.0]` defined in validation code (`src/feelies/alpha/layer_validator.py:173`).
- Inventory source anchors: `sig_kyle_drift_v1` cost/trend/signal at `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:121`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:133`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:147`; `sig_hawkes_burst_v1` at `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:117`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:129`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:152`; `sig_inventory_revert_v1` at `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:195`, `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:208`, `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:222`; `sig_moc_imbalance_v1` at `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:136`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:147`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:159`; `sig_benign_midcap_v1` at `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:141`, `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:151`, `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:175`.
- Parameter surface: the loader parses `range` separately from `min`/`max` bounds, so current specs with bounded parameters but no optimization `range` entries pass the structural free-knob cap (`src/feelies/alpha/loader.py:1225`). Economic overfit risk is still highest in specs with many human-tuned bounds, especially `sig_inventory_revert_v1` (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:67`).

## 3. Engine Audit

### Purity

The intended contract is pure and stateless: `HorizonSignal.evaluate(snapshot, regime, params)` takes only a feature snapshot, regime view, and immutable parameter mapping (`src/feelies/signals/horizon_protocol.py:11`). Loaded alpha code is adapted through `_CompiledHorizonSignal`, which copies params and calls the compiled function without preserving alpha-local mutable state (`src/feelies/alpha/signal_layer_module.py:222`).

The loader compiles inline signal code into a constrained environment rather than importing arbitrary modules (`src/feelies/alpha/loader.py:769`). The validator also applies AST purity checks for banned imports, banned builtins, `global`, and `nonlocal` (`src/feelies/alpha/layer_validator.py:584`). That is a good structural control.

Residual risk: purity is statically checked, not exhaustively proven at runtime. The current tests validate behavior and metadata, but there is no property test that repeatedly calls every loaded alpha with the same snapshot and asserts bitwise identical output plus no mutation of `params` or `snapshot.values`.

### Causality

Alpha `evaluate` receives only `HorizonFeatureSnapshot` and regime state. `HorizonFeatureSnapshot` carries feature values, warm/stale sets, source sensors, and feature versions (`src/feelies/core/events.py:604`). That is the correct boundary for avoiding lookahead inside alpha code.

Regime gates are evaluated by the engine using bindings built from the snapshot first, with sensor-cache fallback for identifiers not present in snapshot values (`src/feelies/signals/horizon_engine.py:611`). This is acceptable for a gate layer if the cache is event-time only, but it means "snapshot is the only input" is literally true for alpha evaluation and not literally true for gate expressions. The engine invalidates cached scalar readings on cold sensor readings (`src/feelies/signals/horizon_engine.py:271`), reducing stale-cache risk.

Residual risk: there is no explicit engine-level duplicate-boundary idempotence check. If upstream emits duplicate snapshots for the same alpha, symbol, and horizon boundary, the engine can evaluate both. Downstream arbitration is deterministic, but the engine itself does not enforce "one signal per alpha per boundary."

### Ordering

Dispatch order is stable. The engine iterates registered signals and emits patched `Signal` events with deterministic alpha metadata. Standalone conflicts are resolved later by `EdgeWeightedArbitrator`, which uses `edge * strength` and deterministic tie-breaks by strategy id (`src/feelies/alpha/arbitration.py:34`).

The determinism tests hash emitted reference alpha event streams and replay the same scenario twice (`tests/determinism/test_signal_replay.py:239`, `tests/determinism/test_signal_replay.py:288`). This is useful for ordering regressions. The baseline is still mostly synthetic and not a proof of economic behavior.

### Warm/Stale Handling

The engine computes required warm features per alpha from snapshot consumption and gate identifiers (`src/feelies/bootstrap.py:1458`). This avoids blocking an alpha because unrelated features are stale.

New entries are suppressed when required features are cold or stale, but gate-close exits still publish FLAT after the gate is evaluated (`src/feelies/signals/horizon_engine.py:476`, `src/feelies/signals/horizon_engine.py:531`). Tests cover both cases: stale required feature permits gate close and suppresses fresh entry (`tests/signals/test_horizon_signal_engine.py:353`, `tests/signals/test_horizon_signal_engine.py:399`).

This is the right tradeoff: do not open new risk on bad inputs, but allow exits to reduce risk.

## 4. Per-Alpha Audit

### `sig_kyle_drift_v1`

Mechanism honesty: Strong. The spec declares KYLE_INFO and actually consumes `kyle_lambda_60s_percentile`, `kyle_lambda_60s_zscore`, and `ofi_ewma` in the signal code (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:147`). That matches the Kyle 1985 "Continuous Auctions and Insider Trading" intuition better than a pure OFI proxy. The declared half-life is 600s against a 300s horizon, exactly at the lower allowed ratio of 0.5 (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:100`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:133`).

Cost reconciliation: G12 reconciles as `11.7 / (2.5 + 3.0 + 1.0) = 1.8`, one-way basis (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:121`). The spec comment openly states round-trip cost is about 13 bps and raw edge divided by round-trip cost is about 0.90, with runtime B4 authoritative (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:121`). This is honest disclosure, but it means the alpha must rely on execution selectivity, passivity, or B4 filtering to survive costs.

Falsifiability: Good. The falsification criteria name sign decay, widened spread buckets, volatility regime breaks, and lambda-estimator drift (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:33`). The missing evidence is a current OOS bucket-return report by lambda percentile and OFI sign.

Classification: no implementation bug found; economic cost-survival is unproven.

### `sig_hawkes_burst_v1`

Mechanism honesty: Strong. The spec declares HAWKES_SELF_EXCITE and consumes `hawkes_intensity_zscore`, `trade_through_rate`, and `ofi_ewma` (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:152`). That is consistent with Hawkes 1971 "Spectra of Some Self-Exciting and Mutually Exciting Point Processes" and a short burst horizon. The half-life equals the 30s horizon (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:96`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:129`).

Cost reconciliation: G12 reconciles as `8.0 / (2.0 + 2.0 + 1.0) = 1.6`, one-way basis (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:117`). Raw round-trip margin is only 0.8. That is especially tight for a 30s alpha because latency and spread shocks directly attack the expected edge.

Falsifiability: Good. The spec calls out intensity half-life, spread-widening failure, and trade-through false positives (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:29`). The hazard exit metadata is present (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:146`), which is appropriate for burst decay.

Classification: no implementation bug found; high latency and stressed-cost sensitivity.

### `sig_inventory_revert_v1`

Mechanism honesty: Mixed, but explicitly quarantined. The declared mechanism is INVENTORY and the signal consumes replenishment asymmetry, quote hazard, and volatility taper (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:208`, `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:222`). That is consistent with Ho and Stoll 1981 "Optimal Dealer Pricing Under Transactions and Return Uncertainty" style inventory pressure.

The YAML itself reports a failed forward-return study: pooled rank IC around `-0.007`, conditional forward returns below disclosed edge and below round-trip cost, and a contra-indicated SHORT leg (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:11`). The lifecycle is RESEARCH and the notes say not to promote to PAPER or LIVE (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:7`).

Cost reconciliation: G12 reconciles as `8.8 / (2.5 + 2.0 + 1.0) = 1.6`, one-way basis (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:195`). Raw round-trip margin is 0.8. The implementation applies a realized capture ratio, hazard weighting, volatility taper, and cost floor (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:222`). Those are sensible controls, but they do not overturn the recorded empirical failure.

Falsifiability: Strong because the spec includes concrete known-bad empirical evidence. The next requirement is not more static validation; it is a new by-leg OOS study with separate LONG and SHORT sign checks.

Classification: no engine bug; current empirical evidence says do not promote.

### `sig_moc_imbalance_v1`

Mechanism honesty: Honest, with an exogenous edge source. The spec declares SCHEDULED_FLOW and explicitly says `flow_direction_prior` is not inferred from L1; it comes from reference event-calendar context (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:15`). The signal consumes active window state, seconds to close, directional prior, and OFI confirmation (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:159`).

This means the alpha is not a pure microstructure alpha from L1 observables. It is a scheduled-flow alpha with L1 confirmation. That is acceptable if documented, and it is documented.

Cost reconciliation: G12 reconciles as `12.0 / (2.5 + 2.5 + 1.0) = 2.0`, one-way basis (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:136`). Raw round-trip margin is 1.0, the best of the production-style specs but still below 1.5. The signal additionally scales edge by remaining window time and suppresses weak late-window entries through a cost floor (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:159`).

Falsifiability: Good if the event-calendar prior is archived. Required validation is a calendar-stratified OOS study that separates prior-only, OFI-only, and prior-plus-OFI conditions.

Classification: no implementation bug; L1 identifiability limit is explicit.

### `sig_benign_midcap_v1`

Mechanism honesty: Plausible but weaker than direct Kyle-lambda variants. The spec declares KYLE_INFO but no longer declares `kyle_lambda_60s` as a dependency. It uses OFI, micro-price/book imbalance, spread, and realized volatility (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:51`). The YAML explains that a prior cosmetic Kyle-lambda fingerprint was replaced by an OFI/book-imbalance footprint (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:151`).

That makes the mechanism honest enough as a Kyle-style L1 projection, but it is not as identifiable as `sig_kyle_drift_v1`. The L1 limitation should stay visible in any promotion memo.

Cost reconciliation: G12 reconciles as `9.0 / (2.0 + 2.0 + 1.0) = 1.8`, one-way basis (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:141`). Raw round-trip margin is 0.9. The signal requires OFI/book-imbalance sign alignment and suppresses edge below `cost_floor_bps` (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:175`).

Falsifiability: Reasonable. The tests lock sign alignment, floor suppression, cap behavior, and non-emission when book imbalance disagrees (`tests/alpha/test_sig_benign_midcap_v1.py:182`). Missing evidence is a midcap-specific OOS IC and realized spread-cost study.

Classification: no implementation bug; mechanism is an L1 proxy and should not be overclaimed.

### `paper_smoke_v1`

Mechanism honesty: Not a research alpha. It has no trend mechanism and exists to guarantee pipeline entries in smoke tests (`alphas/_paper_smoke_v1/paper_smoke_v1.alpha.yaml:1`). The paper smoke config disables strict trend enforcement (`configs/paper_smoke_rth.yaml:14`), and tests assert this behavior (`tests/paper/test_smoke_config.py:18`).

Cost reconciliation: The arithmetic is internally consistent: edge 10 bps over 2.5 bps one-way disclosed cost gives a 4.0 G12 margin (`alphas/_paper_smoke_v1/paper_smoke_v1.alpha.yaml:43`).

Falsifiability: Not applicable. This should remain excluded from production alpha discovery and promotion paths.

Classification: intentional test fixture; not an alpha candidate.

## 5. Multi-Alpha Interaction

Standalone SIGNAL arbitration is deterministic and conservative. `EdgeWeightedArbitrator` chooses the strongest entry by `edge_estimate_bps * strength`, gives FLAT exit intent priority, and tie-breaks deterministically (`src/feelies/alpha/arbitration.py:34`). The orchestrator uses that arbitrator when multiple standalone signals arrive in one tick (`src/feelies/kernel/orchestrator.py:2388`).

This avoids accidental position stacking from independent alpha events. The tradeoff is that same-direction evidence is discarded in the standalone path. That is coherent for a cautious platform, but it means economic combination should happen through explicit PORTFOLIO specs rather than incidental simultaneous SIGNAL emissions.

The generic aggregation module is exit-priority and nets entries, with exits non-cancellable (`src/feelies/alpha/aggregation.py:1`). Portfolio netting has separate capped standing-target machinery in shadow/harness paths (`src/feelies/execution/portfolio_netter.py:1`).

Tests cover the core standalone interaction behavior: arbitration selects highest composite score, respects a dead zone, and resolves directional conflicts deterministically (`tests/alpha/test_arbitration.py:40`, `tests/alpha/test_arbitration.py:48`, `tests/alpha/test_arbitration.py:66`). Aggregation tests cover reversal splitting, exit and entry buckets, and multi-intent netting (`tests/alpha/test_aggregation.py:62`, `tests/alpha/test_aggregation.py:188`, `tests/alpha/test_aggregation.py:208`).

Portfolio research specs are present:

- `pro_burst_revert_v1` combines HAWKES_SELF_EXCITE and INVENTORY signals and caps each mechanism at 0.6 (`alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:73`).
- `pro_kyle_benign_v1` combines two KYLE_INFO alphas and allows KYLE_INFO max share 1.0 (`alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:77`).

Risk assessment:

- `pro_burst_revert_v1` inherits the quarantine risk of `sig_inventory_revert_v1`; it should remain research until the inventory leg is rehabilitated or removed.
- `pro_kyle_benign_v1` intentionally combines two KYLE_INFO alphas that both lean on OFI. This is not diversification unless data shows independent residual edge. Mechanism cap 1.0 is permissive for same-family stacking.
- The portfolio composer has mechanism cap scaling and optional half-life decay (`src/feelies/composition/cross_sectional.py:267`, `src/feelies/composition/cross_sectional.py:406`). That is the right place to combine alphas, but current research specs need more data before promotion.

## 6. Cost & Stress Matrix

| Alpha | Edge | One-way cost | G12 margin | Round-trip cost | Raw RT margin | 1.5x RT stress margin | Main risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `paper_smoke_v1` | 10.0 | 2.5 | 4.00 | 5.0 | 2.00 | 1.33 | test fixture only |
| `sig_benign_midcap_v1` | 9.0 | 5.0 | 1.80 | 10.0 | 0.90 | 0.60 | proxy mechanism, spread sensitivity |
| `sig_hawkes_burst_v1` | 8.0 | 5.0 | 1.60 | 10.0 | 0.80 | 0.53 | 30s latency and burst decay |
| `sig_inventory_revert_v1` | 8.8 | 5.5 | 1.60 | 11.0 | 0.80 | 0.53 | empirical sign/capture failure |
| `sig_kyle_drift_v1` | 11.7 | 6.5 | 1.80 | 13.0 | 0.90 | 0.60 | direct lambda but still round-trip tight |
| `sig_moc_imbalance_v1` | 12.0 | 6.0 | 2.00 | 12.0 | 1.00 | 0.67 | exogenous prior, close-window costs |

Interpretation:

- The G12 contract is one-way disclosure. `CostArithmetic` documents that `cost_total_bps` is one-way and the round-trip Inv-12 gate is handled at runtime (`src/feelies/alpha/cost_arithmetic.py:33`).
- Runtime B4 can use round-trip basis. With `signal_edge_cost_basis="round_trip"`, the code doubles the disclosed one-way edge before comparing to round-trip cost (`src/feelies/execution/position_manager.py:550`).
- The platform default keeps strict trend enforcement on, but `platform.yaml` currently opts out for local smoke compatibility (`src/feelies/core/platform_config.py:510`, `platform.yaml:15`). This is acceptable for local smoke, but production configs should not inherit that opt-out.
- The Inv-12 stress tests validate harness mechanics such as spread/fee/latency stress factors, not per-alpha survival under stressed costs (`tests/acceptance/test_inv12_stress_gate.py:1`).
- Component plausibility cannot be proved from static YAML. The disclosed one-way components are internally consistent, but 2.0-3.0 bps impact and 1.0 bps fee should be treated as optimistic until replayed by symbol cohort, close-window state, and latency bucket (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:117`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:136`).

Cost concern:

Each production-style alpha has a `cost_floor_bps` parameter used in signal code to suppress weak emissions. Those defaults match disclosed one-way cost. However, because the loader treats parameter min/max as ordinary bounds and returns overrideable params (`src/feelies/alpha/loader.py:1225`, `src/feelies/alpha/signal_layer_module.py:184`), a config override could lower a floor unless a separate policy prevents it. Downstream B4 should catch entries, but the alpha-level self-suppression contract would be weakened.

## 7. Test Gap Matrix

| Area | Current coverage | Gap | Priority |
| --- | --- | --- | --- |
| G12 arithmetic | Unit tests cover reconciliation, tolerance, nonnegative costs, and margin floor (`tests/alpha/test_cost_arithmetic_gate.py:45`, `tests/alpha/test_cost_arithmetic_gate.py:139`, `tests/alpha/test_cost_arithmetic_gate.py:152`) | No test tying `cost_floor_bps` min/default to disclosed one-way cost | P1 |
| G16 structural validation | Family, half-life, ratio, fingerprint, failure signature, stress checks, and rule-completeness tests are present (`tests/alpha/test_gate_g16.py:171`, `tests/alpha/test_gate_g16.py:474`, `tests/alpha/test_gate_g16_props.py:187`, `tests/acceptance/test_g16_rule_completeness.py:107`) | Dynamic direction expressions can evade static LIQUIDITY_STRESS entry detection (`tests/alpha/test_gate_g16.py:533`) | P1 |
| G2-G13 loader gates | Signal purity, no-clock, sensor dependency, horizon, and delegated G12 checks are covered (`tests/alpha/test_layer_validator_g2_g13.py:144`, `tests/alpha/test_layer_validator_g2_g13.py:236`, `tests/alpha/test_layer_validator_g2_g13.py:253`) | These tests are structural, not alpha-performance tests | P2 |
| Engine warm/stale | Required-feature narrowing, stale entry suppression, and gate-close exits covered (`tests/signals/test_horizon_signal_engine.py:230`, `tests/signals/test_horizon_signal_engine.py:353`) | No duplicate boundary/idempotence test | P2 |
| Engine metadata | G12 fields and mechanism metadata stamping covered (`tests/signals/test_horizon_signal_engine.py:854`) | Engine allows alpha-supplied mechanism/half-life to override registered defaults (`tests/signals/test_horizon_signal_engine.py:869`) | P1 |
| Typed SIGNAL parity output | JSONL tests preserve Phase-3 provenance fields and arrival order (`tests/determinism/test_emit_signals_jsonl.py:142`, `tests/determinism/test_emit_signals_jsonl.py:163`) | JSON shape tests do not validate economic edge | P2 |
| Determinism | Reference alpha hash and replay tests exist (`tests/determinism/test_signal_replay.py:239`) | Mostly synthetic/empty economic baseline; no non-empty per-alpha replay corpus | P2 |
| Per-alpha behavior | Each alpha has emission/suppression/cap tests, for example benign sign alignment and inventory caveat tests (`tests/alpha/test_sig_benign_midcap_v1.py:182`, `tests/alpha/test_sig_inventory_revert_v1.py:334`) | Tests verify code behavior, not forward-return IC, slippage, or OOS profitability | P1 |
| Inv-12 stress | Stress factors and latency doubling are tested (`tests/acceptance/test_inv12_stress_gate.py:42`) | No per-alpha pass/fail matrix under stressed spread, fee, impact, and latency | P1 |
| Promotion discipline | Discovered active specs load under strict trend mode; underscored smoke fixture excluded (`tests/alpha/test_discovered_alpha_specs_load.py:28`) | No promotion test asserting quarantined `sig_inventory_revert_v1` cannot move beyond RESEARCH | P1 |
| Portfolio composition | Composer supports mechanism caps and decay (`src/feelies/composition/cross_sectional.py:267`) | Research portfolios lack post-cost evidence and same-family crowding tests | P2 |

## 8. Prioritized Backlog

### P0

No P0 production-code correctness defect was found in this audit.

Operational P0 guardrail: keep `sig_inventory_revert_v1` blocked from PAPER/LIVE until a new data run reverses the recorded forward-return failure. Effort S if implemented as a promotion test, M if tied into a full lifecycle gate.

### P1

| Item | Why | Effort |
| --- | --- | --- |
| Add a promotion/lifecycle test that quarantined SIGNAL alphas cannot be promoted | The inventory spec says not to promote, but a test should make that policy executable (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:11`) | S |
| Enforce `cost_floor_bps >= cost_arithmetic.cost_total_bps` when an alpha exposes a cost floor | Prevents config overrides from weakening alpha-local cost suppression while preserving B4 as final gate | S |
| Add per-alpha stressed B4 survival reports | Current G12 passes one-way arithmetic, but raw round-trip and 1.5x stress margins are below 1 for all production-style alphas | M |
| Add OOS IC and bucket-return reports for every RESEARCH SIGNAL alpha | Static contracts cannot prove alpha; the missing evidence is directional forward return net of realistic costs | M |
| Replace or validate alpha-supplied mechanism overrides at engine patch time | Registered metadata should be authoritative; current tests explicitly allow alpha output to override defaults (`tests/signals/test_horizon_signal_engine.py:869`) | S |
| Add runtime guard against non-FLAT LIQUIDITY_STRESS outputs | Static AST checks can miss dynamic direction logic, and engine patching can accept alpha-supplied mechanism metadata | S |
| Archive and test the exogenous scheduled-flow prior for `sig_moc_imbalance_v1` | Its edge source is outside L1; reproducibility depends on event-calendar provenance | M |

### P2

| Item | Why | Effort |
| --- | --- | --- |
| Add duplicate snapshot boundary idempotence test or metric | Clarifies whether one signal per alpha per horizon boundary is engine-enforced or upstream-enforced | S |
| Add non-empty deterministic replay fixtures | Current determinism coverage is useful but not economic evidence | M |
| Mark `paper_smoke_v1` explicitly as a test fixture/lifecycle non-candidate | Reduces accidental interpretation as a research alpha | S |
| Add same-family crowding analysis for `pro_kyle_benign_v1` | Two KYLE_INFO alphas with OFI overlap should prove independent residual edge before stacking | M |
| Add portfolio research evidence bundles before enabling portfolio specs | Composer mechanics exist, but research portfolios should show post-cost value and mechanism cap behavior | M |

## 9. Appendix: Open Questions Needing Data Runs

- For `sig_kyle_drift_v1`, what are OOS forward returns by `kyle_lambda_60s_percentile`, OFI sign, and spread bucket after realistic queue/slippage assumptions?
- For `sig_benign_midcap_v1`, does book-imbalance confirmation add independent information after OFI, or is it mostly a noisy transform of the same pressure?
- For `sig_hawkes_burst_v1`, how much edge remains after doubling latency and widening spread in burst regimes, especially when trade-through rate is elevated?
- For `sig_inventory_revert_v1`, do LONG and SHORT legs remain sign-asymmetric in a newer sample, and does any sub-bucket survive round-trip cost?
- For `sig_moc_imbalance_v1`, what is the isolated contribution of the scheduled-flow prior versus OFI confirmation, and is the event-calendar prior reproducible from archived inputs?
- Across all production-style SIGNAL alphas, what fraction of candidate emissions survives runtime B4 under normal cost, 1.5x spread/fee/impact stress, and latency stress?
- For `pro_kyle_benign_v1`, are the two KYLE_INFO legs independent after controlling for OFI, or should a stricter same-family cap apply?
- For `pro_burst_revert_v1`, does removing the quarantined inventory leg improve or degrade post-cost performance?
- Does the sensor-cache fallback in regime gate bindings ever consume data from a newer event timestamp than the snapshot being evaluated?
- Are there duplicate HorizonFeatureSnapshot events per symbol/horizon boundary in realistic replay, and if so, should the engine or upstream aggregator own deduplication?

## Verification Run

- `uv run pytest tests/signals/test_horizon_signal_engine.py tests/alpha/test_gate_g16.py tests/alpha/test_cost_arithmetic_gate.py -q` -> 114 passed.
- `uv run pytest tests/determinism/test_signal_replay.py tests/acceptance/test_inv12_stress_gate.py -q` -> 15 passed.
