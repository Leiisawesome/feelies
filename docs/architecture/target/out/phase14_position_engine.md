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
| P-13 | A | implemented on exec/P-13. Causal regime calibration from the prior session (D-63), uncalibrated fallback at min(scales) (D-64), widened member 2 (D-65), one-time legacy-oracle re-pin (D-66) | pre-registered prediction; provenance 2026-03-25, n=50636 | declared break: fills 20→10, net 103.93→24.61, trade hash re-pinned |
| P-15 | schema | `exit_policy` in `alphas/SCHEMA.md` (schema bump), loader keys, load checks L1–L8, mode rule | fail-first per load check | hold |
| P-16 | docs | evaluation architecture: three oracles, pre-registered breaks, P-95, campaign 14E gate, stage-letter mechanism, fixture defect (D-14..D-20) | docs tests | hold |
| P-20 | A | synthetic tape generator and its own test | generator verified driftless, on lattice | hold |
| P-21a | A | DONE. Fixture schedule, stage-gate hook, markers, member-1 seams, D-29/D-32 | hook self-tests; fixture schedule | hold |
| P-21b | A | harness (scenarios.py), APP config, CI battery_real step; members 1, 2, 4 | 1, 2, 4-birth red NONVACUOUS; 4-rail green | hold |
| P-21c | A | spec closure for members 3, 5, 6 (contracts §9, D-40..D-48); docs only | docs tests | hold |
| P-21d | A | implemented (PR #257), pending merge. members 3, 5; tape injectors set_quote, excise | each red for its stated reason | hold |
| P-21e | A | implemented (PR #258), pending merge. member 6 spec closure; shift_from, remove_side_run; doc integrity; capture ignore | red for its stated reason | hold |
| P-21f | A | implemented (PR #260), pending merge. Member 6 tests (A1–A6, real + synthetic) + member 4 unusable-side clause; green_from per battery.md | red via NONVACUOUS (member 6) and UNUSABLE_SIDE (member 4 clause) | hold |
| P-22 | A | split: P-22s/P-22a1/P-22a2f/P-22a2/P-22b | see P-22s, P-62a, P-22a1, P-22a2f, P-22a2, P-22b | hold |
| P-22s | A | implemented (PR #261), pending merge. Spec closure G1–G9, member 11 pull-forward, member 1 immutability and member 2 D>0 clauses. Docs only. Parity prediction NONE; captures skipped. | docs tests | NONE |
| P-62a | A | implemented (PR #262), pending merge. Admit source_layer=POSITION on the engine-8 copy path (MARKET, slice-scoped, through check_order); ADVERSE_EXCURSION in the stop-slippage set. Prediction NONE. | POSITION requirement on the copy path; ADVERSE_EXCURSION in the stop-slippage set | NONE |
| P-22a1 | A | G10/N1–N7 spec, additive schema, engine/rail resolution, attribution, reference rail (D-62), import guard, member 1/2/11 clauses. Prediction NONE for the 64 constants. | S-09 pin moves as predicted; members 1/2/11 gated NONVACUOUS at A; member 4 rail and unusable-side green on the reference rail | NONE |
| P-22a2f | A | G11 rejected-exit re-emission, PRECONDITION level, m2 dwell and m11 constructions, A3 END_OF_TAPE branch, F-P13b strict xfail. Tests and spec only (D-106..D-109). | PRECONDITION red at every stage; members gate at A with PRECONDITION passing; 64/64 hold; baseline GREEN | hold |
| P-22a2 | A | implemented (PR pending), pending merge. Reference engine; members 1–6 and 11 green on the reference at stage E | stage E synthetic 44/44, real 9/9; stage A member outcomes unchanged except added self-tests | NONE |
| tooling | A | implemented (PR A #267, PR B #266), pending merge. Opt-in broker/network markers, paper guard, profile fingerprint, single-source pre-push gate, nightly dispatcher on main. Resolves D-110. Backlog: a permanent CI order check (pytest-randomly or a reversed pass). | opt-in hook; paper guard; prepush.py | NONE |
| P-22b | A | implemented (PR #268), pending merge. Broken engines B1–B11 killed by their named members; kill runner; battery holes J1–J6 closed | 11/11 PROPERTY kills; reference control 0 failures | NONE |
| S-1 | — | simulator timing census, report only: R1 fill-report latency is implicit; R2 aggressive fills are priced on the first quote at or after arrival; R3 ACKNOWLEDGED is published at clock C and stamped C plus fill latency; the knowledge-time invariant | report | hold |
| P-23 | — | knowledge-time domain and the R1–R3 fixes. Pre-registered break. Every platform-emitted timestamp_ns is the simulated clock at emission; market-derived records also carry the source quote's exchange time | timestamp_ns at or before the clock at publication | break |
| P-23a | — | implemented, pending merge. Two-class timestamps, causality invariants, publication-clock stamps, cross-class age compares. Pre-registered break of EXPECTED_MARKET_FILL_HASH and EXPECTED_RISK_VERDICT_HASH | I1 and I3 hold; I2 only PENDING; oracle 10 / 24.61 / 18f6bb4e | break |
| P-23b | — | implemented (PR #270), pending merge. R2 prices a deferred aggressive fill on the quote prevailing at arrival. Legacy oracle unchanged (10 / 24.61 / 18f6bb4e). | pre-registered break | break |
| P-23d | — | Option C (D-161, D-162). The drain uniform is keyed on market content only (symbol, vendor sequence number, exchange timestamp, side, level). Orders at the same side, level and event share one draw. `order_id` and `ticks_at_level` are not inputs. Order ids are unchanged. | operator exemption of the legacy oracle | break |
| P-23c1 | — | implemented, pending merge. GateDecision, DeRiskRequirement, and PositionSnapshot are action-class on the publication clock (D-168). The policy-deadline compare operand is unchanged. PENDING I2 is empty. Oracle unchanged: 10 / 26.61 / c95f4e5c. | PENDING empty; I2 holds on the reference run | hold |
| P-23c2 | — | implemented, pending merge. A held single-alpha signal is released only by an NBBOQuote of its own symbol, and is priced and sized from that quote (D-172). Global horizon closure is kept (D-173). Timer closure and immediate actuation are deferred (D-174). Oracle unchanged: 10 / 26.61 / c95f4e5c. | own-symbol release | hold |
| P-23e | — | implemented, pending merge. One regime calibration per symbol, fitted on that symbol's own prior-session quotes, with the cap applied per symbol (D-175). D-63's lookahead rule is unchanged (D-176). The pooled fit is only the fallback for a symbol with no own prior quotes (D-177). Oracle unchanged: 10 / 26.61 / c95f4e5c. | per-symbol prior-session prefix | hold |
| P-23f | — | implemented, pending merge. An unset backtest session_open anchors the horizon grid at the exchange regular-session open (D-178). Third D-66 exemption reserved: 10 / 26.61 / ab3a2b3f, replacing c95f4e5c. The operator declares the break at merge. | exchange-open grid | break |
| P-23g | — | implemented, pending merge. A boundary is emitted once, in order, with content as of the boundary time (D-182). Window statistics use one reduction (D-183). Locked level-3 snapshot hash break under D-143 (D-184): 251cc109 → f8824e5a, 14 snapshots, windowed values only. Legacy oracle unchanged: 10 / 26.61 / ab3a2b3f. Universe-independence is tested with risk limits non-binding (D-185). | boundary-time content | break |
| P-23b2 | — | DONE (merged a2f1fa32, PR #278). R1 closed: fill_report_latency_ms, default None. | parameter plus sweep | hold |
| P-23b3 | — | DONE (merged 8277290f, PR #280). F-P23b-a closed: a marketable arrival limit takes the arrival book. | taker at arrival | hold |
| P-23c | — | position engine on action time: rail visibility time, engine records and the horizon compare; contract, reference, and battery; pre-registered known-answer shifts. Also F-P23d-h: `horizon_scheduler.py:259` closes every configured symbol's horizon on any symbol's event. | known-answer shifts | break |
| P-23a2 | — | action-time producer sweep: the KNOWN_NONCLOCK sites except the IB router; per-site unit tests; pre-registered; shrinks the ratchet to empty. Also `_cached_real` lru key `fraction: float` (±0.0), left unfixed by P-23a G | ratchet empty | hold |
| P-30 | B | skeleton behaviour on the P-10 surface: stub cell born and closed from slice fills, stub gates, the two-phase step, snapshots to the sink; implements the contracts §8 seam PositionEngine(gate_order=...) (member 1 depends on it). Conformance: the production engine's subscriptions are exactly contracts §0's list (MarkRailUpdate, SlicePositionUpdate, Signal) (D-135). PositionClosed has no constructor in src (D-145); the production constructor is in scope here | members 1, 2 green | hold |
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
