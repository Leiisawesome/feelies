"""Backtest order router — simulated fills for backtest mode.

Implements the ``OrderRouter`` protocol with a deterministic
mid-price + walk-the-book partial-fill model.  Despite the historical
"v1 placeholder" framing, the implementation is the production
backtest path: ACKNOWLEDGED + (optional) PARTIALLY_FILLED + FILLED
with cost-model attribution and L1-depth-walk impact.  The
backtest-engine skill's full queue-priority + adverse-selection
fill model is implemented separately by
:class:`feelies.execution.passive_limit_router.PassiveLimitOrderRouter`
and is selected via ``execution_mode in {"passive_limit",
"minimum_cost"}`` at bootstrap time.

Cost-accounting convention (audit R6)
-------------------------------------

Market orders fill at the **mid** ``(bid + ask) / 2`` and the
half-spread cross is debited as a separate ``spread_cost`` component
inside the :class:`CostBreakdown` returned by the cost model.  The
position's :attr:`Position.avg_entry_price` therefore records the
mid (NOT the executed cross price) and the half-spread flows through
:attr:`Position.cumulative_fees` instead.  This is internally
consistent — NAV (`BasicRiskEngine._compute_current_equity`) and
forensics both subtract fees explicitly — but consumers that read
``realized_pnl`` directly without subtracting fees will overstate
edge.  See :class:`feelies.portfolio.position_store.Position` for
the canonical statement of this convention; live deployments must
mirror it (or update both ends together) to preserve Inv-9 parity.

The ``walk-the-book`` excess-quantity branch is the one exception:
the impact premium IS encoded into ``avg_entry_price`` (because the
adverse impact is genuinely realized at fill time, not a synthetic
spread cost).  See the inline comment in :meth:`submit`.

Fill semantics:
  - Orders are acknowledged immediately on submit (ACKNOWLEDGED ack
    emitted first, for parity with the live-mode state machine).
  - Orders are then filled at mid-price of the most recent quote
    for that symbol; the half-spread cost is attributed via the
    cost model (see convention above).
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
    rather than silently producing a second fill; deferred MARKET
    fills (``latency_ns > 0``) are rejected after ``max_resting_ticks``
    quotes for that symbol while still waiting for exchange-time
    eligibility — mirroring :class:`~feelies.execution.passive_limit_router.PassiveLimitOrderRouter`
    aggressive deferrals so thin data cannot leave an ACK-only order
    stranded indefinitely.
"""

from __future__ import annotations

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


# MARKET orders deferred until exchange time reaches the latency deadline use
# the shared :class:`~feelies.execution.market_fill.DeferredFill` record so the
# backtest and passive routers cannot drift on the latency / monotonic-ack
# contract (Inv 9).  Aliased to the historical name for readability at the
# call sites below.
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
    cannot move the fill price more than 10 half-spreads beyond mid,
    even against a 1-lot book.  Protects against unbounded slippage
    on thin quotes.
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

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote for a symbol.

        Called by the bootstrap wiring (bus subscription) or
        explicitly by the caller before each tick.
        """
        self._last_quotes[quote.symbol] = quote
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
