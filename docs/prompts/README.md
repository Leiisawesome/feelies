# Codebase audit prompts

Read-only, evidence-based audit prompts for **Claude Code**, one per architectural area.
Each is designed to elevate codebase quality by producing a structured report with
`file:line` citations, severity tiers (P0/P1/P2), and prioritized recommendations — **no
code changes in the audit pass**.

## How to use

1. Open a Claude Code session with full repo access.
2. Paste the contents of one `audit_<area>.md` as the prompt.
3. The agent writes its report to `docs/audits/<area>_audit_YYYY-MM-DD.md`.
4. (Optional) paste one of the prompt's "Optional follow-ups" to turn findings into a
   scoped, fix-only PR plan.

Each prompt shares the same skeleton: Mission → Platform context → Scope → Audit
dimensions (A–G) → Working method → Output format → Quality bar → Optional follow-ups.

## Conventions

- **Read-only.** Audits never modify production code, baselines, or the promotion ledger.
- **Ownership vs touchpoint.** Every source file has exactly **one owning audit** that
  deep-dives it; other audits may *reference* it as a touchpoint but defer critique via an
  "Out of scope" pointer. This prevents two parallel audits from conflicting over the same
  file. The shared files and their owners are listed under [Overlaps](#overlaps-shared-files).
- **Invariant-anchored.** Findings are tied to the platform invariants in
  `.cursor/rules/platform-invariants.mdc` (Inv-1 … Inv-13).

## The audits

Grouped by pipeline position; the suggested run order follows the table top-to-bottom.

| # | Prompt | Area | Owning skill | Primary lens |
|---|--------|------|--------------|--------------|
| **Front pipeline** |
| 1 | `audit_data_ingestion.md` | Ingestion, storage, replay | data-engineering | Inv-5/6/9 ordering |
| 2 | `audit_sensor.md` | Layer-1 sensors + horizon aggregation | feature-engine | sensor math, no lookahead |
| 3 | `audit_regime.md` | Regime detection + regime gate | regime-detection | gate as risk control |
| **Capital path** |
| 4 | `audit_signal_alpha.md` | Layer-2 SIGNAL alphas + engine | microstructure-alpha | Inv-1 mechanism, Inv-12 cost |
| 5 | `audit_composition.md` | Layer-3 PORTFOLIO / composition | composition-layer | Inv-5 optimizer determinism |
| 6 | `audit_risk_engine.md` | Risk engine + governor | risk-engine | Inv-11 fail-safe |
| 7 | `audit_position_management.md` | Signal→intent decision, exits, sizing economics, PnL ledger (G-1…G-7) | risk-engine + live-execution | Inv-11/12 decision economics, Inv-13 ledger |
| 8 | `audit_execution_fills.md` | Backtest fills / cost / latency | backtest-engine | Inv-6/9/12 PnL realism |
| 9 | `audit_live_execution.md` | Live/paper + IB broker | live-execution | Inv-9 parity, fail-closed |
| **Governance** |
| 10 | `audit_alpha_lifecycle.md` | Promotion gates + ledger | alpha-lifecycle | Inv-13 provenance |
| 11 | `audit_forensics.md` | Post-trade + decay detection | post-trade-forensics | Inv-4 decay default |
| 12 | `audit_research_validation.md` | CPCV / DSR statistics | research-workflow | Inv-2/3 evidence |
| **Foundations (cross-cutting)** |
| 13 | `audit_kernel.md` | Orchestrator, micro-ordering, **bootstrap wiring** | system-architect | Inv-5/6/7/8 |
| 14 | `audit_determinism.md` | Parity-hash harness + scope locks | testing-validation | Inv-5 coverage |
| 15 | `audit_core_clock_config.md` | Clock, config, serialization, SM primitive | system-architect | Inv-10/7/5 |
| 16 | `audit_performance.md` | Hot-path latency budgets | performance-engineering | Inv-5 (binding constraint) |
| 17 | `audit_monitoring_safety.md` | Kill switch, health, alerting | live-execution | Inv-11 fail-closed |
| 18 | `audit_harness_cli.md` | Backtest harness, reporting, operator CLI | backtest-engine | Inv-5 reproducibility, report fidelity |

## Coverage map (`src/feelies/` → owning audit)

| Package | Owning audit |
|---------|--------------|
| `ingestion/`, `storage/` | data_ingestion |
| `sensors/`, `features/` | sensor |
| `services/`, `signals/regime_gate.py` | regime |
| `signals/horizon_engine.py`, `signals/horizon_protocol.py` | signal_alpha |
| `alpha/cost_arithmetic.py`, `arbitration.py`, `aggregation.py` | signal_alpha |
| `alpha/lifecycle.py`, `promotion_ledger.py`, `registry.py`, `loader.py`, `validation.py`, `discovery.py`, `layer_validator.py`, `module.py`, `signal_layer_module.py` | alpha_lifecycle |
| `alpha/promotion_evidence.py` | alpha_lifecycle (matrix) · research_validation (CPCV/DSR) · forensics (quarantine) |
| `alpha/portfolio_layer_module.py`, `intent_set.py` | composition |
| `alpha/fill_attribution.py` | forensics |
| `alpha/risk_wrapper.py` | risk_engine |
| `composition/`, `portfolio/cross_sectional_tracker.py` | composition |
| `portfolio/position_store.py`, `memory_position_store.py`, `strategy_position_store.py`, `lot_ledger.py` | position_management (PnL ledger) |
| `storage/trade_journal.py`, `memory_trade_journal.py` | position_management (fill journal) |
| `risk/` | risk_engine |
| `risk/position_sizer.py`, `edge_weighted_sizer.py` | position_management (sizing economics) |
| `execution/` (backtest fill/cost/routers) | execution_fills |
| `execution/intent.py`, `position_manager.py`, `portfolio_netter.py` | position_management |
| `execution/live_router.py`, `paper_backend.py`, `order_state.py`, `trading_session.py` | live_execution |
| `broker/` | live_execution |
| `forensics/` | forensics |
| `research/` | research_validation |
| `kernel/`, `bus/`, `bootstrap.py`, `__main__.py` | kernel |
| `core/` | core_clock_config |
| `monitoring/` | monitoring_safety |
| `harness/` (run + report) | harness_cli |
| `cli/` | harness_cli (backtest) · alpha_lifecycle (`promote`) |
| `scripts/` | harness_cli (ops: `run_backtest.py`, `run_paper.py`, `run_paper_soak.py`, `smoke_pipeline.py`, `compare_paper_backtest.py`, `split_backtest_emit.py`, `export_full_trade_list.py`, `generate_bt12_fixtures.py`, `rebaseline_parity_hashes.py`, `record_perf_baseline.py`, `record_paper_perf_baseline.py`) · sensor (`sensor_feature_ic.py`, `calibrate_hawkes.py`) · composition (`build_reference_factor_loadings.py`) · live_execution (`verify_ib_broker.py`) · position_management (`analyze_net_divergence.py`, `analyze_size_divergence.py`) |

Cross-cutting concerns (not a single package): **determinism** spans `tests/determinism/`
+ every event producer (audit 14); **performance** spans the whole hot path (audit 16).

## Overlaps (shared files)

These files are deliberately viewed by more than one audit; the **owner** does the deep
dive, the others treat them as touchpoints:

| Shared file | Owner | Touchpoints |
|-------------|-------|-------------|
| `signals/horizon_engine.py` | signal_alpha | regime (gate integration), kernel (M4 ordering) |
| `core/state_machine.py` | core_clock_config | kernel, alpha_lifecycle |
| `alpha/promotion_evidence.py` | alpha_lifecycle | research_validation, forensics |
| `monitoring/kill_switch.py` | monitoring_safety | live_execution |
| `core/inv12_stress.py` | core_clock_config | execution_fills |
| `execution/order_state.py`, `trading_session.py` | live_execution | execution_fills |
| `kernel/orchestrator.py` | kernel (micro ordering, single-writer) | position_management (decision/exit economics), data_ingestion (M1 market-event path), regime (M2 writer) |
| `execution/intent.py` | position_management | execution_fills (order-lifecycle touchpoint) |
| `risk/position_sizer.py`, `edge_weighted_sizer.py` | position_management (sizing economics) | risk_engine (regime-factor fail-safe) |
| `portfolio/{memory,strategy}_position_store.py`, `lot_ledger.py` | position_management (PnL math) | composition (position-state reads) |
| `bootstrap.py` | kernel | every layer (mode-wiring touchpoint) |
| `harness/backtest_runner.py`, `backtest_prep.py` | data_ingestion (ingest) + harness_cli (run/report) | — |
| `alpha/loader.py`, `layer_validator.py`, `module.py`, `signal_layer_module.py` | alpha_lifecycle | signal_alpha (loaded-alpha surface, G12/G16 signal semantics) |
| `storage/feature_snapshot.py`, `memory_feature_snapshot.py` | data_ingestion (persistence) | sensor (snapshot semantics) |
| `storage/reference/**` | data_ingestion (store machinery) | execution_fills (ex-date guard), composition (factor loadings / sectors) |
| `scripts/run_paper.py`, `run_paper_soak.py` | harness_cli | live_execution (safety wiring) |

## Note

The three original prompts (`audit_data_ingestion`, `audit_sensor`, `audit_regime`) were
the template; prompts 4–18 follow the same format and were grounded against real module
and test paths. Update this index when adding a new audit prompt.

## Maintenance

**Any PR that adds a new module under `src/feelies/` must assign it an owning audit in
the coverage map above (and, for split-ownership packages, in
`tests/docs/test_prompt_coverage_map.py`).** This is enforced by
`tests/docs/test_prompt_coverage_map.py`, which fails when a module in a
split-ownership package (`execution/`, `alpha/`, `signals/`, `cli/`, `portfolio/`) has
no explicit owner, or when a new top-level package has no coverage-map entry. The guard
exists because the G-1…G-7 position-management work (2026-06-08…10) landed ~15 commits
of capital-path code with no prompt owner before this index caught up.
