"""Sensor layer (Phase 2 of the three-layer architecture).

Sensors are Layer-1 components: stateless-by-instance computations over
raw L1 NBBO and trade events that emit typed ``SensorReading`` events
on the bus.  They are platform-authored, deterministic, and entirely
decoupled from the deleted per-tick feature path
(see ``design_docs/three_layer_architecture.md`` §4.2 / §6.2).

In Phase 2 the sensor layer is **observational only** — sensors emit
to dead-end consumers (logs, monitoring, forensics, parity recorders)
and never feed back into ``Signal`` or ``OrderIntent`` (Inv-E in the
plan).  Phase 3 introduces the alpha-side ``depends_on_sensors:``
binding.

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
from feelies.sensors.protocol import Sensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

__all__ = [
    "DuplicateSensorRegistrationError",
    "HorizonScheduler",
    "Sensor",
    "SensorRegistry",
    "SensorRegistryError",
    "SensorSpec",
    "SessionOpenAlreadyBoundError",
    "UnresolvedSensorDependencyError",
]
