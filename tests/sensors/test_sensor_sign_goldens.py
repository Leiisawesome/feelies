"""Economic-sign positive-control goldens (audit P0-2 / TG-1).

The most expensive class of microstructure bug is a *sign inversion* — a
sensor whose magnitude is right but whose direction is backwards (the audit
found exactly this in the legacy Kyle alignment).  The per-sensor unit suites
lock numerics, bounds, and warm transitions but almost none lock the *economic
sign*: "monotone one-sided pressure ⇒ value of the documented sign."

These tests drive a deterministic, one-sided synthetic stream through each
signed sensor and assert the sign of the emitted value matches the docstring's
stated convention.  They are intentionally coarse (sign / ordering only) so
they are robust to numerics yet catch any future inversion.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.book_imbalance import BookImbalanceSensor
from feelies.sensors.impl.hawkes_intensity import HawkesIntensitySensor
from feelies.sensors.impl.inventory_pressure import InventoryPressureSensor
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor

_NS = 1_000_000_000


def _quote(
    ts: int, bid: float, ask: float, *, bid_sz: int = 100, ask_sz: int = 100, seq: int = 0
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=bid_sz,
        ask_size=ask_sz,
        exchange_timestamp_ns=ts,
    )


def _trade(ts: int, price: float, *, size: int = 100, seq: int = 0) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"t-{seq}",
        sequence=seq,
        symbol="AAPL",
        price=Decimal(str(price)),
        size=size,
        exchange_timestamp_ns=ts,
    )


# ── OFI EWMA: positive ⇒ accumulating buy pressure ──────────────────────────


def test_ofi_ewma_sign_positive_on_rising_book() -> None:
    """Both sides ratcheting up (bid lifts, ask lifts) ⇒ positive OFI EWMA."""
    s = OFIEwmaSensor(alpha=0.2, warm_after=3, warm_window_seconds=300)
    st = s.initial_state()
    last = None
    for i in range(10):
        last = s.update(_quote(i * _NS, 100.00 + 0.01 * i, 100.02 + 0.01 * i, seq=i), st, {})
    assert last is not None and last.warm
    assert last.value > 0.0


def test_ofi_ewma_sign_negative_on_falling_book() -> None:
    """Both sides ratcheting down ⇒ negative OFI EWMA."""
    s = OFIEwmaSensor(alpha=0.2, warm_after=3, warm_window_seconds=300)
    st = s.initial_state()
    last = None
    for i in range(10):
        last = s.update(_quote(i * _NS, 100.00 - 0.01 * i, 100.02 - 0.01 * i, seq=i), st, {})
    assert last is not None and last.warm
    assert last.value < 0.0


# ── Kyle λ (causal default): positive ⇒ buy flow lifts price ────────────────


def test_kyle_causal_sign_positive_on_buy_pressure() -> None:
    """Rising mids driven by rising (buy) trades ⇒ positive impact λ.

    This is the property the legacy alignment got backwards (audit P0-1);
    the causal default must report a positive slope here.
    """
    s = KyleLambda60sSensor(window_seconds=60, min_samples=3)  # default alignment=causal
    st = s.initial_state()
    last = None
    # Convex-rising mids paired with rising trade sizes: both Δp and the
    # (causal) lagged Δq increase together, so cov(Δp, Δq_{t-1}) > 0 and Δq is
    # non-constant (a constant Δq would make the OLS slope degenerate).
    for i in range(8):
        bid = 100.00 + 0.01 * i + 0.002 * i * i
        s.update(_quote(2 * i * _NS, bid, bid + 0.02, seq=2 * i), st, {})
        last = s.update(
            _trade((2 * i + 1) * _NS, bid + 0.01, size=100 + 40 * i, seq=2 * i + 1), st, {}
        )
    assert last is not None and last.warm
    assert last.value > 0.0


# ── Inventory pressure: positive ⇒ MM net long ⇒ up-revert expected ─────────


def test_inventory_pressure_sign_positive_on_aggressive_selling() -> None:
    """A run of aggressive sells (falling prints) ⇒ MM absorbs ⇒ positive."""
    s = InventoryPressureSensor(window_seconds=60, min_trades=3)
    st = s.initial_state()
    last = None
    for i in range(10):
        last = s.update(_trade(i * _NS, 100.00 - 0.01 * i, seq=i), st, {})
    assert last is not None and last.warm
    assert last.value > 0.0


def test_inventory_pressure_sign_negative_on_aggressive_buying() -> None:
    s = InventoryPressureSensor(window_seconds=60, min_trades=3)
    st = s.initial_state()
    last = None
    for i in range(10):
        last = s.update(_trade(i * _NS, 100.00 + 0.01 * i, seq=i), st, {})
    assert last is not None and last.warm
    assert last.value < 0.0


# ── Hawkes intensity: buy-heavy flow ⇒ λ_buy > λ_sell ───────────────────────


def test_hawkes_intensity_buy_side_dominates_on_buy_burst() -> None:
    s = HawkesIntensitySensor(alpha=0.4, beta=0.05, warm_trades_per_side=0)
    st = s.initial_state()
    last = None
    for i in range(12):
        # Strictly rising prints ⇒ tick-rule buys.
        last = s.update(_trade(i * _NS, 100.00 + 0.01 * i, seq=i), st, {})
    assert last is not None
    lam_buy, lam_sell = last.value[0], last.value[1]
    assert lam_buy > lam_sell


# ── Book imbalance: bid-heavy ⇒ positive, ask-heavy ⇒ negative ──────────────


def test_book_imbalance_sign_tracks_displayed_depth() -> None:
    s = BookImbalanceSensor(warm_after=1)
    st = s.initial_state()
    bid_heavy = s.update(_quote(0, 100.00, 100.02, bid_sz=500, ask_sz=100), st, {})
    ask_heavy = s.update(_quote(_NS, 100.00, 100.02, bid_sz=100, ask_sz=500, seq=1), st, {})
    balanced = s.update(_quote(2 * _NS, 100.00, 100.02, bid_sz=300, ask_sz=300, seq=2), st, {})
    assert bid_heavy is not None and bid_heavy.value > 0.0
    assert ask_heavy is not None and ask_heavy.value < 0.0
    assert balanced is not None and balanced.value == 0.0
