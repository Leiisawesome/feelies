"""Unit tests for :class:`feelies.broker.ib.connection.IBGatewayConnection`.

These tests bypass the real socket by monkeypatching ``EClient.connect``
and the ``placeOrder`` / ``cancelOrder`` / ``disconnect`` calls on the
connection instance.  They exercise:

* ``next_order_id`` raises before ``nextValidId`` arrives, then is
  thread-safe + monotonic afterwards.
* The writer thread is the exclusive caller of ``placeOrder`` /
  ``cancelOrder`` (queue serialisation under concurrent enqueue).
* ``poll_fills`` drains the queue non-blockingly.
* ``error(reqId=-1, ...)`` is logged but does NOT reach the fill queue.
* ``orderStatus`` populates the fill queue with the canonical
  :class:`IBFillEvent`.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any

import pytest

from feelies.broker.ib.connection import IBFillEvent, IBGatewayConnection
from feelies.core.clock import SimulatedClock

try:
    from ibapi.client import EClient  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    EClient = object  # type: ignore[misc, assignment]


def _build_conn(monkeypatch: pytest.MonkeyPatch) -> tuple[IBGatewayConnection, dict[str, list]]:
    """Build a connection with stubbed networking — does NOT start threads."""
    clock = SimulatedClock(start_ns=1_000_000)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    captured = {"place": [], "cancel": [], "disconnect": [], "connect": []}

    def _fake_connect(host: str, port: int, clientId: int) -> None:  # noqa: N803
        captured["connect"].append((host, port, clientId))

    def _fake_disconnect() -> None:
        captured["disconnect"].append(True)
        conn._shutdown_event.set()

    def _fake_run() -> None:
        # Block until shutdown_event flips (simulates ibapi's blocking
        # message loop until disconnect()).
        conn._shutdown_event.wait(timeout=5.0)

    def _fake_place(ib_id: int, contract: Any, order: Any) -> None:
        captured["place"].append((ib_id, contract, order))

    def _fake_cancel(ib_id: int, order_cancel: Any = None) -> None:  # noqa: ARG001
        captured["cancel"].append(ib_id)

    monkeypatch.setattr(conn, "connect", _fake_connect)
    monkeypatch.setattr(conn, "disconnect", _fake_disconnect)
    monkeypatch.setattr(conn, "run", _fake_run)
    monkeypatch.setattr(conn, "placeOrder", _fake_place)
    monkeypatch.setattr(conn, "cancelOrder", _fake_cancel)
    return conn, captured


def test_next_valid_id_never_regresses_on_reconnect_pulse() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.nextValidId(100)
    assert conn.next_order_id() == 100
    assert conn.next_order_id() == 101
    # Simulate IB reconnect handing back a stale lower baseline.
    conn.nextValidId(50)
    assert conn.next_order_id() == 102
    # Fresh reconnect with higher baseline bumps forward.
    conn.nextValidId(500)
    assert conn.next_order_id() == 500


def test_next_order_id_raises_before_handshake() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    with pytest.raises(RuntimeError, match="nextValidId not received"):
        conn.next_order_id()


def test_next_order_id_monotonic_after_handshake() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.nextValidId(100)
    assert conn.next_order_id() == 100
    assert conn.next_order_id() == 101
    assert conn.next_order_id() == 102


def test_next_order_id_thread_safe_under_parallel_calls() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.nextValidId(0)
    collected: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(100):
            oid = conn.next_order_id()
            with lock:
                collected.append(oid)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(collected) == 800
    assert len(set(collected)) == 800
    assert sorted(collected) == list(range(800))


def test_place_order_failure_pushes_synthetic_fill_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, captured = _build_conn(monkeypatch)

    def _boom(ib_id: int, contract: Any, order: Any) -> None:
        raise RuntimeError("socket wedged")

    monkeypatch.setattr(conn, "placeOrder", _boom)
    conn._writer_place_order(7, object(), object())
    fills = conn.poll_fills()
    assert len(fills) == 1
    assert fills[0].ib_order_id == 7
    assert fills[0].error_code == 0
    assert "placeOrder:RuntimeError" in (fills[0].error_msg or "")


def test_run_suppresses_server_version_teardown_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn._shutdown_event.set()

    def _boom() -> None:
        raise TypeError("'>=' not supported between instances of 'NoneType' and 'int'")

    monkeypatch.setattr(conn, "isConnected", lambda: False)
    monkeypatch.setattr(EClient, "run", _boom, raising=False)
    # Should not raise — shutdown path swallows the ibapi race.
    conn.run()


def test_connect_and_start_blocks_until_next_valid_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, captured = _build_conn(monkeypatch)

    # Schedule nextValidId arrival after 100ms.
    def deliver_handshake() -> None:
        time.sleep(0.1)
        conn.nextValidId(500)

    threading.Thread(target=deliver_handshake, daemon=True).start()
    conn.connect_and_start(ready_timeout_s=2.0)

    assert captured["connect"] == [("127.0.0.1", 4002, 1)]
    assert conn.next_order_id() == 500

    conn.disconnect_and_stop()


def test_connect_and_start_times_out_when_no_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, _ = _build_conn(monkeypatch)
    with pytest.raises(RuntimeError, match="nextValidId not received within"):
        conn.connect_and_start(ready_timeout_s=0.2)


def test_writer_thread_serialises_submit_and_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, captured = _build_conn(monkeypatch)
    threading.Thread(
        target=lambda: (time.sleep(0.05), conn.nextValidId(1)),
        daemon=True,
    ).start()
    conn.connect_and_start(ready_timeout_s=2.0)

    # Submit 50 orders + 25 cancels from 4 worker threads concurrently;
    # the writer thread is the sole observer.
    def submit_batch(start: int) -> None:
        for i in range(start, start + 25):
            conn.enqueue_order(i, object(), object())

    def cancel_batch(start: int) -> None:
        for i in range(start, start + 12):
            conn.enqueue_cancel(i)

    threads = [
        threading.Thread(target=submit_batch, args=(0,)),
        threading.Thread(target=submit_batch, args=(25,)),
        threading.Thread(target=cancel_batch, args=(100,)),
        threading.Thread(target=cancel_batch, args=(200,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Wait for the writer to drain (poll timeout 0.05s; allow 2s).
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if (
            len(captured["place"]) == 50
            and len(captured["cancel"]) == 24
        ):
            break
        time.sleep(0.02)

    assert len(captured["place"]) == 50
    assert len(captured["cancel"]) == 24
    # No duplicates: each ib_id appears exactly once.
    place_ids = [p[0] for p in captured["place"]]
    assert len(set(place_ids)) == 50

    conn.disconnect_and_stop()


def test_order_status_coerces_decimal_filled_remaining() -> None:
    clock = SimulatedClock(start_ns=42_000_000)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.orderStatus(
        orderId=7,
        status="PartiallyFilled",
        filled=Decimal("50"),
        remaining=Decimal("50"),
        avgFillPrice=150.25,
        permId=0,
        parentId=0,
        lastFillPrice=150.25,
        clientId=1,
        whyHeld="",
        mktCapPrice=0.0,
    )
    fills = conn.poll_fills()
    assert len(fills) == 1
    assert fills[0].cumulative_filled == 50
    assert fills[0].remaining == 50


def test_error_with_zero_req_id_does_not_reach_queue() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.error(reqId=0, errorTime=0, errorCode=504, errorString="not connected")
    assert conn.poll_fills() == []


def test_connect_and_start_rejects_double_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, _ = _build_conn(monkeypatch)
    threading.Thread(
        target=lambda: (time.sleep(0.05), conn.nextValidId(1)),
        daemon=True,
    ).start()
    conn.connect_and_start(ready_timeout_s=2.0)
    with pytest.raises(RuntimeError, match="already connected"):
        conn.connect_and_start(ready_timeout_s=2.0)
    conn.disconnect_and_stop()


def test_disconnect_resets_handshake_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, _ = _build_conn(monkeypatch)
    threading.Thread(
        target=lambda: (time.sleep(0.05), conn.nextValidId(10)),
        daemon=True,
    ).start()
    conn.connect_and_start(ready_timeout_s=2.0)
    assert conn.next_order_id() == 10
    conn.disconnect_and_stop()
    with pytest.raises(RuntimeError, match="nextValidId not received"):
        conn.next_order_id()


def test_order_status_pushes_fill_event_with_clock_ts() -> None:
    clock = SimulatedClock(start_ns=42_000_000)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.orderStatus(
        orderId=7,
        status="Filled",
        filled=100,
        remaining=0,
        avgFillPrice=150.25,
        permId=0,
        parentId=0,
        lastFillPrice=150.25,
        clientId=1,
        whyHeld="",
        mktCapPrice=0.0,
    )
    fills = conn.poll_fills()
    assert len(fills) == 1
    assert fills[0] == IBFillEvent(
        ib_order_id=7,
        status="Filled",
        cumulative_filled=100,
        remaining=0,
        avg_fill_price=150.25,
        timestamp_ns=42_000_000,
    )


def test_connect_fatal_error_326_aborts_handshake() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.error(
        reqId=-1, errorTime=0, errorCode=326,
        errorString="client id already in use",
    )
    assert conn._connect_failed.is_set()
    assert "326" in conn._connect_failed_reason


def test_error_with_negative_req_id_does_not_reach_queue() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.error(reqId=-1, errorTime=0, errorCode=1100, errorString="connectivity lost")
    assert conn.poll_fills() == []


def test_error_with_order_req_id_forwards_to_queue() -> None:
    clock = SimulatedClock(start_ns=99)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    conn.error(reqId=7, errorTime=0, errorCode=201, errorString="rejected")
    fills = conn.poll_fills()
    assert len(fills) == 1
    assert fills[0].error_code == 201
    assert fills[0].error_msg == "rejected"
    assert fills[0].ib_order_id == 7
    assert fills[0].timestamp_ns == 99


def test_poll_fills_drains_non_blockingly() -> None:
    clock = SimulatedClock(start_ns=0)
    conn = IBGatewayConnection(
        host="127.0.0.1", port=4002, client_id=1, clock=clock,
    )
    for i in range(3):
        conn._fill_queue.put(IBFillEvent(
            ib_order_id=i, status="Filled",
            cumulative_filled=10, remaining=0,
            avg_fill_price=100.0, timestamp_ns=i,
        ))
    out = conn.poll_fills()
    assert [f.ib_order_id for f in out] == [0, 1, 2]
    # Subsequent call returns empty without blocking.
    assert conn.poll_fills() == []
