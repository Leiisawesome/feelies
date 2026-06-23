# Post-Trade Forensics & Edge-Decay Audit — 2026-06-23

**Scope:** the forensics feedback loop — multi-horizon attribution, decay/TCA detection, the
realized-vs-disclosed close-the-loop modules, and the quarantine auto-trigger surface. This is
the layer that decides whether a live edge is still real (Inv-4) and demotes it fail-safe
(Inv-11). Read-only, evidence-based. **No production code, ledger, or test was modified.**

**Method:** static read of every module under `src/feelies/forensics/` plus the trigger
surface (`alpha/promotion_evidence.py`, `alpha/lifecycle.py`, `alpha/registry.py`,
`alpha/fill_attribution.py`), the supporting types (`storage/trade_journal.py`,
`portfolio/cross_sectional_tracker.py`, `services/regime_engine.py`), the wiring
(`harness/backtest_report.py`, `harness/backtest_runner.py`), and the docs/skills. All
`path:line` citations are against the working tree at branch `claude/charming-keller-xttb6e`.

> **Scope correction (read this first).** The mission scope listed four "forensics core"
> files, but the layer actually ships a **wired** close-the-loop pipeline the skill claims
> does not exist yet: `cost_survival.py` (measure) → `cost_circuit_breaker.py` (automate) →
> `AlphaLifecycle.quarantine` (demote), orchestrated by `session_reconcile.py`, plus
> `edge_calibration.py` (calibrate/gate). These are in scope by the mission's
> wiring-trace requirement (dimension D.3) and are audited below.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `pytest tests/forensics/test_tca.py tests/acceptance/test_decay_divergence.py -q` | **16 passed** |
| `pytest tests/alpha/test_promotion_evidence.py -q -k quarantine` | **10 passed**, 105 deselected |
| `grep` for callers of `MultiHorizonAttributor.attribute` | **none** (only the docstring example) |
| `grep` for non-test callers of `reconcile_session` | **none** (only a docs TODO, `close_the_loop.md:162`) |

Classification legend: **[BUG]** implementation defect · **[MODELING]** modeling choice that
may be wrong but is a judgement call · **[DESIGN]** intentional design (flagged where it
carries decision-corruption risk) · **[DOC]** documentation drift.

---

## 1. Executive summary

Top decision-corruption risks first.

1. **[P0/BUG] Regime attribution is non-causal and non-deterministic.**
   `MultiHorizonAttributor._regime_for` reads `regime_engine.current_state(symbol)`
   (`multi_horizon_attribution.py:232`), which returns the *latest* cached posterior with **no
   timestamp** (`regime_engine.py:559-561`). `attribute()` is a batch call over a whole trade
   history (`multi_horizon_attribution.py:143-173`), so **every trade for a symbol is bucketed
   into whatever regime is current at audit time** — typically the end-of-session regime — not
   the regime in effect at entry. This violates Inv-6 (causality) and the skill's own "argmax
   at FILL time" contract, and makes the regime axis a function of live engine state rather
   than of (fills + provenance), so two audits disagree (Inv-5 forensic-determinism gap).

2. **[P0/MODELING] Mechanism attribution re-infers the mechanism from composition gross
   exposure, not from `Signal` provenance — and smears it across all history.** The mechanism
   axis splits a strategy's *total* realized PnL by the gross-exposure shares of a **single
   latest** `CrossSectionalSnapshot.mechanism_breakdown` (`multi_horizon_attribution.py:137,
   174-194`). It never reads `Signal.trend_mechanism`; in fact `TradeRecord` carries no
   mechanism field at all (`trade_journal.py:22-50`). Consequences: (a) a `KYLE_INFO` alpha's
   PnL lands in the `INVENTORY` bucket whenever the latest snapshot's gross mix says so —
   exactly the Inv-1 mismatch the mission warns about; (b) PnL is split by *gross share*, which
   assumes identical return-on-gross across mechanisms; (c) the split uses one point-in-time
   snapshot applied to the entire PnL history (temporal leakage). This is the documented Inv-1
   vehicle, so it corrupts per-mechanism decay diagnosis at the root.

3. **[P0/BUG] The standalone decay detector is statistically under-powered and cannot fire on
   realistic decay.** `detect_edge_decay` uses `z = (hist_mean − recent_mean) / (hist_stdev +
   1e-9)` (`decay_detector.py:166`), dividing the mean shift by the **per-trade** standard
   deviation rather than the standard error of the recent-50 mean (`σ/√50`). It is therefore
   ~√50 ≈ 7× too insensitive: a genuine 50% edge collapse with per-trade σ on the order of the
   edge gives z ≈ 0.1–0.5, far below the `2.0` gate (`decay_detector.py:168`). Under Inv-4
   ("decay is the default; burden of proof is on continued viability") a detector that stays
   silent through a real partial decay is the costly error. The only passing fixture is a
   catastrophic 5 bps → 0 collapse (`test_tca.py:168`).

4. **[P0/BUG] The decay detector is blind to cost-driven decay (crowding) by construction.**
   Edge is computed from `realized_pnl` (mid-to-mid, **gross of fees**;
   `decay_detector.py:69,148`), while `net_pnl = realized_pnl − fees` exists but is unused
   (`trade_journal.py:52-62`). A net-dead edge whose gross stays flat while costs rise — the
   skill's "most dangerous decay vector" — produces z ≈ 0 and never fires. (Partially mitigated
   downstream by the circuit breaker's `net ≤ 0` rule, item 6.)

5. **[P0/TEST] The attributor is entirely untested and entirely unwired.**
   `MultiHorizonAttributor.attribute` has **no callers** (grep) and `tests/forensics/` has no
   `test_multi_horizon_attribution.py` — the file `tests/forensics/test_per_mechanism_attribution.py`
   the architecture doc promises (`three_layer_architecture.md:2948`) does not exist. So the
   conservation, causality, and bucketing defects above are unguarded; nothing would catch a
   regression, and nothing currently consumes the (wrong) output.

6. **[P1/DESIGN] The real quarantine auto-trigger bypasses `QuarantineTriggerEvidence`
   entirely.** The wired path is `cost_circuit_breaker.apply_cost_circuit_breaker` →
   `lifecycle.quarantine(reason)` with **no `structured_evidence`** (`cost_circuit_breaker.py:189`;
   protocol `_Quarantinable` at `:77-84` has no evidence parameter). The ledger records only
   `{"reason": "cost-circuit-breaker: …"}` (verified `test_cost_circuit_breaker.py:166-168`).
   The skill's documented loop (DecayDetector → `QuarantineTriggerEvidence` → quarantine) is
   not the loop that runs; the rich forensic schema is never populated by the auto-trigger
   (Inv-13 provenance gap).

7. **[P1/BUG] No expected-vs-realized comparison exists anywhere in the layer.** Every metric
   is realized-only. `DecaySignal.expected` is *historical realized* (`hist_mean`), not a
   backtest/model prediction (`decay_detector.py:174-176`, `analyzer.py:66-74`).
   `pct_edge_covers_cost` hardcodes `edge > 2×cost` (`decay_detector.py:86`) instead of reading
   the alpha's disclosed `cost_arithmetic` / `margin_ratio` (Inv-12 bar is 1.5×). The skill's
   §1 ("Compare: Expected vs Realized" — slippage residual, hit-rate residual, alpha erosion),
   which it calls *the primary decay signal*, is not implemented.

8. **[P1/BUG] Mechanism-axis conservation leaks.** Strategies with no snapshot or an empty
   breakdown are silently `continue`d (`multi_horizon_attribution.py:179-180`), so
   `Σ(mechanism buckets) ≠ total PnL`. SIGNAL-layer alphas — which *do* carry
   `Signal.trend_mechanism` but have no `CrossSectionalSnapshot` — get **zero** mechanism
   attribution. The horizon axis conserves (item is axis-specific).

9. **[P1/LIM] Even the existing automate loop is not invoked in production.**
   `reconcile_session` (`session_reconcile.py:55`) is shipped and unit-tested but has no
   live/paper call-site (grep; `close_the_loop.md:162` lists it as a TODO). So today no LIVE
   alpha is auto-quarantined by anything running.

10. **[P1/MODELING] Holding-period bucketing ignores realized holding period and
    `expected_half_life_seconds`.** The horizon axis is a static `strategy_id → horizon_seconds`
    label from the constructor map (`multi_horizon_attribution.py:155`), not a realized
    holding-period bucket measured against the alpha's own half-life (the use the glossary
    promises). Realized holding period is not computed and is not cleanly derivable
    (`TradeRecord` is a per-fill differential; `signal→fill` is latency, not holding period).

11. **[P1/MODELING] Dual, unreconciled cost notions.** `cost_survival` flags `BLEED` on
    `net = realized_pnl − fees ≤ 0` (`cost_survival.py:104,70-73`) but computes
    `realized_margin_ratio = mean_edge_bps / mean_cost_bps` from **gross** edge and the separate
    `cost_bps` field (`cost_survival.py:105-109`). Whether `cost_bps` and `fees` denote the same
    economic cost is never asserted; the "apples-to-apples" guarantee (dimension B) is unproven.

12. **[P1/BUG] Signed-quantity inconsistency between modules.** The detector requires
    `filled_quantity > 0` and multiplies it directly (`decay_detector.py:67,146`); the
    attributor takes `abs(filled_quantity)` (`multi_horizon_attribution.py:252`). If a sell is
    ever journalled with a negative quantity, the detector silently drops it from all edge
    statistics (notional ≤ 0 → edge 0 / skipped) while the attributor counts it.

13. **[P1/TEST] The Inv-11 fail-safe-with-evidence path is untested.** No test asserts that a
    *spurious* `QuarantineTriggerEvidence` still commits the demotion while logging a WARNING
    (grep over `tests/alpha/test_lifecycle.py`, `test_registry.py`). The validator's "flag"
    semantics are tested (`test_promotion_evidence.py:480-511`); the lifecycle guarantee that
    those flags never block is not.

14. **[P2/DOC] The architecture doc massively overstates the attributor.** §6.10 and §14.3
    say `multi_horizon_attribution.py` produces gross/net alpha, TC drag, factor bleed, timing
    slippage, realized-vs-expected **IC** per regime/horizon, and parity-hash deltas
    (`three_layer_architecture.md:826-835,1591-1602`), and Inv-4 is mapped to "per-alpha
    rolling-30d realized IC" (`:1907`). The code produces only PnL/fees/count buckets and shares.
    The SKILL.md is honest about this ("design targets"); the architecture doc is not.

15. **[GREEN] What is sound.** `QuarantineTriggerEvidence` fields and `GateThresholds`
    defaults match the skill exactly (`promotion_evidence.py:298-321,410-422`).
    `validate_quarantine_trigger` only flags, never blocks (`:659-701`), and `lifecycle.quarantine`
    always commits the transition after logging warnings (`lifecycle.py:418-437`) — Inv-11 holds
    in code. The attributor and detector take no wall-clock reads, sort all output keys, and read
    no promotion ledger, so the per-tick path is not perturbed (Inv-5). `fill_attribution.py`'s
    largest-remainder allocation is conservation-correct and deterministic (`:159-189`).

---

## 2. Forensic-metric inventory

| Metric | Formula (as coded) | Threshold / trigger | Source |
|--------|--------------------|---------------------|--------|
| Horizon PnL bucket | `Σ realized_pnl` per `(strategy_id, horizon)`; horizon from a static map | — (reporting) | `multi_horizon_attribution.py:155-208` |
| Mechanism PnL share | `total_strategy_pnl × (gross_share_m / Σ gross_share)` from latest snapshot | — (reporting) | `:174-194` |
| Regime PnL bucket | `Σ realized_pnl` per `(strategy_id, argmax current_state(symbol))` | — (reporting) | `:168-172, 229-241` |
| `mean_edge_bps` | `mean(realized_pnl / (fill_price·qty) × 1e4)` — **gross of fees** | — | `decay_detector.py:65-79` |
| `mean_cost_bps` | `mean(cost_bps)` | — | `decay_detector.py:75-77` |
| `pct_edge_covers_cost` | `% trades with edge > 2 × cost` | fixed **2×** (not the alpha's 1.5× `margin_ratio`) | `decay_detector.py:85-87` |
| `rolling_50 / 200_mean_edge` | mean of last 50 / 200 gross edges | — | `decay_detector.py:107-111` |
| Edge-decay z | `(hist_mean − recent_mean) / (hist_stdev + 1e-9)` | **z > 2.0**, n ≥ 100, recent = 50 | `decay_detector.py:141-184` |
| Realized margin (survival) | `mean_edge_bps / mean_cost_bps` (gross/cost_bps) | `< cover` (1.0) → trip; `< survival` (1.5) → WATCH | `cost_survival.py:105-109`, `cost_circuit_breaker.py:135-145` |
| Net (survival) | `Σ realized_pnl − Σ fees` | `net ≤ 0` over ≥ `min_fills` → QUARANTINE | `cost_survival.py:104`, `cost_circuit_breaker.py:125-129` |
| Edge haircut factor | `clamp(realized_mean / disclosed, 0, 1)` | gate uses LCB variant | `edge_calibration.py:107` |
| Edge LCB factor | `clamp((mean − z·std/√n) / disclosed, 0, 1)` | `z = 1.0`, `min_fills = 30` | `edge_calibration.py:100,108` |
| Quarantine trigger (schema) | per-field comparisons; OR of 5 conditions | 10 neg-α days / −15pp hit / 0.3 PnL-compress / 2 micro / 3 crowding | `promotion_evidence.py:659-701` |

**Read this table as the gap map:** every "expected" column the skill specifies (expected
slippage, expected hit rate, backtest IC) is absent; every threshold that exists is either a
self-referential drift bar or a hardcoded constant.

---

## 3. Attribution audit (highest priority)

### 3.1 Conservation (Σ buckets = total)

Plain math of what the code computes:

- **Horizon axis.** Each strategy maps to exactly one `horizon` via
  `horizon_by_strategy.get(sid, -1)` (`multi_horizon_attribution.py:155`), and every trade adds
  its `realized_pnl` to that single bucket (`:160-164`). Therefore
  `Σ_h HorizonBucket.realized_pnl = Σ_trades realized_pnl = total`. **Conserved.** Caveat: an
  unmapped strategy silently collapses into a shared `horizon = −1` bucket (`:119-122,155`);
  the value still sums but the label is a lossy sentinel the caller must detect.

- **Mechanism axis.** Per strategy with a non-empty snapshot,
  `share_m = breakdown_m / Σ breakdown` (`:181-188`) so `Σ_m share_m = 1` and
  `Σ_m realized_pnl_share = total_pnl_sid` (`:190-193`). Per-strategy conserved. **But across
  strategies it leaks:** any strategy whose snapshot is `None` or whose `mechanism_breakdown` is
  empty is skipped (`:179-180`), so `Σ_{sid,m} MechanismBucket ≠ Σ_trades realized_pnl`. There
  is no residual/unattributed bucket to absorb the difference. **[P1/BUG]**

- **Cross-axis.** The three axes are independent partitions of the same `total`; there is no
  attempt (and no field) to reconcile mechanism × regime × horizon jointly, so a per-cell
  double-count cannot occur — but also no joint decomposition exists (the doc's promise at
  `three_layer_architecture.md:1594-1598`). **[DOC]**

### 3.2 Mechanism bucketing — provenance vs re-inference

The mission's falsifiable test: *"attribution buckets by mechanism re-inferred from features,
so a KYLE_INFO alpha's PnL can land in the INVENTORY bucket."* **Confirmed true.**

- The only mechanism input is `intent_snapshots: Mapping[str, CrossSectionalSnapshot]`
  (`:133,137`), and `CrossSectionalSnapshot.mechanism_breakdown` is the **realised gross-exposure
  share** post-optimization (`cross_sectional_tracker.py:122-151`), not a PnL attribution.
- `Signal.trend_mechanism` — the machine-readable Inv-1 claim — is **never read** by the
  attributor. It cannot be: `TradeRecord` has no `trend_mechanism` / `expected_half_life` field
  (`trade_journal.py:22-50`; grep confirms no matches). So the lineage the skill's data-source
  table promises ("`Signal.trend_mechanism` + `SizedPositionIntent.mechanism_breakdown`") is
  broken at the trade-journal boundary; the attributor substitutes gross exposure for causal
  mechanism. **[P0/MODELING]** (modeling substitution forced by **[BUG]** missing provenance on
  `TradeRecord`).
- Two further modeling assumptions ride on this: (a) PnL is proportional to gross share across
  mechanisms (false whenever per-mechanism return-on-gross differs); (b) a single *latest*
  snapshot characterises the whole PnL window (false whenever the mechanism mix drifted — the
  exact thing forensics exists to detect). **[P0/MODELING]**
- SIGNAL-layer alphas produce no `SizedPositionIntent`/snapshot, so they receive **no** mechanism
  bucket at all despite carrying the provenance — a structural blind spot. **[P1/BUG]**

### 3.3 Regime bucketing — causality

`_regime_for(symbol)` (`:229-241`) calls `current_state(symbol)`, documented as returning
"cached posteriors for a symbol **without updating**" (`regime_engine.py:91-98,559-561`) — i.e.
the most recent posterior, with no timestamp parameter and no event lookup. Because `attribute`
iterates a whole batch of historical trades (`:153-172`), **all** trades for a symbol get the
**same** regime label (whatever the engine holds when the audit runs). This is:

- **Non-causal** — not the regime at entry (Inv-6); contradicts the attributor's own docstring
  ("dominant regime state at the fill timestamp", `:10-13`) and the skill table ("argmax at FILL
  time"). **[P0/BUG]**
- **Non-deterministic given fills** — depends on mutable live-engine state, so re-running the
  audit later (after more quotes) yields different regime buckets (see §7). **[P0/BUG]**

The correct source per the skill's data-source table is recorded `RegimeState` events keyed by
timestamp ≤ entry, not a live `RegimeEngine` handle. The argmax convention itself (`:238-241`)
is fine; the *time* it is sampled at is the bug.

### 3.4 Holding-period bucketing vs `expected_half_life_seconds`

The horizon axis is a configured label, not a measured holding period, and is never compared to
the alpha's `expected_half_life_seconds` (the glossary's stated use: "bucket holding-period
realized PnL by the alpha's *own* expected timescale"). Realized holding period is not computed;
the data model does not support it cleanly (`realized_pnl` is a per-fill differential, and
`signal_timestamp_ns → fill_timestamp_ns` is signal-to-fill latency, not entry-to-exit holding).
**[P1/MODELING]** — surfacing half-life drift (the skill's G16 decay check) is not possible from
the current `TradeRecord` shape.

---

## 4. Expected-vs-realized (TCA) audit

1. **Expected side is absent.** No metric is sourced from the alpha's disclosed
   `cost_arithmetic` (`expected_edge_bps`, `half_spread_bps`, `expected_impact_bps`,
   `margin_ratio`) or from a backtest baseline. `pct_edge_covers_cost` uses a literal `2×`
   (`decay_detector.py:86`); the platform's economic bar is `margin_ratio ≥ 1.5` (Inv-12,
   glossary "cost arithmetic"). `DecaySignal.expected` is `hist_mean` — *realized* history, not a
   prediction (`decay_detector.py:174-176`). So the skill's §1 comparison (residual = realized −
   expected) does not exist. **[P1/BUG]**
   - `edge_calibration.py` is the **one** place a disclosed value enters: `haircut/lcb = realized
     / disclosed` (`:107-108`). This is realized-vs-disclosed *shrinkage for the next run's gate*,
     not a forensic residual or significance test, and the disclosed edge is plumbed only through
     `disclosed_edges_from_registry` best-effort (`session_reconcile.py:106-138`).

2. **Statistical meaningfulness.** The TCA reports point estimates (means, p95, percentages)
   with **no** variance, confidence interval, or sample-size gate on the headline figures
   (`decay_detector.py:40-125`). The decay test does use n but mis-scales it (§5.1). The skill's
   trend tests (5-day OLS slope, p < 0.05) and KS tests are not implemented. `edge_calibration`
   is the only module that computes a confidence bound (LCB `mean − z·std/√n`,
   `edge_calibration.py:100`), and it correctly gates on the lower bound — the one statistically
   defensible construct in the layer. **[P1/MODELING]**

3. **Sign / units consistency.** `realized_pnl` is mid-to-mid, gross of fees, with spread booked
   into `fees` (`trade_journal.py:29-33,52-62`). `mean_edge_bps` is therefore **gross**, but is
   presented next to `mean_cost_bps` and an "edge covers 2× cost" line in the report
   (`backtest_report.py:531-534`) as if it were the net economic edge. A consumer reading
   `mean_edge_bps` as net realized edge overstates economics by the fee component. `cost_survival`
   then mixes a net rule (`net = gross − fees ≤ 0`) with a gross margin
   (`mean_edge_bps / mean_cost_bps`) in the same verdict (`cost_survival.py:70-82,104-109`)
   without asserting `cost_bps ≈ fees/notensional·1e4`. **[P1/MODELING]** (reconcile the two cost
   representations and label gross vs net).

---

## 5. Decay detection audit (Inv-4)

### 5.1 What triggers a flag, and is it calibrated?

`detect_edge_decay` (`decay_detector.py:127-184`): requires ≥ 100 trades, takes the last 50 as
"recent" and the rest as "historical", and flags when
`z = (hist_mean − recent_mean)/(hist_stdev + 1e-9) > 2.0`.

- **The denominator is wrong for the question asked.** To test "is the recent-50 *mean* below
  history" the denominator should be the standard error of that mean (`σ/√50`) or a Welch t
  pooled SE — not the raw per-trade `σ`. As written the statistic is ~7× too small. **[P0/BUG].**
  Worked example: edge halves from 5 → 2.5 bps with per-trade σ = 20 bps → z = 0.125 ≪ 2.0; a
  50% decay is invisible. The passing test only covers a total 5 → 0 collapse over a 150/50
  split (`test_tca.py:168-195`), which masks the under-power.
- **Threshold `2.0` is arbitrary and one-sided**, with no documented derivation and no p-value
  (`decay_detector.py:168`). No trend/slope test, no time-based window (count-based only), and no
  per-mechanism or per-regime stratification — the detector is strategy-wide on **gross** edge,
  i.e. it does precisely the cross-mechanism smearing the attributor was meant to prevent.
  **[P1/MODELING].**

### 5.2 False-negative bias (the costly error under Inv-4)

Two independent paths let a genuinely dead edge stay undetected:

- **Cost/crowding blindness** (§1.4): gross edge can hold while net goes negative → z ≈ 0. The
  skill's litmus for crowding ("signal quality pre-cost stable but post-execution alpha erodes")
  is structurally invisible to this detector. **[P0/BUG]** (mitigated only because
  `cost_circuit_breaker` adds an independent `net ≤ 0` rule, `:125-129`).
- **Under-power** (§5.1): sub-catastrophic decay never crosses the gate. **[P0/BUG]**

False-positive cost is bounded by the ≥ 100-trade / 50-recent design and the `2.0` gate (it
rarely fires at all), so the bias is firmly toward silence — the wrong direction for Inv-4.

### 5.3 Crowding / latency / microstructure signals

None of the skill's §3 structural-change detectors exist in code: no spread-regime shift, no
quote-frequency KS test, no venue-Herfindahl, no latency-stratified PnL, no adverse-selection or
quote-anticipation scorecard. `QuarantineTriggerEvidence` has fields for
`microstructure_metrics_breached` and `crowding_symptoms` (`promotion_evidence.py:314-319`), but
**nothing computes them** — they would have to be filled by hand. **[P1/LIM].** The only
"decay" signals that exist are gross-edge drift (`detect_edge_decay`) and realized-vs-cost
survival (`cost_survival`).

---

## 6. Quarantine trigger audit (fail-safe + wiring)

### 6.1 Schema vs skill thresholds — aligned

`QuarantineTriggerEvidence` (`promotion_evidence.py:298-321`) and the `GateThresholds` quarantine
block (`:410-422`) match the skill's "Strategy Quarantine" table and glossary one-for-one: 10
net-α-negative days, hit-rate ≤ −15 pp, PnL compression ≤ 0.3 over 5 d, ≥ 2 microstructure
breaches, ≥ 3 crowding symptoms. Verified by `test_promotion_evidence.py:480-511,815-821`.
**[GREEN].**

### 6.2 The validator never blocks — confirmed

`validate_quarantine_trigger` returns errors **only** when *no* documented threshold crossed
(`:676-701`); it is a consistency/spurious-trigger flag. `AlphaLifecycle.quarantine` runs it,
logs any warnings at WARNING, and **always** calls `self._sm.transition(QUARANTINED, …)` with no
early-return on warnings (`lifecycle.py:416-437`). `AlphaRegistry.quarantine` forwards
`structured_evidence` faithfully (`registry.py:413-442`). Inv-11 holds in code. **[GREEN].**
Caveat: "always commits" means *the validator* never blocks; the SM still raises
`IllegalTransition` if the alpha is not LIVE (tested `test_lifecycle.py:593-604`) — correct
fail-safe (you cannot quarantine what is not live), and the breaker guards it with `is_live`
(`cost_circuit_breaker.py:187`).

### 6.3 Does forensics actually call `quarantine`? — yes, but via a different model that
discards the evidence

End-to-end trace:

```
session_reconcile.reconcile_session            (session_reconcile.py:55)   ← NO production caller
  └ evaluate_cost_circuit_breaker(records)      (cost_circuit_breaker.py:87)
       ├ per_alpha_cost_survival(...)           (cost_survival.py:85)  → DecayDetector.analyze_fills
       └ DecayDetector.detect_edge_decay(...)   (cost_circuit_breaker.py:116)
  └ apply_cost_circuit_breaker(decisions, lifecycles)   (:168)
       └ lifecycle.quarantine(reason)           (:189)   ← reason string only, NO structured_evidence
```

Findings:

- **The wired trigger is the cost circuit breaker, not the documented `DecayDetector →
  QuarantineTriggerEvidence` path.** Its trip rules are `net ≤ 0`, `decay z > 2`, or realized
  margin `< cover` (`:120-150`) — a different, simpler model than the five-field schema. The
  skill's claim that "there is no production forensics → lifecycle auto-trigger wired today"
  (post-trade-forensics SKILL §4) is **out of date**. **[DOC].**
- **The evidence schema is never populated by the auto-trigger.** `apply_cost_circuit_breaker`
  passes only a `reason` string; `_Quarantinable` (`:77-84`) has no evidence parameter. So the
  ledger entry for an auto-quarantine carries `{"reason": "cost-circuit-breaker: …"}` and **no**
  `QuarantineTriggerEvidence` (verified `test_cost_circuit_breaker.py:166-168`). The breaker has
  the numbers (`CircuitBreakerDecision.net/mean_edge_bps/mean_cost_bps/decay_z`, `:62-74`) and
  throws them into a string. Inv-13 provenance is weaker than the schema was built for.
  **[P1/DESIGN].**
- **Nothing invokes the loop in production.** `reconcile_session` has no live/paper call-site
  (grep; `close_the_loop.md:162` TODO). The capability is shipped and tested but dormant.
  **[P1/LIM].**

---

## 7. Determinism & provenance audit

- **Horizon & mechanism axes are deterministic** given fixed inputs: no clock reads, output keys
  sorted for stable iteration (`multi_horizon_attribution.py:176,198,211`;
  module docstring `:22-25`).
- **Regime axis is not deterministic given (fills + provenance).** It reads
  `regime_engine.current_state` — mutable in-memory live state (`:232`) — so the same fills audited
  at two different engine states produce different regime buckets. This is the determinism face of
  the §3.3 causality bug, and it means "two audits agree" fails for the regime axis. **[P0/BUG].**
- **No ledger reads, no per-tick perturbation.** The attributor and `analyzer`/`decay_detector`
  take no bus subscriptions and read no promotion ledger; `cost_circuit_breaker.apply` and
  `edge_calibration` writes are documented and structured as **session/epoch-boundary** actions
  that become fixed inputs at the next run (`cost_circuit_breaker.py:18-22`,
  `edge_calibration.py:22-26`, `session_reconcile.py:11-15`). Inv-5 on the per-tick path is
  respected. **[GREEN].**
- **Forensic-purity smell.** Coupling the attributor to a live `RegimeEngine` handle (rather than
  to recorded `RegimeState` events) is the root cause of both the causality and determinism
  defects; the skill's data-source table already prescribes the event-sourced input. **[P1/DESIGN].**

---

## 8. Test gap matrix

`tests/forensics/` currently holds **only**: `test_tca.py`, `test_cost_survival.py`,
`test_edge_calibration.py`, `test_session_reconcile.py`, `test_cost_circuit_breaker.py`. The
coverage is real for the close-the-loop modules and thin-to-absent for the attribution/decay
core.

| Invariant / behaviour | Status | Evidence |
|-----------------------|--------|----------|
| Attribution conservation (Σ buckets = total) | **MISSING** | no `test_multi_horizon_attribution.py`; promised `test_per_mechanism_attribution.py` absent (`three_layer_architecture.md:2948`) |
| Causal regime bucketing (regime at entry) | **MISSING** | attributor untested; bug live |
| Mechanism bucketing reads provenance | **MISSING** | untested; and provenance not on `TradeRecord` |
| Decay sensitivity to realistic (partial) decay | **PARTIAL** | only catastrophic 5→0 case (`test_tca.py:168`); under-power untested |
| Decay blind-spot to cost/crowding | **MISSING** | no test feeds gross-flat/net-negative fills |
| Expected-vs-realized residuals | **MISSING** | feature absent |
| Quarantine trigger thresholds (each field) | **COVERED** | `test_promotion_evidence.py:480-511` |
| Quarantine validator never blocks (pure) | **COVERED** | `:507-511` |
| Inv-11 fail-safe *with spurious structured evidence* commits + WARNING | **MISSING** | grep: no test in `test_lifecycle.py`/`test_registry.py` |
| Auto-trigger applies & writes ledger | **COVERED** | `test_cost_circuit_breaker.py:146-168` |
| Auto-trigger records `QuarantineTriggerEvidence` | **N/A (not implemented)** | breaker passes reason only |
| Cost-survival verdicts on cached APP/2026-03-26 fills | **COVERED** | `test_cost_survival.py:67-117` |
| Edge calibration LCB / parity-preserving haircut | **COVERED** | `test_edge_calibration.py:44-90` |
| Forensic determinism (two audits agree) | **MISSING** | regime axis non-deterministic; untested |

---

## 9. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ~1–2 days · **L** > 2 days. Each item: component · `file:line` ·
one-line fix · expected impact.

### P0

1. **Regime bucketing causality.** `multi_horizon_attribution.py:229-241` · **M** · attribute
   regime from recorded `RegimeState` events with `timestamp_ns ≤ entry` (carry entry-time regime
   on `TradeRecord`, or pass a per-(symbol, ts) regime timeline), not `current_state`. *Impact:*
   regime axis becomes causal and deterministic — unblocks every regime-stratified decay decision.
2. **Decay statistic power.** `decay_detector.py:166` · **S** · divide the mean shift by the
   standard error of the recent window (`stdev/√len(recent)`), or switch to a Welch two-sample
   test with a stated α. *Impact:* detector can fire on realistic partial decay (Inv-4).
3. **Net-of-cost decay.** `decay_detector.py:69,148` · **S** · compute edge from `net_pnl`
   (`trade_journal.py:52-62`) or add a parallel net-edge series. *Impact:* crowding/cost decay
   becomes detectable by the named detector, not only by the breaker's `net ≤ 0` rule.
4. **Mechanism provenance on the record.** `trade_journal.py:22-50` + `:174-194` · **M** · add
   `trend_mechanism` / `expected_half_life_seconds` to `TradeRecord` (populated from the causing
   `Signal`) and bucket per-trade by it. *Impact:* Inv-1 attribution becomes real instead of a
   gross-exposure proxy; fixes KYLE→INVENTORY mis-bucketing and SIGNAL-alpha blind spot.
5. **Attribution conservation + golden tests.** new `tests/forensics/test_multi_horizon_attribution.py`
   · **M** · property test `Σ buckets == total` on each axis (with a residual bucket for
   un-attributed PnL at `:179-180`) + a regime-causality golden case. *Impact:* guards the P0
   fixes; satisfies the promised-but-missing test.

### P1

6. **Wire the auto-trigger to record evidence.** `cost_circuit_breaker.py:77-84,189` · **S** ·
   widen `_Quarantinable.quarantine` to accept `structured_evidence` and have the breaker build a
   `QuarantineTriggerEvidence` from `CircuitBreakerDecision`. *Impact:* Inv-13 provenance; the
   ledger captures *why*, replay-evidence works.
7. **Invoke `reconcile_session` from a real boundary job.** `session_reconcile.py:55` +
   paper/live EOD entrypoint · **M** · call it from the session-end hook with the rolling window.
   *Impact:* the automate loop actually demotes dead LIVE alphas.
8. **Expected-vs-realized residuals.** `decay_detector.py` / new module · **L** · source expected
   slippage/hit-rate/edge from `cost_arithmetic` + backtest baseline; emit residuals with CIs.
   *Impact:* implements the skill's primary decay signal.
9. **Reconcile cost notions.** `cost_survival.py:104-109` · **S** · assert/derive a single cost
   basis and label gross vs net in the report (`backtest_report.py:531-534`). *Impact:* apples-to-
   apples TCA.
10. **Signed-quantity contract.** `decay_detector.py:67,146` vs `:252` · **S** · use
    `abs(filled_quantity)` consistently (or document qty is unsigned magnitude). *Impact:* sells
    no longer silently dropped from edge stats.
11. **Inv-11 fail-safe-with-evidence test.** `tests/alpha/test_lifecycle.py` · **S** · assert a
    spurious `QuarantineTriggerEvidence` still commits and logs WARNING (caplog). *Impact:* locks
    the safety guarantee.
12. **Mechanism-axis leakage.** `multi_horizon_attribution.py:179-180` · **S** · emit an
    `UNATTRIBUTED` bucket for strategies without a snapshot. *Impact:* conservation across axis.

### P2

13. **Holding-period / half-life axis.** `multi_horizon_attribution.py:155` + `TradeRecord` ·
    **L** · once round-trip linkage exists, bucket realized holding period against
    `expected_half_life_seconds`. *Impact:* surfaces G16 half-life drift.
14. **Crowding / microstructure detectors.** new module · **L** · implement the §3 scorecard that
    fills `microstructure_metrics_breached` / `crowding_symptoms`. *Impact:* the schema fields stop
    being inert.
15. **Doc reconciliation.** `three_layer_architecture.md:826-835,1591-1602,1907` · **S** ·
    downgrade IC / TC-drag / factor-bleed / parity-hash claims to "design target" to match SKILL.md
    and code. *Impact:* the architecture doc stops overstating the layer.

---

## 10. Appendix — open questions needing data runs

1. **Empirical detector power.** On cached APP/2026-03-26 fills (fixture exists at
   `test_cost_survival.py:_app_2026_03_26_fills`), inject synthetic decays of −25 %/−50 %/−75 % into
   the recent-50 window and measure the detection rate under the current `σ` denominator vs an
   `σ/√n` denominator. Quantifies the P0-2 severity.
2. **Gross-vs-net divergence.** For the same fills, compute per-alpha gross-edge vs net-edge
   trajectories to size how many real (net-negative) decays the gross detector misses (P0-3 / P0-4).
3. **`cost_bps` vs `fees` identity.** Reconcile, on real fills, whether
   `cost_bps ≈ (fees / notional)·1e4`; if not, what each represents — required before the cost
   notions can be merged (P1-9).
4. **Per-mechanism realized-vs-disclosed (proposed offline methodology, no code change):** group
   the APP/2026-03-26 fills by the causing `Signal.trend_mechanism` (requires the P0-4 provenance
   to be exact; until then approximate via the intent `mechanism_breakdown` per boundary),
   compute realized edge per mechanism with an LCB (`edge_calibration` style), and compare to each
   alpha's disclosed `edge_estimate_bps`. The expected output is a per-mechanism haircut table that
   would feed both the decay flag and the gate — and would have caught the audit's central finding
   (an alpha clearing G12 on disclosed edge while bleeding fees, `cost_survival.py:5-10`) per
   mechanism rather than per strategy.
5. **Regime-timeline availability.** Confirm whether recorded `RegimeState` events (or a
   per-(symbol, ts) regime log) are durably available to the offline attributor; this gates the
   P0-1 fix.
