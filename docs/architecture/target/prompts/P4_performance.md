# PHASE 4 — Axis E: Performance and efficiency

**Runs in:** Cursor, Agent mode, Opus. Needs the repo to measure.
**Output:** `docs/architecture/target/out/phase4_performance.md`
**Attach:** `00_CORE.md` + this file + `out/phase1_plumbing.md` + `out/phase2_contracts.md` + `out/phase3_flow_gating.md`

---

Institutional grade means budgeted, not fast-feeling. Every number here is either measured or explicitly labeled a target.

## 1. Hot-path allow list

State explicitly what is permitted on the tick-critical path (CORE §D). Everything not listed is prohibited there. Start from this prohibition set and extend: logging with formatting, per-event dict construction, dynamic dispatch through registries, governance evaluation, disk I/O, serialization.

For each prohibition, cite whether the current code violates it (`path:symbol`, from evidence, not from reading).

## 2. Per-engine per-event budget

Allocate the total event budget across every engine on the tick-critical path. For each: budget, measured current cost, complexity class per event, and what makes it that class.

If the current cost is unmeasured, say so and specify the measurement rather than estimating.

## 3. Hot/cold partition

Governance, forensics, research, and reporting are cold. Name the boundary mechanism and prove it does not perturb determinism.

## 4. Budget breach behavior

Per CORE §F.6 there is no queue. State what the system does when an engine exceeds budget in live versus in replay, and confirm the two differ **only in observability, never in output**.

## 5. Measurement harness

Per-engine timing histograms, collected under replay, excluded from the determinism hash by construction. Specify the collection point, the storage, and the exclusion mechanism. Without measurement the budget is decoration.

## 6. Efficiency as deletion

List every computation whose output no consumer reads, citing evidence. An engine computing something nobody reads is the cheapest available speedup. Flag as removal candidates only — CORE §H forbids acting.

**HARD STOP.** Write the file, then stop.
