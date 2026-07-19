"""Non-empty SIGNAL baseline for a real reference alpha (audit-2026-07-02 P1 #6).

``test_signal_replay.py`` locks the *empty* Level-2 ``Signal`` stream for the
actual reference alpha ``sig_benign_midcap_v1`` (and all four v0.3 alphas) —
on the canonical synthetic fixture none of them ever cross their entry gate,
so that baseline pins absence, not the ordering/sequence/content of a real
production alpha's own decision logic.  ``test_signal_fires_replay.py``
proved the *hash mechanism* can pin non-empty content, but only for a
hand-written synthetic probe signal + a trivial hand-built gate — not for an
actual `*.alpha.yaml` reference strategy.

This module closes that gap by driving the **real** ``sig_benign_midcap_v1``
module — loaded through :class:`feelies.alpha.loader.AlphaLoader` exactly as
``test_signal_replay.py`` does, no shortcuts on the alpha's own ``evaluate()``
or its ``regime_gate`` DSL — with hand-built ``RegimeState`` and
``HorizonFeatureSnapshot`` events.  This mirrors ``test_signal_fires_replay``'s
technique (already an established, precedented pattern in this suite for
regime-gated alphas — ``test_regime_hazard_replay.py`` and
``test_cross_sectional_context_replay.py`` also hand-build their upstream
events rather than deriving them through a full sensor/regime-calibration
pipeline) rather than trying to reverse-engineer the raw quote sequence that
would make the real ``OFIEwmaSensor`` + ``HMM3StateFractional`` converge to
the same values — the alpha's *decision* logic is exercised for real; only
its *sensing* inputs are synthesized directly.

The fixture drives two boundaries with ``ofi_ewma_zscore`` at 2.0 and 1.5
(both above the alpha's default ``entry_threshold_z=0.8``), confirming
``book_imbalance_mean`` same-signed and above the ``imbalance_floor=0.05``,
``spread_z_30d`` inside the ON band, and a ``RegimeState`` with
``P(normal)=0.90`` (above the ``on_condition``'s ``P(normal) > 0.5``) — both
boundaries emit a real ``Signal(direction=LONG)`` with the alpha's actual
convex strength scaling and disclosed cost-arithmetic fields.
"""

from __future__ import annotations

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonFeatureSnapshot, RegimeState, Signal
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal

from tests.determinism.test_signal_replay import REFERENCE_PATH, _hash_signal_stream

_SYMBOL = "AAPL"
_HORIZON_S = 120
_BASE_TS = 1_700_000_000_000_000_000
_ENGINE = "hmm_3state_fractional"
_STATE_NAMES: tuple[str, ...] = ("compression", "normal", "vol_breakout")

# Two boundaries, both comfortably past every gate in sig_benign_midcap_v1's
# regime_gate / evaluate(): P(normal)=0.90 > 0.5, spread_z_30d=0.1 < 1.5,
# |ofi_ewma_zscore| in {2.0, 1.5} > entry_threshold_z=0.8, book_imbalance_mean
# same-signed and > imbalance_floor=0.05, realized_vol_30s_zscore=0.2 keeps
# off_condition closed.
_OFI_Z_BY_BOUNDARY: tuple[float, ...] = (2.0, 1.5)


def _regime_state(sequence: int, ts_ns: int) -> RegimeState:
    return RegimeState(
        timestamp_ns=ts_ns,
        correlation_id=f"regime:{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        engine_name=_ENGINE,
        state_names=_STATE_NAMES,
        posteriors=(0.05, 0.90, 0.05),
        dominant_state=1,
        dominant_name="normal",
        calibrated=True,
    )


def _snapshot(
    sequence: int, boundary_index: int, ts_ns: int, ofi_z: float
) -> HorizonFeatureSnapshot:
    values = {
        "ofi_ewma_zscore": ofi_z,
        "book_imbalance_mean": 0.2 if ofi_z > 0 else -0.2,
        "spread_z_30d": 0.1,
        "realized_vol_30s_zscore": 0.2,
    }
    return HorizonFeatureSnapshot(
        timestamp_ns=ts_ns,
        correlation_id=f"snap:{boundary_index}",
        sequence=sequence,
        symbol=_SYMBOL,
        horizon_seconds=_HORIZON_S,
        boundary_index=boundary_index,
        values=values,
        warm={k: True for k in values},
        stale={k: False for k in values},
    )


def _build_engine() -> tuple[EventBus, list[Signal]]:
    bus = EventBus()
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]

    loaded = AlphaLoader(enforce_trend_mechanism=False).load(REFERENCE_PATH)
    assert isinstance(loaded, LoadedSignalLayerModule)

    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
    engine.register(
        RegisteredSignal(
            alpha_id=loaded.manifest.alpha_id,
            horizon_seconds=loaded.horizon_seconds,
            signal=loaded.signal,
            params=loaded.params,
            gate=loaded.gate,
            cost_arithmetic=loaded.cost,
            consumed_features=loaded.consumed_features,
            trend_mechanism=loaded.trend_mechanism_enum,
            expected_half_life_seconds=loaded.expected_half_life_seconds,
        )
    )
    engine.attach()
    return bus, captured


def _replay() -> tuple[str, int]:
    bus, captured = _build_engine()
    seq = 0
    for k, ofi_z in enumerate(_OFI_Z_BY_BOUNDARY, start=1):
        ts = _BASE_TS + k * _HORIZON_S * 1_000_000_000
        seq += 1
        bus.publish(_regime_state(seq, ts - 1_000_000_000))
        seq += 1
        bus.publish(_snapshot(seq, k, ts, ofi_z))
    return _hash_signal_stream(captured), len(captured)


# Locked non-empty reference-alpha SIGNAL baseline.  Re-baseline only with an
# intentional change to sig_benign_midcap_v1's evaluate()/regime_gate or the
# engine's emission semantics, justified in the commit.
EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_HASH = (
    "e74f274141f8963c43237baa05f4b5bcb7b081c7b52cd0cebe92551be3c3d221"
)
EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_COUNT = 2


def test_reference_alpha_signal_fires_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_COUNT, (
        f"sig_benign_midcap_v1 emitted-signal count drift: expected "
        f"{EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_HASH, (
        "Reference-alpha non-empty SIGNAL hash drift!\n"
        f"  Expected: {EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (alpha logic change), update the constant in the "
        "same commit and justify in the commit message."
    )


def test_two_replays_produce_identical_reference_alpha_signal_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_stream_is_non_empty_and_uses_the_real_reference_alpha() -> None:
    """Guard against silently reverting to the empty baseline.

    Confirms the emitted signals actually came from ``sig_benign_midcap_v1``
    (not some other strategy id), fired LONG with ``regime_gate_state="ON"``,
    and that sequence allocation is strictly increasing — i.e. the real
    alpha's decision path ran, not a permissive stand-in.
    """
    _bus, captured = _build_engine()
    seq = 0
    for k, ofi_z in enumerate(_OFI_Z_BY_BOUNDARY, start=1):
        ts = _BASE_TS + k * _HORIZON_S * 1_000_000_000
        seq += 1
        _bus.publish(_regime_state(seq, ts - 1_000_000_000))
        seq += 1
        _bus.publish(_snapshot(seq, k, ts, ofi_z))

    assert captured, "stream is empty — baseline would pin absence, not emission"
    assert all(s.strategy_id == "sig_benign_midcap_v1" for s in captured)
    assert all(s.direction.name == "LONG" for s in captured)
    assert all(s.regime_gate_state == "ON" for s in captured)
    seqs = [s.sequence for s in captured]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        f"sequence allocation broken: {seqs}"
    )
