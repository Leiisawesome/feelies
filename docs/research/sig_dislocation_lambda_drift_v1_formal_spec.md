<!--
  File:   docs/research/sig_dislocation_lambda_drift_v1_formal_spec.md
  Status: hypothesis → candidate pending validation (Task 7 formal spec,
          2026-07-12). Selected candidate H8 per Lei's adjudication
          (prompt_pack_06 DISPOSITIONS 1 — slate formula overridden on
          the dossier's short-side/power finding). Amendment C
          (contamination resolution, the dossier's one CONCERN and
          condition of confirmation) is RESOLVED in §2: the census-legal
          flag-share read at the H8 entry point shows the conditioning
          region at or BELOW the tape base rate (APP ratio 0.95
          count-basis / 0.47 volume-basis vs the pre-registered 2.0
          materiality bar) — the inherited unfiltered kyle_lambda_60s
          stays PRIMARY; the 03b-filtered NEW variant remains a drafted
          fallback (one ledger row). NO forward return, IC, or outcome
          statistic was computed in this task.
  Owner:  microstructure-alpha (spec) / research-workflow (ledger);
          prompt-pack Task 7, Phase B.

  Provenance (FQ-3 template):
    git_sha: "8c69d49f4c45ff0652440a42ed786026b35471fb"
    worktree_clean: "yes at task start except this task's own two
      untracked one-off artifacts (scripts/research/
      h8_contamination_read.py and docs/research/
      h8_contamination_read_results.json — the Amendment-C read;
      method and results reproduced in §2 and Appendix A)"
    pythonhashseed: "0 for the Amendment-C contamination read (the only
      scripted analysis in this task; no forward returns, no IC —
      census-legal print-condition shares only)"
    normative_inputs (Amendment A):
      prompt_pack_06_hypothesis_slate_b.md (H8 card + DISPOSITIONS 1–4),
      prompt_pack_06a_slate_b_review.md (dossier; H8 verdict table incl.
        the contamination CONCERN resolved here),
      prompt_pack_05_horizon_feasibility_map.md + artifact
        horizon_feasibility_map_2026-07-11.json (σ_H quantiles, κ_req,
        §2 floors, §6 operative pre-filter),
      sig_inventory_fade_v1_validation_protocol.md §11.1 (single-stress
        anchor — floor = 2.25 × (2.0 + fee); NO stacking, ever) +
        CENSUS RESULTS (C.3/C.5/C.6 — density, warm, contamination
        bases; census N-neutrality rule),
      prompt_pack_03b_print_eligibility.md (§3.3 Class table, §4.4
        netting, §6 guards),
      prompt_pack_03c_universe_and_cache.md (frozen grid, L1–L4
        verbatim, §5.1 counts, §7 realized tick buckets),
      prompt_pack_00b_edge_units_convention.md (one-way convention),
      prompt_pack_00e_strength_rider_and_thread.md (Track A rider),
      prompt_pack_00c_eval_canon.md (pinned realism profile),
      sig_inventory_fade_v1_formal_spec.md (H2 spec pattern — riders
        carried per Amendment D; never its values as benchmark),
      src/feelies (sensor sources, bootstrap wiring, gate engine,
        hazard-exit controller, layer validator — read this session;
        citations inline).
-->

# `sig_dislocation_lambda_drift_v1` — formal specification (Task 7)

Candidate H8, confirmed by Lei 2026-07-12 subject to Amendments A–E.
This document is the complete formal specification mapped onto the
platform contracts; **no implementation code ships with it** (the
`evaluate` block in §6 is a normative draft for Task 9). The only data
contact in this task is the Amendment-C census-legal contamination read
(§2) — print-condition shares only; no forward return, IC, or outcome
statistic of any kind was computed.

**Hypothesis (unchanged from the pre-registered card).** When a 300-s
price dislocation is produced by *trading with elevated price impact* —
flow moving price more per unit size than the recent baseline — the
dislocation is information being incorporated (Kyle: the market maker's
pricing rule steepens when informed trading intensity rises) rather
than a liquidity shock (which reverts). Because the informed trader
spreads execution over time to limit impact, incorporation is
incomplete at the boundary, which must leak into L1 as continuation of
the move over the next 300 s — but *only* in the impact-elevated
stratum; the same dislocation with baseline λ is expected to revert
(that contrast IS the falsifier).

Family `KYLE_INFO`; archetype **informed-flow-following via the impact
fingerprint**; structural counterparty: liquidity providers and
mean-reversion traders who fade information-driven moves as if they
were liquidity shocks — their fading losses fund the continuation.
`expected_half_life_seconds = 150` (G16 envelope 60–1800 ✓,
`layer_validator.py:156`); `horizon_seconds = 300`; ratio 2.0 ∈
[0.5, 4.0] ✓. Symbol set **{APP primary, RMBS secondary (park-armed)}**
per the card's own park table (§5).

---

## 1. OBSERVABLE STATE

All sensors are **existing, registered** implementations (reference
config `platform.yaml`; no NEW sensor — the cheapest card on the
slate, YAML-only). As existing DI-09 sensors they ingest every
parseable print/quote; the 03b §3.3 print-eligibility convention binds
only NEW sensors, so no condition filter is applied at runtime
(changing that would touch locked parity baselines). The inheritance of
the unfiltered trade-fed `kyle_lambda_60s` **inside the entry rule** was
the dossier's one CONCERN — resolved quantitatively in §2. The
pre-registered 03b Class-A-filtered NEW `kyle_lambda` variant remains
**drafted-not-evaluated** as the fallback (§14).

### 1.1 Sensor table (exact ids, params, warm-up, halt behavior)

| sensor_id | ver | feed | params (reference config) | warm rule | gap/halt behavior | units |
|---|---|---|---|---|---|---|
| `kyle_lambda_60s` | 2.0.0 | Trade (+NBBOQuote for mid) | `min_samples=30`, `alignment="causal"` (`platform.yaml:357-386`) — causal lag-one pairing (Δp over [t−1,t) vs Δq_{t−1}), the correct-sign Kyle estimator (P1-5 IC validation table in platform.yaml) | warm ⇔ ≥ 30 (Δp, Δq) samples in trailing 60 s event-time window | event-time deque evicts on next post-gap trade: a > 60 s halt empties the window and the sensor un-warms on the first post-halt print; horizon staleness marks the feature stale at boundaries during the silent gap | $/share per share of signed flow (OLS slope); consumed only through the percentile reducer (dimensionless) |
| `micro_price` | 1.1.0 | NBBOQuote | `warm_after=1`, `warm_window_seconds=60` (`platform.yaml:327-336`) | warm ⇔ ≥ 1 valid quote in trailing 60 s | warm-window deque empties after a > 60 s quote gap (S3) — reverts to cold; invalid NBBO (zero sizes) yields no update | $ — depth-weighted price `(bid·ask_sz + ask·bid_sz)/(bid_sz+ask_sz)` (Stoikov); displayed-size weighting is the L5 exposure (§9) |
| `realized_vol_30s` | 1.3.0 | NBBOQuote | `window_seconds=30`, `warm_after=16` (`platform.yaml:420-429`) | warm ⇔ ≥ 16 log-returns in trailing 30 s | window-bounded; un-warms after gaps (S3) | std of per-quote mid log-returns (unannualised); **gate use only**, never edge scaling |

`ofi_ewma` appears in the card's observable-state list as a
flow-agreement **diagnostic** and is deliberately **not** in
`depends_on_sensors` and not on any runtime path — it is an offline
Task-8 report only (adding it as an entry arm is the power-reducing
drafted variant, §14). Deviation table row 5.

**No `spread_z_30d` anywhere** (census C.5 warm 0.03–0.16 on thin
names; slate convention §0.1). The regime work is done by the λ arm
plus the `P(vol_breakout)` posterior and the vol z backstop.

**Warm reality (census C.5 + the §2 read's incidental verification).**
Card block 3 pre-registered census-stage verification for the two
unmeasured sensors; the Amendment-C read (census-legal, §2) supplies
it at the h=300 boundary level: all-four-features warm-and-fresh
fraction over in-window boundaries = **APP 760/760 = 1.000; RMBS
729/760 = 0.959** (worst cell 2025-12-04: 58/76 = 0.763). All 20 cells
clear the pre-registered RMBS coverage rule (drop RMBS if coverage
< 0.5 on > 2 sessions) with wide margin. The λ warm marginality on
RMBS quiet stretches is real (three cells below 0.95, worst 0.763)
but not disqualifying.

### 1.2 Horizon reducers consumed (feature_id keys, h = 300)

| feature_id | producer | status |
|---|---|---|
| `micro_price_drift` | `HorizonWindowedFeature("micro_price", 300, reducer="delta")` — signed change of micro-price across the horizon window, level-invariant (audit P1-9) | wired at all horizons (`bootstrap.py:1337-1342`) ✓ |
| `micro_price` | `SensorPassthroughFeature("micro_price", 300)` — last-of-horizon level, used only as the normalising denominator | wired (`bootstrap.py:1325-1326`) ✓ |
| `kyle_lambda_60s_percentile` | `HorizonWindowedFeature("kyle_lambda_60s", 300, reducer="percentile")` — Hazen percentile of the current λ within the trailing 300 s event-time window of λ readings | wired (`bootstrap.py:1212-1217`) ✓ |
| `realized_vol_30s_zscore` | `RollingZscoreFeature` (count-window z) | wired (`bootstrap.py:1352-1356`) ✓ — gate backstop only |

**NO new wiring is required** — every consumed feature exists at every
horizon via `_build_horizon_features`; no bootstrap change, no parity
exposure. (Contrast with H2, which needed the h=120 passthrough.)

Percentile semantics, stated plainly (deviation table row 4): the
wired `kyle_lambda_60s_percentile` ranks λ against its own trailing
**300-second** window, not the session — the operational conditioning
is "λ elevated relative to its recent baseline." The card's prose said
"session baseline"; the session-relative split is registered as a
drafted variant (§14), not silently substituted.

Dislocation threshold, stated plainly (deviation table rows 1–2): the
card froze the multiple 0.75 on a "session σ₃₀₀-scale." No causal
runtime session-σ₃₀₀ feature exists, and `evaluate()` is stateless, so
the spec implements the threshold as **fixed per-symbol constants**
computed from the pre-registered pack-05 artifact medians
(σ₃₀₀,med: APP 33.8084 bps, RMBS 31.622 bps):

    disloc_min(APP)  = 0.75 × 33.8084 bps = 25.36 bps = 2.53563e-3
    disloc_min(RMBS) = 0.75 × 31.622  bps = 23.72 bps = 2.37165e-3

as fractions of the micro-price level, applied to
`|micro_price_drift| / micro_price`. Causal (the artifact predates all
evidence sessions' use here), deterministic, YAML-only. A
session-relative σ variant is drafted-not-evaluated (§14).

### 1.3 Boundary semantics

`HorizonFeatureSnapshot` carries `values` / `warm` / `stale` keyed by
feature_id. Entry is suppressed unless every id in the alpha's
`required_warm_feature_ids` is warm and not stale; exits are permitted
when stale (conservative). The consume-driven required-warm set
(statically parsed `snapshot.values` reads ∪ gate identifiers,
`bootstrap.py:1477-1527`) is exactly:

    { micro_price_drift, micro_price, kyle_lambda_60s_percentile,
      realized_vol_30s_zscore }

`depends_on_sensors: [kyle_lambda_60s, micro_price, realized_vol_30s]`
— both G16 rule-5 KYLE_INFO fingerprints (`kyle_lambda_60s`,
`micro_price`; `layer_validator.py:165`) are present and are genuinely
load-bearing (λ is the conditioning discriminator, not decoration).

### 1.4 Session-time discipline (explicit constants, H2-rider carry)

Fixed constants in `configs/bt_sig_dislocation_lambda_drift_v1.yaml`
(not free-range parameters; varying either is +1 N):

- `no_entry_first_seconds: 300` — no entries in the first 5 minutes
  (opening cross + MC Official Open re-print arrival, id 16/17;
  pre-registered constant, arrival times deliberately not measured).
- `session_flatten_enabled: true`,
  `session_flatten_seconds_before_close: 600` — entries blocked and
  positions flattened from 15:50 ET; every H = 300 s hold completes
  inside RTH and no window overlaps the closing cross or the 15:50
  imbalance dissemination.

All boundary-count arithmetic in this spec uses the resulting
09:35–15:50 in-window count (76 h=300 boundaries/session, 760/symbol
on the 10-session grid). The Task-9 config guard records the
instantiated snapshot checksum including these knobs (00c pinning).

### 1.5 Evidence-time contamination flag (offline, deterministic)

The runtime sensors cannot see condition codes (parity). The evidence
pipeline flags every horizon boundary whose trailing 60 s λ-window
contains any Class-B print (03b §3.3 exclusion set) or any
`correction ∈ {10,11,12}` record, reports the flagged fraction, and
reports eligible-episode counts and (at Task 8+) conditional statistics
**both ways** (contamination-excluded primary and including-flagged).
Offline cache read, PYTHONHASHSEED=0, no runtime behavior change. §2
already exercises exactly this machinery at the entry point.

---

## 2. CONTAMINATION RESOLUTION (Amendment C — condition of confirmation)

**The concern (dossier, verbatim gist).** H8 is the only card with an
inherited unfiltered trade-fed sensor inside the entry rule
(`kyle_lambda_60s_percentile ≥ 0.5`). The card's justification — DI-09
flags concentrate at trade-flow extremes and a median split dilutes
single-print OLS distortion — was judged real but unresolved, because
H8's quote-side extreme (0.75 σ dislocations) is *driven by* heavy
one-sided trading, exactly the windows where census flags cluster.

**Method (census-legal; no forward returns, no IC).** One-off
deterministic replay (PYTHONHASHSEED=0) of the 20 frozen grid cells
{APP, RMBS} × 10 evidence dates through the production
`SensorRegistry → HorizonScheduler → HorizonAggregator` stack at
h = 300 with reference `platform.yaml` sensor params and the
`hmm_3state_fractional` regime engine (per-session causal-prefix
calibration, first 100 000 RTH quotes). At every in-window (§1.4)
boundary with all four entry features warm and fresh, the full H8
entry point was evaluated: `kyle_lambda_60s_percentile ≥ 0.5`,
`|micro_price_drift|/micro_price ≥ disloc_min(symbol)` (§1.2),
`P(vol_breakout) < 0.7`, `realized_vol_30s_zscore ≤ 3.0`. For the
conditioning boundaries, the print population of the trailing 60 s
window — **the population the unfiltered λ regression actually runs
on** — was compared against the full RTH session tape. (h = 300 ≫
60 s, so windows never overlap; no double counting.)

**Pre-registered materiality criterion (frozen before the run):**
materially elevated ⇔ pooled region flagged-print share ≥ **2.0 ×**
the pooled tape base rate on either the print-count or the volume
basis, for APP (primary). Flag set: 03b §3.3 Class-B conditions ∪
correction records {10, 11, 12}. The criterion is an *intensity* (share
of flagged prints), not a binary any-flag indicator — the binary
saturates trivially on active tape (any 60-s window almost always
contains ≥ 1 flagged print) and measures window length, not λ-input
contamination.

**Results (pooled over 10 sessions; per-cell table in Appendix A):**

| symbol | conditioning boundaries | region prints | region flagged share (count) | tape base (count) | **ratio** | region flagged share (volume) | tape base (volume) | **ratio** |
|---|---|---|---|---|---|---|---|---|
| APP  | 81 | 23 986 | 3.24 % | 3.42 % | **0.948** | 2.88 % | 6.17 % | **0.467** |
| RMBS | 77 | 6 379  | 2.90 % | 3.35 % | **0.867** | 2.26 % | 6.02 % | **0.375** |

Binary any-flag boundary rates, disclosed for completeness: APP 98.8 %
of conditioning boundaries vs 96.7 % of all in-window boundaries; RMBS
79.2 % vs 66.4 % — the saturation the intensity criterion was chosen
to avoid; on intensity the region is at or *below* base rate on both
bases for both symbols.

**Verdict: NOT materially elevated** (all four ratios < 1.0, far below
the 2.0 bar). The quantified justification the card owed is now on
record: H8's entry windows, despite being trading-heavy, do **not**
resemble the census's flagged extremes — the flagged-print intensity
feeding the λ OLS at the entry point is indistinguishable from (count)
or less than half of (volume) the ambient tape. The dossier's residual
worry is answered empirically, not argued. Consequences:

1. The inherited unfiltered `kyle_lambda_60s` (2.0.0 causal) **stays
   primary**.
2. The 03b Class-A-filtered NEW `kyle_lambda` variant remains the
   pre-registered fallback — **one ledger row, drafted-not-evaluated**
   (§14); it is promoted to primary only if Task-8 census-stage
   both-ways reporting (§1.5) overturns this read on the full
   conditioning machinery.
3. §1.5 evidence-time flags are still computed and reported both ways
   at Task 8 — this read resolves the *design* question, it does not
   retire the ongoing hygiene.

**Incidental observation, disclosed for honesty (no adjudication
here).** The read incidentally counted conditioning boundaries: APP 81,
RMBS 77 over 10 sessions — below the card's block-2 projection
(≈ 147 / ≈ 111), i.e. the realized joint conditioning fraction at
these frozen thresholds is ≈ 0.10–0.11 vs the assumed 0.226. This is a
density signal only (no returns were touched); the **Task-8 park-rule
census is the pre-registered instrument** that adjudicates power
(§5.3), and no threshold may be re-tuned in response to this
observation (that would be data-contact tuning; any re-thresholded
variant is a NEW drafted row, +1 N if evaluated). Per the census
N-neutrality rule (8-F CENSUS RESULTS C.6), N is unchanged by this
read.

---

## 3. LATENT-STATE INFERENCE

**Framing.** The unobserved quantity is the *cause of the observed
dislocation* — specifically the decomposition of the 300-s move `D`
into permanent (information) and temporary (liquidity/noise)
components. In Kyle terms: informed order flow moves price through the
MM's pricing rule `Δp = λ·Δq`; when informed intensity rises the MM
steepens λ, so **elevated realized λ is the MM population's own
revealed posterior that flow is informed**. The strategy piggybacks on
that inference: conditional on {large dislocation, elevated λ}, the
posterior mass shifts toward "informed incorporation in progress," and
because the informed trader splits execution across time (dynamic
Kyle), a remainder `r_rem` of the full information is still
unincorporated at the boundary — that remainder is the payoff. In
Glosten–Milgrom terms the faders who supply liquidity against the move
are quoting regret-free prices under a *wrong* posterior (they price
the move as noise); their adverse-selection losses fund the edge.

**Cause mixture for the conditioning event**
`E = {|micro_price_drift|/micro_price ≥ 0.75·σ₃₀₀ᵐᵉᵈ, sign-matched;
kyle_lambda_60s_percentile ≥ 0.5; P(vol_breakout) < 0.7;
realized_vol_30s_zscore ≤ 3.0; features warm}`:

| θ | latent cause | adverse? | failure shape | treated by |
|---|---|---|---|---|
| θ₁ | informed institution mid-incorporation (private information, genuinely elevated λ) | no — the harvested case; the *faders* pay | — | — |
| θ₂ | liquidity-shock dislocation with coincidentally elevated λ (thin book inflates the OLS slope without informed flow) | **yes** | **edge reversal** — the move reverts per the card's own contrast prediction; entries systematically lose ~the temporary component, bounded by the dislocation scale, not tail-shaped | λ dose-response check (I-3) + F2 contrast measure it; hazard exit + gate-off bound the hold; dilution-to-negative accounted in κ's `f_perm < 1` |
| θ₃ | herding / momentum-ignition cascades (incl. adversarial manufacture) — dislocation + elevated λ with no information; entry at the top of the move | **yes** | **negative tail, adversarially timed** — collapse after entry, loss a multiple of target edge; the card's dominant risk | hazard exit (`RegimeHazardSpike`), hard age cap 300 s, gate-off on `P(vol_breakout)` / vol z; distributionally F2's reversion-contrast clause (if *everything* continues, λ does no work and the card is dead by its own terms) |
| θ₄ | public-news dislocation already impounded (λ elevated during the print, zero remainder) | no trader to harvest | **edge dilution** — entries pay costs for nothing | session discipline (§1.4) + structural-boundary screen; under-represented on the event-free grid — carried as an external-validity caveat (§10) |
| θ₅ | mechanical artifacts: L5 micro-price shading by revocable displayed size, L6 tick-rule λ mis-signing at bursts, tick-grid discreteness | no | **edge dilution** | conditioning hygiene: threshold 4–5× the manufacturable half-spread bound (§9 L5); §8 R8 stratification; §2 contamination hygiene |

The decision rule and hazard exit treat the shapes differently by
design: the tail component (θ₃) gets state-dependent exits (hazard
spike, gate-off FLAT, hard age 300 s) because holding through a
cascade collapse is where capital dies; the reversal component (θ₂) is
bounded by the same exits but is primarily a *measurement* problem
(the F2 contrast decides whether λ separates it); dilution components
(θ₄/θ₅) get conditioning hygiene and stratified measurement — no exit
rescues an entry that never had an edge.

**What the posterior cannot resolve at L1 (loss-ledger tie).** Per
episode, informedness is undecidable — λ is an OLS slope over
tick-rule-signed prints, and tick-rule signing degrades exactly at
burst moments (L6); whether elevated λ reflects informed intensity or
a thin book is undecidable per window (L1: depth beyond the BBO is
unobserved). Whether the dislocation's depth-weighted component is
real or displayed-size shading is undecidable per quote (L5). Hidden
liquidity absorbing the remainder is invisible until it prints (L4).
Queue position of our passive entry is unobservable (L2). Every one of
these is resolved only distributionally: the posterior over θ is a
population claim tested by F1–F3, never a per-trade classification.

---

## 4. PROCESS MODEL

**Named model: Kyle (1985) dynamic informed-trader incorporation —
partial-adjustment drift.** The informed agent trades against a
linear pricing rule and spreads execution to limit impact, so the
price path toward the full-information value is a persistent drift
with exponentially decaying remainder — pre-registered half-life
150 s, mean lifetime τ = 150/ln 2 ≈ 216 s, fraction of the remainder
captured by the horizon `f_H = 1 − e^(−300/216) ≈ 0.75` (the κ factor
in §5). The observable pair is the model made visible: the dislocation
is the incorporated part; elevated λ is the steepened pricing rule
that identifies incorporation as the cause.

Against the shipped alternatives:

- **Drift-diffusion** (`snr_drift_diffusion` sensor, dormant): the
  closest shipped formalism — DD's drift-vs-noise separation is
  exactly the permanent/temporary decomposition this card needs, and
  a DD-SNR read on conditioned episodes is a natural Task-8
  diagnostic. It is not adopted as the runtime model because the
  sensor is dormant (not in the reference config; activating it is
  new wiring and new parity surface for zero entry-rule content) and
  its SNR output does not carry the λ attribution that makes this
  card falsifiable (F2). Evidence-only.
- **Hawkes self-excitation** (`hawkes_intensity` sensor,
  `scripts/calibrate_hawkes.py`): Hawkes describes *arrival
  clustering* — the loading phase of a burst — with no directional
  content; a Hawkes-framed version of this card would be
  burst-following, i.e. precisely the θ₃ herding confound. It
  survives as a caution: elevated branching ratio without λ elevation
  in conditioned episodes is evidence *for* θ₃ and against θ₁ — an
  offline diagnostic, never the model.
- **HMM / semi-Markov regime persistence** (`services/regime_engine.py`,
  `hmm_3state_fractional`): supplies the *exclusion stratum*
  (`P(vol_breakout)`), not the incorporation dynamics — its dwell is
  the wrong clock for a 150 s drift. Caveat carried verbatim from
  `platform.yaml`: with `transition_time_scaling` OFF (the default,
  protecting locked Level-5/6 baselines) the transition matrix applies
  once per inbound quote, so regime dwell is measured in *ticks* and
  drifts ~10× with intraday quote intensity. The gate is a
  conservative filter whose per-stratum discriminability Task 8 must
  report (gate dwell in seconds, per symbol) — never a calibrated
  dwell model.
- **OU inventory reversion** (the H2 model, Ho–Stoll): structurally
  the *null* here — it is what baseline-λ dislocations should obey.
  The F2 contrast is literally a Kyle-vs-OU discrimination: λ ≥ p50
  strata must continue, λ < p50 strata must revert; a card that
  cannot separate them is not a KYLE_INFO hypothesis.

---

## 5. PARK-RULE ARITHMETIC (Amendment B — κ FROZEN at 0.190)

**Units (00b, THE CONVENTION):** one-way, per-fill, bps of fill
notional throughout. Round-trip figures derived, never disclosed.

### 5.1 Frozen κ decomposition (card block 1, carried unchanged)

    edge_ow = κ × σ₃₀₀ ,   κ = c_D × f_perm × r_rem × f_H × f_pass

| factor | central (frozen) | meaning |
|---|---|---|
| `c_D` | 1.3 | dislocation size in σ₃₀₀ units given \|z\| ≥ 0.75 conditioning (E[\|z\| : \|z\| ≥ 0.75] ≈ 1.33 near-Gaussian — fixed by construction) |
| `f_perm` | 0.6 | permanent share of the dislocation in the λ-elevated stratum |
| `r_rem` | 0.5 | unincorporated remainder at the boundary (uniform detection along the path) |
| `f_H` | 0.75 | remainder captured by H = 300 at hl = 150 (1 − e^(−300/216)) |
| `f_pass` | 0.65 | passive realization haircut |

    κ = 1.3 × 0.6 × 0.5 × 0.75 × 0.65 = 0.190 — FROZEN

**One-way ratchet:** no upward re-estimation of κ or any factor after
any data contact (including §2); revisable down on evidence only. Once
the Task-8 census runs, the **measured conditional edge supersedes the
derivation entirely** — κ-arithmetic exists to fix the pre-data viable
region and the park decision, never quoted as a result afterward.

### 5.2 Single-stress floors and park arithmetic (8-F §11.1 anchor — NO stacking, ever)

Per the §11.1 ruling: the stressed floor applies the Inv-12 1.5×
stress **once** to the one-way passive cost stack —
`floor = 1.5 × 1.5 × (2.0 + fee) = 2.25 × (2.0 + fee)` — and is never
combined with a simultaneously stressed adverse-selection vertex or
any other stressed axis (the H2-ruling §15(ii) stressed-AS floor
construction is explicitly NOT carried; the §12 sensitivity grid
tests the AS axis separately, as robustness, not as a floor). Fees at
the 80-share reference fill against pack-05 median RTH bids
(APP $544.075, RMBS $102.06).

| symbol | fee (bps) | C_ow passive (bps) | single-stress floor (bps) | κ_req,med | κ_frozen·σ₃₀₀,med (bps) | verdict |
|---|---|---|---|---|---|---|
| APP  | 0.0804 | 2.0804 | **4.6809** | 0.139 | 0.190 × 33.8084 = **6.42** | OPEN at median — 37 % headroom (1.37×), best on slate |
| RMBS | 0.4287 | 2.4287 | **5.4645** | 0.173 | 0.190 × 31.622 = **6.00** | OPEN at median, marginally (κ margin 10 %) — **SECONDARY, park rule armed**; map artifact authoritative at rounding boundaries |
| CROX | — | — | 5.66 | 0.228 | 4.71 | CLOSED — excluded |
| rest | — | — | — | ≥ 0.240 | — | CLOSED |

**Short-side rider disclosure (card carry):** SELL legs add 0.5 bps
regulatory + TAF. Rider-inclusive short floors: APP 5.82 ⇒ κ_req
0.172 ≤ 0.190 — **APP short clears rider-inclusive at the median
(unique on the slate)**; RMBS short 6.60 ⇒ κ_req 0.209 > 0.190 —
closed at median. Pre-stated consequence: RMBS restates **long-only**
at census if the measured short edge fails the rider-inclusive floor,
and its power is then re-checked (projected ≈ 55 < 100 ⇒ RMBS drops;
APP stands).

### 5.3 Power floor (carried) and park conditions

**≥ 100 boundary-eligible episodes per deployable symbol** in the
viable region (research-protocol minimum per-stratum sample),
contamination-excluded primary count. Park conditions, pre-registered
for the Task-8 census: (i) edge-region emptiness — measured
conditional edge below the per-symbol single-stress floor on every
grid symbol; (ii) power — no symbol clears ≥ 100. Either parks the
card before any IC exists. The §2 incidental density observation
(81 / 77 at the frozen thresholds) makes (ii) a live possibility —
recorded, not adjudicated; the census decides. Viable-session
arithmetic: σ₃₀₀ session floor = floor/κ = APP 24.6 bps, RMBS
28.8 bps.

---

## 6. DECISION RULE (platform terms)

### 6.1 Free-range parameters (≤ 3 — template discipline)

| param | type | default | range | meaning |
|---|---|---|---|---|
| `lambda_percentile_min` | float | 0.5 | 0.5 – 0.7 | p₀: minimum `kyle_lambda_60s_percentile` at the boundary (the median split; the param can only tighten — the gate's fixed 0.5 arms evaluation) |
| `edge_scale_bps` | float | 10.0 | 6.0 – 16.0 | linear edge attribution per unit of combined normalised exceedance; **provisional pending Task-8 calibration** — the G12 disclosure uses the measured value |
| `edge_cap_bps` | float | 12.0 | 8.0 – 20.0 | hard cap on emitted `edge_estimate_bps` |

Fixed constants (not free-range; varying any is +1 N): the dislocation
multiple 0.75 (frozen at the card); the per-symbol
`disloc_min` fractions and single-stress floors (§1.2, §5.2), embedded
as literal dicts in the pure logic; the session knobs (§1.4); the gate
thresholds (§6.3).

### 6.2 `evaluate(snapshot, regime, params)` — pure logic (normative draft; Task 9 implements)

G5 purity: no imports, no I/O, no state; deterministic in its inputs.
Reads exactly three literal snapshot keys (consume-driven
required-warm derivation, §1.3, plus the gate ids).

```python
signal: |
  def evaluate(snapshot, regime, params):
      drift = snapshot.values.get("micro_price_drift")
      level = snapshot.values.get("micro_price")
      pctl = snapshot.values.get("kyle_lambda_60s_percentile")
      if drift is None or level is None or pctl is None or level <= 0.0:
          return None

      p0 = params["lambda_percentile_min"]
      if pctl < p0:
          return None

      # Frozen per-symbol constants (spec sections 1.2 / 5.2):
      # 0.75 x pack-05 median sigma_300 as a fraction of price, and the
      # single-stress acceptance floor in bps. Literal constants keep
      # evaluate() pure; symbols outside the deployable set emit nothing.
      disloc_min = {"APP": 2.53563e-3, "RMBS": 2.37165e-3}.get(snapshot.symbol)
      floor_bps = {"APP": 4.6809, "RMBS": 5.4645}.get(snapshot.symbol)
      if disloc_min is None:
          return None

      mag = drift if drift >= 0.0 else -drift   # no abs(); stays pure
      disloc = mag / level
      if disloc < disloc_min:
          return None

      # Combined normalised exceedance in [0, 1]: equal-weight mean of
      # (a) dislocation exceedance, saturating at 2x threshold, and
      # (b) lambda-percentile exceedance above p0.
      d_x = (disloc - disloc_min) / disloc_min
      d_x = d_x if d_x < 1.0 else 1.0
      l_x = (pctl - p0) / (1.0 - p0)
      excess = 0.5 * (d_x + l_x)

      # Posterior expected unincorporated remainder, linear proxy of
      # the section-5 derivation; Task 8 calibrates the scale.
      edge_bps = min(params["edge_scale_bps"] * excess, params["edge_cap_bps"])

      # Entry only when posterior EV clears the per-symbol single-stress
      # cost anchor (2.25 x (2.0 + fee), spec section 5.2) -- never a
      # bare threshold. B4 re-checks against the modeled round trip.
      if edge_bps < floor_bps:
          return None

      # Continuation: trade WITH the dislocation (sign-matched).
      direction = LONG if drift > 0.0 else SHORT

      # Strength rider (00e Track A): bounded by construction; explicit
      # clamps as belt-and-suspenders.
      strength = min(max(0.0, excess), 1.0)

      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="sig_dislocation_lambda_drift_v1",
          direction=direction,
          strength=strength,
          edge_estimate_bps=edge_bps,
      )
```

Strength construction (00e Track A rider, adopted verbatim):
`strength = min(max(0.0, 0.5·(d_x + l_x)), 1.0)` — each component is
in [0, 1] by construction at any reachable entry (d_x clamped at 1,
l_x = (pctl − p₀)/(1 − p₀) with pctl ∈ [p₀, 1]), so the mean is
bounded; clamps explicit anyway. Task 9 gains the rider's two tests:
(i) unit test asserting `strength ∈ [0, 1]` across the full declared
parameter ranges; (ii) a Hypothesis property test driving snapshot
values adversarially (NaN, ±inf, extremes, missing keys) asserting
`None` or in-range strength and non-negative finite
`edge_estimate_bps`.

Deliberately **not** in the runtime rule: any runtime σ estimate
(`realized_vol_30s` is a per-quote-return std, quote-rate-dependent —
dimensionally dishonest as a σ₃₀₀ scale), and the OFI flow-agreement
arm (power, §14). Short-side caveat (00c profile): SSR modeling and
HTB fees are inert on the pinned profile — SHORT-side evidence is
optimistic on those axes; carried into evidence interpretation
together with the §5.2 RMBS long-only restatement rule.

### 6.3 Regime gate (AST DSL; hysteresis referenced, not dead config)

```yaml
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(vol_breakout) < 0.7
    and abs(micro_price_drift) >= 0.00237165 * micro_price
    and kyle_lambda_60s_percentile >= 0.5
    and realized_vol_30s_zscore <= 3.0
  off_condition: |
    P(vol_breakout) > 0.7 + posterior_margin
    or realized_vol_30s_zscore > 3.0
    or kyle_lambda_60s_percentile < 0.5 - percentile_margin
  hysteresis:
    posterior_margin: 0.15        # >= 0.15 (G9); REFERENCED above
    percentile_margin: 0.15       # REFERENCED above
```

Notes: `abs` is on the DSL whitelist (`regime_gate.py:128`) and
`BinOp` arithmetic (Mult/Div) is an allowed node, so the side-symmetric
dislocation arm is written directly. The gate's dislocation constant is
the **weaker** (RMBS) per-symbol threshold — the gate arms evaluation;
`evaluate()` enforces the exact per-symbol constants (a single YAML
gate expression cannot vary by symbol). Both hysteresis margins are
referenced (the strict loader rejects declared-but-unused margins as
dead config): the posterior latch arms below 0.70 and releases above
0.85; the λ latch arms at ≥ 0.50 and releases below 0.35 — a
mechanism-lapse exit (λ baseline-reverted ⇒ incorporation story no
longer active), satisfying ≥ 0.15 hysteresis on both axes. All gate
identifiers resolve from boundary-time snapshot values (all four are
wired at h=300, §1.2); gates fail OFF on missing bindings or
non-discriminative posteriors (fail-safe). The vol-z clause is the
sensor-level backstop for the HMM tick-based-dwell weakness (§4).

### 6.4 Hazard exit block

```yaml
hazard_exit:
  enabled: true
  hazard_score_threshold: 0.85     # controller default (hazard_exit.py:90)
  min_age_seconds: 30              # controller default (hazard_exit.py:91)
  hard_exit_age_seconds: null      # -> derived 2 x expected_half_life_seconds = 300 s
```

`RegimeHazardSpike` is an exit-direction hint only (Inv-11);
`HARD_EXIT_AGE` fires at 300 s (2 × hl 150, the platform HM-1
derivation), bounding θ₃ tail exposure — the card's own capacity
sketch calls the hazard exit + hard age load-bearing against
correlated continuation-trader unwinds. Exits also fire on regime-gate
OFF (conservative FLAT close path, including the λ mechanism-lapse
release) and are never blocked by B4 (`not is_exit_or_stop`). This is
not a pure time stop: the age cap is the backstop behind two
state-dependent exits (hazard spike, gate-off), and entry is EV-gated
(§6.2).

### 6.5 Cost arithmetic disclosure (G12; one-way per 00b)

Pinned to the design edge at the APP median; **final values are the
Task-8 measured conditional edge on the deployable set** (disclosed
edge = deployable-set minimum measured edge, conservative):

```yaml
cost_arithmetic:
  edge_estimate_bps: 6.4     # kappa 0.190 x sigma_300 APP median; Task-8 measured value supersedes
  half_spread_bps: 0.0       # maker: no crossing
  impact_bps: 2.0            # passive adverse selection charge (00c pin), disclosed as impact per the passive convention
  fee_bps: 0.08              # commission floor at 80-sh scale, APP anchor (per-symbol table section 5.2)
  margin_ratio: 3.08         # 6.4 / 2.08; reconciles +/- 0.05 absolute; >= 1.5 (G12)
  # cost_basis: one_way (default; round_trip reserved -- never used)
```

Taker was closed at design universe-wide (κT_req 0.449 at H=300, APP
median best) — no taker variant exists, not even drafted. Runtime: the
B4 gate doubles the one-way edge onto the round-trip basis against the
modeled entry+taker-exit cost; Task 9's config adopts
`signal_min_edge_cost_ratio: 1.5`. Sizing: top-of-book scale (APP p50
80 sh; RMBS 100-sh lots; `platform_min_order_shares = 50` respected);
**Sharpe-max declared** — size beyond displayed-depth scale forfeits
the passive economics.

---

## 7. INVARIANCE CHECKS (≥ 2)

**I-1 (R5, zero-integrated-edge conservation — mandatory).** The
integrated edge must be payable out of the adverse-selection losses of
the fading counterparties in the conditioned episodes — the
best-documented funded pool in microstructure, but it must be
*measured*, not asserted. Design: over the full regime-balanced
evidence grid, compute (a) the funding pool — for each conditioned
episode, the measured continuation move times the contra-side
(fading) volume that traded against the dislocation direction inside
the episode window (the faders' mark-to-horizon loss); (b) the
strategy's integrated pre-cost conditional edge at declared
participation (≤ 80 sh/episode against episode volumes O(10³–10⁴) sh —
participation share O(1–10 %)). **Pass:** (b) ≤ participation share ×
(a) within estimation error. **Fail (misattribution):** integrated
edge exceeding what fader losses can fund — the edge, if real, comes
from something unnamed and the card is wrong even if profitable.
Companion conservation checks: (i) unconditional forward returns over
all matched in-window boundaries must integrate to ≈ 0 over the
regime-balanced sample (no ambient-momentum subsidy — a drifting
sample pays any continuation rule); (ii) the **baseline-λ stratum**
(same dislocation, `kyle_lambda_60s_percentile < 0.5`) must show
reversion or zero — its integrated continuation edge ≈ ≤ 0. If
everything continues regardless of λ, the conditioning does no work
and the card is an unpre-registered momentum hypothesis — dead by its
own terms (F2).

**I-2 (side symmetry).** The mechanism is side-symmetric: conditional
continuation on up-dislocations (LONG) and down-dislocations (SHORT)
must agree within sampling error in the benign stratum. Persistent
asymmetry beyond noise ⇒ contamination (ambient drift leakage,
short-side constraint artifacts, signed L6 bias) — investigate before
any deployment claim. The SHORT side additionally carries the §6.2
SSR/HTB optimism caveat and the §5.2 RMBS long-only restatement rule
(an *economic* asymmetry pre-stated at design — floors, not mechanism;
I-2 tests the pre-cost mechanism symmetry).

**I-3 (λ dose-response).** If λ elevation identifies informed
incorporation, conditional continuation must be monotone in the λ
percentile above the split: report the conditional forward return in
λ-percentile bands {[0.5, 0.65), [0.65, 0.8), [0.8, 1.0]} plus the
below-median contrast band. No gradient (flat across bands) ⇒ the
median split is a coin flip and the mechanism attribution fails even
if the pooled number is positive; an inverted-U concentrated at the
extreme top ⇒ θ₃ ignition signature (λ spikes hardest in cascades) —
red flag feeding the hazard-exit calibration, not an automatic kill.

---

## 8. TICK-CONSTRAINT ARTIFACT ANALYSIS (R8)

**Does the state-variable definition survive a tick-regime shift?
Yes — the definition; only parameters need re-estimation.** The
dislocation observable `|micro_price_drift|/micro_price` is a price
*fraction* — dimensionless, grid-independent in definition; what the
grid quantizes is its resolution (Δp in half-tick units) and, more
subtly, **λ's numerator**: on a coarse grid, Δp is a step function of
flow, so the OLS slope is estimated from quantized responses and its
percentile can reflect grid state rather than pricing-rule steepness.

**Grounding in realized buckets (03c §7, binding recompute):** pooled
median spread-in-ticks — APP 61, RMBS 22 = wide/unconstrained (the
deployable set is structurally grid-free at the conditioning scale:
the APP threshold 25.4 bps ≈ 138 ticks of mid movement at $544/1¢;
RMBS 23.7 bps ≈ 24 ticks); CROX 11 moderate; **OLN 2 (per-session
2–4) = discrete/near-constrained — the designated discreteness case,
evidence-set-only (never deployable)**. On OLN a half-tick mid move ≈
2.1 bps and the 0.75σ threshold is a few ticks — grid-state
persistence can masquerade as continuation there, which is exactly why
it is the test bed.

**Explicit test design (pre-registered; OLN evidence-only):**

1. Report the spread-in-ticks distribution **at signal boundaries**
   (not pooled) per symbol — the λ-elevation conditioning may select
   grid states the pooled medians hide (thin books widen spreads AND
   inflate λ; θ₂'s grid twin).
2. **≥ 4-tick-stratum re-derivation:** re-estimate the conditional
   300 s continuation using only boundaries with prevailing spread
   ≥ 4 ticks (APP/RMBS qualify structurally). Survival criterion: the
   ≥ 4-tick-stratum edge consistent with the full-sample estimate;
   collapse ⇒ pooled effect was grid artifact (θ₅) and the economics
   restate on the surviving stratum.
3. **OLN quantum test (persistence vs grid discreteness):** on OLN,
   compare the conditional 300 s move distribution against the
   ±1-half-tick quantum: continuation mass sitting at exactly the
   quantum with no continuous tail ⇒ grid bounce, not incorporation;
   genuine persistence must show mass beyond one quantum and
   σ-normalised agreement with the wide-bucket estimate. Additionally
   report OLN's λ-percentile vs spread-in-ticks correlation: if λ
   elevation on the constrained grid is just spread-state, the λ arm
   is a grid detector there — quantifying exactly how much of the
   conditioning survives discreteness.
4. **Parameters vs definition:** across buckets, `disloc_min` (in
   ticks) and `edge_scale_bps` may legitimately differ
   (re-estimate); if the *sign* of the conditional continuation
   differs by bucket after the quantum correction, that is
   definition-level failure (kill — §11, tick-constraint axis).
5. **Scheduled boundaries (pre-registered structural splits):** SEC
   Rule 612 half-penny regime (compliance first business day Nov 2027)
   halves the grid and migrates symbols down-bucket — never pool
   across it; MDI round-lot reassignments (semiannual, per symbol) are
   declared boundaries for the size-denominated diagnostics (they also
   change `micro_price`'s displayed-size weighting inputs — flagged
   for L5); the 2026-04-27 vendor admissibility split — the grid is
   entirely pre-2026-04-27 by construction.

---

## 9. L2 LOSS LEDGER (signal-specific instantiation of data contract §7)

| row | bite on this signal | treatment adopted (one sentence) |
|---|---|---|
| L1 depth beyond BBO | "elevated λ = informed intensity" is confounded by unobserved thin depth (θ₂) | Treated as a latent-cause prior resolved distributionally (I-3 dose-response + F2 contrast); sizing capped at top-of-book scale so no beyond-BBO liquidity claim is made; forced exits inherit the platform's capped walk-the-book impact model. |
| L2 queue composition / position | passive entry into a continuation move is conditionally adverse — the limit order fills preferentially when the move stalls or retraces (fill ⇔ continuation weakening) | Adopted as **first-class** (§12): the platform's seeded-Bernoulli fill hazard is the probabilistic model and its conservatism is *tested* via the §12 sensitivity grid and the filled-vs-unfilled markout diagnostic — for a continuation card this is the likeliest F4 exit and is pre-declared as such. |
| L3 venue fragmentation | displayed NBBO ≠ single-venue accessible size; fee economics blended | Accepted as systematic noise under the flat blended maker/taker pins; no per-venue claim anywhere in this spec. |
| L4 hidden/midpoint liquidity | hidden absorption completes incorporation without printing — the remainder vanishes silently (dilution of r_rem) | Treated distributionally: no per-episode claim; `trade_through_rate` available as an offline prevalence diagnostic per stratum; r_rem = 0.5 already prices partial invisibility and is one-way-ratchet revisable down. |
| L5 cancel attribution / displayed-size manufacture | `micro_price` is depth-weighted and displayed size is revocable — a quote-size manipulator can shade micro-price without trading (θ₅; MIXED mirage rank) | Bounded and margined by construction: the manufacturable component is ≤ ~the half-spread (APP ≈ 5.6 bps, RMBS ≈ 10.8 bps) while the conditioning threshold is 25.4 / 23.7 bps — a 4.5× / 2.2× margin (RMBS thinner, flagged); the mid-based non-depth-weighted drift NEW sensor is the drafted variant (§14) if Task-8 diagnostics show micro-vs-mid drift divergence at boundaries. |
| L6 aggressor signing | λ's tick-rule signing degrades in fast one-sided tape — exactly the conditioning moment; mis-signing biases the OLS slope and hence the percentile | Inherited and priced: no per-print claim; Task 8 reports a sign-stability diagnostic (tick-rule vs quote-position-of-print agreement, offline) per λ-percentile band so L6 dilution of the conditioning variable is measured rather than assumed away. |
| L7 latency microstructure | none claimed | 20 ms visibility + 50 ms fill = 70 ms ≈ 0.05 % of the 150 s half-life — no latency edge asserted; zero-latency configs invalid for evidence (00c decision A). |

Contamination (the §2 resolution) closes the eighth candidate row —
Class-B print distortion of the λ input at the entry point — with a
measured at-or-below-base-rate verdict rather than a treatment.

---

## 10. REGIME HONESTY (L1–L4 verbatim; intraday gate vs daily stratum)

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

Binding consequences: (i) the **intraday HMM `P(vol_breakout)` gate
and the daily calm/elevated strata are different objects** — the gate
is a quote-clocked intraday posterior (with the §4 tick-dwell caveat),
the strata are session labels; every Task-8 statistic is reported in
the 2×2 of (gate state × daily stratum). (ii) L3 lands directly on
this card: RMBS is both the most heavily conditioned grid subsample
AND this card's secondary symbol — every RMBS figure carries the L3
flag, and the §5.2 park rule plus the warm-coverage rule (§1.1) are
its pre-registered exits. (iii) Calm-stratum conclusions carry the L1
qualifier verbatim in every downstream artifact. (iv) The θ₄
news-dislocation confound is *under-represented* on the event-free
grid (the grid avoids event days by construction) — carried as an
external-validity caveat on any deployment claim, per the card.

---

## 11. KILL CONDITIONS (per regime axis: parameters vs definition, as the platform triple)

For each axis: what a shift breaks; then the three artifacts the
platform consumes — `falsification_criteria` prose,
`failure_signature` clause (G16 rule 6), and the `regime_gate`
`off_condition` term where run-time gating is the right control.

| axis | shift → breaks | falsification_criteria (prose) | failure_signature clause | runtime gate term |
|---|---|---|---|---|
| **Spread** | transient widening → MM stress, passive economics invalid (**gate** — the spread-observing HMM's `vol_breakout` posterior IS the spread gate here); persistent level/bucket migration → **parameters** (floors, fee table, tick-denominated thresholds); continuation sign reversing across spread-in-ticks strata within the benign stratum → **definition (kill)** — the λ arm was reading grid/stress state, not information (F3) | "sign(conditional 300 s forward return) reverses across spread-in-ticks strata within the benign stratum" | `"sign of conditional forward return reverses across spread-in-ticks strata within the benign stratum"` | `P(vol_breakout) > 0.7 + posterior_margin` |
| **Volatility** | disorderly breakout → cascade risk dominates (**gate**); secular σ-regime change → **parameters** (the frozen 0.75·σ₃₀₀ᵐᵉᵈ constants re-derive from a NEW artifact — a drafted variant, never in-place edits); benign-stratum continuation flipping to reversion → **definition (kill)** — the premise (λ-elevated dislocations continue) is dead (F1) | "sign-matched dislocation boundaries with λ ≥ p50 in the benign stratum show 300 s forward-return sign agreement ≤ 0.50 over any rolling 20-session window" | `"sign-matched \|micro_price_drift\| >= 0.75 sigma boundaries with kyle_lambda_60s_percentile >= 0.5 show 300 s forward-return sign agreement <= 0.50 over any rolling 20-session window"` | `realized_vol_30s_zscore > 3.0` (sensor backstop for the HMM tick-dwell weakness) |
| **Liquidity** | MDI round-lot / depth-scale change → **parameters** (sizing scale, fee table, micro-price weighting inputs — L5 re-check at the declared boundary); RMBS trade-rate decay → **coverage rule** (λ warm < 0.5 on > 2 sessions drops the symbol, §1.1 — not a kill); λ split ceasing to discriminate (baseline-λ and elevated-λ dislocations behave identically) → **definition (kill)** — the impact fingerprint carries no information and the mechanism attribution is refuted (F2, the card-defining contrast) | "conditional forward return at matched dislocation magnitude is indistinguishable (\|Δ\| ≤ 1 SE) between kyle_lambda_60s_percentile ≥ 0.5 and < 0.5 strata" | `"conditional forward return at matched dislocation magnitude indistinguishable between kyle_lambda_60s_percentile >= 0.5 and < 0.5 strata"` | `kyle_lambda_60s_percentile < 0.5 - percentile_margin` (mechanism-lapse release) |
| **Tick-constraint** | scheduled Rule 612 half-penny boundary (Nov 2027) → **hard structural split, pre-registered**; bucket migration of a symbol → **parameters** (tick-denominated threshold re-derivation); failure of the §8 ≥ 4-tick re-derivation or the OLN quantum test pattern appearing on a deployable symbol → **definition (kill on the affected stratum)** — the continuation was grid persistence | "the conditional edge does not survive re-derivation on the spread ≥ 4 ticks stratum, or conditional move mass sits at the ±1 half-tick quantum with no continuous tail" | `"conditional edge on the >=4-tick spread stratum inconsistent in sign with the pooled estimate"` | none — measurement stratification, not gateable |
| **Scheduled-flow / news** | auction windows → **config** (session discipline §1.4); a change in auction/dissemination mechanics → declared structural boundary; edge concentrating *only* in scheduled-event-adjacent or news-print windows → **definition (kill)** — the counterparty would be event flow and the remainder already impounded (θ₄), a different, unregistered hypothesis | "conditional edge concentrates in boundaries adjacent to scheduled events/news prints and vanishes in the session interior" | `"conditional edge in session-interior boundaries indistinguishable from zero while event-adjacent boundaries carry it"` | config: `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600` |

Plus the standing structural boundaries (F5, pre-registered once):
Rule 612; MDI round-lot reassignments; the 2026-04-27 vendor
admissibility split (post-2026-04-27 sessions inadmissible).

---

## 12. FILL-MODEL DEPENDENCY — FIRST-CLASS (H2-rider carry)

This card's execution posture is **passive entry into a continuation
move** — the structurally adverse fill geometry (the resting order
fills when the move retraces or stalls; the L2 row). The crowd takes;
we rest. F4 is therefore the pre-declared likely exit, and the
evidence requirements are binding:

**(a) Passive-fill-quality diagnostics (every H8 evidence run reports):**

- **Fill-mix realism:** distribution of fill outcomes from
  `passive_fill_stats()` — level/drain vs through fills, partial-fill
  slices, `EXPIRED` (timeout-cancel) rate, and time-to-fill vs the
  3-tick delay + hazard model. For a continuation card the trap reads
  *inverted* relative to a fade: a fill mix dominated by
  **retrace/drain fills followed by non-resumption** means entries
  are systematically acquired exactly when the continuation premise
  has already failed — the execution-layer signature of θ₂/θ₃.
- **Conditional adverse selection:** post-fill markouts at 150 s and
  300 s on *filled* signal boundaries vs the same conditional forward
  return on *unfilled* signal boundaries — the filled-minus-unfilled
  gap is the realized L2 selection cost; it must be consistent with
  (or better than) the 2.0 bps charged, else F4 arithmetic re-runs
  with the measured figure.

**(b) Task-8 sensitivity grid (pass = robustness across the full
grid):** 3 × 3 × 3 over the pinned profile —

| knob | pinned | grid |
|---|---|---|
| `passive_fill_hazard_max` | 0.5 | {0.25, 0.5, 0.75} |
| `passive_queue_position_shares` | 200 | {100, 200, 400} |
| `cost_passive_adverse_selection_bps` | 2.0 | {2.0, 3.0, 4.0} |

**Pass:** the F4 clearance verdict (measured net edge ≥ per-symbol
**single-stress** floor, §5.2 — the AS axis here is a robustness
sweep, never a second stress folded into the floor; §11.1, no
stacking) holds at **every** grid vertex on the deployable set. A
verdict that flips across the grid is simulator-dependence and the
candidate is not execution-valid regardless of the pinned-profile
number.

**(c) Task 12 parity is a HARD GATE for any H8 evidence** — no number
produced before the router timing-parity check of Task 12 is
presented as a result; the live-WS cancel/correction dissemination row
and the L7 ms-timestamp asymmetry are Task-12 inputs.

**(d) F4 trap-quadrant clause, retained verbatim:** "F4 (execution
validity): pre-cost continuation exists but ≤ 1.5 × C_ow under the
passive realism model → `trap-quadrant`."

---

## 13. FALSIFICATION CRITERIA (consolidated, for the YAML; card F1–F5 carried)

- **F1 (forward test, honest-N):** continuation-signed conditional
  300 s forward return ≤ 0 at the joint condition, or below the
  honest-N noise ceiling `expected_max_sharpe(n_trials=N, …)` with N
  from the living ledger → dead. Clause: `"sign-matched
  |micro_price_drift| >= 0.75 sigma boundaries with
  kyle_lambda_60s_percentile >= 0.5 show 300 s forward-return sign
  agreement <= 0.50 over any rolling 20-session window"`.
- **F2 (mechanism tie — THE card-defining contrast):** the KYLE story
  requires the λ split to discriminate. Clause: `"conditional forward
  return at matched dislocation magnitude is indistinguishable
  (|Δ| <= 1 SE) between kyle_lambda_60s_percentile >= 0.5 and < 0.5
  strata"` — if impact elevation adds nothing, the mechanism
  attribution is refuted regardless of pooled drift; and if the
  baseline-λ stratum *also* continues, the card is an unregistered
  momentum hypothesis (I-1 companion).
- **F3 (regime/stratum):** sign reversal across spread-in-ticks strata
  → definition kill; benign-stratum flip to reversion → premise dead.
- **F4 (execution validity):** §12(d) verbatim, evaluated per-symbol
  against the §5.2 single-stress floors, across the §12(b) grid, only
  on Task-12-parity-cleared machinery.
- **F5 (structural boundaries):** the three pre-registered hard splits
  (§11 footer); never pool across.

Any DSR computed downstream uses the then-current ledger N
(`build_dsr_evidence(trials_count=N)`).

---

## 14. TRIAL LEDGER (drafted-not-evaluated appendix; N = 10 unchanged)

Primary = slate-B ledger row "H8 primary: dislocation(≥0.75σ) ×
λ(≥p50) continuation, H=300, hl=150, passive, {APP, RMBS}" — this spec
is its formalization, not a new trial. FQ-6B-R binding rule: any data
contact increments N; drafting does not. The §2 read is census-legal
and N-neutral (8-F C.6 rule; no outcome statistic touched).

| variant drafted | status |
|---|---|
| H8 alt (slate carry): OFI-sign-agreement as an entry arm (power-reducing) | drafted-not-evaluated (N-impact: 0) |
| H8 alt (slate carry): mid-based (non-depth-weighted) drift NEW sensor replacing `micro_price_drift` (L5 escape hatch) | drafted-not-evaluated (N-impact: 0) |
| Shared conditional (slate carry): 03b Class-A-filtered NEW `kyle_lambda` variant — remains the FALLBACK after the §2 verdict, not primary | drafted-not-evaluated (N-impact: 0) |
| session-relative λ percentile split (vs the wired trailing-300 s percentile, §1.2) | drafted-not-evaluated (N-impact: 0) |
| session-relative σ₃₀₀ dislocation threshold (vs the frozen per-symbol constants, §1.2) | drafted-not-evaluated (N-impact: 0) |
| `hard_exit_age_seconds = 450` (3 × hl; capture 0.875 vs 0.75) | drafted-not-evaluated (N-impact: 0) |
| session-discipline constants varied (`no_entry_first_seconds`, `session_flatten_seconds_before_close`) | drafted-not-evaluated (N-impact: 0 each) |
| re-thresholded conditioning (any change to 0.75 multiple or p50 split, incl. in response to the §2 density observation) | drafted-not-evaluated (N-impact: 0); evaluation is +1 N |

**N = 10 as of this task** (unchanged; the only data contact was the
census-legal §2 read).

---

## 15. DELIVERABLES MAP (Task 9 builds; nothing implemented here)

1. `alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml`
   — schema 1.1 SIGNAL; blocks per §6; `depends_on_sensors:
   [kyle_lambda_60s, micro_price, realized_vol_30s]`;
   `trend_mechanism: {family: KYLE_INFO,
   expected_half_life_seconds: 150, l1_signature_sensors:
   [kyle_lambda_60s, micro_price], failure_signature: §11 clauses}`;
   `falsification_criteria:` §13; `horizon_seconds: 300`.
2. `configs/bt_sig_dislocation_lambda_drift_v1.yaml` — instantiated
   from the pinned 00c profile (checksum guard), deployment
   `signal_min_edge_cost_ratio: 1.5`, §1.4 session knobs, symbol list
   {APP, RMBS} (Task-8 outcome may shrink it; OLN evidence-only,
   never listed).
3. **No bootstrap wiring** — all four consumed features are already
   factory-wired at every horizon (§1.2); no parity surface is
   touched. (This is the YAML-only claim, verified against
   `_HORIZON_FEATURE_FACTORIES` this session.)
4. Tests: Track-A strength/property tests (§6.2), gate-DSL compile
   test (incl. both hysteresis margins referenced), config guard
   (latency > 0 + checksum), ≥ 80 % coverage on new code, mypy
   strict, ruff/DTZ clean. A task is not done while any gate fails.

---

## 16. CARD→SPEC DEVIATION TABLE (logged, never silent)

| # | card (original) | spec (tested form) | where / why |
|---|---|---|---|
| 1 | gate sketch arm: `micro_price_drift_zscore > 0.75` | `abs(micro_price_drift) >= 0.00237165 * micro_price` (gate, weaker-symbol arming constant) + exact per-symbol constants in `evaluate()` | §1.2/§6.3 — `micro_price_drift_zscore` is not a wired feature id, and a windowed z is not the σ₃₀₀ scale the card's conditional claim froze; the explicit price-fraction form implements the frozen 0.75 multiple exactly and is side-symmetric via whitelisted `abs`. |
| 2 | threshold basis: "0.75 × **session** σ₃₀₀-scale … implemented as a fixed multiple of a causal trailing vol estimate (Task-7 spec detail)" | fixed per-symbol constants 0.75 × pack-05 **median** σ₃₀₀ (APP 25.36 bps, RMBS 23.72 bps) | §1.2 — no causal runtime session-σ₃₀₀ feature exists and `evaluate()` is stateless; pack-05 medians are pre-registered artifact data; session-relative variant drafted (§14). |
| 3 | hysteresis `{posterior_margin: 0.15, percentile_margin: 0.15}` declared; off_condition referenced neither | both margins referenced: `P(vol_breakout) > 0.7 + posterior_margin`, `kyle_lambda_60s_percentile < 0.5 - percentile_margin` | §6.3 — declared-but-unused margins are dead config the strict loader rejects; the λ release doubles as the mechanism-lapse exit. |
| 4 | λ conditioning prose: "session baseline" | wired `kyle_lambda_60s_percentile` = Hazen percentile in the trailing 300 s window ("recent baseline") | §1.2 — the wired reducer is the tested object; session-relative split drafted (§14), not silently substituted. |
| 5 | observable-state list includes `ofi_ewma` (diagnostic, not an entry arm) | `ofi_ewma` NOT in `depends_on_sensors`; offline Task-8 diagnostic only | §1.1 — nothing on the runtime path consumes it; keeping it out of the YAML keeps the required-warm set and dependency surface minimal; the entry-arm version is the drafted power-reducing variant (§14). |
| 6 | off_condition: `P(vol_breakout) > 0.7 or realized_vol_30s_zscore > 3.0` | adds the λ mechanism-lapse release (row 3) | §6.3/§6.4 — a continuation position whose λ conditioning has baseline-reverted has lost its stated mechanism; gate-off routes to the conservative FLAT path. |
| 7 | contamination posture: justification argued (median split dilutes; flags concentrate at flow extremes), residual "bounded and disclosed, not resolved" | **measured**: region flagged-print share at the entry point 0.95× (APP count) / 0.47× (APP volume) of tape base rate vs the pre-registered 2.0 bar — resolved, unfiltered λ stays primary | §2 — Amendment C condition of confirmation; the filtered NEW λ variant stays as drafted fallback. |

No other substantive deviation exists; hypothesis text, family,
half-life, horizon, archetype, counterparty, κ decomposition and
freeze, park arithmetic, symbol set, F1–F5, and the failure-mode set
are carried unchanged from the card.

---

## NEXT ACTION (one, concrete — Amendment E contract)

**Task 8, step 1 — park-rule census for H8, pre-registered here
before any IC exists:** offline deterministic scan (PYTHONHASHSEED=0,
direct `DiskEventCache` read, production sensor/feature/regime stack
as in §2) of the frozen grid for {APP, RMBS} (OLN added
evidence-only for §8), reporting per (symbol × session × daily
stratum): boundary-eligible episode counts under the full frozen entry
rule (§1.2/§6.3 constants — no re-tuning), split long/short and
primary (contamination-excluded per §1.5) vs including-flagged; sensor
warm coverage per entry-warm id (§1.1 coverage rule applied to RMBS);
realized session σ₃₀₀ (bps, non-overlapping RTH grid returns); the
(gate state × daily stratum) 2×2 boundary table (§10); and the
spread-in-ticks distribution at eligible boundaries (§8 test 1) —
**no forward returns touched** — then apply the frozen park
arithmetic: κ = 0.190 × realized σ₃₀₀ vs the per-symbol single-stress
floor (§5.2), the rider-inclusive short-side floor check (RMBS
long-only restatement rule), and the ≥ 100-episode power floor per
deployable symbol (§5.3) — fixing the deployable set, or parking the
card, before a single IC number exists.

*Task 7 stops here.*

---

## Appendix A — Amendment-C contamination read, per-cell results

Method in §2; script `scripts/research/h8_contamination_read.py`
(one-off, uncommitted), results JSON
`docs/research/h8_contamination_read_results.json`, run 2026-07-12
under PYTHONHASHSEED=0 at git 8c69d49. Columns: in-window h=300
boundaries (win), all-four-warm boundaries (warm), full-entry-rule
conditioning boundaries (cond), prints in the pooled trailing 60 s
windows of conditioning boundaries (rPrints), flagged-print share in
region (rFlag%) vs session tape base rate (tape%), binary any-flag
rate over conditioning (binC%) vs all in-window (binW%) boundaries.

| sym | date | win | warm | cond | rPrints | rFlag% | tape% | binC% | binW% |
|---|---|---|---|---|---|---|---|---|---|
| APP | 2025-11-25 | 76 | 76 | 11 | 2028 | 3.65 | 3.04 | 100.0 | 96.1 |
| APP | 2025-12-04 | 76 | 76 | 11 | 4136 | 4.84 | 4.13 | 100.0 | 98.7 |
| APP | 2025-12-22 | 76 | 76 | 5 | 1097 | 2.46 | 2.87 | 100.0 | 94.7 |
| APP | 2026-01-05 | 76 | 76 | 7 | 2447 | 5.15 | 4.77 | 100.0 | 100.0 |
| APP | 2026-01-15 | 76 | 76 | 13 | 4667 | 1.48 | 1.66 | 100.0 | 96.1 |
| APP | 2026-01-26 | 76 | 76 | 6 | 1849 | 3.57 | 2.45 | 83.3 | 98.7 |
| APP | 2026-01-27 | 76 | 76 | 6 | 1796 | 4.96 | 5.37 | 100.0 | 97.4 |
| APP | 2026-04-01 | 76 | 76 | 11 | 2783 | 2.19 | 3.14 | 100.0 | 96.1 |
| APP | 2026-04-10 | 76 | 76 | 4 | 1274 | 2.83 | 3.98 | 100.0 | 100.0 |
| APP | 2026-04-22 | 76 | 76 | 7 | 1909 | 1.57 | 2.57 | 100.0 | 89.5 |
| RMBS | 2025-11-25 | 76 | 72 | 6 | 556 | 1.98 | 3.64 | 66.7 | 55.3 |
| RMBS | 2025-12-04 | 76 | 58 | 4 | 263 | 3.04 | 4.93 | 75.0 | 71.1 |
| RMBS | 2025-12-22 | 76 | 70 | 3 | 139 | 2.16 | 1.81 | 66.7 | 34.2 |
| RMBS | 2026-01-05 | 76 | 76 | 7 | 484 | 5.17 | 3.59 | 100.0 | 73.7 |
| RMBS | 2026-01-15 | 76 | 74 | 13 | 1596 | 1.82 | 2.78 | 76.9 | 81.6 |
| RMBS | 2026-01-26 | 76 | 76 | 6 | 535 | 0.93 | 3.16 | 50.0 | 71.1 |
| RMBS | 2026-01-27 | 76 | 76 | 6 | 408 | 1.96 | 2.23 | 100.0 | 63.2 |
| RMBS | 2026-04-01 | 76 | 76 | 15 | 913 | 3.83 | 3.56 | 73.3 | 60.5 |
| RMBS | 2026-04-10 | 76 | 76 | 7 | 723 | 5.39 | 4.31 | 85.7 | 80.3 |
| RMBS | 2026-04-22 | 76 | 75 | 10 | 762 | 2.89 | 3.51 | 90.0 | 73.7 |

Pooled roll-up and the materiality verdict are in §2. Volume-basis
shares (pooled): APP region 2.88 % vs tape 6.17 %; RMBS region 2.26 %
vs tape 6.02 % — the conditioning region is *less* volume-contaminated
than the tape because the biggest flagged prints (auction/summary
lumps) sit outside entry windows by session discipline.
