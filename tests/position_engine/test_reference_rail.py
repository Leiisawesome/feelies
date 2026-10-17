"""Reference rail. One behaviour per contract row. Not a battery member."""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.core.quote_quality import QuoteQuality, classify
from tests.position_engine.reference.rail import ReferenceRail
from tests.position_engine.tapes import excise, force_class, make_tape, remove_side_run

_CLASSES = (
    "NONPOS_BID",
    "NONPOS_ASK",
    "CROSSED",
    "LOCKED",
    "ZERO_SZ_BID",
    "ZERO_SZ_ASK",
)
_INTERVAL = 100_000_000
_CENTS = (
    "paying_mark_cents",
    "valuation_mark_cents",
    "worst_side_mark_cents",
    "forced_exit_mark_cents",
    "dwelled_exit_mark_cents",
)


def _rail() -> ReferenceRail:
    return ReferenceRail(SequenceGenerator(stream="mark_rail", thread_safe=False))


def _quote(
    sequence: int,
    timestamp_ns: int,
    *,
    bid_cents: int,
    ask_cents: int,
    bid_size: int = 100,
    ask_size: int = 100,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="SYN",
        bid=Decimal(bid_cents) / 100,
        ask=Decimal(ask_cents) / 100,
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=timestamp_ns,
    )


def _absent(update: object) -> None:
    for name in ("long", "short"):
        side = getattr(update, name)
        assert side.paying_side_absent is True
        assert side.valuation_side_absent is True


@pytest.mark.parametrize("cls", _CLASSES)
def test_d62_class_marks_both_sides_absent(cls: str) -> None:
    tape = make_tape(seed=11, n=2, symbol="SYN", start_ns=1_000, interval_ns=_INTERVAL, size=1000)
    injected = force_class(tape, 1, cls)
    rail = _rail()
    first = rail.on_quote(injected[0])
    second = rail.on_quote(injected[1])
    assert first.feed_gap_before is False
    assert second.feed_gap_before is False
    _absent(second)
    quality = classify(
        injected[1].bid, injected[1].ask, injected[1].bid_size, injected[1].ask_size
    )
    if cls.startswith("NONPOS"):
        assert quality is QuoteQuality.NONPOS
    elif cls == "CROSSED":
        assert quality is QuoteQuality.CROSSED
        assert second.crossed is True
    elif cls == "LOCKED":
        assert quality is QuoteQuality.LOCKED
        assert second.locked is True
    else:
        assert quality is QuoteQuality.ZERO_SZ
    gap = injected[1].exchange_timestamp_ns - injected[0].exchange_timestamp_ns
    assert second.symbol_quiet_ns == gap
    for name in ("long", "short"):
        side = getattr(second, name)
        assert side.paying_absent_for_ns == gap
        assert side.valuation_absent_for_ns == gap
        assert side.paying_mark_cents == getattr(first, name).paying_mark_cents
        assert side.valuation_mark_cents == getattr(first, name).valuation_mark_cents


def test_held_price_republishes_last_present() -> None:
    rail = _rail()
    first = rail.on_quote(_quote(1, 1_000, bid_cents=10_000, ask_cents=10_001))
    held = rail.on_quote(_quote(2, 1_000 + _INTERVAL, bid_cents=10_050, ask_cents=10_000))
    assert held.crossed is True
    _absent(held)
    assert held.long.paying_mark_cents == first.long.paying_mark_cents == 10_001
    assert held.long.valuation_mark_cents == first.long.valuation_mark_cents == 10_000
    assert held.short.paying_mark_cents == 10_000
    assert held.short.valuation_mark_cents == 10_001


def test_none_before_any_usable_value() -> None:
    rail = _rail()
    first = rail.on_quote(_quote(1, 5_000, bid_cents=0, ask_cents=10_002))
    _absent(first)
    assert first.symbol_quiet_ns == 0
    for name in ("long", "short"):
        side = getattr(first, name)
        for field in _CENTS:
            assert getattr(side, field) is None
        assert side.paying_absent_for_ns == 0
        assert side.valuation_absent_for_ns == 0
    second = rail.on_quote(_quote(2, 5_000 + _INTERVAL, bid_cents=0, ask_cents=10_002))
    _absent(second)
    assert second.symbol_quiet_ns == _INTERVAL
    for name in ("long", "short"):
        side = getattr(second, name)
        for field in _CENTS:
            assert getattr(side, field) is None
        assert side.paying_absent_for_ns == _INTERVAL
        assert side.valuation_absent_for_ns == _INTERVAL


@pytest.mark.parametrize("count", (299, 300, 301))
def test_absence_clock_triplet(count: int) -> None:
    tape = make_tape(
        seed=11,
        n=count + 1,
        symbol="SYN",
        start_ns=1_000,
        interval_ns=_INTERVAL,
        size=1000,
    )
    removed = remove_side_run(tape, 1, count, "bid")
    rail = _rail()
    updates = [rail.on_quote(quote) for quote in removed]
    last = updates[-1]
    expected = removed[-1].exchange_timestamp_ns - removed[0].exchange_timestamp_ns
    _absent(last)
    for name in ("long", "short"):
        side = getattr(last, name)
        assert side.paying_absent_for_ns == expected
        assert side.valuation_absent_for_ns == expected


@pytest.mark.parametrize("n_excise", (298, 299, 300))
def test_quiet_clock_triplet(n_excise: int) -> None:
    tape = make_tape(
        seed=11,
        n=n_excise + 3,
        symbol="SYN",
        start_ns=1_000,
        interval_ns=_INTERVAL,
        size=1000,
    )
    out = excise(tape, 1, n_excise)
    rail = _rail()
    updates = [rail.on_quote(quote) for quote in out]
    gap = out[1].exchange_timestamp_ns - out[0].exchange_timestamp_ns
    assert updates[1].symbol_quiet_ns == gap
    assert (
        updates[2].symbol_quiet_ns == out[2].exchange_timestamp_ns - out[1].exchange_timestamp_ns
    )


def test_dwell_window_drops_quote_older_than_t_minus_d(monkeypatch: pytest.MonkeyPatch) -> None:
    dwell = 2_000_000_000
    monkeypatch.setenv("FEELIES_RAIL_DWELL_NS", str(dwell))
    rail = _rail()
    current = 20_000_000_000
    outside = current - dwell - _INTERVAL
    inside = current - _INTERVAL
    rail.on_quote(_quote(1, outside, bid_cents=1, ask_cents=2))
    rail.on_quote(_quote(2, inside, bid_cents=50, ask_cents=51))
    update = rail.on_quote(_quote(3, current, bid_cents=80, ask_cents=81))
    assert update.long.dwelled_exit_mark_cents == 50
    assert update.short.dwelled_exit_mark_cents == 81
    assert update.long.dwell_window_clean is True
    assert update.warmed_up is True


def test_slippage_worsens_forced_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEELIES_RAIL_SLIPPAGE_TICKS", "4")
    update = _rail().on_quote(_quote(1, 1_000, bid_cents=10_000, ask_cents=10_001))
    assert update.long.worst_side_mark_cents == 10_000
    assert update.long.forced_exit_mark_cents == 9_996
    assert update.short.worst_side_mark_cents == 10_001
    assert update.short.forced_exit_mark_cents == 10_005
    assert update.feed_gap_before is False


def test_env_read_in_a_fresh_child() -> None:
    code = (
        "from feelies.core.identifiers import SequenceGenerator\n"
        "from tests.position_engine.reference.rail import ReferenceRail\n"
        "rail = ReferenceRail(SequenceGenerator(stream='mark_rail', thread_safe=False))\n"
        "print(rail.dwell_ns, rail.slippage_ticks)\n"
    )
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["FEELIES_RAIL_DWELL_NS"] = "2000000000"
    env["FEELIES_RAIL_SLIPPAGE_TICKS"] = "4"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "2000000000 4"
