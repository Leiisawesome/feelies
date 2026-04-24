"""Adapter that exposes a legacy ``FeatureComputation`` as a ``HorizonFeature``.

Phase-2 reality (plan §4.4): no horizon alphas exist yet, so this
shim **lands but stays inactive** in the default bootstrap.  It is
shipped now so Phase 3 can plug horizon alphas on top of pre-existing
feature implementations without touching the legacy feature catalog.

How the shim bridges the two contracts:

- A legacy :class:`feelies.features.definition.FeatureComputation`
  consumes ``NBBOQuote`` (and optionally ``Trade``) per tick and
  returns a scalar ``float`` directly.
- A :class:`feelies.features.protocol.HorizonFeature` consumes
  upstream ``SensorReading`` events and emits a ``(value, warm,
  stale)`` triple at horizon boundaries.

The shim adapts by:

1.  Treating each ``SensorReading`` as a one-tick "synthetic"
    horizon: the most-recent reading wins, and ``finalize`` returns
    that scalar with ``warm=True`` (the upstream sensor already
    declared warmth via :class:`SensorReading.warm`) and
    ``stale=False`` whenever a fresh reading has arrived since the
    previous boundary (per Inv-11 fail-safe default).
2.  Deferring all heavy lifting to the wrapped legacy computation:
    the shim never touches the original ``FeatureComputation.update``
    surface area, so legacy state semantics remain bit-identical
    when consumed via the legacy ``CompositeFeatureEngine`` path.

The shim is intentionally minimal: it does not aggregate over a
window, does not maintain per-window state, and does not call any
``FeatureComputation`` method.  Phase 3 will replace this with first
class horizon alphas; the shim only exists to keep the migration
order strictly additive.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.definition import FeatureComputation, FeatureDefinition


class LegacyFeatureShim:
    """Wrap a legacy ``FeatureComputation`` as a :class:`HorizonFeature`.

    Construction parameters:

    - ``definition``: the original :class:`FeatureDefinition` whose
      ``feature_id`` / ``version`` we mirror so the
      ``HorizonFeatureSnapshot`` carries the legacy identity through
      forensic logs unchanged.
    - ``sensor_id``: the upstream :class:`SensorReading.sensor_id`
      that supplies the scalar (typically a one-to-one mirror of the
      legacy feature, e.g. ``"micro_price"``).
    - ``horizon_seconds``: the horizon at which the shim should emit.
      In Phase 2 the bootstrap layer constructs one shim per
      ``(legacy_feature, horizon)`` tuple it cares about.
    """

    __slots__ = (
        "_definition",
        "feature_id",
        "feature_version",
        "input_sensor_ids",
        "horizon_seconds",
    )

    def __init__(
        self,
        *,
        definition: FeatureDefinition,
        sensor_id: str,
        horizon_seconds: int,
    ) -> None:
        if horizon_seconds <= 0:
            raise ValueError(
                f"horizon_seconds must be > 0, got {horizon_seconds}"
            )
        self._definition = definition
        self.feature_id: str = definition.feature_id
        self.feature_version: str = definition.version
        self.input_sensor_ids: tuple[str, ...] = (sensor_id,)
        self.horizon_seconds: int = horizon_seconds

    @property
    def computation(self) -> FeatureComputation:
        """Underlying legacy computation — exposed for forensic introspection."""
        return self._definition.compute

    def initial_state(self) -> dict[str, Any]:
        # The shim itself only tracks the latest reading + a freshness
        # flag.  The wrapped legacy computation's state lives inside
        # the legacy CompositeFeatureEngine and is not duplicated here.
        return {
            "last_value": None,
            "last_ts_ns": None,
            "received_in_window": False,
        }

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        # SensorReading.value can be a scalar or a tuple; we only
        # surface the scalar form via this shim because legacy
        # FeatureComputation outputs are scalars (``float``).
        value = reading.value
        if isinstance(value, tuple):
            # First component is the canonical scalar by convention;
            # multi-output sensors should be wrapped by a real
            # HorizonFeature implementation in Phase 3 rather than
            # via this shim.
            value = value[0]
        state["last_value"] = float(value)
        state["last_ts_ns"] = reading.timestamp_ns
        # Use the upstream warm flag as a hard floor: a non-warm
        # reading does not constitute "received" for stale-detection
        # purposes (an unreliable reading should not mask staleness).
        if reading.warm:
            state["received_in_window"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        last_value = state.get("last_value")
        if last_value is None:
            value = 0.0
            warm = False
            stale = True
        else:
            value = float(last_value)
            warm = True
            stale = not state["received_in_window"]
        # Reset per-window freshness flag for the next horizon.
        state["received_in_window"] = False
        return value, warm, stale


__all__ = ["LegacyFeatureShim"]
