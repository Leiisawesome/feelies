"""Backtest order router — simulated fills for backtest mode.

Implements the ``OrderRouter`` protocol with a latency-deferred
mid-price fill model.

Latency model (audit F-H-07):
  - ``latency_ns`` defines the gap between submit time and fill
    eligibility.  ACKNOWLEDGED acks are emitted immediately at
    ``submit_time + latency_ns``.
  - The FILL itself is deferred until a quote arrives whose
    ``timestamp_ns >= eligible_at_ns``.  The fill executes against
    THAT later quote — not the submit-time quote.  This models the
    realistic case where additional ticks arrive during the latency
    window and the order fills against a (possibly worse) post-
    latency quote.
  - When ``latency_ns == 0``, the order matures immediately and
    fills synchronously against the submit-time quote (legacy
    behaviour preserved for tests / zero-latency configurations).

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
from dataclasses import dataclass
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
from feelies.execution.cost_model import CostModel


@dataclass
class _PendingSubmit:
    """A submitted order awaiting fill-time eligibility (audit F-H-07)."""

    request: OrderRequest
    eligible_at_ns: int


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
        *,
        cost_model: CostModel,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model
        self._market_impact_factor = _to_decimal(
            market_impact_factor, "market_impact_factor"
        )
        self._max_impact_half_spreads = _to_decimal(
            max_impact_half_spreads, "max_impact_half_spreads"
        )
        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._submitted_order_ids: set[str] = set()
        self._ack_seq = SequenceGenerator()
        # Audit F-H-07: FIFO queue of orders awaiting fill-time
        # eligibility.  Drained on every ``on_quote`` and on ``submit``
        # itself when ``latency_ns == 0`` (so the zero-latency fast
        # path keeps its same-tick semantics).
        self._pending_submits: list[_PendingSubmit] = []

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update the latest quote and drain any mature pending orders.

        Audit F-H-07: orders submitted with ``latency_ns > 0`` are
        queued in ``_pending_submits`` and only fill against a quote
        whose ``timestamp_ns >= eligible_at_ns``.  This is the
        realistic behavior — a market order submitted at T sees
        additional ticks during the latency window and fills against
        a (possibly worse) post-latency quote.
        """
        self._last_quotes[quote.symbol] = quote
        self._drain_pending_submits(quote)

    def _drain_pending_submits(self, quote: NBBOQuote) -> None:
        """Fill pending orders whose eligibility time has elapsed.

        Orders for *quote.symbol* whose ``eligible_at_ns <=
        quote.timestamp_ns`` fill against ``quote``.  FIFO order is
        preserved (determinism, Inv-5).  Other symbols are unaffected.
        """
        if not self._pending_submits:
            return
        still_pending: list[_PendingSubmit] = []
        for entry in self._pending_submits:
            if (
                entry.request.symbol == quote.symbol
                and entry.eligible_at_ns <= quote.timestamp_ns
            ):
                self._fill_against_quote(entry.request, quote, entry.eligible_at_ns)
            else:
                still_pending.append(entry)
        self._pending_submits = still_pending

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
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))

        # Audit F-H-07: when latency_ns > 0, defer the fill until a
        # quote arrives at or after eligibility.  When latency_ns == 0,
        # the order is immediately eligible against the submit-time
        # quote (legacy synchronous fast path).
        eligible_at_ns = ack_ts
        if eligible_at_ns > self._clock.now_ns():
            self._pending_submits.append(_PendingSubmit(
                request=request,
                eligible_at_ns=eligible_at_ns,
            ))
            return

        self._fill_against_quote(request, quote, eligible_at_ns)

    def _fill_against_quote(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
        fill_ts: int,
    ) -> None:
        """Execute the fill for *request* against *quote*.

        Extracted from ``submit`` so the fill logic can run from both
        the synchronous (latency=0) and deferred (latency>0) paths.
        Emits PARTIAL+FILLED on walk-the-book, FILLED otherwise.
        """
        # Re-check quote sanity at fill time — the quote may have
        # changed since submit if we waited for eligibility.
        if quote.bid >= quote.ask:
            self._reject(
                request,
                f"crossed or locked quote at fill time bid={quote.bid} ask={quote.ask}",
            )
            return

        fill_price = (quote.bid + quote.ask) / Decimal("2")
        half_spread = (quote.ask - quote.bid) / Decimal("2")

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
                sequence=self._ack_seq.next(),
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.PARTIALLY_FILLED,
                filled_quantity=partial_qty,
                fill_price=fill_price,
                fees=partial_costs.total_fees,
                cost_bps=partial_costs.cost_bps,
                request_sequence=request.sequence,
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

            # The walk-the-book impact premium is already encoded in
            # ``impact_price`` (the position records its cost basis at
            # the worse-than-mid price) — so the cost model must NOT
            # add the impact a second time as a spread component.
            # Pass plain ``half_spread`` here; ``cost_bps`` will then
            # reflect the half-spread cross + commission + adverse
            # selection, while the impact is captured economically via
            # the position's avg-entry price.  The earlier code passed
            # ``half_spread + impact`` and so charged the impact twice
            # (once via fill_price, once via the spread component),
            # producing a spuriously punitive cost on thin-book partial
            # fills.
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
                sequence=self._ack_seq.next(),
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
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=request.quantity,
            fill_price=fill_price,
            fees=costs.total_fees,
            cost_bps=costs.cost_bps,
            request_sequence=request.sequence,
        ))

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    def _reject(self, request: OrderRequest, reason: str) -> None:
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
            request_sequence=request.sequence,
        ))
