"""Fraction of trades that touch or cross the prevailing NBBO.

Despite its compatibility name, ``trade_through_rate`` measures NBBO
aggression rather than strict Reg NMS trade-throughs:

- buy-side aggression if ``trade.price >= ask``;
- sell-side aggression if ``trade.price <= bid``;
- otherwise the trade is inside the spread.

The sensor retains the latest valid quote and reports the trailing event-time
fraction of aggressive prints.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class TradeThroughRateSensor:
    """Rolling-window fraction of trades that print at or outside the NBBO.

    Parameters:

    - ``window_seconds`` (int, default 30): trailing event-time
      window over which the trade-through fraction is computed.
    - ``min_trades`` (int, default 20): minimum trades inside the
      window before ``warm=True``.
    """

    sensor_id: str = "trade_through_rate"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 30,
        min_trades: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_trades < 0:
            raise ValueError(f"min_trades must be >= 0, got {min_trades}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_trades = min_trades

    def initial_state(self) -> dict[str, Any]:
        return {
            "events": deque(),  # (ts_ns, is_through: bool)
            "through_count": 0,
            "last_bid": None,
            "last_ask": None,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if isinstance(event, NBBOQuote):
            bid = float(event.bid)
            ask = float(event.ask)
            # Keep the prior NBBO when the new quote is invalid.
            if bid <= 0.0 or ask <= 0.0 or bid > ask:
                return None
            state["last_bid"] = bid
            state["last_ask"] = ask
            return None

        if not isinstance(event, Trade):
            return None

        bid = state["last_bid"]
        ask = state["last_ask"]
        if bid is None or ask is None:
            # No NBBO snapshot yet — cannot classify; do not emit.
            return None

        price = float(event.price)
        is_through = price >= ask or price <= bid

        ts = event.timestamp_ns
        events = state["events"]
        events.append((ts, is_through))
        if is_through:
            state["through_count"] += 1

        cutoff = ts - self._window_ns
        while events and events[0][0] < cutoff:
            _t, was_through = events.popleft()
            if was_through:
                state["through_count"] -= 1

        n = len(events)
        value = state["through_count"] / float(n) if n > 0 else 0.0
        warm = n >= self._min_trades

        return SensorEmission(value=value, warm=warm)
