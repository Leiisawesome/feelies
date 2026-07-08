# feelies Agent Skills

Project-scoped skills under `.cursor/skills/`. Each directory has a
`SKILL.md` plus optional one-level-deep references, mirroring SENSOR →
SIGNAL → PORTFOLIO and cross-cutting concerns.

**Canonical references** (avoid duplicating these tables elsewhere):

| Topic | Canonical skill | Code anchor |
|-------|-----------------|-------------|
| Locked parity hashes (L1–L6) | [testing-validation](testing-validation/SKILL.md) | `tests/determinism/parity_manifest.py` |
| Promotion / gate matrix (F-1..F-6) | [alpha-lifecycle](alpha-lifecycle/SKILL.md) | `src/feelies/alpha/promotion_evidence.py` |
| Layer topology & state machines | [system-architect](system-architect/SKILL.md) | `src/feelies/kernel/` |

Always-applied platform rules live in `.cursor/rules/platform-invariants.mdc`.

---

## Skill index by layer

| Layer | Skill | Key packages | Use when |
|-------|-------|--------------|----------|
| Foundation | [system-architect](system-architect/SKILL.md) | `kernel/`, `core/`, `bootstrap.py` | Layer boundaries, SMs, events, gates G1–G16 |
| Layer 1 | [feature-engine](feature-engine/SKILL.md) | `sensors/`, `features/aggregator.py` | Sensors, warm/stale, `HorizonFeatureSnapshot` |
| Layer 2 | [microstructure-alpha](microstructure-alpha/SKILL.md) | `signals/`, `alphas/*.alpha.yaml` | SIGNAL alphas, G16, regime gates, cost arithmetic |
| Layer 2 (service) | [regime-detection](regime-detection/SKILL.md) | `services/regime_engine.py`, `services/regime_hazard_detector.py` | `RegimeState`, hazard spikes |
| Layer 3 | [composition-layer](composition-layer/SKILL.md) | `composition/` | PORTFOLIO alphas, `SizedPositionIntent` |
| Risk | [risk-engine](risk-engine/SKILL.md) | `risk/` | `check_signal` / `check_sized_intent`, hazard exits |
| Execution (sim) | [backtest-engine](backtest-engine/SKILL.md) | `execution/backtest_router.py`, `harness/` | Replay, fills, `feelies backtest` |
| Execution (live) | [live-execution](live-execution/SKILL.md) | `execution/`, `broker/ib/` | Orders, reconciliation, kill switch |
| Data | [data-engineering](data-engineering/SKILL.md) | `ingestion/`, `storage/` | Massive ingest, `EventLog`, `DataHealth` |
| Lifecycle | [alpha-lifecycle](alpha-lifecycle/SKILL.md) | `alpha/lifecycle.py`, `cli/promote.py` | Promotion, quarantine, `feelies promote` |
| Forensics | [post-trade-forensics](post-trade-forensics/SKILL.md) | `forensics/` | Decay, quarantine evidence |
| Research | [research-workflow](research-workflow/SKILL.md) | `research/` | Notebook → alpha handoff |
| Quality | [testing-validation](testing-validation/SKILL.md) | `tests/determinism/`, `tests/acceptance/` | Parity hashes, acceptance gates |
| Performance | [performance-engineering](performance-engineering/SKILL.md) | `tests/perf/` | Latency budgets, perf baselines |

---

## Supplementary reference files

Read these only when the main skill points you here — they are one level
deep from `SKILL.md`.

| Parent skill | File | Contents |
|--------------|------|----------|
| microstructure-alpha | [research-protocol.md](microstructure-alpha/research-protocol.md) | Hypothesis framework, feature taxonomy, reformalization gate, validation procedures |
| microstructure-alpha | [proposal-template.md](microstructure-alpha/proposal-template.md) | Deliverable template every SIGNAL proposal instantiates |
| microstructure-alpha | [system-architecture.md](microstructure-alpha/system-architecture.md) | Layer-2 deltas only (links to system-architect for pipeline) |
| backtest-engine | [fill-model.md](backtest-engine/fill-model.md) | Fill tiers, slippage calibration (partially implemented) |
| backtest-engine | [stress-testing.md](backtest-engine/stress-testing.md) | Perturbation protocols (mostly design targets) |
| live-execution | [order-lifecycle.md](live-execution/order-lifecycle.md) | `OrderState` SM detail |
| live-execution | [safety-controls.md](live-execution/safety-controls.md) | Kill switch, circuit breaker mapping |

---

## Common task routing

| Task | Start here |
|------|------------|
| Author a SIGNAL alpha | microstructure-alpha → feature-engine (sensors) |
| Author a PORTFOLIO alpha | composition-layer → microstructure-alpha (upstream signals) |
| Debug determinism failure | testing-validation → layer-specific skill from failing test |
| Wire promotion evidence | alpha-lifecycle → testing-validation (acceptance criteria) |
| Run historical backtest | backtest-engine (`feelies backtest` or `scripts/run_backtest.py`) |
| Inspect promotion ledger | alpha-lifecycle (`feelies promote …`) |
| Profile tick latency | performance-engineering → system-architect (micro-states) |
| Ingest / cache market data | data-engineering |

---

## Operator CLI surfaces

| Command | Skill | Entry point |
|---------|-------|-------------|
| `feelies promote …` | alpha-lifecycle | `src/feelies/cli/promote.py` |
| `feelies backtest …` | backtest-engine | `src/feelies/cli/backtest.py` |

Both register under `feelies = "feelies.cli.main:main"` in `pyproject.toml`.
