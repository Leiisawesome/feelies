"""Shared cross-price MARKET simulation — D14 partial fill + walk-the-book impact.

:class:`~feelies.execution.backtest_router.BacktestOrderRouter` and
:class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter` both
delegate aggressive fills here so deferred MARKET paths cannot silently diverge
under ``latency_ns > 0`` (Inv-9).

Fill-price convention (BT-3)
----------------------------
A taker MARKET (or marketable-limit) order fills at the **executed cross
price** — the touch the taker crosses to: a BUY lifts ``quote.ask``, a SELL
hits ``quote.bid``.  The half-spread is therefore embedded in the recorded
fill price (matching what IB reports as the fill), NOT debited as a separate
``spread_cost`` fee.  The cost model is consequently called with
``half_spread=0`` so the cross is not double-counted.  Walk-the-book impact
for the excess quantity is added *on top of* the cross (above the ask for
buys, below the bid for sells).

This shifts the half-spread from ``Position.cumulative_fees`` into
``avg_entry_price`` (and, since marks use the mid, into the immediate
unrealized markdown).  NAV is invariant — ``_compute_current_equity`` sums
``account_equity + realized − fees + unrealized`` — only the attribution
changes.  Prior to BT-3 the fill priced at the mid with the half-spread
carried as a fee.

BT-14 snaps all fill and limit prices to the Reg NMS tick grid (see
:mod:`feelies.execution.tick_size`).
"""

from __future__ import annotations

import math
from decimal import Decimal

from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel


def _clamp_fill_price_to_limit(
    side: Side,
    price: Decimal,
    limit_price: Decimal | None,
) -> Decimal:
    """Ensure simulated aggressive fills respect a LIMIT ``limit_price`` when set.

    Pure MARKET orders leave ``limit_price`` unset; marketable LIMIT orders routed
    to this helper carry the submission limit and must not execute worse than it
    (buyer never pays above limit, seller never receives below limit).
    """
    if limit_price is None:
        return price
    if side == Side.BUY:
        return min(price, limit_price)
    return max(price, limit_price)


def to_decimal(value: Decimal | int | str | float, name: str) -> Decimal:
    """Coerce a numeric input to Decimal, rejecting non-finite floats."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, got {value!r}")
        return Decimal(str(value))
    if isinstance(value, (int, str)):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    raise TypeError(f"{name} must be Decimal | int | str | float, got {type(value).__name__}")


def append_market_fill_acks(
    pending_acks: list[OrderAck],
    ack_seq: SequenceGenerator,
    cost_model: CostModel,
    request: OrderRequest,
    quote: NBBOQuote,
    fill_ts: int,
    *,
    market_impact_factor: Decimal,
    max_impact_half_spreads: Decimal,
) -> None:
    """Append FILLED / PARTIALLY_FILLED acks for a MARKET-style fill at L1.

    Caller must ensure the quote is non-crossed and L1 depth on the relevant
    side is strictly positive.
    """
    limit_px = request.limit_price
    # BT-3: fill at the executed cross price (BUY lifts the ask, SELL hits
    # the bid), not the synthetic mid.  The half-spread is embedded in the
    # price, so the cost model is called with half_spread=0 (no separate
    # spread_cost fee).  ``half_spread`` is still used to *size* the
    # walk-the-book impact below, which is measured in half-spread units.
    cross = quote.ask if request.side == Side.BUY else quote.bid
    fill_price = _clamp_fill_price_to_limit(request.side, cross, limit_px)
    half_spread = (quote.ask - quote.bid) / Decimal("2")

    available_depth = (
        quote.ask_size if request.side == Side.BUY else quote.bid_size
    )

    if request.quantity > available_depth:
        partial_qty = available_depth
        partial_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=partial_qty,
            fill_price=fill_price,
            half_spread=Decimal("0"),
            is_short=request.is_short,
        )
        pending_acks.append(OrderAck(
            timestamp_ns=fill_ts,
            correlation_id=request.correlation_id,
            sequence=ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.PARTIALLY_FILLED,
            filled_quantity=partial_qty,
            fill_price=fill_price,
            fees=partial_costs.total_fees,
            cost_bps=partial_costs.cost_bps,
            request_sequence=request.sequence,
        ))

        excess_qty = request.quantity - available_depth
        raw_impact = (
            market_impact_factor
            * Decimal(str(excess_qty))
            / Decimal(str(available_depth))
            * half_spread
        )
        impact_cap = max_impact_half_spreads * half_spread
        impact = min(raw_impact, impact_cap)
        # Walk-the-book impact stacks on top of the cross (above the ask
        # for buys, below the bid for sells).
        if request.side == Side.BUY:
            raw_impact_px = cross + impact
        else:
            raw_impact_px = max(cross - impact, Decimal("0.01"))
        impact_price = _clamp_fill_price_to_limit(
            request.side,
            raw_impact_px,
            limit_px,
        )

        excess_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=excess_qty,
            fill_price=impact_price,
            half_spread=Decimal("0"),
            is_short=request.is_short,
        )
        pending_acks.append(OrderAck(
            timestamp_ns=fill_ts,
            correlation_id=request.correlation_id,
            sequence=ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=excess_qty,
            fill_price=impact_price,
            fees=excess_costs.total_fees,
            cost_bps=excess_costs.cost_bps,
            request_sequence=request.sequence,
        ))
        return

    costs = cost_model.compute(
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        fill_price=fill_price,
        half_spread=Decimal("0"),
        is_short=request.is_short,
    )

    pending_acks.append(OrderAck(
        timestamp_ns=fill_ts,
        correlation_id=request.correlation_id,
        sequence=ack_seq.next(),
        order_id=request.order_id,
        symbol=request.symbol,
        status=OrderAckStatus.FILLED,
        filled_quantity=request.quantity,
        fill_price=fill_price,
        fees=costs.total_fees,
        cost_bps=costs.cost_bps,
        request_sequence=request.sequence,
    ))
