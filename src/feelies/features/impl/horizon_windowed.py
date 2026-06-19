"""Horizon-time-windowed HorizonFeature implementations.

Unlike :mod:`feelies.features.impl.rolling_stats` — whose deques are
*count*-bounded (``max_samples``) and therefore independent of
``horizon_seconds`` — these features aggregate over the **actual
event-time window** ``[tick.ts - horizon_seconds, tick.ts]``.  The
horizon is finally a *window*, not just a *clock*: the same sensor at
horizon 30 s and 1800 s now produces genuinely different baselines, so
the G16 ``horizon / half_life`` binding has real effect (audit P1-1).

Design (mirrors the numerically-stable sensor pattern in
``sensors/impl/spread_z_30d.py`` and ``realized_vol_30s.py``):

- Per-symbol/per-horizon state holds an event-time deque of
  ``(ts_ns, x)`` plus **Welford** running ``mean`` / ``M2`` so the
  z-score / variance reducers avoid the catastrophic cancellation of
  the naive ``Σx²/n − mean²`` form.  This matters here because the
  ``micro_price`` reducer z-scores a price *level* (~$10²) whose
  variance is cents — naive accumulation eats most of the precision
  over a 1800 s window.
- ``observe`` folds each warm reading in and evicts (reverse-Welford)
  anything older than the window anchored at the *reading* ts (bounds
  memory under bursts).  ``finalize`` re-evicts anchored at the *tick*
  ts (correctness: a silent sensor's window must shrink at the
  boundary) and emits the reducer.

Reducers
--------
``last``   most recent in-window value (fast inventory / queue state)
``mean``   time-window mean (persistent imbalance, e.g. OFI drift)
``sum``    integrated value over the window (``mean * n``)
``rms``    ``sqrt(E[x²])`` over the window (realized-vol-style scale)
``zscore`` ``(latest - mean) / std`` clamped to ``±_MAX_ZSCORE``
``percentile`` Hazen plotting position ``(rank - 0.5) / n`` of the
           latest value within the window (rank-based; debiased CDF)
``delta``  ``latest - oldest`` over the window: the signed *drift* of
           the value across the horizon.  Level-invariant — for a
           level-valued sensor like ``micro_price`` this captures the
           directional tilt without leaking the absolute price level
           that a z-score of the raw level does (audit P1-9).

Determinism (Inv-5): insertion-ordered float arithmetic over the
event-time deque; no wall-clock, no RNG.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading

_logger = logging.getLogger(__name__)

_NS_PER_SECOND = 1_000_000_000
# Same clamp as rolling_stats / library so a near-zero-variance window
# cannot emit an unbounded z that poisons downstream signals (audit #5).
_MAX_ZSCORE = 10.0

_REDUCERS = frozenset({"last", "mean", "sum", "rms", "zscore", "percentile", "delta"})


class HorizonWindowedFeature:
    """Aggregate a scalar sensor over its true ``horizon_seconds`` window.

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    horizon_seconds:
        Both the snapshot boundary this feature contributes to **and**
        the trailing event-time window width.
    reducer:
        One of ``{"last", "mean", "sum", "rms", "zscore"}``.
    feature_id:
        Key in ``HorizonFeatureSnapshot.values``.  Defaults depend on
        the reducer (``f"{sensor_id}_zscore"`` etc.).
    min_samples:
        Minimum in-window readings before ``warm=True``.  Must be ``>= 2``
        for the ``zscore`` / ``rms`` reducers (variance needs 2 points).
    max_samples:
        Hard safety cap on retained readings (memory bound under bursty
        streams).  The *time* window is the primary evictor; this only
        bites pathological bursts.
    tuple_sum_component_indices:
        When the sensor emits a tuple, reduce it to the sum of these
        component indices before windowing (e.g. Hawkes ``λ_buy+λ_sell``).
    """

    feature_version: str = "1.0.0"

    _DEFAULT_SUFFIX = {
        "last": "",
        "mean": "_hmean",
        "sum": "_hsum",
        "rms": "_hrms",
        "zscore": "_zscore",
        "percentile": "_percentile",
        "delta": "_delta",
    }

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        reducer: str = "zscore",
        feature_id: str | None = None,
        min_samples: int = 20,
        max_samples: int = 50_000,
        tuple_sum_component_indices: tuple[int, ...] | None = None,
    ) -> None:
        if reducer not in _REDUCERS:
            raise ValueError(
                f"HorizonWindowedFeature: reducer must be one of "
                f"{sorted(_REDUCERS)}, got {reducer!r}"
            )
        needs_var = reducer in ("zscore", "rms")
        if min_samples < (2 if needs_var else 1):
            raise ValueError(
                f"HorizonWindowedFeature: min_samples must be >= "
                f"{2 if needs_var else 1} for reducer {reducer!r}, "
                f"got {min_samples}"
            )
        if max_samples < min_samples:
            raise ValueError(
                f"HorizonWindowedFeature: max_samples ({max_samples}) must "
                f"be >= min_samples ({min_samples})"
            )
        if horizon_seconds <= 0:
            raise ValueError(
                f"HorizonWindowedFeature: horizon_seconds must be > 0, got {horizon_seconds}"
            )
        suffix = self._DEFAULT_SUFFIX[reducer]
        self.feature_id: str = feature_id if feature_id is not None else f"{sensor_id}{suffix}"
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._reducer = reducer
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._window_ns = horizon_seconds * _NS_PER_SECOND
        self._tuple_idxs = tuple_sum_component_indices
        self._warned: set[str] = set()

    def _warn_once(self, category: str, detail: str) -> None:
        if category in self._warned:
            return
        self._warned.add(category)
        _logger.warning(
            "HorizonWindowedFeature(feature_id=%r, sensor=%r): %s; this "
            "feature will stay cold until configuration is corrected.",
            self.feature_id,
            self.input_sensor_ids[0],
            detail,
        )

    def initial_state(self) -> dict[str, Any]:
        return {
            "win": deque(),  # (ts_ns, x)
            "n": 0,
            "mean": 0.0,
            "M2": 0.0,
            # 3P-4: set when a reverse-Welford remove drives M2 negative (the
            # catastrophic-cancellation indicator); triggers an exact recompute.
            "_drift_dirty": False,
        }

    # ── Welford add / remove (sliding window) ────────────────────────

    @staticmethod
    def _welford_add(state: dict[str, Any], x: float) -> None:
        state["n"] += 1
        delta = x - state["mean"]
        state["mean"] += delta / state["n"]
        state["M2"] += delta * (x - state["mean"])

    @staticmethod
    def _welford_remove(state: dict[str, Any], x: float) -> None:
        n = state["n"]
        if n <= 1:
            state["n"] = 0
            state["mean"] = 0.0
            state["M2"] = 0.0
            return
        mean_cur = state["mean"]
        mean_without = (n * mean_cur - x) / (n - 1)
        state["M2"] -= (x - mean_cur) * (x - mean_without)
        if state["M2"] < 0.0:
            # 3P-4: M2 < 0 is impossible in exact arithmetic — it signals
            # catastrophic cancellation has corrupted the incremental
            # accumulator.  Clamp to keep the immediate result sane, but flag
            # for an exact recompute from the live window so the drift is
            # *bounded*, not just hidden.
            state["M2"] = 0.0
            state["_drift_dirty"] = True
        state["mean"] = mean_without
        state["n"] = n - 1

    @staticmethod
    def _recompute_from_window(state: dict[str, Any]) -> None:
        """Exact two-pass mean/M2 over the live window (3P-4 drift reset)."""
        win: deque[tuple[int, float]] = state["win"]
        n = len(win)
        if n == 0:
            state["n"] = 0
            state["mean"] = 0.0
            state["M2"] = 0.0
        else:
            mean = sum(x for _ts, x in win) / n
            state["mean"] = mean
            state["M2"] = sum((x - mean) ** 2 for _ts, x in win)
            state["n"] = n
        state["_drift_dirty"] = False

    def _evict_before(self, state: dict[str, Any], cutoff_ns: int) -> None:
        win: deque[tuple[int, float]] = state["win"]
        while win and win[0][0] < cutoff_ns:
            _ts, x_old = win.popleft()
            self._welford_remove(state, x_old)
        # 3P-4: if cancellation corrupted the accumulator during this eviction
        # sweep, restore it exactly from the window so drift cannot persist.
        if state["_drift_dirty"]:
            self._recompute_from_window(state)

    def _scalarize(self, v_raw: Any) -> float | None:
        idxs = self._tuple_idxs
        if isinstance(v_raw, tuple):
            if idxs is None:
                self._warn_once(
                    "tuple_without_indices",
                    "sensor delivered a tuple but tuple_sum_component_indices is None",
                )
                return None
            acc = 0.0
            for i in idxs:
                if i >= len(v_raw):
                    self._warn_once(
                        "index_out_of_range",
                        f"tuple_sum_component_indices includes {i} but "
                        f"value has only {len(v_raw)} components",
                    )
                    return None
                acc += float(v_raw[i])
            return acc
        if idxs is not None:
            self._warn_once(
                "scalar_with_indices",
                "tuple_sum_component_indices is set but sensor delivered "
                "a scalar — drop the indices kwarg",
            )
            return None
        return float(v_raw)

    # ── HorizonFeature protocol ──────────────────────────────────────

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if not reading.warm:
            return
        x = self._scalarize(reading.value)
        if x is None:
            return
        ts = reading.timestamp_ns
        win: deque[tuple[int, float]] = state["win"]
        win.append((ts, x))
        self._welford_add(state, x)
        # Primary (time) eviction anchored at the reading ts.
        self._evict_before(state, ts - self._window_ns)
        # Safety count cap — only bites pathological bursts.
        while len(win) > self._max_samples:
            _ts, x_old = win.popleft()
            self._welford_remove(state, x_old)

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        # Re-evict at the tick boundary so a sensor that has gone silent
        # since its last reading correctly shrinks (and eventually
        # empties) its window — the aggregator's stale override then
        # fires on the empty/short window.
        self._evict_before(state, tick.timestamp_ns - self._window_ns)
        win: deque[tuple[int, float]] = state["win"]
        n = state["n"]
        reducer = self._reducer
        if n < self._min_samples or not win:
            # Percentile uses 0.5 (neutral prior) during warm-up, matching
            # RollingPercentileFeature; other reducers use 0.0.  The value
            # is unused while warm=False, but a meaningful neutral keeps
            # archived cold snapshots interpretable.
            neutral = 0.5 if reducer == "percentile" else 0.0
            return neutral, False, False

        latest = win[-1][1]
        mean = state["mean"]

        if reducer == "last":
            return latest, True, False
        if reducer == "mean":
            return mean, True, False
        if reducer == "sum":
            return mean * n, True, False
        if reducer == "delta":
            # Signed drift across the window: latest - oldest.  n >= 1 here;
            # a single-sample window has zero drift by definition.
            return latest - win[0][1], True, False
        if reducer == "percentile":
            # Hazen plotting position over the in-window values (audit #9).
            rank = sum(1 for (_ts, x) in win if x <= latest)
            return (rank - 0.5) / n, True, False

        # Variance-based reducers (need n >= 2, guaranteed by min_samples).
        var = state["M2"] / (n - 1) if n >= 2 else 0.0
        if var < 0.0:
            var = 0.0
        if reducer == "rms":
            # E[x²] = mean² + var (sample-corrected var is close enough).
            return (mean * mean + var) ** 0.5, True, False

        # zscore
        std = var**0.5
        if std < 1e-10:
            return 0.0, True, False
        z = (latest - mean) / std
        if z > _MAX_ZSCORE:
            return _MAX_ZSCORE, True, False
        if z < -_MAX_ZSCORE:
            return -_MAX_ZSCORE, True, False
        return z, True, False


__all__ = ["HorizonWindowedFeature"]
