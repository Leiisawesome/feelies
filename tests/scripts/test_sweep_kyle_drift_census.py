"""Unit tests for the H10 sweep_kyle_drift census instrument (no cache contact).

Phase-A pin: predicate helpers, warm-drop, integrity pin, and filter residual
logic only — zero forward-return / IC / grid execution (N = 11 unchanged).
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import Trade
from scripts.research.sweep_kyle_drift_census import (
    apply_warm_drop_rule,
    integrity_pin_check,
    is_entry_eligible,
    trade_fails_sfi_filter,
)


def _trade(
    *,
    conditions: tuple[int, ...] = (14,),
    correction: int | None = None,
) -> Trade:
    return Trade(
        timestamp_ns=1,
        correlation_id="t",
        sequence=1,
        symbol="APP",
        price=Decimal("100"),
        size=100,
        exchange_timestamp_ns=1,
        conditions=conditions,
        correction=correction,
    )


def test_entry_eligible_long_short_and_interior_null() -> None:
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=1.0, p_breakout=0.2) == (
        True,
        "LONG",
    )
    assert is_entry_eligible(sfi=-0.5, pctl=0.05, rvz=1.0, p_breakout=0.2) == (
        True,
        "SHORT",
    )
    assert is_entry_eligible(sfi=0.5, pctl=0.50, rvz=1.0, p_breakout=0.2) == (
        False,
        None,
    )


def test_entry_eligible_sign_disagreement_and_gates() -> None:
    assert is_entry_eligible(sfi=-0.1, pctl=0.95, rvz=1.0, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.1, pctl=0.05, rvz=1.0, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=3.1, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=1.0, p_breakout=0.7)[0] is False
    assert is_entry_eligible(sfi=None, pctl=0.95, rvz=1.0, p_breakout=0.2)[0] is False


def test_trade_fails_sfi_filter_boundaries() -> None:
    assert trade_fails_sfi_filter(_trade(conditions=(14,))) is False
    assert trade_fails_sfi_filter(_trade(conditions=(14, 37, 41))) is False
    assert trade_fails_sfi_filter(_trade(conditions=(8,))) is True
    assert trade_fails_sfi_filter(_trade(conditions=(12,))) is True
    assert trade_fails_sfi_filter(_trade(conditions=(14,), correction=10)) is True
    assert trade_fails_sfi_filter(_trade(conditions=(14,), correction=1)) is False


def test_warm_drop_rule() -> None:
    # 3 sessions below 0.5 → drop
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.2, 0.9], "RMBS": [0.9, 0.9]}) == {
        "APP"
    }
    # exactly 2 bad → keep
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.9]}) == set()


def test_integrity_pin_reproduces_overlapping_counts() -> None:
    prior = [
        {"symbol": "APP", "date": "2025-11-25", "n_events": 10, "n_quotes": 4, "n_trades": 6},
        {"symbol": "RMBS", "date": "2025-11-25", "n_events": 8, "n_quotes": 3, "n_trades": 5},
    ]
    cells = [
        {"symbol": "APP", "date": "2025-11-25", "n_events": 10, "n_quotes": 4, "n_trades": 6},
        {"symbol": "OLN", "date": "2025-11-25", "n_events": 99, "n_quotes": 1, "n_trades": 1},
    ]
    assert integrity_pin_check(cells, prior) == []
    cells[0]["n_trades"] = 7
    mism = integrity_pin_check(cells, prior)
    assert len(mism) == 1 and "n_trades" in mism[0]
