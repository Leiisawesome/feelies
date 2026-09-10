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
                 MEASURE KEEP-ROWS, DO NOT ASSUME THEM. T-02's block
                 sketched 589/794/831; the measured result was
                 588/794/831, because the deleted import carried a
                 blank line with it and a new signature line landed
                 between the first row and the other two. Every step
                 that edits a keep-row file states the shift as
                 measured after the cut, in the same commit, never as
                 predicted before it.
                 PROTOCOL MODULES ARE PER ENGINE CONCERN.
                 One Protocol module per engine concern in
                 core, named for the thing, never for the
                 step. Existing modules are retargeted
                 rather than duplicated -- position.py,
                 metric_collector.py, horizon_protocol.py,
                 composition_protocol.py. No shared
                 kernel_ports.py: a step that appends to a
                 shared module is not independently
                 revertible from the steps that append
                 after it, and later groups carry helper
                 functions as well as constructor types;
                 a ports file invites that category error.
                 CHECK FOR A PUBLIC PROPERTY BEFORE WRITING A
                 PROTOCOL SURFACE. T-03's first attempt scoped
                 AlphaRegistry to the one method kernel calls
                 and failed mypy on seven attribute errors in
                 harness and cli, none of them in FILES,
                 because orchestrator hands the instance out
                 through a public alpha_registry property. A
                 Protocol on a type the orchestrator exposes
                 must cover every consumer of that property,
                 not just the kernel's own calls. Enumerate
                 the property's callers before writing the
                 surface.
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

```
STEP:            T-02
CLOSES:          nothing. Drops harness → bootstrap. Five import tiers stays
                 BROKEN. 12 → 11. G40 stays CLOSED.
PROBLEM:         feelies.harness.backtest_runner imports
                 feelies.bootstrap.build_platform (l.30) and calls it inside
                 _run_backtest_phases_2_7 (l.714-723) after prep. That is T3
                 importing the composition root. The only in-package caller is
                 run_backtest_api:1001. External callers of
                 _run_backtest_phases_2_7, all of which currently rely on
                 harness composing: tests/harness/test_backtest_runner.py:137
                 and :182, tests/acceptance/test_backtest_app_baseline.py:353,
                 scripts/compare_multialpha_runs.py:421,
                 tools/arch/perfmeasure.py:576. No test calls run_backtest_api
                 or harness main. scripts/run_backtest.py re-exports the
                 function; it does not call it.
WHY THIS OWNER:  T1 already owns the operator entry. The illegal edge is
                 harness reaching up for construction. The invert is the entry
                 point supplying a required platform_factory, not relocating
                 bootstrap into harness or moving construction into T3.
FILES:           src/feelies/harness/backtest_runner.py
                 src/feelies/cli/backtest.py
                 scripts/run_backtest.py
                 tests/harness/test_backtest_runner.py
                 tests/acceptance/test_backtest_app_baseline.py
                 scripts/compare_multialpha_runs.py
                 tools/arch/perfmeasure.py
                 tests/conformance/test_import_contracts.py
                 tests/conformance/test_fail_quiet.py
                 Do not add a module. Do not edit bootstrap.py. Do not
                 include harness/__init__.py (re-export, not a call). Do not
                 include cli/main.py. Do not include cli/env.py. Do not
                 include .github/workflows/ci.yml. Do not touch
                 perfmeasure.py DIRECT_PROBES.
REFACTOR PATH:   one commit. Mechanism: required keyword-only
                 platform_factory on _run_backtest_phases_2_7, run_backtest_api,
                 and main; threaded from the entry points; bootstrap untouched.
                 No None default, no getattr, no sys.modules, no
                 TYPE_CHECKING import of build_platform. A default added so
                 an undeclared caller keeps working is not a cut (S-35c1).
                 (1) drop the feelies.bootstrap import from backtest_runner;
                 call platform_factory at the existing compose site with the
                 same kwargs. (2) cli.backtest.run_backtest_handler: import
                 build_platform, pass it into run_backtest_api.
                 (3) scripts/run_backtest.py if __name__: same, then
                 main(..., platform_factory=build_platform).
                 (4) test_backtest_runner.py (both sites), the APP oracle,
                 compare_multialpha_runs.py, and perfmeasure.py pass
                 platform_factory=build_platform. (5) drop
                 ("feelies.harness", "feelies.bootstrap") from
                 _TIER_RESIDUALS (equality, 11 remain). (6) FAIL_QUIET_KEEP
                 is line-pinned. Deleting backtest_runner.py:30 shifts 590,
                 795, 832 by one, to 589, 794, 831. One extra signature line
                 on _run_backtest_phases_2_7, between the first keep-row and
                 the other two, puts 795 and 832 back and leaves 590→589.
                 Measure the three rows after the cut; retarget what actually
                 moved, in this commit. Do not assume the numbers. Do not
                 re-key by enclosing symbol. bootstrap.py 1607 and 1825 do
                 not move.
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 11-pair pin;
                 test_twelve_engine_independence KEPT at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py (APP oracle);
                 tests/harness/test_backtest_runner.py; tests/cli/
                 test_backtest_cli.py. No XPASS. lint-imports: Five import
                 tiers still BROKEN, Twelve engine module sets KEPT. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is unmoved;
                 only who names build_platform changes. A moved HASH or
                 COUNT means the factory call was not a transparent
                 substitute (kwargs, order, or a silent default) — STOP,
                 do not re-pin.
DELETES:         the harness → bootstrap pair; the bootstrap import from
                 backtest_runner.
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert the commit. Independently revertible from T-03
                 (same backtest_runner.py; not independently revertible
                 once T-03 lands).
```

```
STEP:            T-03
CLOSES:          nothing. Drops kernel → alpha, kernel → sensors,
                 kernel → signals. Five import tiers stays BROKEN.
                 11 → 8. G40 stays CLOSED.
PROBLEM:         feelies.kernel.orchestrator imports four injected
                 types from three engine packages: AlphaRegistry
                 (TYPE_CHECKING, l.25), HorizonScheduler (l.190),
                 SensorRegistry (l.191), HorizonSignalEngine (l.194).
                 Used only as constructor/property annotations
                 (l.266, 271-273, 670). Runtime calls methods on the
                 injected instances; no isinstance, no construction.
                 That is T5 importing T2/T3/T4 for names. Bootstrap
                 already constructs all four and passes them in
                 (bootstrap.py ~676-685).
                 The alpha_registry property hands the
                 instance to feelies.harness.backtest_runner,
                 feelies.harness.backtest_report and
                 feelies.cli.forensics, which call alpha_ids,
                 get and get_lifecycle. The Protocol must
                 cover their typed use or mypy fails in files
                 outside FILES. Typing the property as the
                 concrete keeps the import and the pair.
                 sensor_registry, horizon_scheduler and
                 horizon_signal_engine have no public
                 property and no such exposure.
WHY THIS OWNER:  T5 core already owns the names kernel may use.
                 The illegal edges are annotation imports. The invert
                 is Protocols in core, named for the engine concern,
                 not relocating the concretes and not a TYPE_CHECKING
                 delete. Two new modules (alpha_registry,
                 sensor_registry) plus HorizonScheduler and
                 HorizonSignalEngine added to horizon_protocol.py --
                 that file already owns the horizon concern
                 (HorizonSignal). A third new horizon module would
                 duplicate it. SensorRegistry is not horizon; it
                 does not go there.
REFACTOR PATH:   one commit. Mechanism: kernel annotates against
                 core Protocols; bootstrap already constructs the
                 concretes and is not in FILES. No object/Any, no
                 getattr, no sys.modules, no TYPE_CHECKING-only move,
                 no re-export of the Protocol from the engine package
                 as the cut, no kernel_ports.py, no explicit
                 subclassing of the Protocol on the concrete (structural).
                 Alpha is TYPE_CHECKING-only. Retarget the annotation
                 at orchestrator.py:25 to feelies.core.alpha_registry;
                 do not delete l.25 as the cut while the name still
                 binds feelies.alpha.registry. That deletion is the
                 fifth catalogued non-cut.
                 (1) add src/feelies/core/alpha_registry.py:
                 AlphaRegistry Protocol. Members:
                 has_portfolio_alphas() -> bool;
                 alpha_ids() -> frozenset[str];
                 get(alpha_id: str) returning a nested
                 Protocol with only manifest.version: str;
                 get_lifecycle(alpha_id: str) -> object | None.
                 Do not import feelies.alpha. reset and
                 portfolio_alphas stay getattr, not
                 Protocol members. The property at
                 orchestrator.py:670 stays AlphaRegistry
                 | None, so this surface covers harness
                 and cli as well as kernel.
                 (2) add src/feelies/core/sensor_registry.py:
                 SensorRegistry Protocol, is_empty.
                 (3) add HorizonScheduler (on_event → tuple of
                 HorizonTick) and HorizonSignalEngine (is_empty
                 property) to horizon_protocol.py; extend __all__.
                 (4) orchestrator: import the four names from core;
                 drop feelies.alpha.registry, feelies.sensors.*,
                 feelies.signals.horizon_engine. Keep the call sites.
                 (5) drop ("feelies.kernel", "feelies.alpha"),
                 ("feelies.kernel", "feelies.sensors"),
                 ("feelies.kernel", "feelies.signals") from
                 _TIER_RESIDUALS in the same commit (equality, 8
                 remain). (6) coverage map for the two new modules:
                 _FILE_OWNERS rows (audit_core_clock_config) and the
                 README core_clock_config citation list, same commit,
                 S-21. horizon_protocol.py already has a row.
                 orchestrator.py and the core Protocol files are not
                 keep-row files; do not include test_fail_quiet.py.
                 Do not edit bootstrap.py. Do not edit
                 alpha/layer_validator.py. Do not include
                 harness/__init__.py, cli/, ci.yml.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/core/alpha_registry.py
                 src/feelies/core/sensor_registry.py
                 src/feelies/core/horizon_protocol.py
                 tests/conformance/test_import_contracts.py
                 tests/docs/test_prompt_coverage_map.py
                 docs/prompts/README.md
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 8-pair pin;
                 test_twelve_engine_independence KEPT at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py (APP
                 oracle). No XPASS. lint-imports: Five import tiers
                 still BROKEN, Twelve engine module sets KEPT. A new
                 twelve-engine pair is a STOP. test_prompt_coverage_map
                 owns the two new modules.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only which module kernel names for the four
                 injected types changes. A moved HASH or COUNT means
                 the Protocol call was not a transparent substitute
                 (surface, attribute, or a silent default) — STOP,
                 do not re-pin.
DELETES:         the kernel → alpha, kernel → sensors, and
                 kernel → signals pairs; the four engine-package
                 imports from orchestrator.
NET DELTA:       src modules +2, public symbols +4, branch points 0
ROLLBACK:        revert the commit. The two new Protocol modules
                 revert with it. Independently revertible from T-04
                 on those two files; orchestrator.py is shared with
                 T-04 and is not independently revertible once T-04
                 lands.
```
