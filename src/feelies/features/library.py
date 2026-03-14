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

    Returns 0.0 when both sizes are zero.
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
        span: lookback span for EMA decay (alpha = 2 / (span + 1))
    """

    def __init__(self, span: int = 100) -> None:
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
        return state["ewma"]


class RollingVarianceComputation:
    """Incremental EWMA variance of mid-price returns.

    Uses the same exponential decay as EWMA.  The variance is computed
    on tick-to-tick mid-price differences, not raw prices, so it
    measures short-term volatility.

    Parameters:
        span: lookback span for decay (alpha = 2 / (span + 1))
    """

    def __init__(self, span: int = 100) -> None:
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
        return state["var"]


class ZScoreComputation:
    """Z-score of current spread relative to its EWMA.

    Requires upstream ``spread_ewma`` feature value to be present
    in the same tick's computation.  Falls back to computing its own
    EWMA internally if used standalone.

    Parameters:
        span: lookback span for EWMA and variance decay
    """

    def __init__(self, span: int = 100) -> None:
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
        std = math.sqrt(max(state["var"], 1e-24))
        return diff / std
