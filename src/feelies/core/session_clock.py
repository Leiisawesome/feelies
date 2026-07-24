"""Deterministic session-clock helpers anchored to the RTH open/close.

Pure functions of an event timestamp (no wall-clock reads), so they keep
the ``HorizonScheduler``'s determinism contract (Inv-5) while letting the
horizon grid anchor to 09:30 America/New_York instead of the first event,
avoiding a truncated first bucket.

``rth_close_ns`` is the mirror at 16:00 ET.  The bounded-deferral cap
(``feelies.risk.deferral_cap``) consumes it as the wall-clock backstop of
last resort (design §2.3/§2.8): during a post-safety-OFF quote freeze an
open book is held past the nominal deferral ceiling until the next event,
and exits by the session boundary at latest.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

_TZ_ET = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000

# US equities RTH open/close.  Open matches the convention in
# ``feelies.harness.backtest_prep`` (09:30 ET); close is the standard 16:00 ET
# regular-session close (early-close days are resolved by the richer
# ``feelies.execution.trading_session`` bounds, not this fixed helper).
_RTH_OPEN_HOUR = 9
_RTH_OPEN_MINUTE = 30
_RTH_CLOSE_HOUR = 16
_RTH_CLOSE_MINUTE = 0


def _rth_boundary_ns(ts_ns: int, hour: int, minute: int) -> int:
    """Epoch-ns instant of ``hour:minute`` America/New_York on the ET
    calendar date containing ``ts_ns``.

    DST-correct (``zoneinfo`` resolves the offset for that date) and
    integer-exact: the input is split into whole seconds + sub-second
    remainder so no float rounding touches the nanosecond field.
    """
    secs, _rem_ns = divmod(ts_ns, _NS_PER_SECOND)
    dt_et = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(_TZ_ET)
    boundary_et = datetime.combine(dt_et.date(), time(hour, minute), tzinfo=_TZ_ET)
    return int(boundary_et.timestamp()) * _NS_PER_SECOND


def rth_open_ns(ts_ns: int) -> int:
    """Return the 09:30 America/New_York instant (epoch ns) for the ET
    calendar date containing ``ts_ns``."""
    return _rth_boundary_ns(ts_ns, _RTH_OPEN_HOUR, _RTH_OPEN_MINUTE)


def rth_close_ns(ts_ns: int) -> int:
    """Return the 16:00 America/New_York instant (epoch ns) for the ET
    calendar date containing ``ts_ns``.

    Same determinism guarantees as :func:`rth_open_ns`.  This is the
    standard regular-trading-hours close; early-close (half-day) sessions
    are out of scope for this fixed helper and are handled by
    :class:`feelies.execution.trading_session.TradingSessionBounds`.
    """
    return _rth_boundary_ns(ts_ns, _RTH_CLOSE_HOUR, _RTH_CLOSE_MINUTE)


__all__ = ["rth_open_ns", "rth_close_ns"]
