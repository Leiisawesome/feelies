"""Deterministic synthesizer for the Phase-2 multi-boundary fixture.

Produces a JSONL log of ``NBBOQuote`` and ``Trade`` events for a
single symbol (AAPL by default) spanning a 5-minute window.  The
window is **deliberately long enough** to cross at least:

- 10 boundaries of the 30-second horizon,
- 2 boundaries of the 120-second horizon,
- 1 boundary of the 300-second horizon,

so the determinism tests can lock baselines for every sensor + tick
emission for the canonical horizon set.

Determinism contract:

- All randomness flows through ``random.Random`` seeded with the
  ``seed`` argument (default 42); ``PYTHONHASHSEED=0`` is also
  required at the process level for stable dict iteration in
  consumers, but the synthesizer itself relies only on the seeded
  RNG.
- Quote / trade timestamps are pure integer arithmetic
  (``session_open_ns + i * 100_000_000`` for 100ms cadence), no
  floats, so cross-platform reproducibility holds.
- The output JSONL is sorted by ``timestamp_ns`` (each record's
  ``timestamp_ns`` is monotonically increasing).

To regenerate the fixture::

    PYTHONHASHSEED=0 python -m tests.fixtures.event_logs._generate

This will overwrite ``synth_5min_aapl.jsonl`` in this package.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

# Anchor the synthetic session at 2026-01-15 14:30:00 UTC (a recent
# regular US-equity open) — pure constant, unrelated to wall-clock.
SESSION_OPEN_NS: int = 1_768_532_400_000_000_000
QUOTE_CADENCE_NS: int = 100_000_000          # 10 quotes per second
TRADE_EVERY_N_QUOTES: int = 7                # ~1.4 trades per second
NUM_QUOTES: int = 3_000                      # 5 minutes at 10 Hz
DEFAULT_SYMBOL: str = "AAPL"
DEFAULT_OUTPUT: Path = Path(__file__).parent / "synth_5min_aapl.jsonl"


def _quote_record(
    *,
    rng: random.Random,
    symbol: str,
    sequence: int,
    ts_ns: int,
    last_mid_cents: int,
) -> tuple[dict[str, Any], int]:
    """Synthesize a single ``NBBOQuote`` JSON record.

    Returns ``(record, mid_cents)`` so the next call can take a
    one-cent random walk from the previous mid.  Spreads are 1 cent
    everywhere; sizes drift in a deterministic but variety-rich
    fashion so OFI/imbalance sensors have signal to chew on.
    """
    delta_cents = rng.choice((-1, 0, 0, 0, 1))
    mid_cents = last_mid_cents + delta_cents
    bid_cents = mid_cents
    ask_cents = mid_cents + 1
    bid_size = rng.choice((100, 200, 300, 400, 500))
    ask_size = rng.choice((100, 200, 300, 400, 500))
    record = {
        "kind": "NBBOQuote",
        "timestamp_ns": ts_ns,
        "correlation_id": f"synth-q-{sequence}",
        "sequence": sequence,
        "source_layer": "INGESTION",
        "symbol": symbol,
        "bid": f"{bid_cents / 100:.2f}",
        "ask": f"{ask_cents / 100:.2f}",
        "bid_size": bid_size,
        "ask_size": ask_size,
        "exchange_timestamp_ns": ts_ns,
        "bid_exchange": 11,
        "ask_exchange": 11,
        "tape": 3,
    }
    return record, mid_cents


def _trade_record(
    *,
    rng: random.Random,
    symbol: str,
    sequence: int,
    ts_ns: int,
    last_mid_cents: int,
) -> dict[str, Any]:
    side_buy = rng.random() < 0.5
    price_cents = last_mid_cents + (1 if side_buy else 0)
    size = rng.choice((50, 100, 150, 200))
    return {
        "kind": "Trade",
        "timestamp_ns": ts_ns + 1,  # +1ns so trade follows its quote
        "correlation_id": f"synth-t-{sequence}",
        "sequence": sequence,
        "source_layer": "INGESTION",
        "symbol": symbol,
        "price": f"{price_cents / 100:.2f}",
        "size": size,
        "exchange": 11,
        "trade_id": f"synth-trade-{sequence:08d}",
        "exchange_timestamp_ns": ts_ns + 1,
        "tape": 3,
    }


def generate(
    *,
    output: Path = DEFAULT_OUTPUT,
    symbol: str = DEFAULT_SYMBOL,
    seed: int = 42,
    num_quotes: int = NUM_QUOTES,
) -> Path:
    """Write a deterministic JSONL fixture.

    Returns the path written.  Caller is responsible for ensuring
    ``PYTHONHASHSEED=0`` is set at the process level if the consumer
    of the fixture depends on hash-stable iteration.
    """
    rng = random.Random(seed)
    output.parent.mkdir(parents=True, exist_ok=True)

    last_mid_cents = 18_000  # $180.00 starting price
    quote_seq = 0
    trade_seq = 0

    with output.open("w", encoding="utf-8", newline="\n") as fh:
        for i in range(num_quotes):
            ts_ns = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
            quote_seq += 1
            quote, last_mid_cents = _quote_record(
                rng=rng,
                symbol=symbol,
                sequence=quote_seq,
                ts_ns=ts_ns,
                last_mid_cents=last_mid_cents,
            )
            fh.write(json.dumps(quote, sort_keys=True) + "\n")

            if i % TRADE_EVERY_N_QUOTES == 0 and i > 0:
                trade_seq += 1
                trade = _trade_record(
                    rng=rng,
                    symbol=symbol,
                    sequence=trade_seq,
                    ts_ns=ts_ns,
                    last_mid_cents=last_mid_cents,
                )
                fh.write(json.dumps(trade, sort_keys=True) + "\n")

    return output


def load(path: Path = DEFAULT_OUTPUT) -> list[Any]:
    """Load a JSONL fixture as a list of typed event objects.

    Reconstructs ``NBBOQuote`` / ``Trade`` instances from the
    serialized records.  ``Decimal`` price fields are restored from
    string form (preserves bit-exact precision).
    """
    from feelies.core.events import NBBOQuote, Trade

    events: list[Any] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            data = json.loads(line)
            kind = data.pop("kind")
            if kind == "NBBOQuote":
                data["bid"] = Decimal(data["bid"])
                data["ask"] = Decimal(data["ask"])
                events.append(NBBOQuote(**data))
            elif kind == "Trade":
                data["price"] = Decimal(data["price"])
                events.append(Trade(**data))
            else:
                raise ValueError(f"unknown event kind in fixture: {kind!r}")
    return events


if __name__ == "__main__":
    written = generate()
    print(f"wrote {written} ({written.stat().st_size} bytes)")
