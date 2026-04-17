"""Backtest order router — simulated fills for backtest mode.

Implements the ``OrderRouter`` protocol with an immediate mid-price
fill model.  This is a v1 placeholder; the backtest-engine skill
specifies a full queue-priority fill model with adverse selection
and partial fills.

Fill semantics:
  - Orders are acknowledged immediately on submit (ACKNOWLEDGED ack
    emitted first, for parity with the live-mode state machine).
  - Orders are then filled at mid-price of the most recent quote
    for that symbol.
  - If no quote has been seen for the symbol, the order is rejected.
  - If the quote is crossed or locked (bid >= ask), the order is
    rejected rather than silently filling at a dubious mid.
  - If the relevant L1 depth is zero, the order is rejected rather
    than silently filling at mid against a vacuum.
  - When the requested quantity exceeds the L1 available depth
    (``bid_size`` for sells, ``ask_size`` for buys), the fill is
    split into two acks (D14 partial fill model):
      1. ``PARTIALLY_FILLED`` for the available depth at mid-price.
      2. ``FILLED`` for the remainder at a slippage-adjusted price
         modelling walk-the-book impact (2d).
    Slippage for the excess = market_impact_factor × (excess / depth)
    × half-spread, capped at ``max_impact_half_spreads`` multiples
    of the half-spread to avoid unbounded prices on very thin books.
    Impact is directionally applied (buyer pays more, seller
    receives less).  Minimum slippage is zero (price never inverts).

Invariants preserved:
  - Inv 9 (backtest/live parity): implements the same OrderRouter
    protocol used by live and paper routers; emits ACKNOWLEDGED
    before any fill so the order SM trace matches live.
  - Inv 5 (deterministic replay): fill prices are derived from
    deterministic market data, not random noise.
  - Inv 11 (fail-safe): duplicate order_id submissions are rejected
    rather than silently producing a second fill.
"""

from __future__ import annotations

import math
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    Side,
)
from feelies.execution.cost_model import CostModel, ZeroCostModel


def _to_decimal(value: Decimal | int | str | float, name: str) -> Decimal:
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


class BacktestOrderRouter:
    """Simulated order router for backtest mode.

    Maintains last-seen quotes per symbol.  The orchestrator must
    call ``on_quote()`` for each incoming quote so the router has
    price context for fills.

    ``market_impact_factor``: scales the magnitude of the walk-the-book
    slippage applied to the excess portion of a large order (beyond L1
    available depth).  Default 0.5 (50% of one half-spread per full-
    depth multiple of excess).
    ``max_impact_half_spreads``: cap on the impact premium, expressed
    in multiples of the half-spread.  Default 10 — a single order
    cannot move the fill price more than 10 half-spreads beyond mid,
    even against a 1-lot book.  Protects against unbounded slippage
    on thin quotes.
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        cost_model: CostModel | None = None,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._market_impact_factor = _to_decimal(
            market_impact_factor, "market_impact_factor"
        )
        self._max_impact_half_spreads = _to_decimal(
            max_impact_half_spreads, "max_impact_half_spreads"
        )
        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._submitted_order_ids: set[str] = set()

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote for a symbol.

        Called by the bootstrap wiring (bus subscription) or
        explicitly by the caller before each tick.
        """
        self._last_quotes[quote.symbol] = quote

    def submit(self, request: OrderRequest) -> None:
        if request.order_id in self._submitted_order_ids:
            self._reject(request, f"duplicate order_id: {request.order_id}")
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._reject(request, "no quote available for symbol")
            return

        # Crossed/locked quotes produce nonsensical fills — reject.
        if quote.bid >= quote.ask:
            self._reject(
                request,
                f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
            )
            return

        # Emit ACKNOWLEDGED first for live-mode SM parity (Inv 9).
        ack_ts = self._clock.now_ns() + self._latency_ns
        self._pending_acks.append(OrderAck(
            timestamp_ns=ack_ts,
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
        ))

        fill_price = (quote.bid + quote.ask) / Decimal("2")
        half_spread = (quote.ask - quote.bid) / Decimal("2")
        fill_ts = ack_ts

        # Available L1 depth on the relevant side.
        available_depth = (
            quote.ask_size if request.side == Side.BUY else quote.bid_size
        )

        # Zero-depth on the relevant side means no reasonable fill is
        # possible — reject rather than silently filling at mid against
        # a vacuum.
        if available_depth <= 0:
            self._reject(
                request,
                f"zero depth on {request.side.name} side "
                f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
            )
            return

        if request.quantity > available_depth:
            # ── Part 1: fill available depth at mid-price ──────
            partial_qty = available_depth
            partial_costs = self._cost_model.compute(
                symbol=request.symbol,
                side=request.side,
                quantity=partial_qty,
                fill_price=fill_price,
                half_spread=half_spread,
                is_short=request.is_short,
            )
            self._pending_acks.append(OrderAck(
                timestamp_ns=fill_ts,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.PARTIALLY_FILLED,
                filled_quantity=partial_qty,
                fill_price=fill_price,
                fees=partial_costs.total_fees,
                cost_bps=partial_costs.cost_bps,
            ))

            # ── Part 2: fill remainder with market-impact premium ──
            # Capped at max_impact_half_spreads × half_spread so a
            # single large order against a thin book cannot produce
            # unbounded prices.
            excess_qty = request.quantity - available_depth
            raw_impact = (
                self._market_impact_factor
                * Decimal(str(excess_qty))
                / Decimal(str(available_depth))
                * half_spread
            )
            impact_cap = self._max_impact_half_spreads * half_spread
            impact = min(raw_impact, impact_cap)
            if request.side == Side.BUY:
                impact_price = fill_price + impact
            else:
                impact_price = max(fill_price - impact, Decimal("0.01"))

            # Attribute the full per-share slippage of the excess leg
            # (half_spread for the mid crossing + impact premium) to
            # the cost model so cost_bps reflects the true cost.
            excess_costs = self._cost_model.compute(
                symbol=request.symbol,
                side=request.side,
                quantity=excess_qty,
                fill_price=impact_price,
                half_spread=half_spread + impact,
                is_short=request.is_short,
            )
            self._pending_acks.append(OrderAck(
                timestamp_ns=fill_ts,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.FILLED,
                filled_quantity=excess_qty,
                fill_price=impact_price,
                fees=excess_costs.total_fees,
                cost_bps=excess_costs.cost_bps,
            ))
            return

        # Normal path: full fill at mid-price.
        costs = self._cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=fill_price,
            half_spread=half_spread,
            is_short=request.is_short,
        )

        self._pending_acks.append(OrderAck(
            timestamp_ns=fill_ts,
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=request.quantity,
            fill_price=fill_price,
            fees=costs.total_fees,
            cost_bps=costs.cost_bps,
        ))

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    def _reject(self, request: OrderRequest, reason: str) -> None:
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
        ))
