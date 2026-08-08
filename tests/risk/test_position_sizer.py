"""Tests for BudgetBasedSizer — position sizing with regime awareness."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaRiskBudget
from feelies.bus.event_bus import EventBus
from feelies.core.events import RegimeState, Signal, SignalDirection
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_state_cache import RegimeStateCache
from feelies.services.regime_engine import HMM3StateFractional


def _regime_states(
    posteriors: tuple[float, ...] | None,
    *,
    symbol: str = "AAPL",
) -> RegimeStateCache:
    """A cache holding one published ``RegimeState``, or nothing.

    Risk reads the published snapshot rather than the live engine, so tests feed
    it the same way the orchestrator does — by recording the event.  ``None``
    posteriors leaves the cache empty, which is how a cold start or an
    unannounced symbol looks to the consumer.
    """
    cache = RegimeStateCache(bus=EventBus())
    if posteriors is None:
        return cache
    names = tuple(HMM3StateFractional().state_names)
    dominant = max(range(len(posteriors)), key=lambda i: posteriors[i])
    cache.record(
        RegimeState(
            timestamp_ns=1,
            correlation_id="c",
            sequence=1,
            symbol=symbol,
            engine_name="hmm_3state_fractional",
            state_names=names,
            posteriors=tuple(posteriors),
            dominant_state=dominant,
            dominant_name=names[dominant],
        )
    )
    return cache


def _make_signal(
    symbol: str = "AAPL",
    strength: float = 1.0,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=strength,
        edge_estimate_bps=2.0,
    )


@pytest.fixture
def budget() -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=500,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=10.0,
    )


class TestBudgetAllocation:
    def test_basic_allocation(self, budget: AlphaRiskBudget) -> None:
        """equity=100k, alloc=10%, strength=1.0, price=$100 → 100 shares."""
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # 100000 * 10% = 10000 / 100 = 100
        assert qty == 100


class TestConvictionScaling:
    def test_half_strength_halves_quantity(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        full = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        half = sizer.compute_target_quantity(
            _make_signal(strength=0.5),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        assert half == full // 2


class TestRegimeFactor:
    def test_vol_breakout_halves_size(self, budget: AlphaRiskBudget) -> None:

        # No posterior published for this symbol.
        sizer = BudgetBasedSizer(regime_states=_regime_states(None))
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # EV = 1.0*0.5 = 0.5, so 10000 * 0.5 / 100 = 50
        assert qty == 50

    def test_factor_clamped_at_one_when_config_supplies_amplifier(
        self, budget: AlphaRiskBudget
    ) -> None:
        """Regime state must never amplify exposure
        beyond 1.0) is enforced at the value level — an operator-
        supplied factor > 1.0 must NOT increase quantity above the
        un-scaled baseline."""

        # Misconfigured map: "normal" -> 2.0×.  EV would be 2.0; clamp
        # caps it at 1.0.
        sizer = BudgetBasedSizer(
            regime_states=_regime_states((0.0, 1.0, 0.0)),  # 100% "normal"
            regime_factors={"normal": 2.0, "vol_breakout": 0.5, "compression_clustering": 0.75},
        )
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # Without the clamp this would be 200; with the clamp it's 100.
        # 100000 * 10% (capital_allocation_pct) = 10000; 10000 * 1.0 / 100 = 100.
        assert qty == 100

    def test_nan_posterior_fails_safe_to_min_factor_not_baseline(
        self, budget: AlphaRiskBudget
    ) -> None:
        """Missing regime data tightens sizing fail-safe.

        Mirrors ``test_basic_risk.py``'s
        ``test_nan_posterior_fails_safe_to_min_scale_not_baseline``: a
        NaN EV must fail to the minimum configured factor, not to ``1.0``
        (which is what ``min(1.0, float("nan"))`` evaluates to).
        """
        sizer = BudgetBasedSizer(regime_states=_regime_states((float("nan"), 0.0, 0.0)))
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # min(vol_breakout=0.5, compression_clustering=0.75, normal=1.0) = 0.5
        # 100000 * 10% = 10000; 10000 * 0.5 / 100 = 50.
        assert qty == 50


class TestEdgeCases:
    def test_zero_price_returns_zero(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(),
            budget,
            symbol_price=Decimal("0"),
            account_equity=Decimal("100000"),
        )
        assert qty == 0

    def test_zero_equity_returns_zero(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("0"),
        )
        assert qty == 0

    def test_cap_at_max_position(self) -> None:
        small_cap_budget = AlphaRiskBudget(
            max_position_per_symbol=10,
            max_gross_exposure_pct=100.0,
            max_drawdown_pct=50.0,
            capital_allocation_pct=100.0,
        )
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            small_cap_budget,
            symbol_price=Decimal("1"),
            account_equity=Decimal("1000000"),
        )
        assert qty == 10

    def test_no_regime_engine_factor_is_one(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer(regime_states=None)
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # factor 1.0: 100000 * 10% = 10000 / 100 = 100
        assert qty == 100


class TestStrengthClamp:
    """Conviction is clamped to [0, 1] so strength above 1.0
    cannot size above the alpha's allocated capital."""

    def test_strength_above_one_is_clamped(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        clamped = sizer.compute_target_quantity(
            _make_signal(strength=5.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        full = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # strength 5.0 must not exceed the full-conviction (strength 1.0) size.
        assert clamped == full == 100


class TestRegimeMissingDataFailsSafe:
    """A configured engine with no posterior for the symbol
    tightens quantity to min(factors), not the 1.0 baseline."""

    def test_missing_posterior_uses_min_factor(self, budget: AlphaRiskBudget) -> None:
        # No posterior published for this symbol.
        sizer = BudgetBasedSizer(regime_states=_regime_states(None))
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # min factor = 0.5: 100000 * 10% = 10000 * 0.5 / 100 = 50
        assert qty == 50
