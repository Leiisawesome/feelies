"""Tests for HorizonScheduler boundary math, ordering, and lazy bind."""

from __future__ import annotations

import pytest

from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.horizon_scheduler import (
    HorizonScheduler,
    SessionOpenAlreadyBoundError,
)
from tests.sensors._helpers import make_quote


SESSION_OPEN_NS = 1_000_000_000_000_000_000  # arbitrary anchor


def _make_scheduler(
    *,
    horizons: frozenset[int] = frozenset({30, 120}),
    symbols: frozenset[str] = frozenset({"AAPL", "MSFT"}),
    session_open_ns: int | None = SESSION_OPEN_NS,
    session_id: str = "TEST_RTH",
) -> HorizonScheduler:
    return HorizonScheduler(
        horizons=horizons,
        session_id=session_id,
        symbols=symbols,
        session_open_ns=session_open_ns,
        sequence_generator=SequenceGenerator(),
    )


def test_first_event_emits_boundary_zero_for_each_scope() -> None:
    sched = _make_scheduler()
    ticks = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS))
    # 2 horizons × (2 SYMBOL + 1 UNIVERSE) = 6 ticks
    assert len(ticks) == 6
    assert all(t.boundary_index == 0 for t in ticks)


def test_emission_order_horizon_then_scope_then_symbol() -> None:
    sched = _make_scheduler(symbols=frozenset({"ZZZ", "AAA", "MID"}))
    ticks = sched.on_event(make_quote(symbol="AAA", ts_ns=SESSION_OPEN_NS))
    # Per plan §3.2: horizon asc, then SYMBOL before UNIVERSE, then symbol asc.
    expected = [
        (30, "SYMBOL", "AAA"),
        (30, "SYMBOL", "MID"),
        (30, "SYMBOL", "ZZZ"),
        (30, "UNIVERSE", None),
        (120, "SYMBOL", "AAA"),
        (120, "SYMBOL", "MID"),
        (120, "SYMBOL", "ZZZ"),
        (120, "UNIVERSE", None),
    ]
    actual = [(t.horizon_seconds, t.scope, t.symbol) for t in ticks]
    assert actual == expected


def test_no_emission_within_same_boundary_window() -> None:
    sched = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS))
    second = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 5 * 1_000_000_000))
    assert second == ()


def test_emission_when_boundary_crossed() -> None:
    sched = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS))
    ticks = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 31 * 1_000_000_000))
    assert len(ticks) == 2  # SYMBOL + UNIVERSE for boundary_index=1
    assert {t.boundary_index for t in ticks} == {1}


def test_pre_session_event_does_not_emit_negative_boundary() -> None:
    sched = _make_scheduler()
    ticks = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS - 1))
    assert ticks == ()


def test_lazy_bind_uses_first_event_timestamp() -> None:
    sched = _make_scheduler(session_open_ns=None)
    assert sched.session_open_ns is None
    first_ts = 5_000_000_000
    sched.on_event(make_quote(ts_ns=first_ts))
    assert sched.session_open_ns == first_ts


def test_bind_after_event_raises_session_open_already_bound() -> None:
    sched = _make_scheduler(session_open_ns=None)
    sched.on_event(make_quote(ts_ns=1_000))
    with pytest.raises(SessionOpenAlreadyBoundError):
        sched.bind_session_open(2_000)


def test_explicit_bind_before_first_event_succeeds() -> None:
    sched = _make_scheduler(session_open_ns=None)
    sched.bind_session_open(7_777)
    assert sched.session_open_ns == 7_777


def test_construct_with_session_open_locks_immediately() -> None:
    sched = _make_scheduler(session_open_ns=42)
    with pytest.raises(SessionOpenAlreadyBoundError):
        sched.bind_session_open(43)


def test_zero_horizon_rejected() -> None:
    with pytest.raises(ValueError):
        _make_scheduler(horizons=frozenset({0, 30}))


def test_correlation_id_is_deterministic_from_boundary_math() -> None:
    sched1 = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    sched2 = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    t1 = sched1.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 100))
    t2 = sched2.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 999))
    assert [t.correlation_id for t in t1] == [t.correlation_id for t in t2]


def test_session_id_propagates_to_every_tick() -> None:
    sched = _make_scheduler(session_id="MY_RTH_2026-01-15")
    ticks = sched.on_event(make_quote(ts_ns=SESSION_OPEN_NS))
    assert {t.session_id for t in ticks} == {"MY_RTH_2026-01-15"}


def test_sequence_numbers_are_monotonic() -> None:
    sched = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    t1 = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS))
    t2 = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 31_000_000_000))
    seqs = [t.sequence for t in t1] + [t.sequence for t in t2]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_empty_horizons_makes_on_event_a_noop() -> None:
    sched = _make_scheduler(horizons=frozenset())
    assert sched.on_event(make_quote()) == ()


def test_universe_tick_has_none_symbol_and_universe_scope() -> None:
    sched = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    ticks = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS))
    universe = [t for t in ticks if t.scope == "UNIVERSE"]
    assert len(universe) == 1
    assert universe[0].symbol is None


def test_late_event_at_same_boundary_does_not_re_emit() -> None:
    sched = _make_scheduler(horizons=frozenset({30}), symbols=frozenset({"AAPL"}))
    sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 100))
    sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 60_000_000_000))  # boundary 2
    third = sched.on_event(make_quote(symbol="AAPL", ts_ns=SESSION_OPEN_NS + 65_000_000_000))
    assert third == ()
