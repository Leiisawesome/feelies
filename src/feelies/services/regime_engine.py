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
import logging
import math
import statistics
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

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

    Tick-time semantics
    -------------------

    The transition matrix is applied **once per inbound NBBOQuote**,
    not on a wall-clock grid.  The 0.99 self-transition probability
    therefore implies a mean dwell time of *ticks*, not seconds — and
    tick rates vary by orders of magnitude across the universe and
    across the trading day:

    * For a thin name at ~1 quote/sec, mean dwell ≈ 100 ticks ≈
      100 seconds, which is reasonable for an intraday regime.
    * For SPY at ~10⁴ quotes/sec, mean dwell ≈ 10 ms, which is far
      too fast — the engine will appear to switch regimes constantly.

    Practical implications:

    * Calibrate the transition matrix per deployment class (e.g.,
      slow / medium / fast tick-rate cohorts) by passing
      ``transition_matrix=`` at construction.  The default is tuned
      for a *medium* tick rate.
    * If your universe spans wildly different tick rates, consider
      either subsampling fast-tick names to a fixed wall-clock
      cadence before feeding them in, or registering a per-cohort
      engine via :func:`register_engine`.

    Emission parameters are also **log-relative-spread** based; they
    must be calibrated against representative historical quotes for
    the same universe.  Calling :meth:`posterior` without first
    calling :meth:`calibrate` (or constructing with explicit
    ``emission_params``) emits a one-shot warning — the built-in
    defaults are placeholders that will produce poor discrimination
    on real US-equity microstructure.
    """

    _DEFAULT_STATE_NAMES = ("compression_clustering", "normal", "vol_breakout")

    # Default transition matrix.  Per-tick application; see "Tick-time
    # semantics" in the class docstring for caveats.  Tuned for a
    # medium tick-rate cohort (~10–100 quotes/sec); recalibrate or
    # override per-deployment for slow/fast cohorts.
    _DEFAULT_TRANSITION = (
        (0.990, 0.008, 0.002),
        (0.005, 0.990, 0.005),
        (0.002, 0.008, 0.990),
    )

    # Emission: log-normal spread model — (mean_log_spread, std_log_spread)
    # over ``log(spread / mid)`` (i.e., log-relative spread).  These are
    # placeholder defaults; ``calibrate()`` should be called with
    # representative historical quotes before live use, otherwise the
    # one-shot uncalibrated warning fires from ``posterior()``.
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
        self._uncalibrated_warned: bool = False

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
            if any(v < 0 for v in row):
                raise ValueError(
                    f"Transition row {i} contains negative entries: {row}"
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
        k = self._n_states
        boundaries = [i * n // k for i in range(1, k)]
        bucket_edges = [0] + boundaries + [n]
        buckets = [
            log_spreads[bucket_edges[i]:bucket_edges[i + 1]]
            for i in range(k)
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

        self._check_emission_separation()
        return True

    def _check_emission_separation(self) -> None:
        """Log a warning when adjacent emission distributions overlap heavily.

        Uses the Gaussian separability index d = |mu_i - mu_j| / sqrt(s_i^2 + s_j^2)
        between each adjacent pair.  d < 0.5 means substantial overlap —
        the engine will update posteriors but provide weak discrimination
        between those two states.
        """
        for i in range(self._n_states - 1):
            mu_a, sigma_a = self._emission[i]
            mu_b, sigma_b = self._emission[i + 1]
            denom = math.sqrt(sigma_a ** 2 + sigma_b ** 2)
            if denom < 1e-12:
                continue
            separation = abs(mu_b - mu_a) / denom
            if separation < 0.5:
                logger.warning(
                    "regime_engine: weak emission separation between "
                    "state %d (%s) and state %d (%s): d=%.3f "
                    "(mu=%.3f,%.3f sigma=%.3f,%.3f) — posteriors will "
                    "have limited discriminative power",
                    i, self._state_names[i],
                    i + 1, self._state_names[i + 1],
                    separation, mu_a, mu_b, sigma_a, sigma_b,
                )

    def posterior(self, quote: NBBOQuote) -> list[float]:
        symbol = quote.symbol
        seq = quote.sequence

        if self._last_update_seq.get(symbol) == seq:
            return list(self._posteriors[symbol])

        if not self._calibrated and not self._uncalibrated_warned:
            logger.warning(
                "regime_engine: posterior() called before calibrate(); "
                "running with %s default emission parameters — these are "
                "likely inappropriate for typical US-equity log-relative "
                "spreads and will produce poor discrimination. Call "
                "calibrate() with historical quotes first.",
                type(self).__name__,
            )
            self._uncalibrated_warned = True

        prior = self._posteriors.get(symbol)
        if prior is None:
            prior = [1.0 / self._n_states] * self._n_states

        predicted = self._predict(prior)

        spread = float(quote.ask - quote.bid)
        mid = float(quote.ask + quote.bid) / 2.0

        if spread <= 0 or mid <= 0:
            updated: list[float] = predicted
        else:
            rel_spread = spread / mid
            log_spread = math.log(max(rel_spread, 1e-12))

            likelihoods = self._emission_likelihood(log_spread)
            updated = self._bayes_update(predicted, likelihoods)

            if any(math.isnan(v) or math.isinf(v) for v in updated):
                logger.warning(
                    "regime_engine: NaN/inf in Bayesian update for symbol=%s; "
                    "posteriors=%s likelihoods=%s — resetting to uniform prior",
                    symbol, updated, likelihoods,
                )
                updated = [1.0 / self._n_states] * self._n_states

        # Commit the new posterior and seq watermark together.  Doing
        # this only after the update fully succeeds means an exception
        # mid-update leaves both ``_posteriors[symbol]`` and
        # ``_last_update_seq[symbol]`` untouched — the next call sees
        # the previous tick's posterior with a non-matching seq, and
        # re-runs the update rather than returning a phantom-cached
        # value.
        self._posteriors[symbol] = updated
        self._last_update_seq[symbol] = seq
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
                if any(v < 0 for v in post):
                    raise ValueError(
                        f"Negative posterior value for {sym}: {post}"
                    )
                if abs(sum(post) - 1.0) > 1e-6:
                    raise ValueError(
                        f"Posteriors for {sym} sum to {sum(post)}, "
                        f"expected ~1.0"
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
                parsed_emission = []
                for i, pair in enumerate(emission_data):
                    mu, sigma = float(pair[0]), float(pair[1])
                    if sigma <= 0:
                        raise ValueError(
                            f"Restored emission sigma for state {i} "
                            f"is {sigma}, must be > 0"
                        )
                    parsed_emission.append((mu, sigma))
                self._emission = tuple(parsed_emission)
                self._calibrated = True
        except Exception:
            self._posteriors = {}
            self._last_update_seq = {}
            raise

    def _predict(self, prior: list[float]) -> list[float]:
        """Compute predicted state via transition matrix, then renormalize.

        The matrix-vector product preserves unit sum in exact arithmetic
        but accumulates ~7e-16 float drift per step.  In the normal path
        ``_bayes_update`` renormalizes, but the locked-market path
        (spread <= 0) stores the prediction directly.  Renormalizing here
        prevents drift from accumulating across consecutive prediction-only
        steps (common in illiquid names or pre-market).
        """
        predicted = [0.0] * self._n_states
        for j in range(self._n_states):
            for i in range(self._n_states):
                predicted[j] += self._transition[i][j] * prior[i]
        total = sum(predicted)
        if total > 0:
            return [p / total for p in predicted]
        return [1.0 / self._n_states] * self._n_states

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

_ENGINE_REGISTRY: dict[str, type[RegimeEngine]] = {
    "hmm_3state_fractional": HMM3StateFractional,
}


def register_engine(name: str, engine_cls: type[RegimeEngine]) -> None:
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
    return cls(**kwargs)
