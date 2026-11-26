"""P-61 favorable gate, outside the battery (D-228 pattern; D-241, D-244)."""

from __future__ import annotations

import inspect

import pytest

from feelies.position.favorable_gate import (
    REASONS,
    FavorableDecision,
    evaluate_favorable,
    giveback_ticks,
)

Q = 30_000_000_000


def _call(**overrides: object) -> FavorableDecision:
    values: dict[str, object] = {
        "form": "fixed",
        "size": 100,
        "target_ticks": 5,
        "giveback_spread_multiple": None,
        "ceiling_ticks": None,
        "entry_spread_ticks": 1,
        "fee_round_trip_ticks": 1,
        "move_now_cents": 0,
        "best_clean_cents": None,
        "best_clean_sequence": None,
        "dwelled_exit_mark": 9988,
        "valuation_side_absent": False,
        "crossed": False,
        "feed_gap_before": False,
        "dwell_window_clean": True,
        "warmed_up": True,
        "symbol_quiet_ns": 0,
        "quiet_limit_ns": Q,
    }
    values.update(overrides)

    def required_str(name: str) -> str:
        value = values[name]
        if not isinstance(value, str):
            raise AssertionError(name)
        return value

    def required_bool(name: str) -> bool:
        value = values[name]
        if not isinstance(value, bool):
            raise AssertionError(name)
        return value

    def required_int(name: str) -> int:
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise AssertionError(name)
        return value

    def optional_int(name: str) -> int | None:
        value = values[name]
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise AssertionError(name)
        return value

    def optional_float(name: str) -> float | None:
        value = values[name]
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, float):
            raise AssertionError(name)
        return value

    return evaluate_favorable(
        form=required_str("form"),
        size=required_int("size"),
        target_ticks=optional_int("target_ticks"),
        giveback_spread_multiple=optional_float("giveback_spread_multiple"),
        ceiling_ticks=optional_int("ceiling_ticks"),
        entry_spread_ticks=required_int("entry_spread_ticks"),
        fee_round_trip_ticks=required_int("fee_round_trip_ticks"),
        move_now_cents=optional_int("move_now_cents"),
        best_clean_cents=optional_int("best_clean_cents"),
        best_clean_sequence=optional_int("best_clean_sequence"),
        dwelled_exit_mark=optional_int("dwelled_exit_mark"),
        valuation_side_absent=required_bool("valuation_side_absent"),
        crossed=required_bool("crossed"),
        feed_gap_before=required_bool("feed_gap_before"),
        dwell_window_clean=required_bool("dwell_window_clean"),
        warmed_up=required_bool("warmed_up"),
        symbol_quiet_ns=required_int("symbol_quiet_ns"),
        quiet_limit_ns=required_int("quiet_limit_ns"),
    )


# R = 2, round trip 3, arming threshold 500.
TRAIL: dict[str, object] = dict(
    form="trailing",
    target_ticks=None,
    giveback_spread_multiple=1.0,
    entry_spread_ticks=2,
)


def test_giveback_exact_fraction() -> None:
    assert giveback_ticks(0.29, 100) == 29


@pytest.mark.parametrize(
    ("k", "spread"),
    [(0.5, 1), (1.0, 0), (1.0, -2)],
)
def test_giveback_floor_at_one(k: float, spread: int) -> None:
    assert giveback_ticks(k, spread) == 1


def test_giveback_not_inverted() -> None:
    assert giveback_ticks(2.0, 3) == 6


@pytest.mark.parametrize(
    ("token", "overrides"),
    [
        ("VALUATION_SIDE_ABSENT", {"valuation_side_absent": True}),
        ("CROSSED", {"crossed": True}),
        ("FEED_GAP", {"feed_gap_before": True}),
        ("DWELL_NOT_CLEAN", {"dwell_window_clean": False}),
        ("NOT_WARMED_UP", {"warmed_up": False}),
        ("SYMBOL_QUIET", {"symbol_quiet_ns": Q + 1}),
    ],
    ids=(
        "VALUATION_SIDE_ABSENT",
        "CROSSED",
        "FEED_GAP",
        "DWELL_NOT_CLEAN",
        "NOT_WARMED_UP",
        "SYMBOL_QUIET",
    ),
)
def test_single_block(token: str, overrides: dict[str, object]) -> None:
    decision = _call(move_now_cents=500, **overrides)
    assert decision.outcome == "suppressed"
    assert decision.reason == token
    assert decision.suppressions == (token,)


def test_all_blocks_in_order() -> None:
    decision = _call(
        valuation_side_absent=True,
        crossed=True,
        feed_gap_before=True,
        dwell_window_clean=False,
        warmed_up=False,
        symbol_quiet_ns=Q + 1,
    )
    assert decision.suppressions == REASONS
    assert decision.reason == REASONS[0]


def test_quiet_is_strict() -> None:
    assert _call(symbol_quiet_ns=Q, move_now_cents=500).outcome == "fire"


def test_blocked_never_compares() -> None:
    assert _call(crossed=True, move_now_cents=0).outcome == "suppressed"


def test_fixed_fires_at_boundary() -> None:
    assert _call(move_now_cents=500) == FavorableDecision("fire", "", (), "fixed", 9988, 5, None)


def test_fixed_none_one_cent_under() -> None:
    decision = _call(move_now_cents=499)
    assert decision.outcome == "none"
    assert decision.reason == ""
    assert decision.suppressions == ()


@pytest.mark.parametrize("target_ticks", [2, 1])
def test_fixed_disarmed(target_ticks: int) -> None:
    assert _call(target_ticks=target_ticks, move_now_cents=10_000).outcome == "none"


def test_trailing_unset_peak() -> None:
    assert _call(**TRAIL, best_clean_cents=None, move_now_cents=0).outcome == "none"


def test_trailing_arming_is_strict() -> None:
    assert _call(**TRAIL, best_clean_cents=500, move_now_cents=0).outcome == "none"


def test_trailing_fires_at_boundary() -> None:
    assert _call(
        **TRAIL,
        best_clean_cents=501,
        best_clean_sequence=77,
        move_now_cents=301,
    ) == FavorableDecision("fire", "", (), "trailing", 9988, 2, 77)


def test_trailing_none_one_cent_over() -> None:
    assert _call(**TRAIL, best_clean_cents=501, move_now_cents=302).outcome == "none"


def test_none_move_is_none() -> None:
    assert _call(move_now_cents=None).outcome == "none"


@pytest.mark.parametrize("mark", [9988, None])
def test_proposed_is_dwelled_mark(mark: int | None) -> None:
    decision = _call(move_now_cents=500, dwelled_exit_mark=mark)
    assert decision.outcome == "fire"
    assert decision.proposed_price_cents is mark


def test_ceiling_raises() -> None:
    with pytest.raises(ValueError):
        _call(ceiling_ticks=10)


def test_signature_excludes_forbidden() -> None:
    names = set(inspect.signature(evaluate_favorable).parameters)
    forbidden = {
        "forced_exit_mark",
        "worst_side_mark",
        "paying_mark",
        "valuation_age_ns",
        "locked",
        "move_worst",
        "move_forced",
    }
    assert names.isdisjoint(forbidden)
