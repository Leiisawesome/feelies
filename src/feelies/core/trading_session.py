"""RTH session bounds and session-flatten window.

TradingSessionBounds and the flatten-window helpers live in core so
kernel can name them without importing the execution package. Calendar
helpers travel with the bounds so core does not import execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000


def session_date_from_ns(timestamp_ns: int) -> date:
    """ET calendar date for a UTC nanosecond timestamp."""
    return datetime.fromtimestamp(
        timestamp_ns / _NS_PER_SECOND,
        _NY_TZ,
    ).date()


def _parse_clock_time(spec: str) -> time:
    parts = spec.split(":")
    if len(parts) == 2:
        h, m = parts
        return time(hour=int(h), minute=int(m))
    if len(parts) == 3:
        h, m, s = parts
        return time(hour=int(h), minute=int(m), second=int(s))
    raise ValueError(f"clock time {spec!r} must be HH:MM or HH:MM:SS")


def et_clock_to_ns(session_date: date, clock_str: str) -> int:
    """Resolve an ET clock-time on ``session_date`` to UTC nanoseconds."""
    t = _parse_clock_time(clock_str)
    local = datetime.combine(session_date, t, tzinfo=_NY_TZ)
    # int() of the whole-second timestamp first, then multiply by
    # _NS_PER_SECOND in pure integer arithmetic — float64 can't exactly
    # represent seconds-since-epoch * 1e9 at nanosecond magnitude, so
    # multiplying before truncating risked losing precision (mirrors
    # core/session_clock.py:rth_open_ns's integer-safe pattern).
    return int(local.timestamp()) * _NS_PER_SECOND


@dataclass(frozen=True, kw_only=True)
class TradingSessionBounds:
    """Per-session RTH open/close anchors in exchange-time nanoseconds."""

    session_date: date
    rth_open_ns: int
    rth_close_ns: int
    is_holiday: bool = False
    is_early_close: bool = False
    no_entry_first_seconds: int = 0
    rth_open_et: str = "09:30"
    rth_close_et: str = "16:00"
    early_close_rth_close_et: str = "13:00"
    market_holiday_dates: frozenset[str] = frozenset()
    early_close_dates: frozenset[str] = frozenset()

    def covers_ns(self, ts_ns: int) -> bool:
        """Whether ``ts_ns`` falls on ``session_date`` in America/New_York."""
        return session_date_from_ns(ts_ns) == self.session_date

    def resolve_for_timestamp(self, ts_ns: int) -> "TradingSessionBounds":
        """Resolve the effective RTH bounds for an event timestamp."""
        session_date = session_date_from_ns(ts_ns)
        if session_date == self.session_date:
            # The common single-session path is already fully resolved.
            return self

        early = self.is_early_close or (session_date.isoformat() in self.early_close_dates)
        holiday = self.is_holiday or (session_date.isoformat() in self.market_holiday_dates)
        close_et = self.early_close_rth_close_et if early else self.rth_close_et
        return TradingSessionBounds(
            session_date=session_date,
            rth_open_ns=et_clock_to_ns(session_date, self.rth_open_et),
            rth_close_ns=et_clock_to_ns(session_date, close_et),
            is_holiday=holiday,
            is_early_close=early,
            no_entry_first_seconds=self.no_entry_first_seconds,
            rth_open_et=self.rth_open_et,
            rth_close_et=self.rth_close_et,
            early_close_rth_close_et=self.early_close_rth_close_et,
            market_holiday_dates=self.market_holiday_dates,
            early_close_dates=self.early_close_dates,
        )

    def no_entry_before_ns(self) -> int:
        """First exchange-time instant when new entries are allowed."""
        return self.rth_open_ns + self.no_entry_first_seconds * _NS_PER_SECOND


def session_flatten_deadline_ns(
    bounds: TradingSessionBounds | None,
    *,
    enabled: bool,
    seconds_before_close: int,
    at_ns: int,
) -> int | None:
    """Exchange-time ns at/after which the session flattens, or ``None``.

    ``None`` when session flatten is disabled or no RTH session is configured.
    The deadline is ``rth_close - seconds_before_close`` so an operator can
    unwind before the closing auction.

    Bounds are resolved for *this timestamp's* NY session date via
    :meth:`TradingSessionBounds.resolve_for_timestamp`, so a multi-day replay
    rebinds the close per replayed day rather than pinning every day to the
    single ``session_date`` the bounds were booted with (which, for a CLI date
    *range*, falls back to the stale ``event_calendar_path`` date and would
    otherwise flag every quote as past-close — see
    ``apply_backtest_session_dates_from_cli``).

    The deadline answers two distinct questions that must never disagree:
    whether to *emit* the end-of-session flatten, and whether to *suppress* new
    entries inside the window.  Those live in different engines, so the
    arithmetic belongs here — beside the bounds it reads — rather than in either
    caller.
    """
    if not enabled or bounds is None:
        return None
    effective = bounds.resolve_for_timestamp(at_ns)
    return effective.rth_close_ns - seconds_before_close * _NS_PER_SECOND


def in_session_flatten_window(
    bounds: TradingSessionBounds | None,
    *,
    enabled: bool,
    seconds_before_close: int,
    at_ns: int,
) -> bool:
    """Whether ``at_ns`` is at or past the session-flatten deadline."""
    deadline = session_flatten_deadline_ns(
        bounds,
        enabled=enabled,
        seconds_before_close=seconds_before_close,
        at_ns=at_ns,
    )
    return deadline is not None and at_ns >= deadline
