"""Unit tests for signal arbitration."""

from __future__ import annotations

import pytest

from feelies.alpha.arbitration import EdgeWeightedArbitrator
from feelies.core.events import Signal, SignalDirection


def _sig(
    direction: SignalDirection,
    strength: float = 0.8,
    edge_bps: float = 10.0,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="test:1:1",
        sequence=1,
        symbol="AAPL",
        strategy_id="test",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )


class TestEdgeWeightedArbitrator:
    """Tests for EdgeWeightedArbitrator."""

    def test_empty_returns_none(self) -> None:
        arb = EdgeWeightedArbitrator()
        assert arb.arbitrate([]) is None

    def test_single_signal_returns_it(self) -> None:
        arb = EdgeWeightedArbitrator()
        s = _sig(SignalDirection.LONG)
        assert arb.arbitrate([s]) is s

    def test_multiple_picks_highest_composite_score(self) -> None:
        arb = EdgeWeightedArbitrator(dead_zone_bps=0.0)
        low = _sig(SignalDirection.LONG, strength=0.5, edge_bps=5.0)  # 2.5
        high = _sig(SignalDirection.LONG, strength=1.0, edge_bps=20.0)  # 20
        mid = _sig(SignalDirection.SHORT, strength=0.8, edge_bps=10.0)  # 8
        result = arb.arbitrate([low, high, mid])
        assert result is high

    def test_dead_zone_below_threshold_returns_none(self) -> None:
        arb = EdgeWeightedArbitrator(dead_zone_bps=5.0)
        weak1 = _sig(SignalDirection.LONG, strength=0.1, edge_bps=10.0)  # 1.0
        weak2 = _sig(SignalDirection.LONG, strength=0.2, edge_bps=15.0)  # 3.0
        assert arb.arbitrate([weak1, weak2]) is None

    def test_dead_zone_above_threshold_returns_signal(self) -> None:
        arb = EdgeWeightedArbitrator(dead_zone_bps=0.5)
        strong = _sig(SignalDirection.LONG, strength=1.0, edge_bps=10.0)  # 10
        assert arb.arbitrate([strong]) is strong

    def test_all_flat_returns_first(self) -> None:
        arb = EdgeWeightedArbitrator()
        f1 = _sig(SignalDirection.FLAT)
        f2 = _sig(SignalDirection.FLAT)
        result = arb.arbitrate([f1, f2])
        assert result is f1

    def test_directional_conflict_picks_highest_score(self) -> None:
        arb = EdgeWeightedArbitrator(dead_zone_bps=0.0)
        long_sig = _sig(SignalDirection.LONG, strength=0.9, edge_bps=15.0)
        short_sig = _sig(SignalDirection.SHORT, strength=0.5, edge_bps=5.0)
        result = arb.arbitrate([long_sig, short_sig])
        assert result is long_sig
