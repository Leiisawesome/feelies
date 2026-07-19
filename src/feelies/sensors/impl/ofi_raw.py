"""Raw per-event Order-Flow Imbalance (pre-smoothing).

Emits the **single-event** OFI contribution between consecutive quotes — the
same Cont–Kukanov–Stoikov quantity that ``ofi_ewma`` smooths, but *unsmoothed*:

    ofi_t = +bid_size_t              if bid_t  > bid_{t-1}
            -bid_size_{t-1}          if bid_t  < bid_{t-1}
            +(bid_size_t - bid_size_{t-1}) if bid_t == bid_{t-1}
          + +ask_size_{t-1}          if ask_t  > ask_{t-1}
            -ask_size_t              if ask_t  < ask_{t-1}
            -(ask_size_t - ask_size_{t-1}) if ask_t == ask_{t-1}

Why a separate sensor (audit 2P-2):
    The price impact a KYLE alpha cares about is permanent impact ∝ **integrated
    signed flow** ``Σ ofi_t`` over the decision horizon (Cont, Kukanov & Stoikov
    2014).  Summing ``ofi_ewma`` over a window is *not* that integral — the EWMA
    already low-passes the flow, so each raw event is counted many times with
    geometric weights (double-counting), and the result is contaminated by the
    EWMA decay.  Emitting the **raw per-event** OFI lets a ``sum`` reducer
    compute the true ``Σ ofi_t`` over the horizon: each event contributes
    exactly once, so the windowed sum is the genuine net signed flow.

Reference: Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book
Events," *J. Financial Econometrics* 12(1).  Sign convention identical to
``ofi_ewma``: positive ⇒ net buy pressure.

Determinism: pure float arithmetic; no RNG; no time-of-day dependency.

Warm-up: ``warm = True`` once at least ``warm_after`` quotes with a measurable
OFI (i.e. after the first, level-establishing quote) have arrived within the
trailing ``warm_window_seconds`` event-time window — a sliding window, so the
sensor reverts to cold after sustained data gaps (S3), mirroring ``ofi_ewma``.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class OFIRawSensor:
    """Per-event signed OFI (the integrand of integrated order flow).

    Parameters:

    - ``warm_after`` (int, default 50): minimum number of OFI-bearing quotes
      within ``warm_window_seconds`` before ``warm=True``.
    - ``warm_window_seconds`` (int, default 300): sliding event-time window for
      the warm-up quote count.
    """

    sensor_id: str = "ofi_raw"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 50,
        warm_window_seconds: int = 300,
    ) -> None:
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "last_bid": None,
            "last_ask": None,
            "last_bid_size": 0,
            "last_ask_size": 0,
            "warm_ts": deque(),  # event-time timestamps of OFI-bearing quotes (S3)
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if not isinstance(event, NBBOQuote):
            return None

        bid = float(event.bid)
        ask = float(event.ask)
        # A1: drop a degenerate (halt / pre-open) book rather than poisoning
        # state with zero-price deltas.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:  # 3P-2: reject crossed book
            return None
        bid_sz = event.bid_size
        ask_sz = event.ask_size

        last_bid = state["last_bid"]
        last_ask = state["last_ask"]
        last_bid_sz = state["last_bid_size"]
        last_ask_sz = state["last_ask_size"]

        if last_bid is None or last_ask is None:
            # First quote establishes the level; no OFI is measurable yet.
            state["last_bid"] = bid
            state["last_ask"] = ask
            state["last_bid_size"] = bid_sz
            state["last_ask_size"] = ask_sz
            return SensorEmission(value=0.0, warm=False)

        if bid > last_bid:
            bid_contrib = float(bid_sz)
        elif bid < last_bid:
            bid_contrib = -float(last_bid_sz)
        else:
            bid_contrib = float(bid_sz - last_bid_sz)
        if ask > last_ask:
            ask_contrib = float(last_ask_sz)
        elif ask < last_ask:
            ask_contrib = -float(ask_sz)
        else:
            ask_contrib = -float(ask_sz - last_ask_sz)
        ofi = bid_contrib + ask_contrib

        state["last_bid"] = bid
        state["last_ask"] = ask
        state["last_bid_size"] = bid_sz
        state["last_ask_size"] = ask_sz

        # S3: sliding-window warm check — reverts to cold after data gaps.
        ts_ns = event.timestamp_ns
        warm_ts: deque[int] = state["warm_ts"]
        warm_ts.append(ts_ns)
        cutoff = ts_ns - self._warm_window_ns
        while warm_ts and warm_ts[0] < cutoff:
            warm_ts.popleft()

        return SensorEmission(value=ofi, warm=len(warm_ts) >= self._warm_after)
