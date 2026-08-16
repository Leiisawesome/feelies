# PHASE 1 — Axis A: Plumbing (the deterministic substrate)

**Runs in:** Cursor, Agent mode, Opus.
**Output:** `docs/architecture/target/out/phase1_plumbing.md`
**Attach:** `00_CORE.md` + this file + `out/phase0_comprehension.md` + `@src/feelies/core` `@src/feelies/bus` `@src/feelies/kernel` `@src/feelies/bootstrap.py` + `@tools/arch/evidence`

---

Specify the target-state substrate. This axis is contract-independent — it comes before the engine contract sheets on purpose. For each item: state the target, cite the current state from Phase 0 or fresh evidence, and mark `matches target` / `gap`.

## 1. Clock discipline

Event time vs. ingest time vs. wall time. One clock authority. No engine reads the wall clock on the tick-critical path — state the **enforcement mechanism**, not the convention. Evidence: `tools/arch/evidence/clock.json`.

## 2. Sequencing and tie-breaking

The total order rule over concurrent events. The deterministic tie-break key. The resequencing window policy, including what happens to a late arrival outside the window.

## 3. Bus semantics

Exact-type vs. subtype dispatch and the failure mode of each. Whether subscription registration order affects output. Re-entrancy rules. Whether an engine may publish from within its own handler.

## 4. Identity and idempotency

Event, order, and correlation ID generation must be replay-stable: no UUID4, no hash-seed dependence, no address-derived identity. State duplicate-delivery semantics. Order IDs must additionally satisfy exactly-once submission across restart and reconnect.

## 5. State ownership and reset

Every engine declares its mutable state and a deterministic reset path. The warm-start vs. cold-start contract, and which one replay uses.

## 6. Parity surface

Exactly what the determinism oracle hashes, at what granularity, and what is deliberately outside it (timing measurements, log formatting) with the rationale. **If Phase 0 D0.6 found any engine's output outside the hash, say so here in its own subsection and state what it would take to bring it in** — that finding constrains everything the migration plan is allowed to touch.

## 7. Configuration and manifest fingerprinting

What is inside the fingerprint and what is not.

## 8. Schema versioning mechanics

Resolves CORE §F.7. Contract version placement, the compatibility rule, and the replay guarantee under evolution. State which parity hashes survive a schema change and which are expected to break.

## Required artifact — the determinism budget

A table: **source of nondeterminism → neutralizer → enforcing check → current status**. Cover at minimum: hash seed, dict iteration order, set iteration order, float reduction order and any parallel reduction, RNG streams and seeding, wall clock reads, thread and async scheduling, filesystem enumeration order, network arrival order, ID generation, dependency versions, locale and timezone, cache and warm-start state, symbol-identity resolution.

A source with no named neutralizer is an **open defect**, not an accepted risk. Say so in that column.

**HARD STOP.** Write the file, then stop.
