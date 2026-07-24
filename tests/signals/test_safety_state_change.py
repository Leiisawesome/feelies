"""Phase 1 acceptance tests for the dual-permission ``SafetyStateChange`` event.

Covers (design rev 5 §3.1, §4.3; plan Phase 1):

* Default alpha (``decouple_gate_close=False``): the clean ON→OFF FLAT is
  retained *and* a ``SafetyStateChange`` is emitted — the emitted Signal stream
  is unchanged (bit-identical), the safety event is purely additive.
* Decoupled alpha (``decouple_gate_close=True``): the clean transition emits
  ``SafetyStateChange(safe=False)`` and **no** FLAT.
* All four legacy ``_publish_gate_close`` paths (clean transition + three
  fail-closed error paths) emit ``SafetyStateChange`` with the right ``reason``.
* Under decoupling **no** gate-close FLAT is emitted on any path — Phase 3
  removed the temporary Phase-1 error-path FLAT; the risk-layer exit composer
  actuates those fail-closed EXITs from the ``SafetyStateChange`` instead. A
  non-decoupled alpha still FLATs on every path (bit-identical).
* The event carries the full gate-close provenance (Inv-13).
* Replay determinism of the ``SafetyStateChange`` sequence (Inv-5), and its
  isolation from the locked Signal sequence stream.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    SafetyStateChange,
    SensorReading,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import RegimeGate

_ENGINE_NAME = "hmm_3state_fractional"


# ── Helpers ─────────────────────────────────────────────────────────────


class _RecordingSignal:
    """Minimal :class:`HorizonSignal`-shaped callable — LONG on every call."""

    signal_id = "alpha_x"
    signal_version = "1.0.0"

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: Any,
        params: Mapping[str, Any],
    ) -> Signal | None:
        return Signal(
            timestamp_ns=snapshot.timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=0,  # patched by the engine
            symbol=snapshot.symbol,
            strategy_id=self.signal_id,
            direction=SignalDirection.LONG,
            strength=0.5,
            edge_estimate_bps=8.0,
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


def _gate(
    *,
    on_condition: str = "P(normal) > 0.7",
    off_condition: str = "P(normal) < 0.5",
) -> RegimeGate:
    return RegimeGate(
        alpha_id="alpha_x",
        on_condition=on_condition,
        off_condition=off_condition,
        engine_name=_ENGINE_NAME,
    )


def _registered(
    *,
    gate: RegimeGate | None = None,
    decouple_gate_close: bool = False,
    consumed_features: tuple[str, ...] = ("ofi_ewma",),
    trend_mechanism: TrendMechanism | None = None,
    expected_half_life_seconds: int = 0,
) -> RegisteredSignal:
    return RegisteredSignal(
        alpha_id="alpha_x",
        horizon_seconds=120,
        signal=_RecordingSignal(),
        params={},
        gate=gate or _gate(),
        cost_arithmetic=_cost(),
        consumed_features=consumed_features,
        trend_mechanism=trend_mechanism,
        expected_half_life_seconds=expected_half_life_seconds,
        decouple_gate_close=decouple_gate_close,
    )


def _engine(
    registered: RegisteredSignal,
) -> tuple[EventBus, list[Signal], list[SafetyStateChange]]:
    bus = EventBus()
    signals: list[Signal] = []
    safety: list[SafetyStateChange] = []
    bus.subscribe(Signal, signals.append)  # type: ignore[arg-type]
    bus.subscribe(SafetyStateChange, safety.append)  # type: ignore[arg-type]
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
    engine.register(registered)
    engine.attach()
    return bus, signals, safety


def _regime(posterior_normal: float, *, ts_ns: int, seq: int) -> RegimeState:
    return RegimeState(
        timestamp_ns=ts_ns,
        correlation_id="corr",
        sequence=seq,
        symbol="AAPL",
        engine_name=_ENGINE_NAME,
        state_names=("normal",),
        posteriors=(posterior_normal,),
        dominant_state=0,
        dominant_name="normal",
    )


def _snapshot(
    *,
    boundary_index: int,
    sequence: int,
    timestamp_ns: int = 2_000,
    values: dict[str, float] | None = None,
    warm: dict[str, bool] | None = None,
    stale: dict[str, bool] | None = None,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=timestamp_ns,
        correlation_id="corr",
        sequence=sequence,
        symbol="AAPL",
        horizon_seconds=120,
        boundary_index=boundary_index,
        values=values or {},
        warm=warm or {},
        stale=stale or {},
    )


def _ofi_reading(value: float, *, ts_ns: int, seq: int, warm: bool = True) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id="corr",
        sequence=seq,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=value,
        warm=warm,
    )


def _drive_clean_transition(
    bus: EventBus,
) -> None:
    """Latch the gate ON, then a clean ON→OFF close."""
    bus.publish(_regime(0.9, ts_ns=1_000, seq=1))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    bus.publish(_regime(0.3, ts_ns=1_500, seq=2))
    bus.publish(_snapshot(boundary_index=2, sequence=11))


# ── Clean transition: default vs decoupled ───────────────────────────────


def test_default_clean_transition_flats_and_emits_safety_event() -> None:
    """Default (non-decoupled): the FLAT is retained *and* a SafetyStateChange
    is emitted on the clean transition. The FLAT Signal stream is unchanged."""
    bus, signals, safety = _engine(_registered(decouple_gate_close=False))
    _drive_clean_transition(bus)

    # Signal stream: LONG entry then FLAT close — exactly today's behaviour.
    assert [s.direction for s in signals] == [SignalDirection.LONG, SignalDirection.FLAT]
    assert signals[1].regime_gate_state == "OFF"

    # Additive safety event on the clean transition.
    assert len(safety) == 1
    assert safety[0].safe is False
    assert safety[0].reason == "clean_transition"
    assert safety[0].strategy_id == "alpha_x"


def test_decoupled_clean_transition_suppresses_flat_emits_safety_event() -> None:
    """Decoupled: the clean transition emits SafetyStateChange(safe=False) and
    NO gate-close FLAT."""
    bus, signals, safety = _engine(_registered(decouple_gate_close=True))
    _drive_clean_transition(bus)

    # Only the LONG entry — the FLAT is suppressed.
    assert [s.direction for s in signals] == [SignalDirection.LONG]
    assert all(s.direction is not SignalDirection.FLAT for s in signals)

    assert len(safety) == 1
    assert safety[0].reason == "clean_transition"
    assert safety[0].safe is False


def test_decoupled_gate_still_latches_off() -> None:
    """Suppressing the FLAT must not suppress the gate latch transition — the
    gate is genuinely OFF (blocks new entries) after a decoupled clean close."""
    gate = _gate()
    bus, signals, _ = _engine(_registered(gate=gate, decouple_gate_close=True))
    _drive_clean_transition(bus)
    assert gate.is_on("AAPL") is False


# ── Provenance (Inv-13) ──────────────────────────────────────────────────


def test_safety_state_change_carries_full_provenance() -> None:
    """The SafetyStateChange carries the same alpha-level provenance the
    gate-close FLAT carries today (Inv-13)."""
    bus, _signals, safety = _engine(
        _registered(
            decouple_gate_close=True,
            consumed_features=("ofi_ewma", "spread_z_30d"),
            trend_mechanism=TrendMechanism.KYLE_INFO,
            expected_half_life_seconds=600,
        )
    )
    _drive_clean_transition(bus)

    assert len(safety) == 1
    evt = safety[0]
    assert evt.symbol == "AAPL"
    assert evt.strategy_id == "alpha_x"
    assert evt.regime_gate_state == "OFF"
    assert evt.consumed_features == ("ofi_ewma", "spread_z_30d")
    assert evt.trend_mechanism is TrendMechanism.KYLE_INFO
    assert evt.expected_half_life_seconds == 600
    # G12 disclosure fields propagate identically to the entry / FLAT path.
    assert evt.disclosed_cost_total_bps == pytest.approx(5.0)
    assert evt.disclosed_margin_ratio == pytest.approx(1.8)
    assert evt.source_layer == "SIGNAL"
    # Correlation ties the safety event to the triggering snapshot.
    assert evt.correlation_id == "corr"


# ── All four legacy _publish_gate_close paths ────────────────────────────


def _drive_missing_binding(bus: EventBus) -> None:
    """Latch ON with a warm sensor binding, then drop it → UnknownIdentifierError."""
    gate_bus_reading_seq = 3
    bus.publish(_regime(0.9, ts_ns=1_000, seq=1))
    bus.publish(_ofi_reading(2.5, ts_ns=1_900, seq=gate_bus_reading_seq, warm=True))
    bus.publish(
        _snapshot(
            boundary_index=1,
            sequence=10,
            values={"ofi_ewma": 2.5},
            warm={"ofi_ewma": True},
            stale={"ofi_ewma": False},
        )
    )
    # Cold reading drops the cached binding; the ON gate can no longer resolve.
    bus.publish(_ofi_reading(0.0, ts_ns=200_000, seq=4, warm=False))
    bus.publish(_snapshot(boundary_index=2, sequence=11, timestamp_ns=200_000))


def _missing_binding_gate() -> RegimeGate:
    return _gate(
        on_condition="P(normal) > 0.7 AND ofi_ewma > 1.0",
        off_condition="P(normal) < 0.5 OR ofi_ewma < -1.0",
    )


def _drive_gate_error(bus: EventBus) -> None:
    """Latch ON, then evaluate an off_condition referencing an undeclared regime
    state → UnknownRegimeStateError (a RegimeGateError)."""
    bus.publish(_regime(0.9, ts_ns=1_000, seq=1))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    bus.publish(_regime(0.9, ts_ns=1_500, seq=2))
    bus.publish(_snapshot(boundary_index=2, sequence=11))


def _gate_error_gate() -> RegimeGate:
    # 'toxic' is absent from the published state_names → P(toxic) raises.
    return _gate(on_condition="P(normal) > 0.7", off_condition="P(toxic) > 0.5")


def _drive_arithmetic_error(bus: EventBus) -> None:
    """Latch ON, then divide by a zero sensor value in the off_condition."""
    bus.publish(_regime(0.9, ts_ns=1_000, seq=1))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    # ofi_ewma == 0 makes the off_condition divide by zero on the ON gate.
    bus.publish(_ofi_reading(0.0, ts_ns=1_900, seq=3, warm=True))
    bus.publish(
        _snapshot(
            boundary_index=2,
            sequence=11,
            values={"ofi_ewma": 0.0},
        )
    )


def _arithmetic_error_gate() -> RegimeGate:
    return _gate(on_condition="P(normal) > 0.7", off_condition="(1.0 / ofi_ewma) < 0.0")


_FOUR_PATHS = (
    ("clean_transition", _gate, _drive_clean_transition),
    ("missing_binding", _missing_binding_gate, _drive_missing_binding),
    ("gate_error", _gate_error_gate, _drive_gate_error),
    ("arithmetic_error", _arithmetic_error_gate, _drive_arithmetic_error),
)


@pytest.mark.parametrize(
    "reason,gate_factory,driver",
    _FOUR_PATHS,
    ids=[reason for reason, _g, _d in _FOUR_PATHS],
)
def test_all_four_paths_emit_safety_state_change(
    reason: str,
    gate_factory: Any,
    driver: Any,
) -> None:
    """Every legacy ``_publish_gate_close`` path publishes exactly one
    ``SafetyStateChange(safe=False)`` tagged with the matching reason."""
    bus, _signals, safety = _engine(_registered(gate=gate_factory(), decouple_gate_close=True))
    driver(bus)

    assert len(safety) == 1, f"{reason}: expected one SafetyStateChange, got {len(safety)}"
    assert safety[0].reason == reason
    assert safety[0].safe is False
    assert safety[0].strategy_id == "alpha_x"


@pytest.mark.parametrize(
    "reason,gate_factory,driver",
    [p for p in _FOUR_PATHS if p[0] != "clean_transition"],
    ids=[reason for reason, _g, _d in _FOUR_PATHS if reason != "clean_transition"],
)
def test_error_paths_emit_no_flat_under_decoupling(
    reason: str,
    gate_factory: Any,
    driver: Any,
) -> None:
    """Phase 3: a decoupled alpha emits **no** gate-close FLAT on the three
    fail-closed error paths — the risk-layer exit composer actuates the
    fail-closed EXIT from the ``SafetyStateChange`` instead. This removes the
    temporary Phase-1 error-path FLAT that held the unwind before the composer
    existed (plan Phase 3; design §3.1)."""
    bus, signals, safety = _engine(_registered(gate=gate_factory(), decouple_gate_close=True))
    driver(bus)

    flats = [s for s in signals if s.direction is SignalDirection.FLAT]
    assert flats == [], f"{reason}: decoupled error path must not emit a SIGNAL FLAT"
    # The typed safety event is still emitted — it is the composer's trigger.
    assert [e.reason for e in safety] == [reason]


@pytest.mark.parametrize(
    "reason,gate_factory,driver",
    [p for p in _FOUR_PATHS if p[0] != "clean_transition"],
    ids=[reason for reason, _g, _d in _FOUR_PATHS if reason != "clean_transition"],
)
def test_error_paths_still_flat_when_not_decoupled(
    reason: str,
    gate_factory: Any,
    driver: Any,
) -> None:
    """Default (non-decoupled): the error-path FLAT is retained on every path —
    bit-identical to today, so nothing strands for a non-decoupled alpha (Inv-5)."""
    bus, signals, safety = _engine(_registered(gate=gate_factory(), decouple_gate_close=False))
    driver(bus)

    flats = [s for s in signals if s.direction is SignalDirection.FLAT]
    assert len(flats) == 1, f"{reason}: non-decoupled error-path FLAT must be retained"
    assert flats[0].regime_gate_state == "OFF"
    # ...and the safety event is still emitted alongside it (purely additive).
    assert [e.reason for e in safety] == [reason]


# ── Determinism (Inv-5) + sequence isolation ─────────────────────────────


def _replay_safety_stream() -> list[tuple[int, str, bool, str]]:
    """Drive ON→OFF→ON→OFF for a decoupled alpha and return a canonical
    serialization of the emitted SafetyStateChange stream."""
    gate = _gate()
    bus, _signals, safety = _engine(_registered(gate=gate, decouple_gate_close=True))
    bus.publish(_regime(0.9, ts_ns=1_000, seq=1))
    bus.publish(_snapshot(boundary_index=1, sequence=10))
    bus.publish(_regime(0.3, ts_ns=1_500, seq=2))
    bus.publish(_snapshot(boundary_index=2, sequence=11))
    bus.publish(_regime(0.9, ts_ns=2_000, seq=3))
    bus.publish(_snapshot(boundary_index=3, sequence=12))
    bus.publish(_regime(0.3, ts_ns=2_500, seq=4))
    bus.publish(_snapshot(boundary_index=4, sequence=13))
    return [(e.sequence, e.reason, e.safe, e.strategy_id) for e in safety]


def test_replay_determinism_safety_sequence() -> None:
    """Same inputs → identical SafetyStateChange sequence (Inv-5)."""
    a = _replay_safety_stream()
    b = _replay_safety_stream()
    assert a == b
    # Two clean closes, monotonic dedicated-stream sequence starting at 0.
    assert [seq for seq, _r, _s, _sid in a] == [0, 1]
    assert [reason for _seq, reason, _s, _sid in a] == ["clean_transition", "clean_transition"]


def test_safety_sequence_isolated_from_signal_stream() -> None:
    """The SafetyStateChange sequence is a dedicated stream: emitting it does
    not consume Signal sequence numbers (the FLAT keeps its slot)."""
    bus, signals, safety = _engine(_registered(decouple_gate_close=False))
    _drive_clean_transition(bus)

    # Signal seqs come from the engine's own generator: LONG=0, FLAT=1.
    assert [s.sequence for s in signals] == [0, 1]
    # Safety event uses its own generator, independently starting at 0.
    assert [e.sequence for e in safety] == [0]
