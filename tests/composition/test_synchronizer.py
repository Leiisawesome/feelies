"""Tests for :class:`feelies.composition.synchronizer.UniverseSynchronizer`."""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.core.events import (
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    Signal,
    SignalDirection,
)
from feelies.core.identifiers import SequenceGenerator


def _make_signal(*, symbol: str, ts_ns: int, horizon: int = 300) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"sig:{symbol}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id="alpha_a",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
        horizon_seconds=horizon,
    )


def _make_snapshot(*, symbol: str, ts_ns: int, bi: int, horizon: int = 300):
    return HorizonFeatureSnapshot(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"snap:{symbol}:{bi}",
        source_layer="L2",
        symbol=symbol,
        horizon_seconds=horizon,
        boundary_index=bi,
    )


def _make_tick(*, ts_ns: int, bi: int, horizon: int = 300) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"tick:{horizon}:{bi}",
        source_layer="SCHEDULER",
        horizon_seconds=horizon,
        boundary_index=bi,
        session_id="TEST_SESSION",
        scope="UNIVERSE",
        symbol=None,
    )


def test_emits_one_context_per_universe_tick():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL", "MSFT"),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_snapshot(symbol="MSFT", ts_ns=1_100, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    bus.publish(_make_signal(symbol="MSFT", ts_ns=1_100))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.horizon_seconds == 300
    assert ctx.boundary_index == 1
    assert ctx.universe == ("AAPL", "MSFT")
    assert ctx.completeness == 1.0
    assert all(s is not None for s in ctx.signals_by_symbol.values())


def test_emits_degenerate_context_when_signals_missing():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL", "MSFT", "TSLA"),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.completeness == 1 / 3
    assert ctx.signals_by_symbol["AAPL"] is not None
    assert ctx.signals_by_symbol["MSFT"] is None
    assert ctx.signals_by_symbol["TSLA"] is None


def test_idempotent_per_boundary():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    tick = _make_tick(ts_ns=2_000, bi=1)
    bus.publish(tick)
    bus.publish(tick)
    bus.publish(tick)

    assert len(captured) == 1


def test_attach_is_noop_for_empty_universe():
    bus = EventBus()
    sync = UniverseSynchronizer(
        bus=bus,
        universe=(),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()
    bus.publish(_make_tick(ts_ns=2_000, bi=1))
    # No subscription installed → no event raised.


def test_separate_horizons_independent():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300, 900),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=100, bi=1, horizon=300))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=100, horizon=300))
    bus.publish(_make_tick(ts_ns=200, bi=1, horizon=300))

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=300, bi=1, horizon=900))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=300, horizon=900))
    bus.publish(_make_tick(ts_ns=400, bi=1, horizon=900))

    assert len(captured) == 2
    assert {c.horizon_seconds for c in captured} == {300, 900}
