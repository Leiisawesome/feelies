"""Tests for the opt-in 2-D spread+vol regime engine (audit R-3).

``HMM3StateSpreadVol`` adds short-window realized volatility of the mid as a
second observation so ``vol_breakout`` means *high volatility*, not merely the
widest spread tercile.  These cover the protocol contract, idempotency,
realized-vol warm-up, vol-ordered calibration, discriminability, and
checkpoint/restore.  The engine is opt-in (registered as
``hmm_3state_spread_vol``); the default engine is unaffected.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import (
    HMM3StateSpreadVol,
    get_regime_engine,
)


def _quote(
    *,
    mid: float,
    spread: float,
    sequence: int,
    symbol: str = "AAPL",
    ts: int | None = None,
) -> NBBOQuote:
    half = spread / 2.0
    ts = ts if ts is not None else sequence * 1_000_000
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="c",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(str(round(mid - half, 4))),
        ask=Decimal(str(round(mid + half, 4))),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts - 1000,
    )


def _vol_regime_quotes(n_each: int = 120) -> list[NBBOQuote]:
    """Quiet segment (tiny mid jitter, tight spread) then volatile segment
    (large mid swings, wide spread).  Realized vol clearly separates them."""
    quotes: list[NBBOQuote] = []
    seq = 1
    mid = 100.0
    # Quiet: mid micro-jitter, tight spread.
    for i in range(n_each):
        mid += 0.001 if i % 2 == 0 else -0.001
        quotes.append(_quote(mid=mid, spread=0.01, sequence=seq))
        seq += 1
    # Volatile: large alternating mid swings, wider spread.
    for i in range(n_each):
        mid += 0.25 if i % 2 == 0 else -0.25
        quotes.append(_quote(mid=mid, spread=0.05, sequence=seq))
        seq += 1
    return quotes


# ── Protocol contract ────────────────────────────────────────────────────


def test_registry_returns_spread_vol_engine() -> None:
    eng = get_regime_engine("hmm_3state_spread_vol")
    assert isinstance(eng, HMM3StateSpreadVol)
    assert eng.n_states == 3
    assert tuple(eng.state_names) == ("compression_clustering", "normal", "vol_breakout")


def test_posterior_sums_to_one_and_three_floats() -> None:
    eng = HMM3StateSpreadVol()
    post = eng.posterior(_quote(mid=100.0, spread=0.02, sequence=1))
    assert len(post) == 3
    assert all(isinstance(p, float) for p in post)
    assert abs(sum(post) - 1.0) < 1e-9


def test_uncalibrated_by_default_calibrated_with_params() -> None:
    assert HMM3StateSpreadVol().calibrated is False
    eng = HMM3StateSpreadVol(
        emission_params=[
            ((-4.5, 0.3), (-9.5, 1.0)),
            ((-3.5, 0.5), (-8.5, 1.0)),
            ((-2.5, 0.7), (-7.5, 1.0)),
        ]
    )
    assert eng.calibrated is True


def test_idempotent_per_symbol_sequence() -> None:
    eng = HMM3StateSpreadVol()
    q = _quote(mid=100.0, spread=0.02, sequence=7)
    first = eng.posterior(q)
    second = eng.posterior(q)
    assert first == second


def test_current_state_none_for_unknown_then_set() -> None:
    eng = HMM3StateSpreadVol()
    assert eng.current_state("ZZZZ") is None
    eng.posterior(_quote(mid=100.0, spread=0.02, sequence=1))
    assert eng.current_state("AAPL") is not None


def test_reset_clears_symbol_state() -> None:
    eng = HMM3StateSpreadVol()
    eng.posterior(_quote(mid=100.0, spread=0.02, sequence=1))
    eng.reset("AAPL")
    assert eng.current_state("AAPL") is None


def test_invalid_spread_is_prediction_only() -> None:
    eng = HMM3StateSpreadVol()
    eng.posterior(_quote(mid=100.0, spread=0.02, sequence=1))
    # Locked/crossed market (zero spread) must not crash; still sums to 1.
    crossed = NBBOQuote(
        timestamp_ns=2_000_000,
        correlation_id="c",
        sequence=2,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.00"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=1_999_000,
    )
    post = eng.posterior(crossed)
    assert abs(sum(post) - 1.0) < 1e-9


# ── Realized-vol warm-up ───────────────────────────────────────────────────


def test_runs_before_realized_vol_warm() -> None:
    """Before rv warm-up the vol dimension is omitted (spread-only); the engine
    must still produce valid posteriors and not crash."""
    eng = HMM3StateSpreadVol(rv_min_returns=5)
    for s in range(1, 4):  # fewer than rv_min_returns+1 mids
        post = eng.posterior(_quote(mid=100.0 + s * 0.01, spread=0.02, sequence=s))
        assert abs(sum(post) - 1.0) < 1e-9


# ── Calibration ────────────────────────────────────────────────────────────


def test_calibrate_orders_states_by_increasing_realized_vol() -> None:
    eng = HMM3StateSpreadVol()
    ok = eng.calibrate(_vol_regime_quotes())
    assert ok is True
    assert eng.calibrated is True
    # vol-dim mean (index 1 of each emission) must be non-decreasing across
    # states, so vol_breakout (state 2) is the highest-volatility regime.
    vol_means = [eng._emission[k][1][0] for k in range(3)]
    assert vol_means[0] <= vol_means[1] <= vol_means[2]
    # And the spread is genuinely 2-D (vol_breakout vol mean strictly above
    # compression's — the segments differ).
    assert vol_means[2] > vol_means[0]


def test_calibrate_insufficient_data_returns_false() -> None:
    eng = HMM3StateSpreadVol()
    assert eng.calibrate(_vol_regime_quotes(n_each=5)) is False


def test_calibrated_engine_discriminates_vol_regimes() -> None:
    """After calibration, a volatile tape should put more mass on vol_breakout
    than a quiet tape does."""
    eng = HMM3StateSpreadVol()
    assert eng.calibrate(_vol_regime_quotes())

    vb = eng.state_names.index("vol_breakout")
    quiet = HMM3StateSpreadVol()
    quiet._emission = eng._emission
    quiet._calibrated = True
    volatile = HMM3StateSpreadVol()
    volatile._emission = eng._emission
    volatile._calibrated = True

    qmid = 100.0
    for s in range(1, 80):
        qmid += 0.001 if s % 2 == 0 else -0.001
        qpost = quiet.posterior(_quote(mid=qmid, spread=0.01, sequence=s, symbol="Q"))
    vmid = 100.0
    for s in range(1, 80):
        vmid += 0.25 if s % 2 == 0 else -0.25
        vpost = volatile.posterior(_quote(mid=vmid, spread=0.05, sequence=s, symbol="V"))

    assert vpost[vb] > qpost[vb]


# ── Discriminability (audit R-1 contract) ──────────────────────────────────


def test_discriminability_high_for_separated_emissions() -> None:
    eng = HMM3StateSpreadVol(
        emission_params=[
            ((-9.2, 0.25), (-9.5, 0.4)),
            ((-8.0, 0.45), (-8.0, 0.4)),
            ((-6.5, 0.65), (-6.5, 0.4)),
        ]
    )
    assert eng.discriminability > 1.0


def test_discriminability_low_for_degenerate_emissions() -> None:
    eng = HMM3StateSpreadVol(
        emission_params=[
            ((-9.800, 0.01), (-9.500, 0.01)),
            ((-9.799, 0.01), (-9.499, 0.01)),
            ((-9.798, 0.01), (-9.498, 0.01)),
        ]
    )
    assert eng.discriminability < 0.5


# ── Determinism + checkpoint/restore ───────────────────────────────────────


def test_two_runs_identical_posteriors() -> None:
    quotes = _vol_regime_quotes()
    e1 = HMM3StateSpreadVol()
    e1.calibrate(quotes)
    e2 = HMM3StateSpreadVol()
    e2.calibrate(quotes)
    out1 = [e1.posterior(q) for q in quotes]
    out2 = [e2.posterior(q) for q in quotes]
    assert out1 == out2


def test_checkpoint_restore_roundtrip() -> None:
    quotes = _vol_regime_quotes()
    eng = HMM3StateSpreadVol()
    eng.calibrate(quotes)
    for q in quotes[:200]:
        eng.posterior(q)
    blob = eng.checkpoint()

    restored = HMM3StateSpreadVol()
    restored.restore(blob)
    assert restored.current_state("AAPL") == eng.current_state("AAPL")
    # Continuing from the checkpoint matches continuing the original.
    nxt = quotes[200]
    assert restored.posterior(nxt) == eng.posterior(nxt)


def test_restore_rejects_flags_fingerprint_mismatch() -> None:
    eng = HMM3StateSpreadVol(rv_window=30)
    eng.posterior(_quote(mid=100.0, spread=0.02, sequence=1))
    blob = eng.checkpoint()
    other = HMM3StateSpreadVol(rv_window=20)  # different rv_window -> different fingerprint
    with pytest.raises(ValueError, match="flags_fingerprint mismatch"):
        other.restore(blob)
