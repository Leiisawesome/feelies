# PHASE 11 — Engine-to-kernel pin

**Basis.** CI restoration closed on `arch/exec` (`b2d91c38`).
G40 is CLOSED. Five import tiers KEPT. Twelve-engine independence is KEPT
at zero pairs. invoked == MUST_INVOKE, owed 0. Engine-to-kernel equals
the 9-pair pin. The walker still counts harness as an engine; T-07c
already recorded that a blanket forbid cannot go green. Current-state
claims carry their original label; new material is `specified`.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

---

```
CAMPAIGN:        Engine-to-kernel pin
BASE:            arch/exec b2d91c38 (CI restoration closed
                 and verified; duplicated CLOSE removed;
                 Five import tiers KEPT; G40 CLOSED;
                 invoked == MUST_INVOKE, owed 0;
                 engine-to-kernel equals the 9-pair pin)
CLOSES:          _engine_kernel_import_pairs() ==
                 frozenset(), with the walker scoped to
                 what T-07c actually meant: the third-tier
                 engine packages, not the runner and not
                 the composition root. After A-00 the pin
                 is 4. After A-01 it is 1. After A-02 it
                 is empty.
DOES NOT CLOSE:  G10, G28, G32, G36, G39, G41, G42, G44,
                 G45, G46; S-34f groups g–o (15 engine
                 bodies; Inv-8 is a different campaign);
                 perfmeasure.py DIRECT_PROBES; G6 empty
                 depends_on_sensors; S-04c;
                 serialization.py fail-open; verify_step
                 frozen bugs; 152 research cache days.
                 harness → kernel stays legal. Five
                 import tiers already permits it; A-00
                 stops counting it, it does not forbid
                 it. S2 stays KEPT at zero twelve-engine
                 pairs; a new twelve-engine pair is a
                 STOP, not this campaign. The four
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
                 zero pairs. Engine-to-kernel shrinks
                 only in lockstep with the walker or
                 cut that drops the pair, in the same
                 commit: 9 after BASE, 4 after A-00,
                 1 after A-01, 0 after A-02.
                 Do not restore continue-on-error.
                 Do not invent suffixes for g–o.
                 Reset partition holds: _TAPES the five
                 ids; MUST_INVOKE 33; DECLARED_UNINVOKED
                 nine; invoked == MUST_INVOKE.
                 FAIL_QUIET_KEEP must never regain a
                 line key. ruff locked at 0.15.12 in
                 uv.lock.
NON-CUTS:        A re-export without retarget is not a
                 cut. That is why the three KernelFault
                 raisers survived T-06z.
                 A TYPE_CHECKING-only move is not a cut.
                 The walker does not skip TYPE_CHECKING.
                 A sys.modules lookup (or optional
                 getattr fallback) is not a cut.
                 Widening a type to object or Any is
                 not a cut.
                 Inlining the four self-attributed
                 reason strings in forensics is not a
                 cut: it drops the pair and forks the
                 set.
                 Excluding harness from the walker is
                 not a cut of harness → kernel. Five
                 import tiers still permits it.
                 A pytest skip, an xfail, or a noqa on
                 a live import is not a close.
LADDER:          Shared-file steps are sequential, not
                 independently revertible.
                 test_import_contracts.py is shared by
                 all three. A-01 depends on A-00 (the
                 4-pair pin). A-02 depends on A-01 (the
                 1-pair pin).
                   A-00  contract: exclude harness and
                         bootstrap; pin 9 → 4
                   A-01  retarget three KernelFault
                         raisers; pin 4 → 1
                   A-02  move
                         _SELF_ATTRIBUTED_FORCED_EXIT_REASONS
                         to core; pin 1 → 0
```

---

## G. Migration plan

Step blocks land in the fence below. `verify_step` parses fenced `STEP:`
blocks (the P7 template).

```
STEP:            A-00
CLOSES:          nothing by moving code. Pin 9 → 4.
                 Walker scoped to what T-07c meant.
                 Five import tiers stays KEPT. G40 stays
                 CLOSED. An unchanged five-tier count is
                 the declared outcome. The engine-to-
                 kernel pin moves as declared.
PROBLEM:         The pin walks every subdirectory of
                 src/feelies except kernel, bus, core,
                 cli. There is no _ENGINE_PACKAGES.
                 T-07c's block said: "Walk src/feelies
                 engine packages only (ingestion,
                 storage, sensors, features, services,
                 signals, alpha, promotion, composition,
                 portfolio, risk, execution, broker,
                 monitoring, harness, research,
                 forensics). Exclude kernel, bus, core,
                 cli, bootstrap." The code never put
                 bootstrap in _WALK_EXCLUDE. Bootstrap
                 is skipped because the loop is
                 iterdir() if p.is_dir() — an artifact
                 of file layout, not a stated rule.
                 T-07c WHY THIS OWNER already recorded
                 that a contract forbidding engines →
                 kernel cannot go green: "harness must
                 import Orchestrator; MacroState lives
                 in kernel." FILES forbade editing
                 harness/ and bootstrap.py. The five
                 harness pairs are runner wiring
                 counted as engine residuals. Campaign
                 A cannot empty the pin while they
                 remain in the walk. A src drop cannot
                 move a frozenset; shrinking the pin
                 without a walker fail-first is
                 decorative, the same way T-07c's
                 fourteen-pair set would have passed by
                 construction without the
                 fill_attribution probe.
WHY THIS OWNER:  The contract decision that has to land
                 before any cut. Not A-01: retargeting
                 KernelFault does not make harness not
                 an engine. Not a five-tier rewrite:
                 harness → kernel is already legal.
FILES:           tests/conformance/test_import_contracts.py
                 Do not edit core/position.py,
                 bootstrap.py, harness/, cli/,
                 orchestrator.py, fill_attribution.py
                 (portfolio or core), massive_ws.py,
                 horizon_scheduler.py, alpha/registry.py,
                 gate_close_attribution.py,
                 forced_exit_reasons.py,
                 test_fail_quiet.py, ci.yml. No keep-row
                 file is touched. The third probe edits
                 portfolio/fill_attribution.py only for
                 the mutation and restores it; that file
                 is not in the commit.
REFACTOR PATH:   one commit. Mechanism: walker exclude
                 plus equality pin shrink, same lockstep
                 as _TIER_RESIDUALS. Not a subset. A
                 fifth remaining pair fails immediately.
                 Add "harness" and "bootstrap" to
                 _WALK_EXCLUDE. Bootstrap changes no
                 count today (it is not a directory) and
                 is there so packaging the composition
                 root is not a tripwire. Do not add
                 research; it is in T-07c's engine list
                 and currently has zero kernel imports.
                 Three-part fail-first, all required:
                 (1) Add "harness" to _WALK_EXCLUDE
                 only. Do not touch
                 _KERNEL_IMPORT_RESIDUALS. Run only
                 test_engine_kernel_imports_equal_pin.
                 It MUST fail with missing the five
                 harness pairs (walker finds 4, pin
                 still has 9). This is the matcher
                 edit. A frozenset shrink without it
                 would pass by construction.
                 (2) Drop the five harness pairs from
                 _KERNEL_IMPORT_RESIDUALS in the same
                 working tree. Re-run green: 4 == 4.
                 Lockstep: the walker change and the
                 pin shrink land in one commit, never
                 as two rungs.
                 (3) T-07c probe. Add a throwaway
                 `from feelies.kernel.macro import MacroState`
                 to
                 src/feelies/portfolio/fill_attribution.py
                 (not in the pin; not a keep-row file;
                 the package whose reverse-edge
                 detector T-07b deleted). Run only
                 test_engine_kernel_imports_equal_pin.
                 It MUST fail naming
                 ('feelies.portfolio.fill_attribution',
                  'feelies.kernel.macro'). Remove the
                 import. Confirm fill_attribution.py is
                 byte-identical to HEAD. Re-run green.
                 Without (3) an exclude that also
                 skipped portfolio would still look
                 green at 4, and the original detector
                 would be dead.
                 Why all three: (1) proves the walker,
                 not the frozenset, is what dropped the
                 five; (2) is the lockstep shrink; (3)
                 proves T-07c's thing still bites.
                 What this step does not do: it does
                 not close any pair by moving code. It
                 does not make harness → kernel
                 illegal. Five import tiers already
                 permits it.
BLAST RADIUS:    boundary
VALIDATED BY:    test_engine_kernel_imports_equal_pin
                 equals the 4-pair pin (the three
                 KernelFault leftover paths plus
                 forensics → forced_exit_reasons);
                 fail-first (1) missing five, then (2)
                 green, then (3) unexpected
                 fill_attribution → kernel.macro and
                 restore byte-identical;
                 test_five_import_tiers KEPT and pairs
                 == frozenset();
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
                 No XPASS. A new twelve-engine pair is
                 a STOP. lint-imports: both contracts
                 KEPT.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT is a STOP, do not
                 re-pin. A test-only change that moves
                 a hash means the file was not
                 test-only.
DELETES:         nothing in src. The five harness pairs
                 leave the pin because they are no
                 longer walked, not because the imports
                 are gone. Pin stays 4, not 0.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from A-01 until A-01 lands;
                 test_import_contracts.py is shared.
                 Not independently revertible from
                 T-07c (already landed; same file).

STEP:            A-01
CLOSES:          nothing on five-tier. Pin 4 → 1.
                 Drops the three KernelFault leftover
                 paths. Leaves forensics →
                 kernel.forced_exit_reasons. Five import
                 tiers stays KEPT. G40 stays CLOSED.
PROBLEM:         ingestion/massive_ws.py:31,
                 sensors/horizon_scheduler.py:33, and
                 alpha/registry.py:49 still import
                 KernelFault from
                 kernel.exception_taxonomy. They raise
                 INGRESS_ADMIT, HORIZON_GRID, and
                 UNIVERSE. T-06z moved the body to
                 core.exception_taxonomy and left
                 `from feelies.core.exception_taxonomy
                 import KernelFault as KernelFault` on
                 the kernel module so the raisers would
                 need no retarget. A re-export without
                 retarget is the catalogued non-cut.
                 That is why these three survived
                 T-06z. core/data_health.py already
                 imports from core. kernel/orchestrator.py
                 may keep the kernel alias (same
                 package; not in the walk).
WHY THIS OWNER:  The body already lives in core. This
                 is the retarget T-06z deferred. Not
                 A-00: the walker change does not move
                 an import. Not A-02: these are not
                 forensics.
FILES:           src/feelies/ingestion/massive_ws.py
                 src/feelies/sensors/horizon_scheduler.py
                 src/feelies/alpha/registry.py
                 tests/conformance/test_import_contracts.py
                 Do not edit kernel/exception_taxonomy.py
                 (the alias stays for orchestrator),
                 kernel/orchestrator.py, bootstrap.py,
                 harness/, cli/,
                 gate_close_attribution.py,
                 forced_exit_reasons.py,
                 test_fail_quiet.py, ci.yml.
                 massive_ws.py is a keep-row file.
                 FAIL_QUIET_KEEP is keyed
                 (path, enclosing_symbol, exc_type,
                 reason) with no line field, after 0.1.
                 Current massive_ws rows:
                 _drain_stale_sentinels / queue.Empty,
                 _run_loop / asyncio.CancelledError,
                 _subscribe / asyncio.TimeoutError.
                 The KernelFault raise at
                 massive_ws.py:193 is a raise, not a
                 keeper. Swapping the import at line 31
                 does not change those symbols or
                 exception types. 0.1's re-key means
                 FAIL_QUIET_KEEP no longer cares about
                 this line shift; do not name
                 test_fail_quiet.py; do not squeeze the
                 except bodies. MEASURE KEEP-ROWS, DO
                 NOT ASSUME THEM: if a later hunk in
                 this file were to rename an enclosing
                 def, that would be a different step.
REFACTOR PATH:   one commit. Mechanism: retarget three
                 ImportFrom lines to
                 feelies.core.exception_taxonomy.
                 Kind members unchanged. No object/Any,
                 no getattr, no sys.modules, no
                 TYPE_CHECKING-only move, no deletion
                 of the kernel alias.
                 (1) Retarget the three raisers. Shrink
                 _KERNEL_IMPORT_RESIDUALS by those
                 three pairs in the same commit.
                 Remaining pin is the one forensics
                 pair.
                 (2) Probe: restore one raiser to
                 kernel.exception_taxonomy (drop one
                 retarget). Run only
                 test_engine_kernel_imports_equal_pin.
                 It MUST fail naming that module's
                 pair, e.g.
                 ('feelies.ingestion.massive_ws',
                  'feelies.kernel.exception_taxonomy').
                 Restore the retarget. Re-run green.
                 A pin shrink without a src retarget
                 would pass by construction.
                 (3) Closure walk: _engine_kernel_import_pairs()
                 equals the 1-pair pin. An extra
                 KernelFault path is a STOP.
BLAST RADIUS:    boundary
VALIDATED BY:    test_engine_kernel_imports_equal_pin
                 equals the 1-pair pin; probe failed-
                 before on one dropped retarget then
                 passed-after restore;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/conformance/test_ingress_admit.py,
                 test_horizon_grid.py,
                 test_universe_authority.py (via the
                 alias or core; no XPASS);
                 tests/acceptance/test_backtest_app_baseline.py.
                 No XPASS. A new twelve-engine pair is
                 a STOP.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT means KernelFault
                 is not the same type (class identity
                 or Kind member) — STOP, do not re-pin.
DELETES:         three engine →
                 kernel.exception_taxonomy pairs from
                 the pin. Does not delete the kernel
                 alias. Does not delete the forensics
                 pair.
NET DELTA:       src modules 0, public symbols 0,
                 branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from A-02 until A-02 lands;
                 test_import_contracts.py is shared.
                 Not independently revertible from A-00
                 (already landed; same test file).
                 massive_ws.py is not independently
                 revertible from later rungs that edit
                 it; this campaign has none.

STEP:            A-02
CLOSES:          the engine-to-kernel pin.
                 _engine_kernel_import_pairs() ==
                 frozenset(). Pin 1 → 0. Five import
                 tiers stays KEPT. G40 stays CLOSED.
PROBLEM:         forensics/gate_close_attribution.py:46
                 imports _SELF_ATTRIBUTED_FORCED_EXIT_REASONS
                 from kernel.forced_exit_reasons.
                 Forensics is in the twelve-engine
                 independence list. This is a real
                 engine → kernel edge, not a
                 reclassification. The set is four
                 strings: SAFETY_FAIL_CLOSED,
                 DECOUPLING_REVOKED,
                 MAX_HOLD_AFTER_SAFE_OFF,
                 SESSION_FLATTEN. S-35a put the union
                 in kernel so forensics would not
                 import risk. kernel/orchestrator.py
                 imports the same name (and
                 _RISK_FORCED_EXIT_REASONS,
                 _SLICE_SCOPED_FORCED_EXIT_REASONS)
                 from the kernel sibling. Inlining the
                 four strings in forensics would drop
                 the pair and fork the set — a
                 catalogued non-cut.
WHY THIS OWNER:  Shared tokens used by a twelve-engine
                 module and by kernel. Honest home is
                 core, named for the thing, not an
                 append onto exception_taxonomy.py or
                 events.py. Kernel → core is legal
                 (kernel sits above core). That
                 retarget is not a pin pair: kernel is
                 not walked. Not A-00: forensics is an
                 engine. Not A-01: this is not
                 KernelFault.
FILES:           src/feelies/core/forced_exit_reasons.py
                 (new)
                 src/feelies/kernel/forced_exit_reasons.py
                 src/feelies/kernel/orchestrator.py
                 src/feelies/forensics/gate_close_attribution.py
                 tests/conformance/test_import_contracts.py
                 tests/docs/test_prompt_coverage_map.py
                 docs/prompts/README.md
                 Do not edit harness/, bootstrap.py,
                 cli/, massive_ws.py,
                 test_fail_quiet.py, ci.yml.
                 Do not move _RISK_FORCED_EXIT_REASONS
                 or _SLICE_SCOPED_FORCED_EXIT_REASONS;
                 their only production consumer is
                 orchestrator, still via the kernel
                 module. tests/kernel that import
                 _RISK_FORCED_EXIT_REASONS stay on
                 kernel.forced_exit_reasons.
REFACTOR PATH:   one commit. Mechanism: move the
                 frozenset body into a new
                 feelies.core.forced_exit_reasons.
                 Do not re-export it from
                 kernel.forced_exit_reasons. A leftover
                 alias is T-06z again: forensics could
                 keep importing kernel and the pin
                 would not empty.
                 (1) Add core/forced_exit_reasons.py
                 with _SELF_ATTRIBUTED_FORCED_EXIT_REASONS
                 unchanged. Import nothing from
                 feelies.kernel. _FILE_OWNERS row
                 "core/forced_exit_reasons.py":
                 "audit_core_clock_config" and the
                 README citation, same commit, S-21.
                 (2) Delete that name from
                 kernel/forced_exit_reasons.py. Leave
                 the other two frozensets.
                 (3) Retarget forensics and
                 orchestrator to
                 feelies.core.forced_exit_reasons for
                 this name only. Orchestrator still
                 imports the other two from
                 kernel.forced_exit_reasons. kernel →
                 core is the legal downward edge, not
                 a new pin pair.
                 (4) Shrink _KERNEL_IMPORT_RESIDUALS
                 to frozenset() in the same commit.
                 Equality to frozenset() is already
                 the close. This pin has no
                 lint-imports status line. T-09z's
                 KEPT-before-pairs strengthening was
                 for Five import tiers, where an empty
                 _TIER_RESIDUALS could agree with a
                 BROKEN job if only the parsed pair
                 set was asserted. Here the walker
                 IS the detector. pairs ==
                 frozenset() fails on any remaining
                 ImportFrom of feelies.kernel from a
                 walked package. Do not add a fake
                 KEPT. Do not delete the pin test.
                 (5) Closure walk to fixpoint: run
                 _engine_kernel_import_pairs() after
                 the cut, before the pin shrink is
                 trusted. It MUST be empty. If
                 forensics still shows
                 kernel.forced_exit_reasons, the alias
                 leaked — not a cut, STOP, do not
                 shrink the pin.
                 (6) Probe: restore
                 `from feelies.kernel.forced_exit_reasons
                 import _SELF_ATTRIBUTED_FORCED_EXIT_REASONS`
                 on gate_close_attribution.py. Run only
                 test_engine_kernel_imports_equal_pin.
                 It MUST fail naming
                 ('feelies.forensics.gate_close_attribution',
                  'feelies.kernel.forced_exit_reasons').
                 Restore the core import. Then T-07c
                 probe: throwaway MacroState on
                 portfolio/fill_attribution.py MUST
                 still fail unexpected. Restore byte-
                 identical. Without the forensics
                 probe the empty pin is decorative.
                 Without the fill_attribution probe
                 A-00's detector may have died when
                 the pin went empty.
BLAST RADIUS:    boundary
VALIDATED BY:    test_engine_kernel_imports_equal_pin
                 equals frozenset(); closure walk
                 empty at fixpoint; forensics probe
                 failed-before then passed-after;
                 fill_attribution probe still names
                 the T-07c pair;
                 test_five_import_tiers KEPT;
                 test_twelve_engine_independence KEPT
                 at zero pairs;
                 tests/acceptance/test_backtest_app_baseline.py.
                 No XPASS. A new twelve-engine pair is
                 a STOP. lint-imports: both contracts
                 KEPT.
PARITY IMPACT:   Hold: all 64 HASH/COUNT constants, the
                 fingerprint, _BASELINE_CONFIG_HASH. A
                 moved HASH or COUNT means the reason
                 strings changed membership or
                 identity — STOP, do not re-pin.
DELETES:         _SELF_ATTRIBUTED_FORCED_EXIT_REASONS
                 from kernel/forced_exit_reasons.py;
                 the last engine → kernel pair from
                 the pin. Does not delete
                 kernel/forced_exit_reasons.py. Does
                 not delete the pin test.
NET DELTA:       src modules +1, public symbols +1
                 (the frozenset relocates; core is the
                 new owner), branch points 0
ROLLBACK:        revert the commit. Independently
                 revertible from nothing that follows
                 (campaign end). Not independently
                 revertible from A-01 (already landed;
                 test_import_contracts.py is shared).
                 orchestrator.py is shared with every
                 later campaign that edits it.
```
