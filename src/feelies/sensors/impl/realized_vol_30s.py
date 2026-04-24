"""Realized volatility over a sliding event-time window.

Computes the standard deviation of mid-price log-returns over the
last ``window_seconds`` of trades / quotes:

    rv_t = sqrt( sum_{i in window} r_i^2  )

where ``r_i = log(mid_i / mid_{i-1})``.  This is unannualized — the
raw window-local standard deviation — so feature consumers may
re-scale by ``sqrt(seconds_per_year / window_seconds)`` if they want
an annualised number.

The window is enforced by event time, not event count, by storing
``(ts_ns, log_ret)`` tuples in a deque and trimming the front when
events fall out of the trailing ``window_seconds * 1e9`` ns range.
This makes the sensor robust to bursty quote streams.

Determinism: math is purely arithmetic (``math.log``, ``math.sqrt``)
which produces identical results across Python versions on the same
platform.  No RNG, no time-of-day reads.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class RealizedVol30sSensor:
    """Realized volatility over a sliding event-time window.

    Parameters:

    - ``window_seconds`` (int, default 30): trailing window in
      seconds.  Despite the class name, the actual window is
      configurable; the default reflects the canonical 30-second
      bucket from the alpha catalog.
    - ``warm_after`` (int, default 16): minimum number of returns
      observed before ``warm=True``.  16 corresponds to roughly 1.5
      seconds at typical 10Hz quote frequency, enough to compute a
      meaningful local std.
    """

    sensor_id: str = "realized_vol_30s"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 30,
        warm_after: int = 16,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = int(window_seconds) * 1_000_000_000
        self._warm_after = warm_after

    def initial_state(self) -> dict[str, Any]:
        return {
            "history": deque(),  # (ts_ns, log_ret)
            "sum_sq": 0.0,
            "last_mid": None,
            "count": 0,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None

        bid = float(event.bid)
        ask = float(event.ask)
        if bid <= 0.0 or ask <= 0.0:
            return None
        mid = (bid + ask) / 2.0
        ts = event.timestamp_ns
        last_mid = state["last_mid"]

        if last_mid is not None and last_mid > 0.0:
            log_ret = math.log(mid / last_mid)
            history: deque[tuple[int, float]] = state["history"]
            history.append((ts, log_ret))
            state["sum_sq"] += log_ret * log_ret
            state["count"] += 1

            cutoff = ts - self._window_ns
            while history and history[0][0] < cutoff:
                _, ev_ret = history.popleft()
                state["sum_sq"] -= ev_ret * ev_ret

            value = math.sqrt(max(0.0, state["sum_sq"]))
        else:
            value = 0.0

        state["last_mid"] = mid

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=state["count"] >= self._warm_after,
        )
