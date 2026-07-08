<!--
  File:   docs/research/prompt_pack_01_skill_gap_report.md
  Status: APPROVED-AND-EXECUTED — Task 2 audit complete 2026-07-08;
          dispositions approved by Lei in the Task-3 prefix: C1 rephrase
          ("Label unvalidated theories as hypotheses"), C2 all six
          locations (+2 grep-found), C3 skill-level only (loader change
          backlogged), C4 OQ-3 caveat on all capacity text. Task 3
          executed same day — see
          docs/research/prompt_pack_02a_skill_changelog.md.
  Owner:  cross-cutting (microstructure-alpha / research-workflow /
          regime-detection / feature-engine); prompt-pack Task 2, Phase A.
-->

# Prompt-pack Task 2 — Skill gap analysis (R1–R11)

Audit of the existing skill ecosystem against the eleven required
methodology additions, per the Task-2 mandate and the FQ-1 amendment
(R11 = the edge-units rider from
`docs/research/prompt_pack_00b_edge_units_convention.md`, NORMATIVE).

Read this session: `prompt_pack_00_architecture_verification.md`
(incl. §(e) dispositions and §(f) cross-check), `prompt_pack_00b`,
`.cursor/skills/README.md`, and the full text of: platform-invariants
(always-applied rule), microstructure-alpha `SKILL.md` +
`research-protocol.md`, research-workflow, testing-validation,
backtest-engine `SKILL.md` + `fill-model.md` + `stress-testing.md`,
feature-engine, regime-detection, post-trade-forensics,
alpha-lifecycle, plus targeted source checks (`research/dsr.py`,
`execution/tick_size.py`, `alphas/SCHEMA.md`,
`tests/docs/test_internal_links.py`, risk-engine skill §limits).
Line numbers are against the working tree 2026-07-08 and will drift;
treat the cited section/symbol as primary.

Honest-accounting note: no numbers appear in this report; it audits
methodology text only. Zero trials consumed — the trial ledger (R4)
starts at N = 0 when Task 6 opens it.

---

## 1. Verdict summary

| # | Required addition | Verdict | One-line basis |
|---|---|---|---|
| R1 | Reformalization Gate (folk/TA → state variable + conditional claim + falsifier) | **PARTIAL** | TA language banned; hypothesis template exists; no reformalization *procedure* or worked example |
| R2 | Archetype rider + structural-counterparty argument | **PARTIAL** | Mechanism families + `[actor]…[incentive]` hypothesis format exist; archetype mapping and counterparty-incentive argument never required |
| R3 | Mirage-risk ranking on sensor families | **PARTIAL** | L2-blind-spot table + per-sensor caveats exist; no family-level mirage ranking or stricter-accounting rule |
| R4 | Living trial-count ledger discipline | **PARTIAL** | All DSR machinery shipped (`n_trials`); the ledger *discipline* and noise-ceiling framing entirely absent |
| R5 | Zero-integrated-edge conservation check | **MISSING** | One orphan phrase ("specify conservation constraints"); no check defined anywhere |
| R6 | Regime-stratified validation procedure | **PARTIAL** | Requirement stated in three skills; no procedure (strata construction, per-stratum repeat, min-sample rule) |
| R7 | Pre-trade capacity/crowding envelope | **PARTIAL** | ADV limit exists as unimplemented risk *policy*; crowding table is post-trade; pre-trade envelope discipline absent |
| R8 | Tick-constraint artifact rider | **MISSING** | `execution/tick_size.py` ships; no skill mentions grid-discretization artifacts or tick-regime sample boundaries |
| R9 | Research-stage status vocabulary | **MISSING** | Three *adjacent* vocabularies exist, none covers the pre-`alpha_id` doc stage; "working" collides with existing skill text (C1) |
| R10 | Single deliverable template | **PARTIAL** | Four partial templates exist (hypothesis, output format, stress report, handoff table); no unified proposal template |
| R11 | Edge-units convention rider (FQ-1) | **PARTIAL** | Cost block documented in three skills; one-way convention absent from all skill text; ±5% tolerance wording wrong in four places (C2) |

---

## 2. Per-item audit

### R1 — Reformalization Gate

**COVERED:**

- The ban: microstructure-alpha `SKILL.md:416` — "You Must Not …
  Use vague technical-analysis language".
- A hypothesis structure that reformalized claims must land in:
  `research-protocol.md:40-47` (HYPOTHESIS TEMPLATE:
  Observable / Mechanism / Prediction / Counterfactual / Decay model)
  and the reject list `research-protocol.md:49-54` ("Cannot specify
  the mechanism … no testable counterfactual").
- The target machinery for the worked example exists:
  `quote_replenish_asymmetry` is an implemented INVENTORY-fingerprint
  sensor (feature-engine `SKILL.md:129`, catalog #3);
  `research/forward_ic.py` ships `spearman_ic` /
  `bucketed_forward_return` / `long_short_edge_bps` (verified in
  00 §(a) research table) and `scripts/sensor_feature_ic.py` is the
  offline falsification harness (00 §(a)).

**MISSING:** the gate itself — the three-step restatement procedure
(exact L1 state variable with units → conditional-distribution claim
→ falsifying forward test) and the mandated worked example
("price approaching a prior extreme" ⇒ tick distance from best
bid/ask to prior N-bar local extremum; "the level holds" ⇒
quote-replenishment intensity within k ticks vs unconditional
baseline; falsifier via `forward_ic`). Today an author can satisfy
the letter of the ban by simply not writing TA words, without ever
producing the sensor-expressible restatement.

### R2 — Archetype rider on the mechanism taxonomy

**COVERED:**

- Closed mechanism taxonomy with per-family envelopes, fingerprint
  sensors, exit-only stress family: microstructure-alpha
  `SKILL.md:63-115`; G16 rules in `alphas/SCHEMA.md:201`.
- Actor-shaped hypothesis format: `SKILL.md:128` —
  `hypothesis: "[actor] does [action] because [incentive]; L1
  signature: [observable]"`; `hypothesis` and
  `falsification_criteria` are schema-required
  (`alphas/SCHEMA.md:26-27`).
- The `structural_actor` YAML field exists: `alphas/SCHEMA.md:144` —
  "Free-text description of the actor whose behavior the alpha
  trades against" — but is **optional** ("No (Phase 3)").

**MISSING:** the archetype mapping discipline. Nothing requires
stating (a) whether the candidate is liquidity provision,
informed-flow-following, or an argued third case, and (b) who the
structural counterparty is and *why they trade against THIS signal
rather than the market at large*. The hypothesis format names an
actor whose behavior generates the signature — that is the
*upstream* actor, not the counterparty who funds the edge. The two
are conflated nowhere and required nowhere. (Scope boundary: the
rider is skill-level authoring discipline; making `structural_actor`
schema-required is a loader change out of this pack's scope — see C3.)

### R3 — Mirage-risk rider on the sensor families

**COVERED:**

- The L2-blind-spot inventory: `research-protocol.md:159-174`
  ("L1 Data Limitations — What You Cannot See"), including
  "Cancel-to-trade ratio … Proxy via quote flicker rate" (`:167`)
  and the mandatory section "What breaks if the L2 reality diverges
  from our L1 inference?" (`:172-173`).
- Scattered per-observable caveats: micro-price "breaks when
  displayed sizes are strategic (iceberg orders)"
  (`research-protocol.md:202`); "Flickering quotes →
  spoofing-probability estimation" (`SKILL.md:52`); fill-model
  adverse-selection-by-toxicity (`fill-model.md:144-164`).

**MISSING:** the family-level *ranking* (spread-state / trade-print
LOW; micro-price/imbalance MEDIUM; quote-flow/cancellation HIGH with
`quote_flicker_rate`, `quote_hazard_rate` named — both implemented,
feature-engine `SKILL.md:132-134`), the consequence rule (high-mirage
families demand **stricter L2-loss accounting, not disqualification**),
and the separation rule (mirage rank never settles the archetype
question). The rider annotates observable *families*; it does not
duplicate the 16-sensor catalog (canonical in feature-engine).

### R4 — Living trial-count ledger

**COVERED (machinery):**

- `research/dsr.py:246-296` — `expected_max_sharpe(n_trials,
  trial_sharpe_variance)` (BLP eq. 7 two-quantile form; the
  σ√(2 ln N) framing is its asymptotic equivalent);
  `deflated_sharpe(..., n_trials)` (`:341-404`);
  `build_dsr_evidence` feeds `n_trials=trials_count` (`:537`);
  null trial variance defaults to `1/(n_obs−1)` (00 §(a)).
- `DSREvidence.trials_count` must be > 0 — `validate_dsr` refuses
  zero (alpha-lifecycle `SKILL.md:144`).
- The correction *requirement*: `research-protocol.md:119-123`
  ("Track number of features tested; Apply Bonferroni or
  Benjamini-Hochberg"); research-workflow `SKILL.md:268`
  (Bonferroni/BH row) and `:59-61` (unregistered exploration →
  "stricter multiple-testing corrections").

**MISSING (discipline):** nothing defines *where N lives*, what
increments it (every construction / parameter / filter variant tried
anywhere in the workflow — including discarded ones), that the same
N must be the `trials_count` handed to `build_dsr_evidence`, or that
the noise ceiling `E[max Sharpe | null, N]` must be stated alongside
any Sharpe quoted. "Track number of features tested" undercounts by
design: parameter and construction variants are trials too. The
per-workflow living ledger is the session's constraint #5 made
operational; no skill encodes it.

### R5 — Zero-integrated-edge conservation check

**MISSING.** Closest existing text, neither of which is this check:

- microstructure-alpha `SKILL.md:352-353` — "Define state variables.
  Specify conservation constraints." — an orphan phrase in the
  Mathematical Framework paragraph with no procedure attached.
- testing-validation `SKILL.md:172` — "PnL decomposition … alpha +
  beta + costs = total (FP tolerance)" — an accounting identity on
  random trade sequences, not an economic-conservation test.

Nothing requires the one mandatory invariance check per signal: over
a long regime-balanced sample, integrated edge must be consistent
with the stated mechanism's economics — the declared counterparty
(R2) must plausibly supply it. This is the quantitative closure of
Inv-1: a mechanism whose counterparty cannot fund the integrated
edge is a free lunch and therefore a misattribution.

### R6 — Regime-stratified validation procedure

**COVERED (requirement stated three times):**

- `research-protocol.md:109-113` — Phase 3 test hierarchy §3:
  "Test separately in low-vol, medium-vol, high-vol regimes …
  tight-spread vs wide-spread … Report if alpha concentrates in one
  regime".
- research-workflow `SKILL.md:269` — "Signal must work across ≥ 2
  volatility regimes and ≥ 2 spread regimes" (Mandatory Controls).
- backtest-engine `stress-testing.md:182-198` — regime-stratified
  stress table (its perturbation harness is already correctly marked
  Not-shipped, `stress-testing.md:24-27`).
- Live-side counterpart exists in post-trade-forensics
  `SKILL.md:162-175` (Regime Dependency Stability).

**MISSING:** the executable manual procedure — partition horizon
boundaries by HMM dominant state (`HMM3StateFractional`, 3 states,
regime-detection `SKILL.md:96-106`) × `spread_z_30d` strata
(implemented sensor, feature-engine `SKILL.md:133`); repeat
IC (`scripts/sensor_feature_ic.py`) and CPCV (`research/cpcv.py`)
per stratum; a minimum per-stratum sample rule (only floor today is
`spearman_ic`'s ≥ 3 pairs, far below adequacy). Must be encoded and
explicitly marked **Not shipped as harness** per the drift-table
convention (00 §(c) preamble) — no code claim.

### R7 — Pre-trade capacity/crowding envelope

**COVERED (fragments in other layers):**

- risk-engine `SKILL.md:135-141` — "Max position as % of ADV | 1% of
  20-day ADV" under "**Policy only — not yet implemented**"; the
  sizing pseudocode caps at `adv_limit` (`:169`). A runtime risk
  limit, not a research-stage capacity claim.
- post-trade-forensics `SKILL.md:204-219` — Edge Crowding symptom
  table plus the confirmation rule ("signal quality … stable but
  post-execution alpha erodes") — strictly *post-trade*.
- composition-layer mechanism-share caps (G16 rule 8) exist at load;
  runtime enforcement is **disabled** (`mechanism_max_share_of_gross
  = 1.0` at bootstrap) — accepted risk OQ-3, 00 §(e).

**MISSING:** the pre-trade envelope as proposal-stage discipline:
ADV-based capacity ceiling for midcaps stated *before* any backtest;
the Sharpe-max vs profit-max size distinction with an explicit
target declared; correlated-unwind reasoning (who else exits when
this mechanism's trigger fires, and what that does to exit cost).
Per OQ-3's binding obligation, any capacity/crowding text this pack
adds must carry the one-line caveat that runtime mechanism-share
enforcement is not active, so no deployment claim may rely on it.

### R8 — Tick-constraint artifact rider

**MISSING.** Code anchor ships: `execution/tick_size.py:1-14` —
Reg NMS sub-penny grid (≥ $1.00 → $0.01; < $1.00 → $0.0001), BT-14,
with conservative taker/passive snapping. No skill file mentions the
research-side consequence: when the minimum tick is a large fraction
of the quoted midcap spread, spread-state dynamics compress into few
discrete states and apparent regime persistence (or spread-regime
structure, or spread-z strata in R6) can be a grid artifact.
`fill-model.md:187` uses `tick_size` only as a price-level increment
in the sweep model; regime-detection's taxonomy
(`SKILL.md:96-106`) and hazard caveats (`:251-286`) never flag
discretization. Also absent: treating any scheduled tick-regime
change as a pre-registered structural sample boundary.

### R9 — Research-stage status vocabulary

**MISSING** for the pre-`alpha_id` doc stage. Three *adjacent*
vocabularies exist, none of which covers it:

- research-workflow `SKILL.md:92` (target spec, not shipped) —
  `ExperimentRecord.status: "proposed" | "exploring" | "formalizing"
  | "backtesting" | "promoted" | "failed" | "abandoned"` — experiment
  granularity, not proposal-doc granularity.
- research-workflow `SKILL.md:112-118` — `Hypothesis.status: str =
  "active"` plus outcome `"supported" | "falsified" | "inconclusive"`.
- `AlphaLifecycle` states RESEARCH/PAPER/LIVE/QUARANTINED/
  DECOMMISSIONED (alpha-lifecycle `SKILL.md:54`) — post-`alpha_id`
  only.
- A fourth, forward-looking vocabulary is cited from
  `docs/three_layer_architecture.md:1907` ("DECAYING/RETIRED status
  transitions in `research/hypothesis_status.py`") — a whitelisted
  placeholder path, not implemented
  (`tests/docs/test_internal_links.py:71-76`).

Required and absent: docs carry Status ∈ {hypothesis, candidate,
trap-quadrant, accepted, rejected}; "working" banned as a status;
trap-quadrant defined as statistically valid but execution-invalid
(the axes separation of session constraint #5); "accepted" maps to
"ready to seek RESEARCH→PAPER via
`validate_gate(GateId.RESEARCH_TO_PAPER, …)` with
`ResearchAcceptanceEvidence`" (alpha-lifecycle `SKILL.md:113-121`).
See conflict C1 (the word "working" appears in existing skill text).

### R10 — Deliverable template

**COVERED (four partial templates, none unified):**

- `research-protocol.md:40-47` — hypothesis template (maps to
  SIGNAL / PROCESS MODEL / FALSIFICATION CONDITION).
- microstructure-alpha `SKILL.md:427-454` — the
  MICROSTRUCTURE/PORTFOLIO/CTO/SYNTHESIS response format (analysis
  format, not a proposal artifact).
- `stress-testing.md:241-283` — stress-report template (execution
  result only).
- research-workflow `SKILL.md:189-198` — notebook→YAML handoff table
  (field mapping, no economics sections).

**MISSING:** the single instantiable proposal template — SIGNAL /
ARCHETYPE & COUNTERPARTY / STATE VARIABLES / PROCESS MODEL /
ENTRY-EXIT RULE / L2 LOSS ACCOUNTING / STATISTICAL RESULT /
EXECUTION RESULT / CAPACITY & CROWDING / FALSIFICATION CONDITION /
STATUS / NEXT ACTION — with each section mapped to the alpha YAML
field it feeds (`hypothesis`, `structural_actor`,
`trend_mechanism.*`, `depends_on_sensors`, `regime_gate`,
`cost_arithmetic.*`, `falsification_criteria`). It is the
integration point for R2 (archetype section), R3 (L2 loss
accounting), R5 (conservation check under statistical result), R7
(capacity section + OQ-3 caveat), R9 (status field), and R11
(one-way units in the cost lines).

### R11 — Edge-units convention rider (FQ-1 amendment)

**COVERED:**

- Code and YAML level fully verified one-way (00b hops 1–5,
  cross-checked in 00 §(f)): `alpha/cost_arithmetic.py:33-54`
  docstring, `cost_basis` default `one_way`, derived
  `round_trip_cost_bps`; `sig_benign_midcap_v1` self-documents
  (00b hop 1b).
- The cost block is described in three skills: microstructure-alpha
  `SKILL.md:236-250` (Cost Arithmetic G12),
  `research-protocol.md:30`, research-workflow `SKILL.md:195`.

**MISSING / WRONG in skill text (the rider's four clauses):**

1. No skill states that `edge_estimate_bps` and the three cost
   components are **one-way (per-fill) bps of fill notional**, nor
   that a round-trip disclosure is an error that systematically
   loosens the B4 gate (which doubles the disclosed edge,
   `execution/position_manager.py:563`) and corrupts the
   `mean/disclosed` calibration ratio.
2. No skill mentions the `cost_basis` YAML field (accepted but
   reserved; no shipped alpha uses `round_trip` and Task-6+
   candidates must not).
3. The reconciliation tolerance is stated as "±5%" (relative) in
   four skill locations — `SKILL.md:153`, `SKILL.md:244-246`,
   `research-protocol.md:30`, research-workflow `SKILL.md:195` —
   while the code is **±0.05 absolute on the ratio**
   (`alpha/cost_arithmetic.py:95, 248`; 00b C3). See conflict C2.
4. No skill states that realized-edge comparisons (forensics TCA,
   SURVIVES, calibration haircut) are per-fill quantities
   commensurate with the one-way disclosure under balanced
   entry/exit fill counts (00b hop 5 + caveat C1 there).

The rider text to encode is pre-written in 00b §"Amendment for the
Task-2 gap report" — Task 3 transcribes it, it is not re-drafted.

---

## 3. Conflicts with existing skill text (verbatim — for decision)

**C1 — "working" (R9).** microstructure-alpha `SKILL.md:412`
("You Must" list):

> - Label working theories as such; specify falsification criteria

R9 bans "working" as a status value. The existing line uses
"working theories" as prose meaning *provisional*, not as a status —
but the collision invites exactly the sloppiness R9 targets.
Options: (a) rephrase the bullet to "Label provisional theories as
such…" when Task 3 touches the file (recommended — one word, same
meaning); (b) keep the prose and ban "working" only as a `Status:`
value. **Decision needed.**

**C2 — "±5%" tolerance (R11).** Code is `abs(computed − declared) ≤
0.05` absolute (`alpha/cost_arithmetic.py:95, 248`). The relative
wording appears in:

Skill-owned (Task 3 fixes these per the rider — no decision needed):

> `margin_ratio: 1.8                    # must be ≥ 1.5 and reconcile with components ±5%` — microstructure-alpha `SKILL.md:153`

> - The disclosed `margin_ratio` must reconcile with the components
>   within ±5%; otherwise the alpha author has lied about costs and the
>   load is rejected — `SKILL.md:244-246`

> - `cost_arithmetic:` (G12 — margin_ratio ≥ 1.5, reconciles ±5%) — `research-protocol.md:30`

> | Cost arithmetic | `cost_arithmetic:` block (G12 — `margin_ratio ≥ 1.5`, reconciles ±5%) | Alpha YAML | — research-workflow `SKILL.md:195`

Outside skill ownership (decision needed — Task 3 does NOT touch
these without approval):

> | G12 | **Active** (Phase 3-α) | Cost-arithmetic disclosure — `cost_arithmetic` block required, `margin_ratio >= 1.5`, components reconcile within ±5%. | — `alphas/SCHEMA.md:197` (normative gate reference, guard-covered by `tests/docs/test_internal_links.py`)

> | **cost arithmetic** | Required SIGNAL YAML block; `margin_ratio ≥ 1.5` and ±5% reconciliation (Inv-12). … | — `.cursor/rules/platform-invariants.mdc` glossary (always-applied rule file)

Direction is safe (code is tighter than the documented ±5% for all
margins > 1.0 — 00b C3), so leaving the two normative docs unfixed
is not dangerous, only inconsistent. Recommendation: approve fixing
all six in Task 3 in one pass; if the rule file is off-limits, fix
the five docs and log the glossary as a known erratum here.
**Decision needed.**

**C3 — `structural_actor` optionality (R2).** `alphas/SCHEMA.md:144`
marks the field optional:

> | `structural_actor` | string | No (Phase 3) | Free-text description of the actor whose behavior the alpha trades against. |

R2's counterparty-incentive requirement will be encoded as
skill-level authoring discipline (binding on new candidates in this
workflow), **not** as a loader gate — changing the schema
requirement is a `LayerValidator` code change with test surface,
out of this doc-pack's scope. If Lei wants it gate-enforced, that is
a separate scoped thread (same pattern as the OQ-3 backlog entry).
**Confirm the skill-level-only scope.**

**C4 — capacity claims vs OQ-3 (R7; binding rider, not a text
conflict).** Per 00 §(e) OQ-3, every capacity/crowding section this
pack writes must carry: *runtime mechanism-share enforcement is not
active (`mechanism_max_share_of_gross=1.0` at bootstrap); no
deployment claim may rely on it.* Task 3's R7 and R10 additions
inherit this obligation verbatim.

Non-conflicts checked and cleared: `fill-model.md`'s "Tier 1 …
never for final results" (`fill-model.md:24-31, 225`) already agrees
with honest-accounting constraint #5; R4 complements (does not
contradict) the Bonferroni/BH rows; R9's "accepted" mapping agrees
with the alpha-lifecycle promotion surface.

---

## 4. Surgical edit plan (Task 3, pending approval)

Owning-skill placement per `.cursor/skills/README.md`. No canonical
table is duplicated: parity registry stays in testing-validation,
gate matrix in alpha-lifecycle, sensor catalog in feature-engine,
G-gate table in `alphas/SCHEMA.md`, mechanism-family table in
microstructure-alpha. Additions reference these; never restate them.

| Edit | Receiving file | Placement & content | Guards to keep green |
|---|---|---|---|
| E1 (R1) | `microstructure-alpha/research-protocol.md` | New "Phase 0: Reformalization Gate" section before Phase 1: the 3-step procedure + the mandated worked example (prior-extreme tick distance / `quote_replenish_asymmetry` replenishment intensity vs baseline / `forward_ic` falsifier). One-line pointer added to `SKILL.md` "You Must Not" TA bullet. | `tests/docs/` suite; cited paths must resolve |
| E2 (R2) | `microstructure-alpha/SKILL.md` | Rider paragraph in the Trend Mechanism Taxonomy section: families encode mechanisms, not archetypes; every candidate must state archetype (liquidity provision / informed-flow-following / argued third) + structural counterparty + why they trade against THIS signal; anchor `structural_actor` (`alphas/SCHEMA.md:144`) noting skill-level-only enforcement (C3). | `tests/docs/` |
| E3 (R3) | `microstructure-alpha/research-protocol.md` | Mirage-risk subsection appended to "L1 Data Limitations": family ranking (LOW spread-state/trade-print; MEDIUM micro-price/imbalance; HIGH quote-flow/cancellation incl. `quote_flicker_rate`, `quote_hazard_rate`), consequence rule (stricter L2-loss accounting, not disqualification), separation rule (rank never settles archetype). One-line cross-pointer from feature-engine `SKILL.md` catalog note. | `tests/docs/` |
| E4 (R4) | `research-workflow/SKILL.md` | New rows + paragraph in "Multiple Testing & Overfitting Controls": the living ledger (every construction/parameter/filter variant increments N, including discarded ones), N == `trials_count` into `build_dsr_evidence`, noise ceiling `expected_max_sharpe(N, …)` (σ√(2 ln N) asymptotic) stated alongside any Sharpe. Cites `research/dsr.py`; no threshold table duplication. | `tests/docs/` |
| E5 (R5) | `microstructure-alpha/research-protocol.md` | New Phase 3 test-hierarchy item 6: zero-integrated-edge conservation check — regime-balanced long-sample integrated edge must be fundable by the declared counterparty (closes Inv-1 quantitatively; links R2's archetype statement). | `tests/docs/` |
| E6 (R6) | `microstructure-alpha/research-protocol.md` | Expand Phase 3 item 3 into the manual procedure: HMM-dominant-state × `spread_z_30d` strata over horizon boundaries; per-stratum IC (`scripts/sensor_feature_ic.py`) and CPCV; explicit minimum per-stratum sample rule. Marked **Not shipped as harness**. | `tests/docs/`; no code claim |
| E7 (R7) | `microstructure-alpha/research-protocol.md` | New section "Pre-trade capacity & crowding envelope": midcap ADV-based ceiling declared at proposal time (cross-pointer to risk-engine's policy-only ADV row — no duplication), Sharpe-max vs profit-max target declaration, correlated-unwind reasoning; **carries the OQ-3 caveat verbatim (C4)**. | `tests/docs/` |
| E8 (R8) | `microstructure-alpha/research-protocol.md` + one-line rider in `regime-detection/SKILL.md` | Phase 4 robustness-table row + short subsection: tick-grid artifact test (is apparent spread-state/regime persistence an artifact of tick/spread discretization? — anchor `execution/tick_size.py`); scheduled tick-regime changes are pre-registered structural sample boundaries. Regime-detection gets one sentence pointing here (taxonomy consumers must know). | `tests/docs/` |
| E9 (R9) | `research-workflow/SKILL.md` | New subsection "Research-stage status vocabulary" (pre-`alpha_id` docs): {hypothesis, candidate, trap-quadrant, accepted, rejected}; "working" banned as a status; trap-quadrant defined; "accepted" → ready to seek RESEARCH→PAPER via `validate_gate` + `ResearchAcceptanceEvidence`; explicit non-collision note vs `ExperimentRecord.status` target spec and the lifecycle SM. C1 disposition applied to `SKILL.md:412` per Lei's choice. | `tests/docs/` |
| E10 (R10) | **NEW** one-level-deep file: `.cursor/skills/microstructure-alpha/proposal-template.md` | The 12-section template with per-section YAML field mapping; STATUS field uses R9 vocabulary; CAPACITY & CROWDING embeds the OQ-3 caveat; cost lines state one-way units (R11). Registered in `.cursor/skills/README.md` supplementary-reference table; pointers from `research-protocol.md` and research-workflow's handoff table. | `tests/docs/`; README supplementary table updated (README convention, not test-enforced) |
| E11 (R11) | `microstructure-alpha/SKILL.md` (+ tolerance fixes in `research-protocol.md`, `research-workflow/SKILL.md`) | Encode the 00b rider verbatim into the Cost Arithmetic section (four clauses: one-way convention + B4 doubling; `cost_basis` reserved; margin one-way ≈ 0.75× round-trip + ±0.05 absolute; per-fill realized commensurability). Fix the four skill-owned "±5%" instances. `alphas/SCHEMA.md:197` + invariants-glossary fixes per C2 decision. | `tests/docs/test_internal_links.py` (SCHEMA.md is in `_DOC_FILES` if touched); `tests/docs/` |
| E12 (pre-routed, OQ-6/D6 — not an R-item) | `backtest-engine/fill-model.md` | 00 §(e) OQ-6 routes the D6 doc gap to Task 3's edit plan: document the resting through-fill partial-split under `through_fill_size_cap_enabled: true` (the reference `platform.yaml` setting) — code anchors `execution/passive_limit_router.py:634-663` per 00 §(f) 3a. Surgical: the spread-crossing "no split" claim in `backtest-engine/SKILL.md:271-278` gets the same one-line qualification. | `tests/docs/` |

### New reference file — warranted?

Yes, exactly one: `microstructure-alpha/proposal-template.md` (E10).
It is instantiated per proposal (repeated-use artifact), too long to
inline in `SKILL.md` without bloating the always-read surface, and
fits the README's one-level-deep rule. All other additions are
section-sized and land in existing files. Six of twelve edits land
in `research-protocol.md` (~+120 lines on ~250) — deliberate: it is
the designated methodology reference ("Hypothesis framework, feature
taxonomy", README supplementary table), and a second new file would
add README churn without ownership benefit. Rejected alternative
noted for the record: a separate `validation-procedures.md`.

### Guard inventory for the whole edit set

- `tests/docs/test_internal_links.py` — skill files are **not** in
  `_DOC_FILES` (`test_internal_links.py:39-43`: root `README.md`,
  `alphas/SCHEMA.md`, `docs/prompts/*.md` only), so skill edits are
  not directly link-checked; discipline still applies (every path
  cited must resolve). Touching `alphas/SCHEMA.md` (C2 option) IS
  guard-covered.
- `tests/docs/test_prompt_coverage_map.py` — not triggered: no new
  module under `src/feelies/` (doc-only edit set).
- `tests/scripts/test_run_audit_pack.py` — bundles skill files cited
  from prompt docs; no skill file is renamed or removed, so
  unaffected.
- Parity manifest / mypy / ruff / DTZ — no source files touched;
  the standard gates (`uv run pytest -m "not functional and not
  slow"`, `uv run mypy src/feelies`, `uv run ruff check src/ tests/`)
  still run as the Task-3 done-bar per session constraint #3.
- Immutables untouched: no parity baselines, ledger, event schemas,
  or router semantics are affected by any edit above.

---

## 5. Stop

Task 2 ends here. Awaiting Lei's decisions on C1 (rephrase "working
theories" vs status-only ban), C2 (scope of the ±0.05-absolute fix:
skill files only, or also `alphas/SCHEMA.md` and the
platform-invariants glossary), and C3 confirmation (R2 rider is
skill-level discipline, not a loader gate). Task 3 encodes E1–E12
only after this file's Status is flipped to APPROVED with those
dispositions recorded.
