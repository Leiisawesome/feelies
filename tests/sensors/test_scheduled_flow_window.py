"""Unit tests for ScheduledFlowWindowSensor (v0.3 §20.4.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.scheduled_flow_window import (
    ScheduledFlowWindowSensor,
    _window_id_hash,
)
from feelies.storage.reference.event_calendar import (
    CalendarWindow,
    EventCalendar,
    WindowKind,
)


def _quote(*, ts_ns: int, symbol: str = "AAPL") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id="q",
        sequence=0,
        symbol=symbol,
        bid=Decimal("100"),
        ask=Decimal("100.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _calendar() -> EventCalendar:
    return EventCalendar(
        session_date=date(2026, 3, 24),
        windows=(
            CalendarWindow(
                window_id="open",
                kind=WindowKind.OPENING_AUCTION,
                symbol=None,
                start_ns=10_000_000_000,
                end_ns=20_000_000_000,
                flow_direction_prior=0.0,
            ),
            CalendarWindow(
                window_id="aapl_drift",
                kind=WindowKind.EARNINGS_DRIFT,
                symbol="AAPL",
                start_ns=15_000_000_000,
                end_ns=18_000_000_000,
                flow_direction_prior=1.0,
            ),
        ),
    )


def test_constructor_rejects_non_calendar() -> None:
    with pytest.raises(TypeError, match="EventCalendar"):
        ScheduledFlowWindowSensor(calendar="not a calendar")  # type: ignore[arg-type]


def test_inactive_emits_zero_tuple() -> None:
    sensor = ScheduledFlowWindowSensor(calendar=_calendar())
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=5_000_000_000), state, params={})
    assert r is not None
    assert isinstance(r.value, tuple)
    active, secs, hash_, dir_ = r.value
    assert active == 0.0
    assert secs == -1.0
    assert hash_ == 0.0
    assert dir_ == 0.0
    assert r.warm is True


def test_active_universe_window() -> None:
    sensor = ScheduledFlowWindowSensor(calendar=_calendar())
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=12_000_000_000), state, params={})
    assert r is not None
    active, secs, hash_, dir_ = r.value
    assert active == 1.0
    assert secs == pytest.approx((20_000_000_000 - 12_000_000_000) / 1e9)
    assert hash_ == float(_window_id_hash("open"))
    assert dir_ == 0.0


def test_symbol_specific_window_filters_by_symbol() -> None:
    """Earnings window is AAPL-only; MSFT does not see it."""
    sensor = ScheduledFlowWindowSensor(calendar=_calendar())
    state = sensor.initial_state()
    r_aapl = sensor.update(_quote(ts_ns=16_000_000_000, symbol="AAPL"), state, params={})
    r_msft = sensor.update(_quote(ts_ns=16_000_000_000, symbol="MSFT"), state, params={})
    assert r_aapl is not None and r_msft is not None
    # AAPL: earnings_drift wins (ends at 18s; opening ends at 20s).
    _a, _s, hash_aapl, dir_aapl = r_aapl.value
    assert hash_aapl == float(_window_id_hash("aapl_drift"))
    assert dir_aapl == 1.0
    # MSFT: only the universe-wide opening window matches.
    _a, _s, hash_msft, dir_msft = r_msft.value
    assert hash_msft == float(_window_id_hash("open"))
    assert dir_msft == 0.0


def test_chooses_earliest_ending_window_on_overlap() -> None:
    sensor = ScheduledFlowWindowSensor(calendar=_calendar())
    state = sensor.initial_state()
    # At ts=16s both windows are active for AAPL; earnings_drift ends
    # at 18s, opening at 20s — earnings_drift wins.
    r = sensor.update(_quote(ts_ns=16_000_000_000, symbol="AAPL"), state, params={})
    assert r is not None
    _a, _s, hash_, _d = r.value
    assert hash_ == float(_window_id_hash("aapl_drift"))


def test_trade_events_also_classified() -> None:
    sensor = ScheduledFlowWindowSensor(calendar=_calendar())
    state = sensor.initial_state()
    trade = Trade(
        timestamp_ns=12_000_000_000,
        correlation_id="t",
        sequence=0,
        symbol="AAPL",
        price=Decimal("100"),
        size=100,
        exchange_timestamp_ns=12_000_000_000,
    )
    r = sensor.update(trade, state, params={})
    assert r is not None
    active, _s, _h, _d = r.value
    assert active == 1.0


def test_window_id_hash_is_deterministic_and_salt_free() -> None:
    """SHA-256 prefix → independent of PYTHONHASHSEED."""
    h1 = _window_id_hash("open")
    h2 = _window_id_hash("open")
    assert h1 == h2
    # Concrete locked value — protects against accidental algorithm
    # change that would silently shift downstream signal bytes.
    assert h1 == 591985048
