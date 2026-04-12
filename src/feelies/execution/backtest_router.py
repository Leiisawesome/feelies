"""Backtest order router — simulated fills for backtest mode.

Implements the ``OrderRouter`` protocol with an immediate mid-price
fill model.  This is a v1 placeholder; the backtest-engine skill
specifies a full queue-priority fill model with adverse selection
and partial fills.

Fill semantics:
  - Orders are filled immediately on submit at mid-price of the
    most recent quote for that symbol.
  - If no quote has been seen for the symbol, the order is rejected.
  - When the requested quantity exceeds the L1 available depth
    (``bid_size`` for sells, ``ask_size`` for buys), the fill is
    split into two acks (D14 partial fill model):
      1. ``PARTIALLY_FILLED`` for the available depth at mid-price.
      2. ``FILLED`` for the remainder at a slippage-adjusted price
         modelling walk-the-book impact (2d).
    Slippage for the excess = market_impact_factor × (excess / depth)
    × half-spread, directionally applied (buyer pays more, seller
    receives less).  Minimum slippage is zero (price never inverts).

Invariants preserved:
  - Inv 9 (backtest/live parity): implements the same OrderRouter
    protocol used by live and paper routers.
  - Inv 5 (deterministic replay): fill prices are derived from
    deterministic market data, not random noise.
"""

from __future__ import annotations

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


class BacktestOrderRouter:
    """Simulated order router for backtest mode.

    Maintains last-seen quotes per symbol.  The orchestrator must
    call ``on_quote()`` for each incoming quote so the router has
    price context for fills.

    ``market_impact_factor``: scales the magnitude of the walk-the-book
    slippage applied to the excess portion of a large order (beyond L1
    available depth).  Default 0.5 (50% of one half-spread per full-
    depth multiple of excess).
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        cost_model: CostModel | None = None,
        market_impact_factor: float = 0.5,
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._market_impact_factor = Decimal(str(market_impact_factor))
        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote for a symbol.

        Called by the bootstrap wiring (bus subscription) or
        explicitly by the caller before each tick.
        """
        self._last_quotes[quote.symbol] = quote

    def submit(self, request: OrderRequest) -> None:
        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._pending_acks.append(OrderAck(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.REJECTED,
                reason="no quote available for symbol",
            ))
            return

        fill_price = (quote.bid + quote.ask) / Decimal("2")
        half_spread = (quote.ask - quote.bid) / Decimal("2")
        fill_ts = self._clock.now_ns() + self._latency_ns

        # D14 / 2d: partial fill + walk-the-book slippage when order
        # size exceeds the available L1 depth on the relevant side.
        available_depth = (
            quote.ask_size if request.side == Side.BUY else quote.bid_size
        )

        if available_depth > 0 and request.quantity > available_depth:
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
            excess_qty = request.quantity - available_depth
            impact = (
                self._market_impact_factor
                * Decimal(str(excess_qty))
                / Decimal(str(available_depth))
                * half_spread
            )
            if request.side == Side.BUY:
                impact_price = fill_price + impact
            else:
                impact_price = max(fill_price - impact, Decimal("0.01"))

            excess_costs = self._cost_model.compute(
                symbol=request.symbol,
                side=request.side,
                quantity=excess_qty,
                fill_price=impact_price,
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

