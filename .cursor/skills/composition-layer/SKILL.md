---
name: composition-layer
description: >
  Layer-3 (PORTFOLIO) cross-sectional construction pipeline for the
  feelies platform. Owns the `PortfolioAlpha` protocol, the
  `UniverseSynchronizer` fan-in, the `CrossSectionalRanker` (with
  optional decay weighting), `FactorNeutralizer`, `SectorMatcher`,
  the cvxpy-based `TurnoverOptimizer`, and the `CompositionEngine`
  that emits `SizedPositionIntent`. Use when authoring PORTFOLIO
  alphas, designing cross-sectional construction, debugging
  mechanism-cap enforcement, factor-loading ingestion, or the
  decision-basis hash.
---

# Composition Layer — Layer 3 Cross-Sectional Construction

The Layer-3 PORTFOLIO layer is **cross-sectional**: a portfolio alpha
sees the entire declared universe at once and is responsible for
inter-symbol weight construction (factor neutralization, sector
matching, turnover optimization, mechanism capping). It bypasses the
per-symbol `IntentTranslator` and instead emits a typed
`SizedPositionIntent` per `(alpha_id, horizon_seconds, boundary_index)`,
which the risk engine decomposes into per-leg `OrderRequest`s with
**per-leg veto** semantics (Inv-11).

`PortfolioAlpha` instances are loaded from `*.alpha.yaml` files with
`layer: PORTFOLIO`. The PORTFOLIO layer is gated on
`AlphaRegistry.has_portfolio_alphas()` at bootstrap — if no PORTFOLIO
alpha is registered, no composition components are constructed.

## Core Invariants

Inherits Inv-5 (deterministic replay), Inv-6 (causality), Inv-11
(fail-safe), Inv-13 (provenance). Additionally:

1. **Cross-sectional contemporaneity** — `CrossSectionalContext`
   carries only `Signal` events from the same horizon boundary; no
   look-ahead, no stale-window mixing.
2. **Mechanism-cap enforcement** — every `SizedPositionIntent`
   carries a typed `mechanism_breakdown: dict[TrendMechanism, float]`
   and respects per-family `max_share_of_gross` declared on the
   alpha YAML.
3. **Decision-basis hash** — every emitted `SizedPositionIntent`
   carries a `decision_basis_hash` over the input signals + factor
   loadings + parameter snapshot, so two replays produce identical
   hashes.
4. **Per-leg veto on risk** — the risk engine evaluates each leg of
   the intent independently; a single vetoed leg never aborts the
   intent.
5. **Replay byte-identical emission order** — `UniverseSynchronizer`
   sorts `(boundary_ts_ns, alpha_id, horizon_seconds)` so the
   downstream engine receives intents in a stable order.

---

## Pipeline

```
Signal[symbol_i] (Layer 2, multiple symbols, same boundary)
  → UniverseSynchronizer fan-in
    → CrossSectionalContext(alpha_id, horizon_seconds, boundary_index,
                            signals, completeness, boundary_ts_ns)
      → CompositionEngine.evaluate(context)
        → PortfolioAlpha.compute_weights(context, params, factor_loadings, regime)
          → CrossSectionalRanker (raw scores)
            → FactorNeutralizer (factor exposures)
              → SectorMatcher (long/short sector pairing)
                → TurnoverOptimizer (cvxpy QP, optional)
                  → mechanism-cap enforcement
                    → SizedPositionIntent(target_positions, mechanism_breakdown,
                                          decision_basis_hash, correlation_id)
                      → bus.publish(intent) at CROSS_SECTIONAL sub-state
                        → RiskEngine.check_sized_intent (per-leg veto)
                          → per-leg OrderRequest with reason="PORTFOLIO"
```

Implementation files: `feelies.composition.{protocol, synchronizer,
engine, cross_sectional, factor_neutralizer, sector_matcher,
turnover_optimizer}`.

---

## `PortfolioAlpha` Protocol

```python
class PortfolioAlpha(Protocol):
    @property
    def alpha_id(self) -> str: ...
    @property
    def horizon_seconds(self) -> int: ...
    @property
    def universe(self) -> tuple[str, ...]: ...
    @property
    def depends_on_signals(self) -> tuple[str, ...]: ...

    def compute_weights(
        self,
        context: CrossSectionalContext,
        params: Mapping[str, Any],
        factor_loadings: FactorLoadings,
        regime: RegimeState,
    ) -> dict[str, TargetPosition]: ...
```

`compute_weights` is a **pure function**. The
`CrossSectionalContext` carries the most-recent `Signal` per
(symbol, alpha_id) within the alpha's declared `universe` for the
current `boundary_index`. `TargetPosition` is a value object with
signed `qty` and source `Signal.trend_mechanism` for downstream
mechanism-breakdown computation.

`G10` (PORTFOLIO universe presence) and `G11` (factor-neutralization
disclosure) gate alpha load.

---

## `UniverseSynchronizer`

`composition/synchronizer.py` publishes one `CrossSectionalContext`
per `(alpha_id, horizon_seconds, boundary_index)` triple, fanning in
the most recent `Signal` per (symbol, alpha_id) within the alpha's
declared `universe`.

```python
@dataclass(frozen=True, kw_only=True)
class CrossSectionalContext(Event):
    alpha_id: str
    horizon_seconds: int
    boundary_index: int
    boundary_ts_ns: int
    signals: dict[str, Signal]      # symbol → most recent Signal
    completeness: float             # fraction of universe with non-stale signal
```

### Completeness Gate

Portfolio alphas may opt-out of low-completeness boundaries via
`composition_completeness_threshold` in `platform.yaml` (default
`0.7`). Below threshold, the synchronizer drops the
`CrossSectionalContext` rather than emitting a degraded intent.

### Emission Order

Sorted by `(boundary_ts_ns, alpha_id, horizon_seconds)` before
emission so cross-sectional construction is replay-byte-identical
(Inv-5; locked by L3 + L3-orders parity tests).

---

## `CrossSectionalRanker`

`composition/cross_sectional.py` ranks symbols by raw alpha score
from `Signal.strength × sign(direction) × edge_estimate_bps`, then:

1. **Optional decay weighting** (Phase 4.1) — when
   `decay_weighting_enabled: true` in the PORTFOLIO alpha's
   `parameters:` block, multiplies each symbol's raw score by
   `exp(-Δt / hl)` where `Δt = boundary_ts_ns - signal.timestamp_ns`
   and `hl = signal.expected_half_life_seconds × 1e9`. Clamped below
   by `decay_floor` (default `1e-6`). Decay weighting is **additive** —
   it does not change structural ranking semantics, only the relative
   emphasis of fresh vs stale signals. Produces a different
   `decision_basis_hash` from decay-OFF baseline (verified by the
   Level-3 cross-check test). Platform budget: ≤ 5 % wall-clock
   regression.
2. **Standardisation** — robust z-score across the universe.
3. **Mechanism-cap enforcement** — when any `TrendMechanism` family
   would exceed its declared `max_share_of_gross`, scales that
   family's contribution proportionally before re-normalizing the
   gross. G16 PORTFOLIO rule 8 enforces the cap declaration at load
   time; the ranker enforces realisation at emission time.

Output: a `RankResult` carrying ranked alphas and the
realised `mechanism_breakdown: dict[TrendMechanism, float]`.

---

## `FactorNeutralizer`

`composition/factor_neutralizer.py` consumes a `FactorLoadings`
artifact (Parquet, content-addressed hash, `factor_loadings_max_age_seconds`
guard at bootstrap) and projects the ranked weights onto the
factor-neutral subspace. Factors typically include: market beta,
size, value, momentum, sector dummies.

`MissingFactorLoadingsError` is raised at construction if the alpha
declares a factor not present in the loadings file. G11 gates the
disclosure of which factors the alpha intends to neutralize.

The platform refuses to load factor loadings older than
`factor_loadings_max_age_seconds` (default 24 h). Stale loadings →
bootstrap failure (Inv-11).

---

## `SectorMatcher`

`composition/sector_matcher.py` enforces long-short sector pairing
when `sector_match: true` is declared. Symbols are bucketed by
sector code; per-sector net exposure is constrained.

---

## `TurnoverOptimizer` (Optional)

`composition/turnover_optimizer.py` is a cvxpy-based QP that
penalizes turnover against the previous boundary's intent. Activated
by the `[portfolio]` install extra (`pip install -e ".[portfolio]"`,
which pulls `cvxpy`, `ecos`, `pyarrow`).

Without the extra, PORTFOLIO alphas still load and run; only the
turnover-optimisation step is disabled (passthrough). Detected via
`MissingOptionalDependencyError`.

`OptimizerResult` carries optimised weights and a status code; a
non-OPTIMAL solver result downgrades to passthrough with an `Alert`
emission rather than blocking the intent.

---

## `CompositionEngine`

`composition/engine.py` is the entry point at the `CROSS_SECTIONAL`
sub-state:

```python
class CompositionEngine:
    def evaluate(self, context: CrossSectionalContext) -> SizedPositionIntent | None: ...
```

Responsibilities:

1. Locate the registered `PortfolioAlpha` for `context.alpha_id`
2. Drop if `context.completeness < composition_completeness_threshold`
3. Call `PortfolioAlpha.compute_weights(...)`
4. Run the construction pipeline (rank → neutralize → sector → optimize → cap)
5. Compute `decision_basis_hash` over all inputs + parameters
6. Emit `SizedPositionIntent` with sorted target positions and
   `mechanism_breakdown`
7. Publish on the bus → `RiskEngine.check_sized_intent` consumes it

`SizedPositionIntent.correlation_id = f"intent:{alpha_id}:{boundary_index}"`
provides forensic lineage; per-leg `OrderRequest`s inherit this so
post-trade attribution can recover the intent.

---

## `SizedPositionIntent`

```python
@dataclass(frozen=True, kw_only=True)
class SizedPositionIntent(Event):
    alpha_id: str
    horizon_seconds: int
    boundary_index: int
    target_positions: dict[str, int]                 # symbol → signed qty
    mechanism_breakdown: dict[TrendMechanism, float] # gross-share per family
    decision_basis_hash: str                          # SHA-256 over inputs + params
    completeness: float
```

The `mechanism_breakdown` is the audit trail for G16 caps and the
input axis to `MultiHorizonAttributor` for per-mechanism PnL
decomposition. **Mechanism concentration** (the realised gross-share
of any single family) drives the post-trade crowding diagnostic.

---

## Layer Gates Specific to PORTFOLIO

| Gate | Check |
|------|-------|
| G10 | `universe:` is non-empty and ⊆ `platform.yaml: symbols` |
| G11 | `factor_neutralization:` block declared with factors present in loadings |
| G12 | `cost_arithmetic:` declared (margin_ratio ≥ 1.5; reconciles ±5%) |
| G14 | `depends_on_signals:` references registered SIGNAL alpha IDs |
| G16 (PORTFOLIO rule 8) | Every consumed mechanism family declares `max_share_of_gross`; sum ≤ 1.0; family whitelist matches upstream `Signal.trend_mechanism` values |

---

## Determinism (Inv-5)

| Test | Locks |
|------|-------|
| `tests/determinism/test_sized_intent_replay.py` | L3 — ordered `SizedPositionIntent` stream byte-identical |
| `tests/determinism/test_portfolio_order_replay.py` | L3-orders — per-leg `OrderRequest` from PORTFOLIO byte-identical (lex-sorted by symbol) |
| Decay-on/off cross-check | `decision_basis_hash` differs; structural ranking unchanged |

---

## Configuration (`platform.yaml`)

```yaml
composition_completeness_threshold: 0.7   # drop CrossSectionalContext below this
composition_max_universe_size: 50         # PORTFOLIO universe cap (G10)
factor_loadings_max_age_seconds: 86400    # stale → bootstrap fail
```

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Stale factor loadings | `factor_loadings_max_age_seconds` exceeded at bootstrap | Bootstrap fail (Inv-11) |
| Cvxpy unavailable + turnover declared | `MissingOptionalDependencyError` at engine construction | Bootstrap fail unless `[portfolio]` extra installed |
| Solver non-OPTIMAL | `OptimizerResult.status` | Downgrade to passthrough; emit `Alert` |
| Mechanism cap unreachable | G16 load-time check | Reject alpha load |
| Universe symbol absent from `platform.yaml: symbols` | G10 | Reject alpha load |
| Low completeness | `context.completeness < threshold` | Drop intent; log; do not emit |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Microstructure Alpha | `Signal` events (with `trend_mechanism`, `expected_half_life_seconds`) — input |
| Risk Engine | `check_sized_intent` per-leg veto — output consumer |
| System Architect | `Clock`, `EventBus`, `CROSS_SECTIONAL` sub-state, `CrossSectionalContext` event |
| Storage Layer | Reference factor loadings (Parquet, content-addressed) |
| Testing & Validation | L3 + L3-orders parity hashes; decay-on/off cross-check |
| Post-Trade Forensics | `mechanism_breakdown` for crowding diagnostics; `MultiHorizonAttributor` per-mechanism axis |

The composition layer is the only path that constructs cross-sectional
weights. Per-symbol SIGNAL alphas never produce sized positions —
they emit `Signal` events that PORTFOLIO alphas optionally consume.
