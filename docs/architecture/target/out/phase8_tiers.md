# PHASE 8 — Five import tiers

**Basis.** Phase 7 execution closed at S-35e on `arch/exec` (`0cb0c753`).
G40 is CLOSED. Twelve-engine independence is KEPT. Five import tiers stays
BROKEN on the thirteen-pair `_TIER_RESIDUALS` pin. Current-state claims
carry their original label; new material is `specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        Five import tiers
BASE:            arch/exec 0cb0c753 (S-35e closed; G40 CLOSED)
CLOSES:          Five import tiers KEPT; .github/workflows/ci.yml
                 Import contracts continue-on-error.
DOES NOT CLOSE:  G10, G28, G32, G36, G39, G41, G42, G44, G45, G46;
                 S-34f groups g–o (15 engine bodies; Inv-8 is a
                 different campaign); perfmeasure.py DIRECT_PROBES;
                 G6 empty depends_on_sensors; S-04c; serialization.py
                 fail-open; verify_step frozen bugs; 152 research
                 cache days; R6 14/31; the four EXEMPTION tests.
                 Twelve-engine independence stays KEPT; a
                 regression there is a STOP, not this campaign.
                 A five-tier cut must not reintroduce an
                 engine-to-engine edge. Binding through bootstrap
                 moves imports; S2 must be re-run after every
                 pair-dropping step and stay KEPT at zero
                 twelve-engine pairs. A new twelve-engine pair
                 is a STOP, not a trade.
STANDING
INVARIANTS:      Oracle frozen at exec-tools-v1. Never run
                 scripts/rebaseline_parity_hashes.py.
                 Hold all 64 HASH/COUNT constants, the fingerprint
                 (de5d64b019075de0ca271b53834f342623f2b1a39f23ff73910e45b0bc90beb6),
                 and _BASELINE_CONFIG_HASH unless a step names a
                 re-pin.
                 Accepted baseline failures are only
                 test_after_hours_reject_surfaces_as_rejected,
                 test_g12_cost_exceeds_disclosure_alert,
                 test_multi_symbol_subscribe,
                 test_sustained_quotes_with_idle_ticks.
                 A failure outside that set is a STOP.
                 Mechanism before FILES (S-35c4). Do not invent
                 S-35 suffixes. Do not extract g–o. Do not
                 shrink _TIER_RESIDUALS except in lockstep with a
                 dropped pair. Do not flip ci.yml until both
                 contracts are KEPT. Do not rewrite the layers
                 contract by deleting engines or adding
                 ignore_imports.
                 FAIL_QUIET_KEEP is line-pinned (path, line, exc_type)
                 with no enclosing-symbol key. A step that inserts or
                 deletes lines above a keep-row must name
                 tests/conformance/test_fail_quiet.py in FILES and
                 retarget those rows in the same commit. Keep-row files
                 in this campaign: harness/backtest_runner.py (591, 796,
                 833), bootstrap.py (1607, 1825),
                 alpha/layer_validator.py (1190),
                 composition/factor_neutralizer.py (28, 139),
                 ingestion/massive_ingestor.py (73),
                 ingestion/massive_ws.py (185, 228, 344). Re-keying by
                 enclosing symbol would be a consumer change, not a row
                 edit -- out of scope here.
NON-CUTS:        A re-export without retarget is not a cut.
                 A TYPE_CHECKING-only move is not a cut.
                 A sys.modules lookup (or optional getattr
                 fallback) is not a cut.
                 Widening a type to object or Any is not a cut.
                 A deleted TYPE_CHECKING import is not a cut;
                 retarget the annotation to a legal owner.
LADDER:          Pair count is the layers contract, not G40.
                 Shared-file steps are sequential, not
                 independently revertible.
                   now                                              13
                   1  harness → cli (env down)                     12
                   2  harness → bootstrap (composition-root up)   11
                   3  bind: injected types
                      (alpha, sensors, signals)                      8
                   4  bind: selection_policy required
                      (composition)                                 7
                   5  bind: regime/hazard helpers
                      (services)                                    6
                   6  bind: feed and telemetry leftovers
                      (ingestion, monitoring)                      4
                   7  bind: book of record
                      (portfolio)                                    3
                   8  bind: tick path
                      (risk, execution)                              1
                   9  storage (orchestrator and fill_bindings
                      retarget)                                      0
                  10  empty pin AND Five import tiers KEPT
                      AND drop continue-on-error               0 KEPT
                 Gate at every pair-dropping step: pairs ==
                 the expected remaining _TIER_RESIDUALS.
                 S2 (test_twelve_engine_independence) re-run
                 after every pair-dropping step; stays KEPT
                 at zero pairs. A new twelve-engine pair is a
                 STOP.
                 Step 10 adds statuses["Five import tiers"]
                 == "KEPT" beside pairs == frozenset().
                 If pairs == frozenset() but
                 statuses["Five import tiers"] reports BROKEN,
                 the campaign has not closed and
                 continue-on-error does not flip. Two green
                 assertions disagreeing with the status line
                 is a detector question, not a close.
                 Only alpha is TYPE_CHECKING-only; step 3
                 retargets it, it does not delete l.25.
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template).

```
STEP:            T-01
CLOSES:          nothing. Drops harness → cli. Five import tiers stays
                 BROKEN. 13 → 12. G40 stays CLOSED.
PROBLEM:         feelies.harness.backtest_runner imports feelies.cli.env
                 (l.35) and looks up MASSIVE_API_KEY inside
                 run_backtest_api. That is T3 importing T1. The three
                 names are only used at run_backtest_api:929-932.
                 Callers that reach that lookup: cli/backtest.py:33,
                 backtest_runner.main:1026, scripts/run_backtest.py:81.
                 No test calls either function.
FILES:           src/feelies/harness/backtest_runner.py
                 src/feelies/cli/backtest.py
                 scripts/run_backtest.py
                 tests/conformance/test_import_contracts.py
                 tests/conformance/test_fail_quiet.py
                 Do not add a module. Do not move cli/env.py. Do not
                 include tests/conftest.py. Do not include
                 harness/__init__.py (re-export, not a call). Do not
                 include cli/main.py. Do not include cli/env.py.
                 Do not include .github/workflows/ci.yml.
WHY THIS OWNER:  T1 already owns operator env. The illegal edge is
                 harness reaching up for a secret. The invert is the
                 entry point supplying a required api_key, not relocating
                 dotenv into core or harness.
REFACTOR PATH:   one commit. (1) run_backtest_api and main take required
                 api_key; drop the feelies.cli.env import; no os.getenv,
                 no None default, no getattr, no sys.modules.
                 (2) cli.backtest.run_backtest_handler: load_dotenv_optional,
                 massive_api_key_from_env, print MASSIVE_API_KEY_ERROR
                 and return 1 on None, else pass the string.
                 (3) scripts/run_backtest.py if __name__: same load, then
                 main(..., api_key=...).
                 (4) drop ("feelies.harness", "feelies.cli") from
                 _TIER_RESIDUALS (equality, 12 remain).
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 12-pair pin;
                 test_twelve_engine_independence KEPT at zero pairs;
                 tests/cli/test_backtest_cli.py; tests/cli/
                 test_cli_import_isolation.py; tests/harness/
                 test_backtest_runner.py. No XPASS. lint-imports: Five
                 import tiers still BROKEN, Twelve engine module sets
                 KEPT. A new twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only who reads the key changes.
DELETES:         the harness → cli pair; the cli.env import from
                 backtest_runner.
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert the commit. Independently revertible from T-02
                 (same backtest_runner.py; not independently revertible
                 once T-02 lands).
```
