<!--
  File:   docs/research/sig_inventory_fade_v1_formal_spec.md
  Status: hypothesis → candidate pending validation (Task 7 formal spec,
          2026-07-11). Selected candidate H2 per Lei's adjudication
          (prompt_pack_04 DISPOSITIONS 4). Edge re-derivation (§4,
          condition E) verdict: PROCEEDS CONDITIONALLY — the honest
          central estimate at pooled σ priors does NOT clear the 5.0 bps
          stressed anchor; support exists only in a pre-registered
          σ-conditional sub-stratum (benign windows on elevated-stratum
          days / higher-σ symbols). Task 8 step 1 decides; park rule
          pre-registered. NO data was examined in this task.
          RULING appended 2026-07-11 (Lei): E-flag
          proceed-with-park-rule-armed UPHELD with three binding
          tightenings (§15); CARD→SPEC deviation table added (§16);
          §14.3 wiring pre-step landed early as an approved exception
          (commit 6a3ac12, full gate battery green, no baseline moved).
          NO data was examined in this task either.
  Owner:  microstructure-alpha (spec) / research-workflow (ledger);
          prompt-pack Task 7, Phase B.

  Provenance (FQ-3 template):
    git_sha: "f4cd256e25961ad40e97115fbd58631e6b414cf4"
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted analysis run in this task (design
      only; all numbers are priors, disclosure pins, or arithmetic on
      figures already recorded in the normative inputs)"
    normative_inputs:
      prompt_pack_04_hypothesis_slate.md (H2 card + DISPOSITIONS 1–5),
      prompt_pack_04a_slate_review.md (dossier verdicts + dispositions),
      artifacts/h2_h4_adjudication_package.md (§D.2 stressed floor),
      prompt_pack_03b_print_eligibility.md (§3.3 convention, §4.4
        netting, §2 prevalence, §6 guards — Amendment B),
      prompt_pack_03c_universe_and_cache.md (frozen grid, L1–L4, §7
        realized tick buckets, §3.1 median bids, §2 ADV table),
      prompt_pack_00b_edge_units_convention.md (one-way units, floor),
      prompt_pack_00c_eval_canon.md (pinned realism profile),
      prompt_pack_00e_strength_rider_and_thread.md (Track A rider),
      prompt_pack_03_data_contract.md (§7 L2-loss ledger),
      .cursor/skills/microstructure-alpha (SKILL.md, research-protocol.md),
      src/feelies (sensor sources, bootstrap wiring, gate engine,
        platform_config — read this session; citations inline).
-->

# `sig_inventory_fade_v1` — formal specification (Task 7)

Candidate H2, confirmed by Lei 2026-07-11 subject to binding conditions
E–J (Task 7 amendment block). This document is the complete formal
specification mapped onto the platform contracts; **no implementation
code ships with it** (the `evaluate` block in §5 is a normative draft
for Task 9). No forward return, IC, or any outcome statistic was
computed; every number below is a stated prior, a disclosure pin, or
arithmetic on figures already recorded in the normative inputs.

**Hypothesis (unchanged from the pre-registered card).** An impatient
uninformed seller (or their broker schedule — redemption, hedge,
deadline) demands immediacy in size because their mandate prices
completion above price improvement, forcing market makers to warehouse
inventory they do not want; capital- and variance-constrained MMs
concede price temporarily to shed it, which must leak into L1 as
one-sided inferred aggressor flow (trade prints) with *unstressed*
spreads, followed by reversion of the temporary concession.

Family `INVENTORY`; archetype **liquidity provision**; structural
counterparty: the urgency-constrained uninformed trader, whose binding
mandate funds the immediacy premium. `expected_half_life_seconds = 40`
(envelope 5–60 ✓); `horizon_seconds = 120`; ratio 3.0 ∈ [0.5, 4.0] ✓.

---

## 1. OBSERVABLE STATE

All sensors are **existing, registered** implementations (reference
config `platform.yaml`; no NEW sensor). As existing DI-09 sensors they
ingest every parseable print/quote — the 03b §3.3 print-eligibility
convention binds only NEW sensors, so **no condition filter is applied
at runtime** (changing that would touch locked parity baselines). The
consequences of DI-09 ingestion (auction lumps, correction-channel
residue) are handled by session-time discipline (§1.4) and evidence-time
contamination flags (§1.5), not by sensor changes. The pre-registered
condition-filtered NEW variant of `inventory_pressure` (which would
carry the full 03b §3.3 Class-A/B table, the id-12 DW parameter, and
`drop_correction_records = {10,11,12}` as explicit constructor
parameters, per Amendment B) remains **REGISTERED-UNEVALUATED
(N-impact: 0)** — Amendment I.

### 1.1 Sensor table (exact ids, params, warm-up, halt behavior)

| sensor_id | ver | feed | params (reference config) | warm rule | gap/halt behavior | units |
|---|---|---|---|---|---|---|
| `inventory_pressure` | 1.0.0 | Trade | `window_seconds=60`, `min_trades=20` (`platform.yaml:433-442`) | warm ⇔ ≥ 20 trades in trailing 60 s event-time window | no explicit flush param; the event-time deque evicts on the next post-gap trade, so a >60 s halt empties the window and the sensor un-warms on first post-halt print; during the silent gap the aggregator's horizon-staleness marks the feature stale at boundaries | dimensionless ∈ [−1, 1]; `Σ(−aggressor·size)/Σsize`; **positive ⇒ MM net long (absorbed net selling) ⇒ expected upward reversion** (`sensors/impl/inventory_pressure.py:25-31`). Aggressor = tick rule (`:33-36, 112-121`) — an L6 inference, never a label |
| `spread_z_30d` | 1.1.0 | NBBOQuote | `window=6000` quotes, `min_std=1e-9`, `max_gap_seconds=300` (`platform.yaml:254-267`) | warm after a full 6000-quote window (default `warm_after=window`) | **explicit halt flush**: an inter-quote gap > 300 s flushes the rolling distribution and the sensor re-warms against post-gap data (`sensors/impl/spread_z_30d.py:45-54`) | dimensionless z of quoted spread vs rolling count-window mean/std |
| `realized_vol_30s` | 1.3.0 | NBBOQuote | `window_seconds=30`, `warm_after=16` (`platform.yaml:420-429`) | warm ⇔ ≥ 16 log-returns in trailing 30 s | window-bounded length un-warms after gaps (S3); invalid/crossed quote resets the carry-forward mid | std of **per-quote** mid log-returns over the 30 s window (unannualised, quote-rate-dependent — see §5.2 for why this is NOT used to scale edge at runtime) |
| `quote_replenish_asymmetry` | 1.1.0 | NBBOQuote | `window_seconds=5`, `min_observations=20` (`platform.yaml:269-278`) | warm ⇔ ≥ 20 quotes AND ≥ 1 replenishment add on each side | invalid NBBO resets the reference sizes; thin tape cycles it warm/cold (see coverage note) | dimensionless ∈ [−1, 1]; positive ⇒ bid side replenishes faster; adds counted only at an unchanged best price (`sensors/impl/quote_replenish_asymmetry.py:129-141`) |

**Warm-coverage flags (design-stage, from 03c §5.1 counts — not new
measurement).** ENSG/DIOD trade at ~0.3–0.5 trades/s (7–13 k
trades/session), so `inventory_pressure`'s 20-trades/60 s warm gate is
*marginal* on the thin names — warm coverage per (symbol, session) is a
mandatory Task-8 report. `quote_replenish_asymmetry` (≥ 20 quotes/5 s)
will rarely be warm on thin tape (ENSG ≈ 0.15 quotes/s) — it is
therefore **confirmation-only** (F2, offline) and is deliberately kept
out of the entry-warm set (§1.3). `spread_z_30d` with `warm_after=6000`
quotes may warm late or never on ENSG/DIOD/MLI/PCTY (3–9 k
quotes/session) — retained as-is for the primary (entries suppressed
when cold is the correct fail-safe); a re-parameterisation
(`window=2000`) is drafted-not-evaluated (§13).

### 1.2 Horizon reducers consumed (feature_id keys, h = 120)

| feature_id | producer | status |
|---|---|---|
| `inventory_pressure` | `SensorPassthroughFeature("inventory_pressure", 120)` — last-of-horizon of the already-normalised value | **NEW WIRING REQUIRED.** `_HORIZON_FEATURE_FACTORIES` currently wires the passthrough **only at h=30** (`src/feelies/bootstrap.py:1247-1249`); at h=120 the snapshot carries no key and `evaluate()` cannot read it. Task 9 extends the factory to `h ∈ {30, 120}` (and corrects the stale comment claiming only 30 s is admissible for INVENTORY — h=120 with hl=40 is ratio 3.0, legal). Parity assessment pre-registered in §14. |
| `spread_z_30d` | `SensorPassthroughFeature` (bare feature id) | wired at all horizons (`bootstrap.py:1144-1146`) ✓ |
| `realized_vol_30s_zscore` | `RollingZscoreFeature` (count-window z) | wired at all horizons (`bootstrap.py:1348-1352`) ✓ — gate use only |
| `quote_replenish_asymmetry_zscore` | `HorizonWindowedFeature` zscore | wired (`bootstrap.py:1219-1226`) — **offline F2 use only**, never on the entry path |

Explicitly rejected: `inventory_pressure_percentile`. It is not wired
anywhere, the gate engine cannot resolve `*_percentile` identifiers
without a producing feature (they are unconditionally added to the
required-warm set, `bootstrap.py:1517-1519`, and the sensor-cache
fallback carries only raw sensor ids and declared tuple components,
`signals/horizon_engine.py:110-127, 726-756`), and a horizon-windowed
percentile of an already-[−1,1]-normalised value adds path dependence
with no mechanism content. The card was internally split (its
conditional-distribution claim used the **raw threshold ≥ +0.5**; its
gate sketch used a percentile); this spec fixes the **raw form** as
primary because the raw claim is the falsifiable object. The percentile
construction is drafted-not-evaluated (§13); evaluating it is +1 N.

### 1.3 Boundary semantics

`HorizonFeatureSnapshot` carries `values` / `warm` / `stale` **keyed by
feature_id**. Entry is suppressed unless every id in the alpha's
`required_warm_feature_ids` is warm and not stale; exits are permitted
when stale (conservative). The required-warm set is derived at
bootstrap from the statically-parsed `snapshot.values` keys the signal
body reads, intersected with features available at h=120, plus every
regime-gate identifier (`bootstrap.py:1477-1527`). For this alpha that
set is exactly:

    { inventory_pressure, spread_z_30d, realized_vol_30s_zscore }

`quote_replenish_asymmetry` stays in `depends_on_sensors` (G16 rule 5
requires the family fingerprint there) but its features are neither
read by `evaluate()` nor referenced by the gate, so the consume-driven
gating (audit 2P-1) keeps it out of the entry-warm set — thin-tape
warm-cycling of the 5 s quote window cannot starve entries.

### 1.4 Session-time discipline (Amendment I — explicit parameters)

`inventory_pressure` is volume-normalised and, as a DI-09 sensor,
ingests the auction/summary family — 56 prints carrying ~29 % of tape
volume on the 03b §2 scan — so windows overlapping the open/close
crosses take session-scale volume shocks from single events. Mitigation
is at the session gate, using the two shipped config knobs, **fixed
constants in `configs/bt_sig_inventory_fade_v1.yaml`** (not free-range
parameters; varying either is +1 N):

- `no_entry_first_seconds: 300` (`platform_config.py:171`) — no entries
  in the first 5 minutes: covers the 09:30:00 opening cross plus the
  O(1 min) arrival of MC Official Open re-prints (id 16/17). Arrival
  times were deliberately **not** measured (that would be data
  contact); 300 s is a pre-registered conservative constant.
- `session_flatten_enabled: true`, `session_flatten_seconds_before_close: 600`
  (`platform_config.py:342-347`, G-6) — entries blocked and positions
  flattened from 15:50 ET: no window overlapping the closing cross, no
  exposure to the 15:50 imbalance-dissemination information asymmetry
  (an H4 mechanism, a pure hazard here), and every H=120 s hold
  completes inside RTH.

These knobs layer on top of the pinned 00c realism profile; the Task-9
config guard records the instantiated snapshot checksum *including*
them (00c pinning method), so drift still fails the guard.

### 1.5 Evidence-time contamination flag (offline, deterministic)

The runtime sensor cannot see condition codes (parity). The **evidence
pipeline** can: Task 8 flags every horizon boundary whose trailing 60 s
sensor window contains any Class-B print (03b §3.3 exclusion set —
auction/summary/derived/late ids) or any `correction ∈ {10,11,12}`
record, reports the flagged fraction, and excludes flagged boundaries
from the primary estimate (reported both ways). Offline cache read,
PYTHONHASHSEED=0, no runtime behavior change.

---

## 2. LATENT-STATE INFERENCE

**Framing.** The unobserved quantity is the *composition of the flow
the MM just absorbed* — specifically the decomposition of the observed
conditioning-window mid dislocation `D` into a permanent (information)
component and a temporary (inventory/immediacy) component. In
Glosten–Milgrom terms the MM posts regret-free prices given their own
posterior `P(informed)`; the quoted spread *is* that posterior made
visible. The gate's `spread_z_30d ≤ 1.0` condition therefore reads the
MM's own revealed inference: an episode the market-making population
prices as low-adverse-selection. In Kyle terms, the permanent component
of `D` is `λ·Q_informed` and is unrecoverable; the strategy's payoff is
exclusively the temporary component, which reverts as inventory sheds
(hl = 40 s). We are not out-inferring the MM — we are piggybacking on
their inference and harvesting the slower, deeper tail of the
concession they cannot instantly absorb (the residual the card's R7
sketch identified).

**Cause mixture for the conditioning event**
`E = {|inventory_pressure| ≥ p₀ at a 120 s boundary, spread_z_30d ≤ 1.0,
P(normal) > 0.6, features warm}`:

| θ | latent cause | adverse? | failure shape | treated by |
|---|---|---|---|---|
| θ₁ | uninformed impatient liquidity demand (mandate/redemption/hedge/deadline) | no — this is the payer | — (the harvested case) | — |
| θ₂ | informed flow (private information, incl. pre-news positioning) | **yes** | **negative tail** — no reversion, continuation against the position, loss a multiple of the target edge | regime gate `off_condition` (vol-breakout posterior + spread + vol z), hazard exit, hard age cap; F3 monitors the residual |
| θ₃ | predatory flow pushing a detected constrained MM (and momentum ignition) | **yes** | **negative tail, adversarially timed** — deepening before any reversion, flip against induced entries | same runtime controls as θ₂; distributionally monitored via F2 (episodes without an MM re-quote footprint) and the F1 rolling-window clause |
| θ₄ | mechanical artifacts: auction/summary volume lumps, L6 mis-signing during fast tape, correction-channel residue | no trader at all | **edge dilution** — conditioning variable is noise, entries pay costs for nothing | session-time discipline (§1.4), evidence contamination flags (§1.5), warm gating; dilution needs measurement honesty, not exits |
| θ₅ | tick-grid bounce (half-tick mid oscillation read as reversion) | no | **edge dilution** — the artifact component pays nothing after costs by construction | §7 R8 stratification; OLN designated discreteness case |

The decision rule and hazard exit treat the two shapes differently by
design: tail components (θ₂/θ₃) get *state-dependent exits* (hazard
spike, gate-off FLAT, hard age) because holding through them is where
capital dies; dilution components (θ₄/θ₅) get *conditioning hygiene and
stratified measurement* because no exit can rescue an entry that never
had an edge — they must be kept out of the estimate, not traded around.

**What the posterior cannot resolve at L1 (loss-ledger tie).** Per
episode, informedness is undecidable — signing is tick-rule inference
that degrades exactly at burst moments (L6), and there is no trader
identity. The MM's actual inventory and capacity beyond the BBO are
never observed — "constraint binding" is inferred from prints and
replenishment behavior (L1). Hidden/midpoint liquidity absorbing the
flow without concession is invisible until it prints (L4). Queue
composition — whether our resting order is early or late at the level —
is unobservable (L2). Every one of these is resolved only
distributionally: the posterior over θ is a population claim tested by
F1–F3, never a per-trade classification.

---

## 3. PROCESS MODEL

**Named model: inventory-control mean reversion (Ho–Stoll 1981 /
Madhavan–Smidt 1991) — an OU-type exponential decay of the temporary
concession.** The state variable is the temporary component of the mid
dislocation created by absorbed one-sided flow; the MM's variance
penalty makes their quote-shading proportional to inventory, so the
concession decays exponentially as inventory sheds — pre-registered
half-life 40 s, i.e. mean lifetime τ = 40/ln 2 ≈ 57.7 s, nothing
economically left by ~3 hl = 120 s (the horizon). This is exactly the
sensor's own documented mechanism (`inventory_pressure.py:9-31`), so
model and observable are the same object. Task 8 validates the decay
shape via the IC(t) half-life fit (research-protocol Phase 5).

Against the shipped alternatives:

- **Hawkes self-excitation** (`hawkes_intensity` sensor,
  `scripts/calibrate_hawkes.py`): Hawkes describes the *loading* phase
  — clustered aggressive arrivals building the one-sided window — and
  its branching structure predicts *continuation*, which is precisely
  failure mode θ₂/θ₃, not the payoff. Adopting it as the process model
  would re-express the hypothesis as burst-following (that is H3,
  separately parked territory); here it survives only as a caution:
  elevated branching during an episode is evidence against the
  uninformed-reversion premise, not for it.
- **HMM / semi-Markov regime persistence** (`services/regime_engine.py`,
  `hmm_3state_fractional`, states `compression_clustering / normal /
  vol_breakout`): the HMM supplies the *conditioning stratum*
  (`P(normal)`, `P(vol_breakout)`), not the concession dynamics — its
  dwell times are the wrong clock for a 40 s reversion. Caveat carried
  verbatim from `platform.yaml:44-62`: with `transition_time_scaling`
  OFF (the default, protecting locked Level-5/6 baselines) the
  transition matrix applies once per inbound quote, so regime dwell is
  measured in *ticks* and drifts ~10× with intraday quote intensity.
  The gate is therefore treated as a conservative filter whose
  discriminability Task 8 must report per stratum (gate dwell in
  seconds, per symbol) — never as a calibrated dwell model.
- **Drift-diffusion** (`snr_drift_diffusion` sensor, dormant): DD
  separates persistent directional drift from noise — the right tool
  for KYLE-style permanent-impact detection, structurally wrong here
  because the signature of this mechanism is *negative* return
  autocorrelation (reversion), not sustained drift; a DD-framed version
  would be a momentum hypothesis and a different card.

---

## 4. EDGE RE-DERIVATION (Amendment E — condition of confirmation)

**Units (Amendment B / 00b, THE CONVENTION):** everything below is
**one-way, per-fill, in bps of fill notional**. Round-trip figures are
derived, never disclosed.

### 4.1 Recoverable-concession decomposition (mechanism-derived)

The per-episode conditional edge is the product of five named,
separately falsifiable factors:

    edge_ow  =  D × f_temp × f_surv × f_capt        (bps, one-way)
    D        =  c_D × σ₆₀                            conditional dislocation
    σ₆₀      =  σ₁₂₀ / √2                            diffusive scaling prior

| factor | meaning | honest range (prior, no data) | grounding |
|---|---|---|---|
| `c_D` | dislocation of the conditioning window in σ₆₀ units, given the ≥ p₀ one-sidedness tail | 0.5 – 1.0 (central 0.75) | conditioning on a strong one-sided 60 s window selects windows whose flow-driven move is a substantial fraction of local σ; > 1.0 systematically would contradict the *unstressed-spread* condition (a >1σ dislocation with calm spreads is rare by construction) |
| `f_temp` | temporary (recoverable) share of D in the benign-gated stratum | 0.4 – 0.7 (central 0.55) | GM/Kyle decomposition: the benign gate + unstressed spread shift the mixture toward θ₁ but never purify it; block-trade and inventory literature put the temporary share of uninformed institutional flow in this band; F2/F3 test it directly |
| `f_surv` | fraction of peak concession surviving to the boundary (episode peak occurs up to 60 s before the boundary; decay τ = 57.7 s) | 0.6 – 0.9 (central 0.75) | uniform peak-time over the window gives (τ/60)(1−e^{−60/τ}) ≈ 0.62; conditioning on high \|p\| **at** the boundary selects recent/ongoing flow, pushing the realized figure above the uniform bound — hence the asymmetric range |
| `f_capt` | reversion captured before the hard exit at 80 s (= 2 × hl, §5.4) | 0.75 (mechanical) | 1 − e^{−80/57.7} = 0.75; the 120 s variant (f_capt 0.875) is drafted-not-evaluated (§13) |

Composite capture coefficient κ = c_D × f_temp × f_surv × f_capt / √2:

    κ ∈ [0.06, 0.30],  central ≈ 0.16   ⇒   edge_ow ≈ κ × σ₁₂₀

This brackets and decomposes the card's pre-registered "0.15–0.3 ×
σ₁₂₀" — the card's band is the **optimistic half** of the honest band.
At the slate's pooled σ priors (σ₁₂₀ ≈ 16–22 bps):

    central:  ≈ 2.6 – 3.6 bps one-way
    band:     ≈ 1.0 – 6.6 bps one-way

### 4.2 Per-symbol cost floors (Amendment G — fee-in-bps table)

Passive (maker) execution: half_spread = 0; adverse selection 2.0 bps
(00c pin, LEVEL/drain); fee = min-commission floor `max(0.0035×80,
$0.35)` = $0.35 on the 80-share reference fill (top-of-book scale),
in bps of notional at the 03c §3.1 median RTH bid. Strict Inv-12
stressed floor per the adjudication package §D.2:
`floor = 1.5 × C_ow,stressed = 1.5 × 1.5 × (2.0 + fee) = 2.25 × (2.0 + fee)`.

| symbol | median bid ($) | fee (bps, 80-sh fill) | C_ow passive (bps) | stressed floor (bps) | deployable? |
|---|---|---|---|---|---|
| APP  | 615.05 | 0.07 | 2.07 | **4.66** | yes (anchor; the "≈ 5.0 bps" round figure) |
| ENSG | 182.94 | 0.24 | 2.24 | **5.04** | conditional |
| PCTY | 140.80 | 0.31 | 2.31 | **5.20** | conditional |
| MLI  | 130.62 | 0.33 | 2.33 | **5.25** | conditional |
| RMBS | 105.36 | 0.42 | 2.42 | **5.43** | conditional |
| CROX | 83.28  | 0.53 | 2.53 | **5.68** | conditional |
| DIOD | 57.50  | 0.76 | 2.76 | **6.21** | conditional |
| OLN  | 23.67  | 1.85 | 3.85 | **8.66** | **NO — excluded at design (Amendment G)** |

Notes: SELL legs additionally carry `cost_sell_regulatory_bps = 0.5` +
FINRA TAF (~0.007 bps at this scale) — OLN's all-in fee midpoint is the
adjudication's "~2.1 bps at its price point"; its stressed floor ~9 bps
either way. OLN is **excluded from the deployable/economic-viability
set at design but retained in the evidence set** for the §7 tick-
constraint artifact tests. The B4 runtime figure is quote-dependent and
can exceed these disclosure-arithmetic floors (00b qualification 1);
Task 8/9 re-verify against the modeled round trip at candidate size.

### 4.3 Verdict under the pre-registered bar (condition E)

Stated plainly:

1. **The honest central estimate at pooled σ priors (≈ 2.6–3.6 bps)
   does NOT support the ≥ 5.0 bps stressed anchor.** If the deployable
   claim rested on pooled-prior σ, the card would park here.
2. The derivation **does** support ≥ 5 bps in a pre-registered,
   mechanism-consistent sub-stratum: `edge ≥ floor_s` requires
   `σ₁₂₀ ≳ floor_s / κ` — at the central κ = 0.16, σ₁₂₀ ≥ ~29 bps
   (APP floor) — i.e. **benign intraday windows on elevated-stratum
   days and/or the higher-σ symbols**, where σ₁₂₀ runs well above the
   calm-pooled prior while the intraday `P(normal)`/spread gate still
   holds. This is exactly the distinction Amendment H forces (intraday
   HMM gate ≠ daily stratum), and it narrows the deployable region
   *before any data contact*.
3. **Ruling: the card PROCEEDS to Task 8, not on the central estimate,
   but on the pre-registered σ-conditional region — with the park rule
   armed.** Acceptance anchor: the Task-8 measured conditional edge in
   the deployable stratum must be ≥ the **per-symbol stressed floor**
   (table above; ≈ 5.0 bps on APP). If the measured stratum σ₁₂₀ and
   conditional edge cannot clear the floor on **any** grid symbol, the
   card parks exactly as H1 did — before implementation of anything
   beyond the Task-8 measurement itself. This ruling point is flagged
   for Lei's veto.

Consistency check against the confirmation: Lei confirmed H2 knowing
the ~5 bps stressed floor and that "viability rides on the realized
edge landing in the upper half of its target range" (adjudication
§D.2). This derivation reproduces that structure with the factors named
and falsifiable — it does not discover a new impossibility, and it does
not manufacture a new optimism.

---

## 5. DECISION RULE (platform terms)

### 5.1 Free-range parameters (≤ 3 — template discipline)

| param | type | default | range | meaning |
|---|---|---|---|---|
| `pressure_threshold` | float | 0.5 | 0.5 – 0.8 | p₀: minimum \|inventory_pressure\| at the boundary (raw units; the gate's fixed 0.5 arms evaluation, the param can only tighten) |
| `edge_scale_bps` | float | 10.0 | 4.0 – 16.0 | linear edge attribution per unit of normalised exceedance; **provisional pending Task-8 calibration** — the G12 disclosure uses the measured value |
| `edge_cap_bps` | float | 12.0 | 8.0 – 20.0 | hard cap on emitted `edge_estimate_bps` |

Fixed constants (not free-range, not tunable without +1 N):
`_MIN_EDGE_BPS = 5.0` (the stressed acceptance anchor, §4.3 — encoded
in the pure logic so entry requires posterior EV net of the stressed
cost stack > 0, never a bare threshold); the session-discipline knobs
(§1.4); the gate thresholds (§5.3).

### 5.2 `evaluate(snapshot, regime, params)` — pure logic (normative draft; Task 9 implements)

G5 purity: no imports, no I/O, no state; deterministic in its inputs.
Reads exactly two literal snapshot keys (so the consume-driven
required-warm derivation applies, §1.3).

```python
signal: |
  def evaluate(snapshot, regime, params):
      p = snapshot.values.get("inventory_pressure")
      if p is None:
          return None
      p0 = params["pressure_threshold"]
      mag = p if p >= 0.0 else -p            # no abs() needed; stays pure
      if mag < p0:
          return None

      # Normalised exceedance in [0, 1] by construction (sensor is
      # bounded in [-1, 1] and mag >= p0 here).
      excess = (mag - p0) / (1.0 - p0)

      # Posterior expected recoverable concession, linear proxy of the
      # section-4 derivation; calibrated by Task 8. Bounded above.
      edge_bps = min(params["edge_scale_bps"] * excess, params["edge_cap_bps"])

      # Entry only when posterior EV clears the stressed cost anchor
      # (5.0 bps one-way = 1.5 x stressed passive C_ow, spec section 4)
      # -- never a bare threshold. B4 additionally re-checks the
      # calibrated edge against the modeled round trip at runtime.
      if edge_bps < 5.0:
          return None

      # Fade the flow: p > 0 means MM absorbed selling -> revert UP.
      direction = LONG if p > 0.0 else SHORT

      # Strength rider (00e Track A): bounded by construction --
      # excess in [0, 1]; explicit clamps as belt-and-suspenders.
      strength = min(max(0.0, excess), 1.0)

      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="sig_inventory_fade_v1",
          direction=direction,
          strength=strength,
          edge_estimate_bps=edge_bps,
      )
```

Strength construction (Amendment C, 00e Track A rider adopted
verbatim): `strength = min(max(0.0, (|p| − p₀)/(1 − p₀)), 1.0)` —
non-negativity structural (entry requires |p| ≥ p₀ over a positive
denominator), upper bound explicit; emitted `strength ∈ [0, 1]` for
every reachable input. The convex above-saturation scaling of
`sig_benign_midcap_v1` is NOT available to this candidate. Task 9
gains the rider's two tests: (i) unit test asserting `strength ∈ [0,1]`
across the full declared parameter ranges (min and max of every
`parameters:` entry); (ii) a Hypothesis property test driving snapshot
values adversarially (NaN, ±inf, extremes, missing keys) asserting
`None` or in-range strength and non-negative finite
`edge_estimate_bps`.

Deliberately **not** in the runtime rule: σ-scaling via
`realized_vol_30s`. The sensor's value is the std of *per-quote*
log-returns (quote-rate-dependent, `realized_vol_30s.py` docstring), so
multiplying it into the edge would be dimensionally dishonest without a
quote-rate estimate. The σ-conditionality of §4 lives in Task-8
calibration of `edge_scale_bps` and in the deployable-set
determination; a runtime σ-scaled variant is drafted-not-evaluated
(§13).

Short-side caveat (00c profile): SSR modeling and HTB fees are inert on
the pinned profile — SHORT-side evidence (fading buy pressure) is
optimistic on those axes; carried into evidence interpretation.

### 5.3 Regime gate (AST DSL; hysteresis referenced, not dead config)

```yaml
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(normal) > 0.6
    and (inventory_pressure > 0.5 or inventory_pressure < -0.5)
    and spread_z_30d <= 1.0
  off_condition: |
    P(vol_breakout) > 0.3
    or spread_z_30d > 2.0
    or realized_vol_30s_zscore > 3.0
    or P(normal) < 0.6 - posterior_margin
  hysteresis:
    posterior_margin: 0.20        # >= 0.15 (G9); REFERENCED above
```

Notes: the DSL whitelists no function calls, so side symmetry is
written as an explicit disjunction (no `abs()`). `posterior_margin`
appears in the `off_condition` expression (the strict loader rejects
declared-but-unused margins as dead config — template `:99-104`); the
latch arms at `P(normal) > 0.6` and releases at `< 0.40`, satisfying
the ≥ 0.15 hysteresis requirement. `percentile_margin` is omitted (no
percentile binding — would be dead config). All gate identifiers
resolve from boundary-time snapshot values after the §1.2 wiring
(priority rule, `horizon_engine.py:726-756`); gates fail OFF on missing
bindings or non-discriminative posteriors (H8/M6 fail-safe, drift D8).
The `realized_vol_30s_zscore > 3.0` clause is the sensor-level
volatility backstop for the HMM's tick-based-dwell weakness (§3).

### 5.4 Hazard exit block

```yaml
hazard_exit:
  enabled: true
  hazard_score_threshold: 0.85     # controller default
  min_age_seconds: 30              # controller default
  hard_exit_age_seconds: null      # -> derived 2 x expected_half_life_seconds = 80 s
```

`RegimeHazardSpike` is an exit-direction hint only (Inv-11);
`HARD_EXIT_AGE` fires at 80 s (2 × hl, the platform derivation — audit
P1 HM-1), bounding θ₂/θ₃ tail exposure. Exits also fire on regime-gate
OFF (conservative FLAT close path) and are never blocked by B4
(`not is_exit_or_stop`). This is not a pure time stop: the age cap is
the *backstop* behind two state-dependent exits (hazard spike,
gate-off), and entry is EV-gated (§5.2). The `hard_exit_age = 120 s`
variant (capture 0.875 vs 0.75, §4.1) is drafted-not-evaluated (§13).

### 5.5 Cost arithmetic disclosure (G12; one-way per 00b)

Placeholder pinned to the acceptance anchor; **final values are the
Task-8 measured conditional edge on the deployable set** (disclosed
edge = the deployable-set minimum measured edge, conservative):

```yaml
cost_arithmetic:
  edge_estimate_bps: 5.0     # >= per-symbol stressed floor; Task-8 measured
  half_spread_bps: 0.0       # maker: no crossing
  impact_bps: 2.0            # passive adverse selection charge (00c pin), disclosed as impact per the passive convention
  fee_bps: 0.1               # commission floor at 80-sh scale, APP anchor (per-symbol table section 4.2)
  margin_ratio: 2.38         # 5.0 / 2.1; reconciles +/- 0.05 absolute
  # cost_basis: one_way (default; round_trip reserved -- never used)
```

Runtime: the B4 gate doubles the (calibration-factored) one-way edge
onto the round-trip basis against the modeled entry+taker-exit cost;
Task 9's config adopts the deployment `signal_min_edge_cost_ratio: 1.5`
(00c amendment). Sizing: top-of-book scale (≈ 80 sh reference,
`platform_min_order_shares = 50` respected); Sharpe-max declared —
size beyond displayed-depth scale forfeits the passive economics.

---

## 6. INVARIANCE CHECKS (≥ 2)

**I-1 (R5, zero-integrated-edge conservation — mandatory).** The
integrated edge must be payable out of temporary-impact costs paid by
impatient flow in the conditioned episodes. Design: over the full
regime-balanced evidence grid (calm + both elevated episodes), compute
(a) the funding pool `Σ_episodes D̂ × Q_episode` where `D̂` is the
measured conditional dislocation and `Q` the episode's one-sided
eligible volume, times the measured temporary share (F2-consistent
reversion fraction); (b) the strategy's integrated pre-cost conditional
edge at its declared participation (≤ 80 sh per episode against
episode volumes that are O(10³–10⁴) sh on this universe — participation
share O(1–10 %)). **Pass:** (b) ≤ participation share × (a) within
estimation error. **Fail (misattribution):** integrated edge exceeding
what the counterparty's temporary-impact spend can fund — the edge, if
real, is coming from something unnamed, and the card is wrong even if
profitable. Companion directional check: unconditional forward returns
over matched boundaries must integrate to ≈ 0 in the same sample (no
ambient-drift subsidy); the conditional edge must be *paid by the
conditioning event*.

**I-2 (side symmetry).** The mechanism is side-symmetric: the
conditional edge on fade-long (p ≥ +p₀) and fade-short (p ≤ −p₀) must
agree within sampling error in the benign stratum. A persistent
asymmetry beyond noise ⇒ contamination (ambient drift leakage,
short-side constraint artifacts, or signed L6 bias) — investigate
before any deployment claim; the SHORT side additionally carries the
§5.2 SSR/HTB optimism caveat.

**I-3 (episode-volume invariance).** `inventory_pressure` is
volume-normalised, so the conditional edge must not concentrate in the
extremes of the episode-volume distribution: an effect present only in
tiny-volume windows is small-sample noise; one present only in
huge-volume windows is event/auction contamination (θ₄). Report the
conditional edge by episode-volume tercile within the benign stratum;
monotone collapse at either extreme is a red flag, not an automatic
kill (research-protocol Phase 4 discipline).

---

## 7. TICK-CONSTRAINT ARTIFACT ANALYSIS (R8; Amendment D)

**Does the state-variable definition survive a tick-regime shift?
Yes — the definition; only parameters may need re-estimation.**
`inventory_pressure` is built from trade signs and sizes,
volume-normalised and dimensionless — no price-grid quantity enters the
sensor. What is grid-exposed is the **outcome measurement**: the 120 s
forward mid log-return is quantized in half-tick units of the mid.

**Grounding in realized buckets (03c §7, binding recompute):** APP 61 /
ENSG 48 / PCTY 30 / RMBS 22 / MLI 20 / DIOD 18 ticks pooled median =
wide/unconstrained; CROX 11 = moderate; **OLN 2 (per-session 2–4) =
discrete/near-constrained — the designated discreteness case for
failure mode 1** (half-tick bounce masquerading as reversion). On OLN a
half-tick mid move is 0.5 × $0.01 / $23.67 ≈ **2.1 bps** — the same
order as the central edge estimate, so grid bounce alone can mimic the
entire claimed effect there.

**Explicit test design (pre-registered):**

1. Report the spread-in-ticks distribution **at signal boundaries**
   (not pooled) per symbol — conditioning may select grid states the
   pooled medians hide.
2. **≥ 4-tick-stratum re-derivation:** re-estimate the conditional
   120 s forward return using only boundaries whose prevailing spread
   ≥ 4 ticks (all wide-bucket symbols and CROX qualify structurally;
   OLN contributes almost none by construction). The mechanism claim
   survives only if the ≥ 4-tick-stratum edge is consistent with the
   full-sample estimate; a collapse ⇒ the pooled effect was grid
   artifact (θ₅ dilution) and the card's economics must be restated on
   the surviving stratum.
3. **OLN quantum test (separates persistence from grid discreteness):**
   on OLN, compare the distribution of conditional 120 s mid moves
   against the ±1-half-tick quantum: if the conditional "reversion"
   mass sits at exactly ±1 half-tick (≈ ±2.1 bps) with no continuous
   tail beyond it, OLN's apparent effect is bid-ask grid bounce;
   genuine inventory reversion must show mass beyond one quantum and
   agreement (in σ-normalised units) with the wide-bucket estimate.
   OLN is evidence-set-only (Amendment G) — this test is its purpose.
4. **Parameters vs definition:** across buckets, p₀ and
   `edge_scale_bps` may legitimately differ (re-estimate); if the
   *sign* of the conditional effect differs by bucket after the quantum
   correction, that is definition-level failure (kill — see §10,
   tick-constraint axis).
5. **Scheduled boundary (pre-registered):** the SEC Rule 612 half-penny
   tick regime (compliance deferred to first business day of Nov 2027)
   halves the grid and migrates symbols down-bucket — any sample
   spanning it splits hard at that date; never pool across. MDI
   round-lot reassignments (semiannual, per symbol/effective date) are
   likewise declared boundaries for the size-denominated diagnostics.

---

## 8. L2 LOSS LEDGER (signal-specific instantiation of data contract §7)

| row | bite on this signal | treatment adopted (one sentence) |
|---|---|---|
| L1 depth beyond BBO | "MM inventory constraint binding" is inferred, never observed | Treated as a latent-cause prior only (§2); sizing is capped at top-of-book scale (≈ 80 sh) so no beyond-BBO liquidity claim is made, and forced exits inherit the platform's capped walk-the-book impact (`cost_max_impact_half_spreads = 4.0`, stop depletion 2.0). |
| L2 queue composition / position | passive fills are conditionally adverse — filled exactly when reversion fails, unfilled when it is instant | Adopted as **first-class** (Amendment F, §11): the platform's seeded-Bernoulli fill hazard (`passive_queue_position_shares = 200`, `passive_fill_hazard_max = 0.5`, delay 3 ticks) is the probabilistic model, and its conservatism is *tested*, not assumed, via the §11 sensitivity grid and fill-mix diagnostics. |
| L3 venue fragmentation | displayed NBBO ≠ single-venue accessible size; fee economics blended | Accepted as systematic noise under the flat blended maker/taker fee pins; no per-venue claim is made anywhere in this spec (no feature dropped — none was proposed). |
| L4 hidden/midpoint liquidity | hidden absorption removes the concession without a print — dilution | Treated distributionally: no per-episode hidden-liquidity claim; the through-fill displayed-size cap is conservative for our passive fills, and `trade_through_rate` remains available as an offline diagnostic of inside/through print prevalence per stratum. |
| L5 cancel attribution | `quote_replenish_asymmetry` (F2 confirmation) conflates MM repricing, venue churn, and spoof-shaped flow per event | Confirmation is **distributional only** — F2 compares episode-conditional asymmetry against its 30-day IQR baseline, never classifies a single quote event; the observable is kept off the entry path entirely (§1.3). |
| L6 aggressor signing | tick-rule misclassification concentrates in fast one-sided tape — exactly the conditioning moment — diluting the conditioning variable itself | Inherited and priced: no per-print informedness claim; adverse selection is charged flat-by-fill-type (2.0/5.0 bps pins); Task 8 reports a sign-stability diagnostic (tick-rule vs quote-position-of-print agreement, offline) per stratum so L6 dilution is measured rather than assumed away. |
| L7 latency microstructure | none claimed | 20 ms visibility + 50 ms fill = 70 ms ≈ 0.2 % of the 40 s half-life — no latency edge asserted; zero-latency configs are invalid for evidence (00c decision A). |

---

## 9. REGIME HONESTY (Amendment H)

The universe decision's limitations, **verbatim** (03c §2), as they
bind this design:

- "L1: calm stratum = ONE episode; calm-regime conclusions are evidence
  about calm-as-realized Dec-2025/Feb-2026, not calm-in-general"
- "L2: calm dates 2026-01-26/01-27 are adjacent (deterministic redraw
  artifact of a contaminated late-Jan/early-Feb tail); effective calm
  diversity ~4 distinct weeks; benign for intraday horizons across the
  overnight boundary"
- "L3: shared-calendar + any-symbol screen over-represents jointly-quiet
  days; RMBS (highest trip rate, incl. during SPY's calmest stretch) is
  the most heavily conditioned subsample — per-symbol diagnostics must
  flag RMBS; its tick-bucket prior is provisional"
- "L4: elevated stratum spans two episodes ~4 months apart (mild
  Nov-Dec band vs severe April band incl. span rv20 max) — treat
  within-stratum heterogeneity as a feature, report per-window where
  sample permits"

Binding consequences: (i) the **intraday HMM `P(normal)` gate and the
daily calm/elevated strata are different objects** — the gate is a
quote-clocked intraday posterior (with the §3 tick-dwell caveat), the
strata are session labels; every Task-8 statistic is reported in the
2×2 of (gate state × daily stratum). (ii) Because §4.3's viability
region concentrates in benign-windows-on-elevated-days, **the evidence
plan commits to reporting benign-episode counts on elevated-stratum
days** per symbol and per elevated episode (Nov–Dec vs April, per L4) —
if that cell is empty, the deployable claim has no sample and the card
parks on power, not on a pooled average. (iii) Calm-stratum conclusions
carry the L1 qualifier verbatim in every downstream artifact. (iv) RMBS
results carry the L3 flag; its tick-bucket prior is provisional
(03c §7 resolved it wide, but the diagnostic flag stands).

---

## 10. KILL CONDITIONS (per regime axis: parameters vs definition, as the platform triple)

For each axis: what a shift breaks; then the three artifacts the
platform consumes — `falsification_criteria` prose,
`failure_signature` clause (G16 rule 6 list), and the `regime_gate`
`off_condition` term where run-time gating is the right control.

| axis | shift → breaks | falsification_criteria (prose) | failure_signature clause | runtime gate term |
|---|---|---|---|---|
| **Spread** | transient widening → MM stress, passive economics invalid (**gate**, not kill); persistent level/bucket migration → **parameters** (re-estimate floors, p₀); a spread regime where the fade sign flips within the *benign* stratum → **definition (kill)** — the unstressed-spread ⇒ uninformed-flow premise is wrong (F3) | "sign(conditional 120 s forward return) reverses across spread_z_30d terciles within the benign stratum" | `"sign of conditional forward return reverses across spread_z_30d terciles within the benign stratum"` | `spread_z_30d > 2.0` |
| **Volatility** | vol_breakout episodes → informed-flow dominance (**gate**); secular σ-regime change → **parameters** (edge_scale re-calibration per §4's κ·σ structure); reversion→continuation sign flip inside the benign stratum → **definition (kill)** | "conditional forward return in the P(normal) > 0.6 stratum turns to continuation (mean ≤ 0 with sign agreement ≤ 0.50) over any 20-session window" | `"benign-stratum boundaries with \|inventory_pressure\| > 0.5 show 120 s forward-return sign agreement <= 0.50 over any rolling 20-session window"` | `P(vol_breakout) > 0.3 or realized_vol_30s_zscore > 3.0` (+ hysteresis `P(normal) < 0.6 - posterior_margin`) |
| **Liquidity** | MDI round-lot reassignment / depth-scale change → **parameters** (sizing scale, fee-in-bps table); disappearance of the MM re-quoting footprint during episodes → **definition (kill)** — flow without warehousing refutes the mechanism (F2) | "quote_replenish_asymmetry unchanged from unconditional baseline (\|Δ\| below its 30-day IQR) during inventory_pressure episodes" | `"quote_replenish_asymmetry shows no episode-conditional deviation beyond its 30-day IQR across the evidence set"` | none — offline distributional test (L5: not decidable per event at runtime) |
| **Tick-constraint** | scheduled Rule 612 half-penny boundary (Nov 2027) → **hard structural split, pre-registered**; bucket migration of a symbol → **parameters**; failure of the §7 ≥ 4-tick re-derivation → **definition (kill on the affected stratum)** — the effect was grid bounce | "the conditional edge does not survive re-derivation on the spread ≥ 4 ticks stratum, or OLN's conditional move mass sits entirely at the ±1 half-tick quantum" | `"conditional edge on the >=4-tick spread stratum inconsistent in sign with the pooled estimate"` | none — measurement stratification, not gateable |
| **Scheduled-flow / news** | auction windows → **parameters/config** (session-time discipline, §1.4 — no entries in windows overlapping the open/close crosses); a change in auction/dissemination mechanics → declared structural boundary; edge concentrating *only* in scheduled-event-adjacent windows → **definition (kill)** — the counterparty would be event flow, not inventory-constrained MMs, a different (unregistered) hypothesis | "conditional edge concentrates in boundaries adjacent to scheduled events/auction windows and vanishes in the session interior" | `"conditional edge in session-interior boundaries indistinguishable from zero while auction-adjacent boundaries carry it"` | config: `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600` |

Plus the standing structural boundaries (F5, pre-registered once for
all cards): Rule 612 (above); MDI round-lot reassignments; the
2026-06 vendor quote-field population change — post-2026-04-27 sessions
inadmissible (03c amendment A), APP/2026-06-29 UNKNOWN-ID-flagged.

---

## 11. FILL-MODEL DEPENDENCY — FIRST-CLASS (Amendment F)

The card's economics live or die on passive-fill quality (L2). Binding
requirements on the evidence:

**(a) Passive-fill-quality diagnostics (every H2 evidence run reports):**

- **Fill-mix realism:** distribution of fill outcomes from
  `passive_fill_stats()` — level/drain vs through fills, partial-fill
  slices, `EXPIRED` (timeout-cancel) rate, and time-to-fill
  distribution vs the 3-tick delay + hazard model; a fill mix dominated
  by through-fills means entries are being paid *because* the move is
  continuing (θ₂ signature at the execution layer).
- **Conditional adverse selection:** post-fill markouts at 40 s and
  120 s on *filled* signal boundaries vs the same conditional forward
  return on *unfilled* signal boundaries — the filled-minus-unfilled
  gap is the realized L2 selection cost; it must be consistent with (or
  better than) the 2.0 bps charged, else the charge is optimistic and
  F4 arithmetic is re-run with the measured figure.

**(b) Task-8 sensitivity grid (pass criterion = robustness across the
full grid):** 3 × 3 × 3 over the pinned profile —

| knob | pinned | grid |
|---|---|---|
| `passive_fill_hazard_max` | 0.5 | {0.25, 0.5, 0.75} |
| `passive_queue_position_shares` | 200 | {100, 200, 400} |
| `cost_passive_adverse_selection_bps` | 2.0 | {2.0, 3.0, 4.0} |

**Pass:** the F4 clearance verdict (measured net edge ≥ per-symbol
stressed floor) holds at **every** grid vertex on the deployable set.
A verdict that flips across the grid is simulator-dependence, and the
candidate is not execution-valid regardless of the pinned-profile
number.

**(c) Task 12 parity is a HARD GATE for any H2 evidence** — no number
produced before the router timing-parity check of Task 12 is presented
as a result (session constraint 5); the live-WS cancel/correction
dissemination row (03b §7.3 row 2) and the L7 ms-timestamp asymmetry
are Task-12 inputs.

**(d) F4 trap-quadrant clause, retained verbatim:** "F4 (execution
validity): pre-cost reversion exists but ≤ 1.5 × C_ow under the passive
realism model → `trap-quadrant`."

---

## 12. FALSIFICATION CRITERIA (consolidated, for the YAML)

- **F1 (forward test, honest-N):** bucketed conditional 120 s forward
  return after `|inventory_pressure| ≥ 0.5` in the benign stratum not
  significantly > 0 in the fade direction (RankIC / bucket
  monotonicity), or below the honest-N noise ceiling
  `expected_max_sharpe(n_trials=N, …)` with N from the living ledger →
  dead. Clause: `"benign-stratum boundaries with |inventory_pressure| >
  0.5 show mean 120 s forward return (fade-signed) <= 0 over any
  20-session window"`.
- **F2 (mechanism tie — MM re-quoting footprint):** warehousing must be
  visible distributionally. Clause: `"quote_replenish_asymmetry
  unchanged from unconditional baseline (|Δ| below its 30-day IQR)
  during inventory_pressure episodes"`.
- **F3 (regime-stratum sign stability):** clause: `"sign(conditional
  forward return) reverses across spread_z_30d terciles within the
  benign stratum"`.
- **F4 (execution validity):** §11(d) verbatim, evaluated per-symbol
  against the §4.2 stressed floors, across the §11(b) grid, only on
  Task-12-parity-cleared machinery.
- **F5 (structural boundaries):** the three pre-registered hard splits
  (§10 footer); never pool across.

Any DSR computed downstream uses the then-current ledger N
(`build_dsr_evidence(trials_count=N)`).

---

## 13. TRIAL LEDGER (Amendment J — drafted-not-evaluated; N unchanged)

Primary = slate trial **N-row 3** (H2 primary: `inventory_pressure`
60 s fade, H = 120 s, hl = 40 s, passive entry) — this spec is its
formalization, not a new trial. Every variant drafted here is
**drafted-not-evaluated**; evaluation anywhere increments N per the
binding FQ-6B-R rule (any data contact — including exploratory —
increments; drafting does not).

| variant drafted in this spec | status |
|---|---|
| percentile-conditioned gate form (`inventory_pressure_percentile > 0.90`) — superseded by the raw form (§1.2) | REGISTERED-UNEVALUATED (N-impact: 0) |
| `hard_exit_age_seconds = 120` (capture 0.875 vs 0.75) | REGISTERED-UNEVALUATED (N-impact: 0) |
| runtime σ-scaled edge (`realized_vol_30s`-normalised) | REGISTERED-UNEVALUATED (N-impact: 0) |
| `spread_z_30d` re-parameterisation for thin symbols (`window=2000`) | REGISTERED-UNEVALUATED (N-impact: 0) |
| session-discipline constants varied (`no_entry_first_seconds`, `session_flatten_seconds_before_close`) | REGISTERED-UNEVALUATED (N-impact: 0 each) |
| condition-filtered `inventory_pressure` NEW sensor (03b Class table + id-12 DW + correction netting as constructor params) | REGISTERED-UNEVALUATED (N-impact: 0) — carried from the slate, Amendment I |

**N = 10 as of this task** (unchanged; no data contact occurred).

---

## 14. DELIVERABLES MAP (Task 9 builds; nothing implemented here)

1. `alphas/sig_inventory_fade_v1/sig_inventory_fade_v1.alpha.yaml` —
   schema 1.1 SIGNAL; blocks per §5; `depends_on_sensors:
   [inventory_pressure, quote_replenish_asymmetry, spread_z_30d,
   realized_vol_30s]`; `trend_mechanism: {family: INVENTORY,
   expected_half_life_seconds: 40, l1_signature_sensors:
   [quote_replenish_asymmetry, inventory_pressure], failure_signature:
   §10 clauses}`; `falsification_criteria:` §12.
2. `configs/bt_sig_inventory_fade_v1.yaml` — instantiated from the
   pinned 00c profile (checksum guard), deployment
   `signal_min_edge_cost_ratio: 1.5`, §1.4 session knobs, deployable
   symbol list (Task-8 outcome; OLN excluded).
3. **Bootstrap wiring:** extend the `inventory_pressure` entry of
   `_HORIZON_FEATURE_FACTORIES` to `h ∈ {30, 120}` (passthrough only)
   and fix its stale comment. **Pre-registered parity assessment:** the
   locked Level-3 snapshot baseline is fixture-local (ofi_ewma /
   micro_price only — `tests/determinism/test_horizon_feature_snapshot_replay.py`)
   and is not touched; reference-config runs gain one snapshot key at
   h=120, which no shipped alpha consumes (consume-driven required-warm
   sets are unchanged); Task 9 runs the full `tests/determinism/` and
   acceptance suites and treats **any** moved baseline as a blocking
   finding requiring architectural review — never a value edit.
4. Tests: Track-A strength/property tests (§5.2), gate-DSL compile
   test, config guard (latency > 0 + checksum), ≥ 80 % coverage on new
   code, mypy strict, ruff/DTZ clean. A task is not done while any gate
   fails.

---

## NEXT ACTION (one, concrete)

**Task 8, step 1 — power-and-floor census before any IC computation:**
offline deterministic scan of the frozen 80-cell grid
(PYTHONHASHSEED=0, direct `DiskEventCache` read) reporting, per
(symbol × session × daily stratum): boundary-eligible episode counts at
`|inventory_pressure| ≥ 0.5` under the full gate conditions, sensor
warm coverage (§1.1 flags), §1.5 contamination-flag rates, and the
realized stratum σ₁₂₀ — **no forward returns touched** — then apply the
§4.3 park rule arithmetic (`κ·σ₁₂₀ vs per-symbol stressed floor`,
benign-on-elevated cell counts per Amendment H) to fix the deployable
subset, or park the card, before a single IC number exists.
**As tightened by the §15 ruling:** κ = 0.16 frozen; floors at the
stressed adverse-selection vertex (§15(ii) table), viability across
the full adverse-selection axis; and the ≥ ~100-episode per-stratum
power gate per deployable symbol (§15(iii)).

*Task 7 stops here.*

---

## 15. RULING — E-FLAG (Lei, 2026-07-11): proceed-with-park-rule-armed UPHELD

The §4.3 verdict (proceed to Task 8 on the pre-registered σ-conditional
region, park rule armed) is **UPHELD**, with three binding tightenings.
These amend the §4.3 park-rule arithmetic and the NEXT ACTION census in
place; where they conflict with earlier text, this section governs.

**(i) κ_central = 0.16 FROZEN.** All park-rule arithmetic
(`κ·σ₁₂₀ vs floor`, the σ_min region bounds, the deployable-set
determination) uses κ = 0.16 and no other value. No upward
re-estimation of κ — of any §4.1 factor — is permitted after any data
contact: the derivation is now a one-way ratchet (it may be revised
*down* on evidence, never up). Once the census runs, the **measured
conditional edge supersedes the derivation entirely** — κ-arithmetic
exists only to fix the pre-data viable region and the park decision;
it is never quoted as a result afterward.

**(ii) Stressed adverse-selection floors, and σ-conditional viability
across the grid's adverse-selection axis.** The §4.2 floors were
computed at the pinned 2.0 bps passive adverse-selection charge. For
park-rule and census purposes the per-stratum floor uses the
**stressed** adverse-selection value — the top of the §11(b) grid axis
(4.0 bps): `floor_s = 2.25 × (4.0 + fee_s)`. σ-conditional viability
must hold across the full adverse-selection axis {2.0, 3.0, 4.0}; the
4.0 vertex is binding. Derived table (disclosure arithmetic only,
κ = 0.16 frozen):

| symbol | fee (bps) | stressed-AS floor (bps) | σ₁₂₀ min = floor/κ (bps) |
|---|---|---|---|
| APP  | 0.07 | 9.16  | ≈ 57 |
| ENSG | 0.24 | 9.54  | ≈ 60 |
| PCTY | 0.31 | 9.70  | ≈ 61 |
| MLI  | 0.33 | 9.74  | ≈ 61 |
| RMBS | 0.42 | 9.95  | ≈ 62 |
| CROX | 0.53 | 10.19 | ≈ 64 |
| DIOD | 0.76 | 10.71 | ≈ 67 |
| OLN  | —    | —     | excluded (Amendment G) |

The §4.2 table (2.0 bps vertex) remains the *unstressed* reference;
both are disclosure arithmetic, and the Task-8 measured stratum σ₁₂₀
and conditional edge supersede both per (i). Additionally, the I-1
zero-integrated-edge invariance check must test **high-σ edge against
high-σ adverse selection explicitly**: the funding-pool comparison in
the viable (high-σ) stratum is computed with the stressed
adverse-selection charge for that same stratum — never a high-σ edge
funded at pooled/calm adverse-selection assumptions.

**(iii) The census is a POWER gate.** The viable region (σ-conditional
benign-on-elevated cells per §4.3/§9) must contain at least the
research-protocol minimum per-stratum sample — **~100
boundary-eligible episodes** (research-protocol Phase 3, minimum
per-stratum sample rule) — **per deployable symbol**. A symbol whose
viable-region cell count is below the minimum is not deployable; if
no grid symbol clears it, the card **parks on power** before any IC
number exists, exactly as §9(ii) anticipated. INSUFFICIENT cells are
reported as such, never pooled away.

Everything else in the §4.3 ruling stands unchanged, including the
Lei-veto flag on the ruling point and the H1-style park path.

---

## 16. CARD→SPEC DEVIATION TABLE (logged, never silent)

Every place this spec deviates from the pre-registered H2 card
(prompt_pack_04 §H2), with the card's original noted. Prose rationale
lives in the cited sections; this table is the normative index.

| # | card (original) | spec (tested form) | where / why |
|---|---|---|---|
| 1 | conditioning & gate arm: `inventory_pressure_percentile > 0.90` | raw threshold: `\|inventory_pressure\| ≥ 0.5` at the boundary | §1.2 — the card was internally split (its conditional-distribution claim already used raw ≥ +0.5; only the gate sketch used the percentile); the raw claim is the falsifiable object; percentile is unwired and adds path dependence. Percentile variant REGISTERED-UNEVALUATED (§13). |
| 2 | F1 clause: `"inventory_pressure_percentile > 0.90 boundaries in P(normal) > 0.6 stratum show mean 120 s forward return <= 0 over any 20-session window"` | F1 tested in spec form: `"benign-stratum boundaries with \|inventory_pressure\| > 0.5 show mean 120 s forward return (fade-signed) <= 0 over any 20-session window"` | §12 F1 — follows deviation 1; fade-signed makes the direction convention explicit (card's clause was long-side-worded). |
| 3 | hysteresis: `{posterior_margin: 0.20, percentile_margin: 0.30}` | `posterior_margin: 0.20` only | §5.3 — no percentile binding remains after deviation 1; a declared-but-unused margin is dead config the strict loader rejects. |
| 4 | off_condition: `"P(vol_breakout) > 0.3 or spread_z_30d > 2.0"` | adds `realized_vol_30s_zscore > 3.0` and `P(normal) < 0.6 - posterior_margin` | §5.3 — sensor-level backstop for the HMM tick-dwell weakness (§3) + the hysteresis release the loader requires referenced. |
| 5 | edge magnitude: `0.15–0.3 × σ₁₂₀ ≈ 3–6 bps at the priors` | honest band `κ ∈ [0.06, 0.30]`, central 0.16 (frozen per §15(i)) ⇒ central ≈ 2.6–3.6 bps at pooled priors | §4.1/§4.3 — the card's band is the optimistic half of the decomposed derivation; pooled-prior central does NOT clear the stressed anchor, hence the σ-conditional region + park rule. |
| 6 | universe: all 8 grid symbols implicitly in scope | OLN excluded from the deployable set at design (evidence-set-only, §7 quantum test) | §4.2 Amendment G — stressed floor ~9 bps vs the same-order half-tick quantum (≈ 2.1 bps). |
| 7 | auction-lump mitigation: "gate (no entries in windows abutting the auctions; Task-7 spec decision)" | fixed session constants `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600` + offline evidence-time contamination flags | §1.4/§1.5 — the card deferred the mechanism to this spec; constants pre-registered, not measured. |
| 8 | reducers: `inventory_pressure` "passthrough + percentile"; `quote_replenish_asymmetry` "last/mean" | `inventory_pressure` passthrough only (h ∈ {30, 120}); `quote_replenish_asymmetry` zscore, offline F2 only, off the entry path | §1.2/§1.3 — percentile per deviation 1; replenish-asymmetry warm-cycling on thin tape must not starve entries. |

No other substantive deviation exists; hypothesis text, family,
half-life, horizon, archetype, counterparty, F2–F5, and the failure-
mode set are carried unchanged.

*E-flag ruling and census gate setup stop here; Task 8 step 1 is next.*
