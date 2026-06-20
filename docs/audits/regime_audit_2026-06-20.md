# Regime Stack Audit

**Date:** 2026-06-20  
**Mode:** Read-only evidence audit. No production code changed.  
**Scope:** `NBBOQuote -> RegimeState -> RegimeGate -> Signal -> risk/sizer -> OrderRequest`, including hazard exits, shipped alpha gates, platform defaults, and determinism tests.

## 1. Executive Summary

1. **No active production P0 was found in the current regime engine/gate/hazard path.** The single-writer path is concentrated in orchestrator M2, `posterior()` is idempotent per `(symbol, sequence)`, and the requested regime and hazard tests passed (`71 + 90 + 6` tests). See `src/feelies/kernel/orchestrator.py:3432`, `src/feelies/services/regime_engine.py:500`, and test evidence in §9.
2. **The default engine is a fixed-parameter HMM-style forward filter, not a fully Bayesian regime model.** It uses spread-derived emissions, fixed transition probabilities, and empirical calibration from quote samples (`src/feelies/services/regime_engine.py:127`, `src/feelies/services/regime_engine.py:321`, `src/feelies/services/regime_engine.py:827`).
3. **The state called `vol_breakout` is primarily "wide-spread state" under the default engine.** The default observation is `log(spread / mid)`, with states ordered by increasing fitted spread mean (`src/feelies/services/regime_engine.py:127`, `src/feelies/services/regime_engine.py:407`). The optional 2-D spread+realized-vol engine exists but is opt-in (`src/feelies/services/regime_engine.py:858`, `src/feelies/services/regime_engine.py:1268`).
4. **Gate fail-safe behavior is mostly strong.** Uncalibrated or low-discriminability regimes make `P()`, `dominant`, and `entropy` unavailable and force gate-safe OFF/unwind behavior through `HorizonSignalEngine` (`src/feelies/signals/regime_gate.py:410`, `src/feelies/signals/horizon_engine.py:389`).
5. **P1: the documented `hazard_exit.applies_to_regimes` contract is not implemented.** Architecture docs show a departing-state filter, but the loader rejects unknown hazard keys and the controller filters only by enabled policy, symbol universe, threshold, and age (`docs/three_layer_architecture.md:2277`, `docs/three_layer_architecture.md:2403`, `src/feelies/alpha/loader.py:1022`, `src/feelies/risk/hazard_exit.py:165`). This is exit-only, so it reduces rather than increases exposure, but it can flatten for the wrong regime transition.
6. **P1: the default transition dynamics are quote-count based unless time scaling is enabled.** Default dwell time is therefore market-activity dependent: about 100 quote ticks with the shipped transition matrix, not a stable wall-clock duration (`src/feelies/services/regime_engine.py:165`, `src/feelies/services/regime_engine.py:762`, `platform.yaml:41`).
7. **P1: production defaults prioritize availability over regime discriminability.** `regime_min_discriminability` defaults to `0.0`, pairwise separation enforcement is off unless configured, and per-symbol calibration is commented out in the root platform file (`platform.yaml:41`, `platform.yaml:159`, `src/feelies/core/platform_config.py:393`).
8. **P1: gate hysteresis margin blocks can be dead config.** The DSL accepts named constants, but `sig_kyle_drift_v1` and `sig_hawkes_burst_v1` declare hysteresis constants that their expressions do not reference; the loader warns but accepts (`src/feelies/signals/regime_gate.py:685`, `src/feelies/signals/regime_gate.py:780`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:106`).
9. **P1: gate expressions duplicate alpha parameters because the DSL cannot resolve YAML params.** `sig_inventory_revert_v1` documents this explicitly, which means parameter sweeps can silently diverge from gate thresholds (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:171`).
10. **P1: risk/sizer behavior is safer than some docs say.** Code and tests use minimum regime scaling when a configured engine has no posterior, while older docs describe neutral `1.0x` for missing state (`src/feelies/risk/position_sizer.py:111`, `src/feelies/risk/basic_risk.py:790`, `.cursor/skills/regime-detection/SKILL.md:318`). Update the docs, not the fail-safe.
11. **P1: `LIQUIDITY_STRESS` exit-only enforcement has an authoring gap for dynamic signal directions.** Static non-FLAT returns are rejected, but dynamic directions can make validation abstain (`src/feelies/alpha/layer_validator.py:1003`, `src/feelies/alpha/layer_validator.py:1154`, `tests/alpha/test_gate_g16.py:533`). There is no current production `LIQUIDITY_STRESS` alpha, so this is a future guardrail issue.
12. **P2: calibration is deterministic but has a soft causality wrinkle for research replay.** Orchestrator fits on a prefix, then replays that same prefix with parameters estimated from the prefix (`src/feelies/kernel/orchestrator.py:3289`). This is acceptable for deterministic warmup but should not be treated as a live-causal PnL sample.
13. **The largest residual risk is economic validity, not software determinism.** Existing tests prove mechanics; they do not prove that posterior buckets improve forward returns, cost, fill quality, or alpha hit-rate.

## 2. Evidence And Method

I read the regime, microstructure, and risk skills; architecture sections on regime gates, hazard exits, determinism, and G16; platform defaults; shipped alpha gate blocks; and the implementation path from regime publication to sizing and risk.

Relevant contract evidence:

| Contract | Evidence |
|---|---|
| Regime engine owns posterior production; downstream consumers are read-only | `.cursor/skills/regime-detection/SKILL.md:17`, `.cursor/skills/regime-detection/SKILL.md:39`, `.cursor/skills/regime-detection/SKILL.md:142` |
| Downstream current state comes from M2 posteriors | `.cursor/skills/regime-detection/SKILL.md:142`, `src/feelies/kernel/orchestrator.py:3432` |
| Gate DSL and purity boundary | `.cursor/skills/microstructure-alpha/SKILL.md:205`, `docs/three_layer_architecture.md:1075`, `src/feelies/signals/regime_gate.py:216` |
| Warm/stale data suppresses entries while exits remain possible | `.cursor/skills/microstructure-alpha/SKILL.md:225`, `src/feelies/signals/horizon_engine.py:333`, `src/feelies/signals/horizon_engine.py:470` |
| Risk and sizer consume `current_state()` and scale by posterior EV | `.cursor/skills/risk-engine/SKILL.md:181`, `.cursor/skills/risk-engine/SKILL.md:229`, `src/feelies/risk/position_sizer.py:111`, `src/feelies/risk/basic_risk.py:790` |
| Hazard exit is opt-in and exit-only | `.cursor/skills/risk-engine/SKILL.md:187`, `src/feelies/risk/hazard_exit.py:49`, `src/feelies/bootstrap.py:1670` |
| Deterministic replay, causality, typed events, fail-safe invariants | `docs/three_layer_architecture.md:1394`, `docs/three_layer_architecture.md:2025`, `src/feelies/core/events.py:142`, `src/feelies/core/events.py:506` |

Severity rubric:

| Severity | Meaning |
|---|---|
| P0 | Active exposure amplification, causality break in live path, nondeterministic replay, or fail-open safety defect. |
| P1 | Contract mismatch, economic misclassification, future authoring gap, or behavior likely to cause unnecessary exits/suppression. |
| P2 | Research/process/test gap with limited immediate blast radius. |

## 3. Regime Stack Inventory

### 3.1 Runtime flow

| Stage | Component | Regime input | Output | Relevant fail-safe |
|---|---|---|---|---|
| M2 | `RegimeEngine.posterior()` via orchestrator | `NBBOQuote` | `RegimeState` | Uncalibrated publishes `calibrated=False`; gates referencing posterior fail OFF (`src/feelies/kernel/orchestrator.py:3317`, `src/feelies/kernel/orchestrator.py:3432`, `src/feelies/signals/regime_gate.py:410`). |
| M2 | `RegimeHazardDetector.detect()` | Previous/current `RegimeState` | `RegimeHazardSpike` | No spike for invalid pairs, first state, non-drop, or suppressed duplicate (`src/feelies/services/regime_hazard_detector.py:188`, `src/feelies/services/regime_hazard_detector.py:259`). |
| Signal | `RegimeGate` | `RegimeState` + snapshot/sensor bindings | ON/OFF latch | Cold start OFF; runtime expression errors reset OFF and publish gate-close FLAT if needed (`src/feelies/signals/regime_gate.py:568`, `src/feelies/signals/horizon_engine.py:389`). |
| Signal | `HorizonSignalEngine` | Gate result + alpha snapshot | `Signal` or suppression | Warm/stale readings suppress entries; gate close emits FLAT when unwinding (`src/feelies/signals/horizon_engine.py:333`, `src/feelies/signals/horizon_engine.py:517`). |
| Risk/sizer | `BudgetBasedSizer` | `current_state(engine)` | Size multiplier | No engine => `1.0`; configured engine missing posterior => min factor (`src/feelies/risk/position_sizer.py:111`, `tests/risk/test_position_sizer.py:185`). |
| Risk | `BasicRiskManager` | `current_state(engine)` | Limit multiplier/veto | EV-over-posteriors, clamped at `1.0`; no configured engine => neutral, missing posterior => min scale (`src/feelies/risk/basic_risk.py:167`, `src/feelies/risk/basic_risk.py:790`). |
| Hazard risk | `HazardExitController` | `RegimeHazardSpike` + position store | Flattening order | No position, under threshold, or min-age block => no action (`src/feelies/risk/hazard_exit.py:165`, `src/feelies/risk/hazard_exit.py:210`). |

### 3.2 Engines and platform defaults

| Engine | Status | Observation | Notes |
|---|---|---|---|
| `hmm_3state_fractional` | Default | `log(spread / mid)` | Fixed-structure forward filter with default states `compression`, `normal`, `vol_breakout` (`src/feelies/services/regime_engine.py:127`, `src/feelies/services/regime_engine.py:165`, `platform.yaml:41`). |
| `hmm_3state_spread_filter` | Alias | Same | Registered alias for the default engine (`src/feelies/services/regime_engine.py:1268`). |
| `hmm_3state_spread_vol` | Opt-in | Spread + realized mid volatility | Adds a second diagonal-Gaussian dimension but is not the production default (`src/feelies/services/regime_engine.py:858`, `src/feelies/services/regime_engine.py:1268`). |

Important default knobs:

| Config | Current default/profile | Effect |
|---|---|---|
| `regime_engine` | `hmm_3state_fractional` in `platform.yaml` | Spread-only taxonomy (`platform.yaml:41`, `src/feelies/core/platform_config.py:76`). |
| `regime_calibration_max_quotes` | `100000` in root `platform.yaml`; code default `None` | Root profile calibrates; raw code default would mark uncalibrated and alert (`platform.yaml:159`, `src/feelies/core/platform_config.py:393`, `src/feelies/kernel/orchestrator.py:3317`). |
| `regime_min_discriminability` | `0.0` | No-op floor unless deployment raises it (`platform.yaml:169`, `src/feelies/core/platform_config.py:393`). |
| `use_time_scaled_transitions` | Commented example, off by default | Transition dwell is quote-count based unless enabled (`platform.yaml:41`, `src/feelies/services/regime_engine.py:762`). |
| `per_symbol_calibration` | Commented example, off by default | Global emissions unless enabled and sample counts suffice (`platform.yaml:41`, `src/feelies/services/regime_engine.py:188`, `src/feelies/services/regime_engine.py:321`). |

### 3.3 Shipped alpha gate inventory

| Alpha | Family | Horizon | Gate regime dependency | Hysteresis notes | Hazard exit |
|---|---:|---:|---|---|---|
| `sig_benign_midcap_v1` | `KYLE_INFO` | 120 s | ON requires `P(normal)>0.5`; OFF includes `P(normal)<0.35` plus spread/vol sensors (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:123`, `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:133`, `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:161`). | Explicit on/off band. | No. |
| `sig_inventory_revert_v1` | `INVENTORY` | 30 s | ON requires `dominant == 'normal'`, `P(normal)>0.65`, `P(vol_breakout)<0.20`, and sensors; comments warn gate literals duplicate params (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:162`, `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:171`, `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:182`). | Explicit on/off band. | No. |
| `sig_moc_imbalance_v1` | `SCHEDULED_FLOW` | 120 s | Schedule-gated, not posterior-gated (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:110`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:120`, `alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:147`). | Time window latch. | No. |
| `sig_kyle_drift_v1` | `KYLE_INFO` | 300 s | ON requires `P(normal)>0.6`; OFF includes `P(normal)<0.4` and sensors (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:100`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110`, `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:133`). | Hysteresis constants declared but not referenced. | No. |
| `sig_hawkes_burst_v1` | `HAWKES_SELF_EXCITE` | 30 s | ON requires `P(normal)>0.6`; OFF includes `P(normal)<0.4` and sensors (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:96`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:106`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:129`). | Hysteresis constants declared but not referenced. | Enabled, threshold `0.30` (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:140`). |
| `_paper_smoke_v1` | Smoke | n/a | Always-true/never-off smoke gate, no posterior dependency (`alphas/_paper_smoke_v1/paper_smoke_v1.alpha.yaml:50`). | Smoke only. | No. |

Portfolio composition currently consumes mechanism tags and caps, not regime posteriors directly (`alphas/research/pro_kyle_benign_v1/pro_kyle_benign_v1.alpha.yaml:48`, `alphas/research/pro_burst_revert_v1/pro_burst_revert_v1.alpha.yaml:42`, `src/feelies/composition/engine.py:320`).

## 4. Regime Engine Audit

### 4.1 Model class and mathematical status

`HMM3StateFractional` is a deterministic forward filter over a fixed state space. It is HMM-like in the Rabiner/Hamilton/Kim sense of hidden Markov state filtering, but it is not a full Bayesian model over transition/emission parameters. The transition matrix, state names, and default Gaussian emission parameters are fixed or empirically calibrated; no posterior over parameters is maintained (`src/feelies/services/regime_engine.py:127`, `src/feelies/services/regime_engine.py:165`, `src/feelies/services/regime_engine.py:321`, `src/feelies/services/regime_engine.py:827`).

Calibration sorts observed log-spreads, partitions them into quantile buckets, fits means and standard deviations, optionally enforces separation, and clears posterior state after success (`src/feelies/services/regime_engine.py:321`, `src/feelies/services/regime_engine.py:407`, `src/feelies/services/regime_engine.py:434`). That is a pragmatic deterministic estimator, not Baum-Welch/EM and not a hierarchical Bayesian fit.

Microstructure interpretation:

| State | Direct observable under default engine | Plausible latent proxy | Caveat |
|---|---|---|---|
| `compression` | Low relative spread | Tight/liquid quote regime | Could also reflect stale or locked liquidity unless validated by depth/fills. |
| `normal` | Middle relative spread tercile | Baseline trading cost | Name/session-relative, not universal. |
| `vol_breakout` | High relative spread | Volatility, adverse selection, inventory stress, or liquidity withdrawal | Under default engine it is spread widening, not realized volatility by itself (`src/feelies/services/regime_engine.py:127`, `src/feelies/services/regime_engine.py:407`). |

This is directionally consistent with classic market-making and adverse-selection literature: Kyle (1985) links informed flow to price impact, Glosten-Milgrom (1985) links spreads to adverse selection, Ho-Stoll (1981) links dealer inventory and spread setting, and Easley-Lopez de Prado-O'Hara (2012) links order-flow toxicity to liquidity conditions. The implementation only observes L1 spread/mid, so those latent labels are hypotheses to validate, not measured causes.

### 4.2 Posterior update, idempotency, and fail-safe math

The update path is deterministic:

1. First observation starts from a uniform prior (`src/feelies/services/regime_engine.py:500`).
2. Repeated calls with the same or older sequence return the stored posterior, making `posterior()` idempotent per symbol/sequence (`src/feelies/services/regime_engine.py:500`).
3. Transition prediction applies the transition matrix, optionally scaled by elapsed time (`src/feelies/services/regime_engine.py:762`, `src/feelies/services/regime_engine.py:827`).
4. Bayes update multiplies by emission likelihood and renormalizes; invalid likelihoods reset to uniform instead of propagating NaN/Inf (`src/feelies/services/regime_engine.py:827`).
5. Posterior and sequence commit together (`src/feelies/services/regime_engine.py:500`).

This supports Inv-5 deterministic replay and Inv-11 fail-safe behavior. The remaining soft issue is economic, not arithmetic: if emissions are weakly separated, the posterior can be mechanically stable and deterministic while still carrying little predictive information. The code surfaces weak separation warnings (`src/feelies/services/regime_engine.py:477`), and `RegimeState` carries `discriminability` (`src/feelies/core/events.py:142`), but the root platform floor is currently `0.0` (`platform.yaml:169`).

### 4.3 Calibration and causality

The orchestrator calibrates from a prefix of observed quotes and then replays the same prefix through the calibrated engine (`src/feelies/kernel/orchestrator.py:3289`). This is deterministic and avoids uncalibrated default emissions in normal runs. It is also a soft research-causality wrinkle: the early prefix posteriors use parameters estimated using later ticks in that prefix. For live-like research acceptance, calibration should come from a prior session or a strictly earlier warmup window that is excluded from PnL attribution.

If `regime_calibration_max_quotes` is absent, the orchestrator emits a critical alert and marks the engine uncalibrated (`src/feelies/kernel/orchestrator.py:3317`). That is fail-safe for posterior-gated alphas because `P()`, `dominant`, and `entropy` become unavailable (`src/feelies/signals/regime_gate.py:410`).

### 4.4 Transition time scaling

The default transition matrix has diagonal persistence around `0.99`, so the natural dwell is roughly 100 transition steps (`src/feelies/services/regime_engine.py:165`). Without time scaling, one transition step is one quote. At 10, 50, and 100 quotes per second, the same matrix implies rough wall-clock dwell of 10 s, 2 s, and 1 s.

The implementation has a clean time-scaling transform: compute `scale = dt / ref_dt`, clamp it, raise stay probabilities to that scale, and renormalize off-diagonals (`src/feelies/services/regime_engine.py:762`). The issue is default posture: `platform.yaml` leaves time-scaling options commented out (`platform.yaml:41`). For a microstructure system where quote intensity is itself regime-dependent, quote-time persistence can make high-activity periods transition faster by construction.

Recommendation: use time scaling in production profiles after validating `transition_time_ref_ns` by symbol/cohort, or explicitly document that the current regime is a quote-time regime.

### 4.5 Checkpoint determinism

Checkpoint fingerprints include state names, transition parameters, time-scaling flags, and calibration options (`src/feelies/services/regime_engine.py:568`). Restore rejects mismatched fingerprints (`src/feelies/services/regime_engine.py:620`). This is the right shape for deterministic replay: a saved posterior is not silently reused under different model semantics.

## 5. Regime Gate Audit

This is the highest-leverage part of the stack because it translates probabilistic state estimates into discrete alpha eligibility.

### 5.1 DSL surface and purity

The DSL is intentionally small. It validates AST nodes, allows boolean/comparison/arithmetic constructs, exposes whitelisted functions, and blocks attribute/subscript/lambda-style access (`src/feelies/signals/regime_gate.py:118`, `src/feelies/signals/regime_gate.py:216`, `src/feelies/signals/regime_gate.py:256`). `P(state)` requires a bare state identifier and is load-time checked against the configured engine where available (`src/feelies/signals/regime_gate.py:256`, `src/feelies/alpha/loader.py:389`, `src/feelies/alpha/loader.py:1318`).

The evaluator uses Python-like short-circuiting for `and`/`or`, whitelisted `abs/min/max`, and normal arithmetic exceptions for invalid expressions (`src/feelies/signals/regime_gate.py:311`). `HorizonSignalEngine` catches gate errors, resets the latch OFF, and publishes a gate-close FLAT if the gate was previously ON (`src/feelies/signals/horizon_engine.py:389`). This is a strong fail-safe.

Residual edge: division/modulo by zero is still possible in a gate expression and will become a runtime gate error (`src/feelies/signals/regime_gate.py:311`, `src/feelies/signals/horizon_engine.py:389`). That is acceptable as a fail-safe, but it should be linted in alpha review if expressions become more complex.

### 5.2 Binding semantics and data freshness

Gate bindings are composed from:

1. Regime state: `P(state)`, `dominant`, entropy, `pNN` aliases (`src/feelies/signals/regime_gate.py:456`).
2. Snapshot values from the current horizon dispatch (`src/feelies/signals/horizon_engine.py:611`).
3. Sensor cache fallback for values not present in the snapshot (`src/feelies/signals/horizon_engine.py:271`, `src/feelies/signals/horizon_engine.py:611`).

Snapshot values take priority and sensor-cache values fill gaps via `setdefault` (`src/feelies/signals/horizon_engine.py:611`). Warm/stale readings block entries but still allow exits and gate-close FLAT behavior (`src/feelies/signals/horizon_engine.py:333`, `src/feelies/signals/horizon_engine.py:470`). This matches the microstructure skill contract for safe degradation (`.cursor/skills/microstructure-alpha/SKILL.md:225`).

### 5.3 Hysteresis and latch behavior

`RegimeGate` is per-alpha and keeps a per-symbol latch (`src/feelies/signals/regime_gate.py:568`). Cold start is OFF (`src/feelies/signals/regime_gate.py:670`). ON/OFF expressions are evaluated with optional named hysteresis constants injected into the environment (`src/feelies/signals/regime_gate.py:685`).

Important distinction: declaring a `hysteresis:` YAML block does not automatically widen thresholds. The expression must reference those constants. The loader currently warns when constants are declared but unused (`src/feelies/signals/regime_gate.py:780`). Two shipped alphas have this pattern:

| Alpha | Declared constants | Used in expression? | Impact |
|---|---|---|---|
| `sig_kyle_drift_v1` | Posterior/percentile margins | No | The explicit `P(normal)>0.6` / `<0.4` band still provides hysteresis, but the named margin block is dead config (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110`). |
| `sig_hawkes_burst_v1` | Posterior/percentile margins | No | Same: thresholds have a band, but named constants do not affect behavior (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:106`). |

Recommendation: in strict alpha validation, promote "declared hysteresis constants unused" from warning to load error, or remove the blocks from shipped alphas.

### 5.4 Per-alpha semantics

| Alpha | Gate intent | Coherence assessment |
|---|---|---|
| `sig_benign_midcap_v1` | Trade Kyle-style benign drift only when posterior mass favors normal conditions and spread/vol sensors are not stressed (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:133`). | Coherent as a conservative cost filter. Risk: `normal` is spread-middle, not necessarily "benign information". Needs conditional-forward-return validation. |
| `sig_inventory_revert_v1` | Require normal dominant state, high `P(normal)`, low `P(vol_breakout)`, and inventory/asymmetry sensors (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:182`). | Most regime-dependent shipped gate. The YAML comments admit threshold duplication because DSL cannot resolve params (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:171`). |
| `sig_moc_imbalance_v1` | Schedule window, not regime posterior (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:120`). | Appropriate: MOC imbalance is a scheduled-flow mechanism, not necessarily explained by spread-tercile state. |
| `sig_kyle_drift_v1` | Trade only in normal posterior mass and acceptable spread/vol sensors (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110`). | Coherent but margin config is no-op. |
| `sig_hawkes_burst_v1` | Trade only in normal posterior mass and acceptable spread/vol sensors; hazard exit enabled (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:106`, `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:140`). | Coherent as a safety filter, but hazard exit lacks departing-regime filtering (§6). |

### 5.5 Gate versus risk semantics

Gate decisions are hard thresholds. Risk and sizer decisions are posterior-EV scalars. Example: `sig_kyle_drift_v1` can be ON at `P(normal)=0.61` with meaningful mass elsewhere because it has no `P(vol_breakout)` cap (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:110`). The sizer/risk layer then computes an EV multiplier over configured state factors and clamps at `1.0` (`src/feelies/risk/position_sizer.py:111`, `src/feelies/risk/basic_risk.py:790`).

This is not a bug, but it is a semantic mismatch: the gate says "eligible" while risk says "smaller". For some strategies that is exactly right. For others it may create entry churn in borderline mixed posteriors. If a strategy's economic premise is "only trade when expected regime scale is above X", the DSL should expose a `regime_scale` binding or the gate should encode both posterior and risk semantics explicitly.

### 5.6 Exit-only authoring guardrail

The architecture and skill docs treat `LIQUIDITY_STRESS` as exit-only (`.cursor/skills/microstructure-alpha/SKILL.md:89`, `docs/three_layer_architecture.md:2294`). Composition code also zeroes exit-only mechanism scores (`src/feelies/composition/cross_sectional.py:65`, `src/feelies/composition/cross_sectional.py:223`, `src/feelies/composition/cross_sectional.py:290`).

Static validator G16 rejects statically resolvable non-FLAT signals for stress mechanisms (`src/feelies/alpha/layer_validator.py:890`, `src/feelies/alpha/layer_validator.py:1003`). However, when direction extraction is dynamic or unknown, validation abstains (`src/feelies/alpha/layer_validator.py:1154`), and tests explicitly accept that abstention (`tests/alpha/test_gate_g16.py:533`). There is no shipped production `LIQUIDITY_STRESS` alpha today, so this is not an active P0, but it should be closed before allowing user-authored stress alphas.

## 6. Hazard Audit

### 6.1 Detector semantics

`RegimeHazardDetector` is deterministic and intentionally simple:

| Behavior | Evidence |
|---|---|
| First state cannot spike | `src/feelies/services/regime_hazard_detector.py:188` |
| Spike requires posterior decay from previous to current state | `src/feelies/services/regime_hazard_detector.py:188` |
| Flip or drop below hysteresis floor can trigger | `src/feelies/services/regime_hazard_detector.py:188`, `src/feelies/services/regime_hazard_detector.py:91` |
| Duplicate spikes are suppressed until re-armed | `src/feelies/services/regime_hazard_detector.py:259` |
| Dominant-state inconsistencies and tied incoming states are guarded | `src/feelies/services/regime_hazard_detector.py:297`, `src/feelies/services/regime_hazard_detector.py:353` |

The skill is explicit that `hazard_score` is a normalized one-tick relative decay, not a survival-analysis hazard rate (`.cursor/skills/regime-detection/SKILL.md:260`). That distinction matters: `0.30` means "30% relative posterior decay over one transition step", not "30% probability of failure per unit time".

### 6.2 Controller semantics

`HazardExitController` is exit-only and symbol-net based, not per-strategy position based (`src/feelies/risk/hazard_exit.py:49`). On a qualifying spike it checks policy ordering, symbol universe, threshold, min age, and whether there is a position to flatten (`src/feelies/risk/hazard_exit.py:165`, `src/feelies/risk/hazard_exit.py:210`). It suppresses duplicate orders by `(strategy_id, symbol, reason)` until flat (`src/feelies/risk/hazard_exit.py:210`, `src/feelies/risk/hazard_exit.py:268`).

This is safe in exposure terms but imprecise in attribution: one strategy's hazard policy can flatten the symbol-net position containing other strategies' exposure. The docs already call this a future per-strategy concern in spirit; the code makes the current behavior explicit (`src/feelies/risk/hazard_exit.py:49`).

### 6.3 Contract gap: `applies_to_regimes`

Architecture examples include `hazard_exit.applies_to_regimes` and event-flow logic that checks `spike.departing_state in alpha.hazard_exit.applies_to_regimes` (`docs/three_layer_architecture.md:2277`, `docs/three_layer_architecture.md:2403`). Current loader policy does not include that key; it accepts `enabled`, `hazard_score_threshold`, `min_age_seconds`, and `hard_exit_age_seconds`, with legacy normalization for `posterior_drop_threshold` (`src/feelies/alpha/loader.py:1022`). The runtime controller also does not inspect departing or incoming state (`src/feelies/risk/hazard_exit.py:165`).

Severity: **P1**. The behavior is fail-closed because it only exits. It can still force economically unnecessary flattening when a policy meant "exit only on departure from normal" but the implementation exits on any large posterior decay for that symbol.

Recommendation: either implement `applies_to_regimes` end-to-end, including loader schema, policy object, tests, and runtime filter; or remove it from architecture examples and document the current all-departures semantics.

## 7. Consumer Coherence Trace

| Consumer | Input | Aggregation | Fail-safe default | Coherence verdict |
|---|---|---|---|---|
| Orchestrator M2 | `NBBOQuote` | One posterior vector per engine/symbol/sequence | Uncalibrated `RegimeState.calibrated=False`; critical alert if calibration disabled (`src/feelies/kernel/orchestrator.py:3317`, `src/feelies/kernel/orchestrator.py:3432`) | Coherent. |
| RegimeGate | `RegimeState` + snapshot/sensor cache | Boolean ON/OFF latch | Unknown/uncalibrated/low-discriminability regime refs make gate unavailable and reset OFF (`src/feelies/signals/regime_gate.py:410`, `src/feelies/signals/horizon_engine.py:389`) | Coherent and conservative. |
| HorizonSignalEngine | Gate result + alpha evaluate | Emits alpha signal only if gate ON and data usable | Entry suppressed on warm/stale; gate-close FLAT preserved (`src/feelies/signals/horizon_engine.py:333`, `src/feelies/signals/horizon_engine.py:470`) | Coherent. |
| Position sizer | `current_state(engine)` | EV over posterior state factors | No engine `1.0`; configured engine missing posterior min factor (`src/feelies/risk/position_sizer.py:111`) | Coherent, but docs should match code. |
| Basic risk manager | `current_state(engine)` | EV limit multiplier, clamp no amplification | No engine neutral; configured missing posterior min scale (`src/feelies/risk/basic_risk.py:790`) | Coherent and exposure-safe. |
| Order risk | Sized intent/order | Applies same adjusted max sizing/limits | Regime-scaled veto through `check_order` and per-leg intent checks (`src/feelies/risk/basic_risk.py:231`, `src/feelies/risk/basic_risk.py:334`) | Coherent. |
| Hazard exit | `RegimeHazardSpike` | Threshold and age policy | No position, under threshold, or duplicate => no order (`src/feelies/risk/hazard_exit.py:165`, `src/feelies/risk/hazard_exit.py:210`) | Safe, but lacks departing-state filter and per-strategy attribution. |
| Composition | Mechanism scores | Caps and turnover optimization | Exit-only mechanisms skipped/zeroed (`src/feelies/composition/cross_sectional.py:65`, `src/feelies/composition/cross_sectional.py:223`) | Coherent for current mechanisms. |

The main doc mismatch is missing configured posterior behavior: code uses minimum scale/factor, while the regime skill still describes neutral `1.0x` missing-state behavior in places (`.cursor/skills/regime-detection/SKILL.md:52`, `.cursor/skills/regime-detection/SKILL.md:318`, `src/feelies/risk/position_sizer.py:111`, `src/feelies/risk/basic_risk.py:790`).

## 8. Microstructure Grounding

The stack is microstructure-plausible but observation-limited.

### 8.1 What L1 regime can support

L1 NBBO spread is a reasonable proxy for:

| Phenomenon | Why spread helps | Stack support |
|---|---|---|
| Trading cost / liquidity | Spread directly measures immediate quoted cost | Default emissions use `log(spread / mid)` (`src/feelies/services/regime_engine.py:127`). |
| Adverse-selection stress | Dealers widen quotes when informed flow risk rises | `vol_breakout` can proxy stress, but only through spread. |
| Inventory/liquidity withdrawal | Dealers can widen spreads under inventory pressure | Gate sensors supplement posteriors for inventory and volatility (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:59`). |
| Quote-regime persistence | HMM transitions encode dwell and state persistence | Transition matrix and optional time scaling (`src/feelies/services/regime_engine.py:165`, `src/feelies/services/regime_engine.py:762`). |

### 8.2 What L1 regime cannot identify alone

| Missing feature | Consequence |
|---|---|
| L2 depth and queue position | Cannot distinguish a stable wide spread with deep queues from fragile top-of-book liquidity. |
| Trade sign/impact in the regime engine | Kyle-style toxicity is inferred indirectly unless alpha sensors supply impact/flow features. |
| Hidden liquidity / midpoint liquidity | Spread can overstate actual execution cost. |
| Halt/auction microstructure | MOC alpha handles scheduled windows separately, not through posterior state (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:120`). |
| Volatility without spread widening | Default engine may miss it; optional `hmm_3state_spread_vol` addresses this only when selected (`src/feelies/services/regime_engine.py:858`). |

The practical interpretation should therefore be: "posterior over spread/liquidity regimes", not "posterior over latent market truth." The gate should be validated by forward returns and execution cost, not by label intuition.

### 8.3 Literature alignment

The implementation aligns with standard ideas but uses a deliberately small feature set:

| Literature idea | Relevance | Implementation caveat |
|---|---|---|
| Hamilton (1989), Markov-switching regimes | Hidden discrete states with persistent transitions | Fixed transitions, empirical calibration; no full macro-style estimation. |
| Rabiner (1989), HMM filtering | Forward recursion and likelihood update | Deterministic engineering filter, not general-purpose HMM training. |
| Kim (1994), dynamic models with switching | Sequential state inference under Markov switching | No parameter uncertainty or smoothing in live path. |
| Kyle (1985), price impact/informed trading | Spread and impact can reflect adverse selection | Default engine observes spread, not signed flow. |
| Glosten-Milgrom (1985), bid/ask and asymmetric information | Spreads widen under adverse selection | Posterior state remains a proxy. |
| Ho-Stoll (1981), dealer inventory/spread setting | Inventory and uncertainty can affect quotes | Inventory sensors live in alphas, not default regime emissions. |
| Easley-Lopez de Prado-O'Hara (2012), flow toxicity | Toxic flow can degrade liquidity | Requires flow/trade features outside default spread-only HMM. |

## 9. Test Coverage And Gaps

### 9.1 Commands run

| Command | Result |
|---|---|
| `uv run pytest tests/services/test_regime_engine.py tests/services/test_regime_hazard_detector.py -q` | `71 passed in 0.08s` |
| `uv run pytest tests/signals/test_regime_gate_dsl.py tests/signals/test_regime_gate_dsl_props.py -q` | `90 passed in 0.23s` |
| `uv run pytest tests/determinism/test_regime_hazard_replay.py tests/determinism/test_hazard_exit_replay.py -q` | `6 passed in 0.03s` |

### 9.2 Existing coverage

| Area | Evidence | What it proves |
|---|---|---|
| Default uncalibrated artifact | `tests/services/test_regime_engine.py:647` | Realistic tight spreads pin uncalibrated defaults to `vol_breakout`; gate fail-safe matters. |
| Gate uncalibrated/discriminability fail-safe | `tests/signals/test_regime_gate_dsl.py:417` | Posterior refs fail closed when regime is untrusted. |
| Shipped gate hold bands | `tests/signals/test_regime_gate_dsl_props.py:253` | Some shipped gates have non-empty hysteresis bands. |
| Risk missing-posterior behavior | `tests/risk/test_basic_risk.py:630`, `tests/risk/test_position_sizer.py:185` | Configured missing posterior uses minimum scaling/factor; no engine remains neutral. |
| Hazard detector mechanics | `tests/services/test_regime_hazard_detector.py` | Suppression, rearm, mismatches, reset, tied incoming, and purity behavior. |
| Hazard exit wiring and behavior | `tests/services/test_hazard_exit_controller_wiring.py:73`, `tests/risk/test_hazard_exit.py:92`, `tests/integration/test_hazard_exit_e2e.py:170` | Opt-in controller construction, flattening behavior, threshold/min-age/universe/no-position cases. |
| Deterministic replay hashes | `tests/determinism/test_regime_hazard_replay.py:151`, `tests/determinism/test_hazard_exit_replay.py:157`, `tests/determinism/test_regime_state_replay.py:91` | Replay stability for regime state, hazard spikes, and hazard exits. |

### 9.3 Test gaps

| Gap | Severity | Why it matters | Suggested test |
|---|---|---|---|
| `hazard_exit.applies_to_regimes` doc/code mismatch | P1 | Documented policy cannot be expressed; exits can fire on all departures | Add loader/runtime tests if implementing, or doc test/removal if not. |
| Dead hysteresis constants accepted | P1 | Alpha author may believe margins are active | Strict-mode load test that unused hysteresis constants fail. |
| Gate literal/param drift | P1 | Parameter sweeps can leave gate thresholds stale | Loader lint: gate constants matching declared param defaults or explicit exemption. |
| Dynamic `LIQUIDITY_STRESS` direction abstention | P1 | Future stress alpha could emit entries through dynamic code path | Validator/runtime test requiring stress mechanisms to produce FLAT/exit-only regardless of static extraction. |
| Time-scaled transition profile | P1/P2 | Quote-time regimes may misstate dwell across symbols and activity regimes | Deterministic unit test plus offline dwell calibration report by symbol/cohort. |
| Economic validation of posterior buckets | P2 | Current tests prove mechanics, not alpha value | Diagnostic report: occupancy, entropy, transition dwell, forward returns, spread cost, fill quality by posterior decile. |

## 10. Prioritized Backlog And Open Questions

### 10.1 Backlog

| Priority | Item | Recommendation | Effort |
|---|---|---|---|
| P1 | Implement or delete `hazard_exit.applies_to_regimes` | Prefer implementation: loader key, policy field, runtime `departing_state` filter, tests for matching and non-matching transitions. | M |
| P1 | Production discriminability profile | Set `regime_min_discriminability` above `0.0` in production configs after cohort validation; consider enabling `enforce_min_pairwise_emission_separation`. | S/M |
| P1 | Time scaling decision | Either enable `use_time_scaled_transitions` with calibrated `transition_time_ref_ns`, or rename/document the default as quote-time. | M |
| P1 | Strict hysteresis lint | Fail alpha load in strict mode when `hysteresis.constants` are unused, or remove unused blocks from shipped alphas. | S |
| P1 | Gate parameter binding | Allow gate expressions to reference declared alpha params, or add explicit loader validation for duplicated literals. | M |
| P1 | Close stress exit-only dynamic gap | Require `LIQUIDITY_STRESS` mechanisms to be statically or runtime proven exit-only before production. | M |
| P1 | Update stale docs for missing posterior | Align `.cursor/skills/regime-detection/SKILL.md` with safer current code: configured engine missing posterior uses minimum scale/factor, not neutral `1.0x`. | S |
| P2 | Per-strategy hazard attribution | Move hazard exits from symbol-net flattening to strategy-attributed position slices when the position model supports it. | L |
| P2 | Economic regime diagnostics | Add an offline report for posterior occupancy, entropy, dwell, forward returns, spread cost, fill quality, and gate ON/OFF performance. | M |
| P2 | Optional richer observations | Validate `hmm_3state_spread_vol` or future flow/depth dimensions per symbol cohort before switching any production alpha. | M/L |

### 10.2 Open questions for data runs

1. For each traded symbol/cohort, what is the realized distribution of `discriminability`, posterior entropy, state occupancy, and dwell time under the default engine?
2. Do `P(normal)`, `P(vol_breakout)`, and entropy buckets improve forward returns net of spread and expected slippage for each alpha family?
3. Does time scaling improve regime persistence in wall-clock time without degrading deterministic parity or alpha hit-rate?
4. Does the optional spread+vol engine improve conditional-return separation on tight-spread names where the spread-only engine is weak?
5. How often do hazard spikes occur by departing/incoming state, and how many historical exits would have been suppressed by `applies_to_regimes`?
6. How much cross-strategy exposure is flattened by symbol-net hazard exits in multi-alpha runs?

### 10.3 Final assessment

The current implementation is robust as a deterministic, fail-safe regime filter. Its main limitation is not software correctness; it is semantic precision. The default posterior is a posterior over spread-regime labels, while several alpha and doc names invite a stronger interpretation such as volatility, toxicity, or liquidity stress. That stronger interpretation should only be used after cohort-level diagnostics show that the posterior improves forward returns or execution cost.

