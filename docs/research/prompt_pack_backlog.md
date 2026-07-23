<!--
  File:   docs/research/prompt_pack_backlog.md
  Status: LIVING — consolidated register of separate-thread candidates
          spun out of the prompt pack (Tasks FQ-0…FQ-4, 2, 3). Entries
          are pointers to their authoritative specs, not re-specs.
          Created 2026-07-08 (Task 3 prefix, addition (b)).
          + entry 19 (2026-07-17): occupancy pre-reads MANDATORY for
          every non-percentile conditioning arm (H12 census lesson).
          + entry 20 (2026-07-18): arm-specific occupancy must be
          MEASURED on the target window geometry; cross-card f_resid
          transfer is an unvalidated prior (H13 / 8-C-H13; extends 19).
          + PROGRAM-CLOSED stamp (2026-07-18, Task 7-R3): alpha
          program on this universe/grid closed; entries 1–20 remain
          the handoff inventory (see prompt_pack_12_final_retrospective.md).
          + CAPITAL-FORK-CLOSED stamp (2026-07-18): pack-13 NO-GO;
          standing state PAUSE-AND-HARVEST; harvest inventory owned.
          + entries 21–25 (2026-07-20): pack-15 §8 machinery gaps
          (grammar × machine universe doctrine); additive/core class
          carried; PAUSE-AND-HARVEST unchanged.
  Owner:  cross-cutting; prompt-pack Phase A bookkeeping.
-->

# Prompt-pack backlog — separate-thread candidates

Platform threads identified during the pack but explicitly NOT part
of its alpha delivery (the four separate-thread candidates from the
Task-3 prefix, plus the link-check extension deferred by Task-3
addition (a)). Each entry points at the existing spec; scheduling,
ownership, and parity-impact assessment happen in the thread, not
here.

## 1. OQ-3 — Mechanism-cap runtime closure (PORTFOLIO layer)

G16 PORTFOLIO rule 8 validates `trend_mechanism.consumes[*].
max_share_of_gross` at load time, but bootstrap wires
`CrossSectionalRanker` with `mechanism_max_share_of_gross=1.0`, so
runtime enforcement of alpha-declared caps is disabled. Accepted risk
for this pack (SIGNAL-layer delivery; the gap bites only multi-alpha
PORTFOLIO deployment), with the standing obligation that every
capacity/crowding claim carries the not-active caveat. The thread
closes the gap by passing declared caps through bootstrap to the
ranker, with its own tests and a parity-impact assessment. Spec:
`docs/research/prompt_pack_00_architecture_verification.md` §(e)
OQ-3 row; code anchors in the composition-layer skill's
`CrossSectionalRanker` "Known gap" note
(`src/feelies/composition/cross_sectional.py`, `bootstrap.py`).

## 2. OQ-1 — `Signal.strength` engine-level enforcement (00e Track B)

`strength ∈ [0,1]` is a documented-but-unenforced contract (drift
D10), violated by design in shipped alphas (`sig_benign_midcap_v1`
convex scaling, cap 2.0) and baked into the locked
`reference_alpha_signal_fires` parity hash — so an engine clamp is a
known parity-breaking change requiring the mandatory assessment and a
(re-pin + alpha version bump) vs (contract amendment) decision.
Pre-registered semantics (NaN/negative drop, >1 clamp, FLAT kept at
0.0) and enforcement point (`HorizonSignalEngine` post-evaluate) are
fully specified. Spec:
`docs/research/prompt_pack_00e_strength_rider_and_thread.md`
Track B (PROPOSED; not a dependency of any pack task).

## 3. OQ-5 — Parity-manifest host/libm fingerprint FOLLOW-UP

Locked parity hashes are bit-identical only per (platform, libm)
pair; the manifest's own FOLLOW-UP (per-baseline host/libm
provenance) is unimplemented. The thread adds a provenance sidecar
(never a baseline-value change; `EXPECTED_MANIFEST_FINGERPRINT`
byte-identical before/after) plus two caveat-list corrections (add
`ofi_ewma`; annotate `liquidity_stress_score` as unexercised). Spec:
`docs/research/prompt_pack_00d_reproducibility_policy.md` §4; code
anchor `tests/determinism/parity_manifest.py` (FOLLOW-UP note in its
module docstring).

## 4. Extend internal-link checking to `.cursor/skills/**/*.md` — DONE

Landed in Task 3a (2026-07-08) as a pure `_DOC_FILES` data addition
(`tests/docs/test_internal_links.py`): one `rglob` line covering
`.cursor/skills/**/*.md`. The two blockers from the first attempt
(Task 3) were resolved first: the composition-layer `SKILL.md`
`loadings_dir/loadings.json` illustration was reworded so it no
longer parses as a checkable path, and the uncommitted deletion of
`docs/acceptance/v02_v03_matrix.md` was restored from HEAD (worktree
drift, disposition: restore). No checker-logic changes were needed.

## 5. Platform-wide session-admissibility guard (unknown ids + units sanity)

Task FQ-5A (2026-07-09) found the vendor's quote condition/indicator
population changed between the 2026-06-03 and 2026-06-29 cached
sessions (new indicator set 501–604; quote condition 34 absent from
`/v3/reference/conditions`), demonstrating that id vocabularies drift
under DI-09's ingest-everything design with no detection anywhere.
The pack scopes the defense to the new candidate's evidence pipeline
(unknown-id guard + units-sanity check,
`docs/research/prompt_pack_03b_print_eligibility.md` §6, joining the
Task-9 test plan). Extending it platform-wide — a per-session
ingest-health annotation or manifest field consumed by
`backtest_enforce_ingest_terminal_health`-style gating — touches
data-integrity behavior shared by every shipped alpha and needs its
own thread with parity-impact assessment. Spec pointer: 03b §6 and
§7.3 (open vendor questions on id 34, live-WS correction
dissemination, and the June-2026 population change).

## 6. C3 — Schema-require `structural_actor` (loader change)

Task 3 landed the archetype & structural-counterparty requirement as
authoring discipline in skill text only
(`.cursor/skills/microstructure-alpha/research-protocol.md`, Phase 1
rider), per the approved C3 disposition. Making `structural_actor` a
schema-required field is a `LayerValidator` / loader change with its
own test surface (new or amended gate, template + shipped-alpha
audit, load-failure tests) and is out of the doc-pack's scope. Spec
pointer: `docs/research/prompt_pack_01_skill_gap_report.md` §3 C3;
field definition `alphas/SCHEMA.md` (`structural_actor`, optional
Phase-3 field); validator anchor
`src/feelies/alpha/layer_validator.py`.

## 7. Cost-floor pre-filter for hypothesis-slate ranking (skill edit candidate)

Hypothesis-slate ranking must apply the realized cost-floor check
(dossier check d) as a hard pre-filter BEFORE ranking — the current
formula measures explanation quality but not economic viability (H1
lesson, 2026-07-10). Candidate skill edit for
`.cursor/skills/microstructure-alpha/research-protocol.md`; batch with
the next skill maintenance pass. Spec pointers:
`docs/research/prompt_pack_04a_slate_review.md` (check d method +
per-symbol floor table);
`docs/research/prompt_pack_04_hypothesis_slate.md` DISPOSITIONS Q1.

**Extension (H2 park close-out, 2026-07-11):** per-card cost floors
are not enough — H2 cleared the design-time floor arithmetic in a
pre-registered σ-conditional region and still parked because that
region was **empty as realized** (census 642d12d: 1/70 floored cells
σ-viable, contamination-flagged; max 35 episodes/symbol vs the ≥ 100
power floor). Slate pre-filtering must therefore use the **measured
horizon-feasibility map** — the census-measured σ₁₂₀-vs-floor and
eligible-episode-density surfaces on the frozen grid — as the hard
pre-filter, not just per-card disclosure arithmetic. Successor task;
evidence pointers:
`docs/research/sig_inventory_fade_v1_validation_protocol.md`
(CENSUS RESULTS C.3–C.5),
`docs/research/artifacts/inventory_fade_census_2026-07-11.json`,
`docs/research/sig_inventory_fade_v1_result.md` (NEXT ACTION).

prompt_pack_05 §6 is now the operative slate pre-filter gate (first
applied: Task 6-B).

## 9. `spread_z_30d` warm starvation on midcap quote rates

The H2 census (2026-07-11) measured the declared late-warm watch item
as **severe** on thin names: mean warm fraction of RTH h=120
boundaries ENSG 0.03, DIOD 0.05, MLI 0.08, PCTY 0.16 (vs APP 0.94) —
the 6000-quote count window often never fills a session, so entries
are (correctly, fail-safe) suppressed and any `spread_z_30d`-gated
design is warm-starved on 4/8 grid symbols. Candidate fixes: window
recalibration (`window=2000` — REGISTERED-UNEVALUATED, N-impact 0;
evaluating it is +1 N on the owning card's ledger) or a time-based
window variant. **Platform change, own thread, parity assessment
required** (the sensor feeds shipped alphas and locked baselines).
Evidence: `docs/research/sig_inventory_fade_v1_validation_protocol.md`
C.5 warm-coverage table; sensor anchor
`src/feelies/sensors/impl/spread_z_30d.py`
(`platform.yaml` `window: 6000`).

## 10. DI-09 contamination-at-extremes — 03b Class-A filtering for trade-fed extreme-conditioning designs

Lesson from the H2 census (§1.5 flags): pooled over eligible
boundaries, **80 % (496/621)** carried a Class-B print or correction
record in the trailing 60 s window — dominated by condition id 10
(Derivatively Priced) and id 2 (Average Price) at rates far above the
tape-wide base rate. High-|pressure| windows co-occur with
derived/average prints: under DI-09 ingest-everything, a trade-fed
sensor conditioned on its own extremes selects exactly the windows
where ineligible prints distort it. Consequence: **03b Class-A
print-eligibility filtering is near-mandatory for any future trade-fed
extreme-conditioning design** (as a NEW-sensor variant with explicit
constructor params, per the 03b convention — never a mutation of a
shipped sensor). Evidence:
`docs/research/sig_inventory_fade_v1_validation_protocol.md` C.5
contamination section; convention:
`docs/research/prompt_pack_03b_print_eligibility.md` §3.3.

## 8. Dedicated calendar-event grid program (H4 revival path)

H4 (`sig_close_rebalance_drift_v1`) was parked at final selection
(2026-07-11) on an evidence-infrastructure mismatch, not a refutation:
the frozen 03c grid yields only ~10 closing episodes/symbol, and its
F3 calendar-loading falsifier (effect concentration on month-end/
quarter-end/index-event sessions) is untestable on a grid screened
away from event days. A future program would build a dedicated
calendar-event session grid (month-end, quarter-end, index
reconstitution dates) with enough closing windows to power F1–F3,
plus the per-session closing-window calendar YAML the card requires.
Spec pointers: H4 card in
`docs/research/prompt_pack_04_hypothesis_slate.md` (pre-registered,
unedited); parked disposition in that file's DISPOSITIONS 5;
adjudication basis in
`docs/research/artifacts/h2_h4_adjudication_package.md`.

2026-07-11 update: feasibility map (7a08c95) shows taker execution
closed at H=900 median (APP in p90 tail only; sole taker-open cell
APP/1800) — H4's mechanism is intrinsically taker, so the program is
deprioritized; revisit only if a passive-compatible close-mechanism
variant is designed or the cost structure changes.

## 11. Universe tranche 2 (higher-σ midcaps) — diversification path

Registered at slate-B final selection (2026-07-12): the feasibility
map confines the current cycle to one family (KYLE_INFO) with ~2
deployable symbols (APP primary, RMBS marginal) — the measured
frontier of the frozen 03c grid, accepted for this cycle. The
structural fix is not more mechanisms on the same grid but a second
universe tranche of higher-σ midcaps, where the passive κ_req
surfaces open more (family × horizon × symbol) regions. Future
program: candidate screen, cache build, and a fresh feasibility map
for the new tranche — never pooled with the frozen grid. Spec
pointers: `docs/research/prompt_pack_06_hypothesis_slate_b.md`
DISPOSITIONS 3; concentration analysis in
`docs/research/prompt_pack_06a_slate_b_review.md` §1 (structural
consequence note) and §6 Q2.

**T2-C (2026-07-18):** bounded frontier characterization executed —
`prompt_pack_13_tranche2_characterization.md` **NO-GO** (1/5 names at
H≤120 passive κ_req ≤ 0.12). **NO-GO DISPOSITION ratified** (Lei,
2026-07-18): tranche-2 thesis closed by measurement; standing state
**PAUSE-AND-HARVEST**; reopening conditions in pack-12 DISPOSITION
amendment entries 6–7. AXTI is a single-name characterization fact,
not a program seed. N unchanged.

## 12. Magnitude-vs-power labeling in gate design — LANDED

**Landed** Task 3-M (2026-07-15) in
`.cursor/skills/microstructure-alpha/research-protocol.md`
(Validation Protocol & Slate Design Discipline — Magnitude-vs-power
labeling) with cross-link in
`.cursor/skills/testing-validation/SKILL.md`. Incident retained:
H8 step-2b |RankIC| ≥ 0.03 at +0.0186; S.5/S.8;
`sig_dislocation_lambda_drift_v1_result.md`.

## 13. Consequence-precedence defined at freeze — LANDED

**Landed** Task 3-M (2026-07-15) in
`.cursor/skills/microstructure-alpha/research-protocol.md`
(Consequence-precedence at freeze). Incident retained: H8 §9 REJECTED
vs A-2.1 safeguard PARK (S.5/S.8); frozen "pooled over D" vs D={APP}
(AMENDMENT A-2).

## 14. Step-2 ordering — harness-level IC gate option — LANDED

**Landed** Task 3-M (2026-07-15) in
`.cursor/skills/research-workflow/SKILL.md` (Step-2 ordering —
documented tradeoff, **not mandated**; operator decision deferred).
Full analysis pointer:
`docs/research/prompt_pack_07_program_retrospective.md` §3. Incident
retained: H8 Tasks 9–10 (8 commits before step-2b death).

## 15. Census-legal occupancy pre-read before power projections — LANDED

**Landed** Task 3-M (2026-07-15) in
`.cursor/skills/microstructure-alpha/research-protocol.md`
(Census-legal occupancy pre-read). Incident retained: H8 design
0.453/0.226 vs realized 0.343/0.107 (protocol C.5); H6/H7 headline
vs design-central (`prompt_pack_06a_slate_b_review.md` §3).

## 16. Grid-amendment constant governance — LANDED

**Landed** Task 3-M (2026-07-15) in
`.cursor/skills/data-engineering/SKILL.md` (Grid-Amendment Constant
Governance) with cross-link in
`.cursor/skills/microstructure-alpha/research-protocol.md`. Incident
retained: H8 A-1 silence on §4.1/JC-4 terciles → A-2.2 ruling;
`prompt_pack_03c_universe_and_cache.md` AMENDMENT 1.

## 17. Contingent-card triggers must enumerate failure modes — CANDIDATE

When a slate holds a card contingent on another card's step-2
outcome, the freeze must enumerate failure **modes** (magnitude /
significance / mechanism-tie / form / power), not a single "fails"
path. A mixed outcome (e.g. magnitude PASS + significance/F2 FAIL)
otherwise creates a literal trigger gap and forces post-outcome
substance adjudication. Candidate skill edit for
`.cursor/skills/microstructure-alpha/research-protocol.md` (Slate
Design Discipline / consequence-precedence neighbor) and/or
`.cursor/skills/research-workflow/SKILL.md`. Incident: slate-C
DISPOSITIONS 2 vs 6–7 — H9 presumptive-death trigger keyed only to
H10 "fails step 2b on magnitude"; H10 failed on p + F2 with magnitude
cleared; death ruled on sibling arithmetic + shared F2 anyway
(`prompt_pack_09_hypothesis_slate_c.md` DISPOSITIONS 2, 7–8;
`prompt_pack_10_cycle2_retrospective.md` §2.3).

## 18. Contamination REPORTS estimands labeled at freeze — CANDIDATE

JC-style REPORTS diagnostics that carry a "near-zero by construction"
expectation must name the estimand at freeze (sensor-state leakage vs
tape co-travel / composition share). Unlabeled fields invite false
bug investigations when a large-by-construction tape quantity trips a
leakage-shaped threshold. Candidate skill edit for
`.cursor/skills/microstructure-alpha/research-protocol.md`
(contamination / census hygiene) and cross-link in
`.cursor/skills/data-engineering/SKILL.md` if print-eligibility
conventions are touched. Incident: H10 JC-1 / census C.3 / amendment
A-2 — `residual_non_a_share` ≈ 0.62–0.80 on 40/40 cells measured tape
co-travel, not state leakage
(`sig_sweep_kyle_drift_h900_v1_validation_protocol.md` C.3, A-2;
`prompt_pack_10_cycle2_retrospective.md` §2.2).

## 19. Occupancy pre-reads MANDATORY for every non-percentile conditioning arm; percentile-exemption is arm-scoped, not card-scoped — CANDIDATE

Backlog 15 landed a census-legal occupancy pre-read obligation, but
H12 showed the remaining gap: **percentile-tail exemption does not
exempt sibling non-percentile arms** on the same card. Design priors
on window fraction, sign-agreement, gate×warm, or any other
non-percentile conditioner must be **measured** (or geometry-
identity-verified) before power projections are treated as
load-bearing — otherwise design-central clears ≥ 130 while realized
all-cell / viable counts miss the census floor. Contrast retained:
H8 ≈ **0.55×** realized/design (non-percentile joint occupancy);
H12 ≈ **0.46×** (window × gate arms; quintile exempt but insufficient);
H10 ≈ **1.04×** (percentile-exempt decile × ISO-warm — exemption
held because the binding arm *was* the percentile). Candidate skill
edit for `.cursor/skills/microstructure-alpha/research-protocol.md`
(Census-legal occupancy pre-read / Slate Design Discipline —
arm-scoped exemption language). Incident: H12 census
`3ed79a6` / protocol C.4–C.5 / C.8 —
`sig_halfhour_clock_drift_h900_v1_validation_protocol.md`;
closure `sig_halfhour_clock_drift_h900_v1_result.md` §7.

## 20. Arm-specific occupancy must be MEASURED on the target window geometry; cross-card `f_resid` transfer is itself an unvalidated prior — CANDIDATE

Backlog 19 closed the arm-scoped percentile-exemption gap; H13 showed
the next gap: **transferring a sibling card's measured residual
occupancy (`f_resid`) onto a different window geometry is itself an
unvalidated prior.** H13 rebuilt density under backlog 19 using H12's
`f_resid = 0.3935` as characterization input and still missed
bidirectionally: in-hour κ-viable rider ≈96 → measured viable **66**
(≈ **0.69×**); :30 arm rider ≈96 → measured viable **175** (≈
**1.8×**); :00-vs-:30 occupancy asymmetry ≈ **2.6×**. Uniform all-cell
projection **120.9** also failed to predict either arm. Arm-specific
occupancy on the **target** window geometry (hour-only × H=1800 here)
must be measured before power projections are treated as
load-bearing — cross-card residual transfer does not substitute.
Candidate skill edit for `.cursor/skills/microstructure-alpha/research-protocol.md`
(Census-legal occupancy pre-read — extend backlog 19 with
geometry-scoped / no-cross-card-`f_resid`-transfer language).
Incident: H13 census / protocol C.4–C.5 / C.8 (Task 8-C-H13) —
`sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md`;
closure `sig_hour_checkpoint_drift_h1800_v1_result.md` §7.

---

## PROGRAM-CLOSED stamp (2026-07-18 — Task 7-R3; append-only)

The alpha research program on this universe/grid is **CLOSED** under
the pack-10 stop-rule (cycle 3 complete without a step-2b PASS; H12
park + H13 park). Permanent record:
`docs/research/prompt_pack_12_final_retrospective.md` (Status:
AWAITING-LEI-REVIEW). Entries **1–20 above are unedited** by this
stamp; they remain the external-dependency / skill-edit handoff
inventory with owners as written. Residual capital decision (tranche 2
vs STOP vs PAUSE-AND-HARVEST) is **not** pre-committed and requires
its own Lei authorization. Living trial ledger **N = 12** (no
increment in Task 7-R3 — synthesis only). No new backlog entry number
is opened by program closure.

---

## CAPITAL-FORK-CLOSED stamp (2026-07-18 — pack-13 NO-GO; append-only)

Capital fork **resolved**: tranche-2 frontier characterization
returned **NO-GO** (`prompt_pack_13_tranche2_characterization.md`
DISPOSITION); standing state **PAUSE-AND-HARVEST** with reopening
conditions frozen (pack-12 DISPOSITION amendment entries 6–7).
**HARVEST INVENTORY** confirmed committed and owned (pack-12
DISPOSITION amendment entry 8): platform + skill ecosystem + four
frozen protocol templates + parity guards (12-P) + calibration
record + characterization corpus + backlog **1–20 with owners** +
escalated vendor tickets **T5-OQ-3 / V-1** and **AXIS-2 / V-2** as
handed-off external dependencies. Entries **1–20 above are
unedited** by this stamp except entry 11's append-only T2-C
ratification note. Living trial ledger **N = 12** (no increment —
disposition only). No new backlog entry number is opened.

---

## 21. IC harness mid-return dependent variable only — CANDIDATE (Additive harness extension)

IC / RankIC evidence paths score features against forward *mid
returns* only, blocking spread-state / quote-behavior dependent
variables (pack-15 §5.2 lowest-mirage grammar). Spec pointer:
`prompt_pack_15_grammar_machine_universe_doctrine.md` §8 row 1.

## 22. Cross-sectional IC (rank-vs-rank) evidence path — CANDIDATE (Additive harness extension)

No rank-vs-rank / cross-sectional IC harness for Layer-3 PORTFOLIO
grammar validation (pack-15 §5.1). Spec pointer:
`prompt_pack_15_grammar_machine_universe_doctrine.md` §8 row 2; related
runtime gap remains backlog 1 (OQ-3 mechanism-cap closure).

## 23. Boundary-clocked evaluation only — CANDIDATE (Core change — scheduler; backlog only)

Episode = conditioned horizon boundary; event-anchored / rare-event
grammar is ungenerable without a scheduler change. Spec pointer:
`prompt_pack_15_grammar_machine_universe_doctrine.md` §8 row 3 / §5.4.
Never assumed as available for a reopened round.

## 24. Flat 2.0 bps passive adverse-selection charge — CANDIDATE (Calibration study)

Universe-dependent execution realism: names with worse true AS are
flattered by the flat `passive_adverse_selection_bps = 2.0` pin.
Calibration study once any card reaches fills. Spec pointer:
`prompt_pack_15_grammar_machine_universe_doctrine.md` §8 row 4;
`src/feelies/execution/cost_model.py`.

## 25. L1-visibility proxies in characterization — CANDIDATE (New census-legal measurement)

No L1-visibility proxies (primary-venue share, displayed-to-effective
spread, odd-lot share, ISO/trade-through intensity, quote-to-trade
ratio) in any characterization screen — the pack-15 §3/§4 M-axis.
New census-legal measurement on the pack-13 pattern; cutoffs frozen
at first characterization. Spec pointer:
`prompt_pack_15_grammar_machine_universe_doctrine.md` §8 row 5.
