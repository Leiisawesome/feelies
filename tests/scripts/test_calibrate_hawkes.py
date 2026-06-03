"""Unit coverage for the Hawkes MLE calibrator (scripts/calibrate_hawkes.py)."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from feelies.core.events import Trade
import scripts.calibrate_hawkes as ch


def _trade(ts_ns: int, price: str) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        price=Decimal(price),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )


# ── log-likelihood ───────────────────────────────────────────────────────


def test_nll_finite_for_valid_and_inf_for_invalid() -> None:
    ts = [0.0, 0.5, 1.0, 1.2, 2.0, 3.5]
    assert math.isfinite(ch._neg_log_likelihood(ts, 1.0, 0.3, 1.0))
    for bad in ((0.0, 0.3, 1.0), (1.0, -0.1, 1.0), (1.0, 0.3, 0.0)):
        assert ch._neg_log_likelihood(ts, *bad) == math.inf
    assert ch._neg_log_likelihood([0.0], 1.0, 0.3, 1.0) == math.inf


def test_nll_prefers_excitation_on_clustered_data() -> None:
    """Tightly-clustered bursts should have higher likelihood under a
    self-exciting kernel (α>0) than under pure Poisson (α→0)."""
    # Five bursts of 5 events 0.02 s apart, bursts 10 s apart.
    ts: list[float] = []
    for b in range(5):
        base = b * 10.0
        ts.extend(base + k * 0.02 for k in range(5))
    poisson = ch._neg_log_likelihood(ts, mu=len(ts) / ts[-1], alpha=1e-6, beta=1.0)
    excite = ch._neg_log_likelihood(ts, mu=0.05, alpha=8.0, beta=10.0)
    assert excite < poisson  # lower NLL = better fit


# ── optimiser ────────────────────────────────────────────────────────────


def test_nelder_mead_minimises_quadratic() -> None:
    def quad(x: list[float]) -> float:
        return (x[0] - 3.0) ** 2 + (x[1] + 1.0) ** 2

    best, fbest = ch._nelder_mead(quad, [0.0, 0.0], iters=500)
    assert best[0] == pytest.approx(3.0, abs=1e-2)
    assert best[1] == pytest.approx(-1.0, abs=1e-2)
    assert fbest == pytest.approx(0.0, abs=1e-3)


# ── side split (tick rule) ───────────────────────────────────────────────


def test_split_sides_tick_rule() -> None:
    trades = [
        _trade(0, "100.00"),       # first → default buy
        _trade(1, "100.01"),       # up → buy
        _trade(2, "100.00"),       # down → sell
        _trade(3, "100.00"),       # equal → inherit sell
        _trade(4, "100.02"),       # up → buy
    ]
    buys, sells = ch._split_sides(trades)
    assert buys == [0, 1, 4]
    assert sells == [2, 3]


# ── end-to-end fit ───────────────────────────────────────────────────────


def test_fit_returns_sane_positive_params() -> None:
    NS = ch._NS_PER_SECOND
    # Deterministic clustered arrival series (bursts) — fitter must return
    # positive μ, α, β and finite derived quantities.
    ts_ns: list[int] = []
    for b in range(20):
        base = b * 5 * NS
        ts_ns.extend(base + k * (NS // 20) for k in range(8))
    fit = ch._fit(ts_ns, "all")
    assert fit is not None
    assert fit.n == len(ts_ns)
    assert fit.mu > 0.0 and fit.alpha > 0.0 and fit.beta > 0.0
    assert math.isfinite(fit.half_life)
    assert math.isfinite(fit.ratio)


def test_fit_none_when_too_few() -> None:
    assert ch._fit([0, 1, 2], "all") is None
