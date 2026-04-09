# Feelies

Deterministic intraday trading platform. Research backtesting and live trading
share core logic, behavioral equivalence is enforced, and determinism is
guaranteed in replay mode.

Built on L1 NBBO data from Massive (formerly Polygon.io). Python 3.12+.

## Architecture

Feelies is a layered, event-driven system. Every component belongs to exactly
one layer; all inter-layer communication flows through typed events on a
synchronous bus.

```
                    ┌──────────────────────────────────────────────┐
                    │              Kernel / Orchestrator            │
                    │  Macro SM · Micro SM · Risk SM · Order SM    │
                    └──────┬───────────┬───────────┬───────────────┘
                           │           │           │
         ┌─────────────────┼───────────┼───────────┼─────────────────┐
         │                 │           │           │                 │
   ┌─────▼─────┐    ┌─────▼─────┐  ┌──▼──┐  ┌────▼────┐    ┌──────▼──────┐
   │ Ingestion  │    │  Feature   │  │Signal│  │  Risk   │    │  Execution  │
   │ Massive L1 │───▶│  Engine    │─▶│Engine│─▶│ Engine  │───▶│  Backend    │
   │ NBBO+Trade │    │ (stateful) │  │(pure)│  │ (gate)  │    │ (mode-swap) │
   └────────────┘    └───────────┘  └──────┘  └─────────┘    └─────────────┘
         │                                          │                │
   ┌─────▼─────┐                             ┌─────▼─────┐   ┌──────▼──────┐
   │  Storage   │                             │ Portfolio  │   │ Monitoring  │
   │ EventLog   │                             │ Positions  │   │ Metrics     │
   │ Cache      │                             │ PnL        │   │ Alerts      │
   └────────────┘                             └────────────┘   └─────────────┘
```

### State Machines

Five state machines govern all system behavior:

| Machine | States | Scope |
|---------|--------|-------|
| **Macro** (global lifecycle) | INIT → DATA_SYNC → READY → BACKTEST/PAPER/LIVE → DEGRADED → RISK_LOCKDOWN → SHUTDOWN | System-wide |
| **Micro** (tick pipeline) | WAITING → MARKET_EVENT → STATE_UPDATE → FEATURE → SIGNAL → RISK → ORDER → ACK → POSITION → LOG | Per-tick |
| **Order** lifecycle | CREATED → SUBMITTED → ACKNOWLEDGED → FILLED/CANCELLED/REJECTED/EXPIRED | Per-order |
| **Risk** escalation | NORMAL → WARNING → BREACH → FORCED_FLATTEN → LOCKED | Monotonic safety |
| **Data** integrity | HEALTHY → GAP_DETECTED → CORRUPTED → RECOVERING | Per-symbol stream |

Every transition emits a `StateTransition` event for full auditability.

### Backtest/Live Parity

The `ExecutionBackend` is the sole mode-specific abstraction. The tick pipeline
is identical across backtest, paper trading, and live trading. Mode determines
which concrete `MarketDataSource` and `OrderRouter` are composed at startup:

| Mode | MarketDataSource | OrderRouter | Clock |
|------|-----------------|-------------|-------|
| Backtest (`execution_mode: market`) | `ReplayFeed(EventLog)` | `BacktestOrderRouter` (mid-price fills) | `SimulatedClock` |
| Backtest (`execution_mode: passive_limit`) | `ReplayFeed(EventLog)` | `PassiveLimitOrderRouter` (queue-position fills) | `SimulatedClock` |
| Paper | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |
| Live | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |

## Project Structure

```
feelies/
├── src/feelies/             # Core platform package (88 modules)
│   ├── core/                # Events, clock, state machine, identifiers, config
│   ├── kernel/              # Orchestrator, macro/micro state machines
│   ├── bus/                 # Synchronous deterministic event bus
│   ├── ingestion/           # Massive normalizer, historical ingestor, replay feed
│   ├── features/            # Feature engine protocol, definitions, standard library
│   ├── signals/             # Signal engine protocol
│   ├── alpha/               # Alpha module system (loader, registry, composite, arbitration)
│   ├── risk/                # Risk engine, escalation SM, position sizer
│   ├── execution/           # Backend abstraction, intent translator, order SM, routers
│   ├── portfolio/           # Position store, per-strategy tracking
│   ├── storage/             # Event log, disk cache, feature snapshots, trade journal
│   ├── monitoring/          # Metrics, alerting, kill switch, health checks
│   ├── forensics/           # Post-trade analysis, edge decay detection
│   ├── research/            # Grok-parity backtester, experiment tracking
│   ├── services/            # Regime engine (HMM-based)
│   └── bootstrap.py         # One-call platform composition from config
├── alphas/                  # Alpha strategy specs
│   ├── SCHEMA.md            # YAML schema reference
│   ├── _template/           # Starter template
│   └── trade_cluster_drift/      # Example: cluster drift microstructure alpha
├── scripts/                 # CLI entry points
│   ├── run_backtest.py      # Full pipeline backtest
│   ├── run_parity_backtest.py  # Grok-parity research backtest
│   └── run_validation.py    # Validation suite runner
├── tests/                   # Pytest suite (83 files, mirrors src/ structure)
├── platform.yaml            # Reference platform configuration
├── pyproject.toml           # Build, deps, tooling
└── .env.example             # Environment variable template
```

## Getting Started

### Prerequisites

- Python 3.12 or later
- A Massive (Polygon.io) API key for market data

### Installation

```bash
# Clone the repository
git clone https://github.com/<org>/feelies.git
cd feelies

# Install in editable mode with dev dependencies
pip install -e ".[dev,massive]"
```

### Environment

Copy `.env.example` and set your API key:

```bash
cp .env.example .env
# Edit .env with your MASSIVE_API_KEY
```

## Running a Backtest

### Parity Backtest (Research)

The parity backtester replicates external Grok REPL semantics with
spread-crossing fills, seeded RNG, latency queuing, and a full fee stack:

```bash
python scripts/run_parity_backtest.py \
    --spec alphas/trade_cluster_drift/trade_cluster_drift.alpha.yaml \
    --symbols AAPL \
    --start 2026-03-23 --end 2026-03-27 \
    --api-key $MASSIVE_API_KEY
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--spec` | *(required)* | Path to `.alpha.yaml` spec |
| `--symbols` | *(required)* | One or more ticker symbols |
| `--start` / `--end` | *(required)* | Date range (YYYY-MM-DD) |
| `--api-key` | `$POLYGON_API_KEY` | Massive API key |
| `--latency-ms` | 100.0 | Simulated fill latency |
| `--fill-prob` | 0.7 | Probabilistic fill rate |
| `--seed` | 42 | RNG seed for deterministic replay |
| `--latency-sweep` | off | Run 5-point latency sensitivity (0/50/100/200/500 ms) |
| `--cache-dir` | `~/.feelies/cache/` | Disk cache for downloaded data |
| `--no-cache` | off | Force re-download |
| `--output` | none | Write JSON results to file |

### Full Pipeline Backtest

```bash
python scripts/run_backtest.py \
    --symbol AAPL --date 2026-03-24 \
    --config platform.yaml \
    --api-key $MASSIVE_API_KEY
```

## Writing an Alpha

An alpha is a self-contained YAML spec file that declares its hypothesis,
features, signal logic, risk budget, and falsification criteria.

### Directory Layout

```
alphas/
└── my_alpha/
    ├── my_alpha.alpha.yaml     # Spec file
    ├── my_feature.py           # External feature module (optional)
    └── regime_calibration.json # Calibration data (optional)
```

### Spec Structure

```yaml
schema_version: "1.0"
alpha_id: my_alpha_v1
version: "1.0.0"
description: "Short description of the structural edge."
hypothesis: |
  The causal mechanism being exploited (Invariant 1).
falsification_criteria:
  - "OOS DSR < 1.0 or bootstrap p-value > 0.05"

symbols:
  - AAPL

parameters:
  entry_threshold:
    type: float
    default: 2.0
    range: [1.0, 5.0]

risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 10.0

features:
  - feature_id: my_feature
    version: "1.0.0"
    computation_module: my_feature.py   # or inline `computation:`
    warm_up: {min_events: 100}

signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      val = features.values.get("my_feature", 0.0)
      if abs(val) < params["entry_threshold"]:
          return None
      direction = LONG if val > 0 else SHORT
      return Signal(
          timestamp_ns=features.timestamp_ns,
          correlation_id=features.correlation_id,
          sequence=features.sequence,
          symbol=features.symbol,
          strategy_id=alpha_id,
          direction=direction,
          strength=min(abs(val) / 10.0, 1.0),
          edge_estimate_bps=abs(val) * 2.0,
      )
```

Feature computation modules must define `initial_state() -> dict` and
`update(quote, state, params) -> float`. An optional
`update_trade(trade, state, params) -> float | None` handles trade events.
See `alphas/SCHEMA.md` for the full schema reference.

## Platform Configuration

`platform.yaml` controls operating mode, trading universe, risk limits,
cost model, and alpha discovery:

```yaml
mode: BACKTEST                    # BACKTEST | PAPER | LIVE
symbols: [AAPL, MSFT, NVDA]
alpha_spec_dir: alphas/           # Scanned for *.alpha.yaml at boot
regime_engine: hmm_3state_fractional
account_equity: 100000.0

# Risk limits
risk_max_position_per_symbol: 50000
risk_max_gross_exposure_pct: 200.0
risk_max_drawdown_pct: 5.0

# IB US Equity Tiered cost model
cost_commission_per_share: 0.0035
cost_exchange_per_share: 0.0005
cost_min_commission: 0.35
cost_max_commission_pct: 1.0

# Execution mode: "market" (mid-price fill) or "passive_limit" (queue model)
execution_mode: passive_limit
passive_fill_delay_ticks: 3      # Ticks at level before queue-drain fill
passive_max_resting_ticks: 50    # Cancel unfilled orders after N ticks
passive_rebate_per_share: 0.002  # Maker rebate (IB Tiered adding liquidity)
```

## Design Invariants

These invariants are enforced across the entire platform:

1. **Structural mechanism required** — every signal names the causal force being exploited
2. **Falsifiability before testing** — define what disproves the hypothesis before looking at data
3. **Evidence over intuition** — scaling and promotion decisions require statistical evidence
4. **Decay is the default** — every edge is assumed to be eroding
5. **Deterministic replay** — same event log + parameters → bit-identical signals, orders, PnL
6. **Causality enforced** — features at time T use only events with timestamp ≤ T
7. **Event-driven, typed schemas** — all data flows through typed events on the bus
8. **Layer separation** — every piece of code belongs to exactly one layer
9. **Backtest/live parity** — shared core; mode-specific code only behind `ExecutionBackend`
10. **Clock abstraction** — all timestamps via injectable clock; no raw `datetime.now()`
11. **Fail-safe default** — unknown states resolve to reduced exposure, never increased
12. **Transaction cost realism** — expected edge must exceed 1.5× round-trip cost
13. **Full provenance** — every decision traceable to an event, every config change auditable

## Testing

```bash
# Run the full test suite
pytest

# Run with coverage
pytest --cov=feelies --cov-report=term-missing

# Run specific marker groups
pytest -m "not slow"                  # Skip benchmarks
pytest -m functional                  # Network-backed tests only
pytest -m backtest_validation         # Full validation suite

# Run the validation suite via script
python scripts/run_validation.py
python scripts/run_validation.py --quick   # Fast subset
```

The test suite mirrors the `src/feelies/` package structure and includes unit
tests, property-based tests (Hypothesis), replay determinism checks, fault
tolerance tests, and end-to-end backtest validation.

## Tooling

| Tool | Config | Purpose |
|------|--------|---------|
| **pytest** | `pyproject.toml` | Test runner, markers, coverage (≥80%) |
| **mypy** | `pyproject.toml` | Strict static type checking (Python 3.12) |
| **ruff** | `pyproject.toml` | Linting and formatting (line length 99) |
| **hypothesis** | dev dependency | Property-based testing |

```bash
# Type checking
mypy src/feelies

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Data Pipeline

Market data flows through a two-stage pipeline:

1. **Historical ingest** — `MassiveHistoricalIngestor` downloads L1 NBBO quotes
   and trades via Massive REST API, normalizes them through `MassiveNormalizer`
   into canonical `NBBOQuote` and `Trade` events, and stores them in an
   `EventLog`. Downloaded data is cached to `~/.feelies/cache/` by default.

2. **Replay** — `ReplayFeed` iterates over the `EventLog` in timestamp order,
   feeding the orchestrator's tick pipeline. The `SimulatedClock` advances to
   each event's timestamp, preserving causality.

For live operation (future), `MassiveLiveFeed` provides real-time WebSocket
streaming through the same normalizer, ensuring identical event types flow
through the same pipeline.

## License

*Not yet specified.*
