"""Regime engine — platform-provided HMM-based regime detection.

The RegimeEngine protocol defines the contract for regime detection
services.  Alpha specs declare which engine they need in the ``regimes``
section; the AlphaLoader resolves it by name from the engine registry
and injects the instance as ``regime_engine`` into feature computation
namespaces.

The risk engine also consumes RegimeEngine for regime-aware position
sizing and drawdown gating.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from feelies.core.events import NBBOQuote


# ── RegimeEngine protocol ────────────────────────────────────────────


class RegimeEngine(Protocol):
    """Contract for regime detection services.

    Implementations must be per-symbol stateful: each call to
    ``posterior()`` updates internal state for that symbol and
    returns the current posterior probability vector over regimes.
    """

    @property
    def state_names(self) -> Sequence[str]:
        """Human-readable names for each regime state."""
        ...

    @property
    def n_states(self) -> int:
        """Number of regime states."""
        ...

    def posterior(self, quote: NBBOQuote) -> list[float]:
        """Update state and return posterior probabilities for the symbol.

        Returns a list of length ``n_states`` summing to ~1.0.
        """
        ...

    def current_state(self, symbol: str) -> list[float] | None:
        """Return cached posteriors for a symbol without updating.

        Returns None if the symbol has never been updated.  Used by
        risk engine and position sizer as a read-only query — they
        never call ``posterior()`` themselves.
        """
        ...

    def reset(self, symbol: str) -> None:
        """Clear accumulated state for a symbol."""
        ...


# ── HMM 3-State Fractional implementation ───────────────────────────


class HMM3StateFractional:
    """Built-in 3-state HMM regime engine using fractional updates.

    States:
      0 — compression/clustering (low vol, tight spreads)
      1 — normal (typical trading conditions)
      2 — vol_breakout (high vol, wide spreads)

    Uses an online Bayesian update with spread-derived observations.
    Transition matrix and emission parameters are calibrated for
    typical US equity microstructure.
    """

    _DEFAULT_STATE_NAMES = ("compression_clustering", "normal", "vol_breakout")

    _DEFAULT_TRANSITION = (
        (0.990, 0.008, 0.002),
        (0.005, 0.990, 0.005),
        (0.002, 0.008, 0.990),
    )

    # Emission: log-normal spread model — (mean_log_spread, std_log_spread)
    _DEFAULT_EMISSION = (
        (-4.5, 0.3),  # compression: very tight spreads
        (-3.5, 0.5),  # normal: moderate spreads
        (-2.5, 0.7),  # vol_breakout: wide spreads
    )

    def __init__(
        self,
        state_names: Sequence[str] | None = None,
        transition_matrix: Sequence[Sequence[float]] | None = None,
        emission_params: Sequence[tuple[float, float]] | None = None,
    ) -> None:
        self._state_names = tuple(state_names or self._DEFAULT_STATE_NAMES)
        self._n_states = len(self._state_names)
        self._transition = tuple(
            tuple(row) for row in (transition_matrix or self._DEFAULT_TRANSITION)
        )
        self._emission = tuple(
            emission_params or self._DEFAULT_EMISSION
        )
        self._posteriors: dict[str, list[float]] = {}

    @property
    def state_names(self) -> Sequence[str]:
        return self._state_names

    @property
    def n_states(self) -> int:
        return self._n_states

    def posterior(self, quote: NBBOQuote) -> list[float]:
        symbol = quote.symbol
        prior = self._posteriors.get(symbol)
        if prior is None:
            prior = [1.0 / self._n_states] * self._n_states
            self._posteriors[symbol] = prior

        predicted = self._predict(prior)
        spread = float(quote.ask - quote.bid)
        mid = float(quote.ask + quote.bid) / 2.0
        rel_spread = spread / mid if mid > 0 else 1e-6
        log_spread = math.log(max(rel_spread, 1e-12))

        likelihoods = self._emission_likelihood(log_spread)
        updated = self._bayes_update(predicted, likelihoods)
        self._posteriors[symbol] = updated
        return list(updated)

    def current_state(self, symbol: str) -> list[float] | None:
        cached = self._posteriors.get(symbol)
        return list(cached) if cached is not None else None

    def reset(self, symbol: str) -> None:
        self._posteriors.pop(symbol, None)

    def _predict(self, prior: list[float]) -> list[float]:
        predicted = [0.0] * self._n_states
        for j in range(self._n_states):
            for i in range(self._n_states):
                predicted[j] += self._transition[i][j] * prior[i]
        return predicted

    def _emission_likelihood(self, log_spread: float) -> list[float]:
        likelihoods = []
        for mu, sigma in self._emission:
            z = (log_spread - mu) / sigma
            ll = math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))
            likelihoods.append(max(ll, 1e-300))
        return likelihoods

    def _bayes_update(
        self, predicted: list[float], likelihoods: list[float]
    ) -> list[float]:
        unnorm = [p * l for p, l in zip(predicted, likelihoods)]
        total = sum(unnorm)
        if total < 1e-300:
            return [1.0 / self._n_states] * self._n_states
        return [u / total for u in unnorm]


# ── Engine registry ──────────────────────────────────────────────────

_ENGINE_REGISTRY: dict[str, type] = {
    "hmm_3state_fractional": HMM3StateFractional,
}


def register_engine(name: str, engine_cls: type) -> None:
    """Register a custom regime engine class by name."""
    _ENGINE_REGISTRY[name] = engine_cls


def get_regime_engine(name: str, **kwargs: object) -> RegimeEngine:
    """Look up and instantiate a regime engine by name.

    Raises ``KeyError`` if the engine name is not registered.
    """
    cls = _ENGINE_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(_ENGINE_REGISTRY))
        raise KeyError(
            f"Unknown regime engine '{name}'. Available: {available}"
        )
    return cls(**kwargs)  # type: ignore[return-value]
