"""Unit tests + locked-vector replay for KyleLambda60sSensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from tests.sensors.fixtures._generate import kyle_factory, load_fixture


def _trade(*, ts_ns: int, price: str, size: int, sequence: int = 0) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        price=Decimal(price),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


def _quote(
    *,
    ts_ns: int,
    bid: str,
    ask: str,
    sequence: int = 0,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        KyleLambda60sSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_samples"):
        KyleLambda60sSensor(min_samples=1)


def test_quote_updates_mid_returns_none() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    q = _quote(ts_ns=1, bid="100", ask="100.02", sequence=0)
    assert sensor.update(q, state, params={}) is None
    assert state["last_nbbo_mid"] == pytest.approx(100.01)


def test_first_trade_returns_none_without_nbbo_mid() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    assert sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={}) is None


def test_handcomputed_lambda_two_samples() -> None:
    """Two Δp_mid samples (+0.01, +0.02) with tick-rule Δq (+100,+200) → λ = 1e-4."""
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(
        _quote(ts_ns=999_999_999, bid="100.00", ask="100.02", sequence=0),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_999_999_999, bid="100.01", ask="100.03", sequence=2),
        state,
        params={},
    )
    r1 = sensor.update(
        _trade(ts_ns=2_000_000_000, price="100.01", size=100),
        state,
        params={},
    )
    sensor.update(
        _quote(ts_ns=2_999_999_999, bid="100.03", ask="100.05", sequence=4),
        state,
        params={},
    )
    r2 = sensor.update(
        _trade(ts_ns=3_000_000_000, price="100.03", size=200),
        state,
        params={},
    )
    assert r1 is not None
    # First sample only: denom = n*sum_dq² - sum_dq² = 1*10000 - 10000 = 0 → 0.
    assert r1.value == 0.0
    assert r1.warm is False
    assert r2 is not None
    assert r2.value == pytest.approx(1e-4, rel=1e-9)
    assert r2.warm is True


def test_window_evicts_old_samples() -> None:
    sensor = KyleLambda60sSensor(window_seconds=1, min_samples=2)
    state = sensor.initial_state()
    sensor.update(
        _quote(ts_ns=999_999_999, bid="100.00", ask="100.02", sequence=0),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_499_999_999, bid="100.01", ask="100.03", sequence=2),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_500_000_000, price="100.01", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_899_999_999, bid="100.02", ask="100.04", sequence=4),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_900_000_000, price="100.02", size=100), state, params={})
    assert len(state["samples"]) == 2
    sensor.update(
        _quote(ts_ns=6_999_999_999, bid="100.03", ask="100.05", sequence=6),
        state,
        params={},
    )
    sensor.update(
        _trade(ts_ns=7_000_000_000, price="100.03", size=100),
        state,
        params={},
    )
    assert len(state["samples"]) == 1


def test_zero_size_trade_returns_none() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=0, bid="99.99", ask="100.01", sequence=0), state, params={})
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    assert sensor.update(_trade(ts_ns=2, price="100.01", size=0), state, params={}) is None


def test_constant_price_lambda_is_zero() -> None:
    """If Δp_mid = 0, OLS slope is degenerate — emit 0."""
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=0, bid="99.99", ask="100.01", sequence=0), state, params={})
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    sensor.update(_quote(ts_ns=1, bid="99.99", ask="100.01", sequence=2), state, params={})
    reading = sensor.update(_trade(ts_ns=2, price="100", size=100), state, params={})
    assert reading is not None
    assert reading.value == 0.0
    assert reading.warm is False


def test_constructor_validates_alignment() -> None:
    with pytest.raises(ValueError, match="alignment"):
        KyleLambda60sSensor(alignment="bogus")


def _drive(sensor: KyleLambda60sSensor, steps: list[tuple[str, str, int]]):
    """Drive (kind, price/ask-or-mid, size) steps; return last reading.

    kind 'q' → quote with bid=val, ask=val+0.02; 'm' → trade at price=val.
    """
    state = sensor.initial_state()
    last = None
    seq = 0
    for kind, val, size in steps:
        seq += 1
        if kind == "q":
            ev = _quote(
                ts_ns=seq * 1_000_000_000,
                bid=val,
                ask=str(round(float(val) + 0.02, 2)),
                sequence=seq,
            )
            sensor.update(ev, state, params={})
        else:
            r = sensor.update(
                _trade(ts_ns=seq * 1_000_000_000, price=val, size=size, sequence=seq),
                state,
                params={},
            )
            if r is not None:
                last = r
    return last, state


def test_causal_alignment_pairs_dp_with_previous_trade_flow() -> None:
    """Causal: Δp over [t-1,t) pairs with Δq_{t-1}.

    Build 3 trades; the causal estimator must use the *previous* trade's
    signed size as Δq, giving a different slope than legacy.  We verify the
    sample tuples directly via state for an unambiguous, hand-checkable assertion.
    """
    legacy = KyleLambda60sSensor(window_seconds=60, min_samples=2, alignment="legacy")
    causal = KyleLambda60sSensor(window_seconds=60, min_samples=2, alignment="causal")

    # mids: 100.01 → 100.02 → 100.04 ; trades rising (all buy, +size).
    steps = [
        ("q", "100.00", 0),  # mid 100.01
        ("m", "100.00", 100),  # trade 1 (buy, +100); seeds, no sample
        ("q", "100.01", 0),  # mid 100.02
        ("m", "100.01", 200),  # trade 2 (buy, +200); Δp=+0.01
        ("q", "100.03", 0),  # mid 100.04
        ("m", "100.03", 300),  # trade 3 (buy, +300); Δp=+0.02
    ]
    _, s_legacy = _drive(legacy, steps)
    _, s_causal = _drive(causal, steps)

    # samples = [(ts, dp, dq), ...]
    legacy_dq = [dq for _ts, _dp, dq in s_legacy["samples"]]
    causal_dq = [dq for _ts, _dp, dq in s_causal["samples"]]
    # Legacy uses the CURRENT trade's size: +200, +300.
    assert legacy_dq == [200.0, 300.0]
    # Causal uses the PREVIOUS trade's size: +100 (trade1), +200 (trade2).
    assert causal_dq == [100.0, 200.0]
    # Δp is identical between the two (same mids).
    assert [dp for _t, dp, _q in s_legacy["samples"]] == pytest.approx(
        [dp for _t, dp, _q in s_causal["samples"]]
    )


def test_causal_reports_version_2() -> None:
    s = KyleLambda60sSensor(alignment="causal", sensor_version="2.0.0")
    assert s.sensor_version == "2.0.0"


def test_locked_vector_replay() -> None:
    sensor = kyle_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("kyle_lambda_60s.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-9, abs=1e-12), (
            f"record {i}: value drift"
        )
        assert reading.warm is expected_warm, f"record {i}: warm drift"
