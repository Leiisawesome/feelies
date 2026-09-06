"""Declarative SensorSpec — registers one sensor with the registry.

A ``SensorSpec`` is the immutable declaration the registry consumes at
boot time.  It binds a sensor implementation (``cls``) to:

- a registration key (``sensor_id`` + ``sensor_version``);
- the event types it subscribes to (``subscribes_to``);
- any upstream sensors it depends on (``input_sensor_ids``);
- bound parameters (``params``);
- a warm-up minimum (``min_history``);
- an optional throttle expressed in milliseconds (``throttled_ms``).

The class lives in :mod:`feelies.core.sensor_spec` so PlatformConfig can
name it without importing the sensors package.  This module re-exports
it; the registry and YAML loaders keep importing from here.
"""

from __future__ import annotations

from feelies.core.sensor_spec import SensorSpec

__all__ = ["SensorSpec"]
