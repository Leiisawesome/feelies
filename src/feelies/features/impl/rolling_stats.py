"""Count-bounded rolling z-score and percentile features.

Warm readings enter a FIFO window. Z-scores use the latest value and clamp to
``±_MAX_ZSCORE``; percentiles use Hazen's ``(rank - 0.5) / n`` plotting
position. Both return neutral, cold values until ``min_samples`` is reached.
Finalization is O(window size) and deterministic.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading

_logger = logging.getLogger(__name__)

# Bounded z-score envelope (±10) so near-zero early-session variance
# cannot poison downstream signals.
_MAX_ZSCORE = 10.0


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
    tuple_sum_component_indices:
        When set, a tuple-valued ``SensorReading.value`` is reduced to the
        sum of the listed components (e.g. Hawkes ``(λ_buy, λ_sell, …)``
        → ``λ_buy + λ_sell``).  When ``None`` (default), non-scalar values
        are ignored — use :class:`TupleComponentFeature` for single-index
        extraction instead.
    """

    feature_version: str = "1.1.0"

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        feature_id: str | None = None,
        min_samples: int = 30,
        max_samples: int = 2000,
        tuple_sum_component_indices: tuple[int, ...] | None = None,
    ) -> None:
        # Sample variance needs two observations; finalize treats n=1 as constant.
        if min_samples < 1:
            raise ValueError(f"RollingZscoreFeature: min_samples must be >= 1, got {min_samples}")
        if max_samples < min_samples:
            raise ValueError(
                f"RollingZscoreFeature: max_samples ({max_samples}) "
                f"must be >= min_samples ({min_samples})"
            )
        self.feature_id: str = feature_id if feature_id is not None else f"{sensor_id}_zscore"
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._tuple_sum_component_indices = tuple_sum_component_indices
        # Warn once for each input category that would otherwise stay silently cold.
        self._warned_categories: set[str] = set()

    def _warn_once(self, category: str, detail: str) -> None:
        if category in self._warned_categories:
            return
        self._warned_categories.add(category)
        _logger.warning(
            "RollingZscoreFeature(feature_id=%r, sensor=%r): %s; this "
            "feature will stay cold until configuration is corrected.",
            self.feature_id,
            self.input_sensor_ids[0],
            detail,
        )

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
        v_raw = reading.value
        idxs = self._tuple_sum_component_indices
        if isinstance(v_raw, tuple):
            if idxs is None:
                self._warn_once(
                    "tuple_without_indices",
                    "sensor delivered a tuple value but "
                    "tuple_sum_component_indices is None — configure "
                    "the indices or use TupleComponentFeature",
                )
                return
            acc = 0.0
            for i in idxs:
                if i >= len(v_raw):
                    self._warn_once(
                        "index_out_of_range",
                        f"tuple_sum_component_indices includes {i} but "
                        f"sensor value has only {len(v_raw)} components",
                    )
                    return
                acc += float(v_raw[i])
            v = acc
        else:
            if idxs is not None:
                self._warn_once(
                    "scalar_with_indices",
                    "tuple_sum_component_indices is set but sensor "
                    "delivered a scalar value — drop the indices kwarg",
                )
                return
            v = float(v_raw)
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
        # One observation has undefined sample variance; treat it as constant.
        if n < 2:
            return 0.0, True, False
        mean = sum(vals) / n
        # Bessel-corrected sample variance; ``n - 1 >= 1`` here.
        var = sum((x - mean) ** 2 for x in vals) / (n - 1)
        std = var**0.5
        if std < 1e-10:
            # Constant sensor — z-score is undefined; return warm, value 0.
            return 0.0, True, False
        latest = vals[-1]
        # Bound the z-score envelope (±_MAX_ZSCORE).  Without this, a
        # sensor with std just above 1e-10 can produce values that poison
        # downstream signals; the absolute std floor cannot scale with
        # sensor magnitude, so the clamp is the second line of defence.
        z = (latest - mean) / std
        if z > _MAX_ZSCORE:
            return _MAX_ZSCORE, True, False
        if z < -_MAX_ZSCORE:
            return -_MAX_ZSCORE, True, False
        return z, True, False


class RollingPercentileFeature:
    """Rolling window percentile rank (Hazen plotting position).

    Returns ``(rank - 0.5) / n`` where
    ``rank = |{x in window : x <= latest}|`` and ``latest`` is the most
    recently observed warm reading.

    The Hazen formula replaces naive ``rank / n``: because
    ``latest`` itself is always in the window, ``rank`` is always at
    least 1, so ``rank / n`` had a minimum reachable value of ``1/n``
    (≈ 0.033 at ``min_samples=30``) — a threshold at "percentile < 0.05"
    could never fire even for the global minimum.  The Hazen form is
    symmetric around 0.5 and bounded to ``[1/(2n), 1 - 1/(2n)]``.

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
        Minimum warm readings before returning ``warm=True``.  Must be
        >= 1 (a single sample produces percentile 0.5 by Hazen).
    max_samples:
        FIFO window ceiling.
    """

    feature_version: str = "1.1.0"

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        feature_id: str | None = None,
        min_samples: int = 30,
        max_samples: int = 2000,
    ) -> None:
        if min_samples < 1:
            raise ValueError(
                f"RollingPercentileFeature: min_samples must be >= 1, got {min_samples}"
            )
        if max_samples < min_samples:
            raise ValueError(
                f"RollingPercentileFeature: max_samples ({max_samples}) "
                f"must be >= min_samples ({min_samples})"
            )
        self.feature_id: str = feature_id if feature_id is not None else f"{sensor_id}_percentile"
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._warned_categories: set[str] = set()

    def _warn_once(self, category: str, detail: str) -> None:
        if category in self._warned_categories:
            return
        self._warned_categories.add(category)
        _logger.warning(
            "RollingPercentileFeature(feature_id=%r, sensor=%r): %s; "
            "this feature will stay cold until configuration is corrected.",
            self.feature_id,
            self.input_sensor_ids[0],
            detail,
        )

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
            # Extract tuple inputs with TupleComponentFeature before rolling stats.
            self._warn_once(
                "tuple_value",
                "sensor delivered a tuple value; "
                "RollingPercentileFeature only supports scalars — "
                "feed it through TupleComponentFeature first",
            )
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
        # Hazen plotting position gives a debiased empirical CDF.
        return (rank - 0.5) / n, True, False


__all__ = ["RollingZscoreFeature", "RollingPercentileFeature"]
