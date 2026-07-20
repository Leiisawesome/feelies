"""Report whether event time falls inside a scheduled-flow window.

The sensor is stateless but honors symbol-scoped and universe-wide windows.
It emits:

.value = (
        active,                  # 1.0 if inside any matching window, else 0.0
        seconds_to_window_close, # remaining time in the active window; -1.0 if inactive
        window_id_hash,          # int32-hashed window identifier; 0 if inactive
        flow_direction_prior,    # ±1.0 expected sign; 0.0 if neutral / inactive
    )

Overlaps select the earliest close, then the lexicographically smallest ID.
Window IDs use a stable SHA-256-derived 32-bit hash.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission
from feelies.storage.reference.event_calendar import (
    CalendarWindow,
    EventCalendar,
)

_NS_PER_SECOND: float = 1_000_000_000.0


def _window_id_hash(window_id: str) -> int:
    """Stable, salt-free 32-bit hash of a window identifier."""
    digest = hashlib.sha256(window_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


class ScheduledFlowWindowSensor:
    """Reports whether the current event sits inside a known flow window.

    Parameters:

    - ``calendar`` (:class:`EventCalendar`, required): the per-session
      window registry loaded from
      ``src/feelies/storage/reference/event_calendar/<date>.yaml`` (or any path
      passed via ``PlatformConfig.event_calendar_path``).  Pinned at
      construction time; the sensor never mutates it.
    """

    sensor_id: str = "scheduled_flow_window"
    sensor_version: str = "1.2.0"

    def __init__(
        self,
        *,
        calendar: EventCalendar,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
    ) -> None:
        if not isinstance(calendar, EventCalendar):
            raise TypeError(f"calendar must be an EventCalendar, got {type(calendar).__name__}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._calendar = calendar
        # Empty calendars stay cold instead of looking inactive.
        self._has_windows = len(calendar.windows) > 0
        # Each symbol stays cold until it has an eligible window.
        self._symbol_has_windows: dict[str, bool] = {}
        for w in calendar.windows:
            if w.symbol is None:
                # Universe-wide window — keys are resolved lazily.
                self._has_universe_wide_window = True
                break
        else:
            self._has_universe_wide_window = False

    def initial_state(self) -> dict[str, Any]:
        return {}

    def _select_active_window(
        self,
        ts_ns: int,
        symbol: str,
    ) -> CalendarWindow | None:
        """Pick the matching window with the earliest ``end_ns``.

        Ties on ``end_ns`` are broken by lexicographic ``window_id`` so
        selection does not depend on the calendar's internal iteration
        order (Inv-C: determinism).
        """
        chosen: CalendarWindow | None = None
        for w in self._calendar.windows_active_at(ts_ns):
            if w.symbol is not None and w.symbol != symbol:
                continue
            if chosen is None:
                chosen = w
                continue
            if w.end_ns < chosen.end_ns or (
                w.end_ns == chosen.end_ns and w.window_id < chosen.window_id
            ):
                chosen = w
        return chosen

    def _symbol_has_eligible_window(self, symbol: str) -> bool:
        """Memoised check: is at least one window eligible for *symbol*?

        A universe-wide window short-circuits to True for every symbol;
        otherwise we scan the (small) per-session window list once per
        symbol and cache the result.
        """
        if self._has_universe_wide_window:
            return True
        cached = self._symbol_has_windows.get(symbol)
        if cached is not None:
            return cached
        eligible = any(w.symbol == symbol for w in self._calendar.windows)
        self._symbol_has_windows[symbol] = eligible
        return eligible

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        ts_ns = event.timestamp_ns
        symbol = event.symbol
        window = self._select_active_window(ts_ns, symbol)
        if window is None:
            value = (0.0, -1.0, 0.0, 0.0)
        else:
            seconds_remaining = (window.end_ns - ts_ns) / _NS_PER_SECOND
            value = (
                1.0,
                seconds_remaining,
                float(_window_id_hash(window.window_id)),
                float(window.flow_direction_prior),
            )
        # Warm only when both the calendar has windows AND at least one
        # is symbol-eligible for the inbound event.  This catches scope
        # misconfiguration (e.g. EARNINGS_DRIFT for AAPL consumed by MSFT)
        # which would otherwise present as a normal "outside any window"
        # reading and silently disable a downstream alpha.
        warm = self._has_windows and self._symbol_has_eligible_window(symbol)
        return SensorEmission(value=value, warm=warm)
