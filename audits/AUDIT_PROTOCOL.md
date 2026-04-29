# Feelies — Living Audit Protocol (SOP)

**Version:** `v1.1` — revised 2026-05-01. (`v1.0` locked 2026-04-17.)

**v1.1 changelog** *(document in the next audit's `META-01` section)*:
- `A-LAYER-01`: expanded layer list from 11 to 17 named layers (added Sensors, Signals, Composition, Services, Research, Forensics, CLI).
- `A-LAYER-03`: added `SensorRegistry`, `HorizonSignalEngine`, `CompositionEngine`, `StrategyPositionStore`, `FillAttributionLedger` to bootstrap-only grep list.
- `A-FAIL-04`: replaced deleted `CompositeSignalEngine.evaluate` check with `HorizonSignalEngine._evaluate_one` warm-guard check.
- `A-DATA-06`: updated — `EventSerializer` Protocol now exists; finding narrowed to absence of a concrete durable backend.
- `A-REGIME-01`: updated to include `RegimeHazardDetector` Phase-2 wiring.
- `A-THREE-01`–`A-THREE-04` *(new section A15)*: three-layer alpha architecture checks (loader gate flags, `SensorRegistry` binding, `RegimeGate` compilation, `CompositionEngine` wiring).
- `A-PROMO-01`–`A-PROMO-03` *(new section A16)*: promotion lifecycle integrity checks (`AlphaLifecycle`, `PromotionLedger`, `GateId` evidence matrix).
- `B-CAUSAL-02`: replaced `CompositeSignalEngine` with `HorizonSignalEngine._evaluate_one` warm-guard.
- `B-GUARD-03`: replaced `CompositeSignalEngine` cooldown with `RegimeGate` per-(alpha_id, symbol) cooldown.
- `B-MULTI-01`: replaced `MultiAlphaEvaluator` (deleted) with bus-driven `_on_bus_signal`/`_on_bus_sized_intent` description.
- `B-MULTI-02`: updated `SignalArbitrator` description — Protocol + `EdgeWeightedArbitrator`, wired in orchestrator's `_on_bus_signal` path.
- `B-E2E-05`: updated — router stub files now exist; BLOCKER narrowed to `_create_backend` not yet wiring them.
- `B-SENSOR-01`–`B-HAZARD-02` *(new section B14)*: sensor-to-signal pipeline and hazard-controller checks.
- Risk register: updated paper/live-router and `EventSerializer` entries.
- Cadence: added `sensors/`, `signals/`, `composition/`, `services/` to high-blast-radius modules.

This file is the Standard Operating Procedure that the agent re-reads at the start of every audit iteration. It is the *only* document the agent needs in order to execute a complete audit; all source-of-truth references back to platform invariants and skills are inlined per check.

Any change to this SOP requires a revision bump (e.g. `v1.0` -> `v1.1`) and a corresponding entry in the next audit report's `META-01` section.

## How an iteration runs

1. Read this file.
2. Walk Pillar A (`A1` -> `A16`, including `A8b`) in order. For each check, perform the listed Method, decide PASS / FAIL with severity, and record one line of evidence (file path + line number, grep hit count, or command output).
3. Walk Pillar B (`B1` -> `B14`) in order, same protocol.
4. Run the embedded automation:
   - `pytest -q` (record passed/failed/skipped/xfailed counts + exit code)
   - `python scripts/run_backtest.py --demo` (record parity hash, trade count, gross/net PnL, max DD)
   - Re-run the demo to confirm parity hash is bit-identical
   - `python scripts/run_backtest.py --demo --stress-cost 1.5`
   - `python scripts/run_backtest.py --demo --stress-cost 2.0`
5. Open `audits/_template.md`, copy to `audits/YYYY-MM-DD-<slug>.md`, and fill every line.
6. Apply the **Pass/Fail criteria** (below) to compute the iteration verdict.
7. Apply the **META-01** rule: list every change to `.cursor/rules/platform-invariants.mdc` and `.cursor/skills/**` since the prior audit, and either add new check IDs or justify "no new check required".
8. Print the one-line summary: `verdict=PASS|FAIL BLOCKER=N MAJOR=N MINOR=N parity_hash_stable=Y/N tests_delta=+-N promotion_ready=research|paper|small|scaled`.

## Severity rules

- `BLOCKER` — fails a platform invariant outright; halts promotion to a higher operating mode.
- `MAJOR` — drift from a skill contract; must be resolved before the next iteration.
- `MINOR` — hygiene; tracked but not gating.

A finding flagged in the **Risk register** below is *permanent* until verifiably fixed; permanent BLOCKERs do not increment the "new BLOCKER" counter for the iteration verdict.

---

## Pillar A — Structural Audit (plumbing & invariants)

### A1. Layer separation & hidden state — Inv 8 (`system-architect`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-LAYER-01` | Glob `src/feelies/**/*.py`, bucket by top-level directory, then grep cross-layer imports (e.g. `from feelies.execution.passive_limit_router` inside `src/feelies/risk/`). | Every module belongs to exactly one of the 17 layers (Ingestion, Event Bus, Sensors, Features, Signals, Composition, Intent & Sizing, Risk Engine, Execution Engine, Alpha Module System, Portfolio, Storage, Monitoring, Services, Research, Forensics, CLI) plus the Kernel layer. Zero cross-layer imports outside the kernel/bootstrap composition sites. | BLOCKER |
| `A-LAYER-02` | Grep `^_[A-Z_]+ = ` and `^global ` in `src/feelies/{kernel,risk,execution,features}/`. | No module-level mutable singletons in hot-path layers. | MAJOR |
| `A-LAYER-03` | Grep instantiation of `BasicRiskEngine`, `MemoryPositionStore`, `BacktestOrderRouter`, `PassiveLimitOrderRouter`, `BudgetBasedSizer`, `SignalPositionTranslator`, `SensorRegistry`, `HorizonSignalEngine`, `CompositionEngine`, `StrategyPositionStore`, `FillAttributionLedger` across the repo. | All concrete instantiations live only in `src/feelies/bootstrap.py` and `tests/`. | MAJOR |

### A2. Event-bus & typed-schema discipline — Inv 7 (`system-architect`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-EVENT-01` | Grep `bus.publish(` and `\.publish(` in `src/feelies/`. Each call must publish an `Event` subclass, not raw `dict` / `tuple`. | Every cross-layer payload is a frozen `Event` subclass declared in `src/feelies/core/events.py`. | BLOCKER |
| `A-EVENT-02` | Read `src/feelies/bus/event_bus.py` `subscribe`. | Subscription enforces type filtering: `subscribe(EventType, handler)` rejects untyped or wrong-typed handlers. | MAJOR |
| `A-EVENT-03` | Grep constructors of all `Event` subclasses; check that `correlation_id`, `timestamp_ns`, `sequence` are required (no defaulted `None`). | All three fields propagate end-to-end (ingestion -> fill). | BLOCKER |

### A3. Clock abstraction — Inv 10 (`system-architect`, `backtest-engine`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-CLOCK-01` | Grep `datetime.now(`, `time.time(`, `time.monotonic(` under `src/feelies/`, exclude `core/clock.py` and `monitoring/`. | Zero hits outside the allowed files. | BLOCKER |
| `A-CLOCK-02` | Read `src/feelies/core/clock.py` `SimulatedClock.set_time` and `tests/core/`. | Monotonicity guard exists and is exercised by at least one test. | MAJOR |

### A4. State-machine integrity — Inv 5, 11 (`system-architect`, `testing-validation`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-SM-01` | Confirm files exist: `kernel/macro.py` (MacroState), `kernel/micro.py` (MicroState), `execution/order_state.py` (OrderState), `risk/escalation.py` (RiskLevel), `ingestion/data_integrity.py` (DataHealth). | All five state machines present and frozen. | BLOCKER |
| `A-SM-02` | Read `src/feelies/core/state_machine.py` `__init__`. | Constructor triggers enum-completeness check on the SM definition. | MAJOR |
| `A-SM-03` | Grep `except IllegalTransition` outside `tests/`. | Zero hits (never swallowed). | BLOCKER |
| `A-SM-04` | Read `Orchestrator.__init__`. | A `TransitionRecord`/`StateTransition` callback is wired so every transition emits an event. | MAJOR |
| `A-SM-05` | Read `Orchestrator.unlock_from_lockdown` and `_escalate_risk`. | `RiskLevel` is monotonic; only `LOCKED -> NORMAL` is allowed via `unlock_from_lockdown(audit_token=...)` with a zero-exposure guard. | BLOCKER |

### A5. Backtest/live parity surface — Inv 9 (`live-execution`, `backtest-engine`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-PARITY-01` | Grep `backend.mode`, `OperatingMode\.`, `if mode ==` outside `bootstrap.py` and `core/platform_config.py`. | Zero hits — `ExecutionBackend` is the only mode-discriminating abstraction. | BLOCKER |
| `A-PARITY-02` | Read `Orchestrator._process_tick`. | No mode branch. | BLOCKER |
| `A-PARITY-03` | Read `bootstrap._create_backend` table and compare with the system-architect skill composition table. | `(clock x MarketDataSource x OrderRouter)` per mode matches. | MAJOR |

### A6. Fail-safe defaults — Inv 11 (`risk-engine`, `live-execution`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-FAIL-01` | Read `_process_tick` M5/M6 branches. | Every `RiskAction` enum value has an explicit branch and `else: raise ValueError(...)` exists. | BLOCKER |
| `A-FAIL-02` | Read `_apply_ack_to_order`. | Unknown `OrderAckStatus` raises. | MAJOR |
| `A-FAIL-03` | Read `KillSwitch.activate`. | Irreversible without `unlock_from_lockdown(audit_token=...)`. | BLOCKER |
| `A-FAIL-04` | Read `src/feelies/signals/horizon_engine.py` `HorizonSignalEngine._evaluate_one`. | Does not publish a `SignalEvent` when `event.warm is False` (cold-start / warm-up guard); regime gate evaluated before signal; gate `OFF` suppresses evaluation. `CompositeSignalEngine` was deleted by Workstream D.2 PR-2b-ii — `src/feelies/alpha/composite.py` must no longer exist. | BLOCKER |

### A7. Determinism & provenance — Inv 5, 13 (`backtest-engine`, `testing-validation`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-DET-01` | Grep `uuid4` under `src/feelies/execution/` and `src/feelies/kernel/`. | Zero hits; order IDs use `hashlib.sha256(f"{correlation_id}:{seq}")`. | BLOCKER |
| `A-DET-02` | Run `python scripts/run_backtest.py --demo` twice; diff parity hashes. | Bit-identical hashes. Both recorded in report. | BLOCKER |
| `A-DET-03` | Run bootstrap on `platform.yaml`; capture `PlatformConfig.snapshot().checksum`; re-snapshot from the same loaded config. | Checksum identical across snapshots, logged in bootstrap output. | MAJOR |
| `A-DET-04` | Read `scripts/run_backtest.py` event-loading path. | Events are sorted by global `exchange_timestamp_ns` before resequencing, not per-`(symbol, day)`. If still per-day, log as MAJOR finding. | MAJOR |

### A8. Performance measurement plumbing — `performance-engineering`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-PERF-01` | Grep `tick_to_decision_latency_ns` in `src/feelies/kernel/orchestrator.py`. | Emitted as `MetricEvent` at M10. | MAJOR |
| `A-PERF-02` | Read `_process_tick`. | Per-segment scoped timers around M0->M1 ... M9->M10 (or equivalent). | MINOR |
| `A-PERF-03` | Grep `logger\.(debug\|info)\(f"` inside `_process_tick`. | No eager-format logging without level guard in the hot path. | MAJOR |
| `A-PERF-04` | Grep `asyncio`, `Thread\(`, `concurrent\.futures`, `multiprocessing` inside `src/feelies/kernel/orchestrator.py`. | None inside `_process_tick` (single-thread invariant). | BLOCKER |

### A8b. Performance budget enforcement — `performance-engineering`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-PERFB-01` | Run `pytest -m "backtest_validation and not slow"`. Record wall time. | <=25% regression vs prior report. | MAJOR |
| `A-PERFB-02` | Read p50/p95/p99 of `tick_to_decision_latency_ns` from the `--demo` MetricEvent stream (or synthesize from logged samples). | p99 <= 10 ms (hard ceiling). p95 should approach the 3 ms target. | BLOCKER (hard ceiling), MAJOR (target drift) |
| `A-PERFB-03` | Compute events/sec on the demo replay. | <=25% regression vs prior report. | MAJOR |

### A9. Test-coverage spine — `testing-validation`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-TEST-01` | Glob `tests/*/`; confirm presence of one sibling test directory per `src/feelies/` layer. | Every layer has at least one non-empty test directory. | MAJOR |
| `A-TEST-02` | Grep `from hypothesis` under `tests/`. Map results to the 9 invariants in the testing-validation skill (causal ordering, deterministic replay, position conservation, monotonic risk, PnL decomposition, clock monotonicity, idempotent submission, SM validity, enum completeness). | Each of the 9 invariants has at least one property-based test. | MAJOR |
| `A-TEST-03` | Run `pytest -q`. Record total / passed / failed / skipped / xfailed and exit code. | exit code = 0; failed/error = 0; deltas vs prior report logged. | BLOCKER (any new failure) |

### A10. Data ingestion fidelity — `data-engineering`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-DATA-01` | Grep constructions of `NBBOQuote(` / `Trade(` outside `src/feelies/ingestion/` and `tests/`. | Zero hits; `MassiveNormalizer` is the sole ingestion entry point. | BLOCKER |
| `A-DATA-02` | Read `MassiveNormalizer._check_gap`. | Flips `DataHealth` to `GAP_DETECTED` on gap; recovery path back to `HEALTHY` exists. | BLOCKER |
| `A-DATA-03` | Read `MassiveNormalizer` dedup branch. | `duplicates_filtered` counter increments on exact duplicate; `IngestResult` reports it. | MAJOR |
| `A-DATA-04` | Grep `make_correlation_id(` and any reassignment of `correlation_id`. | Assigned once at the ingestion boundary; never re-assigned downstream. | BLOCKER |
| `A-DATA-05` | Grep mutating methods on `EventLog` implementations. | Only `append` / `append_batch`; no `update` / `delete`. | BLOCKER |
| `A-DATA-06` | Confirm `EventSerializer` Protocol at `src/feelies/core/serialization.py`. Then grep `bootstrap.py` for a concrete durable backend (disk/DB implementation, not `InMemory`). | Protocol exists with `serialize`/`deserialize` — PASS on presence. Record `MAJOR` if no concrete durable backend is wired; the Protocol alone does not satisfy replay durability. | MAJOR (until durable backend wired) |

### A11. Regime engine integration — `regime-detection`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-REGIME-01` | Read `bootstrap.py` Phase-2 and Phase-3 wiring. | A single shared `RegimeEngine` is composed via `get_regime_engine(name)` and threaded into risk engine, sizer, and signal engines. A `RegimeHazardDetector` (`services/regime_hazard_detector.py`) is wired as a Phase-2 subscriber and emits hazard events on regime-change threshold breach. | MAJOR |
| `A-REGIME-02` | Grep mutation of `RegimeState` outside `src/feelies/services/regime_engine/`. | Only the regime engine writes; consumers read. | MAJOR |
| `A-REGIME-03` | Read `src/feelies/risk/position_sizer.py` `BudgetBasedSizer`. | Regime scalars (`vol_breakout` -> 0.5x, etc.) actually applied. | MAJOR |
| `A-REGIME-04` | Confirm conservative-divergence rule is documented or implemented; permanent finding until forensic regime is online. | Record state in report. | MAJOR (permanent until forensics online) |
| `A-REGIME-05` | Inspect alpha YAMLs under `alphas/`. | Regime calibration artifact (e.g. `regime_calibration.json`) is versioned and referenced. | MAJOR |

### A12. Safety mechanisms triad — `live-execution`, `risk-engine`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-SAFE-01` | Read `KillSwitch` implementation. | Present; irreversible without `unlock_from_lockdown(audit_token=...)`; zero-exposure guard enforced. | BLOCKER |
| `A-SAFE-02` | Search for a circuit-breaker class distinct from KillSwitch. | Present and cancels open orders without flattening. If absent, record permanent BLOCKER for promotion. | BLOCKER for promotion |
| `A-SAFE-03` | Search for a capital-throttle class distinct from KillSwitch. | Present as a dynamic sizing scalar driven by health signals. If absent, record permanent BLOCKER for promotion. | BLOCKER for promotion |
| `A-SAFE-04` | Grep typed events emitted by each safety mechanism. | All three emit typed events on the bus (`KillSwitchActivation` exists; circuit-breaker / throttle equivalents must exist when added). | MAJOR |
| `A-SAFE-05` | Read each mechanism's trigger predicate. | Each can halt independently; no AND-coupling that makes one a no-op. | BLOCKER |

### A13. Persistence durability — `data-engineering`, `live-execution`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-PERSIST-01` | Read `bootstrap.build_platform`. | Inventory in-memory backends used (`InMemoryEventLog`, `InMemoryTradeJournal`, `InMemoryFeatureSnapshotStore`, `InMemoryKillSwitch`, `InMemoryAlertManager`, `InMemoryMetricCollector`); each acceptable for backtest only. | MAJOR |
| `A-PERSIST-02` | Confirm absence of durable backends. | Permanent BLOCKER for promotion to PAPER/LIVE recorded in the risk register. | BLOCKER for promotion |
| `A-PERSIST-03` | Call `build_platform(config)` twice on the same config. | Identical `config_snapshot.checksum` and equivalent component graph. | MAJOR |
| `A-PERSIST-04` | Look for a feature-snapshot warm-start round-trip test. | Test exists and passes (checkpoint -> restore -> next event = same `FeatureVector`). If absent, record MAJOR. | MAJOR |

### A14. Secrets & credentials handling — `live-execution`, `data-engineering`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-SEC-01` | Grep `MASSIVE_API_KEY`, `BROKER_`, `secret`, `token`, `password`, `Bearer ` under `src/`, `scripts/`, `alphas/`, `platform.yaml`. | All credentials resolve from environment variables or an external secrets store; zero literal credential values in source. | BLOCKER for promotion |

### A15. Three-layer alpha architecture — `system-architect`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-THREE-01` | Read `src/feelies/alpha/loader.py` constructor parameters and `src/feelies/core/platform_config.py`. | `AlphaLoader` exposes `enforce_layer_gates` (default `True`) and `enforce_trend_mechanism` (default `True`); `PlatformConfig` carries matching flags; both flow into bootstrap. | MAJOR |
| `A-THREE-02` | Read `src/feelies/sensors/registry.py` `SensorRegistry` and `bootstrap.py` Phase-2 wiring. | `SensorRegistry` is instantiated in bootstrap; every sensor spec in `PlatformConfig.sensor_specs` is registered before the event loop starts. | MAJOR |
| `A-THREE-03` | Read `src/feelies/signals/horizon_engine.py` `HorizonSignalEngine` and `src/feelies/signals/regime_gate.py` `RegimeGate`. | Each registered signal carries a compiled `RegimeGate`; engine skips evaluation when gate is `OFF`; gate is parsed from the `regime_gate:` YAML block at load time with forbidden-AST node checking (`UnsafeExpressionError`). | BLOCKER |
| `A-THREE-04` | Read `src/feelies/composition/engine.py` `CompositionEngine` and bootstrap Phase-4 wiring. | `CompositionEngine` is instantiated in bootstrap; subscribed to `Signal` events; produces `SizedPositionIntent` for PORTFOLIO-layer alphas. | MAJOR |

### A16. Promotion lifecycle integrity — `testing-validation`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `A-PROMO-01` | Read `src/feelies/alpha/lifecycle.py` `AlphaLifecycleState` enum and the `_ALLOWED_TRANSITIONS` table. | States: RESEARCH → PAPER → LIVE; LIVE → QUARANTINED → PAPER (revalidation); LIVE → LIVE (capital-tier escalation). Transition matrix is enforced by `StateMachine`; no unlisted transition is reachable. | BLOCKER |
| `A-PROMO-02` | Read `src/feelies/alpha/promotion_ledger.py` `PromotionLedger`. | Append-only JSONL ledger; every committed lifecycle transition is durably written (pre-commit semantics: ledger write failure rolls back the state transition, leaving no half-promoted alpha). | MAJOR |
| `A-PROMO-03` | Read `src/feelies/alpha/promotion_evidence.py` `GateId` and `GATE_EVIDENCE_REQUIREMENTS`. | Each `(from_state, to_state)` gate is wired to typed evidence requirements; `GateId` enum is exhaustive over all lifecycle transitions. | MAJOR |

---

## Pillar B — Causal-Chain Audit (institutional-grade trading rigor)

The chain: `quote -> feature -> signal -> intent -> risk -> order -> ack -> fill -> position -> PnL -> guards -> decay -> promotion`.

### B1. Mechanism-before-trade — Inv 1, 2 (`microstructure-alpha`, `post-trade-forensics`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-MECH-01` | Grep `hypothesis:` and `falsification_criteria:` in every `alphas/**/*.alpha.yaml`. | Both keys present in every alpha YAML. | BLOCKER |
| `B-MECH-02` | Read each `falsification_criteria` block. | Each entry references a metric the forensics layer can compute from `TradeRecord` / `EventLog` (e.g. "OOS DSR < 1.0"); text-only narratives are fail. | MAJOR |
| `B-MECH-03` | Grep `risk_budget:` block in alpha YAMLs and `AlphaBudgetRiskWrapper` consumers. | Each alpha has a `risk_budget` consumed by `src/feelies/alpha/risk_wrapper.py`. | BLOCKER |
| `B-MECH-04` | Read each `hypothesis:` text. | Names a structural force in plain English; not a curve-fit narrative. | MAJOR |

### B2. Causality / no-lookahead — Inv 6 (`feature-engine`, `backtest-engine`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-CAUSAL-01` | Read each `computation_module` referenced by alpha YAMLs (`alphas/trade_cluster_drift/`, etc.). | `update(quote)` uses only `quote` plus prior internal state. | BLOCKER |
| `B-CAUSAL-02` | Read `src/feelies/signals/horizon_engine.py` `HorizonSignalEngine._evaluate_one`. | Does not evaluate or publish when `event.warm is False` (cold-start / warm-up guard). `CompositeSignalEngine` was deleted by Workstream D.2 — any surviving import is itself a BLOCKER. | BLOCKER |
| `B-CAUSAL-03` | Read routers (`src/feelies/execution/backtest_router.py`, `src/feelies/execution/passive_limit_router.py`). | Order decisions use last-seen NBBO at ack time, not signal time. | BLOCKER |
| `B-CAUSAL-04` | Grep `Clock.now`, `clock.now` in `src/feelies/{ingestion,bus,kernel}/` outside monitoring/metric paths. | Replay-relevant timestamps use ingestion `exchange_timestamp_ns`, never `Clock.now()`. | BLOCKER |

### B3. Two-phase risk gate — `risk-engine`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-RISK-01` | Read `_process_tick` M5 and M6. | Both `check_signal` (M5) and `check_order` (M6) called for every order; no path constructs an `OrderRequest` without both. | BLOCKER |
| `B-RISK-02` | Read NO_ACTION branch. | Skips M5-M9 and goes to M10. | MAJOR |
| `B-RISK-03` | Read SCALE_DOWN branch. | Applies `verdict.scaling_factor` before submission, then re-checks via `check_order`. | BLOCKER |
| `B-RISK-04` | Read `src/feelies/risk/basic_risk.py` and the risk-engine skill table. | Drawdown gate thresholds (warning / throttle / circuit / kill) match, or any divergence is documented. | MAJOR |

### B4. Position sizing & intent translation — `risk-engine`, `system-architect`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-SIZE-01` | Read `BudgetBasedSizer.compute_target_quantity`. | Consumes regime state (regime scalars present). | MAJOR |
| `B-SIZE-02` | Same. | Caps at the alpha's declared `max_position_per_symbol`. | BLOCKER |
| `B-SIZE-03` | Read `SignalPositionTranslator.translate` (`intent.py`). | Covers the full `(SignalDirection x Position)` matrix with explicit branches. | BLOCKER |
| `B-SIZE-04` | Grep `platform_min_order_shares`. | Enforced after sizing and before routing, at exactly one site. | MAJOR |

### B5. Order-lifecycle & idempotency — `live-execution`, `backtest-engine`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-ORDER-01` | Grep `_active_orders` in `Orchestrator`. | Every order has an SHA-256 ID and lives in `_active_orders` until terminal. | BLOCKER |
| `B-ORDER-02` | Read ack-handling switch. | Exhaustive over `OrderAckStatus`, including auto-ack of `SUBMITTED` on early `FILLED` and alerts on inapplicable transitions. | MAJOR |
| `B-ORDER-03` | Read `Orchestrator.cancel_order`. | Transitions only `ACKNOWLEDGED -> CANCEL_REQUESTED`; `PARTIALLY_FILLED` cannot cancel. | MAJOR |
| `B-ORDER-04` | Read router `submit_order` boundary. | Duplicate `order_id` from replay is dropped; if absent, MAJOR. | MAJOR |

### B6. Fill model realism — Inv 12 (`backtest-engine`, `post-trade-forensics`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-FILL-01` | Read `DefaultCostModelConfig`. | Components present: spread, commission (taker/maker), adverse selection, regulatory, stress multiplier. | BLOCKER |
| `B-FILL-02` | Run `python scripts/run_backtest.py --demo --stress-cost 1.5`. | Run completes; net PnL >= 0 at portfolio level (or affected alpha quarantined per `post-trade-forensics`). | BLOCKER |
| `B-FILL-03` | Read `PassiveLimitOrderRouter`. | Through-fill and level-fill triggers present; cancel after `passive_max_resting_ticks`. | MAJOR |
| `B-FILL-04` | Grep router selection in stop-loss path. | Stop-loss / emergency exits use MARKET orders, not passive (Inv 11). | BLOCKER |

### B7. Position & PnL reconciliation — `risk-engine`, `live-execution`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-PNL-01` | Read `_reconcile_fills`. | Updates `MemoryPositionStore` atomically and emits `PositionUpdate` + `TradeRecord`. | BLOCKER |
| `B-PNL-02` | Read `TradeRecord` schema. | gross / realized / unrealized / fees / slippage computable per trade. | MAJOR |
| `B-PNL-03` | Run a `--demo` with two test alphas (or rely on existing demo if multi-alpha) and sum `StrategyPositionStore` + `FillAttributionLedger`. | Sum equals portfolio totals. | MAJOR |
| `B-PNL-04` | Read mark-to-market drawdown trigger. | Per-tick MtM DD computed against last NBBO mid; trigger path into `_escalate_risk` exists. | BLOCKER |

### B8. End-to-end live-practice replay — `testing-validation`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-E2E-01` | `python scripts/run_backtest.py --demo`. | Capture: parity hash, trade count, gross/net PnL, max DD, kill-switch state. | BLOCKER (run failure) |
| `B-E2E-02` | Run twice. | Bit-identical parity hashes. | BLOCKER |
| `B-E2E-03` | Run with `--stress-cost 1.5` and `--stress-cost 2.0`. | PnL >= 0 at portfolio level OR any negative alpha is quarantined. | BLOCKER |
| `B-E2E-04` | Read `tests/test_backtest_e2e.py`. | Covers warm-up, regime transitions, circuit-breaker firing, reconnect/gap, multi-alpha arbitration. Each missing scenario opens a `MAJOR` finding with the test stub to add. | MAJOR (per gap) |
| `B-E2E-05` | Check existence of `src/feelies/execution/paper_router.py` and `src/feelies/execution/live_router.py`. Then read `bootstrap._create_backend`. | Router stub files `paper_router.py` and `live_router.py` exist. However `_create_backend` still raises `NotImplementedError` for non-BACKTEST modes — stubs are not yet wired. Permanent BLOCKER for promotion until `_create_backend` fully integrates paper/live backends. | BLOCKER for promotion |

### B9. Provenance & audit trail — Inv 13 (`testing-validation`, `data-engineering`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-PROV-01` | Read `TradeRecord`. | Carries `correlation_id`, `signal_ts`, `submit_ts`, `fill_ts`. | BLOCKER |
| `B-PROV-02` | Grep `EventLog.append(` in M1 path and `_process_trade`. | Called for every quote and every trade. | BLOCKER |
| `B-PROV-03` | Capture `PlatformConfig.snapshot().checksum` and record in report. | Recorded; diffable across iterations. | MAJOR |
| `B-PROV-04` | Read alpha YAMLs and registry. | Every alpha has `version` + `schema_version`; registry `lifecycle` state recorded. | MAJOR |

### B10. Personal-trading guardrails — `risk-engine`, `live-execution`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-GUARD-01` | Read stop-loss branch in `_process_tick`. | `stop_loss_per_share` evaluated per tick from last NBBO mid; exit issued via MARKET; not gated by passive cooldowns. | BLOCKER |
| `B-GUARD-02` | Read trailing-stop tracker. | `trail_activate_per_share` + `trail_pct` peak tracker is per-position, resets on flat/flip; peak monotonic (cannot move adversely). | BLOCKER |
| `B-GUARD-03` | Read `src/feelies/signals/regime_gate.py` `RegimeGate` and `HorizonSignalEngine._evaluate_one`. | Entry cooldown state is tracked per-(alpha_id, symbol) inside `RegimeGate`; not a global counter; resets on EXIT. `CompositeSignalEngine` was deleted by Workstream D.2 — cooldown now lives in the signal layer. | MAJOR |
| `B-GUARD-04` | Grep `platform_min_order_shares`. | Enforced at exactly one place, after sizing and before routing. | MAJOR |
| `B-GUARD-05` | Read sizing input wiring. | `account_equity` semantics (start-of-day NAV vs live MtM) recorded; flag any mismatch with the alpha YAML's risk-budget assumption. | MAJOR |
| `B-GUARD-06` | Grep `float(`, bare `float` annotations on price / quantity / PnL fields in `risk/`, `execution/`, `portfolio/`. | Money fields are `Decimal` end-to-end. | BLOCKER |

### B11. Multi-alpha arbitration & attribution — `system-architect`, `risk-engine`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-MULTI-01` | Read `bootstrap.py` Phase-3/4 wiring and `src/feelies/kernel/orchestrator.py` `__init__`. | `MultiAlphaEvaluator` was deleted by Workstream D.2 PR-2b-iv. Multi-alpha coordination is bus-driven: SIGNAL-layer alphas publish `Signal` events buffered by `_on_bus_signal`; PORTFOLIO-layer alphas publish `SizedPositionIntent` events handled by `_on_bus_sized_intent`. Confirm both subscribers are registered in `Orchestrator.__init__`. | MAJOR |
| `B-MULTI-02` | Read `src/feelies/alpha/arbitration.py` `SignalArbitrator` Protocol and `EdgeWeightedArbitrator`. | `SignalArbitrator` is a Protocol with `EdgeWeightedArbitrator` as the default implementation: highest `edge_estimate_bps * strength` wins; dead-zone suppresses low-conviction signals. Same inputs → same outcome. Confirm it is invoked in the `_on_bus_signal` buffer-drain path inside the orchestrator. | BLOCKER |
| `B-MULTI-03` | Read `AlphaBudgetRiskWrapper`. | Per-strategy risk isolated; one alpha's drawdown cannot consume another's allocation. | BLOCKER |
| `B-MULTI-04` | Run `--demo` with two test alphas; sum `FillAttributionLedger` totals against `MemoryPositionStore`. | Sum equals portfolio totals. | MAJOR |
| `B-MULTI-05` | Read alpha YAMLs / risk config. | Cross-strategy correlation budget documented; if absent, permanent finding. | MAJOR |

### B12. Promotion-gate readiness — Inv 3 (`testing-validation`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-PROMO-01` | Walk the testing-validation skill's Research -> Paper criteria. | Each criterion gets a yes/no with evidence in the report. | n/a (records readiness) |
| `B-PROMO-02` | Confirm presence of paper router and sim-vs-live divergence baseline. | Until paper router exists, automatic NO. | n/a (records readiness) |
| `B-PROMO-03` | Confirm presence of >=10 trading days of small-capital live data. | Without it, automatic NO. | n/a (records readiness) |
| `B-PROMO-04` | Compute `hash(strategy_version, config_version, data_version, engine_version)` for the demo run. | Same inputs across two consecutive audits yield same id. | BLOCKER (drift) |

### B13. Decay-detection plumbing — Inv 4 (`post-trade-forensics`)

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-DECAY-01` | Read `src/feelies/forensics/`. | Forensic computations (slippage residual, hit-rate residual, alpha-erosion, fill-rate drift) reachable from `TradeJournal.query()`. | MAJOR |
| `B-DECAY-02` | Read crowding scorecard logic. | 3+ symptom rule wireable on `TradeRecord` + `EventLog` data. | MAJOR |
| `B-DECAY-03` | Read latency-disadvantage computation. | Computable from `signal_ts` / `submit_ts` / `fill_ts` in `TradeRecord`. | MAJOR |
| `B-DECAY-04` | Trace forensic finding -> `Alert` event -> risk scaling. | Quarantine pathway exists or is recorded as a tracked permanent finding. | MAJOR |

### B14. Sensor-to-signal pipeline & hazard controls — `system-architect`

| ID | Method | Pass criterion | Severity if fail |
|---|---|---|---|
| `B-SENSOR-01` | Read `bootstrap.py` Phase-2 and `src/feelies/features/aggregator.py` `HorizonAggregator`. | Sensor output events flow into `HorizonAggregator`; aggregated `HorizonSnapshot` events flow to `HorizonSignalEngine`. No sensor output bypasses the aggregator to reach signal evaluation. | BLOCKER |
| `B-HAZARD-01` | Read `src/feelies/risk/hazard_exit.py` `HazardExitController` and bootstrap wiring. | `HazardExitController` is instantiated in bootstrap; subscribed (via bus) to hazard events emitted by `RegimeHazardDetector`; responds by issuing typed MARKET exit events — does not directly mutate positions. | BLOCKER |
| `B-HAZARD-02` | Read `src/feelies/services/regime_hazard_detector.py` `RegimeHazardDetector`. | Subscribes to `RegimeSnapshot` events; emits a typed `HazardEvent` when regime-change thresholds are breached; read-only with respect to positions and orders. | MAJOR |

---

## Pass/Fail criteria for an iteration

An audit iteration is a **PASS** iff **all** of the following hold:

1. Zero **new** `BLOCKER` findings vs prior report (permanent BLOCKERs in the risk register do not count).
2. `MAJOR` count is non-increasing vs prior report.
3. `pytest` exit code is 0; failed/error counts are 0.
4. `--demo` parity hash is bit-identical across two back-to-back runs.
5. `--demo --stress-cost 1.5` net PnL is `>= 0` at the **portfolio** level. An individual alpha may be net negative under stress only if it is concurrently flagged for quarantine in this report's risk register per `post-trade-forensics`; otherwise FAIL.
6. p99 of `tick_to_decision_latency_ns` does not exceed the 10 ms hard ceiling.

Any FAIL halts promotion to a higher operating mode (BACKTEST -> PAPER -> LIVE) until the next PASS.

## Cadence & triggers

The audit runs:

- On every merge to `main` (CI invocation, agent-driven).
- Before any `mode:` switch in `platform.yaml` (BACKTEST -> PAPER, PAPER -> LIVE).
- On every change to `.cursor/rules/` or `.cursor/skills/` (the audit's source of truth changed).
- On every change to `src/feelies/bootstrap.py`, `src/feelies/kernel/orchestrator.py`, `src/feelies/risk/`, `src/feelies/execution/`, `src/feelies/ingestion/`, `src/feelies/alpha/`, `src/feelies/sensors/`, `src/feelies/signals/`, `src/feelies/composition/`, `src/feelies/services/`, `src/feelies/core/events.py`, or `src/feelies/core/state_machine.py` (high-blast-radius modules).
- Weekly regardless, against latest `main`, to catch drift that escaped per-PR audits.

A new `BLOCKER` auto-halts promotion until resolved. A new permanent risk-register entry requires explicit user acknowledgement before the next mode switch.

## Risk register (seeded at first run)

Permanent findings re-surfaced every iteration so they cannot fade from view. The agent re-prints the current register in every report and only removes an entry when the next iteration verifies it fixed.

Initial seed (first iteration may add to or replace this list based on what the structural audit actually finds):

- **Persistence**: storage backends are in-memory only — `BLOCKER for promotion` to PAPER/LIVE.
- **Paper / live router stubs only**: `paper_router.py` and `live_router.py` exist under `src/feelies/execution/` but `bootstrap._create_backend` still raises `NotImplementedError` for non-BACKTEST modes — `BLOCKER for promotion` to PAPER/LIVE.
- **`EventSerializer` Protocol exists; no durable backend**: `EventSerializer` Protocol is defined at `src/feelies/core/serialization.py` with correct `serialize`/`deserialize` contract. No concrete durable (disk/DB) backend is wired in `bootstrap.py` — `MAJOR` until a durable implementation is wired for PAPER/LIVE replay.
- **Sim-vs-live divergence harness absent**: cannot run drift tests until live router exists — `BLOCKER for promotion` to LIVE.
- **Circuit breaker / capital throttle**: separate-from-kill-switch mechanisms not visibly present — confirm or upgrade to `BLOCKER for promotion`.
- **Session calendar absent**: no NYSE/NASDAQ market-hours awareness in code path — `MAJOR` for paper-trading realism.
- **Multi-symbol global timestamp sort**: `scripts/run_backtest.py` may resequence per-(symbol, day), not globally — `MAJOR` for any multi-symbol run.

## Meta-rule (`META-01`, audit-of-the-audit)

The protocol itself decays. Whenever `.cursor/rules/platform-invariants.mdc` changes, or any file under `.cursor/skills/` is added or materially edited, the next audit iteration must:

1. Add at least one new check ID covering the new invariant or skill clause, **OR**
2. Justify in the report's `META-01` section why no new check is required (existing IDs cover it).

`META-01` is itself recorded in every report.
