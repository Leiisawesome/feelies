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
