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

from feelies.core.clock import Clock
from feelies.execution.backend import (
    ExecutionBackend,
    ExecutionMode,
    MarketDataSource,
    OrderRouter,
)


def build_paper_backend(
    *,
    massive_api_key: str,
    symbols: Sequence[str],
    clock: Clock,
    normalizer: object,
    ib_connection: object,
    order_router: OrderRouter,
    live_feed: MarketDataSource,
    ib_host: str = "127.0.0.1",
    ib_port: int = 4002,
    ib_client_id: int = 1,
    massive_ws_url: str = "wss://socket.massive.com/stocks",
) -> tuple[ExecutionBackend, MarketDataSource, object]:
    """Compose a PAPER ``ExecutionBackend`` with an injected feed + IB router.

    Does NOT call ``MassiveLiveFeed.start()`` or
    ``IBGatewayConnection.connect_and_start()``. The entry script owns
    the connect-then-start ordering. Handles are required: bootstrap
    constructs the feed and IB stack and injects them. Construction
    kwargs remain so composition-root tests can pin forwarded config
    fields; they are not used to build objects here.
    """
    del massive_api_key, symbols, clock, normalizer
    del ib_host, ib_port, ib_client_id, massive_ws_url
    backend = ExecutionBackend(
        market_data=live_feed,
        order_router=order_router,
        mode=ExecutionMode.PAPER,
    )
    return backend, live_feed, ib_connection
