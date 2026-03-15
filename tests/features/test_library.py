"""Tests for standard feature computation library."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.features.library import (
    BidAskImbalanceComputation,
    EWMAComputation,
    MidPriceComputation,
    RollingVarianceComputation,
    SpreadComputation,
    ZScoreComputation,
)


def _make_quote(
    bid: str = "149.50",
    ask: str = "150.50",
    bid_size: int = 100,
    ask_size: int = 200,
    ts: int = 1000,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="t",
        sequence=1,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts - 100,
    )


@pytest.fixture
def quote() -> NBBOQuote:
    return _make_quote()


# ── MidPriceComputation ────────────────────────────────────────────


class TestMidPriceComputation:
    def test_initial_state_is_empty(self) -> None:
        comp = MidPriceComputation()
        assert comp.initial_state() == {}

    def test_returns_midpoint(self, quote: NBBOQuote) -> None:
        comp = MidPriceComputation()
        state = comp.initial_state()
        result = comp.update(quote, state)
        assert result == pytest.approx(150.0)

    def test_symmetric_bid_ask(self) -> None:
        comp = MidPriceComputation()
        state = comp.initial_state()
        q = _make_quote(bid="100.00", ask="100.00")
        assert comp.update(q, state) == pytest.approx(100.0)

    def test_wide_spread(self) -> None:
        comp = MidPriceComputation()
        state = comp.initial_state()
        q = _make_quote(bid="90.00", ask="110.00")
        assert comp.update(q, state) == pytest.approx(100.0)

    def test_state_unchanged_after_update(self) -> None:
        comp = MidPriceComputation()
        state = comp.initial_state()
        comp.update(_make_quote(), state)
        assert state == {}


# ── SpreadComputation ──────────────────────────────────────────────


class TestSpreadComputation:
    def test_initial_state_is_empty(self) -> None:
        comp = SpreadComputation()
        assert comp.initial_state() == {}

    def test_returns_spread(self, quote: NBBOQuote) -> None:
        comp = SpreadComputation()
        state = comp.initial_state()
        result = comp.update(quote, state)
        assert result == pytest.approx(1.0)

    def test_zero_spread(self) -> None:
        comp = SpreadComputation()
        state = comp.initial_state()
        q = _make_quote(bid="100.00", ask="100.00")
        assert comp.update(q, state) == pytest.approx(0.0)

    def test_penny_spread(self) -> None:
        comp = SpreadComputation()
        state = comp.initial_state()
        q = _make_quote(bid="100.00", ask="100.01")
        assert comp.update(q, state) == pytest.approx(0.01)


# ── BidAskImbalanceComputation ─────────────────────────────────────


class TestBidAskImbalanceComputation:
    def test_initial_state_is_empty(self) -> None:
        comp = BidAskImbalanceComputation()
        assert comp.initial_state() == {}

    def test_returns_imbalance(self, quote: NBBOQuote) -> None:
        comp = BidAskImbalanceComputation()
        state = comp.initial_state()
        result = comp.update(quote, state)
        # bid_size=100, ask_size=200 → (100-200)/(100+200) = -1/3
        assert result == pytest.approx(-1.0 / 3.0)

    def test_returns_zero_when_both_sizes_zero(self) -> None:
        comp = BidAskImbalanceComputation()
        state = comp.initial_state()
        q = _make_quote(bid_size=0, ask_size=0)
        assert comp.update(q, state) == 0.0

    def test_full_bid_imbalance(self) -> None:
        comp = BidAskImbalanceComputation()
        state = comp.initial_state()
        q = _make_quote(bid_size=500, ask_size=0)
        assert comp.update(q, state) == pytest.approx(1.0)

    def test_full_ask_imbalance(self) -> None:
        comp = BidAskImbalanceComputation()
        state = comp.initial_state()
        q = _make_quote(bid_size=0, ask_size=500)
        assert comp.update(q, state) == pytest.approx(-1.0)

    def test_balanced_sizes(self) -> None:
        comp = BidAskImbalanceComputation()
        state = comp.initial_state()
        q = _make_quote(bid_size=300, ask_size=300)
        assert comp.update(q, state) == pytest.approx(0.0)


# ── EWMAComputation ───────────────────────────────────────────────


class TestEWMAComputation:
    def test_initial_state_keys(self) -> None:
        comp = EWMAComputation(span=10)
        state = comp.initial_state()
        assert state == {"ewma": 0.0, "count": 0}

    def test_first_update_returns_mid(self, quote: NBBOQuote) -> None:
        comp = EWMAComputation(span=10)
        state = comp.initial_state()
        result = comp.update(quote, state)
        assert result == pytest.approx(150.0)

    def test_subsequent_updates_move_toward_new_mid(self) -> None:
        comp = EWMAComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="100.00")
        q2 = _make_quote(bid="110.00", ask="110.00")

        r1 = comp.update(q1, state)
        assert r1 == pytest.approx(100.0)

        r2 = comp.update(q2, state)
        assert 100.0 < r2 < 110.0

    def test_count_increments(self) -> None:
        comp = EWMAComputation(span=10)
        state = comp.initial_state()
        q = _make_quote()
        comp.update(q, state)
        assert state["count"] == 1
        comp.update(q, state)
        assert state["count"] == 2

    def test_alpha_formula(self) -> None:
        comp = EWMAComputation(span=10)
        expected_alpha = 2.0 / (10 + 1)
        assert comp._alpha == pytest.approx(expected_alpha)

    def test_ewma_update_formula(self) -> None:
        """Verify EWMA follows: ewma += alpha * (mid - ewma)."""
        span = 10
        alpha = 2.0 / (span + 1)
        comp = EWMAComputation(span=span)
        state = comp.initial_state()

        q1 = _make_quote(bid="100.00", ask="100.00")
        comp.update(q1, state)
        assert state["ewma"] == pytest.approx(100.0)

        q2 = _make_quote(bid="120.00", ask="120.00")
        expected = 100.0 + alpha * (120.0 - 100.0)
        result = comp.update(q2, state)
        assert result == pytest.approx(expected)

    def test_convergence_toward_constant_price(self) -> None:
        comp = EWMAComputation(span=5)
        state = comp.initial_state()
        q_start = _make_quote(bid="90.00", ask="90.00")
        comp.update(q_start, state)

        q_target = _make_quote(bid="100.00", ask="100.00")
        for _ in range(100):
            comp.update(q_target, state)
        assert state["ewma"] == pytest.approx(100.0, abs=0.01)


# ── RollingVarianceComputation ─────────────────────────────────────


class TestRollingVarianceComputation:
    def test_initial_state_keys(self) -> None:
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        assert state == {"prev_mid": 0.0, "var": 0.0, "count": 0}

    def test_first_update_returns_zero(self, quote: NBBOQuote) -> None:
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        result = comp.update(quote, state)
        assert result == 0.0

    def test_second_update_returns_diff_squared(self) -> None:
        """count==1 → var = diff*diff (seed variance from first return)."""
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="100.00")
        q2 = _make_quote(bid="105.00", ask="105.00")

        comp.update(q1, state)
        result = comp.update(q2, state)
        expected = (105.0 - 100.0) ** 2
        assert result == pytest.approx(expected)

    def test_variance_positive_after_price_change(self) -> None:
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="100.00")
        q2 = _make_quote(bid="110.00", ask="110.00")

        comp.update(q1, state)
        result = comp.update(q2, state)
        assert result > 0.0

    def test_variance_updates_incrementally(self) -> None:
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="100.00")
        q2 = _make_quote(bid="101.00", ask="101.00")
        q3 = _make_quote(bid="102.00", ask="102.00")

        comp.update(q1, state)
        comp.update(q2, state)
        v3 = comp.update(q3, state)
        assert v3 > 0.0
        assert state["count"] == 3

    def test_zero_variance_when_price_stable(self) -> None:
        """Variance converges toward 0 when price is constant."""
        comp = RollingVarianceComputation(span=5)
        state = comp.initial_state()
        q = _make_quote(bid="100.00", ask="100.00")
        comp.update(q, state)
        for _ in range(50):
            comp.update(q, state)
        assert state["var"] == pytest.approx(0.0, abs=1e-10)

    def test_prev_mid_tracks_last_mid(self) -> None:
        comp = RollingVarianceComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="100.00")
        q2 = _make_quote(bid="105.00", ask="105.00")
        comp.update(q1, state)
        comp.update(q2, state)
        assert state["prev_mid"] == pytest.approx(105.0)


# ── ZScoreComputation ─────────────────────────────────────────────


class TestZScoreComputation:
    def test_initial_state_keys(self) -> None:
        comp = ZScoreComputation(span=10)
        state = comp.initial_state()
        assert state == {"ewma": 0.0, "var": 0.0, "count": 0}

    def test_first_update_returns_zero(self, quote: NBBOQuote) -> None:
        comp = ZScoreComputation(span=10)
        state = comp.initial_state()
        result = comp.update(quote, state)
        assert result == 0.0

    def test_zscore_nonzero_after_spread_change(self) -> None:
        comp = ZScoreComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="101.00")
        q2 = _make_quote(bid="100.00", ask="102.00")

        comp.update(q1, state)
        result = comp.update(q2, state)
        assert result != 0.0

    def test_positive_zscore_on_spread_widening(self) -> None:
        comp = ZScoreComputation(span=10)
        state = comp.initial_state()
        q1 = _make_quote(bid="100.00", ask="101.00")
        comp.update(q1, state)

        q2 = _make_quote(bid="100.00", ask="103.00")
        result = comp.update(q2, state)
        assert result > 0.0

    def test_multiple_updates_track_state(self) -> None:
        comp = ZScoreComputation(span=10)
        state = comp.initial_state()
        q = _make_quote(bid="100.00", ask="101.00")
        comp.update(q, state)
        comp.update(q, state)
        comp.update(q, state)
        assert state["count"] == 3

    def test_zscore_formula_on_second_tick(self) -> None:
        """Verify: diff / sqrt(var) on the second tick."""
        span = 10
        alpha = 2.0 / (span + 1)
        comp = ZScoreComputation(span=span)
        state = comp.initial_state()

        q1 = _make_quote(bid="100.00", ask="101.00")  # spread = 1.0
        comp.update(q1, state)

        q2 = _make_quote(bid="100.00", ask="103.00")  # spread = 3.0
        result = comp.update(q2, state)

        diff = 3.0 - 1.0  # spread - old ewma
        expected_var = diff * diff  # count==1 seed
        expected_z = diff / math.sqrt(max(expected_var, 1e-24))
        assert result == pytest.approx(expected_z)

    def test_ewma_updated_after_second_tick(self) -> None:
        span = 10
        alpha = 2.0 / (span + 1)
        comp = ZScoreComputation(span=span)
        state = comp.initial_state()

        q1 = _make_quote(bid="100.00", ask="101.00")
        comp.update(q1, state)
        assert state["ewma"] == pytest.approx(1.0)

        q2 = _make_quote(bid="100.00", ask="103.00")
        comp.update(q2, state)
        expected_ewma = 1.0 + alpha * (3.0 - 1.0)
        assert state["ewma"] == pytest.approx(expected_ewma)
