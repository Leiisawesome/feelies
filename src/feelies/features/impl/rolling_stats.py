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
    Z-score of the latest reading: ``(latest - mean) / std``, clamped
    to ``[-_MAX_ZSCORE, +_MAX_ZSCORE]`` (audit #5) so near-zero variance
    early in the window cannot produce unbounded values that poison
    downstream signals.  Returns ``(0.0, False, False)`` during warm-up;
    ``(0.0, True, False)`` when std < 1e-10 (constant sensor; z-score
    undefined).

:class:`RollingPercentileFeature`
    Hazen plotting position of the latest reading: ``(rank - 0.5) / n``
    where ``rank = |{x in window : x <= latest}|`` (audit #9).  This
    debiases the naive ``rank / n`` formula whose minimum reachable
    value was ``1/n`` because ``latest`` itself is always counted in
    ``rank``; the Hazen form is symmetric around 0.5 and maps to
    ``[1/(2n), 1 - 1/(2n)]``.  Returns ``(0.5, False, False)`` during
    warm-up (neutral prior).

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

import logging
from collections import deque
from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading

_logger = logging.getLogger(__name__)

# Audit #5: same clamp as ``feelies.features.library.ZScoreComputation``
# — keep the two paths symmetric so a signal wired through either
# computes the same bounded z-score envelope.
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
        # Audit #10: sample variance with Bessel's correction requires
        # n >= 2.  The previous code used ``max(n - 1, 1)`` to silently
        # mask the n=1 edge; we now branch on it explicitly in
        # ``finalize`` (n=1 → std undefined → constant-sensor path).
        if min_samples < 1:
            raise ValueError(
                f"RollingZscoreFeature: min_samples must be >= 1, "
                f"got {min_samples}"
            )
        if max_samples < min_samples:
            raise ValueError(
                f"RollingZscoreFeature: max_samples ({max_samples}) "
                f"must be >= min_samples ({min_samples})"
            )
        self.feature_id: str = (
            feature_id if feature_id is not None else f"{sensor_id}_zscore"
        )
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._tuple_sum_component_indices = tuple_sum_component_indices
        # Audit #18: track silent-drop categories so misconfigurations
        # surface in operator logs instead of producing perpetually-cold
        # features without explanation.  Each warning fires at most once
        # per feature instance per category.
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
        # Audit #10: with n=1, sample variance is undefined.  Treat it
        # the same as a constant sensor (warm, value 0) so the math is
        # explicit rather than hidden behind ``max(n - 1, 1)``.
        if n < 2:
            return 0.0, True, False
        mean = sum(vals) / n
        # Bessel-corrected sample variance; ``n - 1 >= 1`` here.
        var = sum((x - mean) ** 2 for x in vals) / (n - 1)
        std = var ** 0.5
        if std < 1e-10:
            # Constant sensor — z-score is undefined; return warm, value 0.
            return 0.0, True, False
        latest = vals[-1]
        # Audit #5: bound the z-score envelope.  Matches the clamp in
        # ``feelies.features.library.ZScoreComputation``.  Without this,
        # a sensor with std just above 1e-10 and a small numerator can
        # produce values in the 1e7 range that poison downstream signals;
        # the absolute std floor cannot scale with sensor magnitude, so
        # the clamp is the second line of defence.
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

    The Hazen formula (audit #9) replaces the naive ``rank / n``: because
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
                f"RollingPercentileFeature: min_samples must be >= 1, "
                f"got {min_samples}"
            )
        if max_samples < min_samples:
            raise ValueError(
                f"RollingPercentileFeature: max_samples ({max_samples}) "
                f"must be >= min_samples ({min_samples})"
            )
        self.feature_id: str = (
            feature_id if feature_id is not None else f"{sensor_id}_percentile"
        )
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
            # Audit #18: tuple-valued sensors are not supported here —
            # use a TupleComponentFeature to extract a scalar first.
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
        # Hazen plotting position (audit #9): debiased empirical CDF.
        return (rank - 0.5) / n, True, False


__all__ = ["RollingZscoreFeature", "RollingPercentileFeature"]
