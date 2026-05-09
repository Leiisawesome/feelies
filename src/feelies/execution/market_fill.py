"""Shared mid-price MARKET simulation — D14 partial fill + walk-the-book impact.

:class:`~feelies.execution.backtest_router.BacktestOrderRouter` and
:class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter` both
delegate aggressive fills here so deferred MARKET paths cannot silently diverge
under ``latency_ns > 0`` (Inv-9).
"""

from __future__ import annotations

import math
from decimal import Decimal

from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel


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
    fill_price = (quote.bid + quote.ask) / Decimal("2")
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
            half_spread=half_spread,
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
        if request.side == Side.BUY:
            impact_price = fill_price + impact
        else:
            impact_price = max(fill_price - impact, Decimal("0.01"))

        excess_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=excess_qty,
            fill_price=impact_price,
            half_spread=half_spread,
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
        half_spread=half_spread,
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
