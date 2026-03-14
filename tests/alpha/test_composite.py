"""Unit tests for CompositeFeatureEngine and CompositeSignalEngine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.arbitration import EdgeWeightedArbitrator
from feelies.alpha.composite import (
    CompositeFeatureEngine,
    CompositeSignalEngine,
    _topological_sort,
)
from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import FeatureVector, NBBOQuote, SignalDirection, Trade
from feelies.features.definition import FeatureDefinition, WarmUpSpec

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

    def test_symbol_filter_plus_single_signal_returns_signal(self, mock_alpha) -> None:
        """Restricted alpha skipped (continue), second alpha produces signal; len==1 path."""
        restricted = MockAlpha(
            alpha_id="restricted",
            symbols=frozenset({"MSFT"}),
            feature_defs=[_make_spread_feature()],
        )
        registry = AlphaRegistry()
        registry.register(restricted)
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

    def test_alpha_exception_logged_and_skipped(self, mock_alpha) -> None:
        """When an alpha raises, it is skipped and others still evaluate."""
        class FailingAlpha(MockAlpha):
            def evaluate(self, features):
                raise RuntimeError("alpha error")

        registry = AlphaRegistry()
        registry.register(FailingAlpha(alpha_id="failing", feature_defs=[_make_spread_feature()]))
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


class _TradeCountCompute:
    """Feature that updates on trades; returns cumulative trade count."""

    def initial_state(self) -> dict:
        return {"count": 0}

    def update(self, quote, state: dict) -> float:
        return float(state["count"])

    def update_trade(self, trade, state: dict) -> float:
        state["count"] = state.get("count", 0) + 1
        return float(state["count"])


class _TradeNoopCompute:
    """Feature with update_trade that returns None (covers result-is-None branch)."""

    def initial_state(self) -> dict:
        return {}

    def update(self, quote, state: dict) -> float:
        return 0.0

    def update_trade(self, trade, state: dict) -> float | None:
        return None


class TestCompositeFeatureEngineProcessTrade:
    """Tests for process_trade()."""

    def test_process_trade_returns_none_when_no_symbol_state(
        self, clock, mock_alpha
    ) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        trade = Trade(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="t1",
            sequence=1,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=1_700_000_000_000_000_000,
        )
        result = engine.process_trade(trade)
        assert result is None

    def test_process_trade_returns_none_when_no_features_update(
        self, clock, mock_alpha, sample_quote
    ) -> None:
        """Quote-only features return None from update_trade; no fv emitted."""
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        trade = Trade(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="t1",
            sequence=1,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=1_700_000_000_000_000_000,
        )
        result = engine.process_trade(trade)
        assert result is None

    def test_process_trade_update_trade_returns_none_returns_none(
        self, clock, sample_quote
    ) -> None:
        """Feature with update_trade that returns None; covers result-is-None branch."""
        noop = FeatureDefinition(
            feature_id="noop",
            version="1.0",
            description="noop",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_TradeNoopCompute(),
        )
        alpha = MockAlpha(alpha_id="noop_alpha", feature_defs=[noop])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        trade = Trade(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="t1",
            sequence=1,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=1_700_000_000_000_000_000,
        )
        result = engine.process_trade(trade)
        assert result is None

    def test_process_trade_returns_vector_when_trade_feature_updates(
        self, clock, sample_quote
    ) -> None:
        trade_feat = FeatureDefinition(
            feature_id="trade_count",
            version="1.0",
            description="trade count",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_TradeCountCompute(),
        )
        alpha = MockAlpha(alpha_id="trade_alpha", feature_defs=[trade_feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        trade = Trade(
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="t1",
            sequence=2,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=1_700_000_000_000_000_000,
        )
        result = engine.process_trade(trade)
        assert result is not None
        assert result.values["trade_count"] == 1.0
        assert result.symbol == "AAPL"
        assert result.correlation_id == "t1"
        assert result.sequence == 2


class TestCompositeFeatureEngineRestore:
    """Tests for restore() error paths."""

    def test_restore_corrupt_json_raises(self, clock, mock_alpha, sample_quote) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        with pytest.raises(ValueError, match="Corrupt checkpoint"):
            engine.restore("AAPL", b"{ invalid json")

    def test_restore_missing_feature_state_raises(
        self, clock, mock_alpha, sample_quote
    ) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)
        payload = b'{"event_count": 1, "first_ns": 0}'
        with pytest.raises(ValueError, match="Missing feature_state"):
            engine.restore("AAPL", payload)


class TestCompositeFeatureEngineDependencies:
    """Tests for CompositeFeatureEngine with feature dependencies."""

    def test_topological_sort_with_dependency(
        self, clock, mock_alpha, sample_quote
    ) -> None:
        """Features with depends_on hit the in_degree update loop in topological sort."""
        f = _make_spread_feature()
        base = FeatureDefinition(
            feature_id="base",
            version="1.0",
            description="base",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=f.compute,
        )
        derived = FeatureDefinition(
            feature_id="derived",
            version="1.0",
            description="derived",
            depends_on=frozenset({"base"}),
            warm_up=WarmUpSpec(min_events=0),
            compute=f.compute,
        )
        alpha = MockAlpha(alpha_id="dep_alpha", feature_defs=[base, derived])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        clock.set_time(sample_quote.timestamp_ns)
        fv = engine.update(sample_quote)
        assert "base" in fv.values
        assert "derived" in fv.values


class TestTopologicalSort:
    """Tests for _topological_sort."""

    def test_circular_dependency_raises(self) -> None:
        from feelies.features.definition import FeatureDefinition, WarmUpSpec
        from tests.alpha.conftest import _make_spread_feature
        f = _make_spread_feature()
        comp = f.compute
        by_id = {
            "a": FeatureDefinition(
                feature_id="a", version="1", description="a",
                depends_on=frozenset({"b"}), warm_up=WarmUpSpec(), compute=comp,
            ),
            "b": FeatureDefinition(
                feature_id="b", version="1", description="b",
                depends_on=frozenset({"a"}), warm_up=WarmUpSpec(), compute=comp,
            ),
        }
        with pytest.raises(ValueError, match="Circular dependency"):
            _topological_sort(by_id)
