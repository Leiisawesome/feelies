"""HorizonSignalEngine — Phase-3 Layer-2 signal driver.

The :class:`HorizonSignalEngine` ties together the four Phase-3
artifacts:

  - :class:`feelies.signals.horizon_protocol.HorizonSignal` — alpha-side
    pure evaluation function.
  - :class:`feelies.signals.regime_gate.RegimeGate` — DSL-driven
    ON/OFF latch over regime posteriors.
  - :class:`feelies.alpha.cost_arithmetic.CostArithmetic` — disclosed
    edge / cost reconciliation (read at construction; not consumed at
    runtime — every emitted ``Signal`` already encodes
    ``edge_estimate_bps``).
  - :class:`feelies.core.events.HorizonFeatureSnapshot` — Layer-2
    feature aggregate the engine consumes.

Lifecycle
---------

1. **Construction** — register one ``RegisteredSignal`` per
   ``(alpha_id, signal_id)``.  Each entry carries:

     - the compiled ``HorizonSignal`` (callable, stateless);
     - the alpha's parameter mapping (immutable);
     - the per-alpha :class:`RegimeGate` instance;
     - the alpha's ``horizon_seconds`` (engine fires only on matching
       boundary snapshots);
     - the alpha's declared :class:`feelies.core.events.TrendMechanism`
       and ``expected_half_life_seconds`` (Phase-3.1 propagation;
       defaults preserve v0.2 behavior bit-identically);
     - the optional ``regime_engine`` name for downstream filtering.

2. **Bus subscription** — the engine subscribes once to
   :class:`feelies.core.events.HorizonFeatureSnapshot` and once to
   :class:`feelies.core.events.RegimeState`.  RegimeState events are
   cached per ``(symbol, engine_name)`` so the gate has the latest
   posterior without consulting the engine directly.

3. **Per-snapshot dispatch** — for every horizon snapshot the engine
   filters registered signals to those whose ``horizon_seconds``
   match, evaluates the gate, and (when ON) calls the
   ``HorizonSignal.evaluate``.  Returned ``Signal`` objects are
   patched with provenance and published with sequence numbers from
   the engine's dedicated ``signal_seq`` generator (Inv-A / C1
   isolation).

The engine is *passive when no SIGNAL alpha is registered* — the bus
subscription is skipped entirely so deployments without horizon-
anchored alphas incur zero overhead.

Determinism
-----------

  - Iteration order over registered signals is stable (registration
    order); the engine sorts them at registration time so external
    register-order does not perturb the bus stream.
  - Sequence numbers come from a single dedicated generator owned by
    the engine; they never collide with the orchestrator's main
    sequence (``_seq``), the sensor sequence, the horizon sequence,
    the snapshot sequence, or (Phase-3.1) the hazard sequence.
  - The engine is the *only* writer to the SIGNAL stream; replay
    reproduces the stream bit-for-bit (Level-2 baseline).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    SensorReading,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_protocol import HorizonSignal
from feelies.signals.regime_gate import (
    Bindings,
    RegimeGate,
    RegimeGateError,
    UnknownIdentifierError,
)


_logger = logging.getLogger(__name__)


# ── Tuple-sensor component expansion ────────────────────────────────────
#
# A small set of L1 sensors emit tuple values (e.g. the scheduled-flow
# window sensor publishes a 4-tuple per design §20.4.2).  The regime-gate
# DSL only resolves *scalar* identifiers, so the engine fans those tuple
# readings out into per-component scalar cache entries on ingestion.
#
# The mapping is intentionally explicit (not introspected from the sensor
# instance) so the binding names participating in the DSL are auditable
# from this module alone.  Add new sensors here as their consumers come
# online.  Any tuple sensor not declared here is silently skipped — the
# pre-Phase-3.1 behavior — preserving back-compat.
_TUPLE_SENSOR_COMPONENTS: dict[str, tuple[str, ...]] = {
    # design §20.4.2: (active, seconds_to_window_close,
    # window_id_hash, flow_direction_prior)
    "scheduled_flow_window": (
        "scheduled_flow_window_active",
        "seconds_to_window_close",
        "scheduled_flow_window_id_hash",
        "scheduled_flow_window_direction_prior",
    ),
}


@dataclass(frozen=True, kw_only=True)
class RegisteredSignal:
    """Immutable record describing one signal the engine drives.

    All metadata needed to evaluate, gate, and tag the produced
    ``Signal`` event lives on this record so the dispatch loop has
    no per-call lookups beyond a list scan.
    """

    alpha_id: str
    horizon_seconds: int
    signal: HorizonSignal
    params: Mapping[str, Any]
    gate: RegimeGate
    cost_arithmetic: CostArithmetic
    trend_mechanism: TrendMechanism | None = None
    expected_half_life_seconds: int = 0
    consumed_features: tuple[str, ...] = ()


class HorizonSignalEngine:
    """Bus-subscriber that turns Layer-2 snapshots into ``Signal`` events.

    Construction parameters:

    - ``bus`` — the platform :class:`EventBus`; the engine subscribes
      to :class:`HorizonFeatureSnapshot` and :class:`RegimeState`
      lazily on :meth:`attach` so tests can wire and tear down the
      engine without leaking subscriptions.
    - ``signal_sequence_generator`` — dedicated
      :class:`feelies.core.identifiers.SequenceGenerator` owned by the
      engine.  All emitted ``Signal`` events draw sequences from this
      generator only.
    - ``clock`` — used to stamp emitted ``Signal.timestamp_ns`` when
      the snapshot is missing one (defensive — snapshots always carry
      a timestamp in production).
    """

    __slots__ = (
        "_bus",
        "_signal_seq",
        "_clock",
        "_signals",
        "_regime_cache",
        "_sensor_cache",
        "_attached",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        signal_sequence_generator: SequenceGenerator,
        clock: Any | None = None,
    ) -> None:
        self._bus = bus
        self._signal_seq = signal_sequence_generator
        self._clock = clock
        self._signals: list[RegisteredSignal] = []
        self._regime_cache: dict[tuple[str, str], RegimeState] = {}
        # ``_sensor_cache`` holds the latest scalar reading per
        # ``(symbol, sensor_id)``.  Populated incrementally as
        # ``SensorReading`` events flow over the bus.  The cache is
        # the *boundary view* consulted by gate / signal evaluation —
        # in v0.2 the :class:`HorizonAggregator` runs in passive mode
        # (empty ``HorizonFeatureSnapshot.values``), so sensor bindings
        # come from this cache rather than from the snapshot itself.
        self._sensor_cache: dict[tuple[str, str], float] = {}
        self._attached: bool = False

    # ── Registration ─────────────────────────────────────────────────

    def register(self, registered: RegisteredSignal) -> None:
        """Register one signal.  Idempotent within ``alpha_id``.

        Re-registering the same ``alpha_id`` raises :class:`ValueError`
        — the platform's :class:`feelies.alpha.registry.AlphaRegistry`
        already enforces alpha-id uniqueness, so this is a defensive
        belt-and-suspenders check.
        """
        for existing in self._signals:
            if existing.alpha_id == registered.alpha_id:
                raise ValueError(
                    f"HorizonSignalEngine: alpha {registered.alpha_id!r} "
                    f"is already registered"
                )
        self._signals.append(registered)
        # Sort by (horizon_seconds, alpha_id) so iteration order is a
        # deterministic function of registered ids — independent of
        # registration order.
        self._signals.sort(key=lambda s: (s.horizon_seconds, s.alpha_id))

    @property
    def is_empty(self) -> bool:
        """True iff no SIGNAL alphas have been registered."""
        return not self._signals

    @property
    def signals(self) -> tuple[RegisteredSignal, ...]:
        """Read-only view of registered signals in dispatch order."""
        return tuple(self._signals)

    # ── Bus wiring ───────────────────────────────────────────────────

    def attach(self) -> None:
        """Subscribe to :class:`HorizonFeatureSnapshot` and
        :class:`RegimeState` events on the configured bus.

        No-op when no signals are registered (bus subscription is
        skipped entirely so deployments without horizon-anchored
        alphas incur zero overhead — Inv-A).
        """
        if self._attached:
            return
        if not self._signals:
            _logger.debug(
                "HorizonSignalEngine.attach() — no signals registered, "
                "skipping bus subscription (legacy fast-path preserved)"
            )
            return
        self._bus.subscribe(RegimeState, self._on_regime_state)  # type: ignore[arg-type]
        self._bus.subscribe(SensorReading, self._on_sensor_reading)  # type: ignore[arg-type]
        self._bus.subscribe(
            HorizonFeatureSnapshot, self._on_snapshot,  # type: ignore[arg-type]
        )
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_regime_state(self, event: RegimeState) -> None:
        """Cache the latest ``RegimeState`` per ``(symbol, engine_name)``."""
        self._regime_cache[(event.symbol, event.engine_name)] = event

    def _on_sensor_reading(self, event: SensorReading) -> None:
        """Cache the latest scalar sensor reading per ``(symbol, sensor_id)``.

        Tuple-valued readings are fanned out into the per-component
        scalar binding names declared in ``_TUPLE_SENSOR_COMPONENTS``;
        this lets the gate / signal DSL reference vector sensor
        outputs by their documented component names without breaking
        the scalar-only binding contract.  Tuple sensors not declared
        in the registry are skipped — preserving v0.2 behavior — and
        a debug record is emitted so missing entries are easy to spot.
        """
        if not event.warm:
            return
        value = event.value
        if isinstance(value, tuple):
            components = _TUPLE_SENSOR_COMPONENTS.get(event.sensor_id)
            if components is None:
                _logger.debug(
                    "HorizonSignalEngine: tuple sensor %r emitted "
                    "without a registered component map; skipping",
                    event.sensor_id,
                )
                return
            for name, component_value in zip(components, value):
                self._sensor_cache[(event.symbol, name)] = float(
                    component_value
                )
            return
        self._sensor_cache[(event.symbol, event.sensor_id)] = float(value)

    def _on_snapshot(self, snapshot: HorizonFeatureSnapshot) -> None:
        """Evaluate every registered signal whose horizon matches."""
        if not self._signals:
            return
        for registered in self._signals:
            if registered.horizon_seconds != snapshot.horizon_seconds:
                continue
            self._dispatch_one(registered, snapshot)

    # ── Per-signal dispatch ──────────────────────────────────────────

    def _dispatch_one(
        self,
        registered: RegisteredSignal,
        snapshot: HorizonFeatureSnapshot,
    ) -> None:
        """Evaluate gate, then signal, and publish the resulting event."""
        regime = self._lookup_regime(snapshot.symbol, registered.gate)
        bindings = self._build_bindings(snapshot, regime, self._sensor_cache)
        try:
            on = registered.gate.evaluate(
                symbol=snapshot.symbol, bindings=bindings,
            )
        except UnknownIdentifierError:
            _logger.debug(
                "HorizonSignalEngine: %s gate evaluation suppressed for "
                "%s — required binding missing (cold start / warm-up)",
                registered.alpha_id, snapshot.symbol,
            )
            return
        except RegimeGateError as exc:
            _logger.warning(
                "HorizonSignalEngine: %s gate parse/eval error for %s: %s",
                registered.alpha_id, snapshot.symbol, exc,
            )
            return

        if not on:
            return

        try:
            raw = registered.signal.evaluate(
                snapshot, regime, registered.params,
            )
        except Exception as exc:
            _logger.warning(
                "HorizonSignalEngine: %s.evaluate raised on symbol=%s "
                "boundary_index=%d: %s",
                registered.alpha_id, snapshot.symbol,
                snapshot.boundary_index, exc,
            )
            return

        if raw is None:
            return

        if not isinstance(raw, Signal):
            _logger.warning(
                "HorizonSignalEngine: %s.evaluate returned %r (expected "
                "Signal | None); discarding",
                registered.alpha_id, type(raw).__name__,
            )
            return
        if raw.direction == SignalDirection.FLAT:
            # FLAT is the canonical "no trade" disposition; do not
            # publish (matches legacy SignalEngine behavior).
            return

        emitted = self._patch_signal(raw, snapshot, registered)
        self._bus.publish(emitted)

    # ── Helpers ──────────────────────────────────────────────────────

    def _lookup_regime(
        self, symbol: str, gate: RegimeGate
    ) -> RegimeState | None:
        """Resolve the cached :class:`RegimeState` for *symbol*.

        Picks by ``gate.engine_name`` when declared; otherwise returns
        whichever engine published last for *symbol* (matches the
        single-engine production deployment).
        """
        if gate.engine_name is not None:
            return self._regime_cache.get((symbol, gate.engine_name))
        # Single-engine fallback — first match wins, deterministic
        # because cache key insertion order mirrors RegimeState
        # publication order.
        for (sym, _engine), state in self._regime_cache.items():
            if sym == symbol:
                return state
        return None

    @staticmethod
    def _build_bindings(
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        sensor_cache: Mapping[tuple[str, str], float],
    ) -> Bindings:
        """Promote the snapshot's ``values`` mapping into a gate binding.

        The gate DSL recognises the following identifier suffixes:
        ``_percentile`` and ``_zscore``; both are materialised by the
        snapshot's ``values`` mapping when the alpha author wires them
        through Layer-2 features.  Identifiers without a suffix
        resolve to the corresponding sensor/feature value.

        The aggregator runs in passive mode for v0.2 (snapshot.values
        is empty), so this method also overlays the latest scalar
        sensor readings from ``sensor_cache`` for ``snapshot.symbol``.
        Snapshot values take priority — once the active aggregator
        ships in Phase 3.5+ its outputs naturally win.
        """
        sensor_values = dict(snapshot.values)
        for (sym, sensor_id), value in sensor_cache.items():
            if sym != snapshot.symbol:
                continue
            sensor_values.setdefault(sensor_id, value)

        percentiles = {
            k[: -len("_percentile")]: v
            for k, v in sensor_values.items()
            if k.endswith("_percentile")
        }
        zscores = {
            k[: -len("_zscore")]: v
            for k, v in sensor_values.items()
            if k.endswith("_zscore")
        }
        return Bindings(
            regime=regime,
            sensor_values=sensor_values,
            percentiles=percentiles,
            zscores=zscores,
        )

    def _patch_signal(
        self,
        raw: Signal,
        snapshot: HorizonFeatureSnapshot,
        registered: RegisteredSignal,
    ) -> Signal:
        """Tag the alpha-emitted ``Signal`` with engine provenance.

        The alpha is free to leave provenance fields empty; the engine
        fills them in from the snapshot + registration record.  Any
        field already set by the alpha (e.g. ``metadata``) is
        preserved.
        """
        timestamp_ns = (
            raw.timestamp_ns
            if raw.timestamp_ns
            else snapshot.timestamp_ns
        )
        if not timestamp_ns and self._clock is not None:
            timestamp_ns = self._clock.now_ns()

        return replace(
            raw,
            timestamp_ns=timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=self._signal_seq.next(),
            source_layer="SIGNAL",
            symbol=raw.symbol or snapshot.symbol,
            strategy_id=raw.strategy_id or registered.alpha_id,
            layer="SIGNAL",
            horizon_seconds=registered.horizon_seconds,
            regime_gate_state="ON",
            consumed_features=(
                raw.consumed_features
                if raw.consumed_features
                else registered.consumed_features
            ),
            trend_mechanism=(
                raw.trend_mechanism
                if raw.trend_mechanism is not None
                else registered.trend_mechanism
            ),
            expected_half_life_seconds=(
                raw.expected_half_life_seconds
                if raw.expected_half_life_seconds
                else registered.expected_half_life_seconds
            ),
        )


__all__ = ["HorizonSignalEngine", "RegisteredSignal"]
