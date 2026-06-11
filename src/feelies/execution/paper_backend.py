"""Paper-mode :class:`ExecutionBackend` factory.

Composes the Massive WS live feed (market data) with the IB Gateway
router (order execution) into a single ``ExecutionBackend(mode=PAPER)``.
The orchestrator interacts only with the backend; the live-feed and
IB-connection handles are returned separately so the entry script
(:mod:`scripts.run_paper`) can drive their lifecycle.

The normalizer is **shared**: ``MassiveLiveFeed`` uses it to decode WS
frames, and the orchestrator uses the same instance for
:class:`DataHealth` gating.  Bootstrap is the canonical construction
site and threads one instance through both consumers.
"""

from __future__ import annotations

from collections.abc import Sequence

from feelies.broker.ib import IBGatewayConnection, IBOrderRouter
from feelies.core.clock import Clock
from feelies.execution.backend import ExecutionBackend, ExecutionMode
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


def build_paper_backend(
    *,
    massive_api_key: str,
    symbols: Sequence[str],
    clock: Clock,
    normalizer: MassiveNormalizer,
    ib_host: str = "127.0.0.1",
    ib_port: int = 4002,
    ib_client_id: int = 1,
    massive_ws_url: str = "wss://socket.massive.com/stocks",
) -> tuple[ExecutionBackend, MassiveLiveFeed, IBGatewayConnection]:
    """Compose a PAPER ``ExecutionBackend`` with a Massive feed + IB router.

    Does NOT call ``MassiveLiveFeed.start()`` or
    ``IBGatewayConnection.connect_and_start()`` — the entry script
    owns the connect-then-start ordering (see plan §9).
    """
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
    backend = ExecutionBackend(
        market_data=live_feed,
        order_router=router,
        mode=ExecutionMode.PAPER,
    )
    return backend, live_feed, ib_conn
