"""Tests for RTH-open/close session anchoring."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from feelies.core.session_clock import rth_close_ns, rth_open_ns

_ET = ZoneInfo("America/New_York")
_NS = 1_000_000_000


def _et_ns(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> int:
    dt = datetime(y, m, d, hh, mm, ss, tzinfo=_ET)
    return int(dt.timestamp()) * _NS


def test_anchors_to_0930_et_same_day() -> None:
    # An event at 10:15:07 ET on 2026-03-26 anchors to 09:30:00 ET that day.
    ev = _et_ns(2026, 3, 26, 10, 15, 7) + 123_456  # add sub-second ns
    expected = _et_ns(2026, 3, 26, 9, 30, 0)
    assert rth_open_ns(ev) == expected


def test_is_integer_exact_no_ns_rounding() -> None:
    ev = _et_ns(2026, 3, 26, 9, 30, 5) + 999_999_999
    out = rth_open_ns(ev)
    # Result is a whole-second multiple (09:30:00) → divisible by 1e9.
    assert out % _NS == 0


def test_dst_correct_across_the_spring_forward() -> None:
    # 2026 US DST begins Sun 2026-03-08. A date after it (EDT, UTC-4) and a
    # date before it (EST, UTC-5) must each anchor to *local* 09:30.
    after = _et_ns(2026, 3, 26, 11, 0, 0)  # EDT
    before = _et_ns(2026, 1, 15, 11, 0, 0)  # EST
    for ev, (y, m, d) in ((after, (2026, 3, 26)), (before, (2026, 1, 15))):
        anchor = rth_open_ns(ev)
        dt = datetime.fromtimestamp(anchor // _NS, tz=_ET)
        assert (dt.year, dt.month, dt.day) == (y, m, d)
        assert dt.timetz().replace(tzinfo=None) == time(9, 30)


def test_pre_open_event_anchors_to_same_day_open() -> None:
    # An 08:00 ET pre-market event anchors forward to 09:30 ET (the open is
    # later than the event; the scheduler skips negative-elapsed ticks).
    ev = _et_ns(2026, 3, 26, 8, 0, 0)
    assert rth_open_ns(ev) == _et_ns(2026, 3, 26, 9, 30, 0)


def test_close_anchors_to_1600_et_same_day() -> None:
    # An intra-session event anchors to 16:00:00 ET that day.
    ev = _et_ns(2026, 3, 26, 14, 0, 0) + 123_456
    assert rth_close_ns(ev) == _et_ns(2026, 3, 26, 16, 0, 0)


def test_close_is_integer_exact_no_ns_rounding() -> None:
    ev = _et_ns(2026, 3, 26, 15, 59, 5) + 999_999_999
    assert rth_close_ns(ev) % _NS == 0


def test_close_dst_correct_across_the_spring_forward() -> None:
    # Local 16:00 on an EDT date and an EST date — offsets differ, the wall
    # time does not.
    after = _et_ns(2026, 3, 26, 11, 0, 0)  # EDT (UTC-4)
    before = _et_ns(2026, 1, 15, 11, 0, 0)  # EST (UTC-5)
    for ev, (y, m, d) in ((after, (2026, 3, 26)), (before, (2026, 1, 15))):
        anchor = rth_close_ns(ev)
        dt = datetime.fromtimestamp(anchor // _NS, tz=_ET)
        assert (dt.year, dt.month, dt.day) == (y, m, d)
        assert dt.timetz().replace(tzinfo=None) == time(16, 0)


def test_close_is_after_open_within_a_session() -> None:
    ev = _et_ns(2026, 3, 26, 12, 0, 0)
    assert rth_close_ns(ev) > rth_open_ns(ev)
