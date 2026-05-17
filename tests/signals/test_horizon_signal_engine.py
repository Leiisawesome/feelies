"""Tests for :class:`feelies.signals.horizon_engine.HorizonSignalEngine`.

Covers:

* Construction + idempotent registration with deterministic dispatch order.
* :py:meth:`attach` is a no-op when no signals are registered.
* End-to-end flow: ``RegimeState`` cached → ``SensorReading`` cached →
  ``HorizonFeatureSnapshot`` triggers gate evaluation → ``Signal``
  emitted with engine provenance.
* Gate OFF suppresses emission; ``UnknownIdentifierError`` (cold-start)
  is swallowed silently.
* Horizon mismatch causes the engine to skip a registered signal.
* :class:`SignalDirection.FLAT` is suppressed even when the alpha
  returns it.
* Sequence numbers come from the dedicated generator and increase
  monotonically.
* Tuple-valued ``SensorReading`` events are skipped (only scalar
  bindings are exposed to the gate).
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

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
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import RegimeGate


# ── Helpers ─────────────────────────────────────────────────────────────


def _gate(
    alpha_id: str = "alpha_x",
    on_condition: str = "P(normal) > 0.7",
    off_condition: str = "P(normal) < 0.5",
    engine_name: str | None = "hmm_3state_fractional",
) -> RegimeGate:
    return RegimeGate(
        alpha_id=alpha_id,
        on_condition=on_condition,
        off_condition=off_condition,
        engine_name=engine_name,
    )


def _cost() -> CostArithmetic:
    return CostArithmetic.from_spec(
        alpha_id="alpha_x",
        spec={
            "edge_estimate_bps": 9.0,
            "half_spread_bps": 2.0,
            "impact_bps": 2.0,
            "fee_bps": 1.0,
            "margin_ratio": 1.8,
        },
    )


class _RecordingSignal:
    """Minimal :class:`HorizonSignal`-shaped callable that records calls."""

    def __init__(
        self,
        *,
        signal_id: str = "alpha_x",
        signal_version: str = "1.0.0",
        direction: SignalDirection = SignalDirection.LONG,
        emit: bool = True,
    ) -> None:
        self.signal_id = signal_id
        self.signal_version = signal_version
        self._direction = direction
        self._emit = emit
        self.calls: list[tuple[Any, Any, Mapping[str, Any]]] = []

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: Any,
        params: Mapping[str, Any],
    ) -> Signal | None:
        self.calls.append((snapshot, regime, dict(params)))
        if not self._emit:
            return None
        return Signal(
            timestamp_ns=snapshot.timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=0,                # patched by engine
            symbol=snapshot.symbol,
            strategy_id=self.signal_id,
            direction=self._direction,
            strength=0.5,
            edge_estimate_bps=8.0,
        )


def _registered(
    *,
    alpha_id: str = "alpha_x",
    horizon_seconds: int = 120,
    signal: _RecordingSignal | None = None,
    gate: RegimeGate | None = None,
    consumed_features: tuple[str, ...] = ("ofi_ewma",),
    trend_mechanism: TrendMechanism | None = None,
    expected_half_life_seconds: int = 0,
    required_warm_feature_ids: frozenset[str] | None = None,
) -> RegisteredSignal:
    return RegisteredSignal(
        alpha_id=alpha_id,
        horizon_seconds=horizon_seconds,
        signal=signal or _RecordingSignal(signal_id=alpha_id),
        params={"entry_threshold_z": 2.0},
        gate=gate or _gate(alpha_id=alpha_id),
        cost_arithmetic=_cost(),
        consumed_features=consumed_features,
        trend_mechanism=trend_mechanism,
        expected_half_life_seconds=expected_half_life_seconds,
        required_warm_feature_ids=required_warm_feature_ids,
    )


def _engine() -> tuple[HorizonSignalEngine, EventBus, list[Signal]]:
    bus = EventBus()
    seq = SequenceGenerator()
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=seq)
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    return engine, bus, captured


def _regime_normal_high(symbol: str = "AAPL") -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr",
        sequence=1,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("normal",),
        posteriors=(0.9,),
        dominant_state=0,
        dominant_name="normal",
    )


def _regime_normal_low(symbol: str = "AAPL") -> RegimeState:
    return RegimeState(
        timestamp_ns=1_500,
        correlation_id="corr",
        sequence=2,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("normal",),
        posteriors=(0.3,),
        dominant_state=0,
        dominant_name="normal",
    )


def _snapshot(
    *,
    symbol: str = "AAPL",
    horizon_seconds: int = 120,
    boundary_index: int = 1,
    sequence: int = 10,
    values: dict[str, float] | None = None,
    warm: dict[str, bool] | None = None,
    stale: dict[str, bool] | None = None,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=sequence,
        symbol=symbol,
        horizon_seconds=horizon_seconds,
        boundary_index=boundary_index,
        values=values or {},
        warm=warm or {},
        stale=stale or {},
    )


# ── Registration ────────────────────────────────────────────────────────


def test_engine_starts_empty() -> None:
    engine, _, _ = _engine()
    assert engine.is_empty
    assert engine.signals == ()


def test_register_appends_and_sorts() -> None:
    engine, _, _ = _engine()
    engine.register(_registered(alpha_id="b", horizon_seconds=300))
    engine.register(_registered(alpha_id="a", horizon_seconds=120))
    ids = tuple(r.alpha_id for r in engine.signals)
    # Sort key is (horizon_seconds, alpha_id) — 120 < 300 first.
    assert ids == ("a", "b")


def test_register_duplicate_raises() -> None:
    engine, _, _ = _engine()
    engine.register(_registered(alpha_id="x"))
    with pytest.raises(ValueError, match="already registered"):
        engine.register(_registered(alpha_id="x"))


def test_attach_is_noop_when_empty() -> None:
    engine, bus, captured = _engine()
    engine.attach()
    bus.publish(_snapshot())
    assert captured == []


# ── End-to-end dispatch ─────────────────────────────────────────────────


def test_narrow_required_warm_ignores_unrelated_cold_features() -> None:
    """Bootstrap-style ``required_warm_feature_ids`` must not block on other features."""
    engine, bus, captured = _engine()
    rec = _registered(
        gate=_gate(on_condition="P(normal) > 0.7"),
        required_warm_feature_ids=frozenset({"ofi_ewma"}),
    )
    engine.register(rec)
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(
        warm={
            "ofi_ewma": True,
            "hawkes_intensity_zscore": False,
        },
        stale={
            "ofi_ewma": False,
            "hawkes_intensity_zscore": False,
        },
        values={"ofi_ewma": 1.0},
    ))

    assert len(captured) == 1


def test_full_emit_with_gate_on() -> None:
    engine, bus, captured = _engine()
    rec = _registered()
    engine.register(rec)
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(captured) == 1
    sig = captured[0]
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 120
    assert sig.symbol == "AAPL"
    assert sig.strategy_id == "alpha_x"
    assert sig.consumed_features == ("ofi_ewma",)
    assert sig.source_layer == "SIGNAL"


def test_horizon_mismatch_skips_dispatch() -> None:
    engine, bus, captured = _engine()
    sig = _RecordingSignal()
    engine.register(_registered(horizon_seconds=120, signal=sig))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(horizon_seconds=300))

    assert sig.calls == []
    assert captured == []


def test_gate_off_suppresses_emission() -> None:
    engine, bus, captured = _engine()
    sig = _RecordingSignal()
    engine.register(_registered(signal=sig))
    engine.attach()

    bus.publish(_regime_normal_low())
    bus.publish(_snapshot())

    assert sig.calls == []
    assert captured == []


def test_gate_closure_emits_flat_with_off_state() -> None:
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(sequence=10, boundary_index=1))
    bus.publish(_regime_normal_low())
    bus.publish(_snapshot(sequence=11, boundary_index=2))

    assert len(captured) == 2
    close_signal = captured[1]
    assert close_signal.direction == SignalDirection.FLAT
    assert close_signal.strategy_id == "alpha_x"
    assert close_signal.regime_gate_state == "OFF"


def test_flat_close_signal_carries_alpha_metadata() -> None:
    """The FLAT exit signal MUST carry the same alpha-level provenance
    metadata as a regular entry signal so post-trade forensics can
    attribute the unwind PnL to the correct mechanism family (Inv-13).
    """
    engine, bus, captured = _engine()
    engine.register(_registered(
        consumed_features=("ofi_ewma", "spread_z_30d"),
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    ))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(sequence=10, boundary_index=1))
    bus.publish(_regime_normal_low())
    bus.publish(_snapshot(sequence=11, boundary_index=2))

    assert len(captured) == 2
    close_signal = captured[1]
    assert close_signal.direction is SignalDirection.FLAT
    assert close_signal.consumed_features == ("ofi_ewma", "spread_z_30d")
    assert close_signal.trend_mechanism is TrendMechanism.KYLE_INFO
    assert close_signal.expected_half_life_seconds == 600
    # G12 disclosure fields propagate identically to the entry path.
    assert close_signal.disclosed_cost_total_bps == pytest.approx(5.0)
    assert close_signal.disclosed_margin_ratio == pytest.approx(1.8)
    assert close_signal.horizon_seconds == 120


def test_cold_start_missing_binding_swallowed() -> None:
    """Cold start: no RegimeState yet → gate raises UnknownIdentifierError."""
    engine, bus, captured = _engine()
    sig = _RecordingSignal()
    engine.register(_registered(signal=sig))
    engine.attach()

    bus.publish(_snapshot())                  # no RegimeState first

    assert sig.calls == []
    assert captured == []


def test_flat_direction_suppressed() -> None:
    engine, bus, captured = _engine()
    flat_sig = _RecordingSignal(direction=SignalDirection.FLAT)
    engine.register(_registered(signal=flat_sig))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(flat_sig.calls) == 1
    assert captured == []


def test_signal_returning_none_does_not_emit() -> None:
    engine, bus, captured = _engine()
    none_sig = _RecordingSignal(emit=False)
    engine.register(_registered(signal=none_sig))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(none_sig.calls) == 1
    assert captured == []


def test_signal_evaluate_exception_swallowed() -> None:
    class _Boom:
        signal_id = "alpha_x"
        signal_version = "1.0.0"

        def evaluate(self, snapshot, regime, params):  # noqa: D401
            raise RuntimeError("boom")

    engine, bus, captured = _engine()
    engine.register(_registered(signal=_Boom()))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert captured == []


def test_signal_returns_non_signal_discarded() -> None:
    class _Rogue:
        signal_id = "alpha_x"
        signal_version = "1.0.0"

        def evaluate(self, snapshot, regime, params):  # noqa: D401
            return "not a signal"

    engine, bus, captured = _engine()
    engine.register(_registered(signal=_Rogue()))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert captured == []


# ── Sensor / regime caches ──────────────────────────────────────────────


def test_sensor_cache_overlay_makes_value_available_to_gate() -> None:
    """Sensor reading cached → gate using that sensor evaluates True."""
    engine, bus, captured = _engine()
    gate = _gate(
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5 OR ofi_ewma < 0.5",
    )
    engine.register(_registered(gate=gate))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(SensorReading(
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=2.5,
    ))
    bus.publish(_snapshot())

    assert len(captured) == 1


def test_sensor_cache_skips_non_warm_readings() -> None:
    engine, bus, captured = _engine()
    gate = _gate(
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5",
    )
    engine.register(_registered(gate=gate))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(SensorReading(
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=2.5,
        warm=False,
    ))
    bus.publish(_snapshot())

    assert captured == []


def test_sensor_cache_skips_tuple_value() -> None:
    engine, bus, captured = _engine()
    gate = _gate(
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5",
    )
    engine.register(_registered(gate=gate))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(SensorReading(
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=(2.5, 3.0),
    ))
    bus.publish(_snapshot())

    assert captured == []


def test_cold_reading_invalidates_warm_cache_entry() -> None:
    """A previously-warm sensor that goes cold (sliding-window warm-up
    revert after a data gap) MUST drop its cached value.

    Without invalidation the gate would silently fire on the stale
    warm value forever — a real bug for sensors like ``ofi_ewma`` that
    lazily revert to ``warm=False`` after >300 s without quotes.  The
    expected fail-safe is that the next snapshot evaluation hits an
    ``UnknownIdentifierError`` (caught by the H8 / M6 path) which
    resets the gate latch to OFF (Inv-11 fail-safe default).
    """
    engine, bus, captured = _engine()
    gate = _gate(
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5 OR ofi_ewma < 0.5",
    )
    engine.register(_registered(gate=gate))
    engine.attach()

    bus.publish(_regime_normal_high())
    # First, warm reading populates the cache.
    bus.publish(SensorReading(
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=2.5,
        warm=True,
    ))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    assert len(captured) == 1

    # Sensor reverts to cold (e.g. sustained data gap).  This MUST drop
    # the cached 2.5 — otherwise the next snapshot evaluation would
    # spuriously fire on stale data.
    bus.publish(SensorReading(
        timestamp_ns=200_000,
        correlation_id="corr",
        sequence=4,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=0.0,
        warm=False,
    ))
    bus.publish(_snapshot(boundary_index=2, sequence=11))

    # No new entry signal should be emitted.  The gate transition
    # ON → OFF emits one FLAT exit signal, which is correct: the alpha
    # is no longer trading, and any open position should be unwound.
    assert len(captured) == 2
    assert captured[1].direction is SignalDirection.FLAT
    assert captured[1].regime_gate_state == "OFF"


def test_cold_tuple_reading_invalidates_warm_components() -> None:
    """Same invalidation semantics as the scalar case, for tuple sensors.

    A previously-warm tuple sensor that goes cold MUST drop every
    fanned-out component cache entry — otherwise downstream gate
    evaluation could fire on stale component values.
    """
    engine, _bus, _ = _engine()
    engine.register(_registered())
    engine.attach()

    # Warm tuple reading populates four component cache entries
    # (per ``_TUPLE_SENSOR_COMPONENTS["scheduled_flow_window"]``).
    engine._on_sensor_reading(SensorReading(  # type: ignore[arg-type]
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="scheduled_flow_window",
        sensor_version="1.0.0",
        value=(1.0, 60.0, 12345.0, 1.0),
        warm=True,
    ))
    expected_components = {
        "scheduled_flow_window_active",
        "seconds_to_window_close",
        "scheduled_flow_window_id_hash",
        "scheduled_flow_window_direction_prior",
    }
    cached_names = {
        name for (sym, name) in engine._sensor_cache if sym == "AAPL"
    }
    assert expected_components == cached_names

    # Cold reading drops every component, not just the leading one.
    engine._on_sensor_reading(SensorReading(  # type: ignore[arg-type]
        timestamp_ns=200_000,
        correlation_id="corr",
        sequence=4,
        symbol="AAPL",
        sensor_id="scheduled_flow_window",
        sensor_version="1.0.0",
        value=(0.0, -1.0, 0.0, 0.0),
        warm=False,
    ))
    cached_names_after = {
        name for (sym, name) in engine._sensor_cache if sym == "AAPL"
    }
    assert cached_names_after == set()


def test_cold_reading_with_open_position_emits_flat_close() -> None:
    """Sensor reverting to cold while gate is ON unwinds the position.

    H8 / M6 fail-safe: a previously-ON gate that loses its binding
    (sensor reverted to ``warm=False`` after a data gap) is reset to
    OFF and a FLAT signal is emitted so the open position is unwound
    rather than orphaned.  Without this, ``ofi_ewma`` (and any sensor
    with a sliding-window warm criterion) would leave positions
    behind whenever their sliding window emptied between snapshots.
    """
    engine, bus, captured = _engine()
    gate = _gate(
        # Both conditions reference ``ofi_ewma`` so once the cache
        # entry is dropped neither side can evaluate.
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5 OR ofi_ewma < -1.0",
    )
    engine.register(_registered(
        gate=gate,
        consumed_features=("ofi_ewma",),
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    ))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(SensorReading(
        timestamp_ns=1_900,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=2.5,
        warm=True,
    ))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    assert len(captured) == 1
    assert captured[0].direction is SignalDirection.LONG
    assert gate.is_on("AAPL")

    # Cold reading drops the cache entry.
    bus.publish(SensorReading(
        timestamp_ns=200_000,
        correlation_id="corr",
        sequence=4,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=0.0,
        warm=False,
    ))
    bus.publish(_snapshot(boundary_index=2, sequence=11))

    # Gate raised UnknownIdentifierError → was_on=True → FLAT close
    # emitted before the latch is reset to OFF.
    assert len(captured) == 2
    close = captured[1]
    assert close.direction is SignalDirection.FLAT
    assert close.regime_gate_state == "OFF"
    assert close.strategy_id == "alpha_x"
    # Forensic provenance propagates onto the FLAT close.
    assert close.consumed_features == ("ofi_ewma",)
    assert close.trend_mechanism is TrendMechanism.KYLE_INFO
    assert close.expected_half_life_seconds == 600
    assert not gate.is_on("AAPL")


def test_regime_cache_per_symbol_engine() -> None:
    """Regime cache scoped by (symbol, engine_name) — cross-symbol isolation."""
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()

    bus.publish(_regime_normal_high(symbol="MSFT"))
    bus.publish(_snapshot(symbol="AAPL"))

    # AAPL has no regime — gate raises UnknownIdentifier → suppressed.
    assert captured == []


# ── Sequence generator isolation ────────────────────────────────────────


def test_sequence_generator_dedicated_and_monotonic() -> None:
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    bus.publish(_snapshot(boundary_index=2, sequence=11))

    assert len(captured) == 2
    seqs = [s.sequence for s in captured]
    assert seqs == sorted(seqs)
    assert seqs[1] == seqs[0] + 1


def test_attach_is_idempotent() -> None:
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()
    engine.attach()                            # second call: no-op

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    # Single subscription → exactly one captured signal.
    assert len(captured) == 1


# ── Phase-3.1 trend_mechanism propagation (§20.6) ──────────────────────


def test_default_metadata_preserves_v02_behavior() -> None:
    """Default ``RegisteredSignal`` (no mechanism declared) → emitted
    ``Signal`` carries ``trend_mechanism=None`` and
    ``expected_half_life_seconds=0`` — bit-identical to v0.2.
    """
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(captured) == 1
    sig = captured[0]
    assert sig.trend_mechanism is None
    assert sig.expected_half_life_seconds == 0


def test_declared_mechanism_propagates_to_signal() -> None:
    """When the alpha declares ``trend_mechanism:`` and
    ``expected_half_life_seconds:``, the engine stamps both fields on
    every emitted ``Signal``.
    """
    engine, bus, captured = _engine()
    engine.register(_registered(
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    ))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())
    bus.publish(_snapshot(boundary_index=2, sequence=11))

    assert len(captured) == 2
    for sig in captured:
        assert sig.trend_mechanism is TrendMechanism.KYLE_INFO
        assert sig.expected_half_life_seconds == 600


def test_engine_stamps_g12_disclosure_fields() -> None:
    """HorizonSignalEngine copies load-time G12 totals onto every Signal."""
    engine, bus, captured = _engine()
    engine.register(_registered())
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(captured) == 1
    sig = captured[0]
    assert sig.disclosed_cost_total_bps == pytest.approx(5.0)
    assert sig.disclosed_margin_ratio == pytest.approx(1.8)


def test_alpha_supplied_mechanism_overrides_registered_default() -> None:
    """If the alpha returns a ``Signal`` that already carries its own
    ``trend_mechanism``, the engine does NOT overwrite it — alpha wins.
    """

    class _MechanismAwareSignal:
        signal_id = "alpha_x"
        signal_version = "1.0.0"

        def evaluate(
            self,
            snapshot: HorizonFeatureSnapshot,
            regime: Any,
            params: Mapping[str, Any],
        ) -> Signal:
            return Signal(
                timestamp_ns=snapshot.timestamp_ns,
                correlation_id=snapshot.correlation_id,
                sequence=0,
                symbol=snapshot.symbol,
                strategy_id="alpha_x",
                direction=SignalDirection.LONG,
                strength=0.5,
                edge_estimate_bps=8.0,
                trend_mechanism=TrendMechanism.HAWKES_SELF_EXCITE,
                expected_half_life_seconds=30,
            )

    engine, bus, captured = _engine()
    engine.register(_registered(
        signal=_MechanismAwareSignal(),  # type: ignore[arg-type]
        trend_mechanism=TrendMechanism.KYLE_INFO,  # would-be default
        expected_half_life_seconds=600,
    ))
    engine.attach()

    bus.publish(_regime_normal_high())
    bus.publish(_snapshot())

    assert len(captured) == 1
    assert captured[0].trend_mechanism is TrendMechanism.HAWKES_SELF_EXCITE
    assert captured[0].expected_half_life_seconds == 30
