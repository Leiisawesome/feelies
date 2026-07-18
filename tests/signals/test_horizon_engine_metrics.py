"""ENG-2: signal-engine observability counters.

The ``HorizonSignalEngine`` was previously log-only.  These tests lock the four
counters it now emits (gate transitions, entry suppression, fail-safe unwinds,
emitted signals) into a dedicated metrics sequence — off the locked Signal
stream, so they cannot perturb the Level-2 parity hash.
"""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.core.events import Signal, SignalDirection
from feelies.core.identifiers import SequenceGenerator
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.signals.horizon_engine import HorizonSignalEngine

from tests.signals.test_horizon_signal_engine import (
    _RecordingSignal,
    _registered,
    _regime_normal_high,
    _snapshot,
)


def _engine_with_metrics() -> tuple[
    HorizonSignalEngine, EventBus, list[Signal], InMemoryMetricCollector
]:
    bus = EventBus()
    collector = InMemoryMetricCollector()
    engine = HorizonSignalEngine(
        bus=bus,
        signal_sequence_generator=SequenceGenerator(),
        metric_collector=collector,
    )
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    return engine, bus, captured, collector


def _count(collector: InMemoryMetricCollector, name: str) -> int:
    s = collector.get_summary("signal", name)
    return s.count if s is not None else 0


def test_entry_suppressed_counter_increments_when_required_feature_cold() -> None:
    engine, bus, captured, collector = _engine_with_metrics()
    engine.register(_registered(required_warm_feature_ids=frozenset({"ofi_ewma_zscore"})))
    engine.attach()
    bus.publish(_regime_normal_high())  # gate ON: P(normal)=0.9 > 0.7
    # Required feature present in the snapshot but NOT warm → entry suppressed.
    bus.publish(
        _snapshot(
            values={},
            warm={"ofi_ewma_zscore": False},
            stale={"ofi_ewma_zscore": False},
        )
    )
    assert captured == []  # no entry signal
    assert _count(collector, "feelies.signal.entry.suppressed") == 1
    # Reason is tagged on the raw event.
    suppressed = [e for e in collector.events if e.name == "feelies.signal.entry.suppressed"]
    assert suppressed[0].tags == {"alpha_id": "alpha_x", "reason": "not_warm"}


def test_gate_transition_not_double_counted_across_entry_blocked_boundary() -> None:
    """Regression test — audit P1 2026-07-02.

    A single logical OFF->ON admission must count once.  When the gate's
    ``on_condition`` first evaluates true on an entry-blocked (cold/stale)
    snapshot, ``RegimeGate.evaluate(mutate=False)`` correctly withholds the
    latch commit — the transition metric must not fire until the real
    admission commits on a later, clean snapshot.
    """
    engine, bus, captured, collector = _engine_with_metrics()
    engine.register(
        _registered(
            signal=_RecordingSignal(direction=SignalDirection.LONG),
            required_warm_feature_ids=frozenset({"ofi_ewma_zscore"}),
        )
    )
    engine.attach()
    bus.publish(_regime_normal_high())  # on_condition true: P(normal)=0.9 > 0.7

    # Boundary N: required feature cold -> entry blocked, latch not armed.
    bus.publish(
        _snapshot(
            sequence=10,
            boundary_index=1,
            values={},
            warm={"ofi_ewma_zscore": False},
            stale={"ofi_ewma_zscore": False},
        )
    )
    assert captured == []
    assert _count(collector, "feelies.signal.gate.transition") == 0
    assert _count(collector, "feelies.signal.entry.suppressed") == 1
    assert engine.signals[0].gate.is_on("AAPL") is False

    # Boundary N+1: feature recovers -> the real admission commits once.
    bus.publish(
        _snapshot(
            sequence=11,
            boundary_index=2,
            values={},
            warm={"ofi_ewma_zscore": True},
            stale={"ofi_ewma_zscore": False},
        )
    )
    assert len(captured) == 1
    assert _count(collector, "feelies.signal.gate.transition") == 1
    assert _count(collector, "feelies.signal.emitted") == 1


def test_gate_transition_on_and_emitted_counters_on_real_signal() -> None:
    engine, bus, captured, collector = _engine_with_metrics()
    engine.register(_registered(signal=_RecordingSignal(direction=SignalDirection.LONG)))
    engine.attach()
    bus.publish(_regime_normal_high())  # OFF → ON admission
    bus.publish(_snapshot(warm={"ofi_ewma": True}, stale={"ofi_ewma": False}))
    assert len(captured) == 1 and captured[0].direction == SignalDirection.LONG
    assert _count(collector, "feelies.signal.gate.transition") == 1  # to=ON
    assert _count(collector, "feelies.signal.emitted") == 1
    emitted = [e for e in collector.events if e.name == "feelies.signal.emitted"]
    assert emitted[0].tags == {"alpha_id": "alpha_x", "direction": "LONG"}


def test_duplicate_boundary_is_metered_but_still_dispatched() -> None:
    """Audit P2 2026-07-02: a non-increasing ``boundary_index`` for the same
    ``(symbol, alpha_id)`` is logged and metered, never blocked — dispatch
    still proceeds normally (Inv-11: observe, don't speculatively reject).
    """
    engine, bus, captured, collector = _engine_with_metrics()
    engine.register(_registered(signal=_RecordingSignal(direction=SignalDirection.LONG)))
    engine.attach()
    bus.publish(_regime_normal_high())
    bus.publish(
        _snapshot(
            sequence=10, boundary_index=1, warm={"ofi_ewma": True}, stale={"ofi_ewma": False}
        )
    )
    assert len(captured) == 1
    assert _count(collector, "feelies.signal.snapshot.duplicate_boundary") == 0

    # Same boundary_index dispatched again -> flagged as a duplicate/
    # out-of-order snapshot, but the engine still evaluates it normally
    # (demonstrating exactly the double-emission risk the metric exists to
    # surface, rather than silently dropping a possibly-legitimate replay).
    bus.publish(
        _snapshot(
            sequence=11, boundary_index=1, warm={"ofi_ewma": True}, stale={"ofi_ewma": False}
        )
    )
    assert len(captured) == 2
    assert _count(collector, "feelies.signal.snapshot.duplicate_boundary") == 1
    dup = [e for e in collector.events if e.name == "feelies.signal.snapshot.duplicate_boundary"]
    assert dup[0].tags == {"alpha_id": "alpha_x", "symbol": "AAPL"}


def test_increasing_boundary_index_never_flagged_as_duplicate() -> None:
    engine, bus, captured, collector = _engine_with_metrics()
    engine.register(_registered(signal=_RecordingSignal(direction=SignalDirection.LONG)))
    engine.attach()
    bus.publish(_regime_normal_high())
    for i in range(1, 4):
        bus.publish(
            _snapshot(
                sequence=10 + i,
                boundary_index=i,
                warm={"ofi_ewma": True},
                stale={"ofi_ewma": False},
            )
        )
    assert len(captured) == 3
    assert _count(collector, "feelies.signal.snapshot.duplicate_boundary") == 0


def test_no_collector_is_a_silent_no_op() -> None:
    bus = EventBus()
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
    engine.register(_registered(signal=_RecordingSignal(direction=SignalDirection.LONG)))
    engine.attach()
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    bus.publish(_regime_normal_high())
    bus.publish(_snapshot(warm={"ofi_ewma": True}, stale={"ofi_ewma": False}))
    # Engine still works; metric emission is simply skipped.
    assert len(captured) == 1
