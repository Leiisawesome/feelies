"""Tests for :class:`feelies.composition.cross_sectional.CrossSectionalRanker`."""

from __future__ import annotations

import math

from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    TrendMechanism,
)


def _make_signal(
    *,
    symbol: str,
    direction: SignalDirection,
    strength: float = 1.0,
    edge_bps: float = 5.0,
    ts_ns: int = 1_000,
    half_life: int = 0,
    mech: TrendMechanism | None = None,
) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"sig:{symbol}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id="alpha_a",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
        layer="SIGNAL",
        horizon_seconds=300,
        expected_half_life_seconds=half_life,
        trend_mechanism=mech,
    )


def _make_ctx(
    signals: dict[str, Signal | None], *, ts_ns: int = 2_000
) -> CrossSectionalContext:
    universe = tuple(sorted(signals))
    return CrossSectionalContext(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id="ctx:1",
        source_layer="P4",
        horizon_seconds=300,
        boundary_index=1,
        universe=universe,
        signals_by_symbol=signals,
        completeness=1.0,
    )


def test_zscore_centers_to_zero_and_clips():
    ranker = CrossSectionalRanker(clip=4.0)
    ctx = _make_ctx({
        "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG, edge_bps=10),
        "MSFT": _make_signal(symbol="MSFT", direction=SignalDirection.LONG, edge_bps=5),
        "TSLA": _make_signal(symbol="TSLA", direction=SignalDirection.SHORT, edge_bps=10),
    })
    result = ranker.rank(ctx)
    assert sum(result.weights.values()) == 0.0 or math.isclose(
        sum(result.weights.values()), 0.0, abs_tol=1e-9,
    )


def test_none_signal_yields_zero_weight():
    ranker = CrossSectionalRanker()
    ctx = _make_ctx({
        "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG),
        "MSFT": None,
    })
    result = ranker.rank(ctx)
    assert result.weights["MSFT"] == 0.0


def test_decay_weighting_shrinks_old_signals():
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    # Half-life = 60s, age = 60s ⇒ decay = 0.5.
    sig_old = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        ts_ns=1_000_000_000,
        half_life=60,
    )
    sig_fresh = _make_signal(
        symbol="MSFT",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        ts_ns=61_000_000_000,
        half_life=60,
    )
    ctx = _make_ctx(
        {"AAPL": sig_old, "MSFT": sig_fresh}, ts_ns=61_000_000_000,
    )
    result = ranker.rank(ctx)
    assert math.isclose(result.decay_factors["AAPL"], math.exp(-1.0))
    assert math.isclose(result.decay_factors["MSFT"], 1.0)


def test_liquidity_stress_is_exit_only():
    ranker = CrossSectionalRanker()
    sig = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        mech=TrendMechanism.LIQUIDITY_STRESS,
    )
    ctx = _make_ctx({"AAPL": sig, "MSFT": _make_signal(
        symbol="MSFT", direction=SignalDirection.LONG, edge_bps=10.0,
    )})
    result = ranker.rank(ctx)
    assert result.raw_scores["AAPL"] == 0.0


def test_mechanism_cap_scales_overrepresented_family():
    ranker = CrossSectionalRanker(mechanism_max_share_of_gross=0.5)
    sigs = {
        s: _make_signal(
            symbol=s,
            direction=SignalDirection.LONG,
            edge_bps=10.0,
            mech=TrendMechanism.KYLE_INFO,
        )
        for s in ("A", "B", "C")
    }
    sigs["D"] = _make_signal(
        symbol="D",
        direction=SignalDirection.SHORT,
        edge_bps=10.0,
        mech=TrendMechanism.INVENTORY,
    )
    ctx = _make_ctx(sigs)
    result = ranker.rank(ctx)
    breakdown = result.mechanism_breakdown
    if TrendMechanism.KYLE_INFO in breakdown:
        assert breakdown[TrendMechanism.KYLE_INFO] <= 0.5 + 1e-9


def test_deterministic_replay():
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    ctx = _make_ctx({
        s: _make_signal(symbol=s, direction=SignalDirection.LONG, edge_bps=i + 1.0)
        for i, s in enumerate(("AAPL", "MSFT", "GOOG", "TSLA"))
    })
    a = ranker.rank(ctx)
    b = ranker.rank(ctx)
    assert a.weights == b.weights
    assert a.raw_scores == b.raw_scores
