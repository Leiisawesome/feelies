<!--
  File:   docs/research/prompt_pack_09a_slate_c_review.md
  Status: DECIDED (2026-07-15) — see DECISION RECORD at end of file.
          Cold-read review dossier on hypothesis slate C (Task
          FQ-6B-3, 2026-07-15). Independent grading of
          prompt_pack_09_hypothesis_slate_c.md; no candidate selected
          or endorsed in the review body. No forward returns, IC, or
          signal evaluation — boundary counts and arithmetic only.
          Trial ledger: N = 11, unchanged (no outcome contact).
  Owner:  independent slate reviewer (Task FQ-6B-3); decision is Lei's.

  Provenance (FQ-3 template):
    git_sha: "eb416bc40beeeded3874e8bfd8a2d88b8e8a944d" (HEAD at task
      start = TRANCHE-1B ingest commit; slate file untracked at review
      start; this file is the only intended output)
    worktree_clean: "research outputs: slate C untracked; review is
      sole write"
    pythonhashseed: "0 (set in session for every scripted recompute)"
    recompute: "throwaway stdlib script against DiskEventCache on the
      actual 140-cell grid (03c AMENDMENT 2); census-legal mid-series
      n_returns at H∈{900,1800} only — no σ, no IC, no forward
      returns. Script not retained. Every number below is reproduced
      as plain arithmetic. Pack-08 κ_req / floors re-read from
      prompt_pack_08_frontier_refresh.md §2 (APP/RMBS n=20 cells
      unchanged by Tranche-1B)."
    bias_control: "cards graded and an independent order recorded from
      the per-card matrices BEFORE reading slate §(1)–(3)
      ranking/recommendation/override; density actuals and seed audit
      executed before that ranking read and did not change the order."
    normative_inputs:
      prompt_pack_09_hypothesis_slate_c.md (under review),
      prompt_pack_08_frontier_refresh.md (+ operative map artifact
        cited therein),
      prompt_pack_07_program_retrospective.md (items 2, 4, 5; S-1),
      prompt_pack_03b_print_eligibility.md (§3.3 Class-A, §4.4),
      prompt_pack_03c_universe_and_cache.md (through AMENDMENT 2,
        140-cell inventory, HOLIDAY-THIN),
      prompt_pack_00b_edge_units_convention.md,
      sig_dislocation_lambda_drift_v1_result.md (incl. POST-HOC),
      sig_dislocation_lambda_drift_v1_formal_spec.md Appendix A
        (contamination precedent),
      microstructure-alpha/research-protocol.md Validation Protocol &
        Slate Design Discipline (3-M: magnitude-vs-power,
        consequence-precedence, occupancy pre-read — binding),
      src/feelies/alpha/layer_validator.py (_FAMILY_FINGERPRINT_SENSORS).
-->

# Task FQ-6B-3 — Cold-read review dossier: hypothesis slate C

Independent review of `prompt_pack_09_hypothesis_slate_c.md`. I grade;
Lei decides. Trial ledger: **N = 11, unchanged by this review** —
nothing here evaluated any hypothesis; the only computations are
cache boundary counts and design arithmetic.

---

## 1. SEED AUDIT — S-1 EVALUATED-AND-EXCLUDED

**Source arithmetic recomputed (pack-08 APP/300 σ_med 34.0; floor
4.68):**

| view | κ product / haircut | κ_rev | edge (κ×σ) | vs κ_req 4.68/34.0 = **0.1376** | vs floor 4.68 |
|---|---|---|---|---|---|
| (A) observation-ceiling × f_pass | (5.43/34.0) × 0.55 = 0.1597 × 0.55 | **0.0880** | **2.99 bps** | 0.1376 > 0.088 → CLOSED | CLOSED |
| (B) fresh factors | 1.0 × 0.50 × 0.60 × 0.70 × 0.55 | **0.1155** ≈ 0.116 | **3.93 bps** | 0.1376 > 0.1155 → CLOSED | CLOSED |
| Contaminated gross, zero haircut | — | — | 5.43 | opens APP only | 16 % above floor; fails once f_pass binds; fails RMBS/DIOD floors even gross |

Slate quoted values (0.088 / 0.116; 2.99 / 3.94; κ_req 0.138) match to
rounding. **Exclusion is sound.**

**Convention check (harsher / softer / exact):**

- Using the contaminated POST-HOC mean as an *observation ceiling*
  then applying `f_pass` — correct contaminated-seed posture; not
  softer than required (zero-haircut would falsely open APP).
- Fresh (B) refuses H8's contaminated `c_D = 1.3` — correct.
- Floor is pack-08 grid-median passive single-stress APP **4.68** —
  correct; one-way units (00b).
- `f_pass = 0.55` is a design haircut grounded in the POST-HOC's own
  H2-class adverse-fill warning, not an extra Inv-12 stack — honest,
  not harsher than frozen cost conventions require.
- **Minor prose defect:** ranking table (1a) lists seed κ_frozen
  **0.114**, which matches neither (A) 0.088 nor (B) 0.116. Does not
  change the CLOSED verdict.

**Ledger / contamination notes:** S-1 closed at design, N-impact 0
(no outcome contact) — correct under FQ-6B-R. Contaminated,
fresh-sessions-required, honest-N carriage for any future revival —
correct vs pack-07 S-1 / result-doc POST-HOC. Thread status
EVALUATED-AND-EXCLUDED at the cost-floor hard pre-filter is the right
disposition; evidence-cell disjointness and N ≥ 12 are correctly
moot.

**Seed-audit verdict: CONFIRM exclusion.**

---

## 2. DENSITY REALITY UPGRADE — actual 140-cell cache

**Method:** `PYTHONHASHSEED=0`; direct `DiskEventCache` RTH mid-series;
09:30-ET-anchored non-overlapping returns (same estimator as
`horizon_feasibility_map.py`); H ∈ {900, 1800} only. Grid =
03c AMENDMENT 2: 20 sessions for {APP, RMBS, OLN, DIOD, PCTY, CROX};
10 for {ENSG, MLI}. **140/140 cells present.**

| symbol | sess | HT sess | HT_eff | raw H=900 | raw H=1800 | per-sess 900 / 1800 |
|---|---|---|---|---|---|---|
| APP | 20 | 2 | 0.90 | **500** | **240** | 25–25 / 12–12 |
| RMBS | 20 | 2 | 0.90 | **500** | **240** | 25–25 / 12–12 |
| OLN | 20 | 2 | 0.90 | 500 | 240 | 25–25 / 12–12 |
| DIOD | 20 | 2 | 0.90 | 500 | 240 | 25–25 / 12–12 |
| PCTY | 20 | 2 | 0.90 | 500 | 240 | 25–25 / 12–12 |
| CROX | 20 | 2 | 0.90 | 500 | 240 | 25–25 / 12–12 |
| ENSG | 10 | 0 | 1.00 | 250 | 120 | 25–25 / 12–12 |
| MLI | 10 | 0 | 1.00 | 250 | 120 | 25–25 / 12–12 |

Pack-08 §4 convention (25 / 12 per session) is **bit-exact on every
cell**, not a projection shortfall. Tranche-1B does not change
{APP, RMBS} raw counts (already at 20).

**Card design-central episodes on actuals** (same multipliers as cards;
HT = 0.90 on deployable set):

| card | conditioning | per-symbol (APP or RMBS) | pooled APP ∪ RMBS | vs ≥ 130 | projection-only? |
|---|---|---|---|---|---|
| H9 | 0.20 × gate×warm 0.90×0.95 | 500 × 0.90 × 0.20 × 0.90 × 0.95 = **76.95** | **153.9** | pool PASS; per-symbol FAIL | **No** — actuals = pack-08 basis |
| H10 | 0.20 × gw × ISO 0.95 | **73.10** | **146.2** | pool PASS; per-symbol FAIL | **No** on boundary basis; ISO 0.95 remains an *unverified* non-exempt prior (see H10 d) |
| H11 | 0.40 × gw | **73.87** | **147.7** | pool PASS; per-symbol FAIL (required) | **No** |

**No card's ≥ 130 claim survives only on projection** for the
{APP, RMBS} pool. Stale card prose: H11 still says evidence-only
{OLN, DIOD, PCTY, CROX} "if/when 60 DRAWN-NOT-INGESTED cells are
ingested" — **40 of those cells are now ingested** (A2); registering
them into D remains a backlog-16 grid-amendment act, but the
"not ingested" premise is outdated.

---

## 3. PER-CARD VERDICT MATRICES

Verdicts: **PASS / CONCERN / FAIL**, one-line evidence.

### H9 — `sig_ofi_kyle_drift_h900_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 450 ∈ [60, 1800]; H = 900; ratio 2.0; `kyle_lambda_60s` is a rule-5 KYLE primary; conditional dist fully stated (ofi_integrated pct ≥ 0.90 / ≤ 0.10, vol gate); no unreformalized residue. |
| b. Archetype & counterparty | PASS | Informed/committed-flow-following; losing pool = latency-constrained LPs + the parent's own IS — persists because completion schedules force continued impact payment over tens of minutes at these horizons. |
| c. Feasibility | PASS | Recomputed κ = 1.2×0.55×0.50×0.75×0.65 = **0.1609 ≈ 0.161** ≤ 0.30; pack-08 κ_req med APP 0.098 / RMBS 0.117 — both median-open; park 0.161×47.7 ≈ 7.68 > 4.68 (1.64×), RMBS 7.62 > 5.51; short rider APP 0.122 / RMBS 0.140 ≤ 0.161; **honest-κ only** (no p75/p90 dependence). |
| d. Density margin | **CONCERN** | Actuals give pooled 153.9 ≥ 130 with stated decile 0.20 (occupancy-exempt); **per-symbol 76.95 < 130** — §0 "per deployable symbol" bar is met only under the pooled structure of block 3, not per symbol. Not projection-only. |
| e. Power structure | PASS | Deployable {APP, RMBS}; evidence pooled; per-symbol diagnostic-only; consequence-precedence sketch copies backlog-13 defaults + A-2.1-class D-drop recheck — freeze-ready. |
| f. Warm reality | **CONCERN** | `realized_vol_30s_zscore` measured (H2 C.5); `ofi_integrated` @900 and `kyle_lambda_60s` warm **asserted** from quote/trade rates / inventory_pressure proxy — census verification pre-registered, not measured. Four NEW symbols not in D (N/A). No `spread_z_30d`. |
| g. Contamination | PASS | Quote-fed entry (Class-B absent); unfiltered `kyle_lambda_60s` F2-only with Class-A NEW-λ fallback — H8 Appendix-A / §2 precedent fits (λ not at entry extremes). |
| h. Falsification & regime | PASS | ≥ 3 dual-form (F1–F5); L1–L5 via §0.1; NEW-SENSOR count **0** (YAML + percentile factory). |
| i. Rejected-claim adjacency | **CONCERN** | Conditioner/horizon differ from H8 elevated-λ continuation — **not** "H8 again" mechanistically. Dominant failure mode (d) is still the **same population kill**: n-invariant sub-bar continuation magnitude on this universe. Distinguishing falsifier = OFI-specific F2 (λ elevation / same-direction print volume in OFI windows), not a dislocation×λ contrast. |
| k. No anchoring / peeking | PASS | No outcome stats; CKS/Kyle citations are literature; map/census characterization only. |

### H10 — `sig_sweep_kyle_drift_h900_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 450; H = 900; ratio 2.0; `kyle_lambda_60s` rule-5 primary (+ NEW SFI listed); SFI conditional dist with Class-A ∩ id-14; no residue. |
| b. Archetype & counterparty | PASS | Informed sweeper; losing pool = resting LPs lifted cross-venue before repricing — persists because display obligations + ISO urgency leave permanent impact on the tape at 900 s. |
| c. Feasibility | PASS | κ = 1.2×0.65×0.45×0.75×0.60 = **0.15795 ≈ 0.158**; same map cells; park OPEN both symbols; short riders clear thinly; honest median only. |
| d. Density margin | **CONCERN** | Pooled actuals 146.2 ≥ 130; per-symbol 73.1 < 130 (same pool dependency as H9). **Plus:** ISO-warm 0.95 is a **non-percentile occupancy prior** inside the selection density headline — backlog 15 / 3-M requires census-legal pre-read before such headlines (percentile tails exempt; this multiplier is not). Card discloses census-stage verification; still a selection-headline defect relative to H9's percentile-only arithmetic. |
| e. Power structure | PASS | Identical axis split / precedence sketch to H9 — freeze-ready. |
| f. Warm reality | **CONCERN** | NEW `sweep_flow_imbalance` warm **asserted** from 03b ISO rates × trade intensity (legacy characterization, not frozen-grid measured); λ/vol as H9; no `spread_z_30d`. |
| g. Contamination | PASS | Exemplary 03b case: Class-A + §4.4 netting as explicit NEW-sensor parameters; no unfiltered trade-fed entry extremes. |
| h. Falsification & regime | PASS | F1–F5 present; L1–L5 cited; NEW-SENSOR count **1** — sole Task-9 size driver on this slate. |
| i. Rejected-claim adjacency | **CONCERN** | Not H8's claim (sweep flow ≠ dislocation×λ; H = 900). Same dominant magnitude-regime failure mode as H9/H8 population. Distinguisher = certified irrevocable prints + ignition/volume-floor falsifiers. |
| k. No anchoring / peeking | PASS | H1/H7 used as mechanics pointers only (session constraint 6 stated); no outcome peeking. |

### H11 — `sig_halfhour_clock_drift_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | **FAIL** | Declares `SCHEDULED_FLOW` but `l1_signature_sensors: [ofi_ewma]` — validator rule-5 primary for SCHEDULED_FLOW is **only** `scheduled_flow_window` (`layer_validator.py`). Conditional dist is quintile `ofi_integrated` at every H = 1800 boundary — **no clock-window predicate**. Clock-grid story is unreformalized residue. |
| b. Archetype & counterparty | **CONCERN** | Actor/counterparty named (clock-sliced parents vs under-reacting LPs), but without a clock instrument in the rule the counterparty story is not load-bearing on the stated conditional. |
| c. Feasibility | PASS | κ = 0.90×0.50×0.55×0.75×0.65 = **0.1207 ≈ 0.121**; κ_req med APP 0.074 / RMBS 0.086 — deeply open; park OPEN; short riders clear; honest median; soft-σ caveat disclosed. |
| d. Density margin | PASS* | Pooled actuals 147.7 ≥ 130 with stated quintile 0.40; per-symbol 73.9 FAIL as the task requires for any 1800 card. *Pass only under declared pooled structure. |
| e. Power structure | PASS | Pooled-mandatory; deployable {APP, RMBS}; per-symbol cannot PROCEED (freeze-blocking if treated as PROCEED) — verified: no symbol clears 1800 individually (73.9 < 130). Precedence sketch freeze-ready. Evidence-only Tranche-1B prose is stale (see §2). |
| f. Warm reality | **CONCERN** | `ofi_integrated` @1800 warm asserted; vol measured; λ F2-only. Warm on four NEW symbols' cells **asserted-not-measured** and those symbols are not in frozen D — if later amended in, re-measure. |
| g. Contamination | PASS | Quote-fed entry; no NEW trade-fed extreme conditioner; clock crowding named as failure mode not print-eligibility. |
| h. Falsification & regime | PASS | F1–F5 mechanism-specific; L1–L5; NEW-SENSOR count **0**. |
| i. Rejected-claim adjacency | PASS | Different family claim (if reformalized), H = 1800, no λ/dislocation arm — cleanest adjacency table on the slate; does not recycle the H8 population as the entry conditioner. |
| k. No anchoring / peeking | PASS | No outcome stats. |

---

## 4. DISTINCTNESS (H9 vs H10)

Both are **KYLE_INFO @ H = 900, passive, pooled {APP, RMBS}, hl = 450,
decile-tail continuation**. Shared fingerprints at the family level:
`kyle_lambda_60s` (F2 / G16 primary), same regime gate shape, same
dominant failure mode (horizon-magnitude generalization of H8's
sub-bar continuation on this universe). Distinct observables:
**quote-integrated OFI** (revocable, MIXED mirage) vs **Class-A
condition-14 sweep imbalance** (irrevocable, LOW mirage); distinct
κ factor tilts (`f_perm` / `r_rem` / `f_pass`); implementation fork
(YAML-only vs NEW sensor).

**Verdict:** two hypotheses, not one card with two conditioning
variants — the observable class and contamination/mirage posture
differ enough to justify separate ledger rows. They are **weakly
independent trials**: an n-invariant magnitude miss on either is
strong prior that the sibling dies the same way; an OFI-manufacture
kill or an ISO-ignition kill can separate them.

---

## 5. REJECTED-CLAIM ADJACENCY (slate-level)

| card | vs H8 elevated-λ continuation @300 | vs contaminated baseline-λ reversion |
|---|---|---|
| H9 | Different conditioner (OFI) and horizon; **same continuation-on-this-universe magnitude risk** is first-order | Not a fade card |
| H10 | Different conditioner (ISO) and horizon; **same magnitude risk** | Not a fade card |
| H11 | Different family/horizon if reformalized; weakest adjacency | Not a fade card |

For H9/H10 especially: the falsifiable claim that distinguishes each
from "H8 again at a longer horizon" is **not** the horizon alone — it
is the conditioner-specific F2 (OFI↔impact/print co-travel; ISO↔informed
vs delta-hedger). If F1 dies at |RankIC| ≪ bar with F2 still
passing, that is the H8 pattern repeating.

---

## 6. RISKS — H9 specifically

H9 is the cheapest instrument that asks result-doc §12(a)
(horizon-magnitude calibration on this universe) — and that is also
why it is the **highest-adjacency** card to H8's kill. Selecting it
first concentrates cycle-2 risk on the same population failure mode
(continuation magnitude) with a *weaker* mirage posture (MIXED
quote-OFI) than H10, warm assertions unmeasured at h = 900, and a
density bar that clears only in pool. A clean H9 F1 miss teaches the
calibration lesson; it does not buy a better observable. Trap risk:
treating a second magnitude miss as "we learned the universe" while
never testing the certified-print conditioner (H10) that could have
separated manufacture from mechanism.

---

## 7. SLATE-LEVEL — pre-filters, S×F÷M, override audit

**Hard pre-filters recomputed (cost-floor AND density-margin on
actuals):**

| card | κ_frozen vs κ_req med | density (pooled actuals) | enter? |
|---|---|---|---|
| SEED | 0.088 / 0.116 < 0.138 | n/a | **EXCLUDED** (confirm) |
| H9 | 0.161 > 0.098 / 0.117 | 153.9 ≥ 130 | YES |
| H10 | 0.158 > 0.098 / 0.117 | 146.2 ≥ 130 | YES |
| H11 | 0.121 > 0.074 / 0.086 | 147.7 ≥ 130 | YES on economics/density; **form FAIL** is outside these two pre-filters |

Agrees with slate (1a) on cost/density entry. H11's form FAIL should
block confirmation until reformalized — not invisible to ranking.

**S×F÷M arithmetic:** H10 = 5×3÷1.0 = **15.0**; H9 = 4×5÷1.5 = **13.3**;
H11 = 3×5÷1.5 = **10.0**. Formula order **H10 > H9 > H11** — correct.
Blind spots named (pack-07 item 2) — adequate disclosure.

**Independent order (recorded before reading slate §(1)–(3)):
H10 > H9 > H11.**

Basis: H10 has the cleanest mirage, exemplary contamination posture,
and the strongest observable separation from H8's kill population;
density ISO prior is a CONCERN but disclosed. H9 second — YAML-cheap
and occupancy-clean, but highest H8-adjacency and MIXED mirage. H11
last — G16 fingerprint / clock-predicate FAIL; soft σ₁₈₀₀; weakest
conditioning.

**Override audit (slate recommends H9 over formula H10-first):**
Rationale is coherent and pre-registered (largest percentile-only
density margin; no NEW sensor; no non-exempt occupancy prior; cheapest
§12(a) calibration shot). That is **program-strategy**, not the same
class as the H8 selection override (06a): H8 corrected a formula miss
of a hard economics/power interaction. Here the formula and this
review agree on H10-first; the slate demotes the cleaner conditioner
to buy a cheaper calibration experiment. **Principled as research
priority; taste relative to independent card-quality ranking.** Not
blind-spot-driven in the H8 sense.

---

## 8. LEDGER APPENDIX VERIFIED

N = **11** living (pack-07 §9). All H9/H10/H11 primary and alt rows
drafted-not-evaluated (N-impact 0). Shared Class-A NEW-λ fallback
N-neutral. SEED EVALUATED-AND-EXCLUDED at design (N-impact 0). First
outcome contact on any primary → N ≥ 12. **Verified; no inflation.**

---

## 9. RECONCILED RANKING (reviewer's; not a selection)

| Rank | Card | Role in reconciled view |
|---|---|---|
| 1 | **H10** | Best form + mirage + contamination; formula favorite; independent favorite |
| 2 | **H9** | Best cheap §12(a) probe; slate recommendation; highest H8-adjacency risk (§6) |
| 3 | **H11** | Hold for reformalization (G16 `scheduled_flow_window` + clock predicate) before any confirmation path |

I do **not** select. Lei decides.

---

## 10. QUESTIONS FOR LEI

1. **Override class.** Do you treat the H9-over-H10 override as a
   binding program priority (answer §12(a) cheapest first), or do you
   want the independent/formula order (certified conditioner first)
   given H9's explicit adjacency to the H8 magnitude kill?

2. **H11 reformalization bar.** Is H11's FAIL on
   `SCHEDULED_FLOW` without `scheduled_flow_window` (and without a
   clock predicate in the conditional) a confirmation blocker
   requiring a rewritten card before any Task 7 path, or an
   acceptable drafting debt?

3. **Tranche-1B vs H11 D.** With {OLN, DIOD, PCTY, CROX} now at 20
   sessions and median-open at H = 1800 honest κ (pack-08 §2.4 / §5),
   should any confirmed 1800 card pre-register a backlog-16
   disposition for those four as deployable or evidence-only — or
   stay frozen on {APP, RMBS} only for the first census?

---

## DECISION RECORD (Lei, 2026-07-15 — append-only)

Rulings on §10:

1. **Override class — REJECTED.** Independent/formula order governs
   (certified conditioner first): **H10 CONFIRMED**. H9-over-H10
   override is not binding program priority. Information-value
   rationale: certified-print conditioner adjudicates both siblings;
   OFI's does not; H9-first risks an ambiguous kill forcing both
   trials.

2. **H11 reformalization bar — confirmation blocker.** H11 is
   **NOT SELECTED** (design-gate failure: G16 rule-5;
   Reformalization residue). Revival = full re-derivation as a new
   card.

3. **Evidence scope — stay frozen on {APP, RMBS}.** Tranche-1B cells
   carry **no role** in H10's evidence. (H11's 1800-scope question is
   moot while H11 remains NOT SELECTED.)

**H9** held as **CONTINGENT SECOND CARD** (revivable for its own
census/protocol iff H10 passes step 2; presumptively dead on H10
step-2b magnitude fail). **SEQUENCING:** backlog-14 invoked
pre-outcome for H10 — Phase A (SFI sensor + census instrument +
harness IC row) before census/step 2; Phase B (full card) gates on
step-2 PASS. Full record: `prompt_pack_09_hypothesis_slate_c.md`
DISPOSITIONS + SEQUENCING RULING. **N = 11 unchanged** (no outcome
contact).
