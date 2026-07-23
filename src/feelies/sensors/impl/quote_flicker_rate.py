"""Measure best-price reversals in a trailing event-time window.

A quote flickers when either side's non-zero price move reverses its previous
direction. The emitted value is:

    quote_flicker_rate = (# flicker-event quotes) / (# quotes)   ∈ [0, 1]

This is a bounded fraction, not a per-second rate. Warmth requires enough
quotes and, when configured, enough elapsed history.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


def _sign(x: float) -> int:
    if x > 0.0:
        return 1
    if x < 0.0:
        return -1
    return 0


class QuoteFlickerRateSensor:
    """Trailing-window fraction of best-price direction reversals.

    Parameters:

    - ``window_seconds`` (int, default 5): trailing event-time window.
      Short windows track instantaneous flicker bursts.
    - ``min_quotes`` (int, default 20): minimum quotes in the window
      before ``warm=True``.
    - ``min_window_span_seconds`` (int | None, default None): when set,
      ``warm`` additionally requires the retained quotes to span at least
      this many seconds, so a quote burst
      cannot satisfy ``min_quotes`` before a genuine window of history has
      accumulated. ``None`` disables the duration floor.
    """

    sensor_id: str = "quote_flicker_rate"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 5,
        min_quotes: int = 20,
        min_window_span_seconds: int | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_quotes < 0:
            raise ValueError(f"min_quotes must be >= 0, got {min_quotes}")
        if min_window_span_seconds is not None and min_window_span_seconds <= 0:
            raise ValueError(
                f"min_window_span_seconds must be > 0 or None, got {min_window_span_seconds}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_quotes = min_quotes
        self._min_span_ns = (
            None if min_window_span_seconds is None else min_window_span_seconds * 1_000_000_000
        )

    def initial_state(self) -> dict[str, Any]:
        return {
            "events": deque(),  # (ts_ns, is_flicker: bool)
            "flicker_count": 0,
            "last_bid": None,
            "last_ask": None,
            "last_bid_dir": 0,  # sign of last non-zero Δbid
            "last_ask_dir": 0,  # sign of last non-zero Δask
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, NBBOQuote):
            return None

        bid = float(event.bid)
        ask = float(event.ask)
        # A degenerate halt or pre-open quote carries no flicker
        # information and would corrupt the direction references; drop it
        # without disturbing state so the next valid quote diffs cleanly.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            return None

        last_bid = state["last_bid"]
        last_ask = state["last_ask"]

        is_flicker = False
        if last_bid is not None:
            d_bid = _sign(bid - last_bid)
            if d_bid != 0:
                if state["last_bid_dir"] != 0 and d_bid == -state["last_bid_dir"]:
                    is_flicker = True
                state["last_bid_dir"] = d_bid
            d_ask = _sign(ask - last_ask)
            if d_ask != 0:
                if state["last_ask_dir"] != 0 and d_ask == -state["last_ask_dir"]:
                    is_flicker = True
                state["last_ask_dir"] = d_ask

        state["last_bid"] = bid
        state["last_ask"] = ask

        ts = event.timestamp_ns
        events = state["events"]
        events.append((ts, is_flicker))
        if is_flicker:
            state["flicker_count"] += 1

        cutoff = ts - self._window_ns
        while events and events[0][0] < cutoff:
            _t, was_flicker = events.popleft()
            if was_flicker:
                state["flicker_count"] -= 1

        n = len(events)
        value = state["flicker_count"] / float(n) if n > 0 else 0.0
        warm = n >= self._min_quotes
        if warm and self._min_span_ns is not None:
            warm = (events[-1][0] - events[0][0]) >= self._min_span_ns

        return SensorEmission(value=value, warm=warm)
