---
name: testing-validation
description: >
  Parity hashes (L1–L6), acceptance gates, strict mypy. Use for determinism failures and promotion bars.
---

# Testing & Validation Director

Responsible for system integrity end-to-end. No strategy, component,
or configuration change reaches production without passing a
deterministic, reproducible validation pipeline. The default posture
is **deny deployment** — evidence of correctness must be affirmatively
produced, not assumed.

This skill owns the locked parity hashes (the canonical registry — and
source of truth for the current count, which grows over time — is
`tests/determinism/parity_manifest.py:LOCKED_PARITY_BASELINES`), the
gate-matrix **acceptance criteria**, the promotion-ledger schema
references, and the strict-typing / DTZ-rule scope locks. Promotion
wiring detail lives in the [alpha-lifecycle skill](../alpha-lifecycle/SKILL.md).

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

## Locked Parity Hashes (Inv-5)

Each is a SHA-256 over the ordered event stream at one layer, asserted
by an in-process pytest replay test under `tests/determinism/`. The canonical
registry is `tests/determinism/parity_manifest.py:LOCKED_PARITY_BASELINES`
— check `len(LOCKED_PARITY_BASELINES)` for the current count rather than
trusting a number here, since new baselines are added over time (plus a
handful of intentionally-unregistered ones — cvxpy-conditional and
orchestrator-level — tracked in `test_parity_manifest.py`'s
`_UNREGISTERED_HASH_EXEMPTIONS`). Drift between modules is caught in
CI by `tests/determinism/test_parity_manifest.py`.

| Level | Stream | Test |
|-------|--------|------|
| L1 | `SensorReading` (v0.2 fixture) | `test_sensor_reading_replay.py` |
| L1 (v0.3) | `SensorReading` (v0.3 fixture) | `test_v03_sensor_replay.py` |
| L2 | `HorizonTick` | `test_horizon_tick_replay.py` |
| L2 | SIGNAL-layer `Signal` | `test_signal_replay.py` |
| L3 | `HorizonFeatureSnapshot` | `test_horizon_feature_snapshot_replay.py` |
| L3 | `SizedPositionIntent` (decay OFF) | `test_sized_intent_replay.py` |
| L3 | `SizedPositionIntent` (decay ON) | `test_sized_intent_with_decay_replay.py` |
| L4 | per-leg `OrderRequest` from PORTFOLIO | `test_portfolio_order_replay.py` |
| L4 | hazard-exit `OrderRequest` | `test_hazard_exit_replay.py` |
| L5 | `RegimeHazardSpike` | `test_regime_hazard_replay.py` |
| L6 | `RegimeState` | `test_regime_state_replay.py` |
| — | Aggressive-fill economics (`market_fill_acks`) | `test_market_fill_replay.py` |
| — | `PositionUpdate` / PnL reconciliation (`position_pnl`) | `test_position_pnl_replay.py` |
| — | `StateTransition` multi-SM shared-sequence stream (`state_transition`) | `test_state_transition_replay.py` |
| — | `CrossSectionalContext` from a real `UniverseSynchronizer` (`cross_sectional_context`) | `test_cross_sectional_context_replay.py` |
| — | Non-empty SIGNAL `Signal` from a real `HorizonSignalEngine` (`signal_fires`) | `test_signal_fires_replay.py` |
| — | Cross-symbol `SensorReading` interleave (`multi_symbol_sensor_reading`) | `test_multi_symbol_sensor_replay.py` |

Two further determinism modules exist deliberately **outside** the manifest
(see each module's own docstring for why):

- `test_orchestrator_replay.py` — the only replay that instantiates the full
  `Orchestrator` (`build_platform` + `run_backtest`), locking the kernel's own
  `_seq` interleaving, micro-state walk, and bus-subscriber registration order
  that every leaf-driven baseline above is blind to. Its canonical fixture's
  Signal/Order/PositionUpdate streams are empty (no threshold crossed); a
  second, threshold-crossing fixture (seeded position + armed stop-loss)
  locks a non-empty variant of the same three streams.
- `test_hash_seed_independence.py` — re-runs the dict/set-iterating replays
  in subprocesses under several `PYTHONHASHSEED` values and asserts identical
  hashes, proving seed-independence directly rather than only pinning one
  seed value.

Added since the original eleven (level numbering doesn't map as cleanly for
these — see `parity_manifest.py` for the authoritative list):

| Baseline (manifest key) | Stream | Test |
|-------|--------|------|
| `market_fill_acks` | `OrderAck` fill economics | `test_market_fill_replay.py` |
| `position_pnl` | `PositionUpdate` (PnL reconciliation) | `test_position_pnl_replay.py` |
| `state_transition` | `StateTransition` (all five SMs) | `test_state_transition_replay.py` |
| `cross_sectional_context` | `CrossSectionalContext` | `test_cross_sectional_context_replay.py` |
| `signal_fires` | non-empty `Signal` (synthetic probe alpha) | `test_signal_fires_replay.py` |
| `reference_alpha_signal_fires` | non-empty `Signal` (real reference alpha) | `test_reference_alpha_signal_fires_replay.py` |
| `multi_symbol_sensor_reading` | cross-symbol `SensorReading` interleave | `test_multi_symbol_sensor_replay.py` |
| `symbol_halted` / `halt_order` / `halt_ack` / `halt_position_update` | halt-gate fill suppression | `test_symbol_halted_replay.py` |
| `risk_verdict` | `RiskVerdict` | `test_risk_verdict_replay.py` |

Determinism is structurally supported by:

- `SimulatedClock.set_time()` rejecting backward movement
- SHA-256 order IDs (`derive_order_id(f"{correlation_id}:{seq}")` — first 16 hex chars of the SHA-256 digest) — never `uuid4`
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
| `DataHealth` | `ingestion/data_integrity.py` | Four states: HEALTHY ↔ {GAP_DETECTED (WS seq / disconnect), HALTED (LULD / regulatory halt)}; CORRUPTED is terminal |

#### Core Invariants

| Invariant | Generator | Property |
|-----------|-----------|----------|
| Causal ordering | Random event streams with shuffled timestamps | Sensors / signals never depend on future events |
| Deterministic replay | Same event log + config, two runs | All locked parity hashes bit-identical |
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
| Same-machine determinism | Run identical config twice on same machine | Bit-identical event stream + all locked parity hashes |
| Cross-machine determinism | Run identical config on two different machines | Bit-identical (requires fixed seeds, no hardware-dependent floats) |
| Version-upgrade determinism | Run same config on old + new code | Identical, or documented + justified divergence |
| Checkpoint resume | Interrupt replay; resume from checkpoint (design target — no sensor-state checkpoint store exists yet; only `RegimeEngine.checkpoint()`/`restore()` is implemented) | Final output identical to uninterrupted run |
| Hazard-spike parity | Replay `RegimeHazardSpike` stream (`test_regime_hazard_replay.py`) | L5 hash bit-identical |
| Decay-on / decay-off cross-check | Same alpha with `decay_weighting_enabled` toggled (`test_sized_intent_replay.py` vs `test_sized_intent_with_decay_replay.py`) | The locked L3 intent-stream parity hashes differ between the two modes; structural ranking unchanged |

### Regime-Stratified Research Validation

Research-stage regime stratification (partition horizon boundaries by
HMM dominant state × `spread_z_30d` strata; repeat IC/CPCV per
stratum; minimum per-stratum sample rule) is a **manual procedure, not
a shipped harness** — the canonical procedure lives in the
microstructure-alpha skill's
[research-protocol.md](../microstructure-alpha/research-protocol.md)
(Phase 3, test 3). This skill owns only the acceptance posture: the
≥ 2 vol × ≥ 2 spread stability requirement (research-workflow skill)
is evaluated on those per-stratum results.

Research-stage validation-protocol bars (per-candidate freeze
documents) must carry the magnitude-vs-power label and matching
consequence class at freeze — see research-protocol.md, Validation
Protocol & Slate Design Discipline (backlog 12; incident: H8 step-2b
|RankIC| magnitude bar REJECTED vs safeguard PARK). Promotion
acceptance bars inherit the same pairing when translated from a
frozen protocol.

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

## Promotion & Gate Matrix (F-1..F-6)

**Canonical contract:** [alpha-lifecycle skill](../alpha-lifecycle/SKILL.md) —
5-state SM, F-2 evidence schemas, F-5 threshold merge, F-1 ledger, F-3
`feelies promote` CLI, F-6 capital-tier escalation.

This skill owns **what must pass before deployment** (acceptance criteria,
sim-vs-live divergence, parity hashes). The alpha-lifecycle skill owns
**how promotion is wired** (APIs, ledger schema, operator CLI).

Construction-time gate-matrix invariants (`_check_matrix_completeness`,
`_check_validator_coverage`, `_check_reconstructor_coverage`) are enforced
at import in `alpha/promotion_evidence.py` — a missing validator blocks
platform boot.

### Testing-specific promotion gates

| Stage | Minimum evidence (F-2) | Blocking thresholds (defaults) |
|-------|------------------------|--------------------------------|
| RESEARCH → PAPER | `ResearchAcceptanceEvidence` | Acceptance suite green |
| PAPER → LIVE | `PaperWindowEvidence`, `CPCVEvidence`, `DSREvidence` | CPCV mean sharpe ≥ 1.0, p ≤ 0.05; DSR ≥ 1.0; paper-window bands |
| LIVE → LIVE (tier) | `CapitalStageEvidence` | ≥ 10 deployment days; PnL compression [0.5, 1.0] |
| LIVE → QUARANTINED | `QuarantineTriggerEvidence` | Consistency-only; demotion always commits (Inv-11) |
| QUARANTINED → PAPER | `RevalidationEvidence` | OOS sharpe ≥ 1.0; non-empty `human_signoff` |

Sim-vs-live metrics that feed `PaperWindowEvidence` are defined in the
**Sim-vs-Live Divergence** section above. Forensic quarantine triggers
align with post-trade-forensics skill defaults.

### Policy demotion triggers (design targets)

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
| Backtest results | All locked parity hashes; trade logs; integrity checks | keyed to `(strategy_version, data_version, engine_version)` |
| Reference factor loadings | Parquet / built artifacts | content-addressed hash; max-age guard |
| Dependency manifest | Library versions | lockfile committed |

```
artifact_id = hash(strategy_version, config_version, data_version, engine_version)
```

### Backtest Reproducibility Logs

Every run produces a record with `run_id` (deterministic hash),
`strategy_version`, `engine_version`, `data_version`,
`config_snapshot` (JSON), environment, random seeds, **all locked
parity hashes**, integrity-check pass/fail, timestamp.

To reproduce: check out `strategy_version` + `engine_version`, load
`data_version`, apply `config_snapshot`, set seeds, run. All locked
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
| Paper-RTH throughput regression | ≤ 12% e2e vs v0.2 baseline | `tests/perf/test_paper_rth_no_regression.py` |
| Phase 4.1 decay-weighting overhead | ≤ 5% wall-clock vs decay-OFF | plumbing present (`tests/perf/_pinned_baseline.py` + `tests/acceptance/test_perf_baseline_plumbing.py`), but the asserting regression test (`test_phase4_1_no_regression.py`) has not landed — the threshold is **not yet enforced in CI** |
| Per-host pinned baselines | opt-in via `PERF_HOST_LABEL` | `tests/perf/baselines/v02_baseline.json` (loader: `tests/perf/_pinned_baseline.py`) |
| Baseline-plumbing smoke | acceptance | `tests/acceptance/test_perf_baseline_plumbing.py` |
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

**Not shipped:** target pipeline — stage timeouts and gates below describe the
intended merge/promotion bar; not every stage runs in CI today. What ships:
ruff + DTZ, mypy strict, unit/property/replay determinism, and acceptance
sweeps under `tests/acceptance/`. Fault-injection and full perf comparator
gates are aspirational (see Performance Regression Gate above).

```
commit → lint (ruff + DTZ) → mypy strict → unit → property → replay
       → fault injection → cost / latency sensitivity → acceptance gate
```

| Stage | Timeout | Failure |
|-------|---------|---------|
| Lint + DTZ + mypy | 2 min | Block merge |
| Unit | 10 min | Block merge |
| Property | 30 min | Block merge |
| Replay determinism (11 parity hashes) | 15 min | Block merge |
| Fault injection | 45 min | Block merge |
| Cost / latency sensitivity | 60 min | Block promotion |
| Full acceptance + perf gate | 2 hr | Block promotion |

Nightly runs execute the full acceptance suite against HEAD. Weekly
runs include cross-machine reproducibility and extended
property-based testing (10 000+ examples).

---

## Integration Points

See [skill index](../README.md). **Non-obvious edges:** canonical parity-hash table (L1–L6); acceptance criteria for promotion evidence.