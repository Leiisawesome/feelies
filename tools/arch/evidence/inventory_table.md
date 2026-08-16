| module | sloc | public | declared responsibility (docstring — a claim) |
|---|---|---|---|
| `src/feelies/__init__.py` | 1 | 0 | Feelies — deterministic intraday trading platform. |
| `src/feelies/__main__.py` | 11 | 0 | Top-level ``python -m feelies`` entry-point. |
| `src/feelies/alpha/__init__.py` | 63 | 0 | Pluggable alpha module system. |
| `src/feelies/alpha/arbitration.py` | 125 | 6 | Signal arbitration — conflict resolution when multiple alphas fire. |
| `src/feelies/alpha/cost_arithmetic.py` | 191 | 3 | G12 validation for alpha cost disclosures. |
| `src/feelies/alpha/dependency_graph.py` | 234 | 6 | Static feature-dependency graph for SIGNAL alphas. |
| `src/feelies/alpha/discovery.py` | 108 | 3 | Alpha spec discovery — scan a directory for .alpha.yaml files. |
| `src/feelies/alpha/fill_attribution.py` | 172 | 5 | Fill attribution ledger — maps net fills back to per-alpha contributions. |
| `src/feelies/alpha/layer_validator.py` | 1154 | 15 | Three-layer architecture validation gates. |
| `src/feelies/alpha/loader.py` | 1246 | 2 | Parse ``.alpha.yaml`` specs into typed layer modules. |
| `src/feelies/alpha/module.py` | 130 | 4 | Alpha metadata and layer-specific module protocols. |
| `src/feelies/alpha/portfolio_layer_module.py` | 246 | 3 | Loaded representation of ``layer: PORTFOLIO`` alphas. |
| `src/feelies/alpha/registry.py` | 367 | 3 | Alpha registry — lifecycle management for pluggable alpha modules. |
| `src/feelies/alpha/risk_wrapper.py` | 321 | 1 | Per-alpha risk budget wrapper with drawdown enforcement. |
| `src/feelies/alpha/signal_layer_module.py` | 186 | 1 | Loader artifact for ``layer: SIGNAL`` alphas. |
| `src/feelies/alpha/validation.py` | 109 | 1 | Cross-alpha validation — feature conflicts, dependency cycles, coverage. |
| `src/feelies/bootstrap.py` | 1649 | 3 | Compose the platform from configuration. |
| `src/feelies/broker/__init__.py` | 6 | 0 | Broker adapters — concrete implementations of the OrderRouter protocol. |
| `src/feelies/broker/ib/__init__.py` | 16 | 0 | Interactive Brokers Gateway adapter (paper @ 4002 / live @ 4001). |
| `src/feelies/broker/ib/connection.py` | 379 | 2 | Threaded IB Gateway connection (EClient + EWrapper subclass). |
| `src/feelies/broker/ib/contracts.py` | 27 | 1 | IB ``Contract`` factory helpers. |
| `src/feelies/broker/ib/router.py` | 296 | 1 | IB order router — adapts :class:`IBGatewayConnection` to ``OrderRouter``. |
| `src/feelies/bus/__init__.py` | 3 | 0 | Event bus — deterministic event routing. |
| `src/feelies/bus/event_bus.py` | 53 | 1 | Synchronous, deterministic event bus (invariant 7). |
| `src/feelies/cli/__init__.py` | 10 | 0 | Read-only operator commands for promotion-ledger forensics. |
| `src/feelies/cli/__main__.py` | 10 | 0 | Module entry-point so ``python -m feelies <subcommand>`` works. |
| `src/feelies/cli/backtest.py` | 27 | 2 | ``feelies backtest`` subcommand — historical L1 replay via Massive API. |
| `src/feelies/cli/env.py` | 22 | 2 | Environment bootstrap for operator scripts (backtest, paper, tests). |
| `src/feelies/cli/forensics.py` | 237 | 1 | ``feelies forensics`` — post-trade analysis over a finished session. |
| `src/feelies/cli/main.py` | 103 | 1 | Top-level CLI dispatcher for the ``feelies`` console script. |
| `src/feelies/cli/promote.py` | 708 | 1 | ``feelies promote`` subcommand handlers. |
| `src/feelies/composition/__init__.py` | 21 | 0 | Layer-3 composition (PORTFOLIO) layer. |
| `src/feelies/composition/cross_sectional.py` | 512 | 4 | Convert signals to standardized cross-sectional weights. |
| `src/feelies/composition/engine.py` | 398 | 2 | ``CompositionEngine`` — converts ``CrossSectionalContext`` → ``SizedPositionIntent``. |
| `src/feelies/composition/factor_neutralizer.py` | 171 | 2 | Residualize cross-sectional weights against static factor loadings. |
| `src/feelies/composition/protocol.py` | 60 | 2 | Pure Layer-3 portfolio-alpha contract. |
| `src/feelies/composition/sector_matcher.py` | 93 | 1 | Optionally neutralize weights within each GICS sector. |
| `src/feelies/composition/synchronizer.py` | 257 | 1 | Barrier synchronization for cross-sectional contexts. |
| `src/feelies/composition/turnover_optimizer.py` | 300 | 5 | ``TurnoverOptimizer`` — translate target weights into target USD positions. |
| `src/feelies/core/__init__.py` | 19 | 0 | Core primitives shared across all layers. |
| `src/feelies/core/clock.py` | 31 | 3 | Injectable clock abstraction (platform invariant 10). |
| `src/feelies/core/config.py` | 49 | 2 | Typed configuration protocol — versioned and auditable (invariant 13). |
| `src/feelies/core/config_yaml.py` | 63 | 2 | YAML loading with optional ``extends:`` inheritance for platform configs. |
| `src/feelies/core/errors.py` | 52 | 11 | System-wide error hierarchy. |
| `src/feelies/core/events.py` | 502 | 31 | Typed event schemas for all inter-layer communication (invariant 7). |
| `src/feelies/core/identifiers.py` | 45 | 3 | Correlation IDs and sequence management for event provenance (invariant 13). |
| `src/feelies/core/inv12_stress.py` | 39 | 3 | Joint cost and latency stress harness for invariant 12. |
| `src/feelies/core/platform_config.py` | 1030 | 3 | YAML-loadable platform configuration with deterministic snapshots. |
| `src/feelies/core/serialization.py` | 113 | 4 | Deterministic JSON serialization for cached market-data events. |
| `src/feelies/core/session_clock.py` | 45 | 2 | Deterministic session-clock helpers anchored to the RTH open/close. |
| `src/feelies/core/state_machine.py` | 193 | 3 | Generic deterministic state machine framework. |
| `src/feelies/execution/__init__.py` | 9 | 0 | Execution engine layer — order routing and fill handling. |
| `src/feelies/execution/_fill_helpers.py` | 15 | 0 | Aggressive-fill constants shared by both routers. |
| `src/feelies/execution/backend.py` | 72 | 4 | ExecutionBackend — the ONLY mode-specific abstraction (invariant 9). |
| `src/feelies/execution/backtest_backend.py` | 184 | 2 | Backtest execution backend — composes ReplayFeed + order router. |
| `src/feelies/execution/backtest_router.py` | 330 | 1 | Deterministic simulated fills for backtests. |
| `src/feelies/execution/cost_model.py` | 421 | 7 | Transaction cost model for backtest fill realism (invariant 12). |
| `src/feelies/execution/intent.py` | 186 | 4 | Trading intent translator — Signal x Position -> OrderAction. |
| `src/feelies/execution/market_fill.py` | 271 | 5 | Shared aggressive-fill simulation for market and marketable-limit orders. |
| `src/feelies/execution/min_cost_policy.py` | 143 | 2 | Choose passive or aggressive execution from modeled per-order cost. |
| `src/feelies/execution/moc_fill.py` | 199 | 1 | Closing-auction fill simulation for backtest mode. |
| `src/feelies/execution/moc_session.py` | 112 | 6 | MOC session bounds for backtest closing-auction modeling. |
| `src/feelies/execution/order_admission.py` | 188 | 5 | Session, regulatory, and minimum-size admission gates — one definition each. |
| `src/feelies/execution/order_state.py` | 75 | 2 | Order lifecycle state machine (Section V of the system diagram). |
| `src/feelies/execution/paper_backend.py` | 54 | 1 | Paper-mode :class:`ExecutionBackend` factory. |
| `src/feelies/execution/passive_limit_router.py` | 796 | 2 | Deterministic L1 model for passive limit fills. |
| `src/feelies/execution/portfolio_netter.py` | 150 | 5 | Pure cross-alpha position netting. |
| `src/feelies/execution/position_manager.py` | 567 | 18 | Target-based position planning and compatibility comparison. |
| `src/feelies/execution/regulatory/__init__.py` | 31 | 0 | Backtest-modeled regulatory / structural fill constraints. |
| `src/feelies/execution/regulatory/borrow_availability.py` | 56 | 5 | Static per-symbol borrow tiers for backtest short entries. |
| `src/feelies/execution/regulatory/pdt_constraint.py` | 131 | 3 | Track pattern-day-trader round trips and the minimum-equity entry gate. |
| `src/feelies/execution/sized_intent_legs.py` | 148 | 4 | Turn a Layer-3 ``SizedPositionIntent`` target into a candidate order leg. |
| `src/feelies/execution/tick_size.py` | 42 | 4 | Reg NMS tick-size grid for simulated US equity prices. |
| `src/feelies/execution/trading_session.py` | 266 | 9 | RTH calendar and entry-fill gating for backtests. |
| `src/feelies/features/__init__.py` | 15 | 0 | Feature engine layer — stateful computation from event streams. |
| `src/feelies/features/aggregator.py` | 404 | 2 | Passive bridge from sensor readings to horizon snapshots. |
| `src/feelies/features/definition.py` | 68 | 3 | Declarative feature definitions used by registry test scaffolding. |
| `src/feelies/features/impl/__init__.py` | 0 | 0 | (no module docstring) |
| `src/feelies/features/impl/horizon_windowed.py` | 260 | 1 | Features over true event-time horizon windows. |
| `src/feelies/features/impl/rolling_stats.py` | 233 | 2 | Count-bounded rolling z-score and percentile features. |
| `src/feelies/features/impl/sensor_passthrough.py` | 190 | 3 | Sensor passthrough HorizonFeature implementations. |
| `src/feelies/features/protocol.py` | 66 | 1 | Contracts for horizon-aware Layer-2 features. |
| `src/feelies/forensics/__init__.py` | 26 | 0 | Post-trade edge-decay and execution-quality analysis. |
| `src/feelies/forensics/analyzer.py` | 59 | 3 | Forensic analyzer protocol — post-trade analysis contracts. |
| `src/feelies/forensics/cost_circuit_breaker.py` | 192 | 4 | Evaluate and apply cost-based alpha quarantine decisions. |
| `src/feelies/forensics/cost_survival.py` | 164 | 3 | Per-alpha realized edge-versus-cost reporting. |
| `src/feelies/forensics/decay_detector.py` | 155 | 1 | Decay detector — post-trade TCA and edge decay detection. |
| `src/feelies/forensics/decouple_backstop.py` | 84 | 2 | Quote-freeze / session-backstop forensic check for ``decouple_caps_only``. |
| `src/feelies/forensics/edge_calibration.py` | 145 | 3 | Calibrate disclosed edge estimates against realized fills. |
| `src/feelies/forensics/gate_close_attribution.py` | 211 | 4 | Reconstruct gate-close attribution across the SIGNAL→RISK stream migration. |
| `src/feelies/harness/__init__.py` | 53 | 0 | Shared harness helpers for backtest and replay operator scripts. |
| `src/feelies/harness/backtest_cli.py` | 272 | 8 | Shared config and argparse helpers for ``scripts/run_backtest.py``. |
| `src/feelies/harness/backtest_jsonl.py` | 270 | 12 | Deterministic stdout JSONL emitters for backtest parity streams. |
| `src/feelies/harness/backtest_prep.py` | 158 | 5 | Single-pass backtest event-log preparation. |
| `src/feelies/harness/backtest_report.py` | 739 | 13 | Backtest report formatting, parity hashes, and verification helpers. |
| `src/feelies/harness/backtest_runner.py` | 840 | 7 | Backtest runner — connects real Massive data to the platform pipeline. |
| `src/feelies/ingestion/__init__.py` | 32 | 0 | Market data ingestion layer — normalize Massive L1 NBBO into canonical events. |
| `src/feelies/ingestion/data_integrity.py` | 89 | 4 | Per-symbol data integrity state machine (Section VII of the system diagram). |
| `src/feelies/ingestion/idle_tick.py` | 25 | 1 | IdleTick sentinel — data-path control signal for live feeds. |
| `src/feelies/ingestion/ingest_health.py` | 42 | 3 | Aggregate ingestion-time DataHealth across (symbol, day) rows for backtest boot. |
| `src/feelies/ingestion/massive_ingestor.py` | 436 | 4 | Massive historical data ingestor (formerly Polygon.io) — batch ETL for backtest datasets. |
| `src/feelies/ingestion/massive_normalizer.py` | 767 | 1 | Massive normalizer (formerly Polygon.io) — transforms raw WebSocket and REST wire formats into canonical NBBOQuote / Trade events. |
| `src/feelies/ingestion/massive_ws.py` | 365 | 1 | Massive live WebSocket feed (formerly Polygon.io) — real-time L1 quote and trade streaming. |
| `src/feelies/ingestion/normalizer.py` | 52 | 1 | Market data normalizer protocol — the ingestion layer's core contract. |
| `src/feelies/ingestion/replay_feed.py` | 90 | 2 | Replay feed — generic MarketDataSource adapter over EventLog. |
| `src/feelies/kernel/__init__.py` | 9 | 0 | Kernel — system-wide state machines and orchestration. |
| `src/feelies/kernel/macro.py` | 90 | 2 | Global stack state machine (Section I–II of the system diagram). |
| `src/feelies/kernel/micro.py` | 138 | 2 | Micro-state machine for deterministic tick processing (Section III–IV). |
| `src/feelies/kernel/orchestrator.py` | 4778 | 1 | Coordinate deterministic platform state and tick processing. |
| `src/feelies/kernel/signal_order_trace.py` | 80 | 3 | Per-signal diagnostics for the standalone SIGNAL → order pipeline. |
| `src/feelies/monitoring/__init__.py` | 17 | 0 | Monitoring layer — cross-cutting observability. |
| `src/feelies/monitoring/alerting.py` | 41 | 1 | Alert routing protocol — threshold and anomaly-based notifications. |
| `src/feelies/monitoring/horizon_metrics.py` | 304 | 1 | Read-only composition and hazard-exit metrics. |
| `src/feelies/monitoring/in_memory.py` | 163 | 5 | In-memory monitoring implementations for backtest and testing. |
| `src/feelies/monitoring/kill_switch.py` | 45 | 1 | Kill switch protocol — emergency trading halt. |
| `src/feelies/monitoring/paper_session_recorder.py` | 199 | 3 | Forensic session recorder for PAPER-mode runs. |
| `src/feelies/monitoring/telemetry.py` | 17 | 1 | Monitoring and telemetry — cross-cutting observability layer. |
| `src/feelies/portfolio/__init__.py` | 3 | 0 | Portfolio layer — position tracking and PnL. |
| `src/feelies/portfolio/cross_sectional_tracker.py` | 146 | 2 | ``CrossSectionalTracker`` — per-strategy aggregated exposure metrics. |
| `src/feelies/portfolio/lot_ledger.py` | 112 | 2 | Per-symbol FIFO open-lot ledger for observability. |
| `src/feelies/portfolio/memory_position_store.py` | 163 | 1 | In-memory position store for backtest and testing. |
| `src/feelies/portfolio/position_store.py` | 98 | 2 | Position store interface — shared across backtest and live (invariant 9). |
| `src/feelies/portfolio/strategy_position_store.py` | 243 | 1 | Per-strategy position store with aggregate view. |
| `src/feelies/promotion/__init__.py` | 16 | 0 | Alpha lifecycle, promotion gates, and the append-only promotion ledger. |
| `src/feelies/promotion/evidence.py` | 1487 | 31 | Typed promotion evidence, gate requirements, and threshold validators. |
| `src/feelies/promotion/ledger.py` | 168 | 2 | Append-only JSONL ledger of committed alpha lifecycle transitions. |
| `src/feelies/promotion/lifecycle.py` | 713 | 8 | Alpha lifecycle state machine and promotion gates. |
| `src/feelies/research/__init__.py` | 57 | 0 | Deterministic research and promotion-significance utilities. |
| `src/feelies/research/cpcv.py` | 518 | 12 | Deterministic Combinatorial Purged Cross-Validation evidence. |
| `src/feelies/research/decouple_gates.py` | 232 | 5 | Stage-0 ``decouple_caps_only`` promotion-gate harness (design rev 5 §3.5). |
| `src/feelies/research/dsr.py` | 357 | 9 | Deterministic Deflated Sharpe Ratio evidence. |
| `src/feelies/research/forward_ic.py` | 191 | 6 | Forward-return and information-coefficient utilities. |
| `src/feelies/risk/__init__.py` | 16 | 0 | Risk engine layer — position limits, exposure checks, drawdown gates. |
| `src/feelies/risk/basic_risk.py` | 720 | 2 | Basic risk engine — first concrete RiskEngine implementation. |
| `src/feelies/risk/buying_power.py` | 48 | 3 | Reg-T buying-power limits for margin accounts. |
| `src/feelies/risk/deferral_cap.py` | 367 | 2 | Bounded-deferral cap — strategy-slice forced-exit author (design §2.3). |
| `src/feelies/risk/edge_weighted_sizer.py` | 204 | 8 | Tilt base position size by edge, volatility, and current inventory. |
| `src/feelies/risk/engine.py` | 75 | 1 | Risk engine protocol — the sole gatekeeper between signal and execution. |
| `src/feelies/risk/escalation.py` | 53 | 2 | Risk escalation state machine (Section VI of the system diagram). |
| `src/feelies/risk/exit_composer.py` | 387 | 7 | Risk-layer exit composer — actuates the §2.4 dual-permission table. |
| `src/feelies/risk/hazard_exit.py` | 221 | 2 | Hazard- and age-driven exit emitter. |
| `src/feelies/risk/position_sizer.py` | 98 | 2 | Position sizer — compute target quantity from risk budget and regime. |
| `src/feelies/risk/post_exit_position_view.py` | 63 | 1 | Read-only position projection used to risk-check reversal entry legs. |
| `src/feelies/risk/sized_intent_orders.py` | 86 | 1 | Admit or veto the legs of a Layer-3 ``SizedPositionIntent``. |
| `src/feelies/risk/sized_intent_result.py` | 13 | 1 | Structured result for PORTFOLIO :meth:`~feelies.risk.engine.RiskEngine.check_sized_intent`. |
| `src/feelies/risk/stop_exit.py` | 234 | 2 | Risk-layer stop-loss and end-of-session flatten emitter. |
| `src/feelies/sensors/__init__.py` | 37 | 0 | Sensor layer (Layer 1 of the three-layer architecture). |
| `src/feelies/sensors/errors.py` | 24 | 3 | Error hierarchy for the sensor layer. |
| `src/feelies/sensors/horizon_scheduler.py` | 269 | 2 | HorizonScheduler — emits ``HorizonTick`` events at event-time boundaries. |
| `src/feelies/sensors/impl/__init__.py` | 6 | 0 | Concrete Layer-1 sensor implementations. |
| `src/feelies/sensors/impl/book_imbalance.py` | 80 | 1 | Signed top-of-book displayed-size imbalance. |
| `src/feelies/sensors/impl/hawkes_intensity.py` | 131 | 1 | Two-sided exponentially decayed trade-arrival intensity. |
| `src/feelies/sensors/impl/inventory_pressure.py` | 90 | 1 | Volume-normalized market-maker inventory proxy. |
| `src/feelies/sensors/impl/kyle_lambda_60s.py` | 231 | 1 | Kyle's lambda — price-impact regression over a rolling window. |
| `src/feelies/sensors/impl/liquidity_stress_score.py` | 166 | 1 | Unsigned top-of-book liquidity-stress alarm in ``[0, 1]``. |
| `src/feelies/sensors/impl/micro_price.py` | 82 | 1 | Bid/ask micro-price sensor. |
| `src/feelies/sensors/impl/ofi_ewma.py` | 189 | 1 | Exponentially weighted top-of-book order-flow imbalance. |
| `src/feelies/sensors/impl/ofi_raw.py` | 101 | 1 | Emit unsmoothed order-flow imbalance between consecutive quotes. |
| `src/feelies/sensors/impl/quote_flicker_rate.py` | 112 | 1 | Measure best-price reversals in a trailing event-time window. |
| `src/feelies/sensors/impl/quote_hazard_rate.py` | 90 | 1 | Quote-update hazard rate (instantaneous quote arrival intensity). |
| `src/feelies/sensors/impl/quote_replenish_asymmetry.py` | 144 | 1 | Bid-versus-ask depth replenishment asymmetry. |
| `src/feelies/sensors/impl/realized_vol_30s.py` | 133 | 1 | Realized volatility over a sliding event-time window. |
| `src/feelies/sensors/impl/scheduled_flow_window.py` | 118 | 1 | Report whether event time falls inside a scheduled-flow window. |
| `src/feelies/sensors/impl/snr_drift_diffusion.py` | 134 | 1 | Per-horizon drift-to-diffusion signal-to-noise ratio. |
| `src/feelies/sensors/impl/spread_z_30d.py` | 158 | 1 | Online z-score of bid-ask spread over a configurable rolling window. |
| `src/feelies/sensors/impl/structural_break_score.py` | 108 | 1 | Page-Hinkley structural-break score over absolute mid-price returns. |
| `src/feelies/sensors/impl/sweep_flow_imbalance.py` | 235 | 4 | Measure signed intermarket-sweep aggression over event time. |
| `src/feelies/sensors/impl/trade_through_rate.py` | 85 | 1 | Fraction of trades that touch or cross the prevailing NBBO. |
| `src/feelies/sensors/impl/vpin_50bucket.py` | 125 | 1 | Volume-synchronized probability of informed trading. |
| `src/feelies/sensors/protocol.py` | 51 | 2 | Contract for deterministic Layer-1 sensors. |
| `src/feelies/sensors/registry.py` | 359 | 1 | Own per-symbol sensor state and publish stamped readings. |
| `src/feelies/sensors/spec.py` | 111 | 1 | Declarative SensorSpec — registers one sensor with the registry. |
| `src/feelies/services/__init__.py` | 26 | 0 | Platform-provided shared services. |
| `src/feelies/services/regime_engine.py` | 673 | 4 | Regime engine — platform-provided online regime filtering services. |
| `src/feelies/services/regime_hazard_detector.py` | 238 | 3 | Detect sharp decay in a dominant regime posterior. |
| `src/feelies/services/regime_state_cache.py` | 86 | 1 | Last-published ``RegimeState`` per ``(symbol, engine_name)``. |
| `src/feelies/signals/__init__.py` | 1 | 0 | Signal engine layer — pure functions from features to signals. |
| `src/feelies/signals/horizon_engine.py` | 655 | 2 | Turn horizon snapshots into regime-gated signals. |
| `src/feelies/signals/horizon_protocol.py` | 34 | 1 | Layer-2 horizon signal contract. |
| `src/feelies/signals/regime_gate.py` | 628 | 8 | Safe expression evaluator and hysteresis latch for regime gates. |
| `src/feelies/storage/__init__.py` | 13 | 0 | Storage layer — event log, feature snapshots, trade journal. |
| `src/feelies/storage/cache_replay.py` | 130 | 5 | Load merged event logs from :class:`DiskEventCache` without calling Massive. |
| `src/feelies/storage/disk_event_cache.py` | 238 | 1 | Per-day disk cache for normalized market events. |
| `src/feelies/storage/event_log.py` | 42 | 1 | Event log — persistent, append-only record of all events. |
| `src/feelies/storage/event_resequence.py` | 49 | 2 | Deterministic ordering for merged NBBO + trade streams (Inv-5 / Inv-6). |
| `src/feelies/storage/feature_snapshot.py` | 55 | 2 | Feature snapshot protocol — checkpoint and restore feature engine state. |
| `src/feelies/storage/memory_event_log.py` | 128 | 1 | In-memory event log — implements EventLog protocol for testing and development. |
| `src/feelies/storage/memory_feature_snapshot.py` | 53 | 1 | In-memory feature snapshot store for backtesting and testing. |
| `src/feelies/storage/memory_trade_journal.py` | 37 | 1 | In-memory trade journal for backtesting and testing. |
| `src/feelies/storage/reference/__init__.py` | 9 | 0 | Versioned reference data shipped with the platform. |
| `src/feelies/storage/reference/corporate_actions/__init__.py` | 262 | 10 | Corporate-action ex-date calendar for replay integrity. |
| `src/feelies/storage/reference/event_calendar/__init__.py` | 251 | 4 | Load deterministic scheduled-flow calendars from per-session YAML. |
| `src/feelies/storage/reference/factor_loadings/__init__.py` | 1 | 0 | Bundled factor-loading fixtures (``loadings.json``). |
| `src/feelies/storage/reference/paths.py` | 21 | 0 | Bundled reference artefacts (YAML / JSON) shipped with the package. |
| `src/feelies/storage/reference/sector_map/__init__.py` | 1 | 0 | Bundled sector map fixture (``sector_map.json``). |
| `src/feelies/storage/trade_journal.py` | 76 | 2 | Trade journal protocol — structured trade lifecycle records. |
