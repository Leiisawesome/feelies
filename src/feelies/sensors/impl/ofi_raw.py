"""Emit unsmoothed order-flow imbalance between consecutive quotes.

Each quote contributes once:

    ofi_t = +bid_size_t              if bid_t  > bid_{t-1}
            -bid_size_{t-1}          if bid_t  < bid_{t-1}
            +(bid_size_t - bid_size_{t-1}) if bid_t == bid_{t-1}
          + +ask_size_{t-1}          if ask_t  > ask_{t-1}
            -ask_size_t              if ask_t  < ask_{t-1}
            -(ask_size_t - ask_size_{t-1}) if ask_t == ask_{t-1}

Positive values indicate buy pressure. Unlike ``ofi_ewma``, summing this sensor
over a horizon yields integrated signed flow without double-counting. Warmth is
based on OFI-bearing quotes in the trailing event-time window.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class OFIRawSensor:
    """Per-event signed OFI (the integrand of integrated order flow).

    Parameters:

    - ``warm_after`` (int, default 50): minimum number of OFI-bearing quotes
      within ``warm_window_seconds`` before ``warm=True``.
    - ``warm_window_seconds`` (int, default 300): sliding event-time window for
      the warm-up quote count.
    """

    sensor_id: str = "ofi_raw"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 50,
        warm_window_seconds: int = 300,
    ) -> None:
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "last_bid": None,
            "last_ask": None,
            "last_bid_size": 0,
            "last_ask_size": 0,
            "warm_ts": deque(),  # OFI-bearing quote timestamps.
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
        # Invalid books would corrupt the next OFI delta.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            return None
        bid_sz = event.bid_size
        ask_sz = event.ask_size

        last_bid = state["last_bid"]
        last_ask = state["last_ask"]
        last_bid_sz = state["last_bid_size"]
        last_ask_sz = state["last_ask_size"]

        if last_bid is None or last_ask is None:
            # First quote establishes the level; no OFI is measurable yet.
            state["last_bid"] = bid
            state["last_ask"] = ask
            state["last_bid_size"] = bid_sz
            state["last_ask_size"] = ask_sz
            return SensorEmission(value=0.0, warm=False)

        if bid > last_bid:
            bid_contrib = float(bid_sz)
        elif bid < last_bid:
            bid_contrib = -float(last_bid_sz)
        else:
            bid_contrib = float(bid_sz - last_bid_sz)
        if ask > last_ask:
            ask_contrib = float(last_ask_sz)
        elif ask < last_ask:
            ask_contrib = -float(ask_sz)
        else:
            ask_contrib = -float(ask_sz - last_ask_sz)
        ofi = bid_contrib + ask_contrib

        state["last_bid"] = bid
        state["last_ask"] = ask
        state["last_bid_size"] = bid_sz
        state["last_ask_size"] = ask_sz

        # Sliding-window warmth reverts after data gaps.
        ts_ns = event.timestamp_ns
        warm_ts: deque[int] = state["warm_ts"]
        warm_ts.append(ts_ns)
        cutoff = ts_ns - self._warm_window_ns
        while warm_ts and warm_ts[0] < cutoff:
            warm_ts.popleft()

        return SensorEmission(value=ofi, warm=len(warm_ts) >= self._warm_after)
