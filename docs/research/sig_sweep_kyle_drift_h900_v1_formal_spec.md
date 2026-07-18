<!--
  File:   docs/research/sig_sweep_kyle_drift_h900_v1_formal_spec.md
  Status: rejected (H10 rejection close-out, 2026-07-16 — Lei
          adjudication S.8; protocol step 2b FAIL; §9 row "2b IC
          gate"). Spec text below remains the frozen Task-7 design
          record; outcome contact and verdict live in the validation
          protocol STATISTICAL RESULTS + S.8 and in
          sig_sweep_kyle_drift_h900_v1_result.md. Originally: Task 7
          formal spec 2026-07-15; H10 CONFIRMED per DISPOSITIONS 1;
          Amendments A–F applied; no outcome statistic at write.
  Owner:  microstructure-alpha (spec) / research-workflow (ledger);
          prompt-pack Task 7, Phase B (H10).

  Provenance (FQ-3 template):
    git_sha: "decd9170b82e9832800583b97517808a125add31" (HEAD at task
      start; this file is the sole intended output)
    worktree_clean: "research outputs: slate C + review untracked at
      task start; this file is the sole write"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (design only; every number below is quoted from committed
      artifacts or derived by hand arithmetic recorded inline)"
    normative_inputs (Amendment A):
      prompt_pack_08_frontier_refresh.md (OPERATIVE frontier),
      prompt_pack_09_hypothesis_slate_c.md (H10 card VERBATIM +
        DISPOSITIONS + SEQUENCING RULING),
      prompt_pack_09a_slate_c_review.md (DECISION RECORD),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.3
        causality, §4.4 netting, §6 unknown-id guard),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2;
        L1–L5; 140-cell inventory; HOLIDAY-THIN),
      prompt_pack_00b_edge_units_convention.md,
      prompt_pack_00e_strength_rider_and_thread.md (Track A),
      prompt_pack_00c_eval_canon.md (pinned realism profile),
      prompt_pack_12p_router_fill_timing_parity.md (Task 12-P AXIS-1
        VERIFIED — hard gate cited, not re-run),
      sig_dislocation_lambda_drift_v1_result.md (H8 result — mechanics
        pointer / adjacency only; never economic prior),
      sig_dislocation_lambda_drift_v1_formal_spec.md (H8 Task-7 pattern
        — riders carried; never its values as benchmark),
      microstructure-alpha/research-protocol.md Validation Protocol &
        Slate Design Discipline (3-M binding),
      src/feelies (sensor protocol, hazard-exit controller, layer
        validator, regime gate — read this session; citations inline).
-->

# `sig_sweep_kyle_drift_h900_v1` — formal specification (Task 7)

Candidate H10, confirmed by Lei 2026-07-15 subject to Amendments A–F.
This document is the complete formal specification mapped onto the
platform contracts; **no implementation code ships with it** (the
`evaluate` block in §6 is a normative draft for Phase B / Task 9).
**No data contact occurred in this task** — no forward return, IC,
contamination intensity read, or occupancy measurement.

**Hypothesis (unchanged from the pre-registered card).** An
institutional trader with short-half-life information executes with
intermarket sweep orders **because** paying take fees and
through-prices is rational only when immediacy value exceeds patience —
urgency reveals information — **which must leak into L1 as** clusters of
condition-14 prints. Permanent impact (KYLE) continues over
**H = 900 s**; a **passive same-side entry** harvests the remainder at
maker cost.

Conditional-distribution statement: with `SFI(t; 900 s)` = signed
sweep-flow imbalance over eligible condition-14 prints in the trailing
900 s (NEW sensor, Class-A ∩ id-14 filtered):
`E[mid log-return over the next H = 900 s | SFI percentile ≥ 0.90 and
P(vol_breakout) < 0.7] > 0` (symmetric short for ≤ 0.10), magnitude
κ_frozen × σ₉₀₀ with κ central **0.158** ≈ **7.5 bps one-way at the
APP median session** (pack-08 σ₉₀₀ med 47.7).

Family `KYLE_INFO`; archetype **informed-flow-following via certified
ISO sweeps**; structural counterparty: resting LPs lifted across venues
before repricing — their adverse-selection losses fund the continuation.
Conservation: integrated edge ≤ sweep volume × permanent impact; id 14
≈ 17.6 % of tape volume (03b §2). `expected_half_life_seconds = 450`
(G16 envelope 60–1800 ✓); `horizon_seconds = 900`; ratio 2.0 ∈
[0.5, 4.0] ✓. Evidence / deployable set **frozen {APP, RMBS}** —
Tranche-1B cells carry **no role** (DISPOSITIONS 4).

Mirage: **LOW (M = 1.0)** — irrevocable certified prints. F2 still
required (delta-hedger sweeps identically).

---

## 1. OBSERVABLE STATE

### 1.1 Sensor table (exact ids, params, warm-up, halt behavior)

| sensor_id | ver | feed | params | warm rule | gap/halt behavior | units / role |
|---|---|---|---|---|---|---|
| **`sweep_flow_imbalance`** (**NEW**) | **1.0.0** (Phase-A target) | Trade (+ NBBOQuote for mid / tick-rule prior only) | see §1.1.1 | warm ⇔ ≥ `min_eligible_prints` eligible ISO prints in trailing `window_seconds` | event-time deque; gap > `max_gap_seconds` flushes the window (halt → cold); first post-halt eligible print starts re-warm | dimensionless signed imbalance ∈ [−1, 1]; **entry conditioner** |
| `kyle_lambda_60s` | 2.0.0 (existing) | Trade (+NBBOQuote for mid) | `min_samples=30`, `alignment="causal"` (`platform.yaml`) | warm ⇔ ≥ 30 (Δp, Δq) samples in trailing 60 s | event-time deque empties across > 60 s halt | $/share per share; **F2-only** — not on the entry path |
| `realized_vol_30s` | 1.3.0 (existing) | NBBOQuote | `window_seconds=30`, `warm_after=16` | warm ⇔ ≥ 16 log-returns in trailing 30 s | window-bounded; un-warms after gaps | unannualised mid log-return std; **gate backstop only** |

**No `spread_z_30d` anywhere** (census warm 0.03–0.16 on thin names;
slate convention §0.1). **No quote-OFI on the entry path** — that is
H9's conditioner; H10's observable class is certified ISO flow.

**G16 fingerprints:** `l1_signature_sensors: [kyle_lambda_60s,
sweep_flow_imbalance]` — both load-bearing (λ for KYLE attribution /
F2; SFI for the entry conditioner). Rule-5 KYLE primary
`kyle_lambda_60s` is present; SFI is the card-defining NEW observable.

#### 1.1.1 NEW SENSOR SPEC — `sweep_flow_imbalance` (Phase-A deliverable definition)

**Purpose.** Incremental L1 proxy for net signed *intermarket sweep*
aggression over a trailing event-time window. Only exchange-stamped
ISO prints that survive the print-eligibility filter enter state.

**Filter set (explicit constructor / YAML params — load-bearing;
03b as card-stated):**

| parameter | frozen value | source |
|---|---|---|
| `eligible_conditions` | Class-A ∩ id-14 — i.e. a print is eligible iff it carries sale condition **14 (ISO)** AND would pass Class-A (03b §3.3 rule 1: empty/`{37,14}` with 41 overlay; Form-T id 12 is **out** of the intersection by construction because id 12 ≠ 14) | Amendment C / card block 5 |
| `drop_correction_records` | `{10, 11, 12}` | 03b §4.4 |
| retroactive-stamp conditioning | **FORBIDDEN** — do not condition on `correction ∈ {1, 7, 8}` at arrival (03b §4.3 causality trap; Inv-6) | 03b §4.3 |
| unknown-id guard | §6(a) offline session pre-registration: any trade/quote condition or indicator outside the INTERPRETED TABLE → session **UNKNOWN-ID**, inadmissible for evidence until dispositioned; never a silent include on the tick path | 03b §6 |
| `id_12_dw` | **N/A** — id 12 is outside Class-A ∩ id-14; no DW weight exists for this sensor | — |

**Incremental state (registry-owned `state` dict, per symbol):**

```
state = {
  window: deque[(ts_ns, signed_size, size)],   # event-time, eligible only
  last_trade_price: float | None,              # tick-rule prior
  last_side: int,                              # +1 buy / -1 sell; default +1
  last_event_ts_ns: int | None,
}
```

On each `Trade` event (after filter):

1. If `correction ∈ drop_correction_records` → abstain (no state change).
2. If conditions fail Class-A ∩ id-14 → abstain.
3. If `max_gap_seconds` is set and `(ts_ns - last_event_ts_ns) >
   max_gap_ns` → flush `window` (halt semantics).
4. Infer aggressor side via **tick rule** (price > prior → +1; < prior
   → −1; equal → inherit `last_side`; first print default +1) —
   matching `inventory_pressure` / `hawkes_intensity` /
   `vpin_50bucket` (platform convention). **This is an L6 assumption**
   — see §2 and §9 L6 row; do not inherit H9's quote-OFI signing story.
5. Append `(ts_ns, side · size, size)`; evict entries with
   `ts_ns < now - window_ns`.
6. Emit:

       SFI = Σ(signed_size) / (Σ(size) + ε)   ∈ [-1, 1]

   Sign convention (tradeable): **positive ⇒ net aggressive buy
   sweeps** ⇒ continuation LONG; negative ⇒ SHORT.

**Constructor params (versioned in `SensorSpec.params` + provenance):**

| param | default | meaning |
|---|---|---|
| `window_seconds` | 900 | trailing event-time window (= horizon) |
| `min_eligible_prints` | 20 | warm threshold (card: ≥ 20 eligible prints / 900 s) |
| `max_gap_seconds` | 60 | halt flush; post-gap window starts empty |
| `eligible_conditions` / intersection rule | Class-A ∩ id-14 | § above |
| `drop_correction_records` | `{10,11,12}` | § above |
| `epsilon` | 1e-12 | denominator guard |

**Warm semantics.** `SensorReading.warm = True` iff
`len(window) ≥ min_eligible_prints`. Staleness is horizon-layer:
features mark stale at boundaries during silent gaps; entries
suppressed when required features are cold/stale; exits permitted when
stale (Inv-11).

**ISO-warm design prior — ASSERTED (Amendment C).** Selection-density
arithmetic uses an ISO-availability multiplier **0.95** grounded in
legacy 03b APP ISO-rate characterization — **not** a frozen-grid
occupancy read; **not** percentile-by-construction; therefore
**non-exempt** under backlog 15 / 3-M occupancy pre-read.

- Label: **ASSERTED**.
- Census-stage measurement is **mandatory** before any PROCEED that
  cites the density headline (Phase-A census instrument).
- Pre-registered consequence: if measured eligible-print warm drives
  the joint conditioning fraction materially below the design
  projection such that pooled contamination-excluded episodes
  **< 130**, **PARK on power** — no threshold / prior tuning
  (backlog 15; park-on-power, not re-estimation of κ).

**Warm reality table (card block 4, carried):**

| sensor | basis | status |
|---|---|---|
| `sweep_flow_imbalance` | design warm ≥ 20 eligible prints / 900 s; APP ISO ≈ 0.285 × (3.6–6.3 trades/s) ⇒ ample at design; RMBS thinner | **ASSERTED**; census verification; warm < 0.5 on > 2 sessions drops that symbol from D (coverage, not tuning) |
| `kyle_lambda_60s` | proxy `inventory_pressure` ≥ 0.985 on APP; RMBS marginal at 30 trades/60 s | **F2 only**; APP warm ~always; **RMBS warm marginality disclosed** — F2 diagnostic, never entry |
| `realized_vol_30s_zscore` | measured 0.94–0.995 (H2 C.5) | safe for gate |
| `spread_z_30d` | 0.03–0.16 thin names | **NOT USED** |

### 1.2 Horizon reducers consumed (feature_id keys, h = 900)

| feature_id | producer | status / note |
|---|---|---|
| `sweep_flow_imbalance_percentile` | `HorizonWindowedFeature("sweep_flow_imbalance", 900, reducer="percentile")` — Hazen percentile of current SFI within the trailing 900 s window of SFI readings | **NEW wiring required** (Phase A / Phase B bootstrap) — not present today |
| `sweep_flow_imbalance` | `SensorPassthroughFeature` at h = 900 — last-of-horizon level (diagnostic / strength construction) | NEW wiring |
| `kyle_lambda_60s_percentile` | existing factory at all horizons | wired ✓ — **F2 / offline only**; not in `required_warm_feature_ids` for entry |
| `realized_vol_30s_zscore` | `RollingZscoreFeature` | wired ✓ — gate backstop |

Percentile semantics, stated plainly: the wired SFI percentile ranks
SFI against its own trailing **900-second** window of readings ("recent
baseline"), not the session. A session-relative split is a drafted
variant (§14), not silently substituted.

### 1.3 Boundary semantics

`HorizonFeatureSnapshot` carries `values` / `warm` / `stale` keyed by
feature_id. Entry is suppressed unless every id in the alpha's
`required_warm_feature_ids` is warm and not stale; exits are permitted
when stale (conservative). The consume-driven required-warm set
(statically parsed `snapshot.values` reads ∪ gate identifiers) is:

    { sweep_flow_imbalance_percentile, sweep_flow_imbalance,
      realized_vol_30s_zscore }

`depends_on_sensors: [sweep_flow_imbalance, kyle_lambda_60s,
realized_vol_30s]` — `kyle_lambda_60s` is declared for G16 / F2
provenance even though it is not on the runtime entry path (deviation
table row if YAML omits it from consume set: fingerprint still
required on the `trend_mechanism` block).

### 1.4 Session-time discipline (explicit constants)

Fixed constants in `configs/bt_sig_sweep_kyle_drift_h900_v1.yaml`
(not free-range; varying either is +1 N):

- `no_entry_first_seconds: 300` — no entries in the first 5 minutes
  (opening cross + MC Official Open re-print arrival).
- `session_flatten_enabled: true`,
  `session_flatten_seconds_before_close: 600` — entries blocked and
  positions flattened from 15:50 ET; every H = 900 s hold completes
  inside RTH.

All boundary-count arithmetic uses the resulting **09:35–15:50 ET**
in-window count: **25 boundaries / session at H = 900** (pack-08 §1 /
§4; 09a §2 actuals bit-exact). On the 20-session {APP, RMBS} grid with
HOLIDAY-THIN HT = 0.90: raw 500 / symbol; design-central pooled
episodes after HT × decile × gate×warm × ISO-warm — see §5.3.

### 1.5 Evidence-time contamination / eligibility hygiene (offline)

Because the NEW sensor **already filters** Class-A ∩ id-14 + correction
drop at construction, entry episodes are filter-clean by design.
Census still reports:

- residual non-A co-travel diagnostics (prints in the trailing window
  that failed the filter — should be near zero by construction);
- both-ways counts only if a drafted unfiltered variant is ever
  evaluated (+1 N).

Contamination-excluded multiplier = **1.0 at design**. Offline
cache read, PYTHONHASHSEED=0, no runtime behavior change.

---

## 2. LATENT-STATE INFERENCE

**Framing (Kyle / Glosten–Milgrom).** The unobserved quantity is the
*informedness of the sweep cluster* — specifically whether the
condition-14 burst is an informed trader paying for immediacy
(permanent impact still incomplete at the boundary) or a non-informed
urgency print (delta-hedger, momentum-ignition, mechanical sweep). In
Kyle terms: informed flow moves price through the MM pricing rule
`Δp = λ · Δq`; ISO urgency is the revealed preference for immediacy,
which shifts the population posterior toward informed intensity when
coincident with elevated λ (F2). In Glosten–Milgrom terms, resting LPs
lifted across venues quote under a posterior that under-weights the
permanent component; their adverse-selection losses fund the edge.

**Cause mixture for the conditioning event**
`E = {SFI percentile ≥ 0.90 (or ≤ 0.10 short); P(vol_breakout) < 0.7;
realized_vol_30s_zscore ≤ 3.0; required features warm}`:

| θ | latent cause | adverse? | failure shape | treated by |
|---|---|---|---|---|
| θ₁ | informed ISO parent mid-incorporation (private information; genuine urgency) | no — the harvested case; *resting LPs* pay | — | — |
| θ₂ | non-informed urgency (delta-hedger / index arb / forced ISO) with coincidental SFI extreme | **yes** | **edge dilution → mild reversal** — temporary impact reverts; entries pay costs for little permanent remainder; bounded by temporary-impact scale, not tail-shaped | F2 λ-elevation / same-direction print-volume contrast; κ's `f_perm < 1` and `r_rem` price partial non-informedness; hazard + gate-off bound the hold |
| θ₃ | momentum-ignition / adversarial cheap odd-lot ISO clusters (manufacture of the conditioner) | **yes** | **negative tail, adversarially timed** — collapse after entry; loss a multiple of target edge; card's dominant operational risk | min aggregate sweep-volume floor (**drafted** alt, §14); hazard exit + hard age 900 s; gate-off on breakout / vol z |
| θ₄ | public-news / scheduled-flow ISO already impounded (zero remainder) | no trader to harvest | **edge dilution** | session discipline (§1.4); structural-boundary screen; under-represented on event-free grid — external-validity caveat (§10) |
| θ₅ | mechanical artifacts: L6 tick-rule mis-signing at burst moments, tick-grid discreteness, halt-flush residue | no | **edge dilution** (or sign-flip noise if mis-signed) | §9 L6 treatment; §8 R8 stratification; warm/gap flush (§1.1.1) |

The decision rule and hazard exit treat the shapes differently: the
**tail** component (θ₃) gets state-dependent exits (hazard spike,
gate-off FLAT, hard age 900 s) because holding through an ignition
collapse is where capital dies; the **dilution / mild-reversal**
components (θ₂/θ₄/θ₅) are primarily measurement and conditioning
hygiene problems — no exit rescues an entry that never had an edge.

**What the posterior cannot resolve at L1 (loss-ledger tie).** Per
episode, informedness is undecidable — ISO stamps urgency, not
information. Whether elevated SFI reflects informed intensity or a
delta-hedger is undecidable per window without λ co-travel (F2) and
even then only distributionally. **Sweep direction is L6 territory:**
the aggressor side is inferred by tick rule at the exact moments
(bursts) where tick-rule agreement with quote-position-of-print
degrades — a mis-signed burst flips the SFI sign and turns a
continuation entry into a fade of the true flow (**negative-tail if
systematic**, dilution if noisy). Depth beyond BBO is unobserved (L1);
queue position of our passive entry is unobservable (L2); hidden
liquidity absorbing the remainder is invisible until it prints (L4).
Every one of these is resolved only distributionally: the posterior
over θ is a population claim tested by F1–F3, never a per-trade
classification.

---

## 3. PROCESS MODEL

**Named model: Kyle (1985) dynamic informed-trader incorporation —
partial-adjustment drift, conditioned on certified ISO urgency.** The
informed agent trades against a linear pricing rule and, when
immediacy value is high, reveals urgency via ISO; the price path
toward the full-information value remains a persistent drift with
exponentially decaying remainder — pre-registered half-life 450 s,
mean lifetime τ = 450 / ln 2 ≈ 649 s, fraction of the remainder
captured by the horizon `f_H = 1 − e^(−900/649) ≈ 0.75` (the κ factor
in §5). The observable pair is the model made visible: extreme SFI is
the urgency fingerprint; elevated λ (F2) is the steepened pricing rule
that attributes the fingerprint to information rather than mechanical
urgency.

Against the shipped alternatives:

- **Drift-diffusion** (`snr_drift_diffusion` sensor, dormant): closest
  shipped formalism for permanent/temporary decomposition; a DD-SNR
  read on conditioned episodes is a natural Task-8 diagnostic. Not
  adopted as the runtime model — sensor dormant (new wiring / parity
  surface for zero entry-rule content) and SNR alone does not carry
  the ISO-urgency attribution that makes this card falsifiable (F2).
  Evidence-only.
- **Hawkes self-excitation** (`hawkes_intensity`,
  `scripts/calibrate_hawkes.py`): describes *arrival clustering* with
  no directional content — the loading phase of a burst. A
  Hawkes-framed version would be burst-following, i.e. precisely the
  θ₃ ignition confound. Survives as caution: elevated branching ratio
  *without* λ elevation in conditioned episodes is evidence for θ₃ —
  offline diagnostic, never the model.
- **HMM / semi-Markov regime persistence** (`services/regime_engine.py`,
  `hmm_3state_fractional`): supplies the *exclusion stratum*
  (`P(vol_breakout)`), not the incorporation dynamics — its dwell is
  the wrong clock for a 450 s drift. Caveat carried from
  `platform.yaml`: with `transition_time_scaling` OFF (default,
  protecting locked Level-5/6 baselines) the transition matrix
  applies once per inbound quote, so regime dwell is measured in
  *ticks* and drifts ~10× with intraday quote intensity. The gate is
  a conservative filter whose per-stratum discriminability Task 8 must
  report (gate dwell in seconds, per symbol) — never a calibrated
  dwell model.
- **Quote-integrated OFI continuation** (H9's model): structurally a
  *sibling* KYLE claim with a revocable conditioner (MIXED mirage).
  Not adopted — Lei selected the certified-print conditioner
  precisely to separate manufacture from mechanism; using OFI would
  collapse H10 into H9.

---

## 4. PARK-RULE ARITHMETIC (Amendment B — κ FROZEN at 0.158)

**Units (00b, THE CONVENTION):** one-way, per-fill, bps of fill
notional throughout. Round-trip figures derived, never disclosed.

### 4.1 Frozen κ decomposition (card block 1, carried VERBATIM)

    edge_ow = κ × σ₉₀₀ ,   κ = c_D × f_perm × r_rem × f_H × f_pass

| factor | central (frozen) | vs H9 / grounding |
|---|---|---|
| `c_D` | 1.2 | same order — extreme-SFI windows ~1σ contemporaneous |
| `f_perm` | **0.65** | ISO urgency skews permanent (above H9's 0.55) |
| `r_rem` | 0.45 | sweep parents complete faster than limit-heavy parents |
| `f_H` | 0.75 | 1 − e^(−900/τ), τ = 450/ln 2 ≈ 649 |
| `f_pass` | 0.60 | sharper bursts → more adverse pullbacks |

    κ = 1.2 × 0.65 × 0.45 × 0.75 × 0.60 = 0.15795 ≈ **0.158** — FROZEN

**One-way ratchet:** no upward re-estimation of κ or any factor after
any data contact; revisable down on evidence only. Once the Task-8
census / measured conditional edge exists, that measurement
**supersedes the derivation entirely** — κ-arithmetic fixes the
pre-data viable region and the park decision, never quoted as a
result afterward.

### 4.2 Single-stress floors and park arithmetic (VERBATIM from card)

Single-stress anchor (8-F §11.1 / pack-08): `floor = 2.25 × (2.0 +
fee)` — Inv-12 1.5× applied **once**; never stacked with a
simultaneously stressed adverse-selection vertex. Pack-08 floors:
APP **4.68**, RMBS **5.51** bps passive.

| symbol | κ·σ₉₀₀,med | floor | κ_req med | verdict |
|---|---|---|---|---|
| APP | 0.158 × 47.7 ≈ **7.54** | 4.68 | 0.098 | **OPEN** (κ_req 0.098) |
| RMBS | 0.158 × 47.3 ≈ **7.47** | 5.51 | 0.117 | **OPEN** (κ_req 0.117) |
| six others | κ_req med 0.170–0.221 | — | — | CLOSED at median honest κ — **not deployable** |

**Short-side rider restatement chain (VERBATIM from card / H9 carry):**

Short-side rider: APP κ_req 0.122 ≤ 0.158 clears; RMBS 0.140 ≤ 0.158
clears thinly — same restatement chain as H9.

Expanded (H9 arithmetic carried; rider not folded into pack-08
floors): SELL legs add 0.5 bps regulatory + TAF. Rider-inclusive short
floors ≈ APP 5.82 ⇒ κ_req 5.82/47.7 ≈ **0.122** ≤ 0.158 — **APP short
clears at median**. RMBS ≈ 6.60/47.3 ≈ **0.140** ≤ 0.158 — **clears,
thin**. Pre-stated: if census-measured short edge fails
rider-inclusive floor on a symbol, that symbol restates **long-only**
and power is re-checked under the pooled structure (block 3 / §4.3) —
no threshold tuning.

### 4.3 Power structure DECLARED AT DESIGN (VERBATIM — backlog 13)

| role | symbols | basis |
|---|---|---|
| **Deployable** | {APP, RMBS} | both median-open at κ_frozen (§4.2) |
| **Evidence-only** | — | none at design for this card; Tranche-1B cells carry **no role** (DISPOSITIONS 4); OLN remains the designated discreteness case for §8 only |
| **Evidence structure** | **pooled** APP ∪ RMBS | primary RankIC / power counts on the pool; per-symbol diagnostics reported but **do not** govern the step-2 power bar |

**Consequence-precedence sketch (must be copied into the protocol
freeze before any instrument runs — VERBATIM; backlog-13: any
undefined intersection is a freeze-blocking defect):**

1. Primary §9 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK; a single-symbol
   shortfall inside the pool does **not** park the card if the pool
   clears ≥ 130 contamination-excluded — unless that symbol also
   fails deployability park arithmetic, in which case it drops from
   D and the pool is re-checked (A-2.1-class axis split, stated now).
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

### 4.4 Density with margin (design-central; ASSERTED ISO prior)

Percentile decile 0.20 — occupancy pre-read **exempt**. Boundary
basis: 25 × 20 = 500 in-window / symbol; HT = 0.90; gate × warm =
0.90 × 0.95; ISO-warm **0.95 ASSERTED** (§1.1.1).

| set | arithmetic | expectation | vs ≥ 130 |
|---|---|---|---|
| APP alone | 500 × 0.90 × 0.20 × 0.90 × 0.95 × 0.95 | **73.1** | FAIL per-symbol |
| RMBS alone | same | **73.1** | FAIL per-symbol |
| **APP ∪ RMBS pooled** | 1000 × 0.90 × 0.20 × 0.90 × 0.95 × 0.95 | **146.2** | **PASS** |

Conditioning fraction stated: **0.20** × ISO-warm **0.95**. 09a §2
confirms boundary actuals are bit-exact to pack-08 (not
projection-only on the boundary basis); the ISO 0.95 multiplier
remains the unverified non-exempt prior.

Park conditions, pre-registered for census: (i) edge-region emptiness
— measured conditional edge below per-symbol single-stress floor on
every deployable symbol; (ii) power — pooled contamination-excluded
episodes < 130 (including after ISO-warm measurement). Either parks
before any IC outcome is treated as a PROCEED.

---

## 5. DECISION RULE (platform terms)

### 5.1 Free-range parameters (≤ 3 — template discipline)

| param | type | default | range | meaning |
|---|---|---|---|---|
| `sfi_percentile_min` | float | 0.90 | 0.85 – 0.95 | p₀: minimum `sweep_flow_imbalance_percentile` for LONG (symmetric 1−p₀ for SHORT); can only tighten from the gate's arming 0.90 |
| `edge_scale_bps` | float | 10.0 | 6.0 – 16.0 | linear edge attribution per unit normalised SFI exceedance; **provisional pending calibration** — G12 disclosure uses the measured value |
| `edge_cap_bps` | float | 12.0 | 8.0 – 20.0 | hard cap on emitted `edge_estimate_bps` |

Fixed constants (not free-range; varying any is +1 N): the decile
split 0.90 / 0.10 (frozen at the card); per-symbol single-stress
floors (§4.2), embedded as literal dicts; session knobs (§1.4); gate
thresholds (§5.3).

### 5.2 `evaluate(snapshot, regime, params)` — pure logic (normative draft; Phase B implements)

G5 purity: no imports, no I/O, no state; deterministic in its inputs.
Reads literal snapshot keys only (consume-driven required-warm,
§1.3).

```python
signal: |
  def evaluate(snapshot, regime, params):
      sfi = snapshot.values.get("sweep_flow_imbalance")
      pctl = snapshot.values.get("sweep_flow_imbalance_percentile")
      if sfi is None or pctl is None:
          return None
      # Track-A / Inv-11: garbage inputs suppress entry, never create exposure
      if sfi != sfi or pctl != pctl:  # NaN reject (IEEE; no math import)
          return None
      if sfi == sfi and (sfi > 1e308 or sfi < -1e308):
          return None
      if pctl == pctl and (pctl > 1e308 or pctl < -1e308):
          return None

      p0 = params["sfi_percentile_min"]
      # Two-sided decile: long on upper tail, short on lower tail
      if pctl >= p0:
          direction = LONG
          excess = (pctl - p0) / (1.0 - p0)
      elif pctl <= (1.0 - p0):
          direction = SHORT
          excess = ((1.0 - p0) - pctl) / (1.0 - p0)
      else:
          return None

      # Sign agreement: SFI level must agree with percentile tail
      if direction == LONG and sfi <= 0.0:
          return None
      if direction == SHORT and sfi >= 0.0:
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
          strategy_id="sig_sweep_kyle_drift_h900_v1",
          direction=direction,
          strength=strength,
          edge_estimate_bps=edge_bps,
      )
```

Strength construction (00e Track A rider, adopted verbatim):
`strength = min(max(0.0, excess), 1.0)` with `excess ∈ [0, 1]` by
construction at any reachable entry. Phase B / Task 9 gains the
rider's two tests: (i) unit test asserting `strength ∈ [0, 1]` across
the full declared parameter ranges; (ii) Hypothesis property test
driving snapshot values adversarially (NaN, ±inf, extremes, missing
keys) asserting `None` or in-range strength and non-negative finite
`edge_estimate_bps`.

Deliberately **not** in the runtime rule: any runtime σ estimate as
edge scale; `kyle_lambda_60s` (F2 offline); min sweep-volume floor
(drafted ignition defense, §14). Short-side caveat (00c profile): SSR
modeling and HTB fees are inert on the pinned profile — SHORT-side
evidence is optimistic on those axes; carried with the §4.2
restatement chain.

### 5.3 Regime gate (AST DSL; hysteresis referenced, not dead config)

```yaml
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: |
    P(vol_breakout) < 0.7
    and (sweep_flow_imbalance_percentile >= 0.90
         or sweep_flow_imbalance_percentile <= 0.10)
    and realized_vol_30s_zscore <= 3.0
  off_condition: |
    P(vol_breakout) > 0.7 + posterior_margin
    or realized_vol_30s_zscore > 3.0
    or (sweep_flow_imbalance_percentile < 0.90 - percentile_margin
        and sweep_flow_imbalance_percentile > 0.10 + percentile_margin)
  hysteresis:
    posterior_margin: 0.15        # >= 0.15 (G9); REFERENCED above
    percentile_margin: 0.20       # REFERENCED above (card sketch)
```

Notes: both hysteresis margins are **referenced** (strict loader
rejects declared-but-unused margins as dead config). The posterior
latch arms below 0.70 and releases above 0.85; the SFI latch arms at
decile tails and releases when the percentile returns inside
`(0.10 + 0.20, 0.90 − 0.20) = (0.30, 0.70)` — a
mechanism-lapse exit (SFI no longer extreme ⇒ urgency story no longer
active). Gates fail OFF on missing bindings or non-discriminative
posteriors (fail-safe). The vol-z clause is the sensor-level backstop
for the HMM tick-based-dwell weakness (§3).

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
OFF (conservative FLAT close path, including the SFI mechanism-lapse
release) and are never blocked by B4 (`not is_exit_or_stop`). This is
**not** a pure time stop: the age cap is the backstop behind two
state-dependent exits (hazard spike, gate-off), and entry is EV-gated
(§5.2).

### 5.5 Cost arithmetic disclosure (G12; one-way per 00b)

Pinned to the design edge at the APP median; **final values are the
measured conditional edge on the deployable set** (disclosed edge =
deployable-set minimum measured edge, conservative):

```yaml
cost_arithmetic:
  edge_estimate_bps: 7.54    # kappa 0.158 x sigma_900 APP median; measured value supersedes
  half_spread_bps: 0.0       # maker: no crossing
  impact_bps: 2.0            # passive adverse selection charge (00c pin)
  fee_bps: 0.08              # commission floor at reference fill scale, APP anchor
  margin_ratio: 3.63         # 7.54 / 2.08; reconciles +/- 0.05 absolute; >= 1.5 (G12)
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
integrated edge must be payable out of the adverse-selection losses of
the resting LPs lifted by the certified sweeps in the conditioned
episodes — measured, not asserted. Design: over the full
regime-balanced evidence grid, compute (a) the funding pool — for each
conditioned episode, the measured continuation move times the
contra-side (resting / faded) volume that traded against the sweep
direction inside the episode window (the LPs' mark-to-horizon loss);
(b) the strategy's integrated pre-cost conditional edge at declared
participation (≤ top-of-book scale against episode sweep volumes —
participation share must be stated). **Pass:** (b) ≤ participation
share × (a) within estimation error. **Fail (misattribution):**
integrated edge exceeding what LP losses can fund — the edge, if real,
comes from something unnamed and the card is wrong even if profitable.
Companion conservation checks: (i) unconditional forward returns over
all matched in-window boundaries must integrate to ≈ 0 over the
regime-balanced sample (no ambient-momentum subsidy); (ii) the
**non-extreme-SFI stratum** (same gate, SFI percentile ∈ (0.10, 0.90))
must show continuation indistinguishable from zero — if everything
continues regardless of SFI, the conditioning does no work and the
card is an unpre-registered momentum hypothesis — dead by its own
terms (F2 companion).

**I-2 (side symmetry).** The mechanism is side-symmetric: conditional
continuation on buy-sweep extremes (LONG) and sell-sweep extremes
(SHORT) must agree within sampling error in the benign stratum.
Persistent asymmetry beyond noise ⇒ contamination (ambient drift
leakage, short-side constraint artifacts, systematic L6 sign bias) —
investigate before any deployment claim. The SHORT side additionally
carries the §5.2 SSR/HTB optimism caveat and the §4.2 long-only
restatement rule (an *economic* asymmetry pre-stated at design —
floors, not mechanism; I-2 tests the pre-cost mechanism symmetry).

**I-3 (ISO / λ co-travel — mechanism attribution).** If ISO urgency
identifies informed incorporation, conditioned episodes must show
elevated λ and/or same-direction print-volume concentration relative
to the non-extreme baseline (F2). No co-travel ⇒ SFI extremes are
mechanical urgency without information (θ₂/θ₃) — mechanism
attribution fails even if pooled continuation is positive. An
inverted-U concentrated only at the absolute top of SFI with λ
spikes ⇒ θ₃ ignition signature — red flag for hazard-exit
calibration, not an automatic kill.

---

## 7. TICK-CONSTRAINT ARTIFACT ANALYSIS (R8)

**Does the state-variable definition survive a tick-regime shift?
Yes — the definition; only parameters need re-estimation.** SFI is a
**volume-normalised signed imbalance of certified ISO prints** —
dimensionless in definition, not a tick-grid object. What the grid
quantizes is (i) the mid path that *funds* the edge (continuation in
ticks) and (ii) any λ co-travel diagnostic whose numerator is Δp in
ticks. Coarse grids can make continuation mass sit at half-tick
quanta and can inflate λ percentiles via step-function Δp — but they
do not redefine what an ISO print is.

**Grounding in realized buckets (03c §7):** pooled median
spread-in-ticks — APP / RMBS wide/unconstrained (deployable set
structurally grid-free at the H = 900 conditioning scale);
**OLN = discrete/near-constrained — the designated discreteness case,
evidence-only (never deployable; DISPOSITIONS 4: Tranche-1B cells
carry no role in H10 evidence — OLN is used only as the R8 test
bed).**

**Explicit test design (pre-registered; OLN evidence-only):**

1. Report the spread-in-ticks distribution **at signal boundaries**
   (not pooled) per symbol — SFI extremes may select thin-book /
   wide-spread states the pooled medians hide.
2. **≥ 4-tick-stratum re-derivation:** re-estimate the conditional
   900 s continuation using only boundaries with prevailing spread
   ≥ 4 ticks (APP/RMBS qualify structurally). Survival criterion: the
   ≥ 4-tick-stratum edge consistent with the full-sample estimate;
   collapse ⇒ pooled effect was grid artifact (θ₅).
3. **OLN quantum test (persistence vs grid discreteness —
   evidence-only):** on OLN, compare the conditional 900 s move
   distribution against the ±1-half-tick quantum: continuation mass
   sitting at exactly the quantum with no continuous tail ⇒ grid
   bounce, not incorporation; genuine persistence must show mass
   beyond one quantum and σ-normalised agreement with the wide-bucket
   estimate.
4. **Parameters vs definition:** across buckets, `edge_scale_bps` may
   legitimately differ (re-estimate); if the *sign* of the conditional
   continuation differs by bucket after the quantum correction, that
   is definition-level failure (kill — §11, tick-constraint axis).
5. **Scheduled boundaries (pre-registered structural splits):** SEC
   Rule 612 half-penny regime (compliance first business day Nov 2027)
   — never pool across it; MDI round-lot reassignments (semiannual,
   per symbol); the 2026-04-27 vendor admissibility split — the grid
   is entirely pre-2026-04-27 by construction.

---

## 8. L2 LOSS LEDGER (signal-specific; Amendment D — signing honesty)

Baseline ledger instantiated for *this* signal. Sweep signing is
treated explicitly — **not** inherited from H9's quote-OFI framing.

| row | bite on this signal | treatment adopted (one sentence) |
|---|---|---|
| L1 depth beyond BBO | "ISO urgency = informed intensity" is confounded by unobserved thin depth that forces mechanical sweeps (θ₂) | Treated as a latent-cause prior resolved distributionally (I-3 λ co-travel + F2); sizing capped at top-of-book scale so no beyond-BBO liquidity claim is made; forced exits inherit the platform's capped walk-the-book impact model. |
| L2 queue composition / position | passive entry into a continuation move is conditionally adverse — the limit order fills preferentially when the move stalls or retraces (fill ⇔ continuation weakening) | Adopted as **first-class** (§12): the platform's seeded-Bernoulli fill hazard is the probabilistic model and its conservatism is *tested* via the §12 sensitivity grid and the filled-vs-unfilled markout diagnostic — for a continuation card this is the likeliest F4 exit and is pre-declared as such. |
| L3 venue fragmentation | ISO is *defined* cross-venue; displayed NBBO ≠ single-venue accessible size; fee economics blended | Accepted as systematic noise under the flat blended maker/taker pins; the conditioner uses the SIP ISO stamp, not a venue-local size claim — no per-venue feature proposed or dropped. |
| L4 hidden/midpoint liquidity | hidden absorption completes incorporation without printing — the remainder vanishes silently (dilution of `r_rem`) | Treated distributionally: no per-episode claim; `trade_through_rate` available as an offline prevalence diagnostic per stratum; `r_rem = 0.45` already prices partial invisibility and is one-way-ratchet revisable down. |
| L5 cancel attribution / displayed-size manufacture | quote-size manufacture cannot create condition-14 prints — LOW mirage by construction; residual risk is odd-lot ISO ignition (θ₃) | Feature kept: ISO irrevocability removes the L5 entry-path mirage that killed OFI's cleanliness; ignition defense is the drafted min-sweep-volume floor (§14), not an L5 cancel filter. |
| **L6 aggressor signing (SWEEP-SPECIFIC)** | tick-rule signing of ISO prints at burst moments is the **entry-variable's sign**; mis-signing flips SFI and turns continuation into a fade of true flow — failure shape: **noisy dilution** if errors are symmetric, **negative tail** if burst mis-signing is systematically one-sided (fast tape inherits prior side incorrectly) | **Not assumed away and not inherited from H9 OFI:** no per-print informedness claim; aggressor inference is explicitly the tick-rule platform convention (§1.1.1); Task 8 / Phase-A harness reports a sign-stability diagnostic (tick-rule vs quote-position-of-print agreement) **on eligible ISO prints inside conditioned windows** so L6 dilution of SFI is measured; systematic one-sided disagreement in the extreme decile is a red flag feeding F1/F2 adjudication, not a silent haircut. |
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
flag; λ warm marginality (§1.1) and the coverage drop rule are its
pre-registered exits. (iii) Calm-stratum conclusions carry the L1
qualifier verbatim. (iv) L5 binds elevated-A reporting. (v) θ₄
news/ISO confound is *under-represented* on the event-free grid —
external-validity caveat on any deployment claim.

---

## 10. KILL CONDITIONS (per regime axis: parameters vs definition, as the platform triple)

For each axis: what a shift breaks; then the three artifacts the
platform consumes — `falsification_criteria` prose,
`failure_signature` clause (G16 rule 6), and the `regime_gate`
`off_condition` term where run-time gating is the right control.

| axis | shift → breaks | falsification_criteria (prose) | failure_signature clause | runtime gate term |
|---|---|---|---|---|
| **Spread** | transient widening → MM stress, passive economics invalid (**gate** — `vol_breakout` posterior IS the spread/stress gate here); persistent level/bucket migration → **parameters** (floors, fee table); continuation sign reversing across spread-in-ticks strata within the benign stratum → **definition (kill)** — SFI was reading stress state, not information (F3) | "sign(conditional 900 s forward return) reverses across spread-in-ticks strata within the benign stratum" | `"sign of conditional forward return reverses across spread-in-ticks strata within the benign stratum"` | `P(vol_breakout) > 0.7 + posterior_margin` |
| **Volatility** | disorderly breakout → cascade / ignition risk dominates (**gate**); secular σ-regime change → **parameters** (edge_scale / G12 disclosure re-derive from measured edge — never in-place κ edits); benign-stratum continuation flipping to reversion → **definition (kill)** — the premise (extreme-SFI windows continue) is dead (F1) | "extreme-SFI boundaries (percentile ≥ 0.90 or ≤ 0.10) in the benign stratum show 900 s forward-return sign agreement ≤ 0.50 over any rolling 20-session window" | `"extreme sweep_flow_imbalance_percentile boundaries show 900 s forward-return sign agreement <= 0.50 over any rolling 20-session window"` | `realized_vol_30s_zscore > 3.0` (sensor backstop for HMM tick-dwell weakness) |
| **Liquidity** | MDI round-lot / depth-scale change → **parameters** (sizing scale, fee table); RMBS eligible-print / λ warm decay → **coverage rule** (warm < 0.5 on > 2 sessions drops the symbol, §1.1 — not a kill); SFI extremes ceasing to co-travel with λ / same-direction print volume → **definition (kill)** — the ISO fingerprint carries no information (F2) | "conditional forward return at matched SFI extremity is indistinguishable (\|Δ\| ≤ 1 SE) between kyle_lambda_60s_percentile elevated vs baseline strata, or conditioned windows show no same-direction print-volume elevation vs baseline" | `"no lambda elevation / no same-direction print volume in extreme-SFI signal windows"` | SFI mechanism-lapse release: percentile returns inside `(0.10 + percentile_margin, 0.90 - percentile_margin)` |
| **Tick-constraint** | scheduled Rule 612 half-penny boundary (Nov 2027) → **hard structural split, pre-registered**; bucket migration of a symbol → **parameters**; failure of the §7 ≥ 4-tick re-derivation or the OLN quantum test pattern appearing on a deployable symbol → **definition (kill on the affected stratum)** | "the conditional edge does not survive re-derivation on the spread ≥ 4 ticks stratum, or conditional move mass sits at the ±1 half-tick quantum with no continuous tail" | `"conditional edge on the >=4-tick spread stratum inconsistent in sign with the pooled estimate"` | none — measurement stratification, not gateable |
| **Scheduled-flow / news** | auction windows → **config** (session discipline §1.4); a change in auction/dissemination mechanics → declared structural boundary; edge concentrating *only* in scheduled-event-adjacent or news-print windows → **definition (kill)** — the counterparty would be event flow and the remainder already impounded (θ₄) | "conditional edge concentrates in boundaries adjacent to scheduled events/news prints and vanishes in the session interior" | `"conditional edge in session-interior boundaries indistinguishable from zero while event-adjacent boundaries carry it"` | config: `no_entry_first_seconds: 300`, `session_flatten_seconds_before_close: 600` |

Plus the standing structural boundaries (F5, pre-registered once):
Rule 612; MDI round-lot reassignments; the 2026-04-27 vendor
admissibility split (post-2026-04-27 sessions inadmissible).

---

## 11. FILL-MODEL DEPENDENCY — FIRST-CLASS (rider carry)

This card's execution posture is **passive entry into a continuation
move** — the structurally adverse fill geometry (the resting order
fills when the move retraces or stalls; the L2 row). The crowd takes
(ISO); we rest. F4 is therefore the pre-declared likely exit, and the
evidence requirements are binding:

**(a) Passive-fill-quality diagnostics (every H10 evidence run reports):**

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

**(c) Task 12 parity is a HARD GATE for any H10 evidence** — no number
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

## 12. FALSIFICATION CRITERIA (consolidated, for the YAML; card F1–F5 carried)

- **F1 (forward test, honest-N):** continuation-signed conditional
  900 s forward return ≤ 0 at the joint condition, or below the
  honest-N noise ceiling `expected_max_sharpe(n_trials=N, …)` with N
  from the living ledger → dead. Clause: `"extreme
  sweep_flow_imbalance_percentile boundaries show 900 s
  forward-return sign agreement <= 0.50 over any rolling 20-session
  window"`.
- **F2 (mechanism tie — certified ISO ↔ informed):** the KYLE story
  requires λ elevation and/or same-direction print-volume concentration
  in signal windows. Clause: `"no lambda elevation / no same-direction
  print volume in extreme-SFI signal windows"` — if ISO extremes add
  nothing informational, the mechanism attribution is refuted
  regardless of pooled drift; and if the non-extreme stratum *also*
  continues, the card is an unregistered momentum hypothesis (I-1
  companion). Distinguisher from "H8 again at longer horizon."
- **F3 (regime/stratum):** sign reversal across spread-in-ticks strata
  → definition kill; benign-stratum flip to reversion → premise dead.
- **F4 (execution validity):** §11(d) verbatim, evaluated per-symbol
  against the §4.2 single-stress floors, across the §11(b) grid, only
  on Task-12-parity-cleared machinery.
- **F5 (structural boundaries):** the three pre-registered hard splits
  (§10 footer); never pool across.

Any DSR computed downstream uses the then-current ledger N
(`build_dsr_evidence(trials_count=N)`).

---

## 13. TRIAL LEDGER (drafted-not-evaluated appendix; N = 11 unchanged)

Primary = slate-C ledger row "H10 primary: sweep_flow_imbalance(900 s)
decile continuation, H=900, hl=450, passive, pooled {APP,RMBS}" — this
spec is its formalization, not a new trial. FQ-6B-R: any data contact
increments N; drafting does not.

| variant drafted | status |
|---|---|
| H10 primary (this spec) | drafted-not-evaluated (N-impact: 0) — formalization only |
| H10 alt: minimum aggregate sweep-volume floor (ignition defense) | drafted-not-evaluated (N-impact: 0) |
| H9 primary / alt (CONTINGENT SECOND CARD — not authorized for census yet) | drafted-not-evaluated (N-impact: 0) |
| H11 primary (NOT SELECTED — design-gate failure) | drafted-not-evaluated (N-impact: 0) |
| Shared: Class-A-filtered NEW kyle_lambda variant (H9/H10 F2 fallback) | drafted-not-evaluated (N-impact: 0) |
| SEED: baseline-λ dislocation reversion | EVALUATED-AND-EXCLUDED at design (N-impact: 0) |
| session-relative SFI percentile split (vs trailing-900 s wired percentile) | drafted-not-evaluated (N-impact: 0) |
| `hard_exit_age_seconds = 1350` (3 × hl; capture 0.875 vs 0.75) | drafted-not-evaluated (N-impact: 0) |
| session-discipline constants varied | drafted-not-evaluated (N-impact: 0 each) |
| re-thresholded conditioning (any change to 0.90/0.10 split or ISO-warm prior used as a tuned occupancy) | drafted-not-evaluated (N-impact: 0); evaluation is +1 N |

**N = 11 as of this task** (unchanged; no outcome contact). First
outcome contact on the H10 primary → **N ≥ 12**.

---

## 14. CARD→SPEC DEVIATION TABLE (logged, never silent)

| # | card (original) | spec (tested form) | where / why |
|---|---|---|---|
| 1 | gate sketch: `ofi`-style single-tail `> 0.90` only in on_condition prose | two-sided decile in gate + evaluate (`≥ 0.90` OR `≤ 0.10`); off_condition releases via interior band with `percentile_margin` | §5.2/§5.3 — card conditional-distribution statement is explicitly two-sided; hysteresis must be referenced |
| 2 | hysteresis `{posterior_margin: 0.15}` only in H9 sketch; H10 card omitted explicit YAML | both margins declared and referenced (`posterior_margin: 0.15`, `percentile_margin: 0.20`) | §5.3 — dead-config loader rule; 0.20 matches H9 card's percentile_margin sketch for decile tails |
| 3 | `kyle_lambda_60s` in l1_signature_sensors | declared on trend_mechanism + depends_on_sensors for G16; **not** in required-warm entry set; F2-only | §1.1/§1.3 — fingerprint load-bearing for attribution, not for entry extremes |
| 4 | ISO-warm 0.95 in density headline | labeled **ASSERTED**; census measurement + park-on-power consequence pre-registered | §1.1.1/§4.4 — backlog 15 / 3-M non-exempt prior |
| 5 | Implementation: "New sensor module + registration + YAML" | **phased** per SEQUENCING RULING: Phase A = sensor + census instrument + harness IC row; Phase B = full card gated on step-2 PASS | §15 / Next action — backlog-14 Ordering B for H10 only |
| 6 | Signing not called out beyond "L6 signing errors in fast markets" failure mode | L2-loss ledger L6 row is sweep-specific (tick-rule on ISO bursts; failure shapes dilution vs negative tail); not H9 OFI framing | §2/§8 — Amendment D |

No other substantive deviation exists; hypothesis text, family,
half-life, horizon, archetype, counterparty, κ decomposition and
freeze, park arithmetic, symbol set, F1–F5, power structure, and
consequence-precedence sketch are carried as confirmed.

---

## 15. DELIVERABLES MAP (phased; nothing implemented here)

### Phase A (pre-Task-8; Ordering B — SEQUENCING RULING)

1. **`sweep_flow_imbalance` sensor module** — `Sensor` protocol +
   `SensorSpec` registration; params per §1.1.1; version 1.0.0;
   unknown-id / filter unit tests; halt-flush / warm goldens;
   coverage ≥ 80 % on new code; mypy strict; ruff/DTZ clean.
2. **Census instrument** — deterministic offline pass
   (PYTHONHASHSEED=0) over frozen {APP, RMBS} × 20 sessions: eligible
   ISO warm fraction, joint conditioning occupancy at frozen
   thresholds, contamination-excluded episode counts vs ≥ 130 pooled
   bar, ISO-warm ASSERTED→measured resolution, RMBS coverage rule.
   **No forward returns / IC in the census instrument itself** unless
   bundled as the harness row below under the same freeze.
3. **Harness IC row** — implementation-independent step-2b statistic
   on the census-pinned predicate (research-workflow Ordering B);
   harness sign-golden required before 2b; pre-register
   census-consistency smoke consequence for Phase B mismatch
   (implementation-correction re-run, N unchanged).

### Phase B (gates on step-2 PASS only)

4. `alphas/sig_sweep_kyle_drift_h900_v1/sig_sweep_kyle_drift_h900_v1.alpha.yaml`
   — schema 1.1 SIGNAL; blocks per §5; horizon 900; trend_mechanism
   KYLE_INFO hl 450; failure_signature §10; falsification_criteria §12.
5. `configs/bt_sig_sweep_kyle_drift_h900_v1.yaml` — pinned 00c profile,
   session knobs, symbol list {APP, RMBS}.
6. Bootstrap wiring for SFI features at h = 900; parity assessment —
   any moved locked baseline requires architectural review, never a
   value edit.
7. Tests: Track-A strength/property tests, gate-DSL compile (both
   margins referenced), config guard, determinism suite.

---

## 16. STATUS

**Status:** `hypothesis → candidate pending validation`

No outcome statistic exists. Statistical validity and execution
validity remain untested. H9 remains CONTINGENT SECOND CARD
(revivable iff H10 passes step 2; presumptively dead on H10 step-2b
magnitude fail). H11 remains NOT SELECTED.

---

## NEXT ACTION (Amendment F — Phase A scoping contract)

**Concrete next action:** execute **Phase A** as the pre-Task-8
deliverable definition — implement and register `sweep_flow_imbalance`
v1.0.0 (§1.1.1 filter set frozen), build the census instrument that
measures the ASSERTED ISO-warm 0.95 prior and pooled episode counts
against the ≥ 130 bar on frozen {APP, RMBS}, and land the harness IC
row on the census-pinned predicate — then stop for Lei review of the
Phase-A outputs before any Phase-B YAML / Task-8 protocol freeze.
**No Task-8 protocol, no forward-return adjudication, and no Phase-B
alpha YAML until Phase A completes and step-2 is authorized to run.**
