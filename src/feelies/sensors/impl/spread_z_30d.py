"""Online z-score of bid-ask spread over a configurable rolling window.

Computes the standardized residual of the current spread against a
rolling Welford mean/variance over the last ``window`` quotes:

    spread_t = ask_t - bid_t
    z_t      = (spread_t - mean_t) / sqrt(var_t)

Despite the ``30d`` name, the window is bounded by quote count rather than
days, so the sensor behaves identically in
backtest and live trading (Inv-9).  The default ``window`` of 6_000
quotes is roughly 10 minutes at typical equity-market depth and is
enough to estimate the spread distribution stably across the trading
day.

Implementation: maintain a fixed-size deque of recent spreads and
Welford online mean/M2 statistics.  The incremental Welford sliding-
window variant (Pébay 2008) avoids catastrophic cancellation in the
numerically equivalent but unstable ``sum_sq/n - mean²`` formula;
the computational overhead is negligible (two float ops per event).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class SpreadZScoreSensor:
    """Rolling z-score of the bid-ask spread.

    Parameters:

    - ``window`` (int, default 6000): rolling-window size in quotes.
    - ``warm_after`` (int, default ``window``): minimum number of
      quotes before ``warm=True``.  Defaults to a full window so the
      first emitted z-score is meaningful.
    - ``min_std`` (float, default 1e-9): floor on the rolling
      standard deviation; below this we emit ``value=0.0`` to avoid
      pathological z-scores in degenerate (constant-spread) books.
    - ``max_gap_seconds`` (int | None, default None): event-time staleness
      reset. This is a count-window sensor, so
      unlike the event-time-windowed sensors it cannot un-warm on its
      own — once the 6000-quote deque fills it stays warm and keeps
      z-scoring against a distribution that may predate a halt.  When set,
      an inter-quote gap longer than ``max_gap_seconds`` (e.g. a LULD
      halt) flushes the rolling window so the post-gap z-score is built
      against post-gap data, and the sensor correctly reverts to cold
      until ``warm_after`` fresh quotes accumulate. ``None`` disables gap
      resets.
    """

    sensor_id: str = "spread_z_30d"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window: int = 6000,
        warm_after: int | None = None,
        min_std: float = 1e-9,
        max_gap_seconds: int | None = None,
    ) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if min_std <= 0.0:
            raise ValueError(f"min_std must be > 0, got {min_std}")
        if max_gap_seconds is not None and max_gap_seconds <= 0:
            raise ValueError(f"max_gap_seconds must be > 0 or None, got {max_gap_seconds}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window = window
        self._warm_after = window if warm_after is None else warm_after
        self._min_std = min_std
        self._max_gap_ns = None if max_gap_seconds is None else max_gap_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "spreads": deque(maxlen=self._window),
            "n": 0,  # Welford element count (== len(spreads))
            "mean": 0.0,  # Welford running mean
            "M2": 0.0,  # Welford sum of squared deviations from mean
            "last_ts_ns": None,  # event time of the previous accepted quote
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
        # Validate positive prices consistently across price-consuming
        # sensors.  A zero/negative side gives a nonsense spread and
        # would poison the rolling mean/variance.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            return None

        # After a long gap, rebuild the window from post-gap data and return cold.
        ts_ns = event.timestamp_ns
        last_ts = state["last_ts_ns"]
        if (
            self._max_gap_ns is not None
            and last_ts is not None
            and (ts_ns - last_ts) > self._max_gap_ns
        ):
            state["spreads"].clear()
            state["n"] = 0
            state["mean"] = 0.0
            state["M2"] = 0.0
        state["last_ts_ns"] = ts_ns

        spread = ask - bid
        spreads: deque[float] = state["spreads"]

        # Remove the evicted value from Welford state before appending.
        if len(spreads) == spreads.maxlen:
            x_old = spreads[0]
            n_cur = state["n"]  # == len(spreads) == maxlen >= 2
            mean_cur = state["mean"]
            mean_without = (n_cur * mean_cur - x_old) / (n_cur - 1)
            state["M2"] -= (x_old - mean_cur) * (x_old - mean_without)
            state["mean"] = mean_without
            state["n"] -= 1

        # Welford add for the incoming spread.
        n_new = state["n"] + 1
        delta = spread - state["mean"]
        state["mean"] += delta / n_new
        delta2 = spread - state["mean"]
        state["M2"] += delta * delta2
        state["n"] = n_new

        spreads.append(spread)  # evicts oldest when maxlen is hit

        n = state["n"]  # == len(spreads)
        if n < 2:
            value = 0.0
        else:
            # Population variance (M2/n), not Bessel-corrected.  For the
            # default window=6000 the difference vs M2/(n-1) is ~0.008%,
            # and downstream consumers treat this as a standardised score
            # rather than an unbiased point estimate.  The locked-vector
            # tests pin this convention.
            var = max(0.0, state["M2"] / n)
            std = math.sqrt(var)
            if std < self._min_std:
                value = 0.0
            else:
                value = (spread - state["mean"]) / std

        # Deque has maxlen=window with FIFO eviction; once the window
        # fills, ``len`` stays at ``window`` for the lifetime of the
        # state.  (Unlike the event-time-windowed sensors, this one
        # cannot become cold without an explicit gap reset.)
        return SensorEmission(
            value=value,
            warm=len(spreads) >= self._warm_after,
        )
