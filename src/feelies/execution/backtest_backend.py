"""Backtest execution backend — composes ReplayFeed + order router.

Factory functions that build a fully composed ``ExecutionBackend``
for backtest mode.  The orchestrator receives this and runs
identically to live mode (invariant 9).

Two router variants:
  - ``build_backtest_backend``: mid-price market fills (v1 default)
  - ``build_passive_limit_backend``: passive limit order queue model
"""

from __future__ import annotations

import logging
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import CostModel
from feelies.execution.moc_session import MocSessionBounds
from feelies.execution.trading_session import TradingSessionBounds
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.storage.event_log import EventLog

_logger = logging.getLogger(__name__)


def _warn_on_zero_latency(
    *,
    latency_ns: int,
    market_data_latency_ns: int,
    builder: str,
) -> None:
    """Warn when a backtest omits feed or submission latency.

    A backtest with ``latency_ns == 0`` lets an order fill against the very
    quote that triggered it (no submission delay), and
    ``market_data_latency_ns == 0`` lets the strategy act on a quote at its
    exchange timestamp with zero feed-propagation delay.  Both are optimistic
    relative to live and silently inflate PnL.  Production paths set non-zero
    platform defaults; this warning catches ad-hoc / test wiring that relies
    on the (optimistic) zero default.
    """
    zeroed = []
    if latency_ns <= 0:
        zeroed.append("latency_ns")
    if market_data_latency_ns <= 0:
        zeroed.append("market_data_latency_ns")
    if zeroed:
        _logger.warning(
            "%s built with zero %s — backtest fills will be optimistic "
            "(no submission / feed-propagation delay). Set a non-zero "
            "latency for live-like realism (Inv-12).",
            builder,
            " and ".join(zeroed),
        )


def build_backtest_backend(
    event_log: EventLog,
    clock: Clock,
    *,
    cost_model: CostModel,
    start_sequence: int = 0,
    end_sequence: int | None = None,
    latency_ns: int = 0,
    market_impact_factor: float = 0.5,
    max_impact_half_spreads: float = 10.0,
    stop_slippage_half_spreads: float = 2.0,
    within_l1_impact_factor: float = 0.0,
    permanent_impact_coefficient: float = 0.0,
    stop_depth_depletion_factor: float = 1.0,
    max_resting_ticks: int = 50,
    market_data_latency_ns: int = 0,
    moc_bounds: MocSessionBounds | None = None,
    moc_penalty_bps: float = 0.0,
    trading_session_bounds: TradingSessionBounds | None = None,
) -> tuple[ExecutionBackend, BacktestOrderRouter]:
    """Build a backtest ExecutionBackend from an event log.

    Returns ``(backend, router)`` so the caller can wire
    ``router.on_quote()`` to the event bus for price tracking.

    ``max_resting_ticks`` caps how many per-symbol NBBO updates a deferred
    MARKET fill (when ``latency_ns > 0``) may wait while exchange time remains
    before the latency deadline — same fail-safe as
    ``build_passive_limit_backend(..., max_resting_ticks=...)``.
    """
    _warn_on_zero_latency(
        latency_ns=latency_ns,
        market_data_latency_ns=market_data_latency_ns,
        builder="build_backtest_backend",
    )
    feed = ReplayFeed(
        event_log=event_log,
        clock=clock,
        start_sequence=start_sequence,
        end_sequence=end_sequence,
        market_data_latency_ns=market_data_latency_ns,
    )
    router = BacktestOrderRouter(
        clock=clock,
        latency_ns=latency_ns,
        cost_model=cost_model,
        market_impact_factor=market_impact_factor,
        max_impact_half_spreads=max_impact_half_spreads,
        stop_slippage_half_spreads=stop_slippage_half_spreads,
        within_l1_impact_factor=within_l1_impact_factor,
        permanent_impact_coefficient=permanent_impact_coefficient,
        stop_depth_depletion_factor=stop_depth_depletion_factor,
        max_resting_ticks=max_resting_ticks,
        moc_bounds=moc_bounds,
        moc_penalty_bps=moc_penalty_bps,
        trading_session_bounds=trading_session_bounds,
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
    *,
    cost_model: CostModel,
    start_sequence: int = 0,
    end_sequence: int | None = None,
    latency_ns: int = 0,
    fill_delay_ticks: int = 3,
    max_resting_ticks: int = 50,
    queue_position_shares: int = 0,
    cancel_fee_per_share: Decimal = Decimal("0.0"),
    market_impact_factor: float = 0.5,
    max_impact_half_spreads: float = 10.0,
    stop_slippage_half_spreads: float = 2.0,
    within_l1_impact_factor: float = 0.0,
    permanent_impact_coefficient: float = 0.0,
    stop_depth_depletion_factor: float = 1.0,
    through_fill_size_cap_enabled: bool = False,
    require_trade_for_level_fill: bool = False,
    fill_hazard_max: Decimal | float = Decimal("0.5"),
    market_data_latency_ns: int = 0,
    moc_bounds: MocSessionBounds | None = None,
    moc_penalty_bps: float = 0.0,
    trading_session_bounds: TradingSessionBounds | None = None,
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

    ``market_impact_factor`` scales MARKET / marketable-limit aggressive
    walk-the-book impact identically to ``build_backtest_backend``.
    """
    _warn_on_zero_latency(
        latency_ns=latency_ns,
        market_data_latency_ns=market_data_latency_ns,
        builder="build_passive_limit_backend",
    )
    feed = ReplayFeed(
        event_log=event_log,
        clock=clock,
        start_sequence=start_sequence,
        end_sequence=end_sequence,
        market_data_latency_ns=market_data_latency_ns,
    )
    router = PassiveLimitOrderRouter(
        clock=clock,
        latency_ns=latency_ns,
        market_impact_factor=Decimal(str(market_impact_factor)),
        max_impact_half_spreads=Decimal(str(max_impact_half_spreads)),
        cost_model=cost_model,
        fill_delay_ticks=fill_delay_ticks,
        max_resting_ticks=max_resting_ticks,
        queue_position_shares=queue_position_shares,
        cancel_fee_per_share=cancel_fee_per_share,
        fill_hazard_max=fill_hazard_max,
        stop_slippage_half_spreads=Decimal(str(stop_slippage_half_spreads)),
        within_l1_impact_factor=Decimal(str(within_l1_impact_factor)),
        permanent_impact_coefficient=Decimal(str(permanent_impact_coefficient)),
        stop_depth_depletion_factor=Decimal(str(stop_depth_depletion_factor)),
        through_fill_size_cap_enabled=through_fill_size_cap_enabled,
        require_trade_for_level_fill=require_trade_for_level_fill,
        moc_bounds=moc_bounds,
        moc_penalty_bps=Decimal(str(moc_penalty_bps)),
        trading_session_bounds=trading_session_bounds,
    )

    backend = ExecutionBackend(
        market_data=feed,
        order_router=router,
        mode="BACKTEST",
    )
    return backend, router
