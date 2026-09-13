"""Target-based position planning and compatibility comparison.

:class:`TargetPositionManager` builds executable plans.
:class:`LegacyPositionManager` reproduces the translator's intent matrix for
shadow comparison.

Design invariants:
  - Inv-5 (determinism): :meth:`PositionManager.plan` is a pure function
    of ``(desired, current, market, config)``.
  - The compatibility adapter is faithful to
    :class:`~feelies.execution.intent.SignalPositionTranslator` +
    ``_execute_reverse`` / ``_try_build_order_from_intent`` *decision
    outcomes* — no TRIM, no cost gating, full-size MARKET exits/reverses.
  - Inv-11: reducing legs (EXIT / TRIM / REVERSE_EXIT) are never
    suppressed; only additive legs (ENTRY / SCALE_UP / REVERSE_ENTRY) are
    ever cost-gated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from decimal import Decimal

from feelies.core.events import Side
from feelies.core.position import Position
from feelies.core.position_manager import DesiredPosition as DesiredPosition
from feelies.core.position_manager import ExecStyle as ExecStyle
from feelies.core.position_manager import MarketContext as MarketContext
from feelies.core.position_manager import PlanLeg as PlanLeg
from feelies.core.position_manager import PlannedOrder as PlannedOrder
from feelies.core.position_manager import PositionManager as PositionManager
from feelies.core.position_manager import PositionManagerConfig as PositionManagerConfig
from feelies.core.position_manager import PositionPlan as PositionPlan
from feelies.core.position_manager import SuppressedLeg as SuppressedLeg
from feelies.core.position_manager import desired_from_signal as desired_from_signal
from feelies.core.position_manager import order_intent_from_plan as order_intent_from_plan
from feelies.execution.cost_model import CostModel, estimate_round_trip_cost_bps
from feelies.execution.intent import TradingIntent


# Economic cost gates may block only additive legs. Reducing legs always run.
ADDITIVE_LEGS: frozenset[PlanLeg] = frozenset(
    {PlanLeg.ENTRY, PlanLeg.SCALE_UP, PlanLeg.REVERSE_ENTRY}
)
REDUCING_LEGS: frozenset[PlanLeg] = frozenset({PlanLeg.TRIM, PlanLeg.EXIT, PlanLeg.REVERSE_EXIT})


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


class LegacyPositionManager:
    """Represent ``SignalPositionTranslator`` decisions as a ``PositionPlan``.

    Same-direction reductions remain ``NO_ACTION``. Entries are passive;
    exits and reversal exits are aggressive. This planner has no cost gates.
    """

    def __init__(self, default_target_quantity: int = 100) -> None:
        self._default_target = default_target_quantity

    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,
        market: MarketContext | None = None,
        config: PositionManagerConfig | None = None,
    ) -> PositionPlan:
        cur = current.quantity
        sym = desired.symbol
        d = desired.direction or _sign(desired.target_qty)
        mag = abs(desired.target_qty)

        # Directional targets cannot reduce a same-direction position.
        if d > 0:
            eff = max(cur, mag)
        elif d < 0:
            eff = min(cur, -mag)
        else:
            eff = 0

        delta = eff - cur
        if delta == 0:
            return PositionPlan()

        # Sign flip with a non-zero residual → REVERSE (exit + entry).
        if cur != 0 and eff != 0 and (cur > 0) != (eff > 0):
            entry_side = Side.BUY if eff > 0 else Side.SELL
            return self._reverse_plan(
                sym,
                exit_qty=abs(cur),
                entry_qty=abs(eff),
                entry_side=entry_side,
                is_short=eff < 0,
            )

        # An exit-only reversal is the same flatten order as EXIT.
        if eff == 0:
            return PositionPlan(
                orders=(
                    PlannedOrder(
                        symbol=sym,
                        side=Side.SELL if cur > 0 else Side.BUY,
                        quantity=abs(cur),
                        style=ExecStyle.MARKET,
                        leg=PlanLeg.EXIT,
                    ),
                )
            )

        # The target clamp leaves only entry or same-direction scale-up here.
        leg = PlanLeg.ENTRY if cur == 0 else PlanLeg.SCALE_UP
        side = Side.BUY if delta > 0 else Side.SELL
        return PositionPlan(
            orders=(
                self._additive(
                    sym,
                    side,
                    abs(delta),
                    leg,
                    is_short=eff < 0,
                ),
            )
        )

    @staticmethod
    def _additive(
        sym: str,
        side: Side,
        qty: int,
        leg: PlanLeg,
        is_short: bool,
    ) -> PlannedOrder:
        return PlannedOrder(
            symbol=sym,
            side=side,
            quantity=qty,
            style=ExecStyle.PASSIVE,
            leg=leg,
            is_short=is_short,
        )

    @staticmethod
    def _reverse_plan(
        sym: str,
        *,
        exit_qty: int,
        entry_qty: int,
        entry_side: Side,
        is_short: bool,
    ) -> PositionPlan:
        # Mirror _execute_reverse: aggressive MARKET exit + (same-side) entry.
        exit_side = Side.BUY if entry_side == Side.BUY else Side.SELL
        return PositionPlan(
            orders=(
                PlannedOrder(
                    symbol=sym,
                    side=exit_side,
                    quantity=exit_qty,
                    style=ExecStyle.MARKET,
                    leg=PlanLeg.REVERSE_EXIT,
                ),
                PlannedOrder(
                    symbol=sym,
                    side=entry_side,
                    quantity=entry_qty,
                    style=ExecStyle.PASSIVE,
                    leg=PlanLeg.REVERSE_ENTRY,
                    is_short=is_short,
                ),
            )
        )


class TargetPositionManager:
    """Add cost-aware partial reductions to translator-compatible planning.

    A same-direction target shrink emits ``TRIM`` when it clears the churn
    guard. All other decisions delegate to :class:`LegacyPositionManager`.
    """

    def __init__(
        self,
        default_target_quantity: int = 100,
        *,
        trim_min_fraction: float = 0.10,
    ) -> None:
        self._legacy = LegacyPositionManager(default_target_quantity)
        self._trim_min_fraction = trim_min_fraction

    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,
        market: MarketContext | None = None,
        config: PositionManagerConfig | None = None,
    ) -> PositionPlan:
        legacy_plan = self._legacy.plan(
            desired=desired,
            current=current,
            market=market,
            config=config,
        )
        if config is None or not config.enable_trim:
            return legacy_plan

        cur = current.quantity
        d = desired.direction or _sign(desired.target_qty)
        m = abs(desired.target_qty)
        # Only same-direction shrink overrides the delegated plan.
        if d == 0 or _sign(cur) != d or m >= abs(cur):
            return legacy_plan

        trim_qty = abs(cur) - m
        threshold = max(1, math.ceil(self._trim_min_fraction * abs(cur)))
        if trim_qty < threshold:
            # Hold small trims and record the binding churn constraint.
            return PositionPlan(
                suppressed=(
                    SuppressedLeg(
                        leg=PlanLeg.TRIM,
                        reason="trim_below_churn_threshold",
                        constraints={
                            "trim_qty": float(trim_qty),
                            "threshold": float(threshold),
                            "current_qty": float(cur),
                        },
                    ),
                )
            )

        side = Side.SELL if cur > 0 else Side.BUY
        # Price the excess once for both the gate and plan rationale.
        rt_cost_bps: float | None = None
        if market is not None and market.cost_model is not None and market.quote is not None:
            q = market.quote
            rt_cost_bps = round_trip_cost_bps(
                market.cost_model,
                symbol=desired.symbol,
                entry_side=side,
                quantity=trim_qty,
                mid_price=(q.bid + q.ask) / Decimal("2"),
                half_spread=(q.ask - q.bid) / Decimal("2"),
                is_taker_entry=True,
                is_short_entry=False,
                bid_size=q.bid_size,
                ask_size=q.ask_size,
                market_impact_factor=market.market_impact_factor,
                max_impact_half_spreads=market.max_impact_half_spreads,
                within_l1_impact_factor=market.within_l1_impact_factor,
                permanent_impact_coefficient=market.permanent_impact_coefficient,
            )

        # Hold excess while forward edge still covers its round-trip churn cost.
        k = config.trim_edge_gate_multiplier
        if (
            k > 0
            and rt_cost_bps is not None
            and entry_edge_clears_cost(
                edge_bps=desired.edge_bps,
                rt_cost_bps=rt_cost_bps,
                min_ratio=k,
                basis="one_way",
            )
        ):
            return PositionPlan(
                suppressed=(
                    SuppressedLeg(
                        leg=PlanLeg.TRIM,
                        reason="trim_edge_above_gate",
                        constraints={
                            "edge_bps": desired.edge_bps,
                            "required_bps": k * rt_cost_bps,
                            "round_trip_cost_bps": rt_cost_bps,
                            "trim_qty": float(trim_qty),
                        },
                    ),
                )
            )

        rationale: dict[str, float] = {
            "trim_qty": float(trim_qty),
            "current_qty": float(cur),
            "target_qty": float(d * m),
            "trim_fraction": float(trim_qty) / float(abs(cur)),
        }
        if rt_cost_bps is not None:
            rationale["round_trip_cost_bps"] = rt_cost_bps
        # A discretionary trim may rest passively without creating exposure.
        trim_style = ExecStyle.PASSIVE if config.urgency_exec else ExecStyle.MARKET
        return PositionPlan(
            orders=(
                PlannedOrder(
                    symbol=desired.symbol,
                    side=side,
                    quantity=trim_qty,
                    style=trim_style,
                    leg=PlanLeg.TRIM,
                    rationale=rationale,
                ),
            )
        )


# Pure cost gates shared by planning and orchestration; callers own alerts.


def round_trip_cost_bps(
    cost_model: CostModel,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    is_taker_entry: bool,
    is_short_entry: bool,
    bid_size: int | None = None,
    ask_size: int | None = None,
    market_impact_factor: Decimal | None = None,
    max_impact_half_spreads: Decimal | None = None,
    within_l1_impact_factor: Decimal = Decimal("0"),
    permanent_impact_coefficient: Decimal = Decimal("0"),
) -> float:
    """Model entry plus aggressive-exit cost in basis points."""
    return estimate_round_trip_cost_bps(
        cost_model,
        symbol=symbol,
        entry_side=entry_side,
        quantity=quantity,
        mid_price=mid_price,
        half_spread=half_spread,
        is_taker=is_taker_entry,
        is_taker_exit=True,
        is_short_entry=is_short_entry,
        bid_size=bid_size,
        ask_size=ask_size,
        market_impact_factor=market_impact_factor,
        max_impact_half_spreads=max_impact_half_spreads,
        within_l1_impact_factor=within_l1_impact_factor,
        permanent_impact_coefficient=permanent_impact_coefficient,
    )


def entry_edge_clears_cost(
    *,
    edge_bps: float,
    rt_cost_bps: float,
    min_ratio: float,
    basis: str,
) -> bool:
    """Return whether entry edge clears the required round-trip cost."""
    edge_basis = edge_bps * 2.0 if basis == "round_trip" else edge_bps
    return edge_basis >= min_ratio * rt_cost_bps


def reversal_edge_gate(
    *,
    edge_bps: float,
    exit_cost_bps: float,
    entry_cost_bps: float,
    multiplier: float,
) -> tuple[float, float, bool]:
    """B5: combined exit+entry edge gate for a flip.

    Returns ``(combined_cost_bps, required_bps, passes)`` where the flip
    passes iff ``edge_bps > (exit + entry) × multiplier``.
    """
    combined = exit_cost_bps + entry_cost_bps
    required = combined * multiplier
    return combined, required, edge_bps > required


# Compare plans by child orders, not intent labels; both paths may name the same
# exit-only reversal differently while submitting an identical flatten order.


def _legacy_orders(
    intent_name: str,
    target_quantity: int,
    current_quantity: int,
) -> list[tuple[Side, int]] | None:
    """Reconstruct the child orders emitted by the translator path.

    Mirrors ``SignalPositionTranslator`` + ``_execute_reverse`` /
    ``_try_build_order_from_intent`` decomposition.  ``None`` when the
    intent name is unknown.  Sub-``min_order_shares`` filtering is an
    execution concern applied downstream and is *not* modelled here —
    zero-quantity legs are dropped by :func:`_norm`, which suffices for
    the decision-level equivalence the shadow harness asserts.
    """
    cur = current_quantity
    try:
        ti = TradingIntent[intent_name]
    except KeyError:
        return None
    if ti is TradingIntent.NO_ACTION:
        return []
    if ti is TradingIntent.ENTRY_LONG:
        return [(Side.BUY, target_quantity)]
    if ti is TradingIntent.ENTRY_SHORT:
        return [(Side.SELL, target_quantity)]
    if ti is TradingIntent.EXIT:
        return [(Side.SELL if cur > 0 else Side.BUY, target_quantity)]
    if ti is TradingIntent.SCALE_UP:
        return [(Side.BUY if cur > 0 else Side.SELL, target_quantity)]
    if ti is TradingIntent.REVERSE_LONG_TO_SHORT:
        return [(Side.SELL, abs(cur)), (Side.SELL, target_quantity - abs(cur))]
    if ti is TradingIntent.REVERSE_SHORT_TO_LONG:
        return [(Side.BUY, abs(cur)), (Side.BUY, target_quantity - abs(cur))]
    return None


def _norm(orders: list[tuple[Side, int]]) -> list[tuple[str, int]]:
    """Canonical, zero-dropped, order-independent form for comparison."""
    return sorted((s.name, q) for s, q in orders if q > 0)


@dataclass(frozen=True, kw_only=True)
class PlanDivergence:
    """Mismatch between compatibility and shadow-plan order sets."""

    symbol: str
    signal_sequence: int
    legacy_intent: str
    legacy_quantity: int
    planner_leg: str
    planner_quantity: int
    detail: str


def compare_plan_to_intent(
    *,
    intent_name: str,
    intent_target_quantity: int,
    current_quantity: int,
    plan: PositionPlan,
    symbol: str,
    signal_sequence: int,
) -> PlanDivergence | None:
    """Return a :class:`PlanDivergence` iff the plan's orders disagree."""
    legacy = _legacy_orders(
        intent_name,
        intent_target_quantity,
        current_quantity,
    )
    legacy_n = _norm(legacy) if legacy is not None else None
    plan_n = _norm([(o.side, o.quantity) for o in plan.orders])
    if legacy_n == plan_n:
        return None
    return PlanDivergence(
        symbol=symbol,
        signal_sequence=signal_sequence,
        legacy_intent=intent_name,
        legacy_quantity=intent_target_quantity,
        planner_leg=plan.primary_leg.name,
        planner_quantity=plan.total_quantity,
        detail=f"legacy_orders={legacy_n} plan_orders={plan_n}",
    )
