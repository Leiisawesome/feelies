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


__all__ = ["SensorPassthroughFeature", "TupleComponentFeature"]
