"""Passive limit order router — queue-position fill model for backtest mode.

Implements the ``OrderRouter`` protocol with a passive limit order fill
model.  Instead of crossing the spread (market orders), entry orders
post limit orders at the near side of the BBO and fill via a deterministic
queue-drain model.

Fill model (L1-only, conservative):
  LIMIT orders rest at ``limit_price`` (bid for BUY, ask for SELL).
  Two fill triggers:

  1. **Through fill**: the opposite BBO crosses our level.
     - BUY:  ``ask <= limit_price`` (sellers met us)
     - SELL: ``bid >= limit_price`` (buyers met us)
     Fill is guaranteed at ``limit_price``.

  2. **Level fill**: our level remains the BBO for ``fill_delay_ticks``
     consecutive quotes, modeling the queue ahead of us draining.
     Counter resets if the BBO moves away from our level.

  Unfilled orders are cancelled after ``max_resting_ticks`` quotes.

  MARKET orders fill immediately at mid-price (identical to
  ``BacktestOrderRouter``), used for stop-loss and emergency exits.

Invariants preserved:
  - Inv 5 (deterministic replay): no randomness — queue drain is a
    deterministic tick counter.
  - Inv 9 (backtest/live parity): implements the same OrderRouter
    protocol used by live and paper routers.
  - Inv 11 (fail-safe): MARKET orders always fill immediately;
    passive orders that timeout are CANCELLED, not silently dropped.
  - Inv 12 (transaction cost realism): passive fills charge zero
    spread cost and optionally model maker rebates.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.cost_model import CostModel, ZeroCostModel


@dataclass
class _PendingOrder:
    """Mutable state for a resting limit order."""

    request: OrderRequest
    side: Side
    limit_price: Decimal
    submit_time_ns: int
    ticks_at_level: int = 0
    total_ticks: int = 0


class PassiveLimitOrderRouter:
    """Simulated order router with passive limit order fill model.

    Handles two order types:
      - ``LIMIT``: deferred fill via queue-position model (entries/exits)
      - ``MARKET``: immediate mid-price fill (stop-loss, emergency exits)

    The orchestrator must call ``on_quote()`` for each incoming quote
    so the router can (a) track the latest NBBO and (b) check resting
    orders for fill conditions.
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        cost_model: CostModel | None = None,
        *,
        fill_delay_ticks: int = 3,
        max_resting_ticks: int = 50,
        rebate_per_share: Decimal = Decimal("0.002"),
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._fill_delay_ticks = fill_delay_ticks
        self._max_resting_ticks = max_resting_ticks
        self._rebate_per_share = rebate_per_share

        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._resting_orders: dict[str, _PendingOrder] = {}

    # ── Public interface (OrderRouter protocol) ──────────────────

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update latest quote and check resting orders for fills."""
        self._last_quotes[quote.symbol] = quote
        self._check_resting_orders(quote)

    def submit(self, request: OrderRequest) -> None:
        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._reject(request, "no quote available for symbol")
            return

        if request.order_type == OrderType.MARKET:
            self._fill_aggressive(request, quote)
        elif request.order_type == OrderType.LIMIT:
            self._post_passive(request, quote)
        else:
            self._reject(request, f"unsupported order type: {request.order_type}")

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    # ── Aggressive (market) fills ────────────────────────────────

    def _fill_aggressive(self, request: OrderRequest, quote: NBBOQuote) -> None:
        """Immediate fill at mid-price — same economics as BacktestOrderRouter."""
        fill_price = (quote.bid + quote.ask) / Decimal("2")
        half_spread = (quote.ask - quote.bid) / Decimal("2")
        fill_ts = self._clock.now_ns() + self._latency_ns

        costs = self._cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=fill_price,
            half_spread=half_spread,
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

    # ── Passive (limit) order posting ────────────────────────────

    def _post_passive(self, request: OrderRequest, quote: NBBOQuote) -> None:
        """Record a resting limit order and emit ACKNOWLEDGED ack."""
        limit_price = request.limit_price
        if limit_price is None:
            limit_price = quote.bid if request.side == Side.BUY else quote.ask

        self._resting_orders[request.order_id] = _PendingOrder(
            request=request,
            side=request.side,
            limit_price=limit_price,
            submit_time_ns=self._clock.now_ns(),
        )

        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
        ))

    # ── Resting order fill checking ──────────────────────────────

    def _check_resting_orders(self, quote: NBBOQuote) -> None:
        """Evaluate all resting orders for the quoted symbol."""
        to_remove: list[str] = []

        for order_id, pending in self._resting_orders.items():
            if pending.request.symbol != quote.symbol:
                continue

            pending.total_ticks += 1
            action = self._evaluate_fill(pending, quote)

            if action == "fill":
                self._emit_passive_fill(pending)
                to_remove.append(order_id)
            elif action == "cancel":
                self._emit_timeout_cancel(pending)
                to_remove.append(order_id)

        for oid in to_remove:
            del self._resting_orders[oid]

    def _evaluate_fill(self, pending: _PendingOrder, quote: NBBOQuote) -> str:
        """Determine whether a resting order fills, cancels, or continues.

        Returns "fill", "cancel", or "wait".
        """
        if pending.side == Side.BUY:
            if quote.ask <= pending.limit_price:
                return "fill"
            if quote.bid <= pending.limit_price:
                pending.ticks_at_level += 1
                if pending.ticks_at_level >= self._fill_delay_ticks:
                    return "fill"
            else:
                pending.ticks_at_level = 0
        else:
            if quote.bid >= pending.limit_price:
                return "fill"
            if quote.ask >= pending.limit_price:
                pending.ticks_at_level += 1
                if pending.ticks_at_level >= self._fill_delay_ticks:
                    return "fill"
            else:
                pending.ticks_at_level = 0

        if pending.total_ticks >= self._max_resting_ticks:
            return "cancel"

        return "wait"

    # ── Ack emission helpers ─────────────────────────────────────
    def _reject(self, request: OrderRequest, reason: str) -> None:
        """Emit a REJECTED ack for the given order request."""
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
        ))
    def _emit_passive_fill(self, pending: _PendingOrder) -> None:
        """Emit a FILLED ack for a passive limit order."""
        fill_price = pending.limit_price
        fill_ts = self._clock.now_ns() + self._latency_ns

        costs = self._cost_model.compute(
            symbol=pending.request.symbol,
            side=pending.side,
            quantity=pending.request.quantity,
            fill_price=fill_price,
            half_spread=Decimal("0"),
        )

        rebate = self._rebate_per_share * pending.request.quantity
        total_fees = max(costs.total_fees - rebate, Decimal("0"))
        cost_bps = (
            total_fees / costs.notional * Decimal("10000")
            if costs.notional > 0 else Decimal("0")
        )

        self._pending_acks.append(OrderAck(
            timestamp_ns=fill_ts,
            correlation_id=pending.request.correlation_id,
            sequence=pending.request.sequence,
            order_id=pending.request.order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=pending.request.quantity,
            fill_price=fill_price,
            fees=total_fees.quantize(Decimal("0.01")),
            cost_bps=cost_bps.quantize(Decimal("0.01")),
        ))

    def _emit_timeout_cancel(self, pending: _PendingOrder) -> None:
        """Emit a CANCELLED ack for a timed-out resting order."""
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=pending.request.correlation_id,
            sequence=pending.request.sequence,
            order_id=pending.request.order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.CANCELLED,
            reason=(
                f"passive limit timeout after {pending.total_ticks} ticks"
            ),
        ))

    # ── Diagnostics ──────────────────────────────────────────────

    @property
    def resting_order_count(self) -> int:
        """Number of currently resting limit orders."""
        return len(self._resting_orders)

    def resting_symbols(self) -> frozenset[str]:
        """Symbols with at least one resting limit order."""
        return frozenset(
            p.request.symbol for p in self._resting_orders.values()
        )
