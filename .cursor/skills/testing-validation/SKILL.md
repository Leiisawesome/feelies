---
name: testing-validation
description: >
  Testing and validation framework for system integrity across the intraday
  trading platform. Designs unit, property-based, replay reproducibility, and
  sim-vs-live divergence tests. Implements fault injection, data corruption,
  latency spike, and exchange disconnect simulation. Defines acceptance criteria
  and promotion pipeline from research through scaled capital deployment.
  Maintains versioned strategy artifacts, backtest reproducibility logs, and
  configuration audit trails. Use when designing test suites, implementing
  chaos testing, defining deployment gates, building CI/CD for strategies,
  auditing configuration changes, or reasoning about reproducibility,
  promotion criteria, or pre-deployment validation.
---

# Testing & Validation Director

Responsible for system integrity end-to-end. No strategy, component, or
configuration change reaches production without passing a deterministic,
reproducible validation pipeline. The default posture is **deny deployment**
— evidence of correctness must be affirmatively produced, not assumed.

## Core Invariants

Inherits platform invariants 3 (evidence over intuition → gated promotion),
5 (deterministic replay → reproducibility), 13 (provenance → auditable configuration).
Additionally:

1. **Tests are first-class code** — test infrastructure receives the same design rigor as production code
2. **Failure injection is mandatory** — components that have not been tested under failure are assumed to fail in production
3. **Regression is unacceptable** — passing tests never regress; new failures block the pipeline

---

## Test Architecture

### Unit Tests

Every component tested in isolation with mock event streams. Tests are
deterministic — no wall-clock dependencies, no network calls, no randomness
without fixed seeds.

| Layer | Test Focus | Key Assertions |
|-------|-----------|----------------|
| Market Data Ingestion | Schema validation, dedup, gap detection | Malformed messages rejected; duplicates eliminated; gaps surfaced |
| Event Bus | Routing, ordering, type safety | Events delivered in order; type mismatches rejected |
| Feature Engine | Stateful computation correctness | Features match hand-computed values; state resets cleanly |
| Signal Engine | Pure function behavior | Same features → same signals; no side effects |
| Risk Engine | Constraint enforcement, regime transitions | Limits enforced; drawdown gates fire at thresholds; fail-safe on unknown state |
| Execution Engine | Order lifecycle, state machine transitions | No invalid transitions; idempotency honored; timeout handling correct |
| Portfolio Layer | Position tracking, PnL computation | Fills reconcile; PnL components sum to total |

Coverage requirements:
- Branch coverage > 90% for risk engine and execution engine
- Line coverage > 80% for all core layers
- All edge cases documented in test names (not just happy paths)

### Property-Based Tests

Invariants that must hold for all valid inputs. Use hypothesis-style
generators to explore the input space.

| Invariant | Generator | Property |
|-----------|-----------|----------|
| Causal ordering | Random event streams with shuffled timestamps | Features never depend on future events |
| Deterministic replay | Same event log + config, two independent runs | Signals, orders, PnL are bit-identical |
| Position conservation | Random fill sequences | Sum of fills = final position; no phantom shares |
| Risk monotonic safety | Random constraint-tightening sequences | Safety level never decreases without explicit re-auth |
| PnL decomposition | Random trade sequences with known prices | Alpha + beta + costs = total return (to floating-point tolerance) |
| Clock monotonicity | Arbitrary event replay with latency injection | Simulated clock never moves backward |
| Idempotent submission | Duplicate signal sequences | No duplicate orders produced |
| State machine validity | Random state transition attempts | No illegal transitions accepted; terminal states are absorbing |

Run property-based tests with at least 1000 examples per property.
Failures are shrunk to minimal reproducible cases and persisted as
regression tests.

### Replay Reproducibility Tests

Verify that backtest replay is deterministic across environments.

| Test | Method | Pass Criteria |
|------|--------|---------------|
| Same-machine determinism | Run identical config twice on same machine | Bit-identical PnL curve, trade log, position series |
| Cross-machine determinism | Run identical config on two different machines | Bit-identical outputs (requires fixed seeds, no hardware-dependent floats) |
| Version upgrade determinism | Run same config on old and new code versions | Identical outputs, or documented and justified divergence |
| Checkpoint resume | Interrupt replay mid-stream; resume from checkpoint | Final output identical to uninterrupted run |
| Seed sensitivity | Vary random seed for stochastic components | PnL distribution matches expected envelope; no seed produces degenerate results |

Reproducibility tests run on every code change that touches replay logic,
fill models, or feature computation.

### Simulation vs Live Divergence Tests

Detect structural drift between backtest assumptions and live behavior.

| Metric | Comparison | Alert Threshold | Blocking Threshold |
|--------|-----------|-----------------|-------------------|
| Fill rate | Backtest predicted vs live realized | > 10% relative drift | > 20% relative drift |
| Slippage distribution | Backtest model vs live fills | KS test p < 0.10 | KS test p < 0.01 |
| Latency profile | Injected distribution vs measured | KS test p < 0.10 | KS test p < 0.01 |
| PnL compression ratio | Live PnL / backtest PnL (same period) | < 0.6 or > 1.2 | < 0.4 or > 1.5 |
| Signal-to-fill timing | Backtest assumed vs live measured | > 2x mean difference | > 3x mean difference |
| Order rejection rate | Backtest (near 0) vs live broker rejects | > 3% of submissions | > 8% of submissions |

Divergence tests run continuously in live mode. Blocking thresholds trigger
circuit breaker evaluation. Drift reports feed back into backtest model
calibration.

---

## Fault Injection Framework

### Fault Injection Testing

Systematically inject failures into every layer. Components must degrade
gracefully — no silent corruption, no undefined behavior, no hung states.

| Fault | Target Layer | Expected Behavior |
|-------|-------------|-------------------|
| Null/malformed event | Ingestion | Reject and log; do not propagate |
| Out-of-order timestamps | Event Bus | Detect, reorder or flag; never silently consume |
| NaN/Inf feature values | Feature Engine | Detect and suppress; do not pass to signal engine |
| Stale quotes (frozen NBBO) | Risk Engine | Detect via heartbeat; block new orders after threshold |
| Concurrent state mutation | Execution Engine | Lock or CAS prevents corruption; invariant checks catch violations |
| Disk full during write | Storage Layer | Fail loudly; no partial writes; recovery from last good state |

### Data Corruption Simulation

Inject corrupt data at ingestion boundary and verify downstream integrity.

| Corruption Type | Injection Method | Validation |
|-----------------|-----------------|------------|
| Price spikes | Multiply price by 10x or 0.1x randomly | Outlier filter catches; feature engine not contaminated |
| Negative spreads | Set bid > ask | Detected as invalid NBBO; event dropped with alert |
| Zero sizes | Set bid_size or ask_size to 0 | Handled as no-liquidity; no fills attempted |
| Duplicate timestamps | Replay same event twice | Dedup catches; no double-counting in features |
| Schema violations | Remove required fields; add unexpected fields | Schema validator rejects; raw log preserved for diagnosis |
| Encoding errors | Inject invalid UTF-8 or corrupt binary | Deserialization fails safely; no partial state updates |

### Latency Spike Simulation

Model degraded network and processing conditions.

| Scenario | Injection | Expected System Response |
|----------|-----------|------------------------|
| Network delay spike | Add 500ms–2s delay to broker gateway | Orders timeout; retry logic activates; circuit breaker evaluates |
| Processing bottleneck | Throttle feature engine to 10x normal latency | Signals delayed; stale-signal detection fires |
| Feed delay | Delay market data delivery by 1–5s | Stale-data detection activates; risk engine blocks orders |
| Burst latency | Intermittent 100ms spikes (10% of events) | Latency histogram shifts; alert fires if sustained |
| Clock skew | Drift simulated clock ±50ms from exchange time | Clock reconciliation detects; uses conservative timestamp |

### Exchange Disconnect Simulation

Model complete and partial feed failures.

| Scenario | Injection | Expected System Response |
|----------|-----------|------------------------|
| Full disconnect | Drop all market data for 30s | Gap detection fires; orders blocked; reconnect with gap-fill |
| Partial disconnect | Drop data for subset of symbols | Per-symbol staleness detection; affected symbols frozen |
| Reconnect storm | Rapid disconnect/reconnect (5 times in 60s) | Backoff logic prevents thrashing; stable state required before resuming |
| Broker API outage | Reject all order submissions | Orders queue with TTL; kill switch if outage exceeds threshold |
| Execution feed loss | Stop execution reports while orders live | Reconciliation via position query; flag unconfirmed fills |

All fault injection tests must be runnable in CI. Fault injection in
staging environments uses the same framework with real (non-production)
broker connections.

---

## Acceptance Criteria & Promotion Pipeline

### Pre-Deployment Acceptance Criteria

No strategy or system change is deployed to capital without passing every gate.

| Gate | Criteria | Evidence Required |
|------|----------|-------------------|
| Code quality | All tests pass; no new linter warnings; review approved | CI green; PR approval |
| Unit coverage | Branch coverage thresholds met per layer | Coverage report |
| Property tests | All invariants hold for ≥1000 examples | Test report with seed log |
| Replay determinism | Bit-identical across 3 independent runs | Diff report (empty) |
| Backtest integrity | No lookahead bias; causal ordering verified | Integrity check log |
| Cost sensitivity | Strategy profitable at 1.5x cost assumptions | Sensitivity report |
| Latency sensitivity | Strategy profitable at 2x latency assumptions | Sensitivity report |
| Drawdown bounded | Max drawdown < kill-switch threshold across all test periods | Drawdown analysis |
| Fault resilience | All fault injection tests pass | Fault test report |
| Sim-vs-live baseline | Divergence metrics within alert thresholds on paper trading | Divergence report |

### Promotion Pipeline

```
Research → Paper Trading → Small Capital → Scaled Deployment
```

| Stage | Environment | Capital | Duration | Exit Criteria |
|-------|-------------|---------|----------|---------------|
| Research | Backtest only | $0 | Until acceptance gates pass | All pre-deployment criteria met |
| Paper Trading | Live data, simulated execution | $0 | ≥ 5 trading days | Sim-vs-live metrics within thresholds; no anomalous behavior |
| Small Capital | Live execution, minimal size | ≤ 1% of target allocation | ≥ 10 trading days | PnL compression ratio 0.5–1.0; execution quality nominal |
| Scaled Deployment | Live execution, full allocation | Target allocation | Ongoing | Continuous monitoring; regression triggers demotion |

Promotion between stages requires:
1. All acceptance criteria for the current stage met
2. Written sign-off documenting evidence reviewed
3. No open blocking issues in the validation pipeline
4. Rollback plan documented and tested

### Demotion Triggers

| Trigger | Response |
|---------|----------|
| PnL compression ratio < 0.4 for 3 consecutive days | Demote to paper trading; recalibrate models |
| Kill switch activation | Demote to research; root cause analysis required |
| Divergence metric exceeds blocking threshold | Demote one stage; investigate |
| Reproducibility failure | Halt all stages; fix before any resumption |
| Undocumented configuration change in production | Immediate halt; audit trail investigation |

---

## Artifact Management

### Versioned Strategy Artifacts

Every deployed strategy is a versioned, immutable bundle.

| Artifact | Contents | Versioning |
|----------|----------|------------|
| Strategy bundle | Signal logic, feature definitions, risk parameters | Semantic versioning; git SHA tagged |
| Configuration | All tunable parameters with valid ranges | Versioned alongside strategy; diff-auditable |
| Backtest results | PnL curves, trade logs, integrity checks | Keyed to strategy version + data version + engine version |
| Model weights (if any) | Trained model artifacts | Versioned with training data hash and hyperparameters |
| Dependency manifest | Library versions, system requirements | Lockfile committed with strategy |

```
artifact_id = hash(strategy_version, config_version, data_version, engine_version)
```

No two deployments share an artifact ID unless they are truly identical.
Artifact IDs are immutable — if anything changes, a new ID is generated.

### Backtest Reproducibility Logs

Every backtest run produces a reproducibility record.

| Field | Purpose |
|-------|---------|
| `run_id` | Deterministic hash of all inputs |
| `strategy_version` | Git SHA of strategy code |
| `engine_version` | Git SHA of backtest engine |
| `data_version` | Hash of input data files |
| `config_snapshot` | Full parameter dump (JSON) |
| `environment` | OS, Python version, library versions |
| `random_seeds` | All seeds used for stochastic components |
| `output_hash` | Hash of PnL curve + trade log + position series |
| `integrity_checks` | Pass/fail for each automated validation |
| `timestamp` | When the run was executed |

To reproduce: check out `strategy_version` and `engine_version`, load
`data_version`, apply `config_snapshot`, set `random_seeds`, run. Output
must match `output_hash`.

### Configuration Audit Trail

Every configuration change is tracked with full provenance.

| Field | Description |
|-------|-------------|
| `change_id` | Unique identifier |
| `timestamp` | When the change was made |
| `author` | Who made the change |
| `parameter_path` | Dot-notation path to changed parameter |
| `old_value` | Previous value |
| `new_value` | New value |
| `justification` | Why the change was made |
| `associated_artifact` | Strategy version this applies to |
| `rollback_id` | ID of the change this would revert to (if applicable) |

Configuration changes in production require:
1. Entry in the audit trail before the change takes effect
2. Associated backtest showing impact of the new value
3. Approval from a second party (not the author)
4. Automated validation that new config is within defined valid ranges

Unauthorized or unlogged configuration changes are treated as security
incidents and trigger immediate trading halt.

---

## CI/CD Integration

### Pipeline Stages

```
commit → lint → unit tests → property tests → replay determinism → fault injection → acceptance gate
```

| Stage | Timeout | Failure Action |
|-------|---------|----------------|
| Lint & type check | 2 min | Block merge |
| Unit tests | 10 min | Block merge |
| Property-based tests | 30 min | Block merge |
| Replay determinism | 15 min | Block merge |
| Fault injection suite | 45 min | Block merge; alert on infrastructure failures |
| Cost/latency sensitivity | 60 min | Block promotion (not merge) |
| Full acceptance gate | 2 hr | Block promotion to next pipeline stage |

Nightly runs execute the full acceptance suite against HEAD. Weekly runs
include cross-machine reproducibility and extended property-based testing
(10,000+ examples per property).

### Test Data Management

| Concern | Approach |
|---------|----------|
| Deterministic fixtures | Versioned test data committed or referenced by hash |
| Synthetic generators | Seeded generators for property-based and fault injection tests |
| Historical snapshots | Pinned market data segments for regression tests |
| Data isolation | Tests never share mutable state; each test gets a fresh environment |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Backtest Engine (backtest-engine skill) | Replay determinism, fill model validation, integrity checks |
| Live Execution (live-execution skill) | Sim-vs-live divergence metrics, execution quality monitoring |
| Risk Engine (risk-engine skill) | Constraint enforcement tests, drawdown gate validation, regime transition testing |
| Data Engineering (data-engineering skill) | Data corruption simulation, gap injection, schema validation tests |
| System Architect (system-architect skill) | Layer isolation tests, event bus contract tests, clock abstraction verification |
| Performance Engineering (performance-engineering skill) | Latency budget tests, throughput regression tests |

The testing framework validates every other layer but does not contain
business logic itself. It is the gatekeeper — independent, comprehensive,
and unyielding.
