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

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Literal

# Pinned-code-per-log rule. Log-level invalidation is event_schema_hash
# (disk_event_cache._compute_schema_hash); this integer is the envelope pin.
SCHEMA_VERSION: int = 1

# Quantity unit lives in Field.metadata["unit"], not as a dataclass field, so
# name and type are unchanged and event_schema_hash does not move. This token
# marks a disputed dimension: it is a declaration, not an absence.
UNIT_UNDETERMINED: str = "undetermined"


# ── Base ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class Event:
    """Base event.  Every event carries provenance metadata.

    ``source_layer`` names the emitting layer. Default ``"UNKNOWN"`` supports
    producers that do not set it.

    ``schema_version`` is the envelope compatibility pin (``SCHEMA_VERSION``).
    Payload fields such as ``SensorReading.sensor_version`` and
    ``HorizonFeatureSnapshot.feature_versions`` are not this pin.

    Numeric-field units are declared in ``Field.metadata['unit']`` (see
    ``declared_unit``). They are not dataclass fields.

    Immutability is shallow: ``frozen=True`` blocks
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

    timestamp_ns: int = field(metadata={"unit": "ns"})
    correlation_id: str
    sequence: int = field(metadata={"unit": "1"})
    source_layer: str = "UNKNOWN"
    schema_version: int = field(default=SCHEMA_VERSION, metadata={"unit": "1"})


def declared_unit(cls: type[Event], field_name: str) -> str | None:
    """Return the declared unit for ``field_name``, or ``None`` if undeclared."""
    raw = cls.__dataclass_fields__[field_name].metadata.get("unit")
    return raw if isinstance(raw, str) else None


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
    bid: Decimal = field(metadata={"unit": "USD"})
    ask: Decimal = field(metadata={"unit": "USD"})
    bid_size: int = field(metadata={"unit": UNIT_UNDETERMINED})
    ask_size: int = field(metadata={"unit": UNIT_UNDETERMINED})
    bid_exchange: int = field(default=0, metadata={"unit": "1"})
    ask_exchange: int = field(default=0, metadata={"unit": "1"})
    exchange_timestamp_ns: int = field(metadata={"unit": "ns"})
    conditions: tuple[int, ...] = field(default=(), metadata={"unit": "1"})
    indicators: tuple[int, ...] = field(default=(), metadata={"unit": "1"})
    sequence_number: int = field(default=0, metadata={"unit": "1"})
    tape: int = field(default=0, metadata={"unit": "1"})
    participant_timestamp_ns: int | None = field(default=None, metadata={"unit": "ns"})
    trf_timestamp_ns: int | None = field(default=None, metadata={"unit": "ns"})
    received_ns: int | None = field(default=None, metadata={"unit": "ns"})


@dataclass(frozen=True, kw_only=True, slots=True)
class Trade(Event):
    """Trade print from exchange.

    Captures all fields from both WebSocket (ev=T) and REST (/v3/trades)
    wire formats.  New optional fields use defaults so existing code is
    unaffected.
    """

    symbol: str
    price: Decimal = field(metadata={"unit": "USD"})
    size: int = field(metadata={"unit": "share"})
    exchange: int = field(default=0, metadata={"unit": "1"})
    trade_id: str = ""
    exchange_timestamp_ns: int = field(metadata={"unit": "ns"})
    conditions: tuple[int, ...] = field(default=(), metadata={"unit": "1"})
    decimal_size: str | None = None
    sequence_number: int = field(default=0, metadata={"unit": "1"})
    tape: int = field(default=0, metadata={"unit": "1"})
    trf_id: int | None = field(default=None, metadata={"unit": "1"})
    trf_timestamp_ns: int | None = field(default=None, metadata={"unit": "ns"})
    participant_timestamp_ns: int | None = field(default=None, metadata={"unit": "ns"})
    correction: int | None = field(default=None, metadata={"unit": "1"})
    received_ns: int | None = field(default=None, metadata={"unit": "ns"})


@dataclass(frozen=True, kw_only=True, slots=True)
class SymbolHalted(Event):
    """Forensic marker for a per-symbol trading halt or resume.

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
    blackout_until_ns: int = field(default=0, metadata={"unit": "ns"})


# ── Feature Events ──────────────────────────────────────────────────────
# Canonical feature event: :class:`HorizonFeatureSnapshot` (below).


# ── Regime Events ───────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class RegimeState(Event):
    """Regime output published after each platform-level update.

    Uncalibrated or poorly discriminative posteriors fail regime gates closed.
    Posterior ties choose the lowest state index for deterministic replay.
    """

    symbol: str
    engine_name: str
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...] = field(metadata={"unit": "1"})
    dominant_state: int = field(metadata={"unit": "1"})
    dominant_name: str
    horizon_seconds: int = field(default=0, metadata={"unit": "s"})
    stability: float = field(default=1.0, metadata={"unit": "1"})
    posterior_entropy_nats: float = field(default=0.0, metadata={"unit": "nat"})
    calibrated: bool = True
    discriminability: float = field(default=float("inf"), metadata={"unit": UNIT_UNDETERMINED})


# ── Signal Events ───────────────────────────────────────────────────────


class SignalDirection(Enum):
    LONG = auto()
    SHORT = auto()
    FLAT = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class Signal(Event):
    """Signal evaluation output — pure function of features (no side effects).

    Layer fields (``layer`` ∈ {SIGNAL, PORTFOLIO}):

      ``layer`` — ``"SIGNAL"`` (default; :class:`HorizonSignalEngine`)
                 or ``"PORTFOLIO"`` (composition).
      ``horizon_seconds`` — 0 if unspecified, positive for
                            horizon-anchored producers.
      ``regime_gate_state`` — ``"N/A"`` when no gate applies;
                              ``"ON"`` / ``"OFF"`` for regime-gated
                              horizon signals.
      ``consumed_features`` — tuple of feature_ids consulted during
                              evaluation (empty when unspecified).
      ``trend_mechanism`` — None when unspecified; otherwise a
                            ``TrendMechanism`` member.
      ``expected_half_life_seconds`` — 0 for unspecified; otherwise drives
                                        decay weighting and hard-exit age.
    """

    symbol: str
    strategy_id: str
    direction: SignalDirection
    strength: float = field(metadata={"unit": "1"})
    edge_estimate_bps: float = field(metadata={"unit": "bps"})
    disclosed_cost_total_bps: float = field(default=0.0, metadata={"unit": "bps"})
    # Combined exit and entry cost for a reversal; zero for other signals.
    reversal_cost_estimate_bps: float = field(default=0.0, metadata={"unit": "bps"})
    disclosed_margin_ratio: float = field(default=0.0, metadata={"unit": "1"})
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: Literal["SIGNAL", "PORTFOLIO"] = "SIGNAL"
    horizon_seconds: int = field(default=0, metadata={"unit": "s"})
    regime_gate_state: Literal["ON", "OFF", "N/A"] = "N/A"
    consumed_features: tuple[str, ...] = ()
    trend_mechanism: TrendMechanism | None = None
    expected_half_life_seconds: int = field(default=0, metadata={"unit": "s"})


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
    scaling_factor: float = field(default=1.0, metadata={"unit": "1"})
    constraints: Mapping[str, float] = field(
        default_factory=dict, metadata={"unit": UNIT_UNDETERMINED}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "constraints", MappingProxyType(dict(self.constraints)))


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

    ``reason`` is a free-text tag used to distinguish ordinary orders
    from hazard-driven exits (``"HAZARD_SPIKE"`` / ``"HARD_EXIT_AGE"``)
    and portfolio orders (``"PORTFOLIO"``). Present
    on every emitted ``OrderRequest`` so forensics / parity baselines
    can split the order stream by lineage without re-deriving it from
    ``correlation_id``.
    """

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int = field(metadata={"unit": "share"})
    limit_price: Decimal | None = field(default=None, metadata={"unit": "USD"})
    strategy_id: str = ""
    # True for short-entry sells. HTB fees apply on the fill day only.
    is_short: bool = False
    # Closing-auction orders remain queued until the
    # official close print instead of filling on the continuous book.
    is_moc: bool = False
    g12_disclosed_cost_total_bps: float = field(default=0.0, metadata={"unit": "bps"})
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
    filled_quantity: int = field(default=0, metadata={"unit": "share"})
    fill_price: Decimal | None = field(default=None, metadata={"unit": "USD"})
    fees: Decimal = field(default=Decimal("0"), metadata={"unit": "USD"})
    cost_bps: Decimal = field(default=Decimal("0"), metadata={"unit": "bps"})
    reason: str = ""
    request_sequence: int | None = field(default=None, metadata={"unit": "1"})


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
    quantity: int = field(metadata={"unit": "share"})
    avg_price: Decimal = field(metadata={"unit": "USD"})
    realized_pnl: Decimal = field(metadata={"unit": "USD"})
    unrealized_pnl: Decimal = field(metadata={"unit": "USD"})
    cumulative_fees: Decimal = field(default=Decimal("0"), metadata={"unit": "USD"})
    cost_bps: Decimal = field(default=Decimal("0"), metadata={"unit": "bps"})


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
    value: float = field(metadata={"unit": UNIT_UNDETERMINED})
    metric_type: MetricType
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))


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
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


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


@dataclass(frozen=True, kw_only=True, slots=True)
class LatencyBreach(Event):
    """A live p99 latency observation exceeded its declared engine budget.

    Carries statistic, window, observed value, and budget so the record is
    interpretable without the config that produced it. Replay consumes this
    record and never re-measures.
    """

    engine: str
    statistic: str
    window_events: int = field(metadata={"unit": "1"})
    observed_ns: int = field(metadata={"unit": "ns"})
    budget_ns: int = field(metadata={"unit": "ns"})


# Why a regime gate force-closed and drove safety OFF.  One token per legacy
# ``_publish_gate_close`` path in :class:`~feelies.signals.horizon_engine.HorizonSignalEngine`:
# the clean ON→OFF transition and the three fail-closed error paths.
SafetyReason = Literal[
    "clean_transition",
    "missing_binding",
    "gate_error",
    "arithmetic_error",
]


@dataclass(frozen=True, kw_only=True, slots=True)
class SafetyStateChange(Event):
    """Typed safety-permission transition for a regime-gated SIGNAL alpha.

    Published on every path that force-closes the regime gate — the clean
    ON→OFF transition and the three fail-closed error paths (missing binding,
    gate error, arithmetic/type error, named by ``reason``).  ``safe=False``
    means the mechanism "weather" is now OFF: no new exposure is permitted.

    This decouples *"no new exposure"* (the gate's safety meaning) from
    *"flatten this open book now"* (an actuation policy).  A later risk-layer
    exit composer decides HOLD vs EXIT from this event, the hard caps, and book
    state (design §2.3, §3.3); the signal engine stays stateless (Inv-8).

    The event carries the same alpha-level provenance the gate-close ``Signal``
    FLAT carries today — ``trend_mechanism``, ``regime_gate_state``,
    ``consumed_features``, ``expected_half_life_seconds`` and the G12
    disclosed-cost totals — so a downstream flatten reproduces gate-close
    attribution (Inv-13).  The engine emits it on a dedicated sequence stream
    so it can never perturb the locked ``Signal`` stream (Inv-5).
    """

    symbol: str
    strategy_id: str
    safe: bool
    reason: SafetyReason
    trend_mechanism: TrendMechanism | None = None
    regime_gate_state: Literal["ON", "OFF", "N/A"] = "OFF"
    consumed_features: tuple[str, ...] = ()
    expected_half_life_seconds: int = field(default=0, metadata={"unit": "s"})
    disclosed_cost_total_bps: float = field(default=0.0, metadata={"unit": "bps"})
    disclosed_margin_ratio: float = field(default=0.0, metadata={"unit": "1"})


# Layered sensor, signal, and portfolio event contracts.


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


# Exit-only mechanisms may reduce exposure but never open or increase it.
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
    departing_posterior_prev: float = field(metadata={"unit": "1"})
    departing_posterior_now: float = field(metadata={"unit": "1"})
    incoming_state: str | None
    hazard_score: float = field(metadata={"unit": UNIT_UNDETERMINED})


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

    ``expected_edge_bps`` is the leg's disclosed edge, carried so the Inv-12 B4
    cost gate and passive/MOC route resolution can evaluate a PORTFOLIO leg the
    same way they evaluate a standalone SIGNAL order.  It cannot be recovered
    downstream: :class:`~feelies.composition.cross_sectional.CrossSectionalRanker`
    folds each contributing signal's ``edge_estimate_bps`` into a raw score and
    then z-scores it, so a final weight is a cross-sectional *ordering*, not an
    expected return.  The magnitude-weighted mean over aligned contributors is
    computed while the units are still bps and propagated here.

    ``0.0`` means "no edge disclosed" and is treated fail-safe by the gate: an
    opening leg with no edge cannot clear a positive cost bar (Inv-11).
    """

    symbol: str
    target_usd: float
    urgency: float = 0.5
    expected_edge_bps: float = 0.0


# ── Horizon and composition events ──────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class HorizonTick(Event):
    """Deterministic event-time scheduler tick (§5.1).

    Emitted by ``HorizonScheduler`` at boundaries
    ``session_open_ns + k * horizon_seconds * 1e9`` for k = 1, 2, ....
    Drives Layer-2 aggregation and Layer-3 synchronization.

    ``scope`` is ``"SYMBOL"`` for per-symbol horizons (in which case
    ``symbol`` must be set) or ``"UNIVERSE"`` for cross-sectional
    horizons (``symbol`` is ``None``).

    ``timestamp_ns`` is the event time that caused the scheduler to
    emit the tick.  ``boundary_timestamp_ns`` is the exact horizon
    boundary being finalized; direct constructions may leave it at ``0``
    and consumers fall back to ``timestamp_ns``.
    """

    horizon_seconds: int = field(metadata={"unit": "s"})
    boundary_index: int = field(metadata={"unit": "1"})
    session_id: str
    scope: Literal["SYMBOL", "UNIVERSE"]
    boundary_timestamp_ns: int = field(default=0, metadata={"unit": "ns"})
    symbol: str | None = None
    # Nominal grid time, distinct from the event that triggered this boundary.
    # Zero means unset for direct construction; the scheduler always sets it.
    boundary_ts_ns: int = field(default=0, metadata={"unit": "ns"})

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
    triggered this reading. ``SensorRegistry._stamp`` sets it.
    """

    symbol: str
    sensor_id: str
    sensor_version: str
    value: float | tuple[float, ...] = field(metadata={"unit": UNIT_UNDETERMINED})
    confidence: float = field(default=1.0, metadata={"unit": "1"})
    warm: bool = True
    provenance: SensorProvenance = field(default_factory=SensorProvenance)
    parent_correlation_id: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class HorizonFeatureSnapshot(Event):
    """Horizon-bucketed feature aggregate.

    ``values`` contains only warm features, while ``warm`` and ``stale`` cover
    every registered feature. Version and source maps preserve replay
    provenance; ``parent_correlation_id`` links the triggering horizon tick.
    """

    symbol: str
    horizon_seconds: int = field(metadata={"unit": "s"})
    boundary_index: int = field(metadata={"unit": "1"})
    # Exact nominal boundary time, carried verbatim from the triggering
    # ``HorizonTick.boundary_ts_ns``.  ``timestamp_ns`` remains the trigger
    # time; this is the regular-grid anchor for IC labels / forensics.
    boundary_ts_ns: int = field(default=0, metadata={"unit": "ns"})
    values: dict[str, float] = field(default_factory=dict, metadata={"unit": UNIT_UNDETERMINED})
    warm: dict[str, bool] = field(default_factory=dict)
    stale: dict[str, bool] = field(default_factory=dict)
    source_sensors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    feature_versions: dict[str, str] = field(default_factory=dict)
    parent_correlation_id: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class CrossSectionalContext(Event):
    """Universe-wide barrier-synced snapshot for portfolio alphas (§5.6).

    Emitted by ``composition/synchronizer.py`` when every
    symbol in the universe has produced a ``HorizonFeatureSnapshot`` at
    the current decision-horizon boundary (or has been declared
    permanently absent for this boundary).  ``signals_by_symbol`` and
    ``snapshots_by_symbol`` use ``None`` for symbols whose feature
    snapshot was stale or not warm at the barrier time.
    """

    horizon_seconds: int = field(metadata={"unit": "s"})
    boundary_index: int = field(metadata={"unit": "1"})
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
    completeness: float = field(default=0.0, metadata={"unit": "1"})


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
    horizon_seconds: int = field(default=0, metadata={"unit": "s"})
    target_positions: dict[str, TargetPosition] = field(
        default_factory=dict, metadata={"unit": UNIT_UNDETERMINED}
    )
    factor_exposures: dict[str, float] = field(
        default_factory=dict, metadata={"unit": UNIT_UNDETERMINED}
    )
    expected_turnover_usd: float = field(default=0.0, metadata={"unit": "USD"})
    expected_gross_exposure_usd: float = field(default=0.0, metadata={"unit": "USD"})
    mechanism_breakdown: dict[TrendMechanism, float] = field(
        default_factory=dict, metadata={"unit": "1"}
    )
    # Per-symbol one-way cost disclosed by the consumed signals.
    disclosed_cost_total_bps_by_symbol: dict[str, float] = field(
        default_factory=dict, metadata={"unit": UNIT_UNDETERMINED}
    )
    # Digest of the signals, positions, and parameters that produced the targets.
    decision_basis_hash: str = ""
    # Optimizer terminal status; empty means not recorded.
    solver_status: str = ""
