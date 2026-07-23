"""Page-Hinkley structural-break score over absolute mid-price returns.

The sensor reads NBBO quotes directly; it has no upstream sensor dependency.
For each sample it evicts expired observations, computes a past-only rolling
mean, and updates the one-sided cumulant::

    m = max(0, m + x - mean - drift_floor)
    score = min(1, m / alarm_threshold)

A rolling baseline favors abrupt changes; use a longer window for slower drift.
The reading becomes warm after both ``warm_samples`` observations and one full
window of event time. Processing is deterministic and uses no RNG.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission

_NS_PER_SECOND: int = 1_000_000_000


class StructuralBreakScoreSensor:
    """Page-Hinkley score over the absolute mid-price log-returns.

    Parameters:

    - ``window_seconds`` (int, default 3600): event-time width of the
      reference window.  Must be strictly positive.
    - ``alarm_threshold`` (float, default 0.05): page-Hinkley ``λ``;
      ``m_t / λ`` is clipped at 1.0 and reported as the score.
    - ``drift_floor`` (float, default 0.0): page-Hinkley ``δ``;
      tolerated drift that does not contribute to ``m``.
    - ``warm_samples`` (int, default 100): minimum samples in the
      reference window before ``warm=True``.
    """

    sensor_id: str = "structural_break_score"
    sensor_version: str = "1.2.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 3600,
        alarm_threshold: float = 0.05,
        drift_floor: float = 0.0,
        warm_samples: int = 100,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if alarm_threshold <= 0.0:
            raise ValueError(f"alarm_threshold must be > 0, got {alarm_threshold}")
        if drift_floor < 0.0:
            raise ValueError(f"drift_floor must be >= 0, got {drift_floor}")
        if warm_samples < 0:
            raise ValueError(f"warm_samples must be >= 0, got {warm_samples}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * _NS_PER_SECOND
        self._window_seconds = window_seconds
        self._alarm_threshold = alarm_threshold
        self._drift_floor = drift_floor
        self._warm_samples = warm_samples

    def initial_state(self) -> dict[str, Any]:
        return {
            "samples": deque(),  # (ts_ns, value)
            # Kahan-compensated running sum of in-window observables.
            # ``sum_c`` is the running compensation term that absorbs the
            # low-order bits lost in each add/sub, keeping the relative
            # error in ``sum`` near machine epsilon even after millions of
            # add/evict pairs in a multi-day continuous run.
            "sum": 0.0,
            "sum_c": 0.0,
            "m": 0.0,  # page-Hinkley running cumulant
            "last_mid": None,
        }

    @staticmethod
    def _kahan_add(state: dict[str, Any], x: float) -> None:
        """Numerically-stable ``state['sum'] += x``."""
        y = x - state["sum_c"]
        t = state["sum"] + y
        state["sum_c"] = (t - state["sum"]) - y
        state["sum"] = t

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
        if bid <= 0.0 or ask <= 0.0 or bid > ask:
            # Invalidate the carried mid so the next valid quote
            # bootstraps fresh rather than computing an observable that
            # spans the bad-data gap.
            state["last_mid"] = None
            return None
        mid = (bid + ask) / 2.0

        last_mid = state["last_mid"]
        state["last_mid"] = mid
        if last_mid is None or last_mid <= 0.0:
            return SensorEmission(value=0.0, warm=False)

        observable = abs(math.log(mid) - math.log(last_mid))

        ts_ns = event.timestamp_ns
        samples = state["samples"]
        cutoff = ts_ns - self._window_ns
        while samples and samples[0][0] < cutoff:
            _t, v = samples.popleft()
            self._kahan_add(state, -v)

        n_ref = len(samples)
        mu_ref = state["sum"] / float(n_ref) if n_ref > 0 else 0.0

        # Page-Hinkley up-test: reference mean excludes the current ``x_t``.
        new_m = max(0.0, state["m"] + (observable - mu_ref) - self._drift_floor)
        state["m"] = new_m
        score = min(1.0, new_m / self._alarm_threshold)

        samples.append((ts_ns, observable))
        self._kahan_add(state, observable)

        n = len(samples)
        warm = n >= self._warm_samples and (samples[-1][0] - samples[0][0]) >= self._window_ns

        return SensorEmission(value=score, warm=warm)
