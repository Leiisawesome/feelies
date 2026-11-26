"""Uncalibrated regime posteriors size and scale at min(scales)."""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.module import AlphaRiskBudget
from feelies.bus.event_bus import EventBus
from feelies.core.events import RegimeState, Signal, SignalDirection
from feelies.core.position_sizer import BudgetBasedSizer
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.services.regime_engine import HMM3StateFractional
from feelies.services.regime_state_cache import RegimeStateCache

_NAMES = tuple(HMM3StateFractional().state_names)


def _cache(posteriors: tuple[float, ...], *, calibrated: bool) -> RegimeStateCache:
    cache = RegimeStateCache(bus=EventBus())
    dominant = max(range(len(posteriors)), key=lambda i: posteriors[i])
    cache.record(
        RegimeState(
            timestamp_ns=1,
            correlation_id="c",
            sequence=1,
            symbol="AAPL",
            engine_name="hmm_3state_fractional",
            state_names=_NAMES,
            posteriors=posteriors,
            dominant_state=dominant,
            dominant_name=_NAMES[dominant],
            calibrated=calibrated,
        )
    )
    return cache


def _signal() -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol="AAPL",
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=2.0,
    )


def _budget() -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=500,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=10.0,
    )


def test_sizer_uncalibrated_uses_min_scale() -> None:
    sizer = BudgetBasedSizer(regime_states=_cache((0.0, 1.0, 0.0), calibrated=False))
    qty = sizer.compute_target_quantity(
        _signal(),
        _budget(),
        symbol_price=Decimal("100"),
        account_equity=Decimal("100000"),
    )
    assert qty == 50
    assert sizer._get_regime_factor("AAPL") == sizer._regime_factor_default


def test_sizer_calibrated_posterior_is_unchanged() -> None:
    sizer = BudgetBasedSizer(regime_states=_cache((0.0, 1.0, 0.0), calibrated=True))
    qty = sizer.compute_target_quantity(
        _signal(),
        _budget(),
        symbol_price=Decimal("100"),
        account_equity=Decimal("100000"),
    )
    assert qty == 100
    assert sizer._get_regime_factor("AAPL") == 1.0


def test_risk_uncalibrated_uses_min_scale() -> None:
    engine = BasicRiskEngine(
        RiskConfig(max_position_per_symbol=1000, account_equity=Decimal("100000")),
        regime_states=_cache((0.0, 1.0, 0.0), calibrated=False),
    )
    assert engine._regime_scaling("AAPL") == engine._regime_scale_default


def test_risk_calibrated_posterior_is_unchanged() -> None:
    engine = BasicRiskEngine(
        RiskConfig(max_position_per_symbol=1000, account_equity=Decimal("100000")),
        regime_states=_cache((0.0, 1.0, 0.0), calibrated=True),
    )
    assert engine._regime_scaling("AAPL") == 1.0
