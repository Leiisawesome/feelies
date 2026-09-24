# Decisions

Append-only. Decisions the spec did not cover, taken during the build. Each entry: id, date,
rung, the question, the decision, the reason (no reference to results), and whether the
spec was amended upstream. A decision that should have been in the spec gets a matching
edit to the spec file in a later docs rung, citing the entry.

| Id | Date | Rung | Question | Decision | Reason | Spec amended |
|---|---|---|---|---|---|---|
| D-01 | 2026-09-23 | P-10 | How are position moves carried? | moves carried as exact integer cents over the whole position (entry is an exact rational of partial fills; per-share ticks are not exact; thresholds compare total >= X*size*tick) | | pending docs rung |
| D-02 | 2026-09-23 | P-10 | What is the cell's fill source? | SlicePositionUpdate is the cell's fill source, own stream slice_position (PositionUpdate is symbol-net without strategy or fill detail; own stream keeps orchestrator numbering intact) | | pending docs rung |
| D-03 | 2026-09-23 | P-10 | How is the position engine enabled? | enable via build_platform(enable_position_engine=) until P-15 exit_policy; non-BACKTEST raises (no config field, so the config hash cannot move) | | pending docs rung |
| D-04 | 2026-09-24 | P-10 | Do the architecture gates apply to the new engine? | new engine's forbidden-reads rows, subscriber-engine pin 7->8, audit owner, and the mode guard placed in the mode seam | the architecture's own gates apply to a new engine; the guard moved rather than widening the seam test | pending docs rung |
| D-05 | 2026-09-24 | P-10 | What checks the position SUBSCRIPTIONS rows when the engine is off? | S15 builds with the engine off, so the position SUBSCRIPTIONS rows were verified by nothing | T7 runs the runtime-subset check on an enabled build | pending docs rung |
| D-06 | 2026-09-24 | P-10 | S14's dynamic probe builds the default platform, so a dark engine is never observed | the S14 replay builds with enable_position_engine=True; a negative probe proves it catches an engine-13 forbidden read | | pending docs rung |
| D-07 | 2026-09-24 | P-11a | D-01..D-06 recorded "pending docs rung" | spec amended: contracts.md (wiring, SlicePositionUpdate, cents moves and comparisons, enabling, mode seam, structural checks), battery.md (member 4 in cents, structural checks, stage B), amendments.md A-16/A-17, phase14 plan (P-10 done, P-11a, P-30 rescoped, parity facts, capture rule) | an append-only log is closed by a new row, not by rewriting old ones | yes |
