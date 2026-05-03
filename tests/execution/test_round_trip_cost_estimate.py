"""Tests for :func:`feelies.execution.cost_model.estimate_round_trip_cost_bps`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
    ZeroCostModel,
    estimate_round_trip_cost_bps,
)


def test_zero_model_returns_zero_round_trip() -> None:
    model = ZeroCostModel()
    rt = estimate_round_trip_cost_bps(
        model,
        symbol="AAPL",
        entry_side=Side.BUY,
        quantity=100,
        mid_price=Decimal("100"),
        half_spread=Decimal("0.02"),
        is_taker=True,
        is_short_entry=False,
    )
    assert rt == 0.0


def test_short_entry_htb_increases_round_trip_vs_flat_short_flag() -> None:
    cfg = DefaultCostModelConfig(htb_borrow_annual_bps=Decimal("252000"))
    model = DefaultCostModel(cfg)
    common = dict(
        symbol="AAPL",
        quantity=100,
        mid_price=Decimal("100"),
        half_spread=Decimal("0.02"),
        is_taker=True,
    )
    with_htb = estimate_round_trip_cost_bps(
        model,
        entry_side=Side.SELL,
        is_short_entry=True,
        **common,
    )
    flat_short = estimate_round_trip_cost_bps(
        model,
        entry_side=Side.SELL,
        is_short_entry=False,
        **common,
    )
    assert with_htb > flat_short


def test_sell_side_regulatory_applies_on_exit_leg_for_long_round_trip() -> None:
    cfg = DefaultCostModelConfig(sell_regulatory_bps=Decimal("30"))
    model = DefaultCostModel(cfg)
    common = dict(
        symbol="AAPL",
        quantity=100,
        mid_price=Decimal("100"),
        half_spread=Decimal("0.02"),
        is_taker=True,
        is_short_entry=False,
    )
    rt = estimate_round_trip_cost_bps(
        model,
        entry_side=Side.BUY,
        **common,
    )
    entry_only = float(
        model.compute(
            "AAPL",
            Side.BUY,
            100,
            Decimal("100"),
            Decimal("0.02"),
            is_taker=True,
            is_short=False,
        ).cost_bps
    )
    assert rt > entry_only * 2
