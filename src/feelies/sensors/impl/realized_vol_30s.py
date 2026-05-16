"""Realized volatility over a sliding event-time window.

Computes the **sample standard deviation** (Bessel-corrected) of mid-price
log-returns over the last ``window_seconds`` of quotes via a Welford
sliding-window mean/M2 accumulator (Pébay 2008):

    r_i        = log(mid_i / mid_{i-1})
    M2 / (n-1) = sample variance (unbiased)
    rv_t       = sqrt( max(0, M2 / (n-1)) )

The Welford forward + reverse update avoids the catastrophic cancellation
of the ``Σr² − (Σr)²/n`` "shortcut" formula, which is critical here because
log-returns are tiny (~1e-5 over 30s) and naïve cancellation eats several
digits of precision over a full session.  Mirrors the pattern used in
``spread_z_30d`` for the same reason.

For ``n < 2`` returns inside the trailing window, ``value = 0.0``.

Unannualised — consumers may multiply by ``sqrt(seconds_per_year / window_seconds)``
if they need an annualised scale.

Windowing is **event-time** via ``(ts_ns, log_ret)`` and a deque eviction
policy aligned to ``window_seconds * 1e9`` ns — robust to bursty streams.

Determinism: purely ``math.log`` / ``math.sqrt``.  No RNG, no clock reads.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class RealizedVol30sSensor:
    """Realized volatility over a sliding event-time window.

    Parameters:

    - ``window_seconds`` (int, default 30): trailing window in
      seconds.  Despite the class name, the actual window is
      configurable; the default reflects the canonical 30-second
      bucket from the alpha catalog.
    - ``warm_after`` (int, default 16): minimum number of returns
      observed before ``warm=True``.  16 corresponds to roughly 1.5
      seconds at typical 10Hz quote frequency, enough to compute a
      meaningful local std.
    """

    sensor_id: str = "realized_vol_30s"
    sensor_version: str = "1.2.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 30,
        warm_after: int = 16,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = int(window_seconds) * 1_000_000_000
        self._warm_after = warm_after

    def initial_state(self) -> dict[str, Any]:
        return {
            "history": deque(),  # (ts_ns, log_ret)
            "n": 0,       # Welford element count (== len(history))
            "mean": 0.0,  # Welford running mean of log-returns
            "M2": 0.0,    # Welford sum of squared deviations from mean
            "last_mid": None,
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
        if bid <= 0.0 or ask <= 0.0:
            return None
        mid = (bid + ask) / 2.0
        ts = event.timestamp_ns
        last_mid = state["last_mid"]

        if last_mid is not None and last_mid > 0.0:
            log_ret = math.log(mid / last_mid)
            history: deque[tuple[int, float]] = state["history"]

            # Welford forward add for the incoming log-return.
            n_new = state["n"] + 1
            delta = log_ret - state["mean"]
            state["mean"] += delta / n_new
            delta2 = log_ret - state["mean"]
            state["M2"] += delta * delta2
            state["n"] = n_new
            history.append((ts, log_ret))

            # Reverse-Welford eviction of expired returns (Pébay 2008).
            cutoff = ts - self._window_ns
            while history and history[0][0] < cutoff:
                _, x_old = history.popleft()
                n_cur = state["n"]
                mean_cur = state["mean"]
                if n_cur > 1:
                    mean_without = (n_cur * mean_cur - x_old) / (n_cur - 1)
                    state["M2"] -= (x_old - mean_cur) * (x_old - mean_without)
                    state["mean"] = mean_without
                else:
                    state["mean"] = 0.0
                    state["M2"] = 0.0
                state["n"] -= 1

            n = state["n"]
            if n < 2:
                value = 0.0
            else:
                var = max(0.0, state["M2"] / float(n - 1))
                value = math.sqrt(var)
        else:
            value = 0.0

        state["last_mid"] = mid

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=len(state["history"]) >= self._warm_after,  # S3: window-bounded len un-warms after gaps
        )
