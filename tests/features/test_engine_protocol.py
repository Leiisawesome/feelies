"""Tests for FeatureEngine protocol conformance via CompositeFeatureEngine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.composite import CompositeFeatureEngine
from feelies.alpha.registry import AlphaRegistry
from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.features.definition import FeatureDefinition, WarmUpSpec


class _CountCompute:
    """Counts how many updates have been called."""

    def initial_state(self) -> dict:
        return {"n": 0}

    def update(self, quote: NBBOQuote, state: dict) -> float:
        state["n"] += 1
        return float(state["n"])


class _ConstAlpha:
    """Minimal alpha module for engine protocol tests."""

    def __init__(self, alpha_id: str = "test_alpha", warm_min: int = 0):
        from feelies.alpha.module import AlphaManifest
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0",
            description="test",
            hypothesis="test",
            falsification_criteria=("n/a",),
            required_features=frozenset(),
            symbols=None,
        )
        self._warm_min = warm_min

    @property
    def manifest(self):
        return self._manifest

    def feature_definitions(self):
        return [
            FeatureDefinition(
                feature_id="counter",
                version="1.0",
                description="tick counter",
                depends_on=frozenset(),
                warm_up=WarmUpSpec(min_events=self._warm_min, min_duration_ns=0),
                compute=_CountCompute(),
            ),
        ]

    def evaluate(self, features):
        return None

    def validate(self):
        return []


def _make_quote(ts: int = 1_000_000_000, seq: int = 1) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"TEST:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal("150.00"),
        ask=Decimal("150.02"),
        bid_size=100,
        ask_size=50,
        exchange_timestamp_ns=ts,
    )


def _build_engine(warm_min: int = 0) -> CompositeFeatureEngine:
    clock = SimulatedClock(start_ns=1_000_000_000)
    reg = AlphaRegistry(clock=clock)
    reg.register(_ConstAlpha(warm_min=warm_min))
    return CompositeFeatureEngine(reg, clock)


class TestCompositeFeatureEngineProtocol:
    def test_update_returns_feature_vector(self):
        engine = _build_engine()
        fv = engine.update(_make_quote())
        assert fv.symbol == "AAPL"
        assert "counter" in fv.values
        assert fv.values["counter"] == 1.0

    def test_incremental_update(self):
        engine = _build_engine()
        fv1 = engine.update(_make_quote(ts=1_000_000_000, seq=1))
        fv2 = engine.update(_make_quote(ts=2_000_000_000, seq=2))
        assert fv1.values["counter"] == 1.0
        assert fv2.values["counter"] == 2.0

    def test_warm_flag_false_during_warmup(self):
        engine = _build_engine(warm_min=3)
        fv = engine.update(_make_quote())
        assert fv.warm is False

    def test_warm_flag_true_after_warmup(self):
        engine = _build_engine(warm_min=2)
        engine.update(_make_quote(ts=1, seq=1))
        fv = engine.update(_make_quote(ts=2, seq=2))
        assert fv.warm is True

    def test_version_is_string(self):
        engine = _build_engine()
        assert isinstance(engine.version, str)
        assert len(engine.version) > 0

    def test_is_warm_before_any_update(self):
        engine = _build_engine(warm_min=1)
        assert engine.is_warm("AAPL") is False

    def test_is_warm_after_sufficient_updates(self):
        engine = _build_engine(warm_min=1)
        engine.update(_make_quote())
        assert engine.is_warm("AAPL") is True

    def test_reset_clears_state(self):
        engine = _build_engine()
        engine.update(_make_quote(ts=1, seq=1))
        engine.reset("AAPL")
        fv = engine.update(_make_quote(ts=2, seq=2))
        assert fv.values["counter"] == 1.0

    def test_process_trade_default_returns_none(self):
        engine = _build_engine()
        trade = Trade(
            timestamp_ns=1_000_000_000,
            correlation_id="T:1:1",
            sequence=1,
            symbol="AAPL",
            price=Decimal("150.01"),
            size=100,
            exchange_timestamp_ns=1_000_000_000,
        )
        result = engine.process_trade(trade)
        assert result is None

    def test_per_symbol_isolation(self):
        engine = _build_engine()
        q_aapl = _make_quote(ts=1, seq=1)
        q_msft = NBBOQuote(
            timestamp_ns=2,
            correlation_id="MSFT:2:1",
            sequence=1,
            symbol="MSFT",
            bid=Decimal("300.00"),
            ask=Decimal("300.05"),
            bid_size=200,
            ask_size=100,
            exchange_timestamp_ns=2,
        )
        engine.update(q_aapl)
        fv_msft = engine.update(q_msft)
        assert fv_msft.values["counter"] == 1.0

    def test_checkpoint_restore_roundtrip(self):
        engine = _build_engine()
        engine.update(_make_quote(ts=1, seq=1))
        engine.update(_make_quote(ts=2, seq=2))
        state_bytes, event_count = engine.checkpoint("AAPL")
        assert isinstance(state_bytes, bytes)
        assert event_count == 2

        engine2 = _build_engine()
        engine2.restore("AAPL", state_bytes)
        fv = engine2.update(_make_quote(ts=3, seq=3))
        assert fv.values["counter"] == 3.0


class TestWarmUpSpecValidation:
    def test_zero_values_allowed(self) -> None:
        spec = WarmUpSpec(min_events=0, min_duration_ns=0)
        assert spec.min_events == 0
        assert spec.min_duration_ns == 0

    def test_positive_values_allowed(self) -> None:
        spec = WarmUpSpec(min_events=50, min_duration_ns=1_000_000)
        assert spec.min_events == 50

    def test_negative_min_events_raises(self) -> None:
        with pytest.raises(ValueError, match="min_events must be >= 0"):
            WarmUpSpec(min_events=-2)

    def test_negative_min_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="min_duration_ns must be >= 0"):
            WarmUpSpec(min_duration_ns=-1)
