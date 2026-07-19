# Performance & Latency-Budget Audit — 2026-07-02

**Scope:** feelies tick-to-trade hot path (SENSOR → SIGNAL → PORTFOLIO), allocation/GC
behavior, data-structure choices, and the pinned perf baselines — subject to Inv-5
(deterministic replay) as the binding, non-negotiable constraint. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`; no production code, baselines, configs, or
ledgers were modified in this audit.

**Method:** direct reading of `src/feelies/kernel/orchestrator.py` (6,854 lines),
`kernel/micro.py`, `bus/event_bus.py`, `core/state_machine.py`, `core/identifiers.py`,
`core/events.py`, `services/regime_engine.py`, `features/aggregator.py`,
`signals/horizon_engine.py`, `monitoring/in_memory.py`, `bootstrap.py`,
`harness/backtest_runner.py`, `sensors/registry.py`; three parallel deep-reads of
`sensors/impl/*.py` (18 files), `composition/*.py` + `risk/*.py` (14 files), and
`tests/perf/**` + `tests/acceptance/test_perf_baseline_plumbing.py` +
`scripts/record_*_perf_baseline.py`, each cross-checked against source; live execution
of `uv run pytest tests/perf/ -q`, `tests/acceptance/test_perf_baseline_plumbing.py -q`,
`tests/sensors/test_sensor_latency_budget.py` (with and without `CI_BENCHMARK=1`), and
`tests/perf/test_phase4_1_no_regression.py` (twice, for run-to-run variance). One prior
first-party measurement (`docs/audits/performance_audit_2026-06-25.md`, cProfile-based)
is cited where it independently corroborates a finding — labeled explicitly as
"measured, prior audit" throughout, not re-run in this pass.

**Environment caveat:** every test invocation in this pass printed
`PYTHONHASHSEED=None (expected '0')` (`conftest.py:34`) — the platform's own contractual
pin (`docs/three_layer_architecture.md §12.5`) was not active in this container. No
finding below depends on hash-seed-sensitive iteration (verified per-finding in §5), but
none of the timing numbers in this report should be treated as reproducible against a
`PYTHONHASHSEED=0` CI run without re-measuring.

---

## 1. Executive summary

1. **No parallelism or nondeterminism found on the decision path.** Repository-wide grep
   for `threading|asyncio|multiprocessing|Lock|ProcessPoolExecutor|ThreadPoolExecutor`
   across `kernel/`, `bus/`, `risk/`, `composition/`, `sensors/` returns zero hits except
   `SequenceGenerator`'s single `threading.Lock` (item 9 below), which exists for
   live/paper thread-safety, not decision-path concurrency. This is the binding
   constraint (Inv-5) and it holds today — see §5.
2. **Two independent O(n²)-in-universe-size hot spots at horizon boundaries**, same root
   cause (an un-indexed cache scanned in full per lookup instead of keyed by symbol):
   `HorizonSignalEngine._build_bindings` (`signals/horizon_engine.py:754-758`) and
   `UniverseSynchronizer._emit_context`'s legacy branch
   (`composition/synchronizer.py:351-362`). Both are determinism-safe to fix with a
   symbol-keyed index (§5, §8 P1-1/P1-2).
3. **Highest call-frequency finding:** `BasicRiskEngine.check_signal`/`check_order` each
   run 2–5 unconditional O(N) full-position-store scans (N = tracked positions) on
   *every* signal tick — not boundary-gated like items 2 above, so this is plausibly the
   single highest-value target by total time spent (`risk/basic_risk.py:727-728,
   681, 505-511, 581-593`).
4. `RiskEngine.check_sized_intent` → `build_sized_intent_orders` calls the same
   O(N)-scanning `check_order` once per leg → **O(L×N) per PORTFOLIO intent**
   (`risk/sized_intent_orders.py:110-147`) — the concrete instantiation of "per-leg risk
   check that scans all positions."
5. `StateMachine._history` (shared framework used by macro/micro/order/risk-escalation/
   data-integrity SMs) **grows unbounded for the life of the process** — confirmed by
   repo-wide grep, never cleared anywhere (`core/state_machine.py:87,175,207`). Only the
   alpha-lifecycle SM's history is ever read back (`alpha/lifecycle.py:295,599`); the
   other five accumulate forever for no downstream consumer.
6. `InMemoryMetricCollector._events` unbounded growth is **already fixed for BACKTEST**
   (`bootstrap.py:565-566`, gated on `config.mode == OperatingMode.BACKTEST`) but **not
   for PAPER/LIVE**, where the class default (`_store_raw_events = True`,
   `monitoring/in_memory.py:69`) stands — the team's own comment cites "~11M entries →
   91 MB buffer" for long runs (`monitoring/in_memory.py:66-68`).
7. The entire `core/events.py` event catalog (~20+ frozen dataclasses, including the
   highest-frequency `NBBOQuote`/`Trade`/`MetricEvent`/`RiskVerdict`) **lacks
   `slots=True`**, inconsistent with every hand-written framework class in the same
   codebase (`EventBus`, `StateMachine`, `SequenceGenerator`, `SensorRegistry`,
   `HorizonAggregator`, `HorizonSignalEngine` all declare `__slots__` explicitly). This
   is the single best effort/impact ratio in the whole audit — S effort, zero
   determinism risk, touches every hot-path allocation.
8. Sensor dispatch has a **measured** (prior audit, 2026-06-25), real double-allocation:
   every `SensorReading` is built once inside the sensor's own `update()`, then
   discarded and rebuilt field-by-field by the registry's `_stamp()`
   (`sensors/registry.py:19, 350-399`) — 0.077s / 113,136 calls for the throwaway
   instance alone.
9. `SequenceGenerator.next()` acquires a real `threading.Lock` on every event/metric/
   signal/reading emission platform-wide (`core/identifiers.py:44-50`) — already a known,
   documented tradeoff (`.cursor/skills/performance-engineering/SKILL.md:121-123`) with a
   **measured** cost (prior audit: 0.020s / 113,276 calls in the sensor path alone).
   Determinism-safe to drop *only* for the single-threaded BACKTEST path.
10. **cvxpy is OFF by default** (`composition_optimizer_mode: str = "closed_form"`,
    `platform_config.py:592,1648`) — confirmed the composition solver is not on the
    critical path unless an operator explicitly opts into `"ecos"`
    (`bootstrap.py:2021`). When it is enabled, the CVXPY `Problem` is rebuilt from
    scratch every boundary with no `cp.Parameter` reuse (`composition/
    turnover_optimizer.py:316-329`).
11. `FactorNeutralizer.neutralize()` rebuilds a static loadings matrix and re-solves the
    Bᵀ B normal equations from scratch on every call, up to 5×/boundary (once per
    mechanism sleeve), despite the loadings being constant intraday
    (`composition/factor_neutralizer.py:159-191`, docstring at `:6-8` confirms staticness).
12. **Perf-baseline infrastructure is well-built but empty.** `v02_baseline.json` is
    `{"schema_version":"1.0.0","hosts":{}}` — zero hosts recorded, unchanged since at
    least the 2026-06-25 audit — so every `PERF_HOST_LABEL`-gated comparison in both
    perf test files is currently inert by omission (§6, P0).
13. The one gate that *does* compare against a live numeric threshold
    (`test_phase4_1_no_regression.py`) hard-fails at **25%** overhead, 5× looser than the
    5% figure quoted as policy everywhere else in the docs; the 5% line is only a
    non-failing print (`_POLICY_BUDGET_FACTOR = 1.05`, `:88`, vs. `_HARD_GATE_FACTOR =
    1.25`, `:93`). Live-measured runs during this audit landed at **3.09%** and **4.91%**
    — the second run is 0.09 points from silently crossing the un-enforced policy line.
14. `test_sensor_latency_budget.py`'s own `capsys.readouterr()` call
    (`tests/sensors/test_sensor_latency_budget.py:199`) unconditionally swallows the
    p50/p99/mean latency table it prints — confirmed empirically in three invocation
    modes (`-q`, `-q -s`, `-v -s`) with `CI_BENCHMARK=1` set. The one place per-sensor
    latency could be observed today is provably invisible.
15. Only **2 of ~10** M0→M10 micro-state segments have a dedicated timer
    (`signal_evaluate_ns`, `risk_check_ns` in `orchestrator.py:2455-2457, 2606-2608`) —
    sensor fan-out, horizon aggregation, composition, and order construction all fold
    into the single end-to-end `tick_to_decision_latency_ns` bucket with no way to
    attribute cost to a specific stage (§7).

---

## 2. Critical-path cost map

Stages follow the M0–M10 backbone plus Phase-2/3/4 sub-states
(`.cursor/skills/performance-engineering/SKILL.md`, `kernel/micro.py`). "Cost" is
measured where a number exists (labeled), otherwise a complexity-derived estimate
(labeled). N = tracked positions in `PositionStore`; U = universe size; S = registered
sensors (18 implemented, **15** registered in the reference `platform.yaml` as of this
audit — see note below); A = registered SIGNAL alphas; F = mechanism families (≤5,
`TrendMechanism` enum); L = legs in a `SizedPositionIntent`.

| Stage | Complexity | Cost | Hot? |
|---|---|---|---|
| M0→M1 event receipt + log + publish | O(1) | Budget 100μs/500μs; no dedicated timer — folds into end-to-end | Every tick |
| M1→M2 regime posterior (`RegimeEngine.posterior`) | O(1) — idempotent per (symbol,seq) cache hit; else O(n_states≤3) closed-form Bayes update | Budget 50μs/200μs; no dedicated timer; code confirms O(1)-class cost (`services/regime_engine.py:498-555`) | Every tick |
| SENSOR_UPDATE (`SensorRegistry._on_event` fan-out) | O(S) unconditional per-spec scan (`sensors/registry.py:273-274`, no type-bucketing), each sensor O(1) amortized (deque + incremental Welford/EWMA/Kahan — 17 of 18 sensors) | Budget 500μs/2ms; **measured, prior audit:** `_stamp` 0.291s/113,136 calls (≈2.6μs/call, includes double-alloc waste at item 8); lock overhead 0.020s/113,276 calls | Every tick (sensors configured) |
| HORIZON_CHECK + HORIZON_AGGREGATE (`HorizonAggregator`) | O(F_h) — bucketed by horizon, reverse-indexed by sensor (`features/aggregator.py:191-199, 261-273`); fallback staleness scan is O(all buffers) but boundary+cache-miss only (`:581-600`) | Budget 200μs/1ms; no dedicated timer | Boundary only |
| SIGNAL_GATE (`HorizonSignalEngine`) | O(A_h) linear scan over registered signals per snapshot, not horizon-bucketed (`signals/horizon_engine.py:338-345`); **`_build_bindings` is O(U×S) per dispatch** (`:754-758`) → **O(U²×A×S) aggregate per boundary** | Budget 200μs/1ms; not measured | Boundary only — **O(n²) risk** |
| CROSS_SECTIONAL (`UniverseSynchronizer` + `CompositionEngine`) | Legacy branch **O(U×\|signal_cache\|) ≈ O(U²)** (`composition/synchronizer.py:351-362`, default path — active whenever no PORTFOLIO alpha declares `depends_on_signals`); multi-feeder branch O(U×K×H), K/H deployment-bounded; sleeve ranking/capping O(F×U), F≤5; cvxpy off by default | Budget 1ms/5ms; not measured | Boundary only — **O(n²) risk on legacy path** |
| M4 pre-M5 (`PositionSizer` + `IntentTranslator`) | O(1) | Budget 50μs/200μs; no dedicated timer | Every tick w/ signal |
| M4→M5 risk `check_signal` (per-symbol) | **O(N)**, 2 unconditional full-position-store scans (`risk/basic_risk.py:727-728`) | Budget 100μs/500μs; **timed** (`risk_check_ns`, `orchestrator.py:2606-2608`) but not broken out by scan count | Every tick w/ signal — **O(N) growth risk** |
| CROSS_SECTIONAL→M5 risk `check_sized_intent` (per-leg) | **O(L×N)** — `check_order` called once per leg (`risk/sized_intent_orders.py:110-147`) | Budget 200μs/1ms/leg; no dedicated timer | Boundary only (PORTFOLIO) — **O(n²)-shaped** |
| M5→M7 order construction + `check_order` | **O(N)**, up to 5 unconditional scans w/ PDT+buying-power gates wired (`risk/basic_risk.py:265,274,305,313` call chain) | Budget 500μs/2ms; no dedicated timer | Every tick w/ order |
| M7→M9 submission + ack | Network-bound (live) / instant (backtest) | n/a in backtest | Every order |
| M10 finalize + metrics | O(1) per metric; 1–4 `MetricEvent` allocations/tick, each through `SequenceGenerator.next()` (locked) and `EventBus.publish` | Not separately measured | Every tick |
| **End-to-end (M0→M10)** | — | Budget <3ms (non-boundary) / <8ms (boundary+PORTFOLIO); hard ceiling <10ms/<25ms; **measured via `tick_to_decision_latency_ns` HISTOGRAM at M10**, not re-measured in this pass | Every tick |

**Sensor-count note:** `.cursor/skills/performance-engineering/SKILL.md` states "16
sensors ship in v0.3; 13 registered in the reference `platform.yaml`." Direct
verification (`grep -c sensor_id: platform.yaml`, cross-checked independently by two
research passes in this audit) finds **18** implemented (`src/feelies/sensors/impl/*.py`)
and **15** registered (`platform.yaml:254,269,280,291,316,327,341,357,388,398,411,420,
433,444,457`); `snr_drift_diffusion`, `structural_break_score`, `vpin_50bucket` are
implemented but not in the reference config. The skill doc has drifted from the repo —
informational, not a defect (see §6 for the "shipped vs not-shipped" treatment applied
consistently in this audit).

---

## 3. Allocation & GC audit

**Per-tick allocations (confirmed by direct reading, `orchestrator.py:2236-3112`):**
- `mid = (quote.bid + quote.ask) / Decimal("2")` (`:2344`) constructs a fresh `Decimal("2")`
  literal every tick.
- `buf_snapshot = list(self._signal_buffer)` (`:2452`) — new list every tick, plus
  conditional `fresh`/`stale` lists (`:2263-2264`) when the signal buffer is non-empty.
- `_finalize_tick` (`:3070-3112`) constructs 1 `MetricEvent` unconditionally
  (`tick_to_decision_latency_ns`) plus one more per `_tick_timings` entry (currently up
  to 2: `signal_evaluate_ns`, `risk_check_ns`) — each a fresh frozen-dataclass instance,
  each dispatched through `EventBus.publish` (dict-get + list-iterate,
  `bus/event_bus.py:59-68`) and a locked `SequenceGenerator.next()` call. This is
  structurally required by Inv-13 (no silent transitions / full provenance) — the
  *event emission* is not a candidate for removal (see §5); the *allocation pattern*
  (missing `slots=True`) is.
- Every `StateMachine.transition()` call (5–15 per tick depending on branch taken)
  constructs a `TransitionRecord` (`core/state_machine.py:162-170`), appends it to
  `self._history` forever (`:175`), and fires registered callbacks before committing.
  The bus-side `StateTransition` publication this feeds is mandated by Inv-13; the
  unbounded **in-process retention** in `_history` is not (see finding P1-5, §8).

**Unbounded growth patterns (two, same shape, different mitigation status):**

| Structure | Location | Growth driver | Mitigated? |
|---|---|---|---|
| `StateMachine._history: list[TransitionRecord]` | `core/state_machine.py:87,175,207` | Every `.transition()`/`.reset()` call, all 6 SM instances (macro, micro, order-per-order, risk-escalation, data-integrity, alpha-lifecycle) | **No**, any mode — grep-confirmed zero `.clear()` calls anywhere in `src/` |
| `InMemoryMetricCollector._events: list[MetricEvent]` | `monitoring/in_memory.py:63,71-73` | Every `MetricCollector.record()` call | **Yes for BACKTEST** (`bootstrap.py:565-566`); **no for PAPER/LIVE** (class default `True`, `in_memory.py:69`) |

The micro SM is the dominant driver for the first structure — it alone emits 5–10
`TransitionRecord`s per tick with zero downstream reader (confirmed: only
`alpha/lifecycle.py:295,599` ever calls `.history` anywhere in `src/`, and that SM is a
different instance from macro/micro/order/risk-escalation/data-integrity). For a
multi-million-tick backtest day this is a real, currently-uncapped memory-growth vector,
directly analogous to the `_events` pattern the team already partially fixed — the fix
was applied to one instance of the pattern but not the structurally-identical one in the
shared `StateMachine` framework.

**Measured sensor-path allocations (prior audit, 2026-06-25, cited by the sensor
research pass, not re-run in this session):**
- `_stamp()` double-allocates every `SensorReading` (sensor's own throwaway instance +
  registry's canonical instance): 0.291s total / 113,136 calls; the throwaway alone
  costs 0.077s / 113,136 calls (`sensors/registry.py:19` docstring self-acknowledges
  this: *"SensorReading is re-allocated once per emission (H5 / audit)"*).
- `spec.key` is a `@property` rebuilding a 2-tuple on every access
  (`sensors/spec.py:150-153`), hit twice per emission (`sensors/registry.py:294,385`):
  0.032s / 239,988 calls.
- `SequenceGenerator` lock `__exit__`: 0.020s / 113,276 calls in the sensor path alone.

**GC handling:** `harness/backtest_runner.py:745-788` disables GC for the full replay
(`gc.freeze()` → `gc.disable()` → `run_backtest()` under `try`/`finally` → `gc.enable()`
→ `gc.unfreeze()` → `gc.collect()`), with the stated rationale that per-tick allocations
are "short-lived and bounded" and that incremental collection "causes multi-hundred-ms
gen2 sweeps deep into the replay" (`:747-751`). This is well-engineered — the
`try/finally` guarantees re-enable even on exception, and `gc.freeze()` correctly
excludes pre-replay objects from the final sweep. **This GC handling is BACKTEST-only**;
the orchestrator's own tick loop (used by PAPER/LIVE) does not toggle GC, confirmed by
grep (`import gc|gc\.disable|gc\.enable` finds zero hits outside `harness/`).

**Composition-layer per-boundary allocations** (all O(U), all rebuilt fresh every
boundary — not necessarily wasteful given boundary cadence, but real): `cross_sectional.py`'s
`_standardize` (`:595-596,600`) and `_gather_raw_by_mech` (per-symbol `local_raw`/
`local_decay` dicts, `:355-356`), `engine.py`'s `disclosed`/`combined`/`current_positions`
dicts (`:260,414,425`), `synchronizer.py`'s `snapshots`/`signals_by_strategy`/`signals`
dicts and the `sorted_signal_cache` list materialization (`:298,306,322,331-333`).

---

## 4. Data-structure audit

**Hot-path lookups — dict vs. scan:**
- **Correct (O(1)):** `MemoryPositionStore.get(symbol)` (`portfolio/memory_position_store.py:38-42`);
  `HorizonSignalEngine._regime_cache`/`_sensor_cache` point lookups when keyed correctly;
  `SensorRegistry._sensors`/`_state` dict-keyed by `(sensor_id[,version], symbol)`.
- **Should be O(1), is O(n) — the two headline findings from §1/§2:**
  `HorizonSignalEngine._build_bindings` scans all of `_sensor_cache` (`dict[(symbol,
  sensor_id), float]`, unindexed by symbol) instead of a `dict[symbol, dict[sensor_id,
  float]]` structure (`signals/horizon_engine.py:754-758`); `UniverseSynchronizer
  ._emit_context`'s legacy branch scans all of `sorted_signal_cache` per symbol instead
  of indexing `_signal_cache` by `(horizon, symbol)` (`composition/synchronizer.py:
  351-362`) — the code's own comment at `:327-330` shows the team already hoisted the
  **sort** out of the loop but left the **scan** itself un-hoisted.
- **Should be O(1), is O(N)/O(N×S):** `BasicRiskEngine._compute_current_equity` /
  `positions.total_exposure()` — both recompute from `positions.all_positions()`
  (itself an O(N) `dict(self._positions)` copy, `memory_position_store.py:175`) on
  every call, with no incremental running total (`basic_risk.py:839-854, 197-212`).
  If the injected `positions` argument is a `StrategyPositionStore.as_aggregate()` view
  instead of the base `MemoryPositionStore` (confirmed: the main orchestrator path uses
  the base store, `bootstrap.py:537`; only the per-alpha-budget `AlphaBudgetRiskWrapper`
  path uses the aggregate view), every "O(1)" `.get()` degrades to O(S) and every "O(N)"
  scan degrades to O(U×S) (`portfolio/strategy_position_store.py:95,111,131-136,228-230`).
- **Minor, small-n:** `HazardPolicy.universe: tuple[str, ...]` — `symbol not in
  policy.universe` is an O(\|policy.universe\|) linear scan through a tuple where a
  `frozenset` would be O(1) (`risk/hazard_exit.py:126`, used at `:215-223,241`); n is
  per-policy universe size (small), not platform-wide, so impact is bounded but the fix
  is free.
- **Correctly small-n, not a finding:** `SensorRegistry._on_event`'s O(S) per-spec scan
  (S≈15–18) and `HorizonSignalEngine._on_snapshot`'s O(A_h) per-snapshot scan are both
  genuine linear fan-outs over small, deployment-bounded constants, not accidental
  quadratic blowups — flagged as P2 consistency items (§8) because the *sibling*
  `HorizonAggregator` already solved the identical shape via bucketing
  (`features/aggregator.py:191-199,261-273`, with its own comment citing a
  10⁷-events/session motivation for having done so), not because the current cost is
  itself alarming.

**Decimal vs. float:**
- **Correctly float, never Decimal:** all 18 sensors convert `bid`/`ask`/`price` to
  `float` on the first line(s) of `update()` and never import `decimal` — appropriate,
  since L1 sensor output is a statistical estimator, not settlement money.
- **Correctly Decimal:** `buying_power.py` (fully Decimal, no float at all);
  `_compute_current_equity` and the exposure/drawdown Decimal accumulation in
  `basic_risk.py:839-854`; `BudgetBasedSizer`'s capital-allocation chain
  (`risk/position_sizer.py:90-104`); `sized_intent_orders.py`'s share-count conversion
  (`Decimal(str(tgt.target_usd)) / mark`, `:117-121`).
- **Deliberate, repeated float↔Decimal bridging (not a bug, but a real per-call cost
  worth naming):** `Decimal(str(x))` round-trips appear at `basic_risk.py:738,765,776-777`
  (percentages/scaling factors), `edge_weighted_sizer.py:288`, `position_sizer.py:90-92`,
  and `sized_intent_orders.py:117-121,171-174` — each is a `float`→`str`→`Decimal` parse,
  not a direct numeric conversion. `RiskConfig` itself mixes `int`
  (`max_position_per_symbol`), `float` (all percentage/scale fields), and `Decimal`
  (`account_equity`) in one dataclass (`basic_risk.py:56-69`).
- **Cross-layer float→Decimal handoff:** `CompositionEngine`'s entire dollar-target
  pipeline is `float` (`TargetPosition.target_usd: float`, `core/events.py:577`;
  `engine.py`'s `target_usd`/`expected_gross`/`expected_turnover` dicts), then re-parsed
  into `Decimal` at the risk-layer boundary via the same `str()` bridge
  (`sized_intent_orders.py:117-121`). Not a precision bug in practice (float64 carries
  15–17 significant digits, far more than any realistic dollar target needs), but it is
  an inconsistent type boundary between two layers that both ultimately feed order
  quantities — worth a design note, not a fix.
- **Float touching a risk-limit calculation (flagged, not necessarily wrong):**
  `_regime_scaling`/`_get_regime_factor` (`basic_risk.py:790-837`,
  `position_sizer.py:111-137`) compute a `float` regime-conditional expected-value scale
  and multiply it directly into `int` position-limit math
  (`adjusted_max = int(self._config.max_position_per_symbol * regime_scale)`,
  `basic_risk.py:191,258`) — quantity math, not money, so the float precision is
  immaterial here, but it's adjacent enough to the money path to name explicitly.

**Determinism constraint — structures explicitly ruled out, per the audit's request to
justify exclusions:**
- Converting `HazardPolicy.universe` from `tuple` to `frozenset` is safe *only* because
  it is used exclusively for `in` membership tests (`hazard_exit.py:215-223,241`) —
  confirmed by reading every use site; it is never iterated in an order-dependent way.
- The inverse would be **unsafe**: `HorizonSignalEngine._signals: list[RegisteredSignal]`
  is deliberately a `list`, explicitly sorted at registration time
  (`horizon_engine.py:239-242`, *"Sort by (horizon_seconds, alpha_id) so iteration order
  is a deterministic function of registered ids — independent of registration order"*).
  Converting this to a `set`/`dict`-iteration-order-dependent structure would directly
  violate Inv-5 by making dispatch order depend on hash seed / insertion history rather
  than the pinned sort key. Same reasoning protects `_features_sorted` in
  `HorizonAggregator` (`aggregator.py:168-173`) and `self._specs: list[SensorSpec]` in
  `SensorRegistry` (topological-order dependent, `registry.py:214,249-253`).
- The platform's own `PYTHONHASHSEED=0` pin (`docs/three_layer_architecture.md §12.5`,
  surfaced as a live warning in every test run this audit executed — see environment
  caveat above) exists precisely because CPython `set`/`frozenset` iteration order is
  hash-seed-dependent; every `set`/`frozenset` in the hot path was checked for
  order-dependent iteration during this audit (`_subscribed_types: set[type[Event]]` in
  `registry.py:148` — membership-only, safe; `_emitted_for_episode: set[tuple[str,str,str]]`
  in `hazard_exit.py:184` — membership-only, safe; `_transitions: dict[S, frozenset[S]]`
  in `state_machine.py:85` — the frozenset is a membership check via `can_transition`,
  never iterated for ordering, safe). No hash-seed-order-dependent hot-path bug was found.

---

## 5. Determinism-safety classification

**This section gates §§6–8.** Every optimization named anywhere in this report is
classified below. "Constraint: Inv-5" means the finding itself is not a violation but
Inv-5 is the binding requirement any fix must preserve.

**Confirmed: no existing parallelism or nondeterminism on the decision path.**
Repo-wide grep for `threading|asyncio|multiprocessing|Lock|RLock|Semaphore|
ProcessPoolExecutor|ThreadPoolExecutor` across `kernel/`, `bus/`, `risk/`,
`composition/`, `sensors/` returns exactly one hit family: `SequenceGenerator`'s
`threading.Lock` (`core/identifiers.py:44`), which is a live/paper multi-thread
*uniqueness* guarantee, not decision-path concurrency — no thread or process is ever
spawned inside the tick pipeline itself (`EventBus.publish`, `bus/event_bus.py:59-68`,
is a plain synchronous `for` loop; `_process_tick_inner`, `orchestrator.py:2236-3066`,
is straight-line/branching Python with no async/thread constructs). Inv-10 (no
wall-clock on the decision path) is also confirmed intact: `time.perf_counter_ns()`
calls in `_process_tick_inner`/`_finalize_tick` (`orchestrator.py:2241,2455,2606,3072`)
feed **only** `MetricEvent.value` floats through a dedicated `SequenceGenerator`,
disjoint from every locked parity-hash stream (`tests/determinism/
parity_manifest.py:LOCKED_PARITY_BASELINES`, 10+ entries verified present); event
`timestamp_ns` fields come exclusively from `self._clock.now_ns()`
(the injected `Clock`), never from the wall-clock timer. Note the sensor layer takes a
*stricter* stance on the identical question — it bans inline `perf_counter_ns()` reads
from the dispatch path entirely (`sensors/registry.py:152-155`, citing its own prior
removal, "S6") in favor of an external monitoring subscriber, rather than relying on the
disjoint-sequence-generator argument. Both conventions are Inv-10-compliant as
implemented; the inconsistency is a P2 documentation/convention item (§8), not a defect.

| # | Optimization | Component | Classification | Rationale |
|---|---|---|---|---|
| 1 | Symbol-keyed index for `HorizonSignalEngine._sensor_cache` (`dict[symbol, dict[sensor_id,float]]`) | Signal engine | **Safe** | Pure lookup restructuring; same values found, only access path changes. Verify no downstream DSL evaluation depends on `Bindings.sensor_values` dict *iteration order* (only key-lookup by identifier name was found — `regime_gate.py` resolves by name, not position) before merging. |
| 2 | Index `UniverseSynchronizer._signal_cache` by `(horizon, symbol)` | Composition | **Safe** | Same reasoning as #1. Must preserve the exact current "first match in sorted order" tie-break semantics when restructuring — an implementation-care note, not a safety objection. |
| 3 | Horizon-bucket `HorizonSignalEngine._on_snapshot` dispatch (mirror `HorizonAggregator._features_by_horizon`) | Signal engine | **Safe** | Identical pattern already proven safe and shipped in the sibling aggregator file. |
| 4 | Type-bucket `SensorRegistry._on_event` dispatch | Sensors | **Safe** | Same proven pattern; win is small given S≈15–18. |
| 5 | Bound/cap `StateMachine._history` for macro/micro/order/risk-escalation/data-integrity SMs (leave alpha-lifecycle's history intact — it is read) | Kernel/core | **Safe** | Inv-13 requires the `TransitionRecord`/`StateTransition` to be *emitted on the bus* (unchanged by this fix) — it does not require unbounded in-process retention. Grep-confirmed no other reader exists. |
| 6 | Extend `InMemoryMetricCollector._store_raw_events = False` (or a ring buffer) to PAPER/LIVE | Monitoring | **Safe** | `live is not replay-hashed` per the codebase's own documented reasoning (`core/identifiers.py:37-38`) — this doesn't touch the Inv-5 boundary at all; purely an operational memory-safety fix. |
| 7 | Add `slots=True` to `Event` and every subclass in `core/events.py` | Core | **Safe** | Pure memory-layout change; frozen-dataclass equality/hash/repr/field values unaffected. Verify (before merging) that no code does `vars(event)`/dynamic attribute assignment on an event instance — none found in this audit's sampling, but this is the highest-blast-radius change in the backlog, so run the full determinism suite (`tests/determinism/`) as the explicit verify step. |
| 8 | Cache `spec.key` as a stored attribute instead of a recomputed `@property` | Sensors | **Safe** | Trivial memoization of a value fixed at construction. |
| 9 | Reduce `SensorRegistry`/sensor double-`SensorReading` allocation | Sensors | **Safe, but M effort** | Requires a `Sensor.update()` protocol change (return a lighter value+warm payload, let the registry build the one canonical `SensorReading`) — a pure refactor if the final published values are unchanged, but touches all 18 sensor implementations, so higher regression surface than a pure caching fix. |
| 10 | Drop `SequenceGenerator`'s lock for the BACKTEST/replay path specifically | Core | **Conditionally safe** | Safe *only* for the single-threaded backtest path (provably uncontended — removing an uncontended lock changes nothing about value or order). **Must not** be removed unconditionally: PAPER/LIVE "may allocate from multiple threads" per the class's own docstring (`core/identifiers.py:33-38`), where the lock's uniqueness guarantee (not determinism — live isn't replay-hashed) is still required. |
| 11 | Cache `Bᵀ B` / its solve in `FactorNeutralizer` when loadings/universe are unchanged | Composition | **Safe** | Identical linear-algebra inputs → identical outputs (deterministic for fixed inputs on a fixed BLAS build); caching a result that would otherwise be recomputed identically introduces no new nondeterminism — it is strictly a subset of work already being done. |
| 12 | Reuse `cp.Parameter`/long-lived `cp.Problem` in `TurnoverOptimizer._optimize_cvxpy` (ecos mode only) | Composition | **Conditional — verify before merging** | Avoiding re-canonicalization is safe in isolation, but if combined with solver **warm-starting**, ECOS's iterative convergence path can differ in low-order floating-point bits from a cold solve on identical inputs. Since this path is off by default and only reachable via explicit operator opt-in, treat as: safe to implement, but gate the merge on a bit-identical comparison against the existing parity/replay tests specifically exercising `composition_optimizer_mode: "ecos"`, or disable warm-starting explicitly if the solver API exposes that toggle. **Do not** assume safety without that check — this is the one item in this table with genuine Inv-5 exposure if implemented carelessly. |
| 13 | Incrementally maintain `total_exposure()` / `_compute_current_equity()` instead of O(N) full recompute per risk check | Risk | **Safe for Inv-5, real correctness risk** | An incremental running total updated on every fill/mark event is still fully deterministic given the same inputs (Inv-5 is not at risk — the danger is a *correctness* bug, not a *determinism* bug: a missed mutation path would make the cache silently diverge from the true value, deterministically, on every replay of the same buggy code). This is the highest-value target in the backlog by call frequency; recommend implementing behind a debug-mode cross-check (`assert cached == recompute()`) under a test flag before trusting it in production, given the breadth of mutation paths (`update_mark`, fills, realized PnL, fee debits) that must all be captured. Treat as higher *engineering* risk than its Inv-5 classification alone would suggest. |
| 14 | Convert `HazardPolicy.universe` from `tuple` to `frozenset` | Risk | **Safe** | Used exclusively for `in` checks (verified every call site); never iterated for ordering. |
| 15 | Memoize `_window_id_hash()` SHA-256 in `scheduled_flow_window.py` | Sensors | **Safe** | Pure function of a static per-window string; identical output every call. |
| 16 | Hoist `Decimal("2")` to a module constant in `_process_tick_inner` | Kernel | **Safe** | Identical numeric value; construction-site change only. |
| 17 | Unify hot-path timing convention (either extend the orchestrator's dedicated-sequence-generator pattern to sensors, or apply the sensor layer's stricter "off-path only" convention everywhere) | Cross-cutting | **Both current conventions are safe; pick one for consistency** | Not a performance fix — a code-hygiene recommendation, included here because the audit asked every timing-adjacent pattern to be explicitly classified. |
| — | **Explicitly forbidden: parallelizing the per-boundary composition/synchronizer fan-out across symbols** (tempting since it superficially matches "symbol-level independence" in the performance-engineering skill's own optimization table) | Composition | **Forbidden for this codebase** | The skill's own hard rule states parallelism is permitted "across symbols... never within the causal chain," which could be read as licensing this — but in practice it would require splitting/synchronizing `_sensor_cache`/`_regime_cache`/`_signal_cache` (currently safely single-threaded), for marginal gain, when the *same* code already has a strictly-better sequential fix available (items #1/#2 above, which remove the O(n²) shape entirely with zero concurrency risk). Given boundary-only cadence and a 5ms hard ceiling already budgeted, the ROI does not justify the risk. Fix the indexing first; treat parallelization here as out of scope. |
| — | **Explicitly forbidden: batching/delaying/dropping `StateTransition` or `MetricEvent` bus publication** to cut per-tick allocation count | Kernel | **Forbidden** | Directly violates Inv-13 ("no silent transitions," full provenance). Distinguish sharply from item #5 above (bounding *retention*, not *emission*) — emission must stay exactly as-is. |
| — | **Explicitly forbidden: caching `RegimeEngine.posterior()` across sequence numbers** (i.e., beyond its existing per-(symbol,sequence) idempotency) | Regime engine | **Forbidden / unnecessary** | Already optimal (O(1), idempotent, `services/regime_engine.py:502-503`); any further caching would either be a no-op or would break causality (Inv-2/Inv-6) by reusing a stale posterior across sequences. |

---

## 6. Perf-baseline audit

**What's pinned, and how:** `tests/perf/_pinned_baseline.py` loads
`tests/perf/baselines/v02_baseline.json` (path built at `:35`), gated by the
`PERF_HOST_LABEL` env var (`:87,130`). Two loaders: `load_pinned_baseline()` (generic
section) and `load_paper_rth_baseline()` (paper_rth-specific). Missing-baseline handling
is a **soft `None` return** at every failure mode — env var unset, JSON file
missing/corrupt, host label absent from `hosts`, or a malformed section — never a raise;
callers decide (`test_paper_rth_no_regression.py` turns `None` into `pytest.skip`;
`test_phase4_1_no_regression.py` simply skips the pinned-comparison block). Confirmed:
`v02_baseline.json` is exactly
```json
{"schema_version": "1.0.0", "hosts": {}}
```
— zero hosts, byte-identical to what the 2026-06-25 audit found. `scripts/
record_perf_baseline.py` (writes `phase4_1_decay_weighting` sections; refuses to record
from a failing run, `:92-97`) and `scripts/record_paper_perf_baseline.py` (post-processes
a `timing.jsonl`, writes `paper_rth` sections; note `fill_to_position_p99_s` is
**hardcoded to `0.0`**, never computed, `:46`) are both functional, but neither has ever
been run against this repository's history to populate a real entry.

**Drift detection — what's actually enforced, per file:**

| File | What it claims (skill/docs) | What it actually asserts | Live-measured this pass |
|---|---|---|---|
| `test_paper_rth_no_regression.py` | "≤12% e2e vs v0.2 baseline (policy target)" | Zero comparison logic. Only `tick_processing_p99_s > 0.0` and `drain_p99_s >= 0.0` (`:20-21`) — presence/sanity, not drift detection. Skill doc itself already says "the 12% comparator gate is planned," so this is a *disclosed* gap, not a doc/code mismatch. | Skipped (no `PERF_HOST_LABEL` recorded host, even when the var is explicitly set to a fabricated label — confirmed via `PERF_HOST_LABEL=audit-host`, printed `PERF_BASELINE_MISS ... reason=host_not_in_baseline_file`) |
| `test_phase4_1_no_regression.py` | "≤5% wall-clock vs decay-OFF (policy target)" | **Real** ratio computed every run; **hard-fails only above 25%** (`_HARD_GATE_FACTOR = 1.25`, `:93`); 5–25% only prints a non-failing `PHASE4_1_BUDGET_WARNING` (`_POLICY_BUDGET_FACTOR = 1.05`, `:88`, checked at `:141-148`). Separate per-host pinned block (`:160-181`) is dead code today (zero hosts). | Run A: `overhead_pct=3.09` (ratio=1.0309); Run B: `overhead_pct=4.91` (ratio=1.0491) — both under the enforced 25% ceiling, both real and close to the *unenforced* 5% policy line, run B especially (0.09 points away) |
| `test_perf_baseline_plumbing.py` | (acceptance test, no policy claim) | 5 tests, all existence/shape/importability checks (script exists + has `main`, JSON is well-formed, helper returns `None` correctly, referenced pytest node id is collectable) — **zero numeric thresholds anywhere in the file**, confirmed by direct reading | 5 passed |
| `test_sensor_latency_budget.py` | "informational only... no CI gate" (self-documented, `:7-10`) | Only 2 assertions: `emitted > 0` per sensor and `"sensor" in captured.out` — the second assertion **consumes `capsys`**, which empirically hides the printed p50/p99/mean table in every invocation mode tried | 1 passed (`CI_BENCHMARK=1`); table never appears in output under `-q`, `-q -s`, or `-v -s` |

**Is this brittle or host-specific-by-design?** The mechanism itself (host-labeled JSON,
soft-fail loader, `--host-label` recorder CLI) is a reasonable, correctly-engineered
design for "CI on a different machine is meaningful" — the *design* is not brittle. The
*population* is: zero hosts have ever been recorded, on this repository, across at least
two audit passes eight days apart (2026-06-25 → 2026-07-02). Per this audit's
"shipped vs not-shipped" instruction, the two comparator *policies* (12% paper-RTH,
5% decay-weighting) are honestly marked "planned" in the owning skill doc, so their
incompleteness is downgraded from P0 to P1 (§8) — a disclosed gap, not a broken promise.
The **pinned-baseline recording infrastructure itself**, by contrast, is presented in the
skill doc as a live, ready-to-use system ("Per-host pinned baselines live in
`tests/perf/baselines/v02_baseline.json`... record new baselines via `python
scripts/record_perf_baseline.py --host-label <id>`" — no "planned" qualifier) — and it
does work correctly when invoked. Its unpopulated state is therefore the cleanest match
in this audit for the literal P0 example given in the brief: **"a perf baseline that
guards nothing"** (§8, P0-1).

**Cross-reference to the 2026-06-25 audit:** that audit's P0 backlog items #1 ("restore
decay-budget harness") and #2 ("assert referenced harness is collectable") are now
resolved — `test_phase4_1_no_regression.py` and the harness-collectability test in
`test_perf_baseline_plumbing.py` both exist and work as designed today. Item #3 ("wire a
real comparator into `test_paper_rth_no_regression` or record at least one host
baseline") remains open, unchanged, eight days later.

---

## 7. Test gap matrix + proposed benchmarks

| Hot-path stage | Perf coverage today | Gap |
|---|---|---|
| M0→M1 (event receipt/log/publish) | None | No dedicated timer; folds into `tick_to_decision_latency_ns` |
| M1→M2 (regime posterior) | None | Same |
| SENSOR_UPDATE (registry fan-out) | `test_sensor_latency_budget.py` exists, `CI_BENCHMARK=1`-gated | **Output is unconditionally swallowed by the test's own `capsys` consumption** — no p50/p99/mean ever visible, confirmed empirically |
| HORIZON_CHECK/AGGREGATE | None | No dedicated timer or benchmark found anywhere |
| SIGNAL_GATE (`HorizonSignalEngine`) | None | No dedicated timer or benchmark; this is the stage containing the O(U²) `_build_bindings` finding (§1.2) — currently invisible to any regression gate |
| CROSS_SECTIONAL (composition) | None | No dedicated timer or benchmark; contains both the O(U²) synchronizer finding and the cvxpy-rebuild finding |
| M4→M5 `check_signal` | `risk_check_ns` timer exists (`orchestrator.py:2606-2608`) | Timer covers the whole call, not broken out by the up-to-5 internal O(N) scans; no scaling-with-N benchmark |
| CROSS_SECTIONAL→M5 `check_sized_intent` | None | No dedicated timer; the O(L×N) per-intent cost is entirely unmeasured |
| M5→M7 order construction + `check_order` | None | `check_order`'s O(N) scans are untimed (contrast with `check_signal`, which at least has a whole-call timer) |
| End-to-end M0→M10 | `tick_to_decision_latency_ns` HISTOGRAM, every tick | Complete for the aggregate; useless for attributing a regression to a specific stage |
| Perf-baseline drift (paper-RTH, decay-weighting) | Exists, see §6 | Comparator logic incomplete/inert per §6 |

**Proposed minimal benchmarks (specs only — no code in this pass):**

1. **Per-segment timer coverage.** Extend `_tick_timings` (`orchestrator.py:2242`) to
   bracket every M0→M10 sub-stage the way `signal_evaluate_ns`/`risk_check_ns` already
   do, particularly `sensor_dispatch_ns`, `horizon_aggregate_ns`, `cross_sectional_ns`,
   and `order_construction_ns`. Each is a `time.perf_counter_ns()` delta feeding a
   `MetricEvent` through the existing dedicated-sequence-generator pattern — already
   proven Inv-10-safe (§5) and directly analogous to the two timers that exist today.
2. **Universe-scaling benchmark.** Run one representative boundary tick (fixed sensor
   readings, fixed regime state) at U ∈ {10, 50, 100, 500} symbols and assert wall-clock
   scales sub-quadratically (e.g., `t(500)/t(100) < 20` rather than the ~25 an O(U²)
   process would produce). This would directly catch both O(n²) findings in §1.2/§2 and
   guard against their reintroduction.
3. **Position-count-scaling benchmark.** Run `check_signal`/`check_order` at N ∈ {10,
   100, 1000} tracked positions in the store and assert near-linear scaling — would
   directly catch the O(N)-scan findings in §1.3/§4.
4. **Fix, not add:** `test_sensor_latency_budget.py` should stop consuming `capsys` for
   its own assertion (e.g., check the returned per-sensor stats dict directly instead of
   grepping captured stdout) so its existing p50/p99/mean measurement becomes visible —
   this restores an existing, already-written benchmark rather than requiring a new one.
5. **Populate the empty baseline** (operational, not a code change): run
   `scripts/record_perf_baseline.py --host-label <ci-runner-id>` and
   `scripts/record_paper_perf_baseline.py` at least once on a stable CI host so the
   already-built pinned-comparison code paths in both perf test files stop being
   permanently inert (closes 2026-06-25's still-open backlog item #3, and this audit's
   P0-1).

---

## 8. Prioritized backlog

Every P0/P1 item cites at least one platform invariant (`.cursor/rules/
platform-invariants.mdc`) and a `path:line`, per the audit contract. "DS" =
determinism-safety classification from §5.

### P0

**P0-1 — Pinned perf-baseline system has zero recorded hosts; every `PERF_HOST_LABEL`
comparison is inert.**
`tests/perf/baselines/v02_baseline.json` (`{"hosts":{}}`); `tests/perf/
_pinned_baseline.py:87-159`; `tests/perf/test_paper_rth_no_regression.py:16-21`;
`tests/perf/test_phase4_1_no_regression.py:160-181`. Presented as live, ready
infrastructure in the owning skill doc (no "planned" qualifier, unlike the two
comparator policies below), functioning correctly end-to-end when exercised, but never
populated — confirmed unchanged across two audits eight days apart. Matches the audit
brief's literal P0 example: "a perf baseline that guards nothing." Constraint: Inv-5 (any
comparator, once wired, must not itself introduce nondeterminism into the measurement
path — the existing off-path timing pattern already satisfies this). Effort: S
(operational — run the two recorder scripts on a stable host). DS: safe — populating a
baseline is an operational action (running an existing, unmodified script), not a code
change, so no §5 optimization entry applies to it directly.

### P1

**P1-1 — `HorizonSignalEngine._build_bindings` O(U×S) scan → O(U²×A×S) aggregate cost
per horizon boundary.**
`src/feelies/signals/horizon_engine.py:754-758` (scan), `:397-400` (call site),
`:220,291-336` (unindexed `_sensor_cache` population). Constraint: Inv-5 (fix must
preserve identical `Bindings.sensor_values` content). Effort: S–M (§5 item #1). DS: safe.

**P1-2 — `UniverseSynchronizer._emit_context` legacy branch O(U×\|signal_cache\|) ≈
O(U²) per boundary, on the default/common (no-`depends_on_signals`) path.**
`src/feelies/composition/synchronizer.py:351-362`, gating condition at
`bootstrap.py:1875-1882,1984,1996`. Constraint: Inv-5. Effort: S–M (§5 item #2). DS: safe.

**P1-3 — `BasicRiskEngine.check_signal`/`check_order` perform 2–5 unconditional O(N)
full-position-store scans per call, on every signal tick.**
`src/feelies/risk/basic_risk.py:727-728` (`_check_exposure_and_drawdown`), `:681`
(`_prospective_total_exposure`), `:505-511,581-593` (PDT/buying-power sub-checks);
`portfolio/memory_position_store.py:175,206-212` (uncached `all_positions()`/
`total_exposure()`). Highest call-frequency finding in this audit (every tick with a
signal, not boundary-gated). Constraint: Inv-5 for the fix mechanics; Inv-12 (transaction
cost realism) is the reason this budget matters at all — a slow risk check under stress
(2× fill-latency per Inv-12's own stress protocol) compounds with real market conditions.
Effort: M–L (§5 item #13 — Inv-5-safe but carries real correctness risk if the
incremental-maintenance implementation misses a mutation path; recommend a debug-mode
cross-check before trusting it). DS: safe for Inv-5, engineering-risk caveat applies.

**P1-4 — `check_sized_intent` → `build_sized_intent_orders` calls the O(N)-scanning
`check_order` once per leg → O(L×N) per PORTFOLIO intent.**
`src/feelies/risk/sized_intent_orders.py:110-147`; `basic_risk.py:334-397`
(`check_sized_intent` delegation). Same root cause and same fix as P1-3 — resolving P1-3
resolves this proportionally. Constraint: Inv-5, Inv-11 (per-leg veto semantics must be
preserved exactly — an incremental-exposure fix must not change *which* legs pass/fail,
only how fast the check runs). Effort: M–L (shared with P1-3). DS: safe for Inv-5.

**P1-5 — `StateMachine._history` grows unbounded for the life of the process across 5 of
6 SM instances; no reader exists for those 5.**
`src/feelies/core/state_machine.py:87,175,207` (growth), `:112-113` (unbounded-copy
property); confirmed via grep that only `alpha/lifecycle.py:295,599` ever reads
`.history`. Constraint: Inv-13 (full provenance) — the fix must preserve bus-side
`TransitionRecord`/`StateTransition` emission exactly; only in-process retention is
bounded. Effort: S (§5 item #5). DS: safe.

**P1-6 — `InMemoryMetricCollector._events` unbounded for PAPER/LIVE (fixed for
BACKTEST).**
`src/feelies/monitoring/in_memory.py:60,63,66-69,71-73`; `bootstrap.py:564-566` (the
existing BACKTEST-only guard). Team's own comment: "~11M entries → 91 MB buffer" for
long runs — PAPER/LIVE sessions can run for a full RTH session or longer without
restart. Constraint: Inv-11 (fail-safe default) — unbounded growth culminating in an
OOM crash mid-session is an increased-exposure failure mode (a crashed process cannot
manage or flatten open positions), not Inv-5: live is explicitly not replay-hashed
(`core/identifiers.py:37-38`), so this is a safety fix, not a determinism question.
Effort: S (§5 item #6). DS: safe.

**P1-7 — Sensor-path double `SensorReading` allocation + `SequenceGenerator` lock
overhead (measured).**
`src/feelies/sensors/registry.py:19` (docstring self-acknowledges the double-allocation),
`:350-399` (`_stamp`); `core/identifiers.py:44-50`. Measured, prior audit (2026-06-25,
not re-run this pass): `_stamp` 0.291s/113,136 calls (throwaway alone: 0.077s/113,136);
lock `__exit__` 0.020s/113,276 calls. Constraint: Inv-5 (fix must preserve identical
emitted `SensorReading` field values) and Inv-13 (`SensorProvenance` stamping must be
preserved). Effort: M (protocol change across 18 sensors, §5 item #9) for the
double-allocation; S (§5 item #10, backtest-only) for the lock. DS: safe.

**P1-8 — `test_paper_rth_no_regression.py` performs zero regression comparison despite
its name and position in the CI-adjacent perf suite.**
`tests/perf/test_paper_rth_no_regression.py:16-21`. Downgraded from the generic P0
bucket specifically because the owning skill doc already discloses this as "baseline
plumbing only today... the 12% comparator gate is planned" — a disclosed gap, not a
silent break. Still real operational risk: nothing today would catch a paper-RTH
throughput regression via this file. Constraint: Inv-5 (any future comparator must use
the existing off-path timing pattern). Effort: M (needs a real stored-baseline
comparison, not just presence checks). DS: safe.

**P1-9 — `test_phase4_1_no_regression.py` hard-enforces 25% overhead, 5× looser than the
5% figure quoted as policy; live measurements are already close to the softer,
unenforced line.**
`tests/perf/test_phase4_1_no_regression.py:88,93,141-148,151-158`. Measured this pass:
3.09% and 4.91% (two runs). Constraint: Inv-5 (n/a to the gate itself, cited because any
tightening must not change what's being measured, only the threshold). Effort: S (change
`_HARD_GATE_FACTOR` to something closer to `_POLICY_BUDGET_FACTOR`, or make the 5%
breach fail after N consecutive occurrences to absorb noise). DS: safe.

**P1-10 — Only 2 of ~10 M0→M10 segments have dedicated timers; the stages containing
P1-1/P1-2/P1-3/P1-4 are entirely unmeasured.**
`orchestrator.py:2242` (`_tick_timings` dict), `:2455-2457,2606-2608` (the only two
populated entries). Blocks diagnosing every other finding in this report from live
telemetry. Constraint: Inv-10 (must use the existing off-path
`perf_counter_ns()`-into-`MetricEvent` pattern, already proven safe). Effort: S (§7,
proposal 1). DS: safe.

### P2

**P2-1 — `core/events.py`: add `slots=True` to `Event` and all subclasses.**
`core/events.py:30-54` and ~20 subclasses. Best effort/impact ratio in this audit — S
effort, applies to every hot-path event type, zero determinism risk (§5 item #7). Verify
step: full `tests/determinism/` suite pass.

**P2-2 — Horizon-bucket `HorizonSignalEngine._on_snapshot`; type-bucket
`SensorRegistry._on_event`.** `signals/horizon_engine.py:338-345`; `sensors/
registry.py:273-274`. Same proven pattern as the aggregator (`features/
aggregator.py:191-199`); win is small (S≈15–18, A_h typically small) but free and
consistent with the codebase's own established practice.

**P2-3 — `FactorNeutralizer.neutralize()`: cache Bᵀ B / its solve for unchanged
loadings+universe.** `composition/factor_neutralizer.py:159-191`. Up to 5×/boundary
redundant K³ solve of a constant matrix.

**P2-4 — `HazardPolicy.universe`: `tuple` → `frozenset` for membership tests.**
`risk/hazard_exit.py:126,215-223,241`.

**P2-5 — Memoize `_window_id_hash()`; note the self-documented linear calendar-window
scan.** `sensors/impl/scheduled_flow_window.py:55-58,168`; `services/
event_calendar/__init__.py:152-161` (already carries its own "replace with bisect if
10x growth" comment — informational, not urgent at current scale).

**P2-6 — Cache `spec.key` as a stored attribute.** `sensors/spec.py:150-153`;
`sensors/registry.py:294,385`. Measured (prior audit): 0.032s/239,988 calls.

**P2-7 — Hoist `Decimal("2")` to a module constant.** `orchestrator.py:2344`.

**P2-8 — `cp.Parameter`/long-lived `cp.Problem` reuse in `TurnoverOptimizer`
(ecos mode only, off by default).** `composition/turnover_optimizer.py:316-329`.
See §5 item #12 for the mandatory warm-start verification step before merging — this is
the one P2 item that needs a determinism check, not just a perf check, despite its low
priority (gated off by default).

**P2-9 — `MetricCollector.record()` f-string key formatting per call.**
`monitoring/in_memory.py:74`. Trivial; could precompute/intern per (layer,name) pair.

**P2-10 — Unify hot-path latency-instrumentation convention** (orchestrator's inline
dedicated-sequence-generator pattern vs. sensor layer's stricter off-path-only
convention). Cross-cutting, `orchestrator.py:2241` vs. `sensors/registry.py:152-155`.
Documentation/consistency, not a perf fix.

**P2-11 — `snr_drift_diffusion.py`: avoid list→tuple double allocation for the
per-horizon SNR payload.** `sensors/impl/snr_drift_diffusion.py:205,212,223`. Also note:
this sensor's `state["by_horizon"]` dict-of-dicts structure is the literal anti-pattern
named in `.cursor/skills/performance-engineering/SKILL.md:238` ("Dict-of-dicts for
feature state | Cache-hostile; GC pressure") — informational self-reference, low
priority given it's one sensor among 18 well-implemented ones.

**P2-12 — `scheduled_flow_window.py`'s singleton-instance mutable cache
(`self._symbol_has_windows`).** `sensors/impl/scheduled_flow_window.py:149,176`.
Confirmed safe under the single-threaded dispatch model (each symbol writes only its own
key), but it is the sole exception among 18 sensors to the "state confined to the
per-symbol `state` dict argument" pattern — architectural-consistency note, not a bug.
