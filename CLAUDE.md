# feelies — Claude Code Context

Deterministic intraday trading platform. Three alpha layers (SENSOR → SIGNAL → PORTFOLIO)
on L1 NBBO data. Backtest/live parity is contractual; replay is bit-identical.

## Environment (uv)

uv is the package manager. The lockfile is uv.lock. Always use `uv run` — never activate
the venv manually.

    uv sync --all-extras                                    # install everything (recommended)
    uv sync --extra dev --extra massive                     # core dev + Massive data feed
    uv sync --extra dev --extra massive --extra ib          # + IB Gateway adapter

## Credentials

- No `.env` file is needed for the standard test suite.
- `MASSIVE_API_KEY` is only required for `pytest -m functional` network-backed tests,
  `scripts/run_backtest.py` when it needs live Massive data, and paper/live workflows.
- Paper/live mode requires IB Gateway running locally on port 4002.

## Directory Map

    src/feelies/          Core library — all production code
      core/               Events, MonotonicClock, config, state machine identifiers
      kernel/             Orchestrator, macro/micro state machines
      bus/                Synchronous deterministic event bus
      ingestion/          Massive normalizer, replay feed, live WS, IdleTick sentinel
      sensors/            Layer-1 sensor framework (13 sensors in impl/)
      features/           Horizon aggregator + horizon feature engine
      signals/            Layer-2 horizon signal engine + regime gate DSL
      composition/        Layer-3 cross-sectional portfolio construction pipeline
      risk/               Risk engine, escalation SM, sizer, hazard-exit controller
      execution/          Execution backend abstraction, order SM, routers
      broker/ib/          IB Gateway adapter (paper/live only)
      research/           CPCV, DSR, experiment tracking
      forensics/          Multi-horizon attribution, post-trade analysis
      monitoring/         Metrics, alerting, kill switch, telemetry
      cli/                Operator CLI (read-only promotion-ledger forensics)
    alphas/               Alpha strategy YAML specs (*.alpha.yaml)
      _template/          Start here for new alphas (signal + portfolio templates)
      SCHEMA.md           YAML gate reference (G2–G16) — normative
    configs/              Run configuration YAML files
    scripts/              Operator entry points (backtest, paper, smoke, verify)
    tests/                Pytest suite mirroring src/ + determinism + perf
    docs/                 Architecture specs

## Common Commands

    # Fast local test run (skips network and benchmarks)
    uv run pytest -m "not functional and not slow"

    # End-to-end pipeline smoke (no API key needed)
    uv run pytest tests/integration/test_phase4_e2e.py

    # Determinism parity hash verification
    uv run pytest tests/determinism/

    # Full suite
    uv run pytest

    # Coverage
    uv run pytest --cov=feelies --cov-report=term-missing

    # Type checking (strict — no per-module overrides)
    uv run mypy src/feelies

    # Linting and formatting (line length 99)
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/

    # Backtest
    uv run python scripts/run_backtest.py \
        --symbol AAPL --date 2026-03-24 --config platform.yaml

    # Paper trading (requires IB Gateway @ 4002 + MASSIVE_API_KEY)
    uv run python scripts/verify_ib_broker.py --port 4002 --client-id 7
    uv run python scripts/run_paper.py --config platform.yaml

    # Operator CLI (read-only forensics)
    uv run feelies promote list --config platform.yaml
    uv run feelies promote inspect <alpha_id> --config platform.yaml

## Code Style

- Python 3.12+, line length 99, ruff + mypy strict
- DTZ rule: never use datetime.now() / datetime.utcnow() / time.time() in production
  code. All timestamps go through MonotonicClock or accept ts_ns as an explicit
  parameter. Only src/feelies/core/clock.py is exempted (enforced by ruff CI).
- Layer separation is hard: every piece of code belongs to exactly one layer; no
  cross-layer imports
- All inter-layer data flows through typed events on the synchronous bus

## Platform Invariants (never violate)

1. Deterministic replay — same inputs → bit-identical outputs; no RNG or wall-clock
   reads in core logic
2. Causality — features at time T use only events with timestamp ≤ T
3. Clock abstraction — inject MonotonicClock; never call datetime.now() in production
4. Layer separation — SENSOR → SIGNAL → PORTFOLIO; no cross-layer imports
5. Backtest/live parity — tick pipeline is identical; only ExecutionBackend is
   mode-specific

## Alpha Development

- New alphas: copy alphas/_template/template_signal.alpha.yaml
- Schema version 1.1 is current; layer: LEGACY_SIGNAL is rejected by the loader
- SIGNAL requires: depends_on_sensors, horizon_seconds, regime_gate, cost_arithmetic
- PORTFOLIO requires: universe, depends_on_signals, factor_neutralization,
  horizon_seconds
- Cost gate enforced at load: expected_edge > 1.5 × round_trip_cost
- See alphas/SCHEMA.md for the full gate table (G2–G16)

## Known Pre-existing Test Failures (main branch)

None. The full suite was green on `main` as of 2026-06-11: 3319 passed, 27 skipped.
The skips are gated `functional` / `paper_rth` / per-host perf tests.

## Cross-Platform Notes

- Paths in this file use forward slashes; the platform resolves them on both macOS
  and Windows
- Event cache: ~/.feelies/cache/ (macOS: /Users/<you>/.feelies/cache/,
  Windows: C:\Users\<you>\.feelies\cache\)
- IB Gateway: 127.0.0.1:4002 on both platforms
- uv run handles the venv transparently; no manual activation needed

## Coding Behavior

Before implementing: state assumptions explicitly; surface tradeoffs and alternatives
rather than picking silently; push back on overcomplication; stop and ask when unclear.

Simplicity first: minimum code that solves the problem. No speculative features,
single-use abstractions, unrequested configurability, or error handling for
impossible scenarios.

Surgical changes: touch only what the task requires. Don't improve adjacent code or
formatting. Match existing style. Remove imports/variables YOUR changes made orphaned;
leave pre-existing dead code alone unless asked.

Verifiable goals: transform tasks into testable criteria before starting. For
multi-step work, state a plan with an explicit verify step per change.
