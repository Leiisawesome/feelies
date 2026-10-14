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
           Every rung runs PYTHONHASHSEED=0 uv run pytest tests/conformance/test_cap_neutral_universe.py -q -m universe_check locally (not in CI; needs the eight-name cache).

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
| P-21d | A | DONE (merged dfc9b9a5, PR #257). members 3, 5; tape injectors set_quote, excise | each red for its stated reason | hold |
| P-21e | A | DONE (merged 37aa506c, PR #258). member 6 spec closure; shift_from, remove_side_run; doc integrity; capture ignore | red for its stated reason | hold |
| P-21f | A | DONE (merged fa537c59, PR #260). Member 6 tests (A1–A6, real + synthetic) + member 4 unusable-side clause; green_from per battery.md | red via NONVACUOUS (member 6) and UNUSABLE_SIDE (member 4 clause) | hold |
| P-22 | A | split: P-22s/P-22a1/P-22a2f/P-22a2/P-22b | see P-22s, P-62a, P-22a1, P-22a2f, P-22a2, P-22b | hold |
| P-22s | A | DONE (merged 3b3beced, PR #261). Spec closure G1–G9, member 11 pull-forward, member 1 immutability and member 2 D>0 clauses. Docs only. Parity prediction NONE; captures skipped. | docs tests | NONE |
| P-62a | A | DONE (merged 6c00c5d0, PR #262). Admit source_layer=POSITION on the engine-8 copy path (MARKET, slice-scoped, through check_order); ADVERSE_EXCURSION in the stop-slippage set. Prediction NONE. | POSITION requirement on the copy path; ADVERSE_EXCURSION in the stop-slippage set | NONE |
| P-22a1 | A | G10/N1–N7 spec, additive schema, engine/rail resolution, attribution, reference rail (D-62), import guard, member 1/2/11 clauses. Prediction NONE for the 64 constants. | S-09 pin moves as predicted; members 1/2/11 gated NONVACUOUS at A; member 4 rail and unusable-side green on the reference rail | NONE |
| P-22a2f | A | G11 rejected-exit re-emission, PRECONDITION level, m2 dwell and m11 constructions, A3 END_OF_TAPE branch, F-P13b strict xfail. Tests and spec only (D-106..D-109). | PRECONDITION red at every stage; members gate at A with PRECONDITION passing; 64/64 hold; baseline GREEN | hold |
| P-22a2 | A | DONE (merged e5e363f2, PR #265). Reference engine; members 1–6 and 11 green on the reference at stage E | stage E synthetic 44/44, real 9/9; stage A member outcomes unchanged except added self-tests | NONE |
| tooling | A | DONE (merged 25215bc8, PR #267; merged eae14b6c, PR #266). Opt-in broker/network markers, paper guard, profile fingerprint, single-source pre-push gate, nightly dispatcher on main. Resolves D-110. Backlog: a permanent CI order check (pytest-randomly or a reversed pass). | opt-in hook; paper guard; prepush.py | NONE |
| P-22b | A | DONE (merged e98cff2d, PR #268). Broken engines B1–B11 killed by their named members; kill runner; battery holes J1–J6 closed | 11/11 PROPERTY kills; reference control 0 failures | NONE |
| S-1 | — | simulator timing census, report only: R1 fill-report latency is implicit; R2 aggressive fills are priced on the first quote at or after arrival; R3 ACKNOWLEDGED is published at clock C and stamped C plus fill latency; the knowledge-time invariant | report | hold |
| P-23 | — | DONE (D-189). R1 by P-23b2 (merged a2f1fa32, PR #278). R2 by P-23b (merged 3eae11bd, PR #270). R3 by P-23a (merged 02d4719f, PR #269; f643416b): ACKNOWLEDGED stamps the publication clock (backtest_router.py:240). Every platform-emitted timestamp_ns is the simulated clock at emission; market-derived records also carry the source quote's exchange time. | timestamp_ns at or before the clock at publication | break |
| P-23a | — | DONE (merged 02d4719f, PR #269). Two-class timestamps, causality invariants, publication-clock stamps, cross-class age compares. Pre-registered break of EXPECTED_MARKET_FILL_HASH and EXPECTED_RISK_VERDICT_HASH | I1 and I3 hold; I2 only PENDING; oracle 10 / 24.61 / 18f6bb4e | break |
| P-23b | — | DONE (merged 3eae11bd, PR #270). R2 prices a deferred aggressive fill on the quote prevailing at arrival. Legacy oracle unchanged (10 / 24.61 / 18f6bb4e). | pre-registered break | break |
| P-23d | — | Option C (D-161, D-162). The drain uniform is keyed on market content only (symbol, vendor sequence number, exchange timestamp, side, level). Orders at the same side, level and event share one draw. `order_id` and `ticks_at_level` are not inputs. Order ids are unchanged. | operator exemption of the legacy oracle | break |
| P-23c1 | — | DONE (merged e1e636a4, PR #272). GateDecision, DeRiskRequirement, and PositionSnapshot are action-class on the publication clock (D-168). The policy-deadline compare operand is unchanged. PENDING I2 is empty. Oracle unchanged: 10 / 26.61 / c95f4e5c. | PENDING empty; I2 holds on the reference run | hold |
| P-23c2 | — | DONE (merged 1c6d9263, PR #273). A held single-alpha signal is released only by an NBBOQuote of its own symbol, and is priced and sized from that quote (D-172). Global horizon closure is kept (D-173). Timer closure and immediate actuation are deferred (D-174). Oracle unchanged: 10 / 26.61 / c95f4e5c. | own-symbol release | hold |
| P-23e | — | DONE (merged 6a3928f4, PR #274). One regime calibration per symbol, fitted on that symbol's own prior-session quotes, with the cap applied per symbol (D-175). D-63's lookahead rule is unchanged (D-176). The pooled fit is only the fallback for a symbol with no own prior quotes (D-177). Oracle unchanged: 10 / 26.61 / c95f4e5c. | per-symbol prior-session prefix | hold |
| P-23f | — | DONE (merged 70842f9d, PR #275). An unset backtest session_open anchors the horizon grid at the exchange regular-session open (D-178). Third D-66 exemption reserved: 10 / 26.61 / ab3a2b3f, replacing c95f4e5c. The operator declares the break at merge. | exchange-open grid | break |
| P-23g | — | DONE (merged 44ebba03, PR #276). A boundary is emitted once, in order, with content as of the boundary time (D-182). Window statistics use one reduction (D-183). Locked level-3 snapshot hash break under D-143 (D-184): 251cc109 → f8824e5a, 14 snapshots, windowed values only. Legacy oracle unchanged: 10 / 26.61 / ab3a2b3f. Universe-independence is tested with risk limits non-binding (D-185). | boundary-time content | break |
| P-23g2 | — | DONE (merged 15178f03, PR #277). F-P23g-17 closed: eviction waits at the oldest unfinalised boundary; finalize still reads the closed window. | bit-identical to P-23g | hold |
| P-23b2 | — | DONE (merged a2f1fa32, PR #278). R1 closed: fill_report_latency_ms, default None. | parameter plus sweep | hold |
| P-23b3 | — | DONE (merged 8277290f, PR #280). F-P23b-a closed: a marketable arrival limit takes the arrival book. | taker at arrival | hold |
| P-23c | — | DONE by P-23c1 (merged e1e636a4, PR #272) and P-23c2 (merged 1c6d9263, PR #273) (D-189). Remainder deferred, not done: timer closure and immediate actuation (D-174), global closure kept (D-173), session-close flush (F-P23g-2). | known-answer shifts | break |
| P-23a2 | — | DONE (merged 566b4f6c, PR #281). Fill acks publish on the clock. The ratchet is the five remaining rows. | five rows | hold |
| T-2 | — | DONE (merged 2c753a75, PR #279). Check-job Tests is pytest -n 4; event-cache steps are restore-only (LEDGER.md:32782). | CI guard | hold |
| P-24 | — | DONE (merged 6f186503db9132fd31ed580d5b808856156c19b1, PR #283). Economic trade hash on the exempt route (four pins); universe check committed (marker universe_check, run locally each rung); content-keyed ids deferred to the off-ladder row with three triggers (D-190). | census | hold |
| P-29 | docs | DONE (merged 469d1bc62e0b41adb41bb9cbf2f0d328efbfcf7e, PR #282). Plan reconciled with the ledger; P-23 and P-23c closed with deferrals; member 2 levels stated (B; dwell clause C per D-87); rows P-24, P-39, P-49, P-59 and the off-ladder table added (D-189) | docs tests; R4 none | hold |
| P-29b | — | in review. stage-hook capability tags (D-192); member-1 hardening: sinks against bus, two gates per snapshot, two symbols open at once; D-191 moved here and followed by the reference; m5 empty path NONVACUOUS; m6 A2 tagged gate_fire; B12–B14; R-FIX economic re-pin (D-193). | H1–H7; member 1; B12–B14 | declared break: ECONOMIC_TRADE_HASH_RFIX |
| P-30 | B | skeleton behaviour on the P-10 surface: stub cell born and closed from slice fills, stub gates, the two-phase step, snapshots to the sink; implements the contracts §8 seam PositionEngine(gate_order=...) (member 1 depends on it). Conformance: the production engine's subscriptions are exactly contracts §0's list (MarkRailUpdate, SlicePositionUpdate, Signal) (D-135). PositionClosed has no constructor in src (D-145); the production constructor is in scope here. The P-30 census closes contracts.md:197 by naming the field behind birth_fill_sequence (F-P24-15); candidates and stability per P-24 Part 2 R4. Paused for P-29b; D-191 moved to P-29b; Part 2 blocked on F-P30-12..18. Carry into the resumed census: (1) engine.py rewritten in a new session from contracts.md and battery.md, without opening the reference; (2) T2 keeps the equal-stamp rebirth (F-P29b-2); T5 checks cross-cell step order with two strategies on one symbol (F-P29b-13); (3) retire the post-init clock setattr for both engines; the reference constructor is the one test-side file (F-P29b-1, F-P30-18); (4) entry_spread_ticks sign: contracts.md:199-200 says paying − valuation; the reference stores the positive width (reference/engine.py:559) (F-P29b-12); (5) m4_birth_syn_partial passes before D on the saved skeleton, which computes the birth formula (F-P29b-4, F-P29b-11). | members 1, 2 green | hold |
| P-39 | — | Member 9 authoring under the stage-A rule (D-189): spec closure; reference engine extended; at least one broken engine per member; killed with a named member; reference control clean. Before P-40. Deferred (D-91); authored here. Resolve the dwell clause before P-40 (F-P29b-3): green_from C, but it asserts favorable_fire, delivered at E. | member 9 | hold |
| P-40 | C | rail complete (ages, absences, window, warm-up, worst-side, forced, dwelled); PlatformConfig position_rail_slippage_ticks and position_rail_dwell_ns (D-40). rail side usability per D-62: classify once in the orchestrator mark path, pass the result to store and rail; no second classify call site | + 4 (rail half), 9 | hold |
| P-49 | — | Member 10 authoring under the stage-A rule (D-189): spec closure; reference engine extended; at least one broken engine per member; killed with a named member; reference control clean. Before P-50. Deferred (D-91); authored here. | member 10 | hold |
| P-50 | D | position cell: birth from fill, entry rational, excursion, extremes, deadline, states, closing record | + 4 (birth), 10, 11 | hold |
| P-51 | D | entry admission refusals and no-scale-in for owned alphas | member 10 refusal cases | hold |
| P-52 | D | invalidation intake; kernel stops emitting its own exit for owned slices | member 10, 5 (invalidation cases) | hold |
| P-59 | — | Members 7 and 8 authoring under the stage-A rule (D-189): spec closure; reference engine extended; at least one broken engine per member; killed with a named member; reference control clean. Before P-60. Deferred (D-91); authored here. Member 8 adverse half greens at P-60; favorable half and member 7 green at P-61. | members 7, 8 | hold |
| P-60 | E | adverse gate (drawn level, blind limit, never-skips) | + 6, 8 (adverse half) | hold |
| P-61 | E | favorable gate (blocks, forms, arming) | + 6, 8 (favorable half), 7 | hold |
| P-62 | E | precedence and requirement path: `source_layer="POSITION"` accepted, MARKET, `ADVERSE_EXCURSION` in the stop-slippage set | all eleven green | hold |
| P-95 | close | attribution diff tool (evaluation.md §3), tested first on a constructed synthetic tape | classes exact on the constructed tape | hold |
| P-99 | close | CAMPAIGN CLOSE: battery green on the arbitrary config; position oracle pinned (APP 2026-03-26, bt_position_arbitrary_not_calibrated); P-95 report legacy vs engine-on, descriptive; exit mix reported (tripwire, not a dial); refusal and suppression counts reported | operator | hold |

Order inside a stage is fixed; stages do not overlap; no stage begins while an earlier
gate is red.

## Deferred from P-23

Not done (D-189). Re-open when research evidence shows actuation delay matters.

| Item | Record | Trigger |
|---|---|---|
| timer closure and immediate actuation | D-174 | re-open when research evidence shows actuation delay matters |
| global closure kept | D-173; horizon_scheduler.py:289 | re-open when research evidence shows actuation delay matters |
| session-close flush | F-P23g-2 | re-open when research evidence shows actuation delay matters |

## Off-ladder tracked items

Not a stage gate (D-189).

| Item | Finding | Trigger |
|---|---|---|
| portfolio-path census (both `_mint` ratchet rows) | F-P23c-l; sized_intent_legs._mint and sized_intent_orders._mint (LEDGER.md:33143) | before any PORTFOLIO alpha |
| sensor-registry clock | F-P23a2-15 | when the registry is touched |
| cancel inside the latency window | F-P23a2-17 | before any alpha that cancels within order latency |
| passive drain lookahead coverage | F-P23a2-19 | before P-40 |
| point-state deep copy cost | F-P23g2-12; aggregator.py:391 and aggregator.py:406 | if a check job exceeds 960 s (LEDGER.md:33309) |
| exposure-cap policy and in-flight exposure | F-P23b2-17 | operator decision |
| default fill-report latency | F-P23b2-18 | operator decision |
| maker adverse-selection charges | execution/cost_model.py:41 (`passive_adverse_selection_bps`) | paper campaign |
| live early release | F-P23b2-16 | paper campaign |
| live grid origin | F-P23f-2 | paper campaign |
| live calibration | F-P23e-7 | paper campaign |
| IB stamp row | D-144; LEDGER.md:33142 (`IB _fill_to_ack`) | paper campaign |
| seeding main | F-T2-7, F-T2-10 | paper campaign |
| content-keyed order ids | Q2 (ii) design: five rungs; the salt mover set is the expected movers; legacy-oracle exemption required (F-P24-11, F-P29b-9) | before P-60's band draw hashes cell_id; before any PORTFOLIO alpha; before a second hazard-enabled alpha on one symbol (F-P24-10) |
| baseline capture covers exempt locked literals | F-P23b-d, F-P24-6 | next tooling rung |

## Round trip (what comes back for review)

Test output verbatim, including which members are red and why. Decisions the spec did not
cover (logged in `decisions.md`, then fixed upstream in the spec). Places the implementer
believes the spec is wrong (run through the amendment rule). Not code for line review.
