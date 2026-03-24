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

from tests.alpha.conftest import MockAlpha, _SimpleSpreadCompute, _make_spread_feature, clock, mock_alpha, sample_quote


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


def _make_features(symbol: str, seq: int = 1) -> FeatureVector:
    """Helper to create warm FeatureVector that triggers a signal from MockAlpha."""
    return FeatureVector(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id=f"test:{seq}:{seq}",
        sequence=seq,
        symbol=symbol,
        feature_version="hash",
        values={"spread": 150.01},
        warm=True,
    )


class TestEntryCooldown:
    """Entry cooldown is per-symbol, not global across the universe."""

    def test_cooldown_suppresses_within_window(self, mock_alpha) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeSignalEngine(
            registry=registry, entry_cooldown_ticks=3,
        )

        s1 = engine.evaluate(_make_features("AAPL", seq=1))
        assert s1 is not None

        s2 = engine.evaluate(_make_features("AAPL", seq=2))
        assert s2 is None, "should be suppressed (1 tick elapsed, need 3)"

        s3 = engine.evaluate(_make_features("AAPL", seq=3))
        assert s3 is None, "should be suppressed (2 ticks elapsed, need 3)"

        s4 = engine.evaluate(_make_features("AAPL", seq=4))
        assert s4 is not None, "cooldown expired (3 ticks elapsed)"

    def test_cooldown_is_per_symbol(self, mock_alpha) -> None:
        """MSFT ticks must not consume AAPL's cooldown budget."""
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeSignalEngine(
            registry=registry, entry_cooldown_ticks=3,
        )

        s1 = engine.evaluate(_make_features("AAPL", seq=1))
        assert s1 is not None

        engine.evaluate(_make_features("MSFT", seq=2))
        engine.evaluate(_make_features("MSFT", seq=3))
        engine.evaluate(_make_features("MSFT", seq=4))

        s_aapl = engine.evaluate(_make_features("AAPL", seq=5))
        assert s_aapl is None, (
            "only 1 AAPL tick elapsed since entry — MSFT ticks must "
            "not count toward AAPL cooldown"
        )

    def test_cooldown_independent_symbols_fire_immediately(self, mock_alpha) -> None:
        """Each symbol's cooldown is independent — MSFT can fire while AAPL is cooling."""
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeSignalEngine(
            registry=registry, entry_cooldown_ticks=5,
        )

        s_aapl = engine.evaluate(_make_features("AAPL", seq=1))
        assert s_aapl is not None

        s_msft = engine.evaluate(_make_features("MSFT", seq=2))
        assert s_msft is not None, "MSFT has no prior entry — should fire immediately"

    def test_cooldown_zero_means_no_suppression(self, mock_alpha) -> None:
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeSignalEngine(
            registry=registry, entry_cooldown_ticks=0,
        )

        s1 = engine.evaluate(_make_features("AAPL", seq=1))
        s2 = engine.evaluate(_make_features("AAPL", seq=2))
        assert s1 is not None
        assert s2 is not None


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


class TestWarmUpCausality:
    """Warm-up check uses event timestamps, not ambient clock state."""

    def test_warmup_independent_of_clock_state(self, clock) -> None:
        """Clock set far in the future must not prematurely satisfy
        duration-based warm-up.  Only actual event elapsed time counts.
        """
        feat = FeatureDefinition(
            feature_id="slow",
            version="1.0",
            description="needs 10s of data",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=1, min_duration_ns=10_000_000_000),
            compute=_SimpleSpreadCompute(),
        )
        alpha = MockAlpha(alpha_id="slow_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)

        q1 = NBBOQuote(
            timestamp_ns=1_000_000_000,
            correlation_id="AAPL:1:1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("150.00"),
            ask=Decimal("150.02"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1_000_000_000,
        )
        fv1 = engine.update(q1)
        assert fv1.warm is False

        clock.set_time(999_000_000_000)

        q2 = NBBOQuote(
            timestamp_ns=2_000_000_000,
            correlation_id="AAPL:2:2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("150.01"),
            ask=Decimal("150.03"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=2_000_000_000,
        )
        fv2 = engine.update(q2)
        assert fv2.warm is False, (
            "clock is far ahead but only 1s of event data elapsed — "
            "warm-up must not use clock"
        )

        q3 = NBBOQuote(
            timestamp_ns=11_000_000_001,
            correlation_id="AAPL:11:3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("150.02"),
            ask=Decimal("150.04"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=11_000_000_001,
        )
        fv3 = engine.update(q3)
        assert fv3.warm is True

    def test_is_warm_uses_last_event_not_clock(self, clock) -> None:
        """Public is_warm() returns correct result without clock advancement."""
        feat = FeatureDefinition(
            feature_id="timed",
            version="1.0",
            description="needs 5s",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=1, min_duration_ns=5_000_000_000),
            compute=_SimpleSpreadCompute(),
        )
        alpha = MockAlpha(alpha_id="timed_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)

        q1 = NBBOQuote(
            timestamp_ns=1_000_000_000,
            correlation_id="X:1:1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100.00"),
            ask=Decimal("100.01"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1_000_000_000,
        )
        engine.update(q1)
        assert engine.is_warm("AAPL") is False

        q2 = NBBOQuote(
            timestamp_ns=6_000_000_001,
            correlation_id="X:6:2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("100.00"),
            ask=Decimal("100.01"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=6_000_000_001,
        )
        engine.update(q2)
        assert engine.is_warm("AAPL") is True

    def test_checkpoint_restore_preserves_last_ns(self, clock) -> None:
        """Restored engine retains last_ns for correct warm-up after restore."""
        feat = FeatureDefinition(
            feature_id="dur",
            version="1.0",
            description="needs 2s",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=1, min_duration_ns=2_000_000_000),
            compute=_SimpleSpreadCompute(),
        )
        alpha = MockAlpha(alpha_id="dur_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)

        q1 = NBBOQuote(
            timestamp_ns=1_000_000_000,
            correlation_id="R:1:1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100.00"),
            ask=Decimal("100.01"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1_000_000_000,
        )
        q2 = NBBOQuote(
            timestamp_ns=4_000_000_000,
            correlation_id="R:4:2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("100.01"),
            ask=Decimal("100.02"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=4_000_000_000,
        )
        engine.update(q1)
        engine.update(q2)
        assert engine.is_warm("AAPL") is True

        state, _ = engine.checkpoint("AAPL")
        engine.reset("AAPL")
        assert engine.is_warm("AAPL") is False

        engine.restore("AAPL", state)
        assert engine.is_warm("AAPL") is True


class TestValidateStateNonFiniteFloat:
    """_validate_state rejects inf/nan in feature state at checkpoint and init."""

    def test_checkpoint_rejects_inf_in_state(self, clock, sample_quote) -> None:
        """State containing float('inf') is caught at checkpoint time."""
        class _InfCompute:
            def initial_state(self) -> dict:
                return {"val": 0.0}

            def update(self, quote, state: dict) -> float:
                state["val"] = float("inf")
                return 0.0

        feat = FeatureDefinition(
            feature_id="inf_feat",
            version="1.0",
            description="produces inf state",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_InfCompute(),
        )
        alpha = MockAlpha(alpha_id="inf_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)

        with pytest.raises(TypeError, match="non-finite float"):
            engine.checkpoint("AAPL")

    def test_checkpoint_rejects_nan_in_state(self, clock, sample_quote) -> None:
        class _NanCompute:
            def initial_state(self) -> dict:
                return {"val": 0.0}

            def update(self, quote, state: dict) -> float:
                state["val"] = float("nan")
                return 0.0

        feat = FeatureDefinition(
            feature_id="nan_feat",
            version="1.0",
            description="produces nan state",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_NanCompute(),
        )
        alpha = MockAlpha(alpha_id="nan_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)

        with pytest.raises(TypeError, match="non-finite float"):
            engine.checkpoint("AAPL")

    def test_checkpoint_rejects_neg_inf_in_state(self, clock, sample_quote) -> None:
        class _NegInfCompute:
            def initial_state(self) -> dict:
                return {"val": 0.0}

            def update(self, quote, state: dict) -> float:
                state["val"] = float("-inf")
                return 0.0

        feat = FeatureDefinition(
            feature_id="neginf_feat",
            version="1.0",
            description="produces -inf state",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_NegInfCompute(),
        )
        alpha = MockAlpha(alpha_id="neginf_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)

        with pytest.raises(TypeError, match="non-finite float"):
            engine.checkpoint("AAPL")

    def test_initial_state_rejects_inf(self, clock, sample_quote) -> None:
        """Inf in initial_state() is caught on first update(), before any checkpoint."""
        class _InfInitCompute:
            def initial_state(self) -> dict:
                return {"val": float("inf")}

            def update(self, quote, state: dict) -> float:
                return 0.0

        feat = FeatureDefinition(
            feature_id="inf_init",
            version="1.0",
            description="inf in initial state",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(min_events=0),
            compute=_InfInitCompute(),
        )
        alpha = MockAlpha(alpha_id="inf_init_alpha", feature_defs=[feat])
        registry = AlphaRegistry()
        registry.register(alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)

        with pytest.raises(TypeError, match="non-finite float"):
            engine.update(sample_quote)

    def test_finite_floats_accepted(self, clock, mock_alpha, sample_quote) -> None:
        """Normal finite floats pass validation without error."""
        registry = AlphaRegistry()
        registry.register(mock_alpha)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)
        engine.update(sample_quote)

        state, count = engine.checkpoint("AAPL")
        assert count == 1


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
