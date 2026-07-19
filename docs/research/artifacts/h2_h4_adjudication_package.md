<!--
  File:   docs/research/artifacts/h2_h4_adjudication_package.md
  Status: EXTRACTION — verbatim adjudication package for Lei's final
          H2-vs-H4 selection (Task FQ-6B-R, 2026-07-11). Source texts
          unedited; no new analysis except §D.2 (arithmetic behind the
          dossier's "~5 bps floor under Inv-12 stress" remark for H2).
  Owner:  research-workflow bookkeeping; prompt-pack Task FQ-6B-R.
-->

# H2 / H4 adjudication package

Sources: `docs/research/prompt_pack_04_hypothesis_slate.md` (cards,
verbatim, pre-registered 2026-07-10) and
`docs/research/prompt_pack_04a_slate_review.md` (dossier, Task FQ-6B).
Context: H1 overridden/parked per FQ-6B-R disposition Q1; selection
narrowed to {H2, H4}.

---

## A. H2 card — verbatim from the slate

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

## B. H4 card — verbatim from the slate

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

## C. Dossier verdict rows (checks a–h) — verbatim from 04a

### H2 — `sig_inventory_fade_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. FAMILY | PASS | `INVENTORY`; hl=40 ∈ [5,60]; H=120; ratio 3.0; `quote_replenish_asymmetry` fingerprint. |
| b. HYPOTHESIS FORM | PASS | Conditional on `inventory_pressure` ∈ [−1,1] with H=120 s; mandate→MM warehousing→one-sided prints; no folk/TA residue. |
| c. ARCHETYPE & COUNTERPARTY | PASS | Liquidity-provision archetype; urgency-constrained uninformed seller named with mandate binding; selection risk acknowledged. |
| d. COST FLOOR | CONCERN | Passive C_ow ≈ 2.1–2.5 bps → floor ≈ 3.2–3.75 bps vs target 3–6 bps — alive but thin; `--inv12-stress` passive adverse → C_ow ≈ 3.3 bps → floor ≈ **5.0 bps**, erasing low end of target. |
| e. DATA REQUIREMENTS | PASS | All sensors exist; inherited DI-09 auction-lump hazard documented; no NEW sensor; nothing blocking. |
| f. FALSIFICATION | PASS | F1–F5 with regime-stratum (F3) and replenishment footprint (F2) clauses — ≥3 genuine observables. |
| g. REGIME & CAPACITY | CONCERN | Benign-regime gate valid; eligible continuous volume + OQ-3; **L1 not cited** despite `P(normal) > 0.6` being load-bearing. |
| h. NO ANCHORING / NO PEEKING | PASS | No outcome stats; no shipped-alpha economics. |

### H4 — `sig_close_rebalance_drift_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. FAMILY | PASS | `SCHEDULED_FLOW`; hl=600 ∈ [60,1800]; H=900; ratio 1.5; `scheduled_flow_window` fingerprint. |
| b. HYPOTHESIS FORM | PASS | In-window `ofi_integrated` quintile claim with shares/bps; benchmark mandate→closing flow→tape signature. |
| c. ARCHETYPE & COUNTERPARTY | PASS | Argued third archetype (predictable-flow anticipation); benchmark-constrained rebalancer named with tracking-error funding. |
| d. COST FLOOR | CONCERN | Target 5–15 bps taker; floor 9.12 (APP) to 28.40 bps — **upper range only** on cheapest names; slate "comfortably plausible" overstated vs realized spreads; wide names need &gt;19 bps. |
| e. DATA REQUIREMENTS | CONCERN | Calendar YAML deliverable honest; **n ≈ 7 closing episodes stale** — 03c grid gives **10 sessions/symbol** (still ≪ acceptance bar); not blocking pre-reg, blocking Task-8 evidence density. |
| f. FALSIFICATION | PASS | F1–F5; window-bound (F2) and calendar-loading (F3) clauses are mechanism-specific and observable. |
| g. REGIME & CAPACITY | PASS | `scheduled_flow_window_active` binding; continuous-session eligible volume with auction exclusion explicit; OQ-3; L3 imbalance-feed gap in failure modes. |
| h. NO ANCHORING / NO PEEKING | PASS | No outcome stats; "benchmark" is economic actor, not shipped-alpha benchmark. |

---

## D. Realized cost floors

### D.1 Per-symbol table — verbatim from 04a (method paragraph included)

**Cost-floor method (check d).** One-way `C_ow = half_spread_bps + impact_bps +
fee_bps` per 00b; binding minimum one-way `edge_estimate_bps` is
`1.5 × C_ow` (G12, B4 at default `min_ratio=1.0` under `--inv12-stress`, and
Inv-12 cost-side stress — identical floor per 00b worked example). Half-spreads
from 03c §7 pooled median spread/tick × $0.01 and §3.1 median RTH bid (same
session). Impact: 1.0 bps when realized half-spread &lt; 8 bps, else 2.0 bps
(small within-L1 participation). Fee: commission (`max(0.0035×80, $0.35)`) +
taker exchange $0.003/sh on 80-share fill, in bps of notional. Passive cards
use 00c passive adverse 2.0 bps + fee ≈ 0.1–0.5 bps (half-spread = 0 for
maker). **Not** the slate's illustrative $400 / 0.25 bps prior.

| symbol | realized bucket | half-spread (bps) | C_ow taker (bps) | G12 / B4-stress / Inv-12 floor (bps) |
|---|---|---|---|---|
| APP | wide | 4.96 | 6.08 | **9.12** |
| OLN | discrete | 4.22 | 8.34 | **12.51** |
| CROX | moderate | 6.60 | 8.49 | **12.73** |
| MLI | wide | 7.66 | 9.22 | **13.83** |
| RMBS | wide | 10.44 | 13.14 | **19.71** |
| PCTY | wide | 10.65 | 13.18 | **19.77** |
| ENSG | wide | 13.12 | 15.52 | **23.28** |
| DIOD | wide | 15.65 | 18.93 | **28.40** |

### D.2 Stressed-floor detail behind H2's "~5 bps floor under Inv-12 stress"

H2's primary execution is passive (maker), so the taker table above does
not bind it. Components (00c §1 pins):

- half-spread: 0 (maker — resting limit, no crossing);
- fee: maker exchange $0.0; commission `max(0.0035×80, $0.35)` = $0.35 on
  an 80-share fill → ≈ 0.07 bps on APP ($615), ≈ 0.44 bps on a ~$100 name
  → fee ≈ 0.1–0.5 bps;
- adverse selection: `cost_passive_adverse_selection_bps = 2.0` (LEVEL/
  drain fill);
- unstressed passive `C_ow ≈ 2.1–2.5 bps`; **G12 floor = 1.5 × C_ow ≈
  3.2–3.75 bps** (the dossier's "alive but thin" range vs the 3–6 bps
  target).

Under `--inv12-stress`, `cost_stress_multiplier = 1.5` lands on variable
costs (00b hop 4: the edge side is never touched): stressed passive
`C_ow ≈ 1.5 × (2.0 + 0.1…0.5) ≈ 3.2–3.7 bps`. The dossier's **~5 bps**
figure is the strict Inv-12 viability reading — the 1.5× margin must
still hold at stressed costs (Inv-12: "must remain viable under 1.5×
costs"): `e ≥ 1.5 × C_ow,stressed ≈ 1.5 × 3.3 ≈ 5.0 bps`. For
comparison, the weaker 00b identity (B4 at default `min_ratio = 1.0`
under 1.5× stress ⇔ `e ≥ 1.5 × C_ow` unstressed) gives ≈ 3.3 bps.
Consequence either way: the 3–6 bps target's **low end does not survive
the stressed bar** — H2's viability rides on the realized edge landing
in the upper half of its target range and on passive-fill quality (L2
queue-composition row).

---

## E. Dossier RISKS paragraph and reconciliation text bearing on H2/H4

### RISKS — slate-recommended candidate (H1) — verbatim
*(context for the override; H1 is now parked)*

The recommendation rests on cost arithmetic "alive at G12 on tight high-priced
midcaps" and exchange-certified conditioning — but **check (d) is the weakest
link**: realized 03c spreads imply G12/B4-stress/Inv-12 floors of **≥ 9.12 bps
(one-way)** even on APP, while the card targets **3–6 bps**. The slate's tight-book
prior ($400, 0.25–1.0 bps half-spread) is inconsistent with the binding universe
(APP med 61 ticks ≈ 5 bps half-spread; no symbol in the discrete/moderate bucket
except OLN/CROX, and OLN pays a min-commission fee penalty). **Task 7 must
resolve before spec lock:** (1) re-derive edge targets from spread-conditional
strata using Task-8 measured spreads, or narrow deployable symbols to ones where
conditional spread ≪ pooled median; (2) implement `sweep_flow_imbalance` with full
03b Class-A filter + correction netting as versioned parameters; (3) treat L6
signing at sweep bursts and L4 hidden-liquidity absorption as design gates, not
afterthoughts; (4) acknowledge L1 calm-episode limitation if the regime story
remains `P(normal)`-dependent. If post-stratification edge cannot exceed
**1.5 × C_ow** under the canonical profile, the card is structurally dead
regardless of RankIC.

### Reconciliation text bearing on H2/H4 — verbatim excerpts

From the independent (cost-aware) ranking:

1. **H2** — only taker-dead card with passive path clearing (thin) realized floor.
2. **H4** — highest target band can clear floor on APP/OLN at upper edge; F=2 reflects evidence sparsity (≈10 close windows/symbol).

From the reconciliation section:

- **H2 vs H1:** slate correctly flags H2 thin passive margin but ranks H2 second;
  independent review elevates H2 to first because it is the **only** card whose
  primary execution mode survives the realized floor (marginally).
- **H4 vs H3:** slate already caps H4 at F=2 for evidence reachability; independent
  review agrees H4 beats H3 on economics (target band overlaps floor on some names)
  despite lower formula score.

---

*End of extraction. Final H2-vs-H4 adjudication is Lei's; no selection
made here.*
