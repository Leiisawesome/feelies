"""Two-sided exponentially decayed trade-arrival intensity.

Each side decays toward ``mu`` at rate ``beta`` and receives an ``alpha``
impulse on a same-side trade. The output is buy intensity, sell intensity,
dominant-side ratio, and configured ``alpha / beta``. These are impulse-EWMA
units, not fitted Hawkes arrival rates or a branching-ratio estimate.

Trade side follows the tick rule. Warm-up requires enough trades on both sides
within the rolling window. Processing is deterministic and uses no RNG.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission

_NS_PER_SECOND: float = 1_000_000_000.0
_EPS: float = 1e-12


class HawkesIntensitySensor:
    """Track two-sided trade intensity with exponential impulse decay.

    ``alpha`` is impulse size and ``beta`` is the per-second decay rate, with
    half-life ``ln(2)/beta``. The emitted ``alpha/beta`` is diagnostic, not a
    fitted Hawkes branching ratio. Warmth requires enough trades on each side.
    """

    sensor_id: str = "hawkes_intensity"
    sensor_version: str = "1.2.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        alpha: float = 0.4,
        beta: float = 0.05,
        warm_window_seconds: int = 60,
        warm_trades_per_side: int = 20,
        baseline_mu: float = 0.0,
    ) -> None:
        if alpha <= 0.0:
            raise ValueError(f"alpha must be > 0, got {alpha}")
        if beta <= 0.0:
            raise ValueError(f"beta must be > 0, got {beta}")
        if baseline_mu < 0.0:
            raise ValueError(f"baseline_mu must be >= 0, got {baseline_mu}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if warm_trades_per_side < 0:
            raise ValueError(f"warm_trades_per_side must be >= 0, got {warm_trades_per_side}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._warm_window_ns = warm_window_seconds * 1_000_000_000
        self._warm_per_side = warm_trades_per_side
        # Configured impulse-decay ratio (α / β), not an on-line estimate and
        # not a Hawkes branching-ratio stability metric (see module docstring).
        # Emitted verbatim on every reading.
        self._impulse_decay_ratio = self._alpha / self._beta
        self._baseline_mu = float(baseline_mu)

    def initial_state(self) -> dict[str, Any]:
        mu0 = self._baseline_mu
        return {
            "lambda_buy": mu0,
            "lambda_sell": mu0,
            "last_ts_ns": None,
            "last_price": None,
            "last_side": +1,
            "buy_ts": deque(),
            "sell_ts": deque(),
        }

    def _decay_to(self, state: dict[str, Any], ts_ns: int) -> None:
        last_ts = state["last_ts_ns"]
        if last_ts is None:
            state["last_ts_ns"] = ts_ns
            return
        if ts_ns == last_ts:
            # Same-instant event: no decay to apply, no anchor to advance.
            return
        if ts_ns < last_ts:
            # Strictly backwards event (shouldn't happen under monotonic
            # per-symbol delivery, but guard regardless).  Rewinding
            # ``last_ts_ns`` would double-count decay on the next forward
            # event; leave state untouched.
            return
        dt_s = (ts_ns - last_ts) / _NS_PER_SECOND
        decay = math.exp(-self._beta * dt_s)
        mu = self._baseline_mu
        state["lambda_buy"] = mu + (state["lambda_buy"] - mu) * decay
        state["lambda_sell"] = mu + (state["lambda_sell"] - mu) * decay
        state["last_ts_ns"] = ts_ns

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, Trade):
            return None
        if event.size <= 0:
            return None

        ts_ns = event.timestamp_ns
        self._decay_to(state, ts_ns)

        price = float(event.price)
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

        if side > 0:
            state["lambda_buy"] = (
                state["lambda_buy"] + self._alpha
            )  # Additive impulse; decay already applied by ``_decay_to``.
            state["buy_ts"].append(ts_ns)
        else:
            state["lambda_sell"] = state["lambda_sell"] + self._alpha  # Additive impulse.
            state["sell_ts"].append(ts_ns)

        cutoff = ts_ns - self._warm_window_ns
        for q in (state["buy_ts"], state["sell_ts"]):
            while q and q[0] < cutoff:
                q.popleft()

        lam_buy = state["lambda_buy"]
        lam_sell = state["lambda_sell"]
        total = lam_buy + lam_sell
        if total < _EPS:
            # No-information state (both sides below ε; happens at startup
            # when ``baseline_mu = 0`` and no trades have fired yet).
            # ``max / total`` would give 0/ε = 0 which violates the
            # documented [0.5, 1] range.  Emit the neutral midpoint.
            intensity_ratio = 0.5
        else:
            intensity_ratio = max(lam_buy, lam_sell) / total
        warm = (
            len(state["buy_ts"]) >= self._warm_per_side
            and len(state["sell_ts"]) >= self._warm_per_side
        )

        return SensorEmission(value=(lam_buy, lam_sell, intensity_ratio, self._impulse_decay_ratio), warm=warm)
