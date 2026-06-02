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
from feelies.execution._fill_helpers import emit_aggressive_fill
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
        stop_slippage_half_spreads: Decimal | int | str | float = Decimal("2.0"),
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
        self._stop_slippage_half_spreads = _to_decimal(
            stop_slippage_half_spreads, "stop_slippage_half_spreads"
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
        # Audit F-M-26: per-cause reject counters so operators can
        # monitor the rate of skipped orders (locked/crossed quotes,
        # missing quotes, duplicate IDs, zero depth) without parsing
        # the ack stream.
        self.locked_quote_reject_count: int = 0
        self.no_quote_reject_count: int = 0
        self.duplicate_id_reject_count: int = 0
        self.zero_depth_reject_count: int = 0

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
            self.duplicate_id_reject_count += 1
            self._reject(request, f"duplicate order_id: {request.order_id}")
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self.no_quote_reject_count += 1
            self._reject(request, "no quote available for symbol")
            return

        # Crossed/locked quotes produce nonsensical fills — reject.
        if quote.bid >= quote.ask:
            self.locked_quote_reject_count += 1
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
        """Execute the fill for *request* against *quote* via the shared helper."""
        emit_aggressive_fill(
            request=request,
            quote=quote,
            fill_ts=fill_ts,
            cost_model=self._cost_model,
            market_impact_factor=self._market_impact_factor,
            max_impact_half_spreads=self._max_impact_half_spreads,
            pending_acks=self._pending_acks,
            ack_seq=self._ack_seq,
            reject=self._reject,
            stop_slippage_half_spreads=self._stop_slippage_half_spreads,
        )

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
