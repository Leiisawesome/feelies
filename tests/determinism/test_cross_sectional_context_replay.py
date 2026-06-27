"""SIGNAL→PORTFOLIO handoff baseline — ``CrossSectionalContext`` parity (P1 #7).

The Level-3 sized-intent baselines feed a *hand-built* ``CrossSectionalContext``
straight into the composition engine, so the universe-synchronization step —
the barrier fan-in that turns a stream of per-symbol ``Signal`` events into one
cross-sectional snapshot — had **no** parity hash.  The glossary asserts the
synchronizer "enforces deterministic emission order … so cross-sectional
construction is replay-byte-identical (Inv-5)" but nothing pinned it.

This baseline drives the real :class:`UniverseSynchronizer` over a 4-symbol,
2-boundary scenario: boundary 1 drops one symbol (no feeder signal) to exercise
the ``None`` / sub-unity ``completeness`` path; boundary 2 has the full
universe.  The emitted ``CrossSectionalContext`` stream is hashed — pinning the
dedicated ``_ctx_seq`` allocation, the symbol-sorted ``signals_by_symbol`` /
``snapshots_by_symbol`` maps, and ``completeness``.
"""

from __future__ import annotations

import hashlib

from feelies.bus.event_bus import EventBus
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.core.events import (
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    Signal,
    SignalDirection,
)
from feelies.core.identifiers import SequenceGenerator

_UNIVERSE: tuple[str, ...] = ("AAPL", "GOOG", "META", "MSFT")
_STRATEGY_ID = "sig_xsect_feeder"
_HORIZON_S = 300
_HORIZON_NS = _HORIZON_S * 1_000_000_000
_SESSION_OPEN_NS = 1_700_000_000_000_000_000
_DIRECTIONS = {
    "AAPL": SignalDirection.LONG,
    "GOOG": SignalDirection.SHORT,
    "META": SignalDirection.LONG,
    "MSFT": SignalDirection.SHORT,
}


def _snapshot(symbol: str, boundary_index: int, ts_ns: int, seq: int) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=ts_ns,
        correlation_id=f"snap:{symbol}:{boundary_index}",
        sequence=seq,
        symbol=symbol,
        horizon_seconds=_HORIZON_S,
        boundary_index=boundary_index,
    )


def _signal(symbol: str, ts_ns: int, seq: int) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        correlation_id=f"sig:{symbol}:{seq}",
        sequence=seq,
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=_STRATEGY_ID,
        direction=_DIRECTIONS[symbol],
        strength=0.6,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_S,
    )


def _tick(boundary_index: int, ts_ns: int, seq: int) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id=f"tick:{boundary_index}",
        sequence=seq,
        horizon_seconds=_HORIZON_S,
        boundary_index=boundary_index,
        session_id="TEST_SYNTH",
        scope="UNIVERSE",
        symbol=None,
    )


# Boundary 1 drops MSFT (no feeder) → completeness 3/4; boundary 2 is full.
_BOUNDARY_SYMBOLS: dict[int, tuple[str, ...]] = {
    1: ("AAPL", "GOOG", "META"),
    2: _UNIVERSE,
}


def _replay() -> tuple[str, int]:
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, captured.append)  # type: ignore[arg-type]

    sync = UniverseSynchronizer(
        bus=bus,
        universe=_UNIVERSE,
        horizons=(_HORIZON_S,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    seq = SequenceGenerator()
    for boundary_index in (1, 2):
        barrier_ts = _SESSION_OPEN_NS + boundary_index * _HORIZON_NS
        for symbol in _BOUNDARY_SYMBOLS[boundary_index]:
            # snapshot precedes the signal so the freshness floor (signal
            # ts >= snapshot ts) passes; both are causal (ts < barrier).
            bus.publish(_snapshot(symbol, boundary_index, barrier_ts - 20_000_000_000, seq.next()))
            bus.publish(_signal(symbol, barrier_ts - 10_000_000_000, seq.next()))
        bus.publish(_tick(boundary_index, barrier_ts, seq.next()))

    return _hash_context_stream(captured), len(captured)


def _sig_repr(sig: Signal | None) -> str:
    if sig is None:
        return "None"
    return f"{sig.strategy_id}@{sig.direction.name}#{sig.sequence}"


def _hash_context_stream(contexts: list[CrossSectionalContext]) -> str:
    lines: list[str] = []
    for c in contexts:
        sigs = "|".join(
            f"{s}={_sig_repr(c.signals_by_symbol.get(s))}" for s in sorted(c.signals_by_symbol)
        )
        snaps = "|".join(
            f"{s}={'1' if c.snapshots_by_symbol.get(s) is not None else '0'}"
            for s in sorted(c.snapshots_by_symbol)
        )
        lines.append(
            f"{c.sequence}|{c.horizon_seconds}|{c.boundary_index}|{c.correlation_id}|"
            f"{c.timestamp_ns}|U={','.join(c.universe)}|C={c.completeness:.6f}|"
            f"SIG[{sigs}]|SNAP[{snaps}]"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# Locked baseline.  Re-baseline only with an intentional change to the
# synchronizer's barrier / completeness semantics, justified in the commit.
EXPECTED_XSECT_CONTEXT_HASH = "03d90d1226bf8f82e5ef3dfb33976bbfb4c51281584736fb6b7694039a15eef3"
EXPECTED_XSECT_CONTEXT_COUNT = 2


def test_cross_sectional_context_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_XSECT_CONTEXT_COUNT, (
        f"CrossSectionalContext count drift: expected {EXPECTED_XSECT_CONTEXT_COUNT}, "
        f"got {actual_count}"
    )
    assert actual_hash == EXPECTED_XSECT_CONTEXT_HASH, (
        "CrossSectionalContext hash drift!\n"
        f"  Expected: {EXPECTED_XSECT_CONTEXT_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (synchronizer/barrier change), update the constant in "
        "the same commit and justify in the commit message."
    )


def test_two_replays_produce_identical_context_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_boundary_completeness_is_partial_then_full() -> None:
    """Guard: the scenario actually exercises the None / completeness path."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, captured.append)  # type: ignore[arg-type]
    sync = UniverseSynchronizer(
        bus=bus,
        universe=_UNIVERSE,
        horizons=(_HORIZON_S,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()
    seq = SequenceGenerator()
    for boundary_index in (1, 2):
        barrier_ts = _SESSION_OPEN_NS + boundary_index * _HORIZON_NS
        for symbol in _BOUNDARY_SYMBOLS[boundary_index]:
            bus.publish(_snapshot(symbol, boundary_index, barrier_ts - 20_000_000_000, seq.next()))
            bus.publish(_signal(symbol, barrier_ts - 10_000_000_000, seq.next()))
        bus.publish(_tick(boundary_index, barrier_ts, seq.next()))

    assert [c.completeness for c in captured] == [0.75, 1.0]
    assert captured[0].signals_by_symbol["MSFT"] is None
    assert captured[1].signals_by_symbol["MSFT"] is not None
