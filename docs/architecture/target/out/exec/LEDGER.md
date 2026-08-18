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
