"""Quote replenishment asymmetry — bid-vs-ask depth recovery rate.

After a one-sided liquidity sweep, market makers replenish on the
side that was hit.  The *speed* of replenishment is asymmetric:
inventory-stressed MMs delay refilling the heavy side, whereas
informed-trader-anchored MMs refill quickly to maintain spread.
This sensor estimates the asymmetry as the difference between the
trailing average rate of bid-side and ask-side depth additions.

Algorithm:

- On every quote, compute ``Δbid_size`` and ``Δask_size`` versus the
  previous quote.  Positive deltas are *additions* (replenishment);
  negative deltas are *withdrawals*.  A delta is only counted as
  replenishment when the side's price is **unchanged** — a new
  best price represents a *different* price level (a tighter
  quote or a price step), not a deepening of the prior level.
  Without this guard, a best-bid move from 100.00 / 100 lots up to
  100.01 / 200 lots would be miscounted as +100 lots of bid-side
  replenishment.
- Maintain two trailing-window sums of additions per side over
  ``window_seconds`` of event time.
- Sensor value:
      asymmetry = (bid_adds - ask_adds) /
                  max(bid_adds + ask_adds, ε)
  Bounded in ``[-1, 1]``; positive ⇒ bid replenishes faster.  The
  per-second normalisation cancels in the ratio so we use the raw
  trailing-window sums directly.

Returns the asymmetry score.  ``warm`` is true once
``min_observations`` quotes have been seen and at least one
addition on each side has been recorded.

Determinism: deque-based event-time eviction; no floating-point
state other than the additions.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


_EPS = 1e-12


class QuoteReplenishAsymmetrySensor:
    """Asymmetry between bid- and ask-side replenishment rates.

    Parameters:

    - ``window_seconds`` (int, default 5): trailing event-time window.
    - ``min_observations`` (int, default 20): minimum quotes before
      ``warm=True``.
    """

    sensor_id: str = "quote_replenish_asymmetry"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 5,
        min_observations: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_observations < 0:
            raise ValueError(f"min_observations must be >= 0, got {min_observations}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_observations = min_observations

    def initial_state(self) -> dict[str, Any]:
        return {
            "bid_adds": deque(),  # (ts_ns, delta)
            "ask_adds": deque(),
            "bid_sum": 0,
            "ask_sum": 0,
            "last_bid_size": None,
            "last_ask_size": None,
            "last_bid_price": None,
            "last_ask_price": None,
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

        ts = event.timestamp_ns
        bid_price = float(event.bid)
        ask_price = float(event.ask)
        bid_sz = int(event.bid_size)
        ask_sz = int(event.ask_size)

        last_bid_sz = state["last_bid_size"]
        last_ask_sz = state["last_ask_size"]
        last_bid_price = state["last_bid_price"]
        last_ask_price = state["last_ask_price"]
        state["count"] += 1

        # Only count size growth as replenishment when the price is unchanged
        # — a different best price is a *different* level, not a deepening
        # of the prior one.
        if last_bid_sz is not None and last_bid_price == bid_price:
            d_bid = bid_sz - last_bid_sz
            if d_bid > 0:
                state["bid_adds"].append((ts, d_bid))
                state["bid_sum"] += d_bid
        if last_ask_sz is not None and last_ask_price == ask_price:
            d_ask = ask_sz - last_ask_sz
            if d_ask > 0:
                state["ask_adds"].append((ts, d_ask))
                state["ask_sum"] += d_ask

        state["last_bid_size"] = bid_sz
        state["last_ask_size"] = ask_sz
        state["last_bid_price"] = bid_price
        state["last_ask_price"] = ask_price

        cutoff = ts - self._window_ns
        bid_adds = state["bid_adds"]
        while bid_adds and bid_adds[0][0] < cutoff:
            _t, v = bid_adds.popleft()
            state["bid_sum"] -= v
        ask_adds = state["ask_adds"]
        while ask_adds and ask_adds[0][0] < cutoff:
            _t, v = ask_adds.popleft()
            state["ask_sum"] -= v

        bid_total = state["bid_sum"]
        ask_total = state["ask_sum"]
        denom = bid_total + ask_total
        if denom < _EPS:
            value = 0.0
        else:
            value = (bid_total - ask_total) / denom

        warm = state["count"] >= self._min_observations and bool(bid_adds) and bool(ask_adds)

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
