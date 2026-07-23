"""Bid-versus-ask depth replenishment asymmetry.

At unchanged prices, positive size changes count as replenishment. Trailing
bid and ask additions produce a bounded score::

    (bid_adds - ask_adds) / max(bid_adds + ask_adds, epsilon)

Positive means faster bid replenishment. Warm-up requires enough quotes and an
addition on both sides; ``min_window_span_seconds`` can also require elapsed
history. The estimator is deterministic, but its forward-return sign is not
validated: the reference inventory alpha remains quarantined after weak and
contradictory 30-second evidence.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


_EPS = 1e-12


class QuoteReplenishAsymmetrySensor:
    """Asymmetry between bid- and ask-side replenishment rates.

    Parameters:

    - ``window_seconds`` (int, default 5): trailing event-time window.
    - ``min_observations`` (int, default 20): minimum quotes before
      ``warm=True``.
    - ``min_window_span_seconds`` (int | None, default None): when set,
      ``warm`` additionally requires the trailing ``min_observations``
      quotes to span at least this many seconds. ``None`` disables the floor.
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
        min_window_span_seconds: int | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_observations < 0:
            raise ValueError(f"min_observations must be >= 0, got {min_observations}")
        if min_window_span_seconds is not None and min_window_span_seconds <= 0:
            raise ValueError(
                f"min_window_span_seconds must be > 0 or None, got {min_window_span_seconds}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_observations = min_observations
        self._min_span_ns = (
            None if min_window_span_seconds is None else min_window_span_seconds * 1_000_000_000
        )

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
            # All quote times are needed for the optional elapsed-span gate.
            "quote_ts": deque(),
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, NBBOQuote):
            return None

        ts = event.timestamp_ns
        bid_price = float(event.bid)
        ask_price = float(event.ask)
        bid_sz = int(event.bid_size)
        ask_sz = int(event.ask_size)

        invalid_nbbo = (
            bid_price <= 0.0
            or ask_price <= 0.0
            or bid_price > ask_price
            or bid_sz <= 0
            or ask_sz <= 0
        )
        if invalid_nbbo:
            state["last_bid_size"] = None
            state["last_ask_size"] = None
            state["last_bid_price"] = None
            state["last_ask_price"] = None
            return None

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

        quote_ts: deque[int] | None = None
        if self._min_span_ns is not None:
            # Same trailing window as bid_adds/ask_adds — this only measures
            # how much *time* the retained quotes span, not an independent
            # count.
            quote_ts = state["quote_ts"]
            quote_ts.append(ts)
            while quote_ts and quote_ts[0] < cutoff:
                quote_ts.popleft()

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

        if self._min_span_ns is not None and quote_ts is not None:
            # Count the in-window quotes (not the lifetime counter) so the
            # min_observations floor and the elapsed-span floor are backed by
            # the same trailing window, mirroring the other quote-window
            # sensors and this module's documented contract.
            warm = (
                len(quote_ts) >= self._min_observations
                and bool(bid_adds)
                and bool(ask_adds)
                and (quote_ts[-1] - quote_ts[0]) >= self._min_span_ns
            )
        else:
            warm = state["count"] >= self._min_observations and bool(bid_adds) and bool(ask_adds)

        return SensorEmission(value=value, warm=warm)
