"""Acceptance test: Phase-3.5 pipeline fires non-vacuous signals.

Prior to commit df632ef (Phase 3.5, "activate HorizonAggregator with
sensor feature layer"), HorizonAggregator ran in *passive* mode —
``snapshot.values`` was always empty, so every alpha's ``evaluate()``
returned ``None`` and no Signals ever fired from the horizon pipeline.
Every existing e2e integration test acknowledges this explicitly:

    "the realised standalone-Signal count is zero and the assertion
     holds vacuously today"
                          — tests/integration/test_phase4_e2e.py

This test closes that verification gap by driving the full
L1→L2→L3 chain manually and asserting that Signals fire when the
regime gate and feature conditions are met.

Pipeline under test
-------------------

1. ``SensorReading(ofi_ewma)`` events →
   ``RollingZscoreFeature.observe()`` in HorizonAggregator accumulates
   rolling history (30 neutral readings + 1 spike to +3.0).

2. ``HorizonTick(horizon_seconds=120, scope=UNIVERSE)`` →
   ``RollingZscoreFeature.finalize()`` → ``HorizonFeatureSnapshot``
   with ``values={"ofi_ewma_zscore": ~4.9, "ofi_ewma": 3.0, ...}``
   published on the bus.

3. ``HorizonSignalEngine._on_snapshot()``:
   - gate: ``P(normal)=0.85 > 0.7 ✓`` and
     ``abs(spread_z_30d)=0.05 < 0.5 ✓``
   - ``evaluate()``: ``z≈4.9 > entry_threshold_z=2.0`` →
     ``Signal(direction=LONG, strategy_id="pofi_benign_midcap_v1")``

4. Signal published on bus → captured by test subscriber.

Assertions
----------

* At least one ``Signal`` is published (non-vacuous).
* Signal has correct ``strategy_id``, direction ``LONG``, and
  ``edge_estimate_bps > 0``.
* Two independent ``build_platform()`` calls with identical event
  sequences produce byte-identical signal streams (Inv-5 determinism).
* Dropping the OFI spike (z≈1.65 < 2.0) yields zero signals
  (feature threshold is enforced).
* Closing the regime gate (P(normal)=0.30 < 0.70) yields zero signals
  (regime gate is enforced).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import (
    HorizonTick,
    NBBOQuote,
    RegimeState,
    SensorReading,
    Signal,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]

_SIGNAL_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_benign_midcap_v1"
    / "pofi_benign_midcap_v1.alpha.yaml"
)

# Single-symbol universe — sufficient to prove the chain end-to-end.
_UNIVERSE: tuple[str, ...] = ("AAPL",)

# pofi_benign_midcap_v1 declares depends_on_sensors: [ofi_ewma, micro_price,
# spread_z_30d].  All three must be registered for G6 to pass at load.
# warm_after=5 speeds warm-up; the test pre-warms by direct SensorReading
# injection, not through real quotes.
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


def _make_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_SIGNAL_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        # Only horizon=120 to match pofi_benign_midcap_v1 (horizon_seconds=120)
        # and keep the test fast.
        horizons_seconds=frozenset({120}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        # pofi_benign_midcap_v1 has no trend_mechanism: block; this is the
        # designated v0.2 parity anchor.  Workstream-E made True the
        # platform default, so the test must opt out explicitly.
        enforce_trend_mechanism=False,
    )


# ── Bus-driving helpers ────────────────────────────────────────────────────


def _regime_normal(symbol: str, seq: int) -> RegimeState:
    """Build a RegimeState with P(normal)=0.85 that passes the benign gate."""
    # HMM3StateFractional._DEFAULT_STATE_NAMES =
    #   ("compression_clustering", "normal", "vol_breakout")
    # Gate on_condition: P(normal) > 0.7 → posteriors[1] must exceed 0.7.
    return RegimeState(
        timestamp_ns=SESSION_OPEN_NS - 1,
        correlation_id=f"test-regime-{symbol}-{seq}",
        sequence=seq,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.05, 0.85, 0.10),
        dominant_state=1,
        dominant_name="normal",
    )


def _reading(
    symbol: str,
    seq: int,
    sensor_id: str,
    value: float,
    ts_ns: int,
) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"test-{sensor_id}-{symbol}-{seq}",
        sequence=seq,
        symbol=symbol,
        sensor_id=sensor_id,
        sensor_version="1.0.0",
        value=value,
        warm=True,
    )


def _tick_120(seq: int) -> HorizonTick:
    """Universe-scoped horizon tick at the first 120-second boundary."""
    return HorizonTick(
        timestamp_ns=SESSION_OPEN_NS + 120_000_000_000,
        correlation_id=f"test-tick-120-{seq}",
        sequence=seq,
        horizon_seconds=120,
        boundary_index=1,
        scope="UNIVERSE",
        symbol=None,
        session_id="ACCEPTANCE_TEST",
    )


def _fire_signals(
    *,
    ofi_spike: float = 3.0,
    regime_p_normal: float = 0.85,
) -> list[Signal]:
    """Construct the platform, drive the bus, and return captured Signals.

    Parameters
    ----------
    ofi_spike:
        The OFI reading appended after the 30-sample warm-up window.
        Default 3.0 → z ≈ 4.9 >> entry_threshold_z=2.0.
        Set to 1.0 to produce z ≈ 1.65 < 2.0 (below-threshold case).
    regime_p_normal:
        Posterior probability assigned to "normal" in the injected
        RegimeState.  Default 0.85 (gate passes).
        Set to 0.30 to force gate closed.
    """
    config = _make_config()
    # Empty event log — we drive the bus manually rather than running
    # the full orchestrator replay so the test is fast and HMM-agnostic.
    orchestrator, _ = build_platform(config, event_log=InMemoryEventLog())
    bus = orchestrator._bus

    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)

    seq = 1  # monotone sequence counter

    # ── 1. Inject regime state ──────────────────────────────────────────
    # HorizonSignalEngine caches this in _regime_cache[(symbol, engine)].
    # No orchestrator events will overwrite it because we skip run_backtest().
    p_compress = (1.0 - regime_p_normal) * 0.5
    p_breakout = (1.0 - regime_p_normal) * 0.5
    for symbol in _UNIVERSE:
        bus.publish(RegimeState(
            timestamp_ns=SESSION_OPEN_NS - 1,
            correlation_id=f"test-regime-{symbol}",
            sequence=seq,
            symbol=symbol,
            engine_name="hmm_3state_fractional",
            state_names=("compression_clustering", "normal", "vol_breakout"),
            posteriors=(p_compress, regime_p_normal, p_breakout),
            dominant_state=1,
            dominant_name="normal",
        ))
        seq += 1

    # ── 2. Inject spread_z_30d into signal engine sensor cache ──────────
    # Gate condition: abs(spread_z_30d) < 0.5.  Value 0.05 satisfies this.
    # HorizonSignalEngine._on_sensor_reading caches warm scalar readings.
    for symbol in _UNIVERSE:
        bus.publish(_reading(symbol, seq, "spread_z_30d", 0.05,
                             SESSION_OPEN_NS))
        seq += 1

    # ── 3. Warm up RollingZscoreFeature with 30 baseline readings ───────
    # linspace(-1, 1, 30): symmetric around 0, providing a stable
    # rolling window with mean≈0 and std≈0.607.  After 30 readings the
    # feature becomes warm (min_samples=30 default).
    n_warmup = 30
    for i in range(n_warmup):
        v = (i / (n_warmup - 1)) * 2.0 - 1.0  # -1.0 … +1.0
        ts = SESSION_OPEN_NS + i * 1_000_000_000
        for symbol in _UNIVERSE:
            bus.publish(_reading(symbol, seq, "ofi_ewma", v, ts))
            seq += 1

    # ── 4. Spike OFI — this is the reading that drives z above threshold ─
    # After 30 symmetric readings (mean≈0, std≈0.607) a reading of +3.0
    # produces z = (3.0 - 0) / 0.607 ≈ 4.94 >> entry_threshold_z=2.0.
    spike_ts = SESSION_OPEN_NS + n_warmup * 1_000_000_000
    for symbol in _UNIVERSE:
        bus.publish(_reading(symbol, seq, "ofi_ewma", ofi_spike, spike_ts))
        seq += 1

    # ── 5. Trigger the 120-second horizon boundary ─────────────────────
    # HorizonAggregator finalises RollingZscoreFeature → publishes
    # HorizonFeatureSnapshot.values["ofi_ewma_zscore"].
    # HorizonSignalEngine evaluates gate + evaluate() → publishes Signal.
    bus.publish(_tick_120(seq))

    return captured


def _hash(signals: list[Signal]) -> str:
    """Stable content hash across all captured signals."""
    lines = [
        f"{s.timestamp_ns}|{s.symbol}|{s.strategy_id}|{s.layer}|"
        f"{s.horizon_seconds}|{s.direction.name}|"
        f"{s.strength:.8f}|{s.edge_estimate_bps:.8f}|"
        f"{s.correlation_id}|{s.sequence}"
        for s in signals
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# ── Tests ──────────────────────────────────────────────────────────────────


def test_signal_fires_nonvacuously() -> None:
    """At least one Signal is emitted when gate + threshold are satisfied.

    This is the primary Phase-3.5 acceptance assertion: proves that
    HorizonFeatureSnapshot.values is populated with real feature values
    (not empty {}) and that the full evaluate() path is exercised.
    """
    signals = _fire_signals()

    assert len(signals) >= 1, (
        f"Expected ≥1 Signal but got {len(signals)}.  "
        "snapshot.values may still be empty (passive aggregator)."
    )
    sig = signals[0]
    assert sig.strategy_id == "pofi_benign_midcap_v1"
    assert sig.layer == "SIGNAL"
    assert sig.horizon_seconds == 120
    assert sig.regime_gate_state == "ON"
    assert sig.edge_estimate_bps > 0.0


def test_signal_direction_is_long_for_positive_ofi() -> None:
    """Positive OFI spike (z > 0) produces a LONG signal."""
    from feelies.core.events import SignalDirection

    signals = _fire_signals(ofi_spike=3.0)
    assert len(signals) >= 1
    assert signals[0].direction == SignalDirection.LONG


def test_signal_strength_within_bounds() -> None:
    """strength is in (0, 1] — evaluate() formula: min(|z| / (2 * threshold), 1.0)."""
    signals = _fire_signals()
    assert len(signals) >= 1
    for s in signals:
        assert 0.0 < s.strength <= 1.0, (
            f"strength={s.strength!r} out of expected (0, 1]"
        )


def test_signal_determinism_inv5() -> None:
    """Two independent platform builds with identical inputs produce
    byte-identical Signal streams (Inv-5 determinism guarantee).

    Each call to _fire_signals() creates a completely fresh Orchestrator,
    EventBus, HorizonAggregator, HorizonSignalEngine, and SequenceGenerators
    — all initialised from the same seed-free, deterministic sequence of
    bus.publish() calls.  The hash of each run's output must be identical.
    """
    h1 = _hash(_fire_signals())
    h2 = _hash(_fire_signals())
    assert h1 == h2, (
        f"Signal streams diverged across two independent builds:\n"
        f"  run 1: {h1}\n  run 2: {h2}"
    )


def test_below_threshold_no_signal() -> None:
    """OFI z-score below entry_threshold_z=2.0 produces no signals.

    With the same 30-sample warm-up window (mean≈0, std≈0.607) and
    spike value 1.0, z = 1.0 / 0.607 ≈ 1.65 < 2.0 → evaluate() returns None.
    """
    signals = _fire_signals(ofi_spike=1.0)
    assert len(signals) == 0, (
        f"Expected 0 signals below threshold but got {len(signals)}: "
        f"{[(s.strategy_id, s.direction) for s in signals]}"
    )


def test_gate_closed_no_signal() -> None:
    """Closed regime gate (P(normal) < 0.7) suppresses signals entirely.

    Regardless of the OFI z-score, the gate on_condition
    'P(normal) > 0.7 and abs(spread_z_30d) < 0.5' is not satisfied
    when P(normal)=0.30.
    """
    signals = _fire_signals(regime_p_normal=0.30)
    assert len(signals) == 0, (
        f"Expected 0 signals with gate closed but got {len(signals)}: "
        f"{[(s.strategy_id, s.direction) for s in signals]}"
    )
