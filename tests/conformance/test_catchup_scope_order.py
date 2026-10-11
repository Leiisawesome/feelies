"""Catch-up emission order across scopes, and the contexts that order builds.

One market event can cross several boundaries. Those ticks are ordered by
boundary time. Inside one boundary time the standing rule still holds:
horizon ascending, SYMBOL before UNIVERSE, symbol ascending. A universe
context for boundary k is built only from snapshots whose boundary is k.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.core.events import CrossSectionalContext, NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler

_NS = 1_000_000_000
_OPEN = 1_000 * _NS


def _quote(symbol: str, ts: int, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("20.00"),
        ask=Decimal("20.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _expected_order(
    *,
    horizons: frozenset[int],
    symbols: frozenset[str],
    event_ts: int,
) -> list[tuple[int, int, str, str | None, int]]:
    """Boundary time, then horizon, scope, and symbol — the standing rule."""
    symbols_sorted = tuple(sorted(symbols))
    by_time: dict[int, list[tuple[int, int]]] = {}
    for horizon in sorted(horizons):
        window = horizon * _NS
        current = (event_ts - _OPEN) // window
        for boundary_index in range(current + 1):
            boundary_ts = _OPEN + boundary_index * window
            by_time.setdefault(boundary_ts, []).append((horizon, boundary_index))
    ordered: list[tuple[int, int, str, str | None, int]] = []
    for boundary_ts in sorted(by_time):
        for horizon, boundary_index in by_time[boundary_ts]:
            for symbol in symbols_sorted:
                ordered.append((boundary_ts, horizon, "SYMBOL", symbol, boundary_index))
            ordered.append((boundary_ts, horizon, "UNIVERSE", None, boundary_index))
    return ordered


def test_catchup_orders_all_scopes_by_boundary_time() -> None:
    """One event crossing several boundaries emits by boundary time ascending.

    Horizons that fall on the same time stay in the standing order: shorter
    horizon first, then SYMBOL symbols, then UNIVERSE.
    """
    horizons = frozenset({30, 120})
    symbols = frozenset({"ZZZ", "AAA"})
    sched = HorizonScheduler(
        horizons=horizons,
        session_id="P23G",
        symbols=symbols,
        session_open_ns=_OPEN,
        sequence_generator=SequenceGenerator(),
    )
    trigger = _OPEN + 120 * _NS
    ticks = sched.on_event(_quote("AAA", trigger, 1))
    actual = [
        (
            tick.boundary_ts_ns,
            tick.horizon_seconds,
            tick.scope,
            tick.symbol,
            tick.boundary_index,
        )
        for tick in ticks
    ]
    assert actual == _expected_order(horizons=horizons, symbols=symbols, event_ts=trigger)


def test_universe_context_uses_only_same_boundary_snapshots() -> None:
    """Boundary k's universe context is built only from boundary-k snapshots.

    Two symbols. AAA trades inside the open boundary, then one quote 95 s
    later crosses the skipped boundaries for both names. The synchronizer
    is wired behind the aggregator on the same bus.
    """
    symbols = frozenset({"AAA", "BBB"})
    bus = EventBus()
    contexts: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, contexts.append)
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=symbols,
        sensor_buffer_seconds=120,
        sequence_generator=SequenceGenerator(),
        horizon_features=[],
    )
    aggregator.attach()
    synchronizer = UniverseSynchronizer(
        bus=bus,
        universe=tuple(sorted(symbols)),
        horizons=(30,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    synchronizer.attach()
    sched = HorizonScheduler(
        horizons=frozenset({30}),
        session_id="P23G",
        symbols=symbols,
        session_open_ns=_OPEN,
        sequence_generator=SequenceGenerator(),
    )
    tape = [
        ("AAA", _OPEN + 5 * _NS),
        ("BBB", _OPEN + 10 * _NS),
        ("AAA", _OPEN + 95 * _NS),
    ]
    for seq, (symbol, ts) in enumerate(tape, start=1):
        for tick in sched.on_event(_quote(symbol, ts, seq)):
            bus.publish(tick)

    indexes = [ctx.boundary_index for ctx in contexts]
    assert indexes == [0, 1, 2, 3]
    for ctx in contexts:
        assert set(ctx.snapshots_by_symbol) == {"AAA", "BBB"}
        for symbol, snap in ctx.snapshots_by_symbol.items():
            assert snap is not None
            assert snap.boundary_index == ctx.boundary_index, (
                symbol,
                ctx.boundary_index,
                snap.boundary_index,
            )
