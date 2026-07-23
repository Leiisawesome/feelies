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

        # Accumulate into the current bucket; spill into subsequent buckets so
        # total volume is conserved with no rounding.
        #
        # F5 (sensor_review_2026-07-02): the previous ``while remaining > 0``
        # loop was O(size / bucket_volume) — a single block/sweep print (e.g.
        # 1e6 shares into a 5000-share bucket) cost ~200 iterations, breaching
        # the per-sensor latency budget on that one event.  Because the
        # tick-rule ``side`` is constant within a single ``update()``, every
        # *fully-filled* spanned bucket is 100 % one-sided ⇒ imbalance exactly
        # 1.0.  So we complete the current bucket, batch the run of whole
        # 1.0-buckets in O(min(k, window)), and open the remainder — O(1) in
        # the trade size.  On non-spanning trades (the fixture / normal market)
        # the batch branch is never taken, so the emitted stream is byte-
        # identical to the loop (locked by ``vpin_50bucket.jsonl``).
        remaining = size
        bucket_vol = self._bucket_volume
        buckets = state["buckets"]
        maxlen = buckets.maxlen

        cur_total = state["buy_vol"] + state["sell_vol"]
        room = bucket_vol - cur_total  # room >= 1 (buckets reset on completion)

        if remaining < room:
            # Common case: the whole trade fits in the current partial bucket.
            if side > 0:
                state["buy_vol"] += remaining
            else:
                state["sell_vol"] += remaining
        else:
            # 1) Complete the current bucket.
            if side > 0:
                state["buy_vol"] += room
            else:
                state["sell_vol"] += room
            imbalance = abs(state["buy_vol"] - state["sell_vol"]) / float(bucket_vol)
            if len(buckets) == maxlen:
                state["buckets_sum"] -= buckets[0]
            buckets.append(imbalance)
            state["buckets_sum"] += imbalance
            state["buy_vol"] = 0
            state["sell_vol"] = 0
            remaining -= room

            # 2) Whole single-sided buckets (each imbalance == 1.0), batched.
            k = remaining // bucket_vol
            if k > 0:
                if k >= maxlen:
                    # The entire window is overwritten by 1.0 buckets; only the
                    # last ``maxlen`` survive.  Set the running sum to the exact
                    # value (``maxlen`` ones), which also resets any accumulated
                    # float drift.
                    buckets.clear()
                    buckets.extend((1.0,) * maxlen)
                    state["buckets_sum"] = float(maxlen)
                else:
                    overflow = len(buckets) + k - maxlen
                    for _ in range(max(0, overflow)):
                        state["buckets_sum"] -= buckets.popleft()
                    buckets.extend((1.0,) * k)
                    state["buckets_sum"] += float(k)
                remaining -= k * bucket_vol

            # 3) Remainder opens a fresh partial bucket.
            if remaining > 0:
                if side > 0:
                    state["buy_vol"] += remaining
                else:
                    state["sell_vol"] += remaining

        if buckets:
            value = state["buckets_sum"] / float(len(buckets))
        else:
            value = 0.0
        warm = len(buckets) >= self._min_buckets

        return SensorEmission(value=value, warm=warm)
