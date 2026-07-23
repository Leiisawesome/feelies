"""MOC session bounds for backtest closing-auction modeling.

Resolves IB's MOC submission cutoff (15:50 ET regular, 12:50 ET on
NYSE early-close half-days) and the official close print time (16:00 /
13:00 ET) to integer event-time nanoseconds anchored on a session date.
All conversions use ``ZoneInfo("America/New_York")`` for determinism
(Inv-5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000
_CALENDAR_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.ya?ml$")


@dataclass(frozen=True, kw_only=True)
class MocSessionBounds:
    """Per-session MOC cutoff and official-close event-time anchors."""

    session_date: date
    moc_cutoff_ns: int
    official_close_ns: int

    def covers_ns(self, ts_ns: int) -> bool:
        """Whether ``ts_ns`` falls on ``session_date`` in NY tz.

        Used by :class:`MocFillController` to refuse cross-day submits
        and ignore cross-day quotes — the configured cutoff/close are
        only valid anchors for the configured calendar date.
        """
        return session_date_from_ns(ts_ns) == self.session_date


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


def resolve_moc_session_bounds(
    session_date: date,
    *,
    moc_cutoff_et: str = "15:50",
    official_close_et: str = "16:00",
    early_close: bool = False,
    early_close_moc_cutoff_et: str = "12:50",
    early_close_official_close_et: str = "13:00",
) -> MocSessionBounds:
    """Build cutoff/close bounds for a single RTH session date."""
    if early_close:
        return MocSessionBounds(
            session_date=session_date,
            moc_cutoff_ns=et_clock_to_ns(session_date, early_close_moc_cutoff_et),
            official_close_ns=et_clock_to_ns(
                session_date,
                early_close_official_close_et,
            ),
        )
    return MocSessionBounds(
        session_date=session_date,
        moc_cutoff_ns=et_clock_to_ns(session_date, moc_cutoff_et),
        official_close_ns=et_clock_to_ns(session_date, official_close_et),
    )


def session_date_from_calendar_path(path: str | Path | None) -> date | None:
    """Extract ``YYYY-MM-DD`` from an event-calendar filename, if present."""
    if path is None:
        return None
    match = _CALENDAR_DATE_RE.search(str(path))
    if match is None:
        return None
    return date.fromisoformat(match.group(1))


def build_moc_bounds_from_platform(
    *,
    moc_session_date: str | None,
    event_calendar_path: str | None,
    moc_cutoff_et: str,
    official_close_et: str,
    early_close_dates: tuple[str, ...],
    early_close_moc_cutoff_et: str,
    early_close_official_close_et: str,
) -> MocSessionBounds | None:
    """Resolve bounds when MOC modeling is configured.

    Returns ``None`` when no session date can be determined (MOC path
    inert — ``is_moc`` orders should not be emitted without bounds).
    """
    raw_date = moc_session_date
    if raw_date is None:
        cal_date = session_date_from_calendar_path(event_calendar_path)
        if cal_date is not None:
            raw_date = cal_date.isoformat()
    if raw_date is None:
        return None
    session_date = date.fromisoformat(raw_date)
    early = session_date.isoformat() in frozenset(early_close_dates)
    return resolve_moc_session_bounds(
        session_date,
        moc_cutoff_et=moc_cutoff_et,
        official_close_et=official_close_et,
        early_close=early,
        early_close_moc_cutoff_et=early_close_moc_cutoff_et,
        early_close_official_close_et=early_close_official_close_et,
    )
