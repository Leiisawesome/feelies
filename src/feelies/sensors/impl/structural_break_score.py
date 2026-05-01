"""Structural-break score (Page-Hinkley) sensor (v0.3 §20.4.4).

Detects non-stationarity in the *generating process* of an upstream
observable (distinct from regime-switching among recurrent states).
The output is a normalised page-Hinkley score in ``[0, 1]`` that
crosses ``0.95`` when the cumulative drift in the observable's mean
exceeds the configured tolerance — the canonical "alpha is dying"
diagnostic used by ``forensics/multi_horizon_attribution.py`` (§20.9).

H6 / M5 design note (v0.3 implementation boundary):

  This v0.3 sensor subscribes to ``NBBOQuote`` directly and derives its
  internal observable (absolute mid-price log-return) from raw quotes.
  It does **not** consume an upstream ``SensorReading`` stream.
  Accordingly, ``input_sensor_ids`` is declared as an empty tuple —
  accurately reflecting the zero cross-sensor wiring in the current
  implementation.  The ``SensorProvenance`` emitted by this sensor is
  therefore honest for forensic consumers reconstructing the dependency
  DAG (H6 / audit).

  The design §20.4.4 intent is to apply the Page-Hinkley test over an
  upstream sensor's output (e.g. ``hawkes_intensity``).  True
  cross-sensor wiring requires the registry's ``_on_event`` to route
  ``SensorReading`` events to downstream sensors — a v0.4 hot-path
  change tracked separately.  Until that lands, callers should treat
  the ``structural_break_score`` reading as derived from mid-price
  log-returns, not from a named upstream sensor.

Algorithm (page-Hinkley, one-sided up-test):

    Maintain a rolling reference window of the last
    ``window_seconds`` of the observable.  Compute its running mean
    ``μ_ref`` (online incremental).  On each new sample ``x_t``:

        m_t = max(0, m_{t-1} + (x_t - μ_ref) - δ)
        score_t = min(1.0, m_t / λ)

    where ``δ`` is the tolerated drift floor (default ``0.0``) and
    ``λ`` is the alarm threshold (default ``small relative to typical
    cumulative drift``, sensor parameter ``alarm_threshold``).
    ``score_t > 0.95`` is a structural-break alert per §20.4.4.

    The reference window evicts samples older than ``window_seconds``
    in event time.  When the window resets (e.g. after a long pause),
    ``m`` and ``μ_ref`` are re-initialised from the next observation.

Determinism: pure float arithmetic; deque-based event-time eviction;
no RNG.

Warm-up: ``warm = True`` once the reference window has held at least
``warm_samples`` observations *and* spans at least ``window_seconds``
of event time (matches the §20.4.4 "rolling reference window full"
criterion).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade

_NS_PER_SECOND: int = 1_000_000_000


class StructuralBreakScoreSensor:
    """Page-Hinkley score over the absolute mid-price log-returns.

    Parameters:

    - ``window_seconds`` (int, default 3600): event-time width of the
      reference window.  Must be strictly positive.
    - ``alarm_threshold`` (float, default 0.05): page-Hinkley ``λ``;
      ``m_t / λ`` is clipped at 1.0 and reported as the score.
    - ``drift_floor`` (float, default 0.0): page-Hinkley ``δ``;
      tolerated drift that does not contribute to ``m``.
    - ``warm_samples`` (int, default 100): minimum samples in the
      reference window before ``warm=True``.
    """

    sensor_id: str = "structural_break_score"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 3600,
        alarm_threshold: float = 0.05,
        drift_floor: float = 0.0,
        warm_samples: int = 100,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if alarm_threshold <= 0.0:
            raise ValueError(
                f"alarm_threshold must be > 0, got {alarm_threshold}"
            )
        if drift_floor < 0.0:
            raise ValueError(
                f"drift_floor must be >= 0, got {drift_floor}"
            )
        if warm_samples < 0:
            raise ValueError(
                f"warm_samples must be >= 0, got {warm_samples}"
            )
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * _NS_PER_SECOND
        self._window_seconds = window_seconds
        self._alarm_threshold = alarm_threshold
        self._drift_floor = drift_floor
        self._warm_samples = warm_samples

    def initial_state(self) -> dict[str, Any]:
        return {
            "samples": deque(),  # (ts_ns, value)
            "sum": 0.0,
            "m": 0.0,             # page-Hinkley running cumulant
            "last_mid": None,
        }

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

        last_mid = state["last_mid"]
        state["last_mid"] = mid
        if last_mid is None or last_mid <= 0.0:
            return SensorReading(
                timestamp_ns=event.timestamp_ns,
                correlation_id="placeholder",
                sequence=-1,
                symbol=event.symbol,
                sensor_id=self.sensor_id,
                sensor_version=self.sensor_version,
                value=0.0,
                warm=False,
            )

        observable = abs(math.log(mid) - math.log(last_mid))

        ts_ns = event.timestamp_ns
        samples = state["samples"]
        samples.append((ts_ns, observable))
        state["sum"] += observable
        cutoff = ts_ns - self._window_ns
        while samples and samples[0][0] < cutoff:
            _t, v = samples.popleft()
            state["sum"] -= v

        n = len(samples)
        if n == 0:
            return None
        mean = state["sum"] / float(n)

        # Page-Hinkley up-test.  Reset ``m`` to zero when negative —
        # this is the standard one-sided variant detecting an *increase*
        # in the observable's drift (equivalent to a structural shift
        # toward higher volatility / higher activity).
        new_m = max(0.0, state["m"] + (observable - mean) - self._drift_floor)
        state["m"] = new_m
        score = min(1.0, new_m / self._alarm_threshold)

        warm = (
            n >= self._warm_samples
            and (samples[-1][0] - samples[0][0]) >= self._window_ns
        )

        return SensorReading(
            timestamp_ns=ts_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=score,
            warm=warm,
        )
