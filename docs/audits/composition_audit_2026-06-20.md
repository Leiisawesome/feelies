# Composition Layer Audit - 2026-06-20

Scope: read-only audit of the Layer-3 PORTFOLIO construction path: `Signal` fan-in to `CrossSectionalContext`, default construction pipeline, `SizedPositionIntent`, reference factor/sector inputs, and relevant tests. Production code was not modified.

Verification run:

- `uv run pytest tests/composition/ tests/portfolio/ -q` -> 91 passed.
- `uv run pytest tests/determinism/test_sized_intent_replay.py tests/determinism/test_sized_intent_with_decay_replay.py tests/determinism/test_portfolio_order_replay.py -q` -> 10 passed.
- `uv run pytest tests/integration/test_xsect_v1_e2e.py -q` -> 6 passed.
- Additional read-only optimizer check: `uv run pytest tests/determinism/test_sized_intent_solver_replay.py -q` -> 3 passed.

## 1. Executive summary

- P0 implementation bug: `factor_neutralization: false` is parsed and stored, but the engine applies the globally configured `FactorNeutralizer` unconditionally, so a PORTFOLIO alpha that explicitly opts out is still neutralized when `factor_loadings_dir` is set (`src/feelies/alpha/loader.py:625`, `src/feelies/composition/engine.py:351`, `src/feelies/bootstrap.py:1954`).
- P0 implementation bug: `decision_basis_hash` does not cover all inputs that affect `target_positions`; it hashes raw scores, decay, mechanisms, current positions, and caps, but omits factor model/loadings, sector map, optimizer parameters/path/capital, neutralized/sector-matched weights, and final target construction (`src/feelies/composition/engine.py:74`, `src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:368`).
- P0 test/invariant gap: Level-3 parity serialization excludes `decision_basis_hash`, even though Inv-5 in this audit requires that field to be bit-identical (`tests/determinism/test_sized_intent_replay.py:180`, `src/feelies/core/events.py:722`).
- P0 implementation bug: mechanism caps are enforced at ranker output, then factor neutralization, sector matching, and optimization can change realised mechanism shares before emit; the engine recomputes the final breakdown but does not re-enforce caps (`src/feelies/composition/cross_sectional.py:252`, `src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:380`).
- P0 implementation bug: multi-feeder mechanism attribution assigns each symbol to only the largest absolute contribution's mechanism, so mixed-mechanism contributions on the same symbol are not separable for cap accounting (`src/feelies/composition/cross_sectional.py:283`, `src/feelies/composition/cross_sectional.py:314`, `src/feelies/composition/cross_sectional.py:332`).
- P0 fail-safe gap: synchronizer completeness explicitly counts old cached causal signals and does not enforce a true staleness window, so an ancient signal can keep completeness above threshold (`src/feelies/composition/synchronizer.py:344`).
- P0 runtime whitelist gap: `consumes_mechanisms` is exposed on the loaded module, but no runtime path rejects a consumed `Signal.trend_mechanism` outside that whitelist (`src/feelies/alpha/portfolio_layer_module.py:127`, `src/feelies/composition/cross_sectional.py:181`).
- P1 modeling/implementation issue: bootstrap always constructs `TurnoverOptimizer(require_solver=False)`, so the default path is a deterministic closed-form rescale that ignores `composition_lambda_tc` and `composition_lambda_risk` as construction penalties (`src/feelies/bootstrap.py:1966`, `src/feelies/composition/turnover_optimizer.py:177`, `src/feelies/composition/turnover_optimizer.py:192`).
- P1 library nondeterminism contained but not eliminated: the ECOS path is explicit and tolerances are pinned, and the solver parity test passed locally, but cross-OS/BLAS replay is not asserted in this run (`src/feelies/composition/turnover_optimizer.py:50`, `tests/determinism/test_sized_intent_solver_replay.py:13`).
- P1 provenance gap: emitted `factor_exposures` are computed before sector matching and optimization, so they may not describe the final target book (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:355`, `src/feelies/composition/engine.py:397`).
- P1 reference-data determinism risk: the builder can embed `_meta.as_of_ns`, but the committed `loadings.json` has no `_meta`, and tests compensate for mtime drift with a 100-year max-age fixture (`scripts/build_reference_factor_loadings.py:177`, `tests/integration/portfolio_test_constants.py:3`).
- Sound: within a context, universe and upstream strategy IDs are sorted, alpha dispatch order is stable, and per-leg order emission is lexicographic (`src/feelies/composition/synchronizer.py:136`, `src/feelies/composition/engine.py:156`, `src/feelies/risk/sized_intent_orders.py:110`).
- Sound: explicit causal filters prevent selecting `Signal.timestamp_ns > barrier_ts`, although an out-of-order future signal can overwrite the cached causal signal and reduce completeness instead of leaking look-ahead (`src/feelies/composition/synchronizer.py:254`, `src/feelies/composition/synchronizer.py:334`).
- Sound: the two shipped PORTFOLIO alpha YAMLs are research-only and excluded from production discovery by acceptance tests (`alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:9`, `tests/acceptance/test_bt13_portfolio_research_only.py:32`).

## 2. PORTFOLIO alpha inventory

Reference `platform.yaml` loads only `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml`, so no PORTFOLIO alpha is active in the default platform config (`platform.yaml:15`). The loadable PORTFOLIO alpha inventory is under `alphas/research/`, and the acceptance suite asserts those alphas are excluded from production discovery (`tests/acceptance/test_bt13_portfolio_research_only.py:32`).

| alpha_id | lifecycle | horizon | universe | depends_on_signals | mechanism caps | factor_neutralization | completeness threshold | notes |
|---|---:|---:|---|---|---|---|---|---|
| `pro_burst_revert_v1` | `RESEARCH` | 300s | AAPL, MSFT, NVDA | `sig_hawkes_burst_v1`, `sig_inventory_revert_v1` | HAWKES 0.6, INVENTORY 0.6, global 0.7 | false | alpha param default 0.7 | Decommissioned from production discovery at N=3 (`alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:8`, `alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:43`, `alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:72`, `alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:94`). |
| `pro_kyle_benign_v1` | `RESEARCH` | 300s | AAPL, MSFT, NVDA | `sig_benign_midcap_v1`, `sig_kyle_drift_v1` | KYLE_INFO 1.0, global 1.0 | false | platform default 0.80 | No per-alpha completeness parameter is declared; engine falls back to platform config (`alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:8`, `alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:49`, `alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:84`, `src/feelies/composition/engine.py:281`). |

Platform composition defaults:

- `composition_completeness_threshold = 0.80`, `factor_model = FF5_momentum_STR`, `factor_loadings_refresh_seconds = 0`, `factor_loadings_max_age_seconds = 604800`, `composition_lambda_tc = 1.0`, `composition_lambda_risk = 0.1`, `composition_max_universe_size = 50` (`src/feelies/core/platform_config.py:567`).
- YAML parsing uses the same defaults when keys are absent (`src/feelies/core/platform_config.py:1567`).
- Bootstrap unions all loaded PORTFOLIO universes, checks the 50-name cap, checks loadings freshness when `factor_loadings_dir` is set, and then builds one shared synchronizer, neutralizer, matcher, optimizer, and engine (`src/feelies/bootstrap.py:1917`, `src/feelies/bootstrap.py:1931`, `src/feelies/bootstrap.py:1943`, `src/feelies/bootstrap.py:1953`, `src/feelies/bootstrap.py:1961`, `src/feelies/bootstrap.py:1966`, `src/feelies/bootstrap.py:1986`).

## 3. Synchronizer/barrier audit

### What is sound

The synchronizer normalizes the universe with `tuple(sorted(set(universe)))`, so context maps are stable under input universe permutation (`src/feelies/composition/synchronizer.py:136`). Upstream strategy IDs are also sorted and de-duplicated (`src/feelies/composition/synchronizer.py:147`). The emitted `CrossSectionalContext.universe` is that sorted tuple, and `signals_by_symbol` / `snapshots_by_symbol` are filled by iterating it (`src/feelies/composition/synchronizer.py:273`, `src/feelies/composition/synchronizer.py:308`, `src/feelies/composition/synchronizer.py:357`).

The barrier close trigger is the UNIVERSE-scope `HorizonTick`; the synchronizer emits immediately and idempotently per `(horizon_seconds, boundary_index)` (`src/feelies/composition/synchronizer.py:225`, `src/feelies/composition/synchronizer.py:230`, `src/feelies/composition/synchronizer.py:233`). This matches the architecture contract that barrier close is the universe tick, not "all symbols reported" (`docs/three_layer_architecture.md:1009`, `docs/three_layer_architecture.md:1016`).

Causality has explicit timestamp guards. Multi-feeder selection filters candidates to `timestamp_ns <= boundary_ts_ns` (`src/feelies/composition/synchronizer.py:254`). The legacy single-slot path skips any cached signal with `s.timestamp_ns > tick.timestamp_ns` (`src/feelies/composition/synchronizer.py:334`). This prevents look-ahead capture in the selected context.

Low completeness is fail-safe at the engine boundary. `CompositionEngine._dispatch_one` resolves a per-alpha or platform threshold, emits a degenerate empty intent when `ctx.completeness < threshold`, and returns without construction (`src/feelies/composition/engine.py:195`, `src/feelies/composition/engine.py:199`, `src/feelies/composition/engine.py:201`). Unit tests cover the degenerate path and the per-alpha threshold override (`tests/composition/test_engine.py:121`, `tests/composition/test_engine.py:141`).

### Risks and gaps

Implementation bug, P0: completeness is not a true stale-signal completeness measure. The code itself states that a carried-over signal "from a much earlier boundary still counts" and that adding a true staleness gate is deferred (`src/feelies/composition/synchronizer.py:344`). This violates the audit invariant that low completeness or stale data should reduce or skip, never inflate. A stale cached signal can increase `non_none` and let construction proceed (`src/feelies/composition/synchronizer.py:320`, `src/feelies/composition/synchronizer.py:355`).

Implementation bug, P1: if a future signal for the same `(horizon, symbol, strategy_id)` arrives before the barrier, `_on_signal` can replace the cached causal signal because the cache keeps only the latest timestamp (`src/feelies/composition/synchronizer.py:219`, `src/feelies/composition/synchronizer.py:221`). The later selection filters the future signal out, so this is fail-safe rather than look-ahead, but it can understate completeness by losing the earlier causal candidate (`src/feelies/composition/synchronizer.py:254`).

Test gap, P1: tests cover one context per tick, missing signals, idempotence, cross-horizon fan-in, and horizon separation (`tests/composition/test_synchronizer.py:67`, `tests/composition/test_synchronizer.py:95`, `tests/composition/test_synchronizer.py:120`, `tests/composition/test_synchronizer.py:156`, `tests/composition/test_synchronizer.py:214`). They do not explicitly inject future-timestamp signals or stale cached signals that should not satisfy completeness.

Ordering note: composition order is deterministic only as a function of upstream `HorizonTick` order. The synchronizer does not globally sort pending contexts by `(boundary_ts_ns, alpha_id, horizon_seconds)`; it emits on arrival of each qualifying tick (`src/feelies/composition/synchronizer.py:225`). Within each context the engine iterates registered alphas sorted by `(horizon_seconds, alpha_id)` (`src/feelies/composition/engine.py:156`, `src/feelies/composition/engine.py:182`). If the scheduler emits multi-horizon universe ticks in a stable order, replay is stable; if not, the composition layer does not repair that ordering.

## 4. Ranker & decay audit

### Math

For a legacy single signal, raw score is:

`raw_s = sign(direction_s) * strength_s * edge_estimate_bps_s`

where LONG is +1, SHORT is -1, and FLAT is 0 (`src/feelies/composition/cross_sectional.py:238`, `src/feelies/composition/cross_sectional.py:352`). For multi-feeder mode, raw scores are summed over `feeder_strategy_ids` in deterministic order (`src/feelies/composition/cross_sectional.py:289`, `src/feelies/composition/cross_sectional.py:311`). Decay, when enabled, is:

`decay = max(decay_floor, exp(-age_s / expected_half_life_seconds))`

with non-negative age and half-life taken from the `Signal` (`src/feelies/composition/cross_sectional.py:241`, `src/feelies/composition/cross_sectional.py:245`, `src/feelies/composition/cross_sectional.py:304`, `src/feelies/composition/cross_sectional.py:308`). Decay-off vs decay-on is covered by a locked baseline and a non-collision test (`tests/determinism/test_sized_intent_with_decay_replay.py:57`).

Standardization is population z-score over active symbols only; missing symbols remain weight 0.0, and zero variance or no active symbols returns all-zero weights (`src/feelies/composition/cross_sectional.py:384`, `src/feelies/composition/cross_sectional.py:390`, `src/feelies/composition/cross_sectional.py:393`). This is numerically stable for single-symbol and zero-variance universes, but it also means equal scores generate a flat book instead of equal gross allocation, which is a modeling choice (`src/feelies/composition/cross_sectional.py:376`).

Exit-only `LIQUIDITY_STRESS` is zeroed on the entry path (`src/feelies/composition/cross_sectional.py:233`, `src/feelies/composition/cross_sectional.py:295`). The source-of-truth exit-only set is in core events (`src/feelies/core/events.py:510`).

### Mechanism breakdown and caps

Per-alpha caps now reach the ranker. The loader parses `trend_mechanism.consumes[*].max_share_of_gross` into `mechanism_caps` (`src/feelies/alpha/loader.py:554`). Bootstrap rebinds the default constructor with those caps (`src/feelies/bootstrap.py:2003`). The default constructor passes them to `run_default_pipeline` (`src/feelies/alpha/portfolio_layer_module.py:224`). The ranker resolves effective caps as `min(per_family_cap, global_cap)` (`src/feelies/composition/cross_sectional.py:196`).

Implementation bug, P0: the cap is enforced before later construction transforms, not "at emit". The ranker applies `_apply_mechanism_cap` to z-scored weights (`src/feelies/composition/cross_sectional.py:252`). Then the engine applies factor neutralization, sector matching, and optimizer translation (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:355`, `src/feelies/composition/engine.py:368`). The engine recomputes realised breakdown from final dollar targets (`src/feelies/composition/engine.py:380`) but does not reject or rescale if that final breakdown exceeds caps. This makes the final cap report diagnostic rather than enforceable.

Implementation bug, P0: multi-feeder mechanism accounting is per-symbol, not per-contribution. `_rank_multi_feeder` aggregates raw contributions from several feeders into one `raw_total`, tracks the largest absolute contribution as `best_mech`, and assigns the full symbol to that one mechanism (`src/feelies/composition/cross_sectional.py:281`, `src/feelies/composition/cross_sectional.py:313`, `src/feelies/composition/cross_sectional.py:332`). A symbol with both KYLE_INFO and INVENTORY alpha is therefore treated as one family for cap and breakdown purposes. That is ad hoc for a mechanism cap that is defined as gross share by family.

Test gap, P0: the mechanism-cap tests cover the ranker alone and an integration path with no factor neutralizer and no sector matcher (`tests/composition/test_cross_sectional.py:187`, `tests/integration/test_mixed_mechanism_universe.py:157`, `tests/integration/test_mixed_mechanism_universe.py:160`). They do not prove the emitted post-neutralization/post-sector/post-optimizer book respects the declared caps.

Runtime whitelist gap, P0: `LoadedPortfolioLayerModule.consumes_mechanisms` exists (`src/feelies/alpha/portfolio_layer_module.py:127`), but the runtime ranker receives only caps and a global cap, not the whitelist (`src/feelies/composition/cross_sectional.py:154`). G16 rule 9 only validates dict-style dependencies with a `trend_mechanism_family` marker; a dependency without that marker is explicitly skipped (`tests/alpha/test_gate_g16.py:677`). The shipped PORTFOLIO YAMLs use string `depends_on_signals`, so runtime family enforcement is the only robust place to catch a mismatch (`alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:43`).

## 5. Optimizer determinism audit

### Default path

Bootstrap constructs the optimizer with `TurnoverOptimizer(capital_usd=capital_usd, lambda_tc=..., lambda_risk=...)` and does not pass `require_solver=True`, so the constructor default `require_solver=False` is active (`src/feelies/bootstrap.py:1965`, `src/feelies/composition/turnover_optimizer.py:137`). The public `optimize` method chooses the closed-form path whenever `_require_solver` is false (`src/feelies/composition/turnover_optimizer.py:177`, `src/feelies/composition/turnover_optimizer.py:184`).

The closed-form path is deterministic: it iterates the sorted `universe`, computes gross, scales to `capital * gross_cap`, clips per name, rounds target USD to cents, and shrinks post-rounding gross if needed (`src/feelies/composition/turnover_optimizer.py:210`, `src/feelies/composition/turnover_optimizer.py:213`, `src/feelies/composition/turnover_optimizer.py:217`, `src/feelies/composition/turnover_optimizer.py:225`, `src/feelies/composition/turnover_optimizer.py:230`). It returns `solver_status="CLOSED_FORM"` (`src/feelies/composition/turnover_optimizer.py:242`).

Modeling/implementation issue, P1: the default path is not a turnover optimizer in the objective sense. `lambda_tc` and `lambda_risk` are validated and passed through config (`src/feelies/core/platform_config.py:573`, `src/feelies/core/platform_config.py:931`, `src/feelies/bootstrap.py:1968`), but the closed-form path ignores both as penalties. Current positions are used only to report expected turnover, not to reduce turnover (`src/feelies/composition/turnover_optimizer.py:234`). This is deterministic, but economically ad hoc and can surprise operators who tune `composition_lambda_tc` expecting it to affect the desired book.

Modeling choice, P2: the fallback uses fixed construction caps of `gross_cap_pct=2.0` and `per_name_cap_pct=0.05` unless the object is constructed differently (`src/feelies/composition/turnover_optimizer.py:133`). Those are not exposed in `PlatformConfig`; the code comments explain they are composition-shaping parameters, not alpha risk budgets (`src/feelies/composition/turnover_optimizer.py:102`). This is coherent as a separation of concerns, but under-documented at the operator YAML level.

### CVXPY/ECOS path

The solver path is explicitly selected by `require_solver=True`, not by whether cvxpy happens to be installed (`src/feelies/composition/turnover_optimizer.py:93`, `src/feelies/composition/turnover_optimizer.py:147`, `src/feelies/composition/turnover_optimizer.py:177`). This is good for Inv-5 because optional extras do not silently alter production output.

The ECOS solve pins solver name, verbosity, tolerances, and max iterations (`src/feelies/composition/turnover_optimizer.py:301`). The pinned tolerance constants are defined in module scope (`src/feelies/composition/turnover_optimizer.py:50`). Solver failure falls back to the deterministic closed-form allocation with a distinct status (`src/feelies/composition/turnover_optimizer.py:309`, `src/feelies/composition/turnover_optimizer.py:317`, `src/feelies/composition/turnover_optimizer.py:322`). Non-optimal status returns empty allocation (`src/feelies/composition/turnover_optimizer.py:324`).

Library nondeterminism risk, P1/P0 if enabled in production: the local solver-path parity test passed, and the test locks a successful `require_solver=True` stream (`tests/determinism/test_sized_intent_solver_replay.py:51`, `tests/determinism/test_sized_intent_solver_replay.py:95`). However, it is a same-environment replay test; it does not assert bit-identical results across ECOS builds, OSes, or BLAS/LAPACK builds (`tests/determinism/test_sized_intent_solver_replay.py:13`). If the solver path becomes production-active, any cross-platform drift becomes P0 because `target_positions` and downstream Level-4 orders can change.

### Ordering and rounding

Decision variables are ordered by `universe` in both closed-form and solver paths (`src/feelies/composition/turnover_optimizer.py:261`, `src/feelies/composition/turnover_optimizer.py:332`). `CompositionEngine` builds `TargetPosition`s from `sorted(opt.target_usd.items())` (`src/feelies/composition/engine.py:374`).

Target USD is rounded to cents with Python `round(..., 2)` in both paths (`src/feelies/composition/turnover_optimizer.py:225`, `src/feelies/composition/turnover_optimizer.py:333`). Risk-layer share conversion is deterministic and uses `Decimal(...).to_integral_value(rounding=ROUND_HALF_UP)` (`src/feelies/risk/sized_intent_orders.py:117`). Thus float-to-quantity rounding is deterministic at the risk boundary, but target-dollar rounding remains binary-float cents rounding.

## 6. Neutralization / sector audit

### Factor-loading ingestion and staleness

`PlatformConfig` defaults to static-at-bootstrap factor loadings with `factor_loadings_refresh_seconds = 0` and a 7-day max age (`src/feelies/core/platform_config.py:545`, `src/feelies/core/platform_config.py:570`). Bootstrap bypasses freshness when `factor_loadings_dir` is `None`; otherwise it requires `loadings.json`, parses JSON, uses embedded `_meta.as_of_ns` if present, then falls back to file mtime (`src/feelies/bootstrap.py:2212`, `src/feelies/bootstrap.py:2217`, `src/feelies/bootstrap.py:2221`, `src/feelies/bootstrap.py:2229`). When `session_open_ns` is absent it falls back to `time.time()` and logs that this breaks bit-identical replay (`src/feelies/bootstrap.py:2241`, `src/feelies/bootstrap.py:2244`).

The committed fixture has no `_meta` block; it starts directly with symbol keys. The builder supports `--as-of-ns`, but leaves it omitted by default so committed bytes stay stable (`scripts/build_reference_factor_loadings.py:177`, `scripts/build_reference_factor_loadings.py:197`). Integration tests use a 100-year max-age constant because the committed file has a real mtime that ages (`tests/integration/portfolio_test_constants.py:3`, `tests/integration/portfolio_test_constants.py:12`). This is a P1 reproducibility/staleness tradeoff: deterministic bytes, but no content-level as-of date.

The freshness check ensures every universe symbol has a row only when `factor_loadings_dir` is configured (`src/feelies/bootstrap.py:2259`). Inside `FactorNeutralizer`, absent symbol/factor entries are zero-filled (`src/feelies/composition/factor_neutralizer.py:172`, `src/feelies/composition/factor_neutralizer.py:190`). Bootstrap row checks make missing rows fail-stop in normal configured deployments; missing factor columns remain zero-fill modeling choices.

### Neutralization math

The neutralizer implements projection residualization `w_neutral = w - B beta`, solving normal equations and falling back to least squares on singular matrices (`src/feelies/composition/factor_neutralizer.py:151`, `src/feelies/composition/factor_neutralizer.py:156`, `src/feelies/composition/factor_neutralizer.py:159`). This is mathematically standard for factor exposure residualization. Degenerate matrices report residual exposures instead of pretending they are zero (`src/feelies/composition/factor_neutralizer.py:160`, `src/feelies/composition/factor_neutralizer.py:163`).

Implementation bug, P0: the alpha-level disclosure is not honored as an opt-out. G11 requires `factor_neutralization` to be a boolean disclosure (`src/feelies/alpha/layer_validator.py:488`). The loader stores the boolean (`src/feelies/alpha/loader.py:625`), but bootstrap builds one global `FactorNeutralizer` from platform config (`src/feelies/bootstrap.py:1953`), and the engine always calls `self._neutralizer.neutralize(...)` for default-pipeline alphas (`src/feelies/composition/engine.py:351`). Therefore `factor_neutralization: false` only opts out when `factor_loadings_dir` is absent. If an operator sets a global loadings directory, the two research alphas that declare false are still neutralized (`alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:61`, `alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:69`).

Implementation bug, P1: `factor_exposures` recorded on the intent are pre-sector and pre-optimizer. The engine captures exposures from `FactorNeutralizer.neutralize`, then changes weights via `SectorMatcher` and `TurnoverOptimizer`, but passes the original exposures to `SizedPositionIntent` (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:355`, `src/feelies/composition/engine.py:368`, `src/feelies/composition/engine.py:406`). If sector matching or per-name caps alter weights, the intent's exposures are not the exposures of the desired book.

### Sector matching

`SectorMatcher` is globally activated when `sector_map_path` is set; otherwise it returns weights unchanged (`src/feelies/composition/sector_matcher.py:69`, `src/feelies/composition/sector_matcher.py:82`). The algorithm buckets by sector and scales only the dominant side so within-sector net exposure goes to zero, or to zero gross when a sector is one-sided (`src/feelies/composition/sector_matcher.py:95`, `src/feelies/composition/sector_matcher.py:102`, `src/feelies/composition/sector_matcher.py:109`). This is deterministic and conservative on one-sided sectors.

Modeling/implementation issue, P1: sector matching can reintroduce factor exposure and change realised mechanism shares because it is applied after factor neutralization and after pre-transform mechanism capping (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:355`). There is no post-sector re-neutralization or post-sector cap check.

## 7. decision_basis_hash & provenance audit

`SizedPositionIntent` carries `decision_basis_hash` as an additive provenance digest over canonical inputs (`src/feelies/core/events.py:722`). The default pipeline populates it (`src/feelies/composition/engine.py:389`, `src/feelies/composition/engine.py:410`). Degenerate intents and custom alphas can leave it empty by default (`src/feelies/core/events.py:727`).

What is currently hashed:

- `strategy_id`, `ctx.horizon_seconds`, `ctx.boundary_index` (`src/feelies/composition/engine.py:74`).
- For each symbol in `ctx.universe`: `raw_score`, `decay_factor`, assigned mechanism name, and current position USD (`src/feelies/composition/engine.py:75`, `src/feelies/composition/engine.py:81`).
- Global mechanism cap and per-family caps (`src/feelies/composition/engine.py:82`, `src/feelies/composition/engine.py:84`).

Undercoverage, P0:

- The hash omits the factor model identifier, factor loadings content/hash, and whether the alpha opted into neutralization, even though neutralization can change `target_positions` (`src/feelies/composition/engine.py:351`, `src/feelies/composition/factor_neutralizer.py:146`).
- The hash omits sector map content/hash and sector matching tolerance, even though sector matching can change weights (`src/feelies/composition/engine.py:355`, `src/feelies/composition/sector_matcher.py:95`).
- The hash omits optimizer path (`CLOSED_FORM` vs ECOS), `capital_usd`, gross cap, per-name cap, `lambda_tc`, and `lambda_risk`, even though optimizer output changes with those parameters (`src/feelies/composition/turnover_optimizer.py:129`, `src/feelies/composition/turnover_optimizer.py:177`, `src/feelies/composition/engine.py:368`).
- The hash formats current positions to two decimals (`src/feelies/composition/engine.py:81`), while optimizer inputs are floats and could differ below one cent before rounding decisions change around thresholds (`src/feelies/composition/engine.py:360`).
- The hash is not included in the Level-3 parity serialization (`tests/determinism/test_sized_intent_replay.py:180`), so a broken or empty hash would not fail those locked tests.

Correlation IDs are deterministic and sequence-stamped. Non-degenerate intents use `intent:{alpha_id}:{horizon_seconds}:{boundary_index}`, degenerate intents append `:degenerate`, and sequence comes from a dedicated generator (`src/feelies/composition/engine.py:257`, `src/feelies/composition/engine.py:260`, `src/feelies/composition/engine.py:296`). This is unique per `(alpha_id, horizon_seconds, boundary_index, degeneracy)` under unique alpha IDs. The audit request text mentioned `intent:<alpha_id>:<boundary_index>`; the implemented format includes `horizon_seconds`, which is stronger (`src/feelies/composition/engine.py:261`).

`CrossSectionalTracker` records latest gross/net, turnover, factor exposures, mechanism breakdown, and completeness per strategy without wall-clock reads (`src/feelies/portfolio/cross_sectional_tracker.py:122`, `src/feelies/portfolio/cross_sectional_tracker.py:140`). It parses boundary index from correlation IDs defensively (`src/feelies/portfolio/cross_sectional_tracker.py:169`). This is deterministic, but it inherits the pre-veto mechanism breakdown caveat from the risk-engine contract (`.cursor/skills/risk-engine/SKILL.md:115`).

## 8. Test gap matrix

| Invariant / risk | Current coverage | Status | Gap |
|---|---|---:|---|
| Context fan-in emits once per universe tick | `test_emits_one_context_per_universe_tick`, idempotence test (`tests/composition/test_synchronizer.py:67`, `tests/composition/test_synchronizer.py:120`) | Covered | No explicit cross-horizon ordering hash across simultaneous horizons. |
| Completeness below threshold fail-safe | Engine degenerate tests (`tests/composition/test_engine.py:121`, `tests/composition/test_engine.py:141`) | Partial | No stale-age TTL test; old cached signals can count by design (`src/feelies/composition/synchronizer.py:344`). |
| Causality, no future signal capture | Code filters future timestamps (`src/feelies/composition/synchronizer.py:254`, `src/feelies/composition/synchronizer.py:334`) | Partial | No test injects future signals or validates fallback to earlier causal candidate. |
| Decay weighting changes construction | Decay-on/off hash non-collision test (`tests/determinism/test_sized_intent_with_decay_replay.py:57`) | Covered for target stream | Does not assert `decision_basis_hash` changes because parity serialization omits it (`tests/determinism/test_sized_intent_replay.py:180`). |
| Ranker zero-variance and deterministic replay | Ranker deterministic replay test (`tests/composition/test_cross_sectional.py:211`) | Partial | No property test over single-symbol/all-equal universes and caps together. |
| Mechanism caps at emit | Ranker cap test and no-op integration cap test (`tests/composition/test_cross_sectional.py:187`, `tests/integration/test_mixed_mechanism_universe.py:219`) | Partial | No post-factor/post-sector/post-optimizer cap test; no mixed-mechanism same-symbol contribution test. |
| Consumes whitelist | Static dict-style G16 tests (`tests/alpha/test_gate_g16.py:642`) | Partial | Actual string `depends_on_signals` YAML path is not runtime-policed (`tests/alpha/test_gate_g16.py:677`). |
| Factor neutralization disclosure | Loader/validator tests require boolean (`tests/composition/test_portfolio_loader.py:88`) | Partial | No test proves `factor_neutralization: false` disables the global neutralizer when loadings are configured. |
| Factor loadings freshness | `_meta.as_of_ns`, missing row tests (`tests/bootstrap/test_factor_loadings_freshness.py:44`, `tests/bootstrap/test_factor_loadings_freshness.py:77`) | Covered for function | Committed fixture lacks `_meta`, and integration tests bypass mtime drift with a huge max age (`tests/integration/portfolio_test_constants.py:12`). |
| Sector matching correctness | Sector matcher unit tests exist (`tests/composition/test_sector_matcher.py:26`) | Partial | No test verifies sector matching preserves mechanism caps or recomputes factor exposures. |
| Default optimizer determinism | Closed-form Level-3 parity (`tests/determinism/test_sized_intent_replay.py:212`) | Covered in one environment | Does not assert `lambda_tc`/`lambda_risk` affect output, because default path ignores them. |
| CVXPY solver determinism | Solver-path parity test passed locally (`tests/determinism/test_sized_intent_solver_replay.py:95`) | Partial | No cross-platform/BLAS assertion; test skipped when cvxpy missing (`tests/determinism/test_sized_intent_solver_replay.py:45`). |
| Level-4 per-leg order determinism | Portfolio order replay and lex-sort tests (`tests/determinism/test_portfolio_order_replay.py:112`, `tests/determinism/test_portfolio_order_replay.py:140`) | Covered | Downstream realized exposure can differ after veto; that is risk-layer scope. |
| `decision_basis_hash` coverage | Field exists and default pipeline populates it (`src/feelies/core/events.py:722`, `src/feelies/composition/engine.py:389`) | Missing | No comprehensive input coverage test; no parity serialization of the field. |

Minimal new test specs:

- Golden intent hash with `decision_basis_hash`: extend Level-3 serialization to include `decision_basis_hash` and assert decay-on/off hashes differ in that field as well as in target stream.
- Stale completeness fail-safe: publish a signal from boundary 1, skip fresh signal through boundary N, publish a universe tick, and assert completeness drops below threshold once an explicit max-age is exceeded.
- Runtime whitelist: build a PORTFOLIO alpha consuming only KYLE_INFO, inject an INVENTORY feeder signal through `signals_by_strategy_by_symbol`, and assert the decision is degenerate or the signal is excluded.
- Post-pipeline mechanism cap property: generate two mechanisms plus a factor/sector transform that changes relative gross, and assert final emitted `mechanism_breakdown` cannot exceed caps.
- `factor_neutralization: false` opt-out: configure `factor_loadings_dir`, load an alpha with false, and assert output equals the no-op neutralizer path.
- Solver environment guard: record ECOS/cvxpy/numpy versions and solver status in the parity fixture, and run on at least macOS arm64 and Linux x86_64 CI before enabling solver in production.

## 9. Prioritized backlog

### P0

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| Honor factor-neutralization opt-out | `engine.py`, `bootstrap.py`, `portfolio_layer_module.py` | `factor_neutralization_disclosed` stored but engine always neutralizes (`src/feelies/alpha/loader.py:625`, `src/feelies/composition/engine.py:351`) | M | Thread the alpha boolean into `run_default_pipeline` and choose a no-op neutralizer when false, or instantiate per-alpha pipeline components. | Prevents declared opt-outs from being silently overridden by global loadings config. |
| Expand `decision_basis_hash` | `engine.py`, determinism tests | Hash omits factor/sector/optimizer inputs (`src/feelies/composition/engine.py:74`, `src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:368`) | M | Hash canonical serialized inputs including factor loadings digest, sector map digest, optimizer parameters/path/status, config knobs, and final target construction inputs; serialize it in parity tests. | Makes Inv-5/Inv-13 falsifiable for the actual desired-book decision. |
| Enforce caps after full pipeline | `cross_sectional.py`, `engine.py` | Pre-transform cap then final breakdown only diagnostic (`src/feelies/composition/cross_sectional.py:252`, `src/feelies/composition/engine.py:380`) | M | Re-apply caps on final dollar targets or optimize separate mechanism sleeves and combine only after caps are satisfied. | Converts G16 rule 8 from cosmetic/preliminary to true emit-time enforcement. |
| Split multi-feeder mechanism attribution | `cross_sectional.py` | Single `best_mech` gets whole symbol gross (`src/feelies/composition/cross_sectional.py:314`, `src/feelies/composition/cross_sectional.py:332`) | L | Carry per-symbol, per-mechanism contribution weights through ranking and cap each sleeve before aggregation. | Prevents mixed-family gross from being miscounted or assigned to the wrong cap bucket. |
| Add true stale-signal completeness gate | `synchronizer.py` | Old cached signals explicitly count (`src/feelies/composition/synchronizer.py:344`) | M | Define a per-feeder max age, drop stale signals before `non_none`, and emit degenerate intents below threshold. | Restores Inv-11 for stale data and prevents aged signals from inflating completeness. |
| Runtime consumes whitelist | `portfolio_layer_module.py`, `cross_sectional.py` | Whitelist exposed but not used (`src/feelies/alpha/portfolio_layer_module.py:127`, `src/feelies/composition/cross_sectional.py:181`) | S | Pass `consumes_mechanisms` to the ranker and exclude or fail degenerate on undeclared signal families. | Prevents undeclared mechanism families from entering a PORTFOLIO book. |

### P1

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| Make optimizer mode explicit in config | `PlatformConfig`, `bootstrap.py`, `turnover_optimizer.py` | Bootstrap never enables solver, closed-form ignores lambda penalties (`src/feelies/bootstrap.py:1966`, `src/feelies/composition/turnover_optimizer.py:184`) | M | Add `composition_optimizer_mode: closed_form|ecos` and document that lambda knobs bind only in solver mode. | Removes cosmetic optimizer knobs and prevents false confidence in turnover/risk tuning. |
| Recompute final factor exposures | `engine.py`, `factor_neutralizer.py` | Exposures captured before sector/optimizer (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:406`) | S | Compute exposures from final `target_positions` normalized back to weights, or rename the field as pre-sector residual exposure. | Keeps provenance aligned with the emitted desired book. |
| Embed loadings `_meta.as_of_ns` | `scripts/build_reference_factor_loadings.py`, fixture | Builder supports metadata, committed fixture omits it (`scripts/build_reference_factor_loadings.py:177`, `tests/integration/portfolio_test_constants.py:3`) | S | Rebuild reference JSON with a deterministic `as_of_ns` and remove test reliance on a 100-year mtime window. | Makes factor staleness reproducible across checkouts. |
| Cross-platform solver parity | CI/test harness | Same-environment solver test exists (`tests/determinism/test_sized_intent_solver_replay.py:95`) | M | Run solver parity on pinned macOS/Linux runners and record solver/library versions in failure output. | Quantifies whether ECOS is safe for Inv-5 beyond one host. |
| Add future-signal regression test | `tests/composition/test_synchronizer.py` | Code filters future timestamps but no test covers it (`src/feelies/composition/synchronizer.py:334`) | S | Inject a causal signal, then a future signal for the same key before tick, and assert no look-ahead plus desired fallback semantics. | Locks Inv-6 behavior under out-of-order event injection. |
| Align target-dollar rounding | `turnover_optimizer.py` | Uses float `round(..., 2)` (`src/feelies/composition/turnover_optimizer.py:225`) | S | Use `Decimal` cent rounding with a declared mode after solver/fallback values are computed. | Reduces subtle boundary drift around cent-level thresholds. |

### P2

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| Real risk model in optimizer | `turnover_optimizer.py` | Solver path uses identity risk diagonal (`src/feelies/composition/turnover_optimizer.py:269`) | L | Feed deterministic static covariance or diagonal vol estimates with artifact hashes. | Makes `lambda_risk` economically meaningful. |
| Sector taxonomy provenance | `sector_matcher.py`, reference builder | Sector map is static JSON with no as-of metadata (`scripts/build_reference_factor_loadings.py:15`) | S | Add `_meta` to sector map and include digest in `decision_basis_hash`. | Improves auditability of sector-neutral decisions. |
| Property-based cap tests | `tests/composition/` | Current cap tests are fixture-specific (`tests/composition/test_cross_sectional.py:187`) | M | Generate random deterministic mechanism sleeves and assert final caps under factor/sector/optimizer transforms. | Catches future cap regressions across edge cases. |
| Portfolio alpha purity guard | `alpha/loader.py` | Inline `construct` is executed from YAML code (`src/feelies/alpha/loader.py:669`, `src/feelies/alpha/loader.py:684`) | L | If custom PORTFOLIO alphas become production-used, apply the same purity/AST restrictions as signal evaluation. | Reduces custom-constructor nondeterminism and side-effect risk. |

## 10. Appendix: open questions needing data runs

1. What staleness window should define completeness for cross-horizon feeder signals: one feeder horizon, one portfolio horizon, or `expected_half_life_seconds`?
2. Should `factor_neutralization: false` mean "never neutralize this alpha" even under a global `factor_loadings_dir`, or only "disclose that the alpha does not require neutralization"?
3. Should mechanism caps apply to raw alpha contribution sleeves, final dollar gross, or risk-approved post-veto orders? The current risk-engine contract keeps `mechanism_breakdown` pre-veto (`.cursor/skills/risk-engine/SKILL.md:115`).
4. Is ECOS intended for production, or is the closed-form rescale the production path? If ECOS is intended, cross-platform parity must be proven before enabling it.
5. Should sector matching happen before or after factor neutralization? The current order can make factor-exposure reporting stale (`src/feelies/composition/engine.py:351`, `src/feelies/composition/engine.py:355`).
6. Should `decision_basis_hash` include final `target_positions` as well as inputs, or should a separate `target_book_hash` be added?
7. Should context emission be explicitly sorted across horizons with identical boundary timestamps, or is scheduler tick order already contractual enough for Inv-5?
