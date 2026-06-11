"""Tests for InventoryPressureSensor (INVENTORY fingerprint)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.inventory_pressure import InventoryPressureSensor

_NS = 1_000_000_000


def _trade(ts_ns: int, price: str, size: int = 100) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        price=Decimal(price),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


def _quote(ts_ns: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.02"),
        bid_size=100,
        ask_size=100,
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
        InventoryPressureSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_trades"):
        InventoryPressureSensor(min_trades=-1)


def test_quote_returns_none() -> None:
    s = InventoryPressureSensor()
    assert s.update(_quote(1), s.initial_state(), params={}) is None


def test_non_positive_trade_ignored() -> None:
    s = InventoryPressureSensor()
    st = s.initial_state()
    assert s.update(_trade(1, "100.00", size=0), st, params={}) is None
    assert s.update(_trade(2, "0", size=100), st, params={}) is None


def test_aggressive_selling_makes_mm_long_positive_pressure() -> None:
    # Strictly falling prints ⇒ aggressive sells ⇒ MM buys ⇒ MM long ⇒ +.
    s = InventoryPressureSensor(window_seconds=60, min_trades=2)
    evs = [_trade((i + 1) * _NS, f"{100.00 - i * 0.01:.2f}", 100) for i in range(10)]
    last, _ = _drive(s, evs)
    assert last is not None and last.warm is True
    # First trade defaults to buy (+1 → MM short -100); the next 9 are sells
    # (MM long +900). Net +800 / 1000 vol = +0.8.
    assert last.value == pytest.approx(0.8, abs=1e-9)


def test_aggressive_buying_makes_mm_short_negative_pressure() -> None:
    s = InventoryPressureSensor(window_seconds=60, min_trades=2)
    evs = [_trade((i + 1) * _NS, f"{100.00 + i * 0.01:.2f}", 100) for i in range(10)]
    last, _ = _drive(s, evs)
    assert last is not None
    # All buys ⇒ MM short ⇒ value = -1000/1000 = -1.0.
    assert last.value == pytest.approx(-1.0, abs=1e-9)


def test_value_bounded_in_unit_interval() -> None:
    s = InventoryPressureSensor(window_seconds=60, min_trades=1)
    # Alternating up/down around a level ⇒ mixed aggressor ⇒ |value| < 1.
    prices = ["100.00", "100.01", "100.00", "100.01", "100.00", "100.01"]
    evs = [_trade((i + 1) * _NS, p, 100) for i, p in enumerate(prices)]
    last, _ = _drive(s, evs)
    assert last is not None
    assert -1.0 <= last.value <= 1.0


def test_window_evicts_old_trades() -> None:
    s = InventoryPressureSensor(window_seconds=1, min_trades=1)
    st = s.initial_state()
    s.update(_trade(1 * _NS, "100.00"), st, params={})
    s.update(_trade(1 * _NS + 500, "99.99"), st, params={})
    assert len(st["events"]) == 2
    # Jump 10 s ahead ⇒ both prior trades evicted, only the new one remains.
    s.update(_trade(11 * _NS, "99.98"), st, params={})
    assert len(st["events"]) == 1


def test_warm_gate() -> None:
    s = InventoryPressureSensor(window_seconds=60, min_trades=5)
    st = s.initial_state()
    r = None
    for i in range(4):
        r = s.update(_trade((i + 1) * _NS, f"{100 - i * 0.01:.2f}"), st, params={})
    assert r is not None and r.warm is False
    r = s.update(_trade(5 * _NS, "99.95"), st, params={})
    assert r is not None and r.warm is True


def test_deterministic() -> None:
    evs = [
        _trade((i + 1) * _NS, f"{100.00 + ((i * 7) % 5 - 2) * 0.01:.2f}", 100 + i)
        for i in range(50)
    ]
    a, _ = _drive(InventoryPressureSensor(min_trades=5), evs)
    b, _ = _drive(InventoryPressureSensor(min_trades=5), evs)
    assert a is not None and b is not None
    assert a.value == b.value and a.warm == b.warm
