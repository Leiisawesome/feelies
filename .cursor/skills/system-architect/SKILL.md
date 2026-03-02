---
name: system-architect
description: >
  Foundational system architecture for a unified intraday trading platform.
  Enforces layer separation, determinism, event-driven design, and dual-mode
  (research/live) behavioral equivalence under L1 NBBO constraints (Polygon.io
  Advanced). Use when designing system components, defining layer boundaries,
  making architectural decisions, or reasoning about cross-layer interactions,
  failure modes, or deterministic replay.
---

# System Architect — Foundation

Design all components for a unified intraday trading platform where research
backtesting and live trading share core logic, behavioral equivalence is
enforced, and determinism is guaranteed in replay mode.

## System Boundaries

All code must belong to exactly one of these layers:

| Layer | Responsibility |
|-------|---------------|
| Market Data Ingestion | Normalize Polygon L1 NBBO into canonical events |
| Event Bus | Route typed events with deterministic ordering |
| Feature Engine | Stateful feature computation from event streams (see feature-engine skill) |
| Signal Engine | Pure functions: features → signals (no side effects) |
| Risk Engine | Position limits, exposure checks, drawdown gates |
| Execution Engine | Order routing, fill simulation (backtest) / broker API (live) |
| Portfolio Layer | Position tracking, PnL, capital allocation |
| Storage Layer | Event log, feature snapshots, trade journal |
| Monitoring | Latency histograms, throughput, health checks, kill-switch |

## Hard Rules

1. **No cross-layer leakage** — strategy logic never in ingestion; execution logic never in notebooks; no hidden global state.
2. **Event-driven, not polling** — all data flow through typed events on the bus.
3. **Clock abstraction** — all timestamps via an injectable clock (wall clock live, simulated clock backtest). No raw `datetime.now()` in core logic.
4. **Deterministic replay** — given the same event log + parameters, produce identical signals, orders, and PnL.
5. **Explicit latency modeling** — annotate every path with expected latency; measure actual vs expected in production.
6. **Canonical message formats** — define typed schemas for every event crossing a layer boundary.

## Tradeoff Documentation

When making architectural decisions, explicitly state the tradeoff:

- Simplicity vs performance
- Memory vs CPU
- Latency vs abstraction
- Flexibility vs type safety

## Failure & Degradation

- Every component defines its failure mode (crash, degrade, retry).
- Stale data must be detected and surfaced, never silently consumed.
- Kill-switch conditions defined per-strategy and globally.
- Throughput bottlenecks and latency-critical paths identified and documented.

## Observability & Monitoring

The Monitoring layer listed in System Boundaries is a cross-cutting concern.
Every other layer emits telemetry into it; no layer implements its own
alerting or dashboarding in isolation.

### Pillars

| Pillar | What | How |
|--------|------|-----|
| Logging | Structured, machine-parseable event logs | JSON lines; one log stream per layer; no unstructured prints |
| Metrics | Numeric time-series (latency, throughput, PnL, fill rate) | Counters, gauges, histograms; emitted via event bus |
| Tracing | End-to-end request/event correlation | Correlation ID assigned at ingestion; propagated through every layer |
| Alerting | Threshold- and anomaly-based notifications | Defined per layer; routed through a central alert manager |

### Correlation ID

Every inbound market data event receives a unique `correlation_id` at
ingestion. This ID propagates through feature computation, signal
generation, risk check, and order submission. A single correlation ID
links a quote update to the trade it ultimately caused — enabling
end-to-end latency measurement and root-cause investigation.

```
correlation_id = f"{symbol}:{exchange_timestamp_ns}:{sequence}"
```

### Metric Collection

Each layer emits metrics onto the event bus as typed `METRIC` events:

| Layer | Key Metrics |
|-------|------------|
| Ingestion | Events/sec, parse errors, feed latency, gap count |
| Feature Engine | Compute time per tick, warm-up status, stale symbol count |
| Signal Engine | Signals emitted/sec, signal-to-noise ratio, evaluation time |
| Risk Engine | Checks/sec, rejection rate, regime state, drawdown level |
| Execution Engine | Orders/sec, fill rate, slippage, latency histograms |
| Storage | Write throughput, disk usage, checkpoint lag |

Metrics are collected at p50, p95, p99, p99.9 where applicable.

### Alert Routing

| Severity | Response Time | Channel | Examples |
|----------|--------------|---------|----------|
| Info | Async review | Log only | Feature warm-up complete, regime transition |
| Warning | < 15 min | Log + dashboard highlight | Elevated slippage, latency approaching ceiling |
| Critical | < 1 min | Log + push notification | Kill switch fired, position reconciliation failure |
| Emergency | Immediate (automated) | Automated safety response + notification | Unrecoverable state, broker disconnect |

Critical and emergency alerts activate safety controls autonomously.
Human review follows but does not gate the safety response.

### Dashboard Requirements

Operational dashboards must surface at minimum:
- Real-time PnL curve (gross, net, by strategy)
- Tick-to-trade latency histogram (updating)
- Per-symbol feature staleness map
- Risk constraint utilization (how close to limits)
- Safety control state (kill switch, circuit breaker, throttle)
- Feed health (events/sec, gap count, reconnect count)

Dashboards read from the metric stream. They never query production
databases or add load to the critical path.

### Ownership Boundaries

Observability infrastructure (log aggregation, metric storage, alert
routing, dashboards) is owned by this layer. Individual layers define
*what* they emit; this layer defines *how* it is collected, stored,
correlated, and surfaced. Skill-specific monitoring details:
- Execution quality metrics: live-execution skill
- Latency budgets and profiling: performance-engineering skill
- Forensic health reports: post-trade-forensics skill
- Risk snapshots and PnL attribution: risk-engine skill

---

## Portfolio Layer Ownership

The Portfolio Layer (position tracking, PnL, capital allocation) is not a
separate skill. Its responsibilities are distributed:

| Responsibility | Owning Skill |
|---------------|-------------|
| Position tracking and reconciliation | live-execution (live) / backtest-engine (replay) |
| PnL decomposition and attribution | risk-engine |
| Capital allocation and risk budgets | risk-engine (portfolio governor) |
| Position state interface | system-architect (`PositionStore` interface behind `ExecutionBackend`) |

All three skills share the `PositionStore` interface defined here. Mode-specific
implementations (broker-backed live, simulated backtest) are behind the
`ExecutionBackend` abstraction.

---

## Design Targets

- **Auditability**: every decision traceable to an event
- **Determinism**: replay produces identical output
- **Scalability**: horizontal scaling at ingestion and feature layers
- **Testability**: every layer testable in isolation with mock events
