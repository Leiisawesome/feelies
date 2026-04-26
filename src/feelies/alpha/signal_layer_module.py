"""Phase-3 ``layer: SIGNAL`` alpha module.

A :class:`LoadedSignalLayerModule` is the loader-side artifact for a
schema-1.1 ``layer: SIGNAL`` alpha.  Workstream D.2 PR-1 retired
``layer: LEGACY_SIGNAL`` and PR-2a deleted the per-tick
``LoadedAlphaModule`` class itself; PR-2b-i unwired the per-tick
engines from bootstrap and PR-2b-ii deleted the engine classes
themselves (``CompositeFeatureEngine``, ``CompositeSignalEngine``,
``MultiAlphaEvaluator``).  This is therefore one of only two
surviving loaded-module types (the other being
:class:`feelies.alpha.portfolio_layer_module.LoadedPortfolioLayerModule`).

PR-2b-iii (this commit) wired the **first production-reachable
Signal → Order pipeline** by adding a bus-driven ``Signal`` subscriber
on the ``Orchestrator`` (``_on_bus_signal``) that buffers
``Signal(layer="SIGNAL")`` events emitted by
:class:`feelies.signals.horizon_engine.HorizonSignalEngine` and feeds
the M4 ``SIGNAL_EVALUATE`` drain — turning every ``LoadedSignalLayerModule``
that fires a Signal at a horizon boundary into an actual
``OrderRequest`` (subject to risk / intent translation), unless the
alpha is referenced by some PORTFOLIO's ``depends_on_signals`` (in
which case ``CompositionEngine`` aggregates it into a
``SizedPositionIntent`` instead, to be wired to orders by PR-2b-iv).

This module:

* Declares **no inline features** — Layer-2 alphas consume Layer-1
  ``SensorReading`` events via ``depends_on_sensors:``.  ``feature_definitions()``
  therefore returns an empty sequence.
* Implements ``AlphaModule.evaluate(features)`` as a deterministic
  ``None``.  Post-D.2 PR-2b-ii the protocol method survives only as
  test scaffolding for the orchestrator's gated single-alpha
  pipeline; the actual production evaluation runs in
  :class:`feelies.signals.horizon_engine.HorizonSignalEngine` on
  :class:`feelies.core.events.HorizonFeatureSnapshot` events, and the
  emitted ``Signal`` is consumed by the orchestrator's PR-2b-iii bus
  subscriber.
* Exposes the SIGNAL-specific surface (the compiled
  :class:`feelies.signals.horizon_protocol.HorizonSignal` callable, the
  :class:`feelies.signals.regime_gate.RegimeGate` instance, the
  validated :class:`feelies.alpha.cost_arithmetic.CostArithmetic`
  block, ``horizon_seconds``, and the declared ``depends_on_sensors``)
  via dedicated attributes so the bootstrap layer can construct
  :class:`feelies.signals.horizon_engine.RegisteredSignal` records
  without touching the loader internals.

By satisfying the :class:`feelies.alpha.module.AlphaModule` protocol
*and* the SIGNAL-layer surface, the module remains register-able
through :class:`feelies.alpha.registry.AlphaRegistry` without forking
the registry.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.alpha.module import AlphaManifest
from feelies.core.events import (
    FeatureVector,
    HorizonFeatureSnapshot,
    RegimeState,
    Signal,
    TrendMechanism,
)
from feelies.features.definition import FeatureDefinition
from feelies.signals.horizon_protocol import HorizonSignal
from feelies.signals.regime_gate import RegimeGate


class LoadedSignalLayerModule:
    """Concrete ``AlphaModule`` for a schema-1.1 ``layer: SIGNAL`` alpha.

    The class exposes the standard :class:`AlphaModule` surface so it
    can be registered with the existing :class:`AlphaRegistry`
    (smoke-test passes trivially because :py:meth:`evaluate` is a
    constant-``None`` function).  Phase-3 wiring then introspects each
    registered module: those whose ``manifest.layer == "SIGNAL"`` are
    constructed into a :class:`feelies.signals.horizon_engine.RegisteredSignal`
    and handed to the :class:`HorizonSignalEngine`.
    """

    __slots__ = (
        "_manifest",
        "_signal",
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
    ) -> None:
        self._manifest = manifest
        self._signal = signal
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

        They consume Layer-1 sensors directly via ``depends_on_sensors``.
        The per-tick composite feature engine was deleted by D.2
        PR-2b-ii, so this method's return value is consumed only by the
        orchestrator's gated single-alpha test scaffolding (and the
        registry smoke-test).  Returning ``()`` keeps the existing
        dedup / version-conflict logic free of corner cases.
        """
        return ()

    def evaluate(self, features: FeatureVector) -> Signal | None:
        """No-op — SIGNAL-layer alphas evaluate on snapshots, not ticks.

        Post-D.2 PR-2b-ii the legacy per-tick composite signal engine
        is deleted; this protocol method survives purely as test
        scaffolding for the orchestrator's gated single-alpha pipeline.
        Returning ``None`` here means SIGNAL-layer alphas contribute
        nothing to that path; their actual ``Signal`` events are emitted
        on the bus by the :class:`HorizonSignalEngine`.

        The smoke test in
        :class:`feelies.alpha.registry.AlphaRegistry._smoke_test`
        invokes this method twice with identical input and compares the
        results; constant ``None`` trivially satisfies the determinism
        contract (Inv-5).
        """
        return None

    def validate(self) -> list[str]:
        """Return per-parameter validation errors.

        Mirrors
        :py:meth:`feelies.alpha.portfolio_layer_module.LoadedPortfolioLayerModule.validate`
        so registry-side per-alpha validation has consistent behavior
        across the two surviving loaded-module types (SIGNAL and
        PORTFOLIO).  The historical per-tick ``LoadedAlphaModule.validate``
        was deleted by D.2 PR-2 along with the rest of the legacy
        per-tick contract.
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
        """Mapped :class:`TrendMechanism` enum (Phase-3.1 propagation).

        ``None`` when the YAML omits ``trend_mechanism:`` (v0.2 SIGNAL
        behavior preserved bit-identically).
        """
        return self._trend_mechanism_enum

    @property
    def expected_half_life_seconds(self) -> int:
        """Declared expected half-life (Phase-3.1 propagation).

        ``0`` when unspecified (v0.2 SIGNAL behavior preserved
        bit-identically).
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
