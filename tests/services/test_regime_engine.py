"""Tests for HMM3StateFractional regime engine and registry."""

from __future__ import annotations

import json
import math
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
    sequence: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id="corr-1",
        sequence=sequence,
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


def _make_calibration_quotes(
    n: int = 100,
    bid_base: float = 150.0,
    spread: float = 0.01,
) -> list[NBBOQuote]:
    """Generate n quotes with a tight spread typical of large-cap equities."""
    quotes = []
    for i in range(n):
        ts = (i + 1) * 1_000_000
        quotes.append(_make_quote(
            bid=f"{bid_base:.2f}",
            ask=f"{bid_base + spread:.4f}",
            timestamp_ns=ts,
            sequence=i + 1,
        ))
    return quotes


class TestCalibrate:
    def test_uncalibrated_by_default(self) -> None:
        engine = HMM3StateFractional()
        assert engine.calibrated is False

    def test_calibrated_when_emission_params_provided(self) -> None:
        engine = HMM3StateFractional(
            emission_params=[(-9.6, 0.3), (-9.0, 0.5), (-8.0, 0.7)],
        )
        assert engine.calibrated is True

    def test_calibrate_succeeds_with_enough_quotes(self) -> None:
        engine = HMM3StateFractional()
        quotes = _make_calibration_quotes(n=100)
        ok = engine.calibrate(quotes)
        assert ok is True
        assert engine.calibrated is True

    def test_calibrate_fails_with_insufficient_data(self) -> None:
        engine = HMM3StateFractional()
        quotes = _make_calibration_quotes(n=5)
        ok = engine.calibrate(quotes)
        assert ok is False
        assert engine.calibrated is False

    def test_calibrated_emission_means_match_data_scale(self) -> None:
        engine = HMM3StateFractional()
        quotes = _make_calibration_quotes(n=300, bid_base=150.0, spread=0.01)
        engine.calibrate(quotes)

        expected_log_spread = math.log(0.01 / (150.0 + 0.005))
        for mu, _ in engine._emission:
            assert abs(mu - expected_log_spread) < 1.0, (
                f"Calibrated mu={mu:.2f} should be near "
                f"log(0.01/150)={expected_log_spread:.2f}"
            )

    def test_posteriors_discriminate_after_calibration(self) -> None:
        """After calibration on varied-spread data, a wide spread should
        shift posterior toward vol_breakout (state 2)."""
        engine = HMM3StateFractional()
        # Build calibration data with three distinct spread regimes
        # so tercile split produces meaningfully different emission params.
        cal_quotes: list[NBBOQuote] = []
        spreads = (
            [0.01] * 100   # tight (compression tercile)
            + [0.05] * 100  # medium (normal tercile)
            + [0.50] * 100  # wide (vol_breakout tercile)
        )
        for i, sp in enumerate(spreads):
            cal_quotes.append(_make_quote(
                bid="150.00",
                ask=f"{150.0 + sp:.4f}",
                timestamp_ns=(i + 1) * 1_000_000,
                sequence=i + 1,
            ))
        engine.calibrate(cal_quotes)

        # Feed tight-spread quotes to push posteriors toward compression
        seq = 1
        for i in range(20):
            seq += 1
            engine.posterior(_make_quote(
                bid="150.00", ask="150.01",
                timestamp_ns=seq * 1_000_000, sequence=seq,
            ))
        seq += 1
        tight_post = engine.posterior(_make_quote(
            bid="150.00", ask="150.01",
            timestamp_ns=seq * 1_000_000, sequence=seq,
        ))

        # Feed a wide-spread quote
        seq += 1
        wide_post = engine.posterior(_make_quote(
            bid="150.00", ask="151.00",
            timestamp_ns=seq * 1_000_000, sequence=seq,
        ))

        assert wide_post[2] > tight_post[2], (
            f"Wide spread should increase vol_breakout posterior: "
            f"tight={tight_post[2]:.6f}, wide={wide_post[2]:.6f}"
        )

    def test_calibrate_clears_prior_state(self) -> None:
        engine = HMM3StateFractional()
        engine.posterior(_make_quote(sequence=1))
        assert engine.current_state("AAPL") is not None

        quotes = _make_calibration_quotes(n=100)
        engine.calibrate(quotes)
        assert engine.current_state("AAPL") is None

    def test_checkpoint_includes_calibrated_emission(self) -> None:
        engine = HMM3StateFractional()
        quotes = _make_calibration_quotes(n=100)
        engine.calibrate(quotes)
        emission_before = engine._emission

        blob = engine.checkpoint()
        payload = json.loads(blob)
        assert "emission" in payload

        engine2 = HMM3StateFractional()
        assert engine2.calibrated is False
        engine2.restore(blob)
        assert engine2.calibrated is True
        assert engine2._emission == emission_before

    def test_checkpoint_without_calibration_omits_emission(self) -> None:
        engine = HMM3StateFractional()
        blob = engine.checkpoint()
        payload = json.loads(blob)
        assert "emission" not in payload
