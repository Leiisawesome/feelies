"""Error hierarchy for the sensor layer.

All sensor-layer errors derive from :class:`SensorRegistryError` so
callers (the bootstrap layer in particular) can catch the family with
a single ``except`` clause while still being able to discriminate
specific failure modes for diagnostics.
"""

from __future__ import annotations


class SensorRegistryError(Exception):
    """Base class for sensor-registry / scheduler failures."""


class DuplicateSensorRegistrationError(SensorRegistryError):
    """Raised when the same ``(sensor_id, sensor_version)`` is registered twice.

    Versions of the same ``sensor_id`` are intentionally distinct
    sensors (they may have different params and produce different
    values).  Re-registering an exact ``(id, version)`` pair is always
    a configuration error per the plan §3.1 ("version-pin conflict
    detection").
    """


class UnresolvedSensorDependencyError(SensorRegistryError):
    """Raised when a sensor declares ``input_sensor_ids`` not yet registered.

    The registry enforces topological registration order: a sensor
    that consumes another sensor's readings (e.g. ``structural_break_score``
    on ``hawkes_intensity``) must register **after** every input.  This
    keeps determinism explicit and prevents subscribe-order surprises
    on the bus.
    """
