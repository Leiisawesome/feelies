"""Tests for :class:`feelies.composition.cross_sectional.CrossSectionalRanker`."""

from __future__ import annotations

import math

from feelies.composition.cross_sectional import (
    CrossSectionalRanker,
    SleeveRankResult,
    cap_family_vectors,
)
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


def _combined_weights(result: SleeveRankResult) -> dict[str, float]:
    """Per-symbol weight summed across every mechanism sleeve.

    ``rank_sleeves`` standardizes each family separately; the engine recombines
    the sleeves into one book. These tests assert on that combined view, which
    is what downstream construction actually consumes.
    """
    combined: dict[str, float] = {}
    for vector in result.weights_by_mech.values():
        for symbol, weight in vector.items():
            combined[symbol] = combined.get(symbol, 0.0) + weight
    return combined


def test_zscore_centers_to_zero_and_clips():
    ranker = CrossSectionalRanker(clip=4.0)
    ctx = _make_ctx(
        {
            "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG, edge_bps=10),
            "MSFT": _make_signal(symbol="MSFT", direction=SignalDirection.LONG, edge_bps=5),
            "TSLA": _make_signal(symbol="TSLA", direction=SignalDirection.SHORT, edge_bps=10),
        }
    )
    weights = _combined_weights(ranker.rank_sleeves(ctx))
    assert math.isclose(sum(weights.values()), 0.0, abs_tol=1e-9)


def test_none_signal_yields_zero_weight():
    """A symbol with no signal holds (weight 0) without biasing the moments.

    Three symbols so the surviving cross-section is non-degenerate: with only
    one active name ``_standardize`` returns zeros for everyone (std == 0) and
    the assertion would pass without testing the active-set carve-out at all.
    """
    ranker = CrossSectionalRanker()
    ctx = _make_ctx(
        {
            "AAPL": _make_signal(symbol="AAPL", direction=SignalDirection.LONG, edge_bps=10),
            "MSFT": None,
            "TSLA": _make_signal(symbol="TSLA", direction=SignalDirection.SHORT, edge_bps=10),
        }
    )
    weights = _combined_weights(ranker.rank_sleeves(ctx))
    assert weights["MSFT"] == 0.0
    assert weights["AAPL"] != 0.0
    assert weights["TSLA"] != 0.0


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
    result = ranker.rank_sleeves(ctx)
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

    on = ranker.rank_sleeves(ctx)
    off = ranker.rank_sleeves(ctx, decay_weighting_enabled=False)
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

    default = ranker.rank_sleeves(ctx)
    forced_on = ranker.rank_sleeves(ctx, decay_weighting_enabled=True)
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
        ranker.rank_sleeves(ctx, decay_weighting_enabled=None).decay_factors["AAPL"],
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
    result = ranker.rank_sleeves(ctx)
    assert result.raw_scores["AAPL"] == 0.0
    # Every sleeve seeds the whole universe at 0.0, so membership proves nothing.
    # ``decay_factors == 0.0`` is the marker that no contribution was gathered at
    # all — a gathered-then-zeroed signal would carry a decay of 1.0 and would
    # have joined the sleeve's standardization moments.
    assert result.decay_factors["AAPL"] == 0.0
    assert "AAPL" not in result.mechanism_by_symbol
    assert all(vector["AAPL"] == 0.0 for vector in result.weights_by_mech.values())


def test_resolve_caps_takes_the_tighter_of_family_and_global():
    """``min(per_family, global)`` — neither declaration may be exceeded.

    The ranker no longer scales weights itself; it only resolves the caps the
    engine then enforces via ``cap_family_vectors``. This pins the resolution.
    """
    ranker = CrossSectionalRanker(mechanism_max_share_of_gross=0.5)

    per_family, default_cap = ranker.resolve_caps(
        {TrendMechanism.KYLE_INFO: 0.8, TrendMechanism.INVENTORY: 0.2},
        None,
    )
    assert default_cap == 0.5
    # The looser family declaration is clamped to the global; the tighter stands.
    assert per_family[TrendMechanism.KYLE_INFO] == 0.5
    assert per_family[TrendMechanism.INVENTORY] == 0.2

    # An explicit global overrides the instance default for both.
    per_family, default_cap = ranker.resolve_caps({TrendMechanism.KYLE_INFO: 0.8}, 0.3)
    assert default_cap == 0.3
    assert per_family[TrendMechanism.KYLE_INFO] == 0.3


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


def test_deterministic_replay():
    ranker = CrossSectionalRanker(decay_weighting_enabled=True)
    ctx = _make_ctx(
        {
            s: _make_signal(symbol=s, direction=SignalDirection.LONG, edge_bps=i + 1.0)
            for i, s in enumerate(("AAPL", "MSFT", "GOOG", "TSLA"))
        }
    )
    a = ranker.rank_sleeves(ctx)
    b = ranker.rank_sleeves(ctx)
    assert a.weights_by_mech == b.weights_by_mech
    assert a.raw_scores == b.raw_scores
    assert a.decay_factors == b.decay_factors
