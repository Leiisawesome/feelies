"""Deterministic generator for the Phase-2-γ complex-sensor fixtures.

Each fixture is a JSONL file with one record per input event:

    {"input": <event_payload>, "expected_value": <float>, "expected_warm": <bool>}

The generator drives a single, freshly constructed sensor instance
through a synthetic event sequence — different per sensor — and
records the output it produced.  The corresponding test rebuilds the
same input sequence, drives the same sensor, and asserts the output
matches the locked vector value-by-value.

Why per-sensor sequences?  The simple-sensor unit tests in
``tests/sensors/test_*.py`` already cover hand-computable corner
cases.  The locked-vector tests catch *aggregate* drift across long
sequences (deque eviction, rolling-window math, accumulator stability)
that hand-computation cannot economically span.

Determinism contract:

- All synthesis uses ``random.Random(seed)``.
- Timestamps are pure-integer (``base_ns + i * cadence_ns``).
- Prices are integer cents converted to ``Decimal`` so we never
  lose precision in the round-trip through JSON.
- The generator writes JSONL with ``sort_keys=True`` so a textual
  diff catches any reordering.

To regenerate (after intentional sensor-implementation changes)::

    PYTHONHASHSEED=0 python -m tests.sensors.fixtures._generate

This will overwrite the five ``*.jsonl`` files in this package.  Each
must then be explicitly re-baselined in the same commit, with the
sensor change rationalised in the commit message.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.quote_hazard_rate import QuoteHazardRateSensor
from feelies.sensors.impl.quote_replenish_asymmetry import (
    QuoteReplenishAsymmetrySensor,
)
from feelies.sensors.impl.trade_through_rate import TradeThroughRateSensor
from feelies.sensors.impl.vpin_50bucket import VPIN50BucketSensor

_HERE = Path(__file__).parent
SESSION_OPEN_NS: int = 1_768_532_400_000_000_000  # matches event_logs fixture
QUOTE_CADENCE_NS: int = 100_000_000  # 10 quotes / second
SYMBOL: str = "AAPL"


# ── Event synthesis primitives ─────────────────────────────────────


def _quote(
    *,
    rng: random.Random,
    sequence: int,
    ts_ns: int,
    last_mid_cents: int,
) -> tuple[NBBOQuote, int]:
    drift = rng.choice((-1, 0, 0, 0, +1))
    mid_cents = last_mid_cents + drift
    bid_cents = mid_cents - 1
    ask_cents = mid_cents + 1
    bid_size = rng.randint(1, 10) * 100
    ask_size = rng.randint(1, 10) * 100
    quote = NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{SYMBOL}-{sequence}",
        sequence=sequence,
        symbol=SYMBOL,
        bid=Decimal(bid_cents) / Decimal(100),
        ask=Decimal(ask_cents) / Decimal(100),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts_ns,
    )
    return quote, mid_cents


def _trade(
    *,
    rng: random.Random,
    sequence: int,
    ts_ns: int,
    mid_cents: int,
) -> Trade:
    # 50% midpoint, 25% lift offer, 25% hit bid; size in 100s.
    side = rng.choice(("mid", "buy", "sell"))
    if side == "mid":
        price_cents = mid_cents
    elif side == "buy":
        price_cents = mid_cents + 1  # lifts ask
    else:
        price_cents = mid_cents - 1  # hits bid
    size = rng.randint(1, 8) * 100
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{SYMBOL}-{sequence}",
        sequence=sequence,
        symbol=SYMBOL,
        price=Decimal(price_cents) / Decimal(100),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


# ── Generator descriptor ───────────────────────────────────────────


@dataclass
class FixtureSpec:
    output: Path
    sensor_factory: Callable[[], Any]
    needs_quote: bool
    needs_trade: bool
    n_events: int
    seed: int
    quote_every: int = 1   # emit a quote every N steps
    trade_every: int = 5   # emit a trade every M steps


def _serialise_event(event: NBBOQuote | Trade) -> dict[str, Any]:
    if isinstance(event, NBBOQuote):
        return {
            "kind": "NBBOQuote",
            "timestamp_ns": event.timestamp_ns,
            "sequence": event.sequence,
            "symbol": event.symbol,
            "bid": str(event.bid),
            "ask": str(event.ask),
            "bid_size": event.bid_size,
            "ask_size": event.ask_size,
        }
    return {
        "kind": "Trade",
        "timestamp_ns": event.timestamp_ns,
        "sequence": event.sequence,
        "symbol": event.symbol,
        "price": str(event.price),
        "size": event.size,
    }


def deserialise_event(record: dict[str, Any]) -> NBBOQuote | Trade:
    if record["kind"] == "NBBOQuote":
        return NBBOQuote(
            timestamp_ns=record["timestamp_ns"],
            correlation_id=f"q-{record['symbol']}-{record['sequence']}",
            sequence=record["sequence"],
            symbol=record["symbol"],
            bid=Decimal(record["bid"]),
            ask=Decimal(record["ask"]),
            bid_size=record["bid_size"],
            ask_size=record["ask_size"],
            exchange_timestamp_ns=record["timestamp_ns"],
        )
    return Trade(
        timestamp_ns=record["timestamp_ns"],
        correlation_id=f"t-{record['symbol']}-{record['sequence']}",
        sequence=record["sequence"],
        symbol=record["symbol"],
        price=Decimal(record["price"]),
        size=record["size"],
        exchange_timestamp_ns=record["timestamp_ns"],
    )


def _generate_one(spec: FixtureSpec) -> int:
    rng = random.Random(spec.seed)
    sensor = spec.sensor_factory()
    state = sensor.initial_state()

    mid_cents = 10_000  # $100.00
    sequence = 0
    written = 0
    with spec.output.open("w", encoding="utf-8", newline="\n") as f:
        for i in range(spec.n_events):
            ts_ns = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
            event: NBBOQuote | Trade | None = None
            if spec.needs_quote and (i % spec.quote_every == 0):
                quote, mid_cents = _quote(
                    rng=rng,
                    sequence=sequence,
                    ts_ns=ts_ns,
                    last_mid_cents=mid_cents,
                )
                sequence += 1
                event = quote
            elif spec.needs_trade and (i % spec.trade_every == 0):
                event = _trade(
                    rng=rng,
                    sequence=sequence,
                    ts_ns=ts_ns,
                    mid_cents=mid_cents,
                )
                sequence += 1
            if event is None:
                continue
            reading = sensor.update(event, state, params={})
            line: dict[str, Any] = {"input": _serialise_event(event)}
            if reading is None:
                line["expected_value"] = None
                line["expected_warm"] = None
            else:
                value = reading.value
                if isinstance(value, tuple):
                    line["expected_value"] = [float(v) for v in value]
                else:
                    line["expected_value"] = float(value)
                line["expected_warm"] = bool(reading.warm)
            f.write(json.dumps(line, sort_keys=True) + "\n")
            written += 1
    return written


# ── Mixed quote/trade synthesis (for VPIN, Kyle, Trade-Through) ────


@dataclass
class MixedFixtureSpec:
    output: Path
    sensor_factory: Callable[[], Any]
    n_events: int
    seed: int


def _generate_mixed(spec: MixedFixtureSpec) -> int:
    """Quote+trade interleaved synthesis for sensors needing both streams."""
    rng = random.Random(spec.seed)
    sensor = spec.sensor_factory()
    state = sensor.initial_state()

    mid_cents = 10_000
    sequence = 0
    written = 0
    with spec.output.open("w", encoding="utf-8", newline="\n") as f:
        for i in range(spec.n_events):
            ts_ns = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
            # 70% quote, 30% trade — both hit the sensor; the sensor
            # itself decides whether to emit on each kind.
            roll = rng.random()
            event: NBBOQuote | Trade
            if roll < 0.7:
                event, mid_cents = _quote(
                    rng=rng,
                    sequence=sequence,
                    ts_ns=ts_ns,
                    last_mid_cents=mid_cents,
                )
            else:
                event = _trade(
                    rng=rng,
                    sequence=sequence,
                    ts_ns=ts_ns,
                    mid_cents=mid_cents,
                )
            sequence += 1
            reading = sensor.update(event, state, params={})
            line: dict[str, Any] = {"input": _serialise_event(event)}
            if reading is None:
                line["expected_value"] = None
                line["expected_warm"] = None
            else:
                value = reading.value
                if isinstance(value, tuple):
                    line["expected_value"] = [float(v) for v in value]
                else:
                    line["expected_value"] = float(value)
                line["expected_warm"] = bool(reading.warm)
            f.write(json.dumps(line, sort_keys=True) + "\n")
            written += 1
    return written


# ── Fixture catalog ────────────────────────────────────────────────


def vpin_factory() -> VPIN50BucketSensor:
    return VPIN50BucketSensor(
        bucket_volume=1_000, window_buckets=20, min_buckets=5,
    )


def kyle_factory() -> KyleLambda60sSensor:
    return KyleLambda60sSensor(window_seconds=60, min_samples=10)


def hazard_factory() -> QuoteHazardRateSensor:
    return QuoteHazardRateSensor(window_seconds=5, min_samples=20)


def replenish_factory() -> QuoteReplenishAsymmetrySensor:
    return QuoteReplenishAsymmetrySensor(
        window_seconds=5, min_observations=20,
    )


def through_factory() -> TradeThroughRateSensor:
    return TradeThroughRateSensor(window_seconds=30, min_trades=10)


def _all_specs() -> tuple[tuple[str, Any], ...]:
    return (
        ("vpin_50bucket.jsonl", MixedFixtureSpec(
            output=_HERE / "vpin_50bucket.jsonl",
            sensor_factory=vpin_factory,
            n_events=600,
            seed=42,
        )),
        ("kyle_lambda_60s.jsonl", MixedFixtureSpec(
            output=_HERE / "kyle_lambda_60s.jsonl",
            sensor_factory=kyle_factory,
            n_events=600,
            seed=43,
        )),
        ("quote_hazard_rate.jsonl", FixtureSpec(
            output=_HERE / "quote_hazard_rate.jsonl",
            sensor_factory=hazard_factory,
            needs_quote=True,
            needs_trade=False,
            n_events=400,
            seed=44,
            quote_every=1,
            trade_every=10**6,
        )),
        ("quote_replenish_asymmetry.jsonl", FixtureSpec(
            output=_HERE / "quote_replenish_asymmetry.jsonl",
            sensor_factory=replenish_factory,
            needs_quote=True,
            needs_trade=False,
            n_events=400,
            seed=45,
            quote_every=1,
            trade_every=10**6,
        )),
        ("trade_through_rate.jsonl", MixedFixtureSpec(
            output=_HERE / "trade_through_rate.jsonl",
            sensor_factory=through_factory,
            n_events=600,
            seed=46,
        )),
    )


def main() -> None:
    for name, spec in _all_specs():
        if isinstance(spec, MixedFixtureSpec):
            n = _generate_mixed(spec)
        else:
            n = _generate_one(spec)
        print(f"  wrote {name}: {n} records")


if __name__ == "__main__":  # pragma: no cover
    main()


# Ensure ``tests.sensors.fixtures`` consumers can locate fixtures
# deterministically without re-importing this module.
def fixture_path(name: str) -> Path:
    """Absolute path to the named fixture inside this package."""
    return _HERE / name


__all__ = [
    "FixtureSpec",
    "MixedFixtureSpec",
    "SESSION_OPEN_NS",
    "deserialise_event",
    "fixture_path",
    "main",
]


# Used by tests to deserialise a fixture line + its expected fields.
def load_fixture(
    name: str,
) -> list[tuple[NBBOQuote | Trade, float | list[float] | None, bool | None]]:
    """Load a fixture into ``(event, expected_value, expected_warm)`` tuples."""
    path = fixture_path(name)
    out: list[
        tuple[NBBOQuote | Trade, float | list[float] | None, bool | None]
    ] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            event = deserialise_event(record["input"])
            out.append(
                (event, record["expected_value"], record["expected_warm"])
            )
    return out
