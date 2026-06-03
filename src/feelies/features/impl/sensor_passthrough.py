"""Sensor passthrough HorizonFeature implementations.

Exposes the latest (or a specific tuple component of the latest) warm
sensor reading as a named entry in :class:`HorizonFeatureSnapshot.values`
at a chosen horizon boundary.

These are the "identity" features: they do no rolling computation —
they simply carry the most recent warm reading from Layer 1 into the
Layer 2 snapshot so that signal ``evaluate()`` functions can read raw
sensor values without coupling to the sensor bus directly.

Two implementations are provided:

:class:`SensorPassthroughFeature`
    For scalar-valued sensors (e.g. ``ofi_ewma``, ``quote_hazard_rate``,
    ``trade_through_rate``).  ``feature_id`` defaults to the
    ``sensor_id`` so ``snapshot.values["ofi_ewma"]`` carries the
    latest raw reading at this horizon.

:class:`TupleComponentFeature`
    For tuple-valued sensors (e.g. ``scheduled_flow_window`` which emits
    a length-4 tuple per design §20.4.2).  Each component is exposed as
    an independent feature under a caller-supplied ``feature_id`` such as
    ``"scheduled_flow_window_active"`` or ``"seconds_to_window_close"``.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading


class SensorPassthroughFeature:
    """Exposes the latest warm scalar reading as a snapshot feature.

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    horizon_seconds:
        Which horizon boundary this feature contributes to.
    feature_id:
        Key used in ``HorizonFeatureSnapshot.values``.  Defaults to
        ``sensor_id`` so callers that use the sensor name directly
        in ``snapshot.values.get("ofi_ewma")`` work without any
        explicit override.
    """

    feature_version: str = "1.0.0"

    def __init__(
        self,
        sensor_id: str,
        horizon_seconds: int,
        *,
        feature_id: str | None = None,
    ) -> None:
        self.feature_id: str = feature_id if feature_id is not None else sensor_id
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)

    def initial_state(self) -> dict[str, Any]:
        return {"value": None, "warm": False}

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
            # Tuple sensors are handled by TupleComponentFeature.
            return
        state["value"] = float(v)
        state["warm"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        if state["value"] is None:
            return 0.0, False, False
        return state["value"], state["warm"], False


class TupleComponentFeature:
    """Extracts one scalar component from a tuple-valued sensor reading.

    Some sensors emit a fixed-length tuple (e.g.
    :class:`feelies.sensors.impl.scheduled_flow_window.ScheduledFlowWindowSensor`
    emits ``(active, seconds_to_window_close, window_id_hash,
    flow_direction_prior)``).  This feature isolates one index and
    exposes it under a named ``feature_id`` in the snapshot values dict
    so signal ``evaluate()`` functions can access it via
    ``snapshot.values.get("scheduled_flow_window_active")``.

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    component_index:
        Zero-based index into the emitted tuple.
    feature_id:
        Key used in ``HorizonFeatureSnapshot.values``.
    horizon_seconds:
        Which horizon boundary this feature contributes to.
    """

    feature_version: str = "1.0.0"

    def __init__(
        self,
        sensor_id: str,
        component_index: int,
        feature_id: str,
        horizon_seconds: int,
    ) -> None:
        self.feature_id: str = feature_id
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._component_index = component_index

    def initial_state(self) -> dict[str, Any]:
        return {"value": None, "warm": False}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if not reading.warm:
            return
        v = reading.value
        if not isinstance(v, tuple):
            return
        if self._component_index >= len(v):
            return
        state["value"] = float(v[self._component_index])
        state["warm"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        if state["value"] is None:
            return 0.0, False, False
        return state["value"], state["warm"], False


class TupleSignedImbalanceFeature:
    """Signed imbalance between two components of a tuple-valued sensor.

    Computes ``(v[pos] - v[neg]) / (v[pos] + v[neg])`` from the latest
    warm reading, bounded to ``[-1, 1]`` and returning ``0.0`` when the
    denominator is below ``eps`` (no-information state).

    Motivation (audit P1-3): :class:`HawkesIntensitySensor` emits a
    ``(lambda_buy, lambda_sell, intensity_ratio, branching_ratio)``
    tuple.  The only feature wired over it sums ``lambda_buy +
    lambda_sell`` — an *undirected* burst magnitude that discards which
    side is excited.  This feature exposes the **signed** buy/sell
    imbalance so a directional HAWKES_SELF_EXCITE alpha has a usable
    L1 fingerprint (positive ⇒ buy-side excitation dominates).

    Parameters
    ----------
    sensor_id:
        The ``SensorReading.sensor_id`` to observe.
    pos_index, neg_index:
        Zero-based indices of the positive / negative tuple components
        (e.g. ``0`` = ``lambda_buy``, ``1`` = ``lambda_sell``).
    feature_id:
        Key used in ``HorizonFeatureSnapshot.values``.
    horizon_seconds:
        Which horizon boundary this feature contributes to.
    eps:
        Denominator floor below which the imbalance is reported as 0.0.
    """

    feature_version: str = "1.0.0"

    def __init__(
        self,
        sensor_id: str,
        pos_index: int,
        neg_index: int,
        feature_id: str,
        horizon_seconds: int,
        *,
        eps: float = 1e-12,
    ) -> None:
        self.feature_id: str = feature_id
        self.horizon_seconds: int = horizon_seconds
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self._pos_index = pos_index
        self._neg_index = neg_index
        self._eps = eps

    def initial_state(self) -> dict[str, Any]:
        return {"value": None, "warm": False}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if not reading.warm:
            return
        v = reading.value
        if not isinstance(v, tuple):
            return
        if self._pos_index >= len(v) or self._neg_index >= len(v):
            return
        pos = float(v[self._pos_index])
        neg = float(v[self._neg_index])
        denom = pos + neg
        if denom < self._eps:
            state["value"] = 0.0
        else:
            state["value"] = (pos - neg) / denom
        state["warm"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        if state["value"] is None:
            return 0.0, False, False
        return state["value"], state["warm"], False


__all__ = [
    "SensorPassthroughFeature",
    "TupleComponentFeature",
    "TupleSignedImbalanceFeature",
]
