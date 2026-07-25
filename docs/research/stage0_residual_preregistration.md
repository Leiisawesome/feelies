# Stage-0 Residual Measurement — Pre-Registration

**Status:** Pre-registered. Committed **before** any outcome data was touched (Inv-2).
**Purpose:** Fix, in advance, the design of the measurement that decides whether Stage 1
(the \(P^{\mathrm{story}}\) map + mercy cell) may be built at all.
**Authority:** `dual_permission_actuation_design.md` rev 5 — §2.1 (conditional-tail risk),
§2.3 (bounded deferral), §2.8 (half-life scoping), §3.5 (gates), §4.2 (non-claims);
staging law Inv-3 / Inv-4.
**Date:** 2026-07-25
**Branch:** `claude/stage0-residual-measurement-72mxlz`

---

## 0. What this document is for

The staging law says Stage 1 may only be built **after** Stage 0 is shown to leave a
costly residual. That makes the measurement adversarial to the feature: a residual
measurement run *after* seeing outcomes can always be made to produce one, by choosing
the deferral window, the tail level, or the bar. This document removes that freedom by
fixing every such choice now.

Everything in §2–§7 is frozen. §8 lists what is forbidden to change later.

Per design §4.2, **rejecting Claim B is an expected and successful outcome.** Stage 0
stands on its own; nothing downstream depends on a residual existing.

---

## 1. Data-availability disclosure (read first)

This is disclosed **before** any outcome measurement because it determines whether the
study defined below can be executed at all, and because disclosing it afterwards would be
indistinguishable from an excuse.

Inventory of replayable market data in this environment, as of 2026-07-25:

| Source | Status | Suitability for this study |
|---|---|---|
| `MASSIVE_API_KEY` | **Unset**; no `.env` present | `feelies backtest` exits with `ERROR: MASSIVE_API_KEY not set.` |
| `~/.feelies/cache/` (disk event cache) | **Absent** | No cached symbol-days to replay |
| `tests/fixtures/event_logs/synth_5min_aapl.jsonl` | Present — 3 000 quotes + 428 trades, **299.9 s**, one symbol | Seeded ±1-cent random walk with a fixed 1-cent spread (`tests/fixtures/event_logs/_generate.py`). No regime structure, no toxic states, no fat left tail. |
| `tests/fixtures/bt12/*_daily_returns.json` | Present — 240 "daily returns" per alpha | **Seeded Gaussian surrogates** (μ=0.006, σ=0.005), explicitly *"calibrated to clear the F-2 CPCV and DSR gates"* (`tests/fixtures/bt12/README.md`). Not replay-derived. |
| `docs/research/artifacts/*.json` | Census / frontier / boundary extracts | Aggregate research outputs, not replayable L1 event logs |
| `docs/research/artifacts/oq1_ws_quote_frames_APP_2026-07-10.jsonl` | 36 WS frames, ~seconds of APP | Far too short |

**Consequence.** The Step-2 A/B counterfactual requires replaying a real L1 event log
through the kernel twice under two `safety_exit_policy` modes. No such log exists here.
The two candidate substitutes are both disqualified *by construction, not by their
results*:

- **The 5-minute synthetic log** has no latent regime state. §2.1's entire question is
  whether hold-through is conditionally correlated with the regime transition the gate
  flagged. In a driftless random walk that correlation is zero by construction, and any
  measured tail would be a property of the seeded RNG. It would produce a number, and the
  number would mean nothing.
- **The bt12 surrogates** are seeded Gaussians *selected to pass the CPCV/DSR gates*.
  Feeding them to the CVaR gate would manufacture a PASS that reflects the fixture's
  calibration, not the alpha's behaviour.

Generating a longer synthetic log with our own generator has the same defect as the first
substitute, and worse: the residual would be a function of whatever regime dynamics I
chose to write into the generator. That is the "stretch to find a residual" failure mode
this pre-registration exists to prevent.

**Therefore:** the protocol below is registered in full and is executable the moment real
data is supplied (§9 states exactly what is needed). If it is executed against the
inventory above, the pre-registered verdict is **UNDERPOWERED** — see §7 — and that is
determined *now*, by §6's power floor, not after seeing any result.

---

## 2. Pilot alphas

### 2.1 Selection

Frozen half-life and family envelopes are platform constants
(`src/feelies/alpha/layer_validator.py`), not author choices:

| Alpha | Family | `expected_half_life_seconds` | `horizon_seconds` | Family `max_hold` multiple (§2.8) | Legal deferral ceiling |
|---|---|---|---|---|---|
| **`sig_moc_imbalance_v1`** | **SCHEDULED_FLOW** | 240 | 120 | 2× | **480 s** |
| **`sig_kyle_drift_v1`** | **KYLE_INFO** | 600 | 300 | 3× | **1800 s** |
| `sig_benign_midcap_v1` | KYLE_INFO | 120 | 120 | 3× | 360 s |
| `sig_hawkes_burst_v1` | HAWKES_SELF_EXCITE | 30 | 30 | 1× | 30 s |
| `sig_inventory_revert_v1` | INVENTORY | 20 | 30 | 1× | 20 s |

**Pilots: `sig_moc_imbalance_v1` (primary) and `sig_kyle_drift_v1` (secondary).**

**Justification from the mechanism taxonomy.** Design §2.8: *"Short half-life families
typically have little residual to harvest by the time the gate flips."* The platform
encodes this as a per-family deferral multiple. `sig_hawkes_burst_v1` (30 s) and
`sig_inventory_revert_v1` (20 s) carry a 1× multiple, giving legal deferral ceilings of
30 s and 20 s — shorter than a single horizon boundary for the Hawkes alpha and
comparable to one for the inventory alpha. There is essentially no window in which a
story map could act, which is exactly why §2.8 forbids Stage-1 maps below a per-family
floor. They are excluded, and their exclusion is a prediction of the design, not a
convenience.

`sig_moc_imbalance_v1` is the SCHEDULED_FLOW-class pilot: the longest-multiple
scheduled-flow alpha in the book, and the family the brief names. `sig_kyle_drift_v1` is
carried as secondary because it has the **longest legal deferral ceiling on the platform**
(1800 s) and therefore the largest possible window for a residual to appear. If no
residual exists at 1800 s of legal hold, none exists anywhere in the current book.

### 2.2 Pre-registered structural concern about the primary pilot

Stated now so it cannot be presented later as a post-hoc explanation of a null.

`sig_moc_imbalance_v1`'s `off_condition` is:

```
scheduled_flow_window_active < 0.5 or seconds_to_window_close < 30 or realized_vol_30s_zscore > 3.5
```

Two of the three OFF triggers are **deterministic schedule expiry**, not weather. Only
`realized_vol_30s_zscore > 3.5` is a genuine latent-state trigger. This has two
consequences that the analysis must respect:

1. **The populations are not exchangeable.** A benign schedule-expiry population pooled
   with a toxic vol-breakout population can mask a bad tail in the latter. §5.4 therefore
   **mandates stratification by OFF-trigger cause**, and §6's power floor applies **per
   stratum**.
2. **The mechanism's driver stops at window close.** SCHEDULED_FLOW is defined as *"known
   time-of-day flow window."* When the window ends, the flow ends. Holding past a
   schedule-expiry OFF is holding with the declared mechanism switched off, so residual
   edge in that stratum should be near zero *a priori*.

**Pre-committed prior (Inv-2).** I expect: (i) the schedule-expiry stratum to show a
near-zero oracle ceiling; (ii) `session_flatten` to pre-empt the deferral ceiling in a
large fraction of MOC episodes, because a window closing near the session close leaves
less than 480 s of session; and therefore (iii) NO-GO on the primary pilot. Recording this
in advance is what makes the eventual measurement a test rather than a narrative. If the
data contradicts it, the data wins.

---

## 3. Frozen configuration

**These values are frozen as of this commit and may not be changed to make a residual
appear.** Each is *derived*, not chosen — there is no free parameter.

### 3.1 `sig_moc_imbalance_v1` (primary)

```yaml
safety_exit_policy:
  mode: decouple_caps_only        # arm H; arm F uses gate_close_flat
  max_hold_after_safe_off: 480    # = 2 × 240 (per-family legal ceiling, §2.8)
  hard_exit_age_seconds: 600      # = horizon_seconds (120) + max_hold_after_safe_off (480)
```

### 3.2 `sig_kyle_drift_v1` (secondary)

```yaml
safety_exit_policy:
  mode: decouple_caps_only
  max_hold_after_safe_off: 1800   # = 3 × 600 (per-family legal ceiling, §2.8)
  hard_exit_age_seconds: 2100     # = horizon_seconds (300) + max_hold_after_safe_off (1800)
```

### 3.3 Why these exact numbers (removal of discretion)

- **`max_hold_after_safe_off` = the per-family legal ceiling.** Read off
  `_FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE[family] × expected_half_life_seconds`, both frozen
  at schema freeze. This is deliberately the setting **most favourable to Claim B** — the
  largest hold the platform will permit, hence the largest window in which a residual can
  exist. A NO-GO under the most favourable legal configuration is a strong result and
  cannot be dismissed as "the map was not given room." Choosing anything shorter would
  bias toward NO-GO; choosing anything longer is illegal at load (G17).
- **`hard_exit_age_seconds` = `horizon_seconds + max_hold_after_safe_off`.** The alpha's
  own claim horizon plus the full legal deferral window. This is the smallest value that
  guarantees the age backstop does not pre-empt the deferral ceiling for a position opened
  at a horizon boundary — which keeps the two caps separable so §5.6 can report which one
  actually binds. Any larger value would weaken the backstop for no measurement benefit.

### 3.4 Frozen cap inventory

Both arms run with an identical cap inventory; only `mode` differs.

| Cap | State | Note |
|---|---|---|
| `max_hold_after_safe_off` | **Active in arm H only** | Does not exist in arm F (which flattens at gate-OFF) |
| `hard_exit_age_seconds` (deferral-cap author) | **Active in arm H only** | `src/feelies/risk/deferral_cap.py` |
| `session_flatten` | **Active, both arms** | `rth_close_ns`; wall-clock backstop of last resort |
| `stop_loss_pct` | **Active, both arms — 0.01** | Platform default, `platform.yaml:86` |
| `HazardExitController` | **Inactive** | Opt-in; requires a PORTFOLIO alpha with `hazard_exit.enabled: true`. The pilots run single-alpha SIGNAL, so it is not wired. Recorded explicitly so the cap inventory is not overstated. |
| Toxicity envelope | **Inactive** | Not configured on either pilot |

Frozen run flags: `--inv12-stress` (1.5× cost, 2× fill latency), `PYTHONHASHSEED=0`.

---

## 4. Arms and the counterfactual

Replay is bit-identical (Inv-5) and the mode is a config flag, so the **same event log**
is run twice:

- **Arm F (baseline)** — `mode: gate_close_flat`. Flatten on the clean gate ON→OFF.
- **Arm H (treatment)** — `mode: decouple_caps_only` with §3's frozen ceilings.

There is **no sampling noise between arms**: identical inputs, identical seeds, identical
fills up to the first divergence point (the gate-OFF instant). Every difference is
attributable to the actuation policy. Both arms use **modeled fills under `--inv12-stress`**
— never mid marks. Design §3.5 requires this because the deferral tail is realized in the
stressed exit, which is precisely where mid marks flatter the hold.

**Subpopulation \(S\)** — the cell design §2.4/§3.5 names: episodes that are
`open ∧ safe-OFF ∧ ¬caps_hit` at the first `safe→OFF` of the episode. Episodes where a
hard cap had already fired are excluded; they are not decisions the deferral gets to make.

**Per-episode delta** (bps, net of stressed costs):
\[ \Delta_i = R^{H}_i - R^{F}_i \]

---

## 5. Analysis protocol

### 5.1 CPCV setup (frozen)

Estimated under **purged CPCV**, not a single in-sample pass (design §3.5).

| Parameter | Value | Rationale |
|---|---|---|
| `n_groups` | **10** | Conventional purged CPCV partition |
| `k_test_groups` | **2** | 20 % test per split → 45 splits |
| Reconstructed paths (`cpcv_fold_count`) | **9** = C(9,1) | Clears the locked `decouple_cvar_min_folds = 8` floor |
| `label_horizon_bars` | **L** (see below) | Purges overlapping evaluation windows both sides |
| `embargo_bars` | **L**, floor 1 | Clears locked `decouple_cvar_min_embargo_bars = 1` |

Episodes are ordered by `first_safe_off_ns`. **L** is the maximum number of episodes whose
evaluation windows overlap any given episode's window, computed **from event timestamps
only** — a count, not an outcome, so computing it does not breach Inv-2. Floor of 1.
Cross-symbol overlap is the binding case: same-symbol episodes cannot overlap (a slice is
open or flat), but concurrent episodes on different symbols share market-wide shocks,
which is exactly what the embargo guards against.

### 5.2 Evaluation horizon (frozen)

Both arms are marked over a **common** window opening at the episode's first `safe→OFF`
and running to `first_safe_off + max_hold_after_safe_off + horizon_seconds`; both arms are
flat and marked at realized stressed fills thereafter.

| Pilot | Evaluation window | `horizon_bars` |
|---|---|---|
| `sig_moc_imbalance_v1` | 480 + 120 = **600 s** | **5** (of 120 s) |
| `sig_kyle_drift_v1` | 1800 + 300 = **2100 s** | **7** (of 300 s) |

A common window is required: scoring each arm only to its own exit would compare a
short-horizon realization against a long one.

### 5.3 CVaR level (frozen)

**α = 0.05.** Within the platform ceiling (`decouple_cvar_max_level = 0.10`) and the
conventional reading of "conditional left tail." Note the direction of the trade-off,
fixed now: a *larger* α would halve the episode count needed for power. α is **not** to be
widened later to reach the power floor.

### 5.4 Mandatory stratification

Every statistic in §5.5–§5.6 is reported **separately** for:

- **Stratum W (weather)** — OFF triggered by `realized_vol_30s_zscore > 3.5` (MOC) or by
  `P(normal) < 0.4 or spread_z_30d > 2.0 or realized_vol_30s_zscore > 3.5` (kyle_drift).
- **Stratum X (expiry)** — OFF triggered only by schedule expiry
  (`scheduled_flow_window_active < 0.5` or `seconds_to_window_close < 30`). MOC only.

The power floor (§6) applies **per stratum**. Pooling is reported as a diagnostic only,
never as the basis for a verdict — §2.2(1).

### 5.5 The two populations

**(a) WRONG HOLDS** — \(\{i \in S : \Delta_i < 0\}\), episodes where holding to the cap
was worse than flattening at gate-OFF.

Reported as the **conditional left tail, not the mean** (§2.1): `CVaR₅(Δ)` over \(S\),
plus mean and total \(\sum_{i \in (a)} |\Delta_i|\).

**§2.1 correlation test (the load-bearing one).** Explicitly test whether hold-through
outcomes are correlated with the regime transition the gate flagged — *is the reason we
held the reason we should have left?* Operationally: compare `CVaR₅(Δ | stratum W)` against
`CVaR₅(Δ | stratum X)`. A materially worse tail in W is the "same latent state" failure:
weather and holdability projecting the same thing.

**(b) MISSED EARLY STORY-DEATH** — the only population that motivates Stage 1.

Bounded by a **hindsight-optimal exit**, which is the CEILING on what *any* causal story
map could earn, before its own noise and turnover costs. Two ceilings are computed:

- **\(U^{\text{boundary}}_i\) (PRIMARY).** Oracle exit restricted to the alpha's own
  decision cadence — horizon boundaries within `[safe_off, deadline]`, at stressed fills.
  This is the correct ceiling: a story map is evaluated at boundaries, so uplift available
  only *between* boundaries is not addressable by any map. **§6's bar is judged on this.**
- **\(U^{\text{event}}_i\) (DIAGNOSTIC).** Oracle exit at any bus event in the window.
  Reported to show how much of the apparent ceiling is sub-cadence timing luck.

Both are \(\geq 0\) by construction (hold-to-cap is in the oracle's feasible set), and both
restrict the oracle to **feasible** exits — real events, real stressed fills — so the
ceiling is not inflated by unattainable timing.

### 5.6 Also reported (Step-3 requirements)

- **Which cap binds**: frequency of `MAX_HOLD_AFTER_SAFE_OFF` vs `HARD_EXIT_AGE` vs
  `SESSION_FLATTEN` vs `stop_loss` as the terminal exit reason in arm H. If the deferral
  ceiling rarely binds, Stage 0's deferral is largely inoperative and Stage 1 has nothing
  to sit on.
- **Event-time vs wall-clock gap**: count and duration of quote-freeze episodes reaching
  `session_flatten`, via `feelies.forensics.decouple_backstop`. A position held past the
  session bound is a **defect**, not a datum (§1 STOP rule).
- **Turnover delta (Inv-12)**: realized round-trips arm H vs arm F, as
  `observed_ratio`, against the locked `decouple_turnover_ceiling_ratio = 1.5`.

---

## 6. Power floor (frozen)

**Minimum effective tail sample: 20 distinct episodes per stratum**, matching the locked
platform gate `GateThresholds.decouple_cvar_min_tail_sample = 20`. Using the platform's own
number prevents me from setting a laxer private bar; the measurement then speaks directly
to the promotion gate.

`effective_tail_sample = floor(α × |S|)` — the **distinct-episode** count, deliberately not
inflated by CPCV path multiplicity (each episode recurs across reconstructed paths but is
one underlying observation).

At α = 0.05 this requires:

\[ \lfloor 0.05 \times |S| \rfloor \geq 20 \implies |S| \geq \mathbf{400}\ \text{episodes per stratum} \]

**Below this floor the result is UNDERPOWERED and is not evidence either way** — neither
for Stage 1 nor against it. Design §3.5: *"A tail falsifier that cannot be powered on the
available subpopulation blocks promotion — it does not default to accept."* The same logic
runs in the other direction here: an underpowered null does not falsify Claim B.

Note that 20 tail observations is a *bare minimum* for an expected-shortfall estimate.
Results at or near the floor are to be reported as weak, with the estimate's fragility
stated.

---

## 7. Decision rules (frozen)

### 7.1 GO — build Stage 1

All four must hold, on the **primary ceiling** \(U^{\text{boundary}}\), per stratum:

| # | Condition | Threshold |
|---|---|---|
| **B1** | Power | \(\lvert S \rvert \geq 400\) in the stratum (§6) |
| **B2** | Ceiling magnitude | \(\overline{U^{\text{boundary}}} \geq 1.5 \times\) stressed round-trip cost |
| **B3** | (b) dominates (a) | \(\sum_i U^{\text{boundary}}_i \geq 2 \times \sum_{i \in (a)} \lvert \Delta_i \rvert\) |
| **B4** | Stage-0's own gate passes | `cvar_delta ≥ −decouple_cvar_tolerance` on the same run |

**B2 thresholds, computed now from the frozen `cost_arithmetic` blocks:**

| Pilot | One-way | Round-trip | ×1.5 Inv-12 stress | **B2 bar** |
|---|---|---|---|---|
| `sig_moc_imbalance_v1` | 6.0 bps | 12.0 bps | 18.0 bps | **≥ 27.0 bps/episode** |
| `sig_kyle_drift_v1` | 6.5 bps | 13.0 bps | 19.5 bps | **≥ 29.25 bps/episode** |

*B2 rationale.* A causal map captures only a fraction of a hindsight ceiling and pays for
its own false exits. Requiring the **ceiling** to clear the platform's own Inv-12 margin
(1.5×) over one full stressed round-trip is the weakest condition under which a realistic
map could still survive its costs. Clearing B2 is **necessary, not sufficient** — hindsight
ceilings are inflated by construction (they are an option on the running best exit).

*B3 rationale.* A real map cannot perfectly separate (a) from (b); it holds and exits on
the same latent state. A 2:1 margin is the minimum under which a map that misclassifies a
third of cases still nets positive.

*B4 rationale.* If Stage 0's own tail gate fails, the correct response is falling back to
`gate_close_flat` — not layering a story map on a deferral that should not be running. A
story map cannot rescue a Stage 0 that fails its own gate.

### 7.2 NO-GO — Claim B rejected; Stage 0 stands alone

Any of:

| # | Rejection condition | What it means |
|---|---|---|
| **R1** | \(\overline{U^{\text{boundary}}} \leq 0\) net of stressed costs | No residual **even with perfect foresight**. The strongest possible falsification: no map, however good, beats a non-positive ceiling. |
| **R2** | \(\sum_i U^{\text{boundary}}_i < \sum_{i \in (a)} \lvert \Delta_i \rvert\) | The harvestable residual is smaller than the damage the deferral drags along. |
| **R3** | `CVaR₅(Δ \| X) − CVaR₅(Δ \| W)` > one Inv-12-stressed round-trip cost | **The §2.1 failure.** The reason we held is the reason we should have left. A map keyed on the same latent state would hold precisely in the toxic cell — this rejects the *premise* of mercy, not merely its size. |
| **R4** | B1 met but B2 or B3 missed | A real but sub-threshold residual: measured, priced, and not worth the machinery. |

Per design §4.2 this is an **expected outcome and a successful result**, not a shortfall.
Claim A (bounded deferral) stands independently of Claim B; empirical rejection of a map
does not reject Stage 0.

**R3's materiality quantum.** R3 originally read "materially worse" without a number, which
left exactly the discretion this document exists to remove. It is fixed here — still before
any outcome data — as **one Inv-12-stressed round-trip cost** for the pilot (18.0 bps for
MOC, 19.5 bps for kyle_drift): a tail difference smaller than the transaction-cost quantum
is not economically material. R3 requires **both** strata powered to be computable; when
only one is, R3 cannot fire and its silence is recorded as *not computable*, never as a
pass.

### 7.3 UNDERPOWERED — not a GO

If `effective_tail_sample < 20` in a stratum, that stratum returns **UNDERPOWERED**. This
is **not** a GO and **not** a NO-GO; it is an absence of evidence, and it blocks Stage 1
just as surely as a NO-GO does (Inv-3: Stage 1 requires *shown* residual, and "not shown"
is the default state). The report must state what additional data or universe breadth
would power it (§9).

---

## 8. Anti-fitting commitments

Frozen at this commit. Changing any of these after seeing outcomes invalidates the study.

1. **`max_hold_after_safe_off` and `hard_exit_age_seconds` will not be re-tuned.** They are
   derived (§3.3), not chosen. Re-running with a longer window to make a residual appear is
   fitting the config to justify the feature.
2. **α will not be widened** from 0.05 to reach the power floor.
3. **The 400-episode / 20-tail floor will not be lowered**, and CPCV path multiplicity will
   not be substituted for distinct-episode count to inflate apparent power.
4. **The B2/B3 bars will not be moved** after seeing \(\overline{U}\).
5. **Strata will not be pooled** to reach power (§2.2, §5.4). Pooling W into X to clear 400
   episodes is precisely the manoeuvre that hides a toxic tail behind a benign majority.
6. **No synthetic or surrogate data will be substituted for market data** (§1). Neither the
   seeded random-walk log nor the bt12 Gaussian surrogates will be used to produce a
   residual number, and no new generator will be written for that purpose.
7. **The pilot set will not be swapped** after seeing results. If both pilots return NO-GO,
   that is the result; scanning the remaining alphas for one that produces a residual is
   multiple testing without a ledger.
8. **Stage-0 behaviour will not be modified during measurement.** If a Stage-0 defect
   surfaces, it is reported and the measurement **STOPS** — a defect invalidates the arm-H
   replay, and fixing it inline would mean measuring a system that was never reviewed.

---

## 9. What would be required to execute this study

Recorded now so the requirement cannot later be shaped to fit whatever data turns up.

1. **Credential + cache**: `MASSIVE_API_KEY`, or a populated `~/.feelies/cache/{SYMBOL}/{DATE}.jsonl.gz`
   disk cache (`src/feelies/storage/disk_event_cache.py`).
2. **Breadth**: ≥ 400 subpopulation episodes **per stratum, per pilot**. The episode rate
   per symbol-day is *not yet known* and must be measured first (§10).
3. **Order-of-magnitude sizing** (assumption stated, not measured): if the
   `open ∧ safe-OFF ∧ ¬caps` cell yields ~0.3–1 episode per symbol-day for a
   scheduled-flow alpha, 400 episodes needs roughly **400–1300 symbol-days per stratum** —
   about **20–65 trading days at a 20-symbol universe**, and more for stratum W alone,
   since vol-breakout OFFs are the rarer trigger. Stratum W is expected to be the binding
   constraint on the whole study.
4. **Universe breadth over calendar length**: episodes on distinct symbols on the same day
   are closer to independent draws than episodes on one symbol across days, but they share
   market-wide shocks — which is why §5.1's embargo is set from cross-symbol overlap.
   Breadth is the cheaper path to power; it is not a free one.

---

## 10. Pre-approved next step: the power scout

Before any outcome measurement, run a **counting-only** pass that reports, per pilot and
per stratum: number of episodes in \(S\); which cap binds; quote-freeze counts; and
`floor(0.05 × |S|)` against the floor of 20.

This touches **no outcome data** — it reads timestamps, gate-transition causes, and exit
reasons only — so it is Inv-2-safe, and it answers "is this powerable at all?" before any
tail statistic is computed. If the scout returns UNDERPOWERED, the study stops there and
no CVaR estimate is produced, which prevents an underpowered tail number from entering the
record where it could later be quoted as evidence.

---

## 11. Implementation

The protocol is executable; it must be run **where the data is** (a machine with
`MASSIVE_API_KEY` and a populated `~/.feelies/cache/`), not in a cloud session.

| Component | Path | Status |
|---|---|---|
| Decision engine (§7 rules, §6 power floor, frozen bars) | `src/feelies/research/stage0_residual.py` | Implemented, unit-tested |
| Rule tests (including "under-powered ⇒ UNDERPOWERED, never GO") | `tests/research/test_stage0_residual.py` | 31 tests green |
| Local runner — scout + arm materialization | `scripts/research/stage0_residual_measurement.py` | `--scout` implemented; `--full` gated (below) |

```bash
PYTHONHASHSEED=0 uv run python scripts/research/stage0_residual_measurement.py \
    --alpha sig_moc_imbalance_v1 --symbol APP NVDA AMD \
    --date 2026-03-02 --end-date 2026-04-30 --scout \
    --out docs/research/artifacts/stage0_residual
```

The runner never mutates a committed alpha spec: each arm runs from a temporary copy with
`safety_exit_policy` injected, so measuring an alpha cannot promote it as a side effect.
It refuses to start without `PYTHONHASHSEED=0` (Inv-5), and both arms run under
`--inv12-stress` by construction rather than by operator flag.

**`--full` is deliberately gated.** The two-arm PnL reconciliation and the hindsight-oracle
extraction have never been exercised against a real cache, and a silently-wrong extraction
would emit a confident, plausible GO/NO-GO. Since §10 makes the scout the gating step
anyway — a NO-GO on power means `--full` never runs — the extraction should be completed
and validated against a real short date range (reconciling arm-F/arm-H divergence points
and episode counts against the trade journal) before any verdict is recorded.

---

## Document control

| Field | Value |
|---|---|
| Pre-registered | 2026-07-25, before any outcome data was accessed |
| Frozen sections | §2–§8 (pilots, config, protocol, power floor, decision rules) |
| Design authority | `dual_permission_actuation_design.md` rev 5, §2.1 / §2.3 / §2.8 / §3.5 / §4.2 |
| Invariants engaged | Inv-2 (falsifiability before testing), Inv-3 (evidence over intuition), Inv-4 (decay is default), Inv-5 (deterministic replay), Inv-12 (cost realism) |
| Outcome | Report to `docs/research/stage0_residual_<date>.md` |
