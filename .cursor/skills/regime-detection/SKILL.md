---
name: regime-detection
description: >
  Platform-level regime detection + hazard-spike service for the
  feelies platform. Owns the `RegimeEngine` protocol, the
  `RegimeState` event, the state taxonomy, the
  `RegimeHazardDetector` (and the `RegimeHazardSpike` event consumed
  by `HazardExitController`), and the writer/reader contract. Use
  when designing regime-aware components, integrating regime
  posteriors into risk or sizing, extending the state taxonomy,
  swapping HMM implementations, or reasoning about hazard-detection
  semantics, idempotency, or consumer contracts.
---

# Regime Detection — Platform Service

The regime engine is a shared, platform-level service that classifies
market microstructure state per symbol on every tick. It produces a
posterior probability vector over a discrete set of regime states,
consumed read-only by risk, sizing, the `RegimeGate` DSL bindings on
SIGNAL alphas, and the hazard detector.

The orchestrator is the **sole writer** to the engine. All other
consumers are read-only.

The Phase 3.1 amendment adds `RegimeHazardDetector`
(`services/regime_hazard_detector.py`), a pure function over two
consecutive `RegimeState` events that emits `RegimeHazardSpike`
events when a regime flip is imminent. The spike is consumed by
`HazardExitController` (risk-engine skill) for hazard-driven
position exits.

## Core Invariants

Inherits Inv-5 (deterministic replay), Inv-7 (event-driven typed
schemas), Inv-10 (clock abstraction), Inv-11 (fail-safe default).
Additionally:

1. **Single-writer** — only the orchestrator calls `posterior()`,
   once per tick at micro-state M2 (STATE_UPDATE). No other component
   may call `posterior()`.

2. **Idempotency** — `posterior()` caches per `(symbol, sequence)`
   (the per-event monotonic sequence number, not wall-clock).  If
   called multiple times for the same symbol and sequence the
   Bayesian update is applied only once; subsequent calls return the
   cached result.  Prevents double-update corruption.  Note: an
   earlier draft of this skill said `(symbol, timestamp_ns)` — the
   implementation has always keyed on sequence (see
   ``HMM3StateFractional.posterior``).

3. **Read-only consumers** — risk engine, position sizer, regime-gate
   DSL bindings, and forensic consumers access regime state via
   `current_state()` only. Alpha namespaces receive
   `regime_posteriors` (bound to `current_state`) and
   `regime_state_names` — never the engine itself.

4. **Fail-safe default** — when no regime data is available (engine
   absent, symbol never updated, or empty posteriors), all consumers
   default to neutral scaling (`1.0×`). Regime state never amplifies
   exposure beyond baseline (Inv-11).

5. **Determinism** — same quote sequence produces identical posterior
   sequences. No randomness, no external I/O in `posterior()`.

6. **Hazard purity** — `RegimeHazardDetector.detect(prev, curr)` is
   a pure function of two consecutive `RegimeState` events; it
   introduces no new state and no new clock dependency, so replay is
   bit-identical (Inv-5; verifiable via the Level-5 hazard-parity
   hash).

---

## `RegimeEngine` Protocol

`services/regime_engine.py`:

```python
class RegimeEngine(Protocol):
    @property
    def state_names(self) -> Sequence[str]: ...
    @property
    def n_states(self) -> int: ...

    def posterior(self, quote: NBBOQuote) -> list[float]: ...
    def current_state(self, symbol: str) -> list[float] | None: ...
    def reset(self, symbol: str) -> None: ...
    def checkpoint(self) -> bytes: ...
    def restore(self, data: bytes) -> None: ...
```

| Method | Mutates state | Caller |
|--------|--------------|--------|
| `posterior(quote)` | Yes (Bayesian update) | Orchestrator only (M2) |
| `current_state(symbol)` | No (read cache) | Risk engine, position sizer, regime-gate, forensics |
| `reset(symbol)` | Yes (clear cache) | Orchestrator (recovery), tests |
| `checkpoint()` | No (serialize all per-symbol state to an opaque blob) | Recovery / persistence |
| `restore(data)` | Yes (replace all per-symbol state; atomic — rolls back or cold-starts on failure) | Recovery |
| `state_names` | No | Any |
| `n_states` | No | Any |

---

## Default State Taxonomy

`HMM3StateFractional` (`services/regime_engine.py`) defines three
canonical states:

| Index | Name | Interpretation | Typical risk response |
|-------|------|----------------|----------------------|
| 0 | `compression_clustering` | Low vol, tight spreads | Reduced edge; size down |
| 1 | `normal` | Typical conditions | Baseline sizing |
| 2 | `vol_breakout` | High vol, wide spreads | Elevated risk; halve size |

State names are **not hardcoded** in consumers. Risk engine and
position sizer look up names from `state_names` and apply
configurable scaling factors per name. Both consumers handle unknown
names by defaulting to the **minimum** configured scale (fail-safe,
Inv-11): `BasicRiskEngine._regime_scaling()` uses
`_regime_scale_default` (the min of its scale map), and
`BudgetBasedSizer._get_regime_factor()` uses
`min(self._regime_factors.values())`. The resulting EV is then
clamped with `min(EV, 1.0)`.

### Extensibility

New state taxonomies are added by:

1. Implementing `RegimeEngine` with the desired states
2. Registering via `register_engine(name, engine_cls)`
3. Selecting in `PlatformConfig.regime_engine` by name
4. Updating consumer scaling-factor maps (risk config, sizer config)

The platform does not require exactly 3 states. Any `n_states ≥ 2`
is valid. Today, `_ENGINE_REGISTRY` in `services/regime_engine.py`
exposes two names (`hmm_3state_fractional`, `hmm_3state_spread_filter`)
both backed by `HMM3StateFractional`; alternative `RegimeEngine`
implementations can be added via `register_engine(name, engine_cls)`.

---

## Writer / Reader Contract

```
Tick pipeline:
  M0 → M1 (quote logged + bus published)
       → M2: orchestrator calls regime_engine.posterior(quote)
              → publishes RegimeState event on the bus
       → SENSOR_UPDATE: sensors run; regime read-only available
       → HORIZON_AGGREGATE: snapshot built
       → SIGNAL_GATE: HorizonSignal.evaluate sees RegimeState (read-only)
                      regime_gate DSL evaluates against regime posteriors
       → CROSS_SECTIONAL: composition reads regime via depends_on edges
       → M5: risk engine calls current_state(symbol) in check_signal /
              check_sized_intent
              position sizer calls current_state(symbol)
       → M6: risk engine calls current_state(symbol) in check_order
```

The single-writer guarantee means `current_state()` at any downstream
sub-state always returns the posteriors computed at M2 for the
current tick.

---

## `RegimeState` Event

`core/events.py`:

```python
@dataclass(frozen=True, kw_only=True)
class RegimeState(Event):
    symbol: str
    engine_name: str
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_state: int
    dominant_name: str
    horizon_seconds: int = 0
    stability: float = 1.0
    posterior_entropy_nats: float = 0.0
```

The three defaulted fields are additive: `horizon_seconds` is `0`
for the per-tick snapshot (positive for horizon-anchored snapshots),
`stability` is the 0..1 stability of the dominant state over recent
posteriors (default `1.0` is a no-op for legacy producers), and
`posterior_entropy_nats` is the Shannon entropy of the posterior
categorical (`0.0` when unused).

Published by the orchestrator at M2 after `posterior()` returns.

Consumers:

- Risk engine — `current_state(symbol)` → scaling factor
- Position sizer — `current_state(symbol)` → capital scalar
- Regime-gate DSL — bindings `P(<state_name>)`, `dominant`,
  `entropy` (bound to `posterior_entropy_nats`)
- `RegimeHazardDetector` — pairs of consecutive `RegimeState` events
- Post-trade forensics — regime-stability audit

---

## Hazard Detection (Phase 3.1)

`services/regime_hazard_detector.py` produces `RegimeHazardSpike`
events from pairs of consecutive `RegimeState` events.

### `RegimeHazardSpike` Event

```python
@dataclass(frozen=True, kw_only=True)
class RegimeHazardSpike(Event):
    symbol: str
    engine_name: str
    departing_state: str
    departing_posterior_prev: float   # P(departing) on the prior tick
    departing_posterior_now: float    # P(departing) on this tick
    incoming_state: str | None        # may be None on a tie of runners-up
    hazard_score: float               # clip01((p_prev − p_now)/max(p_prev,ε))
```

The event carries the raw `(p_prev, p_now)` pair (not a single
`posterior_drop`) plus the normalized `hazard_score` consumers
threshold on.  An earlier draft of this skill described a single
`posterior_drop` field — see ``feelies.core.events.RegimeHazardSpike``
for the authoritative schema.

### Detection Logic

`RegimeHazardDetector.detect(prev, curr)` flags a spike when:

- Both `RegimeState` events agree on `engine_name` and `symbol`
- The dominant state in `prev` shows a significant posterior drop in
  `curr` (a "departure episode")
- A regime flip is therefore imminent

Suppression at the **detector** layer is keyed on
``(symbol, engine_name, departing_state)``: at most one spike per
departure episode on a given regime channel; re-arms only when the
suppressed departing state becomes dominant *again* after a flip (a
clean round-trip) or its posterior recovers to or above the
``1.0 − hysteresis_threshold`` floor (see ``_rearm_suppression`` in
``services/regime_hazard_detector.py``).  A second,
**controller-side** suppression key (``(strategy_id, symbol,
reason)``) lives in :class:`HazardExitController` and prevents
re-firing an exit for the same open position.  The two are distinct
keys at distinct layers — don't conflate them.

### Pure-Function Property

`detect()` is a pure function of two `RegimeState` events. No new
state is introduced beyond the suppression key cache (which is itself
deterministic given the input sequence). Replay is bit-identical
(Inv-5; locked by the L5 hazard-spike parity test
`tests/determinism/test_regime_hazard_replay.py`, and the L6
`RegimeState` parity test `test_regime_state_replay.py`).

### What `hazard_score` is — and is not

`hazard_score` is the **normalized one-tick relative decay** of the
departing state's posterior, **not** a survival-analysis hazard
rate λ(t) = f(t) / S(t).  The exact formula is:

```
hazard_score = clip01( (p_prev − p_now) / max(p_prev, ε) ),  ε = 1e-12
```

so a drop from 0.95 → 0.45 scores ≈ 0.526 regardless of whether the
two ticks were 1 ms or 30 s apart.  This is a deliberate design
choice — the detector is purely a function of the two `RegimeState`
events on the channel (Inv-5 replay determinism) and carries no
clock dependency.  But it has three operational consequences that
consumers should understand:

1. **Not time-normalized.**  Two slow decays over different quote
   gaps produce identical scores.  A score threshold therefore
   gates a per-tick step, not a per-second event-rate — calibrate
   `hazard_score_threshold` against your tick rate, not your
   wall-clock horizon.
2. **Not a probability of regime-end.**  It does not estimate
   P(flip in next Δt).  Use the (separate) dominance flip /
   `1.0 − hysteresis_threshold` floor checks the detector already
   does for that semantic.
3. **Bounded by `p_prev`.**  When the departing state is already
   near zero (`p_prev < ε`), the divisor is floored at ε and the
   score is clamped at 1.0 by the `clip01`; degenerate "decay from
   already-near-zero" cases produce a small bounded score, not a
   blow-up.

If you need a real survival-analysis hazard rate (events per unit
wall-clock time) for a downstream model, compute it externally from
the published `RegimeHazardSpike` stream — the detector intentionally
does not emit one.

### Wiring

`HazardExitController` (risk-engine skill) consumes
`RegimeHazardSpike` events and emits `OrderRequest.reason ∈
{"HAZARD_SPIKE", "HARD_EXIT_AGE"}` to flatten open positions when:

- `hazard_score >= hazard_score_threshold` (per-alpha; default 0.85)
- The position has been open at least `min_age_seconds` (default 30)

Wired behind alpha-level `hazard_exit.enabled: true` (default off,
v0.2-compatible).

Hazard-driven exits are **exit-only**: entries on a stale regime are
forbidden by Inv-11. The spike never closes a position by itself —
it surfaces a microstructure signal that the controller may act on.

---

## Consumer Contract

### Risk Engine

Reads `current_state(symbol)` in `_regime_scaling()`.  Computes an
**expected value over the posterior** — `Σ pᵢ · scaleᵢ` — *not* a
hard argmax-name lookup (an earlier draft of this doc described
argmax; the implementation has always smoothed via EV to avoid
limit thrash on diffuse posteriors).  Unknown state names default to
the smallest configured scale (fail-safe).  Missing data → `1.0×`.

Audit P1 R-1 also enforces Inv-11 at the value level: the returned
factor is clamped to ``min(EV, 1.0)`` so a mis-configured scale map
can only reduce exposure, never amplify above the baseline.

### Position Sizer

`BudgetBasedSizer._get_regime_factor()` uses the same EV-over-
posteriors smoothing as the risk engine (`Σ pᵢ · scaleᵢ`) and the
same `min(EV, 1.0)` Inv-11 clamp.  Missing data defaults to `1.0×`.
The two consumers operate **in series** — the sizer proposes a
quantity scaled by EV, the risk engine then caps the *limit* by EV
— so the scaling never compounds.

### Regime-Gate DSL

`signals/regime_gate.py` parses the alpha YAML's `regime_gate:`
block into a safe AST-evaluated boolean DSL. Bindings drawn from
`RegimeState`:

- `P(<state_name>)` — posterior probability of the named state
- `dominant` — name of the dominant state
- `entropy` — `posterior_entropy_nats` of the current `RegimeState`

Plus sensor/feature bindings, built by
`HorizonSignalEngine._build_bindings`
(`signals/horizon_engine.py`): the primary source is
`HorizonFeatureSnapshot.values` (horizon-boundary aggregates,
including `SensorPassthroughFeature` rows such as `spread_z_30d`);
the live sensor cache is a fallback only, applied via `setdefault`
for identifiers absent from the snapshot:

- `<sensor_id>` — raw value
- `<sensor_id>_zscore` — z-score
- `<sensor_id>_percentile` — percentile

The gate is the purity boundary: never reads untyped state, never
imports, never mutates the snapshot.

### Forensic Consumers

Post-trade-forensics reads `RegimeState` events from the audit log
to compute the `RegimeBucket` axis of `MultiHorizonAttributor` and
to audit regime classification accuracy over time.

---

## Event Interface

| Event | Direction | Notes |
|-------|-----------|-------|
| `NBBOQuote` | In (from ingestion) | Consumed by `posterior()` |
| `RegimeState` | Out (to bus) | Published after each `posterior()` call |
| `RegimeHazardSpike` | Out (to bus) | Published from pairs of consecutive `RegimeState` events |

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Engine not configured | `regime_engine is None` | All consumers default to `1.0×` (Inv-11) |
| Symbol never updated | `current_state()` returns `None` | Consumers default to `1.0×` |
| Empty posteriors list | `len(posteriors) == 0` | Treat as `None` |
| NaN/inf in posteriors | Checked inside `posterior()` after the Bayesian update | Log WARNING and substitute a uniform prior in place; no `reset()` call |
| Engine raises in `posterior()` | Caught by orchestrator at M2 | Tick degrades; cached state preserved |
| Hazard detector receives mismatched engine_name | `_validate_pair` raises `HazardDetectorContractError` | Tick degrades to DEGRADED; investigate engine swap |

---

## Integration Points

| Dependency | Interface | Direction |
|------------|-----------|-----------|
| Orchestrator | `posterior()` at M2 | Provides |
| Risk engine | `current_state()` | Provides |
| Position sizer | `current_state()` | Provides |
| Regime-gate DSL | `current_state`, `state_names` | Provides |
| `HazardExitController` | `RegimeHazardSpike` | Provides (via the hazard detector) |
| Event bus | `RegimeState`, `RegimeHazardSpike` published | Emits |
| Platform config | `regime_engine: str` selects implementation | Consumes |
| Engine registry | `register_engine`, `get_regime_engine` | Provides |
| Post-trade forensics | `RegimeState` for `RegimeBucket` attribution | Consumed by forensics |
| Testing & Validation | L5 hazard-parity hash; idempotency property tests | Provides |
