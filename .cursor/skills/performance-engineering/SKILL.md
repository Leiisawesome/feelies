---
name: performance-engineering
description: >
  Performance analysis and optimization for latency-critical intraday trading
  infrastructure. Identifies critical paths, enforces latency budgets, guides
  data structure and concurrency decisions, and balances throughput against
  determinism. Use when profiling tick-to-trade pipelines, optimizing hot loops,
  reducing memory footprint, choosing parallelization strategies, diagnosing GC
  pauses, or reasoning about cache locality, vectorization, lock-free design,
  or performance regression prevention.
---

# Performance & Optimization Engineer

Ensure every component in the trading pipeline meets its latency budget while
preserving determinism and readability. Measure first, optimize second, verify
always.

## Core Invariants

1. **Profile before optimizing** — no speculative optimization; every change justified by measurement
2. **Determinism is non-negotiable** — optimizations must not break replay determinism or backtest/live parity
3. **Budget-driven** — every module has a latency and memory budget; violations are defects
4. **Regression-gated** — performance benchmarks run in CI; regressions block merge
5. **Readability default** — micro-optimization only in measured hot paths; everywhere else, clarity wins

---

## Critical Path

The tick-to-trade pipeline defines the system's latency floor:

```
Market data arrives (T₀)
  → Ingestion + normalization (T₁)
    → Event bus routing (T₂)
      → Feature computation (T₃)
        → Signal evaluation (T₄)
          → Risk check (T₅)
            → Order submission (T₆)
```

### Latency Budget

| Segment | Budget | Hard Ceiling | Notes |
|---------|--------|-------------|-------|
| Ingestion + normalization | 500 μs | 2 ms | Polygon WS parse + canonical format |
| Event bus routing | 50 μs | 200 μs | Single-process: direct dispatch |
| Feature computation | 1 ms | 5 ms | Per-tick incremental update, not full recompute |
| Signal evaluation | 200 μs | 1 ms | Pure function; no I/O |
| Risk check | 100 μs | 500 μs | Lookup-heavy; must be pre-computed |
| Order construction + submission | 500 μs | 2 ms | Serialize + network |
| **End-to-end (T₀ → T₆)** | **< 3 ms** | **< 10 ms** | Total tick-to-order |

Budgets are p99 targets. Measure at p50, p95, p99, p99.9.
If any segment exceeds its hard ceiling, treat as a production incident.

### Backtest Replay Budget

| Operation | Target | Acceptable |
|-----------|--------|------------|
| Single event processing | < 10 μs | < 100 μs |
| Full day replay (1 ticker) | < 30s | < 120s |
| Full day replay (100 tickers) | < 10 min | < 30 min |

Replay speed must not regress. Track events-per-second as a first-class metric.

---

## Measurement Framework

### What to Measure

| Metric | Granularity | Collection Method |
|--------|------------|-------------------|
| End-to-end latency | Per-tick | Timestamped event annotations |
| Per-module wall time | Per-tick | Scoped timers around each pipeline stage |
| CPU time per module | Per-session | `cProfile` / `perf` / sampling profiler |
| Memory footprint | Per-module | `tracemalloc` snapshots at steady state |
| Allocation rate | Per-session | Track object creation in hot path |
| GC pause duration | Per-collection | `gc` callback hooks |
| Cache miss rate | On-demand | `perf stat` / `cachegrind` for critical sections |
| Throughput | Per-session | Events processed per second (sustained) |

### Profiling Protocol

1. **Establish baseline** — measure current performance under representative load
2. **Identify bottleneck** — find the single largest contributor to latency or resource usage
3. **Hypothesize** — state expected improvement and mechanism
4. **Implement** — change only the bottleneck; one variable at a time
5. **Measure again** — compare against baseline under identical conditions
6. **Accept or revert** — if improvement < measurement noise, revert

Never skip step 1. Never combine multiple optimizations in a single measurement cycle.

### Benchmark Harness

Benchmarks must be:
- **Deterministic** — same input produces same timing distribution (within noise)
- **Representative** — use production-scale data (full trading day, realistic symbol count)
- **Isolated** — no background load interference; pin to CPU cores if needed
- **Versioned** — benchmark code and reference data checked into the repo
- **Automated** — runnable in CI with regression detection

---

## Optimization Hierarchy

Apply in order. Stop when the budget is met.

### 1. Algorithmic Complexity

| Pattern | Replace With |
|---------|-------------|
| O(n) search in hot path | O(1) hash lookup or pre-sorted binary search |
| Full recomputation on tick | Incremental / streaming update |
| Repeated allocation | Object pooling or pre-allocation |
| String-keyed dispatch | Integer enum dispatch |

### 2. Data Structure Selection

| Concern | Guideline |
|---------|-----------|
| Cache locality | Prefer arrays/contiguous buffers over linked structures |
| Column vs row | Columnar (NumPy/Polars) for analytics; struct-of-arrays for hot path |
| Hash maps | Pre-size to avoid rehash; consider open-addressing for small maps |
| Ring buffers | Use for fixed-window rolling computations (spread, volatility) |
| Typed arrays | `numpy.float64` arrays over Python lists for numerical data |

### 3. Vectorization

| When | How |
|------|-----|
| Batch feature computation | NumPy / Polars vectorized ops; avoid Python-level loops |
| Cross-sectional signals | Vectorize across symbols within a time slice |
| Rolling statistics | `numpy.lib.stride_tricks` or Polars `rolling_*` |
| Avoid | Vectorizing single-event processing (overhead exceeds gain) |

### 4. Parallelization

| Boundary | Strategy |
|----------|----------|
| Symbol-level independence | Process symbols in parallel (multiprocessing or async) |
| Feature engine | Parallelize independent feature groups; merge at signal layer |
| I/O-bound work | `asyncio` for network (broker API, data feeds) |
| CPU-bound batch | `multiprocessing` or `concurrent.futures.ProcessPoolExecutor` |
| Within-tick pipeline | **Do not parallelize** — sequential for determinism |

**Hard rule**: the within-tick pipeline (ingestion → feature → signal → risk → order)
is strictly sequential per symbol. Parallelism is across symbols or across
independent batch operations, never within the causal chain.

### 5. Lock-Free / Low-Lock Patterns

| Pattern | Use Case |
|---------|----------|
| Single-writer queues | Event bus dispatch (one producer, multiple consumers) |
| Immutable event objects | Events never mutated after creation; safe to share without locks |
| Copy-on-write snapshots | Feature state snapshots for concurrent readers |
| Atomic counters | Throughput / latency metric accumulators |

Avoid shared mutable state in the hot path. If unavoidable, prefer
single-writer / multi-reader patterns over mutexes.

---

## Memory Management

### Python-Specific Concerns

| Issue | Mitigation |
|-------|-----------|
| GC pauses in hot path | Disable GC during tick processing; run between sessions or during idle |
| Object churn | Pre-allocate buffers; reuse objects via pools; avoid temporary dicts/lists in loops |
| Reference cycles | Break cycles explicitly in long-lived objects; use `weakref` where appropriate |
| Large DataFrame copies | Use views / zero-copy slicing; `.values` for NumPy pass-through |
| Memory leaks | Periodic `tracemalloc` snapshots; diff between start and steady state |

### Memory Budgets

| Component | Budget | Rationale |
|-----------|--------|-----------|
| Per-symbol feature state | < 1 MB | Scales linearly with symbol count |
| Event bus backlog | < 100 MB | Bounded ring buffer; overflow = drop + alert |
| Historical data (in-memory) | < 2 GB per day per symbol | Parquet memory-mapped when possible |
| Total process RSS | < 8 GB (configurable) | Monitor and alert on approach |

---

## Performance Anti-Patterns

| Anti-Pattern | Why It Hurts | Fix |
|-------------|-------------|-----|
| Logging in hot path (string formatting) | Allocation + I/O per tick | Guard with log-level check; defer formatting |
| `datetime` parsing per tick | Slow; allocates | Parse once at ingestion; propagate as int64 nanos |
| Dict-of-dicts for feature state | Cache-hostile; GC pressure | Flat NumPy arrays or typed dataclass |
| Deep copy of event objects | Unnecessary allocation | Events are immutable; share references |
| Global interpreter lock contention | Threads block each other | Use multiprocessing for CPU parallelism |
| Unbounded queues | Memory leak under load | Ring buffers with overflow policy |
| Premature optimization | Wasted effort; obscured code | Profile first; optimize measured bottlenecks only |

---

## Regression Prevention

### CI Performance Gate

Every PR that touches hot-path code must:

1. Run the benchmark suite against the target branch baseline
2. Report latency and throughput delta
3. Fail if any metric regresses beyond threshold (default: 10% at p99)

### Tracking

| Metric | Storage | Visualization |
|--------|---------|---------------|
| Per-module p50/p95/p99 latency | Time-series DB or flat file per commit | Trend chart over last 50 commits |
| Events per second (throughput) | Same | Same |
| Peak RSS | Same | Same |
| GC pause count and duration | Same | Same |

Alert on sustained regression trends, not just single-commit spikes.

---

## Tradeoff Framework

When a performance decision involves a tradeoff, document it explicitly:

| Tradeoff | Guidance |
|----------|----------|
| Readability vs speed | Default to readable. Micro-optimize only in profiled hot paths. Comment *why*. |
| Throughput vs determinism | Determinism wins. Never introduce non-determinism for speed. |
| Memory vs CPU | Prefer memory (pre-compute, cache, materialize) when within budget. |
| Latency vs abstraction | Thin abstractions in hot path (no virtual dispatch chains). Full abstractions elsewhere. |
| Generality vs specialization | Specialize hot paths for known data shapes; keep cold paths generic. |

---

## Integration Points

| Dependency | Performance Interface |
|------------|---------------------|
| System Architect (system-architect skill) | Layer boundaries define measurement points; clock abstraction for timing |
| Backtest Engine (backtest-engine skill) | Replay speed targets; event processing budget; single-event latency |
| Live Execution (live-execution skill) | End-to-end latency monitoring; signal-to-fill latency histograms |
| Data Engineering (data-engineering skill) | Ingestion throughput; storage I/O; query-path latency (Parquet scans) |
| Feature Engine (feature-engine skill) | Per-tick compute budget; incremental update enforcement; memory budget |
| Signal Layer | Signal evaluation latency budget |
| Risk Engine (risk-engine skill) | Risk check latency budget; pre-computed constraint lookups |
