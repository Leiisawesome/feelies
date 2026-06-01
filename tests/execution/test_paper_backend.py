"""Smoke tests for :func:`feelies.execution.paper_backend.build_paper_backend`.

The factory does not start the WS thread or connect to IB Gateway —
it just composes the objects.  These tests verify the composition
shape; the lifecycle (start / connect / stop / disconnect) lives in
``scripts/run_paper.py`` and is exercised end-to-end by the
``@pytest.mark.functional`` smoke (not run here).
"""

from __future__ import annotations

from feelies.broker.ib import IBGatewayConnection, IBOrderRouter
from feelies.core.clock import SimulatedClock
from feelies.execution.backend import ExecutionMode
from feelies.execution.paper_backend import build_paper_backend
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


def test_build_paper_backend_returns_composed_bundle() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    backend, live_feed, ib_conn = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL", "MSFT"),
        clock=clock,
        normalizer=normalizer,
    )
    assert backend.mode == ExecutionMode.PAPER
    assert isinstance(live_feed, MassiveLiveFeed)
    assert isinstance(ib_conn, IBGatewayConnection)
    assert isinstance(backend.order_router, IBOrderRouter)
    assert backend.market_data is live_feed
    # Normalizer is shared (no fresh construction inside the factory).
    assert live_feed._normalizer is normalizer


def test_build_paper_backend_does_not_start_or_connect() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    _, live_feed, ib_conn = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL",),
        clock=clock,
        normalizer=normalizer,
    )
    # Live feed background thread is unset (start() not called).
    assert live_feed._thread is None
    # IB connection threads not spawned (connect_and_start() not called).
    assert ib_conn._msg_thread is None
    assert ib_conn._writer_thread is None
    # No handshake — next_order_id() must raise.
    import pytest
    with pytest.raises(RuntimeError, match="nextValidId not received"):
        ib_conn.next_order_id()


def test_build_paper_backend_honours_custom_host_port_client_id() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    _, _, ib_conn = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL",),
        clock=clock,
        normalizer=normalizer,
        ib_host="10.0.0.5",
        ib_port=4003,
        ib_client_id=42,
        massive_ws_url="wss://test.example/stocks",
    )
    assert ib_conn._host == "10.0.0.5"
    assert ib_conn._port == 4003
    assert ib_conn._client_id == 42
