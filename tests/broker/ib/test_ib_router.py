"""Unit tests for :class:`feelies.broker.ib.router.IBOrderRouter`.

Uses a fake :class:`IBGatewayConnection` so no socket is opened and
no IB Gateway is required.  Exercises the critical cumulative→delta
arithmetic, the synchronous ACK-at-submit + IB-callback dedup,
status mapping, partial-fill downgrade, cancel, duplicate-submit
rejection, and the unknown-order silent drop.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from feelies.broker.ib.connection import IBFillEvent
from feelies.broker.ib.router import IBOrderRouter
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)

if TYPE_CHECKING:
    from ibapi.contract import Contract  # type: ignore[import-untyped]
    from ibapi.order import Order as IBOrder  # type: ignore[import-untyped]


class _FakeIBConnection:
    """No-socket stand-in for IBGatewayConnection."""

    def __init__(self, *, clock: SimulatedClock, starting_id: int = 1000) -> None:
        self._clock = clock
        self._next_id = starting_id
        self._next_id_lock = threading.Lock()
        self.submitted_orders: list[tuple[int, object, object]] = []
        self.cancelled_orders: list[int] = []
        self._fills: list[IBFillEvent] = []

    def next_order_id(self) -> int:
        with self._next_id_lock:
            oid = self._next_id
            self._next_id += 1
            return oid

    def enqueue_order(
        self,
        ib_order_id: int,
        contract: "Contract",
        order: "IBOrder",
    ) -> None:
        self.submitted_orders.append((ib_order_id, contract, order))

    def enqueue_cancel(self, ib_order_id: int) -> None:
        self.cancelled_orders.append(ib_order_id)

    def poll_fills(self) -> list[IBFillEvent]:
        out = list(self._fills)
        self._fills.clear()
        return out

    def push_fill(self, fill: IBFillEvent) -> None:
        self._fills.append(fill)


def _make_request(
    order_id: str = "ord-1",
    *,
    quantity: int = 100,
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    sequence: int = 1,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1_000_000,
        correlation_id=f"cid:{order_id}",
        sequence=sequence,
        order_id=order_id,
        symbol="AAPL",
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        strategy_id="alpha_x",
    )


def _build_router(
    starting_id: int = 1000,
) -> tuple[IBOrderRouter, _FakeIBConnection, SimulatedClock]:
    clock = SimulatedClock(start_ns=1_000_000)
    conn = _FakeIBConnection(clock=clock, starting_id=starting_id)
    router = IBOrderRouter(connection=conn, clock=clock)  # type: ignore[arg-type]
    return router, conn, clock


# ── submit: synchronous ACK + IB enqueue ────────────────────────────


def test_submit_emits_acknowledged_synchronously() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-1"))
    acks = router.poll_acks()
    assert len(acks) == 1
    assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
    assert acks[0].order_id == "ord-1"
    assert acks[0].request_sequence == 1
    assert len(conn.submitted_orders) == 1


def test_submit_builds_market_buy_order() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-1", side=Side.BUY, order_type=OrderType.MARKET))
    _, _, ib_order = conn.submitted_orders[0]
    assert ib_order.action == "BUY"
    assert ib_order.orderType == "MKT"
    assert ib_order.totalQuantity == Decimal("100")
    assert ib_order.tif == "DAY"
    # ibapi >= 10.x defaults must be set, else IB rejects with Error 10268.
    assert ib_order.eTradeOnly is False
    assert ib_order.firmQuoteOnly is False


def test_submit_builds_limit_sell_order() -> None:
    router, conn, _ = _build_router()
    router.submit(
        _make_request(
            "ord-2",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.25"),
        )
    )
    _, _, ib_order = conn.submitted_orders[0]
    assert ib_order.action == "SELL"
    assert ib_order.orderType == "LMT"
    assert ib_order.lmtPrice == 150.25


def test_submit_limit_without_price_raises() -> None:
    router, _, _ = _build_router()
    with pytest.raises(ValueError, match="missing limit_price"):
        router.submit(
            _make_request(
                "ord-bad",
                order_type=OrderType.LIMIT,
                limit_price=None,
            )
        )


def test_duplicate_submit_emits_rejected_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-1"))
    router.submit(_make_request("ord-1", sequence=2))
    acks = router.poll_acks()
    assert len(acks) == 2
    assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
    assert acks[1].status == OrderAckStatus.REJECTED
    assert "duplicate" in acks[1].reason
    # Only the first submit reached the writer thread.
    assert len(conn.submitted_orders) == 1


# ── cumulative→delta arithmetic (quantity AND price) ────────────────


def _ack_for(router: IBOrderRouter, conn: _FakeIBConnection, fill: IBFillEvent) -> OrderAck | None:
    conn.push_fill(fill)
    acks = router.poll_acks()
    # Filter out the synchronous ACK already drained earlier.
    fill_acks = [a for a in acks if a.status != OrderAckStatus.ACKNOWLEDGED]
    return fill_acks[0] if fill_acks else None


def test_cumulative_to_delta_quantity() -> None:
    router, conn, _ = _build_router()
    req = _make_request("ord-q", quantity=100)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()  # drain synchronous ACK

    fill1 = IBFillEvent(
        ib_order_id=ib_id,
        status="Filled",
        cumulative_filled=50,
        remaining=50,
        avg_fill_price=100.0,
        timestamp_ns=2_000_000,
    )
    a1 = _ack_for(router, conn, fill1)
    assert a1 is not None and a1.filled_quantity == 50

    fill2 = IBFillEvent(
        ib_order_id=ib_id,
        status="Filled",
        cumulative_filled=70,
        remaining=30,
        avg_fill_price=100.0,
        timestamp_ns=2_100_000,
    )
    a2 = _ack_for(router, conn, fill2)
    assert a2 is not None and a2.filled_quantity == 20

    fill3 = IBFillEvent(
        ib_order_id=ib_id,
        status="Filled",
        cumulative_filled=100,
        remaining=0,
        avg_fill_price=100.0,
        timestamp_ns=2_200_000,
    )
    a3 = _ack_for(router, conn, fill3)
    assert a3 is not None and a3.filled_quantity == 30
    assert a3.status == OrderAckStatus.FILLED


def test_cumulative_to_delta_drops_duplicate_cumulative() -> None:
    router, conn, _ = _build_router()
    req = _make_request("ord-q2", quantity=100)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=100,
            remaining=0,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    # Duplicate cumulative — same total, delta = 0 → drop.
    # The router pruned _meta on the terminal FILLED above, so a
    # follow-on fill is treated as "not ours" and silently dropped.
    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=100,
            remaining=0,
            avg_fill_price=100.0,
            timestamp_ns=2_100_000,
        ),
    )
    assert a is None


def test_cumulative_to_delta_skips_negative_regression() -> None:
    router, conn, _ = _build_router()
    req = _make_request("ord-q3", quantity=200)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=100,
            remaining=100,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    # Cumulative regressed (impossible but defensive) → dropped silently.
    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=90,
            remaining=110,
            avg_fill_price=100.0,
            timestamp_ns=2_100_000,
        ),
    )
    assert a is None


def test_cumulative_to_delta_price() -> None:
    """Per-delta price: (cum_new * avg_new - cum_prev * avg_prev) / delta."""
    router, conn, _ = _build_router()
    req = _make_request("ord-p", quantity=100)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    # First fill: 50 @ $100 → cum_value = 5000, avg = 100.0
    a1 = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=50,
            remaining=50,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a1 is not None
    assert a1.fill_price == Decimal("100")

    # Second fill: cum=100 @ avg=100.50 → cum_value = 10050
    # delta_value = 10050 - 5000 = 5050, delta_qty = 50
    # per-delta price = 101.0  (NOT the cumulative VWAP 100.5)
    a2 = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=100,
            remaining=0,
            avg_fill_price=100.5,
            timestamp_ns=2_100_000,
        ),
    )
    assert a2 is not None
    assert a2.fill_price == Decimal("101")
    assert a2.status == OrderAckStatus.FILLED


# ── ACK dedup with IB PreSubmitted/Submitted callbacks ──────────────


def test_pre_submitted_callback_suppressed_after_synchronous_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-ack"))
    ib_id = conn.submitted_orders[0][0]
    # Drain the synchronous ACK already on _pending_acks.
    initial = router.poll_acks()
    assert len(initial) == 1 and initial[0].status == OrderAckStatus.ACKNOWLEDGED

    # IB's later PreSubmitted is suppressed — poll_acks emits nothing
    # (delta_qty == 0 and ACKNOWLEDGED maps to "already emitted").
    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="PreSubmitted",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is None
    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Submitted",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_100_000,
        ),
    )
    assert a is None


# ── status mapping table ─────────────────────────────────────────────


def test_pending_cancel_callback_suppressed() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-pc"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="PendingCancel",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is None


def test_partially_filled_status_maps_to_partial_ack() -> None:
    router, conn, _ = _build_router()
    req = _make_request("ord-pf2", quantity=100)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="PartiallyFilled",
            cumulative_filled=40,
            remaining=60,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None
    assert a.status == OrderAckStatus.PARTIALLY_FILLED
    assert a.filled_quantity == 40


def test_status_expired_maps_to_expired_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-x"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Expired",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None and a.status == OrderAckStatus.EXPIRED


def test_place_order_failure_emits_rejected_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-writer-fail"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="error",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
            error_code=0,
            error_msg="placeOrder:RuntimeError:socket wedged",
        ),
    )
    assert a is not None and a.status == OrderAckStatus.REJECTED
    assert ib_id not in router._meta  # type: ignore[attr-defined]


def test_status_cancelled_maps_to_cancelled_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-c"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Cancelled",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None and a.status == OrderAckStatus.CANCELLED


def test_status_api_cancelled_maps_to_cancelled_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-ac"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="ApiCancelled",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None and a.status == OrderAckStatus.CANCELLED


def test_status_inactive_maps_to_rejected_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-i"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Inactive",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None and a.status == OrderAckStatus.REJECTED


def test_error_code_201_maps_to_rejected_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-e201"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="error",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
            error_code=201,
            error_msg="rejected by venue",
        ),
    )
    assert a is not None and a.status == OrderAckStatus.REJECTED
    assert "201" in a.reason


def test_error_code_202_maps_to_cancelled_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-e202"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="error",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
            error_code=202,
            error_msg="cancelled",
        ),
    )
    assert a is not None and a.status == OrderAckStatus.CANCELLED


def test_unknown_error_code_maps_to_rejected_ack() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-e399"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="error",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
            error_code=399,
            error_msg="order size below minimum",
        ),
    )
    assert a is not None and a.status == OrderAckStatus.REJECTED
    assert "399" in a.reason


@pytest.mark.parametrize("code", [1100, 1101, 1102, 2110])
def test_connectivity_error_codes_drop_ack(code: int) -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-conn"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="error",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
            error_code=code,
            error_msg="conn",
        ),
    )
    assert a is None


def test_unknown_orderstatus_string_dropped() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-u"))
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="MysteryStatus",
            cumulative_filled=0,
            remaining=100,
            avg_fill_price=0.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is None


def test_unknown_order_id_silently_dropped() -> None:
    router, conn, _ = _build_router()
    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=99999,
            status="Filled",
            cumulative_filled=10,
            remaining=0,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is None


# ── partial-fill defensive downgrade ────────────────────────────────


def test_filled_status_downgraded_to_partial_when_qty_short() -> None:
    router, conn, _ = _build_router()
    req = _make_request("ord-pf", quantity=100)
    router.submit(req)
    ib_id = conn.submitted_orders[0][0]
    router.poll_acks()

    a = _ack_for(
        router,
        conn,
        IBFillEvent(
            ib_order_id=ib_id,
            status="Filled",
            cumulative_filled=60,
            remaining=40,
            avg_fill_price=100.0,
            timestamp_ns=2_000_000,
        ),
    )
    assert a is not None
    assert a.status == OrderAckStatus.PARTIALLY_FILLED
    assert a.filled_quantity == 60


# ── cancel_order ────────────────────────────────────────────────────


def test_cancel_known_order_returns_true_and_enqueues_ib_cancel() -> None:
    router, conn, _ = _build_router()
    router.submit(_make_request("ord-c1"))
    ib_id = conn.submitted_orders[0][0]

    result = router.cancel_order("ord-c1")
    assert result is True
    assert conn.cancelled_orders == [ib_id]


def test_cancel_unknown_order_returns_false() -> None:
    router, conn, _ = _build_router()
    assert router.cancel_order("never-submitted") is False
    assert conn.cancelled_orders == []
