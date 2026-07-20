"""Preserve the nominal grid boundary separately from trigger time."""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonTick, NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler

_NS = 1_000_000_000
_OPEN = 1_000 * _NS  # arbitrary session-open anchor


def _quote(ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def test_scheduler_stamps_nominal_boundary_vs_trigger_on_sparse_tape() -> None:
    sched = HorizonScheduler(
        horizons=frozenset({30}),
        session_id="T",
        symbols=frozenset({"AAPL"}),
        session_open_ns=_OPEN,
        sequence_generator=SequenceGenerator(),
    )
    # First event lands 95 s in — it crosses the 90 s boundary (k=3) but
    # arrives 5 s late.
    trigger = _OPEN + 95 * _NS
    ticks = sched.on_event(_quote(trigger))
    assert ticks, "expected a boundary tick"
    for tick in ticks:
        assert tick.boundary_index == 3
        # Nominal boundary is the exact grid point ...
        assert tick.boundary_ts_ns == _OPEN + 90 * _NS
        # ... while the event/trigger time is 5 s later.
        assert tick.timestamp_ns == trigger
        assert tick.boundary_ts_ns < tick.timestamp_ns


def test_aggregator_carries_boundary_ts_onto_snapshot() -> None:
    agg = HorizonAggregator(
        bus=EventBus(),
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=120,
        sequence_generator=SequenceGenerator(),
        horizon_features=[],  # passive mode — one empty snapshot per symbol
    )
    tick = HorizonTick(
        timestamp_ns=_OPEN + 95 * _NS,
        correlation_id="t",
        sequence=0,
        source_layer="SCHEDULER",
        horizon_seconds=30,
        boundary_index=3,
        boundary_ts_ns=_OPEN + 90 * _NS,
        session_id="T",
        scope="SYMBOL",
        symbol="AAPL",
    )
    snaps = agg.on_horizon_tick(tick)
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap.boundary_ts_ns == _OPEN + 90 * _NS
    assert snap.timestamp_ns == _OPEN + 95 * _NS  # trigger time preserved


def test_default_is_zero_for_directly_constructed_events() -> None:
    # Back-compat: a tick/snapshot built without the field reports the
    # "unset" sentinel rather than failing construction.
    tick = HorizonTick(
        timestamp_ns=1,
        correlation_id="t",
        sequence=0,
        source_layer="SCHEDULER",
        horizon_seconds=30,
        boundary_index=0,
        session_id="T",
        scope="UNIVERSE",
    )
    assert tick.boundary_ts_ns == 0
