"""Deterministic simulated fills for backtests.

Orders are acknowledged before filling. Market orders cross the latest valid
touch; the half-spread is embedded in the execution price rather than charged
again as a fee. Quantity beyond L1 depth receives a capped, directional impact
premium and may emit partial then final fill acknowledgements.

Missing, locked, crossed, or zero-depth quotes reject safely. Duplicate IDs and
deferred orders that exceed their resting-tick limit also reject. Passive queue
and adverse-selection behavior lives in ``PassiveLimitOrderRouter``.
"""

from __future__ import annotations

from collections.abc import Callable

from dataclasses import replace
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    Side,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel, ZeroCostModel
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


# Share DeferredFill so both routers preserve latency and monotonic ack ordering.
_DeferredMarketFill = DeferredFill


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
    cannot move the fill price more than 10 half-spreads beyond the
    cross, even against a 1-lot book.  Protects against unbounded
    slippage on thin quotes.
    ``max_resting_ticks``: when ``latency_ns > 0``, deferred MARKET fills
    are rejected after this many quotes for the symbol while exchange
    time is still before the latency eligibility deadline (Inv 11).
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        *,
        cost_model: CostModel | None = None,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
        stop_slippage_half_spreads: Decimal | int | str | float = Decimal("2.0"),
        within_l1_impact_factor: Decimal | int | str | float = Decimal("0"),
        permanent_impact_coefficient: Decimal | int | str | float = Decimal("0"),
        stop_depth_depletion_factor: Decimal | int | str | float = Decimal("1"),
        max_resting_ticks: int = 50,
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
        self._max_resting_ticks = max_resting_ticks
        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._submitted_order_ids: set[str] = set()
        self._ack_seq = SequenceGenerator()
        self.locked_quote_reject_count: int = 0
        self.no_quote_reject_count: int = 0
        self.duplicate_id_reject_count: int = 0
        self.zero_depth_reject_count: int = 0
        self._deferred_markets: list[_DeferredMarketFill] = []
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

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote and drain any mature pending orders.

        Orders submitted with ``latency_ns > 0`` are
        queued in ``_pending_submits`` and only fill against a quote
        whose ``timestamp_ns >= eligible_at_ns``.  This is the
        realistic behavior — a market order submitted at T sees
        additional ticks during the latency window and fills against
        a (possibly worse) post-latency quote.
        """
        self._last_quotes[quote.symbol] = quote
        if self._moc is not None:
            self._moc.on_quote(quote)
        self._flush_deferred_market_fills(quote)

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

        # Crossed/locked quotes produce nonsensical fills — reject.
        # Applied before the MOC ack path so MOC orders share the same
        # data-quality guard as MARKET orders at submit time.
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

        # Emit ACKNOWLEDGED before terminal fill states.
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
            available_depth = quote.ask_size if request.side == Side.BUY else quote.bid_size
            if available_depth <= 0:
                self.zero_depth_reject_count += 1
                self._reject(
                    request,
                    f"zero depth on {request.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                )
                return
            fill_ts = ack_ts
            self._execute_market_fill(request, quote, fill_ts)
        else:
            # Deferred fills: depth is validated in ``_flush_deferred_market_fills``
            # against the first latency-eligible quote (not the submission quote).
            self._deferred_markets.append(
                _DeferredMarketFill(
                    request=request,
                    fill_deadline_exchange_ns=(
                        max(self._clock.now_ns(), quote.exchange_timestamp_ns) + self._latency_ns
                    ),
                    ack_timestamp_ns=ack_ts,
                    ticks_for_symbol=0,
                ),
            )

    def _flush_deferred_market_fills(self, quote: NBBOQuote) -> None:
        """Fill queued MARKET orders once ``latency_ns`` of exchange time has
        elapsed — prices come from the first qualifying quote, not the signal
        quote (causal fill model).
        """
        if not self._deferred_markets:
            return
        remaining: list[_DeferredMarketFill] = []
        for dm in self._deferred_markets:
            if dm.request.symbol != quote.symbol:
                remaining.append(dm)
                continue
            ticks_for_symbol = dm.ticks_for_symbol + 1
            if quote.exchange_timestamp_ns < dm.fill_deadline_exchange_ns:
                if ticks_for_symbol >= self._max_resting_ticks:
                    self._reject(
                        dm.request,
                        f"deferred market timeout after "
                        f"{ticks_for_symbol} ticks (no latency-eligible quote)",
                        timestamp_ns=max(self._clock.now_ns(), dm.ack_timestamp_ns),
                    )
                    continue
                remaining.append(replace(dm, ticks_for_symbol=ticks_for_symbol))
                continue
            reject_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            if quote.bid >= quote.ask:
                self._reject(
                    dm.request,
                    f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
                    timestamp_ns=reject_ts,
                )
                continue
            depth = quote.ask_size if dm.request.side == Side.BUY else quote.bid_size
            if depth <= 0:
                self.zero_depth_reject_count += 1
                self._reject(
                    dm.request,
                    f"zero depth on {dm.request.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                    timestamp_ns=reject_ts,
                )
                continue
            if self._rth_reject_entry_if_needed(
                dm.request,
                quote.exchange_timestamp_ns,
            ):
                continue
            fill_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            self._execute_market_fill(dm.request, quote, fill_ts)
        self._deferred_markets = remaining

    def _execute_market_fill(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
        fill_ts: int,
    ) -> None:
        """Append FILLED / PARTIALLY_FILLED acks for a MARKET order."""
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

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an acknowledged-but-unfilled MOC order by id.

        The market backtest router has no resting limit book of its
        own — MARKET orders fill or reject inline at submit and
        deferred-MARKET fills are flushed by ``on_quote``.  But MOC
        orders sit in :class:`MocFillController` until the closing
        print.  The kernel's halt / reverse cleanup walks active
        orders and calls ``cancel_order`` on each (parity with the
        passive router), so MOC entries must be reachable here too;
        otherwise an acknowledged MOC could still fill at the close
        after the kernel believed resting interest was cleared.
        """
        if self._moc is None:
            return False
        return self._moc.cancel_pending(order_id, "client_cancel")

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

    def _reject(
        self,
        request: OrderRequest,
        reason: str,
        *,
        timestamp_ns: int | None = None,
        release_submitted_id: bool = True,
    ) -> None:
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
