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

import sys
from collections.abc import Sequence
from types import ModuleType

from feelies.core.clock import Clock
from feelies.execution.backend import ExecutionBackend, ExecutionMode, OrderRouter
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


def _ib_module() -> ModuleType:
    """IB types without a static ``feelies.broker`` import (G40).

    Composition-root callers inject the connection and router. Unit
    tests that still construct via this factory import ``feelies.broker.ib``
    first; the classes are then taken from ``sys.modules``.
    """
    loaded = sys.modules.get("feelies.broker.ib")
    if loaded is None:
        raise TypeError(
            "build_paper_backend requires ib_connection and order_router "
            "from the composition root"
        )
    return loaded


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
    ib_connection: object | None = None,
    order_router: OrderRouter | None = None,
) -> tuple[ExecutionBackend, MassiveLiveFeed, object]:
    """Compose a PAPER ``ExecutionBackend`` with a Massive feed + IB router.

    Does NOT call ``MassiveLiveFeed.start()`` or
    ``IBGatewayConnection.connect_and_start()``. The entry script owns
    the connect-then-start ordering. Bootstrap injects the IB handle;
    ``ib_host`` / ``ib_port`` / ``ib_client_id`` remain for callers that
    still construct through this factory.
    """
    live_feed = MassiveLiveFeed(
        api_key=massive_api_key,
        symbols=symbols,
        normalizer=normalizer,
        clock=clock,
        ws_url=massive_ws_url,
    )
    if ib_connection is None:
        ib_connection = getattr(_ib_module(), "IBGatewayConnection")(
            host=ib_host,
            port=ib_port,
            client_id=ib_client_id,
            clock=clock,
        )
    if order_router is None:
        order_router = getattr(_ib_module(), "IBOrderRouter")(
            connection=ib_connection,
            clock=clock,
        )
    backend = ExecutionBackend(
        market_data=live_feed,
        order_router=order_router,
        mode=ExecutionMode.PAPER,
    )
    return backend, live_feed, ib_connection
