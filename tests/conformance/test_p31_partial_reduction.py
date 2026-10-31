"""P-31 partial reduction and close correlation. D-196, D-197.

Extremes after a reduction follow the running-extreme rule already in the
contract: the episode's extremes are not reset. A zero move still updates
``worst`` when it is below the seeded worst.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Event,
    MarkRailUpdate,
    PositionClosed,
    PositionExtreme,
    PositionSnapshot,
    RailOrientation,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.identifiers import SequenceGenerator
from tests.position_engine.scenarios import engine_class

_MARK = 10_100


def _policy() -> ExitPolicy:
    """Wide gates so a reduction rail publishes a snapshot and leaves the cell open."""
    wide = 10**9
    return ExitPolicy(
        archetype="liquidity_provision",
        declared_shape=None,
        curve_ref="ARBITRARY_NOT_CALIBRATED",
        fee_round_trip_ticks=1,
        horizon=HorizonPolicy(T_ns=wide, cutoff_before_close_ns=1),
        adverse=AdversePolicy(
            centre_ticks=wide,
            band_ticks=0,
            lo_ticks=2,
            hi_ticks=wide,
            blind_limit_ns=1,
        ),
        favorable=FavorablePolicy(form="fixed", quiet_limit_ns=1, target_ticks=wide),
    )


def _orient(*, absent: bool = False) -> RailOrientation:
    mark = None if absent else _MARK
    return RailOrientation(
        paying_mark_cents=None if absent else _MARK + 1,
        valuation_mark_cents=mark,
        worst_side_mark_cents=mark,
        forced_exit_mark_cents=mark,
        dwelled_exit_mark_cents=mark,
        paying_size=10,
        valuation_size=10,
        paying_age_ns=0,
        valuation_age_ns=0,
        paying_absent_for_ns=1 if absent else 0,
        valuation_absent_for_ns=1 if absent else 0,
        paying_side_absent=absent,
        valuation_side_absent=absent,
        dwell_window_clean=not absent,
    )


def _rail(sequence: int, correlation_id: str, *, absent: bool = False) -> MarkRailUpdate:
    orient = _orient(absent=absent)
    return MarkRailUpdate(
        timestamp_ns=sequence,
        correlation_id=correlation_id,
        sequence=sequence,
        source_layer="portfolio",
        symbol="SYN",
        quote_sequence=sequence,
        event_timestamp_ns=sequence * 1_000,
        long=orient,
        short=orient,
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
    price: str,
    correlation_id: str,
    stamp: int,
) -> SlicePositionUpdate:
    return SlicePositionUpdate(
        timestamp_ns=sequence,
        correlation_id=correlation_id,
        sequence=sequence,
        source_layer="kernel",
        symbol="SYN",
        strategy_id="alpha",
        order_id=order_id,
        fill_price=Decimal(price),
        fill_quantity=fill_quantity,
        fill_ack_sequence=sequence,
        fill_timestamp_ns=stamp,
        quantity=quantity,
        avg_entry_price=Decimal(price),
    )


def _drive(events: list[Event]) -> tuple[list[Event], object]:
    bus = EventBus()
    engine = engine_class()(
        bus,
        SequenceGenerator(stream="position", thread_safe=False),
        {"alpha": _policy()},
        clock=SimulatedClock(1_000),
    )
    engine.attach()
    seen: list[Event] = []
    bus.subscribe_all(seen.append)
    for event in events:
        bus.publish(event)
    return seen, engine


def _reduced(fills: list[SlicePositionUpdate]) -> PositionSnapshot:
    events: list[Event] = []
    for index, fill in enumerate(fills, start=1):
        events.append(fill)
        events.append(_rail(100 + index, f"rail-{index}"))
    seen, _engine = _drive(events)
    snaps = [event for event in seen if isinstance(event, PositionSnapshot)]
    assert snaps, "reduction rail published no snapshot"
    return snaps[-1]


def _cents(extreme: PositionExtreme | None) -> tuple[int | None, int | None]:
    if extreme is None:
        return None, None
    return extreme.cents, extreme.sequence


def _long_fills() -> list[SlicePositionUpdate]:
    return [
        _fill(
            1,
            order_id="entry",
            fill_quantity=10,
            quantity=10,
            price="100.00",
            correlation_id="buy-100",
            stamp=1_000,
        ),
        _fill(
            2,
            order_id="entry",
            fill_quantity=10,
            quantity=20,
            price="102.00",
            correlation_id="buy-102",
            stamp=2_000,
        ),
        _fill(
            3,
            order_id="exit",
            fill_quantity=-10,
            quantity=10,
            price="101.00",
            correlation_id="sell-10",
            stamp=3_000,
        ),
    ]


def _short_fills() -> list[SlicePositionUpdate]:
    return [
        _fill(
            1,
            order_id="entry",
            fill_quantity=-10,
            quantity=-10,
            price="102.00",
            correlation_id="sell-102",
            stamp=1_000,
        ),
        _fill(
            2,
            order_id="entry",
            fill_quantity=-10,
            quantity=-20,
            price="100.00",
            correlation_id="sell-100",
            stamp=2_000,
        ),
        _fill(
            3,
            order_id="exit",
            fill_quantity=10,
            quantity=-10,
            price="101.00",
            correlation_id="buy-10",
            stamp=3_000,
        ),
    ]


def _split_fills() -> list[SlicePositionUpdate]:
    fills = _long_fills()
    return [
        fills[0],
        fills[1],
        _fill(
            3,
            order_id="exit",
            fill_quantity=-15,
            quantity=5,
            price="101.00",
            correlation_id="sell-15",
            stamp=3_000,
        ),
    ]


def test_t6a_long_fifo_remaining_cost() -> None:
    """Buy 10 @ 100, buy 10 @ 102, sell 10. Remaining lot is 10 @ 102."""
    snap = _reduced(_long_fills())
    assert snap.size == 10
    assert snap.entry_cost_cents == 102_000, snap.entry_cost_cents
    assert snap.move_now_cents == -1_000, snap.move_now_cents


def test_t6b_short_fifo_remaining_cost() -> None:
    """Sell 10 @ 102, sell 10 @ 100, buy 10. Remaining lot is 10 @ 100."""
    snap = _reduced(_short_fills())
    assert snap.side == "SHORT"
    assert snap.size == 10
    assert snap.entry_cost_cents == 100_000, snap.entry_cost_cents
    assert snap.move_now_cents == -1_000, snap.move_now_cents


def test_t6c_split_lot() -> None:
    """Sell 15 consumes the 100 lot and 5 of the 102 lot. Remaining 5 @ 102."""
    snap = _reduced(_split_fills())
    assert snap.size == 5
    assert snap.entry_cost_cents == 51_000, snap.entry_cost_cents
    assert snap.move_now_cents == -500, snap.move_now_cents


def test_t6d_extremes_continue_after_reduction() -> None:
    """The reduction rail absorbs the new move. Earlier extremes stay."""
    cases = (
        (_long_fills(), 1_000, -1_000),
        (_short_fills(), 1_000, -1_000),
        (_split_fills(), 1_000, -500),
    )
    for fills, best, worst in cases:
        snap = _reduced(fills)
        assert _cents(snap.best) == (best, 101), _cents(snap.best)
        assert _cents(snap.worst) == (worst, 103), _cents(snap.worst)
        assert _cents(snap.best_clean) == (best, 101), _cents(snap.best_clean)


def test_t7a_flattening_fill_correlation_id() -> None:
    """The flattening exit fill's id is the close id."""
    seen, _engine = _drive(
        [
            _fill(
                1,
                order_id="entry",
                fill_quantity=4,
                quantity=4,
                price="100.00",
                correlation_id="entry-fill",
                stamp=10,
            ),
            _fill(
                2,
                order_id="exit",
                fill_quantity=-4,
                quantity=0,
                price="101.00",
                correlation_id="exit-fill",
                stamp=11,
            ),
        ]
    )
    closed = [event for event in seen if isinstance(event, PositionClosed)]
    assert len(closed) == 1
    assert closed[0].correlation_id == "exit-fill", closed[0].correlation_id


def test_t7b_sign_flip_correlation_id_births_the_new_cell() -> None:
    """The flip fill closes the old cell and is the entry leg of the new one."""
    seen, _engine = _drive(
        [
            _fill(
                1,
                order_id="entry",
                fill_quantity=10,
                quantity=10,
                price="100.00",
                correlation_id="entry-fill",
                stamp=100,
            ),
            _fill(
                2,
                order_id="flip",
                fill_quantity=-25,
                quantity=-15,
                price="101.00",
                correlation_id="flip-fill",
                stamp=200,
            ),
            _rail(3, "rail-after-flip"),
            _fill(
                4,
                order_id="cover",
                fill_quantity=15,
                quantity=0,
                price="101.00",
                correlation_id="cover-fill",
                stamp=300,
            ),
        ]
    )
    closed = [event for event in seen if isinstance(event, PositionClosed)]
    assert len(closed) == 2, [event.correlation_id for event in closed]
    assert closed[0].correlation_id == "flip-fill", closed[0].correlation_id
    assert closed[0].exit_fills[0].quantity == 10
    born = closed[1]
    assert born.correlation_id == "cover-fill", born.correlation_id
    assert len(born.entry_fills) == 1
    assert born.entry_fills[0].sequence == 2
    assert born.entry_fills[0].quantity == 15
    assert born.entry_fills[0].price_cents == 10_100
    snaps = [event for event in seen if isinstance(event, PositionSnapshot)]
    assert snaps[-1].side == "SHORT"
    assert snaps[-1].size == 15


# D-84. Production finalize closes END_OF_TAPE on the last usable rail.
def test_t7c_end_of_tape_last_usable_rail() -> None:
    """END_OF_TAPE uses the last rail whose exit side is usable, not a later absent one."""
    seen, engine = _drive(
        [
            _fill(
                1,
                order_id="entry",
                fill_quantity=1,
                quantity=1,
                price="100.00",
                correlation_id="entry-fill",
                stamp=10,
            ),
            _rail(2, "rail-usable"),
            _rail(3, "rail-absent", absent=True),
        ]
    )
    engine.finalize()
    closed = [event for event in seen if isinstance(event, PositionClosed)]
    assert len(closed) == 1
    assert closed[0].exit_reason == "END_OF_TAPE"
    assert closed[0].correlation_id == "rail-usable", closed[0].correlation_id
