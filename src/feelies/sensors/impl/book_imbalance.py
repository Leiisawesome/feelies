"""Top-of-book size-imbalance sensor (KYLE_INFO / micro-price fingerprint).

The signed displayed-depth imbalance at the top of book:

    book_imbalance = (bid_size - ask_size) / (bid_size + ask_size)   ∈ [-1, 1]

Positive ⇒ more size resting on the bid ⇒ upward micro-price pressure (the
next marketable order is more likely to lift the offer); negative ⇒ ask-heavy.

Why this sensor exists (audit P1-B / P1-C):
    The Stoikov micro-price deviation from mid is algebraically

        micro - mid = (spread / 2) · (bid_size - ask_size)/(bid_size + ask_size)
                    = (spread / 2) · book_imbalance,

    so ``(micro - mid)/spread = book_imbalance / 2``.  The shipped
    ``micro_price`` sensor emits the micro-price *level* (~$100), and the wired
    z-score of that level is dominated by price drift — the sub-cent imbalance
    content is < 0.01 % of the variance, so the Stoikov edge is destroyed at the
    feature layer.  This sensor exposes the imbalance *directly* and
    level-invariantly, recovering the L1 footprint that the level z-score loses.

Reference: Stoikov (2018) "The Micro-Price: A High-Frequency Estimator of
Future Prices"; Cont, Kukanov & Stoikov (2014) for the queue-imbalance ⇒
short-horizon price-pressure mechanism.

Edge case: a degenerate book with zero total displayed depth (or a non-positive
side, a halt / pre-open marker) carries no imbalance information — we emit
``value=0.0`` with ``warm=False`` so the absence of liquidity is not conflated
with a balanced book (the FeatureComputation ``float``-only sentinel problem the
legacy ``BidAskImbalanceComputation`` could not avoid, audit #13).

Determinism: a single float division per event; no RNG, no clock reads, no
time-of-day dependency.  Replay-stable to the bit.

Warm-up: ``warm = True`` once at least ``warm_after`` quotes with positive
two-sided depth have arrived within the trailing ``warm_window_seconds``
event-time window (sliding window ⇒ reverts to cold after sustained data gaps,
mirroring ``ofi_ewma`` / ``micro_price`` S3 handling).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class BookImbalanceSensor:
    """Signed top-of-book displayed-size imbalance in ``[-1, 1]``.

    Parameters:

    - ``warm_after`` (int, default 1): minimum number of valid (positive
      two-sided depth) quotes within ``warm_window_seconds`` before
      ``warm=True``.  Default 1 because the imbalance is computable from a
      single quote.
    - ``warm_window_seconds`` (int, default 60): sliding event-time window for
      the warm-up quote count; quotes older than this boundary do not count, so
      the sensor reverts to cold after sustained data gaps (S3).
    """

    sensor_id: str = "book_imbalance"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 1,
        warm_window_seconds: int = 60,
        imbalance_cap: float = 1.0,
    ) -> None:
        if warm_after < 0:
            raise ValueError(f"warm_after must be >= 0, got {warm_after}")
        if warm_window_seconds <= 0:
            raise ValueError(f"warm_window_seconds must be > 0, got {warm_window_seconds}")
        if not (0.0 < imbalance_cap <= 1.0):
            raise ValueError(f"imbalance_cap must be in (0, 1], got {imbalance_cap}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._warm_after = warm_after
        self._warm_window_ns = warm_window_seconds * 1_000_000_000
        # 3P-7: winsorise the per-quote contribution.  A lone lopsided resting
        # order (fat-finger / spoof) saturates the raw imbalance toward ±1 and,
        # because (b-a)/(b+a) is asymptotic to ±1, a 1000:1 book (±0.998) is
        # indistinguishable from a 40:1 book (±0.95).  Clamping to ``±cap``
        # bounds the influence of any single extreme quote before it is
        # averaged over the horizon.  Default 1.0 is a no-op (preserves the
        # 1.0.0 estimator exactly); production opts into a tighter cap.
        self._imbalance_cap = float(imbalance_cap)

    def initial_state(self) -> dict[str, Any]:
        return {
            "warm_ts": deque(),  # timestamps of valid (total > 0) quotes (S3)
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
        # sensors.  A zero/negative side is a halt / pre-open marker.
        if bid <= 0.0 or ask <= 0.0:
            return None

        bid_sz = event.bid_size
        ask_sz = event.ask_size
        total = bid_sz + ask_sz

        if total <= 0:
            # No displayed liquidity: imbalance is undefined, not balanced.
            return SensorReading(
                timestamp_ns=event.timestamp_ns,
                correlation_id="placeholder",
                sequence=-1,
                symbol=event.symbol,
                sensor_id=self.sensor_id,
                sensor_version=self.sensor_version,
                value=0.0,
                warm=False,
            )

        value = (bid_sz - ask_sz) / float(total)
        # 3P-7: winsorise to bound a single fat-finger / spoof quote's influence.
        cap = self._imbalance_cap
        if value > cap:
            value = cap
        elif value < -cap:
            value = -cap

        # S3: sliding-window warm check — reverts to cold after data gaps.
        ts_ns = event.timestamp_ns
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
            value=value,
            warm=len(warm_ts) >= self._warm_after,
        )
