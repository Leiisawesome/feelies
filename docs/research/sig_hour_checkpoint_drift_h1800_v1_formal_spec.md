<!--
  File:   docs/research/sig_hour_checkpoint_drift_h1800_v1_formal_spec.md
  Status: hypothesis → candidate pending validation
          (Task 7 formal spec 2026-07-17; H13 ACTIVATED per pack-11
          DISPOSITIONS 7 — trigger (a) FIRED on H12 census park
          (power, n=59); Amendments A–H applied; κ frozen 0.172
          minimum-rule vs factor product 0.189; N = 12; zero outcome
          contact).
          POOL CONFIGURATION appendix appended 2026-07-17; Appendix P
          RULING (Lei, 2026-07-17) FROZEN pre-census: config (B),
          P.3 A-2.1 evidence-pool floor, honest expectation ≈96 /
          expected PARK; (C) REJECTED; zero ingestion. Task 8 next.
  Owner:  microstructure-alpha (spec) / research-workflow (ledger);
          prompt-pack Task 7, Phase B (H13 — final card).

  Provenance (FQ-3 template):
    git_sha: "476b70e5f22b73d9a9aba340add5a1ae24885bc0" (HEAD at Task-7
      start = H12 park close-out / H13 activation commit)
    worktree_clean: "yes at Task-7 start; appendix task appends only"
    pythonhashseed: "0 — appendix arithmetic from committed
      artifacts/horizon_feasibility_map_2026-07-11.json cells
      (ENSG/MLI σ₁₈₀₀ + floors); no new cache contact; no IC"
    normative_inputs (Amendment A):
      prompt_pack_11_hypothesis_slate_d.md (H13 card VERBATIM +
        DISPOSITIONS 1–8; H12 park / H13 activation),
      prompt_pack_11a_slate_d_review.md (κ 0.172 vs 0.189 bug;
        hour-only geometry 12 bounds/session = 6 in / 6 off;
        pool-collapse axis-split §2e; DECISION RECORD),
      sig_halfhour_clock_drift_h900_v1_result.md +
        sig_halfhour_clock_drift_h900_v1_validation_protocol.md
        CENSUS C.0–C.8 + artifacts/halfhour_clock_drift_census_2026-07-17.json
        (H12 census-legal arm-attrition — backlog 19 mandatory input),
      prompt_pack_08_frontier_refresh.md (OPERATIVE frontier; κ /
        floors / σ; Tranche-1B κ caveat),
      prompt_pack_10_cycle2_retrospective.md (cycle-3 FINAL stop-rule;
        outcome-informed prior disclosure),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.4 —
        quote-fed entry; no NEW trade-fed extreme),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2 /
        TRANCHE-1B: 140-cell inventory; APP/RMBS×20,
        OLN/DIOD/PCTY/CROX×20 ingested; ENSG/MLI×10
        DRAWN-NOT-INGESTED; L1–L5; HOLIDAY-THIN),
      prompt_pack_05_horizon_feasibility_map.md +
        artifacts/horizon_feasibility_map_2026-07-11.json
        (ENSG/MLI 10-session floors / σ₁₈₀₀ — appendix source),
      prompt_pack_00b_edge_units_convention.md (one-way),
      prompt_pack_00e_strength_rider_and_thread.md (Track A),
      prompt_pack_00c_eval_canon.md (pinned realism profile),
      prompt_pack_12p_router_fill_timing_parity.md (Task 12-P AXIS-1
        VERIFIED — hard gate cited, not re-run),
      prompt_pack_backlog.md entry 19 (arm-scoped percentile
        exemption; occupancy pre-reads mandatory),
      four frozen protocol precedents (inventory_fade,
        dislocation_lambda, sweep_kyle_h900, halfhour_clock_h900 —
        riders / structure only; never economic priors),
      src/feelies (scheduled_flow_window, WindowKind.ALGO_CLOCK
        landed by H12 Phase A, ofi_integrated_percentile factory
        over all h, hazard-exit, layer validator, regime gate —
        read this session; citations inline).
-->

# `sig_hour_checkpoint_drift_h1800_v1` — formal specification (Task 7)

Candidate **H13**, activated by Lei 2026-07-17 under pack-11
DISPOSITIONS 7 (trigger **(a)** — H12 design/census death / power
park). This document is the complete formal specification mapped onto
the platform contracts; **no implementation code ships with it** (the
`evaluate` block in §5 is a normative draft for Phase B / Task 9).
**No data contact occurred in this task** — no forward return, IC,
contamination intensity read, or new occupancy measurement. H12 census
figures appear only as **characterization priors** (Addendum-G /
Amendment G), never as H13 evidence.

**Hypothesis (unchanged from the pre-registered card).** Larger
institutional parents and desk-level participation caps are often
monitored on an **hourly** checkpoint grid (10:00, 11:00, … ET)
**because** schedule variance and VWAP benchmarks are reviewed on the
hour, **which must leak into L1 as** signed quote-flow pressure
concentrated on on-the-hour decision windows. Residual impact of
still-open parents continues over the next **H = 1800 s**. Binding
claim: matched flow extremes at **half-hour-but-not-hour** marks
(:30) must not produce the same continuation — otherwise the hour
checkpoint story collapses into generic half-hour / unclocked flow.

Conditional-distribution statement: at each in-window H = 1800
boundary (12/session), with `ofi_integrated` over trailing 1800 s and
`W_hr` = inside a registered `ALGO_CLOCK` **on-the-hour** window:

`E[mid log-return over next H = 1800 s | ofi_integrated percentile ≥ 0.80
AND W_hr AND P(vol_breakout) < 0.7] > 0` (symmetric short for ≤ 0.20),
magnitude κ_frozen × σ₁₈₀₀ with κ central ≈ **0.172** ⇒ ≈ **10.8 bps**
one-way at the APP median session (0.172 × 62.8).

Family `SCHEDULED_FLOW`; archetype **schedule-bound flow-following**;
structural counterparty: LPs and discretionary flow that under-react
between hourly reviews. Conservation: edge ≤ residual impact of open
scheduled parents across the hourly grid.
`expected_half_life_seconds = 900` (G16 envelope 60–1800 ✓);
`horizon_seconds = 1800`; ratio 2.0 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [scheduled_flow_window]` (G16 rule-5 primary;
`ofi_integrated` is the conditioner, not the family fingerprint).
Evidence / deployable set **frozen six-symbol pool**
{APP, RMBS, OLN, DIOD, PCTY, CROX} — roles from §4 park arithmetic,
not the map summary. ENSG/MLI remain median-closed under the 0.16-class
honest screen (Lei DECISION RECORD 1) and DRAWN-NOT-INGESTED.
Mirage: **MIXED (M = 1.5)**. Soft-σ caveat: σ₁₈₀₀ rests on 12
returns/session (pack-08 §1 / pack-05 caveat 2).

**Why not “H12 at 1800”:** (i) half-hour windows are tautological at
H = 1800 (frac 1.00 — pack-11 §0.2 / 11a §1); (ii) hour-only windows
give frac **0.50** and a non-empty F2 contrast (:30 marks, 6/session);
(iii) longer residual half-life and multi-symbol D are part of the
claim, not a decoration.

**H12 ↔ H13 architecture note (Amendment E — binding).** H12 parked
on **power** (pooled viable-region in-window n = 59 < 100;
F2-INSUFFICIENT at out-window n = 89). F1–F5 never ran; zero outcome
contact; **PARK ≠ refutation**. No architecture prejudice transfers
from H12's park into H13's F2 design, κ, or RankIC bars — H13 is
evaluated fresh against its own gates (session constraint 6). Shared
`ALGO_CLOCK` taxonomy and quote-OFI conditioner class remain
infrastructure / family adjacency only.

**Stop-rule (pack-10 DISPOSITION 2 / pack-11 DISPOSITIONS 8).** H13 is
the **final card** on this universe/grid. Death at **any** gate
(census power, form/calendar, step-2b magnitude / significance / F2,
or later) **closes the program**. A step-2b PASS is the sole remaining
path that satisfies the cycle-3 stop-rule. **N = 12** (zero outcome
contact for any slate-D candidate).

---

## 1. OBSERVABLE STATE

### 1.1 Sensor table (exact ids, params, warm-up, halt behavior)

| sensor_id | ver | feed | params | warm rule | gap/halt behavior | units / role |
|---|---|---|---|---|---|---|
| **`scheduled_flow_window`** (existing) | 1.2.0 | Quote/Trade (event-time membership only) | calendar injected at construction (`EventCalendar`) — **H13 injects the hour-only derived view** (§1.5) | **calendar-warm:** `warm=True` iff calendar has ≥1 symbol-eligible window; empty/missing → `warm=False` | **stateless** accumulator — no gap flush; halt does not clear membership; misconfigured date → cold forever that session | tuple `(active, seconds_to_close, id_hash, direction_prior)`; **family fingerprint + `W_hr` predicate** |
| `ofi_raw` | 1.0.0 (existing) | NBBOQuote | `warm_after=50`, `warm_window_seconds=300` | warm ⇔ ≥ 50 OFI-bearing quotes in trailing 300 s event-time | sliding warm deque; sustained gap → cold (S3); degenerate/crossed books dropped | shares signed CKS per-event OFI; **integrand** of conditioner |
| `realized_vol_30s` | 1.3.0 (existing) | NBBOQuote | `window_seconds=30`, `warm_after=16` | warm ⇔ ≥ 16 log-returns in trailing 30 s | window-bounded; un-warms after gaps | unannualised mid log-return std; **gate backstop only** |

**No `spread_z_30d` anywhere.** **No NEW trade-fed sensor.** Conditioner
is quote-fed `ofi_integrated` × hour-only calendar membership.

**G16 fingerprints:** `l1_signature_sensors: [scheduled_flow_window]` —
sole primary in `_FAMILY_FINGERPRINT_SENSORS["SCHEDULED_FLOW"]`.

**TAXONOMY:** `WindowKind.ALGO_CLOCK` **already landed** by H12 Phase A
(universe-wide recurring institutional slice / checkpoint windows,
`symbol: null`). H13 does **not** re-author the taxonomy. Mis-labeling
algo clocks as `INDEX_REBALANCE` / `MOC_IMBALANCE` remains
**inadmissible**.

### 1.2 Horizon reducers consumed (feature_id keys, h = 1800)

| feature_id | producer | status / note |
|---|---|---|
| `scheduled_flow_window_active` | `TupleComponentFeature` index 0 | wired ✓ — **`W_hr` runtime predicate** when the injected calendar is the hour-only derived view |
| `seconds_to_window_close` | `TupleComponentFeature` index 1 | wired ✓ — diagnostic |
| `scheduled_flow_window_id_hash` | `TupleComponentFeature` index 2 | wired ✓ — offline kind/id attribution; REPORTS |
| `scheduled_flow_window_direction_prior` | `TupleComponentFeature` index 3 | wired ✓ — ALGO_CLOCK priors frozen at **0.0** (neutral; direction from OFI) |
| `ofi_integrated` | `HorizonWindowedFeature("ofi_raw", 1800, reducer="sum")` | wired ✓ — trailing-1800 s Σ CKS OFI |
| `ofi_integrated_percentile` | `HorizonWindowedFeature("ofi_raw", 1800, reducer="percentile")` | **factory already emits for every h** (H12 Phase A bootstrap) — H13 consumes the **h = 1800** instance; no silent substitution of session-relative or h = 900 percentiles |
| `realized_vol_30s_zscore` | `RollingZscoreFeature` | wired ✓ — gate backstop |

Percentile semantics: Hazen percentile of current `ofi_integrated`
against its own trailing **1800-second** window of readings ("recent
baseline"), not the session. Quintile tails: ≥ 0.80 LONG / ≤ 0.20 SHORT
(frozen; occupancy pre-read **exempt** under backlog 19 —
**percentile arm only**).

### 1.3 Boundary semantics

`HorizonFeatureSnapshot` carries `values` / `warm` / `stale` keyed by
feature_id. Entry is suppressed unless every id in the alpha's
`required_warm_feature_ids` is warm and not stale; exits are permitted
when stale (Inv-11). Consume-driven required-warm set:

    { scheduled_flow_window_active, ofi_integrated_percentile,
      ofi_integrated, realized_vol_30s_zscore }

`depends_on_sensors: [scheduled_flow_window, ofi_raw, realized_vol_30s]`.

**Warm-iff-calendar (load-bearing):** for every
`(symbol ∈ D, session ∈ that symbol's operative 20)`, the hour-only
derived calendar view **must** be non-empty. Missing/empty →
`scheduled_flow_window.warm=False` → entry suppressed (Inv-11).
Census reports fraction of boundaries with calendar-warm ∧ quote path
live; warm < 0.5 on > 2 sessions drops that symbol from D (coverage,
not tuning).

### 1.4 Session-time discipline (explicit constants)

Fixed constants in `configs/bt_sig_hour_checkpoint_drift_h1800_v1.yaml`
(not free-range; varying either is +1 N):

- `no_entry_first_seconds: 300` — no entries in the first 5 minutes
  (opening cross + MC Official Open re-print arrival).
- `session_flatten_enabled: true`,
  `session_flatten_seconds_before_close: 600` — entries blocked and
  positions flattened from 15:50 ET; every H = 1800 s hold completes
  inside RTH.

All boundary-count arithmetic uses the resulting **09:35–15:50 ET**
in-window count: **12 boundaries / session at H = 1800** (pack-08 §1 /
§4; 11a §1 bit-exact on the 140-cell cache). On each 20-session
symbol with HOLIDAY-THIN HT = 0.90: raw **240** / symbol.

**Window-edge discipline (frozen):**

1. Decision boundaries that fall exactly on an **on-the-hour** mark
   are **in-window** (`W_hr = 1`); the complementary **:30** marks on
   the same H = 1800 grid are **F2 contrast** (`W_hr = 0`) —
   6 + 6 per session (11a §1.1).
2. Entries are **not** suppressed solely for proximity to window
   open/close beyond the calendar membership predicate.
3. Session flatten at 15:50 does **not** invent an hour mark; the last
   in-window H = 1800 boundary is 15:30 (11a §1.1: 10:00 … 15:30 step
   30 min).

### 1.5 CALENDAR ARTIFACTS (Amendment F — Phase-A deliverables)

Authoring uses the **exchange schedule only** — **no tape peeking,
no σ, no IC, no forward returns**.

#### 1.5.1 Taxonomy (already landed — not re-opened)

`WindowKind.ALGO_CLOCK` + loader/tests + `EventCalendar.hash` baseline
from H12 Phase A remain platform capability. H13 adds **no** enum
member.

#### 1.5.2 Hour-only windows = deterministic subset (not re-authoring)

Committed per-session YAMLs already carry the twelve half-hour
`ALGO_CLOCK` marks under `[M, M+1s)` (H12 §1.5.2). H13's `W_hr`
population is the **on-the-hour subset**:

    10:00, 11:00, 12:00, 13:00, 14:00, 15:00   (America/New_York)

**Derivation rule (frozen):** for each committed calendar date in the
union of operative dates across all six D symbols, form the H13
injection view by retaining only `ALGO_CLOCK` rows whose mark minute
is `:00` (equivalently `meta.mark_class` projected to `hour`, or
`window_id` matching `algo_clock_hh_(10|11|12|13|14|15)00_*`). The
`:30` rows remain in the committed files for H12 / platform use; they
are **excluded from the H13 injection view** so
`scheduled_flow_window_active` encodes hour membership, not the
tautological half-hour cover at H = 1800.

Interval convention unchanged: half-open `[M, M+1s)` in ET-resolved ns;
lead = 0. Changing lead/ε or the subset rule is +1 N.

Provenance: derived-view hash (content-addressed transform of the
committed calendar hash) recorded in run provenance (Inv-13). Date
surface = union of operative 20-session sets for
{APP, RMBS, OLN, DIOD, PCTY, CROX} (03c A1.1 ∪ original 10 ∪
Tranche-1B expansion 10 for the four).

#### 1.5.3 Warm-iff-calendar per deployable symbol

| check | rule |
|---|---|
| Hour-only derived view non-empty | required for every evidence/deploy date × symbol ∈ D |
| Symbol-eligible windows | universe-wide `symbol: null` ⇒ eligible for all six |
| Sensor warm | `warm=False` if derived view empty |
| Census park | `calendar_missing_rate > 0` after derivation lands → infrastructure FAIL; warm < 0.5 on > 2 sessions → drop symbol from D |

### 1.6 Geometry audit (Amendment A / 11a §1 — binding on F2)

`PYTHONHASHSEED=0` boundary enumeration (11a; exchange calendar only):

| H | in-window / sess | hour (:00) | :30 (F2) |
|---|---|---|---|
| 1800 | **12** | **6** (frac **0.50**) | **6** (frac **0.50**) |

Matched OFI-quintile **geometry-prior** design-central populations on
the six-symbol × 20-session D (HT = 0.90, quintile 0.40,
ASSERTED gw = 0.90 × 0.95) — card / 11a figures, retained for
auditability:

| arm | raw | geometry-prior design-central | vs ≥ 100 |
|---|---|---|---|
| in-window (`W_hr`) | 6 × 20 × 6 = 720 | **221.6** | PASS (geometry prior) |
| F2 contrast (`:30`) | 720 | **221.6** | PASS (geometry prior; symmetric) |

**Rebuilt density under backlog 19 is in §4.4** — the geometry-prior
221.6 is **not** the load-bearing power projection for this card.

### 1.7 Contamination posture (03b)

Entry conditioner is **quote-fed** (`ofi_integrated`) × **hour-only
calendar membership** (no tape). Class-B prints never enter `ofi_raw`.
No NEW trade-fed extreme conditioner. Contamination-excluded
multiplier = **1.0 at design**.

**REPORTS estimands (backlog 18) — labeled at design for freeze:**

| field (proposed) | estimand | expected |
|---|---|---|
| `halfhour_not_hour_cotravel_rate` | share of quintile-OFI H = 1800 boundaries that are :30 (F2 geometry) | ≈ 0.50 — **not** leakage |
| `calendar_missing_rate` | boundaries with sensor warm=False due to missing/empty hour-only view | **0** after derivation lands; > 0 → infrastructure FAIL |
| `tranche1b_kappa_drift` | census-measured median κ_req − design κ_req on {OLN, DIOD, PCTY, CROX} | diagnostic; drop-from-D if measured κ_req > κ_frozen |
| (no `residual_non_a_share`) | — | N/A — no Class-A trade filter on entry |

---

## 2. LATENT-STATE INFERENCE

**Framing (Kyle / Glosten–Milgrom).** The unobserved quantity is the
*hour-checkpoint residual of open institutional parents / desk books*
— whether the quote-flow extreme at an on-the-hour mark is unfinished
permanent impact under hourly VWAP / schedule-variance review, or
non-hour-bound flow (including generic half-hour slice pressure) that
happens to print an OFI quintile on a `:00` boundary. In Kyle terms:
checkpointed parents intensify participation at the hour; the MM
pricing rule leaves residual incorporation over the next H = 1800 s.
In Glosten–Milgrom terms, LPs and discretionary flow that under-weight
predictable hourly review pressure quote under a posterior that leaves
residual edge.

**Cause mixture for the conditioning event**
`E = {ofi_integrated percentile ≥ 0.80 (or ≤ 0.20 short); W_hr;
P(vol_breakout) < 0.7; realized_vol_30s_zscore ≤ 3.0; required
features warm}`:

| θ | latent cause | adverse? | failure shape | treated by |
|---|---|---|---|---|
| θ₁ | hour-checkpointed institutional parent / desk mid-incorporation (genuine schedule pressure; residual permanent impact) | no — the harvested case; *under-reacting LPs / discretionary between hourly reviews* pay | — | — |
| θ₂ | half-hour-slice or unclocked OFI extreme coincidentally on a `:00` mark (no hour-checkpoint binding) | **yes** | **edge dilution → mild reversal** — temporary impact reverts; hour decoration without substance | **F2 hour-vs-:30 binding** (matched OFI quintile on `:30` must *not* continue); κ's `f_perm` / `r_rem` price partial non-hour share |
| θ₃ | OFI manufacture on a known hour clock (adversarial quote spoofing / flicker timed to `:00`) | **yes** | **negative tail, adversarially timed** — collapse after entry; loss a multiple of target edge; dominant operational mirage (MIXED) | hazard exit + hard age 1800 s; gate-off on breakout / vol z; L5 ledger treatment |
| θ₄ | public-news / auction / other scheduled-flow already impounded at the hour (zero remainder) | no trader to harvest | **edge dilution** | session discipline (§1.4); structural-boundary screen; under-represented on event-free grid — external-validity caveat (§9) |
| θ₅ | mechanical artifacts: tick-grid discreteness (OLN), halt/warm residue, hour-subset derivation defect | no | **edge dilution** (or sign-flip noise if derivation wrong) | §7 R8 stratification; warm-iff-calendar (§1.3); census `calendar_missing_rate` |

The decision rule and hazard exit treat the shapes differently: the
**tail** component (θ₃) gets state-dependent exits (hazard spike,
gate-off FLAT, hard age 1800 s); the **dilution** components
(θ₂/θ₄/θ₅) are measurement and attribution problems — **F2 is the
load-bearing falsifier for θ₂** (hour decoration / half-hour
collapse); no exit rescues an entry that never had hour-checkpoint
substance.

**What the posterior cannot resolve at L1 (loss-ledger tie).** Per
episode, whether an OFI extreme is hour-checkpoint residual vs
half-hour-slice / unclocked flow is undecidable from the quote tape
alone — the calendar supplies the hour predicate, not the parent.
Depth beyond BBO is unobserved (L1); queue position of our passive
entry is unobservable (L2); cancel vs trade contribution inside CKS
OFI is indistinguishable per event (L5); aggressor/informedness of
any coincident prints is unlabeled (L6). Every one of these is
resolved only distributionally: the posterior over θ is a population
claim tested by F1–F3, never a per-trade classification.

---

## 3. PROCESS MODEL

**Named model: hour-checkpoint parent residual-impact drift
(partial-adjustment continuation conditioned on on-the-hour
ALGO_CLOCK membership).** Desk-level / large-parent participation is
reviewed on the hour; at hourly checkpoints the signed quote-flow
intensifies; the mid path toward full incorporation of the still-open
parent remains a persistent drift with exponentially decaying
remainder — pre-registered half-life 900 s, mean lifetime
τ = 900 / ln 2 ≈ 1299 s, fraction of the remainder captured by the
horizon `f_H = 1 − e^(−1800/1299) ≈ 0.80` (the κ factor in §4). The
observable pair is the model made visible: extreme `ofi_integrated`
is the flow fingerprint; `W_hr` is the schedule fingerprint that
attributes the fingerprint to hour-checkpointed parents rather than
ambient or half-hour-only OFI continuation.

Against the shipped alternatives:

- **HMM / semi-Markov regime persistence** (`services/regime_engine.py`,
  `hmm_3state_fractional`): supplies the *exclusion stratum*
  (`P(vol_breakout)`), not the incorporation dynamics — its dwell is
  the wrong clock for a 900 s hour-checkpoint residual. Caveat carried
  from `platform.yaml`: with `transition_time_scaling` OFF (default,
  protecting locked Level-5/6 baselines) the transition matrix
  applies once per inbound quote, so regime dwell is measured in
  *ticks* and drifts ~10× with intraday quote intensity. The gate is
  a conservative filter whose per-stratum discriminability Task 8 must
  report (gate dwell in seconds, per symbol) — never a calibrated
  dwell model for the hour claim.
- **Hawkes self-excitation** (`hawkes_intensity`,
  `scripts/calibrate_hawkes.py`): describes *arrival clustering* with
  no schedule content — the loading phase of a burst. A Hawkes-framed
  version would be burst-following at marks, i.e. precisely the θ₃
  manufacture confound. Survives as caution: elevated branching ratio
  *without* hour binding in conditioned episodes is evidence for θ₃ —
  offline diagnostic, never the model.
- **Drift-diffusion** (`snr_drift_diffusion` sensor, dormant): closest
  shipped formalism for permanent/temporary decomposition; a DD-SNR
  read on in-hour vs :30 episodes is a natural Task-8 diagnostic. Not
  adopted as the runtime model — sensor dormant (new wiring / parity
  surface for zero entry-rule content) and SNR alone does not carry
  the hour attribution that makes this card falsifiable (F2).
- **Half-hour clock residual (H12's model class):** related family,
  **distinct claim** — different actor cadence, H, hl, D, and F2
  contrast population. Not adopted as a parameter variant; H12's
  power park transfers **no** magnitude or binding prejudice
  (Amendment E architecture note).

---

## 4. PARK-RULE ARITHMETIC (Amendment B — κ FROZEN at 0.172)

**Units (00b, THE CONVENTION):** one-way, per-fill, bps of fill
notional throughout. Round-trip figures derived, never disclosed.

### 4.1 Frozen κ decomposition (card block 1 + minimum-rule)

    edge_ow = κ × σ₁₈₀₀ ,   κ = c_D × f_perm × r_rem × f_H × f_pass

| factor | central (card table) | grounding |
|---|---|---|
| `c_D` | **1.20** | on-the-hour subset (stricter clock than half-hour) |
| `f_perm` | 0.55 | longer residual permanent share |
| `r_rem` | 0.55 | parent still open across next half-hour+ |
| `f_H` | 0.80 | 1 − e^(−1800/τ), τ = 900/ln 2 |
| `f_pass` | 0.65 | passive same-side pullback haircut |

    Factor product = 1.20 × 0.55 × 0.55 × 0.80 × 0.65 = **0.18876 ≈ 0.189**
    Card freeze (stated) = **0.172**
    κ_frozen = min(0.172, 0.189) = **0.172** — FROZEN (minimum rule)

**Deviation logged (11a H13 check d / Q1 / DECISION RECORD 1; pack-11
DISPOSITIONS 7):** the written factor table multiplies to **0.189**,
not **0.172**. Factors are **not** restated to erase the freeze. The
0.017 gap remains an auditable card arithmetic bug. One-way ratchet:
no upward re-estimation of κ or any factor after any data contact;
revisable down on evidence only. Once the Task-8 census / measured
conditional edge exists, that measurement **supersedes the derivation
entirely**.

### 4.2 Single-stress floors and park arithmetic (grid-median fees)

Single-stress anchor (pack-08): `floor = 2.25 × (2.0 + fee)` — Inv-12
1.5× applied **once**; never stacked with a simultaneously stressed
adverse-selection vertex. Fees = min-commission floor
`max(0.0035×80, $0.35) = $0.35` on the 80-share reference fill, in bps
of notional at pack-08 / pack-05 grid-median RTH bids.

**OLN min-commission trap (re-derived at its price point):**

    fee_bps(OLN) = 0.35 / (23.48 × 80) × 10_000 = **1.863 bps**
    floor_P(OLN) = 2.25 × (2.0 + 1.863) = **8.692 ≈ 8.69 bps**

Contrast APP at pack-08 med bid 553.72: fee ≈ **0.079 ≈ 0.08 bps** —
OLN pays ~**23×** APP's fee bps at the same share scale because the
dollar commission floor is nearly constant while notional collapses.
That fee inflation — not half-spread — is why OLN's passive floor
(8.69) sits far above APP (4.68) despite a tighter quoted spread in
bps. Half-tick quantum ≈ 2.1 bps at OLN's price remains the
discreteness caveat (pack-05 / pack-08), orthogonal to the commission
trap.

Pack-08 floors (passive): APP **4.68**, RMBS **5.51**, OLN **8.69**,
DIOD **6.23**, PCTY **5.19**, CROX **5.66**. σ₁₈₀₀ med: APP **62.8**,
RMBS **63.8** (20-session); OLN **56.8**, DIOD **47.4**, PCTY **37.2**,
CROX **41.5** (pack-05/08 **10-session** surface — Tranche-1B κ
caveat).

| symbol | κ·σ₁₈₀₀,med | floor | κ_req med | headroom | role (from arithmetic) |
|---|---|---|---|---|---|
| APP | 0.172 × 62.8 ≈ **10.80** | 4.68 | 0.074 | **2.31×** | **Deployable (D)** |
| RMBS | 0.172 × 63.8 ≈ **10.97** | 5.51 | 0.086 | **1.99×** | **Deployable (D)** |
| OLN | 0.172 × 56.8 ≈ **9.77** | 8.69 | 0.153 | **1.12×** (thin) | **Deployable (D)** — min-commission + discreteness; thinnest headroom |
| DIOD | 0.172 × 47.4 ≈ **8.15** | 6.23 | 0.131 | **1.31×** | **Deployable (D)** |
| PCTY | 0.172 × 37.2 ≈ **6.40** | 5.19 | 0.140 | **1.23×** (thin) | **Deployable (D)** |
| CROX | 0.172 × 41.5 ≈ **7.14** | 5.66 | 0.136 | **1.26×** | **Deployable (D)** |
| ENSG | 0.172 × 29.8 ≈ 5.13 | 5.04 | 0.169 | — | **CLOSED** at 0.16-class honest screen (Lei); not in D even though 0.169 < 0.172 |
| MLI | 0.172 × 28.4 ≈ 4.88 | 5.32 | 0.187 | — | **CLOSED** (0.187 > 0.172 and > 0.16 screen); not in D |

**Evidence-only:** none at design for the primary RankIC pool — all six
κ-open names are D. OLN additionally serves as the **in-D
discreteness case** for §7 (not demoted to evidence-only; its thin
headroom is the park risk, not a role demotion).

**Short-side rider restatement chain:**

| symbol | short floor ≈ 2.25×(2.0+fee+0.507) | κ_req short | vs 0.172 |
|---|---|---|---|
| APP | ≈ 5.82 | 5.82/62.8 ≈ **0.093** | clears |
| RMBS | ≈ 6.61 | 6.61/63.8 ≈ **0.104** | clears |
| OLN | ≈ 9.83 | 9.83/56.8 ≈ **0.173** | **fails thinly** — pre-stated long-only restatement if census short edge fails |
| PCTY | ≈ 6.33 | 6.33/37.2 ≈ **0.170** | **fails thinly** — same chain |
| DIOD / CROX | — | ≤ 0.16-class | clear with margin at design |

Pre-stated: if census-measured short edge fails rider-inclusive floor
on a symbol, that symbol restates **long-only** and power is
re-checked under the pooled structure — no threshold tuning.

**Tranche-1B κ caveat (explicit):** park numbers for
{OLN, DIOD, PCTY, CROX} use pack-05/08 **10-session** σ. If a
census-legal σ refresh on the operative 20 raises median κ_req above
0.172 for a symbol, that symbol **drops from D** and the pool is
re-checked (§4.3 / §4.5) — no κ inflation.

### 4.3 Power structure DECLARED AT DESIGN (freeze-ready)

| role | symbols | basis |
|---|---|---|
| **Deployable (D)** | {APP, RMBS, OLN, DIOD, PCTY, CROX} | all median-open at κ_frozen on committed map (§4.2 arithmetic) |
| **Evidence-only** | — | none; ENSG/MLI closed + DRAWN-NOT-INGESTED (§4.6) |
| **Evidence structure** | **pooled only** across D | primary RankIC / power on the pool; per-symbol diagnostics reported but **do not** govern PROCEED; treating per-symbol n ≥ 130 as a PROCEED path is a **freeze-blocking defect** |

**Consequence-precedence sketch (must be copied into the protocol
freeze before any instrument runs — backlog-13/17: any undefined
intersection is a freeze-blocking defect):**

1. Primary §12 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK: design headline
   ≥ 130; census park floor ≥ **100** (D-C1). A single-symbol
   shortfall inside the pool does **not** park if the pool clears —
   unless that symbol also fails deployability park arithmetic, in
   which case it drops from D and the pool is re-checked vs ≥ 100
   under §4.5 axis-split.
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. **F2 window-binding** (mechanism): fail → REJECTED (substance),
   regardless of RankIC magnitude/sign. Label at freeze: mechanism /
   n-invariant for the binding claim. Both arms' adjudicability floors
   are stated in §4.4 / §12 (Amendment E).
5. Soft-σ₁₈₀₀ sampling error is a disclosed feasibility caveat — not
   a post-hoc κ rescue.
6. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

### 4.4 Density with margin — REBUILT under backlog 19 (Amendment C)

**Geometry-prior (card / 11a — not load-bearing after H12):**

    1440 × 0.90 × 0.50 × 0.40 × 0.90 × 0.95 = **221.6**

**Arm posture (backlog 19 — percentile exemption is arm-scoped):**

| arm | class | prior used | basis |
|---|---|---|---|
| HOLIDAY-THIN HT = 0.90 | calendar fact | **0.90** | 2 HT dates / 20 on every D symbol (03c A1.4 / A2.3) |
| hour-window membership `w_hr = 0.50` | **geometry identity** | **0.50** | 6/12 bounds/session (11a §1); **pre-registered for census measurement** — not transferred from H12's half-hour arm |
| OFI quintile 0.40 | percentile | **0.40** | **exempt** (arm-scoped) |
| gate × warm × sign-agreement × vol-z joint | non-percentile | **f_resid = 0.3935** | H12 census characterization: measured all-cell / (raw × HT × w × quintile) = 68 / (1000 × 0.90 × 0.48 × 0.40) = **0.3935**; replaces ASSERTED gw = 0.90 × 0.95 = 0.855. Warm alone measured 1.000 on H12 (C.2) — the residual shortfall is gate/sign/vol-z joint occupancy, not calendar-warm |

**H12 characterization disclosure (Addendum-G — not H13 evidence):**

| quantity | H12 measured | use here |
|---|---|---|
| realized / design-central all-cell in-window | 68 / 147.7 ≈ **0.46×** | equivalent check: 221.6 × 0.46 ≈ 102 |
| viable / all-cell in-window | 59 / 68 ≈ **0.868** | viable-region projection haircut |
| calendar-warm | **1.000** | supports replacing ASSERTED 0.95 with measured-class warm; H13 still measures its own |
| F2 out-window viable | 89 < 100 | architecture note only (H12 F2-INSUFFICIENT was power, not binding fail) |

**Rebuilt design-central (all-cell projection, six-symbol pool):**

    1440 × 0.90 × 0.50 × 0.40 × 0.3935 = **102.0**

| estimand | rebuilt projection | vs ≥ 130 design | vs ≥ 100 census |
|---|---|---|---|
| **All-cell in-window (primary)** | **102.0** | **FAIL** (102 < 130) | **BARELY PASS** (102 ≥ 100) |
| **Viable-region in-window** (× H12 viable/all 0.868) | **≈ 88.5** | FAIL | **FAIL** (88.5 < 100) |
| **F2 :30 all-cell** (symmetric geometry) | **102.0** | FAIL vs design | BARELY PASS |
| **F2 :30 viable-region** | **≈ 88.5** | FAIL | **FAIL — F2-INSUFFICIENT class if realized** |

**Plain statement for Lei (Amendment C — mandatory):** the honest
recomputation under backlog 19 lands the **viable-region projection
below the pooled ≥ 100 census floor** (≈ 88.5). The all-cell
projection (102) clears 100 by a hair and **fails** the design margin
≥ 130. The census still adjudicates on measured counts; this
projection is the spend-or-not input. Per-symbol rebuilt all-cell
expectation ≈ **17.0** — pool-mandatory remains.

Both F2 arms' adjudicability floors (Amendment E): each arm requires
pooled viable-region n ≥ **100** to adjudicate binding (H12 JC-9
precedent). Under the rebuilt projection **neither arm is projected
adjudicable**. Geometry-prior 221.6/221.6 would have cleared; H12
taught that geometry priors on non-percentile joints are not
load-bearing.

### 4.5 Pool-collapse behavior FROZEN (Amendment D — pack-11 condition)

Axis-split as symbols drop from D, **stated numerically** for both
projection bases. Re-check vs floors after every D-drop; no threshold
tuning.

**Geometry-prior design-central (card / 11a §2e — freeze completeness):**

| \|D\| | design-central | vs ≥ 130 | vs ≥ 100 |
|---|---|---|---|
| 6 | **221.6** | PASS | PASS |
| 5 | **184.7** | PASS | PASS |
| 4 | **147.7** | PASS | PASS |
| 3 | **110.8** | **FAIL** | PASS |
| 2 | **73.9** | FAIL | FAIL |
| 1 | **36.9** | FAIL | FAIL |

**Backlog-19 rebuilt all-cell projection (load-bearing for Lei's spend ruling):**

| \|D\| | rebuilt all-cell | vs ≥ 130 | vs ≥ 100 |
|---|---|---|---|
| 6 | **102.0** | FAIL | PASS (hair) |
| 5 | **85.0** | FAIL | **FAIL** |
| 4 | **68.0** | FAIL | FAIL |
| 3 | **51.0** | FAIL | FAIL |
| 2 | **34.0** | FAIL | FAIL |
| 1 | **17.0** | FAIL | FAIL |

**Census verdict mapping (every partial-pool outcome):**

| measured pooled viable-region in-window | \|D\| after drops | verdict |
|---|---|---|
| ≥ 100 and edge non-empty on remaining D | any | **PROCEED** to step 2 (power clears); F2 arm separately scored for adjudicability |
| < 100 | any | **PARK (power)** — program closes (H13 final card) |
| ≥ 100 on geometry fantasy but < 100 measured | — | measured governs; geometry-prior never rescues |
| edge-region empty on every remaining symbol | any | **PARK (edge emptiness)** before power |
| drop cascade → rebuilt projection < 100 before instruments | — | pre-registered: if D falls to ≤ 5 under κ/warm/rider drops **before** census, Lei re-auth required — rebuilt table says ≤ 5 fails census floor even as projection |

### 4.6 ENSG / MLI ingestion arithmetic (for Lei's ruling)

| path | arithmetic | opens power? |
|---|---|---|
| Keep DRAWN-NOT-INGESTED (default) | six-symbol rebuilt viable ≈ **88.5 < 100** | **No** — projection already below census floor |
| Ingest ENSG/MLI × 10 as evidence-only | +2 × 10 × 12 × 1.0 × 0.50 × 0.40 × 0.3935 ≈ **+18.9** all-cell; still **closed at median κ** — cannot enter D; primary RankIC remains on D only | **No** — evidence-only cells do not repair the deployable pool's power bar |
| Ingest + promote into D against Lei's 0.16-screen ruling | would require overriding DECISION RECORD 1 | not authorized here |

**Ruling request (stop and ask — session constraint 7):** ingestion is
**not requested** here. Full three-config arithmetic (A/B/C), ENSG/MLI
κ-viable cell counts, and the A-2.1-vs-H10 pool-structure question are
in **Appendix P** (pre-Task-8 ruling input). Lei rules pool
configuration there; Task 8 freezes the choice.

Park conditions, pre-registered for census: (i) edge-region emptiness;
(ii) power — pooled contamination-excluded viable-region episodes
< 100 (census) / design headline miss vs ≥ 130 at freeze (already
projected). Either parks before any IC outcome is treated as a
PROCEED.

---

## 5. DECISION RULE (platform terms)

### 5.1 Free-range parameters (≤ 3 — template discipline)

| param | type | default | range | meaning |
|---|---|---|---|---|
| `ofi_percentile_min` | float | 0.80 | 0.75 – 0.85 | p₀: minimum `ofi_integrated_percentile` for LONG (symmetric 1−p₀ for SHORT); can only tighten from the gate's arming 0.80 |
| `edge_scale_bps` | float | 12.0 | 6.0 – 18.0 | linear edge attribution per unit normalised OFI exceedance; **provisional pending calibration** — G12 disclosure uses the measured value |
| `edge_cap_bps` | float | 16.0 | 10.0 – 24.0 | hard cap on emitted `edge_estimate_bps` |

Fixed constants (not free-range; varying any is +1 N): the quintile
split 0.80 / 0.20; `W_hr` membership via
`scheduled_flow_window_active == 1` under the hour-only derived
calendar; per-symbol single-stress floors (§4.2), embedded as literal
dicts; session knobs (§1.4); gate thresholds (§5.3); hour-subset
derivation rule (§1.5.2).

### 5.2 `evaluate(snapshot, regime, params)` — pure logic (normative draft; Phase B implements)

G5 purity: no imports, no I/O, no state; deterministic in its inputs.
Reads literal snapshot keys only (consume-driven required-warm, §1.3).

```python
signal: |
  def evaluate(snapshot, regime, params):
      ofi = snapshot.values.get("ofi_integrated")
      pctl = snapshot.values.get("ofi_integrated_percentile")
      w_hr = snapshot.values.get("scheduled_flow_window_active")
      if ofi is None or pctl is None or w_hr is None:
          return None
      # Track-A / Inv-11: garbage inputs suppress entry, never create exposure
      if ofi != ofi or pctl != pctl or w_hr != w_hr:  # NaN reject
          return None
      if ofi == ofi and (ofi > 1e308 or ofi < -1e308):
          return None
      if pctl == pctl and (pctl > 1e308 or pctl < -1e308):
          return None

      # Hour-clock predicate — load-bearing (W_hr via hour-only calendar view)
      if w_hr < 0.5:
          return None

      p0 = params["ofi_percentile_min"]
      # Two-sided quintile: long on upper tail, short on lower tail
      if pctl >= p0:
          direction = LONG
          excess = (pctl - p0) / (1.0 - p0)
      elif pctl <= (1.0 - p0):
          direction = SHORT
          excess = ((1.0 - p0) - pctl) / (1.0 - p0)
      else:
          return None

      # Sign agreement: integrated OFI level must agree with percentile tail
      if direction == LONG and ofi <= 0.0:
          return None
      if direction == SHORT and ofi >= 0.0:
          return None

      floor_bps = {
          "APP": 4.68, "RMBS": 5.51, "OLN": 8.69,
          "DIOD": 6.23, "PCTY": 5.19, "CROX": 5.66,
      }.get(snapshot.symbol)
      if floor_bps is None:
          return None

      # Posterior expected unincorporated remainder, linear proxy of
      # section-4 derivation; calibration supersedes the scale.
      if excess > 1.0:
          excess = 1.0
      edge_bps = params["edge_scale_bps"] * excess
      if edge_bps > params["edge_cap_bps"]:
          edge_bps = params["edge_cap_bps"]

      # Entry only when posterior EV clears the per-symbol single-stress
      # cost anchor -- never a bare threshold or pure time stop.
      if edge_bps < floor_bps:
          return None

      # Strength rider (00e Track A): bounded by construction; clamps
      # explicit as belt-and-suspenders.
      strength = excess
      if strength < 0.0:
          strength = 0.0
      if strength > 1.0:
          strength = 1.0

      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="sig_hour_checkpoint_drift_h1800_v1",
          direction=direction,
          strength=strength,
          edge_estimate_bps=edge_bps,
          trend_mechanism=SCHEDULED_FLOW,
          expected_half_life_seconds=900,
      )
```

Strength construction (00e Track A rider, adopted verbatim):
`strength = min(max(0.0, excess), 1.0)` with `excess ∈ [0, 1]` by
construction at any reachable entry. Phase B / Task 9 gains the
rider's two tests: (i) unit test asserting `strength ∈ [0, 1]` across
the full declared parameter ranges; (ii) Hypothesis property test
driving snapshot values adversarially (NaN, ±inf, extremes, missing
keys, `w_hr=0`) asserting `None` or in-range strength and
non-negative finite `edge_estimate_bps`.

Deliberately **not** in the runtime rule: any runtime σ estimate as
edge scale; :30 diagnostic features; session-relative percentile
(drafted §14); half-hour calendar injection (would make F2 vacuous).

### 5.3 Regime gate (AST DSL; hysteresis referenced, not dead config)

```yaml
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(vol_breakout) < 0.7
    and scheduled_flow_window_active >= 0.5
    and (ofi_integrated_percentile >= 0.80
         or ofi_integrated_percentile <= 0.20)
    and realized_vol_30s_zscore <= 3.0
  off_condition: |
    P(vol_breakout) > 0.7 + posterior_margin
    or realized_vol_30s_zscore > 3.0
    or scheduled_flow_window_active < 0.5
    or (ofi_integrated_percentile < 0.80 - percentile_margin
        and ofi_integrated_percentile > 0.20 + percentile_margin)
  hysteresis:
    posterior_margin: 0.15        # >= 0.15 (G9); REFERENCED above
    percentile_margin: 0.15       # REFERENCED above (quintile release band)
```

Notes: both hysteresis margins are **referenced** (strict loader
rejects declared-but-unused margins as dead config). The posterior
latch arms below 0.70 and releases above 0.85; the OFI latch arms at
quintile tails and releases when the percentile returns inside
`(0.20 + 0.15, 0.80 − 0.15) = (0.35, 0.65)`. Gate-off when
`scheduled_flow_window_active < 0.5` is the **hour-clock-lapse exit**.
Gates fail OFF on missing bindings or non-discriminative posteriors
(fail-safe). The vol-z clause is the sensor-level backstop for the
HMM tick-based-dwell weakness (§3).

### 5.4 Hazard exit block

```yaml
hazard_exit:
  enabled: true
  hazard_score_threshold: 0.85     # controller default
  min_age_seconds: 30              # controller default
  hard_exit_age_seconds: null      # -> derived 2 x expected_half_life_seconds = 1800 s
```

`RegimeHazardSpike` is an exit-direction hint only (Inv-11);
`HARD_EXIT_AGE` fires at **1800 s** (2 × hl 900, platform HM-1
derivation), bounding θ₃ tail exposure. Exits also fire on regime-gate
OFF (conservative FLAT close path, including hour-clock-lapse and OFI
mechanism-lapse releases) and are never blocked by B4
(`not is_exit_or_stop`). This is **not** a pure time stop: the age
cap is the backstop behind two state-dependent exits (hazard spike,
gate-off), and entry is EV-gated (§5.2).

### 5.5 Cost arithmetic disclosure (G12; one-way per 00b)

Pinned to the design edge at the APP median; **final values are the
measured conditional edge on the deployable set** (disclosed edge =
deployable-set minimum measured edge, conservative):

```yaml
cost_arithmetic:
  edge_estimate_bps: 10.80   # kappa 0.172 x sigma_1800 APP median; measured value supersedes
  half_spread_bps: 0.0       # maker: no crossing
  impact_bps: 2.0            # passive adverse selection charge (00c pin)
  fee_bps: 0.08              # commission floor at reference fill scale, APP anchor
  margin_ratio: 5.19         # 10.80 / 2.08; reconciles +/- 0.05 absolute; >= 1.5 (G12)
  # cost_basis: one_way (default; round_trip reserved -- never used)
```

Taker was closed at design for this horizon class on the operative
frontier (pack-08) — no taker variant exists for this card. Runtime:
B4 doubles the one-way edge onto the round-trip basis against the
modeled entry+taker-exit cost; config adopts
`signal_min_edge_cost_ratio: 1.5`. Sizing: top-of-book scale;
**Sharpe-max declared**.

---

## 6. INVARIANCE CHECKS (≥ 2)

**I-1 (R5, zero-integrated-edge conservation — mandatory).** The
integrated edge must be payable out of the adverse-selection /
under-reaction losses of the counterparties who supply liquidity
against hour-checkpointed parents in the conditioned in-hour episodes
— measured, not asserted. Design: over the full regime-balanced
evidence grid, compute (a) the funding pool — for each conditioned
in-hour episode, the measured continuation move times the contra-side
(resting / faded) volume that traded against the OFI direction inside
the episode window; (b) the strategy's integrated pre-cost conditional
edge at declared participation (≤ top-of-book scale — participation
share must be stated). **Pass:** (b) ≤ participation share × (a)
within estimation error. **Fail (misattribution):** integrated edge
exceeding what counterparty losses can fund — the edge, if real, comes
from something unnamed and the card is wrong even if profitable.
Companion conservation checks: (i) unconditional forward returns over
all matched in-hour boundaries must integrate to ≈ 0 over the
regime-balanced sample (no ambient-momentum subsidy); (ii) the
**:30 matched-OFI stratum** (`W_hr = 0`, same quintile gate) is
exactly F2 — if it continues at the same sign/magnitude class, the
hour does no work and the card is an unpre-registered half-hour /
unclocked OFI-continuation hypothesis — dead by its own terms.

**I-2 (side symmetry).** The mechanism is side-symmetric: conditional
continuation on buy-OFI extremes (LONG) and sell-OFI extremes (SHORT)
inside `W_hr` must agree within sampling error in the benign stratum.
Persistent asymmetry beyond noise ⇒ contamination — investigate before
any deployment claim. The SHORT side additionally carries the §5.2
SSR/HTB optimism caveat and the §4.2 long-only restatement rule
(OLN/PCTY thin short riders pre-stated — *economic* asymmetry, not
mechanism; I-2 tests the pre-cost mechanism symmetry).

**I-3 (hour / flow co-travel — mechanism attribution).** If hour
binding identifies residual parent impact, conditioned in-hour
episodes must show continuation that the matched :30 OFI-quintile
population does **not** share (F2). No differential ⇒ OFI extremes are
half-hour or unclocked continuation (θ₂) — mechanism attribution fails
even if pooled in-hour continuation is positive. Hour-subset
derivation defects that spuriously create `W_hr` are infrastructure
fails (`calendar_missing_rate` / warm starvation), not edge claims.

---

## 7. TICK-CONSTRAINT ARTIFACT ANALYSIS (R8)

**Does the state-variable definition survive a tick-regime shift?
Yes — the definition; only parameters need re-estimation.** The
state variables are (i) **calendar membership** `W_hr` — a pure
exchange-schedule predicate, not a tick-grid object — and (ii)
**volume-signed CKS integrated OFI** — dimensionless in definition
relative to share flow, not a tick count. What the grid quantizes is
the mid path that *funds* the edge (continuation in ticks). Coarse
grids can make continuation mass sit at half-tick quanta — but they
do not redefine what an hour mark or an OFI event is.

**Grounding in realized buckets (03c §7):** pooled median
spread-in-ticks — APP / RMBS wide/unconstrained; DIOD / PCTY / CROX
moderate; **OLN = discrete/near-constrained — the designated
discreteness case, now inside D** (deployable at κ_frozen @1800 with
thin headroom; half-tick ≈ 2.1 bps at its price point).

**Explicit test design (pre-registered):**

1. Report the spread-in-ticks distribution **at signal boundaries**
   (not pooled) per symbol — OFI×hour extremes may select thin-book /
   wide-spread states the pooled medians hide.
2. **≥ 4-tick-stratum re-derivation:** re-estimate the conditional
   1800 s continuation using only in-hour boundaries with prevailing
   spread ≥ 4 ticks (APP/RMBS qualify structurally; thin names
   reported separately). Survival criterion: the ≥ 4-tick-stratum
   edge consistent with the full-sample estimate; collapse ⇒ pooled
   effect was grid artifact (θ₅).
3. **OLN quantum test (persistence vs grid discreteness — in-D):**
   on OLN, compare the conditional 1800 s move distribution against
   the ±1-half-tick quantum: continuation mass sitting at exactly the
   quantum with no continuous tail ⇒ grid bounce, not hour-checkpoint
   residual; genuine persistence must show mass beyond one quantum and
   σ-normalised agreement with the wide-bucket estimate. OLN remains
   in the pooled RankIC bar unless it drops from D under §4.2/§4.5.
4. **Parameters vs definition:** across buckets, `edge_scale_bps` may
   legitimately differ (re-estimate); if the *sign* of the conditional
   continuation differs by bucket after the quantum correction, that
   is definition-level failure (kill — §10, tick-constraint axis).
5. **Scheduled boundaries (pre-registered structural splits):** SEC
   Rule 612 half-penny regime (compliance first business day Nov 2027)
   — never pool across it; MDI round-lot reassignments (semiannual,
   per symbol); the 2026-04-27 vendor admissibility split — the grid
   is entirely pre-2026-04-27 by construction.

---

## 8. L2 LOSS LEDGER (signal-specific)

Baseline ledger (prompt_pack_03 §7) instantiated for *this* signal.

| row | bite on this signal | treatment adopted (one sentence) |
|---|---|---|
| L1 depth beyond BBO | hour-checkpointed parents may be working size the BBO cannot show; mechanical quote pressure at `:00` can be depth-starvation, not residual impact (θ₂ confound) | Treated distributionally via F2 (matched :30 OFI must not continue) and top-of-book sizing so no beyond-BBO liquidity claim is made; forced exits inherit the platform's capped walk-the-book impact model. |
| L2 queue composition / position | passive entry into a continuation move is conditionally adverse — the limit order fills preferentially when the move stalls or retraces (fill ⇔ continuation weakening) | Adopted as **first-class** (§11): the platform's seeded-Bernoulli fill hazard is the probabilistic model and its conservatism is *tested* via the §11 sensitivity grid and the filled-vs-unfilled markout diagnostic — for a continuation card this is the likeliest F4 exit and is pre-declared as such. |
| L3 venue fragmentation | displayed NBBO ≠ single-venue accessible size; fee economics blended | Accepted as systematic noise under the flat blended maker/taker pins; the conditioner uses consolidated quote OFI + SIP calendar time, not a venue-local size claim — no per-venue feature proposed or dropped. |
| L4 hidden/midpoint liquidity | hidden absorption completes incorporation without printing — the remainder vanishes silently (dilution of `r_rem`) | Treated distributionally: no per-episode claim; `trade_through_rate` available as an offline prevalence diagnostic per stratum; `r_rem = 0.55` already prices partial invisibility and is one-way-ratchet revisable down. |
| L5 cancel attribution / displayed-size manufacture | CKS OFI conflates cancels, replenishment, and trades; adversarial quote manufacture timed to known hour clocks is the dominant MIXED-mirage path (θ₃) | Feature kept with mirage M = 1.5 disclosed; no order-level cancel filter exists on L1 — defense is F2 plus hazard/gate-off bounding θ₃ tails; `quote_flicker_rate` available offline per stratum, not on the entry path. |
| L6 aggressor signing / informedness | quote-fed OFI does not require trade aggressor labels; coincident print signing is not on the entry path | **Quote-OFI path:** no tick-rule entry variable; informedness of parents remains a population claim tested by F1/F2, never a per-print label; flat adverse-selection bps by fill type remain the cost treatment (00c). |
| L7 latency microstructure | none claimed | 20 ms visibility + 50 ms fill = 70 ms ≈ 0.008 % of the 900 s half-life — no latency edge asserted; zero-latency configs invalid for evidence (00c decision A). |

---

## 9. REGIME HONESTY (L1–L5 VERBATIM where touched)

The universe decision's limitations, **verbatim** (03c §2 + A1.6), as
they bind this design:

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
- **L5 (A1.6, verbatim gist carried as binding):** elevated-A single-week
  concentration — combined elevated-A stratum
  `2025-11-25, 2025-12-01, 2025-12-02, 2025-12-04` with three of four
  dates in one calendar week and 12-01/12-02 adjacent; elevated-A
  conclusions are evidence about early-December-2025-as-realized;
  per-window reporting under L4 should treat elevated-A as effectively
  one episode-week.

Binding consequences: (i) the **intraday HMM `P(vol_breakout)` gate
and the daily calm/elevated strata are different objects** — every
statistic is reported in the 2×2 of (gate state × daily stratum).
(ii) L3 lands directly: RMBS is both a heavily conditioned grid
subsample AND a deployable symbol — every RMBS figure carries the L3
flag. (iii) Calm-stratum conclusions carry the L1 qualifier verbatim.
(iv) L5 binds elevated-A reporting. (v) θ₄ news/auction confound is
*under-represented* on the event-free grid — external-validity caveat
on any deployment claim. (vi) OQ-3 caveat: mechanism-share runtime not
active; vendor V-1: grid inside pre-2026-04-27 cap. (vii) Tranche-1B
four names carry L5 elevated-A week concentration once expansion dates
join their operative 20.

---

## 10. KILL CONDITIONS (per regime axis: parameters vs definition, as the platform triple)

For each axis: what a shift breaks; then the three artifacts the
platform consumes — `falsification_criteria` prose,
`failure_signature` clause (G16 rule 6), and the `regime_gate`
`off_condition` term where run-time gating is the right control.

| axis | shift → breaks | falsification_criteria (prose) | failure_signature clause | runtime gate term |
|---|---|---|---|---|
| **Spread** | transient widening → MM stress, passive economics invalid (**gate** — `vol_breakout` posterior IS the spread/stress gate here); persistent level/bucket migration → **parameters** (floors, fee table — OLN min-commission trap re-derives); continuation sign reversing across spread-in-ticks strata within the benign stratum → **definition (kill)** — OFI×hour was reading stress state, not hour residual (F3) | "sign(conditional 1800 s forward return) reverses across spread-in-ticks strata within the benign in-hour stratum" | `"sign of conditional forward return reverses across spread-in-ticks strata within the benign stratum"` | `P(vol_breakout) > 0.7 + posterior_margin` |
| **Volatility** | disorderly breakout → cascade / manufacture risk dominates (**gate**); secular σ-regime change → **parameters** (edge_scale / G12 disclosure re-derive from measured edge — never in-place κ edits; soft-σ₁₈₀₀ caveat); benign-stratum continuation flipping to reversion → **definition (kill)** — the premise (in-hour OFI quintile continues) is dead (F1) | "in-hour ofi_integrated_percentile boundaries (≥ 0.80 or ≤ 0.20) in the benign stratum show 1800 s forward-return sign agreement ≤ 0.50 over any rolling 20-session window" | `"in-hour extreme ofi_integrated_percentile boundaries show 1800 s forward-return sign agreement <= 0.50 over any rolling 20-session window"` | `realized_vol_30s_zscore > 3.0` (sensor backstop for HMM tick-dwell weakness) |
| **Liquidity** | MDI round-lot / depth-scale change → **parameters** (sizing scale, fee table); quote-warm / calendar-warm decay → **coverage rule** (warm < 0.5 on > 2 sessions drops the symbol, §1.3 — not a kill); in-hour continuation ceasing to differ from matched :30 OFI → **definition (kill)** — the hour fingerprint carries no substance (F2) | "conditional forward return at matched ofi-quintile extremity is indistinguishable (\|Δ\| ≤ 1 SE) between W_hr=1 and W_hr=0 (:30) strata" | `"matched ofi-quintile continuation on :30 boundaries indistinguishable from in-hour continuation"` | hour-clock-lapse: `scheduled_flow_window_active < 0.5`; OFI mechanism-lapse: percentile returns inside `(0.20 + percentile_margin, 0.80 - percentile_margin)` |
| **Tick-constraint** | scheduled Rule 612 half-penny boundary (Nov 2027) → **hard structural split, pre-registered**; bucket migration of a symbol → **parameters**; failure of the §7 ≥ 4-tick re-derivation or the OLN quantum test pattern appearing on a deployable symbol → **definition (kill on the affected stratum)** | "the conditional edge does not survive re-derivation on the spread ≥ 4 ticks stratum, or conditional move mass sits at the ±1 half-tick quantum with no continuous tail" | `"conditional edge on the >=4-tick spread stratum inconsistent in sign with the pooled estimate"` | none — measurement stratification, not gateable |
| **Scheduled-flow / news** | auction windows → **config** (session discipline §1.4); a change in auction/dissemination mechanics or hourly institutional practice → declared structural boundary; edge concentrating *only* in non-ALGO_CLOCK scheduled-event-adjacent or news-print windows → **definition (kill)** — the counterparty would be event flow and the remainder already impounded (θ₄); **hour-subset derivation / taxonomy defect** → infrastructure FAIL under stop-rule (program-closing if form FAIL) | "conditional edge concentrates in boundaries adjacent to non-ALGO_CLOCK scheduled events/news prints and vanishes on ALGO_CLOCK hour marks in the session interior; OR calendar_missing_rate > 0 after hour-only derivation lands" | `"conditional edge on ALGO_CLOCK in-hour boundaries indistinguishable from zero while event-adjacent non-ALGO_CLOCK boundaries carry it"` | config: `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600`; runtime: `scheduled_flow_window_active < 0.5` |

Plus the standing structural boundaries (F5, pre-registered once):
Rule 612; MDI round-lot reassignments; the 2026-04-27 vendor
admissibility split (post-2026-04-27 sessions inadmissible).

---

## 11. FILL-MODEL DEPENDENCY — FIRST-CLASS (rider carry)

This card's execution posture is **passive entry into a continuation
move** — the structurally adverse fill geometry (the resting order
fills when the move retraces or stalls; the L2 row). The crowd's
hour-checkpointed parents take or lean; we rest. F4 is therefore the
pre-declared likely exit, and the evidence requirements are binding:

**(a) Passive-fill-quality diagnostics (every H13 evidence run reports):**

- **Fill-mix realism:** distribution of fill outcomes from
  `passive_fill_stats()` — level/drain vs through fills, partial-fill
  slices, `EXPIRED` (timeout-cancel) rate, and time-to-fill vs the
  3-tick delay + hazard model. For a continuation card the trap reads
  *inverted* relative to a fade: a fill mix dominated by
  **retrace/drain fills followed by non-resumption** means entries
  are systematically acquired exactly when the continuation premise
  has already failed — the execution-layer signature of θ₂/θ₃.
- **Conditional adverse selection:** post-fill markouts at 900 s and
  1800 s on *filled* signal boundaries vs the same conditional forward
  return on *unfilled* signal boundaries — the filled-minus-unfilled
  gap is the realized L2 selection cost; it must be consistent with
  (or better than) the 2.0 bps charged, else F4 arithmetic re-runs
  with the measured figure.

**(b) Sensitivity grid (pass = robustness across the full grid):**
3 × 3 × 3 over the pinned profile —

| knob | pinned | grid |
|---|---|---|
| `passive_fill_hazard_max` | 0.5 | {0.25, 0.5, 0.75} |
| `passive_queue_position_shares` | 200 | {100, 200, 400} |
| `cost_passive_adverse_selection_bps` | 2.0 | {2.0, 3.0, 4.0} |

**Pass:** the F4 clearance verdict (measured net edge ≥ per-symbol
**single-stress** floor, §4.2 — the AS axis here is a robustness
sweep, never a second stress folded into the floor; no stacking)
holds at **every** grid vertex on the deployable set. A verdict that
flips across the grid is simulator-dependence and the candidate is not
execution-valid regardless of the pinned-profile number.

**(c) Task 12 parity is a HARD GATE for any H13 evidence** — no number
produced before the router timing-parity check of Task 12 is
presented as a result. **Task 12-P (2026-07-12) AXIS-1 VERIFIED**
(`prompt_pack_12p_router_fill_timing_parity.md`; regression guards
committed) — re-verified green at execution-overlay time; any AXIS-1
regression re-opens the gate. The live-WS cancel/correction
dissemination row (03b §7.3 row 2) and the L7 ms-timestamp asymmetry
remain AXIS-2 / Task-12 inputs reported alongside.

**(d) F4 trap-quadrant clause, retained verbatim:** "F4 (execution
validity): pre-cost continuation exists but ≤ 1.5 × C_ow under the
passive realism model → `trap-quadrant`."

---

## 12. FALSIFICATION CRITERIA (consolidated; F2 load-bearing — Amendment E)

### 12.1 F1–F5

- **F1 (forward test, honest-N):** continuation-signed conditional
  1800 s forward return ≤ 0 at the joint in-hour condition, or below
  the honest-N noise ceiling `expected_max_sharpe(n_trials=N, …)` with
  N from the living ledger → dead. Clause: `"in-hour extreme
  ofi_integrated_percentile boundaries show 1800 s forward-return sign
  agreement <= 0.50 over any rolling 20-session window"`.
- **F2 (mechanism tie — hour-vs-:30 window-binding; LOAD-BEARING
  FALSIFIER; two-arm):** both arms pre-registered (§1.6 / §4.4):
  - **In-hour arm (`W_hr = 1`):** geometry-prior design-central
    **221.6**; backlog-19 rebuilt all-cell **102.0** / viable
    **≈ 88.5**. Adjudicability floor = pooled viable-region n ≥ **100**.
  - **F2 contrast arm (`:30`, `W_hr = 0`):** same populations
    (symmetric geometry). Adjudicability floor = pooled viable-region
    n ≥ **100** (else **F2-INSUFFICIENT** — no primary-only PROCEED on
    the binding claim; H12 JC-9 precedent).
  **Window-binding clause (dual form):**
  1. *Substance form:* if the matched ofi-quintile conditioning on
     `:30` boundaries shows continuation of the **same
     sign/magnitude class** as the in-hour arm → claim refuted
     (hour decoration / half-hour collapse, not hour-checkpoint flow).
  2. *Differential form:* in-hour continuation must exceed :30
     continuation by a pre-registered margin (frozen in the
     validation protocol before instruments run); absence of
     differential ⇒ F2 FAIL.
  Clause: `"matched ofi-quintile continuation on :30 boundaries
  indistinguishable from in-hour continuation"`.
- **F3 (regime/stratum):** sign reversal across spread-in-ticks strata
  → definition kill; benign-stratum flip to reversion → premise dead.
- **F4 (execution validity):** §11(d) verbatim, evaluated per-symbol
  against the §4.2 single-stress floors, across the §11(b) grid, only
  on Task-12-parity-cleared machinery.
- **F5 (structural boundaries):** the three pre-registered hard splits
  (§10 footer); never pool across.

### 12.2 H12 adjacency (no architecture prejudice — Amendment E)

| direction | rule |
|---|---|
| **H12 → H13** | H12's **power park** is trigger (a) activation only — not a magnitude prior, not an F2 result, not a κ/bar input. H12 F2 was **F2-INSUFFICIENT** (n = 89), not F2-NEGATIVE. |
| **H13 → H9** | H13 evidence **never cites toward H9 revival** (pack-11 DISPOSITIONS 3 firewall carries to the family). An H13 F2-fail :30 arm that shows continuation is a **contaminated shelf** about half-hour / unclocked OFI — not KYLE rehabilitation. |
| **H9 → H13** | H9 history never prejudices H13 scoring. |

Any DSR computed downstream uses the then-current ledger N
(`build_dsr_evidence(trials_count=N)`).

---

## 13. OUTCOME-INFORMED PRIOR DISCLOSURE (Amendment G — Addendum-G table)

| prior | source | use on this card | status |
|---|---|---|---|
| H = 300 → H = 900 RankIC magnitude (0.0186 → 0.0893) | H8/H10 POST-HOC shelf | May **bias** toward longer horizons in ranking discussion; **must not** set κ or bars; soft-σ₁₈₀₀ cuts the other way | disclosed; not evidence |
| H10 F2 KYLE miss at H = 900 | H10 S.8 / result §7 | Family switch to SCHEDULED_FLOW only; **not** a magnitude prior | disclosed |
| H12 geometry lesson (§0.2 / 11a §1) | pack-11 / 11a | Forced hour-only subset at H = 1800 so F2 is non-vacuous — design constraint, not an outcome statistic | disclosed |
| **H12 census arm-attrition** (all-cell 68 / design 147.7 ≈ 0.46×; viable 59; warm 1.000; gate residual f_resid = 0.3935) | H12 census `3ed79a6` / protocol C.4–C.5 / result §7; backlog 19 | **Characterization input** for §4.4 density rebuild only — not H13 evidence, not a RankIC prior, not a κ edit | disclosed; characterization |
| H12 power park (n = 59) | pack-11 DISPOSITIONS 6–8; H12 result | Trigger (a) activation only; **PARK ≠ refutation**; no F1–F5 prejudice | disclosed |
| RMBS +0.226 shelf | H10 result-doc | **N ≥ 13** before any use; **not consumed** in κ, density, bars, or ranking | disclosed; unused |
| Cycle-1/2 warm / ISO / occupancy diagnostics | H2/H8/H10 censuses | Conventions only (no `spread_z_30d`; percentile tails arm-scoped exempt; D-C1 ≥ 130 design / ≥ 100 census) | disclosed |
| H11 form FAIL (G16 / no clock predicate) | pack-09 DISPOSITIONS 3; 09a §2 | Forced reformalization bar this card discharges via hour-only path; not an economic prior | disclosed |

---

## 14. TRIAL LEDGER (drafted-not-evaluated appendix; N = 12 unchanged)

Primary = slate-D ledger row "H13 primary: ofi_integrated(1800 s)
quintile × hour `ALGO_CLOCK` continuation, H=1800, hl=900, passive,
pooled six-symbol D" — this spec is its formalization, not a new
trial. FQ-6B-R: any data contact increments N; drafting does not.

| variant drafted | status |
|---|---|
| H13 primary (this spec) | drafted-not-evaluated (N-impact: 0) — formalization only |
| H13 alt: drop OLN from D at freeze (thicker headroom; re-check pool ≥ 130 / ≥ 100 under §4.5) | drafted-not-evaluated (N-impact: 0) |
| H13 alt: session-relative OFI percentile split (vs trailing-1800 s wired percentile) | drafted-not-evaluated (N-impact: 0) |
| H13 alt: `hard_exit_age_seconds = 2700` (3 × hl) | drafted-not-evaluated (N-impact: 0) |
| H12 primary (PARKED power — closed for this path) | parked; N-impact 0 (census N-neutral); F1–F5 never ran |
| Shared: `WindowKind.ALGO_CLOCK` taxonomy + calendar artifact set | infrastructure; N-impact 0 until paired with an outcome contact |
| session-discipline constants varied | drafted-not-evaluated (N-impact: 0 each) |
| re-thresholded conditioning (any change to 0.80/0.20 split or `w_hr` used as a tuned occupancy) | drafted-not-evaluated (N-impact: 0); evaluation is +1 N |

Carried unchanged (not duplicated): pack-04 / pack-06 / pack-09
drafted rows and closed trials (H1–H11, S-1). None authorized for
evaluation by this spec. H9 remains dead pending extraordinary
justification (pack-11 DISPOSITIONS 3). KYLE_INFO continuation not
authorized (pack-10 DISPOSITION 1).

**N = 12 as of this task** (unchanged; no outcome contact). First
outcome contact on the H13 primary → **N ≥ 13**.

---

## 15. CARD→SPEC DEVIATION TABLE (logged, never silent)

| # | card (original) | spec (tested form) | where / why |
|---|---|---|---|
| 1 | κ central ≈ 0.172 from factor table | freeze **0.172** with factor product **0.189** logged; minimum rule applied; factors not rewritten | §4.1 — Amendment B / 11a DECISION RECORD 1 |
| 2 | density design-central **221.6** (geometry × ASSERTED gw) | backlog-19 rebuild: all-cell **102.0** / viable **≈ 88.5**; geometry 221.6 retained as audit prior only | §4.4 — Amendment C; **SAY SO: viable projection < census floor 100** |
| 3 | pool-collapse "re-check on drop" prose | numeric axis-split frozen for geometry AND rebuilt bases; census verdict mapping covers every partial-pool outcome | §4.5 — Amendment D / pack-11 DISPOSITIONS 7 |
| 4 | gate sketch implicit in conditional-distribution prose | two-sided quintile in gate + evaluate; `scheduled_flow_window_active` in on/off; off_condition releases via interior band with `percentile_margin` + hour-clock-lapse | §5.2/§5.3 — hysteresis must be referenced |
| 5 | hysteresis not YAML-sketched on card | both margins declared and referenced (`posterior_margin: 0.15`, `percentile_margin: 0.15`) | §5.3 — dead-config loader rule |
| 6 | "hour-only ALGO_CLOCK calendars" as YAML authoring | **deterministic subset derivation** from committed half-hour calendars (filter `:00`); not re-authoring | §1.5.2 — Amendment F |
| 7 | F2 prose only | two-arm hour-vs-:30 with adjudicability floors ≥ 100 each; dual-form binding; H12 architecture note (park was power, not F2) | §12 — Amendment E |
| 8 | Implementation: "Calendars + YAML + percentile at h = 1800" | **phased** Ordering B: Phase A = hour-only derivation + census + harness IC row (percentile factory already multi-h); Phase B = full card gated on step-2 PASS | §16 / Next action — Amendment H |
| 9 | D roles from map summary | roles assigned from §4.2 park arithmetic (OLN in D with thin headroom + min-commission trap re-derived; ENSG stays out under 0.16 screen) | §4.2 — Amendment B |

No other substantive deviation exists; hypothesis text, family,
half-life, horizon, archetype, counterparty, κ freeze (minimum rule),
symbol set, F1–F5, power structure, and stop-rule finality are carried
as activated.

---

## 16. DELIVERABLES MAP (phased; nothing implemented here)

### Phase A (pre-Task-8; Ordering B carries — Amendment H)

1. **Hour-only calendar derivation** — deterministic subset transform
   over committed `ALGO_CLOCK` YAMLs for the union of six-symbol
   operative dates (§1.5.2); derived-view hash in provenance; unit
   tests that `:30` marks are excluded and `:00` marks admit
   `contains(boundary_ts)`. Taxonomy already landed — do not reopen.
2. **Census instrument** — deterministic offline pass
   (`PYTHONHASHSEED=0`) over frozen six-symbol × 20-session D:
   calendar-warm fraction under hour-only view, joint conditioning
   occupancy at frozen thresholds, in-hour vs :30 episode counts vs
   §4.4 rebuilt projections (102 / 102 all-cell; viable floors) and
   census floor ≥ 100, `calendar_missing_rate`,
   `tranche1b_kappa_drift`, REPORTS estimands. Measure hour-window
   membership realization (geometry identity pre-registered).
   Measure gate/sign residual on this grid (do not silently import
   H12's 0.3935 as a measured H13 fact). **No forward returns / IC
   in the census instrument itself** unless bundled as the harness
   row below under the same freeze.
3. **Harness IC row** — implementation-independent step-2b statistic
   on the census-pinned predicate (research-workflow Ordering B);
   harness sign-golden required before 2b; pre-register
   census-consistency smoke consequence for Phase B mismatch
   (implementation-correction re-run, N unchanged). **Both F2 arms**
   must be instrumented in the same freeze; F2-INSUFFICIENT if either
   arm's viable-region n < 100.
4. **`ofi_integrated_percentile` at h = 1800** — factory already
   emits for every h (H12 Phase A); Phase A verifies the h = 1800
   instance is consumed (no silent h = 900 substitution). Parity
   assessment if any locked baseline moves — architectural review,
   never a value edit.

### Phase B (gates on step-2 PASS only — Ordering B)

5. `alphas/sig_hour_checkpoint_drift_h1800_v1/sig_hour_checkpoint_drift_h1800_v1.alpha.yaml`
   — schema 1.1 SIGNAL; blocks per §5; horizon 1800; trend_mechanism
   SCHEDULED_FLOW hl 900; `l1_signature_sensors: [scheduled_flow_window]`;
   failure_signature §10; falsification_criteria §12.
6. `configs/bt_sig_hour_checkpoint_drift_h1800_v1.yaml` — pinned 00c
   profile, session knobs, symbol list six-symbol D, hour-only
   calendar injection.
7. Tests: Track-A strength/property tests, gate-DSL compile (both
   margins referenced; hour predicate present), config guard,
   hour-subset derivation goldens, determinism suite.

---

## 17. STATUS

**Status:** `hypothesis → candidate pending validation`

No outcome statistic exists. Statistical validity and execution
validity remain untested. H12 remains **parked (power)** with zero
outcome contact. H13 is the **final card** — death at any gate closes
the program (pack-11 DISPOSITIONS 8). H9 remains dead under the
bidirectional firewall. **N = 12**.

**Appendix P RULING (Lei, 2026-07-17) — FROZEN pre-census.** See
§P.4. Configuration **(B)** + P.3 A-2.1 evidence-pool census floor;
**(C) REJECTED**; zero ingestion; honest κ-viable central ≈ **96 <
100** → **expected PARK**; census runs as measurement. D unchanged
(six symbols). N = 12 unchanged (ruling / freeze only — no outcome
contact).

---

## NEXT ACTION (Amendment H — Task 8 scoping contract)

**Appendix P RULED (§P.4).** Task 8 freezes the ruled configuration
into the validation protocol.

Draft
`docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md`
(Task 8) freezing the park-rule census, consequence-precedence,
magnitude-vs-power labels, both F2-arm adjudicability floors, the
§4.5 pool-collapse verdict map, **and the Appendix-P RULING
(config (B); P.3 A-2.1 evidence-pool ≥ 100 floor; honest expectation
≈ 96 / expected PARK)** — then execute **Phase A** under Ordering B:
(1) land the hour-only calendar derivation from committed
`ALGO_CLOCK` files (§1.5.2), (2) build the census instrument that
measures in-hour / :30 episode counts against the frozen-config
projections and the ≥ 100 census floor over the step-2 evidence pool
(hour-window membership and gate/sign residual measured on this grid
— H12's 0.3935 is characterization only), and (3) land the harness
IC row (sign-golden before 2b; both F2 arms in the freeze). **Phase B
(YAML / config / deployable evaluate) gates on step-2 PASS only.**

---

## Appendix P — POOL CONFIGURATION ARITHMETIC (pre-Task-8 ruling input)

**Scope.** Census-legal only: boundary counts, σ_H distributions,
floor / κ arithmetic. **No forward returns. No IC.**
`PYTHONHASHSEED=0`. Source cells:
`docs/research/artifacts/horizon_feasibility_map_2026-07-11.json`
(ENSG/MLI × 10 cached original sessions; expansion cells remain
DRAWN-NOT-INGESTED — zero new ingestion in this appendix). Arm factors
identical to §4.4 backlog-19 rebuild: `f_resid = 0.3935`,
`w_hr = 0.50`, quintile `0.40`, viable/all haircut `59/68 ≈ 0.8676`
(H12 characterization — not H13 evidence). κ screen for viable cells
= **κ_frozen = 0.172** (not the 0.16-class Lei screen used for D
membership in §4.2).

### P.1 ENSG / MLI honest viability at H = 1800

**Single-stress floors at grid-median prices** (fee-in-bps recomputed;
min-commission `$0.35` on 80-share reference; `floor_P = 2.25 ×
(2.0 + fee_P)`):

| symbol | med bid ($) | fee_P (bps) | floor_P (bps) | trap note |
|---|---|---|---|---|
| ENSG | 181.155 | **0.2415** | **5.0434** | fee ≈ 3× APP's 0.08; not OLN-class (OLN fee ≈ 1.86) |
| MLI | 120.405 | **0.3634** | **5.3176** | fee ≈ 4.5× APP; still well below OLN |

Recompute check at each price point: `0.35 / (med_bid × 80) × 10_000`
matches the artifact to 4 dp; floors match pack-05 §2 (5.04 / 5.32).

**σ₁₈₀₀ and κ_req = floor_P / σ** over the 10 cached sessions
(Hyndman-Fan type-7 quantiles from the artifact):

| symbol | σ med | σ p75 | σ p90 | κ_req med | κ_req p75 | κ_req p90 | vs κ_frozen 0.172 |
|---|---|---|---|---|---|---|---|
| ENSG | 29.79 | 32.41 | 35.44 | **0.169** | **0.156** | **0.142** | med **opens** at 0.172; still **closed** under Lei 0.16-class screen (0.169 > 0.16) |
| MLI | 28.44 | 30.68 | 41.22 | **0.187** | **0.173** | **0.129** | med **closed** (0.187 > 0.172); p75 still closed; p90 opens |

**Viable-region cell counts at κ ≤ 0.172** — session OPEN iff
`floor / σ₁₈₀₀ ≤ 0.172`. Two floor bases reported (honest
min-commission trap):

**(i) Grid-median floor** (map convention — one floor per symbol):

| symbol | OPEN / 10 | elevated OPEN | calm OPEN | OPEN dates |
|---|---|---|---|---|
| ENSG | **5 / 10** | **3** | 2 | elev: 2025-11-25, 2026-04-01, 2026-04-22; calm: 2026-01-15, 2026-01-27 |
| MLI | **3 / 10** | **2** | 1 | elev: 2026-04-01, 2026-04-22; calm: 2026-01-05 |

**(ii) Per-session floor** (fee recomputed at that session's median
RTH bid — the trap check at each price point):

| symbol | OPEN / 10 | elevated OPEN | calm OPEN | flip vs (i) |
|---|---|---|---|---|
| ENSG | **5 / 10** | 3 | 2 | none — all five survive |
| MLI | **2 / 10** | **1** | 1 | **2026-04-01 closes** — bid $112.82 → fee 0.388 → floor 5.373 → κ_req **0.1727 > 0.172** |

**Honest read.** MLI is median-closed at 0.172; its open cells are
mostly elevated under (i) (2/3) and split under the stricter
per-session trap (1/2). ENSG is median-*open* at κ_frozen 0.172
(κ_req 0.169) but remains **out of D** under the binding 0.16-class
screen (Lei DECISION RECORD 1 / §4.2) — its 5/10 open set is not
"mostly elevated" (3/5). Neither name clears a median-open
deployability claim under the screen that governs D; both are at best
evidence-only / session-tail contributors. Expansion σ₁₈₀₀ for the
+20 DRAWN-NOT-INGESTED cells is **unknown** — not projected as
κ-viable fractions below.

### P.2 Episode projections — identical backlog-19 rebuild

Arm identity (every row):

    all-cell = raw × HT × 0.50 × 0.40 × 0.3935
    viable-region = all-cell × (59/68)

HT = **0.90** on every 20-session symbol (2 HOLIDAY-THIN / 20).
ENSG/MLI **original 10** contain no HOLIDAY-THIN dates → HT = **1.0**
on those cells (§4.6 convention). ENSG/MLI **expansion 10** carry
2 HOLIDAY-THIN → HT = **0.80** on expansion alone; combined 20-session
ENSG/MLI ⇒ HT = 0.90.

| config | raw boundaries | HT posture | all-cell | viable-region | vs ≥ 100 viable | vs ≥ 130 all-cell |
|---|---|---|---|---|---|---|
| **(A)** six-symbol D (specced) | 6 × 20 × 12 = **1440** | 0.90 | **102.0** | **≈ 88.5** | **FAIL** | FAIL |
| **(B)** eight-symbol evidence pool; ENSG/MLI evidence-only on **cached 10**; zero ingestion | 1440 + 2 × 10 × 12 = **1680** | D @ 0.90; EM @ 1.0 | **120.9** | **≈ 104.9** | **PASS** (hair) | FAIL |
| **(C)** (B) + ingest ENSG/MLI × 10 expansion (**+20 cells**) | 1440 + 2 × 20 × 12 = **1920** | D @ 0.90; EM-20 @ 0.90 | **136.0** | **≈ 118.0** | **PASS** | **PASS** |

**(A) reproduce check:** `1440 × 0.90 × 0.50 × 0.40 × 0.3935 = 101.9952 ≈ 102.0`;
`102.0 × 59/68 ≈ 88.50` — matches §4.4.

**ENSG/MLI contribution (separate — so C − B is explicit):**

| slice | formula | all-cell | viable @ 0.8676 |
|---|---|---|---|
| ENSG/MLI × 10 cached (HT = 1.0) | 2 × 10 × 12 × 1.0 × 0.50 × 0.40 × 0.3935 | **+18.9** | **+16.4** |
| ENSG/MLI × 10 expansion only (HT = 0.80) | 2 × 10 × 12 × 0.80 × 0.50 × 0.40 × 0.3935 | **+15.1** | **+13.1** |
| **Marginal (C) − (B)** | expansion slice above | **+15.1** | **+13.1** |

Decomposition check: (B) = 102.0 + 18.9 = **120.9**; (C) = 120.9 + 15.1
= **136.0** (equivalently 102.0 + 34.0 from ENSG/MLI × 20 @ HT 0.90).

**κ-viable honesty rider (not a substitute for the identical rebuild
above — a tighter overlay on the ENSG/MLI slice only).** Applying
each name's own OPEN fraction at κ 0.172 instead of H12's 0.8676
haircut to the ENSG/MLI all-cell contribution:

| basis | ENSG open frac | MLI open frac | EM viable contrib | (B) viable = 88.5 + EM | vs ≥ 100 |
|---|---|---|---|---|---|
| grid-median floor (i) | 5/10 | 3/10 | 0.5×9.44 + 0.3×9.44 ≈ **7.6** | **≈ 96.1** | **FAIL** |
| per-session floor (ii) | 5/10 | 2/10 | 0.5×9.44 + 0.2×9.44 ≈ **6.6** | **≈ 95.1** | **FAIL** |

Under this overlay, (B)'s apparent viable PASS (104.9) from the
uniform H12 haircut **does not survive** ENSG/MLI's own median-closed
κ geometry. (C)'s expansion σ is unmeasured — the +13.1 viable
marginal remains a uniform-haircut projection only; it cannot be
tightened the same way without ingestion + census-legal σ refresh.
**D-only viable stays ≈ 88.5 < 100 under every row.**

### P.3 Pool-structure question for Lei's ruling

**Census-floor counting over the step-2 evidence pool (A-2.1
precedent).** Count pooled contamination-excluded viable-region
episodes over D ∪ evidence-only symbols toward the ≥ 100 census
floor, while keeping deployable economics / CPCV / DSR / steps 3–8
strictly D-scoped (A-2.1 orthogonality: statistical power vs
deployable economics are separate axes). Under the identical
backlog-19 rebuild this maps (B) → viable ≈ 104.9 PASS and (C) →
≈ 118 PASS on the uniform haircut — so the spend case can clear the
power floor **without** promoting ENSG/MLI into D, provided Lei
accepts evidence-only boundaries into the census n (and accepts the
uniform 0.8676 haircut on median-closed names, or overrides with the
κ-viable rider that puts (B) back under 100). Pool-collapse verdict
mapping (§4.5) would then re-check the **evidence-pool** projection
after every D-drop; evidence-only names do not drop with D but also
cannot rescue a D that has become economically empty (A-2.1
safeguard spirit: pooled n must not mask a dead primary).

**Deployable-only D (H10 precedent).** Count the ≥ 100 census floor
**only** over symbols in D — evidence-only boundaries may appear in
diagnostics / tick-artifact tests but never toward power (H10's
design had evidence pool = D; the strict reading is the one that
rejected carrying non-D n into the sample floor before A-2.1 carved
the exception). Under that mapping, (A)/(B)/(C) are identical on the
binding bar: viable ≈ **88.5 < 100** regardless of ENSG/MLI cache or
ingestion — §4.6's "evidence-only cells do not repair the deployable
pool's power bar" stands, and the pool-collapse table in §4.5 remains
D-only. Ingestion of the +20 cells is then pure density for a future
card, not an H13 power repair. **Open question closed in §P.4
(Lei, 2026-07-17) — A-2.1 evidence-pool counting RULED.**

### P.4 RULING — POOL CONFIGURATION (Lei, 2026-07-17; pre-census)

Where this section conflicts with §4.3 / §4.6 / §P.3 open text, **this
section governs**. Zero outcome contact; **N = 12** unchanged.
Census-legal only — no forward returns / IC. Zero ingestion.

**(1) Configuration (B) FROZEN; (C) REJECTED.**

| config | ruling | binding content |
|---|---|---|
| **(B)** | **FROZEN** | Eight-symbol step-2 evidence pool on the existing **160-cell** drawn inventory (140 ingested admissible + 20 ENSG/MLI expansion DRAWN-NOT-INGESTED): APP/RMBS ×20; OLN/DIOD/PCTY/CROX ×20; ENSG/MLI ×10 cached originals — as defined in §P.2 (B). ENSG/MLI remain **evidence-only**. |
| **(C)** | **REJECTED** | Second expansion for power-chasing. ENSG/MLI expansion cells stay **DRAWN-NOT-INGESTED**. **Zero ingestion.** |
| **(A)** | superseded as spend default — see amendment below | Six-symbol D-only arithmetic retained as nested subset / audit baseline |

**(2) P.3 RULED — A-2.1 evidence-pool census floor.**

Census park floor ≥ **100** counts over the **step-2 evidence pool**
(A-2.1 lineage): contamination-excluded viable-region episodes pooled
across D ∪ {ENSG, MLI evidence-only}, not H10 deployable-only D.
Floor = step-2 adjudicability guarantee (same numeric bar as
consequence-precedence / F2 arm floors). **D unchanged** (six
symbols: {APP, RMBS, OLN, DIOD, PCTY, CROX}). Deployable economics /
CPCV / DSR / steps 3–8 remain strictly D-scoped (A-2.1 orthogonality).

**ENSG marginality (disclosure, not promotion).** At frozen κ = 0.172,
ENSG κ_req med = 0.169 ⇒ **≈ 1.8% headroom** ((0.172 − 0.169) /
0.172). Recorded as **inside estimation noise** — evidence-only;
**never promotable post-hoc** into D. MLI remains median-closed
(κ_req med 0.187 > 0.172). Lei's 0.16-class D-membership screen
(DECISION RECORD 1) is untouched.

**(3) HONEST EXPECTATION FROZEN — expected PARK.**

Backlog-19-compliant κ-viable central under (B) (§P.2 honesty rider,
grid-median floor basis): viable ≈ **96 < 100**. **Expected PARK
(power).** The census still **runs as measurement** per the pack-10-era
precedent (measurement over projection; final characterization data
this grid produces — H12-class: measured counts govern the park
verdict; the ≈96 figure is the pre-registered expectation, not a
skip-authorization). Design ≥ 130 remains failed under every honest
row; that failure does not authorize expansion.

**(4) (A)-fallback amendment (disclosed reasoning).**

Lei's pre-stated fallback — spend / freeze on configuration **(A)**
(six-symbol D) if evidence-pool expansion were refused — is
**amended**: freeze **(B)** instead. Reasoning disclosed pre-census:
**(B) is a free strict superset of (A)** (same D cells + ENSG/MLI ×10
cached originals already on disk; zero ingestion; no new draw). No
census floor, design bar, κ, honest expectation (≈96), or park-rule
threshold is changed by the amendment — only which already-cached
boundaries may count toward the ≥ 100 floor (P.3 A-2.1). Choosing
(B) is not a power repair and does not authorize (C).

**Task 8 contract.** Protocol freeze copies: config (B); P.3 A-2.1
evidence-pool ≥ 100; D six-symbol; ENSG/MLI evidence-only never
promotable post-hoc; honest expectation ≈96 / expected PARK;
(C) rejected / expansion DRAWN-NOT-INGESTED; zero ingestion.
