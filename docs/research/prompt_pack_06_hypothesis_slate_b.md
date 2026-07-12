<!--
  File:   docs/research/prompt_pack_06_hypothesis_slate_b.md
  Status: hypothesis — DECIDED (2026-07-12): H8 CONFIRMED for Task 7,
          H6/H7 NOT SELECTED — see DISPOSITIONS at end of file.
          Second, feasibility-
          constrained hypothesis slate (Task 6-B, 2026-07-11). Three
          pre-registered SIGNAL-layer candidates. Pre-registration
          class: NO forward returns, NO IC, NO signal evaluation was
          computed in producing this file; the census and feasibility-
          map artifacts (boundary counts, σ_H, warm coverage,
          contamination rates) were read as data-contract
          characterization only. Trial ledger: N = 10, unchanged —
          design does not increment (FQ-6B-R rule).
  Owner:  microstructure-alpha (cards) / research-workflow (trial
          ledger); prompt-pack Task 6-B, Phase B.

  Provenance (FQ-3 template):
    git_sha: "7a08c95135fbb1dff0762bf5747eb135e28a7d09" (HEAD at task
      start; this task's outputs — this file plus the three approved
      ride-along backlog/DISPOSITIONS amendments — are the first
      changes after it)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (design only; every number below is quoted from committed
      artifacts or derived by hand arithmetic recorded inline)"
    normative_inputs:
      prompt_pack_05_horizon_feasibility_map.md (§2 floors, §3 κ_req
        table, §4 open regions + central-κ shrinkage, §5 caveats,
        §6 operative pre-filter rule — THE slate pre-filter),
      sig_inventory_fade_v1_validation_protocol.md CENSUS RESULTS
        (C.3 roll-up, C.5 warm coverage + contamination, per-cell
        table — realized boundary densities and warm reality),
      sig_inventory_fade_v1_formal_spec.md §4.1 (the H2-spec κ
        factor-decomposition style, reused structurally, never its
        values as a benchmark),
      prompt_pack_03b_print_eligibility.md (§3.3 Class table, §4.4
        netting, §6 guards),
      prompt_pack_03c_universe_and_cache.md (§2 grid + L1–L4 verbatim
        carry, §5.1 inventory counts, §7 realized tick buckets),
      prompt_pack_00b_edge_units_convention.md (one-way convention),
      prompt_pack_04_hypothesis_slate.md + prompt_pack_04a_slate_review.md
        DISPOSITIONS (H1/H2 park lessons, FQ-6B-R ledger rule).
-->

# Prompt-pack Task 6-B — Hypothesis slate B (feasibility-constrained)

Pre-registration document. Three candidate SIGNAL-layer hypotheses,
written before any data contact for these candidates (Inv-2). The
shipped alphas, the parked H1–H5 cards, and all prior gas decisions
are pointers to mechanics and conventions only — no candidate's
economics is derived from, benchmarked against, or parameterized from
them (session constraint 6). Every number below is either quoted from
a committed artifact (cited) or a stated design prior (flagged).

## 0. SLATE SHAPE — three cards, one family (justification recorded)

This slate supersedes the original five-card / ≥3-family rule. The
reduction is forced by the measured feasibility map (7a08c95), not
chosen for convenience:

1. **INVENTORY / HAWKES_SELF_EXCITE: INADMISSIBLE — closed at honest
   κ.** G16 legality confines both families to H ∈ {30, 120} (map §4
   envelope table). H = 30 is closed universe-wide in both execution
   variants (best cell APP passive κ_req 0.379 at p90). At H = 120
   the passive κ_req is APP 0.222 / RMBS 0.240 at the median and
   0.175 / 0.204 even at p90 — all above an honest central κ ≈ 0.16
   (map §4 shrinkage note). Closed at **every** session quantile at
   honest κ; the 0.30-ceiling opening on {APP, RMBS} is the
   permissive bound the H2 park already demonstrated does not
   survive contact (census 642d12d: 1/70 floored cells viable,
   0 clean episodes).
2. **SCHEDULED_FLOW: admissible in principle, no card — every
   non-close intraday scheduled mechanism fails the ≥ 100 power floor
   on the frozen grid.** Count basis, stated per the task rule:
   single-window-per-session mechanisms (opening-auction aftermath,
   any specific scheduled time such as a 10:00 ET release window)
   yield exactly 10 episodes/symbol on the 10-session grid — the H4
   density failure repeated. The densest non-close scheduled grid we
   could construct — 30-minute algo-clock boundaries, 10:00–15:30,
   12/session — yields ~120/symbol *unconditioned*, requiring a
   conditioning fraction ≥ 0.83 to stay above 100; no meaningful
   directional conditioning preserves 83 % of boundaries. No
   SCHEDULED_FLOW card can be powered on this grid; the close-window
   revival path stays in backlog entry 8 (updated this task).
3. **LIQUIDITY_STRESS:** exit-only (G16); no entry card possible.
4. **KYLE_INFO is therefore the only family with an open entry region
   on the frozen grid at passive execution** (map §4), and the task's
   horizon restriction {300, 900} intersects it as follows:
   - **H = 900 is density-dead for tail conditioning.** In-window
     (09:35–15:50) boundaries at h = 900: 25/session (09:45…15:45) ⇒
     250/symbol. The ≥ 100 floor then requires a conditioning
     fraction ≥ 0.40 — near-unconditional entry — and weak
     conditioning collapses the derived κ (dislocation factor c_D at
     a median-one-sidedness condition ≈ 0.4–0.5, giving κ ≈
     0.05–0.07 against κ_req,med 0.110/0.112 on APP/RMBS). The
     (κ, power) requirement is jointly unsatisfiable at H = 900.
   - **All three cards land at H = 300, passive**: 76 in-window
     boundaries/session ⇒ 760/symbol — tail conditioning at ~0.20
     fraction leaves ~100–150 episodes, marginal but plausible.
   - **Taker is not even a drafted fallback**: κT_req at H = 300 is
     0.449 (APP median, the universe best) — ≥ 1.5× above the 0.30
     derivation ceiling. Closed at design; no taker variant is
     registered.

Three cards is also the honest distinctness bound: the three
genuinely independent KYLE conditioning observables on this data are
quote-flow imbalance, exchange-certified sweep prints, and realized
dislocation with impact confirmation. A fourth card would be a
parameter variant of one of these — ledger inflation, not a
hypothesis.

**Park lessons applied as design rules (pack-04 DISPOSITIONS 1, 6):**

- **H1 lesson** — the realized cost floor is checked FIRST, at design,
  against the card's own derived κ (map §6 rule; backlog 7). No card
  below is carded on illustrative cost priors.
- **H2 lesson** — a σ-conditional (session-tail) region is admissible
  only if it also carries ≥ 100 projected episodes; a tail region
  that is κ-open but power-dead is EXCLUDED at design, not
  pre-registered and ridden to a park. This rule removes RMBS from
  two of the three cards below.

## 0.1 Conventions binding on every card

- **Units:** one-way, per-fill, bps of fill notional throughout (00b
  THE CONVENTION). Round-trip figures derived, never disclosed.
- **Cost floors:** the map §2 recomputed passive floors
  `1.5 × C_ow,stressed = 2.25 × (2.0 + fee)` per symbol — APP 4.68,
  RMBS 5.46, ENSG 5.04, DIOD 6.23, PCTY 5.19, MLI 5.32, CROX 5.66,
  OLN 8.69 bps. Riders (SELL-leg 0.5 bps regulatory + TAF) are NOT
  folded into floors, per the map §2 / protocol §11.1 convention —
  each card discloses its short-side rider arithmetic explicitly
  (it is material at these κ levels; see per-card block 1).
- **σ_H and κ_req:** map §3, Hyndman–Fan-7 quantiles over the 10 grid
  sessions; the artifact
  (`artifacts/horizon_feasibility_map_2026-07-11.json`,
  sha256 362c42ca…) is authoritative at rounding boundaries.
- **Pre-filter (map §6):** a card enters ranking only if its
  (family × horizon × symbol set × execution) intersects a FEASIBLE
  region **at the card's own frozen κ**. A card whose honest κ needs
  the p90 σ tail is dead at design — none below does; one considered
  mechanism (micro-price-divergence level drift, honest κ ≈ 0.11
  against APP/300 p90 κ_req 0.127) was killed at design on exactly
  this rule and appears only in the ledger appendix.
- **Session window:** entries only in 09:35–15:50 ET
  (`no_entry_first_seconds 300`, flatten 600 s before close) — all
  boundary-count arithmetic below uses the in-window count.
- **Warm reality (census C.5):** no card places a load-bearing gate
  on `spread_z_30d` anywhere (measured warm 0.03–0.16 on
  ENSG/DIOD/MLI/PCTY; and although APP measures 0.94, the arm is
  omitted entirely rather than carried symbol-conditionally).
- **Contamination (census C.5):** 80 % (496/621) of the census's
  eligible extreme-flow boundaries carried Class-B prints or
  correction records under DI-09. Any NEW trade-fed sensor below
  carries the 03b §3.3 Class-A filter + §4.4 correction netting as
  explicit constructor/YAML parameters; any *inherited* unfiltered
  trade-fed sensor used near extremes carries an explicit
  justification (per-card block 4).
- **Structural boundaries (R8, once for all cards):** SEC Rule 612
  half-penny (Nov 2027); MDI round-lot reassignments (semiannual,
  per symbol); the 2026-04-27 vendor admissibility split — the grid
  is entirely pre-2026-04-27 by construction; never pool across.
- **L1–L4 (03c §2, verbatim carry):** every card below gates on the
  HMM regime posterior, so all four grid limitations attach to its
  census-stage strata — L1 (calm = ONE episode; calm conclusions are
  calm-as-realized Dec-2025/Feb-2026 only), L2 (adjacent calm dates
  01-26/01-27), L3 (RMBS most heavily conditioned; flag per-symbol),
  L4 (elevated stratum = two heterogeneous episodes; report
  per-window). Cited here once and inherited by every card's
  DATA REQUIREMENTS.
- **OQ-3 caveat:** runtime mechanism-share enforcement not active; no
  capacity claim below relies on it.
- Cost-model pins (00c): passive adverse selection 2.0 bps,
  commission min $0.35 on the 80-share reference fill, latency
  20 ms + 50 ms (≪ 300 s — no latency-edge claim anywhere; L7).

---

## H6. ALPHA_ID (proposed): `sig_ofi_kyle_drift_v1`

**HYPOTHESIS.** An institution working a parent order through
limit-order-heavy execution algos persistently adds size on its own
side of the top of book and depletes the opposite side **because**
top-of-book participation minimizes crossing cost under a completion
schedule, **which must leak into L1 as** persistent signed order-flow
imbalance (Cont–Kukanov–Stoikov OFI) in the parent's direction. Part
of the price impact of that flow is permanent (information/pressure
incorporation, the KYLE signature), and while the parent is still
in flight the unrealized remainder of the permanent impact continues
to arrive — drift in the flow direction over the next 300 s.

Conditional-distribution statement: with `ofi_integrated` = Σ of
per-event L1 OFI over the trailing 300 s window (shares; `ofi_raw` +
`sum` reducer at h = 300): `E[mid log-return over the next H = 300 s |
ofi_integrated percentile ≥ 0.90 and P(vol_breakout) < 0.7] > 0`
(symmetric short for percentile ≤ 0.10), magnitude κ_frozen × σ₃₀₀
with κ central 0.16 (block 1) ≈ **5.4 bps one-way at the APP median
session** (σ₃₀₀ 33.8).

**ARCHETYPE & COUNTERPARTY (R2).** Archetype:
informed/committed-flow-following. Structural actor: the
schedule-bound institutional parent order. Structural counterparty:
(i) latency- and attention-constrained liquidity providers whose
repricing lags persistent one-sided flow — the gap between their
quote and the post-flow value funds the drift; (ii) the parent
itself, whose implementation shortfall is the funding pool — riding
its remaining schedule transfers a slice of the impact cost it must
pay anyway. Conservation: integrated edge ≤ aggregate temporary +
permanent impact paid by scheduled parents — large and structurally
funded.

**FAMILY & MIRAGE RISK (R3).** Family: `KYLE_INFO`.
`expected_half_life_seconds = 150` (envelope 60–1800 ✓);
`horizon_seconds = 300`; ratio 2.0 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [kyle_lambda_60s]` (G16 rule-5 KYLE primary
fingerprint ✓; `ofi_ewma`/`ofi_raw` are the family-related direction
observables). Mirage rank: **MIXED (divisor 1.5 on the pack-04 M
scale)** — OFI is a quote-delta observable: size changes at the
touch are revocable and free to manufacture (unlike prints). The rank does not settle the archetype:
real OFI persistence proves flow pressure, not information — F2's
λ-elevation clause tests the KYLE attribution directly.

**OBSERVABLE STATE.** All existing sensors: `ofi_raw` (NBBOQuote-fed;
`ofi_integrated` sum-reducer factory-wired at any h),
`kyle_lambda_60s` (v2.0.0 causal; zscore + percentile views wired),
`realized_vol_30s` (+ zscore, wired). Needed wiring: a percentile
view of `ofi_integrated` (config/bootstrap-level factory addition,
the H3-precedent pattern — not a new sensor). **No new sensor. No
`spread_z_30d` anywhere.**

**EXPECTED BEHAVIOR.** Sign: continuation with the flow. Horizon
300 s, hl 150 s — most drift in the first 2–3 minutes as the parent's
remaining children arrive. Regime: requires two-sided orderly books;
dangerous in disorderly breakout (flow one-sidedness stops meaning
scheduled execution). Sketch (long side; short mirrors):

```
on_condition:  "P(vol_breakout) < 0.7 and ofi_integrated_percentile > 0.90
                and realized_vol_30s_zscore <= 3.0"
off_condition: "P(vol_breakout) > 0.7 or realized_vol_30s_zscore > 3.0"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.20}
```

**COST ARITHMETIC PLAUSIBILITY.** Passive (maker) entry on the flow
side: C_ow(APP) = 2.08 bps (map §2). Design edge at κ central × APP
median σ₃₀₀ = 0.16 × 33.8 ≈ 5.4 bps ⇒ G12 margin 5.4 / 2.08 ≈ 2.6 ✓;
vs the stressed floor 4.68 ⇒ headroom ≈ 1.16× — **alive but thin**;
the card lives or dies on passive-fill quality (block 1 park
arithmetic; F4). Taker: closed at design (κT_req 0.449 ≫ 0.30).

### H6 · 1. FEASIBILITY CITATION (map §3/§6; κ FROZEN at design)

Map κ_req, passive, H = 300 (med/p75/p90): APP **0.139**/0.132/0.127;
RMBS 0.173/0.143/0.137; CROX 0.228/0.214/0.185; all other symbols
≥ 0.240 at the median.

Derived κ, H2-spec factor style (each factor a stated prior, no data
contact; **FROZEN — one-way ratchet, revisable down on evidence,
never up**):

    edge_ow = κ × σ₃₀₀,   κ = c_D × f_perm × r_rem × f_H × f_pass

| factor | meaning | prior range (central) | grounding |
|---|---|---|---|
| `c_D` | dislocation of the conditioning window in σ₃₀₀ units given the ≥ p90 \|flow\| tail | 0.8–1.6 (**1.2**) | CKS: extreme-OFI windows carry ~1σ contemporaneous moves; > 1.6 systematically would contradict the non-breakout gate |
| `f_perm` | permanent share of the flow-driven move | 0.4–0.7 (**0.55**) | Kyle/GM decomposition of scheduled institutional flow |
| `r_rem` | unrealized remainder of the permanent impact at the boundary (parent still in flight) | 0.3–0.7 (**0.5**) | uniform detection time along the parent's schedule ⇒ half remains in expectation |
| `f_H` | remainder realized within H = 300 at hl = 150 | 0.6–0.85 (**0.75**) | 1 − e^(−300/216) = 0.75 |
| `f_pass` | passive-entry haircut: drift forgone while resting + fill selection beyond the 2.0 bps AS charge | 0.5–0.8 (**0.65**) | passive same-side entry fills on pullbacks — conditionally adverse |

    κ ∈ [0.03, 0.30 (capped at the derivation ceiling)],  central ≈ 0.16 — FROZEN

**Park arithmetic, pre-stated (κ_frozen · σ_med vs 1.5 × C_ow,stressed):**

| symbol | κ_frozen·σ₃₀₀,med | floor | verdict at design |
|---|---|---|---|
| APP | 0.16 × 33.8 = **5.41** | 4.68 | OPEN at median (κ_req 0.139 ≤ 0.16) — headroom 16 % |
| RMBS | 0.16 × 31.6 = 5.06 | 5.46 | median CLOSED (κ_req 0.173 > 0.16); p75-open (0.143) but tail episodes ≈ 33 ≪ 100 ⇒ **EXCLUDED (H2 lesson: κ-open, power-dead)** |
| CROX and rest | 0.16 × 24.8 = 3.97 (best) | 5.66 | CLOSED at every quantile |

**Symbol set = {APP}.** The card does NOT need the p90 tail — it is
median-open on its set at its own κ, not at the 0.30-ceiling
fallback. Short-side rider disclosure (floors exclude riders per
convention): SELL-entry floor APP = 2.25 × (2.0 + 0.08 + 0.507) ≈
**5.82 bps** ⇒ rider-inclusive κ_req 0.172 > κ central 0.16 — the
short side clears only in p90-tail sessions at central κ.
Pre-stated consequence: if the census-stage measured short-side edge
fails the rider-inclusive floor, the short side drops, long-only
episode count halves (≈ 52 < 100), and the card **PARKS on power** —
no threshold tuning.

### H6 · 2. EPISODE-DENSITY PLAUSIBILITY

Basis: map §1 — 78 emitted h=300 boundaries/session; 76 in the
09:35–15:50 window ⇒ **760 in-window boundaries/symbol** over the 10
grid sessions (consistent with the census's 195/188 at h=120). At
h = 300 with a 300-s conditioning window, consecutive windows are
disjoint — no double-count correction.

Conditioning fraction assumed: percentile-tail 0.20 (≥ 0.90 / ≤ 0.10,
two-sided — fraction by construction of the percentile view) ×
gate ≈ 0.90 (P(vol_breakout) < 0.7 is deliberately permissive;
assumption, census-measurable) × warm ≈ 0.95 (block 3) ×
viable-session fraction ≈ 0.8 (σ₃₀₀,min = 4.68/0.16 = 29.3 bps ⇒
σ₁₂₀ ≳ 18.5 under diffusive scaling; 8/10 APP census cells qualify;
the map artifact's per-cell σ₃₀₀ is the census-stage authority).

**Expected ≈ 760 × 0.8 × 0.90 × 0.95 × 0.20 ≈ 104 episodes on APP —
straddles the ≥ 100 floor.** Stated plainly: power is this card's
binding census risk; the park rule is armed on the measured count;
a census count < 100 parks the card with no tuning.

### H6 · 3. SENSOR WARM REALITY (census C.5 citations per sensor)

| sensor | census warm | this card's basis |
|---|---|---|
| `realized_vol_30s_zscore` | **measured**: 0.94–0.995 mean everywhere (APP ≥ 0.94) | gate arm — measured, safe |
| `ofi_raw` / `ofi_integrated` | **unmeasured** in the census | estimated from 03c §5.1 quote counts: APP 37.7k–70.4k quotes/session ≈ 1.6–3.0/s ⇒ a 300-s window holds ~480–900 quotes — warm essentially always on APP; census-stage verification pre-registered (a measured warm fraction < 0.5 drops the symbol per the power rule — coverage, not tuning) |
| `kyle_lambda_60s` (fingerprint/F2 only) | **unmeasured**; closest measured proxy `inventory_pressure` (20 trades/60 s) ≥ 0.985 everywhere | λ needs 30 trades/60 s — 1.5× stricter; APP trade rate 3.6–6.3/s ⇒ 216–380 trades/60 s ⇒ warm ~always on APP; verified at census stage |
| `spread_z_30d` | measured 0.03–0.16 on thin names | **NOT USED** — no arm, no fallback needed |

### H6 · 4. CONTAMINATION POSTURE

The conditioning observable is **quote-fed** — Class-B prints and
correction records structurally never enter `ofi_raw` state, so the
census's 80 %-flagged-at-extremes finding (DI-09, backlog 10) does
not apply to the entry condition. The analogous quote-side hazard is
**L5 cancel conflation** (OFI cannot distinguish trade-driven from
cancel-driven size changes) — carried as failure mode 3, tested by
F2, not filterable by condition codes. `kyle_lambda_60s` is
trade-fed, existing, unfiltered (DI-09): justification for
inheriting it — it enters **only** the F2 mechanism-confirmation
diagnostic at aggregated percentile level, never the entry
conditioning at distribution extremes; a Class-A-filtered NEW λ
variant is pre-registered as fallback (ledger appendix,
drafted-not-evaluated) if census composition checks show derived/
average prints distorting λ in signal-active windows.

**DATA REQUIREMENTS.** NBBOQuote schema verbatim — met (03 §1);
quote-condition semantics benign on interpreted ids, filtering must
be presence-tolerant (03b §5.3(a)); the 03b §6 unknown-id guard is
inherited by the evidence pipeline. L2-loss rows touched: **L5**
(cancel/replenishment conflation — the core observable's weakness),
**L2** (passive queue position: fills conditionally adverse), **L1**
(parent-order state unobservable — "still in flight" is inferred),
**L4** (hidden liquidity absorbs the remainder). L1–L4 grid
limitations attach per §0.1. **Nothing BLOCKING.**

**FAILURE MODES (≥3).**

1. **(a) Tick-grid artifact (R8):** on tighter-grid strata the
   percentile tail of OFI can coincide with discrete book states;
   spread-in-ticks distribution report + re-derivation on the
   ≥ 4-tick stratum required (APP pooled median 61 ticks makes this
   unlikely to bind, but the test is mandatory). Dilution.
2. **(b) Adversarial manufacture — the card's defining risk:**
   quote-size layering/cancelling manufactures OFI at ~zero cost
   (cancels are free; no prints needed). The manufactured shape:
   inflate same-side OFI into the p90 tail, induce continuation
   entries, flip. Per-event indistinguishable (L5 — no cancel
   attribution). Distributional defense (pre-registered monitor):
   genuine parent flow prints — signal-active windows without
   elevated same-direction trade volume are the adversarial
   signature (F2 doubles as this monitor). Failure shape: **negative
   tail, adversarially timed**.
3. **(c) L2-ledger bite — L5 then L2:** cancel-driven OFI in
   thinning books mimics scheduled flow with no parent behind it
   (dilution); passive fills concentrate exactly when continuation
   fails (thin-margin erosion → trap-quadrant).
4. Already-impounded information: flow bursts on public news carry
   no 300-s remainder. Dilution.

**FALSIFICATION CONDITIONS.**

- F1 (forward test): RankIC(ofi_integrated, 300-s forward mid
  log-return) on the pre-registered census boundaries ≤ 0, or below
  the honest-N noise ceiling → dead. Clause:
  `"ofi_integrated_percentile > 0.90 boundaries show 300 s
  forward-return sign agreement <= 0.50 over any rolling 20-session
  window"`.
- F2 (mechanism tie — permanent impact + real flow): KYLE requires
  elevated λ and same-direction print volume during signal windows.
  Clause: `"kyle_lambda_60s_percentile < 0.20 across signal-active
  boundaries"` or `"no elevation of same-direction trade volume
  within the conditioning window vs matched baseline"` — flow-shaped
  quotes without impact or prints refute the attribution (and flag
  the manufactured regime).
- F3 (regime-stratum stability): sign flips to reversion in the
  non-breakout stratum → the committed-flow premise is wrong; sign
  reversal across spread-in-ticks strata → definition kill (R8).
- F4 (execution validity): pre-cost drift exists but ≤ 1.5 × C_ow
  under the pinned passive realism profile or dies under
  `--inv12-stress` → **trap-quadrant**. (Pre-declared as the most
  likely exit given the 1.16× stressed headroom.)
- F5 (structural boundaries): the three §0.1 hard splits.

**IMPLEMENTATION FEASIBILITY.** YAML + one config/bootstrap-level
factory line (percentile view of `ofi_integrated`). No new sensor.
Cheap.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: convention-eligible
continuous dollar volume, grid-session median (03c §2): APP
$1.879 B/day. Passive footprint bounded by fill opportunity at
top-of-book scale (APP p50 ≈ 80 sh/side) — strictly small-capital,
**Sharpe-max**. Who else watches: OFI is the most-published L1
predictor in existence; assume maximal crowding — the residual for a
70 ms observer at 300 s is whatever the sub-ms crowd leaves, which is
why F4 is expected to bind. Correlated unwind: flow-followers exit
together on reversal; hazard exit + hard age 2×hl = 300 s is
load-bearing. OQ-3 caveat applies.

---

## H7. ALPHA_ID (proposed): `sig_sweep_kyle_drift_v2`

*(Passive-first redesign at H = 300 of the mechanism whose taker
variant `sig_sweep_kyle_drift_v1` was parked at design — pack-04
DISPOSITIONS 1: stated 3–6 bps taker edge vs ≥ 9.12 bps realized
taker floor. The park is a pointer, not a prior: this card's
economics are derived fresh, and the execution mode and horizon that
killed v1 are exactly what changed. N-row: new drafted row; the v1
rows stand unchanged in the pack-04 ledger.)*

**HYPOTHESIS.** An institutional trader holding short-half-life
information executes with intermarket sweep orders **because** paying
take fees and through-prices across venues simultaneously is only
rational when the value of immediacy exceeds the cost of patience —
urgency reveals information — **which must leak into L1 as** clusters
of condition-14 prints, one-sided when signed against the prevailing
NBBO, with permanent impact (KYLE). Because the sweeper's information
half-life exceeds the burst duration, drift continues over the next
300 s, and a **passive same-side entry** (join the NBB on a buy
sweep) harvests it at maker cost — the only execution mode the
measured cost structure leaves open.

Conditional-distribution statement: let `SFI(t; 300 s)` = signed
sweep-flow imbalance, Σ(±size) over **eligible** condition-14 prints
in the trailing 300 s, quote-rule signed, in shares (NEW sensor,
block 4 filter): `E[mid log-return over the next H = 300 s |
SFI percentile ≥ 0.90 and P(vol_breakout) < 0.7] > 0` (symmetric
short), magnitude κ_frozen × σ₃₀₀ ≈ **5.3 bps one-way at the APP
median session**.

**ARCHETYPE & COUNTERPARTY (R2).** Archetype:
informed-flow-following. Structural actor: the informed sweeper
(certified by the exchange-stamped ISO flag — paid-for urgency).
Structural counterparty: resting liquidity providers whose displayed
quotes the sweep lifts across venues — standing commitments repriced
with finite latency; during urgency bursts they under-collect the
adverse-selection premium, and that under-collection funds the
drift. Secondary: uninformed flow providing at stale prices after
the burst. Conservation: integrated edge bounded by
(sweep volume × permanent impact); id 14 = 17.6 % of tape volume
(03b §2) — non-trivially large pool.

**FAMILY & MIRAGE RISK (R3).** Family: `KYLE_INFO`.
`expected_half_life_seconds = 150` (envelope ✓); `horizon_seconds =
300`; ratio 2.0 ✓. `l1_signature_sensors: [kyle_lambda_60s,
sweep_flow_imbalance]` — `kyle_lambda_60s` rule-5 primary ✓. Mirage
rank: **LOW** — condition 14 is an exchange-stamped attribute of an
irrevocable execution. The rank does not settle the archetype:
prints prove the sweep, not the information — a delta-hedger sweeps
identically; F2 tests the impact premise.

**OBSERVABLE STATE.** **NEW-SENSOR `sweep_flow_imbalance`**
(Trade-fed): deque of `(ts_ns, signed_size)` over trailing 300 s;
value = windowed signed sum; O(1) amortized incremental update (the
`inventory_pressure` pattern); warm = ≥ 20 eligible prints in
window. Explicit parameters (block 4): `eligible_conditions` =
prints carrying id 14 within the 03b Class-A universe (id 41
overlay pass-through), `drop_correction_records = {10, 11, 12}`, no
conditioning on retroactive `correction ∈ {1, 7, 8}` (03b §4.3),
plus the pre-registered unknown-id guard. Existing:
`kyle_lambda_60s` (fingerprint + F2), `realized_vol_30s` (gate).
Reducers: percentile view on the new sensor. **No `spread_z_30d`.**

**EXPECTED BEHAVIOR.** Continuation with the sweep direction; hl
150 s. Passive entry protocol (design intent, spec'd in Task 7):
rest at the NBB (long case) for ≤ 60 s after the boundary; cancel on
runaway (no chase). Regime: dead in compression (no urgency), gated
off in disorderly breakout (signing degrades — L6). Sketch:

```
on_condition:  "P(vol_breakout) < 0.7 and sweep_flow_imbalance_percentile > 0.90
                and realized_vol_30s_zscore <= 3.0"
off_condition: "P(vol_breakout) > 0.7 or realized_vol_30s_zscore > 3.0
                or sweep_flow_imbalance_percentile < 0.60"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.20}
```

**COST ARITHMETIC PLAUSIBILITY.** Passive: C_ow(APP) = 2.08 bps;
design edge 0.16 × 33.8 ≈ 5.3–5.4 bps ⇒ G12 margin ≈ 2.6 ✓; vs
stressed floor 4.68 ⇒ ≈ 1.15× headroom — thin; identical shape to
H6. Taker (the v1 mode): closed at design, κT_req 0.449 — this card
exists *because* the passive floor is 3.2× lower than the taker
floor on APP (4.68 vs 15.17, map §2).

### H7 · 1. FEASIBILITY CITATION (map §3/§6; κ FROZEN)

Map κ_req, passive, H = 300: APP **0.139**/0.132/0.127
(med/p75/p90); RMBS 0.173/0.143/0.137; rest ≥ 0.228 median.

Derived κ (factors named, FROZEN; same structure as H6 with
sweep-specific centrals):

| factor | prior range (central) | grounding |
|---|---|---|
| `c_D` | 0.8–1.6 (**1.2**) | extreme-\|SFI\| windows carry ~1σ contemporaneous moves (sweeps consume the book) |
| `f_perm` | 0.5–0.8 (**0.65**) | urgency certification skews the impact mix permanent — above generic flow (H6's 0.55); the one factor the ISO flag buys |
| `r_rem` | 0.3–0.6 (**0.45**) | sweep parents complete faster than passive-algo parents — less remainder at detection |
| `f_H` | 0.6–0.85 (**0.75**) | 1 − e^(−300/216) at hl 150 |
| `f_pass` | 0.45–0.75 (**0.6**) | sharper bursts ⇒ pullback fills rarer and more adverse than H6's |

    κ ∈ [0.03, 0.30 (capped)],  central ≈ 0.158 ≈ 0.16 — FROZEN

**Park arithmetic, pre-stated:**

| symbol | κ_frozen·σ₃₀₀,med | floor | verdict |
|---|---|---|---|
| APP | 0.16 × 33.8 = **5.41** | 4.68 | OPEN at median (κ_req 0.139) — 16 % headroom |
| RMBS | 5.06 | 5.46 | median CLOSED; p75-open but tail episodes ≈ 33 ≪ 100 ⇒ **EXCLUDED (H2 lesson)** |
| rest | ≤ 3.97 | ≥ 5.66 | CLOSED |

**Symbol set = {APP}.** Median-open at own κ; no p90 dependence.
Short-side rider: identical to H6 — rider-inclusive short floor 5.82
⇒ κ_req 0.172 > 0.16; pre-stated consequence chain identical (short
drops ⇒ long-only ≈ 52 episodes ⇒ **PARK on power**).

### H7 · 2. EPISODE-DENSITY PLAUSIBILITY

Same boundary basis as H6 (760 in-window/symbol). Conditioning
fraction assumed: percentile tail 0.20 × gate 0.90 × warm 0.95
(block 3 — ISO print availability keeps the new sensor warm on APP)
× viable-session fraction 0.8 (σ_min 29.3 bps, same as H6) ⇒
**≈ 104 episodes on APP — straddles the ≥ 100 floor; park rule
armed on the measured count** (census < 100 ⇒ PARK, no tuning).
One sweep-specific check: the sensor's own conditioning set (id-14
prints, 28.5 % of prints / 17.6 % of volume on the 03b APP scan)
must hold at census scale — a materially lower grid-wide ISO rate
shrinks warm coverage and episode counts together; reported, not
tuned.

### H7 · 3. SENSOR WARM REALITY (census citations)

| sensor | census warm | basis |
|---|---|---|
| `sweep_flow_imbalance` (NEW) | unmeasured (does not exist yet) | design warm ≥ 20 eligible prints/300 s; APP ISO rate ≈ 0.285 × (3.6–6.3 trades/s) ≈ 1.0–1.8/s ⇒ ~300–540 eligible prints/window — warm ~always on APP; census-stage verification pre-registered |
| `kyle_lambda_60s` | unmeasured; proxy `inventory_pressure` ≥ 0.985 measured | as H6 block 3 — warm ~always on APP at 30 trades/60 s |
| `realized_vol_30s_zscore` | **measured 0.94–0.995** | gate arm, safe |
| `spread_z_30d` | 0.03–0.16 thin names | **NOT USED** |

### H7 · 4. CONTAMINATION POSTURE

Exemplary case for the convention: the conditioning observable is a
**NEW trade-fed sensor used at distribution extremes** — precisely
the census-flagged configuration (80 % of extreme boundaries
Class-B-contaminated under DI-09; dominated by id 10 Derivatively
Priced and id 2 Average Price). The 03b §3.3 Class-A filter + §4.4
correction netting are therefore **explicit NEW-sensor parameters**,
load-bearing by design: `eligible_conditions` (Class A ∩ carrying
id 14; 41 overlay pass-through), Class-B exclusion set verbatim,
`drop_correction_records = {10, 11, 12}`, retroactive-correction
conditioning banned (Inv-6). No unfiltered trade-fed sensor is
inherited at extremes; `kyle_lambda_60s` inheritance justified as in
H6 (F2 diagnostic only; filtered NEW variant pre-registered
fallback).

**DATA REQUIREMENTS.** `conditions` tuple verbatim on `Trade` — met
(03 §1.1, DI-09); 03b convention — met as parameters; condition-14
prevalence — met, ample sample; contemporaneous NBBO for quote-rule
signing — met. L2-loss rows: **L6** (signing errors concentrate in
fast markets exactly when sweeps cluster — dilution), **L4** (hidden
midpoint liquidity absorbs sweeps — no continuation), **L3** (visible
prints under-represent multi-venue demand; direction only is
consumed), **L2** (passive queue adversity). Live-WS
cancel/correction dissemination open row (03b §7.3 row 2) noted as a
Task-12 input for the netting rule's parity claim. L1–L4 grid
limitations attach per §0.1. **Nothing BLOCKING.**

**FAILURE MODES (≥3).**

1. **(a) Tick-grid artifact (R8):** as H6; mandatory spread-in-ticks
   report + ≥ 4-tick re-derivation. Dilution.
2. **(b) Adversarial manufacture — momentum ignition:** real small
   ISOs are cheap in odd-lot size (id 37 ∩ 14 co-occurs); an igniter
   prints them to bait continuation-followers, then reverses.
   Rate-limited (prints cost real money — the structural advantage
   over H6's free quote manufacture) but the failure shape is a
   **negative tail at the ignition top**. Mitigation pre-registered
   (pack-04 ledger row, still REGISTERED-UNEVALUATED): minimum
   aggregate sweep-volume floor.
3. **(c) L2-ledger bite — L6 first:** quote-rule mis-signing is
   worst in locked/crossed fast markets — burst moments; systematic
   mis-signing attenuates SFI toward noise (dilution). **L2**
   second: passive fills select continuation failures
   (trap-quadrant path).
4. Stale information: post-announcement sweeps carry no 300-s
   remainder. Dilution.

**FALSIFICATION CONDITIONS.**

- F1: RankIC(SFI, 300-s forward mid return) ≤ 0 on the
  pre-registered boundaries, or below the honest-N ceiling → dead.
  Clause: `"sweep_flow_imbalance_percentile > 0.90 boundaries show
  300 s forward-return sign agreement <= 0.50 over any rolling
  20-session window"`.
- F2 (mechanism tie): `"kyle_lambda_60s_percentile < 0.20 across
  signal-active boundaries while sweep bursts fire"` — sweeps that
  move price no more than baseline refute informed urgency.
- F3 (regime/stratum): benign-stratum sign flip → premise dead;
  ≥ 4-tick-stratum sign collapse → definition kill.
- F4 (execution validity): passive realism profile or
  `--inv12-stress` failure → **trap-quadrant** (pre-declared most
  likely exit; the passive-into-momentum fill mix is the untested
  leg).
- F5: structural boundaries (§0.1) + any Rule 611/ISO regulatory
  change declared a boundary.

**IMPLEMENTATION FEASIBILITY.** New sensor module
`sensors/impl/sweep_flow_imbalance.py` (incremental trade-window
pattern exists) + registration + factory wiring + schema-1.1 YAML.
Guard obligations: audit-prompt entry, mypy strict, DTZ, ≥ 80 %
coverage, no parity-baseline contact. The only card on this slate
requiring a new module.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: APP eligible
$1.879 B/day (03c §2); the conditioning set is 17.6 % of headline
tape volume. Passive top-of-book scale, **Sharpe-max**. Who else
watches: every TCA desk and momentum shop parses ISO flags — assume
crowded; the passive-entry residual (waiting for a pullback the
crowd chases through) is precisely the untested part. Correlated
unwind as H6. OQ-3 caveat applies.

---

## H8. ALPHA_ID (proposed): `sig_dislocation_lambda_drift_v1`

**HYPOTHESIS.** When a 300-s price dislocation is produced by
*trading with elevated price impact* — flow moving price more per
unit size than the session baseline — the dislocation is information
being incorporated (Kyle: the market maker's pricing rule steepens
when informed trading intensity rises) rather than a liquidity shock
(which reverts). **Because** the informed trader spreads execution
over time to limit impact, incorporation is incomplete at the
boundary, **which must leak into L1 as** continuation of the move
over the next 300 s — but *only* in the impact-elevated stratum;
the same dislocation with baseline λ is expected to revert (that
contrast IS the falsifier).

Conditional-distribution statement: with `micro_price_drift(300 s)`
(signed drift of the depth-weighted price over the horizon window,
factory-wired) and `kyle_lambda_60s_percentile`:
`E[mid log-return over the next H = 300 s | |drift| ≥ 0.75 × session
σ₃₀₀-scale and sign-matched, and kyle_lambda_60s_percentile ≥ 0.5,
and P(vol_breakout) < 0.7] > 0` in the dislocation direction,
magnitude κ_frozen × σ₃₀₀ ≈ **6.4 bps one-way at the APP median
session** (κ 0.19 × 33.8).

**ARCHETYPE & COUNTERPARTY (R2).** Archetype:
informed-flow-following via the *impact fingerprint* rather than the
flow itself. Structural actor: an informed institution
mid-incorporation. Structural counterparty: liquidity providers and
mean-reversion traders who fade information-driven moves as if they
were liquidity shocks — the classic Kyle transfer from
noise-trader-model MMs to informed flow; their fading losses fund
the continuation. Conservation: integrated edge ≤ aggregate
adverse-selection losses on informed dislocations — the
best-documented funded pool in microstructure. The danger is
selection in the other direction: herding/ignition moves that carry
elevated λ without information (failure mode 2).

**FAMILY & MIRAGE RISK (R3).** Family: `KYLE_INFO`.
`expected_half_life_seconds = 150`; `horizon_seconds = 300`; ratio
2.0 ✓. `l1_signature_sensors: [kyle_lambda_60s, micro_price]` —
both rule-5 KYLE primaries ✓; λ is not decoration here, it is the
conditioning discriminator. Mirage rank: **MIXED** — the dislocation
observable (`micro_price_drift`) is depth-weighted, and displayed
size is revocable (a quote-size manipulator can shade micro-price
without trading); at the 0.75σ₃₀₀ conditioning scale (≈ 25 bps on
APP) the drift is dominated by the mid path, which cannot be moved
without real trading, so the manufacturable component is bounded by
~the half-spread (≈ 5.6 bps APP) — material but minority. λ is
trade-fed, LOW. M = 1.5 conservatively.

**OBSERVABLE STATE.** All existing, all factory-wired:
`micro_price` (+ `micro_price_drift` — the signed drift-over-horizon
view; + zscore), `kyle_lambda_60s` (+ percentile), `ofi_ewma`
(diagnostic flow-agreement, NOT an entry arm — power, block 2),
`realized_vol_30s` (+ zscore, gate). **No new sensor; no
`spread_z_30d`.** The drift threshold "0.75 × session σ₃₀₀-scale" is
implemented as a fixed multiple of a causal trailing vol estimate
(Task-7 spec detail; the multiple 0.75 is frozen here).

**EXPECTED BEHAVIOR.** Continuation of the dislocation; hl 150 s.
Regime: excluded only in disorderly breakout; the λ arm does the
regime work that spread/HMM-normal gates did in earlier cards.
Sketch (long side):

```
on_condition:  "P(vol_breakout) < 0.7 and micro_price_drift_zscore > 0.75
                and kyle_lambda_60s_percentile >= 0.5
                and realized_vol_30s_zscore <= 3.0"
off_condition: "P(vol_breakout) > 0.7 or realized_vol_30s_zscore > 3.0"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.15}
```

**COST ARITHMETIC PLAUSIBILITY.** Passive: C_ow(APP) 2.08, C_ow(RMBS)
2.43 bps. Design edge: APP 0.19 × 33.8 ≈ 6.4 bps (G12 margin ≈ 3.1;
stressed-floor headroom 1.37× — the largest on the slate); RMBS
0.19 × 31.6 ≈ 6.0 bps (margin ≈ 2.5; headroom 1.10× — thin,
park-rule armed). Taker closed at design as everywhere.

### H8 · 1. FEASIBILITY CITATION (map §3/§6; κ FROZEN)

Map κ_req, passive, H = 300: APP **0.139**/0.132/0.127; RMBS
**0.173**/0.143/0.137 (med/p75/p90); CROX 0.228 med (next best).

Derived κ (factors named, FROZEN):

| factor | prior range (central) | grounding |
|---|---|---|
| `c_D` | 1.0–1.6 (**1.3**) | conditioning directly on realized \|move\| ≥ 0.75σ: E[\|z\| given \|z\| ≥ 0.75] ≈ 1.33 under near-Gaussian tails — the one factor this card fixes by construction rather than inference |
| `f_perm` | 0.45–0.75 (**0.6**) | λ-elevation conditioning selects impact-elevated windows — above the unconditional 0.55, below H7's certified 0.65 |
| `r_rem` | 0.3–0.7 (**0.5**) | uniform detection along the incorporation path |
| `f_H` | 0.6–0.85 (**0.75**) | 1 − e^(−300/216), hl 150 |
| `f_pass` | 0.5–0.8 (**0.65**) | as H6 |

    κ ∈ [0.04, 0.30 (capped)],  central ≈ 0.19 — FROZEN

**Park arithmetic, pre-stated:**

| symbol | κ_frozen·σ₃₀₀,med | floor | verdict |
|---|---|---|---|
| APP | 0.19 × 33.8 = **6.42** | 4.68 | OPEN at median (κ_req 0.139 ≤ 0.19) — 37 % headroom, best on slate |
| RMBS | 0.19 × 31.6 = **6.00** | 5.46 | OPEN at median, marginally (κ_req 0.173 vs 0.19 — 10 % κ margin; artifact flags authoritative at rounding boundaries) — **SECONDARY, park rule armed** |
| CROX | 0.19 × 24.8 = 4.71 | 5.66 | CLOSED at median and p75 (0.19 < 0.214); **excluded** |
| rest | — | — | CLOSED (κ_req ≥ 0.240) |

**Symbol set = {APP primary, RMBS secondary}.** No p90 dependence.
Short-side rider disclosure: rider-inclusive short floors APP 5.82 ⇒
κ_req 0.172 ≤ 0.19 — **APP short side clears even rider-inclusive
at the median (unique on this slate)**; RMBS short 6.60 ⇒ κ_req
0.209 > 0.19 — RMBS short side closed at median: pre-stated
consequence — RMBS restates long-only at census if the measured
short edge fails the rider-inclusive floor, and its power is then
re-checked (≈ 55, below floor ⇒ RMBS drops; APP stands).

### H8 · 2. EPISODE-DENSITY PLAUSIBILITY

Basis: 760 in-window h=300 boundaries/symbol (as H6). Conditioning
fraction assumed: P(|z| ≥ 0.75) ≈ 0.45 two-sided (near-Gaussian;
fat tails raise it) × λ-percentile ≥ 0.5 arm 0.5 ⇒ joint ≈ 0.226
(arms positively correlated in practice — the product is the
conservative independent-arms floor) × gate 0.90 × warm 0.95 ×
viable-session fraction (σ_min = floor/κ): APP 4.68/0.19 = 24.6 bps
⇒ σ₁₂₀ ≳ 15.6 ⇒ 10/10 census cells qualify (APP min 16.8) ⇒ ~1.0;
RMBS 5.46/0.19 = 28.7 ⇒ σ₁₂₀ ≳ 18.2 ⇒ 8/10 cells.

**Expected: APP ≈ 760 × 1.0 × 0.90 × 0.95 × 0.226 ≈ 147 ✓
(comfortable); RMBS ≈ 760 × 0.8 × 0.90 × 0.90 × 0.226 ≈ 111 ✓
(marginal).** The most power-robust card on the slate; the diagnostic
OFI-agreement arm is kept OUT of the entry rule precisely because
adding it (joint fraction ≈ 0.14) would push RMBS under the floor —
recorded as a drafted variant, not silently absorbed.

### H8 · 3. SENSOR WARM REALITY (census citations)

| sensor | census warm | basis |
|---|---|---|
| `realized_vol_30s_zscore` | **measured 0.94–0.995 everywhere** | gate — safe |
| `micro_price` (+drift) | unmeasured | quote-fed; warm on a short quote window — APP 1.6–3.0 quotes/s, RMBS 0.4–2.4/s (03c §5.1) keep it warm on both set symbols; census-stage verification pre-registered |
| `kyle_lambda_60s` | unmeasured; proxy `inventory_pressure` ≥ 0.985 measured | APP warm ~always (216–380 trades/60 s); **RMBS marginal** (0.78–1.8 trades/s ⇒ 47–110/60 s vs the 30 floor — quiet stretches go cold); block-2 RMBS warm multiplier 0.90 reflects this; measured coverage < 0.5 on > 2 sessions drops RMBS (coverage rule, not tuning) |
| `spread_z_30d` | 0.03–0.16 thin names | **NOT USED** |

### H8 · 4. CONTAMINATION POSTURE

Entry conditioning: `micro_price_drift` is **quote-fed** (Class-B
prints structurally absent). `kyle_lambda_60s` is trade-fed,
existing, unfiltered (DI-09) and sits in the entry rule — but at a
**median split** (percentile ≥ 0.5), not a distribution extreme;
justification for inheritance, stated per the census rule: the DI-09
contamination finding concentrates at trade-flow *extremes* (80 % of
|pressure|-tail boundaries flagged; flags dominated by id 10/id 2
prints that co-occur with extreme one-sided volume), while a median
split dilutes any single-print distortion of the OLS slope across
the 60-s window; the card's own extreme is on the quote side.
Residual risk accepted and bounded: a Class-A-filtered NEW
`kyle_lambda` variant is pre-registered as the fallback (ledger
appendix, drafted-not-evaluated, shared with H6), and the census
stage reports λ's flagged-print co-occurrence in signal-active
windows both ways before any IC exists.

**DATA REQUIREMENTS.** All sensors implemented, registered,
factory-wired (03 §5.2; `micro_price_drift` and
`kyle_lambda_60s_percentile` wired in `_HORIZON_FEATURE_FACTORIES`).
L2-loss rows: **L5** (micro-price's displayed-size weighting —
manufacturable minority component, see mirage), **L6** (λ's tick-rule
signing degrades at burst moments), **L2** (passive queue adversity),
**L4** (hidden liquidity absorbs the remainder). L1–L4 grid
limitations attach per §0.1 — with L3 flagged specifically: RMBS is
the most heavily conditioned grid subsample and is this card's
secondary symbol; per-symbol diagnostics must flag RMBS.
**Nothing BLOCKING.**

**FAILURE MODES (≥3).**

1. **(a) Tick-grid artifact (R8):** a 0.75σ dislocation on a coarse
   grid is a few ticks; grid-state persistence can masquerade as
   continuation. Mandatory spread-in-ticks report + ≥ 4-tick
   re-derivation. Dilution.
2. **(b) Adversarial manufacture / herding confound (the dominant
   risk):** ignition cascades produce dislocation + elevated λ
   (thin books make λ spike) without information — entries at the
   top of manufactured or herded moves. Failure shape: **negative
   tail**. Distributional defense: F2's reversion-contrast clause
   (baseline-λ dislocations must revert; if *everything* continues,
   the λ conditioning is doing no work and the card is an
   unpre-registered momentum hypothesis — dead by its own terms).
3. **(c) L2-ledger bite — L5 first:** quote-size shading moves
   micro-price without trades (bounded by ~half-spread; the 0.75σ
   threshold is 4–5× that on APP — bounded dilution). **L6**
   second: λ mis-signing at exactly the conditioning moments.
4. Public-news dislocations: already-impounded — elevated λ during
   the print, no remainder. Dilution; partially separated by the
   structural-boundary screen (grid avoids event days — which also
   means this confound is *under-represented* on the grid; carried
   as an L-style external-validity caveat).

**FALSIFICATION CONDITIONS.**

- F1 (forward test): continuation-signed conditional 300-s forward
  return ≤ 0 at the joint condition, or below the honest-N ceiling
  → dead. Clause: `"sign-matched
  |micro_price_drift| >= 0.75 sigma boundaries with
  kyle_lambda_60s_percentile >= 0.5 show 300 s forward-return sign
  agreement <= 0.50 over any rolling 20-session window"`.
- F2 (mechanism tie — THE card-defining contrast): the KYLE story
  requires the λ split to discriminate. Clause: `"conditional
  forward return at matched dislocation magnitude is
  indistinguishable (|Δ| ≤ 1 SE) between kyle_lambda_60s_percentile
  >= 0.5 and < 0.5 strata"` — if impact elevation adds nothing, the
  mechanism attribution is refuted regardless of pooled drift.
- F3 (regime/stratum): sign reversal across spread-in-ticks strata →
  definition kill; benign-stratum flip to reversion → premise dead.
- F4 (execution validity): passive realism / `--inv12-stress`
  failure → **trap-quadrant**.
- F5: structural boundaries (§0.1).

**IMPLEMENTATION FEASIBILITY.** **YAML-only** (+ config): every
feature already wired. The cheapest card on the slate.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: eligible
continuous dollar volume, grid-session median (03c §2): APP
$1.879 B/day, RMBS $143 M/day. Passive, top-of-book scale (APP p50
80 sh; RMBS 100-sh lots), **Sharpe-max**. Who else watches:
impact-conditioned momentum is standard institutional TCA territory;
crowding assumed high, residual argued from the 300-s scale and
passive entry (the crowd takes). Correlated unwind: shared with all
continuation traders; hazard exit + hard age 300 s load-bearing.
OQ-3 caveat applies.

---

## Constraint compliance check (slate level)

- Exactly three candidates ✓ (slate-shape justification §0 recorded,
  superseding the five-card/three-family rule for this slate).
- Families: KYLE_INFO × 3 (primary, as mandated); SCHEDULED_FLOW
  considered and excluded with count basis stated (§0 point 2);
  INVENTORY/HAWKES inadmissibility cited to the map (§0 point 1) ✓.
- Execution passive-first: all three passive-primary; taker not even
  drafted (κT_req 0.449 at H=300, map) ✓. Horizons: 300 only, inside
  the mandated {300, 900}, with the H=900 exclusion arithmetic
  recorded (§0 point 4) ✓.
- Four mandatory blocks present on every card ✓; no card needs the
  p90 tail (all median-open on their stated sets at frozen κ) ✓; one
  p90-dependent mechanism killed at design and recorded (§0.1
  pre-filter bullet + ledger) ✓.
- No load-bearing `spread_z_30d` gate anywhere; census warm coverage
  cited per sensor per card, unmeasured sensors flagged with
  pre-registered census-stage verification ✓.
- Contamination: H7's NEW trade-fed extreme-conditioned sensor
  carries Class-A + netting as explicit parameters; H6/H8 inherited
  unfiltered trade-fed sensors carry explicit justifications +
  pre-registered filtered fallbacks ✓.
- G16 arithmetic: hl 150 ∈ [60, 1800]; H = 300; ratio 2.0; ≥ 1
  rule-5 fingerprint in `l1_signature_sensors` per card ✓.
- No data examined for these candidates; no IC computed; no backtest
  run; census/map reads were characterization of committed artifacts
  only ✓.

## (1) Ranking

### (1a) Cost-floor hard pre-filter FIRST (backlog 7; map §6 — the operative gate, first application)

| card | family × H × mode × set | κ_frozen (central) | κ_req at set (median) | pre-filter |
|---|---|---|---|---|
| H6 | KYLE_INFO × 300 × passive × {APP} | 0.16 | APP 0.139 | **PASS** (median-open at own κ) |
| H7 | KYLE_INFO × 300 × passive × {APP} | 0.16 | APP 0.139 | **PASS** (median-open at own κ) |
| H8 | KYLE_INFO × 300 × passive × {APP, RMBS} | 0.19 | APP 0.139 / RMBS 0.173 | **PASS** (median-open both; RMBS margin 10 %, park-armed) |

All three enter ranking. (The micro-price-divergence level-drift
mechanism failed here at design — honest κ ≈ 0.11 vs APP p90 κ_req
0.127 — and was not carded.)

### (1b) Quality formula on survivors (S × F ÷ M, pack-04 definitions)

| # | candidate | S | F | M | S×F÷M | notes |
|---|---|---|---|---|---|---|
| H7 | `sig_sweep_kyle_drift_v2` | 5 | 3 | 1.0 | **15.0** | Exchange-certified conditioning (only certified-action observable available); new sensor costs F; power straddles the floor |
| H8 | `sig_dislocation_lambda_drift_v1` | 4 | 5 | 1.5 | **13.3** | Strongest floor headroom (37 %), only two-symbol card, only rider-clean short side, YAML-only; mirage penalty for the micro-price depth component; herding confound carried by F2 |
| H6 | `sig_ofi_kyle_drift_v1` | 4 | 4 | 1.5 | **10.7** | Best-documented mechanism but free-to-manufacture observable (quote-delta, L5) and thinnest defenses against it |

Ranking: **H7 > H8 > H6.**

## (2) Recommendation — ONE candidate

**H7, `sig_sweep_kyle_drift_v2`.** It survives the hard pre-filter
at its own frozen κ on the median session, and among survivors it
carries the strongest structural explanation available on this data:
the condition-14 flag is an exchange-stamped, irrevocable, per-print
certificate of paid-for urgency — the only conditioning variable on
the slate that is a certified action rather than an inference — and
its contamination posture is the convention working as designed
(Class-A filter + netting as explicit NEW-sensor parameters, exactly
what the census's 80 %-flagged finding demands). Its costs are named:
one new sensor module, episode power straddling the ≥ 100 floor
(park rule armed), and a passive-into-momentum fill mix that makes
F4 the pre-declared likely exit.

Stated for the review: **H8 is the robustness runner-up** — largest
stressed-floor headroom (1.37×), the only card whose short side
clears the rider-inclusive floor at the median, the only two-symbol
set, comfortable power (≈ 147 APP), and YAML-only. If Lei weighs
census-power robustness and implementation cost over mechanism
certification, overriding to H8 is defensible; the slate recommends
H7 per the formula on survivors.

## (3) TRIAL-COUNT LEDGER — appendix (append-only; N = 10 UNCHANGED)

FQ-6B-R binding rule: any data contact — including exploratory —
increments N; drafting does not; nothing is evaluated off-ledger.
Every row below is **drafted-not-evaluated (N-impact: 0)** until data
contact; any future DSR uses the then-current living N.

| N | trial | source | status |
|---|---|---|---|
| — | H6 primary: ofi_integrated(300 s) tail continuation, H=300, hl=150, passive, {APP} | H6 | drafted-not-evaluated (N-impact: 0) |
| — | H6 alt: ofi_ewma(decay_tau 60 s) z-form instead of the windowed integral | H6 | drafted-not-evaluated (N-impact: 0) |
| — | H7 primary: sweep_flow_imbalance(300 s) tail continuation, H=300, hl=150, passive, {APP} | H7 | drafted-not-evaluated (N-impact: 0) |
| — | H8 primary: dislocation(≥0.75σ) × λ(≥p50) continuation, H=300, hl=150, passive, {APP, RMBS} | H8 | drafted-not-evaluated (N-impact: 0) |
| — | H8 alt: OFI-sign-agreement as an entry arm (power-reducing; block-2 note) | H8 | drafted-not-evaluated (N-impact: 0) |
| — | H8 alt: mid-based (non-depth-weighted) drift NEW sensor replacing micro_price_drift | H8 | drafted-not-evaluated (N-impact: 0) |
| — | Shared conditional: Class-A-filtered NEW kyle_lambda variant (H6/H8 fallback) | H6/H8 | drafted-not-evaluated (N-impact: 0) |
| — | Design-killed (recorded, never cardable without redesign): micro-price-divergence level drift — honest κ ≈ 0.11 needs the p90 tail (map §6 death rule) | §0.1 | drafted-not-evaluated (N-impact: 0); dead at design |
| — | H8 §1.7 occupancy re-threshold variant (registered 2026-07-12, Task 8-C-H8, pre-authorized post-park): dislocation(≥ 0.571795 σ) × λ(≥ p50) continuation, H=300, hl=150, passive, {APP, RMBS}; κ_variant = 0.170730 via the pinned JC-10 mechanical rule; derivation disclosed in the protocol VARIANT RE-CENSUS §V.1 | H8 protocol §1.7 | census-class evaluated only (re-census PARKED on power, 2026-07-12); N-neutral — no outcome contact (N-impact: 0; first IC/forward-return contact would be +1 N) |

Carried over unchanged from the pack-04 ledger (NOT duplicated
here): H1 sweep-volume floor and H1 SFI-normalization rows
(REGISTERED-UNEVALUATED) — they attach to H7's sensor if it is
built; the 03b id-12 DW row (any trade-fed sensor, hence H7); the H2
condition-filtered `inventory_pressure` row (unrelated to this
slate's sensors, stands).

**N = 10 as of this task** — three cards drafted, zero evaluated, no
outcome statistic of any kind exists for any candidate above.

---

**Task 6-B complete. Stopping here per instruction — the slate is
AWAITING-LEI-REVIEW; an FQ-6B-style cold-read review precedes any
confirmation. Housekeeping ride-alongs landed this task:
`prompt_pack_backlog.md` entry 8 (H4 feasibility-map update) and
entry 7 (§6 operative-gate line); `prompt_pack_04_hypothesis_slate.md`
DISPOSITIONS 7 (H4 pointer, append-only).**

---

## DISPOSITIONS (Slate B final selection, 2026-07-12 — Lei; append-only, cards above unedited)

1. **H8 CONFIRMED.** `sig_dislocation_lambda_drift_v1` is the
   selected candidate for Task 7. Basis: the only card internally
   consistent at its central priors — κ_frozen 0.190; episode density
   147 (APP) / 111 (RMBS) ≥ the ≥ 100 power floor; the short side
   clears the rider-inclusive floor at the median (APP κ_req 0.172 ≤
   0.19 — unique on the slate). The slate formula's H7-first ranking
   (§1b) is **overridden** per the dossier's short-side/power finding
   (`prompt_pack_06a_slate_b_review.md` §3/§5): S×F÷M does not encode
   the short-side/power interaction that degrades H6/H7's headline
   104 to ≈ 52 at the cards' own frozen central κ.
2. **H6, H7 NOT SELECTED** — not parked; no census ran for either.
   Grounds: their central arithmetic is a pre-registered power park
   (design-central ≈ 52 < 100, short side closed at the median at
   the cards' own frozen central κ); H7 additionally rests its
   conditioning set on the legacy 7-session ISO scan (03b), not the
   frozen grid. Revival of either requires re-derivation with an
   explicit short-side posture, entered as a NEW drafted variant
   (FQ-6B-R rule: drafting is N-impact 0; the cards above stay as
   pre-registered).
3. **Concentration ACCEPTED for this cycle** (dossier §1 structural
   note / Q2): one family (KYLE_INFO), ~2 deployable symbols = the
   measured frontier of the frozen grid. Diversification path
   registered in `docs/research/prompt_pack_backlog.md` entry 11:
   universe tranche 2 (higher-σ midcaps) — future program.
4. **N unchanged at 10** — no data contact in this adjudication; no
   outcome statistic exists for any slate-B candidate.
