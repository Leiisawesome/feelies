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


def _engine_with_metrics() -> tuple[HorizonSignalEngine, EventBus, list[Signal], InMemoryMetricCollector]:
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
