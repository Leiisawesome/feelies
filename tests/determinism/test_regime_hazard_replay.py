"""Level-5 baseline — ``RegimeHazardSpike`` replay parity (Phase 3.1).

Locks a deterministic Level-5 fingerprint of the
``RegimeHazardSpike`` stream produced by
:class:`feelies.services.regime_hazard_detector.RegimeHazardDetector`
when driven against a synthetic regime-flip fixture.

The fixture is a hand-crafted :class:`RegimeState` sequence that
covers the four canonical hazard transitions enumerated in v0.3
§20.3.1:

1.  Quiet decay through the dominance floor (``p_now < 1.0 - h``)
    while the dominant state is still nominally the same.
2.  Hard flip from one dominant state to another within one tick.
3.  Suppression: a second decay tick on the *same* departure episode
    must not emit a second spike.
4.  Re-arming: once the departing state regains dominance (or its
    posterior recovers above the dominance floor) the next decay
    fires a fresh spike.

Replay must reproduce the locked SHA-256 hash bit-for-bit.  Any
drift requires updating both the count and the hash in the same
commit, with rationale.
"""

from __future__ import annotations

import hashlib

from feelies.core.events import RegimeHazardSpike, RegimeState
from feelies.services.regime_hazard_detector import RegimeHazardDetector


_STATE_NAMES = ("compression", "normal", "vol_breakout")
_ENGINE = "HMM3StateFractional"
_SYMBOL = "AAPL"


def _state(
    *,
    posteriors: tuple[float, float, float],
    dominant_idx: int,
    sequence: int,
    timestamp_ns: int,
) -> RegimeState:
    return RegimeState(
        timestamp_ns=timestamp_ns,
        correlation_id=f"corr-{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        engine_name=_ENGINE,
        state_names=_STATE_NAMES,
        posteriors=posteriors,
        dominant_state=dominant_idx,
        dominant_name=_STATE_NAMES[dominant_idx],
    )


def _fixture_states() -> list[RegimeState]:
    """Synthetic 7-tick regime fixture covering the canonical
    transitions enumerated above."""
    return [
        # Tick 0 — strongly normal-dominant baseline.
        _state(
            posteriors=(0.05, 0.95, 0.00),
            dominant_idx=1,
            sequence=0,
            timestamp_ns=1_000,
        ),
        # Tick 1 — quiet decay below the 0.70 dominance floor;
        # normal still nominally dominant → spike(1) fires.
        _state(
            posteriors=(0.40, 0.60, 0.00),
            dominant_idx=1,
            sequence=1,
            timestamp_ns=2_000,
        ),
        # Tick 2 — same departure episode continues; suppression
        # must hold → no spike.
        _state(
            posteriors=(0.50, 0.50, 0.00),
            dominant_idx=1,
            sequence=2,
            timestamp_ns=3_000,
        ),
        # Tick 3 — normal recovers above the 0.70 floor; suppression
        # is re-armed but no spike on this tick (posterior rose).
        _state(
            posteriors=(0.10, 0.85, 0.05),
            dominant_idx=1,
            sequence=3,
            timestamp_ns=4_000,
        ),
        # Tick 4 — hard flip: vol_breakout takes over within one
        # tick → spike(2) fires (departing=normal).
        _state(
            posteriors=(0.05, 0.20, 0.75),
            dominant_idx=2,
            sequence=4,
            timestamp_ns=5_000,
        ),
        # Tick 5 — vol_breakout decays below floor; spike(3)
        # fires (departing=vol_breakout).
        _state(
            posteriors=(0.30, 0.45, 0.25),
            dominant_idx=1,
            sequence=5,
            timestamp_ns=6_000,
        ),
        # Tick 6 — normal posterior monotonically recovers to its
        # baseline; no new spike on this tick (rising posterior).
        _state(
            posteriors=(0.05, 0.95, 0.00),
            dominant_idx=1,
            sequence=6,
            timestamp_ns=7_000,
        ),
    ]


def _replay() -> tuple[str, int]:
    detector = RegimeHazardDetector(hysteresis_threshold=0.30)
    states = _fixture_states()
    spikes: list[RegimeHazardSpike] = []
    prev: RegimeState | None = None
    for curr in states:
        spike = detector.detect(prev, curr)
        if spike is not None:
            spikes.append(spike)
        prev = curr
    return _hash_spike_stream(spikes), len(spikes)


def _hash_spike_stream(spikes: list[RegimeHazardSpike]) -> str:
    lines: list[str] = []
    for s in spikes:
        lines.append(
            f"{s.sequence}|{s.symbol}|{s.engine_name}|"
            f"{s.departing_state}|"
            f"{s.departing_posterior_prev:.6f}|"
            f"{s.departing_posterior_now:.6f}|"
            f"{s.incoming_state if s.incoming_state else '-'}|"
            f"{s.hazard_score:.6f}|{s.timestamp_ns}|{s.correlation_id}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Determinism (replay twice → same hash) ──────────────────────────────


def test_two_replays_produce_identical_hazard_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


# ── Locked baseline ─────────────────────────────────────────────────────


# Level-5 baseline: hash of the (RegimeHazardSpike,...) stream emitted
# by the canonical regime-flip fixture above.  Updates require a
# justified commit message and bump of *both* count and hash.
EXPECTED_LEVEL5_HAZARD_COUNT = 3

# Frozen literal SHA-256 of the (RegimeHazardSpike,...) stream
# produced by the canonical fixture above when fed through
# :class:`RegimeHazardDetector` with ``hysteresis_threshold=0.30``.
#
# This constant is the actual locked baseline.  Earlier revisions of
# this test computed ``expected`` via a sibling driver
# (``_drive_reference``) that ran the same detector on the same
# fixture, so any change in detector logic moved both sides in lock-
# step and the assertion was vacuous.  Treat any drift here as a
# Level-5 parity break:
#
#   * If intentional (a deliberate change to the fixture, the hazard
#     formula, or the line format in ``_hash_spike_stream``), update
#     this literal in the same commit and justify the change in the
#     commit message.
#   * If unintentional, the detector or one of its dependencies
#     changed observable output and must be fixed before merge.
EXPECTED_LEVEL5_HAZARD_HASH = (
    "8092e88586a006ff7a46ee02dfc8f26c31d62d4cb2db7d1493bb8e8e81e3bf2e"
)


def test_hazard_count_matches_locked_baseline() -> None:
    _, actual_count = _replay()
    assert actual_count == EXPECTED_LEVEL5_HAZARD_COUNT, (
        f"hazard spike count drift: expected "
        f"{EXPECTED_LEVEL5_HAZARD_COUNT}, got {actual_count}"
    )


def test_hazard_stream_matches_locked_baseline() -> None:
    actual_hash, _ = _replay()
    assert actual_hash == EXPECTED_LEVEL5_HAZARD_HASH, (
        "Level-5 RegimeHazardSpike hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL5_HAZARD_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update EXPECTED_LEVEL5_HAZARD_HASH in the "
        "same commit and justify in the commit message."
    )
