<!--
  File:   docs/research/prompt_pack_02a_skill_changelog.md
  Status: DONE — Task 3 executed 2026-07-08 against the APPROVED edit
          plan of prompt_pack_01_skill_gap_report.md with dispositions
          C1/C2/C3/C4 and prefix additions (a)/(b). No conflicts left
          open. Guards green (tests/docs 57 passed; no Python logic
          touched — the one attempted test edit was reverted).
  Owner:  cross-cutting; prompt-pack Task 3, Phase A.
-->

# Prompt-pack Task 3 — Skill-refinement changelog

Two commits: the dedicated C2 wording commit, then the R1–R10 edit
set. Placement follows the Task-3 prefix (R1/R2/R3/R5/R8 →
research-protocol.md; R4/R9/R10 → research-workflow; R6 →
research-protocol cross-linked from testing-validation; R7 →
microstructure-alpha SKILL.md cross-linked from composition-layer),
which supersedes the gap report's E2/E7 placement where they differed.

## Commit 1 — C2 wording fix (dedicated)

`docs: correct margin reconciliation wording to ±0.05 absolute, 6
locations` — code truth `abs(computed − declared) ≤ 0.05` absolute
(`alpha/cost_arithmetic.py`), not ±5% relative. Pre-commit grep of
`tests/` found no assertion on the old wording. The approved six
locations plus **two further instances the grep surfaced**
(composition-layer `SKILL.md` G12 row;
`microstructure-alpha/system-architecture.md`) — 8 lines, 7 files,
each citing the code anchor. Nothing else altered in
`alphas/SCHEMA.md` or `platform-invariants.mdc`.

## Commit 2 — R-item edits

| R | File(s) | What was added |
|---|---------|----------------|
| R1 | `microstructure-alpha/research-protocol.md` (new Phase 0); pointer in `SKILL.md` "You Must Not" TA bullet + methodology pointer line | Reformalization Gate: folk/TA language inadmissible until restated as (a) sensor-expressible L1 state variable with units, (b) conditional-distribution claim, (c) falsifying forward test; worked example (prior-extreme tick distance via `execution/tick_size.py` grid → `quote_replenish_asymmetry` replenishment-intensity claim → `research/forward_ic.py` falsifier) |
| R2 | `research-protocol.md` (Phase 1 rider); one-line rider in `SKILL.md` Trend Mechanism Taxonomy | Archetype & structural-counterparty discipline: families encode mechanisms, not archetypes; each candidate states archetype (liquidity provision / informed-flow-following / argued third) + who funds the edge and why they trade against THIS signal; recorded in `structural_actor` (schema-optional; skill-level enforcement only per C3 — loader change backlogged) |
| R3 | `research-protocol.md` (L1 Data Limitations subsection); cross-pointer in `feature-engine/SKILL.md` catalog note | Mirage-risk ranking by observable family: LOW spread-state/trade-print, MEDIUM micro-price/imbalance, HIGH quote-flow/cancellation (`quote_flicker_rate`, `quote_hazard_rate`); high-mirage ⇒ stricter L2-loss accounting, never disqualification; rank never settles the archetype question |
| R4 | `research-workflow/SKILL.md` (new "Living Trial-Count Ledger" + control-table row) | Every construction/parameter/filter variant tried anywhere increments N (discarded ones included); the same N feeds `build_dsr_evidence(trials_count=N)` (`research/dsr.py`); every quoted Sharpe carries its noise ceiling `expected_max_sharpe(N, …)` (σ·√(2 ln N) asymptotic); ledger append-only; marked Not-shipped as tooling |
| R5 | `research-protocol.md` (Phase 3 test hierarchy, new item 6) | Zero-integrated-edge conservation check: one mandatory invariance check per signal — regime-balanced integrated edge must be fundable by the declared counterparty; distinguished from testing-validation's PnL-decomposition accounting identity |
| R6 | `research-protocol.md` (Phase 3 item 3 expanded); cross-link section in `testing-validation/SKILL.md` | Manual regime-stratified procedure: HMM dominant state (`services/regime_engine.py`) × `spread_z_30d` strata over horizon boundaries; per-stratum IC (`scripts/sensor_feature_ic.py`) + CPCV (`research/cpcv.py`); ~100-boundary minimum per-stratum rule (the ≥3-pair `spearman_ic` floor is computability, not adequacy); marked **Not shipped as a harness** |
| R7 | `microstructure-alpha/SKILL.md` (new "Pre-Trade Capacity & Crowding Envelope" + PORTFOLIO VIEW line); cross-link in `composition-layer/SKILL.md` | Proposal-time envelope: ADV-based midcap ceiling (distinct from risk-engine's policy-only runtime ADV limit), Sharpe-max vs profit-max target declaration, correlated-unwind reasoning; carries the OQ-3 caveat verbatim (runtime mechanism-share enforcement not active — C4) |
| R8 | `research-protocol.md` (Phase 4 robustness row + tick-constraint subsection); one-line research caveat in `regime-detection/SKILL.md` | Tick-grid artifact test (`execution/tick_size.py` anchor): spread-in-ticks distribution reported; single-grid-value "states" re-derived on spread ≥ ~4 ticks; scheduled tick-regime changes are pre-registered structural sample boundaries |
| R9 | `research-workflow/SKILL.md` (new status-vocabulary section); C1 rephrase in `microstructure-alpha/SKILL.md` | Closed pre-`alpha_id` status set {hypothesis, candidate, trap-quadrant, accepted, rejected}; "working" banned; trap-quadrant = statistically valid but execution-invalid; accepted = ready for RESEARCH→PAPER via `validate_gate` + `ResearchAcceptanceEvidence`; explicit disjointness from `ExperimentRecord.status` and the lifecycle SM. C1: "Label working theories as such" → "Label unvalidated theories as hypotheses" |
| R10 | **NEW** `microstructure-alpha/proposal-template.md`; registered in `.cursor/skills/README.md` supplementary table; pointers from `research-protocol.md` and research-workflow's handoff section | 12-section deliverable template (SIGNAL … NEXT ACTION) with per-section alpha-YAML field mapping; STATUS uses the R9 vocabulary; CAPACITY & CROWDING embeds the OQ-3 caveat; cost lines are one-way per R11 |
| R11 | `microstructure-alpha/SKILL.md` Cost Arithmetic section | The FQ-1 units-convention rider encoded (four clauses from `prompt_pack_00b_edge_units_convention.md`): one-way disclosure everywhere + B4 doubling consequence (`execution/position_manager.py`); `cost_basis` reserved; margin_ratio one-way ≈ 0.75× round-trip + ±0.05-absolute tolerance; per-fill realized-edge commensurability (forensics anchors) |
| E12 (OQ-6/D6) | `backtest-engine/fill-model.md` (new "Through-Fill Size Cap" section); caveat bullet in `backtest-engine/SKILL.md` Spread Crossing Logic | Resting through-fills partial-split under `through_fill_size_cap_enabled: true` (reference `platform.yaml`; code default false): `fill_qty = min(remaining, crossing_size)`, `PARTIALLY_FILLED` + `FILLED_BY_THROUGH`, remainder rests under the same order id (`execution/passive_limit_router.py`); the no-split rule scoped to submission-time marketability |

## Prefix additions

- **(a) Link-check extension:** attempted as the pure one-line
  `_DOC_FILES` glob addition; it surfaced two pre-existing citation
  failures (composition-layer's `loadings_dir/loadings.json`
  illustration; testing-validation's link to
  `docs/acceptance/v02_v03_matrix.md`, deleted-but-uncommitted in the
  working tree). Reverted and **backlogged** (entry 4 of the backlog)
  rather than fixing content beyond the approved scope /
  adjudicating an uncommitted deletion.
- **(b) Backlog file:** `docs/research/prompt_pack_backlog.md`
  created with the four separate-thread candidates (OQ-3 runtime cap
  closure; `Signal.strength` engine enforcement, 00e Track B;
  parity-manifest host/libm fingerprint FOLLOW-UP, 00d §4; C3
  `structural_actor` schema requirement) plus the deferred link-check
  extension.

## Conflicts left for decision

None. C1–C4 were dispositioned in the Task-3 prefix and applied as
approved; the only judgment call taken beyond the letter of the
approvals was including the two grep-found extra instances of the C2
erratum in the C2 commit (same defect, same fix, flagged in the
commit message).

## Guards

- `uv run pytest tests/docs/ -q` — 57 passed (after both commits).
- No Python was touched in the final edit set (the trial
  `test_internal_links.py` edit was reverted), so ruff/mypy are
  unaffected; canonical tables were linked, never duplicated; all
  described-but-unimplemented machinery is marked "Not shipped".
