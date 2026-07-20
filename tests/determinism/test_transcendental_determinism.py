"""Pin intra-process determinism for sensors using ``exp`` or ``log``.

Different libm implementations may differ in the last bit, so parity hashes are
host/libm-specific. Within one process, identical event streams must still
produce byte-identical readings.
"""

from __future__ import annotations

import math
from decimal import Decimal

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.hawkes_intensity import HawkesIntensitySensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor

_NS = 1_000_000_000


def _quote(ts: int, bid: float, ask: float, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _trade(ts: int, price: float, seq: int) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"t-{seq}",
        sequence=seq,
        symbol="AAPL",
        price=Decimal(str(price)),
        size=100,
        exchange_timestamp_ns=ts,
    )


def _replay_realized_vol() -> list[float]:
    s = RealizedVol30sSensor(window_seconds=30, warm_after=4)
    st = s.initial_state()
    out: list[float] = []
    for i in range(40):
        r = s.update(_quote(i * _NS, 100.0 + 0.01 * (i % 7), 100.02 + 0.01 * (i % 7), i), st, {})
        if r is not None:
            out.append(float(r.value))
    return out


def _replay_hawkes() -> list[tuple[float, ...]]:
    s = HawkesIntensitySensor(alpha=0.4, beta=0.05, warm_trades_per_side=0)
    st = s.initial_state()
    out: list[tuple[float, ...]] = []
    for i in range(40):
        # Alternating up/down prints exercise both sides + the exp decay path.
        price = 100.0 + (0.01 if i % 2 == 0 else -0.01) * (i % 5)
        r = s.update(_trade(i * _NS, price, i), st, {})
        if r is not None:
            out.append(tuple(float(v) for v in r.value))
    return out


def test_realized_vol_log_path_is_intra_process_bit_identical() -> None:
    a = _replay_realized_vol()
    b = _replay_realized_vol()
    assert a == b
    assert all(math.isfinite(v) for v in a)


def test_hawkes_exp_path_is_intra_process_bit_identical() -> None:
    a = _replay_hawkes()
    b = _replay_hawkes()
    assert a == b
    assert all(math.isfinite(v) for row in a for v in row)
