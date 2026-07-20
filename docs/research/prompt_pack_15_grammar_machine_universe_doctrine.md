<!--
  File:   docs/research/prompt_pack_15_grammar_machine_universe_doctrine.md
  Status: NORMATIVE-DOCTRINE
  Owner:  research-workflow; prompt-pack Task pack-15.
-->

# Grammar × Machine → Universe: The Reverse-Engineered Selection Doctrine
**Companion to the Success Matrix (pack-14) · candidate pack-15 · Status: NORMATIVE-DOCTRINE once landed**
**Standing state unchanged: PAUSE-AND-HARVEST. This is design doctrine for a reopened round, not ignition.**

---

## §0. The inversion this document performs

Three cycles ran the causal arrow one way: pick a universe → generate hypotheses → let the machine adjudicate. The record shows the failure was never adjudication — it was that the *intersection* of (what my hypothesis grammar generates) × (what the machine can detect, afford, and prove) was nearly empty **on that universe**. This document runs the arrow backward: hold the grammar and the machine fixed, characterize each honestly, and derive the universe on which their intersection is non-empty. Universe selection becomes an engineering output, not an input assumption.

---

## §1. Audit of the hypothesis-formation grammar (what I actually generated)

Every card H1–H13 instantiated one template:

> *conditioning statistic X, computed from L1 over trailing window W, at an extreme/threshold, evaluated at a horizon boundary → E[mid log-return over the next H] has sign s; harvested by a passive single-name entry.*

Fourteen threads, one dependent variable (forward mid drift), one clock (the horizon scheduler's boundaries), one execution posture (passive at the BBO), one aggregation level (single-name time series). The families varied the *causal story* — informed flow, inventory, excitation, calendar — but never the claim shape.

**What the grammar structurally excluded, despite platform support:**

1. **Cross-sectional (PORTFOLIO-layer) claims.** The composition layer — cross-sectional ranker, factor neutralizer, sector matcher, turnover optimizer, universe cap 50 — shipped unused through the entire program. Every card fought single-name noise alone; a relative-value claim cancels common-factor variance by construction, which attacks the M-axis directly (part of the realized-IC shortfall is common noise a ranking never has to predict).
2. **Non-drift dependent variables.** Spread-state transitions and quote-behavior forecasts — the taxonomy's own *lowest-mirage* family — appeared only as gates, never as the predicted quantity. (Machinery gap in §8: the IC harness scores features against forward *mid returns* only.)
3. **Event-anchored claims.** The boundary clock makes an episode = a conditioned boundary; a strong 30-second phenomenon occurring mid-bar at H=900 is diluted or invisible. My grammar therefore drifted toward *persistent-state* conditioners — correctly, given the machine — but without ever stating that the machine had made rare-event alpha ungenerable.
4. **Exit-side and holding-period claims.** Hazard-exit machinery exists; no card hypothesized about exit quality.

**Why the grammar was this narrow:** the platform contract (Signal = direction/strength/edge_bps at boundaries; forward-IC and CPCV built for boundary drift) pulls toward it; the anchor texts' risk-premium framing pulls toward flow-drift stories; and the closed taxonomy — correctly preventing narrative drift — also quietly standardized the claim *shape*, not just the claim *discipline*. The taxonomy governs mechanisms; nothing governs (or deliberately varies) dependent variables, clocks, or aggregation levels. That is a grammar degree of freedom the program never spent.

---

## §2. The machine as a universe filter — end-to-end, each stage's implicit constraint

Walking sensors → position and extracting the numeric universe constraint each stage silently imposes:

| Stage | Mechanism fact | Implicit universe constraint |
|---|---|---|
| **Ingestion** | Consolidated L1 NBBO + prints; no depth, no venue books, no imbalance feeds | The *top of book must be where the information is*. Mega-caps hide the action in queue depth and the venue race; illiquid names have stale, uninformative BBOs. The machine wants the middle. |
| **Sensors** | Windows in event counts (spread_z: 6000 quotes; rv-z: 2000 readings) and seconds; warm gates | Quote arrival ≈ **1–5/s** (measured: APP at 1.6–3.0/s warmed everything; thin names starved at 0.03–0.16 coverage). Below the band: warm starvation. Far above: fixed-second windows become event-count-unstable. |
| **Horizon scheduler** | Boundaries fixed by H: ≈78/25/12 per session at 300/900/1800; episode = conditioned boundary | The **episode budget is a constant of H, not of the name**. Power therefore demands conditioning states that *occupy a large boundary fraction* — persistent states, not spikes. Rare-event mechanisms fail P by construction. |
| **Alpha layer** | G16 half-life envelopes; horizon/half-life ∈ [0.5, 4]; G12 load gate at 1.5× one-way cost | The name's characteristic decay time for the phenomenon must land inside a family envelope at a registered horizon. |
| **Regime/HMM** | Quote-clocked 3-state gate | Another occupancy attrition arm (measured 0.46–0.69× when unmeasured) — the universe must keep the *joint* (gate × conditioner) occupancy high, not each marginal. |
| **Sizing** | Position cap at top-of-book displayed scale (MDI share units); Sharpe-max declared | Capacity = displayed depth × price. Small-capital by design; the universe question is fee geometry, not capacity. |
| **Cost model** | Commission max(0.0035/sh, $0.35); maker fee ≈ 0; flat passive adverse-selection 2.0 bps; single-stress 2.25× | **fee_bps ≈ 43.75 / price** at the 80-share scale — the min-commission trap: $21 OLN pays 2.08 bps, $150 pays 0.29, $544 pays 0.08. Stressed passive floor ≈ 4.7–5.2 bps for P ≥ $150. The machine selects for **high-price names** (or depth allowing 120+ share clips). |
| **Passive fill model** | Seeded queue-hazard at the BBO; level fills require trades at the level; 50 ms fill latency | The BBO must *turn over actively, two-sided* — wide quiet books produce no level fills; heavily tick-constrained books produce the discreteness artifact. Sweet band: **spread/tick ≈ 2–8**. |
| **Validation** | Conjunctive IC (0.03 ∧ p ≤ 0.01) ⇒ required IC ≈ 2.576/√(n−3); CPCV annualization √(bars/session·252) ⇒ fewer bars/session demands *higher per-bar Sharpe* for the same annualized 1.0 | Long horizons are penalized twice: fewer episodes (P) *and* a higher per-boundary Sharpe requirement. The proof machinery wants **many boundaries of a moderately strong effect**, not few boundaries of anything. |

**The machine's composite preference, stated once:** a boundary-clocked detector of *persistent, frequently-occupied L1 states* on names with **1–5 quotes/s, price ≥ ~$150, spread/tick 2–8, active two-sided BBO turnover** — where the only remaining free requirement is that σ_H at the conditioned state clears **floor/κ ≈ 30–40 bps** at honest κ (0.146–0.190), or ≈ 16–18 bps only if a mechanism ever honestly supports κ near the 0.30 ceiling.

---

## §3. The shadowing hypothesis — the deepest reading of the M-gap

The program's most expensive number: mechanisms honestly priced at κ ≈ 0.15–0.19 realized IC of 0.019–0.089 — a 2–8× shortfall *after* economics and power cleared. The candidate explanations, in decreasing credibility given the record:

1. **L1 shadowing (structural).** Our conditioners are consolidated-L1 *shadows* of mechanisms that live partly in depth, venue books, hidden/reserve liquidity, and imbalance feeds (the L2-loss ledger, realized). The realized-to-designed transfer ratio is then roughly the **L1-visibility share of the mechanism** — a *property of the name*, not of the card. Supporting evidence: the certified-print conditioner (H10 — irrevocable prints, lowest mirage) realized the highest IC of the program; the quote-delta shadow conditioners realized the least.
2. **Crowding-to-zero of L1-visible edges** on names every electronic desk watches — consistent with the record, indistinguishable at our n, and equally a *name property*.
3. **Designed-κ optimism** — real but bounded: the factor derivations were literature-anchored, and F2 separated populations exactly as designed; the stories were not fictions, they were diluted.

**Doctrine consequence:** universe selection should *maximize the L1-visibility share*, using measurable, census-legal proxies — primary-venue volume share (less fragmentation shadow), displayed-to-effective spread ratio, odd-lot volume share (post-2026 dissemination caveats noted), ISO/trade-through intensity, quote-to-trade ratio (lower = less cancel-shadow). None of these were screened in the original universe. All of them can be.

---

## §4. The reverse-engineered universe spec sheet (all screens census-legal)

A future universe is *derived*, pack-13-style, with the go/no-go frozen before measurement:

| Axis served | Screen | Bar (measured basis) |
|---|---|---|
| E | Intraday σ_H at the working horizon, sampled per the pack-05 method (mids only, RTH; never daily rv20 — the pack-13 lesson) | σ₃₀₀,med ≥ 30 bps for honest-κ designs (≥ ~17 bps only under a κ ≥ 0.28 derivation surviving review) |
| E | Price / fee geometry | P ≥ $150 at top-of-book scale (fee ≤ 0.3 bps), or displayed depth supporting ≥ 120-share clips at P ≥ $60 |
| P | Boundary occupancy of the *candidate conditioner class*, measured on sample sessions (backlog-19/20: on the target geometry, never transferred) | joint (gate × conditioner) occupancy ≥ 0.15 at the working horizon, so decile/quintile tails clear the ≥130 design margin under the 0.5× unmeasured-arm budget |
| P / fills | Quote rate; two-sided BBO turnover; spread/tick | 1–5 quotes/s; spread/tick ∈ [2, 8]; level-trade rate sufficient for the hazard model to be live |
| M | L1-visibility proxies (§3) | Ranked screens; cutoffs frozen at characterization time — the program holds no priors here yet, so the first characterization *sets* them and says so |
| M (grammar-dependent) | Cohort homogeneity, if the round targets cross-sectional grammar (§5) | ≥ 20–30 names, one sector / price / liquidity band, inside the 50-name composition cap, so relative claims are well-posed |
| Integrity | Feed admissibility | inside the vendor-capped span; units-sanity and unknown-id guards green per cell |

**The honest feasibility question, asked before any spend:** does a US midcap set with σ₃₀₀ ≥ 30 bps *and* the liquidity/fee band exist at all? σ₃₀₀ ≈ 30 bps is ≈ 2.6%/day of *intraday-only* movement — high-beta, news-dense, retail-active territory — and pack-13 already proved extreme daily vol does not imply it. The satisfying set is plausibly small, partially outside the midcap band, and **time-varying**, which forces §6.

---

## §5. Grammar extensions the machine already supports (and what each demands of the universe)

1. **Cross-sectional Layer-3 (highest leverage, zero core change).** A PORTFOLIO-layer alpha ranking a homogeneous cohort converts the claim from "predict this name's drift" to "predict the *ordering*" — common-factor noise cancels, effective IC rises for the same mechanism strength, and power pools across names *natively* (the pooled structures we built by amendment become the default geometry). Demands: the cohort universe of §4; the composition layer's mechanism-share caps finally going live (the OQ-3 backlog item becomes relevant); an additive harness extension for cross-sectional IC (§8).
2. **Spread-state dependent variables (lowest mirage, one harness gap).** Predicting spread/quote-state transitions is fully sensor-observable and boundary-clocked; only the IC harness's mid-return dependent variable blocks it. Universe demand: the spread/tick 2–8 band where transitions are informative rather than grid artifacts.
3. **Exit-quality alpha.** Hazard machinery exists; a claim about *when realized edge decays* becomes testable the day any card reaches fills — currently academic, recorded for completeness.
4. **What stays out:** event-anchored evaluation (rare-event alpha) requires changing the boundary clock — a core platform change; backlogged, never assumed.

---

## §6. The rolling-universe tension, resolved by pre-registration

If the E-satisfying set is time-varying, static universe freezing — which served integrity for three cycles — becomes the thing that starves E. The resolution is not to abandon freezing but to **freeze the selection *function***: a mechanical, lagged, census-legal screen (trailing intraday σ_H percentile + the §4 band screens, evaluated on data strictly preceding each evaluation block) whose *output* is the universe, drawn and frozen per block exactly as the regime windows were drawn. Selection-on-lagged-characterization is a conditioning step like any other: registered before outcomes, mechanical in execution, occupancy-measured. The survivorship hazard (names selected *because* recently volatile then revert) is handled the way the idiosyncratic screen was: the selection variable is disclosed as a conditioner, and design σ priors are taken from *post-selection measured* distributions, never from the screen's own trailing values.

---

## §7. Composition with the reopening conditions

This doctrine sharpens pack-12's conditions rather than replacing them. A cost-frontier change (condition 1) moves the §4 σ bar down mechanically; a data-scale change (condition 2) relaxes the occupancy and n bars; and this document *is* the concrete form of condition 3 — "a new thesis with a characterization gate frozen before measurement" now reads: **grammar extension (cross-sectional and/or spread-state) × reverse-engineered universe spec × pack-13-class go/no-go**. If a round ever reopens, its first artifact is the §4 spec sheet instantiated with frozen cutoffs, and its slate prompt deliberately varies the grammar axes (dependent variable, aggregation level) that three cycles held constant — because the record says the mechanism *stories* were never the binding failure; the claim shape and the universe were.

---

## §8. Machinery gaps surfaced by this contemplation (backlog candidates, not assumptions)

| Gap | What it blocks | Class |
|---|---|---|
| IC harness scores features vs forward *mid returns* only | Spread-state dependent variables (§5.2) | Additive harness extension |
| No cross-sectional IC (rank-vs-rank) evidence path | Layer-3 grammar (§5.1) validation | Additive harness extension |
| Boundary-clocked evaluation only | Event-anchored / rare-event grammar | Core change (scheduler) — backlog only |
| Flat 2.0 bps passive adverse-selection charge | Universe-dependent execution realism (names with worse true AS are flattered) | Calibration study, once any card reaches fills |
| No L1-visibility proxies in any characterization | The §3/§4 M-axis screens | New census-legal measurement, pack-13 pattern |

---

*One-sentence version: three cycles proved the machine kills honestly; the next round — if one ever opens — should stop asking "what alpha lives on this universe" and start asking "what universe lets this machine, speaking this grammar, prove anything at all," and then measure whether that universe exists before spending a single card on it.*

binding for Campaign 2 per pack-16
