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
from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution._fill_helpers import STOP_EXIT_REASONS
from feelies.execution.cost_model import CostModel
from feelies.execution.tick_size import snap_fill_price


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
    pending_acks.append(
        OrderAck(
            timestamp_ns=ts,
            correlation_id=request.correlation_id,
            sequence=ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
            request_sequence=request.sequence,
        )
    )
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


def base_impact_premium(
    *,
    quantity: int,
    available_depth: int,
    raw_half_spread: Decimal,
    within_l1_impact_factor: Decimal,
    permanent_impact_coefficient: Decimal,
) -> Decimal:
    """Participation-based impact premium charged on the *within-L1* leg.

    Audit 2026-06-19 (P1.3 + P2.11): the legacy model charged market impact
    only on the *excess* above displayed L1 depth, so any order sized at or
    below the touch filled at the pure cross with zero impact.  This premium
    closes that gap with two additive, default-off terms (both measured in
    half-spread units, so they vanish when their coefficients are 0):

    * **Temporary (linear in participation):**
      ``within_l1_impact_factor × min(qty/depth, 1) × half_spread``.
    * **Permanent (square-root law):**
      ``permanent_impact_coefficient × sqrt(qty/depth) × half_spread``.

    ``Decimal.sqrt`` is correctly-rounded and platform-independent (unlike
    ``math.sqrt``), so replay stays bit-identical (Inv-5).
    """
    if available_depth <= 0 or quantity <= 0:
        return Decimal("0")
    if within_l1_impact_factor <= 0 and permanent_impact_coefficient <= 0:
        return Decimal("0")
    participation = Decimal(quantity) / Decimal(available_depth)
    capped = participation if participation < Decimal("1") else Decimal("1")
    temporary = within_l1_impact_factor * capped * raw_half_spread
    permanent = permanent_impact_coefficient * participation.sqrt() * raw_half_spread
    return temporary + permanent


def _apply_premium(side: Side, cross: Decimal, premium: Decimal) -> Decimal:
    """Move ``cross`` against the taker by ``premium`` (BUY up, SELL down)."""
    if premium <= 0:
        return cross
    if side == Side.BUY:
        return cross + premium
    return max(cross - premium, Decimal("0.01"))


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
    stop_slippage_half_spreads: Decimal = Decimal("1"),
    within_l1_impact_factor: Decimal = Decimal("0"),
    permanent_impact_coefficient: Decimal = Decimal("0"),
    stop_depth_depletion_factor: Decimal = Decimal("1"),
) -> None:
    """Append FILLED / PARTIALLY_FILLED acks for a MARKET-style fill at L1.

    Caller must ensure the quote is non-crossed and L1 depth on the relevant
    side is strictly positive.

    ``within_l1_impact_factor`` / ``permanent_impact_coefficient`` (audit
    P1.3 / P2.11) add participation-based impact to the within-L1 leg (see
    :func:`base_impact_premium`); both default 0 (legacy: impact only on the
    excess-over-L1 leg).  ``stop_depth_depletion_factor`` (audit P2.9, default
    1.0) shrinks the effective L1 depth a forced exit fills against, so a
    stop / hazard / force-flatten walks deeper into a depleted book.
    """
    limit_px = request.limit_price
    if limit_px is not None:
        # Snap the limit on the *taker* grid (BUY-ceil / SELL-floor) — the
        # passive-side ``snap_limit_price`` (BUY-floor / SELL-ceil) would
        # cap the BUY clamp *below* the lifted ask (and the SELL clamp
        # *above* the hit bid) for sub-penny marketable limits, inventing
        # price improvement the taker shouldn't receive.
        limit_px = snap_fill_price(request.side, limit_px)
    # BT-3: fill at the executed cross price (BUY lifts the ask, SELL hits
    # the bid), not the synthetic mid.  The half-spread is embedded in the
    # price, so the cost model is called with half_spread=0 (no separate
    # spread_cost fee).  ``half_spread`` is still used to *size* the
    # walk-the-book impact below, which is measured in half-spread units.
    cross = quote.ask if request.side == Side.BUY else quote.bid
    raw_half_spread = (quote.ask - quote.bid) / Decimal("2")
    is_stop_exit = request.reason in STOP_EXIT_REASONS
    if is_stop_exit and stop_slippage_half_spreads > Decimal("1"):
        fee_half_spread = raw_half_spread * (stop_slippage_half_spreads - Decimal("1"))
    else:
        fee_half_spread = Decimal("0")

    l1_depth = quote.ask_size if request.side == Side.BUY else quote.bid_size
    # P2.9: a forced exit fills into a depleted book — shrink the effective
    # L1 depth so more of the order walks the book (and the participation
    # ratio rises).  Default factor 1.0 is an exact no-op.
    available_depth = l1_depth
    if is_stop_exit and stop_depth_depletion_factor > Decimal("1"):
        depleted = int(Decimal(l1_depth) / stop_depth_depletion_factor)
        available_depth = max(1, depleted)

    # P1.3 / P2.11: participation impact charged on the within-L1 leg.
    within_premium = base_impact_premium(
        quantity=request.quantity,
        available_depth=available_depth,
        raw_half_spread=raw_half_spread,
        within_l1_impact_factor=within_l1_impact_factor,
        permanent_impact_coefficient=permanent_impact_coefficient,
    )
    # Snap first, then clamp: ``snap_fill_price`` ceils BUY / floors SELL,
    # which can push a clamped sub-tick price *across* the limit.  Snapping
    # before clamping ensures the final price is bounded by the on-grid
    # ``limit_px`` (BT-14 limit-violation guard).
    fill_price = _clamp_fill_price_to_limit(
        request.side,
        snap_fill_price(request.side, _apply_premium(request.side, cross, within_premium)),
        limit_px,
    )

    if request.quantity > available_depth:
        partial_qty = available_depth
        partial_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=partial_qty,
            fill_price=fill_price,
            half_spread=fee_half_spread,
            is_short=request.is_short,
        )
        partial_ts = fill_ts
        final_ts = fill_ts + 1
        pending_acks.append(
            OrderAck(
                timestamp_ns=partial_ts,
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
            )
        )

        excess_qty = request.quantity - available_depth
        raw_impact = (
            market_impact_factor
            * Decimal(str(excess_qty))
            / Decimal(str(available_depth))
            * raw_half_spread
        )
        impact_cap = max_impact_half_spreads * raw_half_spread
        impact = min(raw_impact, impact_cap)
        # Walk-the-book impact stacks on top of the cross plus the within-L1
        # participation premium (above the ask for buys, below the bid for
        # sells).
        raw_impact_px = _apply_premium(request.side, cross, within_premium + impact)
        impact_price = _clamp_fill_price_to_limit(
            request.side,
            snap_fill_price(request.side, raw_impact_px),
            limit_px,
        )

        excess_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=excess_qty,
            fill_price=impact_price,
            half_spread=fee_half_spread,
            is_short=request.is_short,
        )
        pending_acks.append(
            OrderAck(
                timestamp_ns=final_ts,
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
            )
        )
        return

    costs = cost_model.compute(
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        fill_price=fill_price,
        half_spread=fee_half_spread,
        is_short=request.is_short,
    )

    pending_acks.append(
        OrderAck(
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
        )
    )
