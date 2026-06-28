"""Order-Flow Imbalance with exponential weighting.

OFI captures the net pressure on the top-of-book between consecutive
quotes:

    ofi_t = +bid_size_t              if bid_t  > bid_{t-1}
            -bid_size_{t-1}          if bid_t  < bid_{t-1}
            +(bid_size_t - bid_size_{t-1}) if bid_t == bid_{t-1}
          + -ask_size_t              if ask_t  < ask_{t-1}
            +ask_size_{t-1}          if ask_t  > ask_{t-1}
            -(ask_size_t - ask_size_{t-1}) if ask_t == ask_{t-1}

We then EWMA-smooth ``ofi_t`` with either fixed event-count decay ``alpha``:

    ewma_t = alpha * ofi_t + (1 - alpha) * ewma_{t-1}

or, when ``decay_tau_seconds`` is configured, event-time decay:

    alpha_t = 1 - exp(-dt / tau)
    ewma_t  = alpha_t * ofi_t + (1 - alpha_t) * ewma_{t-1}

Reference: Cont, Kukanov & Stoikov (2014) "The Price Impact of Order
Book Events".  The sign convention follows their definition: positive
EWMA ⇒ accumulating buy pressure.

Determinism: pure float arithmetic, no time-of-day dependency, no
RNG.  Replay-stable to the bit.

Warm-up: ``warm = True`` once at least ``warm_after`` NBBOQuote events
have arrived within the trailing ``warm_window_seconds`` event-time
window.  Using a sliding window rather than a monotonic counter means
the sensor correctly reverts to ``warm=False`` after market halts or
extended data gaps (S3).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class OFIEwmaSensor:
    """OFI smoothed with an EWMA filter.

    Parameters (passed via ``SensorSpec.params``):

    - ``alpha`` (float, default 0.1): EWMA smoothing factor in
      (0, 1].  Used only when ``decay_tau_seconds`` is not set.
      Higher α tracks short-horizon flow; lower α emphasises persistent
      imbalance.
    - ``decay_tau_seconds`` (float | None, default None): event-time
      EWMA time constant.  When set, the per-update smoothing weight is
      ``1 - exp(-dt / tau)`` where ``dt`` is the event-time gap since
      the prior accepted quote.
    - ``max_gap_seconds`` (int | None, default None): when set, an
      inter-quote gap larger than this resets the OFI state before
      processing the new quote, preventing stale pre-gap book levels
      from producing a cross-gap OFI jump.
    - ``normalize_by_depth`` (bool, default False): divide the raw OFI
      by local displayed depth before smoothing so the output is a
      scale-aware pressure measure instead of raw share units.
    - ``depth_floor`` (float, default 1.0): denominator floor used only
      when ``normalize_by_depth`` is true.
    - ``warm_after`` (int, default 50): minimum number of quotes
      within ``warm_window_seconds`` before ``warm=True``.
    - ``warm_window_seconds`` (int, default 300): sliding event-time
      window for the warm-up quote count.  Quotes older than this
      boundary do not count toward ``warm_after``, so the sensor
      reverts to cold after sustained data gaps.
    """

    sensor_id: str = "ofi_ewma"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        alpha: float = 0.1,
        decay_tau_seconds: float | None = None,
        max_gap_seconds: int | None = None,
        normalize_by_depth: bool = False,
        depth_floor: float = 1.0,
        warm_after: int = 50,
        warm_window_seconds: int = 300,
    ) -> None:
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        if decay_tau_seconds is not None and decay_tau_seconds <= 0.0:
            raise ValueError(f"decay_tau_seconds must be > 0 or None, got {decay_tau_seconds}")
        if max_gap_seconds is not None and max_gap_seconds <= 0:
            raise ValueError(f"max_gap_seconds must be > 0 or None, got {max_gap_seconds}")
        if depth_floor <= 0.0:
            raise ValueError(f"depth_floor must be > 0, got {depth_floor}")
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._alpha = alpha
        self._decay_tau_ns = (
            None if decay_tau_seconds is None else float(decay_tau_seconds) * 1_000_000_000.0
        )
        self._max_gap_ns = None if max_gap_seconds is None else max_gap_seconds * 1_000_000_000
        self._normalize_by_depth = normalize_by_depth
        self._depth_floor = float(depth_floor)
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000

    def initial_state(self) -> dict[str, Any]:
        return {
            "ewma": 0.0,
            "last_bid": None,
            "last_ask": None,
            "last_bid_size": 0,
            "last_ask_size": 0,
            "last_ts_ns": None,
            "warm_ts": deque(),  # event-time timestamps of recent quotes (S3)
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None

        bid = float(event.bid)
        ask = float(event.ask)
        # A1: uniform bid/ask positivity validation across price-consuming
        # sensors.  A degenerate book (halt / pre-open) provides no useful
        # OFI signal; drop the quote rather than poisoning state with
        # zero-price deltas.
        if bid <= 0.0 or ask <= 0.0 or bid > ask:  # 3P-2: reject crossed book
            return None
        bid_sz = event.bid_size
        ask_sz = event.ask_size
        ts_ns = event.timestamp_ns

        last_bid = state["last_bid"]
        last_ask = state["last_ask"]
        last_bid_sz = state["last_bid_size"]
        last_ask_sz = state["last_ask_size"]
        last_ts = state.get("last_ts_ns")

        if (
            self._max_gap_ns is not None
            and last_ts is not None
            and (ts_ns - last_ts) > self._max_gap_ns
        ):
            state["ewma"] = 0.0
            state["last_bid"] = None
            state["last_ask"] = None
            state["last_bid_size"] = 0
            state["last_ask_size"] = 0
            state["last_ts_ns"] = None
            state["warm_ts"].clear()
            last_bid = None
            last_ask = None
            last_bid_sz = 0
            last_ask_sz = 0
            last_ts = None

        if last_bid is None or last_ask is None:
            # First-quote bootstrap: no prior level to diff against.  Skip
            # the EWMA update so a checkpoint-restored ``state["ewma"]`` is
            # not silently re-seeded toward 0 by folding in a synthetic
            # zero-OFI sample.  Just capture the level for next call.
            state["last_bid"] = bid
            state["last_ask"] = ask
            state["last_bid_size"] = bid_sz
            state["last_ask_size"] = ask_sz
            state["last_ts_ns"] = ts_ns
            new_ewma = state["ewma"]
        else:
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

            if self._normalize_by_depth:
                depth = max(float(bid_sz + ask_sz), self._depth_floor)
                ofi /= depth

            alpha = self._effective_alpha(ts_ns=ts_ns, last_ts_ns=last_ts)
            new_ewma = alpha * ofi + (1.0 - alpha) * state["ewma"]
            state["ewma"] = new_ewma
            state["last_bid"] = bid
            state["last_ask"] = ask
            state["last_bid_size"] = bid_sz
            state["last_ask_size"] = ask_sz
            state["last_ts_ns"] = ts_ns

        # S3: sliding-window warm check — reverts to cold after data gaps
        warm_ts: deque[int] = state["warm_ts"]
        warm_ts.append(ts_ns)
        cutoff = ts_ns - self._warm_window_ns
        while warm_ts and warm_ts[0] < cutoff:
            warm_ts.popleft()

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=new_ewma,
            warm=len(warm_ts) >= self._warm_after,
        )

    def _effective_alpha(self, *, ts_ns: int, last_ts_ns: int | None) -> float:
        if self._decay_tau_ns is None:
            return self._alpha
        if last_ts_ns is None:
            return 0.0
        dt_ns = max(0, ts_ns - last_ts_ns)
        if dt_ns == 0:
            return 0.0
        return 1.0 - math.exp(-float(dt_ns) / float(self._decay_tau_ns))
