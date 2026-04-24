"""Phase-1.1 (v0.3) event-contract tests.

Covers the closed ``TrendMechanism`` enum, ``RegimeHazardSpike`` event,
the v0.3 additive fields on ``Signal``, and the ``mechanism_breakdown``
field on ``SizedPositionIntent`` per
``design_docs/three_layer_architecture.md`` §20.3.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from feelies.core.events import (
    RegimeHazardSpike,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TrendMechanism,
)


# ── TrendMechanism enum is closed at exactly 5 members (§20.2) ──────────


def test_trend_mechanism_has_exactly_five_members() -> None:
    assert len(list(TrendMechanism)) == 5


def test_trend_mechanism_member_names() -> None:
    """Mechanism names are normative — adding new ones is a platform change."""
    assert {m.name for m in TrendMechanism} == {
        "KYLE_INFO",
        "INVENTORY",
        "HAWKES_SELF_EXCITE",
        "LIQUIDITY_STRESS",
        "SCHEDULED_FLOW",
    }


def test_trend_mechanism_members_are_distinct() -> None:
    values = {m.value for m in TrendMechanism}
    assert len(values) == 5


# ── Signal v0.3 additive fields (§20.3.2) ───────────────────────────────


def test_signal_v03_defaults_match_v02_behavior() -> None:
    """A v0.2-shape Signal stays opaque: trend_mechanism=None, half_life=0."""
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=1.0,
    )
    assert sig.trend_mechanism is None
    assert sig.expected_half_life_seconds == 0


def test_signal_with_trend_mechanism() -> None:
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="hawkes_burst",
        direction=SignalDirection.LONG,
        strength=0.8,
        edge_estimate_bps=3.5,
        trend_mechanism=TrendMechanism.HAWKES_SELF_EXCITE,
        expected_half_life_seconds=45,
    )
    assert sig.trend_mechanism is TrendMechanism.HAWKES_SELF_EXCITE
    assert sig.expected_half_life_seconds == 45


def test_signal_v03_round_trip() -> None:
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="kyle_info",
        direction=SignalDirection.LONG,
        strength=0.6,
        edge_estimate_bps=2.0,
        layer="SIGNAL",
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=120,
    )
    copy = replace(sig)
    assert copy == sig
    assert copy.trend_mechanism is TrendMechanism.KYLE_INFO


# ── RegimeHazardSpike (§20.3.1) ─────────────────────────────────────────


def test_regime_hazard_spike_construction() -> None:
    spike = RegimeHazardSpike(
        timestamp_ns=10,
        correlation_id="c",
        sequence=5,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        departing_state="compression",
        departing_posterior_prev=0.85,
        departing_posterior_now=0.40,
        incoming_state="vol_breakout",
        hazard_score=0.72,
    )
    assert spike.departing_state == "compression"
    assert spike.incoming_state == "vol_breakout"
    assert spike.hazard_score == pytest.approx(0.72)


def test_regime_hazard_spike_ambiguous_incoming() -> None:
    """incoming_state is None when no clear successor is dominant."""
    spike = RegimeHazardSpike(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        departing_state="normal",
        departing_posterior_prev=0.7,
        departing_posterior_now=0.35,
        incoming_state=None,
        hazard_score=0.5,
    )
    assert spike.incoming_state is None


def test_regime_hazard_spike_is_frozen() -> None:
    spike = RegimeHazardSpike(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        engine_name="e",
        departing_state="a",
        departing_posterior_prev=0.9,
        departing_posterior_now=0.4,
        incoming_state="b",
        hazard_score=0.6,
    )
    with pytest.raises(FrozenInstanceError):
        spike.hazard_score = 0.99  # type: ignore[misc]


# ── SizedPositionIntent.mechanism_breakdown (§20.3.3) ───────────────────


def test_sized_position_intent_mechanism_breakdown_default_empty() -> None:
    intent = SizedPositionIntent(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        strategy_id="pofi_xsect_v1",
    )
    assert intent.mechanism_breakdown == {}


def test_sized_position_intent_mechanism_breakdown_populated() -> None:
    breakdown = {
        TrendMechanism.KYLE_INFO: 0.4,
        TrendMechanism.HAWKES_SELF_EXCITE: 0.35,
        TrendMechanism.INVENTORY: 0.25,
    }
    intent = SizedPositionIntent(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        strategy_id="pofi_xsect_v1",
        expected_gross_exposure_usd=100_000.0,
        mechanism_breakdown=breakdown,
    )
    assert intent.mechanism_breakdown == breakdown
    # fractions sum to 1.0
    assert sum(intent.mechanism_breakdown.values()) == pytest.approx(1.0)


def test_sized_position_intent_round_trip_with_mechanism_breakdown() -> None:
    intent = SizedPositionIntent(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        strategy_id="x",
        mechanism_breakdown={TrendMechanism.SCHEDULED_FLOW: 1.0},
    )
    copy = replace(intent)
    assert copy == intent
    assert copy.mechanism_breakdown[TrendMechanism.SCHEDULED_FLOW] == 1.0
