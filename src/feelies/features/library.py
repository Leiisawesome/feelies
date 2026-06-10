"""Standard feature computation library.

Pre-built, tested FeatureComputation implementations for common
microstructure features.  These can be used directly in Python-defined
alpha modules or referenced from YAML specs via a ``library:`` shorthand
(future extension).

All implementations satisfy the FeatureComputation protocol:
  - ``initial_state() -> dict``
  - ``update(quote: NBBOQuote, state: dict) -> float``
  - Deterministic: same event sequence + state -> same output (inv 5)
  - Incremental: state advances exactly once per call
"""

from __future__ import annotations

import math
from typing import Any

from feelies.core.events import NBBOQuote


class MidPriceComputation:
    """Mid-price: (bid + ask) / 2."""

    def initial_state(self) -> dict[str, Any]:
        return {}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        return (float(quote.bid) + float(quote.ask)) / 2.0


class SpreadComputation:
    """Bid-ask spread: ask - bid."""

    def initial_state(self) -> dict[str, Any]:
        return {}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        return float(quote.ask) - float(quote.bid)


class BidAskImbalanceComputation:
    """Size imbalance: (bid_size - ask_size) / (bid_size + ask_size).

    Returns 0.0 when both sizes are zero.  This conflates "undefined"
    (no liquidity on either side) with "balanced" (audit #13);
    callers that need to distinguish the two should also gate on the
    raw sizes upstream — the FeatureComputation protocol is constrained
    to ``float`` returns, so a sentinel is not available here.
    """

    def initial_state(self) -> dict[str, Any]:
        return {}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        total = quote.bid_size + quote.ask_size
        if total == 0:
            return 0.0
        return (quote.bid_size - quote.ask_size) / total


class EWMAComputation:
    """Exponentially weighted moving average of mid-price.

    Parameters:
        span: lookback span for EMA decay (alpha = 2 / (span + 1)).
              Must be >= 1; span=0 produces alpha=2 (overshoots every
              update) and span<0 is mathematically meaningless
              (audit #11).
    """

    def __init__(self, span: int = 100) -> None:
        if span < 1:
            raise ValueError(
                f"EWMAComputation: span must be >= 1, got {span}; "
                "smaller values yield alpha >= 1 which is not a valid "
                "exponential smoothing weight"
            )
        self._alpha = 2.0 / (span + 1)

    def initial_state(self) -> dict[str, Any]:
        return {"ewma": 0.0, "count": 0}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        mid = (float(quote.bid) + float(quote.ask)) / 2.0
        if state["count"] == 0:
            state["ewma"] = mid
        else:
            state["ewma"] += self._alpha * (mid - state["ewma"])
        state["count"] += 1
        return float(state["ewma"])


class RollingVarianceComputation:
    """Incremental EWMA of squared mid-price tick-to-tick differences.

    Computes ``EWMA(Δ²)`` where ``Δ = mid_t − mid_{t-1}`` — i.e. the
    second moment of mid-price *differences* (not log-returns), and
    *not* the centred variance ``Var(Δ) = E[Δ²] − E[Δ]²`` (audit #4).
    For high-frequency intraday data the drift ``E[Δ]`` is small, so
    ``E[Δ²] ≈ Var(Δ)``, but the two diverge under non-zero drift
    (intraday momentum, post-news).  Callers needing centred variance
    should subtract a running EWMA of ``Δ``.

    Parameters:
        span: lookback span for decay (alpha = 2 / (span + 1)).
              Must be >= 1 (audit #11).
    """

    def __init__(self, span: int = 100) -> None:
        if span < 1:
            raise ValueError(f"RollingVarianceComputation: span must be >= 1, got {span}")
        self._alpha = 2.0 / (span + 1)

    def initial_state(self) -> dict[str, Any]:
        return {"prev_mid": 0.0, "var": 0.0, "count": 0}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        mid = (float(quote.bid) + float(quote.ask)) / 2.0
        count = state["count"]
        if count == 0:
            state["prev_mid"] = mid
            state["count"] = 1
            return 0.0

        diff = mid - state["prev_mid"]
        if count == 1:
            state["var"] = diff * diff
        else:
            state["var"] += self._alpha * (diff * diff - state["var"])

        state["prev_mid"] = mid
        state["count"] = count + 1
        return float(state["var"])


class ZScoreComputation:
    """Z-score of current spread relative to its EWMA.

    Requires upstream ``spread_ewma`` feature value to be present
    in the same tick's computation.  Falls back to computing its own
    EWMA internally if used standalone.

    Design note (audit #14): the residual ``diff = spread - ewma`` is
    computed against the *prior* EWMA, then both (a) drives the EWMA
    update ``ewma += alpha * diff`` and (b) is reused as the numerator
    of the z-score ``diff / sqrt(EWMA(diff²))``.  Reusing the
    prior-residual matches the RiskMetrics convention for EWMA variance
    estimation; refactoring this to use a "current" residual would bias
    the z-score numerator and is not recommended.

    Parameters:
        span: lookback span for EWMA and variance decay.  Must be >= 1
              (audit #11).
    """

    def __init__(self, span: int = 100) -> None:
        if span < 1:
            raise ValueError(f"ZScoreComputation: span must be >= 1, got {span}")
        self._alpha = 2.0 / (span + 1)

    def initial_state(self) -> dict[str, Any]:
        return {"ewma": 0.0, "var": 0.0, "count": 0}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        spread = float(quote.ask) - float(quote.bid)
        count = state["count"]

        if count == 0:
            state["ewma"] = spread
            state["var"] = 0.0
            state["count"] = 1
            return 0.0

        diff = spread - state["ewma"]
        state["ewma"] += self._alpha * diff

        if count == 1:
            state["var"] = diff * diff
        else:
            state["var"] += self._alpha * (diff * diff - state["var"])

        state["count"] = count + 1
        std = math.sqrt(max(float(state["var"]), 1e-24))
        # Clamp z-score: near-zero variance early in the session (few ticks)
        # can produce arbitrarily large values that poison downstream signals.
        _MAX_ZSCORE = 10.0
        return float(max(-_MAX_ZSCORE, min(_MAX_ZSCORE, diff / std)))
