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

