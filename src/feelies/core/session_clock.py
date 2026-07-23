"""Deterministic session-clock helpers anchored to the RTH open.

Pure functions of an event timestamp (no wall-clock reads), so they keep
the ``HorizonScheduler``'s determinism contract (Inv-5) while letting the
horizon grid anchor to 09:30 America/New_York instead of the first event,
avoiding a truncated first bucket.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

_TZ_ET = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000

# US equities RTH open.  Matches the convention in
# ``feelies.harness.backtest_prep`` (09:30 ET).
_RTH_OPEN_HOUR = 9
_RTH_OPEN_MINUTE = 30


def rth_open_ns(ts_ns: int) -> int:
    """Return the 09:30 America/New_York instant (epoch ns) for the ET
    calendar date containing ``ts_ns``.

    DST-correct (``zoneinfo`` resolves the offset for that date) and
    integer-exact: the input is split into whole seconds + sub-second
    remainder so no float rounding touches the nanosecond field.
    """
    secs, _rem_ns = divmod(ts_ns, _NS_PER_SECOND)
    dt_et = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(_TZ_ET)
    open_et = datetime.combine(dt_et.date(), time(_RTH_OPEN_HOUR, _RTH_OPEN_MINUTE), tzinfo=_TZ_ET)
    return int(open_et.timestamp()) * _NS_PER_SECOND


__all__ = ["rth_open_ns"]
