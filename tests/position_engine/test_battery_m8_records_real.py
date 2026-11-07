"""Battery member 8, decision record completeness, real session (battery.md). P-59.

The clean run and its three copies are built the way member 6 real builds
them: placement rule P, then crossed, valuation-side removed, and feed-gap.
"""

from __future__ import annotations

import functools

import pytest

from feelies.core.events import NBBOQuote
from tests.position_engine.scenarios import (
    _resolution_key,
    placement_rule,
    rth_replay,
    run_real,
    slice_real_events,
)
from tests.position_engine.tapes import remove_side
from tests.position_engine.test_battery_m6_injection_real import (
    _FRACTION,
    _flatter,
    _gap,
    _quote_index,
    _sides,
    _spans,
    _transform,
)
from tests.position_engine.test_battery_m8_records_syn import (
    Run,
    check_adverse_records,
    check_favorable_reasons,
)

_ADVERSE = pytest.mark.battery_member(
    member=8,
    green_from="E",
    red_reason=r"^(CAP:gate_fire|NONVACUOUS)",
)
_FAVORABLE = pytest.mark.battery_member(
    member=8,
    green_from="E",
    red_reason=r"^NONVACUOUS",
)
_REAL = pytest.mark.battery_real


def _build_real_runs() -> list[Run]:
    clean_records = run_real(fraction=_FRACTION)
    events = slice_real_events(rth_replay(), fraction=_FRACTION)
    spans, decisions = _spans(clean_records, events)
    chosen = placement_rule(spans, decisions)
    if not chosen:
        raise AssertionError("CAP:gate_fire: A2: placement rule P found no eligible cell")
    blocked = set(decisions)
    sides = _sides(clean_records)
    crossed: dict[int, NBBOQuote] = {}
    removed: dict[int, NBBOQuote] = {}
    gap_sequences: set[int] = set()
    for cell_id, index in chosen:
        quote_index = _quote_index(events, index, blocked)
        if quote_index is None:
            continue
        quote = events[quote_index]
        assert type(quote) is NBBOQuote
        side = sides[cell_id]
        crossed[quote_index] = _flatter(quote, side)
        removed[quote_index] = remove_side([quote], 0, "bid" if side == "LONG" else "ask")[0]
        gap_sequences.add(quote.sequence)
    return [
        Run("clean", clean_records, False, "m6"),
        Run(
            "crossed",
            run_real(fraction=_FRACTION, quote_transform=_transform(crossed)),
            True,
            "m6",
        ),
        Run(
            "removed",
            run_real(fraction=_FRACTION, quote_transform=_transform(removed)),
            True,
            "m6",
        ),
        Run(
            "gap",
            run_real(fraction=_FRACTION, rail_wrapper=_gap(gap_sequences)),
            True,
            "m6",
        ),
    ]


@functools.lru_cache(maxsize=4)
def _cached_real_runs(resolution: str) -> tuple[Run, ...]:
    del resolution
    return tuple(_build_real_runs())


def real_runs() -> tuple[Run, ...]:
    return _cached_real_runs(_resolution_key())


@_ADVERSE
@_REAL
def test_m8_adverse_record_real() -> None:
    check_adverse_records(real_runs())


@_FAVORABLE
@_REAL
def test_m8_favorable_reasons_real() -> None:
    check_favorable_reasons(real_runs())
