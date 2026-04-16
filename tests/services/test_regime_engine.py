"""Tests for HMM3StateFractional regime engine and registry."""

from __future__ import annotations

import json
import logging
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

    def test_different_sequence_updates(
        self, engine: HMM3StateFractional
    ) -> None:
        q1 = _make_quote(timestamp_ns=1_000_000_000, sequence=1)
        q2 = _make_quote(timestamp_ns=2_000_000_000, sequence=2)
        first = engine.posterior(q1)
        second = engine.posterior(q2)
        assert len(second) == engine.n_states
        # Second update applies a fresh prediction+observation step,
        # so posteriors must differ from the first (transition shifts mass).
        assert first != second


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


class TestNaNInfRecovery:
    """Fail-safe: NaN/inf in Bayesian update resets to uniform prior."""

    def test_nan_emission_resets_to_uniform(self) -> None:
        engine = HMM3StateFractional(
            emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
        )
        # First update to establish non-uniform posteriors
        engine.posterior(_make_quote(sequence=1))

        # Monkey-patch emission to produce NaN likelihoods
        original_emission = engine._emission_likelihood

        def _nan_likelihoods(log_spread: float) -> list[float]:
            return [float("nan")] * engine.n_states

        engine._emission_likelihood = _nan_likelihoods  # type: ignore[assignment]
        posteriors = engine.posterior(_make_quote(sequence=2))
        engine._emission_likelihood = original_emission  # type: ignore[assignment]

        # Should reset to uniform prior
        expected = 1.0 / engine.n_states
        assert all(abs(p - expected) < 1e-10 for p in posteriors)

    def test_inf_emission_resets_to_uniform(self) -> None:
        engine = HMM3StateFractional(
            emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
        )
        engine.posterior(_make_quote(sequence=1))

        original_emission = engine._emission_likelihood

        def _inf_likelihoods(log_spread: float) -> list[float]:
            return [float("inf")] * engine.n_states

        engine._emission_likelihood = _inf_likelihoods  # type: ignore[assignment]
        posteriors = engine.posterior(_make_quote(sequence=2))
        engine._emission_likelihood = original_emission  # type: ignore[assignment]

        expected = 1.0 / engine.n_states
        assert all(abs(p - expected) < 1e-10 for p in posteriors)


class TestLockedAndCrossedMarket:
    """Edge case: spread <= 0 skips observation, applies prediction only."""

    def test_locked_market_skips_observation(self) -> None:
        engine = HMM3StateFractional()
        # Locked market: bid == ask
        q = _make_quote(bid="150.00", ask="150.00", sequence=1)
        posteriors = engine.posterior(q)
        assert len(posteriors) == engine.n_states
        assert abs(sum(posteriors) - 1.0) < 1e-10

    def test_crossed_market_skips_observation(self) -> None:
        engine = HMM3StateFractional()
        # Crossed market: bid > ask
        q = _make_quote(bid="150.10", ask="149.90", sequence=1)
        posteriors = engine.posterior(q)
        assert len(posteriors) == engine.n_states
        assert abs(sum(posteriors) - 1.0) < 1e-10

    def test_locked_market_still_applies_prediction_step(self) -> None:
        engine = HMM3StateFractional()
        # First: normal update to shift posteriors away from uniform
        engine.posterior(_make_quote(bid="149.99", ask="150.01", sequence=1))
        post_after_normal = engine.current_state("AAPL")

        # Second: locked market — prediction step still shifts posteriors
        q_locked = _make_quote(bid="150.00", ask="150.00", sequence=2)
        post_after_locked = engine.posterior(q_locked)

        # Posteriors should change due to prediction step (transition matrix)
        assert post_after_normal != post_after_locked


class TestMultiSymbolIsolation:
    """Updates for one symbol must not affect another."""

    def test_symbols_independent(self) -> None:
        engine = HMM3StateFractional()
        q_aapl = _make_quote(symbol="AAPL", bid="149.99", ask="150.01", sequence=1)
        q_msft = _make_quote(symbol="MSFT", bid="299.90", ask="300.10", sequence=1)

        post_aapl = engine.posterior(q_aapl)
        post_msft = engine.posterior(q_msft)

        # AAPL posteriors should not have changed after MSFT update
        assert engine.current_state("AAPL") == post_aapl

    def test_reset_one_symbol_preserves_other(self) -> None:
        engine = HMM3StateFractional()
        engine.posterior(_make_quote(symbol="AAPL", sequence=1))
        engine.posterior(_make_quote(symbol="MSFT", sequence=1))

        engine.reset("AAPL")
        assert engine.current_state("AAPL") is None
        assert engine.current_state("MSFT") is not None


class TestRestoreValidation:
    """Restore must reject corrupted checkpoint data."""

    def test_restore_rejects_negative_posteriors(self) -> None:
        engine = HMM3StateFractional()
        payload = json.dumps({
            "posteriors": {"AAPL": [0.5, -0.3, 0.8]},
            "last_update_seq": {"AAPL": 1},
        }).encode()
        with pytest.raises(ValueError, match="Negative posterior"):
            engine.restore(payload)

    def test_restore_rejects_posteriors_not_summing_to_one(self) -> None:
        engine = HMM3StateFractional()
        payload = json.dumps({
            "posteriors": {"AAPL": [0.9, 0.9, 0.9]},
            "last_update_seq": {"AAPL": 1},
        }).encode()
        with pytest.raises(ValueError, match="sum to"):
            engine.restore(payload)

    def test_restore_rejects_zero_emission_sigma(self) -> None:
        engine = HMM3StateFractional()
        payload = json.dumps({
            "posteriors": {},
            "last_update_seq": {},
            "emission": [[-4.5, 0.3], [-3.5, 0.0], [-2.5, 0.7]],
        }).encode()
        with pytest.raises(ValueError, match="sigma.*must be > 0"):
            engine.restore(payload)

    def test_restore_rejects_negative_emission_sigma(self) -> None:
        engine = HMM3StateFractional()
        payload = json.dumps({
            "posteriors": {},
            "last_update_seq": {},
            "emission": [[-4.5, 0.3], [-3.5, -0.1], [-2.5, 0.7]],
        }).encode()
        with pytest.raises(ValueError, match="sigma.*must be > 0"):
            engine.restore(payload)

    def test_restore_failure_leaves_clean_state(self) -> None:
        engine = HMM3StateFractional()
        # Establish some state first
        engine.posterior(_make_quote(sequence=1))
        assert engine.current_state("AAPL") is not None

        bad_payload = json.dumps({
            "posteriors": {"AAPL": [0.5, -0.3, 0.8]},
            "last_update_seq": {"AAPL": 1},
        }).encode()
        with pytest.raises(ValueError):
            engine.restore(bad_payload)

        # Engine should be in clean cold-start state
        assert engine.current_state("AAPL") is None


class TestTransitionMatrixValidation:
    """Transition matrix must be a proper stochastic matrix."""

    def test_rejects_negative_transition_entries(self) -> None:
        with pytest.raises(ValueError, match="negative entries"):
            HMM3StateFractional(
                transition_matrix=[
                    (1.5, -0.3, -0.2),
                    (0.005, 0.990, 0.005),
                    (0.002, 0.008, 0.990),
                ],
            )

    def test_accepts_valid_stochastic_matrix(self) -> None:
        engine = HMM3StateFractional(
            transition_matrix=[
                (0.8, 0.1, 0.1),
                (0.1, 0.8, 0.1),
                (0.1, 0.1, 0.8),
            ],
        )
        assert engine.n_states == 3


class TestPredictionNormalization:
    """Prediction step must preserve unit sum even across many steps."""

    def test_posteriors_sum_to_one_after_many_locked_market_quotes(self) -> None:
        """Consecutive locked-market quotes use the prediction-only path.
        Without renormalization, float drift would accumulate."""
        engine = HMM3StateFractional()
        # First update with a normal quote to shift away from uniform
        engine.posterior(_make_quote(bid="149.99", ask="150.01", sequence=1))

        # Feed 10,000 locked-market quotes (prediction-only path)
        for i in range(10_000):
            q = _make_quote(bid="150.00", ask="150.00", sequence=i + 2)
            posteriors = engine.posterior(q)

        total = sum(posteriors)
        assert abs(total - 1.0) < 1e-12, (
            f"After 10k prediction-only steps, posteriors sum to "
            f"{total}, expected ~1.0 within 1e-12"
        )
        assert all(p >= 0 for p in posteriors)


class TestEmissionSeparationDiagnostic:
    """Calibration warns when emissions overlap too heavily."""

    def test_overlapping_emissions_log_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Uniform-spread data produces near-identical emission params."""
        engine = HMM3StateFractional()
        # All quotes with same spread → all terciles are identical
        quotes = _make_calibration_quotes(n=100, spread=0.01)
        with caplog.at_level(logging.WARNING, logger="feelies.services.regime_engine"):
            engine.calibrate(quotes)

        assert any("weak emission separation" in r.message for r in caplog.records), (
            "Expected warning about weak emission separation"
        )

    def test_well_separated_emissions_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Varied-spread data produces well-separated emission params."""
        engine = HMM3StateFractional()
        cal_quotes: list[NBBOQuote] = []
        spreads = [0.01] * 100 + [0.10] * 100 + [1.00] * 100
        for i, sp in enumerate(spreads):
            cal_quotes.append(_make_quote(
                bid="150.00",
                ask=f"{150.0 + sp:.4f}",
                timestamp_ns=(i + 1) * 1_000_000,
                sequence=i + 1,
            ))
        with caplog.at_level(logging.WARNING, logger="feelies.services.regime_engine"):
            engine.calibrate(cal_quotes)

        assert not any("weak emission separation" in r.message for r in caplog.records), (
            "Should not warn when emissions are well separated"
        )
