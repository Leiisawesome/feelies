"""Contract-derived tests for the reference engine. Independent of the battery."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from fractions import Fraction

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    DeRiskRequirement,
    GateDecision,
    MarkRailUpdate,
    PositionClosed,
    PositionSnapshot,
    RailOrientation,
    Side,
    Signal,
    SignalDirection,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.identifiers import SequenceGenerator
from tests.position_engine.reference.engine import PositionEngine

_A = 30_000_000_000
_Q = 5_000_000_000


def _policy(
    *,
    form: str = "fixed",
    target: int | None = 4,
    centre: int = 11,
    band: int = 0,
    giveback: float | None = None,
    fee: int = 0,
    t_ns: int = 16_000_000_000_000,
    blind: int = _A,
    quiet: int = _Q,
) -> ExitPolicy:
    return ExitPolicy(
        archetype="liquidity_provision" if form == "fixed" else "informed_flow_following",
        declared_shape=None,
        curve_ref="ARBITRARY_NOT_CALIBRATED",
        fee_round_trip_ticks=fee,
        horizon=HorizonPolicy(T_ns=t_ns, cutoff_before_close_ns=1),
        adverse=AdversePolicy(
            centre_ticks=centre,
            band_ticks=band,
            lo_ticks=2,
            hi_ticks=20,
            blind_limit_ns=blind,
        ),
        favorable=FavorablePolicy(
            form=form,
            quiet_limit_ns=quiet,
            target_ticks=target,
            giveback_spread_multiple=giveback,
        ),
    )


def _orient(
    *,
    paying: int | None = 10_001,
    valuation: int | None = 10_000,
    worst: int | None = 10_000,
    forced: int | None = 10_000,
    dwelled: int | None = 10_000,
    paying_absent: int = 0,
    valuation_absent: int = 0,
    absent: bool = False,
    clean: bool = True,
) -> RailOrientation:
    return RailOrientation(
        paying_mark_cents=paying,
        valuation_mark_cents=valuation,
        worst_side_mark_cents=worst,
        forced_exit_mark_cents=forced,
        dwelled_exit_mark_cents=dwelled,
        paying_size=100,
        valuation_size=100,
        paying_age_ns=0,
        valuation_age_ns=0,
        paying_absent_for_ns=paying_absent,
        valuation_absent_for_ns=valuation_absent,
        paying_side_absent=absent,
        valuation_side_absent=absent,
        dwell_window_clean=clean,
    )


def _rail(
    sequence: int,
    timestamp_ns: int,
    orient: RailOrientation | None = None,
    *,
    crossed: bool = False,
    quiet: int = 0,
    gap: bool = False,
    warmed: bool = True,
) -> MarkRailUpdate:
    side = orient if orient is not None else _orient()
    return MarkRailUpdate(
        timestamp_ns=timestamp_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="SYN",
        quote_sequence=sequence,
        event_timestamp_ns=timestamp_ns,
        long=side,
        short=side,
        symbol_quiet_ns=quiet,
        locked=False,
        crossed=crossed,
        feed_gap_before=gap,
        warmed_up=warmed,
    )


def _slice(
    sequence: int,
    timestamp_ns: int,
    *,
    order_id: str,
    price: str,
    fill_quantity: int,
    quantity: int,
    strategy_id: str = "sig",
) -> SlicePositionUpdate:
    return SlicePositionUpdate(
        timestamp_ns=timestamp_ns,
        correlation_id=f"fill-{sequence}",
        sequence=sequence,
        symbol="SYN",
        strategy_id=strategy_id,
        order_id=order_id,
        fill_price=Decimal(price),
        fill_quantity=fill_quantity,
        fill_ack_sequence=sequence,
        fill_timestamp_ns=timestamp_ns,
        quantity=quantity,
        avg_entry_price=Decimal(price),
    )


class _Log:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[object] = []
        bus.subscribe_all(self.events.append)


def _engine(
    policy: ExitPolicy | None = None,
    *,
    gate_order: tuple[str, ...] = ("ADVERSE", "FAVORABLE"),
) -> tuple[EventBus, PositionEngine, _Log]:
    bus = EventBus()
    engine = PositionEngine(
        bus,
        SequenceGenerator(stream="position", thread_safe=False),
        policies={"sig": policy if policy is not None else _policy()},
        gate_order=gate_order,
    )
    engine.attach()
    return bus, engine, _Log(bus)


def _of(log: _Log, kind: type[object]) -> list[object]:
    return [event for event in log.events if type(event) is kind]


def test_band_draw_and_cell_id() -> None:
    """contracts.md §2:191 cell_id; §9:433-437 L = (centre - B//2) + (h mod (B+1))."""
    bus, _engine_obj, log = _engine(_policy(band=4, centre=11))
    bus.publish(_rail(7, 1_000))
    bus.publish(_slice(8, 1_000, order_id="entry", price="100.01", fill_quantity=10, quantity=10))
    bus.publish(_rail(9, 2_000))
    snap = _of(log, PositionSnapshot)[0]
    assert isinstance(snap, PositionSnapshot)
    assert snap.cell_id == "SYN|sig|7|LONG"
    digest = hashlib.sha256(b"SYN|sig|7|LONG").digest()[:8]
    level = (11 - 4 // 2) + (int.from_bytes(digest, "big") % 5)
    adverse = [row for row in _of(log, GateDecision) if isinstance(row, GateDecision)]
    assert adverse[0].drawn_level_ticks == level


@pytest.mark.parametrize(
    ("field", "paying_absent", "valuation_absent", "quiet"),
    (
        ("paying", _A + 1, 0, 0),
        ("valuation", 0, _A + 1, 0),
        ("quiet", 0, 0, _A + 1),
    ),
)
def test_blind_is_strictly_greater_than_a(
    field: str, paying_absent: int, valuation_absent: int, quiet: int
) -> None:
    """contracts.md §9:427-429 BLIND iff paying, valuation, or quiet absence is > A."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    under = _orient(paying_absent=paying_absent - 1, valuation_absent=max(valuation_absent - 1, 0))
    if field == "quiet":
        under = _orient()
        bus.publish(_rail(3, 2_000, under, quiet=_A))
    else:
        bus.publish(_rail(3, 2_000, under, quiet=0))
    held = [row for row in _of(log, GateDecision) if isinstance(row, GateDecision) and row.gate == "ADVERSE"]
    assert held[-1].outcome == "hold"
    over = _orient(paying_absent=paying_absent, valuation_absent=valuation_absent, absent=field != "quiet")
    bus.publish(_rail(4, 3_000, over, quiet=quiet))
    fired = [row for row in _of(log, GateDecision) if isinstance(row, GateDecision) and row.gate == "ADVERSE"]
    assert fired[-1].outcome == "fire"
    assert fired[-1].reason == "BLIND"


def test_favorable_tokens_in_order() -> None:
    """contracts.md §9:430-432 six tokens, reason is the first, suppressions keeps all."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    blocked = _orient(valuation=None, dwelled=None, absent=True, clean=False)
    bus.publish(_rail(3, 2_000, blocked, crossed=True, quiet=_Q + 1, gap=True, warmed=False))
    favorable = [row for row in _of(log, GateDecision) if isinstance(row, GateDecision) and row.gate == "FAVORABLE"]
    assert favorable[-1].outcome == "suppressed"
    assert favorable[-1].suppressions == (
        "VALUATION_SIDE_ABSENT",
        "CROSSED",
        "FEED_GAP",
        "DWELL_NOT_CLEAN",
        "NOT_WARMED_UP",
        "SYMBOL_QUIET",
    )
    assert favorable[-1].reason == "VALUATION_SIDE_ABSENT"


def test_extremes_seed_on_the_first_clean_reading() -> None:
    """contracts.md §2:225-228 seed on the first CLEAN reading, never at zero, else None."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    dirty = _orient(absent=True)
    bus.publish(_rail(3, 2_000, dirty, crossed=True))
    first = _of(log, PositionSnapshot)[-1]
    assert isinstance(first, PositionSnapshot)
    assert first.best is None and first.worst is None and first.best_clean is None
    bus.publish(_rail(4, 3_000, _orient(valuation=10_050, worst=10_050, forced=10_050, dwelled=10_050)))
    seeded = _of(log, PositionSnapshot)[-1]
    assert isinstance(seeded, PositionSnapshot)
    assert seeded.move_now_cents is not None and seeded.move_now_cents != 0
    assert seeded.best is not None and seeded.best.cents == seeded.move_now_cents
    assert seeded.worst is not None and seeded.worst.cents == seeded.move_now_cents
    assert seeded.best_clean is not None and seeded.best_clean.cents == seeded.move_now_cents


def test_giveback_r_floors_at_one() -> None:
    """contracts.md §3:325 and §9:438-440 R = max(1, floor(k * spread)); k = Fraction(repr)."""
    bus, _engine_obj, log = _engine(_policy(form="trailing", target=None, giveback=0.1))
    bus.publish(_rail(1, 1_000, _orient(paying=10_003, valuation=10_000)))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.03", fill_quantity=1, quantity=1))
    bus.publish(_rail(3, 2_000, _orient(paying=10_003, valuation=10_000)))
    row = [item for item in _of(log, GateDecision) if isinstance(item, GateDecision) and item.gate == "FAVORABLE"][-1]
    assert row.reference_ticks == max(1, int(Fraction(repr(0.1)) * 3))
    assert row.reference_ticks == 1


def test_precedence_picks_adverse_and_the_worst_price() -> None:
    """contracts.md §2:259-273 ADVERSE > HORIZON > INVALIDATION > FAVORABLE; price is the worst."""
    bus, engine, log = _engine(_policy(form="trailing", target=None, giveback=2, t_ns=1_000))
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=10, quantity=10))
    bus.publish(_rail(3, 1_500, _orient(valuation=11_000, worst=11_000, forced=11_000, dwelled=11_000)))
    bus.publish(
        Signal(
            timestamp_ns=1_600,
            correlation_id="flat",
            sequence=1,
            symbol="SYN",
            strategy_id="sig",
            direction=SignalDirection.FLAT,
            strength=0.0,
            edge_estimate_bps=0.0,
        )
    )
    bus.publish(_rail(4, 3_000, _orient(valuation=9_000, worst=9_000, forced=9_000, dwelled=9_000)))
    requirement = _of(log, DeRiskRequirement)[0]
    assert isinstance(requirement, DeRiskRequirement)
    bus.publish(
        _slice(5, 3_000, order_id=requirement.order_id, price="90.00", fill_quantity=-10, quantity=0)
    )
    closed = _of(log, PositionClosed)
    assert len(closed) == 1
    assert isinstance(closed[0], PositionClosed)
    names = [path.path for path in closed[0].triggered_paths]
    assert names[0] == "ADVERSE"
    assert "HORIZON" in names and "INVALIDATION" in names and "FAVORABLE" in names
    assert closed[0].exit_reason == "ADVERSE"
    prices = [path.proposed_price_cents for path in closed[0].triggered_paths]
    assert closed[0].proposed_price_cents == min(prices)
    requirements = _of(log, DeRiskRequirement)
    assert len(requirements) == 1
    del engine


def test_one_requirement_and_escalation_noop() -> None:
    """contracts.md §2:157-163 one requirement; a higher EXITING path is ESCALATION_NOOP."""
    bus, _engine_obj, log = _engine(_policy(target=4))
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    bus.publish(_rail(3, 2_000, _orient(valuation=10_100, worst=10_100, forced=10_100, dwelled=10_100)))
    assert len(_of(log, DeRiskRequirement)) == 1
    bus.publish(_rail(4, 3_000, _orient(valuation=9_000, worst=9_000, forced=9_000, dwelled=9_000)))
    assert len(_of(log, DeRiskRequirement)) == 1
    adverse = [row for row in _of(log, GateDecision) if isinstance(row, GateDecision) and row.gate == "ADVERSE"]
    assert adverse[-1].outcome == "ESCALATION_NOOP"


def test_partial_exit_reduces_the_next_snapshot() -> None:
    """contracts.md §2:164-167 an EXITING fill reduces open quantity on the next snapshot."""
    bus, _engine_obj, log = _engine(_policy(target=4))
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=10, quantity=10))
    bus.publish(_rail(3, 2_000, _orient(valuation=10_100, worst=10_100, forced=10_100, dwelled=10_100)))
    requirement = _of(log, DeRiskRequirement)[0]
    assert isinstance(requirement, DeRiskRequirement)
    bus.publish(
        _slice(
            5,
            2_000,
            order_id=requirement.order_id,
            price="101.00",
            fill_quantity=-4,
            quantity=6,
        )
    )
    bus.publish(_rail(6, 3_000, _orient(valuation=10_100, worst=10_100, forced=10_100, dwelled=10_100)))
    snap = _of(log, PositionSnapshot)[-1]
    assert isinstance(snap, PositionSnapshot)
    assert snap.state == "EXITING"
    assert snap.size == 6
    assert _of(log, PositionClosed) == []


def test_same_order_extends_and_scale_in_is_refused() -> None:
    """contracts.md §2:197-201 same entry order accumulates; a different order is refused."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=4, quantity=4))
    bus.publish(_slice(3, 1_100, order_id="entry", price="100.01", fill_quantity=6, quantity=10))
    bus.publish(_slice(4, 1_200, order_id="other", price="100.01", fill_quantity=5, quantity=15))
    bus.publish(_rail(5, 2_000))
    snap = _of(log, PositionSnapshot)[-1]
    assert isinstance(snap, PositionSnapshot)
    assert snap.size == 10
    assert snap.entry_cost_cents == 10001 * 10


def test_sign_flip_closes_the_overlap_and_births_the_excess() -> None:
    """contracts.md §2:168-170 EXTERNAL:SIGN_FLIP for the overlap; excess births the new cell."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=4, quantity=4))
    bus.publish(_slice(3, 1_500, order_id="flip", price="100.00", fill_quantity=-7, quantity=-3))
    closed = _of(log, PositionClosed)
    assert len(closed) == 1
    assert isinstance(closed[0], PositionClosed)
    assert closed[0].exit_reason == "EXTERNAL:SIGN_FLIP"
    assert closed[0].exit_fills[0].quantity == 4
    bus.publish(_rail(4, 2_000))
    born = [row for row in _of(log, PositionSnapshot) if isinstance(row, PositionSnapshot)]
    assert born[-1].side == "SHORT"
    assert born[-1].size == 3
    assert born[-1].cell_id.endswith("|SHORT")


def test_subcent_price_raises() -> None:
    """contracts.md §9:480-482 a non-whole-cent price raises."""
    bus, _engine_obj, _log = _engine()
    bus.publish(_rail(1, 1_000))
    with pytest.raises(ValueError):
        bus.publish(_slice(2, 1_000, order_id="entry", price="100.001", fill_quantity=1, quantity=1))


def test_none_marks_produce_none_moves() -> None:
    """contracts.md §2:216-217 a move is None exactly when its mark is None (D-99, D-100)."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000, _orient()))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    bus.publish(_rail(3, 2_000, _orient(valuation=None, worst=None, forced=10_000, dwelled=None)))
    snap = _of(log, PositionSnapshot)[-1]
    assert isinstance(snap, PositionSnapshot)
    assert snap.move_now_cents is None
    assert snap.move_worst_cents is None
    assert snap.move_forced_cents is not None
    assert snap.best is None


def test_requirement_order_id_and_reducing_side() -> None:
    """contracts.md §2:283-284 order_id is cell_id|EXIT; LONG sells and SHORT buys (D-98)."""
    bus, _engine_obj, log = _engine(_policy(target=4))
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=2, quantity=2))
    bus.publish(_rail(3, 2_000, _orient(valuation=10_100, worst=10_100, forced=10_100, dwelled=10_100)))
    requirement = _of(log, DeRiskRequirement)[0]
    assert isinstance(requirement, DeRiskRequirement)
    assert requirement.order_id == "SYN|sig|1|LONG|EXIT"
    assert requirement.side is Side.SELL
    assert requirement.source_layer == "POSITION"
    assert requirement.quantity == 2


def test_end_of_tape_and_missing_exit_side() -> None:
    """contracts.md §2:172-180 and §2:178-180 END_OF_TAPE; no usable side yields None and stale."""
    bus, engine, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    engine.finalize()
    closed = _of(log, PositionClosed)
    assert len(closed) == 1
    assert isinstance(closed[0], PositionClosed)
    assert closed[0].exit_reason == "END_OF_TAPE"
    assert closed[0].proposed_price_cents == 10_000
    assert _of(log, DeRiskRequirement) == []
    bus2, engine2, log2 = _engine()
    bus2.publish(_rail(1, 1_000, _orient(paying=None, valuation=None, worst=None, forced=None, dwelled=None, absent=True)))
    bus2.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    engine2.finalize()
    stale = _of(log2, PositionClosed)[0]
    assert isinstance(stale, PositionClosed)
    assert stale.proposed_price_cents is None
    assert stale.closed_on_stale_data is True


def test_gate_order_does_not_change_published_events() -> None:
    """contracts.md §8:405-407 reversed gate order publishes the same events."""

    def run(order: tuple[str, ...]) -> list[tuple[object, ...]]:
        bus, _engine_obj, log = _engine(gate_order=order)
        bus.publish(_rail(1, 1_000))
        bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
        bus.publish(_rail(3, 2_000))
        found: list[tuple[object, ...]] = []
        for event in log.events:
            if type(event) is PositionSnapshot and isinstance(event, PositionSnapshot):
                found.append(("snap", event.cell_id, event.move_now_cents, event.sequence))
            elif type(event) is GateDecision and isinstance(event, GateDecision):
                found.append((event.gate, event.outcome, event.reason, event.sequence))
        return found

    assert run(("ADVERSE", "FAVORABLE")) == run(("FAVORABLE", "ADVERSE"))


def test_one_snapshot_per_rail_event() -> None:
    """contracts.md §2:248-250 and D-103 at most one snapshot per (cell, rail event)."""
    bus, _engine_obj, log = _engine()
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    bus.publish(_rail(3, 2_000))
    bus.publish(_rail(4, 3_000))
    keys = [
        (row.cell_id, row.rail_sequence)
        for row in _of(log, PositionSnapshot)
        if isinstance(row, PositionSnapshot)
    ]
    assert keys == [("SYN|sig|1|LONG", 3), ("SYN|sig|1|LONG", 4)]
