"""Kyle's lambda — price-impact regression over a rolling window.

Kyle (1985) λ measures the price-impact coefficient of net order
flow.  A practical estimator over a rolling event-time window of
trades is:

    Δp_t = λ * Δq_t + ε_t

where ``Δp_t`` is the trade-to-trade mid-price change and ``Δq_t`` is
signed trade size (buy positive, sell negative; tick rule used to
classify).  We solve the OLS slope online via maintained sums:

    λ = (n * Σ(Δp Δq) - Σ Δp * Σ Δq) /
        (n * Σ(Δq²) - (Σ Δq)²)

The window is event-time bounded by ``window_seconds``; samples
older than ``trade.timestamp_ns - window_seconds * 1e9`` are popped
off the deque tail and their contribution removed from the running
sums (Welford-style decremental update).

Returns ``λ`` (float) on every trade after the first; ``warm`` is
true once at least ``min_samples`` samples are in the window.

Determinism: incremental running sums.  Numerical drift over long
windows is bounded by the deque length cap (~window_seconds * trade
rate).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class KyleLambda60sSensor:
    """Kyle's lambda over a 60-second rolling window of trades.

    Parameters:

    - ``window_seconds`` (int, default 60): event-time window in
      seconds.
    - ``min_samples`` (int, default 30): minimum trades in the
      window before ``warm=True``.
    """

    sensor_id: str = "kyle_lambda_60s"
    # Audit P0-1: the class default is the *causal* (correct-sign) estimator,
    # version 2.0.0.  Previously the default was ``legacy`` / 1.2.0, which the
    # cached IC shows carries the WRONG sign at KYLE horizons (platform.yaml
    # P1-5 note) — any construction without explicit params silently produced
    # an inverted λ.  Defaulting to causal removes that footgun; the legacy
    # estimator is still reachable only by explicit ``alignment="legacy"``
    # (used to regenerate the locked 1.2.0 golden vector).
    sensor_version: str = "2.0.0"

    # Audit P1-5 / P0-1: ``alignment`` selects how ``Δp`` and ``Δq`` are paired.
    #
    # * ``"causal"`` (DEFAULT, sensor_version 2.0.0): ``Δp`` over ``[t-1, t)`` is
    #   paired with ``Δq_{t-1}`` — the flow that occurred at the *start* of that
    #   interval and whose permanent impact the move realises.  This is the
    #   correct Kyle alignment and remains causal (at trade ``t`` both the
    #   previous trade's size and the current mid are known; no lookahead,
    #   Inv-6 holds).
    #
    # * ``"legacy"`` (sensor_version 1.2.0, opt-in only): ``Δp`` over the
    #   interval ``[t-1, t)`` is paired with the *current* trade's signed size
    #   ``Δq_t``.  This regresses *past* mid drift on *current* flow — closer to
    #   a flow-autocorrelation statistic than Kyle's contemporaneous impact λ,
    #   and wrong-signed at the KYLE horizons.  Preserved byte-identically for
    #   the locked 1.2.0 golden vector; do not use in new configs.
    _VALID_ALIGNMENTS = ("legacy", "causal")

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 60,
        min_samples: int = 30,
        alignment: str = "causal",
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_samples < 2:
            raise ValueError(
                f"min_samples must be >= 2 (need 2+ for OLS slope), got {min_samples}"
            )
        if alignment not in self._VALID_ALIGNMENTS:
            raise ValueError(
                f"alignment must be one of {self._VALID_ALIGNMENTS}, got {alignment!r}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_samples = min_samples
        self._alignment = alignment

    def initial_state(self) -> dict[str, Any]:
        return {
            "samples": deque(),  # (ts_ns, dp, dq)
            "sum_dp": 0.0,
            "sum_dq": 0.0,
            "sum_dp_dq": 0.0,
            "sum_dq2": 0.0,
            "last_trade_price": None,
            "last_side": +1,
            "last_nbbo_mid": None,
            "mid_at_prev_trade": None,
            # Causal alignment only: signed size of the *previous* trade,
            # which is the flow paired with the next interval's Δp.
            "prev_signed_size": None,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        if isinstance(event, NBBOQuote):
            bid = float(event.bid)
            ask = float(event.ask)
            if bid <= 0.0 or ask <= 0.0:
                # A2: invalidate carry-forward mid so the next trade waits
                # for a fresh NBBO snapshot rather than using a stale mid
                # from before the bad-data gap.
                state["last_nbbo_mid"] = None
                return None
            state["last_nbbo_mid"] = (bid + ask) / 2.0
            return None

        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = float(event.size)
        if size <= 0.0:
            return None

        mid_now = state["last_nbbo_mid"]
        if mid_now is None:
            return None

        last_trade_price = state["last_trade_price"]
        if last_trade_price is None:
            state["last_trade_price"] = price
            state["mid_at_prev_trade"] = mid_now
            # Seed the previous-trade flow for the causal alignment: the
            # first trade's side defaults to ``last_side`` (+1) under the
            # tick rule, exactly as the legacy classifier would assign it.
            state["prev_signed_size"] = state["last_side"] * size
            return None

        if price > last_trade_price:
            side = +1
        elif price < last_trade_price:
            side = -1
        else:
            side = state["last_side"]
        state["last_side"] = side

        # ``mid_at_prev_trade`` is non-None here: the first-trade branch above
        # always pairs setting ``last_trade_price`` with setting it.
        mid_prev = state["mid_at_prev_trade"]
        dp = mid_now - mid_prev
        if self._alignment == "causal":
            # Pair Δp over [t-1, t) with the flow that drove it: trade t-1.
            dq = state["prev_signed_size"]
        else:
            dq = side * size  # legacy: current trade's flow (1.2.0 vector)

        samples = state["samples"]
        samples.append((event.timestamp_ns, dp, dq))
        state["sum_dp"] += dp
        state["sum_dq"] += dq
        state["sum_dp_dq"] += dp * dq
        state["sum_dq2"] += dq * dq

        cutoff = event.timestamp_ns - self._window_ns
        while samples and samples[0][0] < cutoff:
            _ts, old_dp, old_dq = samples.popleft()
            state["sum_dp"] -= old_dp
            state["sum_dq"] -= old_dq
            state["sum_dp_dq"] -= old_dp * old_dq
            state["sum_dq2"] -= old_dq * old_dq

        # ``n >= 1`` here: the just-appended sample has ts == event.timestamp_ns
        # which equals ``cutoff + window_ns``, so it is never < cutoff and
        # cannot be evicted.
        n = len(samples)

        state["mid_at_prev_trade"] = mid_now
        state["last_trade_price"] = price
        # The current trade becomes "previous" for the next interval's Δq
        # under the causal alignment.
        state["prev_signed_size"] = side * size

        sum_dq2 = state["sum_dq2"]
        denom = n * sum_dq2 - state["sum_dq"] * state["sum_dq"]
        # Relative threshold: by Cauchy-Schwarz ``denom = n²·Var(dq) >= 0``
        # in exact arithmetic, but FP cancellation can produce tiny positive
        # values when dq is nearly constant (e.g. a steady stream of same-
        # size buys).  Treat ``denom < n·sum_dq2·1e-12`` as numerically
        # degenerate and emit 0/warm=False; otherwise the OLS slope would
        # blow up under cancellation.  (The associativity here — ``(1e-12 *
        # n) * sum_dq2`` — is deliberate and pinned by the locked vectors;
        # do not refactor into ``1e-12 * (n * sum_dq2)``.)
        denom_eps = 1e-12 * n * sum_dq2
        if n < 2 or denom <= denom_eps:
            value = 0.0
            warm = False
        else:
            numer = n * state["sum_dp_dq"] - state["sum_dp"] * state["sum_dq"]
            value = numer / denom
            warm = n >= self._min_samples

        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=value,
            warm=warm,
        )
