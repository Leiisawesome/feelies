# Regime Stack Audit — Second Pass

**Date:** 2026-06-13
**Scope:** Same stack as the 2026-06-11 first pass, re-examined with two new
inputs: (a) the up-to-date remediation state on `main`, and (b) the **APP
regression** caused by the first pass's own economic recommendations.
**Mode:** Read-only analysis + a reproducible measurement on the repo's
committed synthetic fixture (no external data). No production code changed.

> Read alongside `docs/audits/regime_audit_2026-06-11.md` (first pass +
> remediation table). This pass does not re-litigate the correctness
> findings that held up; it reckons with the part of the first pass that
> was **wrong**, and extracts the structural lesson.

---

## 1. Executive summary (≤12 bullets)

> **Update (post-data, see §2.5):** the bullets below were written *before* the
> APP cache was measured. The harness then **refuted** the §2 prediction that
> APP is degenerate — APP is well-separated (`d=1.478`) and its posteriors are
> peaked (entropy > 0.95 on only 0.3% of ticks). The regression on APP was
> therefore **not** "gating on noise" (that applies to tight/degenerate names
> like the fixture) but **gating the alpha out of its high-volatility
> opportunity set via the off-condition + latch**. Read §2.5 as the corrected,
> data-backed conclusion; bullets 2–3 and 6 below stand as the original
> hypothesis and the degenerate-case analysis.

1. **The first pass made one decisive error, and it was methodological, not arithmetic.** It tightened gate conditioning on the regime posterior (P1-6 `P(vol_breakout)<0.30`, P2-2 `entropy>0.95`, P1-5, P1-8) while *simultaneously* concluding that the posterior is economically weak (first pass §3.2 "spread-only is not a sufficient statistic", §3.3 "weak emission separation → diffuse posteriors"). You cannot condition harder on a signal you have just judged untrustworthy. The APP backtest is the proof: signals 4,833 → 414 (−91%), Net P&L +$1,804 → −$1,889.
2. **The regression is not a fluke — it is the predicted consequence of §3.3, now measured.** On the repo's committed `synth_5min_aapl.jsonl` (a tight, stable ~0.55 bps spread), calibration collapses the three emissions to `μ = −9.799 / −9.798 / −9.798`, `σ = 0.01` (the floor), pairwise separation `d ≈ 0.02–0.07`. The posterior is uniform noise: **`entropy > 0.95` on 100% of ticks**, `P(vol_breakout)` mean `0.275` (≥0.30 on 28%), `P(normal)` never exceeds `0.5`. (Appendix A; `services/regime_engine.py:368-386,188`.)
3. **Discriminative power is a pure function of intraday spread dispersion.** Re-running the same engine on a *variable*-spread control (same name, spreads drawn 1–5¢) recovers separation to `d01=0.98, d12=2.27`, entropy mean `0.26` (0% > 0.95), `P(normal)>0.5` on 39% of ticks. The engine is informative exactly when spreads disperse and degenerate to noise when they don't — and **nothing in the gate, sizer, or risk path knows which regime of *discriminability* it is in.**
4. **"vol_breakout" is not a volatility state — it is, by construction, the widest third of *this symbol's own* spread distribution.** Quantile calibration (`_fit_quantile_emissions_from_sorted`, `regime_engine.py:368-386`) partitions each symbol's spreads into equal-mass terciles. So `P(vol_breakout) < 0.30` structurally excludes ~a third of perfectly tradeable time for a tight name; it is not an adverse-selection filter. This is why filtering on it removed *profitable* trades.
5. **The kept correctness/safety fixes are sound and remain the right call** — they are orthogonal to entry selection (verified: #124 reproduces #122 bit-for-bit). P0-1, P1-1, P1-2, P2-3, P2-4 stay.
6. **But P0-1 has a newly-exposed blind spot: `calibrated` is binary, and "calibrated" ≠ "discriminative".** The synth fixture calibrates `True` yet produces pure noise (bullet 2). P0-1 fails the gate safe to OFF only when emissions were never fit — not when they were fit but are degenerate. The genuinely correct guard is *continuous discriminability*, which generalizes P0-1.
7. **New P1 (R-1): publish a discriminability statistic on `RegimeState` and fail gates safe to OFF below a floor.** Min pairwise separation `d` (or `1 − H/H_max`) is already computable at calibration time; surface it and let the gate refuse to act on noise — the same fail-safe shape as P0-1 but covering the degenerate-calibration case the regression actually hit.
8. **New P1 (R-2): no economic gate/threshold change merges without a conditional-forward-return delta in the PR.** This is the process gate that would have stopped the regression. The first pass's own Appendix §10 listed exactly these runs; the implementation skipped them. Spec in §5; I can build the harness.
9. **The deferred P2-1 (second observation dimension) is now the highest-value research item, not a "nice to have".** It is the only way `vol_breakout` becomes *volatility* (or toxicity) rather than a spread tercile. Every economic gate recommendation is blocked on it or on R-1/R-2.
10. **`enforce_min_pairwise_emission_separation` defaulting to `False` is now a real (not cosmetic) gap.** On the synth fixture, calibration "succeeded" at `d≈0.02` and ran on noise; flipping it `True` instead retains placeholder emissions that pin to `vol_breakout` (first pass §3.3). *Neither* setting is safe — which is precisely why the guard belongs at the consumer/gate layer (R-1), not only at calibration.
11. **Re-opened items (P1-5/P1-6/P1-8/P2-2) must not be re-attempted until R-1 + R-2 exist**, and when they are, thresholds must be data-derived and almost certainly *symbol/cohort-relative* (e.g. percentile of that symbol's realized `P(vol_breakout)`), not absolute constants like `0.30`.
12. **Net for the trading book today: correct and unchanged from #122.** The remaining audit value is in (a) the discriminability guard, (b) the validation harness, (c) the richer regime feature — in that order.

---

## 2. What the regression actually proved (empirical)

Measured this pass on the committed fixture (Appendix A is the exact, rerunnable script):

| Metric | Constant-spread `synth_5min_aapl` | Variable-spread control (same code) |
|---|---|---|
| Calibrated emissions `μ` | −9.799 / −9.798 / −9.798 | −9.798 / −9.457 / −8.455 |
| `σ` | 0.010 / 0.010 / 0.010 (floor) | 0.010 / 0.347 / 0.274 |
| Min pairwise separation `d` | **0.024** | **0.98** |
| Posterior entropy (mean / max=ln3) | 1.061 / 1.099 | 0.261 |
| Ticks with `entropy > 0.95` | **100%** | 0% |
| `P(vol_breakout)` mean | 0.275 | — |
| Ticks `P(vol_breakout) ≥ 0.30` | 28% | — |
| Ticks `P(normal) > 0.5` | **0%** | 39% |

Mechanism chain (all citations `services/regime_engine.py`):

- `calibrate` splits the symbol's `log(spread/mid)` into equal-mass terciles (`:368-386`); for a tight, stable name the three terciles are statistically indistinguishable, so the fitted means differ in the 3rd–4th decimal and `σ` pins to `_MIN_SIGMA = 0.01` (`:188`).
- Near-identical Gaussians → near-uniform per-tick likelihood (`_emission_likelihood_for_symbol`, `:803-809`) → the posterior is driven by the transition matrix's stationary distribution, not by observation → entropy sits at ≈ `ln 3`.
- `P2-2`'s `entropy > 0.95` is therefore satisfied on ~every tick (forcing the gate OFF), and `P1-6`'s `P(vol_breakout) < 0.30` excludes the ~28% of ticks where uniform noise puts ≥0.30 on that tercile. On APP (a milder version of this disease) the combination cut entries 91% — and because the excluded windows were *not* economically adverse (the tercile is just "wider-but-fine spreads"), the surviving trades were net-losing.

**Falsifiable claim:** on APP 2026-06-01..05, the calibrated min-pairwise separation `d` is well below the `0.5` weak-discrimination line and the realized posterior-entropy distribution has most mass above `0.95`. R-2's harness will confirm or refute this directly; if confirmed, *no* absolute `P(state)`/`entropy` gate threshold is defensible for that symbol until the feature set is enriched (P2-1).

---

## 2.5 APP cache verification — the claim above was REFUTED (and it sharpens the diagnosis)

R-2's harness was run against the real APP 2026-06-01..05 cache (256,973 quotes). The §2 degeneracy claim does **not** hold for APP, and the corrected picture is more precise about *why* the regression happened:

| Measured on APP | Value | Implication |
|---|---|---|
| Calibrated emissions `μ` | −7.824 / −6.970 / −6.217 | Well-separated, not collapsed |
| Min pairwise separation `d` | **1.478** (all pairs > 1.4) | **Discriminative** — far above the 0.5 floor |
| Posterior entropy mean / frac > 0.95 | 0.109 / **0.3%** | Posteriors are *peaked*, not diffuse |
| Occupancy (comp/normal/vol_breakout) | 35.2% / 30.3% / 34.5% | ≈ equal terciles, as quantile calibration intends |

So **APP is not the degenerate fixture case.** Two findings replace the §2 hypothesis:

1. **The on-condition clauses are nearly inert, and the regime-isolated off-condition/latch hypothesis did NOT reproduce the drop (pending a re-run on the corrected harness).** Instantaneous regime eligibility: `P(normal)>0.5` = 30.16% → `+P(vb)<0.30` = 29.39% → `+entropy<0.95` = 29.35% (entry clauses prune ~0.8pp). I then hypothesised the harm was the off-condition knocking the hysteresis latch OFF — but the **latched ON-fraction** (regime terms isolated) measured **42.90% baseline → 41.47% candidate = 97% retained**, not a collapse. *Caveat:* that run used the step-2 harness, which had a **boundary-cadence bug** — it sampled views only inside the NBBO loop with a single global index, so bins first crossed by a Trade were missed or mis-latched, and multi-symbol latching was wrong. Those bugs were fixed afterwards (commits `a223f1d` / `6f1defd` / `82058dc`: HorizonScheduler-faithful cadence over the full event stream, per-symbol latching, hysteresis margins, first-event anchor). **The 97% must therefore be re-measured on the corrected harness** before "refuted" is final — but the on-condition prune (~0.8pp) is unaffected and already shows the entry clauses cannot be the cause.

2. **`vol_breakout` carries genuine economic content on APP — the opposite of noise.** Forward mid `mean|return|` rises monotonically with `P(vol_breakout)` decile, **12.5 → 39.0 bps**, and the top decile carries **−12.9 bps** signed drift. High `P(vol_breakout)` marks higher-volatility, negatively-drifting windows. For a directional footprint alpha those are plausibly the *highest-edge* windows — which `P1-6`/`P2-2` exiled.

**What is now ESTABLISHED vs OPEN.**

- **Established:** the harm is the **benign gate strings** — #124 reverted *only* the YAML gate strings (the kept code fixes P0-1/P1-1/P1-2 remained) and restored 4,833 ≡ #122, so every code fix is exonerated and the gate strings are the cause. APP's posterior is discriminative (`d=1.478`). The regime *terms* of the gate contribute ≤3% by both regime-isolated metrics.
- **Therefore (inference):** the mechanism is the **regime×sensor coupling in the full gate** — `P(vol_breakout)` is strongly correlated with `spread_z_30d` (the engine's observation *is* log-spread), so the new `P(vb)` clauses bite only in conjunction with the real, varying spread/vol sensors, which the regime-isolated harness neutralizes and cannot see.
- **Resolved (multi-alpha backtest, current main):** the "4,833 → 414 signals" figures are **~97% FLAT gate-close / fail-safe events, not entries.** A `configs/backtest_multialpha.yaml` APP 2026-06-01..05 run on main reports **2,049 signals = 30 long + 38 short entries + 1,981 FLAT exits** (5,480 snapshots, +3.29%, 48 fills). So the headline "signal count" regression was dominated by gate-close **churn** — which is exactly why the regime-isolated ON-*fraction* (a steady-state measure) never tracked it: FLAT-close count is driven by ON→OFF *transitions* and the warm/stale fail-safe path, not by ON-fraction. The run is **multi-alpha**, so #123 spanned all four reverted gates, not benign alone.

**Tool status (R-2): the merge-gate metric is corrected, not the latch.** "Signals emitted" is a FLAT-dominated *churn* metric and must **not** be the merge gate. The trusted economic instruments are (a) the **conditional forward-return tables by `P(state)`/entropy decile** (R-2 step 1, built) and (b) **entry-signal / fill / Net-PnL deltas** from a per-alpha backtest funnel. The regime-isolated **latched ON-fraction** (step 2) is a useful *secondary* diagnostic — it correctly showed benign's regime terms move the gate ≤3% (exonerating them) — but it is not the headline number. R-2 step 3 (full-sensor latch) is **deprioritized**: the established cause is multi-alpha gate *strings*, the regression is reverted, benign's regime terms are exonerated, and the churn-vs-activity distinction (entries/fills/PnL) is the right lens going forward.

**Consequence for R-1.** A discriminability guard (R-1) remains correct as a *safety net for the degenerate / tight / uncalibrated class* (the fixture), but on APP it would **not** fire (`d=1.478`, entropy peaked). It does not address the (already-reverted) #123 regression; it protects a different failure mode.

---

## 3. The methodological finding (why pass 1 contradicted itself)

The first pass correctly identified the regime signal as economically weak — §3.2 (1-D spread observation cannot separate volatility / inventory / information), §3.3 (separation gate `d ≥ 0.5` is a weak floor, off by default), and the headline P0-1 (uncalibrated pins to an extreme). It then recommended P1-6/P2-2/P1-5/P1-8, which **increase the book's dependence on that same weak signal.** Those two stances are mutually exclusive, and the audit's own Appendix §10 had already named the experiments needed to resolve the tension ("benign ON with vol mass — if a material tail exceeds ~0.3, P1-6 is confirmed"). The experiments were not run; the changes shipped on assumption.

Two distinct work-streams were conflated and should be permanently separated by process:

- **Correctness / safety lane** (fail-safes, causality, determinism, load-time validation): provable from the code, no market data needed. P0-1, P1-1, P1-2, P2-3, P2-4 — merged correctly.
- **Economic-conditioning lane** (entry/exit thresholds, regime gating strength): a hypothesis about returns; requires a conditional-return backtest delta *before* merge. P1-5, P1-6, P1-8, P2-2 — should never have entered on the correctness lane's evidence bar.

---

## 4. Re-examination of the kept fixes

| Fix | Still correct? | Note from this pass |
|---|---|---|
| **P0-1** calibrated fail-safe (`events.py` `calibrated`, gate disable) | Yes, but **incomplete** | Binary `calibrated` misses the degenerate-but-calibrated case (Appendix A calibrates `True`, posterior is noise). Generalize to continuous discriminability (R-1). The *shape* — refuse to gate on an untrustworthy posterior — is exactly right and is the template for R-1. |
| **P1-1** off-path `RegimeGateError` unwind | Yes | Unchanged; pure fail-safe. |
| **P1-2** load-time `P()` validation | Yes | Would have caught a *typo* class of error; the regression used valid names, so orthogonal — but correct to keep. |
| **P2-3** `pNN` regex | Yes | Trivial, correct. |
| **P2-4** calibration-lookahead doc | Yes | Documentation only. |
| **P2-6** hysteresis-band property test | Yes (rescoped) | Good that it no longer asserts the reverted vol-bound; the band check is design-agnostic. |

No regression risk was introduced by the kept fixes (confirmed empirically: #124 ≡ #122 bit-for-bit).

---

## 5. Revised, evidence-grounded backlog

| ID | Pri | Item | One-line | Status |
|---|---|---|---|---|
| **R-2** | P1 | Regime diagnostics / validation harness | `scripts/regime_diagnostics.py` (steps 1+2): separation `d`, occupancy, entropy distribution, **conditional forward returns by `P(state)`/entropy decile**, gate-clause pruning, regime-isolated **latched ON-fraction**. Merge-gate metric is **conditional returns + entry/fill/PnL deltas**, NOT total "Signals emitted" (which is ~97% FLAT-close churn, §2.5). Step 3 (full-sensor latch) deprioritized. | **Done** for its purpose; latch is a secondary diagnostic |
| **R-1** | P1 | Discriminability guard (degenerate-class net) | `HMM3StateFractional.discriminability` = calibration-time min pairwise separation `d`; published on `RegimeState.discriminability`; the gate fails `P()`/`dominant`/`entropy` safe to OFF when `d < regime_min_discriminability` (platform config, **default 0.0 = exact no-op**) — generalizes the binary P0-1, regime-reference-aware (regime-free gates unaffected). Uses *calibration-time `d`*, **not** per-tick entropy (that would re-create the reverted P2-2). Protects tight/degenerate/uncalibrated names; with the default floor it does **not** fire on APP (`d=1.478`). | **Done** (floor opt-in; APP-neutral) |
| **R-3** | P2 | Second observation dimension | `HMM3StateSpreadVol` (`hmm_3state_spread_vol`): adds short-window realized vol of the mid as a 2nd diagonal-Gaussian dimension; states ordered by increasing realized-vol mean so `vol_breakout` = high volatility, not widest spread. **Opt-in, default-off** — the default engine and all locked baselines are untouched; alphas switch only after R-2 validates conditional returns. On the synth fixture where the spread-only engine is degenerate (`d=0.024`), the 2-D engine is discriminative (`d=1.77`). | **Done** (opt-in; validation-gated) |
| **R-4** | P2 | Default `enforce_min_pairwise_emission_separation = True` + alert | Refuse silent degenerate calibration; pair with R-1. | R-1 |
| — | — | **Re-opened, BLOCKED:** P1-5, P1-6, P1-8, P2-2 | Do not re-attempt until R-1+R-2; thresholds must be data-derived and symbol/cohort-relative, and **validated on latched ON-fraction + conditional returns**, not instantaneous eligibility. | R-1, R-2 |
| — | — | Reaffirmed deferred: P1-3 (time-scaling), P1-7 (per-strategy hazard) | Unchanged. P1-3 does **not** help discriminability (separation is an emission property). | — |

---

## 6. Process recommendation (the actual fix)

Add a contributor rule, enforceable in review: **a change to any regime-gate condition string, hazard threshold, or risk/sizer scaling constant must include, in the PR body, a conditional-return backtest delta on at least one cached symbol** (signals, Net P&L, hit-rate, ON/OFF Sharpe — before vs after). Correctness/safety changes (fail-safes, validation, determinism) are exempt and merge on code evidence. This single rule would have blocked PR #123's harmful half while passing its safe half.

---

## Appendix A — reproducible probe (committed fixture, no external data)

```python
# uv run --no-sync python this_file.py   (run from repo root)
import json, math, statistics as st
from decimal import Decimal
from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import HMM3StateFractional, regime_posterior_entropy_nats

quotes = [NBBOQuote(timestamp_ns=d["timestamp_ns"], correlation_id=d["correlation_id"],
            sequence=d["sequence"], symbol=d["symbol"], bid=Decimal(d["bid"]),
            ask=Decimal(d["ask"]), bid_size=d["bid_size"], ask_size=d["ask_size"],
            exchange_timestamp_ns=d["exchange_timestamp_ns"])
          for d in (json.loads(l) for l in open("tests/fixtures/event_logs/synth_5min_aapl.jsonl"))
          if d.get("kind") == "NBBOQuote"]

eng = HMM3StateFractional(); eng.calibrate(quotes)
nm, vb = eng.state_names.index("normal"), eng.state_names.index("vol_breakout")
ent = [regime_posterior_entropy_nats(eng.posterior(q)) for q in quotes]
# -> separation d≈0.02-0.07; entropy mean 1.061, 100% > 0.95; P(normal) never > 0.5.
# Re-run with spreads drawn 1-5 cents -> d01=0.98, d12=2.27; entropy mean 0.26; P(normal)>0.5 on 39%.
```

Measured output is reproduced in the §2 table. The script is intentionally
*not* added to `src/` (analysis tooling, not production); R-2 would promote a
hardened version into the validation suite.

## Appendix B — open questions still needing the APP cache

1. APP 2026-06-01..05 calibrated min pairwise separation `d` and the realized `P(vol_breakout)` / posterior-entropy distributions (confirms §2's falsifiable claim for the actual regression dataset).
2. Conditional forward return of `sig_benign_midcap_v1` over its 120 s horizon, bucketed by `P(vol_breakout)` decile — does edge actually *fall* as `P(vol_breakout)` rises (the P1-6 premise), or was it flat/positive (which the −91%/sign-flip implies)?
3. Same, bucketed by posterior entropy — is there any entropy band where conditional edge improves, or is entropy uncorrelated with edge for this alpha?
