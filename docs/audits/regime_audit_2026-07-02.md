# Regime & Regime-Gate Audit

**Date:** 2026-07-02
**Mode:** Read-only evidence audit. No production code, configs, baselines, or ledgers changed.
**Scope:** `NBBOQuote -> RegimeState -> RegimeGate -> Signal -> risk/sizer -> OrderRequest`, including
hazard detection/exits, shipped alpha gates, platform defaults, and determinism tests.
**Predecessor:** `docs/audits/regime_audit_2026-06-20.md` (and 2026-06-13, 2026-06-11). This pass
re-verifies every prior finding against current `HEAD` and audits every regime-related commit that
landed since 2026-06-20 (`git log --since=2026-06-20` on the owned file set, ~110 commits total,
cross-referenced by `git log -S<symbol>` where file-level dates were ambiguous).
**Agent context:** `.cursor/rules/platform-invariants.mdc` (Inv-5, Inv-6, Inv-11 primary lenses),
`.cursor/rules/karpathy-guidelines.mdc`, `.cursor/skills/README.md`, owning skill
`.cursor/skills/regime-detection/SKILL.md`, touchpoints `.cursor/skills/microstructure-alpha/SKILL.md`
(regime-gate DSL) and `.cursor/skills/risk-engine/SKILL.md` (hazard exits, regime scaling).

## 1. Executive Summary

1. **No active P0** (Inv-5/Inv-7 single-writer; `src/feelies/kernel/orchestrator.py:3489`) in the
   regime engine / gate / hazard core. Single-writer discipline is structural, not just conventional:
   `git grep '\.posterior('` across `src/` returns exactly one call site, inside `_update_regime`
   (M2). All three requested read-only suites pass under the contractual `PYTHONHASHSEED=0` —
   71 + 97 + 6 = 174 tests (§9).
2. **Three 2026-06-20 P1 findings are now resolved** (Inv-11; `src/feelies/risk/hazard_exit.py:127-147`).
   (a) `hazard_exit.applies_to_regimes` is wired end-to-end — loader validation,
   `HazardPolicy.applies_to_regimes`, `_spike_matches_regimes`, bootstrap construction, and dedicated
   tests (`src/feelies/alpha/loader.py:1162-1210`, `src/feelies/bootstrap.py:2170-2189`) — landed
   same-day
   as the prior audit (`ff8530d`, 2026-06-20T06:46Z) but evidently not re-verified before that report
   shipped. (b) Dead hysteresis constants are now a strict load-time `RegimeGateError`
   (`src/feelies/signals/regime_gate.py:814-846`, commit `858c9f6`). (c) The `LIQUIDITY_STRESS`
   dynamic-direction entry gap is closed by a runtime backstop in `HorizonSignalEngine`
   (`src/feelies/signals/horizon_engine.py:573-590`, commit `bad7055`).
3. **New P1** (Inv-6; `src/feelies/signals/horizon_engine.py:291-336`) — the 2026-06-29
   horizon-boundary causality fix (`08c3da6`) is incomplete. It corrects *windowed/aggregated*
   Layer-2 features and the gate's OFF→ON latch to finalize at the exact nominal boundary
   (`asof_timestamp_ns`), but does not touch `HorizonSignalEngine._sensor_cache` or
   `SensorPassthroughFeature.finalize`
   (`src/feelies/features/impl/sensor_passthrough.py:81-89`) — both of which are documented,
   sanctioned binding sources for bare `<sensor_id>` regime-gate identifiers
   (`src/feelies/bootstrap.py:1788-1795`). Raw sensor gate bindings can still resolve to a value
   timestamped after the nominal horizon boundary (Inv-6) — see §4.2.
4. **New P2 — two independently-developed commits added duplicate boundary-timestamp fields.**
   `08c3da6` (causality fix) and `8645bcb` (ENG-1 labeling) were authored on parallel branches off
   the same parent and merged via `8146a58` without deduplication:
   `HorizonTick.boundary_timestamp_ns` and `HorizonTick.boundary_ts_ns` (ditto on
   `HorizonFeatureSnapshot`) now coexist with overlapping purpose. Currently synced — both are set
   from the same local (`horizon_scheduler.py:304,323,326`) — but nothing enforces the invariant;
   a future direct-construction call site could silently desync them. See §4.2.
5. **New P1** (Inv-4 decay-is-the-default; `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110-119`)
   — no production gate's `off_condition` references its own alpha's primary driver. Across all four
   shipped SIGNAL alphas, `off_condition` checks only
   `P(normal)` / `spread_z_30d` / `realized_vol_30s_zscore` — never `ofi_ewma`, `book_imbalance`,
   `hawkes_intensity`, `trade_through_rate`, or `kyle_lambda_60s_zscore` reversing. The regime gate
   is uniformly a *regime/volatility circuit breaker*, never a *signal-decay exit*. Only 1 of 4
   (`sig_hawkes_burst_v1`) opts into `hazard_exit`. "Structural invalidation" and "time decay,"
   both named exit triggers in `.cursor/skills/microstructure-alpha/SKILL.md`, are therefore not
   mechanically enforced for 3 of 4 production alphas. See §4.4, §7.2.
6. **New P2 — `failure_signature` is free text, not cross-checked against the compiled gate.** Two
   of three `P(normal)`-style alphas declare `"P(vol_breakout) > 0.5"` as an invalidator
   (`sig_benign_midcap_v1`, `sig_hawkes_burst_v1`) but neither `off_condition` references
   `P(vol_breakout)` directly — both rely on the empirically-correlated `spread_z_30d` /
   `realized_vol_30s_zscore` raw sensors instead. `sig_kyle_drift_v1` declares
   `"kyle_lambda_60s_zscore < -1.5"` as an invalidator that its `off_condition` never checks at all.
   See §4.4.
7. **New P2 (documentation only) — `RegimeGate.evaluate()`'s precedence docstring is backwards.**
   It states "hysteresis > params > dynamic sensors" (`regime_gate.py:724-729`), but the merge line
   itself (`{**self._params, **bindings.sensor_values, **self._hysteresis}`) and the platform's own
   test (`test_real_sensor_overrides_param_constant`, `tests/signals/test_regime_gate_dsl.py:596`)
   both show sensors override params, not the reverse. Zero current blast radius — no shipped alpha
   has a param name colliding with a sensor id — but a footgun for a future "fix." See §4.3.
8. **New P2 — `sig_moc_imbalance_v1` gates on exact float equality** (`scheduled_flow_window_active
   == 1.0` / `== 0.0`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:131,133`) while
   its own `evaluate()` explicitly hedges the same value with `active < 0.5` and a comment
   anticipating "any future interpolation/fractional-active variant." See §4.4.
9. **Positive findings worth naming.** The engine is honestly self-documented as a fixed-structure
   forward filter, not Baum-Welch (`regime_engine.py:130-135`); `discriminability` /
   `discriminability_for_symbol` fail-safes are wired through the gate and orchestrator with the
   correct per-symbol-over-pooled preference (`orchestrator.py:3498-3509`); checkpoint/restore now
   fingerprints every constructor flag that affects posteriors (`regime_engine.py:566-599`, schema
   v2); the risk engine and sizer both clamp their EV-over-posterior scale at `1.0` **at the value
   level**, not by config convention (`basic_risk.py:833-837`, `position_sizer.py:130-137`); and the
   orchestrator's hazard-order bridge distinguishes an *authoritative* REJECT (non-reducing order)
   from a *defensive* REJECT (reducing order, submitted anyway per the Inv-11 exit fail-safe) —
   `orchestrator.py:6294-6357`.
10. **Two 2026-06-20 P1s remain open** (Inv-5/Inv-11; `platform.yaml:172,47-62`) but are now
    explicitly, deliberately deferred. `regime_min_discriminability: 0.0` (no-op) and
    `transition_time_scaling_enabled: false` are unchanged — but the file now carries an explicit,
    reasoned comment block (lines 47-62) explaining the deferral is intentional: cohort-specific
    tuning is required and flipping the default would invalidate every locked Level-5/6 determinism
    baseline. This reads as an informed operator decision, not an oversight.
11. **`sig_inventory_revert_v1` is QUARANTINED (`lifecycle_state: RESEARCH`) by its own
    forward-return study**, yet carries the platform's most sophisticated regime gate (dominant-state
    check + dual-posterior thresholds + hysteresis margins + parameter-referenced literals,
    `sig_inventory_revert_v1.alpha.yaml:176-186`). Good evidence that gate-engineering quality and
    alpha economic validity are orthogonal, and that the platform's falsification discipline is
    exercised for real (near-zero IC, contrarian leg possibly inverted-sign — see its own `notes:`
    block) rather than merely documented.
12. **`scripts/regime_diagnostics.py` already implements most of what this audit's methodology
    section (§7.4) would otherwise have to propose from scratch** — discriminability reporting,
    gate-clause pruning effect, and forward-return-by-`P(vol_breakout)`-decile with explicit
    no-lookahead handling. Its own docstring calls it "the merge gate the second pass (R-2)
    requires." No evidence in-repo that it has been run against the four currently-shipped gates.
13. **Test coverage is strong on DSL safety, determinism, and the three 06-20 remediations**, but
    mostly syntactic. Exactly one property test encodes a genuine economic invariant —
    `test_shipped_gate_has_non_empty_hold_band` (whipsaw/chatter prevention) — and it covers 3 of 4
    production alphas (`tests/signals/test_regime_gate_dsl_props.py:269-292`). See §8.
14. **Consumer coherence gap is unchanged since 06-20 (files not touched):** the gate uses hard
    posterior thresholds; risk and sizer use EV-smoothed posteriors clamped at `1.0`, in series
    (sizer proposes, risk caps — not compounding). A signal can be gate-eligible in a regime the
    risk layer is already discounting. See §6.
15. **No path was found where regime state amplifies exposure above baseline.** Every degenerate
    path traced (uncalibrated, indiscriminate/low-separation, unknown state name, missing posterior,
    engine absent, hazard non-reducing order) resolves to gate-OFF, minimum-scale, or an
    authoritative REJECT — matching Inv-11.

## 2. Regime Stack Inventory

### 2.1 Runtime flow (unchanged shape since 06-20; causality of two edges changed — see §4.2)

| Stage | Component | Regime input | Output | Fail-safe default |
|---|---|---|---|---|
| M2 | `RegimeEngine.posterior()` — sole call site `orchestrator.py:3489` | `NBBOQuote` | `RegimeState` | Uncalibrated → `calibrated=False`; low-separation → gate treats as unavailable (`regime_gate.py:410-450`) |
| M2 | `RegimeHazardDetector.detect()` — `orchestrator.py:3581` | prev/curr `RegimeState` | `RegimeHazardSpike?` | No spike on cold start, non-decay, or suppressed episode (`regime_hazard_detector.py:213-239`) |
| Gate | `RegimeGate.evaluate()` | `RegimeState` + snapshot/sensor bindings | ON/OFF latch | Cold start OFF; any binding/arithmetic error forces OFF + unwind (`horizon_engine.py:412-506`) |
| Signal | `HorizonSignalEngine._dispatch_one` | gate + snapshot | `Signal｜None` | Entry suppressed on warm/stale or entry-blocked-mutate=False; exit-only mechanisms backstopped (`horizon_engine.py:372-411,573-590`) |
| Sizer | `BudgetBasedSizer._get_regime_factor` | `current_state()` EV | capital scalar | No engine → `1.0`; engine w/o posterior → min factor; EV clamped ≤ `1.0` (`position_sizer.py:111-137`) |
| Risk | `BasicRiskEngine._regime_scaling` | `current_state()` EV | limit multiplier | Same shape, independently implemented (`basic_risk.py:790-837`) |
| Hazard | `HazardExitController` | `RegimeHazardSpike` | flatten `OrderRequest` | No position / below threshold / below min-age / regime-filtered → no action (`hazard_exit.py:210-256,260-316`) |
| Kernel bridge | `Orchestrator._on_bus_hazard_order` | hazard `OrderRequest` | router submit | Non-reducing order + REJECT → blocked (authoritative); reducing order + REJECT → submitted anyway (defensive Inv-11) (`orchestrator.py:6294-6357`) |

### 2.2 Engines and defaults (unchanged since 06-20 — `regime_engine.py` only touched by
`3b528df`, a formatting-only commit)

| Engine | Status | Observation | Notes |
|---|---|---|---|
| `hmm_3state_fractional` | Default | `log(spread / mid)` | Fixed-structure forward filter (not EM/Baum-Welch), `regime_engine.py:127-163` |
| `hmm_3state_spread_filter` | Alias | Same class | `regime_engine.py:1268` |
| `hmm_3state_spread_vol` | Opt-in | Spread + realized-vol of mid, 2-D diagonal Gaussian | `HMM3StateSpreadVol`, `regime_engine.py:859-1260`; gated behind `scripts/regime_diagnostics.py` validation per its own docstring |

| Config | Current value | Effect |
|---|---|---|
| `regime_engine` | `hmm_3state_fractional` (`platform.yaml:41`) | Spread-only taxonomy |
| `regime_calibration_max_quotes` | `100000` (`platform.yaml:162`) | Bootstrap prefix calibration; code default `None` would mark uncalibrated |
| `regime_min_discriminability` | `0.0` (`platform.yaml:172`) | No-op floor — unchanged since 06-20 |
| `transition_time_scaling_enabled` | commented-out / off (`platform.yaml:47-62`) | Tick-time dwell, not wall-clock — unchanged since 06-20, now with an explicit deferral rationale in-file |
| `per_symbol_calibration` | commented-out / off (`platform.yaml:61`) | Pooled emissions only |
| `enforce_regime_state_scale_alignment` | `False` (`platform_config.py:407`) | Boot-time state-name/risk-scale-map alignment check exists (`bootstrap.py:847-861`) but is opt-in |

### 2.3 Shipped alpha gate inventory

| Alpha | Family | Horizon | Gate | Hazard exit | Lifecycle |
|---|---:|---:|---|---|---|
| `sig_benign_midcap_v1` | `KYLE_INFO` | 120 s | `P(normal)>0.5 and spread_z_30d<1.5` ON / `P(normal)<0.35 or spread_z_30d>3.0 or realized_vol_30s_zscore>4.5` OFF | No | LIVE-eligible |
| `sig_kyle_drift_v1` | `KYLE_INFO` | 300 s | `P(normal)>0.6 and spread_z_30d<=1.0` ON / `P(normal)<0.4 or spread_z_30d>2.0 or realized_vol_30s_zscore>3.5` OFF | No | LIVE-eligible |
| `sig_hawkes_burst_v1` | `HAWKES_SELF_EXCITE` | 30 s | `P(normal)>0.6 and spread_z_30d<1.0` ON / `P(normal)<0.4 or spread_z_30d>2.5 or realized_vol_30s_zscore>3.5` OFF | Yes, threshold `0.30` | LIVE-eligible |
| `sig_inventory_revert_v1` | `INVENTORY` | 30 s | `abs(asym_z)>thr and dominant=="normal" and P(normal)>0.65 and P(vol_breakout)<0.20` ON / 7-clause OFF incl. `posterior_margin`/`percentile_margin` hysteresis | No | **QUARANTINED (RESEARCH)** — own forward-IC study found no edge |
| `sig_moc_imbalance_v1` | `SCHEDULED_FLOW` | 120 s | Pure schedule gate — no `P()`/`dominant`/`entropy` reference (self-documented, `sig_moc_imbalance_v1.alpha.yaml:120-127`) | No | LIVE-eligible |
| `_paper_smoke_v1` | smoke | n/a | Always-true smoke gate | No | Smoke only |

Portfolio composition (`src/feelies/composition/`) has **zero** references to `RegimeState`,
`regime_engine`, `current_state`, `RegimeHazardSpike`, or `posterior` (`grep -rl` across the package
returns no files) — confirms the 06-20 finding unchanged: composition consumes mechanism tags/caps,
not regime posteriors, directly.

## 3. RegimeEngine Audit

`regime_engine.py` and `regime_hazard_detector.py` are byte-identical in substance to the 06-20
snapshot (only a repo-wide `ruff format` touched `regime_engine.py`; `regime_hazard_detector.py` has
zero commits since). The math audited in the prior report stands; this section confirms it against
current `HEAD` and adds two items the prior report did not surface.

### 3.1 Model class

`HMM3StateFractional` is a **deterministic, fixed-structure forward filter** (Markov predict +
diagonal-Gaussian update), not a Baum–Welch/EM-fit HMM — the class docstring says so explicitly
(`regime_engine.py:130-135`), correctly distinguishing itself from Hamilton (1989) / Kim (1994)
parameter-uncertain Markov-switching models and from Rabiner (1989)-style trained HMMs. `calibrate()`
fits emission moments from quantile buckets of `log(spread/mid)` (`regime_engine.py:405-423`); the
transition matrix is author-controlled unless time-scaling reshapes it. This is an accurate
self-classification, not an overclaim.

### 3.2 Calibration

- `_MIN_CALIBRATION_SAMPLES = 30` (`regime_engine.py:188`) remains a small floor for fitting three
  Gaussian buckets (~10 points/bucket at the floor) — carried over from 06-11/06-13, still open,
  low urgency because `platform.yaml`'s 100k-quote prefix cap (`platform.yaml:162`) makes the floor
  rarely binding in practice. **P2, unchanged.**
- Quantile-bucket fitting from *sorted* data means bucket *k*'s mean is mechanically ≥ bucket
  *k-1*'s mean by construction, so `_sort_emissions_by_mean` (`regime_engine.py:425-430`) is a
  redundant safety net, not dead code — it only matters for `per_symbol_calibration`'s per-symbol
  fits where a thin symbol's bucket ordering could theoretically invert. No bug found.
- The pairwise-separation gate (`_emissions_pass_pairwise_gate`, `regime_engine.py:457-473`) now
  **soft-fails**: a calibration that fails separation keeps the constructor-default emissions and
  returns `False` rather than leaving the engine permanently uncalibrated-and-silently-warning
  forever (`regime_engine.py:349-369`, "audit P2 E-4"). This is a real, well-reasoned improvement
  over a naive hard-fail.

### 3.3 Transition dynamics

The time-scaling transform (`_scale_transition_matrix`, `regime_engine.py:783-817`) raises each
row's self-transition probability to `scale = clip(dt/dt_ref, min, max)` and renormalizes the
off-diagonal mass proportionally. This is a **per-row power-scaling heuristic**, not a principled
continuous-time-Markov-chain (CTMC) generator-matrix exponentiation (`T(dt) = expm(Q·dt)`,
`Q = logm(T_ref)/dt_ref`) — the latter would preserve the full eigenstructure/relative-rate
relationships between off-diagonal transitions; the former only preserves row-stochasticity and
monotonicity in `dt`. Given the shipped matrix's off-diagonal mass is tiny relative to
self-persistence (~0.99 vs ~0.005-0.008 per `_DEFAULT_TRANSITION`, `regime_engine.py:171-175`), the
approximation error from skipping full CTMC exponentiation is second-order. **Classification: modeling
choice, not a bug** — but it is opt-in and off by default (§2.2), so it is currently inert in
production regardless.

### 3.4 Posterior update / idempotency / fail-safe

Unchanged from 06-20: idempotent per `(symbol, sequence)` (`regime_engine.py:502-503`); commit
posterior + seq watermark only after a fully successful update, so a mid-update exception leaves
both untouched and the next call re-runs rather than serving a phantom cache
(`regime_engine.py:545-554`); NaN/Inf in the Bayes update resets to uniform with a WARNING
(`regime_engine.py:535-543`) — fail-safe, at the cost of destroying information for that tick.
Invalid spread (`ask <= bid`) takes a **prediction-only** path (Markov predict, no emission update)
rather than crashing or fabricating a likelihood (`regime_engine.py:526-527`) — economically
justified: a locked/crossed quote carries no spread information to update on.

### 3.5 Discriminability (audit R-1, confirmed still wired)

`discriminability` / `discriminability_for_symbol` (`regime_engine.py:283-317`) expose the
calibration-time min pairwise separation `d = |μ_i-μ_j|/√(σ_i²+σ_j²)`; the orchestrator prefers the
**per-symbol** variant when the engine exposes it, falling back to the pooled property
(`orchestrator.py:3498-3509`) — this is the correct choice per the class's own docstring warning
(`regime_engine.py:299-303`): gating a tight symbol against a global `d` would falsely pass a
collapsed per-symbol fit. The gate treats a present-but-indiscriminate `RegimeState` identically to
an uncalibrated one — both raise `UnknownIdentifierError` and force OFF (`regime_gate.py:410-450`).
Correctly wired end-to-end; the only open item is the `regime_min_discriminability: 0.0` no-op
default (§2.2, unchanged from 06-20).

### 3.6 Checkpoint/restore (Inv-5; historical codename "audit P1 E-1"; `src/feelies/services/regime_engine.py:566-599`; confirmed still wired)

Schema v2 checkpoints carry a `flags_fingerprint` — a SHA-256 over every constructor flag that
changes how `posterior()` computes an update, including the transition matrix and state-name tuple
(`regime_engine.py:566-599`). `restore()` rejects a fingerprint mismatch outright
(`regime_engine.py:677-688`) and rolls back in-memory state on **any** failure, including a
non-restorable v1 legacy blob that at least warns about un-verifiable flags
(`regime_engine.py:656-676`). This closes exactly the "restore into a differently-configured engine
silently diverges replay" risk the 06-20 report's §4.5 flagged as a residual concern — confirmed
resolved (no git-log evidence of a recent change here, so it predates 06-20; the prior report simply
did not test the negative path explicitly).

### 3.7 `HMM3StateSpreadVol` (audit R-3, unused in production)

An opt-in 2-D engine (`regime_engine.py:859-1260`) observing `log(spread/mid)` **and** realized
mid-volatility over a rolling window, addressing the 06-13 audit's finding that the default engine's
`vol_breakout` state is a pure spread-widening proxy and cannot see volatility that arrives without
spread widening. It is deterministic (fixed-window realized vol, no wall-clock), warms gracefully
(vol dimension contributes likelihood `1.0` until `rv_min_returns` returns exist,
`regime_engine.py:1060`), and is not selected by any shipped `platform.yaml` or alpha. Its own
docstring correctly gates production adoption behind `scripts/regime_diagnostics.py` validation
(§7.4) rather than asserting it is an improvement.

## 4. RegimeGate Audit (deep dive)

### 4.1 DSL safety (parse-time, G2 purity)

The AST whitelist (`regime_gate.py:133-160`) is exhaustive over `ast.walk`, so nesting an unsafe
call inside a whitelisted one (e.g. `abs(evil())`) is still caught — validation is not shallow.
`Call` is whitelisted at the node-type level but independently restricted at `_validate`
(`regime_gate.py:267-291`): callee must be a bare `Name` in `{abs, min, max, P}`, no keyword
arguments, and `P(...)` must take exactly one bare-identifier argument. No gap found; this matches
the 06-20 finding and the current test suite (`test_forbidden_expressions_always_raise`,
`test_compiled_tree_contains_only_whitelisted_nodes`,
`tests/signals/test_regime_gate_dsl_props.py:115,197`).

Arithmetic/type errors at evaluation time (`ZeroDivisionError`, `ArithmeticError`, `TypeError`,
`ValueError` — e.g. a stray `x / sensor_y` or `dominant < 1`) are caught by a dedicated exception
branch (Inv-11; `src/feelies/signals/horizon_engine.py:474-506`, historical codename "audit P1 G-1")
in `HorizonSignalEngine._dispatch_one` that forces the gate OFF and unwinds any open position. This
closes exactly the "residual edge" the
06-20 report flagged as merely "acceptable" (§5.1 of that report) — confirmed as a real, tested
fail-safe path, not a gap.

### 4.2 Causality (Inv-6) — the section's primary new finding

**Confirmed fixed:** `08c3da6` (2026-06-29, "Fix horizon boundary as-of time for feature snapshots
and gate latches") introduced `HorizonTick.boundary_timestamp_ns` / `asof_timestamp_ns`
(`events.py:606,617-620`) and changed `HorizonAggregator` and `HorizonWindowedFeature` to finalize
rolling-window reducers (`mean`, `rms`, `percentile`, `delta`, …) and the staleness check at the
**exact nominal boundary** rather than at `tick.timestamp_ns` (the triggering event's time, which on
a sparse tape lands strictly after the boundary) — `features/aggregator.py:474-476,507-513`,
`features/impl/horizon_windowed.py:286-328`. The commit message is explicit that the old behavior
"finalize[d] at... the post-boundary event time," and the fix required re-baking the APP backtest
baseline — i.e. it had measurable behavioral impact, not just a semantic cleanup.

The same commit added `RegimeGate.evaluate(mutate: bool = True)` (`regime_gate.py:700-748`) and wired
it from `HorizonSignalEngine._dispatch_one` as `mutate=not (entry_blocked and not was_on)`
(`horizon_engine.py:401-411`). Trace of what this fixes: before the change, a tick with
`entry_blocked=True` (a required feature is cold/stale) that also satisfied `on_condition` would
still **latch the gate ON** using bindings computed from data that the alpha itself was refusing to
trade on. On a later tick, once the same latch read `is_on()==True`, only `off_condition` would be
re-checked — meaning an entry could fire from a gate transition that was never freshly re-confirmed
on warm data. `mutate=False` prevents the OFF→ON transition from being *committed* while `was_on` is
`False` and entry is blocked (the return value is still computed, so downstream logic sees a
consistent boolean), while leaving `mutate=True` unconditionally whenever `was_on` is `True` — so the
ON→OFF exit path, and the gate-close FLAT it triggers, is never suppressed (matches Inv-11: exits
permitted when stale). This is a real, well-targeted fix for a genuine "phantom-armed gate"
causality risk; it is now correctly in place. One residual, low-severity artifact: the
`feelies.signal.gate.transition {to: ON}` metric (`horizon_engine.py:519-525`) still fires whenever
the *return value* flips `False→True`, even on a `mutate=False` call where the latch was not actually
persisted — a telemetry double-count on the next genuinely-warm tick, not a trading-safety issue.
**P2.**

**Not extended to two other sanctioned binding sources — this is the finding:**

1. `HorizonSignalEngine._sensor_cache` / `_on_sensor_reading` (`horizon_engine.py:291-336`) updates
   `self._sensor_cache[(symbol, sensor_id)]` unconditionally on **every** incoming `SensorReading`
   event, with no comparison against any boundary timestamp. `_build_bindings`
   (`horizon_engine.py:725-774`) uses this cache via `setdefault` as the resolution path for any
   `<sensor_id>` gate/signal identifier **not present in `snapshot.values`**. Per its own docstring
   (`horizon_engine.py:750-753`) this is not a rare corner case: "the aggregator runs in passive mode
   for v0.2 (`snapshot.values` is empty), so in that mode all bindings come from `sensor_cache`."
2. `SensorPassthroughFeature.finalize` (`features/impl/sensor_passthrough.py:81-89`) — the
   *standard* Layer-2 wrapper for exposing a raw sensor value into `snapshot.values` (its own module
   docstring: "these are the 'identity' features... they simply carry the most recent warm reading
   from Layer 1 into the Layer 2 snapshot") — ignores the `tick` argument entirely and returns
   whatever `state["value"]` currently holds. That state is updated by `observe()`, which
   `HorizonAggregator._on_sensor_reading` calls **synchronously, in real time, for every incoming
   `SensorReading`** (`features/aggregator.py:406-419`), independent of any horizon boundary —
   confirmed by direct trace of the aggregator's bus-subscriber path (`aggregator.py:345-419`
   vs. `421-464`). `TupleComponentFeature` and `TupleSignedImbalanceFeature` share the identical
   pattern.

Both paths are **documented, intentional design** — `bootstrap.py:1788-1795` explicitly names "the
engine's sensor cache (raw `SensorReading` pass-through via gate DSL)" as one of two valid resolution
targets for `depends_on_sensors`, alongside registered `HorizonFeature`s. Neither was touched by
`08c3da6`. The practical consequence: a gate expression referencing a bare `<sensor_id>` that either
(a) has no registered Layer-2 windowed feature, or (b) is wrapped only in a passthrough/identity
feature, can resolve to a value whose timestamp is strictly after the nominal horizon boundary —
exactly the class of leak `08c3da6`'s own commit message treats as worth a baseline rebake elsewhere
in the same pipeline.

**Severity and scoping.** I rate this **P1**, not **P0** (Inv-6; `src/feelies/signals/horizon_engine.py:291-336`),
for three reasons: (i) magnitude is bounded by
the gap between the nominal boundary and the next tick on the tape (not unbounded lookahead into
data that has not yet occurred on the replay tape — it is a boundary-*alignment* precision gap, not
a future-data leak); (ii) it does not amplify exposure or bypass any fail-safe — worst case is an
entry firing on data that is a few ticks fresher than its nominal label claims, still subject to
every other gate/risk check; (iii) the regime-state bindings the prompt asks me to prioritize
(`P(state)`, `dominant`, `entropy`) are **not** affected — this is scoped to *ancillary raw-sensor*
bindings used alongside them in compound gate expressions (e.g. `spread_z_30d` in
`sig_benign_midcap_v1`'s off-condition, if it is ever resolved via cache rather than a registered
feature). The root cause for item 2 (`SensorPassthroughFeature`, `features/aggregator.py`'s
`observe()`/`finalize()` timing model) sits in files owned by the `feature-engine`/`sensor` audit,
not this one; I am reporting the **consumer-side observation** (the regime gate can see this class of
data) with full evidence, and flagging the aggregator-side root cause as a cross-audit pointer rather
than deep-diving files outside this audit's ownership. Item 1 (`horizon_engine.py._sensor_cache`) is
squarely in-scope and I have complete, direct evidence for it (Inv-6).

**Recommendation:** extend the `08c3da6` as-of-boundary discipline to (a) `_sensor_cache` writes in
`HorizonSignalEngine._on_sensor_reading` — gate on `reading.timestamp_ns <= <the dispatching
snapshot's boundary>` at read time in `_build_bindings`, and (b) `SensorPassthroughFeature.finalize`
(and its two tuple siblings) — replay from the buffered readings up to `tick.asof_timestamp_ns`
instead of returning live-incrementally-updated state, matching what `HorizonWindowedFeature` now
does. **Effort: M** (touches two files across two audit ownership boundaries; needs a
determinism-baseline rebake per the `08c3da6` precedent).

### 4.3 Precedence bug in the `evaluate()` docstring (documentation only)

`RegimeGate.evaluate()`'s docstring states: "Precedence: hysteresis > params > dynamic sensors"
(`regime_gate.py:724-729`, added by `858c9f6`). The implementing line is:

```python
merged = {**self._params, **bindings.sensor_values, **self._hysteresis}
```

Python dict-merge semantics mean the **last**-applied mapping wins on a key collision, so the actual
precedence is `hysteresis > sensor_values > params` — sensors override params, the opposite of the
literal docstring claim for the params-vs-sensors pair. This is not ambiguous: the platform's own
test, `test_real_sensor_overrides_param_constant` (`tests/signals/test_regime_gate_dsl.py:596-604`),
constructs a case where the param value alone would evaluate `False` and the sensor value alone would
evaluate `True`, and asserts the gate returns `True` — i.e. sensor wins, exactly matching the code and
contradicting the docstring's literal ranking. `test_hysteresis_overrides_param_on_collision`
(`tests/signals/test_regime_gate_dsl.py:607-620`) confirms the hysteresis-beats-everything half of
the docstring is correct. **This is a pure documentation defect** — code and tests agree with each
other, only the prose disagrees with both — with zero current blast radius (no shipped alpha's
`parameters:` name collides with a `depends_on_sensors` entry), but it is exactly the kind of comment
that could lead a future contributor to "fix" the merge order to match the docstring, silently
breaking the tested (and, I think, correct — a live sensor reading should not be permanently shadowed
by a static declared default) behavior. **P2. Effort: S** (rewrite the docstring to state the actual
merge order, or state it as "insertion order below," not a ranked "precedence" list).

### 4.4 Per-alpha gate semantics (plain-English translation + coherence)

| Alpha | Plain-English gate | Coherence assessment |
|---|---|---|
| `sig_benign_midcap_v1` | "Trade the Kyle-style OFI/book-imbalance footprint only when regime mass favors `normal` (>50%) and spreads aren't already elevated (z<1.5); bail when `normal` mass drops below 35%, OR spread blows past 3σ, OR realized-vol z exceeds 4.5." | Coherent, conservative cost filter. `failure_signature` declares `"P(vol_breakout) > 0.5"` (`sig_benign_midcap_v1.alpha.yaml:171`) but `off_condition` never references `P(vol_breakout)` directly — relies on the correlated `spread_z_30d`/`realized_vol_30s_zscore` instead (§4.4.1). `off_condition` also never references `ofi_ewma`/`book_imbalance` reversing (§4.4.2). |
| `sig_kyle_drift_v1` | "Trade the 5-minute Kyle-λ drift only when `P(normal)>0.6` and spread is tight (≤1.0σ); bail below `P(normal)<0.4`, OR spread>2.0σ, OR vol-z>3.5." | Coherent. `failure_signature` declares `"kyle_lambda_60s_zscore < -1.5"` (`sig_kyle_drift_v1.alpha.yaml:144`) — the alpha's own primary driver collapsing/reversing — but this is checked only in `evaluate()`'s entry suppression (`lam_pct < floor`), never in `off_condition`, so an open position is not gate-driven-unwound purely from λ collapsing while the broader regime stays benign (§4.4.2). |
| `sig_hawkes_burst_v1` | "Ride a 30-second Hawkes self-excitation burst only when `P(normal)>0.6` and spread<1.0σ; bail below `P(normal)<0.4`, OR spread>2.5σ, OR vol-z>3.5; additionally hard-exit on a hazard score ≥0.30 (a low, sensitive threshold matched to the alpha's fast 30 s half-life)." | Coherent, and the only alpha with `hazard_exit` enabled — appropriately, given the shortest half-life family (`HAWKES_SELF_EXCITE`, 5-60 s envelope). `failure_signature` again declares `P(vol_breakout)>0.5` without a direct gate reference (§4.4.1). |
| `sig_inventory_revert_v1` | "Fade quote-replenishment asymmetry only when the dominant state is literally `normal`, `P(normal)>0.65`, AND `P(vol_breakout)<0.20` — the most conservative, `dominant`-plus-dual-posterior ON condition of any shipped alpha — with a genuine hysteresis band (`posterior_margin=0.20`, `percentile_margin=0.30`) referenced directly in a 7-clause OFF expression that also checks `quote_hazard_rate` and `realized_vol_30s_zscore`." | The best-engineered gate in the repo — and QUARANTINED at `lifecycle_state: RESEARCH` because the alpha's own forward-IC study found the mechanism does not hold (§1.11). Confirms gate quality is orthogonal to alpha validity; no gate defect found in the DSL itself. |
| `sig_moc_imbalance_v1` | "Participate only inside the scheduled MOC-imbalance window with >60 s of runway remaining; hold an open position until <30 s remain (a genuine, economically-sensible asymmetric entry/exit runway band), or vol spikes past 3.5σ." | Correctly self-documented as schedule-gated, not regime-gated (`sig_moc_imbalance_v1.alpha.yaml:120-127`) — no `P()`/`dominant`/`entropy` reference, confirmed by direct read. Uses **exact float equality** (`scheduled_flow_window_active == 1.0` / `== 0.0`, lines 131/133) while its own `evaluate()` explicitly hedges the identical value with `active < 0.5` and a comment anticipating a future fractional/interpolated variant (`sig_moc_imbalance_v1.alpha.yaml:174-177`). If the sensor ever emits a non-binary value, neither gate expression would fire and the latch would silently freeze in its last state rather than transitioning cleanly — safe-by-accident (hysteresis-shaped) rather than safe-by-design. **P2.** |

#### 4.4.1 `failure_signature` vs. `off_condition` — a platform-wide pattern, not a per-alpha slip

`trend_mechanism.failure_signature` entries are free-text strings (G16 rule 6 only requires a
non-empty list — `.cursor/skills/microstructure-alpha/SKILL.md` glossary: "non-empty LIST of
invalidator clauses"); nothing in the loader cross-validates them against the compiled
`regime_gate` AST. Two of the three `P(normal)`-style alphas declare a `P(vol_breakout)` invalidator
that is never referenced by their `off_condition`; the third (`sig_kyle_drift_v1`) declares a
different invalidator (`kyle_lambda_60s_zscore`) that is also absent from its `off_condition`
(§4.4.2). Because `P(vol_breakout)` rising is, by construction of the default engine's shared
spread-only emission, correlated with `spread_z_30d` rising — and every gate's `off_condition` *does*
check `spread_z_30d` — this is not currently an active safety gap; it is a **documentation/tooling
coherence gap**: nothing would catch an author who declares a `failure_signature` clause and forgets
to (or chooses not to) wire the corresponding runtime check. **P2. Recommendation:** either (a) have
the loader attempt to parse `failure_signature` clauses that look like valid gate-DSL expressions and
warn if none of them appear as a sub-expression of `off_condition`, or (b) rename/re-scope
`failure_signature` in the skill docs to explicitly state it is narrative/audit-facing only, not an
executable contract, so no one designs against a false assumption of enforcement. **Effort: S–M.**

#### 4.4.2 No gate references its own alpha's primary driver reversing

Across all four production gates, `off_condition` draws exclusively from `{P(normal), dominant,
spread_z_30d, realized_vol_30s_zscore, quote_hazard_rate}` — a consistent, regime/microstructure-stress
vocabulary — and never from the alpha's own signature sensor (`ofi_ewma`, `book_imbalance`,
`hawkes_intensity`, `trade_through_rate`, `kyle_lambda_60s_zscore`, `quote_replenish_asymmetry_zscore`
excepted — `sig_inventory_revert_v1` *does* reference its own driver in `off_condition`, the one
exception). The owning skill's stated exit-condition list
(`.cursor/skills/microstructure-alpha/SKILL.md`, "Exit Conditions") names four triggers: regime-gate
OFF, hazard-rate reversal, "structural invalidation (the causal premise breaks)," and "time decay
(alpha half-life exceeded)." From direct code trace, for a bare SIGNAL alpha with `hazard_exit` not
enabled (3 of 4 production alphas): there is no mechanism that flattens a position purely because the
alpha's own driver reversed sign, and no mechanism that flattens a position purely because
`expected_half_life_seconds` has elapsed — `hard_exit_age_seconds` only exists as a sub-field of the
opt-in `hazard_exit:` block (`alpha/loader.py:1145-1160`) and defaults to `2 × half_life` **only when
`hazard_exit.enabled: true`** (`.cursor/skills/microstructure-alpha/SKILL.md`, "HM-1"). So for
`sig_benign_midcap_v1` and `sig_kyle_drift_v1`, "structural invalidation" and "time decay" are named
in the skill doc as exit triggers but are not mechanically realized unless the *regime itself* also
deteriorates. **P1 (Inv-4 decay-is-the-default; `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110-119`,
economic soundness).** This is not a fail-open safety defect (positions are still
subject to every risk-engine drawdown/exposure check, and a fresh opposite-sign entry would still
reverse/flatten via the normal intent-translation path) — it is a gap between the documented mental
model of "four independent exit triggers" and what is mechanically wired for 3 of 4 alphas today.
**Recommendation:** either wire each alpha's primary driver reversal into its own `off_condition`
(symmetric with the entry check already present in `evaluate()`), or enable `hazard_exit` with a
`hard_exit_age_seconds` on every production alpha so "time decay" is structurally guaranteed rather
than incidental to regime drift. **Effort: S per alpha; M platform-wide.**

### 4.5 Hysteresis / latch mechanics

Unchanged and confirmed sound: cold start is OFF (`regime_gate.py:670`, `self._state.get(symbol,
False)`); while ON only `off_condition` is checked (classic latch — the ON/OFF band between the two
thresholds is the intended hysteresis, not a bug); while OFF only `on_condition` is checked. Declaring
a `hysteresis:` block with unreferenced constants is now a **hard load-time error** in strict mode
(the loader passes `strict=enforce_layer_gates`, default `True`) rather than a warning
(`regime_gate.py:773-777,814-846`, `loader.py`) — this fully resolves the 06-20 report's §5.3 finding;
`sig_kyle_drift_v1` and `sig_hawkes_burst_v1` had their dead blocks removed
(`sig_kyle_drift_v1.alpha.yaml:116-119`, `sig_hawkes_burst_v1.alpha.yaml:112-114`), each now
documenting that the *implicit* dual-threshold gap is the effective hysteresis. `sig_inventory_revert_v1`
is the one alpha that both declares **and references** hysteresis constants
(`posterior_margin`/`percentile_margin` appear in its `off_condition`, `sig_inventory_revert_v1.alpha.yaml:181-186`)
— confirmed a real, non-dead band. Declared alpha parameters are now also injectable as named gate
constants (`RegimeGate._params`, `regime_gate.py:611-617,722-736`), closing the 06-20 report's §5.5/§10.1
"gate parameter binding" backlog item — though `sig_inventory_revert_v1`'s own comment
(`sig_inventory_revert_v1.alpha.yaml:172-175`) notes it has *not* migrated its literals to param
references yet, to keep the locked replay baseline byte-identical. **P2, residual — the mechanism
exists, the one alpha that most needed it (documented literal/param duplication risk) hasn't adopted
it.** `binding_identifier_names()` correctly excludes injected params from the "must be warm" set
(`regime_gate.py:650-651`, tested by `test_param_names_excluded_from_binding_identifiers`).

### 4.6 Gate vs. risk semantics — unchanged since 06-20

`sig_kyle_drift_v1` can be gate-ON at `P(normal)=0.61` with no `P(vol_breakout)` cap in its
`on_condition`; the risk engine and sizer simultaneously compute an EV-over-posteriors scalar that is
already discounting that same diffuse posterior. This is not a bug (both are independently
fail-safe), but it is a real semantic gap between a **hard-threshold eligibility** decision (the gate)
and a **continuous-discount** decision (risk/sizer) over the same input — see §6 for the full trace.

## 5. Hazard Detector Audit

`regime_hazard_detector.py` has zero commits since 06-20 (`git log` on the file returns empty for the
window); the 06-20 audit's math description is re-verified accurate against current `HEAD`:

- **Detection criterion:** fires iff `p_now < p_prev` (`regime_hazard_detector.py:226-227`) AND
  (`dominant flipped` OR `p_now < 1 - hysteresis_threshold`) (`:229-231`) — the "sliding peak" case
  (dominant unchanged but decaying past the floor) is intentional, catching a regime that is
  statistically indistinguishable from a flip on the next tick even before the argmax moves.
- **`hazard_score = clip01((p_prev - p_now) / max(p_prev, 1e-12))`** (`:241-243`) is explicitly *not*
  a survival-analysis hazard rate λ(t) — no time normalization, no probability-of-flip semantics; a
  drop from 0.95→0.45 and a drop from 0.55→0.05 both score ≈0.9× despite very different starting
  points, and the score does not distinguish a 1 ms decay from a 30 s decay. This is a deliberate,
  correctly-self-documented design choice (module docstring, `regime_hazard_detector.py:36-64`), not
  a bug — but it means `hazard_score_threshold` calibration must be done per tick-rate cohort, not per
  wall-clock horizon; nothing in the codebase currently validates that a threshold was tuned against
  the deployment's actual quote rate (a documentation/operator-process gap, not a code gap).
- **Suppression / re-arm:** one spike per `(symbol, engine_name, departing_state)` departure episode
  (`:234-239`); re-arms on clean round-trip dominance **or** posterior recovery to the floor
  (`_rearm_suppression`, `:259-294`) — both conditions are correctly independent per-key checks, not
  conflated.
- **Contract validation:** `_validate_pair` (`:297-332`) checks symbol/engine/state_names/length
  agreement **and** `dominant_state`/`dominant_name` self-consistency on both `prev` and `curr`
  independently (`_validate_dominant_consistency`, `:335-350`) — raising
  `HazardDetectorContractError` rather than silently producing a wrong suppression key. This is
  exactly the right failure mode for a cross-tick contract violation.
- **Session boundary:** `Orchestrator._reset_regime_session_state` clears both
  `self._last_regime_state` (the detector's prev-pointer) and `self._regime_hazard_detector.reset()`
  (the suppression set) on every `run_*` entry point (`orchestrator.py:3537-3561`) — explicitly
  prevents a session-N-1 `RegimeState` from pairing with session-N's first state and firing a
  spurious cross-session spike. Confirmed correct.
- **`applies_to_regimes` (§20.5.3) — resolved since 06-20, contrary to that report's §6.3 finding.**
  `HazardPolicy.applies_to_regimes` (`hazard_exit.py:127`), `_spike_matches_regimes`
  (`hazard_exit.py:130-147`), loader parsing/validation (`alpha/loader.py:1162-1210`, including
  canonicalization to `"<from> -> <to>"` / bare-state strings and a load-time check that referenced
  state names exist on the target engine), and bootstrap wiring (`bootstrap.py:2170-2189`) are all
  present, with dedicated tests (`tests/services/test_hazard_exit_controller_wiring.py:209,234`).
  Traced via `git log -S"applies_to_regimes"` to commit `ff8530d` (2026-06-20T06:46:32Z) — landed the
  same UTC day as, and per its commit message in response to, "the external audit," but evidently the
  Claude-authored 06-20 report either predates that fix in its working snapshot or was not re-run
  against it before publishing. **This is exactly the kind of drift a fresh audit pass exists to
  catch** — confirmed resolved as of this report.
- **Controller-side exit-only enforcement:** `HazardExitController._maybe_emit_exit` always computes
  `side = SELL if position.quantity > 0 else BUY` and `quantity = abs(position.quantity)`
  (`hazard_exit.py:289-290`) — full-flatten, never partial, never same-direction. The orchestrator's
  bridge (`_on_bus_hazard_order`) adds a second, independent verification
  (`order_reduces = abs(current_qty + signed_qty) < abs(current_qty)`, `orchestrator.py:6302-6304`)
  and treats a REJECT on a **non-reducing** hazard-tagged order as authoritative (blocks submission,
  fires a CRITICAL alert) while treating a REJECT on a **reducing** order as informational only (the
  exit still submits, per the Inv-11 exit-always-permitted contract) — `orchestrator.py:6294-6357`.
  This is meaningfully more careful than "trust the reason tag," and is a good example of
  defense-in-depth done right (Inv-11).

## 6. Consumer Coherence Trace

| Stage | Component | Regime input | Aggregation | Fail-safe default |
|---|---|---|---|---|
| M2 | `RegimeEngine.posterior()` | `NBBOQuote` | one posterior vector / engine / symbol / sequence | Uncalibrated → `calibrated=False`; low-`d` → gate treats unavailable |
| Gate | `RegimeGate` | posteriors + snapshot/sensor bindings | boolean ON/OFF latch, hard thresholds | OFF (no entry); binding/arithmetic errors force OFF + unwind |
| Signal | `HorizonSignalEngine` | gate result + `evaluate()` | `Signal｜None` | Entry suppressed on warm/stale/entry-blocked; exit-only mechanisms backstopped at emission |
| Sizer | `BudgetBasedSizer` | `current_state()` EV | continuous scalar, `Σpᵢ·scaleᵢ`, clamped ≤1.0 | No engine → 1.0; engine w/o posterior → min(scales) |
| Risk (signal) | `BasicRiskEngine.check_signal` | `current_state()` EV | limit multiplier on position cap | Same shape as sizer, independently computed |
| Risk (order) | `BasicRiskEngine.check_order` | `current_state()` EV | limit multiplier, post-fill check | Same |
| Hazard | `HazardExitController` | `RegimeHazardSpike` | threshold + age + regime-filter → flatten order | No position / below threshold / below min-age / regime-mismatch → no action |

Findings, cross-checked against current code (files unchanged since 06-20 except as noted in §1/§4):

1. **Semantic inconsistency (unchanged).** The gate is a hard-threshold eligibility switch; risk/sizer
   are continuous EV discounts over the *same* posterior. A signal can be gate-ON while risk/sizer are
   already scaling it down substantially (§4.6) — not a bug, but a design choice worth naming
   explicitly for anyone tuning gate thresholds independent of risk scale maps.
2. **No double-scaling.** Sizer and risk operate **in series** (sizer proposes a regime-scaled
   quantity; risk then caps the *limit*, not the proposed quantity, by its own independently-computed
   regime scale) — confirmed by both docstrings (`basic_risk.py:801-808`) and by the fact each
   computes its own EV from `current_state()` rather than reading the other's output. Not compounding
   multiplicatively into the *same* quantity twice.
3. **Dominant vs. posterior vs. EV — where they disagree.** Gate can reference `dominant` (argmax,
   ties broken to lowest index — `orchestrator.py:3490-3491`) or `P(state)` (raw posterior mass);
   risk/sizer use EV over the full posterior; hazard uses `dominant_state` for the departing-state
   label but the raw `(p_prev, p_now)` pair for the score. All three are internally consistent with
   their own purpose (gate wants a crisp decision, risk/sizer want smooth limits, hazard wants a
   decay magnitude) — no incoherence found, but `sig_inventory_revert_v1` is the only alpha that
   combines `dominant` **and** `P()` in the same gate, which is the most conservative and least likely
   to disagree with the EV-based risk view.
4. **Timing.** `current_state()` reads the cached posterior from the most recent M2 tick, which can be
   more recent than the horizon-boundary snapshot the gate last evaluated against, since M2 runs on
   every quote while the gate only re-evaluates at horizon boundaries. This means risk/sizer can react
   to regime information the gate has not yet seen at horizon-boundary granularity — asymmetric but
   fail-safe in the conservative direction (risk tightens sooner than the gate would open/close).
5. **Unknown state names.** Risk defaults to `min(scales)` (`basic_risk.py:825`); sizer defaults to
   `min(all factors)` (`position_sizer.py:122`) — aligned. An optional boot-time hard-fail
   (`_validate_regime_engine_risk_scale_alignment`, `bootstrap.py:847-861`) exists for a custom engine
   publishing state names the risk map cannot resolve, but is opt-in
   (`enforce_regime_state_scale_alignment: False` default, `platform_config.py:407`) — belt-and-suspenders
   available, not defaulted on. **P2.**

## 7. Microstructure Grounding

### 7.1 What the default engine can and cannot support

Unchanged from 06-20's assessment, re-verified: `log(spread/mid)` is a reasonable proxy for immediate
quoted trading cost and, indirectly, adverse-selection/inventory stress (Glosten-Milgrom 1985,
Ho-Stoll 1981) — but the taxonomy cannot distinguish a stable-wide-spread-with-deep-queues regime
from a fragile-thin-top-of-book regime (no L2), cannot see signed flow/toxicity directly (Kyle 1985,
Easley/Lopez de Prado/O'Hara 2012 — VPIN-style toxicity requires trade-sign features the alphas
supply separately as sensors, not through the regime engine itself), and cannot see volatility that
arrives without spread widening (addressed only by the opt-in, unused `HMM3StateSpreadVol`, §3.7).
The practical framing that should govern gate design: **`P(state)` is a posterior over spread-regime
labels**, not a posterior over "the market's true condition."

### 7.2 Gate design patterns by mechanism family

| Family | Good pattern observed | Gap observed |
|---|---|---|
| `KYLE_INFO` (`sig_benign_midcap_v1`, `sig_kyle_drift_v1`) | `P(normal)` + tight-spread ON, `P(normal)` + wide-spread/vol-spike OFF — conservative cost filter consistent with "don't trade into adverse selection" | Neither alpha's `off_condition` unwinds on its own driver (OFI/book-imbalance, Kyle-λ) reversing (§4.4.2) |
| `HAWKES_SELF_EXCITE` (`sig_hawkes_burst_v1`) | Same regime pattern **plus** a low, fast `hazard_score_threshold=0.30` matched to its 30 s half-life — the one alpha that pairs regime-gate conservatism with a genuinely sensitive hazard exit | None found at the gate-design level |
| `INVENTORY` (`sig_inventory_revert_v1`, quarantined) | Most conservative gate in the repo: `dominant=="normal"` **and** dual posterior thresholds **and** a referenced hysteresis band **and** its own driver in `off_condition` | None at the gate-design level — its problem is the underlying edge, not the gate (§1.11) |
| `SCHEDULED_FLOW` (`sig_moc_imbalance_v1`) | Correctly schedule-gated, not regime-gated (self-documented); asymmetric entry/exit runway (>60 s to enter, <30 s to force-exit) is economically sensible, not arbitrary | Exact float equality on an indicator the alpha's own `evaluate()` already treats as unreliable-if-exact (§4.4 table) |
| `LIQUIDITY_STRESS` | No shipped alpha. G16 rule 7 statically rejects a literal non-FLAT return; the runtime backstop (`EXIT_ONLY_MECHANISMS`, `horizon_engine.py:573-590`) now also catches a dynamically-computed direction — should the family ever be authored, the gate question this audit was asked to answer ("gate on stress, or off stress?") is: **gate ON the stress condition for exit purposes only** — i.e. a `LIQUIDITY_STRESS` alpha's `on_condition` should itself be the trigger for de-leveraging (referenced from *other* alphas' `off_condition`/`hazard_exit.applies_to_regimes`), never an entry trigger — which is exactly what G16 rule 7 plus the runtime backstop now jointly enforce. |

### 7.3 Regime conditioning and alpha decay

For a 30 s-horizon alpha (`sig_hawkes_burst_v1`, `sig_inventory_revert_v1`), the horizon boundary and
the hazard `min_age_seconds` default (30 s, `hazard_exit.py:91`) are numerically close — a hazard
spike occurring early in a fresh position's life cannot trigger an exit until the position is already
roughly as old as one full horizon cycle, by which point the *regular* gate re-evaluation would likely
have already caught the same deterioration through the correlated spread/vol sensors. This means the
hazard path's marginal value for a 30 s-horizon alpha is concentrated in positions that have
*already* survived past one boundary — plausibly intentional (hazard as a backstop for a held-longer
position, not a replacement for boundary-driven exits), but not stated anywhere as a design rationale.
**P2 — worth an explicit comment in `sig_hawkes_burst_v1.alpha.yaml` or the hazard-exit docs**, not a
code change.

### 7.4 Calibration & offline validation — largely already built

`scripts/regime_diagnostics.py` (confirmed present, read in full header) already implements almost
exactly what this audit's brief asks be *proposed*: it (1) builds the same `RegimeEngine` a real run
would and calibrates on the same causal prefix as `_calibrate_regime_engine`; (2) reports
discriminative power — emission means/sigmas, min pairwise separation, argmax occupancy, posterior and
entropy distributions; (3) reports how a candidate gate clause would prune entries *before it ships*;
(4) buckets forward mid log-return (and its absolute value, a realized-vol/cost proxy) by
`P(vol_breakout)` decile and by entropy decile, with explicit "a tick is dropped if its forward window
extends past the last quote" no-lookahead handling. Its own docstring: "this is the merge gate the
second pass (R-2) requires: any change to a regime-gate condition, hazard threshold, or
regime-conditioned scaling must show its delta here on a cached symbol first." There is no artifact in
the repository (report, CI job, or archived output) showing it has actually been run against the four
currently-shipped gates — see Appendix (§10) for the concrete follow-up.

## 8. Test Gap Matrix

### 8.1 Commands run (this pass, `PYTHONHASHSEED=0` per `docs/three_layer_architecture.md` §12.5)

| Command | Result |
|---|---|
| `uv run pytest tests/services/test_regime_engine.py tests/services/test_regime_hazard_detector.py -q` | `71 passed in 0.21s` |
| `uv run pytest tests/signals/test_regime_gate_dsl.py tests/signals/test_regime_gate_dsl_props.py -q` | `97 passed in 0.87s` (up from `90` at 06-20 — `+7` new tests from `858c9f6`'s dead-hysteresis/param-injection coverage) |
| `uv run pytest tests/determinism/test_regime_hazard_replay.py tests/determinism/test_hazard_exit_replay.py -q` | `6 passed in 0.08s` |

Total: **174 / 174 passed**, no skips, no `PYTHONHASHSEED` warning once pinned.

### 8.2 Invariant → test coverage

| Invariant / behavior | Coverage | Evidence |
|---|---|---|
| Single-writer (`posterior()` called only at M2) | **Structural**, not just tested | `git grep '\.posterior('` → one production call site |
| Idempotency per `(symbol, sequence)` | Covered | `tests/services/test_regime_engine.py` (property-adjacent unit tests) |
| DSL whitelist / forbidden-node rejection | Covered | `test_compiled_tree_contains_only_whitelisted_nodes`, `test_forbidden_expressions_always_raise` (`test_regime_gate_dsl_props.py:115,197`) |
| Gate evaluation determinism | Covered | `test_evaluation_is_deterministic` (`test_regime_gate_dsl_props.py:156`) |
| Hysteresis hold-band prevents whipsaw (economic property) | **Partial** — 3 of 4 production alphas | `test_shipped_gate_has_non_empty_hold_band` (`test_regime_gate_dsl_props.py:269-292`); no probe for `sig_inventory_revert_v1`'s multi-clause band or `sig_moc_imbalance_v1` (N/A, schedule-gated) |
| Dead hysteresis constants rejected (strict) | Covered | `test_from_spec_strict_rejects_dead_hysteresis` (`test_regime_gate_dsl.py:635`) |
| Param injection precedence (sensor > param, hysteresis > param) | Covered | `test_real_sensor_overrides_param_constant`, `test_hysteresis_overrides_param_on_collision` (`:596,607`) — but see §4.3, the docstring itself is untested prose |
| `applies_to_regimes` threading (loader → policy → controller) | Covered | `test_applies_to_regimes_threaded_into_policy`, `test_applies_to_regimes_defaults_empty` (`tests/services/test_hazard_exit_controller_wiring.py:209,234`) |
| Hazard detector suppression / re-arm / contract validation | Covered | `tests/services/test_regime_hazard_detector.py` |
| Hazard exit e2e (threshold, min-age, universe, short-side, no-position) | Covered | `tests/integration/test_hazard_exit_e2e.py:170,220,256,294,321,357` |
| Regime/hazard-spike/hazard-exit replay determinism (L5/L6) | Covered | `tests/determinism/test_regime_hazard_replay.py`, `test_regime_state_replay.py`, `test_hazard_exit_replay.py`; `parity_manifest.py:129,133` |
| `LIQUIDITY_STRESS` static + dynamic entry prohibition | Covered | `test_stress_returning_dynamic_direction_abstains` (`tests/alpha/test_gate_g16.py`), plus a runtime-backstop test added by `bad7055` in `tests/signals/test_horizon_signal_engine.py` |
| **Missing:** as-of-boundary correctness of `_sensor_cache` / `SensorPassthroughFeature` bindings (§4.2) | **Missing** | No test asserts a gate/signal binding sourced from either path is insensitive to a `SensorReading` arriving between the nominal boundary and the triggering tick |
| **Missing:** `boundary_timestamp_ns == boundary_ts_ns` invariant (§1.4) | **Missing** | `tests/sensors/test_boundary_ts.py` tests `boundary_ts_ns` alone; no test pins the two fields together |
| **Missing:** `failure_signature` clauses cross-checked against `off_condition` (§4.4.1) | **Missing** | No loader test enforces or even warns on this |
| **Missing:** economically-meaningful posterior-bucket validation (occupancy, forward-return separation) | **Missing** in the test suite (exists as a *script*, §7.4) | `scripts/regime_diagnostics.py` is not wired into CI/pytest — by design, it is an offline research tool, not a merge gate today despite its docstring calling itself one |

### 8.3 Property-test character (dimension F.2)

`tests/signals/test_regime_gate_dsl_props.py` is predominantly **syntactic/structural**: AST
whitelist enforcement, evaluation determinism, output-type (`bool`, two-value set). Exactly one test,
`test_shipped_gate_has_non_empty_hold_band`, encodes a genuine **economic** invariant (a gate without
hysteresis chatters on posterior noise, which is a real whipsaw/transaction-cost defect, not just a
style issue) — and it is scoped to 3 of 4 production alphas (`sig_inventory_revert_v1`'s multi-clause
band and the schedule-gated `sig_moc_imbalance_v1` are both excluded, per §8.2). No property test
asserts anything about
forward-return separation, cost survivability under the gate, or cross-checks the gate against its
declared `trend_mechanism`.

## 9. Prioritized Backlog

| Priority | Item | File(s) | Recommendation | Effort |
|---|---|---|---|---|
| P1 (Inv-6) | Extend as-of-boundary causality fix to `_sensor_cache` and passthrough features (§4.2) | `src/feelies/signals/horizon_engine.py:291-336`, `src/feelies/features/impl/sensor_passthrough.py:81-89` (cross-audit: feature-engine) | Filter `_sensor_cache` reads/writes and passthrough `finalize()` by `asof_timestamp_ns`, matching `HorizonWindowedFeature` | M |
| P1 (Inv-4) | No gate references its own alpha's primary driver reversing; "structural invalidation"/"time decay" not mechanically enforced for 3/4 alphas (§4.4.2) | `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:133-138`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110-119`; optionally `sig_inventory_revert_v1` (already partial) | Wire each driver's reversal into `off_condition`, or default-enable `hazard_exit` with `hard_exit_age_seconds` platform-wide | S per alpha / M platform-wide |
| P2 | Duplicate `boundary_timestamp_ns` / `boundary_ts_ns` fields, currently synced by convention only (§1.4) | `core/events.py`, `sensors/horizon_scheduler.py`, `features/aggregator.py` | Collapse to one field, or add a construction-time assertion that they agree | S |
| P2 | `evaluate()` docstring states params beat sensors; code and tests say the opposite (§4.3) | `signals/regime_gate.py:724-729` | Rewrite the docstring to describe actual merge order | S |
| P2 | `failure_signature` free text not cross-checked against `off_condition` (§4.4.1) | `alpha/loader.py`, `.cursor/skills/microstructure-alpha/SKILL.md` | Add a loader warn-if-parseable-and-unreferenced check, or explicitly re-scope the field as narrative-only | S–M |
| P2 | `sig_moc_imbalance_v1` gates on exact float equality; own `evaluate()` already hedges the same value (§4.4 table) | `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:131,133` | Use `>= 0.5` / `< 0.5`-style tolerance in the gate, matching `evaluate()` | S |
| P2 | `sig_inventory_revert_v1` hasn't migrated to param-referenced gate literals despite the mechanism now existing (§4.5) | `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:172-175` | Migrate once a baseline rebake is acceptable | S |
| P2 | `enforce_regime_state_scale_alignment` defense-in-depth is opt-in (§6, item 5) | `core/platform_config.py:407` | Consider defaulting `True` in production profiles once operators confirm no custom engines rely on unmapped state names | S |
| P2 | `_MIN_CALIBRATION_SAMPLES = 30` remains a thin floor (§3.2, carried over) | `services/regime_engine.py:188` | Raise the floor or document the effective floor imposed by `regime_calibration_max_quotes` in production profiles | S |
| P1 (Inv-11, open, deliberately deferred) | `regime_min_discriminability: 0.0` no-op default (carried over, unchanged) | `platform.yaml:172` | Set a validated floor per cohort after running `scripts/regime_diagnostics.py` | S once validated |
| P1 (Inv-5, open, deliberately deferred) | `transition_time_scaling_enabled` off by default; tick-time, not wall-clock, dwell (carried over, unchanged, now with documented rationale) | `platform.yaml:47-62` | Enable per-deployment once `transition_dt_reference_seconds` is cohort-validated | M |
| P2 | Hazard `min_age_seconds` default is numerically close to `sig_hawkes_burst_v1`'s own horizon (§7.3) | `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml` | Document the intended interaction, or lower `min_age_seconds` for sub-horizon hazard responsiveness | S |
| P2 | `scripts/regime_diagnostics.py` not run/archived against shipped gates (§7.4) | n/a (process) | Run it against APP 2026-03-26 / 2026-06-01 cached NBBO and archive the report before the next `regime_engine_options` change | S (run) |

**Resolved since 2026-06-20 (confirmed, not carried forward):** `hazard_exit.applies_to_regimes`
(§5); dead hysteresis constants (§4.5); gate/param literal duplication mechanism (§4.5, adoption
still partial — see P2 above); `LIQUIDITY_STRESS` dynamic-direction entry gap (§4.4 table, §7.2);
checkpoint/restore flag-fingerprint verification (§3.6, predates 06-20 but untested by that report's
negative-path check).

## 10. Appendix — Open Questions Needing Data Runs

1. Run `scripts/regime_diagnostics.py` against cached APP (`2026-03-26`, `2026-06-01`) and at least
   one AAPL session to establish current discriminability (`d`), posterior-entropy distribution, and
   `P(vol_breakout)`-decile forward-return separation for the default engine **before** any change to
   `regime_engine_options` or `regime_min_discriminability` — this is the tool's own stated
   prerequisite (§7.4) and appears never to have been archived.
2. For `sig_benign_midcap_v1` and `sig_kyle_drift_v1`: what fraction of realized entries would have
   been followed, within the position's holding period, by a driver reversal (OFI/book-imbalance
   sign flip; Kyle-λ z-score dropping below `-1.5`) that the current gate does **not** act on? This
   would size the practical impact of §4.4.2 before committing to the M-effort platform-wide fix.
3. Does `_sensor_cache` (§4.2) actually diverge from the boundary-correct value often enough to
   matter economically, or is quote arrival dense enough relative to horizon width that the gap is
   negligible in practice? A replay diff (as-of-boundary vs. current cache behavior) on a liquid vs.
   thin symbol would settle this and should gate the M-effort fix's priority.
4. What is the realized dwell-time distribution (in wall-clock seconds) of the default engine's
   states across the traded symbol cohort at current quote rates, and how much would
   `transition_time_scaling_enabled=true` change it? Needed before the deliberately-deferred P1 (Inv-5; `platform.yaml:47-62`) in §9 can be un-deferred with a validated
   `transition_dt_reference_seconds`.
5. For `sig_hawkes_burst_v1`: does the hazard path (`min_age_seconds=30`, `hazard_score_threshold=0.30`)
   ever fire strictly before the next regular 30 s horizon boundary in realistic replay, or is it — as
   §7.3 speculates — effectively only a backstop for positions already held past one boundary? A
   simple counter over a backtest window would answer this directly.
