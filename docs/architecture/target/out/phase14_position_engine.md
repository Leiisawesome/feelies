# Phase 14 — Position engine (backtest)

Spec: `docs/architecture/target/position_engine/` (read `README.md` first).
Ledger: `docs/architecture/target/out/exec/LEDGER.md`. Rung ids `P-nn`.

```
CAMPAIGN:  Position engine, backtest only
BASE:      e2b2745fdfd7717e06f9af2fa76a1cf21aeaf9af (main = arch/exec, PR #248 merged)

CLOSES:    Position management beyond the alpha's FLAT signal, for alphas that declare
           exit_policy, in BACKTEST: honest executable-side marks with staleness facts
           (engine 7), one position cell per owned slice, fail-safe stop, fail-passive
           take-profit, declared deadline, invalidation intake, total exit precedence,
           write-once closing records, and the eleven-member battery green.
           Engine 7 contract debt: crossed/locked/zero-side quotes move the book mark
           today (phase2 L733/L765).

DOES NOT CLOSE:
           Paper/live wiring and the live sequence-gap defect (feed.md F1) — separate
           campaign. Retiring STOP_EXIT / trailing / HARD_EXIT_AGE / hazard / deferral
           authors — campaign 15, after this one is green. Passive routing of any exit
           (blocked on the passive fill-eligibility audit). Parameter calibration (phase 2
           measurement). Fill model. Belief rail, alpha-decay gate. The G41/G42 meter.

STANDING INVARIANTS:
           Oracle frozen at exec-tools-v1. Never run scripts/rebaseline_parity_hashes.py.
           Every rung takes pre-<id> and post-<id> captures (tests/docs/
           test_exec_ledger_captures.py enforces it) and holds parity against the latest
           capture unless the rung is marked PARITY: declared-break and the operator
           declares it. The engine lands dark: no production config enables it; only
           configs/bt_position_arbitrary_not_calibrated.yaml and test fixtures may.
           Zero engine-to-engine import pairs; engine 13 imports core only.
           Tests land before the code they test and are not edited by build rungs.
           Commit to exec/<id> only; merge --no-ff; draft PR per cycle; Bugbot Autofix off.

NON-CUTS:  No new exit authors outside engine 13. No change to engine 8 safety exits.
           No change to production alpha YAMLs. No sizing or allocator work.

PARITY RISK TO MEASURE, NOT ARGUE:
           Adding core event types may move the event-manifest fingerprint (S-17a folds
           Event field sets into it) even while every trade hash holds. The first rung
           that adds an event type measures this first; if the fingerprint moves, the
           rung stops and the operator decides whether to declare a manifest-only break.
           P-11 (book mark rule) may move unrealized PnL / equity constants; measured by
           capture, declared or reverted by the operator.
```

## Ladder

Each rung opens with a report-only census; the block is written from that evidence.

| Rung | Stage | Lands | Gate | Parity |
|---|---|---|---|---|
| P-00 | — | this plan and the spec pack (docs only) | ledger + docs tests green | hold |
| P-10 | rail | `MarkRailUpdate` core event; engine 7 rail module emitting only when the engine is enabled | rail unit tests; manifest fingerprint measured | hold, or stop on fingerprint |
| P-11 | rail | book mark rule: executable-side valuation, retain last valid mark on crossed/locked/zero-side, stale flag; named `reference_mid` for sizing consumers the census identifies | engine 7 contract tests | measured; operator declares or reverts |
| P-15 | schema | `exit_policy` in `alphas/SCHEMA.md` (schema bump), loader keys, load checks L1–L8, mode rule | fail-first per load check | hold |
| P-20 | A | synthetic tape generator and its own test | generator verified driftless, on lattice | hold |
| P-21 | A | fixture alpha; the six blocking members, red | each red for the stated reason, quoted | hold |
| P-22 | A | broken engines B1–B11 | each caught by its named member | hold |
| P-30 | B | 13th independence set in `pyproject.toml` and the import pins; skeleton: stub rail consumer, stub cell, stub gates, two-phase step, sinks, events | members 1, 2 green | hold (fingerprint as P-10) |
| P-40 | C | rail complete (ages, absences, window, warm-up, worst-side, forced, dwelled) | + 4 (rail half), 9 | hold |
| P-50 | D | position cell: birth from fill, entry rational, excursion, extremes, deadline, states, closing record | + 4 (birth), 10, 11 | hold |
| P-51 | D | entry admission refusals and no-scale-in for owned alphas | member 10 refusal cases | hold |
| P-52 | D | invalidation intake; kernel stops emitting its own exit for owned slices | member 10, 5 (invalidation cases) | hold |
| P-60 | E | adverse gate (drawn level, blind limit, never-skips) | + 6, 8 (adverse half) | hold |
| P-61 | E | favorable gate (blocks, forms, arming) | + 6, 8 (favorable half), 7 | hold |
| P-62 | E | precedence and requirement path: `source_layer="POSITION"` accepted, MARKET, `ADVERSE_EXCURSION` in the stop-slippage set | all eleven green | hold |
| P-99 | close | CAMPAIGN CLOSE: battery green on the arbitrary config, exit mix reported (tripwire, not a dial), refusal and suppression counts reported | operator | hold |

Order inside a stage is fixed; stages do not overlap; no stage begins while an earlier
gate is red.

## Round trip (what comes back for review)

Test output verbatim, including which members are red and why. Decisions the spec did not
cover (logged in `decisions.md`, then fixed upstream in the spec). Places the implementer
believes the spec is wrong (run through the amendment rule). Not code for line review.
