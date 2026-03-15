"""Tests for HMM3StateFractional regime engine and registry."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import (
    HMM3StateFractional,
    get_regime_engine,
)


def _make_quote(
    symbol: str = "AAPL",
    bid: str = "149.99",
    ask: str = "150.01",
    timestamp_ns: int = 1_000_000_000,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=timestamp_ns - 1000,
    )


@pytest.fixture
def engine() -> HMM3StateFractional:
    return HMM3StateFractional()


class TestPosteriorUpdate:
    def test_returns_n_states_floats(self, engine: HMM3StateFractional) -> None:
        posteriors = engine.posterior(_make_quote())
        assert len(posteriors) == engine.n_states
        assert all(isinstance(p, float) for p in posteriors)

    def test_posteriors_sum_to_one(self, engine: HMM3StateFractional) -> None:
        posteriors = engine.posterior(_make_quote())
        assert abs(sum(posteriors) - 1.0) < 1e-10


class TestIdempotency:
    def test_same_symbol_timestamp_returns_cached(
        self, engine: HMM3StateFractional
    ) -> None:
        quote = _make_quote(timestamp_ns=1_000_000_000)
        first = engine.posterior(quote)
        second = engine.posterior(quote)
        assert first == second

    def test_different_timestamp_updates(
        self, engine: HMM3StateFractional
    ) -> None:
        q1 = _make_quote(timestamp_ns=1_000_000_000)
        q2 = _make_quote(timestamp_ns=2_000_000_000)
        first = engine.posterior(q1)
        second = engine.posterior(q2)
        # After a second update, posteriors may shift
        assert len(second) == engine.n_states


class TestCurrentState:
    def test_returns_cached_posteriors(self, engine: HMM3StateFractional) -> None:
        engine.posterior(_make_quote(symbol="AAPL"))
        cached = engine.current_state("AAPL")
        assert cached is not None
        assert len(cached) == engine.n_states

    def test_unknown_symbol_returns_none(
        self, engine: HMM3StateFractional
    ) -> None:
        assert engine.current_state("UNKNOWN") is None


class TestStateNames:
    def test_returns_tuple_of_three(self, engine: HMM3StateFractional) -> None:
        names = engine.state_names
        assert len(names) == 3
        assert isinstance(names, tuple)
        assert "normal" in names
        assert "vol_breakout" in names
        assert "compression_clustering" in names


class TestReset:
    def test_clears_cached_state(self, engine: HMM3StateFractional) -> None:
        engine.posterior(_make_quote(symbol="AAPL"))
        assert engine.current_state("AAPL") is not None
        engine.reset("AAPL")
        assert engine.current_state("AAPL") is None


class TestRegistry:
    def test_get_hmm_3state_fractional(self) -> None:
        eng = get_regime_engine("hmm_3state_fractional")
        assert isinstance(eng, HMM3StateFractional)
        assert eng.n_states == 3

    def test_unknown_engine_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown regime engine"):
            get_regime_engine("nonexistent_engine")
