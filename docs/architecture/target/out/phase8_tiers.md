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
                 SIZE A RUNG BY A PER-NAME CENSUS, NOT A
                 PACKAGE LABEL. T-04's one-line description
                 named selection_policy; kernel imported
                 seven names from three composition modules,
                 and a Protocol-only step would have left
                 five in place with the pin unmoved. Before
                 a rung is written as a block, enumerate
                 every kernel import of that package with
                 line and kind, classify each as injected,
                 default-constructed, annotation-only, or a
                 function/enum/dataclass that no Protocol
                 can replace, and check for a public
                 orchestrator property. A rung whose names
                 mix those kinds splits.
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
                 A step that does not empty a package
                 does not move the pin.
                   now                                              13
                   1  harness → cli (env down)                     12
                   2  harness → bootstrap (composition-root up)   11
                   3  bind: injected types
                      (alpha, sensors, signals)                      8
                   4  bind: selection_policy required
                      (composition)                                 7
                   T-05a  four regime helpers (functions;
                          services)                                 7
                   T-05b  RegimeEngine, RegimeHazardDetector
                          Protocols (services)                      6
                   T-06a  halt helpers, IdleTick, DataHealth,
                          HaltTradeability, MarketDataNormalizer
                          (ingestion)                                 5
                   T-06b  MetricCollector retarget; invert
                          LatencyBudgetMonitor; KillSwitch
                          (property), AlertManager,
                          PaperSessionRecorder;
                          observe_kill_switch,
                          apply_breach_response (monitoring)       4
                   T-07a  fill helpers; LotLedger invert;
                          PositionBookView (portfolio)              4
                   T-07b  PositionStore retarget; Protocol
                          FillAttributionLedger,
                          StrategyPositionStore (portfolio)        3
                   T-08a  risk helpers, HAZARD_EXIT bind,
                          RiskLevel; invert BudgetBasedSizer
                          and create_risk_escalation_machine;
                          Protocol RiskEngine,
                          HazardExitController, PositionSizer,
                          EdgeWeightedSizer (risk)                2
                   T-08b  invert SignalPositionTranslator,
                          PortfolioNetter, DesiredTargetBook,
                          MarketContext,
                          create_order_state_machine,
                          min-cost policy; Protocol
                          ExecutionBackend and remaining
                          injected types;
                          enums/dataclasses/functions
                          (execution)                                1
                   T-09a  TradeRecord; fill_bindings retarget
                          (storage)                                  1
                   T-09b  EventLog, FeatureSnapshotStore,
                          TradeJournal query (storage)              0
                   close  empty pin AND Five import tiers KEPT
                          AND drop continue-on-error          0 KEPT
                 Gate at every pair-dropping step: pairs ==
                 the expected remaining _TIER_RESIDUALS.
                 S2 (test_twelve_engine_independence) re-run
                 after every pair-dropping step; stays KEPT
                 at zero pairs. A new twelve-engine pair is a
                 STOP.
                 The close rung adds statuses["Five import
                 tiers"] == "KEPT" beside pairs == frozenset().
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

```
STEP:            T-04a
CLOSES:          nothing. Pin stays 8. Does not drop kernel →
                 composition. Five import tiers stays BROKEN. G40
                 stays CLOSED. A step that leaves the count unchanged
                 is legitimate here and must not be mistaken for a
                 failed cut.
PROBLEM:         feelies.kernel.orchestrator is the only kernel file
                 that imports feelies.composition. Seven names:
                 CompositionEngine from composition.engine
                 (TYPE_CHECKING, l.26); SelectionPolicy from
                 composition.protocol (runtime, l.30);
                 StandaloneArbitrationCollision, Top1SelectionPolicy,
                 collision_is_harmless_flat_gate_close,
                 is_redundant_gate_close_flat,
                 standalone_signal_actionable_for_strategy from
                 composition.selection_policy (runtime, l.31-36).
                 CompositionEngine is injected optional; stored;
                 is None at :1168; getattr reset at :2522. No public
                 property. Kernel never calls is_empty or reset by
                 name. Bootstrap already constructs and passes it
                 (bootstrap.py ~558, ~688). An empty Protocol is
                 enough. Deleting l.26 while the name still binds
                 feelies.composition.engine is not a cut.
                 StandaloneArbitrationCollision is a frozen
                 dataclass kernel constructs at :1594-1605.
                 Public property arbitration_collisions at :630.
                 scripts/compare_multialpha_runs.py imports that
                 name from kernel (not composition) and reads
                 candidate_count, strategy_ids, kinds, harmless.
                 After the move, orchestrator still binds the name
                 from core, so that script import stays valid.
                 The three helpers (and private
                 _signal_reduces_book) are pure predicates on
                 Signal plus book qty, used on the standalone
                 SIGNAL path before select(). Honest owner is
                 core, not Engine 6. Injecting three callables is
                 the wrong cost. SelectionPolicy and
                 Top1SelectionPolicy stay for T-04b.
WHY THIS OWNER:  T5 core already owns the names kernel may use.
                 composition_protocol.py already owns the
                 composition concern (CompositionContextError).
                 The illegal edges here are annotation and helper
                 imports. The invert is names in that existing
                 module, not relocating Top1, not a TYPE_CHECKING
                 delete, and not a new module. A second composition
                 Protocol file would duplicate it.
REFACTOR PATH:   one commit. Mechanism: move the collision record and
                 the three Signal predicates (plus private
                 _signal_reduces_book) into
                 feelies.core.composition_protocol; retarget
                 CompositionEngine at orchestrator.py:26 onto that
                 same module; re-export the moved names from
                 feelies.composition.selection_policy as a
                 convenience for consumers that already import them
                 from Engine 6. That re-export is not the cut. Do
                 not invert selection_policy. No object/Any, no
                 getattr, no sys.modules, no TYPE_CHECKING-only
                 move, no re-export of the Protocol from the engine
                 package as the cut, no kernel_ports.py, no explicit
                 subclassing of the Protocol on the concrete
                 (structural).
                 CompositionEngine is TYPE_CHECKING-only. Retarget
                 the annotation at orchestrator.py:26 to
                 feelies.core.composition_protocol; do not delete
                 l.26 as the cut while the name still binds
                 feelies.composition.engine. That retarget, not a
                 delete of l.26, is the fifth catalogued non-cut.
                 (1) extend src/feelies/core/composition_protocol.py:
                 CompositionEngine Protocol (empty; kernel never
                 calls methods by name; reset stays getattr, not a
                 Protocol member); StandaloneArbitrationCollision
                 frozen dataclass (candidate_count, strategy_ids,
                 kinds, harmless); the three helpers and
                 _signal_reduces_book. Import Signal /
                 SignalDirection from feelies.core.events. Do not
                 import feelies.composition. The property at
                 orchestrator.py:630 stays
                 tuple[StandaloneArbitrationCollision, ...], so
                 this surface covers the kernel property and
                 compare_multialpha_runs.py without retargeting
                 the script.
                 (2) selection_policy.py: delete the moved bodies;
                 re-export the four public names from
                 feelies.core.composition_protocol. Keep
                 Top1SelectionPolicy here. The re-export is a
                 convenience for consumers (including
                 tests/kernel/test_standalone_signal_ownership.py);
                 it is not the cut.
                 (3) orchestrator: import CompositionEngine,
                 StandaloneArbitrationCollision, and the three
                 helpers from feelies.core.composition_protocol;
                 drop those names from composition.engine and
                 composition.selection_policy. Keep
                 SelectionPolicy from composition.protocol and
                 Top1SelectionPolicy from selection_policy. Keep
                 the call sites.
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 8-pair pin (pin
                 does not move); test_twelve_engine_independence
                 KEPT at zero pairs; tests/acceptance/
                 test_backtest_app_baseline.py (APP oracle). No
                 XPASS. lint-imports: Five import tiers still BROKEN,
                 Twelve engine module sets KEPT. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only which module kernel names for
                 CompositionEngine, the collision record, and the
                 three helpers changes. A moved HASH or COUNT
                 means the Protocol or helper was not a transparent
                 substitute (surface, field, or a silent default)
                 — STOP, do not re-pin.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/core/composition_protocol.py
                 src/feelies/composition/selection_policy.py
                 Do not add a module. Do not invert
                 selection_policy. Do not edit bootstrap.py. Do not
                 include tests/conformance/test_import_contracts.py
                 (pin does not move). Do not include
                 scripts/compare_multialpha_runs.py; it keeps
                 importing StandaloneArbitrationCollision from
                 kernel. Do not include
                 tests/conformance/test_fail_quiet.py.
                 composition/factor_neutralizer.py is not in
                 FILES; keep-rows 28 (ImportError) and 139
                 (np.linalg.LinAlgError) stay untouched. Do not
                 include tests/docs/test_prompt_coverage_map.py
                 or docs/prompts/README.md
                 (composition_protocol.py already has a row and a
                 README citation). Do not include
                 tests/kernel/test_standalone_signal_ownership.py
                 (re-export covers it). Do not include
                 composition/engine.py or composition/protocol.py.
                 Do not include harness/__init__.py, cli/,
                 .github/workflows/ci.yml.
DELETES:         the engine-package imports of CompositionEngine,
                 StandaloneArbitrationCollision, and the three
                 helpers from orchestrator. Does not delete the
                 kernel → composition pair.
NET DELTA:       src modules 0, public symbols +1, branch points 0
                 (CompositionEngine Protocol is new; the three
                 helpers and collision relocate: selection_policy
                 loses four public names that become imports;
                 composition_protocol gains them).
ROLLBACK:        revert the commit. Independently revertible from
                 T-04b until T-04b lands; orchestrator.py and
                 composition_protocol.py are shared with T-04b
                 and are not independently revertible once T-04b
                 lands.
```

```
STEP:            T-04b
CLOSES:          nothing. Drops kernel → composition. Five import
                 tiers stays BROKEN. 8 → 7. G40 stays CLOSED.
PROBLEM:         After T-04a, kernel still imports SelectionPolicy
                 from feelies.composition.protocol (runtime, l.30)
                 and Top1SelectionPolicy from
                 feelies.composition.selection_policy. Constructor
                 takes selection_policy: SelectionPolicy | None = None
                 at :279 and defaults at :365-366 with
                 Top1SelectionPolicy(). Runtime uses
                 select(buf).winner at :1636 and
                 type(...).__name__ at :1634. Nothing currently
                 passes selection_policy= — not bootstrap
                 (_RootOrchestrator at ~659), not any of the 52
                 real Orchestrator( sites in 19 test files. A
                 default Top1SelectionPolicy() is the illegal
                 import itself. No legitimate default both
                 preserves Top-1 and drops kernel → composition.
                 Same shape as T-02: a default added so an
                 undeclared caller keeps working is not a cut
                 (S-35c1; T-02's default was
                 platform_factory=build_platform). selection_policy
                 is not a public property; no extra Protocol surface
                 for harness or cli.
WHY THIS OWNER:  T5 core already owns the names kernel may use.
                 SelectionPolicy is the injected type. The
                 illegal edge is the default constructing Top1.
                 The invert is the composition root supplying a
                 required SelectionPolicy, not relocating Top1 into
                 kernel and not a default that keeps the import.
REFACTOR PATH:   one commit. Mechanism: SelectionPolicy Protocol in
                 feelies.core.composition_protocol (same file as
                 T-04a); selection_policy required, no default;
                 bootstrap and every real Orchestrator( site pass
                 Top1SelectionPolicy(). No object/Any, no getattr,
                 no sys.modules, no TYPE_CHECKING-only move, no
                 re-export of the Protocol from the engine package
                 as the cut, no kernel_ports.py, no explicit
                 subclassing of the Protocol on Top1 (structural).
                 A default = Top1SelectionPolicy() is the illegal
                 import itself; no default is legitimate (T-02 /
                 S-35c1 parallel).
                 (1) add SelectionPolicy Protocol to
                 composition_protocol.py. Member: select → nested
                 Protocol with only winner: Signal | None. Do not
                 import SelectionResult or anything else from
                 feelies.composition (that would be core →
                 composition). Nested name underscored so it is
                 not a public symbol.
                 (2) orchestrator: import SelectionPolicy from
                 feelies.core.composition_protocol; drop
                 feelies.composition.protocol and
                 Top1SelectionPolicy. Required
                 selection_policy: SelectionPolicy with no default
                 and no | None. Delete the ternary at :365-366;
                 store the argument. Keep the call sites.
                 (3) bootstrap.py passes
                 selection_policy=Top1SelectionPolicy() into
                 _RootOrchestrator. bootstrap.py is a keep-row file
                 (1607 KeyError, 1825 TypeError/ValueError).
                 test_fail_quiet.py is not in FILES, so this step
                 must not insert or delete lines above those rows:
                 squeeze the Top1SelectionPolicy import onto an
                 existing import line and
                 selection_policy=Top1SelectionPolicy() onto an
                 existing _RootOrchestrator argument line. Measure
                 1607 and 1825 after the cut; if they moved, STOP.
                 (4) every real Orchestrator( site in the 19 test
                 files passes selection_policy=Top1SelectionPolicy().
                 tests/kernel/test_orchestrator.py: updating
                 _build_orchestrator does not cover that file's 27
                 raw sites. Files that import _build_orchestrator
                 from test_orchestrator.py and have no
                 Orchestrator( of their own need no edit of their
                 own: tests/kernel/test_fill_attribution_seam.py,
                 tests/conformance/test_pathological_refusal.py,
                 tests/kernel/test_reverse_edge_calibration.py,
                 tests/kernel/test_orchestrator_order_routing.py,
                 tests/kernel/test_orchestrator_edge_calibration.py.
                 (5) drop ("feelies.kernel", "feelies.composition")
                 from _TIER_RESIDUALS in the same commit (equality,
                 7 remain).
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 7-pair pin;
                 test_twelve_engine_independence KEPT at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py (APP
                 oracle). No XPASS. lint-imports: Five import tiers
                 still BROKEN, Twelve engine module sets KEPT. A
                 new twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only who constructs Top1 and which
                 module kernel names for SelectionPolicy changes.
                 A moved HASH or COUNT means the Protocol call or
                 the required handle was not a transparent
                 substitute (surface, a silent default, or a
                 different policy) — STOP, do not re-pin.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/core/composition_protocol.py
                 src/feelies/bootstrap.py
                 (1 site: _RootOrchestrator ~659; squeeze, see
                 REFACTOR PATH)
                 tests/kernel/test_orchestrator.py
                 (28: 1 factory + 27 raw)
                 tests/kernel/test_orchestrator_bus_sized_intent.py
                 (4: 1 local factory + 3 raw)
                 tests/determinism/test_forced_exit_attribution_replay.py
                 (3)
                 tests/causality/test_anti_lookahead.py
                 (2)
                 tests/kernel/test_trade_path_regime_gate_cold_start.py
                 (1)
                 tests/determinism/test_position_pnl_replay.py
                 (1)
                 tests/kernel/test_reducing_signal_survives_risk_gate.py
                 (1 local factory)
                 tests/kernel/test_orchestrator_hazard_exit_routing.py
                 (1 local factory)
                 tests/kernel/test_data_integrity_runtime.py
                 (1 local factory)
                 tests/determinism/test_symbol_halted_replay.py
                 (1)
                 tests/kernel/test_orchestrator_shutdown_drain.py
                 (1 local factory)
                 tests/kernel/test_orchestrator_async_fill_latency.py
                 (1 local factory)
                 tests/kernel/test_orchestrator_bus_signal.py
                 (1 local factory)
                 tests/conformance/test_registration_order.py
                 (1)
                 tests/kernel/test_orchestrator_exit_composer_routing.py
                 (1 local factory)
                 tests/kernel/test_orchestrator_idle_tick.py
                 (1 local factory)
                 tests/kernel/test_standalone_signal_ownership.py
                 (1 local factory)
                 tests/services/test_regime_hazard_engine_wiring.py
                 (1 local factory)
                 tests/integration/test_dual_scale_down_e2e.py
                 (1)
                 tests/conformance/test_import_contracts.py
                 Do not add a module. Do not include
                 scripts/compare_multialpha_runs.py; it keeps
                 importing StandaloneArbitrationCollision from
                 kernel. Do not include
                 tests/conformance/test_fail_quiet.py.
                 composition/factor_neutralizer.py is not in
                 FILES; keep-rows 28 and 139 stay untouched. Do
                 not include the five test_orchestrator.py-factory
                 funnel files listed in REFACTOR PATH. Do not
                 include tests/harness/test_emit_edge_calibration.py
                 or tests/harness/test_backtest_report.py
                 (_FakeOrchestrator, not a real constructor). Do
                 not include composition/selection_policy.py
                 (T-04a re-export; not this cut) or
                 composition/protocol.py (Top1 still imports
                 SelectionPolicy from there; structural). Do not
                 include harness/__init__.py, cli/,
                 .github/workflows/ci.yml.
DELETES:         the kernel → composition pair; the
                 composition.protocol and Top1SelectionPolicy
                 imports from orchestrator; the Top1 default.
NET DELTA:       src modules 0, public symbols +1, branch points 0
                 (SelectionPolicy Protocol; nested winner type is
                 underscored).
ROLLBACK:        revert the commit. Independently revertible from
                 T-05 until T-05 lands; orchestrator.py is shared
                 with T-04a and T-05 and is not independently
                 revertible once T-05 lands.
```

```
STEP:            T-05a
CLOSES:          nothing. Pin stays 7. Does not drop kernel →
                 services. Five import tiers stays BROKEN. G40
                 stays CLOSED. A step that leaves the count unchanged
                 is legitimate here and must not be mistaken for a
                 failed cut.
PROBLEM:         feelies.kernel.orchestrator is the only kernel file
                 that imports feelies.services. Six names in two
                 modules. This step is the four underscored helpers
                 from services.regime_engine (runtime, l.191):
                 _calibrate_regime_engine, _checkpoint_feature_snapshots,
                 _restore_feature_snapshots, _update_regime. Used at
                 :818, :819, :1002, :1543, each as f(self, ...). They
                 take the orchestrator as self: Any and mutate kernel
                 session state (_bus, _seq, _hazard_seq,
                 _last_regime_state, _publish_alert). Two private
                 callees in the same file exist only for those four:
                 _checkpoint_regime_snapshot, _maybe_publish_hazard_spike.
                 They travel with the four. _regime_label_for is also
                 in that file from S-19; kernel does not import it —
                 not this rung. RegimeEngine and RegimeHazardDetector
                 stay for T-05b. A helpers-only step that left those
                 two types would leave the pair; that is the declared
                 outcome, same shape as T-04a.
WHY THIS OWNER:  The bodies were written in the kernel and parked in
                 services in S-19 (_calibrate_regime_engine,
                 _update_regime, plus the two private callees) and S-20
                 (_restore_feature_snapshots, _checkpoint_feature_snapshots,
                 because after S-19 they only touch regime snapshots).
                 services/regime_engine.py already holds those
                 kernel-authored helper bodies. This is a return
                 move, not a new home. Honest owner is kernel: they
                 take orchestrator as self and write kernel session
                 fields. Core would be convenient, not honest — T-04a
                 put pure Signal predicates in core because they had no
                 orchestrator. These are the opposite. Injecting four
                 callables is the wrong cost.
REFACTOR PATH:   one commit. Mechanism: return the four helpers and
                 the two private callees from
                 feelies.services.regime_engine to
                 feelies.kernel.orchestrator as the same module-level
                 functions taking the orchestrator as self. Kernel
                 drops those names from the services import; keeps
                 RegimeEngine and RegimeHazardDetector. Call sites
                 stay. No object/Any widening, no getattr, no
                 sys.modules, no TYPE_CHECKING-only move, no
                 kernel_ports.py, no new module, no re-export of the
                 helpers from services as the cut.
                 (1) move _calibrate_regime_engine,
                 _checkpoint_feature_snapshots,
                 _restore_feature_snapshots, _update_regime,
                 _checkpoint_regime_snapshot, and
                 _maybe_publish_hazard_spike into orchestrator.py.
                 Bodies unchanged. _restore_feature_snapshots already
                 calls Orchestrator._restore_regime_snapshot; that
                 callee stays. Leave _regime_label_for in services
                 (kernel does not import it).
                 (2) orchestrator: drop the four names from
                 feelies.services.regime_engine; keep RegimeEngine from
                 that module and RegimeHazardDetector from
                 regime_hazard_detector. Keep the call sites.
                 (3) tests/kernel/test_orchestrator.py: retarget
                 `_calibrate_regime_engine` from
                 feelies.services.regime_engine onto kernel
                 (the one FILES-visible importer of a helper).
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 7-pair pin (pin
                 does not move); test_twelve_engine_independence
                 KEPT at zero pairs; tests/acceptance/
                 test_backtest_app_baseline.py (APP oracle). No
                 XPASS. lint-imports: Five import tiers still BROKEN,
                 Twelve engine module sets KEPT. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only which module defines the four
                 helpers changes. A moved HASH or COUNT means the
                 returned helper was not a transparent substitute
                 (body, order, or a silent default) — STOP, do not
                 re-pin.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/services/regime_engine.py
                 tests/kernel/test_orchestrator.py
                 Do not add a module. Do not invert RegimeEngine or
                 RegimeHazardDetector. Do not edit bootstrap.py. Do
                 not include tests/conformance/test_import_contracts.py
                 (pin does not move). Do not include
                 tests/conformance/test_fail_quiet.py. No keep-row
                 file is touched: orchestrator.py and
                 regime_engine.py are not in FAIL_QUIET_KEEP;
                 bootstrap.py 1607/1825, backtest_runner.py
                 588/794/831, layer_validator.py 1190,
                 factor_neutralizer.py 28/139,
                 massive_ingestor.py 73, massive_ws.py 185/228/344
                 stay unedited. Do not include
                 tools/arch/perfmeasure.py (DIRECT_PROBES is unowned;
                 it still names feelies.services.regime_engine:_update_regime).
                 Do not include portfolio/fill_reconciliation.py.
                 Do not include services/regime_hazard_detector.py.
                 Do not include core/regime_gate.py. Do not include
                 harness/, cli/, .github/workflows/ci.yml.
DELETES:         the engine-package imports of the four helpers from
                 orchestrator. Does not delete the kernel → services
                 pair.
NET DELTA:       src modules 0, public symbols 0, branch points 0
                 (underscored helpers relocate; not public).
ROLLBACK:        revert the commit. Independently revertible from
                 T-05b until T-05b lands; orchestrator.py is shared with
                 T-05b and is not independently revertible once T-05b
                 lands.
```

```
STEP:            T-05b
CLOSES:          nothing. Drops kernel → services. Five import
                 tiers stays BROKEN. 7 → 6. G40 stays CLOSED.
PROBLEM:         After T-05a, kernel still imports three names from
                 feelies.services, not two. feelies.kernel.orchestrator
                 is the only kernel file that imports that package.
                 RegimeEngine from feelies.services.regime_engine
                 (runtime, l.194) and RegimeHazardDetector from
                 feelies.services.regime_hazard_detector (runtime,
                 l.195). Both are injected optional (| None = None);
                 stored; never default-constructed in kernel. None
                 is not the illegal import (T-04b's default was
                 Top1SelectionPolicy()). Bootstrap already constructs
                 and passes them. Runtime named calls: restore on
                 the engine at :3293; posterior(quote) at :374;
                 state_names at :377; checkpoint() at :249;
                 RegimeHazardDetector.reset at :2388; detect at
                 :425. After T-05a the returned helpers name those.
                 calibrate, calibrated, discriminability, and
                 discriminability_for_symbol stay getattr inside
                 _calibrate_regime_engine / _update_regime. reset is
                 also reachable via getattr through _maybe_reset;
                 that walk does not list either engine, and named
                 reset is the detector. No public orchestrator
                 property hands either instance out — no
                 harness/cli extra surface (T-03). services/
                 regime_engine.py already defines a RegimeEngine
                 Protocol (state_names, n_states, posterior,
                 current_state, reset(symbol), checkpoint, restore)
                 that is wider than kernel's named calls and lives in
                 the engine package; importing that Protocol is still
                 kernel → services.
                 Third name, function, no Protocol can replace it:
                 regime_posterior_entropy_nats from
                 feelies.services.regime_engine (runtime, l.194),
                 called at _update_regime :403 to fill
                 RegimeState.posterior_entropy_nats. Signature
                 (posteriors: Sequence[float]) -> float. Pure
                 Shannon entropy in nats; no orchestrator, no engine
                 instance, no state. T-05a PROBLEM counted six names
                 (four helpers + two types). The function lived in
                 the same services module as _update_regime and
                 needed no kernel import until the helper returned
                 with the body unchanged. Other callers
                 (tests/services, tests/core, tests/determinism,
                 scripts/regime_diagnostics.py, services/__init__.py)
                 are not kernel. Honest owner is core, same shape as
                 T-04a's Signal predicates. Leaving it on the kernel
                 import leaves the pair and the pin at 7.
WHY THIS OWNER:  T5 core already owns the names kernel may use. The
                 illegal edge is kernel naming Engine 3 for injected
                 types. The invert is a core Protocol module named
                 for the regime concern, not relocating HMM3 or the
                 detector, not deleting the TYPE_CHECKING-equivalent
                 runtime import, and not appending to
                 core/regime_gate.py (that file is the gate DSL).
                 The helpers' return in T-05a does not replace this
                 bind.
REFACTOR PATH:   one commit. Mechanism: Selection-style Protocols
                 plus the pure entropy function in a new
                 feelies.core.regime_protocol (named for the
                 regime concern, not the step; one module per
                 engine concern). Kernel retargets both type
                 annotations and the entropy import there.
                 Required Protocol surface is every named kernel
                 call after T-05a, not a copy of the services
                 Protocol. Structural; no subclassing on
                 HMM3StateFractional or RegimeHazardDetector. No
                 object/Any, no getattr fallback, no sys.modules,
                 no TYPE_CHECKING-only move, no re-export of the
                 Protocol from the engine package as the cut, no
                 kernel_ports.py. Do not inline the entropy formula
                 in _update_regime; do not copy the body.
                 Per-name Protocol surface:
                 RegimeEngine: restore(data: bytes) -> None (named
                 at :3293); posterior(quote: NBBOQuote) ->
                 list[float] (named in returned _update_regime);
                 state_names -> Sequence[str] (named there);
                 checkpoint() -> bytes (named in returned
                 _checkpoint_regime_snapshot). Do not put
                 calibrate, calibrated, discriminability, or
                 discriminability_for_symbol on the Protocol —
                 getattr, T-03. Do not put n_states, current_state,
                 or reset(symbol: str) on it — kernel never names
                 them (current_state is _regime_label_for, not
                 imported; services reset(symbol) is the wrong arity
                 for getattr reset()).
                 RegimeHazardDetector: reset() -> None (named at
                 :2388); detect(prev: RegimeState | None,
                 curr: RegimeState) -> RegimeHazardSpike | None
                 (named in returned _maybe_publish_hazard_spike).
                 regime_posterior_entropy_nats(posteriors:
                 Sequence[float]) -> float — move the body from
                 services.regime_engine into this module; kernel
                 imports it from core. services.regime_engine
                 re-exports the name from core (alias, T-04a);
                 that is not the cut. Import Signal/quote/state/
                 spike types from feelies.core.events. Import
                 nothing from feelies.services.
                 (1) add src/feelies/core/regime_protocol.py with those
                 two Protocols and the entropy function. Nested winner
                 types are not needed; detect's return is already a
                 core event.
                 (2) orchestrator: import both Protocols and
                 regime_posterior_entropy_nats from
                 feelies.core.regime_protocol; drop
                 feelies.services.regime_engine and
                 feelies.services.regime_hazard_detector. Keep
                 constructor optionality and the call sites.
                 Leave getattr as getattr. Leave the services
                 Protocol in place for services/bootstrap/alpha —
                 that re-export is not the cut.
                 (3) services/regime_engine.py: delete the def;
                 `from feelies.core.regime_protocol import
                 regime_posterior_entropy_nats as
                 regime_posterior_entropy_nats`. Leave HMM3 and
                 the services Protocol unedited.
                 (4) drop ("feelies.kernel", "feelies.services") from
                 _TIER_RESIDUALS in the same commit (equality, 6
                 remain).
                 (5) new core module: _FILE_OWNERS row and README
                 citation in this commit (S-21), same as T-03.
BLAST RADIUS:    boundary
VALIDATED BY:    test_five_import_tiers equals the 6-pair pin;
                 test_twelve_engine_independence KEPT at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py (APP
                 oracle). No XPASS. lint-imports: Five import tiers
                 still BROKEN, Twelve engine module sets KEPT. A
                 new twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the fingerprint,
                 _BASELINE_CONFIG_HASH. The ingest/replay body is
                 unmoved; only which module kernel names for the two
                 injected types changes. A moved HASH or COUNT
                 means the Protocol call was not a transparent
                 substitute (surface, attribute, or a silent
                 default) — STOP, do not re-pin.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/core/regime_protocol.py
                 src/feelies/services/regime_engine.py
                 tests/conformance/test_import_contracts.py
                 tests/docs/test_prompt_coverage_map.py
                 docs/prompts/README.md
                 services/regime_engine.py is the T-04a
                 selection_policy.py re-export only: replace the
                 def with an alias from core; do not invert HMM3
                 or the services Protocol. Do not retarget
                 tests/scripts/services/__init__.py — the re-export
                 is not the cut. Do not edit
                 services/regime_hazard_detector.py. Do not edit
                 bootstrap.py. Do not include
                 tests/conformance/test_fail_quiet.py. No keep-row
                 file is touched. Do not include
                 core/regime_gate.py. Do not include
                 harness/, cli/, .github/workflows/ci.yml.
DELETES:         the kernel → services pair; the services.regime_engine
                 and services.regime_hazard_detector imports from
                 orchestrator.
NET DELTA:       src modules +1, public symbols +3, branch points 0
                 (RegimeEngine and RegimeHazardDetector Protocols,
                 and regime_posterior_entropy_nats).
ROLLBACK:        revert the commit. The new Protocol module reverts
                 with it. Independently revertible from T-06 until
                 T-06 lands; orchestrator.py is shared with T-05a
                 and T-06 and is not independently revertible once T-06
                 lands.
```
