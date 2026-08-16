# PHASE 2 — Engine contract sheets + unassigned responsibilities

**Runs in:** a fresh Claude chat, **not Cursor.** This is pure design; repo access anchors the contracts to what happens to exist today, which is the failure mode this phase must avoid.
**Output:** paste the result into `docs/architecture/target/out/phase2_contracts.md`
**Attach:** `00_CORE.md` + this file + `out/phase0_comprehension.md` + `out/phase1_plumbing.md`

---

Produce the target-state contract sheet for each of the 12 engines in CORE §E, then resolve each of the 7 unassigned responsibilities in CORE §F.

## Sheet format — instantiate exactly, once per engine

```
ENGINE:            [n. name]
LATENCY CLASS:     [hot | cold]  (per CORE §D)
OWNS:              [the responsibilities, restated as this engine's alone]
MUST NOT OWN:      [explicit prohibitions]
CONSUMES:          [named contracts, with staleness tolerance]
EMITS:             [named contracts, with units, timestamp semantics, provenance]
FORBIDDEN READS:   [engines/facts it may never read, and the enforcement mechanism]
STATE:             [mutable state held, and the deterministic reset path]
ON DEGRADED INPUT: [behavior; must be exposure-reducing]
ON EXCEPTION:      [contained | halt; must not be silent]
SUBSTITUTABILITY:  [what a drop-in replacement must satisfy — if it cannot be swapped
                    without breaking the contract, the boundary is not real]
CONFORMANCE TEST:  [the test that makes this sheet mechanical rather than aspirational]
GAP vs CURRENT:    [one line, citing Phase 0]
```

## Then, for each of CORE §F.1–7

```
RESPONSIBILITY:    [n. name]
OWNER ENGINE:      [exactly one, from §E]
WHY THIS ENGINE:   [the argument, not the assertion]
CONTRACT PUBLISHED:[what consumers see]
FAILURE BEHAVIOR:  [must be exposure-reducing and must emit]
DETERMINISM NOTE:  [how this survives replay — mandatory for F.2 and F.7]
```

## Pacing

**One engine per turn.** Do not produce twelve sheets in one response. After each sheet, stop and wait. The operator will say "next" or push back.

Take the §F resolutions after all twelve sheets, one per turn, in the same way.

## Standing checks while writing

- Any sheet that cannot be written without naming the live alpha is a defect — record it as one (CORE §I).
- Any sheet where `OWNS` overlaps another engine's `OWNS` violates CORE §C.6 — flag it rather than splitting the difference.
- If a responsibility fits no engine, or an engine carries two irreconcilable jobs, that is a **model finding** (CORE §A). Record it; do not force a fit.

**HARD STOP** after each sheet.
