"""Volume-synchronized probability of informed trading.

Trades fill equal-volume buckets. Tick-rule classification assigns buy and sell
volume, and each completed bucket contributes:

``abs(buy_volume - sell_volume) / bucket_volume``

Excess shares spill into the next bucket. The emitted value is the trailing
mean, warm after ``min_buckets`` completions.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class VPIN50BucketSensor:
    """50-bucket VPIN with tick-rule classification.

    Parameters:

    - ``bucket_volume`` (int, default 5_000): shares per bucket.
    - ``window_buckets`` (int, default 50): number of completed
      buckets to average over.
    - ``min_buckets`` (int, default 10): minimum filled buckets
      before ``warm=True``.
    """

    sensor_id: str = "vpin_50bucket"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        bucket_volume: int = 5_000,
        window_buckets: int = 50,
        min_buckets: int = 10,
    ) -> None:
        if bucket_volume <= 0:
            raise ValueError(f"bucket_volume must be > 0, got {bucket_volume}")
        if window_buckets <= 0:
            raise ValueError(f"window_buckets must be > 0, got {window_buckets}")
        if min_buckets < 0 or min_buckets > window_buckets:
            raise ValueError(f"min_buckets must be in [0, window_buckets], got {min_buckets}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._bucket_volume = bucket_volume
        self._window_buckets = window_buckets
        self._min_buckets = min_buckets

    def initial_state(self) -> dict[str, Any]:
        return {
            "buy_vol": 0,
            "sell_vol": 0,
            "last_price": None,
            "last_side": +1,
            "buckets": deque(maxlen=self._window_buckets),
            "buckets_sum": 0.0,  # Running sum for an O(1) mean.
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
        # Defensive: a non-positive trade price is malformed market data;
        # while VPIN's tick rule only uses *relative* price direction, a
        # zero/negative price would still update ``last_price`` and pollute
        # subsequent tick-rule classifications.
        if size <= 0 or price <= 0.0:
            return None

        last_price = state["last_price"]
        if last_price is None:
            side = state["last_side"]
        elif price > last_price:
            side = +1
        elif price < last_price:
            side = -1
        else:
            side = state["last_side"]
        state["last_price"] = price
        state["last_side"] = side

        # Accumulate into the current bucket; spill into subsequent
        # buckets so total volume is conserved with no rounding.
        remaining = size
        bucket_vol = self._bucket_volume
        buckets = state["buckets"]
        while remaining > 0:
            cur_total = state["buy_vol"] + state["sell_vol"]
            room = bucket_vol - cur_total
            take = remaining if remaining <= room else room
            if side > 0:
                state["buy_vol"] += take
            else:
                state["sell_vol"] += take
            remaining -= take
            if state["buy_vol"] + state["sell_vol"] >= bucket_vol:
                imbalance = abs(state["buy_vol"] - state["sell_vol"]) / float(bucket_vol)
                # Maintain ``buckets_sum`` in sync with the bounded deque.
                # When the deque is at maxlen the append silently drops the
                # oldest element — subtract it from the running sum first.
                if len(buckets) == buckets.maxlen:
                    state["buckets_sum"] -= buckets[0]
                buckets.append(imbalance)
                state["buckets_sum"] += imbalance
                state["buy_vol"] = 0
                state["sell_vol"] = 0

        if buckets:
            value = state["buckets_sum"] / float(len(buckets))
        else:
            value = 0.0
        warm = len(buckets) >= self._min_buckets

        return SensorEmission(value=value, warm=warm)
