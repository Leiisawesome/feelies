"""Bid/ask micro-price sensor.

The micro-price weights bid and ask by the *opposite* side's depth:

    micro = (ask * bid_size + bid * ask_size) / (bid_size + ask_size)

Intuition: if there is much more size on the bid, the next trade is
more likely to lift the offer, so the fair price is closer to the
ask.  Reference: Stoikov (2018) "The Micro-Price: A High-Frequency
Estimator of Future Prices".

Edge case: when total depth is zero we fall back to mid-price
``(bid + ask) / 2`` and emit ``warm=False`` for that reading — a
degenerate book has no informative micro-price.

Determinism: pure float arithmetic; state retained between updates:
running count for warmth and a timestamp deque for the sliding-window
warm check that reverts to cold after sustained data gaps (S3).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class MicroPriceSensor:
    """Stoikov micro-price.

    Parameters:

    - ``warm_after`` (int, default 1): minimum number of valid quotes
      within ``warm_window_seconds`` before ``warm=True``.  Default is
      1 because the micro-price is computable from a single quote.
    - ``warm_window_seconds`` (int, default 60): sliding event-time
      window for the warm-up quote count.  Quotes older than this
      boundary do not count toward ``warm_after``, so the sensor
      reverts to cold after sustained data gaps (S3).
    """

    sensor_id: str = "micro_price"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 1,
        warm_window_seconds: int = 60,
    ) -> None:
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(
                f"warm_window_seconds must be > 0, got {warm_window_seconds}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "count": 0,
            "warm_ts": deque(),  # timestamps of valid (total > 0) quotes (S3)
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
        bid_sz = event.bid_size
        ask_sz = event.ask_size
        total = bid_sz + ask_sz

        if total <= 0:
            value = (bid + ask) / 2.0
            warm = False
        else:
            value = (ask * bid_sz + bid * ask_sz) / float(total)
            state["count"] += 1
            # S3: sliding-window warm check — reverts to cold after data gaps
            ts_ns = event.timestamp_ns
            warm_ts: deque[int] = state["warm_ts"]
            warm_ts.append(ts_ns)
            cutoff = ts_ns - self._warm_window_ns
            while warm_ts and warm_ts[0] < cutoff:
                warm_ts.popleft()
            warm = len(warm_ts) >= self._warm_after

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=warm,
        )
