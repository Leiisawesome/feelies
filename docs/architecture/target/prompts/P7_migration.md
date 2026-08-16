# PHASE 7 — Design thesis and migration plan

**Runs in:** Cursor, Agent mode, Opus, maximum reasoning. This is the judgment call that determines whether each step is safe to ship.
**Output:** `docs/architecture/target/out/phase7_migration.md`
**Attach:** `00_CORE.md` + this file + all of `out/phase0` … `out/phase6`

---

Five deliverables in this phase, in this order.

## A. Design thesis — one page, first

The target architecture in a paragraph. The three decisions it turns on. The one thing most likely to be wrong about it.

Write this **before** the plan. If the thesis cannot be stated in a page, the design is not finished and the plan will encode that confusion.

## G. Migration plan

Ordered steps. Conformance tests (Phase 6) come before the refactors they protect — sequence accordingly.

```
STEP:            [S-01]
CLOSES:          [gap IDs from Phase 5]
PROBLEM:         [and the CORE §C invariant affected]
FILES:           [exact paths and symbols]
WHY THIS OWNER:  [why the target ownership is superior to today's]
REFACTOR PATH:   [smallest safe sequence of edits]
BLAST RADIUS:    [local | boundary | platform-wide]
VALIDATED BY:    [tests and parity checks that must pass]
PARITY IMPACT:   [hashes expected to hold | hashes expected to break, and why]
DELETES:         [what this step removes — modules, symbols, branches]
NET DELTA:       [+/- modules, +/- public symbols, +/- branch points]
ROLLBACK:        [exact revert procedure]
```

Hard requirements on the plan:

- Every step is **independently shippable and independently revertible**. A step that only works if the next one lands is two steps merged.
- Every step names what it deletes. A step with an empty `DELETES` needs a justification under CORE §G.10.
- Report the **running net delta** in modules, public symbols, and branch points across the whole plan.
- Order by risk, not by engine number: P0s and the conformance tests that detect them come first; `platform-wide` blast radius comes last unless a P0 forces it earlier.
- Any step touching the parity surface (Phase 1 §6) states its parity impact explicitly. "Hashes will change" without an accompanying reason is a blocker, not a note.

## I. Do-not-change list

Boundaries that are already correct, promoted from the Phase 5 candidate list. Being sound is a finding. State why each is sound and what would make it stop being sound.

## J. Assumption and unknowns register

Every entry: assumption / why it was necessary / what would falsify it / blast radius if wrong. **A register with fewer than five entries is not honest** — say what you are unsure about.

## K. Model findings

Any place the 12-engine decomposition itself does not fit, with evidence. Empty is an acceptable and expected answer; a forced fit is not.

---

## Closing check — Definition of done (CORE §M)

State explicitly whether each holds:

- [ ] Every deliverable in CORE §K exists
- [ ] Every CORE §F item has exactly one named owner
- [ ] Every CORE §C invariant has a named enforcing test in Phase 6
- [ ] Every Phase 5 gap has a Phase 7 step, or an explicit deferral with a reason
- [ ] Assumption register is non-empty and honest

If any is unchecked, say which and stop. Do not declare the plan locked.

**HARD STOP.** The plan is now locked. Execution is a separate session with a separate prompt.
