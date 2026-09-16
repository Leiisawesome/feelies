# PHASE 9 — Reset invocation

**Basis.** Five import tiers closed at T-09z on `arch/exec` (`4e707c17`).
G40 is CLOSED. Five import tiers KEPT. Twelve-engine independence is KEPT
at zero pairs. R6 still exercises 14 of 31 resets. Current-state claims
carry their original label; new material is `specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        Reset invocation
BASE:            arch/exec 4e707c17 (post-T-09z reference
                 baseline; Five import tiers KEPT; G40
                 CLOSED)
CLOSES:          invoked == MUST_INVOKE on the union of
                 FIX-1 and the four configs, and
                 DECLARED_UNINVOKED equal to the nine
                 never-rows (InMemoryEventLog,
                 RthEntryFillGate, MetricSummary,
                 _WarmTimestampIndex, QuoteReplayObserver,
                 QuoteTraceIndex, MassiveHistoricalIngestor,
                 InMemoryKillSwitch, IBOrderRouter).
                 This is not G04. S-15 closed G04 (S16
                 totality + R6 existence). This campaign
                 closes R6's vacuity: resets that exist
                 and are never entered on a second run in
                 the same process.
DOES NOT CLOSE:  G10, G28, G32, G36, G39, G41, G42, G44,
                 G45, G46; S-34f groups g–o (15 engine
                 bodies; Inv-8 is a different campaign);
                 perfmeasure.py DIRECT_PROBES; G6 empty
                 depends_on_sensors; S-04c;
                 serialization.py fail-open; verify_step
                 frozen bugs; 152 research cache days;
                 keep-row squeezes vs ruff format (T-04b);
                 engine-to-kernel residual 9 pairs (the
                 pin is the detector, not a gap this
                 campaign owns). The four EXEMPTION tests
                 stay environmental. Deliberately not this
                 campaign: IBOrderRouter and paper_rth;
                 for_new_run=False; the no-op-body class of
                 leak that only warm == cold can catch;
                 the three deletable resets
                 (RthEntryFillGate, MetricSummary,
                 _WarmTimestampIndex) that stay because
                 S16 owns them — deleting them fails S16
                 unless the durable-exemption set grows,
                 which is a G04 contract change.
STANDING
INVARIANTS:      Oracle frozen at exec-tools-v1. Never run
                 scripts/rebaseline_parity_hashes.py.
                 Hold all 64 HASH/COUNT constants, the
                 fingerprint
                 (de5d64b019075de0ca271b53834f342623f2b1a39f23ff73910e45b0bc90beb6),
                 and _BASELINE_CONFIG_HASH unless a step
                 names a re-pin.
                 Accepted baseline failures are only
                 test_after_hours_reject_surfaces_as_rejected,
                 test_g12_cost_exceeds_disclosure_alert,
                 test_multi_symbol_subscribe,
                 test_sustained_quotes_with_idle_ticks.
                 A failure outside that set is a STOP.
                 Both import pins from Five import tiers
                 hold: Five import tiers is empty
                 _TIER_RESIDUALS and statuses KEPT;
                 Twelve engine module sets is KEPT at
                 zero pairs. Engine-to-kernel equals the
                 9-pair pin. Shrinking either import pin
                 happens in lockstep with the cut that
                 drops the pair, in the same commit.
                 Do not restore continue-on-error.
                 Do not invent suffixes for g–o.
                 Specific to this campaign: the new tapes
                 are synth conformance fixtures and must
                 never assert LOCKED_PARITY_BASELINES,
                 _BASELINE_TRADE_PARITY_HASH, or
                 _BASELINE_FILL_COUNT. A new tape that
                 runs the APP oracle is a declared break,
                 not a hold. Warm == cold is an equality
                 of two runs in one test, not a golden
                 hash. Moving a name into MUST_INVOKE
                 happens in the same commit as the config
                 that constructs the object.
NON-CUTS:        A re-export without retarget is not a cut.
                 A TYPE_CHECKING-only move is not a cut.
                 A sys.modules lookup (or optional getattr
                 fallback) is not a cut.
                 Widening a type to object or Any is not a
                 cut.
                 A deleted TYPE_CHECKING import is not a
                 cut; retarget the annotation to a legal
                 owner.
                 A spy that invokes a reset it cannot call
                 with zero args (HMM3StateFractional.reset
                 (symbol), InMemoryKillSwitch.reset
                 (*, operator, audit_token)) is not a
                 detector; it is a TypeError.
                 An AST walk of Orchestrator.reset in
                 place of the runtime spy is not a
                 detector; it cannot type the getattr bus
                 walk.
                 Deleting a reset whose absence S16 would
                 report is not a cleanup; it is a G04
                 exemption.
                 Moving a name into MUST_INVOKE in a
                 different commit from the config that
                 constructs it is not a pin movement; the
                 spy is silent or red for the wrong
                 reason.
LADDER:          Owed count is names not yet in
                 MUST_INVOKE: the thirteen DECLARED rows
                 marked owed, plus StrategyPositionStore
                 and FillAttributionLedger (no reset()
                 today, so they are not in either
                 frozenset). The nine never-rows stay in
                 DECLARED_UNINVOKED through close.
                 Shared-file steps are sequential, not
                 independently revertible.
                 Step 2 may split on FILES span
                 (portfolio+kernel vs
                 services+signals+kernel). That split is
                 blast radius, not a seventh behaviour.
                 A rung that does not move a name into
                 MUST_INVOKE does not move the pin.
                   now     15 owed (13 DECLARED + 2 books)
                   1  pin: runtime spy on FIX-1;
                      MUST_INVOKE = 18, DECLARED = 22     15
                   2  default-path leaks: StrategyPositionStore
                      + FillAttributionLedger +
                      HMM3StateFractional.reset(symbol=None)
                      + HorizonSignalEngine cascades
                      gate.reset(); FIX-1 spy must see
                      the four names                         11
                   3  PORTFOLIO config: CompositionEngine,
                      UniverseSynchronizer,
                      CrossSectionalTracker,
                      HorizonMetricsCollector                 7
                   4  hazard + decouple config:
                      HazardExitController, ExitComposer,
                      DeferralCapController,
                      RegimeHazardDetector                    3
                   5  passive_limit + moc_session_date:
                      PassiveLimitOrderRouter,
                      MocFillController                       1
                   6  injected MassiveNormalizer
                      (BACKTEST, not paper_rth)               0
                 Close: invoked == MUST_INVOKE on the
                 union of FIX-1 and the four configs;
                 DECLARED_UNINVOKED equals the nine
                 never-rows.
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template).

```
STEP:            R-01
CLOSES:          nothing. Owed count stays 15. Does not move a
                 name into MUST_INVOKE. A detector landing
                 green is the declared outcome, same shape as
                 T-07c: an unchanged count is not a failed
                 rung. G04 stays CLOSED. This is not G04.
PROBLEM:         S-15 closed G04: every mutator has a reset
                 path (S16) and Orchestrator.reset exists (R6).
                 R6's fingerprint is (event type, sequence) on
                 FIX-1. Seventeen of the 31 resets are never
                 entered. S16 does not record invocation. A
                 second run in the same process can inherit
                 state the determinism corpus never sees,
                 because every tape starts from a fresh
                 process. Nothing today fails when a MUST_INVOKE
                 class is skipped by the cascade.
WHY THIS OWNER:  Conformance owns the invocation pin. Production
                 reset bodies stay with later rungs. Landing the
                 spy on FIX-1 first is what makes rungs 2–6's
                 name-moves a fail-before rather than a silent
                 set edit.
FILES:           tests/conformance/test_reset_invocation.py
                 Do not edit src/. Do not edit
                 tests/conformance/test_reset_paths.py,
                 tests/conformance/test_recovery_determinism.py,
                 tests/conformance/test_import_contracts.py,
                 tests/acceptance/test_backtest_app_baseline.py.
                 No keep-row file is touched. The probe edits
                 src/feelies/kernel/orchestrator.py only for the
                 mutation and restores it; that file is not in
                 the commit.
REFACTOR PATH:   one commit. Mechanism: a runtime spy wrapping
                 reset on the named classes, installed after
                 the first boot+run_backtest and torn down
                 after orchestrator.reset() returns. The spy
                 does not wrap run_backtest. Matching is by
                 MRO name so _BacktestMetricCollector counts
                 as InMemoryMetricCollector. Assert MUST_INVOKE
                 ⊆ invoked and invoked ∩ DECLARED_UNINVOKED
                 == ∅. An AST walk of Orchestrator.reset is
                 not this detector; it cannot type the getattr
                 bus walk.
                 MUST_INVOKE:
                 frozenset({
                   "AlphaBudgetRiskWrapper",
                   "AlphaRegistry",
                   "BacktestOrderRouter",
                   "BasicRiskEngine",
                   "EventBus",
                   "HorizonAggregator",
                   "HorizonScheduler",
                   "HorizonSignalEngine",
                   "InMemoryMetricCollector",
                   "MemoryPositionStore",
                   "Orchestrator",
                   "RegimeStateCache",
                   "SensorRegistry",
                   "SequenceGenerator",
                   "SimulatedClock",
                   "StateMachine",
                   "StopExitController",
                   "_HaltTradeability",
                 })
                 DECLARED_UNINVOKED:
                 frozenset({
                   "CompositionEngine",          # owed, PORTFOLIO tape
                   "CrossSectionalTracker",      # owed, PORTFOLIO tape
                   "DeferralCapController",      # owed, decouple tape
                   "ExitComposer",               # owed, decouple tape
                   "HMM3StateFractional",        # owed, default path; reset(symbol)
                   "HazardExitController",       # owed, hazard tape
                   "HorizonMetricsCollector",    # owed, PORTFOLIO tape
                   "IBOrderRouter",              # never: IB / paper_rth
                   "InMemoryEventLog",           # never: the tape
                   "InMemoryKillSwitch",         # never: operator kwargs; Inv-11
                   "MassiveHistoricalIngestor",  # never: ingest, not replay
                   "MassiveNormalizer",          # owed, injected-normalizer BACKTEST
                   "MetricSummary",              # never: parent clear; S16 owns reset
                   "MocFillController",          # owed, moc_session_date
                   "PassiveLimitOrderRouter",    # owed, execution_mode=passive_limit
                   "QuoteReplayObserver",        # never: CLI; reset hits monotonic
                   "QuoteTraceIndex",            # never: nested in that observer
                   "RegimeGate",                 # owed, default path; no cascade
                   "RegimeHazardDetector",       # owed, hazard tape
                   "RthEntryFillGate",           # never: no-op body; S16 owns reset
                   "UniverseSynchronizer",       # owed, PORTFOLIO tape
                   "_WarmTimestampIndex",        # never: parent clear; S16 owns reset
                 })
                 StrategyPositionStore and FillAttributionLedger
                 have no reset() and are in neither set. Do not
                 wrap them.
                 Two resets cannot be called with zero args:
                 HMM3StateFractional.reset(symbol) and
                 InMemoryKillSwitch.reset(*, operator,
                 audit_token). The spy wraps the original and
                 forwards *args, **kwargs. The test never
                 calls those two. They sit in
                 DECLARED_UNINVOKED; a zero-arg call from the
                 cascade TypeErrors the original and the test
                 fails. Inventing dummy kwargs to "succeed"
                 those calls is not a detector. Do not special-
                 case them by skipping the wrap.
                 Order: (1) add test_reset_invocation.py with
                 the two frozensets and the spy around
                 orchestrator.reset() on the FIX-1 / R6
                 construction. On this tree it passes by
                 construction — that is not the proof.
                 (2) probe, T-07c shape. Drop
                 `_maybe_reset(self._positions)` in
                 src/feelies/kernel/orchestrator.py (not in
                 FILES; not in the commit). Run only the new
                 test. It MUST fail naming
                 MemoryPositionStore. Restore orchestrator.py.
                 Confirm it is byte-identical to HEAD. Re-run
                 the test green. Report the fail-then-green
                 output and the restore hash at the gate.
                 Without the probe the pin is decorative.
                 (3) commit the test only. No production reset
                 body is written or edited in this step.
BLAST RADIUS:    local — tests/ only
VALIDATED BY:    test_reset_invocation spy equals the 18-name
                 MUST_INVOKE pin on FIX-1; probe failed-before
                 naming MemoryPositionStore then passed-after
                 restore; test_five_import_tiers empty
                 _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at zero
                 pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. No XPASS. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A moved
                 HASH or COUNT is a STOP, do not re-pin. A
                 test-only change that moves a hash means the
                 file was not test-only. Do not assert
                 LOCKED_PARITY_BASELINES.
DELETES:         nothing. Owed stays 15. The 18-name set is a
                 new equality pin, not a dropped G04 exemption.
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert the commit. Independently revertible
                 until R-02 lands; test_reset_invocation.py is
                 shared with R-02 through R-06.
```

```
STEP:            R-02
CLOSES:          nothing. Owed 15 to 11. Does not close G04.
                 Moves four names into MUST_INVOKE in the same
                 commit as the bodies that make them reachable:
                 StrategyPositionStore, FillAttributionLedger,
                 HMM3StateFractional, RegimeGate. The nine
                 never-rows stay in DECLARED_UNINVOKED. G04
                 stays CLOSED. This is not G04.
PROBLEM:         Four default-path leaks are live on every
                 tape today. Unlike R-03 through R-06 they
                 need no widened config: build_platform
                 constructs the two books unconditionally,
                 PlatformConfig.regime_engine defaults to
                 hmm_3state_fractional, and every SIGNAL alpha
                 carries a RegimeGate. A second run in the
                 same process inherits:
                 (1) StrategyPositionStore — per-strategy
                 qty, avg entry, realized/unrealized PnL,
                 fees, marks, open-episode timestamps. get()
                 plants an empty sub-book via _get_store, so
                 _stores accumulates on reads as well as
                 writes. MemoryPositionStore.reset on
                 self._positions does not touch these
                 sub-books. Orchestrator.reset does not name
                 _strategy_positions.
                 (2) FillAttributionLedger — _records and
                 _cumulative_allocations. SequenceGenerator
                 reset recycles order_ids, so a leftover
                 record attributes run-2 fills to run-1
                 contributions.
                 (3) HMM3StateFractional — _posteriors,
                 _last_update_seq, _last_quote_ts_ns. Tape
                 quote.sequence is on the event, so
                 posterior() returns the leftover cache
                 when seq matches. reset(symbol) is
                 required-positional, so _maybe_reset would
                 TypeError; orchestrator does not name
                 _regime_engine and the bus walk does not
                 reach it.
                 (4) RegimeGate latch — per-symbol ON/OFF
                 in gate._state. HorizonSignalEngine.reset
                 clears its own caches and nested
                 SequenceGenerators and does not call
                 gate.reset().
WHY THIS OWNER:  The FIX-1 spy is the pin. Names move in the
                 same commit as the config that constructs
                 them (they are already constructed) and the
                 bodies that reach them. Production reset
                 bodies for PORTFOLIO / hazard / passive_limit
                 / injected-normalizer stay with later rungs.
FILES:           src/feelies/portfolio/strategy_position_store.py
                 src/feelies/portfolio/fill_attribution.py
                 src/feelies/kernel/orchestrator.py
                 src/feelies/services/regime_engine.py
                 src/feelies/signals/horizon_engine.py
                 tests/conformance/test_reset_invocation.py
                 Do not edit test_reset_paths.py,
                 test_recovery_determinism.py,
                 test_import_contracts.py,
                 test_backtest_app_baseline.py.
                 Do not edit tests/services/test_regime_engine.py
                 or tests/kernel/test_orchestrator.py: the
                 one-arg callers stay as they are.
                 No keep-row file is touched.
REFACTOR PATH:   one commit.
                 (1) Pin first. Move StrategyPositionStore
                 and FillAttributionLedger from neither
                 frozenset into MUST_INVOKE. Move
                 HMM3StateFractional and RegimeGate from
                 DECLARED_UNINVOKED into MUST_INVOKE. Wrap
                 the two new reset() names; keep wrapping
                 HMM3 and RegimeGate. Run
                 test_reset_invocation. It MUST fail naming
                 those four. That fail-before is the pin
                 movement, not the proof of each path.
                 (2) StrategyPositionStore.reset clears
                 _stores. Optional store.reset() on
                 children is not a new name
                 (MemoryPositionStore is already
                 MUST_INVOKE via _positions). Orchestrator:
                 _maybe_reset(self._strategy_positions)
                 immediately after
                 _maybe_reset(self._positions).
                 (3) FillAttributionLedger.reset clears
                 _records and _cumulative_allocations.
                 No new call site: orchestrator already
                 _maybe_resets self._fill_ledger as a
                 no-op. Adding the method alone changes
                 behaviour.
                 (4) HMM3StateFractional.reset(self, symbol:
                 str | None = None). symbol=None clears
                 _posteriors, _last_update_seq,
                 _last_quote_ts_ns, and
                 _scaled_transition_cache. It must NOT
                 clear _calibrated, _emission, or
                 _emission_by_symbol:
                 _calibrate_regime_engine returns early
                 when calibrated is True, and wiping them
                 leaves the second boot on placeholder
                 emissions. One-arg form keeps today's
                 three pops. Callers that must keep
                 working: tests/services/test_regime_engine.py:98
                 engine.reset("AAPL"); :427
                 engine.reset("AAPL") (preserves MSFT);
                 tests/kernel/test_orchestrator.py:148
                 stub def reset(self, symbol: str);
                 RegimeEngine.reset(self, symbol: str)
                 at regime_engine.py:75 (widen the
                 Protocol in the same file). No src/
                 production caller of the one-arg form
                 exists today. Orchestrator:
                 _maybe_reset(self._regime_engine) so the
                 zero-arg cascade hits the default.
                 (5) HorizonSignalEngine.reset: for
                 registered in self._signals:
                 registered.gate.reset() with no args
                 (RegimeGate.reset(symbol=None) already
                 clears every latch). FIX-1's null_alpha
                 gate is on_condition True / off_condition
                 False, so leftover ON and cold-start
                 False both sit ON after the first
                 evaluate and evaluate returns None; C1
                 and R6 do not see it. A P(state) gate
                 leftover ON would.
                 T-08d closure: StrategyPositionStore.reset
                 optionally names MemoryPositionStore
                 (already reachable). FillAttributionLedger
                 and HMM3 bodies name nothing new. The
                 gate loop names RegimeGate. RegimeGate.reset
                 only clears _state. Stop.
                 (6) Four probes, uncommitted, one per
                 reachability path. One probe does not
                 suffice: the four paths are independent,
                 and a combined drop fails on a set
                 without showing which path held.
                 (a) drop _maybe_reset(self._strategy_positions)
                     → MUST_INVOKE not entered:
                     ['StrategyPositionStore']
                 (b) delete FillAttributionLedger.reset
                     → MUST_INVOKE not entered:
                     ['FillAttributionLedger']
                 (c) drop _maybe_reset(self._regime_engine)
                     → MUST_INVOKE not entered:
                     ['HMM3StateFractional']
                 (d) drop the gate.reset() loop
                     → MUST_INVOKE not entered:
                     ['RegimeGate']
                 Restore each byte-identical with a hash
                 before the next. Re-run green after the
                 last restore. Without the four probes
                 the pin move plus the bodies pass by
                 construction and protect nothing.
BLAST RADIUS:    platform-wide — kernel + portfolio +
                 services + signals + the shared spy file
VALIDATED BY:    test_reset_invocation spy equals MUST_INVOKE
                 on FIX-1 including the four new names;
                 DECLARED_UNINVOKED no longer contains HMM3
                 or RegimeGate and still equals the remaining
                 owed-plus-never set; four probes
                 failed-before naming each of the four then
                 passed-after restore; test_five_import_tiers
                 empty _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. One-arg
                 test_regime_engine reset("AAPL") cases
                 unmoved. No XPASS. A new twelve-engine pair
                 is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. Do
                 not re-pin. Locked hashes are cold-start
                 single-run and do not call
                 Orchestrator.reset(for_new_run=True). A
                 reset-then-replay payload can differ
                 (HMM3 posteriors keyed by tape sequence,
                 leftover gate latches, leftover slice
                 books, leftover attribution order_ids)
                 while R6's (event type, sequence)
                 fingerprint stays green. Clearing these
                 is what makes warm equal cold, not a
                 re-pin. Do not assert
                 LOCKED_PARITY_BASELINES.
DELETES:         nothing. Owed 15 to 11 by moving four
                 names into MUST_INVOKE, not by dropping
                 a G04 exemption.
NET DELTA:       src modules 0, public symbols 0, branch
                 points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from a later R-0* that edits
                 test_reset_invocation.py or
                 orchestrator.py. Shared with R-03
                 through R-06 on the spy file; shared with
                 any later rung that names a new
                 _maybe_reset on orchestrator.py.
```

```
STEP:            R-03
CLOSES:          nothing. Owed 11 to 7. Does not close G04.
                 Moves four names into MUST_INVOKE in the same
                 commit as the PORTFOLIO config that constructs
                 them: CompositionEngine, UniverseSynchronizer,
                 CrossSectionalTracker, HorizonMetricsCollector.
                 The nine never-rows stay in DECLARED_UNINVOKED.
                 G04 stays CLOSED. This is not G04.
PROBLEM:         The four PORTFOLIO objects are absent on FIX-1
                 because build_platform skips
                 _create_composition_layer when
                 registry.portfolio_alphas() is empty. Once a
                 layer: PORTFOLIO spec is loaded, all four are
                 constructed inside that function. The function
                 returns only CompositionEngine (stored as
                 orchestrator._composition_engine). The other
                 three are locals that attach() and are dropped.
                 EventBus.reset() only zeroes cascade depth;
                 subscriptions stay. The getattr bus walk after
                 _bus.reset() therefore reaches every attached
                 owner. All four are reachable by that walk.
                 CompositionEngine is also reached by the
                 existing named _maybe_reset(self._composition_engine).
                 This is a config widen, not a body fix. No new
                 _maybe_reset is required. No src/ edit is
                 required. A second run in the same process
                 currently inherits, on any PORTFOLIO tape:
                 (1) CompositionEngine — leftover intent
                 SequenceGenerator state.
                 (2) UniverseSynchronizer — leftover snapshot
                 and signal caches and emission dedup.
                 (3) CrossSectionalTracker — leftover snapshots
                 and completeness by barrier.
                 (4) HorizonMetricsCollector — leftover counters
                 and last-solver-status map.
WHY THIS OWNER:  The FIX-1 spy is the pin. The four classes
                 already expose reset() and are already wrapped.
                 Names move in the same commit as the config
                 that constructs them. Production reset bodies
                 for hazard / passive_limit / injected-normalizer
                 stay with later rungs.
FILES:           tests/conformance/test_reset_invocation.py
                 tests/conformance/fixtures/portfolio/upstream_signal.alpha.yaml
                 tests/conformance/fixtures/portfolio/null_portfolio.alpha.yaml
                 Do not edit src/. Do not edit
                 test_reset_paths.py,
                 test_recovery_determinism.py,
                 test_import_contracts.py,
                 test_backtest_app_baseline.py.
                 No keep-row file is touched. Probe mutations
                 of orchestrator.py are restored; that file is
                 not in the commit.
                 Yaml is committed fixtures, not inlined.
                 _config() today returns PlatformConfig with
                 Path specs and takes no tmp_path; FIX-1's
                 null_alpha is already a committed Path.
                 Inlining would force tempfile writes or a
                 tmp_path argument, and would bloat the spy
                 file that R-04 through R-06 also edit.
                 A fixture makes universe ⊆ {AAPL, MSFT} a
                 reviewable artifact rather than a string.
REFACTOR PATH:   one commit.
                 Helper, landed on this rung and reused by
                 later ones:
                 def _config(
                     tape_id: Literal[
                         "fix1",
                         "portfolio",
                         "hazard_decouple",
                         "passive_limit",
                         "injected_normalizer",
                     ] = "fix1",
                 ) -> PlatformConfig: ...
                 _TAPES is the tuple actually booted and
                 unioned. This rung starts it at ("fix1",)
                 and appends "portfolio". The other three
                 ids exist on the signature; their branches
                 raise until their rung. Do not add a second
                 helper.
                 The test boots every id in _TAPES under the
                 spy, unions invoked, and asserts
                 MUST_INVOKE ⊆ invoked and
                 invoked ∩ DECLARED_UNINVOKED == ∅.
                 That is the campaign close shape (union of
                 FIX-1 and the configs), not a per-tape
                 expected set.
                 PORTFOLIO tape PlatformConfig:
                 symbols = frozenset({"AAPL", "MSFT"})
                 (FIX-1's _UNIVERSE, so _synth_events is
                 reusable). A universe that adds any other
                 symbol (wiring fixture's GOOG, the template's
                 ten names) would force a wider synth.
                 horizons_seconds includes 300.
                 alpha_specs = [upstream_signal, null_portfolio].
                 sensor_specs = _SENSOR_SPECS.
                 regime_engine = hmm_3state_fractional.
                 enforce_trend_mechanism = False.
                 factor_loadings_dir stays None (the default)
                 so _enforce_factor_loadings_freshness returns
                 immediately.
                 account_equity and session_open_ns as FIX-1.
                 Minimal upstream SIGNAL yaml:
                 schema_version "1.1", layer SIGNAL,
                 alpha_id upstream_null, version, description,
                 hypothesis, falsification_criteria, symbols
                 [AAPL, MSFT], horizon_seconds 300,
                 depends_on_sensors [ofi_ewma], regime_gate
                 (on True / off False or the null_alpha
                 shape), cost_arithmetic with
                 margin_ratio ≥ 1.5, signal: evaluate
                 returns None. Same conservation as FIX-1:
                 no Signal, so the book stays flat.
                 Minimal PORTFOLIO yaml:
                 schema_version "1.1", layer PORTFOLIO,
                 alpha_id null_portfolio, version,
                 description, hypothesis,
                 falsification_criteria, horizon_seconds 300,
                 universe [AAPL, MSFT] (G10; ⊆ FIX-1),
                 depends_on_signals [upstream_null],
                 factor_neutralization false (G11 disclosure;
                 true is legal but unneeded),
                 cost_arithmetic with margin_ratio ≥ 1.5.
                 No construct: block — the default pipeline
                 is enough to construct the four objects.
                 (1) Pin first. Move the four names from
                 DECLARED_UNINVOKED into MUST_INVOKE.
                 _TAPES stays ("fix1",). Helper signature
                 is in place with only the fix1 branch live.
                 Run the spy. It MUST fail naming
                 ['CompositionEngine', 'CrossSectionalTracker',
                 'HorizonMetricsCollector', 'UniverseSynchronizer'].
                 That fail-before is the pin movement.
                 (2) Append "portfolio" to _TAPES and land
                 the two yaml fixtures plus the portfolio
                 branch of _config. The spy MUST pass.
                 MUST_INVOKE 22 to 26.
                 (3) Closure: CompositionEngine.reset names
                 SequenceGenerator (_intent_seq).
                 UniverseSynchronizer.reset names
                 SequenceGenerator (_ctx_seq).
                 HorizonMetricsCollector.reset names
                 SequenceGenerator (_metric_seq).
                 CrossSectionalTracker.reset names nothing.
                 SequenceGenerator is already MUST_INVOKE.
                 Ranker / neutralizer / sector matcher /
                 optimizer have no reset(). Stop.
                 (4) Probes, uncommitted, restore
                 byte-identical between each.
                 Two reachability paths, not four. The three
                 locals share the getattr bus walk;
                 CompositionEngine is on that walk and also
                 on the named _maybe_reset. A combined drop
                 of the walk names a set because they share
                 a path, not because the probe is coarse.
                 Per-name probes of the same walk would not
                 show a different cascade.
                 Pin fail-before already named all four
                 (not constructed). After the config:
                 (a) drop
                 _maybe_reset(self._composition_engine)
                 → CompositionEngine remains entered via
                 the walk. The test MUST still pass for
                 that name. That is the proof the named
                 call is not the PORTFOLIO path and no new
                 _maybe_reset is required.
                 (b) skip the getattr bus walk (the
                 _bus._handlers loop) → MUST_INVOKE not
                 entered: ['CrossSectionalTracker',
                 'HorizonMetricsCollector',
                 'UniverseSynchronizer'].
                 CompositionEngine remains entered by name.
                 Restore each. Re-run green after the last
                 restore. Do not probe by deleting
                 CompositionEngine.reset: that is the
                 FillAttributionLedger shape, and here the
                 named call plus the walk both exist.
BLAST RADIUS:    local — tests/ only. Shared spy file with
                 R-04 through R-06.
VALIDATED BY:    spy union equals MUST_INVOKE including the
                 four new names; DECLARED_UNINVOKED no
                 longer contains them and still equals the
                 remaining owed-plus-never set; pin
                 fail-before named all four then passed
                 after the PORTFOLIO tape; probe (a) kept
                 CompositionEngine entered; probe (b) named
                 the three locals; test_five_import_tiers
                 empty _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. No XPASS. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. Do
                 not re-pin. The new tape is a synth
                 conformance fixture and must never assert
                 LOCKED_PARITY_BASELINES,
                 _BASELINE_TRADE_PARITY_HASH, or
                 _BASELINE_FILL_COUNT. A tape that runs the
                 APP oracle is a declared break, not a
                 hold. Locked hashes are cold-start
                 single-run and do not call
                 Orchestrator.reset(for_new_run=True).
DELETES:         nothing. Owed 11 to 7 by moving four
                 names into MUST_INVOKE, not by dropping
                 a G04 exemption.
NET DELTA:       src modules 0, public symbols 0, branch
                 points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from a later R-0* that edits
                 test_reset_invocation.py. Shared with
                 R-04 through R-06 on the spy file.
```

```
STEP:            R-04a
CLOSES:          nothing. Owed 7 to 4. Does not close G04.
                 Moves three names into MUST_INVOKE in the same
                 commit as the hazard-plus-decouple config that
                 constructs them: HazardExitController,
                 ExitComposer, DeferralCapController.
                 RegimeHazardDetector is constructed by the
                 same yaml and stays in DECLARED_UNINVOKED
                 until R-04b, so the pin does not lie in
                 between: MUST_INVOKE does not claim it, and
                 if the cascade reached it this rung would
                 fail DECLARED_UNINVOKED entered.
                 The nine never-rows stay in
                 DECLARED_UNINVOKED. G04 stays CLOSED. This is
                 not G04.
PROBLEM:         The three objects are absent on FIX-1 and
                 on the PORTFOLIO tape because no alpha
                 declares hazard_exit.enabled or
                 safety_exit_policy.mode=decouple_caps_only.
                 Both switches are alpha-manifest fields, not
                 PlatformConfig. One SIGNAL spec can carry
                 both. Once loaded:
                 (1) HazardExitController is stored as
                 orchestrator._hazard_exit_controller,
                 attach() to RegimeHazardSpike and Trade, and
                 is already named
                 _maybe_reset(self._hazard_exit_controller).
                 (2) ExitComposer and DeferralCapController
                 are bootstrap locals that attach()
                 (SafetyStateChange; the cap also Trade) and
                 are not stored on Orchestrator. EventBus.reset
                 only zeroes cascade depth; subscriptions stay.
                 The getattr bus walk reaches both.
                 This is a config widen, not a body fix. No
                 new _maybe_reset. No src/ edit. A fired
                 hazard or a gate-OFF is not the claim:
                 construction plus cascade is. A second run
                 in the same process currently inherits, on
                 any tape that loads this spec:
                 (1) HazardExitController — leftover episode
                 suppression and pending-exit guards, plus
                 SequenceGenerator state.
                 (2) ExitComposer — leftover pending-exit
                 guards and SequenceGenerator state.
                 (3) DeferralCapController — leftover first-safe-
                 off anchors, pending-exit guards, and
                 SequenceGenerator state.
WHY THIS OWNER:  The FIX-1 spy is the pin. The three classes
                 already expose reset() and are already wrapped.
                 Names move in the same commit as the config
                 that constructs them. The detector body stays
                 with R-04b.
FILES:           tests/conformance/test_reset_invocation.py
                 tests/conformance/fixtures/hazard_decouple/hazard_decouple.alpha.yaml
                 Do not edit src/. Do not edit
                 test_reset_paths.py,
                 test_recovery_determinism.py,
                 test_import_contracts.py,
                 test_backtest_app_baseline.py,
                 the PORTFOLIO fixtures, or
                 null_alpha.alpha.yaml.
                 No keep-row file is touched. Probe mutations
                 of orchestrator.py are restored; that file is
                 not in the commit.
                 Yaml is a committed fixture, not inlined.
                 Do not add a second helper — live the
                 hazard_decouple branch of the R-03 helper.
REFACTOR PATH:   one commit.
                 _TAPES currently ("fix1", "portfolio").
                 The helper signature already has
                 hazard_decouple; its branch raises. This
                 rung lives that branch and appends
                 "hazard_decouple" to _TAPES. Do not add a
                 second helper. Do not split into two tape
                 ids.
                 The test boots every id in _TAPES under the
                 spy, unions invoked, and asserts
                 MUST_INVOKE ⊆ invoked and
                 invoked ∩ DECLARED_UNINVOKED == ∅.
                 hazard_decouple tape PlatformConfig:
                 symbols = frozenset(_UNIVERSE)
                 ({AAPL, MSFT}; _synth_events is reusable).
                 horizons_seconds = frozenset({30})
                 (FIX-1's _HORIZON_SECONDS).
                 alpha_specs = [hazard_decouple yaml].
                 regime_engine = hmm_3state_fractional.
                 enforce_trend_mechanism = False.
                 factor_loadings_dir stays None.
                 account_equity and session_open_ns as FIX-1.
                 sensor_specs cannot be _SENSOR_SPECS
                 alone: G17 forces a trend_mechanism block,
                 and G16 rules 5 and 10 then require the
                 family's fingerprint sensor in both
                 l1_signature_sensors and
                 depends_on_sensors, which
                 resolve_signal_dependencies will refuse
                 unless that sensor is in sensor_specs.
                 Include QuoteReplenishAsymmetrySensor
                 (sensor_id quote_replenish_asymmetry,
                 version 1.1.0, subscribes_to NBBOQuote).
                 ofi_ewma is optional on this tape.
                 Minimal SIGNAL yaml, both blocks on one
                 spec:
                 schema_version "1.1", layer SIGNAL,
                 alpha_id matching ^[a-z][a-z0-9_]*$,
                 version, description, hypothesis,
                 falsification_criteria, symbols
                 [AAPL, MSFT], horizon_seconds 30,
                 depends_on_sensors
                 [quote_replenish_asymmetry],
                 regime_gate (on True / off False, FIX-1
                 shape so evaluate actually runs),
                 cost_arithmetic with margin_ratio ≥ 1.5,
                 signal: evaluate returns None (no Signal;
                 book stays flat; a fired hazard is not
                 needed).
                 hazard_exit:
                   enabled: true
                 (literal True; other keys optional —
                 hard_exit_age_seconds derives from
                 2 × expected_half_life_seconds).
                 safety_exit_policy:
                   mode: decouple_caps_only
                   max_hold_after_safe_off: 30
                   hard_exit_age_seconds: 40
                 G17 requires trend_mechanism even with
                 enforce_trend_mechanism False:
                 family INVENTORY (range 5–60s),
                 expected_half_life_seconds 30
                 (horizon/half-life = 1.0 ∈ [0.5, 4.0];
                 INVENTORY max_hold ceiling is 1 × 30),
                 l1_signature_sensors
                 [quote_replenish_asymmetry],
                 failure_signature a non-empty list.
                 (1) Pin first. Move HazardExitController,
                 ExitComposer, DeferralCapController from
                 DECLARED_UNINVOKED into MUST_INVOKE.
                 RegimeHazardDetector stays in
                 DECLARED_UNINVOKED. _TAPES stays
                 ("fix1", "portfolio"). Hazard branch
                 still raises. Run the spy. It MUST fail
                 naming ['DeferralCapController',
                 'ExitComposer', 'HazardExitController'].
                 That fail-before is the pin movement.
                 (2) Append "hazard_decouple" to _TAPES,
                 live the branch, land the yaml. The spy
                 MUST pass. MUST_INVOKE 26 to 29.
                 RegimeHazardDetector is constructed and
                 must NOT appear in invoked. If it does,
                 DECLARED_UNINVOKED entered — stop; that
                 is R-04b leaking into this rung.
                 (3) Closure: each of the three reset()
                 bodies names SequenceGenerator (_seq).
                 SequenceGenerator is already MUST_INVOKE.
                 Stop.
                 (4) Probes, uncommitted, restore
                 byte-identical. R-03 shape, two paths:
                 named call vs shared walk. Pin
                 fail-before already named all three (not
                 constructed). After the config:
                 skip the getattr bus walk on the
                 hazard_decouple tape only
                 (self._hazard_exit_controller is not None;
                 FIX-1 and PORTFOLIO still walk, or the
                 missing set also names HorizonAggregator,
                 StopExitController, and the three
                 PORTFOLIO locals). MUST_INVOKE not
                 entered: ['DeferralCapController',
                 'ExitComposer']. HazardExitController
                 remains entered by name. Restore.
                 Re-run green. Do not probe by deleting
                 HazardExitController.reset: named call
                 plus walk both exist. Do not drop the
                 named _maybe_reset on this rung — that
                 would be R-03 probe (a) for a path this
                 rung is not claiming is redundant.
BLAST RADIUS:    local — tests/ only. Shared spy file with
                 R-04b through R-06.
VALIDATED BY:    spy union equals MUST_INVOKE including the
                 three new names and excluding
                 RegimeHazardDetector; DECLARED_UNINVOKED
                 still contains RegimeHazardDetector and
                 the nine never-rows; pin fail-before named
                 all three then passed after the
                 hazard_decouple tape; walk-skip named the
                 two locals with HazardExitController still
                 entered by name; test_five_import_tiers
                 empty _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. No XPASS. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. Do
                 not re-pin. The new tape is a synth
                 conformance fixture and must never assert
                 LOCKED_PARITY_BASELINES,
                 _BASELINE_TRADE_PARITY_HASH, or
                 _BASELINE_FILL_COUNT. A tape that runs the
                 APP oracle is a declared break, not a
                 hold. Locked hashes are cold-start
                 single-run and do not call
                 Orchestrator.reset(for_new_run=True).
DELETES:         nothing. Owed 7 to 4 by moving three
                 names into MUST_INVOKE, not by dropping
                 a G04 exemption.
NET DELTA:       src modules 0, public symbols 0, branch
                 points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from R-04b or a later R-0*
                 that edits test_reset_invocation.py.
```

```
STEP:            R-04b
CLOSES:          nothing. Owed 4 to 3. Does not close G04.
                 Moves RegimeHazardDetector into MUST_INVOKE
                 in the same commit as the
                 _maybe_reset(self._regime_hazard_detector)
                 that makes it reachable. The nine never-rows
                 stay in DECLARED_UNINVOKED. G04 stays
                 CLOSED. This is not G04.
PROBLEM:         R-04a constructs RegimeHazardDetector
                 (hazard_exit.enabled on the same yaml) and
                 stores it as
                 orchestrator._regime_hazard_detector. It is
                 not a bus subscriber. Orchestrator.reset
                 does not name it. The getattr walk cannot
                 see it. reset() only clears _suppressed, the
                 set of (symbol, engine_name, departing_state)
                 triples that suppress a duplicate spike until
                 the departing state regains dominance. A
                 leftover entry means a second run in the
                 same process skips a hazard exit it should
                 fire.
                 run_backtest and _run_deployment_session
                 already call _reset_regime_session_state,
                 which does call detector.reset(). That is
                 per session, at the start of a pipeline in a
                 process that has not gone through
                 Orchestrator.reset(for_new_run=True).
                 for_new_run already clears
                 _last_regime_state and
                 _regime_bus_published_symbols inline
                 (orchestrator.py:5242–5243) and does not
                 call _reset_regime_session_state. The
                 detector's _suppressed is the one
                 session-scoped map that reset() does not
                 touch. That distinction is the defect: a
                 cold start is clean; an in-process second
                 run is not.
WHY THIS OWNER:  The object is already stored on Orchestrator.
                 The method already exists. Session code
                 already calls it. The missing line is in
                 Orchestrator.reset, next to the named
                 hazard-exit call that R-04a relied on.
                 The spy already wraps the class. The
                 hazard_decouple tape already constructs it.
FILES:           src/feelies/kernel/orchestrator.py
                 tests/conformance/test_reset_invocation.py
                 Do not edit test_reset_paths.py,
                 test_recovery_determinism.py,
                 test_import_contracts.py,
                 test_backtest_app_baseline.py, or the
                 R-04a yaml. No keep-row file is touched.
                 Probe mutations of orchestrator.py are
                 restored except for the committed line.
REFACTOR PATH:   one commit. Pin first, then the call.
                 No new tape. _TAPES already includes
                 "hazard_decouple". Do not add a helper.
                 (1) Pin first. Move RegimeHazardDetector
                 from DECLARED_UNINVOKED into MUST_INVOKE.
                 Do not add the call yet. Run the spy. It
                 MUST fail naming ['RegimeHazardDetector'].
                 That fail-before is the pin movement.
                 (2) In Orchestrator.reset, immediately after
                 `_maybe_reset(self._hazard_exit_controller)`
                 (orchestrator.py:5228 today), add
                 `_maybe_reset(self._regime_hazard_detector)`.
                 _maybe_reset already no-ops on None, so
                 FIX-1 and PORTFOLIO stay unchanged. The
                 spy MUST pass. MUST_INVOKE 29 to 30.
                 (3) Closure: RegimeHazardDetector.reset
                 clears _suppressed only. Names nothing new.
                 Stop.
                 (4) Probe, uncommitted, restore
                 byte-identical. Drop the new line
                 `_maybe_reset(self._regime_hazard_detector)`
                 → MUST_INVOKE not entered:
                 ['RegimeHazardDetector']. Restore.
                 Re-run green. Do not probe by deleting
                 RegimeHazardDetector.reset: that is the
                 FillAttributionLedger shape, and here the
                 missing piece is the named call, not the
                 body. Do not probe by deleting
                 _reset_regime_session_state: that path is
                 session start, not for_new_run, and is
                 not this defect.
BLAST RADIUS:    platform-wide — kernel Orchestrator.reset
                 plus the shared spy file. The new call is
                 inert when the detector is None.
VALIDATED BY:    spy union equals MUST_INVOKE including
                 RegimeHazardDetector; DECLARED_UNINVOKED
                 no longer contains it and still equals
                 the remaining owed-plus-never set; pin
                 fail-before named it then passed after the
                 call; probe dropping the line named
                 RegimeHazardDetector; test_five_import_tiers
                 empty _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. No XPASS. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. Do
                 not re-pin. Locked hashes are cold-start
                 single-run. They never call
                 Orchestrator.reset(for_new_run=True), so
                 they never reach the new line. Session
                 start already reset the detector on those
                 tapes that construct it; this call only
                 matters for an in-process second run. A
                 hash move is a STOP — this rung must not
                 change cold-start behaviour.
DELETES:         nothing. Owed 4 to 3 by moving one name
                 into MUST_INVOKE, not by dropping a G04
                 exemption.
NET DELTA:       src modules 0, public symbols 0, branch
                 points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from a later R-0* that edits
                 test_reset_invocation.py. The orchestrator
                 line without the pin move would leave
                 RegimeHazardDetector in DECLARED_UNINVOKED
                 while the cascade entered it.
```

```
STEP:            R-05
CLOSES:          nothing. Owed 3 to 1. Does not close G04.
                 Moves two names into MUST_INVOKE in the same
                 commit as the PlatformConfig that constructs
                 them: PassiveLimitOrderRouter,
                 MocFillController.
                 The nine never-rows stay in
                 DECLARED_UNINVOKED. G04 stays CLOSED. This is
                 not G04.
PROBLEM:         The two objects are absent on FIX-1, on the
                 PORTFOLIO tape, and on the hazard_decouple
                 tape because those configs leave
                 execution_mode at its default ("market") and
                 moc_session_date at None. Both switches are
                 PlatformConfig fields, not alpha-manifest
                 fields. execution_mode="passive_limit"
                 constructs PassiveLimitOrderRouter.
                 moc_session_date constructs moc_bounds,
                 which is what sets router._moc.
                 PassiveLimitOrderRouter.__init__ leaves
                 self._moc = None when moc_bounds is None, so
                 passive_limit alone does not construct
                 MocFillController. Both switches are needed
                 on one tape. (moc_session_date on a market
                 tape would nest the controller under
                 BacktestOrderRouter, already MUST_INVOKE,
                 and would not construct
                 PassiveLimitOrderRouter.)
                 The router already calls _moc.reset() in its
                 own reset() body. The cascade is the named
                 _maybe_reset(getattr(self._backend,
                 "order_router", None)) plus that nested
                 call. This is a config widen, not a body
                 fix. No new _maybe_reset. No src/ edit.
                 A submitted MOC order is not the claim:
                 construction plus cascade is.
                 moc_session_date can be any ISO date. A date
                 mismatch only rejects a later submit
                 (MOC_SESSION_DATE_MISMATCH). No fill is
                 needed: evaluate returns None, the book
                 stays flat, a resting LIMIT never has to
                 trade.
                 A second run in the same process currently
                 inherits, on any tape that sets both
                 switches:
                 (1) PassiveLimitOrderRouter — leftover
                 resting book, fill counters, last quotes,
                 pending acks, submitted ids, deferred
                 aggressive fills, plus SequenceGenerator
                 state.
                 (2) MocFillController — leftover pending
                 MOC queue (_pending).
WHY THIS OWNER:  The FIX-1 spy is the pin. Both classes
                 already expose reset() and are already
                 wrapped. Names move in the same commit as
                 the config that constructs them.
                 MassiveNormalizer stays with R-06.
FILES:           tests/conformance/test_reset_invocation.py
                 Do not edit src/. Do not edit
                 test_reset_paths.py,
                 test_recovery_determinism.py,
                 test_import_contracts.py,
                 test_backtest_app_baseline.py,
                 the PORTFOLIO fixtures, the R-04a yaml, or
                 null_alpha.alpha.yaml.
                 No keep-row file is touched. No yaml. Probe
                 mutations of
                 src/feelies/execution/passive_limit_router.py
                 are restored; that file is not in the
                 commit.
                 Do not add a second helper — live the
                 passive_limit branch of the R-03 helper.
REFACTOR PATH:   one commit.
                 _TAPES currently ("fix1", "portfolio",
                 "hazard_decouple"). The helper signature
                 already has passive_limit; its branch
                 raises. This rung lives that branch and
                 appends "passive_limit" to _TAPES. Do not
                 add a second helper. Do not split into two
                 tape ids.
                 The test boots every id in _TAPES under the
                 spy, unions invoked, and asserts
                 MUST_INVOKE ⊆ invoked and
                 invoked ∩ DECLARED_UNINVOKED == ∅.
                 passive_limit tape PlatformConfig:
                 symbols = frozenset(_UNIVERSE)
                 ({AAPL, MSFT}; _synth_events is reusable).
                 horizons_seconds = frozenset({30})
                 (FIX-1's _HORIZON_SECONDS).
                 alpha_specs = [_NULL_ALPHA] (FIX-1's
                 committed Path; evaluate returns None).
                 sensor_specs = _SENSOR_SPECS.
                 regime_engine = hmm_3state_fractional.
                 enforce_trend_mechanism = False.
                 factor_loadings_dir stays None.
                 account_equity and session_open_ns as FIX-1.
                 execution_mode = "passive_limit".
                 moc_session_date = any ISO date (a string
                 is enough to build bounds).
                 RthEntryFillGate stays a never-row. The
                 router constructs it and does not call
                 gate.reset(). This rung must not make that
                 call. If it does, DECLARED_UNINVOKED
                 entered.
                 (1) Pin first. Move
                 PassiveLimitOrderRouter and
                 MocFillController from
                 DECLARED_UNINVOKED into MUST_INVOKE.
                 _TAPES stays ("fix1", "portfolio",
                 "hazard_decouple"). Passive_limit branch
                 still raises. Run the spy. It MUST fail
                 naming ['MocFillController',
                 'PassiveLimitOrderRouter']. That
                 fail-before is the pin movement.
                 (2) Append "passive_limit" to _TAPES and
                 live the branch. The spy MUST pass.
                 MUST_INVOKE 30 to 32.
                 (3) Closure: PassiveLimitOrderRouter.reset
                 names SequenceGenerator (_ack_seq) and
                 MocFillController (_moc.reset).
                 SequenceGenerator is already MUST_INVOKE.
                 MocFillController.reset clears _pending
                 only. Names nothing new. Stop.
                 (4) Probe, uncommitted, restore
                 byte-identical. Pin fail-before already
                 named both (not constructed). After the
                 config: drop the nested
                 `if self._moc is not None: self._moc.reset()`
                 in PassiveLimitOrderRouter.reset.
                 MUST_INVOKE not entered:
                 ['MocFillController'].
                 PassiveLimitOrderRouter remains entered by
                 name (absent from the missing set).
                 Restore. Re-run green.
                 That is the right probe: the controller is
                 nested in the router body, not a bus
                 subscriber, so a getattr-walk skip cannot
                 unreach it. Dropping the named
                 _maybe_reset on order_router would unreach
                 both names together and would not show the
                 nested path. Do not probe by deleting
                 MocFillController.reset: the body exists
                 and the missing piece on this rung is
                 construction, not the call. Do not call
                 RthEntryFillGate.reset.
BLAST RADIUS:    local — tests/ only. Shared spy file with
                 R-06.
VALIDATED BY:    spy union equals MUST_INVOKE including the
                 two new names; DECLARED_UNINVOKED no
                 longer contains them and still equals the
                 remaining owed-plus-never set
                 (MassiveNormalizer plus the nine
                 never-rows, including RthEntryFillGate);
                 pin fail-before named both then passed
                 after the passive_limit tape; nested-call
                 drop named MocFillController with
                 PassiveLimitOrderRouter still entered by
                 name; test_five_import_tiers empty
                 _TIER_RESIDUALS and statuses KEPT;
                 test_twelve_engine_independence KEPT at
                 zero pairs (S2); test_engine_kernel_imports_equal_pin
                 equals the 9-pair pin;
                 tests/acceptance/test_backtest_app_baseline.py.
                 S16 unmoved. R6 unmoved. No XPASS. A new
                 twelve-engine pair is a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. Do
                 not re-pin. The new tape is a synth
                 conformance fixture and must never assert
                 LOCKED_PARITY_BASELINES,
                 _BASELINE_TRADE_PARITY_HASH, or
                 _BASELINE_FILL_COUNT. A tape that runs the
                 APP oracle is a declared break, not a
                 hold. Locked hashes are cold-start
                 single-run and do not call
                 Orchestrator.reset(for_new_run=True).
DELETES:         nothing. Owed 3 to 1 by moving two
                 names into MUST_INVOKE, not by dropping
                 a G04 exemption.
NET DELTA:       src modules 0, public symbols 0, branch
                 points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from R-06 or a later R-0*
                 that edits test_reset_invocation.py.
```

