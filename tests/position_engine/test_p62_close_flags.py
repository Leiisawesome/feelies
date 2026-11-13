"""P-62 close flags, outside the battery (Bugbot on PR #312; D-246 (5))."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import Event, PositionClosed, SlicePositionUpdate
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.identifiers import SequenceGenerator
from feelies.position.engine import PositionEngine, PositionRecordSink

_STRATEGY = "alpha"
_SYMBOL = "SYN"
_SHARES = 4
_STAMP = 5_000_000_000
_T_NS = 10_000_000_000


def _policy() -> ExitPolicy:
    return ExitPolicy(
        archetype="liquidity_provision",
        declared_shape=None,
        curve_ref="ARBITRARY_NOT_CALIBRATED",
        fee_round_trip_ticks=1,
        horizon=HorizonPolicy(T_ns=_T_NS, cutoff_before_close_ns=1),
        adverse=AdversePolicy(
            centre_ticks=10,
            band_ticks=0,
            lo_ticks=2,
            hi_ticks=20,
            blind_limit_ns=1,
        ),
        favorable=FavorablePolicy(form="fixed", quiet_limit_ns=1, target_ticks=4),
    )


def _engine() -> tuple[EventBus, list[Event], PositionEngine]:
    bus = EventBus()
    engine = PositionEngine(
        bus,
        SequenceGenerator(stream="position", thread_safe=False),
        {_STRATEGY: _policy()},
        clock=SimulatedClock(1_000),
    )
    engine.attach()
    sink = PositionRecordSink(bus)
    sink.attach()
    seen: list[Event] = []
    bus.subscribe_all(seen.append)
    return bus, seen, engine


def _fill(
    sequence: int,
    *,
    order_id: str,
    fill_quantity: int,
    quantity: int,
) -> SlicePositionUpdate:
    return SlicePositionUpdate(
        timestamp_ns=sequence,
        correlation_id=f"fill-{sequence}",
        sequence=sequence,
        source_layer="kernel",
        symbol=_SYMBOL,
        strategy_id=_STRATEGY,
        order_id=order_id,
        fill_price=Decimal("1.01"),
        fill_quantity=fill_quantity,
        fill_ack_sequence=sequence,
        fill_timestamp_ns=_STAMP,
        quantity=quantity,
        avg_entry_price=Decimal("1.01"),
    )


def _birth(bus: EventBus) -> None:
    bus.publish(_fill(1, order_id="entry", fill_quantity=_SHARES, quantity=_SHARES))


def _arm_blind_exit(engine: PositionEngine) -> str:
    cell = engine._open[(_STRATEGY, _SYMBOL)]
    armed = replace(cell, state="EXITING", exit_reason="ADVERSE", exited_blind=True)
    engine._put(armed)
    return armed.cell_id


def _closed(seen: list[Event]) -> list[PositionClosed]:
    return [event for event in seen if isinstance(event, PositionClosed)]


def test_blind_gate_exit_fill_keeps_the_flag() -> None:
    bus, seen, engine = _engine()
    _birth(bus)
    cell_id = _arm_blind_exit(engine)
    bus.publish(
        _fill(
            2,
            order_id=f"{cell_id}|EXIT|1",
            fill_quantity=-_SHARES,
            quantity=0,
        )
    )
    closed = _closed(seen)
    assert len(closed) == 1
    assert closed[0].exit_reason == "ADVERSE"
    assert closed[0].exited_on_unusable_data is True


def test_end_of_tape_after_blind_exit_is_not_flagged() -> None:
    bus, seen, engine = _engine()
    _birth(bus)
    _arm_blind_exit(engine)
    engine.finalize()
    closed = _closed(seen)
    assert len(closed) == 1
    assert closed[0].exit_reason == "END_OF_TAPE"
    assert closed[0].exited_on_unusable_data is False
