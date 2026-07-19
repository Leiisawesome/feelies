<!--
  File:   docs/research/sig_halfhour_clock_drift_h900_v1_formal_spec.md
  Status: hypothesis — parked (power)
          (Task 7 formal spec 2026-07-16; H12 CONFIRMED per pack-11
          DISPOSITIONS 1 + pack-11a DECISION RECORD; Amendments A–G
          applied; park close-out 2026-07-17 — Lei ratifies census
          PARK on power per frozen §1.5 / protocol C.8; N = 12;
          closure: sig_halfhour_clock_drift_h900_v1_result.md).
  Owner:  microstructure-alpha (spec) / research-workflow (ledger);
          prompt-pack Task 7, Phase B (H12).

  Provenance (FQ-3 template):
    git_sha: "40b85bf7dd6a7a80214c8475ca619a788dfab45c" (HEAD at task
      start; this file is the sole intended output)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (design only; every number below is quoted from committed
      artifacts or derived by hand arithmetic recorded inline)"
    normative_inputs (Amendment A):
      prompt_pack_08_frontier_refresh.md (OPERATIVE frontier; κ / floors
        / density basis),
      prompt_pack_11_hypothesis_slate_d.md (H12 card VERBATIM +
        DISPOSITIONS 1–5; H13 contingent triggers),
      prompt_pack_11a_slate_d_review.md (DECISION RECORD; §1
        WINDOW-GEOMETRY AUDIT — 25 bounds/session; 12 in-window /
        13 off; F2 contrast design-central ~160),
      prompt_pack_10_cycle2_retrospective.md (DISPOSITION: cycle-3
        authorization + program stop-rule; SCHEDULED_FLOW substance
        rule; outcome-informed prior disclosure),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.4 —
        quote-fed entry; no NEW trade-fed extreme),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2;
        L1–L5; 140-cell inventory; HOLIDAY-THIN),
      prompt_pack_00b_edge_units_convention.md (one-way),
      prompt_pack_00e_strength_rider_and_thread.md (Track A),
      prompt_pack_00c_eval_canon.md (pinned realism profile),
      prompt_pack_12p_router_fill_timing_parity.md (Task 12-P AXIS-1
        VERIFIED — hard gate cited, not re-run),
      prompt_pack_07_program_retrospective.md (cycle-1 funnel;
        mechanics/convention pointers only — never economic priors),
      prompt_pack_03m_skill_verification.md + research-protocol
        Validation Protocol & Slate Design Discipline (3-M:
        magnitude-vs-power, consequence-precedence, occupancy
        pre-read),
      prompt_pack_backlog.md entries 17–18 (failure-mode triggers;
        REPORTS estimand labeling),
      sig_sweep_kyle_drift_h900_v1_formal_spec.md (H10 Task-7 pattern
        — riders carried; never its values as benchmark),
      src/feelies (scheduled_flow_window sensor, WindowKind taxonomy,
        ofi_raw / ofi_integrated wiring, hazard-exit, layer
        validator, regime gate — read this session; citations inline).
-->

# `sig_halfhour_clock_drift_h900_v1` — formal specification (Task 7)

Candidate **H12** (H11′-class reformalization), confirmed by Lei
2026-07-16 subject to Amendments A–G. This document is the complete
formal specification mapped onto the platform contracts; **no
implementation code ships with it** (the `evaluate` block in §5 is a
normative draft for Phase B / Task 9). **No data contact occurred in
this task** — no forward return, IC, contamination intensity read, or
occupancy measurement.

**Hypothesis (unchanged from the pre-registered card).** Institutional
execution algos slice parent orders on a **30-minute wall-clock grid**
(10:00, 10:30, … ET) **because** schedule adherence and
participation-rate caps are specified in clock time, **which must leak
into L1 as** elevated signed quote-flow imbalance in the
half-hour-aligned decision windows. Residual permanent impact of the
still-open parent continues over the next **H = 900 s**. The clock
binding is load-bearing: the same flow extreme **off** the half-hour
grid must not produce the same continuation.

Conditional-distribution statement: at each in-window H = 900
boundary (25/session), with `ofi_integrated` = Σ per-event L1 OFI over
the trailing 900 s and `W_hh` = the event is inside a registered
`ALGO_CLOCK` half-hour window (`scheduled_flow_window_active = 1` and
window kind / id in the half-hour set):

`E[mid log-return over next H = 900 s | ofi_integrated percentile ≥ 0.80
(two-sided quintile) AND W_hh AND P(vol_breakout) < 0.7] > 0`
(symmetric short for ≤ 0.20), magnitude κ_frozen × σ₉₀₀ with κ
central ≈ **0.146** ⇒ ≈ **7.0 bps** one-way at the APP median session
(pack-08 σ₉₀₀ med 47.7).

Family `SCHEDULED_FLOW`; archetype **schedule-bound flow-following**;
structural counterparty: LPs and discretionary flow that under-react to
predictable clock pressure. Conservation: edge ≤ residual impact of
open scheduled parents across the half-hour grid.
`expected_half_life_seconds = 450` (G16 envelope 60–1800 ✓);
`horizon_seconds = 900`; ratio 2.0 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [scheduled_flow_window]` (G16 rule-5 primary;
`ofi_integrated` is the conditioner, not the family fingerprint).
Evidence / deployable set **frozen {APP, RMBS} pooled** — six others
closed at honest κ @900 (pack-08 §2.4); Tranche-1B cells carry **no
role** in H12 evidence. Mirage: **MIXED (M = 1.5)** — OFI manufacture
risk; clock alignment is structural once calendars are pinned, not
exchange-certified.

**Why H = 900 (not drafted H11's 1800):** pack-11 §0.2 / 11a §1 —
half-hour marks cover **all** H = 1800 boundaries (frac 1.00), so
window-binding F2 is vacuous there. At H = 900, half-hour marks are
12/25 (frac **0.48**); the complementary 13/25 off-clock boundaries
are the F2 contrast set. Horizon placement is required by
falsifiability, not an economic prior.

**H11 form failure structurally impossible here:** (i) G16 fingerprint
is `scheduled_flow_window`; (ii) `W_hh` / `ALGO_CLOCK` sits inside the
conditional-distribution statement; (iii) per-session calendar YAMLs
are named Phase-A deliverables with warm-iff-calendar semantics;
(iv) F2 window-binding is load-bearing with powered contrast arms
(§1.6 / §12).

---

## 1. OBSERVABLE STATE

### 1.1 Sensor table (exact ids, params, warm-up, halt behavior)

| sensor_id | ver | feed | params | warm rule | gap/halt behavior | units / role |
|---|---|---|---|---|---|---|
| **`scheduled_flow_window`** (existing) | 1.2.0 | Quote/Trade (event-time membership only) | calendar injected at construction (`EventCalendar`) | **calendar-warm:** `warm=True` iff calendar has ≥1 symbol-eligible window (universe-wide counts); empty/missing calendar → `warm=False` | **stateless** accumulator — no gap flush; halt does not clear calendar membership; misconfigured date → cold forever that session | tuple `(active, seconds_to_close, id_hash, direction_prior)`; **family fingerprint + `W_hh` predicate** |
| `ofi_raw` | 1.0.0 (existing) | NBBOQuote | `warm_after=50`, `warm_window_seconds=300` | warm ⇔ ≥ 50 OFI-bearing quotes in trailing 300 s event-time | sliding warm deque; sustained gap → cold (S3); degenerate/crossed books dropped (no state poison) | shares signed CKS per-event OFI; **integrand** of conditioner |
| `realized_vol_30s` | 1.3.0 (existing) | NBBOQuote | `window_seconds=30`, `warm_after=16` | warm ⇔ ≥ 16 log-returns in trailing 30 s | window-bounded; un-warms after gaps | unannualised mid log-return std; **gate backstop only** |

**No `spread_z_30d` anywhere** (census warm starvation on thin names;
slate convention). **No NEW trade-fed sensor.** Conditioner is
quote-fed `ofi_integrated` × calendar membership.

**G16 fingerprints:** `l1_signature_sensors: [scheduled_flow_window]` —
sole primary in `_FAMILY_FINGERPRINT_SENSORS["SCHEDULED_FLOW"]`.
`ofi_raw` / `ofi_integrated` are declared on `depends_on_sensors` as
the entry conditioner, not as the family fingerprint.

**TAXONOMY EXTENSION (NEW — not a sensor; calendar contract):**
`WindowKind.ALGO_CLOCK` must be added to
`src/feelies/storage/reference/event_calendar/__init__.py` (today:
`{MOC_IMBALANCE, OPENING_AUCTION, INDEX_REBALANCE, EARNINGS_DRIFT,
FOMC_BLACKOUT}`). Semantic frozen: recurring RTH institutional slice /
checkpoint windows, **universe-wide** (`symbol: null`). Mis-labeling
algo clocks as `INDEX_REBALANCE` / `MOC_IMBALANCE` is **inadmissible**.
Versioned migration + `EventCalendar.hash` baseline refresh required
(Inv-13).

### 1.2 Horizon reducers consumed (feature_id keys, h = 900)

| feature_id | producer | status / note |
|---|---|---|
| `scheduled_flow_window_active` | `TupleComponentFeature` index 0 | wired ✓ — **`W_hh` runtime predicate** (1.0 inside any matching window) |
| `seconds_to_window_close` | `TupleComponentFeature` index 1 | wired ✓ — diagnostic / window-edge discipline |
| `scheduled_flow_window_id_hash` | `TupleComponentFeature` index 2 | wired ✓ — offline kind/id attribution; REPORTS |
| `scheduled_flow_window_direction_prior` | `TupleComponentFeature` index 3 | wired ✓ — ALGO_CLOCK priors frozen at **0.0** (neutral; direction from OFI) |
| `ofi_integrated` | `HorizonWindowedFeature("ofi_raw", 900, reducer="sum")` | wired ✓ — trailing-900 s Σ CKS OFI |
| `ofi_integrated_percentile` | `HorizonWindowedFeature("ofi_raw"→integrated path, 900, reducer="percentile")` — Hazen percentile of current `ofi_integrated` within the trailing 900 s window of integrated readings | **NEW factory wiring required** (Phase A) — not present in `bootstrap.py` today (`ofi_raw` factory emits only `ofi_integrated` sum) |
| `realized_vol_30s_zscore` | `RollingZscoreFeature` | wired ✓ — gate backstop |

Percentile semantics, stated plainly: the wired OFI percentile ranks
`ofi_integrated` against its own trailing **900-second** window of
readings ("recent baseline"), not the session. A session-relative
split is a drafted variant (§14), not silently substituted. Quintile
tails: ≥ 0.80 LONG / ≤ 0.20 SHORT (frozen; occupancy pre-read
**exempt** under 3-M / backlog 15 — percentile-by-construction).

### 1.3 Boundary semantics

`HorizonFeatureSnapshot` carries `values` / `warm` / `stale` keyed by
feature_id. Entry is suppressed unless every id in the alpha's
`required_warm_feature_ids` is warm and not stale; exits are permitted
when stale (Inv-11). The consume-driven required-warm set (statically
parsed `snapshot.values` reads ∪ gate identifiers) is:

    { scheduled_flow_window_active, ofi_integrated_percentile,
      ofi_integrated, realized_vol_30s_zscore }

`depends_on_sensors: [scheduled_flow_window, ofi_raw, realized_vol_30s]`.

**Warm-iff-calendar (H11 structural fix — load-bearing):** for every
`(symbol ∈ D, session ∈ operative 20)`, a calendar YAML **must** exist
containing the half-hour `ALGO_CLOCK` set. Missing/empty calendar →
`scheduled_flow_window.warm=False` → entry suppressed (Inv-11). This
makes the H11 form failure (SCHEDULED_FLOW without calendar instrument)
structurally impossible: a deployable symbol without calendars cannot
arm. Census reports fraction of boundaries with calendar-warm ∧ quote
path live; warm < 0.5 on > 2 sessions drops that symbol from D
(coverage, not tuning).

### 1.4 Session-time discipline (explicit constants)

Fixed constants in `configs/bt_sig_halfhour_clock_drift_h900_v1.yaml`
(not free-range; varying either is +1 N):

- `no_entry_first_seconds: 300` — no entries in the first 5 minutes
  (opening cross + MC Official Open re-print arrival).
- `session_flatten_enabled: true`,
  `session_flatten_seconds_before_close: 600` — entries blocked and
  positions flattened from 15:50 ET; every H = 900 s hold completes
  inside RTH.

All boundary-count arithmetic uses the resulting **09:35–15:50 ET**
in-window count: **25 boundaries / session at H = 900** (pack-08 §1 /
§4; 11a §1 bit-exact on the 140-cell cache). On the 20-session
{APP, RMBS} grid with HOLIDAY-THIN HT = 0.90: raw 500 / symbol.

**Window-edge discipline (frozen):**

1. Decision boundaries that fall exactly on a half-hour mark are
   **in-window** (`W_hh = 1`); the complementary 15-minute marks are
   **off-clock** (`W_hh = 0`) — F2 contrast population.
2. Entries are **not** suppressed solely for proximity to window open/
   close beyond the calendar membership predicate — the claim *is*
   clock-aligned pressure at the mark. A drafted alt that requires
   `seconds_to_window_close ∈ [t_lo, t_hi]` is §14 (+1 N if evaluated).
3. Session flatten at 15:50 does **not** invent a half-hour mark; the
   last in-window H = 900 boundary is 15:45 (11a §1.1).

### 1.5 CALENDAR ARTIFACTS (Amendment C — first-class deliverables)

These are **spec deliverables**, not residual assumptions. Authoring
uses the **exchange schedule only** (NYSE RTH + ET half-hour grid) —
**no tape peeking, no σ, no IC, no forward returns**.

#### 1.5.1 `WindowKind.ALGO_CLOCK` taxonomy

- Add enum member `ALGO_CLOCK = "ALGO_CLOCK"`.
- Loader rejects unknown kinds (existing behavior); tests cover
  round-trip YAML ↔ `CalendarWindow` ↔ hash.
- Semantic: universe-wide recurring institutional slice / checkpoint
  windows. `flow_direction_prior` for all H12 windows = **0.0**
  (direction comes from OFI tails, not calendar prior).

#### 1.5.2 Per-session YAML authoring rule (deterministic)

For every date in the operative {APP, RMBS} 20-session sets
(03c A1.1 ∪ original 10), author
`src/feelies/storage/reference/event_calendar/<YYYY-MM-DD>.yaml`
(merge with any existing OPENING_AUCTION / MOC rows — do not delete
them).

**Half-hour mark set (twelve marks / regular RTH session inside
09:35–15:50):**

    10:00, 10:30, 11:00, 11:30, 12:00, 12:30,
    13:00, 13:30, 14:00, 14:30, 15:00, 15:30   (America/New_York)

(09:30 is outside the 09:35 session window; 16:00 is outside flatten.)

**Interval convention (frozen — must make `contains(boundary_ts)` true
iff the boundary is a half-hour mark on the H = 900 grid):**

    For mark M: half-open window [M, M + 1s) in ET-resolved ns
    (platform `CalendarWindow.contains` = `start_ns ≤ ts_ns < end_ns`).

Rationale: H = 900 decision boundaries sit at exact `:00` / `:15` /
`:30` / `:45`; a 1-second half-open window admits the mark boundary
and excludes the next 15-minute boundary. Lead = 0 (no pre-mark
anticipation in v1). Changing lead/ε is +1 N.

Each window:

```yaml
- window_id: algo_clock_hh_<HHMM>_<YYYY_MM_DD>
  kind: ALGO_CLOCK
  symbol: null
  start_et: "<HH>:<MM>"
  end_et: "<HH>:<MM:01>"   # loader resolves; 1 s duration
  flow_direction_prior: 0.0
  meta:
    card: sig_halfhour_clock_drift_h900_v1
    mark_class: half_hour
```

Provenance: each file content-addressed via `EventCalendar.hash`;
bootstrap calendar hash in run provenance (Inv-13). Fixture dates
today (2026-01-15, 2026-03-24, 2026-03-26) must gain ALGO_CLOCK rows
under the same rule when those dates are in the operative set.

#### 1.5.3 Warm-iff-calendar per deployable symbol

| check | rule |
|---|---|
| Calendar present for session | required for every evidence/deploy date |
| Symbol-eligible windows | universe-wide `symbol: null` ⇒ eligible for APP and RMBS |
| Sensor warm | `warm=False` if calendar empty or no eligible windows |
| Census park | `calendar_missing_rate > 0` after artifacts land → infrastructure FAIL (not an edge fail); warm < 0.5 on > 2 sessions → drop symbol from D |

### 1.6 Geometry audit (Amendment A / 11a §1 — binding on F2)

`PYTHONHASHSEED=0` boundary enumeration (11a; exchange calendar only):

| H | in-window / sess | half-hour (:00/:30) | out of half-hour |
|---|---|---|---|
| 900 | **25** | **12** (frac **0.48**) | **13** |

Matched OFI-quintile design-central populations on APP ∪ RMBS
(HT = 0.90, quintile 0.40, gw = 0.90 × 0.95):

| arm | raw | design-central | vs ≥ 100 |
|---|---|---|---|
| in-window (`W_hh`) | 12 × 20 × 2 = 480 | **147.7** | PASS |
| F2 off-clock | 13 × 20 × 2 = 520 | **160.1** | PASS (larger than in-window) |

F2 is **not** a starved decoration arm. Density identity note (11a
§1.2): H12's 147.7 equals H11's headline by algebra
(`1000 × 0.48 = 480`), not by inheritance — mechanistically distinct.

### 1.7 Contamination posture (03b)

Entry conditioner is **quote-fed** (`ofi_integrated`) × **calendar
membership** (no tape). Class-B prints never enter `ofi_raw`. No NEW
trade-fed extreme conditioner. DI-09 extreme-print finding does not
apply to entry. Contamination-excluded multiplier = **1.0 at design**.

**REPORTS estimands (backlog 18) — labeled at design for freeze:**

| field (proposed) | estimand | expected |
|---|---|---|
| `off_clock_cotravel_rate` | share of quintile-OFI boundaries that are off-clock (geometry diagnostic) | ≈ 0.52 by §1.6 — **not** leakage |
| `calendar_missing_rate` | boundaries with sensor warm=False due to missing calendar | **0** by construction after artifacts land; > 0 → infrastructure FAIL |
| (no `residual_non_a_share`) | — | N/A — no Class-A trade filter on entry |

---

## 2. LATENT-STATE INFERENCE

**Framing (Kyle / Glosten–Milgrom).** The unobserved quantity is the
*schedule-bound residual of open institutional parents* — specifically
whether the quote-flow extreme at a half-hour mark is residual
permanent impact still incomplete at the boundary (parents mid-slice
under clock constraints) or non-scheduled flow that happens to print
an OFI quintile. In Kyle terms: scheduled parents move price through
the MM pricing rule as they work; the clock concentrates their
participation, shifting the population posterior toward unfinished
permanent impact when OFI extremes co-occur with `W_hh`. In
Glosten–Milgrom terms, resting LPs and discretionary flow that
under-weight predictable clock pressure quote under a posterior that
leaves residual edge.

**Cause mixture for the conditioning event**
`E = {ofi_integrated percentile ≥ 0.80 (or ≤ 0.20 short); W_hh;
P(vol_breakout) < 0.7; realized_vol_30s_zscore ≤ 3.0; required
features warm}`:

| θ | latent cause | adverse? | failure shape | treated by |
|---|---|---|---|---|
| θ₁ | clock-sliced institutional parent mid-incorporation (genuine schedule pressure; residual permanent impact) | no — the harvested case; *under-reacting LPs / discretionary* pay | — | — |
| θ₂ | unclocked / discretionary OFI extreme coincidentally inside `W_hh` (no schedule binding) | **yes** | **edge dilution → mild reversal** — temporary impact reverts; clock decoration without substance | **F2 window-binding** (matched OFI quintile off-clock must *not* continue); κ's `f_perm` / `r_rem` price partial non-scheduled share |
| θ₃ | OFI manufacture on a known clock (adversarial quote spoofing / flicker timed to marks) | **yes** | **negative tail, adversarially timed** — collapse after entry; loss a multiple of target edge; dominant operational mirage (MIXED) | hazard exit + hard age 900 s; gate-off on breakout / vol z; L5 ledger treatment |
| θ₄ | public-news / auction / other scheduled-flow already impounded at the mark (zero remainder) | no trader to harvest | **edge dilution** | session discipline (§1.4); structural-boundary screen; under-represented on event-free grid — external-validity caveat (§9) |
| θ₅ | mechanical artifacts: tick-grid discreteness, halt/warm residue, calendar mis-authorship | no | **edge dilution** (or sign-flip noise if calendar wrong) | §8 R8 stratification; warm-iff-calendar (§1.3); census `calendar_missing_rate` |

The decision rule and hazard exit treat the shapes differently: the
**tail** component (θ₃) gets state-dependent exits (hazard spike,
gate-off FLAT, hard age 900 s) because holding through manufactured
collapse is where capital dies; the **dilution** components
(θ₂/θ₄/θ₅) are measurement and attribution problems — **F2 is the
load-bearing falsifier for θ₂** (clock decoration); no exit rescues an
entry that never had scheduled-flow substance.

**What the posterior cannot resolve at L1 (loss-ledger tie).** Per
episode, whether an OFI extreme is schedule-bound residual vs
unclocked flow is undecidable from the quote tape alone — the calendar
supplies the clock predicate, not the parent. Depth beyond BBO is
unobserved (L1); queue position of our passive entry is unobservable
(L2); cancel vs trade contribution inside CKS OFI is indistinguishable
per event (L5); aggressor/informedness of any coincident prints is
unlabeled (L6). Every one of these is resolved only distributionally:
the posterior over θ is a population claim tested by F1–F3, never a
per-trade classification. **F2's out-window arm, if it shows
continuation, is a contaminated diagnostic about a dead claim**
(pack-11 DISPOSITIONS 3) — never reused as KYLE / H9 confirmation.

---

## 3. PROCESS MODEL

**Named model: schedule-constrained parent residual-impact drift
(partial-adjustment continuation conditioned on ALGO_CLOCK membership).**
Institutional parents work under clock-time participation caps; at
half-hour checkpoints the signed quote-flow intensifies; the mid path
toward full incorporation of the still-open parent remains a
persistent drift with exponentially decaying remainder — pre-registered
half-life 450 s, mean lifetime τ = 450 / ln 2 ≈ 649 s, fraction of the
remainder captured by the horizon `f_H = 1 − e^(−900/649) ≈ 0.75` (the
κ factor in §4). The observable pair is the model made visible:
extreme `ofi_integrated` is the flow fingerprint; `W_hh` is the
schedule fingerprint that attributes the fingerprint to clock-bound
parents rather than ambient OFI continuation.

Against the shipped alternatives:

- **HMM / semi-Markov regime persistence** (`services/regime_engine.py`,
  `hmm_3state_fractional`): supplies the *exclusion stratum*
  (`P(vol_breakout)`), not the incorporation dynamics — its dwell is
  the wrong clock for a 450 s schedule residual. Caveat carried from
  `platform.yaml`: with `transition_time_scaling` OFF (default,
  protecting locked Level-5/6 baselines) the transition matrix
  applies once per inbound quote, so regime dwell is measured in
  *ticks* and drifts ~10× with intraday quote intensity. The gate is
  a conservative filter whose per-stratum discriminability Task 8 must
  report (gate dwell in seconds, per symbol) — never a calibrated
  dwell model for the half-hour claim.
- **Hawkes self-excitation** (`hawkes_intensity`,
  `scripts/calibrate_hawkes.py`): describes *arrival clustering* with
  no schedule content — the loading phase of a burst. A Hawkes-framed
  version would be burst-following at marks, i.e. precisely the θ₃
  manufacture confound. Survives as caution: elevated branching ratio
  *without* clock binding in conditioned episodes is evidence for θ₃ —
  offline diagnostic, never the model.
- **Drift-diffusion** (`snr_drift_diffusion` sensor, dormant): closest
  shipped formalism for permanent/temporary decomposition; a DD-SNR
  read on in-window vs off-clock episodes is a natural Task-8
  diagnostic. Not adopted as the runtime model — sensor dormant (new
  wiring / parity surface for zero entry-rule content) and SNR alone
  does not carry the schedule attribution that makes this card
  falsifiable (F2).
- **Unclocked Kyle / OFI continuation** (H9 / H10's model class):
  structurally the **adjacency risk** this card exists to separate.
  Not adopted as the process model — Lei selected SCHEDULED_FLOW with
  mandatory window-binding precisely so an OFI-quintile continuation
  without clock substance dies at F2 rather than silent-smuggling into
  KYLE revival (pack-11 DISPOSITIONS 3 firewall).

---

## 4. PARK-RULE ARITHMETIC (Amendment B — κ FROZEN at 0.146)

**Units (00b, THE CONVENTION):** one-way, per-fill, bps of fill
notional throughout. Round-trip figures derived, never disclosed.

### 4.1 Frozen κ decomposition (card block 1, carried VERBATIM)

    edge_ow = κ × σ₉₀₀ ,   κ = c_D × f_perm × r_rem × f_H × f_pass

| factor | central (frozen) | grounding |
|---|---|---|
| `c_D` | **1.15** | half-hour-aligned quintile (weaker than decile; stronger than unclocked) |
| `f_perm` | 0.52 | scheduled residual permanent share |
| `r_rem` | 0.50 | detection mid-parent |
| `f_H` | 0.75 | 1 − e^(−900/τ), τ = 450/ln 2 |
| `f_pass` | 0.65 | passive same-side pullback haircut |

    κ = 1.15 × 0.52 × 0.50 × 0.75 × 0.65 = 0.1458375 ≈ **0.146** — FROZEN

**Reviewer verification (11a H12 check d):** recomputed product
**0.1458 ≈ 0.146** — **matches** the card freeze. Amendment B minimum
rule: on any discrepancy take the **minimum** of stated freeze and
factor product and **log** the gap. **H12: no discrepancy** (unlike
H13's logged 0.172 vs 0.189 bug — irrelevant to this card's freeze;
recorded only so the minimum-rule convention is auditable).

**One-way ratchet:** no upward re-estimation of κ or any factor after
any data contact; revisable down on evidence only. Once the Task-8
census / measured conditional edge exists, that measurement
**supersedes the derivation entirely** — κ-arithmetic fixes the
pre-data viable region and the park decision, never quoted as a
result afterward.

### 4.2 Single-stress floors and park arithmetic (VERBATIM from card)

Single-stress anchor (pack-08): `floor = 2.25 × (2.0 + fee)` — Inv-12
1.5× applied **once**; never stacked with a simultaneously stressed
adverse-selection vertex. Pack-08 floors: APP **4.68**, RMBS **5.51**
bps passive.

| symbol | κ·σ₉₀₀,med | floor | κ_req med | verdict |
|---|---|---|---|---|
| APP | 0.146 × 47.7 ≈ **6.96** | 4.68 | 0.098 | **OPEN** — headroom ≈ 1.49× |
| RMBS | 0.146 × 47.3 ≈ **6.91** | 5.51 | 0.117 | **OPEN** — headroom ≈ 1.25× |
| six others | κ_req med ≥ 0.16-class closed | — | — | CLOSED at median honest κ — **not deployable** |

**Short-side rider restatement chain (VERBATIM from card):**

Short-side rider (APP): floor ≈ 2.25 × (2.0 + 0.08 + 0.507) ≈ 5.82 ⇒
κ_req 5.82/47.7 ≈ **0.122** ≤ 0.146 — clears. RMBS short: ≈ 6.60/47.3
≈ **0.140** ≤ 0.146 — clears thinly. Pre-stated: if census-measured
short edge fails rider-inclusive floor on a symbol, that symbol
restates **long-only** and power is re-checked under the pooled
structure — no threshold tuning.

### 4.3 Power structure DECLARED AT DESIGN (VERBATIM — freeze-ready)

| role | symbols | basis |
|---|---|---|
| **Deployable (D)** | {APP, RMBS} | both median-open at κ_frozen (§4.2) |
| **Evidence-only** | — | none at design for this card; six others closed at honest κ @900; **OLN remains the designated discreteness case for §8 only** (never deployable on this card) |
| **Evidence structure** | **pooled** APP ∪ RMBS | primary RankIC / power counts on the pool; per-symbol diagnostics reported but **do not** govern the step-2 power bar |

**Consequence-precedence sketch (must be copied into the protocol
freeze before any instrument runs — VERBATIM; backlog-13/17: any
undefined intersection is a freeze-blocking defect):**

1. Primary §12 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK: design headline
   ≥ 130; census park floor ≥ **100** (D-C1). A single-symbol
   shortfall inside the pool does **not** park if the pool clears —
   unless that symbol also fails deployability park arithmetic, in
   which case it drops from D and the pool is re-checked vs ≥ 100.
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. **F2 window-binding** (mechanism): fail → REJECTED (substance),
   regardless of RankIC magnitude/sign. Label at freeze: mechanism /
   n-invariant for the binding claim.
5. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

**Contingent-trigger failure modes (H13 held CONTINGENT — pack-11
DISPOSITIONS 2; backlog 17):**

| # | H12 mode | H13 posture |
|---|---|---|
| **(a)** | H12 **design/census death** | **ACTIVATES.** κ remains **frozen at 0.172** (minimum rule vs factor product 0.189 — arithmetic bug logged in 11a §2 H13 check d; factors not restated). Pool-collapse floors (11a §2e) **must** be frozen into any H13 protocol before census. |
| **(b)** | H12 step-**2b fail** with **F2-binding PASS** | **ACTIVATES.** Sibling arithmetic disclosed; honest-N entry as H13's own trial at first outcome contact. |
| **(c)** | H12 step-**2b fail** with **F2-binding NEGATIVE** | **Activation only after Lei reviews** F2 by window type (disclosed outcome-contaminated; extraordinary bar). |

### 4.4 Density with margin (design-central; geometry-grounded)

Percentile quintile **0.40** — occupancy pre-read **exempt**.
`w_hh = 0.48` is **grid-geometry identity** (verifiable from boundary
timestamps alone — §1.6), not a distributional tape prior. Boundary
basis: 25 × 20 = 500 in-window / symbol; HT = 0.90; gate × warm =
0.90 × 0.95; contamination-excluded × 1.0.

| set | arithmetic | expectation | vs ≥ 130 design / ≥ 100 census |
|---|---|---|---|
| APP alone | 500 × 0.90 × 0.48 × 0.40 × 0.90 × 0.95 | **73.9** | FAIL per-symbol |
| RMBS alone | same | **73.9** | FAIL per-symbol |
| **APP ∪ RMBS pooled** | 1000 × 0.90 × 0.48 × 0.40 × 0.90 × 0.95 | **147.7** | **PASS** |

Conditioning fraction stated: **0.48 × 0.40**. Decile joint
(0.48 × 0.20) → 73.9 pooled — **fails** design margin; not used.
Census still **measures** realized in-window count and parks on power
if the joint falls below the floors.

Park conditions, pre-registered for census: (i) edge-region emptiness
— measured conditional edge below per-symbol single-stress floor on
every deployable symbol; (ii) power — pooled contamination-excluded
episodes < 100 (census) / design headline miss vs ≥ 130 at freeze.
Either parks before any IC outcome is treated as a PROCEED.

---

## 5. DECISION RULE (platform terms)

### 5.1 Free-range parameters (≤ 3 — template discipline)

| param | type | default | range | meaning |
|---|---|---|---|---|
| `ofi_percentile_min` | float | 0.80 | 0.75 – 0.85 | p₀: minimum `ofi_integrated_percentile` for LONG (symmetric 1−p₀ for SHORT); can only tighten from the gate's arming 0.80 |
| `edge_scale_bps` | float | 9.0 | 5.0 – 14.0 | linear edge attribution per unit normalised OFI exceedance; **provisional pending calibration** — G12 disclosure uses the measured value |
| `edge_cap_bps` | float | 12.0 | 8.0 – 20.0 | hard cap on emitted `edge_estimate_bps` |

Fixed constants (not free-range; varying any is +1 N): the quintile
split 0.80 / 0.20 (frozen at the card); `W_hh` membership via
`scheduled_flow_window_active == 1`; per-symbol single-stress floors
(§4.2), embedded as literal dicts; session knobs (§1.4); gate
thresholds (§5.3); ALGO_CLOCK interval convention (§1.5.2).

### 5.2 `evaluate(snapshot, regime, params)` — pure logic (normative draft; Phase B implements)

G5 purity: no imports, no I/O, no state; deterministic in its inputs.
Reads literal snapshot keys only (consume-driven required-warm,
§1.3).

```python
signal: |
  def evaluate(snapshot, regime, params):
      ofi = snapshot.values.get("ofi_integrated")
      pctl = snapshot.values.get("ofi_integrated_percentile")
      w_hh = snapshot.values.get("scheduled_flow_window_active")
      if ofi is None or pctl is None or w_hh is None:
          return None
      # Track-A / Inv-11: garbage inputs suppress entry, never create exposure
      if ofi != ofi or pctl != pctl or w_hh != w_hh:  # NaN reject
          return None
      if ofi == ofi and (ofi > 1e308 or ofi < -1e308):
          return None
      if pctl == pctl and (pctl > 1e308 or pctl < -1e308):
          return None

      # Clock predicate — load-bearing (H11 structural fix)
      if w_hh < 0.5:
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

      floor_bps = {"APP": 4.68, "RMBS": 5.51}.get(snapshot.symbol)
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
          strategy_id="sig_halfhour_clock_drift_h900_v1",
          direction=direction,
          strength=strength,
          edge_estimate_bps=edge_bps,
          trend_mechanism=SCHEDULED_FLOW,
          expected_half_life_seconds=450,
      )
```

Strength construction (00e Track A rider, adopted verbatim):
`strength = min(max(0.0, excess), 1.0)` with `excess ∈ [0, 1]` by
construction at any reachable entry. Phase B / Task 9 gains the
rider's two tests: (i) unit test asserting `strength ∈ [0, 1]` across
the full declared parameter ranges; (ii) Hypothesis property test
driving snapshot values adversarially (NaN, ±inf, extremes, missing
keys, `w_hh=0`) asserting `None` or in-range strength and
non-negative finite `edge_estimate_bps`.

Deliberately **not** in the runtime rule: any runtime σ estimate as
edge scale; off-clock diagnostic features; session-relative
percentile (drafted §14). Short-side caveat (00c profile): SSR
modeling and HTB fees are inert on the pinned profile — SHORT-side
evidence is optimistic on those axes; carried with the §4.2
restatement chain.

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
`(0.20 + 0.15, 0.80 − 0.15) = (0.35, 0.65)` — a mechanism-lapse exit
(OFI no longer extreme ⇒ flow story no longer active). Gate-off when
`scheduled_flow_window_active < 0.5` is the **clock-lapse exit** —
leaving an ALGO_CLOCK window ends the schedule premise. Gates fail OFF
on missing bindings or non-discriminative posteriors (fail-safe). The
vol-z clause is the sensor-level backstop for the HMM tick-based-dwell
weakness (§3).

### 5.4 Hazard exit block

```yaml
hazard_exit:
  enabled: true
  hazard_score_threshold: 0.85     # controller default
  min_age_seconds: 30              # controller default
  hard_exit_age_seconds: null      # -> derived 2 x expected_half_life_seconds = 900 s
```

`RegimeHazardSpike` is an exit-direction hint only (Inv-11);
`HARD_EXIT_AGE` fires at **900 s** (2 × hl 450, platform HM-1
derivation), bounding θ₃ tail exposure. Exits also fire on regime-gate
OFF (conservative FLAT close path, including clock-lapse and OFI
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
  edge_estimate_bps: 6.96    # kappa 0.146 x sigma_900 APP median; measured value supersedes
  half_spread_bps: 0.0       # maker: no crossing
  impact_bps: 2.0            # passive adverse selection charge (00c pin)
  fee_bps: 0.08              # commission floor at reference fill scale, APP anchor
  margin_ratio: 3.35         # 6.96 / 2.08; reconciles +/- 0.05 absolute; >= 1.5 (G12)
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
against clock-bound parents in the conditioned in-window episodes —
measured, not asserted. Design: over the full regime-balanced evidence
grid, compute (a) the funding pool — for each conditioned in-window
episode, the measured continuation move times the contra-side
(resting / faded) volume that traded against the OFI direction inside
the episode window; (b) the strategy's integrated pre-cost conditional
edge at declared participation (≤ top-of-book scale — participation
share must be stated). **Pass:** (b) ≤ participation share × (a)
within estimation error. **Fail (misattribution):** integrated edge
exceeding what counterparty losses can fund — the edge, if real, comes
from something unnamed and the card is wrong even if profitable.
Companion conservation checks: (i) unconditional forward returns over
all matched in-window boundaries must integrate to ≈ 0 over the
regime-balanced sample (no ambient-momentum subsidy); (ii) the
**off-clock matched-OFI stratum** (`W_hh = 0`, same quintile gate) is
exactly F2 — if it continues at the same sign/magnitude class, the
clock does no work and the card is an unpre-registered OFI-continuation
hypothesis — dead by its own terms (and the out-window arm is then a
**contaminated shelf**, pack-11 DISPOSITIONS 3).

**I-2 (side symmetry).** The mechanism is side-symmetric: conditional
continuation on buy-OFI extremes (LONG) and sell-OFI extremes (SHORT)
inside `W_hh` must agree within sampling error in the benign stratum.
Persistent asymmetry beyond noise ⇒ contamination (ambient drift
leakage, short-side constraint artifacts) — investigate before any
deployment claim. The SHORT side additionally carries the §5.2
SSR/HTB optimism caveat and the §4.2 long-only restatement rule (an
*economic* asymmetry pre-stated at design — floors, not mechanism;
I-2 tests the pre-cost mechanism symmetry).

**I-3 (clock / flow co-travel — mechanism attribution).** If schedule
binding identifies residual parent impact, conditioned in-window
episodes must show continuation that the matched off-clock OFI-quintile
population does **not** share (F2). No differential ⇒ OFI extremes are
unclocked continuation (θ₂) — mechanism attribution fails even if
pooled in-window continuation is positive. Calendar-missing or
wrong-window authorship that spuriously creates `W_hh` is an
infrastructure fail (`calendar_missing_rate` / warm starvation), not
an edge claim.

---

## 7. TICK-CONSTRAINT ARTIFACT ANALYSIS (R8)

**Does the state-variable definition survive a tick-regime shift?
Yes — the definition; only parameters need re-estimation.** The
state variables are (i) **calendar membership** `W_hh` — a pure
exchange-schedule predicate, not a tick-grid object — and (ii)
**volume-signed CKS integrated OFI** — dimensionless in definition
relative to share flow, not a tick count. What the grid quantizes is
the mid path that *funds* the edge (continuation in ticks). Coarse
grids can make continuation mass sit at half-tick quanta — but they
do not redefine what a half-hour mark or an OFI event is.

**Grounding in realized buckets (03c §7):** pooled median
spread-in-ticks — APP / RMBS wide/unconstrained (deployable set
structurally grid-free at the H = 900 conditioning scale);
**OLN = discrete/near-constrained — the designated discreteness case,
evidence-only (never deployable on this card; closed at honest κ
@900).**

**Explicit test design (pre-registered; OLN evidence-only):**

1. Report the spread-in-ticks distribution **at signal boundaries**
   (not pooled) per symbol — OFI×clock extremes may select thin-book /
   wide-spread states the pooled medians hide.
2. **≥ 4-tick-stratum re-derivation:** re-estimate the conditional
   900 s continuation using only in-window boundaries with prevailing
   spread ≥ 4 ticks (APP/RMBS qualify structurally). Survival
   criterion: the ≥ 4-tick-stratum edge consistent with the
   full-sample estimate; collapse ⇒ pooled effect was grid artifact
   (θ₅).
3. **OLN quantum test (persistence vs grid discreteness —
   evidence-only):** on OLN, compare the conditional 900 s move
   distribution against the ±1-half-tick quantum: continuation mass
   sitting at exactly the quantum with no continuous tail ⇒ grid
   bounce, not schedule residual; genuine persistence must show mass
   beyond one quantum and σ-normalised agreement with the wide-bucket
   estimate. OLN never enters D or the pooled RankIC bar.
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
| L1 depth beyond BBO | clock-bound parents may be working size the BBO cannot show; mechanical quote pressure at marks can be depth-starvation, not residual impact (θ₂ confound) | Treated distributionally via F2 (off-clock matched OFI must not continue) and top-of-book sizing so no beyond-BBO liquidity claim is made; forced exits inherit the platform's capped walk-the-book impact model. |
| L2 queue composition / position | passive entry into a continuation move is conditionally adverse — the limit order fills preferentially when the move stalls or retraces (fill ⇔ continuation weakening) | Adopted as **first-class** (§11): the platform's seeded-Bernoulli fill hazard is the probabilistic model and its conservatism is *tested* via the §11 sensitivity grid and the filled-vs-unfilled markout diagnostic — for a continuation card this is the likeliest F4 exit and is pre-declared as such. |
| L3 venue fragmentation | displayed NBBO ≠ single-venue accessible size; fee economics blended | Accepted as systematic noise under the flat blended maker/taker pins; the conditioner uses consolidated quote OFI + SIP calendar time, not a venue-local size claim — no per-venue feature proposed or dropped. |
| L4 hidden/midpoint liquidity | hidden absorption completes incorporation without printing — the remainder vanishes silently (dilution of `r_rem`) | Treated distributionally: no per-episode claim; `trade_through_rate` available as an offline prevalence diagnostic per stratum; `r_rem = 0.50` already prices partial invisibility and is one-way-ratchet revisable down. |
| L5 cancel attribution / displayed-size manufacture | CKS OFI conflates cancels, replenishment, and trades; adversarial quote manufacture timed to known clocks is the dominant MIXED-mirage path (θ₃) | Feature kept with mirage M = 1.5 disclosed; no order-level cancel filter exists on L1 — defense is F2 (manufacture that is purely clock-decorative fails substance when off-clock also "works"/in-window fails) plus hazard/gate-off bounding θ₃ tails; `quote_flicker_rate` available offline per stratum, not on the entry path. |
| L6 aggressor signing / informedness | quote-fed OFI does not require trade aggressor labels; coincident print signing is not on the entry path | **Quote-OFI path:** no tick-rule entry variable (contrast H10 SFI); informedness of parents remains a population claim tested by F1/F2, never a per-print label; flat adverse-selection bps by fill type remain the cost treatment (00c). |
| L7 latency microstructure | none claimed | 20 ms visibility + 50 ms fill = 70 ms ≈ 0.016 % of the 450 s half-life — no latency edge asserted; zero-latency configs invalid for evidence (00c decision A). |

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
(ii) L3 lands directly: RMBS is both the most heavily conditioned grid
subsample AND a deployable symbol — every RMBS figure carries the L3
flag; the coverage drop rule is its pre-registered exit. (iii)
Calm-stratum conclusions carry the L1 qualifier verbatim. (iv) L5
binds elevated-A reporting. (v) θ₄ news/auction confound is
*under-represented* on the event-free grid — external-validity caveat
on any deployment claim. (vi) OQ-3 caveat: mechanism-share runtime not
active; vendor V-1: grid inside pre-2026-04-27 cap.

---

## 10. KILL CONDITIONS (per regime axis: parameters vs definition, as the platform triple)

For each axis: what a shift breaks; then the three artifacts the
platform consumes — `falsification_criteria` prose,
`failure_signature` clause (G16 rule 6), and the `regime_gate`
`off_condition` term where run-time gating is the right control.

| axis | shift → breaks | falsification_criteria (prose) | failure_signature clause | runtime gate term |
|---|---|---|---|---|
| **Spread** | transient widening → MM stress, passive economics invalid (**gate** — `vol_breakout` posterior IS the spread/stress gate here); persistent level/bucket migration → **parameters** (floors, fee table); continuation sign reversing across spread-in-ticks strata within the benign stratum → **definition (kill)** — OFI×clock was reading stress state, not schedule residual (F3) | "sign(conditional 900 s forward return) reverses across spread-in-ticks strata within the benign in-window stratum" | `"sign of conditional forward return reverses across spread-in-ticks strata within the benign stratum"` | `P(vol_breakout) > 0.7 + posterior_margin` |
| **Volatility** | disorderly breakout → cascade / manufacture risk dominates (**gate**); secular σ-regime change → **parameters** (edge_scale / G12 disclosure re-derive from measured edge — never in-place κ edits); benign-stratum continuation flipping to reversion → **definition (kill)** — the premise (in-window OFI quintile continues) is dead (F1) | "in-window ofi_integrated_percentile boundaries (≥ 0.80 or ≤ 0.20) in the benign stratum show 900 s forward-return sign agreement ≤ 0.50 over any rolling 20-session window" | `"in-window extreme ofi_integrated_percentile boundaries show 900 s forward-return sign agreement <= 0.50 over any rolling 20-session window"` | `realized_vol_30s_zscore > 3.0` (sensor backstop for HMM tick-dwell weakness) |
| **Liquidity** | MDI round-lot / depth-scale change → **parameters** (sizing scale, fee table); quote-warm / calendar-warm decay → **coverage rule** (warm < 0.5 on > 2 sessions drops the symbol, §1.3 — not a kill); in-window continuation ceasing to differ from matched off-clock OFI → **definition (kill)** — the clock fingerprint carries no substance (F2) | "conditional forward return at matched ofi-quintile extremity is indistinguishable (\|Δ\| ≤ 1 SE) between W_hh=1 and W_hh=0 strata" | `"matched ofi-quintile continuation on off-clock boundaries indistinguishable from in-window continuation"` | clock-lapse: `scheduled_flow_window_active < 0.5`; OFI mechanism-lapse: percentile returns inside `(0.20 + percentile_margin, 0.80 - percentile_margin)` |
| **Tick-constraint** | scheduled Rule 612 half-penny boundary (Nov 2027) → **hard structural split, pre-registered**; bucket migration of a symbol → **parameters**; failure of the §7 ≥ 4-tick re-derivation or the OLN quantum test pattern appearing on a deployable symbol → **definition (kill on the affected stratum)** | "the conditional edge does not survive re-derivation on the spread ≥ 4 ticks stratum, or conditional move mass sits at the ±1 half-tick quantum with no continuous tail" | `"conditional edge on the >=4-tick spread stratum inconsistent in sign with the pooled estimate"` | none — measurement stratification, not gateable |
| **Scheduled-flow / news** | auction windows → **config** (session discipline §1.4); a change in auction/dissemination mechanics or half-hour institutional practice → declared structural boundary; edge concentrating *only* in non-ALGO_CLOCK scheduled-event-adjacent or news-print windows → **definition (kill)** — the counterparty would be event flow and the remainder already impounded (θ₄); **calendar/taxonomy defect** → infrastructure FAIL under stop-rule (program-closing if form FAIL) | "conditional edge concentrates in boundaries adjacent to non-ALGO_CLOCK scheduled events/news prints and vanishes on ALGO_CLOCK marks in the session interior; OR calendar_missing_rate > 0 after artifacts land" | `"conditional edge on ALGO_CLOCK in-window boundaries indistinguishable from zero while event-adjacent non-ALGO_CLOCK boundaries carry it"` | config: `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600`; runtime: `scheduled_flow_window_active < 0.5` |

Plus the standing structural boundaries (F5, pre-registered once):
Rule 612; MDI round-lot reassignments; the 2026-04-27 vendor
admissibility split (post-2026-04-27 sessions inadmissible).

---

## 11. FILL-MODEL DEPENDENCY — FIRST-CLASS (rider carry)

This card's execution posture is **passive entry into a continuation
move** — the structurally adverse fill geometry (the resting order
fills when the move retraces or stalls; the L2 row). The crowd's
clock-bound parents take or lean; we rest. F4 is therefore the
pre-declared likely exit, and the evidence requirements are binding:

**(a) Passive-fill-quality diagnostics (every H12 evidence run reports):**

- **Fill-mix realism:** distribution of fill outcomes from
  `passive_fill_stats()` — level/drain vs through fills, partial-fill
  slices, `EXPIRED` (timeout-cancel) rate, and time-to-fill vs the
  3-tick delay + hazard model. For a continuation card the trap reads
  *inverted* relative to a fade: a fill mix dominated by
  **retrace/drain fills followed by non-resumption** means entries
  are systematically acquired exactly when the continuation premise
  has already failed — the execution-layer signature of θ₂/θ₃.
- **Conditional adverse selection:** post-fill markouts at 450 s and
  900 s on *filled* signal boundaries vs the same conditional forward
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

**(c) Task 12 parity is a HARD GATE for any H12 evidence** — no number
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

## 12. FALSIFICATION CRITERIA (consolidated; F2 load-bearing — Amendment D)

### 12.1 F1–F5

- **F1 (forward test, honest-N):** continuation-signed conditional
  900 s forward return ≤ 0 at the joint in-window condition, or below
  the honest-N noise ceiling `expected_max_sharpe(n_trials=N, …)` with
  N from the living ledger → dead. Clause: `"in-window extreme
  ofi_integrated_percentile boundaries show 900 s forward-return sign
  agreement <= 0.50 over any rolling 20-session window"`.
- **F2 (mechanism tie — window-binding; LOAD-BEARING FALSIFIER):**
  both arms pre-registered (§1.6 populations):
  - **In-window arm (`W_hh = 1`):** design-central ≈ **147.7** matched
    OFI-quintile episodes (APP ∪ RMBS).
  - **Out-window arm (`W_hh = 0`):** design-central ≈ **160.1** matched
    OFI-quintile episodes (APP ∪ RMBS).
  **Window-binding clause (dual form):**
  1. *Substance form:* if the matched ofi-quintile conditioning on
     off-clock boundaries shows continuation of the **same
     sign/magnitude class** as the in-window arm → claim refuted
     (clock decoration, not scheduled flow).
  2. *Differential form:* in-window continuation must exceed
     off-clock continuation by a pre-registered margin (frozen in the
     validation protocol before instruments run); absence of
     differential ⇒ F2 FAIL.
  Clause: `"matched ofi-quintile continuation on off-clock boundaries
  indistinguishable from in-window continuation"`.
- **F3 (regime/stratum):** sign reversal across spread-in-ticks strata
  → definition kill; benign-stratum flip to reversion → premise dead.
- **F4 (execution validity):** §11(d) verbatim, evaluated per-symbol
  against the §4.2 single-stress floors, across the §11(b) grid, only
  on Task-12-parity-cleared machinery.
- **F5 (structural boundaries):** the three pre-registered hard splits
  (§10 footer); never pool across.

### 12.2 F2 firewall (pack-11 DISPOSITIONS 3 — binding)

| direction | rule |
|---|---|
| **H12 → H9** | H12 evidence **never cites toward H9 revival**. An H12 **F2-pass** strengthens H9's presumptive death (clock-bound OFI is not KYLE rehabilitation of unclocked OFI continuation). An H12 **F2-fail** out-window arm that shows continuation is a **contaminated shelf** — diagnostic about a dead claim; not extraordinary justification for H9; not a KYLE attribution restore; **not reusable as confirmation evidence** for H9 or any future unclocked-OFI card without Lei extraordinary review. |
| **H9 → H12** | H9 history (dead claim, untested OFI KYLE @900, adjacency prose) **never prejudices H12 scoring** — κ, RankIC bars, census floors, F1/F2 adjudication, or stop-rule accounting. H12 is evaluated fresh against its own gates (session constraint 6). |

Any DSR computed downstream uses the then-current ledger N
(`build_dsr_evidence(trials_count=N)`).

---

## 13. OUTCOME-INFORMED PRIOR DISCLOSURE (Amendment E — Addendum-G table)

| prior | source | use on this card | status |
|---|---|---|---|
| H = 300 → H = 900 RankIC magnitude (0.0186 → 0.0893) | H8/H10 POST-HOC shelf (`sig_dislocation_lambda_drift_v1_result.md`; `sig_sweep_kyle_drift_h900_v1_result.md`) | **Horizon selection discussion only** — supported placing the reformalized claim at H = 900 rather than forcing a vacuous H = 1800 half-hour design; **never** used to set κ, RankIC bars, or as proof | disclosed; not evidence |
| H10 F2 KYLE miss at H = 900 (λ contrast −0.014; volume −19,407) | H10 S.8 / result §7 | Motivates family switch to SCHEDULED_FLOW (authorized region); **not** a magnitude prior for this card | disclosed |
| H10 magnitude PASS (+0.0893) with significance FAIL | H10 S.8 | **Not** imported as a κ or bar prior; power-structure lessons (pooled census ≥ 100) are conventions only | disclosed |
| Cycle-1/2 warm / ISO / occupancy diagnostics | H2/H8/H10 censuses | Conventions only (no `spread_z_30d`; percentile tails exempt; D-C1 ≥ 130 design / ≥ 100 census) | disclosed |
| RMBS +0.226 shelf | H10 result-doc | **N ≥ 13** before any use; **not consumed** in κ, density, bars, or ranking | disclosed; unused |
| H11 form FAIL (G16 / no clock predicate) | pack-09 DISPOSITIONS 3; 09a §2 | Forced reformalization bar this card discharges; not an economic prior | disclosed |
| Geometry lesson (§0.2 / 11a §1) | pack-11 / 11a | Forced H = 900 + half-hour windows so F2 is non-vacuous — design constraint, not an outcome statistic | disclosed |

---

## 14. TRIAL LEDGER (drafted-not-evaluated appendix; N = 12 unchanged)

Primary = slate-D ledger row "H12 primary: ofi_integrated(900 s)
quintile × half-hour `ALGO_CLOCK` continuation, H=900, hl=450,
passive, pooled {APP,RMBS}" — this spec is its formalization, not a
new trial. FQ-6B-R: any data contact increments N; drafting does not.

| variant drafted | status |
|---|---|
| H12 primary (this spec) | drafted-not-evaluated (N-impact: 0) — formalization only |
| H12 alt: decile tail instead of quintile (power-infeasible on current arithmetic — recorded only) | drafted-not-evaluated (N-impact: 0); not authorized |
| H12 alt: session-relative OFI percentile split (vs trailing-900 s wired percentile) | drafted-not-evaluated (N-impact: 0) |
| H12 alt: `seconds_to_window_close` band filter (window-edge entry discipline beyond membership) | drafted-not-evaluated (N-impact: 0) |
| H12 alt: `hard_exit_age_seconds = 1350` (3 × hl) | drafted-not-evaluated (N-impact: 0) |
| H13 primary (CONTINGENT — not authorized for census yet) | drafted-not-evaluated (N-impact: 0) |
| Shared: `WindowKind.ALGO_CLOCK` taxonomy + calendar artifact set | infrastructure; N-impact 0 until paired with an outcome contact |
| session-discipline constants varied | drafted-not-evaluated (N-impact: 0 each) |
| re-thresholded conditioning (any change to 0.80/0.20 split or `w_hh` used as a tuned occupancy) | drafted-not-evaluated (N-impact: 0); evaluation is +1 N |

Carried unchanged (not duplicated): pack-04 / pack-06 / pack-09
drafted rows and closed trials (H1–H11, S-1). None authorized for
evaluation by this spec. H9 remains dead pending extraordinary
justification (pack-11 DISPOSITIONS 3). KYLE_INFO continuation not
authorized (pack-10 DISPOSITION 1).

**N = 12 as of this task** (unchanged; no outcome contact). First
outcome contact on the H12 primary → **N ≥ 13**.

---

## 15. CARD→SPEC DEVIATION TABLE (logged, never silent)

| # | card (original) | spec (tested form) | where / why |
|---|---|---|---|
| 1 | gate sketch implicit in conditional-distribution prose | two-sided quintile in gate + evaluate (`≥ 0.80` OR `≤ 0.20`); `scheduled_flow_window_active` in on/off; off_condition releases via interior band with `percentile_margin` + clock-lapse | §5.2/§5.3 — hysteresis must be referenced; H11 structural fix |
| 2 | hysteresis not YAML-sketched on card | both margins declared and referenced (`posterior_margin: 0.15`, `percentile_margin: 0.15`) | §5.3 — dead-config loader rule; 0.15 matches quintile release into (0.35, 0.65) |
| 3 | "Percentile view at h = 900" | explicit **NEW factory wiring** for `ofi_integrated_percentile` (not in bootstrap today) | §1.2 / §16 Phase A — naming the gap prevents silent substitution of session-relative or ewma percentiles |
| 4 | ALGO_CLOCK interval "frozen at impl" | frozen here: `[M, M+1s)` half-open, lead = 0, twelve marks listed | §1.5.2 — Amendment C requires calendar artifacts as spec deliverables |
| 5 | F2 prose only | dual-form window-binding + powered arm sizes (147.7 / 160.1) + H9 firewall | §12 — Amendment D |
| 6 | Implementation: "Taxonomy + calendars + YAML + percentile factory" | **phased** Ordering B: Phase A = taxonomy + calendars + percentile factory + census + harness IC row; Phase B = full card gated on step-2 PASS | §16 / Next action — Amendment G; backlog-14 Ordering B carries |
| 7 | κ central ≈ 0.146 | freeze **0.146** with reviewer product 0.1458 logged; minimum-rule convention stated (no H12 discrepancy) | §4.1 — Amendment B |

No other substantive deviation exists; hypothesis text, family,
half-life, horizon, archetype, counterparty, κ decomposition and
freeze, park arithmetic, symbol set, F1–F5, power structure,
consequence-precedence sketch, and contingent H13 triggers are
carried as confirmed.

---

## 16. DELIVERABLES MAP (phased; nothing implemented here)

### Phase A (pre-Task-8; Ordering B carries — Amendment G)

1. **`WindowKind.ALGO_CLOCK` taxonomy + loader/tests** — versioned
   migration; `EventCalendar.hash` baseline refresh; unit tests for
   unknown-kind rejection and ALGO_CLOCK round-trip.
2. **Per-session calendar YAMLs** — every date in operative
   {APP, RMBS} 20-session sets; twelve half-hour windows per §1.5.2;
   exchange-schedule authoring only; content-addressed; merge with
   existing OPENING_AUCTION / MOC rows.
3. **`ofi_integrated_percentile` factory wiring** at h = 900 in
   bootstrap (parity assessment — any moved locked baseline requires
   architectural review, never a value edit).
4. **Census instrument** — deterministic offline pass
   (PYTHONHASHSEED=0) over frozen {APP, RMBS} × 20 sessions:
   calendar-warm fraction, joint conditioning occupancy at frozen
   thresholds, in-window vs off-clock episode counts vs design
   (147.7 / 160.1) and census floor ≥ 100, `calendar_missing_rate`,
   REPORTS estimands. **No forward returns / IC in the census
   instrument itself** unless bundled as the harness row below under
   the same freeze.
5. **Harness IC row** — implementation-independent step-2b statistic
   on the census-pinned predicate (research-workflow Ordering B);
   harness sign-golden required before 2b; pre-register
   census-consistency smoke consequence for Phase B mismatch
   (implementation-correction re-run, N unchanged). F2 both arms
   must be instrumented in the same freeze.

### Phase B (gates on step-2 PASS only)

6. `alphas/sig_halfhour_clock_drift_h900_v1/sig_halfhour_clock_drift_h900_v1.alpha.yaml`
   — schema 1.1 SIGNAL; blocks per §5; horizon 900; trend_mechanism
   SCHEDULED_FLOW hl 450; `l1_signature_sensors: [scheduled_flow_window]`;
   failure_signature §10; falsification_criteria §12.
7. `configs/bt_sig_halfhour_clock_drift_h900_v1.yaml` — pinned 00c
   profile, session knobs, symbol list {APP, RMBS}.
8. Tests: Track-A strength/property tests, gate-DSL compile (both
   margins referenced; clock predicate present), config guard,
   calendar-warm goldens, determinism suite.

---

## 17. STATUS

**Status:** `hypothesis → candidate pending validation`

No outcome statistic exists. Statistical validity and execution
validity remain untested. H13 remains **HELD CONTINGENT** under
pack-11 DISPOSITIONS 2 triggers (not co-primary; not authorized for
census yet). H9 remains dead under the bidirectional firewall
(DISPOSITIONS 3). Program stop-rule (pack-10 DISPOSITION 2 / pack-11
DISPOSITIONS 4): either card's step-2b PASS continues the program; both
exhausted without one → program closes.

---

## NEXT ACTION (Amendment G — Phase A scoping contract)

**Concrete next action:** execute **Phase A** under Ordering B —
(1) land `WindowKind.ALGO_CLOCK` + deterministic per-session half-hour
calendar YAMLs for the operative {APP, RMBS} 20-session dates under
the frozen `[M, M+1s)` convention (§1.5), (2) wire
`ofi_integrated_percentile` at h = 900, (3) build the census
instrument that measures calendar-warm, in-window / off-clock
episode counts against the §1.6 design-central arms (147.7 / 160.1)
and the ≥ 100 census floor, and (4) land the harness IC row
(sign-golden before 2b; both F2 arms in the freeze). **Phase B
(YAML / config / deployable evaluate) gates on step-2 PASS only.**
