# Regime Stack Audit — feelies

**Date:** 2026-06-11
**Scope:** `NBBOQuote → RegimeState → RegimeGate → Signal → risk/sizer → OrderRequest`
**Mode:** Read-only, evidence-based. No production code modified.
**Test status:** `148 passed` across the six mandated suites (regime engine, hazard detector, gate DSL + props, hazard replay, hazard-exit replay).

---

## 0. Remediation status (2026-06-12)

The prioritized backlog (§9) was implemented in PR #123. A subsequent APP
2026-06-01..05 backtest then showed the **speculative gate-semantic
changes were net-harmful** (signals 4,833 → 414; Net P&L +$1,804 → −$1,889):
the periods the new entry bound / entropy guard filtered out were
*profitable* for `sig_benign_midcap_v1` on APP, contradicting the audit's
adverse-selection hypothesis. Those changes were therefore **reverted** in
PR #124; the pure correctness/safety fixes were kept. The post-#124 APP
backtest reproduces the pre-#123 (PR #122) result **bit-for-bit**, confirming
the revert restored trading behaviour exactly while the retained fixes act
only in failure/misconfig paths (they cannot change entry selection).
Updated status:

| Item | Status | Where |
|---|---|---|
| **P0-1** uncalibrated engine pins to one extreme | **Fixed (kept)** | `RegimeState.calibrated` field (`core/events.py`); orchestrator publishes it from `engine.calibrated` and escalates the unset-calibration alert to CRITICAL (`kernel/orchestrator.py`); gate fails `P()`/`dominant`/`entropy` safe to OFF when uncalibrated (`signals/regime_gate.py`). Golden test locks the pin-to-vol_breakout behaviour. |
| **P1-1** off-path `RegimeGateError` not fail-safe | **Fixed (kept)** | `signals/horizon_engine.py` `except RegimeGateError` now resets the latch + emits FLAT close when previously ON. |
| **P1-2** no load-time `P()` validation | **Fixed (kept)** | `alpha/loader.py` `_validate_gate_posterior_states` rejects unknown state names at load. |
| **P1-3** tick-time transition default OFF | **Deferred (documented)** | Flipping the global default would change every posterior and invalidate locked L5/L6 baselines, and needs per-cohort `dt_reference` tuning. Strong RECOMMENDED guidance added to `platform.yaml`; remains explicit opt-in. |
| **P1-4** dead hysteresis blocks | **Reverted** | Removal was bundled with the harmful gate edits and rolled back to keep the revert clean; the blocks are still provably dead (loader warns) and can be removed independently. |
| **P1-5** hawkes gate stance + 0.30 hazard | **Reverted** | Backtest showed the entry bound + threshold raise net-harmful; needs the appendix conditional-exit data run to set a calibrated threshold. Re-opened as backlog. |
| **P1-6** loose ON-floor admits vol mass | **Reverted** | `P(vol_breakout) < 0.30` entry bound destroyed alpha on APP; the audit's adverse-selection premise was not supported by the data. Re-opened — needs a data-calibrated bound, not a guessed 0.30. |
| **P1-7** hazard exits symbol, not strategy | **Deferred (documented)** | Per-strategy scoping touches reconciliation; symbol-net-flatten semantics now documented prominently in `risk/hazard_exit.py` with the `universe` filter as the interim control. |
| **P1-8** short-half-life alpha no mid-interval exit | **Reverted** | `hazard_exit` opt-in on inventory rolled back with the rest of the gate changes pending validation. Re-opened as backlog. |
| **P2-1** richer regime features (2nd dimension) | **Deferred (documented)** | Full engine redesign; would break all baselines. Out of scope for this pass. |
| **P2-2** entropy-gating for diffuse posteriors | **Reverted** | `entropy > 0.95` forced OFF on most non-peaked posteriors and was a primary cause of the 91% signal drop. Re-opened — any entropy guard must be calibrated to the engine's realised posterior-entropy distribution. |
| **P2-3** `pNN` regex `p100` unreachable | **Fixed (kept)** | Regex widened to `\d{1,3}` (`signals/regime_gate.py`); bound check unchanged. |
| **P2-4** within-prefix calibration lookahead | **Fixed (documented, kept)** | Rationale added to `_calibrate_regime_engine` docstring. |
| **P2-5** calibration drift detection / auto-refit | **Deferred (documented)** | New subsystem with replay-determinism implications; out of scope. |
| **P2-6** economic property tests for gates | **Fixed (kept, rescoped)** | Replaced the (reverted) "ON ⇒ bounded vol mass" lock with a design-agnostic **non-empty hysteresis band** property loaded from the shipped gates (`tests/signals/test_regime_gate_dsl_props.py`). |

**Lesson:** P1-5/P1-6/P1-8/P2-2 were economic-soundness changes the audit
itself flagged as needing the appendix data runs (§10). They were shipped
without that validation and the backtest falsified the hypothesis. The
correctness fixes (P0-1/P1-1/P1-2/P2-3/P2-4) are orthogonal to entry
selection and stay. Any future re-introduction of an entry bound or entropy
guard must be threshold-calibrated against conditional forward-return data,
not assumed.

New/changed tests (kept): `tests/signals/test_regime_gate_dsl.py` (P0-1,
P2-3), `tests/signals/test_horizon_signal_engine.py` (P1-1),
`tests/alpha/test_signal_layer_loader.py` (P1-2),
`tests/signals/test_regime_gate_dsl_props.py` (P2-6 hysteresis-band),
`tests/services/test_regime_engine.py` (P0-1 golden). Suites green; ruff +
mypy-strict clean.

> Convention: findings are tagged **[BUG]** (implementation defect),
> **[MODEL]** (deliberate modeling choice with consequences), or
> **[L1]** (fundamental limit of an L1/NBBO-only, 1-D-observation
> engine). Severity P0/P1/P2 per the brief.

---

## 1. Executive summary

1. **[P0/MODEL] The default deployment runs the regime engine *uncalibrated*, and uncalibrated it does not "discriminate poorly" — it pins to one extreme state.** `regime_calibration_max_quotes` defaults to `None` (`core/platform_config.py:379`), so calibration is *skipped* (`kernel/orchestrator.py:3092-3122`) while `regime_engine` defaults to ON (`platform_config.py:76`). The placeholder emission means (`regime_engine.py:181-185`) sit at log-relative-spread −4.5/−3.5/−2.5 (≈ 1.1 %/3.0 %/8.2 % relative spread), whereas real US-midcap NBBO relative spread is ≈ 1–10 bps (log ≈ −9…−7). Every real quote lands far in the left tail of all three Gaussians, where the widest-σ state (`vol_breakout`, σ=0.7) has the slowest-decaying likelihood → **the posterior collapses toward `vol_breakout ≈ 1.0`**, not toward uniform. Consequence: every `P(normal) > 0.5..0.65` gate (benign, kyle, hawkes, inventory) **never latches ON**, the sizer/risk pin to the 0.5× `vol_breakout` scale, and the hazard detector never sees a flip. The whole SIGNAL book is silently inert. This is "fail-safe" in the Inv-11 exposure sense but is a catastrophic *availability* failure.
2. **[P1/BUG] `UnknownRegimeStateError` from a typo in `off_condition` is NOT fail-safe-unwound.** `horizon_engine._dispatch_one` catches `UnknownIdentifierError` and arithmetic errors and unwinds an open latch (`horizon_engine.py:372-438`), but `RegimeGateError` (the parent of `UnknownRegimeStateError`) is caught separately and merely logs + returns *without* `gate.reset()` or `_publish_gate_close` (`horizon_engine.py:403-410`). A valid `on_condition` + typo'd `off_condition` (`P(noraml)`) therefore latches ON and can never exit via the gate → orphaned position.
3. **[P1/BUG] `P(<state>)` names are validated only at evaluation, never at load.** The loader injects `regime_state_names` (`alpha/loader.py:1301`) but performs no cross-check of `P(...)` arguments against the engine's `state_names`; the gate AST validator cannot (it has no engine at compile time, `regime_gate.py:272-278`). A misspelled state name passes load and surfaces only at runtime (and per finding #2, possibly without unwind).
4. **[P1/MODEL] Tick-indexed transition matrix → dwell time varies 10× with quote rate.** `p_stay = 0.990` (`regime_engine.py:170-174`) ⇒ mean dwell ≈ 100 ticks = 10 s @ 10 q/s, 2 s @ 50 q/s, 1 s @ 100 q/s. `transition_time_scaling_enabled` fixes this but defaults OFF (`regime_engine.py:202`, `platform_config.py:79`). Regime stickiness therefore drifts intraday with quote intensity.
5. **[P1/MODEL] Dead hysteresis config in two production alphas.** `sig_hawkes_burst_v1` and `sig_kyle_drift_v1` declare `posterior_margin: 0.20 / percentile_margin: 0.30` but never reference them in their ON/OFF expressions, so they are no-ops (loader warns, `regime_gate.py:691-705`). Their *effective* hysteresis is the implicit dual-threshold gap (0.6 ON / 0.4 OFF), which is fine — but the declared block misleads authors into thinking a margin band exists.
6. **[P1/MODEL] `sig_hawkes_burst_v1` gates ON in calm/tight regime for a self-exciting-burst mechanism, and sets `hazard_score_threshold: 0.30`.** Gating a HAWKES_SELF_EXCITE alpha on `P(normal) > 0.6 and spread_z_30d < 1.0` (alpha yaml :96-99) means it trades only *before* the burst widens spreads; the 0.30 hazard threshold (vs 0.85 default) then exits on the first mild posterior wobble (a 0.70→0.49 two-tick decay scores 0.30). Likely starves the edge.
7. **[P1/MODEL] Gate uses hard thresholds; risk/sizer use EV — they can disagree on "stressed".** Benign's gate latches ON at `P(normal) > 0.5` while up to ~0.49 mass sits on `vol_breakout`; the signal fires, while risk EV (`basic_risk.py:721-760`) and sizer EV (`position_sizer.py:105-126`) quietly scale exposure down. No Inv-11 breach (series design, both clamp `min(1.0, EV)`), but the alpha *does* fire into elevated adverse-selection mass.
8. **[P1/MODEL] `HazardExitController` flattens the *symbol* net position, not the per-strategy position.** `_maybe_emit_exit` reads `position_store.get(symbol)` (`hazard_exit.py:206`) keyed only by symbol; the `strategy_id` is carried for suppression/labeling. With hawkes's universe = full platform symbols (`bootstrap.py:1869-1870`), a hawkes hazard spike can flatten a position another alpha opened on the same symbol. Exit-only (Inv-11 safe) but cross-alpha interference / mis-attribution.
9. **[P1/L1] Three spread-derived states cannot represent volatility-without-spread-widening, inventory pressure, or information asymmetry.** The observation is a single scalar `log(spread/mid)` (`regime_engine.py:486-493`); the three "states" are just spread terciles. `vol_breakout` is *wide spread*, not realized volatility.
10. **[P2/BUG] `pNN` percentile literal regex is `p\d{1,2}` (`regime_gate.py:118`) → `p100` is unreachable** despite the range-check message claiming `p0..p100` (`regime_gate.py:429`). Latent only (no shipped gate uses `pNN`). Percentile *scale* is otherwise consistent: literals return `NN/100 ∈ [0,1]` and `_percentile` bindings are Hazen `(rank-0.5)/n ∈ [0,1]` (`features/impl/rolling_stats.py:24`, `218`).
11. **[P2/MODEL] Boot calibration has within-prefix lookahead.** `_calibrate_regime_engine` fits emissions from the first `max_q` quotes (`orchestrator.py:3124-3141`); posteriors for ticks early in that prefix are computed with emission params estimated from later-in-prefix ticks. Deterministic (Inv-5 holds), but a soft Inv-6 wrinkle for the warm-up window.
12. **[GOOD] Single-writer holds:** the only `.posterior(` call site in `src/` is `orchestrator.py:3204`. All consumers use `current_state()`.
13. **[GOOD] Idempotency, NaN/inf reset, predict/update index convention, checkpoint flags-fingerprint, session-boundary hazard reset, and DSL AST whitelist are all correct and tested** (see §3–§6).
14. **[GOOD] Fail-safe defaults verified at the value level:** both consumers clamp `min(1.0, EV)` and default unknown names to `min(scale)` (`basic_risk.py:756-760`, `position_sizer.py:119-126`), tested in `tests/risk/test_position_sizer.py:88-109`.
15. **Top opportunity:** make calibration mandatory-by-default (or fail-loud-and-disable-gates on uncalibrated), enable transition time-scaling, and add a richer (2-D) observation (e.g. spread + realized-vol or trade-intensity) so the taxonomy carries economic meaning rather than spread terciles.

---

## 2. Regime stack inventory

| Engine (registry) | Impl | States (index→name) | Default flags | Calibration |
|---|---|---|---|---|
| `hmm_3state_fractional` (default) / `hmm_3state_spread_filter` (alias) | `HMM3StateFractional` (`regime_engine.py:126`, registry `:821-825`) | 0 `compression_clustering`, 1 `normal`, 2 `vol_breakout` (`:164`) | time-scaling OFF, per-symbol OFF, separation-gate OFF, order-by-mean ON (`:202-209`) | OFF by default (`platform_config.py:379` = `None`) |

| Consumer | Reads | Aggregation | Fail-safe |
|---|---|---|---|
| Orchestrator M2 (`_update_regime`, `orchestrator.py:3195`) | `posterior(quote)` | argmax (lowest-index tie via `max(range,…)`, `:3206`) | engine None → skip |
| RegimeGate (`regime_gate.py:588`) | `P()`, `dominant`, `entropy` from cached `RegimeState` + sensor bindings | boolean ON/OFF latch | cold start OFF; missing binding → OFF + unwind |
| Risk `_regime_scaling` (`basic_risk.py:721`) | `current_state` | `Σ pᵢ·scaleᵢ`, clamp `min(1.0,·)` | None → 1.0×; unknown → min scale |
| Sizer `_get_regime_factor` (`position_sizer.py:105`) | `current_state` | same EV + clamp | None → 1.0× |
| HazardDetector (`regime_hazard_detector.py:188`) | pairs of `RegimeState` | pure two-tick decay | prev None → None |
| HazardExitController (`hazard_exit.py:144`) | `RegimeHazardSpike`, `Trade` | threshold + min-age | no position / below threshold → no-op |

| Alpha | Mechanism / half-life | engine | on_condition | off_condition | hysteresis | hazard_exit |
|---|---|---|---|---|---|---|
| `sig_benign_midcap_v1` | KYLE_INFO / 120 s | hmm_3state | `P(normal)>0.5 and spread_z_30d<1.5` | `P(normal)<0.35 or spread_z_30d>3.0 or realized_vol_30s_zscore>4.5` | none (implicit) | — |
| `sig_kyle_drift_v1` | KYLE_INFO / 600 s | hmm_3state | `P(normal)>0.6 and spread_z_30d<=1.0` | `P(normal)<0.4 or spread_z_30d>2.0 or realized_vol_30s_zscore>3.5` | **dead** (declared, unreferenced) | — |
| `sig_hawkes_burst_v1` | HAWKES_SELF_EXCITE / 30 s | hmm_3state | `P(normal)>0.6 and spread_z_30d<1.0` | `P(normal)<0.4 or spread_z_30d>2.5 or realized_vol_30s_zscore>3.5` | **dead** | enabled, thr **0.30** |
| `sig_inventory_revert_v1` | INVENTORY / 20 s | hmm_3state | `abs(quote_replenish_asymmetry_zscore)>2.0 and dominant=="normal" and P(normal)>0.65 and P(vol_breakout)<0.20` | `dominant!="normal" or P(normal)<0.5-posterior_margin or P(vol_breakout)>0.30 or abs(...)<2.0-percentile_margin or spread_z_30d>2.0 or realized_vol_30s_zscore>3.5 or quote_hazard_rate<4.0` | **active** (0.20 / 0.30) | — |
| `sig_moc_imbalance_v1` | SCHEDULED_FLOW / 240 s | hmm_3state (declared, **unused** — no `P()/dominant`) | `scheduled_flow_window_active==1.0 and seconds_to_window_close>60` | `scheduled_flow_window_active==0.0 or seconds_to_window_close<30 or realized_vol_30s_zscore>3.5` | removed | — |
| `_paper_smoke_v1` | — | hmm_3state | `True` | `False` | — | — |

---

## 3. RegimeEngine audit (`services/regime_engine.py`)

### 3.1 Model specification
Hidden Markov chain over `K=3` states with a **fixed** row-stochastic transition `T` (`:170`); observation `yₜ = log(spreadₜ / midₜ)` (`:486-493`); emission `p(y|k) = N(y; μ_k, σ_k²)` diagonal Gaussian (`:803-809`). Recursion is the standard forward (filtering) step: predict `π̄ = πₜ₋₁ᵀ T` (`:788-801`), update `πₜ ∝ π̄ ⊙ ℓ` (`:811-816`). This is an **online forward filter with frozen parameters**, in the spirit of Elliott, Aggoun & Moore (1995, *Hidden Markov Models: Estimation and Control*) restricted to the filtering equations — *not* Hamilton (1989, "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle", *Econometrica* 57:357) or Kim (1994, "Dynamic Linear Models with Markov-Switching", *J. Econometrics* 60:1) regime-switching EM, where `T` and emissions are jointly estimated. The class docstring states this honestly (`:130-135`); graded as a filter, the predict/update math is **correct**.

### 3.2 Is `log(spread/mid)` a sufficient statistic? — **[L1] No.**
A single monotone scalar can only order states by spread, so the three states *are* spread terciles (`calibrate` buckets by quantile, `:368-386`; `_sort_emissions_by_mean`, `:388-393`). It captures the liquidity/spread axis but is blind to: realized volatility without spread widening (a fast-but-tight tape reads as `normal`/`compression`), inventory pressure / quote-replenishment asymmetry, and information asymmetry (OFI/Kyle's λ). `vol_breakout` is a misnomer — it is "widest-spread tercile". Recommend renaming or adding a second observation dimension (see §9 P2-1).

### 3.3 Emission calibration
- Quantile buckets via integer split `i*n//k` (`:375-377`); `_MIN_CALIBRATION_SAMPLES=30` (`:187`); σ floored at 0.01 (`:188`, `:381-384`). Pooled by default; per-symbol opt-in (`:336-357`). Sound for a moment fit.
- `order_emissions_by_increasing_mean=True` (`:207`) makes index `i` = i-th spread tercile *after* sort. Because the registry names are themselves spread-ordered (`compression<normal<vol_breakout`), index↔name **does** align as long as the flag stays on. **If disabled**, calibration order is data order and the names silently permute → `P(normal)` reads the wrong bucket. **[MODEL] Label stability is contingent on the default flag.**
- Pairwise separation `d = |μ_i−μ_j| / √(σ_i²+σ_j²) ≥ 0.5` (`:395-436`). This is a 1-D, two-class effect-size proxy (≈ a scaled Bhattacharyya/d′). `d=0.5` corresponds to heavy Gaussian overlap (per-pair Bayes error ≈ 40 %), so it is a weak floor for *confident* 3-way posteriors; it rejects only near-degenerate fits. It is also only enforced when `enforce_min_pairwise_emission_separation=True` (default OFF).
- **Uncalibrated discrimination (quantified):** placeholder means at log −4.5/−3.5/−2.5 (`:181-185`). For a typical midcap observation `y ≈ −8` (≈3.4 bps): `|z₀|=11.7, |z₁|=9.0, |z₂|=7.9` → likelihoods ∝ `e^{−68}/0.3`, `e^{−40.5}/0.5`, `e^{−30.9}/0.7`. **State 2 (`vol_breakout`) dominates by ~10⁴**, so the posterior pins to `vol_breakout`. (Note the *separation* of the defaults is fine — `d₀₁=1.71, d₁₂=1.16` — the failure is mean *mis-location* vs the real spread scale.) This is the mechanism behind Exec-summary finding #1.

### 3.4 Transition dynamics — see Exec #4
Per-tick application, dwell = `1/(1−p_stay)` ticks. Time-scaling (`:723-780`) re-exponentiates `p_stay^scale`, renormalizes off-diagonals, caches by `scale` (`:739-744`); edge cases (first quote → scale 1.0 `:730-731`; gaps clamped to `[0.01,40]` `:735-738`; NaN/inf/≤0 scale floored `:748-749`) are handled. Math verified correct. **Default OFF is the risk**, not the implementation.

### 3.5 Update correctness — **[GOOD]**
- Predict convention `π̄[j] = Σ_i T[i][j]·π[i]` = `π @ T`, row-stochastic — correct (`:788-801`).
- Invalid spread (≤0, locked/crossed) → prediction-only (`:489-490`); economically reasonable (no spread information → diffuse via `T`). Tested (`test_locked_market_*`). It still advances the seq watermark — fine.
- NaN/inf → substitute uniform in place (no `reset()`), one-tick, bounded (`:498-507`). Acceptable fail-safe; tested.

### 3.6 Idempotency & single-writer — **[GOOD]**
- Keyed on `quote.sequence` (`:463-466`), watermark committed only after a successful update (`:508-517`) so a mid-update exception re-runs rather than caches a phantom (tested `test_exception_mid_update_leaves_seq_watermark_unset`).
- **Single-writer verified repo-wide:** sole `.posterior(` caller is `orchestrator.py:3204`. *Not enforced in code* (convention only) and *no test* asserts it — see §8.

### 3.7 Checkpoint / restore determinism — **[GOOD]**
Schema v2 adds `flags_fingerprint` (`:529-562`); `restore` rejects a blob whose fingerprint disagrees (`:640-651`), accepts legacy v1 with a warning (`:624-639`), and rolls back atomically on any failure (`:713-721`). Tested thoroughly (`test_mismatched_*`, `test_legacy_v1_blob_loads_with_warning`).

---

## 4. RegimeGate audit (deep dive — `signals/regime_gate.py`, `signals/horizon_engine.py`)

### 4.1 Parse-time safety (G2 purity) — **[GOOD]** with one latent nit
`_ALLOWED_NODES` (`:129-156`) whitelists boolean/compare/arith/`Name`/`Call`; `_validate` (`:243-278`) rejects everything else, restricts `Call` callees to bare `abs|min|max|P`, forbids keyword args, and requires `P(...)` to take exactly one bare identifier. `Attribute`, `Subscript`, `Lambda`, comprehensions, `JoinedStr`, etc. are absent from the whitelist → rejected (tested `test_compile_rejects_forbidden`, property `test_forbidden_expressions_always_raise`). No scope leak path found.
- **[P2/BUG]** `pNN` regex `p\d{1,2}` (`:118`) caps at `p99`; `p100` is silently treated as a sensor id (→ `UnknownIdentifierError`) despite the range message saying `p0..p100` (`:429`).

### 4.2 `P()` resolution — **[P1/BUG]** (Exec #3)
Resolved against `regime.state_names` at eval (`:464-476`), raising `UnknownRegimeStateError` on a miss. There is **no load-time validation** (loader only injects `regime_state_names`, `loader.py:1301`; gate validator has no engine). A typo loads clean and fails at first evaluation.

### 4.3 Runtime bindings & causality (Inv-6) — **[GOOD]**
- `P/dominant/entropy` come from the `RegimeState` cached by `_on_regime_state` (`horizon_engine.py:265-267`), i.e. the most recent M2 posterior with timestamp ≤ boundary T. No lookahead.
- Sensor bindings: `_build_bindings` (`horizon_engine.py:576-622`) prefers `snapshot.values` (boundary aggregates ≤ T) and uses the live sensor cache only via `setdefault` for absent ids (skill contract). `_percentile`/`_zscore` are split off the same `values` map (`:609-616`) — consistent source, no cross-tick leak.
- Missing binding → `UnknownIdentifierError` → `gate.reset(symbol)` + unwind if previously ON (`horizon_engine.py:372-402`). Aligned with warm/stale policy.

### 4.4 Hysteresis state machine — **[GOOD]** with dead-config caveat
`evaluate` (`regime_gate.py:588-629`): OFF + on_condition → ON; ON + off_condition → OFF; else hold (the band). Per-symbol latch (`self._state[symbol]`), cold start OFF (`:573-575`). Margins are injected as named constants **only when referenced** (`:608-619`); declared-but-unreferenced margins are dead (loader warns, `:691-705`). hawkes & kyle hit this (Exec #5). The *effective* hysteresis for those two is the dual-threshold gap, which is real and adequate — but the YAML is misleading.
- **Overlap band concern (Exec #7):** benign ON at `P(normal)>0.5` admits `P(vol_breakout)` up to ~0.49. Falsifiable test: *if the gate is ON while `P(vol_breakout) > 0.3`, benign is firing KYLE_INFO entries into elevated wide-spread/adverse-selection mass.* Recommend raising the ON floor or adding `P(vol_breakout) < x` to benign/kyle/hawkes ON conditions (inventory already does).

### 4.5 Interaction with HorizonSignalEngine — **[GOOD]**
- Gate is evaluated **before** `signal.evaluate` (`horizon_engine.py:364-451`) — verified.
- Warm/stale guard runs **before** the gate (`:342-362`) → stale features cannot fire entries.
- Regime OFF: entries suppressed (`:443-444`); ON→OFF and the missing-binding/arith fail-safe paths emit a FLAT `_publish_gate_close` (`:481-515`) so exits are permitted. Inv-11 honoured on those paths.
- **[P1/BUG] gap (Exec #2):** `except RegimeGateError` (`:403-410`) — which includes `UnknownRegimeStateError` — logs and returns **without** unwinding a previously-ON latch, unlike the `UnknownIdentifierError` (`:372-402`) and arithmetic (`:411-438`) branches. A latched-ON alpha whose `off_condition` references a bad state name (or otherwise raises a `RegimeGateError` only on the OFF path) cannot exit via the gate.

### 4.6 Operator precedence & edge cases — **[GOOD]**
`and/or/not` map to Python `BoolOp/Not` (`:317-330`); `2.0 - percentile_margin` is a `BinOp` inside the `Compare`, so inventory's `abs(...) < 2.0 - percentile_margin` correctly means `< 1.70`. Division/mod/floordiv are whitelisted and can raise `ZeroDivisionError`, caught by the engine's arithmetic fail-safe (`horizon_engine.py:411-438`, audit P1 G-1). `dominant == "normal"` is string equality, case-sensitive, matched verbatim against `state_names`.

---

## 5. Hazard detector audit (`services/regime_hazard_detector.py`)

- **Detection math — [GOOD].** Fires iff `p_now < p_prev` **and** (`flipped` or `p_now < 1−hyst = 0.70`) (`:221-233`). Matches §20.3.1. The "sliding peak" floor catches a decaying-but-still-argmax dominant (`:91-98`). `hazard_score = clip01((p_prev−p_now)/max(p_prev,ε))` (`:241-243`) — a normalized one-tick *relative decay*, explicitly **not** a survival-analysis hazard rate λ(t)=f(t)/S(t) and **not** time-normalized (skill §"What hazard_score is and is not"). Consumers must threshold against tick rate (relevant to hawkes 0.30, Exec #6).
- **Suppression / re-arm — [GOOD].** One spike per `(symbol, engine, departing_state)` (`:234-239`); re-arm on re-dominance or recovery ≥ floor (`:259-294`). Tested (`test_only_one_spike_per_transition`, `test_re_arms_when_departure_episode_resolves`).
- **Pure-function contract — [GOOD].** `detect(prev, curr, suppressed=None)` is pure; the stateful wrapper only owns the suppression set (`:122-185`). `test_pure_detect_matches_stateful` locks equivalence; L5 replay hash green.
- **Tie handling — [GOOD/benign].** Orchestrator dominant tie = lowest index (`orchestrator.py:3206`); hazard `incoming_state` = `None` on a runner-up tie (`:353-376`). `_validate_dominant_consistency` enforces `dominant_name == state_names[dominant_state]` (`:335-350`); the orchestrator constructs `dominant_name` from the index (`orchestrator.py:3221-3224`) so they cannot disagree. `HazardExitController` ignores `incoming_state` entirely, so the `None`-on-tie asymmetry has no capital impact.
- **Session boundary — [GOOD].** `_reset_regime_session_state` clears `_last_regime_state` and the detector's suppression at every `run_*` (`orchestrator.py:3230-3254`); engine posterior deliberately *not* reset (carry-over). `test_no_cross_session_phantom_spike` covers it.
- **Consumer `HazardExitController`:** threshold from alpha YAML (`bootstrap.py:1890-1906`); exit-only, side derived from sign of position (`hazard_exit.py:218`), so entries are never triggered (Inv-11). **[P1] symbol-vs-strategy scope** (Exec #8): exits the symbol net position, not the per-strategy slice. **[P2] gate-OFF + hazard double-emit:** a gate ON→OFF FLAT and a same-tick `HAZARD_SPIKE` order can both be generated; they collapse at fill reconciliation (second is a no-op once flat) and `_on_bus_hazard_order` dedups by `order_id` (`orchestrator.py:5739-5741`), so quantity is correct — but two exit events appear in the tape.

---

## 6. Consumer coherence audit (signal → risk → order)

| Stage | Component | Regime input | Aggregation | Fail-safe |
|---|---|---|---|---|
| M2 | RegimeEngine | NBBOQuote | posterior vector (argmax→dominant) | engine None → skip |
| Gate | RegimeGate | posteriors + sensors | boolean ON/OFF, **hard thresholds** | OFF (no entry) |
| Signal | HorizonSignalEngine | gate + snapshot | Signal or None | suppress / FLAT close |
| M5 | Position sizer | `current_state` EV | `Σpᵢscaleᵢ`, `min(1.0,·)` | 1.0× |
| M5 | Risk `check_signal` | `current_state` EV | limit × EV, `min(1.0,·)` | 1.0× |
| M6 | Risk `check_order` | `current_state` EV | limit × EV | 1.0× |
| Hazard | HazardExitController | RegimeHazardSpike (dominant decay) | flatten symbol | no action |

**Disagreements & their capital impact:**
- **Threshold vs EV (Exec #7):** gate is a *hard* `P(normal)` cut; risk/sizer are *smooth* EV. A signal can fire at `P(normal)=0.5` while EV scaling already implies "partly stressed". Intended series (sizer proposes ×EV, risk caps limit ×EV — both clamped `min(1.0,·)`, `basic_risk.py:756-760`, `position_sizer.py:119-126`), so no compounding and no amplification. The residual risk is *entry timing*, not sizing: the alpha enters in a regime risk would have down-weighted.
- **Dominant vs posterior vs index:** gate may use `dominant` (argmax name); risk/sizer use full-posterior EV; hazard uses `dominant_state` index. They disagree exactly when the posterior is diffuse (entropy high). In that case the gate's `dominant ==` test is brittle (a 0.34/0.33/0.33 split flips dominant on noise) while EV is stable — another argument for entropy-gating diffuse posteriors.
- **Timing / lag model:** `current_state()` at M5/M6 returns the *same* M2 posterior the gate saw, because M2 is the single per-tick writer (skill "Writer/Reader Contract"). But the *gate fires at horizon boundaries* (30–1800 s) while the posterior updates every tick. A gate latched ON at boundary T persists to T+1 even if the regime flips mid-interval; the only mid-interval escape is the hazard path (exit-only). For short-half-life alphas (inventory 20 s, hawkes 30 s) the gate-evaluation cadence can exceed the alpha's own half-life — see §7.
- **Unknown-state fail-safe alignment — [GOOD]:** risk defaults unknown names to `min(scale_map)` (`basic_risk.py:115,751`), sizer to `min(factors)` (`position_sizer.py:76`). Aligned.

---

## 7. Microstructure grounding

### 7.1 State taxonomy vs reality
| State | Observable proxy | Latent force (claimed) | Reality on L1 spread-only |
|---|---|---|---|
| compression_clustering | tightest log-spread tercile | low vol, clustered liquidity | OK as "tight book" |
| normal | mid tercile | typical | OK |
| vol_breakout | widest tercile | high vol | **conflates** wide spread from vol, from thin liquidity, from quote-stuffing, from open/close — all read identically |

**Undetectable with this engine:** flash events (sub-second, may not move the per-tick spread tercile before they pass), MOC imbalance (correctly handled out-of-band by `moc`'s schedule sensors, *not* regime), halts (spread→0 → prediction-only drift), quote stuffing (reads as `vol_breakout`, indistinguishable from genuine stress).

### 7.2 Mechanism × gate matrix
| Family | Shipped alpha | Gate stance | Assessment |
|---|---|---|---|
| KYLE_INFO | benign, kyle | ON in normal + tight | **Sound** — informed-flow capture needs cheap, tight markets; but ON-floor 0.5 (benign) is loose (Exec #7). |
| INVENTORY | inventory_revert | ON in normal + tight + `P(vol_breakout)<0.20` + replenishment asymmetry | **Best-designed gate** — explicitly excludes vol mass; uses margins. |
| HAWKES_SELF_EXCITE | hawkes | ON in normal + tight | **Questionable** — a self-exciting burst tends to widen spreads; gating ON only pre-burst + 0.30 hazard exit likely clips the move (Exec #6). Consider gating ON on *rising intensity within normal* and relying on hazard for the regime flip. |
| SCHEDULED_FLOW | moc | regime unused; schedule sensors only | **Sound** — regime spread-state is irrelevant to a clock-driven window; the declared `regime_engine` is vestigial. |
| LIQUIDITY_STRESS | none shipped | — | **Design rule:** a LIQUIDITY_STRESS alpha must be **exit-only / gate-OFF-on-stress** under G16; it must *not* use a stress regime as an *entry* on_condition (that would amplify exposure into stress, the spirit of Inv-11). |

### 7.3 Cost realism (Inv-12) & decay
- Gates that admit wide-spread mass (benign at high vol_breakout mass) face the largest realized half-spread; benign discloses `half_spread_bps: 2.0` against `edge 9.0` — survivable only if the gate keeps it out of the wide tercile. The loose 0.5 ON-floor erodes this margin.
- **Gate lag vs half-life:** if the spread regime flips faster than the horizon boundary, an ON latch holds stale. For inventory (20 s) and hawkes (30 s), boundary cadence and the not-time-normalized hazard score interact: the hazard spike (per-tick) should dominate exits over the boundary-cadenced gate. Current design already lets hazard exit mid-interval — good — but only hawkes opts into hazard_exit; **inventory_revert (20 s half-life) does not declare `hazard_exit`**, so its only exit is the next boundary's gate OFF. Recommend hazard_exit for short-half-life alphas.

### 7.4 Calibration & deployment protocol (recommended)
Sample ≥ a few thousand intraday quotes per cohort; calibrate per liquidity cohort (per-symbol for the most-traded, pooled otherwise); refit at least daily (spreads regime-shift across the session and across volatility regimes); add drift detection on emission means vs the live spread distribution (KS or mean-shift) to trigger refit. Per-symbol vs global breaks cross-sectional gate comparability the moment two symbols have different emission means for the same state name — composition alphas comparing `P(normal)` across symbols then compare apples to oranges; document that `P()` is only cross-sectionally comparable under pooled calibration.

---

## 8. Test gap matrix

| Invariant / behavior | Coverage | Evidence / gap |
|---|---|---|
| Single-writer (only M2 calls `posterior`) | **Missing** | Convention only; no test asserts it. Add an import-time/AST guard test. |
| Idempotency per `(symbol, sequence)` | Covered | `test_same_symbol_timestamp_returns_cached`, `test_different_sequence_updates` |
| NaN/inf → uniform | Covered | `test_nan_emission_resets_to_uniform`, `_inf_` |
| Checkpoint flags fingerprint | Covered | `test_mismatched_*`, `test_legacy_v1_blob_loads_with_warning` |
| Predict/update math | Partial | sums-to-one + discrimination tested; no golden vector for the predict-step index convention |
| Transition time-scaling | Covered | `test_scale_transition_matrix_more_mixing_at_higher_scale`, cache reuse |
| Separation gate | Covered | `test_enforce_pairwise_separation_rejects_degenerate_calibration` |
| **Uncalibrated pin-to-vol_breakout** | **Missing** | No test quantifies uncalibrated posterior on a realistic midcap spread (Exec #1). |
| DSL whitelist safety | Covered | `test_forbidden_expressions_always_raise` (property) |
| Hysteresis latch boolean/hold | Covered (syntactic) | `test_gate_post_state_is_boolean_and_in_two_value_set` — **encodes syntactic invariants only, no economic ones** |
| Per-symbol gate isolation | Covered | `test_gate_per_symbol_independence` |
| **`UnknownRegimeStateError` in off_condition → no unwind** | **Missing** | Exec #2; no test for the latched-ON + bad-OFF-state path. |
| **Load-time `P()` name validation** | **Missing** | Exec #3. |
| Gate causality (boundary T uses ≤ T) | **Missing** | No replay test pinning gate inputs to ≤ T. |
| Hazard detection + suppression + re-arm | Covered | `tests/services/test_regime_hazard_detector.py` (21 tests) |
| Cross-session hazard reset | Covered | `test_no_cross_session_phantom_spike`, `test_run_backtest_invokes_session_reset` |
| L5 hazard parity / hazard-exit replay | Covered | `test_two_replays_produce_identical_hazard_hash`, `test_two_replays_produce_identical_hazard_exit_hash` |
| Inv-11 EV clamp (sizer/risk) | Covered (sizer) / Partial (risk) | `tests/risk/test_position_sizer.py:88-109`; add the symmetric risk-engine clamp test |
| HazardExit symbol-vs-strategy scope | **Missing** | Exec #8; no multi-alpha-same-symbol test. |

**DSL property tests verdict:** `test_regime_gate_dsl_props.py` encodes **only syntactic/structural invariants** (whitelist closure, eval determinism, boolean latch). It does **not** encode economic invariants (e.g. "gate never ON while `P(vol_breakout) > τ`", or "OFF threshold strictly below ON threshold so the band is non-empty").

**Proposed new tests (specs only):**
1. *Golden uncalibrated posterior* — feed a synthetic AAPL-scale quote (rel spread 2 bps) to a default-constructed engine; assert `P(vol_breakout) > 0.9` (locks Exec #1 as a known hazard) **or**, post-fix, assert near-uniform.
2. *Off-path RegimeGateError unwind* — latch a gate ON, then evaluate with an `off_condition` that raises `UnknownRegimeStateError`; assert a FLAT `_publish_gate_close` is emitted (post-fix).
3. *Load-time P() validation* — load an alpha with `P(noraml)` against a 3-state engine; assert it fails at load.
4. *Economic property* — for random posteriors, assert that whenever any shipped gate is ON, `P(vol_breakout) ≤ (1 − on_floor)` (Hypothesis).
5. *Multi-alpha same-symbol hazard* — two alphas long the same symbol, one with hazard_exit; assert the controller's exit attribution / quantity is correct.
6. *Offline validation harness (methodology)* — over cached APP/AAPL NBBO: compute regime occupancy rates, EM-fit `T̂` vs the assumed `T` (dwell-time gap), and spread-conditional forward returns bucketed by posterior; then gate-ON-vs-OFF conditional Sharpe / hit-rate / realized cost. No randomness, replay from the log.

---

## 9. Prioritized backlog

### P0 — correctness / safety
| # | Component | file:line | One-sentence fix | Impact |
|---|---|---|---|---|
| P0-1 | Default uncalibrated engine pins to one extreme | `platform_config.py:379`, `orchestrator.py:3092-3122`, `regime_engine.py:181-185` | Make calibration mandatory by default (non-None cap), or hard-disable all `P()`-dependent gates (force OFF) + CRITICAL alert when running on placeholder emissions. | Restores the entire SIGNAL book's ability to fire; removes silent total inertness. Effort **M** |

### P1 — economic soundness / latent safety
| # | Component | file:line | One-sentence fix | Impact |
|---|---|---|---|---|
| P1-1 | Off-path `RegimeGateError` not fail-safe | `horizon_engine.py:403-410` | In the `except RegimeGateError` branch, `gate.reset(symbol)` + `_publish_gate_close` when `was_on`. | Closes orphaned-position path. Effort **S** |
| P1-2 | No load-time `P()` name validation | `alpha/loader.py:~384/1301` | Cross-check every `P(...)` argument against the resolved engine `state_names` at load; raise `UnknownRegimeStateError`. | Typos fail at boot, not in production. Effort **S** |
| P1-3 | Tick-time transition default OFF | `regime_engine.py:202`, `platform_config.py:79` | Default `transition_time_scaling_enabled: true` (tune `dt_reference` per cohort). | Stable dwell across intraday quote-rate swings. Effort **S** |
| P1-4 | Dead hysteresis blocks | hawkes/kyle alpha YAML | Either reference the margins in the expressions or delete the block. | Removes misleading config; loader already warns. Effort **S** |
| P1-5 | hawkes gate stance + 0.30 hazard | `sig_hawkes_burst_v1.alpha.yaml:96-99,130-132` | Re-derive gate (intensity-based ON) and raise hazard threshold toward 0.5–0.85 calibrated to tick rate. | Stops clipping the burst edge. Effort **M** |
| P1-6 | Loose ON-floor admits vol mass | benign/kyle YAML | Add `P(vol_breakout) < τ` to ON, or raise `P(normal)` floor. | Keeps entries out of wide-spread adverse selection. Effort **S** |
| P1-7 | Hazard exits symbol, not strategy | `hazard_exit.py:206-219` | Scope the exit quantity to the strategy's own position slice (or document the universe-wide flatten intent). | Prevents cross-alpha flatten / mis-attribution. Effort **M** |
| P1-8 | Short-half-life alpha has no mid-interval exit | `sig_inventory_revert_v1.alpha.yaml` | Add `hazard_exit.enabled` for the 20 s INVENTORY alpha. | Mid-interval regime-flip protection. Effort **S** |

### P2 — research / product
| # | Item | Pointer | Impact |
|---|---|---|---|
| P2-1 | Add a 2nd observation dimension (spread + realized-vol or trade-intensity) | `regime_engine.py:486-495` | Makes `vol_breakout` mean volatility, not just wide spread; richer conditioning. Effort **L** |
| P2-2 | Entropy-gating for diffuse posteriors | gate DSL already exposes `entropy` | Suppress hard `dominant==`/`P()` cuts when entropy high → less noise-driven flip-flop. Effort **S** |
| P2-3 | `pNN` regex `p100` unreachable | `regime_gate.py:118,429` | Widen to `\d{1,3}` + bound check, or fix the message. Effort **S** |
| P2-4 | Within-prefix calibration lookahead | `orchestrator.py:3124-3141` | Document, or fit on a strictly-prior held-out prefix. Effort **S** |
| P2-5 | Calibration drift detection / auto-refit | `_calibrate_regime_engine` | Daily refit + KS drift trigger; per-cohort emissions. Effort **M** |
| P2-6 | Economic property tests for gates | `test_regime_gate_dsl_props.py` | Encode "ON ⇒ bounded vol mass" + "OFF threshold < ON threshold". Effort **S** |

---

## 10. Appendix — open questions needing data runs

1. **(Exec #1) Uncalibrated posterior pin** — Symbol AAPL/APP, any cached intraday session; metric: posterior vector from a default engine on the real spread series. Expected: `P(vol_breakout) → ~1`. Confirms severity of P0-1.
2. **Dwell-time mismatch** — APP/AAPL full session; metric: EM-fit `T̂` dwell times vs the assumed 100-tick dwell, and the same in *seconds* at the session's actual quote rate. Quantifies P1-3.
3. **Gate occupancy & conditional edge** — per shipped alpha; metric: fraction of boundaries with gate ON, and spread-conditional forward return / realized cost / hit-rate in ON vs OFF buckets. Tests whether each gate selects profitable microstructure.
4. **benign ON with vol mass** — metric: distribution of `P(vol_breakout)` conditional on benign gate ON. If a material tail exceeds ~0.3, P1-6 is confirmed.
5. **hawkes hazard exit frequency** — metric: count of `HAZARD_SPIKE` exits per held position at threshold 0.30 vs 0.85. Quantifies edge-clipping for P1-5.
6. **Cross-sectional `P(normal)` comparability** — under per-symbol vs pooled calibration; metric: emission-mean spread of the `normal` state across the universe. Bounds when composition `P()` comparisons break (§7.4).
