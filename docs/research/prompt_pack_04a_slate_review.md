<!--
  File:   docs/research/prompt_pack_04a_slate_review.md
  Status: DECIDED — final selection adjudicated by Lei 2026-07-11:
          H2 (`sig_inventory_fade_v1`) CONFIRMED for Task 7 (six binding
          spec conditions in the Task 7 amendment block); H4 parked
          (evidence-infrastructure mismatch; not refuted — future
          calendar-event grid program, backlog entry 8). Earlier
          dispositions (Task FQ-6B-R): Q1 H1 overridden/parked on the
          realized cost floor, selection narrowed to {H2, H4}; Q2 ledger
          rule (data contact increments N; drafting does not);
          Q3 L1–L4 citations routed forward (Task 7 amendment B +
          Task 8 strata), no retro-edits to the slate cards. Final
          record: `prompt_pack_04_hypothesis_slate.md` DISPOSITIONS 4–5.
  Owner:  independent slate reviewer (Task FQ-6B); no candidate selected.
-->

# Prompt-pack Task FQ-6B — Slate review dossier

Independent review of `prompt_pack_04_hypothesis_slate.md` (Task 6). Cards
were graded **before** reading §(1)–§(3) ranking/recommendation. Normative
inputs: `prompt_pack_03b_print_eligibility.md`, `prompt_pack_03c_universe_and_cache.md`
(§7 realized tick buckets; limitations L1–L4 as carried in 03c §2),
`prompt_pack_00b_edge_units_convention.md`, `prompt_pack_00e_strength_rider_and_thread.md`,
`.cursor/skills/microstructure-alpha/research-protocol.md`,
`.cursor/skills/research-workflow/SKILL.md`.

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

Universe limitations (03c §2, from frozen UNIVERSE_DECISION): **L1** single
calm episode (5 sessions); **L2** adjacent calm dates 2026-01-26/01-27; **L3**
RMBS tick-bucket prior provisional / most heavily conditioned; **L4** elevated
stratum spans two heterogeneous episodes (Nov–Dec 2025 vs Apr 2026).

---

## Per-card verdict matrix

Verdicts: **PASS** / **CONCERN** / **FAIL**. One-line evidence each.

### H1 — `sig_sweep_kyle_drift_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. FAMILY | PASS | `KYLE_INFO`; hl=180 ∈ [60,1800]; H=300 ∈ horizon set; ratio 1.67 ∈ [0.5,4]; `kyle_lambda_60s` rule-5 fingerprint present. |
| b. HYPOTHESIS FORM | PASS | Conditional on `SFI` z-score with shares and H=300 s; actor→immediacy→condition-14 L1 chain; no residual TA/folk language. |
| c. ARCHETYPE & COUNTERPARTY | PASS | Resting LP + stale uninformed LM named; urgency under-collection funds edge; not generic noise-trader boilerplate. |
| d. COST FLOOR | **FAIL** | Claimed edge 3–6 bps; realized floor **9.12 bps best (APP)** to 28.40 (DIOD) — below G12/B4-stress/Inv-12 on all eight symbols; slate priors ($400 / 0.25 bps half-spread) contradict 03c (APP med 61 ticks ≈ 5 bps half-spread). |
| e. DATA REQUIREMENTS | CONCERN | 03b §3.3 + §4.4 cited; NEW-SENSOR incremental O(1) feasible; nothing blocking — but boundary-count note ("546/7 sessions") predates 03c 80-cell / 10-session grid (stale OQ-5 artifact). |
| f. FALSIFICATION | PASS | F1–F4 dual prose + clauses; mechanism tie (F2 λ), execution trap (F3), structural splits (F4) — all observable. |
| g. REGIME & CAPACITY | CONCERN | Valid DSL; convention-eligible volume + OQ-3 caveat; **does not acknowledge L1** (requires `P(normal)` / calm information flow). |
| h. NO ANCHORING / NO PEEKING | PASS | No IC/return/outcome statistics; economics not parameterized from shipped alphas. |

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

### H3 — `sig_hawkes_parent_ride_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. FAMILY | PASS | `HAWKES_SELF_EXCITE`; hl=20 ∈ [5,60]; H=30; ratio 1.5; `hawkes_intensity` fingerprint. |
| b. HYPOTHESIS FORM | PASS | λ-ratio / α/β conditional with units (1/s, dimensionless) and H=30 s; schedule→self-excitation→prints chain. |
| c. ARCHETYPE & COUNTERPARTY | PASS | Parent-order schedule + replenishing LPs; completion constraint funds edge — substantive, not boilerplate. |
| d. COST FLOOR | **FAIL** | Taker mandatory; target 1.5–2.5 bps vs realized floor **9.12–28.40 bps** on every symbol — dead at G12 before test (slate's "borderline alive" uses prior tight-book costs, not 03c buckets). |
| e. DATA REQUIREMENTS | PASS | Existing sensors; L7 ms-timestamp parity flagged for Task 12; nothing blocking. |
| f. FALSIFICATION | PASS | F1–F4; F2 branching vs μ-jump separates self-excitation — observable. |
| g. REGIME & CAPACITY | PASS | DSL valid; eligible volume; OQ-3; disorderly-breakout gated off; no calm-episode claim requiring L1. |
| h. NO ANCHORING / NO PEEKING | CONCERN | References "shipped Hawkes alpha" for tuple wiring only (no economics) — acceptable pointer, but names a shipped alpha; no IC/returns. |

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

### H5 — `sig_flicker_inventory_fade_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. FAMILY | PASS | `INVENTORY` (not `LIQUIDITY_STRESS` entry); hl=40; H=120; ratio 3.0; `quote_replenish_asymmetry` fingerprint; LIQUIDITY_STRESS explicitly rejected. |
| b. HYPOTHESIS FORM | PASS | Joint flicker percentile + asymmetry conditional with [0,1]/[−1,1] units; MM variance penalty→quote instability chain. |
| c. ARCHETYPE & COUNTERPARTY | PASS | Constrained MM as counterparty funding concession; spoofing adversary analyzed separately in failure modes. |
| d. COST FLOOR | **FAIL** | Directional taker; target 3–5 bps vs realized floor **9.12–28.40 bps** — dead at G12 on 03c universe at stated edge. |
| e. DATA REQUIREMENTS | PASS | Quote-fed; 03b §5.1 vocabulary shift load-bearing and APP/2026-06-29 inadmissibility noted; nothing blocking. |
| f. FALSIFICATION | PASS | F1–F5 including adversarial-regime monitor (F3) and INVENTORY attribution kill (F2). |
| g. REGIME & CAPACITY | CONCERN | DSL valid; episode-scale capacity honest; OQ-3; **L1 not cited** for `P(normal) > 0.5` benign dependence. |
| h. NO ANCHORING / NO PEEKING | PASS | No IC/returns; adversarial analysis is design discipline, not peeking. |

**Task 9 NEW-SENSOR sizing note:** only **H1** requires a new sensor module
(`sweep_flow_imbalance`); H2–H5 are YAML/config-level.

---

## Slate-level findings

### i. RANKING ARITHMETIC

Recomputed from slate-stated S, F, M:

| # | S×F÷M | Stated | Match |
|---|---|---|---|
| H1 | 5×3÷1.0 = **15.0** | 15.0 | ✓ |
| H2 | 4×5÷1.5 = **13.3** | 13.3 | ✓ |
| H3 | 3×4÷1.0 = **12.0** | 12.0 | ✓ |
| H4 | 4×2÷1.0 = **8.0** | 8.0 | ✓ |
| H5 | 3×5÷2.0 = **7.5** | 7.5 | ✓ |

Ordering H1 &gt; H2 &gt; H3 &gt; H4 &gt; H5 follows from the table — **no
arithmetic error**. The formula does **not** encode check (d) cost-floor
failures; that is a separate gate.

### j. TRIAL LEDGER

- **Initialized:** yes — §(3) table with task-prefixed rows and status vocabulary.
- **N = 10:** five `pre-registered` primaries + five `design-considered` alts —
  not a five-card-only ledger.
- **CONCERN:** six **deferred-conditional** variants (H1 volume floor /
  normalization / id-12 DW; H2 filtered `inventory_pressure`; H4 MOC election /
  15:50 cutoff) are listed outside N=10 with "0-count until varied." Honest for
  *future* counting, but DSR ceiling is **understated today** if any conditional
  is built in Task 7 without incrementing N first.
- **CONCERN:** card-level failure-mode mitigations (e.g. H1 ignition floor, H3
  size-floored intensity, H5 print-confirmation variant) duplicate ledger rows
  partially but are not all uniquely keyed — risk of silent N reset at Task 7.

---

## Independent ranking vs slate ranking

### Independent ranking (pre-read, cost-aware)

Using the slate formula for S, F, M **then applying check (d) as a hard reorder
key** (FAIL on d demotes regardless of score):

1. **H2** — only taker-dead card with passive path clearing (thin) realized floor.
2. **H4** — highest target band can clear floor on APP/OLN at upper edge; F=2 reflects evidence sparsity (≈10 close windows/symbol).
3. **H1** — strongest mechanism (S=5) but **FAIL (d)** on realized spreads.
4. **H3** — **FAIL (d)**; herding confound; F3 expected binding.
5. **H5** — **FAIL (d)** + HIGH mirage; epistemic overhead dominates.

Formula-only ranking (ignoring d): **H1 &gt; H2 &gt; H3 &gt; H4 &gt; H5** — identical
to the slate.

### Slate ranking

**H1 &gt; H2 &gt; H3 &gt; H4 &gt; H5**; recommends **H1**.

### Reconciliation

- **Arithmetic agreement:** component scores and product ordering match exactly.
- **Divergence driver:** the slate ranks on structural × feasibility ÷ mirage
  **without** folding in 03c realized half-spreads. Under 00b/03c cost recomputation,
  **H1, H3, and H5 fail check (d)** at their stated edge targets on every grid
  symbol; **H1 should not hold the top slot** on honest economics even though it
  wins on mechanism narrative (S=5) and LOW mirage.
- **H2 vs H1:** slate correctly flags H2 thin passive margin but ranks H2 second;
  independent review elevates H2 to first because it is the **only** card whose
  primary execution mode survives the realized floor (marginally).
- **H4 vs H3:** slate already caps H4 at F=2 for evidence reachability; independent
  review agrees H4 beats H3 on economics (target band overlaps floor on some names)
  despite lower formula score.

---

## RISKS — slate-recommended candidate (H1)

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

---

## QUESTIONS FOR LEI

1. **H1 recommendation vs realized cost floor:** The slate recommends H1, but
   03c realized tick buckets place the G12/B4-stress/Inv-12 floor at **≥ 9.12 bps**
   (best case, APP) against a **3–6 bps** target on all eight grid symbols. Do you
   **confirm H1** anyway (mechanism-first, economics to be re-scoped in Task 7),
   or **override** in favor of a card that clears check (d) on realized spreads
   (likely H2 or upper-band H4)?

2. **Trial ledger N honesty:** Six deferred-conditional variants are documented
   outside N=10. Should Task 7 **pre-increment N** for any conditional spec
   decision (id-12 DW, normalization, ignition floors, MOC election) at authoring
   time, or is the slate's "0-count until built" rule the intended DSR policy?

3. **L1 limitation on calm-regime cards:** H1, H2, and H5 gate on `P(normal)` /
   benign strata but do not cite L1 (single calm episode, adjacent 01-26/01-27).
   Should confirm/override include a **mandatory Task 7 amendment** citing L1–L4,
   or is silent deferral to Task 8 per-window diagnostics acceptable?

---

*Reviewer stops here — no candidate selected or advanced.*

---

## DISPOSITIONS RECORD (Task FQ-6B-R, 2026-07-11 — Lei-approved)

- **Q1:** H1 **overridden**, not confirmed — parked at design on the
  realized cost floor (3–6 bps stated vs ≥9.12 bps best-case floor);
  parked ≠ trap-quadrant; no outcome data touched, N unchanged.
  Selection narrowed to **{H2, H4}**; final adjudication pending
  (`docs/research/artifacts/h2_h4_adjudication_package.md`).
- **Q2:** the six deferred conditionals are registered in the slate
  ledger as `REGISTERED-UNEVALUATED (N-impact: 0)`. Binding rule: any
  data contact — including exploratory — increments N; drafting a
  variant in the Task 7 spec does not increment; evaluating it does;
  nothing may be evaluated off-ledger.
- **Q3 (routing, recorded here per disposition):** the L1–L4 citation
  requirement for calm-regime-dependent designs is **routed forward, no
  retro-edits**: Task 7 amendment B carries verbatim L1–L4 citations
  wherever the selected design touches them, and Task 8's stratum
  definitions carry L1 (single calm episode) unconditionally. The slate
  cards stay as pre-registered.
