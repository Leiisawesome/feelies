# Kernel Audit — 2026-06-24

Scope: read-only, evidence-based audit of the feelies kernel spine — the
orchestrator (M1–M10 driver, bus subscribers, drains), the micro/macro state
machines, the generic `StateMachine` primitive, the event bus, the
signal→order trace, the per-mode component graph in `bootstrap.py`, and the
process entry shim. Focus is **ordering determinism, sequence/clock semantics,
single-writer discipline, and layer boundaries** (Inv-5/6/7/8/10). No
production code or tests were changed.

Out of scope (audited elsewhere): internal math of sensors/signals/risk/
composition, and the orchestrator's decision/exit economics (stop/reverse/
flatten/edge-cost gates) — owned by `audit_position_management.md`.

### Verification run

After resolving an environment dependency-sync timeout (`uv sync --all-extras`),
both read-only suites were run:

- `uv run pytest tests/kernel/ tests/bus/ tests/core/test_state_machine.py tests/bootstrap/ -q` — **348 passed**.
- `uv run pytest tests/causality/test_anti_lookahead.py tests/determinism/ -q` — **89 passed** (includes all 12 locked parity baselines).

**Blocker found and fixed during verification** (separately authorized, outside
the read-only analysis below): `src/feelies/kernel/orchestrator.py` passed
`reason=` twice to the same `OrderRequest(...)` constructor (`:4793` and the
stray `:4795`) — a hard `SyntaxError` that prevented
`feelies.kernel.orchestrator` from importing and errored all 19 kernel/bootstrap
test modules at collection (and would have broken every backtest/paper/live run
on this branch). The stray duplicate kwarg and its now-orphaned local
`reason` variable were removed, keeping the documented `_FORCED_EXIT_PANIC_REASON`
mapping form. This was a pre-existing committed defect, unrelated to the
ordering/determinism findings below.

### Severity convention

- **P0** — a nondeterministic ordering on the tick path, a second writer to a
  parity event type, a hidden global, a wall-clock read in core decision logic,
  or a causality leak. (The audit's bright-line rule.)
- **P1** — fragile-but-correct tie-breaks, drain/idle ordering edge cases,
  layer/observability leakage, or a material determinism test hole.
- **P2** — contract clarity, observability of transitions, defensive hardening.

Each finding is tagged **implementation bug** / **fragile-but-correct** /
**intentional design**.

---

## 1. Executive summary

- **P0 (implementation bug) — set-iteration order on the M9 fill path.**
  `Orchestrator._distribute_fill_to_strategies` does
  `strategy_ids = list(self._strategy_positions.strategy_ids())`
  (`src/feelies/kernel/orchestrator.py:5862`), and `strategy_ids()` returns a
  **`frozenset`** (`src/feelies/portfolio/strategy_position_store.py:201`).
  That order seeds the largest-remainder rounding tie-break
  (`orchestrator.py:5880-5886`) and the per-alpha quantity/fee allocation
  (`orchestrator.py:5891-5910`), so on a symbol held by ≥2 alphas with tied
  remainders the per-alpha split is **hash-seed dependent**, not insertion- or
  sorted-order deterministic. It runs at M9 (`POSITION_UPDATE`,
  `_reconcile_fills` → `orchestrator.py:5730`). Fix: `sorted(...)`. See §3.1.
- **P1 (intentional design, but a coverage hole) — no parity hash exercises the
  orchestrator.** All 12 locked baselines in
  `tests/determinism/parity_manifest.py:84` drive **leaf components** on a bare
  `EventBus` (regime engine, sensor/scheduler/aggregator/signal engine,
  composition engine, risk engine, backtest router) and hash the captured
  stream. None instantiates `Orchestrator`. So the kernel's own `_seq`
  interleaving, micro-SM ordering, drain/flush order, and bus-subscriber
  registration order are **not guarded by any parity hash**. See §9, §10.
- **P1 (fragile-but-correct) — shared `_seq` couples parity events to
  observability volume.** RegimeState (`orchestrator.py:3496`) and
  PositionUpdate (`orchestrator.py:5741`) draw `sequence` from the same kernel
  `_seq` generator consumed by every `StateTransition`
  (`orchestrator.py:5944`, one per SM transition), every MetricEvent, and every
  Alert. Their sequence numbers are a function of the cumulative count of all
  kernel emissions — deterministic for a fixed log, but tightly coupled. The
  per-family generators (`_sensor/_horizon/_snapshot/_signal/_hazard`) were
  introduced precisely to avoid this for new families; RegimeState/PositionUpdate
  were never migrated. See §3.2, §9.
- **P1 (fragile-but-correct) — Signal is published twice on the standalone
  path.** At M4 the orchestrator re-publishes the arbitrated winner
  (`orchestrator.py:2484`) that `HorizonSignalEngine` already published. Every
  `Signal` subscriber — `UniverseSynchronizer._on_signal`
  (`src/feelies/composition/synchronizer.py:203`),
  `HorizonMetricsCollector`, forensic consumers — sees the bus-arbitrated
  winner twice. Harmless to composition (a standalone winner is not in any
  PORTFOLIO universe) and to `_on_bus_signal` (re-buffered then evicted), but it
  is a soft single-writer violation and an observability double-count. See §5.3.
- **P1 (fragile-but-correct) — OrderRequest single-consumer is filter-based,
  not single-writer.** `_on_bus_hazard_order` self-filters on
  `source_layer == "RISK"` **and** `reason ∈ {HAZARD_SPIKE, HARD_EXIT_AGE}`
  (`orchestrator.py:6233-6235`). Correct today — no orchestrator-published order
  carries that combination (verified: emergency-flatten `reason="FORCE_FLATTEN"`
  `orchestrator.py:3701`; data-integrity `DATA_CORRUPTED/DATA_GAP_DETECTED`
  `orchestrator.py:6579,6605`; SIGNAL/PORTFOLIO orders carry non-RISK
  `source_layer`). But any future order built with that signature would
  double-submit. See §5.4.
- **P1 (fragile-but-correct) — bus delivery order is encoded in bootstrap
  statement order.** `EventBus.publish` dispatches handlers in registration
  order (`src/feelies/bus/event_bus.py:65-68`); bootstrap relies on this with a
  documented canonical order (`src/feelies/bootstrap.py:498,582-608,1876-1891`).
  Correct and deterministic, but no explicit priority and no regression test
  asserts the order — a construction-order refactor silently changes delivery.
  See §3.3, §8.
- **P1 (documentation/enforcement gap) — `PYTHONHASHSEED=0` is claimed but not
  enforced in-repo.** `docs/three_layer_architecture.md:1475` lists
  "CI sets `PYTHONHASHSEED=0`" as the mitigation for set/hash ordering, but
  there is no `conftest.py`, `pytest.ini`, `tox.ini`, in-repo CI workflow, or
  `[tool.pytest]` `addopts`/`env` pinning it. The only in-repo uses are manual
  fixture-generation prefixes. This is what makes the P0 above genuinely
  process-dependent rather than incidentally stable. See §3.1.
- **Clean (intentional design) — single-writer holds for every parity event
  except the Signal echo.** RegimeState (`orchestrator.py:3517`),
  RegimeHazardSpike (`:3567`), HorizonTick (`:1923,1878`), PositionUpdate
  (`:5737`) each have exactly one publisher. SensorReading / HorizonFeatureSnapshot
  / CrossSectionalContext / SizedPositionIntent each have one writer in their
  owning layer. See §5.1.
- **Clean (intentional design) — sequence allocation is a pure function of the
  log.** `SequenceGenerator` is a monotonic counter (`core/identifiers.py:28`);
  every `_seq.next()` is allocated in imperative code order on a synchronous
  single-threaded bus. `derive_order_id` is SHA-256 of a provenance seed
  (`core/identifiers.py:18`), never `uuid4`. Per-family generators are
  per-instance, not module singletons (`orchestrator.py:655-666`). See §3.2.
- **Clean (intentional design) — clock discipline holds in the kernel.** All
  decision timestamps come from `self._clock.now_ns()` or carried event ns
  (`quote.timestamp_ns`, `ack.timestamp_ns`). The only `time.perf_counter_ns()`
  calls feed latency telemetry (`orchestrator.py:2232,2446,2589,3055,5198`) that
  lands in MetricEvent / `PaperSessionRecorder`, both excluded from parity.
  `SimulatedClock` rejects backward movement (`core/clock.py:46`). See §6.
- **Clean (intentional design) — mode divergence is confined.** The core
  sensor/signal/composition/risk/hazard graph is built identically across
  BACKTEST/PAPER/LIVE; divergence is limited to the clock (`SimulatedClock` vs
  `WallClock`, `bootstrap.py:781`), the `ExecutionBackend` (`_create_backend`),
  the normalizer (PAPER/LIVE only), event-log order enforcement, and
  lifecycle/observability flags — none on the tick-decision path. See §8.
- **Clean (intentional design) — conditional subsystems gate cleanly.**
  Composition returns all-`None` with no PORTFOLIO alpha
  (`bootstrap.py:1902`); the hazard controller returns `None` with no opt-in
  (`bootstrap.py:2090`); `registry_clock=None` in backtest keeps the promotion
  ledger off the tick path (`bootstrap.py:313`). Absence leaves a clean graph.
  See §8.
- **P2 (fragile-but-correct) — the micro SM is descriptive, not prescriptive.**
  Sensor/signal/composition work runs as bus subscribers during
  `bus.publish(quote)` / `bus.publish(tick)`; the corresponding `SENSOR_UPDATE`
  / `SIGNAL_GATE` / `CROSS_SECTIONAL` transitions are recorded **after** the
  work already happened (`orchestrator.py:1906-1956`). The SM is a forensic
  record; real ordering is enforced by the imperative body + subscription order.
  See §4.
- **P2 (fragile-but-correct) — `SENSOR_UPDATE` cannot legally reach
  `FEATURE_COMPUTE`.** `_MICRO_TRANSITIONS[SENSOR_UPDATE] = {HORIZON_CHECK}`
  (`src/feelies/kernel/micro.py:120`). Safe only because `_dispatch_sensor_layer`
  always advances `SENSOR_UPDATE → HORIZON_CHECK` in the same call and never
  strands there. See §4.
- **P2 (style) — one module-level mutable.** `_FORCED_EXIT_PANIC_REASON` is a
  `dict` at module scope (`orchestrator.py:316`) but is read-only in practice
  (`.get()` at `:4793`); effectively constant. Not a hidden-global violation.

---

## 2. Micro-stage map

`Orchestrator._process_tick_inner` (`orchestrator.py:2227`) is the single
per-tick driver; it never inspects `backend.mode`. Stages below are the
implemented 16-state `MicroState` walk (`kernel/micro.py:82-97`), with the
sensor/signal/composition sub-stages between M2 and M3 entered only when the
relevant layer is wired.

| Stage (MicroState) | Writer / action | Inputs | Output event(s) | Ordering guarantee |
|---|---|---|---|---|
| M1 `MARKET_EVENT_RECEIVED` | orchestrator | `NBBOQuote` from feed | log append + `bus.publish(quote)` (`:2328`) | feed yields one quote at a time; synchronous |
| (router drain) | `_reconcile_resting_fills` → `_drain_async_fills` (`:2384`) | router pending acks | `OrderAck`,`PositionUpdate` | preserves `poll_acks()` list order (`:5071`) |
| M2 `STATE_UPDATE` | `_update_regime` (**sole writer**) (`:2392,3463`) | quote + RegimeEngine | `RegimeState` (`:3517`), maybe `RegimeHazardSpike` (`:3567`) | `max()` tie-break lowest index (`:3474`); `_seq`/`_hazard_seq` |
| `SENSOR_UPDATE` | sensors via bus subscription (`:2401`) | quote | `SensorReading` (sensor layer) | `SensorRegistry` order; `_sensor_seq` |
| `HORIZON_CHECK`/`HORIZON_AGGREGATE` | scheduler+aggregator via bus (`:1921-1936`) | quote ts | `HorizonTick`,`HorizonFeatureSnapshot` | ticks ascending horizon (`§7.4`); `_horizon_seq`/`_snapshot_seq` |
| `SIGNAL_GATE` | `HorizonSignalEngine` via bus (`:1948-1956`) | snapshot+regime | `Signal(layer=SIGNAL)` | engine order; `_signal_seq` |
| `CROSS_SECTIONAL` | synchronizer→composition via bus; bookend (`:2402`) | signals+tick | `CrossSectionalContext`,`SizedPositionIntent` | synchronizer sorts `(boundary_ts,alpha_id,horizon)`; buffered into `_pending_sized_intents` |
| (PORTFOLIO flush) | `_flush_pending_sized_intents` (`:2403,1983`) | buffered intents | per-leg `OrderRequest`,`OrderAck`,`PositionUpdate` | FIFO `deque.popleft` (`:1993`); legs lex-sorted by risk engine |
| M3 `FEATURE_COMPUTE` | orchestrator (empty body) (`:2413`) | — | — | bookkeeping only (legacy hook) |
| M4 `SIGNAL_EVALUATE` | `_select_bus_signal` (`:2447,6096`) | `_signal_buffer` (list) | `bus.publish(signal)` (`:2484`) | arbitrator over ordered list; ties = buffer order |
| M5 `RISK_CHECK` | `risk_engine.check_signal` (`:2590`) | signal+positions | `RiskVerdict` | engine-owned sequence |
| M6 `ORDER_DECISION` | `_try_build_order_from_intent` + `check_order` (`:2762,2789`) | intent+verdict | `OrderRequest`,`RiskVerdict` | single order/tick on this path |
| M7 `ORDER_SUBMIT` | `order_router.submit` + `bus.publish(order)` (`:2979,3011`) | order | `OrderRequest` | `_seq`/`derive_order_id` |
| M8 `ORDER_ACK` | `_poll_order_router_acks({order_id})` (`:3030`) | router | `OrderAck` | set used for membership only; list order preserved (`:5071`) |
| M9 `POSITION_UPDATE` | `_reconcile_fills(acks)` (**sole writer**) (`:3041,5504`) | acks | `PositionUpdate` | iterates `acks` list in order; `_seq` |
| M10 `LOG_AND_METRICS` | `_finalize_tick` (`:3049,3053`) | timings | `MetricEvent` | `_tick_timings` insertion order (`:3078`); `_seq` |

Loop-backs: `LOG_AND_METRICS → {WAITING, RISK_CHECK, FEATURE_COMPUTE}`
(`micro.py:210`) support the PORTFOLIO multi-intent flush and resuming M3 after
the flush.

---

## 3. Ordering-determinism audit (Inv-5)

### 3.1 Iteration over collections on the tick path

Every iteration on M1–M10 was enumerated. All but one iterate
deterministically-ordered structures:

- `self._signal_buffer` — `list`, partitioned fresh/stale preserving order
  (`:2256-2279`), arbitrated as an ordered list (`:6116`). Deterministic.
- `self._pending_sized_intents` — `deque`, drained FIFO via `popleft`
  (`:1993`). Deterministic.
- `self._deferred_router_acks` / `acks` — `list`, prepended and iterated in
  order (`:5060-5076,5201`). Deterministic.
- `self._active_orders.items()` — `dict`, insertion-ordered (`:1737,1750,5929`).
  Deterministic.
- `self._tick_timings.items()` — `dict`, insertion-ordered (`:3078`).
  Deterministic (count is path-conditional but the path is deterministic).
- `intent.target_positions` — sorted lex by symbol inside
  `check_sized_intent` (verified by `tests/determinism/test_portfolio_order_replay.py:140`).
- Membership-only sets (never iterated for ordered output):
  `_carryover_signal_sequences`, `_alpha_symbols_with_fills`,
  `_hazard_submitted_order_ids`, `_halted_symbols`, `_ssr_active`,
  `_consumed_by_portfolio_ids` (frozenset built at `:6053-6065`, only
  `in`-tested). Deterministic in effect.
- `_poll_order_router_acks`: `expected_order_ids` is a `set` but used **only**
  for `in` membership; `matched`/`deferred` order comes from iterating the
  `all_acks` **list** (`:5071-5076`). Deterministic.

**The one exception (P0, implementation bug):**
`_distribute_fill_to_strategies` (`:5841`) builds
`strategy_ids = list(self._strategy_positions.strategy_ids())` (`:5862`).
`strategy_ids()` returns `frozenset(self._stores.keys())`
(`strategy_position_store.py:201`). Materialising a `frozenset` to a `list`
yields **hash-ordered**, not insertion-ordered, iteration. That order then:
1. orders `strategy_qtys` (`:5867-5873`),
2. seeds the stable largest-remainder tie-break — `sorted(..., key=-remainder)`
   (`:5884`) preserves `strategy_qtys` order on ties, so the `+1` deficit is
   assigned by frozenset position (`:5885-5886`),
3. selects `remainder_sid`, the recipient of the fee remainder (`:5910-5917`).

This path is the **fallback** distribution (no FillLedger attribution record:
emergency flatten, stop exit, or attribution failure — see the docstring at
`:5849-5857`) and writes to `_strategy_positions`. Per-alpha books feed
`_standalone_signal_actionable_for_strategy_ownership` (`:6068`), which can flip
whether a standalone exit becomes an order on a shared symbol — so the
nondeterminism can reach the order stream. It is masked **only** if
`PYTHONHASHSEED` is pinned, which the repo does not do (§3.3 note,
`docs/three_layer_architecture.md:1475` vs. absence of any in-repo enforcement).
Notably the codebase already knows this hazard and avoids it elsewhere by using
SHA-256 prefixes instead of builtin `hash`
(`src/feelies/sensors/impl/scheduled_flow_window.py:36`). **Fix:** `sorted(self._strategy_positions.strategy_ids())`.

### 3.2 Sequence and correlation-ID allocation

- `correlation_id` is `make_correlation_id(symbol, exchange_ts, sequence)`
  (`core/identifiers.py:9`), carried from the quote — a pure function of the log.
- `SequenceGenerator.next()` is a lock-guarded monotonic counter
  (`core/identifiers.py:37`). On the synchronous single-threaded replay bus,
  allocation order == imperative code order == a pure function of the log.
- **Per-family isolation (good):** `_seq` (kernel), `_sensor_seq`,
  `_horizon_seq`, `_snapshot_seq`, `_signal_seq`, `_hazard_seq` are distinct
  per-instance generators (`orchestrator.py:627,655-666`), each owned by exactly
  one event family. `tests/determinism/test_legacy_sequence_isolation.py`
  asserts this. Enabling sensors/signals/hazard cannot perturb other families'
  sequence numbers (Inv-A).
- **Residual coupling (P1, fragile-but-correct):** RegimeState (`:3496`) and
  PositionUpdate (`:5547,5741`) remain on the shared `_seq`, which is also
  consumed by `_emit_state_transition` (one `StateTransition` per micro/macro/
  risk/order SM transition — `:5944`), MetricEvent (`:3069,3083`), and every
  Alert. Within a fixed log this is deterministic, but the `sequence` field on
  these parity-relevant events is entangled with the exact count and ordering of
  all kernel bus emissions, including path-conditional alerts. The migration
  that protected the new families stopped short of RegimeState/PositionUpdate.

### 3.3 Bus delivery order

`EventBus._handlers` is a `defaultdict(list)`; `publish` calls type-specific
handlers in registration order, then global handlers in registration order
(`bus/event_bus.py:36,65-68`). No superclass dispatch, no reordering — fully
deterministic **given subscription order**. Subscription order is established by
bootstrap construction sequence, which is documented as canonical
(`bootstrap.py:498` router-first; `:582-608` and `:1876-1891`
SensorRegistry→Aggregator→SignalEngine→…→Synchronizer→Composition→Tracker→
Metrics→Hazard). This is correct but the contract lives in statement order with
no explicit priority and no test asserting it (P1/P2 — see §8, §10).

Multiple subscribers per type (tie-break = registration order):
`Signal` → `Orchestrator._on_bus_signal` then `UniverseSynchronizer._on_signal`;
`SizedPositionIntent` → orchestrator, tracker, metrics;
`OrderRequest` → `_on_bus_hazard_order` then `HorizonMetricsCollector._on_order`.
All are independent or filtered, so cross-subscriber order is immaterial to
correctness; it is deterministic regardless.

### 3.4 Drain / flush order

- Signal buffer: cleared at tick start with a fresh/stale partition
  (`:2252-2279`); drained once at M4. Deterministic.
- `_pending_sized_intents`: FIFO `deque` drained in `_flush_pending_sized_intents`
  (`:1992`), each intent walking M5→M10; legs submitted in the risk engine's
  lex-sorted order (`:2073`). Deterministic.
- `_deferred_router_acks`: unrelated acks buffered and prepended on the next
  poll (`:5060-5076`). Deterministic.

---

## 4. Micro-SM audit (transitions vs §7.3)

The implemented table `_MICRO_TRANSITIONS` (`kernel/micro.py:100`) is a superset
of the §7.3 formal rules, adapted to the bus-driven Phase-2/3/4 pipeline (the
§7.3 `LEGACY_PATH` branch is retired; D.2). Mapping and findings:

- **Stage advancement is correct and cannot skip illegally.** `StateMachine.transition`
  raises `IllegalTransition` for any edge not in the table
  (`core/state_machine.py:148`), and construction validates enum completeness
  (`:93-101`). The happy-path walk M1→…→M10 and every early-exit (`no_signal`,
  `intent_no_action`, risk reject/flatten, blackout/SSR/locate guards) routes
  through `LOG_AND_METRICS → WAITING` via `_finalize_tick` — all legal edges.
- **The micro SM is descriptive, not prescriptive (P2, fragile-but-correct).**
  Sensors/signal-engine/composition run as **bus subscribers** during
  `bus.publish(quote)` (M1) and `bus.publish(tick)` inside
  `_dispatch_sensor_layer`; the `SENSOR_UPDATE`/`HORIZON_*`/`SIGNAL_GATE`/
  `CROSS_SECTIONAL` transitions are recorded **after** the work already executed
  (`:1903-1956`, "this transition is the authoritative record … sensors already
  ran"). The SM does not *sequence* those stages — the imperative body plus the
  subscription order do. This is fine for determinism but means a future bug
  that, say, moved a `bus.publish` would not be caught by any micro-SM legality
  check.
- **`SENSOR_UPDATE` is a one-way door (P2).** `_MICRO_TRANSITIONS[SENSOR_UPDATE]
  = {HORIZON_CHECK}` (`micro.py:120`) — it cannot reach `FEATURE_COMPUTE`. The
  M3 transition at `:2413` is legal from `STATE_UPDATE` (no sensors),
  `HORIZON_CHECK` (no boundary), `HORIZON_AGGREGATE`, `SIGNAL_GATE`, or
  `CROSS_SECTIONAL` — but **not** from `SENSOR_UPDATE`. It is safe only because
  `_dispatch_sensor_layer` always performs `SENSOR_UPDATE → HORIZON_CHECK`
  unconditionally in the same call (`:1912`) and never returns with the SM
  parked at `SENSOR_UPDATE`. Correct today; a refactor that early-returned
  between those two transitions would make the next M3 transition raise.
- **HorizonScheduler boundary math (§7.4) — pure integer, anchored.**
  `current_boundary = (t - session_open_ns) // h_ns`, tick ts =
  `session_open_ns + boundary*h_ns`, ticks emitted in `sorted(horizons)` order.
  Confirmed against the spec and `tests/determinism/test_horizon_tick_replay.py`.
  No off-by-one on the tick path: `_last_boundary` is strictly-greater gated.
  (Scheduler internals are sensor-layer-owned; the orchestrator only publishes
  what it returns — `:1922-1923`, trade path `:1877-1878`.)
- **UniverseSynchronizer barrier (§7.5).** Barrier close is the UNIVERSE-scope
  tick, not "all symbols reported"; emission is sorted
  `(boundary_ts, alpha_id, horizon)` and symbol-sorted before hashing
  (per glossary + §12.3). The orchestrator buffers the resulting intents into a
  FIFO deque, so varying symbol report order cannot reorder execution.
- **Macro SM.** `BACKTEST_MODE` has no edge to `RISK_LOCKDOWN`
  (`kernel/macro.py:74`); the orchestrator simulates the flatten instead and
  uses `macro.can_transition(RISK_LOCKDOWN)` to branch (`:2599,2793`). `SHUTDOWN`
  is terminal (`macro.py:107`). Consistent with the spec.

---

## 5. Single-writer & layer-separation audit (Inv-7, Inv-8)

### 5.1 Writer-per-event-type inventory

| Event | Publisher(s) | Single writer? |
|---|---|---|
| `RegimeState` | `_update_regime` (`:3517`) | **Yes** |
| `RegimeHazardSpike` | `_maybe_publish_hazard_spike` (`:3567`) | **Yes** |
| `HorizonTick` | orchestrator quote/trade path (`:1923,1878`) | **Yes** |
| `SensorReading` | `SensorRegistry` | **Yes** (sensor layer) |
| `HorizonFeatureSnapshot` | `HorizonAggregator` | **Yes** |
| `CrossSectionalContext` | `UniverseSynchronizer` | **Yes** |
| `SizedPositionIntent` | `CompositionEngine` | **Yes** |
| `PositionUpdate` | `_reconcile_fills` (`:5737`) | **Yes** |
| `Signal` | `HorizonSignalEngine` **+ orchestrator re-publish** (`:2484`) | **No — echo** (§5.3) |
| `OrderRequest` | orchestrator (5 paths) + `HazardExitController` | **Partitioned** by reason/source_layer (§5.4) |
| `MetricEvent`,`Alert`,`StateTransition` | many | By design (cross-cutting) |

### 5.2 Hidden global state

None on the tick path. All mutable state is instance state (`self._…`); the six
`SequenceGenerator`s are per-instance (`:627,655-666`, asserted distinct by
`test_legacy_sequence_isolation.py:73`). Module-level names are immutable
constants (`_TERMINAL_ORDER_STATES`/`_ENTRY_OPENING_INTENTS`/
`_FORCED_MARKET_EXIT_STRATEGIES` are `frozenset`; correlation-ID strings) — with
the single exception `_FORCED_EXIT_PANIC_REASON: dict` (`:316`), read-only in
practice (`.get()` at `:4793`). No singletons survive across replays; a fresh
`Orchestrator` is built per `build_platform`.

### 5.3 Signal echo (P1, fragile-but-correct)

`_process_tick_inner` re-publishes the selected signal at `:2484`. For a
**bus-arbitrated** winner this is a second publish of an event
`HorizonSignalEngine` already emitted; for a **synthetic** stop/session-flat
signal it is the only publish (correct and necessary). The duplicate reaches
`UniverseSynchronizer._on_signal` (ignored — a standalone winner is not in any
PORTFOLIO universe), `HorizonMetricsCollector`, and `_on_bus_signal` (re-buffered
with `_quote_tick_in_flight=True`, so not marked carry-over → evicted as STALE
next tick, `:2256-2265`). Net: no execution effect, but Signal-stream observers
double-count the arbitrated winner. Because the Level-2 Signal hash is computed
without the orchestrator (§9), this echo is invisible to parity but real on a
live/integration bus.

### 5.4 OrderRequest filter-based single-consumer (P1, fragile-but-correct)

The orchestrator both publishes `OrderRequest` (M7 `:3011`; PORTFOLIO legs
`:2081,2135`; reverse; emergency flatten `:3719`; working-exit fallback `:5290`)
and subscribes to it via `_on_bus_hazard_order` (`:949`). Re-entrant delivery is
contained by a tight filter: `source_layer == "RISK"` **and**
`reason ∈ {HAZARD_SPIKE, HARD_EXIT_AGE}` (`:6233-6235`), a signature only
`HazardExitController` produces, plus an idempotency set
(`_hazard_submitted_order_ids`, `:6245`). Verified no orchestrator-published
order matches the combination. This is correct but relies on an implicit
namespace convention rather than a structural single-writer guarantee.

### 5.5 Cross-layer leakage

The orchestrator consumes typed events off the bus rather than reaching into
layer internals, with two pragmatic exceptions, both duck-typed and guarded:
`getattr(self._risk_engine, "refresh_high_water_mark"/"record_fill", None)`
(`:2356,5677`) and `getattr(self._regime_engine, "discriminability_for_symbol",
…)` (`:3486`). These are capability probes on injected protocols, not imports of
layer internals — acceptable. No SENSOR/SIGNAL/PORTFOLIO module is imported into
the kernel for direct call; all interaction is via the typed bus.

---

## 6. Clock & causality audit (Inv-6, Inv-10)

- **Clock discipline (clean).** Every kernel timestamp is `self._clock.now_ns()`
  or a carried event ns. `grep` for `datetime.now`/`time.time`/`perf_counter` in
  `kernel/` returns only `time.perf_counter_ns()` at `:2232,2446,2448,2589,2591,
  3055,5198,5212` — all latency deltas that feed MetricEvent histograms or
  `PaperSessionRecorder.record_timing`, neither of which is a parity-hashed
  stream. `signal_order_trace.py:43` uses `datetime.fromtimestamp` to *render* an
  existing ns value as an ET string (observability), not to read wall time.
  `SimulatedClock.set_time` rejects backward movement (`core/clock.py:46`);
  `WallClock` (`:21`) is selected only for PAPER/LIVE (`bootstrap.py:781`).
- **Causality (clean on the traced path).** Tracing one quote M1→M10: M2 reads
  the current quote's posterior; sensors/aggregator/signal-engine consume only
  events already published ≤ this quote's ts; the router drain at `:2384`
  reconciles fills the router already produced from prior/equal-ts quotes; M5/M6
  read `self._positions` as mutated by those drains. No stage reads an event with
  ts > sim-time. HorizonTick carries the boundary's theoretical ts, not the
  triggering event's (§7.4), so a late trigger does not leak a future timestamp.
- **Processing delay** is modeled in the `ExecutionBackend` (fill/market-data
  latency ns threaded through `_create_backend`, `bootstrap.py:479-490`), not in
  the kernel — consistent with the architecture.
- **Coverage:** `tests/causality/test_anti_lookahead.py` validates the seams —
  EventLog rejects backward exchange ts (`:139`), ReplayFeed rejects trade-before-
  quote at equal ts (`:145`), fill@T immune to a later quote (`:161`), a prefix
  ack stream is immune to an appended future quote (`:186`), and a boundary
  snapshot excludes a future reading processed early (`:297`). These exercise the
  components, not the full orchestrator (see §10).

---

## 7. Shutdown / drain / idle audit

- **Shutdown (`:1701`).** Order: final `_drain_async_fills("shutdown")` (`:1733`)
  → checkpoint snapshots → resolve `CANCEL_REQUESTED → CANCELLED` over
  `list(_active_orders.items())` (insertion order, `:1737`) → prune → emit a
  pending-orders Alert if any non-terminal remain (`:1748-1768`) → macro
  `SHUTDOWN` → `metrics.flush()`. Deterministic; no events dropped or reordered
  (the final drain reconciles in `poll_acks()` order).
- **Idle tick (`:1803`).** `_run_pipeline` dispatches `IdleTick` to
  `_drain_async_fills` only — **no** micro-SM transition, **no** `bus.publish`,
  **no** EventLog append. The docstring and `macro.py` note that BACKTEST feeds
  never emit `IdleTick` (`:1792`), so replay ordering is untouched by idle
  handling (Inv-A). In PAPER/LIVE the idle drain reconciles broker-pushed fills
  between frames — a parity-irrelevant mode (wall-clock).
- **Tick-failure recovery (`:2171`).** On any tick exception: micro `reset()` to
  M0, clear `_pending_sized_intents` (`:2191`), emit a counter MetricEvent, then
  macro→DEGRADED; if the DEGRADED transition is vetoed, set
  `_pipeline_abort_requested` so `_run_pipeline` raises rather than silently
  continuing (`:1810`). Fail-safe and deterministic.

---

## 8. Bootstrap & mode-parity audit (Inv-9)

`build_platform` (`bootstrap.py:207`) constructs one component graph. The
component-graph **diff across modes** is:

| Concern | BACKTEST | PAPER / LIVE | On tick-decision path? |
|---|---|---|---|
| Clock | `SimulatedClock` (`:781`) | `WallClock` | Yes — but inherent to sim vs live; the second sanctioned divergence alongside `ExecutionBackend` |
| `ExecutionBackend` | `ReplayFeed`+`Backtest/PassiveLimit` router (`:986-1037`) | `MassiveLiveFeed`+`IBOrderRouter` | Yes — the sanctioned divergence |
| `NBBOQuote`→router sub | wired (`:497-498`, router present) | skipped (IB pushes async; `backtest_router=None`) | Behind backend abstraction |
| Normalizer | usually `None` | built for DataHealth gating (`:464-473`) | Gate only |
| EventLog order guard | strict (`enforce_market_order=True`) | relaxed (`:291-295`) | Ingestion guard, not decision |
| `registry_clock` | `None` → lifecycle/ledger off (`:313`) | `clock` | No — ledger is forensic-only |
| `metric_collector._store_raw_events` | `False` (`:563`) | `True` | Observability only |
| `warn_on_inert_entry_gates` | `False` | `True` (`:426`) | Warning only |

The **core decision graph is mode-independent**: sensors, scheduler, aggregator,
`HorizonSignalEngine`, composition, `BasicRiskEngine` (+`AlphaBudgetRiskWrapper`),
`HazardExitController`, sizer, translator, position manager are constructed
identically regardless of mode (`:500-733`). This satisfies Inv-9: replayable
divergence is confined to the clock and the `ExecutionBackend`.

- **Single-writer wiring is mode-invariant.** Exactly one publisher per event
  type is wired regardless of mode (§5.1); the per-family sequence generators are
  created once and threaded into both the layer components and the orchestrator
  (`:568-575,591,646,708-713`).
- **Construction determinism.** The graph is built by a fixed statement sequence;
  no dict/import iteration drives runtime ordering. The two construction-time
  sets (`universe`, `horizons` in `_create_composition_layer`, `:1917-1921`) are
  consumed only after sorting downstream (scheduler `sorted(horizons)`;
  synchronizer symbol-sorted emission), so their unordered construction does not
  leak. `_create_hazard_exit_controller` sorts candidates by `alpha_id` before
  registering policies (`:2099`) and sorts the fallback universe (`:2083`).
- **Conditional subsystems fail safe.** Composition → all-`None` with no
  PORTFOLIO alpha (`:1902`); hazard controller → `None` with no opt-in (`:2090`,
  so no `Trade` subscription in non-hazard deployments — Inv-A); promotion ledger
  only when `promotion_ledger_path` set (`:314`). Each absence leaves the
  orchestrator's optional ctor args unset and the short path intact.
- **`registry_clock=None` confirmed inert.** It is passed only to `AlphaRegistry`
  for lifecycle-transition timestamps / ledger writes (`:329-333`); the registry
  is sealed before `boot()` and never consulted per-tick for decisions, so the
  ledger/forensic path stays off the hot path and does not perturb replay.
- **Bus subscription order is the one fragility** (P1): the canonical handler
  order is achieved purely by *constructing components in order*
  (`:582-608,1876-1891`). No explicit priority; no test asserts the order. The
  `process entry shim` (`src/feelies/__main__.py`) is a 16-line delegate to the
  read-only CLI — no determinism surface.

---

## 9. Parity-hash coupling map

Each locked baseline (`tests/determinism/parity_manifest.py:84`) is computed by
driving its **leaf component(s)** on a bare `EventBus` and hashing the captured
stream — **none instantiates `Orchestrator`.** Consequence: each hash is coupled
to its component's internal ordering and its **isolated** sequence generator,
and to nothing in the kernel.

| Hash | Driven by (no orchestrator) | Ordering assumption it locks | Kernel `_seq`/micro/drain coupling |
|---|---|---|---|
| L1 SensorReading (`test_sensor_reading_replay`) | `SensorRegistry` | registry fan-out + `_sensor_seq` | none |
| L1 v0.3 SensorReading (`test_v03_sensor_replay`) | sensors | sensor compute determinism | none |
| L2 HorizonTick (`test_horizon_tick_replay`) | `HorizonScheduler` | `sorted(horizons)` integer math + `_horizon_seq` | none |
| L2 Signal (`test_signal_replay:109`) | registry+scheduler+aggregator+engine | engine eval order + `_signal_seq` | none; **echo at `:2484` invisible** |
| L3 HorizonFeatureSnapshot (`…snapshot_replay`) | aggregator | `sorted(feature_id)` + `_snapshot_seq` | none |
| L3 SizedPositionIntent off/on (`test_sized_intent[_with_decay]`) | composition engine | synchronizer sorted emission | none; **`_flush` order untested** |
| L4 PORTFOLIO order (`test_portfolio_order_replay:62`) | `BasicRiskEngine.check_sized_intent` | lex-sorted legs + `derive_order_id` | none; **`_filter_portfolio_orders_for_pending_conflicts` untested** |
| L4 hazard exit (`test_hazard_exit_replay`) | `HazardExitController` | SHA-256 order_id + `_hazard_seq` | none; **`_on_bus_hazard_order` bridge untested** |
| L5 RegimeHazardSpike (`test_regime_hazard_replay`) | detector | pure 2-state function + `_hazard_seq` | none |
| L6 RegimeState (`test_regime_state_replay:47`) | `HMM3StateFractional` | posterior determinism; **test-supplied `sequence`** | none; **`_seq` interleaving untested** |
| market_fill_acks (`test_market_fill_replay:63`) | `BacktestOrderRouter` | fill-model economics | none |

**Net:** the assumptions that *would* matter if these ran through the
orchestrator — bus-subscriber registration order (could move L2/L3 events),
shared-`_seq` interleaving (would set RegimeState/PositionUpdate `sequence`),
`_pending_sized_intents` drain order, and the `_distribute_fill_to_strategies`
frozenset order (§3.1) — are **uncoupled from every locked hash**. A
kernel-introduced ordering regression would pass the determinism suite.

---

## 10. Test gap matrix

| Invariant / property | Covered | Partial | Missing |
|---|---|---|---|
| Deterministic iteration on tick path | sorted legs (`test_portfolio_order_replay:140`); per-family seq isolation (`test_legacy_sequence_isolation`) | — | **frozenset order in `_distribute_fill_to_strategies` (§3.1) — untested & unmasked** |
| Sequence allocation = f(log) | per-family isolation unit test | leaf hashes use isolated generators | **orchestrator `_seq` interleaving of RegimeState/PositionUpdate/StateTransition/Metric/Alert — no hash** |
| Bus delivery order | — | implied by leaf wiring | **no test asserts the canonical subscription order (§3.3, §8)** |
| Micro-stage ordering | `tests/kernel/test_micro*` (table legality, properties) | — | no full-tick property test that the M-stage *event sequence* is invariant under sparse/idle ticks through the orchestrator |
| Single-writer per event type | implicit (one publisher wired) | — | **no assertion that exactly one writer exists per parity event; Signal echo (§5.3) undetected** |
| Clock discipline (Inv-10) | ruff DTZ; `SimulatedClock` backward guard | — | no test that perf_counter values never reach a parity stream |
| Causality (Inv-6) | `test_anti_lookahead` at component seams | — | no full-orchestrator anti-lookahead replay |
| Mode parity (Inv-9) | `tests/bootstrap/*` wiring tests | backend-swap wiring | no test asserting the BACKTEST/PAPER decision graph is identical except clock+backend |

### Proposed minimal new tests (specs only)

1. **Iteration-order fuzz under fixed log.** Run a fixed multi-alpha,
   shared-symbol fixture through `Orchestrator` twice under two different
   `PYTHONHASHSEED` values (e.g. `0` and `1`) forcing the
   `_distribute_fill_to_strategies` fallback (no FillLedger record); assert
   identical `_strategy_positions` and identical emitted `OrderRequest` stream.
   This fails today and passes after `sorted(strategy_ids())`.
2. **Single-writer assertion.** Subscribe a counting `subscribe_all` recorder to
   the orchestrator bus over a fixture; assert each of {RegimeState, HorizonTick,
   PositionUpdate, SizedPositionIntent, CrossSectionalContext} has exactly one
   distinct producer call-site (or, pragmatically, that no two identical
   `(type, sequence)` pairs appear) and that no `Signal` `(sequence)` appears
   twice — which would catch the `:2484` echo.
3. **Micro-ordering property.** Property test (hypothesis) over random sparse
   quote/trade/idle interleavings: assert the orchestrator's micro
   `StateTransition` `to_state` sequence per quote tick is a legal walk and that
   adding interleaved `Trade`/`IdleTick` events does not change the
   quote-tick decision-event subsequence.
4. **Orchestrator-level parity hash.** Add one hash over the full kernel bus
   event stream (filtered to the parity event types, with `sequence` included)
   produced by `build_platform(BACKTEST)` + `run_backtest()` on the canonical
   fixture, to actually couple the locked baselines to kernel ordering (closes §9).

---

## 11. Prioritized backlog

| # | Tier | Effort | Component | `file:line` | One-sentence fix | Determinism impact |
|---|---|---|---|---|---|---|
| 1 | **P0** | S | `_distribute_fill_to_strategies` | `orchestrator.py:5862` (+ `strategy_position_store.py:201`) | `sorted(self._strategy_positions.strategy_ids())` before the rounding loop | Removes the only set-iteration-order dependency on the tick path; makes per-alpha fill split seed-independent |
| 2 | **P1** | M | determinism suite | `tests/determinism/*` | Add an orchestrator-level parity hash (gap-test #4) | Couples locked baselines to kernel `_seq`/micro/drain ordering so a kernel regression is caught |
| 3 | **P1** | S | enforcement | `pyproject.toml` / new `conftest.py` | Pin `PYTHONHASHSEED=0` for the test session (and document it), matching §12.5's claim | Makes the documented set/hash mitigation real in-repo; backstops #1 |
| 4 | **P1** | S | Signal echo | `orchestrator.py:2484` | Re-publish only synthetic stop/session signals; skip re-publishing bus-arbitrated winners (or route via a distinct decision-event type) | Restores single-writer for `Signal`; removes observability double-count |
| 5 | **P1** | S | OrderRequest bridge | `orchestrator.py:6231-6235` | Assert/centralise the hazard `(source_layer, reason)` signature as a typed constant shared with `HazardExitController` and add a guard test | Hardens the filter-based single-consumer against future order classes |
| 6 | **P1** | S | bus subscription order | `bootstrap.py:498,582-608,1876-1891` | Add a test that asserts the canonical NBBOQuote/Signal/HorizonTick handler order after `build_platform` | Pins delivery order against a construction-order refactor |
| 7 | **P1/P2** | M | shared `_seq` coupling | `orchestrator.py:3496,5741` vs `5944` | Consider a dedicated `_regime_seq`/`_position_seq` (mirroring the per-family pattern) so parity events decouple from Metric/Alert/StateTransition volume | Reduces fragility of RegimeState/PositionUpdate `sequence` under observability changes |
| 8 | **P2** | S | micro contract | `micro.py:120`, `orchestrator.py:1903-1956` | Document (and test) that `SENSOR_UPDATE` must always advance to `HORIZON_CHECK` in `_dispatch_sensor_layer`; note the SM is a descriptive record | Prevents a future early-return from stranding the SM and raising at M3 |
| 9 | **P2** | S | style | `orchestrator.py:316` | Wrap `_FORCED_EXIT_PANIC_REASON` in `MappingProxyType` (or annotate `Final`) | Removes the lone module-level mutable; defensive only |

---

*Distinctions used above: **implementation bug** (#1); **fragile-but-correct**
(#4, #5, #6, #7, #8 — correct today, brittle under change); **intentional
design** (mode wiring, per-family generators, clock/backend divergence, the
leaf-driven parity hashes — flagged where the design leaves a coverage hole).*

---

## 12. Remediation — 2026-06-24

Applied in the same PR after the audit, at the maintainer's request to "fix the
verified P0, P1". Regression sweep (`tests/kernel tests/bus tests/core
tests/bootstrap tests/risk tests/determinism tests/causality` + the
Phase-4 / hazard / mixed-mechanism / cross-sectional integration e2e tests):
**839 passed**; `ruff` and strict `mypy` clean on the changed modules.

| # | Tier | Status | What changed |
|---|---|---|---|
| 1 | P0 | **Fixed** | `_distribute_fill_to_strategies` now `sorted(self._strategy_positions.strategy_ids())` (`orchestrator.py`), removing the `frozenset`-iteration dependency on the M9 path. New proof test asserts the tie-break +1 lands on the lexicographically-first strategy id. |
| 2 | P1 | **Fixed** | `tests/determinism/test_orchestrator_replay.py` runs the **full** `build_platform` + `run_backtest` and locks the orchestrator-produced Signal / SizedPositionIntent / OrderRequest / PositionUpdate streams (two-replays determinism + host-pinned baseline + no-false-empty guard) — the first parity coverage that exercises kernel `_seq`/drain ordering. |
| 3 | P1 | **Partial (by design)** | `conftest.py` surfaces `PYTHONHASHSEED` in the run header and warns when it is not `0`. A hard `os.execv` re-exec pin was implemented then **rejected** — it corrupts pytest's output capture (the session ran but emitted nothing). True enforcement needs the env var at launch (`PYTHONHASHSEED=0 uv run pytest`); since #1 removed the tick-path set-order dependency, the seed pin is now defensive only. |
| 4 | P1 | **Fixed** | The M4 re-publish (`orchestrator.py`) now emits a `Signal` only for synthetic forced-exit strategies (`_FORCED_MARKET_EXIT_STRATEGIES`); the bus-arbitrated alpha winner is no longer echoed, restoring `HorizonSignalEngine` as the sole writer of alpha `Signal`s. Verified no consumer relied on the echo. |
| 5 | P1 | **Fixed** | The hazard `(source_layer, reason)` signature is centralized as `HAZARD_EXIT_SOURCE_LAYER` / `HAZARD_EXIT_REASONS` in `risk/hazard_exit.py` (the sole writer); the kernel bridge imports them instead of re-declaring literals. Guard test asserts the kernel references the *same* objects (identity) and that every reason in the shared set is routed. |
| 6 | P1 | **Fixed** | `tests/bootstrap/test_bus_subscription_order.py` pins the canonical handler order for the determinism-critical families. (It also corrected a detail in §3.3/§8 of this audit: because the composition/observability layer is constructed **before** the `Orchestrator`, the orchestrator's shared-event handlers register *last*, not first — immaterial to correctness, now locked.) |
| 7 | P1/P2 | **Declined (won't fix)** | Dedicated `_regime_seq` / `_position_seq` was evaluated and rejected. It would delete the single global emission-ordering provenance the shared `_seq` provides, serves no Inv-A purpose (RegimeState/PositionUpdate are *original* families, not newly-added ones for which Inv-A reserves isolated counters), and the coupling it targets is already deterministic and now locked by #2. Net-negative; the shared `_seq` is retained. |
| 8, 9 | P2 | Deferred | Outside the requested P0/P1 scope. |

Behaviour impact: all changes are behaviour-preserving except #1 (makes a
previously hash-seed-dependent per-alpha fill split deterministic) and #4
(removes one redundant duplicate `Signal` publish). Neither alters orders, fills,
or PnL on the regression fixtures.
