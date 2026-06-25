# Determinism & Parity-Hash Audit — 2026-06-24

**Auditor:** test-infrastructure / reproducibility (read-only pass)
**Branch:** `claude/peaceful-goodall-5rr1g3` @ `221e255`
**Scope:** the Inv-5 parity harness (`tests/determinism/`), the scope locks
(`tests/acceptance/test_mypy_strict_scope.py`, `pyproject.toml`), and the causality
cross-reference (`tests/causality/test_anti_lookahead.py`).
**Posture:** evidence-based, read-only. No production code changed; no baseline re-pinned.

> **Method note.** All eleven/twelve replays were run (`uv run pytest tests/determinism/`),
> the mypy scope lock was run (`tests/acceptance/test_mypy_strict_scope.py`), and the
> anti-lookahead suite was attempted. Findings are tagged **[harness weakness]** (the test
> is structurally unable to catch a class of bug), **[coverage gap]** (no test exists), or
> **[intentional scope]** (deliberately out of scope, documented).

---

## 1. Executive summary

Top false-safety risks first. Each line is falsifiable and cited below.

1. **[harness weakness · P0] The mypy strict-scope lock does not lock `strict = true`.**
   `test_mypy_strict_scope.py:62-63` runs `mypy --no-incremental src/feelies` and asserts
   exit 0, inheriting strictness *entirely* from `pyproject.toml [tool.mypy] strict = true`
   (`pyproject.toml:73-74`). Neither acceptance test asserts that key is set. Flip it to
   `false` (or delete it) and **both** acceptance tests still pass — the entire strict
   regime silently evaporates. This is precisely a "silently re-pinnable scope lock."

2. **[harness weakness · P0] The no-override test catches only `ignore_errors`.**
   `test_no_strict_overrides_in_pyproject` (`:104-117`) rejects `ignore_errors = true` on
   `feelies.*` but ignores every other per-module strictness knob
   (`disable_error_code`, `disallow_untyped_defs = false`, `check_untyped_defs = false`,
   `warn_return_any = false`, `follow_imports = "skip"`). Any of those silences a strict
   failure on a `feelies.*` module without tripping the lock.

3. **[coverage gap · P0-class, branch state] The orchestrator does not parse, yet the
   determinism suite is green.** `src/feelies/kernel/orchestrator.py:4793` and `:4795` pass
   `reason=` twice to one `OrderRequest(...)` → `SyntaxError: keyword argument repeated`.
   The per-layer replays scored **62 passed** because they deliberately bypass the
   orchestrator (`tests/fixtures/replay.py:13-17`). mypy (broader scope) caught it; the
   parity hashes structurally cannot. This is the audit thesis in one data point.

4. **[harness weakness · P1] The Level-2 `Signal` parity hash pins *zero bytes of signal*.**
   `EXPECTED_LEVEL2_SIGNAL_HASH = e3b0c442…b855` is the SHA-256 of the **empty string**,
   `EXPECTED_LEVEL2_SIGNAL_COUNT = 0` (`test_signal_replay.py:210-211`). All five SIGNAL
   checks (reference + four v0.3 alphas) assert *no signals are emitted*. The glossary
   claims this hash "locks scope, ordering, and sequence allocation"
   (`platform-invariants.mdc:60`) — on the locked fixture it locks none of those for any
   actual signal; it only locks **absence**.

5. **[coverage gap · P1] PnL has no parity hash, though Inv-5 names it.** Inv-5:
   "same event log + parameters → bit-identical signals, **orders, PnL**"
   (`platform-invariants.mdc:20`). No baseline hashes `PositionUpdate` (carries
   `realized_pnl`/`unrealized_pnl`/`cumulative_fees`, `core/events.py:363-381`). The closest,
   `market_fill_acks`, pins `OrderAck` economics but not the position/PnL reconciliation.

6. **[coverage gap · P1] No end-to-end parity hash exists.** Every replay is a *per-layer
   isolated* harness fed synthetic inputs: L3/L4 consume hand-built `CrossSectionalContext`
   / `RegimeHazardSpike` (`test_sized_intent_replay.py:171-177`,
   `test_hazard_exit_replay.py:114-135`). The end-to-end tests the spec mandates
   (`test_v2_alpha_deterministic`, `test_legacy_alpha_parity_preserved`, `test_mixed_mode`,
   `docs/three_layer_architecture.md:1536-1543`) **do not exist** in the tree.

7. **[coverage gap · P1] The SIGNAL→PORTFOLIO handoff is unpinned.** `CrossSectionalContext`
   as an *output* of `UniverseSynchronizer` has no hash; the L3 test injects a hand-built
   one. The glossary asserts the synchronizer is "replay-byte-identical (Inv-5)"
   (`platform-invariants.mdc:88`) but nothing pins it.

8. **[coverage gap · P1] Single-symbol / single-day everywhere except composition.** L1/L2/L3
   sensor & snapshot replays use `frozenset({"AAPL"})` (`tests/fixtures/replay.py:74,102,150`);
   L5/L6 are single-symbol; only L3-intent/L4-order use 5 symbols. No replay crosses a
   session boundary or a day rollover, so cross-symbol *interleave* ordering (L1/L2) and
   session-reset sequence allocation are unpinned.

9. **[harness weakness · P1] `PYTHONHASHSEED=0` is claimed but not wired.** §12.5 states
   "CI sets `PYTHONHASHSEED=0`" (`docs/three_layer_architecture.md:1475`). `conftest.py`
   does not set it, there is **no `.github/workflows/`**, and no Makefile/tox sets it. The
   two-run identity tests run in one process (same seed), so they cannot catch
   hash-seed-dependent non-determinism either. Mitigated in practice only because hash
   functions use `sorted()`.

10. **[harness weakness · P1] The DTZ lint cannot enforce the `time.time()` ban.** Ruff
    `select = ["DTZ"]` (`pyproject.toml:113-115`) flags `datetime.*` only; `time.time()` /
    `time.monotonic()` are invisible to it. CLAUDE.md claims the `time.time()` ban is
    "enforced by ruff CI" — it is not. A live `time.time()` sits at `bootstrap.py:2251`.

11. **[harness weakness · P2] A production module re-opens the datetime door.**
    `pyproject.toml:131` grants `src/feelies/monitoring/structured_logging.py` a
    `DTZ005/006/011` per-file ignore, contradicting CLAUDE.md ("Only `core/clock.py` is
    exempted"). Currently **dormant** (no `datetime.now()` in the file today) — door open,
    not yet walked through.

12. **[harness weakness · P1] The manifest self-test has no completeness assertion.**
    `test_parity_manifest.py` iterates `LOCKED_PARITY_BASELINES` only. It detects a manifest
    entry with no wired replay (KeyError) but **not** a locked `EXPECTED_*_HASH` that was
    never registered — exactly how `EXPECTED_LEVEL3_SOLVER_HASH`
    (`test_sized_intent_solver_replay.py:109`) sits outside the registry today.

13. **[doc drift · P1] "Eleven" is wrong; the manifest has twelve (+1 unregistered).**
    SKILL.md says "eleven" (`:7-8,25-26,52`); `LOCKED_PARITY_BASELINES` has 12 (adds
    `market_fill_acks`, `parity_manifest.py:117-121`); a 13th locked hash (solver) is
    unregistered. Nothing asserts a count, so the drift is invisible to CI.

14. **[good · note] No tautological baselines remain; the one that existed was fixed.**
    Every `EXPECTED_*_HASH` is a frozen literal compared against a fresh replay. The L5
    hazard test documents a *prior* vacuous baseline (computed via a sibling driver, moving
    both sides in lockstep) and its remediation to a frozen literal
    (`test_regime_hazard_replay.py:170-182`). This is the correct pattern.

15. **[good · note] Intra-process determinism and the cross-libm caveat are honest.** Every
    baseline has a two-run identity test, and the transcendental/cross-libm limit is
    documented rather than hidden (`parity_manifest.py:13-26`,
    `test_transcendental_determinism.py:1-21`). The honesty gap is *cross-process / cross-host*,
    not intra-process.

---

## 2. Parity-hash scope table — what each baseline actually pins

Twelve registered baselines (`parity_manifest.py:84-122`) + one unregistered (solver).
"Ordering" = emission order preserved by iterating the captured list (not sorted away).
"Seq" = the event's own `.sequence` is in the hashed line. "2-run" = same-process replay
identity test present.

| # | Baseline (manifest key) | Hash fn (file:line) | Fields pinned | Ordering | Seq | 2-run | Real or synthetic input | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | `level1_sensor_reading` | `test_sensor_reading_replay.py:75-87` | seq, sensor_id, version, symbol, value, warm, ts, corr_id | ✅ emission | ✅ | ✅ | **real** fixture, 4 simple sensors, 1 symbol | count 12 000 |
| 2 | `level1_v03_sensor_reading` | `test_v03_sensor_replay.py:124-136` | same shape | ✅ | ✅ | ✅ | **real** fixture, 4 v0.3 sensors, 1 symbol | count 9 428; libm-sensitive |
| 3 | `level2_horizon_tick` | `fixtures/replay.py:202-220` | seq, horizon, boundary, scope, symbol, session, corr, ts | ✅ | ✅ | ✅ | **real** fixture, scheduler only | count 28 |
| 4 | `level2_signal` | `test_signal_replay.py:171-187` | (would pin seq, symbol, dir, strength, edge, gate, mech, …) | n/a | n/a | ✅ | **real** fixture | **count 0 — empty-string hash; pins nothing but absence** |
| 5 | `level3_horizon_feature_snapshot` | `test_horizon_feature_snapshot_replay.py:74-84` | seq, symbol, horizon, boundary, ts, corr, **sorted** values/warm/stale | ✅ across snapshots | ✅ | ✅ | **real** fixture, 1 symbol | dict items sorted = within-snapshot canonicalization (OK) |
| 6 | `level3_sized_intent_decay_off` | `test_sized_intent_replay.py:180-201` | seq, ts, strat, layer, horizon, corr, gross, turnover, **sorted** targets/factors/mech | ✅ across intents | ✅ | ✅ | **synthetic** `CrossSectionalContext`, 5 symbols | |
| 7 | `level3_sized_intent_decay_on` | same fn, `decay=True` | same | ✅ | ✅ | ✅ | synthetic, 5 symbols | cross-checked ≠ decay-off (`…with_decay:57-68`) |
| 8 | `level4_portfolio_order` | `test_portfolio_order_replay.py:85-94` | seq, ts, order_id, symbol, side, type, qty, strat, reason, corr, src | ✅ emission | ✅ | ✅ | **synthetic** intents → real risk engine | per-intent legs lex-sorted in **production**, not in hash (no laundering) |
| 9 | `level4_hazard_exit_order` | `test_hazard_exit_replay.py:138-147` | same order shape | ✅ | ✅ | ✅ | **synthetic** spikes+trades, 3 symbols | |
| 10 | `level5_regime_hazard_spike` | `test_regime_hazard_replay.py:134-145` | seq, symbol, engine, departing, posteriors, incoming, score, ts, corr | ✅ | ✅ | ✅ | **hand-built** 7-tick `RegimeState` fixture, 1 symbol | frozen literal (ex-vacuous) |
| 11 | `level6_regime_state` | `test_regime_state_replay.py:79-88` | seq, symbol, engine, dominant, name, posteriors, entropy, ts | ✅ | ✅ | ✅ | synthetic quotes → **real** `HMM3StateFractional.posterior()`; RegimeState assembled in-test | 1 symbol |
| 12 | `market_fill_acks` | `test_market_fill_replay.py:90-96` | order_id, status, filled_qty, fill_price, fees, cost_bps, ts | ✅ emission | **❌ no `.sequence`** | ✅ | **synthetic** orders → real `BacktestOrderRouter` | only baseline that reaches fill economics |
| 13 | `EXPECTED_LEVEL3_SOLVER_HASH` (unregistered) | `test_sized_intent_solver_replay.py` | same as intent | ✅ | ✅ | ✅ | synthetic, cvxpy/ECOS path | **not in manifest**; skipped without `[portfolio]` extra |

**A.1 — ordering & sequence allocation.** Eleven of twelve hashes lock ordering *and*
sequence. Two structural exceptions: `level2_signal` locks neither (empty), and
`market_fill_acks` omits `.sequence` (`test_market_fill_replay.py:90-96`) so a re-sequenced
ack stream with identical economics/order_id would pass.

**A.2 — laundering check (does any hash sort away a real ordering bug?).** No. The
within-event dict sorts in snapshot (`:82-84`) and intent (`:183-193`) canonicalize
*unordered* dicts (feature maps, target maps); the *emission order* of events is always the
list-iteration order and is preserved. The portfolio leg lex-sort happens in **production**
(`BasicRiskEngine.check_sized_intent`), and the hash captures whatever order production
emits, so a production reordering would flip the hash (cross-checked by
`test_orders_are_lex_sorted_within_each_intent`, `:140-162`). **Verdict: no laundering.**

**A.3 — tautology check.** No baseline recomputes its expected value at test time. All are
frozen literals. The only historical tautology (L5 sibling-driver) is fixed and documented
(`test_regime_hazard_replay.py:170-182`). The manifest self-test recomputes and compares to
the frozen constants (`test_parity_manifest.py:59-64`) — this catches a constant edited away
from reality, but cannot, by construction, tell an *intended* re-pin from an unintended one
(both code and constant moving together pass). The only backstop there is review (see §4).

---

## 3. Coverage matrix — bus event type × coverage kind

Event taxonomy from `src/feelies/core/events.py`. "Pinned" = a locked parity hash exists for
the event as an **output**. "2-run" = covered by a same-process identity test.
"Multi-sym" = exercised with >1 symbol. "X-platform" = cross-host/cross-libm pinned.

| Event type (events.py) | Pinned? | 2-run | Multi-sym | X-platform | Assessment |
|---|---|---|---|---|---|
| `NBBOQuote` / `Trade` (`:49,82`) | input | — | — | — | inputs (fixture), not outputs |
| `SensorReading` (`:593`) | ✅ L1 ×2 | ✅ | ❌ 1 sym | ❌ libm-bound | **covered** (single-symbol) |
| `HorizonTick` (`:573`) | ✅ L2 | ✅ | ❌ | ❌ | **covered** (single-symbol) |
| `HorizonFeatureSnapshot` (`:618`) | ✅ L3 | ✅ | ❌ | ❌ | **covered** (single-symbol) |
| `Signal` (`:202`) | ⚠️ empty | ✅(of empty) | ❌ | ❌ | **[gap] pins absence only** |
| `CrossSectionalContext` (`:661`) | ❌ (synthetic input only) | — | (5 as input) | ❌ | **[gap] synchronizer output unpinned** |
| `SizedPositionIntent` (`:688`) | ✅ L3 on/off (+solver) | ✅ | ✅ 5 sym | ❌ | **covered** (best-covered layer) |
| `OrderRequest` (`:305`) | ✅ L4 portfolio + hazard | ✅ | ✅ | ❌ | **covered** |
| `OrderAck` (`:336`) | ✅ market_fill | ✅ | ❌ 1 sym | ❌ | covered; **no `.sequence` in hash** |
| `PositionUpdate` (`:363`) | ❌ | ❌ | ❌ | ❌ | **[gap] PnL — named by Inv-5, unpinned** |
| `RiskVerdict` (`:264`) | ❌ (veto effect implied via L4) | ❌ | — | — | **[gap] action/scaling unpinned directly** |
| `SymbolHalted` (`:108`) | ❌ | ❌ | ❌ | ❌ | **[gap] halt/fill-suppression unpinned** |
| `RegimeState` (`:142`) | ✅ L6 | ✅ | ❌ | ❌ | **covered** (single-symbol) |
| `RegimeHazardSpike` (`:520`) | ✅ L5 | ✅ | ❌ | ❌ | **covered** (single-symbol) |
| `StateTransition` (`:386`) | ❌ | ❌ | — | — | **[gap] SM audit stream unpinned** (see below) |
| `KillSwitchActivation` (`:453`) | ❌ | ❌ | — | — | [gap] safety side-channel (low) |
| `Alert` (`:435`) | ❌ | ❌ | — | — | [intentional] telemetry side-channel |
| `MetricEvent` (`:406`) | ❌ | ❌ | — | — | [intentional] telemetry side-channel |

**State-machine transitions.** SKILL.md names five SMs (MacroState, MicroState, OrderState,
RiskLevel, DataHealth, `SKILL.md:123-129`). Their validity is covered by **property** tests
(transition legality / enum completeness), but **no parity hash pins the `StateTransition`
stream** for a fixed replay. A reordered or re-sequenced transition log on identical input
would not be caught by any determinism baseline. **[coverage gap]**

**Multi-symbol / multi-day (B.3).** Only the composition baselines (#6–#9) are multi-symbol.
The sensor/scheduler/snapshot/regime baselines are single-symbol, so cross-symbol *emission
interleave* determinism at L1/L2/L3/L5/L6 is **unpinned**. **No baseline crosses a session or
day boundary**, so day-rollover sequence-generator resets and session re-anchoring are
**unpinned**.

**Decay & regime (B.2).** Decay-ON and decay-OFF are **both** pinned and cross-checked to
differ (`test_sized_intent_with_decay_replay.py:57-68`). Regime state (L6) and regime hazard
(L5) are **both** pinned. These two requirements are satisfied.

---

## 4. Baseline integrity audit

**C.1 — drift.** Baselines do move across commits, each with a justifying message. Example:
`f15de19 fix(harness): bind RTH/MOC session dates…` re-pinned **both** the L1 sensor hash and
the L4 portfolio-order hash; `c2d106c fix(regime): execute audit P0/P1/P2 backlog` re-pinned
the L1 sensor hash. The L4 order test even carries an inline re-baseline rationale dated
2026-06-18 (`test_portfolio_order_replay.py:98-105`). This is consistent with a disciplined
re-baseline workflow, not silent drift.

**C.2 — gated re-pin procedure.** A documented procedure exists:
`scripts/rebaseline_parity_hashes.py` prints the current fingerprints; the workflow
(`parity_manifest.py:4-8`) is "run script → copy constants into the owning module + manifest →
commit with rationale → run `test_parity_manifest.py`." SKILL.md elevates this to an invariant
("Parity-hash baselines are immutable — any change requires a documented architectural review,
not a one-line update", `SKILL.md:41-43`). **However, this is a *process* control, not a
technical one.** The manifest self-test re-verifies code-vs-constant agreement; it cannot
distinguish an intended re-pin from an unjustified one when code and constant move together.
A reviewer who misses a coordinated re-pin has no automated backstop. *Recommendation (P2):*
add a fingerprint-of-fingerprints (a single SHA-256 over the sorted manifest) printed in CI so
any baseline change surfaces as a one-line diff in review.

**C.3 — does the self-test detect missing/extra baselines?** Partially. **[harness weakness]**
`test_parity_manifest.py:54-64` parametrizes over `LOCKED_PARITY_BASELINES.keys()`:
- A manifest entry whose name is absent from `_REPLAY_BY_NAME` → `KeyError` → detected. ✅
- A locked `EXPECTED_*_HASH` constant that is **never registered** in the manifest →
  **undetected**. The solver baseline (`test_sized_intent_solver_replay.py:109`) is exactly
  this case today, and `market_fill_acks` was this case until someone remembered to register
  it. There is no assertion that
  `set(EXPECTED_*_HASH constants) == set(LOCKED_PARITY_BASELINES)`, nor any count assertion.
- Consequently the **"eleven vs twelve"** doc/code drift (SKILL.md `:7-8` vs
  `parity_manifest.py:84-122`) is invisible to CI.

**Nomenclature debt (note).** The constant `EXPECTED_LEVEL4_READING_HASH` is registered under
the manifest key `level1_sensor_reading` (`parity_manifest.py:85`). The `LEVEL4` in the name
is a fossil of §12.4's original numbering (where `SensorReading` was "Level 4",
`docs/three_layer_architecture.md:1461`); the manifest re-labels it L1. Same hash, two level
numbers — confusing but not a determinism defect.

---

## 5. Scope-lock audit (mypy strict, DTZ, no-override)

### 5.1 mypy strict scope — `tests/acceptance/test_mypy_strict_scope.py`

Observed run on this branch: `test_mypy_strict_clean_on_src_feelies` **FAILED**,
`test_no_strict_overrides_in_pyproject` **PASSED** (mypy checked 192 files and reported
`orchestrator.py:4776: "OrderRequest" gets multiple values for keyword argument "reason"`).
So the lock *is* catching the live break — good. But two structural weaknesses:

- **[harness weakness · P0] `strict = true` is not itself locked.** The subprocess is
  `mypy --no-incremental src/feelies` (`:62-63`) with **no `--strict` on the CLI**; strictness
  comes only from `pyproject.toml:73-74`. Neither test asserts the key is present/true. Setting
  `strict = false` keeps `test_mypy_strict_clean_on_src_feelies` green (mypy still exits 0 on
  clean non-strict code) and `test_no_strict_overrides_in_pyproject` green (it only inspects
  `overrides`). The whole regime is silently weakenable in one line.

- **[harness weakness · P0/P1] The override check is too narrow.** `:104-117` only flags
  `entry.get("ignore_errors")`. A contributor can add
  `[[tool.mypy.overrides]] module = "feelies.foo"` with `disable_error_code = [...]`,
  `disallow_untyped_defs = false`, `check_untyped_defs = false`, `warn_return_any = false`, or
  `follow_imports = "skip"` and silence strict errors on a `feelies.*` module while both tests
  stay green.

- **[note] Slow-lane only.** The test is `pytestmark = slow` (`:53`), so the default fast loop
  (`pytest -m "not … and not slow"`) skips it. It is load-bearing only if the CI slow lane runs
  — and there is **no `.github/workflows/` in the repo** to confirm it does (§5.4).

### 5.2 DTZ / datetime ban (Inv-10)

- **Active** for `datetime.*`: `select = ["DTZ"]` applies tree-wide (`pyproject.toml:113-115`).
- **[harness weakness · P1] DTZ cannot see `time.*`.** flake8-datetimez flags only
  `datetime.now/utcnow/fromtimestamp/today`. `time.time()` / `time.monotonic()` /
  `time.perf_counter()` are **not** linted. CLAUDE.md and the DTZ comment imply the
  `time.time()` ban is CI-enforced; it is not. Live evidence: `bootstrap.py:2251`
  `reference_time = time.time()` (a session-gated, *logged* escape — it warns it "breaks
  bit-identical replay") plus ~15 `time.monotonic()` calls in `harness/*`, `broker/ib/*`,
  `ingestion/massive_ingestor.py` (perf/progress timing — benign for the event stream, but
  proof the lint is blind to them).
- **[harness weakness · P2] Production DTZ exemption.** `pyproject.toml:131` exempts
  `src/feelies/monitoring/structured_logging.py` from `DTZ005/006/011`, contradicting CLAUDE.md
  ("Only `src/feelies/core/clock.py` is exempted"). Currently **dormant** — a grep of the file
  finds no `datetime.now()`/`fromtimestamp`/`today` (only the docstring at `:8`). The door is
  open; nothing has walked through it. Severity is P2 *today*, P1 the moment a logger
  implementation uses it.

### 5.3 Third-party untyped imports (D.3)

**[doc contradiction · P2]** The glossary states third-party untyped imports are handled
"at the call site with `# type: ignore[import-untyped]`, **never with a project-level
override**" (`platform-invariants.mdc:95`). But `pyproject.toml:90-92` is exactly a
project-level override: `module = ["cvxpy", …, "numpy", …, "pyarrow", …]
ignore_missing_imports = true`. This does **not** weaken `feelies.*` strictness
(`ignore_missing_imports` ≠ `ignore_errors`), so it is benign for the lock — but it
falsifies the stated policy and the `test_no_strict_overrides_in_pyproject` docstring's claim
that only `massive` is handled this way (`:91-94`).

### 5.4 No CI configuration present in-repo

There is **no `.github/workflows/`** directory and no `Makefile`/`tox.ini`/`noxfile`
configuring the gates. The CI table in SKILL.md (`:465-484`) and the §12.5 `PYTHONHASHSEED=0`
claim are therefore **aspirational from the repo's perspective** — nothing checked in
enforces them. Either CI lives outside the repo (unverifiable here) or the gates run only by
convention. **[harness weakness · P1]**

---

## 6. Determinism-test honesty audit (two-run vs stored-value)

**E.1 — bit-identical-across-runs vs stored value.** Each baseline does **both**: a
frozen-literal assertion *and* a same-process two-run identity test
(`test_two_replays_produce_identical_*`). The two-run tests are genuine (they would catch
module-level mutable state, RNG, or wall-clock leakage). **Caveat:** "two runs" means two calls
to `_replay()` **in the same process**, hence the **same `PYTHONHASHSEED`**. They therefore
**cannot** catch hash-seed-dependent non-determinism (dict/set hashing). A true cross-process /
cross-seed identity test does not exist. The genuinely strong guarantee is *intra-process*
reproducibility; the *cross-process / cross-host* guarantee is asserted in docs but unpinned.

**E.2 — reliance on dict/set ordering, wall-clock, environment.**
- Wall-clock: replays inject `SimulatedClock` or constant `ts_ns`; no wall-clock reads in the
  replay paths (verified by inspection). ✅
- Dict ordering: defended by `sorted()` at every emission boundary and in the hash functions
  (per §12.2 and §12.5). The risk is *latent*: the safety net §12.5 advertises
  (`PYTHONHASHSEED=0`) is **not actually set** (`conftest.py:1-24`, no CI). If any future hash
  path iterated a `set` or used builtin `hash`, the two-run test would not catch it and the
  baseline could pass non-deterministically across machines. The team is aware of this class
  (`sensors/impl/scheduled_flow_window.py:36` uses SHA-256 specifically to avoid salted
  `hash`), but awareness is not enforcement.
- Cross-libm: explicitly and honestly bounded (`parity_manifest.py:13-26`;
  `test_transcendental_determinism.py`). Five sensors using `exp`/`log` are flagged as
  last-bit-unstable across libm; intra-process identity is locked, cross-host is a documented
  follow-up. ✅ (honest)

**E.3 — the green-while-broken demonstration.** On this branch the per-layer determinism suite
reports **62 passed** while `orchestrator.py` does not parse. This is the cleanest possible
proof that "determinism green" ≠ "pipeline reproducible": the hashes are honest about *what
they replay*, but what they replay excludes the integration point where this break lives.

---

## 7. Test gap matrix + proposed new baselines

| Gap | Kind | Today | Proposed minimal baseline (fixed log) | Closes |
|---|---|---|---|---|
| Empty SIGNAL hash | harness weakness | count 0 | A 1-symbol fixture + a reference alpha tuned to **emit** ≥1 `Signal` (e.g. lower entry threshold or seed snapshot z-scores); lock the non-empty stream hash | makes #4 pin ordering/seq/content |
| No PnL/position hash | coverage gap | none | Replay the `market_fill` ack stream (#12) through `MemoryPositionStore` reconciliation; SHA-256 the resulting `PositionUpdate` stream (`realized_pnl`, `unrealized_pnl`, `cumulative_fees`, seq) | Inv-5 "PnL" clause |
| No end-to-end hash | coverage gap | none | Implement the spec's `test_v2_alpha_deterministic`: boot `run_backtest.py` on `synth_5min_aapl.jsonl` for the reference alpha, hash the **emitted `OrderRequest`/`OrderAck`** stream end-to-end | §13.5; catches orchestrator-level breaks |
| Synchronizer output | coverage gap | synthetic input | Drive real `UniverseSynchronizer` with the L2 signal stream + UNIVERSE ticks; hash the emitted `CrossSectionalContext` (sorted `signals_by_symbol`, `completeness`, `boundary_ts_ns`) | SIGNAL→PORTFOLIO handoff |
| `StateTransition` stream | coverage gap | property-only | Hash the ordered `StateTransition` events from one deterministic micro-state walk (machine, from, to, trigger, seq) | SM-transition determinism |
| `SymbolHalted` / fill suppression | coverage gap | none | Extend the `market_fill` scenario with a halt+resume `SymbolHalted` and an entry attempt inside the blackout; hash the ack stream | halt-gated fill determinism |
| Multi-symbol L1/L2 | coverage gap | 1 symbol | Add a 3-symbol (AAPL/MSFT/NVDA) sensor-reading + tick baseline to pin cross-symbol interleave order | L1/L2 cross-symbol ordering |
| Multi-day | coverage gap | 1 session | A 2-session replay asserting per-day sequence-generator reset + identical per-day hashes | day-rollover determinism |
| `market_fill` no seq | harness weakness | omits `.sequence` | Add `a.sequence` to `_hash_acks` (`test_market_fill_replay.py:90-96`) and re-baseline | ack sequence allocation |
| Cross-process identity | harness weakness | same-process only | One determinism test that re-runs a replay in a `subprocess` with a **different** `PYTHONHASHSEED` and compares hashes | hash-seed sensitivity |

---

## 8. Prioritized backlog

Effort: **S** ≤ ½ day, **M** ~1–2 days, **L** ≥ 3 days. Each item: component · `file:line` ·
one-line fix · Inv-5-confidence impact.

### P0 — false safety / silently weakenable locks
1. **mypy `strict=true` unlocked** · harness · `test_mypy_strict_scope.py:62-63` + `pyproject.toml:73-74` ·
   *Fix (S):* in `test_no_strict_overrides_in_pyproject`, assert `mypy_section.get("strict") is True`
   (and `python_version` pinned). · *Impact:* closes the one-line bypass of the entire type-scope lock.
2. **Override check too narrow** · harness · `test_mypy_strict_scope.py:104-117` ·
   *Fix (S):* also reject any `feelies.*` override that sets `disable_error_code`,
   `disallow_untyped_defs=false`, `check_untyped_defs=false`, `warn_return_any=false`, or
   `follow_imports="skip"`. · *Impact:* removes the alternative strict-silencing paths.
3. **Orchestrator does not parse (branch regression)** · pipeline · `orchestrator.py:4793,4795` ·
   *Fix (S):* delete the duplicate `reason=reason` left by merge `dbf401a` (main has `reason: str`). ·
   *Impact:* restores `test_anti_lookahead.py` (Inv-6) collectability and
   `test_legacy_sequence_isolation` import; unblocks any end-to-end replay. *Not a parity-harness
   defect — but the parity harness is structurally blind to it, which is the P0 lesson.*

### P1 — single-run gaps, missing coverage, narrower-than-claimed locks
4. **Empty L2 signal baseline** · harness/coverage · `test_signal_replay.py:210-211` ·
   *Fix (M):* ship a fixture/alpha that emits ≥1 signal; lock the non-empty stream. ·
   *Impact:* turns the largest "pins-absence-only" hash into a real ordering/seq/content lock.
5. **PnL unpinned** · coverage · `core/events.py:363-381` · *Fix (M):* add a `PositionUpdate`
   reconciliation baseline. · *Impact:* directly pins the "PnL" clause of Inv-5.
6. **No end-to-end parity hash** · coverage · `docs/…:1536-1543` (unimplemented) ·
   *Fix (L):* implement `test_v2_alpha_deterministic` through `run_backtest.py`. ·
   *Impact:* would have caught finding #3; pins the integration point.
7. **Synchronizer / `CrossSectionalContext` output unpinned** · coverage · `events.py:661` ·
   *Fix (M):* hash real synchronizer output. · *Impact:* pins SIGNAL→PORTFOLIO handoff.
8. **Single-symbol & single-day** · coverage · `fixtures/replay.py:74,102,150` ·
   *Fix (M):* add 3-symbol + 2-session baselines. · *Impact:* pins cross-symbol interleave and
   day-rollover sequence resets.
9. **`PYTHONHASHSEED` claimed not wired** · harness · `conftest.py` / `docs/…:1475` ·
   *Fix (S):* `os.environ.setdefault("PYTHONHASHSEED","0")` in `pytest_configure` **and** one
   cross-seed subprocess test; or wire it in the (absent) CI. · *Impact:* makes the documented
   mitigation real and catches hash-seed sensitivity.
10. **DTZ blind to `time.*`** · harness · `pyproject.toml:113-115` · *Fix (S):* add a ruff
    custom/`flake8-tidy-imports` ban or a unit test grepping `src/feelies` for
    `time.time(`/`time.monotonic(` outside `core/clock.py` + harness/broker allowlist. ·
    *Impact:* enforces the half of Inv-10 the lint silently drops.
11. **Manifest completeness not asserted** · harness · `test_parity_manifest.py` ·
    *Fix (S):* assert `set(_REPLAY_BY_NAME) == set(LOCKED_PARITY_BASELINES)` and register (or
    explicitly exempt) the solver hash. · *Impact:* prevents new locked hashes from silently
    escaping the registry; surfaces the 11-vs-12 drift.
12. **`StateTransition` stream unpinned** · coverage · `events.py:386` · *Fix (M):* hash one
    deterministic SM walk. · *Impact:* pins SM-transition ordering/sequence.

### P2 — hardening / tooling
13. **`market_fill` omits `.sequence`** · harness · `test_market_fill_replay.py:90-96` ·
    *Fix (S):* add `a.sequence`, re-baseline. · *Impact:* locks ack sequence allocation.
14. **Production DTZ exemption (dormant)** · harness · `pyproject.toml:131` · *Fix (S):* remove
    the `structured_logging.py` per-file ignore or document it in CLAUDE.md as a second
    sanctioned exemption. · *Impact:* closes the open datetime door.
15. **Re-pin has no review-surfaced diff** · process · `parity_manifest.py` · *Fix (S):* emit a
    single "manifest fingerprint" line in CI so any re-pin is a one-line review diff. ·
    *Impact:* makes silent coordinated re-pins visible.
16. **Third-party override contradicts glossary** · doc · `pyproject.toml:90-92` vs
    `platform-invariants.mdc:95` · *Fix (S):* reconcile the wording (allow project-level
    `ignore_missing_imports` for third-party, forbid only on `feelies.*`). · *Impact:* removes a
    false policy statement.
17. **Cross-libm provenance** · tooling · `parity_manifest.py:24-26` (already a documented
    follow-up) · *Fix (M):* stamp libm/host fingerprint next to each hash. · *Impact:* makes a
    cross-host mismatch attributable.

---

## 9. Appendix — uncovered event types with proposed fixed logs

Concrete, minimal replay logs for the highest-value gaps. All timestamps are deterministic
constants; no wall-clock, no RNG.

### A. `PositionUpdate` / PnL baseline (P1 #5)
Reuse the `market_fill` scenario (`test_market_fill_replay.py:63-87`) — buy 100, sell 100,
walk-the-book buy 200, stop-sell 100 — feed the resulting `OrderAck`s into a fresh
`MemoryPositionStore`, and hash the ordered `PositionUpdate` stream:
`f"{p.sequence}|{p.symbol}|{p.quantity}|{p.avg_price}|{p.realized_pnl}|{p.unrealized_pnl}|{p.cumulative_fees}|{p.cost_bps}|{p.timestamp_ns}"`.
Lock count + hash. This is the first baseline to reach realized PnL.

### B. End-to-end reference-alpha baseline (P1 #6)
Fixed log: the committed `tests/fixtures/event_logs/synth_5min_aapl.jsonl`. Boot
`run_backtest.py` for `alphas/sig_benign_midcap_v1` (single symbol), capture the emitted
`OrderRequest` **and** `OrderAck` streams via a `BusRecorder`, hash both. Requires the
orchestrator to parse (P0 #3) — which is the point: this baseline would fail loudly on the
current branch instead of passing 62 green.

### C. `CrossSectionalContext` synchronizer baseline (P1 #7)
Fixed log: 5-symbol universe, two UNIVERSE-scope `HorizonTick`s at boundaries 1–2, with a
deterministic per-(symbol,boundary) `Signal` book (drop one symbol per boundary to exercise
the `None`/completeness path). Drive the real `UniverseSynchronizer`; hash each emitted
context with `signals_by_symbol` serialized in **symbol-sorted** order, plus `completeness`
and `boundary_ts_ns`. Pins the §12.3 determinism claim that is currently proof-sketch-only.

### D. Multi-symbol L1 sensor baseline (P1 #8)
Fixed log: interleave AAPL/MSFT/NVDA quotes at staggered `ts_ns` so the three symbols' readings
interleave non-trivially. Reuse `_hash_reading_stream` (`test_sensor_reading_replay.py:75-87`)
unchanged — it already includes `symbol` and `sequence`, so cross-symbol emission order is
locked the moment the fixture has >1 symbol.

### E. `StateTransition` baseline (P1 #12)
Fixed log: one deterministic micro-state walk (M0→…→M10 backbone). Hash
`f"{t.sequence}|{t.machine_name}|{t.from_state}|{t.to_state}|{t.trigger}"` over the ordered
stream. Pins that the SM audit trail is itself replay-stable, not just legal.

---

### Read-only commands executed (for reproduction)
```
uv sync --all-extras
uv run pytest tests/determinism/ -q
    → 1 failed, 62 passed, 19 errors
      (failure: test_legacy_sequence_isolation::…default_generators — orchestrator import;
       19 errors: emit-jsonl tests → run_backtest → orchestrator SyntaxError)
uv run pytest tests/determinism/ --ignore=…emit_signals --ignore=…emit_hazard -q
    → 1 failed, 62 passed   (all 12 manifest baselines + solver + transcendental green)
uv run pytest tests/acceptance/test_mypy_strict_scope.py -q
    → 1 failed (test_mypy_strict_clean — orchestrator:4776 dup reason kwarg),
      1 passed (test_no_strict_overrides_in_pyproject); mypy checked 192 files
uv run pytest tests/causality/test_anti_lookahead.py -q
    → ERROR at collection (imports feelies.kernel.orchestrator → SyntaxError)
```
No production code was modified and no baseline was re-pinned during this audit.
