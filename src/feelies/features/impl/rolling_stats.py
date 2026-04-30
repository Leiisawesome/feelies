"""Rolling statistical HorizonFeature implementations.

Computes rolling z-scores and percentile ranks of scalar sensor
readings at horizon boundaries.  These are the Layer-2 features that
give signal ``evaluate()`` functions statistically normalised views of
raw Layer-1 sensor outputs.

Both classes accumulate warm sensor readings in a bounded FIFO window
(``max_samples``) and compute their statistic on every
:class:`HorizonTick`.  They return ``warm=False`` until at least
``min_samples`` readings have been observed; the engine treats
``warm=False`` features as missing and the signal's ``evaluate()``
function typically returns ``None`` in that case.

:class:`RollingZscoreFeature`
    Z-score of the latest reading: ``(latest - mean) / std``.
    Returns ``(0.0, False, False)`` during warm-up; ``(0.0, True,
    False)`` when std < 1e-10 (constant sensor, z-score undefined).

:class:`RollingPercentileFeature`
    Fraction of rolling values ≤ latest: ``rank / n``.
    Returns ``(0.5, False, False)`` during warm-up (neutral prior).

Determinism
-----------
Both implementations use only the FIFO window contents and arithmetic
that is associative over float64 — identical event sequences produce
identical outputs on every platform (Inv-5).

Performance note
----------------
``sum()`` and the rank count in ``finalize()`` are O(n) in the window
size.  At ``max_samples=2000`` and one finalize per horizon boundary
(every 30–1800 seconds in production), this is comfortably within
budget.  For real-time deployments with sub-second horizons, switch to
Welford's online algorithm or a sorted-list structure.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading


class RollingZscoreFeature:
    """Rolling window z-score of a scalar sensor.

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    horizon_seconds:
        Which horizon boundary this feature contributes to.
    feature_id:
        Key in ``HorizonFeatureSnapshot.values``.  Defaults to
        ``f"{sensor_id}_zscore"``.
    min_samples:
        Minimum warm readings before returning ``warm=True``.
    max_samples:
        FIFO window ceiling.  Older readings are silently dropped.
    """

    feature_version: str = "1.0.0"

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        feature_id: str | None = None,
        min_samples: int = 30,
        max_samples: int = 2000,
    ) -> None:
        self.feature_id: str = (
            feature_id if feature_id is not None else f"{sensor_id}_zscore"
        )
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._min_samples = min_samples
        self._max_samples = max_samples

    def initial_state(self) -> dict[str, Any]:
        return {"vals": deque(maxlen=self._max_samples)}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if not reading.warm:
            return
        v = reading.value
        if isinstance(v, tuple):
            return
        state["vals"].append(float(v))

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        vals: deque[float] = state["vals"]
        n = len(vals)
        if n < self._min_samples:
            return 0.0, False, False
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-10:
            # Constant sensor — z-score is undefined; return warm, value 0.
            return 0.0, True, False
        latest = vals[-1]
        return (latest - mean) / std, True, False


class RollingPercentileFeature:
    """Rolling window percentile rank of the latest scalar sensor reading.

    Returns the fraction of historical values that are ≤ the latest
    value, i.e. the empirical CDF evaluated at the latest reading.  A
    value of 0.8 means the current reading is at the 80th percentile
    of its recent history.

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    horizon_seconds:
        Which horizon boundary this feature contributes to.
    feature_id:
        Key in ``HorizonFeatureSnapshot.values``.  Defaults to
        ``f"{sensor_id}_percentile"``.
    min_samples:
        Minimum warm readings before returning ``warm=True``.
    max_samples:
        FIFO window ceiling.
    """

    feature_version: str = "1.0.0"

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        feature_id: str | None = None,
        min_samples: int = 30,
        max_samples: int = 2000,
    ) -> None:
        self.feature_id: str = (
            feature_id if feature_id is not None else f"{sensor_id}_percentile"
        )
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._min_samples = min_samples
        self._max_samples = max_samples

    def initial_state(self) -> dict[str, Any]:
        return {"vals": deque(maxlen=self._max_samples)}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if not reading.warm:
            return
        v = reading.value
        if isinstance(v, tuple):
            return
        state["vals"].append(float(v))

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        vals: deque[float] = state["vals"]
        n = len(vals)
        if n < self._min_samples:
            return 0.5, False, False
        latest = vals[-1]
        rank = sum(1 for v in vals if v <= latest)
        return rank / n, True, False


__all__ = ["RollingZscoreFeature", "RollingPercentileFeature"]
