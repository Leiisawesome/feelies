"""Backtest execution backend — composes ReplayFeed + BacktestOrderRouter.

Factory function that builds a fully composed ``ExecutionBackend``
for backtest mode.  The orchestrator receives this and runs
identically to live mode (invariant 9).
"""

from __future__ import annotations

from feelies.core.clock import Clock
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import CostModel
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.storage.event_log import EventLog


def build_backtest_backend(
    event_log: EventLog,
    clock: Clock,
    start_sequence: int = 0,
    end_sequence: int | None = None,
    latency_ns: int = 0,
    cost_model: CostModel | None = None,
) -> tuple[ExecutionBackend, BacktestOrderRouter]:
    """Build a backtest ExecutionBackend from an event log.

    Returns ``(backend, router)`` so the caller can wire
    ``router.on_quote()`` to the event bus for price tracking.
    """
    feed = ReplayFeed(
        event_log=event_log,
        clock=clock,
        start_sequence=start_sequence,
        end_sequence=end_sequence,
    )
    router = BacktestOrderRouter(
        clock=clock,
        latency_ns=latency_ns,
        cost_model=cost_model,
    )

    backend = ExecutionBackend(
        market_data=feed,
        order_router=router,
        mode="BACKTEST",
    )
    return backend, router
