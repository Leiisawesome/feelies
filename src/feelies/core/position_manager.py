"""Target-based position planning types.

The Protocol and kernel-imported types live in core so kernel can
name them without importing the execution package. TargetPositionManager
and LegacyPositionManager stay in execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Protocol

from feelies.core.cost_model import CostModel
from feelies.core.events import NBBOQuote, Side, Signal, SignalDirection
from feelies.core.intent import OrderIntent, TradingIntent
from feelies.core.position import Position


class PlanLeg(Enum):
    """A classified leg of a position plan.

    ``REVERSE_EXIT`` + ``REVERSE_ENTRY`` are the two legs a flip
    decomposes into (mirrors ``_execute_reverse``).  ``TRIM`` (partial
    same-direction reduce) is not emitted
    by :class:`LegacyPositionManager`.
    """

    NO_ACTION = auto()
    ENTRY = auto()
    SCALE_UP = auto()
    TRIM = auto()
    EXIT = auto()
    REVERSE_EXIT = auto()
    REVERSE_ENTRY = auto()


class ExecStyle(Enum):
    """How a planned order should be worked.

    Plans use passive or market execution according to urgency and leg type.
    """

    PASSIVE = auto()
    MARKET = auto()


@dataclass(frozen=True, kw_only=True)
class DesiredPosition:
    """A desired per-symbol book state — the planner's input.

    Generalises :class:`~feelies.core.events.TargetPosition` (the
    PORTFOLIO path's existing target model) to a signed share target with
    the edge/urgency/provenance the decision needs.

    ``target_qty`` is **signed**: ``> 0`` long, ``< 0`` short, ``0`` flat.
    ``direction`` (+1 long / -1 short / 0 flat) disambiguates the desired
    *intent* when ``target_qty == 0`` — a directional signal that sized to
    zero (hold/clamp) vs. a genuine FLAT (exit).  For non-zero targets it
    is redundant with ``sign(target_qty)``.  The forward-looking planner
    keys on ``target_qty``; the compatibility adapter also consults
    ``direction`` to reproduce translator clamping.

    A risk-driven desired (stop / hazard / flatten / session-flat) is
    always FLAT (``direction == 0``), which structurally never reaches the
    trim cost gate below. :meth:`TargetPositionManager.plan` turns a FLAT
    desired into an unconditional exit. There is no
    separate ``mandatory`` marker: the cost gate is forced open by
    construction, not by an explicit flag.
    """

    symbol: str
    target_qty: int
    direction: int = 0
    edge_bps: float = 0.0
    urgency: float = 0.5
    source: str = ""
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class MarketContext:
    """Market inputs the planner prices a disturbance against.

    The compatibility adapter does no cost math.

    The impact knobs (``market_impact_factor``, ``max_impact_half_spreads``,
    ``within_l1_impact_factor``, ``permanent_impact_coefficient``) mirror
    the orchestrator's B4 entry-gate plumbing so the P3b trim gate prices
    its round-trip churn cost against the same depth-aware / within-L1
    model used by the entry gate and fill path. Defaults imply no within-L1 impact.
    """

    quote: NBBOQuote | None = None
    cost_model: CostModel | None = None
    market_impact_factor: Decimal | None = None
    max_impact_half_spreads: Decimal | None = None
    within_l1_impact_factor: Decimal = Decimal("0")
    permanent_impact_coefficient: Decimal = Decimal("0")


@dataclass(frozen=True, kw_only=True)
class PlannedOrder:
    """One child order proposed by the planner, with its rationale."""

    symbol: str
    side: Side
    quantity: int
    style: ExecStyle
    leg: PlanLeg
    is_short: bool = False
    rationale: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SuppressedLeg:
    """A leg the planner declined to emit (for traces / alerts)."""

    leg: PlanLeg
    reason: str
    constraints: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class PositionPlan:
    """The planner's output: child orders + suppressed-leg rationale."""

    orders: tuple[PlannedOrder, ...] = ()
    suppressed: tuple[SuppressedLeg, ...] = ()

    @property
    def primary_leg(self) -> PlanLeg:
        """The leading leg (``REVERSE_EXIT`` for a flip, else the sole leg)."""
        return self.orders[0].leg if self.orders else PlanLeg.NO_ACTION

    @property
    def total_quantity(self) -> int:
        """Sum the child-order quantities."""
        return sum(o.quantity for o in self.orders)


@dataclass(frozen=True, kw_only=True)
class PositionManagerConfig:
    """Planner controls."""

    enabled: bool = False  # Drive execution from the plan.
    shadow: bool = False  # Compare the plan with translator output.
    enable_trim: bool = False  # Emit partial reductions.
    # Suppress trims while edge covers this multiple of churn cost; 0 disables.
    trim_edge_gate_multiplier: float = 0.0
    # Post discretionary trims passively; safety and reversal exits stay aggressive.
    urgency_exec: bool = False


class PositionManager(Protocol):
    """Diff a desired book against the current book into a plan."""

    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,
        market: MarketContext,
        config: PositionManagerConfig,
    ) -> PositionPlan: ...


def desired_from_signal(
    signal: Signal,
    target_qty: int | None,
    *,
    default_target_quantity: int = 100,
) -> DesiredPosition:
    """Map a signal and unsigned size to a signed desired position."""
    tgt = target_qty if target_qty is not None else default_target_quantity
    if tgt < 0:
        raise ValueError(f"target_quantity must be non-negative, got {tgt}")
    if signal.direction == SignalDirection.LONG:
        target_signed, direction = tgt, 1
    elif signal.direction == SignalDirection.SHORT:
        target_signed, direction = -tgt, -1
    else:  # FLAT
        target_signed, direction = 0, 0
    return DesiredPosition(
        symbol=signal.symbol,
        target_qty=target_signed,
        direction=direction,
        edge_bps=signal.edge_estimate_bps,
        source=signal.strategy_id,
        reason="signal",
    )


# Project plans onto OrderIntent so existing risk and routing remain authoritative.


def order_intent_from_plan(
    plan: PositionPlan,
    *,
    signal: Signal,
    current: Position,
) -> OrderIntent:
    """Project a ``PositionPlan`` onto an ``OrderIntent``.

    The ``target_quantity`` convention matches the translator: ENTRY/
    SCALE_UP carry the leg quantity, EXIT carries ``|current|``, and a
    REVERSE carries ``exit + entry`` (== ``plan.total_quantity`` for both
    the two-leg flip and the degenerate exit-only flip).
    """
    cur = current.quantity

    def _oi(intent: TradingIntent, target: int) -> OrderIntent:
        return OrderIntent(
            intent=intent,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=target,
            current_quantity=cur,
            signal=signal,
        )

    if not plan.orders:
        return _oi(TradingIntent.NO_ACTION, 0)

    leg = plan.primary_leg
    # A flip is keyed on the *current* side: long→short when currently long.
    reverse_intent = (
        TradingIntent.REVERSE_LONG_TO_SHORT if cur > 0 else TradingIntent.REVERSE_SHORT_TO_LONG
    )

    if leg in (PlanLeg.REVERSE_EXIT, PlanLeg.REVERSE_ENTRY):
        return _oi(reverse_intent, plan.total_quantity)
    if leg is PlanLeg.EXIT:
        # A directional zero target keeps the reversal label used in order IDs.
        if signal.direction == SignalDirection.FLAT:
            return _oi(TradingIntent.EXIT, plan.total_quantity)
        return _oi(reverse_intent, plan.total_quantity)
    if leg is PlanLeg.SCALE_UP:
        return _oi(TradingIntent.SCALE_UP, plan.total_quantity)
    if leg is PlanLeg.ENTRY:
        intent = (
            TradingIntent.ENTRY_LONG
            if plan.orders[0].side == Side.BUY
            else TradingIntent.ENTRY_SHORT
        )
        return _oi(intent, plan.total_quantity)
    if leg is PlanLeg.TRIM:
        # TRIM uses the EXIT path so reductions bypass entry cost gates.
        return _oi(TradingIntent.EXIT, plan.total_quantity)
    return _oi(TradingIntent.NO_ACTION, 0)
