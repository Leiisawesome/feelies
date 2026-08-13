"""RTH session bounds and entry-suppression helpers."""

from __future__ import annotations

from datetime import date


from feelies.core.events import Side
from feelies.execution.moc_session import et_clock_to_ns
from feelies.execution.trading_session import (
    MARKET_HOLIDAY,
    RTH_ENTRY_SUPPRESSED,
    build_trading_session_from_platform,
    in_session_flatten_window,
    order_opens_or_increases,
    resolve_trading_session_bounds,
    session_flatten_deadline_ns,
    should_suppress_entry,
)

_NS_PER_SECOND = 1_000_000_000


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


# ── Session-flatten deadline ────────────────────────────────────────────
# One deadline answers two questions in two different engines: whether to emit
# the end-of-session flatten, and whether to suppress new entries inside the
# window.  They must never disagree, so the arithmetic lives here.


def test_flatten_deadline_precedes_close_by_the_buffer() -> None:
    bounds = resolve_trading_session_bounds(date(2026, 1, 15))
    deadline = session_flatten_deadline_ns(
        bounds, enabled=True, seconds_before_close=300, at_ns=bounds.rth_open_ns
    )
    assert deadline == bounds.rth_close_ns - 300 * _NS_PER_SECOND


def test_flatten_deadline_is_none_when_disabled_or_unbounded() -> None:
    bounds = resolve_trading_session_bounds(date(2026, 1, 15))
    assert (
        session_flatten_deadline_ns(
            bounds, enabled=False, seconds_before_close=300, at_ns=bounds.rth_open_ns
        )
        is None
    )
    assert (
        session_flatten_deadline_ns(
            None, enabled=True, seconds_before_close=300, at_ns=bounds.rth_open_ns
        )
        is None
    )


def test_flatten_window_opens_at_the_deadline_not_before() -> None:
    bounds = resolve_trading_session_bounds(date(2026, 1, 15))
    deadline = bounds.rth_close_ns - 300 * _NS_PER_SECOND
    assert not in_session_flatten_window(
        bounds, enabled=True, seconds_before_close=300, at_ns=deadline - 1
    )
    assert in_session_flatten_window(
        bounds, enabled=True, seconds_before_close=300, at_ns=deadline
    )
    assert in_session_flatten_window(
        bounds, enabled=True, seconds_before_close=300, at_ns=bounds.rth_close_ns
    )


def test_flatten_window_disabled_is_never_open() -> None:
    bounds = resolve_trading_session_bounds(date(2026, 1, 15))
    assert not in_session_flatten_window(
        bounds,
        enabled=False,
        seconds_before_close=300,
        at_ns=bounds.rth_close_ns,
    )


def test_resolve_same_session_reuses_precomputed_bounds() -> None:
    session_date = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(session_date)

    resolved = bounds.resolve_for_timestamp(et_clock_to_ns(session_date, "12:00"))

    assert resolved is bounds


def test_flatten_deadline_rebinds_per_replayed_day() -> None:
    """A multi-day replay must not pin every day to the booted session date.

    Bounds are booted once with a single ``session_date`` (for a CLI date range
    that falls back to the calendar path's date).  Resolving per timestamp is
    what keeps day 2 from being treated as entirely past-close.
    """
    day1 = date(2026, 1, 15)
    day2 = date(2026, 1, 16)
    bounds = resolve_trading_session_bounds(day1)
    day2_open = et_clock_to_ns(day2, "09:30")

    deadline = session_flatten_deadline_ns(
        bounds, enabled=True, seconds_before_close=300, at_ns=day2_open
    )
    assert deadline is not None
    # Deadline tracks day 2's close, not day 1's.
    assert deadline == et_clock_to_ns(day2, "16:00") - 300 * _NS_PER_SECOND
    assert deadline > bounds.rth_close_ns
    # And day 2's open is not inside the window.
    assert not in_session_flatten_window(
        bounds, enabled=True, seconds_before_close=300, at_ns=day2_open
    )


def test_flatten_deadline_follows_an_early_close() -> None:
    half_day = date(2026, 11, 27)
    bounds = resolve_trading_session_bounds(
        date(2026, 11, 26),
        early_close_dates=(half_day.isoformat(),),
    )
    deadline = session_flatten_deadline_ns(
        bounds,
        enabled=True,
        seconds_before_close=300,
        at_ns=et_clock_to_ns(half_day, "12:00"),
    )
    assert deadline == et_clock_to_ns(half_day, "13:00") - 300 * _NS_PER_SECOND
