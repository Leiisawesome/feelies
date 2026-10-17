"""P-30 stage-B skeleton. contracts.md §0, §2, §8; D-191; D-194 is not evaluated here."""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock, SimulatedClock
from feelies.core.events import (
    DeRiskRequirement,
    Event,
    GateDecision,
    MarkRailUpdate,
    PositionClosed,
    PositionSnapshot,
    RailOrientation,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.identifiers import SequenceGenerator
from feelies.position.engine import PositionEngine, PositionRecordSink

_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION = _ROOT / "src" / "feelies" / "position" / "engine.py"
_REFERENCE = _ROOT / "tests" / "position_engine" / "reference" / "engine.py"
_CONTRACT_SUBS = ("MarkRailUpdate", "SlicePositionUpdate", "Signal")
_CONTRACT_PUBS = ("PositionSnapshot", "GateDecision", "PositionClosed", "DeRiskRequirement")
_CONTRACT_GATES = ("ADVERSE", "FAVORABLE")


def _orient() -> RailOrientation:
    return RailOrientation(
        paying_mark_cents=101,
        valuation_mark_cents=100,
        worst_side_mark_cents=100,
        forced_exit_mark_cents=99,
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


def _policy() -> ExitPolicy:
    return ExitPolicy(
        archetype="liquidity_provision",
        declared_shape=None,
        curve_ref="ARBITRARY_NOT_CALIBRATED",
        fee_round_trip_ticks=1,
        horizon=HorizonPolicy(T_ns=120_000_000_000, cutoff_before_close_ns=1),
        adverse=AdversePolicy(
            centre_ticks=10,
            band_ticks=0,
            lo_ticks=2,
            hi_ticks=20,
            blind_limit_ns=1,
        ),
        favorable=FavorablePolicy(form="fixed", quiet_limit_ns=1, target_ticks=4),
    )


def _engine(
    policies: dict[str, ExitPolicy],
    clock: Clock,
    *,
    gate_order: tuple[str, ...] = _CONTRACT_GATES,
) -> tuple[EventBus, PositionEngine, PositionRecordSink]:
    bus = EventBus()
    engine = PositionEngine(
        bus,
        SequenceGenerator(stream="position", thread_safe=False),
        policies,
        clock=clock,
        gate_order=gate_order,
    )
    engine.attach()
    sink = PositionRecordSink(bus)
    sink.attach()
    return bus, engine, sink


def _rail(sequence: int, symbol: str = "SYN") -> MarkRailUpdate:
    return MarkRailUpdate(
        timestamp_ns=sequence,
        correlation_id=f"rail-{sequence}",
        sequence=sequence,
        source_layer="portfolio",
        symbol=symbol,
        quote_sequence=sequence,
        event_timestamp_ns=sequence * 1_000,
        long=_orient(),
        short=_orient(),
        symbol_quiet_ns=0,
        locked=False,
        crossed=False,
        feed_gap_before=False,
        warmed_up=True,
    )


def _fill(
    sequence: int,
    *,
    strategy_id: str,
    symbol: str = "SYN",
    order_id: str,
    fill_quantity: int,
    quantity: int,
    stamp: int,
    price: str = "1.01",
) -> SlicePositionUpdate:
    return SlicePositionUpdate(
        timestamp_ns=sequence,
        correlation_id=f"fill-{sequence}",
        sequence=sequence,
        source_layer="kernel",
        symbol=symbol,
        strategy_id=strategy_id,
        order_id=order_id,
        fill_price=Decimal(price),
        fill_quantity=fill_quantity,
        fill_ack_sequence=sequence,
        fill_timestamp_ns=stamp,
        quantity=quantity,
        avg_entry_price=Decimal(price),
    )


def _ids(events: list[Event]) -> list[str]:
    found: list[str] = []
    for event in events:
        if isinstance(event, PositionSnapshot | PositionClosed):
            found.append(event.cell_id)
    return found


def _subscribe_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "PositionEngine":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "attach":
                continue
            for child in ast.walk(item):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if not isinstance(func, ast.Attribute) or func.attr != "subscribe":
                    continue
                if not child.args:
                    continue
                arg = child.args[0]
                if isinstance(arg, ast.Name):
                    names.append(arg.id)
    return tuple(names)


def _post_init_clock_sites(path: Path) -> list[str]:
    """Assignment, augmented assignment, or setattr of _clock outside __init__."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    sites: list[str] = []

    def enclosing(node: ast.AST) -> str:
        current: ast.AST | None = node
        while current in parents:
            current = parents[current]
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                return current.name
        return "<module>"

    for node in ast.walk(tree):
        if enclosing(node) == "__init__":
            continue
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "_clock":
                    sites.append(f"{path.name}:{node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "_clock"
        ):
            sites.append(f"{path.name}:{node.lineno}")
    return sites


def test_t1_subscriptions_match_contract_section_0() -> None:
    """contracts.md:25. Declared publications too, when the engine declares them."""
    assert _subscribe_names(_PRODUCTION) == _CONTRACT_SUBS
    declared = getattr(PositionEngine, "PUBLICATIONS", None)
    if declared is not None:
        names = tuple(item if isinstance(item, str) else item.__name__ for item in declared)
        assert names == _CONTRACT_PUBS


def test_t2_cell_identity_birth_ordinal_and_crossing_fill() -> None:
    """D-191. One birth per stamp is four components; a same-stamp rebirth ends |1."""
    clock = SimulatedClock(1_000)
    policies = {"alpha": _policy()}
    bus, _engine_obj, _sink = _engine(policies, clock)
    seen: list[Event] = []
    bus.subscribe_all(seen.append)
    bus.publish(
        _fill(1, strategy_id="alpha", order_id="e1", fill_quantity=1, quantity=1, stamp=10)
    )
    bus.publish(_rail(2))
    bus.publish(
        _fill(3, strategy_id="alpha", order_id="x1", fill_quantity=-1, quantity=0, stamp=11)
    )
    bus.publish(
        _fill(4, strategy_id="alpha", order_id="e2", fill_quantity=1, quantity=1, stamp=12)
    )
    bus.publish(_rail(5))
    born = [cell_id for cell_id in _ids(seen) if cell_id.count("|") == 3]
    assert born, "a fill at its own stamp did not publish a 4-component id"
    assert all(not cell_id.endswith("|1") for cell_id in born)

    seen.clear()
    bus2, _engine2, _sink2 = _engine(policies, clock)
    bus2.subscribe_all(seen.append)
    stamp = 77
    bus2.publish(
        _fill(1, strategy_id="alpha", order_id="b1", fill_quantity=1, quantity=1, stamp=stamp)
    )
    bus2.publish(
        _fill(2, strategy_id="alpha", order_id="s1", fill_quantity=-1, quantity=0, stamp=stamp)
    )
    bus2.publish(
        _fill(3, strategy_id="alpha", order_id="b2", fill_quantity=1, quantity=1, stamp=stamp)
    )
    bus2.publish(_rail(4))
    rebirth = [cell_id for cell_id in _ids(seen) if cell_id.endswith("|1")]
    assert rebirth, "same-stamp rebirth did not append |1"
    assert rebirth[-1].count("|") == 4

    seen.clear()
    bus3, _engine3, _sink3 = _engine(policies, clock)
    bus3.subscribe_all(seen.append)
    bus3.publish(
        _fill(1, strategy_id="alpha", order_id="L", fill_quantity=10, quantity=10, stamp=100)
    )
    bus3.publish(
        _fill(2, strategy_id="alpha", order_id="X", fill_quantity=-25, quantity=-15, stamp=200)
    )
    closed = [event for event in seen if isinstance(event, PositionClosed)]
    assert len(closed) == 1
    assert closed[0].exit_reason == "EXTERNAL:SIGN_FLIP"
    assert closed[0].exit_fills[0].quantity == 10
    bus3.publish(_rail(3))
    snaps = [event for event in seen if isinstance(event, PositionSnapshot)]
    assert snaps, "excess of a crossing fill did not birth a cell"
    assert snaps[-1].side == "SHORT"
    assert snaps[-1].size == 15
    assert snaps[-1].cell_id.count("|") == 3


def test_t3_one_close_stamped_from_the_injected_clock() -> None:
    """PositionClosed once, with the contract fields, at the injected clock."""
    clock = SimulatedClock(42_000_000_000)
    bus, engine, _sink = _engine({"alpha": _policy()}, clock)
    seen: list[Event] = []
    bus.subscribe_all(seen.append)
    bus.publish(_fill(1, strategy_id="alpha", order_id="e", fill_quantity=4, quantity=4, stamp=9))
    bus.publish(
        _fill(2, strategy_id="alpha", order_id="x", fill_quantity=-4, quantity=0, stamp=10)
    )
    closed = [event for event in seen if isinstance(event, PositionClosed)]
    assert len(closed) == 1
    record = closed[0]
    assert record.timestamp_ns == clock.now_ns()
    assert engine._clock is clock
    assert record.symbol == "SYN"
    assert record.strategy_id == "alpha"
    assert record.side == "LONG"
    assert record.cell_id.startswith("SYN|alpha|")
    assert len(record.entry_fills) == 1
    assert record.entry_fills[0].quantity == 4
    assert record.exit_reason
    assert isinstance(record.entry_spread_ticks, int)
    assert isinstance(record.horizon_deadline_ns, int)


def test_t4_clock_is_constructor_injected_for_both_engines() -> None:
    """No _clock assignment after construction. The stamped clock is the argument."""
    assert _post_init_clock_sites(_PRODUCTION) == []
    assert _post_init_clock_sites(_REFERENCE) == []
    from tests.position_engine.reference.engine import PositionEngine as ReferenceEngine

    for cls in (PositionEngine, ReferenceEngine):
        assert "clock" in inspect.signature(cls.__init__).parameters
    clock = SimulatedClock(7)
    _bus, engine, _sink = _engine({"alpha": _policy()}, clock)
    assert engine._clock is clock
    reference = ReferenceEngine(
        EventBus(),
        SequenceGenerator(stream="position", thread_safe=False),
        {"alpha": _policy()},
        clock=clock,
    )
    assert reference._clock is clock


def test_t5_step_order_is_cell_id_then_contract_gates() -> None:
    """Two open cells, one symbol: cell_id order, snapshot, both gates, then resolve."""
    clock = SimulatedClock(5)
    policies = {"aaa": _policy(), "bbb": _policy()}
    bus, _engine_obj, _sink = _engine(policies, clock)
    seen: list[Event] = []
    bus.subscribe_all(seen.append)
    bus.publish(_fill(1, strategy_id="bbb", order_id="b", fill_quantity=2, quantity=2, stamp=50))
    bus.publish(_fill(2, strategy_id="aaa", order_id="a", fill_quantity=3, quantity=3, stamp=40))
    seen.clear()
    bus.publish(_rail(3))
    position = [
        event
        for event in seen
        if isinstance(event, PositionSnapshot | GateDecision | PositionClosed | DeRiskRequirement)
    ]
    assert not any(isinstance(event, DeRiskRequirement) for event in position)
    assert [type(event).__name__ for event in position] == [
        "PositionSnapshot",
        "GateDecision",
        "GateDecision",
        "PositionSnapshot",
        "GateDecision",
        "GateDecision",
    ]
    first, g1, g2, second, g3, g4 = position
    assert isinstance(first, PositionSnapshot)
    assert isinstance(second, PositionSnapshot)
    assert first.cell_id < second.cell_id
    assert first.cell_id.startswith("SYN|aaa|")
    assert second.cell_id.startswith("SYN|bbb|")
    for snap, adverse, favorable in ((first, g1, g2), (second, g3, g4)):
        assert isinstance(adverse, GateDecision)
        assert isinstance(favorable, GateDecision)
        assert adverse.cell_id == snap.cell_id
        assert favorable.cell_id == snap.cell_id
        assert adverse.gate == "ADVERSE"
        assert favorable.gate == "FAVORABLE"
        assert adverse.rail_sequence == snap.rail_sequence == 3
        assert favorable.rail_sequence == 3
