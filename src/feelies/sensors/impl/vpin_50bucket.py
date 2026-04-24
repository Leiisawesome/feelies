"""Volume-Synchronized Probability of Informed Trading (VPIN).

VPIN sequences trades into equal-volume *buckets* (rather than equal
time intervals) and reports the average absolute order-flow imbalance
across the trailing window of buckets.

Reference: Easley, López de Prado & O'Hara (2012) "Flow Toxicity and
Liquidity in a High-Frequency World" — RFS 25(5).

Algorithm (deterministic, integer bucket boundaries):

1. Maintain a running volume bucket of total size ``bucket_volume``.
2. Each incoming trade contributes ``size`` shares.  Trades are
   classified buy / sell using the *tick rule*: a trade above the
   previous trade price is buy-initiated, below is sell-initiated,
   equal price inherits the prior side (defaulting to buy on the
   very first trade).
3. When the running bucket fills, compute its imbalance
   ``|buy_volume - sell_volume| / bucket_volume`` and append it to
   a deque of length ``window_buckets``.  Excess shares spill into
   the next bucket so total volume is conserved exactly.
4. The sensor's value is the rolling mean of the deque.  ``warm`` is
   true once at least ``min_buckets`` buckets have been completed.

Determinism: pure integer arithmetic for volume accounting; floats
only for the imbalance value.  Tick-rule classification removes any
dependence on quote midpoint, so VPIN is robust to NBBO inversion.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


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
    sensor_version: str = "1.0.0"

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
            raise ValueError(
                f"bucket_volume must be > 0, got {bucket_volume}"
            )
        if window_buckets <= 0:
            raise ValueError(
                f"window_buckets must be > 0, got {window_buckets}"
            )
        if min_buckets < 0 or min_buckets > window_buckets:
            raise ValueError(
                f"min_buckets must be in [0, window_buckets], got {min_buckets}"
            )
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
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = int(event.size)
        if size <= 0:
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
                imbalance = abs(state["buy_vol"] - state["sell_vol"]) / float(
                    bucket_vol
                )
                state["buckets"].append(imbalance)
                state["buy_vol"] = 0
                state["sell_vol"] = 0

        buckets = state["buckets"]
        if buckets:
            value = sum(buckets) / float(len(buckets))
        else:
            value = 0.0
        warm = len(buckets) >= self._min_buckets

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
