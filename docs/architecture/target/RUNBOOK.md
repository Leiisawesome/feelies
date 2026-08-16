# RUNBOOK — Feelies target-state architecture review

Eight phases. Each one: **setup → command → prompt → accept → commit.** Do them in order. Do not skip the accept step.

---

## Contents of this pack

```
prompts/00_CORE.md              standing contract v1.1 — attach to EVERY phase
prompts/P0_comprehension.md     phase task files, attach ONE per phase
prompts/P1_plumbing.md
prompts/P2_contracts.md
prompts/P3_flow_gating.md
prompts/P4_performance.md
prompts/P5_gap_table.md
prompts/P6_conformance.md
prompts/P7_migration.md
tools/arch/measure.py           measurement harness (stdlib only)
tools/arch/setup.sh             one-time setup
tools/arch/check_scope.sh       protocol guard, run at every hard stop
arch-guardrail.mdc              Cursor always-on rule
```

---

## STEP ONE — install the pack (do this once)

> **On Windows?** Use `INSTALL-WINDOWS.md` instead of this section — it is the same steps written out for PowerShell, with the Mark-of-the-Web and `python3`-vs-`python` traps handled.

From the repo root:

```bash
# 1. copy the pack in
mkdir -p docs/architecture/target/prompts tools/arch .cursor/rules
cp <pack>/prompts/*.md        docs/architecture/target/prompts/
cp <pack>/tools/arch/*.py     tools/arch/
cp <pack>/tools/arch/*.sh     tools/arch/
cp <pack>/arch-guardrail.mdc  .cursor/rules/

# 2. verify the pre-derived CONFIG still matches main
python3 tools/arch/measure.py discover

# 3. run setup
chmod +x tools/arch/*.sh
bash tools/arch/setup.sh
```

The CONFIG block in `measure.py` is **already filled in** from the repo — bus API, engine hints, all eleven `alpha_id`s, the symbol list. `discover` re-derives it and prints a paste-ready block; only edit CONFIG if `discover` disagrees with what is there.

`setup.sh` creates the branch `arch/target-design`, makes the directories, runs the full measurement pass, and commits the baseline.

**Baseline expected from a clean run** (as of 2026-08-14 — if yours differs materially, main has moved and that is worth knowing before Phase 0):

```
modules    196 files, 43,197 sloc     largest: kernel/orchestrator.py 4,778
imports    159 modules, 609 edges, 2 cycles
clock      22 wall-clock call sites   (engine 12:11, engine 1:5, engine 10:4, kernel:2)
nondet     34 candidates              (threading 17, id() 10, env 4, hash() 2, listdir 1)
bus        48 publish, 32 subscribe   (subscribe_all: 0 call sites — dead API)
handlers   16 non-bus dispatch sites
gates      153 guard-like functions, 1 silent except
alphaleak  2 LEAKS in core/platform_config.py
```

**Delete `arch-guardrail.mdc` when the review is finished.** It is `alwaysApply: true` and taxes every unrelated request.

---

## STEP TWO — the phase loop

Every phase follows the same five moves.

| Move | What you do |
|---|---|
| **New chat** | Always a fresh chat. Never continue across a hard stop — context compaction silently drops the protocol. |
| **Attach** | `00_CORE.md` + the one phase file + the listed prior outputs + the listed source folders. |
| **Paste the GO line** | Given below, per phase. One line. |
| **Accept** | Run the acceptance commands. If any fails, re-run the phase. |
| **Commit** | `git add docs/architecture/target/out && git commit -m "arch: phase N"` |

**Universal acceptance commands** — run both at every hard stop:

```bash
# macOS / Linux / Git Bash
bash tools/arch/check_scope.sh
python3 tools/arch/measure.py spotcheck docs/architecture/target/out/phaseN_<name>.md -n 5
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1
python tools\arch\measure.py spotcheck docs\architecture\target\out\phaseN_<name>.md -n 5
```

`check_scope.sh` fails if the agent edited production code. `spotcheck` samples five citations and greps them; **one miss means the whole phase output is untrusted and gets re-run.** That is the only thing that makes the `VERIFIED` label real.

---

## PHASE 0 — Comprehension lock

**Where:** Cursor, Agent mode, Opus, maximum reasoning.

**Before:** `python3 tools/arch/measure.py all` (setup.sh already did this; re-run if main has moved).

**Attach:** `@docs/architecture/target/prompts/00_CORE.md` `@docs/architecture/target/prompts/P0_comprehension.md` `@tools/arch/evidence` `@src/feelies`

**Paste:**

```
Run Phase 0 only, per the attached CORE and P0 files. Pass 1 first: code and
evidence files only, no docs/. Write the result to
docs/architecture/target/out/phase0_comprehension.md, then stop at the hard stop.
```

Then, in the **same chat**, after Pass 1 is written:

```
Now Pass 2. Read the CORE §B documents and append a disagreement table to the
same file. Do not revise Pass 1. Then stop.
```

**Accept when:**
- [ ] `check_scope.sh` passes
- [ ] `spotcheck` passes
- [ ] D0.1–D0.9 all present
- [ ] D0.6 states the parity surface and names which engines are unprotected
- [ ] D0.7 answers all seven CORE §F items
- [ ] Zero target-state opinions in the file
- [ ] Any P0 appears in its own section at the top

> **If D0.6 says any engine's output is outside the determinism hash, stop and tell me.** That finding constrains everything Phase 7 is allowed to touch, and may reorder the plan.

---

## PHASE 1 — Axis A: Plumbing

**Where:** Cursor, Agent mode, Opus.

**Attach:** `@…/00_CORE.md` `@…/P1_plumbing.md` `@…/out/phase0_comprehension.md` `@src/feelies/core` `@src/feelies/bus` `@src/feelies/kernel` `@src/feelies/bootstrap.py` `@tools/arch/evidence`

**Paste:**

```
Run Phase 1 only, per the attached CORE and P1 files. Write to
docs/architecture/target/out/phase1_plumbing.md, then stop at the hard stop.
```

**Accept when:**
- [ ] Both universal checks pass
- [ ] All 8 sections present
- [ ] Determinism budget table covers every listed source, each with a neutralizer **or** an explicit `OPEN DEFECT`
- [ ] Parity surface stated concretely, not described

---

## PHASE 2 — Engine contracts + unassigned responsibilities

**Where: a fresh Claude chat, NOT Cursor.** This is pure design. Repo access here anchors the contracts to what happens to exist, which is exactly the failure this phase must avoid.

**Upload:** `00_CORE.md`, `P2_contracts.md`, `out/phase0_comprehension.md`, `out/phase1_plumbing.md`

**Paste:**

```
Run Phase 2 per the attached CORE and P2 files. One engine contract sheet per
turn, starting with Engine 1. Stop after each sheet.
```

Then drive it with `next` / pushback, twelve times. Then:

```
Now the CORE §F resolutions, one per turn, starting with F.1.
```

**Accept when:**
- [ ] 12 sheets, every field populated
- [ ] 7 §F resolutions, each with exactly one owner
- [ ] No two engines' `OWNS` overlap
- [ ] No sheet requires naming the live alpha
- [ ] Model findings recorded, or explicitly none

Paste the assembled result into `out/phase2_contracts.md` and commit.

---

## PHASE 3 — Axes B, C, D

**Where: a fresh Claude chat, NOT Cursor.**

**Upload:** `00_CORE.md`, `P3_flow_gating.md`, `out/phase1_plumbing.md`, `out/phase2_contracts.md`

**Paste:**

```
Run Phase 3.1 only per the attached CORE and P3 files. Stop at the hard stop.
```

Then `Run 3.2.` then `Run 3.3.` — one at a time, reviewing between.

**Accept when:**
- [ ] Dependency direction rule is stated as an enforceable constraint, with a named tool
- [ ] Extension-point answer is specific enough to test at N = 2, 5, 20
- [ ] 12×12 forbidden-reads matrix complete, every cell has an enforcement mechanism
- [ ] Both gate ladders enumerated in the record format, total order, no ties
- [ ] Every gate's `ON UNKNOWN` is the exposure-reducing branch

Paste into `out/phase3_flow_gating.md` and commit.

---

## PHASE 4 — Axis E: Performance

**Where:** Cursor, Agent mode, Opus.

**Attach:** `@…/00_CORE.md` `@…/P4_performance.md` `@…/out/phase1_plumbing.md` `@…/out/phase2_contracts.md` `@…/out/phase3_flow_gating.md` `@src/feelies` `@tools/arch/evidence`

**Paste:**

```
Run Phase 4 only, per the attached CORE and P4 files. Write to
docs/architecture/target/out/phase4_performance.md, then stop at the hard stop.
```

**Accept when:**
- [ ] Both universal checks pass
- [ ] Hot-path allow list is a list, not a principle
- [ ] Every tick-path engine has a budget and a complexity class
- [ ] Unmeasured costs are labeled unmeasured, with the measurement specified
- [ ] Dead-computation candidates are flagged, not removed

---

## PHASE 5 — Gap table

**Where:** Cursor, Agent mode, Opus.

**Attach:** `@…/00_CORE.md` `@…/P5_gap_table.md` `@…/out` (all prior) `@src/feelies`

**Paste:**

```
Run Phase 5 only, per the attached CORE and P5 files. Re-verify every claim
against current source; do not carry Phase 0 forward unchecked. Write to
docs/architecture/target/out/phase5_gaps.md, then stop at the hard stop.
```

**Accept when:**
- [ ] Both universal checks pass — **run spotcheck with `-n 10` here**, this file is the plan's foundation
- [ ] One difference per row
- [ ] No proposed fixes anywhere in the file
- [ ] Every P0 has its own paragraph with containment
- [ ] Completeness count stated: targets in gap rows + targets in do-not-change = all targets

---

## PHASE 6 — Conformance suite

**Where:** Cursor, Agent mode, Opus.

**Attach:** `@…/00_CORE.md` `@…/P6_conformance.md` `@…/out` `@tests` `@tools/arch`

**Paste:**

```
Run Phase 6 only, per the attached CORE and P6 files. Write to
docs/architecture/target/out/phase6_conformance.md, then stop at the hard stop.
```

**Accept when:**
- [ ] Both universal checks pass
- [ ] Every CORE §C invariant maps to at least one test
- [ ] Every test states `FAILS TODAY: yes/no` — a suite where nothing fails today protects nothing
- [ ] Tests that are promotions of `tools/arch/` scripts are identified as such
- [ ] Three fixtures specified concretely enough to build

---

## PHASE 7 — Design thesis + migration plan

**Where:** Cursor, Agent mode, Opus, maximum reasoning.

**Attach:** `@…/00_CORE.md` `@…/P7_migration.md` `@…/out` (all)

**Paste:**

```
Run Phase 7 per the attached CORE and P7 files. Deliverable A (design thesis)
first, on its own — stop after it. Do not start the migration plan until I
accept the thesis.
```

Then `Now deliverable G.` and so on through I, J, K.

**Accept when:**
- [ ] Thesis fits one page and names what is most likely wrong
- [ ] Every step is independently shippable and revertible
- [ ] Every step names what it deletes; running net delta reported
- [ ] Conformance tests sequenced before the refactors they protect
- [ ] Every parity-surface step states parity impact with a reason
- [ ] Assumption register has ≥ 5 honest entries
- [ ] The §M definition-of-done checklist is fully checked

**Then the plan is locked.** Execution is a separate session with a separate prompt, written against the locked plan.

---

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| Agent edited `src/` | Action bias | `check_scope.sh` catches it → `git checkout -- src`, re-run phase |
| Agent ran into the next phase | Compaction dropped the stop | Revert chat to checkpoint, re-run with a shorter attach set |
| Citations don't resolve | Semantic search hallucination | `spotcheck` catches it → re-run phase with explicit `@Folders`, not `@Codebase` |
| Output reads like the docs | Read `docs/` in Pass 1 | Re-run Phase 0 Pass 1 with `docs/` excluded |
| Numbers with no evidence file | Model counted by reading | Reject; require a script under `tools/arch/` |
| Design cites the live alpha | Anchoring | Reject the sheet; CORE §I makes it a defect |
| Rules not loading in Agent mode | Legacy `.cursorrules` is ignored in Agent mode | Use `.cursor/rules/*.mdc` only |

## Model selection

Opus with maximum reasoning for Phases 0, 2, 3, 7 — inventory errors poison everything downstream, contract derivation compounds, and blast-radius classification is the judgment that decides whether a step is safe to ship. Phases 1, 4, 5, 6 are more mechanical but still benefit; there is no phase here where a cheaper model is the right trade.

The efficiency lever is not the model. It is that measurement goes to scripts and judgment goes to Opus.
