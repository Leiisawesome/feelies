"""Inventory-pressure sensor (INVENTORY mechanism fingerprint).

Estimates the market maker's net inventory accumulated from aggressive
trade flow over a short event-time window, normalised to ``[-1, 1]``.
This is the trade-side companion to ``quote_replenish_asymmetry`` (the
quote-side INVENTORY proxy) and the canonical L1 fingerprint for the
``INVENTORY`` mechanism family (half-life 10–120 s, mean-reverting).

Mechanism (Ho & Stoll 1981; Madhavan & Smidt 1991): a liquidity
provider who absorbs one-sided aggressive flow accumulates inventory and
shades quotes to offload it; the price move that loaded the inventory
mean-reverts as the position is unwound.  On L1 we cannot see the MM's
book, but we can infer the *sign and size* of the inventory they must be
carrying from the aggressor side of trades:

- An aggressive **buy** (print lifting the ask) is filled *by* the MM →
  the MM goes **short** that size.
- An aggressive **sell** (print hitting the bid) is filled *by* the MM →
  the MM goes **long** that size.

So per trade the MM inventory change is ``-aggressor_side * size`` (the
MM takes the opposite side).  We accumulate this over a trailing
``window_seconds`` window and normalise by traded volume:

    inventory_pressure = Σ(-aggressor_side · size) / (Σ size + ε)   ∈ [-1, 1]

Sign convention (tradeable): **positive ⇒ MM net long** (it has absorbed
net selling) ⇒ the down-move that loaded it is expected to *revert up* ⇒
positive forward return. Symmetric for negative. ``|pressure|`` near 1
means the window's flow was strongly one-sided (large MM inventory,
strong reversion pressure).

Aggressor classification: tick rule (price strictly above the prior
trade ⇒ buy; below ⇒ sell; equal ⇒ inherit prior side; default ``+1`` on
the first trade), matching ``hawkes_intensity`` / ``vpin_50bucket`` so
the sensor is robust to NBBO inversion / stale quotes.

Determinism: integer volume accounting + one float division; event-time
deque eviction; no RNG, no clock reads.

Warm-up: ``warm = True`` once at least ``min_trades`` trades sit in the
trailing window.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission

_EPS = 1e-12


class InventoryPressureSensor:
    """Signed, volume-normalised MM-inventory proxy over a rolling window.

    Parameters:

    - ``window_seconds`` (int, default 60): trailing event-time window.
    - ``min_trades`` (int, default 20): minimum trades in the window
      before ``warm=True``.
    """

    sensor_id: str = "inventory_pressure"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 60,
        min_trades: int = 20,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_trades < 0:
            raise ValueError(f"min_trades must be >= 0, got {min_trades}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_trades = min_trades

    def initial_state(self) -> dict[str, Any]:
        return {
            "events": deque(),  # (ts_ns, mm_inv_change, size)
            "mm_inv_sum": 0,  # Σ (-aggressor_side · size) in window
            "vol_sum": 0,  # Σ size in window
            "last_price": None,
            "last_side": +1,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = int(event.size)
        # A non-positive price/size is malformed; it would also corrupt the
        # tick-rule ``last_price`` reference for subsequent trades.
        if size <= 0 or price <= 0.0:
            return None

        last_price = state["last_price"]
        if last_price is None:
            aggressor = state["last_side"]
        elif price > last_price:
            aggressor = +1
        elif price < last_price:
            aggressor = -1
        else:
            aggressor = state["last_side"]
        state["last_price"] = price
        state["last_side"] = aggressor

        # MM takes the opposite side of the aggressor.
        mm_inv_change = -aggressor * size

        ts = event.timestamp_ns
        events = state["events"]
        events.append((ts, mm_inv_change, size))
        state["mm_inv_sum"] += mm_inv_change
        state["vol_sum"] += size

        cutoff = ts - self._window_ns
        while events and events[0][0] < cutoff:
            _t, old_inv, old_sz = events.popleft()
            state["mm_inv_sum"] -= old_inv
            state["vol_sum"] -= old_sz

        vol = state["vol_sum"]
        if vol <= 0:
            value = 0.0
        else:
            value = state["mm_inv_sum"] / (float(vol) + _EPS)

        warm = len(events) >= self._min_trades

        return SensorEmission(value=value, warm=warm)
