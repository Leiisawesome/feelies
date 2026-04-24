"""Property-based tests for HorizonScheduler.

Two invariants we lock with Hypothesis:

1.  **Monotone boundary indices.**  For any sequence of monotone-
    increasing event timestamps, the boundary index emitted for any
    fixed ``(horizon, scope, symbol)`` triplet is strictly increasing.
2.  **Replay determinism.**  The ``HorizonTick`` stream produced by
    walking a randomly-generated event sequence twice — through two
    fresh schedulers with identical configuration — is byte-for-byte
    identical (Inv-C).
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from tests.sensors._helpers import make_quote


SESSION_OPEN_NS = 1_700_000_000_000_000_000
NS_PER_SECOND = 1_000_000_000


def _scheduler(horizons: frozenset[int], symbols: frozenset[str]) -> HorizonScheduler:
    return HorizonScheduler(
        horizons=horizons,
        session_id="PROP",
        symbols=symbols,
        session_open_ns=SESSION_OPEN_NS,
        sequence_generator=SequenceGenerator(),
    )


@settings(deadline=None, max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    horizon=st.sampled_from([10, 30, 60, 120, 300]),
    deltas=st.lists(
        st.integers(min_value=1, max_value=200),
        min_size=2,
        max_size=200,
    ),
)
def test_boundary_indices_strictly_monotone_per_triplet(
    horizon: int,
    deltas: list[int],
) -> None:
    sched = _scheduler(frozenset({horizon}), frozenset({"AAPL"}))
    last_seen: dict[tuple[int, str, str | None], int] = {}
    ts = SESSION_OPEN_NS
    for d in deltas:
        ts += d * NS_PER_SECOND
        for tick in sched.on_event(make_quote(symbol="AAPL", ts_ns=ts)):
            key = (tick.horizon_seconds, tick.scope, tick.symbol)
            prev = last_seen.get(key)
            if prev is not None:
                assert tick.boundary_index > prev, (
                    f"boundary regression for {key}: {prev} -> "
                    f"{tick.boundary_index}"
                )
            last_seen[key] = tick.boundary_index


@settings(deadline=None, max_examples=30, suppress_health_check=[HealthCheck.too_slow])
@given(
    horizons=st.sets(
        st.sampled_from([15, 30, 60, 120, 300]),
        min_size=1,
        max_size=3,
    ).map(frozenset),
    symbols=st.sets(
        st.sampled_from(["AAPL", "MSFT", "GOOG"]),
        min_size=1,
        max_size=3,
    ).map(frozenset),
    deltas=st.lists(
        st.integers(min_value=1, max_value=50),
        min_size=2,
        max_size=80,
    ),
)
def test_replay_through_two_schedulers_is_byte_identical(
    horizons: frozenset[int],
    symbols: frozenset[str],
    deltas: list[int],
) -> None:
    sched_a = _scheduler(horizons, symbols)
    sched_b = _scheduler(horizons, symbols)
    syms_sorted = sorted(symbols)

    ticks_a = []
    ticks_b = []
    ts = SESSION_OPEN_NS
    for i, d in enumerate(deltas):
        ts += d * NS_PER_SECOND
        sym = syms_sorted[i % len(syms_sorted)]
        q = make_quote(symbol=sym, ts_ns=ts)
        ticks_a.extend(sched_a.on_event(q))
        ticks_b.extend(sched_b.on_event(q))

    def serialize(ts_: list) -> list:
        return [
            (
                t.horizon_seconds,
                t.scope,
                t.symbol,
                t.boundary_index,
                t.session_id,
                t.correlation_id,
                t.timestamp_ns,
                t.sequence,
            )
            for t in ts_
        ]

    assert serialize(ticks_a) == serialize(ticks_b)
