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
           (blocked on the passive fill-eligibility audit). Parameter calibration and the
           evaluation of whether the engine is better — campaign 14E, which gates campaign
           15 (evaluation.md §4). Fill model. Belief rail, alpha-decay gate. The G41/G42 meter.

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
           Every break is pre-registered (evaluation.md §2). An improved result is never a reason to accept one.

NON-CUTS:  No new exit authors outside engine 13. No change to engine 8 safety exits.
           No change to production alpha YAMLs. No sizing or allocator work.

PARITY FACTS (measured at P-10, census 2026-09-23/24):
           None of the 64 constants hashes the whole bus; each hashes one named stream,
           the trade journal, or the config. A new event type published on the bus moves
           none of them unless it changes fills. The event-manifest fingerprint
           (EXPECTED_MANIFEST_FINGERPRINT) is not one of the 64; P-10 moved it once by pin
           edit (ff2ca64c... -> 7a4739fe...). A new config field moves
           _BASELINE_CONFIG_HASH (one of the 64) unless omitted when at its default, the
           existing mechanism in PlatformConfig._to_dict. Enabled APP run at P-10: 20
           fills, net 103.93, trade hash unchanged.
           P-11 (book mark rule) may move unrealized PnL / equity constants; measured by
           capture, declared or reverted by the operator.

CAPTURE RULE (from P-10): every rung records whether the IB Gateway (port 4002) is up,
           and the pre and post captures must be taken in the same state; ten IB
           functional tests run only when it is up.
```

## Ladder

Each rung opens with a report-only census; the block is written from that evidence.

| Rung | Stage | Lands | Gate | Parity |
|---|---|---|---|---|
| P-00 | — | this plan and the spec pack (docs only) | ledger + docs tests green | hold |
| P-10 | surface | DONE (merged 6e9fa06f). Contract surface in one rung, because the static emission, S-09, S-12 and manifest checks make types, producers and subscribers one unit: five event types, wiring rows, streams `mark_rail` / `slice_position` / `position`, 13th independence module, `MarkRail` and `PositionEngine` stubs, `PositionRecordSink`, mode refusal in the seam, T1–T7 | T1–T7; S14 probes engine 13; enabled APP run unchanged | held; manifest pin moved |
| P-11a | docs | fold P-10 decisions D-01..D-06 into the spec and this plan (A-16, A-17) | docs tests | hold |
| P-11 | rail | book mark rule: executable-side valuation, retain last valid mark on crossed/locked/zero-side, stale flag; named `reference_mid` for sizing consumers the census identifies | engine 7 contract tests; pre-registered prediction per evaluation.md §2, including whether any fill moves | measured; operator declares or reverts |
| P-12 | rail | post-exit hypothetical views valued at the executable side, not the mid (D-23) | census; pre-registered prediction per evaluation.md §2 | measured |
| P-15 | schema | `exit_policy` in `alphas/SCHEMA.md` (schema bump), loader keys, load checks L1–L8, mode rule | fail-first per load check | hold |
| P-16 | docs | evaluation architecture: three oracles, pre-registered breaks, P-95, campaign 14E gate, stage-letter mechanism, fixture defect (D-14..D-20) | docs tests | hold |
| P-20 | A | synthetic tape generator and its own test | generator verified driftless, on lattice | hold |
| P-21a | A | DONE. Fixture schedule, stage-gate hook, markers, member-1 seams, D-29/D-32 | hook self-tests; fixture schedule | hold |
| P-21b | A | harness (scenarios.py), APP config, CI battery_real step; members 1, 2, 4 | 1, 2, 4-birth red NONVACUOUS; 4-rail green | hold |
| P-21c | A | spec closure for members 3, 5, 6 (contracts §9, D-40..D-48); docs only | docs tests | hold |
| P-21d | A | implemented (PR #257), pending merge. members 3, 5; tape injectors set_quote, excise | each red for its stated reason | hold |
| P-21e | A | implemented (PR pending), pending merge. member 6 spec closure; shift_from, remove_side_run; doc integrity; capture ignore | red for its stated reason | hold |
| P-21f | A | Member 6 tests (A1–A6, real + synthetic) + member 4 unusable-side clause; green_from per battery.md; red via NONVACUOUS | red via NONVACUOUS | hold |
| P-22 | A | broken engines B1–B11 | each caught by its named member | hold |
| P-30 | B | skeleton behaviour on the P-10 surface: stub cell born and closed from slice fills, stub gates, the two-phase step, snapshots to the sink; implements the contracts §8 seam PositionEngine(gate_order=...) (member 1 depends on it) | members 1, 2 green | hold |
| P-40 | C | rail complete (ages, absences, window, warm-up, worst-side, forced, dwelled); PlatformConfig position_rail_slippage_ticks and position_rail_dwell_ns (D-40). rail side usability per D-62: classify once in the orchestrator mark path, pass the result to store and rail; no second classify call site | + 4 (rail half), 9 | hold |
| P-50 | D | position cell: birth from fill, entry rational, excursion, extremes, deadline, states, closing record | + 4 (birth), 10, 11 | hold |
| P-51 | D | entry admission refusals and no-scale-in for owned alphas | member 10 refusal cases | hold |
| P-52 | D | invalidation intake; kernel stops emitting its own exit for owned slices | member 10, 5 (invalidation cases) | hold |
| P-60 | E | adverse gate (drawn level, blind limit, never-skips) | + 6, 8 (adverse half) | hold |
| P-61 | E | favorable gate (blocks, forms, arming) | + 6, 8 (favorable half), 7 | hold |
| P-62 | E | precedence and requirement path: `source_layer="POSITION"` accepted, MARKET, `ADVERSE_EXCURSION` in the stop-slippage set | all eleven green | hold |
| P-95 | close | attribution diff tool (evaluation.md §3), tested first on a constructed synthetic tape | classes exact on the constructed tape | hold |
| P-99 | close | CAMPAIGN CLOSE: battery green on the arbitrary config; position oracle pinned (APP 2026-03-26, bt_position_arbitrary_not_calibrated); P-95 report legacy vs engine-on, descriptive; exit mix reported (tripwire, not a dial); refusal and suppression counts reported | operator | hold |

Order inside a stage is fixed; stages do not overlap; no stage begins while an earlier
gate is red.

## Round trip (what comes back for review)

Test output verbatim, including which members are red and why. Decisions the spec did not
cover (logged in `decisions.md`, then fixed upstream in the spec). Places the implementer
believes the spec is wrong (run through the amendment rule). Not code for line review.
