"""IB order router — adapts :class:`IBGatewayConnection` to ``OrderRouter``.

Mirrors the structural shape of
:class:`feelies.execution.backtest_router.BacktestOrderRouter` so the
orchestrator's order-lifecycle path stays bit-identical (Inv-9):

* :meth:`submit` synchronously appends an ``ACKNOWLEDGED`` ``OrderAck``
  (parity with ``BacktestOrderRouter.submit``).
* IB's subsequent ``PreSubmitted`` / ``Submitted`` callback is
  deduplicated by ``_has_acked`` so the platform never observes a
  double-ACK.
* :meth:`poll_acks` converts each IB ``orderStatus`` callback's
  **cumulative** quantity and **cumulative VWAP** into per-delta
  values via ``(cum * avg − prev_cum * prev_avg) / delta`` —
  emitting either as cumulative would silently mis-count positions
  (qty bug) or skew realized PnL (price bug).
* :meth:`cancel_order` is duck-typed (see
  :class:`feelies.execution.backend.OrderRouter` docstring) and
  returns ``True`` for any known platform id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from feelies.core.clock import Clock
from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.broker.ib.connection import IBFillEvent, IBGatewayConnection
from feelies.broker.ib.contracts import stock_contract

if TYPE_CHECKING:
    from ibapi.order import Order as IBOrder  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# IB error code → terminal OrderAckStatus mapping (subset; the rest
# fall through to the textual-status mapping below).
_IB_REJECT_CODES = frozenset({201})
_IB_CANCEL_CODES = frozenset({202})
# Connection-level error codes — translated to alerts (no OrderAck).
_IB_CONNECTIVITY_CODES = frozenset({1100, 1101, 1102, 2110})

# Textual ``orderStatus.status`` → OrderAckStatus mapping (post-error
# triage).  ``PreSubmitted`` / ``Submitted`` map to ACKNOWLEDGED but
# the router suppresses them in poll_acks because submit() already
# emitted the ack at submission time.
_STATUS_TO_ACK = {
    "PreSubmitted": OrderAckStatus.ACKNOWLEDGED,
    "Submitted": OrderAckStatus.ACKNOWLEDGED,
    "PendingSubmit": OrderAckStatus.ACKNOWLEDGED,
    "PendingCancel": OrderAckStatus.ACKNOWLEDGED,
    "PartiallyFilled": OrderAckStatus.PARTIALLY_FILLED,
    "Filled": OrderAckStatus.FILLED,
    "Cancelled": OrderAckStatus.CANCELLED,
    "ApiCancelled": OrderAckStatus.CANCELLED,
    "Inactive": OrderAckStatus.REJECTED,
    "Expired": OrderAckStatus.EXPIRED,
}


@dataclass(frozen=True)
class _IBOrderMeta:
    """Per-order bookkeeping kept on the router (main thread only)."""

    platform_id: str
    symbol: str
    correlation_id: str
    request_sequence: int
    total_quantity: int
    strategy_id: str


class IBOrderRouter:
    """Routes ``OrderRequest`` events through IB Gateway.

    Constructed with an already-built :class:`IBGatewayConnection` so
    the orchestrator's lifecycle (connect → start → submit → drain →
    disconnect) is owned by the entry script (``scripts/run_paper.py``)
    not the router.
    """

    def __init__(
        self,
        *,
        connection: IBGatewayConnection,
        clock: Clock,
    ) -> None:
        self._connection = connection
        self._clock = clock
        self._ack_seq = SequenceGenerator()
        self._pending_acks: list[OrderAck] = []
        self._meta: dict[int, _IBOrderMeta] = {}
        self._platform_to_ib: dict[str, int] = {}
        self._last_cumulative: dict[int, int] = {}
        self._last_cum_value: dict[int, Decimal] = {}
        self._has_acked: dict[int, bool] = {}
        self._submitted_order_ids: set[str] = set()

    # ── OrderRouter protocol ────────────────────────────────────────

    def submit(self, request: OrderRequest) -> None:
        """Synchronous submit-time ACK + enqueue to IB writer thread.

        Duplicate ``order_id`` submissions are REJECTED rather than
        silently double-routed (mirrors
        :meth:`BacktestOrderRouter.submit` and preserves Inv-11).
        """
        if request.order_id in self._submitted_order_ids:
            self._pending_acks.append(OrderAck(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=request.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.REJECTED,
                reason=f"duplicate order_id: {request.order_id}",
                request_sequence=request.sequence,
            ))
            return
        self._submitted_order_ids.add(request.order_id)

        ib_id = self._connection.next_order_id()
        self._meta[ib_id] = _IBOrderMeta(
            platform_id=request.order_id,
            symbol=request.symbol,
            correlation_id=request.correlation_id,
            request_sequence=request.sequence,
            total_quantity=request.quantity,
            strategy_id=request.strategy_id,
        )
        self._platform_to_ib[request.order_id] = ib_id

        contract = stock_contract(request.symbol)
        ib_order = self._build_ib_order(request)
        self._connection.enqueue_order(ib_id, contract, ib_order)

        # Synchronous ACKNOWLEDGED (mirrors BacktestOrderRouter.submit).
        # Suppresses IB's PreSubmitted/Submitted echo via _has_acked.
        self._pending_acks.append(OrderAck(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))
        self._has_acked[ib_id] = True

    def poll_acks(self) -> list[OrderAck]:
        """Drain pending submit-time acks + IB fill-queue callbacks."""
        out: list[OrderAck] = list(self._pending_acks)
        self._pending_acks.clear()
        for fill in self._connection.poll_fills():
            ack = self._fill_to_ack(fill)
            if ack is not None:
                out.append(ack)
        return out

    # ── Duck-typed optional API ─────────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """Enqueue a cancel for a known platform order id.

        Returns ``True`` when the order is known to the router (the
        IB cancel is fire-and-forget; the eventual ``Cancelled``
        callback flows through :meth:`poll_acks` as a ``CANCELLED``
        :class:`OrderAck`).  Returns ``False`` for unknown ids so the
        orchestrator's local CANCELLED transition still runs.
        """
        ib_id = self._platform_to_ib.get(order_id)
        if ib_id is None:
            return False
        self._connection.enqueue_cancel(ib_id)
        return True

    # ── Internals ───────────────────────────────────────────────────

    def _prune_ib_order(self, ib_order_id: int) -> None:
        """Drop per-IB-id runtime bookkeeping after a terminal ack."""
        self._meta.pop(ib_order_id, None)
        self._last_cumulative.pop(ib_order_id, None)
        self._last_cum_value.pop(ib_order_id, None)
        self._has_acked.pop(ib_order_id, None)

    def _build_ib_order(self, request: OrderRequest) -> "IBOrder":
        from ibapi.order import Order

        order = Order()
        order.action = "BUY" if request.side == Side.BUY else "SELL"
        if request.order_type == OrderType.LIMIT:
            order.orderType = "LMT"
            if request.limit_price is None:
                raise ValueError(
                    f"LIMIT order_id={request.order_id!r} missing limit_price",
                )
            order.lmtPrice = float(request.limit_price)
        else:
            order.orderType = "MKT"
        # ibapi >= 10.x uses Decimal for totalQuantity.
        order.totalQuantity = Decimal(str(int(request.quantity)))
        order.tif = "DAY"
        # ibapi >= 10.x defaults bite hard: missing these reject every
        # order with Error 10268 ("eTradeOnly / firmQuoteOnly defaults").
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        return order

    def _fill_to_ack(self, fill: IBFillEvent) -> OrderAck | None:
        """Convert a single ``IBFillEvent`` to an ``OrderAck`` (or None).

        ``None`` means the callback was handled but should not surface
        as a platform ack — e.g. a connectivity-error code (alert path)
        or a redundant ``PreSubmitted``/``Submitted`` echo for an
        already-acknowledged order.
        """
        meta = self._meta.get(fill.ib_order_id)
        if meta is None:
            return None  # not our order; drop silently

        # Connectivity errors carry an error_code in our reserved set —
        # surface as a future alert path (TODO: emit Alert via the
        # orchestrator once we have a wiring hook); for now we just log
        # and drop the ack so the orchestrator never sees a malformed
        # ``OrderAck(filled_quantity=0, fill_price=None)``.
        if (
            fill.error_code is not None
            and fill.error_code in _IB_CONNECTIVITY_CODES
        ):
            logger.warning(
                "ib connectivity event for order_id=%s code=%s msg=%s",
                meta.platform_id,
                fill.error_code,
                fill.error_msg,
            )
            return None

        # Map error codes first; they trump the textual status (which
        # is empty on error callbacks).
        if fill.error_code in _IB_REJECT_CODES:
            self._prune_ib_order(fill.ib_order_id)
            return OrderAck(
                timestamp_ns=fill.timestamp_ns,
                correlation_id=meta.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=meta.platform_id,
                symbol=meta.symbol,
                status=OrderAckStatus.REJECTED,
                reason=f"ib_error:{fill.error_code}:{fill.error_msg}",
                request_sequence=meta.request_sequence,
            )
        if fill.error_code in _IB_CANCEL_CODES:
            self._prune_ib_order(fill.ib_order_id)
            return OrderAck(
                timestamp_ns=fill.timestamp_ns,
                correlation_id=meta.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=meta.platform_id,
                symbol=meta.symbol,
                status=OrderAckStatus.CANCELLED,
                reason=f"ib_error:{fill.error_code}:{fill.error_msg}",
                request_sequence=meta.request_sequence,
            )
        if fill.error_code is not None:
            self._prune_ib_order(fill.ib_order_id)
            return OrderAck(
                timestamp_ns=fill.timestamp_ns,
                correlation_id=meta.correlation_id,
                sequence=self._ack_seq.next(),
                order_id=meta.platform_id,
                symbol=meta.symbol,
                status=OrderAckStatus.REJECTED,
                reason=f"ib_error:{fill.error_code}:{fill.error_msg}",
                request_sequence=meta.request_sequence,
            )

        status = _STATUS_TO_ACK.get(fill.status)
        if status is None:
            logger.warning(
                "ib router: unrecognised orderStatus=%r for ib_id=%d (dropped)",
                fill.status,
                fill.ib_order_id,
            )
            _alert_cb = getattr(self._connection, "_alert_callback", None)
            if _alert_cb is not None:
                try:
                    _alert_cb(
                        0,
                        f"unrecognised_order_status:{fill.status!r} "
                        f"ib_id={fill.ib_order_id} "
                        f"platform_id={meta.platform_id}",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("ib router: alert_callback raised")
            return None

        # PreSubmitted / Submitted — already emitted at submit time.
        if status == OrderAckStatus.ACKNOWLEDGED:
            return None

        prev_qty = self._last_cumulative.get(fill.ib_order_id, 0)
        delta_qty = fill.cumulative_filled - prev_qty
        if delta_qty < 0:
            logger.warning(
                "ib router: cumulative regression for ib_id=%d "
                "(prev=%d new=%d) — dropped",
                fill.ib_order_id,
                prev_qty,
                fill.cumulative_filled,
            )
            return None

        # Per-delta VWAP: (cum_new * avg_new - cum_prev * avg_prev) / delta.
        # Computing this BEFORE mutating _last_cum_value is critical.
        prev_value = self._last_cum_value.get(
            fill.ib_order_id, Decimal("0"),
        )
        new_avg = Decimal(str(fill.avg_fill_price))
        new_value = new_avg * Decimal(fill.cumulative_filled)
        delta_value = new_value - prev_value
        per_delta_price: Decimal | None = (
            (delta_value / Decimal(delta_qty)) if delta_qty > 0 else None
        )

        self._last_cumulative[fill.ib_order_id] = fill.cumulative_filled
        self._last_cum_value[fill.ib_order_id] = new_value

        # Status-only echoes with no new quantity are redundant.
        if (
            status in (OrderAckStatus.FILLED, OrderAckStatus.PARTIALLY_FILLED)
            and delta_qty == 0
        ):
            return None

        # Defensive partial-fill downgrade: IB occasionally sends
        # status="Filled" before the final lot lands.
        if (
            status == OrderAckStatus.FILLED
            and fill.cumulative_filled < meta.total_quantity
        ):
            status = OrderAckStatus.PARTIALLY_FILLED

        ack = OrderAck(
            timestamp_ns=fill.timestamp_ns,
            correlation_id=meta.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=meta.platform_id,
            symbol=meta.symbol,
            status=status,
            filled_quantity=delta_qty,
            fill_price=per_delta_price,
            request_sequence=meta.request_sequence,
        )

        # Prune on terminal statuses so we don't leak metadata.
        if status in (
            OrderAckStatus.FILLED,
            OrderAckStatus.CANCELLED,
            OrderAckStatus.REJECTED,
            OrderAckStatus.EXPIRED,
        ):
            self._prune_ib_order(fill.ib_order_id)

        return ack
