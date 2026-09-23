# Position engine — spec pack

Status: SPEC, not built. Scope: BACKTEST ONLY. Paper and live are separate campaigns.
Source design: "position engine v2" (design sessions of 2026-07-29 to 2026-08-13),
consolidated here with every rename applied and adapted to feelies. Every place this
pack departs from v2 is listed in `amendments.md`. Nothing here is a result.

Read in this order:

| File | What it holds |
|---|---|
| `README.md` | Scope, the five rules, what must not be built, status words, escalation |
| `contracts.md` | The components, their reads/emits/forbidden reads, with the reason for each constraint |
| `results.md` | Standing technical results the design rests on. Not re-derived, not relitigated |
| `battery.md` | The eleven battery members, the load-time checks, the broken engines, the amendment rule |
| `feed.md` | What the feed was measured to do, and what feelies does with it today |
| `amendments.md` | Every departure from v2, with its justification |
| `assumptions.md` | The assumption register. Append-only |
| `decisions.md` | Decisions the spec did not cover, taken during the build. Append-only |

Campaign plan: `docs/architecture/target/out/phase14_position_engine.md`.

---

## What is being built

Feelies today manages an open position only through the alpha's own FLAT signal. Every
other exit rule is off by default, opt-in for one alpha, or scattered across risk-side
authors with no single ranking. The position engine is the one owner of every open
position's life after its entry fill: it values the position honestly, bounds how long it
is held, decides when it leaves, and resolves competing reasons to leave into exactly one.

Five parts, three owners:

- **Mark rail** (engine 7, portfolio). Executable-side prices for each name, with the
  staleness facts that say whether to trust them. Reports; never judges.
- **Position cell** (engine 13, position). One per open strategy slice. The only object
  that holds a position's state. Excursion accounting, the deadline, invalidation intake,
  and exit precedence are pure functions inside it.
- **Favorable-excursion gate** (engine 13). Take-profit. Fail-passive: on bad data it
  abstains, because two other exits are still watching.
- **Adverse-excursion gate** (engine 13). Stop. Fail-safe: it never declines to answer,
  because nothing stands behind it.
- **Exit plan** (engine 9, execution). Turns the one exit requirement into orders. Engine 8
  (risk) keeps its veto and its safety exits, and outranks everything here.

## The five rules

1. **Any component, any order; opening one means declaring a contract.** Reads, emits,
   forbidden reads. The forbidden list does most of the work.
2. **Stub everything else, always.** The loop stays closed from the first rung.
3. **Assumptions are recorded where they are made**, in the register format in
   `assumptions.md`.
4. **Select on the battery only, never on results.** Profit is not a fitness signal until
   parameters are frozen from upstream measurement. A backtest improvement from moving an
   exit parameter is the sound of fitting, because exits cannot manufacture edge
   (`results.md` R1).
5. **Classify blast radius before every change.** A contract change re-runs the whole
   battery, not the members that look affected.

## Must not be built in this campaign

No fill model. No belief rail. No alpha-decay (hazard-rate) gate. No passive routing of
any exit this engine emits. No sizing, no allocator, no fees inside the cell. No
cross-name state. No caching of anything the spec says is recomputed. No fast paths that
skip an emission. No paper or live wiring. No retirement of an existing exit author
(that is campaign 5). An eager implementer adds these as improvements; each one is a
contract change and a STOP.

## Status words

For a component: `stub`, `contracted`, `built`, `calibrated`, `frozen`. Every component is
`contracted` at the start of the build. Nothing becomes `calibrated` in this campaign.
For a rung: `passed`, `reverted`, `blocked`. Never "working".

## Parameters in this campaign

Every parameter is arbitrary. The only config that may enable the engine is named
`configs/bt_position_arbitrary_not_calibrated.yaml`, and its curve provenance is the literal
`ARBITRARY_NOT_CALIBRATED`, which stamps every closing record and the run report. The
battery was built to be blind to whether the numbers are good; the name is what stops
anyone forgetting that.

## Escalate, do not decide

- Any diff touching a test that has already landed. Tests are fixed before the code they
  test; the implementer never edits them.
- Any battery member failing where the fix seems to be the member. Apply the amendment
  rule in `battery.md`.
- Any decision the spec does not cover. Write it in `decisions.md` and stop.
- Any parity constant moving.
- Anything on the must-not-be-built list.

## Standing limitation

The engine emits exit requirements. Engine 9 and the backtest router turn them into fills.
Nothing this engine produces is execution-validated, and that sentence travels with every
number, in the same breath.
