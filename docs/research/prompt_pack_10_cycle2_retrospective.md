<!--
  File:   docs/research/prompt_pack_10_cycle2_retrospective.md
  Status: DECIDED (2026-07-16, Lei) — cycle-2 retrospective accepted;
          §5 Interpretation B adjudicated as overstated by one region;
          CYCLE 3 AUTHORIZED (SCHEDULED_FLOW H∈{900,1800} only) with
          PROGRAM STOP-RULE pre-registered (see DISPOSITION below).
          N = 12 unchanged (authorization / stop-rule only; no outcome
          contact). Body §§1–6 unedited (append-only).
  Owner:  research-workflow (program bookkeeping); prompt-pack Task 7-R2,
          Phase B.

  Provenance (FQ-3 template):
    git_sha: "9026be23c9f559f20595f8ed87026912d2aee15e" (HEAD at task
      start = the H10 close-out commit; this file plus the item-2
      backlog appends are the only outputs)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (synthesis only; every number below is quoted from committed
      records)"
    normative_inputs: prompt_pack_07_program_retrospective.md,
      prompt_pack_08_frontier_refresh.md,
      prompt_pack_09_hypothesis_slate_c.md (+ DISPOSITIONS 1–9 +
      SEQUENCING RULING), prompt_pack_09a_slate_c_review.md,
      artifacts/h9_h10_adjudication_package.md,
      prompt_pack_03c_universe_and_cache.md (+ AMENDMENT 2),
      prompt_pack_03m_skill_verification.md,
      prompt_pack_backlog.md (entries 12–16 LANDED),
      sig_sweep_kyle_drift_h900_v1_{formal_spec,validation_protocol,
      result}.md, sig_dislocation_lambda_drift_v1_{formal_spec,
      result}.md, prompt_pack_12p_router_fill_timing_parity.md.
-->

# Task 7-R2 — Program retrospective: alpha program cycle 2 (slate C)

Scope: the full committed record of cycle 2 — slate C (H9–H11 + S-1
seed, pre-registered 2026-07-15), the H10 Ordering-B validation
sequence (`sig_sweep_kyle_drift_h900_v1`: census PROCEED → step 2a
PASS → step 2b REJECTED), the H9 contingent adjudication, and the
Phase-A / 3-M machinery that adjudicated them. Trial ledger at close:
**N = 12** (§6). Zero candidates survive cycle 2. Cycle 1 closed at
N = 11 with zero survivors (`prompt_pack_07_program_retrospective.md`
§9).

---

## 1. CYCLE-2 FUNNEL

Every card / seed from slate C. "N" = multiple-testing increments
consumed by that card's kill (FQ-6B-R: data contact increments;
drafting and design exclusion do not). Cost figures cite commit
anchors; shared slate/dossier commits are marked (shared).

| card | gate reached | verdict (date) | deciding arithmetic / statistic | approx. cost to kill | N | marginal lesson |
|---|---|---|---|---|---|---|
| S-1 baseline-λ reversion seed | design cost-floor pre-filter | **EVALUATED-AND-EXCLUDED** (2026-07-15; pack-09 SEED; 09a §1 CONFIRM) | honest κ_rev views (A) ≈ **2.99 bps** / (B) ≈ **3.94 bps** both < APP floor **4.68**; κ_req med 0.138 > κ_rev (pack-09 SEED; 09a §1) | shared slate/dossier commits only; N-impact 0 | 0 | contaminated magnitude near the floor is not a card — face |edge| inside the floor band dies at the hard pre-filter before disjointness / N≥12 questions arise |
| H9 `sig_ofi_kyle_drift_h900_v1` | contingent second-card adjudication (never censused) | **NOT SELECTED → ADJUDICATED presumptive death** (2026-07-16; DISPOSITIONS 2, 7–8) | H10 failed step 2b on **p + F2**, not magnitude — literal magnitude-trigger for presumptive death **did not fire**; death ruled on sibling arithmetic + shared-archetype F2 refutation (DISPOSITIONS 7) | shared slate/adjudication only; no H9 census / no outcome contact | 0 | conditionals must enumerate failure **modes**, not a single "fails" path — see §2.3 / backlog 17 |
| H10 `sig_sweep_kyle_drift_h900_v1` | **protocol step 2b** (RankIC gate) — after: Phase A (sensor + census + harness), census PROCEED n=152 (`2c45b6f`), step 2a PASS 7/7, Ordering B harness path | **REJECTED** (2026-07-16; S.8 / result; close-out `9026be2`) | magnitude **PASSED** (+0.0893 ≥ 0.03); significance **FAILED** (Fisher-z **p 0.288 > 0.01**; n≈680 needed vs 144 realized — no legal pool rescue); **F2 FAILED** (λ contrast −0.014; volume −19,407) — KYLE attribution refuted; §9 "2b IC gate" REJECTED; F2 governs substance (protocol S.4/S.8; result §7/§10) | Phase A path ~7 instrument/evidence commits (`faeafaa`…`0ce3d9e`) + protocol freeze + close-out; **Phase B never built** (SEQUENCING RULING; result §8) | **+1** | positive-but-unproven drift with a **refuted** mechanism tie is a terminal reject, not a park; magnitude clearing does not rescue F2 / p failures (S.8) |
| H11 `sig_halfhour_clock_drift_v1` | design review (G16 / form) | **NOT SELECTED** (2026-07-15; DISPOSITIONS 3) | G16 rule-5 FAIL: declares `SCHEDULED_FLOW` but `l1_signature_sensors: [ofi_ewma]`; no clock-window predicate — unreformalized residue (09a §2 H11 check a; §7/§9) | shared slate/dossier only | 0 | family diversification without the family's load-bearing instrument is a form kill before economics — revival is H11′-class re-derivation, not a patch (DISPOSITIONS 3, 8) |

**The funnel fact, explicit:** cycle 2 traversed design exclusion
(S-1 cost; H11 form), contingent sibling death (H9), and a full
Ordering-B step-2 reject (H10: magnitude clear, significance + F2
fail). Zero cards past step 2. Combined with cycle 1
(pack-07 §1): **two cycles, kill chain fired at every gate class that
was reached, zero cards past step 2.**

### 1.1 Phased-ordering payoff (H10 Ordering B vs H8 Ordering A)

| quantity | H8 (Ordering A) | H10 (Ordering B) | citation |
|---|---|---|---|
| YAML / deployable-card investment before step 2b | **8 implementation commits** sunk (Tasks 9–10) | **0** — Phase B gated on PASS; never authorized | pack-07 §3; pack-09 SEQUENCING RULING; result §8 |
| Binding 2b statistic path | standalone extract/stats (YAML not executed for IC) | same class — harness extract/stats on census-pinned predicate | pack-07 §3; protocol S.2 |
| Census / power gates run before IC | primary PARK → variant PARK → expanded PROCEED (135 APP) | **one** census PROCEED (pooled 152) | pack-07 §1 H8 row; protocol C.5–C.6 |
| Step 2a | loader-compiled `evaluate` goldens 7/7 | harness sign-goldens 7/7 (Phase-B evaluate goldens deferred) | H8 result; protocol S.3 |
| Step 2b reached? | yes — REJECTED (magnitude) | yes — REJECTED (p + F2; magnitude PASSED) | H8 S.8; H10 S.8 |
| Artifacts produced for the kill | expanded census + YAML + extract/stats evidence set | Phase-A sensor/census/harness + census JSON + extract/stats | pack-07 §9; H10 S.7 / result provenance |
| Stated savings class | — | "~8 commits per step-2 death" (retrospective §3 tradeoff, invoked pre-outcome) | pack-09 SEQUENCING RULING |

**Payoff realized:** H10 died at the same protocol stage as H8
(step 2b) **without** sinking the YAML/test/config/parity surface
that H8 paid. The integrity price named at freeze (2a/2b inversion;
two-object drift; D-1-class defects post-IC) was accepted
pre-outcome; Phase B proof obligations were never discharged because
PASS never occurred (SEQUENCING RULING; result §8).

### 1.2 Design-margin validation (realized vs design vs H8)

| card | design-central projection | realized census episodes | margin bar | outcome |
|---|---|---|---|---|
| H10 | **146.2** pooled (1000 × HT0.90 × 0.20 × gw × ISO0.95) | **152** pooled viable-region primary (APP 94 / RMBS 58) | design ≥ **130**; census floor ≥ **100** | design margin **held**; realized **above** design-central (C.5; pack-09 H10 · 2; 09a §2) |
| H8 (contrast) | ≈ **147** APP / ≈ **111** RMBS (joint occupancy prior 0.226) | including-flagged **81 / 77** on 10-session grid (primary 73 / 58) — power PARK until expansion lifted APP to 135 | ≥ 100 | design **missed badly** (81 ≪ 147); occupancy shortfall was "the entire power shortfall" | pack-06 H8 block-2; H8 formal-spec incidental count; pack-07 §2.2 item 5; protocol C.5 |

**Validation:** the cycle-2 ≥ 130 design margin + percentile-tail
(exempt) conditioning + measured ISO-warm replacement (JC-10: asserted
0.95 → measured **1.000**) produced a census that cleared the floor
**without** a grid expansion. H8's 81/147 pattern did not recur on
H10's percentile-decile construction (protocol C.4–C.6).

---

## 2. MACHINERY DELTAS

### 2.1 What the 3-M conventions changed in practice

Landed Task 3-M (2026-07-15; backlog 12–16; `prompt_pack_03m_skill_verification.md`
all five probes PASS). Cycle-2 consumption:

**(a) n-variant labeling — read directly off the 2b table.**
H10 protocol §2.2 / S.4 scored each conjunct with an explicit
`n-class` column. The binding decomposition is readable without
post-outcome derivation:

| criterion (S.4 / S.8) | n-class | observed | role in kill |
|---|---|---|---|
| \|RankIC\| ≥ 0.03 / sign > 0 | **n-invariant** | +0.0893 | PASSED — not the kill |
| Fisher-z p ≤ 0.01 | **n-variant** | 0.288 | FAILED — no legal rescue inside frozen pool |
| F2 λ / volume co-travel | mechanism | both absent / negative | FAILED — governing substance |
| conditional-tail t ≥ 2 | sign n-inv; t n-var | t 0.82 | FAILED — reinforces §9 row 2b |

Contrast: H8's S.8 had to *derive* magnitude-vs-power after the fact
(pack-07 §2.2 miss 1 / backlog 12 incident). Cycle 2 did not repeat
that adjudication gap on the primary table.

**(b) Precedence walk — executed as written.**
Frozen §9.1 intersections applied at S.5 without a new mid-flight
ruling: F2 fail ∩ RankIC magnitude/sign PASS → **REJECTED (F2)**;
p and tail-t reinforce the same §9 row; JC-5 not applied (acts only
on PASS). No §9-vs-safeguard collision of the H8 S.5 class
(pack-07 §2.2 miss 1). Citation: protocol S.5 / S.8; backlog 13
LANDED.

**(c) Occupancy pre-reads.**
- H9/H10/H11 percentile tails: **exempt** by construction (pack-09
  §0 / H9 · 2; backlog 15).
- H10 ISO-warm 0.95: **non-exempt** ASSERTED prior inside the density
  headline — dossier CONCERN (09a H10 check d); freeze required
  census measurement + park-on-power if warm-drop fires (spec
  deviation row; JC-10). Census measured warm **1.000** on both
  symbols; warm-drop did not fire; measured warm replaced the prior
  for power scoring (protocol C.4). The 3-M rule converted a
  selection-headline defect into a pre-registered measurement
  obligation rather than a silent assumption.

### 2.2 JC-1 estimand conflation and fix

**Incident (census C.3):** `residual_non_a_share > 1 %` fired on
**40/40** {APP, RMBS} cells with episodes (mean share ≈ 0.62–0.80).
A naive reading of §1.3 / JC-1 "near-zero by construction" would have
treated this as sensor leakage.

**Investigation (closed before step 2):** the instrument field
measures share of *all* trailing-900 s tape prints failing Class-A ∩
id-14 — i.e. ≈ 1 − ISO-eligible share on a mixed tape — **tape
co-travel**, large by construction. The sensor does not ingest those
prints (filter goldens + pin). Citation: protocol C.3.

**Fix (A-2, append-only, pre-statistic):** two estimands distinguished
and never conflated (protocol A-2):

| estimand | expected on real L1 | JC-1 >1 % investigation |
|---|---|---|
| **Sensor-state leakage** | 0 by construction | YES — attaches here only |
| **Tape co-travel share** | natural, large (observed ≈ 62–80 %) | NO — composition diagnostic only; never park / never power deflator |

No sensor-code change; no freeze-body edit; step 2 proceeded on the
clarified reading. **Lesson:** REPORTS diagnostics must name the
estimand at freeze, or a large-by-construction quantity will look
like a bug under the wrong label. → backlog entry 18.

### 2.3 H9-conditional trigger gap — new lesson

**Pre-registered trigger (DISPOSITIONS 2):** H9 revivable iff H10
passes step 2; **presumptively dead if H10 fails step 2b on
magnitude**.

**What happened (DISPOSITIONS 6–7):** H10 failed step 2b on
**significance + F2**; magnitude **cleared** (+0.089 ≥ 0.03). The
literal magnitude-trigger for presumptive death **did not fire**.

**Adjudication:** presumptive death ruled anyway on (i) sibling
arithmetic (certified-print conditioner was the slate's adjudicating
trial for the shared KYLE × H=900 × {APP,RMBS} claim) and
(ii) shared-archetype F2 refutation (same λ / volume fingerprint).
Extraordinary-justification bar restated (DISPOSITIONS 8).

**Lesson (program-level):** conditionals that say "if X fails" without
enumerating failure **modes** (magnitude / significance / mechanism /
form / power) create a trigger gap exactly when the interesting
mixed outcome occurs — here, positive-but-unproven drift with a
refuted mechanism tie. Pre-registration that lists only one mode
forces post-outcome substance adjudication of the kind
pre-registration exists to remove. → backlog entry 17.

### 2.4 Skill-edit candidates (proposals only — backlog appends; NO skill edited)

Appended to `docs/research/prompt_pack_backlog.md` as entries **17–18**
for a future Task-3-style maintenance pass:

- **(17) Contingent-card triggers must enumerate failure modes.**
  Incident: pack-09 DISPOSITIONS 2 vs 6–7 (magnitude-trigger gap;
  presumptive death ruled on sibling/F2 grounds outside the literal
  trigger).
- **(18) Contamination REPORTS estimands labeled at freeze.**
  Incident: H10 JC-1 / C.3 / A-2 (tape co-travel vs sensor-state
  leakage conflation).

---

## 3. MECHANISM SYNTHESIS — F2-NEGATIVE AT H=900 ON CERTIFIED SWEEPS

**The program's most valuable cycle-2 fact** (protocol S.8; result
§10): among primary eligible extreme-SFI episodes on the frozen
{APP, RMBS} × 20-session grid at H = 900, the KYLE fingerprint
required by F2 — `kyle_lambda_60s` percentile elevation **or**
same-direction print-volume elevation versus baseline — was
**absent** (contrasts −0.014 and −19,407). The card's pooled RankIC
was positive and cleared the magnitude floor (+0.0893 ≥ 0.03), yet
the informed-flow attribution did not attach. Scope precision binds:
what is rejected is the extreme-SFI continuation claim **with KYLE
attribution via that F2** on this evidence set — not a claim that
"|RankIC| failed" (S.8).

### 3.1 What is now evidence-backed about informed-flow-following

| horizon / conditioner | magnitude vs \|RankIC\| ≥ 0.03 | F2 / mechanism tie | status of tradable KYLE claim |
|---|---|---|---|
| H = 300, dislocation × elevated-λ (H8) | **FAILED** (+0.0186 < 0.03) | λ-contrast / separation **PASSED** (baseline reverts; F2-class tie held) | elevated-λ **continuation** rejected; λ-separation **not** refuted (pack-07 §5; H8 result S.8) |
| H = 900, certified ISO / extreme-SFI (H10) | **PASSED** (+0.0893 ≥ 0.03; ~5× H8's realization) | λ / volume co-travel **FAILED** (both absent) | continuation sign present-but-unproven (p 0.288); **KYLE attribution refuted in-sample** (H10 S.8) |

Honest synthesis (no recommendation):

1. **H = 300 magnitude sub-bar** on the tested elevated-λ continuation
   claim remains evidence-backed (H8; n-invariant; pack-07 §5).
2. **H = 900 magnitude can clear the floor** on a certified-sweep
   conditioner in this sample — and still fail institutional proof
   bars (significance + mechanism). Magnitude clearance alone is not
   a KYLE edge (H10 S.8 / result §10).
3. **The Kyle fingerprint was absent in H10 sweep windows.** Any
   narrative that equates "ISO extremes ⇒ informed flow ⇒ permanent
   impact remainder" must confront that absence on this universe/grid
   before treating KYLE_INFO as load-bearing at H = 900.

### 3.2 Implication for every KYLE_INFO cell still marked open on pack-08

Pack-08 §2.4 still marks **passive KYLE_INFO / SCHEDULED_FLOW** open
at central κ on H ∈ {900, 1800} for {APP, RMBS} (and broader open
regions at the 0.30 ceiling). That map is a **κ / cost / density
pre-filter**, not a mechanism confirmation
(`prompt_pack_08_frontier_refresh.md` §2.4 / §6; census-legal, N
unchanged by the map).

Cycle-2 updates the interpretation of those open cells:

- **Economics-open ≠ mechanism-open.** H10 cleared design park
  arithmetic and census power on an open H = 900 cell, then failed
  F2. Remaining open KYLE_INFO cells inherit that caution: a future
  card that reuses the same λ / volume fingerprint as its KYLE lock
  faces an in-sample refutation of that fingerprint under certified
  ISO extremes (DISPOSITIONS 7–8; extraordinary-justification bar for
  H9-class revival).
- **H9-class quote-OFI at H = 900** is not authorized; revival
  requires a mechanism distinguisher explaining why quote-OFI extremes
  would carry KYLE attribution when certified-ISO extremes did not
  (DISPOSITIONS 8) — plus fresh evidence and +1 N.
- **Open map cells remain legally draftable** under pack-08 §6 if a
  card's own κ and density clear — but they are no longer
  "untested-unknown" in the weak sense: the strongest available
  conditioner at H = 900 on this deployable set was tested and the
  KYLE tie failed. Untested conditioners / horizons / families are
  still open as **distinct claims**, not as free retries of the
  refuted attribution.

---

## 4. OPPORTUNITY SET, UPDATED

Two closure classes (same convention as pack-07 §5):
**closed-by-rejection** vs **closed-by-precondition**.

### 4.1 KNOWN-CLOSED (with citations)

*From cycle 1 (unchanged scope precision — pack-07 §5):*

- Elevated-λ continuation at H = 300, passive, on {APP, RMBS} —
  closed-by-rejection (H8 S.4/S.8, `3b039f3`). λ-separation not
  refuted.
- Inventory-fade H = 120 passive — closed-by-precondition (H2 park,
  `642d12d`).
- H = 30 anything; taker at design on most cells; INVENTORY/HAWKES at
  honest κ; micro-price level-drift design kill — closed-by-precondition
  (pack-08 §3 HOLD).
- H1-class taker sweep at stated edges — design (04a check d).

*Added by cycle 2:*

- Extreme-SFI / certified-ISO continuation at **H = 900**, passive,
  pooled {APP, RMBS}, with KYLE attribution via F2 — **closed-by-rejection**
  (H10 S.8, `9026be2`; result §11). Magnitude bar did **not** kill;
  p + F2 did.
- H9 contingent OFI × H = 900 KYLE sibling — **closed for program
  purposes** pending extraordinary justification (DISPOSITIONS 7–8);
  never censused (N-impact 0). Not a statistical rejection of
  quote-OFI continuation; a slate-level presumptive death after the
  adjudicating sibling failed F2.
- S-1 baseline-λ reversion seed — **closed-by-precondition** at the
  cost-floor hard pre-filter (pack-09 SEED; 09a §1 CONFIRM). Thread
  closed at design (N-impact 0).
- H11 as drafted — **closed-by-precondition** (G16 / form FAIL; NOT
  SELECTED). Economics/density were not the kill (09a §7).

### 4.2 Still-open

| region | status | citation / constraint |
|---|---|---|
| **SCHEDULED_FLOW at H ∈ {900, 1800}** via **H11′-class reformalization** | open as a *new* card path | must carry `scheduled_flow_window` (G16 rule-5) + a real clock-window predicate; not a patch of drafted H11 (DISPOSITIONS 3, 8; 09a §2 H11) |
| **H = 1800 pooled designs on the 140-cell cache** | density-open under pooling | pack-08 §4 (per-symbol still < 100); 03c AMENDMENT 2 = **140** ingested cells; 09a §2 actuals confirm 25/12 per session. Soft σ₁₈₀₀ (12 returns/session) remains |
| **Universe tranche 2** (higher-σ midcaps) | REGISTERED, never screened | backlog 11; pack-07 fork ii |
| **Paused H4 program** (calendar-event grid) | DEPRIORITIZED | backlog 8; taker closed at H = 900 median on map |
| **Vendor-gated extensions** | OPEN blockers | V-1 caps new draws pre-2026-04-27; V-2 blocks RESEARCH→PAPER; V-3 low stakes (pack-07 §6) |

KYLE_INFO map-open cells at H ≥ 900: still κ-open on pack-08, but
see §3.2 — mechanism caution after H10 F2 miss. No H ≥ 900 KYLE card
is authorized by this retrospective.

### 4.3 Contaminated-seeds shelf

| seed | source | constraints | status |
|---|---|---|---|
| H8 baseline-λ dislocation reversion (−5.43 bps, t −2.50) | H8 result POST-HOC | fresh sessions; honest-N; **cost-excluded as S-1** on this structure | shelf + design-closed on cost (pack-09 SEED) |
| H10 RMBS per-symbol RankIC +0.226 (n=55, p=0.097) | H10 result POST-HOC | fresh sessions; N ≥ 13 at first contact; non-governing diagnostic | shelf only (result POST-HOC 1) |
| H = 300 → H = 900 magnitude comparison (0.0186 → 0.089) | H10 result POST-HOC 2 | both sub-proof; seed only; not a prior | shelf only |

---

## 5. THE PROGRAM-LEVEL QUESTION (for Lei — no recommendation)

**Fact pattern (cited):** two cycles; kill chain fired at every gate
reached; zero cards past step 2 (pack-07 §1; this doc §1). Strongest
available conditioner at the open H = 900 frontier (certified ISO /
extreme-SFI) showed **positive RankIC that cleared magnitude** with
**significance fail** and **F2 mechanism tie refuted** (H10 S.8).

Three honest interpretations — each implies a different continuation
posture. None is selected here.

### Interpretation A — Edges exist below institutional proof bars at this data scale

*Reading:* H10's +0.089 RankIC and interior/bucket structure are real
weak continuation; the frozen p ≤ 0.01 / n≈144 cell and the F2
fingerprint are miscalibrated or underpowered for this universe's
effect sizes; more commensurate evidence (or recalibrated bars in a
**new** pre-registered protocol) could promote a weaker but real
edge.

*Implies about continuing:* invest in power / bar-calibration
research (new trials, honest N), not in declaring the cell closed.
Cost-to-information: **high N burn** — each new outcome contact is
+1; significance rescue at RankIC ≈ 0.09 needs n ≈ 680 inside a
frozen pool that held 144 (S.8) — roughly a **new** multi-grid
program, not a free expansion of the dead trial.

### Interpretation B — The universe–cost cell is closed for tradable KYLE continuation

*Reading:* pack-08 opens the κ door; two independent KYLE-continuation
tests (H8 magnitude death at 300; H10 F2 death at 900 with magnitude
clear) say the tradable informed-flow-following claim does not clear
institutional bars on this midcap / passive / L1-only cell. Map-open
is not edge-open.

*Implies about continuing:* stop drafting KYLE_INFO continuation cards
on this grid; burn vendor/engineering backlog or move to a different
universe / family. Cost-to-information: **low on new KYLE trials**
(avoids further N burn on a refuted attribution class); **information
gain shifts** to tranche-2 / SCHEDULED_FLOW reformalization / pause —
each is a different experiment, not a retry.

### Interpretation C — Remaining open regions are worth N more cycles

*Reading:* H11′-class SCHEDULED_FLOW (clock instrument real), H = 1800
pooled designs on the 140-cell cache, tranche 2, and (separately)
vendor-unlocked fresh draws remain untested as **distinct claims**.
H10 closed one conditioner × one horizon × one attribution lock — not
the entire opportunity set (§4.2).

*Implies about continuing:* sequence the cheapest distinct claim
(reformalized SCHEDULED_FLOW or pooled 1800) before expensive new-data
forks; carry honest N (≥ 12; first contact +1). Cost-to-information
(order-of-magnitude from pack-07 §8 updated by cycle-2 cache state):

| fork | est. cost to first census-grade verdict | what a kill would teach |
|---|---|---|
| H11′ SCHEDULED_FLOW reformalization on 140-cell cache | slate + review + spec/protocol/census on existing cache (~5–8 commits class; no new ingest if D ⊆ cached symbols) | whether clock-aligned scheduled flow clears form **and** F1/F2 where KYLE ISO did not |
| H = 1800 pooled KYLE/SCHED design | similar census cost; soft-σ caveat binds | whether longer horizon changes magnitude/attribution vs H10 |
| Tranche 2 (higher-σ midcaps) | screen + cache + map before any card (highest) | universe-limited vs mechanism-limited (pack-07 fork ii) |
| Pause / vendor burn-down (V-1/V-2) | no census verdict; calendar cost only | unblocks fresh-session programs later; teaches nothing about the opportunity set now |

**QUESTIONS FOR LEI (the fork turns on these — still no recommendation):**

1. Do you read H10's F2 miss as closing KYLE continuation attribution
   on this grid (Interpretation B), or as conditioner-specific
   (ISO vs other locks still live under C)?
2. Is H11′-class SCHEDULED_FLOW reformalization the next distinct claim
   worth a cycle, given H11's form FAIL was the only slate-C card that
   died before economics?
3. Does Interpretation A authorize any bar-recalibration discussion
   only as a **new** pre-registered protocol (never a post-hoc loosen
   of H10's frozen p / F2 bars)?

---

## 6. LEDGER CLOSE

**N accounting (final N = 12; every increment cited):**

- **N = 10** initialized at slate-A pre-registration (pack-04 §(3);
  pack-07 §9).
- **+1 → N = 11** at H8 step-2b first outcome contact (2026-07-14;
  pack-07 §9; H8 result §11).
- **Unchanged through:** cycle-1 retrospective (`bd35cac`); Task 3-M
  skill landing (`e120140`); FQ-9 map (`08666f5`, N = 11 unchanged);
  TRANCHE-1B ingest (`eb416bc`, data augmentation); slate C drafting
  + review + selection (pack-09 §(3) / DISPOSITIONS 5 — N = 11); H10
  protocol freeze; Phase A implementation; H10 census PROCEED
  (protocol C.8 — census-class, N = 11); A-2 JC-1 clarification
  (pre-statistic).
- **+1 → N = 12** at H10 step-2 first outcome contact (2026-07-16;
  protocol S.6; pack-09 ledger update; DISPOSITIONS 9; result §11).
- **N = 12 confirmed.** Zero exploratory variants evaluated in
  Task 11-A-H10. Spec §13 / other drafted rows remain N-impact 0 and
  are **not** authorized by the close-out. Any future DSR uses
  living N ≥ 12; any future evaluation of any drafted row is +1 N
  under its own protocol from step 1.

**Evidence artifacts committed** (FQ-3 provenance in citing records):

- `artifacts/horizon_feasibility_map_operative_2026-07-15.json`
  (sha256 d549a92a…, pack-08 §7).
- `artifacts/sweep_kyle_drift_census_2026-07-16.json` (sha256
  a2f49e6b…, protocol C.8 / S.7).
- `artifacts/sig_sweep_kyle_drift_h900_v1/` —
  `boundaries_extract_2026-07-16.json` (sha256 522e0ff1…),
  `validation_stats_2026-07-16.json` (sha256 4735b20a…) — bit-identical
  re-runs recorded (S.7 / result provenance).
- Cycle-1 artifacts remain as listed in pack-07 §9 (H2/H8 censuses,
  H8 evidence set, universe-draw evidence, etc.).
- Instrument / sensor commits on the H10 Phase-A path:
  `sweep_flow_imbalance` sensor (`faeafaa`),
  `scripts/research/sweep_kyle_drift_census.py` (`19adcfd`),
  harness IC row (`8b8932f`), validation extract/stats (Task 11-A-H10
  / `0ce3d9e`), ownership rows in `docs/prompts/README.md`.

**No uncommitted program state at task start.** Verified at HEAD
`9026be2`: `git status --porcelain` empty. This retrospective plus
the backlog 17–18 appends are the only outputs of Task 7-R2.

*Task 7-R2 body (§§1–6) stopped at AWAITING-LEI-REVIEW. Disposition
appended below (Lei, 2026-07-16).*

---

## DISPOSITION (Cycle 3 authorization + program stop-rule — Lei, 2026-07-16; pre-outcome; §§1–6 unedited)

1. **§5 ADJUDICATED.** Of the three honest readings in §5,
   **Interpretation B** ("the universe–cost cell is closed for
   tradable KYLE continuation") is accepted as the governing posture
   for KYLE_INFO continuation on this grid, but is **overstated by
   one region**. **SCHEDULED_FLOW at H ∈ {900, 1800}** remains
   **map-open at honest κ** (`prompt_pack_08_frontier_refresh.md`
   §2.4 / §6) and has **zero evidence contact** in cycles 1–2:
   drafted H11 died on **form** (G16 rule-5; DISPOSITIONS 3 / §4.1),
   not economics; H4's park was **infrastructure + taker economics**
   and **close-window-specific** (pack-07 §1; backlog 8) — it does
   not adjudicate clock-aligned scheduled-flow claims at H ∈
   {900, 1800}. **Cycle 3 is AUTHORIZED, scoped to that region
   only** (H11′-class reformalization / distinct SCHEDULED_FLOW
   cards at H ∈ {900, 1800} on the existing universe/grid). No
   KYLE_INFO continuation card, no H = 1800 KYLE retry, and no
   other §4.2 fork is authorized by this disposition.

2. **PROGRAM STOP-RULE (pre-registered now; no cycle-3 outcome
   exists).** Cycle 3 is the **FINAL cycle** on this universe/grid.
   **Absent a step-2b PASS by any cycle-3 card, the program
   closes.** The residual fork named in §4.2 / pack-07 (universe
   **tranche 2** vs stop) is a **new capital decision** requiring
   its own Lei authorization — it is **not** a continuation of
   cycle 3 and is not pre-authorized here. **Kill-gate class does
   not matter for closure:** census parks, design exclusions, and
   step-2b rejections **all count** toward program closure under
   this stop-rule. Pre-registration timestamp: this disposition
   (2026-07-16), before any cycle-3 slate, census, or outcome
   statistic.

3. **OUTCOME-INFORMED PRIOR DISCLOSURE.** The H = 300 → H = 900
   magnitude comparison (H8 RankIC +0.0186 → H10 RankIC +0.0893;
   §3.1 / §4.3 POST-HOC shelf) is recorded as a **post-hoc,
   in-sample design prior** usable only for **horizon selection**
   discussion inside cycle-3 drafting. Wherever it is used it must
   be **disclosed as such**. It is **never evidence**, never a
   magnitude bar substitute, and never a KYLE or SCHEDULED_FLOW
   proof claim.

4. **Backlog / vendor sequencing.** Backlog entries **17–18**
   (contingent-trigger failure-mode enumeration; contamination
   REPORTS estimand labeling — §2.4) land via the next
   **3-M-style maintenance pass**; that pass **may ride with
   cycle-3 doc commits**. **Vendor tickets (V-1 / V-2 / V-3)
   remain decoupled:** neither gates cycle 3 (operative grid is
   pre-April; no RESEARCH→PAPER promotion is imminent).

5. **N = 12 confirmed.** This disposition is authorization +
   stop-rule pre-registration only — **no data contact, no
   outcome statistic, no N increment.** Living ledger remains
   **N = 12** (§6). Any cycle-3 card's first outcome contact is
   **+1 → N ≥ 13** under its own frozen protocol from step 1.
   Any future DSR uses the then-current living N (≥ 12).
