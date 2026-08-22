"""R2 — market-data canonical parity baseline.

Engine 1's NBBOQuote/Trade stream.  Hashes a fixed wire fixture through
MassiveNormalizer over the full declared field set, Decimal fields as
exact strings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_normalizer import MassiveNormalizer

_RAW_FRAME = json.dumps(
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


def _replay() -> tuple[str, int]:
    clock = SimulatedClock(start_ns=0)
    normalizer = MassiveNormalizer(clock)
    events = list(normalizer.on_message(_RAW_FRAME, received_ns=1, source="massive_ws"))
    assert events, "fixture produced no canonical events — the hash would be vacuous"
    return _canonical_digest(events), len(events)


EXPECTED_MARKET_DATA_CANONICAL_HASH = "4c0446aa6c9c1dced2e98016158f209f9072df2891d5bc2e60396f369072115a"
EXPECTED_MARKET_DATA_CANONICAL_COUNT = 2


def test_market_data_canonical_parity_baseline() -> None:
    digest, count = _replay()
    assert count == EXPECTED_MARKET_DATA_CANONICAL_COUNT
    assert len(digest) == 64
    import tests.determinism.parity_manifest as manifest

    expected = getattr(manifest, "EXPECTED_MARKET_DATA_CANONICAL_HASH", None)
    assert expected is not None, (
        "engine 1 canonical stream has no baseline (G05); S-17 supplies it"
    )
    assert digest == expected
    assert digest == EXPECTED_MARKET_DATA_CANONICAL_HASH
