"""P5: a symbol's horizon boundaries alone and inside a wider universe.

The anchor is the backtest runner's unset-session_open rule. Share requires
every boundary timestamp the symbol emits alone to be emitted for it in the
wider universe. Identity requires the two sets to be the same.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import PlatformConfig
from feelies.core.session_clock import rth_open_ns
from feelies.harness.backtest_runner import _ensure_backtest_session_anchor
from feelies.sensors.horizon_scheduler import HorizonScheduler
from tests.sensors._helpers import make_quote

_NS = 1_000_000_000
_HORIZON = 30
_FOCUS = "BBB"


def _open_ns() -> int:
    probe = int(datetime(2026, 3, 26, 16, 0, tzinfo=timezone.utc).timestamp()) * _NS
    return rth_open_ns(probe)


def _events(open_ns: int) -> tuple[list, list]:
    """AAA crosses every 30s bucket. BBB skips the bucket that starts at +30s."""
    wider = [
        make_quote(symbol="AAA", ts_ns=open_ns + 10_000_000),
        make_quote(symbol="AAA", ts_ns=open_ns + 31 * _NS),
        make_quote(symbol="AAA", ts_ns=open_ns + 61 * _NS),
        make_quote(symbol=_FOCUS, ts_ns=open_ns + 25_000_000),
        make_quote(symbol=_FOCUS, ts_ns=open_ns + 62 * _NS),
    ]
    alone = [
        make_quote(symbol=_FOCUS, ts_ns=open_ns + 25_000_000),
        make_quote(symbol=_FOCUS, ts_ns=open_ns + 62 * _NS),
    ]
    return alone, wider


def _boundary_stamps(symbols: frozenset[str], events: list) -> set[int]:
    first = min(event.timestamp_ns for event in events)
    anchored = _ensure_backtest_session_anchor(
        PlatformConfig(symbols=symbols, horizons_seconds=frozenset({_HORIZON})),
        first_event_ts_ns=first,
    )
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id="P23F",
        symbols=symbols,
        session_open_ns=anchored.session_open_ns,
        sequence_generator=SequenceGenerator(),
    )
    stamps: set[int] = set()
    for event in sorted(events, key=lambda item: item.timestamp_ns):
        for tick in scheduler.on_event(event):
            if tick.scope == "SYMBOL" and tick.symbol == _FOCUS:
                stamps.add(tick.boundary_timestamp_ns)
    return stamps


def test_p5_solo_boundaries_are_a_subset_of_the_wider_universe() -> None:
    """Every boundary timestamp BBB emits alone is also emitted in the wider run."""
    alone_events, wider_events = _events(_open_ns())
    alone = _boundary_stamps(frozenset({_FOCUS}), alone_events)
    wider = _boundary_stamps(frozenset({"AAA", _FOCUS}), wider_events)
    assert alone, "BBB emitted no boundaries alone"
    missing = alone - wider
    share = len(alone & wider) / len(alone)
    assert not missing, f"solo-only boundaries {sorted(missing)}; share {share:.0%}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F-P23f-8: on a sparse tape a symbol run alone emits fewer boundaries "
        "than in a wider universe. Next rung P-23g emits every boundary exactly "
        "once, in order, with state as of the boundary time."
    ),
)
def test_p5_boundary_sets_are_identical_alone_and_in_a_wider_universe() -> None:
    """BBB's boundary timestamps are the same set alone and in a wider universe."""
    alone_events, wider_events = _events(_open_ns())
    alone = _boundary_stamps(frozenset({_FOCUS}), alone_events)
    wider = _boundary_stamps(frozenset({"AAA", _FOCUS}), wider_events)
    assert alone == wider
