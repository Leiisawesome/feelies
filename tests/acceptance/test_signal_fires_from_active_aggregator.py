"""Acceptance tests for non-empty signals from the horizon pipeline.

The fixture drives sensor readings through aggregation and signal evaluation.
It checks signal identity, replay determinism, feature thresholds, and the
regime gate.
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
from feelies.sensors.impl.book_imbalance import BookImbalanceSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]

_SIGNAL_ALPHA = _REPO_ROOT / "alphas" / "sig_benign_midcap_v1" / "sig_benign_midcap_v1.alpha.yaml"

# Single-symbol universe — sufficient to prove the chain end-to-end.
_UNIVERSE: tuple[str, ...] = ("AAPL",)

# sig_benign_midcap_v1 declares depends_on_sensors including ofi_ewma,
# micro_price, spread_z_30d, realized_vol_30s — all must be registered.
# warm_after=5 speeds warm-up; the test pre-warms by direct SensorReading
# injection, not through real quotes.
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 8},
        subscribes_to=(NBBOQuote,),
    ),
    # The alpha confirms OFI with signed top-of-book imbalance.
    SensorSpec(
        sensor_id="book_imbalance",
        sensor_version="1.0.0",
        cls=BookImbalanceSensor,
        params={"warm_after": 1},
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
        # Only horizon=120 to match sig_benign_midcap_v1 (horizon_seconds=120)
        # and keep the test fast.
        horizons_seconds=frozenset({120}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        # This v0.2 parity fixture intentionally predates trend mechanisms.
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
    *,
    sensor_version: str = "1.0.0",
) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"test-{sensor_id}-{symbol}-{seq}",
        sequence=seq,
        symbol=symbol,
        sensor_id=sensor_id,
        sensor_version=sensor_version,
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
        Default 3.0 → z ≈ 4.9 >> entry_threshold_z=0.8.
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
        bus.publish(
            RegimeState(
                timestamp_ns=SESSION_OPEN_NS - 1,
                correlation_id=f"test-regime-{symbol}",
                sequence=seq,
                symbol=symbol,
                engine_name="hmm_3state_fractional",
                state_names=("compression_clustering", "normal", "vol_breakout"),
                posteriors=(p_compress, regime_p_normal, p_breakout),
                dominant_state=1,
                dominant_name="normal",
            )
        )
        seq += 1

    # ── 2. Inject spread_z_30d into signal engine sensor cache ──────────
    # Gate condition: abs(spread_z_30d) < 0.5.  Value 0.05 satisfies this.
    # HorizonSignalEngine._on_sensor_reading caches warm scalar readings.
    for symbol in _UNIVERSE:
        bus.publish(_reading(symbol, seq, "spread_z_30d", 0.05, SESSION_OPEN_NS))
        seq += 1

    # ── 3. Warm up RollingZscoreFeature with 30 baseline readings ───────
    # linspace(-1, 1, 30): symmetric around 0, providing a stable
    # rolling window with mean≈0 and std≈0.607.  After 30 readings the
    # feature becomes warm (min_samples=30 default).
    n_warmup = 30
    for i in range(n_warmup):
        v = (i / (n_warmup - 1)) * 2.0 - 1.0  # -1.0 … +1.0
        micro = 100.0 + (i / max(n_warmup - 1, 1)) * 1.0  # gentle uptrend
        ts = SESSION_OPEN_NS + i * 1_000_000_000
        for symbol in _UNIVERSE:
            bus.publish(_reading(symbol, seq, "ofi_ewma", v, ts))
            seq += 1
            bus.publish(_reading(symbol, seq, "micro_price", micro, ts))
            seq += 1
            bus.publish(
                _reading(
                    symbol,
                    seq,
                    "realized_vol_30s",
                    0.0005,
                    ts,
                    sensor_version="1.2.0",
                ),
            )
            seq += 1
            # Slight variation keeps the confirmation z-score non-degenerate.
            bus.publish(_reading(symbol, seq, "book_imbalance", 0.20 + 0.001 * i, ts))
            seq += 1

    # ── 4. Spike OFI — this is the reading that drives z above threshold ─
    # After 30 symmetric readings (mean≈0, std≈0.607) a reading of +3.0
    # produces z = (3.0 - 0) / 0.607 ≈ 4.94 >> entry_threshold_z=0.8.
    spike_ts = SESSION_OPEN_NS + n_warmup * 1_000_000_000
    for symbol in _UNIVERSE:
        bus.publish(_reading(symbol, seq, "ofi_ewma", ofi_spike, spike_ts))
        seq += 1
        bus.publish(_reading(symbol, seq, "micro_price", 103.0, spike_ts))
        seq += 1
        bus.publish(
            _reading(
                symbol,
                seq,
                "realized_vol_30s",
                0.0005,
                spike_ts,
                sensor_version="1.2.0",
            ),
        )
        seq += 1
        # Bid-heavy depth confirms the positive OFI spike.
        bus.publish(_reading(symbol, seq, "book_imbalance", 0.5, spike_ts))
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
    """A populated snapshot emits a signal when gate and threshold pass."""
    signals = _fire_signals()

    assert len(signals) >= 1, (
        f"Expected ≥1 Signal but got {len(signals)}.  "
        "snapshot.values may still be empty (passive aggregator)."
    )
    sig = signals[0]
    assert sig.strategy_id == "sig_benign_midcap_v1"
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
    """strength is in (0, strength_cap] for sig_benign_midcap_v1.

    Below saturation (|z| <= 2 * entry_threshold) strength is linear in
    |z|; above saturation it follows convex scaling capped at
    ``parameters.strength_cap`` (default 2.0).
    """
    strength_cap = 2.0  # sig_benign_midcap_v1.parameters.strength_cap default
    signals = _fire_signals()
    assert len(signals) >= 1
    for s in signals:
        assert 0.0 < s.strength <= strength_cap, (
            f"strength={s.strength!r} out of expected (0, {strength_cap}]"
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
        f"Signal streams diverged across two independent builds:\n  run 1: {h1}\n  run 2: {h2}"
    )


def test_below_threshold_no_signal() -> None:
    """OFI z-score below entry_threshold_z=0.8 produces no signals.

    With the same 30-sample warm-up window (mean≈0, std≈0.607) and
    spike value 0.3, z = 0.3 / 0.607 ≈ 0.49 < 0.8 → evaluate() returns None.
    """
    signals = _fire_signals(ofi_spike=0.3)
    assert len(signals) == 0, (
        f"Expected 0 signals below threshold but got {len(signals)}: "
        f"{[(s.strategy_id, s.direction) for s in signals]}"
    )


def test_gate_closed_no_signal() -> None:
    """Closed regime gate (P(normal) < 0.5) suppresses signals entirely.

    Regardless of the OFI z-score, the gate on_condition
    'P(normal) > 0.5 and spread_z_30d < 1.5' is not satisfied
    when P(normal)=0.30.
    """
    signals = _fire_signals(regime_p_normal=0.30)
    assert len(signals) == 0, (
        f"Expected 0 signals with gate closed but got {len(signals)}: "
        f"{[(s.strategy_id, s.direction) for s in signals]}"
    )
