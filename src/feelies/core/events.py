"""Typed event schemas for all inter-layer communication (invariant 7).

Every event crossing a layer boundary must use one of these schemas.
No untyped messages.  No polling.  All events are frozen dataclasses
— immutable after creation, safe to share without copying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Any


# ── Base ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base event.  Every event carries provenance metadata."""

    timestamp_ns: int
    correlation_id: str
    sequence: int


# ── Market Data Events ──────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class NBBOQuote(Event):
    """L1 NBBO quote update from Polygon.io."""

    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    exchange_timestamp_ns: int
    conditions: tuple[int, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Trade(Event):
    """Trade print from exchange."""

    symbol: str
    price: Decimal
    size: int
    exchange_timestamp_ns: int
    conditions: tuple[int, ...] = ()


# ── Feature Events ──────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class FeatureVector(Event):
    """Computed features for a symbol at a point in time.

    Emitted by the feature engine after every incremental update.
    Consumed by the signal engine — never raw market events.
    """

    symbol: str
    feature_version: str
    values: dict[str, float]
    warm: bool = True
    stale: bool = False
    event_count: int = 0


# ── Signal Events ───────────────────────────────────────────────────────


class SignalDirection(Enum):
    LONG = auto()
    SHORT = auto()
    FLAT = auto()


@dataclass(frozen=True, kw_only=True)
class Signal(Event):
    """Signal evaluation output — pure function of features (no side effects)."""

    symbol: str
    strategy_id: str
    direction: SignalDirection
    strength: float
    edge_estimate_bps: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Risk Events ─────────────────────────────────────────────────────────


class RiskAction(Enum):
    ALLOW = auto()
    SCALE_DOWN = auto()
    REJECT = auto()
    FORCE_FLATTEN = auto()


@dataclass(frozen=True, kw_only=True)
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


@dataclass(frozen=True, kw_only=True)
class OrderRequest(Event):
    """Request to place an order — output of ORDER_DECISION micro-state."""

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None = None
    strategy_id: str = ""


@dataclass(frozen=True, kw_only=True)
class OrderAck(Event):
    """Acknowledgement of order state change from execution backend.

    In backtest mode this is emitted by the fill simulator.
    In live mode this is emitted by the broker gateway.
    The pipeline does not branch on which source produced it (invariant 9).
    """

    order_id: str
    symbol: str
    status: str
    filled_quantity: int = 0
    fill_price: Decimal | None = None
    reason: str = ""


# ── Position Events ─────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class PositionUpdate(Event):
    """Position change after fill reconciliation."""

    symbol: str
    quantity: int
    avg_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    slippage_bps: Decimal


# ── System Events ───────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
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


@dataclass(frozen=True, kw_only=True)
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


@dataclass(frozen=True, kw_only=True)
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


@dataclass(frozen=True, kw_only=True)
class KillSwitchActivation(Event):
    """Emitted when the kill switch is activated.

    Kill switch is irreversible without human re-authorization.
    This event is published on the bus so all layers can react
    (cancel orders, freeze state, cease submissions).
    """

    reason: str
    activated_by: str
