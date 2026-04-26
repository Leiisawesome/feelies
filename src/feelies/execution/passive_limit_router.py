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
    passive orders that timeout are CANCELLED, not silently dropped;
    duplicate order_ids are rejected.
  - Inv 12 (transaction cost realism): passive fills charge zero
    spread cost and optionally model maker rebates.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from feelies.core.clock import Clock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
    Trade,
)
from feelies.execution.cost_model import CostModel, ZeroCostModel


@dataclass
class _PendingOrder:
    """Mutable state for a resting limit order."""

    request: OrderRequest
    side: Side
    limit_price: Decimal
    submit_time_ns: int
    # Per-order queue threshold captured at post time.  Allows callers
    # to override the default via ``set_queue_ahead`` if they need a
    # per-order sampled position rather than a global assumption.
    queue_ahead_shares: int = 0
    ticks_at_level: int = 0
    total_ticks: int = 0
    shares_traded_at_level: int = 0


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
        queue_position_shares: int = 0,
        cancel_fee_per_share: Decimal = Decimal("0.0"),
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._fill_delay_ticks = fill_delay_ticks
        self._max_resting_ticks = max_resting_ticks
        self._queue_position_shares = queue_position_shares
        self._cancel_fee_per_share = cancel_fee_per_share

        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._resting_orders: dict[str, _PendingOrder] = {}
        # Symbol → order_ids index so on_quote() is O(k) in the number
        # of orders for that symbol rather than O(n) across all orders.
        self._resting_by_symbol: dict[str, set[str]] = {}
        # Full set of order_ids ever submitted — used for idempotent reject.
        self._submitted_order_ids: set[str] = set()

    # ── Public interface (OrderRouter protocol) ──────────────────

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update latest quote and check resting orders for fills."""
        self._last_quotes[quote.symbol] = quote
        self._check_resting_orders(quote)

    def on_trade(self, trade: Trade) -> None:
        """Accumulate traded volume for the queue-position fill model.

        For each resting order at the traded symbol with a non-zero
        per-order ``queue_ahead_shares`` (or any resting order when
        the global ``queue_position_shares`` is set), adds the trade
        size to ``shares_traded_at_level`` if the trade price is at or
        through our limit price (i.e. the order queue is draining).
        """
        order_ids = self._resting_by_symbol.get(trade.symbol)
        if not order_ids:
            return
        for order_id in order_ids:
            pending = self._resting_orders[order_id]
            if pending.queue_ahead_shares <= 0:
                continue
            if pending.side == Side.BUY and trade.price <= pending.limit_price:
                pending.shares_traded_at_level += trade.size
            elif pending.side == Side.SELL and trade.price >= pending.limit_price:
                pending.shares_traded_at_level += trade.size

    def submit(self, request: OrderRequest) -> None:
        if request.order_id in self._submitted_order_ids:
            self._reject(request, f"duplicate order_id: {request.order_id}")
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._reject(request, "no quote available for symbol")
            return

        # Crossed (bid > ask) quotes are data errors; locked (bid == ask)
        # leaves no passive side and breaks the marketability guard.
        if quote.bid >= quote.ask:
            self._reject(
                request,
                f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
            )
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
        """Immediate fill at mid-price — same economics as BacktestOrderRouter.

        ``submit()`` is the only caller and has already validated that the
        quote is non-crossed, so we do not re-check here.
        """
        fill_price = (quote.bid + quote.ask) / Decimal("2")
        half_spread = (quote.ask - quote.bid) / Decimal("2")
        fill_ts = self._clock.now_ns() + self._latency_ns

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

    # ── Passive (limit) order posting ────────────────────────────

    def _post_passive(self, request: OrderRequest, quote: NBBOQuote) -> None:
        """Record a resting limit order and emit ACKNOWLEDGED ack."""
        limit_price = request.limit_price
        if limit_price is None:
            limit_price = quote.bid if request.side == Side.BUY else quote.ask

        # D13: marketability guard — if the limit price would immediately
        # cross the spread, redirect to aggressive fill to avoid posting
        # a marketable limit order (which exchanges reject or fill as taker).
        if request.side == Side.BUY and limit_price >= quote.ask:
            self._fill_aggressive(request, quote)
            return
        if request.side == Side.SELL and limit_price <= quote.bid:
            self._fill_aggressive(request, quote)
            return

        pending = _PendingOrder(
            request=request,
            side=request.side,
            limit_price=limit_price,
            submit_time_ns=self._clock.now_ns(),
            queue_ahead_shares=self._queue_position_shares,
        )
        self._resting_orders[request.order_id] = pending
        self._resting_by_symbol.setdefault(request.symbol, set()).add(
            request.order_id
        )

        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
        ))

    def set_queue_ahead(self, order_id: str, shares: int) -> bool:
        """Override the queue-ahead threshold for a specific resting order.

        Allows per-order queue-position sampling (e.g. drawn from an
        exchange-specific distribution) rather than the global default.
        Returns True if the order was found.
        """
        pending = self._resting_orders.get(order_id)
        if pending is None:
            return False
        pending.queue_ahead_shares = shares
        return True

    # ── Resting order fill checking ──────────────────────────────

    def _check_resting_orders(self, quote: NBBOQuote) -> None:
        """Evaluate all resting orders for the quoted symbol."""
        order_ids = self._resting_by_symbol.get(quote.symbol)
        if not order_ids:
            return

        to_remove: list[str] = []

        for order_id in order_ids:
            pending = self._resting_orders[order_id]
            pending.total_ticks += 1
            action = self._evaluate_fill(pending, quote)

            if action == "fill":
                self._emit_passive_fill(pending)
                to_remove.append(order_id)
            elif action == "cancel":
                self._emit_timeout_cancel(pending)
                to_remove.append(order_id)

        for oid in to_remove:
            self._remove_resting(oid)

    def _evaluate_fill(self, pending: _PendingOrder, quote: NBBOQuote) -> str:
        """Determine whether a resting order fills, cancels, or continues.

        Returns "fill", "cancel", or "wait".

        Two fill trigger modes:
          - Queue-position: if the order's ``queue_ahead_shares > 0``,
            the level-fill triggers when accumulated trade volume at
            our level reaches that threshold.  More realistic than
            tick counting on high-frequency quote streams.
          - Tick-based (legacy): if ``queue_ahead_shares == 0``, the
            original counter fires after ``fill_delay_ticks`` consecutive
            quotes at our level.
        """
        if pending.side == Side.BUY:
            if quote.ask <= pending.limit_price:
                return "fill"
            if quote.bid <= pending.limit_price:
                if pending.queue_ahead_shares > 0:
                    if pending.shares_traded_at_level >= pending.queue_ahead_shares:
                        return "fill"
                else:
                    pending.ticks_at_level += 1
                    if pending.ticks_at_level >= self._fill_delay_ticks:
                        return "fill"
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0
        else:
            if quote.bid >= pending.limit_price:
                return "fill"
            if quote.ask >= pending.limit_price:
                if pending.queue_ahead_shares > 0:
                    if pending.shares_traded_at_level >= pending.queue_ahead_shares:
                        return "fill"
                else:
                    pending.ticks_at_level += 1
                    if pending.ticks_at_level >= self._fill_delay_ticks:
                        return "fill"
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0

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
        """Emit a FILLED ack for a passive limit order.

        Calls the cost model with ``is_taker=False`` so the maker rebate
        and adverse-selection penalty are applied by the model — no
        separate rebate subtraction needed here.
        """
        fill_price = pending.limit_price
        fill_ts = self._clock.now_ns() + self._latency_ns

        costs = self._cost_model.compute(
            symbol=pending.request.symbol,
            side=pending.side,
            quantity=pending.request.quantity,
            fill_price=fill_price,
            half_spread=Decimal("0"),
            is_taker=False,
            is_short=pending.request.is_short,
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
            fees=costs.total_fees,
            cost_bps=costs.cost_bps,
        ))

    def _cancel_fees(self, quantity: int) -> Decimal:
        """Deterministically quantized cancel-fee computation."""
        return (self._cancel_fee_per_share * quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def _emit_timeout_cancel(self, pending: _PendingOrder) -> None:
        """Emit a CANCELLED ack for a timed-out resting order."""
        cancel_fees = self._cancel_fees(pending.request.quantity)
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
            fees=cancel_fees if cancel_fees > 0 else Decimal("0"),
        ))

    # ── Explicit cancellation ───────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific resting order.

        Returns True if the order was found and cancelled.  The
        cancellation ack is queued for the next ``poll_acks()`` call.
        """
        pending = self._resting_orders.get(order_id)
        if pending is None:
            return False
        cancel_fees = self._cancel_fees(pending.request.quantity)
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=pending.request.correlation_id,
            sequence=pending.request.sequence,
            order_id=order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.CANCELLED,
            reason="client_cancel",
            fees=cancel_fees if cancel_fees > 0 else Decimal("0"),
        ))
        self._remove_resting(order_id)
        return True

    def _remove_resting(self, order_id: str) -> None:
        pending = self._resting_orders.pop(order_id, None)
        if pending is None:
            return
        symbol_set = self._resting_by_symbol.get(pending.request.symbol)
        if symbol_set is not None:
            symbol_set.discard(order_id)
            if not symbol_set:
                del self._resting_by_symbol[pending.request.symbol]

    # ── Diagnostics ──────────────────────────────────────────────

    @property
    def resting_order_count(self) -> int:
        """Number of currently resting limit orders."""
        return len(self._resting_orders)

    def resting_symbols(self) -> frozenset[str]:
        """Symbols with at least one resting limit order."""
        return frozenset(self._resting_by_symbol.keys())

    @property
    def requires_trade_feed(self) -> bool:
        """True when ``on_trade()`` must be wired for correct fills.

        When the queue-position mode is enabled (``queue_position_shares > 0``
        at construction, or any order has a non-zero per-order threshold),
        level fills only fire when accumulated trade volume reaches the
        threshold.  Without a trade feed subscription those orders never
        fill by queue drain and silently degrade — callers should wire
        ``on_trade`` when this is True.
        """
        return self._queue_position_shares > 0
