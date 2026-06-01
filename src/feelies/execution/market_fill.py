"""Shared mid-price MARKET simulation — D14 partial fill + walk-the-book impact.

:class:`~feelies.execution.backtest_router.BacktestOrderRouter` and
:class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter` both
delegate aggressive fills here so deferred MARKET paths cannot silently diverge
under ``latency_ns > 0`` (Inv-9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel


@dataclass(frozen=True)
class DeferredFill:
    """A MARKET / marketable order awaiting exchange-time fill eligibility.

    Shared by :class:`~feelies.execution.backtest_router.BacktestOrderRouter`
    (where it models a deferred MARKET fill) and
    :class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter`
    (deferred aggressive fill).  Both routers previously carried byte-identical
    private copies of this record; unifying it keeps the latency / monotonic-ack
    contract from drifting between the two paths (Inv 9).

    Fields:

    - ``request``: the originating :class:`OrderRequest`.
    - ``fill_deadline_exchange_ns``: exchange time at which the order becomes
      fill-eligible (``submission_quote.exchange_timestamp_ns + latency_ns``).
    - ``ack_timestamp_ns``: the ACKNOWLEDGED ack timestamp emitted at submit;
      FILLED / REJECTED timestamps are floored at this so they can never
      precede ACKNOWLEDGED even when exchange time has not yet reached the
      latency deadline.
    - ``ticks_for_symbol``: count of matching-symbol quotes seen while waiting,
      used to time out after ``max_resting_ticks`` (Inv 11 fail-safe).
    """

    request: OrderRequest
    fill_deadline_exchange_ns: int
    ack_timestamp_ns: int
    ticks_for_symbol: int = 0


def append_reject_ack(
    pending_acks: list[OrderAck],
    ack_seq: SequenceGenerator,
    submitted_order_ids: set[str],
    clock_now_ns: int,
    request: OrderRequest,
    reason: str,
    *,
    timestamp_ns: int | None = None,
    release_submitted_id: bool = True,
) -> None:
    """Append a REJECTED ack for ``request`` (shared router reject path).

    Clears ``request.order_id`` from ``submitted_order_ids`` unless
    ``release_submitted_id=False`` (duplicate submissions, where the id may
    still belong to an in-flight resting / deferred order).  ``clock_now_ns``
    is the caller's current clock reading, used when ``timestamp_ns`` is not
    supplied.
    """
    ts = clock_now_ns if timestamp_ns is None else timestamp_ns
    pending_acks.append(OrderAck(
        timestamp_ns=ts,
        correlation_id=request.correlation_id,
        sequence=ack_seq.next(),
        order_id=request.order_id,
        symbol=request.symbol,
        status=OrderAckStatus.REJECTED,
        reason=reason,
        request_sequence=request.sequence,
    ))
    if release_submitted_id:
        submitted_order_ids.discard(request.order_id)


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
    mid = (quote.bid + quote.ask) / Decimal("2")
    fill_price = _clamp_fill_price_to_limit(request.side, mid, limit_px)
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
            raw_impact_px = mid + impact
        else:
            raw_impact_px = max(mid - impact, Decimal("0.01"))
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
