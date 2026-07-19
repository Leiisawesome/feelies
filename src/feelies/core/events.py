"""Typed event schemas for all inter-layer communication (invariant 7).

Every event crossing a layer boundary must use one of these schemas.
No untyped messages.  No polling.  All events are frozen dataclasses
— immutable after creation, safe to share without copying.

Three-layer architecture additions (§5, §20.3 of docs/three_layer_architecture.md):
  - ``source_layer`` on the base ``Event`` — full-provenance tag (Inv-13).
  - Layer-1 ``SensorReading`` (event-time state estimator output).
  - ``HorizonTick`` cross-cutting scheduler event.
  - Layer-2 ``HorizonFeatureSnapshot`` (horizon-bucketed feature aggregate).
  - Layer-3 ``CrossSectionalContext`` and ``SizedPositionIntent``.
  - v0.3 ``TrendMechanism`` taxonomy + ``RegimeHazardSpike`` exit event.

All new types are strictly additive.  Existing events keep their schema;
existing producers/consumers are unaffected (Inv-5 parity, §11.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Literal


# ── Base ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class Event:
    """Base event.  Every event carries provenance metadata.

    ``source_layer`` is an additive Phase-1 field (Appendix A of
    three_layer_architecture.md) that tags every emitted event with the
    layer that produced it.  Default ``"UNKNOWN"`` preserves construction
    for every existing producer that does not yet pass the tag.

    Immutability is **shallow** (audit P2-3): ``frozen=True`` blocks
    rebinding a field, but events whose fields hold mutable containers
    (e.g. ``Signal.metadata``, ``RiskVerdict.constraints``,
    ``MetricEvent.tags``, ``HorizonFeatureSnapshot.values/warm/stale``,
    ``SizedPositionIntent.target_positions``) can still have those
    containers mutated in place, and those events are not hashable.
    Treat every event as read-only once published — do not mutate a
    container reached through an event you received off the bus; build a
    fresh event instead.  Tuple-valued fields are deeply immutable and the
    preferred shape for new schemas.
    """

    timestamp_ns: int
    correlation_id: str
    sequence: int
    source_layer: str = "UNKNOWN"


# ── Market Data Events ──────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class NBBOQuote(Event):
    """L1 NBBO quote update from Massive (formerly Polygon.io).

    Captures all fields from both WebSocket (ev=Q) and REST (/v3/quotes)
    wire formats.  New optional fields use defaults so existing code is
    unaffected.

    ``received_ns`` is sourced from the normalizer's injected ``Clock``:
    per-frame wall-clock receipt time on live (WallClock), and the
    SimulatedClock's static value on historical REST replays (the clock
    does not advance during batch ingest, so every record in a batch
    shares one value).  Backtests therefore cannot derive a meaningful
    ingest latency from this field.
    """

    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    bid_exchange: int = 0
    ask_exchange: int = 0
    exchange_timestamp_ns: int
    conditions: tuple[int, ...] = ()
    indicators: tuple[int, ...] = ()
    sequence_number: int = 0
    tape: int = 0
    participant_timestamp_ns: int | None = None
    trf_timestamp_ns: int | None = None
    received_ns: int | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class Trade(Event):
    """Trade print from exchange.

    Captures all fields from both WebSocket (ev=T) and REST (/v3/trades)
    wire formats.  New optional fields use defaults so existing code is
    unaffected.
    """

    symbol: str
    price: Decimal
    size: int
    exchange: int = 0
    trade_id: str = ""
    exchange_timestamp_ns: int
    conditions: tuple[int, ...] = ()
    decimal_size: str | None = None
    sequence_number: int = 0
    tape: int = 0
    trf_id: int | None = None
    trf_timestamp_ns: int | None = None
    participant_timestamp_ns: int | None = None
    correction: int | None = None
    received_ns: int | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class SymbolHalted(Event):
    """Forensic marker for a per-symbol trading halt / resume (BT-5).

    Emitted by the orchestrator when a symbol's tape signals an LULD /
    regulatory halt (``halted=True``) or a resume (``halted=False``).
    Carries no control semantics itself — fill suppression is enforced
    separately by the orchestrator's halt gate — but lets post-trade
    forensics reconstruct which fills were suppressed and why.

    ``blackout_until_ns`` is populated only on resume (``halted=False``):
    new *entry* fills remain suppressed until this event-time deadline so
    the reopening-auction print can stabilise.  ``0`` on a halt-on event.
    """

    symbol: str
    halted: bool
    reason: str = ""
    blackout_until_ns: int = 0


# ── Feature Events ──────────────────────────────────────────────────────
#
# Workstream D.2 PR-2b-iv deleted the per-tick ``FeatureVector`` event
# along with the legacy feature-engine plumbing.  The current canonical
# feature event is :class:`HorizonFeatureSnapshot` (Phase-2 horizon-bucketed
# snapshot emitted by :class:`HorizonAggregator` when a HorizonTick boundary
# is crossed); see ``§5.6`` of the migration guide and the ``feature``
# glossary entry in ``platform-invariants.mdc`` for the full timeline.


# ── Regime Events ───────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class RegimeState(Event):
    """Regime detection output published once per tick at M2.

    Emitted by the orchestrator after updating the platform-level
    RegimeEngine.  Consumed by dashboards, risk engine (via cached
    engine state), and logged for provenance.

    Additive Phase-1 fields per §5.4:
      ``horizon_seconds`` — 0 for the per-tick snapshot (legacy), positive
      for horizon-anchored snapshots emitted by Layer-2 consumers in
      Phase 3+.
      ``stability`` — 0..1 stability of the dominant state over recent
      posteriors.  Default 1.0 is a no-op for legacy producers.
      ``posterior_entropy_nats`` — Shannon entropy (natural log base) of
      the posterior categorical; ``0`` when unused (legacy producers).
      ``calibrated`` — whether the producing engine's emission parameters
      were fit from data.  ``False`` means the posteriors were computed
      from placeholder/default emissions and are not trustworthy for
      ``P(<state>)`` gating; the regime gate treats ``P()``/``dominant``/
      ``entropy`` bindings as *unavailable* in that case so entry gates
      fail safe to OFF (audit P0-1, Inv-11).  Defaults to ``True`` so
      legacy producers — and the L6 parity hash, which does not serialize
      this field — are unaffected.
      ``discriminability`` — the engine's calibration-time min pairwise
      emission separation ``d`` (audit R-1).  Near ``0`` means the states
      are statistically indistinguishable (degenerate calibration on a
      tight/stable spread) so ``P(state)`` is noise; consumers fail
      regime-gates safe to OFF when it is below a configured floor.
      Orthogonal to ``calibrated`` (placeholder emissions score high here
      but are caught by ``calibrated=False``).  Defaults to ``+inf`` so
      legacy producers are always treated as fully discriminative, and the
      L6 parity hash does not serialize it.

    When ``posteriors`` tie, producers pick the lowest ``dominant_state``
    index (deterministic replay).
    """

    symbol: str
    engine_name: str
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_state: int
    dominant_name: str
    horizon_seconds: int = 0
    stability: float = 1.0
    posterior_entropy_nats: float = 0.0
    calibrated: bool = True
    discriminability: float = float("inf")


# ── Signal Events ───────────────────────────────────────────────────────


class SignalDirection(Enum):
    LONG = auto()
    SHORT = auto()
    FLAT = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class Signal(Event):
    """Signal evaluation output — pure function of features (no side effects).

    Phase-1.1 / v0.3 fields (§5.5, §20.3.2).  Workstream D.2 PR-2b-ii
    narrowed ``layer`` to ``Literal["SIGNAL", "PORTFOLIO"]`` and made
    ``"SIGNAL"`` the default — the historical ``"LEGACY_SIGNAL"`` value
    was retired together with the per-tick composite engines.  Defaults
    preserve horizon-anchored Phase-3 producers exactly:

      ``layer`` — ``"SIGNAL"`` for horizon-gated Layer-2 outputs
                 (default; emitted by :class:`HorizonSignalEngine`);
                 ``"PORTFOLIO"`` for cross-sectional Layer-3 outputs
                 (Phase-4 PORTFOLIO alphas via
                 :class:`CrossSectionalEngine`).
      ``horizon_seconds`` — 0 if unspecified, positive for
                            horizon-anchored producers.
      ``regime_gate_state`` — ``"N/A"`` when no gate applies;
                              ``"ON"`` / ``"OFF"`` for regime-gated
                              horizon signals.
      ``consumed_features`` — tuple of feature_ids consulted during
                              evaluation (empty when unspecified).
      ``trend_mechanism`` — None when unspecified; one of the 5
                            ``TrendMechanism`` enum members for v0.3
                            mechanism-bound signals (Phase 3.1+).
      ``expected_half_life_seconds`` — 0 for unspecified;
                                        positive for v0.3 mechanism-bound
                                        signals (drives decay weighting
                                        and hard-exit-age in Phase 4.1).
    """

    symbol: str
    strategy_id: str
    direction: SignalDirection
    strength: float
    edge_estimate_bps: float
    disclosed_cost_total_bps: float = 0.0
    # B5: combined exit + entry round-trip cost (bps) estimated by the
    # orchestrator's reversal edge guard in ``_execute_reverse``.  Additive
    # and backward-compatible: all non-reversal producers leave it at 0.0,
    # so it does not affect parity hashes by its presence alone.
    reversal_cost_estimate_bps: float = 0.0
    disclosed_margin_ratio: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: Literal["SIGNAL", "PORTFOLIO"] = "SIGNAL"
    horizon_seconds: int = 0
    regime_gate_state: Literal["ON", "OFF", "N/A"] = "N/A"
    consumed_features: tuple[str, ...] = ()
    trend_mechanism: TrendMechanism | None = None
    expected_half_life_seconds: int = 0


# ── Risk Events ─────────────────────────────────────────────────────────


class RiskAction(Enum):
    ALLOW = auto()
    SCALE_DOWN = auto()
    REJECT = auto()
    FORCE_FLATTEN = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class RiskVerdict(Event):
    """Risk engine decision on a proposed action."""

    symbol: str
    action: RiskAction
    reason: str
    scaling_factor: float = 1.0
    constraints: dict[str, float] = field(default_factory=dict)


# ── Order Events ────────────────────────────────────────────────────────


class Side(Enum):
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()


class OrderAckStatus(Enum):
    """Typed acknowledgement statuses from the execution backend.

    Maps 1:1 to the order lifecycle states that a broker can report.
    Using an enum (not a raw string) ensures type safety at the layer
    boundary and prevents silent drops from typos or case mismatches
    (invariant 7, hard rule 2).
    """

    ACKNOWLEDGED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderRequest(Event):
    """Request to place an order — output of ORDER_DECISION micro-state.

    ``reason`` is a v0.3-additive free-text tag (default ``""``) used by
    Phase-4-finalize emitters to distinguish ordinary entry/exit orders
    from hazard-driven exits (``"HAZARD_SPIKE"`` / ``"HARD_EXIT_AGE"``)
    and from Phase-4 PORTFOLIO-path orders (``"PORTFOLIO"``).  Present
    on every emitted ``OrderRequest`` so forensics / parity baselines
    can split the order stream by lineage without re-deriving it from
    ``correlation_id``.
    """

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None = None
    strategy_id: str = ""
    # True for short-entry sells.  HTB fee applies on the fill day only;
    # multi-day accrual over the holding period is a position-store
    # concern and is documented as a remaining gap in cost_model.py.
    is_short: bool = False
    # BT-8: closing-auction (MOC) order — backtest routers queue until the
    # official close print instead of filling on the continuous book.
    is_moc: bool = False
    g12_disclosed_cost_total_bps: float = 0.0
    reason: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderAck(Event):
    """Acknowledgement of order state change from execution backend.

    In backtest mode this is emitted by the fill simulator.
    In live mode this is emitted by the broker gateway.
    The pipeline does not branch on which source produced it (invariant 9).

    ``sequence`` is the ack event's own sequence within the producer's
    OrderAck stream. ``request_sequence`` is an additive back-reference
    to the originating OrderRequest sequence when the producer has it.
    """

    order_id: str
    symbol: str
    status: OrderAckStatus
    filled_quantity: int = 0
    fill_price: Decimal | None = None
    fees: Decimal = Decimal("0")
    cost_bps: Decimal = Decimal("0")
    reason: str = ""
    request_sequence: int | None = None


# ── Position Events ─────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class PositionUpdate(Event):
    """Position change after fill reconciliation.

    ``realized_pnl`` is **cumulative** gross (price-based) PnL for
    this symbol.  ``cumulative_fees`` is the running total of all
    transaction fees.  Net PnL = realized_pnl - cumulative_fees.
    Contrast with ``TradeRecord.realized_pnl``, which is per-trade
    differential.
    """

    symbol: str
    quantity: int
    avg_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    cumulative_fees: Decimal = Decimal("0")
    cost_bps: Decimal = Decimal("0")


# ── System Events ───────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class StateTransition(Event):
    """Logged whenever any state machine transitions.  No silent transitions."""

    machine_name: str
    from_state: str
    to_state: str
    trigger: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Metric Events ───────────────────────────────────────────────────────


class MetricType(Enum):
    COUNTER = auto()
    GAUGE = auto()
    HISTOGRAM = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class MetricEvent(Event):
    """Telemetry emitted by any layer — collected by the monitoring layer."""

    layer: str
    name: str
    value: float
    metric_type: MetricType
    tags: dict[str, str] = field(default_factory=dict)


# ── Alert Events ────────────────────────────────────────────────────


class AlertSeverity(Enum):
    """Alert severity levels mapped to response SLAs.

    INFO      — async review, log only
    WARNING   — < 15 min response, log + dashboard
    CRITICAL  — < 1 min response, activates safety controls
    EMERGENCY — immediate automated response + notification
    """

    INFO = auto()
    WARNING = auto()
    CRITICAL = auto()
    EMERGENCY = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class Alert(Event):
    """Typed alert emitted by any layer, routed by the central alert manager.

    Critical and Emergency alerts activate safety controls autonomously.
    Human review follows but does not gate the safety response (invariant 11).
    """

    severity: AlertSeverity
    layer: str
    alert_name: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


# ── Safety Events ───────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class KillSwitchActivation(Event):
    """Emitted when the kill switch is activated.

    Kill switch is irreversible without human re-authorization.
    This event is published on the bus so all layers can react
    (cancel orders, freeze state, cease submissions).
    """

    reason: str
    activated_by: str


# ── Three-Layer Architecture (v0.2) ─────────────────────────────────────
#
# Per docs/three_layer_architecture.md §5 and Appendix A.  All
# events below are additive Phase-1 contracts; no producer is wired in
# Phase 1 (Phase 2 ships the sensor framework, Phase 3 ships the
# horizon signal engine, Phase 4 ships the composition layer).
#
# These types are defined for forward compatibility so that downstream
# code can import them, type-check against them, and so that the YAML
# loader can validate references to them without importing experimental
# modules.


# ── v0.3 TrendMechanism Taxonomy (§20.2 / §20.3.2) ──────────────────────


class TrendMechanism(Enum):
    """Closed taxonomy of trend-formation mechanisms (§20.2).

    A v0.3 mechanism-bound signal must declare exactly one of these
    families.  The taxonomy is closed by design: adding a new family is
    a deliberate platform-level change, not an alpha-author decision.

    - KYLE_INFO            — informed-trader price-impact (Kyle 1985)
    - INVENTORY            — market-maker inventory drift
    - HAWKES_SELF_EXCITE   — order-flow self-excitation cluster
    - LIQUIDITY_STRESS     — depth withdrawal / spread blow-out
    - SCHEDULED_FLOW       — known time-of-day flow window
    """

    KYLE_INFO = auto()
    INVENTORY = auto()
    HAWKES_SELF_EXCITE = auto()
    LIQUIDITY_STRESS = auto()
    SCHEDULED_FLOW = auto()


# Mechanisms that are **exit-only**: an alpha bound to one of these must never
# open or increase exposure — it may only de-leverage (FLAT) or have its
# positions flattened.  Single source of truth, consumed by the composition
# layer (cross-sectional ranking zeroes their scores) AND the SIGNAL-layer
# runtime guardrail (``HorizonSignalEngine`` suppresses any non-FLAT signal
# they emit, closing the gap where G16's static analysis abstains on a
# dynamically-computed direction — §20.6.1 rule 7).
EXIT_ONLY_MECHANISMS: frozenset[TrendMechanism] = frozenset(
    {
        TrendMechanism.LIQUIDITY_STRESS,
    }
)


# ── v0.3 RegimeHazardSpike (§20.3.1) ────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class RegimeHazardSpike(Event):
    """Hazard-rate spike emitted when the dominant regime is about to flip.

    Pure function of two consecutive ``RegimeState`` events; introduces no
    new state and no new clock dependency (§20.3.1, replayable bit-
    identically).  Suppression is per
    ``(symbol, engine_name, departing_state)`` transition.
    """

    symbol: str
    engine_name: str
    departing_state: str
    departing_posterior_prev: float
    departing_posterior_now: float
    incoming_state: str | None
    hazard_score: float


# ── Supporting types for new events ─────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class SensorProvenance:
    """Inputs a sensor consumed to produce a ``SensorReading`` (§5.2).

    ``input_sensor_ids`` lists upstream sensors (empty for raw-event
    sensors).  ``input_event_kinds`` lists event-type names consumed
    (e.g. ``("NBBOQuote",)`` or ``("Trade",)``).  Both are immutable
    tuples so the provenance record is safely shareable.
    """

    input_sensor_ids: tuple[str, ...] = ()
    input_event_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class TargetPosition:
    """Per-symbol target produced by a Layer-3 portfolio alpha (§5.7).

    ``target_usd`` is the signed dollar exposure (positive = long,
    negative = short).  ``urgency`` is a 0..1 hint to the risk/execution
    layer about how aggressively to close any gap to target.
    """

    symbol: str
    target_usd: float
    urgency: float = 0.5


# ── v0.2 New Events ─────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class HorizonTick(Event):
    """Deterministic event-time scheduler tick (§5.1).

    Emitted by the (Phase-2) ``HorizonScheduler`` at boundaries
    ``session_open_ns + k * horizon_seconds * 1e9`` for k = 1, 2, ....
    Drives Layer-2 aggregation and Layer-3 synchronization.

    ``scope`` is ``"SYMBOL"`` for per-symbol horizons (in which case
    ``symbol`` must be set) or ``"UNIVERSE"`` for cross-sectional
    horizons (``symbol`` is ``None``).

    ``timestamp_ns`` is the event time that caused the scheduler to
    emit the tick.  ``boundary_timestamp_ns`` is the exact horizon
    boundary being finalized; legacy hand-built ticks leave it at ``0``
    and consumers fall back to ``timestamp_ns``.
    """

    horizon_seconds: int
    boundary_index: int
    session_id: str
    scope: Literal["SYMBOL", "UNIVERSE"]
    boundary_timestamp_ns: int = 0
    symbol: str | None = None
    # ENG-1: the EXACT nominal boundary time
    # ``session_open_ns + boundary_index * horizon_seconds * 1e9``.  Distinct
    # from ``timestamp_ns`` (the *triggering* event time, which on sparse tapes
    # lands at or after the boundary).  Lets consumers anchor to a regular grid
    # (IC labels, forensics, cross-sectional sync) instead of the jittery
    # trigger time.  Default 0 = "unset" (legacy / direct test construction);
    # the scheduler always sets it.
    boundary_ts_ns: int = 0

    @property
    def asof_timestamp_ns(self) -> int:
        """Exact event-time boundary used for feature as-of math."""
        return self.boundary_timestamp_ns or self.timestamp_ns


@dataclass(frozen=True, kw_only=True, slots=True)
class SensorReading(Event):
    """Layer-1 sensor output emitted on every tick (§5.2).

    ``value`` is a scalar or a tuple of floats depending on the sensor
    contract.  ``confidence`` defaults to 1.0 (sensor declares full
    confidence).  ``warm`` is False until the sensor's ``min_history``
    is satisfied.  Consumers must skip non-warm readings.

    ``parent_correlation_id`` carries the ``correlation_id`` of the
    originating market-data event (``NBBOQuote`` / ``Trade``) that
    triggered this reading.  Set by ``SensorRegistry._stamp``;
    restores the audit-spine chain required by A-DATA-04.
    """

    symbol: str
    sensor_id: str
    sensor_version: str
    value: float | tuple[float, ...]
    confidence: float = 1.0
    warm: bool = True
    provenance: SensorProvenance = field(default_factory=SensorProvenance)
    parent_correlation_id: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class HorizonFeatureSnapshot(Event):
    """Layer-2 horizon-bucketed feature aggregate (§5.3).

    Emitted by ``features/aggregator.py`` (Phase 2) on every
    ``HorizonTick``.  Per-feature ``warm`` and ``stale`` flags carry the
    aggregator's state so downstream signal evaluation can suppress on
    either condition without re-reading sensor state.

    Workstream D.2 PR-2b-iv deleted the legacy per-tick ``FeatureVector``
    event; ``HorizonFeatureSnapshot`` is now the sole feature-event type.

    ``values`` contains only *warm* features; cold features are absent
    (not 0.0) so consumers that key on presence correctly distinguish
    "not yet warm" from "computed zero" (S2 / audit).
    ``warm`` and ``stale`` include ALL registered features regardless
    of warmth, so the engine can detect active-mode snapshots even when
    all features are temporarily cold.

    ``parent_correlation_id`` carries the ``correlation_id`` of the
    ``HorizonTick`` that triggered this snapshot, restoring the
    audit-spine chain (S4 / A-DATA-04).

    ``feature_versions`` records the ``feature_version`` string for each
    feature_id present in this snapshot.  Combined with ``source_sensors``
    (which records ``input_sensor_ids``) this closes the Inv-13 provenance
    gap: a consumer reading an archived snapshot can reconstruct exactly
    which feature *version* produced each value, even when the same
    ``feature_id`` is registered at multiple horizons with different
    versions.  Empty dict in passive mode (no features).
    """

    symbol: str
    horizon_seconds: int
    boundary_index: int
    # ENG-1: exact nominal boundary time, carried verbatim from the triggering
    # ``HorizonTick.boundary_ts_ns``.  ``timestamp_ns`` remains the trigger
    # time; this is the regular-grid anchor for IC labels / forensics.
    boundary_ts_ns: int = 0
    values: dict[str, float] = field(default_factory=dict)
    warm: dict[str, bool] = field(default_factory=dict)
    stale: dict[str, bool] = field(default_factory=dict)
    source_sensors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    feature_versions: dict[str, str] = field(default_factory=dict)
    parent_correlation_id: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class CrossSectionalContext(Event):
    """Universe-wide barrier-synced snapshot for portfolio alphas (§5.6).

    Emitted by ``composition/synchronizer.py`` (Phase 4) when every
    symbol in the universe has produced a ``HorizonFeatureSnapshot`` at
    the current decision-horizon boundary (or has been declared
    permanently absent for this boundary).  ``signals_by_symbol`` and
    ``snapshots_by_symbol`` use ``None`` for symbols whose feature
    snapshot was stale or not warm at the barrier time.
    """

    horizon_seconds: int
    boundary_index: int
    universe: tuple[str, ...]
    signals_by_symbol: dict[str, "Signal | None"] = field(default_factory=dict)
    # Per-symbol map strategy_id -> latest feeder Signal at the portfolio barrier.
    # Populated when :class:`~feelies.composition.synchronizer.UniverseSynchronizer`
    # is wired with ``upstream_strategy_ids`` so Layer-3 can aggregate SIGNAL
    # alphas whose ``horizon_seconds`` differ from the PORTFOLIO decision horizon.
    signals_by_strategy_by_symbol: dict[str, dict[str, "Signal | None"]] = field(
        default_factory=dict,
    )
    snapshots_by_symbol: dict[str, "HorizonFeatureSnapshot | None"] = field(default_factory=dict)
    completeness: float = 0.0


@dataclass(frozen=True, kw_only=True, slots=True)
class SizedPositionIntent(Event):
    """Layer-3 portfolio-alpha output (§5.7), consumed by the risk engine.

    Replaces the per-symbol ``OrderRequest`` upstream path for portfolio
    alphas.  Standalone SIGNAL alphas still reach the risk engine via the
    per-symbol ``OrderRequest`` bus path; the risk engine handles both.

    ``mechanism_breakdown`` (v0.3 §20.3.3) reports the gross-exposure
    share of each consumed ``TrendMechanism`` family.  Defaults to ``{}``
    for v0.2 portfolio alphas.
    """

    strategy_id: str
    layer: Literal["PORTFOLIO"] = "PORTFOLIO"
    horizon_seconds: int = 0
    target_positions: dict[str, TargetPosition] = field(default_factory=dict)
    factor_exposures: dict[str, float] = field(default_factory=dict)
    expected_turnover_usd: float = 0.0
    expected_gross_exposure_usd: float = 0.0
    mechanism_breakdown: dict[TrendMechanism, float] = field(default_factory=dict)
    # Per-symbol disclosed one-way ``cost_total_bps`` carried over from
    # the consumed SIGNAL events for each symbol in ``target_positions``.
    # Populated by :class:`CompositionEngine` from
    # :attr:`CrossSectionalContext.signals_by_symbol`; the risk engine
    # stamps the corresponding entry onto each emitted PORTFOLIO
    # ``OrderRequest.g12_disclosed_cost_total_bps`` so the post-fill G12
    # cost-vs-disclosure stress alert (orchestrator §M9) fires for the
    # PORTFOLIO path the same way it does for SIGNAL-driven orders.
    # Empty default keeps v0.2 portfolio alphas bit-identical until the
    # composition engine starts populating it (Inv-A).
    disclosed_cost_total_bps_by_symbol: dict[str, float] = field(
        default_factory=dict,
    )
    # Content-addressable digest over the canonical *inputs* that produced
    # ``target_positions`` (consumed signals, current positions, decision
    # parameters).  Provides in-band provenance so two structurally-equal
    # intents can be distinguished when they were derived from different
    # inputs, and so forensics can detect silent input drift without
    # re-deriving the decision (Inv-13).  Empty string ``""`` denotes
    # "not computed" (degenerate intents, custom alphas that opt out) and
    # is the v0.2-compatible default so existing replay hashes — which do
    # not serialise this field — stay bit-identical (Inv-5).
    decision_basis_hash: str = ""
    # Optimizer terminal status for the solve that produced this intent
    # (e.g. ``"CLOSED_FORM"``, ``"optimal"``, ``"ECOS_FAILED_FALLBACK"``,
    # or a non-optimal solver status).  Surfaced so the monitoring layer
    # can alert on solver degradation without reaching into the optimizer
    # (audit P1-8).  Empty string ``""`` denotes "not recorded" (degenerate
    # intents, custom alphas) and is the v0.2-compatible default — like
    # ``decision_basis_hash`` it is not serialised into the locked replay
    # hashes, so determinism is unaffected (Inv-5).
    solver_status: str = ""
