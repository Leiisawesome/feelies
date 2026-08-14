# PHASE 0 — Comprehension lock

**Runs in:** Cursor, Agent mode, Opus.
**Output:** `docs/architecture/target/out/phase0_comprehension.md`
**Attach:** `00_CORE.md` + this file + `@src/feelies` + `@tools/arch/evidence`

---

You do not yet understand this codebase. Establish ground truth from source before any target-state opinion.

## Method — script-first, in two passes

**Pass 1 — code only.** Do not read `docs/`, `README`, or `docs/reviews/` in this pass. Reason from source and from the evidence files produced by `tools/arch/measure.py all`, which have already been generated and are in `tools/arch/evidence/`.

Where the pre-built evidence is insufficient, extend `tools/arch/measure.py` or add a new script under `tools/arch/`, run it, and commit the output as an evidence file. Do not read hundreds of files and report counts from memory — a number you did not measure is `INFERRED` at best.

**Pass 2 — documentation.** Only after Pass 1 is written. Read the §B documents and record every place they disagree with what Pass 1 found. Do not revise Pass 1; add a disagreement table.

## Deliverables

- **D0.1 Module inventory** — every module under `src/feelies/`, with its responsibility *as implemented*.
- **D0.2 Engine mapping** — modules → the 12 engines of CORE §E. Ownership quality per module: `Clear` / `Mixed` / `Misplaced` / `Unowned`.
- **D0.3 Contract inventory** — every event type on the bus; every direct cross-module call that bypasses it; publisher and subscriber sets; dispatch semantics (exact-type vs. subtype); whether any contract carries a version.
- **D0.4 Actual runtime path** — one real event traced end to end through the composed system, every hop named. The executed path, not the documented one. Mark which hops are synchronous and on the tick-critical path (CORE §D).
- **D0.5 Gate inventory** — every place the system can reject, downgrade, quarantine, halt, or skip, wherever it lives and however it is named. Include the alpha validation gate sequence and every inconsistency between its code definition and its documented definitions.
- **D0.6 Parity surface** — exactly what the determinism oracle hashes, at what granularity, what is outside the hash, and which engines' outputs are therefore unprotected.
- **D0.7 Unassigned-responsibility findings** — for each of CORE §F.1–7, name the current owner or record that none exists.
- **D0.8 Unknowns register** — what you could not determine and what would resolve it.
- **D0.9 Documentation disagreements** — Pass 2 only.

## P0 escalation

If you find a live correctness, determinism, causality, or exposure defect, report it **immediately, at the top of the output, in its own section**, with a proposed containment step. Do not bury it in an inventory table. Do not defer it to the migration plan.

## Constraints specific to this phase

- Inventory, not narrative. Tables and citations.
- **No target-state opinions.** Stating them here contaminates the measurement and they belong to later phases.
- Use explicit folder context, not codebase-wide semantic search. Semantic retrieval returns plausible partial context, which this phase cannot tolerate.

**HARD STOP.** Write the file, then stop.
