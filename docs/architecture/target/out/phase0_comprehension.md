# PHASE 0 — Comprehension lock (D0)

**Pass 1 — code and measured evidence only.** No file under `docs/`, no `README`,
no `docs/reviews/` was read to produce anything below. Pass 2 has not been run;
D0.9 is therefore empty by construction.

**Status vocabulary:** `specified` / `implemented` / `conformance-tested` /
`open defect`. Evidence labels: `VERIFIED` (read the code) / `INFERRED` (derived
from what was read) / `ASSUMED` (not checkable — in D0.8).

## Evidence base

`tools/arch/measure.py all` was re-run at the start of this phase and reproduced
the committed evidence byte-for-byte (`git status` clean, no diff to
`tools/arch/evidence/*.json`). Its `CONFIG` block was **not** edited, per its own
instruction. Where its evidence proved insufficient, new scripts were added
under `tools/arch/` rather than changing the frozen measurement.

| Evidence file | Produced by | What it measures |
|---|---|---|
| `modules.json` | `measure.py modules` | 196 files, 43 197 sloc, per-file sloc / classes / functions |
| `imports.json` | `measure.py imports` | 159 modules, 609 internal edges, 2 cycles |
| `clock.json` | `measure.py clock` | 22 candidate wall-clock sites — **5 false positives, 12 false negatives** (see below) |
| `nondet.json` | `measure.py nondet` | 34 nondeterminism candidates |
| `bus.json` | `measure.py bus` | 48 publish / 32 subscribe call sites |
| `handlers.json` | `measure.py handlers` | 16 non-bus dispatch entry points |
| `gates.json` | `measure.py gates` | 153 guard-*named* functions, 1 silent except |
| `alphaleak.json` | `measure.py alphaleak` | 2 alpha-ID literals in `src/` |
| `contracts.json` | **new** `tools/arch/contracts.py` | Event closure, versioning, dispatch semantics, resolved publisher/subscriber sets |
| `coupling.json` | **new** `tools/arch/coupling.py` | Mode branches vs the `ExecutionBackend` seam, orchestrator collaborators, encapsulation breaks |
| `clockscan.json` | **new** `tools/arch/clockscan.py` | Complete clock scan incl. `*_ns` variants; delta against `clock.json` |
| `gatescan.json` | **new** `tools/arch/gatescan.py` | Gate *outcomes* by family; fail-quiet except handlers |
| `parityscan.json` | **new** `tools/arch/parityscan.py` | The field-level surface the determinism oracle actually hashes |
| — (stdout) | **new** `tools/arch/parity_coverage.py` | Per-event declared / hashed / unhashed field counts from `parityscan.json` |
| `inventory.json`, `inventory_table.md` | **new** `tools/arch/inventory.py` | Full 196-module inventory with declared responsibility |

`tools/arch/measure.py` has **no** `parity` subcommand (`all, modules, imports, clock,
nondet, bus, handlers, gates, alphaleak, discover, spotcheck`), so nothing in the
frozen harness measures the determinism surface — that gap is why
`tools/arch/parityscan.py` exists.

### Two defects in the pre-built evidence itself

`evidence/clock.json` is not a bound in either direction. `VERIFIED` against
`tools/arch/measure.py:71` (`CLOCK_CALLS`) and `tools/arch/measure.py:326` (the matcher):

- **12 false negatives.** `CLOCK_CALLS` lists `time.perf_counter` but not
  `perf_counter_ns`, and the matcher compares only the final dotted segment, so
  `time.perf_counter_ns()` matches nothing. All 12 missed sites are in the two
  hottest modules: 10 in `src/feelies/kernel/orchestrator.py` and 2 in
  `src/feelies/core/state_machine.py`. The under-report is concentrated exactly
  on the tick-critical path.
- **5 false positives.** `datetime.time(hour, minute)` is a *constructor*, not a
  clock read; it is counted as one at `src/feelies/core/session_clock.py:43`,
  `src/feelies/execution/moc_session.py:53`, `src/feelies/execution/moc_session.py:56`,
  `src/feelies/storage/reference/event_calendar/__init__.py:176` and
  `src/feelies/storage/reference/event_calendar/__init__.py:179`.

Corrected count from `evidence/clockscan.json`: **29 raw clock reads** (16
`time.monotonic`, 12 `time.perf_counter_ns`, 1 `time.time_ns`), plus 10
`datetime.fromtimestamp` conversions tracked separately because they convert a
timestamp the caller already holds.

---

## Findings requiring escalation

### E-1 — A specific `alpha_id` literal in platform config changes order routing by default. `open defect`.

`VERIFIED`:

```108:108:src/feelies/core/platform_config.py
    moc_strategy_ids: tuple[str, ...] = ("sig_moc_imbalance_v1",)
```

The same literal is the fallback in the YAML loader at
`src/feelies/core/platform_config.py:910`. It reaches execution semantics:
`src/feelies/kernel/orchestrator.py:876` copies it into `_moc_strategy_ids`, and
`src/feelies/kernel/orchestrator.py:3386` tests `strategy_id in self._moc_strategy_ids`
to set `OrderRequest.is_moc`, which diverts the order from the continuous book to
the closing auction (`src/feelies/core/events.py:288`).

Measured blast radius: **no file under `configs/` or `platform.yaml` sets
`moc_strategy_ids`** (grep over the repo returns hits only in `src/`, `tests/`,
`tools/` and `docs/`), so every deployment inherits the hardcoded default, and
`configs/bt_sig_moc_imbalance.yaml:14` loads that exact alpha.

Why this is escalated rather than filed as an inventory row: the coupling is a
*string literal*, so the failure mode on the routine action of versioning an
alpha (`..._v1` → `..._v2`) is silent. The alpha would move from closing-auction
to continuous-book execution with no gate, no alert, and no failing test —
a change in realised execution cost and in when exposure is actually taken. It
is not producing a wrong number for any config in the tree today; it is a live
violation of alpha-agnosticism with a quiet failure mode.

**Proposed containment (not applied — this phase does not fix):** change the
default to `()` so the behaviour must be requested by config, and make
`bootstrap` fail loudly when `moc_strategy_ids` names an `alpha_id` absent from
the loaded registry. `src/feelies/bootstrap.py:792` already branches on
`if not config.moc_strategy_ids:`, so an empty default is a supported state.
Note `tools/arch/measure.py:139` declares `LEAK_EXEMPT_FILES` empty "by design:
any entry here is an accepted defect" — this leak is currently unexempted and
unfixed, i.e. the check reports it and nothing consumes the report.

### E-2 — Fail-quiet exception handlers on decision paths. `open defect` (2 of 20 sites).

`evidence/gatescan.json` finds 20 `except` handlers whose body neither raises,
returns, nor logs. Eighteen are benign (parse fallbacks, `queue.Empty`,
`ImportError` capability probes). Two sit on decision paths:

| Site | Behaviour | Assessment |
|---|---|---|
| `src/feelies/composition/engine.py:388` | `except Exception: current_positions[s] = 0.0` — a failed per-strategy position lookup is silently reported as flat, with no log, metric or alert. Marked `# pragma: no cover`, so it is also untested. | `VERIFIED` fail-quiet. Exposure consequence is `INFERRED` and bounded: `SizedPositionIntent` carries a desired *book state* (`src/feelies/core/events.py:697`), and the per-leg delta is recomputed against the real store downstream, so the corrupted value distorts turnover/optimiser input rather than the target level. |
| `src/feelies/alpha/risk_wrapper.py:189` | `except KeyError: pass` — an `OrderRequest` whose `strategy_id` is not in the registry skips **all** per-alpha risk budgets and falls through to aggregate checks only. | `VERIFIED`. The comment states the intent ("Synthetic and net strategies use aggregate risk checks only"), but the direction on unknown input is *fewer* constraints, not more. Platform-level caps still apply, so this is fail-open-but-bounded, not unbounded. |

**Proposed containment:** emit a counter or `Alert` at both sites so the branch is
observable, and remove the `pragma: no cover` at the first so it is reachable in
test. No behaviour change is required to make either observable.

### Explicitly checked and *not* defective

Things CORE names as anti-patterns, checked directly, that hold:

- **Optimistic passive fill eligibility** (CORE §J). Both passive paths enforce
  the timing gate in *exchange* time: `src/feelies/execution/passive_limit_router.py:527`
  for quote-driven fills and `src/feelies/execution/passive_limit_router.py:242`
  for trade-driven queue drain. `implemented`.
- **Wall-clock on the tick path.** The 12 `perf_counter_ns` reads are known and
  bounded by an enforced allowlist with per-file justification at
  `tests/acceptance/test_no_walltime_outside_clock.py:31`, and a companion test
  at `tests/acceptance/test_no_walltime_outside_clock.py:96` fails on stale
  entries. They feed `_tick_timings` only, and `_finalize_tick` keeps them from
  consuming sequence numbers (D0.4 hop 42). `conformance-tested`.
- **Silent event drops under backpressure** (CORE §J). The one queue in the
  system counts drops, warns, and degrades `DataHealth` — see D0.7 §F.6.
  `implemented`.
- **A parity registry that can silently lose coverage.** The manifest is closed by
  two enforcing tests, including one that fails on a *stale* exemption. This is the
  only responsibility in Phase 0 that is enumerable from a single source — see
  D0.6. `conformance-tested`.

---

## D0.1 Module inventory

196 modules, 43 197 sloc, 551 module-level public symbols
(`evidence/inventory.json`). The **complete per-module table**, with each
module's declared responsibility taken from its docstring, is
`tools/arch/evidence/inventory_table.md` — 196 rows, generated, not transcribed.
Docstrings are the module's *declared* intent and are labelled as claims there;
where a docstring and behaviour disagree the disagreement is a finding, and the
ones found in this phase are recorded in D0.3–D0.6.

Exactly **1** module has no docstring (`evidence/inventory.json:modules_without_docstring`).

Package-level aggregate, sloc descending:

| package | files | sloc | share | public symbols |
|---|---|---|---|---|
| `kernel/` | 5 | 5095 | 11.8% | 8 |
| `alpha/` | 14 | 4652 | 10.8% | 53 |
| `execution/` | 23 | 4446 | 10.3% | 90 |
| `sensors/` | 26 | 3369 | 7.8% | 31 |
| `risk/` | 14 | 2585 | 6.0% | 34 |
| `promotion/` | 4 | 2384 | 5.5% | 41 |
| `harness/` | 6 | 2332 | 5.4% | 45 |
| `core/` | 12 | 2181 | 5.0% | 67 |
| `ingestion/` | 9 | 1898 | 4.4% | 17 |
| `composition/` | 8 | 1812 | 4.2% | 17 |
| `(root)` | 3 | 1661 | 3.8% | 3 |
| `storage/` | 16 | 1366 | 3.2% | 30 |
| `research/` | 5 | 1355 | 3.1% | 32 |
| `signals/` | 4 | 1318 | 3.1% | 11 |
| `features/` | 8 | 1236 | 2.9% | 12 |
| `cli/` | 7 | 1117 | 2.6% | 7 |
| `forensics/` | 8 | 1036 | 2.4% | 20 |
| `services/` | 4 | 1023 | 2.4% | 8 |
| `monitoring/` | 7 | 786 | 1.8% | 12 |
| `portfolio/` | 6 | 765 | 1.8% | 8 |
| `broker/` | 5 | 724 | 1.7% | 4 |
| `bus/` | 2 | 56 | 0.1% | 1 |

21 packages plus `(root)` (`src/feelies/bootstrap.py`, `src/feelies/__init__.py`, `src/feelies/__main__.py`), matching
the layout CORE §B asserts. Two structural facts worth carrying forward:

- **One module is 11.8% of the platform.** `src/feelies/kernel/orchestrator.py`
  is 4778 sloc with ~120 methods and exports **1** public symbol.
- **The bus is 56 sloc.** The narrowest contract in the system is also the one
  the tick path mostly does not use (D0.4).

### Import cycles — 2, `VERIFIED` (`evidence/imports.json`)

| cycle | members |
|---|---|
| 1 | `feelies.cli` → `feelies.cli.main` |
| 2 | `feelies.core.inv12_stress` → `feelies.core.platform_config` → `feelies.promotion.evidence` |

Cycle 2 crosses a layer boundary: `core/` (kernel, per CORE §E cross-cutting)
imports `promotion/` (engine 5, declared cold and off the tick path). `INFERRED`:
importing engine 5 from `core/` means the governance package is in the import
closure of anything that loads platform config.

---

## D0.2 Engine mapping

Mapping is by *implemented* responsibility, not by directory name. `tools/arch/measure.py`'s
`ENGINE_HINTS` buckets are a starting point and are corrected here.

| Package / module | Engine(s) | Ownership | Basis |
|---|---|---|---|
| `ingestion/` | 1 | **Clear** | Wire→canonical normalization, halt codes, dedup, feed-interruption notification (`src/feelies/ingestion/massive_normalizer.py`, `src/feelies/ingestion/data_integrity.py`) |
| `storage/` | 1, 2, + §F.2 | **Mixed** | Event log / cache / resequencing (1) with `src/feelies/storage/feature_snapshot.py` (2) and `storage/reference/` corporate actions, sector map, factor loadings, event calendar (§F.2 reference data) in one package |
| `sensors/` | 2 | **Clear** | 26 modules; incremental L1 observers + `HorizonScheduler` |
| `features/` | 2 | **Clear** | `HorizonAggregator` → `HorizonFeatureSnapshot` |
| `services/` | 3 | **Clear** | `src/feelies/services/regime_engine.py`, `src/feelies/services/regime_hazard_detector.py`, `src/feelies/services/regime_state_cache.py`. The cache is the declared single read path (`src/feelies/bootstrap.py:289`) |
| `signals/` | 4 | **Clear** | `HorizonSignalEngine` + AST regime-gate DSL |
| `alpha/` | 5 (+4, 6, 7, 8 fragments) | **Mixed** | Governance proper is `src/feelies/alpha/loader.py`, `src/feelies/alpha/registry.py`, `src/feelies/alpha/layer_validator.py`, `src/feelies/alpha/discovery.py`, `src/feelies/alpha/dependency_graph.py`, `src/feelies/alpha/validation.py`. But `src/feelies/alpha/signal_layer_module.py` / `src/feelies/alpha/portfolio_layer_module.py` wrap engine-4/6 execution, `src/feelies/alpha/arbitration.py` selects between signals (engine 6 behaviour), `src/feelies/alpha/fill_attribution.py` is engine-7 accounting, and `src/feelies/alpha/risk_wrapper.py` is an engine-8 veto wrapper |
| `promotion/` | 5 | **Clear** | Lifecycle, evidence, append-only ledger; cold |
| `composition/` | 6 | **Clear** | Synchronizer fan-in, ranker, neutralizer, sector matcher, turnover optimizer |
| `portfolio/` | 7 | **Clear** | Position stores, `src/feelies/portfolio/lot_ledger.py`, `src/feelies/portfolio/strategy_position_store.py`. `src/feelies/portfolio/cross_sectional_tracker.py` is a bus observer feeding forensics — engine 7/12 boundary but read-only |
| `risk/` | 8 (+9) | **Mixed** | Engine 8: `src/feelies/risk/basic_risk.py`, `src/feelies/risk/buying_power.py`, `src/feelies/risk/escalation.py`, sizers. Engine 9 by responsibility: `src/feelies/risk/sized_intent_orders.py` turns an approved target into per-leg orders, and the four exit authors (`src/feelies/risk/stop_exit.py`, `src/feelies/risk/hazard_exit.py`, `src/feelies/risk/exit_composer.py`, `src/feelies/risk/deferral_cap.py`) emit `OrderRequest` directly |
| `execution/` | 9 + 10 | **Mixed by design** | CORE §B already states both engines live here. `src/feelies/execution/order_admission.py`, `intent*.py`, `src/feelies/execution/portfolio_netter.py`, `src/feelies/execution/min_cost_policy.py` are policy (9); routers, fill models, session/MOC constraints, backends are mechanics (10) |
| `broker/ib/` | 10 | **Clear** | The live adapter half of the mode seam |
| `monitoring/` | 11 | **Clear** | Metrics, alerting, kill switch, health, paper session recorder |
| `forensics/` | 12 (+5 write) | **Mixed** | Attribution, decay, calibration are engine 12. `src/feelies/forensics/cost_circuit_breaker.py:159` drives `LIVE → QUARANTINED`, an engine-5 state write performed from engine-12 code — this is CORE §G.9's closed loop, but the write direction crosses the engine boundary |
| `research/` | 12 | **Clear** | CPCV, DSR, forward IC, decouple gates |
| `harness/` | 12 | **Clear** | Backtest prep, runner, report, JSONL |
| `core/`, `bus/`, `src/feelies/kernel/macro.py`, `src/feelies/kernel/micro.py`, `src/feelies/bootstrap.py` | Kernel (cross-cutting) | **Clear** | Contracts, clock, state-machine framework, composition root |
| `cli/` | Kernel (thin) | **Clear** | 7 modules, 1117 sloc, delegates |
| **`src/feelies/kernel/orchestrator.py`** | **1, 2, 3, 7, 8, 9, 10, 11** | **Misplaced** | See below |

### The orchestrator's ownership span, `VERIFIED` by symbol

CORE §E requires the kernel to own "no trading-domain calculation".
`src/feelies/kernel/orchestrator.py` contains, by named method:

| Engine | Evidence in `src/feelies/kernel/orchestrator.py` |
|---|---|
| 1 (market data) | `_update_halt_state:5014`, `_update_ssr_state:5089`, `_data_health_blocks_trading:5263`, `_emit_symbol_halted:5063`, `_verify_data_integrity:5379` |
| 2 (state/feature) | `_restore_feature_snapshots:5423`, `_checkpoint_feature_snapshots:5454` |
| 3 (regime) | `_calibrate_regime_engine:2335`, `_update_regime:2432`, `_maybe_publish_hazard_spike:2501`, `_regime_label_for:4556`, `_checkpoint_regime_snapshot:5460` |
| 7 (accounting) | `_reconcile_fills:4229`, `_distribute_fill_to_strategies:4577`, `_record_fill_attribution:4057` |
| 8 (risk/capital) | `_compute_target_quantity:2718`, `_escalate_risk:2530`, `_emergency_flatten_all:2601`, `_maybe_flip_buying_power_at_rth_close:782`, `_reset_buying_power_phase_for_session:814` |
| 9 (execution policy) | `_plan_for_signal:2814`, `_try_build_order_from_intent:3278`, `_resolve_order_route:3371`, `_filter_portfolio_orders_for_admission:3505`, `_execute_reverse:2984`, `_edge_clears_round_trip_cost:2184`, `_signal_passes_edge_cost_gate:2226`, `_round_trip_cost_bps:2266`, `_reversal_passes_combined_edge_gate:2295` |
| 10 (mechanics) | `_submit_tracked_order:3831`, `_poll_order_router_acks:3793`, `_apply_ack_to_order:4103`, `_transition_order:4086`, `_drain_async_fills:3936`, `cancel_order:3438` |
| 11 (observability) | 13 `_emit_*_alert` / `_publish_alert` methods |

`INFERRED`: the cost-vs-edge gate (`_edge_clears_round_trip_cost:2184`,
`_round_trip_cost_bps:2266`) is trading-domain arithmetic performed in the
kernel. This is the concrete instance of CORE §J's "god orchestrator".

### Unowned by any engine

| Responsibility | Where it currently lives | Note |
|---|---|---|
| Reference/static data (corporate actions, sector map, factor loadings, event calendar) | `storage/reference/` (4 sub-packages) | Consumed by engines 6, 7, 10 and by `bootstrap`; owned by none. Feeds §F.2 |
| Signal→order forensic trace | `src/feelies/kernel/signal_order_trace.py` | Engine 12 output produced inside the kernel; sink injected at `src/feelies/bootstrap.py:564` |
| Universe | split — see D0.7 §F.1 | `Unowned` |

---

## D0.3 Contract inventory

### Event closure — 21 types, all in one module

`evidence/contracts.json`: **21** classes derive transitively from `Event`, and
`event_classes_outside_core_events` is **empty** — every bus contract is declared
in `src/feelies/core/events.py`. All 21 are
`@dataclass(frozen=True, kw_only=True, slots=True)`; `non_frozen_event_classes`
is empty.

### C-1 — No contract carries a version. `open defect` vs CORE §C.11.

`events_with_version_field` is **`NONE`** across all 21 types. The base envelope
is exactly four fields (`src/feelies/core/events.py:49`): `timestamp_ns`,
`correlation_id`, `sequence`, `source_layer`. There is no `schema_version` and no
per-type version. `src/feelies/core/events.py:15` states the evolution policy in
prose — "All new types are strictly additive" — which is a convention, not an
enforced or recorded contract. Events are appended to a replayable log
(`src/feelies/kernel/orchestrator.py:1601`, `:1211`), so this is CORE §J's
"unversioned contracts persisted into a replayable event log", `VERIFIED`.

Note the one exception in spirit: `SensorReading` carries `sensor_version`
(`src/feelies/core/events.py:622`) and `HorizonFeatureSnapshot` carries
`feature_versions` (`:650`). Producer versioning exists; *schema* versioning does
not.

### C-2 — Dispatch is exact-type only. `implemented`, and load-bearing.

```65:68:src/feelies/bus/event_bus.py
        handlers = self._handlers.get(type(event))
        if handlers is not None:
            for handler in handlers:
                handler(event)
```

`exact_type_dispatch=True`, `subtype_dispatch=False`. A handler subscribed to a
base class receives nothing; there is no MRO walk and no `isinstance` check.
`INFERRED`: any future event hierarchy deeper than one level silently delivers
no events to a base-class subscriber. Delivery order is type-specific handlers in
registration order, then global handlers — so **subscriber registration order is
a determinism input**, and `bootstrap` treats it as one: six ordering comments in
`build_platform` state it explicitly (`src/feelies/bootstrap.py:355`, `:423`,
`:435`, `:446`, `:467`, `:1234`).

### C-3 — `subscribe_all` is dead public API. `open defect` (dead surface).

`call_site_counts` = `{'subscribe': 32, 'subscribe_all': 0, 'publish': 48}`.
`src/feelies/bus/event_bus.py:55` defines `subscribe_all` and the global-handler
list at `:37` and `:69` exists to serve it; nothing in `src/` calls it. One third
of the bus's public surface is unreachable, and the `_global_handlers` loop runs
on **every** `publish` on the tick path to iterate an always-empty list.

### Publisher / subscriber sets — fully resolved, 0 unresolved

`tools/arch/contracts.py` resolves each `publish` argument through constructor
calls, `dataclasses.replace` targets, local assignments, loop targets, and
cross-module return annotations; the 2 residual sites are hand-verified and
declared in `MANUAL_RESOLUTIONS`. 48 publish sites, 32 subscribe sites, all typed.

| Event | Publishers | Bus subscribers |
|---|---|---|
| `NBBOQuote` | `src/feelies/kernel/orchestrator.py:1634` | `src/feelies/bootstrap.py:353` (BACKTEST router only), `src/feelies/harness/backtest_runner.py:765`, `src/feelies/risk/stop_exit.py:172`, + dynamic (`src/feelies/sensors/registry.py:193`) |
| `Trade` | `src/feelies/kernel/orchestrator.py:1200`, `:1212` | `src/feelies/risk/deferral_cap.py:238`, `src/feelies/risk/hazard_exit.py:142`, + dynamic |
| `HorizonTick` | `src/feelies/kernel/orchestrator.py:1223`, `:1252` | `src/feelies/features/aggregator.py:253`, `src/feelies/composition/synchronizer.py:130` |
| `SensorReading` | `src/feelies/sensors/registry.py:291` | `src/feelies/features/aggregator.py:252`, `src/feelies/signals/horizon_engine.py:197` |
| `HorizonFeatureSnapshot` | `src/feelies/features/aggregator.py:347` | `src/feelies/signals/horizon_engine.py:198`, `src/feelies/composition/synchronizer.py:128` |
| `RegimeState` | `src/feelies/kernel/orchestrator.py:2476` | `src/feelies/services/regime_state_cache.py:54`, `src/feelies/signals/horizon_engine.py:196` |
| `RegimeHazardSpike` | `src/feelies/kernel/orchestrator.py:2515` | `src/feelies/risk/hazard_exit.py:141`, `src/feelies/monitoring/horizon_metrics.py:89` |
| `Signal` | `src/feelies/signals/horizon_engine.py:505` | `src/feelies/kernel/orchestrator.py:574`, `src/feelies/composition/synchronizer.py:129` |
| `SafetyStateChange` | `src/feelies/signals/horizon_engine.py:540` | `src/feelies/risk/exit_composer.py:289`, `src/feelies/risk/deferral_cap.py:237` |
| `CrossSectionalContext` | `src/feelies/composition/synchronizer.py:312` | `src/feelies/composition/engine.py:197`, `src/feelies/portfolio/cross_sectional_tracker.py:101`, `src/feelies/monitoring/horizon_metrics.py:87` |
| `SizedPositionIntent` | `src/feelies/composition/engine.py:276`, `:324` | `src/feelies/kernel/orchestrator.py:578`, `src/feelies/portfolio/cross_sectional_tracker.py:102`, `src/feelies/monitoring/horizon_metrics.py:88` |
| `OrderRequest` | `src/feelies/kernel/orchestrator.py:3223`, `src/feelies/risk/hazard_exit.py:253`, `src/feelies/risk/stop_exit.py:297`, `src/feelies/risk/deferral_cap.py:378`, `src/feelies/risk/exit_composer.py:486` | `src/feelies/kernel/orchestrator.py:585`, `src/feelies/monitoring/horizon_metrics.py:90` |
| `Alert` | `src/feelies/bootstrap.py:598`, `src/feelies/kernel/orchestrator.py:680`, `src/feelies/risk/basic_risk.py:366`, `:583`, `src/feelies/monitoring/horizon_metrics.py:322` | `src/feelies/kernel/orchestrator.py:563` |
| `MetricEvent` | `src/feelies/kernel/orchestrator.py:1484`, `:1569`, `:2114`, `:2143`, `src/feelies/monitoring/horizon_metrics.py:299` | `src/feelies/kernel/orchestrator.py:559`, `src/feelies/harness/backtest_runner.py:747` |
| **`RiskVerdict`** | `src/feelies/kernel/orchestrator.py:1774`, `:1903`, `:3032`, `:3174`, `:4939` | **none** |
| **`OrderAck`** | `src/feelies/kernel/orchestrator.py:3828` | **none static** (backtest-only, see C-4) |
| **`PositionUpdate`** | `src/feelies/kernel/orchestrator.py:4268`, `:4450` | **none static** (backtest-only) |
| **`StateTransition`** | `src/feelies/kernel/orchestrator.py:4696` | **none** |
| **`SymbolHalted`** | `src/feelies/kernel/orchestrator.py:5074` | **none** |
| **`KillSwitchActivation`** | `src/feelies/kernel/orchestrator.py:2585` | **none** |

### C-4 — Six event types are published to zero bus subscribers.

`published_never_subscribed` = `KillSwitchActivation`, `OrderAck`,
`PositionUpdate`, `RiskVerdict`, `StateTransition`, `SymbolHalted`.

Of these, `OrderAck` and `PositionUpdate` gain a consumer **only in backtest**,
via a dynamic subscription in the harness:

```218:225:src/feelies/harness/backtest_runner.py
    event_types: list[type[Event]] = [
        Alert,
        HorizonFeatureSnapshot,
        OrderAck,
        OrderRequest,
        PositionUpdate,
        Signal,
    ]
```

`VERIFIED`: four types — `KillSwitchActivation`, `RiskVerdict`,
`StateTransition`, `SymbolHalted` — have no consumer in any mode. Their docstrings
describe consumers that do not exist on the bus: `KillSwitchActivation` says
"published on the bus so all layers can react" (`src/feelies/core/events.py:416`)
and `SymbolHalted` says it "lets post-trade forensics reconstruct which fills
were suppressed" (`src/feelies/core/events.py:123`). Both are code-vs-docstring
disagreements, `VERIFIED` in code's favour. The kill switch is instead read
directly on the tick path (`src/feelies/kernel/orchestrator.py:1561`), so the
safety behaviour is present; the *event* is inert.

### C-5 — Two dynamic subscription sites make the subscriber set non-enumerable.

| Site | Keyed on |
|---|---|
| `src/feelies/sensors/registry.py:193` | `spec.subscribes_to` from each `SensorSpec` — the subscriber set for `NBBOQuote`/`Trade` is a function of loaded config |
| `src/feelies/harness/backtest_runner.py:246` | CLI flags (`_recorder_event_types`), and it reaches through `orchestrator._bus` — a private attribute |

`INFERRED`: CORE §G.5 wants every gate enumerable from a single source; the
subscriber graph is not statically enumerable today for these two.

### C-6 — The tick path bypasses the bus: 55 collaborators, 323 direct calls.

The bus docstring states the design (`src/feelies/bus/event_bus.py:7`): "The
critical tick-to-trade path uses direct method calls through the orchestrator for
maximum performance; the bus carries cross-cutting events". `VERIFIED` against
`evidence/coupling.json`: `src/feelies/kernel/orchestrator.py` makes **323** direct
`self._<attr>.<method>()` calls across **55** distinct injected collaborators.

| Collaborator | Direct call sites |
|---|---|
| `self._micro` | 42 |
| `self._clock` | 40 |
| `self._bus` | 36 |
| `self._macro` | 36 |
| `self._positions` | 23 |
| `self._seq` | 17 |
| `self._strategy_positions` | 13 |
| `self._risk_engine` | 7 |
| `self._risk_escalation` | 7 |
| `self._event_log` | 4 |
| `self._normalizer` | 4 |

So the typed-boundary invariant (CORE §C.3) holds for what crosses the bus, and
the majority of engine-to-engine traffic on the tick path does not cross it. The
enforcement point for those 323 calls is type annotations plus `mypy --strict`,
not a runtime boundary check.

### C-7 — Frozen events with mutable containers: 8 of 21.

| Event | Mutable fields |
|---|---|
| `SizedPositionIntent` | `target_positions`, `factor_exposures`, `mechanism_breakdown`, `disclosed_cost_total_bps_by_symbol` |
| `HorizonFeatureSnapshot` | `values`, `warm`, `stale`, `source_sensors`, `feature_versions` |
| `CrossSectionalContext` | `signals_by_symbol`, `signals_by_strategy_by_symbol`, `snapshots_by_symbol` |
| `Signal` | `metadata` |
| `RiskVerdict` | `constraints` |
| `Alert` | `context` |
| `MetricEvent` | `tags` |
| `StateTransition` | `metadata` |

`frozen=True` blocks rebinding, not in-place mutation of a `dict` reached through
a published event, and these events are unhashable as a result. This is disclosed
in the base docstring at `src/feelies/core/events.py:37`, which states the
convention ("Treat every event as read-only once published") and names tuples as
"the preferred shape for new schemas". `implemented` as convention; no runtime
enforcement. `evidence/contracts.json:events_with_mutable_container_fields`.

### C-8 — Mode branches outside the `ExecutionBackend` seam: 24. `open defect` vs CORE §C.4.

`evidence/coupling.json`: 27 matched branches, of which 24 test `OperatingMode`
(the other 3 are the alpha layer's unrelated `safety_exit_policy.mode` at
`src/feelies/alpha/layer_validator.py:1163`, `:1171`,
`src/feelies/alpha/loader.py:1142`). **All 24 sit outside `execution/` and
`broker/`**; `execution/` itself contains zero mode branches — the seam does not
branch, it is selected.

| File | Count |
|---|---|
| `src/feelies/bootstrap.py` | 21 |
| `src/feelies/core/platform_config.py` | 1 |
| `src/feelies/harness/backtest_prep.py` | 1 |
| `src/feelies/harness/backtest_runner.py` | 1 |

Backend *selection* is legitimate composition-root work
(`src/feelies/bootstrap.py:821`, `:867`, and `_select_clock` at `:651`). The
substantive divergences are behavioural and outside the backend:

| Site | Divergence |
|---|---|
| `src/feelies/bootstrap.py:203` | `enforce_market_order = mode != PAPER` — the event log enforces timestamp monotonicity in every mode except PAPER |
| `src/feelies/bootstrap.py:222` | `registry_clock = None if BACKTEST` — the alpha registry has no clock in backtest |
| `src/feelies/bootstrap.py:273` | `_seq_thread_safe = mode != BACKTEST` — sequence generators are non-thread-safe in backtest |
| `src/feelies/bootstrap.py:411` | `metric_collector._store_raw_events = False` in BACKTEST — a private-attribute write from the composition root |
| `src/feelies/bootstrap.py:1143` | `emit_reading_metrics = mode != BACKTEST` — the sensor layer emits metrics in PAPER but not BACKTEST, so the bus event stream differs by mode |
| `src/feelies/bootstrap.py:1180` | `session_open_ns` may lazy-bind in BACKTEST; raises in every other mode |

### C-9 — Encapsulation breaks: 10 cross-object private accesses, 5 injected attributes.

`evidence/coupling.json`. Private access is concentrated in `src/feelies/bootstrap.py` (4),
`src/feelies/harness/backtest_runner.py` (4), `src/feelies/cli/backtest.py` (1), `src/feelies/signals/regime_gate.py` (1).

Five attributes are assigned onto objects from outside their class, so they
appear in no type contract:

```584:588:src/feelies/bootstrap.py
    orchestrator.config_snapshot = config_snapshot  # type: ignore[attr-defined]

    # Expose PAPER lifecycle handles to the operator entry script.
    orchestrator.live_feed = bundle.live_feed  # type: ignore[attr-defined]
    orchestrator.ib_connection = bundle.ib_connection  # type: ignore[attr-defined]
```

plus `metric_collector._store_raw_events` (`src/feelies/bootstrap.py:411`) and
`module._construct` (`src/feelies/bootstrap.py:1543`). Each carries an explicit
`type: ignore`, so the three on `Orchestrator` are invisible to `mypy --strict`
at every read site.

### Non-bus dispatch entry points — 16

`evidence/handlers.json`: `on_transition` 7, `on_quote` 3, `on_message` 2,
`on_event` 2, `on_alert_event` 1, `on_health_transition` 1. These are handler
invocations that are not bus operations; `on_quote` in particular is how the
backtest router receives quotes (`src/feelies/bootstrap.py:353` wraps it in a
lambda subscribed to `NBBOQuote`) and how the trade path reaches the router
(`src/feelies/kernel/orchestrator.py:1214`, via `getattr(..., "on_trade", None)`
— a duck-typed call, not a declared contract).

---

## D0.4 Actual runtime path — one `NBBOQuote`, end to end

Traced by reading `src/feelies/bootstrap.py:145-624` (composition) and
`src/feelies/kernel/orchestrator.py:1153-2158` (dispatch). This is the executed
path. Every hop below is **synchronous**; the platform has no queue on this path.
`Hot` = tick-critical per CORE §D.

| # | Hop | Site | Engine | Hot | Mechanism |
|---|---|---|---|---|---|
| 0 | Backend yields the event | `src/feelies/kernel/orchestrator.py:1157` | 1 | yes | direct iterator over `backend.market_data.events()` |
| 1 | Type dispatch to the quote path | `src/feelies/kernel/orchestrator.py:1162` | kernel | yes | `isinstance` ladder — **not** the bus |
| 2 | Exception boundary opens | `src/feelies/kernel/orchestrator.py:1466` | kernel | yes | `try/except Exception` around the whole tick |
| 3 | Stale carryover signals expired | `src/feelies/kernel/orchestrator.py:1530` | 4/9 | yes | horizon-age test on the buffer |
| 4 | **Kill-switch gate** | `src/feelies/kernel/orchestrator.py:1561` | 11 | yes | direct `is_active` read; returns early |
| 5 | **Data-health gate** | `src/feelies/kernel/orchestrator.py:1583` | 1 | yes | `_data_health_blocks_trading`; drops without logging the event |
| 6 | **Halt gate** | `src/feelies/kernel/orchestrator.py:1591` | 1 | yes | `quote.symbol in self._halted_symbols` |
| 7 | M0→M1 `MARKET_EVENT_RECEIVED` | `src/feelies/kernel/orchestrator.py:1595` | kernel | yes | micro SM transition |
| 8 | Append to replayable event log | `src/feelies/kernel/orchestrator.py:1601` | 1 | yes | `_event_log.append` (skipped when pre-logged) |
| 9 | **Mark positions** | `src/feelies/kernel/orchestrator.py:1609` | 7 | yes | `_positions.update_mark(mid, bid, ask)` before any subscriber sees the quote |
| 10 | Risk high-water mark refresh | `src/feelies/kernel/orchestrator.py:1616` | 8 | yes | `getattr(..., "refresh_high_water_mark", None)` — duck-typed |
| 11 | Per-strategy marks | `src/feelies/kernel/orchestrator.py:1624` | 7 | yes | `_strategy_positions.update_mark` |
| 12 | **`bus.publish(quote)`** — the only bus hop on the market-data leg | `src/feelies/kernel/orchestrator.py:1634` | — | yes | fans out synchronously to 13–15 |
| 13 | ↳ Sensor fan-out | `src/feelies/sensors/registry.py:213` `_on_event` | 2 | yes | indexed by event type; emits `SensorReading` (`:291`) |
| 14 | ↳ Backtest router `on_quote` | `src/feelies/bootstrap.py:353` | 10 | yes | **BACKTEST only**; evaluates resting orders |
| 15 | ↳ Stop-exit author | `src/feelies/risk/stop_exit.py:172` | 8/9 | yes | may publish `OrderRequest` (`:297`) |
| 16 | Buying-power phase flip at RTH close | `src/feelies/kernel/orchestrator.py:1637` | 8 | yes | on exchange time |
| 17 | Reconcile quote-triggered fills | `src/feelies/kernel/orchestrator.py:1640` | 7/10 | yes | before signals are evaluated |
| 18 | M1→M2 `STATE_UPDATE` | `src/feelies/kernel/orchestrator.py:1643` | kernel | yes | |
| 19 | **Regime update** → `bus.publish(RegimeState)` | `src/feelies/kernel/orchestrator.py:1648` → `:2476` | 3 | yes | consumed by `src/feelies/services/regime_state_cache.py:54` and `src/feelies/signals/horizon_engine.py:196` |
| 20 | ↳ Hazard spike | `src/feelies/kernel/orchestrator.py:2515` | 3 | yes | `RegimeHazardSpike` → `src/feelies/risk/hazard_exit.py:141` |
| 21 | Horizon scheduler → `bus.publish(HorizonTick)` | `src/feelies/kernel/orchestrator.py:1252` | 2 | yes | boundary-driven; usually zero ticks |
| 22 | ↳ Aggregator builds snapshot | `src/feelies/features/aggregator.py:253` → `:347` | 2 | yes | `HorizonFeatureSnapshot` |
| 23 | ↳ Signal engine evaluates | `src/feelies/signals/horizon_engine.py:198` → `:505` | 4 | yes | `Signal`; or `SafetyStateChange` at `:540` |
| 24 | ↳ Universe synchronizer fan-in | `src/feelies/composition/synchronizer.py:128` → `:312` | 6 | yes | `CrossSectionalContext` at the barrier |
| 25 | ↳ Composition constructs intent | `src/feelies/composition/engine.py:197` → `:276` | 6 | yes | `SizedPositionIntent` |
| 26 | `Signal` buffered, not acted on inline | `src/feelies/kernel/orchestrator.py:574` → `_on_bus_signal:4721` | kernel | yes | appended to `_signal_buffer` |
| 27 | Cross-sectional bookend, pending intents flushed | `src/feelies/kernel/orchestrator.py:1652`, `:1653` | 6/9 | yes | |
| 28 | M3→M4 `SIGNAL_EVALUATE`; **one** signal selected | `src/feelies/kernel/orchestrator.py:1663`, `:1676` | 6 | yes | `_select_bus_signal` — lossy arbitration across alphas |
| 29 | **Position sizing** | `src/feelies/kernel/orchestrator.py:1696` | 8 | yes | `_compute_target_quantity` |
| 30 | Signal × position → `OrderIntent` | `src/feelies/kernel/orchestrator.py:1731` | 9 | yes | planner, or `_intent_translator` fallback at `:1740` |
| 31 | **M4→M5 `check_signal`** → `bus.publish(RiskVerdict)` | `src/feelies/kernel/orchestrator.py:1772`, `:1774` | 8 | yes | reductions are re-ALLOWed at `:1782` |
| 32 | **Admission gate** (halt blackout, flatten window, SSR, locate) | `src/feelies/kernel/orchestrator.py:1849` | 9 | yes | `admission_block_reason`, shared with the PORTFOLIO path |
| 33 | Build concrete `OrderRequest` | `src/feelies/kernel/orchestrator.py:1882` | 9 | yes | `_try_build_order_from_intent`; min-size gate here |
| 34 | **`check_order`** → `bus.publish(RiskVerdict)` | `src/feelies/kernel/orchestrator.py:1902`, `:1903` | 8 | yes | second veto on the concrete order |
| 35 | Compose both scale factors | `src/feelies/kernel/orchestrator.py:1959` | 8 | yes | `_compose_scaled_quantity`; zero ⇒ no order |
| 36 | Exhaustiveness guard | `src/feelies/kernel/orchestrator.py:1984` | 8 | yes | unknown `RiskAction` raises rather than submitting |
| 37 | Duplicate-pending suppression | `src/feelies/kernel/orchestrator.py:1996` | 9 | yes | blocks only; never cancel-then-submit |
| 38 | Submit | `src/feelies/kernel/orchestrator.py:3831` `_submit_tracked_order` | 10 | yes | order SM → `SUBMITTED` |
| 39 | Poll and publish acks | `src/feelies/kernel/orchestrator.py:3793`, `:3828` | 10 | yes | `OrderAck` on the bus (no subscriber outside backtest) |
| 40 | Apply ack to order SM | `src/feelies/kernel/orchestrator.py:4103` | 10 | yes | |
| 41 | **Reconcile fills → PnL, lots, attribution** | `src/feelies/kernel/orchestrator.py:4229`, `:4577` | 7 | yes | `PositionUpdate` published at `:4268`, `:4450` |
| 42 | M10 `LOG_AND_METRICS`; latency metrics | `src/feelies/kernel/orchestrator.py:2092` `_finalize_tick` | 11 | yes | see below |
| 43 | M10→M0 | `src/feelies/kernel/orchestrator.py:2154` | kernel | yes | |

### Path facts worth carrying forward

- **Two risk vetoes, both on the same tick.** `check_signal` (hop 31) and
  `check_order` (hop 34) both publish `RiskVerdict` to zero subscribers (C-4).
- **The signal is round-tripped through the bus to reach the orchestrator**
  (hops 23 → 26 → 28) but is consumed on the *same* tick, because publish is
  synchronous. The buffer exists to arbitrate multiple alphas, not to defer.
- **Alpha arbitration is lossy at hop 28.** `_select_bus_signal` returns one
  `Signal | None` per tick; the others are discarded and traced
  (`_trace_buffered_signals_arbitration:638`).
- **Exit orders re-enter through the bus.** The four risk-layer exit authors
  publish `OrderRequest`, which the orchestrator consumes at
  `src/feelies/kernel/orchestrator.py:585` → `_on_bus_hazard_order:4919`. So one
  event type carries both the outbound record of hop 33 and the inbound command
  from engine 8. `INFERRED`: `OrderRequest` is doing two jobs on one type,
  disambiguated only by the free-text `reason` field
  (`src/feelies/core/events.py:290`).
- **Two conditions on the path silently skip work.** Marking (hop 9) is inside
  `if mid > 0` (`src/feelies/kernel/orchestrator.py:1607`), so a quote with a
  non-positive mid marks nothing and continues to hop 12 — subscribers then see a
  quote the position store has not been marked against. And the rejected-quote
  alert at hop 5 is conditional on `self._normalizer is not None`
  (`src/feelies/kernel/orchestrator.py:1586`), so with no normalizer wired a
  data-health-blocked quote leaves no record at all: it is not logged (the comment
  at `:1585` says as much — "none reach the event log") and not alerted.
  `VERIFIED`; both are `INFERRED` as reachable only under specific composition.
- **The exception boundary is the whole tick** (hop 2). On any raise,
  `_handle_tick_failure:1474` resets the micro SM, clears
  `_pending_sized_intents`, and drives macro → `DEGRADED`; if that transition
  itself fails it sets `_pipeline_abort_requested` and the pipeline raises at
  `:1174`. Partial mutation before the raise is not rolled back — marks (hop 9),
  log append (hop 8) and any submitted order (hop 38) persist.
- **Metrics on the tick path deliberately avoid the sequence generator.**
  `_finalize_tick` routes always-on timers (`sensor_fanout_ns`,
  `sm_transition_ns`) to `self._metrics.record` with `sequence=0`
  (`src/feelies/kernel/orchestrator.py:2131`) precisely "so they cannot shift
  kernel event IDs", while conditional timers publish with `self._seq.next()`
  (`:2147`). The conditional set is a function of deterministic control flow, so
  sequence consumption is deterministic even though the timer *values* are
  wall-clock derived. `implemented` and correct; see D0.6 for why the values do
  not reach the parity hash.

---

## D0.5 Gate inventory

`measure.py gates` reports 153 functions whose *name* looks like a guard — a name
heuristic, not a decision inventory. `tools/arch/gatescan.py` instead counts the
**outcomes** a gate can produce, by marker family:

| Family | Sites | Concentrated in |
|---|---|---|
| `regime_gate` (`regime_gate_state`, `SafetyStateChange`, `SafetyReason`) | 56 | `forensics` 19, `risk` 13, `signals` 12, `core` 7 |
| `alpha_load_gate` (`LayerValidationError`, `TrendMechanismError`) | 52 | `alpha` 52 |
| `risk_verdict` (`RiskAction.*`) | 48 | `kernel` 25, `risk` 18, `alpha` 5 |
| `data_health` (`DataHealth.*`) | 43 | `ingestion` 37, `kernel` 5, `harness` 1 |
| `macro_degrade` (`MacroState.DEGRADED / RISK_LOCKDOWN / HALTED / SHUTDOWN`) | 35 | `kernel` 35 |
| `order_admission_block` (`BLOCK_*`) | 29 | `execution` 19, `kernel` 10 |
| `escalation` (`RiskLevel.*`) | 27 | `kernel` 16, `risk` 11 |
| `kill_switch` | 22 | `kernel` 9, `monitoring` 6, `harness` 4 |
| `lifecycle_quarantine` | 10 | `promotion` 5, `alpha` 3, `forensics` 2 |
| `warmup_staleness` | 7 | `sensors` 5 |

`INFERRED`: 25 of 48 `RiskAction` sites and 10 of 29 `BLOCK_*` sites are in
`kernel/`, i.e. the largest single consumer of risk and admission vocabulary is
the orchestrator, consistent with D0.2.

### The runtime gate ladder on the SIGNAL path, in execution order

| Order | Gate | Site | On missing/malformed input |
|---|---|---|---|
| 1 | Kill switch | `src/feelies/kernel/orchestrator.py:1561` | absent switch ⇒ **pass** (`is not None` guard) |
| 2 | Data health | `src/feelies/kernel/orchestrator.py:1583` | blocks; the quote never reaches the event log, and the alert is itself conditional on a normalizer being wired (`:1586`) |
| 3 | Symbol halt | `src/feelies/kernel/orchestrator.py:1591` | blocks marks and fills |
| 4 | Regime gate (ON/OFF) | `src/feelies/signals/horizon_engine.py` + `src/feelies/signals/regime_gate.py` | fail-closed; 3 error paths named by `SafetyReason` (`src/feelies/core/events.py:426`) |
| 5 | Edge-vs-cost (Inv-12 B4) | `src/feelies/kernel/orchestrator.py:2226`, `:2184`, `:2266` | edge `0.0` cannot clear a positive bar (`src/feelies/core/events.py:560`) |
| 6 | `check_signal` | `src/feelies/kernel/orchestrator.py:1772` | reductions force-ALLOWed at `:1782` |
| 7 | Admission (halt blackout / flatten window / SSR / locate) | `src/feelies/kernel/orchestrator.py:1849`, `src/feelies/execution/order_admission.py:178` | each blocks entries only |
| 8 | Min order size | `src/feelies/execution/order_admission.py:162` | blocks |
| 9 | `check_order` | `src/feelies/kernel/orchestrator.py:1902` | unknown `RiskAction` **raises** (`:1984`) |
| 10 | Per-alpha budget | `src/feelies/alpha/risk_wrapper.py:178` | unknown `strategy_id` ⇒ **skipped** (E-2) |
| 11 | Duplicate-pending | `src/feelies/kernel/orchestrator.py:1996` | blocks only, never cancels |
| 12 | Router RTH / session | `src/feelies/execution/passive_limit_router.py:536`, `src/feelies/execution/trading_session.py` | rejects |
| 13 | Fill timing eligibility | `src/feelies/execution/passive_limit_router.py:527`, `:242` | exchange-time gate, both paths |

Two vetoes are monotone-reducing by explicit carve-out (rows 6 and 9 re-ALLOW an
EXIT when risk would otherwise block it), which is the fail-safe direction for
exits. The exhaustiveness guard at row 9 is the only gate that converts an
unknown enum value into a raise rather than a decision.

### The alpha load-gate sequence — G1…G17 as implemented

`VERIFIED` by reading `LayerValidator.validate` at
`src/feelies/alpha/layer_validator.py:289-340`. Call order and blocking status:

| Gate | Call site | Blocking |
|---|---|---|
| G1 layer independence | `:307` via `_softly` | **downgradable** — WARNING when `enforce_layer_gates=False` |
| G2 event typing | `:313` | blocking |
| G3 no cross-horizon leakage | `:314` via `_softly` | **downgradable** |
| G4 regime-gate purity | `:320` | blocking |
| G5 signal purity | `:321` | blocking |
| G6 feature dependency DAG | `:322` | blocking (skipped when `known_sensor_ids is None`, `:246`) |
| G7 horizon registration | `:323` | blocking |
| G8 no implicit lookahead | `:324` | blocking |
| G9 session alignment | `:325` | blocking |
| G10 universe disclosure | `:326` | blocking |
| G11 factor-neutralization disclosure | `:327` | blocking |
| G12 cost-arithmetic disclosure | `:328` | blocking |
| **G13** | **absent** | — |
| G14 data scope | `:331` | blocking |
| G15 fill assumptions | `:332` | blocking |
| G16 trend-mechanism compliance | `:335` | blocking; 10 numbered sub-rules |
| G17 safety-exit policy | `:340` | blocking — comment at `:337` states it is never research-downgradable |

### G-1 — G13 does not exist. `open defect` (in the gate registry, not behaviour).

A case-insensitive search for `g13` across all of `src/feelies/` returns **no
matches**. `validate()` runs **16** gates: G1–G12 and G14–G17. There is no G13
function, no G13 constant, and no G13 registry entry — the identifier is simply
absent from the numbering, while `validate()`'s own docstring
(`src/feelies/alpha/layer_validator.py:294`) states "gates are applied in numeric
order (G1 → G17)". The platform glossary is accurate here ("G13 is presently a
no-op"); the code has no no-op to point at. Two consequences:

- The gate set is not enumerable from a single source. `validate()` is an ordered
  sequence of 16 hand-written calls; nothing derives the list, so nothing can
  detect that a number is missing or that a gate was dropped from the sequence.
- The downgrade rule is not uniform and is not declared in data. `_softly`
  (`src/feelies/alpha/layer_validator.py:260`) is applied at exactly two call
  sites; every other gate's blocking status is implicit in whether the author
  wrapped it. Its own docstring at `:270` says the soft gates are "G1, G3", which
  matches the code — but the comment at `:255` claims "G9 / G10 / G11 are *always*
  blocking", singling out three gates when in fact all fourteen non-soft gates are.

`INFERRED`: G16's 10 sub-rules are also identified only by string literals inside
error messages (`:882` "G16 rule 1", `:895` "rule 2", …, `:988` "rule 10"), so
sub-rule coverage cannot be enumerated programmatically either.

### Cross-alpha gates outside `validate()`

Two checks run outside the per-spec sequence and so are not in the G-numbering:

| Check | Site |
|---|---|
| G17 cross-alpha scope invariant (`decouple_caps_only`) | `src/feelies/alpha/layer_validator.py:1317-1373` |
| Decouple symbol-scope enforcement at boot | `src/feelies/bootstrap.py:754` |

### Fail-quiet inventory

20 `except` handlers neither raise, return, nor log
(`evidence/gatescan.json:fail_quiet_except_handlers`); 9 are bare `pass`. Two are
on decision paths and are escalated as E-2. For contrast, `measure.py gates`
reported **1** silent except, because it counts only handlers whose entire body
is `pass` *and* whose enclosing function has a guard-like name.

---

## D0.6 Parity surface

### The oracle — 26 registered baselines, and the registry is closed

`tests/determinism/parity_manifest.py:133` `LOCKED_PARITY_BASELINES` holds **26**
entries, each a `(hash_hex, event_count)` pair imported from the test that computes
it. `evidence/parityscan.json`: **120** hash-producing helpers across 30
determinism modules, `tests/acceptance/`, and the fixture packages; **177** distinct
field names reach a hash.

The registry is *closed*, which is the strongest structural property found in
Phase 0. Two tests enforce it:

- `test_every_locked_hash_is_registered_or_exempt`
  (`tests/determinism/test_parity_manifest.py:261`) AST-scans the whole `tests/`
  tree for any binding whose value contains a 64-hex literal — including `dict`
  and underscore-prefixed bindings — and fails unless each is referenced by the
  manifest or listed in `_UNREGISTERED_HASH_EXEMPTIONS` with a reason.
- `test_every_exemption_names_a_binding_that_exists` (`:288`) fails on a stale
  exemption, so the list cannot assert coverage that has been deleted. Its
  docstring records that this already happened: "All eight
  `EXPECTED_ORCHESTRATOR_*_HASH` exemptions outlived the constants they named."

`manifest_fingerprint()` (`:234`) is one SHA-256 over the sorted manifest, so a
coordinated re-pin is a one-line diff. `conformance-tested`. This satisfies CORE
§G.5's "enumerable from a single source" for the parity surface — the only
responsibility in Phase 0 for which that is true.

### What is outside the manifest, by declaration — 13 exemptions

`tests/determinism/test_parity_manifest.py:144`. The exclusions are reasoned, not
accidental, but two of them matter for what the oracle can catch:

| Exempt binding | Stated reason | Consequence |
|---|---|---|
| `EXPECTED_ORCHESTRATOR_STREAMS`, `EXPECTED_STOP_EXIT_STREAMS` | fixture builds the whole platform, regime included; transcendental math is stable only for a fixed host + libm | **the composed system's streams are not a portable contract** — locked only locally in `tests/determinism/test_orchestrator_replay.py` |
| `_BASELINE_TRADE_PARITY_HASH` | requires the APP/2026-03-26 disk cache | the end-to-end trade baseline is data-gated (see P-3) |
| `EXPECTED_LEVEL3_SOLVER_HASH` | cvxpy/ECOS only under the `[portfolio]` extra | solver path unpinned in a default install |
| `_BASELINE_CONFIG_HASH` | config-contract hash, no event count | not a replay baseline |
| `_FIXTURE_GOLDEN_HASHES` | CPCV fold curves over committed JSON | pins fixture data, not a stream |
| `_EMPTY_SHA`, `_EMPTY_SHA256` | `sha256(b"")` spelling of "stream is empty" | not baselines |
| `_NON_PROMOTED_SIGNAL_HASH`, `_PROMOTED_SIGNAL_HASH` | module-local migration goldens | not cross-layer |

`VERIFIED`, and worth stating plainly: **regime output is pinned** —
`level5_regime_hazard_spike` and `level6_regime_state` are manifest entries — but
the *composed* platform run that includes the regime engine is not, because its
math is host-sensitive. So per-engine parity is portable; whole-system parity is
host-local by design.

### P-1 — Parity is field-selected at a float tolerance, not bit-identical. `implemented`; CORE §C.1 says bit-identical.

Float fields are stringified through a format specifier before hashing. Measured
histogram of specifiers across all 120 helpers: **`.6f` ×10, `.2f` ×1** — no other
precision appears. So two runs whose prices differ by 5e-7 produce an identical
hash. This is reproducibility at a declared tolerance; it is defensible, and it is
not the invariant as written. The gap is recorded nowhere in the manifest.

Field-name coverage per event class, measured (`tools/arch/parity_coverage.py`):

| Event | Declared | Name reaches a hash | Never |
|---|---|---|---|
| `PositionUpdate` | 11 | 11 | 0 |
| `RegimeHazardSpike` | 11 | 11 | 0 |
| `SafetyStateChange` | 14 | 14 | 0 |
| `StateTransition` | 9 | 9 | 0 |
| `SymbolHalted` | 8 | 8 | 0 |
| `Signal` | 19 | 18 | `reversal_cost_estimate_bps` |
| `OrderAck` | 13 | 12 | `request_sequence` |
| `RiskVerdict` | 9 | 8 | `constraints` |
| `CrossSectionalContext` | 11 | 10 | `signals_by_strategy_by_symbol` |
| `KillSwitchActivation` | 6 | 5 | `activated_by` |
| `HorizonTick` | 11 | 9 | `boundary_timestamp_ns`, `boundary_ts_ns` |
| `MetricEvent` | 9 | 7 | `metric_type`, `tags` |
| `SensorReading` | 12 | 9 | `confidence`, `provenance`, `parent_correlation_id` |
| `SizedPositionIntent` | 15 | 12 | `disclosed_cost_total_bps_by_symbol`, `decision_basis_hash`, `solver_status` |
| `Alert` | 9 | 5 | `severity`, `alert_name`, `message`, `context` |
| `HorizonFeatureSnapshot` | 14 | 10 | `boundary_ts_ns`, `source_sensors`, `feature_versions`, `parent_correlation_id` |
| `OrderRequest` | 15 | 11 | `limit_price`, `is_short`, `is_moc`, `g12_disclosed_cost_total_bps` |
| `RegimeState` | 15 | 11 | `state_names`, `stability`, `calibrated`, `discriminability` |
| `NBBOQuote` | 19 | 7 | 12, incl. `bid_size`, `ask_size`, `exchange_timestamp_ns` |
| `Trade` | 19 | 5 | 14, incl. `price`, `size`, `exchange_timestamp_ns` |

**Method caveat, stated because it bounds every number above:** this is a
*union-of-names* measure. A field counts as covered if its name appears in any
helper's field list, so shared names (`symbol`, `timestamp_ns`) mark a field
covered for every class that declares it. The counts are therefore an **upper
bound** on per-stream coverage, not a measurement of it — `Trade`'s 5 are all
generic envelope names, and `Trade` has no helper of its own. `INFERRED`. Resolving
this needs per-helper attribution, recorded as U-8.

Two `INFERRED` consequences that do not depend on the caveat:

- **Adding a field to an event cannot break parity.** The hash input is a
  hand-written field list, so a new field is unhashed until someone edits a
  helper. The oracle cannot detect schema growth — which is C-1's blast radius.
- **`OrderRequest.limit_price` and `is_moc` are unhashed.** Both change execution
  semantics: `is_moc` selects the MOC path implicated in E-1, and `limit_price` is
  the price the order rests at. A change to either can leave every manifest hash
  green. Fills are pinned downstream (`market_fill_acks`, `position_pnl`), so this
  is not unobservable — but it is observable only if the change alters a fill on
  the pinned fixtures.

### P-2 — Unhashed field/behaviour pairs worth naming

`sequence`, `correlation_id`, `source_layer` and `timestamp_ns` **are** in the
hashed name set (`VERIFIED` against `evidence/parityscan.json`), so event ordering
and correlation are inside the surface, not outside it. The gaps that remain are
narrower and specific:

| Unhashed | Why it matters |
|---|---|
| `SizedPositionIntent.decision_basis_hash` | the intent's own provenance digest is not itself pinned |
| `SizedPositionIntent.solver_status` | an intent produced by a degraded solver path hashes identically |
| `RegimeState.calibrated`, `stability`, `discriminability` | regime *quality* flags; a decalibrated regime that emits the same posteriors is invisible |
| `SensorReading.confidence`, `provenance` | feature provenance is versioned (C-1) but not pinned |
| `Alert.severity`, `alert_name`, `message` | no `Alert` content is pinned; only its envelope |

### P-3 — The end-to-end trade baseline is one symbol, one day, and data-gated.

`tests/acceptance/test_backtest_app_baseline.py` pins trade parity hash, net PnL
and fill count for APP on 2026-03-26 — a single symbol, a single session. It is
marked `functional`, so it is deselected from the default CI selector; the repo has
since added `FEELIES_REQUIRE_BASELINE_CACHE=1` and a dedicated `parity oracle` CI
job to close the three independent silent-pass routes (cache-miss skip, marker
deselection, fork-PR secret absence). `conformance-tested` — with the caveat that
coverage breadth is one instrument-day, and the multi-symbol PORTFOLIO path is not
in the pinned baseline. Note that `level4_portfolio_order` and
`cross_sectional_context` *are* manifest entries, so the Layer-3 mechanics are
pinned in isolation; what is unpinned is a multi-symbol run end to end.

### P-4 — Determinism inputs the oracle does not pin

`INFERRED` from D0.3 and D0.4:

| Input | Why it is a determinism input | Pinned? |
|---|---|---|
| Bus subscriber registration order | dispatch is registration-ordered (C-2) | no — only 6 prose comments in `src/feelies/bootstrap.py` |
| Sensor load order from config | fixes `SensorReading` emission order | no |
| `_select_bus_signal` arbitration order | picks 1 of N signals per tick | only the winner is hashed; the discard set is not |
| Host + libm | regime transcendental math | explicitly *not* — the reason 2 orchestrator streams are exempt |
| `PYTHONHASHSEED` | `AGENTS.md` sets it for mutation runs | not asserted in the manifest |

### P-5 — Manifest layer numbering disagrees with the constants it imports. `open defect` (cosmetic).

`level1_sensor_reading` maps to `EXPECTED_LEVEL4_READING_HASH`
(`tests/determinism/parity_manifest.py:134`) — the key says L1, the constant says
L4, and both name the sensor-reading stream. Measured: 1 such mismatch across 26
entries. Separately, only **11** of 26 keys carry a `levelN_` prefix at all
(L1×2, L2×2, L3×3, L4×2, L5×1, L6×1); the other 15 are named by subject
(`position_pnl`, `symbol_halted`, …). `VERIFIED`. So "L1–L6" is not a taxonomy the
manifest actually implements, and a reader mapping baselines to CORE layers by key
name will mis-file one of them.

---

## D0.7 Unassigned-responsibility findings (CORE §F.1–7)

### F.1 Universe definition — `Unowned`, split across four places

No module owns "which symbols exist today". The set is assembled from:

| Source | Site |
|---|---|
| Run config symbol list | `configs/*.yaml` → `PlatformConfig.symbols` |
| Per-alpha `universe` disclosure (G10) | `src/feelies/alpha/layer_validator.py:326` |
| Composition-barrier expected universe | `src/feelies/composition/synchronizer.py` (`completeness` vs threshold) |
| Decouple symbol-scope enforcement | `src/feelies/bootstrap.py:754` |

`VERIFIED` by measured absence: no module under `src/feelies/` has "universe" in
its filename, and the only two module-level `Universe*` symbols are
`src/feelies/bootstrap.py:141` `UniverseScaleError` and
`src/feelies/composition/synchronizer.py:30` `UniverseSynchronizer` — a barrier
that *waits on* a universe it is handed, not one that defines it.
The consequence visible in code is that the barrier's `completeness` is measured
against a universe supplied by config, so a config/alpha-disclosure mismatch
degrades the barrier rather than failing the load.

### F.2 Symbol identity and corporate actions — `none`

No owner. There is no symbol-identity module, no ticker-change map, no split or
dividend adjustment anywhere in `src/feelies/`. Symbols are bare `str` throughout
(`src/feelies/core/events.py`, every event). `VERIFIED` by absence. On a split or
ticker change, cached event logs and live data diverge silently; nothing in the
platform can detect it.

### F.3 Session and halt state — **owned**, `Clear`

`src/feelies/execution/trading_session.py` owns session/RTH state, and halts are
owned jointly by `ingestion` (detection → `DataHealth`) and `kernel`
(`_halted_symbols`, `SymbolHalted` at `src/feelies/kernel/orchestrator.py:5074`).
This is the one §F item with a clean owner. Caveat: the halt *event* has no
subscriber (C-4), and `session_open_ns` may lazy-bind in BACKTEST only
(`src/feelies/bootstrap.py:1180`).

### F.4 Broker reconciliation — **owned for fills**, `Mixed`

`src/feelies/broker/ib/` and the kernel's reconcile hops (D0.4 hops 17, 41) own
order and fill reconciliation. What is **not** owned: no periodic
position-of-record comparison against the broker's own position report. `INFERRED`:
divergence between `PositionTracker` and the broker is detectable only through the
fill stream, so a fill the platform never received leaves the two out of sync
indefinitely. Marked as an unknown in D0.8 (U-3) rather than a defect, because I
did not exhaustively read `broker/ib/`.

### F.5 Exception propagation policy — `Mixed`, and the tick path is explicit

The tick path has a stated policy (D0.4 hop 2 → `_handle_tick_failure`, macro
`DEGRADED`, `_pipeline_abort_requested`). That is the only place a policy is
declared. Elsewhere it is per-site: 20 fail-quiet handlers
(`evidence/gatescan.json`), 9 of them bare `pass`. `VERIFIED`. There is no
platform-wide taxonomy of "recoverable vs fatal" and no single module defining it.

### F.6 Backpressure and queue policy — **owned at ingress only**, `Clear` where present

`src/feelies/ingestion/massive_ws.py` owns the only queue in the system: bounded,
drops on full, counts drops (`_events_dropped`), logs a warning, and notifies the
normalizer via `notify_feed_interrupted` so the drop surfaces as a `DataHealth`
degradation rather than a silent gap. `VERIFIED` — this is not the silent-drop
anti-pattern. Everywhere else the answer is "there is no queue": the bus is
synchronous (`src/feelies/bus/event_bus.py:65`), so backpressure inside the
platform manifests as tick latency, not queue growth.

### F.7 Contract and schema versioning — `none`

See C-1. No event carries a version; the policy exists only as prose at
`src/feelies/core/events.py:15`. Producer versions exist (`sensor_version`,
`feature_versions`); schema versions do not. Combined with P-1 (adding a field
cannot break parity) and the fact that events are persisted to a replayable log,
this is the §F item with the widest blast radius.

**Summary:** of CORE §F.1–7, two have a clear owner (F.3, F.6-at-ingress), two are
partial (F.4, F.5), and three have no owner at all (F.1 split, F.2 absent, F.7
absent).

---

## D0.8 Unknowns register

| ID | Unknown | Why unresolved in Pass 1 | How to resolve |
|---|---|---|---|
| U-1 | Whether the 4 never-subscribed event types (`RiskVerdict`, `StateTransition`, `SymbolHalted`, `KillSwitchActivation`) are consumed by any out-of-tree operator tooling | Pass 1 is scoped to `src/` + evidence; `scripts/` and notebooks not read | read `scripts/`, `configs/`, and any operator runbooks in Pass 2 |
| U-2 | Whether `_select_bus_signal` arbitration is stable across equal-strength signals from different alphas | requires reading the comparator and its tie-break, plus a test that constructs a tie | read `src/feelies/kernel/orchestrator.py:1676` comparator + search tests for a tie fixture |
| U-3 | Whether `broker/ib/` performs any position-of-record reconciliation beyond the fill stream (F.4) | did not exhaustively read the IB adapter; `paper_rth`-gated tests never run in CI | read `src/feelies/broker/ib/` end to end; check for a positions-request call |
| U-4 | Whether the 21-type event closure is complete at runtime, or whether `SensorSpec.subscribes_to` can name a type not in `src/feelies/core/events.py` | subscriber set is config-derived (C-5) | enumerate `subscribes_to` across `alphas/**/*.yaml` and diff against the closure |
| U-5 | Whether a **multi-symbol** run is pinned end to end | resolved in part: `level4_portfolio_order` and `cross_sectional_context` pin Layer-3 mechanics in isolation; no equivalent of the APP whole-run baseline was found for a multi-symbol universe | search `tests/acceptance/` for a portfolio whole-run baseline; check `configs/` for a multi-symbol backtest config |
| U-6 | Whether `enforce_layer_gates=False` is reachable in any non-research config | requires reading `configs/`, out of Pass 1 scope | grep `configs/*.yaml` for `enforce_layer_gates` |
| U-7 | Actual tick-path latency distribution, and whether the always-empty `_global_handlers` loop (C-3) is measurable | no profiling run performed; perf tests are per-host gated | run `tests/perf/` baselines and read recorded budgets |
| U-8 | True **per-stream** parity coverage, as opposed to the union-of-names upper bound in P-1 | `tools/arch/parityscan.py` unions field names across all 120 helpers, so shared envelope names inflate per-event coverage | attribute each helper to the event type it hashes (via its `_REPLAY_BY_NAME` entry) and recompute coverage per stream |
| U-9 | Whether the 2 host-sensitive orchestrator stream exemptions are the *only* place whole-platform parity is asserted | read the exemption list and its reasons, not `tests/determinism/test_orchestrator_replay.py` itself | read `tests/determinism/test_orchestrator_replay.py` and confirm what its local locks cover |

---

## D0.9 Documentation disagreements

**Pass 2 only.** The paragraph that stood here through Pass 1 recorded that this
deliverable was empty by construction. It is now filled. **Nothing in D0.1–D0.8,
E-1, E-2 or the Pass 1 hard stop has been edited** — where Pass 2 narrows,
corrects or extends a Pass 1 claim, it says so below rather than rewriting it.

### Documents read in Pass 2

Everything CORE §B names, plus the two files §B's own claims point at:

`docs/three_layer_architecture.md` (v0.3.1, 2 984 lines) · `alphas/SCHEMA.md` ·
`.cursor/rules/platform-invariants.mdc` · `AGENTS.md` · `CLAUDE.md` ·
`docs/reviews/12_engine_review.md` · `platform.yaml` · `configs/*.yaml` ·
`pyproject.toml` · `conftest.py` · `docs/acceptance/v02_v03_matrix.md` ·
`docs/migration/schema_1_0_to_1_1.md` · `docs/audits/` (19 files, searched) ·
`.github/workflows/ci.yml`.

Two precedence rules the documents declare about themselves, both honoured here:

- `docs/three_layer_architecture.md:13` — "Sections below retain historical Phase
  planning text; where they conflict with D.2, the amendment notes and live code
  win." Its §3.1 is additionally marked "Historical snapshot… deliberately not
  updated" (`:228`). Sections so marked are **not** counted as disagreements.
- `docs/reviews/12_engine_review.md:12` — "where this document and those
  disagree, they win", deferring to the invariants file, the architecture doc and
  `SCHEMA.md`.

**Disclosure.** Three §B documents — `AGENTS.md`, `CLAUDE.md` and
`platform-invariants.mdc` — are always-applied rule files and were therefore in
context during Pass 1, which the two-pass split intends to prevent. One Pass 1
claim traces to that: P-3's account of `FEELIES_REQUIRE_BASELINE_CACHE` and the
`parity oracle` CI job came from `AGENTS.md`, not from code I had read. It is now
verified independently against `.github/workflows/ci.yml:117-139` and holds. No
other Pass 1 claim depends on those three files. Separately,
`docs/architecture/target/RUNBOOK.md:60` already recorded "subscribe_all: 0 call
sites — dead API"; C-3 was measured independently and agrees, so that is
cross-validation rather than novelty.

### D0.9a — Material disagreements

Ordered by what an engineer would do differently on reading the source instead.

| # | Document claim | Source | Severity |
|---|---|---|---|
| **D-1** | `alphas/SCHEMA.md:236`: G9 is "Cross-symbol staleness checks — `CrossSectionalContext.completeness` must clear the per-platform `composition_completeness_threshold`… **Always blocks** (data-integrity gate; not affected by `enforce_layer_gates`)". Repeated at `:454-457` ("G9 / G10 / G11 always block") and asserted in code's own comment at `src/feelies/alpha/layer_validator.py:255`. | `_check_g9_session_alignment` (`src/feelies/alpha/layer_validator.py:448`) **has no raise path at all**. It returns early for every non-PORTFOLIO spec (`:458`), and for PORTFOLIO it falls off the end after a comment calling itself "otherwise a structural placeholder" (`:460-462`). Its docstring concedes the check is "already covered by G7". The completeness rule SCHEMA describes is real but lives at runtime in `src/feelies/composition/engine.py:217`, not in a load gate. `VERIFIED`. | **material** |
| **D-2** | `docs/three_layer_architecture.md:1172`: "If false, only G12-G15 are blocking; G1-G11 warnings logged." | `enforce_layer_gates=False` downgrades **exactly two** gates, G1 and G3, via `_softly` (`src/feelies/alpha/layer_validator.py:307`, `:314`). G2 and G4–G12 keep raising. A reader following the doc would believe eleven gates become advisory in research mode; nine of those eleven still block. `SCHEMA.md:228`/`:230` and `_softly`'s own docstring (`:270`) get this right. `VERIFIED`. | **material** |
| **D-3** | `alphas/SCHEMA.md:243`: "Strict mode is the platform default since Workstream E (**`platform.yaml: enforce_trend_mechanism: true`**, default `true`)". | `platform.yaml:20` sets **`false`**, with the comment "Keep local smoke runs compatible with the reference alpha". So do `configs/paper_run.yaml:20` and `configs/paper_smoke_rth.yaml:19` — i.e. both PAPER configs. The *code* default is `True` (`src/feelies/core/platform_config.py:320`, loader `:1081`), so the parenthetical's second half is right and its first half is wrong about the file it names. G16 mechanism-block presence is therefore unenforced in every shipped config. `VERIFIED`. `docs/acceptance/v02_v03_matrix.md:28` and `docs/audits/alpha_lifecycle_audit_2026-07-02.md:504` both state this correctly. | **material** |
| **D-4** | `docs/audits/live_execution_audit_2026-07-02.md:53`, `:696`: MOC is "Currently **dormant**: no shipped config sets `moc_strategy_ids` (verified)". | The premise is true and the conclusion does not follow. Nothing needs to set it: the default is non-empty (`src/feelies/core/platform_config.py:108`, repeated at `:909`), and `configs/bt_sig_moc_imbalance.yaml:14` loads `alphas/sig_moc_imbalance_v1/`, whose `alpha_id` is exactly that default. MOC routing is live in that config today. No PAPER config loads that alpha, so the audit's IB-specific worry (`:655`) remains prospective — but "dormant" is the wrong word for the backtest path. `VERIFIED`. This **corroborates and sharpens E-1**: the coupling is exercised, not latent. | **material** |
| **D-5** | `.cursor/rules/platform-invariants.mdc` glossary: "`LayerValidator` calls **G1–G17** before load… **G13 is presently a no-op**; all other implemented checks are blocking when applicable." | `validate()` calls **16** gates; no `g13` identifier exists anywhere in `src/feelies/` (Pass 1 G-1, re-verified). There is no G13 no-op to be presently anything. `alphas/SCHEMA.md:240` ("G13 | **Reserved** | Warm-up is platform-owned; there is no alpha-layer runtime check") and `docs/three_layer_architecture.md:1904`, `:1273` ("G13 reserved") are both correct; the invariants file is the outlier. And per D-1 the platform *does* have an unconditional no-op gate — it is **G9**, which this same sentence's "blocking when applicable" clause implicitly denies. `VERIFIED`. | **material** |
| **D-6** | `docs/reviews/12_engine_review.md:42`: "Everything crosses a synchronous typed event bus (Inv-7). There is no polling." | `evidence/coupling.json`: the orchestrator makes **323** direct `self._<attr>.<method>()` calls across **55** injected collaborators, and the bus's own docstring (`src/feelies/bus/event_bus.py:7`) states the tick path uses direct calls by design (Pass 1 C-6). The review's own erratum A02 (`:311`) walks back only the polling half. `VERIFIED`. | **material** |
| **D-7** | `platform.yaml:5`: "# BACKTEST \| PAPER \| LIVE" — offered as the valid set for `mode:`. | `OperatingMode` has **two** members, `BACKTEST` and `PAPER` (`src/feelies/core/platform_config.py:42-44`). `mode: LIVE` raises `ConfigurationError("Unknown mode 'LIVE'. Valid: ['BACKTEST', 'PAPER']")` (`:747-753`) — fail-loud, so the behaviour is safe; the comment invites an operator to write a value that cannot load. `VERIFIED`. | **material** |
| **D-8** | `docs/reviews/12_engine_review.md:324`: "`OperatingMode.LIVE` remains rejected by bootstrap." | No `OperatingMode.LIVE` exists to reject, and `src/feelies/bootstrap.py` contains no LIVE branch — rejection happens at enum parse time in config (D-7). Outcome identical, mechanism misdescribed. The consequence is bigger than the wording: **there is no live mode**, so CORE §C.4's "backtest / paper / live share core logic" and every "backtest/live parity" claim in the doc set are, today, backtest-vs-paper claims. This reframes but does not contradict Pass 1's C-8. `VERIFIED`. | **material** |

### D0.9b — Doc-vs-doc disagreements, adjudicated by code

| # | The disagreement | Code's answer |
|---|---|---|
| **D-9** | Two 12-engine models share one numbering. `docs/reviews/12_engine_review.md:69-82` numbers them 1 Ingestion, 2 Sensor, 3 Feature/horizon, 4 Regime, 5 Signal, 6 Composition, 7 Risk, 8 Sizing, 9 Execution, 10 Portfolio/position, 11 Forensics, 12 Promotion. CORE §E numbers 1 Market Data, 2 State/Feature, 3 Regime, 4 Alpha, 5 Alpha Governance, 6 Portfolio Construction, 7 Portfolio Accounting, 8 Risk & Capital, 9 Execution Decision, 10 Execution Sim/Routing, 11 Observability & Safety, 12 Research/Forensics. | Not a code question — a collision hazard. "Engine 7" is Risk in the review and Portfolio Accounting in CORE; the review has no engine for observability, metrics or the kill switch, and CORE has no standalone Sizing engine. D0.2 used CORE §E. **The prior review's mapping table cannot be lifted into a later phase without renumbering.** |
| **D-10** | `.cursor/rules/platform-invariants.mdc` cites the promotion ledger as promotion_ledger.py; `docs/reviews/12_engine_review.md:82` puts lifecycle at alpha/lifecycle.py. (Both written without backticks here: they are paths quoted *because* they do not resolve.) | Neither path exists. The package is `src/feelies/promotion/` — `src/feelies/promotion/ledger.py`, `src/feelies/promotion/lifecycle.py`, `src/feelies/promotion/evidence.py`. CORE §B is correct that "`promotion/` is its own package, separate from `alpha/`". `VERIFIED` by file listing. |
| **D-11** | `docs/three_layer_architecture.md:2246` ("`platform.yaml: enforce_trend_mechanism` defaults to `true`") vs `:1989`, `:2758` (an `enforce_trend_mechanism: false` in `platform.yaml` is the documented v0.2 escape hatch). | Both describe something real and the doc never reconciles them: the *dataclass* default is `True`, the *file* pins `false`. See D-3. |

### D0.9c — Pass 2 narrows or resolves a Pass 1 claim

Recorded here, not by editing Pass 1.

| # | Pass 1 said | Pass 2 refinement |
|---|---|---|
| **D-12** | P-2: "`sequence`, `correlation_id`, `source_layer` and `timestamp_ns` **are** in the hashed name set… so event ordering and correlation are inside the surface." | True as a union across 120 helpers, and **misleading for the guard that matters most**. `compute_parity_hash` — the APP trade-sequence hash — excludes them by design and says so: "Deliberately still excluded: the three timestamps and `correlation_id` (plumbing — including them would make the hash sensitive to clock and id wiring rather than to economics)" (`src/feelies/harness/backtest_report.py:791-795`). `docs/reviews/12_engine_review.md:290` states the same, and is **correct**. This is exactly the ambiguity U-8 was registered for; it is now demonstrated, not hypothetical. `VERIFIED`. |
| **D-13** | P-4: `PYTHONHASHSEED` is "not asserted in the manifest". | Still true of the manifest, and the platform asserts it elsewhere in both directions: `conftest.py:31-43` warns whenever the seed is not `0` (observed firing on the collection run below), and `.github/workflows/ci.yml:100-115` runs `tests/determinism/` under `PYTHONHASHSEED: random` as a deliberate backstop, with the conftest warning called "expected here" (`:109`). So CORE §B's "a determinism job replays under `PYTHONHASHSEED=random`" is `VERIFIED` — scoped to `tests/determinism/`. Note the `parity oracle` job runs at seed `0` (`:138`), so the APP baseline is never replayed under a random seed. |
| **D-14** | U-6: whether `enforce_layer_gates=False` is reachable in any non-research config. | **Resolved.** No YAML anywhere in the repo sets `enforce_layer_gates`; the default is `True` (`src/feelies/core/platform_config.py:339`, `:1106`). G1 and G3 block in every shipped config. `VERIFIED`. |
| **D-15** | G-1 stated "The platform glossary is accurate here (\"G13 is presently a no-op\")" and then, in the same sentence, "the code has no no-op to point at". | Those two halves contradict each other and the first is wrong; see D-5. The rest of G-1 — no `g13` identifier, 16 gates, the set not enumerable from one source — is unaffected. Its second bullet says the `:255` comment "singles out three gates when in fact all fourteen non-soft gates are" blocking; per D-1 that comment is not merely under-inclusive, it is **wrong about G9**. |
| **D-16** | C-3: `subscribe_all` is "dead public API". | The 0-call-site measurement stands. `docs/audits/kernel_audit_2026-07-02.md:661`, `:689`, `:709` twice propose a concrete consumer — a `subscribe_all`-based recorder asserting exactly one publisher per parity event type — which was never built. So it is dead surface with a documented intended use, which bears on whether it should be deleted or wired. |

### D0.9d — Stale citations and counts, no behavioural consequence

| # | Claim | Measured |
|---|---|---|
| **D-17** | `docs/reviews/12_engine_review.md:103`: "`Orchestrator._on_market_event` drives a 16-state micro state machine per tick." | No `_on_market_event` exists in the repository. The traced entry is `_process_tick` / `_process_tick_inner` (D0.4). The 16-state spine itself matches. |
| **D-18** | Same doc, `:149-157` and open question 3 (`:274-277`): `platform.yaml` sets `platform_min_order_shares: 50`, inflating every sized target to 50 and making `capital_allocation_pct` inert. | Both halves have since changed. `platform.yaml:154` now sets `1`, as do `configs/paper_run.yaml:62` and `configs/paper_smoke_rth.yaml:60`; and the inflation behaviour was removed on 2026-08-12 (`tests/acceptance/test_backtest_app_baseline.py:173` "`platform_min_order_shares` stopped inflating sized …", past-tense comments at `src/feelies/kernel/orchestrator.py:2742`). **An open question in the §B set that current code has already closed.** A stale "(50)" comment survives at `configs/bt_netting_contest.yaml:38`. |
| **D-19** | Same doc, `:47-56` module footprint (dated 2026-08-09): `alpha` 18 files, `execution` 24, `services` 4, `kernel` 6 731 lines. | `evidence/inventory.json`: `alpha` **14**, `execution` **23**, `services` **3**, `kernel` **5 095 sloc**. Line totals are not comparable — the review counts raw lines, Pass 1 counts sloc — but file counts are, and they have drifted; `LiveOrderRouter` was retired on 2026-08-11, after the review. |
| **D-20** | `docs/three_layer_architecture.md:1903`, `:1911`: a "**4-level** parity hash (Fills / Signals / HorizonFeatureSnapshots / SensorReadings)". | 26 registered baselines, keys spanning `level1`–`level6` (D0.6). The 4-level description predates the corpus by several workstreams. |
| **D-21** | `AGENTS.md`: "Full suite (~4300 tests)". | **4 786 collected** (`uv run pytest --collect-only -q`, this session). `tests/determinism/parity_manifest.py:20` records a different figure again — "4600 passed / 5 skipped / 43 deselected" on 2026-08-08. Approximate by construction; noted because three numbers circulate. |
| **D-22** | `docs/audits/alpha_lifecycle_audit_2026-07-02.md:501` cites platform_config.py:527 for the `enforce_trend_mechanism` default; `:450` cites layer_validator.py:760 for G13. (Backticks omitted deliberately — these are the audit's stale locations, not live citations.) | Now `src/feelies/core/platform_config.py:320` and non-existent respectively. A general property of the July audits: line-number citations have decayed, so the audits are usable for *findings* and not for *locations* — consistent with CORE §H's "prior reviews are evidence, not conclusions". |
| **D-23** | `pyproject.toml:100-104`: the ruff config "forbids raw `datetime.now()` / `datetime.utcnow()` / **`time.time*`**" in production source. | `select = ["DTZ", "F401", "F841"]` (`:114-118`). `DTZ` (flake8-datetimez) covers `datetime`/`date` constructs only; it does not implement any `time.time*` rule, and CI lint is green against the 29 measured raw clock reads (16 `time.monotonic`, 12 `time.perf_counter_ns`, 1 `time.time_ns` — `evidence/clockscan.json`). The `time.*` ban is real but enforced by `tests/acceptance/test_no_walltime_outside_clock.py`, not by ruff. `INFERRED` from the ruleset plus a green lint. |
| **D-24** | `docs/three_layer_architecture.md:1908` (Invariant 10): the ban's audit gate is a "ruff rule … must include `src/feelies/sensors/`, `src/feelies/composition/` in its scope after Phase 4". | Satisfied, by being unscoped: `[tool.ruff.lint]` applies tree-wide with per-file ignores only for `src/feelies/core/clock.py` and one ingestion functional test (`pyproject.toml:120-129`). No per-directory scoping was needed. |

### D0.9e — Checked and accurate

Recorded so the table is not read as a defect list. Each was verified against code
or measured evidence in this pass.

| Document claim | Verification |
|---|---|
| CORE §B: 196 files, ~43 200 sloc; 21 packages; engines 9 and 10 both in `execution/`; `promotion/` separate from `alpha/` | `evidence/inventory.json`: 196 files, 43 197 sloc, 21 packages. All correct. |
| CORE §B: "Python version is CI-pinned"; "a determinism job replays under `PYTHONHASHSEED=random`" | `ci.yml:70`, `:148` pin `3.13` (`pyproject.toml:5` requires `>=3.12`); `:114` runs the determinism package at `random`. Both correct. |
| CORE §I: eleven `alpha_id`s — seven shipped, two under `alphas/research/`, two templates; APP 36 vs AAPL 4 vs SPY 1 in `configs/` + `platform.yaml` | `evidence/alphaleak.json` lists exactly 11; the manifest listing splits 7/2/2; measured counts are **36 / 4 / 1**. Exact. |
| `docs/reviews/12_engine_review.md:122-124`: "The book must be marked *before* the quote is published, or drawdown is evaluated against a stale mark." | D0.4 hops 9 and 12: `update_mark` at `src/feelies/kernel/orchestrator.py:1609`, `publish` at `:1634`. Correct, and load-bearing. |
| `docs/reviews/12_engine_review.md:206-215`: registered corpus portable across libm; host-sensitivity caveat applies to the *unregistered* hashes, which carry exemptions | Matches `tests/determinism/test_parity_manifest.py:144-189` and D0.6. Correct. |
| `.cursor/rules/platform-invariants.mdc`: "`mypy --strict` on all `src/feelies/`; no `ignore_errors` overrides (acceptance-locked)" | `pyproject.toml:75` `strict = true`; the no-`ignore_errors` claim is enforced by `tests/acceptance/test_mypy_strict_scope.py` (`pyproject.toml:86-88`). Correct. Pass 1's C-9 concerns inline `type: ignore[attr-defined]` comments, which strict mode permits — a different mechanism, so no contradiction. |
| `.cursor/rules/platform-invariants.mdc`: promotion ledger "never read on the tick path (forensic only)" | Agrees with D0.2's cold classification of `promotion/`. |
| `docs/three_layer_architecture.md:1909` (Invariant 11): regime gate defaults OFF; sub-threshold completeness skips rather than extrapolates | D0.5 row 4 and `src/feelies/composition/engine.py:217`. Correct. |
| `conftest.py:27-43`: surfaces the active hash seed and warns when unpinned | Observed firing: `PYTHONHASHSEED=None (expected '0')` on this session's collection run. Correct. |
| `docs/three_layer_architecture.md` §3.1/§3.2 being wrong about the module tree and the bus-traffic table | **Not counted as disagreements.** §3.1 is marked "Historical snapshot… deliberately not updated" and redirects to `AGENTS.md`/`CLAUDE.md`; §3.2 is marked "approximate" and instructs the reader to reconcile it against `src/feelies/core/events.py`. Both self-disclose. For the record, §3.2's `FeatureUpdate`, `OrderIntent` and `Fill` rows name types that are not `Event` subclasses (`evidence/contracts.json`; `OrderIntent` is a plain frozen dataclass at `src/feelies/execution/intent.py:40`), and its `Signal` consumer is listed as `risk` where code has the kernel buffer and the composition synchronizer. |

---

## Pass 1 hard stop

Deliverables D0.1–D0.8 complete; D0.9 deferred to Pass 2 by protocol. Two findings
escalated: E-1 (`moc_strategy_ids` alpha-ID coupling) and E-2 (fail-quiet handlers
on decision paths).

### Verification performed on this document

- `measure.py spotcheck` over 5 seeds × 45 samples: 218 distinct citations,
  **0 failures**. Before that, 19 of 40 sampled failed — every one an abbreviated
  path (`risk/exit_composer.py:486`) that does not resolve from the repository
  root. All 56 such paths were expanded by `tools/arch/fix_citations.py`; the 3 it
  could not resolve mechanically were rewritten by hand, including one citation to
  a file that does not exist (`universe.py`), now restated as a measured absence.
- **`spotcheck` bounds are narrower than they look.** It verifies that the file
  exists and the line is within EOF — not that the line says what the claim says.
  So a clean sample is necessary, not sufficient. The tick-path hops (D0.4), the
  gate ladder (D0.5) and both E-2 sites were additionally read at the cited lines;
  that reading is what produced the two silent-skip conditions in D0.4.
- Three claims drafted from recollection were **measured and found false**, and are
  corrected above rather than carried: that regime output had no parity hash (it
  has two manifest entries), that `sequence` and `correlation_id` were outside
  every hash (both are in the hashed field set), and that the manifest held 19
  baselines (26). The float-precision claim was likewise wrong: only `.6f` and
  `.2f` appear.
- Scope guard: `scope: OK -- no protected-path changes`. Writes were confined to
  `docs/architecture/target/out/` and `tools/arch/`; `measure.py` and its `CONFIG`
  block were not edited.

### Tooling note for later phases

`tools/arch/parityscan.py` originally wrote to `evidence/parity.json`, a name that
would have collided with a `measure.py parity` subcommand had one existed. It does
not — the frozen harness has no parity measurement at all — but the output was
renamed to `parityscan.json` so the provenance of every evidence file stays
one-to-one with the script that produced it.

---

## Pass 2 verification

- **Scope guard:** `scope: OK -- no protected-path changes`. Pass 2 read `docs/`,
  `alphas/SCHEMA.md`, `platform.yaml`, `configs/`, `pyproject.toml`, `conftest.py`
  and `.github/workflows/ci.yml`; it wrote only to this file.
  `tools/arch/measure.py` and its `CONFIG` block remain unedited.
- **Pass 1 body unmodified.** The only Pass 1 text replaced was the D0.9 stub,
  whose sole content was a note that the deliverable was empty by construction.
  D0.1–D0.8, E-1, E-2 and the Pass 1 hard stop were not edited. The basis is the
  edit itself — a single targeted replacement of the stub — not a diff: this file
  is untracked, so no Pass 1 snapshot exists in git to diff against, and I am not
  going to describe a comparison I cannot run.
- **Citation spotcheck:** 8 seeds × 60 samples over 242 distinct citations.
  **Three citations fail, all in Pass 1 text, all deliberate** (named without
  backticks here so this note does not add three more): risk/exit_composer.py:486
  and universe.py at lines 1074 and 1077 of this file, quoted inside Pass 1's
  verification note as *examples* of the two citation defects that note describes;
  and a bare measure.py at line 1090. They resolve only as
  `src/feelies/risk/exit_composer.py:486` and `tools/arch/measure.py`, and
  universe.py does not exist at all — which is the point being made. Pass 2 is
  forbidden to edit Pass 1, so they stand, and Pass 1's own claim of "0 failures"
  should be read as true when measured and stale thereafter: the illustrative
  examples were appended to that note *after* its spotcheck ran.
- **Deliberate non-citations in D0.9.** Four paths are written without backticks
  so the checker does not treat them as claims: promotion_ledger.py and
  alpha/lifecycle.py (D-10) and platform_config.py:527 and layer_validator.py:760
  (D-22). Each is quoted from a document precisely because it no longer resolves.
- **What spotcheck cannot do, again.** It proves a path and line exist, not that
  they say what the claim says. Every D0.9a row was read at the cited line;
  D-1 (G9), D-3 (`enforce_trend_mechanism`), D-4 (the MOC config), D-7/D-8
  (`OperatingMode` membership) and D-12 (`compute_parity_hash`) were each verified
  in source rather than inferred from the document under review.
- **One Pass 2 measurement, not a document claim:** `uv run pytest
  --collect-only -q` → **4 786 tests collected** (D-21).

**HARD STOP.** Phase 0 complete — Pass 1 and Pass 2. Phase 1 not begun.
