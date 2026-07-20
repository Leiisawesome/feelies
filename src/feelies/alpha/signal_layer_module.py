"""Loader artifact for ``layer: SIGNAL`` alphas.

Loader-side artifact for schema-1.1 ``layer: SIGNAL`` alphas (peer:
:class:`~feelies.alpha.portfolio_layer_module.LoadedPortfolioLayerModule`).

Horizon signals reach orders via orchestrator ``_on_bus_signal``, unless a
PORTFOLIO alpha lists the signal in ``depends_on_signals`` (then
``_on_bus_sized_intent`` + ``check_sized_intent``).

This module:

* Declares **no inline features** — consumes Layer-1 ``SensorReading``
  via ``depends_on_sensors:``; ``feature_definitions()`` is empty.
* Exposes the SIGNAL surface (compiled ``HorizonSignal``, ``RegimeGate``,
  ``CostArithmetic``, ``horizon_seconds``, ``depends_on_sensors``) for
  bootstrap ``RegisteredSignal`` construction.

Satisfies :class:`~feelies.alpha.module.AlphaModule` so it registers
through :class:`~feelies.alpha.registry.AlphaRegistry` without a fork.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.alpha.module import AlphaManifest
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    Signal,
    TrendMechanism,
)
from feelies.features.definition import FeatureDefinition
from feelies.signals.horizon_protocol import HorizonSignal
from feelies.signals.regime_gate import RegimeGate


class LoadedSignalLayerModule:
    """Concrete ``AlphaModule`` for a schema-1.1 SIGNAL alpha."""

    __slots__ = (
        "_manifest",
        "_signal",
        "_signal_source",
        "_gate",
        "_cost",
        "_horizon_seconds",
        "_depends_on_sensors",
        "_trend_mechanism_enum",
        "_expected_half_life_seconds",
        "_consumed_features",
        "_params",
    )

    def __init__(
        self,
        *,
        manifest: AlphaManifest,
        signal: HorizonSignal,
        gate: RegimeGate,
        cost: CostArithmetic,
        horizon_seconds: int,
        depends_on_sensors: tuple[str, ...],
        trend_mechanism: TrendMechanism | None,
        expected_half_life_seconds: int,
        consumed_features: tuple[str, ...],
        params: Mapping[str, Any],
        signal_source: str | None = None,
    ) -> None:
        self._manifest = manifest
        self._signal = signal
        self._signal_source = signal_source
        self._gate = gate
        self._cost = cost
        self._horizon_seconds = horizon_seconds
        self._depends_on_sensors = depends_on_sensors
        self._trend_mechanism_enum = trend_mechanism
        self._expected_half_life_seconds = expected_half_life_seconds
        self._consumed_features = consumed_features
        self._params = dict(params)

    # ── AlphaModule protocol ─────────────────────────────────────────

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        """SIGNAL-layer alphas declare no inline features.

        They consume Layer-1 sensors through ``depends_on_sensors``. Returning
        ``()`` keeps registry deduplication and version checks simple.
        """
        return ()

    def validate(self) -> list[str]:
        """Return per-parameter validation errors.

        Mirrors
        :py:meth:`feelies.alpha.portfolio_layer_module.LoadedPortfolioLayerModule.validate`
        so SIGNAL and PORTFOLIO modules validate consistently.
        """
        errors: list[str] = []
        for pdef in self._manifest.parameter_schema:
            value = self._params.get(pdef.name, pdef.default)
            errors.extend(pdef.validate_value(value))
        return errors

    # ── SIGNAL-layer surface ─────────────────────────────────────────

    @property
    def signal(self) -> HorizonSignal:
        """Compiled :class:`HorizonSignal` callable."""
        return self._signal

    @property
    def signal_source(self) -> str | None:
        """Raw ``signal:`` source the alpha was compiled from.

        Retained so the platform can derive ``required_warm`` from the
        ``snapshot.values`` keys the body reads. ``None`` for modules built
        without source.
        """
        return self._signal_source

    @property
    def gate(self) -> RegimeGate:
        """Per-alpha :class:`RegimeGate` (parsed ON/OFF DSL)."""
        return self._gate

    @property
    def cost(self) -> CostArithmetic:
        """Validated :class:`CostArithmetic` disclosure block."""
        return self._cost

    @property
    def horizon_seconds(self) -> int:
        """Boundary horizon the alpha fires on (seconds)."""
        return self._horizon_seconds

    @property
    def depends_on_sensors(self) -> tuple[str, ...]:
        """Sensors the alpha consumes (declared in YAML)."""
        return self._depends_on_sensors

    @property
    def trend_mechanism_enum(self) -> TrendMechanism | None:
        """Mapped :class:`TrendMechanism` enum.

        ``None`` when YAML omits ``trend_mechanism:``.
        """
        return self._trend_mechanism_enum

    @property
    def expected_half_life_seconds(self) -> int:
        """Declared expected half-life.

        ``0`` when unspecified.
        """
        return self._expected_half_life_seconds

    @property
    def consumed_features(self) -> tuple[str, ...]:
        """Feature/sensor identifiers tagged on emitted ``Signal`` events."""
        return self._consumed_features

    @property
    def params(self) -> Mapping[str, Any]:
        """Resolved parameter mapping passed to ``signal.evaluate``."""
        return dict(self._params)


# ── HorizonSignal adapter for inline YAML evaluate() ────────────────────


class _CompiledHorizonSignal:
    """Adapter wrapping a compiled inline ``evaluate(snapshot, regime, params)``.

    Used by :class:`feelies.alpha.loader.AlphaLoader` when the SIGNAL
    spec carries an inline ``signal:`` code block.  The adapter
    implements the :class:`HorizonSignal` protocol verbatim so the
    :class:`HorizonSignalEngine` treats inline-coded and externally-
    imported signals identically.

    Determinism / safety:

    * The wrapped callable is compiled in the loader's restricted
      namespace (no ``__builtins__``); the adapter simply forwards.
    * The adapter is intentionally *stateless* — every invocation is
      a pure function call with no closure-side cache.  Replay
      reproduces the call-site bit-for-bit.
    """

    __slots__ = ("signal_id", "signal_version", "_fn")

    def __init__(
        self,
        *,
        signal_id: str,
        signal_version: str,
        fn: Any,
    ) -> None:
        self.signal_id = signal_id
        self.signal_version = signal_version
        self._fn = fn

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: Mapping[str, Any],
    ) -> Signal | None:
        result: Signal | None = self._fn(snapshot, regime, params)
        return result


__all__ = ["LoadedSignalLayerModule", "_CompiledHorizonSignal"]
