---
name: data-engineering
description: >
  Data engineering standards for high-fidelity ingestion, validation, and storage
  of L1 NBBO and trade data from Polygon.io. Use when building data pipelines,
  designing storage schemas, implementing gap detection or deduplication, working
  on historical backfill, or reasoning about data integrity, replay invariants,
  or recovery protocols.
---

# Data Engineering — Market Data & Storage

High-fidelity ingestion and storage of L1 NBBO and trades.

## Core Invariants

Inherits platform invariants 5 (deterministic replay), 6 (causality),
7 (event-driven typed schemas), 13 (full provenance). Additionally:

1. **Immutable raw log** — original messages are append-only and never mutated; all downstream representations derive from this log
2. **Gaps are visible** — missing data is surfaced via `DataHealth` SM transitions, never silently skipped or interpolated
3. **Schema as contract** — every event crossing the ingestion boundary conforms to a typed schema (`NBBOQuote`, `Trade`); untyped or malformed data is rejected at the boundary

---

## Canonical Event Types

The ingestion layer produces two canonical event types from `core/events.py`:

- `NBBOQuote` — L1 quote with symbol, bid, ask, bid_size, ask_size,
  exchange_timestamp_ns, conditions
- `Trade` — trade print with symbol, price, size, exchange_timestamp_ns,
  conditions

Both inherit from `Event`, carrying `timestamp_ns` (from injectable clock),
`correlation_id`, and `sequence` for provenance.

## Normalizer Protocol

This skill owns the `MarketDataNormalizer` protocol (`ingestion/normalizer.py`) —
the system boundary. All market data enters through it:

```python
class MarketDataNormalizer(Protocol):
    def on_message(self, raw: bytes, received_ns: int, source: str) -> Sequence[NBBOQuote | Trade]: ...
    def health(self, symbol: str) -> DataHealth: ...
    def all_health(self) -> dict[str, DataHealth]: ...
```

Correlation IDs are assigned at the ingestion boundary via
`make_correlation_id(symbol, exchange_timestamp_ns, sequence)` from
`core/identifiers.py`.

## Ingestion Sources

Three paths bring market data into the platform. The first two converge
through `PolygonNormalizer.on_message()` — the single ingestion boundary.
The third reads already-normalized events from `EventLog`.

| Source | Polygon API | Implementation | Feeds Into | Used By Mode |
|--------|-------------|----------------|------------|--------------|
| Historical backfill | REST `/v3/quotes`, `/v3/trades` | `PolygonHistoricalIngestor` (`ingestion/polygon_ingestor.py`) | `EventLog` (for later replay) | None directly — populates storage |
| Live stream | WebSocket (`Q.*`, `T.*`) | `PolygonLiveFeed` (`ingestion/polygon_ws.py`) | Orchestrator tick pipeline via `MarketDataSource.events()` | `PAPER_TRADING_MODE`, `LIVE_TRADING_MODE` |
| Replay | `EventLog.replay()` | `ReplayFeed` (`ingestion/replay_feed.py`) | Orchestrator tick pipeline via `MarketDataSource.events()` | `BACKTEST_MODE`, `RESEARCH_MODE` |

**Key invariant**: backfill and live both normalize through
`PolygonNormalizer` (source tags `"polygon_rest"` and `"polygon_ws"`
respectively). Replay reads already-normalized events from `EventLog`.
The orchestrator receives identical `NBBOQuote`/`Trade` types regardless
of source — it never knows or cares which path produced them (invariant 9).

### Historical Backfill (`PolygonHistoricalIngestor`)

Batch ETL pipeline: Polygon REST API → `PolygonNormalizer` → `EventLog`.
Runs offline to populate an `EventLog` that is later replayed via
`ReplayFeed`. This is NOT a `MarketDataSource` — it does not feed the
orchestrator directly.

- **Checkpoint-based resumability**: accepts an optional `BackfillCheckpoint`
  protocol (`ingestion/polygon_ingestor.py`). Completed `(symbol, feed_type)`
  pairs are skipped on retry. `InMemoryCheckpoint` provides volatile
  dedup within a single run; persistent implementations can be injected
  for cross-run resumability.
- **Duplicate tracking**: `IngestResult.duplicates_filtered` reports the
  total exact-duplicates filtered by the normalizer during the run.

### Live Stream (`PolygonLiveFeed`)

Real-time WebSocket feed implementing `MarketDataSource`:

- Background thread runs an asyncio event loop with the WS connection
- Auth and subscription responses are validated — failed auth raises
  `ConnectionError`, triggering the reconnect-with-backoff loop
- Reconnection with exponential backoff (1s → 60s) on disconnect
- Events buffered in a bounded `queue.Queue` (100k capacity); overflow
  drops events with a warning (fail-safe: never block the WS reader)

### Replay (`ReplayFeed`)

Generic `MarketDataSource` adapter over `EventLog.replay()`. Polygon-
agnostic — works with any `EventLog` populated through any ingestor.
When a `SimulatedClock` is provided, advances the clock to each event's
`exchange_timestamp_ns` before yielding (deterministic time progression).

## Ingestion Pipeline

| Capability | Requirement | Implementation Status |
|---|---|---|
| Real-time streaming | Polygon WebSocket → `PolygonNormalizer.on_message()` → `NBBOQuote` / `Trade` | Implemented (`PolygonLiveFeed`) |
| Historical backfill | Idempotent; resumable from last checkpoint via `BackfillCheckpoint` | Implemented (`PolygonHistoricalIngestor`) |
| Gap detection | Sequence breaks surfaced via `DataHealth` SM transitions; auto-recovers to `HEALTHY` when continuity resumes | Implemented (`PolygonNormalizer._check_gap`) |
| Deduplication | Exact-duplicate elimination with count tracking (`PolygonNormalizer.duplicates_filtered`) | Implemented |
| Timestamp normalization | All times UTC nanoseconds; exchange time and receipt time tracked separately | Implemented |
| WS auth validation | Auth and subscribe responses validated; failure triggers reconnect | Implemented (`PolygonLiveFeed._validate_status_response`) |

## Data Integrity State Machine

Per-symbol data integrity is tracked by the `DataHealth` SM
(`ingestion/data_integrity.py`) with 4 states:

| State | Transitions To | Meaning |
|-------|---------------|---------|
| `HEALTHY` | GAP_DETECTED, CORRUPTED | Normal operation |
| `GAP_DETECTED` | HEALTHY, CORRUPTED | Sequence gap found; gap-fill in progress |
| `CORRUPTED` | RECOVERING | Unresolvable data corruption |
| `RECOVERING` | HEALTHY, CORRUPTED | Recovery attempt in progress |

The orchestrator checks `normalizer.health(symbol)` at the top of each
tick. If CORRUPTED during a trading mode, macro transitions to DEGRADED.

## Validation & Integrity

- **Schema validation**: every inbound message validated against typed schema before persistence
- **Sequence integrity**: detect out-of-order, missing, or duplicate sequence numbers per feed
- **Clock reconciliation**: maintain offset between exchange timestamp and receipt timestamp; alert on drift > threshold
- **Latency measurement**: annotate every event with ingestion latency (receipt − exchange time)

## Storage Protocols

The storage layer exposes two key protocols:

### EventLog (`storage/event_log.py`)

Append-only, sequence-based event store for replay and audit:

```python
class EventLog(Protocol):
    def append(self, event: Event) -> None: ...
    def append_batch(self, events: Sequence[Event]) -> None: ...
    def replay(self, start_sequence: int = 0, end_sequence: int | None = None) -> Iterator[Event]: ...
    def last_sequence(self) -> int: ...
```

- `append()` — persist a single event; called by the orchestrator at
  M1 (MARKET_EVENT_RECEIVED) for every inbound quote and in
  `_process_trade()` for every trade.
- `append_batch()` — persist a chunk of events atomically; used by
  `PolygonHistoricalIngestor` for chunk-aware ingestion and by
  `scripts/run_backtest.py` for loading resequenced event streams.
- `replay()` — replay by sequence range for deterministic backtest
  replay (invariant 5).
- `last_sequence()` — sequence number of the most recent event.

### TradeJournal (`storage/trade_journal.py`)

Structured, queryable trade lifecycle store — distinct from EventLog:

```python
@dataclass(frozen=True, kw_only=True)
class TradeRecord:
    order_id: str
    symbol: str
    strategy_id: str
    side: Side
    requested_quantity: int
    filled_quantity: int
    fill_price: Decimal | None
    signal_timestamp_ns: int
    submit_timestamp_ns: int
    fill_timestamp_ns: int | None
    slippage_bps: Decimal
    fees: Decimal
    realized_pnl: Decimal
    correlation_id: str
    metadata: dict[str, str]

class TradeJournal(Protocol):
    def record(self, trade: TradeRecord) -> None: ...
    def query(self, *, symbol: str | None = None, strategy_id: str | None = None,
              start_ns: int | None = None, end_ns: int | None = None) -> Iterator[TradeRecord]: ...
```

Failure mode: degrade. If journal write fails, EventLog still has raw events —
the journal can be rebuilt. Journal unavailability does not halt trading.

**Ownership boundary**: this skill owns the storage implementation. The
post-trade-forensics skill consumes `TradeJournal.query()` for analysis.
The live-execution skill produces `TradeRecord` entries from fill events.

### EventSerializer (NOT YET IMPLEMENTED)

Round-trip serialization for event persistence. When implemented, must
guarantee bit-deterministic output — the same event serialized twice
produces identical bytes.

## Storage Design

| Layer | Description | Protocol |
|---|---|---|
| Raw immutable | Append-only log of original messages — never mutated | `EventLog` |
| Normalized events | Schema-conformed, deduplicated, gap-annotated event stream | `EventLog.replay()` |
| Feature snapshots | Versioned and reproducible from normalized events | `FeatureSnapshotStore` |
| Trade journal | Structured trade lifecycle records | `TradeJournal` |

## Design Decisions

- **Storage format**: columnar (Parquet) for analytics; row-based (append log) for ingestion
- **Partitioning**: by symbol and date (`/symbol=AAPL/date=2026-03-02/`)
- **Compression**: Zstandard for cold storage; LZ4 for hot/query path
- **Query path**: optimized for sequential time-range scans per symbol (backtesting primary access pattern)

## Operating Assumptions

1. L1 data is **incomplete** — gaps are expected, not exceptional
2. Data errors **will happen** — corrupt prices, stale quotes, phantom trades
3. Silent corruption must be **detected** — checksums, row counts, price-range sanity checks
4. Upstream feeds **will disconnect** — reconnection with gap-fill is mandatory

## Recovery & Replay

- Define recovery protocol for every failure mode (feed drop, schema change, storage fault)
- Replay from raw immutable log must reproduce identical normalized output (replay invariant)
- All backfills tagged with provenance metadata (source, timestamp, version)

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| System Architect (system-architect skill) | `Clock`, `EventBus`, layer boundaries; `Event` base class for all typed events |
| Feature Engine (feature-engine skill) | Produces `NBBOQuote`/`Trade` consumed by `FeatureEngine.update()` at M2 |
| Backtest Engine (backtest-engine skill) | `EventLog.replay()` drives backtest via `MarketDataSource`; `SimulatedClock` for deterministic time |
| Live Execution (live-execution skill) | Real-time `NBBOQuote`/`Trade` feed for live pipeline; reference pricing for slippage |
| Risk Engine (risk-engine skill) | Real-time NBBO for mark-to-market, volatility estimation, regime detection |
| Post-Trade Forensics (post-trade-forensics skill) | `EventLog.replay()` for historical forensic analysis |
| Testing & Validation (testing-validation skill) | `DataHealth` SM transitions; schema validation; gap injection for fault tests |

The data engineering layer is the system's first contact with the external
world. Every downstream layer depends on the fidelity of the events it
produces. No other layer ingests raw market data — all access is through
`MarketDataNormalizer` and `EventLog`.
