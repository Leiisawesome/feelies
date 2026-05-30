"""Closing-auction (MOC) fill simulation for backtest mode (BT-8).

MOC orders are acknowledged at submit, held until the first quote at
or after the configured official close, then filled in a single print
at the closing mid (proxy for the exchange closing-auction price).
Submissions at or after the IB MOC cutoff are rejected
(``MOC_CUTOFF_MISSED``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel
from feelies.execution.moc_session import MocSessionBounds


@dataclass
class _PendingMoc:
    request: OrderRequest
    ack_timestamp_ns: int
    ticks_for_symbol: int = 0


class MocFillController:
    """Stateful pending-MOC queue wired into backtest order routers."""

    def __init__(
        self,
        bounds: MocSessionBounds,
        clock: Clock,
        cost_model: CostModel,
        ack_seq: SequenceGenerator,
        pending_acks: list[OrderAck],
        *,
        max_resting_ticks: int = 50,
    ) -> None:
        self._bounds = bounds
        self._clock = clock
        self._cost_model = cost_model
        self._ack_seq = ack_seq
        self._pending_acks = pending_acks
        self._max_resting_ticks = max_resting_ticks
        self._pending: list[_PendingMoc] = []

    @property
    def bounds(self) -> MocSessionBounds:
        return self._bounds

    def submit(
        self,
        request: OrderRequest,
        *,
        exchange_timestamp_ns: int,
        reject_fn: object,
    ) -> bool:
        """Handle an MOC submit.  Returns True when consumed by this controller.

        ``reject_fn`` must be callable as
        ``reject_fn(request, reason, *, timestamp_ns=None, release_submitted_id=True)``.
        """
        if not request.is_moc:
            return False

        if not self._bounds.covers_ns(exchange_timestamp_ns):
            reject_fn(  # type: ignore[operator]
                request,
                "MOC_SESSION_DATE_MISMATCH",
                timestamp_ns=max(
                    self._clock.now_ns(),
                    exchange_timestamp_ns,
                ),
            )
            return True

        if exchange_timestamp_ns >= self._bounds.moc_cutoff_ns:
            reject_fn(  # type: ignore[operator]
                request,
                "MOC_CUTOFF_MISSED",
                timestamp_ns=max(
                    self._clock.now_ns(),
                    exchange_timestamp_ns,
                ),
            )
            return True

        ack_ts = self._clock.now_ns()
        self._pending_acks.append(OrderAck(
            timestamp_ns=ack_ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))
        self._pending.append(_PendingMoc(
            request=request,
            ack_timestamp_ns=ack_ts,
        ))
        return True

    def on_quote(
        self,
        quote: NBBOQuote,
        *,
        reject_fn: object,
    ) -> None:
        """Try to fill or expire pending MOC orders on each quote."""
        if not self._pending:
            return
        if not self._bounds.covers_ns(quote.exchange_timestamp_ns):
            # Quote is from a different calendar day than the configured
            # session bounds — the cutoff/close anchors don't apply, so
            # neither tick the resting counters nor trigger fills.
            return
        remaining: list[_PendingMoc] = []
        for pm in self._pending:
            if pm.request.symbol != quote.symbol:
                remaining.append(pm)
                continue
            ticks = pm.ticks_for_symbol + 1
            if quote.exchange_timestamp_ns < self._bounds.official_close_ns:
                if ticks >= self._max_resting_ticks:
                    reject_fn(  # type: ignore[operator]
                        pm.request,
                        "moc timeout before official close",
                        timestamp_ns=max(
                            self._clock.now_ns(),
                            pm.ack_timestamp_ns,
                        ),
                    )
                    continue
                remaining.append(replace(pm, ticks_for_symbol=ticks))
                continue
            if quote.bid >= quote.ask:
                reject_fn(  # type: ignore[operator]
                    pm.request,
                    f"crossed or locked quote at close bid={quote.bid} ask={quote.ask}",
                    timestamp_ns=max(
                        self._clock.now_ns(),
                        pm.ack_timestamp_ns,
                    ),
                )
                continue
            fill_ts = max(pm.ack_timestamp_ns, quote.exchange_timestamp_ns)
            self._fill_at_close(pm.request, quote, fill_ts)
        self._pending = remaining

    def _fill_at_close(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
        fill_ts: int,
    ) -> None:
        """Single full fill at the closing mid (auction-price proxy)."""
        close_mid = (quote.bid + quote.ask) / Decimal("2")
        costs = self._cost_model.compute(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=close_mid,
            half_spread=Decimal("0"),
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
            fill_price=close_mid,
            fees=costs.total_fees,
            cost_bps=costs.cost_bps,
            request_sequence=request.sequence,
        ))
