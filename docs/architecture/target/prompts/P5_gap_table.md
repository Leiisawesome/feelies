# PHASE 5 — Gap table

**Runs in:** Cursor, Agent mode, Opus. Every row needs live evidence.
**Output:** `docs/architecture/target/out/phase5_gaps.md`
**Attach:** `00_CORE.md` + this file + all of `out/phase0` … `out/phase4` + `@src/feelies`

---

One table. Every row is a single, independently-addressable difference between measured current state and the target specified in Phases 1–4.

## Row format

| Field | Content |
|---|---|
| `ID` | `G-001`, stable, referenced by Phase 7 |
| `Engine / Axis` | which of CORE §E or the five axes |
| `Target` | the specific target-state statement, cited to its phase and section |
| `Current` | what the code actually does |
| `Evidence` | `path:symbol` or `path:line`, plus `VERIFIED` / `INFERRED` / `ASSUMED` |
| `Invariant at risk` | CORE §C.1–11, by number |
| `Severity` | `P0` correctness / determinism / causality / exposure · `P1` ownership / extensibility · `P2` naming / docs |
| `Blast radius` | `local` / `boundary` / `platform-wide` |

## Rules for this phase

- **Re-verify.** Do not carry a Phase 0 claim into a gap row without re-checking it against current source. Phase 0 may be weeks old and main has moved.
- **One difference per row.** A row that describes two problems cannot be scheduled, sized, or reverted independently.
- **No proposed fixes.** Fixes are Phase 7. A gap row that contains a solution biases the ordering before the ordering is done.
- **Every P0 gets its own paragraph** below the table: what breaks, under what conditions, and what containment is available today.
- **Gaps that are already fine are findings too.** If a target is already met, do not create a row — record it in the do-not-change candidate list at the bottom of the file.

## Completeness check before you stop

Every target statement in Phases 1–4 is either in a gap row or in the do-not-change candidate list. Nothing is unaccounted for. State the count of each.

**HARD STOP.** Write the file, then stop.
