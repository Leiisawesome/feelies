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

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission


class KyleLambda60sSensor:
    """Kyle's lambda over a 60-second rolling window of trades.

    Parameters:

    - ``window_seconds`` (int, default 60): event-time window in
      seconds.
    - ``min_samples`` (int, default 30): minimum trades in the
      window before ``warm=True``.
    """

    sensor_id: str = "kyle_lambda_60s"
    # Causal alignment is the correct-sign default; legacy alignment is explicit.
    sensor_version: str = "2.0.0"

    # causal pairs an interval's price move with its preceding signed flow.
    # legacy pairs it with the current trade and exists only for vector replay.
    _VALID_ALIGNMENTS = ("legacy", "causal")

    # F1 (sensor_review_2026-07-02): ``covariance_estimator`` selects how the
    # OLS slope ``λ = Cov(Δp, Δq) / Var(Δq)`` is accumulated over the window.
    #
    # * ``"sum_products"`` (DEFAULT, versions 1.2.0 / 2.0.0): the textbook
    #   ``(n·Σδpδq − Σδp·Σδq) / (n·Σδq² − (Σδq)²)`` with add-on-arrival /
    #   subtract-on-eviction running sums.  Correct, but the denominator is a
    #   difference of two large ~equal quantities (catastrophic cancellation)
    #   that loses ~5-6 significant digits when Δq is nearly constant — the
    #   regime where informed flow is most regular.  Kept byte-identical for
    #   the locked 1.2.0 golden vector and the existing determinism baselines.
    #
    # * ``"welford"`` (sensor_version 2.1.0): a streaming Welford/Bennett
    #   co-moment (running means + M2/co-moment) with reverse updates on
    #   eviction and an exact recompute-from-window guard if cancellation ever
    #   drives the variance accumulator negative.  ``λ = C / M2_Δq`` — the
    #   sample count cancels between Cov and Var, so it equals the
    #   sum-of-products slope in exact arithmetic but stays near machine
    #   precision.  This is the recommended estimator for new configs; the
    #   canonical pairing is ``alignment="causal"`` + ``covariance_estimator=
    #   "welford"`` at ``sensor_version="2.1.0"``.
    _VALID_ESTIMATORS = ("sum_products", "welford")

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 60,
        min_samples: int = 30,
        alignment: str = "causal",
        covariance_estimator: str = "sum_products",
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
        if covariance_estimator not in self._VALID_ESTIMATORS:
            raise ValueError(
                f"covariance_estimator must be one of {self._VALID_ESTIMATORS}, "
                f"got {covariance_estimator!r}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_samples = min_samples
        self._alignment = alignment
        self._estimator = covariance_estimator

    def initial_state(self) -> dict[str, Any]:
        return {
            "samples": deque(),  # (ts_ns, dp, dq)
            # sum-of-products accumulators (estimator="sum_products").
            "sum_dp": 0.0,
            "sum_dq": 0.0,
            "sum_dp_dq": 0.0,
            "sum_dq2": 0.0,
            # F1: Welford/Bennett co-moment accumulators (estimator="welford").
            # Unused (and untouched) by the sum_products path, so their presence
            # cannot perturb the locked 1.2.0 / 2.0.0 output.
            "mean_dp": 0.0,
            "mean_dq": 0.0,
            "m2_dq": 0.0,  # Σ(Δq − mean_Δq)²
            "c_dp_dq": 0.0,  # Σ(Δq − mean_Δq)(Δp − mean_Δp)
            "_wn": 0,  # welford element count (== len(samples))
            "_drift_dirty": False,  # set when a reverse update drives m2_dq < 0
            "last_trade_price": None,
            "last_side": +1,
            "last_nbbo_mid": None,
            "mid_at_prev_trade": None,
            # Causal alignment only: signed size of the *previous* trade,
            # which is the flow paired with the next interval's Δp.
            "prev_signed_size": None,
        }

    # ── Welford/Bennett streaming co-moment (F1) ─────────────────────

    @staticmethod
    def _welford_add(state: dict[str, Any], dp: float, dq: float) -> None:
        n = state["_wn"] + 1
        state["_wn"] = n
        dx = dq - state["mean_dq"]
        state["mean_dq"] += dx / n
        dy = dp - state["mean_dp"]
        state["mean_dp"] += dy / n
        state["m2_dq"] += dx * (dq - state["mean_dq"])
        state["c_dp_dq"] += dx * (dp - state["mean_dp"])

    @staticmethod
    def _welford_remove(state: dict[str, Any], dp: float, dq: float) -> None:
        n = state["_wn"]
        if n <= 1:
            state["_wn"] = 0
            state["mean_dp"] = 0.0
            state["mean_dq"] = 0.0
            state["m2_dq"] = 0.0
            state["c_dp_dq"] = 0.0
            return
        n_new = n - 1
        mean_dq_cur = state["mean_dq"]
        mean_dp_cur = state["mean_dp"]
        mean_dq_r = (n * mean_dq_cur - dq) / n_new
        mean_dp_r = (n * mean_dp_cur - dp) / n_new
        state["m2_dq"] -= (dq - mean_dq_r) * (dq - mean_dq_cur)
        state["c_dp_dq"] -= (dq - mean_dq_r) * (dp - mean_dp_cur)
        if state["m2_dq"] < 0.0:
            # Cancellation artifact — clamp now, recompute exactly below.
            state["m2_dq"] = 0.0
            state["_drift_dirty"] = True
        state["mean_dq"] = mean_dq_r
        state["mean_dp"] = mean_dp_r
        state["_wn"] = n_new

    @staticmethod
    def _recompute_from_window(state: dict[str, Any]) -> None:
        """Exact two-pass co-moment over the live window (F1 drift reset)."""
        samples = state["samples"]
        n = len(samples)
        if n == 0:
            state["_wn"] = 0
            state["mean_dp"] = 0.0
            state["mean_dq"] = 0.0
            state["m2_dq"] = 0.0
            state["c_dp_dq"] = 0.0
            state["_drift_dirty"] = False
            return
        mean_dq = sum(dq for _ts, _dp, dq in samples) / n
        mean_dp = sum(dp for _ts, dp, _dq in samples) / n
        state["mean_dq"] = mean_dq
        state["mean_dp"] = mean_dp
        state["m2_dq"] = sum((dq - mean_dq) ** 2 for _ts, _dp, dq in samples)
        state["c_dp_dq"] = sum((dq - mean_dq) * (dp - mean_dp) for _ts, dp, dq in samples)
        state["_wn"] = n
        state["_drift_dirty"] = False

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        if isinstance(event, NBBOQuote):
            bid = float(event.bid)
            ask = float(event.ask)
            if bid <= 0.0 or ask <= 0.0 or bid > ask:
                # Invalidate the carried mid so the next trade waits
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
            # Seed prior flow using the tick rule's initial side.
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
            dq = side * size  # Legacy 1.2.0 vector behavior.

        samples = state["samples"]
        samples.append((event.timestamp_ns, dp, dq))
        if self._estimator == "sum_products":
            state["sum_dp"] += dp
            state["sum_dq"] += dq
            state["sum_dp_dq"] += dp * dq
            state["sum_dq2"] += dq * dq
        else:  # welford
            self._welford_add(state, dp, dq)

        cutoff = event.timestamp_ns - self._window_ns
        while samples and samples[0][0] < cutoff:
            _ts, old_dp, old_dq = samples.popleft()
            if self._estimator == "sum_products":
                state["sum_dp"] -= old_dp
                state["sum_dq"] -= old_dq
                state["sum_dp_dq"] -= old_dp * old_dq
                state["sum_dq2"] -= old_dq * old_dq
            else:
                self._welford_remove(state, old_dp, old_dq)
        if self._estimator == "welford" and state["_drift_dirty"]:
            self._recompute_from_window(state)

        # ``n >= 1`` here: the just-appended sample has ts == event.timestamp_ns
        # which equals ``cutoff + window_ns``, so it is never < cutoff and
        # cannot be evicted.
        n = len(samples)

        state["mid_at_prev_trade"] = mid_now
        state["last_trade_price"] = price
        # The current trade becomes "previous" for the next interval's Δq
        # under the causal alignment.
        state["prev_signed_size"] = side * size

        if self._estimator == "sum_products":
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
        else:
            # F1: streaming co-moment.  ``λ = C / M2_Δq`` (the sample count
            # cancels between Cov and Var); equal to the sum-of-products slope
            # in exact arithmetic but without its catastrophic cancellation.
            m2_dq = state["m2_dq"]
            # Degeneracy guard mirroring the sum-of-products form: the natural
            # scale is ``Σδq² = M2_Δq + n·mean_Δq²``; near-constant Δq ⇒ tiny
            # M2_Δq relative to that scale.
            scale = m2_dq + n * state["mean_dq"] * state["mean_dq"]
            if n < 2 or m2_dq <= 1e-12 * scale:
                value = 0.0
                warm = False
            else:
                value = state["c_dp_dq"] / m2_dq
                warm = n >= self._min_samples

        return SensorEmission(value=value, warm=warm)
