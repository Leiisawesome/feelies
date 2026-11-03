"""P-52 invalidation intake. Production engine; the latch acts at the next rail."""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    DeRiskRequirement,
    Event,
    ExitTriggeredPath,
    MarkRailUpdate,
    PositionClosed,
    RailOrientation,
    Side,
    Signal,
    SignalDirection,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.identifiers import SequenceGenerator
from feelies.position.engine import PositionEngine, PositionRecordSink

_STRATEGY = "alpha"
_SYMBOL = "SYN"
_SHARES = 4
_STAMP = 5_000_000_000
_T_NS = 10_000_000_000
_DEADLINE = _STAMP + _T_NS
_BEFORE = _DEADLINE - 1
_AFTER = _DEADLINE + 1_000
_MARK = 99


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


def _orient() -> RailOrientation:
    return RailOrientation(
        paying_mark_cents=101,
        valuation_mark_cents=100,
        worst_side_mark_cents=100,
        forced_exit_mark_cents=_MARK,
        dwelled_exit_mark_cents=100,
        paying_size=10,
        valuation_size=10,
        paying_age_ns=0,
        valuation_age_ns=0,
        paying_absent_for_ns=0,
        valuation_absent_for_ns=0,
        paying_side_absent=False,
        valuation_side_absent=False,
        dwell_window_clean=True,
    )


def _engine() -> tuple[EventBus, list[Event]]:
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
    return bus, seen


def _rail(sequence: int, event_ns: int) -> MarkRailUpdate:
    side = _orient()
    return MarkRailUpdate(
        timestamp_ns=event_ns,
        correlation_id=f"rail-{sequence}",
        sequence=sequence,
        source_layer="portfolio",
        symbol=_SYMBOL,
        quote_sequence=sequence,
        event_timestamp_ns=event_ns,
        long=side,
        short=side,
        symbol_quiet_ns=0,
        locked=False,
        crossed=False,
        feed_gap_before=False,
        warmed_up=True,
    )


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


def _signal(sequence: int, direction: SignalDirection) -> Signal:
    return Signal(
        timestamp_ns=sequence,
        correlation_id=f"sig-{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        strategy_id=_STRATEGY,
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
    )


def _cell_id() -> str:
    return f"{_SYMBOL}|{_STRATEGY}|{_STAMP}|LONG"


def _reqs(seen: list[Event]) -> list[DeRiskRequirement]:
    return [event for event in seen if isinstance(event, DeRiskRequirement)]


def _closed(seen: list[Event]) -> list[PositionClosed]:
    return [event for event in seen if isinstance(event, PositionClosed)]


def _birth(bus: EventBus) -> None:
    bus.publish(_fill(1, order_id="entry", fill_quantity=_SHARES, quantity=_SHARES))


def _exit_fill(bus: EventBus, sequence: int) -> None:
    bus.publish(
        _fill(
            sequence,
            order_id=f"{_cell_id()}|EXIT|1",
            fill_quantity=-_SHARES,
            quantity=0,
        )
    )


def _path(name: str, trigger: str) -> ExitTriggeredPath:
    return ExitTriggeredPath(path=name, proposed_price_cents=_MARK, trigger=trigger)


def _horizon_paths() -> tuple[ExitTriggeredPath, ...]:
    return (_path("HORIZON", "DEADLINE"),)


def _invalidation_paths() -> tuple[ExitTriggeredPath, ...]:
    return (_path("INVALIDATION", "INVALIDATION"),)


def _both_paths() -> tuple[ExitTriggeredPath, ...]:
    return (_path("HORIZON", "DEADLINE"), _path("INVALIDATION", "INVALIDATION"))


def test_opposite_signal_exits_invalidation_before_deadline() -> None:
    """OPEN cell, opposite signal, next rail before the deadline."""
    bus, seen = _engine()
    _birth(bus)
    bus.publish(_signal(2, SignalDirection.SHORT))
    bus.publish(_rail(3, _BEFORE))
    _exit_fill(bus, 4)
    cell_id = _cell_id()
    assert [(item.reason, item.order_id, item.side, item.quantity) for item in _reqs(seen)] == [
        ("INVALIDATION", f"{cell_id}|EXIT|1", Side.SELL, _SHARES)
    ]
    assert [(item.exit_reason, item.triggered_paths) for item in _closed(seen)] == [
        ("INVALIDATION", _invalidation_paths())
    ]


def test_flat_signal_exits_invalidation_before_deadline() -> None:
    """OPEN cell, FLAT signal, next rail before the deadline."""
    bus, seen = _engine()
    _birth(bus)
    bus.publish(_signal(2, SignalDirection.FLAT))
    bus.publish(_rail(3, _BEFORE))
    _exit_fill(bus, 4)
    cell_id = _cell_id()
    assert [(item.reason, item.order_id, item.side, item.quantity) for item in _reqs(seen)] == [
        ("INVALIDATION", f"{cell_id}|EXIT|1", Side.SELL, _SHARES)
    ]
    assert [(item.exit_reason, item.triggered_paths) for item in _closed(seen)] == [
        ("INVALIDATION", _invalidation_paths())
    ]


def test_latch_and_deadline_on_one_rail_prefer_horizon() -> None:
    """Latch and deadline on one rail: HORIZON wins and both paths are recorded."""
    bus, seen = _engine()
    _birth(bus)
    bus.publish(_signal(2, SignalDirection.SHORT))
    bus.publish(_rail(3, _DEADLINE))
    _exit_fill(bus, 4)
    cell_id = _cell_id()
    assert [(item.reason, item.order_id) for item in _reqs(seen)] == [
        ("HORIZON", f"{cell_id}|EXIT|1")
    ]
    assert [(item.exit_reason, item.triggered_paths) for item in _closed(seen)] == [
        ("HORIZON", _both_paths())
    ]


def test_latch_while_exiting_does_not_replace_the_live_requirement() -> None:
    """A latch while EXITING emits no second requirement; the live reason stays."""
    bus, seen = _engine()
    _birth(bus)
    bus.publish(_rail(2, _DEADLINE))
    bus.publish(_signal(3, SignalDirection.SHORT))
    bus.publish(_rail(4, _AFTER))
    _exit_fill(bus, 5)
    cell_id = _cell_id()
    assert [(item.reason, item.order_id) for item in _reqs(seen)] == [
        ("HORIZON", f"{cell_id}|EXIT|1")
    ]
    assert [(item.exit_reason, item.triggered_paths) for item in _closed(seen)] == [
        ("HORIZON", _horizon_paths())
    ]


def test_same_side_signal_leaves_horizon() -> None:
    """Control: a same-side signal latches nothing. HORIZON is unchanged."""
    bus, seen = _engine()
    _birth(bus)
    bus.publish(_signal(2, SignalDirection.LONG))
    bus.publish(_rail(3, _DEADLINE))
    _exit_fill(bus, 4)
    cell_id = _cell_id()
    assert [(item.reason, item.order_id) for item in _reqs(seen)] == [
        ("HORIZON", f"{cell_id}|EXIT|1")
    ]
    assert [(item.exit_reason, item.triggered_paths) for item in _closed(seen)] == [
        ("HORIZON", _horizon_paths())
    ]
