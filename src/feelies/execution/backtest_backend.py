"""Backtest execution backend — composes ReplayFeed + order router.

Factory functions that build a fully composed ``ExecutionBackend``
for backtest mode.  The orchestrator receives this and runs
identically to live mode (invariant 9).

Two router variants:
  - ``build_backtest_backend``: mid-price market fills (v1 default)
  - ``build_passive_limit_backend``: passive limit order queue model
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.clock import Clock
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import CostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.storage.event_log import EventLog


def build_backtest_backend(
    event_log: EventLog,
    clock: Clock,
    start_sequence: int = 0,
    end_sequence: int | None = None,
    latency_ns: int = 0,
    cost_model: CostModel | None = None,
    market_impact_factor: float = 0.5,
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
        market_impact_factor=market_impact_factor,
    )

    backend = ExecutionBackend(
        market_data=feed,
        order_router=router,
        mode="BACKTEST",
    )
    return backend, router


def build_passive_limit_backend(
    event_log: EventLog,
    clock: Clock,
    start_sequence: int = 0,
    end_sequence: int | None = None,
    latency_ns: int = 0,
    cost_model: CostModel | None = None,
    *,
    fill_delay_ticks: int = 3,
    max_resting_ticks: int = 50,
    queue_position_shares: int = 0,
    cancel_fee_per_share: Decimal = Decimal("0.0"),
) -> tuple[ExecutionBackend, PassiveLimitOrderRouter]:
    """Build a backtest backend with passive limit order fill model.

    Returns ``(backend, router)`` so the caller can wire
    ``router.on_quote()`` to the event bus for price tracking.

    When ``queue_position_shares > 0`` (or callers later set per-order
    thresholds via ``router.set_queue_ahead()``), level fills require
    accumulated trade volume.  In that case the caller MUST also wire
    ``router.on_trade()`` to the trade event stream or orders will
    never fill by queue drain.  Check ``router.requires_trade_feed``
    to detect this requirement at wiring time.
    """
    feed = ReplayFeed(
        event_log=event_log,
        clock=clock,
        start_sequence=start_sequence,
        end_sequence=end_sequence,
    )
    router = PassiveLimitOrderRouter(
        clock=clock,
        latency_ns=latency_ns,
        cost_model=cost_model,
        fill_delay_ticks=fill_delay_ticks,
        max_resting_ticks=max_resting_ticks,
        queue_position_shares=queue_position_shares,
        cancel_fee_per_share=cancel_fee_per_share,
    )

    backend = ExecutionBackend(
        market_data=feed,
        order_router=router,
        mode="BACKTEST",
    )
    return backend, router
