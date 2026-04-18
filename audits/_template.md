# Audit YYYY-MM-DD — <commit-sha>

Protocol version: v1.0
Config checksum: <PlatformConfig.snapshot().checksum>
Artifact id: <hash(strategy_version, config_version, data_version, engine_version)>
Tests: passed=N failed=N skipped=N xfailed=N (vs prior: ±)
Demo backtest parity hash: <hash> (matches prior: yes/no)
Demo run twice — parity hashes: <hash1> | <hash2> (bit-identical: yes/no)
Stress 1.5x net PnL: <amount or bps>  Stress 2.0x net PnL: <amount or bps>
tick_to_decision_latency_ns p50/p95/p99: <p50> / <p95> / <p99>
Iteration verdict: PASS / FAIL  (per "Pass/Fail criteria")

## Pillar A — Structural

### A1. Layer separation & hidden state
- A-LAYER-01: PASS / FAIL <severity> — <evidence + file:line>
- A-LAYER-02: PASS / FAIL <severity> — <evidence>
- A-LAYER-03: PASS / FAIL <severity> — <evidence>

### A2. Event-bus & typed-schema discipline
- A-EVENT-01: PASS / FAIL <severity> — <evidence>
- A-EVENT-02: PASS / FAIL <severity> — <evidence>
- A-EVENT-03: PASS / FAIL <severity> — <evidence>

### A3. Clock abstraction
- A-CLOCK-01: PASS / FAIL <severity> — <evidence>
- A-CLOCK-02: PASS / FAIL <severity> — <evidence>

### A4. State-machine integrity
- A-SM-01: PASS / FAIL <severity> — <evidence>
- A-SM-02: PASS / FAIL <severity> — <evidence>
- A-SM-03: PASS / FAIL <severity> — <evidence>
- A-SM-04: PASS / FAIL <severity> — <evidence>
- A-SM-05: PASS / FAIL <severity> — <evidence>

### A5. Backtest/live parity surface
- A-PARITY-01: PASS / FAIL <severity> — <evidence>
- A-PARITY-02: PASS / FAIL <severity> — <evidence>
- A-PARITY-03: PASS / FAIL <severity> — <evidence>

### A6. Fail-safe defaults
- A-FAIL-01: PASS / FAIL <severity> — <evidence>
- A-FAIL-02: PASS / FAIL <severity> — <evidence>
- A-FAIL-03: PASS / FAIL <severity> — <evidence>
- A-FAIL-04: PASS / FAIL <severity> — <evidence>

### A7. Determinism & provenance
- A-DET-01: PASS / FAIL <severity> — <evidence>
- A-DET-02: PASS / FAIL <severity> — <evidence>
- A-DET-03: PASS / FAIL <severity> — <evidence>
- A-DET-04: PASS / FAIL <severity> — <evidence>

### A8. Performance measurement plumbing
- A-PERF-01: PASS / FAIL <severity> — <evidence>
- A-PERF-02: PASS / FAIL <severity> — <evidence>
- A-PERF-03: PASS / FAIL <severity> — <evidence>
- A-PERF-04: PASS / FAIL <severity> — <evidence>

### A8b. Performance budget enforcement
- A-PERFB-01: PASS / FAIL <severity> — <evidence (wall time vs prior)>
- A-PERFB-02: PASS / FAIL <severity> — <evidence (p99 vs 10ms ceiling)>
- A-PERFB-03: PASS / FAIL <severity> — <evidence (events/sec vs prior)>

### A9. Test-coverage spine
- A-TEST-01: PASS / FAIL <severity> — <evidence>
- A-TEST-02: PASS / FAIL <severity> — <evidence (per-invariant property test mapping)>
- A-TEST-03: PASS / FAIL <severity> — <evidence (pytest counts)>

### A10. Data ingestion fidelity
- A-DATA-01: PASS / FAIL <severity> — <evidence>
- A-DATA-02: PASS / FAIL <severity> — <evidence>
- A-DATA-03: PASS / FAIL <severity> — <evidence>
- A-DATA-04: PASS / FAIL <severity> — <evidence>
- A-DATA-05: PASS / FAIL <severity> — <evidence>
- A-DATA-06: PASS / FAIL <severity> — <evidence>

### A11. Regime engine integration
- A-REGIME-01: PASS / FAIL <severity> — <evidence>
- A-REGIME-02: PASS / FAIL <severity> — <evidence>
- A-REGIME-03: PASS / FAIL <severity> — <evidence>
- A-REGIME-04: PASS / FAIL <severity> — <evidence>
- A-REGIME-05: PASS / FAIL <severity> — <evidence>

### A12. Safety mechanisms triad
- A-SAFE-01: PASS / FAIL <severity> — <evidence>
- A-SAFE-02: PASS / FAIL <severity> — <evidence>
- A-SAFE-03: PASS / FAIL <severity> — <evidence>
- A-SAFE-04: PASS / FAIL <severity> — <evidence>
- A-SAFE-05: PASS / FAIL <severity> — <evidence>

### A13. Persistence durability
- A-PERSIST-01: PASS / FAIL <severity> — <evidence (in-memory backend inventory)>
- A-PERSIST-02: PASS / FAIL <severity> — <evidence>
- A-PERSIST-03: PASS / FAIL <severity> — <evidence>
- A-PERSIST-04: PASS / FAIL <severity> — <evidence>

### A14. Secrets & credentials handling
- A-SEC-01: PASS / FAIL <severity> — <evidence>

## Pillar B — Causal Chain

### B1. Mechanism-before-trade
- B-MECH-01: PASS / FAIL <severity> — <evidence>
- B-MECH-02: PASS / FAIL <severity> — <evidence>
- B-MECH-03: PASS / FAIL <severity> — <evidence>
- B-MECH-04: PASS / FAIL <severity> — <evidence>

### B2. Causality / no-lookahead
- B-CAUSAL-01: PASS / FAIL <severity> — <evidence>
- B-CAUSAL-02: PASS / FAIL <severity> — <evidence>
- B-CAUSAL-03: PASS / FAIL <severity> — <evidence>
- B-CAUSAL-04: PASS / FAIL <severity> — <evidence>

### B3. Two-phase risk gate
- B-RISK-01: PASS / FAIL <severity> — <evidence>
- B-RISK-02: PASS / FAIL <severity> — <evidence>
- B-RISK-03: PASS / FAIL <severity> — <evidence>
- B-RISK-04: PASS / FAIL <severity> — <evidence>

### B4. Position sizing & intent translation
- B-SIZE-01: PASS / FAIL <severity> — <evidence>
- B-SIZE-02: PASS / FAIL <severity> — <evidence>
- B-SIZE-03: PASS / FAIL <severity> — <evidence>
- B-SIZE-04: PASS / FAIL <severity> — <evidence>

### B5. Order-lifecycle & idempotency
- B-ORDER-01: PASS / FAIL <severity> — <evidence>
- B-ORDER-02: PASS / FAIL <severity> — <evidence>
- B-ORDER-03: PASS / FAIL <severity> — <evidence>
- B-ORDER-04: PASS / FAIL <severity> — <evidence>

### B6. Fill model realism
- B-FILL-01: PASS / FAIL <severity> — <evidence>
- B-FILL-02: PASS / FAIL <severity> — <evidence>
- B-FILL-03: PASS / FAIL <severity> — <evidence>
- B-FILL-04: PASS / FAIL <severity> — <evidence>

### B7. Position & PnL reconciliation
- B-PNL-01: PASS / FAIL <severity> — <evidence>
- B-PNL-02: PASS / FAIL <severity> — <evidence>
- B-PNL-03: PASS / FAIL <severity> — <evidence>
- B-PNL-04: PASS / FAIL <severity> — <evidence>

### B8. End-to-end live-practice replay
- B-E2E-01: PASS / FAIL <severity> — <evidence (parity hash, trades, PnL, DD, kill state)>
- B-E2E-02: PASS / FAIL <severity> — <evidence (twin parity hash match)>
- B-E2E-03: PASS / FAIL <severity> — <evidence (1.5x and 2.0x stress PnL)>
- B-E2E-04: PASS / FAIL <severity> — <evidence (e2e coverage gaps + stub list)>
- B-E2E-05: PASS / FAIL <severity> — <evidence (sim-vs-live divergence harness state)>

### B9. Provenance & audit trail
- B-PROV-01: PASS / FAIL <severity> — <evidence>
- B-PROV-02: PASS / FAIL <severity> — <evidence>
- B-PROV-03: PASS / FAIL <severity> — <evidence>
- B-PROV-04: PASS / FAIL <severity> — <evidence>

### B10. Personal-trading guardrails
- B-GUARD-01: PASS / FAIL <severity> — <evidence (stop-loss)>
- B-GUARD-02: PASS / FAIL <severity> — <evidence (trailing stop)>
- B-GUARD-03: PASS / FAIL <severity> — <evidence (entry cooldown)>
- B-GUARD-04: PASS / FAIL <severity> — <evidence (min order size)>
- B-GUARD-05: PASS / FAIL <severity> — <evidence (account_equity semantics)>
- B-GUARD-06: PASS / FAIL <severity> — <evidence (Decimal vs float boundary)>

### B11. Multi-alpha arbitration & attribution
- B-MULTI-01: PASS / FAIL <severity> — <evidence>
- B-MULTI-02: PASS / FAIL <severity> — <evidence>
- B-MULTI-03: PASS / FAIL <severity> — <evidence>
- B-MULTI-04: PASS / FAIL <severity> — <evidence>
- B-MULTI-05: PASS / FAIL <severity> — <evidence>

### B12. Promotion-gate readiness
- B-PROMO-01: YES / NO — <evidence (Research -> Paper criteria walk)>
- B-PROMO-02: YES / NO — <evidence (Paper -> Small Capital)>
- B-PROMO-03: YES / NO — <evidence (Small -> Scaled)>
- B-PROMO-04: PASS / FAIL <severity> — <evidence (artifact id stability)>

### B13. Decay-detection plumbing
- B-DECAY-01: PASS / FAIL <severity> — <evidence>
- B-DECAY-02: PASS / FAIL <severity> — <evidence>
- B-DECAY-03: PASS / FAIL <severity> — <evidence>
- B-DECAY-04: PASS / FAIL <severity> — <evidence>

## Promotion-gate readiness summary

- Research -> Paper: YES / NO  (blocking checks: ...)
- Paper -> Small Capital: YES / NO
- Small -> Scaled: YES / NO

## Deltas vs prior audit

- New BLOCKER: <list>
- Resolved: <list>
- New MAJOR: <list>
- Resolved MAJOR: <list>

## Risk register (permanent / known findings — re-listed every iteration)

- ...
- ...

## Meta (audit-of-the-audit)

- META-01: PASS / FAIL — <list invariant/skill changes since prior audit and the new check IDs added (or justification why none required)>

## Action queue (carried to next iteration)

- ...
