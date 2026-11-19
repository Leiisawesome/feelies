"""P-60 adverse gate, outside the battery (D-228 pattern; D-241, D-243)."""

from __future__ import annotations

import hashlib

import pytest

from feelies.position.adverse_gate import AdverseDecision, drawn_level, evaluate_adverse

A = 30_000_000_000


def _section9(cell_id: str, centre: int, band: int) -> int:
    """Restate contracts.md §9 with hashlib, independently of drawn_level."""
    hashed = int.from_bytes(hashlib.sha256(cell_id.encode("utf-8")).digest()[:8], "big")
    return (centre - band // 2) + (hashed % (band + 1))


def _call(**overrides: object) -> AdverseDecision:
    values: dict[str, object] = {
        "cell_id": "SYN|sig|1|LONG",
        "centre": 11,
        "band": 0,
        "blind_limit_ns": A,
        "size": 100,
        "move_worst": 0,
        "forced_exit_mark": 9988,
        "paying_absent_ns": 0,
        "valuation_absent_ns": 0,
        "quiet_ns": 0,
    }
    values.update(overrides)

    def required_str(name: str) -> str:
        value = values[name]
        if not isinstance(value, str):
            raise AssertionError(name)
        return value

    def required_int(name: str) -> int:
        value = values[name]
        if not isinstance(value, int):
            raise AssertionError(name)
        return value

    def optional_int(name: str) -> int | None:
        value = values[name]
        if value is None:
            return None
        if not isinstance(value, int):
            raise AssertionError(name)
        return value

    return evaluate_adverse(
        cell_id=required_str("cell_id"),
        centre=required_int("centre"),
        band=required_int("band"),
        blind_limit_ns=required_int("blind_limit_ns"),
        size=required_int("size"),
        move_worst=optional_int("move_worst"),
        forced_exit_mark=optional_int("forced_exit_mark"),
        paying_absent_ns=required_int("paying_absent_ns"),
        valuation_absent_ns=required_int("valuation_absent_ns"),
        quiet_ns=required_int("quiet_ns"),
    )


def test_drawn_level_band_zero_is_centre() -> None:
    for cell_id in ("SYN|sig|1|LONG", "APP|a|2|SHORT"):
        assert drawn_level(cell_id, 11, 0) == 11


def test_drawn_level_matches_section_9() -> None:
    for i in range(1, 6):
        cell_id = f"SYN|s|{i}|LONG"
        assert drawn_level(cell_id, 11, 4) == _section9(cell_id, 11, 4)


def test_drawn_level_in_band_and_deterministic() -> None:
    for i in range(1000):
        cell_id = f"SYN|s|{i}|LONG"
        level = drawn_level(cell_id, 11, 8)
        assert 7 <= level <= 15
        assert drawn_level(cell_id, 11, 8) == level


def test_level_fires_at_boundary() -> None:
    assert _call(band=0, size=100, move_worst=-1100) == AdverseDecision("fire", "LEVEL", 11, 9988)


def test_level_holds_one_cent_inside() -> None:
    assert _call(move_worst=-1099) == AdverseDecision("hold", "", 11, 9988)


@pytest.mark.parametrize(
    "measure",
    ["paying_absent_ns", "valuation_absent_ns", "quiet_ns"],
)
def test_blind_is_strict(measure: str) -> None:
    assert _call(**{measure: A}).outcome == "hold"
    beyond = _call(**{measure: A + 1})
    assert (beyond.outcome, beyond.trigger) == ("fire", "BLIND")


def test_blind_precedes_level() -> None:
    assert _call(quiet_ns=A + 1, move_worst=-1100).trigger == "BLIND"


def test_none_move_holds() -> None:
    decision = _call(move_worst=None)
    assert decision.outcome == "hold"
    assert decision.trigger == ""


def test_none_move_fires_blind_beyond_limit() -> None:
    decision = _call(move_worst=None, valuation_absent_ns=A + 1)
    assert (decision.outcome, decision.trigger) == ("fire", "BLIND")


def test_outputs_are_ints_and_proposed_is_forced_mark() -> None:
    marked = _call(forced_exit_mark=9988)
    assert type(marked.drawn_level_ticks) is int
    assert marked.proposed_price_cents == 9988
    unmarked = _call(forced_exit_mark=None)
    assert unmarked.proposed_price_cents is None
