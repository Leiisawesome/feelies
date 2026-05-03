"""Hawkes self-exciting trade-arrival intensity sensor (v0.3 §20.4.1).

Estimates the conditional buy- and sell-side trade arrival rates above
a baseline using two parallel exponentially-weighted self-exciting
kernels — one per side.  A jump in either intensity is the L1
fingerprint of the ``HAWKES_SELF_EXCITE`` mechanism family
(``design_docs/three_layer_architecture.md`` §20.2).

Algorithm (per side, incremental):

Between trades:    λ(t) = μ + (λ(t_last) - μ) · exp(-β · (t - t_last))
On a same-side trade at t_i:  λ(t_i) = λ(t_i⁻) + α
Between-side trades leave the side's λ unchanged except for the decay
above.

Outputs (length-4 tuple):

    SensorReading.value = (
        intensity_buy,        # λ_buy(t)  per second
        intensity_sell,       # λ_sell(t) per second
        intensity_ratio,      # max(buy, sell) / (buy + sell + ε); ∈ [0.5, 1]
        branching_ratio_est,  # α / β; constant under fixed params
    )

Determinism: pure float arithmetic; no RNG; ``math.exp`` over an
integer nanosecond delta is deterministic on IEEE-754.

Trade side classification: tick rule (price strictly above prior trade
price ⇒ buy; below ⇒ sell; equal ⇒ inherit prior side; default ``+1``
on the very first trade).  This avoids a dependency on the prevailing
NBBO so the sensor is robust to NBBO inversion / stale quotes.

Warm-up: ``warm = True`` once at least ``warm_trades_per_side`` trades
of *each* side have been observed within the rolling
``warm_window_seconds`` window.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade

_NS_PER_SECOND: float = 1_000_000_000.0
_EPS: float = 1e-12


class HawkesIntensitySensor:
    """Two-sided exponentially-weighted Hawkes intensity estimator.

    Parameters:

    - ``alpha`` (float, default 0.4): impulse magnitude added to a
      side's intensity on a same-side trade.  Typical range
      ``[0.05, 1.0]``.
    - ``beta`` (float, default 0.05): exponential decay rate (per
      second) of the intensity between trades.  Typical range
      ``[0.01, 0.5]``.  The branching ratio ``α/β`` must stay below 1
      for stability; values near 1 indicate self-sustaining cascades.
    - ``warm_window_seconds`` (int, default 60): event-time window
      used for the per-side trade-count warm-up criterion.
    - ``warm_trades_per_side`` (int, default 20): minimum trades on
      *each* side within ``warm_window_seconds`` before ``warm=True``.
    - ``baseline_mu`` (float, default ``0.0``): Hawkes background
      intensity μ (events / second) toward which both sides decay between
      impulses.  Must be non-negative.
    """

    sensor_id: str = "hawkes_intensity"
    sensor_version: str = "1.1.0"

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
            raise ValueError(
                f"warm_window_seconds must be > 0, got {warm_window_seconds}"
            )
        if warm_trades_per_side < 0:
            raise ValueError(
                f"warm_trades_per_side must be >= 0, got {warm_trades_per_side}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._warm_window_ns = warm_window_seconds * 1_000_000_000
        self._warm_per_side = warm_trades_per_side
        self._branching_ratio = self._alpha / self._beta
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
        if last_ts is None or ts_ns <= last_ts:
            state["last_ts_ns"] = ts_ns
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
    ) -> SensorReading | None:
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
            state["lambda_buy"] = state["lambda_buy"] + self._alpha  # S1: additive impulse; decay already applied by _decay_to
            state["buy_ts"].append(ts_ns)
        else:
            state["lambda_sell"] = state["lambda_sell"] + self._alpha  # S1: additive impulse
            state["sell_ts"].append(ts_ns)

        cutoff = ts_ns - self._warm_window_ns
        for q in (state["buy_ts"], state["sell_ts"]):
            while q and q[0] < cutoff:
                q.popleft()

        lam_buy = state["lambda_buy"]
        lam_sell = state["lambda_sell"]
        denom = lam_buy + lam_sell + _EPS
        intensity_ratio = max(lam_buy, lam_sell) / denom
        warm = (
            len(state["buy_ts"]) >= self._warm_per_side
            and len(state["sell_ts"]) >= self._warm_per_side
        )

        return SensorReading(
            timestamp_ns=ts_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=(lam_buy, lam_sell, intensity_ratio, self._branching_ratio),
            warm=warm,
        )
