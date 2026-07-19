<!--
  File:   docs/research/prompt_pack_07_program_retrospective.md
  Status: AWAITING-LEI-REVIEW — program retrospective for alpha program
          cycle 1 (slates A+B: H1–H5, H6–H8). Task 7-R, 2026-07-15.
          Synthesis of committed record ONLY: no code, no data contact,
          no outcome statistic computed or quoted beyond what the cited
          closure records already carry. Every claim cites its
          document/commit; where the record is silent the entry says
          UNKNOWN. Item-4 recomputes are hand arithmetic on committed
          boundary counts and public grid facts (census-legal).
  Owner:  research-workflow (program bookkeeping); prompt-pack Task 7-R,
          Phase B.

  Provenance (FQ-3 template):
    git_sha: "3b039f3040d56b51527b706ea8b267ed85a9728d" (HEAD at task
      start = the H8 close-out commit; this file plus the item-7
      backlog appends are the only outputs)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (synthesis + hand arithmetic recorded inline)"
    normative_inputs: prompt_pack_00_architecture_verification.md,
      prompt_pack_00e_strength_rider_and_thread.md,
      prompt_pack_02a_skill_changelog.md, prompt_pack_03_data_contract.md,
      prompt_pack_03b_print_eligibility.md,
      prompt_pack_03c_universe_and_cache.md (+ AMENDMENT 1),
      prompt_pack_04_hypothesis_slate.md (+ DISPOSITIONS),
      prompt_pack_04a_slate_review.md,
      prompt_pack_05_horizon_feasibility_map.md,
      prompt_pack_06_hypothesis_slate_b.md (+ DISPOSITIONS),
      prompt_pack_06a_slate_b_review.md,
      sig_inventory_fade_v1_{formal_spec,validation_protocol,result}.md,
      sig_dislocation_lambda_drift_v1_{formal_spec,validation_protocol,
      impl_plan,result}.md, prompt_pack_12p_router_fill_timing_parity.md,
      prompt_pack_backlog.md, artifacts/h2_h4_adjudication_package.md,
      artifacts/universe_draw_expansion_evidence_2026-07-13.md.
-->

# Task 7-R — Program retrospective: alpha program cycle 1 (slates A+B)

Scope: the full committed record of cycle 1 — slate A (H1–H5,
pre-registered 2026-07-10), slate B (H6–H8, pre-registered 2026-07-11),
two executed validation sequences (`sig_inventory_fade_v1` parked at
protocol step 1; `sig_dislocation_lambda_drift_v1` rejected at protocol
step 2b), the feasibility map, the census artifacts, and the Phase-A
machinery that adjudicated them. Trial ledger at close: **N = 11**
(§9). Zero candidates survive cycle 1.

---

## 1. PROGRAM FUNNEL

Every card from both slates. "N" = multiple-testing increments consumed
by that card's kill (FQ-6B-R rule: data contact increments, drafting
does not). Cost figures are approximate and cite their commit anchors;
slate/dossier commits shared across cards are marked (shared).

| card | gate reached | verdict (date) | deciding arithmetic / statistic | approx. cost to kill | N | what this kill taught that prior kills had not |
|---|---|---|---|---|---|---|
| H1 `sig_sweep_kyle_drift_v1` | design review (dossier check d) | PARKED at design (2026-07-11; pack-04 DISPOSITIONS 1) | stated taker edge 3–6 bps vs realized G12/B4/Inv-12 floor **≥ 9.12 bps best-case (APP)** to 28.40 (DIOD) on all 8 grid symbols (04a cost-floor table) | shared slate/dossier commits (`c65d71b`, `4253dbc`, `f4cd256`); ~1 review day; no card-specific artifact | 0 | ranking formulas measure explanation quality, not economic viability — the realized cost floor must be a hard pre-filter BEFORE ranking (backlog 7) |
| H2 `sig_inventory_fade_v1` | protocol step 1 (park-rule census) | PARKED on census (2026-07-11; `642d12d`, close-out `12afd8d`) | viable σ-region empty as realized: **1/70** floored cells σ-viable, its single episode contamination-flagged → viable-excluded = 0; power floor ≥ 100 unreachable, grid max **35** (RMBS) even ungated; robust to the §11.1 correction (protocol C.5) | 5 commits (`f2c71f1`, `6a3ac12`, `f2055d5`, `642d12d`, `12afd8d`); ~1–2 working days; 80-cell grid replayed census-class | 0 | per-card design-time floor arithmetic is insufficient — a pre-registered σ-conditional region can be **empty as realized**; slates need the measured feasibility map as pre-filter (backlog 7 extension). Side lessons: `spread_z_30d` warm starvation (backlog 9), DI-09 contamination-at-extremes (backlog 10) |
| H3 `sig_hawkes_parent_ride_v1` | design review | NOT SELECTED (2026-07-11; FQ-6B-R Q1 narrowed selection to {H2, H4}) | dossier check d **FAIL**: target 1.5–2.5 bps vs floors 9.12–28.40 bps — dead at G12 before test (04a) | shared slate/dossier commits only | 0 | (subsumed by H1's lesson — same gate, thinner arithmetic) |
| H4 `sig_close_rebalance_drift_v1` | final selection adjudication | PARKED (2026-07-11; pack-04 DISPOSITIONS 5; deprioritized 2026-07-11 per map) | evidence-infrastructure mismatch: ~10 closing episodes/symbol on the frozen grid ≪ any bar; F3 calendar-loading falsifier untestable on an event-screened grid; economics top-of-band on ≤ 3 symbols (`artifacts/h2_h4_adjudication_package.md`); map later showed taker closed at H=900 median (backlog 8 update) | shared adjudication commits (`4253dbc`, `f4cd256`) | 0 | statistical power is its own kill axis, distinct from economics — and a falsifier's **testability depends on grid construction** (a grid screened away from event days cannot test a calendar-loading claim) |
| H5 `sig_flicker_inventory_fade_v1` | design review | NOT SELECTED (2026-07-11; FQ-6B-R Q1) | dossier check d **FAIL**: target 3–5 bps vs floors 9.12–28.40 bps; HIGH mirage divisor carried (04a) | shared slate/dossier commits only | 0 | (subsumed by H1's lesson; the high-mirage slot never reached its adversarial-manufacture test) |
| H6 `sig_ofi_kyle_drift_v1` | slate-B cold-read review | NOT SELECTED at design (2026-07-12; pack-06 DISPOSITIONS 2 — not parked, no census ran) | own rider arithmetic closes the short side at central κ 0.16 (rider-inclusive κ_req 0.172) → design-central long-only ≈ **52 < 100** power floor, despite the 104 headline (06a §2 H6 d/e, §3) | slate + dossier commits (`a0881cf`, `5acdcd7` shared); ~1 review day | 0 | headline episode counts must be **design-consistent at the card's own frozen central κ** — the short-side rider × power interaction is invisible to the S×F÷M formula and was caught only by the cold read |
| H7 `sig_sweep_kyle_drift_v2` | slate-B cold-read review | NOT SELECTED at design (2026-07-12; pack-06 DISPOSITIONS 2) | identical 104→≈52 design-central power case at derived κ 0.158, plus the conditioning set rested on the legacy 7-session ISO scan, not the frozen grid (06a §2 H7 d/e, §5) | shared slate/dossier commits | 0 | (extends H6's lesson: prevalence facts feeding a card must come from the operative grid, not a legacy characterization) |
| H8 `sig_dislocation_lambda_drift_v1` | **protocol step 2b** (RankIC gate) — after: census PARK on power (primary 68/30, `fb225ae`), §1.7 variant PARK (76/22, same commit), one-shot grid expansion (`696c618`, `07bbb4b`, `a17e118`, `288cea7`) → PROCEED D={APP} at 135 episodes (E.4), A-2 rulings (`487c351`), implementation Tasks 9–10 (`d643be7`, `8cf091b`…`edb4a3b`), CPCV fixture (`8e6f94d`), step 2a PASS 7/7 | **REJECTED** (2026-07-14; S.8, close-out `3b039f3`) | pooled primary λ-elevated RankIC **+0.0186 < 0.03**, Fisher-z p **0.548 > 0.01**, conditional tail t **1.41 < 2**, A-2.1 APP safeguard p **0.433 > 0.05** — basis-independent across all three contamination bases (S.4). λ-contrast mechanism tie PASSED (baseline reverts −5.4 bps, t −2.5) — the rejection is the elevated-λ continuation claim at H=300 passive on this universe, not the λ-separation phenomenon | ~21 commits (`d9e4c69` → `3b039f3`), 3 calendar days (07-12 → 07-14), +20 ingested grid cells ({APP, RMBS} × 10 expansion dates), 2 census executions + 1 variant re-census + 1 expanded census, 8 implementation commits, 1 evidence run | **+1** | even with the full feasibility chain satisfied — economics viable (1.37× headroom), power cleared after expansion (135 ≥ 100, n = 1,231 ≥ 1,000) — the realized **effect-magnitude regime** of this universe at H=300 sits below the honest magnitude bar; the bar is n-invariant, so this is not curable by more data (S.8 item 3). A mechanism tie can pass while its tradable claim fails |

**The funnel fact, explicit:** three distinct kill gates fired across
the cycle — **design economics** (H1/H3/H5 on the realized cost floor;
H6/H7 on design-central power at the cards' own κ), **census power**
(H2 at step 1; H8 twice on the 10-session grid before the expansion
lifted it), and the **statistical bar with economics viable** (H8 at
step 2b). The kill chain was traversed end to end: every stage of the
funnel — pre-filter, census, statistics — rejected at least one
candidate on its own pre-registered criterion, and no candidate died
twice on the same class of evidence.

---

## 2. MACHINERY AUDIT

### 2.1 Instruments that earned their keep (specific catch cited)

| instrument | the catch |
|---|---|
| Cost-floor pre-filter (dossier check d → map §6 operative gate) | Killed H1 at design: 3–6 bps stated vs ≥ 9.12 bps realized floor (04a); as the map-§6 operative rule it then killed the micro-price-divergence level-drift mechanism at slate-B design (honest κ ≈ 0.11 vs APP/300 p90 κ_req 0.127 — pack-06 §0.1) and forced the passive-only, {APP}-anchored shape of slate B |
| Park-rule census | Fired **three times**: H2 step 1 (1/70 σ-viable, max 35 episodes — `642d12d`); H8 primary (viable-region APP 68 / RMBS-long-only 30 < 100 — protocol C.5); H8 §1.7 variant (76/22 — V.3). Each time before a single IC number existed |
| Frozen-κ ratchet (§1.7 occupancy variant, JC-10 mechanical rule) | Structurally prevented occupancy fishing: lowering m to 0.571795 raised raw occupancy (APP primary 73 → 99) but the mechanical κ_variant = 0.170730 raised the viability floors, shrinking the viable region (APP loses its densest cell) — net power 68 → 76, identical PARK (V.3). It demonstrated, on the record, that threshold relaxation cannot buy power on this grid — which is what justified the grid expansion instead of another threshold (V.4, A-1) |
| Single-stress anchor reconciliation (8-F, H2 protocol §11.1) | Caught the spec-§15(ii) floor substitution stacking the sensitivity-grid AS vertex (4.0 bps) on top of the Inv-12 1.5× stress inside the census floor — σ thresholds ≈ 57–67 bps corrected to ≈ 29.1–38.8 bps **before** census execution; the H2 verdict was later shown robust to it either way (C.5) |
| 00e strength rider (D-1) | The rider's own pre-registered test (ii) (returned Signal must carry non-negative **finite** edge) caught the NaN leak through the EV gate in the H8 spec §6.2 normative draft (`nan < floor_bps` is False) at commit 1 — recorded as spec §16 row 8 with four deterministic NaN goldens (`8dfe366`), provably count-neutral vs the census predicate |
| Cold-read review dossiers | 04a caught the H1 cost failure the slate's own ranking missed; 06a caught the slate-B short-side/power finding (104 headline → ≈ 52 design-central) that reversed the slate's H7-first recommendation to H8 (Lei override, 06a DECISION RECORD) |
| Census-consistency smoke (`3cd8974`) | Verified rather than caught: APP 2026-01-15 predicate count reproduced the census including-flagged number **13/13** through the alpha's own gate machinery, emissions a strict subset (impl record §8.3 item 4) — the implemented card was provably the censused object, which is what made the step-2b statistic attributable to the hypothesis rather than to wiring |
| Router fill-timing parity battery (Task 12-P, `8c69d49`) | AXIS-1 VERIFIED with 18 permanent regression guards; pinned the O-1 wrong-basis cancel fee (full original qty, inert on the canonical profile) rather than silently passing it; discharged the P0-6 precondition steps 7–8 would have required |
| Pre-registered verdict mappings | §1.5's honesty disclosure stated the H8 census power outcome was arithmetically pre-determined (APP 81 / RMBS 77 < 100) **before execution**; A-1.3 fixed the expanded-census verdict mapping (PROCEED D={APP} vs PARK-PERMANENT-CLOSE) before any expanded-cell statistic existed — E.4 then applied it with zero discretion |

### 2.2 Misses — instruments that fired late, ambiguously, or in conflict

1. **§9-vs-A-2.1 consequence conflict (precedence undefined
   pre-outcome) — the cycle's canonical miss.** At step 2b, two
   pre-registered consequence rows fired simultaneously: §9 row
   "2b IC gate" → REJECTED (terminal) and the A-2.1 APP-safeguard →
   PARK (evidence-infrastructure, revivable). The frozen record
   contained no precedence rule for their intersection; S.5 could only
   record both, and the status class had to be adjudicated
   **post-outcome** (S.8) — exactly the discretion pre-registration
   exists to remove. The S.8 construction (a safeguard tightens a pass,
   cannot loosen a primary fail; §9 freeze seniority; the magnitude bar
   is n-invariant) is sound, but it was written after the numbers
   existed. Routed to item 7(b).
2. **Evidence-set wording that needed a mid-flight ruling (E.6 /
   JC-3).** The frozen §2.2 wording "pooled over D" collided with the
   two-axis design the moment D shrank to {APP}: the frozen JC-3
   consequence would have parked a card whose mechanism evidence
   existed (1,231 pooled boundaries) because a *different symbol's
   economics* failed. A-2.1 resolved it pre-outcome (RMBS
   evidence-only pooling + APP-alone safeguard), but the ruling was
   needed at all because the freeze conflated the axes its own
   preamble said were separate.
3. **Grid-amendment constant governance (E.5 / A-2.2).** The A-1
   expansion pre-registration did not state which frozen census-derived
   constants (the §4.1/JC-4 spread-tercile cutpoints) survive a grid
   amendment; the expanded census had to disclose both sets return-free
   and stop for a Lei ruling. Cheap this time (RMBS was out of D), a
   real hazard in general.
4. **The slate ranking formula (S×F÷M) is a two-time repeat
   offender.** Pack-04: ranked H1 first while its cost arithmetic was
   dead (corrected by 04a + Q1 override). Slate B: ranked H7 first
   while its own rider table closed its short side at central κ
   (corrected by 06a + override to H8). Both times the formula measured
   narrative quality and could not see an economics interaction; both
   times the cold read caught it. The formula fired wrong twice and
   never fired right on a contested call.
5. **Design occupancy priors fired late.** H8's block-2 near-Gaussian
   occupancy (P(|z| ≥ 0.75) ≈ 0.453, joint 0.226) was checked against
   reality only at census execution — realized 0.343 / 0.107, "the
   entire power shortfall" (C.5, C.6 occupancy curve). A census-legal
   occupancy read existed conceptually before card selection (the same
   read §1.7 later used) but was not part of the slate pre-filter; the
   map measured σ only (map caveat 4 said so). Routed to item 7(d).
6. **Minor wording repairs mid-flight:** spec §16 row 4 ("session
   baseline" prose vs the wired trailing-300 s Hazen percentile —
   resolved at spec time as a deviation row, correctly); the 03c
   `worktree_clean` definition needed a clarifying commit (`2ce506f`).
   Neither cost evidence integrity; both cost a ruling.

---

## 3. PROCESS-EFFICIENCY QUESTION (analysis only — no decision)

**The fact pattern.** H8 consumed Tasks 9–10 — 8 implementation
commits (`8cf091b`, `8dfe366`, `9ed87ee`, `ddc9be1`, `41c9f0e`,
`477ce55`, `3cd8974`, `2a2458c`) plus two record commits (`8d1d85c`,
`edb4a3b`) and the CPCV fixture (`8e6f94d`) — before dying at step 2b.
Materially: the binding step-2b statistic was produced by **standalone
instrument scripts** (`scripts/research/dislocation_lambda_validation_extract.py`
/ `_stats.py`) that import the pinned census instrument
(`scripts/research/dislocation_lambda_census.py`) for every constant
and predicate — **not by the alpha YAML**. The implemented card
contributed step 2a (sign-goldens through the real pipeline) and the
census-consistency smoke, but the RankIC gate itself never executed
the YAML. An implementation-independent step 2 is therefore
*technically* possible: the census-pinned predicate plus a
forward-return extraction is everything 2b consumed.

**Ordering A (current): implement, then step 2.**

- *Integrity properties.* (i) Step 2a precedes 2b, so a 2b failure is
  attributable to the hypothesis, not to wiring — the gas-01 lesson
  ("single-tape results are indicative only") institutionalized; H8's
  2a passed 7/7 first, which is precisely why the 2b FAIL is clean
  evidence. (ii) The census-consistency smoke proves the tested object
  IS the deployable object before any statistic exists (13/13 +
  emissions-subset). (iii) Implementation-stage scrutiny surfaces spec
  defects before outcome contact — D-1 (the NaN leak) was found at
  commit 1, pre-outcome, and logged as a deviation row; found *after*
  an IC pass it would have been an awkward post-outcome correction to
  the tested predicate.
- *Cost.* 8 commits of YAML, tests, config, and harness work are
  sunk before the cheapest remaining kill gate runs. On H8 that was
  ~2 working days of the 3-day Tasks 9–11 arc.

**Ordering B (proposed): harness-level IC gate before YAML/test
investment.**

- *Shape.* After census PROCEED, run 2b on the census-pinned predicate
  via the extraction/stats instruments (which already exist as a
  pattern); invest in YAML, sign-goldens, config, causality tests,
  parity guard only on a 2b PASS.
- *Savings.* H8 would have died ~8 commits and ~2 tasks earlier. The
  same holds for any future card whose step 2 fails.
- *Integrity costs, named.* (i) **The 2a/2b inversion**: without
  sign-goldens first, a wrong-sign or mis-wired extraction can kill
  (or pass) a card on plumbing — the harness would need its own
  synthetic-tape sign-golden equivalent *for the extraction path*
  before its verdict is trustworthy; that is new machinery, not free.
  (ii) **Two-object drift**: the harness predicate becomes the tested
  object, and the later YAML must be proven equivalent. The
  census-consistency smoke already does exactly this proof
  (predicate-count reproduction + emissions-subset), so the tooling
  exists — but it currently *depends on the implemented card*, so
  under ordering B it runs after the IC verdict, converting it from a
  pre-evidence anchor into a post-hoc reconciliation. If the smoke then
  found a discrepancy, the already-scored 2b statistic would be about
  a predicate that is not the card — requiring either a re-run
  (a second outcome contact on the same trial — accounting is
  resolvable, the primary trial is one row, but the optics and the
  tuning-surface are worse) or a rejection of the implementation.
  (iii) **Sign-goldens and D-1-class catches move post-IC**: defects
  like the NaN leak would be found after outcome contact; any fix that
  touches the predicate after an IC number exists needs a
  count-neutrality proof (D-1 had one — IEEE-754 all-False conjunction
  — but that was luck of the defect class, not a property of the
  ordering).
- *Mitigation available under B.* Freeze the predicate as a shared
  artifact (the census script already is one — Appendix-A pinned,
  imported by both census and extraction); require the harness
  sign-golden before 2b; require the census-consistency smoke as a
  post-implementation acceptance gate with a pre-registered
  consequence for mismatch (implementation-correction re-run, N
  unchanged — the §2.1 rule already says this for 2a failures).

**Honest summary of the tradeoff.** Ordering B saves ~8 commits per
step-2 death and touches nothing about the statistic itself; its real
price is that "the tested object is the deployable object" stops being
true at evidence time and becomes a proof obligation discharged later.
Ordering A pays implementation cost for attribution cleanliness and
pre-outcome defect discovery. The record shows both costs are real:
H8 paid A's cost (8 sunk commits), and H8 also demonstrated B's risk
class is manageable (the extraction reproduced the census 50/50 cells
exactly at stage 0 — S.2 — which is the same equivalence proof B would
rely on). Decision is Lei's; routed as backlog entry 14 (item 7(c)).

---

## 4. STALE-ARITHMETIC RECOMPUTE (census-legal: boundary counts and public grid facts only)

Slate B's exclusions (pack-06 §0) were computed on the 10-session
grid. The operative grid is now **20 sessions for {APP, RMBS}** (03c
AMENDMENT 1; 100 ingested admissible cells) with **60 further cells
DRAWN-NOT-INGESTED** ({OLN, ENSG, DIOD, PCTY, MLI, CROX} × 10
expansion dates, 03c A1.5). All recomputes below are hand arithmetic
on committed boundary counts; no data was touched. This is frontier
characterization, not a new slate — no card is drafted and no
threshold is proposed.

**4.1 H=900 density exclusion — NO LONGER HOLDS as computed.**
Original (pack-06 §0 point 4, verified 06a §1(iii)): 25 in-window
boundaries/session × 10 sessions = 250/symbol ⇒ the ≥ 100 power floor
requires conditioning fraction ≥ 0.40 — near-unconditional entry —
which collapses c_D to ≈ 0.4–0.5 and κ to ≈ 0.05–0.07 vs κ_req,med
0.110 (APP) / 0.112 (RMBS): jointly unsatisfiable. Recomputed on the
operative grid: 25 × 20 = **500/symbol** ⇒ required fraction
**≥ 0.20** — exactly the two-sided decile-tail fraction a percentile
conditioning gives by construction, so the "near-unconditional entry"
premise of the κ-collapse argument is gone. Applying the slate's own
standard multipliers (gate 0.90 × warm 0.95): 500 × 0.20 × 0.90 ×
0.95 ≈ **86 per symbol — straddles the floor from below**; a pooled
{APP ∪ RMBS} evidence set in the A-2.1 style would give ≈ 171.
Caveats binding on any consumer: (i) the map's σ₉₀₀ quantiles and
κ_req values rest on the **original 10 sessions** — the 20-session
σ₉₀₀ distribution is UNKNOWN until a census-legal map recompute runs;
(ii) σ₉₀₀ rests on 26 returns/session (map caveat 2 — soft calls);
(iii) H8's realized-occupancy lesson (assumed 0.226 vs realized 0.107,
C.5) cautions that non-percentile conditioning fractions overstate —
a percentile tail is by construction, but any additional arm is not.
Verdict: the exclusion's arithmetic no longer closes H=900 on
{APP, RMBS}; it degrades to a measurable straddle contingent on the
map recompute. On the six non-expanded symbols it holds unchanged.

**4.2 SCHEDULED_FLOW non-close power basis — single-window mechanisms
HOLD; the algo-clock construction WEAKENS.**
Single-window-per-session mechanisms: 10 → **20 episodes/symbol** on
{APP, RMBS} — still a 5× shortfall against the ≥ 100 floor. The
exclusion **holds**. The densest non-close construction (30-minute
algo-clock boundaries, 12/session; recount verified 06a §1(ii)):
120 → **240/symbol**, so the required conditioning fraction falls from
0.833 to **0.417**. The original kill ("no meaningful directional
conditioning preserves 83 % of boundaries") no longer applies verbatim
— a moderate conditioning retaining ~42 % is not self-evidently
vacuous. But tail conditioning (0.20) yields 48 < 100, and the same
κ-vs-fraction tension (weak conditioning → low c_D) now binds at 0.42
instead of 0.83 — weakened, not opened. On the six non-expanded
symbols the exclusion holds unchanged (10 sessions). The backlog-8
note also stands: taker at H=900 is closed at the median on the
10-session map (κT_req APP 0.357), a magnitude-class fact (§4.4).

**4.3 RMBS power exclusions (H6/H7) — HOLD, numbers stale.**
"p75-open but tail episodes ≈ 33 ≪ 100" (pack-06 H6/H7 §1) doubles to
≈ 66 on 20 sessions — still below the floor. The exclusion holds; the
recorded number is stale and any revival must restate it.

**4.4 Magnitude-class exclusions — HOLD (more data cannot cure them,
subject only to the map recompute).** These exclusions compare κ_req =
floor/σ against a frozen κ; session count enters only through the
quantile estimates, not the criterion:
- **INVENTORY / HAWKES_SELF_EXCITE closed at honest κ** (H=120 κ_req
  exceeds central κ ≈ 0.16 at every quantile; H=30 closed
  universe-wide) — holds as computed on the 10-session map; the
  20-session σ distribution is UNKNOWN until recompute, but doubling
  sessions does not move a magnitude criterion, only its estimate.
- **Taker closed at design** (κT_req 0.449 at H=300 APP median, ≥ 1.5×
  above the 0.30 ceiling) — holds.
- **Micro-price-divergence level drift dead at design** (honest κ ≈
  0.11 vs APP/300 p90 κ_req 0.127) — holds.

**4.5 H6/H7 design-central power park (≈ 52 < 100) — NO LONGER HOLDS
as computed.** The 06a §3 design-central long-only arithmetic doubles
with the grid: 1,520 in-window boundaries × 0.8 × 0.90 × 0.95 × 0.10 ≈
**104 — now straddling the floor from above**. This does not revive
either card (pack-06 DISPOSITIONS 2: revival requires re-derivation
with an explicit short-side posture as a NEW drafted variant), and the
H8 occupancy lesson applies to their gate/warm/viability multipliers;
but the specific arithmetic that made their design-central case a
pre-registered park is stale on the operative grid.

**Summary table:**

| slate-B exclusion | basis then (10-session) | basis now (20-session {APP, RMBS}) | verdict today |
|---|---|---|---|
| H=900 tail conditioning jointly unsatisfiable | 250/symbol ⇒ fraction ≥ 0.40 ⇒ κ collapse | 500/symbol ⇒ fraction ≥ 0.20 (decile tail by construction); ≈ 86/symbol at slate multipliers, ≈ 171 pooled | **does not hold** — straddle, pending map recompute |
| SCHEDULED_FLOW single-window ≪ power | 10/symbol | 20/symbol | **holds** |
| SCHEDULED_FLOW algo-clock needs ≥ 0.83 fraction | 120/symbol | 240/symbol ⇒ ≥ 0.417 | **weakened** — no longer self-evidently vacuous; κ-vs-fraction tension remains |
| RMBS tail-episode exclusion (H6/H7) | ≈ 33 ≪ 100 | ≈ 66 < 100 | **holds** (stale number) |
| INVENTORY/HAWKES κ closure; H=30 closure; taker closure; level-drift design kill | magnitude-class (κ_req vs κ) | unchanged criterion; quantiles unmeasured on 20 sessions | **hold** |
| H6/H7 design-central ≈ 52 < 100 | 760/symbol basis | 1,520/symbol ⇒ ≈ 104 | **does not hold** (revival still requires a NEW drafted variant per DISPOSITIONS 2) |

---

## 5. OPPORTUNITY-SET SYNTHESIS

Combining the feasibility map (`7a08c95`), the three executed verdicts
(H2 park, H8 census arc, H8 rejection), and §4. Two closure classes
are distinguished honestly: **closed-by-rejection** (a claim tested
and failed at its frozen bars) vs **closed-by-precondition** (economics
or power failed before any falsifier ran — mechanism unrefuted).

**KNOWN-CLOSED (with the killing citation):**

- *Closed by rejection:* the elevated-λ continuation claim at H=300,
  passive, on {APP, RMBS} — S.4/S.8, `3b039f3`. Scope precision
  binds: the λ-separation phenomenon is NOT refuted (F2 passed); no
  claim of F2 death may cite this record.
- *Closed by precondition, this universe/grid/cost structure:*
  inventory-fade at H=120 passive (H2 park, `642d12d` — F1–F5 never
  ran); H=30 anything, both execution modes (map §4); taker anything
  at H ≤ 300, and effectively taker everywhere except APP/1800 at the
  median (map §4); the H1-class taker sweep at its stated edges (04a
  check d); INVENTORY/HAWKES at honest central κ on this universe
  (map §4 shrinkage + pack-06 §0); close-window SCHEDULED_FLOW on the
  event-screened grid (H4 park + backlog 8 taker note).

**KNOWN-VIABLE-BUT-UNTESTED (map-open at central κ, never carded or
never censused):**

- KYLE_INFO / SCHEDULED_FLOW **passive at H=900 and H=1800**: map-open
  at κ ≤ 0.30 on all 8 symbols, and at central κ ≈ 0.16 open at the
  median on APP (≥ 300 s) and RMBS (≥ 900 s), with the other symbols
  opening only at 1800 s (map §4 shrinkage). §4.1 now puts H=900
  episode density on {APP, RMBS} at a measurable straddle rather than
  a closure. Untested: no card has ever run a census at H ≥ 900.
- H=1800 on the wider universe (OLN/DIOD/PCTY/CROX at central κ) —
  σ₁₈₀₀ rests on 13 returns/session (map caveat 2); soft.
- H6/H7-class flow-continuation redesigns with an explicit short-side
  posture (pack-06 DISPOSITIONS 2 revival path) — §4.5 arithmetic now
  straddles.

**UNTESTED-UNKNOWN:**

- Universe tranche 2 (higher-σ midcaps) — no screen, cache, or map
  exists (backlog 11).
- The 60 DRAWN-NOT-INGESTED cells — dates ratified, never ingested;
  would double the six thin symbols' grids (03c A1.5).
- A dedicated calendar-event grid (H4 revival program, deprioritized —
  backlog 8).
- Any non-KYLE mechanism family at H ≥ 900 horizons on this universe
  (SCHEDULED_FLOW is the only other legal family there; LIQUIDITY_STRESS
  is exit-only).

**The post-hoc baseline-reversion observation — placed where it
belongs:** it is a **contaminated seed**, not an opportunity-set entry
above. The H8 result doc's POST-HOC section records it as in-sample,
outcome-contaminated, zero evidential weight: matched dislocations
with baseline λ reverted (−5.43 bps, t −2.50 on the primary basis —
H8's own contrast arm, selected into view by the H8 sample). Any card
built on it requires **fresh sessions** (no reuse of the 20-session
H8 evidence grid for confirmation) and **honest-N carriage** (its
first outcome contact is +1 on the living ledger, N ≥ 12 at that
point). The reversion magnitude sits near the single-stress passive
floor (≈ 4.7–5.5 bps) and a fade leg carries the H2-class L2
adverse-fill geometry — both recorded in the seed note itself.

---

## 6. OPEN-THREADS INVENTORY

Backlog entries cite `docs/research/prompt_pack_backlog.md`; vendor
items cite their register. "Prereq-for" flags fork options (§8).

| # | thread | status | owner | prereq-for |
|---|---|---|---|---|
| B-1 | OQ-3 mechanism-cap runtime closure (bootstrap wires `mechanism_max_share_of_gross=1.0`) | OPEN — accepted risk this pack; every capacity claim carries the caveat | composition-layer thread (own tests + parity assessment) | any multi-alpha PORTFOLIO deployment; not blocking forks i–iv |
| B-2 | 00e Track B — engine-level `Signal.strength` enforcement | PROPOSED (spec complete; known parity-breaking: `reference_alpha_signal_fires` embeds strength ≈ 1.1895) | system-architect + signals layer | none of i–iv (evidence runs are single-alpha) |
| B-3 | Parity-manifest host/libm fingerprint FOLLOW-UP | OPEN (sidecar spec in 00d §4) | determinism/testing thread | none directly; hygiene for any cross-host evidence claim |
| B-4 | Link-check extension to `.cursor/skills/**/*.md` | **DONE** (Task 3a, `36c92c8`) | — | — |
| B-5 | Platform-wide session-admissibility guard (unknown ids + units sanity) | OPEN (scoped to the candidate pipeline only; platform-wide needs own thread) | data-integrity thread | forks i–ii (any new ingestion program should inherit it) |
| B-6 | C3 — schema-require `structural_actor` | OPEN (skill-text discipline only; loader change backlogged) | alpha-loader thread | none |
| B-7 | Cost-floor pre-filter as skill edit | PARTIALLY DISCHARGED — map §6 is the operative gate (first applied Task 6-B); the **skill-text edit** remains pending (batch with next maintenance pass) | microstructure-alpha skill | any slate C |
| B-8 | Dedicated calendar-event grid (H4 revival) | DEPRIORITIZED (taker closed at H=900 median; revisit only with a passive-compatible close-mechanism variant) | future program | none current |
| B-9 | `spread_z_30d` warm starvation (warm 0.03–0.16 on 4/8 symbols) | OPEN — platform change, parity assessment required; `window=2000` variant REGISTERED-UNEVALUATED (N-impact 0) | sensors thread | any design gating on `spread_z_30d` (none of i–iii as drafted) |
| B-10 | DI-09 contamination-at-extremes / Class-A filtering for trade-fed extreme-conditioning | OPEN as skill-edit candidate; applied operationally in slate B conventions | microstructure-alpha skill | forks i–iii (any trade-fed extreme conditioning) |
| B-11 | Universe tranche 2 (higher-σ midcaps) | REGISTERED (screen + cache + fresh map; never pooled with the frozen grid) | future program | **fork ii is this thread** |
| V-1 | Vendor: T5-OQ-3 vocabulary answer (June-2026 quote condition/indicator population change; uninterpreted quote condition 34) | OPEN — **post-2026-04-27 sessions are inadmissible until answered** (03c §1(a) amendment A) | Lei / vendor | **forks i and ii** (any fresh-session draw is capped at pre-2026-04-27 until answered); fork iv burns it |
| V-2 | Vendor: AXIS-2 dissemination residuals (cancel/correction records on the `T` channel; stale WS size-units doc) | OPEN — RESEARCH→PAPER promotion blocker per the Task-13 amendment (`prompt_pack_00_architecture_verification.md` §(e)) | Lei / vendor | any promotion past RESEARCH for any future candidate |
| V-3 | Vendor: PCTY quote-indicator-2 confirmation (03b §7.3 question 4) | OPEN — low stakes (3 session-open records; disposition Lei-vetoable) | Lei / vendor | none |
| S-1 | Reversion seed (H8 POST-HOC) | RECORDED — contaminated, fresh-sessions-required, honest-N carried | research-workflow | **fork i is this thread** |
| S-2 | Feasibility-map recompute on the 20-session grid (σ_H quantiles, κ_req surfaces) | NOT YET REGISTERED as a task — implied by §4 (census-legal, no outcome contact) | research-workflow | **fork iii prerequisite**; cheap |

External-dependency summary: **every new-data fork (i, ii) is
date-capped at pre-2026-04-27 until V-1 is answered**; every promotion
past RESEARCH is blocked on V-2. Fork iii needs no new data — only
S-2 plus a fresh card.

---

## 7. SKILL/PROCESS EDIT CANDIDATES (proposals only — routed as backlog entries; NO skill edited in this task)

Appended to `docs/research/prompt_pack_backlog.md` as entries 12–16
for a Task-3-style maintenance pass. Each with its incident citation.

- **(a) Entry 12 — magnitude-vs-power distinction in gate design.**
  Every pre-registered bar is labeled at freeze as n-invariant
  ("more data cannot cure this" — magnitude/κ-class) or power-class
  (curable by evidence volume), and the §9-style consequence class
  (REJECTED vs PARK-evidence-infrastructure) must be consistent with
  that label. Incident: H8's binding failure was the n-invariant
  |RankIC| ≥ 0.03 magnitude bar at 0.0186; the S.8 adjudication had to
  derive this distinction post-outcome (item 3) and the ≈ 110-session
  p-path arithmetic (item 4) to show the safeguard park was a dead
  letter.
- **(b) Entry 13 — consequence-precedence defined at freeze.**
  Whenever two instruments can fire on the same execution
  (gate row + safeguard, park condition + reject condition), the
  freeze must state which governs at every intersection. Incident:
  §9 "2b IC gate" REJECTED vs A-2.1 safeguard PARK fired together
  (S.5); precedence was adjudicated post-outcome (S.8).
- **(c) Entry 14 — step-2 ordering (harness-level IC gate option).**
  The §3 analysis verbatim: an implementation-independent 2b is
  technically possible (the binding statistic never executed the
  YAML); tradeoffs are attribution cleanliness and pre-outcome defect
  discovery (ordering A) vs ~8 sunk commits per step-2 death
  (ordering B), with the equivalence proof (census-consistency smoke,
  stage-0 reproduction) as the migration requirement. Incident: H8
  Tasks 9–10.
- **(d1) Entry 15 — census-legal occupancy pre-read before power
  projections are relied on.** Distribution-theoretic occupancy priors
  (near-Gaussian tail mass, assumed joint fractions) get a
  census-legal occupancy read on the operative grid before a
  selection decision headlines an episode count; percentile-tail
  fractions are exempt (true by construction). Incidents: H8 design
  0.453/0.226 vs realized 0.343/0.107 (C.5 — "the entire power
  shortfall"); H6/H7 104-headline vs ≈ 52 design-central (06a §3).
- **(d2) Entry 16 — grid-amendment constant governance.** Any grid
  amendment pre-registers which frozen census-derived constants
  (cutpoints, terciles, per-symbol thresholds) carry, recompute, or
  refreeze — before execution, not by mid-flight ruling. Incident:
  E.5 spread-tercile discrepancy needing A-2.2.

---

## 8. FORK DECISION BASIS (dossier convention — no selection)

| | (i) reversion-seed program | (ii) universe tranche 2 | (iii) KYLE_INFO/SCHEDULED_FLOW at H=900 on the recomputed frontier | (iv) pause pending vendor answers / backlog burn-down |
|---|---|---|---|---|
| **prerequisites** | Fresh sessions (contamination discipline — no reuse of the 20-session H8 grid for confirmation; draw capped pre-2026-04-27 until V-1); a NEW drafted card under its own protocol from step 1; spec must address the H2-class L2 adverse-fill geometry and the seed magnitude sitting near the single-stress floor (result doc POST-HOC); B-5 guard inheritance; B-10 posture if trade-fed conditioning | B-11: candidate screen, cache build, fresh feasibility map (never pooled with the frozen grid); V-1 caps the draw span; B-5 guard inheritance | S-2 feasibility-map recompute on the 20-session grid (census-legal, no new data); a NEW card with fresh κ derivation (drafting N-impact 0); an evidence-set posture for the per-symbol ≈ 86 straddle (A-2.1 pooling precedent vs per-symbol floor) decided at freeze, not mid-flight (entry 13) | none — burns B-1/2/3/5/6/9 engineering threads and the V-1/V-2/V-3 vendor tickets |
| **est. cost to first census-grade verdict** | Highest of i–iii: fresh draw evidence + ingestion (FQ-5B/A-1 analog, ~2–5 commits) + spec/protocol/census cycle (H8 Tasks 7–8C analog: ~5 commits, 1–2 working days after data) | Highest overall: screen + ~80-cell cache + map (~3–5 commits) before any slate; then slate C + review + spec/protocol/census (~8–10 commits total, several working days + ingestion) | Cheapest: map recompute (1 commit) + card + review + spec/protocol/census on the existing 100-cell cache (~5–7 commits, no new data) | No census-grade verdict is produced; cost is deferral of the opportunity-set question |
| **killing risk** | HIGH — the seed is outcome-contaminated (base rates for contaminated seeds are poor by construction); magnitude ≈ 5.4 bps sits at the 4.7–5.5 floor band; fade economics carry adverse fill selection | MEDIUM-UNKNOWN — higher σ opens κ regions by arithmetic, but H8 taught that realized conditioning occupancy, not σ, was the binding surprise; a new universe re-rolls both dice | HIGH-MEDIUM — per-symbol power straddles from below (≈ 86); σ₉₀₀ rests on 26 returns/session; and the H8 magnitude lesson (realized RankIC ≈ 0.02 at H=300) may generalize across horizons on this universe | n/a — no candidate at risk; the program currently holds zero live edges, so nothing decays except calendar time on the vendor tickets |
| **what a kill would teach** | Whether H8-contrast-arm seeds generalize out of their contaminated sample — calibrates how much weight post-hoc observations deserve as slate inputs (a program-level epistemic constant worth owning) | Whether the cycle-1 frontier is **universe-limited or mechanism-limited**: a second universe failing the same way indicts the mechanism class / horizon band; opening cleanly indicts the frozen grid | Whether the effect-magnitude regime improves with horizon on THIS universe — directly answers the result-doc §12(a) calibration question (is the conjunctive IC gate mis-calibrated to this universe's effect sizes, or are the effects genuinely sub-bar at all horizons?) | nothing about the opportunity set; buys infrastructure and vendor answers for whichever fork follows |

**QUESTIONS FOR LEI (the fork turns on these):**

1. **Magnitude-regime generalization.** H8's kill was magnitude
   (RankIC 0.0186 vs 0.03), n-invariant, at H=300. Do you read that as
   evidence the whole universe's effect-size regime sits below the
   honest bar at all horizons (favoring tranche 2 / pause), or as
   horizon-specific (favoring the cheap H=900 shot, fork iii, before
   any new data spend)?
2. **Vendor dependency posture.** Is the T5-OQ-3 vocabulary answer a
   hard prerequisite for any new data program (forks i–ii), or do we
   accept pre-2026-04-27 draws indefinitely and treat the aging data
   window as an acceptable cost? (V-2 separately blocks any promotion
   past RESEARCH — relevant to how much a census-grade verdict is
   worth before it is answered.)
3. **Contamination discipline for fork i.** If the reversion seed
   proceeds, does it require the full slate-C apparatus (independent
   cold-read review before spec investment, map pre-filter at its own
   κ), or a lighter single-card path given the seed already has a
   mechanism story (the OU null) — and do you confirm its first
   outcome contact is +1 N (N ≥ 12) with fresh sessions only?

---

## 9. LEDGER CLOSE

**N accounting (final N = 11; every increment cited):**

- **N = 10 initialized** at slate-A pre-registration: rows 1–10 of the
  pack-04 §(3) trial-count ledger (five `pre-registered` primaries +
  five `design-considered` alternatives), 2026-07-10.
- **Unchanged through:** FQ-6B-R dispositions (pack-04 DISPOSITIONS 1,
  "N unchanged (N = 10)"); H2 spec/protocol freeze and census
  (protocol §10 + census C.6-equivalent roll-up; result doc §11 —
  census-class, no outcome statistic); H2/H4 adjudication (DISPOSITIONS
  4–5); feasibility map (pack-05 preamble, "N = 10, unchanged");
  slate B and its review (pack-06 §(3); 06a §3 "N = 10, unchanged");
  H8 protocol freeze (§10); H8 primary census + §1.7 variant re-census
  (C.7, V.4 — census-class, variant N-neutral until outcome contact);
  grid expansion + expanded census (E.7 — data augmentation, A1.7);
  A-2 rulings (A-2.4 — zero data contact); Tasks 9–10 implementation
  (impl record §8.4 — "Task 9/10 evaluations: ZERO. N = 10 stands");
  Task 12-P (N-impact 0, card-independent engineering).
- **+1 at H8 step-2b** (2026-07-14): the H8 primary row's first
  outcome contact (protocol S.6; slate-B DISPOSITIONS 7; result doc
  §11). Zero exploratory variants were evaluated; every
  drafted-not-evaluated row remains N-impact 0 and none is authorized
  by the close-out.
- **N = 11 confirmed.** Any future DSR uses the then-current living N
  (≥ 11); any future evaluation of any drafted row is a new trial
  (+1 N) under its own protocol from step 1.

**Evidence artifacts committed with FQ-3 provenance** (each carries
its provenance block in the citing record):

- `artifacts/inventory_fade_census_2026-07-11.json` (sha256 3ab881f5…,
  H2 result doc provenance; bit-identical re-run recorded).
- `artifacts/horizon_feasibility_map_2026-07-11.json` (sha256
  362c42ca…, map §7; bit-identical re-run; SHA independently
  reverified in 06a).
- `artifacts/dislocation_lambda_census_2026-07-12.json` (sha256
  3f571a00…, protocol C.8) and `…_variant_2026-07-12.json` (sha256
  626472e1…, V.5) — both bit-identical on re-run.
- `artifacts/dislocation_lambda_census_expanded_2026-07-13.json`
  (E.8; three runs bit-identical; default invocation reproduced the
  original artifact byte-identically).
- `artifacts/sig_dislocation_lambda_drift_v1/` — Task-11 evidence set
  (`boundaries_extract_2026-07-14.json` sha256 80fdc56c…,
  `validation_stats_2026-07-14.json` sha256 21014b34…, harness CSV +
  stdout/stderr captures; S.7) — untracked at Task-11 report time,
  **disclosed there and committed by the close-out** (`3b039f3`), with
  the five SHA-256s re-verified byte-identical before commit (result
  doc provenance).
- `artifacts/universe_draw_evidence_2026-07-10.md` (`cee84c6`) and
  `artifacts/universe_draw_expansion_evidence_2026-07-13.md`
  (committed with 03c AMENDMENT 1, `696c618`).
- `artifacts/h2_h4_adjudication_package.md` (`4253dbc`).
- Instrument scripts committed with their records:
  `scripts/research/inventory_fade_census.py` (`642d12d`),
  `scripts/research/horizon_feasibility_map.py` (`7a08c95`),
  `scripts/research/dislocation_lambda_census.py` (`fb225ae`/`a17e118`),
  `scripts/research/dislocation_lambda_validation_extract.py` and
  `…_stats.py` (`3b039f3`) — all registered in the
  `docs/prompts/README.md` coverage map per amendment E.

**No uncommitted program state.** Verified this task at HEAD
`3b039f3`: `git status --porcelain` is empty — no modified tracked
file, no untracked research output, no pending artifact anywhere in
the worktree before this retrospective's own outputs. The one
historical instance of evidence produced ahead of its commit (the
Task-11 scripts/artifacts) was disclosed in S.7 at report time and
closed by `3b039f3`.

*Task 7-R stops here. Status: AWAITING-LEI-REVIEW.*
