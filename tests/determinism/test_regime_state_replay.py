"""Level-6 baseline — ``RegimeState`` stream from ``HMM3StateFractional``.

Locks a deterministic fingerprint of :class:`feelies.core.events.RegimeState`
events produced by driving the built-in spread filter with a fixed
quote fixture (calibrated emissions, constant 50ms quote cadence).

Updates require changing both ``EXPECTED_LEVEL6_REGIME_STATE_COUNT`` and
``EXPECTED_LEVEL6_REGIME_STATE_HASH`` in the same commit with rationale.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal


from feelies.core.events import NBBOQuote, RegimeState
from feelies.services.regime_engine import (
    HMM3StateFractional,
    regime_posterior_entropy_nats,
)

_ENGINE = "hmm_3state_fractional"
_SYMBOL = "AAPL"
_N_QUOTES = 40
_DT_NS = 50_000_000


def _make_quote(sequence: int, timestamp_ns: int) -> NBBOQuote:
    spread = 0.01 + (sequence % 5) * 0.02
    bid = 150.0
    ask = bid + spread
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id=f"corr-{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        bid=Decimal(f"{bid:.4f}"),
        ask=Decimal(f"{ask:.4f}"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=timestamp_ns - 1000,
    )


def _drive_regime_states() -> list[RegimeState]:
    engine = HMM3StateFractional(
        emission_params=[(-9.2, 0.25), (-8.8, 0.45), (-8.0, 0.65)],
        transition_time_scaling_enabled=True,
        transition_dt_reference_seconds=0.05,
    )
    state_names = tuple(engine.state_names)
    states: list[RegimeState] = []
    base_ts = 10_000_000_000
    for i in range(_N_QUOTES):
        seq = i + 1
        ts = base_ts + i * _DT_NS
        quote = _make_quote(seq, ts)
        posteriors = engine.posterior(quote)
        dominant_idx = max(range(len(posteriors)), key=lambda j: posteriors[j])
        states.append(
            RegimeState(
                timestamp_ns=ts,
                correlation_id=quote.correlation_id,
                sequence=seq,
                symbol=_SYMBOL,
                engine_name=_ENGINE,
                state_names=state_names,
                posteriors=tuple(posteriors),
                dominant_state=dominant_idx,
                dominant_name=state_names[dominant_idx],
                posterior_entropy_nats=regime_posterior_entropy_nats(posteriors),
            )
        )
    return states


def _hash_regime_stream(states: list[RegimeState]) -> str:
    lines: list[str] = []
    for s in states:
        post = "|".join(f"{p:.6f}" for p in s.posteriors)
        lines.append(
            f"{s.sequence}|{s.symbol}|{s.engine_name}|{s.dominant_state}|"
            f"{s.dominant_name}|{post}|{s.posterior_entropy_nats:.6f}|"
            f"{s.timestamp_ns}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def test_two_replays_produce_identical_regime_state_hash() -> None:
    hash_a = _hash_regime_stream(_drive_regime_states())
    hash_b = _hash_regime_stream(_drive_regime_states())
    assert hash_a == hash_b


# Locked baseline — update only with intentional filter / fixture changes.
EXPECTED_LEVEL6_REGIME_STATE_COUNT = 40
EXPECTED_LEVEL6_REGIME_STATE_HASH = (
    "025d4a228ed4387f89fb6a55c12c7398ed7d1b31edb0ed3e7f4533db107122cb"
)


def test_regime_state_count_matches_locked_baseline() -> None:
    states = _drive_regime_states()
    assert len(states) == EXPECTED_LEVEL6_REGIME_STATE_COUNT


def test_regime_state_stream_matches_locked_baseline() -> None:
    actual = _hash_regime_stream(_drive_regime_states())
    assert actual == EXPECTED_LEVEL6_REGIME_STATE_HASH, (
        "Level-6 RegimeState hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL6_REGIME_STATE_HASH}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_LEVEL6_REGIME_STATE_HASH in the "
        "same commit and justify in the commit message."
    )
