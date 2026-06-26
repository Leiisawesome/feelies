"""Regime engine — platform-provided online regime filtering services.

The :class:`RegimeEngine` protocol defines the contract for per-symbol
stateful regime posteriors (typically driven by NBBO-derived features).
Alpha specs may reference an engine by name in YAML; :class:`AlphaLoader`
and bootstrap resolve registry implementations and inject them into
evaluation namespaces.

The risk engine also consumes :class:`RegimeEngine` for regime-aware
position sizing and drawdown gating.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
from collections import deque
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

from feelies.core.events import NBBOQuote


def regime_posterior_entropy_nats(posteriors: Sequence[float]) -> float:
    """Shannon entropy (nats) of a categorical posterior ``p``.

    Non-finite and negative components are treated as zero mass, then
    the vector is renormalized to a simplex before computing ``H``.
    ``0`` is returned when there is no positive mass (degenerate /
    empty input).  A peaked distribution has entropy near ``0``; a
    diffuse distribution has higher entropy.
    """
    cleaned: list[float] = []
    for p in posteriors:
        x = float(p)
        if math.isnan(x) or math.isinf(x):
            cleaned.append(0.0)
        else:
            cleaned.append(max(0.0, x))
    total = sum(cleaned)
    if total <= 0.0:
        return 0.0
    h = 0.0
    for p in cleaned:
        q = p / total
        if q > 0.0:
            h -= q * math.log(q)
    return h


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

        Replaces all per-symbol state.  On failure, implementations must
        not leave a half-applied checkpoint visible: either roll back to
        the pre-call snapshot (as :class:`HMM3StateFractional` does for
        posteriors and emission parameters) or reset to an empty cold
        start.  Constructor flags are not part of the blob.
        """
        ...


# ── HMM 3-State Fractional implementation ───────────────────────────


class HMM3StateFractional:
    """Built-in 3-state online regime filter on log-relative spread.

      Despite the historical registry name ``hmm_3state_fractional``, the
      implementation is a **fixed-structure discrete-time forward filter**
      (Markov prediction + diagonal Gaussian emissions), **not** a full
      Baum–Welch / EM HMM fit: :meth:`calibrate` fits emission moments from
      spread quantiles (optionally per symbol), while the transition matrix
      stays author-controlled unless time scaling reshapes it.

      States (indices after :meth:`calibrate` with
      ``order_emissions_by_increasing_mean=True``):
        0 — tightest log-relative-spread tercile
        1 — middle tercile
        2 — widest tercile

      The default ``state_names`` (``compression_clustering``, ``normal``,
      ``vol_breakout``) are **registry labels** for risk scaling and YAML
      ``P(...)`` gates — they are **not** re-derived from data.  After
      calibration, index ``i`` always maps to the *i*-th emission sorted by
    increasing spread mean, which may not match the English name's intuition.

      Tick-time semantics
      -------------------

      By default the transition matrix is applied **once per inbound
      NBBOQuote** with no wall-clock adjustment, so mean dwell is in
      *ticks* (see historical caveat in platform docs).  Enable
      ``transition_time_scaling_enabled`` to re-exponentiate each row's
      self-transition by ``p_stay ** (Δt / dt_reference)`` so bursty vs
      sparse quote streams share comparable **per-second** mixing when
      ``dt_reference`` is tuned to the deployment cohort.

      Emission parameters are **log-relative-spread** based; call
      :meth:`calibrate` with representative quotes (or pass explicit
      ``emission_params``) before relying on posteriors in production.
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
    _CHECKPOINT_SCHEMA_VERSION = 2
    # Audit P1 E-1: when the schema version is bumped, also update the
    # restore() compatibility branch so old blobs still load (or fail
    # with a clear migration error).  v1 had no ``flags_fingerprint``;
    # v2 carries one and uses it to reject restores into a differently-
    # configured engine.

    def __init__(
        self,
        state_names: Sequence[str] | None = None,
        transition_matrix: Sequence[Sequence[float]] | None = None,
        emission_params: Sequence[tuple[float, float]] | None = None,
        *,
        transition_time_scaling_enabled: bool = False,
        transition_dt_reference_seconds: float = 0.05,
        transition_dt_scale_min: float = 0.01,
        transition_dt_scale_max: float = 40.0,
        per_symbol_calibration: bool = False,
        order_emissions_by_increasing_mean: bool = True,
        enforce_min_pairwise_emission_separation: bool = False,
        min_pairwise_emission_separation: float = 0.5,
    ) -> None:
        self._state_names = tuple(state_names or self._DEFAULT_STATE_NAMES)
        self._n_states = len(self._state_names)
        self._transition = tuple(
            tuple(row) for row in (transition_matrix or self._DEFAULT_TRANSITION)
        )
        self._emission = tuple(emission_params or self._DEFAULT_EMISSION)
        self._calibrated = emission_params is not None
        self._transition_time_scaling_enabled = transition_time_scaling_enabled
        self._transition_dt_reference_seconds = transition_dt_reference_seconds
        self._transition_dt_scale_min = transition_dt_scale_min
        self._transition_dt_scale_max = transition_dt_scale_max
        self._per_symbol_calibration = per_symbol_calibration
        self._order_emissions_by_increasing_mean = order_emissions_by_increasing_mean
        self._enforce_min_pairwise_emission_separation = enforce_min_pairwise_emission_separation
        self._min_pairwise_emission_separation = min_pairwise_emission_separation

        if self._transition_dt_reference_seconds <= 0:
            raise ValueError(
                "transition_dt_reference_seconds must be positive, got "
                f"{self._transition_dt_reference_seconds}"
            )
        if self._transition_dt_scale_min <= 0 or self._transition_dt_scale_max <= 0:
            raise ValueError("transition_dt scale bounds must be positive")
        if self._transition_dt_scale_min > self._transition_dt_scale_max:
            raise ValueError("transition_dt_scale_min must be <= transition_dt_scale_max")
        if self._min_pairwise_emission_separation <= 0:
            raise ValueError("min_pairwise_emission_separation must be positive")

        self._validate_params()
        self._posteriors: dict[str, list[float]] = {}
        self._last_update_seq: dict[str, int] = {}
        self._last_quote_ts_ns: dict[str, int] = {}
        self._emission_by_symbol: dict[str, tuple[tuple[float, float], ...]] = {}
        self._uncalibrated_warned: bool = False
        self._scaled_transition_cache: tuple[float, tuple[tuple[float, ...], ...]] | None = None

    def _validate_params(self) -> None:
        n = self._n_states
        if n < 2:
            raise ValueError(f"Need at least 2 states, got {n}")

        if len(self._transition) != n:
            raise ValueError(f"Transition matrix has {len(self._transition)} rows, expected {n}")
        for i, row in enumerate(self._transition):
            if len(row) != n:
                raise ValueError(f"Transition row {i} has {len(row)} columns, expected {n}")
            if any(v < 0 for v in row):
                raise ValueError(f"Transition row {i} contains negative entries: {row}")
            row_sum = sum(row)
            if abs(row_sum - 1.0) > 1e-6:
                raise ValueError(f"Transition row {i} sums to {row_sum}, expected ~1.0")

        if len(self._emission) != n:
            raise ValueError(f"Emission params has {len(self._emission)} entries, expected {n}")
        for i, (mu, sigma) in enumerate(self._emission):
            if sigma <= 0:
                raise ValueError(f"Emission sigma for state {i} is {sigma}, must be > 0")

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

    @property
    def discriminability(self) -> float:
        """Calibration-time min pairwise emission separation ``d`` (audit R-1).

        ``d_min = min_{i<j} |mu_i - mu_j| / sqrt(sigma_i^2 + sigma_j^2)`` over
        the *current* (pooled) emissions.  It measures whether the states are
        statistically distinguishable at all: ``d >= ~0.5`` is usable, ``d → 0``
        means the quantile-fit Gaussians have collapsed to near-identical
        distributions (a tight, stable spread), so the posterior is uniform
        noise and ``P(state)`` carries no information.  Consumers compare it
        against a floor and fail regime-gates safe to OFF below it.  This is
        *orthogonal* to :attr:`calibrated`: placeholder (uncalibrated)
        emissions are well-separated yet mis-located, so they score high here
        but are caught by ``calibrated=False`` instead.  ``+inf`` for a
        single-state engine (no pair to compare).

        Reports the *pooled* fit only.  When ``per_symbol_calibration`` is
        enabled, callers that need to gate per symbol must use
        :meth:`discriminability_for_symbol` instead — otherwise a tight
        symbol whose per-symbol fit has collapsed could be gated against the
        global ``d`` and pass falsely (audit R-1 fail-safe)."""
        return self._compute_min_pairwise_emission_separation(self._emission)

    def discriminability_for_symbol(self, symbol: str) -> float:
        """Per-symbol counterpart of :attr:`discriminability` (audit R-1).

        Mirrors the emission-resolution rule used by :meth:`posterior` /
        :meth:`_emission_for_symbol`: returns the min pairwise separation
        of the symbol's per-symbol calibrated emissions when present, or
        of the pooled global emissions otherwise.  This is the quantity
        consumers must compare to ``regime_min_discriminability`` so the
        regime-gate fails safe to OFF for a symbol whose per-symbol fit
        has collapsed even while the pooled fit remains well separated.
        """
        return self._compute_min_pairwise_emission_separation(self._emission_for_symbol(symbol))

    def calibrate(self, quotes: Sequence[NBBOQuote]) -> bool:
        """Fit emission parameters from historical spread distribution.

        Partitions ``log(relative_spread)`` values into quantile buckets
        (one per state) and fits a Gaussian per bucket.  When
        ``per_symbol_calibration`` is enabled, symbols with enough quotes
        receive their own emission triple; others fall back to the
        pooled global fit.

        Returns True if calibration succeeded (enough valid samples and
        optional pairwise-separation gate), False otherwise.
        """
        sym_logs: list[tuple[str, float]] = []
        for q in quotes:
            spread = float(q.ask - q.bid)
            mid = float(q.ask + q.bid) / 2.0
            if spread > 0 and mid > 0:
                sym_logs.append((q.symbol, math.log(spread / mid)))

        if len(sym_logs) < self._MIN_CALIBRATION_SAMPLES:
            return False

        all_sorted = sorted(v for _, v in sym_logs)
        global_fit = self._fit_quantile_emissions_from_sorted(all_sorted)
        if global_fit is None:
            return False

        if self._order_emissions_by_increasing_mean:
            global_fit = self._sort_emissions_by_mean(global_fit)

        if not self._emissions_pass_pairwise_gate(global_fit):
            # Audit P2 E-4: with the separation gate enabled, a poorly-
            # separated calibration would previously leave the engine
            # uncalibrated forever (calibrate() returned False).  That's
            # safe but operationally hostile — every subsequent posterior
            # call fires the uncalibrated warning and the engine runs on
            # placeholder defaults.  Soft-fail instead: warn, keep the
            # constructor defaults but mark them as the "fallback after
            # rejected calibration" so the caller can decide.  Return
            # False so the bootstrap calibration log still says
            # "calibration failed", but leave the engine in a sane state.
            logger.warning(
                "regime_engine: calibration produced emissions that "
                "failed the pairwise-separation gate (min d < %.4f); "
                "retaining constructor-default emissions.  Either "
                "supply better calibration data, lower "
                "min_pairwise_emission_separation, or disable "
                "enforce_min_pairwise_emission_separation.",
                self._min_pairwise_emission_separation,
            )
            return False

        self._emission = global_fit
        self._emission_by_symbol = {}
        if self._per_symbol_calibration:
            by_sym: dict[str, list[float]] = {}
            for sym, v in sym_logs:
                by_sym.setdefault(sym, []).append(v)
            for sym, vals in by_sym.items():
                if len(vals) < self._MIN_CALIBRATION_SAMPLES:
                    continue
                srt = sorted(vals)
                per = self._fit_quantile_emissions_from_sorted(srt)
                if per is None:
                    continue
                if self._order_emissions_by_increasing_mean:
                    per = self._sort_emissions_by_mean(per)
                if not self._emissions_pass_pairwise_gate(per):
                    logger.warning(
                        "regime_engine: per-symbol calibration skipped for "
                        "symbol=%s — pairwise emission separation gate failed "
                        "(falling back to global emissions for this symbol)",
                        sym,
                    )
                    continue
                self._emission_by_symbol[sym] = per

        self._calibrated = True
        self._posteriors.clear()
        self._last_update_seq.clear()
        self._last_quote_ts_ns.clear()
        self._scaled_transition_cache = None

        self._check_emission_separation()
        return True

    def _fit_quantile_emissions_from_sorted(
        self, log_spreads_sorted: list[float]
    ) -> tuple[tuple[float, float], ...] | None:
        n = len(log_spreads_sorted)
        k = self._n_states
        if n < self._MIN_CALIBRATION_SAMPLES:
            return None
        boundaries = [i * n // k for i in range(1, k)]
        bucket_edges = [0] + boundaries + [n]
        buckets = [log_spreads_sorted[bucket_edges[i] : bucket_edges[i + 1]] for i in range(k)]
        fitted: list[tuple[float, float]] = []
        for bucket in buckets:
            mu = statistics.mean(bucket)
            sigma = max(
                statistics.stdev(bucket) if len(bucket) >= 2 else self._MIN_SIGMA,
                self._MIN_SIGMA,
            )
            fitted.append((mu, sigma))
        return tuple(fitted)

    @staticmethod
    def _sort_emissions_by_mean(
        emission: Sequence[tuple[float, float]],
    ) -> tuple[tuple[float, float], ...]:
        """Order (mu, sigma) by increasing *mu* so state 0 is tightest spread."""
        return tuple(sorted(emission, key=lambda t: t[0]))

    def _pairwise_separation_index(
        self,
        emission: Sequence[tuple[float, float]],
        i: int,
        j: int,
    ) -> float:
        mu_a, sigma_a = emission[i]
        mu_b, sigma_b = emission[j]
        denom = math.sqrt(sigma_a**2 + sigma_b**2)
        if denom < 1e-12:
            return 0.0
        return abs(mu_b - mu_a) / denom

    def _compute_min_pairwise_emission_separation(
        self, emission: Sequence[tuple[float, float]]
    ) -> float:
        k = len(emission)
        if k < 2:
            return float("inf")
        best = float("inf")
        for i in range(k):
            for j in range(i + 1, k):
                best = min(best, self._pairwise_separation_index(emission, i, j))
        return best

    def _emissions_pass_pairwise_gate(
        self,
        emission: Sequence[tuple[float, float]],
    ) -> bool:
        if not self._enforce_min_pairwise_emission_separation:
            return True
        min_d = self._compute_min_pairwise_emission_separation(emission)
        if min_d < self._min_pairwise_emission_separation:
            logger.warning(
                "regime_engine: calibration rejected — min pairwise emission "
                "separation d_min=%.4f is below required %.4f "
                "(enforce_min_pairwise_emission_separation=True)",
                min_d,
                self._min_pairwise_emission_separation,
            )
            return False
        return True

    def _check_emission_separation(self) -> None:
        """Log warnings when Gaussian emissions overlap (all pairs + adjacent)."""
        k = self._n_states
        for i in range(k):
            for j in range(i + 1, k):
                separation = self._pairwise_separation_index(self._emission, i, j)
                if separation < 0.5:
                    logger.warning(
                        "regime_engine: weak emission separation between "
                        "state %d (%s) and state %d (%s): d=%.3f "
                        "(mu=%.3f,%.3f sigma=%.3f,%.3f) — posteriors will "
                        "have limited discriminative power",
                        i,
                        self._state_names[i],
                        j,
                        self._state_names[j],
                        separation,
                        self._emission[i][0],
                        self._emission[j][0],
                        self._emission[i][1],
                        self._emission[j][1],
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

        transition = self._transition_for_step(symbol, quote.timestamp_ns)
        predicted = self._predict_with_matrix(prior, transition)

        spread = float(quote.ask - quote.bid)
        mid = float(quote.ask + quote.bid) / 2.0

        if spread <= 0 or mid <= 0:
            updated: list[float] = predicted
        else:
            rel_spread = spread / mid
            log_spread = math.log(max(rel_spread, 1e-12))

            likelihoods = self._emission_likelihood_for_symbol(symbol, log_spread)
            updated = self._bayes_update(predicted, likelihoods)

            if any(math.isnan(v) or math.isinf(v) for v in updated):
                logger.warning(
                    "regime_engine: NaN/inf in Bayesian update for symbol=%s; "
                    "posteriors=%s likelihoods=%s — resetting to uniform prior",
                    symbol,
                    updated,
                    likelihoods,
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
        self._last_quote_ts_ns[symbol] = quote.timestamp_ns
        return list(updated)

    def current_state(self, symbol: str) -> list[float] | None:
        cached = self._posteriors.get(symbol)
        return list(cached) if cached is not None else None

    def reset(self, symbol: str) -> None:
        self._posteriors.pop(symbol, None)
        self._last_update_seq.pop(symbol, None)
        self._last_quote_ts_ns.pop(symbol, None)

    def _flags_fingerprint(self) -> str:
        """Stable hash of the constructor flags that change posteriors.

        Audit P1 E-1: every flag that materially changes how
        :meth:`posterior` computes its update is canonicalized into a
        single short string.  Two engines that share this fingerprint
        produce identical posterior trajectories given identical
        quotes (modulo emission/transition values that *are* in the
        blob).  Two engines that disagree on it would silently diverge
        — :meth:`restore` rejects the blob in that case.

        The state-names tuple is included because the published
        ``dominant_name`` (and therefore downstream gate / risk
        decisions) is indexed by it.  The transition matrix itself is
        included because it is constructor-frozen (not in the blob).
        """
        canonical = {
            "schema": self._CHECKPOINT_SCHEMA_VERSION,
            "n_states": self._n_states,
            "state_names": list(self._state_names),
            "transition": [list(row) for row in self._transition],
            "transition_time_scaling_enabled": (bool(self._transition_time_scaling_enabled)),
            "transition_dt_reference_seconds": float(self._transition_dt_reference_seconds),
            "transition_dt_scale_min": float(self._transition_dt_scale_min),
            "transition_dt_scale_max": float(self._transition_dt_scale_max),
            "per_symbol_calibration": bool(self._per_symbol_calibration),
            "order_emissions_by_increasing_mean": (bool(self._order_emissions_by_increasing_mean)),
            "enforce_min_pairwise_emission_separation": (
                bool(self._enforce_min_pairwise_emission_separation)
            ),
            "min_pairwise_emission_separation": float(self._min_pairwise_emission_separation),
        }
        raw = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def checkpoint(self) -> bytes:
        """Serialize per-symbol filter state to JSON bytes.

        The blob carries posteriors, sequence watermarks, optional
        calibrated emissions, per-symbol emissions, last quote
        timestamps for time-scaled transitions, and a fingerprint of
        the constructor flags / transition matrix.

        Audit P1 E-1: previously, constructor flags were not part of
        the blob and :meth:`restore` made no attempt to verify them.
        Restoring into a differently-configured engine (e.g. with
        ``transition_time_scaling_enabled`` flipped or a different
        transition matrix) therefore silently diverged replay.  The
        ``flags_fingerprint`` field added in schema v2 lets
        :meth:`restore` detect and reject the mismatch up front.
        """
        payload: dict[str, object] = {
            "checkpoint_schema_version": self._CHECKPOINT_SCHEMA_VERSION,
            "flags_fingerprint": self._flags_fingerprint(),
            "posteriors": self._posteriors,
            "last_update_seq": self._last_update_seq,
            "last_quote_ts_ns": self._last_quote_ts_ns,
        }
        if self._calibrated:
            payload["emission"] = [list(pair) for pair in self._emission]
        if self._emission_by_symbol:
            payload["emission_by_symbol"] = {
                sym: [list(pair) for pair in pairs]
                for sym, pairs in self._emission_by_symbol.items()
            }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def restore(self, data: bytes) -> None:
        """Restore state from :meth:`checkpoint` JSON.

        On failure, rolls back in-memory posteriors, watermarks, and
        per-symbol emission maps, restores ``_emission`` / ``_calibrated``
        to their pre-call values, then re-raises.  Constructor flags are
        not stored in the blob — use the same engine configuration as the
        producer when restoring for deterministic replay.
        """
        prev_emission = self._emission
        prev_calibrated = self._calibrated
        prev_emission_by_symbol = self._emission_by_symbol
        try:
            payload = json.loads(data)
            schema_raw = payload.get("checkpoint_schema_version")
            schema_v = 1
            if schema_raw is not None:
                schema_v = int(schema_raw)
                if schema_v > self._CHECKPOINT_SCHEMA_VERSION:
                    raise ValueError(
                        f"Unsupported checkpoint_schema_version {schema_v} "
                        f"(engine supports <= {self._CHECKPOINT_SCHEMA_VERSION})"
                    )
            # Audit P1 E-1: schema v2 carries ``flags_fingerprint``; v1
            # blobs predate the check and are accepted without it (with
            # a one-shot warning) so existing checkpoints keep loading
            # — but new checkpoints (v2+) MUST match the current
            # engine's flags or the restore is rejected.
            blob_fingerprint = payload.get("flags_fingerprint")
            if blob_fingerprint is None:
                if schema_v >= 2:
                    raise ValueError(
                        "checkpoint at schema_version "
                        f"{schema_v} is missing 'flags_fingerprint'; "
                        "blob is malformed"
                    )
                logger.warning(
                    "regime_engine: restoring legacy checkpoint "
                    "(schema_version=%d) without flags_fingerprint; "
                    "this engine cannot verify that the producer's "
                    "constructor flags match — replay determinism is "
                    "not guaranteed",
                    schema_v,
                )
            else:
                current = self._flags_fingerprint()
                if blob_fingerprint != current:
                    raise ValueError(
                        "checkpoint flags_fingerprint mismatch: "
                        f"blob={blob_fingerprint} engine={current} — "
                        "the engine restoring this checkpoint must be "
                        "constructed with identical state_names, "
                        "transition matrix, and *_enabled flags as the "
                        "engine that produced it; otherwise replay is "
                        "not deterministic"
                    )
            posteriors = payload["posteriors"]
            last_seq = payload["last_update_seq"]
            if not isinstance(posteriors, dict) or not isinstance(last_seq, dict):
                raise ValueError("Invalid checkpoint structure")
            for sym, post in posteriors.items():
                if len(post) != self._n_states:
                    raise ValueError(
                        f"Posterior length mismatch for {sym}: {len(post)} vs {self._n_states}"
                    )
                if any(v < 0 for v in post):
                    raise ValueError(f"Negative posterior value for {sym}: {post}")
                if abs(sum(post) - 1.0) > 1e-6:
                    raise ValueError(f"Posteriors for {sym} sum to {sum(post)}, expected ~1.0")
            self._posteriors = {k: list(v) for k, v in posteriors.items()}
            self._last_update_seq = {k: int(v) for k, v in last_seq.items()}

            last_ts_raw = payload.get("last_quote_ts_ns")
            if last_ts_raw is None:
                self._last_quote_ts_ns = {}
            elif not isinstance(last_ts_raw, dict):
                raise ValueError("last_quote_ts_ns must be a dict when present")
            else:
                self._last_quote_ts_ns = {k: int(v) for k, v in last_ts_raw.items()}

            self._emission_by_symbol = {}

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
                            f"Restored emission sigma for state {i} is {sigma}, must be > 0"
                        )
                    parsed_emission.append((mu, sigma))
                self._emission = tuple(parsed_emission)
                self._calibrated = True

            ebs = payload.get("emission_by_symbol")
            if ebs is not None:
                if not isinstance(ebs, dict):
                    raise ValueError("emission_by_symbol must be a dict")
                parsed_ebs: dict[str, tuple[tuple[float, float], ...]] = {}
                for sym, rows in ebs.items():
                    if len(rows) != self._n_states:
                        raise ValueError(f"emission_by_symbol[{sym!r}] length mismatch")
                    sym_pairs: list[tuple[float, float]] = []
                    for i, pair in enumerate(rows):
                        mu, sigma = float(pair[0]), float(pair[1])
                        if sigma <= 0:
                            raise ValueError(f"Restored sigma for {sym}[{i}] invalid")
                        sym_pairs.append((mu, sigma))
                    parsed_ebs[str(sym)] = tuple(sym_pairs)
                self._emission_by_symbol = parsed_ebs
            self._scaled_transition_cache = None
        except Exception:
            self._posteriors = {}
            self._last_update_seq = {}
            self._last_quote_ts_ns = {}
            self._emission_by_symbol = prev_emission_by_symbol
            self._emission = prev_emission
            self._calibrated = prev_calibrated
            self._scaled_transition_cache = None
            raise

    def _transition_for_step(
        self, symbol: str, timestamp_ns: int
    ) -> tuple[tuple[float, ...], ...]:
        """Effective row-stochastic transition for this quote's wall-clock step."""
        if not self._transition_time_scaling_enabled:
            return self._transition
        last_ns = self._last_quote_ts_ns.get(symbol)
        if last_ns is None:
            scale = 1.0
        else:
            dt = max(0.0, (timestamp_ns - last_ns) / 1e9)
            raw = dt / self._transition_dt_reference_seconds
            scale = max(
                self._transition_dt_scale_min,
                min(self._transition_dt_scale_max, raw),
            )
        cache = self._scaled_transition_cache
        if cache is not None and cache[0] == scale:
            return cache[1]
        matrix = self._scale_transition_matrix(scale)
        self._scaled_transition_cache = (scale, matrix)
        return matrix

    def _scale_transition_matrix(self, scale: float) -> tuple[tuple[float, ...], ...]:
        """Raise diagonal self-transition mass toward 1 when *scale* is small."""
        if math.isnan(scale) or math.isinf(scale) or scale <= 0.0:
            scale = 1e-12
        n = self._n_states
        out_rows: list[list[float]] = []
        for i in range(n):
            row = self._transition[i]
            p_stay = min(1.0 - 1e-12, max(1e-12, float(row[i])))
            p_stay_new = min(1.0 - 1e-12, max(1e-12, p_stay**scale))
            off_sum = sum(float(row[j]) for j in range(n) if j != i)
            new_row = [0.0] * n
            new_row[i] = p_stay_new
            if off_sum > 1e-12:
                factor = (1.0 - p_stay_new) / off_sum
                for j in range(n):
                    if j != i:
                        new_row[j] = float(row[j]) * factor
            elif n > 1:
                fill = (1.0 - p_stay_new) / (n - 1)
                for j in range(n):
                    if j != i:
                        new_row[j] = fill
            total = sum(new_row)
            if total <= 0:
                orig = [float(x) for x in self._transition[i]]
                tot2 = sum(orig)
                if tot2 <= 0.0:
                    new_row = [1.0 / n] * n
                else:
                    new_row = [x / tot2 for x in orig]
            else:
                new_row = [x / total for x in new_row]
            out_rows.append(new_row)
        return tuple(tuple(r) for r in out_rows)

    def _emission_for_symbol(self, symbol: str) -> tuple[tuple[float, float], ...]:
        per = self._emission_by_symbol.get(symbol)
        if per is not None:
            return per
        return self._emission

    def _predict_with_matrix(
        self,
        prior: list[float],
        transition: tuple[tuple[float, ...], ...],
    ) -> list[float]:
        """Markov prediction then renormalize (drift-safe for prediction-only paths)."""
        predicted = [0.0] * self._n_states
        for j in range(self._n_states):
            for i in range(self._n_states):
                predicted[j] += transition[i][j] * prior[i]
        total = sum(predicted)
        if total > 0:
            return [p / total for p in predicted]
        return [1.0 / self._n_states] * self._n_states

    def _emission_likelihood_for_symbol(self, symbol: str, log_spread: float) -> list[float]:
        likelihoods = []
        for mu, sigma in self._emission_for_symbol(symbol):
            z = (log_spread - mu) / sigma
            ll = math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))
            likelihoods.append(max(ll, 1e-300))
        return likelihoods

    def _bayes_update(self, predicted: list[float], likelihoods: list[float]) -> list[float]:
        unnorm = [p * l for p, l in zip(predicted, likelihoods)]
        total = sum(unnorm)
        if total < 1e-300:
            return [1.0 / self._n_states] * self._n_states
        return [u / total for u in unnorm]


# ── HMM 3-State 2-D spread+vol implementation (audit R-3) ────────────


class HMM3StateSpreadVol:
    """Opt-in 3-state forward filter on **two** L1 observations: log-relative
    spread *and* short-window realized volatility of the mid (audit R-3).

    Why
    ---
    The default :class:`HMM3StateFractional` observes only log-relative
    spread, so its three states are just spread terciles and ``vol_breakout``
    means *widest spread*, not *high volatility* — it cannot see volatility
    that arrives without spread widening (audit 2026-06-13 §3.2, §7).  This
    engine adds a second, near-orthogonal dimension — realized vol of the mid
    over a rolling window of quotes — and fits a 2-D diagonal-Gaussian
    emission per state, with states ordered by **increasing realized-vol
    mean**, so ``vol_breakout`` is genuinely the high-volatility regime.

    Design / safety
    ---------------
    * **Opt-in, default-off.**  Selected only via ``regime_engine:
      hmm_3state_spread_vol``; the default deployment and every locked
      determinism baseline keep using :class:`HMM3StateFractional` unchanged.
    * Still a **fixed-structure forward filter** (Markov predict + diagonal
      Gaussian emission), *not* a Baum–Welch / EM HMM.  :meth:`calibrate`
      fits per-state moments from realized-vol quantile buckets; the
      transition matrix is author-controlled.
    * **Deterministic** (Inv-5): realized vol is computed from a fixed-count
      rolling window of mids in sequence order; no wall-clock.  Idempotent per
      ``(symbol, sequence)`` like the default engine.
    * Realized vol needs warm-up (``rv_min_returns`` returns).  Until warm the
      vol dimension contributes likelihood ``1.0`` (the filter degrades to
      spread-only), so cold starts never crash.
    * Exposes the same :attr:`discriminability` contract (audit R-1) — the
      joint min pairwise separation across both dimensions — so the gate's
      indiscriminate-regime fail-safe works unchanged.

    Validation gate (the hard lesson of this audit): no alpha should switch
    its ``regime_engine`` to this until ``scripts/regime_diagnostics.py`` shows
    its conditional forward-return tables are at least as informative as the
    spread-only engine on the target cohort.
    """

    _DEFAULT_STATE_NAMES = ("compression_clustering", "normal", "vol_breakout")

    _DEFAULT_TRANSITION = (
        (0.990, 0.008, 0.002),
        (0.005, 0.990, 0.005),
        (0.002, 0.008, 0.990),
    )

    # Per state: ((mu_log_spread, sigma), (mu_log_realized_vol, sigma)).
    # Placeholder defaults ordered by increasing realized vol; ``calibrate()``
    # replaces them.  Uncalibrated use publishes ``calibrated=False`` so the
    # gate fails safe to OFF (audit P0-1), exactly like the default engine.
    _DEFAULT_EMISSION = (
        ((-4.5, 0.3), (-9.5, 1.0)),  # compression: tight spread, low vol
        ((-3.5, 0.5), (-8.5, 1.0)),  # normal
        ((-2.5, 0.7), (-7.5, 1.0)),  # vol_breakout: high vol
    )

    _MIN_SIGMA = 0.01
    _MIN_RV = 1e-12
    _MIN_CALIBRATION_SAMPLES = 30
    _CHECKPOINT_SCHEMA_VERSION = 1

    def __init__(
        self,
        state_names: Sequence[str] | None = None,
        transition_matrix: Sequence[Sequence[float]] | None = None,
        emission_params: Sequence[tuple[tuple[float, float], tuple[float, float]]] | None = None,
        *,
        rv_window: int = 30,
        rv_min_returns: int = 5,
    ) -> None:
        self._state_names = tuple(state_names or self._DEFAULT_STATE_NAMES)
        self._n_states = len(self._state_names)
        self._transition = tuple(
            tuple(float(x) for x in row) for row in (transition_matrix or self._DEFAULT_TRANSITION)
        )
        self._emission = tuple(emission_params or self._DEFAULT_EMISSION)
        self._calibrated = emission_params is not None
        if rv_window < 2:
            raise ValueError(f"rv_window must be >= 2, got {rv_window}")
        if not 2 <= rv_min_returns <= rv_window:
            raise ValueError(
                f"rv_min_returns must be in [2, rv_window]; got {rv_min_returns} (window {rv_window})"
            )
        self._rv_window = int(rv_window)
        self._rv_min_returns = int(rv_min_returns)
        self._validate_params()

        self._posteriors: dict[str, list[float]] = {}
        self._last_update_seq: dict[str, int] = {}
        # Rolling window of recent mids per symbol (maxlen = rv_window + 1 so we
        # retain ``rv_window`` consecutive log-returns).
        self._mid_window: dict[str, deque[float]] = {}
        self._uncalibrated_warned = False

    def _validate_params(self) -> None:
        n = self._n_states
        if n < 2:
            raise ValueError(f"Need at least 2 states, got {n}")
        if len(self._transition) != n:
            raise ValueError(f"Transition matrix has {len(self._transition)} rows, expected {n}")
        for i, row in enumerate(self._transition):
            if len(row) != n:
                raise ValueError(f"Transition row {i} has {len(row)} columns, expected {n}")
            if any(v < 0 for v in row):
                raise ValueError(f"Transition row {i} has negative entries: {row}")
            if abs(sum(row) - 1.0) > 1e-6:
                raise ValueError(f"Transition row {i} sums to {sum(row)}, expected ~1.0")
        if len(self._emission) != n:
            raise ValueError(f"Emission params has {len(self._emission)} entries, expected {n}")
        for i, dims in enumerate(self._emission):
            if len(dims) != 2:
                raise ValueError(f"Emission state {i} must have 2 dims (spread, vol)")
            for d, (_mu, sigma) in enumerate(dims):
                if sigma <= 0:
                    raise ValueError(f"Emission sigma state {i} dim {d} is {sigma}, must be > 0")

    @property
    def state_names(self) -> Sequence[str]:
        return self._state_names

    @property
    def n_states(self) -> int:
        return self._n_states

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def discriminability(self) -> float:
        """Joint min pairwise separation across both dimensions (audit R-1).

        ``d_ij = sqrt( sum_dim (mu_i - mu_j)^2 / (sig_i^2 + sig_j^2) )`` — the
        2-D generalisation of the spread-only separation; ``+inf`` for a
        single-state engine."""
        k = self._n_states
        if k < 2:
            return float("inf")
        best = float("inf")
        for i in range(k):
            for j in range(i + 1, k):
                acc = 0.0
                for (mu_i, sig_i), (mu_j, sig_j) in zip(self._emission[i], self._emission[j]):
                    denom = sig_i * sig_i + sig_j * sig_j
                    if denom > 1e-12:
                        acc += (mu_j - mu_i) ** 2 / denom
                best = min(best, math.sqrt(acc))
        return best

    # ── Realized-vol feature ────────────────────────────────────────

    def _push_mid_and_realized_vol(self, symbol: str, mid: float) -> float | None:
        """Append ``mid`` to the symbol window; return realized vol or None.

        Realized vol is the sample stdev of the consecutive log-returns within
        the rolling window (causal: includes only mids at or before this
        quote).  Returns ``None`` until ``rv_min_returns`` returns exist."""
        window = self._mid_window.get(symbol)
        if window is None:
            window = deque(maxlen=self._rv_window + 1)
            self._mid_window[symbol] = window
        window.append(mid)
        if len(window) < self._rv_min_returns + 1:
            return None
        mids = list(window)
        rets = [
            math.log(mids[i] / mids[i - 1])
            for i in range(1, len(mids))
            if mids[i] > 0.0 and mids[i - 1] > 0.0
        ]
        if len(rets) < self._rv_min_returns:
            return None
        return statistics.stdev(rets)

    def posterior(self, quote: NBBOQuote) -> list[float]:
        symbol = quote.symbol
        seq = quote.sequence
        if self._last_update_seq.get(symbol) == seq:
            return list(self._posteriors[symbol])

        if not self._calibrated and not self._uncalibrated_warned:
            logger.warning(
                "regime_engine: HMM3StateSpreadVol.posterior() called before "
                "calibrate(); running with placeholder 2-D emissions — "
                "RegimeState.calibrated will be False and P(state) gates fail "
                "safe to OFF.  Call calibrate() with historical quotes first."
            )
            self._uncalibrated_warned = True

        prior = self._posteriors.get(symbol)
        if prior is None:
            prior = [1.0 / self._n_states] * self._n_states
        predicted = self._predict(prior)

        spread = float(quote.ask - quote.bid)
        mid = float(quote.ask + quote.bid) / 2.0

        # Always advance the realized-vol window (so the next tick is warm),
        # even on an invalid spread — the mid is still informative.
        rv = self._push_mid_and_realized_vol(symbol, mid) if mid > 0 else None

        if spread <= 0 or mid <= 0:
            updated: list[float] = predicted
        else:
            log_spread = math.log(max(spread / mid, 1e-12))
            log_rv = math.log(max(rv, self._MIN_RV)) if rv is not None else None
            likelihoods = self._emission_likelihood(log_spread, log_rv)
            updated = self._bayes_update(predicted, likelihoods)
            if any(math.isnan(v) or math.isinf(v) for v in updated):
                logger.warning(
                    "regime_engine: NaN/inf in 2-D Bayesian update for symbol=%s; "
                    "resetting to uniform prior",
                    symbol,
                )
                updated = [1.0 / self._n_states] * self._n_states

        self._posteriors[symbol] = updated
        self._last_update_seq[symbol] = seq
        return list(updated)

    def _predict(self, prior: list[float]) -> list[float]:
        predicted = [0.0] * self._n_states
        for j in range(self._n_states):
            for i in range(self._n_states):
                predicted[j] += self._transition[i][j] * prior[i]
        total = sum(predicted)
        if total > 0:
            return [p / total for p in predicted]
        return [1.0 / self._n_states] * self._n_states

    def _emission_likelihood(self, log_spread: float, log_rv: float | None) -> list[float]:
        out: list[float] = []
        for (mu_s, sig_s), (mu_v, sig_v) in self._emission:
            z = (log_spread - mu_s) / sig_s
            ll = math.exp(-0.5 * z * z) / (sig_s * math.sqrt(2.0 * math.pi))
            if log_rv is not None:
                zv = (log_rv - mu_v) / sig_v
                ll *= math.exp(-0.5 * zv * zv) / (sig_v * math.sqrt(2.0 * math.pi))
            out.append(max(ll, 1e-300))
        return out

    def _bayes_update(self, predicted: list[float], likelihoods: list[float]) -> list[float]:
        unnorm = [p * l for p, l in zip(predicted, likelihoods)]
        total = sum(unnorm)
        if total < 1e-300:
            return [1.0 / self._n_states] * self._n_states
        return [u / total for u in unnorm]

    def current_state(self, symbol: str) -> list[float] | None:
        cached = self._posteriors.get(symbol)
        return list(cached) if cached is not None else None

    def reset(self, symbol: str) -> None:
        self._posteriors.pop(symbol, None)
        self._last_update_seq.pop(symbol, None)
        self._mid_window.pop(symbol, None)

    # ── Calibration ─────────────────────────────────────────────────

    def calibrate(self, quotes: Sequence[NBBOQuote]) -> bool:
        """Fit 2-D emissions from realized-vol quantile buckets.

        Replays quotes per symbol in (timestamp, sequence) order to compute
        the causal realized-vol series, pools ``(log_spread, log_rv)`` samples
        across symbols, buckets them by ``log_rv`` tercile, and fits per-bucket
        Gaussian moments for both dimensions.  Buckets are ordered by
        increasing realized-vol mean so state ``k`` is the ``k``-th vol
        regime (``vol_breakout`` = highest)."""
        by_symbol: dict[str, list[NBBOQuote]] = {}
        for q in quotes:
            by_symbol.setdefault(q.symbol, []).append(q)

        samples: list[tuple[float, float]] = []  # (log_spread, log_rv)
        for sym, sym_quotes in by_symbol.items():
            ordered = sorted(sym_quotes, key=lambda q: (q.timestamp_ns, q.sequence))
            window: deque[float] = deque(maxlen=self._rv_window + 1)
            for q in ordered:
                spread = float(q.ask - q.bid)
                mid = float(q.ask + q.bid) / 2.0
                if mid <= 0:
                    continue
                window.append(mid)
                if spread <= 0 or len(window) < self._rv_min_returns + 1:
                    continue
                mids = list(window)
                rets = [
                    math.log(mids[i] / mids[i - 1])
                    for i in range(1, len(mids))
                    if mids[i] > 0.0 and mids[i - 1] > 0.0
                ]
                if len(rets) < self._rv_min_returns:
                    continue
                rv = statistics.stdev(rets)
                samples.append(
                    (math.log(max(spread / mid, 1e-12)), math.log(max(rv, self._MIN_RV)))
                )

        if len(samples) < self._MIN_CALIBRATION_SAMPLES:
            return False

        by_vol = sorted(samples, key=lambda t: t[1])
        n = len(by_vol)
        k = self._n_states
        edges = [i * n // k for i in range(k)] + [n]
        fitted: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for b in range(k):
            bucket = by_vol[edges[b] : edges[b + 1]]
            spreads = [s for s, _ in bucket]
            vols = [v for _, v in bucket]
            fitted.append(
                (
                    (statistics.mean(spreads), self._fit_sigma(spreads)),
                    (statistics.mean(vols), self._fit_sigma(vols)),
                )
            )
        # Already vol-ordered by construction (buckets are vol terciles).
        self._emission = tuple(fitted)
        self._calibrated = True
        self._posteriors.clear()
        self._last_update_seq.clear()
        self._mid_window.clear()
        return True

    def _fit_sigma(self, values: list[float]) -> float:
        sigma = statistics.stdev(values) if len(values) >= 2 else self._MIN_SIGMA
        return max(sigma, self._MIN_SIGMA)

    # ── Checkpoint / restore ────────────────────────────────────────

    def _flags_fingerprint(self) -> str:
        canonical = {
            "schema": self._CHECKPOINT_SCHEMA_VERSION,
            "cls": "HMM3StateSpreadVol",
            "n_states": self._n_states,
            "state_names": list(self._state_names),
            "transition": [list(r) for r in self._transition],
            "rv_window": self._rv_window,
            "rv_min_returns": self._rv_min_returns,
        }
        raw = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def checkpoint(self) -> bytes:
        payload: dict[str, object] = {
            "checkpoint_schema_version": self._CHECKPOINT_SCHEMA_VERSION,
            "flags_fingerprint": self._flags_fingerprint(),
            "posteriors": self._posteriors,
            "last_update_seq": self._last_update_seq,
            "mid_window": {s: list(w) for s, w in self._mid_window.items()},
        }
        if self._calibrated:
            payload["emission"] = [[list(d) for d in dims] for dims in self._emission]
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def restore(self, data: bytes) -> None:
        prev_emission = self._emission
        prev_calibrated = self._calibrated
        try:
            payload = json.loads(data)
            blob_fp = payload.get("flags_fingerprint")
            if blob_fp is not None and blob_fp != self._flags_fingerprint():
                raise ValueError(
                    "checkpoint flags_fingerprint mismatch for HMM3StateSpreadVol; "
                    "restore requires identical state_names / transition / rv_* config"
                )
            posteriors = payload["posteriors"]
            last_seq = payload["last_update_seq"]
            if not isinstance(posteriors, dict) or not isinstance(last_seq, dict):
                raise ValueError("Invalid checkpoint structure")
            for sym, post in posteriors.items():
                if len(post) != self._n_states:
                    raise ValueError(f"Posterior length mismatch for {sym}")
                if any(v < 0 for v in post) or abs(sum(post) - 1.0) > 1e-6:
                    raise ValueError(f"Invalid posterior for {sym}: {post}")
            self._posteriors = {k: list(v) for k, v in posteriors.items()}
            self._last_update_seq = {k: int(v) for k, v in last_seq.items()}
            mw = payload.get("mid_window") or {}
            self._mid_window = {
                str(s): deque((float(x) for x in w), maxlen=self._rv_window + 1)
                for s, w in mw.items()
            }
            emission_data = payload.get("emission")
            if emission_data is not None:
                if len(emission_data) != self._n_states:
                    raise ValueError("Emission params length mismatch")
                parsed: list[tuple[tuple[float, float], tuple[float, float]]] = []
                for dims in emission_data:
                    (ms, ss), (mv, sv) = dims
                    if float(ss) <= 0 or float(sv) <= 0:
                        raise ValueError("Restored emission sigma must be > 0")
                    parsed.append(((float(ms), float(ss)), (float(mv), float(sv))))
                self._emission = tuple(parsed)
                self._calibrated = True
        except Exception:
            self._posteriors = {}
            self._last_update_seq = {}
            self._mid_window = {}
            self._emission = prev_emission
            self._calibrated = prev_calibrated
            raise


# ── Engine registry ──────────────────────────────────────────────────

_ENGINE_REGISTRY: dict[str, type[RegimeEngine]] = {
    "hmm_3state_fractional": HMM3StateFractional,
    # Preferred alias — same implementation; name reflects spread-filter semantics.
    "hmm_3state_spread_filter": HMM3StateFractional,
    # Audit R-3: opt-in 2-D (spread + realized-vol) engine.  Default
    # deployments keep the spread-only engine above; switch to this only after
    # validating its conditional-return tables via scripts/regime_diagnostics.py.
    "hmm_3state_spread_vol": HMM3StateSpreadVol,
}


def register_engine(name: str, engine_cls: type[RegimeEngine]) -> None:
    """Register a custom regime engine class by name."""
    _ENGINE_REGISTRY[name] = engine_cls


def get_regime_engine(name: str, **kwargs: object) -> RegimeEngine:
    """Look up and instantiate a regime engine by name.

    Built-in registry keys: ``hmm_3state_fractional`` (historical) and
    ``hmm_3state_spread_filter`` (alias for the same class).

    Raises ``KeyError`` if the engine name is not registered.
    """
    cls = _ENGINE_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(_ENGINE_REGISTRY))
        raise KeyError(f"Unknown regime engine '{name}'. Available: {available}")
    return cls(**kwargs)
