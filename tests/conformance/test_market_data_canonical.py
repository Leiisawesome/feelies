"""R2 — market-data canonical parity baseline.

Engine 1's NBBOQuote/Trade stream has no manifest entry today (G05).
This test hashes a fixed wire fixture through MassiveNormalizer over the
full declared field set, Decimal fields as exact strings.  S-17 supplies
the baseline this asserts on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_normalizer import MassiveNormalizer


def _canonical_digest(events: list[NBBOQuote | Trade]) -> str:
    parts: list[str] = []
    for event in events:
        row: list[str] = [type(event).__name__]
        for f in fields(event):
            value = getattr(event, f.name)
            if isinstance(value, Decimal):
                row.append(f"{f.name}={value}")
            else:
                row.append(f"{f.name}={value!r}")
        parts.append("|".join(row))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@pytest.mark.xfail(strict=True, reason="GAP G05")
def test_market_data_canonical_parity_baseline() -> None:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock)
    frame = json.dumps(
        [
            {
                "ev": "Q",
                "sym": "AAPL",
                "t": 1_700_000_000_000,
                "bp": 180.0,
                "ap": 180.05,
                "bs": 100,
                "as": 200,
                "q": 1,
            },
            {
                "ev": "T",
                "sym": "AAPL",
                "t": 1_700_000_000_001,
                "p": 180.02,
                "s": 50,
                "q": 1,
            },
        ]
    ).encode("utf-8")
    events = list(normalizer.on_message(frame, received_ns=1, source="massive_ws"))
    assert events, "fixture produced no canonical events — the hash would be vacuous"
    digest = _canonical_digest(events)
    assert len(digest) == 64

    import tests.determinism.parity_manifest as manifest

    expected = getattr(manifest, "EXPECTED_MARKET_DATA_CANONICAL_HASH", None)
    assert expected is not None, (
        "engine 1 canonical stream has no baseline (G05); S-17 supplies it"
    )
    assert digest == expected
