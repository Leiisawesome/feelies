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
        single-state engine (no pair to compare)."""
        return self._compute_min_pairwise_emission_separation(self._emission)

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


# ── Engine registry ──────────────────────────────────────────────────

_ENGINE_REGISTRY: dict[str, type[RegimeEngine]] = {
    "hmm_3state_fractional": HMM3StateFractional,
    # Preferred alias — same implementation; name reflects spread-filter semantics.
    "hmm_3state_spread_filter": HMM3StateFractional,
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
