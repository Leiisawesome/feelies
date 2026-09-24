# Audit: position engine (engine 13)

Scope: `src/feelies/position/`, `src/feelies/portfolio/mark_rail.py`, and the position engine
event types in `src/feelies/core/events.py`.
Authority: `docs/architecture/target/position_engine/` — `contracts.md` (reads, emits, forbidden
reads, step order, precedence), `battery.md` (the eleven members, load checks, broken engines),
`results.md`, `amendments.md`.
Audit questions: Does any component read something its contract forbids? Is any number
accumulated that the contract says is recomputed? Does the resolve phase change a published
value? Is any exit booked at a configured level instead of an observed quote? Does any tie
resolve toward the favorable exit? Is anything filtered, defaulted or cleaned that the contract
says is passed through? Is there any path that emits a second exit requirement for one episode?
Status: dark in BACKTEST; refused in PAPER/LIVE.

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |

## Working method

Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
