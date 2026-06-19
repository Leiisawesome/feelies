"""Quote-flicker-rate sensor (LIQUIDITY_STRESS mechanism fingerprint).

Measures how often the best bid/ask *oscillates* — a best price moves in
one direction and then reverses — over a trailing event-time window.
Flickering / rapidly-reverting quotes are an L1 signature of unstable
liquidity provision and quote-stuffing / spoofing-like behaviour, and a
component of the ``LIQUIDITY_STRESS`` family (exit-only; half-life
30–600 s) alongside ``spread_z_30d`` and ``quote_hazard_rate``.

Estimator (deterministic, event-time):

For each side independently, track the sign of the last *non-zero* best-
price change.  A **reversal (flicker)** occurs on a quote whose best-price
change is non-zero and has the **opposite sign** to that side's previous
non-zero change (up-then-down or down-then-up).  A quote update is a
"flicker event" if either side reverses on it.  The sensor reports the
trailing-window fraction:

    quote_flicker_rate = (# flicker-event quotes) / (# quotes)   ∈ [0, 1]

(Like ``trade_through_rate`` this is a *fraction*, not a per-second rate,
so it is bounded and comparable across symbols and quote frequencies
despite the historical ``_rate`` suffix.)  High values mean the top of
book is whipsawing — depth is being posted and pulled — which precedes /
accompanies liquidity withdrawal.

Determinism: integer/equality comparisons + one float division; deque
event-time eviction; no RNG, no clock reads.

Warm-up: ``warm = True`` once at least ``min_quotes`` quotes sit in the
trailing window.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


def _sign(x: float) -> int:
    if x > 0.0:
        return 1
    if x < 0.0:
        return -1
    return 0


class QuoteFlickerRateSensor:
    """Trailing-window fraction of best-price direction reversals.

    Parameters:

    - ``window_seconds`` (int, default 5): trailing event-time window.
      Short windows track instantaneous flicker bursts.
    - ``min_quotes`` (int, default 20): minimum quotes in the window
      before ``warm=True``.
    """

    sensor_id: str = "quote_flicker_rate"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 5,
        min_quotes: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_quotes < 0:
            raise ValueError(f"min_quotes must be >= 0, got {min_quotes}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_quotes = min_quotes

    def initial_state(self) -> dict[str, Any]:
        return {
            "events": deque(),  # (ts_ns, is_flicker: bool)
            "flicker_count": 0,
            "last_bid": None,
            "last_ask": None,
            "last_bid_dir": 0,  # sign of last non-zero Δbid
            "last_ask_dir": 0,  # sign of last non-zero Δask
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
        # A1: a degenerate (halt / pre-open) quote carries no flicker
        # information and would corrupt the direction references; drop it
        # without disturbing state so the next valid quote diffs cleanly.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:  # 3P-2: reject crossed book
            return None

        last_bid = state["last_bid"]
        last_ask = state["last_ask"]

        is_flicker = False
        if last_bid is not None:
            d_bid = _sign(bid - last_bid)
            if d_bid != 0:
                if state["last_bid_dir"] != 0 and d_bid == -state["last_bid_dir"]:
                    is_flicker = True
                state["last_bid_dir"] = d_bid
            d_ask = _sign(ask - last_ask)
            if d_ask != 0:
                if state["last_ask_dir"] != 0 and d_ask == -state["last_ask_dir"]:
                    is_flicker = True
                state["last_ask_dir"] = d_ask

        state["last_bid"] = bid
        state["last_ask"] = ask

        ts = event.timestamp_ns
        events = state["events"]
        events.append((ts, is_flicker))
        if is_flicker:
            state["flicker_count"] += 1

        cutoff = ts - self._window_ns
        while events and events[0][0] < cutoff:
            _t, was_flicker = events.popleft()
            if was_flicker:
                state["flicker_count"] -= 1

        n = len(events)
        value = state["flicker_count"] / float(n) if n > 0 else 0.0
        warm = n >= self._min_quotes

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
