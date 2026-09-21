# PHASE 12 — G45 proven-site keep

**Basis.** Engine-to-kernel pin closed on `arch/exec` (`1a56239e`).
G40 is CLOSED. Five import tiers KEPT. Twelve-engine independence is KEPT
at zero pairs. invoked == MUST_INVOKE, owed 0. Engine-to-kernel equals
frozenset(). G46 is recorded as an orphan matcher, not this campaign.
Current-state claims carry their original label; new material is
`specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        G45 proven-site keep
BASE:            arch/exec 1a56239e (G46 orphan matcher
                 recorded under Engine-to-kernel CLOSE;
                 engine-to-kernel pin empty; Five import
                 tiers KEPT; G40 CLOSED; invoked ==
                 MUST_INVOKE, owed 0)
CLOSES:          proven per-event prohibited sites
                 equal a named keep of one site,
                 make_correlation_id, with six cut.
                 This does NOT mean "no per-event
                 allocation on the tick path." The id
                 is built from a timestamp and a
                 sequence and cannot be interned, so
                 every replacement — f-string, Add,
                 tuple, packed int — still allocates
                 once per stamp. Inv-13 keeps the call
                 on the path. The close is six body
                 sites gone and one named remainder.
DOES NOT CLOSE:  G41 and G42 (the budget and the
                 meter, BLOCKED — S-33 cannot close an
                 overrun the per-quote timer cannot
                 resolve; S-32 recorded that instrument
                 uninformative). G44 (103 public
                 methods with zero in-src call sites,
                 tree-wide, needs a census). S5 stays
                 xfail on G41/G42/G44/G45; its marker
                 is NOT dropped by this campaign. G45
                 gets its own pin. G46 is the orphan
                 matcher recorded 2026-09-20; do not
                 open a campaign for it.
                 Carried from the five prior closes:
                 G32 S-30f deferred; G36 seventeen
                 keepers; G39 S17 xfail; S-34f groups
                 g–o (15 engine bodies; Inv-8 is a
                 different campaign); perfmeasure.py
                 DIRECT_PROBES; G6 empty
                 depends_on_sensors; S-04c;
                 serialization.py fail-open;
                 verify_step frozen bugs; 152 research
                 cache days. harness → kernel stays
                 legal. S2 stays KEPT at zero
                 twelve-engine pairs; a new twelve-
                 engine pair is a STOP, not this
                 campaign. The four EXEMPTION tests
                 stay environmental (S-13 ALSO: any
                 live-feed test in
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
                 S5's xfail. G45's pin is a separate
                 assertion. The executed set is
                 gitignored (tools/arch/evidence/*.json);
                 a rung that depends on it states the
                 command that produced it. S5 and the
                 G45 pin read the same file.
NON-CUTS:        A re-export without retarget is not a
                 cut.
                 A TYPE_CHECKING-only move is not a cut.
                 A sys.modules lookup (or optional
                 getattr fallback) is not a cut.
                 Widening a type to object or Any is
                 not a cut.
                 A pytest skip, an xfail, or a noqa on
                 a live import is not a close.
                 Rewriting an f-string as concatenation
                 is not a cut while the scanner cannot
                 see Add.
                 Rewriting a getattr as self.__dict__
                 is not a cut.
                 Putting string_formatting into
                 ALLOWED_NOT_PROHIBITED is not a site
                 allowlist — it exempts the whole class
                 including _stamp.
                 Making correlation_id a tuple is not a
                 G45 rung. It is a schema campaign that
                 moves _compute_schema_hash.
LADDER:          Shared-file steps are sequential, not
                 independently revertible. G45-01
                 depends on G45-00: the keep is named
                 against the detector that can see Add
                 and __dict__, not against the scanner
                 that could not. Body rungs G45-02–
                 G45-05 are sequential on the six live
                 sites; G45-05 is boundary (protocol).
                   G45-00  detector: visit_BinOp Add on
                           strings; __dict__ subscript
                           as dynamic_dispatch. Proven
                           expected unchanged at 7 on
                           this tape.
                   G45-01  contract: site keep of
                           make_correlation_id. Live
                           proven stays 7; the keep is
                           the named remainder, not yet
                           the campaign close.
                   G45-02  hoist-once: can_transition
                           empty frozenset, _stamp
                           intern-at-bind, empty
                           MappingProxyType metadata.
                           Proven 7 → 4.
                   G45-03  _require_halt_authority
                           typed attribute plus the
                           existing KernelFault.
                           Proven 4 → 3.
                   G45-04  refresh_high_water_mark
                           bind-time callable cache.
                           Proven 3 → 2.
                   G45-05  all_positions
                           MappingProxyType over live
                           _positions; protocol widens
                           to Mapping. Proven 2 → 1,
                           equal to the keep.
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template). G45-00 through G45-05 are locked here.

```
STEP:            G45-00
CLOSES:          nothing by cutting. Teaches the
                 scanner. Proven expected unchanged at
                 7 on this tape. G45 pin does not exist
                 yet. S5 xfail stays. Five import tiers
                 KEPT. G40 CLOSED. Engine-to-kernel
                 stays empty.
PROBLEM:         A close of the current seven is
                 evadable. visit_BinOp catches only
                 `%` on a string constant, not Add, so
                 `symbol + ":" + str(ts)` is invisible.
                 dynamic_dispatch catches getattr /
                 hasattr / setattr / vars, not
                 `self.__dict__["attr"]`. S-32 recorded
                 both holes. G45-01 must not name a
                 remainder the old scanner cannot see,
                 and a later body rung must not go
                 green by rewriting an f-string as
                 concatenation or a getattr as
                 __dict__.
WHY THIS OWNER:  The detector that has to land before
                 the remainder is named. Not G45-01: a
                 frozenset cannot see a construct the
                 walker misses. Not a body cut: no
                 proven site is removed.
FILES:           tools/arch/hotpath.py
                 Do not edit identifiers.py,
                 sensors/registry.py, events.py,
                 state_machine.py, memory_position_store.py,
                 data_health.py, risk_wrapper.py,
                 test_hot_path_allow_list.py (S5 xfail
                 stays; G45 pin is G45-01),
                 test_fail_quiet.py, ci.yml. The two
                 probe insertions are not in the
                 commit; they are restored
                 byte-identical before it.
REFACTOR PATH:   one commit. Mechanism: teach
                 visit_BinOp to hit string_formatting
                 when Add participates and either
                 operand is a string constant or a
                 JoinedStr (including a chained Add).
                 Teach visit_Subscript (or the Call
                 walk) to hit dynamic_dispatch on
                 `__dict__[…]`.
                 Fail-first cannot be a src cut: the
                 scanner currently cannot see the
                 construct. Probe by insertion, both
                 required, then restore. The inserted
                 statement goes before the existing
                 return in that function so it is
                 unconditional and the scanner walks
                 it. After the return it is dead; inside
                 an if it is not proven.
                 scan() reports proven sites as a list
                 of dicts under
                 prohibitions[kind]["proven_sites"],
                 each with site ("file:line"), func,
                 unconditional, band. A function can
                 appear under two kinds. The probe is
                 membership of (file, func, kind), not
                 a count delta. A count check would
                 pass if the insertion displaced
                 another row.
                 (1) Concatenation. In can_transition
                 (already proven for
                 per_event_set_construction; zero
                 string_formatting hits), insert
                 `_ = "x" + "y"` as a statement before
                 the existing return. Run scan()
                 against the executed set below. Probe
                 (must fail to name it before the
                 detector, must name it after):
                 sites = report["prohibitions"]
                          ["string_formatting"]
                          ["proven_sites"]
                 any(s["func"] == "can_transition"
                     and s["site"].startswith(
                       "src/feelies/core/state_machine.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 Restore the file byte-identical.
                 Restore check, separate from the
                 probe: re-scan, proven still 7.
                 (2) __dict__. In all_positions
                 (already proven for
                 per_event_dict_construction; zero
                 dynamic_dispatch hits), insert a
                 `self.__dict__["…"]` read as a
                 statement before the existing return.
                 Probe:
                 sites = report["prohibitions"]
                          ["dynamic_dispatch"]
                          ["proven_sites"]
                 any(s["func"] == "all_positions"
                     and s["site"].startswith(
                       "src/feelies/portfolio/memory_position_store.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 Restore byte-identical. Restore
                 check, separate from the probe:
                 re-scan, proven still 7.
                 Without (1) an Add rewrite of _stamp
                 still looks like a cut. Without (2)
                 a getattr rewrite to __dict__ still
                 looks like a cut.
                 Expected proven count after the
                 detector lands, on this tape, is
                 unchanged at 7. A change in the count
                 is a finding, not a failure — it would
                 mean the hole was already being used.
                 Stop and record; do not shrink a keep
                 that does not exist yet.
                 Executed set: gitignored
                 (tools/arch/evidence/*.json). This
                 rung's scan uses
                 `uv run python tools/arch/perfmeasure.py
                 --mode profile` then
                 `uv run python tools/arch/hotpath.py`
                 (APP / 2026-03-26 /
                 configs/bt_app.yaml). S5's scan()
                 reads the same
                 hotpath_executed.json. State the
                 commands and the n_quotes /
                 parity_hash of that file in the
                 ledger. Do not commit the json.
BLAST RADIUS:    local
VALIDATED BY:    after restore, scan()
                 proven_per_event_sites still 7,
                 named kinds unchanged on this tape
                 unless the finding above fires;
                 insertion (1) membership: some
                 string_formatting proven_sites dict
                 has func == "can_transition",
                 site startswith
                 src/feelies/core/state_machine.py:,
                 unconditional, band == per_event;
                 insertion (2) membership: some
                 dynamic_dispatch proven_sites dict
                 has func == "all_positions",
                 site startswith
                 src/feelies/portfolio/memory_position_store.py:,
                 unconditional, band == per_event;
                 both restores byte-identical;
                 not a count delta on either probe;
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
DELETES:         nothing in src. The seven proven sites
                 stay. The holes close.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from G45-01 until G45-01
                 lands (different file). G45-01 is not
                 independently revertible from this
                 rung: the keep is named against this
                 detector.

STEP:            G45-01
CLOSES:          nothing by cutting. Installs the site
                 keep. Live proven stays 7. The keep is
                 the named remainder, not the campaign
                 close. S5 xfail stays. Five import
                 tiers KEPT. G40 CLOSED. Engine-to-
                 kernel stays empty.
PROBLEM:         S5 asserts `not proven` under a lumped
                 xfail (G41 G42 G44 G45). Emptying G45
                 cannot drop that marker: G44 still has
                 103 zero-call methods and G41/G42 are
                 BLOCKED. Without a G45 pin, a new
                 proven site joins a stale reason
                 string, the same way UNIT_UNDETERMINED
                 joined RiskVerdict.constraints.
                 ALLOWED_NOT_PROHIBITED cannot be that
                 pin: it is a kind set
                 {transcendental, decimal_arithmetic}
                 with no per-entry reason, and adding
                 string_formatting would exempt _stamp.
WHY THIS OWNER:  The contract that names the remainder
                 before any body cut. Not G45-00: the
                 detector does not decide which of the
                 seven stays. Not a body rung: a src
                 drop cannot move a frozenset.
FILES:           tests/conformance/test_hot_path_allow_list.py
                 Do not edit hotpath.py (detector
                 already landed), identifiers.py, or
                 any of the six body files. Do not drop
                 S5's xfail. Do not add
                 string_formatting to
                 ALLOWED_NOT_PROHIBITED. Do not edit
                 test_fail_quiet.py, ci.yml.
REFACTOR PATH:   one commit. Mechanism: a G45 equality
                 pin, DECLARED_UNINVOKED / FAIL_QUIET_KEEP
                 shape, not a kind allowlist. Key is
                 (path, func, kind), not a line number
                 (0.1 retired line keys):
                 _G45_KEEP = frozenset({
                   ("src/feelies/core/identifiers.py",
                    "make_correlation_id",
                    "string_formatting"),
                 })
                 Live keep-hits = proven keys that
                 match that triple. Assert
                 keep-hits == _G45_KEEP.
                 Reason on the entry: Inv-13 unique
                 per-event stamp; built from a
                 timestamp and a sequence; cannot be
                 interned. Every replacement still
                 allocates.
                 The six other proven sites are not in
                 the keep. They remain live until the
                 body rungs. They must not be silently
                 absorbed into _G45_KEEP.
                 Equality: a second site added to the
                 keep that is not live fails missing.
                 Shrinking the keep while
                 make_correlation_id is still proven
                 fails unexpected. A src drop cannot
                 move this frozenset.
                 Fail-first, required:
                 (1) Add a second triple to _G45_KEEP
                 that is not a live proven site. Run
                 only the new assertion. It MUST fail
                 missing that member. Remove the extra
                 triple. Re-run green: keep-hits ==
                 {(identifiers.py, make_correlation_id,
                 string_formatting)}.
                 (2) Do not cut identifiers.py to
                 "prove" the pin. That would be a body
                 edit on a shared remainder and would
                 pass by construction if the keep were
                 then emptied.
                 Executed set: the same
                 hotpath_executed.json G45-00 stated.
                 If it is absent, regenerate with the
                 G45-00 commands before asserting.
                 S5 still reads that file and still
                 xfails.
BLAST RADIUS:    local
VALIDATED BY:    keep-hits == _G45_KEEP;
                 fail-first (1) missing, then green;
                 scan() proven still 7 on this tape;
                 test_hot_path_allow_list still
                 xfail (G41 G42 G44 G45), no XPASS;
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
DELETES:         nothing in src. The seven proven sites
                 stay. One of them is now named.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from G45-00: the keep is
                 named against that detector. Body
                 rungs are not independently
                 revertible from this pin once they
                 shrink live proven against it.

STEP:            G45-02
CLOSES:          three proven sites by one hoist-once
                 decision. Live proven 7 → 4. Keep
                 unmoved. S5 xfail stays. Five import
                 tiers KEPT. Engine-to-kernel empty.
PROBLEM:         Three per-event allocations are the
                 same internable empty: can_transition
                 builds frozenset() on every miss;
                 StateTransition.__post_init__ does
                 MappingProxyType(dict(self.metadata))
                 on every publish; _stamp formats
                 f"sensor:{spec.sensor_id}" on every
                 reading. 661,993 of 661,994 metadata
                 constructions are empty; the one
                 exception is StateMachine.reset's
                 {"type": "reset"}. Concatenation of
                 _stamp is not a cut: the scanner now
                 sees Add.
WHY THIS OWNER:  One intern decision, three sites.
                 Not three rungs. Not G45-05: that
                 snapshot is live book state, not an
                 internable empty.
FILES:           src/feelies/core/state_machine.py
                 src/feelies/sensors/registry.py
                 src/feelies/core/events.py
                 Do not edit identifiers.py,
                 data_health.py, risk_wrapper.py,
                 memory_position_store.py,
                 test_hot_path_allow_list.py. Do not
                 add string_formatting to
                 ALLOWED_NOT_PROHIBITED. Do not drop
                 S5's xfail.
REFACTOR PATH:   one commit. Hoist
                 _EMPTY_FROZENSET = frozenset() and
                 use it as the .get default in
                 can_transition. Intern
                 "sensor:{id}" onto _SensorBinding at
                 register() bind time; _stamp reads
                 that field. That is intern-at-bind,
                 NOT "sensor:" + id (Add is now
                 proven). Intern
                 _EMPTY_METADATA = MappingProxyType({})
                 for StateTransition; __post_init__
                 uses it when metadata is empty and
                 only dict()-copies the reset row
                 (guarded, not proven).
                 Fail-first, membership shape from
                 G45-00, three probes, all required.
                 Before the cut each is True; after,
                 each is False. Not a count delta.
                 (1) can_transition:
                 sites = report["prohibitions"]
                          ["per_event_set_construction"]
                          ["proven_sites"]
                 any(s["func"] == "can_transition"
                     and s["site"].startswith(
                       "src/feelies/core/state_machine.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 (2) _stamp:
                 sites = report["prohibitions"]
                          ["string_formatting"]
                          ["proven_sites"]
                 any(s["func"] == "_stamp"
                     and s["site"].startswith(
                       "src/feelies/sensors/registry.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 (3) __post_init__:
                 sites = report["prohibitions"]
                          ["per_event_dict_construction"]
                          ["proven_sites"]
                 any(s["func"] == "__post_init__"
                     and s["site"].startswith(
                       "src/feelies/core/events.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 After all three False: proven 4.
                 keep-hits == _G45_KEEP. Do not cut
                 identifiers.py.
BLAST RADIUS:    local
VALIDATED BY:    three memberships False; proven 4;
                 keep-hits == _G45_KEEP; S5 still
                 xfail (G41 G42 G44 G45), no XPASS;
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
DELETES:         three proven sites. Keep stays.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Not independently
                 revertible from G45-01. Body rungs
                 after this re-measure against 4.

STEP:            G45-03
CLOSES:          _require_halt_authority proven
                 dynamic_dispatch. Live proven 4 → 3.
                 Keep unmoved. S5 xfail stays.
PROBLEM:         getattr(self, "_halt_tradeability", None)
                 on the tick path. The store is already
                 bound on Orchestrator (and the
                 normalizer). A rewrite to
                 self.__dict__["_halt_tradeability"]
                 is not a cut: the scanner now sees
                 Subscript on __dict__.
WHY THIS OWNER:  The getattr that is live proven.
                 Not G45-04: that getattr is a
                 different object (_inner hook).
FILES:           src/feelies/core/data_health.py
                 Do not edit orchestrator.py for a
                 typed read of an attribute it already
                 assigns. Do not edit
                 test_hot_path_allow_list.py. Do not
                 drop S5's xfail.
REFACTOR PATH:   one commit. Typed attribute read
                 plus the existing KernelFault:
                 try: authority = self._halt_tradeability
                 except AttributeError: raise
                 KernelFault(SESSION_HALT) as today.
                 Keep the isinstance(_HaltTradeability)
                 check. Never self.__dict__.
                 Fail-first, membership shape from
                 G45-00. Before True; after False:
                 sites = report["prohibitions"]
                          ["dynamic_dispatch"]
                          ["proven_sites"]
                 any(s["func"] ==
                       "_require_halt_authority"
                     and s["site"].startswith(
                       "src/feelies/core/data_health.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 After False: proven 3.
                 keep-hits == _G45_KEEP.
BLAST RADIUS:    local
VALIDATED BY:    membership False; proven 3;
                 keep-hits == _G45_KEEP; S5 still
                 xfail, no XPASS;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin.
DELETES:         one proven getattr. KernelFault stays.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Depends on
                 G45-02's proven 4.

STEP:            G45-04
CLOSES:          refresh_high_water_mark proven
                 dynamic_dispatch. Live proven 3 → 2.
                 Keep unmoved. S5 xfail stays.
PROBLEM:         getattr(self._inner,
                 "refresh_high_water_mark", None) then
                 callable() on every mark. Capability
                 is known at wrap time. A rewrite to
                 self._inner.__dict__[…] is not a cut.
WHY THIS OWNER:  The remaining proven getattr. Do not
                 touch reset or record_fill getattr
                 in the same file (not proven).
FILES:           src/feelies/risk/risk_wrapper.py
                 Do not edit basic_risk.py,
                 test_hot_path_allow_list.py. Do not
                 drop S5's xfail.
REFACTOR PATH:   one commit. Bind-time callable cache
                 in AlphaBudgetRiskWrapper.__init__:
                 resolve the hook once, store
                 Optional[Callable]. The per-event
                 method calls the cache or returns.
                 Fail-first, membership shape from
                 G45-00. Before True; after False:
                 sites = report["prohibitions"]
                          ["dynamic_dispatch"]
                          ["proven_sites"]
                 any(s["func"] ==
                       "refresh_high_water_mark"
                     and s["site"].startswith(
                       "src/feelies/risk/risk_wrapper.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 After False: proven 2
                 (keep + all_positions).
                 keep-hits == _G45_KEEP.
BLAST RADIUS:    local
VALIDATED BY:    membership False; proven 2;
                 keep-hits == _G45_KEEP; S5 still
                 xfail, no XPASS;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin.
DELETES:         one proven getattr. Optional skip stays.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Depends on
                 G45-03's proven 3.

STEP:            G45-05
CLOSES:          all_positions proven dict copy.
                 Live proven 2 → 1, equal to the keep.
                 keep-hits == _G45_KEEP with live
                 proven equal to the keep. That is
                 the campaign close of the six, not
                 "no per-event allocation": the keep
                 still allocates. S5 xfail stays
                 (G44 103 methods; G41/G42 BLOCKED).
PROBLEM:         return dict(self._positions) on every
                 call. A reused snapshot buffer is not
                 a cut: _emergency_flatten_all binds
                 the result, lets fills mutate the
                 book, then calls all_positions()
                 again. That is safe today only
                 because the first name is dead after
                 the loop, which nothing enforces. A
                 held buffer would be retargeted. The
                 protocol says Snapshot; a buffer is
                 not one.
WHY THIS OWNER:  The last live site besides the keep.
                 The honest cut is a live read-only
                 view, which is a protocol change, so
                 this rung owns core/position.py. Not
                 a buffer: flatten already holds
                 across a second call.
FILES:           src/feelies/portfolio/memory_position_store.py
                 src/feelies/core/position.py
                 Do not edit identifiers.py,
                 test_hot_path_allow_list.py. Do not
                 drop S5's xfail. Do not add the six
                 to _G45_KEEP. Do not edit
                 .cursor/skills/system-architect/SKILL.md
                 (same dict annotation; follow-on).
REFACTOR PATH:   one commit. Return
                 MappingProxyType(self._positions).
                 No copy. No buffer. PositionStore
                 all_positions return type
                 dict[str, Position] →
                 Mapping[str, Position]. Docstring
                 changes from "Snapshot of all current
                 positions." to a live read-only view:
                 a proxy is not a snapshot either.
                 Must widen: the protocol and
                 MemoryPositionStore (it returns the
                 proxy). dict is a Mapping, so these
                 still return dict copies and do not
                 have to widen unless mypy rejects
                 them: _AggregateView.all_positions,
                 orchestrator _PostExitPositionView,
                 risk PostExitPositionView.
                 PositionBookView is already Mapping.
                 A held proxy now sees later key
                 inserts that a dict copy did not. No
                 test pins that today.
                 Fail-first, membership shape from
                 G45-00. Before True; after False:
                 sites = report["prohibitions"]
                          ["per_event_dict_construction"]
                          ["proven_sites"]
                 any(s["func"] == "all_positions"
                     and s["site"].startswith(
                       "src/feelies/portfolio/memory_position_store.py:")
                     and s["unconditional"]
                     and s["band"] == "per_event"
                     for s in sites)
                 After False: proven 1, equal to
                 _G45_KEEP. Close assertion:
                 keep-hits == _G45_KEEP and live
                 proven keys == _G45_KEEP.
BLAST RADIUS:    boundary
VALIDATED BY:    membership False; proven 1;
                 keep-hits == _G45_KEEP; live proven
                 == keep; S5 still xfail, no XPASS;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin. A protocol annotation change
                 that moves a hash means the file was
                 not annotation-only.
DELETES:         one proven dict() copy. Protocol
                 widens to Mapping. Keep stays.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Last body rung;
                 not independently revertible from
                 G45-01 once live proven equals the
                 keep. Boundary: present the diff.
```

