"""BT-16: RTH session bounds and entry-suppression helpers."""

from __future__ import annotations

from datetime import date

import pytest

from feelies.core.events import OrderRequest, OrderType, Side
from feelies.execution.moc_session import et_clock_to_ns
from feelies.execution.trading_session import (
    MARKET_HOLIDAY,
    RTH_ENTRY_SUPPRESSED,
    build_trading_session_from_platform,
    order_opens_or_increases,
    resolve_trading_session_bounds,
    should_suppress_entry,
)


def test_regular_rth_window() -> None:
    d = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(d)
    open_ns = bounds.rth_open_ns
    close_ns = bounds.rth_close_ns
    assert open_ns < close_ns
    assert should_suppress_entry(open_ns - 1, bounds, True) == (
        True,
        RTH_ENTRY_SUPPRESSED,
    )
    assert should_suppress_entry(open_ns, bounds, True) == (False, "")
    assert should_suppress_entry(close_ns, bounds, True) == (
        True,
        RTH_ENTRY_SUPPRESSED,
    )
    assert should_suppress_entry(close_ns - 1, bounds, True) == (False, "")


def test_early_close_shortens_rth() -> None:
    d = date(2026, 11, 27)
    reg = resolve_trading_session_bounds(d)
    early = resolve_trading_session_bounds(d, early_close=True)
    assert early.rth_close_ns < reg.rth_close_ns


def test_holiday_suppresses_entries() -> None:
    d = date(2026, 1, 1)
    bounds = resolve_trading_session_bounds(d, is_holiday=True)
    noon = et_clock_to_ns(d, "12:00")
    assert should_suppress_entry(noon, bounds, True) == (True, MARKET_HOLIDAY)


def test_exit_never_suppressed() -> None:
    d = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(d)
    after_close = et_clock_to_ns(d, "16:30")
    assert should_suppress_entry(after_close, bounds, False) == (False, "")


def test_order_opens_or_increases_long_and_exit() -> None:
    assert order_opens_or_increases(0, Side.BUY, 10) is True
    assert order_opens_or_increases(100, Side.SELL, 40) is False
    assert order_opens_or_increases(100, Side.SELL, 100) is False


def test_should_suppress_entry_uses_timestamp_date_for_multi_day_runs() -> None:
    stale_bounds = resolve_trading_session_bounds(
        date(2026, 3, 26),
        early_close_dates=("2026-05-27",),
        market_holiday_dates=(),
    )
    ts_ns = et_clock_to_ns(date(2026, 5, 27), "10:00")

    assert should_suppress_entry(ts_ns, stale_bounds, True) == (False, "")


def test_build_from_platform_disabled() -> None:
    assert (
        build_trading_session_from_platform(
            rth_session_gating_enabled=False,
            rth_session_date="2026-01-15",
            event_calendar_path=None,
            rth_open_et="09:30",
            rth_close_et="16:00",
            early_close_dates=(),
            early_close_rth_close_et="13:00",
            market_holiday_dates=(),
            no_entry_first_seconds=0,
        )
        is None
    )


def test_no_entry_first_seconds() -> None:
    d = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(d, no_entry_first_seconds=300)
    assert should_suppress_entry(bounds.rth_open_ns, bounds, True) == (
        True,
        RTH_ENTRY_SUPPRESSED,
    )
    assert should_suppress_entry(bounds.no_entry_before_ns(), bounds, True) == (
        False,
        "",
    )
