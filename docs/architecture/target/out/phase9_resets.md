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
```
