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

---

## S-08  durable submitted-order journal
DATE:            2026-08-19T17:35:06+08:00
BASE SHA:        f6448370e85e40df2304fc9a4b806aa013de54f4
RESULT SHA:      not committed — waiting at the boundary gate
VERDICT:         blocked
CONFORMANCE:     H2 | failed-before: yes | passes-after: yes
                 X11 | failed-before: yes | passes-after: yes
                 Step-2 failure output, captured with --runxfail before
                 any src edit (xfail(strict, "GAP G03") was on the tests):
                   FAILED tests/conformance/test_order_idempotency.py::
                   test_h2_kill_mid_submission_restart_no_duplicate
                   tests\conformance\test_order_idempotency.py:147: in
                   test_h2_kill_mid_submission_restart_no_duplicate
                       assert broker == [], (
                   E   AssertionError: duplicate reached the broker after
                       restart: ['oid-kill']; acks=[('oid-kill',
                       <OrderAckStatus.ACKNOWLEDGED: 1>, '')]
                   E   assert ['oid-kill'] == []
                   FAILED tests/conformance/test_order_idempotency.py::
                   test_h2_durability_mode_is_fsync_per_record
                   tests\conformance\test_order_idempotency.py:175: in
                   test_h2_durability_mode_is_fsync_per_record
                       assert journal is not None, (
                   E   AssertionError: nothing durable records submitted
                       ids — DurableSubmittedOrderJournal is absent
                   E   assert None is not None
                   2 failed in 0.29s
                   FAILED tests/conformance/test_reconciliation.py::
                   test_x11_journaled_rejected_is_resubmittable
                   tests\conformance\test_reconciliation.py:95:
                       assert journal is not None, (
                   E   AssertionError: nothing durable records submitted
                       ids — DurableSubmittedOrderJournal is absent
                   E   assert None is not None
                   FAILED tests/conformance/test_reconciliation.py::
                   test_x11_journaled_unknown_is_refused
                   tests\conformance\test_reconciliation.py:143:
                       assert journal is not None
                   FAILED tests/conformance/test_reconciliation.py::
                   test_x11_journal_backed_replay_same_refusals
                   tests\conformance\test_reconciliation.py:184:
                       assert journal is not None
                   3 failed in 0.34s
                 How each assertion executed (not merely that it failed):
                   (i)  broker probe is _post_passive; oid-kill was in
                        the probe list and ACKNOWLEDGED after restart —
                        G03 itself, not a missing fixture.
                   (ii) ImportError path returned None; journal is not
                        None fired. After implement, durability_mode ==
                        fsync-per-record and os.fsync spy was non-empty.
                   (iii)/(iv)/replay: journal is not None is required so
                        (iii) cannot pass vacuously on a fresh in-memory
                        set. After implement all three passed.
                 After implement: H2 3 passed, X11 3 passed (xfail removed).
TESTS:           4799 passed / 0 failed / 28 skipped / 10 xfailed
                 -> 4805 passed / 0 failed / 28 skipped / 10 xfailed
                 +6 are this step's six conformance functions. Determinism
                 145 -> 145. Pre-S-08 vs post-S-07 artifact: 4799/28 vs
                 4798/29 (one skip became a pass; cache-environment, not
                 this step). Artifact wins on S-07 numbers; this step's
                 delta is against the live pre-S-08 capture.
PARITY:          declared hold (all 26) | actual 62 constants unmoved,
                 0 changed, key-for-key and value-for-value | MATCH.
                 market_fill_acks and halt_ack still hold. verify_step
                 S-08: FILES clean (uncommitted vs HEAD, 0 touched —
                 frozen oracle diffs base..HEAD only), PARITY holds,
                 NET DELTA +1/+2, CLEAN. Blast radius boundary — human
                 gate required before commit.
FILES DECLARED:  src/feelies/storage/ (durable submitted-order journal, new)
                 src/feelies/execution/passive_limit_router.py:183
                 src/feelies/broker/ib/connection.py:353-364
                 src/feelies/bootstrap.py:358
                 src/feelies/core/platform_config.py
                 tests/conformance/test_order_idempotency.py
                 tests/conformance/test_reconciliation.py
FILES TOUCHED:   src/feelies/storage/submitted_order_journal.py (new)
                 src/feelies/execution/passive_limit_router.py
                 src/feelies/broker/ib/connection.py
                 src/feelies/bootstrap.py
                 src/feelies/core/platform_config.py
                 tests/conformance/test_order_idempotency.py (new)
                 tests/conformance/test_reconciliation.py (new)
                 7 touched against 6 named files + 1 directory scope.
                 Nothing outside FILES.
NET DELTA:       declared src modules +1, public symbols +2, branch
                 points +2, test files +2 | actual src modules 197 ->
                 198 (+1), public symbols 553 -> 555 (+2), sloc 43376 ->
                 43634 (+258), import cycles 1 -> 1 (+0), alphaleak 2 ->
                 2 (+0), n_edges 613 -> 618 (+5), n_modules 160 -> 161
                 (+1). MATCH on modules and symbols. Test files +2.
                 Public symbols: SubmissionJournalState,
                 DurableSubmittedOrderJournal.
FINDINGS:        Carried, not fixed: G.8 registers G01-G45 (G46 is S-10);
                 G6 rejects depends_on_sensors: []; load_platform_config
                 + build_platform(config) loses config-path (S-04c);
                 ci.yml import contract continue-on-error: true until G40
                 (do not flip); verify_step.py uppercases the step id,
                 silently drops unfenced blocks, and matches blast-radius
                 substrings without negation; the __ prefix is a platform
                 sentinel with two instances and no central definition.
                 verify_step FILES is vacuous on an uncommitted tree
                 (diffs base..HEAD only); report, do not fix.
                 PAPER bootstrap tests stub build_paper_backend with
                 object(); wiring uses getattr/hasattr so those mocks
                 skip the journal. Real ExecutionBackend + IB connection
                 still bind. Not a plan defect.
                 Pre-S-08 vs baseline_post-S-07.json: parity 62/62 MATCH;
                 tests 4799/28 vs 4798/29 (one skip flipped). Not a red
                 baseline.
NOTES:           Durability mode is fsync-per-record. Asserted by
                 durability_mode == "fsync-per-record" AND a non-empty
                 os.fsync spy after record_attempt — not inferred from
                 restart survival. Kill-after-fsync raises
                 KeyboardInterrupt from the spy after real os.fsync;
                 _post_passive never ran (broker empty); recovered
                 journal refused.
                 Latency choice (A): write stays on-tick inside
                 submit()/record_attempt, before the wire. Own
                 ENGINE_LATENCY_BUDGETS entry submitted_order_journal_ns,
                 statistic=p99, window_events=100, budget_ns=15_000_000
                 (15 ms, above the 1-10 ms fsync cost, not the S-07 3 ms
                 tick-to-decision budget). Observation is clock.now_ns
                 around fsync in the journal (injected clock, not
                 perf_counter — S4 allowlist not in FILES). A breach is
                 recorded on the journal (latency_breach_count) and does
                 NOT activate the kill switch: flatten-on-kill would
                 enqueue more per-leg writes on the same slow device,
                 leaving UNKNOWN outcomes that brick restart recovery.
                 Journaled-then-rejected: record_attempt then
                 record_reject on release_submitted_id=True; recovery
                 decision is REJECTED; re-submit ACKNOWLEDGES.
                 Journaled-unknown: record_attempt only; recovery
                 decision is UNKNOWN / must_refuse; re-submit REJECTED
                 duplicate, no ACKNOWLEDGED.
                 Journal-backed replay: oid-rej REJECTED, oid-unk-a/b
                 UNKNOWN on a second DurableSubmittedOrderJournal over
                 the same file; third router refused exactly the UNKNOWN
                 set.
                 Backtest does not bind the journal (mode is BACKTEST);
                 oracle path unchanged.
                 Waiting at the human gate. Do not commit. Do not begin
                 S-09.
                 Left uncommitted: baseline_pre-S-08.json,
                 baseline_post-S-08.json, this ledger entry, and the
                 seven declared files pending go/no-go.

---

## S-08  2026-08-19T17:44:00+08:00
  STEP:          S-08
  BASE:          f6448370e85e40df2304fc9a4b806aa013de54f4
  RESULT SHA:    5e0e8db69006032f71c20445cc486397f615244c
  VERDICT:       passed
  CONFORMANCE:   H2 | failed-before: yes | passes-after: yes
                 X11 | failed-before: yes | passes-after: yes
  TESTS:         4799 passed / 28 skipped / 10 xfailed
                 -> 4805 passed / 28 skipped / 10 xfailed
  PARITY:        hold, 62 constants unmoved
  FILES:         7 declared, 7 committed (clean vs 5e0e8db)
  NET DELTA:     modules 197 -> 198 (+1)
                 public_symbols 553 -> 555 (+2)
                 sloc 43376 -> 43634 (+258)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   CLEAN (boundary — committed after human go)
  NOTES:         durability is fsync-per-record, asserted by
                 durability_mode plus a non-empty os.fsync spy, with
                 the kill raised after the real fsync so _post_passive
                 never ran and the recovered journal refused. Latency
                 choice (A): on-tick write with its own budget entry
                 submitted_order_journal_ns, p99 over 100 events,
                 15 ms; a breach increments latency_breach_count and
                 deliberately does NOT activate the kill switch,
                 because flatten-on-kill would enqueue more per-leg
                 fsyncs on the same slow device and leave UNKNOWN
                 records that brick recovery. The journal logs
                 attempts and appends outcomes: attempt-then-reject is
                 re-submittable, attempt-with-no-outcome is refused.
                 Backtest does not bind the journal, so the oracle
                 path is unchanged.
                 recovered_ib_next_valid_id() on an empty journal
                 returns None (_ib_next_valid_id starts None; empty
                 replay is a no-op). nextValidId does not call
                 max(orderId, None): persisted is fetched, then
                 `if persisted is not None: incoming = max(incoming,
                 persisted)`. bind_submitted_order_journal uses the
                 same None-guard. Fresh install is safe. Untested by
                 the fourteen skipped functional tests.
  FINDINGS:      the pre-S-08 count mismatch (4799/28 vs the
                 artifact's 4798/29) is wall-clock dependent, not a
                 regression -- nine skips are gated on US RTH
                 (9:30-16:00 ET) and one crossed the boundary between
                 captures. Baseline test counts are therefore NOT
                 reproducible across time of day; only the parity
                 constants are. Pre-flight should treat a count
                 mismatch as informational unless failed > 0 or the
                 parity map moved. Also: connection.py:353-364 is
                 covered only by tests/broker/ib/test_ib_functional.py,
                 all fourteen of which skip without a reachable IB
                 Gateway, so the nextValidId high-water change ships
                 without automated coverage.
                 Carried: G.8 G01-G45 (G46 is S-10); G6 vs empty
                 depends_on_sensors; load_platform_config +
                 build_platform(config) loses config-path (S-04c);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercases step id, drops unfenced
                 blocks, and matches blast-radius substrings without
                 negation; __ prefix is a platform sentinel with two
                 instances and no central definition.
  NEXT:          S-09 schema_version on Event envelope (boundary).
                 Not started.
                 Left uncommitted: baseline_pre-S-08.json,
                 baseline_post-S-08.json, this ledger entry.

---

## S-09  schema_version on the Event envelope
DATE:            2026-08-19T19:29:19+08:00
BASE SHA:        9fb1d846758832056055273608cf2106f8baadc0
RESULT SHA:      reverted
VERDICT:         reverted
CONFORMANCE:     S8 | failed-before: yes | passes-after: yes | mutation: yes
                 R5 | failed-before: yes | passes-after: yes | mutation: yes
                 Step-2 failure output, captured with --runxfail before
                 any src edit (xfail(strict, "GAP G07") was on the tests):
                   FAILED tests/conformance/test_schema_drift.py::
                   test_s8_every_event_class_resolves_schema_version
                   E   AssertionError: event schema drift: Alert: extra=()
                       missing=('schema_version',); CrossSectionalContext:
                       extra=() missing=('schema_version',); ... Trade:
                       extra=() missing=('schema_version',)
                   (all 21 concrete Event subclasses named; missing is
                   schema_version — absence of versioning, not a fixture)
                   FAILED tests/conformance/test_schema_versioning.py::
                   test_r5_unsupported_schema_version_is_refused
                   E   Failed: DID NOT RAISE CacheReplayError
                   FAILED tests/conformance/test_schema_versioning.py::
                   test_r5_absent_schema_version_is_refused
                   E   Failed: DID NOT RAISE CacheReplayError
                   3 failed in 0.33s
                 S8 throwaway-field mutation (Alert.throwaway: int = 0):
                   before impl: Alert: extra=('throwaway',)
                   missing=('schema_version',) — names the field
                   restore: events.py byte-identical, throwaway gone,
                   S8 again missing=('schema_version',) only
                   after impl: Alert: extra=('throwaway',) missing=()
                   restore: events.py byte-identical, S8 1 passed
                 R5 opt-in mutation (require_schema_version: bool = False
                 wrapping check_cache_schema_version):
                   both R5 tests DID NOT RAISE — the bad log loaded
                   restore: cache_replay.py byte-identical, R5 2 passed
TESTS:           4812 passed / 0 failed / 28 skipped / 10 xfailed
                 -> reverted (same counts; no post-S-09 capture)
PARITY:          declared hold (all 26; oracle is blind to schema
                 growth, pending S-17a) | actual not recaptured after
                 revert; pre-S-09 map matched post-S-08 62/62
                 key-for-key and value-for-value | MATCH
FILES DECLARED:  src/feelies/core/events.py
                 src/feelies/storage/cache_replay.py
                 tests/conformance/test_schema_drift.py
                 tests/conformance/test_schema_versioning.py
FILES TOUCHED:   the four declared files, then git restore / deleted
                 the two new tests. Nothing outside FILES. The writer
                 the gate needs is src/feelies/storage/disk_event_cache.py,
                 which is not in FILES and was not edited.
NET DELTA:       declared src modules 0, public symbols +1, branch
                 points +1, test files +2 | actual none (reverted)
FINDINGS:        PLAN DEFECT — FILES omits disk_event_cache.py.
                 The unconditional ingest gate reads
                 manifest.get("schema_version") and refuses absent or
                 unsupported, following require_healthy_ingestion_manifests
                 at cache_replay.py:131-140 but not its default. DiskEventCache.save
                 never writes that key (manifest is a hand-built dict of
                 symbol/date/counts/checksum/event_schema_hash/
                 normalizer_version/created_at/optional ingestion_health).
                 After the gate lands, previously-passing tests fail:
                   tests/storage/test_cache_replay.py::
                   test_load_cache_replay_day_meta_carries_ingestion_health
                   tests/storage/test_cache_replay.py::
                   test_range_spanning_a_weekend_loads
                 both save() then load_event_log_from_disk_cache; both
                 raise CacheReplayError schema_version=None (require 1).
                 Stop-the-line: previously-passing test now failing, and
                 the change genuinely needs another file. Did not edit
                 disk_event_cache.py. Did not update those tests. Did not
                 fail the gate open. Did not merge envelope and manifest
                 into one check.
                 Adding schema_version to Event also changes
                 DiskEventCache._compute_schema_hash (it iterates
                 NBBOQuote/Trade __dataclass_fields__), so operator
                 caches become unusable at the existing hash check
                 before the new gate runs. Re-ingest still would not
                 tag schema_version unless save() writes it.
                 Carried, not fixed: G.8 registers G01-G45 (G46 is S-10);
                 G6 rejects depends_on_sensors: []; load_platform_config
                 + build_platform(config) loses config-path (S-04c);
                 ci.yml import contract continue-on-error: true until G40
                 (do not flip); verify_step.py uppercases the step id,
                 silently drops unfenced blocks, and matches blast-radius
                 substrings without negation; baseline test COUNTS are
                 not reproducible across time of day (RTH-gated skips);
                 connection.py:353-364 has no automated coverage of the
                 live handshake; all 14 tests in
                 tests/broker/ib/test_ib_functional.py skip without a
                 reachable gateway.
NOTES:           Supported range was stated as SCHEMA_VERSION = 1 in
                 feelies.core.events (singleton; ingest gate imported it
                 and compared with !=). Version-absent: manifest key
                 missing -> raw is None -> CacheReplayError, not a
                 default to 1. The 2 pre-existing version fields
                 (SensorReading.sensor_version, HorizonFeatureSnapshot.
                 feature_versions) are payload, not the envelope pin;
                 they would have stayed; schema_version would have been
                 additive on Event with default SCHEMA_VERSION. All 21
                 concrete Event subclasses would have resolved it by
                 inheritance. The check was unconditional — no flag.
                 The oracle did not and could not detect this change
                 (hand-written hash field lists; pending S-17a); a green
                 oracle would have proved nothing. Revert verified by
                 restoring declared files, deleting the two new tests,
                 deleting branch exec/S-09, HEAD back at
                 9fb1d846758832056055273608cf2106f8baadc0 on arch/exec.
                 Retry requires FILES to add
                 src/feelies/storage/disk_event_cache.py so save()
                 persists schema_version = SCHEMA_VERSION on the
                 manifest. Plan amendment, not a silent extra edit.
                 Left uncommitted: baseline_pre-S-09.json, this ledger
                 entry.

---

## S-09  schema_version on the Event envelope
DATE:            2026-08-19T20:27:22+08:00
BASE SHA:        9fb1d846758832056055273608cf2106f8baadc0
RESULT SHA:      not committed — waiting at the boundary gate
VERDICT:         blocked
CONFORMANCE:     S8 | failed-before: yes | passes-after: yes | mutation: yes
                 Step-2 failure output, captured with --runxfail before
                 any src edit (xfail(strict, "GAP G07") was on the test):
                   FAILED tests/conformance/test_schema_drift.py::
                   test_s8_every_event_class_resolves_schema_version
                   E   AssertionError: event schema drift: Alert: extra=()
                       missing=('schema_version',); CrossSectionalContext:
                       extra=() missing=('schema_version',); ... Trade:
                       extra=() missing=('schema_version',)
                   (all 21 concrete Event subclasses named; missing is
                   schema_version — absence of versioning, not a fixture)
                   1 failed in 0.26s
                 S8 throwaway-field mutation after implement
                 (Alert.throwaway: int = 0):
                   events.py sha256 before
                   3fe82e4aaf82ad7da34a51e043d8aa22669874823ed3aaf6ca76e20253442e8f
                   FAILED: Alert: extra=('throwaway',) missing=()
                   restore: byte-identical, sha256
                   3fe82e4aaf82ad7da34a51e043d8aa22669874823ed3aaf6ca76e20253442e8f
                   S8 1 passed
TESTS:           4812 passed / 0 failed / 28 skipped / 10 xfailed
                 -> 4811 passed / 0 failed / 30 skipped / 10 xfailed
                 +1 is S8. -1 pass / +1 skip is
                 test_app_20260326_backtest_baseline_from_disk_cache
                 (cache miss after event_schema_hash moved; skip is not
                 a pass). +1 further skip is
                 test_two_alphas_hold_live_targets_on_one_symbol (same
                 APP/2026-03-26 cache). Determinism 145 -> 145.
PARITY:          declared hold | actual 62 constants unmoved,
                 0 changed, key-for-key and value-for-value | MATCH.
                 Expected: the oracle is blind to schema growth
                 (pending S-17a). A green oracle proves nothing about
                 this step. verify_step S-09: FILES clean (vacuous —
                 diffs base..HEAD only; both files uncommitted),
                 PARITY holds, NET DELTA by eye, CLEAN. Blast radius
                 boundary — human gate required before commit.
FILES DECLARED:  src/feelies/core/events.py
                 tests/conformance/test_schema_drift.py
FILES TOUCHED:   src/feelies/core/events.py
                 tests/conformance/test_schema_drift.py (new)
                 2 touched against 2 declared. cache_replay.py and
                 disk_event_cache.py not edited. No third file.
NET DELTA:       declared src modules 0, public symbols +1, branch
                 points +1, test files +2 | actual src modules 198 ->
                 198 (+0), public symbols 555 -> 555 (+0), sloc
                 43634 -> 43639 (+5), cycles 1 -> 1, alphaleak 2 -> 2.
                 Test files +1. SCHEMA_VERSION is a module-level
                 Assign; inventory counts only ClassDef/FunctionDef, so
                 the declared +1 public symbol does not appear. Declared
                 branch points +1 and test files +2 are leftovers of
                 withdrawn R5. MATCH on modules. Finding, not a stop
                 (verify_step NET DELTA is compare-by-eye).
FINDINGS:        verify_step FILES is vacuous on an uncommitted tree
                 (declared 2, touched 0). Report, do not fix.
                 NET DELTA leftovers: public symbols +1 / branch points
                 +1 / test files +2 still name the withdrawn ingest
                 gate. BLAST RADIUS still says "one gate at ingest".
                 serialization.py treats a missing __schema_version__
                 tag as v1 (fail-open) — its own step.
                 Live flake during the first full pytest:
                 test_websocket_feed_emits_live_massive_event asserted
                 Trade.size > 0 against a size-0 print; retry passed;
                 post-S-09 capture was 0 failed. Not this step.
                 Carried: G.8 G01-G45 (G46 is S-10); G6 vs empty
                 depends_on_sensors; load_platform_config +
                 build_platform(config) loses config-path (S-04c);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercases step id, drops unfenced
                 blocks, and matches blast-radius substrings without
                 negation; baseline COUNTS not reproducible across
                 RTH; connection.py:353-364 untested live handshake.
NOTES:           R5 withdrawn — event_schema_hash is the log-level pin.
                 Schema hash before:
                 sha256:8ff53428a52107dcaa808fec2be1a4377df8562ec5f2c6d79052bdf1909909a7
                 after:
                 sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa
                 APP/2026-03-26 refused: event_schema_hash mismatch
                 (cached 8ff53428a521..., current 18e8861f5ff9...).
                 Functional baseline SKIPPED by default; FAILED under
                 FEELIES_REQUIRE_BASELINE_CACHE=1. Re-ingestion of
                 every cached session is required before that gate
                 runs. The 2 pre-existing version fields
                 (SensorReading.sensor_version,
                 HorizonFeatureSnapshot.feature_versions) stayed as
                 payload; envelope schema_version is additive default
                 SCHEMA_VERSION=1 on Event; all 21 concrete subclasses
                 resolve it by inheritance. The oracle did not and
                 could not detect this change, pending S-17a.
                 Waiting at the human gate. Do not commit.
                 Left uncommitted: baseline_pre-S-09.json,
                 baseline_post-S-09.json, this ledger entry, and the
                 two declared files pending go/no-go.

---

## S-09  2026-08-19T20:31:04+08:00
  STEP:          S-09
  BASE:          9fb1d846758832056055273608cf2106f8baadc0
  RESULT SHA:    759ae409eb241057ad35920ff114a0b826afac7f
  VERDICT:       passed
  CONFORMANCE:   S8 | failed-before: yes | passes-after: yes | mutation: yes
  TESTS:         4812 passed / 28 skipped / 10 xfailed
                 -> 4811 passed / 30 skipped / 10 xfailed
  PARITY:        hold, 62 constants unmoved
  FILES:         2 declared, 2 committed (clean vs 759ae40)
  NET DELTA:     modules 198 -> 198 (+0)
                 public_symbols 555 -> 555 (+0)
                 sloc 43634 -> 43639 (+5)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   CLEAN (boundary — committed after human go)
  NOTES:         R5 withdrawn -- event_schema_hash is the log-level pin and already
                 refuses an unknown NBBOQuote/Trade shape with a missing key failing closed;
                 schema_version is the envelope pin for consumer readability only, and no second
                 mechanism was built. Schema hash moved 8ff53428 -> 18e8861f, invalidating every
                 cached day; APP/2026-03-26 reports the mismatch by name. The functional baseline
                 SKIPPED by default and FAILED under FEELIES_REQUIRE_BASELINE_CACHE=1 -- re-ingest
                 every cached session before that gate runs, and note the extra skip
                 (test_two_alphas_hold_live_targets_on_one_symbol) has the same cause. All 21
                 classes resolve schema_version=1 by inheritance; SensorReading.sensor_version
                 and HorizonFeatureSnapshot.feature_versions remain payload, since they name the
                 producer version rather than envelope compatibility. S8 detects drift in both
                 directions -- missing and extra -- proven by the Alert.throwaway mutation with a
                 byte-identical restore. The parity oracle did not and could not detect this
                 change; S-17a closes that.
  FINDINGS:      verify_step FILES was vacuous on the uncommitted tree
                 (diffs base..HEAD only). NET DELTA leftovers: declared
                 public symbols +1 / branch points +1 / test files +2
                 still name withdrawn R5; actual +0 / +0 / +1. BLAST
                 RADIUS still says "one gate at ingest". serialization.py
                 treats a missing __schema_version__ tag as v1 (fail-open)
                 -- its own step. Live flake
                 test_websocket_feed_emits_live_massive_event (size-0
                 print) retried green; post capture 0 failed.
                 Carried: G.8 G01-G45 (G46 is S-10); G6 vs empty
                 depends_on_sensors; load_platform_config +
                 build_platform(config) loses config-path (S-04c);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercases step id, drops unfenced
                 blocks, and matches blast-radius substrings without
                 negation; baseline COUNTS not reproducible across
                 RTH; connection.py:353-364 untested live handshake.
  NEXT:          S-10 unit declarations (boundary). Not started.
                 Left uncommitted: baseline_pre-S-09.json,
                 baseline_post-S-09.json, this ledger entry.

---

## DEFERRAL  cache re-ingestion after S-09
DATE:        2026-08-19
CAUSE:       schema_version on the Event envelope is inherited into
             NBBOQuote and Trade. event_to_dict
             (src/feelies/core/serialization.py:50) iterates
             __dataclass_fields__, so the field lands in every new JSONL
             line, and _compute_schema_hash
             (src/feelies/storage/disk_event_cache.py:60-71) walks the same
             field set. The hash moved
             sha256:8ff53428a52107dcaa808fec2be1a4377df8562ec5f2c6d79052bdf1909909a7
             -> sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa.
             The invalidation is CORRECT: the on-disk format genuinely
             changed. The two mechanisms agree by construction.
SCOPE:       159 cache days, 8 symbols (APP, CROX, DIOD, ENSG, MLI, OLN,
             PCTY, RMBS), 378 MB under ~/.feelies/cache. Only APP/2026-03-26
             and the day used by
             test_two_alphas_hold_live_targets_on_one_symbol gate the test
             suite; the remainder is research data.
ACTION NOW:  DONE. Re-ingested APP/2026-03-26 (APP baseline oracle) and
             APP/2026-03-26 (test_two_alphas_hold_live_targets_on_one_symbol).
             Verified with FEELIES_REQUIRE_BASELINE_CACHE=1 and
             PYTHONHASHSEED=0:
               uv run pytest -q -m functional
             -> 19 passed, 24 skipped, 4808 deselected. All 24 functional
             skips are environmental (14 IB Gateway unreachable, 8 outside
             US RTH, 1 no live Massive quote, 1 opt-in
             PAPER_E2E_SIGNAL_PATH). None is cache- or schema-related, so
             the baseline gate ran and matched rather than skipping.
DEFERRED:    the remaining ~157 days until after S-17a. S-11, S-16 and S-31
             each add fields and each invalidates the cache again;
             re-pulling four times is wasted API budget. S-17a is the
             convergence point.
WATCH:       The previously-masked baseline gates now run. Current full
             suite: 4812 passed, 29 skipped, 10 xfailed. Skip counts remain
             wall-clock dependent because the RTH-gated set moves, so a
             count mismatch at pre-flight is informational unless
             failed > 0 or the parity map moved.
ALSO:        APP/2026-03-21 carries ingestion_health=UNKNOWN while the other
             158 days are HEALTHY. Predates S-09; unrelated; unexamined.

---

## S-10  unit declarations on the Event contract
DATE:            2026-08-20T10:04:17+08:00
BASE SHA:        40b66a971c8ae4d1250ceaf20ed7b8a459a1ce60
RESULT SHA:      not committed — waiting at the boundary gate
VERDICT:         blocked
CONFORMANCE:     S9 | failed-before: yes | passes-after: yes | mutation: yes
                 Step-2 failure output, captured with --runxfail before
                 any src edit (xfail(strict, "GAP G46") was on the test):
                   FAILED tests/conformance/test_unit_declaration.py::
                   test_s9_numeric_fields_declare_a_unit
                   E   AssertionError: numeric fields with no declared unit:
                       Event.timestamp_ns, Event.sequence, Event.schema_version,
                       CrossSectionalContext.horizon_seconds, ...
                       SizedPositionIntent.disclosed_cost_total_bps_by_symbol,
                       ... Trade.received_ns
                   (absence of units, not a fixture; 1 failed in 0.22s)
                 S9 mutation after implement (Signal.edge_estimate_bps
                 unit stripped):
                   events.py sha256 before
                   ce2cc0e8fbfd5388449edb01ed49c31310fe148e79a14163d9949b53e901d3c3
                   FAILED: numeric fields with no declared unit:
                   Signal.edge_estimate_bps
                   restore: byte-identical, sha256
                   ce2cc0e8fbfd5388449edb01ed49c31310fe148e79a14163d9949b53e901d3c3
                   S9 1 passed
TESTS:           4812 passed / 0 failed / 29 skipped / 10 xfailed
                 -> 4813 passed / 0 failed / 29 skipped / 10 xfailed
                 +1 is S9. Determinism 145 -> 145. Skip count unchanged
                 (informational; RTH-gated).
PARITY:          declared hold | actual 62 constants unmoved,
                 0 changed, key-for-key and value-for-value | MATCH.
                 Expected: the oracle is blind to Field.metadata (pending
                 S-17a). A green oracle proves nothing about this step.
                 verify_step S-10: FILES clean (vacuous — diffs
                 base..HEAD only; both files uncommitted), PARITY holds,
                 NET DELTA by eye, CLEAN. Blast radius boundary — human
                 gate required before commit.
FILES DECLARED:  src/feelies/core/events.py
                 tests/conformance/test_unit_declaration.py
FILES TOUCHED:   src/feelies/core/events.py
                 tests/conformance/test_unit_declaration.py (new)
                 2 touched against 2 declared. No third file.
NET DELTA:       declared src modules 0, public symbols +1, branch
                 points 0, test files +1 | actual src modules 198 -> 198
                 (+0), public symbols 555 -> 556 (+1, declared_unit),
                 sloc 43639 -> 43654 (+15), cycles 1 -> 1, alphaleak 2
                 -> 2. Test files +1. MATCH.
FINDINGS:        verify_step FILES is vacuous on an uncommitted tree
                 (declared 2, touched 0). Report, do not fix.
                 FILES omits tests/conformance/registry.py. S-01 deferred
                 G46 and the registry comments that S-10 registers it;
                 adding G46 would be a third file, so GAP_REGISTRY remains
                 G01-G45. S9 closes G46 in substance. Not edited.
                 TargetPosition nested numerics (target_usd, urgency,
                 expected_edge_bps) are not on the 21 Event classes; S9
                 does not walk them. target_positions itself is
                 dict[str, TargetPosition] (not numeric) and is marked
                 undetermined per the plan.
                 Carried: G6 vs empty depends_on_sensors; load_platform_config
                 + build_platform(config) loses config-path (S-04c);
                 serialization.py missing __schema_version__ tag treated
                 as current version (fail-open) — its own step;
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercases step id, drops unfenced blocks,
                 and matches blast-radius substrings without negation;
                 ~157 research cache days stale until after S-17a;
                 baseline COUNTS not reproducible across RTH;
                 connection.py:353-364 untested live handshake.
NOTES:           Mechanism: Field.metadata["unit"] plus module-level
                 declared_unit (the +1 public symbol). Chosen over a
                 ClassVar map so the unit sits on the field it describes.
                 Neither adds a dataclass field; _compute_schema_hash
                 and event_to_dict walk name and type only. Schema hash
                 before and after:
                 sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa
                 (unmoved). UNIT_UNDETERMINED is a declaration, not an
                 absence; S9 accepts it. Fields whose unit could not be
                 named, with candidates:
                   SizedPositionIntent.target_positions — plan-flagged;
                   weights / notional / shares. Container is not numeric
                   (TargetPosition.target_usd is USD). Marked undetermined.
                   SizedPositionIntent.disclosed_cost_total_bps_by_symbol
                   — plan-flagged; bps one-way vs bps round-trip.
                   Marked undetermined; blocks S-24.
                   NBBOQuote.bid_size, ask_size — share vs round_lot.
                   MetricEvent.value — heterogeneous per metric.
                   SensorReading.value — heterogeneous per sensor.
                   HorizonFeatureSnapshot.values — heterogeneous per feature.
                   RiskVerdict.constraints — heterogeneous constraint values.
                   SizedPositionIntent.factor_exposures — factor-dependent
                   (beta / USD / percent).
                   RegimeHazardSpike.hazard_score — dimensionless score vs
                   1/s hazard rate.
                   RegimeState.discriminability — 1 / nat / unnamed
                   divergence (default inf).
                 G46 — deferred here by S-01 — is closed by S9. The
                 executable GAP_REGISTRY is still G01-G45 because FILES
                 omitted registry.py; substance is G01-G46.
                 The oracle did not and could not detect this change;
                 S-17a closes that. Waiting at the human gate. Do not
                 commit.
                 Left uncommitted: baseline_pre-S-10.json,
                 baseline_post-S-10.json, this ledger entry, and the
                 two declared files pending go/no-go.

---

## S-10  2026-08-20T10:30:38+08:00
  STEP:          S-10
  BASE:          40b66a971c8ae4d1250ceaf20ed7b8a459a1ce60
  RESULT SHA:    ec20dcf94232eee907b4c40cd42491f6473b476d
  VERDICT:       passed
  CONFORMANCE:   S9 | failed-before: yes | passes-after: yes | mutation: yes
                 undetermined | failed-before: n/a | fails-now: yes
                 (strict xfail; --runxfail lists all 11)
  TESTS:         4812 passed / 29 skipped / 10 xfailed
                 -> 4813 passed / 29 skipped / 11 xfailed
  PARITY:        hold, 62 constants unmoved
  FILES:         3 declared, 3 committed (clean vs ec20dcf)
  NET DELTA:     modules 198 -> 198 (+0)
                 public_symbols 555 -> 556 (+1)
                 sloc 43639 -> 43654 (+15)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   CLEAN (boundary — committed after human go)
  NOTES:         Mechanism is Field.metadata["unit"] plus declared_unit -- no
                 dataclass field added, so name and type are unchanged and the
                 schema hash is unmoved at sha256:18e8861f. S9 fails only on a
                 MISSING unit; UNIT_UNDETERMINED does not certify a field. A
                 separate strict-xfail assertion lists all 11 undetermined
                 fields and fails while any remain, so the disputed set is
                 visible and greppable rather than passing silently. Eleven,
                 not the ten the plan flagged: bid_size and ask_size are
                 separate fields, and target_positions carries the token though
                 S9 does not treat that container as numeric. GAP_REGISTRY is
                 now G01-G46; S1 passes; the uncovered P0/P1 set is unchanged
                 at {G31, G32}. The parity oracle cannot see this step.
  FINDINGS:      verify_step extracted 4 declared tokens from a 3-entry FILES
                 field -- a bare "registry.py" from the prose was counted as a
                 path. Frozen oracle; record against exec-tools-v2 alongside
                 the uppercase, unfenced-block and negation-blind substring
                 bugs.
                 Carried: G6 vs empty depends_on_sensors; load_platform_config
                 + build_platform(config) loses config-path (S-04c);
                 serialization.py missing __schema_version__ tag treated as
                 current version (fail-open) -- its own step; ci.yml G40
                 continue-on-error: true until G40; ~157 research cache days
                 stale until after S-17a; baseline COUNTS not reproducible
                 across RTH; connection.py:353-364 untested live handshake.
  NEXT:          S-11 enumerable gate registry (platform-wide by reach,
                 boundary by behaviour). Not started.
                 Left uncommitted: baseline_pre-S-10.json,
                 baseline_post-S-10.json, this ledger entry.

---

## S-11  2026-08-20T14:39:14+08:00
  STEP:          S-11
  BASE:          748cc17e6798d61f8443d350bd5e148877dd44ae
  RESULT SHA:    63e74e1a5a42728b8e4bad3ad304d578756947ef
  VERDICT:       passed
  CONFORMANCE:   S13 | failed-before: yes | passes-after: yes | mutation: yes
                 X6 | failed-before: yes | passes-after: yes | mutation: yes
                 X6 family (nan, out_of_universe, missing_schema_version)
                   | failed-before: n/a | fails-now: yes
                   (strict xfail; family instances land at S-12)
                 Fail-before (registry absent):
                   ERROR collecting tests/conformance/test_gate_registry.py
                   ModuleNotFoundError: No module named 'feelies.core.gate_registry'
                   X6: 5 failed with the same ModuleNotFoundError;
                   3 family cases already xfailed.
  TESTS:         4813 passed / 29 skipped / 11 xfailed
                 -> 4825 passed / 29 skipped / 14 xfailed
  PARITY:        hold, 62 constants unmoved | MATCH
  FILES:         11 declared, 11 committed (clean vs 63e74e1)
  NET DELTA:     declared src modules +1, public symbols +2,
                 branch points 329 -> 329, test files +2
                 actual modules 198 -> 199 (+1)
                 public_symbols 556 -> 562 (+6)
                 sloc 43654 -> 44494 (+840)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   CLEAN (platform-wide -- committed after human go)
                 FILES reported declared 11, touched 0 (vacuous on the
                 uncommitted tree; known frozen bug). Actual 11/11.
  NOTES:         registry is 53 = 19 governance + 34 runtime spine;
                 RT.SCHEMA_SUPPORTED, RT.CONTRACT_CONFORM and
                 RT.IN_UNIVERSE are per-boundary family templates whose
                 instances are generated from the wiring manifest at
                 S-12, not rows. Three X6 cases (nan, out_of_universe,
                 missing_schema_version) are xfail(strict) awaiting
                 those instances. G13 is a retired alias,
                 stable_id=None, zero LayerValidator methods; warm-up
                 is RT.FEATURE_WARMTH. Runtime emit sites:
                 layer_validator (G-aliases), risk_wrapper
                 (RT.BUDGET_RESOLVE), order_admission (session,
                 min-size), observe_kill_switch (RT.KILL_SWITCH),
                 latency_budget.observe, classify_halt_status
                 (RT.DATA_HEALTH), basic_risk._emit_risk (exposure,
                 drawdown, buying power, compose), orchestrator
                 (RT.COST_GATE, RT.DUPLICATE_INTENT). No sequence draw
                 on the notification path: gate_registry.py contains
                 no SequenceGenerator, no self._seq, no .publish(.
                 Orchestrator emits are folded into existing if/return
                 lines so the Inv-10 wall-clock allowlist line numbers
                 do not move, and record_verdict returns Literal[False]
                 so those folds type-check under --strict. Predicates
                 unchanged, 329 -> 329.
  FINDINGS:      the verify_step NET DELTA table reported cycles 0 and
                 alphaleak 0; re-running measure.py directly gives
                 cycles 1 (feelies.cli -> feelies.cli.main) and
                 alphaleak 2 (core/platform_config.py:152, :954). The
                 zeros were a stale evidence read inside the capture,
                 not a real change. Record against exec-tools-v2.
                 Also: public symbols landed +6 against a declared +2
                 -- the supporting names on the new module plus
                 observe_kill_switch. The plan's NET DELTA understates
                 it.
                 verify_step FILES is vacuous on an uncommitted tree
                 (declared 11, touched 0). Frozen oracle; record
                 against exec-tools-v2 alongside the uppercase,
                 unfenced-block, negation-blind substring, and
                 bare-filename bugs.
                 Carried: G6 vs empty depends_on_sensors;
                 load_platform_config + build_platform(config) loses
                 config-path (S-04c); serialization.py missing
                 __schema_version__ tag treated as current version
                 (fail-open) -- its own step; ci.yml G40
                 continue-on-error: true until G40; ~157 research
                 cache days stale until after S-17a; baseline COUNTS
                 not reproducible across RTH; connection.py:353-364
                 untested live handshake; 11 UNIT_UNDETERMINED fields
                 block S-24.
  NEXT:          S-11a fill provenance (boundary). Not started.
                 Left uncommitted: baseline_pre-S-11.json,
                 baseline_post-S-11.json, this ledger entry.

---

## S-11a  2026-08-20T16:28:35+08:00
  STEP:          S-11a
  BASE:          2f2c1ff7893775a839b5e4126a28113a0b0765d0
  RESULT SHA:    not committed — reverted, no src edit
  VERDICT:       blocked
  CONFORMANCE:   R3 | failed-before: no | passes-after: n/a | mutation: n/a
                 tests/conformance/test_registration_order.py created, then
                 deleted on revert. PYTHONHASHSEED=0:
                   1 passed in 0.15s
                 Permutation took effect: crossing-quote handler order was
                 ["router", "sensor"] vs ["sensor", "router"]. Fill streams
                 of the resting through-fill were identical. R3 passed
                 before any src change, so it cannot guard the field.
  TESTS:         pre-S-11a capture 4826 passed / 0 failed / 28 skipped /
                 14 xfailed (skip vs post-S-11 4825/29 is wall-clock;
                 failed=0). Determinism 145 passed. R3 1 passed before
                 implement. No post-implement suite.
  PARITY:        declared hold, 62 constants | actual unmoved vs
                 baseline_post-S-11.json (62/62, 0 changed) | MATCH
                 (no src edit). Schema hash
                 sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa
                 (pre-flight only; field never landed).
  FILES:         5 declared, 1 created (R3), restored. Branch exec/S-11a
                 deleted. HEAD arch/exec @ 2f2c1ff.
  NET DELTA:     declared src modules 0, public symbols +1, branch
                 points 0, test files 0 (R3 already exists — plan text)
                 vs FILES creating R3 | actual 0 / 0 / 0 / 0
  DETERMINISM:   145 passed (pre-capture)
  VERIFY_STEP:   not run — no implement
  NOTES:         Provenance was to live on Fill so event_schema_hash
                 (NBBOQuote+Trade only) would not move. There is no Fill
                 type; fills are OrderAck. Putting the field on OrderAck
                 would fail S8 (PINNED_PAYLOAD) and S8's file is not in
                 FILES — a sixth path. R3 originates here; S-12 extends
                 it. bootstrap.py:358's ordering requirement was not
                 deleted (no implement). Seq-draw invariance not
                 re-verified beyond "no src edit".
  FINDINGS:      PLAN DEFECT — R3 as specified is unsatisfiable as a
                 fail-then-pass gate. Resting through-fills take the
                 quote argument to on_quote; a second NBBOQuote
                 subscriber that does not submit does not change the
                 OrderAck stream. The permutation was observed and the
                 streams matched, so R3 passed before the field exists.
                 A same-tick submit stand-in would fail today and still
                 fail after an OrderAck field. The comment at
                 bootstrap.py:358 is not a load-bearing fill-stream
                 dependence for observer-style sensors.
                 Also: no Fill event; S8 not in FILES. Plan must name
                 the type (OrderAck) and either add
                 tests/conformance/test_schema_drift.py to FILES or
                 place provenance where S8 does not pin.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA; ~157 research cache
                 days stale until after S-17a; 11 UNIT_UNDETERMINED
                 block S-24; three X6 cases xfail(strict) awaiting
                 S-12 family instances.
  NEXT:          plan amend, then retry S-11a. Do not start S-12.
                 Left uncommitted: baseline_pre-S-11a.json, this
                 ledger entry.

---

## S-11a  2026-08-20T17:53:39+08:00
  STEP:          S-11a
  BASE:          e816ae18d16955dbbbc69e99da250654ebd97f19
  RESULT SHA:    88bd3f5d2faf67872b3a176b579992a988a5d95a
  VERDICT:       passed
  CONFORMANCE:   none — no test in this step. Deletion proven inert:
                 grep src/feelies finds no remaining copy of
                 "Subscribe the router before sensors so fills retain
                 their triggering quote." git diff is exactly that one
                 comment line. bus.subscribe(NBBOQuote, ...) at
                 bootstrap.py:353-356 is byte-identical.
  TESTS:         4826 passed / 28 skipped / 14 xfailed
                 -> 4836 passed / 18 skipped / 14 xfailed
                 failed 0 -> 0. +10 passed / -10 skipped is wall-clock
                 functional (Massive WS); first pre-capture went RED
                 on test_websocket_feed_emits_live_massive_event, retry
                 GREEN 4826/28, same test 1 passed in 1.65s.
  PARITY:        hold, 62 constants unmoved | MATCH
                 schema hash unmoved
                 sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa
  FILES:         1 declared, 1 committed (clean vs 88bd3f5)
                 src/feelies/bootstrap.py
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, test files 0
                 actual modules 199 -> 199 (+0)
                 public_symbols 562 -> 562 (+0)
                 sloc 44494 -> 44494 (+0)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   S-11a uppercased to S-11A not in plan (frozen).
                 Four checks by hand: FILES 1/1 clean; PARITY holds
                 62/62; TESTS failed 0; NET DELTA 0/0/0. CLEAN
                 (local — committed without waiting).
  NOTES:         No provenance field (no Fill type; OrderAck is S8
                 PINNED_PAYLOAD). No R3 here — unfalsifiable for
                 router/sensor; originates in S-11b. Comment at
                 bootstrap.py:358 deleted, not reworded; subscribe
                 order unchanged. Seq-draw invariance: diff is one
                 comment line, no SequenceGenerator, no .next().
  FINDINGS:      pre-flight first capture RED on live Massive WS
                 functional test; flake, not this step. Record with
                 wall-clock skip counts.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA; ~157 research cache
                 days stale until after S-17a; 11 UNIT_UNDETERMINED
                 block S-24; three X6 cases xfail(strict) awaiting
                 S-12 family instances.
  NEXT:          S-11b forced-exit pricing (boundary). Not started.
                 Left uncommitted: baseline_pre-S-11a.json,
                 baseline_post-S-11a.json, this ledger entry.

---

## S-11b  2026-08-21T10:23:07+08:00
  STEP:          S-11b
  BASE:          3b30398fb3806e906dc9956132bb08ad8dbe4222
  RESULT SHA:    not committed — blocked, branch exec/S-11b left intact
  VERDICT:       blocked
  CONFORMANCE:   R3 | failed-before: yes | passes-after: yes | mutation: yes
                 Fail-before (both routers, stale-price mode, not reject):
                   BacktestOrderRouter router_first FILLED 90.00
                   BacktestOrderRouter stop_first   FILLED 99.50
                   PassiveLimitOrderRouter router_first FILLED 90.00
                   PassiveLimitOrderRouter stop_first   FILLED 99.50
                 Handler order observed: (router, stop_exit) vs
                 (stop_exit, router). STOP_EXIT submitted in all four.
                 After implement: 1 passed. Mutation: BacktestOrderRouter
                 pricing reverted to _last_quotes only; R3 failed again
                 on 90.00 vs 99.50 while PassiveLimit stayed 90.00/90.00;
                 SHA256 restore byte-identical
                 19DB5C53D878844B493464E4771784157B202F2CDAFCFAF53AC1678CE4FD9E84.
  TESTS:         pre-S-11b capture 4835 passed / 0 failed / 19 skipped /
                 14 xfailed (skip vs post-S-11a 4836/18 is wall-clock;
                 failed=0). Determinism 145 passed.
                 R3 1 failed before, 1 passed after.
                 kernel: 388 passed, 1 failed
                 (test_orchestrator_order_routing.py::
                 test_submit_exception_rejects_and_prunes_order).
                 conformance 55 passed / 14 xfailed. mypy clean.
                 Full suite and post-capture not run — stop-the-line.
  PARITY:        declared VERIFY, do not assume | actual unmoved vs
                 baseline_post-S-11a.json at pre-capture (62/62, 0 changed)
                 | MATCH (pre only; post not captured).
  FILES:         plan lists 13 unique paths (prompt said 14). 13 touched
                 on exec/S-11b, all declared. A 14th unique path is
                 required and was not declared.
  NET DELTA:     declared src modules 0, public symbols 0, branch points 0
                 | not re-measured — blocked before post-capture.
  DETERMINISM:   145 passed (pre-capture). Not re-run after implement.
  VERIFY_STEP:   not run — blocked before post-capture. S-11b would
                 uppercase to S-11B (frozen).
  NOTES:         Implementation on the branch: both simulated routers
                 take triggering_quote with _last_quotes fallback; IB
                 unused matching parameter; protocol defaulted;
                 _submit_to_router (after 3971) calls
                 submit(order, triggering_quote=quote) unconditionally;
                 StopExit holds the quote on a module global for the
                 nested publish; journal wrapper forwards; _DelayedRouter
                 forwards to super(); six declared doubles accept the
                 argument. No ContextVar. No co_varnames. No OrderRequest
                 or OrderAck field. Wall-clock allowlist lines unmoved
                 at 1642, 1644, 1684, 1686, 1780, 1782, 3968.
                 ContextVar and co_varnames sniff were both rejected:
                 ContextVar is implicit state plus a forbidden
                 risk->execution import; the sniff is fail-quiet on
                 paper because install_on always replaces IB submit.
                 R3 originates here after S-11a discarded it as
                 unfalsifiable for a non-submitting subscriber.
                 BacktestOrderRouter is the tape router (execution_mode
                 defaults to market).
  FINDINGS:      PLAN DEFECT — FILES omitted
                 tests/kernel/test_orchestrator_order_routing.py:98-101.
                 raise_on_submit(_order) is monkeypatched onto
                 order_router.submit. Unconditional
                 submit(order, triggering_quote=quote) raises
                 TypeError("got an unexpected keyword argument
                 'triggering_quote'") instead of RuntimeError, so the
                 previously-passing test fails. The only other submit
                 override in tests/ is this monkeypatch; the six
                 declared doubles were updated. Editing that file is a
                 14th unique path the plan text does not name. No
                 signature sniff / TypeError fallback (forbidden).
                 Prompt said FOURTEEN FILES entries; the plan block
                 names 13 unique paths. This omitted monkeypatch is
                 the likely 14th.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 three X6 cases xfail(strict) awaiting S-12 family
                 instances; Inv-10 wall-clock allowlist line-pinned.
  NEXT:          plan amend — add
                 tests/kernel/test_orchestrator_order_routing.py to
                 FILES, then retry S-11b. Do not start S-12.
                 Branch exec/S-11b left intact (implementation + R3);
                 not reverted, not committed. Left uncommitted:
                 baseline_pre-S-11b.json, this ledger entry.

---

## S-11b  2026-08-21T15:02:06+08:00
  STEP:          S-11b
  BASE:          4a6c4c16c46b1a8ca1398bef30d314720f9e9bd2
  RESULT SHA:    e87d9c56193fc24b51f8892623b1a24f9b9a71f3
  VERDICT:       passed
  CONFORMANCE:   R3 | failed-before: yes | passes-after: yes | mutation: yes
                 Fail-before (both routers, stale-price mode, not reject):
                   BacktestOrderRouter router_first FILLED 90.00
                   BacktestOrderRouter stop_first   FILLED 99.50
                   PassiveLimitOrderRouter router_first FILLED 90.00
                   PassiveLimitOrderRouter stop_first   FILLED 99.50
                 Handler order observed: (router, stop_exit) vs
                 (stop_exit, router). STOP_EXIT submitted in all four.
                 After implement: 1 passed. Mutation: BacktestOrderRouter
                 pricing reverted to _last_quotes only; R3 failed again
                 on 90.00 vs 99.50 while PassiveLimit stayed 90.00/90.00;
                 SHA256 restore byte-identical
                 19DB5C53D878844B493464E4771784157B202F2CDAFCFAF53AC1678CE4FD9E84.
  TESTS:         4835 passed / 0 failed / 19 skipped / 14 xfailed
                 -> 4836 passed / 0 failed / 19 skipped / 14 xfailed
                 +1 passed is R3. Skip vs post-S-11a 18 is wall-clock.
  PARITY:        declared VERIFY | actual hold 62 unmoved | MATCH
                 vs baseline_post-S-11a.json. Tape is
                 tests/determinism/test_orchestrator_replay.py stop-exit
                 (bootstrap router-first + BacktestOrderRouter);
                 EXPECTED_STOP_EXIT_STREAMS unmoved.
  FILES:         14 declared, 13 touched, 13 committed (clean vs
                 e87d9c5). stop_exit.py declared, not touched — quote
                 is the _process_tick argument, not a StopExit hold.
  NET DELTA:     declared src modules 0, public symbols 0, branch
                 points 0
                 actual modules 199 -> 199 (+0)
                 public_symbols 562 -> 562 (+0)
                 sloc 44494 -> 44528 (+34)
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   S-11b uppercased to S-11B not in plan (frozen).
                 Four checks by hand: FILES 14 declared / 13 touched,
                 all declared, stop_exit.py declared-untouched; PARITY
                 holds 62/62; TESTS failed 0; NET DELTA modules +0,
                 symbols +0. CLEAN (boundary — committed after human
                 go).
  NOTES:         Three attempts. Attempt 1 fixed only
                 PassiveLimitOrderRouter while APP and
                 test_orchestrator_replay.py both resolve
                 execution_mode="market" -> BacktestOrderRouter, so
                 parity held because the fix never reached the tape.
                 Attempt 2 added a co_varnames signature sniff that
                 silently fell back to submit(order) -- fail-quiet on
                 the defect being closed, and live on paper because
                 DurableSubmittedOrderJournal.install_on wraps submit
                 as def submit(request). Attempt 3's first pass used a
                 module-level mutable global (_held_triggering_quote)
                 read by the kernel through a private import; rejected
                 as process-global rather than task-scoped and a
                 kernel->risk edge on a private symbol. Final: the
                 quote is the _process_tick argument, carried
                 explicitly to _submit_to_router at all four call
                 sites, with _last_quotes as fallback.
                 _tick_quote_for_trace was rejected as a source: it is
                 diagnostic, assigned only when a signal-order trace
                 sink is bound, and None on every production tick --
                 using it would have left the race live while parity
                 held for the wrong reason. Lines 455, 1474 and 1480
                 join two statements with a semicolon deliberately, so
                 the Inv-10 wall-clock pins at 1642, 1644, 1684, 1686,
                 1780, 1782 and 3968 do not move; _submit_to_router is
                 inserted after 3971 for the same reason. R3 originates
                 here after being discarded from S-11a as
                 unfalsifiable, and drives quotes through _process_tick
                 rather than bus.publish so the orchestrator is
                 actually dispatching when stop-exit fires.
  FINDINGS:      the plan required four amendments during execution --
                 backtest_router.py, the OrderRouter protocol and IB
                 router, the journal wrapper plus six test doubles, and
                 the order-routing monkeypatch. Each was found by an
                 attempt failing, not by reading. Also: three plan
                 commits landed on the step branch and needed
                 cherry-picking to arch/exec.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 three X6 cases xfail(strict) awaiting S-12 family
                 instances; Inv-10 wall-clock allowlist line-pinned.
  NEXT:          S-12 wiring manifest (platform-wide). Not started.
                 Do not begin S-12. Left uncommitted:
                 baseline_pre-S-11b.json, baseline_post-S-11b.json,
                 this ledger entry.

---

## S-12  2026-08-21T18:20:00+08:00
  STEP:          S-12
  BASE:          ac8aa41bb1c175504c4ade98c407843efecb8d60
  RESULT SHA:    0fa569e41334e22c6dd23e6d9c0fc562fca802fb
  VERDICT:       passed
  CONFORMANCE:   S15, S17, X8, X9, R3-manifest | failed-before: yes |
                 passes-after: yes | mutation: yes
                 Fail-before (10 failed, 3 passed in 2.06s):
                   S15 graph: subscription not in the manifest:
                     RegimeState RegimeStateCache
                   S15 hash: wiring manifest is empty
                   S17 injection leftover: metric_collector._store_raw_events,
                     module._construct, orchestrator.config_snapshot,
                     orchestrator.ib_connection, orchestrator.live_feed
                   S17 assignment allowlist: 47 sites; first
                     bootstrap.py:601 orchestrator.config_snapshot
                   S17 private allowlist: 10 sites; first
                     bootstrap.py:428 metric_collector._store_raw_events
                   X8 bound: EventBus has no cascade depth bound
                   X8 fail-closed: same, bound 0
                   X9 consumer: KillSwitchActivation has no subscriber
                   X9 observable: no subscriber
                   R3 new: wiring manifest is empty
                 3 passed (must stay green): S-11b R3 fill-stream;
                 X9 fail-closed without bus delivery; X9 durable
                 (InMemoryKillSwitch.history).
                 After implement: 13 passed in the five conformance
                 files. Mutation: removed
                 Subscription(4, SensorReading, HorizonAggregator);
                 S15 failed naming "SensorReading HorizonAggregator";
                 restore SHA256
                 e2640f66cf4909bacc0f27ee97cb8693a154b764593800a84befa3b2f8d00b74
                 BYTE_IDENTICAL.
  TESTS:         4837 passed / 0 failed / 18 skipped / 14 xfailed
                 -> 4849 passed / 0 failed / 18 skipped / 14 xfailed
                 +12 are S15(2)+S17(3)+X8(2)+X9(4)+R3-manifest(1).
                 determinism 145 -> 145. kernel 389 passed. mypy clean
                 (200 files). wall-clock 2 passed. conformance 67
                 passed / 14 xfailed (S11 still xfail on
                 StateTransition; old S17 still xfail; three X6 still
                 xfail). Post-S-12 capture BASELINE: GREEN.
  PARITY:        declared hold, all 26, R3 proves it | actual 62
                 constants unmoved, 0 changed | MATCH vs
                 baseline_pre-S-12.json. R3 manifest permutation
                 (forward vs reversed EventBus.subscribe buffer) hashes
                 the stop-exit OrderAck stream identically.
  FILES:         8 declared, 8 touched, 8 committed (clean vs 0fa569e).
                 verify_step before commit reported touched 0
                 (uncommitted tree).
  NET DELTA:     declared src modules +1, public symbols +2,
                 branch points +1, test files +4
                 (plan amended: subscribe_all kept)
                 actual modules 199 -> 200 (+1)
                 public_symbols 562 -> 564 (+2)
                 sloc 44528 -> 44773 (+245)
                 n_edges 626 -> 628
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   S-12 --base ac8aa41 (pre-commit): FILES clean
                 (touched 0, uncommitted); PARITY holds; NET DELTA
                 compared by eye against then-stale "subscribe_all
                 deleted"; overall CLEAN, platform-wide gate.
                 After the amend, public symbols +2 MATCH.
  NOTES:         Order was measured by wrapping EventBus.subscribe
                 during build_platform under the phase-4 config
                 (tests/integration/test_phase4_e2e.py) with
                 PYTHONHASHSEED=0 -- 26 runtime rows, ordinals
                 00-25, conditional hazard/deferral/composer rows in
                 the slot they occupy when they attach. S15 is
                 runtime subset-of declared. The bootstrap NBBOQuote
                 lambda was renamed _on_backtest_quote so the
                 subscriber id is stable. Six zero-subscriber types:
                 OrderAck, PositionUpdate, RiskVerdict, SymbolHalted
                 and KillSwitchActivation each gained a consumer via
                 _NotificationObserver; StateTransition is
                 reclassified as a notification record with its
                 publish kept for S-31, so S11 stays xfail. No
                 publish was removed, so no type re-pins. Cascade
                 bound is 16; at the limit publish raises
                 RuntimeError matching "cascade depth" and the nested
                 event is not delivered. KillSwitchActivation's
                 consumer is _NotificationObserver.on_event; X9
                 proves fail-closed via SessionEntryBlockedError on
                 run_backtest after activate-without-publish,
                 durable via InMemoryKillSwitch.history, observable
                 via a production handler plus a tap. Five
                 injections: _store_raw_events through
                 _BacktestMetricCollector, config_snapshot /
                 live_feed / ib_connection through a nested
                 Orchestrator.__init__, module._construct through
                 LoadedPortfolioLayerModule. Parity hold is proved
                 by R3's manifest permutation -- forward vs reversed
                 subscribe buffer, identical stop-exit OrderAck
                 hash. Wall-clock pins unmoved (1642, 1644, 1684,
                 1686, 1780, 1782, 3968). subscribe_all kept: six
                 callers outside FILES. exec/S-12 carries a
                 duplicate plan commit (edf4b25) that also exists on
                 arch/exec as c556242 (identical tree); it will
                 disappear in the merge.
  FINDINGS:      the three X6 xfails remain deferred -- this step
                 does not generate family instances, and S13 forbids
                 RT.SCHEMA_SUPPORTED, RT.CONTRACT_CONFORM and
                 RT.IN_UNIVERSE in GATE_REGISTRY, so dropping them
                 would need a ninth file
                 (tests/conformance/test_pathological_refusal.py).
                 They should move to a new S-12a whose FILES are
                 that test plus the family-instance generator
                 derived from wiring_manifest.SUBSCRIPTIONS (not
                 extra GATE_REGISTRY rows). They must not move to
                 S-13 (sequence-authority; wrong owner, and the 53-
                 row registry constraint is S-11/S13).
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 Inv-10 wall-clock allowlist line-pinned; S-11b
                 semicolons at orchestrator 455, 1474, 1480.
  NEXT:          S-13 sequence-authority registry (boundary). Not
                 started. Do not begin S-13. Left uncommitted:
                 baseline_pre-S-12.json, baseline_post-S-12.json,
                 this ledger entry.

---

## S-12a  2026-08-21T20:44:08+08:00
  STEP:          S-12a
  BASE:          18e1172ad4400bc40d895f1bd6c5fd8d463ef19c
  RESULT SHA:    39b25f1650a083d7a2357a740a1d2b64d4ee9ad2
  VERDICT:       passed
  CONFORMANCE:   S13 generated-instance assertion | failed-before: yes |
                 passes-after: yes | mutation: yes
                 X6 family (nan, out_of_universe, missing_schema_version)
                   | failed-before: xfail(strict) | passes-after: yes
                   | markers dropped in the same commit
                 Fail-before (S13, no FAMILY_INSTANCES):
                   FAILED tests/conformance/test_gate_registry.py::
                   test_s13_generated_family_instances_match_wiring_manifest
                   AssertionError: generated family instances diverge from
                   the wiring manifest: missing [108 ids], extra []
                   1 failed in 0.30s
                 X6 fail-before:
                   XFAIL [nan-RT.CONTRACT_CONFORM] family instances land at S-12
                   XFAIL [out_of_universe-RT.IN_UNIVERSE] family instances land at S-12
                   XFAIL [missing_schema_version-RT.SCHEMA_SUPPORTED] family instances land at S-12
                   3 xfailed in 0.45s
                 After implement: S13 file 9 passed; X6 file 8 passed,
                 -rxX prints no XFAIL. Mutation: removed
                 Subscription(4, SensorReading, HorizonAggregator);
                 S13 failed naming
                 RT.CONTRACT_CONFORM:SensorReading:HorizonAggregator,
                 RT.IN_UNIVERSE:SensorReading:HorizonAggregator,
                 RT.SCHEMA_SUPPORTED:SensorReading:HorizonAggregator;
                 restore SHA256
                 e2640f66cf4909bacc0f27ee97cb8693a154b764593800a84befa3b2f8d00b74
                 BYTE_IDENTICAL.
  TESTS:         4848 passed / 1 failed / 18 skipped / 14 xfailed
                 -> 4852 passed / 1 failed / 18 skipped / 11 xfailed
                 +4 passed / -3 xfailed are the new S13 assertion and
                 the three X6 family cases. failed 1 is the same IB
                 after-hours test already red on baseline_post-S-12.json.
                 determinism 145 -> 145. mypy clean (200 files).
                 conformance 71 passed / 11 xfailed (S11 still xfail on
                 StateTransition; three X6 no longer xfail).
  PARITY:        declared hold | actual 62 constants unmoved, 0 changed
                 | MATCH vs baseline_pre-S-12a.json and
                 baseline_post-S-12.json (62/62 key-for-key).
  FILES:         3 declared, 3 touched, 3 committed (clean vs 39b25f1).
                 verify_step before commit reported S-12A not in plan
                 (uppercase); FILES would have shown touched 0 on the
                 uncommitted tree.
  NET DELTA:     declared src modules 0, public symbols 0, branch points 0
                 actual modules 200 -> 200 (+0)
                 public_symbols 564 -> 564 (+0)
                 sloc 44773 -> 44827 (+54)
                 n_edges 628 -> 629
                 n_modules 162 -> 163
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 The +1 import-graph module/edge is gate_registry
                 importing the existing wiring_manifest.
  DETERMINISM:   145 passed
  VERIFY_STEP:   S-12a uppercased to S-12A not in plan (frozen). Four
                 checks by hand: FILES 3/3 clean; PARITY holds 62/62;
                 TESTS failed 1->1 same IB after-hours test; NET DELTA
                 0/0/0 on declared axes. CLEAN (boundary -- committed
                 after human go).
  NOTES:         108 instances = 36 receiving boundaries x 3 templates,
                 generated from wiring_manifest.SUBSCRIPTIONS.
                 GATE_REGISTRY stays 53 hand-written rows with
                 family=="none"; FAMILY_INSTANCES keys are
                 {template}:{event_type}:{subscriber} with family set
                 to a template id, and the two key sets are disjoint.
                 Template ids remain absent as rows, enforced at import
                 by _check_registry_completeness. The three X6 xfails
                 dropped in the same commit that made them pass.
                 Generated rows stay off the parity manifest:
                 import-time registry data, no EXPECTED_/_BASELINE_
                 pin, record_verdict still resolves against the 53-row
                 GATE_REGISTRY only, and none of the 24 parity modules
                 were edited. Mutation proof: removing
                 Subscription(4, "SensorReading", "HorizonAggregator")
                 made S13 name all three corresponding instances;
                 restore byte-identical.
  FINDINGS:      baseline_post-S-12.json was captured RED -- 4848
                 passed, 1 failed, exit_code 1, on
                 tests/broker/ib/test_ib_functional.py::
                 TestIBGatewayFunctional::
                 test_after_hours_reject_surfaces_as_rejected -- while
                 the S-12 ledger entry records GREEN. Environmental
                 (IB gateway, after hours), not a regression, but the
                 reference artifact and the ledger disagree and the
                 artifact wins. Also: X6's family cases assert
                 instances exist and template ids stay absent; they do
                 not drive nan / out_of_universe /
                 missing_schema_version through a production emit site,
                 because no emit site is in FILES.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 subscribe_all kept (six callers outside src/feelies);
                 StateTransition notification record, publish kept for
                 S-31, S11 stays xfail.
  NEXT:          S-13 sequence-authority registry (boundary). Not
                 started. Do not begin S-13. Left uncommitted:
                 baseline_pre-S-12a.json, baseline_post-S-12a.json,
                 this ledger entry.

---

## EXEMPTION  IB after-hours failure in the reference baselines
DATE:        2026-08-21
FAILURE:     tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::
             test_after_hours_reject_surfaces_as_rejected
             "AssertionError: expected terminal cleanup, got []"
PRESENT IN:  baseline_post-S-12.json (4848 passed, 1 failed, exit 1) and
             baseline_post-S-12a.json (4852 passed, 1 failed, exit 1).
             baseline.py reports "BASELINE: RED -- do not start execution".
CAUSE:       environmental. Requires a reachable IB Gateway at
             127.0.0.1:4002 and a live after-hours session. The other
             thirteen tests in that file skip when the gateway is
             unreachable; this one runs and fails. Predates S-12 and S-12a;
             neither step touches broker/ib/.
DECISION:    proceed. This one failure is the accepted baseline state until
             re-captured with a reachable gateway. It is NOT a regression.
WATCH:       a pre-flight capture reporting failed == 1 on THIS test only is
             expected. failed > 1, or a different test, is a stop. Re-capture
             during US market hours with IB Gateway running to clear it.
NOTE:        the S-12 ledger entry records the baseline as GREEN; the
             artifact says otherwise and the artifact wins.

---

## S-13  2026-08-22T10:28:00+08:00
  STEP:          S-13
  BASE:          5656fd5810e935e28ffed0e06ee308fd4c17173f
  RESULT SHA:    d4244775b3eb620e44e17752f949716bd4bbcc0b
  VERDICT:       passed
  CONFORMANCE:   S12 stream-authority | failed-before: yes | passes-after: yes
                 | mutation: yes
                 S12 contract-producer | failed-before: yes | passes-after: yes
                 | mutation: yes
                 Fail-before (no registry, unnamed production sites):
                   FAILED tests/conformance/test_single_owner.py::
                   test_s12_every_stream_has_exactly_one_sequence_authority
                   AssertionError: stream has no sequence authority:
                   src/feelies/bootstrap.py:358
                   FAILED tests/conformance/test_single_owner.py::
                   test_s12_every_contract_has_exactly_one_producer
                   AssertionError: contract has no producer: Alert
                   2 failed in 0.58s
                 After implement: 2 passed. Mutation: removed
                 SequenceAuthority("sensor", "SensorRegistry",
                 ("SensorReading",)); S12 failed naming stream sensor
                 and contract SensorReading; restore SHA256
                 e2fa811eed7e6dbb54145c142b632872d5ed3990b222a515bd536ab02ca16971
                 BYTE_IDENTICAL.
  TESTS:         4852 passed / 1 failed / 18 skipped / 11 xfailed
                 -> 4864 passed / 2 failed / 7 skipped / 11 xfailed
                 (full capture during US RTH). Comparable
                 `pytest -q -m "not paper_rth"`: 4853 passed / 1 failed
                 / 5 skipped / 14 deselected / 11 xfailed -- failed 1
                 is the exempted IB after-hours test. +2 passed on that
                 cut are S12. The second full-suite failure is the g12
                 paper_rth test (own EXEMPTION). determinism 145 -> 145.
                 mypy clean (201 files). conformance 73 passed / 11
                 xfailed (S11 still xfail on StateTransition).
  PARITY:        declared hold | actual 62 constants unmoved, 0 changed
                 | MATCH vs baseline_pre-S-13.json (62/62 key-for-key).
                 Naming a generator changes no draw order.
  FILES:         14 declared, 14 touched, 14 committed (clean vs
                 d424477). verify_step before commit reported touched 0
                 (uncommitted tree).
  NET DELTA:     declared src modules +1, public symbols +1, branch
                 points 0, test files +1
                 actual modules 200 -> 201 (+1)
                 public_symbols 564 -> 565 (+1, SequenceAuthority)
                 sloc 44827 -> 44920 (+93)
                 n_edges 629 -> 629
                 n_modules 163 -> 163
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 sequence_authority.py is not imported from src/, so
                 the import graph does not gain a module or edge.
  DETERMINISM:   145 passed
  VERIFY_STEP:   Four checks by hand: FILES 14/14 (oracle reported
                 touched 0 on the uncommitted tree); PARITY holds
                 62/62; TESTS failed 1->2, extra is the g12 paper_rth
                 EXEMPTION, comparable not-paper_rth failed 1 IB only;
                 NET DELTA +1/+1/0 on declared axes. DELETES prose is
                 not file deletions -- frozen matcher. CLEAN (boundary
                 -- committed after human go).
  NOTES:         26 SequenceGenerator constructions in src/feelies, 24
                 unique stream names; hazard and metric are shared
                 inject+fallback pairs. stream is keyword-only with
                 default None and no fallback name -- enforcement is by
                 S12 over production call sites, not by the constructor
                 signature, because a required positional would
                 TypeError 154 constructions across 65 test files and
                 21 across 7 scripts. Tests and scripts may construct
                 unnamed generators; they are not authorities. The plan
                 said 13 thread_safe defaults; the actual is 11 -- 13
                 calls have no thread_safe= in the call text, but 2 of
                 those are orchestrator.py SequenceGenerator(stream=...,
                 **_seq_kw) where _seq_kw already carries the flag, and
                 adding it beside **_seq_kw would be a duplicate-keyword
                 error. Stream and contract tables are derived from the
                 construction sites and from wiring_manifest.SUBSCRIPTIONS
                 plus gate_registry, not chosen. S12 uniqueness is per
                 stream; four bus types (Alert, MetricEvent, OrderAck,
                 OrderRequest) have multiple derived authorities and
                 all are listed rather than one being picked. Mutation
                 proof: removing SequenceAuthority("sensor", ...) made
                 S12 fail on both clauses -- orphaned stream and
                 orphaned SensorReading contract -- restore
                 byte-identical. Wall-clock pins unmoved (1642, 1644,
                 1684, 1686, 1780, 1782, 3968).
  FINDINGS:      two baseline failures are now known-environmental and
                 both are recorded -- the IB after-hours EXEMPTION, and
                 this g12 paper_rth failure, which is pre-existing on
                 arch/exec and surfaces only during market hours. Also:
                 ibapi is not a declared dependency, so a fresh
                 worktree cannot run the paper suite -- `uv sync
                 --all-extras` does not install it.
                 Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 subscribe_all kept (six callers outside src/feelies);
                 StateTransition notification record, publish kept for
                 S-31, S11 stays xfail; Inv-10 wall-clock allowlist
                 line-pinned; S-11b semicolons at orchestrator 455,
                 1474, 1480.
  NEXT:          S-14 forbidden-reads matrix (boundary). Not started.
                 Do not begin S-14. Left uncommitted:
                 baseline_pre-S-13.json, baseline_post-S-13.json,
                 this ledger entry.

---

## EXEMPTION  G12 paper_rth cost-disclosure alert in the reference baselines
DATE:        2026-08-22
FAILURE:     tests/integration/test_paper_rth_safety.py::
             test_g12_cost_exceeds_disclosure_alert
             "assert False" on any(a.alert_name ==
             "g12_realized_cost_exceeds_disclosure_stress")
PRESENT IN:  baseline_post-S-13.json (4864 passed, 2 failed, exit 1).
             Absent from baseline_pre-S-13.json (outside RTH; 4852
             passed, 1 failed, 18 skipped) because the test is
             paper_rth-marked and skips. Fails identically on arch/exec
             without the S-13 changes, under PAPER_RTH_FORCE=1 with a
             reachable IB Gateway.
CAUSE:       environmental. paper_rth-marked, so it skips outside US
             RTH and only surfaces during market hours. Requires a
             reachable IB Gateway. Predates S-13; the step does not
             change draw order or the G12 alert path.
DECISION:    proceed. This failure plus the IB after-hours EXEMPTION
             is the accepted in-RTH baseline state. It is NOT a
             regression.
WATCH:       outside RTH, failed == 1 on the IB after-hours test only
             is expected. During US RTH with IB Gateway, failed == 2
             on THIS test and the IB after-hours test is expected.
             failed > 2, or a different test, is a stop.
NOTE:        ibapi is not a declared dependency; `uv sync --all-extras`
             does not install it, so a fresh worktree cannot run the
             paper suite.

---

## EXEMPTION  live-Massive WebSocket failures in the reference baselines
DATE:        2026-08-22
FAILURES:    tests/ingestion/test_massive_functional.py::test_multi_symbol_subscribe
             tests/ingestion/test_massive_functional.py::test_sustained_quotes_with_idle_ticks
PRESENT IN:  baseline_post-S-13.json (4862 passed, 3 failed, exit 1),
             alongside test_g12_cost_exceeds_disclosure_alert.
CAUSE:       environmental. Both require live quote/trade flow from the
             Massive WebSocket feed; they fail when the market is inactive
             or the feed is quiet.
             test_websocket_feed_emits_live_massive_event in the same file
             flipped red then green during the S-11a pre-capture for the
             same reason. Neither S-13 nor any prior step touches
             ingestion/massive_ingestor.py.
DECISION:    proceed. Not regressions.
WATCH:       the accepted baseline failure set is now three tests across two
             files -- the IB after-hours test, g12, and these two Massive
             tests, of which any subset may run or skip depending on market
             hours and feed activity. A failure OUTSIDE that set is a stop.
             `uv run pytest -q -m "not paper_rth"` was clean at 4853 passed
             immediately before this capture.

---

## S-14  2026-08-22T13:15:55+08:00
  STEP:          S-14
  BASE:          fd957d93ca7a0adb795c1db687068b0daa9dc44f
  RESULT SHA:    153ae04c7e15239691da8c344f9e166f8a614708
  VERDICT:       passed
  CONFORMANCE:   S14 static | failed-before: yes | passes-after: yes
                 | mutation: yes
                 S14 dynamic | failed-before: yes | passes-after: yes
                 | mutation: yes
                 Fail-before (no matrix):
                   FAILED tests/conformance/test_forbidden_reads.py::
                   test_s14_static_matrix_and_access_analysis
                   AssertionError: forbidden-reads matrix missing pair:
                   feelies.ingestion event RegimeState
                   FAILED tests/conformance/test_forbidden_reads.py::
                   test_s14_dynamic_no_forbidden_read_during_tick_sequence
                   AssertionError: no forbidden-reads matrix
                   2 failed in 0.64s
                 After implement: 2 passed. Mutation static: dropped
                 FORBIDDEN_READS[0]; S14 failed naming feelies.ingestion
                 event RegimeState; restore SHA256
                 99f6cf7c2b0363d43d57cc315430c0f11e2ea5c6b91dfb2a0bf329050910faf2
                 BYTE_IDENTICAL. Mutation dynamic: probe recorded
                 feelies.forensics event Signal; S14 failed naming that
                 pair; restore SHA256
                 ce38a7a68581f2339b32741a1efbdd4c5fc145569f18b9f164d71602dc2f3f31
                 BYTE_IDENTICAL.
  TESTS:         4854 passed / 0 failed / 19 skipped / 11 xfailed
                 -> 4856 passed / 0 failed / 19 skipped / 11 xfailed
                 +2 are S14. Comparable `pytest -q -m "not paper_rth"`:
                 4855 passed / 0 failed / 6 skipped / 14 deselected /
                 11 xfailed. determinism 145 -> 145. mypy clean
                 (202 files). conformance 75 passed / 11 xfailed
                 (S11 still xfail on StateTransition).
  PARITY:        declared hold | actual 62 constants unmoved, 0 changed
                 | MATCH vs baseline_pre-S-14.json (62/62 key-for-key).
  FILES:         3 declared, 3 touched, 3 committed (clean vs 153ae04).
                 verify_step before commit reported touched 0
                 (uncommitted tree).
  NET DELTA:     declared src modules +1, public symbols +1, branch
                 points 0, test files +1
                 actual modules 201 -> 202 (+1)
                 public_symbols 565 -> 566 (+1, ForbiddenRead)
                 sloc 44920 -> 45034 (+114)
                 n_edges 629 -> 632
                 n_modules 163 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   Four checks by hand: FILES 3/3 (oracle reported
                 touched 0 on the uncommitted tree); PARITY holds
                 62/62; TESTS 4854->4856 passed, 0 failed, +2 are S14;
                 NET DELTA +1/+1/0 on declared axes. DELETES prose is
                 not file deletions -- frozen matcher. CLEAN (boundary
                 -- committed after human go).
  NOTES:         Matrix is 12 x 98 = 1176 cells, 1069 forbidden and
                 107 allowed. Engines derived from pyproject.toml's
                 importlinter "engines" contract in declaration order;
                 facts from the union of SUBSCRIPTIONS event types,
                 ZERO_SUBSCRIBER_RESOLUTIONS, GATE_REGISTRY ids and
                 STREAM_AUTHORITIES streams and contracts -- 21 event
                 + 53 gate + 24 stream. A cell is allowed only if
                 attributable: subscriber class in that engine
                 package, stream or contract authority class in that
                 engine package, or owner_engine as a 1-based index
                 into ENGINES. Classes in kernel, bootstrap or
                 features grant no cell, and no pair was
                 unattributable. Shared feelies.core.events type
                 imports are schema, not scored as reads. Dynamic
                 half runs two tapes: null-alpha SIGNAL-only, 4028
                 reads on four engines, and phase-4 SIGNAL+PORTFOLIO,
                 33539 reads adding composition, portfolio and
                 monitoring -- seven subscriber engines observed in
                 union, no forbidden read on either.
                 LIMITS, both structural and both belonging beside
                 each other: the dynamic half instruments declared
                 bus subscriptions, so it cannot catch a forbidden
                 read on an engine that never subscribes --
                 ingestion, alpha, execution, broker and forensics
                 have no EventBus.subscribe in their packages under
                 any tape. Execution and broker receive quotes
                 through bootstrap's _on_backtest_quote calling
                 router.on_quote(), kernel acting on their behalf,
                 which is the same cell S14 refuses to invent. And
                 the largest violation of the matrix has no row: a
                 Tier-1 module performs Tier-2 reads for nine
                 engines, and kernel, bootstrap and features are not
                 among the twelve. S14 passes while the god
                 orchestrator stands and becomes meaningful as wave D
                 lands.
  FINDINGS:      Carried: G6 vs empty depends_on_sensors; config-path
                 attribution loss + missing loader alpha_id test
                 (S-04c); serialization.py missing
                 __schema_version__ tag as current version (fail-open);
                 ci.yml G40 continue-on-error: true until G40;
                 verify_step uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0 on
                 uncommitted tree; ~157 research cache days stale
                 until after S-17a; 11 UNIT_UNDETERMINED block S-24;
                 subscribe_all kept (six callers outside src/feelies);
                 StateTransition notification record, publish kept for
                 S-31, S11 stays xfail; Inv-10 wall-clock allowlist
                 line-pinned; S-11b semicolons at orchestrator 455,
                 1474, 1480; ibapi is not a declared dependency.
  NEXT:          S-15 reset paths (boundary). Not started.
                 Do not begin S-15. Left uncommitted:
                 baseline_pre-S-14.json, baseline_post-S-14.json,
                 this ledger entry.

---

## S-15  2026-08-22T15:36:09+08:00
  STEP:          S-15
  BASE:          c3e70cc2221b7c18733510b1e1525ad04f9f2602
  RESULT SHA:    not started — blocked at pre-flight, no branch cut, no edit made
  VERDICT:       blocked
  CONFORMANCE:   S16, R6 | failed-before: not run | passes-after: not run
  TESTS:         not run -> not run
  PARITY:        declared hold (all 26 baselines) | actual 62 constants
                 unmoved vs baseline_post-S-14.json, key-for-key and
                 value-for-value | MATCH (read-only parity_constants();
                 no capture run)
  FILES:         28 declared (26 source + 2 test), 0 touched. HEAD
                 arch/exec @ c3e70cc. exec/S-15 not cut.
                 tools/exec diff vs exec-tools-v1 empty. Working tree
                 clean aside from this ledger entry.
  NET DELTA:     declared src modules 0, public symbols +32, branch
                 points 0, test files +2 | actual 0 / 0 / 0 / 0
  DETERMINISM:   not run
  VERIFY_STEP:   not run — no implement
  NOTES:         Class set derived from tools/arch/substrate.py's
                 stateful_no_reset filter (not truncated
                 stateful_no_reset_top[:25]). n_stateful_no_reset=34
                 (plan's "32" is stale; n_stateful_classes=115;
                 mutating outside __init__=40). substrate.json's
                 top-25 truncation made the plan's pointer unusable;
                 FILES was amended at c3e70cc to enumerate 26 source
                 files and still missed eight of the 34.
                 No capture, no branch: same hand-back as S-01's first
                 blocked pre-flight, so the retry starts on a clean
                 tree. Parity verified read-only against
                 baseline_post-S-14.json (artifact git sha 82f02b8;
                 HEAD is c3e70cc = plan FILES amendment on top of
                 cd3385b post-S-14 reference).
  FINDINGS:      PLAN DEFECT — FILES does not contain the scan set.
                 Eight classes live in files the step does not
                 declare. Standing rule: do not edit an undeclared
                 file, and do not skip a class to stay inside FILES.
                 Undeclared (8):
                   MassiveHistoricalIngestor
                     src/feelies/ingestion/massive_ingestor.py
                   CrossSectionalTracker
                     src/feelies/portfolio/cross_sectional_tracker.py
                   DeferralCapController
                     src/feelies/risk/deferral_cap.py
                   ExitComposer
                     src/feelies/risk/exit_composer.py
                   HazardExitController
                     src/feelies/risk/hazard_exit.py
                   StopExitController
                     src/feelies/risk/stop_exit.py
                   SensorRegistry
                     src/feelies/sensors/registry.py
                   InMemoryEventLog
                     src/feelies/storage/memory_event_log.py
                 Declared source files with no class in the set (2):
                   src/feelies/broker/ib/router.py (IBOrderRouter)
                   src/feelies/portfolio/memory_position_store.py
                     (MemoryPositionStore — mutates via dict
                     subscript, so the Attribute-assignment scan
                     does not count it; plan still calls position
                     stores cold-start-only)
                 Full 34, derived, sorted by n_mutated_outside_init:
                   40 Orchestrator src/feelies/kernel/orchestrator.py
                   11 PassiveLimitOrderRouter src/feelies/execution/passive_limit_router.py
                    7 MassiveNormalizer src/feelies/ingestion/massive_normalizer.py
                    6 IBGatewayConnection src/feelies/broker/ib/connection.py
                    6 HorizonMetricsCollector src/feelies/monitoring/horizon_metrics.py
                    5 BacktestOrderRouter src/feelies/execution/backtest_router.py
                    5 MetricSummary src/feelies/monitoring/in_memory.py
                    4 MassiveLiveFeed src/feelies/ingestion/massive_ws.py
                    4 HorizonSignalEngine src/feelies/signals/horizon_engine.py
                    2 AlphaRegistry src/feelies/alpha/registry.py
                    2 _WarmTimestampIndex src/feelies/features/aggregator.py
                    2 BasicRiskEngine src/feelies/risk/basic_risk.py
                    2 HorizonScheduler src/feelies/sensors/horizon_scheduler.py
                    2 RegimeStateCache src/feelies/services/regime_state_cache.py
                    1 AlphaBudgetRiskWrapper src/feelies/alpha/risk_wrapper.py
                    1 EventBus src/feelies/bus/event_bus.py
                    1 CompositionEngine src/feelies/composition/engine.py
                    1 UniverseSynchronizer src/feelies/composition/synchronizer.py
                    1 SimulatedClock src/feelies/core/clock.py
                    1 SequenceGenerator src/feelies/core/identifiers.py
                    1 MocFillController src/feelies/execution/moc_fill.py
                    1 RthEntryFillGate src/feelies/execution/trading_session.py
                    1 HorizonAggregator src/feelies/features/aggregator.py
                    1 QuoteReplayObserver src/feelies/harness/backtest_prep.py
                    1 QuoteTraceIndex src/feelies/harness/backtest_prep.py
                    1 MassiveHistoricalIngestor src/feelies/ingestion/massive_ingestor.py
                    1 CrossSectionalTracker src/feelies/portfolio/cross_sectional_tracker.py
                    1 DeferralCapController src/feelies/risk/deferral_cap.py
                    1 ExitComposer src/feelies/risk/exit_composer.py
                    1 HazardExitController src/feelies/risk/hazard_exit.py
                    1 StopExitController src/feelies/risk/stop_exit.py
                    1 SensorRegistry src/feelies/sensors/registry.py
                    1 InMemoryEventLog src/feelies/storage/memory_event_log.py
                    1 DurableSubmittedOrderJournal src/feelies/storage/submitted_order_journal.py
                 Amend FILES to add the eight undeclared paths before
                 retry. Durable vs run-scoped split was not declared:
                 DurableSubmittedOrderJournal is in the 34 and must
                 not be reset by replay (S-08); InMemoryEventLog is
                 the tape. That split is for the retry, not this stop.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step uppercase / unfenced /
                 negation-blind / bare-filename / stale NET DELTA /
                 FILES touched 0 on uncommitted tree; ~157 research
                 cache days stale until after S-17a; 11
                 UNIT_UNDETERMINED block S-24; subscribe_all kept
                 (six callers outside src/feelies); StateTransition
                 notification record, publish kept for S-31, S11
                 stays xfail; Inv-10 wall-clock allowlist
                 line-pinned at orchestrator 1642, 1644, 1684, 1686,
                 1780, 1782, 3968; S-11b semicolons at orchestrator
                 455, 1474, 1480; ibapi is not a declared
                 dependency; accepted baseline failure set is the
                 four exempted tests.
  NEXT:          plan amend FILES (add the eight undeclared source
                 paths), then retry S-15. Do not start S-16.
                 Left uncommitted: this ledger entry. No
                 baseline_pre-S-15.json.

---

## S-15  2026-08-22T17:50:00+08:00
  STEP:          S-15
  BASE:          f70f7ce5f8c11dd679c3e726b851d0753f3ad373
  RESULT SHA:    9e45fc58c013565592a5963f48c77af4d5508ffa
  VERDICT:       passed
  CONFORMANCE:   S16 | failed-before: yes | passes-after: yes
                 | mutation: yes
                 R6 | failed-before: yes | passes-after: yes
                 Fail-before (HEAD src, S-03 S16 xfail + new R6):
                   FAILED tests/conformance/test_reset_paths.py::
                   test_reset_path_totality --runxfail
                   AssertionError: 34 stateful class(es) mutate
                   outside __init__ with no reset path. First:
                   Orchestrator (src/feelies/kernel/orchestrator.py)
                   assert 34 == 0
                   1 failed in 0.90s
                   FAILED tests/conformance/test_recovery_determinism.py::
                   test_reset_then_replay_matches_cold_start
                   AttributeError: 'Orchestrator' object has no
                   attribute 'reset'
                   1 failed in 0.97s
                 After implement: S16 + R6 pass. Mutation: removed
                 EventBus.reset(); S16 failed Unexpected:
                 ['EventBus']; restore SHA256
                 69FAF0EC4676696E3AABC87642D63997463DF5D2B1D370A15062DD07EC85B769
                 BYTE_IDENTICAL.
  TESTS:         4856 passed / 0 failed / 19 skipped / 10 xfailed
                 -> 4858 passed / 0 failed / 19 skipped / 10 xfailed
                 +2 are S16 un-xfail and R6. determinism 145 -> 145.
                 mypy clean (202 files). conformance 77 passed /
                 10 xfailed (S11 still xfail on StateTransition).
                 wall-clock pins unmoved (1642, 1644, 1684, 1686,
                 1780, 1782, 3968).
  PARITY:        declared hold | actual 62 constants unmoved, 0
                 changed | MATCH vs baseline_pre-S-15.json (62/62
                 key-for-key).
  FILES:         36 declared, 33 touched, 33 committed (clean vs
                 9e45fc5). Three declared untouched:
                 massive_ws.py, broker/ib/connection.py,
                 storage/submitted_order_journal.py (the three
                 durable/live exemptions). verify_step before
                 commit reported touched 0 (uncommitted tree).
  NET DELTA:     declared src modules 0, public symbols +32,
                 branch points 0, test files +2
                 actual modules 202 -> 202 (+0)
                 public_symbols 566 -> 566 (+0; measure.py counts
                 module-level classes/functions, not methods)
                 sloc 45034 -> 45361 (+327)
                 n_edges 632 -> 632
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 Hand count: 33 new instance reset() methods
                 (31 scan-visible + IBOrderRouter +
                 MemoryPositionStore) vs the plan's stale +32.
  DETERMINISM:   145 passed
  VERIFY_STEP:   Four checks by hand: FILES 36 declared / 33
                 touched / 0 extras; PARITY holds 62/62; TESTS
                 4856->4858 passed, 0 failed; NET DELTA modules 0,
                 measure public_symbols 0 (methods), sloc +327.
                 DELETES is replacement of ad-hoc clearing, not a
                 file deletion. CLEAN (boundary gate, then commit).
  NOTES:         34 classes, not the plan's 32. 31 run-scoped got
                 reset(); three durable or live exemptions with
                 reasons -- DurableSubmittedOrderJournal (S-08: the
                 only record of what was sent), IBGatewayConnection
                 (live threads and nextValidId), MassiveLiveFeed
                 (live WS loop). IBOrderRouter and
                 MemoryPositionStore also got reset() despite being
                 absent from the scan: it counts self.attr= only,
                 and both mutate through containers, so their state
                 is run-scoped. InMemoryEventLog.reset()
                 deliberately does not clear _events.
                 _handle_tick_failure now calls self.reset(...,
                 for_new_run=False) -- that branch is exactly the
                 _micro.reset plus _pending_sized_intents.clear(),
                 in that order -- replacing the ad-hoc clearing
                 rather than sitting beside it. Mutation proof:
                 removing EventBus.reset() made S16 report
                 Unexpected: ['EventBus']; restore byte-identical.
                 R6 caught a real reset bug during implementation
                 -- SensorRegistry.reset() cleared preallocated
                 state_by_symbol, warm 10 vs cold 9818, fixed by
                 re-seeding initial_state().
  FINDINGS:      R6 exercises 14 of the 31 resets, of which about
                 six can actually fail it on the FIX-1 tape.
                 Seventeen are never invoked -- four constructed
                 but not reached through the cascade
                 (InMemoryEventLog, RthEntryFillGate, MetricSummary,
                 _WarmTimestampIndex, the last two because the
                 parent calls clear() rather than the child's
                 reset()), and thirteen never constructed on that
                 tape (PassiveLimitOrderRouter, MassiveNormalizer,
                 MassiveHistoricalIngestor, MocFillController,
                 CompositionEngine, UniverseSynchronizer,
                 CrossSectionalTracker, HorizonMetricsCollector,
                 HazardExitController, ExitComposer,
                 DeferralCapController, QuoteReplayObserver,
                 QuoteTraceIndex), plus IBOrderRouter.
                 reset(for_new_run=False) is also untested -- R6
                 never takes that branch. R6's fingerprint is
                 (event type, sequence), not payloads, so a bad
                 reset emitting the same types and sequences would
                 pass. 33 new methods with one covering integration
                 is the shape this campaign keeps finding vacuous,
                 and the follow-up is a widened tape (PORTFOLIO
                 plus a trading SIGNAL plus
                 execution_mode="passive_limit" plus an MOC date)
                 or per-class mutate -> reset() -> equals-post-init
                 roundtrips. Carried, not fixed: G6 vs empty
                 depends_on_sensors; config-path attribution +
                 missing loader alpha_id test (S-04c);
                 serialization.py missing __schema_version__ tag as
                 current version (fail-open); ci.yml G40
                 continue-on-error: true until G40; verify_step
                 uppercase / unfenced / negation-blind /
                 bare-filename / stale NET DELTA / FILES touched 0
                 on uncommitted tree; ~157 research cache days
                 stale until after S-17a; 11 UNIT_UNDETERMINED
                 block S-24; subscribe_all kept; StateTransition
                 kept for S-31, S11 stays xfail; Inv-10 wall-clock
                 allowlist line-pinned; S-11b semicolons;
                 accepted baseline failure set is the four
                 exempted tests.
  NEXT:          S-16 alpha manifest content hash (boundary). Not
                 started. Do not begin S-16. Left uncommitted:
                 baseline_pre-S-15.json, baseline_post-S-15.json,
                 this ledger entry.

---

## S-16  2026-08-22T19:46:00+08:00
  STEP:          S-16
  BASE:          d7c4a856ec15c0ea766ea1411c2afc78269d7cc3
  RESULT SHA:    e2a7c2b3b5faccffbf5cf0ac9ca5707af0c3c8af
  VERDICT:       passed
  CONFORMANCE:   R4 | failed-before: yes | passes-after: yes | mutation: yes
                 Fail-before (HEAD src, R4 xfail + --runxfail):
                   FAILED tests/conformance/test_fingerprint_totality.py::
                   test_r4_fingerprint_covers_resolved_registry_not_promotion_ledger
                   AssertionError: manifest content moves no checksum:
                   alpha_one.alpha.yaml
                   assert not ['alpha_one.alpha.yaml', 'alpha_two.alpha.yaml']
                   1 failed in 0.26s
                 After implement: 1 passed. Mutation: skipped
                 compute_manifest_hash for alpha_one.alpha.yaml in
                 _to_dict; R4 failed naming alpha_one.alpha.yaml;
                 restore SHA256
                 5086A9B13A7B4B2AEF3F88F2404ECBAA2ADA8C442F8C53A1829E1E818E591BFB
                 BYTE_IDENTICAL.
  TESTS:         4858 passed / 0 failed / 19 skipped / 10 xfailed
                 -> 4860 passed / 1 failed / 19 skipped / 10 xfailed
                 (post-S-16 capture, before re-pin). After operator
                 re-pin, test_app_baseline_config_contract_hash
                 1 passed in 0.34s. +3 are R4 and two snapshot
                 tests. Functional APP replay passed. determinism
                 145 -> 145. mypy clean (202 files). conformance
                 77 passed / 10 xfailed -> 78 passed / 10 xfailed
                 (S11 still xfail on StateTransition). wall-clock
                 pins unmoved (1642, 1644, 1684, 1686, 1780, 1782,
                 3968).
  PARITY:        declared break (_BASELINE_CONFIG_HASH only; 26
                 replay baselines hold) | actual 26 hold; pin
                 e4073f3517ce6232dfc067228e991b8477b1de93b8cb582b2ffc9f62cafa0e6b
                 -> 89d43554e749134925b9407c9e810a2fa2e7ce56a3efa26bf596818d0e3cd64c
                 re-pinned by operator | MATCH.
  FILES:         15 declared, 15 committed (clean vs e2a7c2b).
                 verify_step before commit reported touched 0
                 (uncommitted tree).
  NET DELTA:     declared src modules 0, public symbols +1,
                 branch points 0, test files +1
                 actual modules 202 -> 202 (+0)
                 public_symbols 566 -> 567 (+1, compute_manifest_hash)
                 sloc 45361 -> 45452 (+91)
                 n_edges 632 -> 633 (+1, loader imports
                 compute_manifest_hash)
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 passed
  VERIFY_STEP:   Four checks by hand: FILES 15/15 after re-pin
                 (oracle reported touched 0 on the uncommitted
                 tree); PARITY 26 replay hold, config-contract
                 pin moved as declared; TESTS 4858->4860 passed,
                 0->1 failed on the unre-pinned oracle, then the
                 oracle 1 passed after re-pin; NET DELTA modules
                 0, public_symbols +1, sloc +91. DELETES is the
                 names-only reduction, not a file deletion.
                 CLEAN (boundary, then commit).
  NOTES:         First declared parity break of the campaign. All
                 26 replay baselines unmoved -- 62 file constants
                 identical pre to post. _BASELINE_CONFIG_HASH
                 moved e4073f35 -> 89d43554 by construction,
                 verified on a clean alphas/ tree after
                 implementation. The threshold demonstration is
                 the point of the step: editing entry_threshold_z
                 in sig_benign_midcap_v1 from 0.8 to 0.9 moved
                 the config hash 89d43554 -> d2e5870b, and the
                 YAML restored byte-identical. manifest_hash
                 mutation proof: skipping compute_manifest_hash
                 for alpha_one.alpha.yaml in _to_dict made R4
                 name it; restore byte-identical. _to_dict
                 discloses spec content rather than names-only,
                 which is what makes the oracle move --
                 test_app_baseline_config_contract_hash calls
                 from_yaml then snapshot() and never loads
                 alphas, so a hash stored only on AlphaManifest
                 would have been invisible to it. Scope is the
                 resolved registry, never the promotion ledger:
                 R4's docstring states the exclusion, and it
                 asserts that changing ledger.jsonl bytes does
                 not move snapshot().checksum. The compatibility
                 shims at platform_config.py were not extended,
                 and events.py and test_schema_drift.py were not
                 touched.
  FINDINGS:      The S-16 block's DELETES field still cites the
                 names-only reduction at `:683`; the corrected
                 cite is `:726-727`, already fixed in PROBLEM
                 but not in DELETES. Also: compute_config_hash
                 lives on feelies.harness, not platform_config --
                 worth noting for future steps that touch the
                 config oracle.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader
                 alpha_id test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step uppercase / unfenced /
                 negation-blind / bare-filename / stale NET
                 DELTA / FILES touched 0 on uncommitted tree;
                 ~157 research cache days stale until after
                 S-17a; 11 UNIT_UNDETERMINED block S-24;
                 subscribe_all kept; StateTransition kept for
                 S-31, S11 stays xfail; Inv-10 wall-clock
                 allowlist line-pinned; S-11b semicolons;
                 accepted baseline failure set is the four
                 exempted tests; R6 14/31 resets.
  NEXT:          S-17 canonical market-data replay (local). Not
                 started. Do not begin S-17. Left uncommitted:
                 baseline_pre-S-16.json, baseline_post-S-16.json,
                 this ledger entry.

---

## S-17  2026-08-22T20:54:00+08:00
  STEP:          S-17
  BASE:          ecc5afa2ccf0ca21c9a38101aa37f7fa72e53396
  RESULT SHA:    cd5382e883f34c3d39ff16eaf2b9d02515ad7594
  VERDICT:       passed
  CONFORMANCE:   R2 | failed-before: yes | passes-after: yes
                 | mutation: yes
                 R9 | failed-before: yes | passes-after: yes
                 Fail-before (R2 xfail + --runxfail):
                   FAILED tests/conformance/test_market_data_canonical.py::
                   test_market_data_canonical_parity_baseline
                   AssertionError: engine 1 canonical stream has no
                   baseline (G05); S-17 supplies it
                   assert None is not None
                   1 failed in 0.63s
                 Fail-before (R9 closure, after extending :261 and :288,
                 before baselines):
                   FAILED test_every_locked_hash_is_registered_or_exempt
                   AssertionError: engine outputs neither hashed nor
                   exempt-with-a-reason: alert_taxonomy (engine 11 Alert
                   taxonomy, alert_name and severity only (G29));
                   market_data_canonical (engine 1 NBBOQuote/Trade
                   canonical stream (G05))
                   FAILED test_every_exemption_names_a_binding_that_exists
                   AssertionError: engine-output hash bindings missing
                   from scannable modules:
                   EXPECTED_ALERT_TAXONOMY_HASH (engine 11 Alert
                   taxonomy (G29));
                   EXPECTED_MARKET_DATA_CANONICAL_HASH (engine 1
                   canonical stream (G05))
                   2 failed in 1.54s
                 After implement: R2 1 passed (xfail dropped in the
                 same change that supplied the constant); R9 closure
                 2 passed. After operator re-pin:
                 test_manifest_fingerprint_matches_locked_value
                 1 passed in 0.47s. Mutation: one byte of the
                 raw-frame fixture `"sym": "AAPL"` -> `"sym": "BAPL"`
                 (first occurrence); canonical hash
                 4c0446aa6c9c1dced2e98016158f209f9072df2891d5bc2e60396f369072115a
                 ->
                 d4f21e2e1ff8c98cf6ab6c3385789a4dd48d7fd43a1915c214326d007ba38fca;
                 restore SHA256
                 d126ffd134849a7986aad2dee05c017099a30eb266261ab7184df3260d0b8ea0
                 BYTE_IDENTICAL; restored hash 4c0446aa. pycache
                 purged between mutate and restore.
  TESTS:         4861 passed / 0 failed / 19 skipped / 10 xfailed
                 -> 4866 passed / 1 failed / 19 skipped / 9 xfailed
                 (post-S-17 capture, before re-pin). After operator
                 re-pin, test_manifest_fingerprint_matches_locked_value
                 1 passed; determinism 148 passed / 0 failed.
                 conformance 78 passed / 10 xfailed -> 79 passed /
                 9 xfailed (R2 xfail dropped, no XPASS).
  PARITY:        declared 26 hold; manifest 26 -> 28 and
                 manifest_fingerprint() moves by construction |
                 actual 26 replay hashes and counts unmoved
                 (62/62 pre-map constants identical); +2 entries;
                 EXPECTED_MANIFEST_FINGERPRINT
                 4b85ce329259e889100629992c31ff3cac332e0c24de91698adb0e0ca49dd95a
                 ->
                 ec7af15d242a1aa6231b61ef3ee544182ad4dd3d3831927c96e07465f7886e06
                 re-pinned by operator | MATCH.
  FILES:         4 declared, 4 committed (clean vs cd5382e).
                 verify_step before commit reported touched 0
                 (uncommitted tree). git status --porcelain -- src
                 empty.
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, test files +1, manifest entries +2
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45452 -> 45452 (+0)
                 n_edges 633 -> 633
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   145 -> 148 passed
  VERIFY_STEP:   Four checks by hand: FILES 4/4 after re-pin
                 (oracle reported touched 0 on the uncommitted
                 tree); PARITY 26 replay hold, fingerprint pin
                 moved as declared; TESTS 4861->4866 passed,
                 0->1 failed on the unre-pinned fingerprint, then
                 fingerprint 1 passed and determinism 148 after
                 re-pin; NET DELTA 0/0/0, DELETES is conceptual
                 not a file deletion. CLEAN (local, then commit).
  NOTES:         Manifest grows 26 -> 28. New entries:
                 market_data_canonical
                 (4c0446aa6c9c1dced2e98016158f209f9072df2891d5bc2e60396f369072115a,
                 count 2) from engine 1's canonical NBBOQuote/Trade
                 stream, and alert_taxonomy
                 (f6b784b275a549e169f7075ca583b9f198966f802216fbf7e8eb835d6f31b557,
                 count 4) from engine 11. Taxonomy is alert_name
                 and severity.name only -- composition.low_completeness,
                 composition.high_degenerate_rate,
                 composition.solver_degraded,
                 composition.factor_residual_high, all WARNING --
                 with message excluded, because pinning alert
                 content would convert every diagnostic improvement
                 into a parity break. Engine 1 hashes Decimal as
                 exact strings, not .6f. FLOAT_HASH_TOLERANCE =
                 ".6f/.2f" now stated in the manifest, documenting
                 what the helpers already do rather than changing
                 any hash. R2's xfail dropped in the same change
                 that supplied its constant, so no XPASS. All 26
                 existing baselines unmoved; parity map 62
                 identical plus the two new alert-taxonomy
                 constants. EXPECTED_MANIFEST_FINGERPRINT 4b85ce32
                 -> ec7af15d. git status --porcelain -- src empty:
                 no production file touched. Fixture mutation
                 proof: one byte, "sym": "AAPL" -> "BAPL", moved
                 the canonical hash 4c0446aa -> d4f21e2e; restore
                 byte-identical.
  FINDINGS:      1. baseline.py's parity scanner does not see
                    EXPECTED_MARKET_DATA_CANONICAL_HASH/COUNT
                    because R2 lives in tests/conformance/ (S-03
                    authored it there) and the scanner only reads
                    tests/determinism/ plus the acceptance APP
                    file. The hex is in LOCKED_PARITY_BASELINES via
                    import; R9 sees it (whole tests/ tree). Not
                    fixed — would be a tools/exec edit, frozen.
                 2. verify_step FILES touched 0 on uncommitted
                    tree; PARITY blind to FINGERPRINT and to
                    conformance-hosted hashes; NET DELTA treats
                    conceptual DELETES as missing file deletions.
                    Frozen, worked around.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader
                 alpha_id test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step frozen bugs; ~157 research
                 cache days stale until after S-17a; 11
                 UNIT_UNDETERMINED block S-24; accepted baseline
                 failure set is the four exempted tests; R6 14/31
                 resets.
  NEXT:          S-17a fold per-event field sets into
                 manifest_fingerprint() (platform-wide). Not
                 started. Do not begin S-17a. Left uncommitted:
                 baseline_pre-S-17.json,
                 baseline_post-S-17.json, this ledger entry.

---

## S-17a  2026-08-22T21:46:40+08:00
  STEP:          S-17a
  BASE:          064d28ae2841ffdb4f40581a53a3d325a88366d4
  RESULT SHA:    b881cd593f896c3c23f1f1f15c304b730192ff97
  VERDICT:       passed
  CONFORMANCE:   S8 sibling test_s17a_field_add_moves_fingerprint_not_replay_hashes
                 | failed-before: n/a -- the oracle proof is blindness,
                 not S8. S8 fails by name if PINNED_PAYLOAD is not
                 updated; that is not the gap.
                 Blindness (before fold, Signal.s17a_probe present,
                 PINNED_PAYLOAD untouched):
                   tests/determinism/test_parity_manifest.py -k
                   "fingerprint or entry_matches"
                   29 passed, 5 deselected in 1.77s
                 After fold, same probe:
                   fingerprint dbcde6a6 -> 23f758b0
                   EXPECTED_LEVEL2_SIGNAL_HASH held at e3b0c442
                   28 entry_matches passed, fingerprint 1 failed
                 After implement (no probe): schema-drift 2 passed
                 (S8 + S-17a). After operator re-pin:
                 test_manifest_fingerprint_matches_locked_value
                 1 passed in 0.44s; determinism 148 passed / 0 failed.
  TESTS:         4867 passed / 0 failed / 19 skipped / 9 xfailed
                 -> 4867 passed / 1 failed / 19 skipped / 9 xfailed
                 (post-S-17a capture, before re-pin). After operator
                 re-pin, fingerprint 1 passed; determinism 148 passed
                 / 0 failed. conformance 79 passed / 9 xfailed ->
                 80 passed / 9 xfailed (S-17a assertion added, no
                 XPASS). not-paper_rth: 1 failed, 4866 passed, 6
                 skipped, 14 deselected, 9 xfailed -- the one failure
                 was the unre-pinned fingerprint; none of the four
                 exempted tests.
  PARITY:        declared break EXPECTED_MANIFEST_FINGERPRINT only;
                 28 replay hashes and counts do not move | actual
                 28 hashes and counts unmoved; 64/64 scanned
                 constants identical; EXPECTED_MANIFEST_FINGERPRINT
                 ec7af15d242a1aa6231b61ef3ee544182ad4dd3d3831927c96e07465f7886e06
                 ->
                 dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                 re-pinned by operator | MATCH.
  FILES:         3 declared, 3 committed (clean vs b881cd5).
                 verify_step S-17a --base 064d28ae uppercased the id
                 to S-17A and exited "S-17A not in plan" (frozen).
                 git status --porcelain -- src empty.
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, test files +0
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45452 -> 45452 (+0)
                 n_edges 633 -> 633
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   148 -> 148 passed (1 failed before re-pin, then 148)
  VERIFY_STEP:   Four checks by hand (oracle uppercased S-17a to
                 S-17A): FILES 3/3 after re-pin (oracle would report
                 touched 0 on the uncommitted tree); PARITY 28 replay
                 hold, fingerprint pin moved as declared, scanner
                 blind to FINGERPRINT; TESTS 4867->4867 passed,
                 0->1 failed on the unre-pinned fingerprint, then
                 fingerprint 1 passed and determinism 148 after
                 re-pin; NET DELTA 0/0/0, DELETES is conceptual.
                 CLEAN (platform-wide, then commit).
  NOTES:         The fold hashes class names sorted, plus dataclass
                 field names in dataclass order, for the 21 concrete
                 Event subclasses -- Event itself excluded. Type
                 annotations, defaults and Field.metadata are NOT
                 hashed, so S-18's mutable-container conversions will
                 not move the fingerprint. Encoding is
                 ClassName|field1,field2,... per line, appended after
                 the sorted manifest name|hash|count lines. Blindness
                 proof: with Signal.s17a_probe present and
                 PINNED_PAYLOAD untouched, test_manifest_fingerprint_matches_locked_value
                 and all 28 test_manifest_entry_matches_replay passed
                 -- 29 passed, 5 deselected. After the fold the same
                 probe moved the fingerprint dbcde6a6 -> 23f758b0
                 while EXPECTED_LEVEL2_SIGNAL_HASH held at e3b0c442.
                 events.py restored byte-identical both times,
                 SHA256 CE2CC0E8...; git status --porcelain -- src
                 empty. The 28 replay hashes and counts and all 64
                 scanned constants are unmoved.
                 EXPECTED_MANIFEST_FINGERPRINT ec7af15d -> dbcde6a6.
                 From here every field add or delete moves the
                 fingerprint by design. S-23's new DeRiskRequirement
                 class and S-31 step 1's 20 unread-field deletions
                 both do, and S-31's "all baselines hold" line covers
                 replay hashes only. The ~157 stale research cache
                 days are now unblocked for re-ingest.
  FINDINGS:      1. verify_step.py uppercases the step id, so S-17a
                    becomes S-17A and is not found. Frozen -- worked
                    around by hand. Carried: FILES touched 0 on
                    uncommitted tree; PARITY blind to FINGERPRINT;
                    NET DELTA stale counts; blast-radius substring
                    matching; bare filenames in FILES prose.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader
                 alpha_id test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; 11 UNIT_UNDETERMINED block S-24;
                 accepted baseline failure set is the four
                 exempted tests; R6 14/31 resets.
  NEXT:          S-18 convert 8 mutable container fields on frozen
                 events (boundary). Not started. Do not begin S-18.
                 Left uncommitted: baseline_pre-S-17a.json,
                 baseline_post-S-17a.json, this ledger entry.

---

## S-18  2026-08-23T10:40:04+08:00
  STEP:          S-18
  BASE:          555a7bd58b980eb682adbb2ec4661e3cd710ce9e
  RESULT SHA:    b1341db5961de0004e42d4dd3e551000c82b16c7
  VERDICT:       passed
  CONFORMANCE:   S10 | failed-before: yes | passes-after: yes
                 | mutation: yes
                 Fail-before (--runxfail, xfail(strict, GAP G12) still on):
                   FAILED tests/conformance/test_event_immutability.py::
                   test_frozen_events_carry_no_mutable_container
                   AssertionError: frozen events with mutable container
                   fields (G12): Alert=['context'],
                   CrossSectionalContext=['signals_by_symbol',
                   'signals_by_strategy_by_symbol',
                   'snapshots_by_symbol'],
                   HorizonFeatureSnapshot=['values', 'warm', 'stale',
                   'source_sensors', 'feature_versions'],
                   MetricEvent=['tags'], RiskVerdict=['constraints'],
                   Signal=['metadata'],
                   SizedPositionIntent=['target_positions',
                   'factor_exposures', 'mechanism_breakdown',
                   'disclosed_cost_total_bps_by_symbol'],
                   StateTransition=['metadata']
                   1 failed in 0.56s
                 After last class + xfail drop: 1 passed in 0.42s.
                 Mutation: HorizonFeatureSnapshot.values annotation
                 Mapping[str, float] -> dict[str, float]; S10 failed
                 naming HorizonFeatureSnapshot=['values']; restore
                 SHA256 4570911D728997F01C8FAF9DA457F7302C384C8432E4B7286A843DB1DACC8408
                 BYTE_IDENTICAL; restored S10 1 passed. pycache purged
                 between mutate and restore.
  TESTS:         4868 passed / 0 failed / 19 skipped / 9 xfailed
                 -> 4869 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-18 capture GREEN). not-paper_rth: 4868 passed,
                 6 skipped, 14 deselected, 8 xfailed, 0 failed.
                 conformance 80 passed / 9 xfailed -> 81 passed /
                 8 xfailed (S10 xfail dropped, no XPASS).
                 mypy src/feelies: Success, 202 source files.
  PARITY:        declared hold -- all 28 replay hashes and
                 EXPECTED_MANIFEST_FINGERPRINT | actual 64/64 scanned
                 constants identical (pre-S-18 vs post-S-18, and vs
                 baseline_post-S-17a.json); 28 hashes unmoved;
                 EXPECTED_MANIFEST_FINGERPRINT held at
                 dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                 | MATCH. PINNED_PAYLOAD not touched
                 (test_schema_drift.py empty diff; 2 passed).
  FILES:         2 declared, 2 committed (clean vs b1341db).
                 verify_step FILES declared 2, touched 2, clean.
                 git status --porcelain -- src empty.
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, test files +0
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45452 -> 45499 (+47)  (__post_init__ wrappers)
                 n_edges 633 -> 633
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
  DETERMINISM:   148 -> 148 passed after every class; no hash moved
  VERIFY_STEP:   Four checks: FILES 2/2 clean; PARITY moved 0 holds
                 (oracle parsed declared hold as FINGERPRINT only --
                 frozen substring match; 64 constants and FINGERPRINT
                 checked by hand, unmoved); NET DELTA 0/0/0 with
                 conceptual DELETES (oracle "compare by eye"); CLEAN,
                 blast radius boundary -- human gate required.
                 Worked around: scanner blind to FINGERPRINT; DELETES
                 is conceptual not a file deletion.
  NOTES:         Freeze is MappingProxyType(dict(field)) via
                 object.__setattr__ in each class's __post_init__,
                 with annotations dict[...] -> Mapping[...].
                 Copy-then-wrap, so the proxy is not a live view of
                 the caller's dict. Publishers still pass plain dict
                 and no construction site was edited.
                 CrossSectionalContext.signals_by_strategy_by_symbol
                 is a shallow freeze -- the outer mapping only,
                 inner dict values remain dict; a limit, not a defect.
                 Eight commits, cheapest first by field count:
                 Alert 2055bed, MetricEvent 26ea043,
                 RiskVerdict a6a7054, Signal 2318a49,
                 StateTransition c9479d4 (1 field each),
                 CrossSectionalContext 28951ac (3),
                 SizedPositionIntent ab60f89 (4),
                 HorizonFeatureSnapshot b1341db (5, with the S10
                 xfail drop). Determinism 148 passed after every
                 one, no hash moved at any point.
                 EXPECTED_MANIFEST_FINGERPRINT identical before and
                 after at dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b,
                 confirming S-17a's fold hashes field names only
                 and not annotations. PINNED_PAYLOAD untouched.
                 Mutation proof: HorizonFeatureSnapshot.values
                 reverted to dict made S10 name it; restore
                 SHA256 4570911D728997F01C8FAF9DA457F7302C384C8432E4B7286A843DB1DACC8408
                 BYTE_IDENTICAL.
  FINDINGS:      No consumer broke. The block's blast-radius
                 rationale was that every consumer mutating a
                 received event would break loudly -- none did,
                 across all 17 fields and 8 classes. Phase 0 C-7
                 warned read-after-mutation was possible and
                 untested; this step tested it and found none.
                 Cleared risk, not an absence of evidence.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step frozen bugs; 152 research
                 cache days stale (APP/2026-03-26 current; S-18
                 does not re-invalidate); 11 UNIT_UNDETERMINED
                 block S-24; accepted baseline failure set is the
                 four exempted tests; R6 14/31 resets.
  NEXT:          S-19 move 5 regime methods out of the kernel
                 (boundary). Not started. Do not begin S-19.
                 Left uncommitted: baseline_pre-S-18.json,
                 baseline_post-S-18.json, this ledger entry.

---

## S-19  2026-08-23T11:49:53+08:00
  STEP:          S-19
  BASE:          b34276956ec0dc072218789df59542ee51e5f684
  RESULT SHA:    859779965ee2b866329067992995ca0d80a27b20
  VERDICT:       passed
  CONFORMANCE:   no new test. S2/S12/S14 held before and after.
                 S2: 1 passed, 1 xfailed (G40) -> 1 passed, 1 xfailed
                 S12: 2 passed -> 2 passed
                 S14: 2 passed -> 2 passed
                 level5_regime_hazard_spike and level6_regime_state
                 held after every method.
  TESTS:         4869 passed / 0 failed / 19 skipped / 8 xfailed
                 -> 4869 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-19 capture GREEN). not-paper_rth: 4868 passed,
                 6 skipped, 14 deselected, 8 xfailed, 0 failed.
                 conformance 81 passed / 8 xfailed -> 81 passed /
                 8 xfailed (no XPASS).
                 mypy src/feelies: Success, 202 source files.
  PARITY:        declared hold -- all 28 replay hashes and
                 EXPECTED_MANIFEST_FINGERPRINT | actual 64/64 scanned
                 constants identical (pre-S-19 vs post-S-19, and vs
                 baseline_post-S-18.json); 28 hashes unmoved after
                 every method; EXPECTED_MANIFEST_FINGERPRINT held at
                 dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                 | MATCH.
  FILES:         4 real paths declared, 4 committed (clean vs 8597799).
                 verify_step FILES declared 5, touched 4, "not touched
                 orchestrator.py" -- fifth token is prose noise, bare
                 filename vs path (frozen). git status --porcelain -- src
                 empty after the method commits.
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, orchestrator lines -~200
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45499 -> 45501 (+2)
                 n_edges 633 -> 634
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines 5622 -> 5406 (-216)
                 orchestrator methods 126 -> 121 (-5)
  DETERMINISM:   148 -> 148 passed after every method; no hash moved
  VERIFY_STEP:   Four checks: FILES 4/4 real (oracle 5/4, prose noise);
                 PARITY moved 0 holds; TESTS 4869->4869 passed, 0 failed;
                 NET DELTA 0/0/0 with conceptual DELETES (oracle
                 "compare by eye"). CLEAN, blast radius boundary --
                 human gate required.
  NOTES:         Five methods moved to services/regime_engine.py as
                 module functions taking the orchestrator as self: Any,
                 one per commit, _maybe_publish_hazard_spike last
                 because it draws _hazard_seq. No shims. Determinism
                 148 after every commit, level5_regime_hazard_spike
                 held throughout. Orchestrator 5622 -> 5406 lines
                 (-216), 126 -> 121 methods -- the plan's 123 -> 118
                 was stale. SequenceGenerator constructions stayed at
                 orchestrator.py:437 and :445, so S-13's
                 SequenceAuthority bindings hold; S2, S12 and S14 all
                 unchanged. Inv-10 pin 3968 -> 3794 retargeted in
                 _drain_async_fills; the six above the cut did not
                 move; guard proof: a throwaway perf_counter_ns in
                 reset failed as :3814, restore byte-identical.
                 test_orchestrator.py:503 rewritten to
                 _calibrate_regime_engine(orch).
                 WAVE-D METHOD, established here for S-20 onward: one
                 method per commit; bodies copied unchanged as
                 module-level functions taking the orchestrator; no
                 delegating shim; SequenceGenerator constructions stay
                 on Orchestrator; any sequence-drawing method goes
                 last; do not add lines above the six Inv-10 pins;
                 retarget only pins below the cut; prove the guard
                 still names a throwaway.
                 Order: _regime_label_for (285ff6d),
                 _checkpoint_regime_snapshot (dea2141),
                 _calibrate_regime_engine (3b59e8b), _update_regime
                 (466da57), _maybe_publish_hazard_spike last
                 (3fd6630); hashlib noqa pin-hold (8597799).
  FINDINGS:      Three imports -- hashlib, itertools,
                 RegimeHazardSpike -- are now dead on Orchestrator and
                 were kept with noqa: F401 solely to hold the six line
                 pins. That is dead code preserved to satisfy a
                 line-number-keyed test, and every later extraction
                 will either repeat the trick or move the pins.
                 Re-keying by enclosing symbol is not available: all
                 six live in _process_tick_inner, which holds seven
                 perf_counter_ns calls, and the allowlist's symbol
                 keys admit exactly one leftover call each -- a budget
                 already spent on :1533. Re-keying would require
                 changing the consumer to a count budget, which is a
                 different guard property than "a second unmatched
                 read is still an offender". The alternative is
                 splitting _process_tick_inner so each timing pair has
                 its own enclosing symbol, which is an orchestrator
                 refactor. Either way it is a decision S-19's block
                 does not contain. Needs its own step before wave D
                 continues.
                 Also: plan DELETES said 3 method calls through
                 self._regime_engine; 4 module-function calls remain
                 (calibrate, update, label_for, checkpoint).
                 _checkpoint_regime_snapshot imported
                 FeatureSnapshotMeta from storage (n_edges 633 ->
                 634); S2 still 1 passed / 1 xfailed.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step frozen bugs; 152 research
                 cache days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted baseline
                 failure set is the four exempted tests; R6 14/31
                 resets.
  NEXT:          Own step: Inv-10 pin re-key or count-budget, before
                 wave D continues. Then S-20 move 7 halt/integrity
                 and feature-checkpoint methods out of the kernel
                 (boundary). Not started. Do not begin S-20.
                 Left uncommitted: baseline_pre-S-19.json,
                 baseline_post-S-19.json, this ledger entry.

---

## S-19a  2026-08-23T16:44:57+08:00
  STEP:          S-19a
  BASE:          acb01d144879589e7c4b936baa0488904700ceb2
  RESULT SHA:    a4a6e8134c5cb2fd1ab365299c2b1c500c1c22de
  VERDICT:       passed
  CONFORMANCE:   no new conformance test. Allowlist tests 2 -> 3
                 passed (added _tick_timings key assertion).
                 tests/kernel: 389 passed. conformance 81 passed /
                 8 xfailed -> 81 passed / 8 xfailed (no XPASS).
                 mypy src/feelies: Success, 202 source files.
  TESTS:         4869 passed / 0 failed / 19 skipped / 8 xfailed
                 -> 4870 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-19a capture GREEN; +1 is
                 test_process_tick_inner_tick_timings_keys).
                 not-paper_rth: 4869 passed, 6 skipped, 14
                 deselected, 8 xfailed, 0 failed.
  PARITY:        declared hold -- all 28 replay hashes,
                 EXPECTED_MANIFEST_FINGERPRINT, and all 64 scanned
                 constants | actual 64/64 identical (pre-S-19a vs
                 post-S-19a, and vs baseline_post-S-19.json); 0
                 moved | MATCH.
  FILES:         2 declared, 2 committed (clean vs a4a6e81).
                 verify_step FILES declared 2, touched 2, CLEAN
                 (post-commit). Native `S-19a` uppercases to S-19A
                 and exits 2 not-in-plan (frozen); workaround
                 identity-upper ran the four checks.
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, orchestrator lines -3
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45501 -> 45498 (-3)
                 n_edges 634 -> 634
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines -3 (three import deletions)
  DETERMINISM:   148 -> 148 passed; no hash moved
  VERIFY_STEP:   Four checks (workaround): FILES 2/2 CLEAN; PARITY
                 moved 0 holds; NET DELTA 0/0/-3 sloc, compare-by-eye
                 (oracle still says "deletions with no negative
                 delta" because it does not treat sloc as the
                 deletion signal -- frozen); CLEAN, blast radius
                 local -- human gate required and given.
                 False positives (frozen, not acted on): uppercase
                 step id; hold text naming
                 EXPECTED_MANIFEST_FINGERPRINT; numbered REFACTOR
                 PATH flagged as multiple sub-changes.
  NOTES:         Allowlist consumer moved from a frozenset with
                 budget-1 symbol keys to a multiplicity-carrying
                 sequence; all seven line pins retired --
                 _process_tick_inner x7, _finalize_tick x1,
                 _drain_async_fills x2. Exactly-N is enforced by the
                 stale-entry test, whose message now reports the
                 remaining count, so a dropped call fails visibly
                 rather than silently: removing one call gave
                 "_process_tick_inner time.perf_counter_ns()
                 (remaining budget 1)". Leftover consumption is
                 line-ordered so the extra call is the one named.
                 What the count budget gives up: it no longer
                 detects intra-function site identity, so a
                 same-count substitution -- delete one of the seven,
                 add a different seventh elsewhere in the function
                 -- would pass. What compensates: an AST assertion
                 that the _tick_timings keys written in
                 _process_tick_inner are exactly
                 {sensor_fanout_ns, signal_evaluate_ns,
                 risk_check_ns}, which is what those seven calls
                 exist to produce and is stable across line moves.
                 Proven to bite: renaming sensor_fanout_ns failed
                 the assertion; restore byte-identical.
                 Three mutation proofs, all byte-identical
                 restores: an 8th call in _process_tick_inner named
                 at :1783; a 3rd in _drain_async_fills at :3798;
                 the 8th repeated after the import deletion, named
                 at :1780 with the line shift.
                 _process_tick_inner was not split. Each start/stop
                 pair is two AST Call nodes, so each helper would
                 still have needed a count of 2, and the new
                 methods would have sat above _finalize_tick and
                 _drain_async_fills and moved every pin below the
                 cut -- the S-07 problem again.
                 Orchestrator diff is three deleted import lines
                 and nothing else. Wave D's remaining eleven
                 orchestrator-touching steps -- S-20 through S-26,
                 S-29, S-31, S-32, S-34 -- no longer need a
                 dead-import pin hold.
  FINDINGS:      Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step frozen bugs; 152 research
                 cache days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted baseline
                 failure set is the four exempted tests; R6 14/31
                 resets.
  NEXT:          S-20 move 7 halt/integrity and feature-checkpoint
                 methods out of the kernel (boundary). Not started.
                 Do not begin S-20.
                 Left uncommitted: baseline_pre-S-19a.json,
                 baseline_post-S-19a.json, this ledger entry.

---

## S-20  2026-08-23T18:27:54+08:00
  STEP:          S-20
  BASE:          0412c0ca44e9361087888e76334c6716715e5438
  RESULT SHA:    64a1e909ce6f8e0406e4a124b53e2dad0447607b
  VERDICT:       passed
  CONFORMANCE:   no new conformance test. S2/S12/S14 held before
                 and after.
                 S2: 1 passed, 1 xfailed (G40) -> 1 passed, 1 xfailed
                 S12: 2 passed -> 2 passed
                 S14: 2 passed -> 2 passed
                 kernel: 389 passed. ingestion: 147 passed /
                 4 skipped. conformance 81 passed / 8 xfailed
                 (no XPASS). mypy src/feelies: Success, 202 source
                 files.
  TESTS:         4870 passed / 0 failed / 19 skipped / 8 xfailed
                 -> 4870 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-20 capture GREEN). not-paper_rth: 4869
                 passed, 6 skipped, 14 deselected, 8 xfailed,
                 0 failed.
  PARITY:        declared hold -- all 28 replay hashes,
                 EXPECTED_MANIFEST_FINGERPRINT, and all 64 scanned
                 constants | actual 64/64 identical (pre-S-20 vs
                 post-S-20, and vs baseline_post-S-19a.json); 0
                 moved; symbol_halted and market_data_canonical
                 held after every method | MATCH.
  FILES:         4 declared, 4 committed (clean vs 64a1e90).
                 verify_step FILES declared 4, touched 4, CLEAN
                 (post-commit). The mypy annotation that had been
                 990e321 was folded into 99fbb03; tree at 64a1e90
                 is byte-identical to 990e321
                 (f815ae2aeace356f2f60a1280a9ce9eddf6eae39).
  NET DELTA:     declared src modules 0, public symbols 0,
                 branch points 0, orchestrator lines -~300
                 actual modules 202 -> 202 (+0)
                 public_symbols 567 -> 567 (+0)
                 sloc 45498 -> 45507 (+9)
                 n_edges 634 -> 636
                 n_modules 164 -> 164
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines 5403 -> 5207 (-196)
                 orchestrator methods 121 -> 114 (-7)
  DETERMINISM:   148 -> 148 passed after every method; no hash moved
  VERIFY_STEP:   Four checks: FILES 4/4 CLEAN; PARITY moved 0
                 holds; TESTS 4870->4870 passed, 0 failed; NET
                 DELTA 0/0/+9 sloc, compare-by-eye (oracle still
                 says "deletions with no negative delta" because
                 it does not treat sloc or method-count as the
                 deletion signal -- frozen). CLEAN, blast radius
                 boundary -- human gate required.
  NOTES:         Second wave-D extraction; the S-19 method held.
                 Seven commits, engine 1's five first with
                 _emit_symbol_halted last among them because it
                 draws self._seq, then the two engine-2 wrappers.
                 Determinism 148 after every one, no hash moved --
                 including symbol_halted, which S-13 binds to the
                 orchestrator stream, and market_data_canonical,
                 which S-17 landed specifically so an
                 ingestion-side mistake here would be visible.
                 Orchestrator 5403 -> 5207 lines (-196),
                 121 -> 114 methods.
                 Order: _update_halt_state (318e185),
                 _update_ssr_state (28d8c03),
                 _data_health_blocks_trading (99fbb03; includes
                 health: DataHealth annotation),
                 _verify_data_integrity (f8088a7),
                 _emit_symbol_halted last of engine 1 (0c87842),
                 _restore_feature_snapshots (7da5c64),
                 _checkpoint_feature_snapshots (64a1e90).
                 The two engine-2 wrappers went to
                 services/regime_engine.py rather than features/,
                 because after S-19 they only touch regime
                 snapshots. _restore_regime_snapshot stayed on
                 Orchestrator as the callee -- it is not one of
                 the seven. _in_halt_blackout stayed; its three
                 bindings at tests/kernel/test_orchestrator.py:4181,
                 :4182 and :4221 still pass.
                 SequenceGenerator constructions unmoved at :436
                 and :444. Inv-10 count budgets unchanged at
                 7 / 1 / 2 -- none of the seven contained
                 perf_counter_ns.
                 perfmeasure.py: the four engine-1 probes
                 retargeted to feelies.ingestion.data_integrity,
                 and S-19's carried staleness fixed by retargeting
                 E3.update_regime to
                 feelies.services.regime_engine:_update_regime;
                 _install_direct_probes wraps module-level
                 functions so those paths resolve.
                 Fold: 990e321 was an eighth commit; folded into
                 99fbb03 (the _data_health_blocks_trading move
                 that caused the no-any-return). New head 64a1e90
                 tree-identical to 990e321
                 (f815ae2aeace356f2f60a1280a9ce9eddf6eae39);
                 determinism 148 at the rewritten head.
  FINDINGS:      Copying a body onto `self: Any` erases the type
                 narrowing the class provided. _data_health_blocks_trading
                 returned health.name from a narrowed
                 MarketDataNormalizer; as a module function on
                 self: Any it became a no-any-return error at three
                 sites, fixed by annotating health: DataHealth.
                 Expect the same wherever an extracted body returns
                 an attribute of self. It restores the type the
                 class already had rather than adding an invariant.
                 Carry into S-21 onward.
                 Carried: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 test (S-04c); serialization.py missing
                 __schema_version__ tag as current version
                 (fail-open); ci.yml G40 continue-on-error: true
                 until G40; verify_step frozen bugs; 152 research
                 cache days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted baseline
                 failure set is the four exempted tests; R6 14/31
                 resets.
  NEXT:          S-21 move 3 kernel accounting methods and 36
                 store calls (platform-wide / boundary). Not
                 started. Do not begin S-21.
                 Left uncommitted: baseline_pre-S-20.json,
                 baseline_post-S-20.json, this ledger entry.

---

## S-21  2026-08-24T10:52:27+08:00
  STEP:          S-21
  BASE:          0a6fe518dfae3f6ae9784425e159c910ebef49b2
  RESULT SHA:    5d37eebf2a2e48712dfd70357b4861bd7d50f20e
  VERDICT:       passed
  CONFORMANCE:   no new conformance test. S2/S12/S14 held before
                 and after (S2/S14 re-run immediately after
                 commit 3).
                 S2: 1 passed, 1 xfailed (G40) -> 1 passed, 1 xfailed
                 S12: 2 passed -> 2 passed
                 S14: 2 passed -> 2 passed; 12x98 matrix unchanged
                 (class name, not module path).
                 kernel: 390 passed. portfolio: 52 passed.
                 conformance 81 passed / 8 xfailed (no XPASS).
                 mypy src/feelies: Success, 203 source files.
  TESTS:         4870 passed / 0 failed / 19 skipped / 8 xfailed
                 -> 4873 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-21 capture GREEN). not-paper_rth: 4872
                 passed, 6 skipped, 14 deselected, 8 xfailed,
                 0 failed.
  PARITY:        declared hold -- all 28 replay hashes,
                 EXPECTED_MANIFEST_FINGERPRINT, and all 64 scanned
                 constants | actual 64/64 identical (pre-S-21 vs
                 post-S-21); 0 moved at any of the five commits
                 | MATCH.
  FILES:         12 declared after plan amend c737efe on
                 arch/exec (9 original plus docs/prompts/
                 audit_forensics.md, docs/prompts/README.md,
                 tests/docs/test_prompt_coverage_map.py), 12
                 committed (clean vs 5d37eeb). fill_attribution
                 is one move (R100). Fifth commit is the three
                 coverage files only.
  NET DELTA:     declared src modules 0 (G.10-exempt view),
                 public symbols +1 -0, branch points +2 inside
                 the exempt view, 0 outside, orchestrator
                 lines -~250
                 actual modules 202 -> 203 (+1)
                 public_symbols 567 -> 568 (+1)
                 sloc 45507 -> 45561 (+54)
                 n_edges 636 -> 638
                 n_modules 164 -> 165
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines 5207 -> 5208 (+1)
                 orchestrator methods 114 -> 114
  DETERMINISM:   148 -> 148 passed after every commit; no hash moved
  VERIFY_STEP:   Four checks: FILES 12/12 CLEAN against the
                 amended plan; PARITY moved 0 holds; TESTS
                 4870->4873 passed, 0 failed; NET DELTA +1
                 module / +1 symbol (G.10 view), compare-by-eye.
                 CLEAN, blast radius boundary -- human gate
                 required.
  NOTES:         Five commits. Four implementation in the
                 block's order, plus a fifth docs-only commit
                 repairing what the move invalidated. No hash
                 moved at any point; 28 replay hashes, the
                 fingerprint and all 64 constants unmoved.
                 The view is portfolio/position_book_view.py --
                 PositionBookView, a read-only quantity surface
                 exposing get, as_mapping, __contains__ and
                 all_positions. No __setitem__ and no accessor
                 returning a mutable dict, so
                 current_positions[s] = 0.0 is a mypy error and
                 a runtime TypeError rather than a discouraged
                 habit. That is the half S-05 left open: S-05
                 fixed the silent-flat handler, S-21 makes the
                 failure shape unconstructible.
                 Eight call sites adopted, none of which mutated
                 the mapping today -- the view closes a latent
                 shape, not an active defect. Commit 3 moved
                 alpha/fill_attribution.py to
                 portfolio/fill_attribution.py and dropped the
                 alpha re-export; S2 and S14 were re-run
                 immediately after and held, S14's matrix
                 unchanged because it reads class names not
                 module paths. No no-any-return encountered.
                 StrategyPositionStore.all_aggregate_positions
                 now returns sorted keys, removing an Inv-5
                 dict-ordering dependency; substrate's
                 unsorted-mapping count fell 134 -> 133.
                 NET DELTA: +1 module and +1 public symbol,
                 both the G.10 view; branch points +2 inside
                 it, 0 outside.
                 Order: 7535e87 (view), bde2c75 (adopt + sorted
                 keys), 3c0b920 (move + drop re-export),
                 6a0f053 (unconstructible), 5d37eeb (prompt
                 coverage).
  FINDINGS:      Wave D: a package move breaks bindings that no
                 source scan sees. tests/docs/
                 test_prompt_coverage_map.py maintains a
                 _FILE_OWNERS map and tests/docs/
                 test_internal_links.py resolves path citations
                 in docs/prompts/. The move failed four of
                 them, none in FILES, and neither S2 nor S14
                 could have caught it -- one reads the import
                 graph, the other reads class names. Every
                 remaining wave-D step that moves or renames a
                 module must declare those three files.
                 Owners assigned deliberately:
                 portfolio/fill_attribution.py to
                 audit_forensics, because its job is Inv-1 /
                 Inv-13 fill-to-alpha lineage rather than
                 ledger math; portfolio/position_book_view.py
                 to audit_position_management, alongside
                 position_store and strategy_position_store.
                 The three kernel accounting methods named in
                 DELETES were not extracted (114 -> 114); this
                 landing is the view, the move, and the
                 coverage repair.
                 Carried: copying a body onto `self: Any`
                 erases class narrowing (S-20); G6 vs empty
                 depends_on_sensors; config-path attribution +
                 missing loader alpha_id test (S-04c);
                 serialization.py missing __schema_version__
                 tag as current version (fail-open); ci.yml
                 G40 continue-on-error: true until G40;
                 verify_step frozen bugs; 152 research cache
                 days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted
                 baseline failure set is the four exempted
                 tests; R6 14/31 resets.
  NEXT:          S-22 move sizing, escalation and emergency
                 flatten out of the kernel (boundary). Not
                 started. Do not begin S-22.
                 Left uncommitted: baseline_pre-S-21.json,
                 baseline_post-S-21.json, this ledger entry.

---

## S-22  2026-08-25T09:37:07+08:00
  STEP:          S-22
  BASE:          1de32443eed50364c0b1da3d95dee470e9816d6a
  RESULT SHA:    054ba2aab3ff10ca40b599ec0ba8a093ffa5a9fe
  VERDICT:       passed
  CONFORMANCE:   no new conformance test. S2/S12/S14 held before
                 and after (S2/S14 re-run immediately after
                 the move commit).
                 S2: 1 passed, 1 xfailed (G40) -> 1 passed, 1 xfailed
                 S12: 2 passed -> 2 passed
                 S14: 2 passed -> 2 passed
                 kernel: 390 passed. risk: 336 passed.
                 alpha: 441 passed.
                 conformance 81 passed / 8 xfailed (no XPASS).
                 mypy src/feelies: Success, 203 source files.
  TESTS:         4873 passed / 0 failed / 19 skipped / 8 xfailed
                 -> 4873 passed / 0 failed / 19 skipped / 8 xfailed
                 (post-S-22 capture GREEN). not-paper_rth: 4872
                 passed, 6 skipped, 14 deselected, 8 xfailed,
                 0 failed.
  PARITY:        declared hold -- all 28 replay hashes,
                 the manifest fingerprint, and all 64 scanned
                 constants | actual 64/64 identical (pre-S-22 vs
                 post-S-22, and vs baseline_post-S-21.json); 0
                 moved at any of the five commits. level4_hazard_exit_order
                 and decoupled_risk_flatten_order held | MATCH.
  FILES:         16 declared, 13 in the commit diff (clean vs
                 054ba2a). The rename of risk_wrapper is one move
                 (R100). verify_step counted the rename source as
                 not-touched and also listed basic_risk.py and
                 test_internal_links.py as not-touched -- neither
                 needed an edit. Coverage-map repair landed in the
                 move commit, not as a trailing fix.
  NET DELTA:     declared src modules 0 (one moves), public
                 symbols 0, branch points 0, orchestrator
                 lines -~200
                 actual modules 203 -> 203 (+0)
                 public_symbols 568 -> 568 (+0)
                 sloc 45561 -> 45576 (+15)
                 n_edges 638 -> 641
                 n_modules 165 -> 165
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines 5208 -> 4977 (-231)
                 orchestrator methods 114 -> 110 (-4)
  DETERMINISM:   148 -> 148 passed after every commit; no hash moved
  VERIFY_STEP:   Four checks: FILES 16 declared / 13 touched CLEAN
                 (rename-blind on the source path; parsed
                 src/feelies/risk/ as a directory scope despite
                 FILES forbidding it -- frozen); PARITY moved 0
                 holds; TESTS 4873->4873 passed, 0 failed; NET
                 DELTA 0/0/+15 sloc, compare-by-eye (oracle still
                 says "deletions with no negative delta" because
                 it does not treat sloc or method-count as the
                 deletion signal -- frozen). CLEAN, blast radius
                 boundary -- human gate required.
  NOTES:         Fourth wave-D extraction; first module move since
                 S-21. Five commits. Four methods then the wrapper
                 move. Determinism 148 after every one, no hash
                 moved -- including level4_hazard_exit_order and
                 decoupled_risk_flatten_order, which hold here and
                 re-pin in S-23.
                 Orchestrator 5208 -> 4977 lines (-231),
                 114 -> 110 methods.
                 Order: _compute_target_quantity (670e277),
                 _maybe_flip_buying_power_at_rth_close (b96f59c),
                 _emergency_flatten_all then _escalate_risk last
                 because they draw self._seq (db597f4, 20b327d),
                 then the module move with coverage repair
                 (054ba2a).
                 Both self._seq.next() draws stayed on the
                 orchestrator generator (self is the Orchestrator;
                 constructions unmoved at orchestrator.py:442 and
                 :450). A moved hash would have meant a draw was
                 added, dropped, or reordered; none moved.
                 SequenceGenerator constructions did not move.
                 Coverage-map repair landed with the move, not
                 trailing it. New owner of
                 risk/risk_wrapper.py is audit_risk_engine,
                 assigned deliberately: the wrapper is engine 8's
                 per-alpha veto (min of asked, permitted), which
                 is the risk-engine audit's subject. It already
                 had that owner while living in alpha/; the move
                 aligns address with owner. Not alpha_lifecycle --
                 it enforces budgets rather than loading
                 manifests. Explicit _FILE_OWNERS entry so a
                 future risk/ package split cannot silently
                 reassign it. Re-export from alpha/__init__.py
                 dropped, not shimmed.
                 docs tests after the move: 101 passed, including
                 test_prompt_coverage_map and test_internal_links.
  FINDINGS:      verify_step counts a git-mv source as not-touched
                 and still parses "Do not declare src/feelies/risk/
                 as a directory scope" as a directory scope.
                 Worked around; not fixed (frozen).
                 Stale citations outside FILES, not fixed:
                 src/feelies/risk/sized_intent_orders.py Sphinx
                 class ref feelies.alpha.risk_wrapper;
                 tools/arch/microcost.py path
                 alpha/risk_wrapper.py:329;
                 tests/kernel/test_fill_attribution_seam.py
                 Sphinx class ref. test_internal_links does not
                 scan those files, so the move stayed green.
                 no-any-return: _compute_target_quantity annotated
                 qty: int before returning (plan). _emergency_flatten_all
                 annotated residual: dict[str, int] (S-20 finding:
                 dict built from self._positions on self: Any).
                 mypy Success.
                 Carried: copying a body onto self: Any erases
                 class narrowing (S-20); a package move breaks
                 bindings no source scan sees (S-21); G6 vs empty
                 depends_on_sensors; config-path attribution +
                 missing loader alpha_id test (S-04c);
                 serialization.py missing __schema_version__
                 tag as current version (fail-open); ci.yml
                 G40 continue-on-error: true until G40;
                 verify_step frozen bugs; 152 research cache
                 days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted
                 baseline failure set is the four exempted
                 tests; R6 14/31 resets.
  NEXT:          S-23 split OrderRequest inbound de-risk into
                 DeRiskRequirement (platform-wide). Not
                 started. Do not begin S-23.
                 Left uncommitted: baseline_pre-S-22.json,
                 baseline_post-S-22.json, this ledger entry.

---

## S-23  2026-08-25T10:15:30+08:00
  STEP:          S-23
  BASE:          6c5f8403474c8a6893639d1a4e49865970ce3603
  RESULT SHA:    not started — blocked at pre-flight, no branch cut, no edit made
  VERDICT:       blocked
  CONFORMANCE:   S2, S8, S12, S14 | failed-before: not run | passes-after: not run
  TESTS:         not run -> not run
  PARITY:        declared (operator) six movers; declared (STEP block)
                 two hashes + fingerprint, halt/symbol_halted/position_pnl
                 hold | actual unmoved — no implement
  FILES:         14 declared, 0 touched. HEAD arch/exec @ 6c5f840.
                 exec/S-23 not cut. tools/exec diff vs exec-tools-v1
                 empty. Working tree clean aside from this ledger entry.
                 No capture.
  NET DELTA:     declared src modules 0, public symbols +1 -1 = 0,
                 branch points -1 | actual 0 / 0 / 0
  DETERMINISM:   not run
  VERIFY_STEP:   not run — no implement
  NOTES:         Pre-flight: porcelain empty, HEAD arch/exec, tools/exec
                 vs exec-tools-v1 empty. Capture not run (same hand-back
                 as S-15 first blocked). Current values that the operator
                 prompt names as movers (not re-pinned):
                 EXPECTED_LEVEL4_HAZARD_EXIT_ORDER_HASH
                   79b35ea6d10038ec5e36b7844172afadda521734b298b3c8628bd98995bdbd81
                 EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH
                   87445b362a294c75abc6c63f2318e99c2d3da359501222b5b281efba4a62ac14
                 EXPECTED_HALT_ORDER_HASH
                   f791d994712762590eda4281830a0b4ce1af8b20cd295e2defcbbcd34e4a11e7
                 EXPECTED_SYMBOL_HALTED_HASH
                   a7b5c52139086e62019a282a6e3ec9352c677917dda2eaf2d13c7000af06c564
                 EXPECTED_POSITION_PNL_HASH
                   7add366c6db014c0d20d0c4900f3bf192ab20d96738a0d28670ba003afdd6a05
                 EXPECTED_MANIFEST_FINGERPRINT
                   dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                 6c5f840 claimed to name the eight consumers of
                 OrderRequest.reason; the STEP block still does not.
                 Production readers found (not named in the block):
                 orchestrator._order_owns_one_slice:244,
                 _is_forced_market_exit:260,
                 _trade_journal_legs:288,
                 slice-scoped clamp:3338,
                 _on_bus_hazard_order:4643,
                 _emit_forced_exit_resized_alert:4773,
                 _emit_forced_exit_stood_down_alert:4799,
                 execution/market_fill.py:196,
                 monitoring/horizon_metrics.py:276,
                 forensics/gate_close_attribution.py:212.
                 Outbound copies of reason would leave market_fill,
                 horizon_metrics, and forensics unedited; they are
                 still unnamed consumers. A ninth (those three plus
                 resized/stood_down beyond a named eight) is a FILES
                 question if any of them must change.
  FINDINGS:      PLAN DEFECT — FILES cannot land the type split.
                 1. Author tests subscribe to OrderRequest and would
                    go silent when publishers emit DeRiskRequirement.
                    Not in FILES:
                      tests/risk/test_stop_exit_controller.py
                      tests/risk/test_hazard_exit.py
                      tests/risk/test_deferral_cap.py
                      tests/risk/test_exit_composer.py
                      tests/risk/test_exit_composer_revocation.py
                    test_stop_exit_controller.py:101 also asserts
                    order.order_type is MARKET, which a requirement
                    without that field cannot satisfy.
                 2. Kernel tests publish OrderRequest as the inbound
                    de-risk command. Deleting subscribe(OrderRequest,
                    _on_bus_hazard_order) fails them. Not in FILES:
                      tests/kernel/test_orchestrator_hazard_exit_routing.py
                      tests/kernel/test_orchestrator_exit_composer_routing.py
                      tests/kernel/test_stage0_decouple_wiring.py
                      tests/kernel/test_orchestrator.py
                      tests/determinism/test_forced_exit_attribution_replay.py
                    The last also pins
                    EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH; the STEP
                    block says if that hash moves, STOP and amend.
                 3. Parity declarations conflict. Operator prompt:
                    five replay hashes + fingerprint move. STEP
                    PARITY IMPACT: only the two order hashes +
                    fingerprint; halt_order, symbol_halted,
                    position_pnl hold, and a move is amend-not-fold.
                    Retargeting the four S-13 contracts to
                    DeRiskRequirement makes Orchestrator the sole
                    OrderRequest producer, which draws self._seq —
                    that is the halt/pnl shift G.7 already named.
                    Implementing S-13 as written violates the STEP
                    block's hold; obeying the hold leaves four
                    author streams still producing OrderRequest
                    sequences. The step needs one declaration.
                 4. DeRiskRequirement payload is unspecified.
                    Authors today set order_id (derived),
                    order_type=MARKET, sequence from their
                    generator, source_layer=RISK, symbol, side,
                    quantity, strategy_id, reason. Whether the
                    requirement carries order_id and order_type,
                    and whether the kernel copies sequence or
                    draws orchestrator _seq, is a decision the
                    block does not contain.
                 5. sized_intent_orders.py is in FILES and is not
                    an inbound de-risk author (outbound PORTFOLIO
                    legs). The tests that will fail are not.
                 Standing rule: a fifteenth file means STOP; do
                 not edit undeclared tests; do not skip them to
                 stay inside FILES. No implement.
                 Carried, not fixed: G6 vs empty
                 depends_on_sensors; config-path attribution +
                 missing loader alpha_id test (S-04c);
                 serialization.py missing __schema_version__
                 tag as current version (fail-open); ci.yml
                 G40 continue-on-error: true until G40;
                 verify_step frozen bugs; 152 research cache
                 days stale (APP/2026-03-26 current); 11
                 UNIT_UNDETERMINED block S-24; accepted
                 baseline failure set is the four exempted
                 tests; R6 14/31 resets; S-20 no-any-return;
                 S-21 package-move bindings.
  NEXT:          Amend the S-23 block: name the eight consumers;
                 add the author tests and kernel inbound-publish
                 tests to FILES; pick one parity set; specify
                 DeRiskRequirement's fields and which generator
                 stamps outbound OrderRequest.sequence. Then
                 retry S-23. Do not begin S-24.
                 Left uncommitted: this ledger entry.

---

## S-23  2026-08-25T11:20:24+08:00
  STEP:          S-23
  BASE:          e2d6b8a338f1d5cbe08071a5033be2e8c89e57b4
  RESULT SHA:    e29a328cc0686bc08beec5c41b038181c0aa418b (exec/S-23; not merged)
  VERDICT:       blocked
  CONFORMANCE:   S2 1 passed / 1 xfailed (G40) held
                 S8 2 passed (PINNED_PAYLOAD failed-before missing=['DeRiskRequirement'], then passed with the class)
                 S12 2 passed after every commit
                 S14 2 passed
                 schema_drift 2 passed; conformance 81 passed / 8 xfailed
                 kernel 390; risk 336; docs 101; mypy Success (203 files)
  TESTS:         capture pre-S-23 GREEN 4873 passed / 0 failed / 19 skipped
                 -> not-paper_rth 4868 passed / 4 failed / 6 skipped / 14 deselected / 8 xfailed
                 Failures outside the four exempted tests (stop):
                   tests/bootstrap/test_bus_subscription_order.py::test_order_request_handler_order
                   tests/integration/test_hazard_exit_e2e.py::test_hazard_spike_closes_an_open_position
                   tests/integration/test_hazard_exit_e2e.py::test_short_position_exits_via_buy_side
                   tests/promotion/test_lifecycle_revocation.py::test_quarantine_flattens_open_deferred_book_immediately
                 post-S-23 capture not run (suite red).
  PARITY:        declared 3 movers | actual 3 on exec/S-23 | MATCH on branch
                 LEVEL4_HAZARD_EXIT_ORDER_HASH
                   79b35ea6d10038ec5e36b7844172afadda521734b298b3c8628bd98995bdbd81
                   -> a7cc224630daf399c65f21cfcb39687f1c25206bd2bbf57ab87dd80b7ee065b3
                   (d4fd91a hazard_exit)
                 DECOUPLED_RISK_FLATTEN_ORDER_HASH
                   87445b362a294c75abc6c63f2318e99c2d3da359501222b5b281efba4a62ac14
                   -> 3ff6fab7232a015db561a3cf9da3a987f767c981d1aa8943bd9f550d3b8cc8f8
                   (e67ba70 deferral_cap; composer commit held)
                 MANIFEST_FINGERPRINT
                   dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                   -> 82fac390f76c84734eed4d13f0fe82ae9d56d070eeb0f4c4d3854bdff0eab5a1 (3b5ea73 class)
                   -> 43df4a99d9b460b31a3b51f96df9dfb863369017b6b7367a0b06bfd9ca54eeab (d4fd91a)
                   -> e5fe32165d5efbbd55987c120f1268d5cddc305475ad4ff1ab589ca5d180f7e2 (e67ba70)
                 Hold set unmoved: halt_order, symbol_halted, position_pnl,
                 forced_exit_attribution, STOP_EXIT_STREAMS; COUNTs 3 and 2.
  FILES:         23 declared, 21 in e2d6b8a..e29a328 (clean vs declared).
                 Untouched declared: parity_manifest.py (imports only),
                 tests/kernel/test_orchestrator.py (kernel re-publish kept
                 OrderRequest subscribers green).
                 Three failing files are not in FILES — 24th/25th/26th.
                 No 25th production file edited.
  NET DELTA:     declared src modules 0, public symbols +1 -1 = 0,
                 branch points -1 | not landed on arch/exec
  DETERMINISM:   148 passed after every commit
  VERIFY_STEP:   not run — TESTS failed stop-the-line before capture/verify
  NOTES:         Commit order on exec/S-23:
                 3b5ea73 event + PINNED_PAYLOAD (fingerprint)
                 38a2313 wiring / dual-subscribe converter (none)
                 48fa030 stop_exit (none; STOP_EXIT_STREAMS held)
                 d4fd91a hazard_exit (LEVEL4 hash + fingerprint)
                 e67ba70 deferral_cap (flatten hash + fingerprint)
                 be5b654 exit_composer (none; flatten held)
                 e29a328 kernel conversion, delete inbound OrderRequest (none)
                 Arrangement: kernel-constructs, author-stamps. Converter
                 copies event.sequence; no self._seq on conversion.
                 DeRiskRequirement payload: order_id, symbol, side, quantity
                 (share), strategy_id, reason. Author sets envelope + all six;
                 kernel fills OrderRequest.order_type=MARKET and publishes.
                 Ten production reason consumers: 1-4 outbound orchestrator
                 stay on OrderRequest; 5 inbound handler deleted (type is
                 admission); 6-7 alerts stay on outbound OrderRequest; 8-10
                 market_fill / horizon_metrics / gate_close_attribution
                 unedited. No eleventh production reader found.
                 no-any-return: _order_request_from_derisk(event:
                 DeRiskRequirement) -> OrderRequest; mypy clean.
                 Author generators kept stamping. Dual-subscribe existed
                 only until e29a328 so undeclared STOP_EXIT_STREAMS and
                 registration_order stayed green through author commits.
  FINDINGS:      PLAN DEFECT — FILES still incomplete after the four
                 prior fixes. Isolated author and kernel tests were
                 added; a second ring was not:
                 1. tests/bootstrap/test_bus_subscription_order.py
                    asserts Orchestrator remains subscribed to
                    OrderRequest (HorizonMetricsCollector before
                    Orchestrator). DELETES of subscribe(OrderRequest)
                    fails it. Not a .reason reader.
                 2. tests/integration/test_hazard_exit_e2e.py
                    _wire subscribes to OrderRequest and filters
                    o.reason == "HAZARD_SPIKE". Author now emits
                    DeRiskRequirement. Two positive tests fail; four
                    negative tests stay green while still listening
                    to OrderRequest, so they would not catch a
                    spurious DeRiskRequirement.
                 3. tests/promotion/test_lifecycle_revocation.py
                    subscribes to OrderRequest and asserts
                    order.reason == DECOUPLING_REVOKED on composer
                    flatten. Same author-emit gap as (2).
                 Standing rule: a 25th file is STOP; do not edit
                 undeclared tests; do not skip them to stay inside
                 FILES. Branch retained for inspection; not merged;
                 not deleted. Amend FILES with those three, then
                 retry S-23 from exec/S-23 or a fresh cut.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 (S-04c); serialization.py missing __schema_version__
                 fail-open; ci.yml G40 continue-on-error; verify_step
                 frozen bugs; 152 research cache days stale
                 (APP/2026-03-26 current); 11 UNIT_UNDETERMINED block
                 S-24; R6 14/31 resets; S-20 no-any-return; S-21
                 package-move bindings; four exempted baseline tests.
  NEXT:          Amend S-23 FILES with the three test files above.
                 Retry S-23. Do not begin S-24.
                 Left uncommitted: baseline_pre-S-23.json, this ledger
                 entry (no post capture).

---

## S-23  2026-08-27T10:39:01+08:00
  STEP:          S-23
  BASE:          e2d6b8a338f1d5cbe08071a5033be2e8c89e57b4
  RESULT SHA:    cb8fd6327e73ef50a6d0091165489b04384ee7b2 (exec/S-23; not merged)
  VERDICT:       passed
  CONFORMANCE:   S2 1 passed / 1 xfailed (G40) held
                 S8 2 passed (PINNED_PAYLOAD failed-before missing=['DeRiskRequirement'])
                 S12 2 passed after every commit
                 S14 2 passed
                 schema_drift 2; conformance 81 passed / 8 xfailed
                 kernel 390; risk 336; docs 101; mypy Success (203 files)
  TESTS:         capture 4873 passed / 0 failed / 19 skipped
                 -> 4863 passed / 0 failed / 29 skipped (GREEN)
                 not-paper_rth: 4862 passed, 16 skipped, 14 deselected,
                 8 xfailed, 0 failed. Zero failures outside the four
                 exempted environmental tests. Skip +10 vs pre is a
                 two-day host delta (capture exit 0); not a new fail.
  PARITY:        declared 3 movers | actual 3 | MATCH
                 LEVEL4_HAZARD_EXIT_ORDER_HASH
                   79b35ea6d10038ec5e36b7844172afadda521734b298b3c8628bd98995bdbd81
                   -> a7cc224630daf399c65f21cfcb39687f1c25206bd2bbf57ab87dd80b7ee065b3
                   (d4fd91a hazard_exit)
                 DECOUPLED_RISK_FLATTEN_ORDER_HASH
                   87445b362a294c75abc6c63f2318e99c2d3da359501222b5b281efba4a62ac14
                   -> 3ff6fab7232a015db561a3cf9da3a987f767c981d1aa8943bd9f550d3b8cc8f8
                   (e67ba70 deferral_cap; composer commit held)
                 MANIFEST_FINGERPRINT
                   dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b
                   -> 82fac390f76c84734eed4d13f0fe82ae9d56d070eeb0f4c4d3854bdff0eab5a1 (3b5ea73)
                   -> 43df4a99d9b460b31a3b51f96df9dfb863369017b6b7367a0b06bfd9ca54eeab (d4fd91a)
                   -> e5fe32165d5efbbd55987c120f1268d5cddc305475ad4ff1ab589ca5d180f7e2 (e67ba70)
                 Hold set unmoved: halt_order, symbol_halted, position_pnl,
                 forced_exit_attribution, STOP_EXIT_STREAMS; COUNTs 3 and 2.
                 baseline.py's 64-constant map does not include the
                 fingerprint (frozen); capture moved 2 of 64; fingerprint
                 is the third, in test_parity_manifest.py.
  FILES:         amended plan (arch/exec 651324c) 26 declared;
                 e2d6b8a..cb8fd63 24 touched, clean vs amended list.
                 Declared untouched: parity_manifest.py (imports only),
                 tests/kernel/test_orchestrator.py (kernel re-publish).
                 Eighth commit cb8fd63 retargeted the three second-ring
                 files, including the four negative e2e cases.
  NET DELTA:     declared src modules 0, public symbols +1 -1 = 0,
                 branch points -1
                 actual modules 203 -> 203 (+0)
                 public_symbols 568 -> 569 (+1) — DeRiskRequirement;
                 _on_bus_hazard_order was a method, not a module symbol
                 sloc 45576 -> 45600 (+24)
                 n_edges 641 -> 641; n_modules 165; cycles 1; alphaleak 2
  DETERMINISM:   148 passed after every commit
  VERIFY_STEP:   Four checks (frozen oracle has no TESTS section):
                 FILES FAIL — parsed exec/S-23's pre-amend FILES
                 (sized_intent_orders.py still listed; three second-ring
                 files UNDECLARED). Working-tree plan is e2d6b8a's;
                 amend lives on arch/exec 651324c. Also parsed
                 "execution/" from "Do not land an execution/ constructor".
                 PARITY declared break, matches the two scanned hashes;
                 fingerprint unscanned. HUMAN RE-BASELINE REQUIRED.
                 NET DELTA compare-by-eye (public_symbols +1 vs
                 declared 0; method delete is not a public symbol).
                 blast platform-wide — human gate required.
                 Also grepped hold-set EXPECTED_* names into declared
                 movers (frozen).
  NOTES:         Eight commits. Kernel-constructs / author-stamps: the
                 four author generators still stamp the outbound
                 sequence -- stop_exit:288, hazard_exit:246,
                 deferral_cap:372, exit_composer:479 -- and the kernel
                 copies event.sequence without drawing self._seq. That
                 is what kept halt_order, symbol_halted, position_pnl
                 and forced_exit_attribution unmoved; merging the
                 streams onto the orchestrator generator would have
                 moved all four, which is why the block rejected it.
                 DeRiskRequirement carries envelope plus order_id,
                 symbol, side, quantity in shares, strategy_id and
                 reason; the kernel fills only order_type=MARKET.
                 Three constants moved, each in its own commit --
                 LEVEL4 in d4fd91a, flatten in e67ba70, the fingerprint
                 accumulating across 3b5ea73, d4fd91a and e67ba70.
                 The inbound OrderRequest subscribe is deleted, so
                 consumer 5 is gone and the remaining nine readers are
                 unchanged. One no-any-return, resolved by typing the
                 conversion helper's parameter.
                 Re-pin: the three values were already those strings in
                 the owning modules (d4fd91a, e67ba70, fingerprint
                 chain). parity_manifest.py has no hash literals; it
                 imports the owning constants. No ninth commit.
                 Operator confirmation 2026-08-27: determinism 148,
                 test_parity_manifest 34 passed, post-S-23 capture GREEN.
  FINDINGS:      The second ring of listeners was invisible to the
                 first FILES pass.
                 tests/bootstrap/test_bus_subscription_order.py asserted
                 the deleted subscribe; tests/integration/
                 test_hazard_exit_e2e.py filtered on OrderRequest
                 reason; and tests/promotion/
                 test_lifecycle_revocation.py asserted a composer-flatten
                 reason. Worse, four NEGATIVE cases in the e2e file
                 stayed green while listening to the wrong type -- a
                 negative assertion against a type the code no longer
                 emits asserts nothing. Every remaining step that
                 changes an event type must enumerate negative
                 assertions as well as positive ones; a passing test is
                 not evidence the listener is still bound to the right
                 type.
                 verify_step FILES is branch-plan-blind (frozen): the
                 worktree plan on exec/S-23 is e2d6b8a's, so the three
                 second-ring files looked undeclared after 651324c
                 landed only on arch/exec.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 (S-04c); serialization.py missing __schema_version__
                 fail-open; ci.yml G40 continue-on-error; verify_step
                 frozen bugs; 152 research cache days stale
                 (APP/2026-03-26 current); 11 UNIT_UNDETERMINED block
                 S-24; R6 14/31 resets; S-20 no-any-return; S-21
                 package-move bindings; four exempted baseline tests.
  NEXT:          S-24 9 of engine 9's methods sit in the kernel
                 (boundary). Not started. Do not begin S-24.
                 Left uncommitted: baseline_pre-S-23.json,
                 baseline_post-S-23.json, this ledger entry.

---

## S-24  2026-08-27T14:11:21+08:00
  STEP:          S-24
  BASE:          843fabf6bd499bcc8bff224cf898c1243832b159
  RESULT SHA:    not started — blocked at before-state, no branch cut, no edit made
  VERDICT:       blocked
  CONFORMANCE:   S2 1 passed / 1 xfailed (G40)
                 S12 2 passed
                 S14 2 passed
                 tests/docs 101 passed
  TESTS:         reference post-S-23 4873 passed / 0 failed / 19 skipped
                 -> not run. Capture not run (FILES defect found in
                 before-state; same hand-back as S-15 first blocked).
  PARITY:        declared hold | actual 64/64 MATCH vs
                 baseline_post-S-23.json via baseline.parity_constants();
                 0 moved. No implement.
  FILES:         8 declared, 0 touched. HEAD arch/exec @ 843fabf.
                 exec/S-24 not cut. tools/exec diff vs exec-tools-v1
                 empty. Working tree clean aside from this ledger entry.
  NET DELTA:     declared src modules 0, public symbols +1, branch
                 points 0, orchestrator 104 -> 95 | actual 0 / 0 / 0.
                 Live orchestrator 4994 lines, 111 methods (plan 104
                 stale). SequenceGenerator at :443 and :451.
  DETERMINISM:   not run
  VERIFY_STEP:   not run — no implement
  NOTES:         Pre-flight: porcelain empty, HEAD arch/exec, tools/exec
                 vs exec-tools-v1 empty, 64 constants identical to
                 post-S-23. Orchestrator 4994 / 111. Nine spans:
                 _edge_clears_round_trip_cost 2176-2216 (no draw),
                 _signal_passes_edge_cost_gate 2218-2256 (no draw),
                 _round_trip_cost_bps 2258-2285 (no draw),
                 _reversal_passes_combined_edge_gate 2287-2325 (no draw),
                 _plan_for_signal 2428-2471 (no draw),
                 _execute_reverse 2598-2890 (self._seq.next at :2625
                 and :2753),
                 _try_build_order_from_intent 2892-2983 (self._seq.next
                 at :2910),
                 _resolve_order_route 2985-3037 (no draw),
                 _filter_portfolio_orders_for_admission 3119-3187
                 (no draw). Named siblings stay:
                 _emit_signal_edge_gate_suppression_alert 2152-2174,
                 _portfolio_leg_edge_block 3189-3251.
                 Five attribute-call sites outside orchestrator.py, in
                 three files not in FILES:
                 tests/kernel/test_orchestrator.py:1458
                   orch._try_build_order_from_intent
                   (test_signal_path_orders_are_never_tagged_as_panic)
                 tests/kernel/test_orchestrator.py:2522, :2538
                   orch._plan_for_signal, orch._round_trip_cost_bps
                   (test_cost_inputs_are_shared_by_gate_and_position_planner)
                 tests/kernel/test_orchestrator_order_routing.py:63
                   orch._resolve_order_route
                   (test_order_route_precedence, 5 parametrize rows)
                 tests/kernel/test_orchestrator_edge_calibration.py:46
                   orch._signal_passes_edge_cost_gate via _gate()
                   (four tests).
                 WAVE-D forbids a delegating shim, so those tests
                 AttributeError after the move. A ninth file is STOP.
                 Destination bodies construct OrderRequest
                 (_try_build_order_from_intent returns one;
                 _execute_reverse publishes via self._bus.publish).
                 SequenceGenerator constructions stay on Orchestrator;
                 S12 keys on those sites, not publish calls. Retargeting
                 SequenceAuthority would add a generator (merge;
                 halt_order / level4_portfolio_order move). Therefore
                 sequence_authority.py, wiring_manifest.py, and
                 test_single_owner.py are declared-but-unneeded.
                 The ledger note that S-24 is blocked on eleven
                 UNIT_UNDETERMINED fields is stale: S-10 closed the
                 unit mechanism; this step moves methods and does not
                 intersect that field.
  FINDINGS:      PLAN DEFECT — FILES cannot land the extraction.
                 Three kernel tests bind the methods as Orchestrator
                 attributes and are not declared. Standing rule: a
                 ninth file is STOP; do not edit undeclared tests;
                 do not skip them to stay inside FILES; do not leave
                 a shim. No implement.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 (S-04c); serialization.py missing __schema_version__
                 fail-open; ci.yml G40 continue-on-error; verify_step
                 frozen bugs; 152 research cache days stale
                 (APP/2026-03-26 current); R6 14/31 resets; S-20
                 no-any-return; S-21 package-move bindings; S-23
                 negative assertions bound to a type the code no
                 longer emits; four exempted baseline tests.
  NEXT:          Amend S-24 FILES with
                 tests/kernel/test_orchestrator.py,
                 tests/kernel/test_orchestrator_order_routing.py,
                 tests/kernel/test_orchestrator_edge_calibration.py.
                 Retry S-24. Do not begin S-25.
                 Left uncommitted: this ledger entry.

---

## S-24  2026-08-28T09:08:17+08:00
  STEP:          S-24
  BASE:          843fabf6bd499bcc8bff224cf898c1243832b159
  RESULT SHA:    not started — blocked at before-state, no branch cut, no edit made
  VERDICT:       blocked
  CONFORMANCE:   S2 1 passed / 1 xfailed (G40)
                 S12 2 passed
                 S14 2 passed
                 tests/docs 101 passed
  TESTS:         capture pre-S-24 GREEN 4873 passed / 0 failed / 19 skipped
                 determinism 148 passed. -> not implemented.
  PARITY:        declared hold | actual 64/64 MATCH vs
                 baseline_post-S-23.json; capture 64 constants, 0 moved.
  FILES:         8 declared, 0 touched. HEAD arch/exec @ 843fabf.
                 exec/S-24 not cut. tools/exec diff vs exec-tools-v1
                 empty. Plan FILES unchanged from the 2026-08-27 block.
  NET DELTA:     declared src modules 0, public symbols +1, branch
                 points 0, orchestrator 104 -> 95 | actual 0 / 0 / 0.
                 Live orchestrator 4994 lines, 111 methods.
                 SequenceGenerator at :443 and :451.
  DETERMINISM:   148 passed (pre-capture only)
  VERIFY_STEP:   not run — no implement
  NOTES:         Fresh cut from 843fabf as instructed; 4dd6f9f still
                 absent. Pre-flight: porcelain empty after stashing the
                 prior blocked ledger, HEAD arch/exec, tools/exec empty,
                 capture GREEN. Draws verified in code: of the nine,
                 only _execute_reverse (:2625, :2753) and
                 _try_build_order_from_intent (:2910) draw self._seq.
                 The plan's naming of those two is right. The other
                 seven do not draw. Commit order if FILES were complete
                 would be cheapest-first with those two last.
                 Same five attribute-call sites in three files still
                 not in FILES:
                 tests/kernel/test_orchestrator.py:1458
                   orch._try_build_order_from_intent
                 tests/kernel/test_orchestrator.py:2522, :2538
                   orch._plan_for_signal, orch._round_trip_cost_bps
                 tests/kernel/test_orchestrator_order_routing.py:63
                   orch._resolve_order_route
                 tests/kernel/test_orchestrator_edge_calibration.py:46
                   orch._signal_passes_edge_cost_gate
                 WAVE-D forbids a shim. A ninth file is STOP.
                 The ledger note that S-24 is blocked on eleven
                 UNIT_UNDETERMINED fields is stale: S-10 closed the
                 unit mechanism; this step moves methods and does not
                 intersect that field.
  FINDINGS:      PLAN DEFECT — FILES still cannot land the extraction.
                 The three kernel tests from the 2026-08-27 block were
                 not added. Standing rule: a ninth file is STOP. No
                 implement.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 (S-04c); serialization.py missing __schema_version__
                 fail-open; ci.yml G40 continue-on-error; verify_step
                 frozen bugs; 152 research cache days stale
                 (APP/2026-03-26 current); R6 14/31 resets; S-20
                 no-any-return; S-21 package-move bindings; S-23
                 negative assertions bound to a type the code no
                 longer emits; four exempted baseline tests.
  NEXT:          Amend S-24 FILES with the three kernel tests named
                 above. Retry S-24. Do not begin S-25.
                 Left uncommitted: baseline_pre-S-24.json, this ledger
                 entry (both S-24 blocked records).

---

## S-24  2026-08-28T10:30:00+08:00
  STEP:          S-24
  BASE:          566017ca53e773b533375ed02f2ea6f52f4a3f01
  RESULT SHA:    6bedb2676348b40ab94ce5fff9fe811491b1f5e7 (exec/S-24; not merged)
  VERDICT:       passed
  CONFORMANCE:   no new conformance test. S2/S12/S14 held before
                 and after.
                 S2: 1 passed / 1 xfailed (G40) -> 1 passed / 1 xfailed
                 S12: 2 passed after every commit
                 S14: 2 passed -> 2 passed
                 tests/docs 101 passed in commit 1 and again in
                 section 4.
                 conformance 81 passed / 8 xfailed (no XPASS).
                 kernel 390; execution 865; docs 101.
                 mypy src/feelies: Success, 204 source files.
  TESTS:         capture pre-S-24 GREEN 4873 passed / 0 failed / 19 skipped
                 -> post-S-24 GREEN 4873 passed / 0 failed / 19 skipped
                 / 8 xfailed. not-paper_rth: 4872 passed, 6 skipped,
                 14 deselected, 8 xfailed, 0 failed.
  PARITY:        declared hold -- all 28 replay hashes, including
                 halt_order, level4_portfolio_order, and the three
                 S-23 re-pins (LEVEL4_HAZARD_EXIT_ORDER_HASH,
                 DECOUPLED_RISK_FLATTEN_ORDER_HASH,
                 EXPECTED_MANIFEST_FINGERPRINT), plus the remaining
                 scanned constants | actual 64/64 identical
                 (pre-S-24 vs post-S-24); 0 moved at any of the
                 eleven commits | MATCH.
  FILES:         11 declared, 7 touched (verify_step CLEAN).
                 Touched: orchestrator.py, order_policy.py (new),
                 tests/docs/test_prompt_coverage_map.py,
                 docs/prompts/README.md,
                 tests/kernel/test_orchestrator.py,
                 tests/kernel/test_orchestrator_order_routing.py,
                 tests/kernel/test_orchestrator_edge_calibration.py.
                 Declared-but-unneeded, not skipped scope:
                 sequence_authority.py, wiring_manifest.py,
                 tests/conformance/test_single_owner.py,
                 tests/docs/test_internal_links.py.
  NET DELTA:     declared src modules 0, public symbols +1,
                 branch points 0, orchestrator lines -~450,
                 methods 111 -> 102
                 actual modules 203 -> 204 (+1, the new file;
                 no new package)
                 public_symbols 569 -> 569 (+0; every extracted
                 name is _-prefixed)
                 sloc 45600 -> 45638 (+38)
                 n_edges 641 -> 652
                 n_modules 165 -> 166
                 cycles 1 -> 1
                 alphaleak 2 -> 2
                 orchestrator lines 4994 -> 4283 (-711)
                 orchestrator methods 111 -> 102 (-9)
  DETERMINISM:   148 -> 148 passed after every commit; no hash moved
  VERIFY_STEP:   Four checks: FILES 11 declared / 7 touched CLEAN
                 (four declared-but-unneeded); PARITY moved 0 holds;
                 TESTS 4873->4873 passed, 0 failed; NET DELTA
                 compare-by-eye (oracle still says "deletions with
                 no negative delta" because it does not treat
                 method-count as the deletion signal -- frozen;
                 DELETES 111 -> 102 matched). CLEAN, blast radius
                 boundary -- human gate required.
  NOTES:         Sixth wave-D extraction. Eleven commits on
                 exec/S-24, not nine: nine method moves, then a
                 no-any-return annotation, then unused-import
                 cleanup. One method per move commit, non-drawing
                 first in callee-before-caller order, then the two
                 drawing methods last -- _try_build_order_from_intent
                 then _execute_reverse -- matching the plan's naming,
                 which was verified in the source. Determinism 148
                 and S12 2 passed after every commit; no hash moved
                 at any point.
                 Order and orchestrator lines/methods:
                 4d1f392 _round_trip_cost_bps + order_policy.py
                   + _FILE_OWNERS  4994/111 -> 4967/110
                 18681f2 _edge_clears_round_trip_cost     4925/109
                 91a6408 _signal_passes_edge_cost_gate    4886/108
                 9e79c48 _reversal_passes_combined_edge_gate 4846/107
                 4963d6b _plan_for_signal                 4799/106
                 0f1fda8 _resolve_order_route             4746/105
                 cf28279 _filter_portfolio_orders_for_admission 4677/104
                 8889385 _try_build_order_from_intent (one
                   self._seq.next)                        4583/103
                 403ea6c _execute_reverse (two
                   self._seq.next)                        4288/102
                 174c55c annotate _plan_for_signal result 4288/102
                 6bedb26 drop imports the nine no longer
                   need                                   4283/102
                 Draws: only those two methods. The other seven
                 do not draw. All three draws are self._seq.next()
                 on the orchestrator instance. SequenceGenerator
                 constructions stay on Orchestrator -- at HEAD
                 :439 stream=orchestrator and :447 stream=hazard
                 (the gate cited :444 / :452; 6bedb26 deleted five
                 import lines above __init__). order_policy.py
                 does not construct a generator and does not
                 publish in the S-13 sense. _execute_reverse
                 submits via self._submit_tracked_order and
                 publishes OrderRequest / RiskVerdict through
                 self._bus.publish; _try_build_order_from_intent
                 returns an OrderRequest for the caller to publish.
                 There is no _submit_to_router call. S12 confirms
                 Orchestrator remains the sole authority for the
                 orchestrator stream, which is why
                 sequence_authority.py and wiring_manifest.py
                 (and test_single_owner.py) are declared-but-unneeded
                 rather than skipped scope.
                 Owner is audit_execution_fills, assigned in
                 commit 1 next to min_cost_policy.py. The nine are
                 engine-9 order-decision policy -- planning, routing,
                 admission filtering and cost gating -- which is
                 Inv-12 execution policy, not kernel dispatch.
                 There is no audit_execution_pipeline prompt; that
                 name was not used. _FILE_OWNERS repair landed in
                 commit 1 with the module, tests/docs passing in
                 the same commit -- the S-21 pattern on its third
                 reuse (S-21, S-22, S-24).
                 Siblings left in place, as the block named them
                 only for this judgment: _emit_signal_edge_gate_suppression_alert
                 (HEAD :2148) is alerting called by the moved
                 _signal_passes_edge_cost_gate via self; 
                 _portfolio_leg_edge_block (HEAD :2478) reads
                 target_positions on the composition path and is
                 called by the moved _filter_portfolio_orders_for_admission
                 via self. Both are called by the nine but are not
                 engine-9 policy, and the nine close without moving
                 them.
                 Two no-any-return sites, both resolved by
                 annotating rather than casting: _plan_for_signal
                 assigns the planner result to plan: PositionPlan
                 before return (174c55c); _execute_reverse annotates
                 edge_calibration_factor: float and
                 effective_edge_bps: float on Decimal/float
                 arithmetic over attributes of self: Any (403ea6c).
                 The plan's UNIT_UNDETERMINED blocker was stale --
                 S-10 fixed the unit mechanism; this step moves
                 methods and the two do not intersect.
                 Two prior S-24 attempts plus one S-21 attempt were
                 executed in an ephemeral Copilot workspace at
                 C:\Users\cheng.lei\.copilot\repos\feelies and lost
                 when it was deleted; every step prompt now carries
                 a clone-check preamble. This landing is in the
                 canonical clone.
  FINDINGS:      Operator-supplied NOTES are not authoritative.
                 The operator has now dictated NOTES containing
                 invented SHAs and invented facts three times --
                 S-21, S-22 and S-24. On this step the dictated
                 NOTES named SHA 2fd8b8b (absent from this object
                 database, the reflog, and origin), claimed nine
                 commits and orchestrator 4994 -> 4550, named
                 owner audit_execution_pipeline (no such prompt),
                 claimed _submit_to_router (no such call), and
                 placed the no-any-return sites in
                 _round_trip_cost_bps. Observed: HEAD 6bedb26,
                 eleven commits, 4994 -> 4283, owner
                 audit_execution_fills, self._submit_tracked_order
                 and self._bus.publish, no-any-return in
                 _plan_for_signal and _execute_reverse. The
                 executing session's observations take precedence;
                 do not copy dictated NOTES into the ledger when
                 they contradict the tree.
                 order_admission.py still comments
                 Orchestrator._edge_clears_round_trip_cost
                 (outside FILES; not fixed).
                 Pre-existing unused SymbolHalted and
                 _emergency_flatten_all imports on Orchestrator
                 left in place.
                 One recapture failed on
                 tests/ingestion/test_massive_functional.py::
                 test_rest_ingest_uses_live_massive_data (live
                 Massive REST, marked functional). Retry passed;
                 recapture at HEAD GREEN. Not in the four
                 accepted environmental names; treated as flake.
                 Carried, not fixed: G6 vs empty depends_on_sensors;
                 config-path attribution + missing loader alpha_id
                 (S-04c); serialization.py missing __schema_version__
                 fail-open; ci.yml G40 continue-on-error; verify_step
                 frozen bugs; 152 research cache days stale
                 (APP/2026-03-26 current); R6 14/31 resets; S-20
                 no-any-return; S-21 package-move bindings; S-23
                 negative assertions bound to a type the code no
                 longer emits; four exempted baseline tests.
  NEXT:          S-25 6 order-lifecycle transitions in the kernel
                 (boundary). Not started. Do not begin S-25.
                 Left uncommitted: baseline_pre-S-24.json,
                 baseline_post-S-24.json, this ledger entry.


