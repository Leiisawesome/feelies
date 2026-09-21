# PHASE 13 — G44 dead-compute keep

**Basis.** G45 proven-site keep closed on `arch/exec`. G46-01 closed the
orphan matcher (UNIT_UNDETERMINED emptied by fill or S9 exemption).
L-02 caught the third duplicated ledger append at `0ee58817`. G40 is
CLOSED. Five import tiers KEPT. Twelve-engine independence is KEPT at
zero pairs. invoked == MUST_INVOKE, owed 0. Engine-to-kernel equals
frozenset(). G44 census: 103 n_zero_call / 17 n_zero_call_anywhere /
0 DEAD. Current-state claims carry their original label; new material is
`specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        G44 dead-compute keep
BASE:            arch/exec 0ee58817 (L-02 duplicate
                 note; G46-01 merged and captured;
                 G45 CLOSED with test_g45_keep;
                 engine-to-kernel empty; Five import
                 tiers KEPT; G40 CLOSED; invoked ==
                 MUST_INVOKE, owed 0)
CLOSES:          dead_compute n_zero_call_anywhere
                 equals a named keep of the six
                 documented API surfaces, with G44
                 owning its own pin
                 (test_g44_dead_compute) and S5's
                 reason narrowed to "GAP G41 G42".
                 The census found none dead by the
                 old scanner: 103 n_zero_call / 17
                 n_zero_call_anywhere / 0 DEAD.
                 G44-00's getattr fix exposed
                 CompositionEngine.alphas as having
                 no reach at all -- its only
                 apparent one was the "alphas" JSON
                 key in cli/promote.py:466, which
                 reads the promotion ledger, not
                 this property. One method is
                 deleted. Six are kept:
                 CostArithmetic.declared_round_trip_cost_bps
                 (Inv-12 declaration-time
                 disclosure, not runtime B4);
                 AlphaBudgetRiskWrapper.checkpoint_risk_state
                 and restore_risk_state (persist
                 per-alpha HWM across restarts);
                 RegimeStateCache.for_engine
                 (named-engine lookup; tick path
                 uses latest());
                 RegimeStateCache.forget and
                 HorizonSignalEngine.forget (S7
                 delisting / clean restart).
DOES NOT CLOSE:  G41 and G42 (the budget and the
                 meter, BLOCKED — S-33 cannot close
                 an overrun the per-quote timer
                 cannot resolve; S-32 recorded that
                 instrument uninformative). G45
                 (already closed; pin is
                 test_g45_keep). G46 (orphan matcher,
                 closed at G46-01). S5 stays xfail
                 on G41/G42; its marker is narrowed
                 by this campaign, not dropped.
                 Carried from the prior closes:
                 G32 S-30f deferred; G36 seventeen
                 keepers; G39 S17 xfail; S-34f
                 groups g–o (15 engine bodies;
                 Inv-8 is a different campaign);
                 perfmeasure.py DIRECT_PROBES; G6
                 empty depends_on_sensors; S-04c;
                 serialization.py fail-open;
                 verify_step frozen bugs; 152
                 research cache days. harness →
                 kernel stays legal. S2 stays KEPT
                 at zero twelve-engine pairs; a
                 new twelve-engine pair is a STOP,
                 not this campaign. The four
                 EXEMPTION tests stay environmental
                 (S-13 ALSO: any live-feed test in
                 tests/ingestion/test_massive_functional.py).
STANDING
INVARIANTS:      Oracle frozen at exec-tools-v1. Never run
                 scripts/rebaseline_parity_hashes.py.
                 Hold all 64 HASH/COUNT constants, the
                 fingerprint
                 (de5d64b019075de0ca271b53834f342623f2b1a39f23ff73910e45b0bc90beb6),
                 and _BASELINE_CONFIG_HASH unless a step
                 names a re-pin.
                 Accepted baseline failures are the IB
                 after-hours test
                 (test_after_hours_reject_surfaces_as_rejected),
                 g12
                 (test_g12_cost_exceeds_disclosure_alert),
                 and any live-feed test in
                 tests/ingestion/test_massive_functional.py.
                 S-13 EXEMPTION ALSO is adopted. A
                 failure outside that set is a STOP.
                 Five import tiers is empty
                 _TIER_RESIDUALS and statuses KEPT;
                 Twelve engine module sets is KEPT at
                 zero pairs. Engine-to-kernel equals
                 frozenset().
                 Do not restore continue-on-error.
                 Do not invent suffixes for g–o.
                 Reset partition holds: _TAPES the five
                 ids; MUST_INVOKE 33; DECLARED_UNINVOKED
                 nine; invoked == MUST_INVOKE.
                 FAIL_QUIET_KEEP must never regain a
                 line key. ruff locked at 0.15.12 in
                 uv.lock.
                 Specific to this campaign: do not drop
                 S5's xfail. After G44-01 the reason is
                 "GAP G41 G42". G44's pin is
                 test_g44_dead_compute; G45's pin is
                 test_g45_keep. Do not delete any of
                 the six.
                 LEDGER APPENDS ARE END-OF-FILE WRITES,
                 NEVER A PREFIX-PRESERVING STRREPLACE.
                 A StrReplace whose old_string is the
                 ledger's tail and whose new_string is
                 that tail plus a block stays applicable
                 after it succeeds, so any retry,
                 compaction resume or "continue" appends
                 the block again. That is the cause of
                 89d3ac28, c62903ce and the four G46-01
                 copies. tools/exec is frozen and cannot
                 enforce this. Every ledger append is an
                 end-of-file write, and
                 tests/docs/test_exec_ledger_structure.py
                 runs BEFORE git add of the ledger, not
                 after.
NON-CUTS:        Deleting any of the six is not a cut.
                 A getattr rewrite to a direct call
                 is not a G44 rung: that uses the
                 method, it does not prove it dead.
                 Skipping every @property, or every
                 Protocol, as a blanket exemption is
                 not a close.
                 Counting JSON/YAML keys as calls is
                 not a getattr fix.
                 Folding scripts/ back into tests/
                 is not a classification.
                 Emptying n_zero_call_anywhere by
                 shrinking the walker is not a keep.
LADDER:          Shared-file steps are sequential, not
                 independently revertible. G44-01a
                 depends on G44-00: the property was
                 invisible as dead until getattr
                 stopped counting a JSON key as a
                 call. G44-01 depends on G44-01a:
                 the keep is named against a
                 remainder of 6 after the deletion,
                 not against the 7 the detector
                 left, and not against the scanner
                 that could not see the construct.
                   G44-00  detector: property minus-one;
                           Protocol stubs; getattr
                           literal vs JSON/YAML;
                           scripts/ vs tests/. Expected
                           6; actual 7 (finding:
                           CompositionEngine.alphas).
                   G44-01a delete CompositionEngine.alphas.
                           n_zero_call_anywhere 7 to 6;
                           the six equal the S-31c keeps.
                   G44-01  contract: site keep of the
                           six. n_zero_call_anywhere is
                           6 on arrival, equal to
                           _G44_KEEP. S5 reason
                           narrowed same commit.
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template). G44-00, G44-01a, and G44-01 are locked here.

```
STEP:            G44-00
CLOSES:          nothing by cutting. Teaches the
                 scanner. Expected
                 n_zero_call_anywhere after: 6.
                 Anything else is a finding. G44
                 pin does not exist yet. S5 xfail
                 stays (GAP G41 G42 G44 G45). Five
                 import tiers KEPT. G40 CLOSED.
                 Engine-to-kernel stays empty.
                 Zero methods deleted.
PROBLEM:         A close of the current 17 is
                 evadable, and a deletion campaign
                 would delete nothing: the census
                 found 0 DEAD. Four holes inflate
                 n_zero_call_anywhere.
                 Property minus-one:
                 count(".name")-1 treats the def as
                 an attribute read it is not; one
                 real read looks like zero.
                 Protocol stubs are counted as
                 compute; a method on a Protocol
                 class is an interface.
                 getattr is invisible as a call;
                 '"name" in all_text' does not
                 distinguish getattr's argument from
                 a JSON/YAML key.
                 scripts/ is folded into tests_text,
                 so entry points look TEST-ONLY.
                 G44-01 must not name a remainder
                 the old scanner cannot see.
WHY THIS OWNER:  The detector that has to land before
                 the remainder is named. Not G44-01:
                 a frozenset cannot see a construct
                 the walker misses. Not a deletion
                 rung: the census found none dead.
FILES:           tools/arch/hotpath.py
                 Do not edit
                 test_hot_path_allow_list.py (S5
                 xfail stays; G44 pin is G44-01),
                 cost_arithmetic.py, risk_wrapper.py,
                 regime_state_cache.py,
                 horizon_engine.py, registry.py,
                 synchronizer.py, backtest_router.py,
                 identifiers.py, test_fail_quiet.py,
                 ci.yml. Probe insertions, if any,
                 are not in the commit; they are
                 restored byte-identical before it.
REFACTOR PATH:   one commit. Mechanism: count real
                 attribute reads, not count minus the
                 def site. A method on a Protocol
                 class is an interface, not compute.
                 getattr(x, "name") counts as a call
                 when the string is a literal,
                 distinguished from JSON/YAML keys
                 by being getattr's argument.
                 scripts/ separated from tests/ so
                 entry points are not TEST-ONLY;
                 n_zero_call_anywhere is unreached
                 in src/ and tests/ and scripts/.
                 Fail-first cannot be a src cut: the
                 scanner currently cannot see the
                 construct. Probe by insertion, per
                 G45-00: for each hole, show the
                 unpatched scanner miscounting a
                 named site, then the patched one
                 counting it right. Membership of
                 (path, class, method), not a count
                 delta. A count check would pass if
                 the patch displaced another row.
                 The three sites already occupy the
                 holes.
                 (1) Property.
                 UniverseSnapshot.members
                 (src/feelies/alpha/registry.py).
                 Unpatched: in the zero-call set.
                 Patched: a real attribute read;
                 not in the six.
                 (2) Protocol.
                 _UniverseAuthority.members
                 (src/feelies/composition/synchronizer.py).
                 Unpatched: in the zero-call set.
                 Patched: not compute; absent from
                 the census.
                 (3) getattr.
                 BacktestOrderRouter.expire_pending_moc
                 (src/feelies/execution/backtest_router.py).
                 Unpatched: in
                 n_zero_call_anywhere (the call is
                 getattr(order_router,
                 "expire_pending_moc", None) in
                 orchestrator.shutdown). Patched:
                 getattr literal is a call; not in
                 the six.
                 Restore any insertion
                 byte-identical. Restore check,
                 separate from the probe:
                 n_zero_call_anywhere == 6.
                 Without (1) a one-read property
                 still looks dead. Without (2) a
                 Protocol stub can be "deleted".
                 Without (3) a getattr rewrite to
                 a direct call still looks like a
                 cut. Without the scripts/ split,
                 an entry point stays TEST-ONLY.
                 Expected n_zero_call_anywhere
                 after the detector lands, on this
                 tape, is 6. Anything else is a
                 finding, not a failure — it would
                 mean a hole was already being
                 used, or a keep was a scanner
                 artifact. Stop and record; do not
                 shrink a keep that does not exist
                 yet.
BLAST RADIUS:    local
VALIDATED BY:    after restore, dead_compute()
                 n_zero_call_anywhere == 6;
                 insertion (1) membership:
                 (registry.py, UniverseSnapshot,
                 members) zero-call before, not
                 after;
                 insertion (2) membership:
                 (synchronizer.py,
                 _UniverseAuthority, members)
                 zero-call before, absent after;
                 insertion (3) membership:
                 (backtest_router.py,
                 BacktestOrderRouter,
                 expire_pending_moc) in
                 n_zero_call_anywhere before, not
                 after;
                 both restores byte-identical if
                 used; not a count delta on any
                 probe;
                 test_hot_path_allow_list still
                 xfail (G41 G42 G44 G45), no XPASS;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin. A scanner-only change that
                 moves a hash means the file was not
                 scanner-only.
DELETES:         nothing in src. Zero methods. The
                 census found none dead. The holes
                 close.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from G44-01 until G44-01
                 lands (different file). G44-01 is not
                 independently revertible from this
                 rung: the keep is named against this
                 detector.

STEP:            G44-01a
CLOSES:          n_zero_call_anywhere 7 to 6. The six
                 remaining equal the S-31c keeps.
                 CompositionEngine.alphas is deleted.
                 S5 xfail stays (GAP G41 G42 G44 G45).
                 G44 pin does not exist yet. Five
                 import tiers KEPT. G40 CLOSED.
                 Engine-to-kernel stays empty.
PROBLEM:         G44-00 left n_zero_call_anywhere at
                 7, not 6. The seventh is
                 CompositionEngine.alphas
                 (src/feelies/composition/engine.py:193),
                 a @property that returns
                 tuple(self._alphas) -- an immutable
                 snapshot of registered PORTFOLIO
                 alphas. It is not a Protocol member:
                 core/composition_protocol.py
                 CompositionEngine is an empty body
                 ("Kernel never calls methods by
                 name"). No .alphas read and no
                 getattr(..., "alphas") anywhere in
                 src/, tests/, scripts/, tools/,
                 configs/, or docs/prompts. The only
                 apparent reach was the "alphas" JSON
                 key in cli/promote.py:466, which
                 reads the promotion ledger, not this
                 property. git log -S "def alphas"
                 on engine.py is one commit,
                 1be467b8 (Phase-4, 2026-04-24);
                 git log -S ".alphas" on src/feelies,
                 tests, scripts is empty -- no caller
                 was ever added. "Public snapshot of
                 the registry" without a consumer is
                 not a keep reason.
WHY THIS OWNER:  The deletion that has to land before
                 the keep is named. Not G44-00: the
                 detector does not delete. Not G44-01:
                 a frozenset cannot absorb a dead
                 member by omitting it, and FILES of
                 G44-01 is the pin test, not engine.py.
FILES:           src/feelies/composition/engine.py
                 only. Delete the alphas property.
                 Leave self._alphas, register(),
                 attach and _on_context untouched --
                 they are the live list.
                 Do not edit hotpath.py (detector
                 already landed),
                 test_hot_path_allow_list.py (S5
                 xfail stays; G44 pin is G44-01),
                 cost_arithmetic.py, risk_wrapper.py,
                 regime_state_cache.py,
                 horizon_engine.py,
                 composition_protocol.py,
                 cli/promote.py, identifiers.py,
                 test_fail_quiet.py, ci.yml.
                 Do not delete any of the six.
REFACTOR PATH:   one commit. Mechanism: delete the
                 property. The field and the
                 registration/dispatch path stay.
                 Probe, G45-00 membership (file,
                 class, method), not a count delta:
                 before, (src/feelies/composition/engine.py,
                 CompositionEngine, alphas) in
                 n_zero_call_anywhere; after, absent
                 because it no longer exists, and
                 n_zero_call_anywhere is exactly the
                 six S-31c keeps. Also confirm mypy
                 src/feelies: a deleted public member
                 that something typed against would
                 show there.
BLAST RADIUS:    local
VALIDATED BY:    dead_compute() n_zero_call_anywhere
                 == 6, equal to the six S-31c keeps;
                 (engine.py, CompositionEngine,
                 alphas) in n_zero_call_anywhere
                 before, absent after because the
                 property is gone, not because a
                 count moved;
                 mypy src/feelies Success;
                 test_hot_path_allow_list still
                 xfail (G41 G42 G44 G45), no XPASS;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. An
                 unread property cannot move a hash; if
                 one moves, something did read it. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin.
DELETES:         CompositionEngine.alphas. One
                 property. self._alphas stays.
NET DELTA:       src modules 0, public symbols -1,
                 branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from G44-00 until G44-01
                 lands (different files). G44-01 is
                 not independently revertible from
                 this rung: the keep is named against
                 the remainder of 6 this deletion
                 leaves.

STEP:            G44-01
CLOSES:          nothing by deleting. Installs the
                 keep. n_zero_call_anywhere stays 6,
                 equal to _G44_KEEP. S5 reason
                 narrowed to "GAP G41 G42" in the
                 same commit. G44 now has its own
                 pin; G45 already does via
                 test_g45_keep. Five import tiers
                 KEPT. G40 CLOSED. Engine-to-kernel
                 stays empty. Zero methods deleted.
PROBLEM:         S5 asserts n_anywhere == 0 under a
                 lumped xfail (G41 G42 G44 G45).
                 Emptying G44 cannot drop that
                 marker: G41/G42 are BLOCKED and
                 proven sites remain. Without a G44
                 pin, a new zero-call method joins
                 a stale reason string, the same
                 way UNIT_UNDETERMINED joined
                 RiskVerdict.constraints. G45
                 already split its pin out;
                 G44 has not.
WHY THIS OWNER:  The contract that names the remainder
                 after the detector can see it and
                 after G44-01a deleted the seventh.
                 Not G44-00: the detector does not
                 decide which of the six stays. Not
                 G44-01a: a src drop cannot move a
                 frozenset. Do not delete any of the
                 six.
FILES:           tests/conformance/test_hot_path_allow_list.py
                 Do not edit hotpath.py (detector
                 already landed), engine.py
                 (deletion already landed),
                 cost_arithmetic.py,
                 risk_wrapper.py,
                 regime_state_cache.py,
                 horizon_engine.py, identifiers.py.
                 Do not drop S5's xfail. Do not
                 delete any of the six. Do not edit
                 test_fail_quiet.py, ci.yml.
REFACTOR PATH:   one commit. Mechanism: a G44 equality
                 pin, DECLARED_UNINVOKED / FAIL_QUIET_KEEP
                 / _G45_KEEP shape, not a kind
                 allowlist. Key is (path, class,
                 method), not a line number:
                 _G44_KEEP = frozenset({
                   ("src/feelies/core/cost_arithmetic.py",
                    "CostArithmetic",
                    "declared_round_trip_cost_bps"),
                   ("src/feelies/risk/risk_wrapper.py",
                    "AlphaBudgetRiskWrapper",
                    "checkpoint_risk_state"),
                   ("src/feelies/risk/risk_wrapper.py",
                    "AlphaBudgetRiskWrapper",
                    "restore_risk_state"),
                   ("src/feelies/services/regime_state_cache.py",
                    "RegimeStateCache",
                    "for_engine"),
                   ("src/feelies/services/regime_state_cache.py",
                    "RegimeStateCache",
                    "forget"),
                   ("src/feelies/signals/horizon_engine.py",
                    "HorizonSignalEngine",
                    "forget"),
                 })
                 Reason on each entry, in order:
                 Inv-12 declaration-time disclosure,
                 distinct from runtime B4;
                 persist per-alpha HWM across
                 restarts; restore pair of
                 checkpoint; named-engine lookup
                 (tick path uses latest()); S7
                 delisting of cached regime state;
                 S7 symbol lifecycle on the signal
                 engine.
                 Live keep-hits = n_zero_call_anywhere
                 methods matching that triple.
                 Standing test_g44_dead_compute
                 asserts keep-hits == _G44_KEEP.
                 S5's xfail reason narrowed to
                 "GAP G41 G42" in this same commit.
                 A src drop cannot move this
                 frozenset.
                 Fail-first, required:
                 (1) Add a seventh triple to
                 _G44_KEEP that is not a live
                 zero-call-anywhere method. Run
                 only test_g44_dead_compute. It
                 MUST fail missing that member.
                 Remove the extra triple. Re-run
                 green: keep-hits == the six.
                 (2) Confirm S5 still xfails on
                 its first assert (proven
                 non-empty: assert not proven).
                 That is the honesty check on the
                 narrowed marker — not an XPASS
                 waiting to happen. Do not delete
                 a keep member to "prove" the pin.
BLAST RADIUS:    local
VALIDATED BY:    keep-hits == _G44_KEEP;
                 fail-first (1) missing, then green;
                 dead_compute() n_zero_call_anywhere
                 is 6 on arrival from G44-01a,
                 not by construction of this pin;
                 test_hot_path_allow_list still
                 xfail, reason "GAP G41 G42", first
                 assert still the proven-non-empty
                 failure, no XPASS;
                 test_g45_keep still green;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin. A test-only change that moves
                 a hash means the file was not
                 test-only.
DELETES:         nothing in src. Zero methods on this
                 rung. Six of them are now named.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from G44-01a: the keep is
                 named against the remainder that
                 rung left.
```
