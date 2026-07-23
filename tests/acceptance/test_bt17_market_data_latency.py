"""Test market-data propagation latency independently of fill latency."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import (
    DEFAULT_BACKTEST_FILL_LATENCY_NS,
    DEFAULT_MARKET_DATA_LATENCY_NS,
    PlatformConfig,
    latency_stress_ns,
)
from feelies.ingestion.replay_feed import ReplayFeed, market_data_visible_at_ns
from feelies.storage.memory_event_log import InMemoryEventLog


def _quote(exchange_ts_ns: int, bid: str) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"AAPL:{exchange_ts_ns}:0",
        sequence=0,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal("100.05"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )


def test_locked_latency_defaults_on_platform_config() -> None:
    cfg = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[Path("dummy.alpha.yaml")],
    )
    assert cfg.backtest_fill_latency_ns == DEFAULT_BACKTEST_FILL_LATENCY_NS
    assert cfg.market_data_latency_ns == DEFAULT_MARKET_DATA_LATENCY_NS
    assert DEFAULT_BACKTEST_FILL_LATENCY_NS == 50_000_000
    assert DEFAULT_MARKET_DATA_LATENCY_NS == 20_000_000


def test_latency_stress_scales_both_legs() -> None:
    fill, md = latency_stress_ns(50_000_000, 20_000_000, multiplier=2)
    assert fill == 100_000_000
    assert md == 40_000_000


def test_pipeline_clock_at_visibility_not_exchange_time() -> None:
    """Decision time must be exchange_ts + md_latency (no feed lookahead)."""
    t_early = 1_000_000_000
    t_late = 10_000_000_000
    md_latency = 20_000_000

    log = InMemoryEventLog()
    log.append(_quote(t_early, "100.00"))
    log.append(_quote(t_late, "200.00"))

    clock = SimulatedClock(start_ns=0)
    feed = ReplayFeed(log, clock=clock, market_data_latency_ns=md_latency)
    events = list(feed.events())

    assert len(events) == 2
    assert clock.now_ns() == market_data_visible_at_ns(t_late, md_latency)
    assert clock.now_ns() > t_late


def test_first_quote_visibility_before_later_exchange_print() -> None:
    """After the first quote, clock must not reach a later quote's visibility."""
    t1 = 500_000_000
    t2 = 600_000_000
    md_latency = 50_000_000

    log = InMemoryEventLog()
    log.append(_quote(t1, "100.00"))
    log.append(_quote(t2, "200.00"))

    clock = SimulatedClock(start_ns=0)
    feed = ReplayFeed(log, clock=clock, market_data_latency_ns=md_latency)
    it = iter(feed.events())
    next(it)
    after_first = clock.now_ns()
    assert after_first == market_data_visible_at_ns(t1, md_latency)
    assert after_first < market_data_visible_at_ns(t2, md_latency)
