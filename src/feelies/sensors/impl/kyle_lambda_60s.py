"""Kyle's lambda — price-impact regression over a rolling window.

Kyle (1985) λ measures the price-impact coefficient of net order
flow.  A practical estimator over a rolling event-time window of
trades is:

    Δp_t = λ * Δq_t + ε_t

where ``Δp_t`` is the trade-to-trade mid-price change and ``Δq_t`` is
signed trade size (buy positive, sell negative; tick rule used to
classify).  We solve the OLS slope online via maintained sums:

    λ = (n * Σ(Δp Δq) - Σ Δp * Σ Δq) /
        (n * Σ(Δq²) - (Σ Δq)²)

The window is event-time bounded by ``window_seconds``; samples
older than ``trade.timestamp_ns - window_seconds * 1e9`` are popped
off the deque tail and their contribution removed from the running
sums (Welford-style decremental update).

Returns ``λ`` (float) on every trade after the first; ``warm`` is
true once at least ``min_samples`` samples are in the window.

Determinism: incremental running sums.  Numerical drift over long
windows is bounded by the deque length cap (~window_seconds * trade
rate); we recompute from scratch when the deque empties to anchor
the sums to zero exactly.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class KyleLambda60sSensor:
    """Kyle's lambda over a 60-second rolling window of trades.

    Parameters:

    - ``window_seconds`` (int, default 60): event-time window in
      seconds.
    - ``min_samples`` (int, default 30): minimum trades in the
      window before ``warm=True``.
    """

    sensor_id: str = "kyle_lambda_60s"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 60,
        min_samples: int = 30,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if min_samples < 2:
            raise ValueError(
                f"min_samples must be >= 2 (need 2+ for OLS slope), "
                f"got {min_samples}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_samples = min_samples

    def initial_state(self) -> dict[str, Any]:
        return {
            "samples": deque(),  # (ts_ns, dp, dq)
            "sum_dp": 0.0,
            "sum_dq": 0.0,
            "sum_dp_dq": 0.0,
            "sum_dq2": 0.0,
            "last_trade_price": None,
            "last_side": +1,
            "last_nbbo_mid": None,
            "mid_at_prev_trade": None,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if isinstance(event, NBBOQuote):
            bid = float(event.bid)
            ask = float(event.ask)
            if bid <= 0.0 or ask <= 0.0:
                return None
            state["last_nbbo_mid"] = (bid + ask) / 2.0
            return None

        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = float(event.size)
        if size <= 0.0:
            return None

        mid_now = state["last_nbbo_mid"]
        if mid_now is None:
            return None

        last_trade_price = state["last_trade_price"]
        if last_trade_price is None:
            state["last_trade_price"] = price
            state["mid_at_prev_trade"] = mid_now
            return None

        if price > last_trade_price:
            side = +1
        elif price < last_trade_price:
            side = -1
        else:
            side = state["last_side"]
        state["last_side"] = side

        mid_prev = state["mid_at_prev_trade"]
        if mid_prev is None:
            return None

        dp = mid_now - mid_prev
        dq = side * size

        samples = state["samples"]
        samples.append((event.timestamp_ns, dp, dq))
        state["sum_dp"] += dp
        state["sum_dq"] += dq
        state["sum_dp_dq"] += dp * dq
        state["sum_dq2"] += dq * dq

        cutoff = event.timestamp_ns - self._window_ns
        while samples and samples[0][0] < cutoff:
            _ts, old_dp, old_dq = samples.popleft()
            state["sum_dp"] -= old_dp
            state["sum_dq"] -= old_dq
            state["sum_dp_dq"] -= old_dp * old_dq
            state["sum_dq2"] -= old_dq * old_dq

        n = len(samples)
        # Anchor sums to exactly zero when the window empties — keeps
        # numerical drift bounded over long sessions.
        if n == 0:
            state["sum_dp"] = 0.0
            state["sum_dq"] = 0.0
            state["sum_dp_dq"] = 0.0
            state["sum_dq2"] = 0.0

        state["mid_at_prev_trade"] = mid_now
        state["last_trade_price"] = price

        denom = n * state["sum_dq2"] - state["sum_dq"] * state["sum_dq"]
        if n < 2 or denom <= 0.0:
            value = 0.0
            warm = False
        else:
            numer = n * state["sum_dp_dq"] - state["sum_dp"] * state["sum_dq"]
            value = numer / denom
            warm = n >= self._min_samples

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
