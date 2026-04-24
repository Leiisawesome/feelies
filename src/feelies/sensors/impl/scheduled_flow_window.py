"""Scheduled-flow window sensor (v0.3 §20.4.2).

Time-of-day conditional sensor exposing whether the current event-time
falls inside any registered scheduled-flow window from the bootstrap
:class:`feelies.storage.reference.event_calendar.EventCalendar`.

This is the canonical L1 fingerprint sensor for the
``SCHEDULED_FLOW`` mechanism family.  It is *stateless* in the
classical sense — no per-symbol accumulator — but is per-symbol *aware*
because some windows are symbol-scoped (e.g. ``EARNINGS_DRIFT`` for
``AAPL``) and others are universe-wide (e.g. ``MOC_IMBALANCE``).

Outputs (length-4 tuple):

    SensorReading.value = (
        active,                  # 1.0 if inside any matching window, else 0.0
        seconds_to_window_close, # remaining time in the active window; -1.0 if inactive
        window_id_hash,          # int32-hashed window identifier; 0 if inactive
        flow_direction_prior,    # ±1.0 expected sign; 0.0 if neutral / inactive
    )

When multiple windows are simultaneously active for a symbol (e.g.
``OPENING_AUCTION`` and ``EARNINGS_DRIFT`` overlap at 09:30), the
sensor returns the window with the *earliest* ``end_ns`` — the one
about to close first — so the reported ``seconds_to_window_close``
remains a useful regime-clock signal.

Determinism:

- Uses only integer nanosecond comparisons against pre-resolved
  window bounds.
- ``window_id_hash`` is ``int(hashlib.sha256(window_id.encode()).hexdigest()[:8], 16)``
  — fast, salt-free, and identical across processes (unlike Python's
  built-in ``hash``, which is salted by ``PYTHONHASHSEED``).
- Calendar is injected at construction time; the sensor never reads
  the wall clock.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade
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
      ``storage/reference/event_calendar/<date>.yaml``.  Pinned at
      construction time; the sensor never mutates it.
    """

    sensor_id: str = "scheduled_flow_window"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        calendar: EventCalendar,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
    ) -> None:
        if not isinstance(calendar, EventCalendar):
            raise TypeError(
                f"calendar must be an EventCalendar, got {type(calendar).__name__}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._calendar = calendar

    def initial_state(self) -> dict[str, Any]:
        return {}

    def _select_active_window(
        self, ts_ns: int, symbol: str,
    ) -> CalendarWindow | None:
        """Pick the matching window with the earliest ``end_ns``."""
        chosen: CalendarWindow | None = None
        for w in self._calendar.windows_active_at(ts_ns):
            if w.symbol is not None and w.symbol != symbol:
                continue
            if chosen is None or w.end_ns < chosen.end_ns:
                chosen = w
        return chosen

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
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
        return SensorReading(
            timestamp_ns=ts_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=True,
        )
