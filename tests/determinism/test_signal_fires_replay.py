"""Non-empty SIGNAL baseline — ``Signal`` emission parity (audit P1 #4).

The Level-2 ``Signal`` baseline (``test_signal_replay.py``) is the SHA-256 of
the **empty string**: on the synthetic fixture every reference alpha stays
below its entry gate, so the locked hash pins *the absence of signals* — not
the ordering, sequence allocation, or content of any actual ``Signal``.  A
real signal-emission-ordering or sequence-reuse bug could not be caught.

This baseline closes that gap by driving the **real**
:class:`HorizonSignalEngine` to actually emit.  A probe :class:`HorizonSignal`
and a real :class:`RegimeGate` (``on: ofi_ewma > 0``, ``off: ofi_ewma < 0``)
are registered, then a deterministic snapshot sequence walks the gate
OFF→ON→(stays ON)→ON→OFF (gate-close FLAT)→ON.  The emitted stream is hashed
with the *same* canonical serializer as the empty baseline
(``_hash_signal_stream``), so this is literally its non-empty counterpart:
it pins the engine's dedicated ``_signal_seq`` allocation, the ON/OFF
``regime_gate_state`` stamping, the gate-close exit emission, and the
``trend_mechanism`` / ``expected_half_life_seconds`` provenance propagation.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import RegimeGate
from tests.determinism.test_signal_replay import _hash_signal_stream

_ALPHA_ID = "sig_probe_ofi_v1"
_SYMBOL = "AAPL"
_HORIZON_S = 300
_BASE_TS = 1_700_000_000_000_000_000

# Snapshot ofi_ewma values per boundary.  Drives the gate latch:
#   +2 → OFF→ON (entry), +1 → stays ON (entry), -2 → ON→OFF (gate-close FLAT),
#   +3 → OFF→ON (entry).  Four emitted Signals: LONG, LONG, FLAT, LONG.
_OFI_BY_BOUNDARY: tuple[float, ...] = (2.0, 1.0, -2.0, 3.0)


class _ProbeSignal:
    """Minimal real HorizonSignal: LONG when ofi_ewma is positive."""

    signal_id = "probe_ofi"
    signal_version = "1.0.0"

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: Any,
        params: Mapping[str, Any],
    ) -> Signal | None:
        v = float(snapshot.values.get("ofi_ewma", 0.0))
        if v <= 0.0:
            return None
        # Provenance fields are filled in by the engine's _patch_signal.
        return Signal(
            timestamp_ns=0,
            correlation_id="",
            sequence=0,
            symbol=snapshot.symbol,
            strategy_id="",
            direction=SignalDirection.LONG,
            strength=round(abs(v) * 0.1, 6),
            edge_estimate_bps=8.0,
        )


def _cost_arithmetic() -> CostArithmetic:
    # edge 10 / cost 4 → margin 2.5 (> 1.5); constructor is permissive.
    return CostArithmetic(
        edge_estimate_bps=10.0,
        half_spread_bps=2.0,
        impact_bps=1.0,
        fee_bps=1.0,
        margin_ratio=2.5,
    )


def _build_engine() -> tuple[EventBus, list[Signal]]:
    bus = EventBus()
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]

    gate = RegimeGate(
        alpha_id=_ALPHA_ID,
        on_condition="ofi_ewma > 0.0",
        off_condition="ofi_ewma < 0.0",
        engine_name=None,
    )
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
    engine.register(
        RegisteredSignal(
            alpha_id=_ALPHA_ID,
            horizon_seconds=_HORIZON_S,
            signal=_ProbeSignal(),
            params={},
            gate=gate,
            cost_arithmetic=_cost_arithmetic(),
            trend_mechanism=TrendMechanism.KYLE_INFO,
            expected_half_life_seconds=600,
            consumed_features=("ofi_ewma",),
        )
    )
    engine.attach()
    return bus, captured


def _snapshot(boundary_index: int, ofi: float) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=_BASE_TS + boundary_index * _HORIZON_S * 1_000_000_000,
        correlation_id=f"snap:{_SYMBOL}:{boundary_index}",
        sequence=boundary_index,
        symbol=_SYMBOL,
        horizon_seconds=_HORIZON_S,
        boundary_index=boundary_index,
        values={"ofi_ewma": ofi},
        warm={"ofi_ewma": True},
        stale={"ofi_ewma": False},
    )


def _replay() -> tuple[str, int]:
    bus, captured = _build_engine()
    for k, ofi in enumerate(_OFI_BY_BOUNDARY, start=1):
        bus.publish(_snapshot(k, ofi))
    return _hash_signal_stream(captured), len(captured)


# Locked non-empty SIGNAL baseline.  Re-baseline only with an intentional
# change to the engine's emission semantics, justified in the commit.
EXPECTED_SIGNAL_FIRES_HASH = "dca81a0bdaab6e98eb4d40079131645bae3c05b8d922f63ca2acc50d6c875f75"
EXPECTED_SIGNAL_FIRES_COUNT = 4


def test_signal_fires_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_SIGNAL_FIRES_COUNT, (
        f"emitted-signal count drift: expected {EXPECTED_SIGNAL_FIRES_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_SIGNAL_FIRES_HASH, (
        "Non-empty SIGNAL hash drift!\n"
        f"  Expected: {EXPECTED_SIGNAL_FIRES_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (engine emission change), update the constant in the "
        "same commit and justify in the commit message."
    )


def test_two_replays_produce_identical_signal_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_stream_is_non_empty_and_exercises_entry_and_gate_close() -> None:
    """Guard against silently reverting to the empty baseline.

    The whole point is a *non-empty* stream that pins real emission: assert
    at least one LONG entry (regime_gate_state ON) and the ON→OFF gate-close
    FLAT (regime_gate_state OFF) are both present.
    """
    _bus, captured = _build_engine()
    for k, ofi in enumerate(_OFI_BY_BOUNDARY, start=1):
        _bus.publish(_snapshot(k, ofi))

    assert captured, "stream is empty — baseline would pin absence, not emission"
    dispositions = [(s.direction.name, s.regime_gate_state) for s in captured]
    assert ("LONG", "ON") in dispositions, "no gated entry signal emitted"
    assert ("FLAT", "OFF") in dispositions, "no gate-close (ON→OFF) FLAT emitted"
    # Sequence numbers come from the engine's dedicated generator and must be
    # strictly increasing in emission order (no reuse, no gaps backwards).
    seqs = [s.sequence for s in captured]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        f"sequence allocation broken: {seqs}"
    )
