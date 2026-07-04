# Determinism & Parity-Hash Audit — 2026-07-02

**Auditor:** test-infrastructure / reproducibility (read-only pass)
**Branch:** `claude/determinism-audit-unx396`
**Scope:** the Inv-5 parity harness (`tests/determinism/`), the scope locks
(`tests/acceptance/test_mypy_strict_scope.py`, `pyproject.toml`), and the causality
cross-reference (`tests/causality/test_anti_lookahead.py`).
**Posture:** evidence-based, read-only. No production code changed; no baseline re-pinned.

> **Method note.** This is a re-audit following
> [`determinism_audit_2026-06-24.md`](determinism_audit_2026-06-24.md). That audit's
> backlog was largely (not entirely) remediated in a same-day commit sequence on
> 2026-06-26 (`f6fdafa`, `06061b0`, `533e22a`, `8822343`, `5b546be`, `6a77bbf`, `a75d6dc`,
> `bdae0ed`, plus the orchestrator fix `1f0c1c0`/`19c375e`/`abe4b33`). Every claim below was
> independently re-verified against the current tree rather than assumed from the prior
> report — where the prior report's characterization still holds, it is cited; where this
> pass found something new or different, that supersedes it. All eleven/twelve/seventeen
> replays were run (`uv run pytest tests/determinism/`), the mypy scope lock was run
> (`tests/acceptance/test_mypy_strict_scope.py`), and the anti-lookahead suite was run.
> Findings are tagged **[harness weakness]** (the test is structurally unable to catch a
> class of bug), **[coverage gap]** (no test exists), **[doc drift]** (documentation no
> longer matches the tree), or **[intentional scope]** (deliberately out of scope,
> documented).

---

## 0. Headline: what changed since 2026-06-24

The prior audit's three P0s are **closed and independently re-verified live in this
session**:

| Prior P0 | Status | Live evidence this session |
|---|---|---|
| #1 `strict = true` unlocked | **Closed** | `test_strict_mode_enabled_in_pyproject` now asserts it (`tests/acceptance/test_mypy_strict_scope.py:132-152`) |
| #2 override check too narrow | **Closed (mostly — see §5.4)** | `_strict_weakening_reasons` checks 8 knobs, not just `ignore_errors` (`:106-129`) |
| #3 orchestrator `SyntaxError` | **Closed** | `tests/causality/test_anti_lookahead.py` collects and passes (7 passed); `tests/determinism/` collects and passes (108 passed, up from 62) |

Five of the prior report's P1 coverage gaps also shipped genuine new baselines: PnL
(`position_pnl`), `StateTransition`, `CrossSectionalContext`, non-empty `Signal`
(`signal_fires`), and multi-symbol `SensorReading`. A cross-process `PYTHONHASHSEED`
independence test and a first orchestrator-level integration replay were added as well —
neither was in the prior backlog verbatim; both are net-positive, evidence-backed
additions. This pass verified each is a **real** fix, not a name-only one, and found the
residual gaps documented below. Two prior-backlog items were **not** picked up: the
`SymbolHalted` gap and the `market_fill_acks` missing-`.sequence` fix.

---

## 1. Executive summary

Top false-safety risks first. Each line is falsifiable and cited below.

1. **[good] The three prior P0s are genuinely closed**, not just claimed closed — reproduced
   live in this session (see §0). This materially changes the risk posture from the last
   audit and is why nothing in this report reaches P0.

2. **[harness weakness · P1] The new orchestrator-level "end-to-end" baseline pins emptiness
   for 3 of its 4 streams.** `test_orchestrator_replay.py` is the platform's first replay to
   drive the real `Orchestrator`/`build_platform`/`run_backtest` — closing the spirit of the
   prior audit's #3 and #6. But its canonical fixture never crosses an entry threshold, so
   `EXPECTED_ORCHESTRATOR_STREAMS` (`:144-149`) locks the well-known empty-SHA-256 for
   `signal`, `order`, and `position_update`; only `intent` (a single flat
   `SizedPositionIntent`) is non-trivial. A kernel-level ordering bug in order submission,
   ack processing, or position reconciliation — exactly the M4–M10 interleaving this test
   exists to protect — would not be caught, because no order ever flows through the fixture
   it replays.

3. **[harness weakness · P1, empirically confirmed] That same baseline is invisible to the
   manifest's own completeness scanner.** `test_every_locked_hash_is_registered_or_exempt`
   (`tests/determinism/test_parity_manifest.py:116-142`) scans for constants matching
   `^EXPECTED_\w*_HASH` (`:127`). `EXPECTED_ORCHESTRATOR_STREAMS` doesn't end in `_HASH` —
   confirmed by running the exact regex against the file in this session: zero matches. The
   baseline is therefore neither registered in `LOCKED_PARITY_BASELINES` nor listed in
   `_UNREGISTERED_HASH_EXEMPTIONS` (`:91-97`, which today holds exactly one entry, the
   solver hash) — not because anyone decided to hide it, but because the naming-convention
   scanner never saw it to flag it.

4. **[doc drift · P1] "Eleven" is now off by more than 6×.** The audit's own agent-context
   bundle (`.cursor/skills/README.md` → testing-validation) and the canonical
   `testing-validation/SKILL.md` state "eleven entries" seven times
   (`SKILL.md:15,43-44,128,151,264,276,280`); `system-architect/SKILL.md:392` repeats it.
   `LOCKED_PARITY_BASELINES` has **17** registered entries today
   (`parity_manifest.py:104-172`), plus one exempted (solver) plus one invisible
   (orchestrator, see #3) — at least 19 distinct locked hash artifacts. Anyone treating the
   "canonical" skill doc as ground truth for coverage undercounts it substantially.

5. **[coverage gap · P1, carried forward unchanged] `SymbolHalted` and `RiskVerdict` remain
   completely uncovered by any parity hash.** Zero hits for either event type across
   `tests/determinism/` (grep-confirmed this session). Both were flagged in the prior audit;
   neither was among the five gaps closed on 2026-06-26. `SymbolHalted` gates fill
   suppression during a halt/SSR window (Inv-11) and `RiskVerdict` is the risk engine's own
   action/scaling decision — both are tested for *correctness* elsewhere (`RiskVerdict`:
   14 files; `SymbolHalted`: 1 file) but neither has a replay hash pinning emission order or
   sequence allocation.

6. **[coverage gap · P1, partial fix] `StateTransition` now has a real parity hash — for 2 of
   the platform's 5 state machines.** `test_state_transition_replay.py` drives `RiskLevel`
   and `OrderState` through a legal walk and hashes the stream (`:41-111`) — a genuine,
   well-built fix (illegal-edge guard at `:142-157` proves the tables are load-bearing, not
   permissive). `MacroState`, `MicroState`, and `DataHealth` have property/enum-completeness
   coverage (`tests/kernel/test_macro.py`, `test_micro*.py`,
   `tests/ingestion/test_data_integrity.py`) but no baseline pins their emitted
   `StateTransition` stream.

7. **[harness weakness · P2, residual] The new cross-process `PYTHONHASHSEED` test doesn't
   probe two of the six `sorted()`-dependent hash functions.**
   `test_hash_seed_independence.py` proves 3-seed identity for `regime`, `intent_off`,
   `intent_on`, `snapshot` (`:38-48`) — a genuine, well-reasoned fix (see §6). It omits
   `state_transition` (sorts `s.metadata.items()`,
   `test_state_transition_replay.py:46`) and `cross_sectional_context` (sorts
   `signals_by_symbol` / `snapshots_by_symbol`,
   `test_cross_sectional_context_replay.py:129,131`). A regression that dropped either
   `sorted()` call would not be caught by the same-process two-run tests (same seed) nor by
   this probe (wrong paths).

8. **[harness weakness · P2, residual] The mypy override check covers 5 of mypy 1.20.2's 14
   `--strict` flags by name, plus a blanket catch-all.** Verified live against
   `python -m mypy --help` (this session, mypy 1.20.2): `--strict` enables
   `disallow_any_generics`, `disallow_subclassing_any`, `disallow_untyped_calls`✓,
   `disallow_untyped_defs`✓, `disallow_incomplete_defs`✓, `check_untyped_defs`✓,
   `disallow_untyped_decorators`, `warn_redundant_casts`, `warn_unused_ignores`,
   `warn_return_any`✓, `no_implicit_reexport`, `strict_equality`, `strict_bytes`,
   `extra_checks`. `_strict_weakening_reasons` (`test_mypy_strict_scope.py:106-129`)
   explicitly checks the 5 marked ✓ plus a blanket `strict=false`. A surgical per-module
   override flipping only `disallow_any_generics`, `disallow_subclassing_any`,
   `implicit_reexport`, or `strict_equality` would pass both scope-lock tests undetected.
   Narrower than the prior P0 (the highest-traffic flags are covered; exploiting the rest
   requires an unusual, targeted override) — hence P2, not P0.

9. **[coverage gap · P1, still open] The production reference-alpha `Signal` baseline is
   still empty.** `test_signal_replay.py:210-211` still locks
   `EXPECTED_LEVEL2_SIGNAL_COUNT = 0` for `sig_benign_midcap_v1` and all four v0.3 alphas
   against the canonical fixture. The remediation added a **parallel** synthetic-probe
   baseline (`signal_fires`, count 4) proving the hash *mechanism* can pin real content — but
   no actual production reference alpha's own emission is pinned non-empty, so a
   signal-ordering bug specific to one of those five alphas' real gate/decision logic would
   still hide behind the empty hash.

10. **[harness weakness · P2, carried forward unchanged] `market_fill_acks` still omits
    `.sequence`.** `_hash_acks` (`test_market_fill_replay.py:90-96`) hashes `order_id`,
    `status`, `filled_quantity`, `fill_price`, `fees`, `cost_bps`, `timestamp_ns` — no
    `.sequence`, even though `OrderAck` carries one (`core/events.py:348-368`, inherited from
    `Event`). This was an explicit S-effort item in the prior backlog (#13) that wasn't
    picked up alongside the five siblings that were.

11. **[doc drift · P2, carried forward, risk now mitigated differently] §12.5 still claims
    "CI sets `PYTHONHASHSEED=0`."** Still false — no `.github/workflows/` or any CI config
    exists in this repository (confirmed again this session). Unlike the last audit, the
    *underlying risk* is now genuinely addressed — by `conftest.py:27-43`'s honest warning
    (it explicitly explains it *cannot* set the seed mid-session and why) plus
    `test_hash_seed_independence.py`'s direct cross-seed proof, which is arguably a stronger
    guarantee than pinning one seed. The doc simply wasn't updated to describe the actual
    (better) mechanism that replaced the claimed one.

12. **[doc drift · P2, new] `docs/acceptance/v02_v03_matrix.md` does not exist and never
    has.** Cited by name in 7 places (`testing-validation/SKILL.md`, `pyproject.toml:77`,
    and 5 acceptance test files) including the exact assertion-failure message a contributor
    sees when they trip the gap-Z scope lock (`test_no_strict_overrides_in_pyproject:185`).
    `git log --all --diff-filter=D` shows no deletion event — it was never created.

13. **[good, verified] No laundering found in this pass.** Spot-checked
    `test_portfolio_order_replay.py` (leg lex-order is asserted directly on production output
    at `:140-162`, not sorted away in the hash), `test_regime_hazard_replay.py` (frozen
    literal, not the historical sibling-driver tautology), and
    `test_cross_sectional_context_replay.py` (emission order is list order; only the
    *within-event* `signals_by_symbol` dict is sorted, which is correct canonicalization of
    an unordered field, not concealment of a stream-ordering bug). Every `sorted()` found
    canonicalizes a dict *field*, never the event *stream*.

14. **[good, verified] The manifest completeness checks work for their designed case.**
    `test_replay_map_matches_manifest_keys` and
    `test_every_locked_hash_is_registered_or_exempt`
    (`tests/determinism/test_parity_manifest.py:100-142`) do catch a
    declared-but-unwired or wired-but-undeclared baseline, for anything matching the
    `_HASH` naming convention — a real, working closure of the prior audit's #11, with the
    one blind spot in finding #3 above.

15. **[harness weakness · P1, carried forward unchanged] DTZ still cannot see `time.*`.**
    `select = ["DTZ"]` (`pyproject.toml:113-115`) flags only `datetime.*`. The previously
    flagged `bootstrap.py:2298` `time.time()` fallback is unchanged (still present, still
    narrowly guarded and logged — see §5.2); ~13 `time.monotonic()` calls remain in
    harness/broker/ingestion progress-timing code, invisible to the lint by construction.

---

## 2. Parity-hash scope table — what each baseline actually pins

Eighteen locked artifacts total: 17 registered in `LOCKED_PARITY_BASELINES`
(`parity_manifest.py:104-172`) + 1 exempted (solver) + 1 invisible-to-the-scanner
(orchestrator, counted separately, not in the 17). "Ordering" = emission order preserved
by iterating the captured list (not sorted away). "Seq" = the event's own `.sequence` is
in the hashed line. "2-run" = same-process replay identity test present. "X-seed" = covered
by `test_hash_seed_independence.py`'s 3-seed subprocess probe.

| # | Baseline (manifest key) | Hash fn (file:line) | Count | Ordering | Seq | 2-run | X-seed | Real or synthetic input |
|---|---|---|---|---|---|---|---|---|
| 1 | `level1_sensor_reading` | `test_sensor_reading_replay.py:75` | 12,000 | ✅ | ✅ | ✅ | ❌ | **real** fixture, 4 sensors, 1 symbol |
| 2 | `level1_v03_sensor_reading` | `test_v03_sensor_replay.py:124` | 9,428 | ✅ | ✅ | ✅ | ❌ | **real** fixture, 4 v0.3 sensors, 1 symbol; libm-sensitive |
| 3 | `level2_horizon_tick` | `fixtures/replay.py:202` | 28 | ✅ | ✅ | ✅ | ❌ | **real** fixture, scheduler only |
| 4 | `level2_signal` | `test_signal_replay.py:171` | **0** | n/a | n/a | ✅ | ❌ | **real** fixture + real reference alphas — **pins absence only** (see §1.9) |
| 5 | `level3_horizon_feature_snapshot` | `test_horizon_feature_snapshot_replay.py:74` | 14 | ✅ | ✅ | ✅ | ✅ | **real** fixture, 1 symbol |
| 6 | `level3_sized_intent_decay_off` | `test_sized_intent_replay.py:180`(≈) | 4 | ✅ | ✅ | ✅ | ✅ | **synthetic** context, 5 symbols |
| 7 | `level3_sized_intent_decay_on` | same fn, `decay=True` | 4 | ✅ | ✅ | ✅ | ✅ | synthetic, 5 symbols; cross-checked ≠ decay-off (`test_decay_changes_hash_vs_baseline`, `test_sized_intent_with_decay_replay.py:57`) |
| 8 | `level4_portfolio_order` | `test_portfolio_order_replay.py:85` | 15 | ✅ | ✅ | ✅ | ❌ | synthetic intents → **real** `BasicRiskEngine`; lex-sort asserted directly (`:140-162`) |
| 9 | `level4_hazard_exit_order` | `test_hazard_exit_replay.py` (≈`:120`) | 3 | ✅ | ✅ | ✅ | ❌ | synthetic spikes+trades → real `HazardExitController` |
| 10 | `level5_regime_hazard_spike` | `test_regime_hazard_replay.py:134` | 3 | ✅ | ✅ | ✅ | ❌ | hand-built 7-tick fixture → real `RegimeHazardDetector`; frozen literal (not sibling-driver) |
| 11 | `level6_regime_state` | `test_regime_state_replay.py:79` | 40 | ✅ | ✅ | ✅ | ✅ | synthetic quotes → **real** `HMM3StateFractional.posterior()` |
| 12 | `market_fill_acks` | `test_market_fill_replay.py:90` | 9 | ✅ | **❌ no `.sequence`** | ✅ | ❌ | synthetic orders → real `BacktestOrderRouter` |
| 13 | `position_pnl` | `test_position_pnl_replay.py:75` | 6 | ✅ | ✅ | ✅ | ❌ | synthetic fills/marks → real `MemoryPositionStore`; **hand-mirrors** orchestrator's `PositionUpdate` field mapping rather than calling it (see §7) |
| 14 | `state_transition` | `test_state_transition_replay.py:41` | 16 | ✅ | ✅ | ✅ | ❌ | real `RiskLevel` + `OrderState` machines, 2 of 5 SMs (see §1.6) |
| 15 | `cross_sectional_context` | `test_cross_sectional_context_replay.py:125` | 2 | ✅ | ✅(`_ctx_seq`) | ✅ | ❌ | real `UniverseSynchronizer`, 4 symbols, 2 boundaries |
| 16 | `signal_fires` | `test_signal_fires_replay.py:36`(reuses `_hash_signal_stream`) | 4 | ✅ | ✅ | ✅ | ❌ | real `HorizonSignalEngine` + synthetic probe alpha (not a production reference alpha) |
| 17 | `multi_symbol_sensor_reading` | reuses `_hash_reading_stream` | 48 | ✅ interleaved | ✅ | ✅ | ❌ | real `SensorRegistry`, 3-symbol round-robin |
| 18 | `EXPECTED_LEVEL3_SOLVER_HASH` (exempted, not in manifest) | `test_sized_intent_solver_replay.py:109` | 4 | ✅ | ✅ | ✅ | ❌ | synthetic context → real cvxpy/ECOS path; skipped without `[portfolio]` extra |
| — | `EXPECTED_ORCHESTRATOR_STREAMS` (unregistered, **invisible** to completeness scan) | `test_orchestrator_replay.py:144` | 1/0/0/0 | ✅ | ✅ | ✅ | ❌ | **real** `Orchestrator`+`build_platform`+`run_backtest`; 3 of 4 streams are the empty hash (see §1.2) |

**A.1 — ordering & sequence allocation.** Sixteen of eighteen artifacts lock both ordering
and sequence. Two structural exceptions persist: `level2_signal` locks neither (empty
stream — but see #16, which proves the mechanism), and `market_fill_acks` omits `.sequence`
(unchanged from the prior audit).

**A.2 — laundering check.** No hash sorts away a real stream-ordering bug (see §1.13). Every
`sorted()` canonicalizes an unordered dict *field* (feature maps, target maps,
`signals_by_symbol`, transition `metadata`); event *emission order* is always preserved as
list-iteration order.

**A.3 — tautology check.** No baseline recomputes its expected value at test time. All 18
are frozen literals compared against a fresh replay. `test_parity_manifest.py:72-77`
re-verifies code-vs-constant agreement for the 17 registered entries; this cannot by
construction distinguish an intended coordinated re-pin from an unintended one (both sides
move together either way) — same limitation noted in the prior audit, unchanged, and still
only backed by commit-review discipline (§4).

---

## 3. Coverage matrix — bus event type × coverage kind

Event taxonomy from `src/feelies/core/events.py` (18 `Event` subclasses,
`:61-723`). "Pinned" = a locked parity hash exists for the event as an output.

| Event type (events.py) | Pinned? | 2-run | Multi-sym | Notes |
|---|---|---|---|---|
| `NBBOQuote` (`:61`) / `Trade` (`:94`) | input | — | ✅ (multi-symbol baseline) | inputs, not outputs |
| `SymbolHalted` (`:120`) | ❌ | ❌ | ❌ | **[gap, carried forward]** correctness-tested (1 file) but no replay hash |
| `RegimeState` (`:154`) | ✅ L6 | ✅ | ❌ 1 sym | covered |
| `Signal` (`:214`) | ⚠️ empty (reference alphas) + ✅ non-empty (synthetic probe) | ✅ | ❌ | mechanism proven, production alphas still pin absence only (§1.9) |
| `RiskVerdict` (`:276`) | ❌ | ❌ | — | **[gap, carried forward]** correctness-tested (14 files) but no replay hash; the action/scaling decision itself is unpinned even though its downstream leg-orders are |
| `OrderRequest` (`:317`) | ✅ L4 portfolio + hazard; ⚠️ orchestrator (empty except intent-derived legs never materialize) | ✅ | ✅ | leaf-level real, integration-level empty (§1.2) |
| `OrderAck` (`:348`) | ✅ `market_fill_acks` | ✅ | ❌ 1 sym | **no `.sequence` in hash** (unchanged, §1.10) |
| `PositionUpdate` (`:375`) | ✅ `position_pnl`; ⚠️ orchestrator (empty) | ✅ | ❌ 2 sym | field-mapping is hand-mirrored, not invoked (§7) |
| `StateTransition` (`:398`) | ✅ partial (`RiskLevel` + `OrderState` only) | ✅ | — | 2 of 5 SMs (§1.6) |
| `MetricEvent` (`:418`) | ❌ | ❌ | — | **[intentional scope]** telemetry side-channel |
| `Alert` (`:447`) | ❌ | ❌ | — | **[intentional scope]** telemetry side-channel |
| `KillSwitchActivation` (`:465`) | ❌ | ❌ | — | **[intentional scope, low]** safety side-channel; irreversibility covered by SM/property tests, not a replay hash |
| `RegimeHazardSpike` (`:532`) | ✅ L5 | ✅ | ❌ 1 sym | covered |
| `HorizonTick` (`:585`) | ✅ L2 | ✅ | ❌ 1 sym | covered |
| `SensorReading` (`:624`) | ✅ L1 ×2 + multi-symbol | ✅ | ✅ 3 sym | covered, closes prior B.3 gap for L1 |
| `HorizonFeatureSnapshot` (`:649`) | ✅ L3 | ✅ | ❌ 1 sym | covered |
| `CrossSectionalContext` (`:696`) | ✅ (closes prior gap) | ✅ | ✅ 4 sym | real `UniverseSynchronizer`, both completeness paths exercised |
| `SizedPositionIntent` (`:723`) | ✅ L3 on/off + solver | ✅ | ✅ 5 sym | best-covered layer |

### State-machine transitions (five platform SMs)

| SM | Enum file | Property/legality coverage | Parity-hash (`StateTransition` stream) coverage |
|---|---|---|---|
| `MacroState` | `kernel/macro.py` | ✅ `tests/kernel/test_macro.py` | ❌ no baseline |
| `MicroState` | `kernel/micro.py` | ✅ `tests/kernel/test_micro*.py` (3 files) | ❌ no baseline |
| `OrderState` | `execution/order_state.py` | ✅ (existing suites) | ✅ `state_transition` baseline |
| `RiskLevel` | `risk/escalation.py` | ✅ (existing suites) | ✅ `state_transition` baseline |
| `DataHealth` | `ingestion/data_integrity.py` | ✅ `tests/ingestion/test_data_integrity.py` | ❌ no baseline |

All five SMs have legality/enum-completeness coverage (illegal transitions raise, enum gaps
fail construction). Only 2 of 5 have a parity hash pinning the *emitted stream* of their
transitions (ordering, sequence allocation, timestamps) — a reordering or re-sequencing bug
specific to `MacroState`/`MicroState`/`DataHealth` transitions would not be caught by any
replay hash, only by the (orthogonal) legality tests.

**Multi-symbol / multi-day.** L1 (`multi_symbol_sensor_reading`, 3 symbols, explicit
interleave guard `test_stream_interleaves_all_symbols`), L3-intent (5 symbols), and L3-context
(4 symbols) are now multi-symbol — this closes the prior audit's B.3 gap for L1 and confirms
it was already closed for L3-intent. L2/L5/L6 remain single-symbol. **No baseline crosses a
session or day boundary** — day-rollover sequence-generator resets and session re-anchoring
remain unpinned, unchanged from the prior audit.

**Decay & regime.** Unchanged from the prior audit: decay-ON/OFF both pinned and
cross-checked to differ; regime state (L6) and regime hazard (L5) both pinned.

---

## 4. Baseline integrity audit

**Drift.** All 17 registered baselines are frozen literals; the git history for this window
shows disciplined, atomically-labeled re-pins/additions, each citing the specific
prior-audit finding it addresses:

```
a75d6dc test(determinism): add multi-symbol L1 interleave baseline (audit P1 #8)
6a77bbf test(determinism): add non-empty Signal emission baseline (audit P1 #4)
5b546be test(determinism): add CrossSectionalContext synchronizer baseline (P1 #7)
8822343 test(determinism): add StateTransition parity baseline (audit P1 #12)
533e22a test(determinism): add PnL (PositionUpdate) parity baseline (audit P1 #5)
f6fdafa test(determinism): harden scope locks per audit P0/P1 (#1,#2,#9,#10,#11)
bdae0ed Detect per-module strict=false as strict-weakening override
06061b0 test(determinism): orchestrator-level parity + bus order + hashseed visibility
abe4b33/1f0c1c0/19c375e fix(kernel): drop duplicate reason= kwarg (closes prior P0 #3)
```

This is exemplary provenance (Inv-13) for the changes it covers — no evidence of silent
drift anywhere in this window.

**Gated re-pin procedure.** Unchanged and confirmed present:
`scripts/rebaseline_parity_hashes.py` exists; the documented workflow
(`parity_manifest.py:4-8`) is "run script → copy constants → commit with rationale → run
`test_parity_manifest.py`." This remains a *process* control (a reviewer must notice a
coordinated code+constant move), not a technical one — the same limitation flagged in the
prior audit (§4 there), unchanged, and not addressed here (would need e.g. a
manifest-fingerprint-of-fingerprints surfaced in CI; still just a P2 recommendation, §8).

**Does the self-test detect missing/extra baselines?** **Improved, with one demonstrated
blind spot.** The prior audit's #11 (`test_parity_manifest.py` only iterated the manifest, so
a wired-but-unregistered hash was invisible) is now substantively fixed:
`test_replay_map_matches_manifest_keys` (`:100-113`) locks `_REPLAY_BY_NAME` and
`LOCKED_PARITY_BASELINES` to the same key-set, and
`test_every_locked_hash_is_registered_or_exempt` (`:116-142`) scans every
`test_*replay*.py` file for `EXPECTED_\w*_HASH` constants and requires each to be either
imported by the manifest or listed in `_UNREGISTERED_HASH_EXEMPTIONS`. This works exactly as
designed for the solver hash (the one entry in the exemption dict). It does **not** work for
`EXPECTED_ORCHESTRATOR_STREAMS` — confirmed empirically this session (§1.3) — because the
regex requires the constant name to end in `_HASH`, and this one doesn't. The scanner also
depends on the target file matching `test_*replay*.py`; every current baseline file happens
to satisfy this, but the convention itself is unenforced (a differently-named future baseline
file would silently escape the same way).

**Nomenclature debt (note, unchanged).** `EXPECTED_LEVEL4_READING_HASH` is still registered
under the manifest key `level1_sensor_reading` (`parity_manifest.py:105`) — a fossil of an
earlier numbering scheme. Confusing, not a determinism defect.

---

## 5. Scope-lock audit (mypy strict, DTZ, no-override)

### 5.1 mypy strict scope — genuinely hardened

Observed this session: all three tests in `tests/acceptance/test_mypy_strict_scope.py`
**PASS** (`test_mypy_strict_clean_on_src_feelies`,
`test_strict_mode_enabled_in_pyproject`, `test_no_strict_overrides_in_pyproject`; mypy
1.20.2, `--no-incremental` over `src/feelies`).

- **[closed] Prior P0 #1** (`strict = true` unlocked): `test_strict_mode_enabled_in_pyproject`
  (`:132-152`) now asserts `mypy_section.get("strict") is True` and that `python_version` is
  a pinned string. `pyproject.toml:74-75` confirms `strict = true` /
  `python_version = "3.12"`. Setting `strict = false` today would fail this test directly.

- **[closed, with residual gap] Prior P0 #2** (override check too narrow):
  `_strict_weakening_reasons` (`:106-129`) now flags a `feelies.*` override that sets
  `ignore_errors`, `strict=false`, `disallow_untyped_defs=false`,
  `disallow_incomplete_defs=false`, `disallow_untyped_calls=false`,
  `check_untyped_defs=false`, `warn_return_any=false`, any `disable_error_code`, or
  `follow_imports` in `{skip, silent}`. Cross-checked live against mypy 1.20.2's actual
  `--strict` bundle (`python -m mypy --help`, this session) — 14 flags total; 5 are checked
  by name, plus the blanket `strict=false` which subsumes all 14 at once. The **9 unchecked**
  flags are: `disallow_any_generics`, `disallow_subclassing_any`,
  `disallow_untyped_decorators`, `warn_redundant_casts`, `warn_unused_ignores`,
  `no_implicit_reexport` (inverse: `implicit_reexport`), `strict_equality`, `strict_bytes`,
  `extra_checks`. Of these, `disallow_any_generics=false`, `disallow_subclassing_any=false`,
  `implicit_reexport=true`, and `strict_equality=false` are the most consequential for
  silently re-admitting real bugs on a targeted `feelies.*` module; `warn_unused_ignores=false`
  is a slower-burn risk (stale `# type: ignore` comments stop being flagged, so they can mask
  a *newly introduced* error on the same line indefinitely). This is real but narrower than
  the original P0 — it requires a surgical, unusual override rather than the one-line
  `strict = false` the original finding exploited.

- **[note, unchanged] Slow-lane only.** Still `pytestmark = pytest.mark.slow` (`:53`); the
  default fast loop (`pytest -m "not functional and not slow"`) skips it. Still no
  `.github/workflows/` in the repo to confirm a slow lane actually runs it in CI (§5.4).

### 5.2 DTZ / datetime ban (Inv-10) — unchanged

- **Active** for `datetime.*` tree-wide (`pyproject.toml:113-115`).
- **[harness weakness · P1, unchanged]** `select = ["DTZ"]` cannot see `time.time()` /
  `time.monotonic()` / `time.perf_counter()`. Re-verified this session:
  `bootstrap.py:2298` still has `reference_time = time.time()`, reached only when
  `config.factor_loadings_dir` is set **and** `config.session_open_ns` is `None`
  (`:2266,2295-2298`), and it logs a warning naming Inv-5 explicitly (`:2299-2304`) — a
  narrow, opt-in, self-aware escape hatch, unchanged from the prior audit's characterization.
  Also unchanged: ~13 `time.monotonic()` calls in `ingestion/massive_ingestor.py`,
  `harness/backtest_prep.py`, `harness/backtest_runner.py`, `broker/ib/connection.py` — all
  progress-timing or IB-connection-polling, outside the replayed event stream, but invisible
  to the lint by construction either way.
- **[harness weakness · P2, unchanged]** `pyproject.toml:131` still exempts
  `src/feelies/monitoring/structured_logging.py` from `DTZ005/006/011`. Re-read this session:
  the file is a pure `Protocol`/`Enum` definition with no `datetime.now()` /
  `fromtimestamp()` / `today()` calls anywhere. Door open, still unused.

### 5.3 Third-party untyped imports — no longer a live contradiction

The prior audit's #16 cited a glossary line in `platform-invariants.mdc:95` claiming
third-party ignores are "never" project-level overrides, contradicting
`pyproject.toml:90-92`'s `ignore_missing_imports = true` block for `cvxpy`/`numpy`/`pyarrow`.
That exact claim no longer appears anywhere in the current
`.cursor/rules/platform-invariants.mdc` (grep-confirmed zero hits this session). Treat as
resolved/moot; the (benign — `ignore_missing_imports` is not a strictness knob)
`pyproject.toml:90-92` override itself is unchanged and was never the problem.

### 5.4 No CI configuration present in-repo — unchanged

Re-confirmed this session: no `.github/workflows/` directory, no `Makefile`/`tox.ini`/
`noxfile` anywhere in the tree. The CI stage table in `testing-validation/SKILL.md` and the
§12.5 `PYTHONHASHSEED=0` claim remain aspirational from the repository's own perspective —
nothing checked in enforces the slow-lane mypy test or a fixed hash seed. `SKILL.md`'s own
"Not shipped" framing already covers the CI-pipeline table (it says so explicitly:
"Not shipped: target pipeline"), so this is **not** re-scored as a fresh finding — it is
carried forward as context for §5.1's slow-lane caveat and §1.11's PYTHONHASHSEED note.

---

## 6. Determinism-test honesty audit (two-run vs stored-value vs cross-seed)

**Two-run vs stored value.** Unchanged, and still exemplary: every one of the 18 baselines
pairs a frozen-literal assertion with a `test_two_replays_produce_identical_*` /
`test_two_full_orchestrator_replays_are_identical` same-process test. Verified directly in
this session's `uv run pytest tests/determinism/ -q` (108 passed).

**Cross-process / cross-seed — materially improved.** The prior audit's sharpest honesty
finding (#9: "`PYTHONHASHSEED=0` is claimed but not wired; same-process two-run tests share
one seed and can't catch seed-dependent non-determinism") is now addressed by two
complementary, well-reasoned mechanisms rather than the naive fix of just pinning the seed:

1. `conftest.py:27-43` — cannot set `PYTHONHASHSEED` mid-session (correctly explains why: an
   `os.execv` re-exec would corrupt pytest's output capture), so instead it surfaces the
   active seed in the run header and **warns** when unpinned. Reproduced live this session:
   every `pytest` invocation in this audit emitted
   `PytestConfigWarning: PYTHONHASHSEED=None (expected '0')`.
2. `test_hash_seed_independence.py` — re-runs 4 dict-iterating replays
   (`regime`, `intent_off`, `intent_on`, `snapshot`) in **subprocesses** under seeds
   `"0"`, `"1"`, `"424242"` and asserts identical hashes (`:64-73`). This is a direct proof of
   seed-*independence*, which is a stronger property than seed-*pinning* (pinning one seed
   would not prove the hash is actually seed-invariant, only that CI happens to use one
   fixed value). Reproduced live this session as part of the 108-passed run.

The module's own docstring is explicit that the tick path's set-ordering dependency was
separately removed (fill distribution now sorts strategy IDs), so the residual risk from an
unpinned seed is now low. The one gap: the probe covers 4 of 6 `sorted()`-dependent hash
functions, not `state_transition` or `cross_sectional_context` (§1.7). This is a real, if
narrow, residual — not a re-opening of the original finding.

**Reliance on dict/set ordering, wall-clock, environment.**
- Wall-clock: unchanged — replays inject `SimulatedClock` or constant `ts_ns`; the one
  wall-clock read reachable from a replay-adjacent path (`bootstrap.py:2298`) is opt-in and
  logged (§5.2).
- Dict ordering: defended by `sorted()` at every hash-function boundary that touches a dict
  field (verified across every file read in this pass); the two-seed-omission gap in §1.7 is
  the only unproven case, not a known-bad one.
- Cross-libm: unchanged, still honestly bounded
  (`parity_manifest.py:13-26`, `test_transcendental_determinism.py:1-21`). Intra-process
  reproducibility is locked for the five `exp`/`log`-calling sensors; cross-host agreement
  remains a documented follow-up, not a hidden gap.

**The prior audit's "green-while-broken" demonstration no longer reproduces.** On
2026-06-24, the per-layer suite reported 62 passed while `orchestrator.py` didn't parse. On
this branch, `tests/determinism/` reports **108 passed** and orchestrator-dependent suites
(`test_anti_lookahead.py`, `test_legacy_sequence_isolation.py`,
`test_orchestrator_replay.py`) all collect and pass. The single cleanest proof-point from the
last audit is retired — but its lesson (the parity harness's blind spots are structural, not
incidental) is exactly what motivates §1.2/§1.3 above: the *new* orchestrator baseline closes
the "orchestrator doesn't parse" failure mode but not the "orchestrator never actually routes
an order in the fixture it replays" one.

---

## 7. Test gap matrix + proposed new baselines

| Gap | Kind | Today | Proposed minimal baseline (fixed log) | Closes |
|---|---|---|---|---|
| Orchestrator baseline pins emptiness for 3/4 streams | harness weakness | 1 non-empty stream (intent) of 4 | Extend `_synth_multi_symbol_events` (or add a sibling fixture) with at least one symbol/boundary that crosses a reference alpha's entry gate, so `signal`/`order`/`position_update` lock real content; keep the current fixture as a regression baseline for the flat-book case | §1.2 |
| Orchestrator baseline invisible to completeness scan | harness weakness | undetected | Either rename `EXPECTED_ORCHESTRATOR_STREAMS` → `EXPECTED_ORCHESTRATOR_STREAMS_HASH`-suffixed keys the scanner can see, or add an explicit `_UNREGISTERED_HASH_EXEMPTIONS`-style entry (or a second exemption dict) that the test asserts against by import, not just by regex | §1.3 |
| `SymbolHalted` / fill suppression | coverage gap | none | Extend the `market_fill` scenario with a halt+resume `SymbolHalted` pair and an entry attempt inside the blackout; hash the resulting ack stream (repeats the prior audit's still-open proposal) | §1.5 |
| `RiskVerdict` direct hash | coverage gap | none | Hash the ordered `RiskVerdict` stream from a deterministic `check_signal`/`check_sized_intent` walk that exercises `ALLOW`/`SCALE`/`VETO`/`FLATTEN` actions | §1.5 |
| `StateTransition` for `MacroState`/`MicroState`/`DataHealth` | coverage gap | property-only | Add the other 3 SMs to `test_state_transition_replay.py`'s walk (or a sibling module), sharing the one `SequenceGenerator` | §1.6 |
| Hash-seed probe gap (`state_transition`, `cross_sectional_context`) | harness weakness | 4/6 paths probed | Add both replays to `test_hash_seed_independence.py`'s `_probe()` | §1.7 |
| mypy override-check residual flags | harness weakness | 5/14 named | Add `disallow_any_generics`, `disallow_subclassing_any`, `implicit_reexport` (true), `strict_equality` to `_strict_weakening_reasons` | §1.8 |
| Production reference-alpha non-empty `Signal` | coverage gap | probe alpha only | Tune the synthetic fixture (or add a second one) so `sig_benign_midcap_v1` itself crosses its entry gate at least once, and lock that hash alongside the existing empty one | §1.9 |
| `market_fill_acks` no `.sequence` | harness weakness | omitted | Add `a.sequence` to `_hash_acks` (`test_market_fill_replay.py:90-96`) and re-baseline | §1.10 |
| `position_pnl` hand-mirrors orchestrator mapping | harness weakness | reimplemented, not invoked | Either import the orchestrator's actual `PositionUpdate`-construction helper (extracting it to a shared function if it isn't already one) or add an assertion that the two field-mappings stay identical | §8 item, new this pass |

---

## 8. Prioritized backlog

Effort: **S** ≤ ½ day, **M** ~1–2 days, **L** ≥ 3 days. Nothing in this pass reaches P0 — the
prior audit's P0s are closed (§0) and no new laundering, silently-re-pinnable baseline, or
weakened scope lock was found. Highest severity this pass is P1.

### P1 — real coverage/harness gaps carried forward or newly found
1. **Orchestrator baseline pins emptiness for Signal/OrderRequest/PositionUpdate** ·
   coverage · `test_orchestrator_replay.py:133-149` · *Fix (M):* fixture change so at least
   one boundary crosses an entry threshold; keep the flat-book case as a second locked
   baseline. · *Impact:* the only test exercising the full kernel's M4–M10 interleaving would
   then actually exercise it.
2. **Same baseline invisible to the manifest completeness scanner** · harness ·
   `test_parity_manifest.py:127` vs `test_orchestrator_replay.py:144` · *Fix (S):* rename the
   constant to match `_HASH`-suffix convention, or extend the scanner/exemption mechanism to
   cover it explicitly. · *Impact:* closes a demonstrated (not hypothetical) blind spot in the
   one check whose job is to prevent exactly this.
3. **`SymbolHalted` unpinned** · coverage · `core/events.py:120` · *Fix (M):* the halt+resume
   fill-suppression baseline proposed in the prior audit and still not built. · *Impact:*
   pins halt-gated fill determinism (Inv-11 adjacent).
4. **`RiskVerdict` unpinned** · coverage · `core/events.py:276` · *Fix (M):* hash a
   deterministic multi-action `RiskVerdict` walk. · *Impact:* pins the risk decision itself,
   not just its downstream order legs.
5. **`StateTransition` covers 2 of 5 SMs** · coverage · `test_state_transition_replay.py` ·
   *Fix (M):* extend the walk to `MacroState`/`MicroState`/`DataHealth`. · *Impact:* closes
   the remaining SM-transition-stream gap.
6. **Production reference-alpha `Signal` baseline still empty** · coverage ·
   `test_signal_replay.py:210-211` · *Fix (M):* tune the fixture so a real reference alpha
   crosses its gate at least once. · *Impact:* the largest remaining "pins-absence-only" hash
   for an actual production alpha, as opposed to a synthetic probe.
7. **DTZ blind to `time.*`** · harness · `pyproject.toml:113-115` · *Fix (S):* add a
   grep-based unit test (or ruff custom rule) banning `time.time(`/`time.monotonic(` outside
   `core/clock.py` + an explicit harness/broker allowlist. · *Impact:* closes the still-open
   half of Inv-10 the lint silently drops; unchanged from the prior audit's P1 #10.

### P2 — narrower residuals, hardening, doc integrity
8. **mypy override check misses 9 of 14 `--strict` flags** · harness ·
   `test_mypy_strict_scope.py:106-129` · *Fix (S):* add `disallow_any_generics`,
   `disallow_subclassing_any`, `implicit_reexport=true`, `strict_equality=false` at minimum.
   · *Impact:* closes the highest-value residual flags from the now-mostly-fixed prior P0.
9. **Hash-seed probe omits 2 of 6 `sorted()` paths** · harness ·
   `test_hash_seed_independence.py:38-48` · *Fix (S):* add `state_transition` and
   `cross_sectional_context` to `_probe()`. · *Impact:* closes the residual gap in an
   otherwise-strong fix.
10. **`market_fill_acks` omits `.sequence`** · harness · `test_market_fill_replay.py:90-96` ·
    *Fix (S):* add `a.sequence`, re-baseline. · *Impact:* locks ack sequence allocation;
    unchanged from the prior audit's P2 #13, still not done.
11. **`position_pnl` hand-mirrors orchestrator's `PositionUpdate` mapping instead of calling
    it** · harness · `test_position_pnl_replay.py:105-119` · *Fix (M):* extract the mapping
    orchestrator.py uses into a shared, importable function and call it from both places, or
    add a cross-check test. · *Impact:* a future drift in the real mapping (wrong field, wrong
    rounding) would otherwise pass this baseline unnoticed since it hashes a hand-copied
    reimplementation, not the production code path.
12. **Doc: "eleven" baselines, seven citations** · doc · `testing-validation/SKILL.md:15,
    43-44,128,151,264,276,280`, `system-architect/SKILL.md:392` · *Fix (S):* update to the
    current count or reference `len(LOCKED_PARITY_BASELINES)` instead of a hardcoded number.
    · *Impact:* the "canonical" doc should not undercount its own registry by 6×.
13. **Doc: §12.5 "CI sets `PYTHONHASHSEED=0`"** · doc ·
    `docs/three_layer_architecture.md:1475` · *Fix (S):* replace with a description of the
    actual mechanism (`conftest.py` warning + `test_hash_seed_independence.py` cross-seed
    proof). · *Impact:* the doc should describe the (better) mitigation that shipped instead
    of the one that didn't.
14. **`docs/acceptance/v02_v03_matrix.md` never existed** · doc · 7 citations including
    `test_no_strict_overrides_in_pyproject`'s own failure message · *Fix (S):* create the
    file (even a short one recording the gap-Z decision) or repoint the citations at wherever
    that history actually lives. · *Impact:* closes a dangling reference in the exact
    audit-trail path a contributor is told to follow.
15. **No CI-surfaced manifest fingerprint** · process · `parity_manifest.py` · *Fix (S):*
    unchanged recommendation from the prior audit's P2 #15 — emit one "manifest fingerprint"
    line so a coordinated re-pin is a one-line review diff. · *Impact:* makes silent
    coordinated re-pins visible; still not done.

---

## 9. Appendix — uncovered event types with proposed fixed logs

### A. `SymbolHalted` / fill-suppression baseline (P1 #3)
Fixed log: reuse the `market_fill` scenario's router/quote plumbing
(`test_market_fill_replay.py:63-87`), inject a `SymbolHalted(active=True)` between two
quotes, attempt a submit inside the blackout (expect suppression/no fill), then a
`SymbolHalted(active=False)` resume and a follow-up submit that should fill. Hash the
resulting ack stream with the existing `_hash_acks` (plus its own `.sequence` fix, P2 #10).

### B. `RiskVerdict` baseline (P1 #4)
Fixed log: a deterministic sequence of `Signal`/`SizedPositionIntent` inputs against a
`BasicRiskEngine` configured to produce one of each `RiskAction` — `ALLOW`, a
budget-driven `SCALE`, a cap-driven `VETO`, and an escalation-driven `FLATTEN` — via
`check_signal`/`check_sized_intent`. Hash
`f"{v.sequence}|{v.action.name}|{v.reason}|{v.scaling_factor}|{v.timestamp_ns}|{v.correlation_id}"`
over the ordered stream.

### C. Full-SM `StateTransition` baseline (P1 #5)
Extend `test_state_transition_replay.py`'s existing deterministic walk
(`:79-111`) with a `MacroState` boot-to-`BACKTEST_MODE`-to-`DEGRADED` sequence, a
`MicroState` single-tick M0→M10 backbone walk, and a `DataHealth`
`HEALTHY`→`GAP_DETECTED`→`HEALTHY` cycle, all emitting into the same shared
`SequenceGenerator` the existing test already uses. Re-baseline the combined hash and count.

### D. Non-empty production-alpha `Signal` baseline (P1 #6)
Fixed log: extend `tests/fixtures/event_logs/_generate.py`'s synthetic quote stream (or add
a sibling fixture) with a deliberate OFI/price run large enough that `sig_benign_midcap_v1`'s
real `on_condition`/entry logic actually fires at least once, mirroring what
`signal_fires_replay.py` already proves is possible for a probe alpha. Lock the resulting
non-empty hash alongside (not instead of) the existing empty-fixture baseline, so both "the
alpha stays flat on quiet data" and "the alpha fires and the ordering is stable" are pinned.

### E. Hash-seed probe extension (P2 #9)
Add two lines to `test_hash_seed_independence.py:_probe()`:
```python
from tests.determinism.test_state_transition_replay import _replay as transition_replay
from tests.determinism.test_cross_sectional_context_replay import _replay as xsect_replay
print("transition=" + transition_replay()[0])
print("xsect=" + xsect_replay()[0])
```

---

### Read-only commands executed (for reproduction)

```
uv sync --all-extras
    → 40 packages installed, incl. cvxpy/ecos (solver-path baseline not skipped)

uv run pytest tests/determinism/ -q
    → 108 passed, 1 warning (PYTHONHASHSEED unpinned — advisory only) in 16.70s

uv run pytest tests/acceptance/test_mypy_strict_scope.py -q
    → 3 passed, 1 warning in 7.83s

uv run pytest tests/causality/test_anti_lookahead.py -q
    → 7 passed, 1 warning in 0.54s

python3 -c "import re; ...  # confirmed EXPECTED_ORCHESTRATOR_STREAMS is invisible to
                            # test_parity_manifest.py's completeness regex"
    → zero matches (finding §1.3)

python -m mypy --help   # confirmed live --strict flag bundle for the installed
                         # mypy 1.20.2, used to score finding §1.8 / §5.1 precisely
```

No production code, baseline, config, or ledger was modified during this audit.
