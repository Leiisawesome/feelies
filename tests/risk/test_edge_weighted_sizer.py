"""Tests for the G-7 EdgeWeightedSizer — edge / vol / inventory tilts.

The load-bearing test is parity: with the default (all-off) config the
wrapper must reproduce its base sizer byte-for-byte over a grid of inputs.
Each factor is then exercised in isolation, plus the combined-tilt and
re-cap behaviour.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import Signal, SignalDirection
from feelies.risk.edge_weighted_sizer import (
    EdgeWeightedSizer,
    SizerTiltConfig,
    edge_factor,
    inventory_factor,
    vol_factor,
)
from feelies.risk.position_sizer import BudgetBasedSizer


def _signal(
    symbol: str = "AAPL",
    strength: float = 1.0,
    edge_bps: float = 20.0,
    direction: SignalDirection = SignalDirection.LONG,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        strategy_id="test_alpha",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )


@pytest.fixture
def budget() -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=500,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=10.0,
    )


# ── Factor functions (pure) ──────────────────────────────────────────────


class TestEdgeFactor:
    def test_edge_equal_ref_is_unity(self) -> None:
        assert edge_factor(20.0, ref_bps=20.0, floor=0.25, cap=2.0) == 1.0

    def test_higher_edge_amplifies(self) -> None:
        assert edge_factor(40.0, ref_bps=20.0, floor=0.25, cap=2.0) == 2.0

    def test_lower_edge_shrinks(self) -> None:
        assert edge_factor(10.0, ref_bps=20.0, floor=0.25, cap=2.0) == 0.5

    def test_clamped_at_cap_and_floor(self) -> None:
        assert edge_factor(1000.0, ref_bps=20.0, floor=0.25, cap=2.0) == 2.0
        assert edge_factor(0.0, ref_bps=20.0, floor=0.25, cap=2.0) == 0.25

    def test_nonpositive_ref_is_noop(self) -> None:
        assert edge_factor(40.0, ref_bps=0.0, floor=0.25, cap=2.0) == 1.0


class TestVolFactor:
    def test_realized_equal_target_is_unity(self) -> None:
        assert vol_factor(100.0, target_vol_bps=100.0, floor=0.25, cap=2.0) == 1.0

    def test_high_vol_shrinks(self) -> None:
        assert vol_factor(200.0, target_vol_bps=100.0, floor=0.25, cap=2.0) == 0.5

    def test_low_vol_grows_clamped(self) -> None:
        assert vol_factor(10.0, target_vol_bps=100.0, floor=0.25, cap=2.0) == 2.0

    def test_missing_or_nonpositive_is_noop(self) -> None:
        assert vol_factor(None, target_vol_bps=100.0, floor=0.25, cap=2.0) == 1.0
        assert vol_factor(0.0, target_vol_bps=100.0, floor=0.25, cap=2.0) == 1.0


class TestInventoryFactor:
    def test_flat_book_is_unity(self) -> None:
        assert inventory_factor(0, 500, floor=0.0) == 1.0

    def test_half_full_halves(self) -> None:
        assert inventory_factor(250, 500, floor=0.0) == 0.5

    def test_at_cap_floors(self) -> None:
        assert inventory_factor(500, 500, floor=0.1) == 0.1

    def test_sign_agnostic(self) -> None:
        assert inventory_factor(-250, 500, floor=0.0) == 0.5

    def test_nonpositive_cap_is_noop(self) -> None:
        assert inventory_factor(100, 0, floor=0.0) == 1.0


# ── Parity: default config == base sizer ─────────────────────────────────


class TestParity:
    @pytest.mark.parametrize("strength", [0.0, 0.25, 0.5, 0.75, 1.0])
    @pytest.mark.parametrize("price", ["10", "100", "137.5", "1000"])
    @pytest.mark.parametrize("edge", [0.5, 2.0, 20.0, 80.0])
    def test_all_off_matches_base(
        self, budget: AlphaRiskBudget, strength: float, price: str, edge: float
    ) -> None:
        base = BudgetBasedSizer()
        wrapped = EdgeWeightedSizer(base)  # default = all-off
        sig = _signal(strength=strength, edge_bps=edge)
        equity = Decimal("100000")
        assert wrapped.compute_target_quantity(
            sig, budget, Decimal(price), equity
        ) == base.compute_target_quantity(sig, budget, Decimal(price), equity)

    def test_default_tilt_is_unity(self, budget: AlphaRiskBudget) -> None:
        wrapped = EdgeWeightedSizer(BudgetBasedSizer())
        assert wrapped.tilt_for(_signal(), budget) == 1.0
        assert wrapped.config.any_enabled is False


# ── Tilt behaviour when enabled ──────────────────────────────────────────


class TestEdgeTilt:
    def test_high_edge_upsizes(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(edge_enabled=True, edge_ref_bps=20.0, edge_cap=2.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        # base = 100; edge 40 vs ref 20 → 2.0× → 200.
        qty = wrapped.compute_target_quantity(
            _signal(edge_bps=40.0), budget, Decimal("100"), Decimal("100000")
        )
        assert qty == 200

    def test_low_edge_downsizes(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(edge_enabled=True, edge_ref_bps=20.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        qty = wrapped.compute_target_quantity(
            _signal(edge_bps=10.0), budget, Decimal("100"), Decimal("100000")
        )
        assert qty == 50  # base 100 × 0.5


class TestVolTilt:
    def test_uses_provider(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(vol_enabled=True, vol_target_bps=100.0)
        wrapped = EdgeWeightedSizer(
            BudgetBasedSizer(), cfg, realized_vol_provider=lambda _s: 200.0
        )
        qty = wrapped.compute_target_quantity(_signal(), budget, Decimal("100"), Decimal("100000"))
        assert qty == 50  # 100 × (100/200)

    def test_absent_provider_is_noop(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(vol_enabled=True)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)  # no provider
        qty = wrapped.compute_target_quantity(_signal(), budget, Decimal("100"), Decimal("100000"))
        assert qty == 100


class TestInventoryTilt:
    def test_taper_with_inventory(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(inventory_enabled=True)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg, inventory_provider=lambda _s: 250)
        # base 100, inventory 250/500 → factor 0.5 → 50.
        qty = wrapped.compute_target_quantity(_signal(), budget, Decimal("100"), Decimal("100000"))
        assert qty == 50


class TestExitGate:
    """The tilt is entry economics: FLAT exits and zero-edge signals must
    pass through at the base size — never floored/shrunk."""

    def test_flat_exit_not_tilted(self, budget: AlphaRiskBudget) -> None:
        # Edge + inventory both on, a near-full book — a directional add here
        # would shrink hard, but a FLAT exit must stay at base size.
        cfg = SizerTiltConfig(
            edge_enabled=True,
            edge_ref_bps=20.0,
            inventory_enabled=True,
        )
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg, inventory_provider=lambda _s: 400)
        flat = _signal(edge_bps=0.0, direction=SignalDirection.FLAT)
        assert wrapped.tilt_for(flat, budget) == 1.0
        qty = wrapped.compute_target_quantity(flat, budget, Decimal("100"), Decimal("100000"))
        assert qty == 100  # base, untouched

    def test_zero_edge_directional_not_edge_floored(self, budget: AlphaRiskBudget) -> None:
        # A LONG with no disclosed edge: the edge factor is a no-op (1.0),
        # not floored to 0.25.  (Inventory off here to isolate it.)
        cfg = SizerTiltConfig(edge_enabled=True, edge_ref_bps=20.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        bd = wrapped.tilt_breakdown(_signal(edge_bps=0.0), budget)
        assert bd.edge == 1.0
        assert bd.combined == 1.0

    def test_positive_edge_still_tilts(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(edge_enabled=True, edge_ref_bps=20.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        assert wrapped.tilt_for(_signal(edge_bps=40.0), budget) == 2.0


class TestCombinedAndCap:
    def test_recapped_at_budget(self, budget: AlphaRiskBudget) -> None:
        # base 100, edge 80 vs ref 20 → clamps at cap 2.0 → 200, under cap 500.
        cfg = SizerTiltConfig(edge_enabled=True, edge_ref_bps=20.0, edge_cap=2.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        budget_small = AlphaRiskBudget(
            max_position_per_symbol=150,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=2.0,
            capital_allocation_pct=10.0,
        )
        qty = wrapped.compute_target_quantity(
            _signal(edge_bps=80.0), budget_small, Decimal("100"), Decimal("100000")
        )
        assert qty == 150  # tilt wants 200, capped at budget 150

    def test_combined_tilt_clamped(self, budget: AlphaRiskBudget) -> None:
        # edge 2.0 × vol 2.0 = 4.0, clamped to tilt_cap 3.0.
        cfg = SizerTiltConfig(
            edge_enabled=True,
            edge_cap=2.0,
            vol_enabled=True,
            vol_cap=2.0,
            tilt_cap=3.0,
        )
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg, realized_vol_provider=lambda _s: 10.0)
        assert wrapped.tilt_for(_signal(edge_bps=80.0), budget) == 3.0

    def test_zero_base_short_circuits(self, budget: AlphaRiskBudget) -> None:
        cfg = SizerTiltConfig(edge_enabled=True, edge_cap=2.0)
        wrapped = EdgeWeightedSizer(BudgetBasedSizer(), cfg)
        # strength 0 → base 0 → stays 0 regardless of tilt.
        qty = wrapped.compute_target_quantity(
            _signal(strength=0.0, edge_bps=80.0),
            budget,
            Decimal("100"),
            Decimal("100000"),
        )
        assert qty == 0
