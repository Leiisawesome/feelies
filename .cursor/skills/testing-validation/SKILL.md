---
name: testing-validation
description: >
  Testing and validation framework for system integrity across the
  feelies platform. Owns the five locked parity-hash baselines (sensor,
  signal, sized-intent, portfolio-order, hazard-exit), the F-2
  declarative gate matrix that powers the promotion-evidence workflow,
  the F-1 promotion ledger contract, the per-host pinned perf
  baselines, and the strict-mypy / DTZ scope locks. Use when designing
  tests, defining or extending acceptance gates, debugging
  determinism failures, or reasoning about promotion / quarantine /
  capital-tier escalation evidence.
---

# Testing & Validation Director

Responsible for system integrity end-to-end. No strategy, component,
or configuration change reaches production without passing a
deterministic, reproducible validation pipeline. The default posture
is **deny deployment** — evidence of correctness must be affirmatively
produced, not assumed.

This skill owns the five locked parity hashes, the gate-matrix
contract, the promotion-ledger schema, and the strict-typing /
DTZ-rule scope locks.

## Core Invariants

Inherits Inv-3 (evidence over intuition → gated promotion), Inv-5
(deterministic replay → reproducibility), Inv-13 (provenance →
auditable configuration). Additionally:

1. **Tests are first-class code** — test infrastructure receives the
   same design rigor as production code.
2. **Failure injection is mandatory** — components that have not been
   tested under failure are assumed to fail in production.
3. **Regression is unacceptable** — passing tests never regress; new
   failures block the pipeline.
4. **Parity-hash baselines are immutable** — any change to a locked
   parity hash requires a documented architectural review, not a
   one-line update.

---

## Five Locked Parity Hashes (Inv-5)

Each is a SHA-256 over the ordered event stream at one layer,
asserted by a subprocess-isolated test under `tests/determinism/` to
detect any non-determinism introduced by ordering, RNG, or
wall-clock leakage.

| Level | Stream | Test |
|-------|--------|------|
| L1 | `SensorReading` | `test_sensor_replay.py` |
| L2 | SIGNAL-layer `Signal` | `test_signal_replay.py` |
| L3 | `SizedPositionIntent` | `test_sized_intent_replay.py` |
| L3-orders | per-leg `OrderRequest` from PORTFOLIO | `test_portfolio_order_replay.py` |
| L4 | hazard-exit `OrderRequest` | `test_hazard_exit_replay.py` |
| L5 | `RegimeHazardSpike` | `test_hazard_parity.py` |

Determinism is structurally supported by:

- `SimulatedClock.set_time()` rejecting backward movement
- SHA-256 order IDs (`hashlib.sha256(f"{correlation_id}:{seq}")`) — never `uuid4`
- `SequenceGenerator` (`core/identifiers.py`) thread-safe monotonic counter
- Frozen `StateMachine` transition tables; `TransitionRecord` audit trail
- `ruff` `DTZ` rules banning raw `datetime.now()` (Inv-10)
- `mypy --strict` on every module under `src/feelies/`

**Strict-mode scope lock**: `tests/acceptance/test_mypy_strict_scope.py`
runs `mypy --no-incremental src/feelies` and asserts a zero exit
code, **and** parses `pyproject.toml` to assert no
`[[tool.mypy.overrides]]` block sets `ignore_errors = true` on any
`feelies.*` module. A contributor cannot silence a strict-mode
failure by re-introducing an override.

---

## Test Architecture

### Unit Tests

Every component tested in isolation with mock event streams. Tests are
deterministic — no wall-clock dependencies, no network calls, no
randomness without fixed seeds.

| Layer | Test focus | Key assertions |
|-------|-----------|----------------|
| Ingestion | Schema validation, dedup, gap detection | Malformed rejected; duplicates eliminated; gaps surfaced |
| Sensors | Per-symbol incremental correctness | Match hand-computed values; reset cleanly |
| Horizon aggregator | Boundary detection + snapshot fan-in | Boundary index integer math; warm/stale flags correct |
| Signal layer | Pure-function behavior + regime gate purity | Same `(snapshot, regime, params)` → same `Signal` |
| Composition | Cross-sectional ranking + factor neut | Mechanism-cap enforcement; deterministic emission order |
| Risk engine | Constraint enforcement, regime transitions | Limits enforced; per-leg veto; fail-safe on unknown state |
| Execution | Order lifecycle, SM transitions | No invalid transitions; idempotency honored |
| Alpha lifecycle | Promotion / demotion / capital-tier | Gate matrix dispatch; ledger writes; F-5 threshold merge |

Coverage requirements:

- Branch coverage > 90% for risk engine + execution + alpha lifecycle
- Line coverage > 80% on all `src/feelies/` modules
- All edge cases documented in test names (not just happy paths)

### Property-Based Tests

Invariants that must hold for all valid inputs. Use Hypothesis
generators to explore the input space.

#### State-Machine Targets

The five state machines are primary property-based test targets. Each
uses the generic `StateMachine[S]` framework with `IllegalTransition`
and construction-time enum-completeness check.

| SM | File | Key properties |
|----|------|----------------|
| `MacroState` | `kernel/macro.py` | SHUTDOWN terminal; only TRADING_MODES drive the tick pipeline |
| `MicroState` | `kernel/micro.py` | M0 → M10 backbone with Phase-2/3/4 sub-states; no skipping |
| `OrderState` | `execution/order_state.py` | FILLED/CANCELLED/REJECTED/EXPIRED terminal |
| `RiskLevel` | `risk/escalation.py` | Monotonic forward-only; only R4 → R0 via human unlock |
| `DataHealth` | `ingestion/data_integrity.py` | CORRUPTED → RECOVERING required; no direct CORRUPTED → HEALTHY |

#### Core Invariants

| Invariant | Generator | Property |
|-----------|-----------|----------|
| Causal ordering | Random event streams with shuffled timestamps | Sensors / signals never depend on future events |
| Deterministic replay | Same event log + config, two runs | All five parity hashes bit-identical |
| Position conservation | Random fill sequences | Σ fills = final position; no phantoms |
| Risk monotonic safety | Random `RiskLevel` transitions | Safety never decreases without explicit re-auth |
| PnL decomposition | Random trade sequences | alpha + beta + costs = total (FP tolerance) |
| Clock monotonicity | Arbitrary `SimulatedClock.set_time()` | Backward attempts raise `ValueError` |
| Idempotent submission | Duplicate signal sequences | SHA-256 IDs prevent duplicates |
| State-machine validity | Random transitions on all 5 SMs | `IllegalTransition` on forbidden; terminal sets empty |
| Enum completeness | Construct SM with missing entries | `ValueError` at construction |
| Gate-matrix completeness | Add new `GateId` without wiring | Hard import failure (`_check_matrix_completeness`) |
| Validator coverage | Add new evidence type without registering validator + metadata kind | Hard import failure (`_check_validator_coverage`) |

Run property-based tests with at least 1000 examples per property.
Failures are shrunk to minimal reproducible cases and persisted as
regression tests.

### Replay Reproducibility

Determinism tests run on every code change touching replay logic, fill
models, sensor / aggregator / signal / composition implementations,
or hazard-exit logic.

| Test | Method | Pass criteria |
|------|--------|---------------|
| Same-machine determinism | Run identical config twice on same machine | Bit-identical event stream + all five parity hashes |
| Cross-machine determinism | Run identical config on two different machines | Bit-identical (requires fixed seeds, no hardware-dependent floats) |
| Version-upgrade determinism | Run same config on old + new code | Identical, or documented + justified divergence |
| Checkpoint resume | Interrupt replay; resume from `SensorStateStore` checkpoint | Final output identical to uninterrupted run |
| Hazard-parity | Replay `RegimeHazardSpike` stream | L5 hash bit-identical |
| Decay-on / decay-off cross-check | Same alpha with `decay_weighting_enabled` toggled | `SizedPositionIntent.decision_basis_hash` differs; structural ranking unchanged |

### Sim-vs-Live Divergence

Detect structural drift between backtest assumptions and live behavior.
These metrics drive the **paper-window evidence** schema in the F-2
gate matrix (see Alpha Lifecycle below).

| Metric | Comparison | Alert | Blocking |
|--------|-----------|-------|----------|
| Fill rate | Predicted vs realized | > 10% relative | > 20% relative |
| Slippage distribution | Model vs live | KS p < 0.10 | KS p < 0.01 |
| Latency profile | Injected vs measured | KS p < 0.10 | KS p < 0.01 |
| PnL compression | Live / backtest (same period) | < 0.6 or > 1.2 | < 0.4 or > 1.5 |
| Signal-to-fill timing | Backtest assumed vs live measured | > 2× mean diff | > 3× mean diff |
| Order rejection rate | Backtest (≈ 0) vs live broker rejects | > 3% submissions | > 8% submissions |

---

## Fault Injection Framework

### Failure Modes

| Fault | Target | Expected behavior |
|-------|--------|-------------------|
| Null / malformed event | Ingestion | Reject + log; no propagation |
| Out-of-order timestamps | Bus | Detect, reorder or flag; never silent |
| NaN / Inf sensor value | Sensor layer | Suppress emission; alert; flag `provenance.valid = False` |
| Stale quotes (frozen NBBO) | Risk engine | Heartbeat detect; block new orders after threshold |
| Concurrent state mutation | Execution | Lock or CAS prevents corruption |
| Disk full during write | Storage | Fail loudly; no partial writes |

### Data Corruption

| Corruption | Injection | Validation |
|-----------|-----------|------------|
| Price spikes | × 10 / × 0.1 | Outlier filter catches |
| Negative spreads | bid > ask | Detected as invalid; dropped with alert |
| Zero sizes | bid_size or ask_size = 0 | Handled as no-liquidity |
| Duplicate timestamps | Replay same event twice | Dedup catches |
| Schema violations | Remove required fields | Schema validator rejects |
| Encoding errors | Invalid UTF-8 | Deserialization fails safely |

### Latency / Disconnect

| Scenario | Injection | Expected response |
|----------|-----------|-------------------|
| Network spike | +500 ms – 2 s gateway delay | Order timeout; retry; circuit-breaker eval |
| Feature bottleneck | Throttle sensor compute | Stale-snapshot detection fires |
| Feed delay | Delay 1–5 s | Stale-data detection; block orders |
| Burst latency | Intermittent 100 ms (10% events) | Latency histogram shifts; alert if sustained |
| Clock skew | ±50 ms drift | Reconciliation detects; conservative timestamp |
| Full disconnect | Drop all data 30 s | Gap detection; block orders; reconnect with gap-fill |
| Partial disconnect | Drop subset of symbols | Per-symbol staleness; affected symbols frozen |

All fault-injection tests run in CI.

---

## Acceptance Gates & Gate Matrix (F-2)

The platform owns a **declarative gate matrix** that wires each
`GateId` to the tuple of evidence dataclasses the gate requires. The
matrix is `GATE_EVIDENCE_REQUIREMENTS` in `alpha/promotion_evidence.py`.

```python
class GateId(Enum):
    RESEARCH_TO_PAPER          # PAPER promotion gate
    PAPER_TO_LIVE              # LIVE promotion gate (with SMALL_CAPITAL)
    LIVE_PROMOTE_CAPITAL_TIER  # F-6 LIVE @ SMALL_CAPITAL → LIVE @ SCALED
    LIVE_TO_QUARANTINED        # forensic-triggered demotion (consistency-only)
    QUARANTINED_TO_PAPER       # revalidation
    QUARANTINED_TO_DECOMMISSIONED
```

### Evidence Schemas (F-2)

| Schema | Gate(s) | Carries |
|--------|---------|---------|
| `ResearchAcceptanceEvidence` | RESEARCH_TO_PAPER | acceptance-suite outcomes |
| `CPCVEvidence` | RESEARCH_TO_PAPER | fold count, embargo bars, fold sharpes, mean / median sharpe, mean PnL, p-value, content-addressable `fold_pnl_curves_hash` |
| `DSREvidence` | RESEARCH_TO_PAPER | observed sharpe, trials count, skew, kurtosis, deflated `dsr` + `dsr_p_value` |
| `PaperWindowEvidence` | PAPER_TO_LIVE | trading days, sample size, slippage residual bps, fill-rate drift pct (two-sided), latency KS p, PnL compression ratio, anomalous event count |
| `CapitalStageEvidence` | LIVE_PROMOTE_CAPITAL_TIER | tier (`SMALL_CAPITAL`), deployment days, PnL compression band, exec-quality envelopes |
| `QuarantineTriggerEvidence` | LIVE_TO_QUARANTINED | net-alpha negative days, hit-rate residual pp, microstructure metrics breached, crowding symptoms, PnL compression 5d |
| `RevalidationEvidence` | QUARANTINED_TO_PAPER | hypothesis re-derived, OOS walk-forward sharpe, parameter drift resolved, human signoff, revalidation notes |

### Default `GateThresholds`

| Field | Default | Rationale |
|-------|---------|-----------|
| `cpcv_min_folds` | 8 | Combinatorial purged CV minimum |
| `cpcv_min_mean_sharpe` | 1.0 | Pre-deployment statistical significance |
| `cpcv_max_p_value` | 0.05 | Standard significance |
| `dsr_min` | 1.0 | Bailey-López de Prado deflated sharpe ≥ 1 |
| `revalidation_min_oos_sharpe` | 1.0 | Non-degenerate post-quarantine performance |
| `small_min_deployment_days` | 10 | Capital-tier escalation gate |

Defaults can be overridden via the F-5 three-layer merge: skill-pinned
defaults ≺ `platform.yaml: gate_thresholds:` ≺ per-alpha
`promotion: { gate_thresholds: ... }` in the alpha YAML. Merge is
non-mutating (`dataclasses.replace`) and runs once at registration time
so an alpha's effective thresholds are immutable for its lifetime —
replay determinism is preserved (audit `A-DET-02`).

### Construction-Time Invariants

`alpha/promotion_evidence.py` enforces:

- `_check_matrix_completeness` — every `GateId` member has an entry
- `_check_validator_coverage` — every required type has both a
  registered validator AND a metadata `kind` string
- `_check_reconstructor_coverage` — every metadata kind has a
  registered reconstructor (round-trippable through
  `evidence_to_metadata` / `metadata_to_evidence`)

A contributor adding a new gate or evidence type without wiring all
three triggers a hard **import failure** — the platform refuses to
boot.

---

## Promotion Pipeline (`AlphaLifecycle`)

The 5-state lifecycle (`alpha/lifecycle.py`):

```
RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
                  (LIVE @ SMALL_CAPITAL → LIVE @ SCALED via F-6 self-loop)
```

| Stage | Capital | Duration | Exit gate |
|-------|---------|----------|-----------|
| RESEARCH | $0 | Until acceptance gates pass | RESEARCH_TO_PAPER (CPCV + DSR + research-acceptance) |
| PAPER | $0 (live data, simulated execution) | ≥ 5 trading days | PAPER_TO_LIVE (paper-window) |
| LIVE @ SMALL_CAPITAL | ≤ 1% target allocation | ≥ 10 trading days | LIVE_PROMOTE_CAPITAL_TIER (capital-stage) |
| LIVE @ SCALED | Target allocation | Ongoing | Demotion via QUARANTINE_TRIGGER |
| QUARANTINED | $0 (paper-mode only) | Until revalidation | QUARANTINED_TO_PAPER (revalidation) |
| DECOMMISSIONED | terminal | — | — |

### Two Paths

`AlphaLifecycle.promote_to_paper / promote_to_live / revalidate_to_paper`
accept **either**:

1. **Legacy positional** `PromotionEvidence` (validated via
   `check_*_gate` against `GateRequirements`) — persists `{"evidence":
   {...}}` to the ledger
2. **Keyword-only `structured_evidence: Sequence[object]`** (validated
   via `validate_gate(GateId, evidences, gate_thresholds)`) — persists
   F-2 `evidence_to_metadata(*evs)` payload

Supplying both or neither raises `ValueError`. The structured path is
the modern surface; legacy is preserved for backwards compatibility.

### Quarantine Path (Inv-11 Fail-Safe)

`AlphaLifecycle.quarantine` is fail-safe: any
`validate_gate(QUARANTINED, ...)` errors are logged at WARNING level
(spurious-trigger flag) but the demotion **always commits** so a
forensic-layer auto-trigger can never be blocked by the validator.

### Capital-Tier Escalation (F-6)

`AlphaLifecycle.promote_capital_tier(evidence)` is wired as a
`LIVE → LIVE` state-machine self-loop. The lifecycle state name does
not change but the F-1 ledger receives a metadata-only entry with
`trigger == PROMOTE_CAPITAL_TIER_TRIGGER ("promote_capital_tier")` —
distinguishable from the LIVE → QUARANTINED demotion (both share
`from_state == "LIVE"`).

`AlphaLifecycle.current_capital_tier` scans `history` backwards from
the most recent record to the most recent transition into LIVE,
returning `SCALED` if any `promote_capital_tier` self-loop is present
in that epoch and `SMALL_CAPITAL` otherwise. Quarantine + revalidate
+ re-promote starts a new LIVE epoch that resets to `SMALL_CAPITAL` —
operators must re-justify SCALED per epoch.

---

## Promotion Ledger (F-1)

`alpha/promotion_ledger.py` provides an append-only JSONL audit log
that records every committed transition with full evidence,
`trigger`, clock-derived `timestamp_ns`, and `correlation_id`. Wired
into `AlphaLifecycle` via a `StateMachine.on_transition` callback so
a ledger-write failure rolls the SM back atomically (Inv-13 + Inv-11).

The ledger is constructed from `PlatformConfig.promotion_ledger_path`.
**Forensic-only consumer contract**: production code paths must
never read the ledger to make per-tick decisions, so ledger presence
does not perturb replay determinism.

`LEDGER_SCHEMA_VERSION` is asserted on every read.

### Operator CLI (F-3)

`feelies promote …` (entry point in `cli/promote.py`):

| Subcommand | Purpose |
|------------|---------|
| `inspect <alpha_id>` | Per-alpha chronological timeline (text or `--json`) |
| `list` | Every alpha + current state + transition count |
| `replay-evidence <alpha_id>` | Re-run `validate_gate` against every F-2-shaped evidence package recorded for the alpha against today's `GateThresholds` (legacy reason-only metadata reported as SKIPPED) |
| `validate` | Preflight ledger file (parse + `LEDGER_SCHEMA_VERSION` check) |
| `gate-matrix` | Render the F-2 declarative gate matrix |

All accept `--ledger PATH` or `--config PATH` and `--json`.

Exit codes (CI-stable):
- `0` OK
- `1` user error (missing args / non-existent file / config without `promotion_ledger_path`)
- `2` data error (corrupt ledger / schema-version mismatch)
- `3` validation failure (`replay-evidence` found gate violations)

The CLI is **read-only and forensic-only** — never writes to the
ledger, never imports orchestrator / risk-engine production code
(audit `A-DET-02`).

### Demotion Triggers

| Trigger | Response |
|---------|----------|
| PnL compression < 0.4 for 3 consecutive days | Demote to PAPER; recalibrate |
| Kill-switch activation | Demote to RESEARCH; root-cause analysis |
| Divergence metric exceeds blocking threshold | Demote one stage; investigate |
| Reproducibility failure | Halt all stages; fix before any resumption |
| Undocumented config change in production | Immediate halt; audit-trail investigation |

---

## Artifact Management

### Versioned Strategy Artifacts

| Artifact | Contents | Versioning |
|----------|----------|------------|
| Strategy bundle | `*.alpha.yaml`, signal logic, sensor declarations, risk params | semver + git SHA |
| Configuration | All tunable parameters | versioned alongside; diff-auditable |
| Backtest results | All five parity hashes; trade logs; integrity checks | keyed to `(strategy_version, data_version, engine_version)` |
| Reference factor loadings | Parquet / built artifacts | content-addressed hash; max-age guard |
| Dependency manifest | Library versions | lockfile committed |

```
artifact_id = hash(strategy_version, config_version, data_version, engine_version)
```

### Backtest Reproducibility Logs

Every run produces a record with `run_id` (deterministic hash),
`strategy_version`, `engine_version`, `data_version`,
`config_snapshot` (JSON), environment, random seeds, **all five
parity hashes**, integrity-check pass/fail, timestamp.

To reproduce: check out `strategy_version` + `engine_version`, load
`data_version`, apply `config_snapshot`, set seeds, run. All five
parity hashes must match.

### Configuration Audit Trail

Every config change is tracked with `change_id`, `timestamp`,
`author`, `parameter_path`, `old_value`, `new_value`, `justification`,
`associated_artifact`, `rollback_id`.

Config changes in production require: ledger entry before effect,
associated backtest, second-party approval, automated range
validation. Unlogged changes are security incidents — immediate
trading halt.

---

## Performance Regression Gate

| Gate | Threshold | File |
|------|-----------|------|
| Phase 4 throughput regression | ≤ 12% e2e vs v0.2 baseline | `tests/perf/test_phase4_no_regression.py` |
| Phase 4.1 decay-weighting overhead | ≤ 5% wall-clock vs decay-OFF | `tests/perf/test_phase4_1_no_regression.py` |
| Per-host pinned baselines | opt-in via `PERF_HOST_LABEL` | `tests/perf/baselines/v02_baseline.json` |
| Baseline recording | manual | `python scripts/record_perf_baseline.py --host-label <id>` |

---

## Acceptance Sweep

`tests/acceptance/` contains mechanical assertions for the v0.2 +
v0.3 acceptance matrix
([`docs/acceptance/v02_v03_matrix.md`](../../docs/acceptance/v02_v03_matrix.md)),
including:

- mypy-strict scope lock (`test_mypy_strict_scope.py`)
- Reference-alpha load invariants (`margin_ratio`, factor exposures)
- G16 rule completeness
- Decay-divergence (decay-ON vs decay-OFF)
- Strict-mode loading per mechanism family
- Perf-baseline plumbing

---

## CI/CD Pipeline

```
commit → lint (ruff + DTZ) → mypy strict → unit → property → replay
       → fault injection → cost / latency sensitivity → acceptance gate
```

| Stage | Timeout | Failure |
|-------|---------|---------|
| Lint + DTZ + mypy | 2 min | Block merge |
| Unit | 10 min | Block merge |
| Property | 30 min | Block merge |
| Replay determinism (5 parity hashes) | 15 min | Block merge |
| Fault injection | 45 min | Block merge |
| Cost / latency sensitivity | 60 min | Block promotion |
| Full acceptance + perf gate | 2 hr | Block promotion |

Nightly runs execute the full acceptance suite against HEAD. Weekly
runs include cross-machine reproducibility and extended
property-based testing (10 000+ examples).

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Backtest Engine | `SimulatedClock` + `MarketDataSource`; `OrderRouter` for fill-model validation |
| Live Execution | Sim-vs-live divergence metrics; `OrderAckStatus` exhaustiveness verification |
| Risk Engine | `RiskLevel` SM monotonicity; `RiskAction` exhaustiveness; per-leg veto property tests |
| Data Engineering | `DataHealth` SM transitions; `NBBOQuote` / `Trade` schema validation; gap injection |
| System Architect | `StateMachine` framework; `TransitionRecord`; `EventBus` contract tests; `Clock` abstraction |
| Performance Engineering | `MetricEvent` latency budget; throughput regression tests |
| Alpha Lifecycle | Gate-matrix dispatcher; promotion-ledger contract |
| Composition Layer | L3 + L3-orders + decay-on/off cross-check parity tests |
| Sensor / Aggregator | L1 sensor parity + warm-up + staleness invariants |

The testing framework validates every other layer but contains no
business logic itself. It is the gatekeeper — independent,
comprehensive, unyielding.
