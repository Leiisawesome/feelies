"""Smoke tests for :func:`feelies.execution.paper_backend.build_paper_backend`.

The factory does not start the WS thread or connect to IB Gateway —
it just composes injected objects.  These tests verify the composition
shape; construction lives at the composition root. The lifecycle
(start / connect / stop / disconnect) lives in ``scripts/run_paper.py``
and is exercised end-to-end by the ``@pytest.mark.functional`` smoke
(not run here).
"""

from __future__ import annotations

from collections.abc import Sequence

from feelies.broker.ib import IBGatewayConnection, IBOrderRouter
from feelies.core.clock import SimulatedClock
from feelies.execution.backend import ExecutionMode
from feelies.execution.paper_backend import build_paper_backend
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


def _handles(
    clock: SimulatedClock,
    normalizer: MassiveNormalizer,
    *,
    symbols: Sequence[str] = ("AAPL",),
    massive_api_key: str = "dummy",
    ib_host: str = "127.0.0.1",
    ib_port: int = 4002,
    ib_client_id: int = 1,
    massive_ws_url: str = "wss://socket.massive.com/stocks",
) -> tuple[MassiveLiveFeed, IBGatewayConnection, IBOrderRouter]:
    live_feed = MassiveLiveFeed(
        api_key=massive_api_key,
        symbols=symbols,
        normalizer=normalizer,
        clock=clock,
        ws_url=massive_ws_url,
    )
    ib_conn = IBGatewayConnection(
        host=ib_host,
        port=ib_port,
        client_id=ib_client_id,
        clock=clock,
    )
    router = IBOrderRouter(connection=ib_conn, clock=clock)
    return live_feed, ib_conn, router


def test_build_paper_backend_returns_composed_bundle() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    live_feed, ib_conn, router = _handles(
        clock, normalizer, symbols=("AAPL", "MSFT")
    )
    backend, out_feed, out_ib = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL", "MSFT"),
        clock=clock,
        normalizer=normalizer,
        ib_connection=ib_conn,
        order_router=router,
        live_feed=live_feed,
    )
    assert backend.mode == ExecutionMode.PAPER
    assert isinstance(out_feed, MassiveLiveFeed)
    assert isinstance(out_ib, IBGatewayConnection)
    assert isinstance(backend.order_router, IBOrderRouter)
    assert backend.market_data is live_feed
    assert out_feed is live_feed
    assert out_ib is ib_conn
    # Normalizer is shared (no fresh construction inside the factory).
    assert live_feed._normalizer is normalizer


def test_build_paper_backend_does_not_start_or_connect() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    live_feed, ib_conn, router = _handles(clock, normalizer)
    _, out_feed, out_ib = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL",),
        clock=clock,
        normalizer=normalizer,
        ib_connection=ib_conn,
        order_router=router,
        live_feed=live_feed,
    )
    # Live feed background thread is unset (start() not called).
    assert out_feed._thread is None
    # IB connection threads not spawned (connect_and_start() not called).
    assert out_ib._msg_thread is None
    assert out_ib._writer_thread is None
    # No handshake — next_order_id() must raise.
    import pytest

    with pytest.raises(RuntimeError, match="nextValidId not received"):
        out_ib.next_order_id()


def test_build_paper_backend_returns_injected_handles() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock=clock)
    live_feed, ib_conn, router = _handles(
        clock,
        normalizer,
        ib_host="10.0.0.5",
        ib_port=4003,
        ib_client_id=42,
        massive_ws_url="wss://test.example/stocks",
    )
    backend, out_feed, out_ib = build_paper_backend(
        massive_api_key="dummy",
        symbols=("AAPL",),
        clock=clock,
        normalizer=normalizer,
        ib_host="10.0.0.5",
        ib_port=4003,
        ib_client_id=42,
        massive_ws_url="wss://test.example/stocks",
        ib_connection=ib_conn,
        order_router=router,
        live_feed=live_feed,
    )
    assert out_feed is live_feed
    assert out_ib is ib_conn
    assert backend.order_router is router
    assert out_ib._host == "10.0.0.5"
    assert out_ib._port == 4003
    assert out_ib._client_id == 42
