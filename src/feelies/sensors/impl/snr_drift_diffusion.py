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

- Sample mid-prices on a fixed integer-nanosecond grid:
  ``next_sample_ns_h = last_sample_ns_h + h * 1e9``.  The first quote
  bootstraps the grid.  Quotes between grid points only update the
  most-recent mid (no leakage of intra-bar information).
- When the event time reaches or passes a grid deadline, compute a
  single **log-return** over the elapsed bar:
  ``r = log(mid_now) - log(mid_open)`` where ``mid_open`` is the NBBO
  mid carried from the previous grid boundary (bootstrap seeds the
  first open).  Quotes that arrive after **multiple** missed
  deadlines consolidate into **one** return — no zero-filled interior
  steps.
- Update incrementally:
      μ_h ← (1 - λ_μ) · μ_h + λ_μ · r
      σ²_h ← (1 - λ_σ²) · σ²_h + λ_σ² · r²
  with default decay λ_μ = λ_σ² = 2 / (1 + N_eff), N_eff = 16
  effective samples per horizon (≈ Welford-equivalent half-life).
- ``SNR(h) = |μ_h| / (max(σ_h, ε) / √h)``.

Determinism: pure float arithmetic; integer grid crossings.

Warm-up: ``warm = True`` once *every* registered horizon has
accumulated ≥ ``warm_samples_per_horizon`` (default 4) grid samples,
matching the §20.4.3 requirement of "four horizon samples minimum".
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
    - ``warm_samples_per_horizon`` (int, default 4): minimum grid
      samples on every horizon before ``warm=True``.  Matches the
      design-doc default.
    """

    sensor_id: str = "snr_drift_diffusion"
    sensor_version: str = "1.1.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        horizons_seconds: tuple[int, ...] = (30, 120),
        ewma_n_eff: int = 16,
        warm_samples_per_horizon: int = 4,
    ) -> None:
        if not horizons_seconds:
            raise ValueError("horizons_seconds must be non-empty")
        if any(h <= 0 for h in horizons_seconds):
            raise ValueError(
                f"horizons_seconds must be positive, got {horizons_seconds}"
            )
        if ewma_n_eff <= 0:
            raise ValueError(f"ewma_n_eff must be > 0, got {ewma_n_eff}")
        if warm_samples_per_horizon < 0:
            raise ValueError(
                f"warm_samples_per_horizon must be >= 0, "
                f"got {warm_samples_per_horizon}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._horizons = tuple(sorted(int(h) for h in horizons_seconds))
        self._ewma_lambda = 2.0 / (1.0 + float(ewma_n_eff))
        self._warm_samples = warm_samples_per_horizon

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
        if slot["next_sample_ns"] is None:
            slot["mid_bar_open"] = mid
            slot["next_sample_ns"] = ts_ns + h * _NS_PER_SECOND
            slot["samples"] += 1
            return
        if ts_ns < slot["next_sample_ns"]:
            return

        mo = slot["mid_bar_open"]
        if mo is None or mo <= 0.0 or mid <= 0.0:
            slot["mid_bar_open"] = mid if mid > 0 else mo
            while slot["next_sample_ns"] <= ts_ns:
                slot["next_sample_ns"] += h * _NS_PER_SECOND
            return

        # One consolidated log-return across all missed deadlines on this quote.
        r = math.log(mid) - math.log(mo)
        lam = self._ewma_lambda
        slot["mu"] = (1.0 - lam) * slot["mu"] + lam * r
        slot["sig2"] = (1.0 - lam) * slot["sig2"] + lam * r * r
        slot["mid_bar_open"] = mid
        while slot["next_sample_ns"] <= ts_ns:
            slot["next_sample_ns"] += h * _NS_PER_SECOND
        slot["samples"] += 1

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
