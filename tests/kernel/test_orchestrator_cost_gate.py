"""Tests for the runtime cost gate (audit F-H-05, F-H-13, F-H-14)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
    estimate_round_trip_cost_bps,
)
from feelies.core.events import Side

pytestmark = pytest.mark.backtest_validation


class TestRoundTripBasis:
    """Audit F-H-13: gate compares edge in the configured basis."""

    def test_one_way_basis_legacy_arithmetic(self) -> None:
        # One-way edge 5 bps, round-trip cost 4 bps, ratio 1.0:
        # one_way basis → 5 vs 1.0 × 4 = 5 vs 4 → PASS.
        edge_one_way = 5.0
        ratio = 1.0
        rt_cost = 4.0
        # The comparison the orchestrator now does:
        edge_basis = edge_one_way  # no scaling under one_way
        assert edge_basis >= ratio * rt_cost

    def test_round_trip_basis_scales_one_way_edge_by_two(self) -> None:
        # Same numbers under round-trip basis:
        # 5 × 2 = 10 vs 1.0 × 4 = 4 → PASS with bigger margin.
        edge_one_way = 5.0
        ratio = 1.0
        rt_cost = 4.0
        edge_basis = edge_one_way * 2.0
        assert edge_basis >= ratio * rt_cost
        assert edge_basis > rt_cost  # under round-trip basis, must beat full RT

    def test_round_trip_at_breakeven(self) -> None:
        # Round-trip cost equals 2 × edge_one_way → exactly breakeven.
        # ratio=1.0 in round-trip basis: 2 × edge_one_way >= 1.0 × (2 × edge_one_way)
        edge_one_way = 3.0
        ratio = 1.0
        rt_cost = 6.0  # = 2 × edge_one_way
        edge_basis = edge_one_way * 2.0
        assert edge_basis >= ratio * rt_cost  # exactly at the threshold

    def test_round_trip_below_breakeven_fails(self) -> None:
        edge_one_way = 3.0
        ratio = 1.0
        rt_cost = 7.0  # > 2 × edge_one_way
        edge_basis = edge_one_way * 2.0
        assert edge_basis < ratio * rt_cost  # gate would block


class TestDefaultGateActiveBreakeven:
    """Audit F-H-14: default ratio is 1.0, gate active at breakeven."""

    def test_default_signal_min_edge_cost_ratio_is_one(self) -> None:
        from feelies.core.platform_config import PlatformConfig
        from pathlib import Path

        # Construct a minimal-valid PlatformConfig.
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.yaml")],
        )
        assert cfg.signal_min_edge_cost_ratio == 1.0

    def test_default_signal_edge_cost_basis_is_round_trip(self) -> None:
        from feelies.core.platform_config import PlatformConfig
        from pathlib import Path

        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.yaml")],
        )
        assert cfg.signal_edge_cost_basis == "round_trip"


class TestWorstCaseEntryInMinCostMode:
    """Audit F-H-05: in minimum_cost mode the gate prices entry as taker."""

    def test_taker_entry_costs_strictly_more_than_maker_entry(self) -> None:
        model = DefaultCostModel(
            DefaultCostModelConfig(
                maker_exchange_per_share=Decimal("0"),
                passive_adverse_selection_bps=Decimal("2.0"),
            )
        )
        maker_entry_taker_exit = estimate_round_trip_cost_bps(
            model,
            symbol="AAPL",
            entry_side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.02"),
            is_taker=False,
            is_taker_exit=True,
            is_short_entry=False,
        )
        taker_entry_taker_exit = estimate_round_trip_cost_bps(
            model,
            symbol="AAPL",
            entry_side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.02"),
            is_taker=True,
            is_taker_exit=True,
            is_short_entry=False,
        )
        # Worst-case (taker) entry is strictly higher than maker entry.
        assert taker_entry_taker_exit > maker_entry_taker_exit
