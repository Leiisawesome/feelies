"""Online z-score of bid-ask spread over a configurable rolling window.

Computes the standardized residual of the current spread against a
rolling Welford mean/variance over the last ``window`` quotes:

    spread_t = ask_t - bid_t
    z_t      = (spread_t - mean_t) / sqrt(var_t)

Despite the historical "30d" naming (matching the legacy alpha
catalog's window terminology) the actual window is bounded by quote
count, not wall-clock days, so the sensor behaves identically in
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

from feelies.core.events import NBBOQuote, SensorReading, Trade


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
    """

    sensor_id: str = "spread_z_30d"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window: int = 6000,
        warm_after: int | None = None,
        min_std: float = 1e-9,
    ) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if min_std <= 0.0:
            raise ValueError(f"min_std must be > 0, got {min_std}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window = window
        self._warm_after = window if warm_after is None else warm_after
        self._min_std = min_std

    def initial_state(self) -> dict[str, Any]:
        return {
            "spreads": deque(maxlen=self._window),
            "n": 0,       # Welford element count (== len(spreads))
            "mean": 0.0,  # Welford running mean
            "M2": 0.0,    # Welford sum of squared deviations from mean
            "count": 0,   # monotonic insert counter (for warm legacy compat)
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None

        spread = float(event.ask) - float(event.bid)
        spreads: deque[float] = state["spreads"]

        # S14: Welford sliding-window variance (Pébay 2008).
        # If the deque is full, the oldest element will be evicted
        # by the append below; remove it from the Welford accumulators first.
        if len(spreads) == spreads.maxlen:
            x_old = spreads[0]
            n_cur = state["n"]  # == len(spreads) == maxlen
            mean_cur = state["mean"]
            if n_cur > 1:
                mean_without = (n_cur * mean_cur - x_old) / (n_cur - 1)
                state["M2"] -= (x_old - mean_cur) * (x_old - mean_without)
                state["mean"] = mean_without
            else:
                state["mean"] = 0.0
                state["M2"] = 0.0
            state["n"] -= 1

        # Welford add for the incoming spread.
        n_new = state["n"] + 1
        delta = spread - state["mean"]
        state["mean"] += delta / n_new
        delta2 = spread - state["mean"]
        state["M2"] += delta * delta2
        state["n"] = n_new

        spreads.append(spread)  # evicts oldest when maxlen is hit
        state["count"] += 1

        n = state["n"]  # == len(spreads)
        if n < 2:
            value = 0.0
        else:
            # Population variance: M2/n (consistent with prior formula)
            var = max(0.0, state["M2"] / n)
            std = math.sqrt(var)
            if std < self._min_std:
                value = 0.0
            else:
                value = (spread - state["mean"]) / std

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=len(spreads) >= self._warm_after,  # S3: len un-warms after window empties
        )
