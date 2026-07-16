<!--
  File:   docs/research/prompt_pack_11a_slate_d_review.md
  Status: DECIDED (2026-07-16) — see DECISION RECORD at end of file.
          Cold-read review dossier on hypothesis slate D (final cycle).
          Independent grading of prompt_pack_11_hypothesis_slate_d.md;
          no candidate selected or endorsed in the review body. No
          forward returns, IC, or signal evaluation — exchange-calendar
          boundary geometry, cache presence, and design arithmetic only.
          Trial ledger: N = 12, unchanged (no outcome contact).
  Owner:  independent slate reviewer (Task FQ-6B-4); decision is Lei's.

  Provenance (FQ-3 template):
    git_sha: "58c6fc60e9b8fa7b703076187f61d65d37048082" (HEAD at task
      start; slate D untracked; this file is the sole intended write)
    worktree_clean: "research outputs: slate D untracked; review is
      sole write"
    pythonhashseed: "0 (set in session for every scripted recompute)"
    recompute: "throwaway stdlib script against DiskEventCache on the
      actual 140-cell grid (03c AMENDMENT 2); census-legal mid-series
      n_returns + 09:35–15:50 decision-boundary enumeration at
      H∈{900,1800}; half-hour / on-the-hour mark classification from
      boundary timestamps alone — no σ, no IC, no forward returns.
      Script not retained. Pack-08 κ_req / floors / six-symbol σ_med
      re-read from prompt_pack_08 / pack-05 (committed surfaces)."
    bias_control: "WINDOW-GEOMETRY AUDIT first; both cards graded and
      an independent order recorded from the per-card matrices BEFORE
      reading slate §(1)–(3) ranking/recommendation/ledger; geometry
      and density recomputes did not change that order."
    normative_inputs:
      prompt_pack_11_hypothesis_slate_d.md (under review),
      prompt_pack_08_frontier_refresh.md,
      prompt_pack_10_cycle2_retrospective.md (DISPOSITION stop-rule +
        SCHEDULED_FLOW substance / outcome-prior disclosure),
      prompt_pack_09_hypothesis_slate_c.md (H9 card; H11 FAIL;
        DISPOSITIONS 3, 8),
      prompt_pack_09a_slate_c_review.md (H11 FAIL bar; 140-cell density),
      sig_sweep_kyle_drift_h900_v1_result.md (H10 F2-refuted KYLE;
        RMBS +0.226 shelf — N≥13 rule),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.4),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2),
      prompt_pack_00b_edge_units_convention.md,
      prompt_pack_03m_skill_verification.md + research-protocol
        (3-M: magnitude-vs-power, consequence-precedence, occupancy),
      prompt_pack_backlog.md entries 17–18,
      src/feelies/alpha/layer_validator.py
        (_FAMILY_FINGERPRINT_SENSORS SCHEDULED_FLOW →
        scheduled_flow_window).
-->

# Task FQ-6B-4 — Cold-read review dossier: hypothesis slate D

Independent review of `prompt_pack_11_hypothesis_slate_d.md`. I grade;
Lei decides. Trial ledger: **N = 12, unchanged by this review** —
nothing here evaluated any hypothesis; the only computations are
exchange-calendar boundary geometry, cache presence, and design
arithmetic.

---

## 1. WINDOW-GEOMETRY AUDIT (load-bearing; before card grades)

**Method:** `PYTHONHASHSEED=0`; 09:30-ET-anchored non-overlapping
decision grid (same nominal grid as `horizon_feasibility_map.py` /
pack-08 / 09a); session window **09:35–15:50 ET**; half-hour marks =
`:00`/`:30`; hour marks = `:00`. Cache check: 03c AMENDMENT 2
140-cell inventory via `DiskEventCache` — **140/140 present**;
per-session `n_returns` at H∈{900,1800} = **25 / 12** bit-exact on
every cell (matches pack-08 convention and 09a §2).

### 1.1 Per-session geometry (reference RTH open; identical on all 140 cells)

| H | in-window bounds / sess | half-hour (:00/:30) | hour (:00) | out of half-hour | out of hour |
|---|---|---|---|---|---|
| 900 | **25** | **12** (frac **0.48**) | 6 (frac 0.24) | **13** | 19 |
| 1800 | **12** | **12** (frac **1.00**) | **6** (frac **0.50**) | **0** | **6** |

H = 900 in-window times: 09:45 … 15:45 step 15 min.
H = 1800 in-window times: 10:00 … 15:30 step 30 min (all half-hour marks).

### 1.2 Verification claims

**(i) H13 tautology / hour-only contrast.** Confirmed: half-hour @
H = 1800 covers **12/12** in-window boundaries — F2 window-binding
against “off half-hour” is **empty by construction**. Hour-only subset
leaves a **real** out-window contrast: **6** `:30` bounds/session vs
**6** on-the-hour. On the H13 six-symbol × 20-session D, design-central
populations after HT×quintile×gw (0.90 × 0.40 × 0.90 × 0.95):

| arm | raw (6 × 20 × 6) | design-central |
|---|---|---|
| in-window (`W_hr`) | 720 | **221.6** |
| F2 contrast (`:30`) | 720 | **221.6** |

Symmetric and well above the pooled census floor — F2 is testable.

**(ii) H12 in-window fraction and F2 contrast arm.** In-window fraction
**0.48** (12/25). Off-clock contrast = **13/25** per session. Matched
OFI-quintile design-central on the F2 arm (APP ∪ RMBS, HT = 0.90):

| arm | raw | design-central | vs ≥ 100 |
|---|---|---|---|
| in-window (`W_hh`) | 12 × 20 × 2 = 480 | **147.7** | PASS |
| F2 off-clock | 13 × 20 × 2 = 520 | **160.1** | PASS (larger than in-window) |

F2 is **not** a starved decoration arm on this grid. A matched
off-clock continuation of the same sign/magnitude class can refute.

**(iii) Density recomputed vs inherited 147.7.** H12 pooled
design-central recomputed:

`1000 × 0.90 × 0.48 × 0.40 × 0.90 × 0.95 = **147.744**`

H11 slate-C pooled design-central (09a / pack-09):

`480 × 0.90 × 0.40 × 0.90 × 0.95 = **147.744**`

**Flag:** the figures match **exactly** by algebra
(`1000 × 0.48 = 480`), not by inheritance of an H11 headline. H12’s
product is recomputed from H = 900 raw × half-hour fraction × quintile;
H11’s was H = 1800 raw × quintile with no window fraction (every 1800
bound was “in”). Numerically identical; mechanistically distinct.
HOLIDAY-THIN haircut **18/20 = 0.90** applied on every 20-session
symbol (2 HT dates present in the operative 20).

### 1.3 Cache density basis (actuals)

| symbol | sess | HT | HT_eff | raw H=900 | raw H=1800 |
|---|---|---|---|---|---|
| APP, RMBS, OLN, DIOD, PCTY, CROX | 20 | 2 | 0.90 | **500** | **240** |
| ENSG, MLI | 10 | 0 | 1.00 | 250 | 120 |

---

## 2. PER-CARD VERDICT MATRICES

Verdicts: **PASS / CONCERN / FAIL**, one-line evidence.
**Independent order recorded after these matrices, before slate §(1)–(3):**
**H12 > H13** (see §7).

### H12 — `sig_halfhour_clock_drift_h900_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | **PASS** | `SCHEDULED_FLOW`; hl 450, H = 900, ratio 2.0 ∈ [0.5, 4.0]; `l1_signature_sensors: [scheduled_flow_window]` (G16 rule-5); `W_hh` / `ALGO_CLOCK` inside the conditional-distribution statement; per-session YAML + `WindowKind.ALGO_CLOCK` + calendar-warm-iff-calendar named. Clears the H11 reformalization bar (09a / DISPOSITIONS 3, 8). |
| b. Structural distinctness | **CONCERN** | Falsifiable window-binding F2 exists and the contrast arm is powered (§1.2). **Plainly:** at design this is *formulated* as scheduled-flow in substance; until F2 fires it remains an **OFI-quintile continuation claim with a clock gate** — the single separating test is F2 (matched ofi-quintile off-clock shows same continuation ⇒ decoration / refute). |
| c. Archetype & counterparty | **PASS** | Actor = clock-sliced institutional parents (schedule / participation caps in clock time); losers = under-reacting LPs / discretionary flow; conservation ≤ residual impact of open scheduled parents on the half-hour grid. |
| d. Feasibility | **PASS** | Recomputed κ = 1.15×0.52×0.50×0.75×0.65 = **0.1458 ≈ 0.146** ≤ 0.30; pack-08 κ_req med APP 0.098 / RMBS 0.117 — both median-open; park 0.146×47.7 ≈ 6.96 > 4.68, RMBS 6.91 > 5.51; short riders APP 0.122 / RMBS 0.140 ≤ 0.146; honest median only; six others correctly out of D @900. |
| e. Density | **PASS*** | Pooled actuals **147.7 ≥ 130**; per-symbol **73.9 < 130** (pool-mandatory, declared). *Equals H11’s 147.7 by the §1.2 identity — recomputed, not copied. Decile joint fails (73.9) — quintile choice arithmetic-forced, disclosed. |
| f. Power structure & precedence | **PASS** | D = {APP, RMBS} pooled; freeze-ready precedence; contingent-trigger table enumerates magnitude / significance / F2 / form / power **modes** (backlog 17). |
| g. Warm reality | **CONCERN** | `scheduled_flow_window` calendar-warm **pre-registered** (load-bearing new path — zero measured calendar coverage on operative dates today); `ofi_integrated` @900 asserted from quote rates; vol measured. No warm-starved gate in the YAML sense, but calendar landing is infrastructure-critical under the stop-rule. |
| h. Contamination | **PASS** | Quote-fed × calendar; no NEW trade-fed extreme; REPORTS estimands labeled (geometry vs leakage); **RMBS +0.226 shelf not consumed** anywhere on this card (N ≥ 13 rule clean). |
| i. Outcome-informed priors | **PASS** | Dedicated disclosure table; H8/H10 magnitude shelf → horizon-selection discussion only (pack-10 DISPOSITION 3); H10 F2 miss → family switch only; cycle-1/2 warm/ISO/occupancy → conventions. Addendum-G-style tracing complete for stated quantities. |
| j. Rejected / dead-claim adjacency | **CONCERN** | Not H10’s KYLE claim (different F2). **H9 adjacency is first-order:** same quote-OFI continuation machinery at H = 900 on {APP, RMBS}. An H12 **F1 pass + F2 pass** is evidence about *clock-bound* OFI, not a KYLE rehabilitation of H9. An H12 **F1 pass + F2 fail** would look like H9-class unclocked OFI continuation (and would not authorize H9 under DISPOSITIONS 8). An H12 **F1 miss** strengthens the presumption against OFI-continuation magnitude on this universe (H9’s untested claim stays dead). Sibling logic: do **not** treat H12 outcomes as silent H9 adjudication without extraordinary justification. |
| k. Distinctness vs H13 / stop-rule | see §4 | — |

### H13 — `sig_hour_checkpoint_drift_h1800_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | **PASS** | Same G16 / predicate / calendar bar as H12; hl 900, H = 1800, ratio 2.0; hour-only `ALGO_CLOCK` avoids the §0.2 tautology; deliverables named (union of six-symbol operative dates). |
| b. Structural distinctness | **PASS** | Hour-vs-`:30` F2 is load-bearing and powered (§1.2: 221.6 vs 221.6). Not “H12 at 1800 with half-hour marks.” |
| c. Archetype & counterparty | **PASS** | Actor = hour-checkpointed parents / desks (VWAP / schedule variance on the hour); losers = LPs between hourly reviews; conservation ≤ residual impact on the hourly grid. |
| d. Feasibility | **CONCERN** | **κ arithmetic defect:** stated factors 1.20×0.55×0.55×0.80×0.65 = **0.1888**, card freezes **0.172** (matches only if one of `f_perm`/`r_rem` were 0.50). Park edges and OLN/PCTY thinness still OPEN under either number; APP/RMBS short riders clear. D roles match pack-08 §2.4 median-open set at the **0.16 honest screen** — but under the card’s own frozen κ (0.172 or 0.189), ENSG κ_req 0.169 would be open; exclusion is the 0.16-class screen, not the frozen product. Soft-σ₁₈₀₀ + Tranche-1B 10-session κ for four names disclosed; long-only restatement chain present. |
| e. Density | **PASS*** | Six-symbol pool **221.6 ≥ 130**; per-symbol 36.9 FAIL (required). APP∪RMBS alone **73.9 FAIL** — Tranche-1B four are density-mandatory. Axis-split as symbols drop (HT=0.90, w=0.50, quintile, gw): **6 → 221.6; 5 → 184.7; 4 → 147.7; 3 → 110.8** (clears census ≥100, **fails design ≥130**); **2 → 73.9** (fails both). Card states re-check-on-drop but does **not** tabulate these numbers — completeness gap, not a false PASS. |
| f. Power structure & precedence | **CONCERN** | Pooled-only freeze-ready; failure modes vs H12 enumerated (backlog 17) including correct non-auto-kill on H12 half-hour F2. Partial-pool survival **not stated numerically on the card** (reviewer’s §2e table is the missing freeze content). |
| g. Warm reality | **CONCERN** | Same calendar-warm pre-registration; larger surface (6×20); thin names’ `ofi_integrated` @1800 asserted — census drop rule present. |
| h. Contamination | **PASS** | Same quote-fed × calendar class as H12; REPORTS labeled (`halfhour_not_hour_cotravel_rate` ≈ 0.50 geometry); RMBS +0.226 unused. |
| i. Outcome-informed priors | **PASS** | Block present; thinner than H12’s but covers magnitude shelf, H10 F2 family switch, and §0.2 geometry lesson. |
| j. Rejected / dead-claim adjacency | **PASS** | Distinct from H10 KYLE and H4 MOC/close; H11′ family member via hour-only @1800; related-to-H12 without being a parameter variant. |
| k. Distinctness vs H12 / stop-rule | see §4 | — |

---

## 3. REJECTED-CLAIM ADJACENCY (expanded)

| card | vs H10 F2-refuted KYLE @900 | vs H9 untested OFI KYLE @900 |
|---|---|---|
| H12 | Different family; F2 is window-binding, not λ/volume co-travel. H10’s magnitude shelf is disclosed horizon discussion only — not a κ/bar prior. | **Highest adjacency on the slate.** Shared universe, H, OFI conditioner class, pool. H12’s clock instrument + F2 are what keep it from being “H9 with a prose clock.” Outcomes about H12 are **not** automatic evidence *for* H9’s KYLE attribution; they *can* be evidence about OFI-continuation magnitude on this grid (see H12 check j). |
| H13 | Cleanly not that claim (H, window cadence, D differ). | Weaker adjacency than H12 (different H and conditioner window); still OFI-quintile continuation in the entry arm. |

**RMBS +0.226:** H10 result-doc shelf only; **N ≥ 13** before any use as evidence. Neither card consumes it in κ, density, bars, or ranking arithmetic. **Clean.**

---

## 4. DISTINCTNESS (H12 vs H13) AND THE STOP-RULE

Shared: `SCHEDULED_FLOW`, `scheduled_flow_window` + `ALGO_CLOCK` taxonomy,
quote `ofi_integrated` quintile entry, passive, MIXED mirage, calendar
deliverable path, stop-rule exposure to form/calendar FAIL.

Distinct: actor cadence (half-hour slice vs hour checkpoint), H (900 vs
1800), hl (450 vs 900), D ({APP,RMBS} vs six κ-open names), F2 contrast
(off-15-min grid vs `:30`-not-hour), failure modes (H12 F2 fail
presumptively kills shared half-hour binding; H13’s table correctly
does **not** auto-kill on that mode).

**Verdict:** two hypotheses, not one claim at two horizons — different
binding clocks and different F2 populations. Independence is
**moderate:** a shared OFI-manufacture or calendar-taxonomy FAIL can
kill both; a half-hour F2 miss need not kill hour-binding; an
n-invariant magnitude miss on H12 is a strong prior against H13’s
continuation magnitude (card’s contingent table agrees).

**Stop-rule bearing (pack-10 DISPOSITION 2):** this is the **final**
cycle; any non-PASS (park / reject / form) closes the program.
Holding H13 contingent on H12 is informative **only if** the
failure-mode table is the one frozen (backlog 17) — especially
significance-only and F2-architecture splits. Running both as
co-primary doubles infrastructure ruin risk (calendar surface) under
the same stop-rule. I do **not** select sequencing; I note the
asymmetry.

---

## 5. RISKS — H12 specifically

H12 is the cheapest discharge of the H11′ bar with a non-vacuous F2, and
that is also why it concentrates final-cycle risk on:

1. **OFI×clock vs OFI-only** — substance lives entirely in F2; a
   magnitude pass with F2 fail is a terminal scheduled-flow reject and
   a dangerous near-miss relative to dead H9.
2. **Calendar / taxonomy infrastructure** — `ALGO_CLOCK` + 20-session
   YAML set is on the critical path; under the stop-rule a form/calendar
   FAIL closes the **program**, not just the card.
3. **Density coincidence** — design-central 147.7 equals H11’s figure
   by algebra; reviewers must not treat that as independent
   confirmation of power.
4. **Sibling leakage** — any positive H12 statistic must not be smuggled
   into H9 revival or into κ/bar setting (N ≥ 13; DISPOSITIONS 8;
   pack-10 prior-disclosure rule).
5. **Quintile weakness** — c_D prior 1.15 is softer than H9’s decile
   story; F1 can die from dilute conditioning even if the clock is real.

---

## 6. SLATE-LEVEL — pre-filters, S×F÷M, recommendation audit

**Hard pre-filters recomputed:**

| card | κ_frozen (recomputed) | κ_req med (set) | density (pooled actuals) | cost | density | enter? |
|---|---|---|---|---|---|---|
| H12 | **0.146** (matches card) | 0.098 / 0.117 | **147.7** | PASS | PASS | **YES** |
| H13 | card **0.172** / factors **0.189** | 0.074–0.153 (D six) | **221.6** | PASS either κ | PASS | **YES** |

Form / reformalization pre-filter: both drafted to clear pending
taxonomy+calendar landing (named deliverables — not H11-style residue).

**S×F÷M:** H12 = 4×4÷1.5 = **10.67 ≈ 10.7**; H13 = 4×3÷1.5 = **8.0**.
Formula order **H12 > H13** — arithmetic correct. Blind spots (iv)–(vi)
adequately named for a final-cycle slate.

**Independent order (recorded before reading slate §(1)–(3)):
H12 > H13.**

Basis: H12 clears the H11′ bar with powered F2, correct κ product,
smaller calendar/κ-drift surface, and no six-symbol cascade below the
design margin at 3-symbol survival. H13 is a real second claim (hour
binding + density headroom) but carries the κ mis-product, soft-σ /
Tranche-1B caveats, and pool fragility (3 symbols → 110.8 < 130).

**Recommendation audit:** slate recommends **H12**, optional contingent
H13 — **agrees with independent order and with the formula.** Override
class: none required. The slate’s rationale (non-vacuous F2, no
Tranche-1B κ dependence, smaller stop-rule infrastructure surface) is
the same class of reasons this review used. Holding H13 contingent is
available and consistent with moderate distinctness + backlog 17; not
endorsed or rejected here.

---

## 7. RECONCILED RANKING (reviewer's; not a selection)

| Rank | Card | Role in reconciled view |
|---|---|---|
| 1 | **H12** | Best H11′ discharge; formula + independent favorite; see §5 risks |
| 2 | **H13** | Distinct hour×1800 claim; denser pool; κ arithmetic + D-cascade debts before any freeze |

I do **not** select. Lei decides.

---

## 8. LEDGER APPENDIX VERIFIED

Living N = **12** (pack-10 §6 / DISPOSITION 5). Slate-D primary and alt
rows are drafted-not-evaluated (N-impact 0). Shared `ALGO_CLOCK`
infrastructure N-neutral until paired with outcome contact. H9 remains
dead pending extraordinary justification; KYLE continuation not
authorized. First outcome contact on any primary → **N ≥ 13**.
**Verified; no inflation.**

---

## 9. QUESTIONS FOR LEI

1. **H13 κ freeze.** The factor table multiplies to **0.189**, not
   **0.172**. Do you want the freeze restated to the product of the
   written factors, or a factor corrected to make 0.172 (and, under
   either reading, should ENSG at κ_req 0.169 enter D when frozen κ >
   0.16)?

2. **Contingent H13 under the program stop-rule.** Given final-cycle
   closure on any non-PASS, do you want H13 held contingent with the
   backlog-17 mode table (so a significance-only or half-hour-F2 miss
   on H12 can still authorize H13), or H12-only to minimize
   calendar/taxonomy ruin surface?

3. **H12 ↔ H9 firewall.** If H12 posts F1 magnitude with **F2 fail**
   (clock decoration), should that outcome be pre-committed as
   *strengthening* H9’s presumptive death (OFI continuation without
   scheduled-flow substance), or strictly N-inert for H9 under
   DISPOSITIONS 8?

---

**Task FQ-6B-4 complete (2026-07-16). Status: DECIDED — see DECISION
RECORD below. No selection in the review body.**

---

## DECISION RECORD (Lei, 2026-07-16 — append-only)

Rulings on §9:

1. **H13 κ freeze — keep 0.172 (minimum rule).** Factor table multiplies
   to **0.189**; freeze stays at **0.172**. Arithmetic bug logged
   (check d); factors are not rewritten to erase the freeze. ENSG at
   κ_req 0.169 does **not** enter D — exclusion remains the 0.16-class
   honest screen (pack-08 §2.4), not the frozen product. Pool-collapse
   floor behavior (check e axis-split) must be frozen into any H13
   protocol before census.

2. **Contingent H13 under the program stop-rule — HELD CONTINGENT**
   with the enumerated trigger table (pack-11 DISPOSITIONS 2): (a) H12
   design/census death → activates (κ 0.172; pool-collapse floors
   pre-frozen); (b) H12 2b fail with F2-binding PASS → activates,
   sibling arithmetic disclosed; (c) H12 2b fail with F2-binding
   NEGATIVE → activation only after Lei reviews F2 by window type
   (hour-subset masking; disclosed outcome-contaminated). Not
   H12-only; not co-primary.

3. **H12 ↔ H9 firewall — both directions binding** (pack-11
   DISPOSITIONS 3). H12 evidence never cites toward H9 revival
   (F2-pass strengthens H9 death; F2-fail out-window arm =
   contaminated shelf). H9 history never prejudices H12 scoring.

**H12 CONFIRMED** (`sig_halfhour_clock_drift_h900_v1`). Formula +
cold-read + slate recommendation concur (**H12 > H13**). Either
card's 2b PASS satisfies the stop-rule; both exhausted without one →
program closes per pack-10. Full record:
`prompt_pack_11_hypothesis_slate_d.md` DISPOSITIONS.
**N = 12 unchanged** (no outcome contact).
