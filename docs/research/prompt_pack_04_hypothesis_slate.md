<!--
  File:   docs/research/prompt_pack_04_hypothesis_slate.md
  Status: hypothesis — five pre-registered SIGNAL-layer candidates (Task 6).
          NO data was examined in this task: no IC, no forward returns, no
          spread/vol measurement beyond facts already recorded in the data
          contract. All spread/volatility figures below are stated PRIORS,
          flagged as such, to be measured in Task 8 — they are assumptions,
          not observations. Awaiting Lei's confirm/override of the
          recommended candidate before Task 7.
  Owner:  microstructure-alpha (cards) / research-workflow (trial ledger);
          prompt-pack Task 6, Phase B.

  Provenance (FQ-3 template, Amendment B):
    git_sha: "23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f"
    worktree_clean: "no — pre-existing untracked research docs (prompt_pack_03,
      03b, conditions artifacts) and the modified backlog only; no tracked
      source file modified before this task"
    pythonhashseed: "n/a — no scripted analysis run in this task (design only)"
    normative_inputs: prompt_pack_03_data_contract.md (§1 schemas, §5 sensor
      catalog, §6 universe, §7 L2-loss ledger — mandatory input, §8 OQs),
      prompt_pack_03b_print_eligibility.md (§3.3 convention, §4.4 netting
      rule, §6 guards — Amendment A), prompt_pack_00_architecture_verification.md
      (tick path, guard inventory, OQ-3 caveat),
      prompt_pack_00b_edge_units_convention.md (one-way cost units),
      prompt_pack_00c_eval_canon.md (cost-model pins, latency pins),
      .cursor/skills/microstructure-alpha (SKILL.md G16 table,
      research-protocol.md Phases 0–5, R2/R3/R7/R8, proposal-template.md),
      .cursor/skills/research-workflow (trial ledger, status vocabulary).
-->

# Prompt-pack Task 6 — Hypothesis slate (five SIGNAL candidates)

Pre-registration document. Five candidate SIGNAL-layer alpha hypotheses for
the L1 NBBO / horizon-set {30, 120, 300, 900, 1800} s / midcap common-stock
setting, each written before any data contact (Inv-2: falsifiability before
testing). The shipped alphas and gas decisions were used only as pointers to
mechanics and conventions — no candidate's economics is derived from them,
benchmarked against them, or parameterized from them (session constraint 6).

Conventions binding on every card:

- **Cost units** are one-way (per-fill) bps of fill notional throughout
  (00b, THE CONVENTION). G12 requires `edge / (half_spread + impact + fee)
  ≥ 1.5` one-way, reconciling ±0.05 absolute.
- **Print eligibility** for any NEW trade-fed sensor follows 03b §3.3
  (Class A include / Class B exclude, id-12 DW as an explicit parameter)
  plus the §4.4 correction-netting rule (`drop correction ∈ {10,11,12}`;
  never condition on retroactive `correction ∈ {1,7,8}` — lookahead). The
  filter is an explicit, versioned sensor parameter (Amendment A).
- **Volume base** (Amendment B): every capacity sketch states its base
  explicitly. The honest base for an intraday continuous-session strategy
  is **convention-eligible continuous volume** — 74.32% of headline tape
  shares on the APP cache (03b §3.3) — because the excluded ~25% sits in
  auction crosses and summary re-prints that continuous-session execution
  cannot access. APP reference figures (03b §2): headline ≈ 5.00 M sh/day
  (35,011,640 sh / 7 sessions), eligible ≈ 3.72 M sh/day; at the ~$395
  cached print level ≈ $1.47 B/day eligible notional. APP is the **only**
  cached symbol (OQ-5) — all universe-level capacity claims are parametric.
- **L2-loss ledger** (data contract §7): each card names the rows its
  mechanism touches and inherits the modeling consequence.
- **OQ-3 caveat** (architecture doc §(e)): runtime mechanism-share
  enforcement is not active — no capacity or deployment claim below relies
  on it.
- **Volatility/spread priors** (assumption, not measurement): midcap
  annualized vol 35–50% ⇒ σ of mid log-returns ≈ 8–11 bps (30 s), 16–22
  (120 s), 25–35 (300 s), 43–61 bps (900 s), scaling √(h/23400) off a
  2.2–3.1% daily σ. Spread priors: high-priced tight name (P ≈ $400,
  penny tick): spread 1–4 ticks = 0.25–1.0 bps; low-priced wide midcap
  (P ≈ $30): spread 3–5 ¢ = 10–17 bps. Task 8 measures the real values;
  a card whose arithmetic dies under measured values dies with it.
- **Cost-model pins** used in the arithmetic (00c §1): commission
  $0.0035/sh (min $0.35), taker exchange fee $0.003/sh, maker $0.0,
  flat adverse selection 2.0 bps (passive level) / 5.0 bps (through),
  sell-side regulatory ≈ 0.5 bps, latency 20 ms visibility + 50 ms fill
  (doubled under `--inv12-stress`).

Regime-gate DSL vocabulary used below: HMM states `compression_clustering`,
`normal`, `vol_breakout` (`services/regime_engine.py`); bindings
`P(<state>)`, `<sensor_id>`, `<sensor_id>_zscore`, `<sensor_id>_percentile`.
Gates fail OFF on uncalibrated/non-discriminative posteriors (drift D8).

**Scheduled structural boundaries, pre-registered once for all cards** (R8;
data contract §4): (i) SEC Rule 612 half-penny tick regime — compliance
deferred to first business day of Nov 2027; any sample spanning it splits
hard at that date. (ii) MDI round-lot reassignments — semiannual, per
(symbol, effective date); APP's current lot is 40 sh. (iii) The vendor
quote-field population change between cached sessions 2026-06-03 and
2026-06-29 (03b §5.1) — never pool across it without the 03b §6 guard;
APP/2026-06-29 is UNKNOWN-ID-flagged and inadmissible for evidence today.

---

## H1. ALPHA_ID (proposed): `sig_sweep_kyle_drift_v1`

**HYPOTHESIS.** An institutional trader holding short-half-life information
executes with intermarket sweep orders **because** paying take fees and
through-prices across venues simultaneously is only rational when the value
of immediacy exceeds the cost of patience (urgency reveals information),
**which must leak into L1 as** clusters of condition-14 (Intermarket Sweep)
prints, one-sided when signed against the prevailing NBBO — with permanent
(not transient) impact, the KYLE signature.

Conditional-distribution statement: let `SFI(t; W)` = signed sweep-flow
imbalance, Σ(±size) over condition-14 prints in the trailing `W = 300 s`
window, sign by quote rule against the contemporaneous NBBO, in **shares**.
Claim: `E[mid log-return over the next H = 300 s | SFI z-score > +2] > 0`
(symmetric for < −2), with conditional mean ≥ ~0.1–0.2 × σ₃₀₀ (i.e. ~3–6
bps at the σ prior) and monotone in the SFI quantile.

**ARCHETYPE & COUNTERPARTY (R2).** Archetype: informed-flow-following. The
structural counterparty is the resting liquidity provider whose displayed
quotes the sweep lifts across venues: their quotes are standing commitments
repriced with finite latency, so during urgency bursts they systematically
under-collect the adverse-selection premium they normally charge — that
under-collection is the risk premium harvested. They trade against this
signal *specifically* because posting two-sided markets is their business
model; withdrawing on every sweep would forfeit the spread income that pays
for it. Secondary counterparty: uninformed liquidity-motivated flow that
keeps providing after the sweep at stale prices. Conservation check
(Phase 3 test 6, to be argued quantitatively in Task 7): the integrated
edge must be payable out of MM adverse-selection losses on sweep events —
bounded by (sweep volume × permanent impact), which the §2 prevalence
table (id 14 = 17.6% of tape volume) makes non-trivially large.

**FAMILY & MIRAGE RISK (R3).** Family: `KYLE_INFO` (permanent-impact
information mechanism). `expected_half_life_seconds = 180` (envelope
60–1800 ✓); `horizon_seconds = 300`; ratio 300/180 = 1.67 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [kyle_lambda_60s, sweep_flow_imbalance]` —
`kyle_lambda_60s` is a G16 rule-5 primary fingerprint for KYLE_INFO ✓.
Mirage rank: **LOW** — trade prints are irrevocable, and condition 14 is
an exchange-stamped attribute of an execution that actually happened, not
a revocable quote pattern. The rank does **not** settle the archetype:
prints prove the sweep occurred, not that the sweeper was informed — a
delta-hedger or an error trade sweeps identically. The archetype is argued
from the incentive (nobody pays multi-venue take fees plus through-prices
habitually and survives), and falsifier F3 tests it.

**OBSERVABLE STATE.**

- **NEW-SENSOR `sweep_flow_imbalance`** (Trade-fed). State: deque of
  `(ts_ns, signed_size)` over trailing 300 s; value = windowed signed sum
  (optionally depth- or volume-normalized — normalization choice is a
  Task-7 spec decision, one N-ledger trial if varied). Incremental-update
  feasibility: `update(event, state, params) → SensorReading | None` is
  O(1) amortized (append + expire-from-left), exactly the pattern of
  `inventory_pressure`/`ofi_raw`; no libm. Explicit parameters per
  Amendment A: `eligible_conditions` (here: prints carrying id 14, within
  the 03b Class-A universe; id 41 pass-through overlay),
  `drop_correction_records = {10, 11, 12}`, no conditioning on retroactive
  `correction ∈ {1,7,8}`. Signing by quote rule against the last NBBO —
  the same L6 inference every existing signed-flow sensor uses.
- Existing: `kyle_lambda_60s` (v2.0.0 causal lag-one; fingerprint +
  mechanism-confirmation), `spread_z_30d` (gate), `realized_vol_30s`
  (gate). Reducers: `sweep_flow_imbalance` + `zscore` and `percentile`
  views; `kyle_lambda_60s` + `percentile`.

**EXPECTED BEHAVIOR.** Sign: same direction as the sweep imbalance
(continuation). Horizon 300 s; decay ≈ exponential with hl 180 s — most
drift in the first 2–3 minutes as the parent order completes and impact
becomes permanent. Regime dependence: requires information flow — active
in `normal`, dead in `compression_clustering` (no informed activity), and
dangerous in disorderly `vol_breakout` (signing degrades). Sketch:

```
on_condition:  "P(normal) > 0.5 and sweep_flow_imbalance_zscore > 2.0
                and spread_z_30d <= 1.5"
off_condition: "P(vol_breakout) > 0.7 or spread_z_30d > 2.5
                or sweep_flow_imbalance_zscore < 0.5"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.20}
```

(Long side shown; the short side mirrors with the −2.0 threshold.)

**COST ARITHMETIC PLAUSIBILITY.** One-way, taker entry (the mechanism is
momentum-shaped — passive entry adversely selects against it):

| book prior | half_spread | impact | fee | C_ow | G12 needs edge ≥ 1.5·C_ow | vs drift target |
|---|---|---|---|---|---|---|
| tight $400 name | 0.25 bps | 0.5–1.0 | 0.3 | ≈ 1.1–1.6 bps | ≥ 1.6–2.4 bps | target 3–6 bps ⇒ margin ≈ 1.9–3.8 ✓ |
| wide $30 name | 5–8 bps | 2–4 | 2.4 | ≈ 9–14 bps | ≥ 14–21 bps | ≈ 0.5σ₃₀₀ ⇒ implausible ✗ |

Verdict: **alive at G12 on tight high-priced midcaps** (the cached
instance is one); dead on wide low-priced names — the deployable universe
is spread-conditional, and the YAML gate encodes that via `spread_z_30d`.
Not dead at G12 before test.

**DATA REQUIREMENTS** (vs data contract). `conditions` tuple verbatim on
`Trade` — met (§1.1, DI-09). 03b §3.3 convention + §4.4 netting — **met**
(cited as normative; the sensor implements them as parameters). Condition-14
prevalence 28.5% of prints / 17.6% of volume — met, ample sample (§2 of
03b). Contemporaneous NBBO for signing — met (tick path). Latency: 20 ms +
50 ms ≪ 300 s — met. L2-loss rows touched: **L6** (aggressor signing is
inference; misclassification concentrates in fast markets exactly when
sweeps cluster), **L4** (hidden midpoint liquidity can absorb sweeps),
**L3** (one sweep's visible prints under-represent multi-venue demand;
acceptable — direction, not magnitude, is consumed), **L7** (no sub-latency
claim made). Open row noted per Amendment C: live-WS cancel/correction
dissemination parity (03b §7.3 row 2) is a Task-12 input for all trade-fed
sensors; the mechanism does not otherwise depend on it (0.004% prevalence).
**Nothing BLOCKING.** (OQ-5 — single cached symbol — constrains Task-8
generality, not this card's validity.)

**FAILURE MODES** (≥3).

1. **(a) Tick-grid artifact (R8):** on a 1-tick-spread book, 300 s forward
   mid returns are coarsely quantized and the `spread_z_30d ≤ 1.5` gate
   stratum may coincide with a single grid value — apparent conditional
   drift can be grid-state persistence. Required: spread-in-ticks
   distribution report; re-derive on spread ≥ ~4 ticks or survive
   conditioning on spread-in-ticks. Failure shape: edge dilution
   (spurious component evaporates out-of-stratum).
2. **(b) Adversarial manufacture — momentum ignition:** an adversary can
   print *real* small ISOs (cheap in odd-lot size — id 37∩14 co-occurs) to
   ignite continuation-followers, then reverse into them. Unlike quote
   spoofing this costs real executions, so the pattern is rate-limited,
   but the failure shape is a **negative tail**: entries at the ignition
   top, reversal against the position. Mitigation to pre-register in
   Task 7: minimum aggregate sweep-volume floor (a parameter — one
   N-ledger trial if varied).
3. **(c) L2-ledger bite — L6 signing errors:** quote-rule misclassification
   is worst in locked/crossed and fast markets, i.e. exactly at burst
   moments; systematic mis-signing attenuates SFI toward noise. Failure
   shape: edge dilution. Second-worst: **L4** — sweeps absorbed by hidden
   midpoint liquidity produce no continuation (dilution, not tail).
4. Information already stale: sweeps triggered by public news (halted or
   post-announcement) — impact is instantaneous, no 300 s drift left at
   the 20 ms visibility floor. Dilution.

**FALSIFICATION CONDITIONS** (pre-registered; prose + G16
`failure_signature`-style clauses).

- F1 (forward test): on the pre-registered Task-8 sessions, RankIC of
  `SFI z-score` vs 300 s forward mid log-return ≤ 0, or below the
  honest-N noise ceiling `E[max Sharpe | null, N]` — hypothesis dead.
  Clause: `"sweep_flow_imbalance_zscore > 2.0 boundaries show 300 s
  forward-return sign agreement <= 0.50 over any rolling 20-session
  window"`.
- F2 (mechanism tie — permanent impact): the KYLE story requires elevated
  price-impact coefficient during sweep bursts. Clause:
  `"kyle_lambda_60s_percentile < 0.20 across signal-active boundaries
  while sweep bursts fire"` — if flow moves price no more than baseline,
  the informed-urgency premise is refuted even if drift appears.
- F3 (execution validity): conditional drift exists pre-cost but fails
  `edge ≥ 1.5 × C_ow` under the canonical realism profile (00c) or dies
  under `--inv12-stress` → status `trap-quadrant`, candidate closed.
- F4 (structural boundaries, hard splits): the three pre-registered
  boundaries above; additionally any SEC/FINRA rule change to ISO
  (Rule 611 exception) usage is a declared boundary — never pool across.

**IMPLEMENTATION FEASIBILITY.** New sensor module
`sensors/impl/sweep_flow_imbalance.py` (Sensor protocol, incremental —
pattern exists) + `SensorSpec` registration + `_HORIZON_FEATURE_FACTORIES`
wiring (`bootstrap.py` — dormant-sensor lesson, data contract §5.2) +
schema-1.1 SIGNAL YAML. Guard obligations: owning audit-prompt entry
(`tests/docs/test_prompt_coverage_map.py`), mypy strict, DTZ, ≥80%
coverage on the new module, no parity-baseline impact (new sensor not in
any locked fixture). Medium effort — the only card requiring a new module
besides its YAML.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: convention-eligible
continuous volume (APP ≈ 3.72 M sh/day ≈ $1.47 B; the sensor's own
conditioning set — id-14 prints — is ≈ 17.6% of headline tape volume).
Envelope: participation ≤ ~1% of eligible continuous volume in the 300 s
window around entry keeps within-L1 impact modeling honest (00c
`cost_within_l1_impact_factor` 0.3 regime) — on APP-scale books that is
O(10³–10⁴) sh/window, far above personal-scale sizing; capacity is not
the binding constraint, signing quality is. Target: **Sharpe-max** (small
size; the edge is per-event and impact is concave in participation —
profit-max would erode the very impact signature traded on). Who else
watches: every institutional TCA desk and momentum-HFT shop parses ISO
flags; the observable is public and cheap, so assume crowded. Correlated
unwind: momentum followers exit together on reversal — amplifies the
ignition negative tail; exit discipline (hazard exit + hard age 2×hl =
360 s) is load-bearing. OQ-3 caveat applies: no claim relies on runtime
mechanism-share enforcement.

---

## H2. ALPHA_ID (proposed): `sig_inventory_fade_v1`

**HYPOTHESIS.** An impatient uninformed seller (or their broker schedule —
redemption, hedge, deadline) demands immediacy in size **because** their
mandate prices completion above price improvement, forcing market makers to
warehouse inventory they do not want; capital- and variance-constrained MMs
concede price temporarily to shed it, **which must leak into L1 as**
one-sided inferred aggressor flow (trade prints) with *unstressed* spreads,
followed by reversion of the temporary concession.

Conditional-distribution statement: `inventory_pressure` (60 s window,
∈ [−1, 1], positive = net aggressive **selling** per the sensor's
Σ(−aggressor·size)/Σsize convention). Claim:
`E[mid log-return over the next H = 120 s | inventory_pressure ≥ +0.5
and spread_z_30d ≤ 1.0 and P(vol_breakout) < 0.3] > 0` (bounce after
absorbed selling; symmetric short case for ≤ −0.5), magnitude ~0.15–0.3 ×
σ₁₂₀ ≈ 3–6 bps at the priors — the recoverable fraction of the temporary
concession.

**ARCHETYPE & COUNTERPARTY (R2).** Archetype: **liquidity provision** — the
strategy supplies immediacy alongside (and after) the constrained MM, buying
what the impatient seller must sell. Counterparty: the urgency-constrained
uninformed trader; they trade against this signal specifically because
their constraint (mandate/deadline/redemption) binds regardless of
short-term concession — they knowingly pay the immediacy premium. Risk
premium harvested: the inventory-risk/immediacy premium. Conservation:
integrated edge is bounded by aggregate temporary-impact costs paid by
impatient flow — a well-documented, structurally funded pool; the danger is
not conservation but *selection* (informed flow contaminating the
conditioning set — failure mode 2).

**FAMILY & MIRAGE RISK (R3).** Family: `INVENTORY`.
`expected_half_life_seconds = 40` (envelope 5–60 ✓); `horizon_seconds =
120`; ratio 120/40 = 3.0 ∈ [0.5, 4.0] ✓. `l1_signature_sensors:
[quote_replenish_asymmetry, inventory_pressure]` —
`quote_replenish_asymmetry` is the INVENTORY rule-5 primary fingerprint ✓.
Mirage rank: **mixed** — the conditioning observable (`inventory_pressure`,
trade prints) is LOW-mirage; the fingerprint/confirmation observable
(`quote_replenish_asymmetry`, replenishment inference) is MEDIUM-to-HIGH
(revocable-quote family). The rank does not settle the archetype: prints
being real does not prove the flow was uninformed — the entire archetype
claim rides on the *benign-regime conditioning*, which F2 tests directly.

**OBSERVABLE STATE.** All existing, all registered in the reference
config (data contract §5.2): `inventory_pressure` (v1.0.0, Trade, ≥20
trades/60 s), `quote_replenish_asymmetry` (v1.1.0, NBBOQuote, ≥20 obs/5 s),
`spread_z_30d` (gate), `realized_vol_30s` (gate). Reducers:
`inventory_pressure` passthrough + `percentile`; `quote_replenish_asymmetry`
`last`/`mean`. **No new sensor.** Known inherited hazard (Amendment B):
`inventory_pressure` is volume-normalized and, as an *existing* DI-09
sensor, ingests the auction/summary family — 56 prints carrying ~29% of
tape volume (03b §2) — so windows overlapping the open/close crosses take
session-scale volume shocks from single events. Mitigation is at the gate
(no entries in windows abutting the auctions; Task-7 spec decision), not a
sensor change (parity). A condition-filtered NEW variant of
`inventory_pressure` is pre-registered as a fallback (one N-ledger trial
if built).

**EXPECTED BEHAVIOR.** Sign: against the aggressor flow (fade/reversion).
Horizon 120 s; decay: fast exponential, hl 40 s — the concession reverts
as MM inventory sheds; nothing left by ~3 hl. Regime dependence: **only**
in benign regimes — in `vol_breakout` one-sided flow is more likely
informed (continuation, the negative case). Sketch:

```
on_condition:  "P(normal) > 0.6 and inventory_pressure_percentile > 0.90
                and spread_z_30d <= 1.0"
off_condition: "P(vol_breakout) > 0.3 or spread_z_30d > 2.0"
hysteresis:    {posterior_margin: 0.20, percentile_margin: 0.30}
```

**COST ARITHMETIC PLAUSIBILITY.** The natural execution is **passive**
(fading flow = providing liquidity; a resting limit on the pressured side):
half_spread 0 (maker), fee ≈ 0.1 bps (commission only, maker exchange fee
$0.0), impact/adverse ≈ 2.0 bps (the platform's passive-level adverse
charge is the honest proxy) → `C_ow ≈ 2.1–2.3 bps` → G12 needs edge ≥
~3.2–3.5 bps vs target 3–6 bps: **margin ≈ 1.0–1.9 — marginal, alive but
thin**; the card lives or dies on passive-fill quality (L2 row). Taker
entry: C_ow ≈ 1.1–1.6 bps on the tight book (edge ≥ 1.6–2.4 ✓ plausible)
but crossing the spread to fade a move consumes the very concession being
harvested — taker viability is real only when the concession is deep.
Wide-book case dead as in H1. Not dead at G12; flagged **thin-margin**.

**DATA REQUIREMENTS.** All sensors exist and are registered — met.
Trade-fed state under DI-09 (no filter — existing sensors; the 03b
convention applies only to NEW sensors) — met, with the auction-lump
hazard noted above. Aggressor inference (L6) — inherited. L2-loss rows
touched: **L6** (signing; misclassification during fast one-sided tape is
the conditioning moment), **L2** (queue position — passive fills are
conditionally adverse: you are filled exactly when reversion fails;
platform models this as seeded-Bernoulli hazard, and evidence runs inherit
that model's conservatism), **L1** (MM capacity beyond the BBO is
unobservable — "inventory constraint binding" is inferred, never seen).
Live-WS correction-dissemination open row noted (Task-12; not
mechanism-critical). **Nothing BLOCKING.**

**FAILURE MODES** (≥3).

1. **(a) Tick-grid artifact (R8):** on a 1-tick book the "concession +
   reversion" can be pure bid-ask bounce on the grid — mid moves of one
   half-tick quantum that a mid-based return statistic reads as reversion.
   Required: spread-in-ticks report; re-derivation on ≥4-tick stratum.
   Failure shape: edge dilution (the artifact component pays nothing after
   costs by construction).
2. **Informed-flow contamination (the dominant risk):** if the one-sided
   flow was informed, there is no reversion — continuation against the
   position. This is where the archetype dies. Failure shape: **negative
   tail** (fading a real move loses multiples of the target edge).
   Adversarial variant: predators who detect inventory-constrained MMs
   push the same direction (predatory trading), deepening the move before
   any reversion — same tail, worse timing.
3. **(c) L2-ledger bite — L2 queue composition:** the passive-entry fill
   is adversely selected (filled when flow continues, unfilled when
   reversion is instant). If the realized fill mix under the canonical
   passive model erodes the thin margin, the card is a trap-quadrant.
   Second: **L6** — systematic mis-signing at the burst moment dilutes the
   conditioning variable itself.
4. Auction-lump distortion near open/close (inherited DI-09 exposure,
   above): `inventory_pressure` spikes from a single cross → false
   entries. Dilution; gated by session-time discipline.

**FALSIFICATION CONDITIONS.**

- F1 (forward test): bucketed conditional 120 s forward return after
  `inventory_pressure_percentile > 0.90` in the benign stratum not
  significantly > 0 (RankIC/bucket monotonicity, honest-N ceiling) → dead.
  Clause: `"inventory_pressure_percentile > 0.90 boundaries in
  P(normal) > 0.6 stratum show mean 120 s forward return <= 0 over any
  20-session window"`.
- F2 (mechanism tie — MM re-quoting footprint): the inventory story
  requires the passive side to visibly re-quote/skew during episodes.
  Clause: `"quote_replenish_asymmetry unchanged from unconditional
  baseline (|Δ| below its 30-day IQR) during inventory_pressure episodes"`
  — flow without an MM-replenishment footprint refutes the warehousing
  premise.
- F3 (regime-stratum sign stability): if the conditional return sign
  flips to continuation in the *benign* stratum (not just in vol_breakout,
  where continuation is expected and gated off) → the uninformed-flow
  premise is wrong. Clause: `"sign(conditional forward return) reverses
  across spread_z_30d terciles within the benign stratum"`.
- F4 (execution validity): pre-cost reversion exists but ≤ 1.5 × C_ow
  under the passive realism model → `trap-quadrant`.
- F5 (structural boundaries): the three pre-registered hard splits.

**IMPLEMENTATION FEASIBILITY.** **YAML-only** (+ config): all four sensors
implemented, registered, and factory-wired in the reference config. One
schema-1.1 SIGNAL YAML + `configs/bt_*.yaml`. The cheapest card on the
slate.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: convention-eligible
continuous volume (APP ≈ 3.72 M sh/day); the strategy's own flow is
passive so its footprint is bounded by fill opportunity, not impact —
capacity is set by episode frequency × per-episode size, with per-episode
size ≤ the displayed-depth scale (MDI share units, APP p50 ≈ 80 sh at the
BBO per side, data contract §2.2) — genuinely small-capital. Target:
**Sharpe-max** (size beyond top-of-book scale forfeits the passive
economics entirely). Who else watches: every electronic MM runs this
mechanism as their core book-skew logic with better (private) inventory
knowledge — the residual left for an L1 observer is the slower, deeper
concession they cannot fully absorb. Correlated unwind: when reversion
fails (informed flow), all inventory-faders exit together — the negative
tail is shared and exit crowding worsens it. OQ-3 caveat applies.

---

## H3. ALPHA_ID (proposed): `sig_hawkes_parent_ride_v1`

**HYPOTHESIS.** An execution algorithm working a large parent order splits
it into child orders **because** minimizing per-child impact under a
completion schedule is optimal (Almgren-Chriss-style scheduling), which
produces self-exciting, directionally one-sided aggressive arrivals —
**which must leak into L1 as** a Hawkes-intensity burst with high
buy/sell intensity asymmetry and elevated branching (α/β), whose remaining
children continue to push price over the next tens of seconds.

Conditional-distribution statement: with `hawkes_intensity` outputs
(λ_buy, λ_sell, ratio, α/β) over the 60 s estimation window (units: 1/s;
α/β dimensionless): `E[mid log-return over the next H = 30 s |
λ-ratio in top decile AND branching α/β elevated vs baseline] > 0`
in the burst direction (symmetric for sell bursts), magnitude ~0.15–0.25
× σ₃₀ ≈ 1.5–2.5 bps at the priors.

**ARCHETYPE & COUNTERPARTY (R2).** Archetype: informed-flow-following in
the weak sense — following *committed* (schedule-bound), not necessarily
informed, flow. Counterparty is twofold: (i) the parent order itself,
whose execution-cost budget funds the edge — riding its impact transfers
part of the impact cost it must pay anyway to whoever holds inventory in
its direction; the parent trades "against" the signal because its
completion schedule binds (it keeps buying after we buy); (ii) liquidity
providers replenishing at prices that have not yet impounded the remaining
schedule. Conservation: integrated edge ≤ aggregate temporary+permanent
impact paid by scheduled parent orders — large and structurally funded;
the edge is a *slice of institutional implementation shortfall*.

**FAMILY & MIRAGE RISK (R3).** Family: `HAWKES_SELF_EXCITE`.
`expected_half_life_seconds = 20` (envelope 5–60 ✓); `horizon_seconds =
30`; ratio 30/20 = 1.5 ∈ [0.5, 4.0] ✓. `l1_signature_sensors:
[hawkes_intensity]` — the family's rule-5 primary fingerprint ✓ (plus
`trade_through_rate` as family-related confirmation). Mirage rank: **LOW**
— trade prints only, irrevocable. The rank does not settle the archetype:
clustering being real does not prove a schedule-bound parent — news-driven
herding produces the same prints with different (already-impounded)
economics; F2's branching test separates self-excitation from a common
exogenous shock, which is exactly the archetype boundary.

**OBSERVABLE STATE.** All existing: `hawkes_intensity` (v1.2.0, Trade,
warm ≥10/side in 60 s; tuple output — λ_buy, λ_sell, ratio, α/β),
`trade_through_rate` (confirmation: burst prints at/through NBBO),
`spread_z_30d`, `realized_vol_30s` (gate). Both registered in the
reference config; the shipped Hawkes alpha demonstrates the feature wiring
for the tuple components exists (mechanics pointer only — no economics
inherited). Confirm exact `feature_id`s of the ratio and α/β components at
Task-7 spec time; if a component lacks a factory entry, the addition is
config/bootstrap-level, not a new sensor. Existing-sensor DI-09 exposure:
intensity is **count-based**, so the auction volume lumps are single
arrival events (minor), but late/out-of-sequence prints (ids 13/32,
~0.005% of prints) corrupt inter-arrival times at negligible rate — noted,
not material on the 03b prevalence table.

**EXPECTED BEHAVIOR.** Sign: continuation in the burst direction. Horizon
30 s; decay: the fastest on the slate — hl 20 s; the edge is gone when the
parent completes or the market impounds the schedule. Latency check: 20 ms
visibility + 50 ms fill = 70 ms ≈ 0.35% of hl — no latency-edge claim
(L7 respected). Regime: needs orderly two-sided books for signing; dead in
`compression_clustering` (no bursts), gated off in disorderly breakout.

```
on_condition:  "P(normal) > 0.5 and hawkes_intensity_ratio_percentile > 0.90
                and spread_z_30d <= 1.5"
off_condition: "P(vol_breakout) > 0.7 or spread_z_30d > 2.5"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.25}
```

(`hawkes_intensity_ratio_percentile` = percentile view of the ratio
component; exact feature id fixed at Task-7.)

**COST ARITHMETIC PLAUSIBILITY.** Taker entry mandatory (30 s horizon;
passive entry misses the burst). Tight $400 book: C_ow ≈ 1.1–1.6 bps →
G12 needs ≥ 1.6–2.4 bps vs target 1.5–2.5 bps: **margin ≈ 0.9–1.6 —
borderline; alive only at the top of the target range and only on
tight books.** Wide book: C_ow ≈ 9–14 bps vs σ₃₀ ≈ 8–11 bps — dead
before test. Round trip inside ~60 s doubles fee/spread exposure per unit
time; `--inv12-stress` (1.5× cost, 2× latency) is the natural killer.
Honest verdict: **thinnest arithmetic on the slate — viable only on
high-priced tight names, and F3 will likely be the binding test.** Not
dead at G12 a priori, but closest to the floor.

**DATA REQUIREMENTS.** All met: sensors implemented/registered; prints
verbatim (DI-09); 03b convention cited for context (existing sensors keep
DI-09 behavior; a filtered NEW intensity variant is the pre-registered
fallback, one N-ledger trial if built). L2-loss rows touched: **L6**
(side-split of λ_buy/λ_sell rests on signing inference — burst moments are
the worst case), **L7** (ms-resolution live timestamps produce tie-heavy
inter-arrival data live vs ns in replay — the §1.2 asymmetry lands
directly on a point-process sensor; flagged for Task 12), **L4** (hidden
liquidity absorbs bursts → no continuation). Live-WS correction row noted
(Task-12). **Nothing BLOCKING.**

**FAILURE MODES** (≥3).

1. **(a) Tick-grid artifact (R8):** 30 s continuation on a 1-tick book is
   sub-quantum — measured "drift" collapses onto grid transitions, and
   burst states may coincide with single spread-grid values. Required
   test as in H1/H2. Failure shape: edge dilution.
2. **(b) Adversarial manufacture — cheap ignition (applicable and
   serious):** eligible prints include odd lots (id 37, ~74% of prints);
   a manufacturer can shape a genuine-looking intensity burst with
   O(10³–10⁴) dollars of 40-share child prints, trigger
   continuation-followers, and reverse. Prints cost real money (unlike
   quotes) but odd-lot economics make this the cheapest print-based
   manufacture on the slate. Failure shape: **negative tail**. Mitigation
   to pre-register: volume-weighted or size-floored intensity variant
   (one N-ledger trial).
3. **(c) L2-ledger bite — L6 then L7:** mis-signed bursts (L6) invert the
   direction estimate at exactly the highest-λ moments — dilution with
   occasional tail; live ms-timestamp ties (L7/§1.2) flatten measured
   inter-arrival structure live vs backtest — a backtest/live parity risk
   specific to point-process state, flagged for Task 12.
4. Exogenous-shock confound: news bursts are Poisson-rate jumps, not
   self-excited cascades; entering on them buys already-impounded
   information. Dilution. (F2 separates.)

**FALSIFICATION CONDITIONS.**

- F1 (forward test): conditional 30 s forward return at top-decile
  λ-ratio boundaries ≤ 0 or below the honest-N ceiling → dead. Clause:
  `"top-decile hawkes ratio boundaries show 30 s forward-return sign
  agreement <= 0.50 over any rolling 20-session window"`.
- F2 (mechanism tie — self-excitation, not rate shift): the schedule
  story requires elevated branching. Clause: `"hawkes alpha/beta at
  signal-active boundaries statistically indistinguishable from the
  unconditional session baseline"` — a pure baseline-intensity (μ) jump
  with flat branching refutes the parent-order premise.
- F3 (execution validity): survives pre-cost but not `edge ≥ 1.5 × C_ow`
  under the canonical profile, or dies under `--inv12-stress` →
  `trap-quadrant`. (Pre-declared as the most likely exit for this card.)
- F4 (structural boundaries): the three pre-registered hard splits; plus
  any exchange fee-schedule change altering odd-lot economics is declared
  a boundary (it changes the manufacture cost of failure mode 2).

**IMPLEMENTATION FEASIBILITY.** YAML + possibly one config-level feature
wiring line (tuple-component factory). No new sensor module. Cheap.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: convention-eligible
continuous volume (APP ≈ 3.72 M sh/day). The tradable event set is
burst-windows only — capacity = burst frequency × per-burst size, with
per-burst size capped well inside displayed depth (p50 ≈ 80 sh/side on
APP) to keep taker impact within the disclosed `impact_bps`; this is a
strictly small-capital, **Sharpe-max** target (profit-max sizing would
front-load impact and destroy the thin margin). Who else watches:
intensity/burst-following is the most standard HFT momentum construction
in existence — assume maximal crowding; the residual for a 70 ms-latency
observer is whatever the sub-ms crowd leaves at 30 s scale, which is
precisely why F3 is expected to bind. Correlated unwind: burst-followers
unwind together on reversal — shared negative tail. OQ-3 caveat applies.

---

## H4. ALPHA_ID (proposed): `sig_close_rebalance_drift_v1`

**HYPOTHESIS.** Index funds, ETF APs, and MOC-benchmarked institutions
concentrate rebalancing executions into the final ~30 minutes **because**
their benchmark is the official closing price and tracking-error
minimization dominates price improvement, **which must leak into L1 as**
persistent one-sided continuous-tape flow inside the scheduled closing
window that predicts continued drift into the close (the flow is
predictable in timing, inelastic in price).

Conditional-distribution statement: inside the MOC/closing calendar window
(`scheduled_flow_window` active): `E[mid log-return over the next
H = 900 s | ofi_integrated (900 s) in its top quintile of the session] > 0`
(symmetric bottom quintile short), magnitude ~0.1–0.3 × σ₉₀₀ ≈ 5–15 bps at
the priors. Units: `ofi_integrated` in shares (L1 OFI sum), return bps.

**ARCHETYPE & COUNTERPARTY (R2).** Archetype: **argued third case —
predictable-flow anticipation.** Not liquidity provision (we consume
liquidity in the flow direction) and not informed-flow-following (the flow
carries no information about value; it is mechanical). The structural
counterparty is the benchmark-constrained rebalancer: they trade against
this signal specifically because their mandate fixes *when* and *how much*
they trade, not at what price — their tracking-error tolerance funds the
anticipation premium. Secondary counterparty: closing-auction liquidity
suppliers who fade intraday drift into the cross. Conservation: integrated
edge bounded by the implementation shortfall of close-benchmarked flow —
structurally funded, but heavily shared (see crowding).

**FAMILY & MIRAGE RISK (R3).** Family: `SCHEDULED_FLOW`.
`expected_half_life_seconds = 600` (envelope 60–1800 ✓);
`horizon_seconds = 900`; ratio 900/600 = 1.5 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [scheduled_flow_window]` — the family's rule-5
primary (and only) fingerprint ✓; direction observables `ofi_ewma` /
`ofi_raw`(`sum` reducer → `ofi_integrated`). Mirage rank: **LOW-to-MEDIUM**
— the window is calendar fact (zero mirage); the direction proxy is L1 OFI
(quote-delta family, MEDIUM: conflates cancels/replenishment with trades —
L5). Rank does not settle the archetype: a real one-sided tape in the
window could still be informed flow timed to exploit closing liquidity —
F3 (calendar-loading test) separates mechanical rebalancing from
opportunistic timing.

**OBSERVABLE STATE.** All existing: `scheduled_flow_window` (v1.2.0,
calendar-injected; warm requires a symbol-eligible window — misconfig
surfaces as cold, `sensors/impl/scheduled_flow_window.py`),
`ofi_raw`+`sum` → `ofi_integrated` (wired), `ofi_ewma`, `spread_z_30d`.
Gate note: the window sensor's value is a 4-tuple (active, s-to-close,
window-id-hash, direction-prior); the gate needs the `active` component
exposed as a scalar binding — the platform's MOC machinery consumes this
sensor already, so the wiring pattern exists; exact feature id fixed at
Task-7 (config-level if missing). **No new sensor.**

**EXPECTED BEHAVIOR.** Sign: direction of in-window integrated flow.
Horizon 900 s; decay: hl 600 s — drift accumulates toward 16:00 and the
mechanism *terminates at the close* (hard structural end, not exponential
tail); positions must be flat or MOC-converted by the cutoff (15:50 ET,
BT-8). Regime: robust to vol state (mechanical flow) but requires orderly
books for the OFI proxy.

```
on_condition:  "scheduled_flow_window_active > 0.5
                and ofi_integrated_percentile > 0.80
                and spread_z_30d <= 2.0"
off_condition: "scheduled_flow_window_active < 0.5
                or ofi_integrated_percentile < 0.60"
hysteresis:    {percentile_margin: 0.10}
```

**COST ARITHMETIC PLAUSIBILITY.** The strongest on the slate: target 5–15
bps at 900 s. Taker entry, tight book: C_ow ≈ 1.1–1.6 bps → margin
≈ 3–9 ✓. Even the wide-book case (C_ow ≈ 9–14 bps) is not automatically
dead at the top of the target range, though it is not the deployable
case. Exit into the close is the cheap direction (liquidity concentrates
there); MOC conversion (fill at close mid, `moc_strategy_ids`) is
available machinery if elected — an election that is a Task-7 spec
decision, one N-ledger trial if varied. **Comfortably plausible at G12.**

**DATA REQUIREMENTS.** `scheduled_flow_window` implemented + registered —
met; **calendar content**: the sensor warms only if the session calendar
YAML (`event_calendar_path`, set in the reference config) contains a
closing window for the traded symbol/universe — a **config artifact that
must be authored for each evidence session** (deterministic, from exchange
schedule; direction_prior neutral). Not BLOCKING (creatable without data
peeking) but a named Task-7/8 deliverable. **Statistical-power constraint,
stated honestly:** one closing window per session × 7 usable cached
sessions = **n ≈ 7 independent episodes** on the current cache (OQ-5) —
far below any acceptance bar; this card cannot reach evidence without
scheduled ingestion of more sessions. NOT blocking for pre-registration;
BLOCKING for Task-8 evidence on the current cache. L2-loss rows touched:
**L5** (OFI conflates cancels and trades — direction proxy noise), **L6**
(any signed-print alternative inherits signing), **L3** (closing-cross
liquidity and imbalance-feed information are venue data we structurally
lack: NYSE/Nasdaq imbalance dissemination from 15:50 is *not* in the L1
NBBO feed — participants who see it are better-informed in exactly our
window), **L4** (hidden liquidity into the close). Also inherits the 03b
§2 note: the auction prints themselves are Class-B/summary volume —
invisible to continuous-tape sensors until after the close, which is
consistent with the mechanism (we trade the *continuous-session shadow*
of the rebalance, not the cross).

**FAILURE MODES** (≥3).

1. **(a) Tick-grid artifact (R8):** spreads widen and the grid coarsens
   relative behavior into the close; any spread-conditioned stratum needs
   the spread-in-ticks re-derivation. Failure shape: dilution.
2. **Imbalance-feed information asymmetry (the dominant risk):** from
   15:50 ET, auction-imbalance subscribers see the true imbalance we can
   only infer; when the disseminated imbalance contradicts the tape
   proxy, informed flow trades against us with better information.
   Failure shape: **negative tail concentrated in the last 10 minutes**.
   Mitigation: entry cutoff before dissemination (a parameter; one
   N-ledger trial if varied).
3. **(b) Adversarial/crowding:** the effect is the most-documented
   calendar anomaly in equities; anticipators-of-anticipators enter
   earlier, moving the drift before the window and leaving latecomers the
   reversal. Manufacture in the strict sense is minor (the calendar can't
   be faked); the adversarial shape is **edge dilution with occasional
   crowded-unwind tails** when the anticipated imbalance flips at 15:50.
4. **(c) L2-ledger bite — L5:** cancel-driven OFI in thinning pre-close
   books mimics directional flow with no rebalancer behind it — false
   direction, dilution. Second: **L3** (the real liquidity event — the
   cross — is invisible until it prints).

**FALSIFICATION CONDITIONS.**

- F1 (forward test): in-window conditional drift at top/bottom-quintile
  `ofi_integrated` not significantly different from matched out-window
  baseline (same time-of-day-adjusted σ, honest-N ceiling) → dead.
  Clause: `"in-window top-quintile ofi_integrated boundaries show 900 s
  forward-return sign agreement <= 0.50 over the accumulated evidence
  set"`.
- F2 (mechanism tie — window binding): the SCHEDULED_FLOW story requires
  the effect to be *window-bound*. Clause: `"conditional drift of equal
  or larger magnitude at matched ofi_integrated quantiles outside
  scheduled windows"` — an unconditional OFI-momentum effect refutes the
  scheduled-flow attribution (it would be a different, unpre-registered
  hypothesis).
- F3 (mechanism tie — calendar loading): rebalancing flow concentrates on
  month-end/quarter-end/index-event sessions. Clause: `"per-session
  in-window effect size uncorrelated with the session's calendar loading
  (month-end/index-event flag) over the accumulated evidence set"` —
  uniform presence across ordinary days refutes the rebalancer actor.
- F4 (execution validity): drift exists but ≤ 1.5 × C_ow under the
  realism profile including the pre-close spread regime → `trap-quadrant`.
- F5 (structural boundaries): the three pre-registered hard splits; plus
  any exchange change to closing-auction/imbalance-dissemination
  mechanics (e.g. dissemination start time) is a declared boundary.

**IMPLEMENTATION FEASIBILITY.** YAML + per-session calendar config
(+ possibly one feature-wiring line for the `active` scalar). No new
sensor. Cheap in code; expensive in **data** — needs ingestion of
additional sessions before any evidence claim (OQ-5).

**CAPACITY & CROWDING SKETCH (R7).** Volume base, stated per Amendment B
with emphasis because this card sits next to the auctions: the strategy
trades the **continuous session**, so its base is convention-eligible
continuous volume in the 15:30–16:00 band (a session-fraction of APP's
≈ 3.72 M sh/day eligible; the headline-vs-eligible gap is *largest* here
because the excluded 25% — the cross volume itself, ~29% of tape shares in
56 prints — prints exactly at this boundary and is not accessible to
continuous execution). Capacity: the deepest of the slate — pre-close
liquidity is the day's densest; participation ≤ 1% of in-window eligible
volume leaves room above personal scale. Target: **profit-max within the
window is tempting but crowding argues Sharpe-max** — declared:
Sharpe-max. Who else watches: everyone — close-anticipation is
industrial-scale (index desks, ETF APs, closing-liquidity HFTs, TCA-driven
algos); assume the thinnest *residual* edge per unit of flow on the slate,
surviving (if at all) because the funding flow is also the largest.
Correlated unwind: an imbalance flip at 15:50 unwinds the entire
anticipation crowd simultaneously into a closing book — the tail is
shared, fast, and terminal (no next window to recover in). OQ-3 caveat
applies.

---

## H5. ALPHA_ID (proposed): `sig_flicker_inventory_fade_v1`
### (the slate's single high-mirage quote-flow candidate — full adversarial-manufacture analysis included)

**HYPOTHESIS.** A market maker near an inventory or uncertainty limit
rapidly cancels and reprices one side of the book **because** their
marginal cost of adverse selection on the constrained side has spiked
(inventory-skewed quoting is optimal under a variance penalty), **which
must leak into L1 as** an elevated best-price reversal fraction
(`quote_flicker_rate`) concurrent with one-sided replenishment weakness
(`quote_replenish_asymmetry`) — quote instability preceding a price
concession toward the weak side.

Conditional-distribution statement:
`E[mid log-return over the next H = 120 s | quote_flicker_rate_percentile
> 0.90 AND quote_replenish_asymmetry ≤ −0.5 (ask side replenishing
weakly)] < 0` — drift *toward* the weak side (price falls when the ask is
abandoned is the mirrored case; sign convention fixed to the sensor's
bid-vs-ask definition at Task-7); magnitude ~0.15–0.25 × σ₁₂₀ ≈ 3–5 bps.
Units: flicker rate ∈ [0,1] (fraction of direction-reversing quote
updates over the 5 s estimation window), asymmetry ∈ [−1,1].

**ARCHETYPE & COUNTERPARTY (R2).** Archetype: informed-flow-following in
the *inferential* sense — following the MM's private inventory state as
revealed by their own quoting behavior (the MM knows their book; we read
their stress). Counterparty: the constrained MM themselves, who concedes
price to shed inventory — their variance penalty funds the edge; they
"trade against" the signal because posting the concession *is* their
optimal action once constrained — they pay to exit risk, and the strategy
is paid to absorb the concession direction early. Conservation: bounded by
aggregate MM inventory-management costs — real but small per episode; this
is a low-capacity harvest by construction.

**FAMILY & MIRAGE RISK (R3).** Family: `INVENTORY` — the causal force is
inventory-constrained MM repricing (LIQUIDITY_STRESS is the *composite
alarm* family and is exit-only by G16; this card's mechanism is the MM
inventory economics, not a stress-level threshold — and its entry
legality therefore rides on the INVENTORY attribution being genuine,
which F2 tests). `expected_half_life_seconds = 40` (envelope 5–60 ✓);
`horizon_seconds = 120`; ratio 3.0 ∈ [0.5, 4.0] ✓. `l1_signature_sensors:
[quote_replenish_asymmetry]` (rule-5 INVENTORY fingerprint ✓), with
`quote_flicker_rate` as the conditioning observable. Mirage rank: **HIGH**
— both observables are in the revocable-quote family (`quote_flicker_rate`
explicitly named HIGH in R3). Why the rank does not settle the archetype:
high mirage says the *observables* can be manufactured or hidden-book-
distorted; it does not say the inventory mechanism is absent — genuine MM
stress and manufactured flicker are distributionally overlapping, which is
exactly why the confirmation falsifier (F2, trade-print follow-through)
and the adversarial analysis below carry the card's weight.

**OBSERVABLE STATE.** All existing, all registered: `quote_flicker_rate`
(v1.0.0, NBBOQuote, warm ≥20 in 5 s), `quote_replenish_asymmetry`
(v1.1.0), `inventory_pressure` (confirmation), `spread_z_30d`,
`realized_vol_30s` (gates). Reducers: `percentile` views on flicker and
asymmetry; passthrough on `inventory_pressure`. **No new sensor.**

**EXPECTED BEHAVIOR.** Sign: toward the weak (abandoned) side. Horizon
120 s, hl 40 s; decay fast — once the MM has shed inventory or repriced,
the signature vanishes. Regime: benign-to-moderate only; in
`vol_breakout` flicker is ambient and uninformative.

```
on_condition:  "P(normal) > 0.5 and quote_flicker_rate_percentile > 0.90
                and quote_replenish_asymmetry < -0.5
                and spread_z_30d <= 1.5"
off_condition: "P(vol_breakout) > 0.5 or spread_z_30d > 2.5
                or quote_flicker_rate_percentile < 0.60"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.25}
```

**COST ARITHMETIC PLAUSIBILITY.** Entry is directional *with* the coming
concession — taker on the weak side (hitting the side about to fade is
cheap only if timed before the move). Tight book: C_ow ≈ 1.1–1.6 bps vs
target 3–5 bps → margin ≈ 1.9–4.5 ✓ plausible. Wide book: dead as
before. The real cost risk is not the G12 block but adverse timing: the
weak-side quote may step away between signal and fill (50 ms fill
latency) — realized half-spread worse than disclosed. Plausible at G12;
execution-timing risk flagged for the realism profile to price.

**DATA REQUIREMENTS.** Sensors met. Quote `conditions`/`indicators`
semantics: per 03b §5, all interpreted observed ids are benign (no
non-firm quotes in cache), and quote-condition-based filtering must be
presence-tolerant. **Open row noted per Amendment C (mechanism-relevant
here):** the 2026-06-29 vendor vocabulary shift (03b §5.1, cause unknown —
Task-8 concern) directly touches this card's input family — quote-fed
state is where id-vocabulary drift lands; the 03b §6 unknown-id guard is
therefore *load-bearing* for this candidate specifically, and
APP/2026-06-29 is inadmissible. L2-loss rows touched: **L5** (cancel
attribution — the core observable is precisely the unattributable one:
flicker conflates MM repricing, spoofing, and venue churn per event),
**L2** (queue), **L4** (hidden/reserve liquidity behind a "weak" display
falsifies the weakness). **Nothing BLOCKING.**

**FAILURE MODES** (≥3, with the complete adversarial-manufacture analysis
required for the slate's high-mirage slot).

1. **(a) Tick-grid artifact (R8), acute here:** `quote_flicker_rate` is
   *definitionally* a grid observable — "direction-reversing quote
   updates" on a 1-tick spread book are oscillations between adjacent
   grid states; flicker "states" can be pure grid dynamics. The R8 test
   (spread-in-ticks distribution; re-derivation on ≥4-tick stratum) is
   mandatory before any interpretation. Failure shape: edge dilution.
2. **(b) Adversarial manufacture — the complete analysis:**
   - *Who can manufacture:* any DMA participant. Quotes are revocable and
     cancels are free — manufacturing flicker + one-sided replenishment
     weakness costs approximately nothing (vs H3's ignition, which burns
     real executions). On a midcap's thin quote traffic, a single actor
     can move the 90th flicker percentile with trivial message rates.
   - *The manufactured shape:* layer and rapidly cancel the ask
     (produces flicker + weak-ask asymmetry), induce fade-entries short,
     then flip: pull the layer, lift the ask, run the shorts in. The
     manufactured pattern is **per-event indistinguishable** from genuine
     MM stress because of L5 (no order ids, no cancel attribution) — only
     distributional defenses exist.
   - *Failure shape:* **negative tail, adversarially timed** — worse than
     symmetric noise because entries are induced precisely when the
     adversary is positioned against them. This is the defining risk of
     the card, and it is the reason the slate carries at most one
     quote-flow candidate.
   - *Distributional defense (pre-registered monitor):* genuine
     inventory-shedding must eventually print — flicker episodes should
     be followed within ~60 s by elevated one-sided trade prints
     (`inventory_pressure` confirmation). A rising fraction of
     signal-fires *without* print follow-through is the adversarial
     regime signature → kill-switch condition. Adding print-confirmation
     as an entry *requirement* (not just monitor) is a pre-registered
     variant (one N-ledger trial).
   - *Economic bound on the adversary:* manufacture is free but flipping
     into induced entries requires the adversary to trade — their
     capacity to harvest is bounded by our size; at Sharpe-max personal
     scale the bait is barely worth setting, which is a genuine (if
     unflattering) structural defense.
3. **(c) L2-ledger bite — L5 first:** flicker conflates cancel-driven and
   trade-driven quote churn per event; venue-migration churn (L3) also
   reads as flicker. Dilution. **L4** second: a "weak" displayed ask
   backed by hidden reserve absorbs the expected concession — no drift.
4. Warm-window fragility: both quote sensors warm on 5 s windows (≥20
   obs) — on quiet midcap tape they cycle warm/cold, gating entries
   erratically (operational dilution, visible in warm-rate telemetry).

**FALSIFICATION CONDITIONS.**

- F1 (forward test): conditional 120 s forward return at the joint
  condition not < 0 (for the weak-ask case; mirrored long) or below the
  honest-N ceiling → dead. Clause: `"joint flicker>p90 &
  replenish_asymmetry<-0.5 boundaries show forward drift toward the weak
  side <= 0 over any 20-session window"`.
- F2 (mechanism tie — real-flow confirmation): genuine inventory
  shedding prints. Clause: `"no elevation of |inventory_pressure| within
  60 s of signal-active windows vs matched baseline"` — flicker without
  subsequent one-sided prints refutes the MM-inventory attribution (and
  simultaneously flags the adversarial regime). This clause doubles as
  the INVENTORY-vs-LIQUIDITY_STRESS attribution test: if it fails, the
  card has no legal entry family and dies structurally, not just
  statistically.
- F3 (adversarial-regime monitor, pre-registered as a kill condition):
  Clause: `"fraction of signal fires lacking print follow-through rises
  above 2x its evidence-period baseline over any 10-session window"` →
  quarantine-grade condition even if aggregate PnL is flat (the tail is
  latent).
- F4 (execution validity): pre-cost edge ≤ 1.5 × C_ow under the realism
  profile (including weak-side step-away between signal and 50 ms fill)
  → `trap-quadrant`.
- F5 (structural boundaries): the three pre-registered hard splits — the
  2026-06 vendor-vocabulary boundary binds hardest here (quote-fed
  inputs); APP/2026-06-29 inadmissible until id 34 is interpreted.

**IMPLEMENTATION FEASIBILITY.** YAML-only. All sensors registered and
factory-wired. Cheapest implementation, highest epistemic overhead.

**CAPACITY & CROWDING SKETCH (R7).** Volume base: convention-eligible
continuous volume (APP ≈ 3.72 M sh/day) — though the binding constraint
is episode capacity, not volume: flicker states are fleeting and the
harvestable concession is a few bps on top-of-book-scale size (APP p50
≈ 80 sh/side). Strictly **Sharpe-max**, smallest capacity on the slate.
Who else watches: HFT MMs monitor their own (and competitors') quote
stability internally with order-level data we lack; exchange surveillance
watches the same patterns for spoofing — the observable is crowded on
both the harvesting and the policing side. Correlated unwind: small
absolute size, but adversarially correlated (failure mode 2's flip is
*by construction* simultaneous with our exit need). OQ-3 caveat applies.

---

## Constraint compliance check (slate level)

- Exactly five candidates ✓. Families: KYLE_INFO (H1), INVENTORY (H2,
  H5), HAWKES_SELF_EXCITE (H3), SCHEDULED_FLOW (H4) — four families ≥ 3 ✓.
  No LIQUIDITY_STRESS entry ✓. No FAMILY-EXTENSION proposal needed —
  every mechanism fits the closed taxonomy (H4's "argued third case" is
  an *archetype* argument, not a family extension).
- Low-mirage lean: H1, H2, H3 lean on trade prints (LOW) ✓ (≥1 required).
- High-mirage quote-flow (`quote_flicker_rate`/`quote_hazard_rate`): H5
  only ✓ (≤1), with the complete adversarial-manufacture analysis ✓.
- G16 arithmetic: every card's half-life is inside its family envelope,
  horizon ∈ {30,120,300,900,1800}, ratio ∈ [0.5,4.0], and ≥1 rule-5
  fingerprint sensor in `l1_signature_sensors` ✓ (verified per card).
- Amendment A: trade-fed cards (H1; H2/H3 context) cite 03b §3.3 + §4.4
  as met; H1's NEW sensor declares the condition filter as an explicit
  parameter ✓. Amendment B: every capacity sketch states its volume base
  (convention-eligible continuous volume) ✓. Amendment C: the 06-29
  vocabulary row is noted only on H5 (mechanism-dependent); the live-WS
  correction row is noted as a Task-12 input on the trade-fed cards ✓.
- No data examined; no IC computed; no backtest run ✓.

---

## (1) Ranking — structural strength × feasibility ÷ mirage risk

Scores: S = structural-explanation strength (1–5: is the causal force
named, incentive-grounded, counterparty-funded, and confirmable by an
in-family observable?); F = implementation feasibility (1–5: artifacts
needed AND evidence reachability on the current cache — a card that
cannot reach evidence without new data ingestion is capped); M = mirage
divisor (LOW = 1.0, MIXED = 1.5, HIGH = 2.0 per R3 ranks of the
*load-bearing* observables).

| # | candidate | S | F | M | S × F ÷ M | notes |
|---|---|---|---|---|---|---|
| H1 | `sig_sweep_kyle_drift_v1` | 5 | 3 | 1.0 | **15.0** | Exchange-certified urgency flag; new sensor costs F; 546 boundaries/7 sessions at 300 s — evidence-reachable |
| H2 | `sig_inventory_fade_v1` | 4 | 5 | 1.5 | **13.3** | Canonical mechanism, YAML-only; thin passive margin; mixed mirage (replenish fingerprint) |
| H3 | `sig_hawkes_parent_ride_v1` | 3 | 4 | 1.0 | **12.0** | Real mechanism but archetype weakly separated from herding; thinnest cost margin; odd-lot ignition cheap |
| H4 | `sig_close_rebalance_drift_v1` | 4 | 2 | 1.0 | **8.0** | Best cost arithmetic, BUT n ≈ 7 episodes on current cache → evidence-unreachable without new ingestion (F capped) + maximal crowding |
| H5 | `sig_flicker_inventory_fade_v1` | 3 | 5 | 2.0 | **7.5** | Cheapest to build; adversarially manufacturable core observable; carried as the slate's calibrated high-mirage probe |

Ranking: **H1 > H2 > H3 > H4 > H5.**

## (2) Recommendation — ONE candidate

**H1, `sig_sweep_kyle_drift_v1`.** It has the strongest structural
explanation on the slate — the condition-14 flag is an exchange-stamped,
irrevocable, per-print record of paid-for urgency, making it the only
candidate whose conditioning variable is a *certified action* rather than
an inference — and it is the only card that puts the newly issued
print-eligibility convention (03b) to work as a first-class mechanism
input rather than a hygiene filter. Its cost arithmetic clears G12 with
real margin on the tight-book universe, its 300 s horizon yields adequate
boundary counts on the existing 6-admissible-session cache, and the one
mitigating cost — a new sensor module — is the well-trodden incremental
trade-window pattern with no parity-baseline contact.

## (3) TRIAL-COUNT LEDGER — initialized (append-only from here)

Rule (R4, research-workflow): every construction, parameter, or filter
variant considered anywhere in this workflow is one trial toward the
living N — including design-stage variants never evaluated on data.
Status vocabulary for rows: `pre-registered` (primary card),
`design-considered` (named alternative, not data-evaluated),
`deferred-conditional` (becomes a trial only when varied/built —
pre-declared here so its later appearance is not a silent reset).

| N | trial | source | status |
|---|---|---|---|
| 1 | H1 primary: windowed-sum sweep imbalance, W = 300 s, H = 300 s, hl = 180 s | H1 | pre-registered |
| 2 | H1 alt: EWMA sweep flow (τ ≈ 120 s) instead of windowed sum | H1 | design-considered |
| 3 | H2 primary: inventory_pressure(60 s) fade, H = 120 s, hl = 40 s, passive entry | H2 | pre-registered |
| 4 | H2 alt: H = 30 s variant | H2 | design-considered (rejected at design stage — cost floor) |
| 5 | H3 primary: λ-ratio burst continuation, H = 30 s, hl = 20 s | H3 | pre-registered |
| 6 | H3 alt: size-floored / volume-weighted intensity (anti-ignition) | H3 | design-considered |
| 7 | H4 primary: MOC-window tape-flow drift, H = 900 s, hl = 600 s, proxy = ofi_integrated | H4 | pre-registered |
| 8 | H4 alt: direction proxy = inventory_pressure sign instead of ofi_integrated | H4 | design-considered |
| 9 | H5 primary: flicker × replenish-asymmetry fade, H = 120 s, hl = 40 s | H5 | pre-registered |
| 10 | H5 alt: trade-print confirmation as entry requirement (not just monitor) | H5 | design-considered |
| — | H1 conditional: minimum aggregate sweep-volume floor (anti-ignition) | H1 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |
| — | H1 conditional: SFI normalization choice (depth-/volume-normalized) | H1 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |
| — | Conditional: 03b id-12 (Form T) DW weight, any trade-fed sensor | 03b §3.3 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |
| — | H2 conditional: condition-filtered `inventory_pressure` NEW variant | H2 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |
| — | H4 conditional: MOC-conversion election | H4 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |
| — | H4 conditional: entry cutoff before 15:50 imbalance dissemination | H4 | REGISTERED-UNEVALUATED (N-impact: 0) — FQ-6B-R |

**N = 10** as of this task. Pre-declared conditional rows (0-count today,
each becomes +1 when actually varied/built): H1 sweep-volume floor; H1
normalization choice; the 03b id-12 DW weight (any trade-fed sensor); H2
condition-filtered `inventory_pressure` NEW variant; H4 MOC-conversion
election; H4 entry-cutoff-before-15:50 parameter. Any DSR computed
downstream uses the then-current ledger N (`build_dsr_evidence(
trials_count=N)`), and every quoted Sharpe carries its noise ceiling
`expected_max_sharpe(n_trials=N, …)`.

---

**Task 6 complete. Stopping here per instruction — awaiting Lei's
confirmation or override of the H1 recommendation before Task 7.**

---

## DISPOSITIONS (Task FQ-6B-R, 2026-07-11 — approved by Lei; append-only, cards above unedited)

1. **Q1 — H1 OVERRIDDEN, not confirmed.** H1 (`sig_sweep_kyle_drift_v1`)
   status = "hypothesis — parked (fails the realized cost floor at design:
   stated 3–6 bps one-way vs a ≥9.12 bps best-case floor on the frozen
   universe; the G12 load-time gate is unreachable as specified)".
   Explicitly: **parked ≠ trap-quadrant** — that status is reserved for
   post-validation execution failure (statistically valid, execution-invalid
   on evidence); H1 was parked on design-time arithmetic. **No outcome data
   was touched in reaching this decision — trial count N unchanged (N = 10).**
   Selection is narrowed to **{H2, H4}**; final adjudication by Lei pending
   (package: `docs/research/artifacts/h2_h4_adjudication_package.md`).
2. **Q2 — Ledger registration rule (binding).** The six deferred
   conditionals are entered in the ledger table above as
   `REGISTERED-UNEVALUATED (N-impact: 0)`. Binding rule from here on:
   **ANY data contact — including exploratory — increments N; drafting a
   variant in the Task 7 spec does not increment; evaluating it does;
   nothing may be evaluated off-ledger.**
3. **Q3 — No retro-edits.** The L1–L4 citation requirement for
   calm-regime-dependent designs is routed forward (Task 7 amendment B;
   Task 8 stratum definitions) — recorded in the dossier
   (`prompt_pack_04a_slate_review.md`); the slate cards stay as
   pre-registered.
4. **FINAL SELECTION (Lei's adjudication, 2026-07-11) — H2 CONFIRMED.**
   H2 (`sig_inventory_fade_v1`) is the selected candidate for Task 7,
   subject to six binding spec conditions recorded in the Task 7
   amendment block. Adjudication basis: passive floor clearable
   upper-band on ~7/8 symbols vs H4's 1–3 at top-of-band; episode
   density on the frozen grid; H4's F3 falsifier untestable on an
   event-screened grid; simulator dependence measurable via Task 12 +
   sensitivity grid, information asymmetry not curable.
5. **H4 parked.** H4 (`sig_close_rebalance_drift_v1`) status =
   "hypothesis — parked (evidence-infrastructure mismatch: ~10
   episodes/symbol on the frozen grid; F3 calendar-loading falsifier
   untestable on a grid screened away from event days; economics
   top-of-band on <=3 symbols). Not refuted — candidate for a future
   dedicated calendar-event grid program." That program is registered
   in `docs/research/prompt_pack_backlog.md` (entry 8). Adjudication
   touched no outcome data: N unchanged at 10.
