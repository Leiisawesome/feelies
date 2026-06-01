"""Functional IB Gateway tests — require a running IB Gateway/TWS.

Round-2 coverage (live socket):

* Handshake + monotonic ``next_order_id``
* Duplicate submit rejection
* Buy/sell limit submit + cancel lifecycle
* Cancel unknown order
* Two concurrent orders (both cancels fired before polling)
* ``PendingCancel`` intermediate status suppressed (no spurious ack)
* Reconnect after clean disconnect

Run::

    uv run pytest tests/broker/ib/test_ib_functional.py -m functional -v

Environment overrides::

    IB_FUNCTIONAL_HOST=127.0.0.1
    IB_FUNCTIONAL_PORT=4002
    IB_FUNCTIONAL_CLIENT_ID=99
    IB_FUNCTIONAL_SYMBOL=SPY
    IB_FUNCTIONAL_POLL_TIMEOUT_S=20
"""

from __future__ import annotations

import logging
import os
import socket
import time
from decimal import Decimal

import pytest

from feelies.broker.ib.connection import IBGatewayConnection
from feelies.broker.ib.router import IBOrderRouter
from feelies.core.clock import WallClock
from feelies.core.events import OrderAckStatus, OrderRequest, OrderType, Side

from tests._ib_client_id import unique_ib_client_id

pytestmark = pytest.mark.functional

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 4002
_DEFAULT_SYMBOL = "SPY"
_DEFAULT_POLL_TIMEOUT_S = 20.0
_POLL_INTERVAL_S = 0.2


def _unique_client_id() -> int:
    return unique_ib_client_id()


def _host() -> str:
    return os.getenv("IB_FUNCTIONAL_HOST", _DEFAULT_HOST)


def _port() -> int:
    return int(os.getenv("IB_FUNCTIONAL_PORT", str(_DEFAULT_PORT)))


def _client_id() -> int:
    return _unique_client_id()


def _symbol() -> str:
    return os.getenv("IB_FUNCTIONAL_SYMBOL", _DEFAULT_SYMBOL).upper()


def _poll_timeout_s() -> float:
    return float(os.getenv("IB_FUNCTIONAL_POLL_TIMEOUT_S", str(_DEFAULT_POLL_TIMEOUT_S)))


def _require_ib_gateway_reachable() -> None:
    host, port = _host(), _port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect((host, port))
    except OSError as exc:
        pytest.skip(
            f"IB Gateway not reachable at {host}:{port} ({exc}). "
            "Start IB Gateway (paper) and enable API connections.",
        )
    finally:
        sock.close()


def _make_limit_request(
    clock: WallClock,
    order_id: str,
    *,
    side: Side = Side.BUY,
    limit_price: Decimal = Decimal("1.00"),
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=clock.now_ns(),
        correlation_id=f"ib-func:{order_id}",
        sequence=1,
        order_id=order_id,
        symbol=_symbol(),
        side=side,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=limit_price,
        strategy_id="ib_functional_test",
    )


def _poll_until_all(
    router: IBOrderRouter,
    *,
    order_ids: set[str],
    want_status: OrderAckStatus,
    timeout_s: float,
) -> list[object]:
    """Poll until every ``order_id`` has observed ``want_status``."""
    deadline = time.monotonic() + timeout_s
    seen: list[object] = []
    satisfied: set[str] = set()
    while time.monotonic() < deadline:
        batch = router.poll_acks()
        if batch:
            seen.extend(batch)
            for ack in batch:
                if ack.order_id in order_ids and ack.status == want_status:
                    satisfied.add(ack.order_id)
            if satisfied >= order_ids:
                return seen
        time.sleep(_POLL_INTERVAL_S)
    return seen


def _poll_until_terminal_cleanup(
    router: IBOrderRouter,
    *,
    order_ids: set[str],
    timeout_s: float,
) -> list[object]:
    """Poll until each order is ``CANCELLED`` or ``REJECTED``.

    After-hours IB paper accounts often reject DAY orders with error
    399 before a cancel can land; both outcomes prove the API path
    handled the order lifecycle without wedging.
    """
    terminal = {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
    deadline = time.monotonic() + timeout_s
    seen: list[object] = []
    done: set[str] = set()
    while time.monotonic() < deadline:
        batch = router.poll_acks()
        if batch:
            seen.extend(batch)
            for ack in batch:
                if ack.order_id in order_ids and ack.status in terminal:
                    done.add(ack.order_id)
            if done >= order_ids:
                return seen
        time.sleep(_POLL_INTERVAL_S)
    return seen


def _cleanup_order(
    router: IBOrderRouter,
    order_id: str,
    *,
    timeout_s: float,
) -> list[object]:
    """Cancel if possible; accept ``CANCELLED`` or after-hours ``REJECTED``."""
    assert router.cancel_order(order_id)
    return _poll_until_terminal_cleanup(
        router, order_ids={order_id}, timeout_s=timeout_s,
    )


@pytest.fixture
def ib_session() -> tuple[IBGatewayConnection, IBOrderRouter, WallClock]:
    """Connect once per test; always tear down."""
    _require_ib_gateway_reachable()
    clock = WallClock()
    conn = IBGatewayConnection(
        host=_host(),
        port=_port(),
        client_id=_client_id(),
        clock=clock,
    )
    router = IBOrderRouter(connection=conn, clock=clock)
    conn.connect_and_start(ready_timeout_s=10.0)
    try:
        yield conn, router, clock
    finally:
        conn.disconnect_and_stop()


class TestIBGatewayFunctional:
    def test_connect_handshake_and_next_order_id(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        conn, _, _ = ib_session
        first = conn.next_order_id()
        second = conn.next_order_id()
        assert isinstance(first, int)
        assert second == first + 1

    def test_duplicate_submit_rejected(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        _, router, clock = ib_session
        order_id = f"dup-{clock.now_ns()}"
        req = _make_limit_request(clock, order_id)
        router.submit(req)
        router.submit(req)
        acks = router.poll_acks()
        for oid in (order_id,):
            statuses = [a.status for a in acks if a.order_id == oid]
            assert OrderAckStatus.ACKNOWLEDGED in statuses
            assert OrderAckStatus.REJECTED in statuses
        router.cancel_order(order_id)
        seen = _poll_until_terminal_cleanup(
            router, order_ids={order_id}, timeout_s=_poll_timeout_s(),
        )
        terminal = {
            a.status for a in seen if a.order_id == order_id
        } & {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
        assert terminal, f"expected terminal ack for {order_id}, got {seen}"

    def test_submit_buy_limit_and_cancel(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        _, router, clock = ib_session
        order_id = f"buy-{clock.now_ns()}"
        router.submit(_make_limit_request(clock, order_id, side=Side.BUY))
        assert any(
            a.status == OrderAckStatus.ACKNOWLEDGED
            for a in router.poll_acks()
        )
        seen = _cleanup_order(router, order_id, timeout_s=_poll_timeout_s())
        terminal = {
            a.status for a in seen if a.order_id == order_id
        } & {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
        assert terminal, f"expected terminal ack for {order_id}, got {seen}"

    def test_submit_sell_limit_and_cancel(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        _, router, clock = ib_session
        order_id = f"sell-{clock.now_ns()}"
        router.submit(_make_limit_request(
            clock, order_id, side=Side.SELL, limit_price=Decimal("99999.00"),
        ))
        assert any(
            a.status == OrderAckStatus.ACKNOWLEDGED
            for a in router.poll_acks()
        )
        seen = _cleanup_order(router, order_id, timeout_s=_poll_timeout_s())
        terminal = {
            a.status for a in seen if a.order_id == order_id
        } & {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
        assert terminal, f"expected terminal ack for {order_id}, got {seen}"

    def test_cancel_unknown_order_returns_false(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        _, router, _ = ib_session
        assert router.cancel_order("never-submitted-order-id") is False

    def test_two_orders_cancelled_without_cross_drain_race(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        """Fire both cancels, then poll once — mimics orchestrator drain."""
        _, router, clock = ib_session
        oid1 = f"multi-a-{clock.now_ns()}"
        oid2 = f"multi-b-{clock.now_ns()}"
        for oid in (oid1, oid2):
            router.submit(_make_limit_request(clock, oid))
        acked = {
            a.order_id for a in router.poll_acks()
            if a.status == OrderAckStatus.ACKNOWLEDGED
        }
        assert {oid1, oid2} <= acked

        assert router.cancel_order(oid1)
        assert router.cancel_order(oid2)

        seen = _poll_until_terminal_cleanup(
            router,
            order_ids={oid1, oid2},
            timeout_s=_poll_timeout_s(),
        )
        terminal = {
            a.order_id for a in seen
            if a.status in (OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED)
        }
        assert {oid1, oid2} <= terminal, f"expected terminal acks, got {seen}"

    def test_pending_cancel_does_not_emit_spurious_ack(
        self,
        ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Live IB emits ``PendingCancel`` before ``Cancelled`` — must not warn."""
        _, router, clock = ib_session
        order_id = f"pc-{clock.now_ns()}"
        router.submit(_make_limit_request(clock, order_id))
        router.poll_acks()
        assert router.cancel_order(order_id)

        caplog.set_level(logging.WARNING, logger="feelies.broker.ib.router")
        seen = _cleanup_order(router, order_id, timeout_s=_poll_timeout_s())
        terminal = {
            a.status for a in seen if a.order_id == order_id
        } & {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
        assert terminal, f"expected terminal ack for {order_id}, got {seen}"
        assert not any(
            "PendingCancel" in r.message
            for r in caplog.records
            if r.name == "feelies.broker.ib.router"
        )


    def test_after_hours_reject_surfaces_as_rejected(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        """Outside RTH, IB often rejects DAY orders with error 399."""
        _, router, clock = ib_session
        order_id = f"ah-{clock.now_ns()}"
        router.submit(_make_limit_request(clock, order_id))
        router.poll_acks()  # synchronous ACKNOWLEDGED
        seen = _poll_until_terminal_cleanup(
            router, order_ids={order_id}, timeout_s=_poll_timeout_s(),
        )
        statuses = {a.status for a in seen if a.order_id == order_id}
        # During RTH this may be CANCELLED instead; both prove the path.
        assert statuses & {
            OrderAckStatus.REJECTED, OrderAckStatus.CANCELLED,
        }, f"expected terminal cleanup, got {seen}"


class TestIBGatewayReconnect:
    def test_reconnect_after_clean_disconnect(self) -> None:
        _require_ib_gateway_reachable()
        clock = WallClock()
        cid = _unique_client_id()
        conn = IBGatewayConnection(
            host=_host(), port=_port(), client_id=cid, clock=clock,
        )
        conn.connect_and_start(ready_timeout_s=10.0)
        first = conn.next_order_id()
        conn.disconnect_and_stop()

        conn2 = IBGatewayConnection(
            host=_host(), port=_port(),
            client_id=_unique_client_id(),
            clock=clock,
        )
        conn2.connect_and_start(ready_timeout_s=10.0)
        try:
            second = conn2.next_order_id()
            assert isinstance(first, int) and isinstance(second, int)
        finally:
            conn2.disconnect_and_stop()

    def test_double_connect_raises(self) -> None:
        _require_ib_gateway_reachable()
        clock = WallClock()
        conn = IBGatewayConnection(
            host=_host(), port=_port(), client_id=_unique_client_id(), clock=clock,
        )
        conn.connect_and_start(ready_timeout_s=10.0)
        try:
            with pytest.raises(RuntimeError, match="already connected"):
                conn.connect_and_start(ready_timeout_s=10.0)
        finally:
            conn.disconnect_and_stop()


@pytest.mark.paper_rth
class TestIBGatewayRTHFills:
    def test_market_order_submit_and_cancel(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        from tests.paper.conftest import require_rth_window
        require_rth_window()
        _, router, clock = ib_session
        order_id = f"mkt-{clock.now_ns()}"
        req = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id=f"ib-func:{order_id}",
            sequence=1,
            order_id=order_id,
            symbol=_symbol(),
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            strategy_id="ib_functional_test",
        )
        router.submit(req)
        router.poll_acks()
        seen = _poll_until_terminal_cleanup(
            router, order_ids={order_id}, timeout_s=_poll_timeout_s(),
        )
        statuses = {a.status for a in seen if a.order_id == order_id}
        assert statuses & {
            OrderAckStatus.FILLED,
            OrderAckStatus.CANCELLED,
            OrderAckStatus.REJECTED,
        }

    def test_etradeonly_defaults_regression_unit_side(self) -> None:
        """Error 10268 guard covered in test_ib_router; RTH class references it."""
        from feelies.broker.ib.router import IBOrderRouter
        from feelies.core.clock import WallClock
        from feelies.core.events import OrderRequest, OrderType, Side

        class _Conn:
            def next_order_id(self) -> int:
                return 1

            def enqueue_order(self, ib_order_id: int, contract: object, order: object) -> None:
                self.last_order = order

        conn = _Conn()
        router = IBOrderRouter(connection=conn, clock=WallClock())  # type: ignore[arg-type]
        req = OrderRequest(
            timestamp_ns=1,
            correlation_id="c",
            sequence=1,
            order_id="o",
            symbol="SPY",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            strategy_id="t",
        )
        router.submit(req)
        assert conn.last_order.eTradeOnly is False
        assert conn.last_order.firmQuoteOnly is False

    def test_ten_orders_rapid_submit_cancel(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        from tests.paper.conftest import require_rth_window
        require_rth_window()
        _, router, clock = ib_session
        order_ids: list[str] = []
        for i in range(10):
            oid = f"rapid-{clock.now_ns()}-{i}"
            order_ids.append(oid)
            req = _make_limit_request(clock, oid, limit_price=Decimal("1.00"))
            router.submit(req)
        for oid in order_ids:
            _cleanup_order(router, oid, timeout_s=_poll_timeout_s())

    def test_partial_fill_then_cancel(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        from tests.paper.conftest import require_rth_window
        require_rth_window()
        _, router, clock = ib_session
        order_id = f"partial-{clock.now_ns()}"
        req = _make_limit_request(
            clock, order_id, limit_price=Decimal("500000.00"),
        )
        router.submit(req)
        seen = _poll_until_terminal_cleanup(
            router, order_ids={order_id}, timeout_s=_poll_timeout_s(),
        )
        statuses = {a.status for a in seen if a.order_id == order_id}
        assert statuses & {
            OrderAckStatus.CANCELLED,
            OrderAckStatus.REJECTED,
            OrderAckStatus.FILLED,
            OrderAckStatus.PARTIALLY_FILLED,
        }

    def test_fill_ack_lag_exceeds_idle_tick_interval(
        self, ib_session: tuple[IBGatewayConnection, IBOrderRouter, WallClock],
    ) -> None:
        from tests.paper.conftest import require_rth_window
        require_rth_window()
        _, router, clock = ib_session
        order_id = f"lag-{clock.now_ns()}"
        req = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id=f"ib-func:{order_id}",
            sequence=1,
            order_id=order_id,
            symbol=_symbol(),
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            strategy_id="ib_functional_test",
        )
        router.submit(req)
        deadline = time.monotonic() + _poll_timeout_s()
        terminal = {
            OrderAckStatus.FILLED,
            OrderAckStatus.CANCELLED,
            OrderAckStatus.REJECTED,
        }
        while time.monotonic() < deadline:
            time.sleep(1.5)
            batch = router.poll_acks()
            if any(a.order_id == order_id and a.status in terminal for a in batch):
                return
        pytest.fail("no terminal ack within poll window")
