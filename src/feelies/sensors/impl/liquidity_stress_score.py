"""Unsigned top-of-book liquidity-stress alarm in ``[0, 1]``.

The score combines adverse spread and depth deviations from rolling Welford
baselines:

    spread_t  = ask_t - bid_t
    depth_t   = bid_size_t + ask_size_t
    z_spread  = (spread_t - mean(spread)) / std(spread)      # + = wider
    z_thin    = (mean(depth) - depth_t) / std(depth)         # + = thinner
    excess    = max(0, z_spread) + max(0, z_thin)            # one-sided
    score     = 1 - exp(-excess / k)                          # ∈ [0, 1]

Only adverse deviations contribute, so calm books stay near zero. This
exit-only signal becomes warm after ``warm_after`` quotes.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


def _recompute_from_window(state: dict[str, Any], prefix: str) -> None:
    """Exact two-pass mean/M2 over the live window (F2 drift reset).

    Mirrors ``spread_z_30d._recompute_from_window`` /
    ``HorizonWindowedFeature._recompute_from_window``.  Only invoked when a
    reverse-Welford removal drove M2 negative (a floating-point cancellation
    artifact), so on well-conditioned streams it is never reached and locked
    vectors are unaffected.
    """
    buf: deque[float] = state[prefix + "buf"]
    n = len(buf)
    if n == 0:
        state[prefix + "n"] = 0
        state[prefix + "mean"] = 0.0
        state[prefix + "M2"] = 0.0
        return
    mean = sum(buf) / n
    state[prefix + "mean"] = mean
    state[prefix + "M2"] = sum((v - mean) ** 2 for v in buf)
    state[prefix + "n"] = n


def _welford_push(state: dict[str, Any], prefix: str, x: float, window: int) -> None:
    """Add ``x`` to a fixed-size Welford window, evicting the oldest sample."""
    buf: deque[float] = state[prefix + "buf"]
    drift_dirty = False
    if len(buf) == window:
        x_old = buf[0]
        n_cur = state[prefix + "n"]  # == window >= 2
        mean_cur = state[prefix + "mean"]
        mean_without = (n_cur * mean_cur - x_old) / (n_cur - 1)
        state[prefix + "M2"] -= (x_old - mean_cur) * (x_old - mean_without)
        # F2 (sensor_review_2026-07-02): clamp *and* recompute (this helper
        # previously only clamped), matching spread_z_30d / horizon_windowed.
        if state[prefix + "M2"] < 0.0:
            state[prefix + "M2"] = 0.0
            drift_dirty = True
        state[prefix + "mean"] = mean_without
        state[prefix + "n"] -= 1

    n_new = state[prefix + "n"] + 1
    delta = x - state[prefix + "mean"]
    state[prefix + "mean"] += delta / n_new
    delta2 = x - state[prefix + "mean"]
    state[prefix + "M2"] += delta * delta2
    state[prefix + "n"] = n_new
    buf.append(x)  # evicts oldest at maxlen

    if drift_dirty:
        _recompute_from_window(state, prefix)


def _zscore(state: dict[str, Any], prefix: str, x: float, min_std: float) -> float:
    n = state[prefix + "n"]
    if n < 2:
        return 0.0
    var = max(0.0, state[prefix + "M2"] / n)  # population variance (as spread_z)
    std = math.sqrt(var)
    if std < min_std:
        return 0.0
    return float((x - state[prefix + "mean"]) / std)


class LiquidityStressScoreSensor:
    """Composite spread-widening + depth-thinning stress alarm in ``[0, 1]``.

    Parameters:

    - ``window`` (int, default 6000): rolling-window size in quotes for
      both the spread and depth baselines (~10 min at typical depth,
      matching ``spread_z_30d``).
    - ``warm_after`` (int, default ``window``): minimum quotes before
      ``warm=True``.
    - ``sensitivity`` (float, default 2.0): ``k`` in ``1 - exp(-excess/k)``;
      larger = less sensitive (more sigma needed for a given score).
    - ``min_std`` (float, default 1e-9): floor on a baseline std below
      which that axis contributes no z (degenerate constant book).
    - ``max_gap_seconds`` (int | None, default None): event-time staleness
      reset. Both baselines are count windows that cannot
      un-warm on their own; when set, an inter-quote gap longer than
      ``max_gap_seconds`` (e.g. a halt) flushes both axes so the post-gap
      score is built against post-gap data and the sensor reverts to cold.
      ``None`` disables gap resets.
    """

    sensor_id: str = "liquidity_stress_score"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window: int = 6000,
        warm_after: int | None = None,
        sensitivity: float = 2.0,
        min_std: float = 1e-9,
        max_gap_seconds: int | None = None,
    ) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if sensitivity <= 0.0:
            raise ValueError(f"sensitivity must be > 0, got {sensitivity}")
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
        self._sensitivity = float(sensitivity)
        self._min_std = min_std
        self._max_gap_ns = None if max_gap_seconds is None else max_gap_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "spread_buf": deque(maxlen=self._window),
            "spread_n": 0,
            "spread_mean": 0.0,
            "spread_M2": 0.0,
            "depth_buf": deque(maxlen=self._window),
            "depth_n": 0,
            "depth_mean": 0.0,
            "depth_M2": 0.0,
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
        # A degenerate side gives invalid spread and depth and would
        # poison the rolling baselines; drop it.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            return None

        # After a long gap, rebuild both windows from post-gap data.
        ts_ns = event.timestamp_ns
        last_ts = state["last_ts_ns"]
        if (
            self._max_gap_ns is not None
            and last_ts is not None
            and (ts_ns - last_ts) > self._max_gap_ns
        ):
            for prefix in ("spread_", "depth_"):
                state[prefix + "buf"].clear()
                state[prefix + "n"] = 0
                state[prefix + "mean"] = 0.0
                state[prefix + "M2"] = 0.0
        state["last_ts_ns"] = ts_ns

        spread = ask - bid
        depth = float(event.bid_size + event.ask_size)

        # Score against prior history before adding the incoming sample.
        z_spread = _zscore(state, "spread_", spread, self._min_std)
        z_thin = -_zscore(state, "depth_", depth, self._min_std)

        _welford_push(state, "spread_", spread, self._window)
        _welford_push(state, "depth_", depth, self._window)

        excess = max(0.0, z_spread) + max(0.0, z_thin)
        score = 1.0 - math.exp(-excess / self._sensitivity)

        warm = len(state["spread_buf"]) >= self._warm_after

        return SensorEmission(value=score, warm=warm)
