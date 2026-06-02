"""Shared aggressive-fill logic used by both routers (audit F-H-11).

Both ``BacktestOrderRouter`` and ``PassiveLimitOrderRouter`` need an
identical aggressive (market) fill model:

  - Reject on zero L1 depth on the relevant side.
  - Fill up to L1 depth at mid-price (PARTIAL_FILLED).
  - Fill excess at impact-adjusted price (FILLED), with impact capped
    at ``max_impact_half_spreads × half_spread``.
  - Otherwise fill the full quantity at mid (FILLED).

Previously this logic lived only in ``BacktestOrderRouter.submit`` —
``PassiveLimitOrderRouter._fill_aggressive`` filled the entire quantity
at mid regardless of size, silently producing a cheaper fill in passive
and minimum-cost execution modes than the equivalent operation in
market mode.  This helper unifies the two paths.

The helper appends acks to a caller-supplied list and uses the
caller's ack sequence generator — both routers' ack-emission ordering
remains deterministic per ``SequenceGenerator`` (Inv-5).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    Side,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel


STOP_EXIT_REASONS: frozenset[str] = frozenset({
    "STOP_EXIT", "HARD_EXIT_AGE", "HAZARD_SPIKE", "FORCE_FLATTEN",
})


def emit_aggressive_fill(
    *,
    request: OrderRequest,
    quote: NBBOQuote,
    fill_ts: int,
    cost_model: CostModel,
    market_impact_factor: Decimal,
    max_impact_half_spreads: Decimal,
    pending_acks: list[OrderAck],
    ack_seq: SequenceGenerator,
    reject: Callable[[OrderRequest, str], None],
    stop_slippage_half_spreads: Decimal = Decimal("1"),
) -> None:
    """Execute an aggressive (market) fill against ``quote``.

    Emits PARTIAL_FILLED + FILLED on walk-the-book; FILLED otherwise.
    Rejects via ``reject`` callback on locked/crossed quote or zero
    L1 depth.  Determinism preserved via the caller's ``ack_seq``.

    Audit F-H-10: when ``request.reason`` is in ``STOP_EXIT_REASONS``,
    the spread component is inflated by ``stop_slippage_half_spreads``
    to model the panic-slippage that real stop-loss / hazard exits pay
    in depleted depth.  Fill price stays at mid; the extra slippage
    flows through ``fees`` (consistent with the spread-in-fees
    convention).  Multiplier defaults to 1 for non-stop fills.
    """
    if quote.bid >= quote.ask:
        reject(
            request,
            f"crossed or locked quote at fill time bid={quote.bid} ask={quote.ask}",
        )
        return

    fill_price = (quote.bid + quote.ask) / Decimal("2")
    raw_half_spread = (quote.ask - quote.bid) / Decimal("2")

    # Audit F-H-10: stop-exit / forced-flatten fills pay panic slippage.
    is_stop_exit = request.reason in STOP_EXIT_REASONS
    if is_stop_exit and stop_slippage_half_spreads > Decimal("1"):
        half_spread = raw_half_spread * stop_slippage_half_spreads
    else:
        half_spread = raw_half_spread

    available_depth = (
        quote.ask_size if request.side == Side.BUY else quote.bid_size
    )
    if available_depth <= 0:
        reject(
            request,
            f"zero depth on {request.side.name} side "
            f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
        )
        return

    if request.quantity > available_depth:
        # ── L1 leg ────────────────────────────────────────────────
        partial_qty = available_depth
        partial_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=partial_qty,
            fill_price=fill_price,
            half_spread=half_spread,
            is_short=request.is_short,
        )
        # Audit F-M-27: distinct timestamps for partial vs final fill so
        # forensic timelines can distinguish the two events.  1 ns
        # monotonic offset preserves ordering and determinism.
        partial_ts = fill_ts
        final_ts = fill_ts + 1
        pending_acks.append(OrderAck(
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
        ))

        # ── Excess leg (walk-the-book impact) ─────────────────────
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

        # Plain half_spread (no double-count): impact is in fill_price.
        excess_costs = cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=excess_qty,
            fill_price=impact_price,
            half_spread=half_spread,
            is_short=request.is_short,
        )
        pending_acks.append(OrderAck(
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
        ))
        return

    # Normal path: full fill at mid.
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


__all__ = ["emit_aggressive_fill"]
