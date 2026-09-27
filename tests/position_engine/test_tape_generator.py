"""Synthetic tape generator: lattice, drift, hitting probability, injectors."""

from __future__ import annotations

import copy
import math
import time
from decimal import Decimal

import pytest

from feelies.core.quote_quality import QuoteQuality, classify
from tests.position_engine import tapes
from tests.position_engine.tapes import (
    bid_path_cents,
    cross,
    excise,
    hold,
    lattice_barrier,
    make_tape,
    remove_side,
    remove_side_run,
    set_quote,
    shift_from,
)

_G3_N = 64
_G3_M = 20_000


def _integer_cents(price: object) -> bool:
    cents = price * 100  # type: ignore[operator]
    return cents == int(cents)


def test_g1_lattice() -> None:
    spread = 1
    for seed in (1, 2, 3):
        tape = make_tape(seed=seed, n=50_000, spread_cents=spread)
        path = bid_path_cents(tape)
        assert path == [int(quote.bid * 100) for quote in tape]
        for quote, bid_c in zip(tape, path, strict=True):
            assert _integer_cents(quote.bid)
            assert _integer_cents(quote.ask)
            assert quote.ask - quote.bid == quote.bid.__class__(spread) / 100
            assert int(quote.ask * 100) - bid_c == spread


def test_g2_driftless() -> None:
    n = 400_000
    p_move = 0.25
    path = bid_path_cents(make_tape(seed=7, n=n, p_move=p_move))
    steps = [path[i] - path[i - 1] for i in range(1, len(path))]
    mean = sum(steps) / len(steps)
    bound = 4 * math.sqrt(2 * p_move) / math.sqrt(n - 1)
    print(f"G2 mean {mean}")
    assert abs(mean) <= bound


def _favorable_share(up_ticks: int, down_ticks: int) -> float:
    up = lattice_barrier(0, up_ticks)
    down = lattice_barrier(0, -down_ticks)
    hit_up = 0
    for seed in range(_G3_M):
        path = bid_path_cents(make_tape(seed=seed, n=_G3_N))
        origin = path[0]
        winner: int | None = None
        for cents in path:
            rel = cents - origin
            if rel >= up:
                winner = 1
                break
            if rel <= down:
                winner = -1
                break
        assert winner is not None, f"seed {seed} hit neither barrier within {_G3_N}"
        hit_up += winner == 1
    return hit_up / _G3_M


def test_g3_hitting_probability() -> None:
    share_up1 = _favorable_share(1, 2)
    share_up2 = _favorable_share(2, 1)
    tol = 4 * math.sqrt((2 / 3) * (1 / 3) / _G3_M)
    print(f"G3 n {_G3_N} share +1/-2 {share_up1} share +2/-1 {share_up2}")
    assert abs(share_up1 - (2 / 3)) <= tol
    assert abs(share_up2 - (1 / 3)) <= tol


def test_g4_reproducible() -> None:
    args = {"seed": 1, "n": 200}
    assert make_tape(**args) == make_tape(**args)
    path_a = bid_path_cents(make_tape(seed=1, n=200))
    path_b = bid_path_cents(make_tape(seed=2, n=200))
    assert path_a != path_b


def test_g5_no_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> float:
        raise RuntimeError("clock")

    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "time_ns", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)
    monkeypatch.setattr(time, "perf_counter", _boom)
    make_tape(seed=1, n=1000)


def test_g6_guards() -> None:
    with pytest.raises(ValueError):
        make_tape(seed=1, n=10, spread_cents=0)
    with pytest.raises(ValueError):
        make_tape(seed=1, n=10, p_move=0)
    with pytest.raises(ValueError):
        make_tape(seed=1, n=10, p_move=0.6)
    with pytest.raises(RuntimeError, match="tape left the penny-tick region"):
        make_tape(seed=1, n=10_000, start_bid_cents=150, p_move=0.5)


def _preserved(out: list, src: list) -> None:
    assert len(out) == len(src)
    assert [q.sequence for q in out] == [q.sequence for q in src]
    assert [q.timestamp_ns for q in out] == [q.timestamp_ns for q in src]
    assert [q.exchange_timestamp_ns for q in out] == [q.exchange_timestamp_ns for q in src]


def test_g7_injectors() -> None:
    tape = make_tape(seed=3, n=30)
    for quote in tape:
        assert classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID

    snapshot = copy.deepcopy(tape)
    held = hold(tape, 4, 3)
    assert tape == snapshot
    _preserved(held, tape)
    for quote in held[5:8]:
        assert quote.bid == tape[4].bid
        assert quote.ask == tape[4].ask
        assert quote.bid_size == tape[4].bid_size
        assert quote.ask_size == tape[4].ask_size
        assert classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID
    with pytest.raises(IndexError):
        hold(tape, 28, 3)

    snapshot = copy.deepcopy(tape)
    removed = remove_side(tape, 6, "bid")
    assert tape == snapshot
    _preserved(removed, tape)
    assert (
        classify(removed[6].bid, removed[6].ask, removed[6].bid_size, removed[6].ask_size)
        is QuoteQuality.ZERO_SZ
    )

    snapshot = copy.deepcopy(tape)
    crossed = cross(tape, 7, bid_cents=10_050, ask_cents=10_040)
    assert tape == snapshot
    _preserved(crossed, tape)
    assert (
        classify(crossed[7].bid, crossed[7].ask, crossed[7].bid_size, crossed[7].ask_size)
        is QuoteQuality.CROSSED
    )
    with pytest.raises(ValueError):
        cross(tape, 7, bid_cents=10_040, ask_cents=10_050)


def test_g8_set_quote_replaces_prices_keeps_identity() -> None:
    tape = make_tape(seed=3, n=8, size=1000)
    snapshot = copy.deepcopy(tape)
    out = set_quote(tape, 3, bid_cents=10_010, ask_cents=10_014, bid_size=40, ask_size=50)
    assert tape == snapshot
    assert out[3].bid == Decimal("100.10")
    assert out[3].ask == Decimal("100.14")
    assert out[3].bid_size == 40
    assert out[3].ask_size == 50
    assert out[3].timestamp_ns == tape[3].timestamp_ns
    assert out[3].exchange_timestamp_ns == tape[3].exchange_timestamp_ns
    assert out[3].sequence == tape[3].sequence
    assert out[3].symbol == tape[3].symbol
    assert out[2] == tape[2]
    prices_only = set_quote(tape, 3, bid_cents=10_020, ask_cents=10_021)
    assert prices_only[3].bid_size == tape[3].bid_size
    assert prices_only[3].ask_size == tape[3].ask_size
    with pytest.raises(ValueError):
        set_quote(tape, 3, bid_cents=10_010, ask_cents=10_010)
    with pytest.raises(ValueError):
        set_quote(tape, 3, bid_cents=10_012, ask_cents=10_011)


def test_g8_excise_keeps_sequences_and_rejects_bad_spans() -> None:
    tape = make_tape(seed=3, n=10, start_sequence=7)
    snapshot = copy.deepcopy(tape)
    out = excise(tape, 2, 3)
    assert tape == snapshot
    assert len(out) == 7
    assert [quote.sequence for quote in out] == [7, 8, 12, 13, 14, 15, 16]
    assert [quote.timestamp_ns for quote in out] == [
        tape[i].timestamp_ns for i in (0, 1, 5, 6, 7, 8, 9)
    ]
    with pytest.raises(IndexError):
        excise(tape, 8, 3)
    with pytest.raises(ValueError):
        excise(tape, 0, 0)


def test_g9_shift_from_and_remove_side_run() -> None:
    tape = make_tape(seed=3, n=12, size=1000)
    snapshot = copy.deepcopy(tape)
    shifted = shift_from(tape, 4, 5)
    assert tape == snapshot
    _preserved(shifted, tape)
    assert shifted[3].bid == tape[3].bid
    assert shifted[3].ask == tape[3].ask
    for quote, src in zip(shifted[4:], tape[4:], strict=True):
        assert quote.bid == src.bid + Decimal("0.05")
        assert quote.ask == src.ask + Decimal("0.05")
        assert quote.bid_size == src.bid_size
        assert quote.ask_size == src.ask_size
        assert quote.sequence == src.sequence
        assert quote.timestamp_ns == src.timestamp_ns

    removed = remove_side_run(tape, 2, 3, "ask")
    assert tape == snapshot
    _preserved(removed, tape)
    assert removed[1].ask_size == tape[1].ask_size
    for quote in removed[2:5]:
        assert quote.ask_size == 0
        assert quote.bid_size == tape[quote.sequence - tape[0].sequence].bid_size
    assert removed[5].ask_size == tape[5].ask_size

    offending = tape[6].sequence
    with pytest.raises(ValueError, match=str(offending)):
        shift_from(tape, 6, -20_000)
    with pytest.raises(ValueError):
        remove_side_run(tape, 0, 0, "bid")
    with pytest.raises(IndexError):
        remove_side_run(tape, 10, 3, "bid")
    with pytest.raises(IndexError):
        remove_side_run(tape, -1, 1, "bid")


def test_g9_shift_from_after_excise_matches_census_c2() -> None:
    """Seed 11, V3a. Excise 20 quotes at sequence 303, then shift −15 cents from q_g."""
    tape = make_tape(seed=11, n=400, symbol="SYN", start_ns=1_774_533_600_000_000_000, size=1000)
    out = shift_from(excise(tape, 302, 20), 302, -15)
    by_seq = {quote.sequence: quote for quote in out}
    assert by_seq[323].bid == Decimal("99.76")
    assert by_seq[323].ask == Decimal("99.77")
    assert by_seq[324].bid == Decimal("99.75")
    assert by_seq[324].ask == Decimal("99.76")


_FORCE_EXPECT = {
    "NONPOS_BID": (QuoteQuality.NONPOS, Decimal("0"), Decimal("100.02"), None, None),
    "NONPOS_ASK": (QuoteQuality.NONPOS, Decimal("100.01"), Decimal("0"), None, None),
    "CROSSED": (QuoteQuality.CROSSED, Decimal("100.50"), Decimal("100.00"), None, None),
    "LOCKED": (QuoteQuality.LOCKED, Decimal("100.00"), Decimal("100.00"), None, None),
    "ZERO_SZ_BID": (QuoteQuality.ZERO_SZ, None, None, 0, 1000),
    "ZERO_SZ_ASK": (QuoteQuality.ZERO_SZ, None, None, 1000, 0),
}


@pytest.mark.parametrize("cls", sorted(_FORCE_EXPECT))
def test_force_class_round_trips_and_does_not_mutate(cls: str) -> None:
    tape = make_tape(seed=3, n=8, size=1000)
    snapshot = copy.deepcopy(tape)
    original = tape[3]
    out = tapes.force_class(tape, 3, cls)
    assert tape == snapshot
    assert tape[3] is original
    quote = out[3]
    assert quote.timestamp_ns == tape[3].timestamp_ns
    assert quote.exchange_timestamp_ns == tape[3].exchange_timestamp_ns
    assert quote.sequence == tape[3].sequence
    assert quote.symbol == tape[3].symbol
    quality, bid, ask, bid_size, ask_size = _FORCE_EXPECT[cls]
    assert classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is quality
    if bid is not None:
        assert quote.bid == bid
        assert quote.ask == ask
    if bid_size is not None:
        assert quote.bid_size == bid_size
        assert quote.ask_size == ask_size
    assert out[2] == tape[2]
    assert out[4] == tape[4]
