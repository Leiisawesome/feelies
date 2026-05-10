"""CrossSectionalRanker multi-feeder aggregation (portfolio fan-in)."""

from __future__ import annotations

import pytest

from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    TrendMechanism,
)


def test_rank_sums_feeder_marginal_raw_scores() -> None:
    ts = 5_000_000_000
    inv = Signal(
        timestamp_ns=ts - 50_000_000_000,
        sequence=1,
        correlation_id="inv",
        source_layer="SIGNAL",
        symbol="AAPL",
        strategy_id="pofi_inventory_revert_v1",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=3.0,
        layer="SIGNAL",
        horizon_seconds=30,
        trend_mechanism=TrendMechanism.INVENTORY,
        expected_half_life_seconds=20,
    )
    kyle = Signal(
        timestamp_ns=ts - 1_000_000_000,
        sequence=2,
        correlation_id="kyle",
        source_layer="SIGNAL",
        symbol="AAPL",
        strategy_id="pofi_kyle_drift_v1",
        direction=SignalDirection.SHORT,
        strength=0.5,
        edge_estimate_bps=10.0,
        layer="SIGNAL",
        horizon_seconds=300,
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    )
    ctx = CrossSectionalContext(
        timestamp_ns=ts,
        sequence=1,
        correlation_id="xsect:300:1",
        source_layer="P4",
        horizon_seconds=300,
        boundary_index=1,
        universe=("AAPL",),
        signals_by_symbol={"AAPL": kyle},
        signals_by_strategy_by_symbol={
            "AAPL": {
                "pofi_inventory_revert_v1": inv,
                "pofi_kyle_drift_v1": kyle,
            },
        },
        completeness=1.0,
    )
    ranker = CrossSectionalRanker(decay_weighting_enabled=False)
    result = ranker.rank(
        ctx,
        feeder_strategy_ids=(
            "pofi_inventory_revert_v1",
            "pofi_kyle_drift_v1",
        ),
    )
    # LONG: +3 ; SHORT: -0.5 * 10 = -5  → raw_total -2
    assert result.raw_scores["AAPL"] == pytest.approx(-2.0)


def test_multi_feeder_exit_only_mechanism_excluded_from_active() -> None:
    """Exit-only feeders must not join ``active`` or bias cross-sectional moments.

    Regression: ``found_signal`` was true whenever any feeder had a signal, so an
    all-``LIQUIDITY_STRESS`` symbol kept ``decay_factors==1.0`` and entered
    ``active`` with ``raw_total==0``, skewing mean/std for everyone else.
    """
    ts = 10_000_000_000
    stress = Signal(
        timestamp_ns=ts,
        sequence=1,
        correlation_id="stress",
        source_layer="SIGNAL",
        symbol="AAPL",
        strategy_id="stress_alpha",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=10.0,
        layer="SIGNAL",
        horizon_seconds=300,
        trend_mechanism=TrendMechanism.LIQUIDITY_STRESS,
        expected_half_life_seconds=120,
    )
    def _kyle_signal(sym: str, sid: str, raw: float) -> Signal:
        return Signal(
            timestamp_ns=ts,
            sequence=2,
            correlation_id=sid,
            source_layer="SIGNAL",
            symbol=sym,
            strategy_id=sid,
            direction=(
                SignalDirection.LONG if raw > 0 else SignalDirection.SHORT
            ),
            strength=1.0,
            edge_estimate_bps=abs(raw),
            layer="SIGNAL",
            horizon_seconds=300,
            trend_mechanism=TrendMechanism.KYLE_INFO,
            expected_half_life_seconds=600,
        )
    ctx = CrossSectionalContext(
        timestamp_ns=ts,
        sequence=1,
        correlation_id="xsect:300:2",
        source_layer="P4",
        horizon_seconds=300,
        boundary_index=2,
        universe=("AAPL", "GOOG", "MSFT"),
        signals_by_symbol={
            "AAPL": stress,
            "GOOG": _kyle_signal("GOOG", "kyle_g", -10.0),
            "MSFT": _kyle_signal("MSFT", "kyle_m", 10.0),
        },
        signals_by_strategy_by_symbol={
            "AAPL": {"stress_alpha": stress},
            "GOOG": {"kyle_g": _kyle_signal("GOOG", "kyle_g", -10.0)},
            "MSFT": {"kyle_m": _kyle_signal("MSFT", "kyle_m", 10.0)},
        },
        completeness=1.0,
    )
    ranker = CrossSectionalRanker(decay_weighting_enabled=False, clip=4.0)
    result = ranker.rank(
        ctx,
        feeder_strategy_ids=("stress_alpha", "kyle_g", "kyle_m"),
    )
    assert result.decay_factors["AAPL"] == 0.0
    assert result.raw_scores["AAPL"] == 0.0
    assert result.weights["AAPL"] == 0.0
    assert result.mechanism_by_symbol["AAPL"] == TrendMechanism.LIQUIDITY_STRESS
    assert result.weights["GOOG"] == pytest.approx(-1.0)
    assert result.weights["MSFT"] == pytest.approx(1.0)
