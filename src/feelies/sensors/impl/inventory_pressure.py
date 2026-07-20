"""Volume-normalized market-maker inventory proxy.

The tick rule classifies aggressor side. Market-maker inventory takes the
opposite side, so the rolling score is::

    sum(-aggressor_side * size) / max(sum(size), epsilon)

Positive means market makers absorbed net selling and are net long. The score
is bounded to ``[-1, 1]`` and becomes warm after ``min_trades`` in the event-time
window. Processing uses integer volume accounting and no RNG.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission

_EPS = 1e-12


class InventoryPressureSensor:
    """Signed, volume-normalised MM-inventory proxy over a rolling window.

    Parameters:

    - ``window_seconds`` (int, default 60): trailing event-time window.
    - ``min_trades`` (int, default 20): minimum trades in the window
      before ``warm=True``.
    """

    sensor_id: str = "inventory_pressure"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 60,
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
            "events": deque(),  # (ts_ns, mm_inv_change, size)
            "mm_inv_sum": 0,  # Σ (-aggressor_side · size) in window
            "vol_sum": 0,  # Σ size in window
            "last_price": None,
            "last_side": +1,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = int(event.size)
        # A non-positive price/size is malformed; it would also corrupt the
        # tick-rule ``last_price`` reference for subsequent trades.
        if size <= 0 or price <= 0.0:
            return None

        last_price = state["last_price"]
        if last_price is None:
            aggressor = state["last_side"]
        elif price > last_price:
            aggressor = +1
        elif price < last_price:
            aggressor = -1
        else:
            aggressor = state["last_side"]
        state["last_price"] = price
        state["last_side"] = aggressor

        # MM takes the opposite side of the aggressor.
        mm_inv_change = -aggressor * size

        ts = event.timestamp_ns
        events = state["events"]
        events.append((ts, mm_inv_change, size))
        state["mm_inv_sum"] += mm_inv_change
        state["vol_sum"] += size

        cutoff = ts - self._window_ns
        while events and events[0][0] < cutoff:
            _t, old_inv, old_sz = events.popleft()
            state["mm_inv_sum"] -= old_inv
            state["vol_sum"] -= old_sz

        vol = state["vol_sum"]
        if vol <= 0:
            value = 0.0
        else:
            value = state["mm_inv_sum"] / (float(vol) + _EPS)

        warm = len(events) >= self._min_trades

        return SensorEmission(value=value, warm=warm)
