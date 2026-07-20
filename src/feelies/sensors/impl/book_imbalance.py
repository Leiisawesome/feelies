"""Signed top-of-book displayed-size imbalance.

``(bid_size - ask_size) / (bid_size + ask_size)`` is positive for a bid-heavy
book and negative for an ask-heavy book. It exposes microprice pressure without
the price-level drift of a raw microprice. Invalid or empty books are cold.
Warmth requires enough valid quotes in the trailing event-time window.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class BookImbalanceSensor:
    """Signed top-of-book displayed-size imbalance in ``[-1, 1]``.

    Parameters:

    - ``warm_after`` (int, default 1): minimum number of valid (positive
      two-sided depth) quotes within ``warm_window_seconds`` before
      ``warm=True``.  Default 1 because the imbalance is computable from a
      single quote.
    - ``warm_window_seconds`` (int, default 60): sliding event-time window for
      the warm-up quote count; quotes older than this boundary do not count, so
      the sensor reverts to cold after sustained data gaps (S3).
    """

    sensor_id: str = "book_imbalance"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 1,
        warm_window_seconds: int = 60,
        imbalance_cap: float = 1.0,
    ) -> None:
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if not (0.0 < imbalance_cap <= 1.0):
            raise ValueError(f"imbalance_cap must be in (0, 1], got {imbalance_cap}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000
        # Cap each quote's influence before horizon averaging; 1.0 is a no-op.
        self._imbalance_cap = float(imbalance_cap)

    def initial_state(self) -> dict[str, Any]:
        return {
            "warm_ts": deque(),  # Valid-quote timestamps for the warm window.
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
        # Invalid or crossed books carry no usable imbalance.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            return None

        bid_sz = event.bid_size
        ask_sz = event.ask_size
        total = bid_sz + ask_sz

        if total <= 0:
            # No displayed liquidity: imbalance is undefined, not balanced.
            return SensorEmission(value=0.0, warm=False)

        value = (bid_sz - ask_sz) / float(total)
        # Bound one anomalous quote's influence.
        cap = self._imbalance_cap
        if value > cap:
            value = cap
        elif value < -cap:
            value = -cap

        # Sliding-window warmth reverts after data gaps.
        ts_ns = event.timestamp_ns
        warm_ts: deque[int] = state["warm_ts"]
        warm_ts.append(ts_ns)
        cutoff = ts_ns - self._warm_window_ns
        while warm_ts and warm_ts[0] < cutoff:
            warm_ts.popleft()

        return SensorEmission(value=value, warm=len(warm_ts) >= self._warm_after)
