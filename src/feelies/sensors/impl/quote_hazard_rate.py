"""Quote-update hazard rate (instantaneous quote arrival intensity).

Models the inter-arrival times of NBBO updates as a stochastic point
process and reports the rolling-window hazard rate (events per
second).  A spike in the hazard rate often precedes liquidity
withdrawal: market makers cancel and re-post quotes faster when
conditioning on adverse flow.

Estimator (deterministic, event-time):

- Maintain a deque of quote timestamps within the trailing
  ``window_seconds``.
- ``hazard_t = len(window) / window_seconds`` (units: 1/second).

Returns the hazard rate.  ``warm`` is true once the window has held
``min_samples`` quotes for at least one full window.

Determinism: pure integer timestamp comparisons; the float division
at the end is the only floating-point operation.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class QuoteHazardRateSensor:
    """Quote-arrival hazard rate over a rolling window.

    Parameters:

    - ``window_seconds`` (int, default 5): event-time window in
      seconds.  Short windows track instantaneous bursts; long
      windows estimate baseline arrival intensity.
    - ``min_samples`` (int, default 20): minimum quotes inside the
      window before ``warm=True``.
    """

    sensor_id: str = "quote_hazard_rate"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 5,
        min_samples: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if min_samples < 0:
            raise ValueError(
                f"min_samples must be >= 0, got {min_samples}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._window_seconds = float(window_seconds)
        self._min_samples = min_samples

    def initial_state(self) -> dict[str, Any]:
        return {"timestamps": deque()}

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None

        ts = event.timestamp_ns
        timestamps = state["timestamps"]
        timestamps.append(ts)
        cutoff = ts - self._window_ns
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        n = len(timestamps)
        value = float(n) / self._window_seconds
        warm = n >= self._min_samples

        return SensorReading(
            timestamp_ns=ts,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=warm,
        )
