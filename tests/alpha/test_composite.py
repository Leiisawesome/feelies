"""Unit tests for CompositeFeatureEngine and CompositeSignalEngine."""

from __future__ import annotations

import pytest

from feelies.alpha.arbitration import EdgeWeightedArbitrator
from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import FeatureVector, SignalDirection

from tests.alpha.conftest import MockAlpha, _make_spread_feature, clock, mock_alpha, sample_quote


class TestCompositeFeatureEngine:
    """Tests for CompositeFeatureEngine."""

    def test_update_returns_feature_vector(
        self, clock, mock_alpha, sample_quote
    ) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        fv = engine.update(sample_quote)

        assert isinstance(fv, FeatureVector)
        assert fv.symbol == "AAPL"
        assert "spread" in fv.values
        assert fv.values["spread"] == pytest.approx(150.01, abs=0.001)

    def test_version_is_deterministic_hash(self, clock, mock_alpha) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        assert isinstance(engine.version, str)
        assert len(engine.version) == 16

    def test_is_warm_with_zero_warmup(self, clock, mock_alpha, sample_quote) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        clock.set_time(sample_quote.timestamp_ns)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)

        assert engine.is_warm("AAPL") is True

    def test_reset_clears_state(self, clock, mock_alpha, sample_quote) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        engine.reset("AAPL")

        fv = engine.update(sample_quote)
        assert fv.event_count == 1

    def test_checkpoint_restore_roundtrip(
        self, clock, mock_alpha, sample_quote
    ) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        engine.update(sample_quote)

        state, count = engine.checkpoint("AAPL")
        engine.reset("AAPL")
        engine.restore("AAPL", state)

        fv = engine.update(sample_quote)
        assert fv.event_count == 3


class TestCompositeSignalEngine:
    """Tests for CompositeSignalEngine."""

    def test_single_alpha_produces_signal(
        self, mock_alpha
    ) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeSignalEngine(registry=registry)
        features = FeatureVector(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="test:1:1",
            sequence=1,
            symbol="AAPL",
            feature_version="hash",
            values={"spread": 150.01},
            warm=True,
        )

        signal = engine.evaluate(features)
        assert signal is not None
        assert signal.strategy_id == "mock_alpha"
        assert signal.direction == SignalDirection.LONG

    def test_no_signal_when_below_threshold(self, mock_alpha) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)

        engine = CompositeSignalEngine(registry=registry)
        features = FeatureVector(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="test:1:1",
            sequence=1,
            symbol="AAPL",
            feature_version="hash",
            values={"spread": 0.005},
            warm=True,
        )

        signal = engine.evaluate(features)
        assert signal is None

    def test_symbol_filter_excludes_non_subscribed(self, mock_alpha) -> None:
        restricted = MockAlpha(
            alpha_id="restricted",
            symbols=frozenset({"MSFT"}),
            feature_defs=[_make_spread_feature()],
        )
        registry = AlphaRegistry()
        registry.register(restricted)

        engine = CompositeSignalEngine(registry=registry)
        features = FeatureVector(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="test:1:1",
            sequence=1,
            symbol="AAPL",
            feature_version="hash",
            values={"spread": 150.01},
            warm=True,
        )

        signal = engine.evaluate(features)
        assert signal is None
