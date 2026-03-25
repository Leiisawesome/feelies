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

import json
import math
import statistics
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

        Must be idempotent per ``(symbol, sequence)``: if called
        multiple times for the same symbol and sequence number, the
        Bayesian update is applied only once and subsequent calls
        return the cached result.  This prevents double-update
        corruption when both the orchestrator (M2) and downstream
        consumers process the same quote.
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

    def checkpoint(self) -> bytes:
        """Serialize all per-symbol state to an opaque blob.

        The blob must be sufficient to fully restore internal state
        via ``restore()``.  Format is implementation-defined.
        """
        ...

    def restore(self, data: bytes) -> None:
        """Restore internal state from a blob produced by ``checkpoint()``.

        Replaces all per-symbol state.  On failure, the implementation
        must leave itself in a clean cold-start state (empty posteriors).
        """
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

    _MIN_CALIBRATION_SAMPLES = 30
    _MIN_SIGMA = 0.01

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
        self._calibrated = emission_params is not None
        self._validate_params()
        self._posteriors: dict[str, list[float]] = {}
        self._last_update_seq: dict[str, int] = {}

    def _validate_params(self) -> None:
        n = self._n_states
        if n < 2:
            raise ValueError(f"Need at least 2 states, got {n}")

        if len(self._transition) != n:
            raise ValueError(
                f"Transition matrix has {len(self._transition)} rows, "
                f"expected {n}"
            )
        for i, row in enumerate(self._transition):
            if len(row) != n:
                raise ValueError(
                    f"Transition row {i} has {len(row)} columns, expected {n}"
                )
            row_sum = sum(row)
            if abs(row_sum - 1.0) > 1e-6:
                raise ValueError(
                    f"Transition row {i} sums to {row_sum}, expected ~1.0"
                )

        if len(self._emission) != n:
            raise ValueError(
                f"Emission params has {len(self._emission)} entries, "
                f"expected {n}"
            )
        for i, (mu, sigma) in enumerate(self._emission):
            if sigma <= 0:
                raise ValueError(
                    f"Emission sigma for state {i} is {sigma}, must be > 0"
                )

    @property
    def state_names(self) -> Sequence[str]:
        return self._state_names

    @property
    def n_states(self) -> int:
        return self._n_states

    @property
    def calibrated(self) -> bool:
        """Whether emission parameters have been calibrated from data."""
        return self._calibrated

    def calibrate(self, quotes: Sequence[NBBOQuote]) -> bool:
        """Fit emission parameters from historical spread distribution.

        Partitions ``log(relative_spread)`` values into terciles and
        computes per-bucket mean and standard deviation.  Parameters
        are frozen after calibration — call before the first
        ``posterior()`` update.

        Returns True if calibration succeeded (enough valid samples),
        False if insufficient data (defaults are retained).
        """
        log_spreads: list[float] = []
        for q in quotes:
            spread = float(q.ask - q.bid)
            mid = float(q.ask + q.bid) / 2.0
            if spread > 0 and mid > 0:
                log_spreads.append(math.log(spread / mid))

        if len(log_spreads) < self._MIN_CALIBRATION_SAMPLES:
            return False

        log_spreads.sort()
        n = len(log_spreads)
        boundaries = [n // 3, 2 * n // 3]
        buckets = [
            log_spreads[:boundaries[0]],
            log_spreads[boundaries[0]:boundaries[1]],
            log_spreads[boundaries[1]:],
        ]

        fitted: list[tuple[float, float]] = []
        for bucket in buckets:
            mu = statistics.mean(bucket)
            sigma = max(
                statistics.stdev(bucket) if len(bucket) >= 2 else self._MIN_SIGMA,
                self._MIN_SIGMA,
            )
            fitted.append((mu, sigma))

        self._emission = tuple(fitted)
        self._calibrated = True
        self._posteriors.clear()
        self._last_update_seq.clear()
        return True

    def posterior(self, quote: NBBOQuote) -> list[float]:
        symbol = quote.symbol
        seq = quote.sequence

        if self._last_update_seq.get(symbol) == seq:
            return list(self._posteriors[symbol])

        self._last_update_seq[symbol] = seq

        prior = self._posteriors.get(symbol)
        if prior is None:
            prior = [1.0 / self._n_states] * self._n_states
            self._posteriors[symbol] = prior

        predicted = self._predict(prior)

        spread = float(quote.ask - quote.bid)
        mid = float(quote.ask + quote.bid) / 2.0

        if spread <= 0 or mid <= 0:
            self._posteriors[symbol] = predicted
            return list(predicted)

        rel_spread = spread / mid
        log_spread = math.log(max(rel_spread, 1e-12))

        likelihoods = self._emission_likelihood(log_spread)
        updated = self._bayes_update(predicted, likelihoods)

        if any(math.isnan(v) or math.isinf(v) for v in updated):
            updated = [1.0 / self._n_states] * self._n_states

        self._posteriors[symbol] = updated
        return list(updated)

    def current_state(self, symbol: str) -> list[float] | None:
        cached = self._posteriors.get(symbol)
        return list(cached) if cached is not None else None

    def reset(self, symbol: str) -> None:
        self._posteriors.pop(symbol, None)
        self._last_update_seq.pop(symbol, None)

    def checkpoint(self) -> bytes:
        payload: dict[str, object] = {
            "posteriors": self._posteriors,
            "last_update_seq": self._last_update_seq,
        }
        if self._calibrated:
            payload["emission"] = [list(pair) for pair in self._emission]
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def restore(self, data: bytes) -> None:
        try:
            payload = json.loads(data)
            posteriors = payload["posteriors"]
            last_seq = payload["last_update_seq"]
            if not isinstance(posteriors, dict) or not isinstance(last_seq, dict):
                raise ValueError("Invalid checkpoint structure")
            for sym, post in posteriors.items():
                if len(post) != self._n_states:
                    raise ValueError(
                        f"Posterior length mismatch for {sym}: "
                        f"{len(post)} vs {self._n_states}"
                    )
            self._posteriors = {k: list(v) for k, v in posteriors.items()}
            self._last_update_seq = {k: int(v) for k, v in last_seq.items()}

            emission_data = payload.get("emission")
            if emission_data is not None:
                if len(emission_data) != self._n_states:
                    raise ValueError(
                        f"Emission params length mismatch: "
                        f"{len(emission_data)} vs {self._n_states}"
                    )
                self._emission = tuple(
                    (float(pair[0]), float(pair[1])) for pair in emission_data
                )
                self._calibrated = True
        except Exception:
            self._posteriors = {}
            self._last_update_seq = {}
            raise

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
