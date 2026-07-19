"""Sensor layer (Layer 1 of the three-layer architecture).

Sensors are incremental observers over raw L1 NBBO and trade events
that emit typed ``SensorReading`` events on the bus.  They are
platform-authored and deterministic.  SIGNAL alphas bind via
``depends_on_sensors:``; readings also feed the horizon aggregator.

Public surface:

- :class:`Sensor` — Protocol every sensor implementation satisfies.
- :class:`SensorSpec` — declarative registration record.
- :class:`SensorRegistry` — owns per-symbol state and routes
  ``NBBOQuote``/``Trade`` events to sensors.
- :class:`HorizonScheduler` — emits ``HorizonTick`` events at
  deterministic event-time boundaries.
"""

from __future__ import annotations

from feelies.sensors.errors import (
    DuplicateSensorRegistrationError,
    SensorRegistryError,
    UnresolvedSensorDependencyError,
)
from feelies.sensors.horizon_scheduler import (
    HorizonScheduler,
    SessionOpenAlreadyBoundError,
)
from feelies.sensors.protocol import Sensor, SensorEmission
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

__all__ = [
    "DuplicateSensorRegistrationError",
    "HorizonScheduler",
    "Sensor",
    "SensorEmission",
    "SensorRegistry",
    "SensorRegistryError",
    "SensorSpec",
    "SessionOpenAlreadyBoundError",
    "UnresolvedSensorDependencyError",
]
