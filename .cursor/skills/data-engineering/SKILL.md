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

## Ingestion Pipeline

| Capability | Requirement |
|---|---|
| Real-time streaming | Polygon WebSocket → canonical event format |
| Historical backfill | Idempotent; resumable from last checkpoint |
| Gap detection | Sequence breaks surfaced immediately, never silently skipped |
| Deduplication | Exact-duplicate and logical-duplicate elimination |
| Timestamp normalization | All times UTC nanoseconds; exchange time and receipt time tracked separately |

## Validation & Integrity

- **Schema validation**: every inbound message validated against typed schema before persistence
- **Sequence integrity**: detect out-of-order, missing, or duplicate sequence numbers per feed
- **Clock reconciliation**: maintain offset between exchange timestamp and receipt timestamp; alert on drift > threshold
- **Latency measurement**: annotate every event with ingestion latency (receipt − exchange time)

## Storage Design

| Layer | Description |
|---|---|
| Raw immutable | Append-only log of original messages — never mutated |
| Normalized events | Schema-conformed, deduplicated, gap-annotated event stream |
| Feature snapshots | Optional; versioned and reproducible from normalized events |

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
