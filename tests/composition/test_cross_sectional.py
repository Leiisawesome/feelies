"""Tests for :class:`feelies.composition.cross_sectional.CrossSectionalRanker`."""

from __future__ import annotations

import math

from feelies.composition.cross_sectional import CrossSectionalRanker, cap_family_vectors
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


def _make_ctx(signals: dict[str, Signal | None], *, ts_ns: int = 2_000) -> CrossSectionalContext:
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
    ctx = _make_ctx(
        {
            "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG, edge_bps=10),
            "MSFT": _make_signal(symbol="MSFT", direction=SignalDirection.LONG, edge_bps=5),
            "TSLA": _make_signal(symbol="TSLA", direction=SignalDirection.SHORT, edge_bps=10),
        }
    )
    result = ranker.rank(ctx)
    assert sum(result.weights.values()) == 0.0 or math.isclose(
        sum(result.weights.values()),
        0.0,
        abs_tol=1e-9,
    )


def test_none_signal_yields_zero_weight():
    ranker = CrossSectionalRanker()
    ctx = _make_ctx(
        {
            "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG),
            "MSFT": None,
        }
    )
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
        {"AAPL": sig_old, "MSFT": sig_fresh},
        ts_ns=61_000_000_000,
    )
    result = ranker.rank(ctx)
    assert math.isclose(result.decay_factors["AAPL"], math.exp(-1.0))
    assert math.isclose(result.decay_factors["MSFT"], 1.0)


def test_decay_override_disables_decay_for_one_call():
    # A per-call opt-out must not inherit another alpha's decay setting.
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    sig_old = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        ts_ns=1_000_000_000,
        half_life=60,
    )
    ctx = _make_ctx({"AAPL": sig_old, "MSFT": None}, ts_ns=61_000_000_000)

    on = ranker.rank(ctx)
    off = ranker.rank(ctx, decay_weighting_enabled=False)
    assert math.isclose(on.decay_factors["AAPL"], math.exp(-1.0))
    assert math.isclose(off.decay_factors["AAPL"], 1.0)


def test_decay_override_enables_decay_when_instance_off():
    ranker = CrossSectionalRanker(decay_weighting_enabled=False)
    sig_old = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        ts_ns=1_000_000_000,
        half_life=60,
    )
    ctx = _make_ctx({"AAPL": sig_old, "MSFT": None}, ts_ns=61_000_000_000)

    default = ranker.rank(ctx)
    forced_on = ranker.rank(ctx, decay_weighting_enabled=True)
    assert math.isclose(default.decay_factors["AAPL"], 1.0)
    assert math.isclose(forced_on.decay_factors["AAPL"], math.exp(-1.0))


def test_decay_override_none_uses_instance_flag():
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    sig_old = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        ts_ns=1_000_000_000,
        half_life=60,
    )
    ctx = _make_ctx({"AAPL": sig_old, "MSFT": None}, ts_ns=61_000_000_000)
    assert math.isclose(
        ranker.rank(ctx, decay_weighting_enabled=None).decay_factors["AAPL"],
        math.exp(-1.0),
    )


def test_liquidity_stress_is_exit_only():
    ranker = CrossSectionalRanker()
    sig = _make_signal(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        edge_bps=10.0,
        mech=TrendMechanism.LIQUIDITY_STRESS,
    )
    ctx = _make_ctx(
        {
            "AAPL": sig,
            "MSFT": _make_signal(
                symbol="MSFT",
                direction=SignalDirection.LONG,
                edge_bps=10.0,
            ),
        }
    )
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


# ── Simultaneous mechanism-cap convergence ──────────────────────────────
#
# Rescaling one family changes the others' shares, so multi-family breaches
# require iterative convergence.


def test_cap_family_vectors_converges_for_simultaneous_multi_family_breach():
    """4 families, caps at the G16 rule-8 minimum (sum == 1.0 exactly).

    Raw per-family gross (0.35/0.30/0.30/0.05) puts three families
    simultaneously over a shared 0.25 cap -- the regime the old 5-iteration
    budget could not resolve.
    """
    fams = (
        TrendMechanism.KYLE_INFO,
        TrendMechanism.INVENTORY,
        TrendMechanism.HAWKES_SELF_EXCITE,
        TrendMechanism.SCHEDULED_FLOW,
    )
    vectors = {
        fams[0]: {"A": 0.35},
        fams[1]: {"B": 0.30},
        fams[2]: {"C": 0.30},
        fams[3]: {"D": 0.05},
    }
    caps = {f: 0.25 for f in fams}

    _scaled, breakdown = cap_family_vectors(vectors, (caps, 1.0))

    assert breakdown, "expected a non-empty realised breakdown"
    for mech, share in breakdown.items():
        assert share <= caps[mech] + 1e-9, (
            f"{mech.name} share {share} exceeds its cap {caps[mech]} — "
            "multi-family cap convergence regressed"
        )
    assert math.isclose(sum(breakdown.values()), 1.0, abs_tol=1e-9)


def test_apply_mechanism_cap_converges_for_simultaneous_multi_family_breach():
    """Same scenario through the legacy single-signal-per-symbol cap path
    (``CrossSectionalRanker._apply_mechanism_cap``, reached via ``rank()``
    for any future alpha that calls the ranker directly)."""
    ranker = CrossSectionalRanker()
    fams = (
        TrendMechanism.KYLE_INFO,
        TrendMechanism.INVENTORY,
        TrendMechanism.HAWKES_SELF_EXCITE,
        TrendMechanism.SCHEDULED_FLOW,
    )
    weights = {"A": 0.35, "B": 0.30, "C": 0.30, "D": 0.05}
    mechanism_by_symbol = {"A": fams[0], "B": fams[1], "C": fams[2], "D": fams[3]}
    caps = {f: 0.25 for f in fams}

    _scaled, breakdown = ranker._apply_mechanism_cap(  # noqa: SLF001 -- exercising the fix directly
        weights, mechanism_by_symbol, (caps, 1.0)
    )

    assert breakdown, "expected a non-empty realised breakdown"
    for mech, share in breakdown.items():
        assert share <= caps[mech] + 1e-9, (
            f"{mech.name} share {share} exceeds its cap {caps[mech]} — "
            "multi-family cap convergence regressed"
        )


def test_deterministic_replay():
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    ctx = _make_ctx(
        {
            s: _make_signal(symbol=s, direction=SignalDirection.LONG, edge_bps=i + 1.0)
            for i, s in enumerate(("AAPL", "MSFT", "GOOG", "TSLA"))
        }
    )
    a = ranker.rank(ctx)
    b = ranker.rank(ctx)
    assert a.weights == b.weights
    assert a.raw_scores == b.raw_scores
