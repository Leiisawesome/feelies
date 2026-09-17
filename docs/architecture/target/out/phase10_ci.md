# PHASE 10 — CI restoration

**Basis.** Reset invocation closed at R-07 on `arch/exec` (`c1c11288`).
G40 is CLOSED. Five import tiers KEPT. Twelve-engine independence is KEPT
at zero pairs. invoked == MUST_INVOKE, owed 0. Lint and Format have been
red or unevaluated on main since 18 August; this branch has had no CI run
since that date. Current-state claims carry their original label; new
material is `specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        CI restoration
BASE:            arch/exec c1c11288 (post-R-07 reference
                 baseline; Five import tiers KEPT; G40
                 CLOSED; invoked == MUST_INVOKE, owed 0)
CLOSES:          ruff check green and ruff format --check
                 green on src/ tests/ scripts/, with
                 FAIL_QUIET_KEEP re-keyed so no line
                 number survives in it. This restores two
                 blocking CI steps (Lint, Format) that
                 have been red or unevaluated on main
                 since 18 August (Format failed on the
                 S-03 merge, then skipped; Lint failed on
                 the G40 close and still is). This branch
                 has had no CI run since that date: push
                 is filtered to main, there is no open
                 PR, last arch/exec Format success was
                 PR #238 on 18 August (aa413d96), 695
                 commits ago.
FINDING:         A blocking step that goes red once stops
                 being a detector. Every later violation
                 lands behind it, indistinguishable from
                 the first. T-04b's "this step did not
                 make a clean file dirty" / "this step
                 did not make it worse" reasoning is only
                 valid while nobody intends to make the
                 step green. That is why this campaign
                 outranks the OWED list. Format has been
                 red on main for 30 days; Lint for 8;
                 neither has run on this branch in 30.
                 S-19a and T-04b squeezes, and every
                 later hunk in the 57, sat behind that
                 dead gate.
DOES NOT CLOSE:  G10, G28, G32, G36, G39, G41, G42, G44,
                 G45, G46; S-34f groups g–o (15 engine
                 bodies; Inv-8 is a different campaign);
                 perfmeasure.py DIRECT_PROBES; G6 empty
                 depends_on_sensors; S-04c;
                 serialization.py fail-open; verify_step
                 frozen bugs; 152 research cache days;
                 engine-to-kernel residual 9 pairs (the
                 pin is the detector, not a gap this
                 campaign owns). The four EXEMPTION tests
                 stay environmental. G36 stays OPEN: the
                 seventeen keepers remain keepers; only
                 the keying changes. Deliberately not
                 this campaign: the push-filter policy
                 question (opening a PR vs adding
                 arch/exec to on.push.branches is
                 workflow policy, not a lint/format
                 close); Inv-10 (already symbol-keyed
                 with multiplicity on
                 _process_tick_inner × 6; survives the
                 reformat of orchestrator.py; no rung
                 here); the six keep-row files not in
                 the 57 (ib/connection.py, cli/env.py,
                 cli/promote.py, factor_neutralizer.py,
                 massive_ingestor.py, massive_ws.py) —
                 0.3 does not format them; 0.1 re-keys
                 their rows in the test only; the S-19a
                 semicolons already on main
                 (orchestrator.py
                 _quote_tick_in_flight joins), which
                 format will split as ordinary hunks,
                 not as a squeeze-fix rung.
STANDING
INVARIANTS:      Oracle frozen at exec-tools-v1. Never run
                 scripts/rebaseline_parity_hashes.py.
                 Hold all 64 HASH/COUNT constants, the
                 fingerprint
                 (de5d64b019075de0ca271b53834f342623f2b1a39f23ff73910e45b0bc90beb6),
                 and _BASELINE_CONFIG_HASH unless a step
                 names a re-pin. Hold
                 _BASELINE_TRADE_PARITY_HASH,
                 _BASELINE_NET_PNL, _BASELINE_FILL_COUNT,
                 _BASELINE_DATA_VERSION.
                 Accepted baseline failures are only
                 test_after_hours_reject_surfaces_as_rejected,
                 test_g12_cost_exceeds_disclosure_alert,
                 test_multi_symbol_subscribe,
                 test_sustained_quotes_with_idle_ticks.
                 A failure outside that set is a STOP.
                 Both import pins hold: Five import
                 tiers is empty _TIER_RESIDUALS and
                 statuses KEPT; Twelve engine module
                 sets is KEPT at zero pairs;
                 engine-to-kernel equals the 9-pair
                 pin. Shrinking either import pin
                 happens in lockstep with the cut that
                 drops the pair, in the same commit.
                 Do not restore continue-on-error.
                 Do not invent suffixes for g–o.
                 Reset partition holds: _TAPES stays
                 the five ids; MUST_INVOKE stays 33;
                 DECLARED_UNINVOKED stays nine; invoked
                 == MUST_INVOKE. A name does not move
                 between those frozensets in this
                 campaign.
                 Specific to this campaign: the format
                 commit is mechanical and must move no
                 pin. FAIL_QUIET_KEEP must never regain
                 a line key after 0.1. ruff stays
                 0.15.12; a version bump would change
                 the diff and make the format commit
                 non-mechanical.
NON-CUTS:        A re-export without retarget is not a cut.
                 A TYPE_CHECKING-only move is not a cut.
                 A sys.modules lookup (or optional getattr
                 fallback) is not a cut.
                 Widening a type to object or Any is not a
                 cut.
                 A frozenset of (path, symbol, exc_type)
                 is not a re-key; it is a retirement of
                 multiplicity. The two Exception handlers
                 in _run_backtest_phases_2_7 collapse to
                 one allowed key and the test stays green
                 with a missing handler.
                 Splitting the format commit 53/4 is not
                 two rungs; it leaves the job red on the
                 four.
                 A noqa on a genuinely unused import is
                 not a lint fix. The two TYPE_CHECKING
                 names in bootstrap.py (IBGatewayConnection,
                 MassiveLiveFeed) have runtime imports at
                 2102–2103 and no annotation use; delete
                 them.
                 Formatting without the re-key and
                 retargeting three pins in the same
                 commit (layer_validator.py 1190→1191,
                 bootstrap.py 1607→1609 and 1825→1827)
                 is allowed but must be declared, not
                 discovered. The other 14 pins do not
                 move under today's --diff; that is not
                 a reason to keep line keys.
LADDER:          Shared-file steps are sequential, not
                 independently revertible. 0.3 depends
                 on 0.1 unless the three-pin retarget is
                 declared on 0.3. 0.2 and 0.3 are
                 already-red detectors (ruff check, ruff
                 format --check). 0.1 is a new matcher
                 on a currently green test and needs the
                 budget-1 fail-first.
                   0.1  re-key FAIL_QUIET_KEEP: Counter
                        (path, enclosing_symbol, exc_type);
                        "<module>" for the numpy
                        ImportError; budget 2 for
                        _run_backtest_phases_2_7 /
                        Exception. No line number
                        survives. Assert extra/missing
                        empty. Lint and format stay red.
                   0.2  lint: delete the two unused
                        TYPE_CHECKING imports in
                        bootstrap.py. Assert ruff check
                        src/ tests/ scripts/ green.
                        Already red.
                   0.3  format: one commit, all 57
                        files, ruff 0.15.12. Assert
                        ruff format --check src/ tests/
                        scripts/ green; no pin moved.
                        Already red. Do not split 53/4.
                 Close: both CI steps green locally;
                 FAIL_QUIET_KEEP has no line field.
                 Actions on this branch is the
                 push-filter decision, not a fourth
                 rung.
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template).

```
STEP:            0.1
CLOSES:          nothing toward ruff green. Lint stays
                 red (2 F401). Format stays red (57
                 files). FAIL_QUIET_KEEP loses every
                 line number. S6 still has seventeen
                 keepers. G36 stays OPEN. A matcher
                 landing with extra/missing empty is
                 the declared outcome, not a failed
                 rung.
PROBLEM:         FAIL_QUIET_KEEP is keyed
                 (path, line, exc_type). 0.3 will
                 reformat 57 files. Three of the
                 seventeen pins move under today's
                 --diff (layer_validator.py 1190→1191;
                 bootstrap.py 1607→1609, 1825→1827).
                 The other fourteen do not, because
                 six keep-row files are already
                 formatted and the backtest_runner.py
                 hunk sits below 588/794/831. Leaving
                 line keys makes 0.3 either fail S6 or
                 silently retarget three rows in the
                 format commit. That is T-04b's tax,
                 undeclared. Re-keying first is what
                 makes 0.3 mechanical.
WHY THIS OWNER:  Conformance owns the keep-row pin.
                 Production except bodies stay. Copying
                 S-19a's _enclosing_symbol and Counter
                 into this consumer is the same shape
                 as S-19a: a test change, then the
                 hold-the-line tricks become
                 unnecessary. gatescan.py still emits
                 line; the test maps line to symbol.
FILES:           tests/conformance/test_fail_quiet.py
                 Do not edit src/. Do not edit
                 tools/arch/gatescan.py,
                 tests/acceptance/test_no_walltime_outside_clock.py,
                 tests/conformance/test_import_contracts.py,
                 tests/acceptance/test_backtest_app_baseline.py,
                 .github/workflows/ci.yml, uv.lock.
                 Do not format any file. Do not touch
                 the nine keep-row production files
                 (layer_validator.py, bootstrap.py,
                 ib/connection.py, cli/env.py,
                 cli/promote.py, factor_neutralizer.py,
                 backtest_runner.py, massive_ingestor.py,
                 massive_ws.py). The probe edits only
                 the new matcher inside
                 test_fail_quiet.py (budget 1, then 2);
                 it does not mutate production except
                 bodies.
REFACTOR PATH:   one commit. Mechanism: FailQuietKeep
                 drops `line`. Key is (path,
                 enclosing_symbol, exc_type). Matcher
                 is collections.Counter exactly-N, not
                 a frozenset. enclosing_symbol is the
                 smallest covering def/async def name
                 from a copy of S-19a's
                 _function_spans / _enclosing_symbol
                 (duplicate the helpers in this file;
                 do not import them from
                 test_no_walltime_outside_clock.py).
                 When that returns None, the symbol is
                 the sentinel "<module>".
                 Seventeen rows, measured:
                   layer_validator.py
                     _check_g17_safety_exit_policy
                     (TypeError, ValueError)
                   bootstrap.py
                     _create_composition_layer KeyError
                   bootstrap.py
                     _create_hazard_exit_controller
                     (TypeError, ValueError)
                   ib/connection.py
                     _drain_writer_queues queue.Empty
                   ib/connection.py
                     orderStatus (TypeError, ValueError)
                   cli/env.py
                     load_dotenv_optional ImportError
                   cli/promote.py
                     _read_entries_safely StopIteration
                   cli/promote.py
                     _read_entries_safely ValueError
                   factor_neutralizer.py
                     <module> ImportError
                   factor_neutralizer.py
                     neutralize np.linalg.LinAlgError
                   backtest_runner.py
                     _force_utf8_console Exception
                   backtest_runner.py
                     _run_backtest_phases_2_7 Exception
                     (psutil HIGH_PRIORITY_CLASS)
                   backtest_runner.py
                     _run_backtest_phases_2_7 Exception
                     (nice() restore in finally)
                   massive_ingestor.py
                     _clone_parallel_clients TypeError
                   massive_ws.py
                     _drain_stale_sentinels queue.Empty
                   massive_ws.py
                     _run_loop asyncio.CancelledError
                   massive_ws.py
                     _subscribe asyncio.TimeoutError
                 Special handling, closed set:
                 (1) Collision. The two Exception
                 handlers in _run_backtest_phases_2_7
                 share a Counter key. Two keep rows,
                 different reasons, budget 2. A
                 frozenset of (path, symbol, exc_type)
                 collapses them and the test stays
                 green with a missing handler. That
                 spelling is forbidden.
                 (2) Module-level. factor_neutralizer.py
                 ImportError has no enclosing def.
                 Without "<module>" it is an extra.
                 cli/env.py is not this shape
                 (load_dotenv_optional).
                 (3) Adjacent non-quiet.
                 _check_g17_safety_exit_policy has a
                 second except (TypeError, ValueError)
                 at 1204 that returns, so
                 fail_quiet_handlers() omits it. Do not
                 add it. The quiet filter is what keeps
                 1190 unique. If 1204 becomes pass, that
                 is a new collision and a later rung.
                 Class qualification is not required:
                 bare names are unique except (1).
                 reason stays on the row; the matcher
                 does not use it except the existing
                 non-empty check.
                 Order: (1) write the Counter matcher
                 and convert all seventeen rows to
                 symbol keys, with budget 1 for
                 (_run_backtest_phases_2_7, Exception)
                 — one keep row for that pair, not two.
                 Run only
                 test_no_unallowlisted_fail_quiet_exception_handler.
                 It MUST fail (extra handler or unused
                 budget). That is the fail-first. This
                 is a new matcher on a currently green
                 test; without budget-1 it lands green
                 by construction and protects nothing.
                 (2) set budget 2 (second keep row for
                 that pair). Re-run. Green.
                 (3) commit the test only. No production
                 except body is written or edited. No
                 file is formatted.
BLAST RADIUS:    local — tests/ only
VALIDATED BY:    test_no_unallowlisted_fail_quiet_exception_handler
                 extra/missing empty under Counter;
                 budget-1 failed-before then budget-2
                 passed-after; a frozenset matcher must
                 not be what is committed;
                 test_five_import_tiers empty
                 _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2);
                 test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 test_no_raw_wall_clock_outside_allowlist
                 and
                 test_wall_clock_allowlist_has_no_stale_entries
                 unmoved (Inv-10 not this rung);
                 tests/acceptance/test_backtest_app_baseline.py
                 hashes unmoved. No XPASS. ruff check
                 still 2 F401. ruff format --check still
                 57 files. Those reds are 0.2 and 0.3,
                 not this rung failing.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin. A test-only change that moves
                 a hash means the file was not
                 test-only.
DELETES:         FailQuietKeep.line; the
                 (path, line, exc_type) frozenset
                 matcher. Seventeen keepers remain.
                 No production handler is converted.
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible until 0.3 lands. Once 0.3
                 formats bootstrap.py and
                 layer_validator.py, reverting 0.1
                 without reverting 0.3 restores line
                 keys that no longer match. 0.2 does
                 not depend on this rung.
```
