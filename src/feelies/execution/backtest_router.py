"""Backtest order router — simulated fills for backtest mode.

Implements the ``OrderRouter`` protocol with a deterministic
cross-price + walk-the-book partial-fill model.  Despite the historical
"v1 placeholder" framing, the implementation is the production
backtest path: ACKNOWLEDGED + (optional) PARTIALLY_FILLED + FILLED
with cost-model attribution and L1-depth-walk impact.  The
backtest-engine skill's full queue-priority + adverse-selection
fill model is implemented separately by
:class:`feelies.execution.passive_limit_router.PassiveLimitOrderRouter`
and is selected via ``execution_mode in {"passive_limit",
"minimum_cost"}`` at bootstrap time.

Cost-accounting convention (audit R6, revised BT-3)
---------------------------------------------------

Market orders fill at the **executed cross price** — the touch the
taker crosses to (BUY lifts ``quote.ask``, SELL hits ``quote.bid``) —
so :attr:`Position.avg_entry_price` records the price IB would report.
The half-spread is embedded in that price, NOT debited as a separate
``spread_cost`` fee (the cost model is called with ``half_spread=0``);
see :mod:`feelies.execution.market_fill` for the single chokepoint.

Because marks use the mid, a taker entry shows an immediate
half-spread unrealized markdown rather than a fee.  NAV is unchanged —
``BasicRiskEngine._compute_current_equity`` sums
``account_equity + realized − fees + unrealized`` — only the
attribution moved (out of :attr:`Position.cumulative_fees`, into the
entry price / unrealized line).  Consumers that read
:attr:`Position.cumulative_fees` as "total transaction cost" no longer
see the spread there; the spread now lives in realized/unrealized PnL.
See :class:`feelies.portfolio.position_store.Position` for the
canonical statement; live deployments already cross at the touch.

The ``walk-the-book`` excess-quantity branch stacks its impact premium
on top of the cross (above the ask for buys, below the bid for sells)
and that premium is likewise encoded into ``avg_entry_price``.  See the
inline comment in :meth:`submit`.

Fill semantics:
  - Orders are acknowledged immediately on submit (ACKNOWLEDGED ack
    emitted first, for parity with the live-mode state machine).
  - Orders are then filled at the executed cross price of the most
    recent quote for that symbol (BUY lifts the ask, SELL hits the
    bid); the half-spread is embedded in the price (see convention
    above), not attributed as a separate fee.
  - If no quote has been seen for the symbol, the order is rejected.
  - If the quote is crossed or locked (bid >= ask), the order is
    rejected rather than silently filling at a dubious cross.
  - If the relevant L1 depth is zero, the order is rejected rather
    than silently filling against a vacuum.
  - When the requested quantity exceeds the L1 available depth
    (``bid_size`` for sells, ``ask_size`` for buys), the fill is
    split into two acks (D14 partial fill model):
      1. ``PARTIALLY_FILLED`` for the available depth at the cross.
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
    rather than silently producing a second fill; deferred MARKET
    fills (``latency_ns > 0``) are rejected after ``max_resting_ticks``
    quotes for that symbol while still waiting for exchange-time
    eligibility — mirroring :class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter`
    aggressive deferrals so thin data cannot leave an ACK-only order
    stranded indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
from feelies.execution.market_fill import append_market_fill_acks, to_decimal
from feelies.execution.moc_fill import MocFillController
from feelies.execution.moc_session import MocSessionBounds


@dataclass(frozen=True)
class _DeferredMarketFill:
    """MARKET order waiting until exchange time reaches fill deadline.

    ``ticks_for_symbol`` is incremented every time a matching-symbol quote
    arrives so the deferred order can be cancelled after
    ``max_resting_ticks`` quotes — mirroring the safety net the passive
    router applies to deferred aggressive fills.  Without this cap, a halt
    or thinly-traded symbol could leave a MARKET order pending indefinitely
    (Inv 11: fail-safe default).

    ``ack_timestamp_ns`` is the ACKNOWLEDGED ack timestamp emitted at
    submit (``clock.now_ns() + latency_ns`` at submit time).  It is stored
    so the deferred FILLED timestamp can be ``max(ack, fill_quote_ts)``
    instead of ``fill_quote_ts + latency_ns``: the eligibility gate already
    waited ``latency_ns`` on the exchange clock — adding latency again when
    ``ReplayFeed`` keeps ``clock.now_ns()`` aligned with
    ``exchange_timestamp_ns`` would double-count one-way delay (Inv 9).
    The same floor applies to ``max_resting_ticks`` timeout rejects so
    REJECTED never timestamps before ACKNOWLEDGED while exchange time is
    still short of the latency deadline.
    """

    request: OrderRequest
    fill_deadline_exchange_ns: int
    ack_timestamp_ns: int
    ticks_for_symbol: int = 0


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
        cost_model: CostModel | None = None,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
        *,
        max_resting_ticks: int = 50,
        moc_bounds: MocSessionBounds | None = None,
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._market_impact_factor = to_decimal(
            market_impact_factor, "market_impact_factor"
        )
        self._max_impact_half_spreads = to_decimal(
            max_impact_half_spreads, "max_impact_half_spreads"
        )
        self._max_resting_ticks = max_resting_ticks
        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._submitted_order_ids: set[str] = set()
        self._ack_seq = SequenceGenerator()
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
            )

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote for a symbol.

        Called by the bootstrap wiring (bus subscription) or
        explicitly by the caller before each tick.
        """
        self._last_quotes[quote.symbol] = quote
        if self._moc is not None:
            self._moc.on_quote(quote)
        self._flush_deferred_market_fills(quote)

    def submit(self, request: OrderRequest) -> None:
        if request.order_id in self._submitted_order_ids:
            self._reject(
                request,
                f"duplicate order_id: {request.order_id}",
                release_submitted_id=False,
            )
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._reject(request, "no quote available for symbol")
            return

        # Crossed/locked quotes produce nonsensical fills — reject.
        # Applied before the MOC ack path so MOC orders share the same
        # data-quality guard as MARKET orders at submit time.
        if quote.bid >= quote.ask:
            self._reject(
                request,
                f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
            )
            return

        if self._moc is not None and self._moc.submit(
            request,
            exchange_timestamp_ns=quote.exchange_timestamp_ns,
            reject_fn=self._reject,
        ):
            return

        # Emit ACKNOWLEDGED first for live-mode SM parity (Inv 9).
        ack_ts = self._clock.now_ns() + self._latency_ns
        self._pending_acks.append(OrderAck(
            timestamp_ns=ack_ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))

        if self._latency_ns <= 0:
            available_depth = (
                quote.ask_size if request.side == Side.BUY else quote.bid_size
            )
            if available_depth <= 0:
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
                        quote.exchange_timestamp_ns + self._latency_ns
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
        # FILLED must be >= the stored ACKNOWLEDGED timestamp.  When the
        # injected clock tracks exchange time (``ReplayFeed``), using
        # ``clock.now_ns() + latency_ns`` here would add a second copy of
        # one-way latency on top of the exchange-time eligibility gate below.
        for dm in self._deferred_markets:
            if dm.request.symbol != quote.symbol:
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
                        dm.request,
                        f"deferred market timeout after "
                        f"{ticks_for_symbol} ticks (no latency-eligible quote)",
                        timestamp_ns=max(
                            self._clock.now_ns(),
                            dm.ack_timestamp_ns,
                        ),
                    )
                    continue
                remaining.append(replace(dm, ticks_for_symbol=ticks_for_symbol))
                continue
            # Post-ACK reject paths must floor at ``ack_timestamp_ns`` so
            # REJECTED never timestamps before ACKNOWLEDGED (mirrors the
            # ``max_resting_ticks`` timeout path above).
            reject_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            if quote.bid >= quote.ask:
                self._reject(
                    dm.request,
                    f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
                    timestamp_ns=reject_ts,
                )
                continue
            depth = (
                quote.ask_size if dm.request.side == Side.BUY else quote.bid_size
            )
            if depth <= 0:
                self._reject(
                    dm.request,
                    f"zero depth on {dm.request.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                    timestamp_ns=reject_ts,
                )
                continue
            fill_ts = max(dm.ack_timestamp_ns, quote.exchange_timestamp_ns)
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
        ts = self._clock.now_ns() if timestamp_ns is None else timestamp_ns
        self._pending_acks.append(OrderAck(
            timestamp_ns=ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
            request_sequence=request.sequence,
        ))
        if release_submitted_id:
            self._submitted_order_ids.discard(request.order_id)
