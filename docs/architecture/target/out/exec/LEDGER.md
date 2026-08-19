# Execution ledger

Plan: docs/architecture/target/out/phase7_migration.md (35 steps, locked)
Baseline: see docs/architecture/target/out/exec/baseline_pre.json
Blast radius: local 4, boundary 20, platform-wide 11
Parity-breaking: S-16, S-17, S-23, S-31

---

## S-01  conformance instrumentation (registry, FIX-1, HARN-1, HARN-2, S1, C1)
DATE:            2026-08-18T00:45:58+00:00
BASE SHA:        1b35258ba205eefd031a09fb97ab942d088422d9
RESULT SHA:      not started — blocked at pre-flight, no branch cut, no edit made
VERDICT:         blocked
CONFORMANCE:     S1, C1 | failed-before: not run | passes-after: not run
TESTS:           not run -> not run (baseline_pre.json records 4758 passed,
                 0 failed, 28 skipped; determinism 145 passed)
PARITY:          declared hold (all 26 baselines + trade parity hash) | actual
                 unmoved — 62 constants at HEAD, key-for-key and value-for-value
                 identical to baseline_pre.json | MATCH (no step edit made)
FILES DECLARED:  tests/conformance/registry.py
                 tests/conformance/test_registry_closure.py
                 tests/conformance/fixtures/null_alpha/
                 tests/conformance/harness/engine_probe.py
                 tests/conformance/harness/fault_injector.py
                 tests/conformance/test_null_alpha_conservation.py
FILES TOUCHED:   none under FILES. This ledger entry only.
NET DELTA:       declared src modules 0, public symbols 0, branch points 0,
                 test files +6 | actual 0 / 0 / 0 / 0
FINDINGS:        1. BLOCKER — the freeze tag `exec-tools-v1` does not point at the
                    frozen oracle. It resolves to 22596d2, whose `tools/exec` tree
                    is byte-identical to 7e6689b, the commit that reverted the
                    oracle fixes (`git diff --stat 7e6689b..22596d2 -- tools/exec`
                    is empty despite that commit's message reading "restore parity
                    oracle coverage (43 -> 62)"). 22596d2 is not an ancestor of
                    HEAD. HEAD carries the repaired oracle, restored by 87b70c3 and
                    frozen by 1b35258 ("freeze oracle at 62 constants"). The
                    prescribed pre-flight check `git diff --stat exec-tools-v1..HEAD
                    -- tools/exec` therefore reports 1 file, +24/-8, and can only be
                    made empty by reverting the oracle to its blind 43-constant
                    state. Resolution is a human action — move the tag to 1b35258,
                    or state that the blind oracle is the intended freeze point.
                 2. `baseline_pre.json` records sha 8e42a3d, which is also not an
                    ancestor of HEAD; it is a twin of 311a245 carrying the same
                    subject line on the abandoned branch. Its recorded parity map
                    nonetheless matches HEAD exactly (62/62, no value drift), so the
                    pre-baseline is still usable as the S-01 reference.
NOTES:           Working tree was clean and HEAD was on arch/exec. Pre-flight halted
                 at the third command; `baseline.py capture --label pre-S-01` was
                 deliberately not run, so that the tree is handed back pristine for
                 the retry — the capture writes an artifact and would leave the next
                 pre-flight cleanliness check dirty for a step that never ran. The
                 62-constant precondition was instead verified read-only by importing
                 `tools/exec/baseline.py` and calling `parity_constants()`; nothing
                 under `tools/exec/` was modified. Full-suite green at HEAD is
                 therefore unverified for this attempt.

---

## S-01  conformance instrumentation (registry, FIX-1, HARN-1, HARN-2, S1, C1)
DATE:            2026-08-18T09:05:00+08:00
BASE SHA:        bb46c79f6ffa131a4c6cadb2bea8ed01e01077a2
RESULT SHA:      a3e17e43c1f9aa9e1657316496088b1e28ba3961
VERDICT:         passed
CONFORMANCE:     S1 (tests/conformance/test_registry_closure.py) | failed-before: yes
                 | passes-after: yes (xfailed, strict)
                 C1 (tests/conformance/test_null_alpha_conservation.py) |
                 failed-before: yes | passes-after: yes
                 Step-2 failure output, both captured before any implementation:
                   ERROR collecting tests/conformance/test_registry_closure.py
                   tests\conformance\test_registry_closure.py:19: in <module>
                       from tests.conformance.registry import GAP_REGISTRY
                   E   ModuleNotFoundError: No module named 'tests.conformance.registry'
                   ERROR collecting tests/conformance/test_null_alpha_conservation.py
                   tests\conformance\test_null_alpha_conservation.py:28: in <module>
                       from tests.conformance.harness.engine_probe import EngineProbe
                   E   ModuleNotFoundError: No module named 'tests.conformance.harness'
                   !!! Interrupted: 2 errors during collection !!!
                   1 warning, 2 errors in 0.48s
TESTS:           4757 passed / 0 failed / 29 skipped / 0 xfailed
                 -> 4759 passed / 0 failed / 29 skipped / 1 xfailed
                 determinism 145 -> 145. The +2/+1 are exactly this step's three
                 new test functions; nothing previously passing moved.
PARITY:          declared hold (all 26 baselines + trade parity hash) | actual
                 62 constants unmoved, 0 changed, key-for-key and value-for-value
                 | MATCH. verify_step S-01: FILES clean, PARITY holds, CLEAN.
FILES DECLARED:  tests/conformance/registry.py
                 tests/conformance/test_registry_closure.py
                 tests/conformance/fixtures/null_alpha/
                 tests/conformance/harness/engine_probe.py
                 tests/conformance/harness/fault_injector.py
                 tests/conformance/test_null_alpha_conservation.py
FILES TOUCHED:   tests/conformance/registry.py
                 tests/conformance/test_registry_closure.py
                 tests/conformance/fixtures/null_alpha/null_alpha.alpha.yaml
                 tests/conformance/harness/engine_probe.py
                 tests/conformance/harness/fault_injector.py
                 tests/conformance/test_null_alpha_conservation.py
                 6 touched against 5 named files + 1 directory scope; nothing
                 outside FILES. No `__init__.py` was added: `tests` is a regular
                 package and `tests/conformance` resolves as a namespace
                 subpackage, so `tests.conformance.registry` imports without one
                 (`tests/harness/` is the existing precedent). Adding them would
                 have been two undeclared files.
NET DELTA:       declared src modules 0, public symbols 0, branch points 0,
                 test files +6 | actual src modules 196 -> 196 (+0), public
                 symbols 551 -> 551 (+0), sloc 43197 -> 43197 (+0), import
                 cycles 2 -> 2 (+0), test files +6. MATCH.
FINDINGS:        1. The prompt's stated baseline reference (4758 passed, 28
                    skipped) does not match `baseline_pre.json`, which records
                    4757 passed / 29 skipped. The pre-S-01 capture agrees with
                    the artifact key-for-key, so the artifact was treated as
                    authoritative per section 1 ("must match baseline_pre.json").
                    The prompt figure appears to be off by one; worth correcting
                    before S-02 quotes it again.
                 2. The plan's G.8 table carries 46 rows (G01-G46) under a
                    heading reading "all 45, plus the two proposed", while S-01's
                    REFACTOR PATH says "all 45 gap IDs". Only G46 is marked
                    proposed, so "the two" has no referent. Registered G01-G45
                    (45 entries) per the explicit count; G46 (P1 proposed, step
                    S-10, test S9) is deliberately absent and S-10 must add it.
                    This does not affect S1's result either way -- G46 names a
                    test, so it would be covered.
                 3. REFACTOR PATH (1) says the registry lands with "empty test
                    lists", which contradicts (2) in the same sentence: with all
                    lists empty S1 fails on ~38 P0/P1 gaps, not on G31 and G32.
                    The plan states three times that it fails on exactly those
                    two, so the registry was populated from the G.8 table and
                    only G31/G32 are empty. Verified: uncovered P0/P1 == exactly
                    {G31, G32}.
                 4. HARN-2 ships with no in-tree consumer. Its only specified
                    use is S-07's slow-engine injection, so its API is an
                    implementer's choice that S-07 may have to reshape. Not
                    fixed, not expanded speculatively -- kept to the one named
                    capability and flagged in its own docstring.
                 5. Not fixed, outside the step: a SIGNAL alpha cannot declare
                    `depends_on_sensors: []` (G6 rejects it), so a control alpha
                    that reads nothing must still name a sensor and then trips
                    the `sensor_audit_2026-07-02` P1 unused-dependency warning on
                    every load. The two rules cannot both be satisfied. FIX-1
                    declares `ofi_ewma` and documents the warning as expected.
NOTES:           C1 was vacuous twice before it was load-bearing, and both traps
                 are worth knowing because any later replay-based conformance
                 test can fall into them.
                 (a) First draft used `horizon_seconds: 120` against a 20-second
                 tape, so no horizon boundary was ever crossed. (b) Second used a
                 `P(normal)`-referencing regime gate; with
                 `regime_calibration_max_quotes` unset the regime engine is
                 uncalibrated and every P(state) gate fails safe OFF (Inv-11), so
                 `evaluate` was never called. In both cases the conservation
                 assertions passed while testing nothing. Fixed by moving FIX-1
                 to `horizon_seconds: 30` with a 400s tape and the
                 regime-independent `on_condition: "True"` gate (the
                 paper_smoke_v1 pattern), then instrumenting: the alpha's
                 evaluate is called 28 times (14 boundaries x 2 symbols) and
                 emits 0 Signals. C1 now asserts both preconditions -- the probe
                 saw at least as many events as were fed in, and the gate latched
                 ON for every symbol -- so a regression to either trap fails
                 rather than passes.
                 Mutation-proved per AGENTS.md: FIX-1's evaluate replaced with an
                 unconditional LONG emission makes C1 fail with a real position
                 (quantity 1, unrealized -0.01) at 9820 of 19752 observations;
                 restored and proved byte-identical to the pre-mutation backup
                 with the suite green again. An earlier mutation attempt was
                 discarded because PowerShell `Set-Content` rewrote the file in a
                 non-UTF-8 encoding and the resulting failure was an encoding
                 error, not the mutation.
                 S1 lands `xfail(strict=True)`, so it also fails if G31/G32 are
                 ever covered without the marker being dropped -- the marker
                 cannot outlive the hole.
                 Left uncommitted for the operator: `baseline_pre-S-01.json`,
                 `baseline_post-S-01.json`, and this ledger entry. The step
                 commit contains the six declared files only, per section 7.

## S-02  Guard whole-run parity, reduction, fill timing, alpha purity
DATE:            2026-08-18
BASE SHA:        dc3fec5f1499ecd4cdf216dfa368eb2b129df866
RESULT SHA:      73def0347a40d84ec13476db56628f9fa5b7245d
VERDICT:         passed
CONFORMANCE:     R1, X3, H1, A1 | failed-before: no, by design | passes-after:
                 yes (25 passed in the step's three files).
                 The plan states outright that all four behaviours are correct
                 today ("since all four pass today") and NET DELTA declares 0 src
                 modules, so there is nothing to implement and section 2's
                 fail-first gate cannot apply as written. VALIDATED BY names the
                 substitute proof itself: the AGENTS.md mutation procedure. That
                 was run for all four; the mutated-run output is below, and each
                 mutation was reverted with `git diff -- src/` empty afterwards.
                 H1 (the mutation the plan specifies -- `passive_limit_router.py`
                 :527 exchange-time comparison replaced by a wall-clock read):
                   FAILED tests/execution/test_router_fill_timing_parity.py::
                   TestPassiveAggressiveEligibilityParity::
                   test_a_wall_clock_past_the_deadline_makes_neither_path_eligible
                   assert [OrderAck(... order_id='passive', timestamp_ns=9000000,
                   fill_price=Decimal('99.90'), reason='FILLED_BY_THROUGH' ...)]
                   == []
                   1 failed, 15 passed
                 The 15 that passed are the point: all 14 pre-existing tests in
                 that file survive this mutation. Every one of them advances the
                 clock in lockstep with the tape, so a wall-clock read satisfies
                 them. That is precisely the hole H1's extension closes, and it
                 is why the extension separates the two clocks.
                 X3, three mutations of `risk/basic_risk.py`:
                   (a) post-fill quantity computed as an increase
                       (`post_signed = signed_qty + delta`) -- 4 failed:
                       PDT/RTH/holiday/position-limit flattens all REJECT.
                       e.g. AssertionError: a flattening order was refused in a
                       degraded state: REJECT ('post-fill position 200 exceeds
                       limit 100')
                   (b) `_check_buying_power` early return for exits removed --
                       0 failed. The case survives, because the prospective-gross
                       arithmetic independently subtracts the closed position.
                       Removing BOTH guards fails it:
                       AssertionError: ... REJECT ('insufficient buying power:
                       need 10000.00, have 4000.00'). Recorded in the class
                       docstring per AGENTS.md.
                   (c) both `FORCE_FLATTEN` assignments -> `REJECT` -- 2 failed:
                       AssertionError: drawdown breach answered a flattening
                       order with REJECT ('drawdown 5.00% exceeds max 1.0%')
                 A1, two mutations:
                   (a) `PositionUpdate` subscription added to
                       `HorizonSignalEngine.attach` -- 1 failed: the signal engine
                       subscribes to ['HorizonFeatureSnapshot', 'PositionUpdate',
                       'RegimeState', 'SensorReading'], expected exactly [...]
                   (b) `position_quantity: int = 0` field added to
                       `HorizonFeatureSnapshot` -- 1 failed: an input handed to
                       the alpha carries book state in ['position_quantity'] --
                       the type is pure but the payload is not
                 Vacuity, per section 2 -- how each guard is known to have run:
                 X3's seven cases each assert a *control entry* is refused with
                 that state's own reason before asserting the exit is permitted,
                 so a gate that stopped firing fails the case rather than passing
                 it. A1 asserts `recorder.calls` is non-empty before scanning
                 arguments (the C1 trap from S-01), and its subscription check is
                 an equality, so an empty set fails. H1 asserts both orders
                 acknowledge at the shared deadline and that the same tape does
                 fill both once eligible, so the negative assertions cannot pass
                 by nothing happening.
TESTS:           4759 passed / 0 failed / 29 skipped / 1 xfailed
                 -> 4770 passed / 0 failed / 29 skipped / 1 xfailed
                 determinism 145 -> 145. The +11 are exactly this step's eleven
                 new test functions (X3 7, H1 2, A1 2); nothing previously
                 passing moved. Baseline figures read from
                 `baseline_post-S-01.json`, which pre-S-02 matched key-for-key.
PARITY:          declared hold ("All 26 hold") | actual 62 constants unmoved,
                 0 changed, key-for-key and value-for-value | MATCH.
                 verify_step S-02: FILES clean, PARITY holds, CLEAN.
                 R1 exercised locally before landing: the oracle replays green
                 under `PYTHONHASHSEED=random` (2 passed in 17.8s, cache-backed,
                 `FEELIES_REQUIRE_BASELINE_CACHE=1` -- it replayed, it did not
                 skip). G08's residual is therefore closed rather than merely
                 armed; had a hash moved under a random seed that would have been
                 a live defect found, not one introduced.
FILES DECLARED:  .github/workflows/ci.yml
                 tests/conformance/test_reduction_permitted.py
                 tests/execution/test_router_fill_timing_parity.py
                 tests/conformance/test_alpha_purity.py
FILES TOUCHED:   .github/workflows/ci.yml
                 tests/conformance/test_reduction_permitted.py
                 tests/execution/test_router_fill_timing_parity.py
                 tests/conformance/test_alpha_purity.py
                 4 declared, 4 touched, nothing outside FILES. `src/` untouched.
NET DELTA:       declared src modules 0, public symbols 0, branch points 0, test
                 files +3, CI job steps +1 | actual src modules 196 -> 196 (+0),
                 public symbols 551 -> 551 (+0), sloc 43197 -> 43197 (+0), import
                 cycles 2 -> 2 (+0), alphaleak 2 -> 2 (+0), test files +2 new and
                 +1 extended (= the 3 the FILES field lists, one annotated
                 "extend"), CI job steps +1. MATCH.
                 DELETES is satisfied semantically, not textually: the pinned
                 `PYTHONHASHSEED: "0"` step remains, as DELETES itself requires
                 ("The pinned job stays"); what is deleted is its status as the
                 only seed the oracle runs under. No line was removed, so the
                 diff is +21/-0 on ci.yml.
FINDINGS:        1. Not fixed, outside the step, and the reason X3 stops at seven
                    states: the gross-exposure cap is the one gate in
                    `BasicRiskEngine` with no reduction exemption. It is measured
                    on prospective total exposure across the whole book, so when
                    the book is over the cap a flatten of symbol A is REJECTed
                    because symbol B still breaches it -- the reduction is refused
                    exactly when reducing matters. Verified read-only: a $15,000
                    book against a $10,000 cap, flattening the $5,000 leg ->
                    REJECT ('gross exposure limit: 10000 >= 10000.0'). Every other
                    entry gate (PDT, buying power, RTH, holiday, per-symbol cap)
                    exempts reductions explicitly. This looks like an Inv-11
                    violation on the fail-safe path and wants its own step; X3
                    covers the states the engine declares an exemption for, and
                    would have to encode the current refusal as correct to include
                    this one.
                 2. Plan defect, worked around with operator approval: REFACTOR
                    PATH tells R1 to "add the parity oracle to the existing
                    random-seed job", but that job is `check`, which has no
                    event-cache restore step and runs on fork PRs without secrets.
                    Under `FEELIES_REQUIRE_BASELINE_CACHE=1` the oracle would fail
                    there on every run; without it, it would skip and report
                    green, which is the exact failure mode AGENTS.md documents.
                    Landed instead as one step on the existing `parity-oracle`
                    job under `PYTHONHASHSEED: random`, where the cache restore,
                    the refetch fallback and the fork-PR skip already exist. Same
                    end state, and it matches DELETES and "CI job steps +1"
                    literally.
                 3. Process, not a code defect: pre-flight expects HEAD on
                    `arch/exec`, but `arch/exec` is at bb46c79 and does not
                    contain S-01. S-01's commit (a3e17e4) and the operator's
                    capture/ledger commit (dc3fec5) live only on `exec/S-01`.
                    S-02's ROLLBACK says "A1 consumes FIX-1", so branching from
                    `arch/exec` would have deleted A1's input. Cut `exec/S-02`
                    from dc3fec5 with operator confirmation. Either `arch/exec`
                    needs to advance as steps land, or the pre-flight expectation
                    needs restating; S-03 will hit this again.
                 4. S-01's two live findings were checked for collision and
                    neither touches S-02: the G01-G45 registration gap is S-10's,
                    and G6's rejection of `depends_on_sensors: []` is a property
                    of FIX-1 which A1 consumes unchanged (it declares `ofi_ewma`
                    and the P1 unused-dependency warning is expected on load).
                 5. Not fixed, pre-existing, but it reads as an instruction to
                    undo this step: `conftest.py:31-43` issues a
                    `PytestConfigWarning` on any seed other than "0", whose text
                    is "run `PYTHONHASHSEED=0 uv run pytest ...`". R1's new job
                    step therefore prints, on every CI run, advice to re-pin the
                    seed it exists to unpin. It is warn-only -- no behaviour
                    change, and the step exits 0 with it (verified: 2 passed,
                    1 warning, 17.04s, same invocation as the CI step) -- and it
                    already fires in the pre-existing `check` job, so S-02 did
                    not introduce it. Worth narrowing to exempt the deliberate
                    random-seed jobs, which is a conftest change and so outside
                    this step's FILES. The ci.yml comment already tells a reader
                    not to answer a failure by re-pinning; the warning is the
                    louder voice and says the opposite.
NOTES:           Blast radius escalated from the plan's stated `local` to
                 platform-wide under section 0's escalation clause: H1 pins the
                 fill-eligibility rule that governs order submission, and R1
                 changes how the parity surface is exercised in CI. Full diff,
                 verification output and rollback were presented and explicit
                 go was given before commit. Both the escalation and the R1
                 placement in finding 2 were approved by the operator.
                 X3's seven states are enumerated from the engine rather than the
                 plan: PDT minimum equity, Reg-T buying power, outside RTH,
                 market holiday, per-symbol cap, drawdown breach, non-positive
                 equity. The last two answer a flatten with `FORCE_FLATTEN`
                 rather than `ALLOW`; that is not a refusal (the orchestrator
                 flattens the book), so the helper accepts either, and those two
                 cases additionally assert the reason so a bare `FORCE_FLATTEN`
                 from a third state cannot satisfy them.
                 A1 reuses FIX-1 and C1's tape rather than restating either, per
                 S-01's "one control alpha, one fixture". It reaches into
                 `engine._signals` and `bus._handlers` -- private attributes, but
                 the alternative is asserting on public output, which is what
                 makes a purity test vacuous: a pure alpha and a fourth
                 subscription produce identical public output.
                 The mutation cycle followed AGENTS.md exactly, including the two
                 `__pycache__` purges per round. Every restore was verified with
                 `git diff -- src/` before the pristine re-run, and every pristine
                 re-run was green.
                 Left uncommitted for the operator: `baseline_pre-S-02.json`,
                 `baseline_post-S-02.json`, and this ledger entry. The step
                 commit contains the four declared files only, per section 7.

## S-03  arm Phase-6 scan detectors as conformance tests
DATE:            2026-08-18T04:08:20+00:00
BASE SHA:        d2b934c9880eec54049277b99eba3ace16d69acd
RESULT SHA:      57beddff0a7dc20e1dcae4eb87617ce397854191
VERDICT:         passed
CONFORMANCE:     S3, S4, S5, S6, S7, S10, S11, S16, S17, R2, R7, R8, C2, C3 |
                 failed-before: yes for the ten gap detectors; no (by design)
                 for R7, R8, C2, C3 and the I-01 uuid/RNG clause |
                 passes-after: yes (7 passed, 9 xfailed strict)
                 Step-2 failure output, captured before xfail/allowlist:
                   FAILED test_no_raw_wall_clock_outside_allowlist
                   AssertionError: ... kernel/orchestrator.py:1524,1633,1771,
                   3940,1635,1675,1773,2104,1677,3950  time.perf_counter_ns()
                   FAILED test_no_alpha_shape_literal_outside_alphas_and_config
                   AssertionError: 2 alpha-id literal(s) ... platform_config.py:108
                   FAILED test_hot_path_allow_list
                   AssertionError: proven per-event: dict_construction 3,
                   dynamic_dispatch 2, string_formatting 3, set_construction 2,
                   wall_clock_read 3 (orchestrator.py:1524,2104,3940)
                   FAILED test_no_fail_quiet_exception_handler
                   AssertionError: 20 fail-quiet except handler(s). First:
                   layer_validator.py:1189 except (TypeError, ValueError)
                   FAILED test_mode_branches_only_at_composition_root
                   AssertionError: 3 OperatingMode branch(es) outside the
                   composition root and mode seam. First:
                   platform_config.py:447 self.mode != OperatingMode.BACKTEST
                   FAILED test_frozen_events_carry_no_mutable_container
                   AssertionError: frozen events with mutable container fields
                   (G12): Alert, CrossSectionalContext, HorizonFeatureSnapshot,
                   MetricEvent, RiskVerdict, Signal, SizedPositionIntent,
                   StateTransition
                   FAILED test_every_published_type_has_a_subscriber
                   AssertionError: KillSwitchActivation, OrderAck,
                   PositionUpdate, RiskVerdict, StateTransition, SymbolHalted
                   FAILED test_reset_path_totality
                   AssertionError: 32 stateful class(es) ... First: Orchestrator
                   FAILED test_no_post_construction_mutation_or_private_reach
                   AssertionError: 40 external attribute assignment(s) outside
                   the composition root. First: broker/ib/contracts.py:28 c.symbol
                   FAILED test_market_data_canonical_parity_baseline
                   AssertionError: engine 1 canonical stream has no baseline
                   (G05); S-17 supplies it
                   10 failed, 6 passed
                 S4's implementation is the ten call-granular allowlist
                 entries, after which that test passes. The other nine land
                 xfail(strict=True, reason="GAP Gnn").
                 Vacuity: S4 named the ten orchestrator lines; S3 named both
                 leak sites; S5 named proven sites; S6 named a handler; S7
                 named a branch; S10 listed eight event classes (frozen=True
                 asserted first and held); S11 listed six types; S16 named
                 Orchestrator; S17 named a site; R2 hashed a non-empty stream
                 (len==64) before the missing-baseline assert.
                 R7/R8/C2/C3 mutation-proved per AGENTS.md (pycache purged
                 each round; restore via git checkout; git diff -- src empty):
                 R7 duration compare `event.timestamp_ns` -> `0` — FAILED
                 "throttle comparison is not in event time: 0 - last_ns <
                 binding.throttle_ns"; restored, 1 passed.
                 R8 all_positions `dict(self._positions)` -> set comprehension
                 — FAILED iteration ['AAA','MNO','ZZZ'] != insertion
                 ['ZZZ','AAA','MNO']; restored, 1 passed.
                 C2 probe unrealized_pnl forced to Decimal('1') — FAILED
                 "flat book carried unrealized PnL at 19636 of 19636
                 observations"; restored, 1 passed.
                 C3 probe dropped NBBOQuote/Trade samples — FAILED
                 "probe saw no NBBOQuote/Trade — ingress never ran";
                 restored, 1 passed.
TESTS:           4771 passed / 0 failed / 29 skipped / 0 xfailed
                 -> 4776 passed / 0 failed / 29 skipped / 9 xfailed
                 determinism 145 -> 145. The +5 passed are uuid/RNG, R7, R8,
                 C2, C3; the +9 xfailed are the nine gap detectors. S4 was
                 already in the suite (2 tests, still 2, both pass). Nothing
                 previously passing moved. Live pre-S-03 capture is 4771, not
                 the post-S-02 artifact's 4770 — see finding 2.
PARITY:          declared hold (All 26 hold. No src edit.) | actual 62
                 constants unmoved, 0 changed, key-for-key and value-for-value
                 | MATCH. verify_step S-03: FILES clean, PARITY holds, CLEAN.
FILES DECLARED:  tests/conformance/ (S3, S5, S6, S7, S10, S11, S16, S17,
                 R2, R7, R8, C2, C3)
                 tests/acceptance/test_no_walltime_outside_clock.py (extend, S4)
                 promoting tools/arch/{measure,clockscan,hotpath,gatescan,
                 gapscan,contracts,substrate,coupling}.py (imported, not edited)
FILES TOUCHED:   tests/acceptance/test_no_walltime_outside_clock.py
                 tests/conformance/test_alpha_agnosticism.py
                 tests/conformance/test_hot_path_allow_list.py
                 tests/conformance/test_exception_containment.py
                 tests/conformance/test_mode_seam.py
                 tests/conformance/test_event_immutability.py
                 tests/conformance/test_emission_registry.py
                 tests/conformance/test_reset_paths.py
                 tests/conformance/test_construction_integrity.py
                 tests/conformance/test_market_data_canonical.py
                 tests/conformance/test_sensor_throttle_event_time.py
                 tests/conformance/test_store_ordering_seed_independence.py
                 tests/conformance/test_accounting_identities.py
                 tests/conformance/test_ingress_conservation.py
                 14 touched (1 extend + 13 new) against directory scope
                 tests/conformance/ + the named acceptance file. tools/arch/
                 not edited (PATHY does not extract the brace list; editing
                 them would have been UNDECLARED). src/ untouched.
NET DELTA:       declared src modules 0, public symbols 0, branch points 0,
                 test files +13, allowlist entries -1 file +12 call sites |
                 actual src modules 196 -> 196 (+0), public symbols 551 -> 551
                 (+0), sloc 43197 -> 43197 (+0), import cycles 2 -> 2 (+0),
                 alphaleak 2 -> 2 (+0), test files +13. MATCH on modules.
                 Allowlist: deleted the orchestrator whole-file entry, added
                 10 call-granular sites (clockscan reports 10 kernel reads,
                 not 12). See finding 3.
FINDINGS:        1. Process: HEAD was `main` (d2b934c, S-01 and S-02 merged),
                    not `arch/exec`. tools/exec differs from exec-tools-v1
                    (bb46c79) by c6af7d7 and aa413d9 (+96/-12). Branching
                    from arch/exec would have dropped S-01/S-02. Cut
                    exec/S-03 from main. tools/exec was not modified.
                 2. pre-S-03 capture is 4771 passed / 0 xfailed; post-S-02
                    artifact is 4770 / 1 xfailed. Parity 62/62 identical.
                    The extra pass is bbfadcc converting S1 from xfail to
                    equality. Artifact wins as the S-02 reference; S-03
                    before/after uses the live capture.
                 3. NET DELTA said +12 call sites; orchestrator has 10
                    time.perf_counter_ns reads. All ten are allowlisted.
                    The three proven per-event reads (1524, 2104, 3940) stay
                    on the call list as G01 residual for S-32.
                 4. S7 using coupling.mode_branches found 3 OperatingMode
                    AST hits outside bootstrap+execution+broker, not
                    gapscan's 7 line-regex sites. FILES names coupling.py.
                 5. R2, R7, R8 landed in tests/conformance/ per S-03 FILES.
                    p7_index and S-17 name tests/determinism/ paths. S-03
                    FILES is the contract for this step.
                 6. Carried findings checked, no collision: G46 stays S-10;
                    G6 empty-sensors is FIX-1 (C2/C3 reuse it, warning
                    expected); gross-exposure cap untouched — src/feelies/risk/
                    not edited.
                 7. S5's dead_compute clause does not run while proven
                    per-event sites fail first. When the xfail drops, both
                    halves must pass. Recorded, not split.
NOTES:           Blast radius stayed local — tests/ only, no src, no order
                 path, no ExecutionBackend. S4 promotes clockscan.CLOCK_LEAVES
                 and replaces the 5,480-line orchestrator exemption with ten
                 call-granular entries. Scanners are imported, not copied;
                 substrate.main() is pointed at a tmp evidence dir because
                 rel(out) against ROOT raises when EVIDENCE is outside the
                 repo (caught after the JSON is written).
                 Left uncommitted for the operator: `baseline_pre-S-03.json`,
                 `baseline_post-S-03.json`, and this ledger entry. The step
                 commit contains the 14 declared files only, per section 7.

## S-04  import-linter contracts; move inv12_stress out of core
DATE:            2026-08-18T05:32:47+00:00
BASE SHA:        f7f5f915be41ca97faf44acba38d257a3600268a
RESULT SHA:      not committed — blocked at the boundary gate, S-04b split taken
VERDICT:         blocked
CONFORMANCE:     S2 | failed-before: yes | passes-after: no (xfail landed; move not taken)
                 Step-2 failure output, captured before xfail, contracts expressed:
                   Five import tiers BROKEN
                   Twelve engine module sets BROKEN
                   Contracts: 0 kept, 2 broken.
                   feelies.core is not allowed to import feelies.promotion:
                   - feelies.core.platform_config -> feelies.promotion.evidence (l.1199)
                   (plus kernel -> engines, harness -> cli/bootstrap, core -> sensors.spec)
                 S2 without xfail: 2 failed in 0.90s
                   assert 'BROKEN' == 'KEPT'
                 After xfail(strict=True, reason="GAP G16" / "GAP G40"): 2 xfailed
MUTATION:        illegal import present -> fails; removed -> original break remains
                 Added `import feelies.cli` to src/feelies/core/clock.py (not kept):
                   Contracts: 0 kept, 2 broken.
                   feelies.core is not allowed to import feelies.cli:
                   feelies.core is not allowed to import feelies.promotion:
                 Restored via git checkout -- src/feelies/core/clock.py; git diff empty:
                   Contracts: 0 kept, 2 broken.
                   feelies.core is not allowed to import feelies.promotion:
                 (cli edge gone). The contract cannot "pass once removed" until the
                 G16/G40 breaks themselves are gone; the extra edge is what the
                 mutation proved S2 sees.
TESTS:           4776 passed / 0 failed / 29 skipped / 9 xfailed
                 -> 4776 passed / 0 failed / 29 skipped / 11 xfailed
                 determinism 145 -> 145. The +2 xfailed are S2's two tests.
                 Nothing previously passing moved.
PARITY:          declared hold (All 26 hold. A module move changes no sequence
                 draw and no hashed field.) | actual 62 constants unmoved,
                 0 changed, key-for-key and value-for-value | MATCH.
                 verify_step S-04 (uncommitted, so FILES saw 0 touched against
                 HEAD): PARITY holds. NET DELTA note: "claiming deletions with
                 no negative delta did not do what it said" — cycle 2 still 2.
FILES DECLARED:  pyproject.toml
                 .github/workflows/ci.yml
                 tests/conformance/test_import_contracts.py
                 tools/arch/importgraph.py
                 src/feelies/core/inv12_stress.py -> src/feelies/research/inv12_stress.py
FILES TOUCHED:   pyproject.toml
                 .github/workflows/ci.yml
                 tests/conformance/test_import_contracts.py
                 tools/arch/importgraph.py
                 uv.lock   (UNDECLARED — required to add import-linter)
                 inv12_stress.py not moved
NET DELTA:       declared src modules 0 (one moves), public symbols 0, branch
                 points 0. Config files +2, test files +1, tools +1.
                 actual src modules 196 -> 196 (+0), public symbols 551 -> 551
                 (+0), sloc 43197 -> 43197 (+0), import cycles 2 -> 2 (+0).
                 Cycle 2 not deleted. MATCH on modules; DELETES not satisfied.
FINDINGS:        1. S-04b split taken. Eight importers of feelies.core.inv12_stress
                    are not in FILES. Updating them would fail verify_step.
                    src: promotion/evidence.py, research/decouple_gates.py,
                    harness/backtest_cli.py.
                    tests: acceptance/test_inv12_stress_gate.py,
                    acceptance/test_inv12_pnl_survival.py,
                    core/test_inv12_stress.py, research/test_decouple_gates.py,
                    harness/test_backtest_cli.py.
                    core/__init__.py does not re-export the module. The public
                    path feelies.core.inv12_stress would break.
                 2. The move cannot delete cycle 2 or the Tier 0 -> Tier 2 edge.
                    inv12_stress TYPE_CHECKING-imports platform_config;
                    platform_config lazily imports promotion.evidence (l.1199)
                    and sensors.spec (l.22). After a move that updates
                    promotion.evidence, the SCC becomes
                    research.inv12_stress -> platform_config ->
                    promotion.evidence -> research.inv12_stress. The layers
                    break `core -> promotion` is platform_config, not
                    inv12_stress, and survives the move.
                 3. The layers contract is also broken by G40: kernel.orchestrator
                    imports risk, execution, alpha, composition, ingestion,
                    monitoring, portfolio, sensors, signals, storage, services.
                    Dropping the G16 xfail after a successful move would still
                    fail. Independence is G40 residual until S-34.
                 4. tools/arch/coupling.py does not report import cycles.
                    VALIDATED BY named the wrong tool. measure.py / importgraph.py
                    do. importgraph.py after this step: 1 grimp SCC (the G16
                    chain), still PRESENT. measure.py n_cycles still 2 (cli
                    package cycle + G16).
                 5. uv.lock is required to add import-linter to the dev extra
                    and is not in FILES. CI `uv sync --all-extras --locked`
                    fails without it. OneDrive-locked venv uninstalls during
                    `uv sync` briefly broke pygments and certifi; repaired
                    with `uv pip install --no-deps`. Not a src defect.
                 6. I-23 notes S-04 should add a scan that the dynamic-import
                    count stays at one, and currently does not. Not added.
                 7. import-linter 2.13 exits 1 when contracts are broken (the
                    standing rule described exit 0). S2 still parses
                    "Contracts: N kept, M broken" and does not use the exit code.
                 8. Carried findings checked, no collision: G46 stays S-10;
                    G6 empty-sensors is FIX-1; src/feelies/risk/ not edited.
                 9. HEAD was exec/S-03 (f7f5f91), not arch/exec (aa413d9).
                    tools/exec differs from exec-tools-v1 by c6af7d7+aa413d9
                    (+96/-12), same as S-03. Cut exec/S-04 from f7f5f91. Same
                    tree as 2ffde72 (S-03 merge to main) which HEAD later sat
                    on; no content drift.
NOTES:           S-04b split taken: contract shipped xfailed, inv12_stress not
                 moved, xfail not dropped. Importers not updated. Blast radius
                 stayed boundary. Waiting at the human gate; do not commit.
                 Left uncommitted: baseline_pre-S-04.json, baseline_post-S-04.json,
                 this ledger entry, and the step files pending go/no-go.

## S-04b  cut the core->promotion edge
DATE:            2026-08-18T10:54:43+00:00
BASE SHA:        4f91bec26bda50a38cfcf27da1e7f449749e1630
RESULT SHA:      c7c1e90b111654f9fd9238144d2a6894a378295b
VERDICT:         passed
CONFORMANCE:     S2 G16 | xfail-before: yes | KEPT-after: yes
                 Step-2 before-state, captured before any implementation:
                   XFAIL tests/conformance/test_import_contracts.py::test_five_import_tiers - GAP G16
                   XFAIL tests/conformance/test_import_contracts.py::test_twelve_engine_independence - GAP G40
                   2 xfailed, 1 warning in 0.96s
                   lint-imports: Five import tiers BROKEN; Contracts: 0 kept, 2 broken.
                   feelies.core is not allowed to import feelies.promotion:
                   - feelies.core.platform_config -> feelies.promotion.evidence (l.1199)
                   importgraph: G16 chain (PRESENT): feelies.core.inv12_stress ->
                   feelies.core.platform_config -> feelies.promotion.evidence
                 After: G16 xfail dropped; 1 passed, 1 xfailed (G40).
                   core -> promotion absent from the layers report.
                   importgraph: G16 chain (absent); grimp SCCs 1 -> 0.
TESTS:           4777 passed / 0 failed / 28 skipped / 11 xfailed
                 -> 4778 passed / 0 failed / 28 skipped / 10 xfailed
                 determinism 145 -> 145. The +1 passed / -1 xfailed is G16's
                 xfail dropping. Nothing previously passing moved.
PARITY:          declared hold | actual 62 constants unmoved, 0 changed,
                 key-for-key and value-for-value | MATCH.
                 verify_step S-04b: FILES clean (uncommitted at the gate, so
                 0 vs HEAD; working tree was the 5 declared), PARITY holds,
                 CLEAN. Oracle `.upper()` cannot look up `S-04b` (finding 6).
FILES DECLARED:  src/feelies/core/platform_config.py
                 src/feelies/bootstrap.py
                 tests/core/test_platform_config_gate_thresholds.py
                 tests/bootstrap/test_gate_thresholds_wiring.py
                 tests/conformance/test_import_contracts.py
FILES TOUCHED:   src/feelies/core/platform_config.py
                 src/feelies/bootstrap.py
                 tests/core/test_platform_config_gate_thresholds.py
                 tests/bootstrap/test_gate_thresholds_wiring.py
                 tests/conformance/test_import_contracts.py
                 5 declared, 5 touched, nothing outside FILES. ci.yml
                 unchanged. src/feelies/risk/ not edited. inv12_stress not moved.
NET DELTA:       declared src modules 0, public symbols 0, branch points -1
                 | actual src modules 196 -> 196 (+0), public symbols 551 -> 551
                 (+0), sloc 43197 -> 43199 (+2), import cycles 2 -> 1 (-1),
                 alphaleak 2 -> 2 (+0). MATCH on modules. Cycle 2 deleted
                 (the G16 SCC). The +2 sloc is the bootstrap wrap.
FINDINGS:        1. The G.8 table registers G01-G45, with G46 deferred to S-10.
                 2. G6 rejects `depends_on_sensors: []`, contradicting the
                    unused-dependency audit for any control alpha.
                 3. The gross-exposure cap in BasicRiskEngine has no reduction
                    exemption. Under operator review. S-04b must not touch
                    src/feelies/risk/.
                 4. pre-step 4777/28 vs baseline_post-S-04.json 4776/29; live
                    capture used as before-state; parity 62/62 identical
                 5. load_platform_config + build_platform(config) does not
                    thread a Path, so harness backtest CLI and forensics lose
                    config-path attribution. Eager failure preserved. Outside
                    FILES; to be closed by a later step.
                 6. verify_step.py uppercases the step id, so letter-suffixed
                    steps need an invocation workaround. Oracle is frozen; do
                    not fix. Record against exec-tools-v2.
NOTES:           Malformed `gate_thresholds: {not_a_real_threshold: 5}` still
                 fails at startup as ConfigurationError, raised in
                 `_build_platform_gate_thresholds` wrapping ValueError from
                 `apply_gate_thresholds_overrides`. `build_platform(path)`
                 puts the config file path in the message. G40 xfail intact;
                 ci.yml `continue-on-error: true` unchanged until G40 closes.
                 The tiers assertion enumerates the three known residual
                 violations rather than checking the single edge, so a fourth
                 violation fails immediately and G40's closure forces the test
                 to be updated.
                 Left uncommitted for the operator: capture artifacts and this
                 ledger entry. The step commit contains the five declared
                 files only, per section 7.

## S-05  fail-closed position read in composition
DATE:            2026-08-18T11:55:41+00:00
BASE SHA:        80ea15c04ed2a3d509dc01bae3d3ca2fdff48aef
RESULT SHA:      b3847c8f71951e88e5554ab648647a8bd8d66448
VERDICT:         passed
CONFORMANCE:     X5 | failed-before: yes | passes-after: yes
                 X7 | failed-before: not run as a standalone fail-first
                 (AST scan; handler body was the fail-quiet assignment) |
                 passes-after: yes. S6 remains xfailed (G23/G36).
                 Step-2 XPASS then FAILED — see NOTES.
                 Handler-entry proof: lookup.calls and lookup.raised asserted
                 before the target check; both passed on the FAILED run, so
                 the injected KeyError reached composition/engine.py:384-389.
TESTS:           4778 passed / 0 failed / 28 skipped / 10 xfailed
                 -> 4780 passed / 0 failed / 28 skipped / 10 xfailed
                 determinism 145 -> 145. The +2 passed are X5 and X7; nothing
                 previously passing moved. Baseline figures read from
                 baseline_post-S-04b.json, which pre-S-05 matched key-for-key
                 (parity 62/62, tests 4778/28/10, sloc 43199).
PARITY:          declared hold (all 26; A5.3 counter on the four engine-6
                 baselines) | actual 62 constants unmoved, 0 changed,
                 key-for-key and value-for-value | MATCH.
                 verify_step S-05: FILES clean (uncommitted at the gate, so
                 0 vs HEAD; working tree was the 3 declared), PARITY holds,
                 CLEAN. NET DELTA compare-by-eye: modules 196->196, symbols
                 551->551, sloc 43199->43201 (+2, the raise), cycles 1->1.
FILES DECLARED:  src/feelies/composition/engine.py:384-389
                 tests/conformance/test_position_read_fails_closed.py (X5, new)
                 tests/conformance/test_exception_containment.py (X7, extend)
FILES TOUCHED:   src/feelies/composition/engine.py
                 tests/conformance/test_position_read_fails_closed.py
                 tests/conformance/test_exception_containment.py
                 3 declared, 3 touched, nothing outside FILES.
                 src/feelies/risk/ not edited. ci.yml not edited.
NET DELTA:       declared src modules 0, public symbols 0, branch points -1,
                 test files +2 | actual src modules 196 -> 196 (+0), public
                 symbols 551 -> 551 (+0), sloc 43199 -> 43201 (+2), import
                 cycles 1 -> 1 (+0), alphaleak 2 -> 2 (+0), fail-quiet
                 handlers 20 -> 19, test files +1 new and +1 extended.
                 MATCH on modules. Branch-point -1 is the fail-quiet
                 assignment replaced by a raise.
FINDINGS:        1. Degenerate empty `target_positions={}` is hold, not
                    flatten. `build_sized_intent_orders` returns
                    `SizedIntentRiskResult(orders=())` when the dict is
                    empty and otherwise iterates only the keys present;
                    `plan_leg` never backfills omitted symbols to zero.
                    Flatten requires explicit `TargetPosition(target_usd=0)`
                    entries. A failed lookup therefore does not unwind the
                    book. The payload is indistinguishable, by
                    `target_positions` alone, from completeness-degenerate,
                    `CompositionContextError`-degenerate, optimizer-null
                    `{}`, and a legitimate "hold" empty. Observability
                    only: `_emit_degenerate` suffixes `correlation_id`
                    with `:degenerate`; `horizon_metrics` counts every
                    empty intent as degenerate and may alert on rate.
                    Not fixed.
                 2. The G.8 table registers G01-G45, with G46 deferred to S-10.
                 3. G6 rejects `depends_on_sensors: []`, contradicting the
                    unused-dependency audit for any control alpha.
                 4. The gross-exposure cap in BasicRiskEngine has no reduction
                    exemption and preempts the drawdown check. S-05a is being
                    drafted. S-05 did not touch src/feelies/risk/.
                 5. load_platform_config + build_platform(config) loses
                    config-path attribution for the harness CLI and forensics
                    (S-04c, not yet written).
                 6. .github/workflows/ci.yml runs the import contract with
                    continue-on-error: true until G40 closes. Not flipped.
                 7. verify_step.py uppercases the step id; letter-suffixed
                    steps need an invocation workaround. Oracle is frozen.
NOTES:           A5.3 survives: all four engine-6 baselines unmoved
                 (level3_sized_intent_decay_off,
                 level3_sized_intent_decay_on, cross_sectional_context,
                 level4_portfolio_order), so the fail-quiet handler was
                 not firing in any recorded run.
                 The first X5 draft XPASSed under the buggy code because
                 two equal LONG strengths give z-score zero and an empty
                 book either way:
                   F  [100%]
                   [XPASS(strict)] GAP G20
                   1 failed in 0.21s
                 Replaced with an asymmetric book plus a lookup=None
                 control that must size, then re-proved FAILED
                 (--runxfail, still under xfail, before any handler change):
                   FAILED tests/conformance/test_position_read_fails_closed.py::
                   test_failed_position_lookup_halts_emits_and_produces_no_target
                   tests\conformance\test_position_read_fails_closed.py:165:
                   E   AssertionError: failed position lookup produced a
                       target (G20 silent-flat): [('x5_portfolio',
                       {'AAPL': 50000.0, 'MSFT': 50000.0, 'NVDA': -50000.0})]
                   1 failed in 0.31s
                 The exception caught is KeyError, raised as
                 CompositionContextError; `_dispatch_one` emits a
                 degenerate SizedPositionIntent and abandons the
                 boundary; fail-quiet handlers 20 -> 19;
                 `# pragma: no cover` removed.
                 Left uncommitted for the operator: capture artifacts and
                 this ledger entry. The step commit is the three declared
                 files only.

## S-05a  gross-cap reduction exemption; drawdown precedence
DATE:            2026-08-18T13:47:44+00:00
BASE SHA:        14b23cd7d7082dd4169ede4c3e194c591a412105
RESULT SHA:      31771af9456216a27f3d308f8847d72a92f36244
VERDICT:         passed
CONFORMANCE:     X3 repaired | failed-before: yes | passes-after: yes
                 clause-2 case | failed-before: yes | passes-after: yes
                 X3 pre-fix (binding 10% cap, two-symbol book, flatten AAPL):
                   FAILED tests/conformance/test_reduction_permitted.py::
                   TestGrossExposureCap::test_entry_refused_but_flatten_permitted
                   AssertionError: flattening order was not permitted: REJECT
                   ('gross exposure limit: 10000 >= 10000.0'). A degraded state
                   may tighten entries; refusing the exit strands the exposure
                   it is trying to protect (Inv-11).
                   1 failed in 0.28s
                 clause-2 pre-fix (500 AAPL @ 100 marked to 80, check_signal):
                   FAILED tests/risk/test_basic_risk.py::TestCheckOrder::
                   test_drawdown_wins_when_gross_and_drawdown_both_breach
                   AssertionError: assert <RiskAction.REJECT: 3> ==
                   <RiskAction.FORCE_FLATTEN: 4>
                   RiskVerdict(..., action=REJECT,
                   reason='gross exposure limit: 40000.00 >= 18000.000')
                   1 failed in 0.32s
                 After: X3 8 passed; clause-2 included in test_basic_risk 37 passed.
TESTS:           4780 passed / 0 failed / 28 skipped / 10 xfailed
                 -> 4782 passed / 0 failed / 28 skipped / 10 xfailed
                 determinism 145 -> 145. The +2 are exactly this step's two
                 new test functions; nothing previously passing moved.
                 Baseline figures read from baseline_post-S-05.json, which
                 pre-S-05a matched key-for-key (parity 62/62, tests 4780/28/10,
                 sloc 43201).
PARITY:          declared hold (all 62 constants) | actual 62 constants
                 unmoved, 0 changed, key-for-key and value-for-value | MATCH.
                 EXPECTED_RISK_VERDICT_HASH
                 b388a2c57da691c45eb8f3c3d041e74831390d29214e0f39d6881ae21e0cae7b
                 unmoved. EXPECTED_RISK_VERDICT_COUNT 4 unmoved.
                 verify_step S-05A missed the plan key (unfenced block plus
                 uppercase). Four checks by hand: FILES clean, PARITY holds,
                 tests +2, NET DELTA modules 0.
FILES DECLARED:  src/feelies/risk/basic_risk.py
                 tests/conformance/test_reduction_permitted.py
                 tests/risk/test_basic_risk.py
FILES TOUCHED:   src/feelies/risk/basic_risk.py
                 tests/conformance/test_reduction_permitted.py
                 tests/risk/test_basic_risk.py
                 3 declared, 3 touched, nothing outside FILES.
                 Step commit 31771af is those three files only.
NET DELTA:       declared src modules 0, public symbols 0, branch points +1
                 (the exemption) -1 (no new branch for reordering) = 0
                 | actual src modules 196 -> 196 (+0), public symbols 551 -> 551
                 (+0), sloc 43201 -> 43210 (+9), import cycles 1 -> 1 (+0),
                 alphaleak 2 -> 2 (+0). MATCH on modules. The +9 sloc is the
                 exemption flag, the HWM/drawdown reorder, and docstring.
FINDINGS:        The S-05a plan block was written outside a fenced code block,
                 so verify_step._blocks dropped it and --list reported
                 "36 of 36 fully specified" for a plan containing 37 steps.
                 A step that fails to parse is invisible, not reported --
                 same shape as the blind oracle (43 of 62 constants) and
                 the vacuous X3 cap. Every verification tool here needs a
                 coverage assertion, not just a pass/fail. Record against
                 exec-tools-v2 alongside the uppercase step-id bug.
                 Also: this step's PROBLEM field cites equity 89995 / cap
                 17999, which assumed a fee this path does not charge;
                 actual is 90000 / 18000.
                 Carried, not fixed: G.8 registers G01-G45 (G46 is S-10);
                 G6 rejects depends_on_sensors: []; load_platform_config +
                 build_platform(config) loses config-path attribution
                 (S-04c); ci.yml import contract continue-on-error: true
                 until G40; test_forced_exit_attribution_replay.py:193-196
                 stubs check_signal/check_order.
NOTES:           X3 was vacuous at _loose_config:81 (cap 100.0); repaired as
                 a separate TestGrossExposureCap rather than by mutating
                 the shared fixture, preserving the other seven states'
                 gate isolation. The exemption predicate is "prospective
                 exposure does not increase", supplied by the caller --
                 exposure_override vs snapshot at gate 2, signal_reduces at
                 gate 1. The same flag exempts the scale-down band; found
                 because X3 still failed after a REJECT-only exemption.
                 HWM staleness resolved: rally-over-cap probe gives
                 _high_water_mark 110000.
                 Parent of the step commit is fc907c5 (plan: fence the
                 S-05a block), landed while waiting at the gate. Captures
                 were taken at 14b23cd; fc907c5 is plan-only and does not
                 move parity.
                 Left uncommitted for the operator: capture artifacts and
                 this ledger entry.

## S-06  fail-closed unregistered strategy_id
DATE:            2026-08-19T09:22:37+08:00
BASE SHA:        2493c93055231c1cd609f98be4d5a34a027f4ada
RESULT SHA:      not committed — blocked at the boundary gate
VERDICT:         blocked
CONFORMANCE:     X4 (tests/conformance/test_per_alpha_budget.py) |
                 failed-before: yes | passes-after: yes (uncommitted)
                 X6 narrow (tests/conformance/test_pathological_refusal.py) |
                 failed-before: yes | passes-after: yes (uncommitted)
                 Step-2 failure output, captured before any src edit:
                   FAILED tests/conformance/test_per_alpha_budget.py::
                   test_unregistered_strategy_id_is_refused_and_does_not_reach_inner
                   tests\conformance\test_per_alpha_budget.py:192: in
                   test_unregistered_strategy_id_is_refused_and_does_not_reach_inner
                       assert inner.orders == [], (
                   E   AssertionError: unregistered strategy_id was forwarded
                       to the inner engine (G23 swallow):
                       ['not_a_registered_alpha']. The order proceeded
                       unbudgeted.
                   FAILED tests/conformance/test_pathological_refusal.py::
                   test_unregistered_strategy_id_fixture_is_refused
                   tests\conformance\test_pathological_refusal.py:36: in
                   test_unregistered_strategy_id_fixture_is_refused
                       assert inner.orders == [], (
                   E   AssertionError: pathological unregistered id was
                       forwarded unbudgeted: ['not_a_registered_alpha']
                   2 failed, 3 passed in 0.46s
                 Handler-entry proof: both failures are the inner.orders
                 assert. The preceding registry.lookups == [unregistered]
                 and registry.key_errors == [unregistered] asserts passed,
                 so registry.get raised KeyError at check_order:186-192
                 and the except body swallowed it. A failure at the lookup
                 asserts would have meant the scenario never entered the
                 handler.
                 Controls, passing throughout (the 3 passed above, and
                 again after the src edit):
                   test_registered_strategy_id_is_budgeted_and_permitted
                   test_registered_strategy_id_over_position_limit_is_rejected
                   test_synthetic_prefix_uses_aggregate_checks_only
TESTS:           4781 passed / 0 failed / 29 skipped / 10 xfailed
                 -> not advanced. After the src edit, X4+X6 are 5 passed,
                 but two previously-passing tests outside FILES go red
                 (see FINDINGS). Full suite, determinism, post-capture
                 and verify_step were not run. Pre-S-06 capture matched
                 baseline_post-S-05a.json key-for-key (parity 62/62,
                 tests 4781/29/10, sloc 43210, symbols 551, modules 196,
                 cycles 1). S-05a ledger said 4782/28; the artifact and
                 this capture both say 4781/29. Artifact wins.
PARITY:          declared hold (all 26, provided synthetic ``__`` prefix
                 lands before the unregistered refusal) | actual not
                 recaptured | n/a (blocked before post-capture).
                 Hold is structural: no determinism tape reaches the
                 changed path (see NOTES).
FILES DECLARED:  src/feelies/alpha/risk_wrapper.py:186-192
                 tests/conformance/test_per_alpha_budget.py (X4)
                 tests/conformance/test_pathological_refusal.py (X6, narrow)
                 tests/conformance/fixtures/pathological/ (FIX-3 case 1)
FILES TOUCHED:   src/feelies/alpha/risk_wrapper.py
                 tests/conformance/test_per_alpha_budget.py
                 tests/conformance/test_pathological_refusal.py
                 tests/conformance/fixtures/pathological/unregistered_strategy_id.yaml
                 4 touched against 3 named files + 1 directory scope.
                 Need, not touched: tests/alpha/test_risk_wrapper.py
NET DELTA:       declared src modules 0, public symbols 0, branch points
                 -1 +1 = 0, test files +2 | actual not measured
FINDINGS:        1. PLAN DEFECT / blocker — FILES does not list
                    tests/alpha/test_risk_wrapper.py, which pins the G23
                    fail-open as correct:
                      TestCheckOrderDelegatesToInner.test_unknown_strategy_passes_through
                      (strategy_id='unknown_alpha' must be ALLOW/SCALE_DOWN)
                      TestCheckSizedIntent.test_unregistered_strategy_id_falls_through
                      (strategy_id='multi_alpha_net' must emit one order)
                    After the in-FILES edit both fail. Editing them would
                    be UNDECLARED. Leaving them fails "previously-passing
                    test now failing". The step cannot land until FILES
                    is amended to include that file (and those two tests
                    inverted to expect REJECT / dropped legs).
                 2. check_signal:68-71 still does
                    ``except KeyError: return self._inner.check_signal(...)``.
                    Same shape as G23, on the signal path. FILES names
                    only check_order:186-192. Not fixed.
                 3. An unregistered flatten is also REJECT under this
                    edit (exposure does not increase; it also cannot
                    decrease via this path). Empty strategy_id still
                    falls through to aggregate checks (unit test still
                    green). ``__``-prefixed ids skip per-alpha and still
                    reach the inner engine.
                 4. Carried, not fixed: G.8 registers G01-G45 (G46 is
                    S-10); G6 rejects depends_on_sensors: [];
                    load_platform_config + build_platform(config) loses
                    config-path attribution (S-04c); ci.yml import
                    contract continue-on-error: true until G40;
                    verify_step.py uppercases the step id and drops
                    unfenced blocks (S-06 is fenced, invocation is
                    ``S-06``); test_forced_exit_attribution_replay.py
                    :193-196 stubs check_signal/check_order.
NOTES:           Caller on the unregistered non-synthetic path observes
                 RiskVerdict(action=REJECT, reason contains the id and
                 "per-alpha budget unknown; order refused"). Inner
                 check_order is not called. Exposure does not increase.
                 Determinism tapes (rg -l risk_wrapper|RiskWrapper|strategy_id
                 under tests/determinism/): none name the wrapper.
                 test_orchestrator_replay.py is the only hit that
                 constructs it (build_platform, enforce_per_alpha_risk_budget
                 defaults True). Its main stream has 0 orders; the
                 stop-exit stream has 1 order with strategy_id "" which
                 never enters ``if strategy_id:``.
                 test_risk_verdict_replay.py builds BasicRiskEngine
                 directly and calls check_signal with strategy_id="probe"
                 — not the wrapper, not check_order.
                 test_decoupled_safety_replay.py / test_hazard_exit_replay.py
                 emit OrderRequest from ExitComposer / HazardExitController,
                 not wrapper.check_order.
                 test_portfolio_order_replay.py builds BasicRiskEngine.
                 test_forced_exit_attribution_replay.py stubs check_order
                 to always ALLOW (carried finding).
                 Remaining hits hash strategy_id on Signal/intent/JSONL
                 and do not construct risk.
                 Hold is structural: the KeyError handler is not on any
                 taped stream.
                 Blast radius stated boundary; order-path touch noted.
                 Waiting at the human gate. Do not commit. Do not begin
                 S-07.
                 Left uncommitted: baseline_pre-S-06.json, this ledger
                 entry, and the four declared files pending go/no-go
                 (FILES amendment vs revert).

## S-06  fail-closed unregistered strategy_id
DATE:            2026-08-19T09:59:18+08:00
BASE SHA:        2493c93055231c1cd609f98be4d5a34a027f4ada
RESULT SHA:      12c8dcdf3a5099082aa3ca9340bd4741a3d5452b
VERDICT:         passed
CONFORMANCE:     X4 (tests/conformance/test_per_alpha_budget.py) |
                 failed-before: yes | passes-after: yes
                 X6 narrow (tests/conformance/test_pathological_refusal.py) |
                 failed-before: yes | passes-after: yes
                 test_unknown_strategy_passes_through rewritten |
                 failed-before: yes | passes-after: yes
                 test_unregistered_strategy_id_falls_through rewritten |
                 failed-before: yes | passes-after: yes
                 Step-2 failure output, captured after restoring
                 risk_wrapper.py and before re-implementing:
                   FAILED tests/conformance/test_per_alpha_budget.py::
                   test_unregistered_strategy_id_is_refused_and_does_not_reach_inner
                   tests\conformance\test_per_alpha_budget.py:192:
                   E   AssertionError: unregistered strategy_id was forwarded
                       to the inner engine (G23 swallow):
                       ['not_a_registered_alpha']. The order proceeded
                       unbudgeted.
                   FAILED tests/conformance/test_pathological_refusal.py::
                   test_unregistered_strategy_id_fixture_is_refused
                   tests\conformance\test_pathological_refusal.py:36:
                   E   AssertionError: pathological unregistered id was
                       forwarded unbudgeted: ['not_a_registered_alpha']
                   FAILED tests/alpha/test_risk_wrapper.py::
                   TestCheckOrderDelegatesToInner::test_unknown_strategy_passes_through
                   tests\alpha\test_risk_wrapper.py:361:
                   E   AssertionError: unregistered strategy_id reached the
                       inner engine; the order proceeded unbudgeted
                   FAILED tests/alpha/test_risk_wrapper.py::
                   TestCheckSizedIntent::test_unregistered_strategy_id_falls_through
                   tests\alpha\test_risk_wrapper.py:490:
                   E   AssertionError: unregistered strategy_id reached the
                       inner engine on the portfolio path; the intent
                       proceeded unbudgeted
                   4 failed, 6 passed in 0.36s
                 Handler-entry proof: every failure is the inner.orders
                 assert. Lookups/KeyError asserts in X4/X6 passed, so
                 registry.get raised at check_order and the except body
                 swallowed it. The two rewritten unit tests fail the
                 same way: the recording inner saw the order.
                 Controls, passing throughout (the 6 passed above):
                   X4 registered in-budget permitted
                   X4 registered over position-limit rejected
                   X4 synthetic prefix aggregate-only
                   test_empty_strategy_id_passes_through
                   test_registered_strategy_delegates_to_inner
                   test_synthetic_prefix_delegates_to_inner
                 After implement: tests/alpha/test_risk_wrapper.py 26
                 passed; tests/conformance 26 passed / 10 xfailed.
TESTS:           4781 passed / 0 failed / 29 skipped / 10 xfailed
                 -> 4788 passed / 0 failed / 29 skipped / 10 xfailed
                 determinism 145 -> 145. The +7 are X4's four tests, X6's
                 one test, and two new delegation tests on
                 TestCheckOrderDelegatesToInner. The two rewritten tests
                 were already in the suite. Nothing previously passing
                 moved. Pre-S-06 recapture matched
                 baseline_post-S-05a.json key-for-key (parity 62/62,
                 tests 4781/29/10, sloc 43210).
PARITY:          declared hold | actual 62 constants unmoved, 0 changed,
                 key-for-key and value-for-value | MATCH.
                 verify_step S-06: FILES clean (uncommitted vs HEAD, 0
                 touched), PARITY holds, CLEAN. NET DELTA compare-by-eye:
                 modules 196->196, symbols 551->551, sloc 43210->43219
                 (+9), cycles 1->1.
FILES DECLARED:  src/feelies/alpha/risk_wrapper.py:186-192
                 tests/conformance/test_per_alpha_budget.py (X4)
                 tests/conformance/test_pathological_refusal.py (X6, narrow)
                 tests/conformance/fixtures/pathological/ (FIX-3 case 1)
                 tests/alpha/test_risk_wrapper.py
FILES TOUCHED:   src/feelies/alpha/risk_wrapper.py
                 tests/conformance/test_per_alpha_budget.py
                 tests/conformance/test_pathological_refusal.py
                 tests/conformance/fixtures/pathological/unregistered_strategy_id.yaml
                 tests/alpha/test_risk_wrapper.py
                 5 touched against 4 named files + 1 directory scope.
                 Step commit 12c8dcd is those five files only.
NET DELTA:       declared src modules 0, public symbols 0, branch points
                 -1 +1 = 0, test files +2 | actual src modules 196 -> 196
                 (+0), public symbols 551 -> 551 (+0), sloc 43210 ->
                 43219 (+9), import cycles 1 -> 1 (+0), alphaleak 2 -> 2
                 (+0), test files +2 new and +1 extended. MATCH on
                 modules. The +9 sloc is the REJECT return and the
                 explicit ``__`` prefix test.
FINDINGS:        AlphaRegistry.register does not re-apply _ALPHA_ID_RE, so a
                 programmatically registered module with a `__` prefix would
                 count as registered and skip per-alpha budgets. The YAML path
                 is closed (loader and SCHEMA.md both enforce
                 ^[a-z][a-z0-9_]*$); this is the remaining route to an
                 unbudgeted order. Not fixed here.
                 Also not fixed: check_signal:68-71 still does
                 ``except KeyError: return self._inner.check_signal(...)``.
                 Carried: G.8 registers G01-G45 (G46 is S-10); G6 rejects
                 depends_on_sensors: []; load_platform_config +
                 build_platform(config) loses config-path attribution
                 (S-04c); ci.yml import contract continue-on-error: true
                 until G40; verify_step.py uppercases the step id and
                 drops unfenced blocks; test_forced_exit_attribution_replay.py
                 :193-196 stubs check_signal/check_order.
NOTES:           two committed tests from e3281a1 pinned the G23 fail-open
                 as intended and were rewritten, not deleted, to assert the
                 new contract; the class docstring's delegation claim remains
                 tested via test_registered_strategy_delegates_to_inner and
                 test_synthetic_prefix_delegates_to_inner;
                 test_empty_strategy_id_passes_through pins the
                 strategy_id="" case the stop-exit determinism stream
                 relies on. Parity hold is structural: no determinism tape
                 reaches the KeyError handler; only
                 test_orchestrator_replay.py builds the wrapper, with 0
                 orders on the main stream.
                 Caller on the unregistered non-synthetic path observes
                 RiskVerdict(action=REJECT, reason contains the id and
                 "per-alpha budget unknown; order refused"). Inner
                 check_order is not called. Exposure does not increase.
                 Left uncommitted for the operator: baseline_pre-S-06.json,
                 baseline_post-S-06.json, this ledger entry, and the plan
                 amendment in phase7_migration.md. The step commit is the
                 five declared files only.

## S-06a  validate alpha_id at the registry
DATE:            2026-08-19T10:57:56+08:00
BASE SHA:        c277ba7c6debd8e7afc26ea8208677897036744b
RESULT SHA:      e8ef690f1e2df58ba8d6d4176a096365d91ac1bc
VERDICT:         passed
CONFORMANCE:     test_double_underscore_prefixed_id_is_refused_by_registry
                 (tests/conformance/test_per_alpha_budget.py) |
                 failed-before: yes | passes-after: yes
                 TestAlphaIdRuleAtRegister.test_double_underscore_prefix_rejected_without_mutation
                 (tests/alpha/test_registry_per_alpha_thresholds.py) |
                 failed-before: yes | passes-after: yes
                 Step-2 failure output, captured before any src edit.
                 Acceptance proof (register returned; id present; then fail):
                   FAILED tests/conformance/test_per_alpha_budget.py::
                   test_double_underscore_prefixed_id_is_refused_by_registry
                   tests\conformance\test_per_alpha_budget.py:296: in
                   test_double_underscore_prefixed_id_is_refused_by_registry
                       assert False, (
                   E   AssertionError: registry ACCEPTED invalid id
                       '__synthetic_probe__'; rule ^[a-z][a-z0-9_]*$ should
                       have refused it with AlphaRegistryError
                   E   assert False
                   1 failed, 5 passed in 0.40s
                 The presence assert held, so this is the registry accepting
                 the id, not a malformed stub, validate() rejection, or
                 duplicate. Final-form pytest.raises then also failed before
                 the src edit:
                   FAILED tests/conformance/test_per_alpha_budget.py::
                   test_double_underscore_prefixed_id_is_refused_by_registry
                   E   Failed: DID NOT RAISE <class
                       'feelies.alpha.registry.AlphaRegistryError'>
                   FAILED tests/alpha/test_registry_per_alpha_thresholds.py::
                   TestAlphaIdRuleAtRegister::
                   test_double_underscore_prefix_rejected_without_mutation
                   E   Failed: DID NOT RAISE <class
                       'feelies.alpha.registry.AlphaRegistryError'>
                   2 failed, 2 passed in 0.34s
                 Controls, passing throughout:
                   test_valid_alpha_id_still_registers
                   TestAlphaIdRuleAtRegister.test_valid_id_still_registers
                 After implement: test_per_alpha_budget 6 passed;
                 test_registry_per_alpha_thresholds 19 passed.
TESTS:           4788 passed / 0 failed / 29 skipped / 10 xfailed
                 -> 4792 passed / 0 failed / 29 skipped / 10 xfailed
                 determinism 145 -> 145. The +4 are exactly this step's four
                 new test functions. Nothing previously passing moved.
                 Pre-S-06a capture matched baseline_post-S-06.json key-for-key
                 (parity 62/62, tests 4788/29/10, sloc 43219, symbols 551,
                 modules 196, cycles 1). SHA differs (c277ba7 vs 544572d);
                 artifact wins on the numbers.
PARITY:          declared hold | actual 62 constants unmoved, 0 changed,
                 key-for-key and value-for-value | MATCH.
                 verify_step S-06A missed the plan key (uppercase). Four
                 checks by hand: FILES clean, PARITY holds, tests +4, NET
                 DELTA modules 0.
FILES DECLARED:  src/feelies/alpha/registry.py
                 src/feelies/alpha/loader.py
                 tests/conformance/test_per_alpha_budget.py
                 tests/alpha/test_registry_per_alpha_thresholds.py
FILES TOUCHED:   src/feelies/alpha/registry.py
                 src/feelies/alpha/loader.py
                 tests/conformance/test_per_alpha_budget.py
                 tests/alpha/test_registry_per_alpha_thresholds.py
                 4 declared, 4 touched, nothing outside FILES.
NET DELTA:       declared src modules 0, public symbols 0, branch points +1
                 | actual src modules 196 -> 196 (+0), public symbols 551 ->
                 551 (+0), sloc 43219 -> 43226 (+7), import cycles 1 -> 1
                 (+0), n_edges 608 -> 609 (loader now imports registry),
                 alphaleak 2 -> 2 (+0), test files +0 new and +2 extended.
                 MATCH on modules. The +7 sloc is the register() guard,
                 import re, and the regex relocation.
FINDINGS:        No suite test asserts AlphaLoadError on an invalid
                 alpha_id. The loader has enforced ^[a-z][a-z0-9_]*$ at
                 :866 since before this campaign and nothing verifies it;
                 removing that line would leave every test green. The YAML
                 door was called closed throughout S-06 and S-06a on the
                 strength of code alone. Verified by a one-off during this
                 step, not by the suite. Fold into S-04c, which is already
                 queued for loader-adjacent work.
                 Also carried, not fixed: G.8 registers G01-G45 (G46 is
                 S-10); G6 rejects depends_on_sensors: [];
                 load_platform_config + build_platform(config) loses
                 config-path attribution (S-04c); ci.yml import contract
                 continue-on-error: true until G40; verify_step.py
                 uppercases the step id (S-06A missed S-06a).
NOTES:           _ALPHA_ID_RE now lives in registry.py and loader.py
                 imports it; registry did not previously import loader, so
                 the relocation is one-way with no cycle (n_edges 608 ->
                 609, cycles unchanged at 1). The fail-first evidence shows
                 the registry accepting '__synthetic_probe__' and retaining
                 it in _alphas before the guard, then DID NOT RAISE in
                 final form. The wrapper's `__` branch is now reachable
                 only by a platform-constructed order strategy_id -- one
                 instance in src/, orchestrator.py:4006 -- not by
                 registration.
                 G16 still KEPT (1 passed); G40 still xfail. ci.yml not
                 flipped. Step commit e8ef690 is the four declared files
                 only. Left uncommitted for the operator:
                 baseline_pre-S-06a.json, baseline_post-S-06a.json, and
                 this ledger entry.

## S-07  per-engine latency budget and breach response
DATE:            2026-08-19T11:56:13+08:00
BASE SHA:        fe9a0540af00b44b3c2bb00fa92246506c14d1b1
RESULT SHA:      not committed — blocked at the platform-wide gate
VERDICT:         blocked
CONFORMANCE:     X10 | failed-before: yes | passes-after: yes (uncommitted)
                 Step-2 failure output, captured before any src edit:
                   FAILED tests/conformance/test_latency_budget.py::
                   test_x10_tick_timings_are_compared_to_a_budget
                   tests\conformance\test_latency_budget.py:57: in
                   test_x10_tick_timings_are_compared_to_a_budget
                       assert compared, (
                   E   AssertionError: no comparison exists: _tick_timings
                       is published as MetricEvents and never compared to a
                       budget
                   E   assert False
                   1 failed in 0.45s
                 Site-identity asserts (_tick_timings read, MetricEvent
                 published) passed on that run: the failure is the third
                 assert, so this is "no comparison exists", not a missing
                 table or the wrong function.
                 After implement, X10 6 passed (comparison site, (i), (ii),
                 (iii), never-seen, HARN-2 replay).
TESTS:           4792 passed / 0 failed / 29 skipped / 10 xfailed
                 -> 4796 passed / 2 failed / 29 skipped / 10 xfailed
                 (full suite). The +6 X10 tests passed; the 2 failures are
                 S4's call-granular allowlist in
                 tests/acceptance/test_no_walltime_outside_clock.py, which
                 is not in FILES. Determinism 145 -> 145. Parity constants
                 62/62 value-for-value MATCH vs baseline_post-S-06a.json.
                 Pre-S-07 capture matched that artifact key-for-key
                 (parity 62/62, tests 4792/29/10, sloc 43226, symbols 551,
                 modules 196, cycles 1). SHA differs (fe9a054 vs 14b056e);
                 artifact wins on the numbers.
PARITY:          declared hold (all 26, conditional on (a) and (b)) |
                 actual 62 constants unmoved, 0 changed, key-for-key and
                 value-for-value | MATCH. Conditions (a) and (b) both held:
                 LatencyBreach is constructed with sequence=0 and the
                 handler does not draw self._seq; BACKTEST skips the
                 comparison so baselines take the no-breach branch.
                 Determinism 145 passed. R1 under PYTHONHASHSEED=random
                 with FEELIES_REQUIRE_BASELINE_CACHE=1: 2 passed in 17.57s
                 (replayed, did not skip).
                 verify_step S-07: FILES clean (uncommitted vs HEAD, 0
                 touched); PARITY cannot check (no post capture — suite
                 red); NET DELTA cannot check. Oracle .upper() parses
                 S-07. BLAST RADIUS parser treats "Not platform-wide" as
                 naming platform-wide (substring); frozen, not fixed.
FILES DECLARED:  src/feelies/core/events.py (LatencyBreach, new)
                 src/feelies/monitoring/ (budget predicate + breach record)
                 src/feelies/core/platform_config.py (per-engine budget table)
                 src/feelies/kernel/orchestrator.py:2126-2153 (comparison site)
                 tests/conformance/test_latency_budget.py (X10)
FILES TOUCHED:   src/feelies/core/events.py
                 src/feelies/core/platform_config.py
                 src/feelies/kernel/orchestrator.py
                 src/feelies/monitoring/latency_budget.py
                 tests/conformance/test_latency_budget.py
                 5 touched against 4 named files + 1 directory scope.
                 Need, not touched: tests/acceptance/test_no_walltime_outside_clock.py
NET DELTA:       declared src modules +1, public symbols +2 (LatencyBreach,
                 the budget table), branch points +2, test files +1 |
                 actual not recaptured (suite red). By eye: +1 module
                 (latency_budget.py), +2 public classes (LatencyBreach,
                 EngineLatencyBudget). ENGINE_LATENCY_BUDGETS is an
                 assignment and is not counted. Predicate names are
                 _-prefixed.
FINDINGS:        1. PLAN DEFECT / blocker — FILES does not list
                    tests/acceptance/test_no_walltime_outside_clock.py,
                    whose S4 call-granular allowlist pins ten
                    time.perf_counter_ns() sites by line number. Inserting
                    the comparison at :2126-2153 (and the subscribe/import
                    lines above it) shifts those lines; no new wall-clock
                    read was added. After the insertion the live sites are
                    1533, 1642, 1644, 1684, 1686, 1780, 1782, 2113, 3958,
                    3968 vs the pinned 1524, 1633, 1635, 1675, 1677, 1771,
                    1773, 2104, 3940, 3950. Editing the allowlist would be
                    UNDECLARED. Leaving it fails "previously-passing test
                    now failing". The step cannot land until FILES is
                    amended to include that file (retarget the ten tuples;
                    no new perf_counter read).
                 2. The S-07 block names statistic=p99 and window type
                    (rolling event count) but not the numeric window or
                    per-engine budget_ns. Landed as window_events=100 and
                    budget_ns=3_000_000 (the plan's U-7 3 ms tick-to-decision
                    p99 target) on every hot-path engine. G41's 10 µs/event
                    overrun remains S-33.
                 3. OperatingMode has only BACKTEST and PAPER (no LIVE).
                    "Comparison, live only" is implemented as
                    mode is not BACKTEST.
                 4. LatencyBreach is published on the bus with sequence=0
                    and is not appended to InMemoryEventLog. That log is
                    sequence-bisect ordered for quotes/trades; appending
                    sequence=0 would corrupt last_sequence/replay. The bus
                    record is the append-only breach journal. Not fixed.
                 5. Carried, not fixed: G.8 registers G01-G45 (G46 is
                    S-10); G6 rejects depends_on_sensors: [];
                    load_platform_config + build_platform(config) loses
                    config-path attribution (S-04c); ci.yml import
                    contract continue-on-error: true until G40;
                    verify_step.py uppercases the step id and drops
                    unfenced blocks; the `__` prefix is a platform
                    sentinel with two instances and no central definition.
NOTES:           the statistic and window per engine: p99 over 100 events,
                 budget 3_000_000 ns, for sensor_fanout_ns,
                 sm_transition_ns, signal_evaluate_ns, risk_check_ns,
                 tick_to_decision_latency_ns.
                 (iii): 98 samples of 1_000 ns and 2 of 1_000_000 ns,
                 window 100, budget 50_000 ns; mean 20_980 < budget, p99
                 1_000_000 > budget, LatencyBreach fired with sequence=0.
                 A mean-based predicate would not have breached.
                 Conditions (a) and (b) both held (see PARITY).
                 Unread-metric path: supplemented, not removed. _tick_timings
                 is now a compared input on PAPER; MetricEvent
                 publish/record is retained because dropping the
                 seq.next() publishes on signal_evaluate_ns/risk_check_ns
                 would shift kernel event IDs (undeclared parity movement).
                 HARN-2: FaultInjector.slow_engine("risk_check_ns",
                 10_000_000 ns), 100 calls, samples taken from the injected
                 SimulatedClock delta; live monitor wrote LatencyBreach;
                 replay applied _apply_breach_response to the stored
                 records on a fresh monitor that was still NEVER_SEEN
                 (no re-measure) and the kill switch activated.
                 Quoted :2126 comment: "Record always-on timers directly so
                 they cannot shift kernel event IDs."
                 Waiting at the human gate. Do not commit. Do not begin
                 S-08.
                 Left uncommitted: baseline_pre-S-07.json, this ledger
                 entry, and the five declared files pending FILES
                 amendment vs revert.

## S-07  per-engine latency budget and breach response
DATE:            2026-08-19T13:38:13+08:00
BASE SHA:        fe9a0540af00b44b3c2bb00fa92246506c14d1b1
RESULT SHA:      not committed — waiting at the platform-wide gate
VERDICT:         blocked
CONFORMANCE:     X10 | failed-before: yes | passes-after: yes
                 S4 retarget | failed-before: yes (line shift) |
                 passes-after: yes
                 Step-2 X10 failure (unchanged, captured before src edit):
                   E   AssertionError: no comparison exists: _tick_timings
                       is published as MetricEvents and never compared to a
                       budget
                 S4 guard proof, throwaway at orchestrator.py:3979 in
                 _escalate_unfilled_working_exits (after the last
                 line-pinned site, so the seven pins did not shift):
                   FAILED tests/acceptance/test_no_walltime_outside_clock.py::
                   test_no_raw_wall_clock_outside_allowlist
                   E   AssertionError: raw wall-clock reads found outside
                       the Inv-10 allowlist ...
                   E       kernel/orchestrator.py:3979  time.perf_counter_ns()
                   1 failed, 1 passed in 0.93s
                 Restore from pre-insert backup: SHA256
                 141A8D85D67780AE8B7F2E5117BCAC24CA5BC5F15F88AEBD55B7D0DB32A66552
                 BYTE_IDENTICAL. S4 after restore: 2 passed in 0.80s.
TESTS:           4792 passed / 0 failed / 29 skipped / 10 xfailed
                 -> 4798 passed / 0 failed / 29 skipped / 10 xfailed
                 determinism 145 -> 145. The +6 are X10. S4 was already in
                 the suite (2 tests, both pass). Nothing previously
                 passing moved. Post-S-07 capture BASELINE: GREEN.
PARITY:          declared hold | actual 62 constants unmoved, 0 changed,
                 key-for-key and value-for-value | MATCH.
                 Conditions (a) and (b) both held. R1 under
                 PYTHONHASHSEED=random + FEELIES_REQUIRE_BASELINE_CACHE=1:
                 2 passed in 17.22s (replayed, did not skip).
                 verify_step S-07 --base fe9a054: FILES clean, PARITY
                 holds, CLEAN. NET DELTA: modules 196->197 (+1), symbols
                 551->553 (+2), sloc 43226->43376 (+150), cycles 1->1,
                 alphaleak 2->2. n_edges 609->613 (not declared).
FILES DECLARED:  src/feelies/core/events.py
                 src/feelies/monitoring/
                 src/feelies/core/platform_config.py
                 src/feelies/kernel/orchestrator.py:2126-2153
                 tests/conformance/test_latency_budget.py
                 tests/acceptance/test_no_walltime_outside_clock.py
FILES TOUCHED:   src/feelies/core/events.py
                 src/feelies/core/platform_config.py
                 src/feelies/kernel/orchestrator.py
                 src/feelies/monitoring/latency_budget.py
                 tests/conformance/test_latency_budget.py
                 tests/acceptance/test_no_walltime_outside_clock.py
                 6 touched against 5 named files + 1 directory scope.
                 Nothing outside FILES.
NET DELTA:       declared src modules +1, public symbols +2, branch points
                 +2, test files +1 | actual src modules 196 -> 197 (+1),
                 public symbols 551 -> 553 (+2), sloc 43226 -> 43376
                 (+150), import cycles 1 -> 1 (+0), alphaleak 2 -> 2 (+0),
                 test files +1 new and +1 extended. MATCH on modules and
                 symbols. The +150 sloc is LatencyBreach, the budget
                 table, the monitor, and the comparison/handler. Test
                 files: +1 is X10; S4 is extend.
FINDINGS:        Carried, not fixed: G.8 registers G01-G45 (G46 is S-10);
                 G6 rejects depends_on_sensors: []; load_platform_config +
                 build_platform(config) loses config-path attribution
                 (S-04c); ci.yml import contract continue-on-error: true
                 until G40; verify_step.py uppercases the step id and
                 drops unfenced blocks; the `__` prefix is a platform
                 sentinel with two instances and no central definition;
                 OperatingMode has BACKTEST and PAPER only (no LIVE);
                 LatencyBreach is bus-published sequence=0, not appended
                 to InMemoryEventLog (sequence-bisect of quotes/trades).
                 Window 100 and budget_ns 3_000_000 are declared on each
                 entry; the block named the statistic and window type,
                 not N. G41's 10 µs/event overrun remains S-33.
NOTES:           S4 ten tuples: seven retargeted in place (1642, 1644,
                 1684, 1686, 1780, 1782, 3968). Three G01 residuals
                 re-keyed by enclosing symbol (_process_tick_inner,
                 _finalize_tick, _drain_async_fills). Each symbol entry
                 admits one leftover call after line pins are applied, so
                 a second unmatched read in a symbol-keyed function is
                 still an offender. Comment at :39-43 names symbols, not
                 line numbers.
                 Statistic and window per engine: p99 over 100 events,
                 3_000_000 ns, for the five hot-path keys.
                 (iii): mean 20_980 under 50_000, p99 1_000_000 over,
                 breach fired sequence=0.
                 Conditions (a) and (b) both held.
                 Unread-metric path: supplemented, not removed
                 (MetricEvent publish remains per amended DELETES).
                 HARN-2 replay-without-re-measure: fresh monitor stayed
                 NEVER_SEEN; kill switch activated from stored records.
                 Waiting at the human gate. Do not commit. Do not begin
                 S-08.
                 Left uncommitted: baseline_pre-S-07.json,
                 baseline_post-S-07.json, this ledger entry, and the six
                 declared files pending go/no-go.

## S-07  2026-08-19T13:48:39+08:00
  STEP:          S-07
  BASE:          fe9a0540af00b44b3c2bb00fa92246506c14d1b1
  RESULT SHA:    7bf6acd9318f17d8ea64079bcaa504db3c316f1b
  VERDICT:       passed
  CONFORMANCE:   34 passed, 10 xfailed
  TESTS:         4792 passed / 29 skipped / 10 xfailed
                 -> 4798 passed / 29 skipped / 10 xfailed
  PARITY:        hold, 62 constants unmoved
  FILES:         6 declared, 6 committed (clean vs 7bf6acd)
  NET DELTA:     modules 196 -> 197 (+1)
                 public_symbols 551 -> 553 (+2)
                 sloc 43226 -> 43376 (+150)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  X10:           6 passed (fail-first: site-identity ok;
                 third assert: "no comparison exists")
  DETERMINISM:   145 passed
  R1:            2 passed in 16.99s (replayed)
  VERIFY_STEP:   CLEAN
  NOTES:         Budget table is a module-level tuple in
                 platform_config.py, not a PlatformConfig field, so
                 _BASELINE_CONFIG_HASH did not move. Statistic is p99
                 nearest-rank over a 100-event window per entry; an
                 incomplete window resolves NEVER_SEEN, not
                 within-budget. (iii) demonstrated at mean 20,980 under
                 a 50,000 budget with p99 1,000,000 over -- a
                 mean-based predicate would not have breached.
                 Conditions (a) and (b) both held: LatencyBreach
                 carries sequence=0, the handler never draws self._seq,
                 and the comparison is gated on mode is not BACKTEST so
                 baselines take the no-breach branch. S4's three G01
                 residuals are keyed by enclosing symbol
                 (_process_tick_inner, _finalize_tick,
                 _drain_async_fills), one call each, with a second
                 unmatched read in those functions still an offender;
                 the other seven remain line-pinned. S4 guard proof: a
                 throwaway read at :3979 produced a named failure;
                 restore verified byte-identical by SHA256
                 141A8D85D67780AE8B7F2E5117BCAC24CA5BC5F15F88AEBD55B7D0DB32A66552.
                 Unread-metric path supplemented, not removed.
                 importgraph reports cycles 0 with G40 still xfailing
                 -- these are different properties: G40 is an
                 independence contract over directional edges, not an
                 SCC. measure.py n_cycles stayed 1 -> 1 (NET DELTA);
                 that count is also not G40.
  FINDINGS:      Cycle-count explanation (stash check): importgraph SCC
                 count 0, measure.py n_cycles 1, G40 still xfailing.
                 These are three different properties. G40 is an
                 independence contract over directional edges, not an
                 SCC; a zero-cycle importgraph report does not close
                 G40. Also: verify_step classified this step
                 platform-wide by matching the substring inside
                 "Not platform-wide" -- negation-blind. Record against
                 exec-tools-v2. Do not fix in this step.
                 Carried: G.8 G01-G45 (G46 is S-10); G6 vs empty
                 depends_on_sensors; load_platform_config +
                 build_platform(config) loses config-path (S-04c);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercases step id and drops unfenced
                 blocks; __ prefix is a platform sentinel with two
                 instances and no central definition.
  NEXT:          S-08 durable submitted-order journal
                 (boundary -- live/paper). Not started.
                 Left uncommitted: baseline_pre-S-07.json,
                 baseline_post-S-07.json, this ledger entry.
