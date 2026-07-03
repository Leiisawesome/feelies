# Sensor Audit — 2026-07-02

Read-only, evidence-based audit of the feelies Layer-1 sensor framework and its
path into `HorizonFeatureSnapshot` features, per `docs/prompts/audit_sensor.md`.
No production code, baselines, configs, or ledgers were modified.

**Prior audits in this series:** [`sensor_audit_2026-06-11.md`](sensor_audit_2026-06-11.md) →
[`sensor_audit_2026-06-19.md`](sensor_audit_2026-06-19.md) (last full pass) →
[`sensor_audit_2026-06-30.md`](sensor_audit_2026-06-30.md) (short reconciliation pass).
This pass re-verifies every open item from 2026-06-30, closes what the repo has
since fixed, and adds findings the prior passes did not surface — principally
by cross-referencing sensor code against the alpha YAML bodies that actually
consume it, and against the two other prior audit series
(`signal_alpha_audit_2026-06-14.md`) where an alpha built on a sensor was
subsequently quarantined for lack of measured edge.

Severity legend: **P0** correctness / lookahead / non-determinism; **P1**
feature strength / tradability / provenance integrity; **P2** research /
calibration / citation precision.

**Agent context loaded (in order):** `.cursor/rules/platform-invariants.mdc`
(Inv-1, 3, 4, 5, 6, 10, 11, 12, 13), `.cursor/rules/karpathy-guidelines.mdc`,
`.cursor/skills/README.md`, `.cursor/skills/feature-engine/SKILL.md` (owner),
`.cursor/skills/microstructure-alpha/SKILL.md`, `docs/three_layer_architecture.md`
§5.2/5.3/7.4/20.4, `platform.yaml`.

**Not-shipped cross-check:** snapshot/sensor checkpoint persistence
(feature-engine skill) is confirmed absent from `src/feelies/` and is correctly
excluded below as a design target, not a defect. Dormant sensors
(`vpin_50bucket`, `snr_drift_diffusion`, `structural_break_score`) are audited
as available research code, not live production inputs.

**Verification (read-only, this pass):**

```
uv sync --all-extras
PYTHONHASHSEED=0 uv run pytest tests/sensors/ -q                     → 203 passed, 1 skipped
PYTHONHASHSEED=0 uv run pytest tests/sensors/ tests/features/ -q -rs → 319 passed, 1 skipped
  (skip: test_sensor_latency_budget.py — opt-in perf micro-benchmark, CI_BENCHMARK=1)
PYTHONHASHSEED=0 uv run pytest tests/determinism/test_sensor_reading_replay.py \
  tests/determinism/test_horizon_feature_snapshot_replay.py -q        → 4 passed
```

No production code was modified to obtain these results.

---

## Executive summary

1. **No new P0-severity defects.** Across all 18 shipped sensor implementations
   and the aggregator, no lookahead, non-determinism, or unit/sign error was
   found. All read-only checks are green (above). This itself is notable — the
   codebase shows a real, traceable history of prior audit remediation (the
   `audit P0-1`, `P1-x`, `3P-x` markers throughout the sensor modules).
2. **Prior-audit P0 reconciliation:** of 2026-06-19's three open P0s — (a)
   `boundary_ts_ns` ambiguity is now **closed at the data-model level**
   (`core/events.py:615-619,684-686`), but the platform's own IC harness still
   doesn't consume it (see finding P1-3 below — a narrower, concrete re-opening);
   (b) **version-blind feature dispatch remains open**, and is now confirmed to
   have **zero test coverage** of the fold/warn path
   (`features/aggregator.py:379-400`); (c) **the throttled+stateful contract gap
   is now closed** — `tests/sensors/test_throttle_dispatch.py` and
   `test_spec_throttle_guard.py` were added since the 06-30 pass and directly
   lock both registry branches.
3. **`book_imbalance` and `ofi_raw` are undocumented in their own catalog.**
   Both are registered production sensors (`platform.yaml:316-353`) — and
   `book_imbalance` is a load-bearing dependency of the *only* alpha wired into
   the reference config — yet both are absent from the "16 total" table in
   `.cursor/skills/feature-engine/SKILL.md` and from `sensors/impl/__init__.py`'s
   own module docstring (18 modules exist; 15 are registered).
4. **`book_imbalance` skips the crossed-book guard every sibling price sensor
   applies.** `ofi_ewma`, `ofi_raw`, `micro_price`, `spread_z_30d`,
   `liquidity_stress_score`, `quote_flicker_rate`, `kyle_lambda_60s`,
   `trade_through_rate`, `structural_break_score`, `snr_drift_diffusion` all
   reject `bid > ask` (tagged `3P-2` in-line); `book_imbalance.py:111-116` checks
   only `bid <= 0.0 or ask <= 0.0`. A locked/crossed NBBO print therefore updates
   `book_imbalance_mean`/`_zscore` while every sibling silently skips the same
   tick — a cross-sensor time-base inconsistency reaching the one alpha in
   production.
5. **A "cosmetic fingerprint" the platform already has a gate for survives
   undetected in the reference alpha.** `sig_benign_midcap_v1` declares
   `micro_price` in both `depends_on_sensors` (`:51-56`) and the G16
   `l1_signature_sensors` fingerprint list (`:164-166`), but `evaluate()` never
   reads any micro_price-derived value (only `ofi_ewma_zscore` and
   `book_imbalance_mean`, `:181,189`). The alpha's own comment block
   (`:151-160`) narrates fixing exactly this pattern for `kyle_lambda_60s` —
   G16 rule 10 (`alpha/layer_validator.py:983-998`) checks that
   `l1_signature_sensors ⊆ depends_on_sensors`, but nothing checks that
   `depends_on_sensors` is actually read inside `evaluate()`'s body, so the same
   defect re-enters through a different sensor in the same file.
6. **39% of the implemented sensor catalog drives zero strategies.** 3 of 18
   are unregistered/dormant (`vpin_50bucket`, `snr_drift_diffusion`,
   `structural_break_score`); 4 more are registered, computed every session on
   the tick-critical path, and have **no alpha consumer at all**
   (`inventory_pressure`, `liquidity_stress_score`, `quote_flicker_rate`,
   `ofi_raw` — verified by grepping every `depends_on_sensors:` block in
   `alphas/`).
7. **Zero LIQUIDITY_STRESS-family alphas exist**, despite four dedicated
   LIQUIDITY_STRESS sensors computed continuously. G16 marks the family
   exit-only (Inv-11 fail-safe intent), but no alpha has been authored to *act*
   on it as a primary driver — today it only supplies secondary regime-gate
   thresholds inside other families' `off_condition`s.
8. **Direct empirical counter-evidence for the INVENTORY family.**
   `sig_inventory_revert_v1`, built on `quote_replenish_asymmetry_zscore`, was
   QUARANTINED (`docs/audits/signal_alpha_audit_2026-06-14.md`) after a 6-session
   study found the fade premise contradicted (pooled IC ≈ −0.007; the SHORT leg
   showed *positive* forward returns in 5/6 sessions). The sensor's own
   docstring still states its "tradeable" sign convention as settled fact
   (`quote_replenish_asymmetry.py:1-36`), and the family's other L1 fingerprint
   (`inventory_pressure`, trade-side) has never been alpha-tested at all (see
   #6).
9. **Warm-up is a raw reading COUNT almost everywhere, not count-and-elapsed-
   time.** `structural_break_score` is the only sensor requiring both a sample
   count *and* a minimum elapsed window (`structural_break_score.py:203`); every
   other sensor warms on count alone, so a traffic burst can make a sensor
   "warm" using the very burst that makes the reading least representative —
   sharpest for the 5-second-window sensors (`quote_replenish_asymmetry`,
   `quote_hazard_rate`, `quote_flicker_rate`; 20-quote minimums reachable in a
   fraction of a second in a burst).
10. **Design doc drift on `hawkes_intensity` semantics.**
    `docs/three_layer_architecture.md:2116-2119` still documents the tuple output
    as "λ per second" with a branching-ratio stability metric ("near 1 =
    unstable cascade"); the shipped sensor's own docstring
    (`hawkes_intensity.py:18-32`) explicitly disclaims both (arbitrary impulse
    units; not a fitted process, so no branching-ratio semantics apply). The
    code self-corrected; the top-level design doc was never back-ported.
11. **The IC harness itself doesn't use the platform's own "regular-grid anchor
    for IC labels" field.** `HorizonFeatureSnapshot.boundary_ts_ns` is
    documented exactly for this purpose (`core/events.py:684-686`), but
    `scripts/sensor_feature_ic.py:321` still pairs forward returns from
    `snapshot.timestamp_ns` (trigger time). On any session with a data gap
    before a boundary-crossing event, every RankIC number this script (and this
    audit series) has produced is measured from a slightly shifted anchor.
12. **`scripts/calibrate_hawkes.py` output has never been fed back into
    production.** The script implements a correct exponential-kernel Hawkes MLE
    (verified: proper compensator term in the log-likelihood), but
    `platform.yaml`'s `hawkes_intensity` spec (`:398-409`) still hand-sets
    `alpha=0.4, beta=0.05` with no calibration run behind it.
13. **`book_imbalance` has no dedicated test file** — the only registered
    sensor without one (every sibling has `tests/sensors/test_<sensor_id>.py`).
    Existing spot coverage (sign-convention golden, winsorization) does not
    exercise a crossed-book input or the sliding-window gap-reversion its own
    docstring claims to mirror from `ofi_ewma`/`micro_price`.
14. **Verified correct, not just plausible:** `ofi_ewma`/`ofi_raw` match
    Cont–Kukanov–Stoikov (2014) OFI term-by-term (algebraic check below);
    `structural_break_score`'s Page-Hinkley recursion is verified equivalent to
    the canonical reflected-random-walk form; the two count-window sensors that
    cannot self-revert to cold after a gap (`spread_z_30d`,
    `liquidity_stress_score`) are both configured with `max_gap_seconds: 300`
    in the reference `platform.yaml` — the risk the code comments warn about is
    already mitigated in production, not a live gap.
15. **No cross-sectional normalization at the horizon boundary** — deliberate,
    documented, and correctly scoped to Layer 3 (`aggregator.py:57-70`); carried
    forward from 2026-06-19 as still-open research, not a defect.

---

## Sensor inventory

15 of 18 implemented sensors are registered in `platform.yaml` `sensor_specs:`
(all `input_sensor_ids: []` — the live DAG is a flat fan-out from raw
NBBO/Trade; the registry's topological-order/cycle rejection exists but is
currently untriggered). "Consumers" counts `depends_on_sensors:` references
across every `alphas/**/*.alpha.yaml` (10 files, incl. `_template/` and
`research/`).

| sensor_id | ver. | family (G16) | inputs | clock/warm basis | registered | consumers | test file |
|---|---|---|---|---|---|---|---|
| `spread_z_30d` | 1.1.0 | LIQUIDITY_STRESS | NBBO | count window 6000, `max_gap_seconds=300` | yes | 5 | `test_spread_z_30d.py` |
| `quote_replenish_asymmetry` | 1.1.0 | INVENTORY | NBBO | event-time 5s, min 20 obs | yes | 1 (QUARANTINED alpha) | `test_quote_replenish_asymmetry.py` |
| `quote_hazard_rate` | 1.0.0 | INVENTORY | NBBO | event-time 5s, min 20 | yes | 1 | `test_quote_hazard_rate.py` |
| `ofi_ewma` | 1.1.0 | KYLE_INFO | NBBO | quote-decay `tau=10s`, warm 50/300s | yes | 5 | `test_ofi_ewma.py` |
| `ofi_raw` | 1.0.0 | KYLE_INFO | NBBO | event-time, warm 50/300s | yes | **0** | `test_ofi_raw.py` |
| `micro_price` | 1.1.0 | KYLE_INFO | NBBO | event-time, warm 1/60s | yes | 4 | `test_micro_price.py` |
| `book_imbalance` | 1.0.0 | KYLE_INFO | NBBO | event-time, warm 1/60s, cap 0.95 | yes | 1 | **none dedicated** |
| `kyle_lambda_60s` | 2.0.0 | KYLE_INFO | NBBO+Trade | event-time 60s, min 30, `alignment=causal` | yes | 2 | `test_kyle_lambda_60s.py` |
| `trade_through_rate` | 1.1.0 | KYLE_INFO | NBBO+Trade | event-time 30s, min 5 | yes | 1 | `test_trade_through_rate.py` |
| `hawkes_intensity` | 1.2.0 | HAWKES_SELF_EXCITE | Trade | decay `beta=0.05`, warm 10/side/60s | yes | 1 | `test_hawkes_intensity.py` |
| `scheduled_flow_window` | 1.2.0 | SCHEDULED_FLOW | NBBO | calendar lookup, unthrottled | yes | 1 | `test_scheduled_flow_window.py` |
| `realized_vol_30s` | 1.3.0 | LIQUIDITY_STRESS | NBBO | event-time 30s, warm 16 | yes | 6 | `test_realized_vol_30s.py` |
| `inventory_pressure` | 1.0.0 | INVENTORY | Trade | event-time 60s, min 20 | yes | **0** | `test_inventory_pressure.py` |
| `liquidity_stress_score` | 1.0.0 | LIQUIDITY_STRESS | NBBO | count window 6000, `max_gap_seconds=300` | yes | **0** | `test_liquidity_stress_score.py` |
| `quote_flicker_rate` | 1.0.0 | LIQUIDITY_STRESS | NBBO | event-time 5s, min 20 | yes | **0** | `test_quote_flicker_rate.py` |
| `vpin_50bucket` | 1.1.0 | LIQUIDITY_STRESS | Trade | 50×5000-share buckets | **dormant** | 0 | `test_vpin_50bucket.py` |
| `snr_drift_diffusion` | 1.3.0 | cross-cutting | NBBO | multi-horizon EWMA, warm 4/horizon | **dormant** | 0 | `test_snr_drift_diffusion.py` |
| `structural_break_score` | 1.2.0 | cross-cutting | NBBO | Page-Hinkley, 3600s ref window | **dormant** | 0 | `test_structural_break_score.py` |

Note: the microstructure-alpha skill classifies `quote_flicker_rate` under
LIQUIDITY_STRESS (matching G16's `_FAMILY_FINGERPRINT_SENSORS`), correcting the
inventory list above vs. an informal INVENTORY-adjacent reading of its docstring.

---

## Per-sensor audit

### `ofi_ewma` / `ofi_raw` — KYLE_INFO, order-flow imbalance

**Definition.** Both implement Cont–Kukanov–Stoikov (2014) OFI term-by-term —
verified by expanding their indicator-function definition against the code's
branch structure (`ofi_ewma.py:184-197`, `ofi_raw.py:125-137`): bid contributes
`+bid_size_t` / `-bid_size_{t-1}` / `Δbid_size` on price-up/down/flat, ask
contributes the mirror-signed terms. `ofi_raw` emits the unsmoothed per-event
term so a `sum` reducer over a horizon window yields the true Σofi_t (the
literature-correct KYLE_INFO input); `ofi_ewma` low-pass filters it
(event-count or event-time decay, `decay_tau_seconds`). **This is a verified-
correct implementation, not merely plausible** — flag as such in future audits
so it isn't re-litigated.

**L1 caveats.** Depth changes are treated as flow without trade confirmation —
standard OFI limitation, disclosed nowhere but implicit; a cancel-and-repost at
a new size looks identical to genuine replenishment.

**Numerical/warm-up.** Pure float arithmetic, `3P-2` crossed-book rejection,
sliding-window (S3) warm-up that reverts to cold after gaps.
`normalize_by_depth=true` + `max_gap_seconds=300` are both configured in
production (`platform.yaml:298-305`).

**Consumption/findings.** `ofi_ewma` feeds 5 alphas; `ofi_raw`'s only feature
(`ofi_integrated`, `bootstrap.py:1167-1175`) has **zero** alpha consumers — the
bootstrap comment itself says KYLE alphas "should prefer `ofi_integrated` once
an entry threshold is calibrated," i.e. this is a known, disclosed,
not-yet-actioned migration (carried from 06-19 P1 #1 — still open;
`sig_kyle_drift_v1` still reads bare `ofi_ewma`).

---

### `micro_price` — KYLE_INFO, Stoikov micro-price

**Definition.** `(ask·bid_size + bid·ask_size)/(bid_size+ask_size)`, correctly
matching Stoikov (2018). Degenerate (zero-depth) books fall back to mid with
`warm=False` — correct "undefined ≠ balanced" handling.

**L1 caveats.** A z-score of the *level* is dominated by price drift, not the
sub-cent imbalance content — this is exactly why `book_imbalance` was built as
a level-invariant alternative (verified: `(micro-mid)/spread = book_imbalance/2`
holds algebraically).

**Findings.** See executive summary #5 — declared as a dependency and G16
fingerprint in `sig_benign_midcap_v1` but never read in `evaluate()`. This is a
**P1** finding distinct from (and narrower than) 06-19's related recommendation
to stop reading `micro_price_zscore` directly (which *was* actioned — the alpha
migrated to `book_imbalance_mean` — but left the now-unused declaration
behind).

---

### `book_imbalance` — KYLE_INFO, top-of-book size imbalance

**Definition.** `(bid_size-ask_size)/(bid_size+ask_size) ∈ [-1,1]`, winsorised
to `±imbalance_cap` (production: 0.95). Correct, simple, well-motivated as the
level-invariant transform of the Stoikov micro-price deviation.

**Findings (P1).** Missing the `bid > ask` crossed-book guard every sibling
price sensor applies (`book_imbalance.py:111-116` vs. e.g.
`ofi_ewma.py:143`, `micro_price.py:84`) — see executive summary #4. **Test gap
(P1):** no dedicated `tests/sensors/test_book_imbalance.py`; existing coverage
is a sign-convention golden (`test_sensor_sign_goldens.py:149-157`) and two
winsorization robustness tests (`test_robustness_3p.py:141-157`) — neither
exercises a crossed-book input or the sliding-window (S3) gap-reversion its own
docstring claims (`book_imbalance.py:36-39`) to mirror from `ofi_ewma` /
`micro_price`.

---

### `kyle_lambda_60s` — KYLE_INFO, price-impact regression

**Definition.** Standard OLS slope of `Δmid` on signed trade flow over a
60s rolling window: `λ = (nΣΔpΔq - ΣΔpΣΔq)/(nΣΔq² - (ΣΔq)²)`. This is the
common practitioner operationalization of Kyle (1985)'s theoretical λ — note
for precision that Kyle (1985) is the origin of the *concept*, not this
trade-level regression estimator, which is closer to the Hasbrouck (1991)
price-impact-regression tradition (P2 citation nit, not a defect).

**Numerical stability.** The Cauchy-Schwarz-based degeneracy guard
(`denom <= 1e-12 * n * sum_dq2`) is a well-reasoned defence against OLS blow-up
under near-constant flow; comment explicitly pins the non-associative form to
avoid re-triggering a locked golden vector.

**Verified-fixed sign bug.** Two alignments exist: `"causal"` (2.0.0, class +
platform.yaml default) pairs `Δp` with the *prior* trade's flow (correct Kyle
timing); `"legacy"` (1.2.0) pairs it with the *current* trade's flow and is
**documented as wrong-signed at KYLE horizons** by the platform's own cached IC
comparison (`platform.yaml:363-371`: legacy RankIC −0.225/−0.155/−0.194 vs.
causal +0.145/+0.160/+0.150 at 300/900/1800s). Both the class constructor
default and the production YAML pin `causal`; `legacy` requires explicit opt-in
— low residual risk.

---

### `trade_through_rate` — KYLE_INFO (secondary), NBBO-aggression rate

**Definition/naming (P2).** The sensor_id and the standard Reg-NMS
"trade-through" term (strictly outside NBBO) don't match what's measured (at-or-
beyond NBBO, i.e. touches included) — disclosed candidly in the module
docstring (`:1-12`) but not in the microstructure-alpha skill's glossary, so a
future strategy author reading only the sensor_id could assume the stricter
definition. Implementation itself is correct and deterministic.

---

### `hawkes_intensity` — HAWKES_SELF_EXCITE, self-exciting trade intensity

**Definition.** Two-sided additive-impulse EWMA (`λ ← μ + (λ-μ)e^{-βΔt}`, impulse
`+α` on same-side trade). This is **not** a fitted Hawkes process — the
module's own docstring is explicit that `intensity_ratio`'s companion
`impulse_decay_ratio` (α/β) is a configured constant, not a runtime branching-
ratio stability estimate (`:18-32`).

**Findings (P1, documentation).** `docs/three_layer_architecture.md:2108-2136`
(§20.4.1) still describes the tuple as "λ per second" with a branching-ratio
interpretation ("near 1 = unstable cascade") — the top-level design doc was
never back-ported to match the code's own (correct, more careful)
self-disclosure. **Findings (P2, research):** `scripts/calibrate_hawkes.py`
implements a real exponential-kernel MLE (compensator term verified correct:
`comp += (α/β)(1-e^{-β(T-t_i)})`, matching the standard Hawkes log-likelihood),
but its fitted α, β have never been fed back into `platform.yaml`'s hand-set
`alpha=0.4, beta=0.05` (half-life ln2/0.05 ≈ 13.9s, inside the HAWKES family's
[5,60]s G16 envelope by luck of manual tuning, not calibration).

---

### `scheduled_flow_window` — SCHEDULED_FLOW, calendar window membership

**Definition.** Deterministic calendar lookup; salted-hash-free
`window_id_hash` via `sha256` (good determinism hygiene vs. Python's
PYTHONHASHSEED-salted `hash()`). Tie-break (earliest `end_ns`, then
lexicographic `window_id`) is fully deterministic.

**Architectural note (P2).** One of its four tuple components,
`flow_direction_prior`, is an **exogenous, statically-configured** value from
the calendar YAML — not computed from any `NBBOQuote`/`Trade` the sensor
observes. The consuming alpha's own hypothesis text is admirably candid about
this (`sig_moc_imbalance_v1.alpha.yaml:16-25`: "NOT derived from L1 NBBO"), but
the *sensor's* docstring doesn't flag that one of its outputs isn't a computed
observation at all — worth a note in the `Sensor` protocol docs so future
authors don't assume every `SensorReading.value` component is derived from raw
events.

**Efficiency (P2).** Unthrottled (`platform.yaml:411-418`) and returns a value
on every single quote (never `None`), including outside any window when 3 of 4
tuple components are constant — minor tick-path overhead, not correctness.

---

### `realized_vol_30s` — LIQUIDITY_STRESS, realized volatility

**Definition.** Bessel-corrected sample std of mid-price log-returns via
Welford sliding-window mean/M2 (Pébay 2008) — correct, and appropriately more
careful than `spread_z_30d`'s population-variance convention (both documented
choices, not inconsistencies — `spread_z_30d`'s is pinned by a locked golden
vector).

**Aggregation choice, verified by evidence (positive finding).** Its z-score
feature (`realized_vol_30s_zscore`) is the **one exception** still using the
legacy count-window `RollingZscoreFeature` rather than the newer
event-time-windowed `HorizonWindowedFeature` — and the `bootstrap.py:1341-1346`
comment cites a specific, falsifiable reason: an IC run showed the windowed
variant *regressed* (RankIC 0.191 vs. 0.523 at h=1800s). This is exactly the
kind of evidence-before-architecture-preference the platform-invariants doc
(Inv-3) asks for — flag as a template for how other aggregation choices should
be justified, and re-test periodically since Inv-4 assumes edges decay.

---

### `quote_replenish_asymmetry` — INVENTORY, quote-side replenishment

**Definition.** Correctly requires the *same* price level (not just price
improvement) before counting a size increase as replenishment — a real,
non-trivial correctness safeguard (avoids miscounting a price step as
depth-adding).

**Findings (P1, economic).** The one alpha built on this sensor
(`sig_inventory_revert_v1`) is **QUARANTINED**
(`docs/audits/signal_alpha_audit_2026-06-14.md`) on direct empirical grounds:
pooled Spearman IC of `quote_replenish_asymmetry_zscore` vs. forward 30s
micro-price return ≈ −0.007 (indistinguishable from zero), and the SHORT leg
(very negative asym_z) showed *positive* forward returns in 5/6 studied
sessions — the opposite of the fade hypothesis. The sensor's own docstring
(`:26-32`) still states the sign convention as a settled "tradeable" fact. This
doesn't mean the code is wrong (it isn't — it's a clean, correct implementation
of a well-motivated microstructure hypothesis); it means the hypothesis itself
is currently unconfirmed-to-falsified at the studied horizon, and the sensor's
own documentation should say so pending re-study (Inv-3, Inv-4).

---

### `quote_hazard_rate` — INVENTORY (secondary), quote arrival rate

**Definition.** `n_in_window / window_seconds` — simple, correct, but its
"warm" gate is explicitly a **count** threshold ("a burst that fills the
window's count budget instantly satisfies it," `:15-18`, the sensor's own
docstring). See executive summary #9.

---

### `inventory_pressure` — INVENTORY, trade-side MM-inventory proxy

**Definition.** Correctly cites Ho & Stoll (1981) / Madhavan & Smidt (1991);
`Σ(-aggressor·size)/Σsize` is a sound, simple accumulation. Tick-rule aggressor
classification matches `hawkes_intensity`/`vpin_50bucket` for consistency.

**Findings (P1).** Registered and computed every session
(`platform.yaml:433-442`) but **zero alphas** declare it as a dependency —
the INVENTORY family's canonical trade-side fingerprint (per the
microstructure-alpha skill's mechanism table) has never been alpha-tested,
while its quote-side sibling (`quote_replenish_asymmetry`) has been tested and
quarantined for lack of edge. The family's L1-observability is therefore
currently unvalidated-or-falsified end to end.

---

### `liquidity_stress_score` — LIQUIDITY_STRESS, composite stress alarm

**Definition.** `1 - exp(-(max(0,z_spread)+max(0,z_thin))/k)` — a sound,
one-sided (alarm-not-index) composite; scores the incoming sample against the
*prior* baseline before folding it in (avoids self-contamination — a good,
non-obvious correctness property, verified by reading `update()`'s ordering).

**Findings (P1).** Registered, computed every session, **zero alpha
consumers**. Correctly configured with `max_gap_seconds: 300`
(`platform.yaml:450-451`), so the "count window can't self-revert to cold"
risk flagged in its own docstring is mitigated in production — verified, not a
live gap.

---

### `quote_flicker_rate` — LIQUIDITY_STRESS, best-price reversal fraction

**Definition.** Per-side sign-reversal detection on best bid/ask changes,
correctly excludes zero-deltas from "direction" bookkeeping. Sound and simple.

**Findings (P1).** Registered, computed every session, **zero alpha
consumers** — part of the "4 orphaned sensors" / "zero LIQUIDITY_STRESS
alphas" findings above.

---

### `spread_z_30d` — LIQUIDITY_STRESS, spread z-score

**Definition.** Welford sliding-window (Pébay 2008) z-score of `ask-bid`;
"30d" naming is historical (actual window is 6000 *quotes*, not 30 days —
disclosed candidly in the docstring, `:9-15`). Population variance (`M2/n`),
not Bessel-corrected — a deliberate, pinned convention (0.008% difference at
n=6000; locked golden vectors depend on it).

**Findings.** Same `max_gap_seconds`-mitigated pattern as
`liquidity_stress_score` — verified not a live issue. This is the platform's
most heavily consumed sensor (5 of 5 shipped SIGNAL alphas gate on it), making
its numerical conventions the highest-leverage to get right, which they are.

---

### `vpin_50bucket` — LIQUIDITY_STRESS (dormant), flow toxicity

**Definition.** Correctly implements equal-volume bucketing with exact
spillover conservation (verified: the running `buckets_sum` is kept in sync
with deque eviction, `:130-146`) and cites Easley, López de Prado & O'Hara
(2012).

**Findings (P2, citation).** Classifies trades by **tick rule**, not the
original paper's bulk-volume classification (BVC, `Φ(ΔP/σ)`). Tick-rule and BVC
VPIN can diverge materially (cf. Andersen & Bondarenko (2014), "VPIN and the
Flash Crash," on this exact divergence) — worth reconciling with the literature
before promoting out of dormant status, not urgent given zero current
consumers.

---

### `scheduled_flow_window`, `snr_drift_diffusion`, `structural_break_score` — cross-cutting / dormant

`snr_drift_diffusion` (grid-anchored multi-horizon EWMA SNR estimator) is
mathematically sound and clearly self-derived (not tied to one canonical named
estimator in the literature — a P2 citation gap, not a defect).
`structural_break_score`'s Page-Hinkley recursion
(`m_t = max(0, m_{t-1}+(x_t-μ_ref)-δ)`) is **verified algebraically equivalent**
to the canonical reflected-random-walk form `S_t - min_{s≤t}S_s` by induction —
a correct, standard implementation. Its observable is `abs(log-return)`, so it
specifically detects **volatility-regime** up-breaks, not a general
drift/serial-correlation break with unchanged move magnitude — worth a scope
note for `forensics/multi_horizon_attribution.py` consumers (P2). All three
remain correctly excluded from `platform.yaml` per the feature-engine skill's
"Not shipped" classification for cross-sensor wiring
(`structural_break_score.py:9-27` is explicit that true upstream-sensor Page-
Hinkley, the v0.3 design intent, isn't implemented — the shipped version reads
raw mid-price returns instead).

---

## Horizon aggregation audit (`HorizonAggregator`)

**Architecture.** Pull-based (features never subscribe to the bus directly);
O(1) bus-handler count regardless of feature count, mirroring
`SensorRegistry`'s pattern. Per-`(symbol, sensor_id, sensor_version)` ring
buffers bounded to `2×max(horizons)` event-time. Verified deterministic:
features and symbols are pre-sorted at construction (`_features_sorted`,
`_symbols_sorted`), so the hot path never re-sorts (Inv-C).

**Boundary semantics (positive, verified).** `HorizonScheduler` fires
`boundary_index=0` for every `(horizon, scope, symbol)` on the very first event
of the session, immediately (`elapsed=0 ⇒ current_boundary=0`, and the
`last is None` guard treats *any* first value as "new"). This is intentional
and locked by
`tests/sensors/test_horizon_scheduler.py:62-67`
(`test_first_event_emits_boundary_zero_for_each_scope`) — not a bug. Every
consuming feature correctly reports `warm=False` on this degenerate,
near-zero-history snapshot, so it cannot produce a bad signal; it does mean one
guaranteed-wasted `HorizonFeatureSnapshot` emission per `(symbol, horizon)` per
session (P2, efficiency only).

**Dedup symmetry (verified).** `_last_snapshot_boundary` is consulted by both
the SYMBOL and UNIVERSE tick branches (`aggregator.py:439-451`), so the
`(symbol, horizon, boundary)` invariant holds regardless of which scope tick
arrives first — the module's own "audit #1" comment documents this was
previously asymmetric; now fixed and correct.

**Staleness (verified causal).** `_latest_warm_reading_ns_at_or_before` only
considers `ts_ns <= asof_ns` (`:581-600`) and `_last_reading_ns` only advances
forward on warm readings (`:368-372`) — both properties independently
re-derived from the code and confirmed causal (Inv-6) and monotonic (immune to
late/out-of-order arrivals regressing freshness).

**Fail-safe (verified, defence in depth).** Non-finite sensor values are
suppressed at the registry (`registry.py:82-93,317-329`) *and* non-finite
feature-reducer outputs are independently demoted to cold at the aggregator
(`aggregator.py:519-538`) — two independent layers catching the same class of
poison value, which is good practice given they're different code paths
(raw sensor value vs. a reducer computed over many of them).

**Aggregation-policy-per-mechanism (positive, IC-evidenced).** Reducer choice
is sensor-specific and, per `bootstrap.py`'s comments, backed by measured IC in
several cases: `HorizonWindowedFeature`'s event-time window replaced a
horizon-blind count window for `ofi_ewma`/`micro_price`/`kyle_lambda_60s`/
`book_imbalance`/`quote_replenish_asymmetry`/`quote_hazard_rate`/
`quote_flicker_rate` (audit P1-1), while `realized_vol_30s` was deliberately
**kept** on the older count-window feature after an IC regression showed the
windowed variant underperformed at long horizons (see per-sensor section
above). This — aggregation choices justified by a documented, falsifiable IC
comparison rather than by architectural symmetry alone — is the strongest
practice in the pipeline and should be the template going forward.

**Open gaps (carried + refined):**

- **Version-blind dispatch (P0, open, now confirmed untested).**
  `_feature_state` is keyed by `(feature_id, horizon_seconds, symbol)` — no
  `sensor_version` (`aggregator.py:249-259`) — and `_features_by_sensor` is
  keyed by bare `sensor_id` (`:270-273`). Two concurrently-live versions of one
  `sensor_id` fold into the same feature state after only a one-shot warning
  (`:379-400`). Not currently triggered (production registers exactly one
  version per `sensor_id`), so severity-in-current-deployment is low, but it is
  a real gap that would silently corrupt a future A/B sensor rollout, and
  grepping `tests/` for `multi_version` / `_observed_versions` finds **no
  test** exercising this path at all (the throttle contract's equivalent gap
  was closed with dedicated tests — this one hasn't been).
- **IC-harness anchor mismatch (P1, newly identified).**
  `HorizonFeatureSnapshot.boundary_ts_ns` is documented as "the regular-grid
  anchor for IC labels" (`core/events.py:684-686`) specifically to fix the
  06-19 P0 finding, but `scripts/sensor_feature_ic.py:321` still calls
  `_forward_return(mids, s.timestamp_ns, horizon)` — trigger time, not the
  grid anchor. On a sparse tape this silently shifts every IC number the
  script (and by extension this audit series' evidence base) produces.
- **No cross-sectional normalization at the boundary (P2, carried from
  06-19).** Deliberately out of scope per the aggregator's own docstring
  (`:57-70`) — correctly deferred to Layer 3, not a defect, but still an open
  research question for KYLE/momentum families where "unusual vs. peers right
  now" and "unusual vs. own history" are different information.

---

## Mechanism × horizon matrix

| Family | Half-life envelope (G16) | Primary fingerprint(s) wired | Alphas (horizon / half-life / ratio) | Aggregation |
|---|---|---|---|---|
| KYLE_INFO | 60–1800s | `kyle_lambda_60s`, `micro_price`, `book_imbalance`, `ofi_ewma`/`ofi_raw` | `sig_benign_midcap_v1` (120/120=**1.00**), `sig_kyle_drift_v1` (300/600=**0.50**) | Event-time windowed (zscore/percentile/mean/sum/delta), all 5 horizons |
| INVENTORY | 5–60s | `quote_replenish_asymmetry`, `inventory_pressure` | `sig_inventory_revert_v1` (30/20=**1.50**) — QUARANTINED | `quote_replenish_asymmetry`: windowed zscore, all horizons; `inventory_pressure`: passthrough at **h=30 only** (deliberately, `bootstrap.py:1246-1248`) |
| HAWKES_SELF_EXCITE | 5–60s | `hawkes_intensity` | `sig_hawkes_burst_v1` (30/30=**1.00**) | Windowed zscore + signed imbalance, all horizons |
| LIQUIDITY_STRESS | 30–600s | `vpin_50bucket` (dormant), `realized_vol_30s`, `liquidity_stress_score`, `spread_z_30d`, `quote_hazard_rate`, `quote_flicker_rate` | **none** (exit-only; zero dedicated alphas) | Passthrough / count-window zscore; feeds other families' gates only |
| SCHEDULED_FLOW | 60–1800s | `scheduled_flow_window` | `sig_moc_imbalance_v1` (120/240=**0.50**) | Tuple-component passthrough, all horizons |

**Razor's-edge observation (P2, new):** `sig_kyle_drift_v1` and
`sig_moc_imbalance_v1` both sit at horizon/half-life **ratio exactly 0.500** —
the G16 lower bound with zero margin. A small future recalibration of either
`expected_half_life_seconds` field (e.g. from a decay re-study, per Inv-4) could
silently flip a currently-passing alpha into a G16 rejection on next load.
Consider a soft warning below, say, 0.55 so this is visible before it becomes a
hard failure.

---

## Test gap matrix

| Sensor / area | Coverage | Gap |
|---|---|---|
| `book_imbalance` | Sign golden + winsorization (2 shared files) | No dedicated test file; no crossed-book case; no S3 gap-reversion case |
| Multi-version feature dispatch | None | No test drives two live `sensor_version`s into one feature to characterize the fold/warn behavior |
| `scripts/sensor_feature_ic.py` anchor | Script runs, not unit-tested | No test pins `boundary_ts_ns` vs. `timestamp_ns` choice for forward-return pairing |
| Warm-up burst risk | Per-sensor count-threshold tests exist | No test asserts a burst-within-milliseconds still yields a statistically thin/representative warm state (a property test, not a golden vector) |
| `inventory_pressure`, `liquidity_stress_score`, `quote_flicker_rate`, `ofi_raw` | Unit-tested in isolation | No integration/IC test exercises them through a real alpha — because none consumes them |
| `vpin_50bucket` tick-rule vs. BVC | Unit-tested for internal correctness | No test/no methodology doc compares tick-rule VPIN to BVC VPIN on the same tape |
| Sensor IC harness family coverage | 4 sensor families (`ofi_ewma`, `micro_price`, `realized_vol_30s`, `kyle_lambda_60s`) | INVENTORY, HAWKES, LIQUIDITY_STRESS, SCHEDULED_FLOW sensors have no IC harness coverage at all (carried from 06-19 P1 #6, still open) |
| Throttled + stateful contract | **Closed this pass** — `test_throttle_dispatch.py`, `test_spec_throttle_guard.py` | None remaining at the unit level; still zero live production exercise (`throttled_ms: null` everywhere) |

---

## Prioritized backlog

### P0

| Item | Effort | Invariant |
|---|---|---|
| Reject (or version-key) mixed-version feature dispatch in `HorizonAggregator`; add a test that registers two live versions of one `sensor_id` and asserts the fold/reject behavior | M | Inv-5, Inv-13 |

*(No new P0s found. The 06-19 boundary-timestamp P0 is closed at the data-model
level; the throttle-contract P0 is closed with new tests — see reconciliation
above.)*

### P1

| Item | Effort | Invariant |
|---|---|---|
| Add `bid > ask` crossed-book rejection to `BookImbalanceSensor` (`book_imbalance.py:111-116`), matching every sibling price sensor | S | data-quality parity |
| Remove `micro_price` from `sig_benign_midcap_v1`'s `depends_on_sensors`/`l1_signature_sensors`, or wire `evaluate()` to actually read a micro_price-derived feature | S | Inv-1, Inv-13 |
| Add a load-time check (or extend G16 rule 10) that cross-references `depends_on_sensors` against the identifiers actually read via `snapshot.values.get(...)` in `evaluate()`'s AST, so a cosmetic fingerprint can't recur | M | Inv-1, Inv-13 |
| Point `scripts/sensor_feature_ic.py`'s forward-return pairing at `HorizonFeatureSnapshot.boundary_ts_ns` instead of `.timestamp_ns` | S | Inv-6 |
| Add an elapsed-time floor to warm-up gates for the 5-second-window sensors (`quote_replenish_asymmetry`, `quote_hazard_rate`, `quote_flicker_rate`), mirroring `structural_break_score`'s count-AND-duration pattern | M | Inv-11 |
| Add `tests/sensors/test_book_imbalance.py` (crossed-book, S3 gap-reversion) | S | test parity |
| Wire an alpha to `inventory_pressure` / `liquidity_stress_score` / `quote_flicker_rate`, or stop computing them on the tick-critical path if they stay unconsumed | S (remove) / M (wire) | Inv-3 |
| Author (or explicitly defer with rationale) a LIQUIDITY_STRESS exit-generating alpha | L | Inv-11 |
| Update `.cursor/skills/feature-engine/SKILL.md` catalog and `sensors/impl/__init__.py` docstring to include `book_imbalance` and `ofi_raw` (18 implemented, 15 registered) | S | provenance |
| Soften `quote_replenish_asymmetry`'s docstring sign-convention framing pending re-study, given the direct quarantine evidence against it | S | Inv-3, Inv-4 |

### P2

| Item | Effort | Invariant |
|---|---|---|
| Feed `scripts/calibrate_hawkes.py`'s fitted (α, β) into a new `hawkes_intensity` `sensor_version` | M | Inv-4 |
| Reconcile `vpin_50bucket` tick-rule classification against Easley–López de Prado–O'Hara (2012) BVC before promoting out of dormant status; cite Andersen & Bondarenko (2014) | M | citation/rigor |
| Back-port the `hawkes_intensity` unit/semantics correction into `docs/three_layer_architecture.md` §20.4.1 | S | provenance |
| Evaluate cross-sectional normalization at the horizon boundary for KYLE/momentum families (carried from 06-19) | L | research |
| Add a soft warning below G16 ratio ≈0.55 so `sig_kyle_drift_v1` / `sig_moc_imbalance_v1` sitting exactly at 0.500 don't silently fail on a future half-life recalibration | S | operability |
| Throttle or push-on-change `scheduled_flow_window` (currently unthrottled, emits on every quote+trade) | S | efficiency |

---

## Appendix — open questions needing data runs

1. **INVENTORY family re-study.** Regress both `quote_replenish_asymmetry_zscore`
   and `inventory_pressure` against forward returns at 15s/30s/60s on the same
   symbol/date sample as the `signal_alpha_audit_2026-06-14.md` quarantine
   study (AAPL 2026-03-20/23/26, APP 2026-06-01/05, AGNC 2026-04-21), to
   determine whether the INVENTORY mechanism is L1-observable at all with the
   current sensor pair, or whether it needs a different construction
   (methodology only; no code changes in this pass).
2. **`ofi_integrated` calibration.** Run `scripts/sensor_feature_ic.py`'s
   existing `_ofi_integrated_ab` head-to-head (already implemented,
   `sensor_feature_ic.py:446-520`) on cached AAPL/APP data across several
   sessions to determine a defensible entry threshold before any KYLE alpha
   adopts it in place of `ofi_ewma`.
3. **Hawkes calibration.** Run `scripts/calibrate_hawkes.py --min-gap-ms 50`
   against AAPL/APP cached trades to obtain a data-driven (α, β) pair, and
   compare its implied half-life against the family's [5,60]s G16 envelope
   before cutting a new `hawkes_intensity` sensor_version.
4. **`boundary_ts_ns` vs. `timestamp_ns` sensitivity.** Re-run the P1-1 IC
   comparison (windowed vs. count-window) with the IC harness patched to use
   `boundary_ts_ns`, to quantify how much of the previously-reported RankIC
   lift is attributable to windowing vs. to anchor-timing noise on sparse
   tapes.
5. **VPIN tick-rule vs. BVC divergence.** Before promoting `vpin_50bucket` out
   of dormant status, compute both classifications on the same cached tape and
   report the correlation/divergence of the resulting bucket-imbalance series.
