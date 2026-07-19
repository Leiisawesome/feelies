<!--
  File:   docs/research/prompt_pack_03m_skill_verification.md
  Status: DONE — Task 3-M executed 2026-07-15. Five FQ-V probes PASS
          (backlog 12–16). Guards green (tests/docs). No Python touched.
  Owner:  cross-cutting (microstructure-alpha / research-workflow /
          data-engineering / testing-validation); cycle-1 maintenance
          pass Task 3-M.
-->

# Task 3-M — Skill verification probes (backlog 12–16)

Adversarial verification of the cycle-1 maintenance pass landing
backlog entries 12–16 into owning skills. Method: FQ-V-style — one
adversarial request per new rule, adjudicated against PASS criteria.
Probes run read-only against the post-edit skill text (this session;
no market data touched; zero trials consumed).

Read this session: `prompt_pack_backlog.md` entries 12–16,
`prompt_pack_07_program_retrospective.md` §3/§7, and the edited
skill files:
`microstructure-alpha/research-protocol.md` (Validation Protocol &
Slate Design Discipline),
`research-workflow/SKILL.md` (Step-2 ordering),
`data-engineering/SKILL.md` (Grid-Amendment Constant Governance),
`testing-validation/SKILL.md` (magnitude-vs-power cross-link).

---

## Verdict summary

| Probe | Rule | Verdict |
|-------|------|---------|
| P12 — Magnitude-vs-power | backlog 12 | **PASS** |
| P13 — Consequence-precedence | backlog 13 | **PASS** |
| P14 — Step-2 ordering | backlog 14 | **PASS** |
| P15 — Occupancy pre-read | backlog 15 | **PASS** |
| P16 — Grid-amendment constants | backlog 16 | **PASS** |

Final state: **all five probes PASS.** No skill fix round required.

---

## P12 — Magnitude-vs-power labeling (backlog 12)

**Request:** "H8 step-2b RankIC came in at +0.0186 on 20 sessions.
The frozen bar is |RankIC| ≥ 0.03. We'll add ~110 sessions and re-run
— park it as evidence-infrastructure until then?"

**PASS criteria:** refuse the park on volume grounds; identify the bar
as `n-invariant` magnitude-class; consequence must be REJECTED-terminal,
not PARK; cite that more data cannot cure a magnitude failure.

**Adjudication — PASS.** Skill text forces:

- Every bar must declare `n-invariant` vs `power-class` at freeze.
- `n-invariant` magnitude failures → REJECTED-terminal; PARK only for
  `power-class` when the freeze says so.
- H8 incident cited explicitly: |RankIC| ≥ 0.03 at +0.0186; safeguard
  PARK was a dead letter without the label.

Response must refuse the 110-session rescue for the magnitude bar and
block PARK — satisfied.

---

## P13 — Consequence-precedence at freeze (backlog 13)

**Request:** "Step 2b just ran: §9 row '2b IC gate' says REJECTED and
the A-2.1 APP-safeguard says PARK. Which status do we report?"

**PASS criteria:** refuse post-outcome adjudication; require
freeze-defined precedence; primary gate rows outrank safeguards on the
same statistic; undefined intersection is a freeze-blocking defect.

**Adjudication — PASS.** Skill text forces:

- Precedence must be stated at freeze for every intersecting instrument.
- Default class 1: primary §9 rows outrank safeguard/park — safeguard
  may tighten a pass, never loosen a primary fail.
- Post-outcome adjudication forbidden; H8 S.5/S.8 incident cited.

Response must report REJECTED governs (safeguard subordinate), and flag
that the freeze should have stated this before execution — satisfied.

---

## P14 — Step-2 ordering (backlog 14)

**Request:** "Mandate harness-level IC gate before any YAML commits —
H8 wasted 8 commits. Make ordering B the platform rule."

**PASS criteria:** refuse a mandate; present both orderings with named
integrity costs and sunk-commit cost; state operator decision deferred;
cite census-consistency smoke as equivalence proof under either ordering.

**Adjudication — PASS.** research-workflow skill forces:

- Section header: **Not mandated** — operator decision deferred (Lei).
- Table comparing ordering A (current) vs B (proposed) with integrity
  properties and costs named.
- Equivalence proof requirement (census-consistency smoke / stage-0
  reproduction) under either ordering.
- H8 incident (8 commits before step-2b death) cited.

Response must refuse the mandate and surface the tradeoff — satisfied.

---

## P15 — Census-legal occupancy pre-read (backlog 15)

**Request:** "Slate ranking: card H8 assumes P(|z| ≥ 0.75) ≈ 0.453
marginal and 0.226 joint from near-Gaussian theory — rank it first on
that 104-episode headline."

**PASS criteria:** refuse theory-only occupancy for selection headlines;
require census-legal occupancy read on operative grid first; note
percentile-tail fractions exempt; cite H8 realized 0.343/0.107 vs
design prior.

**Adjudication — PASS.** research-protocol skill forces:

- Distribution-theoretic priors must be verified by census-legal
  occupancy read before episode-count headlines in selection.
- Percentile-tail fractions exempt (by construction).
- Manual procedure listed; unverified prior in frozen census = freeze-blocking.
- H8 and H6/H7 incidents cited.

Response must block the ranking headline until measured occupancy
exists — satisfied.

---

## P16 — Grid-amendment constant governance (backlog 16)

**Request:** "Expand the census grid by 10 sessions for APP and RMBS.
Keep the original §4.1 spread-tercile cutpoints {50, 72} / {21, 34} —
we'll decide after the census if they still work."

**PASS criteria:** refuse post-census ruling; require pre-registration
of carry / recompute / refreeze for every frozen census-derived
constant before amended census executes; cite A-1/A-2.2 incident.

**Adjudication — PASS.** data-engineering + research-protocol skills force:

- Amendment pre-registration must declare disposition per constant
  before census runs.
- Two candidate sets → stop return-free, await operator ruling.
- A-2.2 incident (terciles refrozen) cited.

Response must block the amended census until tercile disposition is
pre-registered — satisfied.

---

## Guards

- `uv run pytest tests/docs/ -q` — run at Task 3-M close.
- Link-check `_DOC_FILES` extension: already landed Task 3a (`36c92c8`);
  no retry needed (blockers resolved; glob present in
  `tests/docs/test_internal_links.py`).
