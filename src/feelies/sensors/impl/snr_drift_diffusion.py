"""SNR drift-diffusion sensor (v0.3 §20.4.3).

Per-horizon rolling estimator of the signal-to-noise ratio

    SNR(h) = |μ_t(h)| / (σ_t(h) / √h)

where ``μ_t(h)`` is the EWMA of **log** mid-price returns at horizon
``h`` (seconds) and ``σ_t(h)`` is the EWMA RMSE proxy from squared
log returns at the same horizon.  This is the essay's §4.2 *exploitability gate* — alphas are
required by the regime DSL to consult ``snr(h)`` against a configured
floor before opening positions, where ``h`` matches the alpha's
``horizon_seconds``.

Output (length ``len(horizons_seconds)`` tuple, *sorted ascending*):

    SensorReading.value = tuple(snr_at_horizon[h] for h in sorted(...))

Algorithm (per horizon ``h``):

- Sample mid-prices on a fixed integer-nanosecond grid **anchored to a
  shared reference time** (``grid_anchor_ns``, default 0 = Unix epoch).
  Grid points are at ``grid_anchor_ns + k * h * 1e9`` for integer k, so
  *all symbols share the same grid boundaries* — cross-symbol
  horizon-aligned analyses are well-defined.  The first quote per
  symbol seeds ``mid_bar_open`` and aligns ``next_sample_ns`` to the
  next grid point after its timestamp.  Quotes between grid points
  only update the most-recent mid (no leakage of intra-bar
  information).
- When the event time reaches or passes a grid deadline, compute a
  single **log-return** over the elapsed bar:
  ``r = log(mid_now) - log(mid_open)`` where ``mid_open`` is the NBBO
  mid carried from the previous grid boundary (bootstrap seeds the
  first open).  When a quote arrives after ``N`` missed grid
  deadlines (N ≥ 1), the cumulative log-return ``r`` is split into
  ``N`` equal per-bar increments ``r/N`` and the EWMA is advanced by
  ``N`` updates in closed form (see below).  This keeps both ``μ`` and
  ``σ²`` unbiased after gaps — feeding ``r`` as a single sample would
  inflate ``σ²`` by O(N) and ``μ`` by O(N).
- Update incrementally per missed bar:
      μ_h  ← (1 - λ)·μ_h  + λ·(r/N)
      σ²_h ← (1 - λ)·σ²_h + λ·(r/N)²
  with default decay λ = 2 / (1 + N_eff), N_eff = 16 effective samples
  per horizon (≈ Welford-equivalent half-life).  ``N`` such updates
  collapse into a closed-form weight ``(1-λ)^N`` on the prior state
  plus ``1 - (1-λ)^N`` on the per-bar value — O(1) regardless of gap
  size.
- ``SNR(h) = |μ_h| / (max(σ_h, ε) / √h)``.

Determinism: pure float arithmetic; integer grid crossings.

Warm-up: ``warm = True`` once *every* registered horizon has
accumulated ≥ ``warm_samples_per_horizon`` (default 4) *returns*
contributing to the EWMA accumulators (matching the §20.4.3
requirement of "four horizon samples minimum").  The bootstrap quote
sets ``mid_bar_open`` without producing a return and so does **not**
count toward this gate.  A multi-bar consolidated update increments
the counter by ``N`` (the number of missed bars it stands in for), so
the gate tracks elapsed grid time rather than callback count.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade

_NS_PER_SECOND: int = 1_000_000_000
_EPS: float = 1e-12


class SNRDriftDiffusionSensor:
    """Per-horizon SNR estimator using EWMA mean & variance.

    Parameters:

    - ``horizons_seconds`` (tuple[int, ...], required): horizons (in
      seconds) at which to estimate SNR.  Stored sorted ascending.
    - ``ewma_n_eff`` (int, default 16): effective-sample-size for the
      EWMA decays; smaller is faster-tracking, larger is smoother.
    - ``warm_samples_per_horizon`` (int, default 4): minimum *returns*
      observed on every horizon before ``warm=True``.  Matches the
      design-doc default.  The bootstrap quote does not count.
    - ``grid_anchor_ns`` (int, default 0): shared reference time (ns)
      for the per-horizon grid.  All symbols snap their grid to
      ``grid_anchor_ns + k * h * 1e9``, so any two SNR readings at the
      same wall-clock time are referenced to the same grid boundaries.
      Default 0 anchors to the Unix epoch (gives stable boundaries
      across processes / restarts); set to a session-open timestamp
      for tighter alignment to session structure.
    """

    sensor_id: str = "snr_drift_diffusion"
    sensor_version: str = "1.3.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        horizons_seconds: tuple[int, ...] = (30, 120),
        ewma_n_eff: int = 16,
        warm_samples_per_horizon: int = 4,
        grid_anchor_ns: int = 0,
    ) -> None:
        if not horizons_seconds:
            raise ValueError("horizons_seconds must be non-empty")
        if any(h <= 0 for h in horizons_seconds):
            raise ValueError(f"horizons_seconds must be positive, got {horizons_seconds}")
        if ewma_n_eff <= 0:
            raise ValueError(f"ewma_n_eff must be > 0, got {ewma_n_eff}")
        if warm_samples_per_horizon < 0:
            raise ValueError(
                f"warm_samples_per_horizon must be >= 0, got {warm_samples_per_horizon}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._horizons = tuple(sorted(int(h) for h in horizons_seconds))
        self._ewma_lambda = 2.0 / (1.0 + float(ewma_n_eff))
        self._warm_samples = warm_samples_per_horizon
        self._grid_anchor_ns = int(grid_anchor_ns)

    def initial_state(self) -> dict[str, Any]:
        return {
            "last_mid": None,
            "by_horizon": {
                h: {
                    "mu": 0.0,
                    "sig2": 0.0,
                    "mid_bar_open": None,
                    "next_sample_ns": None,
                    "samples": 0,
                }
                for h in self._horizons
            },
        }

    def _maybe_emit_for_horizon(
        self,
        h: int,
        slot: dict[str, Any],
        ts_ns: int,
        mid: float,
    ) -> None:
        h_ns = h * _NS_PER_SECOND
        if slot["next_sample_ns"] is None:
            # Snap to the next grid boundary at or after ``ts_ns``.
            # Grid points are at ``grid_anchor_ns + k * h_ns``; the next one
            # strictly greater than ``ts_ns`` becomes our first bar close.
            offset = (ts_ns - self._grid_anchor_ns) % h_ns
            slot["next_sample_ns"] = ts_ns + (h_ns - offset)
            slot["mid_bar_open"] = mid
            # Bootstrap quote seeds the grid but produces no return — do not
            # advance the warm-sample counter here (counter measures returns
            # contributing to the EWMA, not callbacks).
            return
        if ts_ns < slot["next_sample_ns"]:
            return

        # Caller's guard (bid, ask > 0) implies mid > 0; combined with the
        # bootstrap branch above which pins mid_bar_open to a positive mid,
        # ``mo`` is always > 0 here.  No defensive fallback is needed.
        mo = slot["mid_bar_open"]

        # Closed-form ``n_bars`` EWMA updates with per-bar return ``r/n_bars``.
        # ``r`` is the total log-return over the elapsed ``n_bars * h``
        # seconds; splitting equally avoids the O(N) variance inflation that
        # treating ``r`` as a single sample would cause.
        n_bars = (ts_ns - slot["next_sample_ns"]) // h_ns + 1
        r_total = math.log(mid) - math.log(mo)
        r_per_bar = r_total / float(n_bars)
        lam = self._ewma_lambda
        decay = (1.0 - lam) ** n_bars
        slot["mu"] = decay * slot["mu"] + (1.0 - decay) * r_per_bar
        slot["sig2"] = decay * slot["sig2"] + (1.0 - decay) * r_per_bar * r_per_bar
        slot["mid_bar_open"] = mid
        slot["next_sample_ns"] += n_bars * h_ns
        slot["samples"] += n_bars

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
        if bid <= 0.0 or ask <= 0.0:
            return None
        mid = (bid + ask) / 2.0
        state["last_mid"] = mid

        ts_ns = event.timestamp_ns
        snrs: list[float] = []
        warm = True
        for h in self._horizons:
            slot = state["by_horizon"][h]
            self._maybe_emit_for_horizon(h, slot, ts_ns, mid)
            sig = math.sqrt(max(slot["sig2"], 0.0))
            denom = max(sig, _EPS) / math.sqrt(float(h))
            snrs.append(abs(slot["mu"]) / denom)
            if slot["samples"] < self._warm_samples:
                warm = False

        return SensorReading(
            timestamp_ns=ts_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=tuple(snrs),
            warm=warm,
        )
