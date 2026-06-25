# Performance & Determinism-Safety Audit — 2026-06-25

**Scope:** the tick-to-trade hot path (`tick → sensor → snapshot → signal → risk → order`)
and its performance guardrails. The binding lens is **determinism (Inv-5)**: an optimization
is only admissible if it is behavior-preserving and replay-bit-identical. Read-only,
evidence-based. **No production code, baseline, or test was modified.**

**Method:** static read of the in-scope modules (`kernel/orchestrator.py`, `kernel/micro.py`,
`bus/event_bus.py`, `sensors/registry.py` + `sensors/impl/*`, `features/aggregator.py`,
`signals/horizon_engine.py`, `composition/*`, `risk/*`), plus off-path measurement via two
purpose-built micro-profilers that drive the **real** components (no production code touched).
All `path:line` citations are against the working tree at branch
`claude/gracious-turing-r3zle7`.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `pytest tests/perf/ tests/acceptance/test_perf_baseline_plumbing.py -q` | **4 passed, 1 skipped in 0.06 s** (measures no latency — see §6) |
| `python -m py_compile src/feelies/kernel/orchestrator.py` | **SyntaxError** at `orchestrator.py:4795` (see §0) |
| `pytest tests/kernel/test_orchestrator_bus_signal.py --collect-only` | **collection ERROR** (orchestrator won't import) |
| Test files importing the orchestrator / `build_platform` | **31 / 265** currently un-collectable |
| `pytest tests/determinism/ --collect-only` | **82 collected** — parity hashes are component-driven, still intact |
| Off-path profile: 13-sensor registry + scheduler + aggregator, 3 symbols, 13.7 k market events | **118 µs/market event**, 8 465 ev/s |
| Off-path profile: `CrossSectionalRanker.rank()` decay ON vs OFF | **+38 % to +48 %** stage-local overhead (§6) |
| `grep` for parallelism / wall-clock across `kernel,sensors,features,signals,composition,risk,bus` | **no parallelism on the decision path** (§5) |

**Classification legend:** **[PERF]** latency/allocation finding · **[GUARD]** regression-guard
gap · **[BLOCKER]** pre-existing defect blocking measurement (out of scope to fix) ·
**[DET-SAFE]** / **[DET-FORBIDDEN]** determinism classification of a proposed change.

> **Measurement caveat.** The orchestrator module does not currently compile (§0), so the full
> M0→M10 pipeline cannot be driven end-to-end. All measured numbers below are from driving the
> **real** hot-path components directly (sensor registry, scheduler, aggregator, cross-sectional
> ranker), which is the dominant per-event cost anyway. Numbers labelled *estimate* are derived
> from code structure, not measured. Absolute µs are from this audit host (CPython 3.12.3,
> Linux) and are **not** portable — they are for relative ranking, not budget certification.

---

## 0. Blocker that gates the whole perf-guard story (out of scope to fix)

**[BLOCKER] `orchestrator.py` does not compile — duplicated `reason=` kwarg.**
`_try_build_order_from_intent` (`kernel/orchestrator.py:4659`) builds an `OrderRequest(...)`
with `reason=` supplied **twice**:
`reason=_FORCED_EXIT_PANIC_REASON.get(intent.signal.strategy_id, "")`
(`kernel/orchestrator.py:4793`) and `reason=reason` (`kernel/orchestrator.py:4795`). Python
rejects this at compile time (`SyntaxError: keyword argument repeated: reason`). Introduced by
the merge commit `dbf401a` ("Merge origin/main into branch — resolve … conflicts in
orchestrator"), which collided with `7704c86` ("Stamp panic-fill reason on forced exits").

Consequences directly relevant to this audit:
- The platform **cannot boot** — `feelies.bootstrap.build_platform` imports the orchestrator.
- **31 / 265 test files** fail at *collection* (every `tests/kernel/*` integration test, paper
  conftest, async-fill-latency test, etc.). The would-be end-to-end perf harness sits behind
  exactly this import, so even if it existed it could not run today.
- It is **not** a performance defect and the mission is explicitly read-only ("Do not implement
  fixes in this pass"), so it is reported, not fixed. The one-line fix is to delete line 4795
  (or merge the two intents into one `reason=`); it should be owned by a correctness pass, and
  the determinism parity suite (§6) re-run afterwards.

The Inv-5 parity hashes themselves are **not** compromised: `tests/determinism/` drives the
components directly (82 tests collect and run) rather than through the orchestrator.

---

## 1. Executive summary — determinism-safe latency wins, highest leverage first

1. **[GUARD/P0] The perf-regression gate guards nothing.** `tests/perf/baselines/v02_baseline.json`
   is `{"schema_version":"1.0.0","hosts":{}}` — **empty** (`v02_baseline.json:1-4`). The only
   perf test, `test_paper_rth_no_regression.py`, `skipif`s when `PERF_HOST_LABEL` is unset and
   otherwise only asserts `tick_processing_p99_s > 0` (`test_paper_rth_no_regression.py:12-21`).
   The whole perf suite runs in **0.06 s and measures no latency**.
2. **[GUARD/P0] The baseline-recording path is dead code.** `record_perf_baseline.py:57-59`
   shells out to `tests/perf/test_phase4_1_no_regression.py::test_phase4_1_decay_overhead_within_budget`
   — a file that **does not exist** in the repo. No host can record a baseline; that is *why*
   the JSON is empty. The acceptance test that is supposed to protect this plumbing
   (`test_perf_baseline_plumbing.py`) only checks the script *imports* and the JSON is
   well-formed — it never runs the script or asserts the referenced test exists
   (`test_perf_baseline_plumbing.py:43-78`).
3. **[GUARD/P1] The ≤5 % decay-weighting budget is unenforced, and the stage-local overhead is
   large.** Measured `CrossSectionalRanker.rank()` decay ON vs OFF: **+38 % (n=10) … +48 %
   (n=50) … +44 % (n=1000)** (off-path, this host). The ≤5 % budget is *end-to-end* (composition
   is boundary-only, so it dilutes), but nothing computes the end-to-end ratio. The +44 % stage
   cost means the budget could silently breach as universe / PORTFOLIO-alpha count grows.
4. **[PERF/P1][DET-SAFE] Each emitted `SensorReading` is allocated twice.** The sensor returns a
   full `SensorReading` (`micro_price.py:104`, every `impl/*.py`), then the registry's `_stamp`
   builds a **second** one re-stamping audit fields (`registry.py:352-401`). Measured: `_stamp`
   = 0.291 s tot / 113 136 calls; the throwaway `SensorReading.__init__` = 0.077 s / 113 136
   calls. Letting sensors return a lightweight `(value, warm, confidence)` and constructing the
   single `SensorReading` in the registry halves `SensorReading` allocations on the hottest path.
5. **[PERF/P1][DET-SAFE] Event dataclasses are not `slots`ed.** `Event` and every subclass are
   `@dataclass(frozen=True, kw_only=True)` with **no `slots=True`** (`core/events.py:30,49,…`),
   so every event carries a `__dict__`. Adding `slots=True` down the hierarchy cuts per-instance
   memory and speeds attribute access on the millions of events/session. Values and ordering are
   unchanged → determinism-safe.
6. **[PERF/P2][DET-SAFE] `SequenceGenerator.next()` takes a lock per event.**
   `identifiers.py:37-41` acquires a `threading.Lock` on every sequence draw; measured lock
   `__exit__` = 0.020 s / 113 276 calls in the sensor path alone, and it fires on **every**
   sequenced event platform-wide. The decision path is single-threaded by Inv-5, so the lock
   guards a scenario Inv-5 already forbids — but see §5 for the live-ingestion-thread caveat
   before any blanket removal.
7. **[PERF/P2][DET-SAFE] `spec.key` is recomputed ~240 k times.** `SensorSpec.key` is a property
   that rebuilds a tuple on every access (`spec.py:150-153`); `registry._on_event` hits it per
   `(event × matching-spec)`. Measured 0.032 s / 239 988 calls. `SensorSpec` is frozen → cache
   the tuple once.
8. **[PERF/P2][DET-SAFE] The registry re-filters all specs by event type every event.**
   `registry._on_event` scans `self._specs` and tests `type(event) not in spec.subscribes_to`
   for all 13 specs per event (`registry.py:273-274`). A pre-built
   `dict[type[Event], tuple[SensorSpec, …]]` (mirroring the aggregator's `_features_by_horizon`
   bucket, `aggregator.py:191-199`) makes dispatch O(matching) and preserves spec order.
9. **[PERF/P1][DET-SAFE] `UniverseSynchronizer` legacy path is O(U²) per boundary.**
   `synchronizer.py:335-371` scans the entire sorted signal cache for **each** of U symbols.
   Production PORTFOLIO alphas take the O(U·K) multi-feeder path (`synchronizer.py:307-320`), so
   severity is bounded — but a per-`(horizon,symbol)` index removes the quadratic for the legacy
   path too. Boundary-only.
10. **[PERF/P2][DET-SAFE] `state["…"]` string-keyed dict access dominates call counts.** Measured
    `dict.get` = 0.111 s across **504 206 calls**; sensors thread all state through
    `dict[str, Any]` (`ofi_ewma.py:111-147`, `realized_vol_30s.py:105-141`). A slotted per-sensor
    state object would cut this, but it is a 16-sensor + protocol change — low priority.
11. **[DET-SAFE, not a win] cvxpy is *not* on the hot path.** `TurnoverOptimizer` uses the
    ECOS/cvxpy path only when `require_solver=True` (default **False**), selected by config not by
    cvxpy availability (`turnover_optimizer.py:109-116,199-218`); the default is an O(universe)
    closed-form rescale, and either path runs at **horizon boundaries only**. No action needed;
    do not "optimize" it onto the per-event path.
12. **[DET-SAFE, latent risk] The orchestrator keeps `perf_counter_ns` inline on the decision
    path; the sensor layer banned it.** `orchestrator.py:2232,2446-2591,3055,5198` time stages
    into `_tick_timings`; the sensor registry explicitly **removed** the same pattern citing
    "A-CLOCK-01 … prohibited in the deterministic dispatch path" (`registry.py:151-155,418-421`).
    Safe today (values land only in non-hashed `MetricEvent`), but it is an inconsistency and a
    latent Inv-10 hazard (§5).
13. **[PERF/P2] `tick_to_decision_latency_ns` and per-stage timers are emitted as bus
    `MetricEvent`s every tick** (`orchestrator.py:3065-3089`), each consuming the main `_seq` and
    a synchronous bus dispatch. Deterministic, but it is per-tick work for off-path observability;
    a dedicated metrics subscriber (the sensor layer's chosen posture) removes it from the tick
    body.
14. **No accidental O(n²) on the per-event path.** Sensors are incremental (Welford/EWMA, event-
    time deques: `realized_vol_30s.py:111-137`, `ofi_ewma.py:127-155`); the ranker, neutralizer,
    sector matcher, and per-leg risk fan-out are all O(universe) or O(universe·small-constant) and
    **boundary-only** (§2). The only quadratic is the synchronizer legacy path (#9).
15. **Determinism posture is strong.** Dedicated per-stream `SequenceGenerator`s isolate every
    hashed stream from `_seq` (`registry.py:104-110`, `aggregator.py:34-39`,
    `horizon_engine.py:54-62`, `synchronizer.py:20-24`); iteration is over sorted tuples with
    `set`/`frozenset` used only for membership (e.g. `cross_sectional.py:593`,
    `synchronizer.py:138-139`). Most proposed wins are pure micro-optimizations that preserve this.

---

## 2. Critical-path cost map

Per-event = runs on **every** `NBBOQuote`/`Trade`. Boundary = runs only when a horizon boundary
is crossed (30 s–30 min). Costs are this-host measurements where a number is given, else
*estimate* from structure. Budgets are from `performance-engineering/SKILL.md` §"Latency Budget".

| Stage (file) | When | Complexity | Measured / est. cost | Hot? | Budget (SKILL) |
|---|---|---|---|---|---|
| M1 log + `bus.publish(quote)` (`orchestrator.py:2317-2328`, `event_bus.py:59-68`) | per-event | O(handlers) | publish 0.124 s / 127 k calls ≈ **1 µs/call** | ⚠ | 100 µs / 500 µs |
| Mark-to-market + HWM (`orchestrator.py:2335-2376`) | per-event | O(1) | Decimal mid each tick — *est. low µs* | ◻ | — |
| M2 regime update (`orchestrator.py:3463-3517`) | per-event | O(states) | *est.* — `posterior()` Bayesian update | ◻ | 50 µs / 200 µs |
| **SENSOR_UPDATE fan-out** (`registry.py:247-351`) | per-event | O(sensors) | `_on_event` 0.350 s tot, 3.045 s cum / 13.7 k | 🔥 | 500 µs / 2 ms |
| → per-sensor `update()` (`sensors/impl/*`) | per-event | O(1) incremental | heaviest `realized_vol_30s` 0.090 s / 12 k ≈ **7.5 µs** | 🔥 | — |
| → `_stamp` 2nd `SensorReading` alloc (`registry.py:352-401`) | per-event | O(1) | **0.291 s / 113 k ≈ 2.6 µs/reading** | 🔥 | — |
| HORIZON_CHECK (`sensors/horizon_scheduler.py:173`) | per-event | O(horizons·symbols) | `on_event` 0.066 s tot / 13.7 k | ⚠ | (part of 200 µs) |
| HORIZON_AGGREGATE buffer fold (`aggregator.py:355-419`) | per-event | O(features/sensor) | **`_on_sensor_reading` 0.368 s / 113 k ≈ 3.3 µs** (top tottime) | 🔥 | 200 µs / 1 ms |
| HORIZON_AGGREGATE snapshot build (`aggregator.py:466-570`) | boundary | O(features) | *est.* — passive mode empty in v0.2 | ◻ | 200 µs / 1 ms |
| SIGNAL_GATE (`horizon_engine.py:323-535`, `regime_gate.py`) | boundary | O(alphas) | *est.* — AST gate eval + `evaluate()` | ◻ | 200 µs / 1 ms |
| CROSS_SECTIONAL sync fan-in (`synchronizer.py:294-396`) | boundary | **O(U²) legacy / O(U·K) multi-feeder** | *est.* — see #9 | ◻ | 1 ms / 5 ms |
| CROSS_SECTIONAL rank (`cross_sectional.py:396-557`) | boundary | O(U·feeders), ≤5 passes cap | **n=300: 429 µs OFF / 629 µs ON** | ◻ | (part of 1 ms) |
| → factor neutralize (`factor_neutralizer.py:172`) | boundary | O(U·F²) `np.linalg.solve` | *est.* — small F | ◻ | — |
| → turnover optimize (`turnover_optimizer.py`) | boundary | closed-form O(U) **default**; ECOS opt-in | *est.* — boundary-only, off hot path | ◻ | — |
| → decision-basis SHA-256 (`engine.py:59-107`) | boundary | O(U) string fold | *est.* | ◻ | — |
| M5 risk `check_signal` (`basic_risk.py:167-229`) | per-signal | O(1) + exposure scan | *est.* — `_tick_timings["risk_check_ns"]` | ⚠ | 100 µs / 500 µs |
| M5 PORTFOLIO `check_sized_intent` per-leg (`sized_intent_orders.py:104-203`) | boundary | O(legs) Decimal | *est.* — boundary-only | ◻ | 200 µs/leg / 1 ms/leg |
| M6 order build (`orchestrator.py:4760-4798`) | per-order | O(1) | *est.* — SHA-256 order_id | ◻ | 500 µs / 2 ms |
| M10 finalize / metrics (`orchestrator.py:3053-3094`) | per-event | O(timers) | 1 HISTOGRAM + N timers on bus + `_seq` | ⚠ | (part of e2e) |

**Whole per-event path (measured, this host):** 13 sensors × 3 symbols → **118 µs / market
event** (8 465 ev/s) uninstrumented; comfortably inside the 500 µs sensor-fan-out target, but it
scales with `sensors × symbols`, and the three 🔥 rows (`_on_sensor_reading`, `_on_event`,
`_stamp`) are ~70 % of that path's tottime.

**cvxpy answer (audit A.3):** heavy but **off the critical path** — opt-in (`require_solver`,
default off) and amortized at horizon boundaries only (`turnover_optimizer.py:199-218`).

---

## 3. Allocation & GC audit

**Per-event allocations (the 🔥 path), measured over 13.7 k market events → 113 k readings:**

| Allocation | Site | Count | Cost | Determinism-safe remedy |
|---|---|---|---|---|
| Sensor-side `SensorReading` (thrown away by `_stamp`) | `sensors/impl/*` e.g. `micro_price.py:104-113` | 113 136 | `__init__` 0.077 s | Return a small value tuple; build one `SensorReading` in registry — **[DET-SAFE]** |
| Registry-side `SensorReading` (the kept one) | `registry.py:388-401` | 113 136 | `_stamp` 0.291 s | Unavoidable (immutable event) — but it should be the *only* one |
| `correlation_id` f-string | `identifiers.py:9-15` via `_stamp` | 113 276 | 0.071 s | Inherent to provenance; leave |
| Sequence tuple `spec.key` | `spec.py:150-153` | 239 988 | 0.032 s | Cache on frozen spec — **[DET-SAFE]** |
| `MetricEvent` per reading (if collector wired) | `registry.py:439-451` | 1/reading | — | Already on a dedicated seq; gate via `emit_reading_metrics` (exists) |
| Per-tick `MetricEvent`(s) + `_seq` draw | `orchestrator.py:3065-3089` | ≥1/tick | bus dispatch | Move to off-path subscriber — **[DET-SAFE]** |
| `buf_snapshot = list(self._signal_buffer)` | `orchestrator.py:2443` | 1/tick w/ signals | O(buffered) tiny | Leave |

**Large transient structures rebuilt every event:** none on the per-event path. Sensor windows
are **bounded event-time deques** with O(1) amortized append/popleft
(`realized_vol_30s.py:117-130`, `ofi_ewma.py:151-155`; measured deque append 0.050 s / 218 k,
popleft 0.016 s / 69 k). The aggregator's per-`(symbol,sensor)` ring buffers are likewise event-
time bounded to `2·max(horizon)` (`aggregator.py:245-247,374-377`). Boundary structures
(snapshot dicts, ranker weight maps, per-leg order lists) are O(universe) and rebuilt only at
boundaries.

**GC pause risk:** low on the per-event path — the dominant objects (`SensorReading`,
`MetricEvent`) are short-lived and acyclic (frozen dataclasses, no back-references). The
long-lived containers (`_buffers`, `_feature_state`, `_signal_cache`, `_regime_cache`) are plain
dicts/deques keyed by tuples — no reference cycles. Note `backtest_runner.py` disables GC for
replay (`gc.disable()`, per SKILL §"Memory Management"); the orchestrator tick loop does **not**
toggle GC — fine, because allocation is modest, but the slots/double-alloc wins (#4,#5) directly
reduce the allocation rate the collector has to keep up with under live load.

---

## 4. Data-structure audit

1. **Hot-path lookups use the right structures.** Sensor/aggregator/synchronizer state is dict-
   keyed by tuples; the aggregator pre-buckets features by horizon so passive horizons cost O(1)
   not O(F) (`aggregator.py:191-199,481`), and pre-builds a `sensor_id → features` reverse index
   so a reading dispatches to consumers without scanning all features (`aggregator.py:270-273`).
   These are exemplary; the one place that still *scans* is `registry._on_event` (#8) and the
   `synchronizer` legacy path (#9).
2. **`Decimal` vs `float` is correctly partitioned.** `Decimal` is confined to **money**: NBBO
   prices (`events.py:66-67`), mark-to-market (`orchestrator.py:2335`), and the USD→shares /
   cent-rounding in order/intent construction (`sized_intent_orders.py:117-121`,
   `turnover_optimizer.py:65-74`) — all PnL-fidelity surfaces, all off the per-event sensor path.
   The numeric hot loops (sensors, ranker, neutralizer) are **pure `float`** by design
   (`cross_sectional.py:38-45,599-601`). No `Decimal` misuse found on the per-event path; the
   one per-tick `Decimal` is the mark mid (`orchestrator.py:2335`), which is required.
3. **No ordering-sensitive "fast" structures on the decision path.** Every place that *could*
   have used a `set`/unordered map for speed instead iterates a **sorted tuple** and uses the set
   only for membership: ranker active-set (`cross_sectional.py:593` iterates `universe`, set is
   membership-only), synchronizer universe (`synchronizer.py:138-139`), sensor specs in
   registration/topological order (`registry.py:247-254`). Swapping any of these to raw set
   iteration would be **[DET-FORBIDDEN]** (Inv-5 ordering). They are already correct.
4. **`event_bus` dispatch** is a `defaultdict(list)` keyed by exact `type(event)`
   (`event_bus.py:36,65`) — O(1) handler lookup, registration-order delivery. `.get(type,[])`
   allocates a throwaway empty list only for event types with no subscribers (minor). Correct and
   determinism-preserving; do **not** replace with anything reordering.

---

## 5. Determinism-safety classification (this section gates all others)

> **Rule:** determinism beats speed, always. Anything that introduces parallelism, ordering
> change, or wall-clock into the decision path is **forbidden**, not "P0 with caveats."

**Standing facts established by this audit:**

- **No parallelism on the decision path.** `grep` across `kernel,sensors,features,signals,
  composition,risk,bus` finds **zero** `threading`/`asyncio`/`multiprocessing`/`concurrent` use
  on the tick path. The only concurrency in the tree is provably **off-path**: batch ETL
  (`ingestion/massive_ingestor.py:23-26,352` — `ThreadPoolExecutor(max_workers=2)`, populates
  `EventLog` *before* replay), the live WS feed (`ingestion/massive_ws.py:19-23,148` — asyncio +
  a reader thread, normalizes *before* the bus), and broker socket I/O
  (`broker/ib/connection.py:154-159`). These feed normalized events into the **synchronous** bus;
  they are not a latent Inv-5 risk.
- **Wall-clock on the decision path is confined to the timing harness.** `perf_counter_ns` appears
  only in the orchestrator timers (`orchestrator.py:2232,2446-2448,2589-2591,3055,5198-5212`).
  Their values land **only** in `MetricEvent.value`, and `MetricEvent` is **excluded from all 12
  locked parity hashes** (`tests/determinism/parity_manifest.py:84-122` — no `MetricEvent`
  entry). The *count* of metric emissions is a deterministic function of inputs, and parity
  streams draw from dedicated generators isolated from `_seq`. So today these reads are
  determinism-safe **by isolation invariant**, not by being off-path.

| Proposed change | Classification | Rationale |
|---|---|---|
| Single `SensorReading` alloc (sensor returns value, registry stamps) (#4) | **[DET-SAFE]** | Identical field values & emission order; only removes a throwaway object |
| `slots=True` on event dataclasses (#5) | **[DET-SAFE]** | Layout-only; values, ordering, hashing unchanged |
| Cache `spec.key` on frozen spec (#7) | **[DET-SAFE]** | Same tuple value, computed once |
| Pre-bucket specs by event type in registry (#8) | **[DET-SAFE]** | Preserve spec order within bucket → byte-identical dispatch |
| Per-`(horizon,symbol)` index for synchronizer legacy path (#9) | **[DET-SAFE]** *iff* it preserves "smallest `strategy_id` passing the causal/stale/fresh guards" selection (`synchronizer.py:352-370`) | Same selection, no O(U²) scan |
| Move per-stage timing to an off-path metrics subscriber (#12,#13) | **[DET-SAFE]** | Removes a latent Inv-10 hazard; aligns with sensor-layer A-CLOCK-01 |
| Slotted per-sensor state object (#10) | **[DET-SAFE]** | Same values; protocol-wide change, low priority |
| Lock-free `SequenceGenerator` for decision-thread generators (#6) | **[DET-SAFE] with caveat** | Output is identical single-threaded; **but** confirm no generator is shared with the live WS normalizer thread before removing the lock — keep the locked variant for any cross-thread producer |
| Parallelize sensor fan-out / symbols within a tick | **[DET-FORBIDDEN]** | Inv-5 §4: within-tick pipeline is strictly sequential; reordering breaks every parity hash |
| `set`/unordered iteration in ranker/synchronizer/registry (§4.3) | **[DET-FORBIDDEN]** | Emission order is hashed (Inv-5) |
| Route any `perf_counter`/wall value into control flow or a hashed field | **[DET-FORBIDDEN]** | Inv-10; would make replay wall-clock-dependent |
| cvxpy/ECOS as default optimizer path | **[DET-FORBIDDEN as default]** | Solver output can drift across BLAS/arch; the code already pins ECOS tolerances *and* gates the path on config not availability precisely to preserve Inv-5/Inv-9 (`turnover_optimizer.py:51-59,109-116`) |

---

## 6. Perf-baseline audit

**What is *claimed* to be guarded** (`performance-engineering/SKILL.md` §"Regression Prevention"):
(a) paper-RTH throughput ≤12 % vs v0.2; (b) Phase-4.1 decay-weighting ≤5 % wall-clock vs decay-OFF.
Both are described in the skill as "policy target … comparator gate planned." This audit confirms
**neither is enforced, and the recording path is broken.**

1. **What is actually pinned: nothing.** `tests/perf/baselines/v02_baseline.json` is
   `{"schema_version":"1.0.0","hosts":{}}` (`v02_baseline.json:1-4`). Zero hosts, zero numbers.
2. **Drift detection: none.** The lone gate `test_paper_rth_no_regression.py` (a) skips unless
   `PERF_HOST_LABEL` is set (`:12-15`), (b) skips again if the host has no baseline blob
   (`:18-19`), (c) otherwise asserts only `tick_processing_p99_s > 0` and `drain_p99_s >= 0`
   (`:20-21`). It never compares against a stored number, so it cannot detect drift. There is **no
   12 % comparator** anywhere.
3. **The ≤5 % decay budget gate does not exist.** `record_perf_baseline.py:57-59` runs
   `tests/perf/test_phase4_1_no_regression.py::test_phase4_1_decay_overhead_within_budget`, which
   is **absent** from the tree (`find tests -name 'test_phase4_1*'` → nothing). So: the recorder
   errors → no baseline is ever written → the JSON stays empty → the (skipping) gate never fires.
   A fully circular dead guard.
4. **The acceptance "plumbing" test gives false assurance.**
   `test_perf_baseline_plumbing.py` asserts the recorder *imports*, the JSON is well-formed, and
   the helper returns `None` when the label is unset (`:43-114`). It **does not** run the
   recorder, exercise the comparator, or assert the referenced harness exists — so the plumbing
   "rots silently" exactly as the docstring fears it won't.
5. **Host-specificity design is sound, but moot.** The intended model is one baseline per
   `host_label` so a laptop number does not gate a CI runner (`record_perf_baseline.py:29-39`,
   `_pinned_baseline.py:69-122`). That keying is correct and would be meaningful — there is just
   nothing to key.
6. **The ≤5 % budget, measured.** Because no test exists, this audit measured the stage directly:
   `CrossSectionalRanker.rank()` decay ON vs OFF (this host, 2 000 iters):

   | universe | decay OFF | decay ON | overhead |
   |---|---|---|---|
   | 10 | 19.5 µs | 26.8 µs | **+37.6 %** |
   | 50 | 73.1 µs | 108.1 µs | **+47.8 %** |
   | 100 | 153.3 µs | 213.8 µs | **+39.4 %** |
   | 300 | 429.0 µs | 629.2 µs | **+46.7 %** |
   | 1000 | 1448.3 µs | 2089.3 µs | **+44.3 %** |

   The extra `math.exp(-Δt/hl)` + float ops per active symbol (`cross_sectional.py:293-298,
   438-443,513-518`) roughly **doubles the inner-loop cost**. This is *stage-local*, not
   end-to-end: composition fires only at boundaries, so when amortized over the per-event sensor
   stream the end-to-end figure is plausibly under 5 %. **The point is that nobody measures the
   end-to-end ratio**, so the budget could be breached (bigger universe, more PORTFOLIO alphas,
   shorter horizons) with no signal. The recorded `max_overhead_factor: 1.05` in
   `record_perf_baseline.py:125` is the right intent — it is just never asserted.

**Verdict:** the perf baselines are not "brittle," they are **absent**; the regression guard is a
no-op. This is a P0 *guard* gap (not a P0 nondeterminism, of which there is none).

---

## 7. Test-gap matrix + proposed benchmarks

| Hot-path stage | Existing perf coverage | Gate? | Gap |
|---|---|---|---|
| Per-sensor `update()` | `tests/sensors/test_sensor_latency_budget.py` | none (CI_BENCHMARK opt-in, prints p50/p99, asserts only `emitted>0`, `:170-201`) | informational; per-sensor, not integrated |
| Registry fan-out + `_stamp` | — | — | **no coverage** (this is a 🔥 row) |
| Aggregator `_on_sensor_reading` fold | — | — | **no coverage** (top tottime) |
| SIGNAL_GATE (engine + regime gate) | — | — | **no coverage** |
| CROSS_SECTIONAL sync + rank + neutralize + optimize | intended `test_phase4_1_no_regression.py` | **file absent** | **no coverage**; ≤5 % budget unmeasured |
| Risk `check_signal` / `check_sized_intent` | — | — | **no coverage** |
| End-to-end tick latency (M0→M10) | `test_paper_rth_no_regression.py` | skips / no comparator | **no real coverage** |

**Proposed minimal benchmarks (specs only — determinism-safe to add):**

- **B1 — restore the decay budget gate.** Add `tests/perf/test_phase4_1_no_regression.py::
  test_phase4_1_decay_overhead_within_budget` that ranks a fixed N-symbol `CrossSectionalContext`
  decay-OFF vs decay-ON (best-of-k to suppress noise), prints the `PHASE4_1_PERF_SUMMARY
  baseline_best=… extended_best=…` line `record_perf_baseline.py:62-67` already parses, and —
  when a pinned baseline exists for the host — asserts `extended_best ≤ 1.05 × baseline_best`.
  This closes the circular dead guard (§6.3) with one file the recorder already expects.
- **B2 — integrated per-event throughput micro-bench.** Generalize this audit's component
  profiler (`scratchpad/profile_components.py`) into `tests/perf/test_sensor_pipeline_throughput.py`
  (CI_BENCHMARK-gated): drive the real registry + scheduler + aggregator over a fixed event log,
  emit `µs/market-event`, and gate against a per-host pin. Covers the three 🔥 rows that have zero
  coverage today.
- **B3 — make the plumbing test prove the harness exists.** Extend
  `test_perf_baseline_plumbing.py` to assert `record_perf_baseline._PHASE4_1_TEST`'s node id
  *resolves to a collectable test* (`pytest --collect-only` of that id returns 1 item). This
  would have caught §6.3 at commit time.
- **B4 — end-to-end tick-latency gate** (after the §0 blocker is fixed): assert p99
  `tick_to_decision_latency_ns` from a fixed replay stays within a per-host pin — the metric is
  already emitted (`orchestrator.py:3065-3075`), only the comparator is missing.

---

## 8. Prioritized backlog

Effort: **S** ≤ ½-day · **M** ~1–2 days · **L** > 2 days. Every item is determinism-safe unless
marked; P0 here is "guard that guards nothing / blocker," **not** nondeterminism (none found).

### P0 — blockers & dead guards

| # | Item | `file:line` | Effort | Det. |
|---|---|---|---|---|
| 0 | **[BLOCKER]** delete the duplicate `reason=` kwarg so the orchestrator compiles & 31 tests collect (out of scope to fix here; flag to a correctness pass, then re-run `tests/determinism/`) | `orchestrator.py:4793,4795` | S | [DET-SAFE] (restores compile) |
| 1 | Restore the decay-budget harness `test_phase4_1_no_regression.py` (B1) so the recorder works and the ≤5 % budget is actually asserted | `record_perf_baseline.py:57-59` (dangling ref); new `tests/perf/` file | M | [DET-SAFE] |
| 2 | Make `test_perf_baseline_plumbing` assert the referenced harness is collectable, not just importable (B3) | `test_perf_baseline_plumbing.py:43-78` | S | [DET-SAFE] |
| 3 | Either wire a real comparator into `test_paper_rth_no_regression` or record at least one host baseline, so the perf JSON stops being empty | `test_paper_rth_no_regression.py:16-21`, `v02_baseline.json` | M | [DET-SAFE] |

### P1 — hot-path allocations / O(n²) / unenforced budgets

| # | Item | `file:line` | Effort | Det. |
|---|---|---|---|---|
| 4 | Eliminate the double `SensorReading` allocation — sensors return `(value, warm, confidence)`, registry builds the one event | `registry.py:352-401` + `sensors/protocol.py` + 16× `impl/*` | M | [DET-SAFE] |
| 5 | Add `slots=True` to `Event` and subclasses (frozen-slots + inheritance; verify no field clashes) | `core/events.py:30,49,…` | M | [DET-SAFE] |
| 6 | Index `synchronizer` legacy path by `(horizon,symbol)` to kill the O(U²) scan (preserve smallest-`strategy_id` selection) | `synchronizer.py:335-371` | M | [DET-SAFE]* |
| 7 | Add the integrated per-event throughput micro-bench + per-host gate (B2) | new `tests/perf/` file | M | [DET-SAFE] |

\* conditional on preserving the documented selection order.

### P2 — micro-opts, observability, consistency (determinism-safe)

| # | Item | `file:line` | Effort | Det. |
|---|---|---|---|---|
| 8 | Cache `spec.key` on the frozen `SensorSpec` (240 k recomputes) | `spec.py:150-153` | S | [DET-SAFE] |
| 9 | Pre-bucket specs by event type in the registry (drop the per-event type filter over all specs) | `registry.py:273-274` | S | [DET-SAFE] |
| 10 | Move per-stage timers + `tick_to_decision_latency_ns` to an off-path metrics subscriber; align orchestrator with sensor-layer A-CLOCK-01 | `orchestrator.py:2446-2591,3065-3089` | M | [DET-SAFE] (removes latent Inv-10 hazard) |
| 11 | Provide a lock-free `SequenceGenerator` variant for decision-thread-confined generators (keep locked default for cross-thread producers — verify WS normalizer) | `identifiers.py:28-41` | S | [DET-SAFE] with caveat (§5) |
| 12 | (Optional, L) slotted per-sensor state object to cut the 504 k `dict.get` calls | `sensors/protocol.py` + `impl/*` | L | [DET-SAFE] |
| 13 | End-to-end tick-latency gate once §0 is fixed (B4) | `orchestrator.py:3065-3075` + new test | M | [DET-SAFE] |

---

### Appendix — measurement provenance

- Off-path profilers (read-only, no production code modified):
  `scratchpad/profile_components.py` (13-sensor registry + scheduler + aggregator, 3 symbols,
  13 713 market events → 113 136 readings) and `scratchpad/profile_ranker.py`
  (`CrossSectionalRanker` decay ON/OFF). Host: CPython 3.12.3, Linux, single run, cProfile for
  per-function tottime + an uninstrumented wall-clock pass for µs/event.
- The orchestrator-level profiler (`scratchpad/profile_hotpath.py`) could **not** run due to the
  §0 `SyntaxError`; component-level numbers are used instead and are the dominant per-event cost.
- All absolute µs are host-specific and for relative ranking only; they are **not** a budget
  certification (which requires a pinned per-host baseline — see §6).
