"""Transaction cost model protocol for backtest fill realism (invariant 12).

The Protocol, breakdown, and aggressive-taker estimator live in core
so kernel can name them without importing the execution package.
DefaultCostModel stays in execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from feelies.core.events import Side


FillType = Literal["TAKER", "LEVEL", "THROUGH"]


class CostModel(Protocol):
    """Computes fees and cost breakdown for a simulated fill."""

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
        half_spread: Decimal,
        is_taker: bool = True,
        is_short: bool = False,
        fill_type: FillType | None = None,
        adverse_notional_price: Decimal | None = None,
        is_through_fill: bool = False,
    ) -> CostBreakdown:
        """Return fees and adverse-selection cost for one fill.

        Maker and taker fees differ; maker through-fills use the stronger
        adverse-selection rate. ``adverse_notional_price`` can anchor that
        charge to the opposite-side BBO. ``is_through_fill`` remains an alias
        for callers that do not pass ``fill_type``.
        """
        ...


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised cost output attached to each fill.

    ``cost_bps`` is quantized to 0.01 for forensic stability.
    ``raw_cost_bps`` is unquantized; callers
    that perform fine-grained comparisons (the minimum-cost policy
    routing decision) should use the raw value to avoid quantization-
    flip on borderline cases.
    """

    spread_cost: Decimal
    commission: Decimal
    total_fees: Decimal
    cost_bps: Decimal
    notional: Decimal
    raw_cost_bps: Decimal = Decimal("0")


def _within_l1_premium(
    *,
    quantity: int,
    available_depth: int,
    half_spread: Decimal,
    within_l1_impact_factor: Decimal,
    permanent_impact_coefficient: Decimal,
) -> Decimal:
    """Per-share within-L1 participation premium (mirrors ``market_fill``).

    Kept local to avoid a ``cost_model`` ↔ ``market_fill`` import cycle; the
    formula is identical to :func:`market_fill.base_impact_premium`.
    """
    if available_depth <= 0 or quantity <= 0:
        return Decimal("0")
    if within_l1_impact_factor <= 0 and permanent_impact_coefficient <= 0:
        return Decimal("0")
    participation = Decimal(quantity) / Decimal(available_depth)
    capped = participation if participation < Decimal("1") else Decimal("1")
    temporary = within_l1_impact_factor * capped * half_spread
    permanent = permanent_impact_coefficient * participation.sqrt() * half_spread
    return temporary + permanent


def estimate_aggressive_taker_cost_bps(
    model: CostModel,
    *,
    symbol: str,
    side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    available_depth: int,
    market_impact_factor: Decimal,
    max_impact_half_spreads: Decimal,
    within_l1_impact_factor: Decimal = Decimal("0"),
    permanent_impact_coefficient: Decimal = Decimal("0"),
    is_short: bool = False,
) -> float:
    """Estimate one-way taker ``cost_bps`` including walk-the-book impact.

    Mirrors ``market_fill.append_market_fill_acks`` — splits the order
    into an L1 leg (filling at mid against ``available_depth``) and an
    excess leg (filling at impact-adjusted mid).  Returns the
    weighted-by-quantity ``cost_bps`` summed across the two legs.

    ``within_l1_impact_factor`` / ``permanent_impact_coefficient`` mirror the
    within-L1 participation premium charged by
    ``market_fill`` so the B4 gate / minimum-cost policy do not under-price
    aggressive fills once enabled. Both default to zero, leaving impact only
    on the excess-over-L1 leg.

    Used by the orchestrator's B4 gate and the minimum-cost policy to
    price the aggressive route with depth. Without
    this helper, both consumers assume a full L1 fill and silently
    under-price large orders against thin books.
    """
    if quantity <= 0 or available_depth <= 0:
        # No fill possible — treat as prohibitively expensive so gating/policy
        # does not under-price aggressive fills on zero depth.
        return float("inf")

    within_premium = _within_l1_premium(
        quantity=quantity,
        available_depth=available_depth,
        half_spread=half_spread,
        within_l1_impact_factor=within_l1_impact_factor,
        permanent_impact_coefficient=permanent_impact_coefficient,
    )

    if quantity <= available_depth:
        breakdown = model.compute(
            symbol,
            side,
            quantity,
            mid_price,
            half_spread,
            is_taker=True,
            is_short=is_short,
        )
        if within_premium <= 0:
            # Keep the raw grain consistent with the non-depth-aware estimator.
            return float(breakdown.raw_cost_bps)
        total_notional = mid_price * Decimal(str(quantity))
        if total_notional <= 0:
            return 0.0
        within_cost = within_premium * Decimal(str(quantity))
        return float((breakdown.total_fees + within_cost) / total_notional * Decimal("10000"))

    # Walk-the-book: L1 + excess.
    partial_qty = available_depth
    excess_qty = quantity - available_depth
    raw_impact = (
        market_impact_factor
        * Decimal(str(excess_qty))
        / Decimal(str(available_depth))
        * half_spread
    )
    impact_cap = max_impact_half_spreads * half_spread
    impact = min(raw_impact, impact_cap)

    # Both legs evaluated against mid-notional so the impact is the
    # only side-dependent cost line.  ``impact * excess_qty`` is the
    # economic slippage on the walk-the-book leg; positive cost
    # regardless of side (BUY pays more, SELL receives less).
    partial = model.compute(
        symbol,
        side,
        partial_qty,
        mid_price,
        half_spread,
        is_taker=True,
        is_short=is_short,
    )
    excess = model.compute(
        symbol,
        side,
        excess_qty,
        mid_price,
        half_spread,
        is_taker=True,
        is_short=is_short,
    )
    total_notional = mid_price * Decimal(str(quantity))
    impact_cost = impact * Decimal(str(excess_qty))
    # The within-L1 premium applies to the whole order (both legs).
    within_cost = within_premium * Decimal(str(quantity))
    total_fees = partial.total_fees + excess.total_fees + impact_cost + within_cost
    if total_notional <= 0:
        return 0.0
    return float(total_fees / total_notional * Decimal("10000"))


def estimate_round_trip_cost_bps(
    model: CostModel,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    is_taker: bool,
    is_short_entry: bool,
    is_taker_exit: bool | None = None,
    bid_size: int | None = None,
    ask_size: int | None = None,
    market_impact_factor: Decimal | None = None,
    max_impact_half_spreads: Decimal | None = None,
    within_l1_impact_factor: Decimal = Decimal("0"),
    permanent_impact_coefficient: Decimal = Decimal("0"),
    is_through_fill_entry: bool = False,
    is_through_fill_exit: bool = False,
) -> float:
    """Estimate entry-plus-exit cost in basis points.

    Entry and exit may use different liquidity and through-fill assumptions.
    Short-entry HTB and sell fees apply only to the relevant leg. Independent
    exit settings avoid understating market exits after passive entries.
    """
    if is_taker_exit is None:
        is_taker_exit = is_taker
    entry_short = bool(is_short_entry and entry_side == Side.SELL)
    exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY

    # Use depth-aware taker estimates only when depth and impact inputs are complete.
    use_depth_aware = (
        bid_size is not None
        and ask_size is not None
        and market_impact_factor is not None
        and max_impact_half_spreads is not None
    )

    def _leg_bps(
        side: Side,
        *,
        taker: bool,
        short: bool,
        through_fill: bool,
    ) -> float:
        if taker and use_depth_aware:
            assert market_impact_factor is not None
            assert max_impact_half_spreads is not None
            depth = ask_size if side == Side.BUY else bid_size
            return estimate_aggressive_taker_cost_bps(
                model,
                symbol=symbol,
                side=side,
                quantity=quantity,
                mid_price=mid_price,
                half_spread=half_spread,
                available_depth=int(depth or 0),
                market_impact_factor=market_impact_factor,
                max_impact_half_spreads=max_impact_half_spreads,
                within_l1_impact_factor=within_l1_impact_factor,
                permanent_impact_coefficient=permanent_impact_coefficient,
                is_short=short,
            )
        return float(
            model.compute(
                symbol,
                side,
                quantity,
                mid_price,
                half_spread,
                is_taker=taker,
                is_short=short,
                fill_type="THROUGH" if through_fill else None,
                is_through_fill=through_fill,
            ).cost_bps
        )

    return _leg_bps(
        entry_side,
        taker=is_taker,
        short=entry_short,
        through_fill=is_through_fill_entry,
    ) + _leg_bps(
        exit_side,
        taker=is_taker_exit,
        short=False,
        through_fill=is_through_fill_exit,
    )
