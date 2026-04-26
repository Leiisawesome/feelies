# Feelies

Deterministic, three-layer intraday trading platform. Research backtesting
and live trading share the same core logic; behavioural equivalence is
enforced; bit-identical replay is contractual.

Built on L1 NBBO data from Massive (formerly Polygon.io). Python 3.12+.

## Architecture

Feelies is a layered, event-driven system. Every component belongs to
exactly one layer; all inter-layer communication flows through typed
events on a synchronous bus. The platform is structured around three
alpha layers — **SENSOR**, **SIGNAL**, **PORTFOLIO** — anchored to
horizon-bucketed snapshots.

```
                            ┌──────────────────────────────────────────────┐
                            │            Kernel / Orchestrator              │
                            │   Macro SM · Micro SM · Risk SM · Order SM   │
                            └──┬─────────┬─────────┬─────────┬─────────┬──┘
                               │         │         │         │         │
                ┌──────────────┘         │         │         │         └────────────────┐
                │                        │         │         │                          │
        ┌───────▼─────────┐    ┌─────────▼──┐ ┌────▼─────┐ ┌─▼────────────────┐ ┌──────▼─────────┐
        │  L1 Ingestion    │    │  Sensors    │ │  Horizon │ │  Composition     │ │  Risk Engine    │
        │  Massive NBBO    │───▶│ (Layer 1)   │ │ Aggreg.  │ │  (Layer 3)       │ │  + Hazard Exit  │
        │  + Trades        │    │ ofi_ewma,…  │ │ Snapshot │ │  CrossSectional  │ │  per-leg veto   │
        └──────────────────┘    └──────┬──────┘ └────┬─────┘ │  Ranker → Factor │ └─────┬───────────┘
                                       │             │       │  Neutralizer →   │       │
                                  SensorReading      │       │  SectorMatcher → │       │
                                                     │       │  Turnover Opt.   │       │
                                              ┌──────▼─────┐ └─────┬────────────┘       │
                                              │  Signals   │       │                    │
                                              │ (Layer 2)  │──────▶│ SizedPosition      │
                                              │ Horizon-   │       │   Intent           │
                                              │ anchored   │       │                    │
                                              └────────────┘       │                    │
                                                                   │                    ▼
                                                                   │             ┌──────────────┐
                                                                   └────────────▶│  Execution   │
                                                                                 │  Backend     │
                                                                                 │ (mode-swap)  │
                                                                                 └──────────────┘
```

### Three Alpha Layers

| Layer | Horizon | Output | Owns |
|---|---|---|---|
| **SENSOR** (`src/feelies/sensors/`) | event-time (≤ 1 s) | `SensorReading` (state estimate) | per-symbol incremental L1 estimators (13 in v0.3) |
| **SIGNAL** (`src/feelies/signals/`) | 30 s – 30 min | `Signal` (directional alpha + edge bps) | horizon-anchored, regime-gated, cost-disclosed predictions |
| **PORTFOLIO** (`src/feelies/composition/`) | 5 – 30 min | `SizedPositionIntent` (cross-sectional sized weights) | factor-neutralised, mechanism-capped, turnover-optimised cross-sectional construction |

`LEGACY_SIGNAL` was a fourth (per-tick) layer that preserved the
Phase-1 contract bit-identically.  It was retired in Workstream D.2;
the loader rejects `layer: LEGACY_SIGNAL` outright with a pointer to
the migration cookbook.  Every alpha must target SIGNAL or PORTFOLIO;
see
[`docs/migration/schema_1_0_to_1_1.md`](docs/migration/schema_1_0_to_1_1.md)
for the migration path.

### State Machines

Five state machines govern all system behaviour:

| Machine | States | Scope |
|---|---|---|
| **Macro** (global lifecycle) | INIT → DATA_SYNC → READY → BACKTEST/PAPER/LIVE → DEGRADED → RISK_LOCKDOWN → SHUTDOWN | System-wide |
| **Micro** (tick pipeline) | WAITING → MARKET_EVENT → STATE_UPDATE → SENSOR → AGGREGATOR → SIGNAL → COMPOSITION → RISK → ORDER → ACK → POSITION → LOG | Per-tick |
| **Order** lifecycle | CREATED → SUBMITTED → ACKNOWLEDGED → FILLED/CANCELLED/REJECTED/EXPIRED | Per-order |
| **Risk** escalation | NORMAL → WARNING → BREACH → FORCED_FLATTEN → LOCKED | Monotonic safety |
| **Data** integrity | HEALTHY → GAP_DETECTED → CORRUPTED → RECOVERING | Per-symbol stream |

Every transition emits a `StateTransition` event for full auditability.

### Backtest/Live Parity

The `ExecutionBackend` is the sole mode-specific abstraction. The tick
pipeline is identical across backtest, paper trading, and live trading.
Mode determines which concrete `MarketDataSource` and `OrderRouter` are
composed at startup:

| Mode | MarketDataSource | OrderRouter | Clock |
|---|---|---|---|
| Backtest (`execution_mode: market`) | `ReplayFeed(EventLog)` | `BacktestOrderRouter` (mid-price fills) | `SimulatedClock` |
| Backtest (`execution_mode: passive_limit`) | `ReplayFeed(EventLog)` | `PassiveLimitOrderRouter` (queue-position fills) | `SimulatedClock` |
| Paper | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |
| Live | `MassiveLiveFeed` | *(not yet implemented)* | `WallClock` |

## Project Structure

```
feelies/
├── src/feelies/                  # Core platform package
│   ├── core/                     # Events, clock, state machine, identifiers, config
│   ├── kernel/                   # Orchestrator, macro/micro state machines
│   ├── bus/                      # Synchronous deterministic event bus
│   ├── ingestion/                # Massive normalizer, historical ingestor, replay feed
│   ├── sensors/                  # Layer-1 sensor framework (13 sensors in impl/)
│   ├── features/                 # Horizon aggregator + legacy per-tick feature engine
│   ├── signals/                  # Layer-2 horizon signal engine + regime gate DSL
│   ├── composition/              # Layer-3 cross-sectional construction pipeline
│   ├── alpha/                    # Alpha module loader (1.0 + 1.1), registry, validator
│   ├── risk/                     # Risk engine, escalation SM, sizer, hazard-exit controller
│   ├── execution/                # Backend abstraction, intent translator, order SM, routers
│   ├── portfolio/                # Position store, per-strategy + cross-sectional trackers
│   ├── storage/                  # Event log, disk cache, reference factor loadings
│   ├── monitoring/               # Metrics (incl. horizon metrics), alerting, kill switch
│   ├── forensics/                # Multi-horizon attribution, post-trade analysis
│   ├── research/                 # Experiment tracking, hypothesis management
│   ├── services/                 # Regime engine + regime-hazard detector
│   ├── cli/                      # Operator CLI (`feelies promote ...` ledger forensics)
│   └── bootstrap.py              # One-call platform composition from config
├── alphas/                       # Alpha strategy specs
│   ├── SCHEMA.md                 # YAML schema reference (1.1)
│   ├── _template/                # Layer-specific templates
│   │   ├── template_signal.alpha.yaml           # 1.1 SIGNAL (recommended)
│   │   └── template_portfolio.alpha.yaml        # 1.1 PORTFOLIO
│   ├── pofi_kyle_drift_v1/       # Reference SIGNAL (KYLE_INFO)
│   ├── pofi_inventory_revert_v1/ # Reference SIGNAL (INVENTORY)
│   ├── pofi_hawkes_burst_v1/     # Reference SIGNAL (HAWKES_SELF_EXCITE)
│   ├── pofi_moc_imbalance_v1/    # Reference SIGNAL (SCHEDULED_FLOW)
│   ├── pofi_benign_midcap_v1/    # Reference SIGNAL (Phase-3 canonical)
│   ├── pofi_xsect_v1/            # Reference PORTFOLIO (decay OFF baseline)
│   └── pofi_xsect_mixed_mechanism_v1/  # Reference PORTFOLIO (multi-mechanism cap)
├── grok/                         # Grok REPL prompts (Hypothesis Reasoning Protocol)
│   └── prompts/
│       ├── hypothesis_reasoning.md  # 7-step protocol, hard gates, output contract
│       ├── sensor_catalog.md        # Layer-1 sensor vocabulary + fingerprint matrix
│       └── mutation_protocol.md     # 5-axis mutation discipline + parity rules
├── docs/migration/               # Migration cookbooks
│   └── schema_1_0_to_1_1.md      # 1.0 → 1.1 cookbook + LEGACY_SIGNAL retirement notes
├── design_docs/                  # Platform architecture & invariants
├── scripts/                      # CLI entry points
│   ├── run_backtest.py           # Full pipeline backtest (incl. parity hash)
│   ├── run_validation.py         # Validation suite runner
│   └── build_reference_factor_loadings.py  # PORTFOLIO factor loadings builder
├── tests/                        # Pytest suite (mirrors src/, plus determinism + perf)
├── platform.yaml                 # Reference platform configuration
├── pyproject.toml                # Build, deps, tooling
└── .env.example                  # Environment variable template
```

## Getting Started

### Prerequisites

- Python 3.12 or later
- A Massive (Polygon.io) API key for market data

### Installation

```bash
git clone https://github.com/<org>/feelies.git
cd feelies

# Core install (backtest + live + sensors + composition; PORTFOLIO solver optional)
pip install -e ".[dev,massive]"

# To enable the PORTFOLIO turnover optimiser (cvxpy-based) and parquet
# reference factor loadings, also install the [portfolio] extra:
pip install -e ".[dev,massive,portfolio]"
```

The `[portfolio]` extra pulls `cvxpy`, `ecos`, and `pyarrow`. Without
it, PORTFOLIO alphas still load and run; only the optional
turnover-optimisation step and parquet-reference factor loadings are
disabled.

### Environment

Copy `.env.example` and set your API key:

```bash
cp .env.example .env
# Edit .env with your MASSIVE_API_KEY
```

## Running a Backtest

```bash
python scripts/run_backtest.py \
    --symbol AAPL --date 2026-03-24 \
    --config platform.yaml

# No-API-key smoke test of the orchestration pipeline
# (Workstream-D: the synthetic --demo CLI mode was retired with the
#  trade_cluster_drift LEGACY reference alpha; the e2e suite is the
#  supported substitute.)
pytest tests/integration/test_phase4_e2e.py

# TC stress (1.5× cost multiplier)
python scripts/run_backtest.py \
    --symbol AAPL --date 2026-03-24 \
    --stress-cost 1.5

# Emit deterministic event streams for parity audits
python scripts/run_backtest.py --symbol AAPL --date 2026-03-24 \
    --emit-sensor-readings-jsonl \
    --emit-snapshots-jsonl \
    --emit-signals-jsonl \
    --emit-cross-sectional-jsonl \
    --emit-sized-intents-jsonl \
    --emit-hazard-exits-jsonl
```

The report includes a **per-level parity hash** (SHA-256 over the
ordered event stream at each layer) for verifying replay reproducibility
across environments. The platform locks five parity baselines —
sensors, snapshots, signals, sized intents, and hazard exits — under
`tests/determinism/`.

## Operator CLI

The `feelies` console-script (registered via `[project.scripts]` in
`pyproject.toml`; equivalently reachable as `python -m feelies` or
`python -m feelies.cli`) is the read-only operator surface for the
append-only **promotion-evidence ledger** (`src/feelies/alpha/promotion_ledger.py`)
written by `AlphaLifecycle` on every committed lifecycle transition.

```bash
# Per-alpha chronological timeline (text or JSON)
feelies promote inspect kyle_drift_v1 --ledger ./var/promotion_ledger.jsonl
feelies promote inspect kyle_drift_v1 --config platform.yaml --json

# Every alpha in the ledger + current state + transition count
feelies promote list --config platform.yaml

# Re-run the F-2 gate matrix against every recorded F-2-shaped evidence
# package (legacy reason-only metadata is reported as SKIPPED).
# Exit code 3 if any gate now fails today's GateThresholds.
feelies promote replay-evidence kyle_drift_v1 --config platform.yaml

# Preflight the ledger file (parse + LEDGER_SCHEMA_VERSION check)
feelies promote validate --ledger ./var/promotion_ledger.jsonl

# Render the F-2 declarative gate matrix
feelies promote gate-matrix --json
```

All subcommands accept `--ledger PATH` (explicit) or `--config PATH`
(loads a `PlatformConfig` and resolves its `promotion_ledger_path`),
and `--json` for stable machine-readable output.

Exit codes are pinned for CI integration: `0` OK, `1` user error
(missing args / non-existent file / config without
`promotion_ledger_path`), `2` data error (corrupt ledger / malformed
YAML / schema-version mismatch), `3` validation failure
(replay-evidence found gate violations).

The CLI is **read-only and forensic-only** — it never writes to the
ledger and never imports orchestrator / risk-engine production code, so
operator invocation cannot perturb replay determinism (audit A-DET-02).

## Writing an Alpha

Two layer-specific templates ship under `alphas/_template/`. The
recommended starting point for new alphas is
`template_signal.alpha.yaml` (horizon-anchored, regime-gated, cost-
disclosed).  Use `template_portfolio.alpha.yaml` once you have ≥ 2
SIGNAL alphas to compose.  The historical `LEGACY_SIGNAL` reference
template was deleted in workstream D.2 along with the
`trade_cluster_drift` reference alpha and the loader-side
`LEGACY_SIGNAL` dispatch.  Any private alpha still pinned to
`layer: LEGACY_SIGNAL` must be promoted to SIGNAL (cookbook §3) or
held in a private fork that retains the per-tick code-path.

### Layer-to-package matrix

| Layer | Required blocks | Loader entry | Engine | Parity hash |
|---|---|---|---|---|
| `LEGACY_SIGNAL` | (rejected by the loader; row preserved for matrix continuity) | rejected by `AlphaLoader._validate_schema` post-D.2 with a migration pointer | n/a (per-tick `CompositeSignalEngine` deletion scheduled for D.2 PR-2) | n/a |
| `SIGNAL` | `depends_on_sensors`, `horizon_seconds`, `regime_gate`, `cost_arithmetic`, `signal` (snapshot) | `AlphaLoader._load_signal_layer` → `LoadedSignalLayerModule` | `HorizonSignalEngine` | `tests/determinism/test_signal_replay.py` |
| `PORTFOLIO` | `universe`, `depends_on_signals`, `factor_neutralization`, `cost_arithmetic`, `horizon_seconds` | `AlphaLoader._load_portfolio_layer` → `LoadedPortfolioLayerModule` | `CompositionEngine` | `tests/determinism/test_sized_intent_replay.py`, `test_portfolio_order_replay.py` |
| `SENSOR` (reserved) | declared in `platform.yaml` (registry-driven, not alpha YAML) | n/a | `SensorRegistry` | per-sensor unit tests |

See [`alphas/SCHEMA.md`](alphas/SCHEMA.md) for the full field reference
and [`docs/migration/schema_1_0_to_1_1.md`](docs/migration/schema_1_0_to_1_1.md)
for the upgrade cookbook.

### Quick start (schema 1.1 SIGNAL)

```yaml
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_signal_alpha
version: "1.0.0"
description: "One-paragraph summary of the structural edge."
hypothesis: |
  [actor] does [action] because [incentive], leaking into L1 as
  [observable signature].
falsification_criteria:
  - "Mechanism-tied criterion (Inv-2)."

depends_on_sensors:
  - kyle_lambda_60s
  - ofi_ewma
  - spread_z_30d

horizon_seconds: 300

regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "P(normal) > 0.6 and spread_z_30d <= 1.0"
  off_condition: "P(normal) < 0.4 or spread_z_30d > 2.0"
  hysteresis: {posterior_margin: 0.20, percentile_margin: 0.30}

cost_arithmetic:
  edge_estimate_bps: 11.7
  half_spread_bps: 2.5
  impact_bps: 3.0
  fee_bps: 1.0
  margin_ratio: 1.8

signal: |
  def evaluate(snapshot, regime, params):
      z = snapshot.values.get("kyle_lambda_60s_zscore")
      ofi = snapshot.values.get("ofi_ewma")
      if z is None or ofi is None or abs(z) < 2.0:
          return None
      direction = LONG if ofi > 0.0 else SHORT
      return Signal(
          timestamp_ns=snapshot.timestamp_ns,
          correlation_id=snapshot.correlation_id,
          sequence=snapshot.sequence,
          symbol=snapshot.symbol,
          strategy_id="my_signal_alpha",
          direction=direction,
          strength=min(abs(z) / 4.0, 1.0),
          edge_estimate_bps=min(abs(z) * 4.0, 20.0),
      )
```

The `LayerValidator` enforces gates G2–G16 at load time. See
[`alphas/SCHEMA.md`](alphas/SCHEMA.md) for the gate table.

### Hypothesis authoring

Use Grok with the prompt at `grok/prompts/hypothesis_reasoning.md` (and
its companion `sensor_catalog.md` + `mutation_protocol.md`). The
protocol enforces a 7-step generation discipline, refuses anti-patterns
(MA crossovers, "momentum without mechanism", etc.), and emits
machine-validated YAML matching the schema-1.1 contract.

## Platform Configuration

`platform.yaml` controls operating mode, trading universe, risk limits,
cost model, alpha discovery, horizons, and v0.3 strict-mode flags:

```yaml
mode: BACKTEST                            # BACKTEST | PAPER | LIVE
symbols: [AAPL, MSFT, NVDA]
alpha_spec_dir: alphas/                   # Scanned for *.alpha.yaml at boot
regime_engine: hmm_3state_fractional
account_equity: 100000.0

# Horizon registry (Phase 2)
horizons_seconds: [30, 120, 300, 900, 1800]

# Composition (Phase 4)
composition_completeness_threshold: 0.7   # Drop CrossSectionalContext below this
composition_max_universe_size: 50         # PORTFOLIO universe cap (G10)
factor_loadings_max_age_seconds: 86400    # Stale factor loadings → bootstrap fail

# v0.3 strict mode (Phase 3.1)
enforce_trend_mechanism: false            # When true, reject schema-1.1 SIGNAL/PORTFOLIO
                                          # alphas missing trend_mechanism: (G16 strict)

# Architectural gate enforcement (Phase 4)
enforce_layer_gates: true                 # When false, G1/G3 violations log WARNING
                                          # instead of failing — research escape hatch.

# Risk limits
risk_max_position_per_symbol: 50000
risk_max_gross_exposure_pct: 200.0
risk_max_drawdown_pct: 5.0

# IB US Equity Tiered cost model
cost_commission_per_share: 0.0035
cost_exchange_per_share: 0.0005
cost_min_commission: 0.35
cost_max_commission_pct: 1.0

# Execution
execution_mode: passive_limit             # market | passive_limit
passive_fill_delay_ticks: 3
passive_max_resting_ticks: 50
passive_rebate_per_share: 0.002
```

## Design Invariants

These invariants are enforced across the entire platform. See
[`.cursor/rules/platform-invariants.mdc`](.cursor/rules/platform-invariants.mdc)
for the canonical wording and glossary.

**Epistemological**

1. **Structural mechanism required** — every signal and entry must name the causal force being exploited.
2. **Falsifiability before testing** — define what disproves the hypothesis before looking at data.
3. **Evidence over intuition** — scaling, quarantine, and promotion decisions require statistical evidence.
4. **Decay is the default** — every edge is assumed to be eroding.

**Architectural**

5. **Deterministic replay** — same event log + parameters → bit-identical signals, orders, PnL.
6. **Causality enforced** — features/signals at time T use only events with timestamp ≤ T.
7. **Event-driven, typed schemas** — all data flows through typed events on the bus.
8. **Layer separation** — every piece of code belongs to exactly one layer.
9. **Backtest/live parity** — shared core; mode-specific code only behind `ExecutionBackend`.
10. **Clock abstraction** — all timestamps via injectable clock; no raw `datetime.now()` in core logic (CI-enforced via `ruff` `DTZ` rules).

**Safety**

11. **Fail-safe default** — unknown states resolve to reduced exposure, never increased; safety controls only tighten autonomously.
12. **Transaction cost realism** — `expected_edge > 1.5 × round_trip_cost`; must survive 1.5× cost and 2× latency stress.

**Provenance**

13. **Full provenance, versioned and auditable** — every decision traceable to an event; every feature to a version; every strategy to a hypothesis.

## Testing

```bash
# Full test suite
pytest

# Coverage
pytest --cov=feelies --cov-report=term-missing

# Selective markers
pytest -m "not slow"                  # skip benchmarks
pytest -m functional                  # network-backed only
pytest -m backtest_validation         # full validation suite

# Validation suite via script
python scripts/run_validation.py
python scripts/run_validation.py --quick
```

The test suite mirrors `src/feelies/` and includes:

- Unit tests + property-based tests (Hypothesis).
- **Determinism tests** (`tests/determinism/`) — five locked parity
  hashes (sensor / signal / sized-intent / portfolio-order /
  hazard-exit), each subprocess-isolated to detect any non-determinism
  introduced by ordering, RNG, or wall-clock.
- **End-to-end integration tests** (`tests/integration/`) — multi-
  symbol, multi-alpha, mixed-mechanism universes.
- **Performance regression gates** (`tests/perf/`) — Phase 4 ≤ 12 %
  end-to-end throughput; Phase 4.1 ≤ 5 % decay-weighting overhead.
  Per-host pinned baselines (opt-in via `PERF_HOST_LABEL`) live in
  `tests/perf/baselines/v02_baseline.json` and are recorded with
  `python scripts/record_perf_baseline.py --host-label <id>`.
- **Acceptance sweep** (`tests/acceptance/`) — mechanical assertions
  for the v0.2 + v0.3 acceptance matrix
  ([`docs/acceptance/v02_v03_matrix.md`](docs/acceptance/v02_v03_matrix.md)),
  including mypy-strict scope, reference-alpha load invariants
  (`margin_ratio`, factor exposures), G16 rule completeness,
  decay-divergence, strict-mode loading per mechanism family, and
  perf-baseline plumbing.

## Tooling

| Tool | Config | Purpose |
|---|---|---|
| **pytest** | `pyproject.toml` | Test runner, markers, coverage (≥ 80 %) |
| **mypy** | `pyproject.toml` | Strict static type checking (Python 3.12) |
| **ruff** | `pyproject.toml` | Linting + formatting (line length 99) + `DTZ` ban on raw `datetime.now()` |
| **hypothesis** | dev dependency | Property-based testing |

```bash
mypy src/feelies
ruff check src/ tests/
ruff format src/ tests/
```

## Data Pipeline

Market data flows through a two-stage pipeline:

1. **Historical ingest** — `MassiveHistoricalIngestor` downloads L1
   NBBO quotes and trades via Massive REST API, normalises through
   `MassiveNormalizer` into canonical `NBBOQuote` and `Trade` events,
   and stores them in an `EventLog`. Cached to `~/.feelies/cache/`.
2. **Replay** — `ReplayFeed` iterates the `EventLog` in timestamp
   order, feeding the orchestrator's tick pipeline. `SimulatedClock`
   advances to each event's timestamp, preserving causality.

For live operation (future), `MassiveLiveFeed` provides real-time
WebSocket streaming through the same normaliser, ensuring identical
event types flow through the same pipeline.

## License

*Not yet specified.*
