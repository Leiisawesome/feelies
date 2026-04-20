<!--
  File:     docs/design/three_layer_architecture.md
  Status:   DRAFT — awaiting repo author review
  Author:   feelies quant team (drafted via /quant-trading-skill)
  Audience: repo maintainer(s) and implementing engineer(s)
  Purpose:  Engineering specification for the 3-layer architecture refactor.
            This is a design document, not a ticket — approval required
            before any implementation work begins.
-->

# Engineering Specification — Three-Layer Architecture Refactor

**Version:** 0.2.0-DRAFT
**Status:** Phase-0 open questions resolved; awaiting final author sign-off
**Invariants preserved:** 1–13 (see `.cursor/rules/platform-invariants.mdc`)
**Breaking changes:** None at schema level; additive only (see §10)
**Estimated effort:** 7–9 engineer-weeks, delivered in 5 phases (revised — see §10)

### Change log

- **0.2.0** — Resolved §17 open questions Q1–Q10 inline; reconciled event
  contracts against actual `core/events.py` (kept existing `RegimeState`
  and `FeatureVector`; added `HorizonFeatureSnapshot` as a peer); renamed
  internal class versioning from `_v1`/`_v2` suffixes to descriptive
  `Legacy*`/`Horizon*` prefixes to avoid collision with YAML
  `schema_version` and alpha semver; bumped Phase 2 estimate; added
  capacity-scaling risk row; added glossary-update acceptance criterion.
- **0.1.0** — Initial draft.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Motivation](#2-motivation)
3. [Current State Analysis](#3-current-state-analysis)
4. [Target Architecture](#4-target-architecture)
5. [Event Contracts (Typed, on the Bus)](#5-event-contracts-typed-on-the-bus)
6. [Module-by-Module Changes](#6-module-by-module-changes)
7. [Micro State Machine Extension](#7-micro-state-machine-extension)
8. [Alpha YAML Schema Evolution](#8-alpha-yaml-schema-evolution)
9. [Platform Configuration Changes](#9-platform-configuration-changes)
10. [Migration Strategy (Phased)](#10-migration-strategy-phased)
11. [Backward Compatibility Guarantees](#11-backward-compatibility-guarantees)
12. [Determinism and Parity Requirements](#12-determinism-and-parity-requirements)
13. [Testing Strategy](#13-testing-strategy)
14. [Monitoring and Observability](#14-monitoring-and-observability)
15. [Risks and Mitigations](#15-risks-and-mitigations)
16. [Rollback Plan](#16-rollback-plan)
17. [Open Questions / Decisions — RESOLVED](#17-open-questions--resolved-v02)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Invariant Compliance Audit](#19-invariant-compliance-audit)
20. [Appendix A — Event Type Hierarchy](#appendix-a--event-type-hierarchy)
21. [Appendix B — File-Level Change Inventory](#appendix-b--file-level-change-inventory)

---

## 1. Executive Summary

### 1.1 What

Refactor the feelies tick pipeline from a **single-horizon per-tick evaluation
model** (every alpha evaluates on every quote/trade event) to a **three-layer,
multi-horizon model** that separates:

- **Layer 1 — SENSOR**: event-time state estimation (unchanged cadence; fires
  on every quote/trade).
- **Layer 2 — SIGNAL**: horizon-gated directional prediction (fires only on
  horizon bar-close events, e.g., every 30 s / 120 s / 300 s).
- **Layer 3 — PORTFOLIO**: cross-sectional construction across the universe
  at decision horizons (5 – 30 min).

### 1.2 Why

The current per-tick signal model implicitly encourages 1-second-horizon
alpha design, which is cost-arithmetic-infeasible on L1 data alone (round-trip
cost ≈ 3 bps vs 1-sec σ ≈ 2–5 bps on liquid names). The refactor decouples
measurement frequency (fast, L1-event-driven) from decision frequency
(slower, cost-hurdle-aware), which is how institutional microstructure desks
actually operate and is a prerequisite for any economically defensible alpha.

### 1.3 How (high level)

Four targeted changes to the existing architecture, all **additive** to the
current event bus contract:

1. **Introduce `SensorReading` and `HorizonFeatureSnapshot` as distinct event types**
   on the bus. Sensors emit `SensorReading` per tick; horizon aggregator
   emits `HorizonFeatureSnapshot` at horizon boundaries.
2. **Split `features/` into `sensors/` (Layer 1) and `features/` (Layer 2
   aggregator)**. Sensors are stateful and update per tick; features are
   horizon-bucketed, cross-symbol aggregations consumed by signals.
3. **Extend the Micro State Machine** with conditional transitions that
   route tick events to sensor updates only, and gate SIGNAL/PORTFOLIO
   evaluation on horizon bar-close events emitted by a new `HorizonScheduler`.
4. **Add `composition/` module** for Layer 3 cross-sectional construction,
   sitting between `signals/` and `risk/` in the event flow.

### 1.4 What stays the same

The event bus, state machine infrastructure, clock abstraction, determinism
guarantees, `ExecutionBackend` mode-swap pattern, `EventLog`/`ReplayFeed`,
risk engine state machine, cost model, order lifecycle, and the `alphas/`
YAML-per-spec authoring model all remain unchanged. This is a **refactor of
the signal-generation path**, not a rewrite.

### 1.5 What breaks

Nothing, if done correctly. All existing alphas in `alphas/trade_cluster_drift/`
continue to work via a compatibility shim (§11). New alphas opt into the
three-layer model via a `layer:` field in their YAML. The single-horizon
path is preserved as `layer: LEGACY_SIGNAL` and emits a deprecation warning
but does not fail.

---

## 2. Motivation

### 2.1 The core problem

The current Micro SM pipeline

```
WAITING → MARKET_EVENT → STATE_UPDATE → FEATURE → SIGNAL → RISK → ORDER → ACK → POSITION → LOG
```

fires every state from MARKET_EVENT through SIGNAL on **every quote/trade
tick** (Polygon L1 NBBO produces 10–500 events/sec per active symbol
during market hours). This has three consequences:

1. **Horizon confusion.** An alpha author is given a `features` block and a
   `signal` block, both evaluated per tick. The natural interpretation is
   "produce a directional signal on every tick," which is precisely the
   cost-arithmetic-infeasible pattern.

2. **No sensor / feature distinction.** The `features/` module conflates
   event-time state estimators (VPIN, Kyle λ, OFI EWMA — which SHOULD run
   per tick) with horizon-bucketed aggregates (3-minute OFI z-score,
   5-minute return forecast — which should fire only at horizon boundaries).
   Overloaded semantics produce both waste (recomputing stable state) and
   subtle bugs (bar-close windows misaligned with tick events).

3. **No cross-sectional construction.** The `portfolio/` module is per-symbol
   per-strategy. Cross-sectional ranking and factor neutralization — the
   primary breadth amplifier for any intraday equity book via
   `IR = IC × √N` — have nowhere to live.

### 2.2 The economic case (restated from prior discussion)

| Horizon | Typical σ (liquid large-cap) | Round-trip cost | Min IC needed |
|---|---|---|---|
| 1 sec | 2–5 bps | ~3 bps | > 0.6 (impossible on public L1) |
| 30 sec | 8–12 bps | ~3.5 bps | ~0.15 (very hard) |
| 2 min | 15–25 bps | ~4 bps | ~0.06 (achievable) |
| 5 min | 25–40 bps | ~4.5 bps | ~0.04 (achievable and published) |

The economically viable zone is 30 s–5 min for SIGNAL and 5–30 min for
PORTFOLIO. The refactor builds this zone in as a first-class citizen of the
platform, not something the alpha author has to reconstruct inside every
`signal` function.

### 2.3 Why now

- The alpha authoring surface (YAML + `signal` Python block) will be
  consumed by the Grok hypothesis-generation REPL (see
  `grok/prompts/hypothesis_reasoning.md`). Grok produces layer-classified
  hypotheses. The platform must accept them natively.
- Design invariant 8 ("layer separation") is currently interpreted as
  "ingestion / feature / signal / risk / execution" layers. The refactor
  extends this to include the **alpha-internal layer classification**
  (SENSOR / SIGNAL / PORTFOLIO), which is orthogonal and additive.
- Design invariant 12 ("expected edge must exceed 1.5× round-trip cost")
  is not mechanically enforced today. The three-layer model makes this
  gate machine-checkable via the `cost_arithmetic` YAML block (§8).

### 2.4 Non-goals

This refactor does NOT:

- Change the event bus transport (stays synchronous, in-process).
- Change the clock abstraction or `SimulatedClock` semantics.
- Change the `ExecutionBackend` / order router behavior.
- Change the cost model in `platform.yaml`.
- Change the risk engine escalation state machine.
- Introduce L2 order book support.
- Introduce ML-based signals.
- Introduce multi-process or multi-node execution.

If any of these become relevant later, they are scoped as separate proposals.

---

## 3. Current State Analysis

### 3.1 Module inventory (as-is)

```
src/feelies/
├── core/           Events, clock, state machine, identifiers, config
├── kernel/         Orchestrator, Macro SM, Micro SM
├── bus/            Synchronous deterministic event bus
├── ingestion/      Massive normalizer, historical ingestor, replay feed
├── features/       Feature engine protocol, definitions, standard library   ← SPLITS
├── signals/        Signal engine protocol                                    ← EXTENDED
├── alpha/          Alpha module system (loader, registry, composite, arbitration)  ← EXTENDED
├── risk/           Risk engine, escalation SM, position sizer
├── execution/      Backend abstraction, intent translator, order SM, routers
├── portfolio/      Position store, per-strategy tracking                     ← EXTENDED
├── storage/        Event log, disk cache, feature snapshots, trade journal
├── monitoring/     Metrics, alerting, kill switch, health checks
├── forensics/      Post-trade analysis, edge decay detection                 ← EXTENDED
├── research/       Experiment tracking, hypothesis management
├── services/       Regime engine (HMM-based)
└── bootstrap.py    One-call platform composition
```

### 3.2 Current event bus traffic (approximate, per active symbol)

| Event type | Frequency | Producer | Consumers |
|---|---|---|---|
| `NBBOQuote` | 10–100/sec | ingestion | features |
| `Trade` | 1–50/sec | ingestion | features |
| `FeatureUpdate` (?) | per-tick | features | signals |
| `Signal` | per-tick (when warm) | signals | risk |
| `OrderIntent` | as-generated | risk | execution |
| `OrderAck` / `Fill` / etc. | per order | execution | portfolio, monitoring |
| `StateTransition` | every SM step | all SMs | monitoring, storage |

Exact event types may differ — the author should reconcile this table
against `src/feelies/core/events.py` during review. The refactor adds
`SensorReading`, `HorizonFeatureSnapshot`, `HorizonTick`, and
`CrossSectionalContext` (§5).

### 3.3 What fits the 3-layer model without modification

- **Event bus.** Synchronous, typed, deterministic. Perfect substrate for
  multi-rate processing. No changes needed.
- **Clock abstraction.** `SimulatedClock` enables event-time horizon
  scheduling with zero real-time drift. No changes needed.
- **EventLog + ReplayFeed.** Deterministic replay is preserved because
  the new horizon events are **derived** from (not stored alongside)
  the underlying NBBOQuote/Trade stream. On replay, the same quotes
  produce the same horizon ticks, same feature snapshots, same signals.
  No changes needed to storage.
- **ExecutionBackend mode-swap.** Unchanged. Multi-horizon signals still
  produce `OrderIntent` events consumed by the same routers.
- **Risk engine.** Unchanged. Sees the same `OrderIntent` events from a
  different upstream source (composition layer instead of per-tick signal
  layer).
- **Regime engine (`services/hmm_3state_fractional`).** Already provides
  posteriors consumable by Layer 2 regime gates. No changes needed.

### 3.4 What does NOT fit and must change

- **`features/`** conflates SENSOR and SIGNAL-input semantics. Split required.
- **`signals/` evaluation cadence** is implicitly per-tick. Must become
  horizon-gated.
- **`alpha/` registry** assumes a flat namespace of signal-layer alphas. Must
  support three typed namespaces (sensor registry, signal registry, portfolio
  registry) with dependency resolution.
- **Micro SM** has no notion of horizon boundaries. Must be extended
  without breaking the existing FEATURE→SIGNAL transition.
- **`portfolio/`** tracks per-symbol positions but has no cross-sectional
  construction logic. A new `composition/` module sits upstream.
- **Alpha YAML schema** has no `layer`, `horizon_seconds`, `cost_arithmetic`,
  `regime_gate`, `depends_on_sensors`, or `depends_on_signals` fields.
  Additive extension required.
- **Forensics** reports single-horizon IC. Must be extended to report
  per-horizon and per-regime IC.

---

## 4. Target Architecture

### 4.1 Architectural diagram (post-refactor)

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Kernel / Orchestrator                             │
│   Macro SM · Micro SM (extended) · Risk SM · Order SM · Data SM      │
└──┬──────────────────┬────────────────┬──────────────┬────────────────┘
   │                  │                │              │
┌──▼────────┐  ┌─────▼─────────┐  ┌───▼──────┐  ┌───▼──────────┐
│ Ingestion │  │  Sensors      │  │ Features │  │ Signals       │
│ (unchanged│─▶│  (LAYER 1)    │─▶│ (LAYER 2 │─▶│ (LAYER 2      │
│  NBBO+Trd)│  │  event-time   │  │ aggreg.) │  │  horizon-     │
│           │  │  state est.   │  │ horizon- │  │  gated pred.) │
└───────────┘  └───────────────┘  │ bucketed │  └───────┬───────┘
                       │          └──────────┘          │
               ┌───────┴──────┐         │               │
               │  Services    │         │      ┌────────▼────────┐
               │ (Regime eng) │─────────┴─────▶│   Composition    │
               └──────────────┘                │   (LAYER 3       │
                                               │   cross-sect.    │
               ┌──────────────┐                │   ranking,       │
               │  Horizon     │ emits          │   factor-neutral)│
               │  Scheduler   │ HorizonTick    └────────┬─────────┘
               └──────┬───────┘ events                  │
                      │                                 │
               (drives bar-close                 ┌──────▼───────┐
                 on Micro SM)                    │    Risk      │
                                                 │  (unchanged) │
                                                 └──────┬───────┘
                                                        │
                                                 ┌──────▼───────┐
                                                 │   Execution  │
                                                 │  (unchanged) │
                                                 └──────────────┘
```

### 4.2 Responsibilities per layer

| Layer | Module | Input events | Output events | State | Cadence |
|---|---|---|---|---|---|
| 1 | `sensors/` | `NBBOQuote`, `Trade` | `SensorReading` | per-symbol-per-sensor | event-time (~10–500/sec) |
| 2a | `features/` | `SensorReading`, `HorizonTick` | `HorizonFeatureSnapshot` | per-symbol-per-feature-per-horizon | horizon-bar-close (30s / 120s / 300s) |
| 2b | `signals/` | `HorizonFeatureSnapshot`, `RegimeState` | `Signal` (layer=SIGNAL) | stateless (pure fn of snapshot) | horizon-bar-close |
| 3 | `composition/` | `Signal` (universe-wide), `HorizonTick` | `SizedPositionIntent` | cross-sectional context per decision horizon | decision-horizon (300s / 900s / 1800s) |

### 4.3 Directory structure (target)

```
src/feelies/
├── core/
│   └── events.py              ← ADD SensorReading, HorizonFeatureSnapshot,
│                                 HorizonTick, CrossSectionalContext,
│                                 SizedPositionIntent
├── kernel/
│   └── micro_sm.py            ← EXTEND with horizon-gated transitions
│                                 (see §7)
├── bus/                       (unchanged)
├── ingestion/                 (unchanged)
│
├── sensors/                   ← NEW (Layer 1)
│   ├── __init__.py
│   ├── protocol.py            Sensor ABC; per-tick update contract
│   ├── registry.py            Catalog of canonical sensors; version pinning
│   ├── horizon_scheduler.py   Emits HorizonTick on event-time boundaries
│   └── impl/
│       ├── ofi_ewma.py
│       ├── micro_price.py
│       ├── vpin_50bucket.py
│       ├── kyle_lambda_60s.py
│       ├── spread_z_30d.py
│       ├── realized_vol_30s.py
│       ├── quote_hazard_rate.py
│       ├── trade_through_rate.py
│       └── quote_replenish_asymmetry.py
│
├── features/                  ← REFACTORED (Layer 2 aggregator)
│   ├── __init__.py
│   ├── protocol.py            Feature ABC; horizon-boundary compute contract
│   ├── aggregator.py          Snapshot sensor state at HorizonTick; produce HorizonFeatureSnapshot
│   ├── legacy_shim.py         Compatibility for LEGACY_SIGNAL alphas (see §11)
│   └── impl/
│       └── (per-alpha feature modules, author-supplied)
│
├── signals/                   ← EXTENDED (Layer 2 predictor)
│   ├── __init__.py
│   ├── protocol.py            HorizonSignal ABC; accepts HorizonFeatureSnapshot + RegimeState
│   ├── engine.py              Evaluates only on HorizonFeatureSnapshot events
│   └── regime_gate.py         Posterior-threshold + hysteresis logic
│
├── composition/               ← NEW (Layer 3)
│   ├── __init__.py
│   ├── protocol.py            PortfolioAlpha ABC
│   ├── cross_sectional.py     Rank signals across universe at decision horizon
│   ├── factor_neutralizer.py  FF5 + momentum + STR residualization
│   ├── sector_matcher.py      GICS pair construction (optional)
│   ├── turnover_optimizer.py  CVXPY turnover-constrained allocator
│   └── synchronizer.py        Barrier: collect universe signals at horizon boundary
│
├── alpha/
│   ├── registry.py            ← EXTEND: three typed registries w/ DAG resolver
│   ├── loader.py              ← EXTEND: parse new YAML fields
│   ├── composite.py           (unchanged or merged with composition/)
│   └── layer_validator.py     ← NEW: enforces G1–G15 gates on load
│
├── risk/                      (unchanged)
├── execution/                 (unchanged)
├── portfolio/
│   └── cross_sectional_tracker.py  ← NEW: tracks universe-level positions
│                                      and factor exposures
├── storage/                   (unchanged)
├── monitoring/
│   └── horizon_metrics.py     ← NEW: per-horizon IC tracking
├── forensics/
│   └── multi_horizon_attribution.py  ← NEW: per-horizon, per-regime P&L decomp
├── research/                  (unchanged)
├── services/                  (unchanged)
└── bootstrap.py               ← EXTEND: wire sensors, features, composition
                                  into the orchestrator at startup
```

---

## 5. Event Contracts (Typed, on the Bus)

All events are dataclasses (or equivalent) in `src/feelies/core/events.py`,
serializable, immutable, and include the standard provenance header
(timestamp_ns, correlation_id, sequence, source_layer). All new events
listed here are **additive** to the existing bus contract.

### 5.1 `HorizonTick` (NEW)

Emitted by `HorizonScheduler` at deterministic event-time boundaries.
Drives Layer 2 aggregation and Layer 3 synchronization.

```python
@dataclass(frozen=True)
class HorizonTick:
    timestamp_ns: int                  # Event-time of the boundary
    correlation_id: CorrelationId      # Derived from horizon + boundary epoch
    sequence: int                      # Monotonic within horizon
    horizon_seconds: int               # e.g., 30, 120, 300, 900, 1800
    boundary_index: int                # k-th tick since session open
    session_id: str                    # 'US_EQUITY_RTH_20260420' etc.
    scope: Literal['SYMBOL', 'UNIVERSE']
    symbol: Optional[Symbol]           # Required if scope == 'SYMBOL'
```

Emission rule (deterministic): given session_open_ns and horizon_seconds,
emit at `session_open_ns + k * horizon_seconds * 1e9` for k = 1, 2, ...
Emission is triggered by the first underlying event (quote or trade) at or
after the boundary time. See §12 for the determinism proof sketch.

### 5.2 `SensorReading` (NEW)

Emitted by sensors on every tick (or throttled if declared). Consumed by
features aggregator and optionally by other sensors (with explicit
dependency declaration).

```python
@dataclass(frozen=True)
class SensorReading:
    timestamp_ns: int
    correlation_id: CorrelationId      # Matches triggering event
    sequence: int
    symbol: Symbol
    sensor_id: str                     # e.g., 'ofi_ewma'
    sensor_version: str                # Semver, from YAML spec
    value: float | tuple[float, ...]   # Scalar or vector
    confidence: float                  # 0..1; null → 1.0
    warm: bool                         # False until min_history satisfied
    provenance: SensorProvenance       # which inputs consumed
```

### 5.3 `HorizonFeatureSnapshot` (NEW)

Emitted by `features/aggregator.py` on `HorizonTick`. Consumed by horizon
signals.

```python
@dataclass(frozen=True, kw_only=True)
class HorizonFeatureSnapshot(Event):
    symbol: str
    horizon_seconds: int
    boundary_index: int
    values: dict[str, float]              # feature_id → value
    warm: dict[str, bool]                 # feature_id → is-warm
    stale: dict[str, bool]                # feature_id → no underlying update in window
    source_sensors: dict[str, list[str]]  # feature_id → [sensor_id used]
```

The base `Event` provides `timestamp_ns`, `correlation_id`, `sequence`,
and `source_layer` — these are **not redeclared** here, matching the
existing convention in `core/events.py`.

**Coexistence with existing `FeatureVector`.** The current
`FeatureVector` event (`core/events.py:85`) is **not removed or
renamed**. It continues to serve LEGACY_SIGNAL alphas at per-tick
cadence via `features/legacy_shim.py`. `HorizonFeatureSnapshot` is a
peer event consumed only by horizon-gated signals. The platform
glossary entry for "feature" (in `.cursor/rules/platform-invariants.mdc`)
must be updated in Phase 5 to acknowledge both shapes — see §18.2.

### 5.4 `RegimeState` (EXTEND existing)

The platform already has a `RegimeState` event at `core/events.py:104`,
emitted once per tick by the orchestrator after updating the
platform-level `RegimeEngine` (see `services/regime_engine.py:30`). Per
the resolution of Q4 (§17), the regime engine is **per-symbol stateful**
— this matches the existing `RegimeEngine` Protocol contract verbatim
and requires no semantic change.

**Existing shape (verified against `core/events.py:104–118`):**

```python
@dataclass(frozen=True, kw_only=True)
class RegimeState(Event):
    symbol: str
    engine_name: str                       # producer identity (already present)
    state_names: tuple[str, ...]           # parallel arrays — index i in
    posteriors: tuple[float, ...]          # posteriors corresponds to state_names[i]
    dominant_state: int                    # argmax(posteriors); index into state_names
    dominant_name: str                     # state_names[dominant_state]; convenience
```

The existing `engine_name` field already covers what I had originally
proposed as `regime_engine_id`; no duplicate is introduced. The
parallel-tuples representation (`state_names` + `posteriors`) is
preserved as-is — it is more efficient than `dict[str, float]` for the
small N=3 state count of `hmm_3state_fractional` and gives deterministic
iteration order for free.

**Refactor adds two fields, both with backward-compatible defaults:**

```python
    # ── NEW additive fields (Phase 1) ────────────────────────────
    horizon_seconds: int = 0    # 0 = event-time snapshot (legacy behavior)
    stability: float = 1.0      # 0..1; recent dominant-state stability over
                                # last N posteriors. 1.0 = stable; → 0 means
                                # frequent regime switches. Default 1.0 makes
                                # legacy producers a no-op.
```

`horizon_seconds = 0` means "current per-tick posterior" (legacy
behavior). Horizon signals consume the latest `RegimeState` at the
moment of `HorizonTick` emission; no separate per-horizon snapshot is
materialized on the bus. This avoids redundant traffic — the regime
engine state at horizon-boundary time is already a deterministic
function of the event log.

**Regime gate DSL binding (§8.4) interaction:**

The `regime_gate` DSL exposes posteriors via the `P(<state_name>)`
function form. The evaluator resolves these against the `RegimeState`
parallel tuples by looking up `posteriors[state_names.index(name)]`,
raising `UnknownRegimeStateError` if the name is absent. The dominant
state is exposed as the identifier `dominant`; e.g.
`dominant == "compression"` is a valid gate predicate. State names
match the engine's published `state_names` verbatim (`compression`,
`normal`, `vol_breakout` for the built-in HMM per
`services/regime_engine.py:HMM3StateFractional`).

**Implementer note:** the canonical example in
`design_docs/hypothesis_reasoning.md` uses the names `benign`,
`stressed`, `toxic` (from Appendix B of the prompt). These are the
*aspirational* taxonomy, not the *current* engine's published names.
Phase 3 must either (a) align the example to the engine's actual names
or (b) rename the HMM's published states to match the prompt. (b) is
backward-compatible if performed with care; (a) is a one-line YAML
edit. Defer the choice to Phase 3 review.

### 5.5 `Signal` (EXTEND existing)

The existing `Signal` event at `core/events.py:131` has the following
shape (verified against the repo, not speculative):

```python
@dataclass(frozen=True, kw_only=True)
class Signal(Event):
    symbol: str
    strategy_id: str
    direction: SignalDirection
    strength: float
    edge_estimate_bps: float
    metadata: dict[str, Any] = field(default_factory=dict)
```

The refactor adds four fields, all with defaults that preserve current
behavior:

```python
    # ── NEW additive fields (Phase 1) ────────────────────────────
    layer: Literal["SIGNAL", "LEGACY_SIGNAL"] = "LEGACY_SIGNAL"
    horizon_seconds: int = 0                          # 0 for LEGACY_SIGNAL
    regime_gate_state: Literal["ON", "OFF", "N/A"] = "N/A"
    consumed_features: tuple[str, ...] = ()           # for provenance
```

`tuple[str, ...]` (frozen) rather than `list[str]` for `consumed_features`,
matching the dataclass-frozen convention and the existing
`suppressed_features: frozenset[str]` precedent on `FeatureVector`.

**Bus coexistence.** Both LEGACY_SIGNAL and SIGNAL events flow on the
same bus channel. Downstream consumers (risk engine, monitoring,
forensics, position tracker) handle both transparently: the only field
they consult for routing is `strategy_id`, and the existing per-strategy
aggregation logic in the risk engine is correct for both layers without
modification. The `layer` field exists for forensics and reporting, not
for runtime dispatch.

### 5.6 `CrossSectionalContext` (NEW)

Emitted by `composition/synchronizer.py` when all symbols in the universe
have produced a `HorizonFeatureSnapshot` for the current decision-horizon tick
(barrier synchronization).

```python
@dataclass(frozen=True)
class CrossSectionalContext:
    timestamp_ns: int                  # = HorizonTick.timestamp_ns (UNIVERSE scope)
    correlation_id: CorrelationId
    sequence: int
    horizon_seconds: int               # decision horizon
    boundary_index: int
    universe: list[Symbol]
    signals_by_symbol: dict[Symbol, Signal | None]
    # None = symbol had no feature snapshot (stale or not warm)
    snapshots_by_symbol: dict[Symbol, HorizonFeatureSnapshot | None]
    completeness: float                # fraction of universe with valid signals
```

### 5.7 `SizedPositionIntent` (NEW, replaces per-symbol `OrderIntent` upstream path)

Emitted by portfolio alphas (Layer 3). Consumed by the risk engine.
For backward compatibility, LEGACY_SIGNAL alphas emit the existing
`OrderIntent` directly.

```python
@dataclass(frozen=True)
class SizedPositionIntent:
    timestamp_ns: int
    correlation_id: CorrelationId
    sequence: int
    strategy_id: str                   # e.g., 'pofi_xsect_v1'
    layer: Literal['PORTFOLIO']
    horizon_seconds: int
    target_positions: dict[Symbol, TargetPosition]
    factor_exposures: dict[str, float]  # post-neutralization check
    expected_turnover_usd: float
    expected_gross_exposure_usd: float
```

`TargetPosition` contains target dollar amount, direction, and per-symbol
execution urgency. The risk engine consumes this, applies limits, and
emits one or more `OrderIntent` events per symbol to execution — preserving
the existing downstream contract.

### 5.8 Event type hierarchy

See [Appendix A](#appendix-a--event-type-hierarchy) for the full inheritance
tree. All new events inherit the existing base event class (whatever the
repo currently uses for `correlation_id`/`sequence`/`timestamp_ns`).

---

## 6. Module-by-Module Changes

This section enumerates, for each affected module, the precise changes
required. Each subsection is scoped tightly so it can be estimated and
assigned as an independent work package.

### 6.1 `src/feelies/core/events.py`

**Change:** Add 5 new dataclasses (§5.1–§5.7).

**Non-change:** Existing event types and fields untouched. The bus contract
is preserved by strict superset.

**Estimation:** 0.5 day.

### 6.2 `src/feelies/sensors/` (NEW)

**Create:**
- `protocol.py` — `Sensor` ABC with `initial_state()`, `update(event, state, params) -> SensorReading | None`. Signature differs from current `features/` by returning a typed `SensorReading`, not a raw float.
- `registry.py` — `SensorRegistry` with `register(sensor_spec: SensorSpec) -> None`, `get(sensor_id, version) -> Sensor`, version pinning, and import-time conflict detection.
- `horizon_scheduler.py` — see §7.2 for semantics.
- `impl/*.py` — 10 canonical sensor implementations per the catalog in `grok/prompts/hypothesis_reasoning.md § 8`. Each sensor is ≤ 150 lines of Python with strict typing.

**Migration note:** The repo currently has feature implementations in
`alphas/*/` directories (external modules). These modules' `update(quote, ...)`
functions can be **adapted** into sensors by wrapping their return values
as `SensorReading`. A migration helper `sensors/_migration.py` reads a
legacy `features:` block from a YAML spec and produces equivalent sensor
registrations at load time (only for LEGACY_SIGNAL alphas).

**Estimation:** 2.5–3 weeks (revised from v0.1 estimate of 1.5 weeks).
Includes 10 sensor implementations; each requires (a) reference
implementation, (b) unit test against a hand-computed expected value,
(c) a locked test vector replayed from a fixture event log, and (d) a
benchmark with documented p50/p99 latency. VPIN, Kyle λ, and
`quote_replenish_asymmetry` are non-trivial individually; the per-sensor
budget of ~6 hours assumed in v0.1 is unrealistic for these three.

### 6.3 `src/feelies/features/` (REFACTORED)

**Preserve:**
- The existing `Feature` ABC and its standard-library implementations are
  kept under their current names. They are renamed in *intent* to
  `LegacyFeature` via a docstring/type-alias note, but the symbol name
  remains `Feature` for source-level backward compatibility with any
  alpha modules that import it directly.
- The existing `FeatureVector` event continues to be emitted by the
  legacy path verbatim (see §5.3).

**Add:**
- `protocol.py` — new `HorizonFeature` ABC with signature
  `compute(buffer_snapshot, params, regime_state) -> float`. Pure
  function; no instance state; stateless across invocations.
- `aggregator.py` — `HorizonAggregator` subscribes to `HorizonTick` and
  `SensorReading`. Maintains rolling buffers per (symbol, sensor_id)
  bounded by the maximum horizon in any registered feature. On
  `HorizonTick` for `(symbol, horizon)`, iterates registered
  `HorizonFeature` instances whose `horizon_seconds == horizon`,
  computes values, emits `HorizonFeatureSnapshot`.
- `legacy_shim.py` — wraps a legacy per-tick `Feature` into a
  `HorizonFeature` that runs on a synthetic 1-tick horizon. This
  preserves existing alpha behavior bit-for-bit (parity hash unchanged).

**Estimation:** 1 week.

### 6.4 `src/feelies/signals/` (EXTENDED)

**Change:**
- `protocol.py` — add `HorizonSignal` ABC.
  `evaluate(snapshot: HorizonFeatureSnapshot, regime: RegimeState, params) -> Signal | None`.
  Pure function, no instance state.
- `engine.py` — new `HorizonSignalEngine` subscribes to
  `HorizonFeatureSnapshot`. Reads the latest cached `RegimeState` for
  the snapshot's symbol from the regime engine. Applies `regime_gate`
  (on-condition / off-condition with hysteresis). If gate is ON,
  evaluates the signal function. Emits a `Signal` event with
  `layer="SIGNAL"`.
- `regime_gate.py` — implements the DSL for `on_condition` /
  `off_condition` (a small safe expression evaluator over named
  bindings like `P(benign)`, `vpin_50bucket_percentile`,
  `spread_z_30d`). See §8.4 for DSL spec.

**Preserve:** the existing per-tick signal engine continues to run for
LEGACY_SIGNAL alphas under the name `LegacySignalEngine` (the current
class is renamed in source; any external imports that referenced the
old name are kept working via a module-level alias).

**Estimation:** 1 week.

### 6.5 `src/feelies/composition/` (NEW)

**Create:**
- `protocol.py` — `PortfolioAlpha` ABC. `construct(ctx: CrossSectionalContext, params) -> SizedPositionIntent`.
- `synchronizer.py` — `UniverseSynchronizer` subscribes to `HorizonFeatureSnapshot`
  and `Signal` events. Maintains a per-horizon barrier: collects all
  symbols' signals for a given `(horizon_seconds, boundary_index)` tuple.
  Emits `CrossSectionalContext` when the barrier is full OR a timeout
  (stale budget) elapses. Completeness field reports fraction of universe
  present.
- `cross_sectional.py` — standard cross-sectional ranker (dollar-neutral
  L/S quintile by default; configurable).
- `factor_neutralizer.py` — residualizes signal weights against configured
  factor model (FF5 + momentum + STR by default). Uses pre-computed
  factor loadings from reference data; refresh cadence configurable.
- `sector_matcher.py` — optional GICS-sector-neutral pairing (toggleable).
- `turnover_optimizer.py` — CVXPY-based solver for
  `max w·α − λ_TC · |Δw|_1 − λ_risk · w'Σw` subject to turnover and
  exposure constraints.

**Dependency addition:** `cvxpy` becomes a required dependency (already
common in quant repos; gate behind optional `[portfolio]` extra if concerned).

**Estimation:** 1.5 weeks. `turnover_optimizer.py` is the only non-trivial
piece; the rest is composition of numpy/pandas routines.

### 6.6 `src/feelies/alpha/` (EXTENDED)

**Change:**
- `registry.py` — split the flat registry into three typed sub-registries:
  `SensorRegistry`, `SignalRegistry`, `PortfolioRegistry`. Add DAG
  resolver: on load, build the dependency graph from `depends_on_sensors`
  / `depends_on_signals`. Topological sort at bootstrap. Missing
  dependencies raise `UnresolvedDependencyError` before any alpha runs.
- `loader.py` — parse the new YAML fields (§8). Dispatch to the correct
  registry based on `layer:` field. Enforce schema_version ≥ 1.1 for
  layered alphas.
- `layer_validator.py` (NEW) — enforces gates G1–G15 from
  `grok/prompts/hypothesis_reasoning.md § 6` on YAML load. Load-time
  validation produces clear error messages tied to gate IDs. Alphas
  failing G1–G11 are refused; alphas failing G12–G15 are refused with a
  different error class (author must fix, cannot be soft-drafted).

**Estimation:** 1 week (with the validator being the main cost).

### 6.7 `src/feelies/kernel/micro_sm.py` (EXTENDED)

See §7 for full treatment. Summary: add three new states (SENSOR_UPDATE,
HORIZON_TICK, CROSS_SECTIONAL) and conditional transitions. Preserve the
legacy path via a branch predicate on the triggering event type.

**Estimation:** 1 week (includes property-based tests for all transition
paths).

### 6.8 `src/feelies/portfolio/` (EXTENDED)

**Add:** `cross_sectional_tracker.py` — tracks universe-level positions
aggregated across symbols, gross and net exposures, factor exposures
computed post-trade. Feeds monitoring and forensics.

**Preserve:** existing per-symbol tracking.

**Estimation:** 3 days.

### 6.9 `src/feelies/monitoring/` (EXTENDED)

**Add:** `horizon_metrics.py` — per-horizon IC tracker, per-regime
performance tracker, hypothesis lifecycle status tracker (tied to
`research/hypothesis_status.py`). Emits alerts when realized IC drops
below configured threshold for a given alpha.

**Estimation:** 1 week.

### 6.10 `src/feelies/forensics/` (EXTENDED)

**Add:** `multi_horizon_attribution.py` — decomposes P&L into:

- Gross alpha (per horizon)
- TC drag (spread + impact + fees, per horizon)
- Factor bleed (unintended exposure, per factor)
- Timing slippage (signal-to-fill delta)
- Net alpha
- Realized-vs-expected IC (per alpha, per horizon, per regime)

Output consumed by the Grok mutation protocol (§ Axis evaluation).

**Estimation:** 1 week.

### 6.11 `src/feelies/bootstrap.py` (EXTENDED)

**Change:** wire the new modules at startup. Composition order matters and
must be deterministic:

1. Load platform.yaml.
2. Build regime engine.
3. Build SensorRegistry; instantiate all referenced sensors; subscribe to
   bus for NBBOQuote/Trade.
4. Build HorizonScheduler; instantiate for every unique
   `horizon_seconds` appearing in any loaded alpha's YAML.
5. Build HorizonAggregator; subscribe to SensorReading + HorizonTick.
6. Build HorizonSignalEngine; subscribe to HorizonFeatureSnapshot.
7. Build UniverseSynchronizer; subscribe to Signal + HorizonTick (UNIVERSE scope).
8. Build composition.PortfolioAlpha instances; subscribe to
   CrossSectionalContext.
9. Build LegacySignalEngine (legacy) if any LEGACY_SIGNAL alpha is loaded.
10. Connect risk engine downstream.
11. Emit MACRO.READY.

**Estimation:** 2 days.

---

## 7. Micro State Machine Extension

This is the most delicate piece of the refactor. The existing Micro SM is
correct and well-tested. We extend it by adding branches, not by mutating
the existing path.

### 7.1 Current Micro SM (from README)

```
WAITING → MARKET_EVENT → STATE_UPDATE → FEATURE → SIGNAL → RISK → ORDER → ACK → POSITION → LOG
```

Every tick walks the full path.

### 7.2 Extended Micro SM

```
                          ┌────────────────────────────────────────────────┐
                          │                                                │
           ┌──────────────▼────┐                                           │
WAITING ──▶│   MARKET_EVENT    │                                           │
           └─────────┬─────────┘                                           │
                     │                                                     │
              ┌──────▼──────┐                                              │
              │ STATE_UPDATE│                                              │
              │  (sensors)  │                                              │
              └──────┬──────┘                                              │
                     │                                                     │
          ┌──────────┴──────────────────┐                                  │
          │                             │                                  │
          ▼                             ▼                                  │
  ┌───────────────┐           ┌───────────────────┐                        │
  │ HORIZON_CHECK │           │ LEGACY_PATH       │                        │
  │ (scheduler    │           │ (LEGACY_SIGNAL    │                        │
  │  decides if   │           │  alphas only)     │                        │
  │  boundary hit)│           │  FEATURE→SIGNAL   │                        │
  └───────┬───────┘           │  per-tick         │                        │
          │                   └──────┬────────────┘                        │
  ┌───────┴─────┐                    │                                     │
  │             │                    ▼                                     │
  ▼ no          ▼ yes             RISK                                     │
 LOG        ┌────────┐               │                                     │
 (sensors   │HORIZON_│               ▼                                     │
  emitted)  │  TICK  │             ORDER                                   │
            └───┬────┘               │                                     │
                │                    ▼                                     │
                ▼                   ACK                                    │
         ┌─────────────┐             │                                     │
         │   FEATURE   │             ▼                                     │
         │   (v2       │           POSITION                                │
         │   aggregate)│             │                                     │
         └──────┬──────┘             ▼                                     │
                │                   LOG ──────────────────────────────────┘
                ▼
         ┌─────────────┐
         │    SIGNAL   │
         │  (v2 gated  │
         │  by regime) │
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐   (only on UNIVERSE-scope horizon ticks
         │CROSS_SECTION│    when all symbols collected)
         │   (compose) │
         └──────┬──────┘
                │
                ▼
              RISK ──▶ ORDER ──▶ ACK ──▶ POSITION ──▶ LOG
```

### 7.3 Transition rules (formal)

```
State            | Trigger event                | Next state       | Guard
─────────────────┼──────────────────────────────┼──────────────────┼───────────────────────────
WAITING          | NBBOQuote | Trade            | MARKET_EVENT     | —
MARKET_EVENT     | (internal)                   | STATE_UPDATE     | —
STATE_UPDATE     | (internal; sensors updated)  | HORIZON_CHECK    | any v2 alpha loaded
                 |                              | LEGACY_PATH      | only legacy alphas loaded
                 |                              | LOG              | no alphas loaded
HORIZON_CHECK    | (internal)                   | HORIZON_TICK     | scheduler.is_boundary()
                 |                              | LEGACY_PATH      | legacy alpha also loaded
                 |                              | LOG              | otherwise
HORIZON_TICK     | HorizonTick emitted          | FEATURE          | scope == SYMBOL
                 |                              | CROSS_SECTIONAL  | scope == UNIVERSE
FEATURE          | HorizonFeatureSnapshot emitted      | SIGNAL           | —
SIGNAL           | Signal emitted               | LOG              | v2 alpha, no composition
                 |                              | WAITING          | v2 alpha, composition pending
CROSS_SECTIONAL  | CrossSectionalContext emitted| RISK             | completeness > threshold
                 |                              | LOG              | otherwise (skip decision)
LEGACY_PATH      | FeatureUpdate_v1 emitted     | RISK             | legacy signal fires
                 |                              | LOG              | legacy signal is None
RISK, ORDER, ACK, POSITION, LOG: unchanged
```

### 7.4 HorizonScheduler semantics

Deterministic, event-driven:

```python
class HorizonScheduler:
    def __init__(self, clock: Clock, session_open_ns: int,
                 horizons: set[int]):
        self._clock = clock
        self._session_open_ns = session_open_ns
        self._horizons = horizons
        self._last_boundary: dict[int, int] = {h: 0 for h in horizons}

    def on_event(self, event: Event) -> list[HorizonTick]:
        """Called on every quote/trade. Returns zero or more HorizonTicks
        for horizons whose boundary has been crossed by this event's
        timestamp. Ticks are emitted in ascending horizon order for
        determinism."""
        t = event.timestamp_ns
        ticks = []
        for h in sorted(self._horizons):
            h_ns = h * 1_000_000_000
            current_boundary = (t - self._session_open_ns) // h_ns
            if current_boundary > self._last_boundary[h]:
                self._last_boundary[h] = current_boundary
                ticks.append(HorizonTick(
                    timestamp_ns=self._session_open_ns + current_boundary * h_ns,
                    horizon_seconds=h,
                    boundary_index=current_boundary,
                    # ... other fields
                ))
        return ticks
```

**Critical determinism property:** the boundary timestamps are a pure
function of `(session_open_ns, horizon_seconds, boundary_index)`, NOT the
triggering event's timestamp. The event merely signals that the boundary
has been reached; the tick itself carries the boundary's theoretical
timestamp. This ensures that replaying the same event log produces
bit-identical HorizonTick streams regardless of which event triggered
the emission (e.g., if a trade at t=10:30:00.001 triggers the 10:30:00
boundary tick, the tick carries timestamp 10:30:00.000, not
10:30:00.001).

### 7.5 UniverseSynchronizer barrier semantics

The Synchronizer is the single non-trivial correctness risk in this design.
Spec:

- Maintains a map `{(horizon, boundary_index): {symbol: Signal | None}}`.
- On `Signal` event with `horizon_seconds == decision_horizon`, record.
- On `HorizonTick` with `scope == UNIVERSE` and matching horizon, this is
  the "barrier closed" trigger. Emit `CrossSectionalContext` with
  whatever has been collected. Fill missing symbols with `None`.
- Garbage-collect entries older than 2× the decision horizon to bound memory.

**Determinism property:** the barrier-close event is the UNIVERSE-scope
HorizonTick, not "when all symbols have reported." This makes the
emission timestamp deterministic. Completeness varies with data sparseness
but the event emission itself does not.

### 7.6 Legacy path coexistence

LEGACY_SIGNAL alphas continue to use the existing
`WAITING → ... → FEATURE → SIGNAL → RISK → ORDER → ACK → POSITION → LOG`
path verbatim. This is not re-implemented; it is the original Micro SM
code, guarded by a predicate that selects it when only legacy alphas are
loaded for that symbol OR as a parallel branch alongside v2 alphas.

In mixed mode (some v2, some legacy alphas on same symbol), both paths
run; their signals reach the risk engine independently; the risk engine
aggregates as it already does (per strategy).

---

## 8. Alpha YAML Schema Evolution

### 8.1 Schema version bump

`schema_version: "1.0"` → `schema_version: "1.1"`.

Schema 1.0 files continue to load as `layer: LEGACY_SIGNAL` with a
deprecation warning logged at bootstrap.

Schema 1.1 files MUST declare `layer: SENSOR | SIGNAL | PORTFOLIO`.

### 8.2 Additive fields (all mandatory for 1.1)

The full set is specified in `grok/prompts/hypothesis_reasoning.md § 7`.
Summary:

- `layer: SENSOR | SIGNAL | PORTFOLIO`
- `horizon_seconds: int` (required for SIGNAL and PORTFOLIO; must be
  ≥ 30 for SIGNAL, ≥ 300 for PORTFOLIO)
- `structural_actor: str` (markdown block)
- `mechanism: str` (markdown block)
- `cost_arithmetic: {...}` (required for SIGNAL and PORTFOLIO; enforces
  `margin_ratio >= 1.5` per Invariant 12)
- `regime_gate: {on_condition, off_condition, hysteresis}`
  (required for SIGNAL and PORTFOLIO)
- `depends_on_sensors: [{sensor_id, version, min_history_seconds}]`
  (required for SIGNAL; optional for SENSOR if a sensor depends on another)
- `depends_on_signals: [{signal_id, version}]` (required for PORTFOLIO;
  must be non-empty)
- Extended `falsification_criteria: {statistical, structural_invalidators, regime_shift_invalidators}`

### 8.3 Layer-specific additions

- SENSOR: `state_estimator:` Python block replacing `signal:`; `output_schema:`.
- SIGNAL: existing `signal:` block signature changes to
  `evaluate(features, params, regime)`.
- PORTFOLIO: `construction:` block (ranking, L/S sets, weighting,
  factor_neutralization); no `signal:` block (uses `construct:` block
  instead: `construct(ctx, params) -> SizedPositionIntent`).

### 8.4 Regime gate expression DSL

`on_condition` / `off_condition` are strings evaluated in a restricted
environment. Allowed identifiers:

- `P(state_name)` — regime posterior, float in [0, 1]
- `<sensor_id>` — latest SensorReading value
- `<sensor_id>_percentile` — percentile rank in rolling window
- `<sensor_id>_zscore` — z-score in rolling window

Allowed operators: `and`, `or`, `not`, `>`, `<`, `>=`, `<=`, `==`, `!=`,
`abs()`, `min()`, `max()`, `p<nn>` literal (e.g., `p40` = 0.40 percentile).

Forbidden: function calls other than the whitelist, attribute access,
imports, `eval`, `exec`, list comprehensions, lambdas.

Implemented via `ast.parse` + AST walk with a visitor that rejects any
unwhitelisted node type. No string interpolation, no templating.

### 8.5 Parameter surface cap

Per Gate G12: at most 3 parameters with `range` declared (i.e., free for
optimization). Additional parameters with only `default` (no `range`) are
allowed and unlimited. This constrains the overfitting surface without
preventing configuration.

### 8.6 Migration of existing `alphas/trade_cluster_drift/`

Immediate: tag with `layer: LEGACY_SIGNAL` via a one-line PR, add
deprecation comment. Continues to work.

Later: rewrite as a native SIGNAL-layer alpha using canonical sensors. This
is not blocking; legacy support is permanent (though maintenance-only).

### 8.7 Schema 1.0 → 1.1 field-level compatibility (NORMATIVE)

To prevent any ambiguity at the loader level, the following fields from
schema 1.0 are **preserved verbatim** under `layer: LEGACY_SIGNAL`:

- `features:` block — the existing per-tick feature definitions and
  `update(quote, state, params)` Python signature are unchanged. Loader
  routes them through `LegacyFeature` and the `legacy_shim.py` adapter.
- `signal:` block — the existing per-tick signal Python signature
  `evaluate(features, params)` is unchanged. Loader instantiates them
  under `LegacySignalEngine`.
- `parameters:`, `risk_budget:`, `symbols:`, `falsification_criteria:`
  (1.0 form) — all preserved verbatim.
- Any field present in 1.0 but absent from 1.1's mandatory set is
  **kept**, not stripped, so older alphas round-trip through
  load → serialize → load with bit-identical YAML.

Schema 1.1 alphas (`layer: SIGNAL | PORTFOLIO | SENSOR`) get the
mandatory new fields enumerated in §8.2. Mixed-shape YAML (1.0 fields
plus a `layer: SIGNAL` declaration) is **rejected** by the loader with a
clear error pointing the author at the migration guide
(`docs/migration/schema_1_0_to_1_1.md`, Phase 5 deliverable). There is
no implicit upgrade path — the choice is opt-in only.

---

## 9. Platform Configuration Changes

`platform.yaml` gets additive fields. None of the existing fields change
semantics.

```yaml
# ── NEW: Multi-Horizon Configuration ─────────────────────
# Session-open timestamp in event-time (nanoseconds since epoch).
# Used as anchor for horizon boundary computation.
# For US equity RTH: 09:30:00 ET in the event's trading date.
# When null (default), derived from first market event of the session.
session_open_ns: null

# Horizons registered at bootstrap. Union of all horizons declared by
# loaded alphas. Explicit entry here is optional — bootstrap derives
# this set automatically from alpha specs. Listed here only for
# documentation / explicit override.
registered_horizons_seconds: [30, 120, 300, 900, 1800]

# Cross-sectional barrier timeout. If UNIVERSE-scope HorizonTick fires
# and fewer than `completeness_threshold` fraction of symbols have
# reported, skip the decision (emit warning). Typical: 0.80.
composition_completeness_threshold: 0.80

# Factor model for portfolio neutralization.
factor_model: "FF5_momentum_STR"        # or "none" to disable

# Factor loadings refresh cadence (in seconds). 0 = static at bootstrap.
factor_loadings_refresh_seconds: 3600

# Turnover optimizer weight on TC penalty (λ_TC).
composition_lambda_tc: 1.0

# Turnover optimizer weight on risk penalty (λ_risk).
composition_lambda_risk: 0.1

# ── NEW: Layer Enforcement ───────────────────────────────
# If true, alphas failing any of G1-G15 gates refuse to load.
# If false, only G12-G15 are blocking; G1-G11 warnings logged.
# Production: true. Development: may be false with justification.
enforce_layer_gates: true

# ── NEW: Legacy Support ──────────────────────────────────
# If true, schema_version 1.0 alphas load with deprecation warning.
# If false, 1.0 alphas refused.
allow_legacy_signal_alphas: true
```

### 9.1 No changes to cost model fields

The existing cost fields in `platform.yaml` (commission, exchange fees,
regulatory fees, stress multiplier, etc.) are consumed by the
`cost_arithmetic` validator in `alpha/layer_validator.py` without
modification. The validator reads these fields and computes the per-alpha
hurdle against the declared `expected_edge_bps`.

### 9.2 No changes to risk fields

Existing `risk_max_*` fields are consumed by the risk engine as-is. The
risk engine receives `SizedPositionIntent` (Layer 3) or `OrderIntent`
(Legacy) and applies the same limits.

---

## 10. Migration Strategy (Phased)

Five phases. Each phase is independently shippable, independently testable,
and independently reversible. No phase requires the previous phase to be
merged — only to be **designed**. This lets implementation parallelize if
multiple engineers are available.

### Phase 0 — Design review and schema freeze (this document)

**Goal:** repo author signs off on this spec. No code changes.

**Deliverable:** this document merged to `docs/design/three_layer_architecture.md`,
with author approval recorded in commit message.

**Blockers to resolve:** all items in §17.

**Estimated duration:** 1–2 weeks of async review.

### Phase 1 — Event contracts and schema extension

**Goal:** new event types on the bus; YAML schema 1.1 accepted by loader
but with `layer: LEGACY_SIGNAL` as the only parsed value. No behavior
change.

**Deliverables:**
- `src/feelies/core/events.py` extended with 5 new types.
- `src/feelies/alpha/loader.py` accepts schema 1.1 with `layer:
  LEGACY_SIGNAL`.
- `src/feelies/alpha/layer_validator.py` scaffolded, only G14–G15 active.
- `alphas/SCHEMA.md` updated with new fields (documented but not yet used).

**Test gates:**
- Existing test suite passes unchanged.
- Parity hash of `scripts/run_backtest.py` output unchanged for
  `alphas/trade_cluster_drift/`.
- New event types round-trip through bus serialization.

**Estimated duration:** 1 week.

### Phase 2 — Sensor layer and horizon scheduling

**Goal:** sensors and horizon scheduler live on the bus but do not affect
signals or orders. Observable only in logs.

**Deliverables:**
- `src/feelies/sensors/` module complete with 10 canonical sensors.
- `src/feelies/sensors/horizon_scheduler.py` emitting `HorizonTick`.
- Sensors subscribe to quotes/trades, emit `SensorReading`.
- Aggregator emits `HorizonFeatureSnapshot` on horizon ticks.
- New monitoring metrics: sensor throughput, horizon tick cadence.

**Test gates:**
- Existing test suite + parity hash: unchanged.
- New test: determinism of `HorizonTick` stream under replay
  (bit-identical across runs).
- New test: `SensorReading` stream replayable across runs.
- Benchmark: sensor update latency < 100 μs per event at p99 on reference
  hardware (documented in test output).

**Estimated duration:** 2.5–3 weeks (revised from v0.1's 1.5 weeks; see
§6.2 for the rationale — VPIN, Kyle λ, and `quote_replenish_asymmetry`
each require careful unit testing and locked test vectors).

### Phase 3 — Signal layer v2 and regime gate

**Goal:** SIGNAL-layer alphas can be authored and run alongside legacy.

**Deliverables:**
- `src/feelies/signals/engine.py` — `HorizonSignalEngine`.
- `src/feelies/signals/regime_gate.py` — DSL evaluator.
- `src/feelies/alpha/layer_validator.py` — gates G1–G13 active.
- One reference SIGNAL alpha (`alphas/pofi_benign_midcap_v1/`) per the
  canonical example in `grok/prompts/hypothesis_reasoning.md § 9`.

**Test gates:**
- Legacy alphas continue to pass parity hash.
- Reference SIGNAL alpha produces a deterministic signal stream
  (bit-identical across replays).
- Regime gate DSL rejects unsafe expressions (property-based test).
- Cost arithmetic validator correctly rejects an alpha with
  `margin_ratio < 1.5`.

**Estimated duration:** 1.5 weeks.

### Phase 4 — Composition layer and cross-sectional construction

**Goal:** PORTFOLIO-layer alphas fully functional; universe synchronizer
shipping `CrossSectionalContext`; turnover-aware construction producing
`SizedPositionIntent` consumed by risk engine.

**Deliverables:**
- `src/feelies/composition/` module complete.
- `src/feelies/portfolio/cross_sectional_tracker.py`.
- `src/feelies/monitoring/horizon_metrics.py`.
- `src/feelies/forensics/multi_horizon_attribution.py`.
- Reference PORTFOLIO alpha consuming the Phase 3 SIGNAL alpha.

**Test gates:**
- Universe synchronizer barrier is deterministic across replays.
- Factor neutralizer produces residual `|β| < 0.10` on synthetic test.
- Turnover optimizer converges on canonical test cases.
- End-to-end: reference SIGNAL + PORTFOLIO alphas produce a deterministic,
  parity-hash-stable trade sequence.

**Estimated duration:** 1.5 weeks.

### Phase 5 — Documentation, Grok wiring, and author migration

**Goal:** first external alpha authors (via Grok REPL) produce validated
layered alphas. Legacy alphas flagged for migration.

**Deliverables:**
- `README.md` updated with three-layer architecture diagram.
- `grok/prompts/hypothesis_reasoning.md` wired to the REPL entry point.
- Migration guide for legacy alphas (`docs/migration/schema_1_0_to_1_1.md`).
- Deprecation timer for LEGACY_SIGNAL (e.g., supported through Q4 2026).

**Estimated duration:** 1 week.

### Total timeline (revised v0.2)

| Phase | Estimated duration |
|---|---|
| 0 — Design freeze (this document) | 1–2 wk async review |
| 1 — Event contracts + schema | 1 wk |
| 2 — Sensor layer + horizon scheduling | 2.5–3 wk |
| 3 — Signal layer v2 + regime gate | 1.5 wk |
| 4 — Composition layer | 1.5 wk |
| 5 — Docs, Grok wiring, migration | 1 wk |

**Optimistic** (one engineer, full-time, no blockers): **8 weeks** of
implementation + 1–2 wk Phase 0 review.
**Realistic** (review cycles, part-time, integration surprises):
**12–14 weeks**.
**Pessimistic** (Phase 2 or 3 redesign required after author feedback):
**18–22 weeks**.

The revision reflects the Phase 2 sensor-implementation estimate bump
in §6.2; all other phases retain their v0.1 estimates.

---

## 11. Backward Compatibility Guarantees

### 11.1 Contract: no existing alpha breaks

Every alpha in `alphas/` at the moment this spec is approved MUST continue
to produce **bit-identical** trade sequences after Phase 5 is complete,
under the existing parity hash check.

This is enforced by:

- `layer: LEGACY_SIGNAL` path preserves the original Micro SM FEATURE→SIGNAL
  transition verbatim.
- `features/legacy_shim.py` wraps legacy `update(quote, state, params)`
  functions without changing their behavior.
- Legacy alphas never see `HorizonFeatureSnapshot` or `HorizonTick` — they operate
  on raw quote/trade events as today.
- Parity hash CI check runs on every PR in the `alphas/trade_cluster_drift/`
  reference alpha. A failure blocks merge.

### 11.2 Contract: no event on the bus is removed or changed

New event types are additive. Existing event types (`NBBOQuote`, `Trade`,
existing `Signal`, `OrderIntent`, `OrderAck`, `Fill`, etc.) preserve their
exact schema. If any field on an existing event type is changed, it is a
breaking change and requires a separate proposal.

### 11.3 Contract: no config field changes semantics

Every existing `platform.yaml` field retains its current meaning. New fields
are added with defaults that preserve current behavior when omitted.

### 11.4 Contract: `ExecutionBackend` is not touched

The mode-swap pattern (`BacktestOrderRouter`, `PassiveLimitOrderRouter`,
`MassiveLiveFeed`, etc.) is preserved exactly. Layer 3 composition emits
`SizedPositionIntent`; the risk engine translates to `OrderIntent` as
before; `ExecutionBackend` receives `OrderIntent` as before.

### 11.5 Deprecation policy

- Schema 1.0 is supported through **Q4 2026** at minimum.
- Deprecation warning logged once per boot per legacy alpha.
- Removal requires a separate proposal with explicit migration plan.

---

## 12. Determinism and Parity Requirements

Invariant 5 ("deterministic replay") is the single most sensitive property
of the platform. This refactor must preserve it absolutely.

### 12.1 Proof sketch: HorizonTick determinism

Claim: given the same `EventLog` and the same `session_open_ns`, the
`HorizonScheduler` emits an identical sequence of `HorizonTick` events
across any number of replays.

Proof:
- The triggering events (`NBBOQuote`, `Trade`) are delivered in a fixed,
  deterministic order from `ReplayFeed`.
- The scheduler's only state is `_last_boundary: dict[horizon, int]`, which
  is updated monotonically.
- The boundary computation
  `(t - session_open_ns) // h_ns` is a pure integer function of `t` and
  `h`.
- The emitted `HorizonTick.timestamp_ns` is
  `session_open_ns + current_boundary * h_ns`, which is a pure function of
  integer inputs.

Therefore the tick sequence is determined entirely by the event-log
content and the (fixed) configuration. QED.

### 12.2 Proof sketch: HorizonFeatureSnapshot determinism

Claim: given a deterministic `SensorReading` stream and a deterministic
`HorizonTick` stream, the `HorizonAggregator` produces a deterministic
`HorizonFeatureSnapshot` stream.

Proof:
- The aggregator's state is a bounded ring buffer per (symbol, sensor_id)
  updated on `SensorReading` (deterministic input).
- On `HorizonTick` (deterministic input), the aggregator iterates
  registered `HorizonFeature` instances in a **sorted** order by `feature_id`
  (ties broken by version) — not insertion order. This guarantees
  order-independence of registry construction.
- Each feature function is pure: `compute(buffer_snapshot, params) → float`.
  Non-determinism in the feature implementation (e.g., hash iteration
  order in Python dicts) must be prevented by requiring feature functions
  to consume only typed buffers, not raw dicts.

### 12.3 Proof sketch: CrossSectionalContext determinism

Claim: given deterministic `Signal` and `HorizonTick` streams, the
`UniverseSynchronizer` produces a deterministic `CrossSectionalContext`
stream.

Proof sketch:
- Barrier close is triggered by UNIVERSE-scope `HorizonTick` (deterministic).
- Collected `Signal` dict is filled by the signals arriving before the
  barrier; their arrival order is a deterministic sub-sequence of the
  Signal stream.
- `signals_by_symbol` is a dict keyed by Symbol; to ensure determinism of
  the emitted event's field order (for hashing), we serialize to a
  frozen, Symbol-sorted representation before emission.

### 12.4 Parity hash extension

The existing parity hash (SHA-256 over ordered trade sequence) is
extended:

- **Level 1 (existing)**: SHA-256 over ordered `Fill` events.
- **Level 2 (NEW)**: SHA-256 over ordered `Signal` events.
- **Level 3 (NEW)**: SHA-256 over ordered `HorizonFeatureSnapshot` events.
- **Level 4 (NEW)**: SHA-256 over ordered `SensorReading` events.

Each level is a separate hash; CI checks all four per reference alpha on
every PR. Level 1 is the existing contract; Levels 2–4 are new.

If any of Levels 2–4 diverges between two runs on identical inputs, the
build fails with a detailed diff pointing at the divergence point.

### 12.5 Non-determinism risk inventory

| Source | Risk | Mitigation |
|---|---|---|
| Python dict iteration order | Low (Python 3.12 preserves insertion order) | Use `sorted()` at all emission boundaries |
| Set iteration | Medium | Forbid `set` in state; use `dict` or `list` |
| Hash randomization | Low (PYTHONHASHSEED=0 in test) | CI sets `PYTHONHASHSEED=0` |
| Float reduction order | Medium | Use `math.fsum` for summations over > 10 items |
| Concurrent event delivery | N/A (bus is synchronous) | Invariant 7 holds |
| Factor model refresh | Medium | Refresh at horizon boundaries, not real-time |
| CVXPY solver | High | Pin solver (`ECOS` or `SCS`), set seed, tolerate on rerun check |
| `numpy` / `pandas` upgrades | Medium | Pin versions in `pyproject.toml`; CI canary on upgrade |

---

## 13. Testing Strategy

### 13.1 Test pyramid

| Level | Scope | Tool | Count (approx) |
|---|---|---|---|
| Unit | One module/class | pytest | 200–300 new |
| Property | Invariants under random inputs | hypothesis | 30–50 new |
| Integration | Multi-module subsystem | pytest | 20–30 new |
| End-to-end | Full bootstrap + backtest | pytest + fixtures | 5–10 new |
| Determinism | Replay parity | pytest | 4 (one per hash level) |
| Performance | Latency, memory | pytest-benchmark | 10–20 new |

### 13.2 Determinism tests (CRITICAL)

The single most important new test category:

```python
def test_horizon_tick_determinism(reference_event_log):
    """Running the same event log twice produces bit-identical
    HorizonTick streams."""
    run1 = replay_and_collect(reference_event_log, event_type=HorizonTick)
    run2 = replay_and_collect(reference_event_log, event_type=HorizonTick)
    assert hashes_equal(run1, run2)
```

One such test per new event type. One aggregate test for the full
Level-1–Level-4 parity hash.

### 13.3 Property-based tests (hypothesis)

- `regime_gate` DSL evaluator: any safe expression parses and evaluates
  without error.
- `regime_gate` DSL evaluator: any unsafe expression (attribute access,
  imports, lambda, etc.) raises `UnsafeExpressionError`.
- `HorizonScheduler`: monotonic `boundary_index` for every horizon.
- `UniverseSynchronizer`: `completeness` ∈ [0, 1] and equals (num present
  symbols) / (num universe symbols) exactly.
- `FactorNeutralizer`: residual weights satisfy `|β_i| < tolerance` for
  any factor `i`.

### 13.4 Integration tests

- Full Phase-2 pipeline: load reference sensors, replay one day of AAPL
  data, assert expected `SensorReading` count and value ranges.
- Full Phase-3 pipeline: add a SIGNAL alpha, assert regime-gated signal
  emission rate.
- Full Phase-4 pipeline: add 5-symbol universe with a PORTFOLIO alpha,
  assert dollar-neutral construction and factor exposures within tolerance.

### 13.5 End-to-end tests

- `test_legacy_alpha_parity_preserved`: the
  `alphas/trade_cluster_drift/` alpha produces the exact same trade
  sequence post-refactor as pre-refactor. Level-1 parity hash check.
- `test_v2_alpha_deterministic`: reference
  `alphas/pofi_benign_midcap_v1/` alpha produces a deterministic trade
  sequence across replays. Level-1–4 parity hashes.
- `test_mixed_mode`: one legacy + one v2 alpha on the same symbol both
  run, both produce expected signals, risk engine aggregates correctly.

### 13.6 Performance budget

The refactor MUST NOT regress single-symbol throughput by more than 10%
from pre-refactor baseline on the `--demo` mode benchmark.

Measurement: p50 and p99 latency from `MARKET_EVENT` state entry to `LOG`
state entry, over a 1M-event synthetic stream.

If regression exceeds 10%, the phase is rolled back and optimized before
re-merge.

### 13.7 Test data

- Reference event log: one trading day (2026-03-24) for AAPL, MSFT, NVDA.
  Cached in `tests/fixtures/event_logs/`. Size: ~50 MB compressed.
- Synthetic event logs: generated by `tests/fixtures/synth.py` for
  unit/property tests. No external data dependency.

---

## 14. Monitoring and Observability

### 14.1 New metrics emitted

| Metric | Type | Tags | Purpose |
|---|---|---|---|
| `feelies.sensor.reading.count` | counter | sensor_id, symbol | Throughput |
| `feelies.sensor.reading.latency` | histogram | sensor_id | Per-sensor compute latency |
| `feelies.horizon.tick.emitted` | counter | horizon_seconds, scope | Scheduler health |
| `feelies.feature.snapshot.stale_fraction` | gauge | horizon_seconds | Data health |
| `feelies.signal.regime_gate.state` | gauge | alpha_id | ON/OFF ratio |
| `feelies.composition.completeness` | gauge | horizon_seconds | Universe coverage |
| `feelies.alpha.ic.realized_rolling_30d` | gauge | alpha_id, horizon, regime | Decay detection |
| `feelies.alpha.margin_ratio.realized` | gauge | alpha_id | Cost hurdle tracking |

### 14.2 Alert thresholds (starting values, tunable)

- `stale_fraction > 0.20` for > 5 minutes → WARN
- `completeness < 0.50` for a decision horizon → WARN; skip decision
- `ic.realized_rolling_30d < 0.50 * ic_insample` → WARN (alpha decaying)
- `ic.realized_rolling_30d < 0.25 * ic_insample` for 30 days → CRITICAL
  (alpha retirement candidate)
- `margin_ratio.realized < 1.0` for 5 days → CRITICAL (alpha is losing money net of costs)

### 14.3 Forensics output

The `forensics/multi_horizon_attribution.py` report is the primary input
to the Grok mutation protocol. It MUST produce, per alpha:

- Per-regime IC (on, off, transitional)
- Per-horizon IC (primary, ± one horizon)
- Per-universe-subset IC (market cap deciles, sector, liquidity tier)
- Factor exposures achieved vs target
- P&L decomposition (gross, TC, factor bleed, slippage, net)
- Parity hash deltas across runs (forensic only, flags non-determinism)

Output format: JSON + Markdown summary, written to
`forensics/reports/<date>/<alpha_id>.json`.

---

## 15. Risks and Mitigations

### 15.1 Technical risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Determinism regression in horizon scheduler | Low | Critical | Level-2–4 parity hash CI + property-based tests |
| Performance regression > 10% | Medium | High | Benchmark in Phase 2 gate; profile and optimize before merge |
| UniverseSynchronizer barrier deadlock | Medium | Critical | Timeout-based barrier close (completeness_threshold); no blocking waits |
| Factor neutralizer numerical instability | Medium | High | Pin CVXPY solver + seed; tolerance-based acceptance test |
| Legacy alpha parity break | Low | Critical | Level-1 parity hash CI on every PR; shim isolates legacy path |
| Event bus traffic overload | Low | Medium | Sensors with `throttled_ms` output spec; measure at Phase 2 |
| Memory growth from horizon buffers | Medium | Medium | Bounded ring buffers; max retention = largest horizon × 2 |
| Universe scaling: synchronizer barrier + CVXPY problem grow with universe size | Medium | Medium | Phase 4 ships with 5–10 symbol reference universe. Before scaling to Russell 1000, profile `UniverseSynchronizer` dict growth and `turnover_optimizer` solver wall time. If solver exceeds horizon budget at N=1000, switch to warm-started SCS or partition universe by sector. Treated as separate workstream post-Phase-5. |

### 15.2 Process risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Scope creep into L2 order book | Medium | Medium | This doc explicitly excludes it (§2.4); new proposal required |
| Author rejects design, iterate in Phase 0 | Medium | Low | §17 lists open questions upfront |
| One engineer blocks all phases serially | High (if solo) | High | Phases are independent; can parallelize with 2 engineers |
| Migration of legacy alphas deprioritized | High | Low | Acceptable — legacy support is permanent until explicit removal proposal |

### 15.3 Economic risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Refactored platform still produces no working alpha | Medium | Low | Platform quality ≠ alpha quality; refactor enables but does not guarantee alpha. Grok's discipline is the second lever. |
| New v2 alphas underperform legacy | Medium | Low | Both run in parallel; A/B comparison over 60 days before any deprecation decision |

---

## 16. Rollback Plan

Each phase is reversible.

### 16.1 Reversibility by phase

- **Phase 1**: revert merge commit; events removed from bus; schema 1.1
  loader rejection re-enabled. Zero production impact (no v2 alphas
  loaded yet).
- **Phase 2**: revert merge commit; sensors no longer subscribed;
  horizon scheduler not instantiated. Legacy path unaffected.
- **Phase 3**: revert merge commit; HorizonSignalEngine not instantiated.
  Any v2 SIGNAL alpha authored against this phase must be reverted or
  re-flagged `LEGACY_SIGNAL`.
- **Phase 4**: revert merge commit; composition module not loaded.
  PORTFOLIO alphas refuse to load (this is a loud failure, surfaced
  immediately at boot, not a silent downgrade).
- **Phase 5**: revert docs and migration guide; no runtime impact.

### 16.2 Emergency rollback (production)

If a production issue surfaces post-Phase-5 rollout:

1. Set `enforce_layer_gates: false` and `allow_legacy_signal_alphas: true`
   in `platform.yaml` to soften gates.
2. If issue persists, revert to Phase 4 tag.
3. If Phase 4 still broken, revert to Phase 3 tag.
4. In extremis, revert all phases; legacy path remains intact.

### 16.3 Data rollback

No data migration is required by this refactor. `EventLog` format is
unchanged. Parity hashes from pre-refactor runs are forward-compatible
(Level 1). Phase 2+ replays of pre-refactor event logs produce new hashes
(Levels 2–4); pre-refactor runs do not compute these, so no comparison is
required.

---

## 17. Open Questions — RESOLVED (v0.2)

All ten Phase-0 open questions were resolved by the repo author during
v0.2 review. Each subsection below records the option chosen and any
implementation consequences. The original options and recommendations
are retained for audit.

### Q1 — Is `HorizonScheduler` a new state-machine-owning module, or a service?

**Options:**
- (a) Scheduler is an independent module in `sensors/` that subscribes to
  quote/trade events and emits `HorizonTick`. Clean separation.
- (b) Scheduler is part of the kernel, driven by Micro SM transitions.
  Tighter coupling but aligned with existing state-machine-centric design.

**Recommendation:** (a). The scheduler is a pure function of incoming
event timestamps; it does not own behavior state. Making it a service
keeps the Micro SM's role centered on tick dispatch.

**RESOLVED → (a).** `HorizonScheduler` lives in `sensors/horizon_scheduler.py`
as an independent service. The Micro SM consults it via a `is_boundary()`
guard predicate but does not own its state.

### Q2 — How is `session_open_ns` determined in backtest mode?

**Options:**
- (a) Explicitly set in `platform.yaml` per session.
- (b) Derived from the first market event at `>= 09:30:00 ET` on the
  session date.
- (c) Hard-coded to `09:30:00 ET` of the replay date.

**Recommendation:** (b) with (a) as override. Most flexible; handles
early/late opens deterministically.

**RESOLVED → (b) with (a) as override.** `HorizonScheduler.__init__`
accepts `session_open_ns: int | None`. When None (default), the
scheduler latches the timestamp of the first event whose timestamp is
`>= 09:30:00 ET` on the event's calendar date and uses that as the
anchor for all subsequent boundary computation. When set in
`platform.yaml`, the configured value wins. The latching event is
emitted as a `StateTransition` for provenance.

### Q3 — Should PORTFOLIO alphas consume `HorizonFeatureSnapshot` directly, or only `Signal`?

**Options:**
- (a) Only `Signal`. Clean layer separation; PORTFOLIO alphas are pure
  aggregators.
- (b) Both. Allows PORTFOLIO alphas to use cross-sectional feature
  patterns (e.g., ranking residual momentum across universe).

**Recommendation:** (a) for Phase 4. (b) can be added in a later proposal
if needed; adding it is backward-compatible.

**RESOLVED → (a).** PORTFOLIO alphas in Phase 4 consume only `Signal`
events via `CrossSectionalContext`. Adding direct
`HorizonFeatureSnapshot` consumption is reserved for a future proposal
once a concrete cross-sectional-feature use case is identified.

### Q4 — How does the regime engine handle per-symbol vs universe regime?

**Current state:** unclear from README. The regime engine is
`hmm_3state_fractional`. Does it run per-symbol or universe-wide?

**Required for refactor:** the `RegimeState` event type assumes
per-symbol. If universe-wide, the event has a null symbol. Please confirm
current behavior before Phase 3.

**RESOLVED → per-symbol (confirmed by author).** The existing
`RegimeEngine` Protocol at `services/regime_engine.py:30` is documented
as per-symbol stateful (`"each call to posterior() updates internal
state for that symbol"`), and the existing `RegimeState` event at
`core/events.py:104` carries a `symbol: str` field. The refactor
therefore extends `RegimeState` in place per §5.4 with no semantic
change to the engine. No new universe-scope regime event is introduced.

### Q5 — Should the factor model (FF5 + momentum + STR) use intraday or end-of-day factor returns?

**Options:**
- (a) End-of-day factor loadings, refreshed daily; intraday exposures
  computed against static loadings.
- (b) Intraday factor returns computed on-the-fly from universe.

**Recommendation:** (a). Simpler, deterministic, widely-accepted
approximation at intraday scale. (b) is a separate future proposal.

**RESOLVED → (a).** End-of-day factor loadings refreshed daily from the
chosen provider (Q6). Intraday factor exposures are computed against
static loadings within a session. The `factor_loadings_refresh_seconds`
field in `platform.yaml` (§9) defaults to `3600` but is set to `0`
(static-at-bootstrap) for deterministic backtests.

### Q6 — What is the reference factor model provider?

**Options:**
- (a) Compute factor loadings from Polygon/Massive equity history (rolling 252-day regression).
- (b) Use a third-party (Barra, Axioma — requires license).
- (c) Use Ken French's daily factor returns (free, US-equity standard).

**Recommendation:** (c) for Phase 4. Free, standard, and sufficient for
intraday neutralization. Upgradeable to (b) later.

**RESOLVED → (c).** Ken French daily factor returns + a rolling 252-day
beta regression per symbol against those factors. Loadings cached at
`storage/reference/factor_loadings/<date>.parquet`. The fetcher is a
small adapter in `composition/factor_neutralizer.py`; license-bearing
providers (Barra, Axioma) are deferred to a future proposal.

### Q7 — Should `cvxpy` be a hard dependency or an optional extra?

**Options:**
- (a) Hard dependency in `pyproject.toml`. Simpler; `cvxpy` is
  widely-used and pip-installable.
- (b) Optional extra `[portfolio]`. Smaller default install; explicit
  opt-in.

**Recommendation:** (b). Keeps the default install lean for users who
only run SIGNAL-layer alphas. Clear error at PORTFOLIO-alpha load time
if extra is missing.

**RESOLVED → (b).** `cvxpy` is added under the `[portfolio]` extra in
`pyproject.toml`. The PORTFOLIO loader raises
`MissingOptionalDependencyError` with a one-line install hint
(`pip install feelies[portfolio]`) if a PORTFOLIO alpha is loaded
without the extra installed. SIGNAL-only and SENSOR-only deployments
incur no `cvxpy` dependency.

### Q8 — Is the `grok/` directory's current contents compatible with the new `grok/prompts/hypothesis_reasoning.md`?

**Required:** repo author to confirm. I have not inspected `grok/`
contents. If there are existing prompt artifacts, they may need
reconciliation or deprecation. Phase 5 deliverable depends on this.

**RESOLVED → reconcilable (confirmed by author).** Current `grok/`
contents (`00_ARCHITECTURE.md` through `07_HYPOTHESIS_REASONING_PLAN.md`)
are planning and architecture documentation, not REPL prompt artifacts.
They are retained as-is. Phase 5 creates a new `grok/prompts/`
subdirectory containing:

- `grok/prompts/hypothesis_reasoning.md` — moved from
  `design_docs/hypothesis_reasoning.md`. The move is a single git
  rename; no content change. The `design_docs/` copy is deleted to
  avoid drift.
- `grok/prompts/sensor_catalog.md` — extracted from §8 of the moved
  prompt; canonical sensor reference table.
- `grok/prompts/mutation_protocol.md` — extracted from §5 of the moved
  prompt; the 5-axis mutation protocol.

Existing `grok/07_HYPOTHESIS_REASONING_PLAN.md` is updated with a
one-line pointer to the new `grok/prompts/` location.

### Q9 — Deprecation timeline for LEGACY_SIGNAL?

**Options:**
- (a) Permanent support.
- (b) Deprecation announced at Phase 5; removal after 12 months.
- (c) Deprecation announced at Phase 5; removal after a specific alpha
  count migrates (e.g., when all `alphas/*` are 1.1).

**Recommendation:** (a) initially; revisit after 6 months of operational
experience with 1.1. The cost of maintaining the legacy shim is small
and isolates risk.

**RESOLVED → (a) initially.** Permanent support for `LEGACY_SIGNAL`
through Q4 2026 minimum. Decision to deprecate revisited 6 months
after Phase 5 ships, in a separate proposal that must include the
count of remaining 1.0-schema alphas and a per-alpha migration
estimate.

### Q10 — Parity hash extension: is adding Levels 2–4 acceptable, or does CI budget not tolerate 4× hashing cost?

**Recommendation:** Yes, acceptable. Hashing cost is negligible vs run
time. But author to confirm CI compute budget.

**RESOLVED → accepted.** All four parity hash levels are computed on
every PR. Each level is incremental (SHA-256 over an ordered iterator
of frozen events); aggregate cost is well under 1% of replay wall time
on the reference event log (`tests/fixtures/event_logs/2026-03-24.bin`).
A regression here would be caught by the existing CI duration alert.

---

## 18. Acceptance Criteria

This spec is accepted when ALL of the following are true:

### 18.1 Design acceptance (Phase 0)

- [ ] Repo author has explicitly approved each section of this document
      (or flagged changes required).
- [ ] All 10 open questions in §17 are resolved.
- [ ] The existing design invariants (1–13) are confirmed preserved by
      this spec.
- [ ] Estimated timeline (§10) is deemed realistic by implementing engineer.

### 18.2 Implementation acceptance (after Phase 5)

- [ ] All Phase 1–5 test gates pass.
- [ ] Level-1 parity hash on `alphas/trade_cluster_drift/` is
      bit-identical pre-and-post-refactor.
- [ ] Levels 2–4 parity hash CI checks green on reference v2 alpha.
- [ ] Single-symbol throughput regression ≤ 10% vs pre-refactor baseline.
- [ ] `grok/prompts/hypothesis_reasoning.md` wired to REPL entry.
- [ ] Reference SIGNAL alpha (`pofi_benign_midcap_v1`) runs end-to-end
      with margin_ratio ≥ 1.5 verified at load.
- [ ] Reference PORTFOLIO alpha runs end-to-end with factor exposures
      within tolerance.
- [ ] Documentation updated: README architecture diagram, new
      `alphas/SCHEMA.md`, migration guide, forensics report format.
- [ ] Glossary in `.cursor/rules/platform-invariants.mdc` updated:
      the "feature" entry now distinguishes `FeatureVector` (legacy
      per-tick) from `HorizonFeatureSnapshot` (horizon-bucketed); a
      new "sensor" entry is added (event-time state estimator emitting
      `SensorReading`); a new "horizon" entry is added (decision-cadence
      anchor); the "regime" entry references the per-symbol
      `RegimeState` extension.
- [ ] Existing `grok/07_HYPOTHESIS_REASONING_PLAN.md` updated with a
      pointer to `grok/prompts/`.

### 18.3 Non-regression acceptance

- [ ] All existing unit and integration tests pass.
- [ ] Coverage remains ≥ 80%.
- [ ] `mypy --strict` passes on all new modules.
- [ ] `ruff check` passes with no new warnings.

---

## 19. Invariant Compliance Audit

This section is the explicit confirmation required by §18.1 that every
invariant in `.cursor/rules/platform-invariants.mdc` is preserved (or
strengthened) by the refactor. The table is normative — any future
revision that weakens a column-3 entry must justify it in the change
log.

| # | Invariant | How the refactor preserves or strengthens it | Status |
|---|---|---|---|
| **1** | Structural mechanism required | `mechanism:` and `structural_actor:` are mandatory YAML fields for SIGNAL/PORTFOLIO (§8.2). Gates G2/G3 in `alpha/layer_validator.py` reject load if they are absent or unparseable. The Grok protocol's Step 1 (§4 of `hypothesis_reasoning.md`) refuses to proceed without naming an actor. | **STRENGTHENED** |
| **2** | Falsifiability before testing | `falsification_criteria:` field extended (§8.2) with three sub-blocks: `statistical`, `structural_invalidators`, `regime_shift_invalidators`. Gates G10/G11 enforce that the criterion is mechanism-tied, not P&L-tied. | **STRENGTHENED** |
| **3** | Evidence over intuition | `cost_arithmetic.edge_source` field (§8.2) requires a citation (empirical backtest path, paper reference, or theoretical derivation). "Guess" is an explicit refusal condition in the Grok protocol (§4 Step 5). Existing promotion gates (paper → live) are unchanged. | **PRESERVED** |
| **4** | Decay is the default | `forensics/multi_horizon_attribution.py` (§6.10) emits per-alpha rolling-30d realized IC; `monitoring/horizon_metrics.py` (§6.9) alerts at `< 50%` and CRITICAL at `< 25%` of in-sample IC. Existing DECAYING/RETIRED status transitions in `research/hypothesis_status.py` remain authoritative. | **STRENGTHENED** |
| **5** | Deterministic replay | §12.1–§12.4: proof sketches for `HorizonTick`, `HorizonFeatureSnapshot`, `CrossSectionalContext` determinism. 4-level parity hash CI (Fills / Signals / HorizonFeatureSnapshots / SensorReadings) replaces the existing 1-level check. Non-determinism risk inventory in §12.5 enumerates and mitigates every known source. | **STRENGTHENED** |
| **6** | Causality enforced | Gate G13 (`alpha/layer_validator.py`) statically checks that feature definitions reference only events with `timestamp ≤ T`. `HorizonAggregator` (§6.3) only consumes `SensorReading` events whose timestamp is `≤ HorizonTick.timestamp_ns`; reading the buffer at boundary close cannot see the future by construction. `HorizonTick.timestamp_ns` carries the *boundary* timestamp, not the *triggering event's* timestamp (§7.4) — this is the load-bearing detail. | **PRESERVED** |
| **7** | Event-driven, typed schemas | All five new event types (§5) are frozen `dataclass(kw_only=True)` instances inheriting `Event`, matching the existing convention. No untyped dict messages cross any layer boundary. The synchronous in-process bus is unchanged. | **PRESERVED** |
| **8** | Layer separation | The refactor is *itself* an extension of layer separation: the previously-monolithic `features/`+`signals/` per-tick path is split into four typed layers (sensors → features → signals → composition), each with its own protocol ABC, registry, and event contract. Gates G4 (sensor catalog), G14 (data scope), and the typed-registry DAG resolver (`alpha/registry.py` extension, §6.6) prevent cross-layer leakage. | **STRENGTHENED** |
| **9** | Backtest/live parity | `ExecutionBackend` is **not touched** (§2.4 non-goal, §11.4 contract). `HorizonScheduler` derives boundaries from event-time, not wall-clock — so the same event log produces the same horizon-tick stream in backtest and replay. Live mode's `HorizonScheduler` consumes the same wall-clock-stamped events from `MassiveLiveFeed` and produces boundaries with identical semantics. The mode-swap discipline is preserved. | **PRESERVED** |
| **10** | Clock abstraction | `HorizonScheduler.__init__` accepts an injected `Clock` (§7.4 reference signature). No `datetime.now()` introduced anywhere in the new modules. Sensors operate on `event.timestamp_ns`, never wall-clock. Audit gate: `ruff` rule pinning the `datetime.now()` ban must include `src/feelies/sensors/`, `src/feelies/composition/` in its scope after Phase 4. | **PRESERVED** |
| **11** | Fail-safe default | (a) `UniverseSynchronizer`: when `completeness < composition_completeness_threshold` (§9, default 0.80), the decision is *skipped*, not extrapolated — the per-symbol fallback is "no position change," which is reduce-or-hold, never increase. (b) Regime gate: default state is **OFF**; the gate must affirmatively evaluate ON to permit a signal — defaulting to no-trade rather than no-filter. (c) Sensor warm-up: features depending on a not-yet-warm sensor emit `warm=False`, suppressing the signal — same convention as legacy `FeatureVector`. (d) CVXPY infeasibility in `turnover_optimizer`: returns the previous holdings (zero turnover), not the unconstrained solution. | **STRENGTHENED** |
| **12** | Transaction cost realism | `cost_arithmetic` block is mandatory for SIGNAL/PORTFOLIO YAML (§8.2). Gate G7 (`alpha/layer_validator.py`) refuses load if `margin_ratio < 1.5`. The existing 1.5× cost / 2× latency stress tests (per the testing-validation skill) are unchanged and still gate promotion. Forensics now tracks `realized_margin_ratio` and alerts at CRITICAL if `< 1.0` for 5 days (§14.2). | **STRENGTHENED** (was advisory; now mechanically enforced at load) |
| **13** | Full provenance, versioned and auditable | (a) `SensorReading` carries `sensor_id` + `sensor_version` + `provenance` (§5.2). (b) `HorizonFeatureSnapshot` carries `source_sensors: dict[feature_id, list[sensor_id]]` (§5.3). (c) `Signal` carries `consumed_features: tuple[str, ...]` (§5.5). (d) `source_layer` field added to base `Event` class (Appendix A). (e) Alpha YAML `version` (semver) + `schema_version` + sensor `version` + Python class version are now distinguished namespaces (§6.3 rename rationale). (f) 4-level parity hash gives a per-event-class audit trail. (g) Mutation predecessors moved to `alphas/_deprecated/` with full git history. | **STRENGTHENED** |

### 19.1 Net assessment

- **8 of 13 invariants STRENGTHENED**, **5 PRESERVED**, **0 weakened**.
- The two invariants whose enforcement moves from "advisory" to
  "mechanical at load time" are **Invariant 12** (cost arithmetic) and
  **Invariant 1** (structural mechanism). These are the two failure
  modes most commonly cited in the post-trade-forensics skill as
  precursors to alpha decay; making them load-time-blocking is the most
  significant epistemological tightening in this refactor.
- The single load-bearing detail for **Invariant 5** is the
  `HorizonTick.timestamp_ns` boundary-anchored emission rule (§7.4).
  This is the property that the determinism CI gates (Levels 2–4 parity
  hashes) most directly check. If a future refactor proposes any
  alternate emission semantics here, it must re-derive the §12.1 proof
  sketch.

### 19.2 What this audit does not cover

- It does not assert that **alphas authored under v1.1** will be
  causally sound — only that the platform mechanically enforces the
  preconditions for soundness. The Grok protocol (§4 Steps 1–7) and the
  human reviewer remain the upstream filter.
- It does not assert that the refactor improves backtest realism.
  Realism is a property of the cost/fill model + execution backend,
  which is unchanged.
- It does not address economic invariants beyond Invariant 12 (e.g.,
  capacity, regime stability across calendar regimes). These are
  out-of-scope here and tracked in the post-trade-forensics and
  microstructure-alpha skills.

---

## Appendix A — Event Type Hierarchy

```
Event  (existing base)
├── MarketEvent
│   ├── NBBOQuote          (existing)
│   └── Trade              (existing)
├── SensorReading          NEW (Layer 1)
├── HorizonTick            NEW (cross-cutting; emitted by scheduler)
├── HorizonFeatureSnapshot NEW    (Layer 2 input)
├── FeatureVector          (existing; preserved for LEGACY_SIGNAL path)
├── RegimeState            EXTEND (per-symbol; +horizon_seconds, +stability, +regime_engine_id)
├── Signal                 EXTEND (+layer, +horizon_seconds, +regime_gate_state, +consumed_features)
├── CrossSectionalContext  NEW (Layer 3 input)
├── SizedPositionIntent    NEW (Layer 3 output)
├── OrderIntent            (existing; also produced by Layer 3 via risk)
├── OrderAck | Fill | Cancel | Reject | Expire
│                          (existing order lifecycle)
├── RiskAlert              (existing)
├── StateTransition        (existing; every SM emits)
└── HealthEvent            (existing)
```

All new types include the standard header `(timestamp_ns, correlation_id,
sequence, source_layer)`. `source_layer` is a new field on the base event
class, documented in §5 but added in Phase 1. Defaults to `'UNKNOWN'` for
backward compat with existing producers.

---

## Appendix B — File-Level Change Inventory

Summary of every file touched, organized by phase. Format:
`path | action | lines (approx)`.

### Phase 1

```
src/feelies/core/events.py                        | EXTEND  | +120
src/feelies/alpha/loader.py                       | EXTEND  | +80
src/feelies/alpha/layer_validator.py              | CREATE  | +200
alphas/SCHEMA.md                                  | EXTEND  | +150
tests/core/test_new_events.py                     | CREATE  | +150
tests/alpha/test_schema_1_1_loading.py            | CREATE  | +100
```

### Phase 2

```
src/feelies/sensors/__init__.py                   | CREATE  | +20
src/feelies/sensors/protocol.py                   | CREATE  | +80
src/feelies/sensors/registry.py                   | CREATE  | +150
src/feelies/sensors/horizon_scheduler.py          | CREATE  | +180
src/feelies/sensors/impl/ofi_ewma.py              | CREATE  | +120
src/feelies/sensors/impl/micro_price.py           | CREATE  | +80
src/feelies/sensors/impl/vpin_50bucket.py         | CREATE  | +150
src/feelies/sensors/impl/kyle_lambda_60s.py       | CREATE  | +130
src/feelies/sensors/impl/spread_z_30d.py          | CREATE  | +100
src/feelies/sensors/impl/realized_vol_30s.py      | CREATE  | +100
src/feelies/sensors/impl/quote_hazard_rate.py     | CREATE  | +150
src/feelies/sensors/impl/trade_through_rate.py    | CREATE  | +110
src/feelies/sensors/impl/quote_replenish_asymmetry.py | CREATE | +140
src/feelies/features/aggregator.py                | CREATE  | +200
src/feelies/features/legacy_shim.py               | CREATE  | +120
src/feelies/kernel/micro_sm.py                    | EXTEND  | +150
src/feelies/bootstrap.py                          | EXTEND  | +80
tests/sensors/test_*.py                           | CREATE  | +800
tests/features/test_aggregator.py                 | CREATE  | +200
tests/kernel/test_micro_sm_extended.py            | CREATE  | +250
tests/determinism/test_horizon_tick_replay.py     | CREATE  | +150
tests/determinism/test_sensor_reading_replay.py   | CREATE  | +150
```

### Phase 3

```
src/feelies/signals/engine.py                     | EXTEND  | +200
src/feelies/signals/regime_gate.py                | CREATE  | +250
src/feelies/alpha/layer_validator.py              | EXTEND  | +150
alphas/pofi_benign_midcap_v1/*.yaml               | CREATE  | reference alpha
tests/signals/test_regime_gate_dsl.py             | CREATE  | +200
tests/signals/test_signal_engine_v2.py            | CREATE  | +250
tests/determinism/test_signal_replay.py           | CREATE  | +150
tests/alpha/test_cost_arithmetic_gate.py          | CREATE  | +100
```

### Phase 4

```
src/feelies/composition/__init__.py               | CREATE  | +20
src/feelies/composition/protocol.py               | CREATE  | +100
src/feelies/composition/synchronizer.py           | CREATE  | +200
src/feelies/composition/cross_sectional.py        | CREATE  | +180
src/feelies/composition/factor_neutralizer.py     | CREATE  | +250
src/feelies/composition/sector_matcher.py         | CREATE  | +120
src/feelies/composition/turnover_optimizer.py     | CREATE  | +300
src/feelies/portfolio/cross_sectional_tracker.py  | CREATE  | +150
src/feelies/monitoring/horizon_metrics.py         | CREATE  | +200
src/feelies/forensics/multi_horizon_attribution.py| CREATE  | +400
alphas/pofi_xsect_v1/*.yaml                       | CREATE  | reference alpha
pyproject.toml                                    | EXTEND  | +5 (cvxpy extra)
tests/composition/test_*.py                       | CREATE  | +1000
tests/determinism/test_xsect_context_replay.py    | CREATE  | +200
```

### Phase 5

```
README.md                                         | EXTEND  | +100
docs/migration/schema_1_0_to_1_1.md               | CREATE  | +300
grok/prompts/hypothesis_reasoning.md              | RENAME  | from design_docs/hypothesis_reasoning.md
design_docs/hypothesis_reasoning.md               | DELETE  | rename target
grok/prompts/sensor_catalog.md                    | CREATE  | +200 (extracted from §8 of moved prompt)
grok/prompts/mutation_protocol.md                 | CREATE  | +300 (extracted from §5 of moved prompt)
grok/07_HYPOTHESIS_REASONING_PLAN.md              | EXTEND  | +20 (pointer to grok/prompts/)
.cursor/rules/platform-invariants.mdc             | EXTEND  | +30 (glossary update per §18.2)
```

### Summary

- Approximately 28 new files, 6 extended files.
- Approximately 8,500 new lines (code + tests + docs).
- Zero file deletions.
- Zero renames of existing files (all changes additive).

---

## End of Specification

> **For the reviewer:** if you disagree with any section, please note the
> section number and the specific concern. I will revise and re-submit
> rather than proceed on assumption. No implementation begins until this
> document is approved.
>
> **For the implementer:** treat §6, §7, §11, §12, and §18 as the
> contract. Everything else is rationale that you may deviate from with
> justification. The four sections above are normative.
