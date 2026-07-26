# Stage-0 Residual Measurement — Pre-Registration

**Status:** PRE-REGISTERED — frozen before any outcome data was touched (Inv-2)
**Date:** 2026-07-25
**Design:** `dual_permission_actuation_design.md` rev 5 (locked) — §2.1, §2.3, §2.8, §3.5, §4.2
**Purpose:** Decide GO / NO-GO / UNDERPOWERED for **Stage 1** (the `P_story` map and
the mercy cell) by measuring whether Stage 0 leaves a *costly residual*.
**Non-goal:** This document authorizes no Stage-1 implementation and no change to
Stage-0 behavior.

> **Staging law (§2.3, §4.2, Inv-3, Inv-4).** Stage 1 may only be built after Stage 0
> is *shown* to leave a costly residual. Per §4.2, rejecting Claim B is an expected
> and successful outcome; Claim A (bounded deferral) stands independently. This
> pre-registration is written so that a NO-GO is as easy to reach as a GO.

---

## 0. Why pre-registration is load-bearing here

The measurement to follow has an unusually large researcher-degrees-of-freedom
surface: the deferral ceiling, the age backstop, the CVaR level, the evaluation
horizon, and the universe subset all move the answer, and all of them are
tunable *after* seeing outcomes. Tuning any of them to make a residual appear
would be fitting the config to justify the feature.

Everything in §2–§6 below is therefore fixed **now**, before any outcome series
has been computed. §7 records the specific anti-fitting commitments.

---

## 1. Pilot selection

### 1.1 Primary pilot — `sig_kyle_drift_v1`

**Selected.** `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml`

| Property | Value |
|---|---|
| Family | `KYLE_INFO` |
| `expected_half_life_seconds` | **600** — the longest declared half-life in `alphas/` |
| `horizon_seconds` | 300 |
| Family half-life envelope (`_FAMILY_HALF_LIFE_RANGES_SECONDS`) | 60 – 1800 s |
| Family `max_hold` multiple (`_FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE`) | **3×** — the most permissive in the table |

Four reasons, all grounded in the mechanism taxonomy rather than in convenience:

1. **Longest half-life ⇒ most residual to harvest.** §2.8 is explicit that mercy and
   long deferrals harvest *residual* edge after safety-OFF, and that short-half-life
   families have little left by the time the gate flips. At 600 s this alpha has the
   slowest decay in the book — if any family has a harvestable residual, it is this
   one. Choosing it is deliberately the *most favorable* case for Claim B; a NO-GO
   here is therefore strong evidence, not a scoping artifact.
2. **Its gate-OFF is a genuine regime transition.** The `off_condition` is
   `P(normal) < 0.4 or spread_z_30d > 2.0 or realized_vol_30s_zscore > 3.5` — regime
   collapse, toxic spread, and vol breakout. These are exactly the "weather" signals
   §2.1 warns are projections of the same latent state as "still looks holdable."
   The conditional-tail question ("is the reason we held the reason we should have
   left?") is *meaningful* here and can be answered per-clause.
3. **Continuous mechanism ⇒ episodes accrue through the session**, not once per
   session. This is the only structural route to a powered tail cell on the
   available cache (see §1.3).
4. **Highest legal deferral ceiling** (3× half-life = 1800 s) — the design gives this
   family the most room to express a deferral, so a null result cannot be blamed on
   an artificially tight ceiling.

### 1.2 Secondary pilot — `sig_moc_imbalance_v1` (pre-declared expected-UNDERPOWERED)

The brief asks to prefer a SCHEDULED_FLOW-class family. `sig_moc_imbalance_v1`
(`SCHEDULED_FLOW`, half-life 240 s) is the only SCHEDULED_FLOW alpha in `alphas/`.
It **will be measured and reported**, but it is pre-declared as *expected
underpowered and structurally adverse*, for two reasons recorded here in advance so
that neither can be presented later as a discovery:

1. **Power — already on the record.** `docs/research/prompt_pack_07_program_retrospective.md`
   §4.2 and its summary table record the SCHEDULED_FLOW single-window exclusion as
   **holding**: single-window-per-session mechanisms yield 10 → 20 episodes/symbol
   against a ≥ 100 floor, "still a 5× shortfall." MOC is one closing-auction window
   per symbol-session. On the frozen universe (§3, 31 non-empty symbol-sessions)
   the *entry* population is bounded above by ≈ 31 episodes before any conditioning
   on `open ∧ safe-OFF ∧ ¬caps`. Against the N_sub ≥ 200 required by §5.3 this is
   roughly an order of magnitude short.
2. **Structural degeneracy of its safe-OFF.** Its dominant OFF trigger is
   `seconds_to_window_close < 30` — a deterministic *clock boundary*, not a regime
   transition. Deferring the flatten there means holding into the closing auction:
   precisely the terminal-slippage regime the alpha's own `min_seconds_to_close`
   parameter exists to avoid, and where `session_flatten` binds within seconds. The
   §2.1 conditional-tail question is close to degenerate for this alpha, and the
   deferral window is nearly empty in event-time.

**Pre-declared reading:** a null or under-powered SCHEDULED_FLOW result is **not
evidence against Claim B**, and equally **not evidence for it**. It will be reported
as UNDERPOWERED with the episode counts, and excluded from the verdict arithmetic.

### 1.3 Alphas excluded, with cause

| Alpha | Family | Half-life | Exclusion |
|---|---|---|---|
| `sig_inventory_revert_v1` | `INVENTORY` | 20 s | §2.8 short-half-life; family `max_hold` multiple is **1×** ⇒ ceiling 20 s. Essentially no deferral window exists. |
| `sig_hawkes_burst_v1` | `HAWKES_SELF_EXCITE` | 30 s | Same: 1× multiple ⇒ 30 s ceiling. Excluded from mercy by §2.8 reasoning. |
| `sig_benign_midcap_v1` | `KYLE_INFO` | 120 s | Same family as the primary but 5× shorter half-life; the primary strictly dominates it as a residual-harvest candidate. |

---

## 2. Frozen configuration — DO NOT RE-TUNE

These values are frozen as of this commit. §7 records the commitment not to move
them.

### 2.1 Primary — `sig_kyle_drift_v1`

```yaml
safety_exit_policy:
  mode: decouple_caps_only          # arm B; arm A is mode: gate_close_flat
  max_hold_after_safe_off: 600      # seconds
  hard_exit_age_seconds: 1800       # seconds
```

| Field | Frozen value | Legal ceiling | Justification for the chosen value |
|---|---|---|---|
| `max_hold_after_safe_off` | **600 s** | 1800 s (3× half-life, `KYLE_INFO`) | One half-life, i.e. the point at which the mechanism's own declared decay has consumed 50 % of the residual, and **two** alpha horizons (2 × 300 s). Deliberately **not** the legal maximum: holding 6 horizons past safety-OFF would be holding long past the window in which the alpha claims any edge, which would inflate the wrong-hold population and bias the study *against* Stage 0 rather than toward a clean read. |
| `hard_exit_age_seconds` | **1800 s** | — | 3 half-lives / 6 horizons from open. Chosen so that the age backstop is *not* normally the binding cap — the object of study is the deferral clock, and a tight age cap would mask it. It remains a real backstop: it binds for any position opened more than 1200 s before its first safe-OFF. |

**Binding structure this produces (stated in advance).** With `max_hold` = 600 s from
first-safe-OFF and `hard_exit_age` = 1800 s from open, the deferral clock is the
binding cap whenever safe-OFF arrives before t+1200 s of the position's life, and the
age backstop binds after that. §6.3 reports the realized split; §5.4 makes a minimum
deferral-binding share a *precondition* of GO so that a study in which some other cap
almost always fires first cannot be read as evidence for Stage 1.

### 2.2 Secondary — `sig_moc_imbalance_v1`

```yaml
safety_exit_policy:
  mode: decouple_caps_only
  max_hold_after_safe_off: 240      # 1× half-life; legal ceiling 480 s (2×, SCHEDULED_FLOW)
  hard_exit_age_seconds: 480
```

Same 1× half-life logic as the primary, for comparability.

### 2.3 Cap inventory (the "other hard caps" in the §2.3 `min(...)`)

Declared now so that §6.3's "which cap fired first" accounting is against a fixed
list, not a post-hoc one:

| Cap | Source | Scope |
|---|---|---|
| `MAX_HOLD_AFTER_SAFE_OFF` | `risk/deferral_cap.py` | strategy slice |
| `HARD_EXIT_AGE` | `risk/deferral_cap.py` (token shared with `HazardExitController`) | strategy slice |
| `SESSION_FLATTEN` | `risk/deferral_cap.py` ← `core/session_clock.py` | strategy slice; **wall-clock backstop of last resort** (§2.3, §2.8) |
| Hazard spike | `risk/hazard_exit.py` (`RegimeHazardSpike`) | symbol-net — recorded separately when it pre-empts |
| Gate re-fire / error paths | `signals/horizon_engine.py` → `SafetyStateChange` → composer | strategy slice |

---

## 3. Frozen universe and data window

All non-empty symbol-sessions in `~/.feelies/cache/` as of this commit. Sessions
whose manifest reports `event_count == 0` (cached weekends/holidays) are excluded
as having no events, **not** as a data-quality judgment; SPY 2026-05-09
(`event_count == 2`, zero quotes) is excluded on the same non-discretionary rule
(no quotes ⇒ no NBBO ⇒ no snapshot can form).

| Symbol | Sessions | Dates |
|---|---|---|
| AAPL | 6 | 2026-03-13, 03-18, 03-26, 04-08, 04-09, 04-28 |
| APP | 14 | 2026-03-23, 03-26, 04-02, 06-01…06-05, 06-08…06-12, 06-29 |
| INTC | 1 | 2026-05-04 |
| MSFT | 1 | 2026-04-08 |
| NVDA | 1 | 2026-04-08 |
| SNDU | 2 | 2026-04-30, 05-01 |
| SPY | 5 | 2026-05-05, 05-06, 05-07, 05-08, 05-11 |
| TSLA | 1 | 2024-12-20 |
| **Total** | **31** | |

**Excluded (empty):** AAPL 2026-03-14; APP 2026-03-21, 03-22; SPY 2026-05-09, 05-10.

**Recorded caveat (not a filter):** three `event_schema_hash` values are present
across the cache (`8ff5342…` for most, `41de152…` for AAPL 03-18 / MSFT / NVDA
04-08, `60bde3f…` for TSLA 2024-12-20). Both A/B arms replay the *same* log per
cell, so schema heterogeneity cannot bias the A−B contrast; it is noted only
because it bears on cross-cell pooling.

---

## 4. Experimental design

### 4.1 The counterfactual

Replay is bit-identical (Inv-5) and the exit policy is a config-level mode, so the
two arms are run over the **same event log** per (symbol, session) cell:

- **Arm A — `mode: gate_close_flat`** (today's behavior): flatten immediately on the
  clean gate ON→OFF.
- **Arm B — `mode: decouple_caps_only`** (Stage 0): hold until the §2.3 `min(...)`
  deadline.

This is a perfectly controlled counterfactual: **no sampling noise between arms**.
Every A−B difference is attributable to the policy, not to draw.

### 4.2 Fills

Modeled fills under `--inv12-stress` (**1.5× cost, 2× latency**) — *not* mid marks.
§3.5 requires this because the deferral tail is realized in the stressed exit. The
1.5× cost leg is applied by `research/decouple_gates.apply_inv12_cost_stress`; the
2× latency leg must already be reflected in the gross series by the fill model
(`core/inv12_stress.apply_inv12_stress` on the platform config) and is stamped as
provenance on the evidence record.

### 4.3 Subpopulation

`open ∧ safe-OFF ∧ ¬caps` — episodes in which, at the moment of the episode's
**first** `safe→OFF`, the strategy slice held a non-zero position and no hard cap
had already fired. One episode = one (strategy, symbol, session, first-safe-OFF)
tuple. Gate flicker within an episode does **not** create a second episode (§2.3
monotonic anchor).

### 4.4 Per-episode outcome

Realized PnL in **bps of notional**, measured from the episode's first-safe-OFF
timestamp to that arm's realized exit fill, direction-adjusted, net of Inv-12
stressed costs. The common anchor makes A and B like-for-like.

### 4.5 Estimation — purged CPCV

Not one in-sample pass. Frozen CPCV hyperparameters:

```python
CPCVConfig(n_groups=10, k_test_groups=3, label_horizon_bars=1, embargo_bars=3)
```

- Reconstructed paths = `C(9, 2)` = **36** ≥ the `decouple_cvar_min_folds` floor of 8.
- `embargo_bars=3` ≥ the `decouple_cvar_min_embargo_bars` floor of 1; set to 3
  episodes (not the floor) to purge serial correlation between temporally adjacent
  episodes inside a session.
- Requires N_sub ≥ 10 for the grouping to be defined; §5.3's power floor is far
  above that.

---

## 5. Pre-registered thresholds

### 5.1 CVaR level

**α = 0.10.** This is the platform's maximum legal level
(`GateThresholds.decouple_cvar_max_level = 0.10`) and is chosen deliberately as the
**most favorable legal choice for power**: for a given N_sub it yields the largest
effective tail sample. Stated plainly so it cannot be mistaken for tuning — a
shallower decile tail is the price paid, and the level will not be moved after
seeing results. A tail failure at α = 0.10 is a fortiori a failure at α = 0.05.

### 5.2 Evaluation horizon

**300 s** for the primary (the alpha's declared `horizon_seconds`); **120 s** for the
secondary. Recorded as `horizon_bars` provenance on the evidence record.

### 5.3 Minimum effective tail-sample — the UNDERPOWERED line

**effective_tail_sample = ⌊α · N_sub⌋ ≥ 20**, i.e. at α = 0.10, **N_sub ≥ 200
distinct subpopulation episodes**.

- 20 is the platform's locked `GateThresholds.decouple_cvar_min_tail_sample`, not a
  number invented for this study.
- The count is of **distinct episodes**, not CPCV paths — path multiplicity
  re-uses the same underlying observations and does not create power
  (`decouple_gates.effective_tail_sample` enforces exactly this).

**Below this line the result is UNDERPOWERED: it is not evidence either way, and it
is NOT a GO.** §3.5: "A tail falsifier that cannot be powered on the available
subpopulation blocks promotion — it does not default to accept."

### 5.4 The residual bar — what counts as "costly enough to justify a story map"

Decided now, as numbers. **GO requires all four.**

| # | Bar | Threshold |
|---|---|---|
| **B1** | **Ceiling magnitude.** Mean per-episode uplift of the hindsight-optimal exit over hold-until-cap, over the subpopulation, net of Inv-12 stressed costs. | **≥ 20 bps/episode** |
| **B2** | **Population dominance.** Population (b) uplift vs population (a)'s conditional left-tail damage. | **(b) uplift ≥ 2 × \|(a) CVaR₁₀ damage\|**, *and* (b) episode share > (a) episode share |
| **B3** | **Deadline surface.** Share of subpopulation episodes in which `MAX_HOLD_AFTER_SAFE_OFF` is the binding cap (not pre-empted by another cap). | **≥ 30 %** |
| **B4** | **Power.** Effective tail sample (§5.3). | **≥ 20** |

**Derivation of B1 = 20 bps/episode** (recorded so it is not a round number pulled
from nowhere). The alpha discloses one-way cost 6.5 bps ⇒ ≈ 13 bps round-trip ⇒
**≈ 19.5 bps round-trip under the 1.5× Inv-12 cost stress**. The platform's
turnover ceiling (`decouple_turnover_ceiling_ratio = 1.5`) permits a Stage-1 map to
burn up to **0.5 extra round-trips per episode** ≈ 10 bps of stressed cost. A real
map captures only a fraction of an oracle gap; at a **50 % capture** assumption —
already generous for exit-timing maps — the ceiling must be at least **2 × 10 = 20
bps/episode** for the map to pay for its own turnover. Below 20 bps/episode there is
no headroom for *any* real map, and the oracle number is the ceiling, not the
expectation.

---

## 6. What will be reported

Regardless of verdict, the report at `docs/research/stage0_residual_<date>.md` will
contain:

### 6.1 Population (a) — WRONG HOLDS

Episodes where holding-until-cap was worse than flatten-on-gate-OFF.
Reported as the **conditional left tail** (CVaR₁₀ of the A−B difference), **not the
mean** (§2.1). Plus, specifically:

> **The §2.1 test.** Are hold-through outcomes correlated with the regime transition
> the gate flagged — i.e. *is the reason we held the reason we should have left?*
> Reported per `off_condition` clause (`P(normal) < 0.4`, `spread_z_30d > 2.0`,
> `realized_vol_30s_zscore > 3.5`), since these are three different latent states and
> pooling them would hide a clause-specific failure.

### 6.2 Population (b) — MISSED EARLY STORY-DEATH

Episodes where a hindsight/oracle exit materially beat hold-until-cap. **This is the
only population that motivates Stage 1.** Bounded by a **hindsight-optimal exit**:
the direction-adjusted best realizable exit over all feasible exit timestamps in
`[first_safe_off, deadline]`, on the same stressed fill model. This is the
**CEILING** on what any real story map could earn *before* its own noise and
turnover costs — it is not an achievable number and will not be presented as one.

### 6.3 Mandatory diagnostics

- **Cap-binding split** — how often the deferral deadline actually binds vs another
  cap firing first, by reason code.
- **Event-time vs wall-clock gap** — quote-freeze episodes that reach
  `session_flatten`, and the realized overshoot past the nominal ceiling (§2.3: the
  bound is event-time; `session_flatten` is the wall-clock last resort).
- **Turnover delta vs baseline** (Inv-12) — realized round-trips, arm B / arm A,
  against the `decouple_turnover_ceiling_ratio = 1.5` platform ceiling.
- **N_sub and effective tail sample**, stated before any tail statistic.

---

## 7. Anti-fitting commitments

1. **The §2 config is frozen.** `max_hold_after_safe_off`, `hard_exit_age_seconds`,
   and the cap inventory will not be re-tuned after seeing outcomes. If a residual
   appears only under some *other* ceiling, that is recorded as a NO-GO with a
   footnote — not re-run to a GO.
2. **α = 0.10 is frozen** (§5.1), as is the 300 s / 120 s horizon.
3. **No post-hoc universe subsetting.** The 31 sessions in §3 are the universe;
   symbols and sessions will not be dropped to improve a tail.
4. **No post-hoc bar movement.** B1–B4 (§5.4) are the bar. A result that lands just
   under a bar is a NO-GO, not a "directionally encouraging" GO.
5. **The oracle is a ceiling, not a forecast.** Population (b)'s hindsight number
   will never be reported as achievable edge.
6. **UNDERPOWERED is not GO** (§5.3), and will be stated as such.
7. **Stage-0 defects stop the study.** If a Stage-0 defect surfaces while measuring,
   it is reported and the measurement STOPS — it is not fixed inline, and a defective
   Stage 0 cannot be used to manufacture a residual.

---

## 8. Verdict rules (fixed in advance)

| Verdict | Condition |
|---|---|
| **GO** | B1 ∧ B2 ∧ B3 ∧ B4 all pass. Residual exceeds the bar, population (b) is materially larger than (a)'s tail cost, and the hindsight ceiling leaves real headroom after realistic map noise + turnover. |
| **NO-GO** | Power is sufficient (B4 passes) but any of B1–B3 fails. Per §4.2 this is an **expected and successful outcome**: Claim B is rejected, Claim A stands, and Stage 0 stands alone. |
| **UNDERPOWERED** | B4 fails (effective tail sample < 20). **Not a GO.** The report will state what additional data or universe breadth would be needed to power it. |

### 8.1 What REJECTS Claim B outright

Any one of these is sufficient to reject:

- **R1 — No headroom.** B1 fails: the hindsight ceiling is below 20 bps/episode.
  If the *oracle* cannot clear a real map's turnover drag, no real map can.
- **R2 — Wrong residual.** Population (a)'s conditional tail damage ≥ population
  (b)'s ceiling. The residual is then *wrong holds*, not *missed story-death*. The
  correct response is a **tighter Stage-0 ceiling**, not a story map — a map cannot
  fix a deferral that is too long.
- **R3 — No surface.** B3 fails: the deferral deadline binds in < 30 % of episodes
  because another cap fires first. The Stage-1 mercy cell (`open ∧ safe OFF ∧ story
  ON ∧ ¬caps`) would then have almost no surface to act on, and any story map is
  decoration on a cell that hard caps already own.
- **R4 — §2.1 confirmed.** Hold-through outcomes are conditionally correlated with
  the flagged regime transition in the direction §2.1 predicts (worse outcomes
  precisely where the gate flagged), at CVaR₁₀ and in at least one `off_condition`
  clause. A story map reading the same microstructure state inherits that
  correlation — "the reason you want to hold is the reason you should leave." This
  rejects Claim B **and** flags the frozen Stage-0 ceiling for review.

---

## Document control

| Field | Value |
|---|---|
| Pre-registered | 2026-07-25, before any outcome series was computed (Inv-2) |
| Design revision | rev 5 (locked) |
| Primary pilot | `sig_kyle_drift_v1` (KYLE_INFO, 600 s) |
| Secondary pilot | `sig_moc_imbalance_v1` (SCHEDULED_FLOW, 240 s) — pre-declared expected-UNDERPOWERED |
| Frozen ceilings | primary 600 s / 1800 s; secondary 240 s / 480 s |
| CVaR | α = 0.10, horizon 300 s (primary) / 120 s (secondary) |
| Power floor | effective tail sample ≥ 20 ⇒ N_sub ≥ 200 |
| Residual bar | B1 ≥ 20 bps/episode; B2 ≥ 2×; B3 ≥ 30 %; B4 ≥ 20 |
| Report | `docs/research/stage0_residual_<date>.md` |
