"""Deterministic L1 model for passive limit fills.

Limits rest at the near-side BBO. They fill when the opposite BBO crosses the
level or when a replay-keyed Bernoulli draw passes a queue-drain hazard. The
hash-based draw uses no RNG, so identical tapes replay identically. Timed-out
orders cancel with a classified outcome.

Market orders share the aggressive router's latency, cross-price, depth-walk,
and acknowledgement ordering. Passive fills charge no spread crossing and may
receive maker rebates.
"""

from __future__ import annotations

from collections.abc import Callable

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum

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
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel, FillType, ZeroCostModel
from feelies.execution.market_fill import (
    DeferredFill,
    append_market_fill_acks,
    append_reject_ack,
    to_decimal,
)
from feelies.execution.moc_fill import MocFillController
from feelies.execution.moc_session import MocSessionBounds
from feelies.execution.trading_session import (
    RthEntryFillGate,
    TradingSessionBounds,
)
from feelies.execution.tick_size import snap_limit_price


class PassiveFillOutcome(Enum):
    """Terminal classification of a resting passive limit order.

    Stamped onto the FILLED / CANCELLED/EXPIRED ``OrderAck.reason`` and tallied
    by :meth:`PassiveLimitOrderRouter.passive_fill_stats` for backtest
    fill-quality forensics.
    """

    FILLED_BY_THROUGH = "FILLED_BY_THROUGH"
    FILLED_BY_DRAIN = "FILLED_BY_DRAIN"
    CANCELLED_MAX_RESTING_TICKS = "CANCELLED_MAX_RESTING_TICKS"
    CANCELLED_LEVEL_LEFT_BBO = "CANCELLED_LEVEL_LEFT_BBO"


@dataclass
class _PendingOrder:
    """Mutable state for a resting limit order."""

    request: OrderRequest
    side: Side
    limit_price: Decimal
    submit_time_ns: int
    # ACKNOWLEDGED ack timestamp captured at submit so subsequent acks
    # (CANCELLED on timeout / explicit cancel) can be floored at it to
    # preserve monotonic per-order ack ordering even when ``clock.now_ns()``
    # has not yet advanced past the post timestamp.
    ack_timestamp_ns: int = 0
    # Per-order queue threshold captured at post time.  Allows callers
    # to override the default via ``set_queue_ahead`` if they need a
    # per-order sampled position rather than a global assumption.
    queue_ahead_shares: int = 0
    ticks_at_level: int = 0
    total_ticks: int = 0
    shares_traded_at_level: int = 0
    # Cumulative quantity across capped through-fills.
    filled_quantity: int = 0
    # Whether the order was resting at the BBO on the most recent quote
    # evaluation — used to classify a timeout cancel as
    # CANCELLED_MAX_RESTING_TICKS (competitive at cancel) vs
    # CANCELLED_LEVEL_LEFT_BBO (behind the market at cancel).
    at_bbo: bool = False


# Share DeferredFill with the market router so latency and ack ordering stay aligned.
_DeferredAggressiveFill = DeferredFill


class PassiveLimitOrderRouter:
    """Simulated order router with passive limit order fill model.

    Handles two order types:
      - ``LIMIT``: deferred fill via queue-position model (entries/exits)
      - ``MARKET``: cross-price aggressive fill with the same ``latency_ns``
        deferral and D14 depth walk as
        :class:`~feelies.execution.backtest_router.BacktestOrderRouter`
        (zero L1 depth rejects; no vacuum fills)

    The orchestrator must call ``on_quote()`` for each incoming quote
    so the router can (a) track the latest NBBO and (b) check resting
    orders for fill conditions.
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
        *,
        cost_model: CostModel | None = None,
        fill_delay_ticks: int = 3,
        max_resting_ticks: int = 50,
        queue_position_shares: int = 0,
        cancel_fee_per_share: Decimal = Decimal("0.0"),
        fill_hazard_max: Decimal | int | str | float = Decimal("0.5"),
        stop_slippage_half_spreads: Decimal | int | str | float = Decimal("2.0"),
        within_l1_impact_factor: Decimal | int | str | float = Decimal("0"),
        permanent_impact_coefficient: Decimal | int | str | float = Decimal("0"),
        stop_depth_depletion_factor: Decimal | int | str | float = Decimal("1"),
        through_fill_size_cap_enabled: bool = False,
        require_trade_for_level_fill: bool = False,
        moc_bounds: MocSessionBounds | None = None,
        moc_penalty_bps: Decimal | int | str | float = Decimal("0"),
        trading_session_bounds: TradingSessionBounds | None = None,
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._market_impact_factor = to_decimal(market_impact_factor, "market_impact_factor")
        self._max_impact_half_spreads = to_decimal(
            max_impact_half_spreads, "max_impact_half_spreads"
        )
        self._fill_delay_ticks = fill_delay_ticks
        self._max_resting_ticks = max_resting_ticks
        self._queue_position_shares = queue_position_shares
        self._cancel_fee_per_share = cancel_fee_per_share
        self._stop_slippage_half_spreads = to_decimal(
            stop_slippage_half_spreads, "stop_slippage_half_spreads"
        )
        self._within_l1_impact_factor = to_decimal(
            within_l1_impact_factor, "within_l1_impact_factor"
        )
        self._permanent_impact_coefficient = to_decimal(
            permanent_impact_coefficient, "permanent_impact_coefficient"
        )
        self._stop_depth_depletion_factor = to_decimal(
            stop_depth_depletion_factor, "stop_depth_depletion_factor"
        )
        # Cap through-fills at displayed opposite-side size.
        self._through_fill_size_cap_enabled = through_fill_size_cap_enabled
        # Optionally require traded volume before a queue-drain fill.
        self._require_trade_for_level_fill = require_trade_for_level_fill
        self._fill_hazard_max = to_decimal(fill_hazard_max, "fill_hazard_max")
        # Base per-tick fill hazard for the quote-imbalance regime,
        # h0 = 1 / fill_delay_ticks (so mean ticks-to-fill ≈
        # fill_delay_ticks at a balanced book).  fill_delay_ticks <= 0
        # collapses to the hazard cap (near-immediate level fills).
        self._base_hazard = (
            Decimal(1) / Decimal(fill_delay_ticks)
            if fill_delay_ticks > 0
            else self._fill_hazard_max
        )

        # Passive fill-quality counters.
        self._fills_by_through = 0
        self._fills_by_drain = 0
        self._cancels_max_resting = 0
        self._cancels_level_left = 0
        self._sum_ticks_to_fill = 0

        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._resting_orders: dict[str, _PendingOrder] = {}
        # Symbol → insertion-ordered order_ids index so on_quote() is O(k)
        # in the number of orders for that symbol rather than O(n) across
        # all orders.  Order of fills/cancels is determinism-critical.
        self._resting_by_symbol: dict[str, dict[str, None]] = {}
        # Full set of order_ids ever submitted — used for idempotent reject.
        self._submitted_order_ids: set[str] = set()
        self._ack_seq = SequenceGenerator()
        self.locked_quote_reject_count: int = 0
        self.no_quote_reject_count: int = 0
        self.duplicate_id_reject_count: int = 0
        self.zero_depth_reject_count: int = 0
        # Deferred MARKET orders: see ``_DeferredAggressiveFill``.
        self._deferred_aggressive: list[_DeferredAggressiveFill] = []
        self._moc: MocFillController | None = None
        if moc_bounds is not None:
            self._moc = MocFillController(
                moc_bounds,
                clock,
                self._cost_model,
                self._ack_seq,
                self._pending_acks,
                max_resting_ticks=max_resting_ticks,
                moc_penalty_bps=to_decimal(moc_penalty_bps, "moc_penalty_bps"),
            )
        self._rth_gate = RthEntryFillGate(trading_session_bounds)

    def bind_position_qty(self, fn: Callable[[str], int]) -> None:
        """Provide signed position quantity for RTH entry classification."""
        self._rth_gate.bind_position_qty(fn)

    # ── Public interface (OrderRouter protocol) ──────────────────

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update latest quote and check resting / pending orders for fills."""
        self._last_quotes[quote.symbol] = quote
        if self._moc is not None:
            self._moc.on_quote(quote)
        self._flush_deferred_aggressive(quote)
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
            # Accumulate level volume for the explicit queue-depth mode
            # (``queue_ahead_shares > 0``) and for the volume gate
            # (``require_trade_for_level_fill``), which needs at least one
            # print at the level before a quote-imbalance drain fill.
            if pending.queue_ahead_shares <= 0 and not self._require_trade_for_level_fill:
                continue
            # Pre-eligibility trades (printed before the order is live at the
            # exchange in exchange time) must not drain the queue or satisfy
            # the volume gate — the order was not on the book when they
            # occurred (mirrors the ``_check_resting_orders`` quote gate).
            if trade.exchange_timestamp_ns < pending.ack_timestamp_ns:
                continue
            if pending.side == Side.BUY and trade.price <= pending.limit_price:
                pending.shares_traded_at_level += trade.size
            elif pending.side == Side.SELL and trade.price >= pending.limit_price:
                pending.shares_traded_at_level += trade.size

    def _rth_reject_entry_if_needed(
        self,
        request: OrderRequest,
        exchange_ts_ns: int,
    ) -> bool:
        suppress, reason = self._rth_gate.should_suppress(
            request,
            exchange_ts_ns,
        )
        if not suppress:
            return False
        self._reject(request, reason)
        return True

    def submit(self, request: OrderRequest) -> None:
        if request.order_id in self._submitted_order_ids:
            self.duplicate_id_reject_count += 1
            self._reject(
                request,
                f"duplicate order_id: {request.order_id}",
                release_submitted_id=False,
            )
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self.no_quote_reject_count += 1
            self._reject(request, "no quote available for symbol")
            return

        # Crossed (bid > ask) quotes are data errors; locked (bid == ask)
        # leaves no passive side and breaks the marketability guard.
        # Applied before the MOC ack path so MOC orders share the same
        # data-quality guard as MARKET/LIMIT orders at submit time.
        if quote.bid >= quote.ask:
            self.locked_quote_reject_count += 1
            self._reject(
                request,
                f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
            )
            return

        if self._rth_reject_entry_if_needed(
            request,
            quote.exchange_timestamp_ns,
        ):
            return

        if self._moc is not None and self._moc.submit(
            request,
            exchange_timestamp_ns=quote.exchange_timestamp_ns,
            reject_fn=self._reject,
        ):
            return

        if request.order_type == OrderType.MARKET:
            self._submit_aggressive_market(request, quote)
        elif request.order_type == OrderType.LIMIT:
            self._post_passive(request, quote)
        else:
            self._reject(request, f"unsupported order type: {request.order_type}")

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    # ── Aggressive (market) fills ────────────────────────────────

    def _submit_aggressive_market(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
    ) -> None:
        """MARKET submit: ACKNOWLEDGED first (Inv 9, parity with
        ``BacktestOrderRouter``); then immediate FILLED when ``latency_ns <= 0``
        (after depth check), else deferred fill on the first exchange-time-
        eligible quote.
        """
        ack_ts = self._clock.now_ns() + self._latency_ns
        self._pending_acks.append(
            OrderAck(
                timestamp_ns=ack_ts,
                correlation_id=request.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.ACKNOWLEDGED,
                request_sequence=request.sequence,
            )
        )

        if self._latency_ns <= 0:
            depth = quote.ask_size if request.side == Side.BUY else quote.bid_size
            if depth <= 0:
                self.zero_depth_reject_count += 1
                self._reject(
                    request,
                    f"zero depth on {request.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                )
                return
            self._execute_market_fill(request, quote, fill_ts=ack_ts)
            return

        # Deferred fills: depth is checked in ``_flush_deferred_aggressive`` on
        # the first latency-eligible quote (not the submission quote).
        self._deferred_aggressive.append(
            _DeferredAggressiveFill(
                request=request,
                fill_deadline_exchange_ns=(
                    max(self._clock.now_ns(), quote.exchange_timestamp_ns) + self._latency_ns
                ),
                ack_timestamp_ns=ack_ts,
            ),
        )

    def _flush_deferred_aggressive(self, quote: NBBOQuote) -> None:
        if not self._deferred_aggressive:
            return
        remaining: list[_DeferredAggressiveFill] = []
        for dm in self._deferred_aggressive:
            req = dm.request
            if req.symbol != quote.symbol:
                remaining.append(dm)
                continue
            ticks_for_symbol = dm.ticks_for_symbol + 1
            if quote.exchange_timestamp_ns < dm.fill_deadline_exchange_ns:
                if ticks_for_symbol >= self._max_resting_ticks:
                    # Preserve monotonic ordering of the order's ack stream:
                    # the timeout fires precisely because exchange time has
                    # not yet reached the latency deadline, so ``clock.now_ns()``
                    # may be < the stored ACKNOWLEDGED timestamp.
                    self._reject(
                        req,
                        f"deferred aggressive timeout after "
                        f"{ticks_for_symbol} ticks (no latency-eligible quote)",
                        timestamp_ns=max(
                            self._clock.now_ns(),
                            dm.ack_timestamp_ns,
                        ),
                    )
                    continue
                remaining.append(
                    replace(dm, ticks_for_symbol=ticks_for_symbol),
                )
                continue
            # Post-ACK reject paths must floor at ``ack_timestamp_ns`` so
            # REJECTED never timestamps before ACKNOWLEDGED (mirrors the
            # ``max_resting_ticks`` timeout path above).
            reject_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            if quote.bid >= quote.ask:
                self._reject(
                    req,
                    f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
                    timestamp_ns=reject_ts,
                )
                continue
            depth = quote.ask_size if req.side == Side.BUY else quote.bid_size
            if depth <= 0:
                self._reject(
                    req,
                    f"zero depth on {req.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                    timestamp_ns=reject_ts,
                )
                continue
            # Marketable LIMIT orders route here via ``_post_passive``; during a
            # positive-latency window the BBO may move so mid exceeds limit_price.
            if req.limit_price is not None:
                fill_mid = (quote.bid + quote.ask) / Decimal("2")
                if (req.side == Side.BUY and fill_mid > req.limit_price) or (
                    req.side == Side.SELL and fill_mid < req.limit_price
                ):
                    self._reject(
                        req,
                        f"deferred fill mid {fill_mid} violates "
                        f"{req.side.name} limit {req.limit_price} "
                        f"(BBO moved adversely during latency window)",
                        timestamp_ns=reject_ts,
                    )
                    continue
            if self._rth_reject_entry_if_needed(
                req,
                quote.exchange_timestamp_ns,
            ):
                continue
            fill_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            self._execute_market_fill(req, quote, fill_ts=fill_ts)
        self._deferred_aggressive = remaining

    def _execute_market_fill(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
        *,
        fill_ts: int | None = None,
    ) -> None:
        """Aggressive fill at ``quote`` — shared D14 model with ``BacktestOrderRouter``."""
        if self._rth_reject_entry_if_needed(
            request,
            quote.exchange_timestamp_ns,
        ):
            return
        if fill_ts is None:
            fill_ts = self._clock.now_ns() + self._latency_ns
        append_market_fill_acks(
            self._pending_acks,
            self._ack_seq,
            self._cost_model,
            request,
            quote,
            fill_ts,
            market_impact_factor=self._market_impact_factor,
            max_impact_half_spreads=self._max_impact_half_spreads,
            stop_slippage_half_spreads=self._stop_slippage_half_spreads,
            within_l1_impact_factor=self._within_l1_impact_factor,
            permanent_impact_coefficient=self._permanent_impact_coefficient,
            stop_depth_depletion_factor=self._stop_depth_depletion_factor,
        )

    # ── Passive (limit) order posting ────────────────────────────

    def _post_passive(self, request: OrderRequest, quote: NBBOQuote) -> None:
        """Record a resting limit order and emit ACKNOWLEDGED ack."""
        limit_price = request.limit_price
        if limit_price is None:
            limit_price = quote.bid if request.side == Side.BUY else quote.ask

        # Evaluate marketability against the submitted
        # limit price (pre-snap) so a sub-penny marketable limit (e.g.
        # BUY 100.072 vs ask 100.071) isn't floored below the cross by
        # ``snap_limit_price`` and then mis-classified as passive.
        if request.side == Side.BUY and limit_price >= quote.ask:
            self._submit_aggressive_market(request, quote)
            return
        if request.side == Side.SELL and limit_price <= quote.bid:
            self._submit_aggressive_market(request, quote)
            return

        limit_price = snap_limit_price(request.side, limit_price)

        ack_ts = max(self._clock.now_ns(), quote.exchange_timestamp_ns) + self._latency_ns
        pending = _PendingOrder(
            request=request,
            side=request.side,
            limit_price=limit_price,
            submit_time_ns=ack_ts,
            ack_timestamp_ns=ack_ts,
            queue_ahead_shares=self._queue_position_shares,
        )
        self._resting_orders[request.order_id] = pending
        self._resting_by_symbol.setdefault(request.symbol, {})[request.order_id] = None

        self._pending_acks.append(
            OrderAck(
                timestamp_ns=ack_ts,
                correlation_id=request.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.ACKNOWLEDGED,
                request_sequence=request.sequence,
            )
        )

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
            if quote.exchange_timestamp_ns < pending.ack_timestamp_ns:
                # Order-entry latency not yet elapsed in exchange time — the
                # order is not yet live at the exchange, so this quote cannot
                # fill it (mirrors the aggressive path's deferred-fill gate).
                continue
            pending.total_ticks += 1
            action = self._evaluate_fill(pending, quote)

            if action in ("through", "drain"):
                suppress, rth_reason = self._rth_gate.should_suppress(
                    pending.request,
                    quote.exchange_timestamp_ns,
                )
                if suppress:
                    self._reject(
                        pending.request,
                        rth_reason,
                        timestamp_ns=max(
                            self._clock.now_ns(),
                            pending.ack_timestamp_ns,
                        ),
                    )
                    to_remove.append(order_id)
                    continue

            if action == "through":
                # Through-fills receive the better of the limit and current BBO.
                fill_price = pending.limit_price
                if pending.side == Side.BUY and quote.ask < pending.limit_price:
                    fill_price = quote.ask
                elif pending.side == Side.SELL and quote.bid > pending.limit_price:
                    fill_price = quote.bid
                adverse_notional_price = quote.ask if pending.side == Side.BUY else quote.bid
                remaining_qty = pending.request.quantity - pending.filled_quantity
                # Cap enabled through-fills at displayed opposite-side size.
                fill_qty = remaining_qty
                if self._through_fill_size_cap_enabled:
                    crossing_size = quote.ask_size if pending.side == Side.BUY else quote.bid_size
                    if crossing_size > 0:
                        fill_qty = min(remaining_qty, crossing_size)
                    # crossing_size <= 0 is a degenerate through with no
                    # displayed size; fall back to the full remainder.
                if fill_qty >= remaining_qty:
                    self._emit_passive_fill(
                        pending,
                        fill_price=fill_price,
                        fill_type="THROUGH",
                        adverse_notional_price=adverse_notional_price,
                        outcome=PassiveFillOutcome.FILLED_BY_THROUGH,
                        fill_quantity=fill_qty,
                    )
                    self._record_fill(pending, PassiveFillOutcome.FILLED_BY_THROUGH)
                    to_remove.append(order_id)
                else:
                    # Partial through-fill: emit PARTIALLY_FILLED for the
                    # available size and keep the remainder resting.
                    self._emit_passive_fill(
                        pending,
                        fill_price=fill_price,
                        fill_type="THROUGH",
                        adverse_notional_price=adverse_notional_price,
                        outcome=PassiveFillOutcome.FILLED_BY_THROUGH,
                        fill_quantity=fill_qty,
                        status=OrderAckStatus.PARTIALLY_FILLED,
                    )
                    pending.filled_quantity += fill_qty
            elif action == "drain":
                adverse_notional_price = quote.ask if pending.side == Side.BUY else quote.bid
                self._emit_passive_fill(
                    pending,
                    fill_price=pending.limit_price,
                    fill_type="LEVEL",
                    adverse_notional_price=adverse_notional_price,
                    outcome=PassiveFillOutcome.FILLED_BY_DRAIN,
                )
                self._record_fill(pending, PassiveFillOutcome.FILLED_BY_DRAIN)
                to_remove.append(order_id)
            elif action == "cancel":
                outcome = (
                    PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS
                    if pending.at_bbo
                    else PassiveFillOutcome.CANCELLED_LEVEL_LEFT_BBO
                )
                self._emit_timeout_cancel(pending, outcome=outcome)
                self._record_cancel(outcome)
                to_remove.append(order_id)

        for oid in to_remove:
            self._remove_resting(oid)

    def _evaluate_fill(self, pending: _PendingOrder, quote: NBBOQuote) -> str:
        """Determine whether a resting order fills, cancels, or continues.

        Returns ``"through"``, ``"drain"``, ``"cancel"``, or ``"wait"``.

        A through-fill occurs when the opposite BBO crosses the resting level.
        A level fill is a
        *seeded Bernoulli trial per quote tick* against a per-tick fill
        hazard ``h`` (see :meth:`_fill_hazard`): the queue ahead drains
        probabilistically rather than after a fixed tick count or share
        threshold.  Determinism (Inv-5) is preserved because the uniform
        is derived from a SHA-256 of the replay-stable quote/order keys
        (no RNG) — see :meth:`_seeded_uniform`.
        """
        at_level = False
        if pending.side == Side.BUY:
            if quote.ask <= pending.limit_price:
                pending.at_bbo = True
                return "through"
            if quote.bid <= pending.limit_price:
                at_level = True
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0
        else:
            if quote.bid >= pending.limit_price:
                pending.at_bbo = True
                return "through"
            if quote.ask >= pending.limit_price:
                at_level = True
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0

        pending.at_bbo = at_level
        if at_level:
            pending.ticks_at_level += 1
            hazard = self._fill_hazard(pending, quote)
            if hazard > 0 and self._seeded_uniform(pending, quote) < hazard:
                return "drain"

        if pending.total_ticks >= self._max_resting_ticks:
            return "cancel"

        return "wait"

    def _fill_hazard(
        self,
        pending: _PendingOrder,
        quote: NBBOQuote,
    ) -> Decimal:
        """Return the per-tick fill hazard for a resting limit.

        With queue depth, hazard is zero until observed trades drain the queue,
        then equals the cap. Without depth, ``h = base × 2 × opposite_share``;
        a balanced book therefore uses the base hazard.
        """
        if pending.queue_ahead_shares > 0:
            if pending.shares_traded_at_level >= pending.queue_ahead_shares:
                return self._fill_hazard_max
            return Decimal(0)

        # When enabled, a level fill requires traded volume at our price.
        if self._require_trade_for_level_fill and pending.shares_traded_at_level <= 0:
            return Decimal(0)

        our_size = quote.bid_size if pending.side == Side.BUY else quote.ask_size
        opp_size = quote.ask_size if pending.side == Side.BUY else quote.bid_size
        total_size = our_size + opp_size
        if total_size > 0:
            imbalance = Decimal(opp_size) / Decimal(total_size)
        else:
            imbalance = Decimal("0.5")
        aggression = Decimal(2) * imbalance
        hazard = self._base_hazard * aggression

        if hazard < 0:
            return Decimal(0)
        if hazard > self._fill_hazard_max:
            return self._fill_hazard_max
        return hazard

    def _seeded_uniform(
        self,
        pending: _PendingOrder,
        quote: NBBOQuote,
    ) -> Decimal:
        """Deterministic per-tick uniform in ``[0, 1)`` for the fill trial.

        Derived from a SHA-256 over replay-stable keys (symbol, quote
        sequence number, exchange timestamp, the order's resting-tick
        count, side, level price, order id) so the draw varies per tick
        and per order yet replays bit-identically (Inv-5) — no live RNG,
        no sampling.
        """
        seed = (
            f"{quote.symbol}|{quote.sequence_number}|"
            f"{quote.exchange_timestamp_ns}|{pending.ticks_at_level}|"
            f"{pending.side.name}|{pending.limit_price}|"
            f"{pending.request.order_id}"
        )
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        return Decimal(value) / Decimal(1 << 64)

    def _record_fill(
        self,
        pending: _PendingOrder,
        outcome: PassiveFillOutcome,
    ) -> None:
        if outcome is PassiveFillOutcome.FILLED_BY_THROUGH:
            self._fills_by_through += 1
        else:
            self._fills_by_drain += 1
        self._sum_ticks_to_fill += pending.total_ticks

    def _record_cancel(self, outcome: PassiveFillOutcome) -> None:
        if outcome is PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS:
            self._cancels_max_resting += 1
        else:
            self._cancels_level_left += 1

    def passive_fill_stats(self) -> dict[str, float | int]:
        """Return backtest fill-quality statistics.

        Returns counts per :class:`PassiveFillOutcome`, the
        ``passive_fill_rate`` (fills / terminal resting orders), and
        ``mean_resting_ticks_to_fill`` (0.0 when nothing has filled).
        """
        filled = self._fills_by_through + self._fills_by_drain
        cancelled = self._cancels_max_resting + self._cancels_level_left
        terminal = filled + cancelled
        return {
            "filled": filled,
            "fills_by_through": self._fills_by_through,
            "fills_by_drain": self._fills_by_drain,
            "cancelled": cancelled,
            "cancels_max_resting_ticks": self._cancels_max_resting,
            "cancels_level_left_bbo": self._cancels_level_left,
            "passive_fill_rate": (filled / terminal) if terminal > 0 else 0.0,
            "mean_resting_ticks_to_fill": (
                self._sum_ticks_to_fill / filled if filled > 0 else 0.0
            ),
        }

    # ── Ack emission helpers ─────────────────────────────────────
    def _reject(
        self,
        request: OrderRequest,
        reason: str,
        *,
        timestamp_ns: int | None = None,
        release_submitted_id: bool = True,
    ) -> None:
        """Emit a REJECTED ack for the given order request.

        Clears ``order_id`` from :attr:`_submitted_order_ids` unless
        ``release_submitted_id=False`` (duplicate submissions — the id may
        still belong to an in-flight resting or deferred aggressive order).
        """
        append_reject_ack(
            self._pending_acks,
            self._ack_seq,
            self._submitted_order_ids,
            self._clock.now_ns(),
            request,
            reason,
            timestamp_ns=timestamp_ns,
            release_submitted_id=release_submitted_id,
        )

    def _emit_passive_fill(
        self,
        pending: _PendingOrder,
        fill_price: Decimal | None = None,
        fill_type: FillType = "LEVEL",
        adverse_notional_price: Decimal | None = None,
        outcome: PassiveFillOutcome = PassiveFillOutcome.FILLED_BY_DRAIN,
        fill_quantity: int | None = None,
        status: OrderAckStatus = OrderAckStatus.FILLED,
    ) -> None:
        """Emit a FILLED ack for a passive limit order.

        Calls the cost model with ``is_taker=False`` so the maker rebate
        and adverse-selection penalty are applied by the model — no
        separate rebate subtraction needed here.

        ``fill_price`` defaults to the resting ``limit_price`` (queue-
        drain / level fills).  Callers may pass a better price (BUY:
        a lower ask that gapped through, SELL: a higher bid) to model
        IBKR's price-improvement rule on through-fills.

        ``fill_type`` (``"LEVEL"`` default, ``"THROUGH"`` on price
        improvement) controls the adverse-selection bps.

        ``adverse_notional_price`` is forwarded as the
        adverse-selection notional basis when provided.

        ``outcome`` is stamped onto the FILLED ack ``reason`` for
        fill-quality forensics.
        """
        if fill_price is None:
            fill_price = pending.limit_price
        # ``fill_quantity`` defaults to the *remaining* unfilled size so a
        # capped through-fill bills only the size that traded through.
        if fill_quantity is None:
            fill_quantity = pending.request.quantity - pending.filled_quantity
        # Maker rounding: a passive fill must be at the resting limit
        # OR BETTER (BUY pays no more, SELL receives no less).  Taker
        # rounding (``snap_fill_price``) would round *against* the
        # resting order on through-fills and erase the documented
        # price improvement, so snap on the limit-price grid instead.
        fill_price = snap_limit_price(pending.side, fill_price)
        # The resting order is already live at the exchange (gated by
        # Entry latency is already in ack_timestamp_ns; do not charge it twice.
        fill_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)

        costs = self._cost_model.compute(
            symbol=pending.request.symbol,
            side=pending.side,
            quantity=fill_quantity,
            fill_price=fill_price,
            half_spread=Decimal("0"),
            is_taker=False,
            is_short=pending.request.is_short,
            fill_type=fill_type,
            adverse_notional_price=adverse_notional_price,
            is_through_fill=(fill_type == "THROUGH"),
        )

        self._pending_acks.append(
            OrderAck(
                timestamp_ns=fill_ts,
                correlation_id=pending.request.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=pending.request.order_id,
                symbol=pending.request.symbol,
                status=status,
                filled_quantity=fill_quantity,
                fill_price=fill_price,
                fees=costs.total_fees,
                cost_bps=costs.cost_bps,
                reason=outcome.value,
                request_sequence=pending.request.sequence,
            )
        )

    def _cancel_fees(self, quantity: int) -> Decimal:
        """Deterministically quantized cancel-fee computation.

        Use Decimal's default half-even rounding so cancel-fee quantization matches the
        cost model's quantize() rule.
        """
        return (self._cancel_fee_per_share * quantity).quantize(Decimal("0.01"))

    def _append_cancel_ack(
        self,
        pending: _PendingOrder,
        *,
        reason: str,
        status: OrderAckStatus = OrderAckStatus.CANCELLED,
    ) -> None:
        """Append a terminal cancel-style ack for ``pending`` with ``reason``.

        Shared by the timeout-cancel and explicit-cancel paths. Floors the
        timestamp at ``pending.ack_timestamp_ns`` so the terminal ack never
        precedes ACKNOWLEDGED.
        """
        cancel_fees = self._cancel_fees(pending.request.quantity)
        cancel_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)
        self._pending_acks.append(
            OrderAck(
                timestamp_ns=cancel_ts,
                correlation_id=pending.request.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=pending.request.order_id,
                symbol=pending.request.symbol,
                status=status,
                reason=reason,
                fees=cancel_fees if cancel_fees > 0 else Decimal("0"),
                request_sequence=pending.request.sequence,
            )
        )

    def _emit_timeout_cancel(
        self,
        pending: _PendingOrder,
        outcome: PassiveFillOutcome = (PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS),
    ) -> None:
        """Emit an EXPIRED ack for a timed-out resting order."""
        self._append_cancel_ack(
            pending,
            reason=(f"{outcome.value}: passive limit timeout after {pending.total_ticks} ticks"),
            status=OrderAckStatus.EXPIRED,
        )

    # ── Explicit cancellation ───────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific resting order.

        Returns True if the order was found and cancelled.  The
        cancellation ack is queued for the next ``poll_acks()`` call.
        """
        pending = self._resting_orders.get(order_id)
        if pending is None:
            # Acknowledged-but-unfilled MOC orders live in the
            # MocFillController queue, not ``_resting_orders``.  Halt
            # cleanup walks active orders and calls ``cancel_order``
            # on each, so MOC entries must be reachable here too.
            if self._moc is not None and self._moc.cancel_pending(
                order_id,
                "client_cancel",
            ):
                return True
            return False
        self._append_cancel_ack(pending, reason="client_cancel")
        self._remove_resting(order_id)
        return True

    def _remove_resting(self, order_id: str) -> None:
        pending = self._resting_orders.pop(order_id, None)
        if pending is None:
            return
        symbol_orders = self._resting_by_symbol.get(pending.request.symbol)
        if symbol_orders is not None:
            symbol_orders.pop(order_id, None)
            if not symbol_orders:
                del self._resting_by_symbol[pending.request.symbol]

    # ── Diagnostics ──────────────────────────────────────────────

    def expire_pending_moc(
        self,
        reason: str = "MOC_NO_CLOSE_PRINT",
    ) -> int:
        """Reject any acknowledged MOC orders that never received a
        closing-auction print.  Called by the kernel at session /
        replay end so an MOC cannot remain non-terminal indefinitely
        when no qualifying post-close NBBO arrives in the feed.
        Returns the number of orders expired.
        """
        if self._moc is None:
            return 0
        return self._moc.expire_unfilled(reason, reject_fn=self._reject)

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
        threshold. Without a trade feed, those orders never fill by queue drain;
        callers should wire
        ``on_trade`` when this is True.

        Also true when ``require_trade_for_level_fill`` is enabled: drain fills
        require at least one print at the level, so the trade feed must be
        wired or passive orders only ever fill on through-trades.
        """
        return self._queue_position_shares > 0 or self._require_trade_for_level_fill
