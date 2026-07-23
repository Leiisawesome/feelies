"""Tests for QuoteFlickerRateSensor (LIQUIDITY_STRESS fingerprint)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.quote_flicker_rate import QuoteFlickerRateSensor

_NS = 1_000_000_000


def _quote(ts_ns: int, bid: str, ask: str) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(ts_ns: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        price=Decimal("100.00"),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _drive(sensor, events):
    state = sensor.initial_state()
    last = None
    for ev in events:
        r = sensor.update(ev, state, params={})
        if r is not None:
            last = r
    return last, state


def test_constructor_validates() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        QuoteFlickerRateSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_quotes"):
        QuoteFlickerRateSensor(min_quotes=-1)
    with pytest.raises(ValueError, match="min_window_span_seconds"):
        QuoteFlickerRateSensor(min_window_span_seconds=0)


def test_trade_returns_none() -> None:
    s = QuoteFlickerRateSensor()
    assert s.update(_trade(1), s.initial_state(), params={}) is None


def test_monotonic_quotes_have_zero_flicker() -> None:
    s = QuoteFlickerRateSensor(window_seconds=60, min_quotes=1)
    evs = [
        _quote((i + 1) * _NS, f"{100.00 + i * 0.01:.2f}", f"{100.02 + i * 0.01:.2f}")
        for i in range(10)
    ]
    last, _ = _drive(s, evs)
    assert last is not None and last.warm is True
    assert last.value == 0.0  # strictly rising → no direction reversal


def test_zigzag_quotes_have_high_flicker() -> None:
    s = QuoteFlickerRateSensor(window_seconds=60, min_quotes=1)
    # bid oscillates 100.00/100.01 → every move after the first reverses.
    evs = []
    for i in range(11):
        b = 100.00 + (i % 2) * 0.01
        evs.append(_quote((i + 1) * _NS, f"{b:.2f}", f"{b + 0.02:.2f}"))
    last, _ = _drive(s, evs)
    assert last is not None
    assert last.value > 0.7  # almost every update is a reversal


def test_value_bounded_unit_interval() -> None:
    s = QuoteFlickerRateSensor(window_seconds=60, min_quotes=1)
    evs = []
    for i in range(20):
        b = 100.00 + ((i * 3) % 4) * 0.01
        evs.append(_quote((i + 1) * _NS, f"{b:.2f}", f"{b + 0.02:.2f}"))
    last, _ = _drive(s, evs)
    assert last is not None
    assert 0.0 <= last.value <= 1.0


def test_bad_quote_dropped() -> None:
    s = QuoteFlickerRateSensor(min_quotes=1)
    st = s.initial_state()
    assert s.update(_quote(1 * _NS, "0", "100.02"), st, params={}) is None
    assert s.update(_quote(2 * _NS, "100.00", "0"), st, params={}) is None


def test_window_eviction() -> None:
    s = QuoteFlickerRateSensor(window_seconds=1, min_quotes=1)
    st = s.initial_state()
    for i in range(3):
        s.update(_quote((i + 1) * _NS // 2, "100.00", "100.02"), st, params={})
    n_before = len(st["events"])
    assert n_before >= 1
    s.update(_quote(20 * _NS, "100.00", "100.02"), st, params={})
    assert len(st["events"]) == 1  # all earlier quotes aged out


def test_deterministic() -> None:
    evs = []
    for i in range(40):
        b = 100.00 + ((i * 5) % 3) * 0.01
        evs.append(_quote((i + 1) * _NS, f"{b:.2f}", f"{b + 0.02:.2f}"))
    a, _ = _drive(QuoteFlickerRateSensor(min_quotes=5), evs)
    b, _ = _drive(QuoteFlickerRateSensor(min_quotes=5), evs)
    assert a is not None and b is not None
    assert a.value == b.value and a.warm == b.warm


# Minimum window span.


def test_burst_satisfies_count_but_not_elapsed_span() -> None:
    s = QuoteFlickerRateSensor(window_seconds=10, min_quotes=3, min_window_span_seconds=8)
    st = s.initial_state()
    s.update(_quote(0, "100.00", "100.02"), st, params={})
    s.update(_quote(10_000_000, "100.00", "100.02"), st, params={})
    r3 = s.update(_quote(20_000_000, "100.00", "100.02"), st, params={})
    assert r3 is not None
    assert r3.warm is False  # count=3 satisfied, span=20ms << 8s floor


def test_genuine_elapsed_history_satisfies_span_floor() -> None:
    s = QuoteFlickerRateSensor(window_seconds=10, min_quotes=3, min_window_span_seconds=8)
    st = s.initial_state()
    s.update(_quote(0, "100.00", "100.02"), st, params={})
    s.update(_quote(1 * _NS, "100.00", "100.02"), st, params={})
    r3 = s.update(_quote(9 * _NS, "100.00", "100.02"), st, params={})
    assert r3 is not None
    assert r3.warm is True  # count=3, span=9s >= 8s floor


def test_span_floor_defaults_off_preserving_legacy_behaviour() -> None:
    s = QuoteFlickerRateSensor(window_seconds=10, min_quotes=3)
    st = s.initial_state()
    s.update(_quote(0, "100.00", "100.02"), st, params={})
    s.update(_quote(10_000_000, "100.00", "100.02"), st, params={})
    r3 = s.update(_quote(20_000_000, "100.00", "100.02"), st, params={})
    assert r3 is not None and r3.warm is True
